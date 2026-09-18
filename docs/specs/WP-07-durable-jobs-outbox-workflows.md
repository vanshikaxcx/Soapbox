# WP-07 — Durable jobs, outbox, workflows, and projections

**Owner:** P4. **Implementation help:** P3 (agreed with P4; P3 owns the port this
fills in). **Reviewers:** P3 for restart semantics; P2 for search-task shape.
**Depends on:** WP-01 (deployed stack), WP-08 (**the `StateStore` port**),
WP-09 (`operator.py`, the one production caller of the prefix methods), WP-02
(merged — the job and outbox envelopes in `services/domain/jobs.py`).

**Correction from implementation review.** An earlier draft said "WP-02 (merged
— the port and envelopes)". That was wrong and would have sent the work to the
wrong branch: `services/application/ports/core.py` is introduced by **WP-08**
and `operator.py` by **WP-09**, and neither is merged. Verified by
`git ls-tree`: `main` and the WP-02 branch carry only `ports/id_generator.py`.
Only the envelopes (`Job`, `OutboxEvent`, `generation`, `job_id-rN`) are WP-02's
and merged. This package therefore **stacks on WP-09**, not on `main`, and its
test baseline is 951, not 570.

**Goal:** every async command is durably committed, restartable under defined
rules, observable, and safe under duplicate delivery.

---

## Outcome and user value

A shopper never sees a job that silently vanished, and never pays twice because
a queue delivered the same message again. The visible promise is narrow and
absolute: **a command that was committed will reach a terminal state, and a
command that was delivered twice will have happened once.**

Everything here is infrastructure, so its user value is entirely negative-space
— the failures that never surface. The evidence is therefore behavioural, not
architectural: duplicate delivery producing one effect, a failed run staying
failed, a DLQ replay that changes nothing it should not.

## In scope

- A DynamoDB `StateStore` adapter implementing WP-02's port, with single-table
  keys, conditional writes and all-or-none transactions.
- Outbox publication: Streams filter, publisher batch-failure handling,
  EventBridge routing, SQS/DLQ settings, partial-batch response.
- Controller start / existing-run resolution and Step Functions Standard
  execution naming.
- Task retry, `Catch`, timeout behaviour and final-status repair.
- The offer/guidance indexer, including version ordering and canonical
  fallback.
- Operator scripts: retry a job, replay a DLQ, each with an audit record.
- Correlated logs, alarms and dashboards sufficient for the demo trace.

## Out of scope

- **Any new business rule.** Job legality lives in `services/domain/jobs.py`
  (WP-02, merged). This package moves jobs; it does not decide what a job may
  do. A retry rule implemented here rather than there is a defect.
- **The provider simulator's own durability** — WP-09 owns its ledger.
- **Deciding the AWS account, region or service versions** — WP-01.
- OpenSearch cluster provisioning; this package consumes the index it is given
  and records the blocker if there is none.

## Split: what needs the cloud and what does not

Recorded because it determines what can be built before WP-01 lands, and
because the two halves have different definitions of done.

| part | needs a deployed stack |
|---|---|
| DynamoDB `StateStore` adapter | no — local DynamoDB or `moto` |
| adapter/`MemoryStore` conformance suite | no |
| offer/guidance indexer version ordering | no |
| table, Streams and queue declarations in `infra/template.yaml` | no (authoring), yes (proof) |
| publisher, controller, workflow/task wiring | **yes** |
| DLQ replay, stale-running repair, alarms, dashboards | **yes** |
| every acceptance criterion marked *deployed* below | **yes** |

The first three are built and merged first, against fakes, the way WP-02/08/09
were. Nothing in this package is allowed to make the pure half depend on the
cloud half — that is what kept 951 tests runnable with no AWS at all.

## The contract this package fills in

WP-02 merged the port; this package implements it. Reproduced here so the
adapter is written against the real signatures rather than a memory of them:

