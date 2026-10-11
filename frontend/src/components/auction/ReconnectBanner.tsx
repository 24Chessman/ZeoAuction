import { RefreshCw, WifiOff } from "lucide-react";
import { useConnectionStatus } from "@/app/live";
import { useNow } from "@/components/ui";
import { CLOSE_RATE_LIMITED, CLOSE_TOKEN_EXPIRED } from "@/lib/live/LiveClient";

/**
 * Shown whenever live prices are not flowing, so a frozen price is never mistaken for a quiet
 * auction. It goes away on its own once the gateway resubscribes and sends the snapshot.
 */
export function ReconnectBanner() {
  const info = useConnectionStatus();
  const now = useNow(500);
  if (info.status !== "reconnecting" && info.status !== "offline") return null;

  const seconds = info.retryAt ? Math.max(0, Math.ceil((info.retryAt - now) / 1000)) : null;
  const reason =
    info.status === "offline"
      ? "Your device is offline."
      : info.lastCloseCode === CLOSE_TOKEN_EXPIRED
        ? "Refreshing your session."
        : info.lastCloseCode === CLOSE_RATE_LIMITED
          ? "Too many messages; backing off."
          : "The live connection dropped.";

  return (
    <div role="status" className="flex items-center gap-3 rounded-2xl border border-live/30 bg-live-soft/80 px-4 py-3 text-sm animate-fade-up">
      <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-surface/70 text-live">
        {info.status === "offline" ? <WifiOff className="size-4" aria-hidden /> : <RefreshCw className="size-4 animate-spin" aria-hidden />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-ink">Live prices paused</p>
        <p className="text-ink-muted">
          {reason} The price shown may be out of date.{" "}
          {seconds !== null && seconds > 0 ? `Reconnecting in ${seconds}s…` : info.status === "offline" ? "We'll reconnect when you're back online." : "Reconnecting…"}
        </p>
      </div>
    </div>
  );
}
