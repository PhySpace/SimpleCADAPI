"""Regression: repeated native render workers exiting inside the Python extension."""
import numpy as np

from simplecadapi import _cpp as native


def test_repeated_parallel_frames_match_the_serial_buffers():
    scene = native.RenderScene()
    scene.add_mesh_arrays(
        vertices=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
        normals=np.array([[0, 0, 1]] * 3, dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        face_ids=np.array([17], dtype=np.uint32),
    )
    options = dict(
        width=241, height=177, supersample=1,
        views=[(28, -45, "iso"), (90, 0, "top"), (0, 90, "side")],
    )
    serial = native.render_scene(scene, threads=1, **options)
    assert 17 in np.asarray(serial.face_id)
    for _ in range(48):
        parallel = native.render_scene(scene, threads=12, **options)
        for name in ("rgba", "depth", "mesh_id", "face_id"):
            np.testing.assert_array_equal(getattr(parallel, name), getattr(serial, name))
