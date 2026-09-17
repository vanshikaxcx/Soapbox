# ProofPath — Three-Day Implementation Plan of Action

Status: execution plan derived from [`docs/PROOFPATH-SPEC.md`](../docs/PROOFPATH-SPEC.md)
Audience: four-person hackathon engineering team  
Primary target: **Ship It**  
Development window: **three implementation days**, followed by an optional protected submission/fix day if the event schedule permits

---

## 1. Purpose and operating model

This document turns the product specification into small, reviewable work packages. Every package follows the same controlled path:

1. Write the package specification.
2. Review and approve the specification.
3. Implement only the approved scope.
4. Run the package's automated and manual tests.
5. Open a pull request and review the implementation.
6. Merge only after its exit gate passes.

The team must not start a dependent package merely because code exists. A dependency is usable only after its contract or implementation has passed the stated gate. Time pressure can reduce visual polish, but it must not remove transaction invariants, honesty labels, authorization, failure states, or tests of irreversible effects.

The product is complete when the single end-to-end journey works in the deployed environment: voice/text/photo/usual basket → two-source live comparison → deterministic repair → recheck → exact simulated approval → durable checkout ambiguity → recovery → reviewed export.

### Non-negotiable scope

- Maximum four distinct grocery items, two live merchants, and one tested locality.
- Live data is used only for discovery, comparison, alternatives, and recheck.
- Checkout, payment, order, callbacks, and refunds are independently simulated and visibly labelled.
- Fixture and live results are never combined or ranked together.
- Only the dedicated exact-price touch action authorizes simulated checkout.
- Payment, order, and refund states remain separate.
- An unresolved payment exposure blocks a replacement attempt.
- Recovery queries existing facts and never creates a payment, order, refund, or complaint.
- No additional feature begins until the core journey passes its acceptance gate.

---

## 2. Team structure and ownership

Replace P1–P4 with the four team members' names before development starts.

| Person | Role | Owns | Does not own |
| --- | --- | --- | --- |
| **P1 — Experience and voice** | Frontend lead | React application shell, shared cards, polling client, conversation UX, mic/transcript, Polly playback, photo/usual-basket UI, responsive/accessibility behavior, demo storyboard | Domain rules, provider state transitions, merchant scraping, cloud orchestration |
| **P2 — Shopping intelligence** | Agent and merchant lead | Agent container, schema-bound extraction, image-list extraction, merchant registry/connectors, normalization, basket evaluation, repair proposals, merchant evidence | Approval authorization, payment/order mutations, web auth, infrastructure deployment |
| **P3 — Transaction safety** | Transaction-core lead | Canonical commerce schemas, preparation/quote/approval, simulator ledger, checkout idempotency, provider keys, transaction invariants and provider-fact contracts | Merchant access, deployment pipeline, generic UI framework, recovery presentation |
| **P4 — Platform, durability and recovery** | Cloud/recovery lead and release captain | Repository/build conventions, OpenAPI pipeline, AWS stacks, Cognito/Cedar integration, DynamoDB/S3 adapters, job/outbox pipeline, Step Functions, callback ingestion, reconciliation workflow, case/guidance/export backend, CI/CD, logging, cloud verification and teardown | Merchant and transaction-domain decisions owned by P2/P3, page-level UX owned by P1 |

### Decision authority

- Product scope or architecture change: all four discuss; user approves any change to a settled decision.
- API/schema change: owning producer and every affected consumer approve; P4 confirms generated contracts and deployment effect.
- Payment/order/refund invariant change: P3 approval is mandatory.
- Live merchant evidence or matching-rule change: P2 approval is mandatory.
- Shared component/interaction change: P1 approval is mandatory.
- Infrastructure, IAM, deployment, or environment change: P4 approval is mandatory.
- Recovery may interpret only the provider-fact and transition contracts approved by P3; P4 owns its workflow, storage, authorization and export implementation.
- Merge decision: package owner plus assigned reviewer; release captain can stop a merge when main or the deployed environment is unhealthy.

### Independence rules

Each person works inside their owned directories and consumes other work through agreed contracts. Cross-cutting edits require advance notice in the team channel and review by the directory owner.

| Area | Default editor |
| --- | --- |
| `web/**` | P1 |
| `services/agent/**`, `services/merchants/**` | P2 |
| `services/domain/**` commerce state, `services/simulator/**` | P3 |
| `infra/**`, `policies/**`, `.github/**`, job transport/adapters, recovery/export handlers | P4 |
| `contracts/openapi.yaml` | Package owner proposes; affected owners and P4 approve |
| `services/application/**` | Use-case owner; ports are reviewed by adapter owner |
| `tests/e2e/**` | P1 owns scenarios; relevant backend owner supplies fixtures/assertions |
| `docs/specs/**` | Work-package owner |

Do not solve ownership conflicts by having two people edit the same file simultaneously. Split along a port/interface, agree the contract, and implement on opposite sides.

---

## 3. Git, branch, pull-request, and merge policy

### Branch model

Use protected `main` plus short-lived work-package branches. **Every person uses a separate branch. Two people must not work on the same branch.** Collaboration is shown by reviewed specifications, API/port agreements, pull-request reviews, paired test evidence, and integration commits—not by sharing a branch.

Branch format:

```text
feat/wp-<number>-<short-name>-p<owner>
fix/wp-<number>-<short-name>-p<owner>
docs/wp-<number>-spec-p<owner>
```

Examples:

```text
docs/wp-04-live-merchants-spec-p2
feat/wp-04-live-merchants-p2
fix/wp-09-callback-dedup-p3
```

For speed, the approved specification may remain on the implementation branch if review latency makes a separate docs PR impractical. It must still receive an explicit specification review before implementation commits begin. Never create long-lived `frontend`, `backend`, `dev`, or per-person branches.

### Required workflow for every work package

