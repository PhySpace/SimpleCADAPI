"""Names kept (Python) code imports that the native module does not export itself.

``names_for(key)`` is the per-module table of extras; ``prepare(native)``
makes the native error translator build the SDK's own ``SimpleCADError``.
"""

from __future__ import annotations

import functools
import types
from collections.abc import Sequence
from numbers import Real
from typing import Any, Callable, Dict, Optional, Union

_native: Any = None
_tables: Dict[str, Dict[str, Any]] = {}


def lazy(fn: Callable[[], Any]) -> Callable[[], Any]:
    fn._lazy = True  # type: ignore[attr-defined]
    return fn


def names_for(key: str) -> Dict[str, Any]:
    return _tables.get(key, {})


def _register(key: str, **names: Any) -> None:
    _tables.setdefault(key, {}).update(names)


def _install_errors(nat: Any) -> None:
    """Native errors become the SDK's ``SimpleCADError`` (same class, same rendering)."""

    from .. import errors as sdk_errors

    native_errors = nat.errors

    class TagValidationError(sdk_errors.SimpleCADMessageError):
        """A tag binding or policy is malformed."""

        operation = "tagging"
        possible_causes = (
            "A tag name is not normalised (use lowercase dotted names such as 'role.mounting_surface').",
            "A tag binding, producer, evidence or target record is missing a required field, or carries an unknown one.",
            "A tag was applied to a result or entity that the operation did not produce.",
        )
        how_to_fix = (
            "Read 'What happened' for the exact field or name and correct that value.",
            "Create tags through the operator tag arguments (result_tag and the *_face_tag family) instead of building binding records by hand.",
            "List the tags an object carries before binding or selecting by tag.",
        )

    class SemanticCapabilityError(sdk_errors.SimpleCADMessageError):
        """An object cannot evaluate a requested semantic scope."""

        operation = "semantic_query"
        possible_causes = (
            "The object cannot evaluate the requested semantic scope (for example a lineage or role query on a shape the operation did not produce).",
            "An operation output role has no kernel-proven result to bind to.",
            "The query asked for evidence that the shape does not carry.",
        )
        how_to_fix = (
            "Build the shape with the operation that records the role or lineage you query, then query that shape.",
            "Change the query to a scope the object supports (its local topology, or a tag it carries).",
            "Check the operation's documented output tags and roles before binding a tag to one.",
        )

    class UnsupportedQueryCapabilityError(SemanticCapabilityError):
        """Required query evidence is unavailable or incomplete."""

        possible_causes = (
            "The query needs evidence (lineage, history, kernel-proven results) that was not recorded for this shape.",
            "The shape came from an operation or an import that does not track that evidence.",
        )
        how_to_fix = (
            "Rebuild the shape with tracking enabled (the operation's tracking_policy argument) so the evidence is recorded.",
            "Use a query that relies on geometry, which every shape supports, instead of tracked lineage.",
        )

    families = {
        "TagValidationError": TagValidationError,
        "SemanticCapabilityError": SemanticCapabilityError,
        "UnsupportedQueryCapabilityError": UnsupportedQueryCapabilityError,
    }

    def make_error(operation: str, guidance: Dict[str, Any], message: str, family: str = "") -> Exception:
        if family in families:  # message-first: the text is the whole payload, as in the SDK
            return families[family](str(guidance.get("what_happened") or message))
        def evidence(item: Dict[str, Any]) -> Any:
            return sdk_errors.ErrorEvidence(
                kind=item.get("kind", ""),
                path=item.get("path"),
                view=item.get("view"),
                caption=item.get("caption"),
                symbols=tuple((dict(item.get("symbols") or {})).items()),
            )

        def measurement(item: Dict[str, Any]) -> Any:
            value = item.get("value")
            return sdk_errors.ErrorMeasurement(
                name=item.get("name", ""),
                value=tuple(value) if isinstance(value, list) else value,
                unit=item.get("unit"),
            )

        def inventory(item: Dict[str, Any]) -> Any:
            return sdk_errors.InventoryEntry(
                symbol=item.get("symbol", ""),
                status=item.get("status", ""),
                description=item.get("description", ""),
            )

        built = sdk_errors.ErrorGuidance(
            what_happened=guidance.get("what_happened", ""),
            possible_causes=tuple(guidance.get("possible_causes") or ()),
            how_to_fix=tuple(guidance.get("how_to_fix") or ()),
            technical_details=guidance.get("technical_details"),
            signature=_operation_signature(operation),
            documentation_hint=sdk_errors._documentation_hint(operation),
            measurements=tuple(measurement(m) for m in guidance.get("measurements") or ()),
            evidence=tuple(evidence(e) for e in guidance.get("evidence") or ()),
            repair=tuple(guidance.get("repair") or ()),
            inventory=tuple(inventory(i) for i in guidance.get("inventory") or ()),
        )
        return sdk_errors.SimpleCADError(operation, built)

    native_errors.make_error = make_error
    native_errors.SimpleCADError = sdk_errors.SimpleCADError
    nat.SimpleCADError = sdk_errors.SimpleCADError
    # The tag-error families are the SDK's message-first classes; `tagging` names the ones that are raised.
    tagging = getattr(nat, "tagging", None)
    if tagging is not None:
        for family, cls in families.items():
            setattr(tagging, family, cls)


