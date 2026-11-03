"""GUI-made features: every operation renders a cell that runs, uses only the SDK's real parameters, and cannot carry code."""

from __future__ import annotations

import ast
import inspect

import pytest

import simplecadapi as scad
from simplecadapi.editor import features as F

RECT_SKETCH = {
    "plane": "XY",
    "points": [{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 41, "y": 1}, {"id": "c", "x": 40, "y": 21}, {"id": "d", "x": 1, "y": 19}],
    "entities": [{"id": "l0", "kind": "line", "start": "a", "end": "b"}, {"id": "l1", "kind": "line", "start": "b", "end": "c"},
                 {"id": "l2", "kind": "line", "start": "c", "end": "d"}, {"id": "l3", "kind": "line", "start": "d", "end": "a"}],
    "constraints": [{"kind": "fix", "targets": ["a"]}, {"kind": "horizontal", "targets": ["l0"]}, {"kind": "vertical", "targets": ["l1"]},
                    {"kind": "horizontal", "targets": ["l2"]}, {"kind": "vertical", "targets": ["l3"]},
                    {"kind": "length", "targets": ["l0"], "value": 40.0}, {"kind": "length", "targets": ["l1"], "value": 20.0}],
    "profile": 0, "inner": [], "fully_constrained": True,
}
HOLE_SKETCH = {
    "plane": "XY",
    "points": [{"id": "o", "x": 20, "y": 10}],
    "entities": [{"id": "ring", "kind": "circle", "center": "o", "radius": 4.0}],
    "constraints": [{"kind": "fix", "targets": ["o"]}, {"kind": "radius", "targets": ["ring"], "value": 4.0}],
    "profile": 0, "inner": [], "fully_constrained": True,
}
DEFAULTS = {spec.id: {slot.name: slot.default for slot in spec.slots if slot.kind not in ("select", "profile")} for spec in F.SPECS}


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
        assert {slot["kind"] for slot in spec["slots"]} <= {"length", "angle", "float", "count", "bool", "enum", "point", "body", "select", "points2d", "points3d", "profile", "sketch", "assembly"}


@pytest.mark.parametrize("spec", F.SPECS, ids=lambda s: s.id)
def test_every_template_uses_real_sdk_functions_and_parameters(spec):
    """The drift test: an SDK change that breaks a template breaks this, not a user."""
    picks = {slot.name: [{"kind": slot.entity, "properties": {"centroid": [0, 0, 0], "area": 10.0, "length": 5.0}, "geometry": {"type": "plane"}}] for slot in spec.slots if slot.kind == "select"}
    bodies = {"a": "solid", "b": "solid", "many": "solids", "prof": "face"}
    values = {k: (v if v is not None else None) for k, v in DEFAULTS[spec.id].items()}
    for slot in spec.slots:
        if slot.kind == "body":
            values[slot.name] = "a"
        elif slot.kind == "profile":
            values[slot.name] = "prof"
        elif slot.kind == "sketch":
            values[slot.name] = RECT_SKETCH
    rendered = F.render_feature(spec.id, "probe", values, bodies=bodies, selections=picks, env={"profile_normals": {"prof": (0.0, 0.0, 1.0)}})
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
            if spec.produces in ("face", "assembly") or any(slot.kind in ("body", "select", "profile") for slot in spec.slots):
                continue  # sketches and assemblies have their own tests
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
        if statuses <= {"idle", "stale", "exception", "error", None}:
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
        # the header says kind = "part": the runtime makes the Part from the open body, no product cell is written
        assert snap["product"] == {"cell": None, "body": "base", "implicit": True}
        assert "make_part_rpart" not in path.read_text()
        # a part holds one solid: the new cylinder says how it meets the body, so no second body is left behind
        assert service.snapshot()["defaults"]["cylinder"]["operation"] == "join"
        service.add({"spec": "cylinder", "name": "bore", "values": {"radius": 5.0, "height": 40.0, "origin": [0.0, 0.0, -10.0], "operation": "cut"}})
        _wait_idle(state)
        snap = service.snapshot()
        assert snap["open"] == ["bore"] and snap["product"]["body"] == "bore", snap
        assert all(not f["errors"] for f in snap["features"]), snap["features"]
        assert next(f for f in snap["features"] if f["slug"] == "bore")["role"] == "subtract"
        assert "_tool = scad.make_cylinder_rsolid(" in path.read_text() and "bore = scad.cut_rsolid(base, _tool" in path.read_text()
        from simplecadapi.runtime import run_notebook

        product = run_notebook(path, cache=False).product  # the same notebook headless: its Part is the open body
        assert product.part_id == "plate" and product.body.get_volume() < 40 * 30 * 20
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True


