"""The callback contract (WP-09 acceptance criteria 10, 11, 12, 13).

These are the fixtures P4's WP-10 handler must satisfy. Anything that passes here
and fails there means the two halves disagree, which is precisely what defining
the contract on this side is meant to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from services.application.callbacks import (
    MAX_SKEW_SECONDS,
    CallbackBody,
    CallbackHeaders,
    Disposition,
    FactKind,
    Rejection,
    Verified,
    _timestamp_text,
    disposition_of,
    sign,
    signing_input,
    verify,
)
from services.domain.money import Currency, Money
from services.domain.purchase import ProviderLookup

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
SECRET = b"a-rotated-secret-from-secrets-manager"
RAW_BODY = (
    b'{"event_id":"evt-0001","provider":"sim","kind":"payment","key":"'
    + b"a" * 64
    + b'","reference":"payref-1","status":"succeeded","amount_paise":59000,'
    b'"currency":"INR","seller_id":"demo-seller-01",'
    b'"observed_at":"2026-09-15T12:00:00.000Z"}'
)


def a_lookup(**over: Any) -> ProviderLookup:
    base: dict[str, Any] = dict(
        provider="sim",
        payment_key="a" * 64,
        purchase_id="purchase-0001",
        attempt_id="attempt-0001",
        expected_seller_id="demo-seller-01",
        expected_amount=Money.paise(59_000),
        expected_currency=Currency.INR,
    )
    base.update(over)
    return ProviderLookup(**base)


def a_body(**over: Any) -> CallbackBody:
    base: dict[str, Any] = dict(
        event_id="evt-0001",
        provider="sim",
        kind=FactKind.PAYMENT,
        key="a" * 64,
        reference="payref-1",
        status="succeeded",
        amount_paise=59_000,
        currency=Currency.INR,
        seller_id="demo-seller-01",
        observed_at=NOW,
    )
    base.update(over)
    return CallbackBody(**base)


def headers_for(raw_body: bytes = RAW_BODY, *, at: datetime = NOW, **over: Any) -> CallbackHeaders:
    stamp = _timestamp_text(at)
    base: dict[str, Any] = dict(
        provider="sim",
        event_id="evt-0001",
        delivery_timestamp=at,
        signature=sign(
            secret=SECRET, delivery_timestamp=stamp, event_id="evt-0001", raw_body=raw_body
        ),
    )
    base.update(over)
    return CallbackHeaders(**base)


# -- the signing input -----------------------------------------------------


def test_the_signing_input_is_timestamp_newline_event_newline_body() -> None:
    payload = signing_input(
        delivery_timestamp="2026-09-15T12:00:00.000Z", event_id="evt-0001", raw_body=b'{"a":1}'
    )
    assert payload == b'2026-09-15T12:00:00.000Z\nevt-0001\n{"a":1}'


def test_the_signature_covers_raw_bytes_not_a_reserialised_object() -> None:
    """A JSON round-trip reorders keys; an honest delivery would fail."""
    with pytest.raises(TypeError):
        # Deliberately the wrong type: a str body must be refused, because
        # signing a re-serialised object is how an honest delivery breaks.
        signing_input(delivery_timestamp="t", event_id="e", raw_body='{"a":1}')  # type: ignore[arg-type]


def test_semantically_equal_json_with_different_bytes_signs_differently() -> None:
    spaced = sign(secret=SECRET, delivery_timestamp="t", event_id="e", raw_body=b'{"a": 1}')
    compact = sign(secret=SECRET, delivery_timestamp="t", event_id="e", raw_body=b'{"a":1}')
    assert spaced != compact


# -- verification order ----------------------------------------------------


def test_a_valid_delivery_verifies() -> None:
    result = verify(secret=SECRET, headers=headers_for(), raw_body=RAW_BODY, now=NOW)
    assert isinstance(result, Verified)
    assert result.event_id == "evt-0001"


def test_an_unknown_provider_is_refused_first() -> None:
    result = verify(
        secret=SECRET, headers=headers_for(provider="stripe"), raw_body=RAW_BODY, now=NOW
    )
    assert result is Rejection.UNKNOWN_PROVIDER


@pytest.mark.parametrize("offset", [-301, 301, -600, 600])
def test_a_timestamp_outside_five_minutes_is_refused(offset: int) -> None:
    at = NOW + timedelta(seconds=offset)
    result = verify(secret=SECRET, headers=headers_for(at=at), raw_body=RAW_BODY, now=NOW)
    assert result is Rejection.SKEW_TOO_LARGE


@pytest.mark.parametrize("offset", [-299, 0, 299])
def test_a_timestamp_inside_five_minutes_is_accepted(offset: int) -> None:
    at = NOW + timedelta(seconds=offset)
    result = verify(secret=SECRET, headers=headers_for(at=at), raw_body=RAW_BODY, now=NOW)
    assert isinstance(result, Verified)


def test_a_future_timestamp_is_as_suspicious_as_a_stale_one() -> None:
    assert MAX_SKEW_SECONDS == 300
    ahead = verify(
        secret=SECRET,
        headers=headers_for(at=NOW + timedelta(seconds=400)),
        raw_body=RAW_BODY,
        now=NOW,
    )
    behind = verify(
        secret=SECRET,
        headers=headers_for(at=NOW - timedelta(seconds=400)),
        raw_body=RAW_BODY,
        now=NOW,
    )
    assert ahead is behind is Rejection.SKEW_TOO_LARGE


def test_a_tampered_body_fails_the_signature() -> None:
    result = verify(
        secret=SECRET, headers=headers_for(), raw_body=RAW_BODY.replace(b"59000", b"00001"), now=NOW
    )
    assert result is Rejection.BAD_SIGNATURE


def test_a_tampered_event_id_fails_the_signature() -> None:
    result = verify(
        secret=SECRET, headers=headers_for(event_id="evt-9999"), raw_body=RAW_BODY, now=NOW
    )
    assert result is Rejection.BAD_SIGNATURE


def test_the_wrong_secret_fails() -> None:
    result = verify(secret=b"not-the-secret", headers=headers_for(), raw_body=RAW_BODY, now=NOW)
    assert result is Rejection.BAD_SIGNATURE


def test_the_signature_comparison_is_constant_time() -> None:
    """A timing side channel here leaks the secret one byte at a time."""
    import inspect

    from services.application import callbacks

    assert "compare_digest" in inspect.getsource(callbacks.verify)


def test_a_redelivery_signs_differently_because_the_timestamp_is_refreshed() -> None:
    """Same event, same body, new delivery -- so a replayed signature is useless."""
    first = headers_for(at=NOW)
    second = headers_for(at=NOW + timedelta(seconds=30))
    assert first.signature != second.signature
    assert isinstance(
        verify(secret=SECRET, headers=second, raw_body=RAW_BODY, now=NOW + timedelta(seconds=30)),
        Verified,
    )


# -- disposition -----------------------------------------------------------


def _verified(raw_body: bytes = RAW_BODY) -> Verified:
    result = verify(secret=SECRET, headers=headers_for(raw_body), raw_body=raw_body, now=NOW)
    assert isinstance(result, Verified), f"the fixture should verify: {result}"
    return result


def test_the_same_event_with_the_same_bytes_is_a_duplicate() -> None:
    verified = _verified()
    result = disposition_of(
        verified=verified, existing_body_hash=verified.body_hash, lookup=a_lookup(), body=a_body()
    )
    assert result is Disposition.DUPLICATE


def test_the_same_event_id_with_different_bytes_conflicts() -> None:
    """Someone is replaying an id with a changed body. Never applied."""
    verified = _verified()
    result = disposition_of(
        verified=verified, existing_body_hash="f" * 64, lookup=a_lookup(), body=a_body()
    )
    assert result is Disposition.CONFLICTED


def test_an_unmatchable_key_is_quarantined() -> None:
    result = disposition_of(
        verified=_verified(), existing_body_hash=None, lookup=None, body=a_body()
    )
    assert result is Disposition.QUARANTINED


def test_a_different_amount_is_quarantined_not_believed() -> None:
    result = disposition_of(
        verified=_verified(),
        existing_body_hash=None,
        lookup=a_lookup(),
        body=a_body(amount_paise=1),
    )
    assert result is Disposition.QUARANTINED


def test_a_different_seller_is_quarantined() -> None:
    result = disposition_of(
        verified=_verified(),
        existing_body_hash=None,
        lookup=a_lookup(),
        body=a_body(seller_id="someone-else"),
    )
    assert result is Disposition.QUARANTINED


def test_a_matching_payment_fact_is_applied() -> None:
    result = disposition_of(
        verified=_verified(), existing_body_hash=None, lookup=a_lookup(), body=a_body()
    )
    assert result is Disposition.APPLIED


def test_an_order_fact_does_not_have_to_match_a_payment_amount() -> None:
    """Order and refund facts are matched by key, not by re-checking the price."""
    result = disposition_of(
        verified=_verified(),
        existing_body_hash=None,
        lookup=a_lookup(),
        body=a_body(kind=FactKind.ORDER, amount_paise=0),
    )
    assert result is Disposition.APPLIED


def test_every_disposition_is_covered_by_a_test() -> None:
    assert set(Disposition) == {
        Disposition.APPLIED,
        Disposition.DUPLICATE,
        Disposition.CONFLICTED,
        Disposition.QUARANTINED,
    }
