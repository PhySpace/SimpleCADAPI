"""Verifier scripts: hand SDK shapes to OCP and take OCP shapes back.

The SDK computes on its own compiled OpenCASCADE (``simplecadapi._cpp``) and does not need OCP.  A verifier script that
measures a model with the full OCCT toolbox (mass properties, point classification, distances, Boolean overlap, ...)
is easier to write against OCP, whose API every OCCT reference documents.  Install it with the ``verify`` extra::

    pip install "simplecadapi[verify]"

``shape.wrapped`` is **not** an OCP object: it is the SDK's own binding, and OCP functions reject it with
``incompatible function arguments``.  Convert instead::

    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from simplecadapi.verify import to_ocp

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(to_ocp(solid), props)      # not solid.wrapped
    print(props.Mass())

The conversion goes through OpenCASCADE's binary format (geometry only, bit-exact doubles, a few milliseconds for a
part), so it copies: changes made to the OCP shape do not reach the SDK shape; use ``from_ocp`` to bring a result back.
Tags and tracking history stay with the SDK shape.
"""

from __future__ import annotations

import io
from typing import Any

import simplecadapi._cpp as _cpp

__all__ = ["to_ocp", "from_ocp", "ocp_available"]

_INSTALL_HINT = (
    'OCP is not installed.  Verifier scripts that use OCP need the optional extra: pip install "simplecadapi[verify]" '
    "(the SDK itself does not use OCP)."
)


def ocp_available() -> bool:
    """True when OCP can be imported."""

    try:
        import OCP  # noqa: F401
    except ImportError:
        return False
    return True


def _require_ocp() -> None:
    try:
        import OCP  # noqa: F401
    except ImportError as error:
        raise ImportError(_INSTALL_HINT) from error


def to_ocp(shape: Any) -> Any:
    """The OCP ``TopoDS_Shape`` of an SDK shape (a copy).

    Down-cast it when a function wants the concrete type: ``TopoDS.Solid_s(to_ocp(solid))``.
    """

    _require_ocp()
    from OCP.BinTools import BinTools
    from OCP.TopoDS import TopoDS_Shape

    if not hasattr(shape, "to_brep"):
        raise TypeError(
            f"to_ocp expects an SDK shape (Solid, Face, Wire, Edge, Vertex, Compound, ...), got {type(shape).__name__}; "
            "an OCP shape is already one"
        )
    result = TopoDS_Shape()
    BinTools.Read_s(result, io.BytesIO(shape.to_brep()))
    return result


def from_ocp(shape: Any) -> Any:
    """The SDK shape (``Solid``, ``Face``, ... as the content says) of an OCP ``TopoDS_Shape`` (a copy)."""

    _require_ocp()
    from OCP.BinTools import BinTools

    if hasattr(shape, "to_brep"):
        raise TypeError("from_ocp expects an OCP TopoDS_Shape, got an SDK shape")
    buffer = io.BytesIO()
    BinTools.Write_s(shape, buffer)
    return _cpp.from_brep(buffer.getvalue())
