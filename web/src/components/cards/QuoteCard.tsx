import { useState } from "react";
import { formatPaise } from "./format";
import type { ExactQuote } from "./types";
import { SimulatedCheckoutNotice } from "./NoticeCard";

export interface QuoteCardProps {
  quote: ExactQuote;
  /**
   * The ONLY call site allowed to trigger simulated approval (SPEC/AGENTS.md
   * invariant: only the dedicated `Approve simulated ₹X` touch control may
   * call the approval endpoint - not voice, not conversational text, not a
   * model or agent tool). Disabled while a submission is in flight so a
   * double-tap can't fire two intents.
   */
  onApprove: () => void | Promise<void>;
  disabled?: boolean;
}

export function QuoteCard({ quote, onApprove, disabled = false }: QuoteCardProps) {
  const [submitting, setSubmitting] = useState(false);
  const busy = disabled || submitting;

  const handleApprove = (): void => {
    if (busy) {
      return;
    }
    setSubmitting(true);
    void Promise.resolve(onApprove()).finally(() => setSubmitting(false));
  };

  return (
    <section className="pp-card pp-quote" aria-label={`Exact quote from ${quote.seller}`}>
      <SimulatedCheckoutNotice />
      <h3>{quote.seller}</h3>
      <ul className="pp-quote__lines">
        {quote.lines.map((line) => (
          <li key={line.id} className="pp-quote__line">
            <span>{line.name}</span>
            <span>{line.quantity}</span>
            <span>{formatPaise(line.pricePaise)}</span>
          </li>
        ))}
      </ul>
      <dl className="pp-quote__totals">
        <div>
          <dt>Charges &amp; fees</dt>
          <dd>{formatPaise(quote.chargesPaise)}</dd>
        </div>
        <div>
          <dt>Total ({quote.currency})</dt>
          <dd>{formatPaise(quote.totalPaise)}</dd>
        </div>
        <div>
          <dt>Delivery</dt>
          <dd>{quote.deliveryTerms}</dd>
        </div>
      </dl>
      <p className="pp-quote__expiry">Quote expires {new Date(quote.expiresAt).toLocaleTimeString()}</p>
      <button
        type="button"
        className="pp-button pp-button--primary pp-button--approve"
        onClick={handleApprove}
        disabled={busy}
        aria-busy={submitting}
      >
        {submitting ? "Approving…" : `Approve simulated ${formatPaise(quote.totalPaise)}`}
      </button>
    </section>
  );
}