def test_a_sketch_becomes_a_face_and_the_sketch_features_build_on_it():
    with scad.GraphSession(graph_id="features-sketch"):
        scope: dict = {"scad": scad}
        bodies: dict[str, str] = {}

        def add(spec_id, slug, values):
            rendered = F.render_feature(spec_id, slug, values, bodies=bodies)
            _run(rendered, scope)
            bodies[slug] = rendered.produces
            return rendered

        outline = add("sketch", "outline", {"sketch": RECT_SKETCH})
        assert outline.produces == "face" and "OUTLINE_LENGTH_L0" in "\n".join(outline.params)
        assert outline.feature.splitlines()[0] == "# ---- feature: outline (build, profile=sketch) ----"
        plate = add("extrude_sketch", "plate", {"profile": "outline", "direction": "+z", "distance": 6.0})
        assert abs(scope["plate"].get_volume() - 40 * 20 * 6) < 1e-6 and plate.reads == ["outline"]
        add("sketch", "bore", {"sketch": HOLE_SKETCH})
        add("cut_sketch", "drilled", {"body": "plate", "profile": "bore", "direction": "+z", "depth": 6.0})
        assert scope["drilled"].get_volume() < scope["plate"].get_volume()
        add("boss_sketch", "stud", {"body": "drilled", "profile": "bore", "direction": "+z", "distance": 3.0})
        assert scope["stud"].get_volume() > scope["drilled"].get_volume()
        add("revolve_sketch", "ring", {"profile": "outline", "axis": "+y", "origin": [0.0, 0.0, 0.0], "angle": 90.0})
        assert scope["ring"].get_volume() > 0
        # a sketch face is not a body, and a body is not a profile
        with pytest.raises(F.FeatureError, match="not a sketch profile"):
            F.render_feature("extrude_sketch", "bad", {"profile": "plate", "direction": "+z", "distance": 1.0}, bodies=bodies)
        with pytest.raises(F.FeatureError, match="not a body"):
            F.render_feature("fillet", "bad", {"body": "outline", "radius": 1.0}, bodies=bodies, selections={"edges": [{"kind": "edge", "properties": {"centroid": [0, 0, 0], "length": 1.0}, "geometry": {"type": "line"}}]})


