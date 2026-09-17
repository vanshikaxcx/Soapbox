"""Money, charges and totals (WP-02).

Money is integer paise. There is no float, no Decimal coercion at a boundary,
and no division operator on Money -- division is what turns exact arithmetic
into approximately-right arithmetic.

An unknown fee is representable in exactly one way: ``confidence=UNKNOWN`` with
``amount=None``. There is no code path in this module that produces a zero-paise
unknown fee, because "we don't know" and "it's free" are different claims and
only one of them is honest.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from fractions import Fraction

from pydantic import Field, model_validator

from services.domain.errors import BudgetExceeded
from services.domain.ids import Record
from services.domain.units import Quantity


class Currency(StrEnum):
    INR = "INR"


class Confidence(StrEnum):
    """How well we know an amount. Ordered worst-wins when combined."""

    VERIFIED = "verified"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


#: Higher is worse. Used to take the worst confidence across many amounts.
_BADNESS: dict[Confidence, int] = {
    Confidence.VERIFIED: 0,
    Confidence.ESTIMATED: 1,
    Confidence.UNKNOWN: 2,
}


def worst(confidences: Sequence[Confidence]) -> Confidence:
    """The worst confidence in a collection; VERIFIED when empty."""
    return max(confidences, key=lambda c: _BADNESS[c], default=Confidence.VERIFIED)


class ChargeKind(StrEnum):
    DELIVERY = "delivery"
    HANDLING = "handling"
    PACKAGING = "packaging"
    SMALL_ORDER = "small_order"
    SURGE = "surge"
    TAX = "tax"
    OTHER = "other"


class Money(Record):
    """A non-negative amount of money, in integer paise."""

    amount_paise: int = Field(ge=0)
    currency: Currency = Currency.INR

    @classmethod
    def paise(cls, amount: int) -> Money:
        return cls(amount_paise=amount)

    def add(self, other: Money) -> Money:
        _same_currency(self, other)
        return Money(amount_paise=self.amount_paise + other.amount_paise, currency=self.currency)

    def subtract(self, other: Money) -> Money:
        _same_currency(self, other)
        if other.amount_paise > self.amount_paise:
            raise ValueError("Money cannot go negative; use MoneyDelta for signed differences")
        return Money(amount_paise=self.amount_paise - other.amount_paise, currency=self.currency)

    def times(self, factor: int) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, int) or factor < 0:
            raise TypeError("money may only be multiplied by a non-negative whole number")
        return Money(amount_paise=self.amount_paise * factor, currency=self.currency)


class MoneyDelta(Record):
    """A signed difference between two amounts. Never a price, never a total."""

    amount_paise: int
    currency: Currency = Currency.INR


def difference(later: Money, earlier: Money) -> MoneyDelta:
    _same_currency(later, earlier)
    return MoneyDelta(
        amount_paise=later.amount_paise - earlier.amount_paise, currency=later.currency
    )


def _same_currency(left: Money, right: Money) -> None:
    if left.currency is not right.currency:
        raise ValueError(f"currency mismatch: {left.currency} vs {right.currency}")


def total_of(amounts: Sequence[Money]) -> Money:
    """Sum money by addition only. This is the only way a total is ever built."""
    if not amounts:
        return Money.paise(0)
    result = amounts[0]
    for amount in amounts[1:]:
        result = result.add(amount)
    return result


def unit_rate(amount: Money, quantity: Quantity, per_base_units: int = 100) -> Fraction:
    """An exact "price per N base units" rate, for comparison and display only.

    Returned as a Fraction, never a float and never a Money. It may not be
    summed, stored as a price, or used to build a line or quote total: totals
    are only ever built by adding integer paise. Rounding here would compound
    into a total that disagrees with the sum of its own lines.
    """
    if quantity.value_base <= 0:
        raise ValueError("cannot compute a rate for a zero quantity")
    if per_base_units <= 0:
        raise ValueError("rate basis must be positive")
    return Fraction(amount.amount_paise * per_base_units, quantity.value_base)


class Amount(Record):
    """An amount we may or may not know.

    The invariant is the whole point: UNKNOWN if and only if there is no value.
    An unknown fee can never be stored as zero, and a known fee can never be
    stored without its number.
    """

    amount: Money | None
    confidence: Confidence

    @model_validator(mode="after")
    def _unknown_iff_absent(self) -> Amount:
        unknown = self.confidence is Confidence.UNKNOWN
        absent = self.amount is None
        if unknown != absent:
            raise ValueError(
                "confidence UNKNOWN requires amount=None, and a known amount "
                "requires confidence VERIFIED or ESTIMATED"
            )
        return self

    @classmethod
    def known(cls, amount: Money, confidence: Confidence = Confidence.VERIFIED) -> Amount:
        if confidence is Confidence.UNKNOWN:
            raise ValueError("a known amount cannot have UNKNOWN confidence")
        return cls(amount=amount, confidence=confidence)

    @classmethod
    def unknown(cls) -> Amount:
        return cls(amount=None, confidence=Confidence.UNKNOWN)


class Charge(Amount):
    """A basket-level fee. Fees are never attributed to individual lines."""

    kind: ChargeKind

    @classmethod
    def known_charge(
        cls, kind: ChargeKind, amount: Money, confidence: Confidence = Confidence.VERIFIED
    ) -> Charge:
        if confidence is Confidence.UNKNOWN:
            raise ValueError("a known charge cannot have UNKNOWN confidence")
        return cls(kind=kind, amount=amount, confidence=confidence)

    @classmethod
    def unknown_charge(cls, kind: ChargeKind) -> Charge:
        return cls(kind=kind, amount=None, confidence=Confidence.UNKNOWN)


class Totals(Record):
    """The published shape of a basket's cost, as two bounds.

    ``total`` is None exactly when confidence is UNKNOWN. When present it is the
    basket's **ceiling**: for a VERIFIED basket it is the exact cost, and for an
    ESTIMATED one it is the most the basket should cost, because every estimated
    charge is carried at its upper bound (see WP-02-A1 §3).

    ``floor`` is the **only** true lower bound. It sums VERIFIED amounts alone;
    estimated and unknown amounts contribute nothing, because an estimated fee's
    real minimum is not known -- a free-delivery threshold can take it to zero.

    ``known_subtotal`` is neither bound. It is "every number we have", estimates
    included, and is published so a shopper can be shown a figure when the total
    is unknown. It was previously documented as a lower bound; that was wrong for
    estimated baskets and the comparator no longer relies on it.
    """

    known_subtotal: Money
    floor: Money
    total: Money | None
    confidence: Confidence
    unknown_charges: tuple[ChargeKind, ...]
    unpriced_lines: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _total_absent_iff_unknown(self) -> Totals:
        unknown = self.confidence is Confidence.UNKNOWN
        if unknown != (self.total is None):
            raise ValueError("total must be absent exactly when confidence is UNKNOWN")
        if unknown and not (self.unknown_charges or self.unpriced_lines):
            raise ValueError(
                "an unknown total must name an unknown charge or an unpriced line"
            )
        if not unknown and (self.unknown_charges or self.unpriced_lines):
            raise ValueError("a known total cannot carry unknowns")
        if self.floor.amount_paise > self.known_subtotal.amount_paise:
            raise ValueError("floor cannot exceed the known subtotal")
        if self.total is not None and self.floor.amount_paise > self.total.amount_paise:
            # The comparator proves "cheaper" from ceiling < floor. If a basket's
            # own floor could sit above its own ceiling the relation would admit
            # contradictions, so the impossible state is refused at construction.
            raise ValueError("floor cannot exceed the ceiling")
        return self


def compute_totals(lines: Sequence[Amount], charges: Sequence[Charge]) -> Totals:
    """Combine line amounts and basket charges into a published total.

    Worst confidence wins. Any unknown charge makes the whole total unknown, in
    which case there is no ceiling and ``known_subtotal`` is published instead so
    the shopper still sees a figure.

    ``floor`` is computed in every case, including the unknown one: the amounts
    we have verified are a lower bound whether or not the rest is known, and that
    is what lets the comparator rule a basket out without pricing it.
    """
    known: list[Money] = [a.amount for a in lines if a.amount is not None]
    known += [c.amount for c in charges if c.amount is not None]
    known_subtotal = total_of(known)

    # The floor counts VERIFIED amounts only. An estimated charge is carried at
    # its upper bound, so it says nothing about how low the basket can go, and
    # an unknown one says nothing at all.
    certain: list[Money] = [
        a.amount for a in lines if a.amount is not None and a.confidence is Confidence.VERIFIED
    ]
    certain += [
        c.amount for c in charges if c.amount is not None and c.confidence is Confidence.VERIFIED
    ]
    floor = total_of(certain)

    confidences = [a.confidence for a in lines] + [c.confidence for c in charges]
    confidence = worst(confidences)

    unknown_charges = tuple(c.kind for c in charges if c.confidence is Confidence.UNKNOWN)
    unpriced_lines = sum(1 for a in lines if a.confidence is Confidence.UNKNOWN)

    if confidence is Confidence.UNKNOWN:
        # An unpriced line is reported as exactly that. Folding it into a phantom
        # "other" charge would have the UI tell a shopper we could not confirm a
        # fee when the truth is we could not price an item -- a false statement
        # on the one surface that exists to be honest.
        return Totals(
            known_subtotal=known_subtotal,
            floor=floor,
            total=None,
            confidence=Confidence.UNKNOWN,
            unknown_charges=unknown_charges,
            unpriced_lines=unpriced_lines,
        )

    return Totals(
        known_subtotal=known_subtotal,
        floor=floor,
        total=known_subtotal,
        confidence=confidence,
        unknown_charges=(),
        unpriced_lines=0,
    )


class BudgetCheck(StrEnum):
    WITHIN = "within"
    EXCEEDED = "exceeded"
    UNKNOWN = "unknown"


def check_budget(totals: Totals, budget_paise: int | None) -> BudgetCheck | BudgetExceeded:
    """Compare a total against a budget.

    An unknown total is never reported as within budget, however small the known
    subtotal is. Equality is within: a total of exactly the budget is affordable.
    """
    if budget_paise is None:
        return BudgetCheck.WITHIN
    if totals.total is None:
        return BudgetCheck.UNKNOWN
    if totals.total.amount_paise > budget_paise:
        return BudgetExceeded(budget_paise=budget_paise, total_paise=totals.total.amount_paise)
    return BudgetCheck.WITHIN


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "Amount",
    "BudgetCheck",
    "Charge",
    "ChargeKind",
    "Confidence",
    "Currency",
    "Money",
    "MoneyDelta",
    "Totals",
    "check_budget",
    "compute_totals",
    "difference",
    "total_of",
    "unit_rate",
    "worst",
]