1. Create the branch from the latest green `main`.
2. Add `docs/specs/WP-XX-name.md` using the template in section 4.
3. Open a draft PR labelled `spec-review`.
4. Assigned reviewer resolves ambiguities and records `SPEC APPROVED` in the PR.
5. Rebase or merge the latest `main` into the branch immediately before implementation.
6. Implement in small commits with tests beside behavior.
7. Mark the PR ready only when its local checks and evidence checklist pass.
8. Assigned reviewer performs code, test, security, and scope review.
9. Package owner addresses findings; reviewer records `IMPLEMENTATION APPROVED`.
10. Squash-merge to `main`. Delete the branch after merge.
11. CI runs on `main`; P4 deploys only from green `main` using the serialized deploy workflow.
12. If the cloud smoke test fails, stop dependent merges or revert the isolated package through a normal PR. Never patch the deployed environment manually.

### Merge order and frequency

- Merge contract/scaffold packages first.
- Merge independent vertical packages whenever their exit gates pass; do not wait for an end-of-day mega-merge.
- Target integration windows at approximately hour 3, hour 6, end of day 1, midday/end of day 2, and midday/feature-freeze on day 3.
- Only one deployment runs at a time. P4 is release captain and records commit SHA, stack version, container tag, smoke result, and rollback target.
- `main` must remain buildable. A red `main` blocks feature merges until repaired.

### Pull-request minimums

Every PR must contain:

- linked work-package specification;
- scope summary and explicit out-of-scope statement;
- API/schema/migration implications;
- tests added and exact commands run;
- screenshots or trace IDs for user-visible/cloud behavior;
- security, privacy, cost, and failure-mode notes where applicable;
- rollback or disable path;
- confirmation that no credentials, recordings, exports, or personal data were committed.

Approval matrix:

| PR owner | Primary reviewer | Required specialist reviewer when relevant |
| --- | --- | --- |
| P1 | P3 | P4 for auth/upload/presigned URL changes; P2 for agent-facing UX contracts |
| P2 | P1 | P3 for persisted commerce fields; P4 for container/cloud networking |
| P3 | P4 | P1 for approval/recovery UX; P2 for basket/quote inputs |
| P4 | P2 | P3 for transaction persistence; P1 for generated client/auth behavior |

Self-merge is forbidden. One approval is enough for an isolated change; two are required for OpenAPI breaking changes, Cedar/IAM changes, and approval/payment/order/refund state changes.

---

## 4. Specification-first quality gates

Each work package gets one concise but complete file: `docs/specs/WP-XX-name.md`. Do not produce separate technical, design, and testing documents unless a package is unusually large; use one document with the sections below so review remains achievable in three days.

### Work-package specification template

```markdown
# WP-XX — Name

Owner:
Reviewers:
Status: Draft | Approved | Implemented | Verified
Depends on:

## Outcome and user value
## In scope
## Out of scope
## User flow and UI states
## API and event contracts
## Data model and state transitions
## Components, ports, and dependency direction
## Security, privacy, and authorization
## Idempotency, concurrency, timeout, and retry behavior
## Failure modes and user-visible errors
## Observability and cost limits
## Test plan
### Unit
### Contract
### Integration
### End-to-end/manual
## Acceptance criteria
## Rollout, rollback, and fixture strategy
## Open questions and decisions
```

### Gate A — specification approved

A package may enter implementation only when:

- inputs, outputs, state ownership, and error behavior are explicit;
- UI includes loading, empty, partial, success, error, expired, and stale states where relevant;
- authorization and owner/operator boundaries are stated;
- retries and duplicate requests have defined results;
- test cases map to acceptance criteria;
- affected owners agree on the contract;
- no open question can materially change implementation.

### Gate B — implementation complete

Implementation is complete only when:

- approved behavior exists without unrelated features;
- unit and contract tests pass;
- relevant integration tests pass with deterministic adapters;
- formatter, linter, type checker, dependency lock, and security checks pass;
- logs use request/job/aggregate correlation IDs and contain no sensitive content;
- documentation and generated types match the implementation.

### Gate C — implementation reviewed and merged

Merge only when:

- reviewer traces acceptance criteria to code and tests;
- negative paths, stale versions, and duplicate actions were examined;
- cloud-impacting behavior has either cloud evidence or an explicitly scheduled cloud gate;
- no critical/high review finding remains;
- branch is current with green `main` and all required checks pass.

### Gate D — integrated/deployed acceptance

A user-facing capability counts as done only after it works against the actual shared backend in the deployed environment, or is explicitly labelled as locally complete pending a named cloud gate. Screenshots alone do not prove merchant liveness, idempotency, authorization, or durable recovery; retain source timestamps, effect counts, logs, and trace IDs.

---

## 5. Engineering and coding standards

### Architecture and dependency direction

- Use the flow `handler → application use case → domain → port → adapter`.
- Domain code is pure and imports no AWS SDK, browser library, FastAPI, Lambda event, database representation, or UI type.
- Infrastructure and merchant/provider details implement typed ports; application code does not branch on concrete adapters.
- Agents may propose typed actions. Deterministic application/domain services validate and commit them.
- Keep one canonical data flow. Do not duplicate state in the UI, OpenSearch, Step Functions input, and DynamoDB as competing authorities. DynamoDB is canonical; UI and indexes are projections.
- Modules communicate in process through typed functions/ports, not unnecessary internal HTTP services.

### Functions and modules

- A function performs one observable responsibility and has a name describing that responsibility.
- Prefer small composable functions, but do not split coherent logic merely to satisfy a line count.
- Separate validation, authorization, domain decision, persistence, and presentation.
- Make dependencies explicit through parameters or constructors; avoid hidden globals and service locators.
- Keep side effects at boundaries. Pure calculations cover normalization, totals, hashes, matching, state transitions, and redaction selection.
- Return typed domain results/errors; do not use generic exceptions for expected conflicts, expiry, or unavailable merchants.
- Avoid boolean arguments that change a function into two behaviors; use named commands or strategies.
- No copy-pasted transition rules in handlers and simulator. Give each rule one authoritative implementation.

