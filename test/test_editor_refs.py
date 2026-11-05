"""GUI-made selections are stable references in the code (``scad.ref``), read back by the editor, repaired in place.

The editor never computes geometry: the server has the kernel name each picked entity (``runtime/live_refs.py``), the
feature cell gets one ``_<slot> = scad.ref.<kinds>(...)`` statement, and a reference that splits or is lost shows its
status and candidates; choosing one rewrites the literal (``piece=``, or a new reference at the look-alike).
"""

from __future__ import annotations

import pytest

import simplecadapi as scad
from simplecadapi.editor import features as F

DEFAULTS = {spec.id: {slot.name: slot.default for slot in spec.slots if slot.kind not in ("select", "profile")} for spec in F.SPECS}


def _run(rendered: F.Rendered, scope: dict) -> None:
    if rendered.params:
        exec("\n".join(rendered.params), scope)  # noqa: S102 - the code under test is ours
    exec(rendered.feature, scope)  # noqa: S102


def _picks(refs):
    return [{"kind": r.kind, "entity_id": f"entity/x/{r.kind}/{i}", "ref": r.to_dict()} for i, r in enumerate(refs)]


def test_picked_references_render_as_one_statement_that_reads_back_and_runs():
    with scad.GraphSession(namespace="base"):
        scope: dict = {"scad": scad}
        base = F.render_feature("box", "base", DEFAULTS["box"], bodies={})
        _run(base, scope)
        rims = [r for r in (scad.ref.of(e, scope["base"]) for e in scad.ql.edges().resolve(scope["base"])) if "box.top" in r.between]
        assert len(rims) == 4
        rendered = F.render_feature("fillet", "round", {"body": "base", "radius": 2.0}, bodies={"base": "solid"}, selections={"edges": _picks(rims[:2])})
        statement = F.extract_recipe(rendered.feature, "edges")
        assert statement[0] == "_edges = scad.ref.edges(" and all(line.strip().startswith(("scad.ref.edge(", ")")) for line in statement[1:])
        assert "by_geometry" not in rendered.feature and "exactly(" not in rendered.feature
        # render -> code -> parse -> the same references; an edit that keeps the pick writes the same cell
        assert F.extract_refs(rendered.feature, "edges") == rims[:2]
        again = F.render_feature("fillet", "round", {"body": "base", "radius": 2.0}, bodies={"base": "solid"}, keep_recipes={"edges": statement})
        assert again.feature.splitlines()[2:] == rendered.feature.splitlines()[2:]  # (the # gui: line keeps no pick count)
        _run(rendered, scope)
        assert scope["round"].get_volume() < scope["base"].get_volume()
        # one pick, one line
        one = F.render_feature("shell", "cup", {"body": "base", "thickness": 1.0}, bodies={"base": "solid"},
                               selections={"faces": _picks([scad.ref.face("base", "make_box_rsolid", role="box.top")])})
        assert "_faces = scad.ref.faces(scad.ref.face('base', 'make_box_rsolid', role='box.top'))" in one.feature.splitlines()
        _run(one, scope)
        assert scope["cup"].get_volume() < scope["base"].get_volume()


def test_a_repair_rewrites_only_the_literal():
    top = scad.ref.face("base", "make_box_rsolid", role="box.top")
    rendered = F.render_feature("shell", "cup", {"body": "base", "thickness": 1.0}, bodies={"base": "solid"}, selections={"faces": _picks([top])})
    fixed = F.replace_refs(rendered.feature, "faces", [scad.ref.face("base", "make_box_rsolid", role="box.top", piece=1)])
    assert fixed.splitlines()[:2] == rendered.feature.splitlines()[:2]
    assert "role='box.top', piece=1))" in fixed
    assert F.extract_refs(fixed, "faces")[0].piece == 1
    assert F.extract_refs(rendered.feature, "nothing") is None
    with pytest.raises(F.FeatureError):
        F.replace_refs(rendered.feature, "nothing", [top])


