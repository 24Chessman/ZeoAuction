import { useState, type FormEvent } from "react";
import { ArrowRight, BadgeCheck, CalendarDays, Mail, ShieldCheck, SlidersHorizontal, Sparkles, UserRound } from "lucide-react";
import { useAuth } from "@/app/auth";
import { OrdersCard } from "@/components/auction/OrdersCard";
import { Banner, Button, ButtonLink, Card, CardBody, CardHeader, Field, Input, KycBadge, PageHeader, useToast } from "@/components/ui";
import { CategoryOnboardingModal } from "@/components/recommendations/CategoryOnboardingModal";
import { describeError } from "@/lib/errors";
import { formatDate, initials, titleCase } from "@/lib/format";

export function AccountPage() {
  const { user, updateName } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(user?.display_name ?? "");
  const [busy, setBusy] = useState(false);
  const [interestsOpen, setInterestsOpen] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (!user) return null;

  const trimmed = name.trim();
  const invalid = trimmed.length < 1 || trimmed.length > 80;

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (invalid) return;
    setBusy(true);
    setError(null);
    try {
      await updateName(trimmed);
      toast({ tone: "positive", title: "Profile updated" });
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <PageHeader eyebrow="Account" title="Your profile" description="How you appear on ZeoAuction, and where your seller verification stands." />

      <div className="mt-8 grid gap-6 md:grid-cols-[260px_minmax(0,1fr)]">
        <Card className="h-fit p-6 text-center">
          <span className="mx-auto grid size-20 place-items-center rounded-full bg-gradient-to-br from-brand to-gold font-display text-2xl font-bold text-white ring-4 ring-brand-soft">
            {initials(user.display_name)}
          </span>
          <p className="mt-5 font-display text-xl font-semibold">{user.display_name}</p>
          <p className="truncate text-sm text-ink-faint">{user.email}</p>
          <div className="mt-3 flex flex-wrap justify-center gap-1.5">
            <KycBadge status={user.kyc_status} />
            {user.role === "ADMIN" && <span className="inline-flex h-6 items-center rounded-full bg-ink px-2.5 text-xs font-medium text-canvas">Admin</span>}
          </div>
        </Card>

        <div className="space-y-6">
          <OrdersCard userId={user.user_id} />

          <Card>
            <CardHeader title="Profile" description="Your display name is shown on your account. In auctions you always appear under a per-auction nickname." />
            <CardBody>
              <form onSubmit={save} className="space-y-5">
                {error ? (
                  <Banner tone="danger" title={describeError(error).title} live>
                    {describeError(error).message}
                  </Banner>
                ) : null}
                <Field label="Display name" error={invalid && name !== user.display_name ? "Display name must be 1 to 80 characters" : null}>
                  {(props) => <Input {...props} value={name} onChange={(e) => setName(e.target.value)} leading={<UserRound className="size-4" />} />}
                </Field>
                <dl className="grid gap-3 text-sm sm:grid-cols-2">
                  <div className="flex items-center gap-2.5 rounded-xl bg-surface-2/60 px-3.5 py-3">
                    <Mail className="size-4 text-ink-faint" aria-hidden />
                    <dt className="sr-only">Email</dt>
                    <dd className="truncate">{user.email}</dd>
                  </div>
                  <div className="flex items-center gap-2.5 rounded-xl bg-surface-2/60 px-3.5 py-3">
                    <CalendarDays className="size-4 text-ink-faint" aria-hidden />
                    <dt className="sr-only">Member since</dt>
                    <dd>Member since {formatDate(user.created_at)}</dd>
                  </div>
                </dl>
                <div className="flex justify-end">
                  <Button type="submit" loading={busy} disabled={invalid || trimmed === user.display_name}>
                    Save changes
                  </Button>
                </div>
              </form>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title={
                <div className="flex items-center gap-2">
                  <Sparkles className="size-4 text-brand" />
                  <span>Favorite Categories & Recommendations</span>
                </div>
              }
              description="Auctions in these categories are automatically suggested on your home feed and curated in the 'For you' tab."
            />
            <CardBody>
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between rounded-2xl border border-line p-4">
                <div className="space-y-1.5">
                  <p className="text-xs font-semibold uppercase tracking-wider text-ink-faint">
                    Selected Interests ({user.favorite_categories?.length ?? 0})
                  </p>
                  {user.favorite_categories && user.favorite_categories.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {user.favorite_categories.map((cat) => (
                        <span
                          key={cat}
                          className="rounded-full border border-brand/20 bg-brand-soft px-3 py-1 text-xs font-semibold text-brand-ink"
                        >
                          {titleCase(cat)}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-ink-muted">
                      No categories selected yet. Pick your favorite categories to enable personalized recommendations.
                    </p>
                  )}
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => setInterestsOpen(true)}
                  className="shrink-0"
                  icon={<SlidersHorizontal className="size-3.5" />}
                >
                  Edit Interests
                </Button>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Selling on ZeoAuction" description="Bidding needs no verification. Listing an item does." />
            <CardBody>
              <div className="flex flex-col gap-4 rounded-2xl border border-line p-4 sm:flex-row sm:items-center">
                <span className={`grid size-11 shrink-0 place-items-center rounded-xl ${user.kyc_status === "VERIFIED" ? "bg-positive-soft text-positive" : "bg-surface-2 text-ink-muted"}`}>
                  {user.kyc_status === "VERIFIED" ? <BadgeCheck className="size-5" /> : <ShieldCheck className="size-5" />}
                </span>
                <div className="flex-1">
                  <p className="font-semibold">
                    {user.kyc_status === "VERIFIED" ? "You're a verified seller" : user.kyc_status === "NOT_SUBMITTED" ? "Not verified yet" : "Verification in progress"}
                  </p>
                  <p className="text-sm text-ink-muted">
                    {user.kyc_status === "VERIFIED" ? "You can create and publish auctions." : "Verify with your Aadhaar QR code to start selling."}
                  </p>
                </div>
                <ButtonLink to={user.kyc_status === "VERIFIED" ? "/sell" : "/sell/verify"} variant="secondary" iconRight={<ArrowRight className="size-4" />}>
                  {user.kyc_status === "VERIFIED" ? "Seller hub" : "View status"}
                </ButtonLink>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>

      <CategoryOnboardingModal
        forcedOpen={interestsOpen}
        onClose={() => setInterestsOpen(false)}
      />
    </div>
  );
}
