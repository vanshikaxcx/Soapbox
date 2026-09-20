# WP-09 — Independent simulator, checkout, and callback contract

Owner: P3 — Transaction safety
Reviewers: P4 (delivery, security, callback ingestion), P2 (isolation from merchant agents); P1 informed (outcome copy)
Status: Draft — awaiting Gate A review
Depends on: WP-02 (rules), WP-07 (workflow, tasks, outbox), WP-08 (attempt, provider lookup, request hash)
Target merge: Day 2, end of day

---

## Outcome and user value

This is the package the whole demo is built to show.

A shopper approves. The payment provider accepts the payment — and then the response is lost.
The app does not know whether money moved. The shopper reloads, taps retry, and reloads again.

What must happen: **the same one attempt, in a clearly-labelled unknown state, and exactly one
effect in the provider's ledger.** Not a second payment. Not a cheerful "failed, try again" that
hides a real charge. Not a spinner that forgets on refresh.

WP-09 delivers three things that make that true:

1. An **independent simulator** with its own ledger, which is the only writer of provider truth.
2. A **checkout task** that persists intent before acting, reuses one key forever, and treats
   silence as ambiguity rather than as failure.
3. A **callback contract** — signed, deduplicated, matched and immutable — that P4 implements in
   WP-10 and that reconciles the truth when it finally arrives.

## In scope

1. The simulator: separate DynamoDB table, typed `Payment` / `Order` / `Refund` operations,
   conditional ledger writes, key uniqueness, request-hash conflict, expiry handling.
2. Operator-only scenario control and the effect-count endpoint.
3. The checkout workflow task: dispatch marking, submission, ambiguity handling, the polling
   schedule and the three-minute observation window.
4. Idempotent simulated order creation after verified payment.
5. `POST /purchases/{id}/reconcile` — read existing references, never create.
6. The **callback envelope contract**: canonical signing input, headers, body schema,
   verification order, deduplication, matching and quarantine rules — defined and contract-tested
   here, implemented by P4 in WP-10.
7. The authoritative read-only **provider-fact query** API that recovery consumes.
8. Case opening on an unresolved window (handing off to WP-10).

## Out of scope

- The callback HTTP handler, inbox persistence and reconciliation workflow — **WP-10, P4.**
  WP-09 owns the contract and the contract tests; P4 owns the endpoint.
- Guidance corpus, case narrative, draft and export — WP-10.
- Step Functions definitions, SQS/DLQ wiring, IAM roles and the Lambda invoke plumbing — WP-07.
- The `/demo` operator screen — P1, WP-11. WP-09 owns the API behind it.
- Real payment rails of any kind. Nothing in ProofPath touches money.

## User flow and UI states

The demo sequence, and what each step must show:

| Step | Domain state | Shopper sees |
| --- | --- | --- |
| Approve | `dispatch = ready` | "Sending your simulated payment" |
| Dispatch marked | `dispatch = started`, payment `claimed` | Same — the marker is invisible but decisive |
| Response lost | payment `unknown` | **"We're confirming this payment"** — never "failed" |
| Reload / retry | payment `unknown`, same attempt | The identical attempt, same amount, same time |
| Polling finds success | payment `succeeded`, order `pending` | "Payment confirmed · creating order" |
| Order confirmed | order `confirmed` | Success, with both facts shown separately |
| Window elapses | payment `unknown` or `pending` | "Still unresolved" + a case is opened |
| Late callback arrives | payment `succeeded`, order missing | "Paid, but we can't find an order" → case |
| Definitive failure | payment `failed` | "Payment did not go through" + approve again allowed |

Three copy rules, non-negotiable:

- Payment, order and refund are shown as **three separate facts**, never merged into one status.
- `unknown` is displayed as its own state with its own wording. It is never rendered as failure
  and never as success.
- A failed *job* is shown as a system retry affordance and never as a payment outcome.

## API and event contracts

### Simulator operations (internal, IAM `lambda:InvokeFunction` only)

```text
Payment.submit(provider_key, quote_hash, seller_id, total_paise, currency, expires_at) -> PaymentFacts
Payment.query(provider_key)                                                            -> PaymentFacts | NotFound
Order.create(order_key, payment_reference, quote_hash)                                 -> OrderFacts    # checkout only
Order.get(order_key)                                                                   -> OrderFacts | NotFound
Refund.query(refund_reference)                                                         -> RefundFacts | NotFound
```

