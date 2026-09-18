import type { ApiError, ApiErrorKind } from "../../api/errors";

const MESSAGE_BY_KIND: Record<ApiErrorKind, string> = {
  validation:
    "Some of the information wasn't valid. Please check and try again.",
  conflict:
    "That action couldn't be completed because something changed. Refresh and try again.",
  stale_version:
    "This changed since you last looked. Refresh to see the current version.",
  expired: "This has expired and can no longer be used.",
  not_found: "We couldn't find that.",
  unauthorized: "You need to sign in again.",
  forbidden: "You don't have access to this.",
  rate_limited: "Too many attempts. Please wait a moment and try again.",
  server: "Something went wrong on our side. Please try again.",
  network: "We couldn't reach the server. Check your connection and try again.",
  timeout: "That took too long. Please try again.",
  canceled: "That request was canceled.",
  malformed: "We got an unexpected response. Please try again.",
};

export interface ErrorCardProps {
  error: ApiError;
  onRetry?: (() => void) | undefined;
  /** Diagnostic mode: surfaces the request id for support/bug reports. */
  showRequestId?: boolean;
}

export function ErrorCard({
  error,
  onRetry,
  showRequestId = false,
}: ErrorCardProps) {
  return (
    <div className="pp-card pp-error" role="alert">
      <p className="pp-error__message">{MESSAGE_BY_KIND[error.kind]}</p>
      {onRetry !== undefined && (
        <button
          type="button"
          className="pp-button pp-button--primary"
          onClick={onRetry}
        >
          Try again
        </button>
      )}
      {showRequestId && error.requestId !== undefined && (
        <p className="pp-error__request-id">Reference: {error.requestId}</p>
      )}
    </div>
  );
}
