import { useState, useEffect } from "react";
import { Check, Sparkles } from "lucide-react";
import { useAuth } from "@/app/auth";
import { categoryIcon } from "@/components/auction/AuctionArt";
import { Button, Modal, useToast } from "@/components/ui";
import { cn } from "@/lib/cn";
import { titleCase } from "@/lib/format";

export const ALL_CATEGORIES = [
  { id: "watches", desc: "Luxury timepieces & vintage watches" },
  { id: "cameras", desc: "Film, mirrorless, vintage & rare lenses" },
  { id: "jewelry", desc: "Fine gold, gemstones & antique heirlooms" },
  { id: "art", desc: "Paintings, prints, sculptures & originals" },
  { id: "electronics", desc: "Audio equipment, rare gear & classics" },
  { id: "music", desc: "Vinyl records, guitars & instruments" },
  { id: "furniture", desc: "Mid-century, artisan & design pieces" },
  { id: "books", desc: "First editions, manuscripts & rare volumes" },
];

interface Props {
  forcedOpen?: boolean;
  onClose?: () => void;
}

export function CategoryOnboardingModal({ forcedOpen, onClose }: Props = {}) {
  const { user, status, updatePreferences } = useAuth();
  const toast = useToast();
  const [internalOpen, setInternalOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  // Auto-trigger when a signed-in user hasn't onboarded yet
  useEffect(() => {
    if (forcedOpen !== undefined) return;
    if (status === "signed-in" && user) {
      const alreadyDismissed = localStorage.getItem(`zeo.onboarding_dismissed.${user.user_id}`);
      if (!user.onboarded && (!user.favorite_categories || user.favorite_categories.length === 0) && !alreadyDismissed) {
        setInternalOpen(true);
      }
    }
  }, [status, user, forcedOpen]);

  // Sync selected with user's current categories
  useEffect(() => {
    if (user?.favorite_categories && user.favorite_categories.length > 0) {
      setSelected(user.favorite_categories);
    }
  }, [user]);

  const isOpen = forcedOpen !== undefined ? forcedOpen : internalOpen;

  const handleClose = () => {
    if (user) {
      localStorage.setItem(`zeo.onboarding_dismissed.${user.user_id}`, "true");
    }
    setInternalOpen(false);
    onClose?.();
  };

  const toggleCategory = (catId: string) => {
    setSelected((prev) =>
      prev.includes(catId) ? prev.filter((id) => id !== catId) : [...prev, catId]
    );
  };

  const handleSelectAll = () => {
    if (selected.length === ALL_CATEGORIES.length) {
      setSelected([]);
    } else {
      setSelected(ALL_CATEGORIES.map((c) => c.id));
    }
  };

  const handleSave = async () => {
    if (!user) return;
    setBusy(true);
    try {
      await updatePreferences(selected);
      toast({
        tone: "positive",
        title: "Interests saved!",
        description: selected.length > 0
          ? `We will highlight ${selected.length} favorite categories on your home feed.`
          : "You can customize your interests anytime.",
      });
      handleClose();
    } catch {
      toast({
        tone: "danger",
        title: "Could not save preferences",
        description: "Please check your network and try again.",
      });
    } finally {
      setBusy(false);
    }
  };

  const handleSkip = async () => {
    if (user) {
      try {
        await updatePreferences(user.favorite_categories ?? []);
      } catch {
        // Fallback to local storage dismiss
      }
    }
    handleClose();
  };

  if (!isOpen) return null;

  return (
    <Modal
      open={isOpen}
      onClose={handleClose}
      size="lg"
      title={
        <div className="flex items-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-brand to-gold text-white shadow-lift">
            <Sparkles className="size-5" />
          </div>
          <div>
            <h3 className="font-display text-xl font-bold">What are you looking for?</h3>
          </div>
        </div>
      }
      description="Pick your favorite auction categories so we can tailor your home feed and recommend auctions you care about."
      footer={
        <div className="flex w-full items-center justify-between gap-3">
          <button
            type="button"
            onClick={handleSelectAll}
            className="text-xs font-semibold text-ink-muted transition-colors hover:text-ink underline"
          >
            {selected.length === ALL_CATEGORIES.length ? "Deselect all" : "Select all"}
          </button>
          <div className="flex items-center gap-2.5">
            <Button variant="ghost" size="sm" onClick={handleSkip} disabled={busy}>
              Skip for now
            </Button>
            <Button
              size="sm"
              loading={busy}
              onClick={handleSave}
              className="px-5 font-semibold"
            >
              Save & Personalize Feed
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-4 py-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-faint">
          Categories ({selected.length} selected)
        </p>

        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {ALL_CATEGORIES.map((cat) => {
            const Icon = categoryIcon(cat.id);
            const isChecked = selected.includes(cat.id);
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => toggleCategory(cat.id)}
                aria-pressed={isChecked}
                className={cn(
                  "group relative flex items-start gap-3.5 rounded-2xl border p-3.5 text-left transition-all",
                  isChecked
                    ? "border-brand bg-brand-soft/60 shadow-lift ring-1 ring-brand/30"
                    : "border-line bg-surface hover:border-line-strong hover:bg-surface-2"
                )}
              >
                <div
                  className={cn(
                    "grid size-10 shrink-0 place-items-center rounded-xl transition-colors",
                    isChecked
                      ? "bg-brand text-white shadow-lift"
                      : "bg-surface-2 text-ink-muted group-hover:text-ink"
                  )}
                >
                  <Icon className="size-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <span className="font-display text-sm font-semibold text-ink">
                      {titleCase(cat.id)}
                    </span>
                    <span
                      className={cn(
                        "grid size-5 place-items-center rounded-full border transition-all",
                        isChecked
                          ? "border-brand bg-brand text-white"
                          : "border-line-strong bg-canvas"
                      )}
                    >
                      {isChecked && <Check className="size-3 stroke-[2.5]" />}
                    </span>
                  </div>
                  <p className="mt-0.5 line-clamp-1 text-xs text-ink-faint">
                    {cat.desc}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
