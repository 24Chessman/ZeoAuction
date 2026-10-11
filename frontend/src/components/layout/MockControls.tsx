import { useState } from "react";
import { FlaskConical, RotateCcw, Unplug, X } from "lucide-react";
import { mockNetwork, mockServer } from "@/lib/mock";
import { session } from "@/lib/api";
import { DEV_PASSWORD } from "@/lib/mock/seed";

/**
 * Demo controls, mock mode only: drop the live connection to show the reconnect banner, and
 * reset the synthetic data. Not part of the real product.
 */
export function MockControls() {
  const [open, setOpen] = useState(false);

  return (
    <div className="fixed bottom-4 left-4 z-40">
      {open ? (
        <div className="w-72 rounded-2xl border border-line bg-surface/95 p-4 shadow-lift backdrop-blur-md animate-toast-in">
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-2 text-sm font-semibold">
              <FlaskConical className="size-4 text-brand-ink" aria-hidden /> Demo controls
            </p>
            <button onClick={() => setOpen(false)} className="rounded-md p-1 text-ink-faint hover:text-ink" aria-label="Close demo controls">
              <X className="size-4" />
            </button>
          </div>
          <p className="mt-1 text-xs text-ink-faint">Mock mode. Accounts use the password <code className="font-mono">{DEV_PASSWORD}</code>.</p>
          <ul className="mt-2 space-y-0.5 font-mono text-[11px] text-ink-muted">
            <li>buyer1@zeo.local · buyer2@zeo.local</li>
            <li>seller@zeo.local · unverified@zeo.local</li>
            <li>admin@zeo.local</li>
          </ul>
          <div className="mt-3 grid gap-2">
            <button onClick={() => mockNetwork.dropFor(6000)} className="flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-left text-sm hover:bg-surface-2">
              <Unplug className="size-4 text-live" aria-hidden /> Drop connection for 6 s
            </button>
            <button
              onClick={() => {
                mockServer().reset();
                session.clear();
                window.location.assign("/");
              }}
              className="flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-left text-sm hover:bg-surface-2"
            >
              <RotateCcw className="size-4 text-ink-muted" aria-hidden /> Reset demo data
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-2 rounded-full border border-line bg-surface/90 px-3 py-2 text-xs font-medium text-ink-muted shadow-lift backdrop-blur-md hover:text-ink"
        >
          <FlaskConical className="size-3.5 text-brand-ink" aria-hidden /> Demo
        </button>
      )}
    </div>
  );
}
