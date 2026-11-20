import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Camera, Receipt, ShieldAlert } from "lucide-react";
import { auctionApi, disputeApi, orderApi, type Auction, type Dispute, type DisputeReasonCode, type Order } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { formatMoney, parseMoney } from "@/lib/money";
import { useAsync } from "@/lib/useAsync";
import { Badge, Banner, Button, Card, CardBody, CardHeader, EmptyState, Field, FileDrop, Modal, Select, Skeleton, Textarea, useToast, type FileRules } from "@/components/ui";
import { AuctionArt } from "./AuctionArt";
import { ORDER_LABEL } from "./orderLabels";

interface Row {
  auction: Auction;
  order: Order;
}

const photoRules: FileRules = {
  accept: ["image/jpeg", "image/png", "image/webp"],
  extensions: [".jpg", ".jpeg", ".png", ".webp"],
  typeLabel: "JPEG, PNG or WebP",
  maxBytes: 10 * 1024 * 1024,
};

const disputeReasons: Array<{ value: DisputeReasonCode; label: string }> = [
  { value: "ITEM_NOT_RECEIVED", label: "Item did not arrive" },
  { value: "NOT_AS_DESCRIBED", label: "Item is not as described" },
  { value: "DAMAGED_IN_TRANSIT", label: "Item was damaged" },
  { value: "COUNTERFEIT", label: "Item may be counterfeit" },
  { value: "OTHER", label: "Other issue" },
];

/**
 * The caller's orders, as buyer or seller. Payment has no list endpoint yet, so this asks for the
 * order of every ended auction the browse page knows; the service answers only for the parties.
 */
async function loadOrders(userId: string): Promise<Row[]> {
  const ended = (await auctionApi.list()).filter((a) => a.state === "CLOSED" || a.state === "SETTLED");
  const rows = await Promise.all(
    ended.map(async (auction) => {
      const order = await orderApi.forAuction(auction.auction_id).catch(() => null);
      return order && (order.buyer_id === userId || order.seller_id === userId) ? { auction, order } : null;
    }),
  );
  return rows
    .filter((row): row is Row => row !== null)
    .sort((a, b) => Number(b.order.state === "INVOICED") - Number(a.order.state === "INVOICED") || Date.parse(b.order.created_at) - Date.parse(a.order.created_at));
}

