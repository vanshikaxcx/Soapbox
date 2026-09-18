import type { ConversationQuestion } from "./types";

export interface QuestionPromptProps {
  question: ConversationQuestion;
  onAnswer: (optionId: string) => void;
  disabled?: boolean;
}

/** The active clarification question - fixed choices, not free text (WP-05). */
export function QuestionPrompt({ question, onAnswer, disabled = false }: QuestionPromptProps) {
  return (
    <div className="pp-card pp-question" role="group" aria-label={question.prompt}>
      <p className="pp-question__prompt">{question.prompt}</p>
      <div className="pp-question__options">
        {question.options.map((option) => (
          <button
            key={option.id}
            type="button"
            className="pp-button pp-button--secondary"
            onClick={() => onAnswer(option.id)}
            disabled={disabled}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
