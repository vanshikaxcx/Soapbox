import type { ApiError } from "../api/errors";

/**
 * The one state shape every async surface renders from (WP-03: "every async
 * surface implements loading, partial, empty, retryable error, terminal
 * error, expired, and stale-conflict behavior"). A route/card never invents
 * its own ad hoc loading/error booleans - it maps data into this union once.
 */
export type AsyncState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "empty" }
  /** Some but not all expected sources reported back (e.g. one merchant failed). */
  | { status: "partial"; data: T }
  | { status: "success"; data: T }
  /** Last-known data still shown, invalidated by a 409 stale_version/conflict. */
  | { status: "stale"; data: T; error: ApiError }
  | { status: "expired"; error: ApiError }
  | { status: "error"; error: ApiError };

export function isTerminalError(
  state: AsyncState<unknown>,
): state is Extract<AsyncState<unknown>, { status: "error" | "expired" }> {
  return state.status === "error" || state.status === "expired";
}