### Data and contracts

- Python 3.12 with strict Pydantic models; TypeScript in strict mode.
- OpenAPI is the browser/API contract source; generate TypeScript client types rather than duplicating interfaces by hand.
- Use opaque IDs, UTC timestamps, INR integer paise, canonical JSON, and SHA-256 quote hashes.
- Never use floating point for money.
- Every mutation accepts an idempotency key and expected version/revision as specified.
- Same idempotency key plus different payload is `409`; stale versions are `409`; invalid input is `422`; expired resources are `410`; inaccessible resources appear as `404`.
- Validate at trust boundaries, then operate on typed objects internally.
- Schema changes must be backward-compatible during a deployment. Add before use; remove only after all consumers stop using a field.

### State and concurrency

- Encode permitted transitions explicitly and reject illegal transitions.
- Perform authorization reads and conditional/transactional writes against canonical records.
- Persist a dispatch-started marker before a provider network call.
- Reuse provider/payment/order keys across retry, timeout, and crash.
- Treat SQS, EventBridge, callbacks, and workflow tasks as at-least-once delivery.
- Deduplicate by stable business/event identity; a retry must not create a second effect.
- Never interpret a failed workflow as a failed payment.

### Frontend

- Reuse basket, quote, progress, error, recovery, and evidence cards across routes.
- Server state comes from the typed API client and polling controller; avoid copying it into multiple local stores.
- Keep temporary form/draft state local and reconcile it explicitly with server versions.
- Every async surface implements loading, partial, empty, retryable error, terminal error, expired, and stale-conflict behavior as applicable.
- Use semantic HTML, keyboard access, visible focus, captions, text alternatives, mobile layout, and sufficient contrast.
- Spoken summaries are concise; exact terms and all consent remain visible.
- The approval endpoint is called only by the dedicated `Approve simulated ₹X` touch control.

### Agent, browser, and external content

- All model outputs are schema constrained, parsed, validated, and bounded to six model turns per job.
- Treat merchant pages, uploaded images, and retrieved text as untrusted data, never instructions.
- Allowlist merchant domains and validate redirect destinations; block private/local addresses.
- Do not bypass CAPTCHA, use shopper credentials, or attempt checkout on merchant sites.
- Run each browser task in an isolated context and close it in `finally`.
- Record verified locality, fetch time, merchant/SKU URL, extraction status, and evidence reference.
- Enforce 45 seconds per item fetch, concurrency two, two repair rounds, and 90-second agent deadline.

### Security and privacy

- Server derives owner identity from the validated access token; never trusts owner IDs supplied by the browser/model.
- Apply Cedar/owner checks before issuing record access or presigned URLs.
- Operator faults are inaccessible to shopper roles.
- No secrets, tokens, cookies, OTPs, PINs, raw audio, or sensitive export contents in logs/prompts/source control.
- Validate image type, size, dimensions, decoded bytes, metadata stripping, and model-safe resize.
- Exports use an allowlist, not a blacklist, for fields.
- Use least-privilege IAM and repository/branch-scoped GitHub OIDC; never store long-lived AWS keys.

### Testing and review discipline

- Write unit tests with domain code and contract tests with every adapter.
- A bug fix begins with a failing regression test whenever reproducible.
- Deterministic model, merchant, speech, and provider adapters run in CI; real AWS and live merchant checks are separate smoke suites.
- Tests assert outcomes and external effects, not private implementation details.
- Time, IDs, randomness, model responses, and provider responses must be injectable.
- Do not use arbitrary sleeps in tests; advance fake time or poll bounded observable state.
- Mark a package complete only with negative-path evidence, not just a happy-path screenshot.

### Observability and operational limits

- Structured logs include `request_id`, `job_id`, `execution_arn`, aggregate ID/version, stage, outcome, and safe error code.
- Metrics cover job latency/failures, DLQ depth, duplicate suppression, merchant success/freshness, provider effect count, callbacks, and active cost-bearing resources.
- Never log raw callback secrets, access tokens, full prompt contents, or private exports.
- Pin dependencies and AWS region/model/Polly voice; tag container images with commit SHA.
- Record standing compute/search cost and teardown commands before feature freeze.

---

## 6. Work-package map

The sequence below is the implementation order, not a requirement that only one package run at a time. Packages in the same wave run concurrently after their dependencies pass.

| WP | Work package | Owner | Reviewer(s) | Depends on | Target merge |
| --- | --- | --- | --- | --- | --- |
| 00 | Repository, toolchain, and contract baseline | P4 | P1, P2 | None | Day 1, hour 2 |
| 01 | Six-hour cloud viability checkpoint | P4 | P2, P3 | WP-00 | Day 1, hour 6 gate |
| 02 | Core domain records and deterministic rules | P3 | P2, P4 | WP-00 contracts | Day 1, hour 6 |
| 03 | Web shell, auth, typed client, and shared states | P1 | P4 | WP-00 | Day 1, hour 6 |
| 04 | Agent container and two live merchant connectors | P2 | P1, P4 | WP-00; checkpoint access | Day 1 end |
| 05 | Conversation, voice, photo, and usual basket | P1 | P2, P4 | WP-03; extraction contract | Day 2 midday |
| 06 | Search, comparison, fees, and basket repair | P2 | P3, P1 | WP-02, WP-04 | Day 2 midday |
| 07 | Durable jobs, outbox, workflow, and projections | P4 | P3, P2 | WP-01, WP-02 | Day 2 midday |
| 08 | Preparation, exact quote, and touch approval | P3 | P1, P4 | WP-02, WP-06, WP-07 | Day 2 end |
| 09 | Independent simulator, checkout, and callback contract | P3 | P4, P2 | WP-07, WP-08 | Day 2 end |
| 10 | Callback ingestion, recovery, guidance, case, and export | P4 | P3, P1 | WP-09 | Day 3 midday |
| 11 | Integrated UI journey and operator console | P1 | P3, P2 | WP-05, WP-06, WP-08–10 | Day 3 midday |
| 12 | Security, resilience, cloud verification, and release | P4 | all | All prior packages | Day 3 freeze |

