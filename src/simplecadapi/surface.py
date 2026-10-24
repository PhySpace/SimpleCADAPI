"""``simplecadapi.surface``: the C++ module's ``surface`` namespace.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_surface.cpp`` -> ``src/cpp/src/surface``
"""

from __future__ import annotations

import simplecadapi._cpp as _cpp

_ns = _cpp.surface

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
    "fill_holes_rshell",
    "fit_point_grid_rface",
    "free_boundaries_rwirelist",
    "loft_rshell",
    "make_bezier_surface_rface",
    "make_cylindrical_surface_rface",
    "make_gordon_surface_rface",
    "make_ruled_surface_rface",
    "make_solid_from_shell_rsolid",
    "make_surface_patch_rface",
    "sew_faces_rshell",
    "trim_surface_rface",
]
