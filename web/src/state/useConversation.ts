import { useCallback, useRef, useState } from "react";
import { ApiError, isApiError } from "../api/errors";
import type {
  ConversationQuestion,
  ConversationResponder,
  ConversationTurn,
} from "../components/cards/types";

export interface UseConversationOptions {
  initialTurns?: ConversationTurn[];
  /** Test-only override, same convention as idempotency.ts's newIdempotencyKey. */
  newId?: () => string;
}

function randomId(): string {
  return crypto.randomUUID();
}

export interface UseConversationResult {
  turns: ConversationTurn[];
  activeQuestion: ConversationQuestion | null;
  submitting: boolean;
  error: ApiError | null;
  /** A stale answerQuestion click - not a network/server error, so kept separate from `error`. Cleared on the next submit. */
  staleNotice: string | null;
  /**
   * The ONE canonical path: typing today, a later voice feature's final
   * transcript calls this exact function too - never a separate call site.
   */
  submit: (text: string) => void;
  /** Answers the currently active question by resubmitting its option's label through `submit`. */
  answerQuestion: (optionId: string) => void;
}

/**
 * Bridges a conversation to shopper-turn state (WP-05). `respond` is
 * injectable exactly like AuthProviderDeps/useAsyncResource's fetcher - a
 * fixture today, P2's real schema-bound extraction later, same call shape.
 */
export function useConversation(
  respond: ConversationResponder,
  options: UseConversationOptions = {},
): UseConversationResult {
  const newId = options.newId ?? randomId;
  const [turns, setTurns] = useState<ConversationTurn[]>(options.initialTurns ?? []);
  const [activeQuestion, setActiveQuestion] = useState<ConversationQuestion | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [staleNotice, setStaleNotice] = useState<string | null>(null);
  // A second guard alongside the `submitting` state: state drives the UI
  // (disabling the send/option buttons), but two synchronous calls to
  // `submit` before React re-renders would both still read the same
  // pre-update `submitting` value from this closure. The ref catches that
  // case too, so duplicate-submit prevention holds regardless of render timing.
  const submittingRef = useRef(false);

  const submit = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (trimmed === "" || submittingRef.current) {
        return;
      }
      submittingRef.current = true;
      const shopperTurn: ConversationTurn = { id: newId(), role: "shopper", text: trimmed };
      setTurns((prev) => [...prev, shopperTurn]);
      setActiveQuestion(null);
      setError(null);
      setStaleNotice(null);
      setSubmitting(true);

      void respond(trimmed, [...turns, shopperTurn])
        .then((result) => {
          setTurns((prev) => [...prev, result.turn]);
          setActiveQuestion(result.question ?? null);
        })
        .catch((cause: unknown) => {
          setError(isApiError(cause) ? cause : new ApiError({ kind: "server", message: "Something unexpected happened.", cause }));
        })
        .finally(() => {
          submittingRef.current = false;
          setSubmitting(false);
        });
    },
    [newId, respond, turns],
  );

  const answerQuestion = useCallback(
    (optionId: string) => {
      const option = activeQuestion?.options.find((candidate) => candidate.id === optionId);
      // A stale click - the question was already replaced or answered.
      // Nothing to submit, but the shopper should know why their tap did
      // nothing rather than it silently going nowhere.
      if (option === undefined) {
        setStaleNotice("That question isn't current anymore — go ahead and type your answer instead.");
        return;
      }
      submit(option.label);
    },
    [activeQuestion, submit],
  );

  return { turns, activeQuestion, submitting, error, staleNotice, submit, answerQuestion };
}
