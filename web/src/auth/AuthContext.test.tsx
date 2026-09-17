import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth, type AuthProviderDeps } from "./AuthContext";
import type { CognitoConfig } from "./cognitoConfig";
import { writeTokens, type StoredTokens } from "./tokens";
import { fakeStorage } from "../test/fakeStorage";

const config: CognitoConfig = {
  domain: "auth.example.invalid",
  clientId: "client-123",
  redirectUri: "https://app.example.invalid/",
  logoutUri: "https://app.example.invalid/",
  scopes: ["openid", "email"],
};

function Probe() {
  const { status, user } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="email">{user?.email ?? ""}</span>
    </div>
  );
}

function fixedTime(ms: number): () => number {
  return () => ms;
}

function tokenResponseBody(overrides: Partial<Record<string, unknown>> = {}) {
  // header.payload.signature with payload {"sub":"user-1","email":"shopper@example.invalid"}
  const payload = btoa(JSON.stringify({ sub: "user-1", email: "shopper@example.invalid" }));
  return {
    access_token: "new-access",
    id_token: `h.${payload}.s`,
    refresh_token: "new-refresh",
    expires_in: 3600,
    token_type: "Bearer",
    ...overrides,
  };
}

function renderWithProvider(deps: AuthProviderDeps) {
  return render(
    <AuthProvider
      deps={{
        config,
        location: { search: "", pathname: "/" },
        navigate: () => undefined,
        ...deps,
      }}
    >
      <Probe />
    </AuthProvider>,
  );
}

describe("AuthProvider", () => {
  it("starts unauthenticated when no session exists", async () => {
    renderWithProvider({ storage: fakeStorage() });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
  });

  it("becomes authenticated immediately from a valid stored session", async () => {
    const storage = fakeStorage();
    const now = fixedTime(1_000_000);
    const tokens: StoredTokens = {
      accessToken: "a",
      idToken: tokenResponseBody().id_token,
      refreshToken: "r",
      expiresAt: now() + 60_000,
    };
    writeTokens(tokens, storage);

    renderWithProvider({ storage, now });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(screen.getByTestId("email").textContent).toBe("shopper@example.invalid");
  });

  it("logout() clears the session and redirects to the Cognito logout URL", async () => {
    const storage = fakeStorage();
    const now = fixedTime(1_000_000);
    writeTokens(
      { accessToken: "a", idToken: tokenResponseBody().id_token, refreshToken: "r", expiresAt: now() + 60_000 },
      storage,
    );
    const redirect = vi.fn();

    function LogoutProbe() {
      const { logout, status } = useAuth();
      return (
        <div>
          <span data-testid="status">{status}</span>
          <button type="button" onClick={logout}>
            logout
          </button>
        </div>
      );
    }

    render(
      <AuthProvider deps={{ config, storage, now, redirect, location: { search: "", pathname: "/" }, navigate: () => undefined }}>
        <LogoutProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    act(() => {
      screen.getByText("logout").click();
    });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
    expect(redirect).toHaveBeenCalledTimes(1);
    const url = new URL((redirect.mock.calls[0] as [string])[0]);
    expect(url.host).toBe(config.domain);
  });

  it("refreshes an expired session with a refresh token and becomes authenticated", async () => {
    const storage = fakeStorage();
    const now = fixedTime(1_000_000);
    writeTokens(
      { accessToken: "stale", idToken: "stale", refreshToken: "r", expiresAt: now() - 1 },
      storage,
    );
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(tokenResponseBody()),
    });

    renderWithProvider({ storage, now, fetchImpl });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("moves to 'expired' - not 'unauthenticated' - when a stale session's refresh fails", async () => {
    const storage = fakeStorage();
    const now = fixedTime(1_000_000);
    writeTokens(
      { accessToken: "stale", idToken: "stale", refreshToken: "r", expiresAt: now() - 1 },
      storage,
    );
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 400, json: () => Promise.resolve({}) });

    renderWithProvider({ storage, now, fetchImpl });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("expired"));
  });

  it("exchanges an authorization-code callback and navigates to the original return path", async () => {
    const storage = fakeStorage();
    storage.setItem(
      "proofpath.auth.pending",
      JSON.stringify({ codeVerifier: "verifier", state: "state-abc", returnTo: "/purchases/42" }),
    );
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(tokenResponseBody()),
    });
    const navigate = vi.fn();

    renderWithProvider({
      storage,
      fetchImpl,
      navigate,
      location: { search: "?code=abc123&state=state-abc", pathname: "/" },
    });

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(navigate).toHaveBeenCalledWith("/purchases/42");
  });

  it("fails closed to 'unauthenticated' when the callback state doesn't match the stored pending value", async () => {
    const storage = fakeStorage();
    storage.setItem(
      "proofpath.auth.pending",
      JSON.stringify({ codeVerifier: "verifier", state: "expected-state", returnTo: "/" }),
    );
    const fetchImpl = vi.fn();

    renderWithProvider({
      storage,
      fetchImpl,
      location: { search: "?code=abc123&state=wrong-state", pathname: "/" },
    });

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("AuthProvider login()", () => {
  it("stores a pending authorization and redirects to the Cognito hosted UI with PKCE params", async () => {
    const storage = fakeStorage();
    const redirect = vi.fn();
    const pkce = {
      randomBytes: (length: number) => new Uint8Array(length).fill(1),
      sha256: () => Promise.resolve(new Uint8Array(32).fill(2).buffer),
    };

    function LoginProbe() {
      const { login } = useAuth();
      return (
        <button type="button" onClick={() => login("/searches/1")}>
          login
        </button>
      );
    }

    render(
      <AuthProvider
        deps={{
          config,
          storage,
          redirect,
          pkce,
          location: { search: "", pathname: "/" },
          navigate: () => undefined,
        }}
      >
        <LoginProbe />
      </AuthProvider>,
    );

    await act(async () => {
      screen.getByText("login").click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(redirect).toHaveBeenCalledTimes(1);
    const url = new URL((redirect.mock.calls[0] as [string])[0]);
    expect(url.host).toBe(config.domain);
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("client_id")).toBe(config.clientId);
    expect(url.searchParams.get("state")).not.toBeNull();

    const pending = storage.getItem("proofpath.auth.pending");
    expect(pending).not.toBeNull();
    expect(JSON.parse(pending as string)).toMatchObject({ returnTo: "/searches/1" });
  });
});
