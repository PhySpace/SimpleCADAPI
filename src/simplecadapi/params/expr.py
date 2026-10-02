"""Minimal expression graph support for SimpleCADAPI 2.0.

The goal of this module is to provide a low-intrusion parametric layer:

- users explicitly create variables with ``var(name, default)``
- plain numeric literals are automatically lifted to constants when needed
- arithmetic on variables/expressions builds a small expression DAG
- public modeling APIs can keep their existing pure-function signatures while
  accepting expression values transparently
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from numbers import Real
from typing import Any, Dict, List, Mapping, Sequence, Tuple, Union, cast

from .units import (
    Dimension,
    Unit,
    UnitLike,
    get_unit,
    unit_from_payload,
    unit_to_payload,
)


def _structural_expr_id(prefix: str, node: ScalarExpr) -> str:
    """The id a node gets when none is given: a digest of its content.

    Nodes with the same content (for ``Expr``: the same op over the same
    operands) get the same id, so building the same model twice records the
    same expression graph, and so the same content hash.
    """

    signature = repr(_expr_signature(node)).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(signature).hexdigest()[:16]}"


def _settle_expr_id(node: ScalarExpr, prefix: str) -> None:
    if not isinstance(node.expr_id, str):
        raise ValueError("Expression id must be a string")
    if not node.expr_id:
        object.__setattr__(node, "expr_id", _structural_expr_id(prefix, node))


def _finite_scalar(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} must be a real number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


@dataclass(frozen=True)
class DimensionTolerance:
    """Permitted lower and upper deviations from a nominal dimension.

    Deviations are signed: the lower deviation must be less than or equal to
    zero and the upper deviation must be greater than or equal to zero.
    """

    lower_deviation: float
    upper_deviation: float

    def __post_init__(self) -> None:
        lower = _finite_scalar(self.lower_deviation, label="lower_deviation")
        upper = _finite_scalar(self.upper_deviation, label="upper_deviation")
        if lower > 0.0:
            raise ValueError("lower_deviation must be less than or equal to zero")
        if upper < 0.0:
            raise ValueError("upper_deviation must be greater than or equal to zero")
        object.__setattr__(self, "lower_deviation", lower)
        object.__setattr__(self, "upper_deviation", upper)

    @classmethod
    def symmetric(cls, deviation: int | float) -> "DimensionTolerance":
        """Create a symmetric ``+/- deviation`` tolerance."""

        value = _finite_scalar(deviation, label="deviation")
        if value < 0.0:
            raise ValueError("deviation must be greater than or equal to zero")
        return cls(lower_deviation=-value, upper_deviation=value)

    @property
    def width(self) -> float:
        return self.upper_deviation - self.lower_deviation

    def to_dict(self) -> Dict[str, float]:
        return {
            "lower_deviation": self.lower_deviation,
            "upper_deviation": self.upper_deviation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DimensionTolerance":
        if not isinstance(data, Mapping):
            raise TypeError("Dimension tolerance payload must be an object")
        if "lower_deviation" not in data or "upper_deviation" not in data:
            raise ValueError(
                "Dimension tolerance payload requires lower_deviation and upper_deviation"
            )
        return cls(
            lower_deviation=data["lower_deviation"],
            upper_deviation=data["upper_deviation"],
        )


ToleranceLike = Union[
    int,
    float,
    Sequence[int | float],
    DimensionTolerance,
]


def coerce_dimension_tolerance(value: ToleranceLike) -> DimensionTolerance:
    """Normalize a symmetric scalar or ``(lower, upper)`` deviation pair."""

    if isinstance(value, DimensionTolerance):
        return value
    if isinstance(value, bool):
        raise TypeError("Tolerance must be a real number or a two-value sequence")
    if isinstance(value, Real):
        return DimensionTolerance.symmetric(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != 2:
            raise ValueError("Asymmetric tolerance must contain exactly two deviations")
        return DimensionTolerance(value[0], value[1])
    raise TypeError("Tolerance must be a real number or a two-value sequence")


_EXPR_OP_ARITY = {
    "add": 2,
    "sub": 2,
    "mul": 2,
    "div": 2,
    "pow": 2,
    "neg": 1,
    "abs": 1,
    "sin": 1,
    "cos": 1,
    "tan": 1,
    "sqrt": 1,
    "acos": 1,
    "asin": 1,
    "atan": 1,
    "atan2": 2,
}


class ScalarExprBase:
    """Base class for scalar expression nodes."""

    expr_id: str

    def evaluate(self, bindings: Mapping[str, float] | None = None) -> float:
        raise NotImplementedError

    def __float__(self) -> float:
        return float(self.evaluate())

    def __bool__(self) -> bool:
        raise TypeError(
            "Expression objects do not define truthiness. Evaluate them explicitly first."
        )

    def _binary_expr(self, op: str, other: ScalarLike) -> Expr:
        return Expr(op=op, args=(lift_scalar(self), lift_scalar(other)))

    def _rbinary_expr(self, op: str, other: ScalarLike) -> Expr:
        return Expr(op=op, args=(lift_scalar(other), lift_scalar(self)))

    def __add__(self, other: ScalarLike) -> Expr:
        return self._binary_expr("add", other)

    def __radd__(self, other: ScalarLike) -> Expr:
        return self._rbinary_expr("add", other)

    def __sub__(self, other: ScalarLike) -> Expr:
        return self._binary_expr("sub", other)

    def __rsub__(self, other: ScalarLike) -> Expr:
        return self._rbinary_expr("sub", other)

    def __mul__(self, other: ScalarLike) -> Expr:
        return self._binary_expr("mul", other)

    def __rmul__(self, other: ScalarLike) -> Expr:
        return self._rbinary_expr("mul", other)

    def __truediv__(self, other: ScalarLike) -> Expr:
        return self._binary_expr("div", other)

    def __rtruediv__(self, other: ScalarLike) -> Expr:
        return self._rbinary_expr("div", other)

    def __pow__(self, other: ScalarLike) -> Expr:
        return self._binary_expr("pow", other)

    def __rpow__(self, other: ScalarLike) -> Expr:
        return self._rbinary_expr("pow", other)

    def __neg__(self) -> Expr:
        return Expr(op="neg", args=(lift_scalar(self),))

    def __abs__(self) -> Expr:
        return Expr(op="abs", args=(lift_scalar(self),))


@dataclass(frozen=True)
class Const(ScalarExprBase):
    """Immutable constant node used in the v2 expression graph."""

    value: float
    expr_id: str = ""  # empty: derived from the content

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _finite_scalar(self.value, label="value"))
        _settle_expr_id(self, "const")

    def evaluate(self, bindings: Mapping[str, float] | None = None) -> float:
        return float(self.value)


@dataclass(frozen=True)
class Var(ScalarExprBase):
    """Named scalar parameter with optional physical-unit and tolerance intent.

    ``default`` and ``tolerance`` remain in their declared units. Evaluation,
    geometry parameters, and tolerance propagation convert them to SimpleCAD's
    canonical CAD units: millimeters for length and degrees for angle.
    """

    name: str
    default: float
    comment: str | None = None
    expr_id: str = ""  # empty: derived from the content
    tolerance: DimensionTolerance | None = None
    unit: Unit | None = None
    tolerance_unit: Unit | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Variable name must be a non-empty string")
        object.__setattr__(
            self, "default", _finite_scalar(self.default, label="Variable default")
        )
        if self.comment is not None and not isinstance(self.comment, str):
            raise ValueError("Variable comment must be a string when provided")
        if self.tolerance is not None and not isinstance(
            self.tolerance, DimensionTolerance
        ):
            raise TypeError("Variable tolerance must be a DimensionTolerance")
        if self.unit is not None and not isinstance(self.unit, Unit):
            object.__setattr__(self, "unit", get_unit(self.unit))
        if self.tolerance_unit is not None and not isinstance(
            self.tolerance_unit, Unit
        ):
            object.__setattr__(
                self, "tolerance_unit", get_unit(self.tolerance_unit)
            )
        if self.unit is None and self.tolerance_unit is not None:
            raise ValueError("A tolerance unit requires a nominal variable unit")
        if self.tolerance is None and self.tolerance_unit is not None:
            raise ValueError("A tolerance unit requires a declared tolerance")
        if self.tolerance is not None and self.unit is not None:
            if self.tolerance_unit is None:
                object.__setattr__(self, "tolerance_unit", self.unit)
            elif self.tolerance_unit.dimension != self.unit.dimension:
                raise ValueError(
                    "Variable tolerance unit must have the same dimension as its nominal unit"
                )
        if self.unit is not None:
            self.unit.to_canonical(self.default)
        if self.canonical_tolerance is not None:
            self.canonical_tolerance.width
        _settle_expr_id(self, "var")

    @property
    def dimension(self) -> Dimension | None:
        return None if self.unit is None else self.unit.dimension

    @property
    def canonical_default(self) -> float:
        return self.default if self.unit is None else self.unit.to_canonical(self.default)

    @property
    def canonical_tolerance(self) -> DimensionTolerance | None:
        if self.tolerance is None:
            return None
        if self.tolerance_unit is None:
            return self.tolerance
        return DimensionTolerance(
            self.tolerance_unit.to_canonical(self.tolerance.lower_deviation),
            self.tolerance_unit.to_canonical(self.tolerance.upper_deviation),
        )

    def evaluate(self, bindings: Mapping[str, float] | None = None) -> float:
        if bindings is not None and self.name in bindings:
            value = _finite_scalar(bindings[self.name], label=f"Binding '{self.name}'")
            return value if self.unit is None else self.unit.to_canonical(value)
        return self.canonical_default


@dataclass(frozen=True)
class Expr(ScalarExprBase):
    """Derived scalar expression node built from one or more operands."""

    op: str
    args: Tuple[ScalarExpr, ...]
    expr_id: str = ""  # empty: derived from the content

    def __post_init__(self) -> None:
        if not isinstance(self.args, tuple):
            object.__setattr__(self, "args", tuple(self.args))
        if not isinstance(self.op, str):
            raise TypeError("Expression op must be a string")
        if self.op not in _EXPR_OP_ARITY:
            raise ValueError(f"Unsupported expression op '{self.op}'")
        if len(self.args) != _EXPR_OP_ARITY[self.op]:
            raise ValueError(
                f"Expression op '{self.op}' expects {_EXPR_OP_ARITY[self.op]} arguments, "
                f"got {len(self.args)}"
            )
        if not all(isinstance(arg, (Const, Var, Expr)) for arg in self.args):
            raise TypeError("Expression arguments must be scalar expression nodes")
        _settle_expr_id(self, "expr")

    def evaluate(self, bindings: Mapping[str, float] | None = None) -> float:
        from .units import infer_dimension

        infer_dimension(self)
        values = [arg.evaluate(bindings) for arg in self.args]
        if self.op == "add":
            return values[0] + values[1]
        if self.op == "sub":
            return values[0] - values[1]
        if self.op == "mul":
            return values[0] * values[1]
        if self.op == "div":
            return values[0] / values[1]
        if self.op == "pow":
            return values[0] ** values[1]
        if self.op == "neg":
            return -values[0]
        if self.op == "abs":
            return abs(values[0])
        if self.op == "sin":
            from .units import expression_uses_units

            value = math.radians(values[0]) if expression_uses_units(self) else values[0]
            return math.sin(value)
        if self.op == "cos":
            from .units import expression_uses_units

            value = math.radians(values[0]) if expression_uses_units(self) else values[0]
            return math.cos(value)
        if self.op == "tan":
            from .units import expression_uses_units

            value = math.radians(values[0]) if expression_uses_units(self) else values[0]
            return math.tan(value)
        if self.op == "sqrt":
            return math.sqrt(values[0])
        if self.op == "acos":
            from .units import expression_uses_units

            result = math.acos(values[0])
            return math.degrees(result) if expression_uses_units(self) else result
        if self.op == "asin":
            from .units import expression_uses_units

            result = math.asin(values[0])
            return math.degrees(result) if expression_uses_units(self) else result
        if self.op == "atan":
            from .units import expression_uses_units

            result = math.atan(values[0])
            return math.degrees(result) if expression_uses_units(self) else result
        if self.op == "atan2":
            from .units import expression_uses_units

            result = math.atan2(values[0], values[1])
            return math.degrees(result) if expression_uses_units(self) else result
        raise ValueError(f"Unsupported expression op '{self.op}'")


ScalarExpr = Union[Const, Var, Expr]
ScalarLike = Union[int, float, ScalarExpr]


def const(value: int | float) -> Const:
    """Create a constant scalar node for parameterized modeling."""

    return Const(_finite_scalar(value, label="Constant value"))


def var(
    name: str,
    default: int | float,
    comment: str | None = None,
    tolerance: ToleranceLike | None = None,
    *,
    unit: UnitLike | None = None,
    tolerance_unit: UnitLike | None = None,
) -> Var:
    """Create a physical or legacy scalar variable.

    ``tolerance=0.1`` declares a symmetric ``+/-0.1`` tolerance. Use a
    ``(lower_deviation, upper_deviation)`` pair for an asymmetric tolerance.
    ``tolerance_unit`` defaults to ``unit`` when a nominal unit is declared.
    Values are converted to canonical CAD units only when evaluated, so the
    declaration and serialized expression node preserve the user's units.

    Variables without ``unit`` retain legacy unitless behavior. A unit-aware
    expression cannot mix declared-unit variables with legacy variables.
    """

    if not isinstance(name, str) or not name:
        raise ValueError("Variable name must be a non-empty string")
    if comment is not None and not isinstance(comment, str):
        raise ValueError("Variable comment must be a string when provided")
    return Var(
        name=name,
        default=_finite_scalar(default, label="Variable default"),
        comment=comment,
        tolerance=(
            coerce_dimension_tolerance(tolerance) if tolerance is not None else None
        ),
        unit=get_unit(unit) if unit is not None else None,
        tolerance_unit=(
            get_unit(tolerance_unit) if tolerance_unit is not None else None
        ),
    )


def lift_scalar(value: ScalarLike) -> ScalarExpr:
    if isinstance(value, (Const, Var, Expr)):
        return value
    if isinstance(value, bool):
        raise TypeError("Boolean values are not valid scalar expression inputs")
    if isinstance(value, (int, float)):
        return Const(float(value))
    raise TypeError(f"Unsupported scalar expression value: {type(value)!r}")


def evaluate_scalar(
    value: ScalarLike, bindings: Mapping[str, float] | None = None
) -> float:
    expr = lift_scalar(value)
    from .units import infer_dimension

    infer_dimension(expr)
    return float(expr.evaluate(bindings))


def sin(value: ScalarLike) -> Expr:
    return Expr(op="sin", args=(lift_scalar(value),))


def cos(value: ScalarLike) -> Expr:
    return Expr(op="cos", args=(lift_scalar(value),))


def tan(value: ScalarLike) -> Expr:
    return Expr(op="tan", args=(lift_scalar(value),))


def sqrt(value: ScalarLike) -> Expr:
    return Expr(op="sqrt", args=(lift_scalar(value),))


def acos(value: ScalarLike) -> Expr:
    return Expr(op="acos", args=(lift_scalar(value),))


def asin(value: ScalarLike) -> Expr:
    return Expr(op="asin", args=(lift_scalar(value),))


def atan(value: ScalarLike) -> Expr:
    return Expr(op="atan", args=(lift_scalar(value),))


def atan2(y: ScalarLike, x: ScalarLike) -> Expr:
    return Expr(op="atan2", args=(lift_scalar(y), lift_scalar(x)))


def evaluate_value(value: Any, bindings: Mapping[str, float] | None = None) -> Any:
    if isinstance(value, tuple):
        return tuple(evaluate_value(item, bindings) for item in value)
    if isinstance(value, list):
        return [evaluate_value(item, bindings) for item in value]
    if isinstance(value, dict):
        return {key: evaluate_value(item, bindings) for key, item in value.items()}
    if isinstance(value, (Const, Var, Expr, int, float)) and not isinstance(
        value, bool
    ):
        return evaluate_scalar(value, bindings)
    return value


def _expr_to_node_payload(expr: ScalarExpr) -> Dict[str, Any]:
    if isinstance(expr, Const):
        return {
            "expr_id": expr.expr_id,
            "kind": "const",
            "value": float(expr.value),
        }
    if isinstance(expr, Var):
        payload = {
            "expr_id": expr.expr_id,
            "kind": "var",
            "name": expr.name,
            "default": float(expr.default),
        }
        if expr.comment:
            payload["comment"] = expr.comment
        if expr.tolerance is not None:
            payload["tolerance"] = expr.tolerance.to_dict()
        if expr.unit is not None:
            payload["unit"] = unit_to_payload(expr.unit)
        if expr.tolerance_unit is not None:
            payload["tolerance_unit"] = unit_to_payload(expr.tolerance_unit)
        return payload
    return {
        "expr_id": expr.expr_id,
        "kind": "expr",
        "op": expr.op,
        "args": [arg.expr_id for arg in expr.args],
    }


def _expr_signature(expr: ScalarExpr) -> Tuple[Any, ...]:
    if isinstance(expr, Const):
        return ("const", expr.value.hex())
    if isinstance(expr, Var):
        tolerance = (
            None
            if expr.tolerance is None
            else (
                expr.tolerance.lower_deviation.hex(),
                expr.tolerance.upper_deviation.hex(),
            )
        )
        return (
            "var",
            expr.name,
            expr.default.hex(),
            expr.comment,
            tolerance,
            None
            if expr.unit is None
            else (
                expr.unit.symbol,
                expr.unit.dimension.length,
                expr.unit.dimension.angle,
                expr.unit.scale_to_canonical.hex(),
            ),
            None
            if expr.tolerance_unit is None
            else (
                expr.tolerance_unit.symbol,
                expr.tolerance_unit.dimension.length,
                expr.tolerance_unit.dimension.angle,
                expr.tolerance_unit.scale_to_canonical.hex(),
            ),
        )
    return ("expr", expr.op, tuple(arg.expr_id for arg in expr.args))


class ExpressionGraph:
    """A lightweight registry of expression DAG nodes."""

    def __init__(self) -> None:
        self._nodes: Dict[str, ScalarExpr] = {}

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    def get(self, expr_id: str) -> ScalarExpr | None:
        return self._nodes.get(expr_id)

    def register(self, value: ScalarLike) -> ScalarExpr:
        expr = lift_scalar(value)
        staged: Dict[str, ScalarExpr] = {}
        visiting: set[str] = set()
        validated_objects: set[int] = set()

        def stage(node: ScalarExpr) -> None:
            if node.expr_id in visiting:
                raise ValueError(
                    f"Expression graph contains a cycle at '{node.expr_id}'"
                )
            existing = staged.get(node.expr_id)
            if existing is None:
                existing = self._nodes.get(node.expr_id)
            if existing is not None:
                if _expr_signature(existing) != _expr_signature(node):
                    raise ValueError(
                        f"Expression id '{node.expr_id}' is already registered by a different node"
                    )
            else:
                staged[node.expr_id] = node
            object_id = id(node)
            if object_id in validated_objects:
                return
            visiting.add(node.expr_id)
            if isinstance(node, Expr):
                for arg in node.args:
                    stage(arg)
            visiting.remove(node.expr_id)
            validated_objects.add(object_id)

        stage(expr)
        from .units import infer_dimension

        infer_dimension(expr)
        self._nodes.update(staged)
        return expr

    def _topological_expr_ids(self) -> List[str]:
        ordered: List[str] = []
        seen: set[str] = set()
        visiting: set[str] = set()

        def visit(expr: ScalarExpr) -> None:
            if expr.expr_id in seen:
                return
            if expr.expr_id in visiting:
                raise ValueError(
                    f"Expression graph contains a cycle at '{expr.expr_id}'"
                )
            visiting.add(expr.expr_id)
            if isinstance(expr, Expr):
                for arg in expr.args:
                    visit(arg)
            visiting.remove(expr.expr_id)
            seen.add(expr.expr_id)
            ordered.append(expr.expr_id)

        for expr in list(self._nodes.values()):
            visit(expr)
        return ordered

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [
                _expr_to_node_payload(self._nodes[expr_id])
                for expr_id in self._topological_expr_ids()
            ]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExpressionGraph":
        if not isinstance(data, dict):
            raise TypeError("Expression graph payload must be an object")
        raw_nodes = data.get("nodes", [])
        if not isinstance(raw_nodes, list):
            raise TypeError("Expression graph 'nodes' must be an array")

        graph = cls()
        payload_by_id: Dict[str, Dict[str, Any]] = {}
        for node in raw_nodes:
            if not isinstance(node, dict):
                raise TypeError("Expression graph nodes must be objects")
            if "expr_id" not in node:
                raise ValueError("Expression graph node is missing 'expr_id'")
            expr_id_value = node["expr_id"]
            if not isinstance(expr_id_value, str) or not expr_id_value:
                raise ValueError("Expression graph node id must be non-empty")
            expr_id = expr_id_value
            if expr_id in payload_by_id:
                raise ValueError(f"Duplicate expression node id '{expr_id}'")
            payload_by_id[expr_id] = node

        node_map: Dict[str, ScalarExpr] = {}
        visiting: set[str] = set()

        def build(expr_id: str) -> ScalarExpr:
            if expr_id in node_map:
                return node_map[expr_id]
            if expr_id in visiting:
                raise ValueError(f"Expression graph contains a cycle at '{expr_id}'")
            node = payload_by_id.get(expr_id)
            if node is None:
                raise ValueError(f"Unknown expression dependency '{expr_id}'")
            visiting.add(expr_id)
            kind = node.get("kind")
            if kind == "const":
                if "value" not in node:
                    raise ValueError(
                        f"Constant expression node '{expr_id}' is missing 'value'"
                    )
                expr = Const(value=node["value"], expr_id=expr_id)
            elif kind == "var":
                if "name" not in node or "default" not in node:
                    raise ValueError(
                        f"Variable expression node '{expr_id}' requires 'name' and 'default'"
                    )
                tolerance_payload = node.get("tolerance")
                expr = Var(
                    name=node["name"],
                    default=node["default"],
                    comment=node.get("comment"),
                    tolerance=(
                        DimensionTolerance.from_dict(tolerance_payload)
                        if tolerance_payload is not None
                        else None
                    ),
                    unit=(
                        unit_from_payload(node["unit"])
                        if "unit" in node
                        else None
                    ),
                    tolerance_unit=(
                        unit_from_payload(node["tolerance_unit"])
                        if "tolerance_unit" in node
                        else None
                    ),
                    expr_id=expr_id,
                )
            elif kind == "expr":
                if "op" not in node:
                    raise ValueError(
                        f"Derived expression node '{expr_id}' is missing 'op'"
                    )
                raw_args = node.get("args", [])
                if not isinstance(raw_args, list):
                    raise TypeError(
                        f"Expression node '{expr_id}' field 'args' must be an array"
                    )
                if not all(isinstance(arg_id, str) for arg_id in raw_args):
                    raise TypeError(
                        f"Expression node '{expr_id}' dependencies must be string ids"
                    )
                args = tuple(build(arg_id) for arg_id in raw_args)
                expr = Expr(op=node["op"], args=args, expr_id=expr_id)
            else:
                raise ValueError(f"Unknown expression node kind: {kind!r}")
            visiting.remove(expr_id)
            graph._nodes[expr_id] = expr
            node_map[expr_id] = expr
            return expr

        for expr_id in payload_by_id:
            build(expr_id)
        from .units import infer_dimension

        for expr in node_map.values():
            infer_dimension(expr)
        return graph


def _canonicalize_param_value(
    value: Any, expression_graph: ExpressionGraph
) -> Tuple[Any, Any | None]:
    if isinstance(value, tuple):
        numeric_items: List[Any] = []
        expr_items: List[Any] = []
        has_expr = False
        for item in value:
            numeric_item, expr_item = _canonicalize_param_value(item, expression_graph)
            numeric_items.append(numeric_item)
            expr_items.append(expr_item)
            has_expr = has_expr or expr_item is not None
        return tuple(numeric_items), expr_items if has_expr else None

    if isinstance(value, list):
        numeric_items = []
        expr_items = []
        has_expr = False
        for item in value:
            numeric_item, expr_item = _canonicalize_param_value(item, expression_graph)
            numeric_items.append(numeric_item)
            expr_items.append(expr_item)
            has_expr = has_expr or expr_item is not None
        return numeric_items, expr_items if has_expr else None

    if isinstance(value, dict):
        numeric_dict: Dict[str, Any] = {}
        expr_dict: Dict[str, Any] = {}
        for key, item in value.items():
            numeric_item, expr_item = _canonicalize_param_value(item, expression_graph)
            numeric_dict[str(key)] = numeric_item
            if expr_item is not None:
                expr_dict[str(key)] = expr_item
        return numeric_dict, expr_dict or None

    if isinstance(value, (Const, Var, Expr)):
        expr = expression_graph.register(cast(ScalarLike, value))
        return float(expr.evaluate()), {"expr_id": expr.expr_id}

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), None

    return value, None


def _is_discrete_param_name(key: str) -> bool:
    key_lower = key.lower()
    return key_lower.endswith("_indices") or key_lower in {
        "edge_count",
        "face_count",
        "geo_selector",
        "removed_face_count",
        "profile_count",
        "profile",
        "count",
        "degree",
        "multiplicities",
        "output_count",
        "periodic",
        "tag_binding",
    }


def canonicalize_params(
    params: Dict[str, Any] | None,
    expression_graph: ExpressionGraph,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not params:
        return {}, {}

    numeric_params: Dict[str, Any] = {}
    param_exprs: Dict[str, Any] = {}
    for key, value in params.items():
        if _is_discrete_param_name(key):
            numeric_params[key] = value
            continue
        numeric_value, expr_value = _canonicalize_param_value(value, expression_graph)
        numeric_params[key] = numeric_value
        if expr_value is not None:
            param_exprs[key] = expr_value
    return numeric_params, param_exprs


def referenced_expressions(
    param_exprs: Mapping[str, Any], expression_graph: ExpressionGraph
) -> Tuple[ScalarExpr, ...]:
    """Return the expressions *param_exprs* refers to, in first-use order.

    *param_exprs* is the second value of :func:`canonicalize_params`: the
    params' nesting with a ``{"expr_id": ...}`` leaf for every expression.
    Registering the returned expressions in another graph (which also
    registers their operands) makes the ids resolvable there.
    """

    found: Dict[str, ScalarExpr] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            expr_id = value.get("expr_id")
            if len(value) == 1 and isinstance(expr_id, str):
                expr = expression_graph.get(expr_id)
                if expr is None:
                    raise KeyError(f"unknown expression id '{expr_id}'")
                found.setdefault(expr_id, expr)
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for item in param_exprs.values():
        visit(item)
    return tuple(found.values())
