import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, FlaskConical, LogOut, Menu, Moon, ShieldCheck, Sun, User, WifiOff, X } from "lucide-react";
import { useAuth } from "@/app/auth";
import { useConnectionStatus } from "@/app/live";
import { useTheme } from "@/app/theme";
import { ButtonLink, KycBadge } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useMocks } from "@/lib/config";
import { initials } from "@/lib/format";
import { policy } from "@/lib/policy";
import { Logo } from "./Logo";
import { MockControls } from "./MockControls";

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
          isActive ? "bg-surface-2 text-ink" : "text-ink-muted hover:bg-surface-2/70 hover:text-ink",
        )
      }
    >
      {children}
    </NavLink>
  );
}

function ConnectionDot() {
  const { status } = useConnectionStatus();
  if (status === "idle") return null;
  const map = {
    open: { label: "Live", cls: "bg-positive", ring: "bg-positive" },
    connecting: { label: "Connecting", cls: "bg-live", ring: "" },
    reconnecting: { label: "Reconnecting", cls: "bg-live", ring: "" },
    offline: { label: "Offline", cls: "bg-danger", ring: "" },
  } as const;
  const item = map[status];
  return (
    <span className="hidden items-center gap-2 rounded-full border border-line px-2.5 py-1 text-xs font-medium text-ink-muted md:inline-flex" title={`Real-time connection: ${item.label}`}>
      <span className="relative flex size-2">
        {item.ring && <span className={cn("absolute inline-flex size-full animate-live-ping rounded-full opacity-60", item.ring)} />}
        <span className={cn("relative inline-flex size-2 rounded-full", item.cls)} />
      </span>
      {item.label}
    </span>
  );
}

function ThemeToggle() {
  const [theme, toggle] = useTheme();
  return (
    <button
      onClick={toggle}
      className="grid size-9 place-items-center rounded-xl text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
    >
      {theme === "dark" ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
    </button>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const esc = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  if (!user) return null;
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-xl py-1 pl-1 pr-2 transition-colors hover:bg-surface-2"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-brand to-info text-xs font-semibold text-white">
          {initials(user.display_name)}
        </span>
        <span className="hidden max-w-32 truncate text-sm font-medium sm:block">{user.display_name}</span>
        <ChevronDown className="size-4 text-ink-faint" aria-hidden />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-40 mt-2 w-64 overflow-hidden rounded-2xl border border-line bg-surface p-1.5 shadow-lift animate-fade-up">
          <div className="px-3 py-2.5">
            <p className="truncate text-sm font-semibold">{user.display_name}</p>
            <p className="truncate text-xs text-ink-faint">{user.email}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <KycBadge status={user.kyc_status} />
              {user.role === "ADMIN" && <span className="inline-flex h-6 items-center rounded-full bg-ink px-2.5 text-xs font-medium text-canvas">Admin</span>}
            </div>
          </div>
          <div className="my-1 h-px bg-line" />
          <Link role="menuitem" to="/account" onClick={() => setOpen(false)} className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-ink-muted hover:bg-surface-2 hover:text-ink">
            <User className="size-4" aria-hidden /> Account and orders
          </Link>
          <Link role="menuitem" to="/sell/verify" onClick={() => setOpen(false)} className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-ink-muted hover:bg-surface-2 hover:text-ink">
            <ShieldCheck className="size-4" aria-hidden /> Seller verification
          </Link>
          <button
            role="menuitem"
            onClick={async () => {
              setOpen(false);
              await logout();
              navigate("/");
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm text-ink-muted hover:bg-surface-2 hover:text-danger"
          >
            <LogOut className="size-4" aria-hidden /> Log out
          </button>
        </div>
      )}
    </div>
  );
}

function SimulationStrip() {
  return (
    <div className="border-b border-line bg-surface-2/60 text-[12px] text-ink-muted">
      <div className="mx-auto flex max-w-page items-center justify-center gap-2 px-4 py-1.5 text-center sm:px-6">
        <FlaskConical className="size-3.5 shrink-0 text-brand-ink" aria-hidden />
        <span>
          Test mode: payments are not real and escrow is simulated.{useMocks && " You're viewing synthetic demo data."}
        </span>
      </div>
    </div>
  );
}

function OfflineBar() {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  if (online) return null;
  return (
    <div className="bg-danger text-white dark:text-canvas" role="alert">
      <div className="mx-auto flex max-w-page items-center gap-2 px-4 py-2 text-sm font-medium sm:px-6">
        <WifiOff className="size-4" aria-hidden /> You're offline. Prices will resume when the connection returns.
      </div>
    </div>
  );
}

export function AppShell() {
  const { user, status } = useAuth();
  const [menu, setMenu] = useState(false);
  const location = useLocation();
  useEffect(() => {
    setMenu(false);
  }, [location.pathname]);

  const links = (
    <>
      <NavItem to="/auctions">Auctions</NavItem>
      <NavItem to="/sell">Sell</NavItem>
      {user?.role === "ADMIN" && <NavItem to="/admin/kyc">Review queue</NavItem>}
    </>
  );

  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[70] focus:rounded-lg focus:bg-surface focus:px-4 focus:py-2 focus:shadow-lift">
        Skip to content
      </a>
      <SimulationStrip />
      <OfflineBar />
      <header className="sticky top-0 z-30 border-b border-line/80 bg-canvas/75 backdrop-blur-xl backdrop-saturate-150">
        <div className="mx-auto flex h-16 max-w-page items-center gap-4 px-4 sm:px-6">
          <Logo />
          <nav className="ml-4 hidden items-center gap-1 md:flex" aria-label="Main">
            {links}
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            <ConnectionDot />
            <ThemeToggle />
            {status === "signed-in" ? (
              <UserMenu />
            ) : status === "signed-out" ? (
              <div className="hidden items-center gap-1.5 sm:flex">
                <ButtonLink to="/login" variant="ghost" size="sm">Log in</ButtonLink>
                <ButtonLink to="/register" size="sm">Create account</ButtonLink>
              </div>
            ) : null}
            <button className="grid size-9 place-items-center rounded-xl text-ink-muted hover:bg-surface-2 md:hidden" onClick={() => setMenu((m) => !m)} aria-label="Menu" aria-expanded={menu}>
              {menu ? <X className="size-5" /> : <Menu className="size-5" />}
            </button>
          </div>
        </div>
        {menu && (
          <nav className="flex flex-col gap-1 border-t border-line px-4 py-3 md:hidden" aria-label="Mobile">
            {links}
            {status === "signed-out" && (
              <div className="mt-2 grid grid-cols-2 gap-2">
                <ButtonLink to="/login" variant="secondary">Log in</ButtonLink>
                <ButtonLink to="/register">Create account</ButtonLink>
              </div>
            )}
          </nav>
        )}
      </header>

      <main id="main" className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-page flex-col gap-3 px-4 py-8 text-sm text-ink-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="flex items-center gap-2.5">
            <Logo className="scale-90" />
          </div>
          <p>
            Coursework simulation · M.Sc. IT semester 3, 2026 · Fee policy {policy.feeVersion}
          </p>
        </div>
      </footer>
      {useMocks && <MockControls />}
    </div>
  );
}
