# ProofPath: Consent to Resolution — panel recommendation

Planning and source review, 13 September 2026. No application code was implemented or deployed for this review.

## Decision

Build a narrowly scoped **agentic grocery purchase and payment-recovery assistant**, targeting **Ship It**. The team has confirmed four members, event credits, and organizer permission to reuse its GenPay/MiraclePay code in a different repository. Treat that permission as settled; preserve it with the submission's provenance notes. Reuse selected existing components and build the transaction/recovery core anew during the event.

The strongest contribution is the connection between the exact purchase a person approved and the evidence needed when payment and order outcomes disagree. A broad shopping assistant, another payment mandate framework, or a generic complaint-writing chatbot is a weaker submission.

The [event page](https://www.wemakedevs.org/aws/first-commit) says one submission is considered across awards, so Ship It is the deployment target rather than an exclusive enrollment choice. The [published rules](https://www.wemakedevs.org/aws/rules) otherwise exclude prior projects, including rewrites. Disclose the reuse covered by the organizer's permission and identify what was added during the event.

## Panel and disagreements

| Reviewer | Mandate | Conclusion |
| --- | --- | --- |
| Product and judging reviewer | Challenge daily usefulness, novelty, scope and the three-minute demonstration | Lead with the payment/order mismatch. The biggest weakness is a simulator that could look like scripted screens. |
| Payments and references reviewer, extra-high effort | Verify protocol claims, UPI recovery distinctions and unsafe retry semantics | Mandates and post-purchase protocols already exist. Build evidence-based recovery over these ideas; do not claim a new payment rail. |
| Code and AWS reviewer, high effort | Inspect source, identify reusable parts and failure gaps, propose a four-day deployment | Reuse presentation and pure helpers selectively. Replace payment, budget, approval and persistence logic. |
| Lead synthesis | Compare options, reconcile tradeoffs and choose the final scope | One continuous purchase-to-case workflow; minimal useful AWS services; independent failure injection as proof. |

The product reviewer challenged whether a simulated commerce app demonstrates real usefulness. Our response is a separate backend simulator, an independently triggered failure, a page refresh, a replay attempt, and an export built from actual persisted events. This proves the prototype's behavior. It still does not prove live merchant access, bank settlement, or consumer adoption.

| Candidate | Verdict |
| --- | --- |
| Multi-domain shopping, recharge, trains, movies and recovery | Cut. Adapter work and demonstration complexity overwhelm the distinctive feature. |
| Standalone failed-UPI evidence assistant | Useful fallback. Easier to build, but imported evidence cannot independently verify settlement. |
| Grocery purchase through consent, reconciliation and recovery | Recommended. Capturing evidence before payment makes recovery more useful than reconstructing everything afterward. |

## Final problem statement

> When an everyday online purchase stalls after payment, shoppers struggle to establish what they approved, whether their money moved, whether an order exists, and whether paying again could create another charge. ProofPath helps a shopper prepare and approve a grocery purchase, follows payment and order status separately, and assembles a source-backed recovery case when the outcome remains unclear.

Primary user: a student or household shopper buying a small grocery basket within a fixed budget. The first implementation supports two explicitly labeled demonstration merchants.

Product promise: **“Approve the purchase. Track the outcome. Have the evidence when something goes wrong.”**

This is supervised agentic commerce: the agent interprets the request, invokes discovery tools, proposes a basket, retrieves relevant evidence and explains next steps. The backend controls approval, execution, state transitions and monetary calculations. Final payment approval remains an explicit user action.

Do not describe an application approval record as a bank mandate, UPI AutoPay authorization, or an AP2-compliant credential.

## Exactly what to build

Example request: “Find 5 kg rice and 1 litre oil under ₹900 including delivery. Show me the options before paying.”

1. **Prepare the basket.** A Strands agent extracts items, quantities, budget and delivery constraints into a validated schema. Ask about material ambiguity only. Search two fixture merchant adapters. Compute pack equivalence, substitutions and full delivered totals in deterministic code. Select one merchant for the entire basket; no split orders.
2. **Approve exact terms.** Show merchant, items, quantities, fees, total, delivery terms and quote expiry. Store the authenticated user's approval against the frozen quote version. The natural-language request supplies shopping constraints; it is not standing permission to pay.
3. **Execute the approved attempt.** Revalidate the quote, enforce Cedar policy through Verified Permissions, and atomically create the payment attempt and consume the approval. Repeated submission returns the same attempt. A new attempt requires a new approval.
4. **Follow two outcomes.** Display payment status and order status independently. A timeout produces uncertainty, not a definitive failure. While unresolved, a repeat application checkout is blocked and the user can check the original transaction.
5. **Open the recovery case.** When payment or order remains unresolved, assemble the approved quote, approval, attempt reference, provider observations, order observations and timeline. Show “What we know,” “What is missing,” and “Next action.”
6. **Export a reviewed packet.** Generate a redacted HTML/printable report and JSON evidence manifest. Include source references, timestamps, provenance and the draft support message. Export is a useful completed action; it is not evidence of refund or complaint submission.

Keep the interface to four surfaces: request/comparison, approval card, transaction status, recovery case. A developer-only simulator panel drives provider events and must be separate from shopper UI state.

### First stretch

Add **paste a UPI SMS or manually enter a receipt** as a second intake route into the same recovery-case model. Extract candidate fields, ask the user to confirm them, and preserve the source. Label this evidence “user supplied; unverified.” This enables assistance for purchases made outside ProofPath without pretending to have bank API access.

OCR, PDF ingestion and multiple languages come after this. Manual correction is more important than adding another input modality.

### Cut from the hackathon

- Flights, hotels, movies, trains, recharge and broad web scraping.
- Multi-merchant split orders and shared budgets across multiple autonomous agents.
- Automatic payment based on a low-risk threshold.
- Real money, wallet custody, PIN/OTP collection and real merchant onboarding.
- Automatic dispute filing, automatic refund issuance and promised recovery times.
- AP2/UCP certification claims or implementing several competing protocols.
- A separate user-facing policy editor, multi-agent runtime, vector database and additional AWS products without a demonstrated need.

## How every industry reference informs the design

These references establish industry direction and relevant primitives. They do not establish the frequency of your users' problem or prove that this prototype solves it.

| Reference | Established capability | Design implication and honest boundary |
| --- | --- | --- |
| [OpenAI Instant Checkout/ACP announcement](https://openai.com/index/buy-it-in-chatgpt/) and [official concepts](https://developers.openai.com/commerce/guides/key-concepts) | Structured commerce connects agents and merchant systems; the merchant remains responsible for its commercial operations. | Use explicit merchant contracts. Do not claim that existing agents universally stop before checkout. |
| [Stripe agentic commerce](https://docs.stripe.com/agentic-commerce) and [Shared Payment Tokens](https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens) | Payment credentials can have seller, amount and expiry restrictions; access to some agent capabilities is gated. | Bind approval to merchant, amount and expiry. A local approval object is not a Stripe token; no Stripe integration is required. |
| [Google AP2 announcement](https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol) and [current AP2 specification](https://ap2-protocol.org/ap2/specification/) | Verifiable checkout/payment authority and receipts support agent payments. The specification leaves dispute-resolution procedures and evidence retention/retrieval requirements outside its scope. | Preserve authorization and outcome evidence together. Call the design AP2-inspired unless it actually implements a pinned specification and its verification requirements. |
| [Google UCP explanation](https://developers.googleblog.com/under-the-hood-universal-commerce-protocol-ucp/) and [order specification](https://ucp.dev/specification/shopping/order/) | Commerce includes order management and post-purchase updates; order reconciliation is already a protocol concern. | Give adapters separate order lookup and event methods. The contribution is the implemented consumer recovery experience, not discovering that post-purchase events exist. |
| [Mastercard Agent Pay](https://newsroom.mastercard.com/news/press/2025/april/mastercard-unveils-agent-pay-pioneering-agentic-payments-technology-to-power-commerce-in-the-age-of-ai/) | Registered agents, tokenization and consumer control are established industry themes. | Record the acting identity and the approval. Application authentication does not make the agent Mastercard-registered. |
| [Visa Intelligent Commerce](https://corporate.visa.com/en/products/intelligent-commerce.html) | Agent payments require credentials, controls and authentication. | Keep payment credentials out of model context and distinguish recommendation from authorization. No Visa integration or protection is implied. |
| [PayPal agentic commerce services](https://developer.paypal.com/agentic-commerce-services/about/) | Product discovery, cart operations and checkout are available through merchant-facing services with onboarding. | Use supported adapter contracts instead of assuming access to every storefront. PayPal onboarding is outside the critical path. |
| [AWS AgentCore Payments GA, 18 August 2026](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-payments-is-now-generally-available-enabling-agents-to-transact-safely-and-autonomously-at-scale/) | Stablecoin wallet integration, x402/MPP payments, infrastructure-enforced spending limits and observability. | A timely rationale for separating model reasoning from financial controls. It does not establish native UPI settlement or recovery. Keep direct integration outside this MVP. |

Use three references in the spoken pitch: AP2 for authorization evidence, AWS for deterministic controls, and an official Indian source for recovery routing. Put the full comparison in the README. Mentioning eight companies in the video consumes time needed to demonstrate the product.

The competitive comparison should also acknowledge Mastercard's subsequent [Verifiable Intent announcement](https://www.mastercard.com/mt/en/news-and-trends/stories/2026/verifiable-intent.html): recording identity, instructions and purchase evidence is already an explicit industry direction. This reinforces the choice to differentiate on a working, understandable recovery workflow. For Visa, consult its [current product page](https://www.visa.com/en-us/solutions/intelligent-commerce) alongside announcements; described capabilities do not guarantee access or universal availability.

The name is **AP2**, distinct from Google's A2A agent-communication protocol. Pin protocol versions if implementation is later attempted; launch-blog terminology can differ from current specifications.

## Recovery correctness

Maintain separate facts for payment, order, refund/reversal and case progress. A user-provided SMS, payment-processor status and merchant order record are different evidence sources.

| Observed situation | Application behavior |
| --- | --- |
| Request timed out; payment outcome unknown | Retain original attempt and reservation; query status; block a new attempt through this purchase flow. |
| Payment authoritatively failed with no debit exposure | Close the attempt; release the application reservation when appropriate; require fresh approval to try again. |
| Account debit reported but payment/order outcome unclear | Preserve the discrepancy; do not equate a failed screen with money returned. |
| Payment confirmed; order missing | Query the merchant and open an order-reconciliation case. Do not automatically label every such case a failed UPI transaction. |
| Refund requested or approved | Track it as pending; display completed refund only with corresponding evidence. |
| Duplicate or contradictory callbacks | Deduplicate by provider event ID; preserve conflicting observations and reconcile against authoritative status. Never apply last-arrival-wins blindly. |

A spending reservation inside this app is not a hold placed on a bank account. Releasing it is not a refund. The app cannot prevent the user paying again through another UPI application.

Use reviewed, versioned guidance records with a rule identifier, applicability conditions, official URL, checked date and required facts. Deterministic classification selects the applicable guidance; the model explains it. When the payment category or outcome is unknown, request missing information instead of inventing a deadline.

For example, RBI's [failed-transaction circular and annex](https://m.rbi.org.in/commonman/English/Scripts/Notification.aspx?Id=3074) distinguish domestic UPI transfers where the beneficiary is not credited (reversal by T+1 if credit cannot be completed) from merchant payments where transaction confirmation is not received (T+5). The specified compensation is ₹100 per day beyond the respective deadline; T is the calendar transaction date. These are conditional incident categories, not a universal deadline for every missing grocery order. This review found no replacement of those UPI rows.

For a payment/order mismatch, first establish which category applies and prepare the relevant provider/merchant inquiry. Link the [NPCI complaint facility](https://www.npci.org.in/register-a-complaint) where appropriate. Current Ombudsman filing deadlines need a separate final source check: the reviewer found an updated [official RBI FAQ](https://old.rbi.org.in/commonman/english/scripts/faqs.aspx?id=3407), but the full page was challenge-blocked on retrieval. Do not ship a deadline calculator based on remembered 2021 rules or unverified indexed text. This does not block the source-linked inquiry and evidence-export MVP.

The old NCH statistic in the candidate document must not be presented as a current UPI transaction failure rate. The linked historical report could not be fully fetched in this review. Use a verified historical denominator if retaining it, or omit the number and validate the problem with user interviews.

## Minimal Ship It architecture

| Component | Responsibility |
| --- | --- |
| React/TypeScript on Amplify Hosting | Comparison, approval, status and evidence UI. |
| Cognito | Authenticated human identity; never trust a user ID passed by the model. |
| API Gateway and Python Lambda | Public APIs, typed tools, quote calculations, approval and callback validation. |
| Strands with a Bedrock model | Interpret requests, invoke read tools, explain matching offers and grounded recovery guidance. |
| Amazon Verified Permissions/Cedar | Decide whether this identity can execute the approved purchase or view/export this case. |
| Step Functions Standard | Bounded durable agent jobs and checkout/reconciliation workflows; explicit waits and failure branches. |
| DynamoDB | Quotes, approvals, attempts, independent statuses, callback inbox and append-only application events. |
| S3 | Versioned guidance and private exported evidence artifacts. |
| CloudWatch; SAM infrastructure definitions | Correlated operational traces and repeatable deployment. |

The asynchronous request API starts a durable job and returns a job/transaction identifier after acceptance. The UI reads persisted progress. Run bounded Strands calls in Lambda through the workflow; do not hold an HTTP request open across model calls or approval waits. Approval can be persisted separately and then start the checkout workflow, avoiding a task-token handoff as a required feature.

Use a bounded Step Functions Wait/query loop for reconciliation. Callback ingestion validates signatures, checks references/amounts, and persists the inbox event before acknowledgement. Reconciliation consumes durable observations and queries provider status. This avoids requiring EventBridge or SQS for the prototype. After the automatic polling window, keep the case unresolved and expose a safe status-refresh action; do not claim indefinite background monitoring unless implemented.

[Standard workflows](https://docs.aws.amazon.com/step-functions/latest/dg/choosing-workflow-type.html) suit durable execution and visible history. Their execution semantics do not eliminate ambiguous external payment side effects. [DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html) support atomic local changes, but they cannot atomically commit a remote provider charge. [Verified Permissions](https://docs.aws.amazon.com/verifiedpermissions/latest/userguide/what-is-avp.html) supplies authorization decisions; it does not provide settlement or database locks.

### Transaction core contract

- Store PurchaseIntent, QuoteVersion, Approval, PaymentAttempt, OrderObservation, EvidenceEvent and RecoveryCase. Track refunds independently when present.
- Express INR amounts in paise. Canonicalize the full approval payload before hashing, including all purchase terms whose change requires consent.
- Atomically consume a valid approval, reserve the purchase and create a unique attempt. Enforce approval/version conditions at the write boundary, not only during an earlier read.
- Use a stable provider idempotency key for the attempt. Persist it before the external call. A retry must reuse that identity or query its outcome.
- If the provider acted but the response was lost, retain uncertainty and reconcile. Never start a new payment because a worker restarted.
- Maintain durable application idempotency records. DynamoDB's request token window is not a permanent replay defense.
- Make simulator side effects persistent and independently countable. Replaying a callback or transport request must not create another simulated charge/order.
- Authorize case access before evidence reaches the model and again before export. Redaction is implemented by an explicit field allowlist and user review; Cedar decides permission, not text redaction.
- Give each record source/provenance and observation time. A hash can detect a changed payload under the stated trust model; it does not prove bank settlement or non-repudiation.

No OpenSearch is required for a handful of guidance documents and a transaction-keyed timeline. No AgentCore Payments, custom VPC/NAT or always-running search cluster is necessary. Add AgentCore Runtime only if hosting needs justify it after the required flow works.

Set a small planning spend envelope, for example $25–$50 for development and demonstration, then estimate against actual selected services, region and model. This is a team budget target, not a verified bill forecast. Confirm the credited account and available model before development, cap model/tool calls and workflow retries, avoid tight polling, and remove unused resources after judging. Do not assume participant credits can all be pooled into one account.

## Reuse strategy

The organizer has allowed reuse. A fresh repository is an organizational choice; the valuable engineering decision is which code to carry forward.

Prefer the team's existing presentational components, design tokens, typed product shapes and genuinely pure normalization helpers after checking their dependencies. Adapt merchant interfaces and pause/resume concepts. Rebuild approval validation, wallet/payment execution, concurrency handling, callbacks and recovery persistence against explicit contracts.

Do not migrate SQLite wallet balances into a pretend UPI integration. Do not preserve fallback code that silently turns a failed real operation into a successful demonstration result. Display mock mode explicitly.

Source review is not runtime validation. Neither existing application was executed during this panel review. Exact reusable files and observed hazards are listed in the code-review appendix below.

### Code-review appendix

| Inspected source | Observed behavior | Reuse decision |
| --- | --- | --- |
| [GenPay routes/agent.py](https://github.com/Shubhank165/GenPay/blob/main/backend/app/routes/agent.py) | Local catalog options and local wallet SUCCESS records; new state per query; demonstration PIN in the route. | Adapt response shapes and pure helpers after review. Replace payment and credential paths. |
| [GenPay core/graph.py](https://github.com/Shubhank165/GenPay/blob/main/backend/app/core/graph.py) | Planning, risk and execution nodes; confirmation depends on risk; no durable checkpointer supplied in the inspected compilation. | Use as a conceptual reference for tool separation. Replace with bounded Strands jobs and durable transaction state. |
| [MiraclePay orchestrator.py](https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/modules/paybot/orchestrator.py) | Gemini function calls, sessions and pause/resume; broad exception handling can enter the mock loop, which generates new order IDs. | Adapt session/tool schemas. Rewrite execution routing so a failure cannot silently launch another purchase path. |
| [MiraclePay shopping_agent.py](https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/modules/paybot/shopping_agent.py) | Seeded catalog, first fuzzy match, error line items for missing products and simulated signatures. | Adapt fixture structure. Rebuild complete-basket checks, pack normalization, delivered totals and quote versions. |
| [MiraclePay grocery_crawler.py](https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/crawlers/grocery_crawler.py) | Playwright searches with explicitly labeled static fallback data. | Defer crawling. Neither source inspection nor fallback data proves live merchant checkout. |
| [MiraclePay hitl.py](https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/modules/paybot/hitl.py) | Approval fields and expiry exist; pending approval is read before an unconditional update; some audit writes follow commit. | Reuse interaction ideas. Replace with authenticated quote binding and conditional approval consumption. |
| [MiraclePay payment_agent.py](https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/modules/paybot/payment_agent.py), [wallet.py](https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/wallet.py), [db.py](https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/db.py) | Local transfer precedes budget update on another connection; transfer commits before audit; order ID lacks a uniqueness constraint in the inspected table; x402 is a stub. | Replace this core. Existing comments do not establish atomic payment/budget/audit behavior or safe provider replay. |
| [MiraclePay merchant UI adapters](https://github.com/vanshikaxcx/MiraclePay/blob/main/paytm%20ui/src/adapters/index.ts) | Forced single demo merchant and normalization to seller_a. | Reuse interface ideas only; remove forced identities before policy checks. |

Individual consumer UI components were not audited. Their reuse is a promising candidate, not a verified estimate of code saved. Both repositories lacked an identified LICENSE file in the review; this does not prevent using the team's own code, but check third-party contributions and assets. Record source repository, commit, reused path, changes and attribution in the new repository. Do not invent a reuse percentage.

A suitable new module layout is `web/`, `backend/contracts.py`, `backend/agent.py`, `backend/quotes.py`, `backend/approval.py`, `backend/payments.py`, `backend/callbacks.py`, `backend/reconcile.py`, `backend/evidence.py`, `backend/adapters/`, `backend/simulator/`, `policies/`, `guidance/`, `infra/template.yaml`, `workflows/` and `tests/scenarios/`. This is a planning layout, not files created before the event.

## Four-person, four-day plan

| Owner | Main workstream | Interface boundary |
| --- | --- | --- |
| 1: frontend | Adapt selected UI; approval/status/case screens; record demo | Uses agreed API schemas and synthetic fixtures. |
| 2: agent and merchants | Strands/Bedrock, typed intent, two merchant adapters, explanations | Produces quotes; cannot approve or execute payment. |
| 3: transaction backend | DynamoDB, approval binding, idempotency, simulators, reconciliation | Owns state transitions and invariant tests. |
| 4: AWS and recovery | SAM deployment, Cognito/AVP, Step Functions wiring, guidance/export | Integrates closely with owner 3 on workflow and permissions. |

During the event, freeze schemas first and integrate daily. Owner labels are responsibility boundaries, not isolated four-day branches.

| Day | Required exit condition |
| --- | --- |
| 1 | New repository with disclosed reuse, deployed authenticated skeleton, merchant quotes and persistent transaction IDs. |
| 2 | Full happy path on AWS: request, exact approval, one simulated charge and confirmed order. |
| 3 | Timeout, late success/order mismatch, replay protection, recovery case and export; complete failure tests. |
| 4 | Feature freeze, repair failures, test fresh login/refresh, record video, document measured behavior and submit early. |

If cloud access is a persistent blocker by day two, use the same product scope with local Strands/Cedar, a transactional database and local APIs for Build It. Do not spend the remaining event reproducing the whole AWS cloud through emulators. If engineering time is the blocker, reduce discovery to one fixed basket before cutting recovery correctness.

## Acceptance and demonstration

Required tests: exact approval enforced; changed/expired quote rejected; two concurrent submits create one logical attempt; duplicate callback has one effect; timeout preserves uncertainty; late success reconciles the original attempt; payment success does not imply order success; restart retains state; another user cannot access/export evidence; refund pending is not shown as refunded; export matches recorded facts.

Include a crash immediately after the simulator accepts payment but before the application records success. Recovery must query the same attempt and preserve the single provider effect. This is stronger evidence than testing repeated button clicks alone.

Also exercise a merchant description containing an instruction to bypass approval. The trusted payment tool must reject the unauthorized action regardless of how the model responds. Report the particular test outcome, not general immunity to prompt injection.

| Video time | What to demonstrate |
| --- | --- |
| 0:00–0:20 | Familiar problem and a grocery request. |
| 0:20–0:45 | Comparable basket totals and exact approval. |
| 0:45–1:20 | Independent simulator causes timeout; refresh page and attempt again; original attempt persists. |
| 1:20–2:05 | Late payment success, order still missing; show the correct discrepancy and reconciliation. |
| 2:05–2:35 | Recovery case, cited next step, reviewed evidence export. |
| 2:35–3:00 | Actual Step Functions execution, authorization decision and measured replay result. |

Keep “Demo merchants · simulated payment · no money moved” visible. Present event timestamps as recorded rather than staging unrelated UI messages. If a simulated refund is shown, advance it through an independent provider event and label it accordingly.

Before the event, conduct a few voluntary interviews about actual purchase/payment confusion without collecting sensitive records. During the event, test whether participants can correctly answer: “Was I charged?”, “Do I have an order?”, and “What should I do next?” Record observed results and limitations. Industry references support the design; the working fault demonstration and user feedback support the solution.

## Submission pitch

> ProofPath helps shoppers carry a grocery purchase from exact approval to a known outcome. When payment and order status disagree, it reconciles the original attempt, prevents another attempt within the unresolved purchase flow, and prepares a source-backed recovery case. Strands and Bedrock interpret the task; Cedar governs sensitive actions; Step Functions and DynamoDB preserve the transaction through failures. Our demonstration uses explicit merchant and payment simulators to show repeatable failure recovery without moving money.
