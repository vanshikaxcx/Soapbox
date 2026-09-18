/**
 * Server-declared error code from the shared envelope (WP-00 contract). The
 * contract only constrains this to `^[a-z][a-z0-9_]*$`, not a closed enum -
 * each work package mints its own codes as it lands, so an unrecognized one
 * falls back to `kindForFailure`'s status-based mapping rather than a type error.
 */
export type ServerErrorCode = string;

/**
 * What the UI branches on. Server codes are authoritative when present; HTTP
 * status is the fallback, and the transport-only kinds have no server code.
 */
export type ApiErrorKind =
  | "validation" //     422 - input rejected, show field details
  | "conflict" //       409 - same idempotency key, different payload
  | "stale_version" //  409 - expected_version/revision behind server
  | "expired" //        410 - quote/preparation/URL past its lifetime
  | "not_found" //      404 - absent, or concealed because not owned
  | "unauthorized" //   401 - no/expired session, re-authenticate
  | "forbidden" //      403 - authenticated but not permitted
  | "rate_limited" //   429
  | "server" //         5xx
  | "network" //        request never produced a response
  | "timeout" //        aborted by our own deadline
  | "canceled" //       aborted by the caller (navigation, superseded request)
  | "malformed"; //     response did not match the envelope contract

const CODE_TO_KIND: Partial<Record<ServerErrorCode, ApiErrorKind>> = {
  validation_error: "validation",
  conflict: "conflict",
  stale_version: "stale_version",
  expired: "expired",
  not_found: "not_found",
  unauthorized: "unauthorized",
  forbidden: "forbidden",
  rate_limited: "rate_limited",
  internal_error: "server",
};

const STATUS_TO_KIND: Record<number, ApiErrorKind> = {
  400: "validation",
  401: "unauthorized",
  403: "forbidden",
  404: "not_found",
  409: "conflict",
  410: "expired",
  422: "validation",
  429: "rate_limited",
};

/**
 * Kinds that may be retried with the SAME idempotency key. A retry that
 * generates a fresh key is a second intent, not a retry (WP-00 concurrency
 * contract), so callers must reuse the key from `idempotencyKeyFor`.
 */
const RETRYABLE: ReadonlySet<ApiErrorKind> = new Set<ApiErrorKind>([
  "network",
  "timeout",
  "rate_limited",
  "server",
]);

export interface ApiErrorInit {
  kind: ApiErrorKind;
  message: string;
  /** Present only when the server returned a well-formed error envelope. */
  code?: ServerErrorCode | undefined;
  status?: number | undefined;
  requestId?: string | undefined;
  details?: Record<string, unknown> | null | undefined;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly code: ServerErrorCode | undefined;
  readonly status: number | undefined;
  /** Shown in diagnostic mode and quoted in support/case flows. */
  readonly requestId: string | undefined;
  readonly details: Record<string, unknown> | null | undefined;

  constructor(init: ApiErrorInit) {
    super(
      init.message,
      init.cause === undefined ? undefined : { cause: init.cause },
    );
    this.name = "ApiError";
    this.kind = init.kind;
    this.code = init.code;
    this.status = init.status;
    this.requestId = init.requestId;
    this.details = init.details;
  }

  get retryable(): boolean {
    return RETRYABLE.has(this.kind);
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/**
 * Resolve the kind for a failed response. A 409 is ambiguous by status alone -
 * only the server code separates "you reused a key with a different payload"
 * from "your expected_version is behind" - so an unlabelled 409 stays
 * `conflict`, the more conservative of the two for the UI.
 */
export function kindForFailure(
  status: number,
  code: ServerErrorCode | undefined,
): ApiErrorKind {
  if (code !== undefined) {
    const byCode = CODE_TO_KIND[code];
    if (byCode !== undefined) {
      return byCode;
    }
  }
  const byStatus = STATUS_TO_KIND[status];
  if (byStatus !== undefined) {
    return byStatus;
  }
  return status >= 500 ? "server" : "malformed";
}
