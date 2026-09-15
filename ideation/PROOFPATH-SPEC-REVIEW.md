# ProofPath - Spec Review

Review of `PROOFPATH-SPEC.md` v1.2 and `proofpath-panel-recommendation.md`, 14 September 2026.
No code was read or executed; this is a document review only.

Scope decisions settled by the team before this review:

- Build the spec's scope as written, with the Build It profile retained as fallback.
- Both halves of the product (agentic shopping, payment recovery) stay in.
- Live merchant connectors will be attempted, as live as possible.
- Voice stays exactly as specified in the spec (Transcribe input and Polly output).
- Pre-event work is limited to documents and decisions.
- Region and Bedrock model selection deferred to later today.
- OpenSearch, EventBridge and SQS all stay (see 2.6).

Findings below are written against that settled scope. Items marked **Blocking** are ones that
can cause a failed or unimpressive submission; **Gap** items are things the spec omits and will
have to be invented under time pressure if not decided now.

---

## 1. Document contradictions

The panel recommendation and the spec disagree on five points, and the spec does not record why
it departed. Whoever reads these documents next will not know which is authoritative. Either
reconcile them or mark the panel document superseded in full.

| Topic | Panel recommendation (13 Sep) | Spec v1.2 (14 Sep) |
| --- | --- | --- |
| Merchants | "Search two fixture merchant adapters"; "Defer crawling" | F05 live connectors for Blinkit, Zepto, BigBasket; two working live connectors is a delivery gate |
| Event plumbing | "This avoids requiring EventBridge or SQS for the prototype" | EventBridge, two SQS queues, two DLQ paths, DynamoDB Streams, transactional outbox, outbox publisher |
| Search index | "No OpenSearch is required for a handful of guidance documents" | OpenSearch with `offers-v1` and `guidance-v1`, plus a projection queue and indexer Lambda |
| UI surface count | "Keep the interface to four surfaces" | Six routes, including a `/demo` operator console |
| Container hosting | "Add AgentCore Runtime only if hosting needs justify it after the required flow works" | App Runner + ECR on the critical path from day 1 |

The spec is the declared source of truth, so the practical action is one line in the panel
document marking it superseded, plus a short note in the spec saying the service additions were
deliberate.

## 2. Risk register

Ordered by expected damage, not probability alone.

### 2.1 Live merchant connectors (Blocking)

`§1 Delivery gate` makes two working live connectors a release gate, and `§1` forbids silently
mixing fixtures into live results. Both rules are correct. Together they create an unhedged
dependency on third-party bot defenses staying friendly during a four-day window.

Specific hazards:

- Blinkit, Zepto and BigBasket are authenticated or location-gated SPAs. Setting a delivery
  location commonly requires a pincode flow, and on some surfaces a phone number. The spec has
  no design for how a connector establishes location without an account.
- Playwright Chromium from an App Runner datacenter IP is a well-known signature. Cloudflare or
  Akamai interstitials are a realistic steady state, not an edge case.
- `§7` explicitly forbids CAPTCHA bypass, which is the right call and also means a block is
  terminal for that connector.
- Scraping these sites is against their terms of service. This does not block a hackathon
  submission but should be acknowledged once in the README rather than discovered by a judge.

What the spec is missing is the demo-night protocol: if both connectors are blocked at the hour
the video is recorded, what exactly appears on screen. `§1` mentions "disclosed fallback
demonstrations" in one clause and never designs them. See open question Q9.

### 2.2 Search latency does not fit the stated budget (Blocking)

`§13` sets: at most 10 items per search, 3 concurrent merchant sessions, 45 seconds per merchant
fetch, partial results shown by 90 seconds.

10 items across 3 merchants is 30 search-page navigations, each a real SPA load with its own
network waterfall. At an optimistic 3-5 seconds per navigation and 3 concurrent contexts, the
floor is roughly 30-50 seconds with zero retries, and the realistic figure with retries, consent
banners and location re-prompts is several minutes. The 90-second partial-results target is
likely unreachable at 10 items, and a multi-minute wait is unwatchable on video.

