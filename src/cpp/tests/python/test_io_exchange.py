"""STEP / STL / OBJ / GLB / BREP exchange, against numbers and files from the reference SDK."""

import base64
import json
import struct

import numpy as np
import pytest

import simplecadapi._cpp as scad
from simplecadapi._cpp import _testing
from test_io_support import exchange_reference, need_reference, reference_shapes, ref_eval  # noqa: F401


def face_count(shape):
    return len(shape.faces())


# ---------------------------------------------------------------------------
# STEP
# ---------------------------------------------------------------------------
def test_reference_step_round_trips_volume_faces_and_bbox(reference_shapes, exchange_reference):
    for name, shape in reference_shapes.items():
        expected = exchange_reference[name]
        assert shape.get_volume() == pytest.approx(expected["volume"], rel=1e-9), name
        assert face_count(shape) == expected["faces"], name
        lower, upper = scad.mesh(shape).bounds
        bbox = expected["bbox"]  # padded by OCCT's tolerance gap: compare loosely
        assert lower == pytest.approx(bbox[:3], abs=0.05), name
        assert upper == pytest.approx(bbox[3:], abs=0.05), name


def test_step_export_import_round_trip(reference_shapes, exchange_reference, tmp_path):
    for name, shape in reference_shapes.items():
        path = tmp_path / f"{name}.step"
        scad.export_step(shape, path)
        again = scad.import_step(path)
        assert again.get_volume() == pytest.approx(exchange_reference[name]["volume"], rel=1e-9), name
        assert face_count(again) == exchange_reference[name]["faces"], name


def test_step_export_of_several_shapes_and_unicode_paths(tmp_path):
    directory = tmp_path / "\u6a21\u578b \u00e9"
    directory.mkdir()
    path = directory / "\u90e8\u4ef6.step"
    scad.export_step([_testing.box(1, 2, 3), _testing.cylinder(1, 2)], path)
    assert path.stat().st_size > 1000
    assert scad.import_step(str(path)).get_volume() == pytest.approx(6 + np.pi * 2)
    assert scad.step_bytes(_testing.box(1, 1, 1)).startswith(b"ISO-10303-21;")


def test_step_errors_are_simplecad_errors(tmp_path):
    with pytest.raises(scad.SimpleCADError) as info:
        scad.import_step(tmp_path / "missing.step")
    assert info.value.operation == "import_step"
    (tmp_path / "junk.step").write_text("not a step file")
    with pytest.raises(scad.SimpleCADError):
        scad.import_step(tmp_path / "junk.step")
    with pytest.raises(scad.SimpleCADError) as info:
        scad.export_step([], tmp_path / "x.step")
    assert info.value.operation == "export_step_shapes"
    with pytest.raises(TypeError):
        scad.export_step([42], tmp_path / "x.step")


# ---------------------------------------------------------------------------
# STL / OBJ / GLB
# ---------------------------------------------------------------------------
def test_binary_stl_counts_match_the_reference_exporter(reference_shapes, exchange_reference, tmp_path):
    for name, shape in reference_shapes.items():
        path = tmp_path / f"{name}.stl"
        report = scad.export_stl(shape, path)
        expected = exchange_reference[name]["welded"]
        assert report["triangle_count"] == pytest.approx(expected["triangles"], rel=0.05, abs=2), name
        assert report["vertex_count"] == pytest.approx(expected["vertices"], rel=0.05, abs=2), name
        data = path.read_bytes()
        assert len(data) == 84 + 50 * report["triangle_count"]
        assert struct.unpack_from("<I", data, 80)[0] == report["triangle_count"]
        assert data[:39] == b"SimpleCAD OpenCASCADE BREP tessellation"
        mesh = scad.import_stl(path)
        assert mesh.triangle_count == report["triangle_count"]
        assert mesh.vertex_count == report["vertex_count"]


def test_binary_stl_normals_agree_with_the_triangles(tmp_path):
    path = tmp_path / "c.stl"
    scad.export_stl(_testing.cylinder(5, 10), path)
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    records = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=count, offset=84)
    v = records["v"].astype(np.float64)
    cross = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    cross /= np.linalg.norm(cross, axis=1)[:, None]
    assert np.allclose(cross, records["n"], atol=1e-5)


