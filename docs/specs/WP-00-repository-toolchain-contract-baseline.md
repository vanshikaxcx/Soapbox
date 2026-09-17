# WP-00 — Repository, toolchain, and contract baseline

Owner: P4 — Sparsh Jain — @SparshJain769  
Reviewers: P1 — Vanshika — @vanshikaxcx (web and generated-client conventions); P2 — Rudransh Singh Rathore — @Rudransh-1508 (Python and container conventions)  
Affected owner: P3 — Aarushi — @a-for-aarushi (shared contract primitives and the transaction/recovery ownership boundary)  
Status: SPEC APPROVED  
Depends on: None

## Outcome and user value

WP-00 creates the smallest stable repository, toolchain, contract, and quality baseline on which four contributors can work independently. A clean checkout must produce the same generated API types, deterministic test results, build artifacts, and health response on supported machines and in CI.

The package exists to remove setup and contract ambiguity before feature work begins. It does not implement the ProofPath journey. Its user-visible output is limited to a web scaffold smoke surface and an unauthenticated API health route.

## In scope

- Treat the current Soapbox repository root as the current ProofPath root without creating a nested repository or `proofpath/` directory.
- Preserve portability for later transfer into the official competition repository.
- Establish the repository skeleton, canonical documentation locations, ownership metadata, status tracking, MIT license, ignore rules, and learning log.
- Pin and configure the approved JavaScript, Python, SAM, OpenAPI, test, security, and CI toolchain.
- Establish a cross-platform command surface for Windows, macOS, and Linux CI.
- Establish OpenAPI 3.0.3 with one real `GET /health` operation and shared transport primitives.
- Generate and commit TypeScript API declarations from OpenAPI.
- Establish package boundaries, dependency direction, composition-root conventions, and deterministic adapter-test conventions without defining feature ports.
- Establish deterministic unit, contract, integration, and browser-scaffold tests for the baseline.
- Establish ordinary CI that requires no AWS or LocalStack credentials.
- Optionally validate the exact DynamoDB, S3, and SQS APIs later packages expect to exercise through an authenticated LocalStack profile.

## Out of scope

- Any shopper, conversation, voice, upload, merchant, search, comparison, repair, quote, approval, simulator, checkout, callback, recovery, case, guidance, export, or operator feature.
- Authentication, authorization behavior, Cedar policies, AWS account provisioning, deployment, or live cloud smoke tests.
- Domain records, commerce state machines, domain errors, transaction reconciliation semantics, provider facts, or domain-specific ports.
- Speculative OpenAPI paths or schemas for WP-01 through WP-12.
- The runtime browser API client, authentication middleware, polling controller, routing, or reusable feature cards; WP-03 owns them.
- Live merchant/model/speech/provider access or their fixtures.
- Durable jobs, outbox/event schemas, workflow behavior, DLQs, projections, or restart semantics; WP-07 owns them.
- Full browser/device E2E, live suites, deployment workflows, release automation, or production monitoring.
- Making LocalStack a prerequisite for setup, deterministic tests, or ordinary CI.
- Creating, moving to, or imposing competition-specific rules on the future official competition repository.

## Repository baseline

### Root and portability

The current repository root is the ProofPath root for pre-competition development. The `proofpath/` label in the product specification's tree is a logical root label, not a directory to create.

Repository files and commands must:

- use repository-relative paths;
- derive the root from the running script rather than the caller's current directory;
- avoid absolute paths, user profile paths, drive letters, and Soapbox-specific Git history;
- avoid depending on the current remote name, repository owner, repository numeric ID, or pre-existing branches;
- keep generated and copied artifacts reproducible after transfer to another Git repository.

### Required skeleton

WP-00 implementation establishes only package boundaries and baseline files in this shape. Directories reserved for later packages contain boundary documentation or package markers, not speculative feature code.

```text
<repository-root>/
├── README.md
├── AGENTS.md
├── LICENSE
├── LEARNING.md
├── .editorconfig
├── .env.example
├── .gitignore
├── .node-version
├── .python-version
├── package.json
├── pyproject.toml
├── uv.lock
├── uv.toml
├── docs/
│   ├── PROOFPATH-SPEC.md
│   ├── STATUS.md
│   └── specs/
├── contracts/
│   └── openapi.yaml
├── web/
│   ├── package.json
│   ├── package-lock.json
│   ├── .env.example
│   ├── index.html
│   ├── eslint.config.js
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── src/{pages,components,api/generated}/
├── services/
│   ├── api/
│   ├── application/
│   ├── domain/
│   ├── agent/
│   ├── merchants/
│   ├── adapters/
│   ├── workers/
│   └── simulator/
├── workflows/
├── policies/
├── guidance/
├── infra/
│   └── template.yaml
├── local/                             # optional; only when LocalStack is validated
│   └── compose.yaml                   # conditional authenticated LocalStack profile
├── scripts/
├── tests/{unit,contracts,integration,e2e,live}/
└── .github/
    ├── CODEOWNERS
    ├── pull_request_template.md
    └── workflows/checks.yml
```

The root `package.json` is a private metadata-only package used to declare the npm version and expose the shared command aliases. It must not introduce npm workspaces, a monorepo framework, or application dependencies. `web/package.json` is the sole JavaScript application package in WP-00. The `local/` directory and `local/compose.yaml` are conditional and are omitted when optional LocalStack validation is not performed.

### Existing and canonical documentation

- `docs/PROOFPATH-SPEC.md` becomes the single authoritative product specification by verified migration from `Final idea and archi/PROOFPATH-SPEC.md`. Its content is identical to the approved source except for the narrow, already-approved recovery ownership correction: P3 owns transaction truth/semantics, simulator behavior, provider facts, transaction-domain reconciliation rules, and commerce invariants; P4 owns callback ingestion, durable reconciliation/recovery machinery, recovery handlers, and the guidance/case/export backend; P1 owns recovery/export presentation.
- The previous specification is retained only as clearly labelled migration/historical material or removed after verification; it must not remain a coequal authority.
- `AGENTS.md`, `README.md`, and other live references must point to `docs/PROOFPATH-SPEC.md` after migration.
- `Final idea and archi/PROOFPATH-IMPLEMENTATION-POA.md` remains the authoritative POA unless it is separately migrated without creating a duplicate authority.
- `docs/STATUS.md` records every WP's owner, status, dependency state, specification link, implementation PR/commit when available, verification state, and blockers. WP-00 starts as `Draft` and advances only through the approved gates.
- Root `LEARNING.md` is an append-only team learning log for concrete findings, failed assumptions, and decisions during the event.
- `ideation/**` and supporting recommendation material remain historical and cannot be cited as implementation authority.
- The project license is MIT, using the standard MIT license text and `Copyright (c) 2026 ProofPath contributors`.

### Ignore policy

`.gitignore` must cover at least:

- all `.env` files except explicitly allowlisted `.env.example` templates;
- `.venv/`, Python caches, test caches, coverage, build, and package artifacts;
- `.tools/`, including the checksum-verified local Gitleaks executable cache;
- `node_modules/`, Vite output, Playwright browser/test artifacts, traces, sessions, and recordings;
- `.aws-sam/`, AWS/SAM build output and local state;
- LocalStack volumes/state and credentials;
- raw audio, uploads, personal captures, private evidence, and export output;
- editor, OS, and local tool state, including `.DS_Store`.

Gate A verifies ignore behavior with disposable sentinel files and `git check-ignore`; it must not create real secrets or private data.

## Toolchain contract

