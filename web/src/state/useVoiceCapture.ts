import { useCallback, useRef, useState } from "react";

export type MicState =
  | "idle"
  | "requesting"
  | "recording"
  | "denied"
  | "no-device"
  | "unsupported"
  | "error";

export interface VoiceCaptureDeps {
  /** Real by default: navigator.mediaDevices.getUserMedia. Injectable so tests never touch a real device. */
  getMicStream?: () => Promise<MediaStream>;
  /**
   * Real Transcribe streaming doesn't exist yet (P4/WP-01) - this is a
   * fixture stand-in. Ignores the real audio (nothing to send it to), emits
   * a canned partial sequence then a final transcript via `onUpdate`, and
   * returns a stop function. `isFinal` on the last call ends recording.
   */
  transcribe?: (
    stream: MediaStream,
    onUpdate: (text: string, isFinal: boolean) => void,
  ) => () => void;
}

export interface UseVoiceCaptureResult {
  state: MicState;
  start: () => void;
  stop: () => void;
}

const FIXTURE_PARTIALS = ["2", "2 litres", "2 litres of milk"];

function defaultGetMicStream(): Promise<MediaStream> {
  if (navigator.mediaDevices?.getUserMedia === undefined) {
    return Promise.reject(
      new DOMException("getUserMedia is not available", "NotSupportedError"),
    );
  }
  return navigator.mediaDevices.getUserMedia({ audio: true });
}

function defaultTranscribe(
  _stream: MediaStream,
  onUpdate: (text: string, isFinal: boolean) => void,
): () => void {
  const timers = FIXTURE_PARTIALS.map((partial, index) =>
    setTimeout(
      () => onUpdate(partial, index === FIXTURE_PARTIALS.length - 1),
      (index + 1) * 500,
    ),
  );
  return () => timers.forEach(clearTimeout);
}

function stateForError(error: unknown): MicState {
  if (error instanceof DOMException) {
    if (error.name === "NotSupportedError") {
      return "unsupported";
    }
    if (
      error.name === "NotAllowedError" ||
      error.name === "PermissionDeniedError" ||
      error.name === "SecurityError"
    ) {
      return "denied";
    }
    if (
      error.name === "NotFoundError" ||
      error.name === "DevicesNotFoundError"
    ) {
      return "no-device";
    }
  }
  return "error";
}

/**
 * Mic capture UI's data source (WP-05). Real getUserMedia permission
 * handling - `denied`/`no-device`/`unsupported` are genuine browser states,
 * not simulated - with a fixture transcript stream standing in for real
 * Transcribe until P4's adapter exists. Every update flows through
 * `onTranscriptUpdate`, the same draft state typing writes to, so voice
 * never bypasses the shopper's review before they hit Send.
 */
export function useVoiceCapture(
  onTranscriptUpdate: (text: string) => void,
  deps: VoiceCaptureDeps = {},
): UseVoiceCaptureResult {
  const getMicStream = deps.getMicStream ?? defaultGetMicStream;
  const transcribe = deps.transcribe ?? defaultTranscribe;
  const [state, setState] = useState<MicState>("idle");
  const cleanupRef = useRef<(() => void) | null>(null);

  const cleanup = useCallback((): void => {
    cleanupRef.current?.();
    cleanupRef.current = null;
  }, []);

  const stop = useCallback((): void => {
    cleanup();
    setState("idle");
  }, [cleanup]);

  const start = useCallback((): void => {
    setState("requesting");
    void getMicStream()
      .then((stream) => {
        setState("recording");
        const stopTranscribe = transcribe(stream, (text, isFinal) => {
          onTranscriptUpdate(text);
          if (isFinal) {
            stop();
          }
        });
        cleanupRef.current = () => {
          stopTranscribe();
          for (const track of stream.getTracks()) {
            track.stop();
          }
        };
      })
      .catch((error: unknown) => {
        setState(stateForError(error));
      });
  }, [getMicStream, transcribe, onTranscriptUpdate, stop]);

  return { state, start, stop };
}
