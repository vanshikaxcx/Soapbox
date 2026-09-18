export interface NoticeAction {
  label: string;
  onClick: () => void;
}

export interface NoticeCardProps {
  tone: "info" | "warning" | "simulated";
  title: string;
  body?: string;
  action?: NoticeAction | undefined;
}

/**
 * Also the vehicle for the non-negotiable simulated-checkout label (SPEC/AGENTS.md):
 * "Simulated checkout · no money moved · no retailer order placed."
 */
export function NoticeCard({ tone, title, body, action }: NoticeCardProps) {
  return (
    <div
      className={`pp-card pp-notice pp-notice--${tone}`}
      role={tone === "warning" ? "alert" : "status"}
    >
      <p className="pp-notice__title">{title}</p>
      {body !== undefined && <p className="pp-notice__body">{body}</p>}
      {action !== undefined && (
        <button
          type="button"
          className="pp-button pp-button--secondary"
          onClick={action.onClick}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

export function SimulatedCheckoutNotice() {
  return (
    <NoticeCard
      tone="simulated"
      title="Simulated checkout · no money moved · no retailer order placed."
      body="This entire purchase flow is a simulation for demonstration purposes."
    />
  );
}
