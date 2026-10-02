"""Manufacturing-tolerance propagation over scalar expression graphs."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, localcontext
from fractions import Fraction
import math
from typing import Any, Dict, List, Literal, Mapping, Tuple
import uuid

from ..errors import SimpleCADMessageError
from .expr import (
    Const,
    DimensionTolerance,
    Expr,
    ExpressionGraph,
    ScalarExpr,
    ScalarLike,
    ToleranceLike,
    Var,
    coerce_dimension_tolerance,
    lift_scalar,
)
from .units import (
    ANGLE,
    Dimension,
    Unit,
    UnitLike,
    canonical_unit_for_dimension,
    expression_uses_units,
    get_unit,
    infer_dimension,
    unit_from_payload,
    unit_to_payload,
)


ToleranceMethod = Literal["worst_case", "rss"]
_SUPPORTED_METHODS = {"worst_case", "rss"}
_AffineForm = Tuple[Fraction, Dict[str, Fraction]]


class ToleranceAnalysisError(SimpleCADMessageError):
    """Raised when a tolerance chain cannot be propagated safely."""

    operation = "tolerance_analysis"


class ToleranceValidationError(SimpleCADMessageError):
    """Raised when one or more declared tolerance requirements fail."""

    operation = "tolerance_validation"

    def __init__(self, report: "ToleranceReport") -> None:
        self.report = report
        failed = [check.requirement.name for check in report.checks if not check.passed]
        super().__init__("Tolerance requirements failed: " + ", ".join(failed))


@dataclass(frozen=True)
class ToleranceContribution:
    """One source dimension's propagated contribution to a result."""

    variable_expr_id: str
    variable_name: str
    nominal: float
    source_tolerance: DimensionTolerance
    sensitivity: float | None
    lower_deviation: float
    upper_deviation: float
    source_unit: Unit | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variable_expr_id": self.variable_expr_id,
            "variable_name": self.variable_name,
            "nominal": self.nominal,
            "source_tolerance": self.source_tolerance.to_dict(),
            "sensitivity": self.sensitivity,
            "lower_deviation": self.lower_deviation,
            "upper_deviation": self.upper_deviation,
            "source_unit": (
                None
                if self.source_unit is None
                else unit_to_payload(self.source_unit)
            ),
        }


@dataclass(frozen=True)
class ToleranceAnalysis:
    """Nominal value and propagated limits for an expression."""

    target_expr_id: str
    method: ToleranceMethod
    nominal: float
    lower_bound: float
    upper_bound: float
    lower_deviation: float
    upper_deviation: float
    dimension: Dimension | None = None
    unit: Unit | None = None
    contributions: Tuple[ToleranceContribution, ...] = ()

    def __post_init__(self) -> None:
        values = (
            self.nominal,
            self.lower_bound,
            self.upper_bound,
            self.lower_deviation,
            self.upper_deviation,
        )
        if not all(math.isfinite(value) for value in values):
            raise ToleranceAnalysisError(
                "Tolerance analysis values must all be finite"
            )
        if self.lower_bound > self.upper_bound:
            raise ToleranceAnalysisError("Tolerance analysis bounds are inverted")
        if self.lower_bound > self.nominal or self.upper_bound < self.nominal:
            raise ToleranceAnalysisError(
                "Tolerance analysis bounds must enclose the nominal value"
            )
        if self.lower_deviation > 0.0 or self.upper_deviation < 0.0:
            raise ToleranceAnalysisError(
                "Tolerance analysis deviations must enclose the nominal value"
            )
        if self.unit is not None:
            if self.dimension is None or self.unit.dimension != self.dimension:
                raise ToleranceAnalysisError(
                    "Tolerance analysis unit must match its result dimension"
                )
        elif self.dimension is not None:
            raise ToleranceAnalysisError(
                "A dimensioned tolerance analysis requires a canonical result unit"
            )

    @property
    def tolerance(self) -> DimensionTolerance:
        return DimensionTolerance(self.lower_deviation, self.upper_deviation)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_expr_id": self.target_expr_id,
            "method": self.method,
            "nominal": self.nominal,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "lower_deviation": self.lower_deviation,
            "upper_deviation": self.upper_deviation,
            "dimension": (
                None if self.dimension is None else self.dimension.to_dict()
            ),
            "unit": None if self.unit is None else unit_to_payload(self.unit),
            "contributions": [item.to_dict() for item in self.contributions],
        }


@dataclass(frozen=True)
class ToleranceRequirement:
    """Permitted result deviations for one derived dimension."""

    requirement_id: str
    target_expr_id: str
    tolerance: DimensionTolerance
    method: ToleranceMethod = "worst_case"
    name: str = ""
    tolerance_unit: Unit | None = None
    target_dimension: Dimension | None = None
    # The target expression itself. Not part of the payload (that stores
    # ``target_expr_id``); kept so a requirement can be declared again in
    # another session, e.g. when a notebook projects its product.
    target: ScalarExpr | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.requirement_id, str) or not self.requirement_id:
            raise ValueError("Tolerance requirement id must be a non-empty string")
        if not isinstance(self.target_expr_id, str) or not self.target_expr_id:
            raise ValueError("Tolerance target expression id must be a non-empty string")
        if self.target is not None and self.target.expr_id != self.target_expr_id:
            raise ValueError("Tolerance target expression does not match target_expr_id")
        _validate_method(self.method)
        if not isinstance(self.tolerance, DimensionTolerance):
            raise TypeError(
                "Tolerance requirement tolerance must be a DimensionTolerance"
            )
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Tolerance requirement name must be a non-empty string")
        if self.tolerance_unit is not None and not isinstance(
            self.tolerance_unit, Unit
        ):
            raise TypeError("Tolerance requirement unit must be a Unit")
        if self.target_dimension is not None and not isinstance(
            self.target_dimension, Dimension
        ):
            raise TypeError("Tolerance target dimension must be a Dimension")
        if (
            self.target_dimension is not None
            and not self.target_dimension.is_design_dimension
        ):
            raise ValueError(
                "Manufacturing tolerance requirements require a Length or Angle target"
            )
        if self.tolerance_unit is not None:
            if self.target_dimension is None:
                raise ValueError(
                    "A tolerance unit requires a unit-aware target expression"
                )
            if self.tolerance_unit.dimension != self.target_dimension:
                raise ValueError(
                    "Tolerance requirement unit must match the target expression dimension"
                )
        elif self.target_dimension is not None:
            raise ValueError(
                "A dimensioned tolerance requirement requires a tolerance unit"
            )

    @property
    def canonical_tolerance(self) -> DimensionTolerance:
        if self.tolerance_unit is None:
            return self.tolerance
        return DimensionTolerance(
            self.tolerance_unit.to_canonical(self.tolerance.lower_deviation),
            self.tolerance_unit.to_canonical(self.tolerance.upper_deviation),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "target_expr_id": self.target_expr_id,
            "tolerance": self.tolerance.to_dict(),
            "method": self.method,
            "name": self.name,
            "tolerance_unit": (
                None
                if self.tolerance_unit is None
                else unit_to_payload(self.tolerance_unit)
            ),
            "target_dimension": (
                None
                if self.target_dimension is None
                else self.target_dimension.to_dict()
            ),
        }


