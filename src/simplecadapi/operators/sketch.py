"""Operators of the ``sketch`` group.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_sketch.cpp`` -> ``src/cpp/src/sketch``

Names that carry Python-side behaviour (recording wrappers, typing aliases) come from
``simplecadapi/_native/glue.py``.
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_sketch.cpp
    add_arc_rsketch,
    add_bspline_rsketch,
    add_circle_rsketch,
    add_ellipse_rsketch,
    add_line_rsketch,
    add_point_rsketch,
    constrain_midpoint_points_rsketch,
    constrain_mirror_rsketch,
    constrain_symmetric_rsketch,
    constrain_tangent_rsketch,
    get_sketch_entity_rsketchref,
    get_sketch_point_rsketchref,
    inspect_sketch_rsketchresult,
    make_face_from_sketch_rface,
    make_sketch_rsketch,
    make_wire_from_sketch_rwire,
    # (defined by the module itself)
    constrain_angle_rsketch,
    constrain_coincident_rsketch,
    constrain_collinear_rsketch,
    constrain_concentric_rsketch,
    constrain_connect_rsketch,
    constrain_diameter_rsketch,
    constrain_distance_rsketch,
    constrain_distance_x_rsketch,
    constrain_distance_y_rsketch,
    constrain_equal_length_rsketch,
    constrain_equal_radius_rsketch,
    constrain_fix_rsketch,
    constrain_horizontal_rsketch,
    constrain_length_rsketch,
    constrain_line_distance_rsketch,
    constrain_major_radius_rsketch,
    constrain_midpoint_rsketch,
    constrain_minor_radius_rsketch,
    constrain_normal_rsketch,
    constrain_parallel_rsketch,
    constrain_perpendicular_rsketch,
    constrain_point_on_rsketch,
    constrain_points_horizontal_rsketch,
    constrain_points_vertical_rsketch,
    constrain_radius_rsketch,
    constrain_vertical_rsketch,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

_assert_sketch_solve_snapshot_dict_matches = _glue._assert_sketch_solve_snapshot_dict_matches
_constrain_rsketch = _glue._constrain_rsketch

__all__ = [
    "add_arc_rsketch",
    "add_bspline_rsketch",
    "add_circle_rsketch",
    "add_ellipse_rsketch",
    "add_line_rsketch",
    "add_point_rsketch",
    "constrain_angle_rsketch",
    "constrain_coincident_rsketch",
    "constrain_collinear_rsketch",
    "constrain_concentric_rsketch",
    "constrain_connect_rsketch",
    "constrain_diameter_rsketch",
    "constrain_distance_rsketch",
    "constrain_distance_x_rsketch",
    "constrain_distance_y_rsketch",
    "constrain_equal_length_rsketch",
    "constrain_equal_radius_rsketch",
    "constrain_fix_rsketch",
    "constrain_horizontal_rsketch",
    "constrain_length_rsketch",
    "constrain_line_distance_rsketch",
    "constrain_major_radius_rsketch",
    "constrain_midpoint_points_rsketch",
    "constrain_midpoint_rsketch",
    "constrain_minor_radius_rsketch",
    "constrain_mirror_rsketch",
    "constrain_normal_rsketch",
    "constrain_parallel_rsketch",
    "constrain_perpendicular_rsketch",
    "constrain_point_on_rsketch",
    "constrain_points_horizontal_rsketch",
    "constrain_points_vertical_rsketch",
    "constrain_radius_rsketch",
    "constrain_symmetric_rsketch",
    "constrain_tangent_rsketch",
    "constrain_vertical_rsketch",
    "get_sketch_entity_rsketchref",
    "get_sketch_point_rsketchref",
    "inspect_sketch_rsketchresult",
    "make_face_from_sketch_rface",
    "make_sketch_rsketch",
    "make_wire_from_sketch_rwire",
]