def prepare(nat: Any) -> None:
    global _native
    _native = nat
    _install_errors(nat)
    from . import bridge

    bridge.install(nat)
    from . import topology as topology_module

    topology_module.install(nat)
    from . import values

    values.install(nat)
    from . import graph_nodes

    graph_nodes.install(nat)
    _name_modules(nat)

    _register(
        "core",
        TaggedMixin=nat.AnyShape,
    )
    from . import replay_support
    from .._internal.workspace import diagnostics_dir

    from simplecadapi._cpp import evidence

    evidence.install()  # failure pictures: the C++ diagnostics ask, this draws
    _register("operators._diagnostics", diagnostics_dir=diagnostics_dir, _RENDER_DEDUP=evidence._RENDER_DEDUP)

    for module in ("operators", "operators.geometry"):
        _register(
            module,
            _brep_region_path=nat._brep_region_path,
            _load_brep_region_rshape=replay_support.load_brep_region_rshape(nat),
        )

    for module in ("operators", "operators.sketch"):
        _register(
            module,
            _constrain_rsketch=nat._constrain_rsketch,
            _assert_sketch_solve_snapshot_dict_matches=replay_support.assert_sketch_solve_snapshot_dict_matches,
        )
    for module in ("operators", "operators._support"):
        _register(module, _OPERATION_OUTPUT_ROLE_CARDINALITY=lazy(lambda: _load_tables().get("_OPERATION_OUTPUT_ROLE_CARDINALITY")))
    for module in ("operators", "operators.features"):
        _register(
            module,
            render_screenshot_rpath=lazy(lambda: _render().render_screenshot_rpath),
            _prepare_screenshot_render=lazy(lambda: _render()._prepare_screenshot_render),
            _execute_screenshot_render=lazy(lambda: _render()._execute_screenshot_render),
            _screenshot_views=lazy(lambda: _render()._screenshot_views),
            SCREENSHOT_VIEWS=lazy(lambda: _render()._screenshot_views()),
        )
    _register(
        "_internal.shape_pickle",
        remember_source_bytes=remember_source_bytes,
        source_bytes=source_bytes,
    )
    _patch_node_deltas(nat)
    _register(
        "core",
        clone_semantic_shape_view=_clone_semantic_shape_view,
        use_coordinate_system=use_coordinate_system,
    )
    from . import session as session_module

    session_module.install_product_operators(nat)
    _register(
        "recording.graph",
        GraphSession=session_module.GraphSession,
        attach_graph_node=session_module.attach_graph_node,
        attach_semantic_graph_node=session_module.attach_semantic_graph_node,
        record_operation_if_active=session_module.record_operation_if_active,
        record_operation=session_module.record_operation,
    )
    _register(
        "product.assembly",
        _AUTHORED_PLACEMENTS_RUNTIME_KEY=_AUTHORED_PLACEMENTS_RUNTIME_KEY,
        _component_occurrence_placements=_component_occurrence_placements,
        _restore_component_occurrence_placements=_restore_component_occurrence_placements,
    )
    _register("params.units", UnitLike=Union[nat.Unit, str])
    _register(
        "params.expr",
        ScalarExprBase=nat.ExprBase,
        ScalarExpr=Union[nat.Const, nat.Var, nat.Expr],
        ScalarLike=Union[int, float, nat.Const, nat.Var, nat.Expr],
        ToleranceLike=Union[int, float, Sequence[Union[int, float]], nat.DimensionTolerance],
        coerce_dimension_tolerance=_coerce_dimension_tolerance,
        _expr_signature=lambda expr: ("native-expr", getattr(expr, "expr_id", None)),
    )
    wrap_namespaces(nat)