@dataclass(frozen=True)
class ToleranceCheck:
    """Validation result for one tolerance requirement."""

    requirement: ToleranceRequirement
    analysis: ToleranceAnalysis
    passed: bool
    lower_margin: float
    upper_margin: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "analysis": self.analysis.to_dict(),
            "passed": self.passed,
            "lower_margin": self.lower_margin,
            "upper_margin": self.upper_margin,
        }


@dataclass(frozen=True)
class ToleranceReport:
    """Validation report for every requirement in a tolerance graph."""

    checks: Tuple[ToleranceCheck, ...] = ()

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class _Interval:
    lower: float
    upper: float
    varies: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.lower) or not math.isfinite(self.upper):
            raise ToleranceAnalysisError("Tolerance propagation produced a non-finite interval")
        if self.lower > self.upper:
            raise ToleranceAnalysisError("Tolerance propagation produced an inverted interval")


def _validate_method(method: str) -> ToleranceMethod:
    if not isinstance(method, str):
        raise TypeError("Tolerance propagation method must be a string")
    if method not in _SUPPORTED_METHODS:
        raise ValueError(
            f"Unsupported tolerance propagation method '{method}'; "
            "expected 'worst_case' or 'rss'"
        )
    return method  # type: ignore[return-value]


def _validate_expression_identity(expr: ScalarExpr) -> None:
    signatures: Dict[str, Tuple[Any, ...]] = {}
    visiting: set[str] = set()
    validated_objects: set[int] = set()

    def signature(node: ScalarExpr) -> Tuple[Any, ...]:
        if isinstance(node, Const):
            return ("const", node.value.hex())
        if isinstance(node, Var):
            tolerance = (
                None
                if node.tolerance is None
                else (
                    node.tolerance.lower_deviation.hex(),
                    node.tolerance.upper_deviation.hex(),
                )
            )
            return (
                "var",
                node.name,
                node.default.hex(),
                node.comment,
                tolerance,
                None if node.unit is None else node.unit.symbol,
                None
                if node.tolerance_unit is None
                else node.tolerance_unit.symbol,
            )
        return ("expr", node.op, tuple(arg.expr_id for arg in node.args))

    def visit(node: ScalarExpr) -> None:
        if node.expr_id in visiting:
            raise ToleranceAnalysisError(
                f"Expression graph contains a cycle at '{node.expr_id}'"
            )
        node_signature = signature(node)
        existing = signatures.get(node.expr_id)
        if existing is not None and existing != node_signature:
            raise ToleranceAnalysisError(
                f"Expression id '{node.expr_id}' refers to multiple structural nodes"
            )
        signatures[node.expr_id] = node_signature
        object_id = id(node)
        if object_id in validated_objects:
            return
        visiting.add(node.expr_id)
        if isinstance(node, Expr):
            for arg in node.args:
                visit(arg)
        visiting.remove(node.expr_id)
        validated_objects.add(object_id)

    visit(expr)


def _variables(expr: ScalarExpr) -> Tuple[Var, ...]:
    variables: Dict[str, Var] = {}
    visiting: set[str] = set()

    def visit(node: ScalarExpr) -> None:
        if node.expr_id in visiting:
            raise ToleranceAnalysisError(
                f"Expression graph contains a cycle at '{node.expr_id}'"
            )
        if isinstance(node, Var):
            existing = variables.get(node.expr_id)
            if existing is not None and existing != node:
                raise ToleranceAnalysisError(
                    f"Expression id '{node.expr_id}' refers to multiple variables"
                )
            variables[node.expr_id] = node
            return
        if not isinstance(node, Expr):
            return
        visiting.add(node.expr_id)
        for arg in node.args:
            visit(arg)
        visiting.remove(node.expr_id)

    visit(expr)
    return tuple(sorted(variables.values(), key=lambda item: item.expr_id))


def _require_source_tolerances(variables: Tuple[Var, ...]) -> None:
    missing = [f"{var.name} ({var.expr_id})" for var in variables if var.tolerance is None]
    if missing:
        raise ToleranceAnalysisError(
            "Every variable in a tolerance chain must declare a tolerance; missing: "
            + ", ".join(missing)
        )


def _finite_fsum(values: List[float], *, label: str) -> float:
    try:
        result = math.fsum(values)
    except OverflowError as exc:
        raise ToleranceAnalysisError(f"{label} is non-finite") from exc
    if not math.isfinite(result):
        raise ToleranceAnalysisError(f"{label} is non-finite")
    return result


def _fraction_to_decimal(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


def _decimal_to_float(
    value: Decimal,
    *,
    label: str,
    allow_unrepresentable: bool = False,
    outward: bool = False,
) -> float | None:
    if not value.is_finite():
        raise ToleranceAnalysisError(f"{label} is non-finite")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        if allow_unrepresentable:
            return None
        raise ToleranceAnalysisError(f"{label} is outside the supported float range")
    if not math.isfinite(result):
        if allow_unrepresentable:
            return None
        raise ToleranceAnalysisError(f"{label} is outside the supported float range")
    if result == 0.0 and value != 0:
        return math.copysign(math.ulp(0.0), -1.0 if value < 0 else 1.0)
    if outward and value != 0:
        represented = Decimal.from_float(result)
        if value < 0 and represented > value:
            result = math.nextafter(result, -math.inf)
        elif value > 0 and represented < value:
            result = math.nextafter(result, math.inf)
    return result


def _sensitivity_decimal(value: Decimal | Fraction | float) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Fraction):
        return _fraction_to_decimal(value)
    return Decimal.from_float(value)


def _mul_interval(left: _Interval, right: _Interval) -> _Interval:
    products = (
        left.lower * right.lower,
        left.lower * right.upper,
        left.upper * right.lower,
        left.upper * right.upper,
    )
    return _outward_interval(
        min(products), max(products), varies=left.varies or right.varies
    )


def _reciprocal_interval(value: _Interval) -> _Interval:
    if value.lower <= 0.0 <= value.upper:
        raise ToleranceAnalysisError(
            "Cannot propagate division because the denominator tolerance interval contains zero"
        )
    reciprocal = (1.0 / value.lower, 1.0 / value.upper)
    return _outward_interval(
        min(reciprocal), max(reciprocal), varies=value.varies
    )


def _integer_power_interval(base: _Interval, exponent: int) -> _Interval:
    if exponent == 0:
        return _Interval(1.0, 1.0)
    if exponent < 0:
        return _reciprocal_interval(_integer_power_interval(base, -exponent))
    values = (base.lower**exponent, base.upper**exponent)
    if exponent % 2 == 0 and base.lower <= 0.0 <= base.upper:
        return _bounded_outward_interval(
            0.0,
            max(values),
            minimum=0.0,
            maximum=math.inf,
            varies=base.varies,
        )
    return _outward_interval(
        min(values), max(values), varies=base.varies
    )