def test_a_sketch_feature_added_through_the_editor_is_extruded_into_the_product(tmp_path):
    import threading

    import uvicorn

    from simplecadapi.editor.server import WorkspaceState, create_app
    from simplecadapi.editor.templates import create_notebook

    path = create_notebook(tmp_path, "tab", "blank")
    state = WorkspaceState(tmp_path)
    state.port = 17734
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(__import__("asyncio").new_event_loop())
    try:
        state.start_kernel(path)
        service = state.features
        service.add({"spec": "sketch", "name": "outline", "values": {"sketch": RECT_SKETCH}})
        _wait_idle(state)
        snap = service.snapshot()
        assert snap["profiles"] == [{"name": "outline", "plane": "XY", "plane_label": "XY", "normal": "+z", "normal_vec": [0, 0, 1]}]
        assert snap["tip"] is None and snap["product"] is None  # a face is not a body: no product yet
        assert snap["defaults"]["extrude_sketch"] == {"profile": "outline", "operation": "new"}
        service.add({"spec": "extrude_sketch", "name": "tab_body", "values": {"direction": "+z", "distance": 5.0}})
        _wait_idle(state)
        snap = service.snapshot()
        assert snap["tip"] == "tab_body" and snap["product"]["body"] == "tab_body"
        assert all(not f["errors"] for f in snap["features"]), snap["features"]
        text = path.read_text()
        assert "scad.make_face_from_sketch_rface" in text and "TAB_BODY_DISTANCE" in text.upper() and "OUTLINE_LENGTH_L0" in text
        # a dimension is a slider variable: editing the sketch document keeps the name and rewrites the numbers
        outline = next(f for f in snap["features"] if f["slug"] == "outline")
        longer = {**RECT_SKETCH, "constraints": [dict(c, value=60.0) if c.get("targets") == ["l0"] and c["kind"] == "length" else c for c in RECT_SKETCH["constraints"]]}
        service.edit({"cell": outline["cell"], "values": {"sketch": longer}})
        _wait_idle(state)
        assert "default=60.0" in path.read_text()
        # the face must be picked from a sketch that exists
        undo_count = service.snapshot()["undo"]
        assert undo_count >= 3
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True


def test_a_name_that_is_taken_is_a_message_not_a_server_error(tmp_path):
    import threading

    import uvicorn

    from simplecadapi.editor.gui_features import GuiError
    from simplecadapi.editor.server import WorkspaceState, create_app
    from simplecadapi.editor.templates import create_notebook

    path = create_notebook(tmp_path, "dup", "blank")
    state = WorkspaceState(tmp_path)
    state.port = 17739
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(__import__("asyncio").new_event_loop())
    try:
        state.start_kernel(path)
        state.features.add({"spec": "box", "name": "base", "values": {}})
        _wait_idle(state)
        with pytest.raises(GuiError, match="already used"):
            state.features.add({"spec": "box", "name": "base", "values": {}})
        import json
        import urllib.error
        import urllib.request

        request = urllib.request.Request(f"http://127.0.0.1:{state.port}/api/features", data=json.dumps({"op": "add", "spec": "box", "name": "base"}).encode(), method="POST")
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request)
        assert refused.value.code == 400 and "already used" in json.loads(refused.value.read())["error"]
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True


def test_a_new_solid_is_joined_cut_or_intersected_at_once_and_never_left_beside_the_body():
    with scad.GraphSession(graph_id="features-combine"):
        scope: dict = {"scad": scad}
        bodies: dict[str, str] = {}

        def add(spec_id, slug, values):
            rendered = F.render_feature(spec_id, slug, values, bodies=bodies)
            _run(rendered, scope)
            bodies[slug] = rendered.produces
            return rendered

        base = add("box", "base", {**DEFAULTS["box"], "operation": "new"})
        assert base.feature.splitlines()[0] == "# ---- feature: base (build) ----"
        volume = scope["base"].get_volume()
        pin = add("cylinder", "pin", {**DEFAULTS["cylinder"], "operation": "join", "target": "base", "origin": [0.0, 0.0, 20.0]})
        assert pin.feature.splitlines()[0] == "# ---- feature: pin (add) ----" and "_tool = scad.make_cylinder_rsolid(" in pin.feature
        assert scope["pin"].get_volume() > volume and pin.reads == ["base"]
        hole = add("cylinder", "bore", {**DEFAULTS["cylinder"], "operation": "cut", "target": "pin", "radius": 3.0, "origin": [0.0, 0.0, -5.0], "height": 60.0})
        assert hole.feature.splitlines()[0] == "# ---- feature: bore (subtract) ----" and scope["bore"].get_volume() < scope["pin"].get_volume()
        common = add("box", "core", {**DEFAULTS["box"], "operation": "intersect", "target": "bore", "origin": [0.0, 0.0, 0.0]})
        assert common.feature.splitlines()[0] == "# ---- feature: core (intersect) ----"
        # the tags a primitive gives its faces are on the tool, and survive the boolean
        assert scad.ql.faces().where(scad.ql.tag("pin.end")).exactly(1).resolve(scope["pin"])
    with pytest.raises(F.FeatureError, match="no body to combine with"):
        F.render_feature("box", "x", {**DEFAULTS["box"], "operation": "join"}, bodies={})
    with pytest.raises(F.FeatureError, match="choose one of"):
        F.render_feature("box", "x", {**DEFAULTS["box"], "operation": "merge"}, bodies={})


