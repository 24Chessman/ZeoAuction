import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, Fingerprint, RotateCcw, ShieldCheck, ShieldOff, X } from "lucide-react";
import {
  adminKycApi, type AdminKycEvent, type AdminSubmission,
} from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatDateTime, shortId } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { Banner, Button, Card, CardBody, CardHeader, Field, KycBadge, Modal, Select, Skeleton, Textarea, useToast } from "@/components/ui";
import { KycStatusStrip } from "@/components/kyc/KycStatusStrip";

const SUSPEND_CODES = ["IDENTITY_MISMATCH", "AADHAAR_MISUSE", "FRAUD_SUSPECTED", "POLICY_VIOLATION"];
const GENDER: Record<string, string> = { M: "Male", F: "Female", T: "Transgender" };

export function AdminKycReviewPage() {
  const { submissionId = "" } = useParams();
  const { data, error, loading, setData } = useAsync(() => adminKycApi.detail(submissionId), [submissionId]);

  return (
    <div className="mx-auto max-w-page px-4 py-10 sm:px-6">
      <Link to="/admin/kyc" className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden /> Review queue
      </Link>
      {error ? (
        <Banner tone="danger" title={describeError(error).title} className="mt-6">{describeError(error).message}</Banner>
      ) : loading && !data ? (
        <Skeleton className="mt-6 h-96 w-full rounded-3xl" />
      ) : data ? (
        <Review submission={data} onChange={setData} />
      ) : null}
    </div>
  );
}

