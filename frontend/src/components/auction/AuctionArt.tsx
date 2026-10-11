import { Armchair, BookOpen, Camera, Cpu, Gem, Music, Package, Palette, Watch, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

/**
 * Listings have no images in the API yet, so each one gets a generated cover: a category
 * glyph on a gradient seeded by the auction id. Never a stock photo pretending to be the item.
 */
const CATEGORY: Record<string, { icon: LucideIcon; hues: [number, number] }> = {
  cameras: { icon: Camera, hues: [250, 200] },
  electronics: { icon: Cpu, hues: [210, 170] },
  furniture: { icon: Armchair, hues: [28, 345] },
  watches: { icon: Watch, hues: [222, 280] },
  books: { icon: BookOpen, hues: [160, 95] },
  music: { icon: Music, hues: [300, 255] },
  art: { icon: Palette, hues: [12, 40] },
  jewelry: { icon: Gem, hues: [330, 280] },
};

function seed(id: string): number {
  let hash = 7;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash;
}

export function categoryIcon(category: string): LucideIcon {
  return CATEGORY[category.toLowerCase()]?.icon ?? Package;
}

export function AuctionArt({ id, category, className, size = "md" }: { id: string; category: string; className?: string; size?: "sm" | "md" | "lg" }) {
  const entry = CATEGORY[category.toLowerCase()] ?? { icon: Package, hues: [250, 190] as [number, number] };
  const Icon = entry.icon;
  const s = seed(id);
  const shift = (s % 30) - 15;
  const [a, b] = [entry.hues[0] + shift, entry.hues[1] + shift];
  const x = 20 + (s % 60);
  const y = 15 + ((s >> 5) % 55);

  return (
    <div
      className={cn("relative isolate overflow-hidden", className)}
      style={{
        background: `radial-gradient(120% 90% at ${x}% ${y}%, hsl(${a} 90% 72% / .95), transparent 60%),
                     radial-gradient(90% 90% at ${100 - x}% ${100 - y}%, hsl(${b} 85% 62% / .9), transparent 65%),
                     linear-gradient(135deg, hsl(${a} 70% 30%), hsl(${b} 65% 22%))`,
      }}
      aria-hidden
    >
      <div
        className="absolute inset-0 opacity-[0.18] mix-blend-overlay"
        style={{
          backgroundImage: "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />
      <Icon
        className={cn(
          "absolute text-white/85 drop-shadow-[0_8px_24px_rgba(0,0,0,.25)]",
          size === "sm" && "bottom-3 right-3 size-8",
          size === "md" && "bottom-5 right-5 size-14",
          size === "lg" && "bottom-8 right-8 size-24",
        )}
        strokeWidth={1.25}
      />
      <Icon className="absolute -left-6 -top-6 size-40 text-white/10" strokeWidth={0.75} />
    </div>
  );
}
