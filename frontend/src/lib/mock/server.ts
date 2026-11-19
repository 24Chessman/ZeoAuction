import type { Auction, AuctionState, CheckoutSession, ErrorEnvelope, FaceAttemptRecord, FaceOutcome, KycStatus, LedgerEntry, Order, Profile } from "../api/types";
import type { TransportRequest, TransportResponse } from "../api/http";
import { minimumNextBid } from "../bidRules";
import { parseMoney, toMoneyString } from "../money";
import { BridgeError, paymentBridge, type PaymentBridge } from "../payments/devBridge";
import { policy } from "../policy";
import { AadhaarInvalid, readSecureQr } from "./aadhaarQr";
import { ids, seedState, type MockBid, type MockDocument, type MockFacePlan, type MockOrder, type MockState, type MockSubmission, type MockUser } from "./seed";

/**
 * An in-browser simulation of the Plan 1–4 services, used when VITE_USE_MOCKS is on. Routes,
 * status codes and error codes follow the real services so the UI code path is the same.
 * State is kept in localStorage and live events cross tabs on a BroadcastChannel, so two
 * windows watching one auction see each other's bids.
 */

const STORE_KEY = "zeo.mock.v1";
const ACCESS_TTL_SECONDS = 15 * 60;
const MAX_QR_IMAGE_BYTES = 8 * 1024 * 1024;
const MAX_STORED_PREVIEW = 1_500_000;
// services/auction-orchestrator app/domain/images.py.
const LISTING_PHOTOS = { max: 6, maxBytes: 5 * 1024 * 1024 };
/** Same limits as services/kyc (FacePolicy). */
const FACE = { minFrames: 3, maxFrames: 8, maxAttempts: 3, cooldownMs: 24 * 60 * 60 * 1000 };
const COUNTED: ReadonlySet<FaceOutcome> = new Set(["NO_MATCH", "LIVENESS_FAILED"]);
const MONEY = /^(0|[1-9]\d*)\.\d{2}$/;

export type LiveListener = (message: Record<string, unknown>, target: { auctionId?: string; userId?: string }) => void;

class HttpError extends Error {
  constructor(readonly status: number, readonly code: string, message: string, readonly details: Record<string, unknown> | null = null) {
    super(message);
  }
}

function now(): number {
  return Date.now();
}

function iso(ms = now()): string {
  return new Date(ms).toISOString();
}

/** FNV-1a: a stable per-auction pseudonym, like the bid service's HMAC alias. */
function alias(auctionId: string, bidderId: string): string {
  let hash = 0x811c9dc5;
  for (const char of `${auctionId}:${bidderId}`) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `bidder-${hash.toString(16).padStart(8, "0")}`;
}

function profile(user: MockUser): Profile {
  return {
    user_id: user.id, email: user.email, display_name: user.display_name, role: user.role,
    kyc_status: user.kyc_status, suspended: user.suspended, created_at: user.created_at,
    favorite_categories: user.favorite_categories ?? [],
    onboarded: user.onboarded ?? false,
    email_verified: user.email_verified ?? false,
  };
}

export class MockServer {
  private state: MockState;
  private readonly listeners = new Set<LiveListener>();
  private readonly channel: BroadcastChannel | null;
  /** token_version claimed by the token on the request being handled, per user. */
  private readonly claims = new Map<string, number>();
  /** Simulated network latency range in ms; tests set it to [0, 0]. */
  latency: [number, number] = [120, 300];
  /** Real Razorpay test mode through the dev server, when it has keys; null simulates Checkout. */
  payments: () => Promise<PaymentBridge | null> = () => paymentBridge();
  /** The text of every QR code in a photo (zxing-wasm, loaded on first use); tests swap it. */
  qrCodes: (image: Blob) => Promise<string[]> = (image) => import("./qrDecoder").then((m) => m.readQrCodes(image));
  /** SubjectPublicKeyInfo of the keys a Secure QR may be signed with; UIDAI's when unset. */
  trustedQrKeys: Uint8Array<ArrayBuffer>[] | undefined = undefined;
  private readonly otps = new Map<string, { code: string; expiresAt: number }>();
  private readonly emailTokens = new Map<string, { userId: string; type: "VERIFY_EMAIL" | "RESET_PASSWORD"; expiresAt: number }>();

  constructor(private readonly storage: Storage | null = safeStorage()) {
    this.state = this.load();
    this.channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("zeo.mock.live");
    if (this.channel) {
      this.channel.onmessage = (event: MessageEvent) => {
        const { message, target } = event.data as { message: Record<string, unknown>; target: { auctionId?: string; userId?: string } };
        for (const listener of this.listeners) listener(message, target);
      };
    }
  }

  // ---------------------------------------------------------------- persistence

  private load(): MockState {
    try {
      const raw = this.storage?.getItem(STORE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as { version: number } & Partial<MockState>;
        if (parsed.version === 4) return withImages(parsed as MockState);
        // The Secure QR replaced the offline XML (v4): only the summary's timestamp was renamed.
        if (parsed.version === 3) {
          const submissions = (parsed.submissions ?? []).map((s) => {
            if (!s.aadhaar) return s;
            const { xml_generated_at, ...rest } = s.aadhaar as typeof s.aadhaar & { xml_generated_at?: string };
            return { ...s, aadhaar: { ...rest, qr_generated_at: rest.qr_generated_at ?? xml_generated_at ?? iso() } };
          });
          return { ...(parsed as MockState), version: 4, submissions };
        }
        // Plan 4 added orders (v2); Aadhaar e-KYC replaced document upload (v3). Keep everything
        // else a tester made; old document submissions can't be re-verified, so they go.
        if (parsed.version === 1 || parsed.version === 2) {
          const fresh = seedState();
          const users = (parsed.users ?? fresh.users).map((u) => ({ ...u, kyc_status: fresh.users.find((f) => f.id === u.id)?.kyc_status ?? "NOT_SUBMITTED" }));
          return { ...(parsed as MockState), version: 4, orders: parsed.orders ?? [], submissions: fresh.submissions, users };
        }
      }
    } catch {
      // fall through to a fresh seed
    }
    const fresh = seedState();
    this.persist(fresh);
    return fresh;
  }

  private persist(state = this.state): void {
    try {
      this.storage?.setItem(STORE_KEY, JSON.stringify(state));
    } catch {
      // Storage full (large document previews): keep running in memory.
    }
  }

  /** Re-read storage so a write in another tab is visible, then run the lifecycle timer. */
  sync(): void {
    try {
      const raw = this.storage?.getItem(STORE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as MockState;
        if (parsed.version === 4) this.state = withImages(parsed);
      }
    } catch {
      // keep the in-memory state
    }
    this.tick();
  }

  reset(): void {
    this.state = seedState();
    this.persist();
  }

  // ---------------------------------------------------------------- live events

