# WP-02 — Core domain records and deterministic rules

Owner: P3 — Transaction safety
Reviewers: P2 (shopping rules), P4 (persistence compatibility); P1 informed (error → UI mapping)
Status: Draft — awaiting Gate A review
Depends on: WP-00 contracts (repo skeleton, pinned Python 3.12, strict Pydantic, test runner)
Target merge: Day 1, hour 6

---

## Outcome and user value

Every honesty claim ProofPath makes to a judge is decided in this package.

"You were not charged twice" is a transition rule. "This fee is unknown, not zero" is a totals
rule. "This basket is genuinely cheaper" is a comparison rule. "This quote is exactly what you
approved" is a hash rule. None of these are UI or infrastructure concerns — they are pure
functions, and they must have exactly one implementation that everyone else calls.

WP-02 delivers that implementation: pure Python records, value objects and deterministic rules
with no AWS, no persistence, no I/O and no clock of their own. WP-06 (comparison), WP-08
(approval), WP-09 (simulator/checkout) and WP-10 (recovery) all import from here and are
forbidden from reimplementing any rule in it.

It is scheduled for Day 1 hour 6 because three packages block on it. It is also the cheapest
place in the project to be exhaustively correct: no network, no deploy, no flakiness.

## In scope

1. Typed IDs, money, units, quantities and their invariants.
2. Canonical JSON encoding and the SHA-256 hashing scheme (quote, diff, line set, idempotency
   request, provider keys).
3. Intent/item model, revision semantics, flexibility and hard-attribute matching predicates.
4. Observation → basket line matching primitives, pack selection and overbuy bounds.
5. Basket totals, basket-level fee assessment, completeness classification and the
   definitively-cheaper comparator.
6. Preparation, diff, checkout quote, approval, purchase, attempt records and expiry rules.
7. Provider fact records (payment/order/refund) and the fact-application rules, including
   stale-fact and contradictory-fact handling.
8. All state machines: payment, order, refund, dispatch, approval, purchase claim, job, inbox,
   case.
9. Structural records for conversation, turn, question, voice session, search, observation,
   evidence, inbox, job and outbox envelopes.
10. The domain error taxonomy and its HTTP mapping table (as a contract; the mapping is applied
    by handlers, not by domain).
11. Golden test vectors published for other packages to verify against.

## Out of scope

- Any persistence, DynamoDB key layout, repository or transaction code (WP-07, P4).
- Any HTTP handler, OpenAPI wiring or status-code emission (owning packages).
- Merchant access, scraping, extraction or connector behaviour (WP-04/WP-06, P2).
- Ranking presentation, repair proposal generation and search orchestration (WP-06, P2).
- Simulator ledger storage and the checkout workflow itself (WP-09 — uses these rules).
- Callback ingestion, reconciliation workflow, guidance corpus, case workflow and export
  generation (WP-10, P4 — consumes the fact rules defined here).
- Cedar policies and authorization evaluation (P4). Domain states *who owns what*; it does not
  evaluate permission.
- Export redaction field allowlist (WP-10). Noted here only because POA §5 requires redaction
  selection to be pure — WP-10 should place it in `services/domain/` and reuse this package's
  conventions.

## User flow and UI states

This package renders nothing. It constrains what the UI is *allowed* to say:

| Domain result | What P1 must be able to show |
| --- | --- |
| `Totals.confidence = complete` | An exact total. |
| `Totals.confidence = estimated` | Total shown with an estimate marker; never "cheapest" against a complete total. |
| `Totals.confidence = unknown` | "At least ₹X" from `known_subtotal` plus a named unknown charge. Never a total, never ₹0. |
| `Comparison.not_comparable` | Both baskets shown, neither marked cheapest, with the reason. |
| `BudgetCheck.unknown` | "Can't confirm this is under your budget" — never "within budget". |
| `QuoteExpired` | Expired card, requires a fresh preparation; approval control disabled. |
| `PreparationStale` / diff non-empty | Explicit change list, each change acceptable only by its exact `diff_hash`. |
| `AttemptBlockedByExposure` | "We're still confirming your last payment" — retry disabled, never a new pay button. |
| `payment = unknown` | Unknown is displayed as its own state, never as failure and never as success. |
| `mode = fixture` | Persistent fixture label on comparison, quote and export. |

## API and event contracts

WP-02 exposes no HTTP surface. It defines the vocabulary those surfaces serialize, and the
error → status mapping every handler must apply.

