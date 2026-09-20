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
  ConversationResponder,
  ConversationTurn,
  EvidenceRecord,
  ExactQuote,
  ProgressStage,
  PurchaseStatus,
  RecoveryCase,
  UnresolvedExtraction,
} from "../components/cards/types";
import { formatQuantity } from "../components/cards/format";
import { fakeExtractFromText } from "./fixtureExtractor";

export const fixtureConversation: ConversationTurn[] = [
  { id: "t1", role: "assistant", text: "What would you like to buy today?" },
];

const UNRESOLVED_COPY: Record<
  UnresolvedExtraction["reason_code"],
  (fragment: string) => string
> = {
  no_quantity_detected: (fragment) => `how much of "${fragment}" you need`,
  ambiguous_item: (fragment) => `which "${fragment}" you mean`,
  item_limit_exceeded: (fragment) =>
    `"${fragment}" - that's more than I can compare at once (max 4 items)`,
  extraction_unavailable: () => "that - please try again",
  no_items_detected: () => "anything I could shop for in that",
};

/**
 * Placeholder for P2's real `/tasks/extract` (WP-05, P2's slice) - runs the
 * exact same `ExtractionOutcome` shape through `fakeExtractFromText`, then
 * turns it into conversation copy. Per the extraction contract, an
 * unresolved item never comes with candidate options to choose from, so it's
 * re-prompted through this same canonical text path - not a fixed-choice
 * QuestionPrompt, which stays reserved for a genuine multiple-choice case.
 */
export const fixtureConversationResponder: ConversationResponder = (text) => {
  const outcome = fakeExtractFromText(text);
  const parts: string[] = [];

  if (outcome.items.length > 0) {
    const summary = outcome.items
      .map((item) => `${formatQuantity(item.quantity)} ${item.name}`)
      .join(", ");
    parts.push(`Got it — comparing ${summary} across two nearby stores now.`);
  }
  if (outcome.unresolved.length > 0) {
    const asks = outcome.unresolved.map((entry) =>
      UNRESOLVED_COPY[entry.reason_code](entry.raw_fragment),
    );
    parts.push(
      `I didn't catch ${asks.join(", or ")} — could you tell me again?`,
    );
  }

  return Promise.resolve({
    turn: {
      id: `a-${crypto.randomUUID()}`,
      role: "assistant",
      text: parts.join(" "),
    },
  });
};

export const fixtureBaskets: BasketSummary[] = [
  {
    merchant: "GreenMart",
    mode: "fixture",
    confidence: "complete",
    totalPaise: 26_800,
    lines: [
      {
        id: "l1",
        name: "Toned milk",
        brand: "Amul",
        quantity: "2 L",
        pricePaise: 11_000,
      },
      {
        id: "l2",
        name: "Whole wheat bread",
        brand: undefined,
        quantity: "1 loaf",
        pricePaise: 4_500,
      },
    ],
  },
  {
    merchant: "QuickBasket",
    mode: "fixture",
    confidence: "estimated",
    totalPaise: 27_900,
    lines: [
      {
        id: "l1",
        name: "Toned milk",
        brand: "Amul",
        quantity: "2 L",
        pricePaise: 11_400,
      },
      {
        id: "l2",
        name: "Whole wheat bread",
        brand: "Britannia",
        quantity: "1 loaf",
        pricePaise: 5_200,
      },
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
    {
      id: "l2",
      name: "Whole wheat bread",
      quantity: "1 loaf",
      pricePaise: 4_500,
    },
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
    {
      label: "Order",
      status: "unknown",
      detail: "No confirmation from merchant yet",
    },
    { label: "Refund", status: "unknown", detail: undefined },
  ],
};
