// Wire shapes, mirrored from the services' response models. Money fields are strings here.

export type Role = "USER" | "ADMIN";
export type KycStatus =
  | "NOT_SUBMITTED" | "SUBMITTED" | "UNDER_REVIEW" | "VERIFIED" | "REJECTED" | "SUSPENDED";
export type AuctionState =
  | "DRAFT" | "SCHEDULED" | "OPEN" | "EXTENDED" | "CLOSING" | "CLOSED" | "SETTLED" | "CANCELLED";
/** Images a KYC submission keeps (services/kyc): the Aadhaar photo and the live capture. */
export type DocType = "AADHAAR_PHOTO" | "FACE_CAPTURE";

export interface Profile {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
  kyc_status: KycStatus;
  suspended: boolean;
  created_at: string;
  favorite_categories?: string[];
  onboarded?: boolean;
  email_verified?: boolean;
}

export interface VerifyEmailResult {
  status: string;
  email: string;
}

export interface ForgotPasswordResult {
  status: string;
  email: string;
  dev_reset_link?: string;
}

export interface ResetPasswordResult {
  status: string;
  message: string;
}

export interface RegisterResult extends Profile {
  dev_verify_link?: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: Profile;
  is_first_login?: boolean;
}

export interface SendGmailOtpResult {
  status: string;
  email: string;
  expires_in: number;
  dev_otp?: string;
}

/** A listing photo (services/auction-orchestrator). The URL is signed and expires in minutes. */
export interface AuctionImage {
  image_id: string;
  url: string;
  mime_type: string;
  position: number;
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
  images: AuctionImage[];
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

/** What the verified Aadhaar Secure QR said; the QR itself is never kept. */
export interface AadhaarSummary {
  holder_name: string;
  year_of_birth: number;
  gender: "M" | "F" | "T";
  state: string | null;
  reference_last4: string;
  qr_generated_at: string;
  mobile_verified: boolean | null;
}

export type FaceOutcome = "MATCH" | "REVIEW" | "NO_MATCH" | "LIVENESS_FAILED" | "NO_FACE";

export interface FaceStatus {
  attempts_used: number;
  attempts_left: number;
  last_outcome: FaceOutcome | null;
}

export interface KycSubmission {
  submission_id: string;
  state: KycStatus;
  rejection_reason: string | null;
  submitted_at: string;
  decided_at: string | null;
  /** A new Aadhaar upload is accepted now (it replaces a submission still waiting for the face). */
  can_resubmit: boolean;
  /** Set after the face check rejected the submission: no new upload before this time. */
  resubmit_after: string | null;
  aadhaar: AadhaarSummary | null;
  face: FaceStatus;
  documents: KycDocument[];
}

export interface FaceCheckResult {
  outcome: FaceOutcome;
  attempts_left: number;
  submission: KycSubmission;
}

export interface AdminKycDocument extends KycDocument {
  sha256: string;
}

export interface AdminAadhaar extends AadhaarSummary {
  pincode: string | null;
  signer_sha256: string;
  face_model: string;
  reference_faces: number;
}

export interface FaceAttemptRecord {
  attempt_no: number;
  outcome: FaceOutcome;
  frames: number;
  good_frames: number;
  median_score: number | null;
  min_score: number | null;
  yaw_span: number | null;
  at: string;
}

export interface AdminSubmission {
  submission_id: string;
  user_id: string;
  state: KycStatus;
  rejection_reason: string | null;
  submitted_at: string;
  decided_at: string | null;
  decided_by: string | null;
  aadhaar: AdminAadhaar | null;
  face_attempts: FaceAttemptRecord[];
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
