import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { AuctionState, KycStatus } from "@/lib/api/types";

export type Tone = "neutral" | "brand" | "positive" | "live" | "danger" | "info";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-muted ring-line-strong/60",
  brand: "bg-brand-soft text-brand-ink ring-brand/20",
  positive: "bg-positive-soft text-positive ring-positive/20",
  live: "bg-live-soft text-live ring-live/25",
  danger: "bg-danger-soft text-danger ring-danger/20",
  info: "bg-info-soft text-info ring-info/20",
};

const dots: Record<Tone, string> = {
  neutral: "bg-ink-faint",
  brand: "bg-brand",
  positive: "bg-positive",
  live: "bg-live",
  danger: "bg-danger",
  info: "bg-info",
};

interface BadgeProps {
  tone?: Tone;
  dot?: boolean;
  pulse?: boolean;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Badge({ tone = "neutral", dot, pulse, icon, className, children }: BadgeProps) {
  return (
    <span className={cn("inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-xs font-medium ring-1 ring-inset", tones[tone], className)}>
      {dot && (
        <span className="relative flex size-1.5">
          {pulse && <span className={cn("absolute inline-flex size-full animate-live-ping rounded-full", dots[tone])} />}
          <span className={cn("relative inline-flex size-1.5 rounded-full", dots[tone])} />
        </span>
      )}
      {icon}
      {children}
    </span>
  );
}

/** Labels follow docs/state-machines.md exactly; only the wording is friendlier. */
const AUCTION: Record<AuctionState, { label: string; tone: Tone }> = {
  DRAFT: { label: "Draft", tone: "neutral" },
  SCHEDULED: { label: "Scheduled", tone: "info" },
  OPEN: { label: "Live", tone: "live" },
  EXTENDED: { label: "Live · extended", tone: "live" },
  CLOSING: { label: "Closing", tone: "live" },
  CLOSED: { label: "Closed", tone: "neutral" },
  SETTLED: { label: "Settled", tone: "positive" },
  CANCELLED: { label: "Cancelled", tone: "danger" },
};

export function AuctionStateBadge({ state, className }: { state: AuctionState; className?: string }) {
  const { label, tone } = AUCTION[state];
  const live = state === "OPEN" || state === "EXTENDED";
  return (
    <Badge tone={tone} dot pulse={live} className={className}>
      {label}
    </Badge>
  );
}

export const KYC_LABEL: Record<KycStatus, { label: string; tone: Tone }> = {
  NOT_SUBMITTED: { label: "Not verified", tone: "neutral" },
  SUBMITTED: { label: "Submitted", tone: "info" },
  UNDER_REVIEW: { label: "Under review", tone: "info" },
  VERIFIED: { label: "Verified seller", tone: "positive" },
  REJECTED: { label: "Rejected", tone: "danger" },
  SUSPENDED: { label: "Suspended", tone: "danger" },
};

export function KycBadge({ status, className }: { status: KycStatus; className?: string }) {
  const { label, tone } = KYC_LABEL[status];
  return (
    <Badge tone={tone} dot className={className}>
      {label}
    </Badge>
  );
}
