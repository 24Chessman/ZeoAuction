import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, Eye, EyeOff, KeyRound, Lock } from "lucide-react";
import { authApi } from "@/lib/api";
import { describeError, errorField } from "@/lib/errors";
import { Banner, Button, Field, Input, useToast } from "@/components/ui";
import { cn } from "@/lib/cn";
import { AuthLayout } from "./AuthLayout";

function passwordRules(password: string) {
  return {
    length: password.length >= 10 && password.length <= 128,
    mix: password.length > 0 && !/^[A-Za-z]+$/.test(password) && !/^\d+$/.test(password),
  };
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const toast = useToast();

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const rules = passwordRules(newPassword);

  const local = {
    new_password: !rules.length
      ? "Password must be 10 to 128 characters"
      : !rules.mix
        ? "Password must mix letters with digits or symbols"
        : null,
    confirm_password:
      confirmPassword.length > 0 && confirmPassword !== newPassword
        ? "Passwords do not match"
        : null,
  };

  const serverField = errorField(error);
  const serverCopy = error ? describeError(error) : null;
  const fieldError = (field: keyof typeof local) =>
    (submitted ? local[field] : null) ?? (serverField === field ? serverCopy?.message ?? null : null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (local.new_password || local.confirm_password) return;
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await authApi.resetPassword(token, newPassword);
      toast({ title: "Password updated", description: "You can now log in with your new password.", tone: "positive" });
      navigate("/login", { replace: true });
    } catch (caught) {
      setError(caught);
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <AuthLayout
        title="Reset password"
        subtitle="Set a new password for your account."
        footer={
          <Link to="/forgot-password" className="font-medium text-brand-ink hover:underline">
            Request a new reset link
          </Link>
        }
      >
        <Banner tone="danger" title="Invalid reset link">
          This link is missing a token. Please request a new password reset link.
        </Banner>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Reset password"
      subtitle="Choose a new password for your account."
      footer={
        <>
          Remember your password?{" "}
          <Link to="/login" className="font-medium text-brand-ink hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-5" noValidate>
        {serverCopy && !serverField && (
          <Banner tone="danger" title={serverCopy.title} live>
            {serverCopy.code === "INVALID_TOKEN" ? (
              <>
                {serverCopy.hint ?? serverCopy.message}{" "}
                <Link to="/forgot-password" className="font-medium underline">
                  Request a new link.
                </Link>
              </>
            ) : (
              serverCopy.hint ?? serverCopy.message
            )}
          </Banner>
        )}

        <Field label="New password" error={fieldError("new_password")}>
          {(props) => (
            <Input
              {...props}
              type={showNew ? "text" : "password"}
              autoComplete="new-password"
              required
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              leading={<Lock className="size-4" />}
              trailing={
                <button
                  type="button"
                  onClick={() => setShowNew((s) => !s)}
                  className="mr-1 rounded-lg p-2 text-ink-faint hover:text-ink"
                  aria-label={showNew ? "Hide password" : "Show password"}
                >
                  {showNew ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              }
            />
          )}
        </Field>

        <ul className="-mt-2 grid grid-cols-2 gap-2 text-xs" aria-label="Password requirements">
          <PasswordRule ok={rules.length}>10 or more characters</PasswordRule>
          <PasswordRule ok={rules.mix}>Letters plus digits or symbols</PasswordRule>
        </ul>

        <Field label="Confirm new password" error={fieldError("confirm_password")}>
          {(props) => (
            <Input
              {...props}
              type={showConfirm ? "text" : "password"}
              autoComplete="new-password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              leading={<KeyRound className="size-4" />}
              trailing={
                <button
                  type="button"
                  onClick={() => setShowConfirm((s) => !s)}
                  className="mr-1 rounded-lg p-2 text-ink-faint hover:text-ink"
                  aria-label={showConfirm ? "Hide password" : "Show password"}
                >
                  {showConfirm ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              }
            />
          )}
        </Field>

        <Button
          type="submit"
          size="lg"
          className="w-full font-semibold"
          loading={busy}
          disabled={!newPassword || !confirmPassword}
          iconRight={<ArrowRight className="size-4" />}
        >
          Set new password
        </Button>
      </form>
    </AuthLayout>
  );
}

function PasswordRule({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className={cn("flex items-center gap-1.5 transition-colors", ok ? "text-positive" : "text-ink-faint")}>
      <span className={cn("grid size-4 place-items-center rounded-full", ok ? "bg-positive text-white dark:text-canvas" : "bg-surface-3")}>
        <svg viewBox="0 0 10 10" className="size-2.5" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
          <polyline points="2,5 4,8 8,2" />
        </svg>
      </span>
      {children}
      <span className="sr-only">{ok ? "(met)" : "(not met)"}</span>
    </li>
  );
}