There is deliberately no `Refund.initiate`. Refunds exist in ProofPath only as facts that arrive
from the provider, which is why WP-02's refund machine has no initiation event.

### Simulator ledger (separate table)

`PAYMENT#{provider}#{payment_key}` →
`{request_hash, seller_id, amount_paise, currency, expires_at, status, provider_reference,
created_at, scenario, effect_recorded: bool}`

`ORDER#{provider}#{order_key}` → `{payment_reference, quote_hash, status, created_at}`

Write rules, all conditional:

- **Unseen key** → check `expires_at` against the simulator's own clock **atomically with the
  insert**. If already past, write an immutable `expired_rejected` record with
  `effect_recorded = false`. The rejection is itself durable, so a replay returns the same
  answer rather than being accepted late.
- **Same key, same `request_hash`** → return the original facts unchanged, **even after
  expiry, even after any number of replays**. This is what makes the checkout task's resend safe.
- **Same key, different `request_hash`** → `PaymentKeyConflict`. No write, no effect. Combined
  with WP-08 freezing `request_hash` at approval time, approved-₹X-submitted-₹Y is unreachable
  from both directions.
- Only the simulator writes this table. No other Lambda, task or role has write access to it.
- **The scenario is captured on the ledger record at write time.** An operator changing the
  scenario afterwards does not retroactively change a recorded effect — the ledger is a record of
  what happened, not a view over current settings. This matters during the demo, where the
  operator will be switching scenarios between runs while earlier purchases stay on screen.

### Operator API

- `POST /demo/scenarios` — set the active scenario for an owner or a purchase. Cedar action
  `SetScenario`, operator role only; a shopper receives `404`, never `403`.
- `GET /demo/effects` — counts straight from the ledger: payment effects, order effects,
  submissions received, duplicate submissions suppressed, callbacks sent. These are the numbers
  WP-11 displays and the video shows.

Scenarios: `SUCCESS` (default), `DEFINITIVE_FAILURE`, `ACCEPT_THEN_TIMEOUT`,
`PAID_ORDER_MISSING`, `DUPLICATE_CALLBACK`, `CONFLICTING_CALLBACK`, `REFUND_PENDING_THEN_COMPLETE`.

`ACCEPT_THEN_TIMEOUT` is the one that matters most: the simulator **commits the payment effect
and then fails the response**. The effect is real; the caller learns nothing. That is the exact
shape of the failure the product exists to survive, and it is why the dispatch marker must be
written before the call rather than after.

### `POST /purchases/{id}/reconcile`

Reads the original references — `payment_key`, `order_key`, any refund reference already present
in provider facts — and applies whatever the provider currently reports, through WP-02's
fact-application rules. Cedar action `ReconcilePurchase`.

Reconcile needs no idempotency key: applying the same provider facts twice is a no-op by WP-02's
rules, so the endpoint is idempotent by construction rather than by bookkeeping. It is rate
limited per purchase (one call per 10 seconds) so a shopper tapping "check again" cannot turn
into a provider query storm.

It **cannot** create a payment, an order, a refund or an attempt. This is enforced structurally,
not by review: reconcile imports `provider_read` only. `Payment.submit` and `Order.create` live
in `provider_write`, which `provider_read` does not import and which the recovery and reconcile
paths never import. A test asserts the import graph, so the guarantee survives refactoring.

### Callback envelope — the contract P4 implements

```text
POST /callbacks/simulator
X-ProofPath-Provider:            sim
X-ProofPath-Event-Id:            <opaque>
X-ProofPath-Delivery-Timestamp:  <RFC3339 UTC>
X-ProofPath-Signature:           <lowercase hex HMAC-SHA256>

{ "event_id", "provider", "kind": "payment"|"order"|"refund",
  "key", "reference", "status", "amount_paise", "currency",
  "seller_id", "observed_at" }
```

Signing input, exactly: `delivery_timestamp + "\n" + event_id + "\n" + raw_body` — the **raw**
body bytes as received, never a re-serialised object. The timestamp is a header and is refreshed
on redelivery, so the signature changes between deliveries while `event_id` and body stay fixed.

Verification order, which is also the order of the contract tests:

1. Known provider, else `400`.
2. Timestamp skew ≤ 5 minutes, else `400`. Both directions — a future timestamp is as invalid as
   a stale one.
