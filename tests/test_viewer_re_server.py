"""Tests for the reverse-engineering studio server (viewer/server).

Covers the scene synthesis contract (the browser re-mode depends on it), the
region resolver math, submission composition with server-side context, and
the CLI wait handshake — everything except the three.js side.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from viewer.server.runtime import (  # noqa: E402
    ReCase,
    compose_submission,
    entity_neighborhood,
    resolve_region,
)
from viewer.server.scene_build import build_step_scene  # noqa: E402
from viewer.server.server import StudioServer, StudioState, _wait_for_submission  # noqa: E402


@pytest.fixture(scope="module")
def fixture_step(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("re_case") / "target.step"
    import simplecadapi as scad
    from simplecadapi.kernel.ocp_export import export_step_shapes

    plate = scad.make_box_rsolid(width=40.0, height=30.0, depth=12.0)
    bore = scad.make_cylinder_rsolid(
        radius=6.0,
        height=16.0,
        bottom_face_center=(0.0, 0.0, -2.0),
        axis=(0.0, 0.0, 1.0),
    )
    cut = scad.cut_rsolid(plate, bore)
    export_step_shapes([cut.wrapped], str(path))
    return path


@pytest.fixture(scope="module")
def case(fixture_step: Path) -> ReCase:
    return ReCase.open_case(fixture_step.parent)


@pytest.fixture(scope="module")
def scene(fixture_step: Path):
    return build_step_scene(fixture_step)


def test_scene_matches_package_projection_shape(scene) -> None:
    manifest = scene.manifest
    assert manifest["schema_version"] == "2.0"
    assert manifest["units"] == "mm"
    assert len(manifest["nodes"]) == len(manifest["definitions"]) == 1
    node = manifest["nodes"][0]
    assert node["geometry_asset_id"] and node["entity_asset_id"]

    sidecar_uri = manifest["entity_assets"][0]["uri"]
    sidecar = json.loads(scene.files[sidecar_uri])
    assert sidecar["schema_version"] == "2.0"
    kinds = {entity["kind"] for entity in sidecar["entities"]}
    assert kinds == {"solid", "face", "edge", "vertex"}
    # 6 box faces + 1 bore cylinder face
    assert sum(1 for e in sidecar["entities"] if e["kind"] == "face") == 7

    group_ids = {group["entity_id"] for group in sidecar["face_groups"]}
    face_ids = {e["entity_id"] for e in sidecar["entities"] if e["kind"] == "face"}
    assert group_ids == face_ids
    # every entity record carries the canonical id the inspection API accepts
    for entity in sidecar["entities"]:
        assert entity["topo_id"].split(":")[0] == entity["kind"] or entity["kind"] == "solid"
        assert scene.model.resolve_entity(entity["topo_id"])


def test_scene_files_decode_and_describe(scene) -> None:
    assert "scene.json" in scene.files
    bore = scene.model.describe_entity("face:6")
    assert bore["geometry"]["type"] == "CYLINDER"
    assert bore["adjacency"]["bodies"] == ["body:0"]


def test_scene_marks_seam_and_degenerate_edges(scene) -> None:
    sidecar_uri = scene.manifest["entity_assets"][0]["uri"]
    sidecar = json.loads(scene.files[sidecar_uri])
    edges = [entity for entity in sidecar["entities"] if entity["kind"] == "edge"]
    # the bore cylinder wall carries exactly one seam (its doubled edge)
    assert [e["topo_id"] for e in edges if e["properties"]["seam"]] == ["edge:14"]
    assert all(not e["properties"]["degenerate"] for e in edges)
    # the flag agrees with the topology: seam ⇔ fewer than 2 distinct faces
    for edge in edges:
        faces = len(scene.model.adjacency_details(edge["topo_id"])["faces"])
        assert (faces < 2) == edge["properties"]["seam"]


def test_region_resolve_projects_and_filters(scene) -> None:
    camera = {
        "position": [0.0, -0.06, 0.03],
        "target": [0.0, 0.006, 0.0],
        "up": [0, 0, 1],
        "fov_deg": 42,
        "width": 800,
        "height": 600,
    }
    fullscreen = [[0, 0], [800, 0], [800, 600], [0, 600]]
    hits = resolve_region(scene.anchors, camera, fullscreen)
    hit_faces = {eid for eid in hits["entity_ids"] if eid.startswith("face:")}
    # camera sits below-front in cad space: exactly the -y face and the -z
    # (bottom) face point toward it; everything else fails the normal test
    expected = {
        eid
        for eid, anchor in scene.anchors.items()
        if anchor["kind"] == "face"
        and (anchor["normal"][1] < -0.9 or anchor["normal"][2] < -0.9)
    }
    assert len(expected) == 2
    assert hit_faces == expected

    far_away = [[10000, 10000], [10100, 10000], [10100, 10100], [10000, 10100]]
    assert resolve_region(scene.anchors, camera, far_away)["count"] == 0


def test_compose_submission_attaches_context_and_names_failures(scene, case: ReCase) -> None:
    submission = compose_submission(
        case,
        scene.model.describe_entity,
        scene.summary,
        {
            "annotations": [
                {
                    "annotation_id": "a1",
                    "kind": "entity_set",
                    "intent": "exact_copy",
                    "text": "bore",
                    "entity_ids": ["face:6", "face:999"],
                }
            ],
            "note": "round 1",
            "snapshot_png": "data:image/png;base64,iVBORw0KGgo=",
        },
    )
    assert submission["submission_seq"] >= 1
    annotation = submission["annotations"][0]
    assert annotation["entity_ids"] == ["face:6", "face:999"]
    # failures are named, not swallowed
    assert annotation["unresolved_entity_ids"] == ["face:999"]
    context = annotation["context"]["face:6"]
    assert context["kind"] == "face"
    assert context["adjacency"]["direct"]
    assert submission["snapshot"] and (case.root / submission["snapshot"]).exists()
    assert case.submission_path.is_file()
    assert case.read_submission_seq() == submission["submission_seq"]


def test_compose_submission_never_truncates_entity_selection(scene, case: ReCase) -> None:
    """A user pick list passes through whole — capping it would silently
    discard part of the human's selection (ruling 2026-09-06)."""

    entity_ids = [f"edge:{index}" for index in range(1, 15)]
    submission = compose_submission(
        case,
        scene.model.describe_entity,
        scene.summary,
        {"annotations": [{"annotation_id": "a1", "kind": "free", "intent": "free", "text": "seams", "entity_ids": entity_ids}]},
    )
    annotation = submission["annotations"][0]
    assert annotation["entity_ids"] == entity_ids


