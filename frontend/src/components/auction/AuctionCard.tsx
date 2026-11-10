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
      className="group flex flex-col overflow-hidden rounded-3xl border border-line bg-surface p-2 shadow-card transition-[box-shadow,transform,border-color] duration-300 hover:-translate-y-1 hover:border-line-strong hover:shadow-lift"
    >
      <div className="relative overflow-hidden rounded-[18px]">
        <AuctionArt id={auction.auction_id} category={auction.category} src={auction.images?.[0]?.url} className="aspect-[4/3] transition-transform duration-700 group-hover:scale-[1.05]" />
        <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/45 to-transparent" aria-hidden />
        <div className="absolute left-3 top-3 flex gap-1.5">
          <AuctionStateBadge state={auction.state} className="bg-surface/95 shadow-card backdrop-blur" />
        </div>
        {live && auction.closes_at && (
          <span className="absolute bottom-3 left-3 inline-flex items-center gap-1.5 rounded-full bg-black/50 px-2.5 py-1 text-xs font-semibold text-white backdrop-blur">
            <Clock3 className="size-3.5" aria-hidden />
            <Countdown to={auction.closes_at} />
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-4 px-3 pb-3 pt-4">
        <div>
          <p className="text-xs font-semibold text-ink-faint">{titleCase(auction.category)}</p>
          <h3 className="mt-1 line-clamp-2 text-lg font-semibold leading-snug tracking-[-0.015em] transition-colors group-hover:text-brand-ink">{auction.title}</h3>
        </div>
        <div className="mt-auto flex items-end justify-between gap-3 rounded-2xl bg-surface-2/70 px-3.5 py-3">
          <div>
            <p className="text-xs text-ink-faint">{hasBids ? "Current bid" : "Starting at"}</p>
            <p className="tnum font-display text-2xl font-bold tracking-[-0.03em]">{formatMoney(shown, auction.currency)}</p>
          </div>
          <div className="text-right text-xs text-ink-muted">
            {live && auction.closes_at ? (
              <span className="font-medium">
                Ends in <Countdown to={auction.closes_at} urgentBelowMs={10 * 60_000} className="font-semibold" />
              </span>
            ) : auction.state === "SCHEDULED" ? (
              <span>Opens {formatDateTime(auction.opens_at)}</span>
            ) : null}
            {bidCount !== undefined && <p className="mt-0.5 text-ink-faint">{bidCount} {bidCount === 1 ? "bid" : "bids"}</p>}
          </div>
        </div>
        <div className="flex items-center gap-1.5 px-1 text-xs text-ink-muted">
          <ShieldCheck className="size-3.5 text-positive" aria-hidden />
          Verified seller · fee shown before you bid
        </div>
      </div>
    </Link>
  );
}

export function AuctionCardSkeleton() {
  return (
    <div className="overflow-hidden rounded-3xl border border-line bg-surface p-2">
      <div className="skeleton aspect-[4/3] rounded-[18px]" />
      <div className="space-y-3 p-4">
        <div className="skeleton h-3 w-20" />
        <div className="skeleton h-4 w-3/4" />
        <div className="skeleton h-6 w-24" />
      </div>
    </div>
  );
}