export function OrdersCard({ userId }: { userId: string }) {
  const { data, error, loading } = useAsync(() => loadOrders(userId), [userId]);

  return (
    <Card>
      <CardHeader title="Orders" description="Auctions you've won or sold. Winners pay here within the payment window." />
      <CardBody>
        {error ? (
          <Banner tone="danger" title="Couldn't load your orders">{describeError(error).message}</Banner>
        ) : loading && !data ? (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full rounded-xl" />
            <Skeleton className="h-16 w-full rounded-xl" />
          </div>
        ) : !data?.length ? (
          <EmptyState icon={<Receipt className="size-5" />} title="No orders yet">
            When you win an auction, its invoice appears here.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line">
            {data.map(({ auction, order }) => {
              const buying = order.buyer_id === userId;
              const due = buying && order.state === "INVOICED";
              const { label, tone } = ORDER_LABEL[order.state];
              return (
                <li key={order.order_id} className="px-4 py-3">
                  <Link to={`/auctions/${auction.auction_id}`} className="group flex items-center gap-3.5 hover:bg-surface-2/50">
                    <AuctionArt id={auction.auction_id} category={auction.category} src={auction.images?.[0]?.url} size="sm" className="size-12 shrink-0 rounded-xl" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium group-hover:text-brand-ink">{auction.title}</p>
                      <p className="text-xs text-ink-faint">
                        {buying ? "You won" : "You sold"} · {order.invoice.invoice_number}
                        {due && order.payment_due_at ? ` · pay by ${formatDateTime(order.payment_due_at)}` : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <span className="tnum text-sm font-semibold">{formatMoney(parseMoney(buying ? order.total : order.winning_bid_amount), order.currency)}</span>
                      {due ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-brand-ink">
                          Pay now <ArrowRight className="size-3.5" aria-hidden />
                        </span>
                      ) : (
                        <Badge tone={tone} dot>{label}</Badge>
                      )}
                    </div>
                  </Link>
                  {buying && <DisputeAction order={order} />}
                </li>
              );
            })}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

/** Buyer case controls, shared by the Account order list and the order detail panel. */
export function DisputeAction({ order }: { order: Order }) {
  const toast = useToast();
  const { data: disputes } = useAsync(() => disputeApi.listForOrder(order.order_id).catch(() => []), [order.order_id]);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<DisputeReasonCode>("NOT_AS_DESCRIBED");
  const [description, setDescription] = useState("");
  const [photos, setPhotos] = useState<Array<File | null>>([null]);
  const [photoErrors, setPhotoErrors] = useState<Array<string | null>>([null]);
  const [active, setActive] = useState<Dispute | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canRaise = ["IN_ESCROW", "SHIPPED", "DISPUTED"].includes(order.state);
  const existing = disputes?.find((dispute) => dispute.state === "OPEN" || dispute.state === "UNDER_REVIEW") ?? null;

  const setPhoto = (index: number, file: File | null, fileError: string | null) => {
    setPhotos((all) => all.map((item, i) => i === index ? file : item));
    setPhotoErrors((all) => all.map((item, i) => i === index ? fileError : item));
  };

  async function submit() {
    if (photoErrors.some(Boolean)) return;
    if (!active && !description.trim()) {
      setError("Describe what happened before opening a dispute.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const dispute = active ?? existing ?? await disputeApi.create(order.order_id, { reason_code: reason, description: description.trim() });
      setActive(dispute);
      for (const photo of photos) if (photo) await disputeApi.uploadPhoto(dispute.id, photo);
      setPhotos([null]);
      setPhotoErrors([null]);
      toast({ tone: "positive", title: active ? "Photos added" : "Dispute opened", description: "Your order is now protected while the case is reviewed." });
      setOpen(false);
    } catch (cause) {
      const message = describeError(cause).message;
      setError(active || existing ? message : `Your dispute may have opened, but the photo upload failed: ${message}`);
    } finally {
      setLoading(false);
    }
  }

  if (!canRaise && !existing) return null;
  return (
    <div className="mt-3 border-t border-line pt-3">
      <Button variant="secondary" size="sm" icon={<ShieldAlert className="size-3.5" />} onClick={() => setOpen(true)}>
        {active || existing ? "Add case photos" : "Raise a dispute"}
      </Button>
      <Modal
        open={open}
        onClose={() => !loading && setOpen(false)}
        title={active || existing ? "Add dispute photos" : "Raise a dispute"}
        description={active || existing ? "Add clear photos to support your open case." : "Tell us what happened. Your payment remains protected while we review the case."}
        footer={<><Button variant="ghost" onClick={() => setOpen(false)} disabled={loading}>Cancel</Button><Button loading={loading} onClick={() => void submit()}>{active || existing ? "Upload photos" : "Open dispute"}</Button></>}
      >
        <div className="space-y-4">
          {error && <Banner tone="danger" title="Couldn't save your dispute">{error}</Banner>}
          {!active && !existing && <>
            <Field label="Issue">
              {(props) => <Select {...props} value={reason} onChange={(event) => setReason(event.target.value as DisputeReasonCode)}>{disputeReasons.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</Select>}
            </Field>
            <Field label="What happened" hint="Include dates, condition, and any relevant details.">
              {(props) => <Textarea {...props} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the issue" maxLength={4000} />}
            </Field>
          </>}
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm font-medium text-ink"><Camera className="size-4" /> Photo evidence <span className="font-normal text-ink-faint">optional, up to 3</span></p>
            {photos.map((photo, index) => <FileDrop key={index} label={`Photo ${index + 1}`} file={photo} rules={photoRules} disabled={loading} error={photoErrors[index]} onChange={(file, fileError) => setPhoto(index, file, fileError)} />)}
            {photos.length < 3 && <Button variant="ghost" size="sm" onClick={() => { setPhotos((all) => [...all, null]); setPhotoErrors((all) => [...all, null]); }}>Add another photo</Button>}
          </div>
        </div>
      </Modal>
    </div>
  );
}
