"""Tessellation: numpy views, parity with the reference SDK's meshes, thread safety."""

import gc
import threading

import numpy as np
import pytest

import simplecadapi._cpp as scad
from simplecadapi._cpp import _native, _testing
from test_io_support import exchange_reference, reference_shapes  # noqa: F401  (fixtures)

internal_mesh = _native._internal_mesh


def signed_volume(mesh):
    v = mesh.vertices.astype(np.float64)
    t = mesh.triangles
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def test_mesh_arrays_have_the_documented_dtypes_and_shapes():
    box = _testing.box(10, 20, 30)
    mesh = scad.mesh(box)
    assert mesh.vertices.dtype == np.float32 and mesh.vertices.shape == (24, 3)
    assert mesh.normals.dtype == np.float32 and mesh.normals.shape == (24, 3)
    assert mesh.triangles.dtype == np.uint32 and mesh.triangles.shape == (12, 3)
    assert mesh.face_ids.dtype == np.uint32 and mesh.face_ids.shape == (12,)
    assert mesh.face_ranges.shape == (6, 3)
    assert mesh.vertex_count == 24 and mesh.triangle_count == 12
    assert mesh.bounds == ((0.0, 0.0, 0.0), (10.0, 20.0, 30.0))
    assert sorted(set(mesh.face_ids.tolist())) == list(range(6))
    assert int(mesh.triangles.max()) < mesh.vertex_count
    assert np.allclose(np.linalg.norm(mesh.normals, axis=1), 1.0, atol=1e-5)


def test_mesh_arrays_are_zero_copy_read_only_views_that_keep_the_mesh_alive():
    mesh = scad.mesh(_testing.box(1, 2, 3))
    first = mesh.vertices
    assert first.__array_interface__["data"][0] == mesh.vertices.__array_interface__["data"][0]
    assert not first.flags.writeable
    with pytest.raises(ValueError):
        first[0, 0] = 1.0
    keep = mesh.triangles
    expected = keep.copy()
    del mesh
    gc.collect()
    assert np.array_equal(keep, expected)  # the view owns a reference to its mesh


def test_mesh_triangles_wind_outward_and_normals_agree():
    for shape in (_testing.box(10, 20, 30), _testing.cylinder(5, 10)):
        mesh = scad.mesh(shape)
        assert signed_volume(mesh) > 0
        v = mesh.vertices.astype(np.float64)
        t = mesh.triangles
        flat = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
        flat /= np.linalg.norm(flat, axis=1)[:, None]
        corner = mesh.normals[t[:, 0]]
        assert np.all(np.einsum("ij,ij->i", flat, corner) > 0.5)


def test_mesh_volume_converges_with_deflection():
    cylinder = _testing.cylinder(5, 10)
    exact = np.pi * 25 * 10
    coarse = signed_volume(scad.mesh(cylinder, 1.0, 0.8))
    fine = signed_volume(scad.mesh(cylinder, 0.001, 0.05))
    assert abs(fine - exact) < abs(coarse - exact)
    assert fine == pytest.approx(exact, rel=1e-3)


def test_mesh_parameters_are_validated():
    box = _testing.box(1, 1, 1)
    with pytest.raises(ValueError, match="linear_deflection"):
        scad.mesh(box, linear_deflection=0)
    with pytest.raises(ValueError, match="angular_deflection"):
        scad.mesh(box, angular_deflection=float("nan"))
    with pytest.raises(TypeError):
        scad.mesh("not a shape")


def test_meshing_leaves_the_input_untouched():
    cylinder = _testing.cylinder(5, 10)
    before = cylinder.to_brep()
    scad.mesh(cylinder, 0.01, 0.1)
    assert cylinder.to_brep() == before


def test_triangle_counts_match_the_reference_sdk(reference_shapes, exchange_reference):
    for name, shape in reference_shapes.items():
        expected = exchange_reference[name]["trimesh"]
        mesh = internal_mesh.cached_mesh(shape)
        assert mesh is not None, name
        assert mesh.triangle_count == pytest.approx(expected["triangles"], rel=0.05, abs=2), name
        assert mesh.vertex_count == pytest.approx(expected["vertices"], rel=0.05, abs=2), name
        lower, upper = mesh.bounds
        assert lower == pytest.approx(expected["bounds"][0], abs=1e-6), name
        assert upper == pytest.approx(expected["bounds"][1], abs=1e-6), name
        assert mesh.corner_normals.shape == (mesh.triangle_count, 3, 3)
        assert sum(r.count for r in mesh.face_triangle_ranges) == mesh.triangle_count
        assert [r.face_index for r in mesh.face_triangle_ranges] == list(range(len(mesh.face_triangle_ranges)))


def test_whole_shape_mesh_agrees_with_the_per_face_mesh_in_size(reference_shapes):
    for name, shape in reference_shapes.items():
        per_face = internal_mesh.cached_mesh(shape)
        whole = scad.mesh(shape)
        assert whole.triangle_count == pytest.approx(per_face.triangle_count, rel=0.1, abs=2), name


def test_mesh_volume_matches_the_reference_volume(reference_shapes, exchange_reference):
    for name, shape in reference_shapes.items():
        mesh = scad.mesh(shape, 0.01, 0.05)
        assert signed_volume(mesh) == pytest.approx(exchange_reference[name]["volume"], rel=2e-3), name


def test_cached_mesh_is_cached_and_reports_errors():
    box = _testing.box(1, 2, 3)
    first = internal_mesh.cached_mesh(box)
    assert internal_mesh.cached_mesh(box) is first
    assert internal_mesh.mesh_error(box) is None
    assert internal_mesh.cached_mesh(box, linear_tolerance=0.1) is not first
    assert internal_mesh.cached_mesh(box, linear_tolerance=-1.0) is None
    assert internal_mesh.mesh_error(box)
    assert internal_mesh.DEFAULT_LINEAR_TOLERANCE == 0.35
    assert internal_mesh.DEFAULT_ANGULAR_TOLERANCE == 0.22


def test_meshing_runs_concurrently_without_the_gil():
    cylinder = _testing.cylinder(5, 10)
    expected = scad.mesh(cylinder, 0.05, 0.1).triangle_count
    results = []

    def work():
        results.append(scad.mesh(cylinder, 0.05, 0.1).triangle_count)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [expected] * 8
