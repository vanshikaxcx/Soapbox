import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { AsyncStateView } from "../components/async/AsyncStateView";
import { BasketCard } from "../components/cards/BasketCard";
import { EvidenceCard } from "../components/cards/EvidenceCard";
import { ProgressCard } from "../components/cards/ProgressCard";
import { fixtureBaskets, fixtureEvidence, fixtureProgressStages } from "../fixtures/routeFixtures";
import { useFixtureAsyncState } from "../fixtures/useFixtureAsyncState";

/** `/searches/:id` - two-source comparison. Real data lands with WP-06's contract. */
export function SearchPage() {
  const { id } = useParams<{ id: string }>();
  const searchData = useMemo(() => ({ baskets: fixtureBaskets, evidence: fixtureEvidence }), []);
  const state = useFixtureAsyncState(searchData);

  return (
    <div className="pp-page">
      <h1>Search {id}</h1>
      <ProgressCard stages={fixtureProgressStages} />
      <AsyncStateView state={state} emptyLabel="No baskets could be compared yet.">
        {(data, partial) => (
          <>
            {partial && <p role="status">One source is still missing — showing what we have so far.</p>}
            <div className="pp-search__baskets">
              {data.baskets.map((basket) => (
                <BasketCard key={basket.merchant} {...basket} />
              ))}
            </div>
            <div className="pp-search__evidence">
              {data.evidence.map((evidence) => (
                <EvidenceCard key={evidence.merchant} {...evidence} />
              ))}
            </div>
          </>
        )}
      </AsyncStateView>
    </div>
  );
}
