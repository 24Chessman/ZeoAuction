import type { Config } from "tailwindcss";

// Every color is a token defined in src/styles/index.css (light + dark). Components never use
// raw palette colors, so a theme change is a token change. Text pairs are checked for 4.5:1.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      white: "#ffffff",
      black: "#000000",
      canvas: token("canvas"),
      surface: { DEFAULT: token("surface"), 2: token("surface-2"), 3: token("surface-3") },
      ink: { DEFAULT: token("ink"), muted: token("ink-muted"), faint: token("ink-faint") },
      line: { DEFAULT: token("line"), strong: token("line-strong") },
      brand: {
        DEFAULT: token("brand"),
        strong: token("brand-strong"),
        soft: token("brand-soft"),
        ink: token("brand-ink"),
        on: token("on-brand"),
      },
      positive: { DEFAULT: token("positive"), soft: token("positive-soft") },
      live: { DEFAULT: token("live"), soft: token("live-soft") },
      danger: { DEFAULT: token("danger"), soft: token("danger-soft") },
      info: { DEFAULT: token("info"), soft: token("info-soft") },
    },
    fontFamily: {
      sans: ['"Geist Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
      mono: ['"Geist Mono Variable"', "ui-monospace", "SFMono-Regular", "monospace"],
    },
    extend: {
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
        display: ["clamp(2.5rem, 5.5vw, 4.5rem)", { lineHeight: "1.02", letterSpacing: "-0.035em" }],
        price: ["clamp(2.5rem, 4vw, 3.5rem)", { lineHeight: "1", letterSpacing: "-0.03em" }],
      },
      borderRadius: { xl: "0.875rem", "2xl": "1.125rem", "3xl": "1.5rem" },
      boxShadow: {
        card: "0 1px 2px rgb(var(--shadow) / 0.06), 0 1px 1px rgb(var(--shadow) / 0.04)",
        lift: "0 12px 32px -12px rgb(var(--shadow) / 0.22), 0 2px 6px rgb(var(--shadow) / 0.06)",
        glow: "0 0 0 1px rgb(var(--brand) / 0.25), 0 10px 40px -10px rgb(var(--brand) / 0.55)",
        focus: "0 0 0 3px rgb(var(--brand) / 0.35)",
      },
      maxWidth: { page: "76rem" },
      keyframes: {
        "fade-up": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        "price-flash": { "0%": { backgroundColor: "rgb(var(--positive) / 0.18)" }, "100%": { backgroundColor: "transparent" } },
        pulse: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        ping: { "75%,100%": { transform: "scale(2.2)", opacity: "0" } },
        shimmer: { from: { backgroundPosition: "200% 0" }, to: { backgroundPosition: "-200% 0" } },
        "toast-in": { from: { opacity: "0", transform: "translateY(12px) scale(.98)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: {
        "fade-up": "fade-up .35s cubic-bezier(.2,.7,.2,1) both",
        "price-flash": "price-flash 1.2s ease-out",
        "live-ping": "ping 1.6s cubic-bezier(0,0,.2,1) infinite",
        shimmer: "shimmer 1.6s linear infinite",
        "toast-in": "toast-in .25s cubic-bezier(.2,.7,.2,1) both",
      },
    },
  },
  plugins: [],
} satisfies Config;