| Domain error | HTTP | Applied by |
| --- | --- | --- |
| `VersionConflict` | 409 | all handlers |
| `IdempotencyPayloadMismatch` | 409 | all mutations |
| `ApprovalAlreadyConsumed` (same approval, same payload) | 200 + existing attempt | WP-08 |
| `ApprovalAlreadyConsumed` (different payload) | 409 | WP-08 |
| `QuoteExpired`, `ApprovalExpired`, `PreparationExpired` | 410 | WP-08 |
| `DiffHashMismatch`, `DiffNotAccepted` | 409 | WP-08 |
| `QuoteHashMismatch` | 409 | WP-08 |
| `AttemptBlockedByExposure` | 409 | WP-08/WP-09 |
| `IllegalTransition` | 409 | all |
| `ContradictoryProviderFact` | 202 + quarantine | WP-10 callback ingestion |
| `FactIgnoredStale` | 200 (no-op, idempotent) | WP-10 callback ingestion |
| `IncompatibleUnits`, `OverbuyLimitExceeded`, `SubstitutionNotPermitted`, `HardAttributeUnsatisfied` | not user errors — matching outcomes | WP-06 |
| `InvalidRecord` (Pydantic strict failure) | 422 | all |
| Owner mismatch | 404 (concealment) | all — enforced at handler, not domain |

Event payload shapes (job, outbox envelope) are defined structurally here so P4's WP-07 can
serialize them without inventing a second schema. Routing, delivery and generation *mechanics*
are WP-07's; the envelope *fields* and the job status enum are WP-02's.

## Data model and state transitions

### Module layout

```text
services/domain/
├── ids.py            typed opaque ID aliases, mode enum
├── money.py          Paise, Money, Charge, ChargeKind, Confidence, Totals
├── units.py          Dimension, Unit, Quantity, convert
├── canonical.py      canonical_json, sha256_hex, domain-separation tags
├── keys.py           provider/order keys, idempotency request hash
├── intent.py         Item, Flexibility, Intent, UsualBasket, revision rules
├── catalog.py        Observation, ExtractionStatus, match predicates
├── basket.py         BasketLine, Basket, FeeAssessment, totals, compare_baskets
├── purchase.py       Preparation, Diff, CheckoutQuote, Approval, Purchase, Attempt, ProviderLookup
├── provider.py       PaymentFacts, OrderFacts, RefundFacts, apply_* rules
├── transitions.py    every state machine, one table each
├── conversation.py   Conversation, Turn, Question, VoiceSession (structure + versions)
├── evidence.py       InboxEvent, Evidence, Case
├── jobs.py           Job, JobStatus, OutboxEvent envelope
└── errors.py         DomainError taxonomy
```

Every module: stdlib + `pydantic` only. No logging, no `datetime.now()`, no `uuid4()`, no
`random`. `now: datetime` is an explicit parameter wherever time matters; IDs are supplied by
the caller.

### Cross-cutting record conventions

- **Timestamps are timezone-aware UTC.** A naive `datetime` is rejected by strict validation at
  construction, not silently assumed to be UTC. All comparisons are on aware datetimes.
- **IDs are opaque strings**, `^[A-Za-z0-9_-]{8,64}$`, case-sensitive, generated by the caller.
  The charset is constrained so canonical JSON and hashing stay stable and shell/URL safe.
- Every mutable record carries `version: int` starting at 1. `Intent` additionally carries
  `revision: int` starting at 1.
- Every record carries `owner_id`. Domain treats it as data; handlers enforce ownership.
- All records are **frozen** (immutable) Pydantic models. A "mutation" is a pure function
  returning a new record with `version + 1`, which makes accidental in-place state change
  impossible and makes every transition auditable.

### Records this package defines (commerce core)

