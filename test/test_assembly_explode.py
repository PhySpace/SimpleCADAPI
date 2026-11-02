"""explode_rassembly: an exploded view as a pure function of the assembly."""

from __future__ import annotations

import json
import math

import pytest

import simplecadapi as scad
from simplecadapi.product.connector import resolve_connector_ref_placement
from simplecadapi.recording.serializer import export_graph_json, import_graph_json, replay_graph


def cross():
    """Four 2 x 2 x 2 boxes (centred on x and y, standing on z = 0): one at the origin, three 10 away on the axes."""
    part = scad.make_part_rpart("cube", scad.make_box_rsolid(2.0, 2.0, 2.0))
    assembly = scad.make_assembly_rassembly("cross")
    for cid, origin in [("c0", (0, 0, 0)), ("cx", (10, 0, 0)), ("cy", (0, 10, 0)), ("cz", (0, 0, 10))]:
        assembly = scad.add_component_rassembly(assembly, part, cid, scad.make_placement_rplacement(origin))
    return assembly


def origins(assembly):
    return {c.component_id: tuple(c.placement.origin) for c in assembly.components}


SIZE = math.sqrt(3.0) * 12.0  # the bodies span [-1, 11] x [-1, 11] x [0, 12]
MIDDLE = (5.0, 5.0, 6.0)


def test_each_component_moves_away_from_the_centre_by_factor_times_the_size():
    assembly = cross()
    exploded = scad.explode_rassembly(assembly, 1.0)
    info = exploded.get_metadata("explode")
    assert info["size"] == pytest.approx(SIZE) and info["center"] == pytest.approx(list(MIDDLE))
    before = origins(assembly)
    for cid, start in before.items():
        centre = (start[0], start[1], start[2] + 1.0)
        away = [c - m for c, m in zip(centre, MIDDLE)]
        norm = math.sqrt(sum(a * a for a in away))
        expected = tuple(s + SIZE * a / norm for s, a in zip(start, away))
        assert origins(exploded)[cid] == pytest.approx(expected)
        assert info["displacements"][cid] == pytest.approx([SIZE * a / norm for a in away])
    assert origins(assembly) == before  # the input is untouched


def test_factor_scales_linearly_and_zero_is_the_same_placement_set():
    assembly = cross()
    half = origins(scad.explode_rassembly(assembly, 0.5))
    full = origins(scad.explode_rassembly(assembly, 1.0))
    start = origins(assembly)
    for cid in start:
        assert half[cid] == pytest.approx(tuple((a + b) / 2 for a, b in zip(start[cid], full[cid])))
    assert origins(scad.explode_rassembly(assembly, 0)) == start
    assert origins(scad.explode_rassembly(assembly, -1.0))["cx"][0] < 10.0  # a negative factor implodes


def test_weights_directions_axis_and_center():
    assembly = cross()
    held = scad.explode_rassembly(assembly, 1.0, weights={"cx": 0.0})
    assert origins(held)["cx"] == (10.0, 0.0, 0.0)  # listed with weight 0: stays; nothing else is held back
    assert origins(held)["cy"][1] > 10.0

    along = scad.explode_rassembly(assembly, 0.5, directions={"cx": (0, 0, 2)})
    assert origins(along)["cx"] == pytest.approx((10.0, 0.0, 0.5 * SIZE))  # normalised: the length of 2 is not used

    axial = origins(scad.explode_rassembly(assembly, 1.0, axis=(0, 0, 3)))
    assert axial["cz"] == pytest.approx((0.0, 0.0, 10.0 + SIZE))  # above the centre: up
    assert axial["cx"] == pytest.approx((10.0, 0.0, -SIZE))  # below it: down

    around_cx = scad.explode_rassembly(assembly, 1.0, center=(10, 0, 1))
    assert origins(around_cx)["cx"] == (10.0, 0.0, 0.0)  # at the centre: no direction, stays
    assert around_cx.get_metadata("explode")["stationary"] == ["cx"]


def test_parts_constraints_and_grounding_are_untouched_and_the_result_is_a_display_copy():
    part = scad.make_part_rpart("p", scad.make_box_rsolid(1.0, 1.0, 1.0))
    axis = scad.make_placement_connector_rconnector("axis", scad.identity_placement_rplacement())
    part = scad.add_connector_rpart(part, axis)
    assembly = scad.make_assembly_rassembly("pair")
    assembly = scad.add_component_rassembly(assembly, part, "base", scad.identity_placement_rplacement())
    assembly = scad.add_component_rassembly(assembly, part, "lid", scad.make_placement_rplacement((0, 0, 5)))
    assembly = scad.ground_component_rassembly(assembly, "base")
    assembly = scad.add_fixed_constraint_rassembly(
        assembly,
        "mate",
        scad.make_connector_ref_rconnectorref("base", "axis"),
        scad.make_connector_ref_rconnectorref("lid", "axis"),
    )
    exploded = scad.explode_rassembly(assembly, 1.0, weights={"base": 0.0})
    assert exploded.grounded_component_ids == assembly.grounded_component_ids
    assert [c.constraint_id for c in exploded.constraints] == ["mate"]
    assert exploded.component_ids() == assembly.component_ids()
    assert origins(exploded)["base"] == (0.0, 0.0, 0.0) and origins(exploded)["lid"][2] > 5.0
    assert exploded.get_component("lid").item is assembly.get_component("lid").item or (
        exploded.get_component("lid").item.part_id == "p"
    )
    # the connector frame of the moved component goes with it
    frame = resolve_connector_ref_placement(exploded, scad.make_connector_ref_rconnectorref("lid", "axis"))
    assert tuple(frame.origin) == pytest.approx(origins(exploded)["lid"])


