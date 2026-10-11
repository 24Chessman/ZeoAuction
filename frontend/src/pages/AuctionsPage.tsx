import { useMemo, useState } from "react";
import { Gavel, Search, SearchX } from "lucide-react";
import { auctionApi, bidApi, type Auction } from "@/lib/api";
import { useMocks } from "@/lib/config";
import { cn } from "@/lib/cn";
import { describeError } from "@/lib/errors";
import { titleCase } from "@/lib/format";
import { parseMoney, type Cents } from "@/lib/money";
import { useAsync } from "@/lib/useAsync";
import { Banner, Button, EmptyState, Input, PageHeader } from "@/components/ui";
import { AuctionCard, AuctionCardSkeleton } from "@/components/auction/AuctionCard";

type Filter = "live" | "upcoming" | "ended" | "all";

const FILTERS: Array<{ id: Filter; label: string; states: Auction["state"][] }> = [
  { id: "live", label: "Live now", states: ["OPEN", "EXTENDED", "CLOSING"] },
  { id: "upcoming", label: "Upcoming", states: ["SCHEDULED"] },
  { id: "ended", label: "Ended", states: ["CLOSED", "SETTLED"] },
  { id: "all", label: "All", states: [] },
];

interface Row {
  auction: Auction;
  price: Cents | null;
  bids: number;
}

async function loadRows(): Promise<Row[]> {
  const auctions = (await auctionApi.list()).filter((a) => a.state !== "DRAFT" && a.state !== "CANCELLED");
  return Promise.all(
    auctions.map(async (auction) => {
      try {
        const page = await bidApi.list(auction.auction_id, 1, 1);
        return { auction, price: page.items[0] ? parseMoney(page.items[0].amount) : null, bids: page.total };
      } catch {
        return { auction, price: null, bids: 0 };
      }
    }),
  );
}

export function AuctionsPage() {
  const { data, error, loading, reload } = useAsync(loadRows, []);
  const [filter, setFilter] = useState<Filter>("live");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);

  const categories = useMemo(() => [...new Set((data ?? []).map((r) => r.auction.category))].sort(), [data]);

  const rows = useMemo(() => {
    const states = FILTERS.find((f) => f.id === filter)?.states ?? [];
    const q = query.trim().toLowerCase();
    return (data ?? [])
      .filter((r) => states.length === 0 || states.includes(r.auction.state))
      .filter((r) => !category || r.auction.category === category)
      .filter((r) => !q || r.auction.title.toLowerCase().includes(q) || r.auction.description.toLowerCase().includes(q))
      .sort((a, b) => Date.parse(a.auction.closes_at ?? "9999") - Date.parse(b.auction.closes_at ?? "9999"));
  }, [data, filter, query, category]);

  const counts = useMemo(() => {
    const all = data ?? [];
    return Object.fromEntries(FILTERS.map((f) => [f.id, f.states.length ? all.filter((r) => f.states.includes(r.auction.state)).length : all.length]));
  }, [data]);

  return (
    <div className="mx-auto max-w-page px-4 py-10 sm:px-6">
      <PageHeader
        eyebrow="Marketplace"
        title="Auctions"
        description="Every listing comes from a verified seller, and the flat fee is shown before you bid."
      />

      <div className="mt-8 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex gap-1 overflow-x-auto rounded-2xl border border-line bg-surface p-1 shadow-card" role="tablist" aria-label="Auction status">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              role="tab"
              aria-selected={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={cn(
                "flex items-center gap-2 whitespace-nowrap rounded-xl px-3.5 py-2 text-sm font-medium transition-colors",
                filter === f.id ? "bg-ink text-canvas shadow-card" : "text-ink-muted hover:bg-surface-2 hover:text-ink",
              )}
            >
              {f.id === "live" && <span className={cn("size-1.5 rounded-full", filter === f.id ? "bg-canvas" : "bg-live")} />}
              {f.label}
              {data && <span className={cn("tnum text-xs", filter === f.id ? "text-canvas/60" : "text-ink-faint")}>{counts[f.id]}</span>}
            </button>
          ))}
        </div>
        <div className="w-full lg:w-80">
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search auctions" aria-label="Search auctions" leading={<Search className="size-4" />} />
        </div>
      </div>

      {categories.length > 1 && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Chip active={category === null} onClick={() => setCategory(null)}>All categories</Chip>
          {categories.map((c) => (
            <Chip key={c} active={category === c} onClick={() => setCategory(category === c ? null : c)}>
              {titleCase(c)}
            </Chip>
          ))}
        </div>
      )}

      <div className="mt-8">
        {error ? (
          <Banner tone="danger" title={describeError(error).title} action={<Button size="sm" variant="secondary" onClick={() => void reload()}>Retry</Button>}>
            {describeError(error).hint ?? describeError(error).message}
          </Banner>
        ) : loading && !data ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => <AuctionCardSkeleton key={i} />)}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={query || category ? <SearchX className="size-5" /> : <Gavel className="size-5" />}
            title={query || category ? "No auctions match" : `No ${FILTERS.find((f) => f.id === filter)?.label.toLowerCase()} auctions`}
            action={(query || category) && <Button variant="secondary" onClick={() => { setQuery(""); setCategory(null); }}>Clear filters</Button>}
          >
            {!useMocks && !query && !category
              ? "Live mode lists the featured auctions from VITE_FEATURED_AUCTIONS and the ones created in this browser."
              : "Try another tab or search."}
          </EmptyState>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {rows.map((row, index) => (
              <div key={row.auction.auction_id} className="animate-fade-up" style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}>
                <AuctionCard auction={row.auction} price={row.price} bidCount={row.bids} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-full border px-3 py-1 text-[13px] font-medium transition-colors",
        active ? "border-brand bg-brand-soft text-brand-ink" : "border-line text-ink-muted hover:border-line-strong hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