This also breaks the timeout budget elsewhere in the same section: an agent request has a
90-second deadline and the Lambda proxy worker 100 seconds, so a whole merchant's 10-item sweep
cannot complete inside one worker call. `§9`'s Search workflow describes "parallel
MerchantSearch", which implies fan-out per merchant. It needs fan-out per merchant *and* per
item, with progress persisted between calls, or the workflow will hit the worker timeout before
the merchant timeout.

Concrete fix: demo path uses 3-4 items, fan out as a Step Functions Map over (merchant, item)
pairs, and treat 10 items as a documented ceiling that the demo does not exercise.

### 2.3 The Build It parity profile is a second system (Blocking on schedule)

`§12` requires, in addition to the cloud build: a local speech-to-text adapter with a downloaded
model, a local text-to-speech adapter with an installed voice, a local OpenSearch container, an
image-and-tool-capable Ollama model for photo extraction, SQLite transactional storage, and a
persisted SQLite job runner implementing stage, attempt, next-run time and lease semantics that
resume after restart. That last item is a hand-written re-implementation of the durable parts of
Step Functions.

`§12` also says the same domain and provider contract tests must pass against both profiles, and
`§14` scenario 14 makes that an acceptance criterion.

Retaining this as a genuine fallback is defensible. Retaining it as a *tested, asserted* fallback
is a second full delivery inside four days. The cheap middle path: define every port from day 1
as `§12` says, keep the local adapters unimplemented, and drop acceptance scenario 14 to
"domain tests are adapter-agnostic" rather than "both profiles pass". See Q11.

### 2.4 Voice cost concentration (Schedule)

Kept as specified, per the team's decision. Recording the realistic cost so it is planned rather
than discovered:

- Browser capture as mono 16 kHz signed 16-bit little-endian PCM via AudioWorklet, correctly
  framed for the Transcribe event stream. `§13` is right that a MediaRecorder WebM blob will not
  work, and this is the single most common failure in this integration.
- Server-side SigV4 presigning of the Transcribe streaming websocket with minimal permissions
  and short validity.
- Partial and final result assembly keyed by result ID so text replaces rather than appends.
- Polly synthesis of persisted assistant turns, private S3, short-lived playback URLs, autoplay
  fallback to an explicit Play button, mute, replay and caption parity.
- Pause recognition during playback, resume only inside an authorized listening session.
- Then all of the above again for the local profile if 2.3 is kept.

This is the largest single feature in the spec by integration surface and it sits upstream of
everything else in the demo. It should be day-1 work with a hard abandon-to-typed-input decision
point, not day-2.

### 2.5 The AWS-integral argument is diluted (Judging)

Judging criterion 2 rewards AWS being load-bearing. The spec's strongest answers are genuinely
strong: Step Functions Standard carrying a checkout across a lost provider response, DynamoDB
conditional writes and transactions enforcing single-attempt semantics, Cedar deciding approval
and export outside the model, Transcribe doing work no local library does as well.

The weak answers are in the same list and drag the average down. `§6` states that OpenSearch
index failures do not block checkout or evidence persistence and that exact values are reloaded
from DynamoDB, which is a correct design and also an admission that removing OpenSearch changes
no product behavior. `offers-v1` is a per-user, per-search index of data that the critical path
reads from DynamoDB anyway. EventBridge plus two SQS queues plus Streams is a full outbox for a
system with one producer and two consumers.

If these stay, the README should justify each one in a sentence that survives the
"what breaks if removed" test, or state plainly that they are demonstrating durable event
plumbing as a learning goal under criterion 3. An unjustified service list reads as padding.

### 2.6 The event chain (Schedule) - DECIDED: keep all three

**Decision, 14 September: OpenSearch, EventBridge and SQS all stay, as the spec specifies.**
The analysis below is retained as the rationale record and as the list of costs now accepted.
Consequences to plan for:

- Owner 4 in `§14` is the bottleneck and now carries the indexer, projection queue and domain on
  top of Transcribe, Polly, SAM, App Runner, Amplify, guidance, export, local profiles and CI.
  Rebalance that table or the schedule will absorb it silently.
- Provision the OpenSearch domain in its own CloudFormation stack or an early separate deploy, so
  a bad domain config cannot roll back the application stack on day 1.
