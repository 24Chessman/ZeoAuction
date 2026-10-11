import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { refreshSession, session } from "@/lib/api";
import { serviceUrls, useMocks } from "@/lib/config";
import { LiveClient, type SocketFactory, type StatusInfo } from "@/lib/live/LiveClient";
import { mockSocketFactory } from "@/lib/mock";
import { formatMoney, parseMoney } from "@/lib/money";
import { useToast } from "@/components/ui";
import { useAuth } from "./auth";

const browserSocket: SocketFactory = (url) => new WebSocket(url) as unknown as ReturnType<SocketFactory>;

export function createLiveClient(factory: SocketFactory = useMocks ? mockSocketFactory : browserSocket): LiveClient {
  return new LiveClient({
    url: serviceUrls.ws,
    factory,
    getToken: () => session.accessToken,
    refresh: () => refreshSession(),
  });
}

const LiveContext = createContext<LiveClient | null>(null);

export function LiveProvider({ children, client: injected }: { children: ReactNode; client?: LiveClient }) {
  const client = useMemo(() => injected ?? createLiveClient(), [injected]);
  const { status } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  // The gateway needs a token, so the socket runs only while signed in.
  useEffect(() => {
    if (status === "signed-in") client.start();
    else client.stop();
  }, [client, status]);

  useEffect(() => () => client.stop(), [client]);

  useEffect(() => {
    const offline = () => client.markOffline();
    const online = () => client.markOnline();
    window.addEventListener("offline", offline);
    window.addEventListener("online", online);
    return () => {
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", online);
    };
  }, [client]);

  // Outbid alerts reach every connection of the displaced bidder, whatever page they are on.
  useEffect(
    () =>
      client.onMessage((message) => {
        if (message.type !== "outbid") return;
        toast({
          tone: "outbid",
          title: "You've been outbid",
          description: `The price is now ${formatMoney(parseMoney(message.current_price))}.`,
          action: { label: "Go to auction", onClick: () => navigate(`/auctions/${message.auction_id}`) },
          duration: 8000,
        });
      }),
    [client, toast, navigate],
  );

  return <LiveContext.Provider value={client}>{children}</LiveContext.Provider>;
}

export function useLiveClient(): LiveClient {
  const client = useContext(LiveContext);
  if (!client) throw new Error("useLiveClient outside LiveProvider");
  return client;
}

export function useConnectionStatus(): StatusInfo {
  const client = useLiveClient();
  const [info, setInfo] = useState<StatusInfo>(client.status);
  useEffect(() => client.onStatus(setInfo), [client]);
  return info;
}