| Record | Fields that carry rules |
| --- | --- |
| `Item` | `id, name, quantity: Quantity, unit, hard_attributes: dict[str,str], flexibility` |
| `Intent` | `items[≤4], location, budget_paise: Paise \| None, delivery_constraint, revision, version` |
| `UsualBasket` | items + preferences only — **no price, no quote, no approval, no payment identity** |
| `Observation` | `merchant_id, sku, url, pack: Quantity, unit_price: Money, in_stock, verified_location, fetched_at, evidence_key, extraction_status, mode` |
| `BasketLine` | `item_id, observation_ref, packs[], selected_quantity, overbuy_base_units, substitution: Substitution \| None, line_total: Money, confidence` |
| `FeeAssessment` | `merchant_id, location, line_hash, subtotal, assessed_at, charges: [Charge]` — **basket-level, never per-line** |
| `Basket` | `search_id, merchant_id, mode, lines, fee_assessment, totals: Totals` |
| `Diff` | `preparation_id, changes: [Change], diff_hash` where `Change = {kind: PRICE \| AVAILABILITY \| PACK \| FEE \| DELIVERY, target, before, after}`; empty `changes` ⟹ no acceptance required |
| `Preparation` | `purchase_id, base_basket_id, intent_revision, refreshed_facts, diff, refreshed_at, accepted_diff_hash \| None, version` |
| `CheckoutQuote` | `quote_id, version, demo_seller_id, source_merchant_id, mode, lines, charges, total, currency, delivery, issued_at, expires_at, quote_hash` — **immutable, never updated in place** |
| `Approval` | `approval_id, quote_id, quote_hash, quote_version, purchase_version, status, consumed_attempt_id \| None` |
| `Purchase` | `intent_revision, basket_id, active_attempt_id \| None, payment, order, refund, claim, version` |
| `Attempt` | `attempt_id, approval_id, payment_key, request_hash, dispatch, started_at \| None, provider_reference \| None, next_check_at \| None, version` |
| `ProviderLookup` | `provider, payment_key, purchase_id, attempt_id, expected_seller_id, expected_amount: Money, expected_currency` — the uniqueness record that makes a duplicate attempt impossible |
| `InboxEvent` | `provider, event_id, body_hash, received_at, delivery_timestamp, facts, status` — immutable once received |
| `Evidence` | `purchase_id, kind, source_ref, observed_at, payload_hash` |
| `Case` | `purchase_id, known_facts, missing_facts, guidance_versions, draft_ref, status, version` |
| `Job` | `job_type, input_hash, reference, status, stage, progress, result \| None, error \| None, generation, execution_ref \| None` |
| `OutboxEvent` | `event_id, schema_version, event_type, aggregate_id, aggregate_version, owner_id, occurred_at, reference, publication_state` |

`ProviderLookup` deserves emphasis: it is the record whose uniqueness constraint — one row per
`(provider, payment_key)` — is what turns "we must not double-charge" from a hope into a
database-enforced fact. WP-02 defines its shape and the key derivation; WP-08 creates it inside
the approval transaction; WP-07 provides the conditional write.

### Money

- `Paise = NewType("Paise", int)`. Integer only. Strict Pydantic rejects `float`, numeric
  strings and `bool`.
- `Money = {amount_paise: Paise, currency: Literal["INR"]}`. Non-negative. A signed delta uses
  `MoneyDelta` with the same currency rule; the two do not mix.
- Arithmetic helpers live here (`add`, `sub`, `mul_by_quantity`) and reject currency mismatch.
  No `__truediv__` is exposed — division would invite floats.
- **Unit rates never touch money.** A "₹ per 100 g" figure is a comparison and display concept,
  and computing it requires division. It is returned as an exact `Fraction` (numerator and
  denominator, both integers), rounded only at the presentation edge, and it may never be summed,
  stored as a price, or used to compute a line total or a quote total. Totals are only ever built
  by adding integer paise. Without this rule, integer division would silently round rates and
  those roundings would compound into a total that does not match the sum of its lines.
- `Confidence = VERIFIED | ESTIMATED | UNKNOWN`.
- `Charge = {kind, confidence, amount: Money | None}` with the invariant
  **`confidence == UNKNOWN` ⟺ `amount is None`**. A charge may never be `UNKNOWN` with an
  amount, and may never be `VERIFIED`/`ESTIMATED` without one. There is no path that produces
  `amount = 0` for an unknown fee.
- `ChargeKind = DELIVERY | HANDLING | PACKAGING | SMALL_ORDER | SURGE | TAX | OTHER`.

### Totals

```text
Totals = {
  known_subtotal: Money      # lines + all known charges; a true lower bound
  total: Money | None        # None iff confidence == UNKNOWN
  confidence: Confidence     # worst confidence across lines and charges
  unknown_charges: [ChargeKind]
}
```

Rule: `confidence = min(VERIFIED, ESTIMATED, UNKNOWN)` over every line and every charge, worst
wins. If any charge is `UNKNOWN`, `total is None` and `known_subtotal` is the only publishable
number, labelled as a lower bound.

### Definitively-cheaper comparator

`compare_baskets(a, b) -> A_CHEAPER | B_CHEAPER | EQUAL | NOT_COMPARABLE`

A is declared cheaper than B only when **A is `VERIFIED`-complete** and:

- B is complete and `a.total < b.total`; or
- B is estimated/unknown and `a.total < b.known_subtotal` — because B's true total can only be
  ≥ its known subtotal.

Otherwise `NOT_COMPARABLE`. An estimated or unknown basket is therefore never declared cheaper
than a verified one, which is exactly the honesty rule in SPEC §1, expressed as arithmetic
rather than as a UI convention. Baskets in different `mode`s (live vs fixture) always return
`NOT_COMPARABLE` and additionally raise `MixedModeComparison` if a caller tries to rank them
in one list.

### Units and quantities

