import type { MoneyPaise } from "./types";

/** INR paise -> display string. Formatting only; never do money math in floats. */
export function formatPaise(paise: MoneyPaise | null): string {
  if (paise === null) {
    return "Unknown";
  }
  return `₹${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
