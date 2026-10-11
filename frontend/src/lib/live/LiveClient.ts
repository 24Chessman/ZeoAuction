/**
 * WebSocket client for the ws-gateway (SDD 7.8, #71).
 *
 * - Price frames whose server_seq is not greater than the last one seen are discarded, so a
 *   redelivered or reordered frame can never move the price backwards.
 * - On (re)connect every room is re-subscribed with its last server_seq; the gateway answers
 *   with a snapshot when it holds anything newer, which closes any gap.
 * - Close codes from services/ws-gateway/app/connections.py each get their own recovery:
 *   4401 token expired -> refresh, then reconnect; 4408 idle -> reconnect now;
 *   4429 rate limited -> back off; 1013 try again later -> reconnect and take a snapshot.
 */

export const CLOSE_TOKEN_EXPIRED = 4401;
export const CLOSE_IDLE = 4408;
export const CLOSE_RATE_LIMITED = 4429;
export const CLOSE_TRY_AGAIN_LATER = 1013;
export const CLOSE_NORMAL = 1000;

const PING_INTERVAL_MS = 25_000;
const BASE_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 15_000;
const RATE_LIMIT_BACKOFF_MS = 5_000;

export interface SocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number; reason?: string }) => void) | null;
  onerror: ((event: unknown) => void) | null;
}

export type SocketFactory = (url: string) => SocketLike;

export interface PriceUpdate {
  type: "price_update";
  auction_id: string;
  current_price: string;
  min_next_bid: string;
  server_seq: number;
}
export interface Outbid {
  type: "outbid";
  auction_id: string;
  your_bid_id: string;
  current_price: string;
  server_seq: number;
}
export interface AuctionExtended {
  type: "auction_extended";
  auction_id: string;
  new_closes_at: string;
}
export interface AuctionClosed {
  type: "auction_closed";
  auction_id: string;
  winning_bid_id: string | null;
}
export interface ServerError {
  type: "error";
  code: string;
  message: string;
  auction_id?: string;
}

export type LiveMessage = PriceUpdate | Outbid | AuctionExtended | AuctionClosed | ServerError;

export type ConnectionStatus = "idle" | "connecting" | "open" | "reconnecting" | "offline";

export interface StatusInfo {
  status: ConnectionStatus;
  attempt: number;
  lastCloseCode: number | null;
  retryAt: number | null;
}

type Handler = (message: LiveMessage) => void;
type StatusHandler = (info: StatusInfo) => void;

export interface LiveClientOptions {
  url: string;
  factory: SocketFactory;
  /** The current access token, or null when signed out. */
  getToken: () => string | null;
  /** Refresh the access token after a 4401; rejects when the session is gone. */
  refresh: () => Promise<unknown>;
  now?: () => number;
  random?: () => number;
}

export class LiveClient {
  private socket: SocketLike | null = null;
  private readonly rooms = new Map<string, number>(); // auction_id -> last server_seq
  private readonly handlers = new Set<Handler>();
  private readonly statusHandlers = new Set<StatusHandler>();
  private info: StatusInfo = { status: "idle", attempt: 0, lastCloseCode: null, retryAt: null };
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private stopped = true;
  private readonly now: () => number;
  private readonly random: () => number;

  constructor(private readonly options: LiveClientOptions) {
    this.now = options.now ?? Date.now;
    this.random = options.random ?? Math.random;
  }

  get status(): StatusInfo {
    return this.info;
  }

  lastSeq(auctionId: string): number {
    return this.rooms.get(auctionId) ?? 0;
  }

  /**
   * Record a server_seq learned outside the socket (a bid acknowledgement or the REST history).
   * Returns true when it is newer than anything seen, i.e. the caller should apply it.
   */
  observe(auctionId: string, serverSeq: number): boolean {
    if (serverSeq <= this.lastSeq(auctionId)) return false;
    if (this.rooms.has(auctionId)) this.rooms.set(auctionId, serverSeq);
    return true;
  }

