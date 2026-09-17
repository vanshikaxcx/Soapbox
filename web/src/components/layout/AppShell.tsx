import { Link, Outlet } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { DiagnosticBar } from "./DiagnosticBar";

/** The authenticated shell: header/nav/diagnostic-bar around every protected route. */
export function AppShell() {
  const { status, user, logout } = useAuth();

  return (
    <div className="pp-shell">
      <a href="#pp-main" className="pp-skip-link">
        Skip to main content
      </a>
      <header className="pp-shell__header">
        <Link to="/" className="pp-shell__brand">
          ProofPath
        </Link>
        <nav aria-label="Primary">
          <Link to="/">Home</Link>
          <Link to="/demo">Demo</Link>
        </nav>
        {status === "authenticated" && (
          <div className="pp-shell__account">
            {user?.email !== undefined && <span>{user.email}</span>}
            <button type="button" className="pp-button pp-button--secondary" onClick={logout}>
              Sign out
            </button>
          </div>
        )}
      </header>
      <main id="pp-main" tabIndex={-1}>
        <Outlet />
      </main>
      <DiagnosticBar />
    </div>
  );
}