### Version and pinning classes

| Class | Rule |
| --- | --- |
| Exact executable pins | Node, npm, local CPython, uv, and SAM CLI use the exact versions below in version/configuration files and CI. |
| JavaScript direct dependencies | Direct versions are written without `^` or `~`; `web/package-lock.json` is the only npm lockfile and exact transitive authority, and installs use `npm --prefix web ci`. |
| Python compatibility ranges | `pyproject.toml` expresses supported APIs/ranges; `uv.lock` is the exact transitive authority and installs use frozen/locked modes. |
| Platform-managed versions | AWS controls the Lambda Python 3.12 patch; GitHub controls software preinstalled on its hosted runner. The project pins the language minor/runner image and verifies behavior. |
| Desktop software | Docker Desktop is constrained by documented requirements and Gate A evidence, not one global patch pin. Exact validated Docker Desktop and Compose versions are recorded. |
| Repository-controlled images/actions | Container images use an exact immutable digest where practical, with a readable version tag comment. GitHub Actions use a verified full commit SHA with a readable release comment. |

### Approved versions

| Component | WP-00 selection | Pin expression |
| --- | --- | --- |
| Node.js | 24.21.0 Active LTS | `.node-version`, CI input, and root metadata: exact `24.21.0` |
| npm | 12.0.2 | root and web `packageManager`: `npm@12.0.2`; exact executable used for lockfile changes |
| React / React DOM | 19.2.8 | exact direct dependencies |
| Vite | 8.3.0 | exact direct development dependency |
| TypeScript | 5.9.3 | exact direct development dependency; strict mode required; selected to satisfy the verified `openapi-typescript` 7.13.0 peer requirement of TypeScript `^5.x` |
| ESLint | 10.10.0 | exact direct development dependency |
| typescript-eslint | 8.70.0 | exact direct development dependency |
| Prettier | 3.9.6 | exact direct development dependency |
| Vitest | 4.1.11 | exact direct development dependency |
| React Testing Library | `@testing-library/react` 16.3.3 | exact direct dependency; compatible `@testing-library/dom` peer resolved and pinned in the lockfile |
| Playwright | `@playwright/test` 1.63.0 | exact direct development dependency and matching Chromium binary |
| Python | CPython 3.12.14 for local/CI; Lambda runtime `python3.12` | exact `.python-version`; project compatibility `>=3.12,<3.13`; AWS-managed Lambda patch |
| uv | 0.12.13 | exact `required-version` in `uv.toml` and CI setup |
| Pydantic | 2.13.5 baseline | compatible `>=2.13.5,<3`; exact resolution in `uv.lock`; strict models required |
| Ruff | 0.16.7 | compatible `>=0.16.7,<0.17`; exact resolution in `uv.lock`; preview rules disabled |
| mypy | 2.3.1 | compatible `>=2.3.1,<2.4`; exact resolution in `uv.lock`; strict checks and Pydantic plugin |
| pytest | 9.1.1 | compatible `>=9.1.1,<10`; exact resolution in `uv.lock` |
| pip-audit | 2.10.1 | compatible `>=2.10.1,<3`; exact resolution in `uv.lock` |
| SAM CLI | 1.164.0 | exact developer prerequisite and exact CI action input |
| OpenAPI | 3.0.3 | exact `openapi` document version |
| openapi-typescript | 7.13.0 | exact web development dependency |
| Gitleaks CLI | 8.30.1 | exact native CLI release; platform archive verified against the publisher's checksum |
| GitHub runner | Ubuntu 24.04 | explicit `ubuntu-24.04`, never `ubuntu-latest` |

Supporting packages required to make the selected stack work, such as the React Vite plugin, DOM test environment, React type declarations, and ESLint plugins, must be chosen from stable versions compatible with this table. Their exact resolved versions belong in `web/package-lock.json`; implementation must record them in the WP-00 evidence and may not replace a listed primary selection without specification review.

TypeScript 7, React 19.3, and Vitest 5 are intentionally not selected because their recent releases or ecosystem constraints add risk without a WP-00 requirement. SAM's preview `python-uv` builder is also intentionally excluded.

## Cross-platform development contract

Supported development hosts are Windows and macOS. CI uses Linux.

- PowerShell 7 (`pwsh`) is the shared orchestration runtime.
- Every shared PowerShell script must run under PowerShell 7 on Windows, macOS, and Linux; use PowerShell APIs/cmdlets and repository-relative `Join-Path`/literal paths.
- Scripts must not assume a Windows drive, backslash separator, case-insensitive filesystem, Unix executable bit, `/bin/bash`, Homebrew, WSL, GNU-only flags, or globally activated virtual environment.
- No Bash-only path may be required for setup or verification. Platform-specific installation notes may supplement, but not replace, the shared commands.
- Text files use UTF-8 and LF where supported by the file type; Git/editor configuration must prevent accidental whole-repository line-ending churn.
- Docker Desktop is the documented local container environment for Windows and macOS, subject to each developer's applicable licensing terms. Documentation must not claim it is universally free.
- Windows documentation must cover supported Docker Desktop/WSL2 requirements and long-path considerations. macOS documentation must cover supported Docker Desktop/macOS requirements and both Intel and Apple Silicon where applicable.
- Use `docker compose`, never legacy `docker-compose`.
- Docker is required for the full `dev` command because SAM Local runs Lambda containers, for release-equivalent SAM build evidence, and for optional LocalStack. Deterministic unit/contract/integration tests must not require Docker, LocalStack, or AWS credentials.
- Gate A requires clean-clone evidence from at least one Windows machine and one macOS machine. Evidence records OS, architecture, Node/npm/Python/uv/SAM, Docker Desktop, Docker Engine, and Compose versions plus command outcomes.
- After Gate A, the lowest Docker Engine/Compose capabilities proven on both supported developer platforms become the documented initial minimums; this records evidence without globally pinning a Docker Desktop patch.

## Python and SAM dependency/build strategy

- `uv` is the only Python project dependency and environment manager.
- Root `pyproject.toml` declares Python compatibility, application dependencies, development dependency groups, package discovery, and Ruff/mypy/pytest settings.
- Root `uv.lock` is committed and is the deterministic dependency authority for all supported hosts.
- Setup and CI use frozen installs; CI must fail rather than rewrite `uv.lock`.
- WP-00 exports the production subset from `uv.lock` to `services/api/requirements.txt`, colocated with the health Lambda `CodeUri`. The export is committed because SAM's stable Python builder consumes it.
- The canonical export is `uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file services/api/requirements.txt`. It includes uv's deterministic package ordering, environment markers, and hashes; excludes development groups and the local editable project; and fails rather than changing `uv.lock`. CI runs the identical command and fails on diff. The exported file is generated material and is never manually edited.
- SAM uses its stable default `pip` build method. No function receives `Metadata: BuildMethod: python-uv`, no beta flag is enabled, and no beta environment variable is required.
- The native SAM `python-uv` builder may be reconsidered only after AWS marks it stable and a later approved specification records the migration.
- The release-equivalent Gate A build is `sam build --use-container` through the repository command surface. It must use the pinned Lambda Python 3.12 build image by immutable repository-controlled reference where SAM permits that selection.
- A host build may be used for iteration, but cannot substitute for the containerized Gate A result.
- Build artifacts under `.aws-sam/` are ignored and never committed.

## Repository commands

WP-00 implementation must establish the following root command surface. From the repository root, the canonical spelling is `pwsh ./scripts/proofpath.ps1 <command>`. The script resolves the repository root for its internal paths and operations.

