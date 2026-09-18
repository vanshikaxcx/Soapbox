"""Canonical JSON and hashing (WP-02 acceptance criteria 2, 8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from services.domain.canonical import (
    ALL_TAGS,
    TAG_DIFF,
    TAG_QUOTE,
    CanonicalEncodingError,
    body_hash,
    canonical_json,
    digest,
)
from services.domain.money import Charge, ChargeKind, Money

# -- floats never reach a signing input ------------------------------------


@pytest.mark.parametrize("bad", [1.0, 0.1, float("inf"), Decimal("1.00")])
def test_a_float_or_decimal_in_a_payload_raises(bad: object) -> None:
    with pytest.raises(CanonicalEncodingError):
        canonical_json({"amount": bad})


def test_a_nested_float_is_caught_too() -> None:
    with pytest.raises(CanonicalEncodingError):
        canonical_json({"lines": [{"price": 1.0}]})


def test_an_unsupported_type_raises_rather_than_being_stringified() -> None:
    with pytest.raises(CanonicalEncodingError):
        canonical_json({"quantity": {1, 2, 3}})


# -- nulls are explicit, never omitted -------------------------------------


def test_an_explicit_null_does_not_collide_with_an_absent_key() -> None:
    """The collision this rule exists to prevent.

    "we don't know the delivery fee" and "there is no delivery fee" must not be
    indistinguishable inside a signature.
    """
    unknown_fee = canonical_json({"delivery_charge": None})
    no_fee_key = canonical_json({})
    assert unknown_fee != no_fee_key
    assert unknown_fee == b'{"delivery_charge":null}'


def test_a_model_keeps_every_declared_field_including_nones() -> None:
    encoded = canonical_json(Charge.unknown_charge(ChargeKind.DELIVERY))
    assert b'"amount":null' in encoded
    assert b'"confidence":"unknown"' in encoded


# -- determinism -----------------------------------------------------------


def test_keys_are_sorted_by_code_point_regardless_of_insertion_order() -> None:
    forward = canonical_json({"a": 1, "b": 2, "z": 3})
    backward = canonical_json({"z": 3, "b": 2, "a": 1})
    assert forward == backward == b'{"a":1,"b":2,"z":3}'


def test_arrays_keep_their_order() -> None:
    assert canonical_json([1, 2, 3]) != canonical_json([3, 2, 1])


def test_strings_are_nfc_normalised() -> None:
    # Written as escapes on purpose: as literal characters, an editor or a
    # formatter that normalises this file would collapse them and quietly
    # empty the test out.
    composed = "é"  # e-acute, one code point
    decomposed = "é"  # e + combining acute, two code points
    assert composed != decomposed
    assert canonical_json({"name": composed}) == canonical_json({"name": decomposed})


def test_no_insignificant_whitespace() -> None:
    assert b" " not in canonical_json({"a": 1, "b": [2, 3]})


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=8),
        st.integers(min_value=-1000, max_value=1000),
        max_size=8,
    )
)
def test_encoding_is_stable_under_any_key_permutation(mapping: dict[str, int]) -> None:
    shuffled = dict(reversed(list(mapping.items())))
    assert canonical_json(mapping) == canonical_json(shuffled)


# -- timestamps ------------------------------------------------------------


def test_a_naive_datetime_cannot_be_canonicalised() -> None:
    with pytest.raises(CanonicalEncodingError):
        canonical_json({"at": datetime(2026, 9, 15, 12, 0, 0)})


def test_timestamps_are_utc_with_exactly_three_fractional_digits() -> None:
    encoded = canonical_json({"at": datetime(2026, 9, 15, 12, 0, 0, 123456, tzinfo=UTC)})
    assert encoded == b'{"at":"2026-09-15T12:00:00.123Z"}'


def test_the_same_instant_in_another_offset_hashes_identically() -> None:
    utc_moment = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    ist_moment = datetime(2026, 9, 15, 17, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert canonical_json({"at": utc_moment}) == canonical_json({"at": ist_moment})


def test_microsecond_truncation_in_storage_does_not_change_the_hash() -> None:
    precise = datetime(2026, 9, 15, 12, 0, 0, 123999, tzinfo=UTC)
    truncated = datetime(2026, 9, 15, 12, 0, 0, 123000, tzinfo=UTC)
    assert canonical_json({"at": precise}) == canonical_json({"at": truncated})


# -- domain separation -----------------------------------------------------


def test_the_same_payload_under_two_tags_gives_two_digests() -> None:
    payload = {"id": "abcdefgh"}
    assert digest(TAG_QUOTE, payload) != digest(TAG_DIFF, payload)


def test_an_unknown_tag_is_refused() -> None:
    with pytest.raises(CanonicalEncodingError):
        digest("proofpath.invented.v1", {"a": 1})


def test_every_tag_is_distinct() -> None:
    assert len(set(ALL_TAGS)) == len(ALL_TAGS)


def test_digest_is_lowercase_hex_sha256() -> None:
    value = digest(TAG_QUOTE, {"total": Money.paise(100)})
    assert len(value) == 64
    assert value == value.lower()
    int(value, 16)  # parses as hex


def test_digest_is_deterministic_across_calls() -> None:
    payload = {"b": 2, "a": [1, {"z": None}]}
    assert digest(TAG_QUOTE, payload) == digest(TAG_QUOTE, dict(payload))


# -- raw body hashing ------------------------------------------------------


def test_body_hash_is_over_raw_bytes_not_a_reserialised_object() -> None:
    spaced = b'{"a": 1,  "b": 2}'
    compact = b'{"a":1,"b":2}'
    # Semantically equal JSON, different bytes: a callback signature must notice.
    assert body_hash(spaced) != body_hash(compact)


def test_body_hash_requires_bytes() -> None:
    with pytest.raises(CanonicalEncodingError):
        body_hash('{"a":1}')  # type: ignore[arg-type]
