import { formatPaise } from "./format";
import type { BasketSummary } from "./types";

const CONFIDENCE_LABEL: Record<BasketSummary["confidence"], string> = {
  complete: "All fees included",
  estimated: "Fees estimated",
  unknown: "Fees unknown — may change at checkout",
};

export function BasketCard({
  merchant,
  lines,
  totalPaise,
  confidence,
  mode,
}: BasketSummary) {
  return (
    <section className="pp-card pp-basket" aria-label={`Basket at ${merchant}`}>
      <header className="pp-basket__header">
        <h3>{merchant}</h3>
        {mode === "fixture" && (
          <span className="pp-badge pp-badge--fixture">Fixture data</span>
        )}
      </header>
      <ul className="pp-basket__lines">
        {lines.map((line) => (
          <li key={line.id} className="pp-basket__line">
            <span className="pp-basket__name">
              {line.name}
              {line.brand !== undefined && (
                <span className="pp-basket__brand"> · {line.brand}</span>
              )}
            </span>
            <span className="pp-basket__quantity">{line.quantity}</span>
            <span className="pp-basket__price">
              {formatPaise(line.pricePaise)}
            </span>
          </li>
        ))}
      </ul>
      <footer className="pp-basket__footer">
        <span className="pp-basket__total">{formatPaise(totalPaise)}</span>
        <span
          className={`pp-badge pp-badge--${confidence}`}
          title={CONFIDENCE_LABEL[confidence]}
        >
          {CONFIDENCE_LABEL[confidence]}
        </span>
      </footer>
    </section>
  );
}
