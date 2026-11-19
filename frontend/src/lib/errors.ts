import type { ErrorEnvelope } from "./api/types";

/**
 * Every failure the UI shows is one of the codes in contracts/errors/ (bid taxonomy v1.0.0,
 * payment codes and common codes). The copy below explains the code to a person; the code itself is the server's.
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
const RETRYABLE = new Set(["AUCTION_STATE_UNAVAILABLE", "SERVICE_UNAVAILABLE", "PAYMENT_PROVIDER_UNAVAILABLE", "NETWORK_ERROR"]);

interface Copy {
  title: string;
  hint?: string;
}

export const ERROR_COPY: Record<string, Copy> = {
  EMAIL_NOT_VERIFIED: {
    title: "Email verification required",
    hint: "Please verify your email address before logging in. Check your inbox for the verification link.",
  },
  // Bid taxonomy v1.0.0
  SELLER_NOT_VERIFIED: {
    title: "Seller verification required",
    hint: "Verify your identity with your Aadhaar QR code before you list.",
  },
  ACCOUNT_SUSPENDED: { title: "Your account is suspended", hint: "Contact an administrator to review it." },
  SELF_BIDDING_FORBIDDEN: { title: "You can't bid on your own auction" },
  AUCTION_NOT_OPEN: { title: "This auction isn't taking bids" },
  AUCTION_CLOSED: { title: "The auction closed before your bid was sequenced" },
  BID_BELOW_INCREMENT: { title: "Your bid is below the minimum next bid" },
  INSUFFICIENT_FUNDS: { title: "The funds check failed", hint: "Please check your payment account balance." },
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
  INTERNAL_ERROR: {
    title: "Something went wrong on our side",
    hint: "An unexpected error occurred. Please try again shortly.",
  },
  SERVICE_UNAVAILABLE: {
    title: "Service temporarily unavailable",
    hint: "The backend service may be waking up or deploying. Please wait a few seconds and try again.",
  },
  // Auth and KYC service codes
  INVALID_CREDENTIALS: { title: "Email or password is incorrect" },
  EMAIL_ALREADY_REGISTERED: { title: "An account with this email already exists" },
  REFRESH_TOKEN_INVALID: { title: "Your session ended", hint: "Log in again to continue." },
  KYC_ALREADY_ACTIVE: { title: "You already have a verification in progress" },
  KYC_COOLDOWN: { title: "Verification temporarily unavailable", hint: "You can try again after the cooldown period." },
  AADHAAR_INVALID: { title: "We couldn't verify that Aadhaar file" },
  // Payment codes (contracts/errors/payment-error-codes.yaml)
  ORDER_NOT_PAYABLE: { title: "This order has nothing left to pay" },
  PAYMENT_SIGNATURE_INVALID: { title: "The payment could not be verified", hint: "Nothing was captured. Try paying again." },
  PAYMENT_PROVIDER_UNAVAILABLE: { title: "The payment provider is unavailable", hint: "Nothing was charged. Try again shortly." },
  PAYMENT_PROVIDER_ERROR: { title: "The payment provider refused the request", hint: "Please try another card or check your payment details." },
  SETTLEMENT_CONFLICT: { title: "This auction is already being settled" },
  // Client-side, never from the server
  NETWORK_ERROR: { title: "Can't reach the server", hint: "Check your connection and try again." },
};

function sanitizeMessage(msg: unknown): string {
  if (typeof msg !== "string") return "An unexpected error occurred.";
  const trimmed = msg.trim();
  // Strip or replace raw HTML error pages (e.g. 502/503 from Nginx or Render)
  if (trimmed.startsWith("<") || trimmed.includes("<html") || trimmed.includes("<!DOCTYPE")) {
    return "The service is temporarily unavailable or starting up. Please try again shortly.";
  }
  // Truncate overly verbose server dumps
  if (trimmed.length > 200) {
    return `${trimmed.slice(0, 197)}...`;
  }
  return trimmed;
}

export function describeError(error: unknown): Copy & { code: string; message: string } {
  if (error instanceof ApiError) {
    const cleanMessage = sanitizeMessage(error.message);
    const copy = ERROR_COPY[error.code] ?? {
      title: error.status >= 500 ? "Service temporarily unavailable" : cleanMessage,
      hint: error.status >= 500 ? "The backend may be warming up. Please try again shortly." : undefined,
    };
    return { ...copy, code: error.code, message: cleanMessage };
  }
  const rawMessage = error instanceof Error ? error.message : String(error);
  const cleanMessage = sanitizeMessage(rawMessage);
  return {
    title: "Something went wrong",
    code: "UNKNOWN",
    message: cleanMessage,
    hint: "Please check your connection and try again.",
  };
}

/** The `field` key the services put in VALIDATION_ERROR details, if any. */
export function errorField(error: unknown): string | null {
  if (error instanceof ApiError && typeof error.details?.field === "string") return error.details.field;
  return null;
}
