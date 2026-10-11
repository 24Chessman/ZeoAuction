import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} aria-hidden>
      <defs>
        <linearGradient id="zeo-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="rgb(var(--brand))" />
          <stop offset="1" stopColor="rgb(var(--brand-strong))" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#zeo-mark)" />
      <path d="M10 10.5h12l-12 11h12" fill="none" stroke="rgb(var(--on-brand))" strokeWidth="2.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <Link to="/" className={cn("group flex items-center gap-2.5 rounded-lg", className)} aria-label="ZeoAuction home">
      <LogoMark className="transition-transform duration-300 group-hover:rotate-[-8deg]" />
      <span className="text-[17px] font-semibold tracking-[-0.03em]">
        Zeo<span className="text-ink-muted">Auction</span>
      </span>
    </Link>
  );
}