| Command | Required real behavior in WP-00 |
| --- | --- |
| `setup` | Check exact required tool versions; acquire the native Gitleaks 8.30.1 archive for the host platform into an ignored repository tool cache and verify its published checksum; run frozen Python synchronization and `npm --prefix web ci`; install the pinned Playwright Chromium binary; never request AWS/LocalStack credentials. |
| `format` | Apply Ruff formatting/fixes only to Python under `services/**` and `tests/**`; apply Prettier only to WP-00-owned web source/configuration, package manifests, `contracts/openapi.yaml`, and active CI/local configuration. Authoritative/migrated specifications, the POA, `ideation/**`, and historical material are excluded from automatic formatting. |
| `format-check` | Check the same explicit Ruff and Prettier path allowlists used by `format` without changing files. |
| `lint` | Run Ruff lint and ESLint with zero warnings permitted. |
| `typecheck` | Run strict mypy and strict TypeScript checking without emitting build output. |
| `test-unit` | Run deterministic Python unit tests and Vitest unit/component tests. |
| `test-contract` | Run baseline adapter/transport/OpenAPI contract tests without AWS or LocalStack. |
| `test-integration` | Run the local health handler/use-case integration test without network cloud dependencies. |
| `test` | Run `test-unit`, `test-contract`, and `test-integration`. |
| `openapi-generate` | Validate `contracts/openapi.yaml` using pinned openapi-typescript 7.13.0's parser/validator plus the focused AWS-subset contract test, generate the declared TypeScript output, then format it. |
| `openapi-check` | Run generator validation, the focused AWS-subset contract test, and SAM template validation; regenerate deterministically; regenerate `services/api/requirements.txt` with the canonical locked export; and fail if either generated artifact differs from committed content. It must leave the working tree understandable for diagnosis. |
| `build` | Produce the Vite production build and a containerized SAM build. |
| `dev` | With Docker available, start only the WP-00 Vite scaffold and SAM Local health API with documented endpoints and clean shutdown; it must not start LocalStack implicitly. |
| `security` | Run the checksum-verified native Gitleaks binary, audit both the frozen Python development environment and production SAM export, run `npm --prefix web audit`, and verify ignore rules. |
| `verify-gate-a` | Run all non-mutating version, lock, generation, format, lint, type, test, security, build, and Chromium smoke checks and write no tracked changes. |
| `verify-clean-clone` | From a documented fresh checkout, run `setup` and then `verify-gate-a`; reject an already dirty checkout as evidence. |

`web/package-lock.json` is the only npm lockfile in WP-00. All dependency installation and audit operations target `web` explicitly; no root `npm ci` is run. The root private `package.json` may expose equivalent one-way `npm run` wrappers around the PowerShell dispatcher, but the dispatcher invokes package-scoped web scripts directly and never calls a root alias, preventing recursion. Documentation and CI use the PowerShell surface above so the same orchestration is exercised everywhere.

Commands for full E2E, live merchants, real cloud smoke, infrastructure deployment, application deployment, DLQ operations, release, and teardown are reserved for their owning WPs and must not be added as nonfunctional placeholders.

## User flow and UI states

WP-00 has no product user flow. The web scaffold must render a stable, accessible ProofPath application shell identifying itself as a development baseline. It must not imitate a finished shopping flow or expose nonfunctional controls.

The scaffold smoke verifies successful render. Loading, empty, partial, retryable error, terminal error, expired, and stale-conflict product states are not applicable to WP-00 and remain WP-03/feature-WP responsibilities.

## API and event contracts

### OpenAPI authority and compatibility

- `contracts/openapi.yaml` is the browser/API contract source.
- It declares OpenAPI `3.0.3` and uses the documented API Gateway/SAM-compatible subset.
- Do not use OpenAPI 3.1 JSON Schema behavior, external `$ref` documents, unsupported discriminator/nullable constructs, or other API Gateway-incompatible features.
- Base structural validation uses the parser/validator embedded in pinned openapi-typescript 7.13.0, so WP-00 adds no second validator dependency. A focused deterministic contract test rejects the documented unsupported constructs used by the compatibility policy, and SAM validates/builds the containing template.
- These checks demonstrate conformance to the documented subset; they do not prove that API Gateway has imported the document. Empirical API Gateway import/deployment evidence belongs to WP-01.
- Shared components live in the same file until a later approved migration proves a bundled multi-file workflow.
- WP-00 defines no event contract and no speculative endpoint.

### Initial route

`GET /health` is the only WP-00 route.

- It is the sole unauthenticated public liveness exception in WP-00 and is side-effect free. Its success is not authentication evidence; WP-01/WP-03 must verify authentication separately.
- It is a liveness check, not proof that AWS dependencies, merchants, persistence, or downstream services are ready.
- It does not query DynamoDB, S3, SQS, LocalStack, or external networks.
- Success is HTTP `200` with `Content-Type: application/json`:

```json
{
  "data": { "status": "ok" },
  "request_id": "opaque-server-generated-id"
}
```

- An unexpected handler failure uses HTTP `500` and the baseline error envelope with safe code `internal_error`; no exception, stack, path, environment value, or secret is returned.
- The health response must not expose commit identifiers, dependency versions, hostnames, account data, or deployment configuration.

### Request IDs and envelopes

- Every application-handled API response receives a new opaque server-generated request ID. Client-supplied correlation values may be logged separately only after validation in a later WP; they never replace the authoritative ID. Normalization of errors generated by API Gateway before the handler runs is deferred to WP-01 or the WP introducing the applicable gateway/auth behavior.
- The same request ID appears in each application-handled response's `X-Request-ID` header and JSON envelope.
- Success envelope: `{ "data": <operation-specific value>, "request_id": <OpaqueId> }`.
- Error envelope: `{ "error": { "code": <stable snake_case string>, "message": <safe human-readable string>, "details": <object> }, "request_id": <OpaqueId> }`.
- `details` is always an object and defaults to `{}` when no structured details exist. It must never contain exception text, secrets, tokens, raw external content, or private records.
- OpenAPI defines concrete operation responses such as `HealthSuccessResponse`; it must not model `data` as an unconstrained generic object that erases generated operation-specific typing.

### Shared primitives

WP-00 owns only transport-level primitives needed to prevent later duplication:

- `OpaqueId`: non-empty opaque string; clients must not parse or infer type/time/ownership from it.
- `UtcTimestamp`: RFC 3339 `date-time` string normalized to UTC by servers. Exact storage precision is deferred to the record-owning WP.
- `CurrencyCode`: string enum containing only `INR` for the approved product scope.
- `MoneyINR`: `{ "amount_paise": integer, "currency": "INR" }`; `amount_paise` is a non-negative JSON safe integer from `0` through `9007199254740991`, and floating-point money is forbidden. Later domain schemas may impose tighter limits or define a separate signed adjustment type, but must not use negative `MoneyINR` values.
- `Version` and `Revision`: non-negative JSON safe-integer counters from `0` through `9007199254740991`. Record-owning WPs define initialization and increment rules.
- `Idempotency-Key`: reusable non-empty HTTP header component. WP-00 does not choose payload identity or persistence behavior for future mutations beyond the settled global `409` rule.
- `JobStatus`: stable external transport enum `queued | running | succeeded | failed`. WP-07 owns stage/progress, generations, restart, timeout repair, terminal semantics, and mapping internal states into these values. Adding or changing an enum member is a potentially breaking contract change and requires affected-consumer review.
- `AsyncAccepted`: data payload containing `job_id`, `resource_id`, and `status_url`, matching the settled product response. It is not attached to any WP-00 route.

