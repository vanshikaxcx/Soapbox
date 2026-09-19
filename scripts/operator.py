"""Operator actions against a running ProofPath: retry a job, replay an event.

Run deliberately, never from a test:

    python scripts/operator.py retry  --operator me --job job-00000001
    python scripts/operator.py replay --operator me --event event-00000001
    python scripts/operator.py history

This file is a shim and is meant to stay one. Every decision -- whether the
retry is allowed, what the audit record says, where it is written -- lives in
``services/application/operations.py``, which is tested. Logic that ends up here
is logic outside the gates: ``scripts/`` is not in ``testpaths`` and not in
mypy's ``files``, so anything written here is unchecked by construction.

Two things are deliberate and worth not "fixing":

``--operator`` is required and never defaulted. An audit trail whose actor is
"whoever had the credentials" answers nothing, and the one moment there is to
capture a name is the moment a human types the command.

The backends come from the composition root, so this script talks to whatever
the environment says -- ``PROOFPATH_STORE_BACKEND=memory`` for a dry run against
nothing, ``aws`` for the real thing. It has no opinion of its own about which,
which is what stops a rehearsal quietly becoming a production action. Note that
a ``memory`` run starts empty every time, so ``history`` will always print
nothing there: the store lives and dies with the process.

``--operator`` must match the identifier rule the rest of the codebase uses,
``^[A-Za-z0-9_-]{8,64}$``. That is deliberately the *existing* rule rather than
a new one invented for humans -- but it does mean an email address or an IAM ARN
will not do, and mapping a real principal onto one is WP-01's to decide.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import uuid
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pydantic import ValidationError  # noqa: E402

from services.adapters.composition import (  # noqa: E402
    build_event_bus,
    build_state_store,
    build_workflow_engine,
)
from services.application.controller import JobController  # noqa: E402
from services.application.operations import AuditRecord, OperatorConsole  # noqa: E402


class SystemClock:
    """Real time. The application layer only ever sees the ``Clock`` port."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIds:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:16]}"


def build_console() -> OperatorConsole:
    store = build_state_store()
    return OperatorConsole(
        store=store,
        controller=JobController(store=store, engine=build_workflow_engine()),
        bus=build_event_bus(),
        clock=SystemClock(),
        ids=UuidIds(),
    )


def render(record: AuditRecord) -> str:
    return (
        f"{record.recorded_at.isoformat()}  {record.action.value:<13}"
        f"  {record.subject:<24}  {record.outcome.value:<20}"
        f"  by {record.operator_id}" + (f"  ({record.detail})" if record.detail else "")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, prog="operator")
    commands = parser.add_subparsers(dest="command", required=True)

    retry = commands.add_parser("retry", help="authorised retry of a failed job")
    retry.add_argument("--operator", required=True, help="who is asking; recorded")
    retry.add_argument("--job", required=True)

    replay = commands.add_parser("replay", help="put a committed event back on the bus")
    replay.add_argument("--operator", required=True, help="who is asking; recorded")
    replay.add_argument("--event", required=True)

    commands.add_parser("history", help="every operator action recorded")

    args = parser.parse_args(argv)
    console = build_console()

    if args.command == "history":
        for record in console.history():
            print(render(record))
        return 0

    try:
        if args.command == "retry":
            record = console.retry_job(operator_id=args.operator, job_id=args.job)
        else:
            record = console.replay_event(operator_id=args.operator, event_id=args.event)
    except ValidationError as malformed:
        # A traceback is not an operator interface. This is the one thing the
        # shim is allowed to know: which field the human got wrong.
        fields = ", ".join(str(error["loc"][0]) for error in malformed.errors())
        print(f"refused before acting: {fields} is not in the form this system uses")
        print("identifiers match ^[A-Za-z0-9_-]{8,64}$ -- try 'firstname-lastname'")
        return 2

    print(render(record))
    # The outcome is printed, not signalled: a refusal by the cap is the system
    # working, and an exit code that called it a failure would put it in the
    # same bucket as a crash for whatever ran this.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
