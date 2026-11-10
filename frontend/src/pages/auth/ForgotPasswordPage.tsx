import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, Mail } from "lucide-react";
import { authApi } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { Banner, Button, Field, Input } from "@/components/ui";
import { AuthLayout } from "./AuthLayout";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.forgotPassword(email.trim());
      setSent(true);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  const errCopy = error ? describeError(error) : null;

  return (
    <AuthLayout
      title="Forgot password"
      subtitle="Enter your email and we'll send you a link to reset your password."
      footer={
        <>
          Remember your password?{" "}
          <Link to="/login" className="font-medium text-brand-ink hover:underline">
            Log in
          </Link>
        </>
      }
    >
      {sent ? (
        <div className="flex flex-col items-center gap-5 py-4 text-center">
          <div className="grid size-16 place-items-center rounded-full bg-positive/10">
            <CheckCircle2 className="size-8 text-positive" />
          </div>
          <div>
            <p className="text-lg font-semibold">Check your inbox</p>
            <p className="mt-1 text-sm text-ink-muted">
              If <span className="font-medium">{email}</span> has an account, we've sent a password
              reset link. It expires in 1 hour.
            </p>
          </div>

          <button
            type="button"
            onClick={() => {
              setSent(false);
            }}
            className="text-sm text-brand-ink underline"
          >
            Try a different email
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-5" noValidate>
          {errCopy && (
            <Banner tone="danger" title={errCopy.title} live>
              {errCopy.hint ?? errCopy.message}
            </Banner>
          )}

          <Field label="Email address">
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

          <Button
            type="submit"
            size="lg"
            className="w-full font-semibold"
            loading={busy}
            disabled={!email}
            iconRight={<ArrowRight className="size-4" />}
          >
            Send reset link
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
