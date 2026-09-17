import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the accessible development baseline", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "ProofPath" })).not.toBeNull();
    expect(screen.getByText("Development baseline")).not.toBeNull();
  });
});
