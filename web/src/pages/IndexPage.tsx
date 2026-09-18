import { useState } from "react";
import { useApiClient } from "../api/ApiProvider";
import { AsyncStateView } from "../components/async/AsyncStateView";
import { ConversationCard } from "../components/cards/ConversationCard";
import { ErrorCard } from "../components/cards/ErrorCard";
import { MicButton } from "../components/cards/MicButton";
import { NoticeCard } from "../components/cards/NoticeCard";
import { PhotoUpload } from "../components/cards/PhotoUpload";
import { PlaybackCard } from "../components/cards/PlaybackCard";
import { QuestionPrompt } from "../components/cards/QuestionPrompt";
import { TranscriptEditor } from "../components/cards/TranscriptEditor";
import { UsualBasketCard } from "../components/cards/UsualBasketCard";
import { useAsyncResource } from "../state/useAsyncResource";
import { useConversation } from "../state/useConversation";
import { useVoiceCapture } from "../state/useVoiceCapture";
import { fixtureConversation, fixtureConversationResponder } from "../fixtures/routeFixtures";

/**
 * `/` - entry point. WP-05's text/voice/photo/usual-basket intake slice: one
 * canonical submit path everything else funnels through, against fixtures
 * until P2's real extraction and P4's real Transcribe/Polly/S3 adapters land.
 */
export function IndexPage() {
  const client = useApiClient();
  const { state, retry } = useAsyncResource((signal) =>
    client.health({ signal }),
  );
  const { turns, activeQuestion, submitting, error, staleNotice, submit, answerQuestion } = useConversation(
    fixtureConversationResponder,
    { initialTurns: fixtureConversation },
  );
  const [draft, setDraft] = useState("");
  const voice = useVoiceCapture(setDraft);

  const lastAssistantTurn = turns.filter((turn) => turn.role === "assistant").at(-1) ?? null;
  const lastShopperTurn = turns.filter((turn) => turn.role === "shopper").at(-1) ?? null;

  return (
    <div className="pp-page">
      <h1>ProofPath</h1>
      <ConversationCard turns={turns} />
      {lastAssistantTurn !== null && <PlaybackCard key={lastAssistantTurn.id} text={lastAssistantTurn.text} />}
      {activeQuestion !== null && (
        <QuestionPrompt question={activeQuestion} onAnswer={answerQuestion} disabled={submitting} />
      )}
      {staleNotice !== null && <NoticeCard tone="warning" title={staleNotice} />}
      {error !== null && <ErrorCard error={error} />}
      <div className="pp-intake">
        <TranscriptEditor value={draft} onChange={setDraft} onSubmit={submit} disabled={submitting} />
        <MicButton state={voice.state} onStart={voice.start} onStop={voice.stop} disabled={submitting} />
      </div>
      <PhotoUpload onConfirm={submit} disabled={submitting} />
      <UsualBasketCard lastShopperText={lastShopperTurn?.text ?? null} onLoad={submit} disabled={submitting} />
      <section aria-label="API connectivity">
        <h2>Connection status</h2>
        <AsyncStateView state={state} onRetry={retry}>
          {(data) => <p>API reachable — status: {data.status}.</p>}
        </AsyncStateView>
      </section>
    </div>
  );
}
