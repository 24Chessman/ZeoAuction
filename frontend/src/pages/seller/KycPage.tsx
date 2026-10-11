import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, BadgeCheck, Clock3, FileCheck2, FileText, Lock, ShieldCheck } from "lucide-react";
import { useAuth } from "@/app/auth";
import { kycApi, type DocType, type KycFiles, type KycStatus, type KycSubmission } from "@/lib/api";
import { describeError, errorField } from "@/lib/errors";
import { formatBytes, formatDateTime } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import {
  Banner, Button, ButtonLink, Card, CardBody, CardHeader, FileDrop, KycBadge, PageHeader, Skeleton, useToast, type FileRules,
} from "@/components/ui";
import { KycStatusStrip } from "@/components/kyc/KycStatusStrip";
import { ListingGatePanel } from "@/components/kyc/ListingGatePanel";

/** Same limits as services/kyc (app/domain/submission.py). */
const RULES: FileRules = { accept: ["image/jpeg", "image/png", "application/pdf"], maxBytes: 10 * 1024 * 1024 };

const DOCS: Array<{ type: DocType; field: string; label: string; description: string; required: boolean }> = [
  { type: "GOVERNMENT_ID", field: "government_id", label: "Government ID", description: "Passport, national ID card or driving licence", required: true },
  { type: "PROOF_OF_ADDRESS", field: "proof_of_address", label: "Proof of address", description: "Utility bill or bank statement from the last 3 months", required: true },
  { type: "SELFIE", field: "selfie", label: "Selfie", description: "A clear photo of your face (optional)", required: false },
];

const DOC_LABEL: Record<DocType, string> = { GOVERNMENT_ID: "Government ID", PROOF_OF_ADDRESS: "Proof of address", SELFIE: "Selfie" };

const WAITING: ReadonlySet<KycStatus> = new Set(["SUBMITTED", "UNDER_REVIEW"]);

