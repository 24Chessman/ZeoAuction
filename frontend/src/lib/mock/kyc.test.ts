import type { AdminSubmission, KycSubmission, QueuePage } from "../api/types";
import { makeSigner, secureQrText, type QrSigner } from "./secureQrFixture";
import { MockServer } from "./server";

/** A synthetic PNG: only its magic number is checked. The fake QR reader below picks the QR the
 * "photo" holds by its file name: *noqr* has none, *tampered* is signed by an untrusted key,
 * *minor* holds a 15-year-old's; anything else, Asha Verma's QR. */
const PNG = new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0])], { type: "image/png" });

let trusted: QrSigner;
let codes: Record<"valid" | "tampered" | "minor", string>;

beforeAll(async () => {
  trusted = await makeSigner();
  const untrusted = await makeSigner();
  codes = {
    valid: await secureQrText(trusted),
    tampered: await secureQrText(untrusted),
    minor: await secureQrText(trusted, { dob: "01-01-2011" }),
  };
}, 30_000);

function server(): MockServer {
  const mock = new MockServer(localStorage);
  mock.reset();
  mock.latency = [0, 0];
  mock.trustedQrKeys = [trusted.spki];
  mock.qrCodes = async (image) => {
    const name = image instanceof File ? image.name : "";
    if (name.includes("noqr")) return [];
    if (name.includes("tampered")) return [codes.tampered];
    if (name.includes("minor")) return [codes.minor];
    return ["https://example.com/not-aadhaar", codes.valid];
  };
  return mock;
}

async function login(mock: MockServer, email: string): Promise<string> {
  const response = await mock.handle({
    service: "auth", method: "POST", path: "/api/v1/auth/login", headers: {},
    body: JSON.stringify({ email, password: "zeo-dev-password" }),
  });
  return (response.body as { access_token: string }).access_token;
}

async function send(mock: MockServer, token: string, method: "GET" | "POST", path: string, body?: FormData | string) {
  const response = await mock.handle({ service: "kyc", method, path, headers: { Authorization: `Bearer ${token}` }, body });
  return response as { status: number; body: unknown };
}

function aadhaarForm(name = "aadhaar-qr.png", image: Blob = PNG, mobile?: string): FormData {
  const form = new FormData();
  form.append("qr_image", image, name);
  if (mobile) form.append("mobile", mobile);
  return form;
}

function frames(count: number): FormData {
  const form = new FormData();
  for (let i = 0; i < count; i += 1) form.append("frames", new Blob([`frame-${i}`], { type: "image/jpeg" }), `f${i}.jpg`);
  return form;
}

async function upload(mock: MockServer, token: string, name?: string) {
  const response = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm(name));
  expect(response.status).toBe(201);
  return response.body as KycSubmission;
}

describe("mock Aadhaar Secure QR verification", () => {
  it("verifies the Aadhaar and puts the seller directly in the admin queue", async () => {
    const mock = server();
    const token = await login(mock, "unverified@zeo.local");
    const submission = await upload(mock, token);
    expect(submission).toMatchObject({ state: "UNDER_REVIEW", can_resubmit: false });
    expect(submission.aadhaar).toMatchObject({
      holder_name: "Asha Verma", year_of_birth: 1998, gender: "F", state: "Maharashtra", reference_last4: "3632",
      qr_generated_at: "2026-01-15T05:00:00.123Z", mobile_verified: null,
    });
    expect(submission.aadhaar).not.toHaveProperty("pincode");
    expect(submission.documents.map((d) => d.doc_type)).toEqual(["AADHAAR_PHOTO"]);
  });

  it("names the field when the QR or mobile is wrong, and refuses non-images", async () => {
    const mock = server();
    const token = await login(mock, "unverified@zeo.local");
    const tampered = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm("tampered.png"));
    expect(tampered.status).toBe(422);
    expect(tampered.body).toMatchObject({ code: "AADHAAR_INVALID", details: { reason: "signature_invalid", field: "qr_image" } });
    const noQr = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm("noqr.png"));
    expect(noQr.body).toMatchObject({ details: { reason: "no_qr" } });
    const minor = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm("minor.png"));
    expect(minor.body).toMatchObject({ details: { reason: "underage", field: "qr_image" } });
    const wrongMobile = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm(undefined, PNG, "9999999999"));
    expect(wrongMobile.body).toMatchObject({ details: { reason: "mobile_mismatch", field: "mobile" } });
    const pdf = new Blob(["%PDF-1.7"], { type: "application/pdf" });
    const notImage = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm("aadhaar.pdf", pdf));
    expect(notImage.body).toMatchObject({ details: { reason: "not_image" } });
    const rightMobile = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm(undefined, PNG, "+91 98765 43210"));
    expect((rightMobile.body as KycSubmission).aadhaar?.mobile_verified).toBe(true);
  });

  it("does not run the removed face-capture flow", async () => {
    const mock = server();
    const token = await login(mock, "unverified@zeo.local");
    const { submission_id } = await upload(mock, token);
    const response = await send(mock, token, "POST", `/api/v1/kyc/submissions/${submission_id}/face`, frames(2));
    expect(response.status).toBe(409);
    expect(response.body).toMatchObject({ code: "CONFLICT", details: { state: "UNDER_REVIEW" } });
  });

  it("refuses a replacement while the submission is under review", async () => {
    const mock = server();
    const token = await login(mock, "unverified@zeo.local");
    await upload(mock, token);
    const again = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm());
    expect(again.status).toBe(409);
    expect(again.body).toMatchObject({ code: "KYC_ALREADY_ACTIVE" });
  });

  it("sends a verified QR to the admin queue, where an administrator approves it", async () => {
    const mock = server();
    const seller = await login(mock, "unverified@zeo.local");
    const { submission_id } = await upload(mock, seller, "review.png");

    const admin = await login(mock, "admin@zeo.local");
    const queue = (await send(mock, admin, "GET", "/api/v1/admin/kyc/queue?limit=50&offset=0")).body as QueuePage;
    expect(queue.items.map((i) => i.submission_id)).toContain(submission_id);
    expect(queue.items.every((i) => i.state === "UNDER_REVIEW")).toBe(true);
    const detail = (await send(mock, admin, "GET", `/api/v1/admin/kyc/${submission_id}`)).body as AdminSubmission;
    expect(detail.aadhaar?.pincode).toBe("411001");
    expect(detail.face_attempts).toHaveLength(0);
    const approved = await send(mock, admin, "POST", `/api/v1/admin/kyc/${submission_id}/approve`, "{}");
    expect(approved.body).toMatchObject({ state: "VERIFIED" });
    const startReview = await send(mock, admin, "POST", `/api/v1/admin/kyc/${submission_id}/start-review`, "{}");
    expect(startReview.status).toBe(404);
  });

  it("keeps the active submission when another QR is uploaded", async () => {
    const mock = server();
    const token = await login(mock, "unverified@zeo.local");
    const first = await upload(mock, token);
    const second = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm());
    expect(second.status).toBe(409);
    expect(second.body).toMatchObject({ code: "KYC_ALREADY_ACTIVE", details: { state: "UNDER_REVIEW" } });
    const current = (await send(mock, token, "GET", "/api/v1/kyc/submissions/me")).body as KycSubmission;
    expect(current.submission_id).toBe(first.submission_id);
  });
});