P3 owns the transaction state machine through provider facts; P4 owns the durable recovery path that consumes those facts. The boundary is a reviewed provider-fact/reconciliation contract. P1 owns all recovery UI, and P2 supplies merchant evidence, so P4's recovery responsibility remains backend-focused.

---

## 7. Detailed work packages

### WP-00 — Repository, toolchain, and contract baseline

**Owner:** P4. **Reviewers:** P1 for web conventions; P2 for Python/container conventions.  
**Goal:** everybody can build and test independently against stable types.

Specification must decide:

- exact `proofpath/` repository tree from the product specification;
- pinned Node, Python, SAM, Playwright, Docker, and package-manager versions;
- formatter/linter/type-check/test commands and dependency lock strategy;
- environment-variable naming and secret handling;
- initial OpenAPI error envelope, IDs, timestamps, money, version, idempotency, job-status, and health contracts;
- generated TypeScript process and CI drift check;
- deterministic adapter interfaces and local development boundaries.

Implementation:

- create the repository skeleton and copy the authoritative product spec to `docs/PROOFPATH-SPEC.md`;
- add root setup/command documentation, ignore rules, license if chosen, local environment example, and placeholder modules with explicit package boundaries;
- add `LEARNING.md`; every owner appends concrete technical findings, failed assumptions and decisions throughout the event rather than reconstructing them at submission time;
- configure strict TypeScript and Python checks, unit/contract test runners, OpenAPI generation, and basic CI;
- provide one API health route and one web render smoke test;
- add PR template and ownership rules.

Tests/evidence:

- clean clone setup succeeds using documented commands;
- web and Python build/type/lint/test commands are green;
- generated client has no uncommitted drift;
- secret/artifact ignore test covers `.env`, AWS SAM output, browser sessions, audio, captures, and exports.

Exit gate: all four can create independent branches and consume the same generated primitives. No feature implementation starts before this baseline merges.

### WP-01 — Six-hour cloud viability checkpoint

**Owner:** P4. **Reviewers:** P2 for Chromium/locality; P3 for durable job evidence.  
**Goal:** prove the selected Ship It architecture is deployable before most implementation effort is committed.

Specification must decide:

- AWS account/region, Bedrock model ID, Polly voice/engine, Transcribe language profile, quotas and pinned service/dependency versions;
- minimal stack boundaries and teardown order;
- authentication redirect URLs and test identities;
- smallest durable event/job used for checkpoint proof;
- Fargate browser smoke input, tested locality, allowed domain and evidence format;
- cost owner, budget alerts, log retention, and standing-resource estimate.

Implementation and proof:

- deploy minimal Amplify → Cognito → API Gateway/Lambda → DynamoDB path;
- authenticate a test user and complete one owner-scoped write/read;
- invoke the pinned Bedrock model, Transcribe access check, and Polly synthesis;
- build/push/run the FastAPI + Playwright image on ECS Express Mode/Fargate and capture one locality-specific merchant screenshot/search result;
- commit an outbox record and observe DynamoDB Streams → publisher → EventBridge → SQS → controller → Step Functions → task → terminal job state;
- provision or begin early OpenSearch provisioning and verify access or record the exact blocker;
- capture commit SHA, trace IDs, timestamps, screenshots, quotas, errors, and cost estimate in `docs/evidence/checkpoint.md`.

Checkpoint decision at implementation hour 6:

- **Pass:** all five gates work: model/speech, authenticated API/database, cloud Chromium/locality, durable job, deployable UI. Continue Ship It.
- **Conditional pass:** only OpenSearch is blocked and canonical fallback works; continue with recorded limitation.
- **Fail:** one or more core gates remain unresolved. Stop feature expansion and present evidence to the user before any Build It switch.

This checkpoint can use thin vertical code that later packages replace behind the same contracts. It must not become an alternate architecture.

### WP-02 — Core domain records and deterministic rules

**Owner:** P3. **Reviewers:** P2 for shopping rules; P4 for persistence compatibility.  
**Goal:** establish pure, tested rules used by every workflow.

Specification must cover:

- Pydantic records and enums listed in the product spec;
- canonical JSON and quote/diff/input hashing;
- unit normalization and forbidden mass/volume conversion;
- money/totals and fee completeness semantics;
- intent revision and entity version behavior;
- preparation/quote expiry;
- payment, order, refund, dispatch, approval, job, inbox, and case transitions;
- domain error taxonomy.

Implementation:

- pure models/value objects and state transition functions;
- canonical hash builder binding owner, purchase, version, seller, source, lines, charges, currency, delivery, and expiry;
- basket/fee total classification: complete, estimated, unknown;
- idempotency request hash and stable provider/order key helpers;
- no AWS imports or persistence calls.

Tests must include boundary values, incompatible units, unknown hard attributes, unknown fees, budget edge, expired quote, illegal transitions, old-pending-after-success, hash determinism, replay identity, and property/table tests for transition rules.

Exit gate: P2, P3, and P4 agree these are the sole canonical rules; adapters and handlers cannot reimplement them.

### WP-03 — Web shell, identity, typed API client, and shared async states

**Owner:** P1. **Reviewer:** P4.  
**Goal:** a mobile-first authenticated shell can render every route from typed deterministic data.

Specification must cover:

- route hierarchy and shared layouts/cards;
- Cognito authorization-code PKCE lifecycle and logout/expired-session behavior;
- typed API client, error mapping, idempotency-key generation, expected-version handling, and polling policy;
- state ownership: server state versus local draft/input state;
- mobile/desktop breakpoints, accessibility, focus/error announcements, and preserved drafts;
- generic loading/empty/partial/error/stale/expired components.

Implementation:

