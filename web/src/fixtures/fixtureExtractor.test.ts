import { describe, expect, it } from "vitest";
import { fakeExtractFromImage, fakeExtractFromText } from "./fixtureExtractor";

function sequentialIds(): () => string {
  let n = 0;
  return () => `id-${(n += 1)}`;
}

describe("fakeExtractFromText", () => {
  it("resolves a quantity+unit+name fragment into an Item in canonical base units", () => {
    const outcome = fakeExtractFromText("2 litres of milk", sequentialIds());
    expect(outcome.items).toEqual([
      {
        item_id: "id-1",
        name: "milk",
        quantity: { value_base: 2000, dimension: "volume" },
        hard_attributes: {},
        flexibility: "exact_only",
      },
    ]);
    expect(outcome.unresolved).toEqual([]);
  });

  it("splits on 'and'/',' and resolves each fragment independently", () => {
    const outcome = fakeExtractFromText("2 litres of milk and 500 g cheese", sequentialIds());
    expect(outcome.items).toHaveLength(2);
    expect(outcome.items[1]).toMatchObject({ name: "cheese", quantity: { value_base: 500, dimension: "mass" } });
  });

  it("reports a fragment with no detectable quantity as unresolved, never guessed", () => {
    const outcome = fakeExtractFromText("a loaf of bread", sequentialIds());
    expect(outcome.items).toEqual([]);
    expect(outcome.unresolved).toEqual([
      { raw_fragment: "a loaf of bread", reason_code: "no_quantity_detected", reason_detail: null },
    ]);
  });

  it("treats a bare number with no unit as a count", () => {
    const outcome = fakeExtractFromText("3 avocados", sequentialIds());
    expect(outcome.items[0]).toMatchObject({ name: "avocados", quantity: { value_base: 3, dimension: "count" } });
  });

  it("reports no_items_detected when nothing at all was said", () => {
    const outcome = fakeExtractFromText("   ", sequentialIds());
    expect(outcome.items).toEqual([]);
    expect(outcome.unresolved).toEqual([{ raw_fragment: "   ", reason_code: "no_items_detected", reason_detail: null }]);
  });

  it("caps at 4 items and reports the rest as item_limit_exceeded, never silently dropped", () => {
    const outcome = fakeExtractFromText(
      "1 kg rice and 1 kg flour and 1 kg sugar and 1 kg salt and 1 kg pepper",
      sequentialIds(),
    );
    expect(outcome.items).toHaveLength(4);
    expect(outcome.unresolved).toEqual([
      { raw_fragment: "1 kg pepper", reason_code: "item_limit_exceeded", reason_detail: "at most 4 items are supported per request" },
    ]);
  });
});

describe("fakeExtractFromImage", () => {
  it("resolves a known fixture image to its canned items", () => {
    const outcome = fakeExtractFromImage(new Uint8Array([42]), sequentialIds());
    expect(outcome.unresolved).toEqual([]);
    expect(outcome.items).toEqual([
      { item_id: "id-1", name: "milk", quantity: { value_base: 1000, dimension: "volume" }, hard_attributes: {}, flexibility: "exact_only" },
      { item_id: "id-2", name: "eggs", quantity: { value_base: 6, dimension: "count" }, hard_attributes: {}, flexibility: "exact_only" },
    ]);
  });

  it("reports extraction_unavailable for any image that isn't a known fixture, never a guess", () => {
    const outcome = fakeExtractFromImage(new Uint8Array([1, 2, 3]), sequentialIds());
    expect(outcome.items).toEqual([]);
    expect(outcome.unresolved).toEqual([
      { raw_fragment: "<image>", reason_code: "extraction_unavailable", reason_detail: "no matching fixture for this image" },
    ]);
  });
});
