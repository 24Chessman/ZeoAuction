import { useState, useMemo } from "react";
import { Sparkles, SlidersHorizontal, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { AuctionCard } from "@/components/auction/AuctionCard";
import { Button } from "@/components/ui";
import { titleCase } from "@/lib/format";
import type { Auction } from "@/lib/api";
import type { Cents } from "@/lib/money";
import { CategoryOnboardingModal } from "./CategoryOnboardingModal";

interface Props {
  auctions: Array<{
    auction: Auction;
    price: Cents | null;
    bids: number;
  }>;
  onCustomize?: () => void;
  title?: string;
  maxItems?: number;
}

export function RecommendedFeedSection({
  auctions,
  title = "Recommended For You",
  maxItems = 6,
}: Props) {
  const { user, status } = useAuth();
  const [modalOpen, setModalOpen] = useState(false);

  const favoriteCategories = useMemo(() => {
    return (user?.favorite_categories ?? []).map((c) => c.toLowerCase());
  }, [user?.favorite_categories]);

  const recommendedRows = useMemo(() => {
    if (!favoriteCategories.length) return [];
    return auctions
      .filter((r) => favoriteCategories.includes(r.auction.category.toLowerCase()))
      .filter((r) => r.auction.state !== "CANCELLED" && r.auction.state !== "DRAFT");
  }, [auctions, favoriteCategories]);

  if (status !== "signed-in" || !user) {
    return null;
  }

  // If user has not chosen any categories, show an inviting prompt
  if (favoriteCategories.length === 0) {
    return (
      <>
        <div className="relative overflow-hidden rounded-3xl border border-line bg-gradient-to-r from-brand/10 via-surface to-gold/10 p-6 sm:p-8">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-4">
              <div className="grid size-12 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-brand to-gold text-white shadow-lift">
                <Sparkles className="size-6" />
              </div>
              <div>
                <h3 className="font-display text-xl font-bold text-ink">
                  Personalize Your Auction Feed
                </h3>
                <p className="mt-1 max-w-xl text-sm text-ink-muted">
                  Tell us what you love (Watches, Cameras, Art, Jewelry...) and we'll suggest matching auctions here.
                </p>
              </div>
            </div>
            <Button
              onClick={() => setModalOpen(true)}
              className="shrink-0 font-semibold"
              iconRight={<SlidersHorizontal className="size-4" />}
            >
              Choose Interests
            </Button>
          </div>
        </div>
        <CategoryOnboardingModal
          forcedOpen={modalOpen}
          onClose={() => setModalOpen(false)}
        />
      </>
    );
  }

  return (
    <section className="space-y-6" aria-label="Personalized auction recommendations">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="inline-flex items-center gap-1.5 rounded-full border border-brand/20 bg-brand-soft px-3 py-1 text-xs font-semibold text-brand-ink">
            <Sparkles className="size-3.5" />
            <span>Curated For You</span>
          </div>
          <h2 className="mt-2.5 font-display text-2xl font-bold tracking-tight text-ink sm:text-3xl">
            {title}
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            Matching your favorite categories:{" "}
            <span className="font-medium text-ink">
              {favoriteCategories.map((c) => titleCase(c)).join(", ")}
            </span>
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setModalOpen(true)}
            icon={<SlidersHorizontal className="size-3.5" />}
          >
            Customize
          </Button>
          <Link
            to="/auctions"
            className="inline-flex items-center gap-1 text-xs font-semibold text-brand-ink hover:underline sm:hidden"
          >
            View all <ArrowRight className="size-3.5" />
          </Link>
        </div>
      </div>

      {recommendedRows.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-line-strong bg-surface p-8 text-center">
          <p className="text-sm font-medium text-ink">No live auctions right now in your selected categories.</p>
          <p className="mt-1 text-xs text-ink-faint">
            You can add more categories or check back soon as sellers list new items.
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-4"
            onClick={() => setModalOpen(true)}
          >
            Add More Categories
          </Button>
        </div>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {recommendedRows.slice(0, maxItems).map((row, index) => (
            <div
              key={row.auction.auction_id}
              className="animate-fade-up relative"
              style={{ animationDelay: `${Math.min(index, 6) * 40}ms` }}
            >
              <div className="absolute right-3 top-3 z-10 rounded-full bg-midnight/80 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-brand backdrop-blur border border-brand/30">
                ★ Recommended
              </div>
              <AuctionCard
                auction={row.auction}
                price={row.price}
                bidCount={row.bids}
              />
            </div>
          ))}
        </div>
      )}

      <CategoryOnboardingModal
        forcedOpen={modalOpen}
        onClose={() => setModalOpen(false)}
      />
    </section>
  );
}
