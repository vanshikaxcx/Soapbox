import { ApiProvider } from "./api/ApiProvider";
import { AuthProvider, type AuthProviderDeps } from "./auth/AuthContext";
import { AppRouter } from "./pages/router";

const API_BASE_URL: string = (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "/api";

export interface AppProps {
  /** Test-only seam: overrides Cognito config/fetch/storage/redirect without touching real env/network. */
  authDeps?: AuthProviderDeps;
  apiBaseUrl?: string;
}

export function App({ authDeps, apiBaseUrl }: AppProps = {}) {
  return (
    <AuthProvider deps={authDeps}>
      <ApiProvider baseUrl={apiBaseUrl ?? API_BASE_URL}>
        <AppRouter />
      </ApiProvider>
    </AuthProvider>
  );
}
