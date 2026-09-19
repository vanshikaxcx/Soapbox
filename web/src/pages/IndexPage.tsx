import { useApiClient } from "../api/ApiProvider";
import { AsyncStateView } from "../components/async/AsyncStateView";
import { ConversationCard } from "../components/cards/ConversationCard";
import { useAsyncResource } from "../state/useAsyncResource";
import { fixtureConversation } from "../fixtures/routeFixtures";

/**
 * `/` - entry point. Voice/text/photo/usual-basket intake is WP-05's scope;
 * this page proves the authenticated client/route/card wiring end to end
 * with a real call to `/health` plus fixture conversation state.
 */
export function IndexPage() {
  const client = useApiClient();
  const { state, retry } = useAsyncResource((signal) =>
    client.health({ signal }),
  );

  return (
    <div className="pp-page">
      <h1>ProofPath</h1>
      <ConversationCard turns={fixtureConversation} />
      <section aria-label="API connectivity">
        <h2>Connection status</h2>
        <AsyncStateView state={state} onRetry={retry}>
          {(data) => <p>API reachable — status: {data.status}.</p>}
        </AsyncStateView>
      </section>
    </div>
  );
}
