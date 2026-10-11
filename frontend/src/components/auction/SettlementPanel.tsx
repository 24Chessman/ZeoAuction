import { useRef, useState } from "react";
import { Check, ChevronDown, CreditCard, FlaskConical, Landmark, Receipt, RefreshCw } from "lucide-react";
import { useAuth } from "@/app/auth";
import { orderApi, type Auction, type CheckoutSession, type LedgerEntry, type OrderState } from "@/lib/api";
import { cn } from "@/lib/cn";
import { describeError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { formatMoney, parseMoney } from "@/lib/money";
import { CheckoutDismissed, payWithRazorpay } from "@/lib/payments/razorpay";
import { policy } from "@/lib/policy";
import { useAsync } from "@/lib/useAsync";
import { Badge, Banner, Button, Card, CardBody, CardHeader, Divider, Modal, Table, Td, Th, type Tone, useToast } from "@/components/ui";

export const ORDER_LABEL: Record<OrderState, { label: string; tone: Tone }> = {
  INVOICED: { label: "Awaiting payment", tone: "info" },
  AUTHORIZED: { label: "Payment authorised", tone: "info" },
  AWAITING_CAPTURE_RETRY: { label: "Capturing payment", tone: "info" },
  CAPTURED: { label: "Captured", tone: "positive" },
  IN_ESCROW: { label: "Held in escrow", tone: "positive" },
  SHIPPED: { label: "Shipped", tone: "positive" },
  DISPUTED: { label: "Disputed", tone: "danger" },
  RELEASED: { label: "Released to seller", tone: "positive" },
  REFUNDED: { label: "Refunded", tone: "neutral" },
  CANCELLED: { label: "Cancelled", tone: "danger" },
};

function newKey(): string {
  return `pay-${crypto.randomUUID()}`;
}

/**
 * The order of a closed auction (ADR-0009): the winner pays the invoice (winning bid + flat fee)
 * in Razorpay Checkout, test mode; the seller and admins follow its state. Renders nothing for
 * anyone else, or before Payment has opened the order.
 */
export function SettlementPanel({ auction, onSettled }: { auction: Auction; onSettled?: () => void }) {
  const { user } = useAuth();
  const toast = useToast();
  const { data: order, error, setData, reload } = useAsync(
    () => (user ? orderApi.forAuction(auction.auction_id) : Promise.resolve(null)),
    [auction.auction_id, auction.state, user?.user_id],
  );
  const [paying, setPaying] = useState(false);
  const [simulated, setSimulated] = useState<CheckoutSession | null>(null);
  const [payError, setPayError] = useState<unknown>(null);
  const key = useRef(newKey());

  if (!user || !order) {
    return error ? <Banner tone="danger" title="Couldn't load the order">{describeError(error).message}</Banner> : null;
  }
  const isBuyer = user.user_id === order.buyer_id;
  const money = (value: string) => formatMoney(parseMoney(value), order.currency);
  const { label, tone } = ORDER_LABEL[order.state];

  async function confirm(session: CheckoutSession, payment: { provider_order_id: string; payment_id: string; signature: string }) {
    const updated = await orderApi.confirm(session.order_id, payment, key.current);
    setData(updated);
    key.current = newKey();
    if (updated.state === "IN_ESCROW") {
      toast({ tone: "positive", title: "Payment received", description: `${money(updated.total)} is held in simulated escrow.` });
      onSettled?.();
    }
  }

  async function pay() {
    if (!order || !user) return;
    setPaying(true);
    setPayError(null);
    try {
      const session = await orderApi.checkout(order.order_id);
      if (session.provider === "mock") {
        setSimulated(session); // finished by the simulated Checkout dialog below
        return;
      }
      const payment = await payWithRazorpay(session, { name: user.display_name, email: user.email });
      await confirm(session, payment);
    } catch (caught) {
      if (!(caught instanceof CheckoutDismissed)) setPayError(caught);
    } finally {
      setPaying(false);
    }
  }

  async function paySimulated() {
    if (!simulated?.simulated_payment) return;
    setPaying(true);
    try {
      await confirm(simulated, { provider_order_id: simulated.provider_order_id, ...simulated.simulated_payment });
      setSimulated(null);
    } catch (caught) {
      setPayError(caught);
      setSimulated(null);
    } finally {
      setPaying(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={isBuyer ? "Your purchase" : "Settlement"}
        description={`Invoice ${order.invoice.invoice_number}`}
        action={<Badge tone={tone} dot>{label}</Badge>}
      />
      <CardBody className="space-y-4 pt-4">
        <dl className="space-y-2 text-sm">
          <Row label="Winning bid" value={money(order.winning_bid_amount)} />
          <Row label={`Convenience fee (flat, ${order.fee_version})`} value={money(order.convenience_fee)} />
          <Divider />
          <Row label="Total" value={money(order.total)} strong />
        </dl>

        <OrderProgress state={order.state} />

        {user.user_id === order.seller_id && order.state !== "CANCELLED" && (
          <p className="rounded-xl bg-surface-2/60 px-3.5 py-3 text-sm text-ink-muted">
            You receive <span className="tnum font-medium text-ink">{money(order.winning_bid_amount)}</span> when escrow is released. The buyer pays the fee.
          </p>
        )}

        {order.state === "INVOICED" && isBuyer && (
          <div className="space-y-3">
            <p className="text-sm text-ink-muted">
              You won. Pay by <span className="font-medium text-ink">{formatDateTime(order.payment_due_at)}</span> to complete the purchase.
            </p>
            <Button className="w-full" size="lg" loading={paying} onClick={() => void pay()} icon={<CreditCard className="size-4" />}>
              Pay {money(order.total)}
            </Button>
            <TestPaymentHints />
          </div>
        )}
        {order.state === "INVOICED" && !isBuyer && (
          <p className="text-sm text-ink-muted">Waiting for the winner to pay (due {formatDateTime(order.payment_due_at)}).</p>
        )}
        {(order.state === "AUTHORIZED" || order.state === "AWAITING_CAPTURE_RETRY") && (
          <Banner tone="info" title="Payment authorised" action={
            <Button variant="secondary" size="sm" icon={<RefreshCw className="size-3.5" />} onClick={() => void reload()}>Refresh</Button>
          }>
            We're moving the payment into escrow. If the payment provider is slow, we retry automatically, and you can't be charged twice.
          </Banner>
        )}
        {order.state === "IN_ESCROW" && (
          <Banner tone="positive" title={isBuyer ? "Paid and held in escrow" : "The buyer has paid"}>
            {money(order.total)} is held in simulated escrow. The seller is paid when the buyer confirms receipt, or {policy.protectionDays} days after
            shipping if there's no dispute.
          </Banner>
        )}
        {order.state === "CANCELLED" && (
          <Banner tone="danger" title="Order cancelled">
            The payment wasn't completed (declined, or not made in time). The invoice was voided and nothing was charged.
          </Banner>
        )}
        {user.role === "ADMIN" && order.state !== "INVOICED" && order.state !== "CANCELLED" && (
          <LedgerPanel orderId={order.order_id} currency={order.currency} />
        )}
        {payError != null && (
          <Banner tone="danger" title={describeError(payError).title} live>
            {describeError(payError).hint ?? describeError(payError).message}
          </Banner>
        )}

        <p className="flex items-start gap-2 text-xs leading-relaxed text-ink-faint">
          <FlaskConical className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {order.notice} Payments run through Razorpay in test mode.
        </p>
      </CardBody>

      <Modal
        open={simulated !== null}
        onClose={() => setSimulated(null)}
        title="Simulated checkout"
        description="Mock mode stands in for Razorpay Checkout. No card is needed and no money moves."
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setSimulated(null)}>Cancel</Button>
            <Button loading={paying} onClick={() => void paySimulated()} icon={<Landmark className="size-4" />}>
              Pay {simulated ? formatMoney(parseMoney(simulated.amount), simulated.currency) : ""}
            </Button>
          </div>
        }
      >
        <div className="flex items-center gap-3 rounded-xl border border-line p-4 text-sm">
          <Receipt className="size-5 text-ink-faint" aria-hidden />
          <div>
            <p className="font-medium">{simulated?.description}</p>
            <p className="font-mono text-xs text-ink-faint">{simulated?.provider_order_id}</p>
          </div>
        </div>
      </Modal>
    </Card>
  );
}

const STEPS: Array<{ label: string; from: OrderState[] }> = [
  { label: "Invoiced", from: ["INVOICED", "AUTHORIZED", "AWAITING_CAPTURE_RETRY", "CAPTURED", "IN_ESCROW", "SHIPPED", "DISPUTED", "RELEASED", "REFUNDED"] },
  { label: "Authorised", from: ["AUTHORIZED", "AWAITING_CAPTURE_RETRY", "CAPTURED", "IN_ESCROW", "SHIPPED", "DISPUTED", "RELEASED", "REFUNDED"] },
  { label: "Captured", from: ["CAPTURED", "IN_ESCROW", "SHIPPED", "DISPUTED", "RELEASED", "REFUNDED"] },
  { label: "In escrow", from: ["IN_ESCROW", "SHIPPED", "DISPUTED", "RELEASED", "REFUNDED"] },
];

/** Where the order is on the settlement path (docs/state-machines.md, O1 and O1a). */
export function OrderProgress({ state }: { state: OrderState }) {
  if (state === "CANCELLED") return null;
  const reached = STEPS.filter((step) => step.from.includes(state)).length;
  return (
    <ol className="grid grid-cols-4 gap-1.5" aria-label="Settlement progress">
      {STEPS.map((step, index) => {
        const done = index < reached;
        return (
          <li key={step.label} className="min-w-0" aria-current={index === reached - 1 ? "step" : undefined}>
            <span className={cn("block h-1.5 rounded-full", done ? "bg-positive" : "bg-surface-2")} />
            <span className={cn("mt-1.5 flex items-center gap-1 truncate text-2xs", done ? "font-medium text-ink" : "text-ink-faint")}>
              {done && <Check className="size-3 shrink-0 text-positive" aria-hidden />}
              {step.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** Razorpay's published test credentials. Nothing real is charged in test mode. */
function TestPaymentHints() {
  return (
    <details className="group rounded-xl border border-line text-sm">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3.5 py-2.5 text-ink-muted hover:text-ink">
        <span className="flex items-center gap-2">
          <FlaskConical className="size-4" aria-hidden /> Test-mode payment details
        </span>
        <ChevronDown className="size-4 transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="space-y-2 border-t border-line px-3.5 py-3 text-[13px] leading-relaxed text-ink-muted">
        <p>Checkout runs in Razorpay test mode, so no real money moves. Pay with any of these:</p>
        <dl className="space-y-1.5">
          <TestRow label="Card" value="4111 1111 1111 1111" note="any future expiry and CVV; any OTP if asked" />
          <TestRow label="UPI" value="success@razorpay" note="failure@razorpay tries a decline" />
          <TestRow label="Netbanking" value="any bank" note="then pick Success on the test page" />
        </dl>
      </div>
    </details>
  );
}

function TestRow({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2">
      <dt className="w-20 shrink-0 text-ink-faint">{label}</dt>
      <dd>
        <span className="font-mono text-ink">{value}</span> <span className="text-ink-faint">· {note}</span>
      </dd>
    </div>
  );
}

const ENTRY_LABEL: Record<LedgerEntry["entry_type"], string> = {
  CAPTURE: "Capture", HOLD: "Hold", FEE_RETAIN: "Fee retained", RELEASE: "Release", REFUND: "Refund", COMPENSATION: "Compensation",
};

/** A ledger amount is signed: negative moves money out of custody. */
function signedCents(amount: string): number {
  return amount.startsWith("-") ? -parseMoney(amount.slice(1)) : parseMoney(amount);
}

/** The order's append-only escrow ledger (getOrderLedger, admins only). */
function LedgerPanel({ orderId, currency }: { orderId: string; currency: string }) {
  const { data, error } = useAsync(() => orderApi.ledger(orderId), [orderId]);
  if (error) return <p className="text-xs text-danger">The escrow ledger didn't load: {describeError(error).message}</p>;
  if (!data) return null;
  const custody = data.reduce((sum, row) => sum + signedCents(row.amount), 0);
  const money = (cents: number) => `${cents < 0 ? "−" : ""}${formatMoney(Math.abs(cents), currency)}`;
  return (
    <section aria-label="Escrow ledger" className="overflow-hidden rounded-xl border border-line">
      <p className="flex items-baseline justify-between px-4 py-2.5 text-[13px] font-semibold">
        Escrow ledger <span className="text-2xs font-normal text-ink-faint">append-only · admin view</span>
      </p>
      {data.length === 0 ? (
        <p className="border-t border-line px-4 py-3 text-xs text-ink-faint">No rows yet.</p>
      ) : (
        <Table>
          <thead>
            <tr><Th>Entry</Th><Th className="text-right">Amount</Th></tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr key={row.idempotency_key}>
                <Td>
                  <p className="font-medium">{ENTRY_LABEL[row.entry_type]}</p>
                  {row.provider_ref && <p className="font-mono text-2xs text-ink-faint">{row.provider_ref}</p>}
                </Td>
                <Td className="tnum text-right">{money(signedCents(row.amount))}</Td>
              </tr>
            ))}
            <tr>
              <Td className="font-semibold">Held for the seller</Td>
              <Td className="tnum text-right font-semibold">{money(custody)}</Td>
            </tr>
          </tbody>
        </Table>
      )}
    </section>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className={strong ? "font-semibold" : "text-ink-muted"}>{label}</dt>
      <dd className={strong ? "tnum text-lg font-semibold" : "tnum font-medium"}>{value}</dd>
    </div>
  );
}
