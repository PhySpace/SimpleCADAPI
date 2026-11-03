"""The operation catalog: every public operation, its parameters and what they mean, read from the signatures.

Nothing here is written by hand.  The bound operations carry their Python signature (pybind writes it as the first line of
the native docstring, with the semantic types of :mod:`simplecadapi.types`); the standard library's operations are Python
functions with the same annotations.  The catalog parses both, so a GUI, an agent or the API pages get the same answer:

    >>> from simplecadapi import catalog
    >>> op = catalog.operation("make_cylinder_rsolid")
    >>> [(p.name, p.kind) for p in op.params][:4]
    [('radius', 'length'), ('height', 'length'), ('bottom_face_center', 'point3'), ('axis', 'direction3')]

A parameter's ``kind`` is one of: the meanings of :mod:`simplecadapi.types` (``length``, ``angle``, ``point3``,
``direction3``, ``vector3``, ``count``, ``point2``, ``plane``, ``sketch_profile``), ``number`` (a unitless ``float | Expr``), ``int``, ``bool``, ``text``, ``path``
(``str | os.PathLike``), ``enum`` (``Literal[...]``, with ``choices``), a value type (``solid``, ``face``, ``wire``,
``edge``, ``vertex``, ``shell``, ``shape``, ``sketch``, ``part``, ``assembly``, ``scalar_limit``, ...), ``query`` (a
``ql`` selection), ``points`` / ``numbers`` (sequences), ``grid`` (rows of points), ``<kind>_map`` (``dict[str, <kind>]``: a value per id),
``<a>|<b>`` (a union of kinds, e.g. ``enum|numbers`` or ``query|shape``), or ``unknown`` when the signature says no
more than ``object``.  ``many`` marks a sequence of the kind, ``optional`` a
``None`` default.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Callable

from .types import MEANINGS

_OP_NAME = re.compile(r"^[a-z][a-z0-9_]*_r[a-z]+$")
STD_MODULES = ("simplecadapi.std.gear", "simplecadapi.std.fastener", "simplecadapi.std.chain", "simplecadapi.std.bearing")
"""The standard-library modules whose ``*_r<kind>`` functions are operations too."""

_VALUE_KINDS = {
    "Solid": "solid",
    "Face": "face",
    "Wire": "wire",
    "Edge": "edge",
    "Vertex": "vertex",
    "Shell": "shell",
    "Compound": "compound",
    "AnyShape": "shape",
    "Shape": "shape",
    "Sketch": "sketch",
    "SketchRef": "sketch_ref",
    "Part": "part",
    "Assembly": "assembly",
    "Component": "component",
    "Connector": "connector",
    "ConnectorRef": "connector_ref",
    "Placement": "placement",
    "Material": "material",
    "Query": "query",
    "ShapeSelector": "query",
    "Vec3": "vector3",
    "SketchPosition": "sketch_ref",
    "SurfaceBoundary": "surface_boundary",
    "SurfaceFillingSettings": "filling_settings",
    "ScalarLimit": "scalar_limit",
    "PathLike": "path",
    "Path": "path",
}


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    type: str
    """The type as the signature writes it (shortened: no module paths)."""
    default: Any = None
    has_default: bool = False
    keyword_only: bool = False
    many: bool = False
    optional: bool = False
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Operation:
    name: str
    module: str
    """Where to import it from (``simplecadapi`` or a standard-library module)."""
    returns: str
    """The kind of the result (``solid``, ``face``, ``solids`` for a list ...)."""
    summary: str
    params: tuple[Param, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["params"] = [asdict(p) for p in self.params]
        return out


# ---- types -------------------------------------------------------------------------------------------------------------


def _short(text: str) -> str:
    """Drop module paths: ``simplecadapi._cpp._native.Solid`` -> ``Solid``, ``collections.abc.Sequence`` -> ``Sequence``."""
    return re.sub(r"\b(?:[A-Za-z_][\w]*\.)+([A-Za-z_]\w*)", r"\1", text)


def _split_top(text: str, sep: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def classify(type_text: str) -> dict[str, Any]:
    """The kind of a parameter from its (shortened) type text: ``{kind, many, optional, choices}``."""
    text = _short(type_text).strip()
    optional = False
    union = _split_top(text, "|")
    if "None" in union:
        optional = True
        union = [u for u in union if u != "None"]
    if not union:
        return {"kind": "unknown", "many": False, "optional": optional, "choices": ()}
    if len(union) > 1:
        return _classify_union(union, optional)
    text = union[0]
    annotated = re.fullmatch(r"Annotated\[(.*)\]", text)
    if annotated:
        inner, *meta = _split_top(annotated.group(1), ",")
        if any("FixedSize(3)" in m for m in meta):
            return {"kind": "point3", "many": False, "optional": optional, "choices": ()}
        for m in meta:
            word = m.strip("'\" ")
            if word in MEANINGS.values():
                return {"kind": word, "many": False, "optional": optional, "choices": ()}
        text = inner
    literal = re.fullmatch(r"Literal\[(.*)\]", text)
    if literal:
        choices = tuple(c.strip().strip("'\"") for c in _split_top(literal.group(1), ","))
        return {"kind": "enum", "many": False, "optional": optional, "choices": choices}
    if text in MEANINGS:
        return {"kind": MEANINGS[text], "many": False, "optional": optional, "choices": ()}
    sequence = re.fullmatch(r"(?:Sequence|list|List|tuple|Iterable)\[(.*)\]", text)
    if sequence:
        inner = classify(_split_top(sequence.group(1), ",")[0])
        kind = inner["kind"]
        if kind in ("number", "length", "angle"):
            return {"kind": "numbers", "many": False, "optional": optional, "choices": ()}
        if kind in ("point3", "vector3", "direction3", "point2"):
            return {"kind": "points", "many": False, "optional": optional, "choices": ()}
        if kind == "points":  # rows of points: a control net or a point grid
            return {"kind": "grid", "many": False, "optional": optional, "choices": ()}
        return {"kind": kind, "many": True, "optional": optional, "choices": inner["choices"]}
    mapping = re.fullmatch(r"(?:dict|Dict|Mapping)\[(.*)\]", text)
    if mapping:  # a value per name (component id, tag ...): ``direction3_map``, ``number_map``, ``text_map``
        key_and_value = _split_top(mapping.group(1), ",")
        inner = classify(key_and_value[-1])
        if inner["kind"] == "unknown":
            return {"kind": "unknown", "many": False, "optional": optional, "choices": ()}
        return {"kind": f"{inner['kind']}_map", "many": inner["many"], "optional": optional, "choices": inner["choices"]}
    return _classify_names([text], optional)


def _classify_names(names: list[str], optional: bool) -> dict[str, Any]:
    """Plain type names (no brackets but ``PathLike[str]``), alone or as a union."""
    names = [re.sub(r"^(PathLike)\[.*\]$", r"\1", n.strip()) for n in names]
    if set(names) <= {"float", "Expr", "SupportsFloat", "SupportsIndex", "int"} and {"float", "SupportsFloat"} & set(names):
        return {"kind": "number", "many": False, "optional": optional, "choices": ()}
    if set(names) <= {"int", "SupportsInt", "SupportsIndex"}:
        return {"kind": "int", "many": False, "optional": optional, "choices": ()}
    if names == ["bool"]:
        return {"kind": "bool", "many": False, "optional": optional, "choices": ()}
    if names == ["str"]:
        return {"kind": "text", "many": False, "optional": optional, "choices": ()}
    if set(names) <= {"str", "PathLike", "Path"} and set(names) != {"str"}:  # a file path, as text or os.PathLike
        return {"kind": "path", "many": False, "optional": optional, "choices": ()}
    if "SketchRef" in names:  # a point or entity of the sketch, by reference or id (a position too, where allowed)
        return {"kind": "sketch_ref", "many": False, "optional": optional, "choices": ()}
    # A sequence alternative counts as its item kind: ``Sketch | AnyShape | Sequence[AnyShape]`` reads as sketch | shape.
    kinds = {_VALUE_KINDS.get(n) or _sequence_item_kind(n) for n in names}
    if None not in kinds:
        kind = kinds.pop() if len(kinds) == 1 else "shape" if kinds <= {"solid", "face", "wire", "edge", "vertex", "shell", "compound", "shape"} else "|".join(sorted(kinds))
        return {"kind": kind, "many": False, "optional": optional, "choices": ()}
    return {"kind": "unknown", "many": False, "optional": optional, "choices": ()}


def _sequence_item_kind(text: str) -> str | None:
    match = re.fullmatch(r"(?:Sequence|list|List|tuple|Iterable)\[(.*)\]", text)
    return _VALUE_KINDS.get(match.group(1).strip()) if match else None


def _classify_union(union: list[str], optional: bool) -> dict[str, Any]:
    """``A | B``: different spellings of one value, or a choice between kinds.

    Plain names read as one kind (``float | Expr`` is a number).  ``Literal[...] | SomeEnum`` is the enum (the enum class
    spells the same choices); ``Sequence[Edge] | Query`` is edges (or a ``ql`` query that finds them, ``many``);
    ``Solid | Sequence[Solid]`` is one solid or many.  Otherwise the kinds are joined (``Wire | Direction3`` ->
    ``direction3|wire``; ``Literal[...] | tuple[Angle, Angle]`` -> ``enum|numbers`` with the Literal's choices).
    """
    if "SketchRef" in union:  # a point or entity of the sketch, by reference or id (a position too, where allowed)
        return {"kind": "sketch_ref", "many": False, "optional": optional, "choices": ()}
    if not any("[" in u for u in union) or all(re.fullmatch(r"PathLike\[.*\]", u) for u in union if "[" in u):
        plain = _classify_names(union, optional)
        if plain["kind"] != "unknown":
            return plain
    parts = [classify(u) for u in union]
    literal = next((p for p in parts if p["kind"] == "enum"), None)
    if literal is not None and all(p is literal or p["kind"] == "unknown" for p in parts):
        return {"kind": "enum", "many": False, "optional": optional, "choices": literal["choices"]}
    if any(p["kind"] == "unknown" for p in parts):
        return {"kind": "unknown", "many": False, "optional": optional, "choices": ()}
    many = any(p["many"] for p in parts)
    kinds = {p["kind"] for p in parts}
    if many and len(kinds) > 1:
        kinds.discard("query")
    if len(kinds) == 1:
        kind = kinds.pop()
    elif kinds <= {"solid", "face", "wire", "edge", "vertex", "shell", "compound", "shape"}:
        kind = "shape"
    else:
        kind = "|".join(sorted(kinds))
    choices = next((p["choices"] for p in parts if p["choices"]), ())
    return {"kind": kind, "many": many, "optional": optional or any(p["optional"] for p in parts), "choices": choices}


def _returns(type_text: str) -> str:
    info = classify(type_text)
    if info["many"]:
        return f"{info['kind']}s"
    text = _short(type_text).strip()
    if text in ("list", "List"):
        return "list"
    return info["kind"] if info["kind"] != "unknown" else text or "unknown"


# ---- signatures --------------------------------------------------------------------------------------------------------


def _native_signature(fn: Callable[..., Any]) -> str | None:
    """The ``name(params) -> ret`` line pybind writes first in a bound function's docstring."""
    target = getattr(fn, "__wrapped__", fn)
    doc = getattr(target, "__doc__", None) or ""
    first = doc.lstrip().splitlines()[0] if doc.strip() else ""
    return first if "(" in first and first.endswith(tuple("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_]")) else None


def _summary(fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn) or ""
    lines = doc.splitlines()
    if lines and _native_signature(fn) and lines[0].startswith(fn.__name__ + "("):
        lines = lines[1:]
    text = "\n".join(lines).strip()
    return text.split("\n\n")[0].replace("\n", " ").strip()


def _parse_native(line: str) -> tuple[list[dict[str, Any]], str]:
    """Params and return type from a pybind signature line (parsed as a Python ``def``)."""
    source = re.sub(r"<\w+(?:\.\w+)+: ('[^'<>]*')>", r"\1", line)  # a str enum member: <TopologyPropagation.LOCAL: 'local'>
    source = re.sub(r"<[^<>]*>", "None", source)  # defaults pybind cannot print: <object at 0x...>
    tree = ast.parse(f"def {source}: pass")
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    args = fn.args
    out: list[dict[str, Any]] = []
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for arg, default in zip(positional, defaults):
        out.append(_param_from_ast(arg, default, keyword_only=False))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        out.append(_param_from_ast(arg, default, keyword_only=True))
    returns = ast.unparse(fn.returns) if fn.returns is not None else ""
    return out, returns


def _param_from_ast(arg: ast.arg, default: ast.expr | None, *, keyword_only: bool) -> dict[str, Any]:
    type_text = ast.unparse(arg.annotation) if arg.annotation is not None else "object"
    value: Any = None
    if default is not None:
        try:
            value = ast.literal_eval(default)
        except ValueError:
            value = ast.unparse(default)
    return {"name": arg.arg, "type": _short(type_text), "default": value, "has_default": default is not None, "keyword_only": keyword_only}


def _parse_python(fn: Callable[..., Any]) -> tuple[list[dict[str, Any]], str]:
    sig = inspect.signature(fn)
    out = []
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        annotation = p.annotation
        type_text = "object" if annotation is p.empty else (annotation if isinstance(annotation, str) else inspect.formatannotation(annotation))
        has_default = p.default is not p.empty
        out.append({"name": p.name, "type": _short(str(type_text)), "default": p.default if has_default else None,
                    "has_default": has_default, "keyword_only": p.kind == p.KEYWORD_ONLY})
    ret = sig.return_annotation
    return out, "" if ret is sig.empty else _short(ret if isinstance(ret, str) else inspect.formatannotation(ret))


def describe(fn: Callable[..., Any], module: str) -> Operation:
    """The catalog entry of one operation."""
    line = _native_signature(fn)
    raw, returns = _parse_native(line) if line else _parse_python(fn)
    params = []
    for item in raw:
        info = classify(item["type"])
        params.append(Param(name=item["name"], kind=info["kind"], type=item["type"], default=item["default"],
                            has_default=item["has_default"], keyword_only=item["keyword_only"], many=info["many"],
                            optional=info["optional"] or (item["has_default"] and item["default"] is None),
                            choices=info["choices"]))
    return Operation(name=fn.__name__ if hasattr(fn, "__name__") else str(fn), module=module, returns=_returns(returns),
                     summary=_summary(fn), params=tuple(params))


# ---- the catalog -------------------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def operations() -> tuple[Operation, ...]:
    """Every public operation: the ``*_r<kind>`` functions of ``simplecadapi`` and of the standard library, by name."""
    import simplecadapi

    found: dict[str, Operation] = {}
    for name in sorted(simplecadapi.__all__):
        if _OP_NAME.match(name) and callable(getattr(simplecadapi, name, None)):
            found[name] = describe(getattr(simplecadapi, name), "simplecadapi")
    for module_name in STD_MODULES:
        module = importlib.import_module(module_name)
        for name in sorted(dir(module)):
            fn = getattr(module, name)
            if _OP_NAME.match(name) and callable(fn) and getattr(fn, "__module__", "") == module_name and name not in found:
                found[name] = describe(fn, module_name)
    return tuple(found.values())


def operation(name: str) -> Operation:
    for op in operations():
        if op.name == name:
            return op
    raise KeyError(f"no operation {name!r} in the catalog")


def catalog_dict() -> dict[str, Any]:
    """The whole catalog as plain data (what ``sca ops --json`` prints and the editor serves)."""
    return {"version": 1, "operations": [op.to_dict() for op in operations()]}


# ---- ``sca ops`` -------------------------------------------------------------------------------------------------------


def configure(subparsers: Any) -> None:
    """``sca ops [NAME] [--json]``: the operation catalog (every operation and the meaning of its parameters)."""
    import json as _json

    parser = subparsers.add_parser(
        "ops",
        help="the SDK operations and what their parameters mean (read from the signatures)",
        description="Without a name: one line per operation (name, result, parameters with their kinds). With a name: "
        "that operation in full. --json prints the catalog as data (what the editor's forms are made from).",
    )
    parser.add_argument("name", nargs="?", help="one operation")
    parser.add_argument("--json", action="store_true", help="print JSON")

    def show(report: dict[str, Any], as_json: bool) -> None:
        if as_json:
            print(_json.dumps(report, indent=2, default=str))
            return
        ops = report.get("operations", [report])
        for op in ops:
            params = ", ".join(f"{p['name']}: {p['kind']}{'[]' if p['many'] else ''}{'?' if p['optional'] else ''}" for p in op["params"])
            where = f"   [{op['module']}]" if op["module"] != "simplecadapi" else ""
            print(f"{op['name']}({params}) -> {op['returns']}{where}")
            if len(ops) == 1 and op["summary"]:
                print(f"  {op['summary']}")

    def run(args: Any) -> tuple[dict[str, Any], int]:
        args.printer = lambda report: show(report, args.json)  # read by cli.run after the handler
        return (operation(args.name).to_dict() if args.name else catalog_dict()), 0

    parser.set_defaults(handler=run, printer=None)


__all__ = ["Operation", "Param", "STD_MODULES", "catalog_dict", "classify", "configure", "describe", "operation", "operations"]