def _pow_interval(base: _Interval, exponent: _Interval) -> _Interval:
    exponent_is_point = exponent.lower == exponent.upper
    if exponent_is_point and float(exponent.lower).is_integer():
        return _integer_power_interval(base, int(exponent.lower))

    if base.lower < 0.0:
        raise ToleranceAnalysisError(
            "Cannot propagate a non-integer or varying power over a negative base interval"
        )
    if base.lower == 0.0 and exponent.lower <= 0.0:
        raise ToleranceAnalysisError(
            "Power tolerance interval includes an undefined or unbounded zero-base value"
        )

    candidates: List[float] = []
    if base.lower == 0.0:
        candidates.append(0.0)
    for base_value in {base.lower, base.upper}:
        if base_value == 0.0:
            continue
        for exponent_value in {exponent.lower, exponent.upper}:
            candidates.append(base_value**exponent_value)
    if not candidates or not all(math.isfinite(value) for value in candidates):
        raise ToleranceAnalysisError("Power tolerance propagation is non-finite")
    return _outward_interval(
        min(candidates),
        max(candidates),
        varies=base.varies or exponent.varies,
    )


def _outward_interval(
    lower: float, upper: float, *, varies: bool = False
) -> _Interval:
    if not math.isfinite(lower) or not math.isfinite(upper):
        raise ToleranceAnalysisError(
            "Tolerance propagation produced a non-finite interval"
        )
    if lower == upper and not varies:
        return _Interval(lower, upper)
    return _Interval(
        math.nextafter(lower, -math.inf),
        math.nextafter(upper, math.inf),
        varies,
    )


def _bounded_outward_interval(
    lower: float,
    upper: float,
    *,
    minimum: float,
    maximum: float,
    varies: bool = False,
) -> _Interval:
    if lower == upper and not varies:
        return _Interval(lower, upper)
    outward_lower = (
        minimum if lower <= minimum else math.nextafter(lower, -math.inf)
    )
    outward_upper = (
        maximum if upper >= maximum else math.nextafter(upper, math.inf)
    )
    return _Interval(outward_lower, outward_upper, varies)


def _bound_from_deviation(nominal: float, deviation: float) -> float:
    if deviation == 0.0:
        return nominal
    bound = nominal + deviation
    if not math.isfinite(bound):
        raise ToleranceAnalysisError(
            "Tolerance bound is non-finite at the declared nominal value"
        )
    direction = -math.inf if deviation < 0.0 else math.inf
    if (deviation < 0.0 and bound >= nominal) or (
        deviation > 0.0 and bound <= nominal
    ):
        bound = nominal
    return math.nextafter(bound, direction)


def _contains_periodic_point(
    interval: _Interval, *, first: float, period: float
) -> bool:
    if not interval.varies or interval.lower == interval.upper:
        return False
    if max(abs(interval.lower), abs(interval.upper)) >= 2.0**50 * period:
        return True
    first_index = math.ceil((interval.lower - first) / period)
    point = first + first_index * period
    return point <= interval.upper


def _angle_interval_to_radians(value: _Interval) -> _Interval:
    return _outward_interval(
        math.radians(value.lower),
        math.radians(value.upper),
        varies=value.varies,
    )


def _angle_interval_to_degrees(value: _Interval) -> _Interval:
    return _outward_interval(
        math.degrees(value.lower),
        math.degrees(value.upper),
        varies=value.varies,
    )


def _sin_interval(value: _Interval) -> _Interval:
    if value.upper - value.lower >= 2.0 * math.pi:
        return _Interval(-1.0, 1.0)
    candidates = [math.sin(value.lower), math.sin(value.upper)]
    if _contains_periodic_point(value, first=math.pi / 2.0, period=2.0 * math.pi):
        candidates.append(1.0)
    if _contains_periodic_point(value, first=-math.pi / 2.0, period=2.0 * math.pi):
        candidates.append(-1.0)
    return _bounded_outward_interval(
        min(candidates),
        max(candidates),
        minimum=-1.0,
        maximum=1.0,
        varies=value.varies,
    )


def _cos_interval(value: _Interval) -> _Interval:
    if value.upper - value.lower >= 2.0 * math.pi:
        return _Interval(-1.0, 1.0)
    candidates = [math.cos(value.lower), math.cos(value.upper)]
    if _contains_periodic_point(value, first=0.0, period=2.0 * math.pi):
        candidates.append(1.0)
    if _contains_periodic_point(value, first=math.pi, period=2.0 * math.pi):
        candidates.append(-1.0)
    return _bounded_outward_interval(
        min(candidates),
        max(candidates),
        minimum=-1.0,
        maximum=1.0,
        varies=value.varies,
    )


def _tan_interval(value: _Interval) -> _Interval:
    if _contains_periodic_point(value, first=math.pi / 2.0, period=math.pi):
        raise ToleranceAnalysisError(
            "Cannot propagate tangent across a discontinuity in the tolerance interval"
        )
    tangent = (math.tan(value.lower), math.tan(value.upper))
    return _outward_interval(
        min(tangent), max(tangent), varies=value.varies
    )


def _interval_has_negative_side(value: _Interval) -> bool:
    return value.lower < 0.0 or (
        value.lower == 0.0 and math.copysign(1.0, value.lower) < 0.0
    )


def _interval_has_positive_side(value: _Interval) -> bool:
    return value.upper > 0.0 or (
        value.upper == 0.0 and math.copysign(1.0, value.upper) > 0.0
    )


def _atan2_interval(
    y: _Interval, x: _Interval, *, reject_branch_cut: bool = False
) -> _Interval:
    if x.lower <= 0.0 <= x.upper and y.lower <= 0.0 <= y.upper:
        raise ToleranceAnalysisError(
            "Cannot propagate atan2 because the tolerance region contains the undefined origin"
        )
    crosses_branch_cut = (
        x.upper < 0.0
        and _interval_has_negative_side(y)
        and _interval_has_positive_side(y)
    )
    if crosses_branch_cut:
        if reject_branch_cut:
            raise ToleranceAnalysisError(
                "RSS cannot propagate atan2 across its negative-x-axis branch cut"
            )
        return _Interval(-math.pi, math.pi, True)

    points = [
        math.atan2(y_value, x_value)
        for y_value in {y.lower, y.upper}
        for x_value in {x.lower, x.upper}
    ]
    return _bounded_outward_interval(
        min(points),
        max(points),
        minimum=-math.pi,
        maximum=math.pi,
        varies=y.varies or x.varies,
    )


