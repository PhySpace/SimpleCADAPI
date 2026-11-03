"""The operation catalog is read from the signatures: every public operation is in it, and its parameters say what they mean."""

from __future__ import annotations

import json

import simplecadapi as scad
from simplecadapi import catalog



def test_every_public_operation_is_in_the_catalog_with_its_parameters():
    names = {op.name for op in catalog.operations()}
    public = {n for n in scad.__all__ if catalog._OP_NAME.match(n) and callable(getattr(scad, n))}
    assert public <= names
    assert {"make_spur_gear_rsolid", "make_bolt_rsolid"} <= names  # the standard library too
    json.dumps(catalog.catalog_dict(), default=str)  # plain data


def test_the_meaning_comes_from_the_binding_types():
    cylinder = catalog.operation("make_cylinder_rsolid")
    kinds = {p.name: p.kind for p in cylinder.params}
    assert (kinds["radius"], kinds["height"], kinds["bottom_face_center"], kinds["axis"]) == ("length", "length", "point3", "direction3")
    assert cylinder.returns == "solid" and cylinder.module == "simplecadapi"
    assert next(p for p in cylinder.params if p.name == "axis").default == (0, 0, 1)
    assert next(p for p in cylinder.params if p.name == "start_face_tag").keyword_only


def test_every_parameter_of_every_operation_says_what_it_is():
    """No signature reads ``object``: a new operation that does not type its parameters fails here, not in a GUI form."""
    untyped = sorted(f"{op.name}({p.name}: {p.type})" for op in catalog.operations() for p in op.params if p.kind == "unknown")
    assert not untyped, untyped


def test_types_classify():
    assert catalog.classify("Sequence[Edge]") == {"kind": "edge", "many": True, "optional": False, "choices": ()}
    assert catalog.classify("Literal['NEXT', 'LAST']")["choices"] == ("NEXT", "LAST")
    assert catalog.classify("simplecadapi.types.Angle | None") == {"kind": "angle", "many": False, "optional": True, "choices": ()}
    assert catalog.classify("Sequence[simplecadapi.types.Point3]")["kind"] == "points"


def test_sca_ops_prints_one_operation_and_the_whole_catalog(capsys):
    from simplecadapi.cli import main

    assert main(["ops", "make_cylinder_rsolid"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("make_cylinder_rsolid(radius: length, height: length, bottom_face_center: point3, axis: direction3")
    assert main(["ops", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert any(op["name"] == "make_spur_gear_rsolid" for op in data["operations"])
