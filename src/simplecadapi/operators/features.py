"""Operators of the ``features`` group.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_ops_features.cpp`` -> ``src/cpp/src/ops/features``
  * ``bind_ops_geometry.cpp`` -> ``src/cpp/src/ops/geometry``

Names that carry Python-side behaviour (recording wrappers, typing aliases) come from
``simplecadapi/_native/glue.py``.
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_ops_features.cpp
    assert_blend_volume_monotonic,
    chamfer_rsolid,
    diagnose_blend_failure,
    draft_rsolid,
    extrude_rsolid,
    extrude_taper_rsolid,
    extrude_until_rsolid,
    fillet_rsolid,
    helical_sweep_rsolid,
    loft_rsolid,
    offset_rsolid,
    raise_loft_failure_if_diagnosed,
    revolve_rsolid,
    shell_rsolid,
    sweep_multisection_rsolid,
    sweep_rsolid,
    twisted_sweep_rsolid,
    # bind_ops_geometry.cpp
    make_face_from_wire_rface,
    make_helix_rwire,
    # (defined by the module itself)
    BlendDiagnosis,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

SCREENSHOT_VIEWS = _glue.SCREENSHOT_VIEWS
_execute_screenshot_render = _glue._execute_screenshot_render
_prepare_screenshot_render = _glue._prepare_screenshot_render
_screenshot_views = _glue._screenshot_views
render_screenshot_rpath = _glue.render_screenshot_rpath

__all__ = [
    "BlendDiagnosis",
    "SCREENSHOT_VIEWS",
    "assert_blend_volume_monotonic",
    "chamfer_rsolid",
    "diagnose_blend_failure",
    "draft_rsolid",
    "extrude_rsolid",
    "extrude_taper_rsolid",
    "extrude_until_rsolid",
    "fillet_rsolid",
    "helical_sweep_rsolid",
    "loft_rsolid",
    "make_face_from_wire_rface",
    "make_helix_rwire",
    "offset_rsolid",
    "raise_loft_failure_if_diagnosed",
    "render_screenshot_rpath",
    "revolve_rsolid",
    "shell_rsolid",
    "sweep_multisection_rsolid",
    "sweep_rsolid",
    "twisted_sweep_rsolid",
]
