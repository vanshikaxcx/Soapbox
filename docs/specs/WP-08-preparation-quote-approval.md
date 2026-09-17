# WP-08 — Preparation, exact quote, and touch approval

Owner: P3 — Transaction safety
Reviewers: P1 (consent UI and copy), P4 (DynamoDB transactions, Cedar); P2 informed (basket/quote inputs)
Status: Draft — awaiting Gate A review
Depends on: WP-02 (domain rules), WP-06 (basket to prepare), WP-07 (job/outbox commit, conditional writes)
Target merge: Day 2, end of day

---

## Outcome and user value

This is the consent boundary. Everything before it is browsing; everything after it is money.

The shopper has chosen a basket from a comparison that may be minutes old. WP-08 re-checks that
basket against the merchant, shows exactly what changed, makes the shopper accept those exact
changes, freezes an immutable quote, and then — only through one dedicated touch control
showing the exact rupee amount — converts that consent into **at most one logical payment
attempt, ever**.

The two claims a judge will test here:

1. "I tapped approve twice / reloaded / raced a cancel — and there is still exactly one attempt."
2. "The amount I approved is byte-for-byte the amount that was submitted."

Both are settled by one atomic transaction and one hash. Not by UI state, not by a lock, not by
a retry policy.

## In scope

1. `POST /purchases` — create a purchase from a chosen basket and start the preparation job.
2. The **prepare** workflow: refresh the selected lines and basket fees, build an immutable
   preparation + diff, enforce 120s freshness.
3. `POST /purchases/{id}/preparations/{version}/accept` — explicit acceptance of an exact diff.
4. Quote construction, including the rule that an exact quote requires an exact total.
5. `POST /purchases/{id}/approve` — the single approval transaction.
6. `POST /purchases/{id}/cancel` — the competing cancellation, on the same version.
7. `GET /purchases/{id}` — the read contract for preparation, diff, quote and approval state.
8. `expired_unsent` handling: an approval that expires before any provider call.
9. The exact consent copy and UI state matrix P1 renders.
10. The Cedar action names P4 must model, and the authorization-versus-consent split.
11. Server-side proof that no conversational, voice, model or replayed path can approve.

## Out of scope

- The provider call itself, the simulator, polling and callbacks — WP-09.
- `POST /purchases/{id}/reconcile` — WP-09, because it reads provider references.
- Merchant refresh mechanics, connector deadlines and fee scraping — P2's `Merchant.refresh` /
  `Merchant.assess_fees` behind the port. WP-08 consumes the port, never the connector.
- The DynamoDB table layout, `TransactWriteItems` plumbing and Streams/outbox delivery — WP-07.
  WP-08 specifies **what must be atomic**; P4 specifies how the write is issued.
- Cedar policy text and evaluation — P4. WP-08 names the actions and states the required
  decisions.
- React rendering of the approve card — P1. WP-08 owns the endpoint, payload, exact copy and
  state list; P1 owns the pixels.
- Recovery, case creation and export — WP-10.

## User flow and UI states

Flow: comparison → choose basket → **prepare** → (accept changes if any) → **quote** →
**approve** → attempt exists.

State matrix P1 must implement. The copy below is the contract; P1 may restyle but not reword
the honesty strings.

| Purchase state | What the screen shows | Approve control |
| --- | --- | --- |
| Preparation running | Progress, "Re-checking prices with the merchant" | Absent |
| Prepared, diff empty | Exact quote, all terms, expiry countdown | **Enabled** |
| Prepared, diff non-empty | Change list, one row per change, before → after | **Absent** until changes are accepted |
| Diff accepted, preparation fresh | Exact quote, expiry countdown | **Enabled** |
| Preparation stale (>120s) | "These prices are no longer current" + Re-check button | Absent |
| Quote expired (>120s) | "This quote expired" + Re-check button | Absent |
| Quote not constructible | "We couldn't confirm the {charge} for this basket" + choose another merchant | Absent |
| Approved | Attempt card, outcomes (WP-09) | Replaced by status |
| Cancelled | "Cancelled. Nothing was sent." | Absent |
| Blocked by exposure | "We're still confirming your last payment" | Absent — never a second pay button |

Required copy, verbatim:

- Disclaimer on every quote and approve surface:
  **"Simulated checkout · no money moved · no retailer order placed."**
