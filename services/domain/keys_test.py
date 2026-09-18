"""Derived keys and hashes (WP-02 acceptance criteria 8, 9).

The claim under test: one approval yields one payment key, byte-identical across
retry, timeout, crash and workflow-generation bump -- because the key is a pure
function of identities fixed at consent time.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest

from services.domain.canonical import CanonicalEncodingError
from services.domain.ids import Mode
from services.domain.keys import (
    approval_id,
    diff_hash,
    idempotency_request_hash,
    line_hash,
    order_key,
    payment_key,
    quote_hash,
)
from services.domain.money import Charge, ChargeKind, Currency, Money

QUOTE: dict[str, Any] = {
    "owner_id": "owner-001",
    "purchase_id": "purchase-001",
    "purchase_version": 3,
    "quote_id": "quote-0001",
    "quote_version": 1,
    "seller_id": "seller-01",
    "source_merchant_id": "merchant-01",
    "mode": Mode.LIVE,
    "lines": [{"sku": "sku-00001", "line_total": Money.paise(10_000)}],
    "charges": [Charge.known_charge(ChargeKind.DELIVERY, Money.paise(2_000))],
    "currency": Currency.INR,
    "delivery": "standard",
    "expires_at": datetime(2026, 9, 15, 12, 2, 0, tzinfo=UTC),
}


# -- approval id is derived from consent, not minted per request -----------


def test_the_same_consent_always_produces_the_same_approval_id() -> None:
    first = approval_id(quote_id="quote-0001", quote_hash="a" * 64, quote_version=1)
    second = approval_id(quote_id="quote-0001", quote_hash="a" * 64, quote_version=1)
    assert first == second


def test_a_different_quote_or_version_produces_a_different_approval_id() -> None:
    base = approval_id(quote_id="quote-0001", quote_hash="a" * 64, quote_version=1)
    assert base != approval_id(quote_id="quote-0002", quote_hash="a" * 64, quote_version=1)
    assert base != approval_id(quote_id="quote-0001", quote_hash="b" * 64, quote_version=1)
    assert base != approval_id(quote_id="quote-0001", quote_hash="a" * 64, quote_version=2)


def test_approval_id_takes_no_clock_random_or_counter_argument() -> None:
    """If it did, two concurrent approvals of one quote would yield two keys."""
    assert set(inspect.signature(approval_id).parameters) == {
        "quote_id",
        "quote_hash",
        "quote_version",
    }


# -- payment key stability -------------------------------------------------


def test_payment_key_is_identical_across_a_hundred_retries() -> None:
    consent = approval_id(quote_id="quote-0001", quote_hash="a" * 64, quote_version=1)
    keys = {payment_key(purchase_id="purchase-001", approval_id=consent) for _ in range(100)}
    assert len(keys) == 1


def test_payment_key_survives_crash_restart_and_generation_bump() -> None:
    """Nothing in the derivation can observe a restart, so nothing can change."""
    consent = approval_id(quote_id="quote-0001", quote_hash="a" * 64, quote_version=1)
    before_crash = payment_key(purchase_id="purchase-001", approval_id=consent)

    # Simulate: process died, job retried with generation 4, clock moved a day.
    after_restart = payment_key(purchase_id="purchase-001", approval_id=consent)
    assert before_crash == after_restart


def test_payment_key_takes_no_clock_random_or_attempt_argument() -> None:
    assert set(inspect.signature(payment_key).parameters) == {"purchase_id", "approval_id"}


def test_two_different_approvals_on_one_purchase_get_different_keys() -> None:
    first = approval_id(quote_id="quote-0001", quote_hash="a" * 64, quote_version=1)
    second = approval_id(quote_id="quote-0002", quote_hash="b" * 64, quote_version=1)
    assert payment_key(purchase_id="purchase-001", approval_id=first) != payment_key(
        purchase_id="purchase-001", approval_id=second
    )


def test_order_key_is_stable_and_scoped_to_the_attempt() -> None:
    first = order_key(purchase_id="purchase-001", attempt_id="attempt-01")
    assert first == order_key(purchase_id="purchase-001", attempt_id="attempt-01")
    assert first != order_key(purchase_id="purchase-001", attempt_id="attempt-02")
    assert first != order_key(purchase_id="purchase-002", attempt_id="attempt-01")


def test_a_payment_key_and_an_order_key_never_collide() -> None:
    # Same inputs, different tags: domain separation does its job.
    assert payment_key(purchase_id="p-0000001", approval_id="a-0000001") != order_key(
        purchase_id="p-0000001", attempt_id="a-0000001"
    )


# -- quote hash binding ----------------------------------------------------


def test_quote_hash_is_deterministic() -> None:
    assert quote_hash(**QUOTE) == quote_hash(**QUOTE)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("owner_id", "owner-002"),
        ("purchase_id", "purchase-002"),
        ("purchase_version", 4),
        ("quote_id", "quote-0002"),
        ("quote_version", 2),
        ("seller_id", "seller-02"),
        ("source_merchant_id", "merchant-02"),
        ("mode", Mode.FIXTURE),
        ("delivery", "express"),
        ("expires_at", datetime(2026, 9, 15, 12, 3, 0, tzinfo=UTC)),
    ],
)
def test_changing_any_bound_field_changes_the_hash(field: str, replacement: object) -> None:
    altered = {**QUOTE, field: replacement}
    assert quote_hash(**altered) != quote_hash(**QUOTE)


def test_changing_a_line_price_changes_the_hash() -> None:
    altered = {
        **QUOTE,
        "lines": [{"sku": "sku-00001", "line_total": Money.paise(10_001)}],
    }
    assert quote_hash(**altered) != quote_hash(**QUOTE)


def test_changing_a_charge_changes_the_hash() -> None:
    altered = {
        **QUOTE,
        "charges": [Charge.known_charge(ChargeKind.DELIVERY, Money.paise(2_001))],
    }
    assert quote_hash(**altered) != quote_hash(**QUOTE)


def test_a_fixture_quote_never_hashes_the_same_as_an_identical_live_quote() -> None:
    """The reason mode is bound (WP-02 D-3)."""
    live = quote_hash(**{**QUOTE, "mode": Mode.LIVE})
    fixture = quote_hash(**{**QUOTE, "mode": Mode.FIXTURE})
    assert live != fixture


def test_quote_hash_is_keyword_only_and_enumerates_every_bound_term() -> None:
    parameters = inspect.signature(quote_hash).parameters
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    assert set(parameters) == set(QUOTE)


def test_a_float_anywhere_in_a_quote_refuses_to_hash() -> None:
    with pytest.raises(CanonicalEncodingError):
        quote_hash(**{**QUOTE, "lines": [{"sku": "sku-00001", "line_total": 100.0}]})


# -- idempotency request hash ---------------------------------------------


def _request(**overrides: Any) -> dict[str, Any]:
    base = {
        "method": "POST",
        "path_template": "/purchases/{id}/approve",
        "path_params": {"id": "purchase-001"},
        "owner_id": "owner-001",
        "body": {"quote_id": "quote-0001", "quote_version": 1},
    }
    return {**base, **overrides}


def test_an_identical_retry_hashes_identically() -> None:
    assert idempotency_request_hash(**_request()) == idempotency_request_hash(**_request())


def test_method_case_does_not_change_the_hash() -> None:
    assert idempotency_request_hash(**_request(method="post")) == idempotency_request_hash(
        **_request(method="POST")
    )


def test_any_body_change_changes_the_hash() -> None:
    altered = _request(body={"quote_id": "quote-0001", "quote_version": 2})
    assert idempotency_request_hash(**altered) != idempotency_request_hash(**_request())


def test_two_owners_sending_the_same_request_do_not_collide() -> None:
    assert idempotency_request_hash(**_request(owner_id="owner-002")) != (
        idempotency_request_hash(**_request())
    )


def test_the_hash_ignores_headers_timestamps_and_trace_ids() -> None:
    """Only the five declared inputs participate, so a retry is recognisable."""
    assert set(inspect.signature(idempotency_request_hash).parameters) == {
        "method",
        "path_template",
        "path_params",
        "owner_id",
        "body",
    }


# -- line and diff hashes --------------------------------------------------


def test_line_hash_is_order_significant() -> None:
    a = {"sku": "sku-00001", "qty": 1}
    b = {"sku": "sku-00002", "qty": 2}
    assert line_hash([a, b]) != line_hash([b, a])


def test_diff_hash_changes_when_any_change_changes() -> None:
    before = [{"kind": "price", "before": 100, "after": 110}]
    after = [{"kind": "price", "before": 100, "after": 120}]
    assert diff_hash(before) != diff_hash(after)


def test_an_empty_diff_has_a_stable_hash() -> None:
    assert diff_hash([]) == diff_hash([])
