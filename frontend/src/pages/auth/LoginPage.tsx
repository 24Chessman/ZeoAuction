import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { ArrowRight, Eye, EyeOff, Lock, Mail } from "lucide-react";
import { useAuth } from "@/app/auth";
import { Banner, Button, Field, Input } from "@/components/ui";
import { useMocks } from "@/lib/config";
import { describeError } from "@/lib/errors";
import { AuthLayout } from "./AuthLayout";

export function LoginPage() {
  const { login, status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/auctions";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (status === "signed-in" && !busy) return <Navigate to={from} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (caught) {
      setError(caught);
      setBusy(false);
    }
  };

  const copy = error ? describeError(error) : null;

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Log in to bid, watch auctions live and manage your listings."
      footer={
        <>
          New to ZeoAuction?{" "}
          <Link to="/register" className="font-medium text-brand-ink hover:underline">Create an account</Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-5" noValidate>
        {copy && (
          <Banner tone="danger" title={copy.title} live>
            {copy.hint}
          </Banner>
        )}
        <Field label="Email">
          {(props) => (
            <Input {...props} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} leading={<Mail className="size-4" />} placeholder="you@example.com" />
          )}
        </Field>
        <Field label="Password">
          {(props) => (
            <Input
              {...props}
              type={show ? "text" : "password"}
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              leading={<Lock className="size-4" />}
              trailing={
                <button type="button" onClick={() => setShow((s) => !s)} className="mr-1 rounded-lg p-2 text-ink-faint hover:text-ink" aria-label={show ? "Hide password" : "Show password"}>
                  {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              }
            />
          )}
        </Field>
        <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!email || !password} iconRight={<ArrowRight className="size-4" />}>
          Log in
        </Button>
        {useMocks && (
          <div className="rounded-xl border border-dashed border-line-strong p-3 text-xs text-ink-muted">
            <p className="font-medium text-ink">Demo accounts</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {["buyer1@zeo.local", "seller@zeo.local", "unverified@zeo.local", "admin@zeo.local"].map((demo) => (
                <button
                  key={demo}
                  type="button"
                  onClick={() => {
                    setEmail(demo);
                    setPassword("zeo-dev-password");
                  }}
                  className="rounded-lg bg-surface-2 px-2 py-1 font-mono text-[11px] hover:bg-brand-soft hover:text-brand-ink"
                >
                  {demo.split("@")[0]}
                </button>
              ))}
            </div>
          </div>
        )}
      </form>
    </AuthLayout>
  );
}