- routes `/`, `/searches/:id`, `/purchases/:id/approve`, `/purchases/:id`, `/cases/:id`, `/demo`;
- auth boundary, generated client wrapper, request correlation display in diagnostic mode, bounded polling at 2s then 5s, and stop-on-terminal/background behavior;
- reusable conversation, basket, quote, progress, evidence, recovery, notice, and error card primitives;
- deterministic Storybook-equivalent route fixtures or component harness without inventing a second backend.

Tests/evidence:

- keyboard-only path, visible focus, responsive viewport, session expiry, 404 concealment, 409 stale refresh, 410 expiry, network retry, polling stop, and draft preservation;
- no real endpoint is needed for component-state review, but the authenticated health call must work against the deployed API.

### WP-04 — Agent container and two live merchant connectors

**Owner:** P2. **Reviewers:** P1 for result explainability; P4 for container/cloud limits.  
**Goal:** retrieve honest, location-verified observations from two real merchants through an extensible registry.

Specification must cover:

- two selected merchants and one exact test locality;
- evidence that access works locally and on Fargate under actual event conditions;
- registry metadata: domain allowlist, location method, connector capability and failure codes;
- `search`, `refresh`, and `assess_fees` port behavior and deadlines;
- extraction schema, evidence capture, freshness, redirect/private-address restrictions, CAPTCHA/block handling;
- agent FastAPI task authentication, 90/100-second deadlines and cancellation/cleanup;
- explicit live-versus-fixture mode isolation.

Implementation:

- one FastAPI + Strands + Playwright container with health endpoint;
- allowlisted tool wrappers and model schema validation;
- independent connector modules so one merchant failure yields partial results rather than failing the search;
- isolated browser context per task, cleanup in `finally`, safe evidence in S3, and typed errors;
- deterministic connector fixtures for CI, visually labelled and never mixed with live results.

Tests/evidence:

- connector contract suite runs identically for both merchants and deterministic adapters;
- locality is applied and recorded; observations include SKU/URL/pack/unit/price/stock/time/evidence/extraction status;
- redirect and prompt-injection tests cannot access an arbitrary destination or agent control;
- CAPTCHA/access denial returns an explicit error;
- cloud trace proves two working live sources. If this fails, the two-live-merchant acceptance gate is not met.

### WP-05 — Conversation, voice, photo list, and usual basket

**Owner:** P1. **Reviewers:** P2 for extraction contract; P4 for speech/upload security.  
**Goal:** shoppers can establish a reviewed intent by speaking, typing, photographing a list, or loading their usual basket.

Specification must cover:

- conversation/turn/question state and one-active-question rule;
- one canonical editable-text submission path used by typing and final voice transcripts; voice remains the primary interaction and typing the reliable fallback;
- voice-session context binding, expiry, cancellation, transcript hash, and once-only submission;
- AudioWorklet PCM format, Transcribe event framing, partial-result assembly and mic failure;
- Polly caption/audio state and autoplay fallback;
- upload issue/verify/extract/confirm lifecycle;
- usual-basket save/update/load semantics and freshness rule;
- exact interaction copy for ambiguity, stale answer, failure, and spoken approval rejection.

Implementation split within the package:

- P1 implements mic, transcript editor, question UI, playback, photo/usual forms and page integration.
- P4 supplies presigned Transcribe/S3 and Polly adapter endpoints through reviewed ports, on P4's separate supporting branch/PR if non-trivial.
- P2 supplies schema-bound text/image extraction callable through the agent contract, on P2's own branch.
- P1 integrates only merged contracts; nobody shares P1's branch.

Tests/evidence:

- voice → transcript → reviewed turn → search;
- duplicate submit, stale question, disconnect, unsupported mic, autoplay rejection, background stop and typed fallback;
- JPEG/PNG up to 5 MB, bad MIME/decoded bytes/dimensions rejected, metadata removed, ambiguity confirmed before search;
- usual basket loads item/preferences only and triggers fresh observations;
- generic/spoken “yes” or “buy it” never invokes approval.

### WP-06 — Search, comparison, fees, and basket repair

**Owner:** P2. **Reviewers:** P3 for deterministic constraints; P1 for presentation contract.  
**Goal:** compare complete single-merchant baskets and offer only valid, explicit repairs.

Specification must cover:

- search job input/output, progress, observation, basket and repair schemas;
- maximum four items/two merchants, concurrency two, 45-second fetch and partial-result behavior;
- normalized quantities, pack combinations, overbuying, brand flexibility, hard attributes, stock and delivery constraints;
- basket-level fee assessment and complete/estimated/unknown totals;
- ranking rules that never declare estimated totals cheaper than verified totals;
- two-round repair boundary, proposal explanation, acceptance and intent revision;
- index use and canonical fallback.

Implementation:

- merchant/item task planning and partial observation persistence;
- pure matching, compatible-unit conversion, pack selection, basket assembly and ranking using WP-02 rules;
- alternatives constrained by user flexibility;
- repair proposal only; accepting a repair changes the intent revision and starts a new search;
- explicit all-live or all-fixture result-set mode and persistent honesty labels.

Tests/evidence:

- two live merchants in the tested locality; one source failure still renders partial coverage;
- incompatible units, missing hard attributes, out of stock, fee unknown, budget exceeded, permitted overbuy and forbidden substitution;
- stale repair acceptance conflicts; accepted change increments revision and old search cannot become current;
- fixture/live isolation is asserted at persistence, ranking, API and UI boundaries.

### WP-07 — Durable jobs, outbox, workflows, and projections

**Owner:** P4. **Reviewers:** P3 for restart semantics; P2 for search task shape.  
**Goal:** every async command is durably committed, restartable under defined rules, observable, and safe under duplicate delivery.

Specification must cover:

- DynamoDB single-table keys, conditional operations and transaction boundaries;
- job/outbox/event envelope and generation semantics;
- Streams filter, publisher batch failure, EventBridge routing, SQS/DLQ settings and partial-batch response;
- controller start/existing-run resolution and Step Functions Standard names;
- task retry/Catch/timeout behavior and final-status repair;
- index version ordering and canonical fallback;
- retry API versus operator replay distinction.

