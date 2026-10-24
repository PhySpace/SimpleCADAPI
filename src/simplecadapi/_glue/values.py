"""Product values on the native backend: pickling, deepcopy and Python-object runtime entries.

The cell cache pickles ``Part``/``Assembly`` values; the C++ classes carry
their state in typed fields and JSON-like ``metadata`` / ``runtime``
dictionaries.  Two things make them behave like the Python dataclasses:

* a constructor-argument reduction (``copyreg``): the constructor arguments are
  read back from the attributes of the same name, then the two dictionaries;
* a side table for runtime entries that are not JSON-like (the attached
  ``PartDefinition`` / ``AssemblyDefinition`` objects), keyed by object
  identity and pickled with the value.
"""

from __future__ import annotations

import copyreg
import re
import weakref
from typing import Any, Dict, Tuple

# class name -> (constructor parameter names, has state dictionaries)
_VALUES: Dict[str, bool] = {
    "Part": True,
    "Assembly": True,
    "Placement": True,
    "Material": True,
    "Connector": True,
    "ConnectorRef": True,
    "GeometryRef": True,
    "ConnectorAnchor": True,
    "Constraint": True,
    "ScalarLimit": True,
    "Component": False,
    "PublicConnectorRef": False,
    "ConstraintResidual": False,
    "ConstraintReport": False,
}

# Runtime entries that are Python objects (the attached definitions) live here; the value's own
# runtime dictionary holds a token naming them, so the entry follows the C++ object (the same
# Part seen through another Python wrapper) and is pickled with it.
_OBJECTS: Dict[str, Any] = {}
_TOKEN = "\x00pyobj:"
_JSON = (type(None), bool, int, float, str)


def _is_value(item: Any) -> bool:
    if isinstance(item, _JSON):
        return True
    if isinstance(item, (list, tuple)):
        return all(_is_value(entry) for entry in item)
    if isinstance(item, dict):
        return all(isinstance(key, str) and _is_value(entry) for key, entry in item.items())
    return False


def _parameters(cls: type) -> Tuple[str, ...]:
    signature = cls.__init__.__doc__.split("->")[0]
    inner = signature[signature.index("(") + 1 : signature.rindex(")")]
    names, depth, current = [], 0, ""
    for char in inner + ",":
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            name = current.strip().split(":")[0].split("=")[0].strip()
            if name and name != "self":
                names.append(name)
            current = ""
        else:
            current += char
    return tuple(names)


def _rebuild(cls: type, args: tuple, state: Any) -> Any:
    value = cls(*args)
    if state is not None:
        metadata, runtime, objects = state
        _OBJECTS.update(objects or {})
        for key, item in metadata.items():
            value.set_metadata(key, item)
        for key, item in runtime.items():
            value._set_runtime(key, item)
    return value


def _token_for(key: str, item: Any) -> str:
    # Two objects with the same content (a deterministic rebuild) are still two objects: the id is part of the name.
    digest = getattr(item, "content_hash", None)
    if isinstance(digest, str):
        return f"{_TOKEN}{key}:{digest}:{id(item):x}"
    return f"{_TOKEN}{key}:{id(item):x}"


def _reduce(has_state: bool, names: Tuple[str, ...]):
    def reduce(value: Any) -> tuple:
        args = tuple(getattr(value, name) for name in names)
        state = None
        if has_state:
            runtime = value._runtime_dict()
            objects = {
                item: _OBJECTS[item]
                for item in runtime.values()
                if isinstance(item, str) and item.startswith(_TOKEN) and item in _OBJECTS
            }
            state = (value._metadata_dict(), runtime, objects or None)
        return (_rebuild, (type(value), args, state))

    return reduce


def install(nat: Any) -> None:
    install_scalars(nat)
    install_dataclass_protocol(nat)
    for name, has_state in _VALUES.items():
        cls = getattr(nat, name)
        copyreg.pickle(cls, _reduce(has_state, _parameters(cls)))
        if not has_state:
            continue
        original_set = cls._set_runtime
        original_get = cls._get_runtime

        def set_runtime(self: Any, key: str, item: Any, _set=original_set) -> None:
            if _is_value(item):
                _set(self, key, item)
            else:
                token = _token_for(key, item)
                _OBJECTS[token] = item
                _set(self, key, token)

        def get_runtime(self: Any, key: str, default: Any = None, _get=original_get) -> Any:
            item = _get(self, key, default)
            if isinstance(item, str) and item.startswith(_TOKEN):
                return _OBJECTS.get(item, default)
            return item

        cls._set_runtime = set_runtime
        cls._get_runtime = get_runtime


# ---- scalar expressions and units: content-keyed values ---------------------------------


def _build(cls: type, args: tuple) -> Any:
    return cls(*args)


def _reduce_by(getter):
    def reduce(value: Any) -> tuple:
        return (_build, (type(value), getter(value)))

    return reduce


def install_scalars(nat: Any) -> None:
    copyreg.pickle(
        nat.Var,
        _reduce_by(
            lambda v: (v.name, v.default, v.comment, v.expr_id, v.tolerance, v.unit, v.tolerance_unit)
        ),
    )
    copyreg.pickle(nat.Const, _reduce_by(lambda v: (v.value, v.expr_id)))
    copyreg.pickle(nat.Expr, _reduce_by(lambda v: (v.op, tuple(v.args), v.expr_id)))
    copyreg.pickle(nat.Unit, _reduce_by(lambda v: (v.symbol, v.dimension, v.scale_to_canonical)))
    copyreg.pickle(nat.Dimension, _reduce_by(lambda v: (v.length, v.angle)))
    copyreg.pickle(
        nat.DimensionTolerance, _reduce_by(lambda v: (v.lower_deviation, v.upper_deviation))
    )


# ---- dataclass protocol -------------------------------------------------------------------


def _dataclass_like(cls: type, names: Tuple[str, ...]) -> None:
    """Let ``dataclasses.replace`` / ``fields`` / ``asdict`` see a native value as the frozen dataclass it is in the SDK.

    The fields are the constructor parameters (read back from the attributes of the same name).
    """

    import dataclasses

    fields: Dict[str, Any] = {}
    for name in names:
        item = dataclasses.field()
        item.name = name
        item.type = Any
        item._field_type = dataclasses._FIELD  # type: ignore[attr-defined]
        fields[name] = item
    cls.__dataclass_fields__ = fields
    cls.__dataclass_params__ = dataclasses._DataclassParams(  # type: ignore[attr-defined]
        init=True, repr=True, eq=True, order=False, unsafe_hash=False, frozen=True,
        match_args=False, kw_only=False, slots=False, weakref_slot=False,
    ) if hasattr(dataclasses, "_DataclassParams") else None


def install_dataclass_protocol(nat: Any) -> None:
    for name in (
        "Var", "Const", "Expr", "Unit", "Dimension", "DimensionTolerance", "SemanticRef",
        "Part", "Assembly", "Component", "Placement", "Material", "Connector", "ConnectorRef",
        "GeometryRef", "ConnectorAnchor", "Constraint", "ScalarLimit", "PublicConnectorRef",
    ):
        cls = getattr(nat, name, None)
        if cls is None:
            continue
        try:
            names = _parameters(cls)
            if name == "SemanticRef":
                names = ("graph_id", "node_id", "entity_type", "entity_id")
            elif name == "Var":
                names = ("name", "default", "comment", "expr_id", "tolerance", "unit", "tolerance_unit")
            names = tuple(item for item in names if item.isidentifier() and hasattr(cls, item))
            _dataclass_like(cls, names)
        except Exception:  # noqa: BLE001 - a class without a parsable constructor stays as it is
            continue
