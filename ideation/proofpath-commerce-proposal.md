# ProofPath Commerce: purchase assistance, explicit consent, and payment recovery

Planning draft — 11 September 2026. No implementation is proposed before the hackathon opens.

## Eligibility decision

First Commit's published rules exclude prior projects, including rewrites. Extending GenPay or MiraclePay and adding AWS components is therefore not an eligible submission under the published wording. A new repository alone does not resolve this.

The proposed new project is a standalone transaction-consent and recovery system, with a small newly built shopping demonstration. Because it overlaps with earlier agentic-commerce work, obtain an organizer ruling before treating it as eligible. Disclose the existing repositories and what the new project will contain. This document is planning, which the rules allow.

Organizer question to send: “We previously built GenPay and MiraclePay for another event. We propose a new standalone transaction-consent and payment-recovery project during First Commit, using Strands and Cedar, with a newly built simulated grocery checkout for demonstration. We would disclose the prior projects and use none of their project code or assets. Does this qualify as a new project under your prior-work rule?”

Source: https://www.wemakedevs.org/aws/rules

## Problem statement

Buying an everyday item online requires a person to translate their needs into searches, compare quantities and delivered prices, choose a merchant, check a cart, and complete payment. When payment status is unclear or payment succeeds without an order confirmation, that same person must reconstruct what happened from separate screens, references, receipts, and support conversations.

An assistant that executes these tasks also needs a precise boundary around the user's financial intent. Approval of one basket must not authorize a different amount, merchant, or purchase. A timeout must not cause the assistant to charge again, and a payment acknowledgement must not be confused with successful order creation.

How can an assistant carry an everyday purchase from intent to a verified outcome while preserving explicit user control and the evidence needed to resolve failures?

These are problem hypotheses and design requirements, not quantified claims of validated demand. Before the event, interview potential users about a recent purchase or failed-payment experience without collecting sensitive financial records.

## Proposed solution

ProofPath Commerce is a local application that prepares a purchase, obtains approval for its exact terms, and follows the payment and order through to a verified outcome. If a transaction remains unresolved, it retains a structured evidence record and helps the user prepare the appropriate support request.

The broader product can support groceries, flights, and hotels through separate connectors. The hackathon demonstration supports groceries only. Compare two explicitly labeled test merchants using fixture catalogs and an executable payment simulator. This demonstrates working orchestration without claiming live merchant relationships or access to every website.

Primary user: a student or busy household shopper buying a small grocery basket under a fixed budget. Example request: “Find 5 kg rice and 1 litre oil for under ₹900 including delivery. Show me the options before paying.”

## Core user journey

1. Interpret the request into item, quantity, budget, and delivery constraints. Ask only about material missing choices.
2. Query two merchant adapters. Compare matching pack sizes, availability, delivery fees, and final totals. Mark substitutions explicitly. Say “best among connected sources” and show when quotes were retrieved.
3. Present the recommended basket and alternative with understandable reasons. The user selects the basket.
4. Produce an approval card with merchant, products, quantities, total, delivery details, quote expiry, and relevant cancellation terms. The user approves that exact version.
5. The backend records approval, checks authorization, and initiates the payment once. A real integration would hand authentication to the provider's checkout; the assistant never asks for a payment PIN or OTP in chat.
6. Reconcile provider payment status and merchant order status separately. Show “payment pending,” “paid, order confirmation pending,” or “order confirmed” as appropriate.
7. When unresolved, open a recovery case containing the approved quote, payment/order references, timestamps, provider responses, and event history. Explain known facts and missing information. Prepare a redacted complaint packet for the user's review and export.
8. Update the case when new evidence arrives. Record confirmed failure, confirmed order, or verified refund only when the corresponding adapter supplies evidence. Otherwise leave the case unresolved.

## What connects commerce and recovery

Use a shared transaction record rather than a separate recovery chat. Its related records are PurchaseIntent, QuoteVersion, Approval, PaymentAttempt, Order, EvidenceEvent, and RecoveryCase.

Payment and order are separate state machines. Payment can be not started, pending, succeeded, failed, or unknown; order can be not created, pending, confirmed, or failed. A recovery case has its own status, and a refund is tracked separately. Do not overload a single SUCCESS flag.

