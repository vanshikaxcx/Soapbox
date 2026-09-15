import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";
import { ApiError, isApiError } from "./errors";
import { idempotencyKeyFor, memoryKeyStore } from "./idempotency";
import type { Transport, TransportRequest } from "./transport";

function envelope(status: number, text: string): Transport {
  return () => Promise.resolve({ status, text });
}

function errorEnvelope(status: number, code: string, message = "nope"): Transport {
  return envelope(status, JSON.stringify({ error: { code, message, details: null }, request_id: "req-1" }));
}

function recordingTransport(response: { status: number; text: string }): {
  transport: Transport;
  requests: TransportRequest[];
} {
  const requests: TransportRequest[] = [];
  return {
    requests,
    transport: (request) => {
      requests.push(request);
      return Promise.resolve(response);
    },
  };
}

const okHealth = JSON.stringify({ data: { status: "ok", time: "2026-09-15T13:25:44.293186Z" }, request_id: "req-1" });

describe("ApiClient envelope handling", () => {
  it("unwraps data and surfaces the request id", async () => {
    const client = new ApiClient({ baseUrl: "/api", transport: envelope(200, okHealth) });
    const result = await client.health();
    expect(result.data.status).toBe("ok");
    expect(result.requestId).toBe("req-1");
  });

  it("reports a 200 that is not a ProofPath envelope as malformed", async () => {
    const client = new ApiClient({ baseUrl: "/api", transport: envelope(200, JSON.stringify({ status: "ok" })) });
    await expect(client.health()).rejects.toMatchObject({ kind: "malformed" });
  });

  it("emits a trace for diagnostic mode", async () => {
    const onTrace = vi.fn();
    const client = new ApiClient({ baseUrl: "/api", transport: envelope(200, okHealth), onTrace });
    await client.health();
    expect(onTrace).toHaveBeenCalledWith(expect.objectContaining({ method: "GET", path: "/health", status: 200, requestId: "req-1" }));
  });
});

describe("ApiClient error mapping", () => {
  const cases: ReadonlyArray<[number, string, string]> = [
    [422, "validation_error", "validation"],
    [409, "conflict", "conflict"],
    [409, "stale_version", "stale_version"],
    [410, "expired", "expired"],
    [404, "not_found", "not_found"],
    [401, "unauthorized", "unauthorized"],
    [403, "forbidden", "forbidden"],
    [429, "rate_limited", "rate_limited"],
    [500, "internal_error", "server"],
  ];

  it.each(cases)("maps %i/%s to %s", async (status, code, kind) => {
    const client = new ApiClient({ baseUrl: "/api", transport: errorEnvelope(status, code) });
    const error = await client.health().catch((e: unknown) => e);
    expect(isApiError(error)).toBe(true);
    expect(error).toMatchObject({ kind, status, requestId: "req-1" });
  });

  it("falls back to status when the server sends no usable code", async () => {
    const client = new ApiClient({ baseUrl: "/api", transport: envelope(410, "<html>gateway</html>") });
    await expect(client.health()).rejects.toMatchObject({ kind: "expired", code: undefined });
  });

  it("treats an unlabelled 409 as a conflict, not a stale version", async () => {
    const client = new ApiClient({ baseUrl: "/api", transport: envelope(409, JSON.stringify({ request_id: "req-1" })) });
    await expect(client.health()).rejects.toMatchObject({ kind: "conflict" });
  });

  it("marks only transport, rate-limit and server failures retryable", () => {
    const retryable = new ApiError({ kind: "network", message: "x" }).retryable;
    const notRetryable = new ApiError({ kind: "stale_version", message: "x" }).retryable;
    expect([retryable, notRetryable]).toEqual([true, false]);
  });
});

describe("ApiClient mutations", () => {
  it("sends the idempotency key and merges expected_version into the body", async () => {
    const { transport, requests } = recordingTransport({ status: 200, text: okHealth });
    const client = new ApiClient({ baseUrl: "/api", transport });
    const key = idempotencyKeyFor("purchase-1", memoryKeyStore(), () => "key-abc");

    await client.mutate("POST", "/purchases/p1/approve", { idempotencyKey: key, body: { basket_id: "b1" }, expectedVersion: 3 });

    const sent = requests[0];
    expect(sent?.headers["idempotency-key"]).toBe("key-abc");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ basket_id: "b1", expected_version: 3 });
  });

  it("reuses one key across a retry of the same intent", () => {
    const store = memoryKeyStore();
    let n = 0;
    const uuid = (): string => `key-${(n += 1)}`;
    expect(idempotencyKeyFor("purchase-1", store, uuid)).toBe(idempotencyKeyFor("purchase-1", store, uuid));
  });

  it("attaches the bearer token resolved at request time", async () => {
    const { transport, requests } = recordingTransport({ status: 200, text: okHealth });
    const client = new ApiClient({ baseUrl: "/api", transport, accessToken: () => Promise.resolve("tok-1") });
    await client.health();
    expect(requests[0]?.headers["authorization"]).toBe("Bearer tok-1");
  });

  it("omits authorization when there is no session", async () => {
    const { transport, requests } = recordingTransport({ status: 200, text: okHealth });
    const client = new ApiClient({ baseUrl: "/api", transport, accessToken: () => null });
    await client.health();
    expect(requests[0]?.headers["authorization"]).toBeUndefined();
  });
});

describe("ApiClient cancellation", () => {
  it("reports a caller abort as canceled, not as a failure", async () => {
    const controller = new AbortController();
    const client = new ApiClient({
      baseUrl: "/api",
      transport: (request) =>
        new Promise<never>((_resolve, reject) => {
          request.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
        }),
    });
    const pending = client.health({ signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ kind: "canceled" });
  });
});
