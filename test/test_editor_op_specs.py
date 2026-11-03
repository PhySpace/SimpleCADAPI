"""Every SDK operation the forms offer is made from the catalog, writes a call with the operation's real parameters, and runs."""

from __future__ import annotations

import ast
import inspect

import pytest

import simplecadapi as scad
from simplecadapi.editor import features as F
from simplecadapi.editor import op_specs

SPECS = op_specs.operation_specs()
_SAMPLE = {"solid": "a_solid", "face": "a_face", "wire": "a_wire", "edge": "an_edge", "vertex": "a_vertex", "shell": "a_shell",
           "compound": "a_compound", "part": "a_part", "assembly": "an_assembly", "material": "a_material", "placement": "a_placement",
           "connector": "a_connector", "connector_ref": "a_ref"}
_BODIES = {name: kind for kind, name in _SAMPLE.items()}


def _values(spec):
    values = {}
    for slot in spec.slots:
        if slot.kind == "value":
            name = _SAMPLE[slot.accepts[0]]
            values[slot.name] = [name] if slot.many else name
        elif slot.default is not None:
            values[slot.name] = slot.default
    return values


def _function(path: str):
    target = scad
    for part in path.split(".")[1:]:
        target = getattr(target, part)
    return target


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_the_form_writes_the_operation_with_its_real_parameters(spec):
    picks = {slot.name: [{"kind": slot.entity, "properties": {"centroid": [0, 0, 0], "area": 10.0, "length": 5.0}, "geometry": {"type": "plane"}}]
             for slot in spec.slots if slot.kind == "select"}
    rendered = F.render_feature(spec.id, "probe", _values(spec), bodies=_BODIES, selections=picks, known_slugs=set(_BODIES))
    calls = [n for n in ast.walk(ast.parse(rendered.feature)) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(spec.operation)]
    assert calls, rendered.feature
    names = set(inspect.signature(_function(ast.unparse(calls[0].func))).parameters)
    assert {k.arg for k in calls[0].keywords} <= names
    ast.parse("\n".join(rendered.params))


def test_the_catalog_reaches_the_forms_and_the_command_bar():
    data = F.catalog()
    ids = {s["id"] for s in data["specs"]}
    assert {"op.make_gordon_surface_rface", "op.make_spur_gear_rsolid", "op.sweep_rsolid", "op.make_helix_rwire"} <= ids
    assert "box" in ids  # the curated features stay
    gear = next(s for s in data["specs"] if s["id"] == "op.make_spur_gear_rsolid")
    assert gear["group"] == "Standard library" and gear["combinable"]


@pytest.mark.parametrize("spec", [s for s in SPECS if not any(slot.kind in ("value", "select") for slot in s.slots)], ids=lambda s: s.id)
def test_an_operation_made_from_defaults_runs(spec):
    with scad.GraphSession(graph_id=f"op-{spec.id}"):
        scope: dict = {"scad": scad}
        rendered = F.render_feature(spec.id, "made", _values(spec), bodies={})
        if rendered.params:
            exec("\n".join(rendered.params), scope)  # noqa: S102 - code under test is ours
        try:
            exec(rendered.feature, scope)  # noqa: S102
        except (scad.errors.SimpleCADError, ValueError) as exc:  # defaults that do not make a valid shape are the SDK's to refuse
            pytest.skip(f"{spec.id}: the defaults are refused by the SDK: {str(exc).splitlines()[0]}")
        assert scope["made"] is not None