def test_the_catalog_says_which_slots_belong_to_which_operation():
    spec = next(s for s in F.catalog()["specs"] if s["id"] == "extrude_sketch")
    assert spec.get("combinable") is True
    by_name = {slot["name"]: slot for slot in spec["slots"]}
    assert [o["value"] for o in by_name["operation"]["options"]] == ["join", "cut", "intersect", "new"]
    assert by_name["target"]["show_when"] == {"operation": ["join", "cut", "intersect"]}
    assert not any(s.get("combinable") for s in F.catalog()["specs"] if s["id"] in ("fillet", "hole", "cut", "union"))


def test_a_hole_goes_along_an_axis_a_face_normal_or_a_free_vector():
    base = {**DEFAULTS["hole"], "body": "block", "position": [10.0, 10.0, 20.0]}
    axis = F.render_feature("hole", "bore", {**base, "direction": "-z"}, bodies={"block": "solid"}, known_slugs={"block"})
    assert "(0.0, 0.0, -1.0)" in axis.feature or "(0, 0, -1)" in axis.feature
    slanted = F.render_feature("hole", "bore", {**base, "direction": "face", "dx": 3.0, "dy": 0.0, "dz": -4.0}, bodies={"block": "solid"}, known_slugs={"block"})
    assert "(0.6, 0.0, -0.8)" in slanted.feature  # the unit vector, whatever the length typed or picked
    free = F.render_feature("hole", "bore", {**base, "direction": "vector", "dx": 0.0, "dy": 1.0, "dz": 0.0}, bodies={"block": "solid"}, known_slugs={"block"})
    assert "(0.0, 1.0, 0.0)" in free.feature
    with pytest.raises(F.FeatureError, match="must not be zero"):
        F.render_feature("hole", "bore", {**base, "direction": "vector", "dx": 0.0, "dy": 0.0, "dz": 0.0}, bodies={"block": "solid"}, known_slugs={"block"})


def test_a_picked_face_is_pushed_out_or_in_along_its_normal_without_a_sketch():
    with scad.GraphSession(graph_id="features-extrude-face"):
        scope: dict = {"scad": scad}
        base = F.render_feature("box", "base", DEFAULTS["box"], bodies={})
        _run(base, scope)
        top = scad.ql.faces().where(scad.ql.tag("base.top")).exactly(1).resolve(scope["base"])[0]
        picked = _entity("face", top, area=top.get_area(), tags=["base.top"])
        volume = scope["base"].get_volume()
        area = top.get_area()
        pad = F.render_feature("extrude_face", "pad", {**DEFAULTS["extrude_face"], "body": "base", "distance": 5.0, "operation": "join", "target": "base"},
                               bodies={"base": "solid"}, selections={"face": [picked]}, known_slugs={"base"})
        _run(pad, scope)
        assert scope["pad"].get_volume() == pytest.approx(volume + 5.0 * area, rel=1e-6)
        pocket = F.render_feature("extrude_face", "pocket", {**DEFAULTS["extrude_face"], "body": "base", "direction": "-normal", "distance": 4.0, "operation": "cut", "target": "base"},
                                  bodies={"base": "solid"}, selections={"face": [picked]}, known_slugs={"base"})
        _run(pocket, scope)
        assert scope["pocket"].get_volume() == pytest.approx(volume - 4.0 * area, rel=1e-6)
        with pytest.raises(F.FeatureError, match="exactly one"):
            F.render_feature("extrude_face", "two", {**DEFAULTS["extrude_face"], "body": "base"}, bodies={"base": "solid"}, selections={"face": [picked, picked]}, known_slugs={"base"})