Future WPs may add compatible fields or schemas through their required contract reviews. They may not duplicate these primitives under feature-specific names.

## Generated TypeScript API types

- Generator: exact `openapi-typescript` 7.13.0 installed in the web package.
- Destination: `web/src/api/generated/schema.d.ts`.
- The generated file is committed so branches can consume reviewed types without generation-order races.
- It begins with a generated-file notice and is never hand-edited.
- Generation reads only `contracts/openapi.yaml`, uses pinned Node/npm/generator versions, and applies pinned Prettier after generation.
- `openapi-generate` must produce byte-identical output on a second invocation.
- `openapi-check` validates the schema and AWS subset, regenerates the file, formats it, regenerates `services/api/requirements.txt`, and then uses `git diff --exit-code -- web/src/api/generated/schema.d.ts services/api/requirements.txt` to reject drift.
- CI performs the same check from a clean checkout after frozen installs.
- WP-00 generates declarations only. WP-03 owns the runtime browser client, base URL selection, authentication, fetch behavior, polling, retries, and error mapping.

## Data model and state transitions

WP-00 owns no persistent product record and no business-state transition. The health operation is stateless, creates no canonical record, and performs no external effect. The shared `Version`, `Revision`, `JobStatus`, and `AsyncAccepted` schemas are transport primitives only; record initialization/increment rules, job lifecycle semantics, and all transaction states/transitions remain with their explicitly deferred owning WPs.

## Environment and configuration policy

### Names and modes

- Server/private configuration uses the `PROOFPATH_` prefix.
- Values deliberately compiled into browser code use the `VITE_PROOFPATH_` prefix.
- `PROOFPATH_MODE=local|test|cloud` is reserved as the deployment-mode convention for later composition roots; browser code may receive `VITE_PROOFPATH_MODE` only for honest labels/presentation, never authorization or security decisions.
- When later WPs introduce adapters, `local` selects explicit local adapters, `test` deterministic test adapters, and `cloud` AWS adapters at their composition roots. WP-00 health has no mode-dependent dependency, does not read this variable, and does not implement empty adapter-selection branches.
- Fixture versus live data remains a separate domain/source mode owned by later shopping WPs and must not be conflated with deployment mode.

### Templates and secrets

- Root `.env.example` documents server/local variable names with safe dummy or blank values and comments stating which WP introduces each variable.
- `web/.env.example` contains only browser-safe `VITE_PROOFPATH_*` variables.
- Local values use untracked `.env.local` files. All `.env*` files are ignored except explicitly negated `.env.example` templates.
- Required configuration is validated once at the relevant composition root and fails fast with a safe variable-name/error-code message.
- Once a WP consumes the mode convention, unknown values fail and cloud mode must never silently fall back to deterministic/local adapters.
- Browser code must never receive secrets, AWS credentials, LocalStack tokens, access tokens, callback secrets, private URLs, or server-only configuration.
- Secrets are neither defaulted to plausible values nor printed. CI ordinary checks require none.

## Components, ports, and dependency direction

The dependency direction is:

```text
handler → application use case → domain → port → adapter
```

- Domain packages are pure and import no AWS SDK, Lambda event, FastAPI, browser, UI, persistence representation, or concrete adapter.
- Handlers translate transport values and envelopes. They contain no domain decisions.
- Application use cases orchestrate typed domain behavior and ports.
- Port protocols/interfaces are defined on the application/domain side that consumes them; adapters implement them.
- Concrete adapters are selected and constructed only in an outer composition root under the transport/worker entry point.
- Application and domain code do not inspect environment variables or branch on adapter names.
- Dependencies are passed explicitly by constructor or function parameter; no service locator or mutable global dependency registry is allowed.
- Modules in one process communicate through typed functions, not internal HTTP.

WP-00 establishes only `IdGenerator.new_id()` returning an opaque ID, because health request IDs must be server-generated and deterministic in tests. It must not encode an ID format, domain record type, persistence, or transaction behavior. A generic `Clock` is deferred until the first time-dependent WP has a real consumer. Merchant, model, speech, payment, provider, repository, job, workflow, browser, and recovery ports are explicitly deferred.

Future port locations are `services/application/ports/` when consumed by use cases and domain-local protocol modules only when a pure domain rule directly consumes them. Concrete implementations belong in their owning adapter package. Every future concrete adapter must pass a shared contract-test suite defined from the consuming port; deterministic fakes are test implementations, not alternate business logic. WP-00 tests `IdGenerator` injection through observable health/envelope behavior and does not create a generalized adapter-test framework for this one callable dependency.

The health route may use the generic `IdGenerator` for its request ID. As a transport liveness operation with no domain decision or external dependency, it need not invent a domain entity solely to traverse every layer.

## LocalStack policy

LocalStack is optional and must not be required by `setup`, `dev`, deterministic unit/contract/integration tests, `verify-gate-a`, or ordinary CI.

If enabled:

- it is an explicit Docker Compose profile and never starts implicitly;
- use the maintained authenticated distribution and an exact image tag plus immutable digest;
- `LOCALSTACK_AUTH_TOKEN` is supplied outside Git, is masked, and is never copied into browser configuration or logs;
- validate only the concrete DynamoDB, S3, and SQS API operations ProofPath expects to use;
- record LocalStack image/tag/digest, API operation, request shape, result, host OS, Docker versions, and date as compatibility evidence;
- a LocalStack pass does not claim cloud parity and cannot replace WP-01 or later AWS evidence;
- unsupported behavior remains explicit and must not be hidden behind a different local workflow engine.

## Security, privacy, and authorization

- WP-00 contains no shopper/operator authorization behavior and no AWS access.
- The health route is intentionally public, contains no private data, and performs no privileged readiness checks.
- Ordinary CI permissions are `contents: read`; job-specific permissions may only be added with a documented need.
- Ordinary CI has no AWS credentials, OIDC `id-token: write`, LocalStack token, application secrets, or production access.
- Gitleaks uses native CLI 8.30.1, not the separately licensed Gitleaks Action. `setup` downloads the publisher's platform archive into ignored `.tools/gitleaks/`, verifies it against the published release checksum before extraction, and refuses another version. CI checks repository history from a full-depth checkout with the same verified binary.
- `pip-audit` audits both `services/api/requirements.txt` and the complete frozen `uv` development environment. The development audit runs inside the already synchronized environment (for example, `uv run --frozen pip-audit`) and adds no second development export or lockfile.
- npm 12's `npm --prefix web audit` audits all dependencies in the committed web lockfile because development/build tools execute in CI.
- No credential, token, private capture, recording, evidence body, export, or realistic secret-like fixture is committed.
- Ignore-rule tests use unmistakably fake sentinel names/content and verify both ignored sensitive paths and tracked example templates.
- A vulnerability or secret-scanner suppression requires advisory/rule ID, narrow scope, reason, owner, approval, and explicit expiry/review date. Blanket ignores and unaudited baseline suppressions are forbidden.
- Baseline logs are structured JSON in deployed/server execution and include `request_id`, component, outcome, and safe error code where applicable. Health logs exclude request headers/bodies, environment values, paths, stack traces in normal output, and secrets.

## Idempotency, concurrency, timeout, and retry behavior

`GET /health` is read-only and needs no idempotency key, expected version, concurrency control, or retry state. Repeated calls create no stored or external effect and receive independently generated request IDs.

