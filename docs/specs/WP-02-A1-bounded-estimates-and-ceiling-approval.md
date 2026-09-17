# WP-02-A1 — Bounded estimates and ceiling approval

Amendment to `WP-02-core-domain-and-rules.md` and `WP-08-preparation-quote-approval.md`.
Resolves open question **D-1**, raised by P3 and answered by P2 in
`P2-response-to-p3-open-questions.md`.

Status: implemented, tests green. Decided by P3 (owner of WP-02/08/09) on 2026-09-17, on the
product owner's instruction to "work on top of what P2 has given".

---

## 1. The constraint, and why it is permanent

Neither live connector can read a real fee. A current delivery or handling fee
exists only inside a live cart, and adding items to a live cart is not
attempted — deliberately. P2's connector docstrings record the reason:
Blinkit sits behind Cloudflare bot management keyed off TLS fingerprint, and
Lightpanda refuses to impersonate a real browser (confirmed live: 403 from
Blinkit's edge). Zepto is equivalent. This is not an unfinished integration
that a later work package closes; it is a standing property of the data source.

So `FeeAssessment.completeness` is `"estimated"` for every live merchant, now
and for the life of this project. Only the fixture connector reports
`"complete"`.

## 2. What that breaks under the rule as written

WP-02 admits a total at three confidences and treats only `VERIFIED` as usable:

- **Approval** — `can_build_quote` rejects `ESTIMATED` with
  `QuoteNotConstructible(reason="estimated_total")`. No live basket can ever
  be approved.
- **Ranking** — `_beats` requires the candidate to be exact, so no estimated
  basket can win. `basket_test.py::test_two_estimated_baskets_are_not_comparable`
  asserts this deliberately. Two live merchants therefore return
  `NOT_COMPARABLE` at **any** price gap.

The second consequence is the serious one. It is not a degraded comparison; it
is no comparison at all, on the product's headline feature.

## 3. The insight that makes this fixable without weakening honesty

P2's estimates are not point guesses. `services/merchants/fees.py` constructs
them as **upper bounds, by rule**:

> Range values (e.g. "up to Rs 30", "Rs 5-28") resolve to their upper bound,
> never the lower one — an estimate must never make a basket look cheaper than
> it could turn out to be.

`_BLINKIT_HANDLING_FEE_PAISE = 11_00` is the top of the published ₹4–11 band.
`_ZEPTO_DELIVERY_FEE_PAISE = 28_00` is the top of ₹5–28.

An upper bound is a fact you can reason from. The existing model throws that
fact away by collapsing every non-verified amount into "unusable". The fix is
to carry it.

## 4. Design: floor and ceiling

Replace "confidence decides usability" with two explicit bounds on every
`Totals`.

| term | definition | meaning |
|---|---|---|
| `floor` | sum of **`VERIFIED` amounts only** | the basket cannot cost less than this |
| ceiling | the **existing `total` field**, unchanged | the basket should not cost more than this |

**Only `floor` is a new field.** Review found that the proposed `ceiling` is
exactly the existing `total`: `compute_totals` already sets
`total = known_subtotal` whenever confidence is not `UNKNOWN`, and
`known_subtotal` already sums estimated charges at their upper bound. So
`total` *is* the ceiling for an estimated basket, and is the exact amount for
a verified one. `confidence` says which. Adding a second field carrying the
same number would be redundant state that can drift out of step.

Line amounts are `VERIFIED` — P2 builds them with `Amount.known(...)`, whose
default confidence is `VERIFIED` (`compare.py:333`). So `floor` is the basket's
item subtotal in practice, not zero, and the comparison has real room to fire.

`ESTIMATED` and `UNKNOWN` amounts contribute **zero** to `floor`. That is
deliberately conservative: an estimated fee's true lower bound is not known
(a free-delivery threshold can take it to zero), so claiming any positive
floor for it would be a guess.

### Comparison rule

> `A` is definitively cheaper than `B` **iff** `A.total is not None and
> A.total < B.floor`.

Soundness: `A.true ≤ A.total` (ceiling) and `B.true ≥ B.floor`, so
`A.total < B.floor ⟹ A.true < B.true`. The claim is proved, never guessed.

### This is strictly sounder than the current rule

Today `_beats` compares against `other.known_subtotal`, and `known_subtotal`
includes estimated charges at their upper bound. Using an upper-bound-inflated
figure as if it were a *lower* bound is unsound: if Zepto's real delivery fee
is ₹5 where we estimated ₹28, the current comparator can declare a rival
cheaper when it is not. **This amendment fixes a live soundness bug in WP-02,
not only a restriction.**

Existing behaviour is preserved where it was already correct:

| case | today | under A1 |
|---|---|---|
| verified 9 000 vs estimated (10 000 + 500) | LEFT_CHEAPER | LEFT_CHEAPER (floor 10 000) |
| verified 11 000 vs estimated (10 000 + 500) | NOT_COMPARABLE | NOT_COMPARABLE |
| verified vs verified | exact compare | identical (`floor == ceiling`) |
| any basket with an unknown charge | NOT_COMPARABLE | NOT_COMPARABLE (`ceiling is None`) |
| **estimated (10 000 + 100) vs estimated (20 000 + 100)** | **NOT_COMPARABLE** | **LEFT_CHEAPER** |

Only the last row changes. `test_two_estimated_baskets_are_not_comparable` is
rewritten to assert the new rule, and a companion test pins the case where the
bands overlap and the answer must remain `NOT_COMPARABLE`.

## 5. Approval becomes an authorisation ceiling

`can_build_quote` stops rejecting `ESTIMATED`. A quote built from an estimated
total carries `ceiling` as its amount, and the approval control says:

```
Approve simulated up to ₹590.00
```

This is the honest sentence. The shopper authorises a maximum; the true cost
can only land at or below it. It mirrors how a real payment authorisation
works, and it is exactly what the data supports — no more, no less.

`UNKNOWN` remains rejected, unchanged. An unknown charge has no ceiling, so
there is no maximum to authorise and nothing honest to put on the button.

### What must not happen

- The label must never read `Approve simulated ₹590.00` for an estimated
  quote. Dropping "up to" turns a bound into a claim.
- `ceiling` must never be rendered as the expected price. It is a maximum.

## 6. Two leaks in the upper-bound claim — disclosed, not hidden

The ceiling is a *best-known* bound, not a guaranteed one. Two documented
gaps, both P2's to close:

1. **Zepto's late-night surcharge (~₹15) is not modelled.** `fees.py` says so
   outright: there is no reliable "is it late night" signal without a real
   order timestamp. A late-night basket can therefore exceed its ceiling.
2. **Published schedules drift with no staleness signal.** `fees.py` again:
   Zepto's platform fee was introduced in 2024 and rolled back by 2025 per the
   same source, and nothing tells this code when its numbers went stale.

Neither is fixed here, because neither is WP-02's to fix. This spec provides a
*correct mechanism*; it depends on P2 supplying *honest inputs*. Raised to P2
as A1-Q1 (§10).

This is why the disclaimer must state the fee is estimated from published
schedules rather than read from the merchant — the existing mode/fixture
disclosure is not sufficient for this.

## 7. Code changes

| file | change |
|---|---|
| `domain/money.py` | `Totals` gains **`floor: Money`** only; `compute_totals` computes it as the verified-only sum; validator asserts `floor <= known_subtotal` |
| `domain/basket.py` | `_beats` rewritten to `candidate.total < other.floor`; `_is_exact` no longer gates who may win |
| `domain/purchase.py` | `can_build_quote` drops the `ESTIMATED` rejection; `UNKNOWN` rejection unchanged |
| `application/prepare.py` | `build_quote` stops refusing an estimated total |
| `application/copy.py` | `APPROVE_CEILING_LABEL = "Approve simulated up to ₹{amount}"`; `approve_label` takes the confidence and picks the wording |
| `contracts/openapi.yaml` | `Quote` gains `amount_is_ceiling: boolean` (derived, for the UI); `Totals` schema gains `floor_paise` |

`known_subtotal` is **retained**, unchanged, and still means "sum of every
amount we have a number for". It is consumed by `copy.lower_bound_label` and
by P2's `compare_test.py:289`. Removing it would break P2 for no gain.

## 8. Hash impact: none

The first draft of this spec claimed `quote_hash` had to grow new terms.
**That was wrong, and review caught it.** `quote_hash` already binds `lines`
and `charges`, and `confidence` is part of a `Charge`'s canonical form —
verified directly:

```
verified  -> {"amount":{"amount_paise":3000,...},"confidence":"verified","kind":"delivery"}
estimated -> {"amount":{"amount_paise":3000,...},"confidence":"estimated","kind":"delivery"}
```

Two quotes with identical numbers but different confidence therefore already
hash differently. The ceiling and the `amount_is_ceiling` flag are both pure
functions of terms that are already bound, so binding them again would add
nothing and would force every golden vector to be regenerated — breaking
cross-package verification with P2 and P4 for no gain.

**No change to `keys.py`. No golden-vector regeneration.**

## 9. Tests

New or rewritten:

1. `test_two_estimated_baskets_compare_when_bands_are_disjoint` — the row that changes.
2. `test_two_estimated_baskets_do_not_compare_when_bands_overlap` — the guard.
3. `test_estimated_ceiling_never_ranks_below_a_rivals_floor` — Hypothesis, over arbitrary amounts.
4. `test_an_unknown_charge_leaves_ceiling_absent_and_blocks_both_paths`.
5. `test_estimated_quote_label_says_up_to` — asserts the literal string.
6. `test_verified_quote_label_omits_up_to` — the inverse; guards against blanket relabelling.
7. `test_ceiling_is_bound_into_quote_hash` — mutate the ceiling, expect mismatch.
8. Regression: every existing `basket_test.py` and `money_test.py` case in §4's table.

## 10. Open items

- **A1-Q1 → P2.** For the ceiling to be true, the late-night surcharge must be
  either modelled or folded into the estimate as a worst case, and the
  schedule needs a `fetched_at`/`source_checked_on` field so staleness is
  visible. Until then the ceiling is best-effort and §6 must stay in the
  disclaimer.
- **A1-Q2 → P1.** The approval control must render `approve_label` verbatim
  and must not compose its own amount string. "up to" is load-bearing.
- **A1-Q3 → P2.** Two defects in `p3_merchant_port_adapter.py` become
  materially more dangerous under A1, because an estimated total is now
  approvable rather than inert:
  - a fee the merchant does not know arrives as `None` and no charge is
    appended at all, so it is counted as zero rather than as unknown;
  - an unrecognised `completeness` string falls through to `VERIFIED`.

  Scope correction from review: **`compare.py` is not affected.** Its own
  mapping (`compare.py:384-389`) defaults the unrecognised case to
  `ESTIMATED`, which is safe. The defect is confined to the adapter.

## 11. What this does not change

- Live and fixture baskets are still never ranked together.
- An unknown fee is still never zero, still blocks the quote, and still has no
  ceiling.
- Mode labelling, terminal-sticky provider facts, dispatch-before-call, the
  409/422/410/404 contract and every WP-09 rule are untouched.

---

## 12. Spec review record

Reviewed before implementation, per the project's spec -> review -> implement
-> review method. Four findings, three of which changed the design:

1. **`ceiling` was redundant.** It is arithmetically identical to the existing
   `total`. Dropped; only `floor` is added. Removes a second source of truth
   for the same number. (§4, §7)
2. **The hash-change requirement was false.** `confidence` is already inside a
   `Charge`'s canonical form, so the distinction A1 introduces is already
   bound. Verified by running `canonical_json` on both confidences. Removes a
   golden-vector regeneration that would have broken P2 and P4. (§8)
3. **Blast radius overstated.** `compare.py` defaults unrecognised
   completeness to `ESTIMATED`, not `VERIFIED`; only the adapter is unsafe.
   (§10, A1-Q3)
4. **Load-bearing assumption confirmed, not assumed.** The design is worthless
   if line amounts are not `VERIFIED`, since `floor` would collapse to zero
   and nothing could ever be proved cheaper. Checked: `Amount.known` defaults
   to `VERIFIED` and `compare.py:333` relies on that default. Design holds.

---

## 13. Implementation review record

Implemented and reviewed. 928 tests pass, ruff clean, and no new mypy error in
production code (the 8 that remain are P4's baseline `envelope.py`, `health.py`
and `local_app.py`, untouched by this change).

### Found during implementation, not during specification

1. **A second enforcement point the spec missed.** `CheckoutQuote` carries its
   own `_every_charge_is_known` validator rejecting any non-verified charge,
   independently of `can_build_quote`. Relaxing only the gate would have left
   quote construction raising a `ValidationError` instead. Found because the
   rewritten test failed; now refuses `UNKNOWN` only.
2. **`total_confidence` was needed and did not exist.** The label has to know
   whether the amount is exact or a ceiling. Added as a derived property on
   `CheckoutQuote` rather than a stored field, so it cannot contradict the
   charges it is computed from.
3. **`approve_label` takes `confidence` as a required argument.** A default
   would mean a caller who forgets it silently ships the un-hedged wording on
   an estimated total -- the one mistake this function exists to prevent.
4. **`amount_is_ceiling` is exposed on the quote payload, not just the label.**
   P1 shows the amount on more than the approve control, and a ceiling rendered
   as an expected price is the same lie in a smaller font.

### Verified, not assumed

- **The live case now works.** Replaying P2's published fee schedule
  (`fees.py`, verbatim) across two live merchants: disjoint bands name a winner
  (`Rs 480.00-491.00` beats `Rs 520.00-522.00`), overlapping bands still return
  no winner (`Rs 480.00-491.00` vs `Rs 485.00-487.00`). Both halves matter --
  the second is what keeps this honest rather than merely decisive.
- **The guards are load-bearing.** Mutation-tested: comparing ceiling against
  ceiling instead of floor breaks 3 tests; dropping the "up to" wording breaks
  1. Neither passes silently.

### Deviation from SPEC section 1 -- needs team sign-off

SPEC section 1 says "estimated totals never rank as definitively cheaper than
verified totals". A1 does not enforce that: an estimate whose ceiling sits
entirely below a verified total now wins. The rationale is in §3 and repeated in
`basket.py`'s module docstring so it is visible where the code lives.

This is the one part of A1 that changes a rule the whole team agreed, so it
should not ship on P3's authority alone. Practically it is near-unreachable --
mixed modes are never ranked, live baskets are uniformly estimated and fixture
baskets uniformly verified, so estimated-versus-verified barely arises in the
real pipeline -- but the rule is written down and this contradicts it.