def _affine_interval(
    affine: _AffineForm, variables: Mapping[str, Var]
) -> _Interval:
    nominal = affine[0]
    lower_deviations: List[Fraction] = []
    upper_deviations: List[Fraction] = []
    for expr_id, coefficient in affine[1].items():
        variable = variables.get(expr_id)
        if variable is None or variable.canonical_tolerance is None:
            raise ToleranceAnalysisError(
                f"Unknown or untoleranced affine variable '{expr_id}'"
            )
        source_tolerance = variable.canonical_tolerance
        nominal += coefficient * Fraction.from_float(variable.canonical_default)
        deviations = (
            coefficient
            * Fraction.from_float(source_tolerance.lower_deviation),
            coefficient
            * Fraction.from_float(source_tolerance.upper_deviation),
        )
        lower_deviations.append(min(deviations))
        upper_deviations.append(max(deviations))
    with localcontext() as context:
        context.prec = 100
        nominal_value = _decimal_to_float(
            _fraction_to_decimal(nominal), label="Affine nominal value"
        )
        lower_deviation = _decimal_to_float(
            _fraction_to_decimal(sum(lower_deviations, Fraction(0))),
            label="Affine lower deviation",
            outward=True,
        )
        upper_deviation = _decimal_to_float(
            _fraction_to_decimal(sum(upper_deviations, Fraction(0))),
            label="Affine upper deviation",
            outward=True,
        )
    if (
        nominal_value is None
        or lower_deviation is None
        or upper_deviation is None
    ):
        raise ToleranceAnalysisError("Affine tolerance interval is not representable")
    return _Interval(
        _bound_from_deviation(nominal_value, lower_deviation),
        _bound_from_deviation(nominal_value, upper_deviation),
        any(item != 0.0 for item in lower_deviations + upper_deviations),
    )


def _interval_value(
    expr: ScalarExpr,
    cache: Dict[str, _Interval],
    variables: Mapping[str, Var] | None = None,
    *,
    reject_atan2_branch_cut: bool = False,
) -> _Interval:
    cached = cache.get(expr.expr_id)
    if cached is not None:
        return cached
    variable_map = variables
    if variable_map is None:
        variable_map = {item.expr_id: item for item in _variables(expr)}
    if isinstance(expr, Const):
        result = _Interval(expr.value, expr.value)
    elif isinstance(expr, Var):
        source_tolerance = expr.canonical_tolerance
        if source_tolerance is None:
            raise ToleranceAnalysisError(
                f"Variable '{expr.name}' ({expr.expr_id}) has no declared tolerance"
            )
        result = _Interval(
            _bound_from_deviation(
                expr.canonical_default, source_tolerance.lower_deviation
            ),
            _bound_from_deviation(
                expr.canonical_default, source_tolerance.upper_deviation
            ),
            source_tolerance.width > 0.0,
        )
    else:
        affine = _affine_form(expr, {}, {})
        if affine is not None:
            result = _affine_interval(affine, variable_map)
            cache[expr.expr_id] = result
            return result
        args = [
            _interval_value(
                arg,
                cache,
                variable_map,
                reject_atan2_branch_cut=reject_atan2_branch_cut,
            )
            for arg in expr.args
        ]
        if expr.op == "add":
            result = _outward_interval(
                args[0].lower + args[1].lower,
                args[0].upper + args[1].upper,
                varies=args[0].varies or args[1].varies,
            )
        elif expr.op == "sub":
            result = _outward_interval(
                args[0].lower - args[1].upper,
                args[0].upper - args[1].lower,
                varies=args[0].varies or args[1].varies,
            )
        elif expr.op == "mul":
            if expr.args[0].expr_id == expr.args[1].expr_id:
                result = _integer_power_interval(args[0], 2)
            else:
                result = _mul_interval(args[0], args[1])
        elif expr.op == "div":
            reciprocal = _reciprocal_interval(args[1])
            if expr.args[0].expr_id == expr.args[1].expr_id:
                result = _Interval(1.0, 1.0)
            else:
                result = _mul_interval(args[0], reciprocal)
        elif expr.op == "pow":
            result = _pow_interval(args[0], args[1])
        elif expr.op == "neg":
            result = _outward_interval(
                -args[0].upper, -args[0].lower, varies=args[0].varies
            )
        elif expr.op == "abs":
            if args[0].lower <= 0.0 <= args[0].upper:
                upper = max(-args[0].lower, args[0].upper)
                result = (
                    _Interval(0.0, 0.0)
                    if not args[0].varies and upper == 0.0
                    else _Interval(
                        0.0,
                        math.nextafter(upper, math.inf),
                        args[0].varies,
                    )
                )
            else:
                values = (abs(args[0].lower), abs(args[0].upper))
                result = _bounded_outward_interval(
                    min(values),
                    max(values),
                    minimum=0.0,
                    maximum=math.inf,
                    varies=args[0].varies,
                )
        elif expr.op == "sin":
            result = _sin_interval(
                _angle_interval_to_radians(args[0])
                if expression_uses_units(expr)
                else args[0]
            )
        elif expr.op == "cos":
            result = _cos_interval(
                _angle_interval_to_radians(args[0])
                if expression_uses_units(expr)
                else args[0]
            )
        elif expr.op == "tan":
            result = _tan_interval(
                _angle_interval_to_radians(args[0])
                if expression_uses_units(expr)
                else args[0]
            )
        elif expr.op == "sqrt":
            lower = args[0].lower
            if lower == math.nextafter(0.0, -math.inf):
                lower = 0.0
            if lower < 0.0:
                raise ToleranceAnalysisError(
                    "Square-root tolerance interval extends below zero"
                )
            result = _bounded_outward_interval(
                math.sqrt(lower),
                math.sqrt(args[0].upper),
                minimum=0.0,
                maximum=math.inf,
                varies=args[0].varies,
            )
        elif expr.op in {"asin", "acos"}:
            lower = args[0].lower
            upper = args[0].upper
            if lower == math.nextafter(-1.0, -math.inf):
                lower = -1.0
            if upper == math.nextafter(1.0, math.inf):
                upper = 1.0
            if lower < -1.0 or upper > 1.0:
                raise ToleranceAnalysisError(
                    f"{expr.op} tolerance interval extends outside [-1, 1]"
                )
            values = (
                getattr(math, expr.op)(lower),
                getattr(math, expr.op)(upper),
            )
            if expr.op == "asin":
                minimum, maximum = -math.pi / 2.0, math.pi / 2.0
            else:
                minimum, maximum = 0.0, math.pi
            result = _bounded_outward_interval(
                min(values), max(values), minimum=minimum, maximum=maximum
                , varies=args[0].varies
            )
            if expression_uses_units(expr):
                result = _angle_interval_to_degrees(result)
        elif expr.op == "atan":
            result = _outward_interval(
                math.atan(args[0].lower),
                math.atan(args[0].upper),
                varies=args[0].varies,
            )
            if expression_uses_units(expr):
                result = _angle_interval_to_degrees(result)
        elif expr.op == "atan2":
            result = _atan2_interval(
                args[0], args[1], reject_branch_cut=reject_atan2_branch_cut
            )
            if expression_uses_units(expr):
                result = _angle_interval_to_degrees(result)
        else:
            raise ToleranceAnalysisError(
                f"Unsupported expression op '{expr.op}' in tolerance propagation"
            )
    cache[expr.expr_id] = result
    return result


def _constant_value(expr: ScalarExpr, cache: Dict[str, float | None]) -> float | None:
    if expr.expr_id in cache:
        return cache[expr.expr_id]
    if isinstance(expr, Var):
        result = None
    elif isinstance(expr, Const):
        result = expr.value
    elif any(_constant_value(arg, cache) is None for arg in expr.args):
        result = None
    else:
        result = expr.evaluate()
    cache[expr.expr_id] = result
    return result


