"""The assembly document: validation, the three cells it renders, and the GUI feature against a real editor."""

from __future__ import annotations

import copy
import threading

import pytest

from simplecadapi.editor import assembly_doc as A
from simplecadapi.editor.templates import _HEADER, _RUNNER

PART = """

@app.cell
def _():
    body = scad.make_box_rsolid(width=20.0, height=20.0, depth=10.0, bottom_face_center=(0.0, 0.0, 0.0))
    part = scad.make_part_rpart(part_id=scad.notebook_id(), body=body, name="{name}")
    part = scad.add_connector_rpart(part=part, connector=scad.make_placement_connector_rconnector(
        connector_id="top", placement=scad.make_placement_rplacement(origin=(0.0, 0.0, 10.0))))
    part = scad.add_connector_rpart(part=part, connector=scad.make_placement_connector_rconnector(
        connector_id="root", placement=scad.make_placement_rplacement(origin=(0.0, 0.0, 0.0))))
    return (part,)
"""

DOC = {
    "components": [
        {"id": "base", "part": "base.py", "origin": [0, 0, 0], "x_axis": "+x", "y_axis": "+y"},
        {"id": "arm", "part": "arm.py", "origin": [0, 0, 10], "x_axis": "+x", "y_axis": "+y"},
    ],
    "ground": "base",
    "constraints": [
        {"id": "j1", "kind": "revolute", "a": {"component": "base", "connector": "top"}, "b": {"component": "arm", "connector": "root"}, "drive": 30.0, "limit": [-90, 90]}
    ],
}


def _write_part(root, name):
    path = root / f"{name}.py"
    path.write_text(_HEADER.format(id=name) + PART.format(name=name) + _RUNNER, encoding="utf-8")
    return path


def test_the_document_renders_params_uses_and_a_layout_that_solves():
    clean = A.validate(DOC)
    cells = A.render("rig", "rig", clean)
    assert cells["uses"] == ['base_part = scad.use("base.py")', 'arm_part = scad.use("arm.py")']
    assert any(line.startswith("RIG_J1_DRIVE = scad.var(") and "unit=\"deg\"" in line for line in cells["params"])
    layout = "\n".join(cells["layout"])
    assert "scad.ground_component_rassembly(assembly=_assembly, component_id=\"base\")" in layout
    assert "drive_angle_degrees=RIG_J1_DRIVE" in layout and "angle_limit=scad.make_scalar_limit_rscalarlimit(lower_value=-90.0, upper_value=90.0)" in layout
    assert cells["layout"][-1] == "rig = scad.solve_assembly_constraints_rassembly(assembly=_assembly)"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["components"][0].update(id="Base"), "lowercase"),
        (lambda d: d["components"][1].update(id="base"), "used twice"),
        (lambda d: d["components"][0].update(part="../x.py"), "not a notebook path"),
        (lambda d: d["components"][0].update(part="x.py; import os"), "not a notebook path"),
        (lambda d: d["components"][0].update(x_axis="+x", y_axis="-x"), "same line"),
        (lambda d: d.update(ground="ghost"), "not in the assembly"),
        (lambda d: d.update(ground=None), "need a grounded component"),
        (lambda d: d["constraints"][0].update(kind="weld"), "unknown constraint"),
        (lambda d: d["constraints"][0]["b"].update(component="base"), "two different components"),
        (lambda d: d["constraints"][0].update(limit=[10, 5]), "lower limit"),
        (lambda d: d["constraints"][0]["a"].update(connector="top; x"), "not a connector name"),
    ],
)
def test_a_bad_document_is_refused_before_it_reaches_code(mutate, message):
    doc = copy.deepcopy(DOC)
    mutate(doc)
    with pytest.raises(A.AssemblyError, match=message):
        A.validate(doc)


def test_the_assembly_feature_is_added_edited_undone_and_deleted_in_a_real_editor(tmp_path):
    import uvicorn

    from simplecadapi.editor.gui_features import GuiError
    from simplecadapi.editor.server import WorkspaceState, create_app
    from simplecadapi.editor.templates import create_notebook
    from test_editor_features import _wait_idle

    _write_part(tmp_path, "base")
    _write_part(tmp_path, "arm")
    assert {c["id"] for c in A.connectors_of(tmp_path / "base.py")} == {"top", "root"}
    path = create_notebook(tmp_path, "rig", "blank")
    state = WorkspaceState(tmp_path)
    state.port = 17735
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(__import__("asyncio").new_event_loop())
    try:
        state.start_kernel(path)
        service = state.features
        with pytest.raises(GuiError, match="not in the workspace"):
            bad = copy.deepcopy(DOC)
            bad["components"][0]["part"] = "nowhere.py"
            service.add({"spec": "assembly", "name": "rig", "values": {"assembly": bad}})
        before = [c["code"] for c in state.cells]
        service.add({"spec": "assembly", "name": "rig", "values": {"assembly": DOC}})
        _wait_idle(state)
        snap = service.snapshot()
        slugs = [f["slug"] for f in snap["features"]]
        assert slugs == ["rig_parts", "rig"], slugs
        assert snap["features"][0]["part_of"] == "rig" and snap["assembly"]["slug"] == "rig"
        assert snap["tip"] is None and snap["bodies"] == [{"name": "rig", "produces": "assembly"}]
        assert all(not f["errors"] for f in snap["features"]), snap["features"]
        text = path.read_text()
        assert "RIG_J1_DRIVE" in text and "rig = scad.solve_assembly_constraints_rassembly" in text and "# gui: " in text

        # a joint angle edit rewrites the params cell, not the structure
        doc = copy.deepcopy(DOC)
        doc["constraints"][0]["drive"] = 45.0
        service.edit({"cell": snap["assembly"]["cell"], "values": {"assembly": doc}})
        _wait_idle(state)
        assert "default=45.0" in path.read_text()

        # an unreachable part (no connector of that name) shows as an error on the feature, it does not take the editor down
        broken = copy.deepcopy(DOC)
        broken["constraints"][0]["b"]["connector"] = "nope"
        service.edit({"cell": snap["assembly"]["cell"], "values": {"assembly": broken}})
        _wait_idle(state)
        assert any(f["errors"] for f in service.snapshot()["features"])

        service.delete({"cell": snap["assembly"]["cell"]})
        _wait_idle(state)
        assert service.snapshot()["features"] == []
        for _ in range(4):
            service.undo()
        _wait_idle(state)
        assert [c["code"] for c in state.cells] == before
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True
