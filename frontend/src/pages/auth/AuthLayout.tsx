import type { ReactNode } from "react";
import { BadgeCheck, Landmark, Timer } from "lucide-react";
import { formatMoney } from "@/lib/money";
import { photoFor } from "@/lib/photos";
import { policy } from "@/lib/policy";

const photo = photoFor("", "watches");

export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle: ReactNode; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="mx-auto grid min-h-[calc(100dvh-10rem)] max-w-page items-stretch gap-10 px-4 py-10 sm:px-6 lg:grid-cols-2 lg:py-14">
      <div className="flex flex-col justify-center">
        <div className="mx-auto w-full max-w-sm animate-fade-up">
          <h1 className="text-[44px] font-semibold leading-[1.02] tracking-[-0.035em]">{title}</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-ink-muted">{subtitle}</p>
          <div className="mt-8">{children}</div>
          <div className="mt-8 text-center text-sm text-ink-muted">{footer}</div>
        </div>
      </div>
      <aside className="bg-midnight relative hidden overflow-hidden rounded-4xl text-white shadow-float lg:flex lg:flex-col lg:justify-end">
        <img src={photo.src} alt="" className="absolute inset-0 size-full object-cover opacity-60 mix-blend-luminosity" />
        <div className="absolute inset-0 bg-gradient-to-t from-night via-night/70 to-night/10" aria-hidden />
        <div className="relative p-10">
          <p className="font-display text-[42px] font-semibold leading-[1.02] tracking-[-0.035em]">
            Every safeguard,
            <br />
            <span className="text-brand">visible before you bid.</span>
          </p>
          <ul className="mt-8 space-y-3">
            <Point icon={<BadgeCheck className="size-[18px]" aria-hidden />}>Sellers are verified before they list</Point>
            <Point icon={<Landmark className="size-[18px]" aria-hidden />}>Payment held in escrow for {policy.protectionDays} days (simulated)</Point>
            <Point icon={<Timer className="size-[18px]" aria-hidden />}>{formatMoney(policy.feeCents, policy.currency)} flat fee, only if you win</Point>
          </ul>
          <p className="mt-10 text-xs text-white/50">
            Test mode. No real money moves. Photo: {photo.photographer} on Pexels.
          </p>
        </div>
      </aside>
    </div>
  );
}

function Point({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <li className="flex items-center gap-3 text-white/85">
      <span className="grid size-9 place-items-center rounded-xl bg-white/10 text-brand backdrop-blur">{icon}</span>
      {children}
    </li>
  );
}
