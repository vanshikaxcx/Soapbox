import { ApiError } from "./errors";

export interface TransportRequest {
  method: string;
  /** Absolute URL, already joined with the base URL and query string. */
  url: string;
  headers: Record<string, string>;
  body: string | undefined;
  signal: AbortSignal | undefined;
}

export interface TransportResponse {
  status: number;
  /** Raw body text; the client owns envelope parsing so fakes stay trivial. */
  text: string;
}

/**
 * The single seam between the client and the network. Tests inject a function;
 * nothing below this line knows about `fetch`, so no test needs MSW or a second
 * backend to exercise error mapping (WP-03: no second backend).
 */
export type Transport = (
  request: TransportRequest,
) => Promise<TransportResponse>;

export function fetchTransport(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Transport {
  return async (request) => {
    let response: Response;
    try {
      response = await fetchImpl(request.url, {
        method: request.method,
        headers: request.headers,
        ...(request.body === undefined ? {} : { body: request.body }),
        ...(request.signal === undefined ? {} : { signal: request.signal }),
      });
    } catch (cause) {
      throw new ApiError({
        kind: request.signal?.aborted === true ? "timeout" : "network",
        message:
          request.signal?.aborted === true
            ? "Request timed out."
            : "Could not reach ProofPath.",
        cause,
      });
    }
    return { status: response.status, text: await response.text() };
  };
}
