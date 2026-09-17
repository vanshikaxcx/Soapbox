"""Unit tests for extraction orchestration (WP-05, P2's slice).

Runs against the real `FakeExtractor` (fixture mode), the same "exercise the
real fake backend, not a mock of it" style `compare_test.py` uses for its
scripted `Merchant`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from services.agent.extract import run_extraction
from services.application.fakes import SequentialIds
from services.domain.intent import MAX_ITEMS, Flexibility
from services.extraction.fake import FIXTURE_IMAGE_MILK_AND_RICE
from services.merchants.models import Mode

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_transcript_resolves_to_real_items() -> None:
    outcome = run_extraction(
        mode=Mode.FIXTURE,
        now=NOW,
        id_factory=SequentialIds(),
        transcript="2 kg rice, 500 ml milk",
    )
    assert not outcome.unresolved
    assert [item.name for item in outcome.items] == ["rice", "milk"]
    assert outcome.items[0].item_id == "item-00000001"
    assert outcome.items[0].flexibility == Flexibility.EXACT_ONLY


def test_unparseable_fragment_is_unresolved_not_dropped() -> None:
    outcome = run_extraction(
        mode=Mode.FIXTURE, now=NOW, id_factory=SequentialIds(), transcript="milk"
    )
    assert not outcome.items
    [entry] = outcome.unresolved
    assert entry.reason_code == "no_quantity_detected"
    assert entry.raw_fragment == "milk"


def test_more_than_max_items_reports_overflow_not_truncation() -> None:
    transcript = ", ".join(f"{n} kg item{n}" for n in range(1, MAX_ITEMS + 3))
    outcome = run_extraction(
        mode=Mode.FIXTURE, now=NOW, id_factory=SequentialIds(), transcript=transcript
    )
    assert len(outcome.items) == MAX_ITEMS
    overflow = [u for u in outcome.unresolved if u.reason_code == "item_limit_exceeded"]
    assert len(overflow) == 2


def test_image_extraction_resolves_from_the_fixture() -> None:
    outcome = run_extraction(
        mode=Mode.FIXTURE,
        now=NOW,
        id_factory=SequentialIds(),
        image_bytes=FIXTURE_IMAGE_MILK_AND_RICE,
        image_mime_type="image/jpeg",
    )
    assert not outcome.unresolved
    assert {item.name for item in outcome.items} == {"milk", "basmati rice"}


def test_unknown_image_degrades_to_unresolved_never_raises() -> None:
    outcome = run_extraction(
        mode=Mode.FIXTURE,
        now=NOW,
        id_factory=SequentialIds(),
        image_bytes=b"an-unknown-photo",
        image_mime_type="image/jpeg",
    )
    assert not outcome.items
    [entry] = outcome.unresolved
    assert entry.reason_code == "extraction_unavailable"


def test_live_mode_with_no_bedrock_model_configured_degrades_gracefully() -> None:
    # BEDROCK_MODEL_ID is unset in every environment until WP-01 runs -- this
    # must be an honest unresolved entry, never an unhandled exception.
    outcome = run_extraction(
        mode=Mode.LIVE, now=NOW, id_factory=SequentialIds(), transcript="2 kg rice"
    )
    assert not outcome.items
    [entry] = outcome.unresolved
    assert entry.reason_code == "extraction_unavailable"
    assert "BEDROCK_MODEL_ID" in (entry.reason_detail or "")
