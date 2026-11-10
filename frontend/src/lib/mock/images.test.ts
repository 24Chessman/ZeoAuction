import type { Auction } from "../api/types";
import { MockServer } from "./server";

const JPEG = () => new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4])], { type: "image/jpeg" });

function server(): MockServer {
  const mock = new MockServer(localStorage);
  mock.reset();
  mock.latency = [0, 0];
  return mock;
}

async function login(mock: MockServer, email: string): Promise<string> {
  const response = await mock.handle({
    service: "auth", method: "POST", path: "/api/v1/auth/login", headers: {},
    body: JSON.stringify({ email, password: "zeo-dev-password" }),
  });
  return (response.body as { access_token: string }).access_token;
}

async function send(mock: MockServer, token: string, method: "GET" | "POST" | "DELETE", path: string, body?: FormData | string) {
  const response = await mock.handle({ service: "auction", method, path, headers: { Authorization: `Bearer ${token}` }, body });
  return response as { status: number; body: unknown };
}

function photo(blob: Blob = JPEG(), name = "front.jpg"): FormData {
  const form = new FormData();
  form.append("image", blob, name);
  return form;
}

async function draft(mock: MockServer, token: string): Promise<Auction> {
  const opens = new Date(Date.now() + 5 * 60_000).toISOString();
  const closes = new Date(Date.now() + 86_400_000).toISOString();
  const body = JSON.stringify({ title: "Rangefinder camera", description: "", category: "cameras", starting_price: "100.00", reserve_price: null, currency: "INR", opens_at: opens, closes_at: closes });
  return (await send(mock, token, "POST", "/api/v1/auctions", body)).body as Auction;
}

describe("mock listing photos", () => {
  it("adds photos in order, lists them on the auction and removes them", async () => {
    const mock = server();
    const token = await login(mock, "seller@zeo.local");
    const auction = await draft(mock, token);
    expect(auction.images).toEqual([]);
    const first = await send(mock, token, "POST", `/api/v1/auctions/${auction.auction_id}/images`, photo());
    expect(first.status).toBe(201);
    await send(mock, token, "POST", `/api/v1/auctions/${auction.auction_id}/images`, photo());
    const fetched = (await send(mock, token, "GET", `/api/v1/auctions/${auction.auction_id}`)).body as Auction;
    expect(fetched.images.map((i) => i.position)).toEqual([0, 1]);
    expect(fetched.images[0].url).toMatch(/^data:image\/jpeg/);

    const removed = await send(mock, token, "DELETE", `/api/v1/auctions/${auction.auction_id}/images/${fetched.images[0].image_id}`);
    expect((removed.body as Auction).images.map((i) => i.position)).toEqual([1]);
  });

  it("checks the bytes, the size and the count", async () => {
    const mock = server();
    const token = await login(mock, "seller@zeo.local");
    const { auction_id } = await draft(mock, token);
    const gif = await send(mock, token, "POST", `/api/v1/auctions/${auction_id}/images`, photo(new Blob(["GIF89a"], { type: "image/jpeg" })));
    expect(gif.body).toMatchObject({ code: "VALIDATION_ERROR", details: { field: "image", reason: "unsupported_format" } });
    for (let i = 0; i < 6; i += 1) await send(mock, token, "POST", `/api/v1/auctions/${auction_id}/images`, photo());
    const seventh = await send(mock, token, "POST", `/api/v1/auctions/${auction_id}/images`, photo());
    expect(seventh.status).toBe(422);
    expect(seventh.body).toMatchObject({ details: { reason: "too_many" } });
  });

  it("lets only the seller change photos, and only before the auction opens", async () => {
    const mock = server();
    const seller = await login(mock, "seller@zeo.local");
    const { auction_id } = await draft(mock, seller);
    const buyer = await login(mock, "buyer1@zeo.local");
    expect((await send(mock, buyer, "POST", `/api/v1/auctions/${auction_id}/images`, photo())).status).toBe(403);
    const admin = await login(mock, "admin@zeo.local");
    await send(mock, seller, "POST", `/api/v1/auctions/${auction_id}/publish`);
    await send(mock, admin, "POST", `/api/v1/auctions/${auction_id}/events`, JSON.stringify({ event: "open" }));
    const late = await send(mock, seller, "POST", `/api/v1/auctions/${auction_id}/images`, photo());
    expect(late.status).toBe(409);
    expect(late.body).toMatchObject({ details: { state: "OPEN" } });
  });
});
