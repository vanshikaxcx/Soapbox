/**
 * Authorization-code PKCE primitives (WP-03). Pure and crypto-injectable so
 * tests don't depend on the real Web Crypto RNG/digest.
 */
export interface PkceCrypto {
  randomBytes: (length: number) => Uint8Array;
  sha256: (input: string) => Promise<ArrayBuffer>;
}

export const webCryptoPkce: PkceCrypto = {
  randomBytes: (length) => crypto.getRandomValues(new Uint8Array(length)),
  sha256: (input) => crypto.subtle.digest("SHA-256", new TextEncoder().encode(input)),
};

function base64Url(bytes: Uint8Array | ArrayBuffer): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (const byte of view) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** 43-128 char unreserved-character string per RFC 7636. */
export function generateCodeVerifier(pkce: PkceCrypto = webCryptoPkce): string {
  return base64Url(pkce.randomBytes(64));
}

export async function generateCodeChallenge(
  verifier: string,
  pkce: PkceCrypto = webCryptoPkce,
): Promise<string> {
  return base64Url(await pkce.sha256(verifier));
}

/** Opaque CSRF-binding value for the `state` param; also doubles as the nonce. */
export function generateState(pkce: PkceCrypto = webCryptoPkce): string {
  return base64Url(pkce.randomBytes(32));
}

export interface PendingAuthorization {
  codeVerifier: string;
  state: string;
  /** Where to return the user once the callback is handled. */
  returnTo: string;
}

const PENDING_KEY = "proofpath.auth.pending";

export function storePendingAuthorization(
  pending: PendingAuthorization,
  storage: Storage = sessionStorage,
): void {
  storage.setItem(PENDING_KEY, JSON.stringify(pending));
}

/** One-shot: the pending record is consumed and removed so a replayed callback fails closed. */
export function consumePendingAuthorization(
  storage: Storage = sessionStorage,
): PendingAuthorization | null {
  const raw = storage.getItem(PENDING_KEY);
  if (raw === null) {
    return null;
  }
  storage.removeItem(PENDING_KEY);
  try {
    const parsed = JSON.parse(raw) as Partial<PendingAuthorization>;
    if (
      typeof parsed.codeVerifier !== "string" ||
      typeof parsed.state !== "string" ||
      typeof parsed.returnTo !== "string"
    ) {
      return null;
    }
    return { codeVerifier: parsed.codeVerifier, state: parsed.state, returnTo: parsed.returnTo };
  } catch {
    return null;
  }
}