- `§4` currently excludes PartyRock, Firecracker and Corretto on the grounds that they "supply no
  missing product behavior", while `§6` states OpenSearch cannot change any outcome. The README
  needs a different, explicit justification for OpenSearch: rebuildable projection plus keyword
  guidance retrieval, kept deliberately off the correctness path.
- Build the DynamoDB-backed guidance path anyway. `§6` already requires a "curated guidance
  fallback" when the index is unavailable, and acceptance scenario 12 tests it.
- Add teardown of the domain to a named owner, not just to the `cleanup cloud` script.

---

Original analysis:

`§9`'s dispatch chain is five hops: DynamoDB transaction writing domain change plus Job plus
OutboxEvent, then Streams, publisher Lambda, EventBridge, SQS job queue, starter Lambda, Step
Functions. Applying the team's own "what breaks if removed" bar per hop:

| Piece | What breaks if removed | Verdict |
| --- | --- | --- |
| DynamoDB transaction + outbox row | API could commit the purchase and never start the job. A stated invariant fails. | Load-bearing |
| Streams + publisher Lambda | Same; something must read the outbox. | Load-bearing |
| EventBridge | Nothing. The publisher can call SQS or `StartExecution` directly. | Removable |
| SQS job queue + DLQ | Buffering and the DLQ replay path in acceptance scenario 12. | Judgement |
| SQS projection queue + indexer | Exists only to feed OpenSearch. | Dies with OpenSearch |
| OpenSearch | Nothing; `§6` guarantees index failures cannot change an outcome. | Removable |

These are not independent toggles. EventBridge earns its place by routing to two consumers. Cut
OpenSearch and the projection queue goes with it, leaving a bus with one publisher and one
subscriber. So the real menu is two options:

- **A**: keep all three. Five hops, two queues, two DLQs, an indexer, index mappings, owner-filter
  injection, stale-result expiry, and acceptance scenario 12's index-outage test.
- **B**: cut OpenSearch, the projection queue, the indexer and EventBridge. Streams to publisher
  Lambda to SQS job queue to starter to Step Functions. Guidance moves to a `GUIDANCE#` partition,
  which is the right shape for a dozen curated rules filtered by category and merchant scope.

B keeps the DLQ replay footage, which is the only part of this chain worth filming. What A buys
over B is the OpenSearch and EventBridge hops, and neither appears on screen.

### 2.7 Standing cost (Operational)

Nearly everything in the stack scales to zero. Two things do not:

- **Managed OpenSearch**: the smallest single-node domain bills continuously. Over the event
  window itself this is a few dollars and is not an argument against it; the real exposure is
  the domain nobody remembers to delete after judging. The cost that matters for OpenSearch is
  build time, not dollars - see 2.6.
- **App Runner**: bills for provisioned container instances even when idle, and the Playwright
  Chromium image will not be small.

`§13` says to set budget alerts and correctly notes alerts are not a hard cap. What it does not
state is the expected idle burn per day or who owns teardown. `cleanup cloud` exists in `§12`'s
script list; nobody in `§14` owns running it.

---

## 3. Specification gaps

These are concrete holes that will have to be filled during implementation. Each one is cheap to
decide now and expensive to decide at 3 AM on day 3.

### 3.1 Callback cannot find its purchase

`§9` says provider callbacks resolve purchase IDs through a trusted provider-key mapping rather
than caller-supplied ownership. Correct. But `§6`'s physical layout has no such mapping. The
`ID#opaque_id` LOOKUP partition covers "repair, case and export IDs" only, and `InboxEvent` is
stored under `PURCHASE#id`, which is the partition you cannot address until the lookup has
already succeeded.

**Needs**: a `PROVIDER#provider_key` item resolving to the purchase and attempt, written inside
the same transaction that creates the attempt.

### 3.2 Provider key uniqueness is asserted but not enforced

`§9` requires a submitted provider key to be stable across transport retries, worker crashes and
workflow recovery, and `§7` says `submit` uses a conditional unique provider key on the simulator
side. There is no uniqueness constraint on the application side: nothing in `§6` prevents two
`PaymentAttempt` records carrying the same `provider_key`, and `PaymentAttempt` lives under
`PURCHASE#id` with `ATTEMPT#id` as sort key, so the key is not in any unique position.

