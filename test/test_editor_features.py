"""GUI-made features: every operation renders a cell that runs, uses only the SDK's real parameters, and cannot carry code."""

from __future__ import annotations

import ast
import inspect

import pytest

import simplecadapi as scad
from simplecadapi.editor import features as F

DEFAULTS = {spec.id: {slot.name: slot.default for slot in spec.slots if slot.kind != "select"} for spec in F.SPECS}


def _calls(source: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "scad":
            yield node


def _entity(shape_kind, entity, area=None, length=None, tags=()):
    center = entity.get_center()
    props = {"centroid": [center.x, center.y, center.z]}
    if area is not None:
        props["area"] = area
    if length is not None:
        props["length"] = length
    return {"kind": shape_kind, "properties": props, "geometry": {"type": "plane" if shape_kind == "face" else "line"}, "tags": list(tags)}


def _run(rendered: F.Rendered, scope: dict) -> None:
    """Run the params cell and the feature cell the way the notebook would (in order, one namespace)."""
    if rendered.params:
        exec("\n".join(rendered.params), scope)  # noqa: S102 - the code under test is ours
    exec(rendered.feature, scope)  # noqa: S102


def test_the_catalog_lists_every_operation_with_typed_slots():
    data = F.catalog()
    ids = [spec["id"] for spec in data["specs"]]
    assert len(ids) == len(set(ids)) >= 24
    for spec in data["specs"]:
        assert spec["slots"], spec["id"]
        assert {slot["kind"] for slot in spec["slots"]} <= {"length", "angle", "float", "count", "bool", "enum", "point", "body", "select", "points2d", "points3d"}


@pytest.mark.parametrize("spec", F.SPECS, ids=lambda s: s.id)
def test_every_template_uses_real_sdk_functions_and_parameters(spec):
    """The drift test: an SDK change that breaks a template breaks this, not a user."""
    picks = {slot.name: [{"kind": slot.entity, "properties": {"centroid": [0, 0, 0], "area": 10.0, "length": 5.0}, "geometry": {"type": "plane"}}] for slot in spec.slots if slot.kind == "select"}
    bodies = {"a": "solid", "b": "solid", "many": "solids"}
    values = {k: (v if v is not None else None) for k, v in DEFAULTS[spec.id].items()}
    for slot in spec.slots:
        if slot.kind == "body":
            values[slot.name] = "a"
    rendered = F.render_feature(spec.id, "probe", values, bodies=bodies, selections=picks)
    seen = 0
    for call in _calls(rendered.feature):
        function = getattr(scad, call.func.attr, None)
        assert function is not None, f"{spec.id}: scad.{call.func.attr} does not exist"
        names = set(inspect.signature(function).parameters)
        for keyword in call.keywords:
            assert keyword.arg in names, f"{spec.id}: scad.{call.func.attr} has no parameter {keyword.arg!r}"
        seen += 1
    assert seen, spec.id
    ast.parse("\n".join(rendered.params))
    assert rendered.feature.splitlines()[0] == f"# ---- feature: probe ({spec.role}) ----"
    assert rendered.feature.splitlines()[1].startswith("# gui: ")


def test_the_primitives_and_profiles_make_one_valid_solid_each():
    with scad.GraphSession(graph_id="features-primitives"):
        for spec in F.SPECS:
            if any(slot.kind in ("body", "select") for slot in spec.slots):
                continue
            scope: dict = {"scad": scad}
            rendered = F.render_feature(spec.id, "made", DEFAULTS[spec.id], bodies={})
            _run(rendered, scope)
            made = scope["made"]
            assert made.get_volume() > 0, spec.id


def test_a_chain_of_features_builds_and_the_picked_face_still_resolves_after_a_hole():
    with scad.GraphSession(graph_id="features-chain"):
        scope: dict = {"scad": scad}
        bodies: dict[str, str] = {}

        def add(spec_id, slug, values=None, selections=None):
            rendered = F.render_feature(spec_id, slug, {**DEFAULTS[spec_id], **(values or {})}, bodies=bodies, selections=selections, known_slugs=set(bodies))
            _run(rendered, scope)
            bodies[slug] = rendered.produces
            return rendered

        add("box", "base")
        base = scope["base"]
        top = scad.ql.faces().where(scad.ql.tag("base.top")).exactly(1).resolve(base)[0]
        add("hole", "bore", {"body": "base", "position": [0, 0, 20], "direction": "-z", "diameter": 6.0, "depth": 20.0})
        assert scope["bore"].get_volume() < base.get_volume()
        # the top face was tagged by the box; a feature after the hole selects it through the tag
        picked = _entity("face", top, area=top.get_area(), tags=["base.top"])
        shelled = add("shell", "case", {"body": "bore", "thickness": 2.0}, {"faces": [picked]})
        assert "scad.ql.tag(\"base.top\")" in shelled.feature and "by_geometry" in shelled.feature
        assert scope["case"].get_volume() < scope["bore"].get_volume()


def test_a_fillet_picks_edges_by_geometry_and_counts_them():
    with scad.GraphSession(graph_id="features-fillet"):
        scope: dict = {"scad": scad}
        bodies = {}
        box = F.render_feature("box", "base", DEFAULTS["box"], bodies=bodies)
        _run(box, scope)
        bodies["base"] = "solid"
        base = scope["base"]
        vertical = scad.ql.edges().where(scad.ql.and_(scad.ql.prop("geom.center.z", ">=", 9.0), scad.ql.prop("geom.center.z", "<=", 11.0), scad.ql.prop("geom.length", ">=", 19.0))).resolve(base)
        assert len(vertical) == 4
        items = [_entity("edge", e, length=e.get_length()) for e in vertical[:2]]
        rendered = F.render_feature("fillet", "round", {"body": "base", "radius": 2.0}, bodies=bodies, selections={"edges": items})
        assert ".exactly(2)" in rendered.feature
        _run(rendered, scope)
        assert scope["round"].get_volume() < base.get_volume()
        # the same recipe on a body where the geometry moved selects nothing: an error, not another edge
        scope2 = {"scad": scad, "base": scad.make_box_rsolid(width=10, height=10, depth=10, bottom_face_center=(100, 100, 100))}
        with pytest.raises(Exception):
            exec(rendered.feature, scope2)  # noqa: S102


@pytest.mark.parametrize(
    "spec_id, values, message",
    [
        ("box", {"width": -1.0}, "greater than zero"),
        ("box", {"width": "ten"}, "a number is required"),
        ("box", {"origin": [0, 0]}, "three numbers"),
        ("cylinder", {"axis": "+w"}, "choose one of"),
        ("cut", {"base": "a; import os", "tool": "b"}, "is not a body"),
        ("cut", {"base": "nope", "tool": "b"}, "is not a body"),
        ("linear_pattern", {"shape": "a", "count": 2.5}, "whole number"),
        ("mirror", {"body": "a", "merge": "yes"}, "true or false"),
    ],
)
def test_bad_values_are_refused_with_a_message_and_never_reach_the_source(spec_id, values, message):
    bodies = {"a": "solid", "b": "solid"}
    base = {**DEFAULTS[spec_id], **({"base": "a", "tool": "b"} if spec_id == "cut" else {})}
    with pytest.raises(F.FeatureError, match=message):
        F.render_feature(spec_id, "x", {**base, **values}, bodies=bodies)


def test_names_are_checked_and_made_unique():
    taken = {"base", "BASE", "block"}
    assert F.default_slug("box", taken) == "box"
    assert F.default_slug("extrude_rect", taken) == "block_2"
    with pytest.raises(F.FeatureError):
        F.check_slug("Base", taken)
    with pytest.raises(F.FeatureError, match="already used"):
        F.check_slug("base", taken)
    with pytest.raises(F.FeatureError):
        F.check_slug("a; b", taken)


def test_the_gui_line_round_trips_and_code_cells_are_left_alone():
    rendered = F.render_feature("box", "base", DEFAULTS["box"], bodies={})
    parsed = F.parse_gui(rendered.feature)
    assert parsed and parsed["spec"] == "box" and parsed["values"]["width"] == 40.0
    assert F.parse_gui("# ---- feature: x (build) ----\nx = scad.make_box_rsolid(width=1, height=1, depth=1)") is None
    assert F.parse_gui("# ---- feature: x (build) ----\n# gui: {not json") is None
    assert F.parse_gui('# ---- feature: x (build) ----\n# gui: {"spec": "no_such_op"}') is None


def test_numbers_become_slider_params_and_counts_plain_values():
    rendered = F.render_feature("linear_pattern", "row", {**DEFAULTS["linear_pattern"], "shape": "a"}, bodies={"a": "solid"})
    joined = "\n".join(rendered.params)
    assert "ROW_SPACING = scad.var(name=\"row_spacing\"" in joined and "# ui: slider(" in joined
    assert "ROW_COUNT = 3  # ui: number(2, 500, step=1" in joined
    assert rendered.params[0] == "# ---- params: row ----"


# ---- the commands, against a real kernel ----------------------------------------------------------------------------------


def _wait_idle(state, timeout=120):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        statuses = {c.get("status") for c in state.cells}
        if statuses <= {"idle", "stale", None}:
            return
        time.sleep(0.3)


def test_the_commands_add_edit_undo_and_redo_against_the_real_editor(tmp_path):
    import threading

    import uvicorn

    from simplecadapi.editor.gui_features import GuiError
    from simplecadapi.editor.server import WorkspaceState, create_app
    from simplecadapi.editor.templates import create_notebook

    path = create_notebook(tmp_path, "bracket", "part")
    state = WorkspaceState(tmp_path)
    state.port = 17732
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(__import__("asyncio").new_event_loop())
    try:
        state.start_kernel(path)
        service = state.features
        before = [c["code"] for c in state.cells]
        snap = service.snapshot()
        assert [f["slug"] for f in snap["features"]] == ["base"] and snap["tip"] == "base"
        assert snap["product"]["body"] == "base" and snap["features"][0]["gui"] is None  # the template's cell is code

        # a hole: two cells appear (numbers, then the feature), the product follows the new body
        result = service.add({"spec": "hole", "values": {"position": [0.0, 0.0, 10.0], "direction": "-z", "diameter": 8.0, "depth": 12.0}})
        _wait_idle(state)
        assert result["ok"] and result["name"] == "hole"
        snap = service.snapshot()
        assert [f["slug"] for f in snap["features"]] == ["base", "hole"] and snap["tip"] == "hole"
        assert snap["product"]["body"] == "hole"
        assert snap["features"][1]["gui"]["spec"] == "hole" and snap["features"][1]["params_cell"]
        source = path.read_text()
        assert "# gui: " in source and "HOLE_DIAMETER = scad.var" in source
        assert all(not f["errors"] for f in snap["features"]), snap["features"]

        # editing the diameter rewrites both cells and keeps the name
        service.edit({"cell": snap["features"][1]["cell"], "values": {"diameter": 10.0}})
        _wait_idle(state)
        assert "default=10.0" in path.read_text() and snap["features"][1]["slug"] == "hole"

        # a fillet on the top rim picked by geometry; the count is written into the recipe
        rim = {"kind": "edge", "properties": {"centroid": [0.0, 0.0, 10.0], "length": 2 * 3.141592653589793 * 25.0}, "geometry": {"type": "circle"}}
        service.add({"spec": "fillet", "values": {"radius": 1.0}, "selections": {"edges": [rim]}})
        _wait_idle(state)
        snap = service.snapshot()
        assert snap["tip"] == "fillet" and snap["product"]["body"] == "fillet"
        assert ".exactly(1)" in path.read_text()

        # undo walks back through the three commands, and the file is what it was
        for _ in range(3):
            service.undo()
        _wait_idle(state)
        assert [c["code"] for c in state.cells] == before
        assert service.snapshot()["redo"] == 3
        service.redo()
        _wait_idle(state)
        assert [f["slug"] for f in service.snapshot()["features"]] == ["base", "hole"]

        # an edit made behind the GUI's back wins: undoing over it is refused, not forced
        hole_cell = service.snapshot()["features"][1]["cell"]
        state.cell_command("edit", {"cell": hole_cell, "code": "# ---- feature: hole (subtract) ----\nhole = base", "run": True})
        _wait_idle(state)
        with pytest.raises(GuiError) as refused:
            service.undo()
        assert "changed since" in str(refused.value)
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True


def test_a_blank_notebook_gets_its_product_with_the_first_feature(tmp_path):
    import threading

    import uvicorn

    from simplecadapi.editor.server import WorkspaceState, create_app
    from simplecadapi.editor.templates import create_notebook

    path = create_notebook(tmp_path, "plate", "blank")
    assert "@app.cell" not in path.read_text()
    state = WorkspaceState(tmp_path)
    state.port = 17733
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(__import__("asyncio").new_event_loop())
    try:
        state.start_kernel(path)
        service = state.features
        assert service.snapshot()["features"] == [] and service.snapshot()["product"] is None
        service.add({"spec": "box", "name": "base", "values": {}})
        _wait_idle(state)
        snap = service.snapshot()
        assert [f["slug"] for f in snap["features"]] == ["base"]
        assert snap["product"] == {"cell": snap["product"]["cell"], "body": "base"}
        assert "plate = scad.Part(part_id=scad.notebook_id(), body=base)" in path.read_text()
        service.add({"spec": "cylinder", "values": {"radius": 5.0, "height": 40.0, "origin": [0.0, 0.0, -10.0]}})
        service.add({"spec": "cut", "values": {}})  # base is the second-last open body, the cylinder the last: it is cut out
        _wait_idle(state)
        snap = service.snapshot()
        assert snap["product"]["body"] == "cut" and all(not f["errors"] for f in snap["features"]), snap["features"]
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True