WP-00 defines reusable idempotency/version primitives only. Persistence, payload identity, duplicate results, conditional writes, timeouts, retries, and at-least-once behavior belong to the WP introducing each mutation or async flow. Those WPs remain bound by the product-wide `409`, `410`, `422`, and `404` rules.

Tool download/network retries during `setup` must be delegated to the official installer/package manager defaults or be bounded and visible. Scripts must not contain unbounded retries or arbitrary sleeps.

## Failure modes and user-visible errors

| Failure | Required result |
| --- | --- |
| Wrong/missing executable version | `setup` fails before installing dependencies, names expected and observed versions, and links to platform instructions; Gitleaks is the exception because `setup` acquires and checksum-verifies its pinned native binary. |
| Frozen lock mismatch | Installation/check fails; it must not silently update a lockfile. |
| npm peer conflict | Setup and CI fail; WP-00 cannot pass Gate A until resolved and recorded. |
| OpenAPI invalid or generated drift | `openapi-check` fails with the schema/generation stage and leaves a reviewable diff. |
| SAM requirements export drift | Check fails; generated export is regenerated from `uv.lock`, never hand-patched. |
| Docker unavailable | Containerized build reports the missing prerequisite; non-Docker deterministic tests remain runnable. |
| Optional LocalStack unavailable/token absent | Only the explicitly requested LocalStack command/profile fails; ordinary commands remain unaffected. |
| Health handler unexpected failure | Safe `500` error envelope with request ID; detailed exception is not returned. |
| Browser scaffold cannot reach health during smoke | Bounded poll fails with captured safe diagnostics; no fixed sleep is used as proof. |
| Audit/scanner finding | Security command and CI fail unless a narrow approved, unexpired suppression exists. |

## Observability and cost limits

- Health invocations emit one bounded structured result log with request ID and outcome.
- Baseline CI groups output by command and retains only useful, non-sensitive failure artifacts for a short documented period.
- WP-00 creates no standing cloud resource and incurs no required AWS cost.
- Optional LocalStack is local developer compute and must be explicitly stopped; its state is disposable and ignored.
- CI uses cancellation/concurrency to cancel an older in-progress run for the same workflow and branch/PR, except protected `main` completion must not be cancelled by an unrelated branch.
- Dependency caches are keyed by runner OS, pinned tool version, and lockfile hash. Caches store package-manager download caches, not virtual environments, `node_modules`, secrets, build output, or generated API types.

## Testing baseline

### Conventions and fixture strategy

- Python tests live under `tests/unit`, `tests/contracts`, and `tests/integration` and mirror the package under test.
- Web unit/component tests may be colocated as `*.test.ts[x]`; browser scaffold tests live under `tests/e2e` and are owned by P1 after WP-00 establishes the smoke.
- `tests/live` is reserved and excluded from deterministic CI.
- Unit tests exercise one pure unit with no filesystem/network/cloud dependency.
- Contract tests define externally observable behavior shared by a port/adapter or transport/schema implementation.
- Integration tests exercise two or more real local components while replacing external/cloud boundaries deterministically.
- Fixtures are small, reviewed, synthetic, deterministic, and labelled `fixture`; no personal captures or copied live responses are committed.
- Time, IDs, randomness, model/provider responses, and external failures are injected when introduced. Tests never rely on wall-clock sleeps; use fake time or bounded polling of observable state.
- LocalStack tests, if added, receive a separate marker/command and do not enter ordinary deterministic suites.

### Unit

- Request-ID/envelope helpers with deterministic ID injection.
- Health response construction and safe internal-error mapping.
- Root command version/parsing helpers where logic warrants tests.
- Web scaffold render with React Testing Library.

### Contract

- OpenAPI validates as 3.0.3 and contains only the approved route and primitives.
- The health handler response conforms to the generated/schema contract for success and failure.
- Health/envelope behavior proves deterministic `IdGenerator` injection without a generalized adapter contract harness.
- Generated declaration and SAM requirements outputs have no drift.

### Integration

- Invoke the packaged health handler locally with a representative API Gateway event and assert HTTP status, headers, envelope, unique request IDs, and no external calls.

### End-to-end/manual

- Playwright 1.63.0 with its matching Chromium performs two independent assertions: render the static scaffold, then call `/health` using Playwright's test request context. The web scaffold does not implement a runtime API client, base-URL abstraction, polling, or health-fetching UI.
- The smoke is bounded by observable readiness and always closes browser/context resources.
- At least one Windows and one macOS clean-clone operator execute the documented Gate A flow and record environment/command evidence.
- Full responsive journey, Firefox/WebKit coverage, accessibility audit, authentication, live backend, and product-state E2E remain WP-03/WP-11/WP-12 work.

## CI contract

`.github/workflows/checks.yml` is the only WP-00 workflow. Deployment workflows are deferred.

- Trigger on pull requests and pushes to `main`; allow manual dispatch for diagnosis.
- Use explicit `ubuntu-24.04` and a concurrency group based on workflow plus PR number/ref, with `cancel-in-progress` for superseded runs on the same non-main branch/PR.
- Default permissions are `contents: read`. No privileged pull-request target execution is allowed.
- Reference `actions/checkout` 7.0.1, `actions/setup-node` 7.0.0, `astral-sh/setup-uv` 10.1.0, and `aws-actions/setup-sam` v3 by verified full release commit SHA with a version comment. `setup-uv` provisions the pinned Python interpreter; WP-00 does not also use `actions/setup-python`. Add artifact upload only when a defined failure artifact exists.
- Checkout full history for Gitleaks. Do not persist checkout credentials after they are needed.
- Install Node/npm, uv/Python, and SAM at the exact approved versions; use `npm --prefix web ci` and frozen `uv` synchronization.
- Use safe download caches only. Cache misses must not change behavior.
- Required named checks are: `locks-and-generated`, `format-lint-type`, `unit-contract-integration`, `build`, `security`, and `web-smoke`. Jobs may share setup through scripts but must keep failure ownership clear.
- `locks-and-generated` checks lock consistency, SAM export drift, OpenAPI validity, deterministic TypeScript generation, and a clean generated diff.
- `format-lint-type` runs format-check, lint, and typecheck.
- `unit-contract-integration` runs the deterministic test suites without Docker, AWS, or LocalStack.
- `build` produces the web build and containerized SAM build.
- `security` runs the checksum-verified Gitleaks history scan, pip-audit against the production export and frozen development environment, `npm --prefix web audit`, and ignore sentinel checks.
- `web-smoke` installs only pinned Chromium through Playwright's supported dependency installer and runs the scaffold/health smoke.
- CI must finish from a clean checkout without tracked changes and without AWS or LocalStack credentials.

## Ownership and CODEOWNERS

The ownership map is:

| Area | Owner |
| --- | --- |
| `web/**`, shared UI, browser client/polling, recovery/export presentation, frontend E2E | P1 — @vanshikaxcx |
| `services/agent/**`, `services/merchants/**`, shopping intelligence and merchant evidence | P2 — @Rudransh-1508 |
| transaction semantics in `services/domain/**`, `services/simulator/**`, provider-fact contracts and commerce invariants | P3 — @a-for-aarushi |
| `infra/**`, `policies/**`, `.github/**`, AWS adapters, workers/job transport, callback ingestion and recovery/export backend | P4 — @SparshJain769 |

