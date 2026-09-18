"""Deterministic in-memory adapters (WP-08).

Test-only. P4's WP-07 owns the real DynamoDB, Step Functions and Cedar
adapters; these exist so the whole P3 lane is buildable and provable without
waiting for them, and so the same contract tests can run against both.

``MemoryStore`` implements real conditional semantics -- must-not-exist and
version-must-be, all-or-none -- because the safety argument for "one approval,
one attempt" is entirely about those conditions. A fake that just wrote
everything would make the tests meaningless.

It also carries a ``before_transact`` hook. That is what lets a test interleave
two callers deterministically at the exact moment that matters: after both have
read, before either has committed. Without it, concurrency tests are either
sleep-based and flaky, or they only ever test the sequential case.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from services.application.ports import (
    Action,
    Condition,
    ConditionFailed,
    ExecutionState,
    ExecutionStatus,
    Key,
    PublishRejected,
    StartedExecution,
    Write,
    reject_duplicate_keys,
)
from services.application.ports.speech import (
    SpeechSynthesisError,
    SpeechSynthesisResult,
    TranscribeSessionUrl,
)
from services.domain.catalog import Observation
from services.domain.errors import DomainError
from services.domain.jobs import OutboxEvent
from services.domain.money import Charge


class FixedClock:
    """Time moves only when a test says so."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)

    def set(self, moment: datetime) -> None:
        self._now = moment