def _affine_form(
    expr: ScalarExpr,
    cache: Dict[str, _AffineForm | None],
    constant_cache: Dict[str, float | None],
) -> _AffineForm | None:
    if expr.expr_id in cache:
        return cache[expr.expr_id]
    if isinstance(expr, Const):
        result: _AffineForm | None = (Fraction.from_float(expr.value), {})
    elif isinstance(expr, Var):
        result = (Fraction(0), {expr.expr_id: Fraction(1)})
    elif expr.op in {"add", "sub"}:
        left = _affine_form(expr.args[0], cache, constant_cache)
        right = _affine_form(expr.args[1], cache, constant_cache)
        if left is None or right is None:
            result = None
        else:
            sign = Fraction(1) if expr.op == "add" else Fraction(-1)
            coefficients = dict(left[1])
            for expr_id, coefficient in right[1].items():
                coefficients[expr_id] = (
                    coefficients.get(expr_id, Fraction(0)) + sign * coefficient
                )
            result = (left[0] + sign * right[0], coefficients)
    elif expr.op == "neg":
        value = _affine_form(expr.args[0], cache, constant_cache)
        result = (
            None
            if value is None
            else (-value[0], {key: -item for key, item in value[1].items()})
        )
    elif expr.op in {"mul", "div"}:
        left_constant = _constant_value(expr.args[0], constant_cache)
        right_constant = _constant_value(expr.args[1], constant_cache)
        if expr.op == "mul" and left_constant is not None:
            value = _affine_form(expr.args[1], cache, constant_cache)
            factor = Fraction.from_float(left_constant)
        elif right_constant is not None:
            if expr.op == "div" and right_constant == 0.0:
                raise ToleranceAnalysisError("Expression divides by zero")
            value = _affine_form(expr.args[0], cache, constant_cache)
            right_factor = Fraction.from_float(right_constant)
            factor = (
                right_factor if expr.op == "mul" else Fraction(1) / right_factor
            )
        else:
            value = None
            factor = Fraction(0)
        result = (
            None
            if value is None
            else (
                value[0] * factor,
                {key: item * factor for key, item in value[1].items()},
            )
        )
    elif expr.op == "pow":
        exponent = _constant_value(expr.args[1], constant_cache)
        if exponent == 1.0:
            result = _affine_form(expr.args[0], cache, constant_cache)
        elif exponent == 0.0:
            result = (Fraction(1), {})
        else:
            constant = _constant_value(expr, constant_cache)
            result = (
                (Fraction.from_float(constant), {})
                if constant is not None
                else None
            )
    else:
        constant = _constant_value(expr, constant_cache)
        result = (
            (Fraction.from_float(constant), {}) if constant is not None else None
        )
    cache[expr.expr_id] = result
    return result


def _merge_gradients(
    left: Mapping[str, Decimal],
    right: Mapping[str, Decimal],
    *,
    left_scale: Decimal,
    right_scale: Decimal,
) -> Dict[str, Decimal]:
    result = {
        key: value * left_scale
        for key, value in left.items()
        if value * left_scale != 0
    }
    for key, value in right.items():
        result[key] = result.get(key, Decimal(0)) + value * right_scale
        if result[key] == 0:
            del result[key]
    return result


