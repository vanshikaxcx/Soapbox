import { useEffect, useState } from "react";
import type { RefObject } from "react";

export type PlaybackStatus = "idle" | "loading" | "ready" | "error";

export interface PollyPlaybackDeps {
  /** Real Polly doesn't exist yet (P4) - this fixture returns a tiny real, playable audio clip. */
  synthesize?: (text: string) => Promise<{ audioUrl: string; caption: string }>;
}

export interface UsePollyPlaybackResult {
  status: PlaybackStatus;
  caption: string | null;
  audioUrl: string | null;
  /** True only after a real `play()` call was actually rejected by the browser's autoplay policy. */
  autoplayBlocked: boolean;
}

// A minimal, valid, silent WAV - real audio a browser can actually load and play, not a placeholder path.
const FIXTURE_AUDIO_DATA_URI =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

function defaultSynthesize(
  text: string,
): Promise<{ audioUrl: string; caption: string }> {
  return Promise.resolve({ audioUrl: FIXTURE_AUDIO_DATA_URI, caption: text });
}

/**
 * Polly caption/audio state and the autoplay fallback (WP-05). The `<audio>`
 * element/ref belongs to the caller (PlaybackCard) - this hook only decides
 * *when* to attempt a real autoplay and reports whether the browser actually
 * rejected it, exactly like the mic's real getUserMedia permission handling.
 */
export function usePollyPlayback(
  text: string,
  audioRef: RefObject<HTMLAudioElement | null>,
  deps: PollyPlaybackDeps = {},
): UsePollyPlaybackResult {
  const synthesize = deps.synthesize ?? defaultSynthesize;
  const [status, setStatus] = useState<PlaybackStatus>("idle");
  const [caption, setCaption] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [autoplayBlocked, setAutoplayBlocked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Resetting to "loading" when `text` changes is this hook's own state,
    // not derivable during render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus("loading");
    setAutoplayBlocked(false);
    void synthesize(text)
      .then((result) => {
        if (cancelled) {
          return;
        }
        setCaption(result.caption);
        setAudioUrl(result.audioUrl);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [text, synthesize]);

  useEffect(() => {
    if (audioUrl === null) {
      return;
    }
    const audio = audioRef.current;
    if (audio === null) {
      return;
    }
    // Wrapped in Promise.resolve(): jsdom's play() returns undefined rather
    // than a real Promise (a test-environment gap only - real browsers
    // always return one), which would otherwise throw on `.then`.
    Promise.resolve(audio.play())
      .then(() => setAutoplayBlocked(false))
      .catch(() => setAutoplayBlocked(true));
  }, [audioUrl, audioRef]);

  return { status, caption, audioUrl, autoplayBlocked };
}
