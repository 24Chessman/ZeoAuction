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
      body = { code: "INTERNAL_ERROR", message: text, details: null };
    }
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
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "Network request failed", details: null });
  }
}

function toError(response: TransportResponse): ApiError {
  const envelope = response.body as Partial<ErrorEnvelope> | null;
  return new ApiError(response.status, {
    code: envelope?.code ?? "INTERNAL_ERROR",
    message: envelope?.message ?? `Request failed (${response.status})`,
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
