import { ArrowRight, BadgeCheck, Fingerprint, Gavel, Hash, Landmark, Radio, ShieldCheck, Store, Timer, UserCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { ButtonLink } from "@/components/ui";
import { AuctionArt } from "@/components/auction/AuctionArt";
import { formatMoney } from "@/lib/money";
import { duration, policy } from "@/lib/policy";

const fee = formatMoney(policy.feeCents, policy.currency);

export function LandingPage() {
  const { status } = useAuth();
  const signedIn = status === "signed-in";

  return (
    <div className="overflow-x-clip">
      {/* Hero */}
      <section className="relative">
        <div className="pointer-events-none absolute inset-0 bg-aurora" aria-hidden />
        <div className="pointer-events-none absolute inset-0 bg-grid" aria-hidden />
        <div className="relative mx-auto grid max-w-page items-center gap-14 px-4 pb-20 pt-14 sm:px-6 lg:grid-cols-[1.1fr_1fr] lg:pb-28 lg:pt-24">
          <div className="animate-fade-up">
            <span className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/80 px-3 py-1 text-xs font-medium text-ink-muted shadow-card backdrop-blur">
              <span className="relative flex size-2">
                <span className="absolute inline-flex size-full animate-live-ping rounded-full bg-positive opacity-60" />
                <span className="relative inline-flex size-2 rounded-full bg-positive" />
              </span>
              Real-time bidding, every safeguard on screen
            </span>
            <h1 className="mt-6 text-display font-semibold">
              Bid live.
              <br />
              <span className="bg-gradient-to-r from-brand via-info to-brand bg-clip-text text-transparent">Know it's safe.</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-muted">
              ZeoAuction shows you who's selling, exactly what you'll pay, and where your money waits until the item arrives, before you place a single bid.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <ButtonLink to="/auctions" size="lg" iconRight={<ArrowRight className="size-[18px]" />}>
                Browse live auctions
              </ButtonLink>
              {!signedIn && (
                <ButtonLink to="/register" size="lg" variant="secondary">
                  Create a free account
                </ButtonLink>
              )}
            </div>
            <p className="mt-5 text-sm text-ink-faint">Coursework simulation: payments run in test mode and escrow is simulated.</p>
          </div>

          <HeroPreview />
        </div>
      </section>

      {/* Safeguards */}
      <section className="border-y border-line bg-surface">
        <div className="mx-auto max-w-page px-4 py-20 sm:px-6">
          <div className="max-w-2xl">
            <p className="eyebrow">Trust, built in</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">Six safeguards a generic auction site doesn't show you.</h2>
          </div>
          <div className="mt-12 grid gap-px overflow-hidden rounded-3xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
            <Pillar icon={<BadgeCheck />} title="Verified sellers">Nobody can list until an administrator has approved their identity documents.</Pillar>
            <Pillar icon={<Gavel />} title={`${fee} flat fee, shown first`}>Added only if you win, and shown with your total before you bid. Losing bidders pay nothing.</Pillar>
            <Pillar icon={<Landmark />} title="Escrow until delivery">The seller is paid when you confirm receipt, or {policy.protectionDays} days after shipping with no dispute.</Pillar>
            <Pillar icon={<Hash />} title="Server-ordered bids">The server numbers every accepted bid, so equal bids resolve the same way every time.</Pillar>
            <Pillar icon={<Timer />} title="No last-second sniping">A bid in the final {duration(policy.guardSeconds)} adds {duration(policy.extensionSeconds)}, up to {policy.maxExtensions} times.</Pillar>
            <Pillar icon={<Fingerprint />} title="Privacy by default">Bidders appear under per-auction nicknames, and the reserve amount stays private.</Pillar>
          </div>
        </div>
      </section>

      {/* How a sale settles */}
      <section className="mx-auto max-w-page px-4 py-20 sm:px-6">
        <div className="grid gap-12 lg:grid-cols-[1fr_1.4fr]">
          <div>
            <p className="eyebrow">From listing to payout</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">How a sale settles, step by step.</h2>
            <p className="mt-4 text-ink-muted">
              The services enforce every step. The screens only show what the server has already decided, so the page never promises something the platform doesn't do.
            </p>
          </div>
          <ol className="relative space-y-1">
            {[
              ["Seller verified", "Identity documents are reviewed by an administrator before the first listing."],
              ["Auction opens", "Watchers see the starting price and whether the reserve has been met."],
              ["Bids are numbered", "Each accepted bid gets the next sequence number and reaches every watcher live."],
              ["The close is protected", `Late bids extend the auction by ${duration(policy.extensionSeconds)} so everyone can answer.`],
              ["Payment is held", `The winning bid plus the ${fee} fee goes into escrow (simulated). The seller isn't paid yet.`],
              ["Funds are released", "After you confirm receipt, or the protection window passes with no dispute."],
            ].map(([title, body], index) => (
              <li key={title} className="group relative flex gap-5 rounded-2xl p-4 transition-colors hover:bg-surface">
                <span className="tnum grid size-9 shrink-0 place-items-center rounded-full border border-line-strong bg-surface font-mono text-sm font-medium text-ink-muted transition-colors group-hover:border-brand group-hover:bg-brand group-hover:text-brand-on">
                  {index + 1}
                </span>
                <div>
                  <p className="font-semibold">{title}</p>
                  <p className="mt-0.5 text-sm text-ink-muted">{body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Roles */}
      <section className="mx-auto max-w-page px-4 pb-20 sm:px-6">
        <div className="grid gap-4 md:grid-cols-3">
          <Role icon={<Radio />} title="Buying" lead="Watch the price move without refreshing.">
            Bids, outbid alerts and extensions arrive as they happen. You only pay if you win.
          </Role>
          <Role icon={<Store />} title="Selling" lead="Verify once, then list.">
            Opening an account asks for no documents. To sell, submit ID for review, then list and get paid from escrow.
          </Role>
          <Role icon={<UserCheck />} title="Administering" lead="Every decision leaves a record.">
            Review identity documents through short-lived links. Every decision is written to an append-only audit log.
          </Role>
        </div>
      </section>

      {/* CTA */}
      <section className="px-4 pb-24 sm:px-6">
        <div className="relative mx-auto max-w-page overflow-hidden rounded-[2rem] bg-ink px-6 py-14 text-canvas sm:px-14">
          <div className="pointer-events-none absolute -right-24 -top-24 size-96 rounded-full bg-brand/40 blur-3xl" aria-hidden />
          <div className="pointer-events-none absolute -bottom-32 left-1/3 size-96 rounded-full bg-info/25 blur-3xl" aria-hidden />
          <div className="relative flex flex-col gap-8 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">Watch the next auction live.</h2>
              <p className="mt-3 max-w-lg text-canvas/70">A display name, an email address and a password. That's all it takes to start bidding.</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <ButtonLink to={signedIn ? "/auctions" : "/register"} size="lg" className="bg-canvas text-ink hover:bg-canvas/90" iconRight={<ArrowRight className="size-[18px]" />}>
                {signedIn ? "Go to auctions" : "Create account"}
              </ButtonLink>
              {!signedIn && (
                <Link to="/login" className="inline-flex h-12 items-center rounded-xl border border-canvas/25 px-6 text-[15px] font-medium text-canvas transition-colors hover:bg-canvas/10">
                  Log in
                </Link>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function Pillar({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="group bg-surface p-7 transition-colors hover:bg-surface-2/50">
      <span className="grid size-11 place-items-center rounded-2xl bg-brand-soft text-brand-ink transition-transform duration-300 group-hover:-translate-y-0.5 [&>svg]:size-5">
        {icon}
      </span>
      <h3 className="mt-5 font-semibold tracking-[-0.01em]">{title}</h3>
      <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{children}</p>
    </div>
  );
}

function Role({ icon, title, lead, children }: { icon: React.ReactNode; title: string; lead: string; children: React.ReactNode }) {
  return (
    <div className="rounded-3xl border border-line bg-surface p-7 shadow-card">
      <span className="grid size-10 place-items-center rounded-xl bg-surface-2 text-ink [&>svg]:size-5">{icon}</span>
      <p className="eyebrow mt-6">{title}</p>
      <h3 className="mt-2 text-lg font-semibold tracking-[-0.02em]">{lead}</h3>
      <p className="mt-2 text-sm leading-relaxed text-ink-muted">{children}</p>
    </div>
  );
}

/** An illustrative bid card. Labelled as a demo; its numbers are fixed, not live data. */
function HeroPreview() {
  const bid = 120_000;
  return (
    <div className="relative mx-auto w-full max-w-md animate-fade-up [animation-delay:120ms] lg:max-w-none">
      <div className="absolute -inset-6 rounded-[2.5rem] bg-gradient-to-br from-brand/25 via-info/10 to-transparent blur-2xl" aria-hidden />
      <div className="relative overflow-hidden rounded-3xl border border-line bg-surface shadow-lift" role="img" aria-label="Illustration of an auction bid panel">
        <AuctionArt id="hero-demo-leica" category="cameras" className="h-40" />
        <div className="absolute right-4 top-4 rounded-full bg-black/40 px-2.5 py-1 text-[11px] font-medium text-white backdrop-blur">Illustration</div>
        <div className="p-6">
          <div className="flex items-center justify-between">
            <p className="font-semibold">Rangefinder camera, 1957</p>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-live-soft px-2.5 py-0.5 text-xs font-medium text-live">
              <span className="size-1.5 rounded-full bg-live" /> Live
            </span>
          </div>
          <p className="eyebrow mt-5">Current bid</p>
          <p className="tnum mt-1 text-5xl font-semibold tracking-[-0.04em]">{formatMoney(bid, policy.currency)}</p>
          <div className="mt-5 space-y-2 rounded-2xl bg-surface-2/70 p-4 text-sm">
            <Row label="Your bid" value={formatMoney(bid + 1_000, policy.currency)} />
            <Row label="Flat fee if you win" value={`+ ${fee}`} />
            <div className="h-px bg-line" />
            <Row label="Total if you win" value={formatMoney(bid + 1_000 + policy.feeCents, policy.currency)} strong />
          </div>
          <div className="mt-4 flex items-center justify-between text-xs text-ink-muted">
            <span className="inline-flex items-center gap-1.5"><ShieldCheck className="size-3.5 text-positive" /> Verified seller</span>
            <span className="inline-flex items-center gap-1.5"><Timer className="size-3.5" /> Anti-snipe on</span>
          </div>
        </div>
      </div>
      <div className="absolute -bottom-5 -left-4 hidden items-center gap-3 rounded-2xl border border-line bg-surface/95 p-3 pr-4 shadow-lift backdrop-blur sm:flex">
        <span className="grid size-9 place-items-center rounded-xl bg-positive-soft text-positive"><Hash className="size-4" /></span>
        <div className="text-xs">
          <p className="font-semibold text-ink">Bid #0142 accepted</p>
          <p className="text-ink-faint">Sequenced by the server</p>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className={strong ? "font-semibold" : "text-ink-muted"}>{label}</span>
      <span className={`tnum ${strong ? "text-base font-semibold" : "font-medium"}`}>{value}</span>
    </div>
  );
}