# ---- product.assembly -------------------------------------------------------------------

_AUTHORED_PLACEMENTS_RUNTIME_KEY = "assembly.authored_component_placements"


def _component_occurrence_placements(assembly: Any) -> tuple:
    from ..product.placement import placement_ticks

    records: list = []

    def visit(owner: Any, prefix: tuple) -> None:
        for component in sorted(owner.components, key=lambda item: item.component_id.encode("utf-8")):
            component_path = (*prefix, component.component_id)
            records.append(
                {"component_path": list(component_path), "placement": placement_ticks(component.placement)}
            )
            if isinstance(component.item, _native.Assembly):
                visit(component.item, component_path)

    visit(assembly, ())
    return tuple(records)


def _restore_component_occurrence_placements(assembly: Any, records: Any) -> Any:
    from collections.abc import Mapping

    from ..product.placement import placement_from_canonical

    expected_paths = {tuple(record["component_path"]) for record in _component_occurrence_placements(assembly)}
    by_path: Dict[tuple, Any] = {}
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {"component_path", "placement"}:
            raise ValueError("invalid occurrence placement record")
        raw_path = record["component_path"]
        if (
            not isinstance(raw_path, list)
            or not raw_path
            or not all(isinstance(item, str) and item for item in raw_path)
        ):
            raise ValueError("component_path must be a non-empty string array")
        component_path = tuple(raw_path)
        if component_path in by_path:
            raise ValueError("duplicate component occurrence path")
        placement = record["placement"]
        if not isinstance(placement, Mapping):
            raise ValueError("occurrence placement must be an object")
        by_path[component_path] = placement
    if set(by_path) != expected_paths:
        raise ValueError("occurrence placement paths differ from the assembly tree")
    current = {tuple(r["component_path"]): r["placement"] for r in _component_occurrence_placements(assembly)}
    result = assembly
    for path in sorted(by_path, key=lambda p: (-len(p), p)):
        if by_path[path] == current[path]:
            continue
        result = result._with_component_path_placement(list(path), placement_from_canonical(by_path[path]))
    return result


def _clone_semantic_shape_view(shape: Any) -> Any:
    """An independent copy of the shape with its tags, lineage and topo ids."""

    if not isinstance(shape, _native.AnyShape):
        raise TypeError("shape must be a SimpleCAD topology object")
    return _native.clone_semantic_view(shape)





# ---- topology.model ---------------------------------------------------------------------