3. Signature valid under a **constant-time** comparison, else `401`.
4. **Persist the immutable `InboxEvent` before returning `2xx`**, conditional on
   `attribute_not_exists(provider, event_id)`. Durability precedes acknowledgement; a provider
   that got a `2xx` must never need to redeliver for our sake.
5. Only then resolve and apply.

Deduplication and matching:

- Same `(provider, event_id)`, same `body_hash` → `duplicate`, `200`, no state change.
- Same `event_id`, **different** `body_hash` → `conflicted`, `202`, never applied, flagged for
  operator attention.
- Resolve `ProviderLookup` by `(provider, key)`. Unknown key → `quarantined`.
- Compare `seller_id`, `amount_paise`, `currency` against the lookup's expected values →
  mismatch is `quarantined`, not applied. A callback claiming a different amount is exactly the
  kind of thing that must never silently become truth.
- Apply through WP-02 only: terminal-sticky, contradictory-terminal quarantine, stale-fact
  ignore. An old `pending` cannot downgrade a `succeeded`, structurally.

## Data model and state transitions

No new record types. WP-09 drives WP-02's machines and adds the simulator's own ledger record,
which lives in a different table and is deliberately not a domain record.

### The checkout task

```text
1. Load attempt, approval, quote, provider lookup.
2. If dispatch == ready and (quote expired or approval expired):
     conditional ready -> expired_unsent; release claim; clear active attempt.
     Job SUCCEEDS. No provider call was made, so there is no exposure.   [WP-08 rule]
     If the condition FAILS because dispatch is already expired_unsent, that is success,
     not an error: another run got there first. Re-read and finish.
     If it fails because dispatch is already started, do NOT expire it -- fall through
     to the query loop, because a provider call has happened and only facts decide now.
3. Resolve the ProviderLookup for this payment_key. Missing -> fail the task loudly.
     A payment is NEVER submitted without a resolvable lookup row, because without it a
     returning callback could not be matched and would have to be quarantined.
4. Conditional dispatch ready -> started.        <-- PERSISTED BEFORE ANY NETWORK CALL
5. Rebuild the submit payload; assert it hashes to attempt.request_hash. Refuse if not.
6. Payment.submit(...).
     success  -> apply facts
     timeout / error / lost response -> payment = unknown, continue at 7
7. Payment.query(payment_key) on 5s, 10s, 20s, 30s, 30s... to a 3-minute window
     measured from attempt.started_at, not from the first failure.
     NotFound and dispatch == started -> resend the IDENTICAL payload, same key, same expiry.
8. payment succeeded -> Order.create(order_key, payment_reference, quote_hash), idempotent.
9. Window elapses unresolved -> retain the attempt, open a case, job SUCCEEDS.
```

Step 3 before step 5 is the whole design. If the process dies between them, the attempt is
`started` with no facts — ambiguous, and correctly so. If we wrote the marker after the call, a
crash would leave `ready`, the system would think nothing happened, and a retry would pay twice.

Step 6's resend is safe only because of three independent guarantees stacked: the key is derived
and unchanged, the payload is hash-frozen at approval, and the simulator returns original facts
for an identical replay. Any one of them alone would be a bug waiting to happen.

Step 8 is where a lesser system lies. The job **succeeds** — it did its work correctly. The
*payment* is unresolved. Conflating the two is the specific mistake SPEC §8 calls out, and the
one a judge is most likely to probe by asking "so what does the user see?"

### Simulator ledger status → domain payment state

The ledger has statuses the domain does not, so the mapping must be explicit or two people will
each invent one:

| Ledger status | Domain payment | Claim | New approval allowed |
| --- | --- | --- | --- |
| `accepted` / `pending` | `pending` | held | No |
| `succeeded` | `succeeded` | held | No — it is paid |
| `failed` | `failed` | released | Yes |
| `expired_rejected` | **`failed`** | released | Yes |
| no response at all | `unknown` | held | No |

`expired_rejected` is the case the pre-dispatch `expired_unsent` rule does *not* cover: dispatch
had already started, we did call the provider, and the provider refused because the quote's
expiry had passed. It is a definitive, zero-effect refusal — so it maps to `failed`, not to
`unknown`, and the shopper may approve again. The distinction matters: `expired_unsent` means we
never called, `expired_rejected` means we called and were told no. Both are safe; only the second
produces a provider record.

### Order creation