The approval contains authenticated user identity, quote ID/version, merchant, amount in currency minor units, currency, expiry, and an immutable description/hash of the approved purchase. Trusted backend code creates and verifies it. Model-generated text cannot create consent.

Before execution, revalidate the quote and atomically reserve the approved attempt. Changed amount, merchant, or basket requires fresh approval. Use an idempotency key for repeated transport submissions of the same attempt; a genuinely new attempt gets its own identity and fresh approval. A pending or unknown attempt must be reconciled before permitting another purchase attempt. This is an application guard, not a promise of exactly-once behavior across all providers.

Authenticate callbacks, compare references and amounts, deduplicate repeated events, and reconcile contradictory or late notifications with the provider. For the local demo, implement equivalent signatures and status queries in the simulator. Provider-specific real integration requirements remain future work.

## AWS Build It architecture

| Component | Concrete responsibility |
|---|---|
| Web interface | Request, comparison, exact approval card, status timeline, recovery case |
| Strands Agents SDK + a local Ollama model | Parse intent; invoke typed search/retrieval tools; explain comparisons and recovery evidence |
| Cedar | Authorize quote approval, payment execution, case viewing, and evidence export using trusted request context |
| Deterministic backend | Amount calculations, quote validation, approval verification, atomic transitions, idempotency, and callback checks |
| SAM Local | Expose local Lambda-backed workflow and callback APIs |
| SQLite | Transactional source of truth for approvals, payment attempts, orders, and event records |
| OpenSearch | Retrieve merchant terms and recovery guidance; search authorized evidence with source references |
| Two merchant adapters and one payment simulator | Executable local contracts and controllable failure scenarios |

Keep the Strands runtime as a local service if long model calls make request handling awkward. The language model proposes actions; backend checks decide whether those actions execute. Cedar returns authorization decisions; it does not verify payment settlement, provide authentication, or replace database concurrency controls.

Apply authorization before retrieving sensitive evidence for the model and again before viewing/exporting records. Do not retrieve all users' cases and rely on a prompt to hide them. Store guidance sources with retrieval dates, and separate official provider instructions from simulated merchant policies.

SAM Local, Strands, Cedar, and OpenSearch provide meaningful AWS ecosystem usage. LocalStack is optional if S3/SQS emulation becomes useful; do not make another dependency essential just to increase the tool count. The core demo can run locally after dependencies and model weights are installed. Live merchant discovery and real payments require connectivity.

Technical references:
- https://strandsagents.com/docs/learning/switching-model-providers/
- https://docs.cedarpolicy.com/auth/authorization.html
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/using-sam-cli-local-start-api.html
- https://business.paytm.com/docs/callback-and-webhook/
- https://business.paytm.com/docs/miniapps/payment-flow

## Four-day scope

Required: one grocery workflow; two test merchants; explicit quote-bound approval; enforced Cedar checks; persistent transaction state; source-backed explanation; payment/order reconciliation; recovery case and redacted export; a clear working UI.

Required scenarios: successful payment and order; timeout followed by later success; definitive payment failure; successful payment without a confirmed order; duplicate callback; changed quote after approval.

Deferred: flight/hotel bookings, universal web browsing, real money, autonomous dispute submission, automatic refund promises, voice, multiple Indian languages, merchant onboarding, lending, and a full wallet app. One extra language or permitted live read-only source is stretch work only after the required scenarios pass.

Day 1: create the new repository when the event opens; implement contracts, fixtures, state persistence, and a basic request-to-quote path. Start Strands/Cedar wiring early.

Day 2: complete comparison, approval card, policy enforcement, and one successful simulated checkout. Test changed quote and duplicate execution behavior.

Day 3: implement reconciliation, failure injection, recovery evidence, source retrieval, export, and restart recovery. Test authorization boundaries and delayed notifications.

Day 4: simplify the UI, run the scenario matrix, verify clean setup, record the three-minute demo, finish the public README and write-up, and submit with time to spare.

## Acceptance criteria

