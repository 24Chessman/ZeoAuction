/// <reference types="vitest" />
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { razorpayDevBridge } from "./dev/razorpayBridge";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig(({ mode }) => ({
  // RAZORPAY_* come from the repository's .env (git-ignored) and stay in the dev server process:
  // they are not VITE_-prefixed, so none of them reaches the bundle (ADR-0009).
  plugins: [react(), razorpayDevBridge(loadEnv(mode, repoRoot, "RAZORPAY_"))],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  // The settlement policy is read from config/ at build time, never copied (ADR-0011).
  // Bind IPv4 explicitly: on Windows "localhost" resolves to ::1 only, so http://127.0.0.1:5173 was refused.
  server: { host: "127.0.0.1", port: 5173, strictPort: true, fs: { allow: [repoRoot] } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/test/**", "src/**/*.test.{ts,tsx}", "src/vite-env.d.ts"],
      thresholds: { lines: 80, statements: 80, functions: 80, branches: 75 },
    },
  },
}));
