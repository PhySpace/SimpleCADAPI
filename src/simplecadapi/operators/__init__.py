"""Unified operator exports for the SimpleCAD modeling API.

Implementation modules are organized by capability domain (geometry, features,
booleans, transforms, selection/tagging, sketch, product/assembly). This
package aggregates them into one import surface::

    from simplecadapi.operators import make_box_rsolid, fillet_rsolid

Each implementation module re-exports its shared helpers from ``_support``;
the aggregated ``__all__`` is the union of the implementation ``__all__``s.
Assignments to symbols on this package (e.g. ``mock.patch.object``) are
mirrored into the implementation modules so monkeypatch-based integrations
keep observing the executed binding.
"""

import sys as _sys
from types import ModuleType as _ModuleType

from . import _support, geometry, transform, boolean, product, sketch, selection, features
from ._support import *
from .geometry import *
from .transform import *
from .boolean import *
from .product import *
from .sketch import *
from .selection import *
from .features import *

_IMPLEMENTATION_MODULES = (
    _support,
    geometry,
    transform,
    boolean,
    product,
    sketch,
    selection,
    features,
)

__all__ = tuple(
    dict.fromkeys(
        name
        for module in _IMPLEMENTATION_MODULES
        for name in module.__all__
    )
)

_SYMBOL_MODULES = {
    name: tuple(
        module for module in _IMPLEMENTATION_MODULES if name in vars(module)
    )
    for name in __all__
}


class _OperatorsFacade(_ModuleType):
    def __setattr__(self, name, value):
        for module in self.__dict__.get("_SYMBOL_MODULES", {}).get(name, ()):
            setattr(module, name, value)
        super().__setattr__(name, value)


_sys.modules[__name__].__class__ = _OperatorsFacade
