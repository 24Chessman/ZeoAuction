import type { ReactNode } from "react";
import { ArrowRight, ArrowUpRight, BadgeCheck, EyeOff, Gavel, Hash, Landmark, ReceiptIndianRupee, ShieldCheck, Timer } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { ButtonLink } from "@/components/ui";
import { categoryIcon } from "@/components/auction/AuctionArt";
import { cn } from "@/lib/cn";
import { formatMoney } from "@/lib/money";
import { photoFor } from "@/lib/photos";
import { duration, policy } from "@/lib/policy";
import { auctionApi, bidApi, type Auction } from "@/lib/api";
import { parseMoney, type Cents } from "@/lib/money";
import { useAsync } from "@/lib/useAsync";
import { RecommendedFeedSection } from "@/components/recommendations/RecommendedFeedSection";

interface Row {
  auction: Auction;
  price: Cents | null;
  bids: number;
}

async function loadLandingAuctions(): Promise<Row[]> {
  const auctions = (await auctionApi.list()).filter((a) => a.state !== "DRAFT" && a.state !== "CANCELLED");
  return Promise.all(
    auctions.map(async (auction) => {
      try {
        const page = await bidApi.list(auction.auction_id, 1, 1);
        return { auction, price: page.items[0] ? parseMoney(page.items[0].amount) : null, bids: page.total };
      } catch {
        return { auction, price: null, bids: 0 };
      }
    }),
  );
}

const fee = formatMoney(policy.feeCents, policy.currency);
const CATEGORIES = ["watches", "cameras", "jewelry", "music", "furniture", "books", "art", "electronics"];

