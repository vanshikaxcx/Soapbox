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

export interface ConversationQuestionOption {
  id: string;
  label: string;
}

/**
 * A structured clarification attached to the latest assistant turn - fixed
 * choices, not free text (WP-05: "one-active-question rule"). Only one can be
 * active; a new question replaces the previous one outright rather than
 * queuing behind it.
 */
export interface ConversationQuestion {
  id: string;
  prompt: string;
  options: ConversationQuestionOption[];
}

export interface ConversationTurnResult {
  turn: ConversationTurn;
  question?: ConversationQuestion;
}

/**
 * WP-05's one canonical editable-text submission path: typing and a later
 * voice feature's final transcript both resolve to a string and call the
 * same responder. P2's real schema-bound extraction is a different
 * implementation of this exact type, not a different call site.
 */
export type ConversationResponder = (
  text: string,
  priorTurns: readonly ConversationTurn[],
) => Promise<ConversationTurnResult>;

/**
 * Mirrors P2's real `/tasks/extract` contract exactly (WP-05, P2's slice -
 * `docs/specs/WP-05-extraction-contract-p2.md`), so swapping the fixture
 * responder for a real fetch later is a mapping change, not a UI rewrite.
 * Not yet browser-callable: the agent container is server-to-server only
 * (rotated token, "never directly by the browser") until a public API
 * Gateway/Lambda route in front of it exists (WP-07/P4).
 */
export type ExtractedDimension = "mass" | "volume" | "count";

export interface ExtractedQuantity {
  value_base: number;
  dimension: ExtractedDimension;
}

export type ExtractedFlexibility =
  | "exact_only"
  | "brand_flexible"
  | "pack_flexible"
  | "brand_and_pack_flexible";

export interface ExtractedItem {
  item_id: string;
  name: string;
  quantity: ExtractedQuantity;
  hard_attributes: Record<string, string>;
  flexibility: ExtractedFlexibility;
}

export type UnresolvedReasonCode =
  | "no_quantity_detected"
  | "ambiguous_item"
  | "item_limit_exceeded"
  | "extraction_unavailable"
  | "no_items_detected";

export interface UnresolvedExtraction {
  raw_fragment: string;
  reason_code: UnresolvedReasonCode;
  reason_detail: string | null;
}

export interface ExtractionOutcome {
  items: ExtractedItem[];
  unresolved: UnresolvedExtraction[];
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
