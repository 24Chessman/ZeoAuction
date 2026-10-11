// Wire shapes, mirrored from the services' response models. Money fields are strings here.

export type Role = "USER" | "ADMIN";
export type KycStatus =
  | "NOT_SUBMITTED" | "SUBMITTED" | "UNDER_REVIEW" | "VERIFIED" | "REJECTED" | "SUSPENDED";
export type AuctionState =
  | "DRAFT" | "SCHEDULED" | "OPEN" | "EXTENDED" | "CLOSING" | "CLOSED" | "SETTLED" | "CANCELLED";
export type DocType = "GOVERNMENT_ID" | "PROOF_OF_ADDRESS" | "SELFIE";

export interface Profile {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
  kyc_status: KycStatus;
  suspended: boolean;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: Profile;
}

export interface Auction {
  auction_id: string;
  seller_id: string;
  title: string;
  description: string;
  category: string;
  starting_price: string;
  reserve_price: string | null;
  currency: string;
  state: AuctionState;
  opens_at: string | null;
  closes_at: string | null;
  original_closes_at: string | null;
  extension_count: number;
  max_extensions: number;
  guard_interval_seconds: number;
  extension_seconds: number;
  winning_bid_id: string | null;
  version: number;
}

export interface CreateAuction {
  title: string;
  description: string;
  category: string;
  starting_price: string;
  reserve_price: string | null;
  currency: string;
  opens_at: string | null;
  closes_at: string | null;
}

export interface BidAccepted {
  bid_id: string;
  auction_id: string;
  server_seq: number;
  current_price: string;
  min_next_bid: string;
  accepted_at: string;
}

export interface Bid {
  bid_id: string;
  auction_id: string;
  amount: string;
  server_seq: number;
  accepted_at: string;
  bidder_alias: string;
}

export interface BidPage {
  page: number;
  page_size: number;
  total: number;
  items: Bid[];
}

export interface FeeQuote {
  bid_amount: string;
  convenience_fee: string;
  total: string;
  currency: string;
  fee_version: string;
}

export interface KycDocument {
  document_id: string;
  doc_type: DocType;
  mime_type: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface KycSubmission {
  submission_id: string;
  state: KycStatus;
  rejection_reason: string | null;
  submitted_at: string;
  decided_at: string | null;
  can_resubmit: boolean;
  documents: KycDocument[];
}

export interface AdminKycDocument extends KycDocument {
  sha256: string;
}

export interface AdminSubmission {
  submission_id: string;
  user_id: string;
  state: KycStatus;
  rejection_reason: string | null;
  submitted_at: string;
  decided_at: string | null;
  decided_by: string | null;
  documents: AdminKycDocument[];
}

export interface QueueItem {
  submission_id: string;
  user_id: string;
  state: KycStatus;
  submitted_at: string;
}

export interface QueuePage {
  items: QueueItem[];
  limit: number;
  offset: number;
}

export interface DocumentUrl {
  url: string;
  expires_in: number;
}

export interface ErrorEnvelope {
  code: string;
  message: string;
  details: Record<string, unknown> | null;
  request_id?: string | null;
}

export type KycFiles = Partial<Record<DocType, File>>;

/** Order states, docs/state-machines.md section 2 (contracts/openapi/payment.v1.yaml). */
export type OrderState =
  | "INVOICED" | "AUTHORIZED" | "AWAITING_CAPTURE_RETRY" | "CAPTURED" | "IN_ESCROW"
  | "SHIPPED" | "DISPUTED" | "RELEASED" | "REFUNDED" | "CANCELLED";

export interface Invoice {
  invoice_number: string;
  bid_amount: string;
  convenience_fee: string;
  total: string;
  currency: string;
  fee_version: string;
  issued_at: string;
  voided_at: string | null;
}

export interface Order {
  order_id: string;
  auction_id: string;
  buyer_id: string;
  seller_id: string;
  winning_bid_id: string;
  state: OrderState;
  winning_bid_amount: string;
  convenience_fee: string;
  total: string;
  currency: string;
  fee_version: string;
  provider: "razorpay" | "mock";
  payment_due_at: string | null;
  authorized_at: string | null;
  created_at: string;
  updated_at: string;
  invoice: Invoice;
  test_mode: true;
  notice: string;
}

/** What the browser opens Checkout with (POST /orders/{id}/checkout). */
export interface CheckoutSession {
  order_id: string;
  provider: "razorpay" | "mock";
  key_id: string | null;
  provider_order_id: string;
  amount: string;
  amount_minor: number;
  currency: string;
  description: string;
  simulated_payment: { payment_id: string; signature: string } | null;
  test_mode: true;
}

/** Checkout's signed result, handed back to POST /orders/{id}/payment. */
export interface PaymentConfirmation {
  provider_order_id: string;
  payment_id: string;
  signature: string;
}

/** One append-only escrow ledger row (GET /orders/{id}/ledger, admins). Negative = out of custody. */
export interface LedgerEntry {
  id: number | null;
  entry_type: "CAPTURE" | "HOLD" | "FEE_RETAIN" | "RELEASE" | "REFUND" | "COMPENSATION";
  amount: string;
  currency: string;
  idempotency_key: string;
  provider_ref: string | null;
  note: string | null;
  created_at: string | null;
}
