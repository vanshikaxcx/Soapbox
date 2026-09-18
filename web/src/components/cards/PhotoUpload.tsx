import { useState } from "react";
import { fakeExtractFromImage } from "../../fixtures/fixtureExtractor";
import { formatQuantity } from "./format";
import type { ExtractionOutcome } from "./types";

export interface PhotoUploadProps {
  /** Confirmed result, summarized as text - flows through the same canonical submit path as typing/voice. */
  onConfirm: (summary: string) => void;
  disabled?: boolean;
}

const MAX_BYTES = 5 * 1024 * 1024;
const ALLOWED_TYPES = new Set(["image/jpeg", "image/png"]);

type Stage =
  | { status: "idle" }
  | { status: "invalid"; reason: string }
  | { status: "extracting" }
  | { status: "ready"; outcome: ExtractionOutcome }
  | { status: "error" };

/**
 * Photo issue/verify/extract/confirm lifecycle (WP-05). Real file input and
 * real client-side validation against the actual File object - only
 * "extract" (image -> items) is fixture-backed, mirroring P2's real image
 * extraction path exactly. EXIF stripping isn't implemented here - a real
 * gap in this skeleton, not a silent omission.
 */
export function PhotoUpload({ onConfirm, disabled = false }: PhotoUploadProps) {
  const [stage, setStage] = useState<Stage>({ status: "idle" });

  const handleFile = (file: File): void => {
    if (!ALLOWED_TYPES.has(file.type)) {
      setStage({ status: "invalid", reason: "Only JPEG or PNG photos are supported." });
      return;
    }
    if (file.size > MAX_BYTES) {
      setStage({ status: "invalid", reason: "That photo is larger than 5 MB." });
      return;
    }
    setStage({ status: "extracting" });
    // FileReader, not file.arrayBuffer(): broader real-world support, and
    // notably jsdom (this project's own test environment) doesn't implement
    // arrayBuffer() on File at all.
    const reader = new FileReader();
    reader.onload = () => {
      const buffer = reader.result;
      if (!(buffer instanceof ArrayBuffer)) {
        setStage({ status: "error" });
        return;
      }
      setStage({ status: "ready", outcome: fakeExtractFromImage(new Uint8Array(buffer)) });
    };
    reader.onerror = () => setStage({ status: "error" });
    reader.readAsArrayBuffer(file);
  };

  const handleConfirm = (): void => {
    if (stage.status !== "ready") {
      return;
    }
    const summary = stage.outcome.items.map((item) => `${formatQuantity(item.quantity)} ${item.name}`).join(", ");
    onConfirm(summary === "" ? "Photo: nothing recognised" : `Photo: ${summary}`);
    setStage({ status: "idle" });
  };

  return (
    <div className="pp-card pp-photo-upload">
      <label htmlFor="pp-photo-input" className="pp-photo-upload__label">
        Add a photo of your list
      </label>
      <input
        id="pp-photo-input"
        type="file"
        accept="image/jpeg,image/png"
        disabled={disabled || stage.status === "extracting"}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file !== undefined) {
            handleFile(file);
          }
        }}
      />
      {stage.status === "invalid" && (
        <p className="pp-photo-upload__error" role="alert">
          {stage.reason}
        </p>
      )}
      {stage.status === "extracting" && <p role="status">Reading your photo…</p>}
      {stage.status === "error" && <p role="alert">Something went wrong reading that photo. Please try again.</p>}
      {stage.status === "ready" && (
        <div className="pp-photo-upload__result">
          {stage.outcome.items.length > 0 ? (
            <ul>
              {stage.outcome.items.map((item) => (
                <li key={item.item_id}>
                  {formatQuantity(item.quantity)} {item.name}
                </li>
              ))}
            </ul>
          ) : (
            <p>I couldn't recognise anything in that photo.</p>
          )}
          {stage.outcome.unresolved.length > 0 && <p>Some parts weren't clear and won't be included.</p>}
          <button type="button" className="pp-button pp-button--primary" onClick={handleConfirm} disabled={disabled}>
            Confirm
          </button>
        </div>
      )}
    </div>
  );
}
