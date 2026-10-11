import type { SocketLike } from "../live/LiveClient";
import type { MockServer } from "./server";

/**
 * A WebSocket stand-in that speaks the ws-gateway protocol against the MockServer:
 * 4401 on a bad token, a snapshot on subscribe, price_update / outbid / auction_extended /
 * auction_closed fan-out, ping -> pong.
 */

const sockets = new Set<MockSocket>();
let offlineUntil = 0;

/** Demo control: drop every connection and refuse new ones for a while (mock mode only). */
export const mockNetwork = {
  dropFor(ms: number): void {
    offlineUntil = Date.now() + ms;
    for (const socket of [...sockets]) socket.serverClose(1006, "network lost");
  },
  get offline(): boolean {
    return Date.now() < offlineUntil;
  },
  /** Auctions that someone in this tab is watching. */
  watched(): Set<string> {
    const rooms = new Set<string>();
    for (const socket of sockets) for (const room of socket.rooms) rooms.add(room);
    return rooms;
  },
};

export class MockSocket implements SocketLike {
  readyState = 0;
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;
  readonly rooms = new Set<string>();
  private userId: string | null = null;
  private unlisten: (() => void) | null = null;

  constructor(url: string, private readonly server: MockServer) {
    const token = new URL(url, "http://mock.local").searchParams.get("access_token");
    setTimeout(() => this.handshake(token), 60);
  }

  private handshake(token: string | null): void {
    if (this.readyState === 3) return;
    if (mockNetwork.offline) return this.serverClose(1006, "network lost");
    const user = this.server.socketUser(token);
    if (!user) return this.serverClose(4401, "token expired");
    this.userId = user.id;
    this.readyState = 1;
    sockets.add(this);
    this.unlisten = this.server.onLive((message, target) => {
      if ((target.auctionId && this.rooms.has(target.auctionId)) || (target.userId && target.userId === this.userId)) {
        this.deliver(message);
      }
    });
    this.onopen?.({});
  }

  send(data: string): void {
    if (this.readyState !== 1) return;
    const message = JSON.parse(data) as { type: string; auction_id?: string; last_seq?: number };
    if (message.type === "ping") this.deliver({ type: "pong" });
    else if (message.type === "unsubscribe" && message.auction_id) this.rooms.delete(message.auction_id);
    else if (message.type === "subscribe" && message.auction_id) {
      this.rooms.add(message.auction_id);
      const snapshot = this.server.snapshot(message.auction_id);
      if (snapshot && Number(snapshot.server_seq) > (message.last_seq ?? 0)) this.deliver(snapshot);
    }
  }

  close(code = 1000): void {
    this.serverClose(code, "client closed");
  }

  serverClose(code: number, reason: string): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    sockets.delete(this);
    this.unlisten?.();
    setTimeout(() => this.onclose?.({ code, reason }), 0);
  }

  private deliver(message: unknown): void {
    setTimeout(() => {
      if (this.readyState === 1) this.onmessage?.({ data: JSON.stringify(message) });
    }, 20);
  }
}
