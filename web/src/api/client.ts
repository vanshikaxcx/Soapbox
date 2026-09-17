import { ApiError, kindForFailure } from "./errors";
import type { IdempotencyKey } from "./idempotency";
import { fetchTransport, type Transport } from "./transport";
import type { components } from "./generated/schema";

/** Every successful response carries its correlation id alongside the payload. */
export interface ApiResult<T> {
  data: T;
  requestId: string;
}

export interface RequestTrace {
  method: string;
  path: string;
  status: number;
  requestId: string | undefined;
  durationMs: number;
}

export interface ApiClientOptions {
  baseUrl: string;
  transport?: Transport;
  /** Resolved per request so a refreshed Cognito token is picked up (WP-03 auth boundary). */
  accessToken?: () => string | null | Promise<string | null>;
  /** Client-side deadline; the server's own deadlines are longer and authoritative. */
  timeoutMs?: number;
  /** Diagnostic mode hook: surfaces request ids without logging them by default. */
  onTrace?: (trace: RequestTrace) => void;
  now?: () => number;
}

export interface GetOptions {
  query?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface MutateOptions<TBody> extends GetOptions {
  /** Required: mutations without an intent key are not retry-safe. */
  idempotencyKey: IdempotencyKey;
  body?: TBody;
  /** Merged into the body per the WP-00 convention (body field, not header). */
  expectedVersion?: number;
  expectedRevision?: number;
}

type HealthData = components["schemas"]["HealthSuccessResponse"]["data"];

const DEFAULT_TIMEOUT_MS = 15_000;

function joinUrl(baseUrl: string, path: string, query: GetOptions["query"]): string {
  const trimmed = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
  const url = new URL(`${trimmed}${path}`, "http://api.invalid");
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  }
  const absolute = /^https?:/i.test(trimmed);
  return absolute ? url.toString() : `${url.pathname}${url.search}`;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readRequestId(envelope: Record<string, unknown> | null): string | undefined {
  const requestId = envelope?.["request_id"];
  return typeof requestId === "string" ? requestId : undefined;
}

/**
 * Turns an error envelope into an ApiError. A response that claims failure but
 * does not match the contract is `malformed`, never silently treated as data -
 * the UI must not render a half-understood failure as success.
 */
function failureToError(status: number, envelope: Record<string, unknown> | null): ApiError {
  const requestId = readRequestId(envelope);
  const body = asRecord(envelope?.["error"]);
  const rawCode = body?.["code"];
  const code = typeof rawCode === "string" ? rawCode : undefined;
  const message = typeof body?.["message"] === "string" ? body["message"] : undefined;
  const details = asRecord(body?.["details"]);
  return new ApiError({
    kind: kindForFailure(status, code),
    code,
    status,
    requestId,
    details,
    message: message ?? `Request failed with status ${status}.`,
  });
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly transport: Transport;
  private readonly accessToken: (() => string | null | Promise<string | null>) | undefined;
  private readonly timeoutMs: number;
  private readonly onTrace: ((trace: RequestTrace) => void) | undefined;
  private readonly now: () => number;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl;
    this.transport = options.transport ?? fetchTransport();
    this.accessToken = options.accessToken;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.onTrace = options.onTrace;
    this.now = options.now ?? (() => Date.now());
  }

  async get<T>(path: string, options: GetOptions = {}): Promise<ApiResult<T>> {
    return this.send<T>("GET", path, options, undefined, undefined);
  }

  async mutate<T, TBody = unknown>(
    method: "POST" | "PUT" | "PATCH" | "DELETE",
    path: string,
    options: MutateOptions<TBody>,
  ): Promise<ApiResult<T>> {
    const { idempotencyKey, body, expectedVersion, expectedRevision, ...rest } = options;
    const payload = asRecord(body) ?? (body === undefined ? {} : null);
    if (payload === null) {
      throw new TypeError("Mutation body must be an object so version fields can be merged.");
    }
    const withVersions: Record<string, unknown> = {
      ...payload,
      ...(expectedVersion === undefined ? {} : { expected_version: expectedVersion }),
      ...(expectedRevision === undefined ? {} : { expected_revision: expectedRevision }),
    };
    return this.send<T>(method, path, rest, withVersions, idempotencyKey);
  }

  /** Unauthenticated liveness probe; typed from the generated contract. */
  async health(options: GetOptions = {}): Promise<ApiResult<HealthData>> {
    return this.get<HealthData>("/health", options);
  }

  private async send<T>(
    method: string,
    path: string,
    options: GetOptions,
    body: Record<string, unknown> | undefined,
    idempotencyKey: IdempotencyKey | undefined,
  ): Promise<ApiResult<T>> {
    // Wired before the first await: a caller that aborts synchronously after
    // calling us must still cancel the request.
    const timeoutMs = options.timeoutMs ?? this.timeoutMs;
    const controller = new AbortController();
    let timedOut = false;
    const abortCaller = (): void => controller.abort();
    if (options.signal?.aborted === true) {
      controller.abort();
    } else {
      options.signal?.addEventListener("abort", abortCaller, { once: true });
    }
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const startedAt = this.now();

    const headers: Record<string, string> = { accept: "application/json" };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
    }
    if (idempotencyKey !== undefined) {
      headers["idempotency-key"] = idempotencyKey;
    }
    const token = await this.accessToken?.();
    if (token !== null && token !== undefined && token !== "") {
      headers["authorization"] = `Bearer ${token}`;
    }

    try {
      if (controller.signal.aborted) {
        throw new ApiError({
          kind: timedOut ? "timeout" : "canceled",
          message: timedOut ? "Request timed out." : "Request canceled.",
        });
      }
      const response = await this.transport({
        method,
        url: joinUrl(this.baseUrl, path, options.query),
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      }).catch((cause: unknown) => {
        // A caller abort is a cancellation, not a failure the UI should report.
        if (!timedOut && options.signal?.aborted === true) {
          throw new ApiError({ kind: "canceled", message: "Request canceled.", cause });
        }
        throw cause;
      });

      let envelope: Record<string, unknown> | null = null;
      try {
        envelope = asRecord(JSON.parse(response.text) as unknown);
      } catch {
        envelope = null;
      }
      const requestId = readRequestId(envelope);
      this.onTrace?.({
        method,
        path,
        status: response.status,
        requestId,
        durationMs: this.now() - startedAt,
      });

      if (response.status >= 400) {
        throw failureToError(response.status, envelope);
      }
      if (envelope === null || !("data" in envelope) || requestId === undefined) {
        throw new ApiError({
          kind: "malformed",
          status: response.status,
          requestId,
          message: "Response did not match the ProofPath envelope.",
        });
      }
      return { data: envelope["data"] as T, requestId };
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", abortCaller);
    }
  }
}
