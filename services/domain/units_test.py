"""Units and quantities (WP-02 acceptance criterion 5).

The headline rule: no mass<->volume conversion exists in any code path, and there
is no flag that enables one.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from services.domain.errors import IncompatibleUnits
from services.domain.units import (
    Dimension,
    Quantity,
    Unit,
    add,
    convert,
    dimension_of,
    scale,
)

MASS_UNITS = [Unit.G, Unit.KG]
VOLUME_UNITS = [Unit.ML, Unit.L]
COUNT_UNITS = [Unit.PIECE]


# -- permitted conversions -------------------------------------------------


@pytest.mark.parametrize(
    ("value", "unit", "expected_base"),
    [
        (0, Unit.G, 0),
        (1, Unit.G, 1),
        (999, Unit.G, 999),
        (1, Unit.KG, 1000),
        (5, Unit.KG, 5000),
        (0, Unit.ML, 0),
        (1, Unit.ML, 1),
        (1, Unit.L, 1000),
        (2, Unit.L, 2000),
        (3, Unit.PIECE, 3),
    ],
)
def test_quantities_are_expressed_in_integer_base_units(
    value: int, unit: Unit, expected_base: int
) -> None:
    assert Quantity.of(value, unit).value_base == expected_base


@pytest.mark.parametrize(("small", "big"), [(Unit.G, Unit.KG), (Unit.ML, Unit.L)])
def test_within_dimension_round_trip_is_exact(small: Unit, big: Unit) -> None:
    quantity = Quantity.of(7, big)
    assert convert(quantity, small) == 7000
    assert convert(quantity, big) == 7


def test_a_quantity_that_is_not_a_whole_number_of_the_target_unit_refuses() -> None:
    # 1500 g is not a whole number of kg. We refuse rather than round, because a
    # rounded quantity would feed a rounded price.
    assert isinstance(convert(Quantity.of(1500, Unit.G), Unit.KG), IncompatibleUnits)


def test_fractional_input_is_rejected_at_construction() -> None:
    for bad in (1.5, "1", True):
        with pytest.raises(TypeError):
            Quantity.of(bad, Unit.KG)  # type: ignore[arg-type]


# -- the forbidden conversion ---------------------------------------------


@pytest.mark.parametrize("mass_unit", MASS_UNITS)
@pytest.mark.parametrize("volume_unit", VOLUME_UNITS)
def test_mass_never_converts_to_volume_in_either_direction(
    mass_unit: Unit, volume_unit: Unit
) -> None:
    mass = Quantity.of(1, mass_unit)
    volume = Quantity.of(1, volume_unit)
    assert isinstance(convert(mass, volume_unit), IncompatibleUnits)
    assert isinstance(convert(volume, mass_unit), IncompatibleUnits)


@pytest.mark.parametrize("other", MASS_UNITS + VOLUME_UNITS)
def test_count_never_converts_to_mass_or_volume(other: Unit) -> None:
    assert isinstance(convert(Quantity.of(1, Unit.PIECE), other), IncompatibleUnits)
    assert isinstance(convert(Quantity.of(1, other), Unit.PIECE), IncompatibleUnits)


@given(
    st.sampled_from(list(Unit)),
    st.sampled_from(list(Unit)),
    st.integers(min_value=0, max_value=10**6),
)
def test_no_argument_combination_can_cross_a_dimension(
    source: Unit, target: Unit, value: int
) -> None:
    """Exhaustive property: a successful conversion implies a shared dimension."""
    result = convert(Quantity.of(value, source), target)
    if not isinstance(result, IncompatibleUnits):
        assert dimension_of(source) is dimension_of(target)


def test_convert_takes_no_density_or_override_argument() -> None:
    # Guards against a future "just this once" parameter.
    import inspect

    assert list(inspect.signature(convert).parameters) == ["quantity", "to_unit"]


# -- arithmetic ------------------------------------------------------------


def test_addition_requires_a_shared_dimension() -> None:
    assert add(Quantity.of(1, Unit.KG), Quantity.of(500, Unit.G)) == Quantity(
        value_base=1500, dimension=Dimension.MASS
    )
    assert isinstance(add(Quantity.of(1, Unit.KG), Quantity.of(1, Unit.L)), IncompatibleUnits)


def test_scaling_requires_a_whole_non_negative_factor() -> None:
    assert scale(Quantity.of(1, Unit.KG), 3).value_base == 3000
    for bad in (1.5, -1, True):
        with pytest.raises(TypeError):
            scale(Quantity.of(1, Unit.KG), bad)  # type: ignore[arg-type]
