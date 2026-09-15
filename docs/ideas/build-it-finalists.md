# First Commit Build It: Final Idea Portfolio

**Status:** Approved research and design brief  
**Prepared:** 8 September 2026  
**Target event:** First Commit, Bharat Builds Tour 2026  
**Track:** Build It

## Executive decision

This portfolio contains three deliberately different candidates:

1. **1930 Evidence Capsule** — a direct-user product for UPI and bank-transfer fraud victims.
2. **Civic Dark-Pattern Crash Lab** — an organization-facing test system for public grievance journeys.
3. **Agent Treaty Simulator** — a developer/infrastructure system for privacy-preserving cyber-threat collaboration.

All three are designed around the same competitive principle: expose a hidden failure, enforce a non-negotiable rule, and prove the corrected outcome in one uninterrupted demonstration. They are not chatbots, dashboards, or collections of loosely connected features.

**Primary recommendation:** Build **Agent Treaty Simulator**, conditional on a successful pre-event Firecracker environment practice run. It offers the strongest combination of Build It technology depth, originality, adversarial demonstration, and Amazon engineering signal.

**First fallback:** Civic Dark-Pattern Crash Lab if Firecracker or local-agent reliability cannot be made deterministic during practice.

**Second fallback:** 1930 Evidence Capsule if the team decides that a direct human story and lower systems risk matter more than maximum infrastructure novelty.

## 1. Competition constraints

