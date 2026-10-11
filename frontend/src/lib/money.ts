/**
 * Money is integer cents inside the frontend and a two-decimal string at every API boundary
 * ("1250.00"). Floats never hold an amount.
 */
export type Cents = number;

const MONEY = /^(0|[1-9]\d*)\.\d{2}$/;
const INPUT = /^\s*(\d{1,12})(?:\.(\d{0,2}))?\s*$/;

/** Parse a wire amount ("1250.00") into cents. Throws on anything else. */
export function parseMoney(value: string): Cents {
  if (!MONEY.test(value)) throw new Error(`Not a money string: ${value}`);
  const [whole, fraction] = value.split(".");
  return Number(whole) * 100 + Number(fraction);
}

/** Cents to the wire format ("1250.00"). */
export function toMoneyString(cents: Cents): string {
  if (!Number.isInteger(cents) || cents < 0) throw new Error(`Invalid cents: ${cents}`);
  const whole = Math.floor(cents / 100);
  const fraction = String(cents % 100).padStart(2, "0");
  return `${whole}.${fraction}`;
}

/** What a person typed ("1,250", "1250.5") into cents, or null when it is not an amount. */
export function parseMoneyInput(raw: string): Cents | null {
  const match = INPUT.exec(raw.replace(/,/g, ""));
  if (!match) return null;
  const fraction = (match[2] ?? "").padEnd(2, "0");
  return Number(match[1]) * 100 + Number(fraction);
}

const formatters = new Map<string, Intl.NumberFormat>();

/** Display form, e.g. "$1,250.00". The currency comes from the API, never assumed. */
export function formatMoney(cents: Cents, currency = "USD", opts: { compact?: boolean } = {}): string {
  const key = `${currency}:${opts.compact ? 1 : 0}`;
  let fmt = formatters.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: opts.compact ? 0 : 2,
      maximumFractionDigits: 2,
    });
    formatters.set(key, fmt);
  }
  // Display only: an integer number of cents divided by 100 prints exactly at two decimals.
  return fmt.format(cents / 100);
}
