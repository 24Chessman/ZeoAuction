import type { CheckoutSession, PaymentConfirmation } from "../api/types";

/**
 * Razorpay Checkout (ADR-0009), test mode only: the payment service hands out a rzp_test_ key
 * and refuses live keys. Checkout authorises the payment; our server verifies the signature it
 * returns and captures into simulated escrow. Card details never touch our code.
 */

export const CHECKOUT_SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

interface RazorpayResponse {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
}

export interface RazorpayOptions {
  key: string;
  amount: number;
  currency: string;
  order_id: string;
  name: string;
  description: string;
  prefill?: { name?: string; email?: string };
  notes?: Record<string, string>;
  theme?: { color?: string };
  handler: (response: RazorpayResponse) => void;
  modal: { ondismiss: () => void };
}

export type RazorpayConstructor = new (options: RazorpayOptions) => { open: () => void };

declare global {
  interface Window {
    Razorpay?: RazorpayConstructor;
  }
}

/** The buyer closed Checkout without paying. Nothing was charged. */
export class CheckoutDismissed extends Error {
  constructor() {
    super("Checkout was closed before paying");
    this.name = "CheckoutDismissed";
  }
}

let loading: Promise<RazorpayConstructor> | null = null;

/** Load checkout.js once. */
export function loadRazorpay(doc: Document = document): Promise<RazorpayConstructor> {
  if (window.Razorpay) return Promise.resolve(window.Razorpay);
  loading ??= new Promise<RazorpayConstructor>((resolve, reject) => {
    const script = doc.createElement("script");
    script.src = CHECKOUT_SCRIPT;
    script.async = true;
    script.onload = () => (window.Razorpay ? resolve(window.Razorpay) : reject(new Error("Razorpay Checkout did not load")));
    script.onerror = () => {
      loading = null;
      reject(new Error("Can't reach Razorpay Checkout. Check your connection and try again."));
    };
    doc.head.appendChild(script);
  });
  return loading;
}

/** Open Checkout for a session and resolve with the signed result for POST /orders/{id}/payment. */
export async function payWithRazorpay(
  session: CheckoutSession,
  prefill: { name?: string; email?: string },
  load: () => Promise<RazorpayConstructor> = loadRazorpay,
): Promise<PaymentConfirmation> {
  if (!session.key_id) throw new Error("The payment service sent no Checkout key");
  const Razorpay = await load();
  return new Promise<PaymentConfirmation>((resolve, reject) => {
    const checkout = new Razorpay({
      key: session.key_id!,
      amount: session.amount_minor,
      currency: session.currency,
      order_id: session.provider_order_id,
      name: "ZeoAuction (test mode)",
      description: session.description,
      prefill,
      notes: { order_id: session.order_id },
      handler: (response) =>
        resolve({
          provider_order_id: response.razorpay_order_id,
          payment_id: response.razorpay_payment_id,
          signature: response.razorpay_signature,
        }),
      modal: { ondismiss: () => reject(new CheckoutDismissed()) },
    });
    checkout.open();
  });
}

/** Test hook: forget a cached loader. */
export function resetRazorpayLoader(): void {
  loading = null;
}
