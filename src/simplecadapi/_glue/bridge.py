"""The ``.wrapped`` view of a native shape.

A native shape's ``wrapped`` is the OpenCASCADE shape (``TopoDS_Solid``, ...) it stands for, as the class of
``simplecadapi._cpp.occt``: the same OpenCASCADE, so nothing is copied or serialised.  The layers that stay Python
(inspect, drawings, translators, scene meshing) take their OCCT view of a shape through it; ``from_occt`` is the
way back for a shape they made (a STEP read, a decoded BREP).
"""

from __future__ import annotations

from typing import Any


def from_occt(shape: Any) -> Any:
    """The native shape of an OCCT shape."""

    import simplecadapi._cpp as n

    return n._from_occt(shape)


def install(nat: Any) -> None:
    """Nothing to install: ``wrapped`` is a property of the C++ shape classes."""
