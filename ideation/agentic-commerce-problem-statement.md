# Trustworthy Agentic Commerce on AWS

## The shift from assisted shopping to delegated buying

Online commerce was designed around a human operating every step. A person searches for a product, compares alternatives, chooses a merchant, reviews the cart, enters payment details, and confirms the transaction.

AI agents are changing that model. A consumer can now describe an outcome such as:

> Find the cheapest 2 kg atta and 1 litre milk that can arrive today, recharge my Jio number with a 28-day plan, and keep the total below Rs.600.

An agent can translate that request into several tasks, search multiple providers, compare price and availability, make selections, and initiate payment. The interface is no longer a catalogue or checkout page. It is a delegated instruction.

The technology for discovery and reasoning is developing quickly. The unresolved problem begins when the agent is allowed to act and spend.

## The problem

Payment and commerce systems still assume that a human directly controls each checkout. They are not designed for a probabilistic software agent that can interpret instructions, call external tools, and execute several transactions across different merchants.

Giving an AI agent unrestricted access to a wallet or payment credential creates serious risks:

- The agent may misunderstand an ambiguous instruction.
- A merchant listing may contain malicious or misleading content intended to manipulate the agent.
- The agent may select an incorrect product, merchant, quantity, date, route, or subscription.
- A delayed merchant response may cause the agent to retry and pay twice.
- Two agent sessions may spend from the same budget concurrently.
- A price may change after the user has approved an order.
- An approval may be reused after its expiry or for a different transaction.
- A compromised tool may attempt a purchase outside the user's original request.
- When something goes wrong, the consumer, merchant, and payment provider may not be able to determine which party authorized which action.

Existing shopping assistants usually address this by stopping before payment and returning the user to a conventional checkout page. That preserves safety, but it also removes the main value of an agent: completing a multi-step outcome on the user's behalf.

The core challenge is therefore not product search or conversational checkout. It is **safe delegation of commercial authority**.

## Full problem statement

AI agents can discover products, compare offers, and make purchasing decisions, but consumers do not have a reliable way to grant them narrowly bounded and verifiable spending authority.

A consumer needs to specify what an agent may purchase, which merchants and categories it may use, how much it may spend, how long the permission remains valid, and which decisions require human approval. These constraints must be enforced independently of the language model so that an agent cannot bypass them through faulty reasoning, prompt injection, or a compromised tool.

At the same time, an agentic purchase is a long-running distributed transaction. It may depend on inventory systems, booking providers, merchant APIs, approval from the consumer, and a payment service. Any of these systems can respond slowly, fail, or return an uncertain result. The transaction must resume safely without losing state, exceeding the budget, or charging twice.

Consumers, merchants, and payment providers also need a shared record that explains:

- What the consumer originally asked for
- What authority the consumer granted
- Which offers the agent considered
- Why the agent selected a particular offer
- Which policy permitted or rejected each action
- When human approval was requested and received
- Whether the payment succeeded, failed, timed out, or was reversed

The problem is to create a trustworthy agentic commerce system that converts human intent into enforceable spending authority and safely coordinates discovery, selection, approval, payment, failure recovery, and audit across multiple commerce providers.

## Why this is an emerging industry problem

Agentic commerce has moved beyond research prototypes:

- OpenAI and Stripe introduced Instant Checkout and the Agentic Commerce Protocol so agents and merchants can complete purchases through a standard interface.
- Stripe introduced Shared Payment Tokens that are limited by merchant, amount, and time instead of exposing the customer's underlying payment credential.
- Google introduced the Agent Payments Protocol to provide cryptographically verifiable mandates for agent-initiated payments.
- Google later introduced the Universal Commerce Protocol for interoperable discovery, checkout, and post-purchase experiences.
- Mastercard Agent Pay focuses on registered agents, agentic payment tokens, consumer controls, and traceable transactions.
- Visa Intelligent Commerce provides credentials, controls, authentication, and protections for AI-initiated purchases.
- PayPal now provides agentic commerce services covering product discovery, cart management, and checkout.
- AWS has introduced Amazon Bedrock AgentCore Payments for agents purchasing paid APIs, MCP tools, content, and services through x402.