class SequentialIds:
    """Predictable identifiers, so an assertion can name one."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def new_id(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}-{self._counts[prefix]:08d}"


class MemoryStore:
    """An in-memory state store with genuine conditional-write semantics."""

    def __init__(self) -> None:
        self._items: dict[Key, object] = {}
        #: Called once, just before a transaction is evaluated. A test uses this
        #: to run a competing caller at the one instant that can expose a race.
        self.before_transact: Callable[[list[Write]], None] | None = None
        self.transactions: list[list[Write]] = []
        self.commits = 0
        self.rejections = 0

    # -- reads -------------------------------------------------------------

    def get(self, key: Key) -> object | None:
        return self._items.get(key)

    def keys_matching(self, prefix: str) -> list[Key]:
        return sorted(k for k in self._items if k[0].startswith(prefix))

    def count_matching(self, prefix: str) -> int:
        return len(self.keys_matching(prefix))

    # -- writes ------------------------------------------------------------

    def transact(self, writes: list[Write]) -> None | ConditionFailed:
        hook, self.before_transact = self.before_transact, None
        if hook is not None:
            hook(writes)

        self.transactions.append(writes)
        reject_duplicate_keys(writes)

        for write in writes:
            existing = self._items.get(write.key)
            if write.condition is Condition.MUST_NOT_EXIST and existing is not None:
                self.rejections += 1
                return ConditionFailed(key=write.key, reason=write.reason)
            if write.condition is Condition.VERSION_MUST_BE:
                if existing is None:
                    self.rejections += 1
                    return ConditionFailed(key=write.key, reason=write.reason)
                if getattr(existing, "version", None) != write.expected_version:
                    self.rejections += 1
                    return ConditionFailed(key=write.key, reason=write.reason)

        # Every condition held: apply all of them, or we would not be here.
        for write in writes:
            if write.item is None:
                self._items.pop(write.key, None)
            else:
                self._items[write.key] = write.item
        self.commits += 1
        return None

    # -- test helpers ------------------------------------------------------

    def seed(self, key: Key, item: object) -> None:
        self._items[key] = item

    def snapshot(self) -> dict[Key, object]:
        return copy.copy(self._items)


class RecordingEventBus:
    """An event bus that keeps what it was given and refuses what it is told to.

    ``refuse`` is the important half. EventBridge reports a rejected entry
    inside a successful response, so the failure a publisher most needs to
    survive is one that never raises -- and a fake that only ever accepted
    could not express it at all.
    """

    def __init__(self, *, refuse: dict[str, str] | None = None) -> None:
        self.published: list[OutboxEvent] = []
        self.batches: list[list[OutboxEvent]] = []
        #: event id -> the error code the bus should report for it.
        self.refuse = dict(refuse or {})

    def publish(self, events: Sequence[OutboxEvent]) -> list[PublishRejected]:
        self.batches.append(list(events))
        rejected: list[PublishRejected] = []
        for event in events:
            error_code = self.refuse.get(event.event_id)
            if error_code is None:
                self.published.append(event)
            else:
                rejected.append(PublishRejected(event_id=event.event_id, error_code=error_code))
        return rejected


class RecordingWorkflowEngine:
    """A workflow engine that enforces the one rule the real one enforces.

    Names are unique, and starting a name it already has resolves to that run
    rather than creating a second. A fake that started whatever it was asked to
    would make every duplicate-delivery test pass for the wrong reason -- the
    suppression is the name, so the fake has to keep names.
    """

    def __init__(self) -> None:
        self.started: list[str] = []
        self._executions: dict[str, ExecutionStatus] = {}
        self._payloads: dict[str, str] = {}

    def start(self, *, run_id: str, payload: str) -> StartedExecution:
        self.started.append(run_id)
        existing = self._executions.get(run_id)
        if existing is not None:
            return StartedExecution(
                run_id=run_id, execution_ref=self.execution_ref(run_id), started_new_run=False
            )
        self._executions[run_id] = ExecutionStatus(run_id=run_id, state=ExecutionState.RUNNING)
        self._payloads[run_id] = payload
        return StartedExecution(
            run_id=run_id, execution_ref=self.execution_ref(run_id), started_new_run=True
        )

    def status(self, *, execution_ref: str) -> ExecutionStatus | None:
        return self._executions.get(self.run_id_of(execution_ref))

    # -- test helpers ------------------------------------------------------

    def execution_ref(self, run_id: str) -> str:
        return f"arn:fake:execution:{run_id}"

    def run_id_of(self, execution_ref: str) -> str:
        return execution_ref.rsplit(":", 1)[-1]

    def payload_of(self, run_id: str) -> str:
        return self._payloads[run_id]

    def finish(
        self,
        run_id: str,
        state: ExecutionState,
        *,
        result_ref: str | None = None,
        error_code: str | None = None,
    ) -> None:
        """Move a run to a terminal state, the way the engine eventually would."""
        self._executions[run_id] = ExecutionStatus(
            run_id=run_id, state=state, result_ref=result_ref, error_code=error_code
        )

    def forget(self, run_id: str) -> None:
        """Make the engine deny all knowledge, which is not the same as failing."""
        self._executions.pop(run_id, None)

    def runs(self) -> int:
        return len(self._executions)


class AllowAllPolicy:
    def allows(self, owner_id: str, action: Action, purchase_id: str) -> bool:
        return True


class DenyPolicy:
    """Denies one action, so a test can prove the check is actually consulted."""

    def __init__(self, denied: Action) -> None:
        self._denied = denied

    def allows(self, owner_id: str, action: Action, purchase_id: str) -> bool:
        return action is not self._denied


class ScriptedMerchant:
    """A merchant port that answers from a script, including failures.

    WP-08 never waits for a real connector to be green: P2's WP-04 is verified
    separately, and this stands in for it behind the same port.
    """

    def __init__(
        self,
        *,
        observations: dict[str, Observation | DomainError] | None = None,
        fees: tuple[Charge, ...] | DomainError = (),
    ) -> None:
        self._observations = observations or {}
        self._fees = fees
        self.refresh_calls: list[str] = []
        self.fee_calls: int = 0

    def refresh(self, location: str, sku: str, deadline_seconds: int) -> Observation | DomainError:
        self.refresh_calls.append(sku)
        return self._observations[sku]

    def assess_fees(
        self, location: str, merchant_id: str, line_hash: str, deadline_seconds: int
    ) -> tuple[Charge, ...] | DomainError:
        self.fee_calls += 1
        return self._fees


class FixedTranscribeUrlSigner:
    """Never calls AWS. Returns a URL a test can assert on, unchanged per call."""

    def __init__(
        self, url: str = "wss://transcribestreaming.ap-south-1.amazonaws.com:8443/x"
    ) -> None:
        self._url = url
        self.calls: list[tuple[str, int]] = []

    def presign(
        self, *, language_code: str, media_sample_rate_hz: int, expires_in_seconds: int
    ) -> TranscribeSessionUrl:
        self.calls.append((language_code, media_sample_rate_hz))
        return TranscribeSessionUrl(url=self._url, expires_in_seconds=expires_in_seconds)


class ScriptedSpeechSynthesizer:
    """Answers from a script, including a failure, without ever calling Polly."""

    def __init__(self, result: SpeechSynthesisResult | SpeechSynthesisError | None = None) -> None:
        self._result = result or SpeechSynthesisResult(
            audio_bytes=b"fake-mp3-bytes", content_type="audio/mpeg"
        )
        self.synthesize_calls: list[str] = []

    def synthesize(self, *, text: str) -> SpeechSynthesisResult | SpeechSynthesisError:
        self.synthesize_calls.append(text)
        return self._result


class MemoryAudioSink:
    """An in-memory audio sink so a test can assert what was actually stored."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[bytes, str]] = {}
        self.save_calls = 0

    def save(self, turn_id: str, content: bytes, content_type: str) -> str:
        self.save_calls += 1
        key = f"{turn_id}/{self.save_calls}"
        self._items[key] = (content, content_type)
        return key

    def playback_url(self, audio_key: str, expires_in_seconds: int) -> str:
        return f"https://audio.test/{audio_key}?expires={expires_in_seconds}"


__all__ = [
    "AllowAllPolicy",
    "DenyPolicy",
    "FixedClock",
    "FixedTranscribeUrlSigner",
    "MemoryAudioSink",
    "MemoryStore",
    "RecordingEventBus",
    "RecordingWorkflowEngine",
    "ScriptedMerchant",
    "ScriptedSpeechSynthesizer",
    "SequentialIds",
]
