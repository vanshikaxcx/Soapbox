import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ApiClient } from "./client";
import type { RequestTrace } from "./client";
import { useAuth } from "../auth/AuthContext";

const MAX_TRACES = 20;

interface ApiContextValue {
  client: ApiClient;
  traces: RequestTrace[];
}

const ApiContext = createContext<ApiContextValue | null>(null);

/**
 * One ApiClient per app, so no route copies server-derived state into a
 * second store (WP-03: "server state comes from the typed API client...
 * avoid copying it into multiple local stores"). Traces feed the diagnostic
 * bar; nothing else reads them, so a slow/dropped trace never affects a route.
 */
export function ApiProvider({ baseUrl, children }: { baseUrl: string; children: ReactNode }) {
  const { getAccessToken } = useAuth();
  const [traces, setTraces] = useState<RequestTrace[]>([]);

  // getAccessToken is a stable useCallback in AuthContext (memoized config,
  // storage, etc.), so this only reconstructs the client on a genuine auth
  // dependency change, not every render.
  const client = useMemo(
    () =>
      new ApiClient({
        baseUrl,
        accessToken: getAccessToken,
        onTrace: (trace) => setTraces((prev) => [trace, ...prev].slice(0, MAX_TRACES)),
      }),
    [baseUrl, getAccessToken],
  );

  const value = useMemo<ApiContextValue>(() => ({ client, traces }), [client, traces]);
  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

export function useApiClient(): ApiClient {
  const value = useContext(ApiContext);
  if (value === null) {
    throw new Error("useApiClient must be used within an ApiProvider.");
  }
  return value.client;
}

export function useDiagnosticTraces(): RequestTrace[] {
  const value = useContext(ApiContext);
  if (value === null) {
    throw new Error("useDiagnosticTraces must be used within an ApiProvider.");
  }
  return value.traces;
}
