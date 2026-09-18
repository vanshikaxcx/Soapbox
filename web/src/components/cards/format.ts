import type { ExtractedQuantity, MoneyPaise } from "./types";

/** INR paise -> display string. Formatting only; never do money math in floats. */
export function formatPaise(paise: MoneyPaise | null): string {
  if (paise === null) {
    return "Unknown";
  }
  return `₹${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** ISO timestamp -> locale date+time display string, shared so every card renders dates consistently. */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

/** ISO timestamp -> locale time-only display string. */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString();
}

/**
 * P2's real extraction contract reports quantity in canonical base units
 * (grams/millilitres/pieces) - never a float, never a display unit. This is
 * display formatting only, the inverse of P2's own base-unit conversion.
 */
export function formatQuantity({ value_base, dimension }: ExtractedQuantity): string {
  switch (dimension) {
    case "mass":
      return value_base % 1000 === 0 ? `${value_base / 1000} kg` : `${value_base} g`;
    case "volume":
      return value_base % 1000 === 0 ? `${value_base / 1000} L` : `${value_base} ml`;
    case "count":
      return value_base === 1 ? "1 pc" : `${value_base} pcs`;
  }
}
