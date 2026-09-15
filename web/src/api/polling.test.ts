import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./errors";
import { DEFAULT_POLL_POLICY, pollUntilTerminal, type Scheduler, type Visibility } from "./polling";

/** Deterministic clock: sleeps advance virtual time instead of real time. */
function fakeScheduler(): Scheduler & { slept: number[] } {
  let clock = 0;
  const slept: number[] = [];
  return {
    slept,
    now: () => clock,
    sleep: (ms) => {
      slept.push(ms);
      clock += ms;
      return Promise.resolve();
    },
  };
}

function hiddenUntilCalls(visibleAfter: number): Visibility & { resumes: number } {
  let checks = 0;
  const state = {
    resumes: 0,
    isVisible: () => (checks += 1) > visibleAfter,
    whenVisible: () => {
      state.resumes += 1;
      return Promise.resolve();
    },
  };
  return state;
}

type Job = { status: "pending" | "succeeded" };
const isTerminal = (job: Job): boolean => job.status === "succeeded";

describe("pollUntilTerminal", () => {
  it("stops on the first terminal read", async () => {
    const poll = vi.fn<(signal?: AbortSignal) => Promise<Job>>().mockResolvedValue({ status: "succeeded" });
    const result = await pollUntilTerminal({ poll, isTerminal, scheduler: fakeScheduler() });
    expect(result).toMatchObject({ status: "terminal", attempts: 1 });
    expect(poll).toHaveBeenCalledTimes(1);
  });

  it("polls at 2s for the first attempts, then 5s", async () => {
    const scheduler = fakeScheduler();
    const responses: Job[] = Array.from({ length: 7 }, () => ({ status: "pending" }));
    responses.push({ status: "succeeded" });
    let i = 0;
    await pollUntilTerminal({
      poll: (): Promise<Job> => Promise.resolve(responses[i++] ?? { status: "succeeded" }),
      isTerminal,
      scheduler,
    });
    expect(scheduler.slept).toEqual([2000, 2000, 2000, 2000, 5000, 5000, 5000]);
  });

  it("gives up once the visible-time budget is spent", async () => {
    const scheduler = fakeScheduler();
    const result = await pollUntilTerminal({
      poll: () => Promise.resolve<Job>({ status: "pending" }),
      isTerminal,
      scheduler,
      policy: { ...DEFAULT_POLL_POLICY, maxVisibleDurationMs: 10_000 },
    });
    expect(result.status).toBe("deadline_exceeded");
    expect(result.attempts).toBeLessThan(10);
  });

  it("waits for the tab to come back instead of polling while hidden", async () => {
    const visibility = hiddenUntilCalls(1);
    await pollUntilTerminal({
      poll: () => Promise.resolve<Job>({ status: "succeeded" }),
      isTerminal,
      scheduler: fakeScheduler(),
      visibility,
    });
    expect(visibility.resumes).toBe(1);
  });

  it("survives a transient failure and reports it", async () => {
    const onTransientError = vi.fn();
    const poll = vi
      .fn<(signal?: AbortSignal) => Promise<Job>>()
      .mockRejectedValueOnce(new ApiError({ kind: "network", message: "offline" }))
      .mockResolvedValue({ status: "succeeded" });
    const result = await pollUntilTerminal({ poll, isTerminal, scheduler: fakeScheduler(), onTransientError });
    expect(result).toMatchObject({ status: "terminal", attempts: 2 });
    expect(onTransientError).toHaveBeenCalledOnce();
  });

  it("propagates a non-retryable failure instead of polling a dead job", async () => {
    const poll = vi.fn<(signal?: AbortSignal) => Promise<Job>>().mockRejectedValue(new ApiError({ kind: "not_found", message: "gone" }));
    await expect(pollUntilTerminal({ poll, isTerminal, scheduler: fakeScheduler() })).rejects.toMatchObject({
      kind: "not_found",
    });
    expect(poll).toHaveBeenCalledTimes(1);
  });
});