- Fixture mode adds:
  **"Demonstration data — fixture prices, not current retailer offers"**
- The approval control label: **`Approve simulated ₹X`**, where `X` is the exact quote total
  formatted from integer paise at presentation time only.
- The control is a dedicated touch target. It is not a form submit, not a chat reply, not a
  keyboard-activated default button in a dialog, and it carries no other action.

Every quote surface shows, without truncation or "show more": seller, each line with quantity
and unit price, each charge (including any that are labelled), currency, delivery terms, the
exact total, and the expiry time.

## API and event contracts

All mutations require `Idempotency-Key` and an expected version. All responses use the
`{data, request_id}` / `{error:{code,message,details}, request_id}` envelope from SPEC §7.

### `POST /purchases`

Body: `{basket_id, search_id, intent_revision, expected_intent_revision}`
Validations: basket belongs to owner; `intent_revision` is current (an old revision is `409`,
so a basket from a superseded search can never be purchased); basket mode recorded on purchase.
Effect: create `Purchase` (claim `unclaimed`, payment `not_started`) + preparation `Job` +
`OutboxEvent` + a **unique active-purchase row** `BASKET#{basket_id} / ACTIVE_PURCHASE`, all
atomically.
Returns `202 {job_id, resource_id: purchase_id, status_url}`.

The unique row closes a hole that idempotency keys alone do not: two *different* idempotency
keys would otherwise create two purchases for the same basket, each with its own valid approval,
each producing a real payment. One active purchase per basket means a second create returns the
existing purchase (`200`) instead.

Release paths — all four are needed, or an abandoned purchase locks its basket forever:

1. the purchase reaches a terminal state (paid and confirmed, or definitively failed);
2. its attempt goes `expired_unsent`;
3. the shopper cancels;
4. **the purchase is abandoned** — no live quote, no attempt, and no mutation for 30 minutes.
   Without (4), a shopper who walks away at the quote screen can never buy that basket again,
   and the only remedy would be a manual database edit during a demo.

### Prepare workflow (job)

1. Load purchase, basket and the basket's lines.
2. For each selected line call `Merchant.refresh(location, sku, deadline)`; then one
   `Merchant.assess_fees(location, exact_lines, deadline)` for the basket.
3. Persist refreshed facts and build `Diff` (WP-02 `Change` kinds: `PRICE`, `AVAILABILITY`,
   `PACK`, `FEE`, `DELIVERY`).
4. Persist `Preparation` with `refreshed_at = now`, `diff`, `diff_hash`, version.
5. If `diff.requires_acceptance` is false **and** the totals are exact → construct the quote in
   the same job.
6. If the refresh could not produce an exact total → terminal `QuoteNotConstructible` with the
   offending charge kinds. The job **succeeds**; the purchase carries the reason. A failed job
   must never be the way a user learns a fee is unknown.

Partial refresh: if one line fails to refresh, its confidence becomes `UNKNOWN`, which makes the
total unknown, which means no quote. We do not guess, and we do not fall back to the stale
price from the search.

### `POST /purchases/{id}/preparations/{version}/accept`

Body: `{diff_hash, expected_purchase_version}`
- `diff_hash` must equal the stored hash exactly → else `409 DiffHashMismatch`. This is what
  stops a shopper accepting a change list they never saw.
- Preparation must be fresh → else `410 PreparationExpired`.
- Effect: set `accepted_diff_hash`, version+1, and **construct the quote in the same request if
  the preparation is still fresh — without re-refreshing.** This is the anti-loop rule: a fresh
  accepted preparation always yields a quote.
- Returns `200 {preparation, quote}`.

### `POST /purchases/{id}/approve`

Body: `{quote_id, quote_hash, quote_version, expected_purchase_version}`
Header: `Idempotency-Key`

Validation order — each step's failure is distinguishable, because P1 shows different copy for
each:

1. Owner check → `404` if not owner (concealment, never `403`).
2. Cedar `ApprovePurchase` → `404` on deny.
3. Idempotency: same key + same request hash → return the stored result (`200`, existing
   attempt). Same key + different request hash → `409 IdempotencyPayloadMismatch`.
   **If two requests carrying the same key race past this read and the transaction's idempotency
   item loses its `attribute_not_exists` condition, the loser re-reads the record and returns the
   winner's result — never a `409`.** The check-then-act here is racy by nature; the transaction
   resolves it, and the loser's job is to report what actually happened. Returning an error to a
   double-tapping shopper whose payment did in fact succeed is the precise failure this product
   exists to argue against.
