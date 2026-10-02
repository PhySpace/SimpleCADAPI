from __future__ import annotations

import simplecadapi as scad
from simplecadapi.artifacts.brep import read_brep_solid, write_brep_bytes


def test_geometry_interface_hash_is_independent_of_brep_bytes_and_build_identity():
    first = scad.make_box_rsolid(width=2.0, height=3.0, depth=4.0)
    independently_built = scad.make_box_rsolid(width=2.0, height=3.0, depth=4.0)
    round_tripped = read_brep_solid(write_brep_bytes(first))
    changed = scad.make_box_rsolid(width=2.1, height=3.0, depth=4.0)

    first_interface = scad.geometry_interface_fingerprint(first)

    assert first_interface == scad.geometry_interface_fingerprint(independently_built)
    assert first_interface == scad.geometry_interface_fingerprint(round_tripped)
    assert first_interface != scad.geometry_interface_fingerprint(changed)
    assert first_interface != "sha256:" + write_brep_bytes(first).hex()[:64]

    descriptor = scad.geometry_interface_descriptor(first)
    assert descriptor["body_count"] == 1
    assert descriptor["face_count"] == 6
    assert descriptor["edge_count"] == 12
    assert descriptor["vertex_count"] == 8
