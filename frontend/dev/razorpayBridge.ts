import { createHmac, timingSafeEqual } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

/**
 * Razorpay test mode for mock mode (ADR-0009), dev server only.
 *
 * Mock mode has no payment service, and Checkout needs a provider order created with the key
 * secret. This plugin plays the payment service's provider calls inside the Vite dev server, so the
 * secret stays in Node and never reaches the bundle. The browser's mock server calls it to:
 *
 *   GET  /__dev/razorpay/config   -> { enabled, key_id }        (public key id only)
 *   POST /__dev/razorpay/orders   -> POST /v1/orders, payment_capture 0 (manual capture)
 *   POST /__dev/razorpay/capture  -> verify the Checkout signature, then POST /payments/{id}/capture
 *
 * The same calls as services/payment-escrow/app/payment_port/razorpay_adapter.py. Like the adapter,
 * it refuses anything but an rzp_test_ key.
 */

const API = "https://api.razorpay.com/v1";
const RECEIPT_MAX = 40;

export interface RazorpayKeys {
  keyId: string;
  keySecret: string;
}

/** Keys from the repository's .env, or null when absent or not test-mode keys. */
export function testKeys(env: Record<string, string | undefined>): RazorpayKeys | null {
  const keyId = env.RAZORPAY_KEY_ID?.trim() ?? "";
  const keySecret = env.RAZORPAY_KEY_SECRET?.trim() ?? "";
  if (!keyId || !keySecret) return null;
  if (!keyId.startsWith("rzp_test_")) {
    console.warn("[razorpay] RAZORPAY_KEY_ID is not a rzp_test_ key; refusing it, so mock mode keeps the simulated Checkout");
    return null;
  }
  return { keyId, keySecret };
}

/** Checkout's signature: HMAC-SHA256(order_id + "|" + payment_id) with the key secret. */
export function checkoutSignature(secret: string, providerOrderId: string, paymentId: string): string {
  return createHmac("sha256", secret).update(`${providerOrderId}|${paymentId}`).digest("hex");
}

export function signatureValid(secret: string, providerOrderId: string, paymentId: string, signature: string): boolean {
  const expected = Buffer.from(checkoutSignature(secret, providerOrderId, paymentId));
  const given = Buffer.from(String(signature ?? ""));
  return expected.length === given.length && timingSafeEqual(expected, given);
}

type Fetch = typeof fetch;

interface RazorpayPayment {
  id: string;
  order_id: string;
  status: string;
  amount: number;
  currency: string;
  method?: string;
  error_description?: string | null;
}

class BridgeError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
  }
}

