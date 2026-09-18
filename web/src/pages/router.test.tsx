import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CognitoConfig } from "../auth/cognitoConfig";
import { fakeStorage } from "../test/fakeStorage";

const config: CognitoConfig = {
  domain: "auth.example.invalid",
  clientId: "client",
  redirectUri: "https://app.example.invalid/",
  logoutUri: "https://app.example.invalid/",
  scopes: ["openid"],
};

function authenticatedStorage(): Storage {
  const storage = fakeStorage();
  storage.setItem(
    "proofpath.auth.tokens",
    JSON.stringify({
      accessToken: "a",
      idToken: "i",
      refreshToken: "r",
      expiresAt: Date.now() + 60_000,
    }),
  );
  return storage;
}

/**
 * The router module builds its browser router from `window.location` at
 * import time, so each path needs a fresh module registry - and the
 * AuthProvider must come from that same fresh registry, or its React Context
 * object won't match the one AuthBoundary's useAuth() reads from.
 */
async function renderAtPath(path: string) {
  window.history.pushState({}, "", path);
  vi.resetModules();
  const { AppRouter } = await import("./router");
  const { AuthProvider } = await import("../auth/AuthContext");
  const { ApiProvider } = await import("../api/ApiProvider");
  return render(
    <AuthProvider
      deps={{
        config,
        storage: authenticatedStorage(),
        location: { search: "", pathname: path },
      }}
    >
      <ApiProvider baseUrl="/api">
        <AppRouter />
      </ApiProvider>
    </AuthProvider>,
  );
}

afterEach(() => {
  window.history.pushState({}, "", "/");
});

describe("router", () => {
  it("renders the not-found page for an unmatched route", async () => {
    await renderAtPath("/no-such-route");
    await waitFor(() => expect(screen.getByText("Not found")).toBeTruthy());
  });

  it("renders the demo component harness at /demo, separate from shopper routes", async () => {
    await renderAtPath("/demo");
    await waitFor(() =>
      expect(screen.getByText("Component harness")).toBeTruthy(),
    );
  });

  it("renders the case page at /cases/:id", async () => {
    await renderAtPath("/cases/case-1");
    await waitFor(() => expect(screen.getByText("Case case-1")).toBeTruthy());
  });
});
