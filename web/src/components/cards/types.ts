/**
 * Shell-local shapes for the shared cards. These are WP-03's own fixture
 * types, not the API contract - WP-02/06/08/09/10 own the real schemas and
 * will land in `api/generated/schema.d.ts` once approved. Keeping these
 * separate means adopting the real contract later is a mapping change at the
 * route boundary, not a card rewrite.
 */

export type MoneyPaise = number;

export interface BasketLine {
  id: string;
  name: string;
  brand: string | undefined;
  quantity: string;
  pricePaise: MoneyPaise | null;
}

export type TotalConfidence = "complete" | "estimated" | "unknown";

export interface BasketSummary {
  merchant: string;
  lines: BasketLine[];
  totalPaise: MoneyPaise | null;
  confidence: TotalConfidence;
  mode: "live" | "fixture";
}

export interface QuoteLine {
  id: string;
  name: string;
  quantity: string;
  pricePaise: MoneyPaise;
}

export interface ExactQuote {
  quoteId: string;
  quoteHash: string;
  version: number;
  seller: string;
  lines: QuoteLine[];
  chargesPaise: MoneyPaise;
  totalPaise: MoneyPaise;
  currency: "INR";
  deliveryTerms: string;
  expiresAt: string;
}

export type ProgressStageStatus = "pending" | "active" | "done" | "failed";

export interface ProgressStage {
  id: string;
  label: string;
  status: ProgressStageStatus;
}

export interface EvidenceRecord {
  merchant: string;
  locality: string;
  fetchedAt: string;
  sourceUrl: string;
  mode: "live" | "fixture";
  freshnessLabel: string;
}

export type FactStatus = "known" | "unknown" | "contradictory";

export interface RecoveryFact {
  label: string;
  status: FactStatus;
  detail: string | undefined;
}

export interface RecoveryCase {
  caseId: string;
  status: string;
  openedAt: string;
  facts: RecoveryFact[];
}

export interface ConversationTurn {
  id: string;
  role: "assistant" | "shopper";
  text: string;
}

/**
 * Payment, order, and refund are independent states (SPEC/AGENTS.md
 * invariant) - never collapsed into one "purchase status" field.
 */
export interface PurchaseStatus {
  purchaseId: string;
  payment: "pending" | "succeeded" | "failed" | "unknown";
  order: "unknown" | "placed" | "not_placed";
  refund: "none" | "pending" | "complete";
}
