// Aadhaar Secure QR, read and verified in the browser for mock mode. A port of
// services/kyc/app/domain/aadhaar.py: decimal text -> bytes -> GZip -> UIDAI's RSA-SHA256
// signature over all but the last 256 bytes -> the 0xFF-separated fields (V2 and the 2019
// layout). The mock keeps only the summary the real service stores; nothing here logs.

const SIGNATURE_BYTES = 256;
const HASH_BYTES = 32;
const DELIMITER = 0xff;
const MAX_QR_DIGITS = 7089;
const MAX_PAYLOAD_BYTES = 64 * 1024;
const ADULT_AGE = 18;
const CLOCK_SKEW_MS = 5 * 60_000;
const IST_OFFSET_MS = (5 * 60 + 30) * 60_000;

type Bytes = Uint8Array<ArrayBuffer>;

/** UIDAI's offline e-KYC key 06 (valid to 2029), the SubjectPublicKeyInfo of
 * services/kyc/app/certs/uidai_offline_publickey_2026.cer. */
const UIDAI_SPKI =
  "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAh1+zYnvbcEm0Yz73s5u42odpUJMr9wv5bVw7sOE5nFNbrB+U++5I0f8cL2HoHnJOkwvLZzrD0jG/vxAKi6vii/gjEzUEgrkdIHxMP3D6GJs0MSQHiEXvIGOwPIH3BLtBOc3m28NVNT6Q9iq0gUwuxnlhV38UdNhCllqNYhWmAMPJkImgaKrRZvY2pWNs6gd+PlAF/9SO69x3+1meA8kPk2ZvQanZlx9tfaExeOe9or3NQiKy2+UbtXrpcoAfYbbWi1OUzXi5bJdhbGp239c1fX6UKyUM5IUMY+m3I7wu2WQ7lmeO2n/vwzQz/PKHXPWYu3bydWMLdCi07vOQBqzCKwIDAQAB";

// Text fields between the indicator and the photo, in order (first layout and V2 alike).
const FIELDS = ["reference_id", "name", "dob", "gender", "careof", "district", "landmark", "house",
  "location", "pincode", "postoffice", "state", "street", "subdistrict", "vtc"] as const;
type Field = (typeof FIELDS)[number];
const GENDERS: Record<string, "M" | "F" | "T"> = { M: "M", F: "F", T: "T", MALE: "M", FEMALE: "F", TRANSGENDER: "T" };
const JP2_MAGIC = [[0x00, 0x00, 0x00, 0x0c, 0x6a, 0x50, 0x20, 0x20, 0x0d, 0x0a, 0x87, 0x0a], [0xff, 0x4f, 0xff, 0x51], [0xff, 0xd8, 0xff]];

export class AadhaarInvalid extends Error {
  constructor(readonly reason: string, message: string) {
    super(message);
  }

  get field(): string {
    return this.reason === "mobile_mismatch" ? "mobile" : "qr_image";
  }
}

export interface SecureQr {
  version: number;
  reference_last4: string;
  generated_at: Date;
  name: string;
  year_of_birth: number;
  gender: "M" | "F" | "T";
  state: string | null;
  pincode: string | null;
  mobile_verified: boolean | null;
}

export interface ReadOptions {
  now: Date;
  mobile?: string;
  /** SubjectPublicKeyInfo (DER) of the keys to accept; UIDAI's by default. */
  trustedKeys?: Bytes[];
}

let uidaiKey: Promise<CryptoKey> | null = null;

