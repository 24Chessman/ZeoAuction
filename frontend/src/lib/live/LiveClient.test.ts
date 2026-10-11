import { LiveClient, type LiveMessage, type SocketLike, type StatusInfo } from "./LiveClient";

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: Array<Record<string, unknown>> = [];
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;
  closedWith: number | null = null;
  constructor(readonly url: string) {}
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close(code = 1000) {
    this.closedWith = code;
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  receive(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
  drop(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

function setup(token: string | null = "tok-1") {
  const sockets: FakeSocket[] = [];
  const refresh = vi.fn(async () => undefined);
  let current = token;
  const client = new LiveClient({
    url: "ws://gw/ws",
    factory: (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    getToken: () => current,
    refresh,
    random: () => 0.5,
  });
  const messages: LiveMessage[] = [];
  const statuses: StatusInfo[] = [];
  client.onMessage((m) => messages.push(m));
  client.onStatus((s) => statuses.push(s));
  return { client, sockets, refresh, messages, statuses, setToken: (t: string | null) => (current = t) };
}

const price = (seq: number, amount = "100.00") => ({
  type: "price_update", auction_id: "a1", current_price: amount, min_next_bid: "101.00", server_seq: seq,
});

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("LiveClient", () => {
  it("connects with the token and subscribes with the last server_seq", () => {
    const { client, sockets } = setup();
    client.subscribe("a1", 7);
    client.start();
    expect(sockets[0].url).toBe("ws://gw/ws?access_token=tok-1");
    sockets[0].open();
    expect(sockets[0].sent).toEqual([{ type: "subscribe", auction_id: "a1", last_seq: 7 }]);
    expect(client.status.status).toBe("open");
  });

  it("stays idle without a token", () => {
    const { client, sockets } = setup(null);
    client.start();
    expect(sockets).toHaveLength(0);
    expect(client.status.status).toBe("idle");
  });

  it("discards price frames that are not newer than the last server_seq", () => {
    const { client, sockets, messages } = setup();
    client.subscribe("a1");
    client.start();
    sockets[0].open();
    sockets[0].receive(price(3, "130.00"));
    sockets[0].receive(price(2, "120.00")); // reordered
    sockets[0].receive(price(3, "130.00")); // duplicate
    sockets[0].receive(price(4, "140.00"));
    expect(messages.map((m) => (m as { server_seq: number }).server_seq)).toEqual([3, 4]);
    expect(client.lastSeq("a1")).toBe(4);
  });

  it("ignores malformed frames and passes other message types through", () => {
    const { client, sockets, messages } = setup();
    client.start();
    sockets[0].open();
    sockets[0].onmessage?.({ data: "not json" });
    sockets[0].receive({ type: "auction_extended", auction_id: "a1", new_closes_at: "2026-10-06T12:00:00Z" });
    expect(messages).toHaveLength(1);
  });

  it("reconciles a bid acknowledgement through the same ordering", () => {
    const { client, sockets, messages } = setup();
    client.subscribe("a1");
    client.start();
    sockets[0].open();
    expect(client.observe("a1", 5)).toBe(true);
    expect(client.observe("a1", 5)).toBe(false);
    sockets[0].receive(price(5));
    expect(messages).toHaveLength(0); // the ack already applied seq 5
  });

  it("reconnects with backoff and resubscribes from the last seen seq", () => {
    const { client, sockets, statuses } = setup();
    client.subscribe("a1");
    client.start();
    sockets[0].open();
    sockets[0].receive(price(9));
    sockets[0].drop(1006);
    expect(client.status.status).toBe("reconnecting");
    expect(client.status.retryAt).not.toBeNull();
    vi.advanceTimersByTime(1000);
    expect(sockets).toHaveLength(2);
    sockets[1].open();
    expect(sockets[1].sent).toEqual([{ type: "subscribe", auction_id: "a1", last_seq: 9 }]);
    expect(statuses.at(-1)?.status).toBe("open");
  });

  it("refreshes the token after 4401 before reconnecting", async () => {
    const { client, sockets, refresh, setToken } = setup();
    client.start();
    sockets[0].open();
    setToken("tok-2");
    sockets[0].drop(4401);
    expect(refresh).toHaveBeenCalledOnce();
    await vi.runOnlyPendingTimersAsync();
    expect(sockets[1].url).toContain("access_token=tok-2");
  });

  it("goes idle when the refresh after 4401 fails", async () => {
    const { client, sockets, refresh } = setup();
    refresh.mockRejectedValueOnce(new Error("signed out"));
    client.start();
    sockets[0].open();
    sockets[0].drop(4401);
    await vi.runOnlyPendingTimersAsync();
    expect(client.status.status).toBe("idle");
  });

  it("reconnects at once after an idle close and backs off after a rate limit", () => {
    const { client, sockets } = setup();
    client.start();
    sockets[0].open();
    sockets[0].drop(4408);
    vi.advanceTimersByTime(0);
    expect(sockets).toHaveLength(2);
    sockets[1].open();
    sockets[1].drop(4429);
    vi.advanceTimersByTime(4_000);
    expect(sockets).toHaveLength(2);
    vi.advanceTimersByTime(1_500);
    expect(sockets).toHaveLength(3);
  });

  it("treats 1013 as try-again-later and recovers with a snapshot", () => {
    const { client, sockets, messages } = setup();
    client.subscribe("a1", 3);
    client.start();
    sockets[0].open();
    sockets[0].drop(1013);
    vi.advanceTimersByTime(2000);
    sockets[1].open();
    sockets[1].receive(price(6)); // snapshot covering the gap
    expect(messages).toHaveLength(1);
    expect(client.status.lastCloseCode).toBe(1013);
  });

  it("shows offline immediately and reconnects when the browser is back", () => {
    const { client, sockets } = setup();
    client.start();
    sockets[0].open();
    client.markOffline();
    expect(client.status.status).toBe("offline");
    expect(sockets[0].closedWith).toBe(1000);
    client.markOnline();
    expect(sockets).toHaveLength(2);
    expect(client.status.status).toBe("reconnecting");
  });

  it("pings, unsubscribes and stops cleanly", () => {
    const { client, sockets } = setup();
    client.subscribe("a1");
    client.start();
    sockets[0].open();
    vi.advanceTimersByTime(25_000);
    expect(sockets[0].sent.at(-1)).toEqual({ type: "ping" });
    client.unsubscribe("a1");
    expect(sockets[0].sent.at(-1)).toEqual({ type: "unsubscribe", auction_id: "a1" });
    client.stop();
    expect(client.status.status).toBe("idle");
    expect(sockets[0].closedWith).toBe(1000);
    client.markOffline(); // no-op when stopped
    expect(client.status.status).toBe("idle");
  });
});
