import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";

type BannerTone = "info" | "positive" | "warning" | "danger";

const styles: Record<BannerTone, { box: string; icon: ReactNode }> = {
  info: { box: "bg-info-soft/70 border-info/20 text-ink", icon: <Info className="size-[18px] text-info" aria-hidden /> },
  positive: { box: "bg-positive-soft/70 border-positive/20 text-ink", icon: <CheckCircle2 className="size-[18px] text-positive" aria-hidden /> },
  warning: { box: "bg-live-soft/70 border-live/25 text-ink", icon: <AlertTriangle className="size-[18px] text-live" aria-hidden /> },
  danger: { box: "bg-danger-soft/70 border-danger/20 text-ink", icon: <XCircle className="size-[18px] text-danger" aria-hidden /> },
};

interface BannerProps {
  tone?: BannerTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
  live?: boolean;
}

export function Banner({ tone = "info", title, children, action, className, live }: BannerProps) {
  const style = styles[tone];
  return (
    <div
      className={cn("flex items-start gap-3 rounded-xl border px-4 py-3 text-sm", style.box, className)}
      role={live ? (tone === "danger" ? "alert" : "status") : undefined}
    >
      <span className="mt-px shrink-0">{style.icon}</span>
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium text-ink">{title}</p>}
        {children && <div className={cn("text-ink-muted", title ? "mt-0.5" : null)}>{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}
