"""Units, dimensions and dimension inference: ports of test_units.py."""

import json
import math

import pytest

import simplecadapi._cpp as scad
from ref import golden


def test_named_dimensions_and_dimension_algebra():
    assert scad.DIMENSIONLESS.name == "Dimensionless"
    assert scad.LENGTH.name == "Length"
    assert scad.AREA.name == "Area" and scad.VOLUME.name == "Volume" and scad.ANGLE.name == "Angle"
    assert scad.LENGTH.multiply(scad.LENGTH) == scad.AREA
    assert scad.VOLUME.divide(scad.LENGTH) == scad.AREA
    assert scad.LENGTH.power(3) == scad.VOLUME
    assert scad.AREA.square_root() == scad.LENGTH
    assert scad.Dimension(length=-1, angle=2).symbol == "L^-1 A^2"
    assert scad.DIMENSIONLESS.is_dimensionless and scad.LENGTH.is_design_dimension
    assert not scad.AREA.is_design_dimension
    assert repr(scad.LENGTH) == "Dimension(length=1, angle=0)"
    assert hash(scad.LENGTH) == hash(scad.Dimension(1, 0))


def test_dimension_serialization_and_validation():
    assert scad.Dimension.from_dict(scad.VOLUME.to_dict()) == scad.VOLUME
    for payload in (None, {}, {"length": 1}, {"length": True, "angle": 0}, {"length": 1, "angle": 0.5}):
        with pytest.raises((TypeError, ValueError)):
            scad.Dimension.from_dict(payload)
    with pytest.raises(TypeError):
        scad.LENGTH.power(0.5)
    with pytest.raises(scad.UnitValidationError):
        scad.LENGTH.square_root()
    with pytest.raises(TypeError):
        scad.Dimension(length=True)


REGISTERED = [
    ("MM", 1.0), ("CM", 10.0), ("M", 1000.0), ("INCH", 25.4), ("FOOT", 304.8), ("DEGREE", 1.0),
    ("RADIAN", 180.0 / math.pi), ("ONE", 1.0), ("PERCENT", 0.01), ("SQUARE_MM", 1.0), ("SQUARE_CM", 100.0),
    ("SQUARE_M", 1e6), ("SQUARE_INCH", 25.4**2), ("SQUARE_FOOT", 304.8**2), ("CUBIC_MM", 1.0),
    ("CUBIC_CM", 1000.0), ("CUBIC_M", 1e9), ("CUBIC_INCH", 25.4**3), ("CUBIC_FOOT", 304.8**3),
]


@pytest.mark.parametrize(("name", "scale"), REGISTERED)
def test_every_registered_unit_converts_to_canonical_units(name, scale):
    unit = getattr(scad, name)
    assert unit.to_canonical(1.0) == pytest.approx(scale)
    assert unit.from_canonical(scale) == pytest.approx(1.0)
    assert scad.get_unit(unit) is unit
    assert scad.get_unit(unit.symbol) == unit
    assert scad.canonical_unit_for_dimension(unit.dimension).dimension == unit.dimension


def test_unit_aliases_and_conversion():
    aliases = {"millimeters": scad.MM, "centimeter": scad.CM, "meters": scad.M, "inches": scad.INCH,
               "feet": scad.FOOT, "degrees": scad.DEGREE, "radians": scad.RADIAN, "percent": scad.PERCENT,
               "square feet": scad.SQUARE_FOOT, "cubic inches": scad.CUBIC_INCH, "ml": scad.CUBIC_CM}
    for alias, unit in aliases.items():
        assert scad.get_unit(alias) == unit
    assert scad.convert_value(1.0, "in", "mm") == pytest.approx(25.4)
    assert scad.convert_value(180.0, "deg", "rad") == pytest.approx(math.pi)
    assert scad.convert_value(1.0, "ft^2", "in^2") == pytest.approx(144.0)
    with pytest.raises(scad.UnitValidationError):
        scad.convert_value(1.0, "mm", "deg")
    with pytest.raises(ValueError, match="Unknown unit"):
        scad.get_unit("parsec")


def test_unit_messages_match_the_reference():
    cases = {
        "unknown": "scad.get_unit('parsec')",
        "convert": "scad.convert_value(1.0, 'mm', 'deg')",
        "sqrt": "scad.LENGTH.square_root()",
        "range": "scad.M.to_canonical(1e308)",
        "nonfinite": "scad.MM.to_canonical(float('inf'))",
        "scale": "scad.Unit('bad', scad.LENGTH, 0.0)",
    }
    expected = golden(
        "reactive_unit_messages",
        f"""
        result = {{}}
        for key, source in {cases!r}.items():
            try:
                eval(source, {{"scad": scad}})
                result[key] = None
            except Exception as error:
                result[key] = [type(error).__name__, str(error)]
        """,
    )
    for key, source in cases.items():
        with pytest.raises(Exception) as caught:
            eval(source, {"scad": scad})
        assert [type(caught.value).__name__, str(caught.value)] == expected[key], key