  onMessage(handler: Handler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    handler(this.info);
    return () => this.statusHandlers.delete(handler);
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onclose = null;
      socket.close(CLOSE_NORMAL, "client stopped");
    }
    this.setStatus({ status: "idle", attempt: 0, lastCloseCode: null, retryAt: null });
  }

  subscribe(auctionId: string, lastSeq = 0): void {
    const known = this.rooms.get(auctionId) ?? 0;
    this.rooms.set(auctionId, Math.max(known, lastSeq));
    this.sendSubscribe(auctionId);
  }

  unsubscribe(auctionId: string): void {
    this.rooms.delete(auctionId);
    this.sendRaw({ type: "unsubscribe", auction_id: auctionId });
  }

  /** The browser went offline: show it now instead of waiting for a socket timeout. */
  markOffline(): void {
    if (this.stopped) return;
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onclose = null;
      socket.close(CLOSE_NORMAL, "offline");
    }
    // attempt >= 1 so the reconnect after `online` reads as "reconnecting", not a first connect.
    this.setStatus({ ...this.info, status: "offline", attempt: Math.max(1, this.info.attempt), retryAt: null });
  }

  /** The browser is back online: reconnect immediately. */
  markOnline(): void {
    if (this.stopped || this.socket) return;
    this.clearTimers();
    this.open();
  }

  private open(): void {
    const token = this.options.getToken();
    if (!token) {
      this.setStatus({ ...this.info, status: "idle" });
      return;
    }
    const reconnecting = this.info.attempt > 0 || this.info.lastCloseCode !== null;
    this.setStatus({ ...this.info, status: reconnecting ? "reconnecting" : "connecting", retryAt: null });
    const separator = this.options.url.includes("?") ? "&" : "?";
    const socket = this.options.factory(`${this.options.url}${separator}access_token=${encodeURIComponent(token)}`);
    this.socket = socket;
    socket.onopen = () => {
      this.setStatus({ status: "open", attempt: 0, lastCloseCode: this.info.lastCloseCode, retryAt: null });
      for (const auctionId of this.rooms.keys()) this.sendSubscribe(auctionId);
      this.pingTimer = setInterval(() => this.sendRaw({ type: "ping" }), PING_INTERVAL_MS);
    };
    socket.onmessage = (event) => this.receive(event.data);
    socket.onerror = () => {
      // The close event that follows carries the code; nothing to do here.
    };
    socket.onclose = (event) => this.closed(event.code);
  }

  private closed(code: number): void {
    this.socket = null;
    this.clearTimers();
    if (this.stopped) return;
    const attempt = this.info.attempt + 1;
    if (code === CLOSE_TOKEN_EXPIRED) {
      this.setStatus({ status: "reconnecting", attempt, lastCloseCode: code, retryAt: null });
      this.options.refresh().then(
        () => !this.stopped && this.open(),
        () => this.setStatus({ status: "idle", attempt: 0, lastCloseCode: code, retryAt: null }),
      );
      return;
    }
    let delay: number;
    if (code === CLOSE_IDLE) delay = 0;
    else if (code === CLOSE_RATE_LIMITED) delay = Math.max(RATE_LIMIT_BACKOFF_MS, this.backoff(attempt));
    else delay = this.backoff(attempt);
    this.setStatus({ status: "reconnecting", attempt, lastCloseCode: code, retryAt: this.now() + delay });
    this.retryTimer = setTimeout(() => this.open(), delay);
  }

  /** Exponential backoff with full jitter, capped. */
  private backoff(attempt: number): number {
    const ceiling = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** (attempt - 1));
    return Math.round(ceiling / 2 + (this.random() * ceiling) / 2);
  }

  private receive(data: unknown): void {
    let message: LiveMessage;
    try {
      message = JSON.parse(String(data)) as LiveMessage;
    } catch {
      return;
    }
    if (message.type === "price_update") {
      if (message.server_seq <= this.lastSeq(message.auction_id)) return; // stale or duplicate
      this.rooms.set(message.auction_id, message.server_seq);
    }
    for (const handler of this.handlers) handler(message);
  }

  private sendSubscribe(auctionId: string): void {
    this.sendRaw({ type: "subscribe", auction_id: auctionId, last_seq: this.lastSeq(auctionId) });
  }

  private sendRaw(message: object): void {
    if (this.socket && this.socket.readyState === 1) this.socket.send(JSON.stringify(message));
  }

  private clearTimers(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.retryTimer = null;
    this.pingTimer = null;
  }

  private setStatus(info: StatusInfo): void {
    this.info = info;
    for (const handler of this.statusHandlers) handler(info);
  }
}
