"""One exception translator asks its handlers most specific first, whatever the order the areas were bound in."""

from __future__ import annotations

import pytest

import simplecadapi._cpp._native as native
from simplecadapi._cpp._native import _occt


def test_an_occt_failure_is_the_modules_standard_failure() -> None:
    with pytest.raises(_occt.Standard_Failure, match="Standard_ConstructionError"):
        _occt.gp_Dir(0, 0, 0)


def test_a_unit_error_is_its_own_class_not_the_general_sdk_error() -> None:
    """UnitValidationError derives from scad::Error in C++: the general handler would turn it into SimpleCADError."""
    with pytest.raises(native.UnitValidationError) as caught:
        native.LENGTH.square_root()
    assert type(caught.value) is native.UnitValidationError


def test_a_stale_lineage_error_is_its_own_class_not_a_plain_value_error() -> None:
    """StaleLineageError derives from ValueError in C++, which the general handler would also take."""
    ours, theirs = native.OperationGraph("g"), native.OperationGraph("g")
    first = ours.add_node("root", {"v": 1}, node_id="same")
    theirs.add_node("root", {"v": 2}, node_id="same")
    tip = ours.add_node("join", {}, inputs=[first])
    with pytest.raises(native.StaleLineageError) as caught:
        theirs.adopt(tip)
    assert type(caught.value) is native.StaleLineageError and caught.value.node_id == "same"
