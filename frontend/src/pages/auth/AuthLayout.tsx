import type { ReactNode } from "react";
import { BadgeCheck, Landmark, Timer } from "lucide-react";
import { LogoMark } from "@/components/layout/Logo";
import { formatMoney } from "@/lib/money";
import { policy } from "@/lib/policy";

export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle: ReactNode; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="mx-auto grid min-h-[calc(100dvh-10rem)] max-w-page items-stretch gap-10 px-4 py-10 sm:px-6 lg:grid-cols-2 lg:py-16">
      <div className="flex flex-col justify-center">
        <div className="mx-auto w-full max-w-sm animate-fade-up">
          <h1 className="text-[28px] font-semibold tracking-[-0.03em]">{title}</h1>
          <p className="mt-2 text-[15px] text-ink-muted">{subtitle}</p>
          <div className="mt-8">{children}</div>
          <div className="mt-8 text-center text-sm text-ink-muted">{footer}</div>
        </div>
      </div>
      <aside className="relative hidden overflow-hidden rounded-[2rem] bg-ink p-10 text-canvas lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -right-20 -top-20 size-80 rounded-full bg-brand/50 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute -bottom-24 -left-10 size-80 rounded-full bg-info/30 blur-3xl" aria-hidden />
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{ backgroundImage: "linear-gradient(currentColor 1px, transparent 1px), linear-gradient(90deg, currentColor 1px, transparent 1px)", backgroundSize: "40px 40px" }}
          aria-hidden
        />
        <LogoMark className="relative size-10" />
        <div className="relative">
          <p className="text-3xl font-semibold leading-tight tracking-[-0.03em]">Every safeguard,<br />visible before you bid.</p>
          <ul className="mt-8 space-y-4 text-canvas/75">
            <li className="flex items-center gap-3"><BadgeCheck className="size-5 text-canvas" aria-hidden /> Sellers are verified before they list</li>
            <li className="flex items-center gap-3"><Landmark className="size-5 text-canvas" aria-hidden /> Payment held in escrow for {policy.protectionDays} days (simulated)</li>
            <li className="flex items-center gap-3"><Timer className="size-5 text-canvas" aria-hidden /> {formatMoney(policy.feeCents, policy.currency)} flat fee, only if you win</li>
          </ul>
        </div>
        <p className="relative text-xs text-canvas/50">Test mode. No real money moves.</p>
      </aside>
    </div>
  );
}
