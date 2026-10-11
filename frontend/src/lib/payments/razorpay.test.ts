import type { CheckoutSession } from "../api/types";
import {
  CHECKOUT_SCRIPT,
  CheckoutDismissed,
  loadRazorpay,
  payWithRazorpay,
  resetRazorpayLoader,
  type RazorpayConstructor,
  type RazorpayOptions,
} from "./razorpay";

const SESSION: CheckoutSession = {
  order_id: "0d000000-0000-4000-8000-000000000001",
  provider: "razorpay",
  key_id: "rzp_test_ZeoAuction01",
  provider_order_id: "order_ABC",
  amount: "1349.00",
  amount_minor: 134_900,
  currency: "INR",
  description: "Invoice ZA-202610-1 (test mode)",
  simulated_payment: null,
  test_mode: true,
};

function fakeCheckout(behave: (options: RazorpayOptions) => void): { ctor: RazorpayConstructor; seen: RazorpayOptions[] } {
  const seen: RazorpayOptions[] = [];
  class Fake {
    constructor(private readonly options: RazorpayOptions) {
      seen.push(options);
    }
    open() {
      behave(this.options);
    }
  }
  return { ctor: Fake as unknown as RazorpayConstructor, seen };
}

afterEach(() => {
  delete window.Razorpay;
  resetRazorpayLoader();
  document.head.querySelectorAll("script").forEach((s) => s.remove());
});

describe("Razorpay Checkout", () => {
  it("opens Checkout for the session and resolves with the signed result", async () => {
    const { ctor, seen } = fakeCheckout((o) =>
      o.handler({ razorpay_order_id: "order_ABC", razorpay_payment_id: "pay_1", razorpay_signature: "sig" }));
    const result = await payWithRazorpay(SESSION, { name: "Buyer Two", email: "buyer2@zeo.local" }, async () => ctor);
    expect(result).toEqual({ provider_order_id: "order_ABC", payment_id: "pay_1", signature: "sig" });
    expect(seen[0]).toMatchObject({
      key: "rzp_test_ZeoAuction01", amount: 134_900, currency: "INR", order_id: "order_ABC",
      name: "ZeoAuction (test mode)", prefill: { email: "buyer2@zeo.local" },
    });
  });

  it("rejects with CheckoutDismissed when the buyer closes it", async () => {
    const { ctor } = fakeCheckout((o) => o.modal.ondismiss());
    await expect(payWithRazorpay(SESSION, {}, async () => ctor)).rejects.toBeInstanceOf(CheckoutDismissed);
  });

  it("needs a key from the payment service", async () => {
    await expect(payWithRazorpay({ ...SESSION, key_id: null }, {})).rejects.toThrow("no Checkout key");
  });

  it("loads checkout.js once", async () => {
    const { ctor } = fakeCheckout(() => undefined);
    const first = loadRazorpay();
    const script = document.head.querySelector("script")!;
    expect(script.src).toBe(CHECKOUT_SCRIPT);
    window.Razorpay = ctor;
    script.onload?.(new Event("load"));
    await expect(first).resolves.toBe(ctor);
    await expect(loadRazorpay()).resolves.toBe(ctor);
  });

  it("reports a script that cannot load, and can retry", async () => {
    const failed = loadRazorpay();
    document.head.querySelector("script")!.onerror?.(new Event("error"));
    await expect(failed).rejects.toThrow("Can't reach Razorpay Checkout");
    const retry = loadRazorpay();
    const scripts = document.head.querySelectorAll("script");
    expect(scripts).toHaveLength(2);
    scripts[1].onload?.(new Event("load"));
    await expect(retry).rejects.toThrow("did not load");
  });
});
