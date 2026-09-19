# P2's response to WP-02/WP-08 open questions

P3 raised three items in `docs/specs/WP-02-core-domain-and-rules.md` and
`docs/specs/WP-08-preparation-quote-approval.md` (on
`feat/wp-02-08-09-transaction-safety-p3`) that explicitly need P2's
confirmation. Answered here, from P2's side (`feat/wp-04-live-merchants-p2`),
since the two branches aren't merged yet and this needs a durable record
either way.

## WP-08 D-5 — does "selected lines + one basket-level fee assessment" match `assess_fees` semantics?

**Confirmed, yes, exactly.** `Merchant.assess_fees(location, exact_lines: list[Line], deadline) -> FeeAssessment` in `services/merchants/base.py` already takes exactly this shape: the selected lines (not the whole basket's every alternative), one call, one basket-level `FeeAssessment` back. No change needed on either side.

## WP-02 D-2 — is `OVERBUY_LIMIT_BP = 15000` (1.5x) the right default?

**Confirmed as proposed — no change.** 1.5x gives enough room to match real Blinkit/Zepto pack-size jumps (500g/1kg/2kg/5kg for rice, for example) without permitting a wasteful overbuy. Nothing observed in live connector data during WP-04 suggests this needs to be looser or tighter. Revisit only if WP-06 matching against real pack sizes surfaces a specific case this rejects that shouldn't be rejected.

## WP-08 D-1 — estimated-fee merchants can be compared but not purchased: agreed, but flagging a real consequence

**Agreed with the rule itself.** An exact quote needs an exact total — approving "simulated ₹X" when X is an estimate is a false statement to the shopper, even in a simulated flow. This shouldn't be relaxed.

**The consequence that needs a real decision, not just a rubber stamp:** as WP-04 is actually built today, `assess_fees` on **both** Blinkit and Zepto always returns `completeness="estimated"` — never `"complete"`. A real, current fee requires adding items to a live cart on the merchant's actual site, which is deliberately never attempted (ToS risk, and the harness's own permission system correctly blocked a much smaller cart-mutation test during WP-04's development). There is no planned path to a `"complete"` fee from either live connector.

Under D-1's rule as written, **this means neither live merchant's basket can ever reach actual quote/approval** — only comparison. That's a real gap between "the live price-comparison pipeline works" and "the demo can show an approved, simulated purchase," and it needs a decision, not just documentation:

- **Option A** — accept it. The live path stops at comparison; only a fixture-mode basket (if the fixture connector is built to report `"complete"` fees) can demonstrate the actual approve → simulated-payment flow end to end.
- **Option B** — find or build a fee source that can honestly reach `"complete"` without cart mutation (e.g., a curated, disclosed fixed-fee table for a fixed demo item set — still not a live cart read, but could be labeled `"complete"` if the number is genuinely fixed and known rather than estimated from a range).
- **Option C** — reconsider D-1 specifically for the simulated-checkout case: since WP-09's payment is already sandboxed and no real money moves, treat "approve simulated ₹X (estimated)" as an honest sentence as long as the UI is explicit that X is an estimate — i.e., move the honesty requirement from "the number must be exact" to "the uncertainty must be disclosed." This changes P3's rule, so it needs P3's (and P1's, since they own the approval copy) agreement, not just P2's.

**P2's recommendation: Option A for now.** It requires no rule change and no new fee-estimation work, and it's consistent with everything else in this project labeling live vs. simulated/estimated explicitly rather than blurring them. Revisit if the demo specifically needs to show a live-merchant basket reaching approval, not just a fixture one.

---
Written 2026-09-17, from P2's side, against `origin/feat/wp-02-08-09-transaction-safety-p3` commit `d873fc4`. Needs P3 (and P1 for D-1/Option C if pursued) to actually read and respond — this file is P2's position, not a mutual agreement yet.
