import { featuredAuctionIds, useMocks } from "../config";
import { ApiError } from "../errors";
import { toMoneyString, type Cents } from "../money";
import { request } from "./http";
import type {
  AdminSubmission, Auction, BidAccepted, BidPage, CheckoutSession, CreateAuction, DocumentUrl, FeeQuote,
  FaceCheckResult, ForgotPasswordResult, KycSubmission, LedgerEntry, Order, PaymentConfirmation, Profile, QueuePage,
  RegisterResult, ResetPasswordResult, SendGmailOtpResult, TokenPair, VerifyEmailResult,
} from "./types";

export * from "./types";
export { refreshSession } from "./http";
export { session } from "./session";

const MY_AUCTIONS_KEY = "zeo.myAuctions";

function rememberAuction(id: string): void {
  try {
    const ids = new Set<string>(JSON.parse(localStorage.getItem(MY_AUCTIONS_KEY) ?? "[]"));
    ids.add(id);
    localStorage.setItem(MY_AUCTIONS_KEY, JSON.stringify([...ids]));
  } catch {
    // Remembering is a convenience for the browse page; losing it loses nothing on the server.
  }
}

function rememberedAuctions(): string[] {
  try {
    return JSON.parse(localStorage.getItem(MY_AUCTIONS_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export const authApi = {
  async register(body: { email: string; password: string; display_name: string }): Promise<RegisterResult> {
    return (await request<RegisterResult>("auth", "POST", "/api/v1/auth/register", { json: body })).data;
  },
  async verifyEmail(token: string): Promise<VerifyEmailResult> {
    return (await request<VerifyEmailResult>("auth", "POST", "/api/v1/auth/verify-email", { json: { token } })).data;
  },
  async resendVerification(email: string): Promise<{ status: string; email: string; dev_verify_link?: string }> {
    return (await request<{ status: string; email: string; dev_verify_link?: string }>("auth", "POST", "/api/v1/auth/resend-verification", { json: { email } })).data;
  },
  async forgotPassword(email: string): Promise<ForgotPasswordResult> {
    return (await request<ForgotPasswordResult>("auth", "POST", "/api/v1/auth/forgot-password", { json: { email } })).data;
  },
  async resetPassword(token: string, new_password: string): Promise<ResetPasswordResult> {
    return (await request<ResetPasswordResult>("auth", "POST", "/api/v1/auth/reset-password", { json: { token, new_password } })).data;
  },
  async login(email: string, password: string): Promise<TokenPair> {
    return (await request<TokenPair>("auth", "POST", "/api/v1/auth/login", { json: { email, password } })).data;
  },
  async logout(refreshToken: string): Promise<void> {
    await request("auth", "POST", "/api/v1/auth/logout", { json: { refresh_token: refreshToken } });
  },
  async me(): Promise<Profile> {
    return (await request<Profile>("auth", "GET", "/api/v1/users/me", { auth: true })).data;
  },
  async updateMe(display_name: string): Promise<Profile> {
    return (await request<Profile>("auth", "PATCH", "/api/v1/users/me", { auth: true, json: { display_name } })).data;
  },
  async sendGmailOtp(email: string): Promise<SendGmailOtpResult> {
    return (await request<SendGmailOtpResult>("auth", "POST", "/api/v1/auth/gmail/send-otp", { json: { email } })).data;
  },
  async verifyGmailOtp(email: string, otp: string, displayName?: string): Promise<TokenPair> {
    return (await request<TokenPair>("auth", "POST", "/api/v1/auth/gmail/verify-otp", { json: { email, otp, display_name: displayName } })).data;
  },
  async updatePreferences(favorite_categories: string[]): Promise<Profile> {
    return (await request<Profile>("auth", "PATCH", "/api/v1/users/me", { auth: true, json: { favorite_categories, onboarded: true } })).data;
  },
};

export const auctionApi = {
  /**
   * There is no list endpoint before search-analytics (Plan 6). Live mode loads the featured
   * ids from config plus the auctions created in this browser; mock mode lists its catalogue.
   */
  async list(): Promise<Auction[]> {
    if (useMocks) return (await request<Auction[]>("auction", "GET", "/api/v1/auctions")).data;
    const ids = [...new Set([...featuredAuctionIds, ...rememberedAuctions()])];
    const results = await Promise.allSettled(ids.map((id) => auctionApi.get(id)));
    return results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
  },
  async get(id: string): Promise<Auction> {
    return (await request<Auction>("auction", "GET", `/api/v1/auctions/${id}`)).data;
  },
  async create(body: CreateAuction): Promise<Auction> {
    const auction = (await request<Auction>("auction", "POST", "/api/v1/auctions", { auth: true, json: body })).data;
    rememberAuction(auction.auction_id);
    return auction;
  },
  /** Seller only, while DRAFT or SCHEDULED; at most six JPEG, PNG or WebP photos. */
  async addImage(id: string, image: File): Promise<Auction> {
    const form = new FormData();
    form.append("image", image);
    return (await request<Auction>("auction", "POST", `/api/v1/auctions/${id}/images`, { auth: true, form })).data;
  },
  async removeImage(id: string, imageId: string): Promise<Auction> {
    return (await request<Auction>("auction", "DELETE", `/api/v1/auctions/${id}/images/${imageId}`, { auth: true })).data;
  },
  async publish(id: string): Promise<Auction> {
    return (await request<Auction>("auction", "POST", `/api/v1/auctions/${id}/publish`, { auth: true })).data;
  },
  async cancel(id: string): Promise<Auction> {
    return (await request<Auction>("auction", "POST", `/api/v1/auctions/${id}/cancel`, { auth: true })).data;
  },
  /** Administrators' operator override, e.g. opening a scheduled auction early in a demo. */
  async operatorEvent(id: string, event: "open" | "close" | "drained" | "settle"): Promise<Auction> {
    return (await request<Auction>("auction", "POST", `/api/v1/auctions/${id}/events`, { auth: true, json: { event } })).data;
  },
};

export const bidApi = {
  async list(auctionId: string, page = 1, pageSize = 20): Promise<BidPage> {
    const path = `/api/v1/auctions/${auctionId}/bids?page=${page}&page_size=${pageSize}`;
    return (await request<BidPage>("bid", "GET", path)).data;
  },
  async place(auctionId: string, amount: Cents, idempotencyKey: string): Promise<{ bid: BidAccepted; replay: boolean }> {
    const result = await request<BidAccepted>("bid", "POST", `/api/v1/auctions/${auctionId}/bids`, {
      auth: true,
      json: { amount: toMoneyString(amount) },
      headers: { "Idempotency-Key": idempotencyKey },
    });
    return { bid: result.data, replay: result.headers["idempotent-replay"] === "true" };
  },
};

export const feeApi = {
  async quote(amount: Cents): Promise<FeeQuote> {
    return (await request<FeeQuote>("payment", "GET", `/api/v1/fees/quote?bid_amount=${toMoneyString(amount)}`)).data;
  },
};

export const orderApi = {
  /** The order of a closed auction, for its buyer, seller or an admin; null until it is invoiced. */
  async forAuction(auctionId: string): Promise<Order | null> {
    try {
      return (await request<Order>("payment", "GET", `/api/v1/auctions/${auctionId}/order`, { auth: true })).data;
    } catch (error) {
      if (error instanceof ApiError && (error.code === "NOT_FOUND" || error.code === "FORBIDDEN")) return null;
      throw error;
    }
  },
  async get(orderId: string): Promise<Order> {
    return (await request<Order>("payment", "GET", `/api/v1/orders/${orderId}`, { auth: true })).data;
  },
  /** The winner opens Checkout; repeating it returns the same provider order. */
  async checkout(orderId: string): Promise<CheckoutSession> {
    return (await request<CheckoutSession>("payment", "POST", `/api/v1/orders/${orderId}/checkout`, { auth: true })).data;
  },
  /** Checkout's signed result; the payment is captured into (simulated) escrow. */
  async confirm(orderId: string, payment: PaymentConfirmation, idempotencyKey: string): Promise<Order> {
    return (await request<Order>("payment", "POST", `/api/v1/orders/${orderId}/payment`, {
      auth: true, json: payment, headers: { "Idempotency-Key": idempotencyKey },
    })).data;
  },  /** The order's append-only escrow ledger (admins). */
  async ledger(orderId: string): Promise<LedgerEntry[]> {
    return (await request<LedgerEntry[]>("payment", "GET", `/api/v1/orders/${orderId}/ledger`, { auth: true })).data;
  },
};

export const kycApi = {
  /** Step 1: a photo of the Aadhaar Secure QR code (services/kyc). */
  async uploadAadhaar(qrImage: File, mobile?: string): Promise<KycSubmission> {
    const form = new FormData();
    form.append("qr_image", qrImage);
    if (mobile) form.append("mobile", mobile);
    return (await request<KycSubmission>("kyc", "POST", "/api/v1/kyc/aadhaar", { auth: true, form })).data;
  },
  /** Step 2: live camera frames, matched against the Aadhaar photo on the server. */
  async faceCheck(submissionId: string, frames: Blob[]): Promise<FaceCheckResult> {
    const form = new FormData();
    frames.forEach((frame, i) => form.append("frames", frame, `frame-${i}.jpg`));
    return (await request<FaceCheckResult>("kyc", "POST", `/api/v1/kyc/submissions/${submissionId}/face`, { auth: true, form })).data;
  },
  /** The caller's latest submission, or null before the first one. */
  async mine(): Promise<KycSubmission | null> {
    try {
      return (await request<KycSubmission>("kyc", "GET", "/api/v1/kyc/submissions/me", { auth: true })).data;
    } catch (error) {
      if (error instanceof ApiError && error.code === "NOT_FOUND") return null;
      throw error;
    }
  },
};

export type AdminKycEvent = "approve" | "reject" | "suspend" | "reinstate";

export const adminKycApi = {
  async queue(limit = 50, offset = 0): Promise<QueuePage> {
    return (await request<QueuePage>("kyc", "GET", `/api/v1/admin/kyc/queue?limit=${limit}&offset=${offset}`, { auth: true })).data;
  },
  async detail(id: string): Promise<AdminSubmission> {
    return (await request<AdminSubmission>("kyc", "GET", `/api/v1/admin/kyc/${id}`, { auth: true })).data;
  },
  async transition(id: string, event: AdminKycEvent, body?: { reason?: string; reason_code?: string }): Promise<AdminSubmission> {
    return (await request<AdminSubmission>("kyc", "POST", `/api/v1/admin/kyc/${id}/${event}`, { auth: true, json: body })).data;
  },
  async documentUrl(submissionId: string, documentId: string): Promise<DocumentUrl> {
    const path = `/api/v1/admin/kyc/${submissionId}/documents/${documentId}/url`;
    return (await request<DocumentUrl>("kyc", "GET", path, { auth: true })).data;
  },
};
