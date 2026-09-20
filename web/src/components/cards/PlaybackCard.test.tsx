import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlaybackCard } from "./PlaybackCard";

describe("PlaybackCard", () => {
  it("renders the assistant's reply as a caption", async () => {
    render(<PlaybackCard text="Got it — comparing that now." />);
    await waitFor(() =>
      expect(screen.getByText("Got it — comparing that now.")).toBeTruthy(),
    );
  });
});