Implementation:

- state/job/outbox atomic repository operations;
- publisher, controller, workflow/task skeletons and job-status repair;
- generation-specific `job_id-rN` execution, duplicate start suppression, bounded retries and persisted task results;
- offer/guidance indexer that ignores older versions;
- scripts to retry jobs and replay DLQs with audit output;
- correlated logs, alarms and dashboards sufficient for the demo trace.

Tests/evidence:

- duplicate event delivery does not create a second run/effect;
- failed execution remains failed until authorized retry increments generation;
- outbox replay, individual EventBridge failure, partial SQS batch retry, DLQ replay and stale-running repair;
- index outage and older projection cannot corrupt canonical results;
- deployed job from durable commit reaches a terminal result after handler retry.

### WP-08 — Preparation, exact quote, and touch approval

**Owner:** P3. **Reviewers:** P1 for consent UI; P4 for transactions/Cedar.  
**Goal:** bind informed consent to a fresh, immutable simulated quote and create at most one logical attempt.

Specification must cover:

- preparation refresh, diff, acceptance, 120-second freshness and quote construction;
- immutable quote fields/hash/version/expiry and all honesty copy;
- approval authorization versus user consent;
- exact API commands, expected versions, idempotency and concurrent approve/cancel transaction;
- atomic creation of consumed approval, attempt, unique provider lookup, checkout job/outbox/evidence and purchase claim;
- expired-unsent behavior and repeat approval response.

Implementation:

- refresh selected lines/fees and persist preparation/diff;
- require explicit diff acceptance only when facts changed;
- construct exact simulated quote when fresh;
- render the dedicated `Approve simulated ₹X` control and disclaimer;
- approval transaction and cancel race using conditional writes/Cedar;
- prevent every conversational/model/voice path from calling approval.

Tests/evidence:

- unchanged, changed, and expired preparation; accepted fresh preparation does not loop endlessly;
- canonical quote tamper/hash mismatch, stale purchase version and expired quote;
- concurrent approve/approve and approve/cancel create one attempt or one cancellation, never both effects;
- generic yes, keyboard text, model output and replayed UI request cannot produce extra approval;
- exact seller/items/charges/total/currency/delivery/expiry and simulation label are visible.

### WP-09 — Independent simulator, checkout, and callback contract

**Owner:** P3. **Reviewers:** P4 for delivery/security; P2 for isolation from merchant agents.  
**Goal:** prove safe ambiguous-payment handling using a separate provider ledger and operator-controlled faults.

Specification must cover:

- separate simulator table and typed payment/order/refund operations;
- stable keys, request hashes, expiry, unique effects and conflict behavior;
- dispatch `ready|started|expired_unsent` state machine;
- payment polling schedule and three-minute observation window;
- scenario definitions and operator authorization;
- callback HMAC canonical input, skew, deduplication, matching and contradictory-fact behavior;
- late callback reconciliation and case opening.

Implementation:

- operator-only scenario API and effect-count endpoint;
- simulator conditional ledger writes: same key/same payload returns original facts; changed payload conflicts;
- checkout task persists `started` before submission, queries after ambiguity, and uses the same key/payload/expiry;
- creates an idempotent simulated order only after verified payment;
- define and contract-test the signed callback envelope, immutable inbox event and authoritative provider-fact query used by P4;
- checkout-side reconciliation reads original references and never makes a replacement attempt.

Tests/evidence:

- success, definitive failure, expiry before dispatch, crash after dispatch, accept-then-timeout, paid/order-missing, duplicate/conflicting callback and refund pending→complete;
- reload/retry shows the same unknown attempt and one simulator effect;
- same callback ID/different body conflicts; old pending cannot downgrade success; amount/seller/currency mismatch is quarantined;
- no new attempt while payment is pending/unknown; job failure is not displayed as payment failure;
- shopper receives `404`/deny for demo controls; operator is authorized.

### WP-10 — Callback ingestion, recovery, guidance, case, and reviewed export

**Owner:** P4. **Reviewers:** P3 for provider facts/state safety; P1 for understandable UX.
**Goal:** turn missing/late provider evidence into a grounded, editable, private support packet without taking unauthorized action.

Specification must cover:

- known/missing fact derivation from payment/order/refund evidence;
- recovery tool allowlist and explicit absence of mutation tools;
- guidance record provenance, version, reviewed date, applicability and canonical fallback;
- case status, timeline, editable draft/version and evidence linking;
- export review screen, field allowlist, redaction, HTML/JSON generation, retention and presigned download;
- unknown/contradictory/late facts and user-facing wording.

Implementation:

- implement the callback API: verify HMAC/timestamp, durably record the immutable inbox before success, deduplicate delivery and atomically apply valid facts using P3's contract;
- deterministic reconciliation before model-authored explanation;
- read-only `read_case`, `query_payment`, `query_order`, `query_refund`, and `read_guidance` wrappers;
- exactly three reviewed guidance rules with official source URLs, checked dates, applicability conditions and required facts: UPI beneficiary-not-credited, merchant-payment confirmation missing, and unresolved-provider escalation;
- grounded draft whose claims link to evidence/guidance versions;
- editable draft with optimistic concurrency;
- private redacted export job and five-minute download URL.

Tests/evidence:

- paid/order-missing opens an accurate case without claiming refund entitlement;
- missing facts produce questions/unknown labels, not invented deadlines;
- recovery code has no call path to payment submit, order create, refund initiate or complaint submission;
- index outage uses canonical guidance; stale guidance version cannot silently replace reviewed content;
- cross-user access is denied; unapproved/private fields never appear in HTML/JSON; expired links fail.
- duplicate/conflicting/late callbacks follow the WP-09 contract; an old pending fact cannot downgrade success.

### WP-11 — Integrated UI journey and operator console

