import type { Profile, TokenPair } from "./types";

/**
 * The access token lives in memory only. The refresh token is kept in localStorage so a reload
 * keeps you signed in; logout revokes it on the server and removes it here.
 */
const REFRESH_KEY = "zeo.refresh";

export interface SessionState {
  accessToken: string | null;
  expiresAt: number | null;
  user: Profile | null;
}

type Listener = (state: SessionState) => void;

let state: SessionState = { accessToken: null, expiresAt: null, user: null };
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) listener(state);
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export const session = {
  get state(): SessionState {
    return state;
  },
  get accessToken(): string | null {
    return state.accessToken;
  },
  refreshToken(): string | null {
    return storage()?.getItem(REFRESH_KEY) ?? null;
  },
  establish(pair: TokenPair, now = Date.now()): void {
    storage()?.setItem(REFRESH_KEY, pair.refresh_token);
    state = { accessToken: pair.access_token, expiresAt: now + pair.expires_in * 1000, user: pair.user };
    emit();
  },
  updateUser(user: Profile): void {
    state = { ...state, user };
    emit();
  },
  clear(): void {
    storage()?.removeItem(REFRESH_KEY);
    state = { accessToken: null, expiresAt: null, user: null };
    emit();
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};