  onLive(listener: LiveListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private publish(message: Record<string, unknown>, target: { auctionId?: string; userId?: string }): void {
    for (const listener of this.listeners) listener(message, target);
    this.channel?.postMessage({ message, target });
  }

  /** Room snapshot for a subscribe with an older last_seq (FR-WS-3). */
  snapshot(auctionId: string): Record<string, unknown> | null {
    this.sync();
    const auction = this.state.auctions.find((a) => a.auction_id === auctionId);
    const leader = this.leader(auctionId);
    if (!auction || !leader) return null;
    return {
      type: "price_update", auction_id: auctionId, current_price: toMoneyString(leader.amount),
      min_next_bid: toMoneyString(minimumNextBid(leader.amount, parseMoney(auction.starting_price))),
      server_seq: leader.server_seq,
    };
  }

  /** The user behind a token, for the WebSocket handshake. Null means close 4401. */
  socketUser(token: string | null): MockUser | null {
    this.sync();
    try {
      return token ? this.principal(token) : null;
    } catch {
      return null;
    }
  }

  // ---------------------------------------------------------------- lifecycle timer

  tick(at = now()): void {
    let changed = false;
    for (const auction of this.state.auctions) {
      if (auction.state === "SCHEDULED" && auction.opens_at && Date.parse(auction.opens_at) <= at) {
        auction.state = "OPEN";
        auction.version += 1;
        changed = true;
      }
      if ((auction.state === "OPEN" || auction.state === "EXTENDED") && auction.closes_at && Date.parse(auction.closes_at) <= at) {
        this.closeAuction(auction);
        changed = true;
      }
      // Saga S1 (CT-4): the orchestrator hands every closed auction with a winner to Payment.
      if (auction.state === "CLOSED" && auction.winning_bid_id && !this.state.orders.some((o) => o.auction_id === auction.auction_id)) {
        this.openOrder(auction, at);
        changed = true;
      }
    }
    if (changed) this.persist();
  }

  private closeAuction(auction: Auction): void {
    // A5 + A6 collapsed: the in-browser queue is always drained.
    auction.state = "CLOSED";
    auction.winning_bid_id = this.leader(auction.auction_id)?.bid_id ?? null;
    auction.version += 1;
    this.publish({ type: "auction_closed", auction_id: auction.auction_id, winning_bid_id: auction.winning_bid_id }, { auctionId: auction.auction_id });
  }

  // ---------------------------------------------------------------- simulated bidders

  /** A synthetic bidder raises the price on an open auction, so a demo shows live movement. */
  simulateBid(auctionId: string): void {
    this.sync();
    const auction = this.state.auctions.find((a) => a.auction_id === auctionId);
    if (!auction || (auction.state !== "OPEN" && auction.state !== "EXTENDED")) return;
    const leader = this.leader(auctionId);
    const bots = ids.bots.filter((id) => id !== leader?.bidder_id);
    const bidder = bots[Math.floor(Math.random() * bots.length)];
    const amount = minimumNextBid(leader?.amount ?? null, parseMoney(auction.starting_price));
    this.acceptBid(auction, bidder, amount);
  }

  // ---------------------------------------------------------------- transport

  handle = async (request: TransportRequest): Promise<TransportResponse> => {
    const [min, max] = this.latency;
    if (max > 0) await new Promise((resolve) => setTimeout(resolve, min + Math.random() * (max - min)));
    this.sync();
    try {
      return await this.route(request);
    } catch (error) {
      if (error instanceof HttpError) {
        const body: ErrorEnvelope = { code: error.code, message: error.message, details: error.details, request_id: crypto.randomUUID() };
        return { status: error.status, headers: {}, body };
      }
      throw error;
    }
  };

  private async route(req: TransportRequest): Promise<TransportResponse> {
    const [path, query = ""] = req.path.split("?");
    const params = new URLSearchParams(query);
    const json = typeof req.body === "string" ? (JSON.parse(req.body) as Record<string, unknown>) : {};
    const key = `${req.method} ${path}`;
    let m: RegExpMatchArray | null;

    switch (key) {
      case "POST /api/v1/auth/register": return ok(201, this.register(json));
      case "POST /api/v1/auth/login": return ok(200, this.login(json));
      case "POST /api/v1/auth/gmail/send-otp": return ok(200, this.sendGmailOtp(json));
      case "POST /api/v1/auth/gmail/verify-otp": return ok(200, this.verifyGmailOtp(json));
      case "POST /api/v1/auth/refresh": return ok(200, this.refresh(json));
      case "POST /api/v1/auth/logout":
        delete this.state.refresh[String(json.refresh_token)];
        this.persist();
        return ok(204, null);
      case "POST /api/v1/auth/verify-email": return ok(200, this.verifyEmailToken(json));
      case "POST /api/v1/auth/resend-verification": return ok(200, this.resendVerification(json));
      case "POST /api/v1/auth/forgot-password": return ok(200, this.forgotPassword(json));
      case "POST /api/v1/auth/reset-password": return ok(200, this.resetPassword(json));
      case "GET /api/v1/users/me": return ok(200, profile(this.auth(req)));
      case "PATCH /api/v1/users/me": return ok(200, this.updateMe(req, json));
      case "PUT /api/v1/users/me/preferences": return ok(200, this.updatePreferences(req, json));
      case "GET /api/v1/auctions": return ok(200, this.listAuctions());
      case "GET /api/v1/auctions/mine": return ok(200, this.listMyAuctions(req));
      case "POST /api/v1/auctions": return ok(201, this.createAuction(req, json));
      case "GET /api/v1/fees/quote": return ok(200, this.quote(params.get("bid_amount") ?? ""));
      case "POST /api/v1/kyc/aadhaar": return ok(201, await this.uploadAadhaar(req));
      case "GET /api/v1/kyc/submissions/me": return ok(200, this.myKyc(req));
      case "GET /api/v1/admin/kyc/queue": return ok(200, this.queue(req, params));
    }

    if ((m = path.match(/^\/api\/v1\/auctions\/([^/]+)$/)) && req.method === "GET") return ok(200, this.auction(m[1]));
    if ((m = path.match(/^\/api\/v1\/auctions\/([^/]+)\/(publish|cancel|events)$/)) && req.method === "POST") {
      return ok(200, this.auctionCommand(req, m[1], m[2], json));
    }
    if ((m = path.match(/^\/api\/v1\/auctions\/([^/]+)\/images$/)) && req.method === "POST") return ok(201, await this.addImage(req, m[1]));
    if ((m = path.match(/^\/api\/v1\/auctions\/([^/]+)\/images\/([^/]+)$/)) && req.method === "DELETE") return ok(200, this.removeImage(req, m[1], m[2]));
    if ((m = path.match(/^\/api\/v1\/auctions\/([^/]+)\/order$/)) && req.method === "GET") {
      const auctionId = m[1];
      return ok(200, this.orderView(req, this.state.orders.find((o) => o.auction_id === auctionId)));
    }
    if ((m = path.match(/^\/api\/v1\/orders\/([^/]+)$/)) && req.method === "GET") {
      const orderId = m[1];
      return ok(200, this.orderView(req, this.state.orders.find((o) => o.order_id === orderId)));
    }
    if ((m = path.match(/^\/api\/v1\/orders\/([^/]+)\/checkout$/)) && req.method === "POST") return ok(200, await this.checkout(req, m[1]));
    if ((m = path.match(/^\/api\/v1\/orders\/([^/]+)\/payment$/)) && req.method === "POST") return ok(200, await this.confirmPayment(req, m[1], json));
    if ((m = path.match(/^\/api\/v1\/orders\/([^/]+)\/ledger$/)) && req.method === "GET") return ok(200, this.ledger(req, m[1]));
    if ((m = path.match(/^\/api\/v1\/auctions\/([^/]+)\/bids$/))) {
      if (req.method === "GET") return ok(200, this.listBids(m[1], params));
      if (req.method === "POST") return this.placeBid(req, m[1], json);
    }
    if ((m = path.match(/^\/api\/v1\/admin\/kyc\/([^/]+)\/documents\/([^/]+)\/url$/)) && req.method === "GET") {
      return { status: 200, headers: { "cache-control": "no-store" }, body: this.documentUrl(req, m[1], m[2]) };
    }
    if ((m = path.match(/^\/api\/v1\/kyc\/submissions\/([^/]+)\/face$/)) && req.method === "POST") return ok(200, await this.faceCheck(req, m[1]));
    if ((m = path.match(/^\/api\/v1\/admin\/kyc\/([^/]+)\/(approve|reject|suspend|reinstate)$/)) && req.method === "POST") {
      return ok(200, this.kycTransition(req, m[1], m[2], json));
    }
    if ((m = path.match(/^\/api\/v1\/admin\/kyc\/([^/]+)$/)) && req.method === "GET") {
      this.admin(req);
      return ok(200, this.adminView(this.submission(m[1])));
    }
    throw new HttpError(404, "NOT_FOUND", `No route ${key}`);
  }

  // ---------------------------------------------------------------- auth

  private token(user: MockUser): string {
    return `mock.${user.id}.${user.token_version}.${now() + ACCESS_TTL_SECONDS * 1000}`;
  }

  private pair(user: MockUser) {
    const refresh = `rt_${crypto.randomUUID().replace(/-/g, "")}`;
    this.state.refresh[refresh] = user.id;
    this.persist();
    return {
      access_token: this.token(user),
      refresh_token: refresh,
      token_type: "Bearer",
      expires_in: ACCESS_TTL_SECONDS,
      user: profile(user),
      is_first_login: !user.onboarded,
    };
  }

  /** Decode a mock access token: mock.<user_id>.<token_version>.<expires_ms>. */
  private principal(token: string): MockUser {
    const [prefix, userId, version, expires] = token.split(".");
    const user = this.state.users.find((u) => u.id === userId);
    if (prefix !== "mock" || !user || Number(expires) < now()) {
      throw new HttpError(401, "UNAUTHENTICATED", "Missing, expired or invalid bearer token");
    }
    this.claims.set(user.id, Number(version));
    return user;
  }

  private auth(req: TransportRequest): MockUser {
    const header = req.headers.Authorization ?? "";
    if (!header.startsWith("Bearer ")) throw new HttpError(401, "UNAUTHENTICATED", "Missing bearer token");
    return this.principal(header.slice(7));
  }

  private admin(req: TransportRequest): MockUser {
    const user = this.auth(req);
    if (user.role !== "ADMIN") throw new HttpError(403, "FORBIDDEN", "Requires role ADMIN");
    return user;
  }

  /** zeo_common.gateway listing gate: fresh token, not suspended, KYC verified. */
  private verifiedSeller(req: TransportRequest): MockUser {
    const user = this.auth(req);
    if (this.claims.get(user.id) !== user.token_version) {
      throw new HttpError(401, "UNAUTHENTICATED", "Your account status changed; refresh the access token and retry", { reason: "TOKEN_STALE" });
    }
    if (user.suspended) throw new HttpError(403, "ACCOUNT_SUSPENDED", "This account is suspended");
    if (user.kyc_status !== "VERIFIED") {
      throw new HttpError(403, "SELLER_NOT_VERIFIED", "Seller verification (KYC) must be approved before listing", { kyc_status: user.kyc_status });
    }
    return user;
  }

  private register(body: Record<string, unknown>): Profile {
    const email = String(body.email ?? "").trim().toLowerCase();
    const password = String(body.password ?? "");
    const name = String(body.display_name ?? "").trim();
    if (email.length > 254 || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) throw validation("email", "Enter a valid email address");
    if (password.length < 10 || password.length > 128) throw validation("password", "Password must be 10 to 128 characters");
    if (/^[A-Za-z]+$/.test(password) || /^\d+$/.test(password)) throw validation("password", "Password must mix letters with digits or symbols");
    if (name.length < 1 || name.length > 80) throw validation("display_name", "Display name must be 1 to 80 characters");
    if (this.state.users.some((u) => u.email === email)) throw new HttpError(409, "EMAIL_ALREADY_REGISTERED", "An account with this email exists");
    const user: MockUser = {
      id: crypto.randomUUID(), email, password, display_name: name, role: "USER", kyc_status: "NOT_SUBMITTED",
      suspended: false, token_version: 1, created_at: iso(), favorite_categories: [], onboarded: false,
      email_verified: false,
    };
    this.state.users.push(user);
    this.persist();
    const token = crypto.randomUUID().replace(/-/g, "");
    this.emailTokens.set(token, { userId: user.id, type: "VERIFY_EMAIL", expiresAt: now() + 24 * 60 * 60 * 1000 });
    return profile(user);
  }

  private sendGmailOtp(body: Record<string, unknown>) {
    const email = String(body.email ?? "").trim().toLowerCase();
    if (email.length > 254 || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) throw validation("email", "Enter a valid email address");
    const code = String(Math.floor(100000 + Math.random() * 900000));
    this.otps.set(email, { code, expiresAt: now() + 10 * 60 * 1000 });
    return { status: "sent", email, expires_in: 600, dev_otp: code };
  }

  private verifyGmailOtp(body: Record<string, unknown>) {
    const email = String(body.email ?? "").trim().toLowerCase();
    const code = String(body.otp ?? "").trim();
    const entry = this.otps.get(email);
    if (!entry || entry.code !== code || entry.expiresAt < now()) {
      throw new HttpError(401, "INVALID_OTP", "The verification code is incorrect or expired");
    }
    this.otps.delete(email);

    let user = this.state.users.find((u) => u.email === email);
    let isFirstLogin = false;
    if (!user) {
      isFirstLogin = true;
      const rawName = String(body.display_name ?? "").trim() || email.split("@")[0] || "User";
      user = {
        id: crypto.randomUUID(),
        email,
        password: "zeo-dev-password",
        display_name: rawName.slice(0, 80),
        role: "USER",
        kyc_status: "NOT_SUBMITTED",
        suspended: false,
        token_version: 1,
        created_at: iso(),
        favorite_categories: [],
        onboarded: false,
        email_verified: true,
      };
      this.state.users.push(user);
      this.persist();
    } else {
      user.email_verified = true;
      this.persist();
      isFirstLogin = !user.onboarded;
    }
    const pair = this.pair(user);
    return { ...pair, is_first_login: isFirstLogin };
  }

  private verifyEmailToken(body: Record<string, unknown>) {
    const token = String(body.token ?? "");
    const entry = this.emailTokens.get(token);
    if (!entry || entry.type !== "VERIFY_EMAIL" || entry.expiresAt < now()) {
      throw new HttpError(400, "INVALID_TOKEN", "Verification link is invalid or has expired");
    }
    this.emailTokens.delete(token);
    const user = this.state.users.find((u) => u.id === entry.userId);
    if (!user) throw new HttpError(404, "NOT_FOUND", "User not found");
    user.email_verified = true;
    this.persist();
    return { status: "verified", email: user.email };
  }

  private resendVerification(body: Record<string, unknown>) {
    const email = String(body.email ?? "").trim().toLowerCase();
    const user = this.state.users.find((u) => u.email === email);
    if (!user) return { status: "sent", email }; // don't reveal non-existence
    const token = crypto.randomUUID().replace(/-/g, "");
    this.emailTokens.set(token, { userId: user.id, type: "VERIFY_EMAIL", expiresAt: now() + 24 * 60 * 60 * 1000 });
    return { status: "sent", email };
  }

  private forgotPassword(body: Record<string, unknown>) {
    const email = String(body.email ?? "").trim().toLowerCase();
    const user = this.state.users.find((u) => u.email === email);
    if (!user) return { status: "sent", email }; // don't reveal non-existence
    const token = crypto.randomUUID().replace(/-/g, "");
    this.emailTokens.set(token, { userId: user.id, type: "RESET_PASSWORD", expiresAt: now() + 60 * 60 * 1000 });
    return { status: "sent", email };
  }

  private resetPassword(body: Record<string, unknown>) {
    const token = String(body.token ?? "");
    const newPassword = String(body.new_password ?? "");
    const entry = this.emailTokens.get(token);
    if (!entry || entry.type !== "RESET_PASSWORD" || entry.expiresAt < now()) {
      throw new HttpError(400, "INVALID_TOKEN", "Reset link is invalid or has expired");
    }
    if (newPassword.length < 10 || newPassword.length > 128) throw validation("new_password", "Password must be 10 to 128 characters");
    if (/^[A-Za-z]+$/.test(newPassword) || /^\d+$/.test(newPassword)) throw validation("new_password", "Password must mix letters with digits or symbols");
    this.emailTokens.delete(token);
    const user = this.state.users.find((u) => u.id === entry.userId);
    if (!user) throw new HttpError(404, "NOT_FOUND", "User not found");
    user.password = newPassword;
    this.persist();
    return { status: "password_updated" };
  }

  private updatePreferences(req: TransportRequest, body: Record<string, unknown>): Profile {
    const user = this.auth(req);
    const raw = Array.isArray(body.favorite_categories) ? body.favorite_categories : [];
    const valid = ["watches", "cameras", "jewelry", "music", "furniture", "books", "art", "electronics"];
    user.favorite_categories = [...new Set(raw.map(String).map((c) => c.toLowerCase()).filter((c) => valid.includes(c)))];
    user.onboarded = body.onboarded !== undefined ? Boolean(body.onboarded) : true;
    this.persist();
    return profile(user);
  }

  private login(body: Record<string, unknown>) {
    const email = String(body.email ?? "").trim().toLowerCase();
    const user = this.state.users.find((u) => u.email === email);
    if (!user || user.password !== body.password) throw new HttpError(401, "INVALID_CREDENTIALS", "Email or password is incorrect");
    if (!user.email_verified) {
      throw new HttpError(403, "EMAIL_NOT_VERIFIED", "Please verify your email address before logging in. Check your inbox for the verification link.", { email: user.email });
    }
    return this.pair(user);
  }

  private refresh(body: Record<string, unknown>) {
    const token = String(body.refresh_token ?? "");
    const userId = this.state.refresh[token];
    if (!userId) throw new HttpError(401, "REFRESH_TOKEN_INVALID", "Refresh token is invalid or was revoked");
    delete this.state.refresh[token]; // rotation: each refresh token works once
    const user = this.state.users.find((u) => u.id === userId);
    if (!user) throw new HttpError(401, "REFRESH_TOKEN_INVALID", "Account no longer exists");
    return this.pair(user);
  }

  private updateMe(req: TransportRequest, body: Record<string, unknown>): Profile {
    const user = this.auth(req);
    if ("display_name" in body && body.display_name !== undefined) {
      const name = String(body.display_name ?? "").trim();
      if (name.length < 1 || name.length > 80) throw validation("display_name", "Display name must be 1 to 80 characters");
      user.display_name = name;
    }
    if ("favorite_categories" in body && body.favorite_categories !== undefined) {
      const raw = Array.isArray(body.favorite_categories) ? body.favorite_categories : [];
      const valid = ["watches", "cameras", "jewelry", "music", "furniture", "books", "art", "electronics"];
      user.favorite_categories = [...new Set(raw.map(String).map((c) => c.toLowerCase()).filter((c) => valid.includes(c)))];
    }
    if ("onboarded" in body && body.onboarded !== undefined) {
      user.onboarded = Boolean(body.onboarded);
    }
    this.persist();
    return profile(user);
  }

  // ---------------------------------------------------------------- auctions

  private auction(id: string): Auction {
    const auction = this.state.auctions.find((a) => a.auction_id === id);
    if (!auction) throw new HttpError(404, "NOT_FOUND", `Auction ${id} does not exist`);
    return auction;
  }

  private listAuctions(): Auction[] {
    return this.state.auctions.filter((a) => a.state !== "DRAFT" && a.state !== "CANCELLED");
  }

  private listMyAuctions(req: TransportRequest): Auction[] {
    const caller = this.auth(req);
    return this.state.auctions.filter((auction) => auction.seller_id === caller.id);
  }

  private createAuction(req: TransportRequest, body: Record<string, unknown>): Auction {
    const seller = this.verifiedSeller(req);
    if ("seller_id" in body) throw validation("seller_id", "Extra inputs are not permitted");
    const title = String(body.title ?? "").trim();
    const category = String(body.category ?? "").trim();
    const starting = String(body.starting_price ?? "");
    const reserve = body.reserve_price == null ? null : String(body.reserve_price);
    if (!MONEY.test(starting)) throw validation("starting_price", "starting_price must be a two-decimal amount");
    if (reserve !== null && !MONEY.test(reserve)) throw validation("reserve_price", "reserve_price must be a two-decimal amount");
    if (title.length < 3 || title.length > 200) throw validation("title", "title must be 3 to 200 characters");
    if (!category) throw validation("category", "category is required");
    if (reserve !== null && parseMoney(reserve) < parseMoney(starting)) throw validation("reserve_price", "reserve_price must not be below starting_price");
    const opens = body.opens_at ? String(body.opens_at) : null;
    const closes = body.closes_at ? String(body.closes_at) : null;
    if (opens && closes && Date.parse(closes) <= Date.parse(opens)) throw validation("closes_at", "closes_at must be after opens_at");
    const auction: Auction = {
      auction_id: crypto.randomUUID(), seller_id: seller.id, title, description: String(body.description ?? ""), category,
      starting_price: starting, reserve_price: reserve, currency: String(body.currency ?? policy.currency), state: "DRAFT",
      opens_at: opens, closes_at: closes, original_closes_at: closes, extension_count: 0, max_extensions: policy.maxExtensions,
      guard_interval_seconds: policy.guardSeconds, extension_seconds: policy.extensionSeconds, winning_bid_id: null, version: 1,
      images: [],
    };
    this.state.auctions.unshift(auction);
    this.persist();
    return auction;
  }

  /** The seller's own auction, while its photos may still change (DRAFT or SCHEDULED). */
  private editablePhotos(req: TransportRequest, id: string): Auction {
    const seller = this.verifiedSeller(req);
    const auction = this.auction(id);
    if (auction.seller_id !== seller.id) throw new HttpError(403, "FORBIDDEN", "Only the seller can change this auction's photos");
    if (auction.state !== "DRAFT" && auction.state !== "SCHEDULED") {
      throw new HttpError(409, "CONFLICT", `Photos can only change while the auction is DRAFT or SCHEDULED, not ${auction.state}`, { state: auction.state });
    }
    return auction;
  }

  private async addImage(req: TransportRequest, id: string): Promise<Auction> {
    const auction = this.editablePhotos(req, id);
    const image = (req.body instanceof FormData ? req.body : new FormData()).get("image");
    const invalid = (reason: string, message: string) => new HttpError(422, "VALIDATION_ERROR", message, { field: "image", reason });
    if (!(image instanceof Blob) || image.size === 0) throw invalid("empty", "The photo is empty");
    if (image.size > LISTING_PHOTOS.maxBytes) throw invalid("too_large", "Each photo must be at most 5 MB");
    if (!isImage((await readBytes(image.slice(0, 12))))) throw invalid("unsupported_format", "Only JPEG, PNG and WebP photos are accepted");
    const taken = new Set(auction.images.map((i) => i.position));
    const position = [...Array(LISTING_PHOTOS.max).keys()].find((p) => !taken.has(p));
    if (position === undefined) throw invalid("too_many", `An auction can have at most ${LISTING_PHOTOS.max} photos`);
    // Small photos survive a reload as data URLs; larger ones last for this tab only.
    const url = image.size <= MAX_STORED_PREVIEW ? await readDataUrl(image) : null;
    auction.images = [...auction.images, {
      image_id: crypto.randomUUID(), position, mime_type: image.type || "image/jpeg",
      url: url ?? (typeof URL.createObjectURL === "function" ? URL.createObjectURL(image) : ""),
    }].sort((a, b) => a.position - b.position);
    this.persist();
    return auction;
  }

  private removeImage(req: TransportRequest, id: string, imageId: string): Auction {
    const auction = this.editablePhotos(req, id);
    if (!auction.images.some((i) => i.image_id === imageId)) throw new HttpError(404, "NOT_FOUND", `Photo ${imageId} does not exist`);
    auction.images = auction.images.filter((i) => i.image_id !== imageId);
    this.persist();
    return auction;
  }

  private auctionCommand(req: TransportRequest, id: string, command: string, body: Record<string, unknown>): Auction {
    const auction = this.auction(id);
    const conflict = (event: string) => new HttpError(409, "CONFLICT", `Cannot ${event} an auction in state ${auction.state}`);
    if (command === "publish") {
      const seller = this.verifiedSeller(req);
      if (auction.seller_id !== seller.id) throw new HttpError(403, "FORBIDDEN", "Only the seller can publish this auction");
      if (auction.state !== "DRAFT") throw conflict("publish");
      if (!auction.opens_at || !auction.closes_at) throw validation("opens_at", "opens_at and closes_at are required to publish");
      if (Date.parse(auction.opens_at) < now() - 60_000) throw validation("opens_at", "opens_at is in the past");
      this.transition(auction, "SCHEDULED");
    } else if (command === "cancel") {
      const caller = this.auth(req);
      if (auction.seller_id !== caller.id && caller.role !== "ADMIN") throw new HttpError(403, "FORBIDDEN", "Only the seller or an administrator can cancel this auction");
      if (auction.state !== "DRAFT" && auction.state !== "SCHEDULED") throw conflict("cancel");
      if (this.state.bids.some((b) => b.auction_id === id)) throw new HttpError(409, "CONFLICT", "An auction with bids cannot be cancelled");
      this.transition(auction, "CANCELLED");
    } else {
      this.admin(req);
      const event = String(body.event);
      if (event === "open" && auction.state === "SCHEDULED") {
        auction.opens_at = iso();
        this.transition(auction, "OPEN");
      } else if (event === "close" && (auction.state === "OPEN" || auction.state === "EXTENDED")) {
        auction.closes_at = iso();
        this.closeAuction(auction);
        this.persist();
      } else if (event === "settle" && auction.state === "CLOSED" && auction.winning_bid_id) {
        this.transition(auction, "SETTLED");
      } else {
        throw conflict(event);
      }
    }
    return auction;
  }

  private transition(auction: Auction, to: AuctionState): void {
    auction.state = to;
    auction.version += 1;
    this.persist();
  }

  // ---------------------------------------------------------------- bids

  private leader(auctionId: string): MockBid | null {
    let best: MockBid | null = null;
    for (const bid of this.state.bids) {
      if (bid.auction_id === auctionId && (!best || bid.server_seq > best.server_seq)) best = bid;
    }
    return best;
  }

  private listBids(auctionId: string, params: URLSearchParams) {
    this.auction(auctionId);
    const page = Math.max(1, Number(params.get("page") ?? 1));
    const size = Math.min(100, Math.max(1, Number(params.get("page_size") ?? 20)));
    const all = this.state.bids.filter((b) => b.auction_id === auctionId).sort((a, b) => b.server_seq - a.server_seq);
    return {
      page, page_size: size, total: all.length,
      items: all.slice((page - 1) * size, page * size).map((b) => ({
        bid_id: b.bid_id, auction_id: b.auction_id, amount: toMoneyString(b.amount), server_seq: b.server_seq,
        accepted_at: b.accepted_at, bidder_alias: alias(b.auction_id, b.bidder_id),
      })),
    };
  }

  private placeBid(req: TransportRequest, auctionId: string, body: Record<string, unknown>): TransportResponse {
    const bidder = this.auth(req);
    const key = req.headers["Idempotency-Key"];
    if (!key || key.length < 8) throw validation("Idempotency-Key", "Idempotency-Key header is required");
    const replayKey = `${bidder.id}:${key}`;
    const previous = this.state.idempotency[replayKey];
    if (previous) return { status: previous.status === 202 ? 200 : previous.status, headers: { "idempotent-replay": "true" }, body: previous.body };

    const amountText = String(body.amount ?? "");
    if (!MONEY.test(amountText)) throw validation("amount", "amount must be a two-decimal string");
    const auction = this.auction(auctionId);
    const amount = parseMoney(amountText);
    const leader = this.leader(auctionId);
    const minNext = minimumNextBid(leader?.amount ?? null, parseMoney(auction.starting_price));

    const reject = (status: number, code: string, message: string, details: Record<string, unknown> | null = null) => {
      const envelope = { code, message, details, request_id: crypto.randomUUID() };
      this.state.idempotency[replayKey] = { status, body: envelope };
      this.persist();
      return { status, headers: {}, body: envelope };
    };
    if (bidder.suspended) return reject(403, "ACCOUNT_SUSPENDED", "Caller is suspended");
    if (auction.seller_id === bidder.id) return reject(403, "SELF_BIDDING_FORBIDDEN", "Sellers cannot bid on their own auction");
    if (auction.state !== "OPEN" && auction.state !== "EXTENDED") return reject(409, "AUCTION_NOT_OPEN", `Auction is ${auction.state}`, { state: auction.state });
    if (amount < minNext) return reject(422, "BID_BELOW_INCREMENT", "Bid is below the minimum next bid", { min_next_bid: toMoneyString(minNext) });

    const accepted = this.acceptBid(auction, bidder.id, amount);
    this.state.idempotency[replayKey] = { status: 202, body: accepted };
    this.persist();
    return { status: 202, headers: {}, body: accepted };
  }

  private acceptBid(auction: Auction, bidderId: string, amount: number) {
    const previous = this.leader(auction.auction_id);
    const at = now();
    const bid: MockBid = {
      bid_id: crypto.randomUUID(), auction_id: auction.auction_id, bidder_id: bidderId, amount,
      server_seq: (previous?.server_seq ?? 0) + 1, accepted_at: iso(at),
    };
    this.state.bids.push(bid);
    const minNext = minimumNextBid(amount, parseMoney(auction.starting_price));

    // A4 anti-snipe: a bid inside the guard interval extends the close, up to the cap.
    if (auction.closes_at && Date.parse(auction.closes_at) - at < auction.guard_interval_seconds * 1000
        && auction.extension_count < auction.max_extensions) {
      auction.closes_at = iso(Date.parse(auction.closes_at) + auction.extension_seconds * 1000);
      auction.extension_count += 1;
      auction.state = "EXTENDED";
      auction.version += 1;
      this.publish({ type: "auction_extended", auction_id: auction.auction_id, new_closes_at: auction.closes_at }, { auctionId: auction.auction_id });
    }
    this.persist();

    this.publish({
      type: "price_update", auction_id: auction.auction_id, current_price: toMoneyString(amount),
      min_next_bid: toMoneyString(minNext), server_seq: bid.server_seq,
    }, { auctionId: auction.auction_id });
    if (previous && previous.bidder_id !== bidderId) {
      this.publish({
        type: "outbid", auction_id: auction.auction_id, your_bid_id: previous.bid_id,
        current_price: toMoneyString(amount), server_seq: bid.server_seq,
      }, { userId: previous.bidder_id });
    }
    return {
      bid_id: bid.bid_id, auction_id: auction.auction_id, server_seq: bid.server_seq,
      current_price: toMoneyString(amount), min_next_bid: toMoneyString(minNext), accepted_at: bid.accepted_at,
    };
  }

  private quote(amountText: string) {
    if (!MONEY.test(amountText)) throw validation("bid_amount", "bid_amount must be a two-decimal amount");
    const amount = parseMoney(amountText);
    return {
      bid_amount: amountText, convenience_fee: toMoneyString(policy.feeCents), total: toMoneyString(amount + policy.feeCents),
      currency: policy.currency, fee_version: policy.feeVersion,
    };
  }

  // ---------------------------------------------------------------- orders (Plan 4, ADR-0009)

  /** S1: order and invoice for the winning bid only, at the flat fee in force. */
  private openOrder(auction: Auction, at: number): void {
    const winner = this.state.bids.find((b) => b.bid_id === auction.winning_bid_id);
    if (!winner) return;
    const orderId = crypto.randomUUID();
    const fee = toMoneyString(policy.feeCents);
    const total = toMoneyString(winner.amount + policy.feeCents);
    const issued = iso(at);
    const invoiceNumber = `ZA-${issued.slice(0, 4)}${issued.slice(5, 7)}-${orderId.replace(/-/g, "").slice(0, 12).toUpperCase()}`;
    this.state.orders.push({
      order_id: orderId, auction_id: auction.auction_id, buyer_id: winner.bidder_id, seller_id: auction.seller_id,
      winning_bid_id: winner.bid_id, state: "INVOICED", winning_bid_amount: toMoneyString(winner.amount),
      convenience_fee: fee, total, currency: policy.currency, fee_version: policy.feeVersion,
      provider: "mock", payment_due_at: iso(at + policy.paymentWindowHours * 3_600_000), authorized_at: null,
      created_at: issued, updated_at: issued, test_mode: true,
      notice: "Payment is held in secure escrow until order delivery is confirmed.",
      invoice: {
        invoice_number: invoiceNumber, bid_amount: toMoneyString(winner.amount), convenience_fee: fee, total,
        currency: policy.currency, fee_version: policy.feeVersion, issued_at: issued, voided_at: null,
      },
      provider_order_id: null,
    });
  }

  private orderView(req: TransportRequest, order: MockOrder | undefined): Order {
    const caller = this.auth(req);
    if (!order) throw new HttpError(404, "NOT_FOUND", "No order for this auction yet");
    if (caller.role !== "ADMIN" && caller.id !== order.buyer_id && caller.id !== order.seller_id) {
      throw new HttpError(403, "FORBIDDEN", "Only the buyer, the seller or an administrator can see this order");
    }
    const view: Order & Partial<Pick<MockOrder, "provider_order_id" | "ledger">> = { ...order };
    delete view.provider_order_id;
    delete view.ledger;
    return view;
  }

  private buyersOrder(req: TransportRequest, orderId: string): MockOrder {
    const caller = this.auth(req);
    const order = this.state.orders.find((o) => o.order_id === orderId);
    if (!order) throw new HttpError(404, "NOT_FOUND", `Order ${orderId} does not exist`);
    if (caller.id !== order.buyer_id) throw new HttpError(403, "FORBIDDEN", "Only the winning bidder can pay this order");
    return order;
  }

  /** Repeating checkout returns the same provider order. Real Razorpay (test) when the dev bridge is up. */
  private async checkout(req: TransportRequest, orderId: string): Promise<CheckoutSession> {
    const order = this.buyersOrder(req, orderId);
    if (order.state !== "INVOICED") {
      throw new HttpError(409, "ORDER_NOT_PAYABLE", `Order is ${order.state}; there is nothing to pay`, { state: order.state });
    }
    const description = `Invoice ${order.invoice.invoice_number} (test mode)`;
    const bridge = await this.payments();
    if (bridge && (order.provider_order_id === null || order.provider === "razorpay")) {
      if (order.provider_order_id) return this.razorpaySession(order, bridge.keyId, description);
      const created = await viaBridge(() => bridge.createOrder({
        amount_minor: parseMoney(order.total), currency: order.currency, receipt: order.invoice.invoice_number,
        notes: { order_id: order.order_id, auction_id: order.auction_id, environment: "zeoauction-mock-mode" },
      }));
      // The bridge call yielded: re-read storage so a write from another tab isn't lost.
      this.sync();
      const fresh = this.state.orders.find((o) => o.order_id === order.order_id) ?? order;
      fresh.provider = "razorpay";
      fresh.provider_order_id = created.provider_order_id;
      fresh.updated_at = iso();
      this.persist();
      return this.razorpaySession(fresh, bridge.keyId, description);
    }
    if (order.provider === "razorpay") {
      throw new HttpError(503, "PAYMENT_PROVIDER_UNAVAILABLE", "This order is paid through Razorpay test mode, and the dev server's bridge is off");
    }
    order.provider_order_id ??= `mock_order_${fakeDigest(order.order_id).slice(0, 14)}`;
    this.persist();
    const paymentId = `mock_pay_${fakeDigest(order.provider_order_id).slice(0, 14)}`;
    return {
      order_id: order.order_id, provider: "mock", key_id: "mock_key", provider_order_id: order.provider_order_id,
      amount: order.total, amount_minor: parseMoney(order.total), currency: order.currency, description,
      simulated_payment: { payment_id: paymentId, signature: mockSignature(order.provider_order_id, paymentId) },
      test_mode: true,
    };
  }

  private razorpaySession(order: MockOrder, keyId: string, description: string): CheckoutSession {
    return {
      order_id: order.order_id, provider: "razorpay", key_id: keyId, provider_order_id: order.provider_order_id!,
      amount: order.total, amount_minor: parseMoney(order.total), currency: order.currency, description,
      simulated_payment: null, test_mode: true,
    };
  }

  /** Verify Checkout's signature, capture and hold (S2, S3), then A7 settle. */
  private async confirmPayment(req: TransportRequest, orderId: string, body: Record<string, unknown>): Promise<Order> {
    const order = this.buyersOrder(req, orderId);
    const key = req.headers["Idempotency-Key"];
    if (!key || key.length < 8) throw validation("Idempotency-Key", "Idempotency-Key header is required");
    const providerOrder = String(body.provider_order_id ?? "");
    const paymentId = String(body.payment_id ?? "");
    if (!order.provider_order_id || providerOrder !== order.provider_order_id) {
      throw new HttpError(400, "PAYMENT_SIGNATURE_INVALID", "The payment signature is invalid");
    }
    if (order.provider !== "razorpay" && body.signature !== mockSignature(providerOrder, paymentId)) {
      throw new HttpError(400, "PAYMENT_SIGNATURE_INVALID", "The payment signature is invalid");
    }
    if (order.state !== "INVOICED") return this.orderView(req, order); // a retry after success

    let outcome: { captured: boolean; ref: string };
    if (order.provider === "razorpay") {
      const bridge = await this.payments();
      if (!bridge) throw new HttpError(503, "PAYMENT_PROVIDER_UNAVAILABLE", "The dev server's Razorpay bridge is off; nothing was captured");
      const result = await viaBridge(() => bridge.capture({
        provider_order_id: providerOrder, payment_id: paymentId, signature: String(body.signature ?? ""), amount_minor: parseMoney(order.total),
      }));
      outcome = { captured: result.status === "captured", ref: result.payment_id };
      this.sync();
    } else {
      // The mock provider's test-card convention: a total ending in .13 is declined (O4).
      outcome = { captured: !order.total.endsWith(".13"), ref: paymentId };
    }

    const current = this.state.orders.find((o) => o.order_id === order.order_id) ?? order;
    if (current.state === "INVOICED") {
      const at = iso();
      current.authorized_at = at;
      current.updated_at = at;
      if (outcome.captured) {
        current.state = "IN_ESCROW";
        current.ledger = this.holdRows(current, outcome.ref, at);
        const auction = this.state.auctions.find((a) => a.auction_id === current.auction_id);
        if (auction?.state === "CLOSED") this.transition(auction, "SETTLED");
      } else {
        current.state = "CANCELLED";
        current.invoice.voided_at = at;
      }
      this.persist();
    }
    return this.orderView(req, current);
  }

  /** S3: CAPTURE (+total), HOLD (0) and FEE_RETAIN (-fee), the rows payment-escrow appends. */
  private holdRows(order: MockOrder, paymentRef: string, at: string): LedgerEntry[] {
    const row = (id: number, entry_type: LedgerEntry["entry_type"], amount: string, note: string): LedgerEntry => ({
      id, entry_type, amount, currency: order.currency, idempotency_key: `order:${order.order_id}:${entry_type.toLowerCase()}`,
      provider_ref: entry_type === "CAPTURE" ? paymentRef : null, note, created_at: at,
    });
    return [
      row(1, "CAPTURE", order.total, "Winner's payment captured into custody"),
      row(2, "HOLD", "0.00", `Held in escrow for the ${policy.protectionDays}-day protection window`),
      row(3, "FEE_RETAIN", `-${order.convenience_fee}`, `Convenience fee (${order.fee_version}) retained by the platform`),
    ];
  }

  /** The order's escrow ledger, admins only (getOrderLedger). */
  private ledger(req: TransportRequest, orderId: string): LedgerEntry[] {
    this.admin(req);
    const order = this.state.orders.find((o) => o.order_id === orderId);
    if (!order) throw new HttpError(404, "NOT_FOUND", `Order ${orderId} does not exist`);
    return order.ledger ?? [];
  }

  // ---------------------------------------------------------------- KYC
  //
  // Aadhaar Secure QR + live face check. The QR is read for real (src/lib/mock/aadhaarQr.ts:
  // UIDAI's signature, layout, 18+, mobile), so the summary shows what the QR says. The face
  // check is simulated; the image's file name scripts it for demos:
  //   *review*   -> face check goes to review   *nomatch* -> face never matches
  // Anything else matches.

  private latestSubmission(userId: string): MockSubmission | null {
    const mine = this.state.submissions.filter((s) => s.user_id === userId);
    return mine.sort((a, b) => Date.parse(b.submitted_at) - Date.parse(a.submitted_at))[0] ?? null;
  }

  private submission(id: string): MockSubmission {
    const found = this.state.submissions.find((s) => s.id === id);
    if (!found) throw new HttpError(404, "NOT_FOUND", "Submission not found");
    return found;
  }

  private counted(s: MockSubmission): number {
    return s.attempts.filter((a) => COUNTED.has(a.outcome)).length;
  }

  /** services/kyc KycService._resubmission: may a new Aadhaar upload start now, and from when. */
  private resubmission(s: MockSubmission | null): { can: boolean; after: string | null } {
    if (!s) return { can: true, after: null };
    if (s.state === "REJECTED") {
      if (this.counted(s) >= FACE.maxAttempts && s.decided_at) {
        const after = Date.parse(s.decided_at) + FACE.cooldownMs;
        return now() >= after ? { can: true, after: null } : { can: false, after: iso(after) };
      }
      return { can: true, after: null };
    }
    if (s.state === "SUBMITTED") return { can: this.counted(s) === 0, after: null };
    return { can: false, after: null };
  }

  private sellerView(s: MockSubmission) {
    const { can, after } = this.resubmission(s);
    // Sellers see less than reviewers: no PIN code (services/kyc AadhaarView).
    const aadhaar = s.aadhaar
      ? { holder_name: s.aadhaar.holder_name, year_of_birth: s.aadhaar.year_of_birth, gender: s.aadhaar.gender, state: s.aadhaar.state,
          reference_last4: s.aadhaar.reference_last4, qr_generated_at: s.aadhaar.qr_generated_at, mobile_verified: s.aadhaar.mobile_verified }
      : null;
    return {
      submission_id: s.id, state: s.state, rejection_reason: s.rejection_reason, submitted_at: s.submitted_at,
      decided_at: s.decided_at, can_resubmit: can, resubmit_after: after, aadhaar,
      face: { attempts_used: s.attempts.length, attempts_left: Math.max(0, FACE.maxAttempts - this.counted(s)), last_outcome: s.attempts.at(-1)?.outcome ?? null },
      documents: s.documents.map((d) => ({ document_id: d.id, doc_type: d.doc_type, mime_type: d.mime_type, size_bytes: d.size_bytes, uploaded_at: d.uploaded_at })),
    };
  }

  private adminView(s: MockSubmission) {
    return {
      submission_id: s.id, user_id: s.user_id, state: s.state, rejection_reason: s.rejection_reason,
      submitted_at: s.submitted_at, decided_at: s.decided_at, decided_by: s.decided_by,
      aadhaar: s.aadhaar ? { ...s.aadhaar, signer_sha256: fakeDigest("mock-uidai-signer"), face_model: "mock-engine", reference_faces: 1 } : null,
      face_attempts: s.attempts,
      documents: s.documents.map((d) => ({
        document_id: d.id, doc_type: d.doc_type, mime_type: d.mime_type, size_bytes: d.size_bytes, uploaded_at: d.uploaded_at, sha256: d.sha256,
      })),
    };
  }

  private setStatus(userId: string, status: KycStatus): void {
    const user = this.state.users.find((u) => u.id === userId);
    if (!user) return;
    user.kyc_status = status;
    // Every KYC status change forces a token refresh, so the listing gate sees it at once.
    user.token_version += 1;
  }

  private myKyc(req: TransportRequest) {
    const user = this.auth(req);
    const latest = this.latestSubmission(user.id);
    if (!latest) throw new HttpError(404, "NOT_FOUND", "No KYC submission yet", { kyc_status: "NOT_SUBMITTED" });
    return this.sellerView(latest);
  }

  private async uploadAadhaar(req: TransportRequest) {
    const user = this.auth(req);
    const latest = this.latestSubmission(user.id);
    const { can, after } = this.resubmission(latest);
    if (!can) {
      if (after) throw new HttpError(409, "KYC_COOLDOWN", "The face check failed too many times; you can try again later", { retry_after: after });
      throw new HttpError(409, "KYC_ALREADY_ACTIVE", "A verification is already in progress or approved", latest ? { state: latest.state } : null);
    }
    const form = req.body instanceof FormData ? req.body : new FormData();
    const image = form.get("qr_image");
    const mobile = String(form.get("mobile") ?? "").replace(/\D/g, "").replace(/^91(?=\d{10}$)/, "");
    const invalid = (reason: string, message: string, field = "qr_image") => new HttpError(422, "AADHAAR_INVALID", message, { reason, field });
    if (!(image instanceof Blob)) throw validation("qr_image", "Upload a photo of the Aadhaar QR code");
    if (image.size === 0) throw invalid("not_image", "The file is empty");
    if (image.size > MAX_QR_IMAGE_BYTES) throw invalid("too_large", "The photo must be at most 8 MB");
    if (!isImage(await readBytes(image.slice(0, 12)))) throw invalid("not_image", "Upload a JPEG, PNG or WebP photo of the QR code");
    const name = (image instanceof File ? image.name : "").toLowerCase();
    let qr;
    try {
      const texts = await this.qrCodes(image).catch(() => []);
      qr = await readSecureQr(texts, { now: new Date(now()), mobile: mobile || undefined, trustedKeys: this.trustedQrKeys });
    } catch (error) {
      if (error instanceof AadhaarInvalid) throw invalid(error.reason, error.message, error.field);
      throw error;
    }
    const plan: MockFacePlan = name.includes("nomatch") ? "no_match" : name.includes("review") ? "review" : "match";
    if (latest && latest.state === "SUBMITTED") {
      latest.state = "REJECTED";
      latest.rejection_reason = "Replaced by a new Aadhaar QR upload";
      latest.decided_at = iso();
    }
    const submission: MockSubmission = {
      id: crypto.randomUUID(), user_id: user.id, state: "UNDER_REVIEW", rejection_reason: null,
      submitted_at: iso(), decided_at: null, decided_by: null,
      documents: [{
        id: crypto.randomUUID(), doc_type: "AADHAAR_PHOTO", mime_type: "image/jpeg", size_bytes: 9_400, uploaded_at: iso(),
        sha256: fakeDigest(`aadhaar:${user.id}:${now()}`), name: "aadhaar-photo.jpg", data_url: null,
      }],
      aadhaar: {
        holder_name: qr.name, year_of_birth: qr.year_of_birth, gender: qr.gender, state: qr.state, pincode: qr.pincode,
        reference_last4: qr.reference_last4, qr_generated_at: qr.generated_at.toISOString(), mobile_verified: qr.mobile_verified,
      },
      attempts: [], face_plan: plan,
    };
    this.state.submissions.push(submission);
    // Live KYC no longer has a face-capture step: a verified Secure QR goes straight to admin.
    this.setStatus(user.id, "UNDER_REVIEW");
    this.persist();
    return this.sellerView(submission);
  }

  private async faceCheck(req: TransportRequest, id: string) {
    const user = this.auth(req);
    const submission = this.submission(id);
    if (submission.user_id !== user.id) throw new HttpError(404, "NOT_FOUND", "Submission not found");
    if (submission.state !== "SUBMITTED") {
      throw new HttpError(409, "CONFLICT", "The face check is only open while the submission is waiting", { state: submission.state });
    }
    const form = req.body instanceof FormData ? req.body : new FormData();
    const frames = form.getAll("frames").filter((f): f is File => f instanceof Blob);
    if (frames.length < FACE.minFrames || frames.length > FACE.maxFrames) {
      throw new HttpError(422, "FACE_CAPTURE_INVALID", `Send between ${FACE.minFrames} and ${FACE.maxFrames} camera frames`, { reason: "frame_count", field: "frames" });
    }
    const outcome: FaceOutcome = submission.face_plan === "match" ? "MATCH" : submission.face_plan === "review" ? "REVIEW" : "NO_MATCH";
    const median = outcome === "MATCH" ? 0.57 : outcome === "REVIEW" ? 0.36 : 0.14;
    submission.attempts.push({
      attempt_no: submission.attempts.length + 1, outcome, frames: frames.length, good_frames: frames.length,
      median_score: median, min_score: median - 0.03, yaw_span: 0.31, at: iso(),
    } satisfies FaceAttemptRecord);
    if (outcome === "MATCH" || outcome === "REVIEW") {
      const best = frames[Math.floor(frames.length / 2)];
      submission.documents.push({
        id: crypto.randomUUID(), doc_type: "FACE_CAPTURE", mime_type: best.type || "image/jpeg", size_bytes: best.size, uploaded_at: iso(),
        sha256: fakeDigest(`face:${submission.id}:${now()}`), name: "face-capture.jpg",
        data_url: best.size <= MAX_STORED_PREVIEW ? await readDataUrl(best) : null,
      });
      // Even a clear match waits in the admin queue: only an administrator verifies a seller.
      submission.state = "UNDER_REVIEW";
      this.setStatus(user.id, submission.state);
    } else if (this.counted(submission) >= FACE.maxAttempts) {
      submission.state = "REJECTED";
      submission.rejection_reason = `face check ${outcome}, median similarity ${median.toFixed(3)}`;
      submission.decided_at = iso();
      this.setStatus(user.id, "REJECTED");
    }
    this.persist();
    const view = this.sellerView(submission);
    return { outcome, attempts_left: view.face.attempts_left, submission: view };
  }

  private queue(req: TransportRequest, params: URLSearchParams) {
    this.admin(req);
    const limit = Math.min(100, Number(params.get("limit") ?? 25));
    const offset = Number(params.get("offset") ?? 0);
    const states = params.getAll("state");
    const wanted = new Set(states.length ? states : ["UNDER_REVIEW"]);
    const waiting = this.state.submissions
      .filter((s) => wanted.has(s.state))
      .sort((a, b) => Date.parse(a.submitted_at) - Date.parse(b.submitted_at));
    return {
      items: waiting.slice(offset, offset + limit).map((s) => ({ submission_id: s.id, user_id: s.user_id, state: s.state, submitted_at: s.submitted_at })),
      limit, offset,
    };
  }

  private kycTransition(req: TransportRequest, id: string, event: string, body: Record<string, unknown>) {
    const admin = this.admin(req);
    const submission = this.submission(id);
    const table: Record<string, [KycStatus, KycStatus]> = {
      approve: ["UNDER_REVIEW", "VERIFIED"],
      reject: ["UNDER_REVIEW", "REJECTED"],
      suspend: ["VERIFIED", "SUSPENDED"],
      reinstate: ["SUSPENDED", "VERIFIED"],
    };
    const [from, to] = table[event];
    if (submission.state !== from) throw new HttpError(409, "CONFLICT", `Cannot ${event} a submission in state ${submission.state}`, { state: submission.state, event });
    let reason: string | null = null;
    if (event === "reject") {
      reason = String(body.reason ?? "").trim();
      if (reason.length < 10 || reason.length > 500) throw validation("reason", "A rejection reason of 10 to 500 characters is required");
    }
    if (event === "suspend") {
      reason = String(body.reason_code ?? "");
      if (!/^[A-Z][A-Z0-9_]{2,39}$/.test(reason)) throw validation("reason_code", "reason_code must be an UPPER_SNAKE code");
    }
    submission.state = to;
    if (event === "approve" || event === "reject") {
      submission.decided_at = iso();
      submission.decided_by = admin.id;
    }
    if (event === "reject" || event === "suspend") submission.rejection_reason = reason;
    this.setStatus(submission.user_id, to);
    this.persist();
    return this.adminView(submission);
  }

  private documentUrl(req: TransportRequest, submissionId: string, documentId: string) {
    this.admin(req);
    const document = this.submission(submissionId).documents.find((d) => d.id === documentId);
    if (!document) throw new HttpError(404, "NOT_FOUND", "Document not found");
    return { url: document.data_url ?? placeholderDocument(document), expires_in: 60 };
  }
}

/** Bridge errors come back in the services' envelope; anything else means the bridge is unreachable. */
async function viaBridge<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (error) {
    if (error instanceof BridgeError) throw new HttpError(error.status, error.code, error.message);
    throw new HttpError(503, "PAYMENT_PROVIDER_UNAVAILABLE", "Can't reach Razorpay test mode; nothing was charged");
  }
}

