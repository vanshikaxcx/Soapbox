import { useState } from "react";
import { useApiClient } from "../api/ApiProvider";
import { AsyncStateView } from "../components/async/AsyncStateView";
import { ConversationCard } from "../components/cards/ConversationCard";
import { ErrorCard } from "../components/cards/ErrorCard";
import { MicButton } from "../components/cards/MicButton";
import { QuestionPrompt } from "../components/cards/QuestionPrompt";
import { TranscriptEditor } from "../components/cards/TranscriptEditor";
import { useAsyncResource } from "../state/useAsyncResource";
import { useConversation } from "../state/useConversation";
import { useVoiceCapture } from "../state/useVoiceCapture";
import { fixtureConversation, fixtureConversationResponder } from "../fixtures/routeFixtures";

/**
 * `/` - entry point. WP-05's text/voice-intake slice: one canonical submit
 * path (typing or a final voice transcript both write to `draft`, only
 * `submit` moves it into the conversation), against a fixture responder
 * until P2's real extraction lands and a fixture transcript stream until
 * P4's Transcribe adapter lands.
 */
export function IndexPage() {
  const client = useApiClient();
  const { state, retry } = useAsyncResource((signal) =>
    client.health({ signal }),
  );
  const { turns, activeQuestion, submitting, error, submit, answerQuestion } = useConversation(
    fixtureConversationResponder,
    { initialTurns: fixtureConversation },
  );
  const [draft, setDraft] = useState("");
  const voice = useVoiceCapture(setDraft);

  return (
    <div className="pp-page">
      <h1>ProofPath</h1>
      <ConversationCard turns={turns} />
      {activeQuestion !== null && (
        <QuestionPrompt question={activeQuestion} onAnswer={answerQuestion} disabled={submitting} />
      )}
      {error !== null && <ErrorCard error={error} />}
      <div className="pp-intake">
        <TranscriptEditor value={draft} onChange={setDraft} onSubmit={submit} disabled={submitting} />
        <MicButton state={voice.state} onStart={voice.start} onStop={voice.stop} disabled={submitting} />
      </div>
      <section aria-label="API connectivity">
        <h2>Connection status</h2>
        <AsyncStateView state={state} onRetry={retry}>
          {(data) => <p>API reachable — status: {data.status}.</p>}
        </AsyncStateView>
      </section>
    </div>
  );
}
