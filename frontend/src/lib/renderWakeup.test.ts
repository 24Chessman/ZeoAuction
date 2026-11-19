import { describe, expect, it, vi } from "vitest";
import { renderServiceUrls, wakeRenderServices } from "./renderWakeup";

describe("wakeRenderServices", () => {
  it("pings every deployed Render service without blocking", () => {
    const fetcher = vi.fn(() => Promise.resolve(new Response()));

    wakeRenderServices(fetcher);

    expect(fetcher).toHaveBeenCalledTimes(10);
    expect(fetcher).toHaveBeenCalledWith("https://zeo-auth-user.onrender.com", {
      method: "GET",
      mode: "no-cors",
      keepalive: true,
    });
    expect(renderServiceUrls).toHaveLength(10);
  });
});