- `Dimension = MASS | VOLUME | COUNT`.
- `Unit = G | KG | ML | L | PIECE` mapped to base units gram, millilitre, piece.
- `Quantity = {value_base: int, dimension: Dimension}` — integer base units, so 1.5 kg is
  `1500 g` and no float ever appears.
- `convert(quantity, to_unit)` succeeds only within a dimension. **MASS ↔ VOLUME returns
  `IncompatibleUnits` unconditionally** — there is no density parameter, no override flag and
  no configuration that enables it.
- `COUNT` never converts to MASS or VOLUME.

### Matching, packs and overbuy

- `Flexibility = EXACT_ONLY | BRAND_FLEXIBLE | PACK_FLEXIBLE | BRAND_AND_PACK_FLEXIBLE`.
- `hard_attributes: dict[str, str]` on the item. An observation satisfies a hard attribute only
  when it carries that attribute with an equal value. **A missing or unknown attribute never
  satisfies a hard attribute** — it returns `HardAttributeUnsatisfied`, not a match.
- Pack selection: choose the multiset of packs that meets the required quantity, minimising
  (1) total quantity, then (2) total cost, then (3) pack count — deterministic tie-breaking, no
  randomness. Ties beyond that break on SKU lexicographic order so results are reproducible.
- Overbuy is whatever that minimum yields, is always reported as `overbuy_base_units > 0`, and
  is rejected with `OverbuyLimitExceeded` when
  `selected_quantity * 10000 > required_quantity * OVERBUY_LIMIT_BP`, default
  `OVERBUY_LIMIT_BP = 15000` (1.5×), expressed in integer basis points so no float is involved.
- A brand change requires `BRAND_FLEXIBLE` or `BRAND_AND_PACK_FLEXIBLE`; a pack-size change
  requires `PACK_FLEXIBLE` or `BRAND_AND_PACK_FLEXIBLE`. Anything else is
  `SubstitutionNotPermitted`. Every substitution is recorded on the line, never silently applied.

### Canonical JSON and hashing

`pp-canon-v1`:

1. UTF-8, no insignificant whitespace, no trailing newline.
2. Object keys sorted by Unicode code point.
3. Strings NFC-normalised.
4. Integers only. **A float anywhere in a hashed payload is a programming error and raises** —
   money is already integer paise.
5. **Every field declared in the record's schema is always present, with an explicit `null` for
   an absent value. Nothing is omitted.** Omitting nulls is the usual convention and it is a
   collision bug here: `{"delivery_charge": null}` and `{}` would hash identically, so "we don't
   know the delivery fee" and "there is no delivery fee" would be indistinguishable in a
   signature. Arrays are order-significant and never reordered.
6. Booleans lowercase, no `NaN`/`Infinity`.

Each hash is domain-separated by a tag prefix so one hash kind can never be replayed as
another: `proofpath.quote.v1`, `proofpath.diff.v1`, `proofpath.lines.v1`,
`proofpath.idem.v1`, `proofpath.payment_key.v1`, `proofpath.order_key.v1`. Output is lowercase
hex SHA-256.

**Quote hash** binds, in this order: tag, owner_id, purchase_id, purchase_version, quote_id,
quote_version, seller_id, source_merchant_id, mode, lines (sku, name, quantity base units and
dimension, unit price, line total, substitution flag), charges (kind, confidence, amount),
currency, delivery constraint, expires_at.

`mode` is a **proposed addition** to the SPEC §6 field list — see D-3. Without it, a fixture
quote and a live quote with identical numbers hash identically, which is a labelling hole in
exactly the surface judges will inspect.

**Provider keys** — deterministic and stable by construction:

- `approval_id = H("proofpath.approval_id.v1", quote_id, quote_hash, quote_version)`
- `payment_key = H("proofpath.payment_key.v1", purchase_id, approval_id)`
- `order_key   = H("proofpath.order_key.v1", purchase_id, attempt_id)`

`approval_id` being **derived from the consent rather than freshly generated** is load-bearing,
and it was wrong in the first draft of this spec. If the server minted a new `approval_id` per
approve request, two concurrent approvals of the same quote would produce two different
`approval_id`s, therefore two different `payment_key`s, therefore two different
`ProviderLookup` rows — and the uniqueness condition on that row would catch nothing. The whole
safety argument would rest on the purchase-version CAS alone, with no second line of defence.

Deriving it from `(quote_id, quote_hash, quote_version)` means the same consent always produces
the same approval and the same key, so a duplicate is caught independently by the approval
condition, the lookup condition **and** the version CAS. Three independent mechanisms, any one
of which is sufficient.

