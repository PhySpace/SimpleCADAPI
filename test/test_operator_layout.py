"""Where the operators live.

An operator is implemented in the module of its family (transforms next to
``translate_shape``, booleans next to ``union_rsolid``, features next to
``extrude_rsolid``).  The one-feature modules the converters' operators were
first written in remain as thin aliases of the new places: old imports keep
working and say where to import from instead.
"""

from __future__ import annotations

import importlib
import warnings

import pytest

import simplecadapi

HOME = {
    "scale_rsolid": "transform",
    "transform_rsolid": "transform",
    "boolean_rsolidlist": "boolean",
    "offset_rsolid": "features",
    "draft_rsolid": "features",
    "extrude_taper_rsolid": "features",
    "extrude_until_rsolid": "features",
    "sweep_multisection_rsolid": "features",
}

OLD = {
    "deformation": ["scale_rsolid", "transform_rsolid", "offset_rsolid", "boolean_rsolidlist"],
    "draft": ["draft_rsolid"],
    "section_features": ["extrude_taper_rsolid", "sweep_multisection_rsolid"],
    "limited_extrusion": ["extrude_until_rsolid"],
}


@pytest.mark.parametrize("name,module", sorted(HOME.items()))
def test_an_operator_is_implemented_in_the_module_of_its_family(name, module):
    assert getattr(simplecadapi, name).__module__ == f"simplecadapi.operators.{module}"


@pytest.mark.parametrize("old,names", sorted(OLD.items()))
def test_the_old_module_paths_still_work_and_point_to_the_new_place(old, names):
    module = importlib.import_module(f"simplecadapi.operators.{old}")
    for name in names:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            found = getattr(module, name)
        assert found is getattr(simplecadapi, name)
        assert any(issubclass(w.category, DeprecationWarning) and HOME[name] in str(w.message) for w in caught), name


def test_a_name_that_never_existed_is_still_an_attribute_error():
    module = importlib.import_module("simplecadapi.operators.deformation")
    with pytest.raises(AttributeError):
        module.no_such_operator


def test_the_package_root_exports_each_once():
    assert len(simplecadapi.__all__) == len(set(simplecadapi.__all__))
    for name in HOME:
        assert name in simplecadapi.__all__