def _gradient_value(
    expr: ScalarExpr, cache: Dict[str, Tuple[float, Dict[str, Decimal]]]
) -> Tuple[float, Dict[str, Decimal]]:
    cached = cache.get(expr.expr_id)
    if cached is not None:
        return cached
    affine = _affine_form(expr, {}, {})
    if affine is not None:
        try:
            nominal = float(expr.evaluate())
        except Exception as exc:
            raise ToleranceAnalysisError(
                "Affine expression cannot be evaluated at nominal values"
            ) from exc
        result = (
            nominal,
            {
                expr_id: _fraction_to_decimal(coefficient)
                for expr_id, coefficient in affine[1].items()
                if coefficient != 0
            },
        )
    elif isinstance(expr, Const):
        result = (expr.value, {})
    elif isinstance(expr, Var):
        result = (expr.canonical_default, {expr.expr_id: Decimal(1)})
    else:
        args = [_gradient_value(arg, cache) for arg in expr.args]
        values = [item[0] for item in args]
        gradients = [item[1] for item in args]
        if expr.op == "add":
            result = (
                values[0] + values[1],
                _merge_gradients(
                    gradients[0],
                    gradients[1],
                    left_scale=Decimal(1),
                    right_scale=Decimal(1),
                ),
            )
        elif expr.op == "sub":
            result = (
                values[0] - values[1],
                _merge_gradients(
                    gradients[0],
                    gradients[1],
                    left_scale=Decimal(1),
                    right_scale=Decimal(-1),
                ),
            )
        elif expr.op == "mul":
            result = (
                values[0] * values[1],
                _merge_gradients(
                    gradients[0],
                    gradients[1],
                    left_scale=Decimal.from_float(values[1]),
                    right_scale=Decimal.from_float(values[0]),
                ),
            )
        elif expr.op == "div":
            if values[1] == 0.0:
                raise ToleranceAnalysisError("Expression divides by zero at nominal values")
            result = (
                values[0] / values[1],
                _merge_gradients(
                    gradients[0],
                    gradients[1],
                    left_scale=Decimal(1) / Decimal.from_float(values[1]),
                    right_scale=-Decimal.from_float(values[0])
                    / Decimal.from_float(values[1])
                    / Decimal.from_float(values[1]),
                ),
            )
        elif expr.op == "pow":
            try:
                value = values[0] ** values[1]
            except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
                raise ToleranceAnalysisError(
                    "Power expression is undefined at nominal values"
                ) from exc
            if isinstance(value, complex) or not math.isfinite(value):
                raise ToleranceAnalysisError(
                    "Power expression is not finite and real at nominal values"
                )
            if not gradients[1] and values[1] == 0.0:
                result = (1.0, {})
                cache[expr.expr_id] = result
                return result
            if gradients[1]:
                if values[0] <= 0.0:
                    raise ToleranceAnalysisError(
                        "RSS propagation through a varying exponent requires a positive base"
                    )
                exponent_scale = Decimal.from_float(float(value)) * Decimal.from_float(
                    math.log(values[0])
                )
            else:
                exponent_scale = Decimal(0)
            if gradients[0]:
                if values[0] == 0.0:
                    if values[1] == 1.0:
                        base_scale = Decimal(1)
                    elif values[1] > 1.0:
                        base_scale = Decimal(0)
                    else:
                        raise ToleranceAnalysisError(
                            "Power derivative is undefined at nominal values"
                        )
                else:
                    base_scale = (
                        Decimal.from_float(float(value))
                        * Decimal.from_float(values[1])
                        / Decimal.from_float(values[0])
                    )
            else:
                base_scale = Decimal(0)
            result = (
                float(value),
                _merge_gradients(
                    gradients[0],
                    gradients[1],
                    left_scale=base_scale,
                    right_scale=exponent_scale,
                ),
            )
        elif expr.op == "neg":
            result = (-values[0], {key: -value for key, value in gradients[0].items()})
        elif expr.op == "abs":
            if values[0] == 0.0 and gradients[0]:
                raise ToleranceAnalysisError(
                    "RSS propagation is undefined where abs is non-differentiable"
                )
            sign = Decimal(-1) if values[0] < 0.0 else Decimal(1)
            result = (
                abs(values[0]),
                {key: sign * value for key, value in gradients[0].items()},
            )
        elif expr.op in {"sin", "cos", "tan", "sqrt", "acos", "asin", "atan"}:
            value = values[0]
            unit_aware = expression_uses_units(expr)
            function_value = (
                math.radians(value)
                if unit_aware and expr.op in {"sin", "cos", "tan"}
                else value
            )
            if expr.op == "sin":
                output = math.sin(function_value)
                scale = Decimal.from_float(math.cos(function_value))
                if unit_aware:
                    scale *= Decimal.from_float(math.pi / 180.0)
            elif expr.op == "cos":
                output = math.cos(function_value)
                scale = Decimal.from_float(-math.sin(function_value))
                if unit_aware:
                    scale *= Decimal.from_float(math.pi / 180.0)
            elif expr.op == "tan":
                cosine = math.cos(function_value)
                if cosine == 0.0:
                    raise ToleranceAnalysisError("Tangent is undefined at the nominal value")
                output = math.tan(function_value)
                scale = Decimal(1) / (Decimal.from_float(cosine) ** 2)
                if unit_aware:
                    scale *= Decimal.from_float(math.pi / 180.0)
            elif expr.op == "sqrt":
                if value < 0.0 or (value == 0.0 and gradients[0]):
                    raise ToleranceAnalysisError(
                        "Square-root derivative is undefined at the nominal value"
                    )
                output = math.sqrt(value)
                scale = (
                    Decimal(0)
                    if not gradients[0]
                    else Decimal("0.5") / Decimal.from_float(output)
                )
            elif expr.op in {"acos", "asin"}:
                if value < -1.0 or value > 1.0 or (
                    abs(value) == 1.0 and gradients[0]
                ):
                    raise ToleranceAnalysisError(
                        f"{expr.op} derivative is undefined at the nominal value"
                    )
                output = getattr(math, expr.op)(value)
                if gradients[0]:
                    denominator = (
                        Decimal(1) - Decimal.from_float(value) ** 2
                    ).sqrt()
                    scale = Decimal(1) / denominator
                    if expr.op == "acos":
                        scale = -scale
                else:
                    scale = Decimal(0)
                if unit_aware:
                    output = math.degrees(output)
                    scale *= Decimal.from_float(180.0 / math.pi)
            else:
                output = math.atan(value)
                decimal_value = Decimal.from_float(value)
                if abs(value) <= 1.0:
                    scale = Decimal(1) / (
                        Decimal(1) + decimal_value * decimal_value
                    )
                else:
                    reciprocal = Decimal(1) / decimal_value
                    scale = reciprocal * reciprocal / (
                        Decimal(1) + reciprocal * reciprocal
                    )
                if unit_aware:
                    output = math.degrees(output)
                    scale *= Decimal.from_float(180.0 / math.pi)
            result = (
                output,
                {key: scale * item for key, item in gradients[0].items()},
            )
        elif expr.op == "atan2":
            if values[0] == 0.0 and values[1] == 0.0:
                raise ToleranceAnalysisError("atan2 is undefined at the nominal origin")
            decimal_y = Decimal.from_float(values[0])
            decimal_x = Decimal.from_float(values[1])
            denominator = decimal_y * decimal_y + decimal_x * decimal_x
            output = math.atan2(values[0], values[1])
            left_scale = decimal_x / denominator
            right_scale = -decimal_y / denominator
            if expression_uses_units(expr):
                output = math.degrees(output)
                angle_scale = Decimal.from_float(180.0 / math.pi)
                left_scale *= angle_scale
                right_scale *= angle_scale
            result = (
                output,
                _merge_gradients(
                    gradients[0],
                    gradients[1],
                    left_scale=left_scale,
                    right_scale=right_scale,
                ),
            )
        else:
            raise ToleranceAnalysisError(
                f"Unsupported expression op '{expr.op}' in RSS propagation"
            )
    if not math.isfinite(result[0]) or not all(
        item.is_finite() for item in result[1].values()
    ):
        raise ToleranceAnalysisError("RSS propagation produced a non-finite result")
    cache[expr.expr_id] = result
    return result


def _contribution(
    variable: Var, sensitivity: Decimal | Fraction | float | None
) -> ToleranceContribution:
    source_tolerance = variable.canonical_tolerance
    if source_tolerance is None:
        raise ToleranceAnalysisError(
            f"Variable '{variable.name}' ({variable.expr_id}) has no declared tolerance"
        )
    if sensitivity is None:
        lower = source_tolerance.lower_deviation
        upper = source_tolerance.upper_deviation
        sensitivity_value: float | None = None
    else:
        with localcontext() as context:
            context.prec = 80
            decimal_sensitivity = _sensitivity_decimal(sensitivity)
            deviations = (
                decimal_sensitivity
                * Decimal.from_float(source_tolerance.lower_deviation),
                decimal_sensitivity
                * Decimal.from_float(source_tolerance.upper_deviation),
            )
            lower_decimal, upper_decimal = min(deviations), max(deviations)
            lower_value = _decimal_to_float(
                lower_decimal,
                label="Tolerance contribution lower deviation",
                outward=True,
            )
            upper_value = _decimal_to_float(
                upper_decimal,
                label="Tolerance contribution upper deviation",
                outward=True,
            )
            if lower_value is None or upper_value is None:
                raise ToleranceAnalysisError(
                    "Tolerance contribution is outside the supported float range"
                )
            lower, upper = lower_value, upper_value
            sensitivity_value = _decimal_to_float(
                decimal_sensitivity,
                label="Tolerance sensitivity",
                allow_unrepresentable=True,
            )
    return ToleranceContribution(
        variable_expr_id=variable.expr_id,
        variable_name=variable.name,
        nominal=variable.canonical_default,
        source_tolerance=source_tolerance,
        sensitivity=sensitivity_value,
        lower_deviation=lower,
        upper_deviation=upper,
        source_unit=(
            None
            if variable.dimension is None
            else canonical_unit_for_dimension(variable.dimension)
        ),
    )


def _nonlinear_contribution(
    expr: ScalarExpr,
    variable: Var,
    variables: Tuple[Var, ...],
    nominal: float,
) -> ToleranceContribution:
    source_tolerance = variable.canonical_tolerance
    if source_tolerance is None:
        raise ToleranceAnalysisError(
            f"Variable '{variable.name}' ({variable.expr_id}) has no declared tolerance"
        )
    if source_tolerance.width == 0.0:
        return _contribution(variable, None)
    variable_map = {
        item.expr_id: (
            item
            if item.expr_id == variable.expr_id
            else replace(item, tolerance=DimensionTolerance.symmetric(0.0))
        )
        for item in variables
    }
    interval = _interval_value(expr, {}, variable_map)
    return ToleranceContribution(
        variable_expr_id=variable.expr_id,
        variable_name=variable.name,
        nominal=variable.canonical_default,
        source_tolerance=source_tolerance,
        sensitivity=None,
        lower_deviation=interval.lower - nominal,
        upper_deviation=interval.upper - nominal,
        source_unit=(
            None
            if variable.dimension is None
            else canonical_unit_for_dimension(variable.dimension)
        ),
    )


