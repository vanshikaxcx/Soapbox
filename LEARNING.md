# ProofPath learning log

Append dated, concrete findings, failed assumptions, and decisions here. Do not rewrite earlier entries; link evidence or the approving work package when relevant.

## 2026-09-15 — WP-00 Stage 1

- Decision: `docs/PROOFPATH-SPEC.md` is the single canonical product specification. The former source under `Final idea and archi/` is retained only as labelled historical migration material.
- Decision: P3 owns transaction truth and semantics, simulator behavior, provider facts, transaction-domain reconciliation rules, and commerce invariants. P4 owns callback ingestion, durable reconciliation/recovery machinery, recovery handlers, and the guidance/case/export backend. P1 owns recovery/export presentation.

## 2026-09-15 — WP-00 Stage 2

- Finding: `openapi-typescript` 7.13.0 declares a TypeScript `^5.x` peer. The approved WP-00 amendment pins TypeScript 5.9.3 rather than 6.0.0 so npm 12 can resolve the graph without `--force` or `--legacy-peer-deps`.
- Finding: Vite 8.3.0 requires the compatible supporting `@vitejs/plugin-react` 6.1.1; ESLint 10.10.0 requires the compatible supporting `eslint-plugin-react-hooks` 7.1.1. These are supporting-package selections, not changes to listed primary pins.
- Decision: `web/package.json` declares `"type": "module"` so the approved ESM Vite and ESLint configuration files load without Node's module-type warning.

## 2026-09-17 — WP-00 Stage 5

- Finding: `sam build --use-container` must pass an exact `--build-image` digest reference (`public.ecr.aws/sam/build-python3.12@sha256:6b977f28341c892f743070ef945b600f1b257b668003720dc3bc9b1839fcd666`, verified against SAM CLI `1.164.0`'s `latest-x86_64` resolution) to satisfy the repository-controlled immutable-image requirement; an unpinned `--use-container` invocation is not sufficient.
- Finding: SAM CLI's own internal image-pull path (via docker-py) can intermittently report `Failed to download a new <image>. Invoking with the already downloaded image.` even immediately after a `docker pull` of the same digest completes and verifies successfully. This is harmless because digest references are content-addressed: a locally cached image matching the pinned digest is guaranteed byte-identical to a fresh pull. Contributors should not treat this message alone as evidence of a broken or stale pin; treat it as a SAM CLI pull-path quirk, not a build-image defect.

## 2026-09-17 — WP-00 Stage 6

- Finding: `uv run --frozen pip-audit` against the complete frozen development environment reports the local editable `proofpath` project itself under a `Name / Skip Reason` table (`Dependency not found on PyPI and could not be audited`), alongside `No known vulnerabilities found` for everything else. This is expected pip-audit behavior for a local-only editable package and is not a failure or a suppression; do not interpret that skip line as an unreviewed finding.
- Finding: `aws-actions/setup-sam` only publishes floating major tags (`v0`–`v3`), with no finer concrete semver release to pin to. `.github/workflows/checks.yml` pins the exact commit SHA that `v3` currently resolves to, with a dated comment recording when/how it was resolved, since a bare `@v3` reference would float.
- Decision: `.github/workflows/checks.yml` invokes the same `pwsh ./scripts/proofpath.ps1 <command>` surface used locally (`openapi-check`, `format-check`/`lint`/`typecheck`, `test`, `build`, `security`, `web-smoke`) rather than reimplementing check logic in YAML, so CI and local verification cannot drift apart.

## 2026-09-17 — WP-00 Stage 7

- Finding: plain `git status --porcelain` (no `--ignored` flag) already omits ignored paths entirely, so `.aws-sam/`, `node_modules/`, and `.tools/` never appear even as `??` lines. `verify-gate-a`'s "no tracked changes" assertion only needs to reject any line that is not a bare `??` (i.e. any tracked-file modification); it does not need to special-case known build-artifact directories.
- Decision: `verify-gate-a` composes the existing `Invoke-Stage*`/`Invoke-OpenApiCheck` functions in sequence rather than re-implementing any check, and uses `Test-RequiredVersions` (which throws on mismatch) rather than `Show-Versions` (which only prints and never fails) for its version gate.
- Decision: `verify-clean-clone` cannot verify a checkout is genuinely a fresh clone from within the script itself; it instead rejects a checkout that is already dirty at start, which is the verifiable proxy the WP-00 spec's "reject an already dirty checkout as evidence" wording asks for. Actual freshness is an operator/evidence-collection responsibility (running the command from a real fresh clone), not something the script can prove.
- Finding: a pre-push audit of the working tree against the WP-00 spec's required skeleton (done before the first commit, since nothing had been committed through Stages 1-7) found 7 missing entries that earlier stage approvals had not caught: root `AGENTS.md`; top-level `workflows/`, `policies/`, `guidance/` boundary directories; `web/src/pages/` and `web/src/components/`; and `tests/live/`. All were added as either a pointer file (`AGENTS.md` → `CLAUDE.md`, per explicit user decision to avoid duplicated/drifting instructions) or one-line ownership/reservation markers matching the existing `services/*/README.md` convention. Future stage reviews should diff the actual filesystem against the spec's required-skeleton tree explicitly, not just trust that prior stage sign-offs covered it.
- Finding: the first real Windows clean-clone evidence run (Stage 7) caught a genuine cross-platform bug the original development machine could never surface: Stage 2's `.gitattributes` only forced `eol=lf` for a narrow allowlist (root config, `scripts/**`, `web/**`), missing `contracts/openapi.yaml`, `services/**`, `tests/**`, `docs/**`, `infra/**`, and other repository-controlled text. On a fresh Windows clone, Git's default `core.autocrlf` converted `contracts/openapi.yaml` to CRLF, and `tests/contracts/openapi-contract.test.mjs`'s raw-text regex match (`\n`-only) failed against it. Fixed by broadening `.gitattributes` to force `eol=lf` across all repository-controlled text trees; verified no file's actual committed content needed changing (everything was already LF at the source, this was a checkout-normalization gap only). This is exactly the class of defect cross-platform Gate A evidence exists to catch before merge.
