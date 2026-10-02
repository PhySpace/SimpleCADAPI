from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import threading
from pathlib import Path
import sys
import pytest

import simplecadapi as scad
from simplecadapi.artifacts.assembly_io import attached_definition
from simplecadapi.artifacts.canonical import ArtifactValidationError


def _load_function(path: Path, source: str, name: str):
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"part_fixture_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, getattr(module, name)


def test_part_builds_on_every_call_with_identical_definitions() -> None:
    calls = 0

    @scad.part(id="tagged_box")
    def build_box(width: float = 2.0) -> scad.Part:
        nonlocal calls
        calls += 1
        body = scad.make_box_rsolid(width=width, height=3.0, depth=4.0)
        body = scad.apply_tag(shape=body, tag="role.body")
        part = scad.make_part_rpart(part_id="tagged_box", body=body)
        connector = scad.make_placement_connector_rconnector(
            connector_id="mount",
            placement=scad.make_placement_rplacement(origin=(1.0, 0.0, 0.0)),
        )
        return scad.add_connector_rpart(part=part, connector=connector)

    first = build_box()
    second = build_box()

    # No cache: the builder runs every time, and the output is deterministic.
    assert calls == 2
    assert second.value is not first.value
    assert second.definition.canonical_bytes == first.definition.canonical_bytes
    assert second.feature_graph.canonical_bytes == first.feature_graph.canonical_bytes
    assert second.feature_graph.restore_session().graph.to_dict() == (
        first.feature_graph.restore_session().graph.to_dict()
    )
    assert first.value.body.get_volume() == pytest.approx(24.0)
    assert first.value.connector_ids() == ("mount",)
    assert "role.body" in scad.list_tags(shape=first.value.body)

    # The runtime value carries its own definition identity.
    assert attached_definition(first.value) is first.definition
    assert first.value._get_runtime("definition.content_hash") == (
        first.definition.content_hash
    )
    assert first.value._get_runtime("definition.revision") == "1.0.0"


def test_part_definition_does_not_depend_on_the_call_site() -> None:
    @scad.part(id="call_site_free")
    def build() -> scad.Solid:
        return scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)

    first = build()
    second = [build()][0]  # different line, column and assignment target

    assert second.definition.content_hash == first.definition.content_hash
    # @part itself wraps the Solid into a Part; that node has no user source.
    graph = first.feature_graph.restore_session().graph.to_dict()
    (wrap,) = [node for node in graph["nodes"] if node["op"] == "make_part_rpart"]
    assert wrap.get("source") is None


def test_part_accepts_solid_and_wraps_definition_id() -> None:
    @scad.part(id="solid_result")
    def build() -> scad.Solid:
        return scad.make_box_rsolid(width=1.0, height=2.0, depth=3.0)

    result = build()

    assert result.value.part_id == "solid_result"
    assert result.value.body.get_volume() == pytest.approx(6.0)
    assert result.feature_graph.result_node_ids == (
        result.feature_graph.restore_session().result_node_ids
    )


def test_part_builds_concurrently_in_isolated_sessions() -> None:
    calls = 0
    guard = threading.Lock()

    @scad.part(id="concurrent_part")
    def build(width: float) -> scad.Solid:
        nonlocal calls
        with guard:
            calls += 1
        return scad.make_box_rsolid(width=width, height=2.0, depth=3.0)

    widths = [float(index + 1) for index in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(build, widths))

    assert calls == 8
    for width, result in zip(widths, results):
        assert result.value.body.get_volume() == pytest.approx(width * 6.0)


def test_part_rejects_wrong_result_and_mismatched_part_id() -> None:
    @scad.part(id="expected")
    def wrong_type():
        scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)
        return ()

    @scad.part(id="expected")
    def wrong_id():
        body = scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)
        return scad.make_part_rpart(part_id="actual", body=body)

    with pytest.raises(ArtifactValidationError, match="solid_cardinality_invalid"):
        wrong_type()
    with pytest.raises(ArtifactValidationError, match="definition_id_mismatch"):
        wrong_id()


def test_part_rejects_multiple_explicit_results() -> None:
    @scad.part(id="multiple")
    def build():
        first = scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)
        second = scad.make_box_rsolid(width=2.0, height=2.0, depth=2.0)
        session = scad.get_active_session()
        assert session is not None
        session.capture_result(value=(first, second))
        return second

    with pytest.raises(ArtifactValidationError, match="exactly one result node"):
        build()


def test_part_runs_in_its_own_session_when_called_inside_a_recording() -> None:
    seen: dict[str, object] = {}

    @scad.part(id="nested")
    def build() -> scad.Solid:
        seen["session"] = scad.get_active_session()
        seen["origin"] = tuple(scad.get_current_cs().origin)
        return scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)

    outer = scad.GraphSession(graph_id="outer", allow_external_definitions=True)
    with outer:
        scad.make_box_rsolid(width=5.0, height=5.0, depth=5.0)
        nodes_before = len(outer.graph.nodes)
        with scad.SimpleWorkplane(origin=(10.0, 0.0, 0.0)):
            result = build()
        # The build neither recorded into the caller nor inherited its frame.
        assert scad.get_active_session() is outer
        assert len(outer.graph.nodes) == nodes_before
        assert seen["session"] is not outer
        assert seen["origin"] == pytest.approx((0.0, 0.0, 0.0))

        # Used in the caller, the Part appears as an external definition.
        assembly = scad.make_assembly_rassembly("holder")
        scad.add_component_rassembly(
            assembly,
            result.part,
            component_id="nested_1",
            placement=scad.identity_placement_rplacement(),
        )
        assert outer.external_definition_node(result.part) is not None