**Owner:** P1. **Reviewers:** P3 for state labels; P2 for merchant evidence.  
**Goal:** present all capabilities as one coherent, accessible mobile-first experience.

Specification must cover:

- final screen-by-screen state matrix and navigation;
- concise spoken summaries versus visible exact terms;
- partial merchant results, repairs, recheck diffs, quote approval, independent outcomes, case evidence and export review;
- `/demo` operator flow and separation from shopper routes;
- demo data seeding and three-minute storyboard.

Implementation:

- connect shared cards and polling to the merged APIs;
- display source coverage, verified locality/time, freshness, unknown fees, total confidence, explicit errors and fixture labels;
- render independent payment/order/refund status and durable timeline through reload;
- implement operator scenario selection without exposing controls to ordinary shoppers; seed a restricted demo-operator identity for judge verification rather than weakening operator authorization;
- display metrics computed from persisted records: provider effects, submission attempts, callbacks received versus applied, seconds from timeout to case opened, and merchant observations with locality/freshness;
- preserve drafts and show accessible mobile/desktop feedback;
- create a rough end-to-end recording at the end of day 2 and the first release-candidate recording on day 3.

Tests/evidence:

- Playwright desktop and mobile journey against the actual backend and controlled simulator;
- route reload at search, preparation, unknown payment and case states;
- accessibility smoke, keyboard approval, captions/play fallback, errors and stale conflicts;
- seeded identities: two private shoppers and one operator; no credentials committed or shown in video.

### WP-12 — Security, resilience, cloud verification, and release

**Owner:** P4. **Reviewers:** all owners for their acceptance gates.  
**Goal:** freeze a demonstrably safe, reproducible deployed release.

Specification must cover:

- complete acceptance matrix and evidence owner;
- least-privilege IAM/Cedar review, CORS, API JWT claim validation, rate/concurrency limits and retention;
- CI/CD OIDC, serialized deployment, rollback and last-known-good artifacts;
- cloud smoke plan, live merchant plan, fault matrix, observability dashboard and teardown;
- public README, evaluator access, limitations and video plan.

Implementation and verification:

- run unit, contract, integration, Cedar, frontend, E2E and separate live/cloud suites;
- test cross-user denial, operator denial, prompt injection, upload attacks, callback HMAC/skew, export redaction and secret scanning;
- run outbox/DLQ/index/provider failure drills and retain trace/effect evidence;
- deploy commit-tagged artifacts only from green `main`;
- document setup, architecture, commands, data modes, limitations, evidence and cleanup;
- record the final three-minute video and perform explicit post-judging teardown.

Exit gate:

- deployed URL and evaluator sign-in work;
- two live location-verified merchants pass the live gate;
- core journey and accept-then-timeout recovery pass without manual database changes;
- one approval produces one simulator payment effect across reload/retry;
- all simulated/fixture limitations remain visible;
- no critical/high issue remains; medium issues are documented and do not compromise the core claim;
- feature freeze is declared and only regression fixes may merge.

---

## 8. Three-day execution schedule

Assumption: approximately 10 focused implementation hours per day, with specifications intentionally time-boxed. The team should prepare the WP-00/WP-01 specifications before the official implementation clock if event rules permit documentation work; code must still be created during the allowed event window.

### Day 1 — Prove feasibility and establish independent lanes

| Time | P1 | P2 | P3 | P4 | Integration gate |
| --- | --- | --- | --- | --- | --- |
| H0–H1 | Review WP-00 UI/client conventions; draft WP-03 | Review Python/container conventions; draft WP-04 | Draft WP-02 state/rule spec | Implement/merge WP-00 baseline | All owners approve contracts/toolchain |
| H1–H3 | Implement WP-03 shell/client/states | Run local + cloud connector spike with chosen locality | Implement WP-02 pure records/transitions | Deploy auth/API/DB skeleton; service-access checks | Green `main`; authenticated write/read |
| H3–H6 | Deploy UI shell; test auth/errors | Build/push browser container; prove first/second merchant | Finish domain tests; help durable job contract review | Prove outbox→workflow job; speech/model checks | **Six-hour Ship It decision** |
| H6–H10 | Start WP-05 text/voice UI against contracts | Complete WP-04 connector registry/evidence | Integrate WP-02 and draft WP-08/09 specs | Harden WP-07 transport skeleton/OpenSearch | Merge WP-02–04 as gates pass; day-end cloud smoke |

Day 1 required outcome: green scaffold, passed/explicitly decided checkpoint, typed domain baseline, authenticated UI shell, and credible two-merchant live path. If the checkpoint fails, do not pretend Day 2 can absorb an architectural rewrite; present the blockers and switch decision to the user.

### Day 2 — Complete shopping through safe simulated checkout

| Time | P1 | P2 | P3 | P4 | Integration gate |
| --- | --- | --- | --- | --- | --- |
| H0–H2 | Finish WP-05 spec/voice/photo/usual integration | Finish WP-06 spec and deterministic comparison | Implement WP-08 preparation/quote rules | Finish WP-07 job infrastructure/adapters | Specs approved; WP-07 merge first |
| H2–H5 | Complete WP-05 states/tests | Complete search/fees/repair and tests | Implement approval transaction/race tests | Support speech/upload adapters; review transaction writes | Merge WP-05–08 independently as green |
| H5–H8 | Integrate search/recheck/approval UI | Cloud live search and repair evidence; fix connector only | Implement WP-09 simulator/checkout and callback contract | Wire checkout workflow, callback ingestion, HMAC secret and alarms | Deployed happy path by H8 |
| H8–H10 | E2E happy-path test/mobile fixes; record rough end-to-end video | Verify live refresh/evidence/fixture isolation | Fault tests: timeout/reload/duplicate callback | Run durability and effect-count evidence | Day-end shopping→one-effect checkout gate and rough video |

