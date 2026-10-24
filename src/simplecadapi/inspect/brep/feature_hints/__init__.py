"""Private geometric feature recognizers used by the v2 feature catalog."""

from .extrusions import extrusion_hints
from .holes import hole_hints
from .lofts import loft_hints
from .revolutions import revolution_hints
from .sweeps import sweep_hints

__all__ = [
    "extrusion_hints",
    "hole_hints",
    "loft_hints",
    "revolution_hints",
    "sweep_hints",
]