The item in 3.1 solves both problems if it is written with a condition expression asserting the
key does not already exist.

### 3.3 `PaymentProvider.submit` signature is missing fields the callback validates

`§7` declares `submit(provider_key, quote_hash, total_paise)`. `§9` requires callbacks to match
provider key, seller, amount **and currency**. Currency and seller never reach the provider on
submit, so there is nothing authoritative to match against. Add them to the signature or state
that they are derived from the quote hash preimage.

### 3.4 No guidance corpus owner or deadline

The recovery case's value rests on `guidance/` containing reviewed, versioned, source-linked
rules with applicability conditions and checked dates. The panel document does the hard research
honestly, including flagging that the Ombudsman deadline source was challenge-blocked and must
not be shipped from memory. `§9` correctly requires requesting facts rather than fabricating
deadlines.

But nothing in `§14`'s day plan or ownership table allocates time to curating that corpus, and it
is on the critical path for the single most differentiated screen in the product. Without it,
`/cases/:id` shows an empty "next action".

### 3.5 Nobody owns the demo video, and the spec never budgets its 180 seconds

The panel document assigns the recording to owner 1. `§14`'s ownership table drops it entirely,
and the day plan mentions "demo" only inside day 4 alongside freeze, tests and submission. The
video is what judges actually see (criterion 5). Day 4 is where hackathon videos die.

There is also no timeline. The video appears twice in the spec: "Day 4: freeze, tests, demo and
submission", and the Done criteria's "a three-minute video showing spoken request → live
comparison/basket repair → approval → lost payment response → recovery case". That is five beats
with no seconds attached.

The only timed storyboard in the project is `proofpath-panel-recommendation.md` lines 206-215,
and it predates voice: it opens with a typed request and never mentions a microphone, photo
import or the usual basket. So the two documents describe two different videos and neither is
costed. Costing the spec's five beats at a realistic pace gives roughly: spoken request 15s,
live comparison 25s, basket repair 25s, approval 15s, lost payment with refresh and retry 35s,
recovery case with export 35s. That is 150s, leaving nothing for the problem setup the panel
spent 20s on, nothing for the Step Functions / Cedar / replay proof the panel spent 25s on, and
no slack for anything running slowly on the take.

A timed storyboard belongs in `§14` before day 1, because it is the thing that decides which
features actually need to be finished.

### 3.6 Tests are scheduled after the freeze

`§14` lists 16 mandatory acceptance scenarios, several of which require crash-injection
harnesses, concurrent-submit harnesses and replay tooling. The day plan puts "tests" on day 4,
alongside freeze, demo and submission. Either the invariant tests move to day 2-3 alongside the
transaction core that they validate, or the list shrinks.

### 3.7 No seeded demo identity

Judges and teammates need to open the deployed URL. `§11` forbids committing secrets, correctly.
There is no plan for a seeded demo account, or for whether the video shows a Cognito hosted-UI
login at all. A login screen inside a 180-second video is 8-10 seconds of nothing.

### 3.8 Branch protection versus four-day throughput

`§11` requires branch protection with passing checks and one teammate review on every PR. With
four people integrating daily, this is a real throughput tax and a real 2 AM blocker when the one
teammate who can approve is asleep. This is a judgement call, not an error, but it should be a
conscious one: consider requiring review on `services/domain` and `policies` only.

### 3.9 Outside-payment intake is excluded, which caps real-world usefulness

`§1` excludes outside-payment receipt intake, which removes the panel document's "first stretch"
(paste a UPI SMS or enter a receipt manually into the same recovery-case model). That is a
defensible hackathon cut. It is worth knowing what it costs: without it, ProofPath can only help
with purchases made through ProofPath, which for a judge weighing Idea and Impact is the obvious
"so what does this do for me today" question. One sentence in the README framing it as the
designed next step defuses this.

### 3.10 Overloaded terminology - DECIDED: keep the names, document the ambiguity

**Decision, 14 September: no renames. The collisions are recorded here so that four people
collide consistently.** Neither document has a glossary, and the project fuses a shopping domain
with a payments domain, so several words carry two meanings drawn from the two halves.

#### `Intent`

