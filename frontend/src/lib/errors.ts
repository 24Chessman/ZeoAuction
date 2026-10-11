import type { ErrorEnvelope } from "./api/types";

/**
 * Every failure the UI shows is one of the codes in contracts/errors/ (bid taxonomy v1.0.0 +
 * common codes). The copy below explains the code to a person; the code itself is the server's.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown> | null;
  readonly requestId: string | null;

  constructor(status: number, envelope: ErrorEnvelope) {
    super(envelope.message);
    this.name = "ApiError";
    this.code = envelope.code;
    this.status = status;
    this.details = envelope.details ?? null;
    this.requestId = envelope.request_id ?? null;
  }

  get retryable(): boolean {
    return RETRYABLE.has(this.code);
  }
}

/** contracts/errors/bid-rejection-codes.yaml `retryable: true`, plus the common 503. */
const RETRYABLE = new Set(["AUCTION_STATE_UNAVAILABLE", "SERVICE_UNAVAILABLE", "NETWORK_ERROR"]);

interface Copy {
  title: string;
  hint?: string;
}

export const ERROR_COPY: Record<string, Copy> = {
  // Bid taxonomy v1.0.0
  SELLER_NOT_VERIFIED: {
    title: "Seller verification required",
    hint: "An administrator has to approve your identity documents before you can list.",
  },
  ACCOUNT_SUSPENDED: { title: "Your account is suspended", hint: "Contact an administrator to review it." },
  SELF_BIDDING_FORBIDDEN: { title: "You can't bid on your own auction" },
  AUCTION_NOT_OPEN: { title: "This auction isn't taking bids" },
  AUCTION_CLOSED: { title: "The auction closed before your bid was sequenced" },
  BID_BELOW_INCREMENT: { title: "Your bid is below the minimum next bid" },
  INSUFFICIENT_FUNDS: { title: "The funds check failed", hint: "Test mode: no real funds are checked or held." },
  AUCTION_STATE_UNAVAILABLE: {
    title: "Bidding is briefly unavailable",
    hint: "Nothing was placed. Retrying sends the same bid with the same key, so it can't be placed twice.",
  },
  // Common codes
  BAD_REQUEST: { title: "The request was malformed" },
  UNAUTHENTICATED: { title: "Please log in again" },
  FORBIDDEN: { title: "You don't have access to this" },
  NOT_FOUND: { title: "Not found" },
  CONFLICT: { title: "That change conflicts with the current state" },
  VALIDATION_ERROR: { title: "Please check the highlighted fields" },
  RATE_LIMITED: { title: "Too many requests", hint: "Wait a moment and try again." },
  INTERNAL_ERROR: { title: "Something went wrong on our side" },
  SERVICE_UNAVAILABLE: { title: "A service is temporarily unavailable", hint: "Nothing changed. Try again shortly." },
  // Auth and KYC service codes
  INVALID_CREDENTIALS: { title: "Email or password is incorrect" },
  EMAIL_ALREADY_REGISTERED: { title: "An account with this email already exists" },
  REFRESH_TOKEN_INVALID: { title: "Your session ended", hint: "Log in again to continue." },
  KYC_ALREADY_ACTIVE: { title: "You already have a verification in progress" },
  // Client-side, never from the server
  NETWORK_ERROR: { title: "Can't reach the server", hint: "Check your connection and try again." },
};

export function describeError(error: unknown): Copy & { code: string; message: string } {
  if (error instanceof ApiError) {
    const copy = ERROR_COPY[error.code] ?? { title: error.message };
    return { ...copy, code: error.code, message: error.message };
  }
  const message = error instanceof Error ? error.message : String(error);
  return { title: "Something went wrong", code: "UNKNOWN", message };
}

/** The `field` key the services put in VALIDATION_ERROR details, if any. */
export function errorField(error: unknown): string | null {
  if (error instanceof ApiError && typeof error.details?.field === "string") return error.details.field;
  return null;
}
