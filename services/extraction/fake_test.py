"""Unit tests for the fake/dev extraction backend (WP-05, P2's slice)."""

from __future__ import annotations

from datetime import UTC, datetime

from services.extraction.fake import FIXTURE_IMAGE_MILK_AND_RICE, FakeExtractor

DEADLINE = datetime(2026, 1, 1, tzinfo=UTC)


def an_extractor() -> FakeExtractor:
    return FakeExtractor()


def test_parses_quantity_unit_and_name() -> None:
    result = an_extractor().extract_from_text("2 kg rice, 500 ml milk", DEADLINE)
    assert not result.unresolved
    assert [(c.name, c.quantity_value, c.unit) for c in result.candidates] == [
        ("rice", 2.0, "kg"),
        ("milk", 500.0, "ml"),
    ]


def test_treats_a_bare_count_of_pieces_as_explicit_not_guessed() -> None:
    result = an_extractor().extract_from_text("6 eggs", DEADLINE)
    assert not result.unresolved
    [candidate] = result.candidates
    assert candidate.name == "eggs"
    assert candidate.unit == "piece"
    assert candidate.quantity_value == 6.0


def test_unit_word_not_recognised_is_folded_into_the_name() -> None:
    # "amul" isn't a unit, so it's part of the item's name, not discarded --
    # a bare count of pieces is still an explicit, honest reading.
    result = an_extractor().extract_from_text("2 amul milk", DEADLINE)
    assert not result.unresolved
    [candidate] = result.candidates
    assert candidate.name == "amul milk"
    assert candidate.unit == "piece"


def test_item_with_no_quantity_is_unresolved_not_guessed() -> None:
    result = an_extractor().extract_from_text("milk", DEADLINE)
    assert not result.candidates
    [entry] = result.unresolved
    assert entry.reason_code == "no_quantity_detected"


def test_garbled_input_yields_no_items_detected() -> None:
    result = an_extractor().extract_from_text("   ,,, and  ", DEADLINE)
    assert not result.candidates
    [entry] = result.unresolved
    assert entry.reason_code == "no_items_detected"


def test_explicit_hard_attribute_is_carried_verbatim() -> None:
    result = an_extractor().extract_from_text("2 l organic milk", DEADLINE)
    [candidate] = result.candidates
    assert candidate.hard_attributes == {"type": "organic"}


def test_no_hard_attribute_when_none_was_stated() -> None:
    result = an_extractor().extract_from_text("2 l milk", DEADLINE)
    [candidate] = result.candidates
    assert candidate.hard_attributes == {}


def test_multiple_fragments_split_on_comma_and_and() -> None:
    result = an_extractor().extract_from_text("1 kg sugar and 2 l milk, 3 piece bread", DEADLINE)
    assert not result.unresolved
    names = {c.name for c in result.candidates}
    assert names == {"sugar", "milk", "bread"}


def test_known_fixture_image_resolves() -> None:
    result = an_extractor().extract_from_image(
        FIXTURE_IMAGE_MILK_AND_RICE, "image/jpeg", DEADLINE
    )
    assert not result.unresolved
    names = {c.name for c in result.candidates}
    assert names == {"milk", "basmati rice"}


def test_unknown_image_is_extraction_unavailable_not_a_guess() -> None:
    result = an_extractor().extract_from_image(b"some-unknown-photo-bytes", "image/jpeg", DEADLINE)
    assert not result.candidates
    [entry] = result.unresolved
    assert entry.reason_code == "extraction_unavailable"
