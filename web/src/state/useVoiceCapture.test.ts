import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useVoiceCapture } from "./useVoiceCapture";

function fakeStream(): MediaStream {
  const track = { stop: vi.fn() };
  return { getTracks: () => [track] } as unknown as MediaStream;
}

describe("useVoiceCapture", () => {
  it("goes idle -> requesting -> recording, streams partials into onTranscriptUpdate, then returns to idle on the final one and stops the tracks", async () => {
    const stream = fakeStream();
    const getMicStream = vi.fn().mockResolvedValue(stream);
    let emit: ((text: string, isFinal: boolean) => void) | undefined;
    const stopTranscribe = vi.fn();
    const transcribe = vi.fn((_stream: MediaStream, onUpdate: (text: string, isFinal: boolean) => void) => {
      emit = onUpdate;
      return stopTranscribe;
    });
    const onTranscriptUpdate = vi.fn();

    const { result } = renderHook(() => useVoiceCapture(onTranscriptUpdate, { getMicStream, transcribe }));
    expect(result.current.state).toBe("idle");

    act(() => {
      result.current.start();
    });
    expect(result.current.state).toBe("requesting");

    await waitFor(() => expect(result.current.state).toBe("recording"));

    act(() => {
      emit?.("2", false);
    });
    expect(onTranscriptUpdate).toHaveBeenCalledWith("2");
    expect(result.current.state).toBe("recording");

    act(() => {
      emit?.("2 litres of milk", true);
    });
    expect(onTranscriptUpdate).toHaveBeenCalledWith("2 litres of milk");
    expect(result.current.state).toBe("idle");
    expect(stopTranscribe).toHaveBeenCalledTimes(1);
    expect((stream.getTracks()[0] as { stop: () => void }).stop).toHaveBeenCalledTimes(1);
  });

  it("stop() before any final update still tears down the stream and transcription", async () => {
    const stream = fakeStream();
    const stopTranscribe = vi.fn();
    const getMicStream = vi.fn().mockResolvedValue(stream);
    const transcribe = vi.fn().mockReturnValue(stopTranscribe);

    const { result } = renderHook(() => useVoiceCapture(vi.fn(), { getMicStream, transcribe }));
    act(() => {
      result.current.start();
    });
    await waitFor(() => expect(result.current.state).toBe("recording"));

    act(() => {
      result.current.stop();
    });
    expect(result.current.state).toBe("idle");
    expect(stopTranscribe).toHaveBeenCalledTimes(1);
  });

  it("maps a permission-denied failure to state 'denied', never crashing", async () => {
    const getMicStream = vi.fn().mockRejectedValue(new DOMException("no", "NotAllowedError"));
    const { result } = renderHook(() => useVoiceCapture(vi.fn(), { getMicStream }));

    act(() => {
      result.current.start();
    });
    await waitFor(() => expect(result.current.state).toBe("denied"));
  });

  it("maps a missing-device failure to state 'no-device'", async () => {
    const getMicStream = vi.fn().mockRejectedValue(new DOMException("no", "NotFoundError"));
    const { result } = renderHook(() => useVoiceCapture(vi.fn(), { getMicStream }));

    act(() => {
      result.current.start();
    });
    await waitFor(() => expect(result.current.state).toBe("no-device"));
  });

  it("maps an unrecognized failure to state 'error'", async () => {
    const getMicStream = vi.fn().mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useVoiceCapture(vi.fn(), { getMicStream }));

    act(() => {
      result.current.start();
    });
    await waitFor(() => expect(result.current.state).toBe("error"));
  });
});
