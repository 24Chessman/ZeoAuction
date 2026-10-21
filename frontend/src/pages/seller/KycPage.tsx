import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, BadgeCheck, Fingerprint, ImageIcon, Lock, Phone, QrCode, ScanFace, ShieldCheck } from "lucide-react";
import { useAuth } from "@/app/auth";
import { kycApi, type FaceOutcome, type KycStatus, type KycSubmission } from "@/lib/api";
import { useMocks } from "@/lib/config";
import { ApiError, describeError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import {
  Banner, Button, ButtonLink, Card, CardBody, CardHeader, Field, FileDrop, Input, KycBadge, PageHeader, Skeleton, useToast, type FileRules,
} from "@/components/ui";
import { FaceCapture } from "@/components/kyc/FaceCapture";
import { KycStatusStrip } from "@/components/kyc/KycStatusStrip";
import { ListingGatePanel } from "@/components/kyc/ListingGatePanel";

/** Same limits as services/kyc (app/domain/aadhaar.py check_image). */
const QR_RULES: FileRules = {
  accept: ["image/jpeg", "image/png", "image/webp"],
  extensions: [".jpg", ".jpeg", ".png", ".webp"],
  maxBytes: 8 * 1024 * 1024,
  typeLabel: "JPEG, PNG or WebP",
};
const GENDER: Record<string, string> = { M: "Male", F: "Female", T: "Transgender" };

const FACE_RESULT: Record<Exclude<FaceOutcome, "MATCH" | "REVIEW">, { title: string; hint: string }> = {
  NO_MATCH: { title: "That didn't match your Aadhaar photo", hint: "Make sure it's you on the Aadhaar, face the light and remove glasses, then try again." },
  LIVENESS_FAILED: { title: "We couldn't confirm a live person", hint: "Turn your head left and right when the prompt asks, and keep moving naturally." },
  NO_FACE: { title: "We couldn't see exactly one face", hint: "Fill the oval with your face, use brighter light, and keep others out of the frame. This didn't use up an attempt." },
};

export function KycPage() {
  const { user, reload: reloadUser, refreshClaims } = useAuth();
  const toast = useToast();
  const { data: submission, loading, error, reload, setData } = useAsync(() => kycApi.mine(), []);
  const status: KycStatus = submission?.state ?? user?.kyc_status ?? "NOT_SUBMITTED";
  const previous = useRef<KycStatus | null>(null);
  const [replacing, setReplacing] = useState(false);

  // Only a manual review waits on someone else; check every few seconds so the decision shows up.
  useEffect(() => {
    if (status !== "UNDER_REVIEW") return;
    const timer = setInterval(() => void reload(), 5000);
    return () => clearInterval(timer);
  }, [status, reload]);

  // A status change changes the token's claims: refresh it so the listing gate sees it at once.
  useEffect(() => {
    const before = previous.current;
    previous.current = status;
    if (!before || before === status) return;
    void refreshClaims().catch(() => undefined);
    void reloadUser();
    if (status === "VERIFIED") toast({ tone: "positive", title: "You're verified", description: "You can now create and publish auctions." });
    if (status === "REJECTED" && before === "UNDER_REVIEW") toast({ tone: "danger", title: "Verification rejected", description: "See the reason below." });
  }, [status, refreshClaims, reloadUser, toast]);

  if (!user) return null;
  const update = (next: KycSubmission) => {
    setData(next);
    setReplacing(false);
  };
  const showUpload = !submission || (submission.state === "REJECTED" && submission.can_resubmit) || (replacing && submission.can_resubmit);
  const showFace = submission?.state === "SUBMITTED" && !replacing;

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <PageHeader
        eyebrow="Seller verification"
        title={status === "VERIFIED" ? "You're a verified seller" : "Verify your identity to sell"}
        description="Bidding needs nothing. To list an item, verify with your Aadhaar offline e-KYC and a quick live face check. Buyers never see any of it."
        actions={<KycBadge status={status} />}
      />

      <Card className="mt-8">
        <CardBody className="space-y-5">
          <KycStatusStrip status={status} />
          {loading && !submission && !error ? <Skeleton className="h-14 w-full" /> : <StatusMessage status={status} submission={submission ?? null} />}
        </CardBody>
      </Card>

      {error ? (
        <Banner tone="danger" title={describeError(error).title} className="mt-6">{describeError(error).message}</Banner>
      ) : null}

      <div className="mt-6 grid gap-6 md:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-6">
          {loading && !submission ? null : showUpload ? (
            <AadhaarForm
              replacing={Boolean(submission && submission.state !== "REJECTED")}
              onCancel={replacing ? () => setReplacing(false) : undefined}
              onVerified={(next) => {
                update(next);
                void reloadUser();
                toast({ tone: "positive", title: "Aadhaar verified", description: "UIDAI's signature checks out. Now the face check." });
              }}
            />
          ) : showFace && submission ? (
            <FaceStep submission={submission} onResult={update} onReplace={() => setReplacing(true)} />
          ) : null}
          {submission?.aadhaar && !showUpload && !showFace ? <IdentityCard submission={submission} /> : null}
        </div>
        <div className="space-y-4">
          {status === "VERIFIED" ? (
            <div className="rounded-3xl border border-positive/25 bg-positive-soft/50 p-5">
              <BadgeCheck className="size-6 text-positive" aria-hidden />
              <p className="mt-3 font-semibold">Ready to list</p>
              <p className="mt-1 text-sm text-ink-muted">Your next access token carries the verified status, so the listing gate lets you through.</p>
              <ButtonLink to="/sell/new" className="mt-4 w-full" iconRight={<ArrowRight className="size-4" />}>Create an auction</ButtonLink>
            </div>
          ) : (
            <ListingGatePanel status={status} showAction={false} />
          )}
          <div className="rounded-3xl border border-line p-5 text-sm text-ink-muted">
            <p className="flex items-center gap-2 font-semibold text-ink">
              <Lock className="size-4" aria-hidden /> What we keep
            </p>
            <ul className="mt-3 list-disc space-y-2 pl-4">
              <li>Your name, birth year, gender, state and the last 4 digits UIDAI already shows. Never your full Aadhaar number or address.</li>
              <li>The QR photo, what the QR holds and your mobile number are used once to verify, then discarded.</li>
              <li>Your Aadhaar photo and one matched camera frame are stored encrypted. An administrator sees them only if a review is needed, and every view is logged.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusMessage({ status, submission }: { status: KycStatus; submission: KycSubmission | null }) {
  switch (status) {
    case "NOT_SUBMITTED":
      return <Banner tone="info" title="Two steps, about two minutes">Upload a photo of the QR code on your Aadhaar, then look into your camera for a few seconds.</Banner>;
    case "SUBMITTED":
      return (
        <Banner tone="info" title="Aadhaar verified, face check next" live>
          {submission?.aadhaar ? `Signed by UIDAI for ${submission.aadhaar.holder_name}. ` : ""}Now show us it's really you.
        </Banner>
      );
    case "UNDER_REVIEW":
      return (
        <Banner tone="info" title="Your face check needs a second look" live>
          It was close, so an administrator is comparing your camera frame with the Aadhaar photo. This page updates by itself.
        </Banner>
      );
    case "VERIFIED":
      return <Banner tone="positive" title="Verified" live>Approved {formatDateTime(submission?.decided_at ?? null)}. You can create and publish auctions.</Banner>;
    case "REJECTED":
      return (
        <Banner tone="danger" title="Verification didn't go through" live>
          {submission?.rejection_reason ? <span className="block text-ink">Reason: “{submission.rejection_reason}”</span> : null}
          <span className="mt-1 block">
            {submission?.resubmit_after
              ? `You can try again after ${formatDateTime(submission.resubmit_after)}.`
              : "Upload a photo of your Aadhaar QR code below to try again."}
          </span>
        </Banner>
      );
    case "SUSPENDED":
      return (
        <Banner tone="danger" title="Seller verification suspended" live>
          {submission?.rejection_reason ? <span className="font-mono text-xs">{submission.rejection_reason}</span> : null} Listing is refused until an administrator reinstates you.
        </Banner>
      );
  }
}

function AadhaarForm({ replacing, onVerified, onCancel }: { replacing: boolean; onVerified: (s: KycSubmission) => void; onCancel?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [mobile, setMobile] = useState("");
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<unknown>(null);

  const field = serverError instanceof ApiError ? String(serverError.details?.field ?? "") : "";
  const fieldError = (name: string) => (field === name ? describeError(serverError).message : null);
  const ready = Boolean(file) && !fileError;
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    if (!file || fileError) return setPreview(null);
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file, fileError]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || !ready) return;
    setBusy(true);
    setServerError(null);
    try {
      onVerified(await kycApi.uploadAadhaar(file, mobile.trim() || undefined));
    } catch (caught) {
      setServerError(caught);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title={<span className="flex items-center gap-2"><Fingerprint className="size-5 text-brand-ink" aria-hidden /> Step 1 · Aadhaar QR code</span>}
        description={replacing ? "Upload a different photo. It replaces the one waiting for the face check." : "UIDAI signs the QR code, so we can check it wasn't changed. Your full Aadhaar number is never in it."}
      />
      <CardBody>
        <ol className="mb-6 grid gap-2 rounded-2xl bg-surface-2/60 p-4 text-sm text-ink-muted sm:grid-cols-2">
          <li><span className="font-semibold text-ink">1.</span> Find the large QR code on your Aadhaar letter, PVC card or e-Aadhaar PDF.</li>
          <li><span className="font-semibold text-ink">2.</span> Lay it flat in good light, without glare.</li>
          <li><span className="font-semibold text-ink">3.</span> Take a photo with the QR code filling most of the frame, in focus.</li>
          <li><span className="font-semibold text-ink">4.</span> Upload it here. A screenshot of the e-Aadhaar works too.</li>
        </ol>
        <form onSubmit={submit} className="space-y-5">
          <FileDrop
            label="Photo of the Aadhaar QR code"
            description={<span className="inline-flex items-center gap-1"><ImageIcon className="size-3.5" aria-hidden /> JPEG, PNG or WebP · up to 8 MB</span>}
            required
            file={file}
            rules={QR_RULES}
            disabled={busy}
            error={fileError ?? fieldError("qr_image")}
            onChange={(next, problem) => {
              setFile(next);
              setFileError(problem);
              setServerError(null);
            }}
          />
          {preview && (
            <div className="flex items-center gap-4 rounded-2xl bg-surface-2/60 p-3">
              <img src={preview} alt="The QR photo you picked" className="size-24 shrink-0 rounded-xl object-cover" />
              <p className="flex min-w-0 items-center gap-2 text-sm text-ink-muted">
                <QrCode className="size-4 shrink-0 text-brand-ink" aria-hidden />
                <span>The whole QR code should be sharp and visible. If it's cut off or blurry, take another photo.</span>
              </p>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Mobile linked to Aadhaar" optional hint="Checked against what UIDAI put in the QR, then discarded" error={fieldError("mobile")}>
              {(p) => (
                <Input {...p} type="tel" autoComplete="tel-national" inputMode="numeric" value={mobile} maxLength={16} disabled={busy}
                  leading={<Phone className="size-4" />} placeholder="98765 43210" onChange={(e) => { setMobile(e.target.value); setServerError(null); }} />
              )}
            </Field>
          </div>
          {serverError && !field ? (
            <Banner tone="danger" title={describeError(serverError).title} live>{describeError(serverError).message}</Banner>
          ) : null}
          {useMocks && (
            <p className="rounded-2xl border border-dashed border-line-strong p-3 text-xs text-ink-faint">
              Mock mode: the QR is read and UIDAI&apos;s signature checked in your browser; nothing is uploaded. The face check is
              simulated: a file name containing <code>review</code> sends it to review, <code>nomatch</code> never matches.
            </p>
          )}
          <div className="flex flex-col-reverse items-stretch gap-3 border-t border-line pt-5 sm:flex-row sm:items-center sm:justify-end">
            {onCancel && <Button variant="ghost" onClick={onCancel} disabled={busy}>Keep the current one</Button>}
            <Button type="submit" loading={busy} disabled={!ready} icon={<ShieldCheck className="size-4" />}>Verify Aadhaar</Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

function FaceStep({ submission, onResult, onReplace }: { submission: KycSubmission; onResult: (s: KycSubmission) => void; onReplace: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<FaceOutcome | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [round, setRound] = useState(0);
  const left = submission.face.attempts_left;

  const check = async (frames: Blob[]) => {
    setBusy(true);
    setError(null);
    setOutcome(null);
    try {
      const result = await kycApi.faceCheck(submission.submission_id, frames);
      setOutcome(result.outcome);
      if (result.outcome === "REVIEW") toast({ tone: "info", title: "Sent for a quick review", description: "An administrator will compare the photos." });
      onResult(result.submission);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
      setRound((n) => n + 1);
    }
  };

  const failed = outcome && outcome !== "MATCH" && outcome !== "REVIEW" ? FACE_RESULT[outcome] : null;
  return (
    <Card>
      <CardHeader
        title={<span className="flex items-center gap-2"><ScanFace className="size-5 text-brand-ink" aria-hidden /> Step 2 · Live face check</span>}
        description={`We compare you with the photo in your Aadhaar. ${left} ${left === 1 ? "attempt" : "attempts"} left.`}
      />
      <CardBody className="space-y-5">
        {submission.aadhaar && (
          <div className="flex items-center gap-3 rounded-2xl bg-positive-soft/50 p-3 text-sm">
            <BadgeCheck className="size-5 shrink-0 text-positive" aria-hidden />
            <p className="min-w-0 text-ink-muted">
              <span className="font-semibold text-ink">{submission.aadhaar.holder_name}</span> · Aadhaar XXXX XXXX {submission.aadhaar.reference_last4}
            </p>
          </div>
        )}
        {failed && (
          <Banner tone={outcome === "NO_FACE" ? "warning" : "danger"} title={failed.title} live>
            {failed.hint} {outcome !== "NO_FACE" && (left > 0 ? `${left} ${left === 1 ? "attempt" : "attempts"} left.` : "")}
          </Banner>
        )}
        {error ? <Banner tone="danger" title={describeError(error).title} live>{describeError(error).message}</Banner> : null}
        <FaceCapture key={round} busy={busy} onCaptured={(frames) => void check(frames)} />
        {submission.can_resubmit && (
          <p className="text-center text-sm text-ink-muted">
            Wrong Aadhaar?{" "}
            <button type="button" onClick={onReplace} className="font-medium text-brand-ink underline-offset-2 hover:underline">Upload a different one</button>
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function IdentityCard({ submission }: { submission: KycSubmission }) {
  const a = submission.aadhaar;
  if (!a) return null;
  return (
    <Card>
      <CardHeader title="Your Aadhaar details" description={`From the Aadhaar QR code UIDAI generated ${formatDateTime(a.qr_generated_at)}`} />
      <CardBody>
        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <Item label="Name" value={a.holder_name} />
          <Item label="Aadhaar" value={<span className="font-mono">XXXX XXXX {a.reference_last4}</span>} />
          <Item label="Birth year" value={String(a.year_of_birth)} />
          <Item label="Gender" value={GENDER[a.gender] ?? a.gender} />
          <Item label="State" value={a.state ?? "—"} />
          <Item label="Mobile" value={a.mobile_verified ? "Matched" : "Not checked"} />
        </dl>
      </CardBody>
    </Card>
  );
}

function Item({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="mt-0.5 font-medium text-ink">{value}</dd>
    </div>
  );
}
