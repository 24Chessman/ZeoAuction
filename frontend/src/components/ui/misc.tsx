import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { formatRemaining } from "@/lib/format";
import { formatMoney, parseMoney, type Cents } from "@/lib/money";

export function EmptyState({ icon, title, children, action, className }: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-2xl border border-dashed border-line-strong px-6 py-14 text-center", className)}>
      <span className="grid size-12 place-items-center rounded-2xl bg-surface-2 text-ink-muted ring-1 ring-line">{icon}</span>
      <h3 className="mt-4 text-[15px] font-semibold">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-sm text-ink-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/** Re-renders every `interval` ms; one shared clock per component. */
export function useNow(interval = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(timer);
  }, [interval]);
  return now;
}

export function Countdown({ to, className, urgentBelowMs = 0 }: { to: string; className?: string; urgentBelowMs?: number }) {
  const now = useNow();
  const remaining = Date.parse(to) - now;
  return (
    <time dateTime={to} className={cn("tnum font-mono", remaining > 0 && remaining < urgentBelowMs && "text-live", className)}>
      {formatRemaining(remaining)}
    </time>
  );
}

export function Money({ value, cents, currency, className }: { value?: string; cents?: Cents; currency: string; className?: string }) {
  const amount = cents ?? (value ? parseMoney(value) : 0);
  return <span className={cn("tnum", className)}>{formatMoney(amount, currency)}</span>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-md border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">{children}</kbd>;
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: ReactNode; title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.03em] sm:text-[34px]">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-[15px] text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
