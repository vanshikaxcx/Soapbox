# Build It Finalist Ideas

## 1930 Evidence Capsule

### Idea and Problem

A person who has just lost money through UPI or a bank transfer must act quickly, but the evidence needed for reporting is scattered across payment screenshots, SMS messages, bank statements, call records, and notes. Transaction references and timestamps may appear in different formats. Screenshots often expose unrelated balances, contacts, and conversations. The victim must reconstruct the sequence while under stress, and an incomplete account can create more work at the point where speed matters most.

The official [National Cyber Crime Reporting Portal](https://cybercrime.gov.in/) and its financial-fraud instructions describe the reporting channel and the information a citizen must provide. The gap addressed here is preparation: turning scattered material into a complete, consistent package without giving an automated system authority to accuse someone, submit a complaint, or promise recovery.

**Proposed solution:** The Evidence Capsule is a local application for UPI and bank-transfer cases. A victim imports selected screenshots, relevant SMS exports, a PDF statement, optional call metadata, and any details that must be entered manually. The system hashes each original, extracts candidate facts, connects them into a proposed timeline, and shows every fact beside its source. It identifies missing reporting fields, marks uncertain matches, and requires the victim to approve what will be included. Cedar policies prevent unrelated personal fields from entering the export. The final output is a reviewed folder containing selected evidence, redacted copies where needed, a timeline, a field checklist, and an integrity manifest. The victim remains responsible for calling 1930 and submitting through the official process. The consumer workflow can remain free or low cost, while banks, payment providers, insurers, legal-aid organizations, and fraud-support teams license a self-hosted version per investigator seat or completed evidence package. Institutional customers pay for controlled deployment, policy administration, workflow integration, audit retention, and support rather than for access to a victim's raw data.

### Architecture and Data Flow

1. **Local intake:** The interface imports only the files selected by the user and stores them in a case workspace on the device.
2. **Integrity capture:** The system calculates a hash for every original before extraction. Derived or redacted copies remain separate from originals.
3. **Structured extraction:** Deterministic tools read transaction IDs, dates, amounts, UPI handles, account fragments, and message metadata. A Strands agent coordinates these narrow tools and proposes relationships between records; it cannot mark a proposal as verified.
4. **Evidence indexing:** OpenSearch stores exact identifiers, extracted text, timestamps, and source references. The local test corpus includes hundreds of irrelevant synthetic records, so the search layer must isolate the small set connected to the incident.
5. **Human review:** The victim accepts, rejects, or corrects proposed facts. Missing information stays missing until the user supplies or confirms it.
6. **Disclosure enforcement:** Before any field or artifact enters the package, an enforcement service asks Cedar whether that user may export that resource for the reporting purpose. The default is denial when no policy permits disclosure.
7. **Package creation:** The builder copies approved evidence, applies approved redactions to derived copies, writes the incident timeline and checklist, and creates a manifest containing file hashes.

### Why Build It Open Source Is Essential

- OpenSearch is the evidence reconstruction layer. Exact search finds transaction references, text retrieval finds related messages, and time filtering builds a traceable sequence across a noisy local corpus. Removing it reduces the product to disconnected extractors.
- Cedar turns privacy minimization into an executable rule. Every export becomes a principal, action, resource, and context decision. Removing Cedar makes selective disclosure an informal convention inside application code.
- Strands coordinates local extraction and review tools where the evidence is ambiguous. The model proposes observations and missing-field questions, while deterministic parsers and human review remain authoritative. This keeps the system useful without treating model output as evidence.

## Civic Dark Pattern Crash Lab

### Idea and Problem

A public digital service can pass an ordinary desktop test while still failing legitimate users. A name written in an Indian script may be rejected. An uploaded document may disappear after connectivity drops. A keyboard-only user may be unable to reach a recovery control. A completed grievance may fail to produce a durable acknowledgement. Uptime remains green because the server is running, even though a complete journey is impossible for a specific person under realistic conditions.

The [government grievance handling guidelines](https://darpg.gov.in/sites/default/files/Comprehensive_guidelines_for_handling_the_Public_Grievances.pdf) emphasize correct handling, categorization, feedback, and quality of disposal. [WCAG 2.2](https://www.w3.org/TR/WCAG22/) provides testable accessibility criteria. Existing page-level checks, however, do not by themselves prove that a multi-step process survives interrupted networks, unusual identity formats, evidence upload, session recovery, and acknowledgement.

**Proposed solution:** The Crash Lab runs controlled local replicas of a public-grievance journey. It creates synthetic personas with declared interaction needs, identity formats, devices, and connection conditions, then executes the full path from starting a grievance to receiving an acknowledgement. The system introduces repeatable disruptions such as slow connections, disconnection during upload, duplicated requests, session expiry, keyboard-only navigation, and Indian-script text. Each run is checked against explicit invariants, such as preserving an attachment after resume or issuing exactly one acknowledgement. When many runs fail, the lab reduces them to the smallest reproducible case and reruns that exact case after a correction. The product reports a verified journey failure; it does not claim malicious intent or certify legal compliance. A hosted or self-managed version can be licensed to government vendors, universities, banks, utilities, and other operators of essential digital journeys. Pricing combines an annual platform license with usage tiers based on tested journeys, replay volume, or CI runs; higher tiers add private runners, retention controls, custom persona packs, and audit-ready regression reports.

### Architecture and Data Flow

1. **Controlled journey:** A realistic grievance application runs locally. It contains seeded defects so the same failure and correction can be shown without touching a live government service.
2. **Scenario definition:** A compact specification describes each synthetic persona, input set, interaction mode, and network interruption. Fixed seeds keep every run reproducible.
3. **Scenario expansion:** The runner generates combinations of names, scripts, attachment sizes, navigation modes, devices, and interruption points without hand-authoring every case.
4. **Local AWS-shaped workflow:** SAM CLI and LocalStack host the API, functions, storage, and event path behind the replica. This lets the test exercise retries, duplicate submissions, upload loss, and acknowledgement failures as part of the complete journey.
5. **Browser execution:** Automated browser workers perform each journey and capture user actions, application events, screenshots, network state, and accessibility results.
6. **Trace analysis:** OpenSearch indexes the ordered events from hundreds of runs. Aggregations expose which persona or disruption correlates with a failure, while the invariant engine makes the actual pass-or-fail decision.
7. **Minimal replay:** A Strands workflow proposes the smallest failing sequence from the indexed evidence. The system reruns that fixed sequence to confirm it is reproducible.
8. **Repair verification:** The same sequence runs against the corrected replica. The lab compares completion, state preservation, duplicate effects, and acknowledgement before and after the change.

### Why Build It Open Source Is Essential

- SAM CLI and LocalStack provide the local event-driven application being tested. They make backend retries, duplicate events, object storage, and failure recovery visible without requiring a cloud account. Removing them leaves only superficial browser automation.
- OpenSearch turns thousands of step and backend events into a causal record across runs. It supports time ordering, exact event lookup, cohort aggregation, and failure clustering. Removing it produces isolated test logs rather than a journey-level failure laboratory.
- Strands helps investigate failures by navigating trace evidence and proposing a minimal reproduction. It never determines whether a journey passed; explicit invariants and deterministic replays do that work.

## Agent Treaty Simulator

### Idea and Problem

Several organizations may suspect that the same cyberattack crossed their networks, but their evidence is incomplete when viewed separately. Sharing complete security logs can expose customer identifiers, internal paths, infrastructure details, and unrelated incidents. Asking AI agents to share only what is necessary does not solve the problem because a prompt is not an enforcement boundary. A malicious agent request or an instruction hidden inside a log could still trigger excessive disclosure.

The proposed design follows the principle in [NIST Zero Trust Architecture](https://csrc.nist.gov/pubs/sp/800/207/final) that trust should not be granted implicitly, and it can represent shared findings using concepts compatible with [STIX and TAXII](https://oasis-open.github.io/cti-documentation/). Its narrow question is whether independently governed local agents can establish one useful shared finding while executable policies prevent raw records from crossing organizational boundaries.

**Proposed solution:** Three synthetic organizations each operate their own evidence index, local agent, and Cedar policy set. A coordinator asks one typed question, such as whether the same indicator appeared across all three organizations during a fixed time window. The system computes an executable treaty from the intersection of what each organization permits. Each agent searches only its local evidence and proposes a narrowly structured finding. An enforcement point outside the model checks every search scope and outbound field against Cedar before anything executes or leaves the organization. Firecracker capsules separate the organizations and restrict filesystem and network access. The coordinator receives only approved claims, such as a presence flag, first-seen time, and evidence count. Raw logs and unrelated identifiers remain local. Security teams, managed detection providers, industry information-sharing groups, and regulated enterprises can license this as self-hosted collaboration infrastructure through an annual fee per participating organization plus usage based on active treaties or investigation volume. Enterprise tiers add policy templates, standards adapters, deployment support, audit retention, and verified isolation profiles.

### Architecture and Data Flow

1. **Independent evidence stores:** Each organization keeps a separate OpenSearch index containing synthetic logs, one shared indicator, and unrelated sensitive records.
2. **Typed investigation request:** The coordinator specifies the indicator, time range, permitted result fields, intended recipients, purpose, and treaty expiry.
3. **Policy intersection:** Each organization evaluates what it is willing to disclose. The coordinator derives the common claim schema. If the policies have no useful intersection, the investigation stops without weakening a participant's rules.
4. **Local agent investigation:** A Strands agent inside each organization uses narrow search and claim-construction tools. It sees local evidence but has no authority to export it.
5. **External enforcement:** Every tool call and proposed outbound field becomes a Cedar principal, action, resource, and context request. An enforcement service outside the agent blocks denied, malformed, expired, or policy-error requests.
6. **Firecracker isolation:** Each organization's agent and tool worker run in a constrained microVM with explicit filesystem, network, CPU, and memory limits. Only the typed disclosure channel reaches the coordinator.
7. **Minimum disclosure:** The bus accepts only schema-valid, Cedar-approved claims. It rejects free-form log fragments and fields outside the treaty.
8. **Joint finding:** The coordinator combines the permitted claims and checks whether they meet the treaty's evidence threshold. A disclosure ledger records requests, decisions, policy identifiers, and released fields without storing raw logs.

### Why Build It Open Source Is Essential

- Cedar is the treaty's decision engine. Each disclosure is evaluated against independently owned policy using principal, action, resource, and context. Removing Cedar turns the treaty into natural-language guidance that an agent can misunderstand or ignore.
- Strands provides the local tool-using agents that search evidence and construct candidate claims. Hooks route every consequential action through the external enforcement point, so the agent remains useful without becoming authoritative.
- Firecracker supplies the isolation boundary between mutually distrustful agents and their tools. A stable Linux host with KVM is required. Removing the microVM boundary makes the claim that evidence stays inside each organization much weaker.
- OpenSearch gives each organization a realistic local evidence environment with exact indicator matching, temporal filters, aggregation, and retrieval across many events. Removing it reduces the system to agents reading hand-selected files rather than investigating independent evidence stores.
