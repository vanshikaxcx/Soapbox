import type { MoneyPaise } from "./types";

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
