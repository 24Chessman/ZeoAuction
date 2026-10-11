import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, ExternalLink, Eye, FileText, Image as ImageIcon, Play, RotateCcw, ShieldOff, X } from "lucide-react";
import { adminKycApi, type AdminKycDocument, type AdminKycEvent, type AdminSubmission, type DocType } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatBytes, formatDateTime, shortId } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { Banner, Button, Card, CardBody, CardHeader, Field, KycBadge, Modal, Select, Skeleton, Spinner, Textarea, useNow, useToast } from "@/components/ui";
import { KycStatusStrip } from "@/components/kyc/KycStatusStrip";

const DOC_LABEL: Record<DocType, string> = { GOVERNMENT_ID: "Government ID", PROOF_OF_ADDRESS: "Proof of address", SELFIE: "Selfie" };
const SUSPEND_CODES = ["DOCUMENT_FORGERY", "IDENTITY_MISMATCH", "FRAUD_SUSPECTED", "POLICY_VIOLATION"];

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
        <Skeleton className="mt-6 h-96 w-full rounded-2xl" />
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
  const [viewing, setViewing] = useState<AdminKycDocument | null>(null);

  const act = async (event: AdminKycEvent, body?: { reason?: string; reason_code?: string }) => {
    setBusy(event);
    setError(null);
    try {
      const next = await adminKycApi.transition(submission.submission_id, event, body);
      onChange(next);
      setRejecting(false);
      setSuspending(false);
      const titles: Record<AdminKycEvent, string> = {
        "start-review": "Review started",
        approve: "Seller approved",
        reject: "Submission rejected",
        suspend: "Seller suspended",
        reinstate: "Seller reinstated",
      };
      toast({ tone: event === "approve" || event === "reinstate" ? "positive" : event === "start-review" ? "info" : "warning", title: titles[event], description: event === "start-review" ? undefined : "The seller's next token refresh carries the new status." });
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

        <Card>
          <CardHeader title="Documents" description="Each one opens through a signed link that expires after 60 seconds. Opening it is recorded in the audit log." />
          <CardBody>
            {submission.documents.length === 0 ? (
              <p className="text-sm text-ink-muted">No documents on this submission.</p>
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2">
                {submission.documents.map((doc) => (
                  <li key={doc.document_id} className="flex flex-col rounded-2xl border border-line p-4">
                    <div className="flex items-center gap-3">
                      <span className="grid size-10 place-items-center rounded-xl bg-surface-2 text-ink-muted">
                        {doc.mime_type === "application/pdf" ? <FileText className="size-5" /> : <ImageIcon className="size-5" />}
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold">{DOC_LABEL[doc.doc_type]}</p>
                        <p className="text-xs text-ink-faint">{doc.mime_type} · {formatBytes(doc.size_bytes)}</p>
                      </div>
                    </div>
                    <p className="mt-3 truncate font-mono text-[11px] text-ink-faint" title={doc.sha256}>sha256 {doc.sha256.slice(0, 24)}…</p>
                    <Button variant="secondary" size="sm" className="mt-3" icon={<Eye className="size-3.5" />} onClick={() => setViewing(doc)}>
                      View document
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
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
            {s === "SUBMITTED" && (
              <>
                <p className="text-sm text-ink-muted">Start the review to unlock approve and reject.</p>
                <Button className="w-full" loading={busy === "start-review"} icon={<Play className="size-4" />} onClick={() => act("start-review")}>
                  Start review
                </Button>
              </>
            )}
            {s === "UNDER_REVIEW" && (
              <>
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
                <Banner tone="positive" title="Approved">This seller can list auctions.</Banner>
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
              <Banner tone="danger" title="Rejected">“{submission.rejection_reason}” The seller can resubmit.</Banner>
            )}
          </CardBody>
        </Card>
        <Card className="p-5 text-sm">
          <dl className="space-y-2.5">
            <Meta label="Applicant" value={<span className="font-mono text-xs" title={submission.user_id}>…{shortId(submission.user_id)}</span>} />
            <Meta label="Submitted" value={formatDateTime(submission.submitted_at)} />
            <Meta label="Decided" value={formatDateTime(submission.decided_at)} />
            {submission.decided_by && <Meta label="Decided by" value={<span className="font-mono text-xs">…{shortId(submission.decided_by)}</span>} />}
          </dl>
        </Card>
      </aside>

      <RejectModal open={rejecting} busy={busy === "reject"} onClose={() => setRejecting(false)} onSubmit={(reason) => act("reject", { reason })} />
      <SuspendModal open={suspending} busy={busy === "suspend"} onClose={() => setSuspending(false)} onSubmit={(code) => act("suspend", { reason_code: code })} />
      {viewing && <DocumentViewer submissionId={submission.submission_id} document={viewing} onClose={() => setViewing(null)} />}
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
      description="The seller sees this reason and can upload new documents."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={busy} disabled={!valid} onClick={() => onSubmit(reason.trim())}>Reject</Button>
        </>
      }
    >
      <Field label="Reason" hint={`${length}/500 · at least 10 characters`} error={length > 500 ? "At most 500 characters" : null}>
        {(p) => <Textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. The proof of address is older than three months." />}
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
      description="Listing is refused until the seller is reinstated. The seller's token is refreshed at once."
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

/** Fetches a fresh signed URL each time it opens; the link is never cached or stored. */
function DocumentViewer({ submissionId, document, onClose }: { submissionId: string; document: AdminKycDocument; onClose: () => void }) {
  const { data, error, loading, reload } = useAsync(() => adminKycApi.documentUrl(submissionId, document.document_id), [document.document_id]);
  const [openedAt] = useState(() => Date.now());
  const now = useNow(1000);
  const left = data ? Math.max(0, data.expires_in - Math.floor((now - openedAt) / 1000)) : null;
  const pdf = document.mime_type === "application/pdf" && !data?.url.startsWith("data:image");

  return (
    <Modal
      open
      onClose={onClose}
      size="xl"
      title={DOC_LABEL[document.doc_type]}
      description={left !== null ? (left > 0 ? `Signed link expires in ${left}s · this view is audited` : "The signed link has expired.") : "Requesting a signed link…"}
      footer={
        <>
          {left === 0 && <Button variant="secondary" onClick={() => void reload()} icon={<RotateCcw className="size-4" />}>Get a new link</Button>}
          {data && left !== 0 && (
            <a href={data.url} target="_blank" rel="noreferrer noopener" className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm font-medium text-ink-muted hover:bg-surface-2 hover:text-ink">
              <ExternalLink className="size-4" /> Open in new tab
            </a>
          )}
          <Button onClick={onClose}>Done</Button>
        </>
      }
    >
      <div className="grid min-h-[50vh] place-items-center rounded-2xl bg-surface-2">
        {loading && !data ? (
          <Spinner label="Loading document" />
        ) : error ? (
          <Banner tone="danger" title={describeError(error).title}>{describeError(error).message}</Banner>
        ) : data ? (
          pdf ? (
            <iframe title={DOC_LABEL[document.doc_type]} src={data.url} className="h-[65vh] w-full rounded-2xl" />
          ) : (
            <img src={data.url} alt={`${DOC_LABEL[document.doc_type]} submitted for verification`} className="max-h-[65vh] w-auto rounded-xl object-contain" />
          )
        ) : null}
      </div>
    </Modal>
  );
}
