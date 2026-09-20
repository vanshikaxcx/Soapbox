<p align="center">
  <img src="docs/assets/logo.png" alt="ProofPath logo" width="160">
</p>

# ProofPath

ProofPath is a voice-first web application for comparing locality-specific grocery baskets and demonstrating safe simulated checkout with evidence-based recovery. Checkout, payment, orders, callbacks, and refunds are simulated: **Simulated checkout · no money moved · no retailer order placed.**

> [!IMPORTANT]
> Discovery, comparison, alternatives, and rechecking use **live** merchant data (maximum four distinct items, two working merchants, one tested locality). Unknown fees are never treated as zero, and estimated totals never outrank verified ones.

The project is built by a four-person team through a sequence of reviewed work packages (WPs), each scoped, specified, implemented, and merged independently. See [Governance and authority](#governance-and-authority) for the documents that define scope and ownership, and [Project status](#project-status) for what is implemented today.

## What it does

1. Speak (or type) a list — "Five kilos of rice, one litre of oil, two litres of milk, under ₹900." The agent asks only for what's missing, such as location.
2. Two merchants are queried live. If an item is unavailable, the agent proposes a permitted brand or pack substitution for review.
3. The basket is rechecked before checkout; you accept any changed terms, then separately approve the exact simulated quote with a dedicated touch control — spoken "yes" or a generic confirm can never authorize payment.
4. If the simulator loses a response, reloading shows the same pending attempt; a retry cannot create a second payment.
5. When a late callback confirms payment but order evidence is missing, the recovery flow queries the original references and prepares a sourced, exportable support packet.

| Route | Purpose |
| --- | --- |
| `/` | Conversation: mic, captions, photo/usual-list input, questions, inline basket/approval/recovery cards. |
| `/searches/:id` | Comparison, source coverage, freshness, repair, and recheck. |
| `/purchases/:id/approve` | Exact quote, change summary, expiry, approve/cancel. |
| `/purchases/:id` | Independent payment/order/refund outcomes, progress, timeline. |
| `/cases/:id` | Known/missing facts, guidance, editable draft, redaction preview, export. |
| `/demo` | Operator-only provider-simulator controls and effect counts. |

### End-to-end walkthrough

The sequence below traces one full journey — voice capture through simulated checkout to evidence-based recovery — across every backend hop. Everything after "Dedicated simulation approval" is deliberately adversarial: the simulator drops its own response on purpose so the durable-checkout and recovery paths are demonstrated, not merely described.

```mermaid
sequenceDiagram
  actor U as Shopper
  participant UI as Web app
  participant API as API
  participant STT as Transcribe
  participant DB as DynamoDB
  participant JOB as Outbox / EventBridge / SQS / SFN
  participant AG as Agent / merchant connectors
  participant SIM as Provider simulator
  U->>UI: Tap mic and speak
  UI->>API: HTTPS: bound voice session
  API-->>UI: Presigned WSS URL
  UI->>STT: WSS: PCM audio
  STT-->>UI: Partial/final transcript
  UI->>API: HTTPS: final transcript + context
  API->>DB: Commit turn + job + outbox
  DB-->>JOB: Durable event
  JOB->>AG: Extract and search real merchants
  Note over UI,AG: Missing facts: persisted question → Polly/S3 audio → bound voice/touch answer
  AG-->>JOB: Observations/errors/alternatives
  JOB->>DB: Persist comparison
  UI->>API: HTTPS polling: results
  U->>UI: Accept repair and select basket
  UI->>API: HTTPS: prepare
  API->>DB: Preparation job/outbox
  DB-->>JOB: Recheck work
  JOB->>AG: Refresh basket
  JOB->>DB: Diff or immutable quote
  UI->>API: Accept exact changes if needed
  U->>UI: Dedicated simulation approval
  UI->>API: HTTPS: quote ID/hash/version
  API->>DB: Atomic approval/attempt/lookup/job
  DB-->>JOB: Checkout work
  JOB->>SIM: IAM Invoke: stable provider key
  SIM--xJOB: Accepted but response lost
  JOB->>DB: Unknown outcome, preserve attempt
  U->>UI: Reload / retry
  UI->>API: Read existing attempt
  SIM->>API: HMAC HTTPS late callback
  API->>DB: Inbox + reconciliation job
  DB-->>JOB: Recovery work
  JOB->>SIM: Read original payment/order/refund
  JOB->>AG: Grounded investigation
  JOB->>DB: Case and evidence
  UI->>API: Review/export request
  Note over UI,DB: Export task writes private S3. UI polls then obtains presigned download
```

Every arrow into `API` and `JOB` is HTTP, not a persistent connection: the browser polls (2s, then 5s) rather than subscribing, and the only WebSocket in the system is the turn-scoped Transcribe session. Nothing in this diagram lets a spoken word, a generic "yes," or model output reach the approval endpoint — only the dedicated `Approve simulated ₹X` control on `/purchases/:id/approve` does.

## Architecture

### High-level design and AWS responsibilities

```mermaid
flowchart TB
  UI[React / Amplify] -->|HTTPS + JWT| API[API Gateway / Lambda]
  UI -->|OAuth PKCE| AUTH[Cognito]
  UI <-->|Turn-scoped WSS| STT[Transcribe]
  API --> AVP[Verified Permissions / Cedar]
  API --> DB[(DynamoDB: state, inbox, outbox)]
  DB -->|Streams| PUB[Publisher Lambda]
  PUB --> EB[EventBridge]
  EB --> JQ[SQS jobs + DLQ]
  JQ --> CTRL[Job controller Lambda]
  CTRL --> SF[Step Functions Standard]
  SF --> W[Task Lambdas]
  W -->|Bounded HTTPS| AG[ECS Fargate / Express Mode<br/>FastAPI + Strands + Playwright]
  AG --> BED[Bedrock: text, vision, tools]
  AG -->|Read-only HTTPS| MER[Real merchants]
  AG --> OS[OpenSearch: offers + guidance]
  W --> DB
  W -->|IAM Lambda Invoke| SIM[Simulator / separate ledger]
  SIM -->|HMAC HTTPS callback| API
  EB --> PQ[SQS projections + DLQ]
  PQ --> IDX[Indexer Lambda]
  IDX --> OS
  W --> POL[Polly]
  W --> S3[(Private S3: images, speech, evidence, exports)]
  AG --> S3
  UI <-->|Presigned HTTPS| S3
```

| Service | Responsibility |
| --- | --- |
| Bedrock + Strands | Schema-constrained extraction and bounded, read-only shopping/recovery tool use — no autonomous swarm. |
| Transcribe / Polly | Microphone transcription and audible, persisted assistant questions/summaries. |
| Amplify / Cognito | Static hosting and authorization-code PKCE sign-in. |
| API Gateway / Lambda | User API, transaction/task handlers, callbacks, publisher, controller, indexer. |
| ECS Express Mode / Fargate / ECR | One agent/browser container with a managed HTTP entry point and commit-tagged images. |
| Verified Permissions / Cedar | Owner/action/operator authorization outside the model. |
| DynamoDB | Canonical state with conditional writes/transactions; a separate simulator ledger. |
| Step Functions Standard | Durable jobs, bounded parallel tasks, and explicit failure states. |
| EventBridge / SQS | Route committed events to jobs/projections with DLQ-backed retry. |
| OpenSearch | Rebuildable offer search and guidance retrieval — never the price/payment authority; canonical DynamoDB facts are reloaded before acting on index results. |
| S3 | Private images, source extracts, speech, exports, and versioned guidance snapshots. |

Communication is HTTP polling end to end — there is no permanent WebSocket between the app and the backend. Every event hop (DynamoDB Streams → publisher → EventBridge → SQS → controller → Step Functions → task Lambdas) treats delivery as at-least-once and deduplicates on stable business identities, so a retried or redelivered message never doubles an effect.

### Code architecture and dependency direction

```mermaid
flowchart LR
  API[API handlers] --> APP[Application services]
  TASK[Workflow handlers] --> APP
  APP --> DOMAIN[Pure domain: matching, totals,<br/>hashes, transitions]
  APP --> PORTS[Typed ports: state, jobs, blobs,<br/>policy, browser, model, providers, speech]
  PORTS --> AWS[AWS adapters]
  PORTS --> TEST[Test / selected local adapters]
  AG[Shopping or recovery agent] --> TOOLS[Allowlisted wrappers]
  TOOLS --> APP
```

Dependency direction is one-way: `handler → application use case → domain → port → adapter`. Domain code stays pure — no AWS SDKs, browser libraries, or transport types — and every state transition or business rule has exactly one authoritative implementation, never duplicated across handlers, workers, and simulator code. Agents only reach the system through allowlisted tool wrappers (`search_merchants`, `find_alternatives`, `evaluate_baskets`, `read_guidance` for shopping; `read_case`, `query_payment`, `query_order`, `query_refund`, `read_guidance` for recovery) that resolve to authorized server records — agents propose, deterministic application/domain code validates, authorizes, and commits.

### Repository layout

```text
proofpath/
├── contracts/openapi.yaml            # API/schemas; generated TS types
├── web/src/{pages,components,api}/    # shared cards, mic/audio, auth, polling
├── services/
│   ├── api/                          # Lambda HTTP entry points
│   ├── application/                  # use cases and typed ports
│   ├── domain/                       # pure rules; no AWS/browser imports
│   ├── agent/                        # FastAPI, Strands tools, Dockerfile
│   ├── merchants/                    # registry + independent connectors
│   ├── adapters/                     # AWS and deterministic test implementations
│   ├── workers/                      # tasks, publisher, controller, indexer
│   └── simulator/                    # separate ledger, scenarios, callback sender
├── workflows/                        # converse/speak/search/prepare/checkout/recovery/export
├── policies/                         # Cedar schema, policies, allow/deny fixtures
├── guidance/                         # rules, applicability, URLs, checked dates
├── infra/{template.yaml,compute.yaml,search.yaml,parameters/}
├── scripts/                          # dev/test/deploy/seed/retry/verify/cleanup
└── tests/{unit,contracts,integration,e2e,live}/
```

## Data model

One DynamoDB table (`PK/SK`) holds canonical application state, plus a separate table for the simulator's own ledger — the simulator never reads or writes application records directly. Partitions: `USER#id` (intents/usual-basket/idempotency/exports), `CONVERSATION#id` (turns/questions), `VOICE#id`, `SEARCH#id` (observations/baskets/fees/repairs), `PURCHASE#id` (preparations/quotes/approvals/attempts/refunds/inbox/evidence/case), `JOB#id`, `OUTBOX#id`, `GUIDANCE#id`. A unique `PROVIDER#provider#key` item is conditionally created together with its attempt, which is how the system enforces "one irreversible simulator effect" at the storage layer rather than by convention.

| Record | Carries |
| --- | --- |
| Intent / UsualBasket | Items (`id`, `name`, `quantity`, `unit`, hard attributes, flexibility), location, budget, delivery constraint, revision/version. The saved usual basket excludes prices and payment state — loading it always triggers a fresh observation. |
| Search / Observation | Revision, mode (`live` \| `fixture`), progress, merchant/SKU/URL, pack/unit/price/stock, verified location/time, evidence key, extraction status. |
| Basket / FeeAssessment | Line matches/quantities/substitutions/subtotal; fees bound to merchant/location/line hash/subtotal/time; a total marked `complete` \| `estimated` \| `unknown`. |
| Preparation / CheckoutQuote | Preparation version/base basket/revision/refreshed facts/diff hash/expiry/acceptance; an immutable quote carrying version, seller, exact lines, charges, total, currency, delivery terms, expiry, and hash. |
| Approval / Purchase / Attempt | The approval's exact quote/hash/version and consumed status; the purchase's active attempt and independent payment/order/refund outcomes; the attempt's bound approval, provider key, request hash, dispatch state, start time, provider reference. |
| ProviderLookup / Refund | A unique `provider+key → purchase/attempt` mapping with expected seller/amount/currency; a refund reference pointing back to `purchase/attempt/amount/provider status`. |
| Job / Outbox | Job type, input hash, reference, status, stage, progress, result, error, run generation, execution ARN; outbox event ID, type, aggregate version, reference, publication state. |

Money is always integer paise, never floating point. IDs are opaque and owner identity is always derived server-side from the validated Cognito token — never trusted from the browser or the model. OpenSearch (`offers-v1`, `guidance-v1`) injects trusted owner/search/location/freshness filters and is treated purely as a rebuildable search index: canonical DynamoDB facts are reloaded before acting on any index result, and an index outage falls back to canonical reads rather than failing the request.

## API and workflows

Every response is `{data, request_id}` or `{error: {code, message, details}, request_id}`. Mutations require an `Idempotency-Key` (the same key with a different payload returns `409`) and an expected version/revision (a stale one also returns `409`; invalid input is `422`; expiry is `410`; an inaccessible resource is `404`). Async commands return `202 {job_id, resource_id, status_url}` only after the domain write, job, and outbox commit atomically together.

| Endpoint | Contract |
| --- | --- |
| `POST /conversations`, `GET /conversations/{id}` | Create/read an owned conversation. |
| `POST /conversations/{id}/turns` | Text/upload plus captured question/context versions → interpretation job. |
| `POST /conversations/{id}/questions/{qid}/answer` | Choice plus conversation/target versions → atomic answer/change; never a payment approval. |
| `POST /intents`, `PATCH /intents/{id}`, `GET/PUT /me/usual-basket` | Create/edit a shopping request; read/save the usual list. |
| `POST /searches`, `GET /searches/{id}`, `POST /repairs/{id}/accept` | Start a search; read its progress; accept an explicit repair into a new revision. |
| `POST /purchases`, `GET /purchases/{id}` | Basket/revision → preparation job; read changes, quote, and independent outcomes. |
| `POST /purchases/{id}/preparations/{version}/accept` | Exact diff hash plus purchase version → accept refreshed terms and build a quote if still fresh. |
| `POST /purchases/{id}/approve` | Exact quote ID/hash/version plus purchase version → consumed approval, attempt, and checkout job, all atomically. |
| `POST /purchases/{id}/cancel`, `POST /purchases/{id}/reconcile` | Cancel before claim, or reconcile existing references without starting new payment. |
| `GET /cases/{id}`, `PATCH /cases/{id}/draft` | Read a recovery case; edit its draft — never provider facts. |
| `POST /cases/{id}/exports`, `GET /exports/{id}` | Reviewed fields/draft version → private HTML/JSON export job and presigned downloads. |
| `POST /callbacks/simulator`, `POST /demo/scenarios` | HMAC-signed provider ingestion; operator-only fault injection. |

| Workflow | Stages |
| --- | --- |
| Converse / Speak | Validate input → extract → schema-check → persist turn/intent/question → synthesize caption. A clear complete request starts a read-only search; a photo requires a summary confirmation first. |
| Search | Validate → map over **(merchant, item)** tasks at concurrency 2 → persist partial observations → assess basket fees → deterministic comparison → bounded repair → results. |
| Prepare | Refresh lines/fees → build an immutable preparation/diff → require explicit acceptance if anything changed → build the quote. A fresh, already-accepted preparation builds the quote directly, avoiding an endless recheck loop. |
| Checkout | Load the attempt → validate the bound approval → conditionally mark dispatch `started` → submit/query the same provider key → bounded polling → idempotent order creation only after verified payment → reconcile or open a case. |
| Recovery / Export | Read existing provider facts → deterministic reconciliation → applicable guidance → grounded draft → separate authorized/redacted export. |

## Transaction safety

Every irreversible effect in the system is gated by the same rule: only the dedicated touch control **`Approve simulated ₹X`** on `/purchases/:id/approve` may call the approval endpoint. Spoken approval, a generic "yes," typed conversational approval, model output, and any agent tool are all structurally incapable of authorizing checkout — there is no code path from them to the approval handler.

Dispatch against the simulator is a small explicit state machine, chosen specifically so that a crash or lost response can never be confused with a definite outcome:

```mermaid
stateDiagram-v2
  [*] --> ready
  ready --> started: persist before provider submission
  ready --> expired_unsent: expiry while still ready (no provider call occurred)
  started --> reconciled: response received, or same-key query after ambiguous dispatch
  expired_unsent --> [*]: requires fresh preparation/approval
  reconciled --> [*]
```

Payment, order, and refund are deliberately tracked as **independent** states — payment success never implies an order exists, and a refund `pending` fact can never be silently downgraded by an older, still-`pending` fact arriving late:

```mermaid
flowchart LR
  subgraph Payment
    P1[not_started] --> P2[claimed] --> P3[pending] --> P4{outcome}
    P4 -->|success| P5[succeeded]
    P4 -->|failure| P6[failed]
    P3 -.ambiguous.-> P7[unknown]
  end
  subgraph Order
    O1[not_created] --> O2[pending] --> O3{outcome}
    O3 -->|confirmed| O4[confirmed]
    O3 -->|failure| O5[failed]
    O2 -.ambiguous.-> O6[unknown]
  end
  subgraph Refund
    R1[none] --> R2[pending] --> R3{outcome}
    R3 -->|completed| R4[completed]
    R3 -->|failure| R5[failed]
    R2 -.ambiguous.-> R6[unknown]
  end
```

Other invariants that are never weakened for a demo:

- Approval binds the exact quote ID, hash, version, seller, lines, charges, total, currency, delivery terms, and expiry; repeated approval of the same quote returns the existing attempt rather than creating a second one.
- The simulator uniquely enforces payment/order keys: an identical replay returns the original facts even after expiry, and a changed payload conflicts outright. After an ambiguous dispatch, the checkout job always queries the same key first — it never resends refreshed terms.
- Callback bodies are immutable and HMAC-signed (`delivery_timestamp + "\n" + event_id + "\n" + raw_body`); a callback with more than 5 minutes of clock skew, a mismatched lookup/seller/amount/currency, or the same provider+event ID with a different body is rejected.
- A workflow or job failure is never treated as a payment failure, and unknown or otherwise unresolved payment exposure blocks any replacement attempt.
- Recovery may read payment, order, refund, evidence, and guidance facts, but it can never submit payment, create an order, initiate a refund, or file a complaint — it only investigates and drafts.
- Duplicate requests, events, callbacks, workflow starts, and retries result in **at most one** irreversible simulator effect, enforced by conditional writes at the canonical write boundary, not by client-side prevention.

## Governance and authority

- The settled product and architecture authority is [docs/PROOFPATH-SPEC.md](docs/PROOFPATH-SPEC.md).
- The execution plan, work packages, ownership, and review gates are in [Final idea and archi/PROOFPATH-IMPLEMENTATION-POA.md](Final%20idea%20and%20archi/PROOFPATH-IMPLEMENTATION-POA.md).
- [docs/STATUS.md](docs/STATUS.md) is the canonical package-status ledger; [LEARNING.md](LEARNING.md) is append-only.
- `ideation/` and the retained `Final idea and archi/PROOFPATH-SPEC.md` are historical material and are not implementation authority.
- [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md) define the operating rules that all contributors and coding agents follow, including the ownership boundaries below.

## Project status

Work packages WP-00 through WP-09 are implemented and merged into `main`. In summary:

- **WP-00 (P4):** repository, toolchain, and contract baseline. PowerShell command surface, Vite web scaffold, SAM-based health Lambda, deterministic CI.
- **WP-01 (P4):** cloud viability checkpoint. AWS OIDC federation for CI, DynamoDB-backed checkpoint API behind Cognito, durable job/outbox chain, Bedrock/Polly/Transcribe adapters, Amplify hosting, OpenSearch template. Delivered as a conditional pass with two accepted, documented environmental exceptions (an AWS Organization service-control-policy restriction outside this project's control, and a merchant-side network block unrelated to the code).
- **WP-02 (P3):** core commerce domain. Pure domain rules, canonical hashing, and transaction-state invariants.
- **WP-03 (P1):** web shell, Cognito PKCE authentication, and a generated, typed API client.
- **WP-04 (P2):** agent container and live merchant connectors (Blinkit, Zepto).
- **WP-05 (P1):** text, voice, photo, and usual-basket intake, built against fixtures ahead of the real extraction and speech adapters.
- **WP-06 (P2):** search comparison and basket repair built on WP-02 and WP-04's extraction contract.
- **WP-07 (P4):** durable workflow and job-transport infrastructure supporting preparation, checkout, and recovery.
- **WP-08 (P3):** preparation, exact quote hashing, and the dedicated touch-approval control.
- **WP-09 (P3):** the simulated provider, durable checkout, and callback ingestion.

WP-10 (P4, callback reconciliation, recovery, guidance, case, and export) has not started; it is the sole remaining dependency for WP-11 (P1, the integrated UI journey and operator console). WP-12 (P4, release and teardown) follows once every preceding package is complete.

`docs/STATUS.md` carries the full acceptance-criteria detail per package; treat it, not this summary, as authoritative for any specific claim. See [`MVP-PATH.md`](MVP-PATH.md) for the current minimum-viable delivery path.

## Getting started

Install these exact prerequisite versions before setup: [Node.js `24.21.0`](https://nodejs.org/dist/v24.21.0/), npm `12.0.2` (`npm install --global npm@12.0.2`), [uv `0.12.13`](https://docs.astral.sh/uv/getting-started/installation/), [PowerShell 7](https://learn.microsoft.com/powershell/scripting/install/installing-powershell), and [SAM CLI `1.164.0`](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html).

> [!NOTE]
> CPython `3.12.14` has no official binary installer on any platform: Python 3.12 entered upstream "security fixes only" mode and python.org only ships source tarballs for this version. Install it through uv's own toolchain instead of Homebrew/conda/pyenv:
>
> ```sh
> uv python install 3.12.14 --default
> python --version   # must print Python 3.12.14
> ```
>
> If a different Python still wins on `PATH`, ensure uv's shim directory takes priority.

Docker Desktop (or Docker Engine + `docker compose`) is only required for `build`, `dev`, and Gate A work — not for setup. If your platform's package manager for SAM CLI is broken or unavailable, `uv tool install aws-sam-cli==1.164.0` is a working platform-independent alternative.

```sh
pwsh ./scripts/proofpath.ps1 versions
pwsh ./scripts/proofpath.ps1 setup
```

`setup` verifies prerequisite versions, checksum-verifies Gitleaks into ignored `.tools/`, performs frozen `uv`/`npm` installs, and installs the pinned Playwright Chromium build. It never requests AWS or LocalStack credentials. Root `npm` aliases expose the same command surface; use the PowerShell interface as canonical.

### Running locally

```sh
pwsh ./scripts/proofpath.ps1 build
pwsh ./scripts/proofpath.ps1 dev
pwsh ./scripts/proofpath.ps1 web-smoke
```

`build` produces `web/dist` and a release-equivalent containerized SAM build, using an exact repository-controlled build image (updating the digest requires a reviewed spec change, not an opportunistic edit). `dev` starts the Vite scaffold at `http://127.0.0.1:5173` and the SAM Local health API at `http://127.0.0.1:3001/health` — Ctrl+C stops both. `web-smoke` starts those services with bounded readiness checks and runs a Chromium scaffold smoke test. None of these commands touch LocalStack or AWS credentials.

Daily development runs Vite plus SAM local API, with LocalStack limited to the services actually verified in its available edition (initially DynamoDB, S3, SQS). CI always uses deterministic model/merchant/speech/provider fixtures; real AWS access is exercised only in separate, manual smoke tests, and live/fixture data are never mixed in persistence, ranking, UI, or exports.

### Commands

All commands run through `pwsh ./scripts/proofpath.ps1 <command>` from the repository root (or the equivalent `npm run <command>` alias):

| Command | Purpose |
| --- | --- |
| `help`, `versions` | Command reference; verify pinned tool versions. |
| `setup` | Verified, frozen dependency installation. |
| `format`, `format-check`, `lint`, `typecheck` | Formatting and static analysis. |
| `test-unit`, `test-contract`, `test-integration`, `test` | Deterministic test suites (model/merchant/speech/provider adapters are faked in CI). |
| `build`, `dev`, `web-smoke` | Containerized SAM build, local dev servers, browser smoke test. |
| `security` | Gitleaks history scan, `pip-audit`, `npm audit`, ignore-rule sentinel checks. |
| `verify-gate-a` | Every non-mutating check in one pass, then asserts a clean tracked tree. |
| `verify-clean-clone` | `setup` followed by `verify-gate-a` from a fresh clone. |

`.github/workflows/checks.yml` runs the same command surface as required named CI jobs, using pinned action commit SHAs and no AWS or LocalStack credentials.

> [!WARNING]
> Any vulnerability or secret-scanner suppression must be recorded in [`security/suppressions.toml`](security/suppressions.toml) with an advisory ID, narrow scope, reason, owner, approval reference, and expiry date. The manifest starts empty; blanket suppressions are rejected and expired entries fail `security` outright.

### Deployment pipeline

```mermaid
flowchart LR
  BR[Branch] --> PR[PR: lint/unit/contracts/Cedar]
  PR --> TEST[Integration + Playwright]
  TEST --> MAIN[Teammate review / main]
  MAIN --> BUILD[SAM build + web + ECR image]
  BUILD --> DEPLOY[OIDC: app/compute/search deploy]
  BUILD --> WEB[Amplify release]
  DEPLOY --> SMOKE[Cloud smoke + fault evidence]
  WEB --> SMOKE
  SMOKE --> DEMO[URL + README + video]
```

Deployment is serialized from a green `main` by the release owner using repository/branch-scoped GitHub OIDC/STS — never long-lived AWS credentials, and never a manual patch of deployed infrastructure. PRs cannot deploy; the last working template/image is always retained for rollback.

## Ownership boundary

- **P1 (experience and voice)** owns `web/**`, shared UI cards, the polling client, text/voice/photo/usual-basket interactions, recovery and export presentation, accessibility, and frontend end-to-end scenarios.
- **P2 (shopping intelligence)** owns `services/agent/**` and `services/merchants/**`: extraction, merchant connectors, matching, normalization, fees, comparison, repair, and merchant evidence.
- **P3 (transaction safety)** owns transaction truth and semantics in `services/domain/**` and `services/simulator/**`: simulator behavior, provider-fact contracts, transaction-domain reconciliation rules, and commerce invariants.
- **P4 (platform, durability, and recovery)** owns `infra/**`, `policies/**`, `.github/**`: AWS adapters, job transport and workers, callback ingestion, durable reconciliation and recovery machinery, recovery handlers, the guidance/case/export backend, CI/CD, and releases.

Follow [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md)'s approved work-package process before making changes.

## Industry grounding

ProofPath's contribution is the shopper-facing journey from exact approval to understandable payment/order recovery — not a claim of certification against any of these protocols.

| Reference | Applied as | Boundary |
| --- | --- | --- |
| [OpenAI Instant Checkout / ACP](https://openai.com/index/buy-it-in-chatgpt/) | Explicit merchant, basket, and checkout contracts. | No ACP integration required. |
| [Stripe Shared Payment Tokens](https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens) | Bind approval to seller, amount, and expiry. | Our approval record is not a payment token or credential. |
| [Google AP2](https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol) | Preserve exact consent and outcome evidence together. | Application hashing is not AP2 compliance. |
| [Google UCP order specification](https://ucp.dev/specification/shopping/order/) | Separate order lookup/events from payment state; reconcile post-purchase evidence. | No UCP implementation required. |
| [Mastercard Agent Pay](https://newsroom.mastercard.com/news/press/2025/april/mastercard-unveils-agent-pay-pioneering-agentic-payments-technology-to-power-commerce-in-the-age-of-ai/) | Record acting identity, instructions, and exact approval with evidence. | Cognito authentication does not make an agent Mastercard-registered. |
| [Visa Intelligent Commerce](https://www.visa.com/en-us/solutions/intelligent-commerce) | Keep credentials outside model context; separate recommendation from authorization. | No Visa integration implied. |
| [PayPal agentic commerce services](https://developer.paypal.com/agentic-commerce-services/about/) | Capability-based discovery/cart/provider adapters with explicit access limits. | No assumed universal storefront access. |
| [AWS AgentCore Payments](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-payments-is-now-generally-available-enabling-agents-to-transact-safely-and-autonomously-at-scale/) | Separate model reasoning from deterministic spending controls. | Architectural grounding only. |
