import type { Auction, DocType, KycStatus, Role } from "../api/types";
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

export interface MockSubmission {
  id: string;
  user_id: string;
  state: KycStatus;
  rejection_reason: string | null;
  submitted_at: string;
  decided_at: string | null;
  decided_by: string | null;
  documents: MockDocument[];
}

export interface MockState {
  version: 1;
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
}

const MIN = 60_000;

const catalogue: CatalogueItem[] = [
  {
    id: "00000000-0000-4000-8000-000000000201",
    title: "Vintage film camera",
    description: "Working 35mm rangefinder, synthetic demo listing. Shutter speeds tested, light seals replaced, original leather case included.",
    category: "cameras", start: 10_000, reserve: 15_000, opensIn: -60, closesIn: 2 * 24 * 60, state: "OPEN",
    bids: [10_000, 10_100, 10_500],
  },
  {
    id: "00000000-0000-4000-8000-000000000202",
    title: "Mechanical keyboard",
    description: "Draft listing, not yet published.",
    category: "electronics", start: 4_000, reserve: null, opensIn: null, closesIn: null, state: "DRAFT",
  },
  {
    id: "00000000-0000-4000-8000-000000000203",
    title: "Mid-century walnut lounge chair",
    description: "Synthetic demo listing. Solid walnut frame with re-upholstered wool cushions. Light patina on the arms, structurally sound.",
    category: "furniture", start: 45_000, reserve: 60_000, opensIn: -120, closesIn: 9, state: "OPEN",
    bids: [45_000, 46_000, 47_500, 48_000],
  },
  {
    id: "00000000-0000-4000-8000-000000000204",
    title: "Automatic dive watch, 200 m",
    description: "Synthetic demo listing. Stainless case, unidirectional bezel, serviced last year. Box and papers.",
    category: "watches", start: 120_000, reserve: null, opensIn: -300, closesIn: 95, state: "OPEN",
    bids: [120_000, 121_000, 123_500],
  },
  {
    id: "00000000-0000-4000-8000-000000000205",
    title: "First-edition science fiction novel",
    description: "Synthetic demo listing. Hardcover with dust jacket, minor shelf wear. Protected in a mylar sleeve.",
    category: "books", start: 8_000, reserve: 9_000, opensIn: -30, closesIn: 26 * 60, state: "OPEN",
    bids: [8_000],
  },
  {
    id: "00000000-0000-4000-8000-000000000206",
    title: "Analog synthesizer, 37 keys",
    description: "Synthetic demo listing. Fully analog signal path, all keys and knobs verified. Ships in original box.",
    category: "music", start: 60_000, reserve: 70_000, opensIn: 45, closesIn: 3 * 24 * 60, state: "SCHEDULED",
  },
  {
    id: "00000000-0000-4000-8000-000000000207",
    title: "Hand-thrown stoneware tea set",
    description: "Synthetic demo listing. Teapot and four cups, ash glaze. Each piece signed on the base.",
    category: "art", start: 6_500, reserve: null, opensIn: -3 * 24 * 60, closesIn: -60, state: "CLOSED",
    bids: [6_500, 7_000, 7_500, 8_000, 9_000],
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
    user(ids.pending, "pending@zeo.local", "Pending Seller", "USER", "SUBMITTED", created),
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
        bidder_id: bidders[index % bidders.length],
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

  const submissions: MockSubmission[] = [
    {
      id: "00000000-0000-4000-8000-000000000102", user_id: ids.seller, state: "VERIFIED", rejection_reason: null,
      submitted_at: iso(now - 20 * 24 * 60 * MIN), decided_at: iso(now - 19 * 24 * 60 * MIN), decided_by: ids.admin,
      documents: [],
    },
    {
      id: "00000000-0000-4000-8000-000000000106", user_id: ids.pending, state: "SUBMITTED", rejection_reason: null,
      submitted_at: iso(now - 3 * 60 * MIN), decided_at: null, decided_by: null,
      documents: [
        { id: crypto.randomUUID(), doc_type: "GOVERNMENT_ID", mime_type: "image/png", size_bytes: 482_113, uploaded_at: iso(now - 3 * 60 * MIN), sha256: "9f2c4e1a7b3d8c6e5f0a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4f5a6", name: "passport.png", data_url: null },
        { id: crypto.randomUUID(), doc_type: "PROOF_OF_ADDRESS", mime_type: "application/pdf", size_bytes: 1_204_331, uploaded_at: iso(now - 3 * 60 * MIN), sha256: "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f809", name: "utility-bill.pdf", data_url: null },
      ],
    },
  ];

  return { version: 1, users, auctions, bids, submissions, refresh: {}, idempotency: {} };
}