Derived only from identities that are fixed at approval time. They contain no clock, no random
source, no retry count, no job generation and no attempt ordinal, so retry, timeout, crash and
workflow restart all reproduce the same key. One approval → one attempt → one payment key,
permanently.

**Idempotency request hash** = `H("proofpath.idem.v1", method, path_template, sorted path
params, owner_id, canonical(body))`. Headers other than the key itself, timestamps and trace
IDs are excluded, so a legitimate retry hashes identically.

### State machines

Every machine is one table in `transitions.py` with a single `apply(machine, current, event)`
entry point. Transitions not in the table return `IllegalTransition`. No handler, workflow or
simulator may encode a transition of its own.

**Payment** — `not_started → claimed → {pending, succeeded, failed, unknown}`;
`pending ↔ unknown`; `pending|unknown → succeeded|failed`.
Terminal: `succeeded`, `failed`.

**Order** — `not_created → {pending, confirmed, failed, unknown}`; `pending ↔ unknown`;
`pending|unknown → confirmed|failed`. Terminal: `confirmed`, `failed`.

**Refund** — `none → {pending, unknown}`; `pending ↔ unknown`; `pending|unknown → completed|failed`.
Terminal: `completed`, `failed`.

**Dispatch** — `ready → started`; `ready → expired_unsent`. Both are one-way. There is no
transition out of `started`: after it, the outcome is decided by provider facts only, never by
expiry.

**Approval** — `issued → consumed | expired | cancelled`. All terminal; `consumed` is one-shot
and carries the attempt it created.

**Purchase claim** — `unclaimed → claimed → released`. Released only by `expired_unsent` or by
cancel that won the race; never by a job failure.

**Job** — `queued → running → {succeeded, failed}`; authorised retry takes `failed → queued`
**and increments `generation`**. Duplicate delivery resolves the existing run and never
restarts a failed one.

**Inbox** — `received → {applied, duplicate, conflicted, quarantined}`. All terminal.

**Case** — `open → {awaiting_user, resolved} → closed`; reopen `resolved → open` on new
contradicting evidence.

### Provider fact application

`apply_payment_facts(current, incoming, now) -> Applied | FactIgnoredStale | ContradictoryProviderFact | IllegalTransition`

Three rules, in order:

1. **Terminal is sticky.** A non-terminal incoming fact against a terminal current state is
   ignored as `FactIgnoredStale`. This is what makes "an old pending callback cannot downgrade
   a success" structurally impossible rather than merely tested.
2. **Contradictory terminals quarantine.** `succeeded → failed` or `failed → succeeded` never
   applies. It returns `ContradictoryProviderFact`; the caller must query the provider and
   quarantine the inbox event. State is left unchanged.
3. **Otherwise apply if not older.** Among non-terminal states, apply only when
   `incoming.observed_at >= current.observed_at`; equal timestamps with an identical body are a
   no-op, equal timestamps with a different body are contradictory.

The same three rules govern order and refund facts.

### Exposure and attempt creation

```text
has_unresolved_exposure(attempt) =
    attempt.dispatch == started and attempt.payment in {claimed, pending, unknown}
```

`may_create_attempt(purchase) -> Allowed | AttemptBlockedByExposure` returns `Allowed` only
when there is no active attempt, and the previous attempt (if any) ended in
`payment = failed` or `dispatch = expired_unsent`. A `succeeded` payment also blocks a new
attempt — the purchase is paid; a replacement would be a second charge. A failed *job* never
unblocks anything.

### Expiry and the no-loop rule

- `PREPARATION_FRESHNESS_SECONDS = 120`, `QUOTE_LIFETIME_SECONDS = 120`, both parameters with
  those defaults, both checked against an injected `now`, never against a client clock.
- `is_fresh(preparation, now)` = `now - refreshed_at < freshness`.
- Quote construction:
  - diff empty **and** preparation fresh → build the quote directly;
  - diff non-empty → require acceptance of that exact `diff_hash`; once accepted, if the
    preparation is **still fresh, build the quote without re-refreshing**. This is the rule that
    stops the endless recheck loop the POA warns about;
  - preparation stale → `PreparationExpired`, a new preparation is required.
- An expired quote can never be approved; an expired *approval* before dispatch yields
  `expired_unsent`. After dispatch has started, expiry is irrelevant to the money question.

### Revision vs version

- `Intent.revision` increments only on an accepted content change (user edit, accepted repair).
- Every other record uses `version`, +1 per mutation, checked optimistically.
- A `Search` binds `(intent_id, revision)`. `is_current(search, intent)` is false for an older
  revision, so an old search can never become current after a repair is accepted.

## Components, ports, and dependency direction

- `services/domain/` sits at the bottom: **it imports nothing from the project**. Not
  application, not adapters, not api, not simulator.
