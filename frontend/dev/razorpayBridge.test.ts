import { checkoutSignature, createBridge, signatureValid, testKeys } from "./razorpayBridge";

const keys = { keyId: "rzp_test_abc123", keySecret: "s3cret" };

function scripted(responses: Array<{ status: number; body: unknown }>) {
  const calls: Array<{ url: string; method: string; body: unknown }> = [];
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined });
    const next = responses.shift()!;
    return new Response(JSON.stringify(next.body), { status: next.status });
  }) as unknown as typeof fetch;
  return { calls, fetchImpl };
}

describe("razorpay dev bridge (ADR-0009)", () => {
  it("accepts only rzp_test_ keys", () => {
    expect(testKeys({ RAZORPAY_KEY_ID: "rzp_test_x", RAZORPAY_KEY_SECRET: "y" })).toEqual({ keyId: "rzp_test_x", keySecret: "y" });
    vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(testKeys({ RAZORPAY_KEY_ID: "rzp_live_x", RAZORPAY_KEY_SECRET: "y" })).toBeNull();
    expect(testKeys({ RAZORPAY_KEY_ID: "rzp_test_x" })).toBeNull();
  });

  it("verifies Checkout's HMAC signature", () => {
    const signature = checkoutSignature("s3cret", "order_1", "pay_1");
    expect(signatureValid("s3cret", "order_1", "pay_1", signature)).toBe(true);
    expect(signatureValid("s3cret", "order_1", "pay_2", signature)).toBe(false);
    expect(signatureValid("other", "order_1", "pay_1", signature)).toBe(false);
  });

  it("creates the provider order with manual capture", async () => {
    const { calls, fetchImpl } = scripted([{ status: 200, body: { id: "order_X" } }]);
    const bridge = createBridge(keys, fetchImpl);
    await expect(bridge.createOrder({ amount_minor: 709_900, currency: "INR", receipt: "ZA-202610-ABCDEF123456" })).resolves.toEqual({ provider_order_id: "order_X" });
    expect(calls[0]).toMatchObject({ url: "https://api.razorpay.com/v1/orders", method: "POST", body: { amount: 709_900, currency: "INR", payment_capture: 0 } });
  });

  it("captures an authorized payment after checking the signature and amount", async () => {
    const { calls, fetchImpl } = scripted([
      { status: 200, body: { id: "pay_1", order_id: "order_1", status: "authorized", amount: 709_900, currency: "INR", method: "card" } },
      { status: 200, body: { id: "pay_1", status: "captured", amount: 709_900 } },
    ]);
    const bridge = createBridge(keys, fetchImpl);
    const result = await bridge.capture({
      provider_order_id: "order_1", payment_id: "pay_1", signature: checkoutSignature("s3cret", "order_1", "pay_1"), amount_minor: 709_900,
    });
    expect(result).toMatchObject({ status: "captured", payment_id: "pay_1", method: "card" });
    expect(calls[1]).toMatchObject({ url: "https://api.razorpay.com/v1/payments/pay_1/capture", method: "POST", body: { amount: 709_900 } });
  });

  it("refuses a bad signature without calling Razorpay", async () => {
    const { calls, fetchImpl } = scripted([]);
    const bridge = createBridge(keys, fetchImpl);
    await expect(bridge.capture({ provider_order_id: "order_1", payment_id: "pay_1", signature: "nope", amount_minor: 100 }))
      .rejects.toMatchObject({ status: 400, code: "PAYMENT_SIGNATURE_INVALID" });
    expect(calls).toHaveLength(0);
  });

  it("treats an already captured payment as success and a failed one as a decline", async () => {
    const sig = checkoutSignature("s3cret", "order_1", "pay_1");
    const captured = scripted([{ status: 200, body: { id: "pay_1", order_id: "order_1", status: "captured", amount: 500, currency: "INR" } }]);
    await expect(createBridge(keys, captured.fetchImpl).capture({ provider_order_id: "order_1", payment_id: "pay_1", signature: sig, amount_minor: 500 }))
      .resolves.toMatchObject({ status: "captured" });
    const failed = scripted([{ status: 200, body: { id: "pay_1", order_id: "order_1", status: "failed", amount: 500, currency: "INR" } }]);
    await expect(createBridge(keys, failed.fetchImpl).capture({ provider_order_id: "order_1", payment_id: "pay_1", signature: sig, amount_minor: 500 }))
      .resolves.toMatchObject({ status: "failed" });
  });

  it("refuses a payment for a different amount", async () => {
    const sig = checkoutSignature("s3cret", "order_1", "pay_1");
    const { fetchImpl } = scripted([{ status: 200, body: { id: "pay_1", order_id: "order_1", status: "authorized", amount: 100, currency: "INR" } }]);
    await expect(createBridge(keys, fetchImpl).capture({ provider_order_id: "order_1", payment_id: "pay_1", signature: sig, amount_minor: 500 }))
      .rejects.toMatchObject({ code: "PAYMENT_SIGNATURE_INVALID" });
  });
});
