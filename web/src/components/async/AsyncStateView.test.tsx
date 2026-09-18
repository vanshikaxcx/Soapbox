import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/errors";
import type { AsyncState } from "../../state/asyncState";
import { AsyncStateView } from "./AsyncStateView";

function renderState(state: AsyncState<string>, onRetry?: () => void) {
  return render(
    <AsyncStateView state={state} onRetry={onRetry}>
      {(data, partial) => (
        <span>
          data:{data} partial:{String(partial)}
        </span>
      )}
    </AsyncStateView>,
  );
}

describe("AsyncStateView", () => {
  it("shows a loading indicator", () => {
    renderState({ status: "loading" });
    expect(screen.getByRole("status").textContent).toContain("Loading");
  });

  it("shows the empty message", () => {
    renderState({ status: "empty" });
    expect(screen.getByText("Nothing here yet.")).toBeTruthy();
  });

  it("renders success data with partial=false", () => {
    renderState({ status: "success", data: "milk" });
    expect(screen.getByText("data:milk partial:false")).toBeTruthy();
  });

  it("renders partial data with partial=true", () => {
    renderState({ status: "partial", data: "milk" });
    expect(screen.getByText("data:milk partial:true")).toBeTruthy();
  });

  it("renders stale data alongside a refresh notice", () => {
    const onRetry = vi.fn();
    renderState(
      {
        status: "stale",
        data: "milk",
        error: new ApiError({ kind: "stale_version", message: "x" }),
      },
      onRetry,
    );
    expect(screen.getByText("data:milk partial:true")).toBeTruthy();
    expect(screen.getByText(/changed since you last looked/i)).toBeTruthy();
    screen.getByText("Refresh").click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders a retryable error with a retry action", () => {
    const onRetry = vi.fn();
    renderState(
      {
        status: "error",
        error: new ApiError({ kind: "network", message: "x" }),
      },
      onRetry,
    );
    expect(screen.getByRole("alert").textContent).toContain("connection");
    screen.getByText("Try again").click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("does not offer retry for a non-retryable error", () => {
    renderState(
      {
        status: "error",
        error: new ApiError({ kind: "forbidden", message: "x" }),
      },
      vi.fn(),
    );
    expect(screen.queryByText("Try again")).toBeNull();
  });

  it("renders an expired state without a retry action", () => {
    renderState(
      {
        status: "expired",
        error: new ApiError({ kind: "expired", message: "x" }),
      },
      vi.fn(),
    );
    expect(screen.getByRole("alert").textContent).toContain("expired");
    expect(screen.queryByText("Try again")).toBeNull();
  });
});
