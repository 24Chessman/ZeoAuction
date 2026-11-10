import type { AdminSubmission, FaceCheckResult, KycSubmission, QueuePage } from "../api/types";
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

describe("mock Aadhaar Secure QR and face check", () => {
  it("verifies the Aadhaar, then a clear face match puts the seller in the admin queue", async () => {
    const mock = server();
    const token = await login(mock, "unverified@zeo.local");
    const submission = await upload(mock, token);
    expect(submission).toMatchObject({ state: "SUBMITTED", can_resubmit: true, face: { attempts_left: 3, last_outcome: null } });
    expect(submission.aadhaar).toMatchObject({
      holder_name: "Asha Verma", year_of_birth: 1998, gender: "F", state: "Maharashtra", reference_last4: "3632",
      qr_generated_at: "2026-01-15T05:00:00.123Z", mobile_verified: null,
    });
    expect(submission.aadhaar).not.toHaveProperty("pincode");

    const check = await send(mock, token, "POST", `/api/v1/kyc/submissions/${submission.submission_id}/face`, frames(6));
    expect(check.status).toBe(200);
    const result = check.body as FaceCheckResult;
    expect(result.outcome).toBe("MATCH");
    expect(result.submission.state).toBe("UNDER_REVIEW");
    expect(result.submission.decided_at).toBeNull();
    expect(result.submission.documents.map((d) => d.doc_type)).toEqual(["AADHAAR_PHOTO", "FACE_CAPTURE"]);
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
    const rightMobile = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm(undefined, PNG, "+91 98765 43210"));
    expect((rightMobile.body as KycSubmission).aadhaar?.mobile_verified).toBe(true);
    const pdf = new Blob(["%PDF-1.7"], { type: "application/pdf" });
    const notImage = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm("aadhaar.pdf", pdf));
    expect(notImage.body).toMatchObject({ details: { reason: "not_image" } });
  });

  it("refuses too few frames without counting an attempt", async () => {
    const mock = server();
    const token = await login(mock, "unverified@zeo.local");
    const { submission_id } = await upload(mock, token);
    const response = await send(mock, token, "POST", `/api/v1/kyc/submissions/${submission_id}/face`, frames(2));
    expect(response.status).toBe(422);
    expect(response.body).toMatchObject({ code: "FACE_CAPTURE_INVALID", details: { reason: "frame_count" } });
    const me = (await send(mock, token, "GET", "/api/v1/kyc/submissions/me")).body as KycSubmission;
    expect(me.face.attempts_left).toBe(3);
  });

  it("rejects after three failed matches and then enforces the cooldown", async () => {
    const mock = server();
    const token = await login(mock, "unverified@zeo.local");
    const { submission_id } = await upload(mock, token, "nomatch.png");
    const outcomes: FaceCheckResult[] = [];
    for (let i = 0; i < 3; i += 1) {
      outcomes.push((await send(mock, token, "POST", `/api/v1/kyc/submissions/${submission_id}/face`, frames(6))).body as FaceCheckResult);
    }
    expect(outcomes.map((o) => [o.outcome, o.attempts_left])).toEqual([["NO_MATCH", 2], ["NO_MATCH", 1], ["NO_MATCH", 0]]);
    expect(outcomes[2].submission).toMatchObject({ state: "REJECTED", can_resubmit: false });
    expect(outcomes[2].submission.resubmit_after).not.toBeNull();
    expect(outcomes[0].submission.can_resubmit).toBe(false); // a counted attempt locks the QR
    const again = await send(mock, token, "POST", "/api/v1/kyc/aadhaar", aadhaarForm());
    expect(again.status).toBe(409);
    expect(again.body).toMatchObject({ code: "KYC_COOLDOWN" });
  });

  it("sends a close match to the admin queue, where an administrator approves it", async () => {
    const mock = server();
    const seller = await login(mock, "unverified@zeo.local");
    const { submission_id } = await upload(mock, seller, "review.png");
    const check = (await send(mock, seller, "POST", `/api/v1/kyc/submissions/${submission_id}/face`, frames(6))).body as FaceCheckResult;
    expect(check).toMatchObject({ outcome: "REVIEW", submission: { state: "UNDER_REVIEW" } });

    const admin = await login(mock, "admin@zeo.local");
    const queue = (await send(mock, admin, "GET", "/api/v1/admin/kyc/queue?limit=50&offset=0")).body as QueuePage;
    expect(queue.items.map((i) => i.submission_id)).toContain(submission_id);
    expect(queue.items.every((i) => i.state === "UNDER_REVIEW")).toBe(true);
    const detail = (await send(mock, admin, "GET", `/api/v1/admin/kyc/${submission_id}`)).body as AdminSubmission;
    expect(detail.aadhaar?.pincode).toBe("411001");
    expect(detail.face_attempts).toHaveLength(1);
    const approved = await send(mock, admin, "POST", `/api/v1/admin/kyc/${submission_id}/approve`, "{}");
    expect(approved.body).toMatchObject({ state: "VERIFIED" });
    const startReview = await send(mock, admin, "POST", `/api/v1/admin/kyc/${submission_id}/start-review`, "{}");
    expect(startReview.status).toBe(404);
  });

  it("replaces a waiting submission when a new file is uploaded before any face attempt", async () => {
    const mock = server();
    const token = await login(mock, "unverified@zeo.local");
    const first = await upload(mock, token);
    const second = await upload(mock, token);
    expect(second.submission_id).not.toBe(first.submission_id);
    const admin = await login(mock, "admin@zeo.local");
    const old = (await send(mock, admin, "GET", `/api/v1/admin/kyc/${first.submission_id}`)).body as AdminSubmission;
    expect(old).toMatchObject({ state: "REJECTED", rejection_reason: "Replaced by a new Aadhaar QR upload" });
  });
});
