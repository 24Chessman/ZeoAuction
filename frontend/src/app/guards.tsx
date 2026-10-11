import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import { ButtonLink, EmptyState, Spinner } from "@/components/ui";
import { useAuth } from "./auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") {
    return (
      <div className="grid min-h-[50vh] place-items-center text-ink-faint">
        <Spinner label="Restoring your session" />
      </div>
    );
  }
  if (status === "signed-out") return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <>{children}</>;
}

/** The UI hides admin screens from non-admins; the services enforce it with 403 FORBIDDEN. */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return (
    <RequireAuth>
      {user?.role === "ADMIN" ? (
        children
      ) : (
        <div className="mx-auto max-w-page px-4 py-16 sm:px-6">
          <EmptyState icon={<ShieldAlert className="size-5" />} title="Administrators only" action={<ButtonLink to="/" variant="secondary">Go home</ButtonLink>}>
            This area needs the ADMIN role.
          </EmptyState>
        </div>
      )}
    </RequireAuth>
  );
}
