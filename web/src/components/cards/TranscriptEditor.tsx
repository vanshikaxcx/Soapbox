import type { FormEvent } from "react";

export interface TranscriptEditorProps {
  value: string;
  onChange: (text: string) => void;
  onSubmit: (text: string) => void;
  disabled?: boolean;
}

/**
 * The editable text box WP-05 names explicitly: typing writes to `value`
 * directly; a later voice feature's partial/final transcript writes to the
 * exact same `value` via `onChange` - controlled by the caller so both
 * sources share one reviewable, editable draft before the shopper submits
 * through the one canonical `onSubmit` path.
 */
export function TranscriptEditor({
  value,
  onChange,
  onSubmit,
  disabled = false,
}: TranscriptEditorProps) {
  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (disabled) {
      return;
    }
    onSubmit(value);
    onChange("");
  };

  return (
    <form className="pp-transcript-editor" onSubmit={handleSubmit}>
      <label htmlFor="pp-transcript-input" className="pp-visually-hidden">
        Message
      </label>
      <input
        id="pp-transcript-input"
        type="text"
        className="pp-transcript-editor__input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        placeholder="Speak or type your list…"
        autoComplete="off"
      />
      <button
        type="submit"
        className="pp-button pp-button--primary"
        disabled={disabled || value.trim() === ""}
      >
        Send
      </button>
    </form>
  );
}