function ok(status: number, body: unknown): TransportResponse {
  return { status, headers: {}, body };
}

function validation(field: string, message: string): HttpError {
  return new HttpError(422, "VALIDATION_ERROR", message, { field });
}

function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function mockSignature(providerOrderId: string, paymentId: string): string {
  return fakeDigest(`checkout:${providerOrderId}|${paymentId}`);
}

function fakeDigest(seed: string): string {
  let out = "";
  let hash = 0x811c9dc5;
  while (out.length < 64) {
    for (const char of seed + out.length) hash = Math.imul(hash ^ char.charCodeAt(0), 0x01000193) >>> 0;
    out += hash.toString(16).padStart(8, "0");
  }
  return out.slice(0, 64);
}

/** JPEG, PNG or WebP, by magic number (the server sniffs the same way). */
function isImage(b: Uint8Array): boolean {
  const jpeg = b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff;
  const png = b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47;
  const ascii = (from: number, to: number) => String.fromCharCode(...b.slice(from, to));
  return jpeg || png || (ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP");
}

/** Blob bytes, through FileReader where Blob.arrayBuffer is missing (older browsers, jsdom). */
function readBytes(blob: Blob): Promise<Uint8Array> {
  if (typeof blob.arrayBuffer === "function") return blob.arrayBuffer().then((buffer) => new Uint8Array(buffer));
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => resolve(new Uint8Array());
    reader.readAsArrayBuffer(blob);
  });
}

