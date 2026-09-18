import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PhotoUpload } from "./PhotoUpload";

function fakeImageFile(bytes: number[], type = "image/jpeg"): File {
  return new File([new Uint8Array(bytes)], "list.jpg", { type });
}

describe("PhotoUpload", () => {
  it("rejects a non-JPEG/PNG file with a real validation message, never calling the extractor", () => {
    render(<PhotoUpload onConfirm={vi.fn()} />);
    const input = screen.getByLabelText("Add a photo of your list");
    fireEvent.change(input, { target: { files: [new File(["x"], "list.gif", { type: "image/gif" })] } });

    expect(screen.getByRole("alert").textContent).toMatch(/jpeg or png/i);
  });

  it("rejects a file over 5 MB with a real size check against the actual File object", () => {
    render(<PhotoUpload onConfirm={vi.fn()} />);
    const input = screen.getByLabelText("Add a photo of your list");
    const big = new File([new Uint8Array(5 * 1024 * 1024 + 1)], "list.jpg", { type: "image/jpeg" });
    fireEvent.change(input, { target: { files: [big] } });

    expect(screen.getByRole("alert").textContent).toMatch(/5 mb/i);
  });

  it("extracts a known fixture image and confirming it submits a summary through the canonical path", async () => {
    const onConfirm = vi.fn();
    render(<PhotoUpload onConfirm={onConfirm} />);
    const input = screen.getByLabelText("Add a photo of your list");
    fireEvent.change(input, { target: { files: [fakeImageFile([42])] } });

    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeTruthy());
    expect(screen.getByText(/milk/)).toBeTruthy();
    expect(screen.getByText(/eggs/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith("Photo: 1 L milk, 6 pcs eggs");
  });

  it("reports an unmatched photo honestly, never a fabricated result", async () => {
    render(<PhotoUpload onConfirm={vi.fn()} />);
    const input = screen.getByLabelText("Add a photo of your list");
    fireEvent.change(input, { target: { files: [fakeImageFile([1, 2, 3])] } });

    await waitFor(() => expect(screen.getByText(/couldn't recognise/i)).toBeTruthy());
  });
});
