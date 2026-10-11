import { Link } from "react-router-dom";
import { Clock3, ShieldCheck } from "lucide-react";
import type { Auction } from "@/lib/api";
import { AuctionStateBadge, Countdown } from "@/components/ui";
import { formatDateTime, titleCase } from "@/lib/format";
import { formatMoney, parseMoney, type Cents } from "@/lib/money";
import { AuctionArt } from "./AuctionArt";

interface Props {
  auction: Auction;
  /** Current price when known (latest accepted bid); otherwise the starting price shows. */
  price?: Cents | null;
  bidCount?: number;
}

export function AuctionCard({ auction, price, bidCount }: Props) {
  const live = auction.state === "OPEN" || auction.state === "EXTENDED";
  const hasBids = price != null;
  const shown = price ?? parseMoney(auction.starting_price);

  return (
    <Link
      to={`/auctions/${auction.auction_id}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card transition-[box-shadow,transform,border-color] duration-200 hover:-translate-y-0.5 hover:border-line-strong hover:shadow-lift"
    >
      <div className="relative">
        <AuctionArt id={auction.auction_id} category={auction.category} className="aspect-[16/10] transition-transform duration-500 group-hover:scale-[1.03]" />
        <div className="absolute left-3 top-3 flex gap-1.5">
          <AuctionStateBadge state={auction.state} className="bg-surface/90 backdrop-blur" />
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <p className="text-2xs font-medium uppercase tracking-[0.1em] text-ink-faint">{titleCase(auction.category)}</p>
          <h3 className="mt-1 line-clamp-2 text-[15px] font-semibold leading-snug tracking-[-0.01em] group-hover:text-brand-ink">{auction.title}</h3>
        </div>
        <div className="mt-auto flex items-end justify-between gap-3">
          <div>
            <p className="text-xs text-ink-faint">{hasBids ? "Current bid" : "Starting at"}</p>
            <p className="tnum text-lg font-semibold tracking-[-0.02em]">{formatMoney(shown, auction.currency)}</p>
          </div>
          <div className="text-right text-xs text-ink-muted">
            {live && auction.closes_at ? (
              <span className="inline-flex items-center gap-1">
                <Clock3 className="size-3.5" aria-hidden />
                <Countdown to={auction.closes_at} urgentBelowMs={10 * 60_000} />
              </span>
            ) : auction.state === "SCHEDULED" ? (
              <span>Opens {formatDateTime(auction.opens_at)}</span>
            ) : null}
            {bidCount !== undefined && <p className="mt-0.5 text-ink-faint">{bidCount} {bidCount === 1 ? "bid" : "bids"}</p>}
          </div>
        </div>
        <div className="flex items-center gap-1.5 border-t border-line pt-3 text-xs text-ink-muted">
          <ShieldCheck className="size-3.5 text-positive" aria-hidden />
          Verified seller · fee shown before you bid
        </div>
      </div>
    </Link>
  );
}

export function AuctionCardSkeleton() {
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface">
      <div className="skeleton aspect-[16/10] rounded-none" />
      <div className="space-y-3 p-4">
        <div className="skeleton h-3 w-20" />
        <div className="skeleton h-4 w-3/4" />
        <div className="skeleton h-6 w-24" />
      </div>
    </div>
  );
}
