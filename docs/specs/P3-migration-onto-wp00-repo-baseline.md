# P3 migration onto `feat/wp-00-repo-baseline-p4`

WP-02, WP-08 and WP-09 were built on `feat/wp-00-repository-toolchain-baseline-p4`
(the first WP-00, nested layout under `proofpath/`). The team took the newer
`feat/wp-00-repo-baseline-p4` instead. This records what moved and what did not.

P2's `feat/wp-06-search-comparison-p2` is still on the old baseline as of this
writing, so it will need the same move; §5 is written to save them the
rediscovery.

## 1. State after the move

| gate | result |
|---|---|
| `pytest` | 940 collected, 939 passed, 1 skipped |
| `ruff check .` | clean |
| `mypy` — production code | **0 errors** |
| `mypy` — co-located test files | **0 errors** |
| WP-00 Gate A (`openapi-check`) | still passes, contract untouched |
| baseline's own `tests/` | 6 passed |

## 2. Layout

`proofpath/services/**` → `services/**`. No import statement changed: they were
already `services.domain.*`, so only the package root moved.

## 3. Files deliberately not carried over

- **`services/api/health.py`** — the baseline has its own, built on typed Pydantic
  envelopes. The old one was kept out; the baseline's wins.
- **`services/api/local_app.py`** — a FastAPI wrapper for the old `make dev-api`.
  It imports `get_health`, which the baseline's health module does not define,
  and the baseline runs locally through SAM (`infra/template.yaml`). Keeping it
  would have been the second local workflow engine the spec warns against.
  Nothing in WP-02/08/09 referenced it.
- The old baseline's `__init__.py` docstrings for `domain`, `application`, `api`
  and `adapters` — the baseline owns those files.

`services/api/envelope.py` **was** carried, because `http.py` depends on it and
the new baseline has no equivalent. Its `dict` annotations were tightened so the
tree stays mypy-clean. See §6 for the follow-up that would retire it.

## 4. The `ports` collision

The baseline ships `services/application/ports/` as a *package*
(`ports/__init__.py`, `ports/id_generator.py`); P3 had `ports.py` as a *module*.
Those cannot coexist.

Resolved by making P3's module `ports/core.py` and re-exporting from
`ports/__init__.py`, so every existing `from services.application.ports import
StateStore` keeps working unchanged.

`IdFactory` and `IdGenerator` both survive and are **not** duplicates:
`IdGenerator.new_id()` mints an opaque request id for the baseline transport;
`IdFactory.new_id(prefix)` mints a typed domain id whose prefix the caller
chooses. The names are close enough to be mistaken for one another, so the
package docstring says which is which.

## 5. The contract, and why it is a separate file

P3's endpoints are in **`contracts/openapi-p3-purchases.yaml`**, not merged into
`contracts/openapi.yaml`. Two reasons, both discovered by running WP-00's own
gate rather than by reading it:

1. `scripts/check-openapi-aws-subset.mjs` asserts **only `GET /health` may be
   declared**. That is true of the baseline and must relax when any WP adds a
   route. Relaxing it is P4's call — they have just recorded Gate A evidence
   against the current rule, and silently editing the gate would invalidate it.
2. The same gate forbids `nullable`, `allOf`, `oneOf`, `anyOf`, `discriminator`
   and `const`, because API Gateway and SAM reject them. **P3's original schemas
   used `nullable` and `allOf` throughout** — they would have parsed fine and
   then failed to deploy. The separate document is rewritten inside the subset,
   so it is mergeable verbatim once the path rule moves.

The rewrite changed one modelling decision: an amount that is not known is now
**absent** rather than null, since `nullable` is unavailable. Absent means "we
could not confirm this" and is never to be read as zero. `purchases_test.py`
enforces the subset rules directly so this cannot regress.

Two differences from the baseline document still need P4's decision:

- **Money.** P3 emits bare integer paise (`total_paise`); the baseline defines a
  `MoneyINR` object. Unifying is right, but it changes every payload P1 renders.
- **Error codes.** The baseline's `ErrorBody.code` is a free pattern, where P3's
  taxonomy has 26 named codes the UI branches on. A shared enum would help P1.

## 6. Open items

- ~~`mypy` on co-located test files~~ — **done.** All 325 are fixed, so the
  whole tree passes the baseline's `strict` mypy over `services` and `tests`,
  and `typecheck` is green. The fix was not a config exemption: the root cause
  was test harnesses reaching through `store.get`, which returns `object`, and
  use-case unions that were never narrowed. Harnesses now use the typed `read`
  helper and expose narrowing twins (`prepare_ok`, `accept_ok`, `approve_ok`,
  `run_ok`, `step_ok`) beside the un-narrowed originals the failure-path tests
  need. Deliberate monkeypatching in spies carries a targeted
  `# type: ignore[method-assign]` rather than being restructured away.
- **Retire `envelope.py`** once the baseline's typed envelopes can carry the
  full error taxonomy (their `code` is `Literal["internal_error"]` today).
- **P2's branch** needs this same move; §3–§5 are the parts that are not obvious.

## 7. One real bug found while migrating

`EffectLedger.set_scenario` took `object`. That looked permissive and was in
fact impossible to satisfy: protocol parameters are contravariant, so
`Simulator`, which accepts only its own `Scenario` enum, never conformed — and
a caller holding an `EffectLedger` could legally pass anything at all and fail
at runtime. It was invisible before because the old toolchain never type-checked
that call site.

Fixed by making the protocol generic in the scenario type
(`class EffectLedger[ScenarioT](Protocol)`), which states the real contract
without the application layer having to name the simulator's enum.
