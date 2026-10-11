import { Link } from "react-router-dom";
import { ArrowRight, Receipt } from "lucide-react";
import { auctionApi, orderApi, type Auction, type Order } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { formatMoney, parseMoney } from "@/lib/money";
import { useAsync } from "@/lib/useAsync";
import { Badge, Banner, Card, CardBody, CardHeader, EmptyState, Skeleton } from "@/components/ui";
import { AuctionArt } from "./AuctionArt";
import { ORDER_LABEL } from "./SettlementPanel";

interface Row {
  auction: Auction;
  order: Order;
}

/**
 * The caller's orders, as buyer or seller. Payment has no list endpoint yet, so this asks for the
 * order of every ended auction the browse page knows; the service answers only for the parties.
 */
async function loadOrders(userId: string): Promise<Row[]> {
  const ended = (await auctionApi.list()).filter((a) => a.state === "CLOSED" || a.state === "SETTLED");
  const rows = await Promise.all(
    ended.map(async (auction) => {
      const order = await orderApi.forAuction(auction.auction_id).catch(() => null);
      return order && (order.buyer_id === userId || order.seller_id === userId) ? { auction, order } : null;
    }),
  );
  return rows
    .filter((row): row is Row => row !== null)
    .sort((a, b) => Number(b.order.state === "INVOICED") - Number(a.order.state === "INVOICED") || Date.parse(b.order.created_at) - Date.parse(a.order.created_at));
}

export function OrdersCard({ userId }: { userId: string }) {
  const { data, error, loading } = useAsync(() => loadOrders(userId), [userId]);

  return (
    <Card>
      <CardHeader title="Orders" description="Auctions you've won or sold. Winners pay here within the payment window." />
      <CardBody>
        {error ? (
          <Banner tone="danger" title="Couldn't load your orders">{describeError(error).message}</Banner>
        ) : loading && !data ? (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full rounded-xl" />
            <Skeleton className="h-16 w-full rounded-xl" />
          </div>
        ) : !data?.length ? (
          <EmptyState icon={<Receipt className="size-5" />} title="No orders yet">
            When you win an auction, its invoice appears here.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line">
            {data.map(({ auction, order }) => {
              const buying = order.buyer_id === userId;
              const due = buying && order.state === "INVOICED";
              const { label, tone } = ORDER_LABEL[order.state];
              return (
                <li key={order.order_id}>
                  <Link to={`/auctions/${auction.auction_id}`} className="group flex items-center gap-3.5 px-4 py-3 hover:bg-surface-2/50">
                    <AuctionArt id={auction.auction_id} category={auction.category} size="sm" className="size-12 shrink-0 rounded-xl" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium group-hover:text-brand-ink">{auction.title}</p>
                      <p className="text-xs text-ink-faint">
                        {buying ? "You won" : "You sold"} · {order.invoice.invoice_number}
                        {due && order.payment_due_at ? ` · pay by ${formatDateTime(order.payment_due_at)}` : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <span className="tnum text-sm font-semibold">{formatMoney(parseMoney(buying ? order.total : order.winning_bid_amount), order.currency)}</span>
                      {due ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-brand-ink">
                          Pay now <ArrowRight className="size-3.5" aria-hidden />
                        </span>
                      ) : (
                        <Badge tone={tone} dot>{label}</Badge>
                      )}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
