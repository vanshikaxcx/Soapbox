# ProofPath — AI Session Handoff

## Project goal

Build a new hackathon project called **ProofPath**: a voice-first responsive web app that takes a spoken, typed or photographed grocery list, compares real location-specific merchants, repairs baskets within explicit constraints, and then demonstrates safe agentic checkout plus failed-payment/order recovery through an independent simulator.

- Live: merchant discovery, comparison, alternatives and basket recheck.
- Simulated and visibly labelled: checkout, payment, order, callback and refund.
- Team/event: four people, AWS WeMakeDevs First Commit, event AWS credits, new repository and new implementation.
- Target: **Ship It**, with an early decision checkpoint for a Build It switch—not two parallel releases.

## Current status

Planning/specification is complete; **no application code has been implemented in this workspace**.

`PROOFPATH-SPEC.md` is the standalone implementation source of truth. It now contains:

- final feature scope and exclusions;
- example user journey and UI routes;
- AWS HLD, module LLD and end-to-end sequence diagrams;
- repository layout and explicit component communication matrix;
- API, data, adapter and transaction contracts;
- safety/idempotency rules, tests, ownership and four-day schedule;
- mapping of eight industry references to design choices and honest boundaries.

The current spec is modified but uncommitted. Earlier reviews/proposals remain background only.

## Active files

| File | Role |
| --- | --- |
| `PROOFPATH-SPEC.md` | Final implementation plan; read this first and treat it as authoritative. |
| `ideation/PROOFPATH-SPEC-REVIEW.md` | Claude review already assessed and incorporated where relevant. It was moved here from the root; do not implement its open suggestions blindly. |
| `proofpath-panel-recommendation.md` | Earlier panel analysis and industry research; useful rationale, but superseded by the spec on scope/architecture. |
| `ideation/agentic-commerce-problem-statement.md` | Original problem framing and reference collection. |
| `ideation/proofpath-commerce-proposal.md` | Earlier product proposal; background only. |
| Other `ideation/*` files | Historical brainstorming, not implementation authority. |

## Settled design decisions

- Voice is the primary interaction: tap mic, speak, Transcribe returns text, agent acts; Polly speaks concise questions/results. Typed input is always available. No always-on or full-duplex voice.
- Photo-list import and saved usual basket are required, not stretch goals.
- Launch limit: **four items, two live merchants, one tested locality**. Connector registry is extensible; Blinkit, Zepto, BigBasket and other sources may be evaluated without guaranteeing all will work.
- Fixtures are a disclosed demo fallback only. Never mix/rank live and fixture prices; fixtures do not satisfy the live gate.
- Checkout/payment/order/refund are simulated. The simulator has a separate ledger and operator-only fault controls; no real money or retailer order.
- Exact touch approval is required. Spoken/generic “yes” and model output cannot authorize checkout.
- Payment, order and refund states remain separate. Unknown payment blocks a new attempt. Provider keys are unique/stable across retry, timeout and crash.
- Recovery queries existing facts only; it cannot create an order/payment or automatically file a complaint/refund.
- Cloud architecture: Amplify, Cognito, API Gateway/Lambda, Verified Permissions/Cedar, DynamoDB, Streams, EventBridge, SQS/DLQs, Step Functions Standard, S3, OpenSearch, Bedrock/Strands, Transcribe, Polly and CloudWatch.
- Agent/browser hosting: one FastAPI + Strands + Playwright container on **ECS Fargate via ECS Express Mode**, stored in ECR. App Runner is not assumed because it is closed to new customers.
- Browser engine is per-connector, not one global choice: Zepto runs on **Lightpanda** (CDP-compatible, no rendering/CSS/image/font cost — confirmed live at ~5s/search vs. Chromium's fuller page-load cost); Blinkit stays on real **Chromium** because it sits behind Cloudflare bot management keyed off TLS fingerprint, and Lightpanda deliberately refuses to impersonate a real browser (confirmed live: Lightpanda gets a 403 from Blinkit's Cloudflare edge). Both engines are long-lived per container and reused across tasks; only the browser context is created fresh per task. See `proofpath/services/merchants/browser_pool.py`.
- Browser↔backend uses HTTPS requests and polling; **only Transcribe uses a turn-scoped WebSocket**. Internal in-process modules use typed function/port calls.
- SAM/Vite/limited LocalStack support daily development. Do not build a second local workflow engine in parallel.
- End of first six implementation hours is the Ship It checkpoint: confirm model/speech access, deployed UI→authenticated API→DynamoDB, cloud browser/locality smoke, and one durable job. Bring unresolved blockers to the user before switching to Build It.
- Feature freeze at end of day 3; day 4 is reserved for fixes, regression, recording and submission.
- All eight references—OpenAI, Stripe, Google AP2, Google UCP, Mastercard, Visa, PayPal and AWS AgentCore Payments—are industry grounding, not claimed integrations.
- Existing GenPay/MiraclePay repositories are optional conceptual references only. Write this project from scratch; do not make them dependencies.

## Next work

1. Read `PROOFPATH-SPEC.md` fully before creating code.
2. Create the new repository skeleton exactly around the spec's `proofpath/` tree and check in the spec under `docs/`.
3. During the event, execute the six-hour checkpoint first:
   - pin region, Bedrock model, Polly voice and dependency versions;
   - verify AWS permissions/quotas and ECS Express Mode availability;
   - deploy minimal Amplify/Cognito/API Gateway/Lambda/DynamoDB path;
   - run one Playwright locality screenshot/search from Fargate;
   - run one DynamoDB outbox→EventBridge→SQS→Step Functions job.
4. If those pass, implement the vertical slice in this order: voice/text intent → two-source live search → deterministic comparison/repair → preparation/recheck → exact simulated approval → durable timeout/recovery → export.
5. Add tests with each subsystem; do not defer invariant/fault tests to day 4.
6. Validate all Mermaid diagrams in the target Markdown renderer. A previous sequence-diagram parse error caused by semicolons was fixed, but no local Mermaid parser was installed for a full render test.

## Guardrails for the next AI

- Keep the solution concise and finishable. Do not add services or features unless the core journey already passes its acceptance tests.
- Ask the user before changing a settled product/architecture decision or switching away from Ship It.
- Do not describe fixtures as live data, app claims as bank holds, simulated refunds as recovered money, or quote hashes as AP2 compliance.
- Preserve user changes and inspect Git status before edits. Current known state: `PROOFPATH-SPEC.md` is modified; `handoff.md` is new; the review was moved from root to `ideation/` (Git may display this as deleted + untracked until staged).
