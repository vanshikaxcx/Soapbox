import type {
  ExtractedDimension,
  ExtractedItem,
  ExtractionOutcome,
  UnresolvedExtraction,
} from "../components/cards/types";

/**
 * Deterministic placeholder for P2's real `/tasks/extract` (WP-05's
 * extraction contract, `docs/specs/WP-05-extraction-contract-p2.md`) - a
 * light regex heuristic, exactly what P2's own fake backend is, not a
 * substitute for the real Bedrock-backed one. Produces the identical
 * `ExtractionOutcome` shape so the UI mapping it feeds never changes when a
 * real fetch replaces this function.
 */
const MAX_ITEMS = 4;

// Longest alternative first in each unit group: regex alternation takes the
// first match, not the longest, so "l" before "litres" would truncate it.
const QUANTITY_PATTERN =
  /^(\d+(?:\.\d+)?)\s*(litres|litre|liters|liter|l|kilograms|kilogram|kg|grams|gram|g|ml)?\s*(?:of\s+)?(.+)$/i;

function toBaseUnits(
  quantityValue: number,
  unit: string | undefined,
): { value_base: number; dimension: ExtractedDimension } | null {
  switch (unit?.toLowerCase()) {
    case "l":
    case "litre":
    case "litres":
    case "liter":
    case "liters":
      return { value_base: Math.round(quantityValue * 1000), dimension: "volume" };
    case "ml":
      return { value_base: Math.round(quantityValue), dimension: "volume" };
    case "kg":
    case "kilogram":
    case "kilograms":
      return { value_base: Math.round(quantityValue * 1000), dimension: "mass" };
    case "g":
    case "gram":
    case "grams":
      return { value_base: Math.round(quantityValue), dimension: "mass" };
    case undefined:
      return { value_base: Math.round(quantityValue), dimension: "count" };
    default:
      return null;
  }
}

export function fakeExtractFromText(
  transcript: string,
  newId: () => string = () => crypto.randomUUID(),
): ExtractionOutcome {
  const fragments = transcript
    .split(/,|\band\b/i)
    .map((fragment) => fragment.trim())
    .filter((fragment) => fragment.length > 0);

  if (fragments.length === 0) {
    return {
      items: [],
      unresolved: [{ raw_fragment: transcript, reason_code: "no_items_detected", reason_detail: null }],
    };
  }

  const items: ExtractedItem[] = [];
  const unresolved: UnresolvedExtraction[] = [];

  for (const fragment of fragments) {
    if (items.length >= MAX_ITEMS) {
      unresolved.push({
        raw_fragment: fragment,
        reason_code: "item_limit_exceeded",
        reason_detail: `at most ${MAX_ITEMS} items are supported per request`,
      });
      continue;
    }
    const match = QUANTITY_PATTERN.exec(fragment);
    const quantity = match !== null ? toBaseUnits(Number(match[1]), match[2]) : null;
    const name = match?.[3]?.trim();
    if (quantity === null || name === undefined || name === "") {
      unresolved.push({ raw_fragment: fragment, reason_code: "no_quantity_detected", reason_detail: null });
      continue;
    }
    items.push({ item_id: newId(), name, quantity, hard_attributes: {}, flexibility: "exact_only" });
  }

  return { items, unresolved };
}
