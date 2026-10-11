import { parse } from "yaml";
import raw from "../../../config/settlement-policy.yaml?raw";
import { parseMoney, type Cents } from "./money";

/**
 * The settlement numbers come from config/settlement-policy.yaml (ADR-0011)
 * at build time, so the UI never hard-codes a fee, a window or an anti-snipe rule.
 */
interface PolicyFile {
  convenience_fee: { fee_version: string; amount: string; currency: string; charged_to_losing_bidders: boolean };
  checkout?: { provider: string; payment_window_hours: number };
  protection_window: { days: number };
  anti_snipe: { guard_interval_seconds: number; extension_seconds: number; max_extensions: number };
}

export interface SettlementPolicy {
  feeVersion: string;
  feeCents: Cents;
  currency: string;
  chargedToLosingBidders: boolean;
  /** How long the winner has to pay in Checkout (ADR-0009). */
  paymentWindowHours: number;
  protectionDays: number;
  guardSeconds: number;
  extensionSeconds: number;
  maxExtensions: number;
}

export function readPolicy(text: string): SettlementPolicy {
  const file = parse(text) as PolicyFile;
  return {
    feeVersion: file.convenience_fee.fee_version,
    feeCents: parseMoney(file.convenience_fee.amount),
    currency: file.convenience_fee.currency,
    chargedToLosingBidders: file.convenience_fee.charged_to_losing_bidders,
    paymentWindowHours: file.checkout?.payment_window_hours ?? 48,
    protectionDays: file.protection_window.days,
    guardSeconds: file.anti_snipe.guard_interval_seconds,
    extensionSeconds: file.anti_snipe.extension_seconds,
    maxExtensions: file.anti_snipe.max_extensions,
  };
}

export const policy: SettlementPolicy = readPolicy(raw);

/** 120 -> "2 min"; anything not a whole minute stays in seconds. */
export function duration(seconds: number): string {
  const m = seconds / 60;
  return Number.isInteger(m) ? `${m} min` : `${seconds} s`;
}
