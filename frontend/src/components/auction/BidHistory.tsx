import { History } from "lucide-react";
import type { BidPage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { formatMoney, parseMoney } from "@/lib/money";
import { useNow } from "@/components/ui";

/** Bids in server order (server_seq), bidders only by their per-auction nickname. */
export function BidHistory({ bids, currency }: { bids: BidPage; currency: string }) {
  const now = useNow(15_000);
  if (bids.items.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-dashed border-line-strong px-5 py-8 text-sm text-ink-muted">
        <History className="size-5 text-ink-faint" aria-hidden />
        No bids yet. The first bid must be at least the starting price.
      </div>
    );
  }
  return (
    <ol className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
      {bids.items.map((bid, index) => (
        <li key={bid.bid_id} className={cn("flex items-center gap-4 px-5 py-3.5", index === 0 && "bg-brand-soft/40")}>
          <span className="tnum w-14 shrink-0 font-mono text-xs text-ink-faint" title="Server order">#{String(bid.server_seq).padStart(4, "0")}</span>
          <span className="flex min-w-0 flex-1 items-center gap-2">
            <span
              className="size-6 shrink-0 rounded-full"
              style={{ background: `conic-gradient(from ${parseInt(bid.bidder_alias.slice(-6), 16) % 360}deg, rgb(var(--brand)), rgb(var(--info)), rgb(var(--brand)))` }}
              aria-hidden
            />
            <span className="truncate font-mono text-[13px] text-ink-muted">{bid.bidder_alias}</span>
            {index === 0 && <span className="rounded-md bg-brand px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-on">Top</span>}
          </span>
          <span className="tnum text-sm font-semibold">{formatMoney(parseMoney(bid.amount), currency)}</span>
          <span className="hidden w-24 text-right text-xs text-ink-faint sm:block">{timeAgo(bid.accepted_at, now)}</span>
        </li>
      ))}
      {bids.total > bids.items.length && (
        <li className="px-5 py-3 text-center text-xs text-ink-faint">Showing the latest {bids.items.length} of {bids.total} bids</li>
      )}
    </ol>
  );
}