4. `expected_purchase_version` matches → else `409 VersionConflict`.
5. Quote exists, belongs to this purchase and owner → else `404`.
6. `quote_version` matches → else `409 VersionConflict`.
7. **Recompute the quote hash from the stored quote and compare to both the stored hash and the
   submitted `quote_hash`** → mismatch is `409 QuoteHashMismatch`. This catches a tampered
   client payload and a corrupted stored record with the same check.
8. Quote not expired against server `now` → else `410 QuoteExpired`.
9. Approval for this quote not already consumed → if consumed, return `200` with the **existing
   attempt** (SPEC §8: "repeated approval returns the existing attempt").
10. `may_create_attempt(purchase)` → else `409 AttemptBlockedByExposure`.

Then one transaction (see below). Returns `202 {job_id, resource_id: attempt_id, status_url}`.

### `POST /purchases/{id}/cancel`

Body: `{expected_purchase_version}`. Cedar `CancelPurchase`.
Permitted only while the purchase is unclaimed. Competes with approve on the same
`purchase.version`, so exactly one of the two succeeds; the loser gets `409 VersionConflict`.
After a claim exists, cancel returns `409` — there is an attempt, and cancelling an attempt is
not a thing this system pretends to do.

### `GET /purchases/{id}`

Returns purchase, current preparation + diff, current quote (with `expires_at` and
`seconds_remaining` computed server-side), approval state, attempt reference, and — once WP-09
lands — the three independent outcomes. Client clocks are never trusted for expiry; the server
publishes remaining seconds and the client only counts down for display.

### Cedar actions P4 must model

`ProofPath::Action::"CreatePurchase"`, `"ReadPurchase"`, `"AcceptPreparation"`,
`"ApprovePurchase"`, `"CancelPurchase"`. Principal is the owner; resource is the purchase.
No operator role may approve on a shopper's behalf.

## Data model and state transitions

All records are WP-02's; WP-08 adds no new record types. It adds **one write path**.

### The approval transaction

Every item below commits or none do. P4 issues it as a single `TransactWriteItems`; WP-08
specifies the items and their conditions.

| # | Item | Condition | Why it matters |
| --- | --- | --- | --- |
| 1 | Put `Approval` → `consumed` | `attribute_not_exists` or `status = issued` | Consent is one-shot |
| 2 | Put `Attempt` (`dispatch = ready`, `payment_key`, **`request_hash`**) | `attribute_not_exists(attempt_id)` | The attempt is created once, with its payload frozen |
| 3 | Put `ProviderLookup` `PROVIDER#sim#{payment_key}` with `expected_seller_id`, `expected_amount`, `expected_currency` from the quote | **`attribute_not_exists(PK)`** | **The uniqueness guarantee — a duplicate payment key cannot exist** |
| 4 | Update `Purchase`: `active_attempt_id`, `claim = claimed`, `version + 1` | `version = expected` | Wins or loses the cancel race, atomically |
| 5 | Put checkout `Job` (`queued`, `generation = 1`) | `attribute_not_exists` | Durable commit before any work |
| 6 | Put `OutboxEvent` | `attribute_not_exists(event_id)` | Work is dispatched only from committed state |
| 7 | Put `Evidence` (approval recorded, quote hash, timestamp) | `attribute_not_exists` | The consent record a case can cite |
| 8 | Put idempotency record (key → request hash → result) | `attribute_not_exists` | Replay returns, never re-executes |

Item 3 is the load-bearing one. `payment_key = H(tag, purchase_id, approval_id)` and the
approval is consumed exactly once, so two attempts on one approval would have to write the same
lookup row twice — which the condition forbids. The guarantee is enforced by the database, not
by application logic that could be raced.

Item 2's `request_hash` matters almost as much. The exact payment payload — key, quote hash,
seller, total, currency, expiry — is canonicalised and hashed **at approval time** and stored on
the attempt. WP-09's checkout task rebuilds the payload and asserts the hash before submitting,
and again before any resend. A later code path therefore cannot submit slightly different terms
under the same key: either it reproduces the approved payload exactly, or it refuses to send.
Together with the simulator's own same-key/different-payload conflict rule, that makes
"approved ₹X, submitted ₹Y" unreachable from either side.