Day 2 required outcome: voice/text/photo/usual intent, two-source comparison/repair, recheck, exact approval and simulated happy-path checkout work in the shared environment. The accept-then-timeout scenario must already preserve one attempt/effect across reload, even if the recovery prose/export completes on Day 3.

### Day 3 — Recovery, resilience, and feature freeze

| Time | P1 | P2 | P3 | P4 | Integration gate |
| --- | --- | --- | --- | --- | --- |
| H0–H3 | Implement WP-11 purchase/case/operator UI | Run live regression and injection/access tests | Support WP-10 provider-fact/state-safety review | Implement WP-10 callback/reconciliation/guidance/draft/export workflow | Paid/order-missing case visible |
| H3–H6 | Complete mobile/desktop E2E | Fix only merchant/matching defects; verify evidence | Complete transaction fault matrix and redaction review | Complete recovery/export; run DLQ/index/outbox/auth/Cedar drills | Full journey and recovery export pass |
| H6–H8 | Accessibility/copy/fixture-label audit; coordinate lightweight user validation | README merchant limits and freshness evidence; help observe user test | Transaction invariant audit and effect-count proof | Deploy candidate; dashboards/cost/cleanup docs | Release candidate tagged and validation recorded |
| H8–H10 | Final demo rehearsal/video assets | Demo support and live-source contingency | Demo fault sequence and case narrative | Full regression, release notes, freeze | **Feature freeze; green deployed main** |

Day 3 required outcome: a frozen deployed candidate, full fault/recovery demonstration, private export, passing core regression, first complete video, honest README and teardown instructions.

### Optional Day 4 — protected submission day

If available, Day 4 contains no new features or services. Only fix release-blocking regressions, rerun the complete acceptance suite, record/edit the final video, verify evaluator access, submit, and tear down cost-bearing resources after judging.

---

## 9. Dependency and collaboration protocol

### Contract-first handoff

When P1 needs an endpoint from P3 or P4, or P3 needs data from P2:

1. Consumer writes an example request, success response, error response, and required state transition in the package spec.
2. Producer edits/approves the OpenAPI/Pydantic/port definition.
3. Producer supplies deterministic fixtures and a contract test.
4. Consumer implements against generated types/fixture while producer implements the real adapter on a separate branch.
5. Both run the same contract test before either integration claim is accepted.

This is how people remain independent without waiting for a complete backend or sharing branches.

### Daily coordination

- Start of day, 15 minutes: blockers, contract changes, merge order, cloud-cost status.
- Every three hours, 10 minutes: gate status using evidence, not percentage-complete estimates.
- Before a breaking contract proposal: immediate owner sync; do not discover it at PR review.
- End of day, 20 minutes: deploy green `main`, run the day's integrated gate, record failures and assign owners.
- Keep a single `docs/STATUS.md` table with package state: Draft, Spec Review, Approved, Implementing, Code Review, Merged, Cloud Verified, Blocked.

### Lightweight user validation

On Day 3, P1 coordinates a 45–60 minute test with 5–8 available participants using seeded, non-sensitive demo data. After the failure scenario, ask: “Were you charged?”, “Does an order exist?”, and “What should you do next?” Record only aggregate correct-answer counts and recurring usability observations in `docs/evidence/user-validation.md`; do not collect payment records, credentials or personal messages. Treat this as usability evidence, not statistical proof of demand.

### Blocking rule

A blocker entry includes time found, exact failing gate, owner, evidence link/trace, attempted fixes, next decision time, and safe fallback. The release captain escalates any checkpoint blocker immediately. Never conceal a live-source failure by silently switching to fixtures.

---

## 10. Scope-control and fallback order

The team may reduce polish in this order without invalidating the core product:

1. Reduce animations, ornamental visuals and nonessential spoken narration.
2. Keep only the essential shared cards and one excellent mobile breakpoint plus functional desktop layout.
3. Keep the guidance corpus small but reviewed and properly sourced.
4. Keep OpenSearch as an optional projection with canonical fallback if it alone is unavailable.
5. Demonstrate only the required simulator scenarios in the UI; retain remaining invariant tests in code.

Do not cut:

- voice, photo list, usual basket;
- two genuinely live merchants in one locality;
- explicit fees/unknown-total semantics and fixture separation;
- preparation refresh and exact dedicated touch approval;
- unique stable provider key, unknown-payment blocking and callback deduplication;
- separate payment/order/refund states;
- evidence-based recovery and reviewed/redacted export;
- owner/operator authorization and core failure tests.

Any move from Ship It to Build It requires the hour-six evidence and explicit user decision. Do not maintain both implementations in parallel.

Receipt/SMS intake remains outside the three-day committed scope. It is the first candidate after every core gate passes, but it may be added only with explicit user approval and must label all pasted evidence as user-supplied and unverified.

---

## 11. Definition of done

### Package done

A work package is done when its spec is approved, implementation reviewed, automated tests pass, docs/contracts are current, it is merged to green `main`, and its stated integration evidence exists.

### Product done

ProofPath is done when:

- a shopper signs in and uses voice, text, photo, or usual basket;
- the app obtains and transparently presents observations from two live merchants for the tested locality;
- deterministic matching, fees, constraints, repair and recheck behave correctly;
- the exact simulated quote is approved only by its dedicated touch action;
- concurrent/repeated actions cause one logical attempt and one simulator effect;
- an accept-then-timeout survives reload, late callback and reconciliation;
- payment, order and refund facts remain distinct and recovery creates no commerce effect;
- a sourced, editable case produces a reviewed/redacted private HTML/JSON export;
- shopper/operator/cross-user boundaries and failure paths pass;
- CI, deployed cloud smoke, live merchant smoke and mobile/desktop E2E are green;
- the README, evidence, evaluator access, three-minute video, cost record and cleanup process are complete;
- every simulated or fixture surface is honestly labelled.

### Stop condition

At feature freeze, incomplete packages are reported as incomplete; they are not represented as working features. A smaller truthful, tested end-to-end journey is preferable to disconnected screens or unverified claims.
