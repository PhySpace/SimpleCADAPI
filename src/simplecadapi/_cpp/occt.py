"""The OCCT classes the kept Python layers use, laid out like the ``OCP`` package.

``from simplecadapi._cpp.occt.TopoDS import TopoDS_Shape`` is ``from OCP.TopoDS import TopoDS_Shape`` on the OpenCASCADE
this module carries (no second OCCT, no cadquery-ocp).  Which names exist is what the SDK's Python layers and their tests
call: see ``bindings/python/occt/occt.hpp``.  The module layout (`_occt_layout.json`) is
a committed table (name -> the module of the same name in the OCP layout it mirrors); add a name there when a class is bound.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import json
import sys
import types
from pathlib import Path

from . import _native

_flat = _native._occt
__version__ = _flat.OCC_VERSION_COMPLETE  # the OpenCASCADE this module carries
_layout = json.loads((Path(__file__).with_name("_occt_layout.json")).read_text(encoding="utf-8"))
_by_module: dict = {}
for _name, _module in _layout.items():
    _by_module.setdefault(_module, []).append(_name)

__path__: list = []  # a package for the import system: the finder below makes its submodules


class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    prefix = __name__ + "."

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self.prefix):
            return None
        module = fullname[len(self.prefix):]
        if "." in module or module not in _by_module:
            return None
        return importlib.machinery.ModuleSpec(fullname, self)

    def create_module(self, spec):
        module = types.ModuleType(spec.name)
        for name in _by_module[spec.name[len(self.prefix):]]:
            setattr(module, name, getattr(_flat, name))
        module.__all__ = list(_by_module[spec.name[len(self.prefix):]])
        return module

    def exec_module(self, module):
        return None


if not any(isinstance(finder, _Finder) for finder in sys.meta_path):
    sys.meta_path.append(_Finder())


def __getattr__(name: str):
    """``occt.TopoDS`` as an attribute as well (OCP does both)."""

    if name in _by_module:
        import importlib

        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