`Order.create` runs **only** after `payment = succeeded`, never speculatively, and uses
`order_key = H(tag, purchase_id, attempt_id)` from WP-02 — so a retried task creates the same
order or none at all. Order failure never changes the payment state: the money is gone and the
order is missing, which is precisely the `PAID_ORDER_MISSING` case the recovery flow exists for.

### Polling and the observation window

5s, 10s, 20s, then 30s intervals to a **three-minute** total, measured from `started_at`. Each
poll persists `next_check_at` on the attempt, so a crash resumes the schedule rather than
restarting it — the requirement on WP-07 is that the wait/poll loop is workflow-driven and
resumable, not an in-process sleep, since an in-process sleep dies with its Lambda. After
the window: the attempt is retained in its real state, a case is opened, and polling stops. We
do not poll forever and we do not declare failure.

## Components, ports, and dependency direction

```text
workers/checkout_task.py       orchestration only
  -> application/checkout_use_cases.py
      -> domain (WP-02)        every transition and key
      -> ports:
          ProviderWritePort    submit / create        (simulator adapter)   [checkout only]
          ProviderReadPort     query / get            (simulator adapter)   [checkout + recovery]
          StateStore, JobStore                        (P4, WP-07)

simulator/                     its own Lambda, its own table, the only writer of provider truth
  ledger.py  operations.py  scenarios.py  callback_sender.py
```

- `ProviderWritePort` and `ProviderReadPort` are **separate types in separate modules**. Recovery
  and reconcile may depend on the read port only. The split is what makes "recovery creates no
  commerce effect" a property of the import graph rather than a promise.
- The simulator never imports domain state or the app table. It knows keys, amounts and its own
  ledger. It is a stand-in for a third party and is built like one.
- The agent container has **no** route to the simulator: no tool, no port, no IAM permission.
  P2's review of this package is specifically to confirm that isolation.

## Security, privacy, and authorization

- Callback secret in Secrets Manager, rotated, never in source, logs or prompts. The signature
  comparison is constant-time.
- A callback is authenticated **only** by its HMAC. Source IP, user agent and body claims confer
  no trust. Body content is data, never instruction.
- Scenario control and effect counts require the operator role. Shoppers get `404`. Seeding a
  restricted demo-operator identity for judges is WP-11's job and must not weaken this check.
- The simulator's table has a dedicated IAM role. The API Lambdas, the agent container and the
  recovery path have no write access to it.
- No PAN, UPI handle, OTP, PIN or credential exists anywhere in this package — there is nothing
  of that kind to leak, by design.
- Reconcile and recovery cannot reach a write operation; enforced by the import-graph test.

## Idempotency, concurrency, timeout, and retry behavior

- One `payment_key` per approval, forever. Submit, resend, query, crash, restart, generation
  bump — all the same key.
- Submit is idempotent at the simulator: identical replay returns original facts; different
  payload conflicts.
- `Order.create` is idempotent on `order_key`.
- Task retries are bounded by WP-07 with `Catch`; a retried task re-reads state and continues
  rather than restarting the payment.
- Duplicate SQS/EventBridge delivery resolves the same run and never starts a second one.
- A stuck `running` job is repaired by `GET /jobs/{id}` consulting `DescribeExecution` (WP-07) —
  repairing a job status never touches payment state.
- Callback redelivery is expected and safe: dedupe by `(provider, event_id)` + body hash.
- The simulator's own writes are conditional, so concurrent submit and callback cannot interleave
  into a second effect.

## Failure modes and user-visible errors

| Failure | System behaviour | Shopper sees |
| --- | --- | --- |
| Submit times out | `unknown`, query loop begins | "Confirming this payment" |
| Simulator unreachable | `unknown`, bounded retry, then case | Same — never "failed" |
| Payment definitively failed | `failed`, claim released | "Did not go through", approve again allowed |
| Paid, order creation fails | payment `succeeded`, order `failed`/`unknown` | Both facts, separately; case opens |
| Window elapses unresolved | attempt retained, case opened | "Still unresolved", with what we know |
| Callback signature invalid | `401`, nothing recorded, alarm | Nothing — never user-visible |
| Callback conflicts | `conflicted`, never applied, operator alarm | Unchanged state |
| Callback amount mismatch | `quarantined` | Unchanged state |
| Task crashes after dispatch | `started` + `unknown` on resume | The same attempt, unchanged |
| Job fails | job failure + retry affordance | **Never** a payment outcome |

