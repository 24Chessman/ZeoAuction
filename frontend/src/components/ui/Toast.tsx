import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, TrendingUp, X, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";

export type ToastTone = "info" | "positive" | "warning" | "danger" | "outbid";

export interface ToastInput {
  tone?: ToastTone;
  title: string;
  description?: ReactNode;
  action?: { label: string; onClick: () => void };
  duration?: number;
}

interface ToastItem extends ToastInput {
  id: number;
}

const ToastContext = createContext<(toast: ToastInput) => void>(() => undefined);

const icons: Record<ToastTone, ReactNode> = {
  info: <Info className="size-[18px] text-info" aria-hidden />,
  positive: <CheckCircle2 className="size-[18px] text-positive" aria-hidden />,
  warning: <AlertTriangle className="size-[18px] text-live" aria-hidden />,
  danger: <XCircle className="size-[18px] text-danger" aria-hidden />,
  outbid: <TrendingUp className="size-[18px] text-live" aria-hidden />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (toast: ToastInput) => {
      const id = next.current++;
      setItems((all) => [...all.slice(-3), { ...toast, id }]);
      setTimeout(() => dismiss(id), toast.duration ?? 5000);
    },
    [dismiss],
  );

  const value = useMemo(() => push, [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6" aria-live="polite" aria-relevant="additions">
        {items.map((toast) => (
          <div
            key={toast.id}
            role={toast.tone === "danger" || toast.tone === "outbid" ? "alert" : "status"}
            className={cn(
              "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-2xl border bg-surface/95 p-4 shadow-lift backdrop-blur-md animate-toast-in",
              toast.tone === "outbid" ? "border-live/40" : "border-line",
            )}
          >
            <span className="mt-px">{icons[toast.tone ?? "info"]}</span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink">{toast.title}</p>
              {toast.description && <div className="mt-0.5 text-sm text-ink-muted">{toast.description}</div>}
              {toast.action && (
                <button
                  className="mt-2 text-sm font-semibold text-brand-ink hover:underline"
                  onClick={() => {
                    toast.action?.onClick();
                    dismiss(toast.id);
                  }}
                >
                  {toast.action.label}
                </button>
              )}
            </div>
            <button onClick={() => dismiss(toast.id)} className="-m-1 rounded-md p-1 text-ink-faint hover:text-ink" aria-label="Dismiss">
              <X className="size-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): (toast: ToastInput) => void {
  return useContext(ToastContext);
}