```python
Key = tuple[str, str]                       # partition, sort

class Condition(StrEnum):
    NONE = "none"
    MUST_NOT_EXIST = "must_not_exist"
    VERSION_MUST_BE = "version_must_be"

class Write(Record):
    key: Key
    item: object = None                     # None means delete
    condition: Condition = Condition.NONE
    expected_version: int | None = None
    reason: str                             # one phrase, surfaces in failures

class StateStore(Protocol):
    def get(self, key: Key) -> object | None: ...
    def transact(self, writes: list[Write]) -> None | ConditionFailed: ...
```

**The Protocol is narrower than what production code actually calls.** It
declares only `get` and `transact`. But `services/application/operator.py:128`
calls `keys_matching("PURCHASE#")`, and it compiles only because of a
`# type: ignore[attr-defined]` on that line -- the type checker was silenced
rather than the port corrected. `MemoryStore` happens to provide
`keys_matching` and `count_matching`, so nothing has ever failed.

This matters here and not before, because the fake was the only implementation.
**A DynamoDB adapter that implements the Protocol as written would satisfy
mypy and then crash at runtime the first time an operator reads effect counts.**

Resolved by putting both methods on the Protocol and deleting the ignore, so
the adapter's obligations are stated rather than discovered. That is a WP-02
change; it is small, it is a bug fix, and it belongs with whoever touches it
first. Recorded here as **D-1** so the adapter is not written against the
narrower surface by mistake.

Three properties of that contract are load-bearing and are not the adapter's to
reinterpret:

1. **`ConditionFailed` is a returned value, not an exception.** The whole
   application layer branches on it. An adapter that raises
   `ConditionalCheckFailedException` through to the caller breaks every use
   case at once, silently, because the callers have no `except` to catch it.
2. **`transact` is all-or-none.** Partial application is not a degraded
   outcome; it is corruption. The approval transaction is the worst case and
   the best illustration -- eight writes, each carrying its own reason, that
   must land together or not at all:

   | # | reason on the write |
   |---|---|
   | 1 | consent is one-shot |
   | 2 | the attempt is created once |
   | 3 | THE uniqueness guarantee: no duplicate payment key |
   | 4 | wins or loses the cancel race, atomically |
   | 5 | durable commit before any provider call |
   | 6 | checkout is dispatched only from committed state |
   | 7 | the consent record a case can cite |
   | 8 | replay returns, never re-executes |

   Any adapter that can apply seven of these and not the eighth has taken money
   without recording consent, or recorded consent without a payment key.
3. **`item=None` means delete.** Confirmed against the reference
   implementation (`fakes.py`: `if write.item is None: self._items.pop(...)`).
   The claim-releasing writes depend on it, and a delete participates in the
   same all-or-none guarantee as a put.

## Data model: the single table

Partition key is the aggregate; sort key is the row within it. The prefixes
already in use by merged code, which the table must serve unchanged:

| partition | sort | written by |
|---|---|---|
| `PURCHASE#<id>` | `PURCHASE` | WP-08 |
| `PURCHASE#<id>` | `ATTEMPT#<id>` | WP-08 |
| `PURCHASE#<id>` | `APPROVAL#<id>` | WP-08 |
| `PURCHASE#<id>` | `PREPARATION#<n>` / `FACTS#<n>` | WP-08 |
| `PURCHASE#<id>` | `EVIDENCE#<id>` | WP-08 |
| `PURCHASE#<id>` | `BASKET#<id>` | WP-08 |
| `PROVIDER#<provider>#<payment_key>` | `LOOKUP` | WP-08 |
| `INBOX#<provider>#<event_id>` | `EVENT` | WP-09 |
| `IDEMPOTENCY#<hash>` | `RECORD` | WP-08 |
| `JOB#<job_id>` | `JOB` | WP-08 |
| `OUTBOX#<event_id>` | `EVENT` | WP-08 |