These companies are solving different parts of the ecosystem. Their work demonstrates that agentic commerce requires more than a capable model. It requires verifiable intent, constrained credentials, agent identity, transaction safety, interoperable merchant access, and complete observability.

Primary references:

- [OpenAI: Instant Checkout and Agentic Commerce Protocol](https://openai.com/index/buy-it-in-chatgpt/)
- [Stripe agentic commerce documentation](https://docs.stripe.com/agentic-commerce)
- [Google Agent Payments Protocol](https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol)
- [Google Universal Commerce Protocol](https://developers.googleblog.com/under-the-hood-universal-commerce-protocol-ucp/)
- [Mastercard Agent Pay](https://newsroom.mastercard.com/news/press/2025/april/mastercard-unveils-agent-pay-pioneering-agentic-payments-technology-to-power-commerce-in-the-age-of-ai/)
- [Visa Intelligent Commerce](https://corporate.visa.com/en/products/intelligent-commerce.html)
- [PayPal agentic commerce services](https://developer.paypal.com/agentic-commerce-services/about/)
- [Amazon Bedrock AgentCore Payments](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-payments-is-now-generally-available-enabling-agents-to-transact-safely-and-autonomously-at-scale/)

Razorpay should be described as a potential Indian payment integration unless an official source confirms a specific agentic commerce product or protocol implementation.

## Who faces this problem

### Consumers

Consumers want an agent to complete repetitive or time-consuming purchases without surrendering control over their money. They need clear limits, meaningful approval points, and a way to understand what the agent did.

### Merchants

Merchants need to distinguish an authorized shopping agent from a malicious bot. They also need structured requests, authenticated agent identity, reliable payment confirmation, and protection against duplicate or disputed orders.

### Banks, wallets, and payment providers

Payment providers need evidence that a transaction was within the consumer's mandate. Existing fraud systems can identify suspicious payment behaviour, but they do not automatically prove that an agent correctly followed a natural-language instruction.

### Agent developers

Agent developers currently have to build custom authorization, approval, credential, retry, and audit logic around every merchant and payment integration. Small mistakes in this infrastructure can move real money.

## Proposed solution

### ArthSetu PayBot

ArthSetu PayBot is a policy-governed agentic commerce system for everyday Indian purchases. It allows a user to delegate a commercial task while retaining explicit control over the agent's authority.

The user provides an outcome in natural language. PayBot converts it into a structured spending mandate containing:

- Permitted products or services
- Maximum total budget
- Permitted categories
- Permitted or blocked merchants
- Validity period
- Quantity and delivery constraints
- Human-approval rules
- Agent and user identity

The user reviews and confirms this mandate. The commerce agent can then search, compare, and propose transactions within it. Every consequential action is checked by a deterministic policy engine before execution.

The model may decide which tools could achieve the user's goal. It cannot decide whether it is authorized to spend.

## Example experience

The user says:

> Recharge my Jio number with the best 28-day plan below Rs.300. Buy atta and milk from the cheapest available provider. Do not spend more than Rs.600 in total.

PayBot performs the following steps:

1. Converts the instruction into a Rs.600 mandate covering telecom and grocery purchases.
2. Shows the mandate to the user before activating it.
3. Searches recharge plans and grocery providers.
4. Selects a Rs.239 recharge that satisfies the deterministic constraints.
5. Executes the recharge automatically because it is below the user's approval threshold.
6. Compares grocery offers and prepares a frozen quote.
7. Requests approval because the cumulative transaction crosses the configured threshold.
8. Verifies that the approved quote has not changed.
9. Reserves the remaining mandate budget atomically.
10. Executes the payment with an idempotency key.
11. Records the mandate, policy decisions, approval, payment, and final receipt in a readable timeline.

If a provider times out, PayBot checks the existing payment state before retrying. If the purchase cannot complete, it releases the budget reservation. If the same request is replayed, it returns the original result without charging again.

## How the complete agentic commerce project fits

The existing project already demonstrates four commerce domains:

- Grocery discovery and cross-platform price comparison
- Mobile recharge plan selection
- Movie discovery and show selection
- Train search and travel-class selection

These should be presented as domain adapters connected to one shared agentic transaction system. They should not be framed as four independent product features.

Each domain demonstrates a different form of delegation:

| Domain | Agent behaviour | Human involvement |
| --- | --- | --- |
| Mobile recharge | Finds the best deterministic match | May execute automatically within a low-risk mandate |
| Grocery | Compares price, quantity, and availability | Approval based on amount or substitutions |
| Movies | Finds suitable shows and seats | User selects among preference-sensitive options |
| Trains | Compares route, timing, availability, and class | User selects the travel option before booking |

The product is the shared mandate, policy, workflow, and audit layer. The four domains prove that it can govern different kinds of commerce.

## Why AWS is integral

The system should use AWS for product-level guarantees rather than ordinary hosting.

### Strands Agents SDK

Strands runs the commerce agent that interprets the goal, plans the task, and invokes merchant tools. The same agent can use Amazon Bedrock when deployed or a local model for a Build It demonstration.

### Amazon Bedrock

Bedrock supplies the model used for intent normalization, planning, comparison, and user-facing explanations. Model output remains outside the payment authorization boundary.

### Cedar and Amazon Verified Permissions

Cedar expresses the user's spending constraints as authorization policies. Before an agent searches restricted data, reserves an offer, or requests payment, the application asks whether that agent may perform that action on that resource in the current transaction context.

Cedar evaluates attributes such as:

- Agent identity
- User identity
- Merchant identity
- Product category
- Transaction amount
- Cumulative mandate spend
- Mandate expiry
- Risk level
- Required human approval

This separates authorization from model reasoning and application-specific conditions.

### AWS Step Functions

Step Functions coordinates the complete purchase lifecycle:

`Understand intent -> Confirm mandate -> Search -> Compare -> Select -> Authorize -> Reserve budget -> Await approval -> Pay -> Confirm -> Audit`

It provides durable state, bounded retries, timeouts, error branches, compensation, and human approval through callback tokens. A workflow can wait for the user without keeping an application process alive and then resume from the exact state where it paused.

### Amazon DynamoDB

DynamoDB stores mandates, sessions, quotes, approvals, orders, and idempotency records. Conditional writes and transactions ensure that two agent sessions cannot spend the same remaining budget and that a repeated payment request cannot create a second charge.

### Amazon EventBridge and Amazon SQS

EventBridge publishes mandate, approval, policy, payment, and order events. SQS absorbs delayed merchant or payment callbacks and sends repeatedly failing events to a dead-letter queue for investigation and recovery.

### Amazon OpenSearch Service

OpenSearch powers the user and investigator timeline across natural-language intent, agent actions, policy decisions, approvals, failures, and receipts. It makes the operation of the agent explainable without treating the model's private reasoning as evidence.

### Amazon Bedrock AgentCore

AgentCore Runtime can host the agent in isolated sessions. AgentCore Identity and Gateway can give the agent controlled access to merchant and payment tools without exposing raw credentials in model context. AgentCore Observability can connect agent and tool activity to the transaction timeline.

AgentCore Payments can support an x402 or paid MCP tool demonstration. It should not be presented as a complete UPI or consumer-fiat payment system.

### AWS Amplify, Cognito, and API Gateway

Amplify provides the live web experience. Cognito establishes the human identity behind every mandate. API Gateway exposes the mandate, approval, session, and audit interfaces.

## Mechanical AWS dependency

If Cedar is removed, spending authority returns to application conditions that can drift or be bypassed.

If Step Functions is removed, approval, timeout, retry, compensation, and recovery state must be rebuilt in application code.

If DynamoDB conditional transactions are removed, concurrent agents can reserve the same budget or repeat a payment.

If EventBridge and SQS are removed, external callbacks and failures become tightly coupled to a running process and can be lost.

If AgentCore Identity and Gateway are removed, secure tool credentials and authenticated agent access require a separate custom system.

AWS is therefore part of the product's safety and reliability model. It is not simply the location where the backend runs.

## Build It and Ship It positioning

### Recommended: Ship It

Ship It provides the strongest version of the idea because judges can use a live application and inspect real Step Functions executions, Cedar decisions, DynamoDB conditional state, EventBridge events, and failure recovery.

The deployed stack would use Strands, Bedrock, AgentCore, Verified Permissions, Step Functions, DynamoDB, EventBridge, SQS, OpenSearch, Cognito, API Gateway, and Amplify.

### Local alternative: Build It

The same core concept can run locally with:

- Strands with Ollama
- Open-source Cedar
- SAM CLI and LocalStack
- Locally emulated Step Functions, DynamoDB, EventBridge, and SQS
- OpenSearch

The local version would demonstrate the same policies, state machine, atomic budget enforcement, replay protection, and audit experience without using Bedrock or managed AgentCore services.

## Hackathon demo narrative

The three-minute video should show one continuous commerce task:

1. The user gives PayBot a multi-part instruction and a total budget.
2. PayBot creates a readable mandate and the user activates it.
3. The recharge completes automatically within policy.
4. Grocery offers are compared and a frozen quote is created.
5. The workflow pauses for human approval.
6. The user approves and payment completes.
7. A duplicate payment attempt is sent and safely returns the original result.
8. An attempted electronics purchase is rejected because the mandate permits only groceries and telecom.
9. The interface shows the policy decision, workflow state, budget usage, and audit timeline.

The video should display the Step Functions execution graph and the corresponding product UI. This makes AWS involvement visible and connects each AWS primitive to behaviour the user experiences.

## Differentiation

PayBot is not another conversational shopping interface. Product search and chat are becoming standard features across commerce platforms.

Its differentiation is the transaction boundary between a probabilistic agent and deterministic financial infrastructure:

- Natural-language intent becomes explicit authority.
- Authority is evaluated for every action.
- Payment credentials stay outside model context.
- Budget is enforced across concurrent tasks.
- Human approval is tied to the exact quote being purchased.
- Retries cannot create duplicate charges.
- Failed workflows resume or compensate safely.
- Every decision produces a readable record.

Payment networks provide payment credentials and transaction rails. Commerce protocols provide interoperable message formats. PayBot demonstrates the user-facing orchestration and enforcement layer that applies those primitives to a complete multi-domain task.

## Scope boundaries

For the hackathon, the project should not claim:

- Formal compliance or certification with AP2, ACP, UCP, Visa, Mastercard, Stripe, Razorpay, or UPI
- Custody of real card, bank, wallet, or UPI credentials
- Production financial settlement
- Reliable scraping of every third-party platform
- A complete replacement for Paytm, Razorpay, or another consumer payment application

The existing implementation should be described as AP2-inspired until its mandate signatures, identities, and protocol messages conform to the relevant specification.

## Expected impact

For consumers, PayBot makes delegation understandable and reversible. Users receive the convenience of autonomous purchasing without giving an agent unrestricted control over their money.

For merchants, it provides structured requests, agent identity, authorization evidence, idempotent transactions, and fewer ambiguous disputes.

For payment providers, it supplies the intent and execution context needed to distinguish a valid agent-initiated transaction from an unauthorized automated payment.

For developers, it provides a reusable pattern for safely connecting AI reasoning to systems that move money.

## Submission summary

**Problem:** AI agents can shop, but consumers cannot safely delegate bounded spending authority, and commerce systems cannot reliably prove that agent actions matched user intent or recover from failures without duplicate payments.

**Solution:** ArthSetu PayBot converts natural-language goals into enforceable spending mandates, governs every agent action with Cedar, runs the purchase as a durable Step Functions workflow, enforces budget and idempotency with DynamoDB, and records the transaction through EventBridge, SQS, OpenSearch, and AgentCore observability.

**AWS necessity:** AWS provides the authorization, durable execution, concurrency control, identity, event delivery, and observability guarantees that make autonomous purchasing safe enough to demonstrate.

**Demo:** One instruction completes a low-risk recharge, pauses for grocery approval, prevents a duplicate charge, rejects an out-of-scope purchase, and shows every decision in a live audit timeline.
