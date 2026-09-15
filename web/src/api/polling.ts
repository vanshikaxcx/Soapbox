import { ApiError, isApiError } from "./errors";

/**
 * Bounded polling for async commands (WP-00 `202 {job_id, resource_id,
 * status_url}` shape). Three rules the UI depends on:
 *
 *  - 2s while the user is plausibly still watching, then 5s;
 *  - stop the moment the job reaches a terminal state - never keep polling a
 *    settled purchase;
 *  - pause while the tab is hidden and poll immediately on return, so a phone
 *    left on a lock screen does not burn the budget or the user's battery.
 */
export interface PollPolicy {
  fastIntervalMs: number;
  /** Number of fast polls before dropping to the slow interval. */
  fastAttempts: number;
  slowIntervalMs: number;
  /** Bound measured in visible time; hidden time does not count against it. */
  maxVisibleDurationMs: number;
}

export const DEFAULT_POLL_POLICY: PollPolicy = {
  fastIntervalMs: 2_000,
  fastAttempts: 5,
  slowIntervalMs: 5_000,
  maxVisibleDurationMs: 120_000,
};

export interface Scheduler {
  now(): number;
  sleep(ms: number, signal?: AbortSignal): Promise<void>;
}

export const realScheduler: Scheduler = {
  now: () => Date.now(),
  sleep: (ms, signal) =>
    new Promise((resolve, reject) => {
      if (signal?.aborted === true) {
        reject(new ApiError({ kind: "canceled", message: "Polling canceled." }));
        return;
      }
      const timer = setTimeout(() => {
        signal?.removeEventListener("abort", onAbort);
        resolve();
      }, ms);
      const onAbort = (): void => {
        clearTimeout(timer);
        reject(new ApiError({ kind: "canceled", message: "Polling canceled." }));
      };
      signal?.addEventListener("abort", onAbort, { once: true });
    }),
};

export interface Visibility {
  isVisible(): boolean;
  /** Resolves the next time the document becomes visible. */
  whenVisible(signal?: AbortSignal): Promise<void>;
}

export const alwaysVisible: Visibility = {
  isVisible: () => true,
  whenVisible: () => Promise.resolve(),
};

export function documentVisibility(doc: Document = document): Visibility {
  return {
    isVisible: () => doc.visibilityState === "visible",
    whenVisible: (signal) =>
      new Promise((resolve, reject) => {
        if (doc.visibilityState === "visible") {
          resolve();
          return;
        }
        const onChange = (): void => {
          if (doc.visibilityState === "visible") {
            cleanup();
            resolve();
          }
        };
        const onAbort = (): void => {
          cleanup();
          reject(new ApiError({ kind: "canceled", message: "Polling canceled." }));
        };
        const cleanup = (): void => {
          doc.removeEventListener("visibilitychange", onChange);
          signal?.removeEventListener("abort", onAbort);
        };
        doc.addEventListener("visibilitychange", onChange);
        signal?.addEventListener("abort", onAbort, { once: true });
      }),
  };
}

export type PollOutcome<T> =
  | { status: "terminal"; value: T; attempts: number }
  | { status: "deadline_exceeded"; last: T | undefined; attempts: number };

export interface PollOptions<T> {
  /** One status read. Throwing a retryable ApiError is tolerated; anything else aborts. */
  poll: (signal?: AbortSignal) => Promise<T>;
  isTerminal: (value: T) => boolean;
  policy?: PollPolicy;
  scheduler?: Scheduler;
  visibility?: Visibility;
  signal?: AbortSignal;
  /** Called after every successful read, including the terminal one. */
  onUpdate?: (value: T) => void;
  /** Called when a transient read fails, so the UI can show a "reconnecting" notice. */
  onTransientError?: (error: ApiError) => void;
}

/**
 * Polls until terminal, the visible-time budget is exhausted, or the caller
 * aborts (which rejects with a `canceled` ApiError). Transient failures -
 * network, timeout, 429, 5xx - consume an attempt and keep the loop alive;
 * every other failure propagates, because polling a 404 or a 403 forever is
 * how a UI ends up lying about a purchase.
 */
export async function pollUntilTerminal<T>(options: PollOptions<T>): Promise<PollOutcome<T>> {
  const policy = options.policy ?? DEFAULT_POLL_POLICY;
  const scheduler = options.scheduler ?? realScheduler;
  const visibility = options.visibility ?? alwaysVisible;
  const { signal } = options;

  let attempts = 0;
  let visibleElapsedMs = 0;
  let last: T | undefined;

  for (;;) {
    if (!visibility.isVisible()) {
      await visibility.whenVisible(signal);
    }

    const startedAt = scheduler.now();
    attempts += 1;
    try {
      const value = await options.poll(signal);
      last = value;
      options.onUpdate?.(value);
      if (options.isTerminal(value)) {
        return { status: "terminal", value, attempts };
      }
    } catch (error) {
      if (!isApiError(error) || !error.retryable) {
        throw error;
      }
      options.onTransientError?.(error);
    }
    visibleElapsedMs += scheduler.now() - startedAt;

    if (visibleElapsedMs >= policy.maxVisibleDurationMs) {
      return { status: "deadline_exceeded", last, attempts };
    }

    const intervalMs =
      attempts < policy.fastAttempts ? policy.fastIntervalMs : policy.slowIntervalMs;
    const waitStartedAt = scheduler.now();
    await scheduler.sleep(intervalMs, signal);
    if (visibility.isVisible()) {
      visibleElapsedMs += scheduler.now() - waitStartedAt;
    }
  }
}
