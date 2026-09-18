import type { ConversationTurn } from "./types";

export function ConversationCard({ turns }: { turns: ConversationTurn[] }) {
  return (
    <div
      className="pp-card pp-conversation"
      role="log"
      aria-label="Conversation"
    >
      {turns.map((turn) => (
        <p
          key={turn.id}
          className={`pp-conversation__turn pp-conversation__turn--${turn.role}`}
        >
          <span className="pp-visually-hidden">
            {turn.role === "assistant" ? "ProofPath: " : "You: "}
          </span>
          {turn.text}
        </p>
      ))}
    </div>
  );
}