export function KycPage() {
  const { user, reload: reloadUser, refreshClaims } = useAuth();
  const toast = useToast();
  const { data: submission, loading, error, reload, setData } = useAsync(() => kycApi.mine(), []);
  const status: KycStatus = submission?.state ?? user?.kyc_status ?? "NOT_SUBMITTED";
  const previous = useRef<KycStatus | null>(null);

  // While waiting on a decision, check every few seconds so approval shows up without a reload.
  useEffect(() => {
    if (!WAITING.has(status)) return;
    const timer = setInterval(() => void reload(), 5000);
    return () => clearInterval(timer);
  }, [status, reload]);

  // A decision changes the token's claims: refresh it so the listing gate sees VERIFIED at once.
  useEffect(() => {
    const before = previous.current;
    previous.current = status;
    if (!before || before === status) return;
    void refreshClaims().catch(() => undefined);
    void reloadUser();
    if (status === "VERIFIED") toast({ tone: "positive", title: "You're verified", description: "You can now create and publish auctions." });
    if (status === "REJECTED") toast({ tone: "danger", title: "Verification rejected", description: "See the reason below and resubmit." });
  }, [status, refreshClaims, reloadUser, toast]);

  if (!user) return null;
  const canUpload = !submission || submission.can_resubmit;

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <PageHeader
        eyebrow="Seller verification"
        title={status === "VERIFIED" ? "You're a verified seller" : "Verify your identity to sell"}
        description="Bidding needs no documents. To list an item, an administrator reviews your identity first. Documents are never shown to buyers."
        actions={<KycBadge status={status} />}
      />

      <Card className="mt-8">
        <CardBody className="space-y-5">
          <KycStatusStrip status={status} />
          {loading && !submission && !error ? (
            <Skeleton className="h-14 w-full" />
          ) : (
            <StatusMessage status={status} submission={submission ?? null} />
          )}
        </CardBody>
      </Card>

      {error ? (
        <Banner tone="danger" title={describeError(error).title} className="mt-6">
          {describeError(error).message}
        </Banner>
      ) : null}

      <div className="mt-6 grid gap-6 md:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-6">
          {canUpload && !loading ? (
            <UploadForm
              resubmit={Boolean(submission)}
              onSubmitted={(next) => {
                setData(next);
                void reloadUser();
              }}
            />
          ) : submission ? (
            <SubmittedDocuments submission={submission} />
          ) : null}
        </div>
        <div className="space-y-4">
          {status === "VERIFIED" ? (
            <div className="rounded-2xl border border-positive/25 bg-positive-soft/50 p-5">
              <BadgeCheck className="size-6 text-positive" aria-hidden />
              <p className="mt-3 font-semibold">Ready to list</p>
              <p className="mt-1 text-sm text-ink-muted">Your next access token carries the verified status, so the listing gate lets you through.</p>
              <ButtonLink to="/sell/new" className="mt-4 w-full" iconRight={<ArrowRight className="size-4" />}>
                Create an auction
              </ButtonLink>
            </div>
          ) : (
            <ListingGatePanel status={status} showAction={false} />
          )}
          <div className="rounded-2xl border border-line p-5 text-sm text-ink-muted">
            <p className="flex items-center gap-2 font-semibold text-ink">
              <Lock className="size-4" aria-hidden /> How your documents are handled
            </p>
            <ul className="mt-3 space-y-2">
              <li>Stored privately and opened by administrators only through links that expire after 60 seconds.</li>
              <li>Every time a document is opened, it's written to the audit log.</li>
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
      return <Banner tone="info" title="Not submitted yet">Upload your documents below. Review usually starts once an administrator picks up the queue.</Banner>;
    case "SUBMITTED":
      return (
        <Banner tone="info" title="Waiting for review" live>
          Submitted {formatDateTime(submission?.submitted_at ?? null)}. This page updates by itself when an administrator decides.
        </Banner>
      );
    case "UNDER_REVIEW":
      return <Banner tone="info" title="An administrator is reviewing your documents" live>You'll see the decision here as soon as it's made.</Banner>;
    case "VERIFIED":
      return <Banner tone="positive" title="Verified" live>Approved {formatDateTime(submission?.decided_at ?? null)}. You can create and publish auctions.</Banner>;
    case "REJECTED":
      return (
        <Banner tone="danger" title="Your submission was rejected" live>
          <span className="block text-ink">Reason from the reviewer: “{submission?.rejection_reason ?? "No reason given"}”</span>
          <span className="mt-1 block">Upload corrected documents below to submit again.</span>
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

function UploadForm({ resubmit, onSubmitted }: { resubmit: boolean; onSubmitted: (submission: KycSubmission) => void }) {
  const toast = useToast();
  const [files, setFiles] = useState<KycFiles>({});
  const [errors, setErrors] = useState<Partial<Record<DocType, string | null>>>({});
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<unknown>(null);

  const requiredMissing = DOCS.filter((d) => d.required && !files[d.type]);
  const hasErrors = Object.values(errors).some(Boolean);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (requiredMissing.length || hasErrors) return;
    setBusy(true);
    setServerError(null);
    try {
      const submission = await kycApi.submit(files);
      toast({ tone: "positive", title: "Documents submitted", description: "An administrator will review them." });
      onSubmitted(submission);
    } catch (caught) {
      setServerError(caught);
      const field = errorField(caught);
      const doc = DOCS.find((d) => d.field === field);
      if (doc) setErrors((e) => ({ ...e, [doc.type]: describeError(caught).message }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader title={resubmit ? "Submit again" : "Upload documents"} description="JPEG, PNG or PDF, up to 10 MB each." />
      <CardBody>
        <form onSubmit={submit} className="space-y-5">
          {DOCS.map((doc) => (
            <FileDrop
              key={doc.type}
              label={doc.label}
              description={`${doc.description} · JPEG, PNG or PDF up to 10 MB`}
              required={doc.required}
              file={files[doc.type] ?? null}
              rules={RULES}
              disabled={busy}
              error={errors[doc.type] ?? null}
              onChange={(file, error) => {
                setFiles((f) => ({ ...f, [doc.type]: file ?? undefined }));
                setErrors((e) => ({ ...e, [doc.type]: error }));
                setServerError(null);
              }}
            />
          ))}
          {serverError && !errorField(serverError) ? (
            <Banner tone="danger" title={describeError(serverError).title} live>
              {describeError(serverError).message}
            </Banner>
          ) : null}
          <div className="flex flex-col-reverse items-stretch gap-3 border-t border-line pt-5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-ink-faint">
              {requiredMissing.length ? `Still needed: ${requiredMissing.map((d) => d.label).join(", ")}` : "Ready to submit."}
            </p>
            <Button type="submit" loading={busy} disabled={requiredMissing.length > 0 || hasErrors} icon={<ShieldCheck className="size-4" />}>
              Submit for review
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

function SubmittedDocuments({ submission }: { submission: KycSubmission }) {
  return (
    <Card>
      <CardHeader title="Submitted documents" description={`Submitted ${formatDateTime(submission.submitted_at)}`} />
      <CardBody>
        {submission.documents.length === 0 ? (
          <p className="text-sm text-ink-muted">Documents from this submission are on file.</p>
        ) : (
          <ul className="space-y-2">
            {submission.documents.map((doc) => (
              <li key={doc.document_id} className="flex items-center gap-3 rounded-xl border border-line p-3">
                <span className="grid size-10 place-items-center rounded-lg bg-surface-2 text-ink-muted">
                  {doc.mime_type === "application/pdf" ? <FileText className="size-5" /> : <FileCheck2 className="size-5" />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{DOC_LABEL[doc.doc_type]}</p>
                  <p className="text-xs text-ink-faint">{doc.mime_type} · {formatBytes(doc.size_bytes)}</p>
                </div>
                <span className="flex items-center gap-1 text-xs text-ink-faint">
                  <Clock3 className="size-3.5" aria-hidden /> {formatDateTime(doc.uploaded_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-4 text-xs text-ink-faint">For your privacy, documents can't be downloaded again from here.</p>
      </CardBody>
    </Card>
  );
}
