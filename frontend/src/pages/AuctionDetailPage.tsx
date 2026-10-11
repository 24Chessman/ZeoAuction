import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BadgeCheck, CalendarClock, Hash, Landmark, Scale, ShieldCheck, Timer, Trophy } from "lucide-react";
import { useAuth } from "@/app/auth";
import { auctionApi, bidApi, type Auction, type BidPage } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatDateTime, titleCase } from "@/lib/format";
import { formatMoney, parseMoney } from "@/lib/money";
import { duration, policy } from "@/lib/policy";
import { photoFor } from "@/lib/photos";
import { useAsync } from "@/lib/useAsync";
import { AuctionStateBadge, Badge, Banner, ButtonLink, Skeleton } from "@/components/ui";
import { AuctionArt } from "@/components/auction/AuctionArt";
import { BidHistory } from "@/components/auction/BidHistory";
import { BidPanel } from "@/components/auction/BidPanel";
import { ReconnectBanner } from "@/components/auction/ReconnectBanner";
import { useAuctionLive } from "@/components/auction/useAuctionLive";
import { SellerAuctionActions } from "@/components/auction/SellerAuctionActions";
import { SettlementPanel } from "@/components/auction/SettlementPanel";

export function AuctionDetailPage() {
  const { auctionId = "" } = useParams();
  const { data, error, loading } = useAsync(
    () => Promise.all([auctionApi.get(auctionId), bidApi.list(auctionId, 1, 20)]),
    [auctionId],
  );

  if (loading && !data) return <DetailSkeleton />;
  if (error || !data) {
    const copy = describeError(error);
    return (
      <div className="mx-auto max-w-page px-4 py-16 sm:px-6">
        <Banner tone="danger" title={copy.code === "NOT_FOUND" ? "This auction doesn't exist" : copy.title}>
          {copy.hint ?? copy.message}
        </Banner>
        <ButtonLink to="/auctions" variant="secondary" className="mt-6" icon={<ArrowLeft className="size-4" />}>
          All auctions
        </ButtonLink>
      </div>
    );
  }
  return <AuctionDetail key={auctionId} auction={data[0]} bids={data[1]} />;
}

