# ProofPath

ProofPath is a voice-first web application for comparing locality-specific grocery baskets and demonstrating safe simulated checkout with evidence-based recovery. Checkout, payment, orders, callbacks, and refunds are simulated: **Simulated checkout · no money moved · no retailer order placed.**

## Governance and authority

- The settled product and architecture authority is [docs/PROOFPATH-SPEC.md](docs/PROOFPATH-SPEC.md).
- The execution plan, work packages, ownership, and review gates are in [Final idea and archi/PROOFPATH-IMPLEMENTATION-POA.md](Final%20idea%20and%20archi/PROOFPATH-IMPLEMENTATION-POA.md).
- [docs/STATUS.md](docs/STATUS.md) is the current package-status ledger; [LEARNING.md](LEARNING.md) is append-only.
- `ideation/` and the retained `Final idea and archi/PROOFPATH-SPEC.md` are historical material and are not implementation authority.

## Current baseline

WP-00 Stage 5 establishes the baseline health Lambda, Vite production build, and Chromium smoke. It does not implement product flows, a runtime browser API client, authentication, cloud deployment, or LocalStack.

### Stage 2 prerequisites and commands

Install these exact prerequisites before setup: [Node.js `24.21.0`](https://nodejs.org/dist/v24.21.0/), npm `12.0.2` (`npm install --global npm@12.0.2` after installing Node), [uv `0.12.13`](https://docs.astral.sh/uv/getting-started/installation/), [PowerShell 7](https://learn.microsoft.com/powershell/scripting/install/installing-powershell), and [SAM CLI `1.164.0`](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html).

CPython `3.12.14` has **no official binary installer on any platform** — Python 3.12 entered upstream "security fixes only" mode and python.org only ships source tarballs for this version. After installing uv, use uv's own independent Python toolchain instead:

```text
uv python install 3.12.14 --default
python --version
```

This must print `Python 3.12.14`; if a different Python (from Homebrew, conda, pyenv, or similar) still wins on `PATH`, ensure uv's shim directory takes priority.

If your platform's package manager for SAM CLI is broken or unavailable, `uv tool install aws-sam-cli==1.164.0` is a working platform-independent alternative. If your platform's package manager has no `pwsh` package, the portable release tarball from the PowerShell link above needs no elevated privileges to install.

Docker Desktop is not required for Stage 2 setup. Later `build`, `dev`, and Gate A work require Docker Desktop, Docker Engine, and `docker compose`; use the [Docker Desktop requirements](https://docs.docker.com/desktop/setup/install/windows-install/) for the supported Windows version, virtualization, and WSL2-backend requirements. Enable Windows long paths through the documented [Win32 long-path policy](https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation) before installing deep npm dependency trees. On macOS, use Docker's supported [Mac installation requirements](https://docs.docker.com/desktop/setup/install/mac-install/) and select the Intel or Apple Silicon installer matching the host architecture. Docker Desktop licensing remains subject to the applicable license terms; this project does not claim it is universally free.

From the repository root, use:

```text
pwsh ./scripts/proofpath.ps1 versions
pwsh ./scripts/proofpath.ps1 setup
```

`setup` verifies the exact prerequisite versions before dependency installation, downloads and checksum-verifies Gitleaks `8.30.1` into ignored `.tools/`, performs frozen uv/npm installs, and installs the pinned Playwright Chromium. It does not request AWS or LocalStack credentials. Root `npm` aliases expose the implemented WP-00 commands; use the PowerShell command surface as the canonical interface.

With Docker Desktop's Linux engine available, the Stage 5 commands are:

```text
pwsh ./scripts/proofpath.ps1 build
pwsh ./scripts/proofpath.ps1 dev
pwsh ./scripts/proofpath.ps1 web-smoke
```

`build` creates `web/dist` and performs the release-equivalent containerized SAM build. `dev` starts only the Vite scaffold at `http://127.0.0.1:5173` and SAM Local health API at `http://127.0.0.1:3001/health`; Ctrl+C shuts both down. `web-smoke` starts those services with bounded readiness checks and runs the Chromium scaffold and independent health-request assertions. None of these commands starts LocalStack or requests AWS credentials.

The containerized SAM build uses an exact, repository-controlled build image: `public.ecr.aws/sam/build-python3.12@sha256:6b977f28341c892f743070ef945b600f1b257b668003720dc3bc9b1839fcd666` (matching the `latest-x86_64` tag verified against SAM CLI `1.164.0` on 2026-09-17). Updating this digest requires a reviewed specification/maintenance change, not an opportunistic edit.

### Security checks and CI

```text
pwsh ./scripts/proofpath.ps1 security
```

`security` runs the checksum-verified native Gitleaks history scan, `pip-audit` against both `services/api/requirements.txt` and the complete frozen `uv` development environment, `npm --prefix web audit`, and disposable ignore-rule sentinel checks against `.gitignore`; it fails on any unreviewed finding. `.github/workflows/checks.yml` runs the same command surface (`openapi-check`, `format-check`/`lint`/`typecheck`, `test`, `build`, `security`, `web-smoke`) as required named CI jobs on `ubuntu-24.04`, using pinned action commit SHAs and no AWS or LocalStack credentials.

Any vulnerability or secret-scanner suppression must be recorded in [`security/suppressions.toml`](security/suppressions.toml) with an advisory/rule ID, narrow scope, reason, owner, approval reference, and explicit expiry date; the manifest starts empty, an expired entry fails `security` outright, and blanket or unaudited suppressions are forbidden.

### Gate A verification

```text
pwsh ./scripts/proofpath.ps1 verify-gate-a
pwsh ./scripts/proofpath.ps1 verify-clean-clone
```

`verify-gate-a` runs every non-mutating check in one pass — versions, `openapi-check`, `format-check`, `lint`, `typecheck`, `test`, `security`, `build`, and `web-smoke` — then asserts the working tree has no tracked changes. `verify-clean-clone` rejects an already-dirty checkout, then runs `setup` followed by `verify-gate-a`; it is the command a Windows or macOS clean-clone evidence run executes from a freshly cloned directory.

## Ownership boundary

P3 owns transaction truth and semantics, simulator behavior, provider-fact contracts, transaction-domain reconciliation rules, and commerce invariants. P4 owns callback ingestion, durable reconciliation/recovery machinery, recovery handlers, and the guidance/case/export backend. P1 owns recovery/export presentation.

Follow [AGENTS.md](AGENTS.md) and the approved work-package process before making changes.
