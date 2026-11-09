"""Level of detail: a part the viewer sees up close is tessellated again, its key and entities unchanged."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi.scene import preview as pv


def _cylinder_scene() -> pv.PreviewScene:
    return pv.compile_preview(scad.make_part_rpart(part_id="c", body=scad.make_cylinder_rsolid(25.0, 10.0)))


def _entities(part: dict) -> list[str]:
    return sorted(group["entity_id"] for group in part["face_groups"] + part["edge_groups"]) + sorted(part["vertex_ids"])


def test_a_finer_level_is_denser_and_names_the_same_entities() -> None:
    pv.clear_preview_cache()
    scene = _cylinder_scene()
    [key] = scene.parts
    coarse = pv.decode_preview_header(pv.refine_preview(scene, [key], linear_tolerance=0.35, angular_tolerance=0.22))
    fine = pv.decode_preview_header(pv.refine_preview(scene, [key, "unknown"], linear_tolerance=0.01, angular_tolerance=0.025))
    [before], [after] = coarse["parts"], fine["parts"]
    assert after["key"] == before["key"] == key  # unknown keys are left out
    assert fine["nodes"] == []
    assert after["triangles"] > 4 * before["triangles"]
    assert after["edge_positions"]["count"] > 4 * before["edge_positions"]["count"]
    assert _entities(after) == _entities(before)
    with pytest.raises(pv.PreviewError):
        pv.refine_preview(scene, [key], linear_tolerance=0.0, angular_tolerance=0.1)


def test_the_editor_hands_the_kernels_answer_to_the_page() -> None:
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from simplecadapi.editor.server import WorkspaceState, create_app

    scene = _cylinder_scene()
    [key] = scene.parts
    asked: list[tuple] = []

    class Kernel:
        def refine_preview(self, keys, linear, angular):
            asked.append((keys, linear, angular))
            return pv.refine_preview(scene, keys, linear_tolerance=linear, angular_tolerance=angular)

    with tempfile.TemporaryDirectory() as tmp:
        state = WorkspaceState(Path(tmp).resolve())
        client = TestClient(create_app(state))
        body = {"keys": [key], "linear": 0.03, "angular": 0.05}
        assert client.post("/api/preview/refine", json=body).status_code == 409  # no kernel yet
        state.kernel = Kernel()
        reply = client.post("/api/preview/refine", json=body)
        assert reply.status_code == 200
        assert [part["key"] for part in pv.decode_preview_header(reply.content)["parts"]] == [key]
        assert asked == [([key], 0.03, 0.05)]
        for bad in ({"keys": [key], "linear": 0.0001, "angular": 0.05}, {"keys": [], "linear": 0.03, "angular": 0.05}, {"keys": [key]}):
            assert client.post("/api/preview/refine", json=bad).status_code == 400
