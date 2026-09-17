import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AsyncStateView } from "../components/async/AsyncStateView";
import { QuoteCard } from "../components/cards/QuoteCard";
import { fixtureQuote } from "../fixtures/routeFixtures";
import { useFixtureAsyncState } from "../fixtures/useFixtureAsyncState";

/**
 * `/purchases/:id/approve` - the exact quote and its dedicated approval
 * control. Wiring `onApprove` to the real WP-08 endpoint (idempotency key,
 * expected_version, atomic approval-consumption) is that WP's job; this page
 * only guarantees the control exists, is the sole approval call site, and is
 * disabled while a submission is outstanding.
 */
export function PurchaseApprovePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const state = useFixtureAsyncState(fixtureQuote);

  const handleApprove = async (): Promise<void> => {
    setError(null);
    try {
      // Placeholder for WP-08's POST /purchases/:id/approve; not yet approved/contracted.
      await new Promise((resolve) => setTimeout(resolve, 400));
      void navigate(`/purchases/${id ?? ""}`);
    } catch {
      setError("Approval couldn't be completed. Please try again.");
    }
  };

  return (
    <div className="pp-page">
      <h1>Approve purchase</h1>
      <AsyncStateView state={state}>
        {(quote) => <QuoteCard quote={quote} onApprove={handleApprove} />}
      </AsyncStateView>
      {error !== null && (
        <p role="alert" className="pp-error__message">
          {error}
        </p>
      )}
    </div>
  );
}
