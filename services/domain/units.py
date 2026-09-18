"""Units and quantities (WP-02).

Quantities are integers in a canonical base unit per dimension -- gram,
millilitre, piece -- so 1.5 kg is 1500 g and no float ever appears in a
quantity calculation.

Mass and volume never convert into one another. There is no density parameter,
no override flag and no configuration that enables it: the conversion table is
keyed by dimension and a cross-dimension request returns ``IncompatibleUnits``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from services.domain.errors import IncompatibleUnits
from services.domain.ids import Record


class Dimension(StrEnum):
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"


class Unit(StrEnum):
    G = "g"
    KG = "kg"
    ML = "ml"
    L = "l"
    PIECE = "piece"


#: Each unit's dimension and how many base units it is worth.
#: Base units are: mass -> gram, volume -> millilitre, count -> piece.
_UNIT_TABLE: dict[Unit, tuple[Dimension, int]] = {
    Unit.G: (Dimension.MASS, 1),
    Unit.KG: (Dimension.MASS, 1000),
    Unit.ML: (Dimension.VOLUME, 1),
    Unit.L: (Dimension.VOLUME, 1000),
    Unit.PIECE: (Dimension.COUNT, 1),
}


def dimension_of(unit: Unit) -> Dimension:
    return _UNIT_TABLE[unit][0]


def base_units_per(unit: Unit) -> int:
    return _UNIT_TABLE[unit][1]


class Quantity(Record):
    """An amount in canonical base units for its dimension."""

    value_base: int = Field(ge=0)
    dimension: Dimension

    @classmethod
    def of(cls, value: int, unit: Unit) -> Quantity:
        """Build a quantity from a whole number of ``unit``.

        Fractional input is not accepted: callers express 1.5 kg as
        ``Quantity.of(1500, Unit.G)``. Accepting 1.5 here would put a float in
        the one place we have promised there will never be one.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("quantity must be a whole number of base units")
        dimension, factor = _UNIT_TABLE[unit]
        return cls(value_base=value * factor, dimension=dimension)

    def as_unit(self, unit: Unit) -> int | IncompatibleUnits:
        """Express this quantity in ``unit``, exactly, or refuse."""
        target_dimension, factor = _UNIT_TABLE[unit]
        if target_dimension is not self.dimension:
            return IncompatibleUnits(
                from_dimension=self.dimension.value,
                to_dimension=target_dimension.value,
            )
        if self.value_base % factor != 0:
            # 1500 g is not a whole number of kg. Callers that need a display
            # value use a rate (see money.unit_rate); they never round a quantity.
            return IncompatibleUnits(
                from_dimension=self.dimension.value,
                to_dimension=target_dimension.value,
            )
        return self.value_base // factor


def convert(quantity: Quantity, to_unit: Unit) -> int | IncompatibleUnits:
    """Convert within a dimension. Mass <-> volume always refuses."""
    return quantity.as_unit(to_unit)


def add(left: Quantity, right: Quantity) -> Quantity | IncompatibleUnits:
    if left.dimension is not right.dimension:
        return IncompatibleUnits(
            from_dimension=left.dimension.value,
            to_dimension=right.dimension.value,
        )
    return Quantity(value_base=left.value_base + right.value_base, dimension=left.dimension)


def scale(quantity: Quantity, factor: int) -> Quantity:
    if isinstance(factor, bool) or not isinstance(factor, int) or factor < 0:
        raise TypeError("scale factor must be a non-negative whole number")
    return Quantity(value_base=quantity.value_base * factor, dimension=quantity.dimension)


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "Dimension",
    "Quantity",
    "Unit",
    "add",
    "base_units_per",
    "convert",
    "dimension_of",
    "scale",
]