def test_compose_submission_injects_one_level_neighborhood(scene, case: ReCase) -> None:
    """face → edges → adjacent faces and vertices, exactly one level deep."""

    submission = compose_submission(
        case,
        scene.model.describe_entity,
        scene.summary,
        {
            "annotations": [
                {
                    "annotation_id": "a1",
                    "kind": "free",
                    "intent": "free",
                    "text": "bore wall",
                    "entity_ids": ["face:6"],
                }
            ],
            "note": "",
        },
        adjacency=scene.model.adjacency_details,
    )
    card = submission["annotations"][0]["context"]["face:6"]
    assert card["level"] == 1
    assert card["entity"]["geometry"]["type"] == "CYLINDER"

    details = scene.model.adjacency_details("face:6")
    assert card["edges"]["total"] == len(details["edges"])
    assert card["edges"]["truncated"] is False
    for edge in card["edges"]["items"]:
        assert edge["curve_type"] and edge["length"] is not None
        face_ids = {face["topo_id"] for face in edge["adjacent_faces"]["items"]}
        assert "face:6" in face_ids  # the edge borders the selected face itself
        for face in edge["adjacent_faces"]["items"]:
            assert face["surface_type"] and face["area"] is not None

    assert {vertex["topo_id"].split(":")[0] for vertex in card["vertices"]["items"]} == {"vertex"}
    assert all(len(vertex["coordinates"]) == 3 for vertex in card["vertices"]["items"])
    neighbor_ids = {face["topo_id"] for face in card["neighboring_faces"]["items"]}
    assert neighbor_ids == set(details["neighboring_faces"])
    assert "face:6" not in neighbor_ids


def test_compose_submission_edge_and_vertex_neighborhood(scene, case: ReCase) -> None:
    def edge_summary(edge_id: str) -> tuple[str, int]:
        geometry = scene.model.describe_entity(edge_id)["geometry"]
        faces = scene.model.adjacency_details(edge_id)["faces"]
        return geometry["type"], len(faces)

    # interior straight edge: two endpoints, exactly two bordering faces.
    # (cylinder seam edges border one distinct face on both sides — correct.)
    line_edge = next(
        edge_id
        for edge_id in (f"edge:{index}" for index in range(len(scene.model.edges)))
        if edge_summary(edge_id) == ("LINE", 2)
    )
    edge_card = entity_neighborhood(
        scene.model.describe_entity, scene.model.adjacency_details, line_edge
    )
    assert len(edge_card["vertices"]["items"]) == 2
    assert len(edge_card["adjacent_faces"]["items"]) == 2
    assert edge_card["adjacent_edges"]["items"]

    vertex_id = edge_card["vertices"]["items"][0]["topo_id"]
    vertex_card = entity_neighborhood(
        scene.model.describe_entity, scene.model.adjacency_details, vertex_id
    )
    assert vertex_card["adjacent_edges"]["items"]
    assert vertex_card["adjacent_faces"]["items"]