def test_a_reference_of_the_wrong_kind_or_shape_is_refused_and_an_unnamed_pick_keeps_the_older_recipe():
    edge = scad.ref.edge("base", "make_box_rsolid", between=("box.top", "box.front"))
    with pytest.raises(F.FeatureError, match="a edge reference where a face is picked"):
        F.render_feature("shell", "cup", {"body": "base", "thickness": 1.0}, bodies={"base": "solid"},
                         selections={"faces": [{"kind": "face", "ref": edge.to_dict()}]})
    with pytest.raises(F.FeatureError):
        F.render_feature("shell", "cup", {"body": "base", "thickness": 1.0}, bodies={"base": "solid"},
                         selections={"faces": [{"kind": "face", "ref": {"kind": "face", "feature": "x", "op": "y", "role": "__import__('os')", "topo": "z"}}]})
    plain = {"kind": "face", "properties": {"centroid": [0, 0, 20], "area": 1200.0}, "geometry": {"type": "plane"}}
    rendered = F.render_feature("shell", "cup", {"body": "base", "thickness": 1.0}, bodies={"base": "solid"}, selections={"faces": [plain]})
    assert ".exactly(1)" in rendered.feature and F.extract_refs(rendered.feature, "faces") is None


# ---- against a real kernel -------------------------------------------------------------------------------------------


def _wait_idle(state, timeout=120):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if {c.get("status") for c in state.cells} <= {"idle", "stale", "exception", "error", None}:
            return
        time.sleep(0.3)


def test_the_server_names_picks_shows_a_split_and_writes_the_chosen_piece(tmp_path):
    import json
    import threading

    import uvicorn

    from simplecadapi.editor.server import WorkspaceState, create_app
    from simplecadapi.editor.templates import create_notebook

    path = create_notebook(tmp_path, "cup", "blank")
    state = WorkspaceState(tmp_path)
    state.port = 17741
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(__import__("asyncio").new_event_loop())
    try:
        state.start_kernel(path)
        service = state.features
        service.add({"spec": "box", "name": "base", "values": {"width": 40.0, "height": 30.0, "depth": 20.0}})
        _wait_idle(state)
        # what the viewport would send: the entity id of the top face in the scene the kernel previews
        found = state.kernel.execute(
            "from simplecadapi.runtime import live as _live\n"
            "_s = _live._live_scene()\n"
            "for _k, _solid in _s.solids.items():\n"
            "    for _f in _solid._iter_faces():\n"
            "        if abs(_f.get_center().z - 20.0) < 1e-6:\n"
            "            print('SCA-PICK', f'entity/{_s.definitions[_k]}/face/{_f.topo_id}')\n"
        )
        (entity_id,) = [line.split(" ", 1)[1] for line in found["log"].splitlines() if line.startswith("SCA-PICK ")]
        service.add({"spec": "shell", "name": "cup", "values": {"body": "base", "thickness": 2.0}, "selections": {"faces": [{"kind": "face", "entity_id": entity_id}]}})
        _wait_idle(state)
        source = path.read_text()
        assert "_faces = scad.ref.faces(scad.ref.face('base', 'make_box_rsolid', role='box.top', guard=('PLANE', (0, 0, 20), 1200, (0, 0, 1))))" in source
        cup = next(f for f in service.snapshot()["features"] if f["slug"] == "cup")
        assert not cup["errors"], cup["errors"]
        assert service.ref_status({"cell": cup["cell"]})["badge"] == "ok"

        # a groove across the top, and the shell moved onto it: the top is now two pieces -> amber, with both pieces
        service.add({"spec": "box", "name": "groove", "values": {"width": 4.0, "height": 40.0, "depth": 6.0, "origin": [0.0, 0.0, 16.0], "operation": "cut", "target": "base"}})
        _wait_idle(state)
        service.edit({"cell": cup["cell"], "values": {"body": "groove"}})
        _wait_idle(state)
        report = service.ref_status({"cell": cup["cell"]})
        assert report["badge"] == "split" and report["body"] == "groove", report
        (row,) = report["slots"]["faces"]
        assert row["status"] == "split" and [round(c["center"][0], 3) for c in row["candidates"]] == [-11.0, 11.0]
        json.dumps(report)  # plain data for the page
        cup = next(f for f in service.snapshot()["features"] if f["slug"] == "cup")
        assert cup["errors"]  # the feature fails with the reference error, never on another face

        service.ref_repair({"cell": cup["cell"], "slot": "faces", "index": 0, "choice": 1})
        _wait_idle(state)
        assert "role='box.top', piece=1, guard=" in path.read_text()
        assert service.ref_status({"cell": cup["cell"]})["badge"] == "ok"
        cup = next(f for f in service.snapshot()["features"] if f["slug"] == "cup")
        assert not cup["errors"], cup["errors"]
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True


