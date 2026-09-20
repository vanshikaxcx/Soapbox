import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { AsyncStateView } from "../components/async/AsyncStateView";
import { RecoveryCard } from "../components/cards/RecoveryCard";
import { fixtureCase } from "../fixtures/routeFixtures";
import { useFixtureAsyncState } from "../fixtures/useFixtureAsyncState";

/** `/cases/:id` - read-only recovery view (WP-10 supplies the real case/guidance data). */
export function CasePage() {
  const { id } = useParams<{ id: string }>();
  const data = useMemo(
    () => ({ ...fixtureCase, caseId: id ?? fixtureCase.caseId }),
    [id],
  );
  const state = useFixtureAsyncState(data);

  return (
    <div className="pp-page">
      <h1>Case {id}</h1>
      <AsyncStateView state={state}>
        {(recoveryCase) => <RecoveryCard {...recoveryCase} />}
      </AsyncStateView>
    </div>
  );
}