def _upper_kinds(data: Any) -> Any:
    """The C++ delta names a topology kind or event in lower case; the SDK's enum members are upper case."""

    if isinstance(data, dict):
        return {
            key: (
                value.upper()
                if key in ("kind", "event") and isinstance(value, str) and value.isalpha() and value.islower()
                else _upper_kinds(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_upper_kinds(item) for item in data]
    return data


def _patch_node_deltas(nat: Any) -> None:
    """``OperationNode.topo_delta`` as the SDK's ``TopoDelta`` dataclass (the C++ node hands out a dict)."""

    node_class = nat.OperationNode
    dict_property = node_class.__dict__["topo_delta"]

    def topo_delta(self: Any) -> Any:
        data = dict_property.fget(self)
        if data is None:
            return None
        from ..topology.model import topo_delta_from_dict

        return topo_delta_from_dict(_upper_kinds(data))

    node_class.topo_delta = property(topo_delta)


# ---- _internal.shape_pickle -------------------------------------------------------------

_source_bytes_by_id: Dict[int, Any] = {}


def remember_source_bytes(wrapper: Any, payload: bytes) -> None:
    """Remember the BinTools bytes ``wrapper`` was decoded from (a handle's shape is immutable)."""

    import weakref

    key = id(wrapper)
    if key not in _source_bytes_by_id:
        weakref.finalize(wrapper, _source_bytes_by_id.pop, key, None)
    _source_bytes_by_id[key] = payload


def source_bytes(wrapper: Any) -> Optional[bytes]:
    return _source_bytes_by_id.get(id(wrapper))


def _render() -> Any:
    from . import render

    return render


def _coerce_dimension_tolerance(value: Any) -> Any:
    """A symmetric scalar or a ``(lower, upper)`` pair as a DimensionTolerance."""

    tolerance = _native.DimensionTolerance
    if isinstance(value, tolerance):
        return value
    if isinstance(value, bool):
        raise TypeError("Tolerance must be a real number or a two-value sequence")
    if isinstance(value, Real):
        return tolerance.symmetric(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != 2:
            raise ValueError("Asymmetric tolerance must contain exactly two deviations")
        return tolerance(value[0], value[1])
    raise TypeError("Tolerance must be a real number or a two-value sequence")


def use_coordinate_system(cs: Any) -> Any:
    """``use_coordinate_system`` of a CoordinateSystem or of the context dictionary a node recorded."""

    if isinstance(cs, dict):
        cs = _native.CoordinateSystem(cs["origin"], cs["x_axis"], cs["y_axis"])
    return _native.use_coordinate_system(cs)


def _load_tables() -> Any:
    from . import tables

    return tables


def _name_modules(nat: Any) -> None:
    """Give the native functions and classes the module the Python SDK defines them in.

    ``modules.json`` maps public names to the SDK module (``make_box_rsolid`` ->
    ``simplecadapi.operators.geometry``): ``help()``, error text and pickling by reference then read
    the same as in the ``ocp`` backend (the shim modules resolve the names back to the native objects).
    """

    import json
    from pathlib import Path

    for attribute, module in (
        ("ql", "simplecadapi.ql"),
        ("surface", "simplecadapi.surface"),
        ("math", "simplecadapi.math"),
        ("tagging", "simplecadapi.topology.tagging"),
    ):
        _name_submodule(getattr(nat, attribute, None), module)
    for attribute in ("gear", "bearing", "chain", "fastener"):
        _name_submodule(getattr(nat.std, attribute, None), f"simplecadapi.std.{attribute}")

    table = json.loads((Path(__file__).with_name("modules.json")).read_text(encoding="utf-8"))
    for name, module in table.items():
        item = getattr(nat, name, None)
        current = getattr(item, "__module__", None)
        if isinstance(current, str) and current.startswith("simplecadapi._cpp"):
            try:
                item.__module__ = module
            except (AttributeError, TypeError):
                pass


class _Raw:
    """A default value shown as written in the C++ signature."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text


def _split_top(text: str) -> list:
    parts, depth, current, quote = [], 0, "", ""
    for char in text:
        if quote:
            current += char
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


class _VarArgNames(dict):
    """``{function name: its *args parameter name}`` read, without importing it, from the SDK's operator sources."""

    _loaded = False

    def _load(self) -> None:
        import json
        from pathlib import Path

        self._loaded = True
        self.update(json.loads(Path(__file__).with_name("varargs.json").read_text(encoding="utf-8")))

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        if not self._loaded:
            self._load()
        return super().get(key, default)


_SDK_VARARGS = _VarArgNames()


def _signature_of(function: Any) -> Any:
    import ast
    import inspect

    if isinstance(function, type):  # a class: its constructor's signature
        function = function.__init__
        doc = getattr(function, "__doc__", None) or ""
        first = doc.split("\n", 1)[0]
        name = "__init__"
    else:
        doc = getattr(function, "__doc__", None) or ""
        first = doc.split("\n", 1)[0]
        name = getattr(function, "__name__", "")
    if not first.startswith(name + "(") or first.startswith("1."):
        return None
    close = first.rindex(")") if "->" not in first else first.rindex(")", 0, first.rindex("->"))
    inner = first[len(name) + 1 : close]
    parameters = []
    keyword_only = False
    for part in _split_top(inner):
        if part == "*":
            keyword_only = True
            continue
        if part in ("self", "self: object") or part.startswith("self:"):
            continue
        head, _, default = part.partition(" = ")
        pname = head.split(":")[0].strip()
        if pname.startswith("**") and pname[2:].isidentifier():
            parameters.append(inspect.Parameter(pname[2:], inspect.Parameter.VAR_KEYWORD))
            continue
        if pname.startswith("*") and pname[1:].isidentifier():
            # pybind11 cannot name `*args`: the SDK's own name for it is taken from its source.
            var_name = _SDK_VARARGS.get(name) if pname == "*args" else None
            parameters.append(inspect.Parameter(var_name or pname[1:], inspect.Parameter.VAR_POSITIONAL))
            keyword_only = True
            continue
        if not pname.isidentifier():
            return None
        if default:
            try:
                value: Any = ast.literal_eval(default)
            except (ValueError, SyntaxError):
                value = _Raw(default)
        else:
            value = inspect.Parameter.empty
        kind = inspect.Parameter.KEYWORD_ONLY if keyword_only else inspect.Parameter.POSITIONAL_OR_KEYWORD
        parameters.append(inspect.Parameter(pname, kind, default=value))
    try:
        return inspect.Signature(parameters)
    except ValueError:
        return None


def _operation_signature(operation: str) -> Optional[str]:
    """``op(args)`` of a public operation; pybind11 functions carry theirs only in the docstring."""

    import inspect

    from .. import errors as sdk_errors

    function = sdk_errors._resolve_operation_callable(operation)
    if function is None:
        return None
    try:
        return f"{operation}{inspect.signature(function)}"
    except (TypeError, ValueError):
        parsed = _signature_of(function)
        return None if parsed is None else f"{operation}{parsed}"


def signature_of(obj: Any) -> Any:
    """``inspect.signature`` of a native function or class (parsed from the pybind11 docstring), or None."""

    return _signature_of(obj)


_WITH_SIGNATURE: Dict[int, Any] = {}


def with_signature(function: Any) -> Any:
    """A pybind11 function as a Python function that carries its signature.

    ``inspect.signature`` finds none on a built-in; the SDK's own operators are Python functions and every
    tool that reads parameters (the editor's API index, the parameter UI, the docs generator, ``help``) uses it.
    One wrapper per function, so ``a is b`` holds wherever the name is reached.
    """

    if not isinstance(function, types.BuiltinFunctionType):
        return function
    found = _WITH_SIGNATURE.get(id(function))
    if found is not None:
        return found
    signature = _signature_of(function)
    if signature is None:
        return function

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    wrapper.__signature__ = signature  # type: ignore[attr-defined]
    _WITH_SIGNATURE[id(function)] = wrapper
    return wrapper


def _name_submodule(submodule: Any, module: str) -> None:
    if submodule is None:
        return
    try:
        submodule.__name__ = module
    except (AttributeError, TypeError):
        pass
    for name in dir(submodule):
        if name.startswith("_"):
            continue
        item = getattr(submodule, name, None)
        current = getattr(item, "__module__", None)
        if isinstance(current, str) and current.startswith("simplecadapi._cpp"):
            try:
                item.__module__ = module
            except (AttributeError, TypeError):
                pass


def wrap_namespaces(nat: Any) -> None:
    """Replace the built-in functions of the C++ module (and its sub-namespaces) by their signature-carrying wrappers.

    Done once at install, so every way of reaching a name (``simplecadapi.x``, ``simplecadapi._cpp.x``, the legacy module
    paths) yields the same object.
    """

    for namespace in (nat, getattr(nat, "ql", None), getattr(nat, "surface", None), getattr(nat, "math", None),
                      getattr(nat, "tagging", None), getattr(nat, "std", None),
                      *(getattr(getattr(nat, "std", None), part, None) for part in ("gear", "bearing", "chain", "fastener"))):
        if namespace is None:
            continue
        for name in dir(namespace):
            if name.startswith("__"):
                continue
            value = getattr(namespace, name, None)
            if isinstance(value, types.BuiltinFunctionType):
                wrapped = with_signature(value)
                if wrapped is not value:
                    try:
                        setattr(namespace, name, wrapped)
                    except (AttributeError, TypeError):
                        pass


def apply_docstrings(namespace) -> None:
    """Give the exported objects the docstrings the C++ bindings do not carry (``docstrings.json``, lifted from the old Python operators)."""

    import json
    from pathlib import Path

    import importlib

    table = json.loads(Path(__file__).with_name("docstrings.json").read_text(encoding="utf-8"))
    modules = json.loads(Path(__file__).with_name("modules.json").read_text(encoding="utf-8"))
    for name, doc in table.items():
        obj = getattr(namespace, name, None)
        if obj is None:
            try:
                obj = getattr(importlib.import_module(modules[name]), name, None)
            except (ImportError, KeyError):
                obj = None
        if obj is None:
            continue
        try:
            obj.__doc__ = doc
        except (AttributeError, TypeError):
            wrapped = with_signature(obj)  # a built-in takes no docstring: its wrapper does
            if wrapped is obj:
                continue
            wrapped.__doc__ = doc
            try:
                owner = importlib.import_module(modules[name])
            except (ImportError, KeyError):
                continue
            for holder in (owner, namespace):
                if getattr(holder, name, None) is obj:
                    setattr(holder, name, wrapped)
