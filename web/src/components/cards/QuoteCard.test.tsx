import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QuoteCard } from "./QuoteCard";
import { fixtureQuote } from "../../fixtures/routeFixtures";

describe("QuoteCard", () => {
  it("labels the control with the exact simulated total and calls onApprove when activated", async () => {
    const onApprove = vi.fn();
    render(<QuoteCard quote={fixtureQuote} onApprove={onApprove} />);

    const button = screen.getByRole("button", { name: /approve simulated/i });
    expect(button.textContent).toContain("₹298.00");
    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
    });
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it("disables the control while a submission is in flight, so a second tap cannot fire twice", async () => {
    let resolveApproval: () => void = () => undefined;
    const onApprove = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveApproval = resolve;
        }),
    );
    render(<QuoteCard quote={fixtureQuote} onApprove={onApprove} />);

    const button = screen.getByRole("button", { name: /approve simulated/i });
    act(() => {
      fireEvent.click(button);
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(onApprove).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveApproval();
      await Promise.resolve();
    });
  });

  it("always shows the simulated-checkout label", () => {
    render(<QuoteCard quote={fixtureQuote} onApprove={vi.fn()} />);
    expect(screen.getByText(/simulated checkout/i)).toBeTruthy();
    expect(screen.getByText(/no money moved/i)).toBeTruthy();
    expect(screen.getByText(/no retailer order placed/i)).toBeTruthy();
  });
});
