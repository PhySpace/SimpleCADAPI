"""``simplecadapi.surface``: the C++ module's ``surface`` namespace.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_surface.cpp`` -> ``src/cpp/src/surface``
  * ``bind_surface_editing.cpp`` -> ``src/cpp/src/surface/editing``
"""

from __future__ import annotations

import simplecadapi._cpp as _cpp

_ns = _cpp.surface

# bind_surface_editing.cpp
convert_to_bspline_redge = _ns.convert_to_bspline_redge
convert_to_bspline_rface = _ns.convert_to_bspline_rface
elevate_curve_degree_redge = _ns.elevate_curve_degree_redge
elevate_surface_degree_rface = _ns.elevate_surface_degree_rface
insert_curve_knot_redge = _ns.insert_curve_knot_redge
insert_surface_knot_rface = _ns.insert_surface_knot_rface
inspect_curve_rcurvedata = _ns.inspect_curve_rcurvedata
inspect_surface_rsurfacedata = _ns.inspect_surface_rsurfacedata
move_curve_poles_redge = _ns.move_curve_poles_redge
move_surface_poles_rface = _ns.move_surface_poles_rface
rebuild_curve_redge = _ns.rebuild_curve_redge
rebuild_surface_rface = _ns.rebuild_surface_rface
sample_curve_rcurvature = _ns.sample_curve_rcurvature
sample_surface_risocurves = _ns.sample_surface_risocurves
set_curve_poles_redge = _ns.set_curve_poles_redge
set_curve_weights_redge = _ns.set_curve_weights_redge
set_surface_poles_rface = _ns.set_surface_poles_rface
set_surface_weights_rface = _ns.set_surface_weights_rface
# bind_surface.cpp
SurfaceBoundary = _ns.SurfaceBoundary
SurfaceFillingSettings = _ns.SurfaceFillingSettings
fill_holes_rshell = _ns.fill_holes_rshell
fit_point_grid_rface = _ns.fit_point_grid_rface
free_boundaries_rwirelist = _ns.free_boundaries_rwirelist
loft_rshell = _ns.loft_rshell
make_bezier_surface_rface = _ns.make_bezier_surface_rface
make_cylindrical_surface_rface = _ns.make_cylindrical_surface_rface
make_gordon_surface_rface = _ns.make_gordon_surface_rface
make_ruled_surface_rface = _ns.make_ruled_surface_rface
make_solid_from_shell_rsolid = _ns.make_solid_from_shell_rsolid
make_surface_patch_rface = _ns.make_surface_patch_rface
sew_faces_rshell = _ns.sew_faces_rshell
trim_surface_rface = _ns.trim_surface_rface

__all__ = [
    "SurfaceBoundary",
    "SurfaceFillingSettings",
    "convert_to_bspline_redge",
    "convert_to_bspline_rface",
    "elevate_curve_degree_redge",
    "elevate_surface_degree_rface",
    "fill_holes_rshell",
    "fit_point_grid_rface",
    "free_boundaries_rwirelist",
    "insert_curve_knot_redge",
    "insert_surface_knot_rface",
    "inspect_curve_rcurvedata",
    "inspect_surface_rsurfacedata",
    "loft_rshell",
    "make_bezier_surface_rface",
    "make_cylindrical_surface_rface",
    "make_gordon_surface_rface",
    "make_ruled_surface_rface",
    "make_solid_from_shell_rsolid",
    "make_surface_patch_rface",
    "move_curve_poles_redge",
    "move_surface_poles_rface",
    "rebuild_curve_redge",
    "rebuild_surface_rface",
    "sample_curve_rcurvature",
    "sample_surface_risocurves",
    "set_curve_poles_redge",
    "set_curve_weights_redge",
    "set_surface_poles_rface",
    "set_surface_weights_rface",
    "sew_faces_rshell",
    "trim_surface_rface",
]
