import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useUsualBasket } from "./useUsualBasket";
import { fakeStorage } from "../test/fakeStorage";

describe("useUsualBasket", () => {
  it("starts with nothing saved when storage is empty", () => {
    const { result } = renderHook(() =>
      useUsualBasket({ storage: fakeStorage() }),
    );
    expect(result.current.saved).toBeNull();
  });

  it("save() persists to storage and is readable on the next mount - a real round trip", () => {
    const storage = fakeStorage();
    const now = () => 1_000_000;
    const { result } = renderHook(() => useUsualBasket({ storage, now }));

    act(() => {
      result.current.save("2 litres of milk");
    });
    expect(result.current.saved).toEqual({
      text: "2 litres of milk",
      savedAt: new Date(1_000_000).toISOString(),
    });

    const { result: reloaded } = renderHook(() =>
      useUsualBasket({ storage, now }),
    );
    expect(reloaded.current.saved?.text).toBe("2 litres of milk");
  });

  it("is not stale just after saving, and stale once past the freshness window", () => {
    const storage = fakeStorage();
    let clock = 1_000_000;
    const now = () => clock;
    const { result } = renderHook(() => useUsualBasket({ storage, now }));

    act(() => {
      result.current.save("bread");
    });
    expect(result.current.isStale).toBe(false);

    clock += 25 * 60 * 60 * 1000; // 25h later
    const { result: later } = renderHook(() =>
      useUsualBasket({ storage, now }),
    );
    expect(later.current.isStale).toBe(true);
  });

  it("clear() removes the saved record", () => {
    const storage = fakeStorage();
    const { result } = renderHook(() =>
      useUsualBasket({ storage, now: () => 1 }),
    );

    act(() => {
      result.current.save("milk");
    });
    expect(result.current.saved).not.toBeNull();

    act(() => {
      result.current.clear();
    });
    expect(result.current.saved).toBeNull();
    expect(storage.getItem("proofpath.usual_basket")).toBeNull();
  });
});
