"""The ``.wrapped`` view of a native shape.

``shape.wrapped`` is the OpenCASCADE shape a native shape stands for, and which OpenCASCADE that is depends on what is
installed.  With OCP importable (the ``verify`` extra) it is an **OCP** ``TopoDS_Shape``: the object every OCCT reference,
CadQuery and an agent's habits expect, so ``BRepGProp.VolumeProperties_s(solid.wrapped, props)`` works as written.  It is a
copy made through OpenCASCADE's binary format (milliseconds for a part): changing it does not change the SDK shape.
Without OCP it is the OCCT shape of ``simplecadapi._cpp.occt`` (the same OpenCASCADE the SDK computes with, nothing
copied), which is what the SDK's own Python layers (inspect, drawings, translators, scene meshing) work on: they take
``shape._native_wrapped``, which is always that one.

``SCA_WRAPPED=native`` or ``SCA_WRAPPED=ocp`` chooses.  The SDK functions that take a raw shape (the ``inspect.brep``
queries, the STEP export) accept either; ``from_occt`` is the way back for a shape made with either.
"""

from __future__ import annotations

import functools
import io
import os
from typing import Any, Callable

_SHAPE_CLASSES: tuple[Any, ...] = ()
_ocp_present: bool | None = None


def ocp_available() -> bool:
    """Whether OCP can be imported (looked up once)."""

    global _ocp_present
    if _ocp_present is None:
        try:
            import OCP  # noqa: F401
        except ImportError:
            _ocp_present = False
        else:
            _ocp_present = True
    return _ocp_present


def wrapped_mode() -> str:
    """``"ocp"`` or ``"native"``: what ``.wrapped`` returns now (``SCA_WRAPPED`` first, else OCP when it is installed)."""

    forced = os.environ.get("SCA_WRAPPED", "").strip().lower()
    if forced in ("native", "ocp"):
        return forced
    return "ocp" if ocp_available() else "native"


def is_ocp_shape(value: Any) -> bool:
    """Whether *value* is an OCP ``TopoDS_Shape`` (any subclass)."""

    return type(value).__module__.startswith("OCP") and hasattr(value, "ShapeType")


def ocp_to_native(shape: Any) -> Any:
    """The SDK shape of an OCP shape (a copy, through BinTools)."""

    from OCP.BinTools import BinTools

    import simplecadapi._cpp as n

    buffer = io.BytesIO()
    BinTools.Write_s(shape, buffer)
    return n.from_brep(buffer.getvalue())


def native_occt(value: Any) -> Any:
    """*value* as the OCCT shape the SDK's Python layers work on: an OCP shape is converted, anything else is kept."""

    if is_ocp_shape(value):
        return ocp_to_native(value)._native_wrapped
    return value


def from_occt(shape: Any) -> Any:
    """The native shape of an OCCT shape (an OCP shape or one of ``simplecadapi._cpp.occt``)."""

    import simplecadapi._cpp as n

    if is_ocp_shape(shape):
        return ocp_to_native(shape)
    return n._from_occt(shape)


def accepts_ocp(function: Callable[..., Any]) -> Callable[..., Any]:
    """*function* taking OCP shapes where it takes OCCT shapes (a shape, or a list or tuple of them)."""

    def convert(value: Any) -> Any:
        if is_ocp_shape(value):
            return native_occt(value)
        if isinstance(value, (list, tuple)) and any(is_ocp_shape(item) for item in value):
            return type(value)(native_occt(item) for item in value)
        return value

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return function(*(convert(arg) for arg in args), **{key: convert(value) for key, value in kwargs.items()})

    return wrapper


def accepting_ocp(namespace: dict[str, Any], names: Any = None, *, reexported: bool = False) -> None:
    """Make the public functions of a module (its globals) take OCP shapes: ``accepting_ocp(globals())``.

    Only functions defined in the module are wrapped (not what it imports), unless *reexported*: a package that
    re-exports the functions of its submodules wraps its own names for them.
    """

    module = namespace.get("__name__")
    for name in list(names if names is not None else namespace.get("__all__") or namespace):
        function = namespace.get(name)
        if name.startswith("_") or not callable(function):
            continue
        if not reexported and getattr(function, "__module__", None) != module:
            continue
        if isinstance(function, type) or not hasattr(function, "__code__"):
            continue
        namespace[name] = accepts_ocp(function)


def native_to_ocp(shape: Any) -> Any:
    """The OCP ``TopoDS_Shape`` of an SDK shape (a copy, through BinTools)."""

    from OCP.BinTools import BinTools
    from OCP.TopoDS import TopoDS_Shape

    if not hasattr(shape, "to_brep"):
        raise TypeError(
            f"expected an SDK shape (Solid, Face, Wire, Edge, Vertex, Compound, ...), got {type(shape).__name__}; "
            "an OCP shape is already one"
        )
    result = TopoDS_Shape()
    BinTools.Read_s(result, io.BytesIO(shape.to_brep()))
    return _concrete(result)


def _concrete(shape: Any) -> Any:
    """*shape* as the class of its kind (``TopoDS_Edge``, ``TopoDS_Solid``, ...), as CadQuery's ``wrapped`` is.

    OCP's functions take the concrete class where they mean one (``BRepAdaptor_Curve(edge)``), and BinTools reads a
    generic ``TopoDS_Shape``.
    """

    from OCP.TopAbs import TopAbs_ShapeEnum as kind
    from OCP.TopoDS import TopoDS

    casts = {
        kind.TopAbs_COMPOUND: TopoDS.Compound_s,
        kind.TopAbs_COMPSOLID: TopoDS.CompSolid_s,
        kind.TopAbs_SOLID: TopoDS.Solid_s,
        kind.TopAbs_SHELL: TopoDS.Shell_s,
        kind.TopAbs_FACE: TopoDS.Face_s,
        kind.TopAbs_WIRE: TopoDS.Wire_s,
        kind.TopAbs_EDGE: TopoDS.Edge_s,
        kind.TopAbs_VERTEX: TopoDS.Vertex_s,
    }
    cast = casts.get(shape.ShapeType())
    return cast(shape) if cast is not None else shape


_to_ocp = native_to_ocp


def install(nat: Any) -> None:
    """Make ``wrapped`` follow :func:`wrapped_mode` on every shape class; ``_native_wrapped`` stays the SDK's own view."""

    global _SHAPE_CLASSES
    classes = []
    for name in dir(nat):
        cls = getattr(nat, name)
        if isinstance(cls, type) and "wrapped" in cls.__dict__ and "_native_wrapped" not in cls.__dict__:
            classes.append(cls)
    for cls in classes:
        native = cls.__dict__["wrapped"]
        cls._native_wrapped = native

        def wrapped(self: Any, _native: Any = native) -> Any:
            if wrapped_mode() == "ocp":
                return _to_ocp(self)
            return _native.fget(self)

        wrapped.__doc__ = (
            "The OpenCASCADE shape of this shape: an OCP ``TopoDS_Shape`` (a copy) when OCP is installed, else the "
            "OCCT shape of ``simplecadapi._cpp.occt``. See simplecadapi._glue.bridge."
        )
        cls.wrapped = property(wrapped)
    _SHAPE_CLASSES = tuple(classes)
