import { useState } from "react";
import { ApiError } from "../api/errors";
import { AsyncStateView } from "../components/async/AsyncStateView";
import type { AsyncState } from "../state/asyncState";
import { fixtureBaskets } from "../fixtures/routeFixtures";

type PreviewStatus = AsyncState<typeof fixtureBaskets>["status"];

const PREVIEWABLE_STATUSES: PreviewStatus[] = [
  "loading",
  "empty",
  "partial",
  "success",
  "stale",
  "expired",
  "error",
];

function stateFor(status: PreviewStatus): AsyncState<typeof fixtureBaskets> {
  switch (status) {
    case "idle":
    case "loading":
      return { status: "loading" };
    case "empty":
      return { status: "empty" };
    case "partial":
      return { status: "partial", data: fixtureBaskets };
    case "success":
      return { status: "success", data: fixtureBaskets };
    case "stale":
      return {
        status: "stale",
        data: fixtureBaskets,
        error: new ApiError({ kind: "stale_version", message: "Stale." }),
      };
    case "expired":
      return { status: "expired", error: new ApiError({ kind: "expired", message: "Expired." }) };
    case "error":
      return { status: "error", error: new ApiError({ kind: "server", message: "Server error." }) };
  }
}

/**
 * `/demo` - the component harness (POA §7: "deterministic Storybook-equivalent
 * route fixtures or component harness without inventing a second backend")
 * and, from WP-11 onward, the operator console entry point. Kept separate
 * from shopper routes as the spec requires.
 */
export function DemoPage() {
  const [selected, setSelected] = useState<PreviewStatus>("success");

  return (
    <div className="pp-page">
      <h1>Component harness</h1>
      <p>Preview every async state a shared card can render, without a live backend.</p>
      <label htmlFor="pp-demo-state">Async state</label>
      <select
        id="pp-demo-state"
        value={selected}
        onChange={(event) => setSelected(event.target.value as PreviewStatus)}
      >
        {PREVIEWABLE_STATUSES.map((status) => (
          <option key={status} value={status}>
            {status}
          </option>
        ))}
      </select>
      <AsyncStateView state={stateFor(selected)} onRetry={() => setSelected("loading")}>
        {(baskets, partial) => (
          <>
            {partial && <p role="status">Partial coverage.</p>}
            <ul>
              {baskets.map((basket) => (
                <li key={basket.merchant}>{basket.merchant}</li>
              ))}
            </ul>
          </>
        )}
      </AsyncStateView>
    </div>
  );
}
