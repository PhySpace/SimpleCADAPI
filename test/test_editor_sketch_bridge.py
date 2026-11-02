"""The editor holds a sketch as a document; the capabilities are the SDK's. These adapters call the SDK's own operations."""

from __future__ import annotations

import pytest

import simplecadapi as scad
from simplecadapi.editor import sketch_doc as S


def _doc(points, entities, constraints=()):
    return {"plane": "XY", "points": [{"id": k, "x": x, "y": y} for k, (x, y) in points.items()], "entities": entities, "constraints": list(constraints), "profile": 0, "inner": []}


def _line(i, a, b, **kw):
    return {"id": i, "kind": "line", "start": a, "end": b, **kw}


def _plus():
    """A horizontal line crossed by a vertical one at (5, 0)."""
    return _doc({"a": (0, 0), "b": (10, 0), "c": (5, -5), "d": (5, 5)}, [_line("h", "a", "b"), _line("v", "c", "d")], [{"id": "k1", "kind": "horizontal", "targets": ["h"]}])


def test_a_document_round_trips_through_the_sdk_sketch():
    doc = S.validate(_plus())
    again = S.from_sketch(S.to_sketch(doc), doc)
    assert {p["id"] for p in again["points"]} == {p["id"] for p in doc["points"]}
    assert {e["id"] for e in again["entities"]} == {"h", "v"}
    assert [c["kind"] for c in again["constraints"]] == ["horizontal"]


def test_trim_is_the_sdk_operation_and_the_adapter_only_translates():
    answer = S.apply_edit(_plus(), "trim", {"entity": "h", "at": [8.0, 0.0]})
    # the same call in code, on the sketch the document builds, gives the same sketch
    sketch = S.to_sketch(_plus())
    direct = scad.trim_rsketch(sketch=sketch, entity="h", at=(8.0, 0.0))
    assert S.from_sketch(direct, S.validate(_plus())) == answer["sketch"]
    assert answer["created"] and "h" in answer["removed"] and any(c["kind"] == "point_on" for c in answer["sketch"]["constraints"])
    assert answer["removed_constraints"] and S.solve(answer["sketch"])["status"] in ("solved", "underconstrained")


def test_extend_moves_the_end_through_the_sdk():
    doc = _doc({"a": (0, 0), "b": (3, 0), "c": (8, -4), "d": (8, 4)}, [_line("h", "a", "b"), _line("wall", "c", "d")])
    answer = S.apply_edit(doc, "extend", {"entity": "h", "end": "end"})
    moved = next(p for p in answer["sketch"]["points"] if p["id"] == "b")
    assert moved["x"] == pytest.approx(8.0)


def test_only_sdk_edit_operations_are_reachable_and_their_errors_come_through():
    with pytest.raises(S.SketchError, match="unknown sketch operation"):
        S.apply_edit(_plus(), "explode", {})
    with pytest.raises(S.SketchError, match="no entity 'zz'"):
        S.apply_edit(_plus(), "trim", {"entity": "zz", "at": [0.0, 0.0]})
    with pytest.raises(S.SketchError, match="nothing is ahead"):
        S.apply_edit(_plus(), "extend", {"entity": "h", "end": "end"})


def test_an_agent_trims_a_sketch_feature_from_the_command_line(tmp_path, monkeypatch):
    """`sca feature` and `sca sketch` against a real editor: the same document, the same SDK operation as the canvas and as code."""
    import argparse
    import json
    import threading

    import uvicorn

    from simplecadapi.editor import cli
    from simplecadapi.editor.server import WorkspaceState, create_app
    from simplecadapi.editor.templates import create_notebook
    from test_editor_features import _wait_idle

    path = create_notebook(tmp_path, "cross", "blank")
    state = WorkspaceState(tmp_path)
    state.port = 17737
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(__import__("asyncio").new_event_loop())
    monkeypatch.setattr(cli, "_editor_url", lambda args: f"http://127.0.0.1:{state.port}")
    ns = lambda **kw: argparse.Namespace(workspace=None, notebook=None, **kw)  # noqa: E731
    try:
        state.start_kernel(path)
        doc = _plus() | {"fully_constrained": False}
        added, code = cli._feature_add(ns(spec="sketch", name="cross", values=json.dumps({"sketch": doc}), selections=None, after=None))
        assert code == 0 and added["ok"]
        _wait_idle(state)
        listing, _ = cli._sketch_ls(ns())
        assert [s["slug"] for s in listing["sketches"]] == ["cross"]
        dry, code = cli._sketch_op(ns(cell="cross", operation="trim", args='{"entity": "h", "at": [8, 0]}', dry_run=True))
        assert code == 0 and "h" in dry["removed"]
        written, code = cli._sketch_op(ns(cell="cross", operation="trim", args='{"entity": "h", "at": [8, 0]}', dry_run=False))
        assert code == 0 and written["written"] is True
        _wait_idle(state)
        got, _ = cli._sketch_get(ns(cell="cross"))
        assert "h" not in {e["id"] for e in got["sketch"]["entities"]} and "v" in {e["id"] for e in got["sketch"]["entities"]}
        refused, code = cli._sketch_op(ns(cell="cross", operation="trim", args='{"entity": "nope", "at": [0, 0]}', dry_run=False))
        assert code == 1 and "no entity 'nope'" in refused["error"]
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True


def _corner():
    return _doc({"a": (0, 0), "b": (10, 0), "c": (10, 10)}, [_line("l0", "a", "b"), _line("l1", "b", "c")])


def test_fillet_and_chamfer_corner_are_sdk_operations_reached_through_the_document():
    filleted = S.apply_edit(_corner(), "fillet_corner", {"a": "l0", "b": "l1", "radius": 2.0})
    assert any(e["kind"] == "arc" for e in filleted["sketch"]["entities"]) and filleted["created"]
    chamfered = S.apply_edit(_corner(), "chamfer_corner", {"a": "l0", "b": "l1", "distance": 2.0})
    assert not any(e["kind"] == "arc" for e in chamfered["sketch"]["entities"]) and len(chamfered["sketch"]["entities"]) == 3
    with pytest.raises(S.SketchError):
        S.apply_edit(_corner(), "fillet_corner", {"a": "l0", "b": "l1", "radius": 50.0})


def test_project_brings_another_sketchs_geometry_in_as_fixed_reference():
    source = _doc({"s": (2, 3), "t": (8, 3)}, [_line("edge", "s", "t")])
    target = _doc({"o": (0, 0)}, [])
    answer = S.apply_edit(target, "project", {"source_doc": source})
    projected = [e for e in answer["sketch"]["entities"] if e["id"].startswith("proj_")]
    assert projected and all(e["construction"] for e in projected)
    assert any(c["kind"] == "fix" for c in answer["sketch"]["constraints"])