def test_operations_registry_loads_from_markdown() -> None:
    from viewer.server import operation_tips

    payload = operation_tips.operation_payload()
    assert [category["id"] for category in payload["categories"]] == [
        "sketch",
        "boolean",
        "solid",
        "primitive",
        "modify",
        "surface",
        "pattern",
    ]
    assert payload["errors"] == []
    op_ids = {operation["op_id"] for operation in payload["operations"]}
    assert {
        "sketch",
        "union",
        "cut",
        "intersect",
        "extrude",
        "box",
        "cylinder",
        "sphere",
        "fillet",
        "shell",
        "surface_patch",
        "linear_pattern",
        "radial_pattern",
    } <= op_ids
    for operation in payload["operations"]:
        assert operation["hint"].strip()
        assert operation["api"] and operation["reads"] and operation["doc_refs"]
        assert (Path(REPO_ROOT) / operation["doc_refs"][0]).is_file(), operation["op_id"]
    fillet = next(operation for operation in payload["operations"] if operation["op_id"] == "fillet")
    assert any("ql-playbook" in ref for ref in fillet["doc_refs"])


def test_operations_registry_names_broken_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from viewer.server import operation_tips

    (tmp_path / "good.md").write_text(
        "---\nlabel: good\ncategory: solid\napi:\n  - union_rsolid\nreads:\n  - overlaps\ndoc_refs:\n  - docs/x.md\n---\nDo it.\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.md").write_text("no frontmatter at all", encoding="utf-8")
    monkeypatch.setattr(operation_tips, "_TIPS_DIR", tmp_path)
    monkeypatch.setattr(operation_tips, "_REGISTRY_CACHE", None)
    monkeypatch.setattr(operation_tips, "_REGISTRY_STAMP", None)
    payload = operation_tips.operation_payload()
    assert {operation["op_id"] for operation in payload["operations"]} == {"good"}
    # failures are named, not swallowed
    assert len(payload["errors"]) == 1 and payload["errors"][0].startswith("broken.md:")


def test_compose_submission_embeds_operation_context(scene, case: ReCase) -> None:
    submission = compose_submission(
        case,
        _null_describe,
        scene.summary,
        {
            "annotations": [
                {
                    "annotation_id": "a1",
                    "kind": "free",
                    "intent": "free",
                    "text": "[face:6](face:6) then [fillet](op:fillet)",
                    "entity_ids": [],
                    "operations": ["fillet", "not_a_tip"],
                }
            ],
            "note": "",
        },
    )
    annotation = submission["annotations"][0]
    assert annotation["operations"] == ["fillet", "not_a_tip"]
    context = submission["operation_context"]
    assert set(context) == {"fillet"}
    assert context["fillet"]["category"] == "modify"
    assert context["fillet"]["hint"]
    assert any("ql-playbook" in ref for ref in context["fillet"]["doc_refs"])


def test_wait_handshake_times_out_then_returns(case: ReCase) -> None:
    state = StudioState(case)
    server = StudioServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        # timeout yields exit code 124 while the server stays alive
        assert _wait_for_submission(case, port=port, timeout=0.3) == 124
        baseline = case.read_submission_seq()
        submission_thread = threading.Timer(
            0.4,
            compose_submission,
            args=(case, _null_describe, {}, {"annotations": [], "note": "next round"}),
        )
        submission_thread.start()
        try:
            started = time.monotonic()
            assert _wait_for_submission(case, port=port, timeout=30) == 0
            assert case.read_submission_seq() > baseline
            assert time.monotonic() - started < 10
        finally:
            submission_thread.join()
        # a dead server surfaces as exit code 1, not a silent hang
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert _wait_for_submission(case, port=port, timeout=1) == 1
    finally:
        if thread.is_alive():
            server.shutdown()
            server.server_close()


def _null_describe(entity_id: str) -> dict:
    return {"entity_id": entity_id, "kind": "unknown", "geometry": {}, "bounding_box": {}, "adjacency": {}}


def test_http_endpoints(case: ReCase) -> None:
    state = StudioState(case)
    server = StudioServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=3) as response:
            assert json.loads(response.read())["ok"] is True
        with urllib.request.urlopen(f"{base}/api/session", timeout=3) as response:
            session = json.loads(response.read())
        assert session["target"]["present"] is True
        assert set(session["artifacts"]) == {
            "rebuild.py",
            "rebuilt.step",
            "rebuilt.scadpkg",
            "comparison.png",
            "evaluation.json",
        }
        with urllib.request.urlopen(f"{base}/api/scene/original", timeout=30) as response:
            scene_payload = json.loads(response.read())
        assert "scene.json" in scene_payload["files"]
        with urllib.request.urlopen(f"{base}/api/entity?id=face:6", timeout=3) as response:
            assert json.loads(response.read())["geometry"]["type"] == "CYLINDER"
        with urllib.request.urlopen(f"{base}/api/operations", timeout=3) as response:
            operations = json.loads(response.read())
        assert operations["errors"] == []
        assert len(operations["categories"]) == 7
        assert any(operation["op_id"] == "extrude" for operation in operations["operations"])
        request = urllib.request.Request(
            f"{base}/api/annotate",
            data=json.dumps({"action": "add", "annotation": {"annotation_id": "x1"}}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            assert json.loads(response.read())["recorded"] == 1
    finally:
        server.shutdown()
        server.server_close()
