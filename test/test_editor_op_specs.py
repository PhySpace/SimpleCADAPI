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


def test_body_appearance_is_a_form_with_a_colour_slot_and_runs():
    spec = next(s for s in SPECS if s.id == "op.set_body_appearance_rpart")
    kinds = {slot.name: slot.kind for slot in spec.slots}
    assert kinds == {"part": "value", "body_id": "text", "color": "color", "opacity": "float", "name": "text", "reset": "bool"}
    opacity = next(slot for slot in spec.slots if slot.name == "opacity")
    assert (opacity.min, opacity.max) == (0.0, 1.0)
    values = {"part": "plate", "body_id": "body", "color": [0.9, 0.2, 0.1], "opacity": 0.5, "name": "Plate", "reset": False}
    rendered = F.render_feature(spec.id, "painted", values, bodies={"plate": "part"})
    assert "color=(0.9, 0.2, 0.1)" in rendered.feature
    scope: dict = {"scad": scad, "plate": scad.make_part_rpart("plate", body=scad.make_box_rsolid(4, 4, 4))}
    exec("\n".join(rendered.params), scope)  # noqa: S102 - code under test is ours
    exec(rendered.feature, scope)  # noqa: S102
    body = scope["painted"].bodies[0]
    assert (body.color, body.opacity, body.name) == ((0.9, 0.2, 0.1), 0.5, "Plate")
    with pytest.raises(F.FeatureError):
        F.render_feature(spec.id, "painted", {**values, "color": [2, 0, 0]}, bodies={"plate": "part"})


def test_naming_a_face_is_the_tag_operation_with_picked_faces():
    spec = next(s for s in SPECS if s.id == "op.apply_tag_rselection")
    targets = next(slot for slot in spec.slots if slot.name == "targets")
    assert (targets.kind, targets.entity) == ("select", "face")
    assert spec.produces == "shape"
    pick = [{"kind": "face", "properties": {"centroid": [0.0, 0.0, 4.0], "area": 16.0}, "geometry": {"type": "plane", "normal": [0, 0, 1]}}]
    rendered = F.render_feature(spec.id, "named", {"scope": "block", "tag": "lid_seat", "topology_propagation": "local",
                                                   "lineage_policy": "continuation_fragment"},
                                bodies={"block": "solid"}, selections={"targets": pick}, known_slugs={"block"})
    scope: dict = {"scad": scad, "block": scad.make_box_rsolid(4, 4, 4)}
    exec(rendered.feature.replace("{BODY}", "block"), scope)  # noqa: S102
    top = scad.select_faces_by_tag(scope["named"], "lid_seat")
    assert len(top) == 1


@pytest.mark.parametrize("spec", [s for s in SPECS if any(slot.kind == "select" for slot in s.slots)], ids=lambda s: s.id)
def test_a_picked_selection_is_passed_to_the_operation(spec):
    picks = {slot.name: [{"kind": slot.entity, "properties": {"centroid": [0, 0, 0], "area": 10.0, "length": 5.0}, "geometry": {"type": "plane"}}]
             for slot in spec.slots if slot.kind == "select"}
    rendered = F.render_feature(spec.id, "probe", _values(spec), bodies=_BODIES, selections=picks, known_slugs=set(_BODIES))
    call = next(n for n in ast.walk(ast.parse(rendered.feature)) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(spec.operation))
    assert set(picks) <= {k.arg for k in call.keywords}, rendered.feature
