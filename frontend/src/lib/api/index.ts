import { featuredAuctionIds, useMocks } from "../config";
import { ApiError } from "../errors";
import { toMoneyString, type Cents } from "../money";
import { request } from "./http";
import type {
  AdminSubmission, Auction, BidAccepted, BidPage, CheckoutSession, CreateAuction, DocumentUrl, FeeQuote,
  KycFiles, KycSubmission, LedgerEntry, Order, PaymentConfirmation, Profile, QueuePage, TokenPair,
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
  async register(body: { email: string; password: string; display_name: string }): Promise<Profile> {
    return (await request<Profile>("auth", "POST", "/api/v1/auth/register", { json: body })).data;
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
  async submit(files: KycFiles): Promise<KycSubmission> {
    const form = new FormData();
    if (files.GOVERNMENT_ID) form.append("government_id", files.GOVERNMENT_ID);
    if (files.PROOF_OF_ADDRESS) form.append("proof_of_address", files.PROOF_OF_ADDRESS);
    if (files.SELFIE) form.append("selfie", files.SELFIE);
    return (await request<KycSubmission>("kyc", "POST", "/api/v1/kyc/submissions", { auth: true, form })).data;
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

export type AdminKycEvent = "start-review" | "approve" | "reject" | "suspend" | "reinstate";

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
