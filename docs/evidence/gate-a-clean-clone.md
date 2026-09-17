# WP-00 Gate A — cross-platform clean-clone evidence

Per `docs/specs/WP-00-repository-toolchain-contract-baseline.md` AC-00-08 and AC-00-09: at least one supported Windows machine and one supported macOS machine must complete `verify-clean-clone` from a genuinely fresh clone in a differently-named directory.

## Windows — AC-00-08 — PASS

- **Date:** 2026-09-17
- **Commit tested:** `9c9f715a0615dcabd8663ed8c6f29b9bb3369fa9` (`feat/wp-00-repo-baseline-p4`) — confirm this matches `git rev-parse HEAD` in the tested clone before treating this as final evidence.
- **OS:** Windows NT 10.0.26200.0 (Windows 11), 64-bit
- **Docker Engine:** 27.2.0
- **Docker Compose:** v2.29.2-desktop.2
- **Clone method:** fresh `git clone` into a new, differently-named directory (`proofpath-clean-clone-win6`, following `proofpath-clean-clone-win` through `-win5` as earlier attempts surfaced and fixed real defects — see below), never reused from the primary development checkout.
- **Command:** `pwsh ./scripts/proofpath.ps1 verify-clean-clone`
- **Result:** `2 passed (3.9m)`. Final output: `Gate A: versions, openapi-check, format-check, lint, typecheck, test, security, build, and web-smoke passed with no tracked changes.` / `verify-clean-clone: setup and Gate A completed from a clean checkout.`

### Defects found and fixed during this evidence-gathering process (see `LEARNING.md` for full detail)

The first five attempts on this same Windows machine failed, each surfacing a genuine defect invisible on the original development machine (which carried undocumented ambient state — cached tools, prior AWS/GCP configuration, cached Docker images — masking each one). None were environment-specific flukes; all were fixed in the repository:

1. Toolchain not yet installed at pinned versions (Python 3.12.14, uv, Node 24.21.0, npm 12.0.2) — operator install/PATH issue, not a repo defect, but exposed that `python.org` no longer ships a 3.12.14 Windows installer (Python 3.12 is security-fixes-only upstream); documented `uv python install 3.12.14 --default` as the working alternative.
2. `.gitattributes` did not force LF line endings for `contracts/openapi.yaml`, `services/**`, `tests/**`, `docs/**`, `infra/**`, and other repository-controlled text — a fresh Windows checkout's CRLF conversion broke a raw-text contract test. Fixed by broadening `.gitattributes` coverage to every repository-controlled text tree.
3. `sam validate` failed with "AWS Region was not found" on a host with zero AWS configuration, despite performing no real AWS calls. Fixed with a scoped placeholder region around local-only SAM invocations (`Invoke-WithScopedAwsRegion`).
4. Four `npm exec -- <tool> -- <args>` invocations had a redundant second `--` that broke `prettier --write`/`--check` (parsed as file glob patterns instead of flags) — fixed by removing the redundant separator in all four call sites.
5. The same missing-region exposure existed in `sam local start-api` (used by `dev` and `web-smoke`), not just `sam validate` — fixed proactively across all three call sites once the pattern was identified.
6. Operator's personal Docker credential-store configuration (`~/.docker/config.json` `credHelpers` pointing stale/expired `gcloud` auth at unrelated GCR registries, from prior non-ProofPath work) broke every Docker image build, since Docker resolves credentials for all configured registries regardless of which one is actually being pulled. Machine-specific, not a repo defect; resolved by removing the stale `credHelpers` entries.
7. SAM Local's first-ever invocation on a cold host must pull the Lambda Runtime Interface Emulator base image and then build a function image on top of it, which took several minutes — the original 60-second `webServer` readiness timeout was far too short. Raised to 1200s (20 minutes) in both `playwright.config.ts` and `Invoke-Stage5Dev`; this is a one-time cost per Docker image cache.

## macOS — AC-00-09 — PENDING

Not yet performed. Queued with a teammate who has macOS hardware access.
