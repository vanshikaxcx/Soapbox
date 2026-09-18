import { formatDateTime } from "./format";
import type { EvidenceRecord } from "./types";

export function EvidenceCard({
  merchant,
  locality,
  fetchedAt,
  sourceUrl,
  mode,
  freshnessLabel,
}: EvidenceRecord) {
  return (
    <section
      className="pp-card pp-evidence"
      aria-label={`Evidence from ${merchant}`}
    >
      <header className="pp-evidence__header">
        <h4>{merchant}</h4>
        <span className={`pp-badge pp-badge--${mode}`}>
          {mode === "live" ? "Live" : "Fixture data"}
        </span>
      </header>
      <dl>
        <div>
          <dt>Locality</dt>
          <dd>{locality}</dd>
        </div>
        <div>
          <dt>Fetched</dt>
          <dd>{formatDateTime(fetchedAt)}</dd>
        </div>
        <div>
          <dt>Freshness</dt>
          <dd>{freshnessLabel}</dd>
        </div>
      </dl>
      <a
        href={sourceUrl}
        target="_blank"
        rel="noreferrer noopener"
        className="pp-evidence__source"
      >
        View source
      </a>
    </section>
  );
}
