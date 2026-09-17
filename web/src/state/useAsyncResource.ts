import { useCallback, useEffect, useState } from "react";
import { ApiError, isApiError } from "../api/errors";
import type { ApiResult } from "../api/client";
import { pollUntilTerminal, type PollPolicy, type Scheduler, type Visibility } from "../api/polling";
import type { AsyncState } from "./asyncState";

export interface UseAsyncResourceOptions<T> {
  /** Classifies a successful payload as empty/partial/success. Defaults to always "success". */
  classify?: (data: T) => "empty" | "partial" | "success";
  /** When present, the resource is polled until this returns true (WP-00 job-status contract). */
  poll?: {
    isTerminal: (data: T) => boolean;
    policy?: PollPolicy;
    scheduler?: Scheduler;
    visibility?: Visibility;
  };
  /** Re-fetches when any dependency changes, same semantics as useEffect deps. */
  deps?: readonly unknown[];
}

export interface UseAsyncResourceResult<T> {
  state: AsyncState<T>;
  requestId: string | undefined;
  /** Re-runs the fetch from scratch (retryable errors and manual "try again"). */
  retry: () => void;
}

/**
 * Bridges the typed API client to route-level state (WP-03: "server state
 * comes from the typed API client and polling controller; avoid copying it
 * into multiple local stores"). Every fetcher receives an AbortSignal so a
 * superseded request (route change, retry) reports `canceled`, not a stale
 * success racing in after a newer one.
 */
export function useAsyncResource<T>(
  fetcher: (signal: AbortSignal) => Promise<ApiResult<T>>,
  options: UseAsyncResourceOptions<T> = {},
): UseAsyncResourceResult<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  const [requestId, setRequestId] = useState<string | undefined>(undefined);
  const [generation, setGeneration] = useState(0);
  const classify = options.classify;
  const poll = options.poll;
  const deps = options.deps ?? [];

  const retry = useCallback(() => setGeneration((g) => g + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    // Resetting to "loading" when the fetch identity (generation/deps) changes
    // is the fetch's own state, not a value derivable from props during render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState({ status: "loading" });
    setRequestId(undefined);

    const classifyOrDefault = (data: T): AsyncState<T> => {
      const kind = classify?.(data) ?? "success";
      return kind === "success" ? { status: "success", data } : { status: kind, data };
    };

    async function run(): Promise<void> {
      try {
        if (poll) {
          const outcome = await pollUntilTerminal<ApiResult<T>>({
            poll: (signal) => fetcher(signal ?? controller.signal),
            isTerminal: (result) => poll.isTerminal(result.data),
            policy: poll.policy,
            scheduler: poll.scheduler,
            visibility: poll.visibility,
            signal: controller.signal,
            onUpdate: (result) => {
              setRequestId(result.requestId);
              setState(classifyOrDefault(result.data));
            },
          });
          if (outcome.status === "deadline_exceeded") {
            setState({
              status: "error",
              error: new ApiError({
                kind: "timeout",
                message: "Timed out waiting for this to finish. You can try again.",
              }),
            });
          }
          return;
        }

        const result = await fetcher(controller.signal);
        setRequestId(result.requestId);
        setState(classifyOrDefault(result.data));
      } catch (error) {
        if (isApiError(error) && error.kind === "canceled") {
          return;
        }
        const apiError = isApiError(error)
          ? error
          : new ApiError({ kind: "server", message: "Something unexpected happened." });
        setRequestId(apiError.requestId);
        setState(
          apiError.kind === "expired" || apiError.kind === "stale_version" || apiError.kind === "conflict"
            ? { status: apiError.kind === "expired" ? "expired" : "error", error: apiError }
            : { status: "error", error: apiError },
        );
      }
    }

    void run();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generation, ...deps]);

  return { state, requestId, retry };
}