The `ProviderLookup` carries the expected seller, amount and currency copied from the quote.
That is what WP-10's callback matching compares an incoming provider fact against, so a
mismatched callback can be quarantined without re-deriving anything.

Quote versioning: quotes are immutable, so a "new quote" is a new record with
`quote_version + 1` on the same purchase. Superseded quotes are retained for the case timeline
but are not approvable — approval requires the current `quote_version`.

The simulator's ledger is a **separate table** and is deliberately not part of this transaction.
Nothing here touches money; this commits the *intent* to pay.

### Dispatch and `expired_unsent`

The attempt is created `ready`. WP-09's checkout task is what moves it. WP-08 owns one rule:

If the approval or quote expiry passes while `dispatch = ready`, the attempt transitions
`ready → expired_unsent` under condition `dispatch = ready`, the purchase claim is released and
`active_attempt_id` cleared. No provider call happened, so there is no exposure and the shopper
may prepare and approve again.

The `ProviderLookup` row is **not deleted**. The key is spent. A new approval is a new quote,
therefore a new `approval_id` (WP-02 derives it from the quote), therefore a new key — so an
expired-unsent attempt can never collide with its successor.

**The approve control must not be re-enabled on a virtually-computed expiry.** The read path may
*display* that an attempt looks expired, but the transition is only real once committed under
its `dispatch = ready` condition. If P1 enabled approval on the displayed state, a shopper could
approve again in the window between "looks expired" and "the task actually marked it" — and the
task might instead win the race, mark `started`, and submit. The second approval would be
blocked by `may_create_attempt`, so this is safe rather than a double-charge, but it surfaces as
a confusing `409` on a button that looked live. `GET /purchases/{id}` therefore returns
`approve_enabled` as a **server-computed boolean**, and P1 binds the control to that field alone
rather than deriving it from timestamps.

### What blocks a second attempt

`may_create_attempt` (WP-02) allows a new attempt only when there is no active attempt **and**
the previous one ended in `payment = failed` or `dispatch = expired_unsent`. `pending`,
`unknown`, `claimed` and `succeeded` all block. A failed *job* changes nothing.

## Components, ports, and dependency direction

```text
api/purchases.py           handlers: validate, authorize, map errors → status
  → application/purchase_use_cases.py
      → domain (WP-02)     all rules, hashes, transitions — no logic duplicated here
      → ports:
          StateStore       conditional + transactional writes (P4 adapter, WP-07)
          JobStore         job + outbox commit (P4 adapter, WP-07)
          MerchantPort     refresh / assess_fees (P2 adapter, WP-04)
          PolicyPort       Cedar decision (P4 adapter)
          Clock            supplies `now` at the handler edge only
```

- Handlers do no arithmetic and no state reasoning. They validate shape, call a use case, and
  map a returned `DomainError` to a status via WP-02's table.
- The use case is the only place the transaction is assembled, and it assembles it from
  domain-computed values.
- `MerchantPort` is consumed through a deterministic fake in every WP-08 test. WP-08 never
  waits for a real connector to be green.

## Security, privacy, and authorization

- **Authorization ≠ consent.** Cedar answers "may this principal approve this purchase". The
  `Approval` record answers "did this human agree to these exact terms". Both are required, and
  neither substitutes for the other.
- Owner identity comes from the validated access token. An `owner_id` in a request body is
  ignored if present and the presence itself is a `422`.
- Inaccessible purchases return `404`, never `403`.
- **No path other than the approve endpoint may create an approval.** Enforced three ways:
  1. `/conversations/{id}/questions/{qid}/answer` accepts only question kinds from an allowlist,
     and no kind in it mutates a purchase, approval or attempt. A test asserts the allowlist
     contains no purchase-mutating kind.
  2. The agent tool registry contains no approval, payment or refund tool. A test walks the
     registry and fails on any tool whose target module is `purchase` or `provider`.
  3. The approve endpoint requires `quote_id + quote_hash + quote_version +
     expected_purchase_version` together. A model or a replayed transcript does not possess a
     current hash and version pair.
