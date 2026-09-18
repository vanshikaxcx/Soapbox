/**
 * Session token storage. sessionStorage (not localStorage) for the same
 * reason as the idempotency key store (api/idempotency.ts): tokens must
 * survive a reload of this tab but must not leak into a later session.
 */
export interface StoredTokens {
  accessToken: string;
  idToken: string;
  refreshToken: string | null;
  /** Epoch ms; derived from `expires_in` at exchange/refresh time. */
  expiresAt: number;
}

const TOKENS_KEY = "proofpath.auth.tokens";

export function readTokens(
  storage: Storage = sessionStorage,
): StoredTokens | null {
  const raw = storage.getItem(TOKENS_KEY);
  if (raw === null) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<StoredTokens>;
    if (
      typeof parsed.accessToken !== "string" ||
      typeof parsed.idToken !== "string" ||
      typeof parsed.expiresAt !== "number"
    ) {
      return null;
    }
    return {
      accessToken: parsed.accessToken,
      idToken: parsed.idToken,
      refreshToken:
        typeof parsed.refreshToken === "string" ? parsed.refreshToken : null,
      expiresAt: parsed.expiresAt,
    };
  } catch {
    return null;
  }
}

export function writeTokens(
  tokens: StoredTokens,
  storage: Storage = sessionStorage,
): void {
  storage.setItem(TOKENS_KEY, JSON.stringify(tokens));
}

export function clearTokens(storage: Storage = sessionStorage): void {
  storage.removeItem(TOKENS_KEY);
}

/** A short grace window avoids treating a token as valid on a request that will arrive after it lapses. */
const EXPIRY_SKEW_MS = 10_000;

export function isExpired(
  tokens: StoredTokens,
  now: () => number = Date.now,
): boolean {
  return now() >= tokens.expiresAt - EXPIRY_SKEW_MS;
}