def analyze_tolerance(
    value: ScalarLike, *, method: ToleranceMethod = "worst_case"
) -> ToleranceAnalysis:
    """Propagate source manufacturing tolerances through a scalar expression.

    ``worst_case`` returns guaranteed interval bounds. Affine chains are
    dependency-aware, so repeated variables such as ``x - x`` cancel exactly;
    nonlinear chains use conservative interval arithmetic. ``rss`` performs a
    first-order root-sum-square calculation using analytic sensitivities.

    Unit-aware variables are converted to canonical CAD units before
    propagation. The returned analysis reports the inferred physical dimension
    and canonical result unit. Every variable in the expression must declare a
    source tolerance.
    """

    resolved_method = _validate_method(method)
    expr = lift_scalar(value)
    _validate_expression_identity(expr)
    result_dimension = infer_dimension(expr)
    result_unit = (
        None
        if result_dimension is None
        else canonical_unit_for_dimension(result_dimension)
    )
    variables = _variables(expr)
    _require_source_tolerances(variables)

    # Both methods must reject undefined values anywhere inside the declared
    # source intervals. RSS still reports a first-order estimate, but it must
    # not legitimize a chain that crosses a singularity or function domain.
    variable_map = {item.expr_id: item for item in variables}
    try:
        interval = _interval_value(
            expr,
            {},
            variable_map,
            reject_atan2_branch_cut=resolved_method == "rss",
        )
    except ToleranceAnalysisError:
        raise
    except Exception as exc:
        raise ToleranceAnalysisError(
            "Expression is undefined inside its declared tolerance interval"
        ) from exc

    try:
        nominal = float(expr.evaluate())
    except Exception as exc:
        raise ToleranceAnalysisError(
            "Expression cannot be evaluated at its nominal values"
        ) from exc
    if not math.isfinite(nominal):
        raise ToleranceAnalysisError("Expression nominal value must be finite")
    interval = _Interval(
        min(interval.lower, nominal), max(interval.upper, nominal)
    )

    if resolved_method == "worst_case":
        affine = _affine_form(expr, {}, {})
        if affine is not None:
            contributions: List[ToleranceContribution] = []
            variable_by_id = {item.expr_id: item for item in variables}
            for expr_id, coefficient in sorted(affine[1].items()):
                contribution = _contribution(variable_by_id[expr_id], coefficient)
                contributions.append(contribution)
            lower_deviation = _finite_fsum(
                [item.lower_deviation for item in contributions],
                label="Worst-case lower deviation",
            )
            upper_deviation = _finite_fsum(
                [item.upper_deviation for item in contributions],
                label="Worst-case upper deviation",
            )
            lower_bound = _bound_from_deviation(nominal, lower_deviation)
            upper_bound = _bound_from_deviation(nominal, upper_deviation)
        else:
            lower_bound, upper_bound = interval.lower, interval.upper
            lower_deviation = min(0.0, lower_bound - nominal)
            upper_deviation = max(0.0, upper_bound - nominal)
            contributions = [
                _nonlinear_contribution(expr, item, variables, nominal)
                for item in variables
            ]
    else:
        with localcontext() as context:
            context.prec = 100
            gradient_nominal, gradients = _gradient_value(expr, {})
        if not math.isclose(gradient_nominal, nominal, rel_tol=1e-12, abs_tol=1e-12):
            raise ToleranceAnalysisError(
                "Nominal expression evaluation disagrees with RSS differentiation"
            )
        contributions = [
            _contribution(variable, gradients.get(variable.expr_id, Decimal(0)))
            for variable in variables
        ]
        lower_magnitude = math.hypot(
            *(item.lower_deviation for item in contributions)
        )
        upper_magnitude = math.hypot(
            *(item.upper_deviation for item in contributions)
        )
        if not math.isfinite(lower_magnitude) or not math.isfinite(upper_magnitude):
            raise ToleranceAnalysisError("RSS tolerance magnitude is non-finite")
        lower_deviation = -lower_magnitude
        upper_deviation = upper_magnitude
        lower_bound = _bound_from_deviation(nominal, lower_deviation)
        upper_bound = _bound_from_deviation(nominal, upper_deviation)

    return ToleranceAnalysis(
        target_expr_id=expr.expr_id,
        method=resolved_method,
        nominal=nominal,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        lower_deviation=lower_deviation,
        upper_deviation=upper_deviation,
        dimension=result_dimension,
        unit=result_unit,
        contributions=tuple(contributions),
    )


def _requirement_unit(
    expr: ScalarExpr, tolerance_unit: UnitLike | None
) -> Tuple[Dimension | None, Unit | None]:
    target_dimension = infer_dimension(expr)
    if target_dimension is None:
        if tolerance_unit is not None:
            raise ValueError(
                "A tolerance unit requires a unit-aware target expression"
            )
        return None, None
    if not target_dimension.is_design_dimension:
        raise ValueError(
            "Manufacturing tolerance requirements currently require a Length or "
            f"Angle result; got {target_dimension.name}"
        )
    resolved_unit = (
        canonical_unit_for_dimension(target_dimension)
        if tolerance_unit is None
        else get_unit(tolerance_unit)
    )
    if resolved_unit.dimension != target_dimension:
        raise ValueError(
            f"Tolerance unit '{resolved_unit.symbol}' is incompatible with "
            f"target dimension {target_dimension.name}"
        )
    return target_dimension, resolved_unit


def check_tolerance(
    value: ScalarLike,
    tolerance: ToleranceLike,
    *,
    method: ToleranceMethod = "worst_case",
    name: str | None = None,
    tolerance_unit: UnitLike | None = None,
) -> ToleranceCheck:
    """Propagate and verify one Length or Angle requirement.

    ``tolerance_unit`` defaults to the target dimension's canonical unit. When
    provided, it must be dimensionally compatible and is converted before the
    comparison. Legacy unitless requirements remain supported when no unit is
    supplied.
    """

    expr = lift_scalar(value)
    allowed = coerce_dimension_tolerance(tolerance)
    target_dimension, resolved_tolerance_unit = _requirement_unit(
        expr, tolerance_unit
    )
    requirement = ToleranceRequirement(
        requirement_id=f"tolreq_{uuid.uuid4().hex[:8]}",
        target_expr_id=expr.expr_id,
        tolerance=allowed,
        method=_validate_method(method),
        name=expr.expr_id if name is None else name,
        tolerance_unit=resolved_tolerance_unit,
        target_dimension=target_dimension,
        target=expr,
    )
    return _check_requirement(expr, requirement)