- It defines no ports. Ports live in `services/application/`. Domain functions receive `now`
  and IDs as arguments, which keeps them trivially testable and removes the need for a Clock
  abstraction inside the domain.
- Direction is enforced mechanically, not by convention: a test walks the AST of every module
  under `services/domain/` and fails on any import outside `{stdlib, pydantic, services.domain}`
  — explicitly including `boto3`, `botocore`, `fastapi`, `playwright`, `aws_lambda_powertools`,
  `requests`, `httpx` and any `services.*` sibling.
- A second test asserts the absence of `datetime.now`, `time.time`, `uuid4`, `random` and
  `logging` in the package.

## Security, privacy, and authorization

- Domain performs **no** authorization. It records `owner_id` as data; Cedar and handler-level
  owner checks decide access (P4). Domain never reads an owner ID from a request body — callers
  pass the token-derived value.
- No secrets, tokens, HMAC keys, OTPs or PINs enter this package. The callback HMAC is computed
  in WP-09/WP-10 adapters over a raw body; WP-02 supplies only the canonical body-hash helper.
- Hashes cover opaque IDs and commercial terms, never free text from a shopper, and never audio
  or image bytes.
- No logging in the package at all, so no accidental disclosure path exists.

## Idempotency, concurrency, timeout, and retry behavior

- Every rule in this package is a **pure function of its inputs**: same inputs, same output,
  every time, on every machine, in any order.
- Re-applying an identical provider fact is a no-op that returns the same state — replay safe by
  construction.
- `payment_key`/`order_key` are derived, never stored-then-reused, so a crash between derivation
  and use changes nothing.
- No timeouts, no retries and no concurrency primitives live here. Domain tells callers whether
  a transition is legal; it never decides when to retry.
- Optimistic concurrency is expressed as `expected_version` comparison helpers that return
  `VersionConflict`; the conditional write itself is WP-07's.

## Failure modes and user-visible errors

`errors.py` defines a closed `DomainError` union with a stable `code` string on each member.
Errors are **returned as typed results, never raised as generic exceptions** (POA §5). A
`DomainError` carries only structured, safe fields — codes, enum values, IDs — never prose, so
P1 owns all user-facing copy and no message is ever assembled inside the domain.

Taxonomy: `IncompatibleUnits`, `HardAttributeUnsatisfied`, `SubstitutionNotPermitted`,
`OverbuyLimitExceeded`, `MixedModeComparison`, `BudgetExceeded`, `PreparationExpired`,
`DiffNotAccepted`, `DiffHashMismatch`, `QuoteExpired`, `QuoteHashMismatch`,
`QuoteNotConstructible`, `VersionConflict`, `IdempotencyPayloadMismatch`,
`ApprovalAlreadyConsumed`, `ApprovalExpired`, `PurchaseAlreadyClaimed`,
`AttemptBlockedByExposure`, `PaymentKeyConflict`, `IllegalTransition`,
`ContradictoryProviderFact`, `FactIgnoredStale`, `InvalidRecord`.

`QuoteNotConstructible`, `PurchaseAlreadyClaimed` and `PaymentKeyConflict` were added after
WP-08 and WP-09 were specified — writing those two is what revealed the domain needed them.
`QuoteNotConstructible` carries the offending `[ChargeKind]` so callers can name the fee.

## Observability and cost limits

- Zero runtime cost: no I/O, no AWS calls, nothing deployed.
- The package emits no logs or metrics. It makes callers *able* to log well by returning stable
  `code` values and by exposing `aggregate_id` / `version` on every record, which is what POA
  §5's correlated-log requirement needs.
- CI budget: the full unit suite must run in **under 30 seconds** on a laptop, so the other
  three packages are never slowed by importing it.

## Test plan

### Unit

Money and totals
- integer paise only; `float`, `"100"`, `Decimal` and `True` all rejected by strict Pydantic.
- unknown charge ⟹ `total is None`, `confidence = UNKNOWN`, kind listed in `unknown_charges`;
  **no input produces a 0-paise unknown fee**.
- worst-confidence propagation across every line/charge combination (table test).
- `known_subtotal` is always ≤ any possible true total.

Comparator
- complete vs complete; complete vs estimated; complete vs unknown; estimated vs estimated;
  unknown vs anything ⟹ never `B_CHEAPER` for the unknown side.
- an estimated basket with a *lower* point estimate than a complete basket still returns
  `NOT_COMPARABLE` in the cheaper direction.
- cross-mode comparison returns `NOT_COMPARABLE` and flags `MixedModeComparison`.