The resolved recovery boundary is mandatory: P3 defines what payment, order, refund, transaction transitions, provider facts, and transaction-domain reconciliation mean. P4 receives, persists, orchestrates, reconciles, and exposes those facts through P3-defined contracts. P4 must not redefine transaction semantics. P1 owns recovery/export presentation.

`CODEOWNERS` must encode static ownership without pretending it can express the entire reviewer matrix:

- direct patterns for the four fixed ownership areas above;
- P1 for `tests/e2e/**`;
- WP-specific spec patterns assigned to their POA owner where expressible;
- P4 for repository baseline files, command scripts, root toolchain configuration, and `docs/STATUS.md`.

`contracts/openapi.yaml` and `services/application/**` are deliberately not assigned to all four owners. Their producer/use-case owner and affected consumers are change-dependent and must be declared through the PR template and POA reviewer matrix. P4 may be listed as a routing reviewer for `contracts/openapi.yaml`, but that does not make P4 its universal producer or replace affected-consumer approval.

CODEOWNERS requests are routing aids. They do not transfer ownership or replace the POA approval matrix.

## CI, PR, and review workflow

The required lifecycle is:

```text
specification → spec review → SPEC APPROVED → implementation with tests
→ implementation review → IMPLEMENTATION APPROVED → squash merge
```

- No implementation begins while this document is Draft.
- No self-merge is permitted.
- This WP-00 specification requires approval from P1 and P2 because both are its named reviewers. P3 must explicitly acknowledge the shared primitives and resolved recovery boundary; if either changes in a transaction-affecting way, P3 approval is mandatory.
- The full WP-00 implementation PR requires P2's primary approval and P1's specialist approval because it touches Python/container and web/generated-client conventions. P3 approval is required only if implementation changes transaction-affecting primitives or the recovery boundary.
- P4 supplies the owner and deployment-impact attestation but never counts as an independent approval of P4's own work.
- One approval is sufficient only for a later isolated WP-00 follow-up change that touches no required specialist or two-approval category.
- Two approvals are mandatory for a breaking OpenAPI change, Cedar/IAM change, or approval/payment/order/refund state change. WP-00 must not contain the latter three categories. The initial additive OpenAPI baseline is not a breaking change; P1 approves its consumer/generation conventions and P4 documents its producer/deployment effect without self-approving.
- Any API/schema proposal identifies the owner, all affected consumers, compatibility effect, generated diff, and P4 deployment review.
- The PR includes scope/out-of-scope, linked spec, exact commands/evidence, security/privacy/cost/failure notes, and rollback path.

## Acceptance criteria

WP-00 may pass Gate A for implementation only after this Draft has no material open question and its required reviewers record `SPEC APPROVED`. WP-00 implementation is accepted only when all applicable criteria below have linked evidence.

1. **AC-00-01 — Root layout:** The current repository root contains all applicable entries in the approved skeleton and no nested ProofPath repository/root. `local/compose.yaml` is present only if optional LocalStack validation is performed and is otherwise not required.
2. **AC-00-02 — Portability:** A scan of tracked configuration/scripts finds no Soapbox-specific absolute path, remote, repository ID, user profile, drive letter, or Git-history dependency; the clean-clone procedure works in a differently named parent directory.
3. **AC-00-03 — Canonical authority:** `docs/PROOFPATH-SPEC.md` is verified against the approved source at migration, with the only content difference being the documented approved recovery ownership correction; all live references point to it, and no second copy is described as authoritative.
4. **AC-00-04 — Governance files:** MIT `LICENSE`, `docs/STATUS.md`, `LEARNING.md`, PR template, and CODEOWNERS exist and reflect the approved identities, ownership, and review rules.
5. **AC-00-05 — Tool versions:** The documented version check reports exactly the selected Node, npm, local Python, uv, and SAM versions; Docker/Desktop/Compose reports are recorded without imposing one global Desktop patch.
6. **AC-00-06 — Dependency resolution:** `npm --prefix web ci` and frozen `uv` synchronization succeed from committed lockfiles on clean environments; no root npm lockfile/install is introduced.
7. **AC-00-07 — Peer compatibility:** npm installation reports no unresolved/invalid peer dependency, and the selected React/Vite/TypeScript/ESLint/Vitest/RTL/Playwright graph is recorded.
8. **AC-00-08 — Windows clean clone:** At least one supported Windows machine completes `verify-clean-clone`; evidence records OS/architecture and all required tool/container versions and command results.
9. **AC-00-09 — macOS clean clone:** At least one supported macOS machine completes `verify-clean-clone`; evidence records OS/architecture and all required tool/container versions and command results.
10. **AC-00-10 — Formatting:** `format-check` passes from a clean checkout and `format` followed by `git diff --exit-code` creates no change.
11. **AC-00-11 — Static analysis:** `lint` and `typecheck` pass with strict TypeScript, strict mypy/Pydantic checks, zero ESLint warnings, and Ruff preview disabled.
12. **AC-00-12 — Deterministic tests:** `test-unit`, `test-contract`, and `test-integration` pass without AWS credentials, LocalStack, network merchant/model/provider calls, arbitrary sleeps, or un-injected time/IDs.
13. **AC-00-13 — OpenAPI baseline:** The OpenAPI 3.0.3 document passes pinned generator validation, the focused documented-AWS-subset contract test, and SAM validation; it contains only `GET /health`, concrete operation response types, the approved envelopes/primitives, and no speculative feature endpoint. Actual API Gateway import evidence is explicitly deferred to WP-01.
14. **AC-00-14 — Deterministic API types:** Two consecutive generation runs are byte-identical; `openapi-check` ends with `git diff --exit-code` success for `web/src/api/generated/schema.d.ts`.
15. **AC-00-15 — Stable SAM export:** `services/api/requirements.txt` regenerates from `uv.lock` using the canonical locked, production-only, hashed export command with no diff; SAM installs it successfully, and no preview `python-uv` builder/beta flag is configured.
16. **AC-00-16 — Build:** The Vite production build and `sam build --use-container` both succeed from locked dependencies; `.aws-sam` output remains untracked.
17. **AC-00-17 — Health contract:** Local invocation of `GET /health` returns `200`, `data.status=ok`, matching opaque request IDs in each application-handled envelope/header, safe JSON headers, no external calls, and the documented safe `500` envelope on injected handler failure.
18. **AC-00-18 — Browser smoke:** Pinned Playwright Chromium starts, renders the static scaffold, independently calls `/health` through Playwright's request context, and closes resources without fixed sleeps or introducing a runtime browser API client.
19. **AC-00-19 — Ignore behavior:** Disposable `.env.local`, SAM output, LocalStack state, browser sessions/traces/recordings, raw audio/captures, private evidence/exports, and OS files are proven ignored; `.env.example` templates are proven trackable.
20. **AC-00-20 — Secret scan:** The native Gitleaks CLI 8.30.1 archive is verified against its published checksum, scans full available history, and passes with no unreviewed suppression or committed credential/private artifact.
21. **AC-00-21 — Dependency audits:** pip-audit runs against both `services/api/requirements.txt` and the complete frozen `uv` development environment without an additional development export; `npm --prefix web audit` checks all dependencies in `web/package-lock.json`. Findings fail the gate unless a narrow approved, owned, expiring suppression is documented.
22. **AC-00-22 — CI:** All required jobs pass from a clean GitHub checkout on explicit `ubuntu-24.04`, using immutable action SHAs, least permissions, frozen installs, and no AWS/LocalStack/application secret.
23. **AC-00-23 — Command integrity:** Every command in this specification exists, has help/failure output, performs the stated real behavior, and no reserved later-WP command is advertised as working.
24. **AC-00-24 — Independent branches:** All four owners can create separate branches and consume the same canonical spec, OpenAPI file, generated primitives, locks, and commands without sharing a branch.
25. **AC-00-25 — LocalStack isolation:** Ordinary setup, deterministic tests, CI, and Gate A verification pass with LocalStack stopped and no token configured.
26. **AC-00-26 — Optional LocalStack evidence:** If the optional profile is enabled in WP-00, its exact pinned image/digest and the concrete validated DynamoDB/S3/SQS operations are recorded; failures are explicit and do not weaken AC-00-25. If not enabled, the criterion is marked not applicable rather than claimed passed.
27. **AC-00-27 — Clean final tree:** From the committed WP-00 PR head, all checks leave `git status --short` empty; no generated, downloaded-tool, build, or test artifact is accidentally tracked. During pre-commit development, any non-empty status must match the explicitly reviewed WP-00 change set rather than being described as clean evidence.
28. **AC-00-28 — Ownership boundary:** The canonical `docs/PROOFPATH-SPEC.md`, the POA, AGENTS.md, and ownership routing consistently state the approved P3/P4/P1 recovery split. The stale product-spec ownership row is corrected in the canonical migrated document, and the stale POA ownership row is narrowly corrected, without changing transaction semantics or unrelated content.

