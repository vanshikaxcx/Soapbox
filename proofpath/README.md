# ProofPath

Voice-first grocery shopping assistant: live two-merchant comparison, deterministic
basket repair, exact simulated checkout approval, and evidence-based payment/order
recovery. See `docs/PROOFPATH-SPEC.md` for the full product/engineering spec and
`docs/specs/` for individual work-package specs.

**No real money moves and no retailer order is placed.** Checkout, payment, order,
callbacks, and refunds are all independently simulated and visibly labelled.

## Setup

Prerequisites: Node 20.x, Python 3.12, Docker, AWS SAM CLI, `uv` or `pip`.

```bash
# Python services
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -r services/agent/requirements.txt

# Web
cd web && npm ci && cd ..
```

## Common commands

| Command | What it does |
| --- | --- |
| `make lint` | Ruff (Python) + ESLint (web) |
| `make typecheck` | mypy strict (Python) + `tsc --noEmit` strict (web) |
| `make test` | pytest (unit/contract) + vitest (web smoke test) |
| `make openapi-check` | Validates `contracts/openapi.yaml` and checks generated TS client has no drift |
| `make dev-api` | Runs the health API locally via uvicorn |
| `make dev-web` | Runs the Vite dev server |

Deployment, live-merchant, and cloud-smoke commands land in WP-01/WP-07/WP-12 and are
documented here as those packages merge.

## Repository layout

```text
proofpath/
├── docs/                # specs, evidence, this repo's source of truth
├── contracts/openapi.yaml
├── web/                  # React/TS shell (P1)
├── services/
│   ├── api/               # Lambda HTTP entry points (P4)
│   ├── application/        # use cases, typed ports (use-case owner)
│   ├── domain/               # pure rules, no AWS/browser imports (P3)
│   ├── agent/                  # FastAPI + Strands + Playwright container (P2)
│   ├── merchants/                # registry + connectors (P2)
│   ├── adapters/                    # AWS + deterministic test adapters (P4)
│   ├── workers/                       # tasks, publisher, controller, indexer (P4)
│   └── simulator/                       # separate ledger, scenarios (P3)
├── workflows/            # ASL step functions definitions
├── policies/              # Cedar schema/policies
├── guidance/                # reviewed recovery guidance corpus
├── infra/                     # SAM/CloudFormation templates
├── local/                       # SAM local / LocalStack compose
├── scripts/                       # dev/test/deploy/seed/retry/verify/cleanup
└── tests/{unit,contracts,integration,e2e,live}/
```

Ownership table and PR/merge policy: see `docs/PROOFPATH-IMPLEMENTATION-POA.md` §2-3
(kept in the planning workspace, not duplicated here to avoid drift).

## Data modes

Every observation/basket/quote is tagged `mode: live|fixture`. Live and fixture data
are never combined, ranked, or displayed together. Fixture surfaces always show
"Demonstration data — fixture prices, not current retailer offers."
