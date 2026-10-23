"""``simplecadapi.std.gear``: the C++ module's ``std.gear`` namespace.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_std.cpp`` -> ``src/cpp/src/std``
"""

from __future__ import annotations

import simplecadapi._cpp as _cpp

_ns = _cpp.std.gear

# bind_std.cpp
_build_gear_profile_face = _ns._build_gear_profile_face
_build_internal_gear_profile_wire = _ns._build_internal_gear_profile_wire
_build_ring_gear_face = _ns._build_ring_gear_face
_compute_internal_tooth_geometry = _ns._compute_internal_tooth_geometry
_compute_tooth_geometry = _ns._compute_tooth_geometry
_internal_ring_radii = _ns._internal_ring_radii
_involute_point = _ns._involute_point
_involute_t_for_radius = _ns._involute_t_for_radius
_root_fillet_control_points = _ns._root_fillet_control_points
_rotate_xy = _ns._rotate_xy
make_cycloidal_disc_rsolid = _ns.make_cycloidal_disc_rsolid
make_helical_gear_rsolid = _ns.make_helical_gear_rsolid
make_helical_rack_rsolid = _ns.make_helical_rack_rsolid
make_helical_ring_gear_rsolid = _ns.make_helical_ring_gear_rsolid
make_herringbone_gear_rsolid = _ns.make_herringbone_gear_rsolid
make_herringbone_rack_rsolid = _ns.make_herringbone_rack_rsolid
make_herringbone_ring_gear_rsolid = _ns.make_herringbone_ring_gear_rsolid
make_spur_gear_rsolid = _ns.make_spur_gear_rsolid
make_spur_rack_rsolid = _ns.make_spur_rack_rsolid
make_spur_ring_gear_rsolid = _ns.make_spur_ring_gear_rsolid
make_straight_bevel_gear_rsolid = _ns.make_straight_bevel_gear_rsolid

__all__ = [
    "make_cycloidal_disc_rsolid",
    "make_helical_gear_rsolid",
    "make_helical_rack_rsolid",
    "make_helical_ring_gear_rsolid",
    "make_herringbone_gear_rsolid",
    "make_herringbone_rack_rsolid",
    "make_herringbone_ring_gear_rsolid",
    "make_spur_gear_rsolid",
    "make_spur_rack_rsolid",
    "make_spur_ring_gear_rsolid",
    "make_straight_bevel_gear_rsolid",
]