### Acceptance evidence format

The implementation PR maps each criterion to command output, test name, diff, or reviewer acknowledgment. Machine evidence records commit SHA, date, OS/architecture, tool versions, and pass/fail. Screenshots may supplement but never replace command/test output.

## Deliverables

WP-00 implementation is expected to create, migrate, or update the following. Exact supporting filenames may vary only when the implementation PR explains an equivalent simpler layout and reviewers approve it.

| Deliverable | Action | Purpose |
| --- | --- | --- |
| `docs/specs/WP-00-repository-toolchain-contract-baseline.md` | approve/update status | Package contract and acceptance authority. |
| `docs/PROOFPATH-SPEC.md` | create by verified migration with the approved ownership correction | Single canonical product specification with the resolved P3/P4/P1 recovery boundary. |
| `Final idea and archi/PROOFPATH-SPEC.md` | label historical/migrated or remove | Prevent competing authoritative copies. |
| `AGENTS.md` | update references only as needed | Point agents to canonical spec and resolved ownership. |
| `Final idea and archi/PROOFPATH-IMPLEMENTATION-POA.md` | narrowly correct stale ownership row | Remove the P3/P4 recovery-handler contradiction; no broader POA rewrite. |
| `docs/STATUS.md` | create | WP ownership/dependency/gate status ledger. |
| `README.md` | create | Supported setup, commands, boundaries, prerequisites, and evidence instructions. |
| `LEARNING.md` | create | Append-only team learning record required by the POA. |
| `LICENSE` | create | Standard MIT license. |
| `.gitignore`, `.editorconfig` | create/update | Secret/artifact exclusion and cross-platform text conventions. |
| `.env.example`, `web/.env.example` | create | Safe server/browser configuration templates. |
| `.node-version`, `.python-version`, `uv.toml` | create | Exact executable/runtime requests. |
| root `package.json` | create | Private command aliases and npm executable metadata; no workspace framework. |
| `pyproject.toml`, `uv.lock` | create | Python metadata, strict tool configuration, and exact dependency graph. |
| `services/api/requirements.txt` | create as generated file | Stable, production-only, hashed SAM pip-builder input derived from `uv.lock`. |
| `contracts/openapi.yaml` | create | OpenAPI 3.0.3 source with health and shared primitives. |
| `web/package.json`, `web/package-lock.json` | create | Exact web dependencies and transitive lock. |
| web TypeScript/Vite/ESLint/Vitest/Prettier configs | create | Strict build, format, lint, type, and unit-test behavior. |
| `web/index.html` and minimal `web/src/**` scaffold | create | Honest render target for baseline smoke, without feature UI. |
| `web/src/api/generated/schema.d.ts` | generate and commit | Browser-facing API declarations. |
| `services/**` package markers/boundary docs | create | Establish ownership/dependency locations without feature implementation. |
| minimal health transport/application support | create under `services/api` as applicable | Implement only the liveness contract and composition root. |
| `infra/template.yaml` | create | Minimal SAM definition for the health API/Lambda; no feature/cloud estate. |
| `local/compose.yaml` | create only if optional LocalStack is validated | Explicit authenticated optional DynamoDB/S3/SQS profile. |
| `scripts/proofpath.ps1` and focused helper modules | create | Cross-platform canonical command surface, including checksum-verified native Gitleaks acquisition. |
| `tests/unit/**`, `tests/contracts/**`, `tests/integration/**` | create | Baseline deterministic Python/transport tests. |
| `tests/e2e/**` Chromium smoke | create | Scaffold and health browser verification. |
| `.github/CODEOWNERS` | create | Ownership-based review routing. |
| `.github/pull_request_template.md` | create | Enforce spec, scope, evidence, security, and rollback fields. |
| `.github/workflows/checks.yml` | create | Ordinary least-privilege deterministic CI. |
| Gate A evidence referenced by the PR/status file | produce without secrets | Windows/macOS/CI/tool/build/generation/security evidence. |

No deployment workflow, feature handler, feature schema, or empty promise script is a WP-00 deliverable.

## Deferred work

- **WP-01, P4:** real AWS access checkpoint, authenticated cloud skeleton, service feasibility, and cloud evidence.
- **WP-02, P3:** canonical domain records, value objects beyond shared transport primitives, deterministic business rules, transitions, and transaction-domain ownership foundations.
- **WP-03, P1:** web routing/auth, runtime generated-type client, polling, shared async UI states, and reusable cards.
- **WP-04, P2:** agent container, model/browser ports, merchant registry/connectors, external-content controls, and deterministic merchant/model fixtures.
- **WP-05, P1:** conversation, voice, photo, usual-basket UI/use cases and speech/upload integration contracts.
- **WP-06, P2:** matching, compatible units, fees, comparison, repair, freshness, ranking, and fixture/live separation.
- **WP-07, P4:** DynamoDB persistence model, job/outbox/event contracts, queues/workflows/DLQs, projections, generations, retries, and job-status semantics beyond the baseline enum.
- **WP-08, P3:** preparation, quote/hash, exact touch approval, version/idempotency transaction behavior, and approve/cancel races.
- **WP-09, P3:** simulator, checkout, provider keys/facts, callback contract, payment/order/refund state meaning, transaction reconciliation rules, and commerce invariants.
- **WP-10, P4:** callback transport/ingestion, durable recovery orchestration, persistence, reconciliation application workflows, recovery handlers, guidance/case/export backend against P3 contracts.
- **WP-11, P1:** integrated shopper/operator and recovery/export presentation plus full journey E2E.
- **WP-12, P4 with all owners:** security/resilience drills, full cloud verification, deployment/OIDC, monitoring/costs, release, teardown, broader browser/accessibility evidence.

Toolchain upgrades to React 19.3, TypeScript 7, Vitest 5, SAM's preview uv builder, or additional LocalStack services require later evidence and an approved maintenance/specification change; they are not opportunistic WP work.

## Implementation staging

This sequence is a plan, not implementation authorization. Each stage stops on failed validation; do not mask a failure by beginning the next stage.

### Stage 1 — Canonical documentation and governance