export function createBridge(keys: RazorpayKeys, fetchImpl: Fetch = fetch) {
  const auth = `Basic ${Buffer.from(`${keys.keyId}:${keys.keySecret}`).toString("base64")}`;

  async function call<T>(method: string, path: string, body?: unknown): Promise<{ status: number; json: T }> {
    const response = await fetchImpl(`${API}${path}`, {
      method,
      headers: { Authorization: auth, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { status: response.status, json: (await response.json().catch(() => ({}))) as T };
  }

  function providerError(json: unknown, status: number): string {
    const error = (json as { error?: { code?: string; description?: string } }).error;
    return error ? `${error.code ?? status}: ${error.description ?? ""}`.trim() : `HTTP ${status}`;
  }

  return {
    config: () => ({ enabled: true, key_id: keys.keyId }),

    async createOrder(body: { amount_minor: number; currency: string; receipt: string; notes?: Record<string, string> }) {
      if (!Number.isInteger(body.amount_minor) || body.amount_minor < 100) {
        throw new BridgeError(422, "VALIDATION_ERROR", "amount_minor must be a whole number of paise, at least 100");
      }
      const { status, json } = await call<{ id?: string }>("POST", "/orders", {
        amount: body.amount_minor,
        currency: body.currency,
        receipt: String(body.receipt).slice(0, RECEIPT_MAX),
        notes: body.notes ?? {},
        payment_capture: 0, // manual capture: the payment stays authorized until we capture it
      });
      if (status >= 400 || !json.id) throw new BridgeError(502, "PAYMENT_PROVIDER_ERROR", `Razorpay refused the order: ${providerError(json, status)}`);
      return { provider_order_id: json.id };
    },

    /** Verify Checkout's signature, then capture into (simulated) escrow. A repeat is a no-op success. */
    async capture(body: { provider_order_id: string; payment_id: string; signature: string; amount_minor: number }) {
      if (!signatureValid(keys.keySecret, body.provider_order_id, body.payment_id, body.signature)) {
        throw new BridgeError(400, "PAYMENT_SIGNATURE_INVALID", "The payment signature is invalid");
      }
      const fetched = await call<RazorpayPayment>("GET", `/payments/${encodeURIComponent(body.payment_id)}`);
      if (fetched.status >= 400) throw new BridgeError(502, "PAYMENT_PROVIDER_ERROR", `Can't read the payment: ${providerError(fetched.json, fetched.status)}`);
      const payment = fetched.json;
      if (payment.order_id !== body.provider_order_id || payment.amount !== body.amount_minor) {
        throw new BridgeError(400, "PAYMENT_SIGNATURE_INVALID", "The payment doesn't belong to this order");
      }
      if (payment.status === "captured") return { status: "captured", payment_id: payment.id, method: payment.method ?? null };
      if (payment.status === "failed") return { status: "failed", payment_id: payment.id, method: payment.method ?? null, reason: payment.error_description ?? null };
      const captured = await call<RazorpayPayment>("POST", `/payments/${encodeURIComponent(payment.id)}/capture`, {
        amount: payment.amount,
        currency: payment.currency,
      });
      if (captured.status >= 400 || captured.json.status !== "captured") {
        throw new BridgeError(502, "PAYMENT_PROVIDER_ERROR", `Capture refused: ${providerError(captured.json, captured.status)}`);
      }
      return { status: "captured", payment_id: payment.id, method: payment.method ?? null };
    },
  };
}

function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new BridgeError(400, "VALIDATION_ERROR", "Body must be JSON"));
      }
    });
    req.on("error", reject);
  });
}

function send(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}

/** The Vite plugin. Without test keys, /config reports disabled and mock mode simulates Checkout. */
export function razorpayDevBridge(env: Record<string, string | undefined>): Plugin {
  const keys = testKeys(env);
  const bridge = keys ? createBridge(keys) : null;
  return {
    name: "zeo-razorpay-dev-bridge",
    apply: "serve",
    configureServer(server) {
      server.config.logger.info(
        bridge ? `  Razorpay test mode: on (${keys!.keyId.slice(0, 13)}…), Checkout is real in mock mode` : "  Razorpay test mode: off (no rzp_test_ keys in ../.env), Checkout is simulated",
      );
      server.middlewares.use("/__dev/razorpay", async (req, res) => {
        try {
          if (req.method === "GET" && req.url === "/config") return send(res, 200, bridge?.config() ?? { enabled: false, key_id: null });
          if (!bridge) throw new BridgeError(503, "PAYMENT_PROVIDER_UNAVAILABLE", "Razorpay test keys are not configured");
          if (req.method === "POST" && req.url === "/orders") return send(res, 200, await bridge.createOrder((await readJson(req)) as never));
          if (req.method === "POST" && req.url === "/capture") return send(res, 200, await bridge.capture((await readJson(req)) as never));
          throw new BridgeError(404, "NOT_FOUND", `No route ${req.method} ${req.url}`);
        } catch (error) {
          if (error instanceof BridgeError) return send(res, error.status, { code: error.code, message: error.message, details: null });
          server.config.logger.error(`[razorpay] ${(error as Error).message}`);
          return send(res, 502, { code: "PAYMENT_PROVIDER_ERROR", message: "Can't reach Razorpay. Check your connection and try again.", details: null });
        }
      });
    },
  };
}
