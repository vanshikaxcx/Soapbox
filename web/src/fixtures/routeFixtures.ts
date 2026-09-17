/**
 * Deterministic route fixtures - WP-03's "Storybook-equivalent" harness
 * (POA §7: "deterministic Storybook-equivalent route fixtures or component
 * harness without inventing a second backend"). These are placeholders for
 * shapes WP-06/WP-08/WP-09/WP-10 will define for real; nothing here is a
 * live network call, and every consumer must keep working once those WPs
 * replace it with a fetch from an approved endpoint.
 */
import type {
  BasketSummary,
  ConversationTurn,
  EvidenceRecord,
  ExactQuote,
  ProgressStage,
  PurchaseStatus,
  RecoveryCase,
} from "../components/cards/types";

export const fixtureConversation: ConversationTurn[] = [
  { id: "t1", role: "assistant", text: "What would you like to buy today?" },
  { id: "t2", role: "shopper", text: "2 litres of milk and a loaf of bread." },
  { id: "t3", role: "assistant", text: "Got it — comparing that across two nearby stores now." },
];

export const fixtureBaskets: BasketSummary[] = [
  {
    merchant: "GreenMart",
    mode: "fixture",
    confidence: "complete",
    totalPaise: 26_800,
    lines: [
      { id: "l1", name: "Toned milk", brand: "Amul", quantity: "2 L", pricePaise: 11_000 },
      { id: "l2", name: "Whole wheat bread", brand: undefined, quantity: "1 loaf", pricePaise: 4_500 },
    ],
  },
  {
    merchant: "QuickBasket",
    mode: "fixture",
    confidence: "estimated",
    totalPaise: 27_900,
    lines: [
      { id: "l1", name: "Toned milk", brand: "Amul", quantity: "2 L", pricePaise: 11_400 },
      { id: "l2", name: "Whole wheat bread", brand: "Britannia", quantity: "1 loaf", pricePaise: 5_200 },
    ],
  },
];

export const fixtureProgressStages: ProgressStage[] = [
  { id: "search", label: "Searching merchants", status: "done" },
  { id: "compare", label: "Comparing baskets", status: "done" },
  { id: "repair", label: "Repairing basket", status: "active" },
  { id: "recheck", label: "Rechecking prices", status: "pending" },
];

export const fixtureEvidence: EvidenceRecord[] = [
  {
    merchant: "GreenMart",
    locality: "Koramangala, Bengaluru",
    fetchedAt: "2026-09-15T09:12:00Z",
    sourceUrl: "https://example-merchant.invalid/greenmart/search",
    mode: "fixture",
    freshnessLabel: "Fetched 4 minutes ago",
  },
];

export const fixtureQuote: ExactQuote = {
  quoteId: "01J8Z6QUOTE00000000000001",
  quoteHash: "sha256:fixture-hash",
  version: 1,
  seller: "GreenMart",
  currency: "INR",
  chargesPaise: 3_000,
  totalPaise: 29_800,
  deliveryTerms: "Delivery within 45 minutes",
  expiresAt: new Date(Date.now() + 120_000).toISOString(),
  lines: [
    { id: "l1", name: "Toned milk", quantity: "2 L", pricePaise: 11_000 },
    { id: "l2", name: "Whole wheat bread", quantity: "1 loaf", pricePaise: 4_500 },
  ],
};

export const fixturePurchaseStatus: PurchaseStatus = {
  purchaseId: "01J8Z6PURCHASE0000000001",
  payment: "succeeded",
  order: "unknown",
  refund: "none",
};

export const fixtureCase: RecoveryCase = {
  caseId: "01J8Z6CASE000000000000001",
  status: "Awaiting merchant confirmation",
  openedAt: "2026-09-15T09:40:00Z",
  facts: [
    { label: "Payment", status: "known", detail: "Charged ₹298.00" },
    { label: "Order", status: "unknown", detail: "No confirmation from merchant yet" },
    { label: "Refund", status: "unknown", detail: undefined },
  ],
};
