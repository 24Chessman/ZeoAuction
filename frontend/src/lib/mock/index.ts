import type { SocketFactory } from "../live/LiveClient";
import { MockServer } from "./server";
import { MockSocket, mockNetwork } from "./socket";

export { mockNetwork };

let server: MockServer | null = null;

export function mockServer(): MockServer {
  server ??= new MockServer();
  return server;
}

export const mockSocketFactory: SocketFactory = (url) => new MockSocket(url, mockServer());

let started = false;

/**
 * Background activity for mock mode: the lifecycle timer (open / close on time) and synthetic
 * bidders on the auctions this tab is watching, so a demo shows the price moving on its own.
 */
export function startMockActivity(): void {
  if (started) return;
  started = true;
  const instance = mockServer();
  setInterval(() => instance.sync(), 1_000);
  setInterval(() => {
    if (mockNetwork.offline) return;
    for (const auctionId of mockNetwork.watched()) {
      if (Math.random() < 0.3) instance.simulateBid(auctionId);
    }
  }, 12_000);
}
