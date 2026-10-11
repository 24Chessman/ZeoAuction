import { useState } from "react";
import { Ban, Play, Rocket, Square, Wrench } from "lucide-react";
import { useAuth } from "@/app/auth";
import { auctionApi, type Auction } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { Banner, Button, useToast } from "@/components/ui";

/**
 * Seller commands on their own listing (A1 publish, A8 cancel) and, for administrators, the
 * operator override (open/close early in a demo). The state table on the server decides; the
 * buttons only appear where docs/state-machines.md allows the transition.
 */
export function SellerAuctionActions({ auction, onChange }: { auction: Auction; onChange: () => void }) {
  const { user } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const isSeller = user?.user_id === auction.seller_id;
  const isAdmin = user?.role === "ADMIN";

  const run = async (name: string, action: () => Promise<Auction>, success: string) => {
    setBusy(name);
    setError(null);
    try {
      await action();
      toast({ tone: "positive", title: success });
      onChange();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(null);
    }
  };

  const canPublish = isSeller && auction.state === "DRAFT";
  const canCancel = (isSeller || isAdmin) && (auction.state === "DRAFT" || auction.state === "SCHEDULED");
  const canOpen = isAdmin && auction.state === "SCHEDULED";
  const canClose = isAdmin && (auction.state === "OPEN" || auction.state === "EXTENDED");
  if (!canPublish && !canCancel && !canOpen && !canClose) return null;

  const copy = error ? describeError(error) : null;

  return (
    <div className="rounded-2xl border border-brand/25 bg-brand-soft/40 p-4">
      <p className="flex items-center gap-2 text-sm font-semibold">
        <Wrench className="size-4 text-brand-ink" aria-hidden /> {isSeller ? "Your listing" : "Operator controls"}
      </p>
      <p className="mt-1 text-[13px] text-ink-muted">
        {auction.state === "DRAFT"
          ? "Drafts are visible only to you. Publishing schedules the auction to open at its start time."
          : auction.state === "SCHEDULED"
            ? "Scheduled auctions open automatically. You can cancel until the first bid."
            : "Administrators can close a live auction early for a demo; the server's state table still applies."}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {canPublish && (
          <Button size="sm" loading={busy === "publish"} icon={<Rocket className="size-3.5" />} onClick={() => run("publish", () => auctionApi.publish(auction.auction_id), "Auction published")}>
            Publish
          </Button>
        )}
        {canOpen && (
          <Button size="sm" variant="secondary" loading={busy === "open"} icon={<Play className="size-3.5" />} onClick={() => run("open", () => auctionApi.operatorEvent(auction.auction_id, "open"), "Auction opened")}>
            Open now
          </Button>
        )}
        {canClose && (
          <Button size="sm" variant="secondary" loading={busy === "close"} icon={<Square className="size-3.5" />} onClick={() => run("close", () => auctionApi.operatorEvent(auction.auction_id, "close"), "Auction closing")}>
            Close now
          </Button>
        )}
        {canCancel && (
          <Button size="sm" variant="ghost" loading={busy === "cancel"} icon={<Ban className="size-3.5" />} className="text-danger hover:text-danger" onClick={() => run("cancel", () => auctionApi.cancel(auction.auction_id), "Auction cancelled")}>
            Cancel listing
          </Button>
        )}
      </div>
      {copy && (
        <Banner tone="danger" title={copy.title} className="mt-3" live>
          {copy.message} <span className="font-mono text-[11px]">({copy.code})</span>
        </Banner>
      )}
    </div>
  );
}
