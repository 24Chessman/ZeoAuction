import type { AadhaarSummary, Auction, DocType, FaceAttemptRecord, KycStatus, LedgerEntry, Order, Role } from "../api/types";
import { toMoneyString } from "../money";
import { policy } from "../policy";

/**
 * Synthetic demo data for mock mode. The five accounts and the first two auctions mirror
 * infra/postgres/seed/dev-seed.sql (same ids, same password); the rest is demo catalogue.
 */
export const DEV_PASSWORD = "zeo-dev-password";

export interface MockUser {
  id: string;
  email: string;
  password: string;
  display_name: string;
  role: Role;
  kyc_status: KycStatus;
  suspended: boolean;
  token_version: number;
  created_at: string;
}

export interface MockBid {
  bid_id: string;
  auction_id: string;
  bidder_id: string;
  amount: number; // cents
  server_seq: number;
  accepted_at: string;
}

export interface MockDocument {
  id: string;
  doc_type: DocType;
  mime_type: string;
  size_bytes: number;
  uploaded_at: string;
  sha256: string;
  name: string;
  data_url: string | null;
}

/** How the simulated face check answers for this submission (set from the QR file name). */
export type MockFacePlan = "match" | "review" | "no_match";

export interface MockSubmission {
  id: string;
  user_id: string;
  state: KycStatus;
  rejection_reason: string | null;
  submitted_at: string;
  decided_at: string | null;
  decided_by: string | null;
  documents: MockDocument[];
  aadhaar: (AadhaarSummary & { pincode: string | null }) | null;
  attempts: FaceAttemptRecord[];
  face_plan: MockFacePlan;
}

/** An order plus the provider order its Checkout pays (mock adapter, ADR-0009). */
export interface MockOrder extends Order {
  provider_order_id: string | null;
  /** Escrow ledger rows, appended when the payment is captured. */
  ledger?: LedgerEntry[];
}

export interface MockState {
  version: 4;
  orders: MockOrder[];
  users: MockUser[];
  auctions: Auction[];
  bids: MockBid[];
  submissions: MockSubmission[];
  refresh: Record<string, string>;
  idempotency: Record<string, { status: number; body: unknown }>;
}

export const ids = {
  admin: "00000000-0000-4000-8000-000000000001",
  seller: "00000000-0000-4000-8000-000000000002",
  unverified: "00000000-0000-4000-8000-000000000003",
  buyer1: "00000000-0000-4000-8000-000000000004",
  buyer2: "00000000-0000-4000-8000-000000000005",
  pending: "00000000-0000-4000-8000-000000000006",
  bots: ["00000000-0000-4000-8000-0000000000b1", "00000000-0000-4000-8000-0000000000b2", "00000000-0000-4000-8000-0000000000b3"],
};

function user(id: string, email: string, name: string, role: Role, kyc: KycStatus, created: string): MockUser {
  return { id, email, password: DEV_PASSWORD, display_name: name, role, kyc_status: kyc, suspended: false, token_version: 1, created_at: created };
}

function iso(ms: number): string {
  return new Date(ms).toISOString();
}

interface CatalogueItem {
  id: string;
  title: string;
  description: string;
  category: string;
  start: number;
  reserve: number | null;
  opensIn: number | null; // minutes from now; null = draft
  closesIn: number | null;
  state: Auction["state"];
  bids?: number[];
  /** Who placed the last bid; by default the bidders rotate buyer2, bot1, bot2, bot3. */
  winner?: string;
}

const MIN = 60_000;

