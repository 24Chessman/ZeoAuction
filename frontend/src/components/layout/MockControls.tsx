import { useState } from "react";
import { FlaskConical, RotateCcw, Server, Unplug, X, Zap } from "lucide-react";
import { mockNetwork, mockServer } from "@/lib/mock";
import { session } from "@/lib/api";
import { DEV_PASSWORD } from "@/lib/mock/seed";
import { serviceUrls, toggleAppMode, useMocks } from "@/lib/config";

/**
 * Runtime environment & mode switcher:
 * Allows switching between Demo (in-browser mock simulation) and Prod (live API Gateway / microservices)
 * directly in the deployed app without rebuilding or changing environment files.
 */
export function MockControls() {
  const [open, setOpen] = useState(false);

  return (
    <div className="fixed bottom-4 left-4 z-40">
      {open ? (
        <div className="w-80 rounded-3xl border border-line bg-surface p-4 shadow-float animate-toast-in">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {useMocks ? (
                <span className="flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-600 dark:text-amber-400">
                  <FlaskConical className="size-3.5" aria-hidden /> Demo Mode
                </span>
              ) : (
                <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                  <Zap className="size-3.5" aria-hidden /> Prod Mode
                </span>
              )}
            </div>
            <button
              onClick={() => setOpen(false)}
              className="rounded-md p-1 text-ink-faint hover:text-ink"
              aria-label="Close controls"
            >
              <X className="size-4" />
            </button>
          </div>

          <div className="mt-3">
            {useMocks ? (
              <div className="space-y-3">
                <p className="text-xs text-ink-faint">
                  Running in-memory simulation. Accounts use the password{" "}
                  <code className="font-mono text-ink">{DEV_PASSWORD}</code>.
                </p>

                <button
                  onClick={() => {
                    session.clear();
                    toggleAppMode(false);
                  }}
                  className="flex w-full items-center justify-center gap-2 rounded-2xl bg-brand-ink px-3 py-2.5 text-center text-xs font-semibold text-white shadow-lift hover:opacity-90 transition-opacity"
                >
                  <Zap className="size-3.5 text-emerald-300" aria-hidden /> Switch to Prod (Live Stack)
                </button>

                <ul className="space-y-0.5 font-mono text-[11px] text-ink-muted">
                  <li>buyer1@zeo.local · buyer2@zeo.local</li>
                  <li>seller@zeo.local · unverified@zeo.local</li>
                  <li>admin@zeo.local</li>
                </ul>

                <div className="grid gap-2 border-t border-line/60 pt-2">
                  <button
                    onClick={() => mockNetwork.dropFor(6000)}
                    className="flex items-center gap-2 rounded-2xl border border-line px-3 py-2 text-left text-xs hover:bg-surface-2"
                  >
                    <Unplug className="size-3.5 text-live" aria-hidden /> Drop connection for 6 s
                  </button>
                  <button
                    onClick={() => {
                      mockServer().reset();
                      session.clear();
                      window.location.assign("/");
                    }}
                    className="flex items-center gap-2 rounded-2xl border border-line px-3 py-2 text-left text-xs hover:bg-surface-2"
                  >
                    <RotateCcw className="size-3.5 text-ink-muted" aria-hidden /> Reset demo data
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-xs text-ink-faint">
                  Connected to real backend microservices via API Gateway.
                </p>

                <div className="rounded-2xl border border-line bg-surface-2 p-2.5 text-[11px]">
                  <p className="flex items-center gap-1.5 font-medium text-ink-muted">
                    <Server className="size-3 text-ink-faint" /> Target API Gateway:
                  </p>
                  <p className="mt-1 truncate font-mono text-ink">{serviceUrls.auth}</p>
                </div>

                <button
                  onClick={() => {
                    session.clear();
                    toggleAppMode(true);
                  }}
                  className="flex w-full items-center justify-center gap-2 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-center text-xs font-semibold text-amber-700 dark:text-amber-300 hover:bg-amber-500/20 transition-colors"
                >
                  <FlaskConical className="size-3.5 text-amber-500" aria-hidden /> Switch to Demo Mode
                </button>
              </div>
            )}
          </div>
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className={`flex items-center gap-2 rounded-full border px-3.5 py-2 text-xs font-semibold shadow-lift transition-all hover:scale-105 ${
            useMocks
              ? "border-amber-500/40 bg-surface text-amber-600 dark:text-amber-400"
              : "border-emerald-500/40 bg-surface text-emerald-600 dark:text-emerald-400"
          }`}
        >
          {useMocks ? (
            <>
              <FlaskConical className="size-3.5 text-amber-500" aria-hidden /> Demo
            </>
          ) : (
            <>
              <Zap className="size-3.5 text-emerald-500" aria-hidden /> Prod
            </>
          )}
        </button>
      )}
    </div>
  );
}
