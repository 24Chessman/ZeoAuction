import { Link } from "react-router-dom";
import { ArrowRight, BadgeCheck, PackageOpen, Plus } from "lucide-react";
import { useAuth } from "@/app/auth";
import { auctionApi } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { formatMoney, parseMoney } from "@/lib/money";
import { useAsync } from "@/lib/useAsync";
import { AuctionStateBadge, ButtonLink, Card, EmptyState, KycBadge, PageHeader, Skeleton, Table, Td, Th } from "@/components/ui";
import { AuctionArt } from "@/components/auction/AuctionArt";
import { KycStatusStrip } from "@/components/kyc/KycStatusStrip";
import { ListingGatePanel } from "@/components/kyc/ListingGatePanel";

export function SellPage() {
  const { user } = useAuth();
  const { data, loading } = useAsync(() => auctionApi.list(), [user?.user_id]);
  if (!user) return null;
  const verified = user.kyc_status === "VERIFIED";
  const mine = (data ?? []).filter((a) => a.seller_id === user.user_id);

  return (
    <div className="mx-auto max-w-page px-4 py-10 sm:px-6">
      <PageHeader
        eyebrow="Seller hub"
        title="Sell on ZeoAuction"
        description="List items, follow your auctions and see where your verification stands."
        actions={
          verified ? (
            <ButtonLink to="/sell/new" icon={<Plus className="size-4" />}>New auction</ButtonLink>
          ) : (
            <ButtonLink to="/sell/verify" iconRight={<ArrowRight className="size-4" />}>Get verified</ButtonLink>
          )
        }
      />

      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section aria-labelledby="my-auctions">
          <h2 id="my-auctions" className="sr-only">Your auctions</h2>
          {loading && !data ? (
            <Skeleton className="h-64 w-full rounded-2xl" />
          ) : mine.length === 0 ? (
            <EmptyState
              icon={<PackageOpen className="size-5" />}
              title="No auctions yet"
              action={verified ? <ButtonLink to="/sell/new" icon={<Plus className="size-4" />}>Create your first auction</ButtonLink> : undefined}
            >
              {verified ? "Create a draft, check it, then publish it to schedule the auction." : "Once you're verified, your listings show up here."}
            </EmptyState>
          ) : (
            <Card className="overflow-hidden">
              <Table>
                <thead>
                  <tr>
                    <Th>Auction</Th>
                    <Th>Status</Th>
                    <Th className="hidden md:table-cell">Starts at</Th>
                    <Th className="hidden sm:table-cell">Closes</Th>
                  </tr>
                </thead>
                <tbody>
                  {mine.map((auction) => (
                    <tr key={auction.auction_id} className="group hover:bg-surface-2/50">
                      <Td>
                        <Link to={`/auctions/${auction.auction_id}`} className="flex items-center gap-3">
                          <AuctionArt id={auction.auction_id} category={auction.category} size="sm" className="size-11 shrink-0 rounded-xl" />
                          <span className="font-medium group-hover:text-brand-ink">{auction.title}</span>
                        </Link>
                      </Td>
                      <Td><AuctionStateBadge state={auction.state} /></Td>
                      <Td className="tnum hidden md:table-cell">{formatMoney(parseMoney(auction.starting_price), auction.currency)}</Td>
                      <Td className="hidden whitespace-nowrap text-ink-muted sm:table-cell">{formatDateTime(auction.closes_at)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card>
          )}
        </section>

        <aside className="space-y-4">
          <Card className="p-5">
            <div className="flex items-center justify-between">
              <p className="font-semibold">Verification</p>
              <KycBadge status={user.kyc_status} />
            </div>
            <div className="mt-4">
              <KycStatusStrip status={user.kyc_status} />
            </div>
            {verified ? (
              <p className="mt-4 flex items-center gap-2 text-sm text-ink-muted">
                <BadgeCheck className="size-4 text-positive" aria-hidden /> You can list and publish auctions.
              </p>
            ) : (
              <Link to="/sell/verify" className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-brand-ink hover:underline">
                View verification <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            )}
          </Card>
          <ListingGatePanel status={user.kyc_status} />
        </aside>
      </div>
    </div>
  );
}
