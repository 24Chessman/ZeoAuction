import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Table({ className, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="-mx-px overflow-x-auto">
      <table className={cn("w-full border-separate border-spacing-0 text-sm", className)} {...rest} />
    </div>
  );
}

export function Th({ className, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th scope="col" className={cn("border-b border-line bg-surface-2/60 px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-[0.1em] text-ink-faint first:pl-5 last:pr-5", className)} {...rest} />;
}

export function Td({ className, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b border-line px-4 py-3 align-middle text-ink first:pl-5 last:pr-5 [tr:last-child>&]:border-b-0", className)} {...rest} />;
}
