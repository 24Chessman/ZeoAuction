import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { ArrowRight, CheckCircle2, Eye, EyeOff, KeyRound, Lock, Mail, Sparkles } from "lucide-react";
import { useAuth } from "@/app/auth";
import { authApi } from "@/lib/api";
import { Banner, Button, Field, Input } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useMocks } from "@/lib/config";
import { describeError } from "@/lib/errors";
import { AuthLayout } from "./AuthLayout";

type AuthMode = "gmail" | "password";

export function LoginPage() {
  const { login, sendGmailOtp, loginWithGmailOtp, status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/auctions";

  const [mode, setMode] = useState<AuthMode>(useMocks ? "password" : "gmail");
  const activeMode = useMocks ? "password" : mode;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [resending, setResending] = useState(false);
  const [resendMessage, setResendMessage] = useState<string | null>(null);

  if (status === "signed-in" && !busy) return <Navigate to={from} replace />;

  const handleResendVerification = async () => {
    if (!email.trim()) return;
    setResending(true);
    setResendMessage(null);
    try {
      await authApi.resendVerification(email.trim());
      setResendMessage("Verification email sent! Check your inbox.");
    } catch {
      setResendMessage("Failed to send verification email. Try again later.");
    } finally {
      setResending(false);
    }
  };

  const submitPassword = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setResendMessage(null);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (caught) {
      setError(caught);
      setBusy(false);
    }
  };

  const handleSendOtp = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await sendGmailOtp(email.trim());
      setOtpSent(true);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handleVerifyOtp = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !otp.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await loginWithGmailOtp(email.trim(), otp.trim());
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
          <Link to="/register" className="font-medium text-brand-ink hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      {/* Auth Method Switcher (Live / Prod Mode Only) */}
      {!useMocks && (
        <div className="mb-6 grid grid-cols-2 gap-1 rounded-2xl border border-line bg-surface p-1 shadow-card">
          <button
            type="button"
            onClick={() => {
              setMode("gmail");
              setError(null);
            }}
            className={cn(
              "flex items-center justify-center gap-2 rounded-xl py-2 text-xs font-semibold transition-all",
              activeMode === "gmail"
                ? "bg-midnight text-brand shadow-lift"
                : "text-ink-muted hover:text-ink"
            )}
          >
            <Mail className="size-3.5" />
            Gmail OTP
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("password");
              setError(null);
            }}
            className={cn(
              "flex items-center justify-center gap-2 rounded-xl py-2 text-xs font-semibold transition-all",
              activeMode === "password"
                ? "bg-midnight text-brand shadow-lift"
                : "text-ink-muted hover:text-ink"
            )}
          >
            <KeyRound className="size-3.5" />
            Password
          </button>
        </div>
      )}

      {copy && (
        <div className="mb-5 space-y-3">
          <Banner tone="danger" title={copy.title} live>
            {copy.hint ?? copy.message}
          </Banner>
          {copy.code === "EMAIL_NOT_VERIFIED" && (
            <div className="rounded-xl border border-line bg-surface-2 p-3 text-xs text-ink-muted flex flex-col gap-2">
              <p>Didn't receive the verification email or link expired?</p>
              <div className="flex items-center gap-3">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  loading={resending}
                  onClick={handleResendVerification}
                >
                  Resend verification email
                </Button>
                {resendMessage && <span className="text-positive font-medium">{resendMessage}</span>}
              </div>
            </div>
          )}
        </div>
      )}

      {activeMode === "gmail" ? (
        !otpSent ? (
          <form onSubmit={handleSendOtp} className="space-y-5" noValidate>
            <div className="rounded-xl border border-brand/20 bg-brand-soft/40 p-3 text-xs text-brand-ink">
              <p className="font-semibold flex items-center gap-1.5">
                <Sparkles className="size-3.5" /> Gmail Login
              </p>
              <p className="mt-0.5 text-ink-muted">
                Enter your Gmail or email address. We will send a secure 6-digit code via Gmail SMTP.
              </p>
            </div>

            <Field label="Gmail or Email Address">
              {(props) => (
                <Input
                  {...props}
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  leading={<Mail className="size-4" />}
                  placeholder="you@gmail.com"
                />
              )}
            </Field>

            <Button
              type="submit"
              size="lg"
              className="w-full font-semibold"
              loading={busy}
              disabled={!email}
              iconRight={<ArrowRight className="size-4" />}
            >
              Send Login Code
            </Button>
          </form>
        ) : (
          <form onSubmit={handleVerifyOtp} className="space-y-5" noValidate>
            <div className="rounded-xl border border-positive/30 bg-positive-soft/40 p-3 text-xs text-positive-ink">
              <p className="font-semibold flex items-center gap-1.5">
                <CheckCircle2 className="size-3.5 text-positive" /> Code Sent to {email}
              </p>
              <p className="mt-0.5 text-ink-muted">
                Enter the 6-digit code from your email to log in.
              </p>
            </div>

            <Field label="6-Digit Verification Code">
              {(props) => (
                <Input
                  {...props}
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                  maxLength={6}
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  placeholder="123456"
                  className="font-mono text-center tracking-widest text-lg"
                />
              )}
            </Field>

            <div className="flex gap-2">
              <Button
                type="button"
                variant="secondary"
                size="lg"
                className="w-1/3"
                onClick={() => setOtpSent(false)}
              >
                Back
              </Button>
              <Button
                type="submit"
                size="lg"
                className="w-2/3 font-semibold"
                loading={busy}
                disabled={otp.length !== 6}
                iconRight={<ArrowRight className="size-4" />}
              >
                Verify & Log in
              </Button>
            </div>

            <p className="text-center text-xs text-ink-faint">
              Didn't receive it?{" "}
              <button
                type="button"
                onClick={handleSendOtp}
                className="font-semibold text-brand-ink underline"
                disabled={busy}
              >
                Resend code
              </button>
            </p>
          </form>
        )
      ) : (
        <form onSubmit={submitPassword} className="space-y-5" noValidate>
          <Field label="Email">
            {(props) => (
              <Input
                {...props}
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                leading={<Mail className="size-4" />}
                placeholder="you@example.com"
              />
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
                  <button
                    type="button"
                    onClick={() => setShow((s) => !s)}
                    className="mr-1 rounded-lg p-2 text-ink-faint hover:text-ink"
                    aria-label={show ? "Hide password" : "Show password"}
                  >
                    {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                }
              />
            )}
          </Field>
          <div className="flex justify-end -mt-2">
            <Link to="/forgot-password" className="text-xs text-brand-ink hover:underline">
              Forgot your password?
            </Link>
          </div>
          <Button
            type="submit"
            size="lg"
            className="w-full font-semibold"
            loading={busy}
            disabled={!email || !password}
            iconRight={<ArrowRight className="size-4" />}
          >
            Log in with Password
          </Button>
        </form>
      )}

      {useMocks && (
        <div className="mt-6 rounded-xl border border-dashed border-line-strong p-3 text-xs text-ink-muted">
          <p className="font-medium text-ink">Demo accounts</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {["buyer1@zeo.local", "seller@zeo.local", "unverified@zeo.local", "admin@zeo.local"].map((demo) => (
              <button
                key={demo}
                type="button"
                onClick={() => {
                  setEmail(demo);
                  setPassword("zeo-dev-password");
                  setMode("password");
                }}
                className="rounded-lg bg-surface-2 px-2 py-1 font-mono text-[11px] hover:bg-brand-soft hover:text-brand-ink"
              >
                {demo.split("@")[0]}
              </button>
            ))}
          </div>
        </div>
      )}
    </AuthLayout>
  );
}