Units
- g↔kg and ml↔l round-trip exactly at boundary values (0, 1, 999, 1000, 1001, very large).
- **every** MASS↔VOLUME pair returns `IncompatibleUnits`; a property test asserts no argument
  combination can produce a successful cross-dimension conversion.
- COUNT never converts.

Matching and packs
- missing attribute, `None` attribute and empty-string attribute each fail a hard attribute.
- pack selection is deterministic under input reordering (property test).
- overbuy at exactly 1.5×, just under and just over the limit.
- substitution permitted/forbidden for all four flexibility values.

Budget
- total exactly equal to budget ⟹ within (inclusive); one paise over ⟹ `BudgetExceeded`;
  unknown total ⟹ `BudgetCheck.unknown`, never "within".

Hashing
- determinism across process runs, key insertion order and dict iteration order (property test).
- a float anywhere in the payload raises.
- changing any single bound field changes the quote hash; changing an unbound field does not.
- domain separation: the same payload under two tags yields different digests.
- `payment_key` identical across 100 simulated retries, a crash-and-resume, a job generation
  bump and a clock jump; different across two different approvals on the same purchase.
- idempotency hash ignores trace/timestamp headers, and differs on any body change.

Transitions (table-driven, every machine)
- every legal edge applies; **every illegal edge returns `IllegalTransition`** — the test
  enumerates the full cartesian product of states × events, so a new state cannot be added
  without a deliberate table entry.
- terminal stickiness: `succeeded` then `pending` ⟹ `FactIgnoredStale`, state unchanged.
- contradictory terminals: `succeeded` then `failed` ⟹ `ContradictoryProviderFact`, state
  unchanged.
- out-of-order `observed_at` is ignored; identical fact re-applied is a no-op.
- dispatch: no event escapes `started`; `expired_unsent` only from `ready`.
- exposure: new attempt blocked while `claimed|pending|unknown` after `started`, blocked after
  `succeeded`, allowed after `failed` and after `expired_unsent`.
- job: `failed → queued` only via authorised retry and always increments `generation`.

Record conventions
- a naive `datetime` is rejected at construction on every record carrying a timestamp.
- IDs outside `^[A-Za-z0-9_-]{8,64}$` are rejected; an ID with a space or slash cannot reach a
  hash input.
- every record is frozen: in-place assignment raises, and each transition helper returns a new
  record with `version + 1`.
- `UsualBasket` has no field capable of holding a price, quote, approval or payment identity —
  asserted structurally so a future field cannot quietly add one.
- `Diff` with zero changes reports `requires_acceptance = False`; with one or more changes it
  reports `True` and exposes a stable `diff_hash` under key reordering.

Expiry
- fresh/stale boundary at exactly 120s (inclusive/exclusive stated and tested).
- accepted diff + still-fresh preparation builds a quote **without** requiring another refresh
  (the anti-loop test).
- expired quote can never be approved.

Property tests (Hypothesis)
- money arithmetic never produces a negative total from non-negative inputs;
- canonical JSON is stable under any key permutation;
- applying any random sequence of provider facts never moves a terminal state;
- `known_subtotal ≤ total` whenever `total` exists.

### Contract

- **Public API snapshot test**: the exported names of `services.domain` are asserted against a
  committed list. Adding a rule is deliberate; and the same test is what lets reviewers of
  WP-06/08/09/10 see at a glance whether a rule was reimplemented elsewhere.
- **Golden vectors**: `tests/vectors/wp02/*.json` — canonical JSON inputs with expected
  digests for quote hash, diff hash, line hash, idempotency hash, payment key and order key.
  P4's simulator and any other implementation must reproduce them byte for byte. This is the
  mechanism that keeps "one authoritative implementation" true across package boundaries.
- Transition tables exported as data and snapshotted, so P4's workflow code and P3's simulator
  provably read the same table.

### Integration

None — the package has no I/O. The integration obligation is inverted: WP-06, WP-08, WP-09 and
WP-10 each add a test proving they call these functions rather than recomputing.

### End-to-end / manual

Not applicable. Evidence for this package is the test suite plus the import-boundary test.

## Acceptance criteria

1. `services/domain/` imports nothing outside stdlib, `pydantic` and itself; the AST test
   proves it, and it fails loudly if someone adds `boto3`.
2. No float can reach money, a total or a hashed payload; strict Pydantic plus the canonical
   encoder both reject it.
3. An unknown fee is representable only as `confidence = UNKNOWN, amount = None`, and no code
   path yields 0 paise for it.
4. A total is `unknown` whenever any charge is unknown, in which case there is no ceiling and
   `known_subtotal` is published for display. `floor` -- the sum of verified amounts alone -- is
   the only true lower bound, and is computed in every case (amended by WP-02-A1; before it,
   `known_subtotal` was wrongly described as a lower bound even when it included estimates at
   their upper bound).