**Correction from spec review:** an earlier draft of this table claimed `JOB#`
and `OUTBOX#` as this package's rows. They are not. `job_key` and `outbox_key`
are defined in `services/application/purchase.py` (WP-08, merged) and the rows
are written inside the approval transaction. This package **moves and resolves**
them; it does not own or define them. Getting that backwards would have
justified re-declaring the envelope here, which is precisely the duplication
"Out of scope" forbids.

`keys_matching(prefix)` and `count_matching(prefix)` are prefix scans on the
partition key. In DynamoDB they are `Query` where the prefix is a whole
partition, and `Scan` otherwise — the operator effect counts are the only
callers of the latter, and they are operator-only and bounded, so a scan is
acceptable there and nowhere else.

**Open question O-1** — whether `PROVIDER#` uniqueness needs a GSI or is served
by the partition key alone. WP-02 acceptance criterion 17 fixes the shape and
the `(provider, payment_key)` uniqueness; the index choice is this package's.

## Generation semantics, and where they already live

`services/domain/jobs.py` (WP-02, merged) already defines:

- `Job` with `generation: int`, and `execution_name` rendering `job_id-rN`;
- `retry()`, which is the **only** thing that increments the generation;
- `start()`, `succeed()`, `fail()` as transitions returning `IllegalTransition`
  rather than raising;
- `resolve_delivery()` / `DuplicateDelivery`, which is duplicate start
  suppression expressed as a rule.

This package does not restate any of that. The controller calls it. A Step
Functions execution is named `job_id-rN`, so **a duplicate delivery produces a
name collision rather than a second run** — the suppression is the naming, not
a check the controller might forget.

The distinction the POA asks for between **retry API** and **operator replay**
follows from the same place: a retry increments the generation and is therefore
a new execution; a replay re-delivers an existing event and must resolve to the
existing execution. If a replay ever creates a new generation, that is the bug
this rule exists to prevent.

## Idempotency, concurrency, timeout, and retry

- **Duplicate delivery:** resolved by execution name. The controller starts
  `job_id-rN`; `ExecutionAlreadyExists` is a success, not an error.
- **Committed-then-crashed:** the outbox row is written in the same transaction
  as the state change, so the publisher's job is to catch up, never to decide.
- **Publisher partial failure:** SQS partial-batch response reports only the
  failed message ids; a whole-batch failure on one bad message is a defect.
- **Task timeout:** a task that times out leaves the job `running` with a stale
  heartbeat. Final-status repair reconciles it; until then the job is not
  reported as failed, because "we stopped watching" is not "it failed."
- **Bounded retries:** attempts are capped and the cap is recorded on the job,
  so an operator sees why it stopped rather than inferring it.

## Failure modes and user-visible errors

| failure | behaviour | what the shopper sees |
|---|---|---|
| condition failed on write | `ConditionFailed` returned, nothing written | the caller's own 409 wording |
| duplicate delivery | existing execution resolved | nothing — it already happened |
| EventBridge rejects one event | that event retried, batch unaffected | nothing |
| SQS batch partial failure | only failed ids retried | nothing |
| task timeout | job stays `running`, repair reconciles | "we're still confirming" — never a failure |
| DLQ exhausted | job `failed`, alarm raised | a job failure, **never** a payment outcome |
| index outage | canonical fallback serves the read | slower, not wrong |

The last two rows are the ones that matter. WP-02's `JOB_FAILED` copy exists
because a job failing says nothing about money, and this package is where that
distinction is most easily lost.

## Observability and cost limits

- Every log line carries `job_id`, `generation` and the correlation id.
- Alarms: DLQ depth above zero, stale `running` jobs beyond the timeout,
  publisher batch failure rate.
- One dashboard sufficient for the demo trace: commit → outbox → publisher →
  EventBridge → SQS → controller → execution → terminal state.
- Cost: the table is on-demand; queues and Step Functions Standard are
  per-execution. No standing compute is introduced by this package.

## Test plan

**Without the cloud (merged first):**

1. **Adapter/fake conformance suite** — the same tests run against
   `MemoryStore` and the DynamoDB adapter, asserting identical behaviour for:
   every `Condition`, `item=None` deletes, all-or-none `transact`, and
   `ConditionFailed` returned rather than raised. This is the single most
   valuable artifact in the package: it is what makes swapping the fake for the
   real store safe.