def test_an_edit_keeps_the_references_it_is_given_and_adds_what_is_picked_on_the_result(tmp_path):
    """The shell session: faces picked on the shelled body are named on the body before it and join the openings; the
    ones the feature holds come back as references (a face it opened is not drawn any more), so one can be taken out."""
    import threading

    import uvicorn

    from simplecadapi.editor.server import WorkspaceState, create_app
    from simplecadapi.editor.templates import create_notebook

    path = create_notebook(tmp_path, "cup", "blank")
    state = WorkspaceState(tmp_path)
    state.port = 17742
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(__import__("asyncio").new_event_loop())

    def pick(axis: int, at: float) -> str:
        found = state.kernel.execute(
            "from simplecadapi.runtime import live as _live\n"
            "_s = _live._live_scene()\n"
            "for _k, _solid in _s.solids.items():\n"
            "    for _f in _solid._iter_faces():\n"
            f"        if abs(_f.get_center().{'xyz'[axis]} - {at}) < 1e-6:\n"
            "            print('SCA-PICK', f'entity/{_s.definitions[_k]}/face/{_f.topo_id}')\n"
        )
        (entity_id,) = [line.split(" ", 1)[1] for line in found["log"].splitlines() if line.startswith("SCA-PICK ")]
        return entity_id

    def cup() -> dict:
        return next(f for f in state.features.snapshot()["features"] if f["slug"] == "cup")

    try:
        state.start_kernel(path)
        service = state.features
        service.add({"spec": "box", "name": "base", "values": {"width": 40.0, "height": 30.0, "depth": 20.0}})
        _wait_idle(state)
        service.add({"spec": "shell", "name": "cup", "values": {"body": "base"}, "selections": {"faces": [{"kind": "face", "entity_id": pick(2, 20.0)}]}})
        _wait_idle(state)
        (top,) = cup()["gui"]["refs"]["faces"]
        assert top["role"] == "box.top" and not cup()["errors"]
        assert cup()["gui"]["values"]["thickness"] == 1.0  # a thin wall to start from

        # a side picked on the cup itself joins the openings; picking it again changes nothing
        side = pick(0, 20.0)
        kept = {"kind": "face", "ref": top}
        service.edit({"cell": cup()["cell"], "selections": {"faces": [kept, {"kind": "face", "entity_id": side}]}})
        _wait_idle(state)
        refs = cup()["gui"]["refs"]["faces"]
        assert [r["role"] for r in refs] == ["box.top", "box.front"] and not cup()["errors"], (refs, cup()["errors"])
        again = [{"kind": "face", "ref": r} for r in refs] + [{"kind": "face", "ref": refs[1]}]
        service.edit({"cell": cup()["cell"], "selections": {"faces": again}})
        _wait_idle(state)
        assert len(cup()["gui"]["refs"]["faces"]) == 2

        # the top taken out again: only the side is open
        service.edit({"cell": cup()["cell"], "selections": {"faces": [{"kind": "face", "ref": refs[1]}]}})
        _wait_idle(state)
        assert [r["role"] for r in cup()["gui"]["refs"]["faces"]] == ["box.front"] and not cup()["errors"]
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True
