"""Regression tests for the two defects P3 flagged in the port adapter.

Both bugs matter once WP-02-A1 makes an estimated total approvable rather
than inert: a fee silently treated as zero, or a completeness silently
treated as fully verified, would let a shopper approve a wrong number.
"""

from __future__ import annotations

from datetime import UTC, datetime

from services.domain.money import ChargeKind, Confidence
from services.merchants.base import Merchant
from services.merchants.models import FeeAssessment, ItemQuery, Line, Location, Observation
from services.merchants.p3_merchant_port_adapter import P3MerchantPortAdapter

LOCATION = Location(locality="Connaught Place", pincode="110001")
LINES = [Line(sku="rice-5kg", quantity=1, price_paise=65000)]


class _StubMerchant(Merchant):
    name = "stub"

    def __init__(self, assessment: FeeAssessment | None) -> None:
        self._assessment = assessment

    def search(
        self, location: Location, item: ItemQuery, deadline: datetime
    ) -> list[Observation]:
        raise NotImplementedError

    def refresh(self, location: Location, sku: str, deadline: datetime) -> Observation:
        raise NotImplementedError

    def assess_fees(
        self, location: Location, exact_lines: list[Line], deadline: datetime
    ) -> FeeAssessment | None:
        return self._assessment


def _adapter(assessment: FeeAssessment | None) -> P3MerchantPortAdapter:
    return P3MerchantPortAdapter(
        _StubMerchant(assessment), line_lookup=lambda _line_hash: LINES
    )


def test_a_fee_the_merchant_did_not_report_is_an_unknown_charge_not_dropped() -> None:
    assessment = FeeAssessment(
        merchant="stub",
        location=LOCATION,
        line_hash="whatever",
        subtotal_paise=65000,
        delivery_fee_paise=3000,
        platform_fee_paise=None,  # merchant didn't report this one at all
        other_fees_paise=1100,
        completeness="estimated",
        fetch_time=datetime.now(UTC),
    )
    charges = _adapter(assessment).assess_fees("110001", "stub", "whatever", 30)
    assert isinstance(charges, tuple)

    by_kind = {c.kind: c for c in charges}
    # The unreported platform fee must show up as an explicit unknown
    # charge -- never silently omitted, which would let it be read as zero.
    assert by_kind[ChargeKind.OTHER].confidence is Confidence.UNKNOWN
    assert by_kind[ChargeKind.OTHER].amount is None
    # The two fees the merchant did report stay estimated, not dragged down.
    assert by_kind[ChargeKind.DELIVERY].confidence is Confidence.ESTIMATED
    assert by_kind[ChargeKind.HANDLING].confidence is Confidence.ESTIMATED


def test_an_unrecognised_completeness_string_becomes_unknown_not_verified() -> None:
    assessment = FeeAssessment(
        merchant="stub",
        location=LOCATION,
        line_hash="whatever",
        subtotal_paise=65000,
        delivery_fee_paise=3000,
        platform_fee_paise=200,
        other_fees_paise=0,
        completeness="totally-fresh-value-nobody-agreed-on",
        fetch_time=datetime.now(UTC),
    )
    charges = _adapter(assessment).assess_fees("110001", "stub", "whatever", 30)
    assert isinstance(charges, tuple)
    assert all(c.confidence is Confidence.UNKNOWN for c in charges)


def test_a_recognised_complete_assessment_still_maps_to_verified() -> None:
    assessment = FeeAssessment(
        merchant="stub",
        location=LOCATION,
        line_hash="whatever",
        subtotal_paise=65000,
        delivery_fee_paise=3000,
        platform_fee_paise=200,
        other_fees_paise=0,
        completeness="complete",
        fetch_time=datetime.now(UTC),
    )
    charges = _adapter(assessment).assess_fees("110001", "stub", "whatever", 30)
    assert isinstance(charges, tuple)
    assert all(c.confidence is Confidence.VERIFIED for c in charges)
