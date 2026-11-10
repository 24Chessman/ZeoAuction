import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, CheckCircle2, Mail } from "lucide-react";
import { authApi } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { Banner, Button, Field, Input } from "@/components/ui";
import { AuthLayout } from "./AuthLayout";

type State = "loading" | "success" | "error";

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";

  const [state, setState] = useState<State>("loading");
  const [verifiedEmail, setVerifiedEmail] = useState("");
  const [error, setError] = useState<unknown>(null);

  // Resend flow
  const [resendEmail, setResendEmail] = useState("");
  const [resendBusy, setResendBusy] = useState(false);
  const [resendDone, setResendDone] = useState(false);
  const [resendError, setResendError] = useState<unknown>(null);

  // Ref prevents duplicate executions in React StrictMode
  const executedTokenRef = useRef<string | null>(null);

  useEffect(() => {
    if (!token) {
      setState("error");
      return;
    }
    if (executedTokenRef.current === token) return;
    executedTokenRef.current = token;

    authApi
      .verifyEmail(token)
      .then((res) => {
        setVerifiedEmail(res.email);
        setState("success");
      })
      .catch((caught) => {
        setError(caught);
        setState("error");
      });
  }, [token]);

  const handleResend = async (event: FormEvent) => {
    event.preventDefault();
    setResendBusy(true);
    setResendError(null);
    try {
      await authApi.resendVerification(resendEmail.trim());
      setResendDone(true);
    } catch (caught) {
      setResendError(caught);
    } finally {
      setResendBusy(false);
    }
  };

  const errCopy = error ? describeError(error) : null;
  const resendErrCopy = resendError ? describeError(resendError) : null;

  return (
    <AuthLayout
      title="Verify your email"
      subtitle="Confirming your email address keeps your account secure."
      footer={
        <>
          Back to{" "}
          <Link to="/login" className="font-medium text-brand-ink hover:underline">
            Log in
          </Link>
        </>
      }
    >
      {state === "loading" && (
        <div className="flex flex-col items-center gap-4 py-8 text-ink-muted">
          <div className="size-8 animate-spin rounded-full border-2 border-brand border-t-transparent" />
          <p className="text-sm">Verifying your link…</p>
        </div>
      )}

      {state === "success" && (
        <div className="flex flex-col items-center gap-5 py-4 text-center">
          <div className="grid size-16 place-items-center rounded-full bg-positive/10">
            <CheckCircle2 className="size-8 text-positive" />
          </div>
          <div>
            <p className="text-lg font-semibold">Email verified!</p>
            {verifiedEmail && (
              <p className="mt-1 text-sm text-ink-muted">
                <span className="font-medium">{verifiedEmail}</span> is now confirmed.
              </p>
            )}
            <p className="mt-1 text-sm text-ink-muted">You can now log in to your account.</p>
          </div>
          <Link
            to="/login"
            className="inline-flex items-center gap-2 rounded-xl bg-midnight px-5 py-2.5 text-sm font-semibold text-brand hover:opacity-90"
          >
            Go to log in <ArrowRight className="size-4" />
          </Link>
        </div>
      )}

      {state === "error" && (
        <div className="space-y-5">
          {errCopy && (
            <Banner tone="danger" title={errCopy.title}>
              {errCopy.hint ?? errCopy.message}
            </Banner>
          )}
          {!errCopy && (
            <Banner tone="danger" title="Invalid or missing token">
              This verification link is invalid or has already been used.
            </Banner>
          )}

          <p className="text-sm text-ink-muted">
            Need a new verification link? Enter your email below.
          </p>

          {resendDone ? (
            <div className="space-y-3">
              <Banner tone="positive" title="Verification email sent">
                Check your inbox for a new link.
              </Banner>
            </div>
          ) : (
            <form onSubmit={handleResend} className="space-y-4">
              {resendErrCopy && (
                <Banner tone="danger" title={resendErrCopy.title}>
                  {resendErrCopy.hint ?? resendErrCopy.message}
                </Banner>
              )}
              <Field label="Your email address">
                {(props) => (
                  <Input
                    {...props}
                    type="email"
                    autoComplete="email"
                    required
                    value={resendEmail}
                    onChange={(e) => setResendEmail(e.target.value)}
                    leading={<Mail className="size-4" />}
                    placeholder="you@example.com"
                  />
                )}
              </Field>
              <Button
                type="submit"
                size="lg"
                className="w-full"
                loading={resendBusy}
                disabled={!resendEmail}
                iconRight={<ArrowRight className="size-4" />}
              >
                Resend verification email
              </Button>
            </form>
          )}
        </div>
      )}
    </AuthLayout>
  );
}