function importKey(spki: Bytes): Promise<CryptoKey> {
  return crypto.subtle.importKey("spki", spki, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
}

function base64Bytes(text: string): Bytes {
  return Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
}

/** The QR's decimal number as big-endian bytes. */
export function decimalToBytes(text: string): Bytes {
  let hex = BigInt(text).toString(16);
  if (hex.length % 2) hex = `0${hex}`;
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

/** GZip -> bytes, stopping once past the limit so a crafted stream can't inflate without end. */
async function gunzip(data: Bytes): Promise<Bytes> {
  const stream = new DecompressionStream("gzip");
  const writer = stream.writable.getWriter();
  writer.write(data).catch(() => undefined);
  writer.close().catch(() => undefined);
  const reader = stream.readable.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    size += value.length;
    if (size > MAX_PAYLOAD_BYTES) {
      await reader.cancel().catch(() => undefined);
      throw new AadhaarInvalid("malformed_qr", "The QR code holds too much data");
    }
  }
  const out = new Uint8Array(size);
  let at = 0;
  for (const chunk of chunks) {
    out.set(chunk, at);
    at += chunk.length;
  }
  return out;
}

/** QR text -> the signed payload. */
export async function inflate(text: string): Promise<Bytes> {
  const digits = text.trim();
  if (!/^\d+$/.test(digits)) {
    // The pre-2019 QR held plain, unsigned XML (<PrintLetterBarcodeData .../>).
    throw new AadhaarInvalid("not_secure_qr", "This is not an Aadhaar Secure QR code; use a recent Aadhaar");
  }
  if (digits.length > MAX_QR_DIGITS) throw new AadhaarInvalid("malformed_qr", "The QR code could not be read");
  try {
    return await gunzip(decimalToBytes(digits));
  } catch (error) {
    if (error instanceof AadhaarInvalid) throw error;
    throw new AadhaarInvalid("not_secure_qr", "This is not an Aadhaar Secure QR code");
  }
}

async function verifySignature(payload: Bytes, trusted: Bytes[] | undefined): Promise<void> {
  if (payload.length <= SIGNATURE_BYTES) throw new AadhaarInvalid("malformed_qr", "The QR code is incomplete");
  const signed = payload.slice(0, -SIGNATURE_BYTES);
  const signature = payload.slice(-SIGNATURE_BYTES);
  const keys = trusted ? trusted.map(importKey) : [(uidaiKey ??= importKey(base64Bytes(UIDAI_SPKI)))];
  for (const key of keys) {
    if (await crypto.subtle.verify("RSASSA-PKCS1-v1_5", await key, signature, signed)) return;
  }
  throw new AadhaarInvalid("signature_invalid", "The QR code is not signed by UIDAI");
}

function decodeText(raw: Uint8Array): string {
  let value: string;
  try {
    value = new TextDecoder("utf-8", { fatal: true }).decode(raw);
  } catch {
    value = new TextDecoder("latin1").decode(raw);
  }
  return value.split(/\s+/).filter(Boolean).join(" ");
}

interface Layout {
  version: number;
  fields: Record<Field, string>;
  mobileLast4: string | null;
  photo: Uint8Array;
  mobileHash: Uint8Array | null;
}

/** Cut the signed bytes into fields, photo and hashes. Only the leading delimiters count: the
 * photo and hashes are binary and may contain 0xFF. */
export function splitPayload(signed: Uint8Array): Layout {
  const first = signed.indexOf(DELIMITER);
  const marker = first > 0 ? /^V(\d)$/.exec(new TextDecoder("latin1").decode(signed.slice(0, first))) : null;
  const version = marker ? Number(marker[1]) : 1;
  const count = FIELDS.length + 1 + (marker ? 2 : 0); // + indicator, + marker and mobile
  const parts: Uint8Array[] = [];
  let start = 0;
  for (let i = 0; i < count; i += 1) {
    const end = signed.indexOf(DELIMITER, start);
    if (end < 0) throw new AadhaarInvalid("malformed_qr", "The QR code has missing fields");
    parts.push(signed.slice(start, end));
    start = end + 1;
  }
  const rest = signed.slice(start);
  if (marker) parts.shift();
  const indicatorText = decodeText(parts[0]);
  const indicator = /^\d+$/.test(indicatorText) ? Number(indicatorText) : -1;
  if (![0, 1, 2, 3].includes(indicator)) throw new AadhaarInvalid("malformed_qr", "The QR code has missing fields");
  const fields = Object.fromEntries(FIELDS.map((name, i) => [name, decodeText(parts[1 + i])])) as Record<Field, string>;

  if (marker) {
    return { version, fields, mobileLast4: decodeText(parts[parts.length - 1]) || null, photo: rest, mobileHash: null };
  }
  const hashesLength = HASH_BYTES * ((indicator & 1) + ((indicator >> 1) & 1));
  if (rest.length < hashesLength) throw new AadhaarInvalid("no_photo", "The QR code has no photo");
  return {
    version, fields, mobileLast4: null,
    photo: rest.slice(0, rest.length - hashesLength),
    // The mobile hash comes last, after the email's.
    mobileHash: indicator & 2 ? rest.slice(rest.length - HASH_BYTES) : null,
  };
}

/** `{last 4 digits}{YYYYMMDDHHMMSS}{mmm}`, the timestamp in IST -> (last4, UTC time). */
export function parseReferenceId(referenceId: string): [string, Date] {
  const match = /^(\d{4})(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{3})?$/.exec(referenceId);
  if (!match) throw new AadhaarInvalid("malformed_qr", "The QR code has no valid reference id");
  const [, last4, y, mo, d, h, mi, s, ms] = match;
  const utc = Date.UTC(+y, +mo - 1, +d, +h, +mi, +s, +(ms ?? 0)) - IST_OFFSET_MS;
  const check = new Date(utc + IST_OFFSET_MS);
  if (check.getUTCMonth() !== +mo - 1 || check.getUTCDate() !== +d || +h > 23 || +mi > 59 || +s > 59) {
    throw new AadhaarInvalid("malformed_qr", "The QR code has no valid reference id");
  }
  return [last4, new Date(utc)];
}

/** `DD-MM-YYYY` (the usual form), `YYYY-MM-DD`, `DD/MM/YYYY` or a bare year. */
export function parseBirth(dob: string): [Date | null, number] {
  const value = dob.trim();
  if (/^\d{4}$/.test(value)) return [null, Number(value)];
  const parts = /^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/.exec(value) ?? /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(value);
  if (parts) {
    const [day, month, year] = parts[3].length === 4 ? [+parts[1], +parts[2], +parts[3]] : [+parts[3], +parts[2], +parts[1]];
    const born = new Date(Date.UTC(year, month - 1, day));
    if (born.getUTCMonth() === month - 1 && born.getUTCDate() === day) return [born, year];
  }
  throw new AadhaarInvalid("malformed_qr", "The QR code has no readable date of birth");
}

/** With only a year, assume 31 December, so nobody under 18 passes. `today` is a UTC-midnight date. */
function isAdult(born: Date | null, year: number, today: Date): boolean {
  const [y, m, d] = born ? [born.getUTCFullYear(), born.getUTCMonth(), born.getUTCDate()] : [year, 11, 31];
  let comingOfAge = new Date(Date.UTC(y + ADULT_AGE, m, d));
  if (comingOfAge.getUTCMonth() !== m) comingOfAge = new Date(Date.UTC(y + ADULT_AGE, 2, 1)); // 29 February
  return comingOfAge.getTime() <= today.getTime();
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** UIDAI's hash of a mobile number in the first layout: SHA-256, as hex, applied as many times as
 * the last Aadhaar digit (once when it is 0 or 1). */
export async function contactHash(value: string, lastDigit: number): Promise<string> {
  let digest = value;
  for (let i = 0; i < Math.max(1, lastDigit); i += 1) digest = await sha256Hex(digest);
  return digest;
}

function normaliseMobile(mobile: string): string {
  let digits = mobile.replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("91")) digits = digits.slice(2);
  if (digits.length !== 10) throw new AadhaarInvalid("mobile_mismatch", "Enter the 10-digit mobile number");
  return digits;
}

async function checkMobile(layout: Layout, mobile: string, lastDigit: number): Promise<boolean> {
  const digits = normaliseMobile(mobile);
  const hex = (b: Uint8Array) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  const matches = layout.version >= 2
    ? layout.mobileLast4 !== null && digits.slice(-4) === layout.mobileLast4.slice(-4)
    : layout.mobileHash !== null && (await contactHash(digits, lastDigit)) === hex(layout.mobileHash);
  if (!matches) throw new AadhaarInvalid("mobile_mismatch", "This mobile number is not the one linked to the Aadhaar");
  return true;
}

/** Verify and read one QR's text; throws AadhaarInvalid when a check fails. */
export async function readPayload(text: string, options: ReadOptions): Promise<SecureQr> {
  const payload = await inflate(text);
  await verifySignature(payload, options.trustedKeys);
  const layout = splitPayload(payload.slice(0, -SIGNATURE_BYTES));
  const { fields } = layout;
  const [last4, generatedAt] = parseReferenceId(fields.reference_id);
  if (generatedAt.getTime() > options.now.getTime() + CLOCK_SKEW_MS) {
    throw new AadhaarInvalid("from_future", "The QR code's timestamp is in the future");
  }
  if (!fields.name) throw new AadhaarInvalid("malformed_qr", "The QR code has no holder name");
  const gender = GENDERS[fields.gender.toUpperCase()];
  if (!gender) throw new AadhaarInvalid("malformed_qr", "The QR code has no valid gender");
  const [born, year] = parseBirth(fields.dob);
  const ist = new Date(options.now.getTime() + IST_OFFSET_MS);
  if (!isAdult(born, year, new Date(Date.UTC(ist.getUTCFullYear(), ist.getUTCMonth(), ist.getUTCDate())))) {
    throw new AadhaarInvalid("underage", "Sellers must be 18 or older");
  }
  if (!JP2_MAGIC.some((magic) => magic.every((b, i) => layout.photo[i] === b))) {
    throw new AadhaarInvalid("no_photo", "The QR code has no readable photo");
  }
  const mobileVerified = options.mobile ? await checkMobile(layout, options.mobile, Number(last4[3])) : null;
  return {
    version: layout.version, reference_last4: last4, generated_at: generatedAt, name: fields.name,
    year_of_birth: year, gender, state: fields.state || null,
    pincode: /^\d{6}$/.test(fields.pincode) ? fields.pincode : null, mobile_verified: mobileVerified,
  };
}

/** Pick the Secure QR among the codes found in the photo and read it. With several, the first that
 * verifies wins; otherwise the first real error is reported. */
export async function readSecureQr(texts: string[], options: ReadOptions): Promise<SecureQr> {
  if (texts.length === 0) {
    throw new AadhaarInvalid("no_qr", "No QR code was found; photograph it flat, in focus and filling the frame");
  }
  let firstError: AadhaarInvalid | null = null;
  for (const text of texts) {
    try {
      return await readPayload(text, options);
    } catch (error) {
      if (!(error instanceof AadhaarInvalid)) throw error;
      // A real Secure QR's error says more than a stray code's "not a Secure QR".
      if (firstError === null || firstError.reason === "not_secure_qr") firstError = error;
    }
  }
  throw firstError as AadhaarInvalid;
}
