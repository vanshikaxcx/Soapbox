import { useCallback, useState } from "react";
import { formatRelativeTime } from "../components/cards/format";

const STORAGE_KEY = "proofpath.usual_basket";
/** Domain rule (UsualBasket): loading it always starts a fresh search, never replays an old
 * result - this window only decides whether the UI mentions that the save looks old, not
 * whether loading behaves differently. */
const FRESHNESS_WINDOW_MS = 24 * 60 * 60 * 1000;

export interface UsualBasketRecord {
  text: string;
  savedAt: string;
}

export interface UseUsualBasketDeps {
  /** Real by default: localStorage, same convention as auth's sessionStorage. */
  storage?: Storage;
  now?: () => number;
}

export interface UseUsualBasketResult {
  saved: UsualBasketRecord | null;
  /** Pre-formatted here, not via a raw Date.now() call in the component's render body. */
  savedRelativeTime: string | null;
  isStale: boolean;
  save: (text: string) => void;
  clear: () => void;
}

function readSaved(storage: Storage): UsualBasketRecord | null {
  const raw = storage.getItem(STORAGE_KEY);
  if (raw === null) {
    return null;
  }
  try {
    return JSON.parse(raw) as UsualBasketRecord;
  } catch {
    return null;
  }
}

/**
 * Usual-basket save/load (WP-05). Real persistence is WP-07/P4's scope
 * ("UsualBasket deliberately cannot hold a price, a quote, an approval or a
 * payment identity" - WP-02's own domain doc); this stores only the raw
 * request text, and loading always resubmits it through the normal
 * canonical path, so it re-runs extraction/comparison fresh rather than
 * caching anything that could go stale.
 */
export function useUsualBasket(deps: UseUsualBasketDeps = {}): UseUsualBasketResult {
  const storage = deps.storage ?? localStorage;
  const now = deps.now ?? Date.now;
  const [saved, setSaved] = useState<UsualBasketRecord | null>(() => readSaved(storage));

  const save = useCallback(
    (text: string) => {
      const record: UsualBasketRecord = { text, savedAt: new Date(now()).toISOString() };
      storage.setItem(STORAGE_KEY, JSON.stringify(record));
      setSaved(record);
    },
    [storage, now],
  );

  const clear = useCallback(() => {
    storage.removeItem(STORAGE_KEY);
    setSaved(null);
  }, [storage]);

  const isStale = saved !== null && now() - new Date(saved.savedAt).getTime() > FRESHNESS_WINDOW_MS;
  const savedRelativeTime = saved !== null ? formatRelativeTime(saved.savedAt, now()) : null;

  return { saved, savedRelativeTime, isStale, save, clear };
}
