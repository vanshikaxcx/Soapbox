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

## macOS — AC-00-09 — PASS

- **Date:** 2026-09-17
- **Commit tested:** `c8a5efff2d9b49c883e583da1d5db6bad44e2b92` (`feat/wp-00-repo-baseline-p4`) — confirm this matches `git rev-parse HEAD` in the tested clone before treating this as final evidence.
- **OS:** macOS 15.7.3 (BuildVersion 24G419), arm64 (Apple Silicon)
- **Docker Engine:** 28.5.1
- **Docker Compose:** v2.40.2-desktop.1
- **Clone method:** fresh `git clone` into `proofpath-clean-clone-mac`, never reused from any other checkout.
- **Command:** `pwsh ./scripts/proofpath.ps1 verify-clean-clone`
- **Result:** `2 passed (3.2m)`. Final output: `Gate A: versions, openapi-check, format-check, lint, typecheck, test, security, build, and web-smoke passed with no tracked changes.` / `verify-clean-clone: setup and Gate A completed from a clean checkout.` / `EXIT_CODE=0`.

### Defects/findings during this evidence-gathering process (see `LEARNING.md` for full detail)

- Everything through the Vite production build passed cleanly on the first attempt: exact tool versions (worked around three machine-specific toolchain gaps — no python.org 3.12.14 installer on any platform, this machine's Homebrew SAM CLI install independently broken, Homebrew's `powershell` cask no longer existing — none were repository defects), Gitleaks, both `pip-audit` runs, `npm audit`, OpenAPI/SAM validation, format/lint/typecheck, and all unit/contract/integration tests.
- First attempt failed at the containerized build step: `Could not find public.ecr.aws/sam/build-python3.12@sha256:...` image locally and failed to pull it from Docker, alongside SAM CLI's own warning about cross-architecture emulation (this x86_64-pinned function build running on an arm64 host). Manual pull attempts showed partial-transfer failures (TLS handshake timeout, then EOF on a different layer) — the same network-flakiness signature already seen on Windows earlier in WP-00, not a hard architecture-incompatibility failure.
- Retrying the pull explicitly with `docker pull --platform linux/amd64 <digest>` succeeded, and the full `verify-clean-clone` run then passed completely on retry.
- Explicit decision recorded (user call, not silently resolved): keep the Lambda function's architecture at its implicit `x86_64` default for now. `infra/template.yaml` never actually declared an `Architectures:` property — this was SAM's silent default, not a prior team decision. Real AWS deployment target architecture (x86_64 vs Graviton/arm64) is deferred to WP-01; Mac developers pay an emulation/network-exposure cost on local WP-00 builds until then.