def test_nested_assemblies_move_as_one_component():
    part = scad.make_part_rpart("p", scad.make_box_rsolid(1.0, 1.0, 1.0))
    inner = scad.make_assembly_rassembly("inner")
    inner = scad.add_component_rassembly(inner, part, "a", scad.identity_placement_rplacement())
    inner = scad.add_component_rassembly(inner, part, "b", scad.make_placement_rplacement((2, 0, 0)))
    outer = scad.make_assembly_rassembly("outer")
    outer = scad.add_component_rassembly(outer, part, "base", scad.identity_placement_rplacement())
    outer = scad.add_component_rassembly(outer, inner, "group", scad.make_placement_rplacement((20, 0, 0)))
    exploded = scad.explode_rassembly(outer, 1.0)
    assert origins(exploded)["group"][0] > 20.0
    assert [c.component_id for c in exploded.get_component("group").item.components] == ["a", "b"]


def test_an_empty_assembly_is_returned_as_it_is_and_bad_arguments_are_refused_by_name():
    assert scad.explode_rassembly(scad.make_assembly_rassembly("none"), 1.0).components == ()
    assembly = cross()
    cases = [
        (dict(factor=float("nan")), "factor must be a finite number"),
        (dict(factor=1.0, axis=(0, 0, 0)), "axis must be a finite, nonzero vector"),
        (dict(factor=1.0, center=(1, 2)), "center must be a 3-element"),
        (dict(factor=1.0, directions={"ghost": (1, 0, 0)}), "directions names 'ghost'"),
        (dict(factor=1.0, directions={"c0": (0, 0, 0)}), "component 'c0' must be a finite, nonzero vector"),
        (dict(factor=1.0, weights={"ghost": 1.0}), "components: c0, cx, cy, cz"),
        (dict(factor=1.0, weights={"c0": float("inf")}), "weight of component 'c0'"),
        (dict(factor=1.0, directions=[1, 2]), "directions must be a dict"),
        (dict(factor=1.0, weights=3), "weights must be a dict"),
        (dict(factor="x"), "factor must be numeric"),
    ]
    for kwargs, expected in cases:
        with pytest.raises(ValueError) as caught:
            scad.explode_rassembly(assembly, **kwargs)
        text = str(caught.value)
        assert "Operation: explode_rassembly" in text and "What happened:" in text and expected in text, (kwargs, text)
    with pytest.raises(ValueError) as caught:
        scad.explode_rassembly("not an assembly", 1.0)
    assert "assembly must be an Assembly" in str(caught.value)


def test_a_flat_assembly_has_no_size_to_scale_by():
    flat = scad.make_assembly_rassembly("pt")
    part = scad.make_part_rpart("p", scad.make_box_rsolid(1.0, 1.0, 1.0))
    flat = scad.add_component_rassembly(flat, part, "only", scad.identity_placement_rplacement())
    exploded = scad.explode_rassembly(flat, 1.0)  # one box has a size: it stays where it is (it is the centre)
    assert origins(exploded)["only"] == (0.0, 0.0, 0.0)
    assert exploded.get_metadata("explode")["stationary"] == ["only"]


def test_explode_is_recorded_and_replayed_from_model_json():
    with scad.GraphSession() as session:
        assembly = cross()
        exploded = scad.explode_rassembly(
            assembly, 0.5, center=(5, 5, 6), axis=None, directions={"cx": (0, 0, 1)}, weights={"cy": 0.25}
        )
        session.capture_result(value=exploded)
    payload = json.loads(export_graph_json(session.graph))
    node = next(n for n in payload["nodes"] if n["op"] == "explode_rassembly")
    assert node["params"]["factor"] == 0.5 and node["params"]["center"] == [5.0, 5.0, 6.0]
    assert node["params"]["directions"] == {"cx": [0.0, 0.0, 1.0]} and node["params"]["weights"] == {"cy": 0.25}
    assert len(node["inputs"]) == 1
    rebuilt = replay_graph(import_graph_json(json.dumps(payload)))
    assert origins(rebuilt[0]) == pytest.approx(origins(exploded))


def test_a_var_factor_is_kept_in_the_graph_as_a_parameter():
    factor = scad.var("explode_factor", 1.0)
    with scad.GraphSession() as session:
        exploded = scad.explode_rassembly(cross(), factor)
        session.capture_result(value=exploded)
    node = next(n for n in json.loads(export_graph_json(session.graph))["nodes"] if n["op"] == "explode_rassembly")
    assert node["params"]["factor"] == 1.0
    assert origins(exploded)["cx"][0] > 10.0
