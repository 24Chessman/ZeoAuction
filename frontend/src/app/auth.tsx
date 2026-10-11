import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { authApi, refreshSession, session, type Profile } from "@/lib/api";
import type { SessionState } from "@/lib/api/session";

type Status = "loading" | "signed-in" | "signed-out";

interface AuthValue {
  status: Status;
  user: Profile | null;
  login: (email: string, password: string) => Promise<Profile>;
  register: (input: { email: string; password: string; display_name: string }) => Promise<Profile>;
  logout: () => Promise<void>;
  /** Re-read /users/me, e.g. after a KYC submission changes kyc_status. */
  reload: () => Promise<Profile | null>;
  /** Force a token refresh so new claims (KYC approval) reach the gateway. */
  refreshClaims: () => Promise<void>;
  updateName: (name: string) => Promise<Profile>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>(session.state);
  const [status, setStatus] = useState<Status>(() => (session.refreshToken() ? "loading" : "signed-out"));

  useEffect(
    () =>
      session.subscribe((next) => {
        setState(next);
        setStatus(next.user ? "signed-in" : "signed-out");
      }),
    [],
  );

  // Restore a session from the stored refresh token on first load.
  useEffect(() => {
    if (!session.refreshToken() || session.accessToken) return;
    refreshSession().catch(() => setStatus("signed-out"));
  }, []);

  // Coming back to the tab re-reads the profile, so a KYC decision made elsewhere shows up.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible" || !session.accessToken) return;
      authApi.me().then((me) => session.updateUser(me), () => undefined);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  // Refresh a minute before the access token expires, so a live socket never sees 4401.
  useEffect(() => {
    if (!state.expiresAt) return;
    const wait = Math.max(5_000, state.expiresAt - Date.now() - 60_000);
    const timer = setTimeout(() => {
      refreshSession().catch(() => undefined);
    }, wait);
    return () => clearTimeout(timer);
  }, [state.expiresAt]);

  const login = useCallback(async (email: string, password: string) => {
    const pair = await authApi.login(email, password);
    session.establish(pair);
    return pair.user;
  }, []);

  const register = useCallback(
    async (input: { email: string; password: string; display_name: string }) => {
      await authApi.register(input);
      return login(input.email, input.password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    const token = session.refreshToken();
    session.clear();
    if (token) await authApi.logout(token).catch(() => undefined);
  }, []);

  const reload = useCallback(async () => {
    if (!session.accessToken) return null;
    const me = await authApi.me();
    session.updateUser(me);
    return me;
  }, []);

  const refreshClaims = useCallback(async () => {
    await refreshSession();
  }, []);

  const updateName = useCallback(async (name: string) => {
    const me = await authApi.updateMe(name);
    session.updateUser(me);
    return me;
  }, []);

  const value = useMemo<AuthValue>(
    () => ({ status, user: state.user, login, register, logout, reload, refreshClaims, updateName }),
    [status, state.user, login, register, logout, reload, refreshClaims, updateName],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}
