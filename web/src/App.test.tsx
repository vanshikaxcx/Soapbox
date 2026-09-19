import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { fakeStorage } from "./test/fakeStorage";
import type { CognitoConfig } from "./auth/cognitoConfig";

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

describe("App", () => {
  it("renders the authenticated shell with a working skip link and primary nav", async () => {
    render(
      <App
        authDeps={{
          config,
          storage: authenticatedStorage(),
          location: { search: "", pathname: "/" },
        }}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "ProofPath" })).toBeTruthy(),
    );

    const skipLink = screen.getByText("Skip to main content");
    expect(skipLink.getAttribute("href")).toBe("#pp-main");

    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Demo" })).toBeTruthy();
  });

  it("does not show the diagnostic bar by default", async () => {
    render(
      <App
        authDeps={{
          config,
          storage: authenticatedStorage(),
          location: { search: "", pathname: "/" },
        }}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "ProofPath" })).toBeTruthy(),
    );
    expect(screen.queryByLabelText("Diagnostic request trace")).toBeNull();
  });

  it("redirects instead of rendering shopper routes when unauthenticated", async () => {
    const redirect = vi.fn();
    render(
      <App
        authDeps={{
          config,
          storage: fakeStorage(),
          redirect,
          location: { search: "", pathname: "/" },
          navigate: () => undefined,
        }}
      />,
    );

    await waitFor(() => expect(redirect).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("heading", { name: "ProofPath" })).toBeNull();
  });
});
