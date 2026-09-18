import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useConversation } from "./useConversation";
import { ApiError } from "../api/errors";
import type { ConversationResponder } from "../components/cards/types";

function sequentialIds(): () => string {
  let n = 0;
  return () => `id-${(n += 1)}`;
}

describe("useConversation", () => {
  it("submits text through the canonical path and appends both turns", async () => {
    const respond: ConversationResponder = vi.fn().mockResolvedValue({
      turn: { id: "a1", role: "assistant", text: "Got it." },
    });
    const { result } = renderHook(() => useConversation(respond, { newId: sequentialIds() }));

    act(() => {
      result.current.submit("2 litres of milk");
    });

    expect(result.current.turns).toEqual([{ id: "id-1", role: "shopper", text: "2 litres of milk" }]);
    expect(result.current.submitting).toBe(true);

    await waitFor(() => expect(result.current.submitting).toBe(false));
    expect(result.current.turns).toHaveLength(2);
    expect(result.current.turns[1]).toEqual({ id: "a1", role: "assistant", text: "Got it." });
    expect(respond).toHaveBeenCalledWith("2 litres of milk", [
      { id: "id-1", role: "shopper", text: "2 litres of milk" },
    ]);
  });

  it("ignores empty/whitespace-only text - never appends a turn or calls respond", () => {
    const respond: ConversationResponder = vi.fn();
    const { result } = renderHook(() => useConversation(respond));

    act(() => {
      result.current.submit("   ");
    });

    expect(result.current.turns).toHaveLength(0);
    expect(respond).not.toHaveBeenCalled();
  });

  it("a duplicate submit while one is already in flight only calls respond once", async () => {
    let resolveRespond: (() => void) | undefined;
    const respond: ConversationResponder = vi.fn(
      () =>
        new Promise<{ turn: { id: string; role: "assistant"; text: string } }>((resolve) => {
          resolveRespond = () => resolve({ turn: { id: "a1", role: "assistant", text: "Got it." } });
        }),
    );
    const { result } = renderHook(() => useConversation(respond, { newId: sequentialIds() }));

    act(() => {
      result.current.submit("first");
      result.current.submit("second");
    });

    expect(respond).toHaveBeenCalledTimes(1);
    expect(result.current.turns).toEqual([{ id: "id-1", role: "shopper", text: "first" }]);

    await act(async () => {
      resolveRespond?.();
      await Promise.resolve();
    });
  });

  it("answering the active question resubmits its option's label through the same submit path", async () => {
    const respond: ConversationResponder = vi
      .fn()
      .mockResolvedValueOnce({
        turn: { id: "a1", role: "assistant", text: "Which milk?" },
        question: { id: "q1", prompt: "Which milk?", options: [{ id: "o1", label: "Amul" }] },
      })
      .mockResolvedValueOnce({ turn: { id: "a2", role: "assistant", text: "Got it." } });
    const { result } = renderHook(() => useConversation(respond, { newId: sequentialIds() }));

    act(() => {
      result.current.submit("milk");
    });
    await waitFor(() => expect(result.current.activeQuestion).not.toBeNull());

    act(() => {
      result.current.answerQuestion("o1");
    });

    await waitFor(() => expect(result.current.activeQuestion).toBeNull());
    expect(respond).toHaveBeenLastCalledWith(
      "Amul",
      expect.arrayContaining([expect.objectContaining({ text: "Amul" })]),
    );
  });

  it("answering a stale question - already replaced/cleared - is a no-op", () => {
    const respond: ConversationResponder = vi.fn().mockResolvedValue({
      turn: { id: "a1", role: "assistant", text: "Got it." },
    });
    const { result } = renderHook(() => useConversation(respond, { newId: sequentialIds() }));

    // No question has ever been active, so "o1" cannot resolve to anything.
    act(() => {
      result.current.answerQuestion("o1");
    });

    expect(respond).not.toHaveBeenCalled();
    expect(result.current.turns).toHaveLength(0);
  });

  it("on failure, keeps the shopper's turn visible, surfaces the error, and re-enables submission", async () => {
    const respond: ConversationResponder = vi
      .fn()
      .mockRejectedValue(new ApiError({ kind: "network", message: "offline" }));
    const { result } = renderHook(() => useConversation(respond, { newId: sequentialIds() }));

    act(() => {
      result.current.submit("2 litres of milk");
    });
    await waitFor(() => expect(result.current.submitting).toBe(false));

    expect(result.current.turns).toEqual([{ id: "id-1", role: "shopper", text: "2 litres of milk" }]);
    expect(result.current.error?.kind).toBe("network");

    // Re-enabled: a follow-up submit is not blocked by the earlier failure.
    act(() => {
      result.current.submit("retry");
    });
    expect(result.current.submitting).toBe(true);
  });
});
