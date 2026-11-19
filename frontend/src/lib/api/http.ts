import { serviceUrls } from "../config";
import { ApiError } from "../errors";
import { session } from "./session";
import type { ErrorEnvelope, TokenPair } from "./types";

export type Service = Exclude<keyof typeof serviceUrls, "ws">;

export interface TransportRequest {
  service: Service;
  method: "GET" | "POST" | "PATCH" | "DELETE";
  path: string;
  headers: Record<string, string>;
  body?: string | FormData;
}

export interface TransportResponse {
  status: number;
  headers: Record<string, string>;
  body: unknown;
}

/** Sends one request. The real one is fetch; mock mode swaps in the in-browser simulation. */
export type Transport = (request: TransportRequest) => Promise<TransportResponse>;

export const fetchTransport: Transport = async (request) => {
  const response = await fetch(`${serviceUrls[request.service]}${request.path}`, {
    method: request.method,
    headers: request.headers,
    body: request.body,
  });
  const headers: Record<string, string> = {};
  response.headers.forEach((value, key) => {
    headers[key.toLowerCase()] = value;
  });
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      // If the backend or proxy returned HTML (e.g. 502 Bad Gateway from Render/Nginx),
      // sanitize it into a clean, friendly JSON envelope instead of leaking raw HTML to the UI.
      const isHtml = text.trim().startsWith("<") || text.includes("<html") || text.includes("<!DOCTYPE");
      let code = "SERVICE_UNAVAILABLE";
      let message = "Backend service is temporarily unavailable or warming up. Please retry shortly.";

      if (response.status === 404) {
        code = "NOT_FOUND";
        message = "The requested resource was not found.";
      } else if (response.status === 401 || response.status === 403) {
        code = "UNAUTHENTICATED";
        message = "Authentication required or access denied.";
      } else if (!isHtml && text.length < 200) {
        message = text;
        code = response.status >= 500 ? "SERVICE_UNAVAILABLE" : "INTERNAL_ERROR";
      }

      body = { code, message, details: null };
    }
  } else if (!response.ok) {
    const code = response.status >= 500 ? "SERVICE_UNAVAILABLE" : "INTERNAL_ERROR";
    const message =
      response.status === 502 || response.status === 503 || response.status === 504
        ? "Backend service is warming up or temporarily unreachable. Please retry in a few moments."
        : `Request failed with status ${response.status}`;
    body = { code, message, details: null };
  }
  return { status: response.status, headers, body };
};

let transport: Transport = fetchTransport;

export function setTransport(next: Transport): void {
  transport = next;
}

export interface RequestOptions {
  json?: unknown;
  form?: FormData;
  headers?: Record<string, string>;
  /** Attach the access token and refresh it once on a 401. */
  auth?: boolean;
}

export interface Result<T> {
  status: number;
  headers: Record<string, string>;
  data: T;
}

async function send(
  service: Service,
  method: TransportRequest["method"],
  path: string,
  options: RequestOptions,
): Promise<TransportResponse> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  let body: string | FormData | undefined;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  } else if (options.form) {
    body = options.form;
  }
  if (options.auth && session.accessToken) headers.Authorization = `Bearer ${session.accessToken}`;
  try {
    return await transport({ service, method, path, headers, body });
  } catch {
    throw new ApiError(0, {
      code: "NETWORK_ERROR",
      message: "Unable to reach the server. Please check your internet connection or try again shortly.",
      details: null,
    });
  }
}

function toError(response: TransportResponse): ApiError {
  const envelope = response.body as Partial<ErrorEnvelope> | null;
  let message = envelope?.message;

  // Never leak raw HTML strings into ApiError
  if (typeof message === "string" && (message.trim().startsWith("<") || message.includes("<html"))) {
    message = "Backend service is temporarily unavailable or starting up. Please retry in a moment.";
  }

  if (!message) {
    message =
      response.status >= 500
        ? "Backend service is temporarily unavailable or warming up. Please retry shortly."
        : `Request failed (${response.status})`;
  }

  const code =
    envelope?.code ??
    (response.status === 502 || response.status === 503 || response.status === 504
      ? "SERVICE_UNAVAILABLE"
      : response.status >= 500
      ? "INTERNAL_ERROR"
      : "REQUEST_ERROR");

  return new ApiError(response.status, {
    code,
    message,
    details: envelope?.details ?? null,
    request_id: envelope?.request_id ?? null,
  });
}

let refreshing: Promise<TokenPair> | null = null;

/**
 * Rotate the refresh token for a new access token. Concurrent callers share one request, so a
 * burst of 401s (or a TOKEN_STALE after a KYC decision) refreshes exactly once.
 */
export function refreshSession(): Promise<TokenPair> {
  if (!refreshing) {
    refreshing = (async () => {
      const token = session.refreshToken();
      if (!token) {
        throw new ApiError(401, { code: "UNAUTHENTICATED", message: "Not signed in", details: null });
      }
      const response = await send("auth", "POST", "/api/v1/auth/refresh", { json: { refresh_token: token } });
      if (response.status >= 400) {
        session.clear();
        throw toError(response);
      }
      const pair = response.body as TokenPair;
      session.establish(pair);
      return pair;
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

export async function request<T>(
  service: Service,
  method: TransportRequest["method"],
  path: string,
  options: RequestOptions = {},
): Promise<Result<T>> {
  let response = await send(service, method, path, options);
  // An expired token and a stale one (KYC status changed: details.reason = TOKEN_STALE) are
  // both 401 UNAUTHENTICATED; either way the fix is one refresh and one retry.
  if (response.status === 401 && options.auth && session.refreshToken()) {
    await refreshSession();
    response = await send(service, method, path, options);
  }
  if (response.status >= 400) throw toError(response);
  return { status: response.status, headers: response.headers, data: response.body as T };
}