const catalogue: CatalogueItem[] = [
  {
    id: "00000000-0000-4000-8000-000000000201",
    title: "Vintage film camera",
    description: "Working 35mm rangefinder, synthetic demo listing. Shutter speeds tested, light seals replaced, original leather case included.",
    category: "cameras", start: 800_000, reserve: 1_200_000, opensIn: -60, closesIn: 2 * 24 * 60, state: "OPEN",
    bids: [800_000, 810_000, 850_000],
  },
  {
    id: "00000000-0000-4000-8000-000000000202",
    title: "Mechanical keyboard",
    description: "Draft listing, not yet published.",
    category: "electronics", start: 300_000, reserve: null, opensIn: null, closesIn: null, state: "DRAFT",
  },
  {
    id: "00000000-0000-4000-8000-000000000203",
    title: "Mid-century walnut lounge chair",
    description: "Synthetic demo listing. Solid walnut frame with re-upholstered wool cushions. Light patina on the arms, structurally sound.",
    category: "furniture", start: 3_500_000, reserve: 4_500_000, opensIn: -120, closesIn: 9, state: "OPEN",
    bids: [3_500_000, 3_600_000, 3_700_000, 3_800_000],
  },
  {
    id: "00000000-0000-4000-8000-000000000204",
    title: "Automatic dive watch, 200 m",
    description: "Synthetic demo listing. Stainless case, unidirectional bezel, serviced last year. Box and papers.",
    category: "watches", start: 9_500_000, reserve: null, opensIn: -300, closesIn: 95, state: "OPEN",
    bids: [9_500_000, 9_600_000, 9_800_000],
  },
  {
    id: "00000000-0000-4000-8000-000000000205",
    title: "First-edition science fiction novel",
    description: "Synthetic demo listing. Hardcover with dust jacket, minor shelf wear. Protected in a mylar sleeve.",
    category: "books", start: 600_000, reserve: 700_000, opensIn: -30, closesIn: 26 * 60, state: "OPEN",
    bids: [600_000],
  },
  {
    id: "00000000-0000-4000-8000-000000000206",
    title: "Analog synthesizer, 37 keys",
    description: "Synthetic demo listing. Fully analog signal path, all keys and knobs verified. Ships in original box.",
    category: "music", start: 4_800_000, reserve: 5_500_000, opensIn: 45, closesIn: 3 * 24 * 60, state: "SCHEDULED",
  },
  {
    id: "00000000-0000-4000-8000-000000000207",
    title: "Hand-thrown stoneware tea set",
    description: "Synthetic demo listing. Teapot and four cups, ash glaze. Each piece signed on the base.",
    category: "art", start: 500_000, reserve: null, opensIn: -3 * 24 * 60, closesIn: -60, state: "CLOSED",
    bids: [500_000, 550_000, 600_000, 650_000, 700_000],
  },
  {
    id: "00000000-0000-4000-8000-000000000208",
    title: "Sterling silver pendant necklace",
    description: "Synthetic demo listing. Handmade 925 silver pendant on an 18-inch chain, hallmarked. Comes in a gift pouch.",
    category: "jewelry", start: 250_000, reserve: null, opensIn: -2 * 24 * 60, closesIn: -30, state: "CLOSED",
    bids: [250_000, 260_000, 280_000, 300_000], winner: ids.buyer1,
  },
];

