import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { CalendarClock, Eye, Info, Rocket, Save, Timer } from "lucide-react";
import { useAuth } from "@/app/auth";
import { auctionApi, type CreateAuction } from "@/lib/api";
import { describeError, errorField } from "@/lib/errors";
import { titleCase } from "@/lib/format";
import { currencySymbol, formatMoney, parseMoneyInput, toMoneyString } from "@/lib/money";
import { duration, policy } from "@/lib/policy";
import { Banner, Button, Card, CardBody, CardHeader, Field, Input, PageHeader, Select, Textarea, useToast } from "@/components/ui";
import { AuctionArt } from "@/components/auction/AuctionArt";
import { ListingGatePanel } from "@/components/kyc/ListingGatePanel";

const CATEGORIES = ["art", "books", "cameras", "electronics", "furniture", "jewelry", "music", "watches"];

/** A Date as the value of <input type="datetime-local"> in the viewer's own time zone. */
function toLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function CreateAuctionPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("cameras");
  const [starting, setStarting] = useState("");
  const [reserve, setReserve] = useState("");
  const [opens, setOpens] = useState(() => toLocalInput(new Date(Date.now() + 5 * 60_000)));
  const [closes, setCloses] = useState(() => toLocalInput(new Date(Date.now() + 24 * 3_600_000)));
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState<"draft" | "publish" | null>(null);
  const [error, setError] = useState<unknown>(null);

  const startingCents = parseMoneyInput(starting);
  const reserveCents = reserve.trim() ? parseMoneyInput(reserve) : null;
  const opensAt = opens ? new Date(opens) : null;
  const closesAt = closes ? new Date(closes) : null;

  // The orchestrator's checks (domain/auction.py + publish guard A1), mirrored.
  const local = {
      title: title.trim().length < 3 || title.trim().length > 200 ? "Title must be 3 to 200 characters" : null,
      category: category ? null : "Choose a category",
      starting_price: startingCents === null ? "Enter a starting price, like 100.00" : null,
      reserve_price:
        reserve.trim() && reserveCents === null
          ? "Enter an amount, like 8000.00"
          : reserveCents !== null && startingCents !== null && reserveCents < startingCents
            ? "The reserve can't be below the starting price"
            : null,
      opens_at: !opensAt || Number.isNaN(opensAt.getTime()) ? "Choose when bidding opens" : null,
      closes_at: closesAt && opensAt && closesAt <= opensAt ? "The auction must close after it opens" : !closesAt ? "Choose when bidding closes" : null,
  };
  const invalid = Object.values(local).some(Boolean);
  const serverField = errorField(error);
  const show = (field: keyof typeof local) => (submitted ? local[field] : null) ?? (serverField === field ? describeError(error).message : null);

  if (!user) return null;
  const verified = user.kyc_status === "VERIFIED";

  const submit = async (mode: "draft" | "publish", event?: FormEvent) => {
    event?.preventDefault();
    setSubmitted(true);
    if (invalid || startingCents === null) return;
    setBusy(mode);
    setError(null);
    const body: CreateAuction = {
      title: title.trim(),
      description: description.trim(),
      category,
      starting_price: toMoneyString(startingCents),
      reserve_price: reserveCents === null ? null : toMoneyString(reserveCents),
      currency: policy.currency,
      opens_at: opensAt ? opensAt.toISOString() : null,
      closes_at: closesAt ? closesAt.toISOString() : null,
    };
    try {
      const draft = await auctionApi.create(body);
      if (mode === "publish") await auctionApi.publish(draft.auction_id);
      toast({ tone: "positive", title: mode === "publish" ? "Auction published" : "Draft saved", description: mode === "publish" ? "It opens automatically at its start time." : "Publish it when you're ready." });
      navigate(`/auctions/${draft.auction_id}`);
    } catch (caught) {
      setError(caught);
      setBusy(null);
    }
  };

  const copy = error && !serverField ? describeError(error) : null;

  return (
    <div className="mx-auto max-w-page px-4 py-10 sm:px-6">
      <PageHeader eyebrow="Seller hub" title="Create an auction" description="Save a draft to check it, or publish to schedule it straight away." />

      {!verified && (
        <div className="mt-6">
          <ListingGatePanel status={user.kyc_status} />
        </div>
      )}

      <form onSubmit={(e) => submit("publish", e)} className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]" noValidate>
        <div className="space-y-6">
          {copy && (
            <Banner tone="danger" title={copy.title} live>
              {copy.hint ?? copy.message} <span className="font-mono text-[11px] text-ink-faint">({copy.code})</span>
            </Banner>
          )}
          <Card>
            <CardHeader title="The item" />
            <CardBody className="space-y-5">
              <Field label="Title" error={show("title")}>
                {(p) => <Input {...p} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Vintage film camera" maxLength={200} />}
              </Field>
              <Field label="Description" optional hint="Condition, what's included, anything a buyer should know.">
                {(p) => <Textarea {...p} value={description} onChange={(e) => setDescription(e.target.value)} rows={5} />}
              </Field>
              <Field label="Category" error={show("category")}>
                {(p) => (
                  <Select {...p} value={category} onChange={(e) => setCategory(e.target.value)}>
                    {CATEGORIES.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
                  </Select>
                )}
              </Field>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Pricing" description={`Prices are in ${policy.currency}.`} />
            <CardBody className="grid gap-5 sm:grid-cols-2">
              <Field label="Starting price" error={show("starting_price")} hint="The first bid must be at least this.">
                {(p) => <Input {...p} inputMode="decimal" value={starting} onChange={(e) => setStarting(e.target.value)} placeholder="8000.00" leading={<span className="text-sm">{currencySymbol(policy.currency)}</span>} />}
              </Field>
              <Field label="Reserve price" optional error={show("reserve_price")} hint="Never shown to bidders, only whether it's met.">
                {(p) => <Input {...p} inputMode="decimal" value={reserve} onChange={(e) => setReserve(e.target.value)} placeholder="12000.00" leading={<span className="text-sm">{currencySymbol(policy.currency)}</span>} />}
              </Field>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Schedule" description="Times are in your local time zone and stored in UTC." />
            <CardBody className="grid gap-5 sm:grid-cols-2">
              <Field label="Bidding opens" error={show("opens_at")}>
                {(p) => <Input {...p} type="datetime-local" value={opens} onChange={(e) => setOpens(e.target.value)} leading={<CalendarClock className="size-4" />} />}
              </Field>
              <Field label="Bidding closes" error={show("closes_at")}>
                {(p) => <Input {...p} type="datetime-local" value={closes} onChange={(e) => setCloses(e.target.value)} leading={<CalendarClock className="size-4" />} />}
              </Field>
              <p className="flex items-start gap-2 text-[13px] text-ink-muted sm:col-span-2">
                <Timer className="mt-0.5 size-4 shrink-0 text-ink-faint" aria-hidden />
                Anti-snipe applies automatically: a bid in the last {duration(policy.guardSeconds)} extends the close by {duration(policy.extensionSeconds)}, up to {policy.maxExtensions} times.
              </p>
            </CardBody>
          </Card>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <Card className="overflow-hidden">
            <AuctionArt id={title || "preview"} category={category} className="h-36" />
            <div className="p-5">
              <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-[0.12em] text-ink-faint">
                <Eye className="size-3.5" aria-hidden /> Preview
              </p>
              <p className="mt-2 line-clamp-2 font-semibold">{title.trim() || "Your auction title"}</p>
              <p className="tnum mt-3 text-2xl font-semibold tracking-[-0.02em]">{startingCents !== null ? formatMoney(startingCents, policy.currency) : formatMoney(0, policy.currency)}</p>
              <p className="text-xs text-ink-faint">Starting price</p>
            </div>
          </Card>
          <div className="flex gap-2.5 rounded-2xl border border-line bg-surface-2/50 p-4 text-[13px] text-ink-muted">
            <Info className="mt-0.5 size-4 shrink-0 text-ink-faint" aria-hidden />
            <p>When the auction sells, the buyer's payment is held in simulated escrow and released to you after delivery is confirmed or the {policy.protectionDays}-day window passes.</p>
          </div>
          <div className="grid gap-2">
            <Button type="submit" size="lg" loading={busy === "publish"} disabled={busy !== null || !verified} icon={<Rocket className="size-4" />}>
              Publish auction
            </Button>
            <Button variant="secondary" size="lg" loading={busy === "draft"} disabled={busy !== null || !verified} onClick={() => submit("draft")} icon={<Save className="size-4" />}>
              Save as draft
            </Button>
          </div>
        </aside>
      </form>
    </div>
  );
}
