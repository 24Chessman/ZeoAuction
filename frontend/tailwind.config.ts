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
      gold: { DEFAULT: token("gold"), soft: token("gold-soft") },
      info: { DEFAULT: token("info"), soft: token("info-soft") },
      night: { DEFAULT: token("night"), 2: token("night-2") },
    },
    fontFamily: {
      sans: ['"Plus Jakarta Sans Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
      display: ['"Bricolage Grotesque Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
      mono: ['"Geist Mono Variable"', "ui-monospace", "SFMono-Regular", "monospace"],
    },
    extend: {
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
        display: ["clamp(2.75rem, 6.5vw, 5.75rem)", { lineHeight: "0.95", letterSpacing: "-0.035em" }],
        price: ["clamp(2.5rem, 4vw, 3.25rem)", { lineHeight: "1", letterSpacing: "-0.03em" }],
      },
      borderRadius: { lg: "0.5rem", xl: "0.75rem", "2xl": "1rem", "3xl": "1.5rem", "4xl": "2rem" },
      // Soft, layered shadows tinted with the ink color rather than flat grey.
      boxShadow: {
        card: "0 1px 2px rgb(var(--shadow) / 0.05), 0 1px 1px rgb(var(--shadow) / 0.03)",
        lift: "0 24px 48px -18px rgb(var(--shadow) / 0.25), 0 6px 14px -6px rgb(var(--shadow) / 0.08)",
        float: "0 40px 80px -24px rgb(var(--shadow) / 0.45), 0 12px 24px -12px rgb(var(--shadow) / 0.2)",
        glow: "0 12px 28px -10px rgb(var(--brand) / 0.55)",
        focus: "0 0 0 3px rgb(var(--brand) / 0.3)",
      },
      maxWidth: { page: "78rem" },
      keyframes: {
        "fade-up": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
        "price-flash": { "0%": { backgroundColor: "rgb(var(--positive) / 0.18)" }, "100%": { backgroundColor: "transparent" } },
        pulse: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        ping: { "75%,100%": { transform: "scale(2.2)", opacity: "0" } },
        shimmer: { from: { backgroundPosition: "200% 0" }, to: { backgroundPosition: "-200% 0" } },
        "toast-in": { from: { opacity: "0", transform: "translateY(12px) scale(.98)" }, to: { opacity: "1", transform: "none" } },
        marquee: { from: { transform: "translateX(0)" }, to: { transform: "translateX(-50%)" } },
        float: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-8px)" } },
      },
      animation: {
        "fade-up": "fade-up .45s cubic-bezier(.2,.7,.2,1) both",
        "price-flash": "price-flash 1.2s ease-out",
        "live-ping": "ping 1.6s cubic-bezier(0,0,.2,1) infinite",
        shimmer: "shimmer 1.6s linear infinite",
        "toast-in": "toast-in .25s cubic-bezier(.2,.7,.2,1) both",
        marquee: "marquee 48s linear infinite",
        float: "float 7s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
