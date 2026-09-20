/**
 * An idempotency key identifies an *intent*, not a request. Every retry of the
 * same intent - including one issued after a reload or a crash - must send the
 * key the intent started with, or the server sees a second intent and the
 * "one approval, one payment effect" invariant is lost (SPEC, WP-08/WP-09).
 */
export type IdempotencyKey = string & { readonly __brand: "IdempotencyKey" };

export interface KeyStore {
  get(intentId: string): string | null;
  set(intentId: string, key: string): void;
  clear(intentId: string): void;
}

export function memoryKeyStore(seed?: Record<string, string>): KeyStore {
  const keys = new Map<string, string>(Object.entries(seed ?? {}));
  return {
    get: (intentId) => keys.get(intentId) ?? null,
    set: (intentId, key) => void keys.set(intentId, key),
    clear: (intentId) => void keys.delete(intentId),
  };
}

/**
 * sessionStorage, not localStorage: a key must survive a reload of this tab
 * mid-attempt, but must not leak into a later session where the user believes
 * they are starting a fresh purchase. Falls back to memory when storage is
 * unavailable (private mode, blocked cookies).
 */
export function sessionKeyStore(
  storage: Storage | undefined = globalThis.sessionStorage,
): KeyStore {
  if (storage === undefined) {
    return memoryKeyStore();
  }
  const namespaced = (intentId: string): string =>
    `proofpath.idempotency.${intentId}`;
  try {
    storage.setItem(namespaced("probe"), "1");
    storage.removeItem(namespaced("probe"));
  } catch {
    return memoryKeyStore();
  }
  return {
    get: (intentId) => storage.getItem(namespaced(intentId)),
    set: (intentId, key) => storage.setItem(namespaced(intentId), key),
    clear: (intentId) => storage.removeItem(namespaced(intentId)),
  };
}

export function newIdempotencyKey(
  randomUuid: () => string = () => crypto.randomUUID(),
): IdempotencyKey {
  return randomUuid() as IdempotencyKey;
}

/**
 * Stable key for `intentId`: minted once, then returned unchanged until the
 * intent reaches a terminal outcome and the caller releases it.
 */
export function idempotencyKeyFor(
  intentId: string,
  store: KeyStore,
  randomUuid?: () => string,
): IdempotencyKey {
  const existing = store.get(intentId);
  if (existing !== null) {
    return existing as IdempotencyKey;
  }
  const key = newIdempotencyKey(randomUuid);
  store.set(intentId, key);
  return key;
}

/** Call only once the intent is settled; a released key must never be resent. */
export function releaseIdempotencyKey(intentId: string, store: KeyStore): void {
  store.clear(intentId);
}
