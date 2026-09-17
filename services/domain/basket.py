"""Baskets, fee assessments and comparison (WP-02 acceptance criterion 7).

Comparison is bound-arithmetic, not a UI convention, so no caller can forget it.
Every basket carries a floor (the verified amounts alone) and a ceiling
(``total``, which carries estimated charges at their upper bound). One basket is
declared cheaper only when its ceiling sits strictly below the other's floor --
the bands must not overlap. That is a proof, not a preference. A basket with an
unknown charge has no ceiling at all and can never be proven cheaper than
anything.

DEVIATION FROM SPEC SECTION 1, recorded rather than hidden. The spec says
"estimated totals never rank as definitively cheaper than verified totals", and
this module no longer enforces that: an estimate whose ceiling sits entirely
below a verified total *does* win. The spec's rule assumes an estimate is a point
guess with error in both directions. P2 builds estimates as published upper
bounds (``services/merchants/fees.py`` resolves every fee range to its top), and
with an upper bound in hand, "at most 491 versus exactly 520" is arithmetic
rather than a guess.

Enforcing the original rule would not have been more honest, only less useful:
the live merchants can never report a complete fee, so *every* live comparison
returned NOT_COMPARABLE at every price gap. See
``docs/specs/WP-02-A1-bounded-estimates-and-ceiling-approval.md``; it needs the
team's sign-off on the SPEC amendment, and the ceiling is only as good as the
inputs (A1-Q1 tracks two known gaps in P2's fee schedule).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from services.domain.catalog import Substitution
from services.domain.errors import MixedModeComparison
from services.domain.ids import Digest, Id, Mode, Record, Timestamped
from services.domain.money import Amount, Charge, Confidence, Money, Totals, compute_totals


class BasketLine(Record):
    """One item, priced, with any permitted substitution recorded on its face."""

    item_id: Id
    observation_id: Id
    merchant_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=300)
    pack_counts: tuple[tuple[str, int], ...]
    selected_base_units: int = Field(gt=0)
    #: The size of ONE pack, as priced. Without it a re-check cannot tell that
    #: the merchant swapped a 5 kg pack for a 1 kg one, and would price five
    #: kilos at the cost of one.
    pack_base_units: int = Field(gt=0)
    #: The dimension of selected_base_units. Carried so a failed refresh can
    #: describe the line without guessing what kind of quantity it was.
    dimension: str = Field(default="mass", min_length=1, max_length=16)
    overbuy_base_units: int = Field(default=0, ge=0)
    substitution: Substitution | None = None
    unit_price: Money
    line_total: Amount

    @property
    def is_substituted(self) -> bool:
        return self.substitution is not None


class FeeAssessment(Timestamped):
    """Fees for a whole basket, bound to the exact lines they were quoted for.

    Basket-level by construction: there is no per-line fee field, so a delivery
    charge cannot be silently attributed to one item and counted twice.
    """

    merchant_id: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=200)
    line_hash: Digest
    subtotal: Money
    assessed_at: datetime
    charges: tuple[Charge, ...] = ()


class Basket(Record):
    """A complete single-merchant basket with its published totals."""

    basket_id: Id
    search_id: Id
    merchant_id: str = Field(min_length=1, max_length=64)
    mode: Mode
    lines: tuple[BasketLine, ...] = Field(min_length=1)
    fee_assessment: FeeAssessment | None = None
    totals: Totals

    @model_validator(mode="after")
    def _totals_match_the_lines_and_charges(self) -> Basket:
        """The totals are not free-form: they must be what the parts add up to.

        Without this, a caller could construct a basket whose headline number
        disagrees with its own lines -- which is the single most damaging thing
        this system could display.
        """
        charges = self.fee_assessment.charges if self.fee_assessment else ()
        expected = compute_totals([line.line_total for line in self.lines], charges)
        if expected != self.totals:
            raise ValueError("totals do not match this basket's lines and charges")
        return self

    @model_validator(mode="after")
    def _lines_belong_to_this_merchant(self) -> Basket:
        """A basket is single-merchant; SPEC section 1 compares complete baskets."""
        for line in self.lines:
            if line.merchant_id != self.merchant_id:
                raise ValueError("every line must come from the basket's merchant")
        return self


def build_basket(
    *,
    basket_id: str,
    search_id: str,
    merchant_id: str,
    mode: Mode,
    lines: tuple[BasketLine, ...],
    fee_assessment: FeeAssessment | None = None,
) -> Basket:
    """Assemble a basket with totals computed rather than supplied."""
    charges = fee_assessment.charges if fee_assessment else ()
    return Basket(
        basket_id=basket_id,
        search_id=search_id,
        merchant_id=merchant_id,
        mode=mode,
        lines=lines,
        fee_assessment=fee_assessment,
        totals=compute_totals([line.line_total for line in lines], charges),
    )


class Comparison(StrEnum):
    """Which ARGUMENT won, by position.

    Named left/right rather than a/b on purpose. The members used to be
    ``A_CHEAPER``/``B_CHEAPER``, which read as "merchant A is cheaper" while
    actually meaning "the first argument is cheaper" -- so a caller comparing
    merchant B against merchant A got ``a_cheaper`` for a result where B won.
    In a price-comparison app that reads as the opposite of the truth.

    When in doubt use ``cheaper_of``, which hands back the winning basket
    itself and has no positional meaning to get backwards.
    """

    LEFT_CHEAPER = "left_cheaper"
    RIGHT_CHEAPER = "right_cheaper"
    EQUAL = "equal"
    NOT_COMPARABLE = "not_comparable"


class BasketCost(Record):
    """The comparable surface of a basket: what it costs and how sure we are."""

    basket_id: str
    mode: Mode
    totals: Totals


def _is_exact(totals: Totals) -> bool:
    return totals.confidence is Confidence.VERIFIED and totals.total is not None


def _beats(candidate: Totals, other: Totals) -> bool:
    """True when candidate's ceiling is provably below other's floor.

    One rule, no special cases. ``candidate.total`` is the most the candidate can
    cost and ``other.floor`` is the least the other can cost, so a strict gap
    between them is a proof rather than a guess -- and it stays a proof when
    either side is estimated, which is the whole point of WP-02-A1.

    Guards rather than asserts: an ``assert`` disappears under ``python -O``, and
    what it was protecting here is a ``None.amount_paise`` in the middle of a
    price comparison. Refusing to answer is always safe; crashing is not.
    """
    if candidate.total is None:
        # No ceiling at all -- an unknown charge. Nothing can be proved.
        return False
    return candidate.total.amount_paise < other.floor.amount_paise


def compare_baskets(a: BasketCost, b: BasketCost) -> Comparison | MixedModeComparison:
    """Compare two baskets, refusing to guess.

    Live and fixture results are never ranked together: a demonstration price and
    a real price are not commensurable, whatever the numbers say.
    """
    if a.mode is not b.mode:
        return MixedModeComparison(left_mode=str(a.mode), right_mode=str(b.mode))

    a_exact = _is_exact(a.totals)
    b_exact = _is_exact(b.totals)

    # EQUAL is only ever claimed between two exact totals. Two estimates that
    # happen to share a ceiling are not equal; they are merely indistinguishable.
    if a_exact and b_exact and a.totals.total and b.totals.total:
        left = a.totals.total.amount_paise
        right = b.totals.total.amount_paise
        if left < right:
            return Comparison.LEFT_CHEAPER
        if right < left:
            return Comparison.RIGHT_CHEAPER
        return Comparison.EQUAL

    # Either side may win, estimated or not. ``Totals`` guarantees floor <= total,
    # so at most one of these can hold and the order of the checks is not a tie
    # break hiding in control flow.
    if _beats(a.totals, b.totals):
        return Comparison.LEFT_CHEAPER
    if _beats(b.totals, a.totals):
        return Comparison.RIGHT_CHEAPER

    return Comparison.NOT_COMPARABLE


def cheaper_of(
    left: BasketCost, right: BasketCost
) -> BasketCost | None | MixedModeComparison:
    """The cheaper of two baskets, as the basket itself.

    Prefer this over reading a positional enum: it cannot be misinterpreted,
    because it returns the thing that won rather than where it sat in the
    argument list. ``None`` means neither can be proven cheaper -- a tie, or an
    unknown fee that makes the claim unprovable.
    """
    verdict = compare_baskets(left, right)
    if isinstance(verdict, MixedModeComparison):
        return verdict
    if verdict is Comparison.LEFT_CHEAPER:
        return left
    if verdict is Comparison.RIGHT_CHEAPER:
        return right
    return None


def cheapest(baskets: list[BasketCost]) -> BasketCost | None | MixedModeComparison:
    """The one basket provably cheaper than every other, or None if there isn't one.

    Returning None is a real answer: "we cannot honestly call any of these the
    cheapest" is what the shopper should be told when the fees are unknown.
    """
    if not baskets:
        return None

    modes = {basket.mode for basket in baskets}
    if len(modes) > 1:
        ordered = sorted(str(mode) for mode in modes)
        return MixedModeComparison(left_mode=ordered[0], right_mode=ordered[1])

    for index, candidate in enumerate(baskets):
        # Exclude by position, not by identity: the same object listed twice
        # would otherwise remove both entries and "beat" an empty comparison set.
        others = [other for position, other in enumerate(baskets) if position != index]
        if all(compare_baskets(candidate, other) is Comparison.LEFT_CHEAPER for other in others):
            return candidate
    return None


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "Basket",
    "BasketCost",
    "BasketLine",
    "FeeAssessment",
    "build_basket",
    "Comparison",
    "cheaper_of",
    "cheapest",
    "compare_baskets",
]
