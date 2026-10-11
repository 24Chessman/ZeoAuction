import { useState } from "react";
import { Armchair, BookOpen, Camera, Cpu, Gem, Music, Package, Palette, Watch, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { photoFor } from "@/lib/photos";

/**
 * A listing's cover: its stock photo (src/lib/photos.ts). Until the photo loads, or if it fails,
 * a generated cover shows instead: a category glyph on a gradient seeded by the auction id.
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

interface Props {
  id: string;
  category: string;
  className?: string;
  size?: "sm" | "md" | "lg";
  /** Above-the-fold covers load eagerly; grids load lazily. */
  priority?: boolean;
}

export function AuctionArt({ id, category, className, size = "md", priority = false }: Props) {
  const photo = photoFor(id, category);
  const [state, setState] = useState<"loading" | "loaded" | "failed">("loading");
  const entry = CATEGORY[category.toLowerCase()] ?? { icon: Package, hues: [250, 190] as [number, number] };
  const Icon = entry.icon;
  const s = seed(id);
  const shift = (s % 30) - 15;
  const [a, b] = [entry.hues[0] + shift, entry.hues[1] + shift];
  const x = 20 + (s % 60);
  const y = 15 + ((s >> 5) % 55);

  return (
    <div
      className={cn("relative isolate overflow-hidden bg-surface-2", className)}
      style={{
        background: `radial-gradient(120% 90% at ${x}% ${y}%, hsl(${a} 90% 72% / .95), transparent 60%),
                     radial-gradient(90% 90% at ${100 - x}% ${100 - y}%, hsl(${b} 85% 62% / .9), transparent 65%),
                     linear-gradient(135deg, hsl(${a} 70% 30%), hsl(${b} 65% 22%))`,
      }}
    >
      {state !== "loaded" && (
        <div aria-hidden>
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
      )}
      {state !== "failed" && (
        <img
          src={photo.src}
          alt={size === "lg" ? photo.alt : ""}
          loading={priority ? "eager" : "lazy"}
          decoding="async"
          onLoad={() => setState("loaded")}
          onError={() => setState("failed")}
          className={cn("absolute inset-0 size-full object-cover transition-opacity duration-500", state === "loaded" ? "opacity-100" : "opacity-0")}
        />
      )}
    </div>
  );
}
