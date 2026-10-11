import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { ArrowRight, Crown, Gavel, Info, Loader2, Lock, RotateCcw, Timer } from "lucide-react";
import { useAuth } from "@/app/auth";
import { bidApi, feeApi, type FeeQuote } from "@/lib/api";
import { BIDDABLE, checkBid, tierIncrement } from "@/lib/bidRules";
import { cn } from "@/lib/cn";
import { ApiError, describeError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { formatMoney, parseMoney, parseMoneyInput, toMoneyString, type Cents } from "@/lib/money";
import { duration, policy } from "@/lib/policy";
import { Banner, Button, ButtonLink, Countdown } from "@/components/ui";
import type { AuctionLive } from "./useAuctionLive";

function newKey(): string {
  return `bid-${crypto.randomUUID()}`;
}

const CLIENT_COPY: Record<string, string> = {
  ACCOUNT_SUSPENDED: "Your account is suspended, so bids are refused.",
  SELF_BIDDING_FORBIDDEN: "This is your listing. Sellers can't bid on their own auctions.",
  AUCTION_NOT_OPEN: "This auction isn't taking bids right now.",
  INVALID_AMOUNT: "Enter an amount, like 125.00.",
};

/** The fee quote for the typed amount, from GET /fees/quote (never computed here). */
function useFeeQuote(amount: Cents | null) {
  const [quote, setQuote] = useState<FeeQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (amount === null || amount <= 0) {
      setQuote(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      feeApi.quote(amount).then(
        (q) => {
          if (cancelled) return;
          setQuote(q);
          setFailed(false);
          setLoading(false);
        },
        () => {
          if (cancelled) return;
          setQuote(null);
          setFailed(true);
          setLoading(false);
        },
      );
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [amount]);
  return { quote: quote && amount !== null && parseMoney(quote.bid_amount) === amount ? quote : null, loading, failed };
}

export function BidPanel({ state }: { state: AuctionLive }) {
  const { auction, live, pending, leadingSeq, flash } = state;
  const { user } = useAuth();
  const location = useLocation();
  const currency = auction.currency;
  const [raw, setRaw] = useState(() => toMoneyString(live.minNext));
  const [touched, setTouched] = useState(false);
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const key = useRef<string>(newKey());
  const priceRef = useRef<HTMLDivElement>(null);

  const amount = parseMoneyInput(raw);
  const { quote, loading: quoting, failed: quoteFailed } = useFeeQuote(amount);
  const biddable = BIDDABLE.has(auction.state);
  const isSeller = user?.user_id === auction.seller_id;
  const leading = leadingSeq !== null && leadingSeq === live.seq;

  // Keep the field at the minimum until the person types their own amount.
  useEffect(() => {
    if (!touched) setRaw(toMoneyString(live.minNext));
  }, [live.minNext, touched]);

  // Flash the price when a newer server_seq lands.
  useEffect(() => {
    if (flash === 0 || !priceRef.current) return;
    const node = priceRef.current;
    node.classList.remove("animate-price-flash");
    void node.offsetWidth;
    node.classList.add("animate-price-flash");
  }, [flash]);

  const check = useMemo(
    () => checkBid({ amount, minNextBid: live.minNext, state: auction.state, suspended: Boolean(user?.suspended), isSeller }),
    [amount, live.minNext, auction.state, user?.suspended, isSeller],
  );

  const clientError = !check.ok
    ? check.code === "BID_BELOW_INCREMENT"
      ? `The minimum next bid is ${formatMoney(live.minNext, currency)}.`
      : CLIENT_COPY[check.code]
    : null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!check.ok || amount === null || !user) return;
    setSubmitting(true);
    setServerError(null);
    state.begin(amount);
    try {
      const { bid } = await bidApi.place(auction.auction_id, amount, key.current);
      state.acknowledge(bid);
      key.current = newKey();
      setTouched(false);
    } catch (error) {
      state.fail();
      if (error instanceof ApiError) {
        setServerError(error);
        // A retryable failure keeps the key, so retrying cannot place the bid twice.
        if (!error.retryable) key.current = newKey();
        if (error.code === "BID_BELOW_INCREMENT" && typeof error.details?.min_next_bid === "string") {
          setRaw(error.details.min_next_bid);
        }
      }
    } finally {
      setSubmitting(false);
    }
  };

  const step = tierIncrement(live.minNext);
  const quick = [0, 2, 5].map((steps) => live.minNext + steps * step);
  const shownPrice = pending ?? live.price ?? parseMoney(auction.starting_price);
  const urgent = auction.closes_at ? Date.parse(auction.closes_at) - Date.now() < auction.guard_interval_seconds * 1000 : false;

  return (
    <div className="overflow-hidden rounded-3xl border border-line bg-surface shadow-lift">
      {/* Price */}
      <div className="relative border-b border-line p-6">
        <div className="pointer-events-none absolute inset-0 bg-aurora opacity-70" aria-hidden />
        <div className="relative">
          <div className="flex items-center justify-between">
            <p className="eyebrow">{live.price === null ? "Starting price" : "Current bid"}</p>
            {leading && (
              <span className="inline-flex items-center gap-1 rounded-full bg-positive-soft px-2.5 py-1 text-xs font-semibold text-positive">
                <Crown className="size-3.5" aria-hidden /> You're leading
              </span>
            )}
          </div>
          <div ref={priceRef} className="-mx-2 mt-2 rounded-xl px-2" aria-live="polite" aria-atomic>
            <p className={cn("tnum text-price font-semibold transition-opacity", pending !== null && "opacity-60")}>
              {formatMoney(shownPrice, currency)}
            </p>
            {pending !== null && (
              <p className="mt-1 flex items-center gap-1.5 text-xs font-medium text-ink-muted">
                <Loader2 className="size-3.5 animate-spin" aria-hidden /> Your bid is being sequenced by the server…
              </p>
            )}
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-xl bg-surface/70 p-3 ring-1 ring-line backdrop-blur">
              <dt className="text-xs text-ink-faint">Minimum next bid</dt>
              <dd className="tnum mt-0.5 font-semibold">{formatMoney(live.minNext, currency)}</dd>
            </div>
            <div className="rounded-xl bg-surface/70 p-3 ring-1 ring-line backdrop-blur">
              <dt className="text-xs text-ink-faint">{biddable ? "Ends in" : auction.state === "SCHEDULED" ? "Opens" : "Status"}</dt>
              <dd className={cn("mt-0.5 font-semibold", urgent && biddable && "text-live")}>
                {biddable && auction.closes_at ? (
                  <Countdown to={auction.closes_at} />
                ) : auction.state === "SCHEDULED" ? (
                  formatDateTime(auction.opens_at)
                ) : (
                  <span>{auction.state === "SETTLED" ? "Settled" : auction.state === "CANCELLED" ? "Cancelled" : "Bidding closed"}</span>
                )}
              </dd>
            </div>
          </dl>
          {biddable && (
            <p className="mt-3 flex items-start gap-1.5 text-xs text-ink-muted">
              <Timer className="mt-px size-3.5 shrink-0" aria-hidden />
              A bid in the last {duration(auction.guard_interval_seconds)} adds {duration(auction.extension_seconds)}
              {" "}(used {auction.extension_count} of {auction.max_extensions}).
            </p>
          )}
        </div>
      </div>

      {/* Form */}
      <div className="p-6">
        {!user ? (
          <div className="text-center">
            <span className="mx-auto grid size-11 place-items-center rounded-2xl bg-brand-soft text-brand-ink">
              <Lock className="size-5" aria-hidden />
            </span>
            <p className="mt-3 font-semibold">Log in to bid and watch live</p>
            <p className="mt-1 text-sm text-ink-muted">Live prices and outbid alerts need an account.</p>
            <ButtonLink to="/login" state={{ from: location.pathname }} className="mt-4 w-full" iconRight={<ArrowRight className="size-4" />}>
              Log in
            </ButtonLink>
          </div>
        ) : !biddable ? (
          <Banner tone={auction.state === "SCHEDULED" ? "info" : "warning"} title={auction.state === "SCHEDULED" ? "Not open yet" : "Bidding is closed"}>
            {auction.state === "SCHEDULED" ? "Bids are accepted once the auction opens." : "This auction is no longer taking bids."}
          </Banner>
        ) : (
          <form onSubmit={submit} noValidate>
            <label htmlFor="bid-amount" className="text-[13px] font-medium">Your bid</label>
            <div className="relative mt-1.5">
              <span className="pointer-events-none absolute inset-y-0 left-4 flex items-center text-lg font-medium text-ink-faint">{currency === "USD" ? "$" : currency}</span>
              <input
                id="bid-amount"
                inputMode="decimal"
                autoComplete="off"
                value={raw}
                onChange={(event) => {
                  setRaw(event.target.value);
                  setTouched(true);
                  setServerError(null);
                }}
                aria-invalid={touched && Boolean(clientError)}
                aria-describedby="bid-help"
                disabled={isSeller || Boolean(user.suspended)}
                className={cn(
                  "tnum h-14 w-full rounded-2xl border bg-surface pl-10 pr-4 text-2xl font-semibold tracking-[-0.02em] transition-[border-color,box-shadow] focus:border-brand focus:shadow-focus focus:outline-none disabled:opacity-60",
                  touched && clientError ? "border-danger" : "border-line-strong",
                )}
              />
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {quick.map((value) => (
                <button
                  key={value}
                  type="button"
                  disabled={isSeller}
                  onClick={() => {
                    setRaw(toMoneyString(value));
                    setTouched(true);
                    setServerError(null);
                  }}
                  className="tnum rounded-lg border border-line bg-surface-2/60 px-2.5 py-1 text-xs font-medium text-ink-muted transition-colors hover:border-brand/40 hover:text-brand-ink"
                >
                  {formatMoney(value, currency)}
                </button>
              ))}
            </div>
            <p id="bid-help" className={cn("mt-2 min-h-5 text-[13px]", touched && clientError ? "text-danger" : "text-ink-faint")} role={touched && clientError ? "alert" : undefined}>
              {touched && clientError ? clientError : isSeller ? CLIENT_COPY.SELF_BIDDING_FORBIDDEN : `Enter ${formatMoney(live.minNext, currency)} or more.`}
            </p>

            {/* AC-07: the flat fee and the total, before the bid is placed. */}
            <div className="mt-4 rounded-2xl border border-line bg-surface-2/50 p-4" aria-live="polite">
              <div className="flex items-center justify-between text-sm">
                <span className="text-ink-muted">Your bid</span>
                <span className="tnum font-medium">{amount !== null ? formatMoney(amount, currency) : "—"}</span>
              </div>
              <div className="mt-2 flex items-center justify-between text-sm">
                <span className="flex items-center gap-1 text-ink-muted">
                  Flat fee if you win
                  <span title={`Fee policy ${quote?.fee_version ?? policy.feeVersion}. Losing bidders pay nothing.`}>
                    <Info className="size-3.5 text-ink-faint" aria-hidden />
                  </span>
                </span>
                <span className="tnum font-medium">
                  {quote ? `+ ${formatMoney(parseMoney(quote.convenience_fee), quote.currency)}` : quoting ? "…" : "—"}
                </span>
              </div>
              <div className="my-3 h-px bg-line" />
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold">Total if you win</span>
                <span className="tnum text-lg font-semibold">{quote ? formatMoney(parseMoney(quote.total), quote.currency) : quoting ? "…" : "—"}</span>
              </div>
              {quoteFailed && <p className="mt-2 text-xs text-danger">The fee quote is unavailable; try again before bidding.</p>}
              <p className="mt-2 text-xs text-ink-faint">Only charged if you win. Losing bidders pay nothing. Test mode: no real payment.</p>
            </div>

            {serverError && (
              <Banner
                tone={serverError.retryable ? "warning" : "danger"}
                title={describeError(serverError).title}
                className="mt-4"
                live
                action={
                  serverError.retryable ? (
                    <Button type="submit" size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" />}>
                      Retry
                    </Button>
                  ) : undefined
                }
              >
                {serverError.code === "BID_BELOW_INCREMENT" && typeof serverError.details?.min_next_bid === "string"
                  ? `Someone bid first. The minimum is now ${formatMoney(parseMoney(serverError.details.min_next_bid), currency)}.`
                  : describeError(serverError).hint ?? serverError.message}
                <span className="mt-1 block font-mono text-[11px] text-ink-faint">{serverError.code}</span>
              </Banner>
            )}

            <Button
              type="submit"
              size="lg"
              className="mt-4 w-full"
              loading={submitting}
              disabled={!check.ok || !quote || isSeller}
              icon={!submitting ? <Gavel className="size-[18px]" /> : undefined}
            >
              {quote && check.ok ? `Place bid · ${formatMoney(parseMoney(quote.bid_amount), currency)}` : "Place bid"}
            </Button>
            {user.kyc_status !== "VERIFIED" && isSeller === false && (
              <p className="mt-3 text-center text-xs text-ink-faint">
                Bidding needs no verification. <Link to="/sell/verify" className="text-brand-ink hover:underline">Selling does.</Link>
              </p>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
