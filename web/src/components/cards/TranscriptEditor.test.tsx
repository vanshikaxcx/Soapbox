import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  TranscriptEditor,
  type TranscriptEditorProps,
} from "./TranscriptEditor";

/** TranscriptEditor is fully controlled (voice and typing share one draft) - this harness plays the role of the parent that owns the draft state, same as IndexPage does. */
function ControlledHarness(
  props: Omit<TranscriptEditorProps, "value" | "onChange"> & {
    initial?: string;
  },
) {
  const [value, setValue] = useState(props.initial ?? "");
  return <TranscriptEditor {...props} value={value} onChange={setValue} />;
}

describe("TranscriptEditor", () => {
  it("submits the typed text and clears the draft", () => {
    const onSubmit = vi.fn();
    render(<ControlledHarness onSubmit={onSubmit} />);

    const input = screen.getByLabelText("Message");
    fireEvent.change(input, { target: { value: "2 litres of milk" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(onSubmit).toHaveBeenCalledWith("2 litres of milk");
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("submits on Enter (form submit), not just the button", () => {
    const onSubmit = vi.fn();
    render(<ControlledHarness onSubmit={onSubmit} />);

    const input = screen.getByLabelText("Message");
    fireEvent.change(input, { target: { value: "bread" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(onSubmit).toHaveBeenCalledWith("bread");
  });

  it("renders whatever the parent's value is - a voice feature can populate it the same way typing does", () => {
    render(
      <TranscriptEditor
        value="2 litres of milk"
        onChange={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByLabelText<HTMLInputElement>("Message").value).toBe(
      "2 litres of milk",
    );
  });

  it("disables the input and send button while submitting", () => {
    render(
      <TranscriptEditor
        value=""
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        disabled
      />,
    );

    expect(screen.getByLabelText<HTMLInputElement>("Message").disabled).toBe(
      true,
    );
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Send" }).disabled,
    ).toBe(true);
  });

  it("disables Send for empty/whitespace-only text", () => {
    render(<ControlledHarness onSubmit={vi.fn()} />);
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion -- see above
    const sendButton = screen.getByRole("button", {
      name: "Send",
    }) as HTMLButtonElement;
    expect(sendButton.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "   " },
    });
    expect(sendButton.disabled).toBe(true);
  });
});
