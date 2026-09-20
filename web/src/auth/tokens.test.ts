import { describe, expect, it } from "vitest";
import {
  clearTokens,
  isExpired,
  readTokens,
  writeTokens,
  type StoredTokens,
} from "./tokens";
import { fakeStorage } from "../test/fakeStorage";

const baseTokens: StoredTokens = {
  accessToken: "access",
  idToken: "id",
  refreshToken: "refresh",
  expiresAt: 1_000_000,
};

describe("token storage", () => {
  it("round-trips through storage", () => {
    const storage = fakeStorage();
    writeTokens(baseTokens, storage);
    expect(readTokens(storage)).toEqual(baseTokens);
  });

  it("clears tokens", () => {
    const storage = fakeStorage();
    writeTokens(baseTokens, storage);
    clearTokens(storage);
    expect(readTokens(storage)).toBeNull();
  });

  it("treats malformed stored JSON as absent", () => {
    const storage = fakeStorage({ "proofpath.auth.tokens": "{broken" });
    expect(readTokens(storage)).toBeNull();
  });
});

describe("isExpired", () => {
  it("is false comfortably before expiry", () => {
    expect(isExpired(baseTokens, () => baseTokens.expiresAt - 60_000)).toBe(
      false,
    );
  });

  it("is true within the skew window before the nominal expiry", () => {
    expect(isExpired(baseTokens, () => baseTokens.expiresAt - 5_000)).toBe(
      true,
    );
  });

  it("is true after expiry", () => {
    expect(isExpired(baseTokens, () => baseTokens.expiresAt + 1)).toBe(true);
  });
});
