# WP-00 — Repository, toolchain, and contract baseline

Owner: P4
Reviewers: P1 (web conventions), P2 (Python/container conventions)
Status: Draft
Depends on: None

## Outcome and user value

Every team member can `git clone`, install, build, type-check, lint, and test their owned area independently, against the same generated types and error/ID/timestamp/money conventions, without waiting on anyone else's code to exist. This is the precondition for all other work packages — no feature implementation starts before this merges (POA §6).

## In scope

- Repository tree matching SPEC §5.
- Pinned toolchain versions (Node, Python, package managers, Docker, SAM, Playwright).
- Formatter / linter / type-checker / test-runner commands for both Python and TypeScript.
- Dependency lock strategy.
- Environment-variable naming convention and `.env.example`.
- Initial OpenAPI contract: error envelope, ID format, timestamp format, money representation, version/idempotency header semantics, job-status shape, health route.
- Generated-TypeScript-client process and a CI drift check.
- Deterministic adapter interface convention (how a port gets a real AWS adapter and a test adapter side by side).
- One API health route, one web render smoke test.
- `.gitignore` covering secrets, SAM output, browser sessions, audio, captures, exports.
- PR template and ownership table (already defined in POA §2, referenced not duplicated here).
- `LEARNING.md` for running technical-decision notes.
- `docs/STATUS.md` for daily package-state tracking (POA §9).

## Out of scope

- Any AWS deployment (that's WP-01).
- Real domain rules (WP-02), real merchant connectors (WP-04), real UI routes beyond a smoke test (WP-03).
- CI steps that require live AWS credentials or live merchant access.

## User flow and UI states

N/A — this package has no end-user-facing behavior. The "user" is the other three team members.

## API and event contracts

Establishes, in `contracts/openapi.yaml`:

- **Error envelope:** `{"error": {"code": string, "message": string, "details": object|null}, "request_id": string}`
- **Success envelope:** `{"data": object, "request_id": string}`
- **IDs:** opaque strings, ULID-formatted (`^[0-9A-HJKMNP-TV-Z]{26}$`), never client-supplied for server-owned records.
- **Timestamps:** UTC ISO-8601 with `Z` suffix, e.g. `2026-09-15T13:25:44.293186Z`.
- **Money:** integer paise, never a decimal/float field, field names suffixed `_paise`.
- **Concurrency:** mutations accept an `Idempotency-Key` header and an `expected_version`/`expected_revision` body field. Same key + different payload → `409`. Stale version → `409`. Invalid input → `422`. Expired resource → `410`. Inaccessible/not-found → `404`.
- **Async commands:** return `202 {data: {job_id, resource_id, status_url}, request_id}` immediately after an atomic domain+job+outbox commit.
- **Health route:** `GET /health` → `200 {"data": {"status": "ok", "time": <timestamp>}, "request_id": ...}`, unauthenticated.

## Data model and state transitions

None owned by this package. This package only fixes the *shape* conventions (ID/timestamp/money/version) that WP-02's real records must follow.

## Components, ports, and dependency direction

Establishes the layering all services must respect (SPEC §5):

```
handler → application use case → domain → port → adapter
```

- `services/domain/` — pure Python, no AWS SDK / FastAPI / Lambda-event / browser imports. Enforced by a lint rule (import-linter or equivalent) added in this package.
- `services/application/` — use cases, typed ports (protocols/ABCs).
- `services/adapters/` — concrete AWS and deterministic-test implementations of those ports, selected by environment/DI at the composition root, never by branching inside application code.
- `services/api/` — Lambda HTTP handlers; thin, delegate to application use cases.
- `services/workers/` — Step Functions task handlers; same rule.
- `web/src/{pages,components,api}/` — React/TS, strict mode, typed client generated from `contracts/openapi.yaml`.

## Security, privacy, and authorization

- `.gitignore` blocks `.env`, AWS SAM build output, Playwright/browser session state, captured audio/images, exports, `.aws-sam/`.
- No secrets committed; `.env.example` documents variable *names* only, never real values.
- CI has no AWS credentials at this stage (added in WP-01/WP-12 for the smoke-test workflows only).

## Idempotency, concurrency, timeout, and retry behavior

Defined as the contract in "API and event contracts" above; not implemented against real state until WP-02/WP-07/WP-08 exist. This package's job is to make the convention unambiguous and machine-checkable (OpenAPI schema), not to implement it.

## Failure modes and user-visible errors

N/A (no user-visible behavior in this package beyond the health route, which has no failure states other than process-down).

## Observability and cost limits

- Structured JSON logging convention documented in README: every log line includes `request_id` at minimum; `job_id`/`execution_arn`/aggregate ID+version are added by the packages that own those concepts.
- No cost-bearing resources created by this package (no AWS calls).

## Test plan

### Unit
- Python: `pytest` runs and passes on a clean clone with zero tests failing (placeholder test for the health route logic).

### Contract
- OpenAPI file lints clean (e.g. `redocly lint` or `openapi-spec-validator`).
- Generated TypeScript client has zero uncommitted diff after regeneration (drift check).

### Integration
- N/A at this stage.

### End-to-end/manual
- Clean clone → documented setup commands → build/lint/type-check/test all green, for both `web/` and Python services, without needing AWS credentials or network access beyond package installation.

## Acceptance criteria

- [ ] `git clone` + documented setup commands succeed with no manual fixes.
- [ ] `make lint` / equivalent passes for Python and TypeScript.
- [ ] `make typecheck` passes strict mypy (or equivalent) and strict `tsc`.
- [ ] `make test` runs Python unit tests and the web smoke test, all green.
- [ ] `contracts/openapi.yaml` validates; generated TS client has no drift.
- [ ] `GET /health` works locally (SAM local or plain uvicorn) and returns the documented envelope.
- [ ] `.gitignore` verified to exclude `.env`, SAM output, browser session state, audio, captures, exports (tested by attempting to `git add` a dummy file of each kind and confirming it's ignored).
- [ ] All four members can create independent branches off `main` and consume the same generated primitives without contacting each other first.

## Rollout, rollback, and fixture strategy

No deployment. If a convention decided here needs to change later (e.g. error envelope shape), it goes through the normal API/schema-change approval path (POA §2: owning producer + every affected consumer approve, P4 confirms generated-contract and deployment effect).

## Open questions and decisions

- Exact Bedrock model ID, Polly voice, AWS region: deferred to WP-01 checkpoint, not decided here.
- Whether import-linter (Python) is worth the setup time in a 3-day hackathon vs. a documented convention + code review discipline: **decision — documented convention only; skip automated enforcement to save setup time**, revisit only if a violation actually happens.
