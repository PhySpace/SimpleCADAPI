"""Vector-PDF engineering-drawing inspection utilities.

Diagnostic evidence extraction for 2D engineering-drawing documents. These
functions are analysis tools, not modeling operations: they do not record
graph nodes and are not supported inside replayable modeling scripts. Import
the namespace as ``simplecadapi.inspect.drawing``.

PDF text, vectors and crop rectangles use page display coordinates in pt.
Rendered pixels use px via the sidecar transforms; model sections use local
plane coordinates in mm. Source identities and coordinate preflight precede
measurement claims. Rendering caller data is not proof of its correctness.
"""

from .calibrate import (
    DrawingCalibration,
    DrawingMeasurements,
    calibrate_drawing_scale_rcalibration,
    measure_drawing_rmeasurements,
)
from .geometry import DrawingStrokes, extract_drawing_primitives_rstrokes
from .render import render_drawing_view_rpath
from .section import (
    DrawingSectionDimensions,
    measure_model_section_rdimensions,
    render_model_section_rpath,
)
from .summary import DrawingSummary, inspect_drawing_rsummary
from .text import DrawingText, extract_drawing_text_rwords
from .preflight import inspect_drawing_coordinates_rreport
from .evidence import (
    assess_dimension_rverdict,
    build_section_annotation_rrecord,
    summarize_dimension_coverage_rreport,
    validate_section_annotations_rreport,
)

__all__ = [
    "DrawingCalibration",
    "DrawingMeasurements",
    "DrawingStrokes",
    "DrawingSectionDimensions",
    "DrawingSummary",
    "DrawingText",
    "calibrate_drawing_scale_rcalibration",
    "extract_drawing_primitives_rstrokes",
    "extract_drawing_text_rwords",
    "inspect_drawing_rsummary",
    "measure_drawing_rmeasurements",
    "measure_model_section_rdimensions",
    "render_drawing_view_rpath",
    "render_model_section_rpath",
    "inspect_drawing_coordinates_rreport",
    "assess_dimension_rverdict",
    "build_section_annotation_rrecord",
    "summarize_dimension_coverage_rreport",
    "validate_section_annotations_rreport",
]


# Match the diagnostic-only boundary enforced by inspect.brep, including
# imports through the defining submodules.
from functools import wraps as _wraps
from inspect import isfunction as _isfunction
import sys as _sys
from simplecadapi._cpp import get_active_session as _get_active_session


def _outside_model_graph(function):
    @_wraps(function)
    def checked(*args, **kwargs):
        if _get_active_session() is not None:
            raise RuntimeError(
                "drawing inspection cannot run inside an active GraphSession"
            )
        return function(*args, **kwargs)

    return checked


for _name in __all__:
    _function = globals()[_name]
    if _isfunction(_function):
        globals()[_name] = _outside_model_graph(_function)
        setattr(_sys.modules[_function.__module__], _name, globals()[_name])
del _name, _function, _isfunction, _outside_model_graph