- **Cedar failures fail closed.** An unavailable or erroring policy decision is a deny, never an
  allow-by-default. The approval path has no degraded mode.
- Idempotency records are scoped `USER#{owner_id}` + endpoint + key, so two shoppers cannot
  collide on the same client-generated key, and a key from one endpoint cannot satisfy another.
- Quote contents are not logged. Logs carry `purchase_id`, `attempt_id`, `quote_id`,
  `quote_hash` (an opaque digest) and the outcome code.
- `payment_key` is an idempotency key, not a secret, and may be logged — it is what makes the
  effect-count proof auditable during the demo.

## Idempotency, concurrency, timeout, and retry behavior

- **Same `Idempotency-Key`, same payload** → the stored result, `200`, no new effect, at any
  point after the first success.
- **Same key, different payload** → `409`, nothing written.
- **Different key, already-consumed approval** → `200` with the existing attempt. The consent
  was already given; a fresh client key does not create a second attempt.
- **Concurrent approve + approve** → both contend on `purchase.version` and on the
  `ProviderLookup` condition. Exactly one commits; the other returns `409` or, if it carried the
  same idempotency key, the stored result. Under no interleaving do two attempts exist.
- **Concurrent approve + cancel** → both contend on `purchase.version`. Exactly one effect:
  either an attempt or a cancellation, never both, never neither.
- **Retry of the prepare job** → refreshes again and writes a new preparation version, keeping
  the same purchase identity and incrementing WP-07's job `generation`. This is safe: no money
  is involved and the shopper re-accepts any new diff.
- Active prepare jobs are capped per user (SPEC §9); the cap is a `429`, not a queue, so a stuck
  user never accumulates background merchant load.
- Timeouts: `Merchant.refresh` is bounded by the port deadline (45s/item per SPEC §9); a
  timeout makes that line `UNKNOWN`, which makes the total unknown, which blocks the quote.
  It never produces a guessed price.
- Expiry is always evaluated against the server clock, injected as `now`, never the client's.

## Failure modes and user-visible errors

| Failure | Code | Shopper sees | Recoverable by |
| --- | --- | --- | --- |
| Merchant refresh timed out | `QuoteNotConstructible` | "We couldn't confirm the price for {item}" | Re-check |
| Fee unknown after assessment | `QuoteNotConstructible` | "We couldn't confirm the {charge}" | Re-check or another merchant |
| Diff changed since shown | `DiffHashMismatch` (409) | Fresh change list | Re-accept |
| Preparation older than 120s | `PreparationExpired` (410) | "No longer current" | Re-check |
| Quote older than 120s | `QuoteExpired` (410) | "This quote expired" | Re-check |
| Client sent a stale version | `VersionConflict` (409) | Silent refresh, then the current card | Automatic |
| Tampered or corrupted quote | `QuoteHashMismatch` (409) | "We couldn't verify these terms" | Re-check |
| Approval already used | — | The existing attempt (200) | N/A — correct behaviour |
| Prior payment unresolved | `AttemptBlockedByExposure` (409) | "Still confirming your last payment" | Wait / recovery |
| Cancel lost the race | `VersionConflict` (409) | The attempt that won | N/A |

A failed *job* is reported as a job failure with a retry affordance. It is never rendered as a
payment or approval failure.

## Observability and cost limits

Structured logs on every approval path, carrying `request_id`, `purchase_id`, `attempt_id`,
`payment_key`, `quote_hash`, `outcome_code`, and the WP-07 job/execution correlation IDs.

Metrics (feed the `/demo` counters in WP-11):

- `approvals_committed`, `attempts_created` — these two must stay equal, forever;
- `approval_duplicate_suppressed` (idempotent replays);
- `approval_race_lost`, `cancel_race_lost`;
- `attempts_blocked_by_exposure`;
- `dispatch_expired_unsent`;
- `quote_not_constructible` by charge kind;
- preparation refresh latency and partial-refresh rate.

Cost: one extra DynamoDB transaction per approval, plus up to five merchant refresh calls per
preparation. Nothing standing.

## Test plan

### Unit

Preparation and diff
- unchanged facts → empty diff → `requires_acceptance = false` → quote built directly.
- price change, availability change, pack change, fee change, delivery change → each appears as
  exactly one typed `Change` with before/after.