export function seedState(now = Date.now()): MockState {
  const created = iso(now - 30 * 24 * 60 * MIN);
  const users: MockUser[] = [
    user(ids.admin, "admin@zeo.local", "Dev Admin", "ADMIN", "NOT_SUBMITTED", created),
    user(ids.seller, "seller@zeo.local", "Verified Seller", "USER", "VERIFIED", created),
    user(ids.unverified, "unverified@zeo.local", "Unverified Seller", "USER", "NOT_SUBMITTED", created),
    user(ids.buyer1, "buyer1@zeo.local", "Buyer One", "USER", "NOT_SUBMITTED", created),
    user(ids.buyer2, "buyer2@zeo.local", "Buyer Two", "USER", "NOT_SUBMITTED", created),
    user(ids.pending, "pending@zeo.local", "Pending Seller", "USER", "UNDER_REVIEW", created),
    ...ids.bots.map((id, i) => user(id, `bot${i + 1}@zeo.local`, `Simulated bidder ${i + 1}`, "USER", "NOT_SUBMITTED", created)),
  ];

  const auctions: Auction[] = [];
  const bids: MockBid[] = [];
  for (const item of catalogue) {
    const opens = item.opensIn === null ? null : now + item.opensIn * MIN;
    const closes = item.closesIn === null ? null : now + item.closesIn * MIN;
    let seq = 0;
    const bidders = [ids.buyer2, ...ids.bots];
    let winner: string | null = null;
    for (const [index, amount] of (item.bids ?? []).entries()) {
      seq += 1;
      const bid: MockBid = {
        bid_id: crypto.randomUUID(),
        auction_id: item.id,
        bidder_id: item.winner && index === item.bids!.length - 1 ? item.winner : bidders[index % bidders.length],
        amount,
        server_seq: seq,
        accepted_at: iso((opens ?? now) + (index + 1) * 7 * MIN),
      };
      bids.push(bid);
      winner = bid.bid_id;
    }
    auctions.push({
      auction_id: item.id,
      seller_id: ids.seller,
      title: item.title,
      description: item.description,
      category: item.category,
      starting_price: toMoneyString(item.start),
      reserve_price: item.reserve === null ? null : toMoneyString(item.reserve),
      currency: policy.currency,
      state: item.state,
      opens_at: opens === null ? null : iso(opens),
      closes_at: closes === null ? null : iso(closes),
      original_closes_at: closes === null ? null : iso(closes),
      extension_count: 0,
      max_extensions: policy.maxExtensions,
      guard_interval_seconds: policy.guardSeconds,
      extension_seconds: policy.extensionSeconds,
      winning_bid_id: item.state === "CLOSED" ? winner : null,
      version: 1,
    });
  }

  // Synthetic Aadhaar summaries: invented names, never a real person's data.
  const aadhaar = (name: string, at: number, last4: string) => ({
    holder_name: name, year_of_birth: 1994, gender: "M" as const, state: "Karnataka", pincode: "560001",
    reference_last4: last4, qr_generated_at: iso(at - 400 * 24 * 60 * MIN), mobile_verified: true,
  });
  const attempt = (outcome: FaceAttemptRecord["outcome"], median: number, at: number): FaceAttemptRecord => ({
    attempt_no: 1, outcome, frames: 6, good_frames: 6, median_score: median, min_score: median - 0.04, yaw_span: 0.34, at: iso(at),
  });
  const image = (docType: DocType, at: number, name: string): MockDocument => ({
    id: crypto.randomUUID(), doc_type: docType, mime_type: "image/jpeg", size_bytes: docType === "AADHAAR_PHOTO" ? 9_412 : 64_208,
    uploaded_at: iso(at), sha256: fakeSha(name), name, data_url: null,
  });
  const verifiedAt = now - 20 * 24 * 60 * MIN;
  const referredAt = now - 3 * 60 * MIN;
  const submissions: MockSubmission[] = [
    {
      id: "00000000-0000-4000-8000-000000000102", user_id: ids.seller, state: "VERIFIED", rejection_reason: null,
      submitted_at: iso(verifiedAt), decided_at: iso(verifiedAt + 2 * MIN), decided_by: null,
      documents: [image("AADHAAR_PHOTO", verifiedAt, "aadhaar-photo.jpg"), image("FACE_CAPTURE", verifiedAt + 2 * MIN, "face-capture.jpg")],
      aadhaar: aadhaar("Verified Seller", verifiedAt, "4417"), attempts: [attempt("MATCH", 0.58, verifiedAt + 2 * MIN)], face_plan: "match",
    },
    {
      // The face check was borderline, so it waits in the admin queue.
      id: "00000000-0000-4000-8000-000000000106", user_id: ids.pending, state: "UNDER_REVIEW", rejection_reason: null,
      submitted_at: iso(referredAt), decided_at: null, decided_by: null,
      documents: [image("AADHAAR_PHOTO", referredAt, "aadhaar-photo.jpg"), image("FACE_CAPTURE", referredAt + 3 * MIN, "face-capture.jpg")],
      aadhaar: aadhaar("Pending Seller", referredAt, "9083"), attempts: [attempt("REVIEW", 0.36, referredAt + 3 * MIN)], face_plan: "review",
    },
  ];

  return { version: 4, users, auctions, bids, orders: [], submissions, refresh: {}, idempotency: {} };
}

/** A stable 64-hex stand-in for a seeded image's SHA-256. */
function fakeSha(seed: string): string {
  let out = "";
  let hash = 0x811c9dc5;
  while (out.length < 64) {
    for (const char of seed + out.length) hash = Math.imul(hash ^ char.charCodeAt(0), 0x01000193) >>> 0;
    out += hash.toString(16).padStart(8, "0");
  }
  return out.slice(0, 64);
}
