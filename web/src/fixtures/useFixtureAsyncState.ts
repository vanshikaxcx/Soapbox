import { useEffect, useState } from "react";
import type { AsyncState } from "../state/asyncState";

/**
 * Renders a fixture through the same AsyncState the real API client will
 * eventually produce, so routes exercise loading/success like production
 * without a second backend (POA §7 component-harness requirement).
 */
export function useFixtureAsyncState<T>(data: T, delayMs = 300): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting to loading when delayMs changes is this hook's own state, not derivable during render
    setState({ status: "loading" });
    const timer = setTimeout(
      () => setState({ status: "success", data }),
      delayMs,
    );
    return () => clearTimeout(timer);
  }, [data, delayMs]);

  return state;
}