5. No mass↔volume conversion exists in any code path, with no flag to enable one.
6. An unknown or missing attribute never satisfies a hard attribute.
7. The cheaper comparator declares a winner only when that basket's ceiling sits strictly below
   the other's floor, so a verdict is always a proof rather than a preference. A basket with an
   unknown charge has no ceiling and can never win. Modes are never compared.

   **Amended by WP-02-A1, and this is a deviation from SPEC section 1**, which says an estimated
   total never ranks as cheaper than a verified one. P2 builds estimates as published upper
   bounds, so "at most 491 against exactly 520" is arithmetic, not a guess. Enforcing the
   original wording was not more honest, only less useful: the live merchants can never report a
   complete fee, so every live comparison returned NOT_COMPARABLE at every price gap. Needs the
   team's sign-off on the SPEC amendment; see
   `docs/specs/WP-02-A1-bounded-estimates-and-ceiling-approval.md`.
8. Quote, diff, line, idempotency and provider-key hashes are deterministic, domain-separated
   and reproduce the committed golden vectors.
9. `payment_key` and `order_key` are byte-identical across retry, timeout, crash and generation
   bump, and contain no clock or randomness.
10. Every state machine rejects every transition absent from its table, proven by exhaustive
    state × event enumeration.
11. A terminal payment state can never be downgraded, and contradictory terminal facts
    quarantine instead of applying.
12. A new attempt is impossible while a payment exposure is unresolved, and a failed job never
    changes a payment state.
13. An accepted diff on a still-fresh preparation produces a quote without another refresh.
14. Every rule is a returned typed result; no generic exception is raised for an expected
    outcome.
15. Records are frozen and timestamps are timezone-aware UTC; a naive datetime or a
    malformed ID cannot reach a hash input.
16. `UsualBasket` is structurally incapable of carrying a price, quote, approval or payment
    identity.
17. `ProviderLookup` shape and `(provider, payment_key)` uniqueness are defined here and used
    unchanged by WP-07's conditional write and WP-08's approval transaction.
18. P2, P3 and P4 have recorded agreement that these are the **sole** canonical rules and that
    their packages will call them rather than reimplement them (the POA exit gate).
19. Full unit suite green in under 30 seconds; formatter, linter and type checker clean.

## Rollout, rollback, and fixture strategy

- Pure library, merged behind no flag; nothing is deployed and there is nothing to roll back
  operationally. Rollback is `git revert` of one squashed commit.
- Additive by default. Changing a hash scheme or a transition table is **breaking**: it requires
  a new version tag (`...v2`), the two approvals the POA mandates for state-machine changes, and
  a note in `LEARNING.md`.
- Fixtures: this package is where `mode = live | fixture` is defined and where mixed-mode
  comparison is made impossible. It ships no fixture *data* — connector fixtures are WP-04's.
- Golden vectors are committed and treated as contract: changing one is a breaking change.

## Open questions and decisions

Gate A requires that no open question can materially change the implementation. **D-1 and D-3
must be closed before the first implementation commit** — D-1 changes the size of the package,
D-3 changes a persisted hash. D-2, D-4, D-5 and D-6 are confirmations: if no reviewer objects,
the stated decision stands and implementation proceeds.

- **D-1 — Which records belong to WP-02?** POA WP-02 says "Pydantic records and enums listed in
  the product spec", which includes conversation, turn, question and voice session. *Decision:*
  WP-02 defines all canonical record **structures** (so everyone shares one type), but the
  behavioural rules for conversation and voice — one-active-question, transcript binding, stale
  answers — stay with P1 in WP-05. Needs P1's explicit agreement at Gate A.
- **D-2 — Overbuy limit.** `OVERBUY_LIMIT_BP = 15000` (1.5×) is my proposed default. P2 owns
  matching quality and should confirm or change it; it is a single constant.
- **D-3 — `mode` in the quote hash.** SPEC §6 does not list it. I propose adding it so a fixture
  quote can never hash-match a live one. Additive to the spec; needs P4 review because it binds
  the persisted hash.
- **D-4 — Case transitions.** POA assigns case transitions to WP-02 but the case *workflow* to
  P4's WP-10. I define the machine; P4 drives it. Confirm P4 agrees the table is authoritative.
- **D-5 — Redaction selection.** POA §5 requires it to be pure, but it is not in WP-02's scope
  list. Left out; flagged so WP-10 places it in `services/domain/` rather than in a handler.
- **D-6 — Refund initiation.** Refund facts are read-only everywhere in ProofPath. The machine
  therefore has no "initiate" event; refunds only ever arrive as provider facts. Confirming this
  with P4 so WP-10 does not expect one.
