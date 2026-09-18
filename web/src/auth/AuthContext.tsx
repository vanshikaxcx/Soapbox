import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  buildAuthorizeUrl,
  buildLogoutUrl,
  exchangeAuthorizationCode,
  refreshTokens,
  type FetchLike,
} from "./cognitoClient";
import { loadCognitoConfig, type CognitoConfig } from "./cognitoConfig";
import {
  base64UrlDecode,
  consumePendingAuthorization,
  generateCodeChallenge,
  generateCodeVerifier,
  generateState,
  storePendingAuthorization,
  type PkceCrypto,
} from "./pkce";
import { clearTokens, isExpired, readTokens, writeTokens, type StoredTokens } from "./tokens";

export type AuthStatus =
  | "loading"
  /** No session and none was ever established this visit. */
  | "unauthenticated"
  /** A session existed but its refresh token no longer works - distinct copy/redirect from a fresh visit. */
  | "expired"
  | "authenticated";

export interface AuthUser {
  sub: string;
  email: string | undefined;
}

export interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  /** Resolved per API request; refreshes the token if it's about to lapse. Returns null when unauthenticated. */
  getAccessToken: () => Promise<string | null>;
  login: (returnTo?: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export interface AuthProviderDeps {
  config?: CognitoConfig;
  fetchImpl?: FetchLike;
  pkce?: PkceCrypto;
  storage?: Storage;
  now?: () => number;
  location?: Pick<Location, "search" | "pathname">;
  navigate?: (path: string) => void;
  redirect?: (url: string) => void;
}

function defaultNavigate(path: string): void {
  window.history.replaceState(null, "", path);
}

function defaultRedirect(url: string): void {
  window.location.assign(url);
}

function decodeIdToken(idToken: string): AuthUser | null {
  const [, payload] = idToken.split(".");
  if (payload === undefined) {
    return null;
  }
  try {
    const claims = JSON.parse(base64UrlDecode(payload)) as { sub?: unknown; email?: unknown };
    if (typeof claims.sub !== "string") {
      return null;
    }
    return { sub: claims.sub, email: typeof claims.email === "string" ? claims.email : undefined };
  } catch {
    return null;
  }
}

export function AuthProvider({
  children,
  deps = {},
}: {
  children: ReactNode;
  deps?: AuthProviderDeps | undefined;
}) {
  // Memoized: loadCognitoConfig() builds a fresh object every call, and an
  // unstable config identity would defeat downstream consumers (ApiProvider)
  // that key a memoized value off it.
  const config = useMemo(() => deps.config ?? loadCognitoConfig(), [deps.config]);
  const fetchImpl = deps.fetchImpl ?? fetch;
  const pkce = deps.pkce;
  const storage = deps.storage ?? sessionStorage;
  const now = deps.now ?? Date.now;
  const location = deps.location ?? window.location;
  const navigate = deps.navigate ?? defaultNavigate;
  const redirect = deps.redirect ?? defaultRedirect;

  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const tokensRef = useRef<StoredTokens | null>(null);
  const refreshInFlight = useRef<Promise<StoredTokens | null> | null>(null);
  const initStartedRef = useRef(false);

  const applyTokens = useCallback(
    (tokens: StoredTokens) => {
      tokensRef.current = tokens;
      writeTokens(tokens, storage);
      setUser(decodeIdToken(tokens.idToken));
      setStatus("authenticated");
    },
    [storage],
  );

  const clearSession = useCallback(
    (nextStatus: AuthStatus) => {
      tokensRef.current = null;
      clearTokens(storage);
      setUser(null);
      setStatus(nextStatus);
    },
    [storage],
  );

  useEffect(() => {
    // consumePendingAuthorization is a one-shot delete-on-read: under
    // StrictMode's dev-only double-invoke, a second call would find the
    // record already consumed and wrongly clear a session mid-callback.
    if (initStartedRef.current) {
      return;
    }
    initStartedRef.current = true;

    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    const state = params.get("state");

    async function init(): Promise<void> {
      if (code !== null && state !== null) {
        const pending = consumePendingAuthorization(storage);
        if (pending === null || pending.state !== state) {
          clearSession("unauthenticated");
          return;
        }
        try {
          const tokens = await exchangeAuthorizationCode(config, code, pending.codeVerifier, fetchImpl, now);
          applyTokens(tokens);
          navigate(pending.returnTo);
        } catch {
          clearSession("unauthenticated");
        }
        return;
      }

      const existing = readTokens(storage);
      if (existing === null) {
        setStatus("unauthenticated");
        return;
      }
      if (!isExpired(existing, now)) {
        tokensRef.current = existing;
        setUser(decodeIdToken(existing.idToken));
        setStatus("authenticated");
        return;
      }
      if (existing.refreshToken === null) {
        clearSession("expired");
        return;
      }
      try {
        const refreshed = await refreshTokens(config, existing.refreshToken, fetchImpl, now);
        applyTokens(refreshed);
      } catch {
        clearSession("expired");
      }
    }

    void init();
    // Runs once per mount; callback/refresh outcomes drive state from here on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const current = tokensRef.current;
    if (current === null) {
      return null;
    }
    if (!isExpired(current, now)) {
      return current.accessToken;
    }
    if (current.refreshToken === null) {
      clearSession("expired");
      return null;
    }
    if (refreshInFlight.current === null) {
      refreshInFlight.current = refreshTokens(config, current.refreshToken, fetchImpl, now)
        .then((tokens) => {
          applyTokens(tokens);
          return tokens;
        })
        .catch(() => {
          clearSession("expired");
          return null;
        })
        .finally(() => {
          refreshInFlight.current = null;
        });
    }
    const refreshed = await refreshInFlight.current;
    return refreshed?.accessToken ?? null;
  }, [applyTokens, clearSession, config, fetchImpl, now]);

  const login = useCallback(
    (returnTo?: string) => {
      const verifier = generateCodeVerifier(pkce);
      const state = generateState(pkce);
      storePendingAuthorization(
        { codeVerifier: verifier, state, returnTo: returnTo ?? location.pathname },
        storage,
      );
      void generateCodeChallenge(verifier, pkce).then((codeChallenge) => {
        redirect(buildAuthorizeUrl(config, { codeChallenge, state }));
      });
    },
    [config, location.pathname, pkce, redirect, storage],
  );

  const logout = useCallback(() => {
    clearSession("unauthenticated");
    redirect(buildLogoutUrl(config));
  }, [clearSession, config, redirect]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, getAccessToken, login, logout }),
    [status, user, getAccessToken, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used within an AuthProvider.");
  }
  return value;
}
