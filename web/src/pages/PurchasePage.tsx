import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { AsyncStateView } from "../components/async/AsyncStateView";
import { PurchaseStatusCard } from "../components/cards/PurchaseStatusCard";
import { SimulatedCheckoutNotice } from "../components/cards/NoticeCard";
import { fixturePurchaseStatus } from "../fixtures/routeFixtures";
import { useFixtureAsyncState } from "../fixtures/useFixtureAsyncState";

/** `/purchases/:id` - durable status across reload (WP-09/WP-10 supply the real facts). */
export function PurchasePage() {
  const { id } = useParams<{ id: string }>();
  const data = useMemo(
    () => ({
      ...fixturePurchaseStatus,
      purchaseId: id ?? fixturePurchaseStatus.purchaseId,
    }),
    [id],
  );
  const state = useFixtureAsyncState(data);

  return (
    <div className="pp-page">
      <h1>Purchase {id}</h1>
      <SimulatedCheckoutNotice />
      <AsyncStateView state={state}>
        {(status) => <PurchaseStatusCard {...status} />}
      </AsyncStateView>
    </div>
  );
}
