import { useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";
import { ArrowRight, Check, CheckCircle2, Eye, EyeOff, Lock, Mail, UserRound } from "lucide-react";
import { useAuth } from "@/app/auth";
import { Banner, Button, Field, Input } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useMocks } from "@/lib/config";
import { describeError, errorField } from "@/lib/errors";
import { AuthLayout } from "./AuthLayout";

/** The auth-user service's rules (app/domain/users.py), mirrored, not invented. */
export function passwordRules(password: string) {
  return {
    length: password.length >= 10 && password.length <= 128,
    mix: password.length > 0 && !/^[A-Za-z]+$/.test(password) && !/^\d+$/.test(password),
  };
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function RegisterPage() {
  const { register, status } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [registeredDone, setRegisteredDone] = useState(false);

  if (status === "signed-in" && !busy) return <Navigate to="/auctions" replace />;

  const rules = passwordRules(password);
  const local = {
    display_name: name.trim().length === 0 ? "Enter a display name" : name.trim().length > 80 ? "Display name must be 1 to 80 characters" : null,
    email: !EMAIL.test(email.trim()) ? "Enter a valid email address" : null,
    password: !rules.length ? "Password must be 10 to 128 characters" : !rules.mix ? "Password must mix letters with digits or symbols" : null,
  };
  const serverField = errorField(error);
  const serverCopy = error ? describeError(error) : null;
  const fieldError = (field: keyof typeof local) =>
    (submitted ? local[field] : null) ?? (serverField === field ? serverCopy?.message ?? null : null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (local.display_name || local.email || local.password) return;
    setBusy(true);
    setError(null);
    try {
      await register({ email: email.trim(), password, display_name: name.trim() });
      setRegisteredDone(true);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Bid on anything listed. No identity check needed until you want to sell."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-brand-ink hover:underline">Log in</Link>
        </>
      }
    >
      {registeredDone ? (
        <div className="flex flex-col items-center gap-5 py-4 text-center">
          <div className="grid size-16 place-items-center rounded-full bg-positive/10">
            <CheckCircle2 className="size-8 text-positive" />
          </div>
          <div>
            <p className="text-lg font-semibold">Verify your email address</p>
            <p className="mt-1.5 text-sm text-ink-muted">
              We've sent a verification link to <span className="font-semibold text-ink">{email}</span>.
              Please click the link in your email to verify your account before logging in.
            </p>
          </div>

          <div className="flex w-full flex-col gap-2 pt-2">
            <Link
              to="/login"
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-midnight py-2.5 text-sm font-semibold text-brand hover:opacity-90"
            >
              Go to log in <ArrowRight className="size-4" />
            </Link>
          </div>
        </div>
      ) : (
        <>
          {!useMocks && (
            <div className="mb-5 rounded-2xl border border-brand/20 bg-brand-soft/50 p-3.5 text-xs text-brand-ink flex items-center justify-between gap-3">
              <div>
                <p className="font-semibold">Email OTP Login Available</p>
                <p className="text-ink-muted">Sign up and log in passwordlessly with a 6-digit email code.</p>
              </div>
              <Link
                to="/login"
                className="shrink-0 inline-flex items-center gap-1 rounded-xl bg-midnight px-3 py-1.5 text-xs font-semibold text-brand hover:opacity-90"
              >
                Use Email OTP <ArrowRight className="size-3" />
              </Link>
            </div>
          )}

          <form onSubmit={submit} className="space-y-5" noValidate>
            {serverCopy && !serverField && (
              <Banner tone="danger" title={serverCopy.title} live>
                {serverCopy.code === "EMAIL_ALREADY_REGISTERED" ? (
                  <>
                    Try <Link to="/login" className="font-medium text-brand-ink underline">logging in</Link> instead.
                  </>
                ) : (
                  serverCopy.hint
                )}
              </Banner>
            )}
            <Field label="Display name" hint="Shown on your account. Bidders always appear under a nickname." error={fieldError("display_name")}>
              {(props) => <Input {...props} autoComplete="nickname" value={name} onChange={(e) => setName(e.target.value)} leading={<UserRound className="size-4" />} placeholder="Alex" />}
            </Field>
            <Field label="Email" error={fieldError("email")}>
              {(props) => <Input {...props} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} leading={<Mail className="size-4" />} placeholder="you@example.com" />}
            </Field>
            <Field label="Password" error={fieldError("password")}>
              {(props) => (
                <Input
                  {...props}
                  type={show ? "text" : "password"}
                  autoComplete="new-password"
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
            <ul className="-mt-2 grid grid-cols-2 gap-2 text-xs" aria-label="Password requirements">
              <Rule ok={rules.length}>10 or more characters</Rule>
              <Rule ok={rules.mix}>Letters plus digits or symbols</Rule>
            </ul>

            <Button type="submit" size="lg" className="w-full" loading={busy} iconRight={<ArrowRight className="size-4" />}>
              Create account
            </Button>
          </form>
        </>
      )}
    </AuthLayout>
  );
}

function Rule({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className={cn("flex items-center gap-1.5 transition-colors", ok ? "text-positive" : "text-ink-faint")}>
      <span className={cn("grid size-4 place-items-center rounded-full", ok ? "bg-positive text-white dark:text-canvas" : "bg-surface-3")}>
        <Check className="size-2.5" strokeWidth={3} aria-hidden />
      </span>
      {children}
      <span className="sr-only">{ok ? "(met)" : "(not met)"}</span>
    </li>
  );
}
