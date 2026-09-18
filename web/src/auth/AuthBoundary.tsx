import type { ReactNode } from "react";
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";

/**
 * Wraps every authenticated route. Redirects to Cognito hosted UI on both
 * "unauthenticated" and "expired" - but `login()` is called with the copy
 * distinguished at the call site so an expired session can show a
 * "your session ended" notice before the redirect (WP-03 logout/expired-session behavior).
 */
export function AuthBoundary({ children }: { children: ReactNode }) {
  const { status, login } = useAuth();
  const location = useLocation();
  const returnTo = `${location.pathname}${location.search}`;

  useEffect(() => {
    if (status === "unauthenticated" || status === "expired") {
      login(returnTo);
    }
  }, [status, login, returnTo]);

  if (status === "loading") {
    return (
      <div role="status" aria-live="polite" className="pp-boundary-loading">
        Checking your session…
      </div>
    );
  }
  if (status === "unauthenticated" || status === "expired") {
    return (
      <div role="status" aria-live="polite" className="pp-boundary-loading">
        {status === "expired"
          ? "Your session ended. Redirecting you to sign in…"
          : "Redirecting you to sign in…"}
      </div>
    );
  }
  return <>{children}</>;
}
