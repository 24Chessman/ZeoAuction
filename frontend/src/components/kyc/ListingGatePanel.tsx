import { ArrowRight, HelpCircle } from "lucide-react";
import type { KycStatus } from "@/lib/api";
import { ButtonLink } from "@/components/ui";

const REASON: Record<Exclude<KycStatus, "VERIFIED">, string> = {
  NOT_SUBMITTED: "You haven't submitted identity documents yet.",
  SUBMITTED: "Your documents are waiting for an administrator to pick them up.",
  UNDER_REVIEW: "An administrator is reviewing your documents right now.",
  REJECTED: "Your last submission was rejected. Fix the issue below and submit again.",
  SUSPENDED: "Your seller verification has been suspended by an administrator.",
};

/** "Why can't I list yet?" — names the exact refusal the API gives (SDD Fig. 8.4). */
export function ListingGatePanel({ status, showAction = true }: { status: KycStatus; showAction?: boolean }) {
  if (status === "VERIFIED") return null;
  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <p className="flex items-center gap-2 font-semibold">
        <HelpCircle className="size-[18px] text-brand-ink" aria-hidden /> Why can't I list yet?
      </p>
      <p className="mt-2 text-sm text-ink-muted">{REASON[status]}</p>
      <p className="mt-3 text-sm text-ink-muted">
        Until you're verified, creating an auction is refused by the server with{" "}
        <code className="rounded-md bg-danger-soft px-1.5 py-0.5 font-mono text-xs font-semibold text-danger">SELLER_NOT_VERIFIED</code>{" "}
        <span className="text-ink-faint">(HTTP 403, kyc_status: {status})</span>.
      </p>
      {showAction && (status === "NOT_SUBMITTED" || status === "REJECTED") && (
        <ButtonLink to="/sell/verify" className="mt-4" iconRight={<ArrowRight className="size-4" />}>
          {status === "REJECTED" ? "Resubmit documents" : "Start verification"}
        </ButtonLink>
      )}
    </div>
  );
}
