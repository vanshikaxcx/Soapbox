import { formatDateTime } from "./format";
import type { RecoveryCase } from "./types";

const FACT_LABEL: Record<RecoveryCase["facts"][number]["status"], string> = {
  known: "Known",
  unknown: "Unknown",
  contradictory: "Conflicting reports",
};

/**
 * Read-only, by construction: this card has no action that submits payment,
 * creates an order, or initiates a refund (SPEC/AGENTS.md - recovery may
 * only read/query existing facts).
 */
export function RecoveryCard({ caseId, status, openedAt, facts }: RecoveryCase) {
  return (
    <section className="pp-card pp-recovery" aria-label={`Case ${caseId}`}>
      <header>
        <h3>Case {caseId}</h3>
        <p>
          Status: {status} · opened {formatDateTime(openedAt)}
        </p>
      </header>
      <dl className="pp-recovery__facts">
        {facts.map((fact) => (
          <div key={fact.label} className={`pp-recovery__fact pp-recovery__fact--${fact.status}`}>
            <dt>{fact.label}</dt>
            <dd>
              {FACT_LABEL[fact.status]}
              {fact.detail !== undefined && <span> — {fact.detail}</span>}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
