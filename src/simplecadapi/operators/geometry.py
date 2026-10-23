"""Operators of the ``geometry`` group.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_ops_features.cpp`` -> ``src/cpp/src/ops/features``
  * ``bind_ops_geometry.cpp`` -> ``src/cpp/src/ops/geometry``
  * ``bind_surface.cpp`` -> ``src/cpp/src/surface``

Names that carry Python-side behaviour (recording wrappers, typing aliases) come from
``simplecadapi/_native/glue.py``.
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_ops_features.cpp
    raise_loft_failure_if_diagnosed,
    # bind_ops_geometry.cpp
    load_brep_region_rshell,
    load_brep_region_rsolid,
    make_angle_arc_redge,
    make_angle_arc_rwire,
    make_box_rsolid,
    make_circle_redge,
    make_circle_rface,
    make_circle_rwire,
    make_cone_rsolid,
    make_cylinder_rsolid,
    make_ellipse_redge,
    make_ellipse_rface,
    make_ellipse_rwire,
    make_face_from_wire_rface,
    make_face_from_wires_rface,
    make_helix_redge,
    make_helix_rwire,
    make_interpolated_spline_redge,
    make_interpolated_spline_rwire,
    make_line_redge,
    make_periodic_spline_rwire,
    make_point_rvertex,
    make_polyline_rwire,
    make_rectangle_rface,
    make_rectangle_rwire,
    make_segment_redge,
    make_segment_rwire,
    make_sphere_rsolid,
    make_spline_redge,
    make_spline_rwire,
    make_three_point_arc_redge,
    make_three_point_arc_rwire,
    make_wire_from_edges_rwire,
    # bind_surface.cpp
    SurfaceBoundary,
    SurfaceFillingSettings,
    fill_holes_rshell,
    fit_point_grid_rface,
    free_boundaries_rwirelist,
    loft_rshell,
    make_bezier_surface_rface,
    make_cylindrical_surface_rface,
    make_gordon_surface_rface,
    make_ruled_surface_rface,
    make_solid_from_shell_rsolid,
    make_surface_patch_rface,
    sew_faces_rshell,
    trim_surface_rface,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

_brep_region_path = _glue._brep_region_path
_load_brep_region_rshape = _glue._load_brep_region_rshape

__all__ = [
    "SurfaceBoundary",
    "SurfaceFillingSettings",
    "fill_holes_rshell",
    "fit_point_grid_rface",
    "free_boundaries_rwirelist",
    "load_brep_region_rshell",
    "load_brep_region_rsolid",
    "loft_rshell",
    "make_angle_arc_redge",
    "make_angle_arc_rwire",
    "make_bezier_surface_rface",
    "make_box_rsolid",
    "make_circle_redge",
    "make_circle_rface",
    "make_circle_rwire",
    "make_cone_rsolid",
    "make_cylinder_rsolid",
    "make_cylindrical_surface_rface",
    "make_ellipse_redge",
    "make_ellipse_rface",
    "make_ellipse_rwire",
    "make_face_from_wire_rface",
    "make_face_from_wires_rface",
    "make_gordon_surface_rface",
    "make_helix_redge",
    "make_helix_rwire",
    "make_interpolated_spline_redge",
    "make_interpolated_spline_rwire",
    "make_line_redge",
    "make_periodic_spline_rwire",
    "make_point_rvertex",
    "make_polyline_rwire",
    "make_rectangle_rface",
    "make_rectangle_rwire",
    "make_ruled_surface_rface",
    "make_segment_redge",
    "make_segment_rwire",
    "make_solid_from_shell_rsolid",
    "make_sphere_rsolid",
    "make_spline_redge",
    "make_spline_rwire",
    "make_surface_patch_rface",
    "make_three_point_arc_redge",
    "make_three_point_arc_rwire",
    "make_wire_from_edges_rwire",
    "raise_loft_failure_if_diagnosed",
    "sew_faces_rshell",
    "trim_surface_rface",
]