export function LandingPage() {
  const { status } = useAuth();
  const signedIn = status === "signed-in";
  const { data } = useAsync(loadLandingAuctions, []);

  return (
    <div className="overflow-x-clip">
      {/* Hero */}
      <section className="bg-midnight relative text-white">
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgb(255_255_255/0.04)_1px,transparent_1px),linear-gradient(90deg,rgb(255_255_255/0.04)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:radial-gradient(70%_60%_at_50%_40%,black,transparent)]" aria-hidden />
        <div className="relative mx-auto grid max-w-page items-center gap-14 px-4 pb-24 pt-16 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pb-32 lg:pt-24">
          <div className="animate-fade-up">
            <p className="inline-flex items-center gap-2.5 rounded-full border border-white/15 bg-white/[0.06] py-1.5 pl-2 pr-4 text-[13px] font-medium text-white/80 backdrop-blur">
              <span className="relative flex size-2.5 items-center justify-center">
                <span className="absolute inline-flex size-full animate-live-ping rounded-full bg-brand opacity-70" />
                <span className="relative inline-flex size-2 rounded-full bg-brand" />
              </span>
              Live auctions with buyer-protected escrow
            </p>
            <h1 className="mt-7 text-display font-semibold">
              Bid live.
              <br />
              Know it's <span className="bg-gradient-to-r from-[#ff8a5c] via-[#ffb547] to-[#ffd166] bg-clip-text text-transparent">safe.</span>
            </h1>
            <p className="mt-7 max-w-xl text-lg leading-relaxed text-white/70">
              See who's selling, exactly what you'll pay, and where your money waits until the item arrives, all before you place a single bid.
            </p>
            <div className="mt-10 flex flex-wrap items-center gap-3">
              <ButtonLink to="/auctions" size="lg" iconRight={<ArrowRight className="size-[18px]" />}>
                Browse live auctions
              </ButtonLink>
              {!signedIn && (
                <Link to="/register" className="inline-flex h-[52px] items-center rounded-full border border-white/20 px-7 text-[15px] font-semibold text-white transition-colors hover:bg-white/10">
                  Create a free account
                </Link>
              )}
            </div>

            <dl className="mt-14 grid max-w-xl grid-cols-3 gap-3">
              <Stat value={fee} label="flat fee, only if you win" />
              <Stat value={`${policy.protectionDays} days`} label="buyer protection" />
              <Stat value={`+${duration(policy.extensionSeconds)}`} label="per last-moment bid" />
            </dl>
          </div>

          <HeroCollage />
        </div>
      </section>

      {/* Category strip */}
      <section className="border-b border-line bg-surface" aria-label="Categories">
        <div className="relative overflow-hidden py-5 [mask-image:linear-gradient(90deg,transparent,black_8%,black_92%,transparent)]">
          <div className="flex w-max animate-marquee gap-3 hover:[animation-play-state:paused]">
            {[...CATEGORIES, ...CATEGORIES].map((category, index) => {
              const Icon = categoryIcon(category);
              const photo = photoFor("", category);
              return (
                <Link
                  key={`${category}-${index}`}
                  to="/auctions"
                  aria-hidden={index >= CATEGORIES.length || undefined}
                  tabIndex={index >= CATEGORIES.length ? -1 : undefined}
                  className="group flex items-center gap-3 rounded-full border border-line bg-canvas py-1.5 pl-1.5 pr-5 transition-colors hover:border-brand/40"
                >
                  <img src={photo.src} alt="" className="size-10 rounded-full object-cover" loading="lazy" />
                  <Icon className="size-4 text-ink-faint transition-colors group-hover:text-brand" aria-hidden />
                  <span className="text-sm font-semibold capitalize">{category}</span>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* Recommended For You Section on Home Feed */}
      {signedIn && data && (
        <section className="mx-auto max-w-page px-4 pt-16 sm:px-6">
          <RecommendedFeedSection auctions={data} />
        </section>
      )}

      {/* Safeguards */}
      <section className="mx-auto max-w-page px-4 py-24 sm:px-6">
        <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr] lg:items-end">
          <div>
            <p className="eyebrow">Trust, built in</p>
            <h2 className="mt-3 text-4xl font-semibold leading-[1.02] sm:text-[56px]">Six safeguards, all on the page.</h2>
          </div>
          <p className="max-w-lg text-lg leading-relaxed text-ink-muted lg:justify-self-end">
            Most auction sites keep these behind the curtain. Here each one shows up at the moment it matters.
          </p>
        </div>
        <div className="mt-14 grid gap-4 md:grid-cols-6">
          <Tile className="md:col-span-4" tone="brand" icon={<ReceiptIndianRupee className="size-5" />} title={`${fee} flat fee, shown first`}>
            Added only if you win, and shown with your total before you bid. Losing bidders pay nothing, ever.
            <div className="mt-6 flex flex-wrap gap-2 text-sm">
              <span className="tnum rounded-full bg-surface px-3 py-1.5 font-semibold shadow-card">Your bid {formatMoney(1_250_000, policy.currency)}</span>
              <span className="tnum rounded-full bg-surface px-3 py-1.5 font-semibold shadow-card">+ {fee}</span>
              <span className="tnum rounded-full bg-ink px-3 py-1.5 font-semibold text-canvas">= {formatMoney(1_250_000 + policy.feeCents, policy.currency)}</span>
            </div>
          </Tile>
          <Tile className="md:col-span-2" tone="positive" icon={<BadgeCheck className="size-5" />} title="Verified sellers">
            Nobody lists before their Aadhaar e-KYC verifies.
          </Tile>
          <Tile className="md:col-span-2" tone="info" icon={<Landmark className="size-5" />} title="Escrow until delivery">
            The seller is paid when you confirm receipt, or {policy.protectionDays} days after shipping with no dispute.
          </Tile>
          <Tile className="md:col-span-2" tone="gold" icon={<Hash className="size-5" />} title="Server-ordered bids">
            The server numbers every accepted bid, so equal bids always resolve the same way.
          </Tile>
          <Tile className="md:col-span-2" tone="live" icon={<Timer className="size-5" />} title="No last-second sniping">
            A bid in the final {duration(policy.guardSeconds)} adds {duration(policy.extensionSeconds)}, up to {policy.maxExtensions} times.
          </Tile>
          <Tile className="md:col-span-6" tone="night" icon={<EyeOff className="size-5" />} title="Privacy by default">
            Bidders appear under per-auction nicknames, and the reserve amount stays private. Your name never shows on a bid list.
          </Tile>
        </div>
      </section>

      {/* How a sale settles */}
      <section className="border-y border-line bg-surface">
        <div className="mx-auto max-w-page px-4 py-24 sm:px-6">
          <div className="max-w-2xl">
            <p className="eyebrow">From listing to payout</p>
            <h2 className="mt-3 text-4xl font-semibold leading-[1.02] sm:text-[56px]">How a sale settles.</h2>
            <p className="mt-5 text-lg leading-relaxed text-ink-muted">
              The services enforce every step. The screens only show what the server has already decided.
            </p>
          </div>
          <ol className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {STEPS.map(([title, body], index) => (
              <li key={title} className="group relative overflow-hidden rounded-3xl border border-line bg-canvas p-6 transition-[transform,box-shadow] duration-300 hover:-translate-y-1 hover:shadow-lift">
                <span className={cn("tnum grid size-11 place-items-center rounded-2xl font-display text-lg font-bold", STEP_TONES[index])}>{index + 1}</span>
                <p className="mt-5 font-display text-xl font-semibold tracking-[-0.015em]">{title}</p>
                <p className="mt-2 leading-relaxed text-ink-muted">{body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Roles */}
      <section className="mx-auto max-w-page px-4 py-24 sm:px-6">
        <div className="grid gap-4 md:grid-cols-3">
          <Role photo={photoFor("", "watches").src} title="Buying" lead="Watch the price move without refreshing.">
            Bids, outbid alerts and extensions arrive as they happen. You only pay if you win.
          </Role>
          <Role photo={photoFor("", "art").src} title="Selling" lead="Verify once, then list.">
            Opening an account asks for no documents. To sell, verify with Aadhaar e-KYC, then list and get paid from escrow.
          </Role>
          <Role photo={photoFor("", "books").src} title="Administering" lead="Every decision leaves a record.">
            Review and approve seller verification submissions directly. Every decision goes to an append-only audit log.
          </Role>
        </div>
      </section>

      {/* CTA */}
      <section className="px-4 sm:px-6">
        <div className="bg-midnight relative mx-auto max-w-page overflow-hidden rounded-4xl px-6 py-16 text-white sm:px-14 sm:py-20">
          <Gavel className="pointer-events-none absolute -bottom-10 right-6 size-72 -rotate-12 text-white/[0.05]" strokeWidth={1} aria-hidden />
          <div className="relative flex flex-col gap-8 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-4xl font-semibold leading-tight sm:text-[52px]">The next lot is about to open.</h2>
              <p className="mt-4 max-w-lg text-lg text-white/65">A display name, an email address and a password. That's all it takes to start bidding.</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <ButtonLink to={signedIn ? "/auctions" : "/register"} size="lg" iconRight={<ArrowRight className="size-[18px]" />}>
                {signedIn ? "Go to auctions" : "Create account"}
              </ButtonLink>
              {!signedIn && (
                <Link to="/login" className="inline-flex h-[52px] items-center rounded-full border border-white/20 px-7 text-[15px] font-semibold text-white transition-colors hover:bg-white/10">
                  Log in
                </Link>
              )}
            </div>
          </div>
        </div>
        <p className="mx-auto mt-4 max-w-page text-center text-xs text-ink-faint">
          Real-time live auction platform. Photos are Pexels stock images.
        </p>
      </section>
    </div>
  );
}

const STEPS = [
  ["Seller verified", "A UIDAI-signed Aadhaar e-KYC verification comes before the first listing."],
  ["Auction opens", "Watchers see the starting price and whether the reserve has been met."],
  ["Bids are numbered", "Each accepted bid gets the next sequence number and reaches every watcher live."],
  ["The close is protected", `Late bids extend the auction by ${duration(policy.extensionSeconds)} so everyone can answer.`],
  ["Payment is held", `The winning bid plus the ${fee} fee goes into secure escrow. The seller isn't paid yet.`],
  ["Funds are released", "After you confirm receipt, or the protection window passes with no dispute."],
] as const;

const STEP_TONES = [
  "bg-positive-soft text-positive",
  "bg-info-soft text-info",
  "bg-gold-soft text-live",
  "bg-live-soft text-live",
  "bg-brand-soft text-brand-ink",
  "bg-ink text-canvas",
];

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.05] p-4 backdrop-blur">
      <dt className="sr-only">{label}</dt>
      <dd className="tnum font-display text-2xl font-semibold tracking-[-0.03em] sm:text-[28px]">{value}</dd>
      <dd className="mt-1 text-xs leading-snug text-white/55 sm:text-[13px]">{label}</dd>
    </div>
  );
}

const TILE_TONES = {
  brand: "bg-brand-soft [&_.tile-icon]:bg-brand [&_.tile-icon]:text-brand-on",
  positive: "bg-positive-soft [&_.tile-icon]:bg-positive [&_.tile-icon]:text-white dark:[&_.tile-icon]:text-canvas",
  info: "bg-info-soft [&_.tile-icon]:bg-info [&_.tile-icon]:text-white dark:[&_.tile-icon]:text-canvas",
  gold: "bg-gold-soft [&_.tile-icon]:bg-gold [&_.tile-icon]:text-white dark:[&_.tile-icon]:text-canvas",
  live: "bg-live-soft [&_.tile-icon]:bg-live [&_.tile-icon]:text-white dark:[&_.tile-icon]:text-canvas",
  night: "bg-midnight text-white ring-1 ring-inset ring-white/10 [&_.tile-body]:text-white/65 [&_.tile-icon]:bg-white/10 [&_.tile-icon]:text-white",
} as const;

function Tile({ tone, icon, title, className, children }: { tone: keyof typeof TILE_TONES; icon: ReactNode; title: string; className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-3xl p-7 transition-transform duration-300 hover:-translate-y-0.5", TILE_TONES[tone], className)}>
      <span className="tile-icon grid size-11 place-items-center rounded-2xl">{icon}</span>
      <h3 className="mt-6 text-2xl font-semibold tracking-[-0.02em]">{title}</h3>
      <div className="tile-body mt-2 max-w-xl leading-relaxed text-ink-muted">{children}</div>
    </div>
  );
}

function Role({ photo, title, lead, children }: { photo: string; title: string; lead: string; children: ReactNode }) {
  return (
    <div className="group overflow-hidden rounded-3xl border border-line bg-surface shadow-card">
      <div className="relative h-44 overflow-hidden">
        <img src={photo} alt="" loading="lazy" className="size-full object-cover transition-transform duration-700 group-hover:scale-105" />
        <div className="absolute inset-0 bg-gradient-to-t from-night/70 to-transparent" aria-hidden />
        <span className="absolute bottom-4 left-5 rounded-full bg-white/95 px-3 py-1 text-xs font-bold text-[rgb(14_18_38)]">{title}</span>
      </div>
      <div className="p-6">
        <h3 className="text-xl font-semibold leading-snug tracking-[-0.015em]">{lead}</h3>
        <p className="mt-2 leading-relaxed text-ink-muted">{children}</p>
      </div>
    </div>
  );
}

/** Illustrative lots. Labelled as an illustration; the numbers are fixed, not live data. */
function HeroCollage() {
  const bid = 120_000;
  const tiles = [
    { category: "watches", label: "Watches", className: "left-0 top-6 w-[46%] -rotate-[5deg]" },
    { category: "cameras", label: "Cameras", className: "right-0 top-0 w-[50%] rotate-[4deg]" },
    { category: "jewelry", label: "Jewellery", className: "bottom-0 left-[2%] w-[40%] rotate-[3deg]" },
  ];
  return (
    <div className="relative mx-auto aspect-[1/1] w-full max-w-[560px] animate-fade-up [animation-delay:120ms]" role="img" aria-label="Illustration of auction lots and a bid summary">
      {tiles.map((tile) => {
        const photo = photoFor("", tile.category);
        return (
          <div key={tile.category} className={cn("absolute overflow-hidden rounded-3xl border border-white/10 bg-night-2 shadow-float transition-transform duration-500 hover:rotate-0", tile.className)}>
            <img src={photo.src} alt="" className="aspect-[4/5] w-full object-cover" />
            <span className="absolute left-3 top-3 rounded-full bg-black/45 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur">{tile.label}</span>
          </div>
        );
      })}

      <div className="absolute bottom-[6%] right-0 w-[60%] min-w-[250px] animate-float rounded-3xl border border-line bg-surface p-5 text-ink shadow-float">
        <div className="flex items-center justify-between">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-1 text-xs font-bold text-brand-ink">
            <span className="size-1.5 rounded-full bg-brand" /> Live
          </span>
          <span className="text-[11px] font-medium text-ink-faint">Illustration</span>
        </div>
        <p className="mt-3 font-display text-lg font-semibold leading-snug tracking-[-0.015em]">Rangefinder camera, 1957</p>
        <p className="mt-3 text-xs font-medium text-ink-faint">Current bid</p>
        <p className="tnum font-display text-[40px] font-semibold leading-none tracking-[-0.04em]">{formatMoney(bid, policy.currency)}</p>
        <div className="mt-4 space-y-1.5 rounded-2xl bg-surface-2 p-3 text-[13px]">
          <Row label="Flat fee if you win" value={`+ ${fee}`} />
          <Row label="Total if you win" value={formatMoney(bid + 1_000 + policy.feeCents, policy.currency)} strong />
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-ink-muted">
          <span className="inline-flex items-center gap-1.5"><ShieldCheck className="size-3.5 text-positive" /> Verified seller</span>
          <span className="inline-flex items-center gap-1 font-semibold text-brand-ink">Bid <ArrowUpRight className="size-3.5" /></span>
        </div>
      </div>

      <div className="absolute left-[16%] top-[-3%] z-10 hidden items-center gap-3 rounded-2xl border border-white/10 bg-white/10 p-3 pr-4 text-white shadow-float backdrop-blur-md sm:flex">
        <span className="grid size-9 place-items-center rounded-xl bg-positive text-white dark:text-canvas"><Hash className="size-4" /></span>
        <div className="text-xs">
          <p className="font-semibold">Bid #0142 accepted</p>
          <p className="text-white/60">Sequenced by the server</p>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className={strong ? "font-semibold" : "text-ink-muted"}>{label}</span>
      <span className={cn("tnum", strong ? "font-bold" : "font-medium")}>{value}</span>
    </div>
  );
}