## Observability and cost limits

Logs: `request_id`, `job_id`, `execution_arn`, `purchase_id`, `attempt_id`, `payment_key`,
`provider_reference`, poll number, outcome code. Never the callback secret, never a raw body.

Metrics — these are the demo's evidence:

- `provider_payment_effects` — **must equal** `attempts_dispatched`, always;
- `submissions_sent` vs `duplicate_submissions_suppressed` (resends are expected; effects are not);
- `callbacks_received` / `applied` / `duplicate` / `conflicted` / `quarantined`;
- `seconds_from_timeout_to_case_opened`;
- payment state distribution, and time spent in `unknown`.

Cost: one extra Lambda and one small on-demand table. Polling is bounded at ≤ 8 queries per
attempt over three minutes, so a stuck attempt cannot generate unbounded invocations.

## Test plan

### Unit

Simulator ledger
- unseen key, in date → effect recorded once, facts returned.
- unseen key, already expired → immutable `expired_rejected`, `effect_recorded = false`, and a
  later replay returns that same rejection rather than accepting late.
- same key + same request hash × 50 replays → one effect, identical facts every time.
- same key + different request hash → `PaymentKeyConflict`, no write, effect count unchanged.
- expired key, identical replay → original facts, still one effect.
- `Order.create` twice on one `order_key` → one order.

Checkout task (fake provider, injected clock)
- dispatch is persisted `started` **before** the submit call — asserted by ordering the fake's
  recorded calls, not by reading the code.
- crash injected between marker and submit → resume finds `started` + `unknown` and queries; it
  does not re-approve and does not create a second attempt.
- `ACCEPT_THEN_TIMEOUT` → exactly one ledger effect, attempt `unknown`, no second submission
  with a different payload.
- payload mutated between approval and submit → refused on the `request_hash` assertion.
- `NotFound` + `started` → resend is byte-identical, including expiry.
- polling schedule is exactly 5/10/20/30/30…, resumes from `next_check_at` after a crash, and
  stops at three minutes.
- `Order.create` is never called while payment is `pending` or `unknown`.
- window elapses → job status `succeeded`, payment still `unknown`, case opened.

Callback contract
- valid signature over the raw body → accepted; re-serialised body → rejected (catches the
  classic JSON round-trip bug).
- skew at −5m01s, −4m59s, +4m59s, +5m01s.
- tampered body, tampered timestamp, tampered event id → all `401`.
- inbox row is written before the `2xx` — asserted by failing the store and checking that no
  `2xx` is returned.
- duplicate event → `200`, no state change. Same id, different body → `conflicted`, not applied.
- unknown key → quarantined. Amount / seller / currency mismatch → quarantined.
- late `pending` after `succeeded` → ignored. `failed` after `succeeded` → contradictory,
  quarantined, state unchanged.

### Contract

- **Callback envelope golden vectors**: signing input, signature and expected disposition, so
  P4's WP-10 handler is verified against the same fixtures before the two halves ever meet.
- **Provider-fact query contract**: the exact shapes recovery consumes.
- **Import-graph test**: `provider_read` does not import `provider_write`; reconcile and the
  recovery tool wrappers do not import `provider_write`. Fails the build if anyone adds it.
- **Tool-registry test**: no agent tool targets the simulator or any write operation.
- Simulator operation schemas pinned so P4's Lambda invoke and my adapter cannot drift.

### Integration (in-memory adapters, no AWS)

Every scenario end to end, each asserting **one effect**:

- `SUCCESS` — paid, order confirmed, one effect.
- `DEFINITIVE_FAILURE` — failed, claim released, a new approval permitted, one effect.
- `ACCEPT_THEN_TIMEOUT` — unknown, reload ×5, retry ×5, **one effect**, same attempt throughout.
- `PAID_ORDER_MISSING` — payment succeeded, order missing, case opened, no order retry loop.
- `DUPLICATE_CALLBACK` — applied once.
- `CONFLICTING_CALLBACK` — never applied, operator alarm raised.
- `REFUND_PENDING_THEN_COMPLETE` — refund transitions independently; payment and order untouched.
- Expiry before dispatch — `expired_unsent`, zero effects, fresh approval gets a new key.

Plus: the full P3 lane in one harness — fixture basket → prepare → approve → checkout →
ambiguity → reload → callback → reconcile → resolved, with no AWS anywhere. This is the artifact
that makes my section demonstrably done regardless of the other lanes' progress.

