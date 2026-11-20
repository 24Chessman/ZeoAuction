import { describe, expect, it, vi } from "vitest";
import { RENDER_WAKE_INTERVAL_MS, renderServiceUrls, wakeRenderServices } from "./renderWakeup";

describe("wakeRenderServices", () => {
  it("pings every deployed Render service without blocking", () => {
    const fetcher = vi.fn(() => Promise.resolve(new Response()));

    wakeRenderServices(fetcher);

    expect(fetcher).toHaveBeenCalledTimes(12);
    expect(fetcher).toHaveBeenCalledWith("https://zeo-auth-user.onrender.com/healthz", {
      method: "GET",
      mode: "no-cors",
      cache: "no-store",
      keepalive: true,
    });
    expect(fetcher).toHaveBeenCalledWith("https://zeo-api-gateway.onrender.com/healthz", {
      method: "GET",
      mode: "no-cors",
      cache: "no-store",
      keepalive: true,
    });
    expect(fetcher).toHaveBeenCalledWith("https://zeo-bid-flusher.onrender.com/healthz", {
      method: "GET",
      mode: "no-cors",
      cache: "no-store",
      keepalive: true,
    });
    expect(renderServiceUrls).toHaveLength(12);
  });

  it("uses a ten-minute interval so active viewers keep Render services warm", () => {
    expect(RENDER_WAKE_INTERVAL_MS).toBe(10 * 60 * 1_000);
  });
});
