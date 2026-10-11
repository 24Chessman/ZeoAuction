import { Check, Clock3, FileUp, Search, ShieldAlert, ShieldCheck, X } from "lucide-react";
import type { KycStatus } from "@/lib/api";
import { cn } from "@/lib/cn";

/**
 * The KYC state machine as a progress strip (docs/state-machines.md §3):
 * SUBMITTED -> UNDER_REVIEW -> VERIFIED, with REJECTED and SUSPENDED as the off-ramps.
 */
const STEPS = [
  { id: "SUBMITTED", label: "Submitted", icon: FileUp },
  { id: "UNDER_REVIEW", label: "Under review", icon: Search },
  { id: "VERIFIED", label: "Verified", icon: ShieldCheck },
] as const;

function position(status: KycStatus): number {
  switch (status) {
    case "NOT_SUBMITTED": return -1;
    case "SUBMITTED": return 0;
    case "UNDER_REVIEW": return 1;
    case "REJECTED": return 2;
    default: return 2; // VERIFIED, SUSPENDED
  }
}

export function KycStatusStrip({ status }: { status: KycStatus }) {
  const at = position(status);
  const failed = status === "REJECTED" || status === "SUSPENDED";

  return (
    <ol className="grid grid-cols-3 gap-2" aria-label="Verification progress">
      {STEPS.map((step, index) => {
        const isLast = index === STEPS.length - 1;
        const done = index < at || (index === at && status === "VERIFIED");
        const current = index === at && !done;
        const Icon = isLast && failed ? (status === "REJECTED" ? X : ShieldAlert) : done ? Check : current ? Clock3 : step.icon;
        const label = isLast && failed ? (status === "REJECTED" ? "Rejected" : "Suspended") : step.label;
        return (
          <li key={step.id} className="flex flex-col gap-2" aria-current={current || (isLast && failed) ? "step" : undefined}>
            <div
              className={cn(
                "h-1.5 rounded-full transition-colors duration-500",
                isLast && failed ? "bg-danger" : done ? "bg-positive" : current ? "bg-brand" : "bg-surface-3",
              )}
            />
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "grid size-6 shrink-0 place-items-center rounded-full",
                  isLast && failed ? "bg-danger-soft text-danger" : done ? "bg-positive-soft text-positive" : current ? "bg-brand-soft text-brand-ink" : "bg-surface-2 text-ink-faint",
                )}
              >
                <Icon className="size-3.5" aria-hidden />
              </span>
              <span className={cn("text-[13px] font-medium", done || current || (isLast && failed) ? "text-ink" : "text-ink-faint")}>
                {label}
                <span className="sr-only">{done ? " (done)" : current ? " (current)" : ""}</span>
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
