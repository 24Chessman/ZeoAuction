import type { CheckoutSession, LedgerEntry, Order } from "../api/types";
import { BridgeError, type CaptureResult } from "../payments/devBridge";
import { MockServer } from "./server";
import { ids } from "./seed";

/** The closed seed auction (tea set), won by buyer2 at 7,000.00. */
const CLOSED_AUCTION = "00000000-0000-4000-8000-000000000207";

function server(): MockServer {
  const mock = new MockServer(localStorage);
  mock.reset();
  mock.latency = [0, 0];
  return mock;
}

async function call(mock: MockServer, method: "GET" | "POST", path: string, token?: string, body?: unknown, headers: Record<string, string> = {}) {
  const response = await mock.handle({
    service: "payment", method, path,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return response as { status: number; body: unknown };
}

async function login(mock: MockServer, email: string): Promise<string> {
  const response = await mock.handle({
    service: "auth", method: "POST", path: "/api/v1/auth/login", headers: {},
    body: JSON.stringify({ email, password: "zeo-dev-password" }),
  });
  return (response.body as { access_token: string }).access_token;
}

describe("mock settlement (ADR-0009)", () => {
  it("opens an order for the winner of a closed auction, at the policy fee", async () => {
    const mock = server();
    const buyer = await login(mock, "buyer2@zeo.local");
    const response = await call(mock, "GET", `/api/v1/auctions/${CLOSED_AUCTION}/order`, buyer);
    expect(response.status).toBe(200);
    const order = response.body as Order;
    expect(order).toMatchObject({
      state: "INVOICED", buyer_id: ids.buyer2, winning_bid_amount: "7000.00", convenience_fee: "99.00",
      total: "7099.00", currency: "INR", fee_version: "2026-10-v1", provider: "mock", test_mode: true,
    });
    expect(order.invoice.invoice_number).toMatch(/^ZA-\d{6}-[0-9A-F]{12}$/);
    expect(order).not.toHaveProperty("provider_order_id");
  });

  it("keeps the order from other users and has none for open auctions", async () => {
    const mock = server();
    const loser = await login(mock, "buyer1@zeo.local");
    expect((await call(mock, "GET", `/api/v1/auctions/${CLOSED_AUCTION}/order`, loser)).status).toBe(403);
    const seller = await login(mock, "seller@zeo.local");
    expect((await call(mock, "GET", `/api/v1/auctions/${CLOSED_AUCTION}/order`, seller)).status).toBe(200);
    expect((await call(mock, "GET", "/api/v1/auctions/00000000-0000-4000-8000-000000000201/order", seller)).status).toBe(404);
  });

  it("pays through the simulated checkout, holds in escrow and settles the auction", async () => {
    const mock = server();
    const buyer = await login(mock, "buyer2@zeo.local");
    const order = (await call(mock, "GET", `/api/v1/auctions/${CLOSED_AUCTION}/order`, buyer)).body as Order;
    const checkout = await call(mock, "POST", `/api/v1/orders/${order.order_id}/checkout`, buyer);
    const session = checkout.body as CheckoutSession;
    expect(session).toMatchObject({ provider: "mock", amount: "7099.00", amount_minor: 709_900, currency: "INR" });
    expect((await call(mock, "POST", `/api/v1/orders/${order.order_id}/checkout`, buyer)).body).toEqual(session);

    const forged = await call(mock, "POST", `/api/v1/orders/${order.order_id}/payment`, buyer,
      { provider_order_id: session.provider_order_id, payment_id: "mock_pay_x", signature: "nope" }, { "Idempotency-Key": "pay-key-0001" });
    expect(forged.status).toBe(400);

    const paid = await call(mock, "POST", `/api/v1/orders/${order.order_id}/payment`, buyer,
      { provider_order_id: session.provider_order_id, ...session.simulated_payment }, { "Idempotency-Key": "pay-key-0001" });
    expect((paid.body as Order).state).toBe("IN_ESCROW");
    const auction = await mock.handle({ service: "auction", method: "GET", path: `/api/v1/auctions/${CLOSED_AUCTION}`, headers: {} });
    expect((auction.body as { state: string }).state).toBe("SETTLED");

    const again = await call(mock, "POST", `/api/v1/orders/${order.order_id}/checkout`, buyer);
    expect(again.status).toBe(409);
    expect((again.body as { code: string }).code).toBe("ORDER_NOT_PAYABLE");
  });

  it("only the winner may pay, with an idempotency key", async () => {
    const mock = server();
    const buyer = await login(mock, "buyer2@zeo.local");
    const seller = await login(mock, "seller@zeo.local");
    const order = (await call(mock, "GET", `/api/v1/auctions/${CLOSED_AUCTION}/order`, buyer)).body as Order;
    expect((await call(mock, "POST", `/api/v1/orders/${order.order_id}/checkout`, seller)).status).toBe(403);
    const session = (await call(mock, "POST", `/api/v1/orders/${order.order_id}/checkout`, buyer)).body as CheckoutSession;
    const keyless = await call(mock, "POST", `/api/v1/orders/${order.order_id}/payment`, buyer,
      { provider_order_id: session.provider_order_id, ...session.simulated_payment });
    expect(keyless.status).toBe(422);
    expect((await call(mock, "GET", "/api/v1/orders/unknown", buyer)).status).toBe(404);
  });

  it("writes CAPTURE, HOLD and FEE_RETAIN rows that only admins can read", async () => {
    const mock = server();
    const buyer = await login(mock, "buyer2@zeo.local");
    const order = (await call(mock, "GET", `/api/v1/auctions/${CLOSED_AUCTION}/order`, buyer)).body as Order;
    const session = (await call(mock, "POST", `/api/v1/orders/${order.order_id}/checkout`, buyer)).body as CheckoutSession;
    await call(mock, "POST", `/api/v1/orders/${order.order_id}/payment`, buyer,
      { provider_order_id: session.provider_order_id, ...session.simulated_payment }, { "Idempotency-Key": "pay-key-0002" });

    expect((await call(mock, "GET", `/api/v1/orders/${order.order_id}/ledger`, buyer)).status).toBe(403);
    const admin = await login(mock, "admin@zeo.local");
    const ledger = (await call(mock, "GET", `/api/v1/orders/${order.order_id}/ledger`, admin)).body as LedgerEntry[];
    expect(ledger.map((row) => [row.entry_type, row.amount])).toEqual([["CAPTURE", "7099.00"], ["HOLD", "0.00"], ["FEE_RETAIN", "-99.00"]]);
    expect(ledger[0].provider_ref).toBe(session.simulated_payment!.payment_id);
    expect((await call(mock, "GET", `/api/v1/orders/${order.order_id}`, buyer)).body).not.toHaveProperty("ledger");
  });

  it("seeds a second closed auction won by buyer1", async () => {
    const mock = server();
    const buyer = await login(mock, "buyer1@zeo.local");
    const order = (await call(mock, "GET", "/api/v1/auctions/00000000-0000-4000-8000-000000000208/order", buyer)).body as Order;
    expect(order).toMatchObject({ buyer_id: ids.buyer1, state: "INVOICED", total: "3099.00" });
  });

  describe("with the dev server's Razorpay bridge", () => {
    function bridged(capture: Partial<CaptureResult> | Error = {}) {
      const mock = server();
      const bridge = {
        keyId: "rzp_test_demo",
        createOrder: vi.fn(async () => ({ provider_order_id: "order_RZP123" })),
        capture: vi.fn(async () => {
          if (capture instanceof Error) throw capture;
          return { status: "captured" as const, payment_id: "pay_RZP456", method: "card", ...capture };
        }),
      };
      mock.payments = async () => bridge;
      return { mock, bridge };
    }

    async function checkout(mock: MockServer) {
      const buyer = await login(mock, "buyer2@zeo.local");
      const order = (await call(mock, "GET", `/api/v1/auctions/${CLOSED_AUCTION}/order`, buyer)).body as Order;
      const session = (await call(mock, "POST", `/api/v1/orders/${order.order_id}/checkout`, buyer)).body as CheckoutSession;
      return { buyer, order, session };
    }

    it("opens real Checkout with a Razorpay test order, once", async () => {
      const { mock, bridge } = bridged();
      const { buyer, order, session } = await checkout(mock);
      expect(session).toMatchObject({ provider: "razorpay", key_id: "rzp_test_demo", provider_order_id: "order_RZP123", amount_minor: 709_900, simulated_payment: null });
      expect(bridge.createOrder).toHaveBeenCalledWith(expect.objectContaining({ amount_minor: 709_900, currency: "INR", receipt: order.invoice.invoice_number }));
      await call(mock, "POST", `/api/v1/orders/${order.order_id}/checkout`, buyer);
      expect(bridge.createOrder).toHaveBeenCalledTimes(1);
    });

    it("captures through the bridge into escrow", async () => {
      const { mock, bridge } = bridged();
      const { buyer, order } = await checkout(mock);
      const paid = await call(mock, "POST", `/api/v1/orders/${order.order_id}/payment`, buyer,
        { provider_order_id: "order_RZP123", payment_id: "pay_RZP456", signature: "sig" }, { "Idempotency-Key": "pay-key-0003" });
      expect((paid.body as Order).state).toBe("IN_ESCROW");
      expect((paid.body as Order).provider).toBe("razorpay");
      expect(bridge.capture).toHaveBeenCalledWith({ provider_order_id: "order_RZP123", payment_id: "pay_RZP456", signature: "sig", amount_minor: 709_900 });
    });

    it("cancels the order when Razorpay reports the payment failed", async () => {
      const { mock } = bridged({ status: "failed" });
      const { buyer, order } = await checkout(mock);
      const paid = await call(mock, "POST", `/api/v1/orders/${order.order_id}/payment`, buyer,
        { provider_order_id: "order_RZP123", payment_id: "pay_RZP456", signature: "sig" }, { "Idempotency-Key": "pay-key-0004" });
      expect((paid.body as Order).state).toBe("CANCELLED");
    });

    it("passes the bridge's refusal through and leaves the order payable", async () => {
      const { mock } = bridged(new BridgeError(400, "PAYMENT_SIGNATURE_INVALID", "bad"));
      const { buyer, order } = await checkout(mock);
      const refused = await call(mock, "POST", `/api/v1/orders/${order.order_id}/payment`, buyer,
        { provider_order_id: "order_RZP123", payment_id: "pay_RZP456", signature: "forged" }, { "Idempotency-Key": "pay-key-0005" });
      expect(refused.status).toBe(400);
      expect((refused.body as { code: string }).code).toBe("PAYMENT_SIGNATURE_INVALID");
      expect(((await call(mock, "GET", `/api/v1/orders/${order.order_id}`, buyer)).body as Order).state).toBe("INVOICED");
    });

    it("reports the provider unavailable when the bridge goes away mid-order", async () => {
      const { mock } = bridged();
      const { buyer, order } = await checkout(mock);
      mock.payments = async () => null;
      const response = await call(mock, "POST", `/api/v1/orders/${order.order_id}/checkout`, buyer);
      expect(response.status).toBe(503);
      expect((response.body as { code: string }).code).toBe("PAYMENT_PROVIDER_UNAVAILABLE");
    });
  });

  it("migrates a Plan 3 mock store instead of discarding it", () => {
    const fresh = server();
    fresh.reset();
    const stored = JSON.parse(localStorage.getItem("zeo.mock.v1")!);
    delete stored.orders;
    stored.version = 1;
    localStorage.setItem("zeo.mock.v1", JSON.stringify(stored));
    const migrated = new MockServer(localStorage);
    expect(migrated.snapshot("00000000-0000-4000-8000-000000000201")).not.toBeNull();
  });
});
