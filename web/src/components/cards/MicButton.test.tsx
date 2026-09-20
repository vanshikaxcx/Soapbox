import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MicButton } from "./MicButton";

describe("MicButton", () => {
  it("calls onStart when idle and clicked", () => {
    const onStart = vi.fn();
    render(<MicButton state="idle" onStart={onStart} onStop={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("calls onStop when recording and clicked, and reflects the pressed state", () => {
    const onStop = vi.fn();
    render(<MicButton state="recording" onStart={vi.fn()} onStop={onStop} />);
    const button = screen.getByRole("button", { name: "Stop recording" });
    expect(button.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(button);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("disables the button and shows a fallback-to-typing notice for every failure state", () => {
    for (const state of [
      "denied",
      "no-device",
      "unsupported",
      "error",
    ] as const) {
      const { unmount } = render(
        <MicButton state={state} onStart={vi.fn()} onStop={vi.fn()} />,
      );
      expect(
        screen.getByRole("button", { name: "Record" }).hasAttribute("disabled"),
      ).toBe(true);
      expect(screen.getByText(/you can still type your list/i)).toBeTruthy();
      unmount();
    }
  });

  it("disables the button while requesting permission", () => {
    render(<MicButton state="requesting" onStart={vi.fn()} onStop={vi.fn()} />);
    expect(
      screen
        .getByRole("button", { name: "Requesting…" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });
});