- No simulator payment execution without a valid backend-recorded approval.
- Changing merchant, basket, currency, or total invalidates approval for execution.
- Repeating the same submission produces one logical payment attempt in the tested simulator workflow.
- A timeout leaves an unresolved state, rather than automatically initiating another payment.
- A late success reconciles the original attempt without creating another order.
- Payment success without order confirmation creates a visible unresolved-order case.
- Duplicate callbacks do not duplicate effects; conflicting events trigger reconciliation.
- A process restart preserves pending attempts and recovery cases.
- Another user cannot retrieve or export the case, including through agent tools.
- Recovery text cites recorded evidence and guidance, and marks unknown outcomes explicitly.

Report measured results on this test set and the actual demo machine; do not claim production reliability or invented savings percentages.

## Demo and pitch

0:00–0:20: explain the shopper's problem and enter the grocery request.
0:20–0:55: show two offers, comparable quantities, and the delivered total.
0:55–1:20: show exact approval; briefly demonstrate Cedar denying execution before approval.
1:20–2:05: initiate the simulated payment, inject a timeout, show pending status and blocked duplicate purchase, then reconcile a late success with missing order confirmation.
2:05–2:40: open the recovery case with the original approval and transaction evidence; export the support packet. Clearly label simulated provider events.
2:40–3:00: show the AWS components, test results, and what the team learned.

Submission pitch: “ProofPath Commerce helps a shopper move from a grocery request to a verified purchase outcome. It compares offers from connected merchants, requires approval for the exact basket, and tracks payment and order status separately. If something goes wrong, it preserves the evidence and prepares a recovery case. The local prototype uses Strands for task orchestration, Cedar for action authorization, SAM Local for workflow APIs, and OpenSearch for cited guidance and evidence retrieval.”

## Reference review boundaries

The supplied two-page Fin-O-Hack PDF describes broad AI-for-users and AI-for-small-businesses tracks. It does not specify universal shopping or a detailed payment-agent architecture.

GenPay and MiraclePay are reviewed as prior-work context. Neither their existence nor a README feature claim proves functioning live payments, broad merchant coverage, or recovery. Source inspection results should be distinguished from runtime testing; no repository code was executed for this review.

### GenPay findings

The inspected agent endpoint searches local Flight/Hotel tables and returns options; that branch does not create reservations. Payment/recharge branches write local wallet debits and successful ledger records. The inspected graph makes confirmation conditional on risk and rebuilds state on a subsequent query. No durable quote-bound approval or recovery case was established by these files. Some deeper tool/node sources could not be fetched, so this is not a repository-wide absence claim.

- https://github.com/Shubhank165/GenPay/blob/main/backend/app/routes/agent.py
- https://github.com/Shubhank165/GenPay/blob/main/backend/app/core/graph.py

### MiraclePay findings

The repository presents ArthSetu, including a separate consumer commerce application. Its orchestrator uses Gemini when configured and deterministic mock flows otherwise. It has pause/resume and approval machinery, but autonomous and amount-based modes do not implement universal explicit payment approval.

Playwright grocery crawlers attempt Blinkit, Zepto, and BigBasket searches and can return labeled static fallback data. They were not run in this review. The inspected comparison totals item sticker prices without complete delivered-cost or package-size normalization. Seeded shopping functions and simulated merchant signatures support demonstrations; the crawler itself does not establish live platform checkout. The payment agent calls a local wallet transfer, and its x402 function is a stub. The merchant UI adapter is forced to a demo merchant, with selected OCR/voice exceptions. A full failed-payment reconciliation and evidence workflow was not established in the inspected commerce files.

- https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/modules/paybot/orchestrator.py
- https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/crawlers/grocery_crawler.py
- https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/modules/paybot/shopping_agent.py
- https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/modules/paybot/payment_agent.py
- https://github.com/vanshikaxcx/MiraclePay/blob/main/Agentic%20Commerce%20app/agentic%20commerce/backend/modules/paybot/hitl.py
- https://github.com/vanshikaxcx/MiraclePay/blob/main/paytm%20ui/src/adapters/index.ts

The proposed differences are complete basket comparison, mandatory exact approval, durable separate payment/order states, and evidence-based recovery. These differences support product reasoning; only organizers can settle eligibility given the prior projects.