def test_ascii_stl_facets_match_the_reference_kernel_writer(reference_shapes, exchange_reference, tmp_path):
    for name, shape in reference_shapes.items():
        path = tmp_path / f"{name}_ascii.stl"
        scad.export_stl(shape, path, linear_deflection=0.1, angular_deflection_degrees=0.5 * 180 / np.pi, ascii=True)
        text = path.read_text()
        assert text.startswith("solid")
        assert text.count("facet normal") == pytest.approx(exchange_reference[name]["ascii_stl_facets"], rel=0.05, abs=2), name
        assert scad.import_stl(path).triangle_count == text.count("facet normal")


def test_stl_reimport_as_a_solid(tmp_path):
    path = tmp_path / "b.stl"
    scad.export_stl(_testing.box(10, 20, 30), path)
    solid = scad.import_stl_shape(path)
    assert isinstance(solid, scad.Solid)
    assert solid.get_volume() == pytest.approx(6000.0, rel=1e-6)


def test_obj_export_is_plain_locale_free_text(reference_shapes, exchange_reference, tmp_path):
    path = tmp_path / "m.obj"
    report = scad.export_obj(reference_shapes["cylinder"], path)
    text = path.read_text(encoding="ascii")
    lines = text.splitlines()
    assert lines[0] == "# SimpleCAD OpenCASCADE BREP tessellation"
    assert sum(line.startswith("v ") for line in lines) == report["vertex_count"]
    assert sum(line.startswith("f ") for line in lines) == report["triangle_count"]
    assert "," not in text and "\r" not in text
    indices = [int(i) for line in lines if line.startswith("f ") for i in line.split()[1:]]
    assert min(indices) == 1 and max(indices) == report["vertex_count"]


def test_glb_is_a_valid_gltf_binary(reference_shapes, tmp_path):
    path = tmp_path / "m.glb"
    scad.export_glb(reference_shapes["holed"], path, linear_deflection=0.1)
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    json_length, json_type = struct.unpack_from("<II", data, 12)
    assert json_type == 0x4E4F534A
    document = json.loads(data[20 : 20 + json_length])
    bin_length, bin_type = struct.unpack_from("<II", data, 20 + json_length)
    assert bin_type == 0x004E4942
    assert document["buffers"][0]["byteLength"] == bin_length
    index_accessor, position_accessor, normal_accessor = document["accessors"]
    assert index_accessor["count"] % 3 == 0
    assert position_accessor["count"] == normal_accessor["count"]
    blob = data[28 + json_length :]
    indices = np.frombuffer(blob, dtype="<u4", count=index_accessor["count"])
    assert int(indices.max()) < position_accessor["count"]
    positions = np.frombuffer(blob, dtype="<f4", count=position_accessor["count"] * 3, offset=index_accessor["count"] * 4)
    assert positions.reshape(-1, 3).max(axis=0) == pytest.approx(position_accessor["max"])


# ---------------------------------------------------------------------------
# BREP bytes, interop with OCP
# ---------------------------------------------------------------------------
def test_brep_bytes_are_bintools_v4_without_mesh():
    box = _testing.box(1, 2, 3)
    scad.mesh(box)
    data = box.to_brep()
    assert data.startswith(b"\nOpen CASCADE Topology V4, (c) Open Cascade\n")
    restored = scad.from_brep(data)
    assert isinstance(restored, scad.Solid) and restored.get_volume() == pytest.approx(6.0)
    assert scad.Solid.from_brep(data).get_volume() == pytest.approx(6.0)
    with pytest.raises(ValueError):
        scad.from_brep(b"nonsense")


def test_reference_brep_bytes_load_and_re_encode_identically(exchange_reference):
    for name, record in exchange_reference.items():
        data = base64.b64decode(record["brep_b64"])
        shape = scad.from_brep(data)
        assert shape.get_volume() == pytest.approx(record["volume"], rel=1e-12), name
        # artifacts.brep.write_brep_bytes and our canonical encoding are the same function.
        assert scad.canonical_brep_bytes(shape) == data, name


def test_brep_files_round_trip(tmp_path):
    scad.export_brep(_testing.box(3, 4, 5), tmp_path / "b.brep")
    assert scad.import_brep(tmp_path / "b.brep").get_volume() == pytest.approx(60.0)
    with pytest.raises(scad.SimpleCADError) as info:
        scad.import_brep(tmp_path / "absent.brep")
    assert info.value.operation == "import_brep"
