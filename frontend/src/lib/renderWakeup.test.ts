import { describe, expect, it, vi } from "vitest";
import { renderServiceUrls, wakeRenderServices } from "./renderWakeup";

describe("wakeRenderServices", () => {
  it("pings every deployed Render service without blocking", () => {
    const fetcher = vi.fn(() => Promise.resolve(new Response()));

    wakeRenderServices(fetcher);

    expect(fetcher).toHaveBeenCalledTimes(11);
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
    expect(renderServiceUrls).toHaveLength(11);
  });
});
