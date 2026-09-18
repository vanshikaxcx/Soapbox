import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePollyPlayback } from "./usePollyPlayback";

function fakeAudioRef(playImpl: () => Promise<void>) {
  const audio = { play: vi.fn(playImpl) } as unknown as HTMLAudioElement;
  return { current: audio };
}

describe("usePollyPlayback", () => {
  it("synthesizes the text and attempts a real play(), reporting no block on success", async () => {
    const synthesize = vi.fn().mockResolvedValue({ audioUrl: "data:audio/wav;base64,AA==", caption: "Got it." });
    const audioRef = fakeAudioRef(() => Promise.resolve());

    const { result } = renderHook(() => usePollyPlayback("Got it.", audioRef, { synthesize }));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(result.current.caption).toBe("Got it.");
    await waitFor(() => expect(audioRef.current.play).toHaveBeenCalledTimes(1));
    expect(result.current.autoplayBlocked).toBe(false);
  });

  it("reports autoplayBlocked when the real play() call is rejected", async () => {
    const synthesize = vi.fn().mockResolvedValue({ audioUrl: "data:audio/wav;base64,AA==", caption: "Got it." });
    const audioRef = fakeAudioRef(() => Promise.reject(new DOMException("no", "NotAllowedError")));

    const { result } = renderHook(() => usePollyPlayback("Got it.", audioRef, { synthesize }));
    await waitFor(() => expect(result.current.autoplayBlocked).toBe(true));
  });

  it("moves to status 'error' when synthesis itself fails, never crashing", async () => {
    const synthesize = vi.fn().mockRejectedValue(new Error("boom"));
    const audioRef = fakeAudioRef(() => Promise.resolve());

    const { result } = renderHook(() => usePollyPlayback("Got it.", audioRef, { synthesize }));
    await waitFor(() => expect(result.current.status).toBe("error"));
  });

  it("re-synthesizes when the text changes", async () => {
    const synthesize = vi
      .fn()
      .mockResolvedValueOnce({ audioUrl: "data:audio/wav;base64,AA==", caption: "First." })
      .mockResolvedValueOnce({ audioUrl: "data:audio/wav;base64,BB==", caption: "Second." });
    const audioRef = fakeAudioRef(() => Promise.resolve());

    const { result, rerender } = renderHook(({ text }) => usePollyPlayback(text, audioRef, { synthesize }), {
      initialProps: { text: "first" },
    });
    await waitFor(() => expect(result.current.caption).toBe("First."));

    act(() => {
      rerender({ text: "second" });
    });
    await waitFor(() => expect(result.current.caption).toBe("Second."));
    expect(synthesize).toHaveBeenCalledTimes(2);
  });
});
