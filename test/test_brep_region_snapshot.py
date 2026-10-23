from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi.inspect import brep
from simplecadapi._internal.canonical_json import canonical_json_bytes, parse_canonical_json
from simplecadapi._internal.brep_region import HEADER
from simplecadapi.kernel.ocp_export import export_step_shapes


KETTLE_STEP = os.environ.get("SIMPLECADAPI_KETTLE_STEP")


def _write_box_step(path: Path) -> scad.Solid:
    box = scad.make_box_rsolid(
        width=10.0,
        height=20.0,
        depth=30.0,
        bottom_face_center=(5.0, 0.0, 0.0),
    )
    export_step_shapes([box.wrapped], str(path))
    return box


def _rewrite_snapshot_manifest(path: Path, update) -> None:
    data = path.read_bytes()
    magic, major, minor, flags, manifest_size, payload_size = HEADER.unpack_from(data)
    manifest_start = HEADER.size
    payload_start = manifest_start + manifest_size
    manifest = parse_canonical_json(data[manifest_start:payload_start])
    update(manifest)
    manifest_bytes = canonical_json_bytes(manifest)
    path.write_bytes(
        HEADER.pack(magic, major, minor, flags, len(manifest_bytes), payload_size)
        + manifest_bytes
        + data[payload_start:]
    )