- diff hash is stable under change reordering and changes when any field changes.
- one line fails to refresh → total unknown → `QuoteNotConstructible`, and **no** stale price
  from the search is reused (asserted by injecting a different stale price).
- unknown fee → `QuoteNotConstructible` naming the charge kind; never a ₹0 fee, never an
  approvable quote.

Freshness and the anti-loop rule
- accept at 119s → quote built without a second refresh (the `MerchantPort` fake asserts zero
  additional calls).
- accept at 121s → `PreparationExpired`.
- accept → quote → approve, all within one freshness window, is a terminating sequence. A test
  runs the full loop 50 times and asserts it never re-enters refresh.

Quote
- quote is immutable: any attempt to mutate returns a new record; the stored one is unchanged.
- recomputed hash equals stored hash for a round-tripped quote.
- flipping one line price, one charge, the seller, the currency, the delivery term, the expiry
  or the **mode** each changes the hash (the mode case is why D-3 in WP-02 matters).
- expiry is exactly `issued_at + 120s`; boundary tested at −1s, 0s, +1s.

Approval validation order
- each of the ten validation steps is exercised in isolation, and a test asserts the *order*:
  an expired quote with a stale version returns the version error first, so P1's copy is
  deterministic.

### Contract

- **The transaction contract with P4**: the eight items, their conditions and their all-or-none
  semantics are expressed as a fixture that P4's `StateStore` adapter must satisfy. The same
  test runs against the in-memory fake and against the real adapter in WP-07's suite.
- Error → HTTP mapping asserted against WP-02's table, so P1's generated client sees exactly the
  documented codes.
- The approve request/response schema is added to `contracts/openapi.yaml`; the generated
  TypeScript type is what P1 builds the card against.
- Cedar action names asserted against P4's schema fixture.

### Integration (in-memory adapters, no AWS)

- **Concurrent approve + approve** — 100 interleavings via a deterministic scheduler over the
  fake store; invariant after each: exactly one attempt, exactly one `ProviderLookup` row.
- **Concurrent approve + approve with the same idempotency key** — the loser of the idempotency
  condition returns the winner's result with `200`, never a `409`.
- **Defence-in-depth check** — the same interleavings are re-run three times, each with one
  safeguard disabled in the fake (approval condition off, lookup condition off, version CAS off).
  With any *one* disabled the invariant must still hold. This is what proves the three mechanisms
  are genuinely independent rather than one mechanism described three ways — and it is the test
  that would have caught `approval_id` being freshly generated per request.
- **Concurrent approve + cancel** — same harness; invariant: exactly one of {attempt,
  cancellation}, never both, never neither.
- **Replay** — the same idempotency key replayed 20 times mid-flight yields one attempt.
- **Crash between condition check and commit** — the fake aborts the transaction; the result is
  no partial state: no orphan attempt, no orphan lookup, no consumed approval without an attempt.
- **expired_unsent** — approve, let expiry pass with `dispatch = ready`, run the transition:
  claim released, `active_attempt_id` cleared, lookup row retained, a fresh approval succeeds
  with a **different** payment key.
- **Blocked replacement** — attempt in `pending`, then `unknown`, then `succeeded`: each blocks
  a new approval; `failed` and `expired_unsent` allow one.
- **Two purchases, one basket** — two creates with different idempotency keys yield one purchase;
  the second returns the existing one. Then approving "both" is structurally impossible.
- **Counter invariant** — after every scenario in this suite, the harness asserts
  `approvals_committed == attempts_created == provider_lookup_rows`. Any divergence fails the
  suite, so acceptance criterion 16 is proven by test rather than by watching the demo.

### End-to-end / manual

- Playwright: prepare → changed diff → accept → approve → attempt exists; then reload at every
  step and confirm the same state, never a duplicate.