The [official First Commit page](https://www.wemakedevs.org/aws/first-commit) establishes the following:

- The event runs online from **17–20 September 2026** and permits teams of one to four.
- Build It runs locally using AWS open-source technology. Named options include Strands Agents SDK, Cedar, SAM CLI with LocalStack, OpenSearch, Firecracker, PartyRock, and Corretto.
- The judging dimensions are idea and impact, meaningful AWS usage, learning, working execution, and the recorded demonstration.
- The organizers explicitly prefer one working feature over five incomplete features.
- The submission consists of a public repository, a three-minute recorded demo, and a short write-up. There is no live judging demo.

The [tour rules](https://www.wemakedevs.org/aws/rules) add two critical boundaries:

- Planning, learning, and practice before the event are allowed, but project implementation must begin only when the event clock starts.
- AWS technology must be visible in the working project and demonstrable in the video; mentioning it in the write-up is insufficient.

This document is planning and research. It contains no competition implementation.

## 2. Evaluation method

The team assigned similar importance to four objectives:

1. Probability of winning Build It.
2. Strength as evidence for an Amazon fast-track interview.
3. Potential to become a real startup or maintained product.
4. Measurable human or organizational impact.

Every idea must also satisfy these gates:

- The decisive result can be reproduced using controlled inputs.
- No institutional partnership or private dataset is required for the prototype.
- No specialized hardware is required.
- At least one eligible AWS open-source component is structurally necessary.
- The central claim is machine-verifiable rather than a subjective AI opinion.
- The MVP can be divided among four people and completed in four days.

Scores later in this document are planning estimates, not facts or predictions of judging results.

## 3. Lessons from international hackathons

Recent first-party winner reports reveal transferable patterns:

- The ElevenLabs worldwide winner GibberLink created a memorable state transition: agents recognized one another and switched to a machine-native protocol. The lesson is that a visible mechanism change is more memorable than another result card. See the [ElevenLabs winner announcement](https://elevenlabs.io/blog/announcing-the-winners-of-the-elevenlabs-worldwide-hackathon).
- Google’s Gemma 3n winners treated offline operation as the product rather than a degraded fallback. See the [Gemma 3n winner announcement](https://blog.google/innovation-and-ai/technology/developers-tools/developers-changing-lives-with-gemma-3n/).
- Amazon’s Nova AI Challenge evaluated systems adversarially and balanced security against continued usefulness. A system that blocks everything is not successful. See the [Amazon Science results](https://www.amazon.science/nova-ai-challenge/pushing-the-boundaries-of-secure-ai-winners-of-the-amazon-nova-ai-challenge).
- The FINOS–AWS hackathon rewarded improvements to real interoperability and domain boundaries rather than a superficial standalone application. See the [FINOS event recap](https://www.finos.org/blog/open-source-in-finance-hackathon-nyc-2025-recap).

The portfolio therefore prioritizes state transitions, adversarial cases, minimum disclosure, replayable evidence, and visible enforcement.

---

# Idea 1: 1930 Evidence Capsule

## 4. The problem

UPI and bank-transfer fraud create a time-critical evidence problem after the victim realizes what happened. The relevant artifacts are often scattered across screenshots, SMS messages, call history, bank statements, payment-app screens, and handwritten notes. A frightened victim must identify transaction references, accounts or UPI handles, timestamps, amounts, communications, and suspect identifiers while avoiding accidental disclosure of unrelated private material.

The Indian Cyber Crime Coordination Centre’s [citizen financial-fraud reporting instructions](https://cybercrime.gov.in/uploadmedia/instructions_citizenreportingcyberfrauds.pdf) enumerate information needed for reporting and describe completing information on the portal after helpline contact. The [National Cyber Crime Reporting Portal](https://cybercrime.gov.in/) is the official reporting destination.

The design inference is that the portal and helpline provide the reporting channel, but a victim still needs help preparing a complete, consistent, privacy-minimized evidence package. The product must not claim that it determines guilt, reverses a payment, guarantees recovery, or replaces 1930, a bank, or law enforcement.

## 5. Affected user and failure scenario

**Primary user:** an individual who has just lost money through a UPI or bank-transfer fraud.

**Secondary user:** a trusted family member or support volunteer helping the victim prepare the report.

**Current failure scenario:**

1. The victim calls 1930 but cannot immediately locate the transaction reference.
2. Relevant messages are mixed with hundreds of unrelated personal messages.
3. Several screenshots contain contacts, balances, or conversations irrelevant to the incident.
4. Timestamps use different formats and the victim reconstructs the sequence manually.
5. A screenshot is later cropped or modified, making provenance harder to explain.
6. The victim submits incomplete or inconsistent information and must repeat work.

The meaningful outcome is not “AI detects a scam.” It is **a victim-controlled, report-ready package in substantially less time, with fewer missing fields and less unrelated data exposure**.

## 6. Proposed solution

The user imports a controlled set of artifacts:

- UPI or banking screenshots.
- Transaction and fraud-related SMS exports.
- A PDF bank statement.
- Optional call-log metadata.
- Manually entered incident details when no digital artifact exists.

The local application then:

1. Hashes each original artifact before processing.
2. Extracts candidate transaction IDs, amounts, timestamps, UPI handles, accounts, and communications.
3. Indexes exact identifiers and textual evidence into a local evidence store.
4. Links records into a proposed chronological incident timeline.
5. Marks every extracted fact with its source artifact and confidence.
6. Identifies missing report fields without inventing values.
7. Applies disclosure policies to remove unrelated messages, balances, contacts, and identifiers.
8. Produces a human-review screen showing included, withheld, uncertain, and missing information.
9. Exports a report-ready folder containing selected evidence, a manifest, hashes, timeline, and completion checklist.

The victim—not the software—reviews and submits the package.

## 7. Non-goals

- No automatic submission to 1930, the cybercrime portal, a bank, or police.
- No claim that a person or account is fraudulent.
- No prediction of whether funds will be recovered.
- No access to the victim’s entire phone.
- No cloud upload by default.
- No support for every cybercrime category in the MVP.
- No alteration of original evidence.

## 8. Domain model

**Artifact:** an original imported file or user-entered record.

**Observation:** a candidate fact extracted from one artifact, always linked back to its source.

**Incident Timeline:** an ordered collection of reviewed observations about one suspected fraud event.

**Required Field:** information the official reporting workflow expects the victim to provide.

**Disclosure Decision:** a Cedar Allow or Deny decision controlling whether an artifact or field enters the exported package.

**Report-Ready Package:** reviewed evidence, normalized metadata, integrity information, and missing-field guidance prepared for personal submission.

**Integrity Manifest:** the list of included files and their hashes. It detects later change; it does not prove that the original content was truthful.

## 9. Architecture and data flow

1. **Local intake:** the browser or desktop interface imports fixture files into a local workspace.
2. **Integrity service:** hashes originals and writes immutable metadata before extraction.
3. **Strands extraction workflow:** a local-model agent invokes narrow OCR, PDF-text, identifier, and timestamp tools. The model proposes observations; it never marks them verified by itself.
4. **OpenSearch evidence index:** stores hundreds of fixture messages and statement rows, supporting exact transaction-ID lookup, text retrieval, time filtering, and evidence clustering.
5. **Review service:** displays every proposed observation beside its source region.
6. **Cedar enforcement point:** evaluates principal, action, resource, and context before a field can be exported. For example, an unrelated contact is denied while the reported beneficiary handle is allowed.
7. **Package builder:** copies approved artifacts, applies explicit redactions to derived copies, and writes the manifest and checklist.
8. **Visual console:** shows the transformation from evidence chaos to a reviewed package.

Raw artifacts remain local. The demonstration uses synthetic data only.

## 10. Why the AWS open-source stack is essential

### OpenSearch

OpenSearch combines exact identifiers, text, time, and aggregation across a large noisy fixture set. Its [hybrid-search documentation](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/) describes combining lexical and semantic retrieval.

**Removal test:** without the evidence index, the MVP becomes a sequence of isolated extractors and loses its central ability to reconstruct a traceable timeline across many records.

### Cedar

Cedar answers whether a principal may perform an action on a resource in a supplied context. Its authorizer uses default deny and gives forbid policies precedence, as documented in [How Cedar authorization works](https://docs.cedarpolicy.com/auth/authorization.html).

**Removal test:** without Cedar, privacy minimization is a convention inside export code. With Cedar, every released field must pass an inspectable policy decision.

### Strands Agents SDK

Strands runs inside the application process and can use local model providers, as described in the [Strands quick start](https://strandsagents.com/docs/user-guide/quickstart/overview/).

**Removal test:** deterministic parsers still handle exact identifiers, but the system loses flexible cross-artifact extraction and missing-information dialogue. Strands is useful, but Cedar and OpenSearch form the stronger Build It claim.

Firecracker and Corretto are intentionally excluded from the MVP unless practice proves a concrete need. Adding sponsor tools without a removal-test justification would weaken the design.

## 11. Error, privacy, and abuse handling

- All model output is a proposal requiring source-linked review.
- Missing information remains missing; the system never fabricates a transaction ID or timestamp.
- Derived redacted copies are separated from hashed originals.
- Ambiguous matches appear as alternatives rather than being silently merged.
- Cedar denies export by default.
- The package states that a hash detects change but does not certify authenticity.
- Fixtures contain no real victim data.
- The user can remove any proposed item before export.

## 12. Controlled three-minute demo

**0:00–0:20 — Failure:** show 500 synthetic messages, six screenshots, a statement, and a timer. Ask: “Can a victim turn this into a complete report without exposing the rest of their life?”

**0:20–0:55 — Intake:** import the artifacts. Hashes appear immediately.

**0:55–1:30 — Reconstruction:** the timeline assembles around a transaction ID, amount, suspect handle, and message sequence. Each fact opens its source.

**1:30–1:55 — Privacy attack:** a tempting screenshot contains the relevant transaction plus an unrelated balance and personal chat. Cedar permits the transaction region and denies the unrelated fields.

**1:55–2:20 — Missing evidence:** the system detects that a required account detail is absent and asks the victim to review—not invent—it.

**2:20–2:40 — Tamper reveal:** modify one exported fixture. Manifest verification flips from green to red.

**2:40–3:00 — Proof:** show completion, redaction, integrity, and elapsed-time metrics; export the reviewed package.

## 13. Proposed success targets

These are MVP targets to validate, not established performance claims:

- Detect 100% of deliberately seeded required-field omissions in the demo fixtures.
- Link every included timeline fact to at least one source artifact.
- Export zero fields explicitly marked forbidden by Cedar tests.
- Detect 100% of post-manifest file modifications.
- Produce the package in under 60 seconds after extraction completes.
- Keep all raw evidence on the demonstration machine.

## 14. Four-day MVP and team split

**Day 1:** artifact schema, fixture corpus, hashing, OpenSearch mappings, and basic UI.

**Day 2:** extraction tools, Strands workflow, timeline linking, and source review.

**Day 3:** Cedar disclosure model, redacted package builder, integrity verification, and adversarial fixtures.

**Day 4:** integration, metric tests, video capture, public repository cleanup, and write-up.

Suggested lanes:

- Person 1: ingestion, hashing, and package generation.
- Person 2: extraction tools and Strands workflow.
- Person 3: OpenSearch evidence model and Cedar enforcement.
- Person 4: visual console, fixture authoring, metrics, and demo narrative.

## 15. Risks and mitigations

- **OCR errors:** use high-quality synthetic screenshots and show source review; never hide uncertainty.
- **Small search corpus:** include hundreds of synthetic irrelevant messages so retrieval is genuinely demonstrated.
- **Weak AWS story:** make the Cedar decision and OpenSearch evidence trace visible in the video.
- **Perceived legal automation:** state repeatedly that the product prepares evidence and the victim submits it.
- **Sensitive-data fear:** local-only processing and selective export are core product properties.

## 16. Expansion path

After the hackathon, adapters could support card fraud, wallet fraud, marketplace fraud, and authorized integrations with banks or reporting workflows. Real-world pilots would require security review, victim-support research, retention controls, and formal confirmation of current reporting requirements.

---

# Idea 2: Civic Dark-Pattern Crash Lab

## 17. The problem

A public digital process can appear functional in a normal developer test while failing for legitimate people with interrupted connectivity, keyboard-only navigation, Indian-script names, uncommon address formats, older devices, large attachments, or the need to resume later. Static page checks do not necessarily prove that a complete multi-step journey works.

The Department of Administrative Reforms and Public Grievances emphasizes correct handling, categorization, quality of disposal, feedback, and review in its [comprehensive grievance-handling guidelines](https://darpg.gov.in/sites/default/files/Comprehensive_guidelines_for_handling_the_Public_Grievances.pdf). The W3C’s [Web Content Accessibility Guidelines](https://www.w3.org/TR/WCAG22/) define testable accessibility success criteria, but the proposed product goes beyond a static conformance scan by replaying complete journeys under controlled disruptions.

The design does not accuse an organization of intentional deception. “Dark pattern” is the working product name; the tested domain concept is a reproducible **Journey Failure**.

## 18. Affected user and failure scenario

**Primary user:** the product, accessibility, QA, or digital-governance team responsible for a public-service journey.

**Person represented in testing:** a legitimate user attempting to submit and receive acknowledgement for a grievance.

**Current failure scenario:**

1. The ordinary desktop happy path passes.
2. A user enters a name in an Indian script and uploads supporting evidence.
3. Connectivity drops during the final step.
4. The session resumes, but the attachment or entered text has silently disappeared.
5. A keyboard-only user cannot reach the recovery control.
6. Aggregate uptime remains green although a real journey is impossible for that persona.

The meaningful outcome is **a deterministic counterexample and replay proving that a specific legitimate journey failed and later passed after correction**.

## 19. Proposed solution

The MVP contains a controlled local replica of a public-grievance journey with deliberately seeded defects. A scenario author defines synthetic personas, input formats, interaction constraints, and controlled failures. The lab then executes hundreds of browser journeys and records every state transition.

The lab:

1. Creates personas with declared capabilities and input characteristics.
2. Generates deterministic variants for names, scripts, attachment sizes, navigation modes, and interruption points.
3. Runs the journey under normal, slow, disconnected, duplicated, and resumed conditions.
4. Tests explicit invariants such as “submitted evidence survives resume” and “a successful submission returns a durable acknowledgement.”
5. Indexes events and screenshots by persona, step, failure, and invariant.
6. Reduces a large failure cluster to the smallest reproducible counterexample.
7. Replays the exact scenario after a fixture fix.
8. Shows cohort completion before and after correction.

## 20. Non-goals

- No crawling, stress-testing, or attacking live government websites.
- No claim that the lab certifies legal compliance.
- No subjective “good design” score.
- No automatic redesign of a production service.
- No simulation of every disability or every device.
- No reliance on a model to decide whether an invariant passed.

## 21. Domain model

**Journey:** the complete path from start through submission and acknowledgement.

**Persona:** a synthetic user profile with declared interaction, identity-format, device, and connectivity characteristics.

**Replay Scenario:** a fixed persona, input set, action sequence, and controlled perturbation.

**Invariant:** a machine-checkable condition that must hold during or after the journey.

**Journey Failure:** the smallest reproducible scenario in which a legitimate persona cannot complete the journey or loses required work.

**Repair Verification:** a rerun of the unchanged replay scenario against a revised fixture that satisfies the failed invariant.

## 22. Architecture and data flow

1. **Local journey fixture:** a realistic multi-step grievance application hosted through SAM CLI and LocalStack-backed services.
2. **Scenario compiler:** expands a small persona specification into deterministic test cases.
3. **Browser runners:** execute controlled journeys and capture actions, network state, accessibility results, application events, and screenshots.
4. **Local event pipeline:** receives step and backend events through an AWS-shaped local topology.
5. **OpenSearch trace index:** stores hundreds or thousands of ordered events and supports clustering and cohort comparisons.
6. **Invariant engine:** deterministically passes or fails each scenario.
7. **Strands analysis workflow:** proposes minimal reproductions and plain-language summaries from trace evidence; it does not determine pass/fail.
8. **Visual console:** displays persona races, the failure funnel, the minimal trace, and the unchanged replay after repair.

Firecracker is optional. The four-day MVP should use ordinary isolated browser workers unless a preflight proves that microVM isolation adds visible value without threatening delivery.

## 23. Why the AWS open-source stack is essential

### SAM CLI and LocalStack

SAM CLI can locally invoke functions and host local APIs, documented in [AWS SAM local testing](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/using-sam-cli-local.html). LocalStack provides a local AWS-shaped resource graph.

**Removal test:** without the event-driven local service, the lab can test page interactions but cannot reproduce backend retries, duplicate submissions, lost attachments, or acknowledgement failures across the full journey.

### OpenSearch

The lab generates enough events that exact search, time ordering, aggregation, and cohort analysis become core capabilities.

**Removal test:** without OpenSearch, the product becomes a collection of individual browser-test reports and loses cross-run failure clustering and causal reconstruction.

### Strands Agents SDK

Strands converts trace evidence into proposed minimal reproductions and readable explanations.

**Removal test:** deterministic execution and invariants remain possible, but analyzing many failing traces becomes manual. The agent is an investigator, not the testing oracle.

Cedar is excluded from the first MVP unless a concrete policy boundary emerges. Using it merely to implement ordinary login would be ornamental.

## 24. Error, privacy, and ethics

- Only controlled replicas and synthetic personas are tested.
- The same scenario is replayed before and after repair.
- Pass/fail derives from declared invariants, not model sentiment.
- Reports state exactly what was simulated and avoid generalizing beyond it.
- A failure does not imply intent or legal noncompliance.
- Flaky scenarios are rerun and labeled rather than treated as confirmed defects.
- Screenshots and traces contain synthetic information only.

## 25. Controlled three-minute demo

**0:00–0:20 — False confidence:** one ordinary desktop journey completes and the service appears healthy.

**0:20–0:45 — Persona race:** launch hundreds of controlled journeys with different scripts, navigation modes, attachments, devices, and network disruptions.

**0:45–1:15 — Hidden exclusion:** the dashboard shows one cohort collapsing at resume. Completion falls from the proposed 100% baseline to 82% in the seeded fixture.

**1:15–1:45 — Minimal counterexample:** open one trace: Indian-script name, keyboard navigation, evidence upload, disconnect, resume, missing attachment, unreachable recovery.

**1:45–2:05 — Mechanism view:** show the LocalStack event sequence and OpenSearch evidence explaining where state disappeared.

**2:05–2:35 — Exact replay:** apply the prepared fixture correction and rerun the unchanged scenario. The attachment persists and acknowledgement appears.

**2:35–3:00 — Proof:** compare cohort completion, invariant failures, and interruption recovery before and after.

## 26. Proposed success targets

- Detect every deliberately seeded journey failure in the controlled fixture suite.
- Produce a deterministic minimal replay for each confirmed failure.
- Achieve zero failed invariants after the prepared correction set.
- Keep flaky-test rate below 2% across repeated local runs.
- Index at least 1,000 meaningful journey events.
- Complete the headline before/after replay within the three-minute recording.

## 27. Four-day MVP and team split

**Day 1:** journey fixture, persona schema, invariants, LocalStack/SAM topology, and one browser runner.

**Day 2:** scenario expansion, interruption controls, event instrumentation, and OpenSearch index.

**Day 3:** clustering, minimal-replay generation, visual console, and prepared fixture corrections.

**Day 4:** deterministic reruns, flake removal, metric validation, video capture, repository, and write-up.

Suggested lanes:

- Person 1: public-journey fixture and prepared corrections.
- Person 2: browser runner, personas, network/interruption controls.
- Person 3: local event topology, OpenSearch, and invariant engine.
- Person 4: console, Strands trace analysis, metrics, and demo narrative.

## 28. Risks and mitigations

- **Name implies malicious intent:** define Journey Failure precisely and consider renaming the shipped product to **Civic Journey Crash Lab**.
- **Accessibility becomes subjective:** use explicit WCAG-aligned checks plus deterministic completion and state-survival invariants.
- **Synthetic fixture looks fake:** model it on documented grievance workflow requirements and expose the fixture source.
- **Too many personas:** demonstrate four meaningful axes and generate combinations, rather than hand-authoring dozens.
- **Browser flakiness:** freeze browser version, fonts, viewport, time, and random seeds.
- **Weak AWS story:** make backend event replay and OpenSearch causal evidence visible.

## 29. Expansion path

Authorized organizations could later run the lab against staging environments, add other essential journeys, maintain regression packs, and integrate results into CI. Any production use would require permission, data-handling agreements, broader accessibility research, and independent validation.

---

# Idea 3: Agent Treaty Simulator

## 30. The problem

Organizations may recognize that a cyberattack crosses their boundaries while being unable or unwilling to exchange raw logs containing customer identifiers, internal paths, infrastructure details, or unrelated security events. Conventional collaboration can force a bad choice: disclose too much, or fail to assemble a useful joint finding.

NIST’s [Zero Trust Architecture](https://csrc.nist.gov/pubs/sp/800/207/final) treats trust as something that should not be implicitly granted based on network location. OASIS publishes [STIX and TAXII standards](https://oasis-open.github.io/cti-documentation/) for structured cyber-threat information exchange. The proposed simulator explores a narrower question: can independently governed local agents derive one useful shared conclusion while executable policies prove that raw records did not cross boundaries?

The product is not a generic multi-agent framework or prompt-based promise. The agents are mutually untrusted. They may propose disclosures, but they cannot change policies or bypass enforcement.

## 31. Affected user and failure scenario

**Primary user:** a security engineering, incident-response, platform, or threat-intelligence team evaluating cross-organization collaboration.

**Demonstration participants:** three synthetic organizations with independently generated security logs.

**Current failure scenario:**

1. Each organization sees a partial signal that looks inconclusive alone.
2. A coordinator asks whether the same indicator appeared across all three.
3. Sharing raw logs would reveal prohibited customer and infrastructure data.
4. Prompt instructions tell agents to share only what is necessary, but a malicious request or injected log line asks for raw records.
5. A prompt-only agent follows the instruction or over-shares during reasoning.

The meaningful outcome is **one verified joint threat finding with zero forbidden raw records transferred**.

## 32. Proposed solution

Each organization operates a local agent, evidence index, policy set, and isolated execution capsule. The coordinator submits a narrowly typed investigation question. Agents negotiate a treaty describing the allowed claim, evidence threshold, time window, disclosure fields, recipients, and expiry.

The system then:

1. Compiles each organization’s disclosure limits into Cedar policies.
2. Computes the intersection of what all participants permit.
3. Rejects the task if no useful treaty exists.
4. Sends each agent only the treaty-approved query.
5. Searches each local OpenSearch index without exporting raw records.
6. Converts a proposed outbound fact into a Cedar authorization request.
7. Enforces the decision outside the agent process.
8. Releases only typed, minimum-necessary claims.
9. Combines permitted claims into the joint finding.
10. Records policy IDs, decision diagnostics, capsule IDs, and hashes in a disclosure ledger.

## 33. Non-goals

- No production threat-intelligence network.
- No proof that an indicator is malicious in the real world.
- No transfer of raw logs between organizations.
- No agent-written or agent-modified authorization policies during an investigation.
- No reliance on prompts as a security boundary.
- No complex cryptography or secure multi-party computation in the four-day MVP.
- No more than three organizations and one investigation type in the demo.

## 34. Domain model

**Organization:** an independently governed participant that owns local evidence and policy.

**Proposal:** an agent-generated candidate action or disclosure; never authoritative.

**Treaty:** the executable intersection of participant policies for one question, recipient set, purpose, and validity window.

**Authorization Request:** the Cedar principal-action-resource-context tuple plus supplied entities.

**Decision:** Cedar Allow or Deny with determining policy IDs and errors.

**Enforcement Point:** code outside the agent that prevents the operation after Deny.

**Capsule:** one isolated Firecracker guest with explicit CPU, memory, network, and storage limits.

**Local Evidence:** raw organization-owned security records that never cross the treaty boundary.

**Treaty-Approved Finding:** a typed fact all relevant policies permit the organization to disclose.

**Disclosure Ledger:** metadata proving what was requested, allowed, denied, and released. It is an audit record, not proof that the underlying log was truthful.

## 35. Architecture and data flow

1. **Three local evidence stores:** each OpenSearch index contains synthetic logs with one shared indicator and unrelated sensitive records.
2. **Treaty coordinator:** accepts one typed question and computes compatible disclosure fields.
3. **Cedar policy stores:** one independently owned schema and policy set per organization.
4. **Three Strands agents:** each uses narrow local search and claim-construction tools.
5. **Before-tool enforcement:** every search scope and outbound disclosure is converted to an authorization request before execution.
6. **Firecracker capsules:** each organization’s agent and tool worker run with a restricted filesystem and network path.
7. **Disclosure bus:** accepts only schema-valid, Cedar-approved claims.
8. **Joint finding builder:** evaluates whether the permitted claims meet the agreed evidence threshold.
9. **Visual treaty console:** shows proposals, decisions, policy reasons, boundary crossings, and the final minimum-disclosure result.

The coordinator is trusted to route typed messages and display decisions but is not trusted with raw evidence. Agents cannot modify policies. The enforcement point and capsule boundary—not the model—provide control.

## 36. Why the AWS open-source stack is essential

### Cedar

Cedar separates application behavior from authorization policy and evaluates explicit principal, action, resource, and context requests. The [Cedar reference guide](https://docs.cedarpolicy.com/) documents role- and attribute-based policies, while the [authorization algorithm](https://docs.cedarpolicy.com/auth/authorization.html) documents default deny and forbid-overrides-permit behavior.

**Removal test:** without Cedar, the treaty becomes natural-language guidance the agents can misunderstand or ignore. Executable, inspectable, independently owned policy is the product’s foundation.

### Strands Agents SDK

Strands provides tool-using agents and lifecycle controls in the application process. Its [hooks documentation](https://strandsagents.com/docs/user-guide/concepts/agents/hooks/) supports intercepting lifecycle events.

**Removal test:** without agents, a static query federation system could answer one fixed question, but the negotiation and evidence-seeking behavior would disappear. The enforcement design ensures the model remains replaceable and non-authoritative.

### Firecracker

Firecracker combines VM isolation with container-like speed and resource efficiency for multi-tenant workloads. Its official [design document](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md) describes KVM, seccomp, cgroups, namespaces, the jailer, and its minimal device model.

**Removal test:** without isolation, mutually distrustful agent tools share the host process and the claim that local evidence cannot cross boundaries becomes substantially weaker.

### OpenSearch

Each participant needs exact indicator matching, temporal filtering, aggregation, and retrieval across enough synthetic events to make manual inspection impractical.

**Removal test:** without local searchable evidence stores, the demo becomes three agents reading hand-selected files and no longer demonstrates realistic evidence minimization.

## 37. Threat, error, and privacy handling

- Agents cannot edit Cedar schemas or policies.
- A Deny response is enforced outside the model and cannot be talked around.
- Forbid policies override permits.
- The enforcement point fails closed: a request with no matching permit, malformed entities, or any policy-evaluation error is denied.
- Outbound claims must match a narrow schema; free-form log output is rejected.
- Capsules have no general cross-organization network access.
- Raw log fragments are never placed in the shared agent prompt.
- A malicious log line is treated as data, not an instruction.
- A treaty expires and cannot be reused for a different purpose.
- Useful claims are evaluated separately from privacy: blocking everything fails the utility metric.

## 38. Controlled three-minute demo

**0:00–0:20 — Fragmented attack:** three organizations each see an inconclusive event. Raw logs visibly contain prohibited customer and infrastructure fields.

**0:20–0:45 — Treaty negotiation:** the coordinator asks whether indicator X appeared across all three during a fixed window. Three Cedar policy panels converge on an allowed claim schema.

**0:45–1:20 — Local investigation:** the agents search separate OpenSearch indexes inside three capsules. No raw record crosses the boundary.

**1:20–1:45 — Valid disclosure:** each agent proposes a typed “observed/not observed, first seen, confidence evidence count” claim. Cedar allows only approved fields.

**1:45–2:10 — Adversarial climax:** a poisoned log entry or malicious agent asks for raw logs and customer IDs. The agent may propose the tool call, but the enforcement point produces a red Deny and nothing exits.

**2:10–2:35 — Useful result:** the coordinator produces the joint finding that all three observed the same indicator within the treaty window.

**2:35–3:00 — Proof:** show fields transferred, fields denied, bytes withheld, policy IDs, capsule isolation, and a utility test demonstrating that the system did not simply block everything.

## 39. Proposed success targets

- Produce the correct joint result for every seeded demo scenario.
- Transfer zero raw log records and zero explicitly forbidden fields.
- Deny 100% of seeded exfiltration attempts.
- Permit 100% of treaty-valid claims in the normal scenario.
- Make every outbound claim traceable to a Cedar decision and policy ID.
- Complete the headline investigation in under 90 seconds after treaty approval.
- Demonstrate three independently owned policy sets and three isolated evidence stores.

## 40. Four-day MVP and team split

Pre-event practice may validate generic Firecracker setup, local models, and Cedar syntax, but no competition project code should be written before the clock.

**Day 1:** three fixture indexes, shared schemas, Cedar organization models, and treaty coordinator skeleton.

**Day 2:** Strands search agents, enforcement point, typed disclosure bus, and normal joint finding.

**Day 3:** Firecracker capsule integration, malicious requests, poisoned log fixtures, and visual treaty console.

**Day 4:** deterministic adversarial tests, resource stabilization, video capture, public repository cleanup, and write-up.

Suggested lanes:

- Person 1: Cedar schemas, policies, treaty intersection, and enforcement tests.
- Person 2: Strands agents, search tools, and adversarial fixtures.
- Person 3: Firecracker images, jailer/network restrictions, and evidence stores.
- Person 4: coordinator, visual console, metrics, integration, and demo narrative.

## 41. Risks and mitigations

- **Firecracker environment failure:** preflight Linux, `/dev/kvm`, kernel, root filesystem, jailer, and one golden capsule lifecycle during allowed practice. Fall back to Crash Lab if this prerequisite is not stable.
- **Too many systems:** freeze the demo to three organizations, one indicator type, one query, and one malicious disclosure.
- **Prompt-injection project perception:** lead with executable treaty intersection and external enforcement, not prompt filtering.
- **Blocking everything:** display normal permitted claims and score usefulness alongside privacy.
- **Policy-model ambiguity:** hand-author and test the small Cedar policy sets; agents must not generate production policy.
- **Weak isolation claim:** demonstrate network and filesystem denial from inside a capsule, not merely show an architecture diagram.
- **Performance variance:** use preloaded local models, fixed fixtures, and warmed indexes.

## 42. Expansion path

Future work could add standards-based threat claims, more organizations, treaty templates, revocation, cryptographic attestations, federated deployment, and other mutually distrustful collaboration domains. Those features require formal security review and are outside the hackathon MVP.

---

# 43. Comparative assessment

## Equal-weight scoring

Each category is scored out of five. The total is the simple mean because the team gave the four objectives similar preference.

| Idea | Build It win probability | Amazon engineering signal | Startup potential | Measurable impact | Mean |
|---|---:|---:|---:|---:|---:|
| Agent Treaty Simulator | 4.8 | 5.0 | 4.6 | 4.0 | **4.60** |
| Civic Dark-Pattern Crash Lab | 4.6 | 4.6 | 4.4 | 4.5 | **4.53** |
| 1930 Evidence Capsule | 4.4 | 4.2 | 4.2 | 4.8 | **4.40** |

### 1930 Evidence Capsule

**Strengths:** immediate human story, official workflow, strong privacy framing, low institutional dependency, controlled evidence fixtures, and straightforward before/after metrics.

**Weaknesses:** lower systems novelty; extraction and report-preparation products can look like document automation unless Cedar enforcement and evidence provenance are made visible.

### Civic Dark-Pattern Crash Lab

**Strengths:** high demo clarity, objective replay, broad organizational market, no specialized hardware, and a strong connection between human exclusion and technical failure.

**Weaknesses:** the current name may imply intent; synthetic fixtures must look credible; AWS relevance weakens if it becomes only browser automation.

### Agent Treaty Simulator

**Strengths:** strongest Cedar indispensability, deepest systems architecture, exceptional adversarial reveal, high Amazon engineering signal, and a credible emerging market around governed agent collaboration.

**Weaknesses:** highest integration risk, lower immediately visible human impact, crowded agent-security language, and dependence on a stable Linux/KVM environment.

## 44. Final recommendation

Build **Agent Treaty Simulator** if all of these pre-event practice gates pass:

1. A Firecracker microVM starts reliably on the chosen Linux/KVM host.
2. The jailer and network boundary can be demonstrated, not merely configured.
3. A local Strands agent can call a narrow search tool deterministically.
4. A Cedar enforcement point blocks a forbidden disclosure outside the model.
5. Three fixture OpenSearch indexes can return the shared indicator quickly.
6. The team can explain the full system in one sentence: **three organizations jointly identify one cyber threat without sharing their raw logs**.

Choose **Civic Dark-Pattern Crash Lab** instead if any Firecracker gate remains unstable. It has the best risk-adjusted chance of producing a polished, repeatable three-minute result.

Choose **1930 Evidence Capsule** if the team prioritizes direct human impact, wants the lowest infrastructure risk, or cannot make the other candidates’ stories understandable to non-security judges.

## 45. Ruthless scope rules for the selected build

- One user problem.
- One decisive state transition.
- One adversarial edge case.
- One visible enforcement mechanism.
- One before/after metric panel.
- No architecture component without a removal-test explanation.
- No agent decision treated as truth without deterministic verification.
- No feature included only in the write-up.
- No project implementation before the event clock begins.

## 46. Source index

### Event

- [First Commit event page](https://www.wemakedevs.org/aws/first-commit)
- [Bharat Builds Tour rules](https://www.wemakedevs.org/aws/rules)

### Public problem and standards

- [National Cyber Crime Reporting Portal](https://cybercrime.gov.in/)
- [Citizen financial-fraud reporting instructions](https://cybercrime.gov.in/uploadmedia/instructions_citizenreportingcyberfrauds.pdf)
- [DARPG grievance-handling guidelines](https://darpg.gov.in/sites/default/files/Comprehensive_guidelines_for_handling_the_Public_Grievances.pdf)
- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [NIST Zero Trust Architecture](https://csrc.nist.gov/pubs/sp/800/207/final)
- [OASIS cyber-threat intelligence standards](https://oasis-open.github.io/cti-documentation/)

### AWS open-source technology

- [Cedar reference guide](https://docs.cedarpolicy.com/)
- [Cedar authorization algorithm](https://docs.cedarpolicy.com/auth/authorization.html)
- [Strands Agents SDK quick start](https://strandsagents.com/docs/user-guide/quickstart/overview/)
- [Strands hooks](https://strandsagents.com/docs/user-guide/concepts/agents/hooks/)
- [Firecracker design](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md)
- [AWS SAM local testing](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/using-sam-cli-local.html)
- [OpenSearch hybrid search](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/)

### International hackathon references

- [ElevenLabs worldwide hackathon winners](https://elevenlabs.io/blog/announcing-the-winners-of-the-elevenlabs-worldwide-hackathon)
- [Google Gemma 3n impact challenge winners](https://blog.google/innovation-and-ai/technology/developers-tools/developers-changing-lives-with-gemma-3n/)
- [Amazon Nova AI Challenge winners](https://www.amazon.science/nova-ai-challenge/pushing-the-boundaries-of-secure-ai-winners-of-the-amazon-nova-ai-challenge)
- [FINOS–AWS open-source hackathon recap](https://www.finos.org/blog/open-source-in-finance-hackathon-nyc-2025-recap)