function Review({ submission, onChange }: { submission: AdminSubmission; onChange: (s: AdminSubmission) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<AdminKycEvent | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [rejecting, setRejecting] = useState(false);
  const [suspending, setSuspending] = useState(false);

  const act = async (event: AdminKycEvent, body?: { reason?: string; reason_code?: string }) => {
    setBusy(event);
    setError(null);
    try {
      const next = await adminKycApi.transition(submission.submission_id, event, body);
      onChange(next);
      setRejecting(false);
      setSuspending(false);
      const titles: Record<AdminKycEvent, string> = {
        approve: "Seller approved",
        reject: "Submission rejected",
        suspend: "Seller suspended",
        reinstate: "Seller reinstated",
      };
      toast({ tone: event === "approve" || event === "reinstate" ? "positive" : "warning", title: titles[event], description: "The seller's account status has been updated." });
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(null);
    }
  };

  const s = submission.state;
  return (
    <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="eyebrow">Submission</p>
            <h1 className="mt-1 font-mono text-2xl font-semibold tracking-[-0.02em]">KYC-{shortId(submission.submission_id)}</h1>
          </div>
          <KycBadge status={s} />
        </div>

        <Card>
          <CardBody>
            <KycStatusStrip status={s} />
          </CardBody>
        </Card>

        <AadhaarCard submission={submission} />
      </div>

      <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
        <Card>
          <CardHeader title="Decision" />
          <CardBody className="space-y-3">
            {error ? (
              <Banner tone="danger" title={describeError(error).title} live>
                {describeError(error).message} <span className="font-mono text-[11px]">({describeError(error).code})</span>
              </Banner>
            ) : null}
            {(s === "SUBMITTED" || s === "UNDER_REVIEW") && (
              <>
                <p className="text-sm text-ink-muted">Review the verified Aadhaar details on the left to decide whether to approve this seller.</p>
                <Button variant="positive" className="w-full" loading={busy === "approve"} disabled={busy !== null} icon={<Check className="size-4" />} onClick={() => act("approve")}>
                  Approve seller
                </Button>
                <Button variant="secondary" className="w-full text-danger" disabled={busy !== null} icon={<X className="size-4" />} onClick={() => setRejecting(true)}>
                  Reject with reason
                </Button>
              </>
            )}
            {s === "VERIFIED" && (
              <>
                <Banner tone="positive" title="Approved">This seller is verified and authorized to list auctions.</Banner>
                <Button variant="secondary" className="w-full text-danger" disabled={busy !== null} icon={<ShieldOff className="size-4" />} onClick={() => setSuspending(true)}>
                  Suspend seller
                </Button>
              </>
            )}
            {s === "SUSPENDED" && (
              <>
                <Banner tone="danger" title="Suspended">{submission.rejection_reason && <span className="font-mono text-xs">{submission.rejection_reason}</span>}</Banner>
                <Button className="w-full" loading={busy === "reinstate"} icon={<RotateCcw className="size-4" />} onClick={() => act("reinstate")}>
                  Reinstate seller
                </Button>
              </>
            )}
            {s === "REJECTED" && (
              <Banner tone="danger" title="Rejected">“{submission.rejection_reason}”</Banner>
            )}
          </CardBody>
        </Card>
        <Card className="p-5 text-sm">
          <dl className="space-y-2.5">
            <Meta label="Applicant" value={<span className="font-mono text-xs" title={submission.user_id}>…{shortId(submission.user_id)}</span>} />
            <Meta label="Submitted" value={formatDateTime(submission.submitted_at)} />
            <Meta label="Decided" value={formatDateTime(submission.decided_at)} />
            <Meta label="Decided by" value={submission.decided_by ? <span className="font-mono text-xs">…{shortId(submission.decided_by)}</span> : "—"} />
          </dl>
        </Card>
      </aside>

      <RejectModal open={rejecting} busy={busy === "reject"} onClose={() => setRejecting(false)} onSubmit={(reason) => act("reject", { reason })} />
      <SuspendModal open={suspending} busy={busy === "suspend"} onClose={() => setSuspending(false)} onSubmit={(code) => act("suspend", { reason_code: code })} />
    </div>
  );
}

function AadhaarCard({ submission }: { submission: AdminSubmission }) {
  const a = submission.aadhaar;
  return (
    <Card>
      <CardHeader
        title={<span className="flex items-center gap-2"><Fingerprint className="size-5 text-brand-ink" aria-hidden /> Aadhaar e-KYC Details</span>}
        description="UIDAI offline cryptographic signature verified directly from the uploaded QR code."
      />
      <CardBody>
        {!a ? (
          <p className="text-sm text-ink-muted">No Aadhaar record found on this submission.</p>
        ) : (
          <div className="space-y-6">
            <div className="rounded-2xl border border-positive/30 bg-positive-soft/40 p-4">
              <p className="flex items-center gap-2 text-sm font-semibold text-positive-ink">
                <ShieldCheck className="size-4 text-positive" aria-hidden /> Cryptographically Verified by UIDAI
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                Digital signature matches UIDAI's root public certificate. Holder information extracted and verified without tampering.
              </p>
            </div>

            <dl className="grid gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
              <Item label="Full name" value={a.holder_name} />
              <Item label="Aadhaar reference" value={<span className="font-mono font-semibold">XXXX XXXX {a.reference_last4}</span>} />
              <Item label="Year of birth" value={String(a.year_of_birth)} />
              <Item label="Gender" value={GENDER[a.gender] ?? a.gender} />
              <Item label="State" value={a.state ?? "—"} />
              <Item label="PIN code" value={a.pincode ?? "—"} />
              <Item label="Mobile verification" value={a.mobile_verified ? "Matched UIDAI record" : "Not matched / Not provided"} />
              <Item label="QR generated timestamp" value={formatDateTime(a.qr_generated_at)} />
              <Item
                label="Signer certificate hash"
                value={<span className="font-mono text-xs text-ink-muted" title={a.signer_sha256}>{a.signer_sha256}</span>}
              />
            </dl>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function Item({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="mt-1 font-medium text-ink">{value}</dd>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}

function RejectModal({ open, busy, onClose, onSubmit }: { open: boolean; busy: boolean; onClose: () => void; onSubmit: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  const length = reason.trim().length;
  const valid = length >= 10 && length <= 500;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reject submission"
      description="The applicant will receive this reason and can re-submit a fresh Aadhaar QR."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={busy} disabled={!valid} onClick={() => onSubmit(reason.trim())}>Reject</Button>
        </>
      }
    >
      <Field label="Reason" hint={`${length}/500 · at least 10 characters`} error={length > 500 ? "At most 500 characters" : null}>
        {(p) => <Textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Identity details could not be confirmed from the provided Aadhaar." />}
      </Field>
    </Modal>
  );
}

function SuspendModal({ open, busy, onClose, onSubmit }: { open: boolean; busy: boolean; onClose: () => void; onSubmit: (code: string) => void }) {
  const [code, setCode] = useState(SUSPEND_CODES[0]);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Suspend seller"
      description="Listing privileges will be suspended until the seller is reinstated."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={busy} onClick={() => onSubmit(code)}>Suspend</Button>
        </>
      }
    >
      <Field label="Reason code">
        {(p) => (
          <Select {...p} value={code} onChange={(e) => setCode(e.target.value)}>
            {SUSPEND_CODES.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        )}
      </Field>
    </Modal>
  );
}
