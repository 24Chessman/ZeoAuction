/**
 * Mock mode's way to real Razorpay test mode: the Vite dev server's bridge (dev/razorpayBridge.ts)
 * makes the provider calls with the key secret, which never reaches the browser. In a build, in
 * tests, or without rzp_test_ keys there is no bridge, and the mock server simulates Checkout.
 */

export interface CaptureResult {
  status: "captured" | "failed";
  payment_id: string;
  method: string | null;
  reason?: string | null;
}

export interface PaymentBridge {
  keyId: string;
  createOrder(body: { amount_minor: number; currency: string; receipt: string; notes?: Record<string, string> }): Promise<{ provider_order_id: string }>;
  capture(body: { provider_order_id: string; payment_id: string; signature: string; amount_minor: number }): Promise<CaptureResult>;
}

/** An error the bridge answered with, in the services' envelope. */
export class BridgeError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
  }
}

const BASE = "/__dev/razorpay";

async function post<T>(path: string, body: unknown, fetchImpl: typeof fetch): Promise<T> {
  let response: Response;
  try {
    response = await fetchImpl(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new BridgeError(503, "PAYMENT_PROVIDER_UNAVAILABLE", "The dev server's Razorpay bridge is unreachable");
  }
  const json = await response.json().catch(() => ({}));
  if (!response.ok) throw new BridgeError(response.status, json.code ?? "PAYMENT_PROVIDER_ERROR", json.message ?? `HTTP ${response.status}`);
  return json as T;
}

let probe: Promise<PaymentBridge | null> | null = null;

/** The bridge when the dev server has test keys, else null. Probed once per page load. */
export function paymentBridge(fetchImpl: typeof fetch = fetch): Promise<PaymentBridge | null> {
  if (!import.meta.env.DEV || import.meta.env.MODE === "test") return Promise.resolve(null);
  probe ??= fetchImpl(`${BASE}/config`)
    .then((r) => (r.ok ? r.json() : null))
    .then((config: { enabled?: boolean; key_id?: string } | null): PaymentBridge | null =>
      config?.enabled && config.key_id?.startsWith("rzp_test_")
        ? {
            keyId: config.key_id,
            createOrder: (body) => post("/orders", body, fetchImpl),
            capture: (body) => post("/capture", body, fetchImpl),
          }
        : null,
    )
    .catch(() => null);
  return probe!;
}
