import { History } from "lucide-react";
import type { BidPage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { formatMoney, parseMoney } from "@/lib/money";
import { useNow } from "@/components/ui";

/** One flat swatch per nickname, from the palette, so the list stays calm. */
const SWATCHES = ["bg-brand", "bg-gold", "bg-positive", "bg-info", "bg-danger", "bg-ink-muted"];

/** Bids in server order (server_seq), bidders only by their per-auction nickname. */
export function BidHistory({ bids, currency }: { bids: BidPage; currency: string }) {
  const now = useNow(15_000);
  if (bids.items.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-3xl border border-dashed border-line-strong bg-surface/60 px-5 py-8 text-sm text-ink-muted">
        <History className="size-5 text-ink-faint" aria-hidden />
        No bids yet. The first bid must be at least the starting price.
      </div>
    );
  }
  return (
    <ol className="divide-y divide-line overflow-hidden rounded-3xl border border-line bg-surface shadow-card">
      {bids.items.map((bid, index) => (
        <li key={bid.bid_id} className={cn("flex items-center gap-4 px-5 py-3.5", index === 0 && "bg-brand-soft/50")}>
          <span className="tnum w-14 shrink-0 font-mono text-xs text-ink-faint" title="Server order">#{String(bid.server_seq).padStart(4, "0")}</span>
          <span className="flex min-w-0 flex-1 items-center gap-2">
            <span
              className={cn("size-7 shrink-0 rounded-full ring-2 ring-surface", SWATCHES[(parseInt(bid.bidder_alias.slice(-6), 16) || 0) % SWATCHES.length])}
              aria-hidden
            />
            <span className="truncate font-mono text-[13px] text-ink-muted">{bid.bidder_alias}</span>
            {index === 0 && <span className="rounded-full bg-brand px-2 py-0.5 text-[11px] font-bold text-brand-on">Top bid</span>}
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
