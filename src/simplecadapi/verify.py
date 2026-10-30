"""Verifier scripts: hand SDK shapes to OCP and take OCP shapes back.

The SDK computes on its own compiled OpenCASCADE (``simplecadapi._cpp``) and does not need OCP.  A verifier script that
measures a model with the full OCCT toolbox (mass properties, point classification, distances, Boolean overlap, ...)
is easier to write against OCP, whose API every OCCT reference documents.  Install it with the ``verify`` extra::

    pip install "simplecadapi[verify]"

With OCP installed ``shape.wrapped`` is an OCP shape of its own kind (``TopoDS_Solid``, ...) made through the same
conversion, so OCP functions take it as written; ``to_ocp`` is the explicit form (it returns the generic
``TopoDS_Shape``)::

    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from simplecadapi.verify import to_ocp

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(to_ocp(solid), props)      # or solid.wrapped
    print(props.Mass())

The conversion goes through OpenCASCADE's binary format (geometry only, bit-exact doubles, a few milliseconds for a
part), so it copies: changes made to the OCP shape do not reach the SDK shape; use ``from_ocp`` to bring a result back.
Tags and tracking history stay with the SDK shape.
"""

from __future__ import annotations

from typing import Any

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
    from simplecadapi._glue import bridge

    if not hasattr(shape, "to_brep"):
        raise TypeError(
            f"to_ocp expects an SDK shape (Solid, Face, Wire, Edge, Vertex, Compound, ...), got {type(shape).__name__}; "
            "an OCP shape is already one"
        )
    return bridge.native_to_ocp(shape)


def from_ocp(shape: Any) -> Any:
    """The SDK shape (``Solid``, ``Face``, ... as the content says) of an OCP ``TopoDS_Shape`` (a copy)."""

    _require_ocp()
    from simplecadapi._glue import bridge

    if hasattr(shape, "to_brep"):
        raise TypeError("from_ocp expects an OCP TopoDS_Shape, got an SDK shape")
    return bridge.ocp_to_native(shape)
