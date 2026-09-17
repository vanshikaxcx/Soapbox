import type { ProgressStage } from "./types";

const ICON: Record<ProgressStage["status"], string> = {
  pending: "○",
  active: "◐",
  done: "●",
  failed: "✕",
};

export function ProgressCard({ stages }: { stages: ProgressStage[] }) {
  return (
    <ol className="pp-card pp-progress" aria-label="Progress">
      {stages.map((stage) => (
        <li key={stage.id} className={`pp-progress__stage pp-progress__stage--${stage.status}`}>
          <span aria-hidden="true">{ICON[stage.status]}</span>
          <span>{stage.label}</span>
          <span className="pp-visually-hidden">
            {stage.status === "active" ? " (in progress)" : ` (${stage.status})`}
          </span>
        </li>
      ))}
    </ol>
  );
}