| | |
| --- | --- |
| Meaning in this project | The shopping request: items, quantity, budget, location, delivery constraint, revision. `§6` `Intent`, `§5` module `intents`, `§8` `POST /intents`. |
| Conflicting meaning | In payments generally, an intent is the object representing a charge (Stripe PaymentIntent, and similar). That role here is played by `PaymentAttempt`. |
| Where it bites | "Create the intent" and "the intent was approved" are ambiguous between *the shopping list was confirmed* and *the payment was authorized* - the exact distinction the product exists to preserve. |
| Blast radius | `intent_revision` appears on `MerchantObservation`, `BasketCandidate`, `RepairProposal`, `PendingQuestion`, `ConversationTurn`; `expected_intent_revision` on `VoiceSession`; `intent_id` on `Conversation` and `Purchase`. |
| Known drift | `proofpath-panel-recommendation.md` line 137 names a `PurchaseIntent` that does not exist in the spec. Treat the spec's `Intent` as canonical and the panel's `PurchaseIntent` as the same concept under an obsolete name. |
| **Convention** | `Intent` unqualified always means the shopping request. Never write "intent" about anything payment-related; say `PaymentAttempt`, `Approval` or `CheckoutQuote` by name. Never introduce `PurchaseIntent`. |

#### `reservation`

| | |
| --- | --- |
| Meaning in this project | An application-side block preventing a second payment attempt on a purchase whose outcome is unresolved. `§9` "Application reservation/claim is not a real bank hold." |
| Conflicting meaning | In banking, a reservation or hold is an actual authorization placed against a customer's funds. |
| Where it bites | The product's central honesty claim is that it never implies money moved. Both documents have to append a disclaimer every time the word appears (`§9`; panel "Recovery correctness": "A spending reservation inside this app is not a hold placed on a bank account. Releasing it is not a refund."). A word that needs a disclaimer at every use is the wrong word. |
| Blast radius | Prose only. The schema already expresses this as the `Claimed` state and `Purchase.active_attempt_id`; no field is named `reservation`. |
| **Convention** | Prefer "claim" or "attempt lock" in all new prose and in UI copy. If "reservation" is used, the disclaimer sentence is mandatory, not optional. Never use "hold", "block on funds" or "release" about it in user-facing text. |

#### `quote`

| | |
| --- | --- |
| Surface forms | `CheckoutQuote` (`§6` entity), "simulation quote" (`§2` step 5, `§7`), `QuoteVersion` (panel, transaction core contract), `QUOTE#version` (`§6` sort key), `quote_hash` / `quote_version` / `quote_id` (`Approval`). |
| The reality | There is one entity. `CheckoutQuote` already carries `simulation=true`, so "simulation quote" is not a distinct type; `QuoteVersion` is the panel's name for the same record's `version` field. |
| Where it bites | Someone will look for a `SimulationQuote` type or a separate `QuoteVersion` table and not find one. |
| **Convention** | `CheckoutQuote` is the entity. `version` is its only qualifier. "Simulation quote" is acceptable in user-facing prose and the demo script, never in code, schema or API naming. `QuoteVersion` is retired. |

#### `authorize` / `authorization`

| | |
| --- | --- |
| Meaning A - consent | The shopper agreeing to exact terms. `§9` `AuthorizeStoredTerms`; `§1` F09 "require explicit authenticated approval"; `§9` "Approval endpoint loads trusted quote/owner". |
| Meaning B - policy | Cedar and Verified Permissions deciding whether a principal may perform an action. `§4`, `§13` "tool wrappers reauthorize record access", `§8` "unauthorized resource → 404". |
| Meaning C - AWS access | Signed URLs and IAM: `§6` "5-minute authorized download URLs", `§8` "authorized status". |
| Where it bites | Three meanings inside one workflow definition. A ticket saying "authorization failed on checkout" could be a Cedar denial, an expired approval, or an expired presigned URL - three different bugs owned by three different people. |
| **Convention** | Use `approve` / `approval` for shopper consent, exclusively. Use `authorize` / `authorization` for Cedar decisions, exclusively. For meaning C say "signed URL" or "presigned", never "authorized". `§9`'s state name `AuthorizeStoredTerms` is grandfathered but means *revalidate the stored approval*, not *run a Cedar check*. |

