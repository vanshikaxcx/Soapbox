import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AuthBoundary } from "./AuthBoundary";
import { AuthProvider } from "./AuthContext";
import type { CognitoConfig } from "./cognitoConfig";
import { fakeStorage } from "../test/fakeStorage";

const config: CognitoConfig = {
  domain: "auth.example.invalid",
  clientId: "client",
  redirectUri: "https://app.example.invalid/",
  logoutUri: "https://app.example.invalid/",
  scopes: ["openid"],
};

describe("AuthBoundary", () => {
  it("redirects to sign-in instead of rendering protected content when unauthenticated", async () => {
    const redirect = vi.fn();
    render(
      <MemoryRouter initialEntries={["/purchases/1"]}>
        <AuthProvider
          deps={{
            config,
            storage: fakeStorage(),
            redirect,
            location: { search: "", pathname: "/purchases/1" },
            navigate: () => undefined,
          }}
        >
          <AuthBoundary>
            <div>Protected content</div>
          </AuthBoundary>
        </AuthProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(redirect).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Protected content")).toBeNull();
  });

  it("renders protected content once authenticated", async () => {
    const now = () => 1_000_000;
    const storage = fakeStorage();
    storage.setItem(
      "proofpath.auth.tokens",
      JSON.stringify({ accessToken: "a", idToken: "i", refreshToken: "r", expiresAt: now() + 60_000 }),
    );

    render(
      <MemoryRouter initialEntries={["/purchases/1"]}>
        <AuthProvider
          deps={{
            config,
            storage,
            now,
            location: { search: "", pathname: "/purchases/1" },
            navigate: () => undefined,
          }}
        >
          <AuthBoundary>
            <div>Protected content</div>
          </AuthBoundary>
        </AuthProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Protected content")).toBeTruthy());
  });
});
