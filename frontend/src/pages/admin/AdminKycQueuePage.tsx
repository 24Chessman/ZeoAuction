import { Link } from "react-router-dom";
import { ChevronRight, Inbox, RefreshCw } from "lucide-react";
import { adminKycApi } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { shortId, timeAgo } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { Banner, Button, Card, EmptyState, KycBadge, PageHeader, Skeleton, Table, Td, Th, useNow } from "@/components/ui";

export function AdminKycQueuePage() {
  const { data, error, loading, reload } = useAsync(() => adminKycApi.queue(50, 0), []);
  const now = useNow(30_000);
  const items = data?.items ?? [];
  const oldest = items[0]?.submitted_at ?? null;

  return (
    <div className="mx-auto max-w-page px-4 py-10 sm:px-6">
      <PageHeader
        eyebrow="Administration"
        title="KYC review queue"
        description="Sellers whose live face check was close to the Aadhaar photo, oldest first. Clear matches verify on their own. Every decision and every photo view is audited."
        actions={<Button variant="secondary" icon={<RefreshCw className="size-4" />} onClick={() => void reload()} loading={loading && Boolean(data)}>Refresh</Button>}
      />

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <Stat label="Waiting for a decision" value={data ? items.length : null} />
        <Card className="p-5">
          <p className="text-sm text-ink-muted">Oldest waiting</p>
          {!data ? <Skeleton className="mt-2 h-8 w-24" /> : <p className="mt-1 text-3xl font-semibold tracking-[-0.03em]">{oldest ? timeAgo(oldest, now) : "—"}</p>}
        </Card>
      </div>

      <div className="mt-6">
        {error ? (
          <Banner tone="danger" title={describeError(error).title}>{describeError(error).message}</Banner>
        ) : loading && !data ? (
          <Skeleton className="h-64 w-full rounded-2xl" />
        ) : items.length === 0 ? (
          <EmptyState icon={<Inbox className="size-5" />} title="The queue is empty">Close face matches will appear here.</EmptyState>
        ) : (
          <Card className="overflow-hidden">
            <Table>
              <thead>
                <tr>
                  <Th>Submission</Th>
                  <Th>Applicant</Th>
                  <Th>Status</Th>
                  <Th>Waiting</Th>
                  <Th><span className="sr-only">Open</span></Th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.submission_id} className="group hover:bg-surface-2/50">
                    <Td>
                      <Link to={`/admin/kyc/${item.submission_id}`} className="font-mono text-[13px] font-medium group-hover:text-brand-ink">
                        KYC-{shortId(item.submission_id)}
                      </Link>
                    </Td>
                    <Td className="font-mono text-[13px] text-ink-muted" title={item.user_id}>user …{shortId(item.user_id)}</Td>
                    <Td><KycBadge status={item.state} /></Td>
                    <Td className="whitespace-nowrap text-ink-muted">{timeAgo(item.submitted_at, now)}</Td>
                    <Td className="text-right">
                      <Link to={`/admin/kyc/${item.submission_id}`} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm font-medium text-brand-ink hover:bg-brand-soft" aria-label={`Review submission ${shortId(item.submission_id)}`}>
                        Review <ChevronRight className="size-4" aria-hidden />
                      </Link>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | null }) {
  return (
    <Card className="p-5">
      <p className="text-sm text-ink-muted">{label}</p>
      {value === null ? <Skeleton className="mt-2 h-8 w-12" /> : <p className="tnum mt-1 text-3xl font-semibold tracking-[-0.03em]">{value}</p>}
    </Card>
  );
}