def _check_requirement(
    expr: ScalarExpr, requirement: ToleranceRequirement
) -> ToleranceCheck:
    analysis = analyze_tolerance(expr, method=requirement.method)
    allowed = requirement.canonical_tolerance
    lower_margin = analysis.lower_deviation - allowed.lower_deviation
    upper_margin = allowed.upper_deviation - analysis.upper_deviation
    lower_epsilon = (
        0.0
        if allowed.lower_deviation == 0.0
        else 8.0 * math.ulp(abs(allowed.lower_deviation))
    )
    upper_epsilon = (
        0.0
        if allowed.upper_deviation == 0.0
        else 8.0 * math.ulp(abs(allowed.upper_deviation))
    )
    passed = lower_margin >= -lower_epsilon and upper_margin >= -upper_epsilon
    return ToleranceCheck(
        requirement=requirement,
        analysis=analysis,
        passed=passed,
        lower_margin=lower_margin,
        upper_margin=upper_margin,
    )


class ToleranceGraph:
    """Tolerance requirements attached to one expression graph."""

    def __init__(self, expression_graph: ExpressionGraph) -> None:
        if not isinstance(expression_graph, ExpressionGraph):
            raise TypeError("ToleranceGraph requires an ExpressionGraph")
        self.expression_graph = expression_graph
        self._requirements: Dict[str, ToleranceRequirement] = {}

    @property
    def requirement_count(self) -> int:
        return len(self._requirements)

    @property
    def requirements(self) -> Tuple[ToleranceRequirement, ...]:
        return tuple(self._requirements.values())

    def require(
        self,
        value: ScalarLike,
        tolerance: ToleranceLike,
        *,
        method: ToleranceMethod = "worst_case",
        name: str | None = None,
        requirement_id: str | None = None,
        tolerance_unit: UnitLike | None = None,
    ) -> ToleranceRequirement:
        """Declare a target tolerance and register its expression dependencies."""

        resolved_id = (
            f"tolreq_{uuid.uuid4().hex[:8]}"
            if requirement_id is None
            else requirement_id
        )
        if not isinstance(resolved_id, str) or not resolved_id:
            raise ValueError("Tolerance requirement id must be a non-empty string")
        if resolved_id in self._requirements:
            raise ValueError(f"Duplicate tolerance requirement id '{resolved_id}'")
        expr = lift_scalar(value)
        target_dimension, resolved_tolerance_unit = _requirement_unit(
            expr, tolerance_unit
        )
        requirement = ToleranceRequirement(
            requirement_id=resolved_id,
            target_expr_id=expr.expr_id,
            tolerance=coerce_dimension_tolerance(tolerance),
            method=_validate_method(method),
            name=(expr.name if isinstance(expr, Var) else expr.expr_id)
            if name is None
            else name,
            tolerance_unit=resolved_tolerance_unit,
            target_dimension=target_dimension,
            target=expr,
        )
        # Reject incomplete or mathematically invalid chains when declared.
        _check_requirement(expr, requirement)
        self.expression_graph.register(expr)
        self._requirements[resolved_id] = requirement
        return requirement

    def add(self, requirement: ToleranceRequirement) -> ToleranceRequirement:
        """Register a requirement declared in another graph, with its target.

        Adding one requirement twice is a no-op; a different requirement
        under a taken id is rejected.
        """

        if requirement.target is None:
            raise ValueError(
                f"Tolerance requirement '{requirement.requirement_id}' "
                "does not carry its target expression"
            )
        existing = self._requirements.get(requirement.requirement_id)
        if existing is not None:
            if existing != requirement:
                raise ValueError(
                    f"Duplicate tolerance requirement id '{requirement.requirement_id}'"
                )
            return existing
        self.expression_graph.register(requirement.target)
        self._requirements[requirement.requirement_id] = requirement
        return requirement

    def validate(self, *, raise_on_failure: bool = False) -> ToleranceReport:
        checks: List[ToleranceCheck] = []
        for requirement in self._requirements.values():
            expr = self.expression_graph.get(requirement.target_expr_id)
            if expr is None:
                raise ToleranceAnalysisError(
                    f"Unknown tolerance target expression '{requirement.target_expr_id}'"
                )
            checks.append(_check_requirement(expr, requirement))
        report = ToleranceReport(tuple(checks))
        if raise_on_failure and not report.passed:
            raise ToleranceValidationError(report)
        return report

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirements": [item.to_dict() for item in self._requirements.values()],
            "validation": self.validate().to_dict(),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], expression_graph: ExpressionGraph
    ) -> "ToleranceGraph":
        if not isinstance(data, Mapping):
            raise TypeError("Tolerance graph payload must be an object")
        raw_requirements = data.get("requirements", [])
        if not isinstance(raw_requirements, list):
            raise TypeError("Tolerance graph 'requirements' must be an array")
        graph = cls(expression_graph)
        for raw in raw_requirements:
            if not isinstance(raw, Mapping):
                raise TypeError("Tolerance requirements must be objects")
            target_expr_id = raw.get("target_expr_id")
            if not isinstance(target_expr_id, str) or not target_expr_id:
                raise ValueError(
                    "Tolerance requirement 'target_expr_id' must be a non-empty string"
                )
            expr = expression_graph.get(target_expr_id)
            if expr is None:
                raise ValueError(
                    f"Unknown tolerance target expression '{target_expr_id}'"
                )
            tolerance_payload = raw.get("tolerance")
            if not isinstance(tolerance_payload, Mapping):
                raise TypeError("Tolerance requirement 'tolerance' must be an object")
            method = raw.get("method", "worst_case")
            name = raw.get("name", target_expr_id)
            requirement_id = raw.get("requirement_id")
            has_tolerance_unit = "tolerance_unit" in raw
            tolerance_unit_payload = raw.get("tolerance_unit")
            has_target_dimension = "target_dimension" in raw
            target_dimension_payload = raw.get("target_dimension")
            if not isinstance(method, str):
                raise TypeError("Tolerance requirement 'method' must be a string")
            if not isinstance(name, str) or not name:
                raise ValueError(
                    "Tolerance requirement 'name' must be a non-empty string"
                )
            if not isinstance(requirement_id, str) or not requirement_id:
                raise ValueError(
                    "Tolerance requirement 'requirement_id' must be a non-empty string"
                )
            tolerance_unit = (
                None
                if tolerance_unit_payload is None
                else unit_from_payload(tolerance_unit_payload)
            )
            declared_target_dimension = (
                None
                if target_dimension_payload is None
                else Dimension.from_dict(target_dimension_payload)
            )
            requirement = graph.require(
                expr,
                DimensionTolerance.from_dict(tolerance_payload),
                method=method,  # type: ignore[arg-type]
                name=name,
                requirement_id=requirement_id,
                tolerance_unit=tolerance_unit,
            )
            if has_target_dimension and (
                requirement.target_dimension != declared_target_dimension
            ):
                raise ValueError(
                    "Tolerance requirement target_dimension does not match the "
                    "inferred target expression dimension"
                )
            if has_tolerance_unit and requirement.tolerance_unit != tolerance_unit:
                raise ValueError(
                    "Tolerance requirement tolerance_unit does not match the "
                    "inferred target expression dimension"
                )
        return graph
