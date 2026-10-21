import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, ExternalLink, Eye, Fingerprint, Image as ImageIcon, RotateCcw, ScanFace, ShieldOff, X } from "lucide-react";
import {
  adminKycApi, type AdminKycDocument, type AdminKycEvent, type AdminSubmission, type DocType, type DocumentUrl, type FaceAttemptRecord,
} from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatBytes, formatDateTime, shortId } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { Banner, Button, Card, CardBody, CardHeader, Field, KycBadge, Modal, Select, Skeleton, Spinner, Table, Td, Textarea, Th, useNow, useToast } from "@/components/ui";
import { KycStatusStrip } from "@/components/kyc/KycStatusStrip";

const DOC_LABEL: Record<DocType, string> = { AADHAAR_PHOTO: "Aadhaar photo", FACE_CAPTURE: "Live capture" };
const SUSPEND_CODES = ["IDENTITY_MISMATCH", "AADHAAR_MISUSE", "FRAUD_SUSPECTED", "POLICY_VIOLATION"];
const OUTCOME_LABEL: Record<FaceAttemptRecord["outcome"], string> = {
  MATCH: "Match", REVIEW: "Close: review", NO_MATCH: "No match", LIVENESS_FAILED: "Liveness failed", NO_FACE: "No face",
};
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
        approve: "Seller approved",
        reject: "Submission rejected",
        suspend: "Seller suspended",
        reinstate: "Seller reinstated",
      };
      toast({ tone: event === "approve" || event === "reinstate" ? "positive" : "warning", title: titles[event], description: "The seller's next token refresh carries the new status." });
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(null);
    }
  };

  const s = submission.state;
  const photo = submission.documents.find((d) => d.doc_type === "AADHAAR_PHOTO") ?? null;
  const capture = submission.documents.find((d) => d.doc_type === "FACE_CAPTURE") ?? null;
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

        <ComparePhotos submissionId={submission.submission_id} photo={photo} capture={capture} onEnlarge={setViewing} />

        <AadhaarCard submission={submission} />

        <Card className="overflow-hidden">
          <CardHeader title="Face check attempts" description="SFace cosine similarity to the Aadhaar photo. Automatic match at 0.42, review from 0.30." />
          <CardBody className="px-0 pb-0 sm:px-0">
            {submission.face_attempts.length === 0 ? (
              <p className="px-5 pb-5 text-sm text-ink-muted sm:px-6">No face check yet.</p>
            ) : (
              <Table>
                <thead>
                  <tr><Th>#</Th><Th>Outcome</Th><Th>Median</Th><Th>Lowest</Th><Th>Head turn</Th><Th>Frames</Th><Th>When</Th></tr>
                </thead>
                <tbody>
                  {submission.face_attempts.map((a) => (
                    <tr key={a.attempt_no}>
                      <Td className="font-mono text-[13px]">{a.attempt_no}</Td>
                      <Td className="whitespace-nowrap font-medium">{OUTCOME_LABEL[a.outcome]}</Td>
                      <Td className="tnum font-mono text-[13px]">{a.median_score?.toFixed(3) ?? "—"}</Td>
                      <Td className="tnum font-mono text-[13px]">{a.min_score?.toFixed(3) ?? "—"}</Td>
                      <Td className="tnum font-mono text-[13px]">{a.yaw_span?.toFixed(2) ?? "—"}</Td>
                      <Td className="tnum text-[13px]">{a.good_frames}/{a.frames}</Td>
                      <Td className="whitespace-nowrap text-ink-muted">{formatDateTime(a.at)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
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
              <p className="text-sm text-ink-muted">Waiting for the seller's face check. A clear match verifies them on its own; a close one comes back here.</p>
            )}
            {s === "UNDER_REVIEW" && (
              <>
                <p className="text-sm text-ink-muted">Compare the live capture with the Aadhaar photo. Approve only if it's clearly the same person.</p>
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
              <Banner tone="danger" title="Rejected">“{submission.rejection_reason}”</Banner>
            )}
          </CardBody>
        </Card>
        <Card className="p-5 text-sm">
          <dl className="space-y-2.5">
            <Meta label="Applicant" value={<span className="font-mono text-xs" title={submission.user_id}>…{shortId(submission.user_id)}</span>} />
            <Meta label="Submitted" value={formatDateTime(submission.submitted_at)} />
            <Meta label="Decided" value={formatDateTime(submission.decided_at)} />
            <Meta label="Decided by" value={submission.decided_by ? <span className="font-mono text-xs">…{shortId(submission.decided_by)}</span> : submission.decided_at ? "Face check" : "—"} />
          </dl>
        </Card>
      </aside>

      <RejectModal open={rejecting} busy={busy === "reject"} onClose={() => setRejecting(false)} onSubmit={(reason) => act("reject", { reason })} />
      <SuspendModal open={suspending} busy={busy === "suspend"} onClose={() => setSuspending(false)} onSubmit={(code) => act("suspend", { reason_code: code })} />
      {viewing && <DocumentViewer submissionId={submission.submission_id} document={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

/** Both images behind one deliberate click: each opening is a signed 60 s link and is audited. */
function ComparePhotos({ submissionId, photo, capture, onEnlarge }: {
  submissionId: string; photo: AdminKycDocument | null; capture: AdminKycDocument | null; onEnlarge: (d: AdminKycDocument) => void;
}) {
  const [urls, setUrls] = useState<Record<string, DocumentUrl> | null>(null);
  const [openedAt, setOpenedAt] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const now = useNow(1000);
  const docs = [photo, capture].filter((d): d is AdminKycDocument => d !== null);
  const left = urls ? Math.max(0, 60 - Math.floor((now - openedAt) / 1000)) : null;

  const open = async () => {
    setLoading(true);
    setError(null);
    try {
      const fetched = await Promise.all(docs.map(async (d) => [d.document_id, await adminKycApi.documentUrl(submissionId, d.document_id)] as const));
      setUrls(Object.fromEntries(fetched));
      setOpenedAt(Date.now());
    } catch (caught) {
      setError(caught);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Compare photos"
        description="Opening them requests signed links that expire after 60 seconds. Each view is written to the audit log."
        action={docs.length > 0 && (!urls || left === 0) ? (
          <Button size="sm" variant="secondary" loading={loading} icon={<Eye className="size-3.5" />} onClick={() => void open()}>
            {urls ? "Open again" : "Open photos"}
          </Button>
        ) : null}
      />
      <CardBody>
        {error ? <Banner tone="danger" title={describeError(error).title} className="mb-4">{describeError(error).message}</Banner> : null}
        <div className="grid gap-4 sm:grid-cols-2">
          {([["AADHAAR_PHOTO", photo, Fingerprint], ["FACE_CAPTURE", capture, ScanFace]] as const).map(([type, doc, Icon]) => {
            const url = doc && urls && left ? urls[doc.document_id]?.url : null;
            return (
              <figure key={type} className="flex flex-col gap-2">
                <div className="grid aspect-[4/5] place-items-center overflow-hidden rounded-3xl bg-surface-2">
                  {url ? (
                    <button type="button" onClick={() => doc && onEnlarge(doc)} className="size-full" aria-label={`Enlarge ${DOC_LABEL[type]}`}>
                      <img src={url} alt={`${DOC_LABEL[type]} submitted for verification`} className="size-full object-cover" />
                    </button>
                  ) : (
                    <div className="flex flex-col items-center gap-2 text-ink-faint">
                      <Icon className="size-8" aria-hidden />
                      <span className="text-xs">{doc ? "Not opened" : type === "FACE_CAPTURE" ? "No capture kept" : "No photo"}</span>
                    </div>
                  )}
                </div>
                <figcaption className="flex items-center justify-between gap-2 text-xs">
                  <span className="font-semibold text-ink">{DOC_LABEL[type]}</span>
                  {doc && <span className="truncate font-mono text-ink-faint" title={doc.sha256}>{formatBytes(doc.size_bytes)} · {doc.sha256.slice(0, 10)}…</span>}
                </figcaption>
              </figure>
            );
          })}
        </div>
        {urls && left !== null && left > 0 && <p className="mt-3 text-xs text-ink-faint">Links expire in {left}s.</p>}
      </CardBody>
    </Card>
  );
}

function AadhaarCard({ submission }: { submission: AdminSubmission }) {
  const a = submission.aadhaar;
  return (
    <Card>
      <CardHeader title="Aadhaar Secure QR" description="Signature verified against UIDAI's certificate when the seller uploaded it." />
      <CardBody>
        {!a ? (
          <p className="text-sm text-ink-muted">No Aadhaar record on this submission (seeded before Aadhaar e-KYC).</p>
        ) : (
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
            <Item label="Name" value={a.holder_name} />
            <Item label="Aadhaar" value={<span className="font-mono">XXXX XXXX {a.reference_last4}</span>} />
            <Item label="Birth year" value={String(a.year_of_birth)} />
            <Item label="Gender" value={GENDER[a.gender] ?? a.gender} />
            <Item label="State · PIN" value={`${a.state ?? "—"} · ${a.pincode ?? "—"}`} />
            <Item label="Mobile" value={a.mobile_verified ? "Matched UIDAI hash" : "Not checked"} />
            <Item label="QR generated" value={formatDateTime(a.qr_generated_at)} />
            <Item label="Faces in Aadhaar photo" value={a.reference_faces === 1 ? "1 (usable)" : `${a.reference_faces} (not usable: review by eye)`} />
            <Item label="Signer" value={<span className="font-mono text-xs" title={a.signer_sha256}>{a.signer_sha256.slice(0, 16)}…</span>} />
          </dl>
        )}
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
      description="The seller sees this reason and can verify again with a fresh Aadhaar file."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={busy} disabled={!valid} onClick={() => onSubmit(reason.trim())}>Reject</Button>
        </>
      }
    >
      <Field label="Reason" hint={`${length}/500 · at least 10 characters`} error={length > 500 ? "At most 500 characters" : null}>
        {(p) => <Textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. The live capture shows a different person from the Aadhaar photo." />}
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
      <div className="grid min-h-[50vh] place-items-center rounded-3xl bg-surface-2">
        {loading && !data ? (
          <Spinner label="Loading image" />
        ) : error ? (
          <Banner tone="danger" title={describeError(error).title}>{describeError(error).message}</Banner>
        ) : data ? (
          <img src={data.url} alt={`${DOC_LABEL[document.doc_type]} submitted for verification`} className="max-h-[65vh] w-auto rounded-2xl object-contain" />
        ) : (
          <ImageIcon className="size-8 text-ink-faint" aria-hidden />
        )}
      </div>
    </Modal>
  );
}
