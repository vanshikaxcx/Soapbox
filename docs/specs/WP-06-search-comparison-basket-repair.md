# WP-06 — Search orchestration, basket assembly, fee integration, comparison

Owner: P2
Reviewers: P3 (domain rule usage), P1 (comparison result shape), P4 (workflow wrapping)
Status: Implementing
Depends on: WP-04 (merchant connectors, this branch), WP-02 (domain records/rules, merged from P3's branch)

## Outcome and user value

A shopper's multi-item request becomes, per merchant, either a complete basket
with a computed total, or an honest list of which items couldn't be matched
and why — then the two merchants' baskets are compared under WP-02's
honesty-safe rules, and a provable winner is named when one exists.

This is the gap both WP-04 and WP-08 explicitly left open: WP-04's spec lists
"basket-level comparison, repair, ranking" as out of scope ("WP-06"), and
WP-08's `prepare.py` explicitly defers pack re-selection to WP-06.

## In scope

- `run_comparison`: map over (merchant, item) search tasks at bounded
  concurrency (`SEARCH_CONCURRENCY = 2`, `services/agent/config.py`), calling
  WP-04's connectors directly.
- Converting each connector's raw `Observation` into WP-02's domain
  `Observation` — including the brand extraction WP-04 deliberately left at
  `attributes={}` (see `p3_merchant_port_adapter.py`'s docstring: "hard-attribute
  extraction isn't built (WP-06 scope)").
- Per-item, per-merchant matching with **bounded repair**: an exact match if
  one exists, else the cheapest match the item's own `Flexibility` already
  permits (via WP-02's `check_substitution`) — never a forbidden substitution,
  never a guessed one when nothing qualifies.
- Pack selection via WP-02's `select_packs` (minimise overbuy, then cost).
- Fee assessment integration: calling the connector's own `assess_fees` and
  converting its result into WP-02's `FeeAssessment`/`Charge`, with the real
  domain-separated `line_hash` (`services.domain.keys.line_hash`) — not the
  local placeholder hash WP-04's connectors fall back to
  (`services/merchants/fees.py::placeholder_line_hash`, which predates WP-02
  landing in this tree).
- Basket assembly (`build_basket`) and comparison (`compare_baskets`,
  `cheapest`), honoring the budget constraint and the live/fixture isolation
  rule.
- `POST /tasks/compare` on the agent's FastAPI app, the same shape as WP-04's
  `/tasks/search`.

## Out of scope

- Durable job/workflow wrapping of a compare call, and persistence of the
  `ComparisonOutcome` (WP-07).
- Hard-attribute extraction beyond brand (e.g. "organic", "variety") — no
  connector exposes structured attributes today; any such hard attribute is
  honestly unsatisfiable until one does (absence is never assent — WP-02).
- Re-check/recheck after a comparison is shown (WP-08's `prepare.py` owns
  refreshing a *chosen* basket).
- Voice/photo/usual-basket intent construction (WP-05) — this package
  consumes an already-built `Intent`.

## Components, ports, and dependency direction

```
FastAPI /tasks/compare -> run_comparison (services.agent.compare)
    -> services.merchants.registry (WP-04 connectors, direct calls)
    -> services.domain.{catalog,basket,money,errors,keys} (WP-02 rules, called only)
```

Lives in `services.agent`, not `services.application`: it calls P2's own
connectors directly and runs them concurrently, both of which
`services/application/boundaries_test.py` forbids for that package (P4's
adapter seam — `services.application` may depend on nothing but the domain
and the standard library). Confirmed by running that test suite against this
module's first draft: it failed exactly as designed, which is what moved this
file from `services/application/compare.py` to `services/agent/compare.py`.

Every domain rule (matching, pack selection, honesty-safe comparison) lives
in `services.domain` and is only ever called here, never re-implemented.

## API and event contracts

`POST /tasks/compare`
```
{
  "intent": <Intent, as Intent.model_dump(mode="json") produces it>,
  "location": {"locality": str, "pincode": str},
  "mode": "live" | "fixture"
}
-> <ComparisonOutcome, as ComparisonOutcome.model_dump(mode="json") produces it>
```

`ComparisonOutcome`: `search_id, intent_id, intent_revision, mode, location,
results: [MerchantResult], winner_merchant_id, budget_check`.
`MerchantResult`: `merchant_id, basket: Basket | null, unresolved:
[UnresolvedItem]`. Exactly one of `basket`/`unresolved` is populated per
merchant (a basket is only built once every item resolved).
`UnresolvedItem`: `item_id, name, reason_code, reason_detail` — `reason_code`
is either `"no_results"` or a WP-02 `DomainError.code` (e.g.
`hard_attribute_unsatisfied`, `substitution_not_permitted`,
`overbuy_limit_exceeded`). Deliberately a plain string, not the raw
`DomainError` dataclass: `UnresolvedItem` is a pydantic `Record` and must
round-trip to JSON.

Request validation note: `Intent` (a WP-02 `Record`) is `strict=True`, so a
plain-dict `model_validate` of a JSON-decoded body rejects list-for-tuple and
str-for-enum — the endpoint uses `Intent.model_validate_json(json.dumps(...))`
to get pydantic's JSON-mode coercion instead. Confirmed live against the
fixture connector's real catalog (see "Test plan").

## Idempotency, concurrency, timeout, and retry behavior

- One `search_id` per `run_comparison` call, generated fresh each time — no
  idempotency key yet (this package has no durable store; WP-07 owns that).
- (merchant, item) tasks run at `SEARCH_CONCURRENCY = 2` via a
  `ThreadPoolExecutor`, matching WP-04's own per-connector concurrency model
  (each engine's Playwright work is confined to its own thread; see WP-04
  spec, "Cross-merchant concurrency").
- A merchant's `search()` raising or returning a typed `MerchantError` yields
  zero observations for that (merchant, item) pair, surfaced as an
  `UnresolvedItem` — never a whole-run failure (SPEC section 1: partial
  coverage, not a failed search).
- Each (merchant, item) search shares one run-wide `deadline`
  (`ITEM_FETCH_DEADLINE_SECONDS = 45`, `services/agent/config.py`), the same
  per-item budget WP-04 already enforces per connector call.

## Failure modes and user-visible errors

An item can go unresolved on one merchant for any of:

| `reason_code` | When |
|---|---|
| `no_results` | Nothing usable (in stock, extraction OK/partial) came back for this item on this merchant. |
| `hard_attribute_unsatisfied` | Every candidate failed a hard attribute the item declared (other than brand — see below). |
| `substitution_not_permitted` | The only candidates differ in brand, and the item's `Flexibility` doesn't allow a brand change. |
| `overbuy_limit_exceeded` / `incompatible_units` | No pack combination of a permitted candidate group meets the required quantity within WP-02's overbuy ceiling, or a unit mismatch. |

A single unresolved item makes that **merchant's** basket incomplete
(`MerchantResult.basket = null`); it never blocks another merchant's basket.

## An important, deliberate honesty consequence — read before assuming a comparison will show a winner

**Two merchants whose fees are both `"estimated"` can never be declared
cheaper than one another, however large the price gap** — this is WP-02's
`compare_baskets` behaving exactly as designed (`basket_test.py`:
`test_two_estimated_baskets_are_not_comparable`), not a bug in this package.

As WP-04 is actually built, `assess_fees` on **both** Blinkit and Zepto
always returns `completeness="estimated"`, never `"complete"` (published-fee-
schedule estimate, since a real fee needs live-cart mutation — deliberately
never attempted). That means **every live two-merchant comparison this
package produces will have `winner_merchant_id = null`** unless a budget
filter happens to leave only one merchant standing. Each basket's
`totals.known_subtotal` is still reported (an honest lower bound) so the UI
has something to show, but "here's the cheaper one" is not a claim a live
comparison can make today.

This is the same gap P2 already flagged for WP-08 in
`docs/specs/P2-response-to-p3-open-questions.md` (D-1: an estimated basket
can never reach an exact quote either) — this package's tests
(`services/agent/compare_test.py`) now confirm it concretely at the
comparison layer too, not just the approval layer. **Fixture-mode
comparisons are unaffected**: the fixture connector's fee is labeled
`"complete"`, so a fixture-mode comparison reliably produces a provable
winner (see `main_test.py`'s
`test_tasks_compare_returns_a_provable_winner_in_fixture_mode`). This is
worth knowing before building the comparison UI (P1, WP-11) or picking demo
items (whoever scripts the walkthrough): plan the live-comparison beat around
"here's what each known subtotal is" language, not "X is cheaper than Y",
unless the demo specifically uses fixture mode for that beat.

## Observability and cost limits

- No AWS calls, no cost-bearing resources from this package alone (same as
  WP-04).
- No persistence: `run_comparison`'s result lives only in the HTTP response
  until WP-07's store exists.

## Test plan

### Unit
`services/agent/compare_test.py` — 16 tests, all against a scripted
`Merchant` fake (no real browser/network): fractional pack-size conversion
without truncation, brand extraction, pack-quantity selection preferring the
cheaper sufficient pack, forbidden vs. permitted brand substitution (and
preferring an exact match over a permitted one), partial coverage on a
merchant search failure, budget exclusion (including the case where the
globally cheapest basket exceeds budget but a second basket doesn't), live/
fixture mode isolation, and the two-estimated-baskets-not-comparable behavior
above (both directions: confirmed absent, and confirmed present when one
basket has no open charges).

### Contract/integration
`services/agent/main_test.py` — 7 tests against the real FastAPI app via
`TestClient`, real fixture data (`services/merchants/fixtures/*.json`), no
mocking: `/health`, `/tasks/search` (previously untested — WP-04's spec
listed this as blocked on WP-00's config, now merged), `/tasks/compare`
returning a provable winner in fixture mode, budget exclusion end to end, and
bearer-token auth gating on both task endpoints.

### End-to-end/manual
Ran `/tasks/compare` against the real FastAPI app with fixture data via a raw
`TestClient` call (not just pytest) during development, confirming the
`Intent.model_validate_json` request-parsing fix was necessary and correct
(`model_validate` on the raw dict fails strict-mode tuple/enum coercion;
`model_validate_json` on the same data, re-serialized, succeeds) — see
`main.py`'s `run_compare` docstring/comment.

### Not yet run
Against real Blinkit/Zepto live connectors (would require the same live
network access WP-04's manual verification used); expected to work
unchanged, since `run_comparison` calls the exact same `Merchant.search`/
`assess_fees` methods WP-04 already verified live — only the never-
comparable-when-both-estimated consequence above is new information from
combining the two, not a live-connector-specific risk.

## Acceptance criteria

- [x] Every registered merchant is searched for every item, concurrently,
      within one comparison run.
- [x] A merchant search failure or an unmatched item produces partial
      coverage (`UnresolvedItem`), never a failed run.
- [x] Matching never returns a hard-attribute-failing or forbidden-
      substitution candidate.
- [x] Pack selection never exceeds WP-02's overbuy ceiling.
- [x] Fee assessment is converted to WP-02's `FeeAssessment`/`Charge` with the
      real canonical `line_hash`, not a placeholder.
- [x] Comparison honors the budget constraint (excludes over-budget baskets
      from winner selection) and the live/fixture isolation rule.
- [x] `POST /tasks/compare` works end to end against real fixture data,
      auth-gated the same way as `/tasks/search`.
- [ ] Verified against real live Blinkit/Zepto connectors (see "Not yet run").
- [ ] Wrapped in a durable job (WP-07, not started).
- [ ] `ComparisonOutcome` persisted as a `Search`/`Basket` record pair
      (WP-07's store).

## Open questions and decisions

- **Product-group matching (`_product_key`) is a text heuristic**, not a
  structured product ID: brand plus up to three non-size name tokens. Two
  genuinely different products sharing that signature would wrongly combine
  into one pack-selection group. Accepted for the two-merchant, four-item
  hackathon scope; would need real product IDs (neither connector exposes
  one) to fully close.
- **Brand extraction (`_brand_of`) is "first capitalised token"** — a
  deliberately conservative guess since neither connector extracts a
  structured brand field. A wrong guess can only produce a spurious
  substitution record on a line (never a wrong price, never a bypassed hard
  attribute — see the module docstring). Revisit if a connector starts
  exposing a real brand field.
- **The live-comparison-rarely-has-a-winner consequence above** needs a
  product decision from whoever scripts the demo, not just documentation:
  either accept "known subtotal" language for the live-comparison beat, or
  script that beat in fixture mode. Not P2's call alone — flagging for P1
  (UI copy) and whoever owns the walkthrough script.