- Double-tap the approve control within 200 ms → one attempt (this is the judge's first instinct).
- Type "yes", say "buy it", and submit a conversation answer while a quote is live → no approval
  is created. Asserted at the API, not by hiding a button.
- Screenshot evidence: the approve card showing seller, lines, charges, exact total, currency,
  delivery, expiry and the simulation disclaimer together in one viewport, on mobile width.

## Acceptance criteria

1. One approval creates exactly one attempt and exactly one `ProviderLookup` row, under every
   tested interleaving, replay and crash point.
2. Concurrent approve/cancel produces exactly one effect.
3. A repeated approval returns the existing attempt rather than creating another.
4. A quote cannot be approved if its recomputed hash differs from the stored or submitted hash.
5. A quote cannot be approved after expiry, measured on the server clock.
6. A quote is only constructible when the total is **bounded**. An unknown charge blocks it and
   names the charge, because an unknown fee has no ceiling and no amount on the control would be
   true; no code path yields ₹0 for it. An estimated charge is permitted and makes the quote's
   total a ceiling (amended by WP-02-A1: the live merchants can never report a complete fee, so
   blocking estimates refused every live purchase rather than protecting anyone).
7. A stale price from the original search is never reused when a refresh fails.
8. An accepted diff on a fresh preparation yields a quote without another refresh.
9. A diff can only be accepted by its exact hash.
10. `expired_unsent` releases the claim, retains the spent key, and permits a fresh approval with
    a new key.
11. No new attempt is possible while a payment is `claimed`, `pending`, `unknown` or `succeeded`.
12. A failed job is never surfaced as a payment or approval failure.
13. No conversational, voice, model or replayed path can create an approval — proven at the API
    and by the tool-registry and question-kind allowlist tests.
14. The approve control is the only caller of the approval endpoint, and its label states the
    amount and what kind of amount it is: `Approve simulated ₹X` when the total is exact, and
    `Approve simulated up to ₹X` when it is a ceiling. The server renders the label and the
    client displays it verbatim; dropping "up to" would turn a bound into a claim.
15. The simulation disclaimer is present on every quote and approval surface, and the fixture
    label additionally in fixture mode.
16. `approvals_committed == attempts_created` in the metrics over the whole demo run.

## Rollout, rollback, and fixture strategy

- Merges behind no flag; the routes are additive. Rollback is a revert of one squashed commit.
- The approval transaction shape is a **breaking** contract with WP-07: changing its items or
  conditions requires P4's re-approval and the two approvals the POA mandates for
  payment-state changes.
- Fixture mode: a purchase inherits `mode` from its basket and cannot change it. A fixture
  purchase produces a fixture quote, carries the demonstration label through approval, and is
  hashed with `mode` bound in — so a fixture quote can never be presented as a live one.
- Demo seeding creates purchases at each state (prepared-clean, prepared-changed, expired,
  approved) so WP-11 and the video do not depend on live timing.

## Open questions and decisions

- **D-1 — An exact quote requires an exact total.** I am ruling that `ESTIMATED` and `UNKNOWN`
  charges both block quote construction, not just `UNKNOWN`. Rationale: the control says
  "Approve simulated ₹X"; if X is an estimate, the sentence is false. SPEC §1 allows estimated
  totals in *comparison*, and comparison is where they belong. P1 and P2 should confirm they are
  happy that an estimated-fee merchant can be compared but not purchased.
- **D-2 — Resolved.** Two errors were missing from WP-02's taxonomy and have now been added
  there: `QuoteNotConstructible` and `PurchaseAlreadyClaimed`. (A third candidate,
  `PreparationNotAccepted`, turned out to duplicate the existing `DiffNotAccepted` — WP-08 uses
  that name.) Writing this spec is what surfaced them.
- **D-3 — Cancel after claim.** I am ruling `409`: once an attempt exists, there is nothing to
  cancel safely, because we cannot know whether a provider call is in flight. P1 should make the
  control disappear rather than fail. Confirm.
- **D-4 — Who runs the expiry sweep?** `ready → expired_unsent` needs a trigger. Two options:
  the checkout task evaluates it on pickup (no extra infrastructure), or a scheduled sweep. I
  propose **checkout-task evaluation**, with the read path computing it virtually for display,
  so no timer is required. Needs P4's agreement since it affects WP-07's task shape.
- **D-6 — One active purchase per basket.** Added on review; it needs a second unique row and
  therefore P4's agreement on the key shape and on when the row is released. Without it, two
  idempotency keys produce two approvable purchases for one basket — the only double-charge path
  I could find that the `ProviderLookup` uniqueness does not already close.
- **D-5 — Preparation refresh scope.** Selected lines only, or the whole basket? I propose
  selected lines plus one basket-level fee assessment — it is what the shopper is buying and it
  keeps us inside the 45s/item budget. P2 to confirm it matches `assess_fees` semantics.