def test_unit_validation_and_custom_unit_roundtrip():
    invalid_calls = [
        lambda: scad.Unit("", scad.LENGTH, 1.0),
        lambda: scad.Unit("bad", "Length", 1.0),
        lambda: scad.Unit("bad", scad.LENGTH, True),
        lambda: scad.Unit("bad", scad.LENGTH, 0.0),
        lambda: scad.Unit("bad", scad.LENGTH, math.inf),
        lambda: scad.MM.to_canonical(math.inf),
        lambda: scad.MM.to_canonical(True),
        lambda: scad.M.to_canonical(1e308),
        lambda: scad.Unit("tiny", scad.LENGTH, 5e-324).to_canonical(0.5),
        lambda: scad.Unit("tiny", scad.LENGTH, 5e-324).from_canonical(1.0),
        lambda: scad.Unit("huge", scad.LENGTH, 1e308).from_canonical(5e-324),
        lambda: scad.MM.to_canonical(10**10000),
        lambda: scad.get_unit(None),
        lambda: scad.get_unit(""),
        lambda: scad.Unit.from_dict(None),
        lambda: scad.unit_to_payload(None),
    ]
    for call in invalid_calls:
        with pytest.raises((TypeError, ValueError)):
            call()

    thou = scad.Unit("thou", scad.LENGTH, 0.0254)
    width = scad.var("width", 1000.0, unit=thou, tolerance=2.0, tolerance_unit=thou)
    graph = scad.ExpressionGraph()
    graph.register(width)
    payload = graph.to_dict()
    assert isinstance(payload["nodes"][0]["unit"], dict)
    rebuilt = scad.ExpressionGraph.from_dict(payload).get(width.expr_id)
    assert isinstance(rebuilt, scad.Var)
    assert rebuilt.unit == thou and rebuilt.tolerance_unit == thou
    assert rebuilt.evaluate() == pytest.approx(25.4)
    assert rebuilt.canonical_tolerance.upper_deviation == pytest.approx(0.0508)
    assert scad.unit_to_payload(scad.MM) == "mm"
    assert scad.unit_from_payload(scad.unit_to_payload(thou)) == thou


def test_unknown_compound_dimension_uses_a_canonical_scale_one_unit():
    unit = scad.canonical_unit_for_dimension(scad.Dimension(length=-1, angle=2))
    assert unit.symbol == "L^-1 A^2" and unit.scale_to_canonical == 1.0


def test_malformed_custom_unit_payloads_are_rejected():
    base = {"nodes": [{"expr_id": "var_x", "kind": "var", "name": "x", "default": 1.0,
                       "unit": {"symbol": "custom", "dimension": {"length": 1, "angle": 0}, "scale_to_canonical": 2.0}}]}
    for field in ("symbol", "dimension", "scale_to_canonical"):
        payload = json.loads(json.dumps(base))
        del payload["nodes"][0]["unit"][field]
        with pytest.raises(ValueError):
            scad.ExpressionGraph.from_dict(payload)


# ---- unit-aware variables ------------------------------------------------


def test_nominal_and_tolerance_units_are_canonicalized_independently():
    width = scad.var("width", 1.0, unit="in", tolerance=(-0.1, 0.2), tolerance_unit="mm")
    inherited = scad.var("inherited", 1.0, unit="in", tolerance=0.01)
    assert width.default == 1.0
    assert width.tolerance == scad.DimensionTolerance(-0.1, 0.2)
    assert width.unit == scad.INCH and width.tolerance_unit == scad.MM
    assert width.canonical_default == pytest.approx(25.4)
    assert width.canonical_tolerance == scad.DimensionTolerance(-0.1, 0.2)
    assert inherited.tolerance_unit == scad.INCH
    assert inherited.canonical_tolerance.upper_deviation == pytest.approx(0.254)


def test_bindings_use_the_variable_declaration_unit():
    width = scad.var("width", 1.0, unit="in")
    assert width.evaluate({"width": 2.0}) == pytest.approx(50.8)
    assert (width + 1.0).evaluate({"width": 2.0}) == pytest.approx(51.8)


def test_invalid_variable_unit_combinations_are_rejected():
    invalid = [
        lambda: scad.var("x", 1.0, tolerance=0.1, tolerance_unit="mm"),
        lambda: scad.var("x", 1.0, unit="mm", tolerance_unit="mm"),
        lambda: scad.var("x", 1.0, unit="mm", tolerance=0.1, tolerance_unit="deg"),
        lambda: scad.var("x", 1.0, unit="unknown"),
        lambda: scad.var("x", 1e308, unit="m"),
        lambda: scad.var("x", 1.0, unit="mm", tolerance=1e308, tolerance_unit="m"),
    ]
    for call in invalid:
        with pytest.raises((TypeError, ValueError)):
            call()


# ---- dimension inference -------------------------------------------------


@pytest.fixture
def q():
    class Quantities:
        length = scad.var("length", 3.0, unit="mm")
        other_length = scad.var("other_length", 4.0, unit="cm")
        angle = scad.var("angle", 90.0, unit="deg")
        scalar = scad.var("scalar", 50.0, unit="%")

    return Quantities