def test_part_nests_inside_another_part() -> None:
    @scad.part(id="inner")
    def inner() -> scad.Solid:
        return scad.make_box_rsolid(width=1.0, height=1.0, depth=2.0)

    @scad.part(id="outer")
    def outer() -> scad.Solid:
        depth = inner().value.body.get_volume()
        return scad.make_box_rsolid(width=1.0, height=1.0, depth=depth)

    result = outer()

    assert result.value.body.get_volume() == pytest.approx(2.0)
    assert result.definition.definition_id == "outer"


def test_part_rejects_async_and_removed_keywords(tmp_path: Path) -> None:
    async def async_build():
        return None

    with pytest.raises(TypeError, match="does not support async"):
        scad.part(async_build)
    with pytest.raises(TypeError, match="cache"):
        scad.part(id="cached", cache="off")  # type: ignore[call-overload]
    with pytest.raises(TypeError, match="export_dir"):
        scad.part(id="exported", export_dir=tmp_path / "out")  # type: ignore[call-overload]


def test_part_records_file_input_bytes_not_mtime(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='1.0.0'\n", encoding="utf-8"
    )
    source = tmp_path / "input.txt"
    source.write_text("alpha", encoding="utf-8")
    _module, function = _load_function(
        tmp_path / "builder.py",
        "import simplecadapi as scad\n"
        "def build():\n"
        "    return scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)\n",
        "build",
    )
    build = scad.part(
        id="dependent",
        inputs=(scad.file_input("input.txt"),),
        project_root=tmp_path,
    )(function)

    first = build()
    source.touch()
    touched = build()
    source.write_text("bravo", encoding="utf-8")
    changed = build()

    (snapshot,) = first.definition.file_inputs
    assert snapshot.path == "input.txt"
    assert snapshot.byte_length == 5
    assert touched.definition.content_hash == first.definition.content_hash
    assert changed.definition.file_inputs[0].sha256 != snapshot.sha256
    assert changed.definition.content_hash != first.definition.content_hash


def test_part_snapshots_helper_sources_and_picks_up_their_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='source-fixture'\nversion='1.0.0'\n",
        encoding="utf-8",
    )
    helper_path = tmp_path / "body_helper.py"
    builder_path = tmp_path / "builder.py"
    helper_path.write_text(
        "import simplecadapi as scad\n"
        "def make_body():\n"
        "    return scad.make_box_rsolid(width=1.0, height=2.0, depth=3.0)\n",
        encoding="utf-8",
    )
    builder_source = (
        "import body_helper\n"
        "def build():\n"
        "    return body_helper.make_body()\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    _module, function = _load_function(builder_path, builder_source, "build")
    first = scad.part(id="helper_dependent", project_root=tmp_path)(function)()

    encoded = scad.encode_part_definition(first.definition)
    from simplecadapi.scene.archive import preflight_zip_bytes

    archive = preflight_zip_bytes(encoded, manifest_name="part-definition.json")
    feature_payload = archive.members[
        "blobs/" + first.definition.feature_graph_ref.path
    ]
    archived_graph = scad.load_feature_graph_artifact(feature_payload)
    helper_snapshot = next(
        item for item in archived_graph.source_files if item.display_path == "body_helper.py"
    )
    assert archived_graph.blobs[helper_snapshot.uri] == helper_path.read_bytes()

    helper_path.write_text(
        "import simplecadapi as scad\n"
        "def make_body():\n"
        "    # Deliberately changes helper bytes without changing builder bytes.\n"
        "    return scad.make_box_rsolid(width=1.0, height=5.0, depth=3.0)\n",
        encoding="utf-8",
    )
    importlib.invalidate_caches()
    sys.modules.pop("body_helper", None)
    _module, changed_function = _load_function(builder_path, builder_source, "build")
    changed = scad.part(id="helper_dependent", project_root=tmp_path)(changed_function)()

    assert changed.value.body.get_volume() == pytest.approx(15.0)
    assert changed.definition.content_hash != first.definition.content_hash


def test_part_definition_archive_round_trip_and_reexport(tmp_path: Path) -> None:
    @scad.part(id="definition_io")
    def build() -> scad.Solid:
        return scad.make_box_rsolid(width=2.0, height=3.0, depth=4.0)

    result = build()
    first = scad.export_part_definition(
        result.definition,
        tmp_path / "first.part-definition.zip",
    )
    loaded = scad.load_part_definition(first)
    second = scad.export_part_definition(
        loaded,
        tmp_path / "second.part-definition.zip",
    )

    assert loaded.canonical_bytes == result.definition.canonical_bytes
    assert first.read_bytes() == second.read_bytes()


def test_part_definition_archive_rejects_mutated_and_extra_blobs() -> None:
    from simplecadapi.scene.archive import canonical_zip_bytes, preflight_zip_bytes

    @scad.part(id="definition_corrupt")
    def build() -> scad.Solid:
        return scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)

    encoded = scad.encode_part_definition(build().definition)
    archive = preflight_zip_bytes(encoded, manifest_name="part-definition.json")
    members = dict(archive.members)
    body_name = next(name for name in members if name.endswith(".brep"))
    members[body_name] += b"x"
    mutated = canonical_zip_bytes(members, manifest_name="part-definition.json")
    with pytest.raises(
        ArtifactValidationError, match="blob_size_mismatch|blob_hash_mismatch"
    ):
        scad.load_part_definition(mutated)

    members = dict(archive.members)
    members["blobs/unexpected.bin"] = b"unexpected"
    extra = canonical_zip_bytes(members, manifest_name="part-definition.json")
    with pytest.raises(ArtifactValidationError, match="member set differs"):
        scad.load_part_definition(extra)
