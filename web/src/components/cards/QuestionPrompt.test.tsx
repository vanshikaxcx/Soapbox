import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QuestionPrompt } from "./QuestionPrompt";
import type { ConversationQuestion } from "./types";

const question: ConversationQuestion = {
  id: "q1",
  prompt: "Which milk brand?",
  options: [
    { id: "o1", label: "Amul" },
    { id: "o2", label: "Mother Dairy" },
  ],
};

describe("QuestionPrompt", () => {
  it("renders the prompt and every option as a button, calling onAnswer with the option's id", () => {
    const onAnswer = vi.fn();
    render(<QuestionPrompt question={question} onAnswer={onAnswer} />);

    expect(screen.getByText("Which milk brand?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mother Dairy" }));
    expect(onAnswer).toHaveBeenCalledWith("o2");
  });

  it("disables every option button while submitting", () => {
    render(<QuestionPrompt question={question} onAnswer={vi.fn()} disabled />);
    for (const button of screen.getAllByRole("button")) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
  });
});