#### Terms that are already unambiguous

Recorded so nobody "fixes" them: `observation` (a retrieved merchant fact, always source-linked
and timestamped), `attempt` (always `PaymentAttempt`), `revision` (always the shopping request's
monotonic counter), `version` (always an entity's optimistic-concurrency counter - note this is
deliberately *not* the same thing as revision), `simulated` versus `live` (the real/simulated
boundary, never softened).

### 3.11 Disclosed-fixture fallback is one clause, not a design - DECIDED: use it, but specify it

**Decision, 14 September: the demo-night fallback is the spec's own disclosed-fixture rule.**
That rule is a single clause in `§1`: "Test fixtures are for regression tests and disclosed
fallback demonstrations, never silently mixed into live results." The protocol is therefore:
attempt live, and if a connector is blocked, present fixture results with a visible disclosure.

Three things must be specified before that clause is usable, and none exist in `§3`'s route
table today:

1. **Disclosure treatment.** Exact banner copy, placement, and persistence across the comparison,
   basket and approval screens. It must be as prominent as the existing "Simulated checkout · no
   money moved · no retailer order placed" strip, and visually distinct from it, because they are
   two different admissions and may appear on screen together.
2. **Mixing rule.** `§1` forbids silently mixing fixtures into live results but does not say
   whether a *disclosed* fixture merchant may sit in the same ranked list as a live one. Since
   `§7` ranks baskets by total, a fixture price competing against a live price produces a
   meaningless ranking. Recommended: fixtures replace the entire result set rather than partially
   populating it, and the comparison switches to a clearly labeled demonstration mode.
3. **The real error stays on screen.** The connector's actual failure - block, timeout, CAPTCHA
   interstitial - and its timestamp appear next to the disclosure, reusing the existing
   `extraction_status` values (`blocked`, `timeout`, `unsupported`). That turns the disclosure
   into evidence rather than an apology, which is consistent with the rest of the product.

Residual risk accepted: the take you record is whatever the merchant sites are doing at that
hour, so the video shoot carries an external dependency that cannot be scheduled.

---

## 4. What is already strong

Stated so that revisions do not accidentally weaken it.

- **`§9` transaction invariants.** Approval consumed atomically with attempt, job and outbox
  creation; cancel competing on the same version; unknown payment never releasing the purchase
  for a new attempt; stable provider key across crashes; explicit acknowledgement that Standard
  workflow semantics do not guarantee exactly-once external charging. This is better than a great
  deal of production payment code and it is the heart of the submission.
- **Separation of payment, order and refund status** into independent fields rather than one
  status enum. This is the single design decision that makes the recovery case coherent.
- **The simulator as an independent service with its own ledger** and countable effects, unable
  to be driven from the shopper UI. This is the right answer to the panel's strongest objection.
- **Honesty discipline throughout**: unknown fees are never zero, pending is never shown as
  resolved, estimated totals are never ranked as definitively cheaper, model output can never
  authorize payment, hashes are described as application binding rather than AP2 signatures or
  bank mandates, and simulated refunds are never described as recovered money. Protect this. It
  is also the thing that will read as maturity to a judge.
- **`§13` prompt-injection posture**: merchant text treated as untrusted, no credentials in
  prompts, tool wrappers reauthorizing record access, plus the panel's test of a merchant
  description containing an instruction to bypass approval. Keep that test; it demos in 15
  seconds and it lands.

---

## 5. Open decisions

Carried into the next grilling round rather than resolved here.

| # | Decision |
| --- | --- |
| ~~Q7~~ | ~~Keep or cut OpenSearch, EventBridge and SQS~~ - **decided: keep all three, see 2.6** |
| Q8 | 180-second video budget when both product halves stay in |
| ~~Q9~~ | ~~Demo-night protocol if live connectors are blocked~~ - **decided: the spec's disclosed-fixture fallback, see 3.11** |
| Q10 | Demo-path search size, and Map-state granularity for the Search workflow |
| Q11 | What event, by what hour, triggers the Build It fallback |
| ~~Q12~~ | ~~Terminology collisions~~ - **decided: keep names, document ambiguity, see 3.10** |
