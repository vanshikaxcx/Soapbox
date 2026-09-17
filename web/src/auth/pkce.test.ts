import { describe, expect, it } from "vitest";
import {
  consumePendingAuthorization,
  generateCodeChallenge,
  generateCodeVerifier,
  generateState,
  storePendingAuthorization,
  type PkceCrypto,
} from "./pkce";
import { fakeStorage } from "../test/fakeStorage";

function fixedCrypto(byte: number): PkceCrypto {
  return {
    randomBytes: (length) => new Uint8Array(length).fill(byte),
    sha256: (input) => {
      // Deterministic non-cryptographic stand-in: length-prefixed byte sum per char.
      const bytes = new TextEncoder().encode(input);
      const digest = new Uint8Array(32);
      for (let i = 0; i < bytes.length; i += 1) {
        digest[i % 32] = ((digest[i % 32] ?? 0) + (bytes[i] ?? 0)) % 256;
      }
      return Promise.resolve(digest.buffer);
    },
  };
}

describe("generateCodeVerifier", () => {
  it("is URL-safe (no +, /, or = padding)", () => {
    const verifier = generateCodeVerifier(fixedCrypto(255));
    expect(verifier).not.toMatch(/[+/=]/);
    expect(verifier.length).toBeGreaterThanOrEqual(43);
  });
});

describe("generateCodeChallenge", () => {
  it("is deterministic for the same verifier and crypto", async () => {
    const crypto1 = fixedCrypto(7);
    const a = await generateCodeChallenge("verifier-a", crypto1);
    const b = await generateCodeChallenge("verifier-a", crypto1);
    expect(a).toBe(b);
  });

  it("differs for a different verifier", async () => {
    const crypto1 = fixedCrypto(7);
    const a = await generateCodeChallenge("verifier-a", crypto1);
    const b = await generateCodeChallenge("verifier-b", crypto1);
    expect(a).not.toBe(b);
  });
});

describe("generateState", () => {
  it("produces distinct values across calls with real randomness sources", () => {
    let counter = 0;
    const crypto1: PkceCrypto = {
      randomBytes: (length) => {
        counter += 1;
        return new Uint8Array(length).fill(counter);
      },
      sha256: fixedCrypto(0).sha256,
    };
    expect(generateState(crypto1)).not.toBe(generateState(crypto1));
  });
});

describe("pending authorization store", () => {
  it("round-trips and is consumed exactly once", () => {
    const storage = fakeStorage();
    storePendingAuthorization({ codeVerifier: "v", state: "s", returnTo: "/purchases/1" }, storage);

    const first = consumePendingAuthorization(storage);
    expect(first).toEqual({ codeVerifier: "v", state: "s", returnTo: "/purchases/1" });

    const second = consumePendingAuthorization(storage);
    expect(second).toBeNull();
  });

  it("returns null for malformed stored data instead of throwing", () => {
    const storage = fakeStorage({ "proofpath.auth.pending": "not json" });
    expect(consumePendingAuthorization(storage)).toBeNull();
  });
});
