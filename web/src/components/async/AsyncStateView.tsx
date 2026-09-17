import type { ReactNode } from "react";
import type { AsyncState } from "../../state/asyncState";
import { ErrorCard } from "../cards/ErrorCard";
import { NoticeCard } from "../cards/NoticeCard";

export interface AsyncStateViewProps<T> {
  state: AsyncState<T>;
  /** Rendered for "success" and, unless `renderPartial` is given, for "partial" too. */
  children: (data: T, partial: boolean) => ReactNode;
  renderPartial?: (data: T) => ReactNode;
  renderEmpty?: (() => ReactNode) | undefined;
  emptyLabel?: string;
  onRetry?: (() => void) | undefined;
}

/**
 * The single dispatch point every route/card uses instead of ad hoc
 * loading/error booleans (WP-03: "every async surface implements loading,
 * partial, empty, retryable error, terminal error, expired, and
 * stale-conflict behavior as applicable").
 */
export function AsyncStateView<T>({
  state,
  children,
  renderPartial,
  renderEmpty,
  emptyLabel = "Nothing here yet.",
  onRetry,
}: AsyncStateViewProps<T>) {
  switch (state.status) {
    case "idle":
    case "loading":
      return (
        <div role="status" aria-live="polite" className="pp-async-loading">
          <span className="pp-spinner" aria-hidden="true" />
          Loading…
        </div>
      );
    case "empty":
      return (
        renderEmpty?.() ?? (
          <div role="status" className="pp-async-empty">
            {emptyLabel}
          </div>
        )
      );
    case "partial":
      return <>{renderPartial ? renderPartial(state.data) : children(state.data, true)}</>;
    case "success":
      return <>{children(state.data, false)}</>;
    case "stale":
      return (
        <>
          <NoticeCard
            tone="warning"
            title="This has changed since you last looked"
            body="Someone or something updated this. Refresh to see the current version before acting on it."
            action={onRetry ? { label: "Refresh", onClick: onRetry } : undefined}
          />
          {children(state.data, true)}
        </>
      );
    case "expired":
      return <ErrorCard error={state.error} onRetry={undefined} />;
    case "error":
      return <ErrorCard error={state.error} onRetry={state.error.retryable ? onRetry : undefined} />;
    default: {
      const exhaustive: never = state;
      return exhaustive;
    }
  }
}