### End-to-end / manual

- Playwright against the deployed backend with the operator setting `ACCEPT_THEN_TIMEOUT`:
  approve → unknown → reload → retry → late callback → resolved, with `/demo/effects` showing
  **1** throughout.
- Shopper identity hitting `/demo/scenarios` → `404`.
- Trace evidence retained: execution ARN, effect count before and after, callback IDs.

## Acceptance criteria

1. One approval produces **exactly one** provider payment effect, across reload, retry, crash,
   duplicate delivery and workflow-generation bump — proven by ledger count, not by UI.
2. Dispatch `started` is persisted before any network call, proven by call ordering.
3. The same `payment_key`, payload and expiry are used for every submit and resend; a mutated
   payload is refused before it is sent.
4. Identical replay returns original facts even after expiry; a changed payload conflicts with
   no effect.
5. An unseen key past its expiry records an immutable no-effect rejection.
6. `Order.create` happens only after verified payment and is idempotent on `order_key`.
7. Payment, order and refund states move independently; none is derived from another.
8. `unknown` is never rendered as success or failure, and a failed job is never rendered as a
   payment outcome.
9. No new attempt is possible while payment is `claimed`, `pending`, `unknown` or `succeeded`.
10. Callbacks verify provider, skew and signature in that order, persist the immutable inbox row
    before `2xx`, and deduplicate on `(provider, event_id)` + body hash.
11. Same event id with a different body conflicts and is never applied.
12. Amount, seller or currency mismatch is quarantined.
13. An old `pending` fact can never downgrade a `succeeded`; contradictory terminals quarantine.
14. Reconcile and recovery have **no import path** to any write operation.
15. The agent container has no route to the simulator.
16. Scenario control and effect counts are operator-only; shoppers get `404`.
17. `provider_payment_effects == attempts_dispatched` over the entire demo run.

## Rollout, rollback, and fixture strategy

- Simulator is a separate Lambda and table, deployable and revertible independently of the app
  stack. Its table is disposable — teardown drops it.
- The callback envelope is a **breaking** contract with WP-10: any change needs P4's re-approval
  and the two approvals the POA mandates for payment-state changes. Versioned as
  `proofpath.callback.v1`.
- Default scenario is `SUCCESS`, so nothing is faulty unless an operator asks for it.
- Seed script puts a purchase into each terminal and each ambiguous state, so WP-11 and the video
  never depend on live timing.
- Fixture-mode purchases run through the same simulator; the demonstration label rides the quote
  hash and the export, so a fixture run can never be presented as a live one.

## Open questions and decisions

- **D-1 — How `ACCEPT_THEN_TIMEOUT` loses the response.** I propose: the simulator commits the
  effect, then raises, so the caller sees an invoke error. That is deterministic and needs no
  sleeps. The alternative — an actual timeout — is slow and flaky in CI. P4 should confirm it
  matches how a real Lambda invoke failure surfaces, because the whole demo hinges on this path
  behaving like the real thing.
- **D-2 — Who opens the case?** Checkout on window elapse, or P4's reconciliation workflow?
  I propose **checkout opens the case record** (it owns the attempt and knows when the window
  ended) and WP-10 enriches it with guidance and a draft. Needs P4's agreement — it is the exact
  WP-09/WP-10 seam.
- **D-3 — Where does the callback sender live?** Inside the simulator, so it behaves like a third
  party calling us. Confirming with P4 that the simulator may hold the HMAC secret.
- **D-4 — Polling beyond the window.** Nothing polls after three minutes; resolution then depends
  on a callback or a manual reconcile. Confirm P1 shows an explicit "check again" affordance, so
  an unresolved purchase is never a dead end for the shopper.
- **D-5 — Refund origination.** No refund is ever initiated by ProofPath; refunds appear only as
  provider facts from a scenario. Confirming with P4 so WP-10 does not expect an initiation API.
- **D-6 — Resolved.** `PaymentKeyConflict` has been added to WP-02's error taxonomy.
- **D-7 — `expired_rejected` maps to payment `failed`.** Added on the cross-spec review pass;
  neither WP-08 nor WP-09 had defined what a post-dispatch expiry refusal means in domain terms,
  which would have left the checkout task and P4's recovery free to disagree. P4 should confirm
  the mapping, since WP-10 reads these facts.