function AuctionDetail({ auction: initial, bids: initialBids }: { auction: Auction; bids: BidPage }) {
  const state = useAuctionLive(initial, initialBids);
  const { auction, bids } = state;
  const { user } = useAuth();
  const isSeller = user?.user_id === auction.seller_id;
  const reserve = auction.reserve_price ? parseMoney(auction.reserve_price) : null;
  const reserveMet = reserve === null || (state.live.price !== null && state.live.price >= reserve);
  const extended = auction.extension_count > 0;
  const winning = auction.winning_bid_id ? bids.items.find((b) => b.bid_id === auction.winning_bid_id) : null;
  const photo = photoFor(auction.auction_id, auction.category);

  return (
    <div className="mx-auto max-w-page px-4 pb-20 pt-6 sm:px-6">
      <Link to="/auctions" className="inline-flex items-center gap-1.5 rounded-lg text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden /> All auctions
      </Link>

      <div className="mt-4">
        <ReconnectBanner />
      </div>

      {/* Three blocks so the bid panel follows the title on phones and sits beside everything on desktop. */}
      <div className="mt-4 grid gap-8 lg:grid-cols-[minmax(0,1fr)_400px] lg:gap-x-10">
        <div className="min-w-0 space-y-8 lg:col-start-1">
          <figure>
            <div className="overflow-hidden rounded-3xl border border-line">
              <AuctionArt id={auction.auction_id} category={auction.category} size="lg" priority className="aspect-[16/9]" />
            </div>
            <figcaption className="mt-2 text-xs text-ink-faint">
              Stock photo by{" "}
              <a href={photo.source} target="_blank" rel="noreferrer" className="underline decoration-line-strong underline-offset-2 hover:text-ink">
                {photo.photographer} on Pexels
              </a>
              , for illustration. It isn't a photo of this item.
            </figcaption>
          </figure>

          <header>
            <div className="flex flex-wrap items-center gap-2">
              <AuctionStateBadge state={auction.state} />
              <Badge tone="neutral">{titleCase(auction.category)}</Badge>
              {reserve !== null && (
                <Badge tone={reserveMet ? "positive" : "neutral"}>{reserveMet ? "Reserve met" : "Reserve not met"}</Badge>
              )}
              {extended && <Badge tone="live" icon={<Timer className="size-3" aria-hidden />}>Extended ×{auction.extension_count}</Badge>}
            </div>
            <h1 className="mt-4 text-[30px] font-semibold leading-[1.1] tracking-[-0.035em] sm:text-[40px]">{auction.title}</h1>
            <p className="mt-4 max-w-3xl whitespace-pre-line text-[15px] leading-relaxed text-ink-muted">{auction.description || "No description."}</p>
          </header>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-24 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:self-start">
          {(auction.state === "CLOSED" || auction.state === "SETTLED") && auction.winning_bid_id && (
            <SettlementPanel auction={auction} onSettled={() => void state.refresh()} />
          )}
          <BidPanel state={state} />
        </aside>

        <div className="min-w-0 space-y-8 lg:col-start-1">
          {(isSeller || user?.role === "ADMIN") && <SellerAuctionActions auction={auction} onChange={() => void state.refresh()} />}

          {(auction.state === "CLOSED" || auction.state === "SETTLED") && (
            <Banner tone={winning ? "positive" : "info"} title={winning ? "Auction closed with a winner" : "Auction closed without bids"}>
              {winning ? (
                <>
                  Won by <span className="font-mono">{winning.bidder_alias}</span> at {formatMoney(parseMoney(winning.amount), auction.currency)}. The winner pays
                  the bid plus the flat fee in Razorpay Checkout (test mode), and it's held in simulated escrow until delivery is confirmed.
                </>
              ) : (
                "No order is created when an auction ends without bids."
              )}
            </Banner>
          )}

          {/* Safeguards: visible at the moment they matter. */}
          <section aria-labelledby="safeguards">
            <h2 id="safeguards" className="text-lg font-semibold tracking-[-0.02em]">How this auction protects you</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Safeguard icon={<BadgeCheck className="size-5" />} title="Verified seller">
                Only sellers an administrator has verified can list. Their identity documents are never shown to buyers.
              </Safeguard>
              <Safeguard icon={<Landmark className="size-5" />} title={`${policy.protectionDays}-day protection window`}>
                Your payment waits in escrow (simulated) until you confirm receipt, or {policy.protectionDays} days after shipping with no dispute.
              </Safeguard>
              <Safeguard icon={<Hash className="size-5" />} title="Server-ordered bids">
                Every accepted bid gets the next sequence number, so equal bids always resolve the same way.
              </Safeguard>
              <Safeguard icon={<Timer className="size-5" />} title="No sniping">
                A bid in the final {duration(auction.guard_interval_seconds)} extends the close by {duration(auction.extension_seconds)}, up to {auction.max_extensions} times.
              </Safeguard>
            </div>
          </section>

          <section aria-labelledby="history">
            <div className="flex items-end justify-between">
              <h2 id="history" className="text-lg font-semibold tracking-[-0.02em]">Bid history</h2>
              <p className="text-sm text-ink-faint">{bids.total} {bids.total === 1 ? "bid" : "bids"} · bidders shown by nickname</p>
            </div>
            <div className="mt-4">
              <BidHistory bids={bids} currency={auction.currency} />
            </div>
          </section>

          <section aria-labelledby="details" className="rounded-2xl border border-line bg-surface p-5">
            <h2 id="details" className="text-[15px] font-semibold">Listing details</h2>
            <dl className="mt-3 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <Detail icon={<CalendarClock className="size-4" />} label="Opens" value={formatDateTime(auction.opens_at)} />
              <Detail icon={<CalendarClock className="size-4" />} label={extended ? "Closes (extended)" : "Closes"} value={formatDateTime(auction.closes_at)} />
              {extended && <Detail icon={<Timer className="size-4" />} label="Originally closed" value={formatDateTime(auction.original_closes_at)} />}
              <Detail icon={<Scale className="size-4" />} label="Starting price" value={formatMoney(parseMoney(auction.starting_price), auction.currency)} />
              <Detail icon={<ShieldCheck className="size-4" />} label="Reserve" value={reserve === null ? "No reserve" : reserveMet ? "Met" : "Not met yet"} />
              {winning && <Detail icon={<Trophy className="size-4" />} label="Winning bid" value={`#${winning.server_seq} · ${winning.bidder_alias}`} />}
            </dl>
          </section>
        </div>
      </div>
    </div>
  );
}

function Safeguard({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3.5 rounded-2xl border border-line bg-surface p-4">
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-positive-soft text-positive">{icon}</span>
      <div>
        <p className="text-sm font-semibold">{title}</p>
        <p className="mt-0.5 text-[13px] leading-relaxed text-ink-muted">{children}</p>
      </div>
    </div>
  );
}

function Detail({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-ink-faint">{icon}</span>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="ml-auto font-medium sm:ml-0">{value}</dd>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="mx-auto grid max-w-page gap-10 px-4 py-10 sm:px-6 lg:grid-cols-[minmax(0,1fr)_400px]">
      <div className="space-y-6">
        <Skeleton className="aspect-[16/9] w-full rounded-3xl" />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-20 w-full" />
      </div>
      <Skeleton className="h-[520px] w-full rounded-3xl" />
    </div>
  );
}
