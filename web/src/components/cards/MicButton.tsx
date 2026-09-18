import type { MicState } from "../../state/useVoiceCapture";

export interface MicButtonProps {
  state: MicState;
  onStart: () => void;
  onStop: () => void;
  disabled?: boolean;
}

const NOTICE_BY_STATE: Partial<Record<MicState, string>> = {
  denied: "Microphone access was denied. You can still type your list.",
  "no-device": "No microphone was found. You can still type your list.",
  unsupported: "Voice input isn't supported in this browser. You can still type your list.",
  error: "Something went wrong starting the microphone. You can still type your list.",
};

/** Voice remains the primary interaction, typing the reliable fallback (WP-05) - every failure notice says so explicitly. */
export function MicButton({ state, onStart, onStop, disabled = false }: MicButtonProps) {
  const isRecording = state === "recording";
  const notice = NOTICE_BY_STATE[state];

  return (
    <div className="pp-mic">
      <button
        type="button"
        className="pp-button pp-button--secondary pp-mic__button"
        onClick={isRecording ? onStop : onStart}
        disabled={disabled || state === "requesting" || notice !== undefined}
        aria-pressed={isRecording}
      >
        {isRecording ? "Stop recording" : state === "requesting" ? "Requesting…" : "Record"}
      </button>
      {notice !== undefined && (
        <p className="pp-mic__notice" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