def test_addition_subtraction_and_contextual_constants(q):
    assert scad.infer_dimension(q.length + q.other_length) == scad.LENGTH
    assert scad.infer_dimension(q.length - 1.0) == scad.LENGTH
    assert scad.infer_dimension(1.0 + q.angle) == scad.ANGLE
    assert (q.length + q.other_length).evaluate() == pytest.approx(43.0)


def test_multiplication_division_and_powers(q):
    assert scad.infer_dimension(q.length * q.other_length) == scad.AREA
    assert scad.infer_dimension(q.length * q.other_length * q.length) == scad.VOLUME
    assert scad.infer_dimension(q.length / q.other_length) == scad.DIMENSIONLESS
    assert scad.infer_dimension(1.0 / q.length) == scad.Dimension(length=-1)
    assert scad.infer_dimension(q.length**3) == scad.VOLUME
    assert scad.infer_dimension(q.length**0) == scad.DIMENSIONLESS
    assert scad.infer_dimension(q.scalar ** scad.var("power", 2.0, unit="1")) == scad.DIMENSIONLESS


def test_square_root_requires_even_dimension_exponents(q):
    diagonal = scad.sqrt(q.length**2 + q.other_length**2)
    assert scad.infer_dimension(diagonal) == scad.LENGTH
    assert diagonal.evaluate() == pytest.approx(math.sqrt(1609.0))
    assert scad.infer_dimension(scad.sqrt(q.scalar)) == scad.DIMENSIONLESS
    with pytest.raises(scad.UnitValidationError):
        scad.infer_dimension(scad.sqrt(q.length))
    with pytest.raises(scad.UnitValidationError):
        scad.infer_dimension(q.length**0.5)


def test_unary_and_trigonometric_dimensions(q):
    assert scad.infer_dimension(-q.length) == scad.LENGTH
    assert scad.infer_dimension(abs(q.length)) == scad.LENGTH
    for expression in (scad.sin(q.angle), scad.cos(q.angle), scad.tan(q.angle)):
        assert scad.infer_dimension(expression) == scad.DIMENSIONLESS
    for expression in (scad.asin(q.scalar), scad.acos(q.scalar), scad.atan(q.scalar), scad.atan2(q.length, q.other_length)):
        assert scad.infer_dimension(expression) == scad.ANGLE


def test_invalid_physical_expressions_are_rejected_with_the_references_messages(q):
    legacy = scad.var("legacy", 1.0)
    cases = [
        "q.length + q.angle", "q.length + q.scalar", "q.length + legacy", "q.length * legacy",
        "q.length ** q.scalar", "q.length ** q.angle", "q.length ** legacy", "q.length ** 0.25",
        "scad.sin(q.length)", "scad.asin(q.length)", "scad.atan2(q.length, q.angle)",
    ]
    setup = (
        "class q:\n"
        "    length = scad.var('length', 3.0, unit='mm')\n"
        "    other_length = scad.var('other_length', 4.0, unit='cm')\n"
        "    angle = scad.var('angle', 90.0, unit='deg')\n"
        "    scalar = scad.var('scalar', 50.0, unit='%')\n"
        "legacy = scad.var('legacy', 1.0)\n"
    )
    expected = golden(
        "reactive_invalid_expressions",
        f"""
        scope = {{"scad": scad}}
        exec({setup!r}, scope)
        result = {{}}
        for source in {cases!r}:
            try:
                scad.infer_dimension(eval(source, scope))
                result[source] = None
            except Exception as error:
                result[source] = [type(error).__name__, str(error)]
        """,
    )
    scope = {"scad": scad}
    exec(setup, scope)
    for source in cases:
        with pytest.raises(scad.UnitValidationError) as caught:
            scad.infer_dimension(eval(source, scope))
        assert [type(caught.value).__name__, str(caught.value)] == expected[source], source
    with pytest.raises(scad.UnitValidationError):
        (q.length + q.angle).evaluate()


def test_legacy_expressions_keep_radian_math_and_unknown_dimension():
    value = scad.var("legacy", 0.5)
    expression = value ** scad.var("legacy_power", 2.0)
    assert scad.infer_dimension(expression) is None
    assert not scad.expression_uses_units(expression)
    assert scad.sin(value).evaluate() == pytest.approx(math.sin(0.5))
    assert scad.asin(value).evaluate() == pytest.approx(math.asin(0.5))
    assert scad.infer_dimension(scad.sin(value)) is None
    assert scad.infer_dimension(value + value) is None
    assert scad.infer_dimension(scad.atan2(value, value)) is None


def test_trigonometric_evaluation_uses_degrees_canonically():
    degrees = scad.var("degrees", 90.0, unit="deg")
    radians = scad.var("radians", math.pi / 2.0, unit="rad")
    ratio = scad.var("ratio", 50.0, unit="%")
    y = scad.var("y", 1.0, unit="in")
    x = scad.var("x", 25.4, unit="mm")
    assert scad.sin(degrees).evaluate() == pytest.approx(1.0)
    assert scad.sin(radians).evaluate() == pytest.approx(1.0)
    assert scad.asin(ratio).evaluate() == pytest.approx(30.0)
    assert scad.atan2(y, x).evaluate() == pytest.approx(45.0)
    assert scad.expression_uses_units(scad.sin(degrees))