/** State saved before listing photos existed has auctions without an images list. */
function withImages(state: MockState): MockState {
  for (const auction of state.auctions) auction.images ??= [];
  return state;
}

function readDataUrl(file: Blob): Promise<string | null> {
  return new Promise((resolve) => {
    if (typeof FileReader === "undefined") return resolve(null);
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : null);
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(file);
  });
}

/** Seeded images have no bytes; the viewer gets a labelled synthetic portrait instead. */
function placeholderDocument(document: MockDocument): string {
  const label = document.doc_type === "AADHAAR_PHOTO" ? "Aadhaar photo" : "Live capture";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="600" viewBox="0 0 480 600">
<rect width="480" height="600" fill="#ecebf3"/><circle cx="240" cy="235" r="105" fill="#c9c7d9"/><path d="M70 600c10-130 90-200 170-200s160 70 170 200z" fill="#c9c7d9"/>
<rect x="0" y="520" width="480" height="80" fill="#1b1a2e" opacity=".82"/>
<text x="240" y="556" font-family="sans-serif" font-size="24" font-weight="700" text-anchor="middle" fill="#fff">${label}</text>
<text x="240" y="584" font-family="sans-serif" font-size="15" text-anchor="middle" fill="#cfcde0">Mock mode: synthetic, no real person</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