Scope: migrate/verify the canonical product spec; create status, learning, license, README governance sections, PR template, CODEOWNERS, and narrow reference/ownership corrections.  
Areas: `docs/**`, `AGENTS.md`, `Final idea and archi/**` narrow corrections, root governance files, `.github/CODEOWNERS`, PR template.  
Validate: source/copy comparison, authority-link scan, ownership review, MIT text, Git status/diff, AC-00-01 through AC-00-04 and AC-00-28.  
Stop if: two authoritative product specs remain, ownership conflicts remain, or unrelated historical text changes.

### Stage 2 — Version files, locks, configuration, and command shell

Scope: add version metadata, root/web manifests, Python configuration, ignore/editor/environment templates, and command dispatcher with version/help/setup behavior.  
Areas: root config, `web` manifests/config, `scripts/**`.  
Validate: exact version checks, clean frozen resolution, peer graph, ignore sentinels, cross-platform static review, AC-00-05 through AC-00-07, AC-00-19, AC-00-23.  
Stop if: a selected version cannot resolve on supported platforms, lockfiles mutate under frozen install, or a secret path is trackable.

### Stage 3 — OpenAPI and generated declarations

Scope: create OpenAPI health/primitives, validation/generation commands, and committed TypeScript declarations.  
Areas: `contracts/**`, generated API directory, generator configuration/tests.  
Validate: pinned generator validation, focused documented-AWS-subset contract tests, SAM validation, two-run generation identity, clean diff, AC-00-13 and AC-00-14.  
Stop if: generation differs by run/platform, schema introduces future endpoints, or unsupported OpenAPI features appear.

### Stage 4 — Package skeleton and deterministic baseline tests

Scope: create documented package boundaries, health `IdGenerator` injection, minimal health implementation, web scaffold, and unit/contract/integration tests.  
Areas: `services/**`, `web/src/**`, `tests/unit|contracts|integration`.  
Validate: format, lint, strict types, deterministic suites, architecture import checks, health success/failure contract, AC-00-10 through AC-00-12 and AC-00-17.  
Stop if: feature behavior/ports enter the diff, domain imports infrastructure, or tests require cloud/network/sleeps.

### Stage 5 — SAM and browser build/smoke

Scope: add minimal SAM template, locked requirements export, Vite build, Playwright Chromium smoke, and `dev`/`build` orchestration.  
Areas: `infra/**`, health requirements, Playwright/Vite config, `tests/e2e/**`, scripts.  
Validate: export drift, containerized SAM build, Vite build, bounded Chromium smoke, clean resource shutdown, AC-00-15, AC-00-16, AC-00-18.  
Stop if: SAM beta uv is required, browser versions mismatch, build needs AWS credentials, or artifacts become tracked.

### Stage 6 — Security and CI

Scope: Gitleaks, dependency audits, safe caches, immutable actions, CI jobs/concurrency, and full Gate A command.  
Areas: security configuration, scripts, `.github/workflows/checks.yml`.  
Validate: local security command, full clean-checkout CI, permission review, cache review, no secret requirement, AC-00-20 through AC-00-22 and AC-00-27.  
Stop if: an unreviewed finding/suppression remains, an action floats, ordinary CI receives privileged permissions/credentials, or CI dirties the tree.

### Stage 7 — Cross-platform Gate A evidence

Scope: fresh Windows and macOS clones in differently named directories; optional LocalStack API validation if the profile is enabled.  
Areas: evidence/status/learning documentation only after commands are fixed.  
Validate: complete `verify-clean-clone`, compare generated hashes and outcomes, record Docker versions/licensing reminder, AC-00-02, AC-00-08, AC-00-09, AC-00-24 through AC-00-26.  
Stop if: either platform needs an undocumented divergent path, generated content differs, or LocalStack leaks into ordinary setup.

### Stage 8 — Final scope/diff review

Scope: map all acceptance criteria, remove accidental artifacts, and obtain required implementation reviews.  
Areas: entire WP-00 diff; no new behavior.  
Validate: `verify-gate-a`, clean status expectation, secret scan, deliverable inventory, reviewer matrix, and every AC evidence link.  
Stop if: any required criterion is unsupported, another owner's feature area was implemented, or a material question emerged.

## Rollout, rollback, and fixture strategy

WP-00 rolls out only by the approved PR workflow. It has no deployed migration or production data.

If a stage fails:

- stop at that stage and preserve diagnostic output;
- use `git status`, scoped diffs, and the last reviewed commit to identify only WP-00 changes;
- repair forward in a small commit when safe;
- if reversal is required, use a normal revert commit/PR or manually reverse the specific WP-00 patch with review;
- never use `git reset --hard`, destructive checkout, broad deletion, history rewriting, or removal of another contributor's files;
- do not regenerate locks/types with a different tool version as an undocumented workaround;
- keep `main` buildable; if merged WP-00 makes `main` red, revert the isolated squash commit through a normal PR before feature merges continue.

Synthetic baseline fixtures consist only of health events/responses, fake IDs/times, safe configuration sentinels, and the minimal web smoke. They must be deterministic and clearly labelled. No live capture becomes a fixture.

## Open questions and decisions

### Settled decisions encoded by this specification

- Current Soapbox root is the current ProofPath root; portability to a later official competition repository is mandatory.
- Team identities, ownership, MIT license, Windows/macOS support, canonical spec migration, optional LocalStack, and Docker Desktop policy are settled by human decision.
- The P3/P4 recovery boundary is the approved split-by-boundary model stated above.
- Version/tool selections and compatibility policies are the approved research recommendations.
- OpenAPI 3.0.3, stable SAM pip building from a uv-locked export, conservative React/TypeScript/Vitest choices, immutable CI actions, and CLI-based Gitleaks are settled technical defaults.

### Minor implementation decisions made explicit here

- Use one metadata-only root npm package and one real `web` npm package; do not introduce npm workspaces yet.
- Use one cross-platform `pwsh ./scripts/proofpath.ps1 <command>` orchestration surface.
- Generate declarations at `web/src/api/generated/schema.d.ts`.
- Make health a dependency-free public liveness exception with a server-generated request ID in each application-handled response header and envelope.
- Define only an opaque IdGenerator dependency at WP-00; defer Clock and runtime adapter-mode dispatch until a real consumer exists.
- Use Chromium only for the WP-00 browser smoke.
- Keep the LocalStack profile explicit and separate from ordinary `dev`.

These choices are reversible within WP-00 review, do not choose feature behavior, and optimize for a four-person three-day implementation.

### Known authoritative-document contradiction

The source product specification's Section 10 ownership row assigns callbacks, reconciliation, and guidance/export to P3, and the POA ownership table near its collaboration section assigns `recovery/export handlers` to P3. These stale rows conflict with the POA's P4 role definition, its resolved-boundary prose, WP-10, AGENTS.md, and the approved human decision. The approved interpretation is:

- P3 owns transaction truth, transaction state meaning/transitions, simulator behavior, provider-fact contracts, transaction-domain reconciliation rules, and commerce invariants.
- P4 owns callback ingestion, durable platform/persistence/orchestration, reconciliation application workflows, recovery handlers, and guidance/case/export backend against P3 contracts.
- P1 owns recovery/export presentation.

During canonical product-spec migration, WP-00 implementation must narrowly correct the stale product-spec row and must also narrowly correct the stale POA row, as required by AC-00-03 and AC-00-28. It must not change unrelated authoritative content or use either correction to move transaction semantics into P4.

### Unresolved questions

None. Any newly discovered material ambiguity stops implementation and returns this specification to Draft review.
