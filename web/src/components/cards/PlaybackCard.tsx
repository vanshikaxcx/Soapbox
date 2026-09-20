import { useRef } from "react";
import { usePollyPlayback } from "../../state/usePollyPlayback";

export interface PlaybackCardProps {
  text: string;
}

/** Renders the assistant's reply as Polly caption + audio, with a real autoplay-rejection fallback (WP-05). */
export function PlaybackCard({ text }: PlaybackCardProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const { status, caption, audioUrl, autoplayBlocked } = usePollyPlayback(
    text,
    audioRef,
  );

  if (status === "error") {
    return null;
  }

  return (
    <div
      className="pp-card pp-playback"
      role="status"
      aria-label="Assistant voice reply"
    >
      {audioUrl !== null && (
        <audio ref={audioRef} src={audioUrl} className="pp-visually-hidden" />
      )}
      {caption !== null && <p className="pp-playback__caption">{caption}</p>}
      {autoplayBlocked && (
        <button
          type="button"
          className="pp-button pp-button--secondary"
          onClick={() => {
            void audioRef.current?.play();
          }}
        >
          Play
        </button>
      )}
    </div>
  );
}
