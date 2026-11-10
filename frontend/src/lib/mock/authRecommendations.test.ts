import { describe, expect, it } from "vitest";
import { MockServer } from "./server";

describe("Gmail Auth & Recommendation Preferences (Mock)", () => {
  it("sends OTP, verifies code, creates new user and updates favorite categories", async () => {
    const server = new MockServer(null);
    server.latency = [0, 0];

    // 1. Send OTP
    const sendRes = await server.handle({
      service: "auth",
      method: "POST",
      path: "/api/v1/auth/gmail/send-otp",
      headers: {},
      body: JSON.stringify({ email: "testuser@gmail.com" }),
    });
    expect(sendRes.status).toBe(200);
    const sendBody = sendRes.body as { status: string; email: string; dev_otp: string };
    expect(sendBody.status).toBe("sent");
    expect(sendBody.email).toBe("testuser@gmail.com");
    expect(sendBody.dev_otp).toHaveLength(6);

    const otp = sendBody.dev_otp;

    // 2. Verify with wrong OTP fails
    const badVerify = await server.handle({
      service: "auth",
      method: "POST",
      path: "/api/v1/auth/gmail/verify-otp",
      headers: {},
      body: JSON.stringify({ email: "testuser@gmail.com", otp: "000000" }),
    });
    expect(badVerify.status).toBe(401);

    // 3. Verify with correct OTP succeeds and returns first login
    const verifyRes = await server.handle({
      service: "auth",
      method: "POST",
      path: "/api/v1/auth/gmail/verify-otp",
      headers: {},
      body: JSON.stringify({ email: "testuser@gmail.com", otp, display_name: "Test Bidder" }),
    });
    expect(verifyRes.status).toBe(200);
    const authData = verifyRes.body as {
      access_token: string;
      is_first_login: boolean;
      user: {
        email: string;
        display_name: string;
        favorite_categories: string[];
        onboarded: boolean;
      };
    };
    expect(authData.is_first_login).toBe(true);
    expect(authData.user.email).toBe("testuser@gmail.com");
    expect(authData.user.display_name).toBe("Test Bidder");
    expect(authData.user.favorite_categories).toEqual([]);
    expect(authData.user.onboarded).toBe(false);

    // 4. Update preferences / favorite categories
    const token = authData.access_token;
    const prefRes = await server.handle({
      service: "auth",
      method: "PATCH",
      path: "/api/v1/users/me",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        favorite_categories: ["watches", "cameras", "art"],
        onboarded: true,
      }),
    });
    expect(prefRes.status).toBe(200);
    const updatedUser = prefRes.body as {
      favorite_categories: string[];
      onboarded: boolean;
    };
    expect(updatedUser.favorite_categories).toEqual(["watches", "cameras", "art"]);
    expect(updatedUser.onboarded).toBe(true);

    // 5. Query /users/me reflects new preferences
    const meRes = await server.handle({
      service: "auth",
      method: "GET",
      path: "/api/v1/users/me",
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(meRes.status).toBe(200);
    const me = meRes.body as {
      favorite_categories: string[];
      onboarded: boolean;
    };
    expect(me.favorite_categories).toEqual(["watches", "cameras", "art"]);
    expect(me.onboarded).toBe(true);
  });
});