def test_complete_step_region_loads_as_one_replayable_solid(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    source = _write_box_step(target)
    snapshot = tmp_path / "body.scadbrep"

    result_path = brep.copy_step_region_rpath(
        path=target,
        output_path=snapshot,
    )
    digest = "sha256:" + hashlib.sha256(snapshot.read_bytes()).hexdigest()
    target.unlink()

    previous_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with scad.GraphSession() as session:
            loaded = scad.load_brep_region_rsolid(
                path=Path(snapshot.name),
                sha256=digest,
                tag_prefix="kettle.transcribed",
            )
    finally:
        os.chdir(previous_cwd)

    assert result_path == snapshot.resolve()
    assert not target.exists()
    assert loaded.get_volume() == pytest.approx(source.get_volume(), abs=1.0e-9)
    assert "kettle.transcribed.solid" in scad.list_tags(loaded, scope="local")

    payload = json.loads(scad.export_model_json(session))
    nodes = payload["graph"]["nodes"]
    assert [node["op"] for node in nodes] == ["load_brep_region_rsolid"]
    assert nodes[0]["params"] == {
        "path": snapshot.name,
        "sha256": digest,
        "tag_prefix": "kettle.transcribed",
    }

    try:
        os.chdir(tmp_path)
        replayed = scad.replay_model_json(json.dumps(payload, indent=2))
    finally:
        os.chdir(previous_cwd)
    assert len(replayed) == 1
    assert isinstance(replayed[0], scad.Solid)
    assert replayed[0].get_volume() == pytest.approx(source.get_volume(), abs=1.0e-9)
    assert "kettle.transcribed.solid" in scad.list_tags(replayed[0], scope="local")


def test_brep_region_load_rejects_changed_snapshot(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "body.scadbrep"
    brep.copy_step_region_rpath(path=target, output_path=snapshot)
    digest = "sha256:" + hashlib.sha256(snapshot.read_bytes()).hexdigest()
    snapshot.write_bytes(snapshot.read_bytes() + b"changed")

    previous_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(scad.SimpleCADError, match="SHA-256"):
            scad.load_brep_region_rsolid(path=Path(snapshot.name), sha256=digest)
    finally:
        os.chdir(previous_cwd)


def test_graph_rejects_absolute_snapshot_path(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "body.scadbrep"
    brep.copy_step_region_rpath(path=target, output_path=snapshot)
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    with scad.GraphSession(), pytest.raises(scad.SimpleCADError, match="relative"):
        scad.load_brep_region_rsolid(path=snapshot.resolve(), sha256=digest)


def test_graph_rejects_alternate_data_stream_snapshot_path() -> None:
    with (
        scad.GraphSession(),
        pytest.raises(scad.SimpleCADError, match="must not contain"),
    ):
        scad.load_brep_region_rsolid(
            path="body:hidden.scadbrep",
            sha256="0" * 64,
        )


def test_face_region_loads_as_one_replayable_shell(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    model = brep.load_step_rbrepmodel(target)
    top_face_id = max(
        range(len(model.faces)),
        key=lambda index: model.describe_entity(f"face:{index}")["geometry"][
            "centroid"
        ][2],
    )
    snapshot = tmp_path / "top.scadbrep"

    brep.copy_step_region_rpath(
        path=target,
        output_path=snapshot,
        face_ids=[f"face:{top_face_id}"],
    )
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    previous_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with scad.GraphSession() as session:
            loaded = scad.load_brep_region_rshell(
                path=Path(snapshot.name),
                sha256=digest,
                tag_prefix="kettle.copied",
            )
    finally:
        os.chdir(previous_cwd)

    assert isinstance(loaded, scad.Shell)
    assert len(loaded._iter_faces()) == 1
    assert not loaded.is_closed()
    assert "kettle.copied.shell" in scad.list_tags(loaded, scope="local")
    assert "provenance.exact_transcription" in scad.list_tags(loaded)
    assert all(
        face.get_metadata("provenance")["construction"] == "exact_transcription"
        for face in loaded._iter_faces()
    )
    assert loaded.get_faces(0).get_metadata("provenance")["source_face_id"] == (
        f"face:{top_face_id}"
    )
    explanation = scad.explain_tag(
        loaded.get_faces(0),
        "provenance.exact_transcription",
        scope="local",
    )
    assert explanation[0]["binding"]["certainty"] == "asserted"
    assert explanation[0]["binding"]["evidence"]["source_face_id"] == (
        f"face:{top_face_id}"
    )
    provenance = loaded.get_metadata("brep_region")["provenance"]
    assert provenance["construction"] == "exact_transcription"
    assert provenance["topology_origin"] == "retained"
    assert loaded.get_metadata("brep_region")["source_face_ids"] == [
        f"face:{top_face_id}"
    ]

    payload = json.loads(scad.export_model_json(session))
    assert [node["op"] for node in payload["graph"]["nodes"]] == [
        "load_brep_region_rshell"
    ]
    try:
        os.chdir(tmp_path)
        replayed = scad.replay_model_json(json.dumps(payload))
    finally:
        os.chdir(previous_cwd)
    assert isinstance(replayed[0], scad.Shell)
    assert len(replayed[0]._iter_faces()) == 1


def test_face_region_rejects_duplicate_face_ids(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)

    with pytest.raises(ValueError, match="duplicate"):
        brep.copy_step_region_rpath(
            path=target,
            output_path=tmp_path / "body.scadbrep",
            face_ids=["face:0", "face:0"],
        )


def test_face_region_rejects_disconnected_faces(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    model = brep.load_step_rbrepmodel(target)
    face_centers = [
        model.describe_entity(f"face:{index}")["geometry"]["centroid"]
        for index in range(len(model.faces))
    ]
    bottom = min(range(len(face_centers)), key=lambda index: face_centers[index][2])
    top = max(range(len(face_centers)), key=lambda index: face_centers[index][2])

    with pytest.raises(ValueError, match="connected"):
        brep.copy_step_region_rpath(
            path=target,
            output_path=tmp_path / "disconnected.scadbrep",
            face_ids=[f"face:{bottom}", f"face:{top}"],
        )


def test_snapshot_is_deterministic_and_preserves_trimmed_topology(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.step"
    body = scad.make_box_rsolid(
        width=20.0,
        height=20.0,
        depth=20.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )
    cutter = scad.make_cylinder_rsolid(
        radius=3.0,
        height=30.0,
        bottom_face_center=(0.0, 0.0, -5.0),
    )
    drilled = scad.cut_rsolid(body, cutter, skip_non_intersecting=False)
    export_step_shapes([drilled.wrapped], str(target))
    first = tmp_path / "first.scadbrep"
    second = tmp_path / "second.scadbrep"

    brep.copy_step_region_rpath(path=target, output_path=first)
    brep.copy_step_region_rpath(path=target, output_path=second)

    assert first.read_bytes() == second.read_bytes()
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    loaded = scad.load_brep_region_rsolid(path=first, sha256=digest)
    source_summary = brep.index_shape_rbrepmodel(drilled.wrapped).summary()
    loaded_summary = brep.index_shape_rbrepmodel(loaded.wrapped).summary()
    assert loaded_summary["face_count"] == source_summary["face_count"]
    assert loaded_summary["edge_count"] == source_summary["edge_count"]
    assert loaded_summary["vertex_count"] == source_summary["vertex_count"]
    assert (
        loaded_summary["surface_type_statistics"]
        == source_summary["surface_type_statistics"]
    )


def test_failed_copy_does_not_replace_existing_snapshot(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "body.scadbrep"
    snapshot.write_bytes(b"accepted")

    with pytest.raises(ValueError, match="out of range"):
        brep.copy_step_region_rpath(
            path=target,
            output_path=snapshot,
            face_ids=["face:999"],
        )

    assert snapshot.read_bytes() == b"accepted"


def test_face_region_is_deterministic_across_face_id_order(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    first = tmp_path / "first.scadbrep"
    second = tmp_path / "second.scadbrep"

    brep.copy_step_region_rpath(
        path=target,
        output_path=first,
        face_ids=["face:0", "face:1", "face:2", "face:3", "face:4", "face:5"],
    )
    brep.copy_step_region_rpath(
        path=target,
        output_path=second,
        face_ids=["face:5", "face:2", "face:4", "face:1", "face:3", "face:0"],
    )

    assert first.read_bytes() == second.read_bytes()


def test_copy_rejects_symbolic_link_destination(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symbolic links are not supported")
    target = tmp_path / "target.step"
    _write_box_step(target)
    sentinel = tmp_path / "sentinel.scadbrep"
    sentinel.write_bytes(b"sentinel")
    destination = tmp_path / "body.scadbrep"
    try:
        destination.symlink_to(sentinel)
    except OSError:
        pytest.skip("symbolic link creation is not permitted")

    with pytest.raises(ValueError, match="symbolic link"):
        brep.copy_step_region_rpath(path=target, output_path=destination)

    assert sentinel.read_bytes() == b"sentinel"


def test_copy_step_region_is_forbidden_inside_model_graph(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)

    with scad.GraphSession(), pytest.raises(RuntimeError, match="cannot run inside"):
        brep.copy_step_region_rpath(
            path=target,
            output_path=tmp_path / "body.scadbrep",
        )


def test_corrupt_snapshot_is_rejected_even_with_matching_artifact_hash(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "body.scadbrep"
    brep.copy_step_region_rpath(path=target, output_path=snapshot)
    data = bytearray(snapshot.read_bytes())
    data[-1] ^= 0xFF
    snapshot.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()

    with pytest.raises(scad.SimpleCADError, match="payload SHA-256"):
        scad.load_brep_region_rsolid(path=snapshot, sha256=digest)


def test_snapshot_loader_rejects_trailing_native_payload_data(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "body.scadbrep"
    brep.copy_step_region_rpath(path=target, output_path=snapshot)
    data = snapshot.read_bytes()
    magic, major, minor, flags, manifest_size, payload_size = HEADER.unpack_from(data)
    manifest_start = HEADER.size
    payload_start = manifest_start + manifest_size
    payload = data[payload_start:] + b"trailing"
    manifest = parse_canonical_json(data[manifest_start:payload_start])
    manifest["shape"]["byte_length"] = len(payload)
    manifest["shape"]["content_hash"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    manifest_bytes = canonical_json_bytes(manifest)
    artifact = (
        HEADER.pack(
            magic,
            major,
            minor,
            flags,
            len(manifest_bytes),
            len(payload),
        )
        + manifest_bytes
        + payload
    )
    snapshot.write_bytes(artifact)

    with pytest.raises(scad.SimpleCADError, match="trailing or missing"):
        scad.load_brep_region_rsolid(
            path=snapshot,
            sha256=hashlib.sha256(artifact).hexdigest(),
        )


def test_snapshot_loader_rejects_wrong_root_kind(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "shell.scadbrep"
    brep.copy_step_region_rpath(
        path=target,
        output_path=snapshot,
        face_ids=["face:0"],
    )
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    with pytest.raises(scad.SimpleCADError, match="contains shell, expected solid"):
        scad.load_brep_region_rsolid(path=snapshot, sha256=digest)


def test_snapshot_policy_is_checked_before_native_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import simplecadapi._internal.brep_region as container

    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "body.scadbrep"
    brep.copy_step_region_rpath(path=target, output_path=snapshot)
    _rewrite_snapshot_manifest(
        snapshot, lambda manifest: manifest["shape"].update({"format_version": 3})
    )
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("native decoder must not run")

    monkeypatch.setattr(container, "decode_shape", fail_if_called)
    with pytest.raises(scad.SimpleCADError, match="BinTools version"):
        scad.load_brep_region_rsolid(path=snapshot, sha256=digest)
    assert called is False


def test_snapshot_loader_rejects_non_regular_file(tmp_path: Path) -> None:
    directory = tmp_path / "directory.scadbrep"
    directory.mkdir()
    with pytest.raises(scad.SimpleCADError, match="regular file"):
        scad.load_brep_region_rsolid(path=directory, sha256="0" * 64)


def test_copied_face_provenance_survives_downstream_boolean(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "body.scadbrep"
    brep.copy_step_region_rpath(path=target, output_path=snapshot)
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    copied = scad.load_brep_region_rsolid(path=snapshot, sha256=digest)
    tool = scad.make_cylinder_rsolid(
        radius=2.0,
        height=40.0,
        bottom_face_center=(5.0, 0.0, -5.0),
    )

    cut = scad.cut_rsolid(
        copied,
        tool,
        skip_non_intersecting=False,
        tracking_policy="full",
    )

    descendants = [
        face
        for face in cut._iter_faces()
        if "provenance.exact_transcription" in scad.list_tags(face, scope="lineage")
    ]
    assert descendants
    assert len(descendants) < len(cut._iter_faces())


def test_copied_face_provenance_survives_sewing(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "top.scadbrep"
    model = brep.load_step_rbrepmodel(target)
    top = max(
        range(len(model.faces)),
        key=lambda index: model.describe_entity(f"face:{index}")["geometry"][
            "centroid"
        ][2],
    )
    brep.copy_step_region_rpath(
        path=target,
        output_path=snapshot,
        face_ids=[f"face:{top}"],
    )
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    copied = scad.load_brep_region_rshell(path=snapshot, sha256=digest)

    sewn = scad.sew_faces_rshell(faces=copied._iter_faces(), tolerance=1.0e-7)

    assert "provenance.exact_transcription" in scad.list_tags(sewn.get_faces(0))
    assert sewn.get_faces(0).get_metadata("provenance")["source_face_id"] == (
        f"face:{top}"
    )


def test_shell_faces_sew_and_solid_conversion_replay(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    source = _write_box_step(target)
    snapshot = tmp_path / "shell.scadbrep"
    model = brep.load_step_rbrepmodel(target)
    brep.copy_step_region_rpath(
        path=target,
        output_path=snapshot,
        face_ids=[f"face:{index}" for index in range(len(model.faces))],
    )
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    previous_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with scad.GraphSession() as session:
            copied = scad.load_brep_region_rshell(
                path=Path(snapshot.name), sha256=digest
            )
            sewn = scad.sew_faces_rshell(copied._iter_faces(), tolerance=1.0e-7)
            solid = scad.make_solid_from_shell_rsolid(sewn, tag_prefix="hybrid")
            authored_bindings = {
                face.get_metadata("provenance")["source_face_id"]: scad.explain_tag(
                    face, "provenance.exact_transcription", scope="local"
                )[0]["binding_id"]
                for face in solid._iter_faces()
            }
            session.capture_result(value=solid)
        payload = scad.export_model_json(session)
        replayed = scad.replay_model_json(payload, strict=True)[0]
    finally:
        os.chdir(previous_cwd)

    assert isinstance(replayed, scad.Solid)
    assert replayed.get_volume() == pytest.approx(source.get_volume(), abs=1.0e-9)
    assert "hybrid.solid" in scad.list_tags(replayed)
    assert all(
        face.get_metadata("provenance")["construction"] == "exact_transcription"
        for face in replayed._iter_faces()
    )
    assert len(
        {
            scad.explain_tag(face, "provenance.exact_transcription", scope="local")[0][
                "binding_id"
            ]
            for face in replayed._iter_faces()
        }
    ) == len(replayed._iter_faces())
    assert {
        face.get_metadata("provenance")["source_face_id"]: scad.explain_tag(
            face, "provenance.exact_transcription", scope="local"
        )[0]["binding_id"]
        for face in replayed._iter_faces()
    } == authored_bindings

    payload_data = json.loads(payload)
    face_selectors = [
        node["params"]["geo_selector"]
        for node in payload_data["graph"]["nodes"]
        if node["op"] == "make_select_rface"
    ]
    assert len(face_selectors) == len(source._iter_faces())
    assert {
        selector["brep_region_ref"]["source_face_id"] for selector in face_selectors
    } == set(authored_bindings)


def test_semantically_tagged_face_replays_as_sewing_input(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    _write_box_step(target)
    snapshot = tmp_path / "shell.scadbrep"
    model = brep.load_step_rbrepmodel(target)
    omitted = len(model.faces) - 1
    brep.copy_step_region_rpath(
        path=target,
        output_path=snapshot,
        face_ids=[f"face:{index}" for index in range(omitted)],
    )
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    previous_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with scad.GraphSession() as session:
            copied = scad.load_brep_region_rshell(snapshot.name, digest)
            boundary = scad.free_boundaries_rwirelist(copied)[0]
            feature_face = scad.make_face_from_wire_rface(boundary)
            feature_face = scad.apply_tag(
                feature_face, "provenance.feature_constructed"
            )
            sewn = scad.sew_faces_rshell([*copied._iter_faces(), feature_face])
            solid = scad.make_solid_from_shell_rsolid(sewn)
            session.capture_result(value=solid)
        replayed = scad.replay_model_json(scad.export_model_json(session))[0]
    finally:
        os.chdir(previous_cwd)

    assert isinstance(replayed, scad.Solid)
    assert (
        sum(
            "provenance.feature_constructed" in scad.list_tags(face)
            for face in replayed._iter_faces()
        )
        == 1
    )


@pytest.mark.skipif(
    not KETTLE_STEP, reason="set SIMPLECADAPI_KETTLE_STEP for corpus probe"
)
def test_kettle_bspline_regions_roundtrip_as_two_exact_shells(tmp_path: Path) -> None:
    from collections import deque

    from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Surface

    target = Path(str(KETTLE_STEP))
    model = brep.load_step_rbrepmodel(target)
    remaining = {
        index
        for index, face in enumerate(model.faces)
        if BRepAdaptor_Surface(face, True).GetType().name == "GeomAbs_BSplineSurface"
    }
    components = []
    while remaining:
        seed = next(iter(remaining))
        remaining.remove(seed)
        queue = deque([seed])
        component = []
        while queue:
            index = queue.popleft()
            component.append(index)
            neighbors = {
                int(value.split(":")[1])
                for value in model.adjacency_details(f"face:{index}")[
                    "neighboring_faces"
                ]
            }
            additions = neighbors & remaining
            remaining -= additions
            queue.extend(additions)
        components.append(sorted(component))

    assert sorted(map(len, components)) == [53, 70]
    loaded_shells = []
    for index, component in enumerate(components):
        snapshot = tmp_path / f"region-{index}.scadbrep"
        brep.copy_step_region_rpath(
            path=target,
            output_path=snapshot,
            face_ids=[f"face:{face_index}" for face_index in component],
        )
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        loaded_shells.append(scad.load_brep_region_rshell(path=snapshot, sha256=digest))

    assert sorted(len(shell._iter_faces()) for shell in loaded_shells) == [53, 70]
    assert sum(len(shell._iter_faces()) for shell in loaded_shells) == 123
    assert all(
        face.get_metadata("provenance")["construction"] == "exact_transcription"
        for shell in loaded_shells
        for face in shell._iter_faces()
    )
