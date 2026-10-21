import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";

/** A rounded tile with a stroked Z and a persimmon "hammer" dot at its corner. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} aria-hidden>
      <rect width="32" height="32" rx="10" fill="rgb(var(--ink))" />
      <path d="M10 10.5h12L10 21.5h12" fill="none" stroke="rgb(var(--canvas))" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="24.5" cy="7.5" r="3.5" fill="rgb(var(--brand))" stroke="rgb(var(--ink))" strokeWidth="1.5" />
    </svg>
  );
}

export function Logo({ className, tone = "default" }: { className?: string; tone?: "default" | "night" }) {
  return (
    <Link to="/" className={cn("group flex items-center gap-2.5 rounded-lg", className)} aria-label="ZeoAuction home">
      <LogoMark className={cn("rounded-[10px] transition-transform duration-300 group-hover:-rotate-6", tone === "night" && "ring-1 ring-white/25")} />
      <span className={cn("font-display text-[21px] font-bold leading-none tracking-[-0.04em]", tone === "night" && "text-white")}>
        zeo<span className="text-brand">auction</span>
      </span>
    </Link>
  );
}
