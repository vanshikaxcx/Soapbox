import { Link } from "react-router-dom";
import type { PurchaseStatus } from "./types";

/**
 * Renders payment/order/refund as three independent fields, never a single
 * derived "purchase status" (SPEC/AGENTS.md: "payment success does not prove
 * an order exists; refund pending is not refund completed").
 */
export function PurchaseStatusCard({ purchaseId, payment, order, refund }: PurchaseStatus) {
  const ambiguous = payment === "succeeded" && order === "unknown";
  return (
    <section className="pp-card pp-purchase-status" aria-label={`Purchase ${purchaseId} status`}>
      <dl>
        <div>
          <dt>Payment</dt>
          <dd>{payment}</dd>
        </div>
        <div>
          <dt>Order</dt>
          <dd>{order}</dd>
        </div>
        <div>
          <dt>Refund</dt>
          <dd>{refund}</dd>
        </div>
      </dl>
      {ambiguous && (
        <p role="alert">
          We can't yet confirm the merchant placed your order.{" "}
          <Link to={`/cases/${purchaseId}`}>See what we know and your options</Link>.
        </p>
      )}
    </section>
  );
}