2. A failed condition anywhere in a transaction leaves **nothing** written.
3. `ConditionalCheckFailedException` is mapped, never propagated.
4. Indexer ignores an older version and serves canonical fallback on outage.
5. Existing WP-08/09 suites pass unchanged against the adapter — 951 tests that
   already encode the semantics, reused as a conformance corpus.

**Deployed (WP-01 required):**

6. Duplicate event delivery creates no second run and no second effect.
7. A failed execution stays failed until an authorised retry increments the
   generation.
8. Outbox replay, single EventBridge failure, partial SQS batch retry, DLQ
   replay, stale-running repair.
9. An index outage and an older projection cannot corrupt canonical results.
10. A job from a durable commit reaches a terminal result after handler retry.

## Acceptance criteria

1. The DynamoDB adapter satisfies `StateStore` and passes the conformance suite
   against the same tests as `MemoryStore`.
2. `ConditionFailed` is returned, never raised, for every conditional failure.
3. `transact` is all-or-none under every tested interleaving.
4. `item=None` deletes, and a delete participates in the same atomicity.
5. WP-08 and WP-09's existing suites pass unchanged against the adapter.
6. *(deployed)* Duplicate delivery produces exactly one run and one effect.
7. *(deployed)* A failed execution remains failed until an authorised retry
   increments the generation; a replay never increments it.
8. *(deployed)* Partial SQS batch failure retries only the failed ids.
9. *(deployed)* DLQ replay and stale-running repair are operator-invocable and
   leave an audit record.
10. *(deployed)* An older projection cannot overwrite a newer canonical result.
11. A job failure is never rendered as a payment outcome, at any layer.
12. No business rule is introduced here; `services/domain/jobs.py` remains the
    only place a job transition is decided — enforced by the existing
    import-boundary test.
13. Full suite green; formatter, linter and type checker clean under
    `--frozen`.

## Rollout, rollback, and fixture strategy

- The adapter is selected at the composition root by environment, never by
  branching inside application code. `MemoryStore` remains the test default, so
  a rollback is a configuration change, not a revert.
- The table is disposable; teardown drops it. No migration is required because
  nothing is deployed before this package.
- Changing a key prefix or the transaction shape is **breaking**: WP-08's spec
  records the approval transaction as a contract with this package, and it
  needs P3's and P4's agreement plus the two approvals the POA mandates for
  payment-state changes.

## Open questions and decisions

- **O-1 — `PROVIDER#` uniqueness: GSI or partition key alone? ANSWERED: no
  GSI.** Every access is a point read by payment key --
  `store.get(provider_lookup_key(payment_key))` in `checkout.py`, `cases.py`
  and `reconcile.py` -- plus one conditional write in `purchase.py`. Nothing
  queries lookups by any other attribute. The key is
  `("PROVIDER#<provider>#<payment_key>", "LOOKUP")`, so uniqueness is the
  partition key plus `MUST_NOT_EXIST`, which is exactly WP-02 AC-17. A GSI
  would be cost and consistency risk for a query nobody makes. Revisit only if
  a surface ever needs "all lookups for a purchase".
- **O-2 — table name and environment scoping.** WP-01 decides the account and
  region; this package needs the naming convention before `infra/template.yaml`
  is authored. Needs P4.
- **O-3 — `count_matching` on a scan. ANSWERED: acceptable, and narrower than
  feared.** The only production caller of either prefix method is
  `operator.py:128` (`keys_matching("PURCHASE#")`, operator-only, bounded).
  Every other caller is a test. No shopper-facing path scans. The answer comes
  with D-1 above: the methods must go on the Protocol, because production
  depends on them and the port does not say so.
- **O-4 — search-task shape.** P2 is the named reviewer for it; WP-06's
  `/tasks/compare` is the caller and should confirm the envelope before the
  controller is written. Needs P2.
