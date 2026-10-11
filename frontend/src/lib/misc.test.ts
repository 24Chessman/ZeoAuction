import { ApiError, describeError, errorField } from "./errors";
import { formatBytes, formatRemaining, initials, shortId, timeAgo, titleCase } from "./format";
import { duration, policy, readPolicy } from "./policy";
import { cn } from "./cn";

describe("settlement policy", () => {
  it("is read from config/settlement-policy.yaml", () => {
    expect(policy.feeVersion).toMatch(/^\d{4}-\d{2}-v\d+$/);
    expect(policy.feeCents).toBeGreaterThan(0);
    expect(policy.guardSeconds).toBeGreaterThan(0);
    expect(policy.chargedToLosingBidders).toBe(false);
  });

  it("parses the file shape", () => {
    const parsed = readPolicy(`
convenience_fee: { fee_version: "x-v1", amount: "30.00", currency: "INR", charged_to_losing_bidders: false }
protection_window: { days: 5 }
anti_snipe: { guard_interval_seconds: 60, extension_seconds: 90, max_extensions: 3 }
`);
    expect(parsed).toMatchObject({ feeCents: 3_000, currency: "INR", protectionDays: 5, extensionSeconds: 90, maxExtensions: 3 });
    expect(duration(120)).toBe("2 min");
    expect(duration(90)).toBe("90 s");
  });
});

describe("errors", () => {
  it("describes taxonomy codes with their own copy", () => {
    const error = new ApiError(422, { code: "BID_BELOW_INCREMENT", message: "low", details: { min_next_bid: "5.00" } });
    expect(describeError(error)).toMatchObject({ code: "BID_BELOW_INCREMENT", title: "Your bid is below the minimum next bid" });
    expect(error.retryable).toBe(false);
    expect(new ApiError(503, { code: "AUCTION_STATE_UNAVAILABLE", message: "x", details: null }).retryable).toBe(true);
  });

  it("falls back to the server message for unknown codes", () => {
    expect(describeError(new ApiError(400, { code: "SOMETHING_NEW", message: "Server said", details: null })).title).toBe("Server said");
    expect(describeError(new Error("boom"))).toMatchObject({ code: "UNKNOWN", message: "boom" });
  });

  it("reads the field from validation details", () => {
    expect(errorField(new ApiError(422, { code: "VALIDATION_ERROR", message: "x", details: { field: "email" } }))).toBe("email");
    expect(errorField(new Error("x"))).toBeNull();
  });
});

describe("format", () => {
  it("formats remaining time", () => {
    expect(formatRemaining(0)).toBe("00:00");
    expect(formatRemaining(65_000)).toBe("01:05");
    expect(formatRemaining(3 * 3_600_000 + 12 * 60_000)).toBe("3h 12m");
    expect(formatRemaining(2 * 86_400_000 + 4 * 3_600_000)).toBe("2d 4h");
  });

  it("formats relative times, sizes, ids and names", () => {
    const now = Date.parse("2026-10-06T12:00:00Z");
    expect(timeAgo("2026-10-06T11:59:50Z", now)).toBe("just now");
    expect(timeAgo("2026-10-06T11:50:00Z", now)).toBe("10 minutes ago");
    expect(timeAgo("2026-10-06T09:00:00Z", now)).toBe("3 hours ago");
    expect(timeAgo("2026-10-04T12:00:00Z", now)).toBe("2 days ago");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(shortId("00000000-0000-4000-8000-000000000106")).toBe("000106");
    expect(initials("Buyer One")).toBe("BO");
    expect(initials("solo")).toBe("S");
    expect(titleCase("cameras")).toBe("Cameras");
    expect(cn("a", false, null, "b")).toBe("a b");
  });
});
