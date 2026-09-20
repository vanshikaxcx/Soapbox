import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UsualBasketCard } from "./UsualBasketCard";

describe("UsualBasketCard", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("offers to save the last shopper text, and saving reveals a Load usual button", () => {
    render(
      <UsualBasketCard lastShopperText="2 litres of milk" onLoad={vi.fn()} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save this as my usual" }),
    );

    expect(screen.getByText(/2 litres of milk/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Load usual" })).toBeTruthy();
  });

  it("Load usual calls onLoad with the saved text - the same canonical submit path, not a cached result", () => {
    const onLoad = vi.fn();
    render(
      <UsualBasketCard lastShopperText="2 litres of milk" onLoad={onLoad} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save this as my usual" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Load usual" }));

    expect(onLoad).toHaveBeenCalledWith("2 litres of milk");
  });

  it("has no Save button before anything has been said yet", () => {
    render(<UsualBasketCard lastShopperText={null} onLoad={vi.fn()} />);
    expect(
      screen.queryByRole("button", { name: "Save this as my usual" }),
    ).toBeNull();
  });
});
