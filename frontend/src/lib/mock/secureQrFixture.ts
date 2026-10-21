// Test helper: a synthetic Aadhaar Secure QR (V2 layout), signed with a key made here, the
// browser twin of services/kyc/scripts/synthetic_qr.py. Accepted only when its key is trusted.

export interface FixtureHolder {
  name?: string;
  dob?: string;
  gender?: string;
  state?: string;
  pincode?: string;
  aadhaarLast4?: string;
  /** IST, YYYYMMDDHHMMSS. */
  generated?: string;
  mobileLast4?: string;
}

export interface QrSigner {
  key: CryptoKeyPair;
  spki: Uint8Array<ArrayBuffer>;
}

export async function makeSigner(): Promise<QrSigner> {
  const key = await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true, ["sign", "verify"],
  );
  return { key, spki: new Uint8Array(await crypto.subtle.exportKey("spki", key.publicKey)) };
}

async function gzip(data: Uint8Array<ArrayBuffer>): Promise<Uint8Array> {
  const stream = new CompressionStream("gzip");
  const writer = stream.writable.getWriter();
  void writer.write(data);
  void writer.close();
  const reader = stream.readable.getReader();
  const chunks: number[] = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(...value);
  }
  return new Uint8Array(chunks);
}

/** The QR's text (a decimal number) for this holder. */
export async function secureQrText(signer: QrSigner, holder: FixtureHolder = {}): Promise<string> {
  const h = {
    name: "Asha Verma", dob: "14-02-1998", gender: "F", state: "Maharashtra", pincode: "411001",
    aadhaarLast4: "3632", generated: "20260115103000", mobileLast4: "3210", ...holder,
  };
  const fields = ["V2", "2", `${h.aadhaarLast4}${h.generated}123`, h.name, h.dob, h.gender, "W/O Ravi Verma", "Pune", "",
    "12", "Kothrud", h.pincode, "Kothrud", h.state, "Paud Road", "Pune City", "Pune", h.mobileLast4];
  const text = new TextEncoder();
  const bytes: number[] = [];
  for (const field of fields) bytes.push(...text.encode(field), 0xff);
  bytes.push(0xff, 0x4f, 0xff, 0x51, 1, 2, 3, 0xff, 4); // a J2K codestream header, then "image" bytes
  const signed = new Uint8Array(bytes);
  const signature = new Uint8Array(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", signer.key.privateKey, signed));
  const packed = await gzip(new Uint8Array([...signed, ...signature]));
  return BigInt(`0x${Array.from(packed, (b) => b.toString(16).padStart(2, "0")).join("")}`).toString();
}
