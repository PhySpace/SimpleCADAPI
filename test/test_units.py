"""Complete coverage for physical units and dimensional expression inference."""

from __future__ import annotations

import json
import math
import unittest

import simplecadapi as scad
from simplecadapi.params.units import _infer, unit_to_payload


class TestDimensionsAndUnits(unittest.TestCase):
    def test_named_dimensions_and_dimension_algebra(self):
        self.assertEqual(scad.DIMENSIONLESS.name, "Dimensionless")
        self.assertEqual(scad.LENGTH.name, "Length")
        self.assertEqual(scad.AREA.name, "Area")
        self.assertEqual(scad.VOLUME.name, "Volume")
        self.assertEqual(scad.ANGLE.name, "Angle")
        self.assertEqual(scad.LENGTH.multiply(scad.LENGTH), scad.AREA)
        self.assertEqual(scad.VOLUME.divide(scad.LENGTH), scad.AREA)
        self.assertEqual(scad.LENGTH.power(3), scad.VOLUME)
        self.assertEqual(scad.AREA.square_root(), scad.LENGTH)
        self.assertEqual(scad.Dimension(length=-1, angle=2).symbol, "L^-1 A^2")
        self.assertTrue(scad.DIMENSIONLESS.is_dimensionless)
        self.assertTrue(scad.LENGTH.is_design_dimension)
        self.assertTrue(scad.ANGLE.is_design_dimension)
        self.assertFalse(scad.AREA.is_design_dimension)

    def test_dimension_serialization_and_validation(self):
        self.assertEqual(
            scad.Dimension.from_dict(scad.VOLUME.to_dict()), scad.VOLUME
        )
        invalid = [
            None,
            {},
            {"length": 1},
            {"length": True, "angle": 0},
            {"length": 1, "angle": 0.5},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(
                (TypeError, ValueError)
            ):
                scad.Dimension.from_dict(payload)
        with self.assertRaises(TypeError):
            scad.LENGTH.power(0.5)
        with self.assertRaises(scad.UnitValidationError):
            scad.LENGTH.square_root()

    def test_every_registered_unit_converts_to_canonical_units(self):
        conversions = [
            (scad.MM, 1.0),
            (scad.CM, 10.0),
            (scad.M, 1000.0),
            (scad.INCH, 25.4),
            (scad.FOOT, 304.8),
            (scad.DEGREE, 1.0),
            (scad.RADIAN, 180.0 / math.pi),
            (scad.ONE, 1.0),
            (scad.PERCENT, 0.01),
            (scad.SQUARE_MM, 1.0),
            (scad.SQUARE_CM, 100.0),
            (scad.SQUARE_M, 1_000_000.0),
            (scad.SQUARE_INCH, 25.4**2),
            (scad.SQUARE_FOOT, 304.8**2),
            (scad.CUBIC_MM, 1.0),
            (scad.CUBIC_CM, 1000.0),
            (scad.CUBIC_M, 1_000_000_000.0),
            (scad.CUBIC_INCH, 25.4**3),
            (scad.CUBIC_FOOT, 304.8**3),
        ]
        for unit, expected in conversions:
            with self.subTest(unit=unit.symbol):
                self.assertAlmostEqual(unit.to_canonical(1.0), expected)
                self.assertAlmostEqual(unit.from_canonical(expected), 1.0)
                self.assertIs(scad.get_unit(unit), unit)
                self.assertEqual(scad.get_unit(unit.symbol), unit)
                self.assertEqual(
                    scad.canonical_unit_for_dimension(unit.dimension).dimension,
                    unit.dimension,
                )

    def test_unit_aliases_and_conversion(self):
        aliases = {
            "millimeters": scad.MM,
            "centimeter": scad.CM,
            "meters": scad.M,
            "inches": scad.INCH,
            "feet": scad.FOOT,
            "degrees": scad.DEGREE,
            "radians": scad.RADIAN,
            "percent": scad.PERCENT,
            "square feet": scad.SQUARE_FOOT,
            "cubic inches": scad.CUBIC_INCH,
            "ml": scad.CUBIC_CM,
        }
        for alias, unit in aliases.items():
            with self.subTest(alias=alias):
                self.assertEqual(scad.get_unit(alias), unit)
        self.assertAlmostEqual(scad.convert_value(1.0, "in", "mm"), 25.4)
        self.assertAlmostEqual(scad.convert_value(180.0, "deg", "rad"), math.pi)
        self.assertAlmostEqual(scad.convert_value(1.0, "ft^2", "in^2"), 144.0)
        with self.assertRaises(scad.UnitValidationError):
            scad.convert_value(1.0, "mm", "deg")
        with self.assertRaisesRegex(ValueError, "Unknown unit"):
            scad.get_unit("parsec")

    def test_unit_validation_and_custom_unit_roundtrip(self):
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
            lambda: unit_to_payload(None),
        ]
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()

        thou = scad.Unit("thou", scad.LENGTH, 0.0254)
        width = scad.var(
            "width", 1000.0, unit=thou, tolerance=2.0, tolerance_unit=thou
        )
        graph = scad.ExpressionGraph()
        graph.register(width)
        payload = graph.to_dict()
        self.assertIsInstance(payload["nodes"][0]["unit"], dict)

        rebuilt = scad.ExpressionGraph.from_dict(payload).get(width.expr_id)
        self.assertIsInstance(rebuilt, scad.Var)
        self.assertEqual(rebuilt.unit, thou)
        self.assertEqual(rebuilt.tolerance_unit, thou)
        self.assertAlmostEqual(rebuilt.evaluate(), 25.4)
        self.assertAlmostEqual(rebuilt.canonical_tolerance.upper_deviation, 0.0508)

    def test_unknown_compound_dimension_uses_a_canonical_scale_one_unit(self):
        dimension = scad.Dimension(length=-1, angle=2)
        unit = scad.canonical_unit_for_dimension(dimension)

        self.assertEqual(unit.symbol, "L^-1 A^2")
        self.assertEqual(unit.dimension, dimension)
        self.assertEqual(unit.scale_to_canonical, 1.0)

    def test_malformed_custom_unit_payloads_are_rejected(self):
        base = {
            "nodes": [
                {
                    "expr_id": "var_x",
                    "kind": "var",
                    "name": "x",
                    "default": 1.0,
                    "unit": {
                        "symbol": "custom",
                        "dimension": {"length": 1, "angle": 0},
                        "scale_to_canonical": 2.0,
                    },
                }
            ]
        }
        for field in ("symbol", "dimension", "scale_to_canonical"):
            payload = json.loads(json.dumps(base))
            del payload["nodes"][0]["unit"][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                scad.ExpressionGraph.from_dict(payload)


class TestUnitAwareVariables(unittest.TestCase):
    def test_nominal_and_tolerance_units_are_canonicalized_independently(self):
        width = scad.var(
            "width",
            1.0,
            unit="in",
            tolerance=(-0.1, 0.2),
            tolerance_unit="mm",
        )
        inherited = scad.var("inherited", 1.0, unit="in", tolerance=0.01)

        self.assertEqual(width.default, 1.0)
        self.assertEqual(width.tolerance, scad.DimensionTolerance(-0.1, 0.2))
        self.assertEqual(width.unit, scad.INCH)
        self.assertEqual(width.tolerance_unit, scad.MM)
        self.assertAlmostEqual(width.canonical_default, 25.4)
        self.assertEqual(
            width.canonical_tolerance, scad.DimensionTolerance(-0.1, 0.2)
        )
        self.assertEqual(inherited.tolerance_unit, scad.INCH)
        self.assertAlmostEqual(
            inherited.canonical_tolerance.upper_deviation, 0.254
        )

    def test_bindings_use_the_variable_declaration_unit(self):
        width = scad.var("width", 1.0, unit="in")
        self.assertAlmostEqual(width.evaluate({"width": 2.0}), 50.8)
        self.assertAlmostEqual((width + 1.0).evaluate({"width": 2.0}), 51.8)

    def test_invalid_variable_unit_combinations_are_rejected(self):
        invalid_calls = [
            lambda: scad.var("x", 1.0, tolerance=0.1, tolerance_unit="mm"),
            lambda: scad.var("x", 1.0, unit="mm", tolerance_unit="mm"),
            lambda: scad.var(
                "x", 1.0, unit="mm", tolerance=0.1, tolerance_unit="deg"
            ),
            lambda: scad.var("x", 1.0, unit="unknown"),
            lambda: scad.var("x", 1e308, unit="m"),
            lambda: scad.var("x", 1.0, unit="mm", tolerance=1e308, tolerance_unit="m"),
        ]
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()

    def test_expression_graph_roundtrip_preserves_registered_units(self):
        angle = scad.var(
            "angle", math.pi / 2.0, unit="rad", tolerance=0.5, tolerance_unit="deg"
        )
        expression = scad.sin(angle)
        graph = scad.ExpressionGraph()
        graph.register(expression)

        payload = graph.to_dict()
        rebuilt = scad.ExpressionGraph.from_dict(payload)
        rebuilt_angle = rebuilt.get(angle.expr_id)

        self.assertEqual(rebuilt_angle.unit, scad.RADIAN)
        self.assertEqual(rebuilt_angle.tolerance_unit, scad.DEGREE)
        self.assertAlmostEqual(rebuilt.get(expression.expr_id).evaluate(), 1.0)

    def test_geometry_parameters_use_canonical_cad_values(self):
        width = scad.var("width", 1.0, unit="in")
        with scad.GraphSession() as session:
            scad.make_box_rsolid(width, 2.0, 3.0)

        node = session.graph.topological_order()[0]
        self.assertAlmostEqual(node.params["width"], 25.4)
        self.assertEqual(node.param_exprs["width"]["expr_id"], width.expr_id)


class TestDimensionInference(unittest.TestCase):
    def setUp(self):
        self.length = scad.var("length", 3.0, unit="mm")
        self.other_length = scad.var("other_length", 4.0, unit="cm")
        self.angle = scad.var("angle", 90.0, unit="deg")
        self.scalar = scad.var("scalar", 50.0, unit="%")

    def test_addition_subtraction_and_contextual_constants(self):
        self.assertEqual(scad.infer_dimension(self.length + self.other_length), scad.LENGTH)
        self.assertEqual(scad.infer_dimension(self.length - 1.0), scad.LENGTH)
        self.assertEqual(scad.infer_dimension(1.0 + self.angle), scad.ANGLE)
        self.assertAlmostEqual((self.length + self.other_length).evaluate(), 43.0)

    def test_multiplication_division_and_powers(self):
        area = self.length * self.other_length
        volume = area * self.length
        ratio = self.length / self.other_length
        inverse = 1.0 / self.length

        self.assertEqual(scad.infer_dimension(area), scad.AREA)
        self.assertEqual(scad.infer_dimension(volume), scad.VOLUME)
        self.assertEqual(scad.infer_dimension(ratio), scad.DIMENSIONLESS)
        self.assertEqual(scad.infer_dimension(inverse), scad.Dimension(length=-1))
        self.assertEqual(scad.infer_dimension(self.length**3), scad.VOLUME)
        self.assertEqual(scad.infer_dimension(self.length**0), scad.DIMENSIONLESS)
        self.assertEqual(
            scad.infer_dimension(self.scalar ** scad.var("power", 2.0, unit="1")),
            scad.DIMENSIONLESS,
        )

    def test_square_root_requires_even_dimension_exponents(self):
        diagonal = scad.sqrt(self.length**2 + self.other_length**2)
        self.assertEqual(scad.infer_dimension(diagonal), scad.LENGTH)
        self.assertAlmostEqual(diagonal.evaluate(), math.sqrt(1609.0))
        self.assertEqual(scad.infer_dimension(scad.sqrt(self.scalar)), scad.DIMENSIONLESS)
        with self.assertRaises(scad.UnitValidationError):
            scad.infer_dimension(scad.sqrt(self.length))
        with self.assertRaises(scad.UnitValidationError):
            scad.infer_dimension(self.length**0.5)

    def test_unary_and_trigonometric_dimensions(self):
        self.assertEqual(scad.infer_dimension(-self.length), scad.LENGTH)
        self.assertEqual(scad.infer_dimension(abs(self.length)), scad.LENGTH)
        for expression in (
            scad.sin(self.angle),
            scad.cos(self.angle),
            scad.tan(self.angle),
        ):
            self.assertEqual(scad.infer_dimension(expression), scad.DIMENSIONLESS)
        for expression in (
            scad.asin(self.scalar),
            scad.acos(self.scalar),
            scad.atan(self.scalar),
            scad.atan2(self.length, self.other_length),
        ):
            self.assertEqual(scad.infer_dimension(expression), scad.ANGLE)

    def test_invalid_physical_expressions_are_rejected(self):
        legacy = scad.var("legacy", 1.0)
        invalid = [
            self.length + self.angle,
            self.length + self.scalar,
            self.length + legacy,
            self.length * legacy,
            self.length ** self.scalar,
            self.length ** self.angle,
            self.length ** legacy,
            self.length**0.25,
            scad.sin(self.length),
            scad.asin(self.length),
            scad.atan2(self.length, self.angle),
        ]
        for expression in invalid:
            with self.subTest(op=expression.op), self.assertRaises(
                scad.UnitValidationError
            ):
                scad.infer_dimension(expression)

        with self.assertRaises(scad.UnitValidationError):
            (self.length + self.angle).evaluate()

    def test_inference_cache_does_not_hide_conflicting_duplicate_ids(self):
        length = scad.Var("length", 1.0, expr_id="same", unit=scad.MM)
        angle = scad.Var("angle", 1.0, expr_id="same", unit=scad.DEGREE)
        expression = scad.Expr("add", (length, angle))

        with self.assertRaises(scad.UnitValidationError):
            scad.infer_dimension(expression)
        with self.assertRaisesRegex(ValueError, "different node"):
            scad.ExpressionGraph().register(expression)

    def test_inference_rejects_mutated_cycles_ops_and_node_types(self):
        cycle = scad.Expr("neg", (scad.const(1.0),), expr_id="cycle")
        object.__setattr__(cycle, "args", (cycle,))
        with self.assertRaisesRegex(scad.UnitValidationError, "cycle"):
            scad.infer_dimension(cycle)

        unsupported = scad.Expr("neg", (scad.const(1.0),))
        object.__setattr__(unsupported, "op", "unsupported")
        with self.assertRaisesRegex(scad.UnitValidationError, "Unsupported"):
            scad.infer_dimension(unsupported)

        with self.assertRaisesRegex(TypeError, "Unsupported expression node"):
            _infer(object(), {}, set())

    def test_legacy_expressions_keep_radian_math_and_unknown_dimension(self):
        value = scad.var("legacy", 0.5)
        expression = value ** scad.var("legacy_power", 2.0)

        self.assertIsNone(scad.infer_dimension(expression))
        self.assertFalse(scad.expression_uses_units(expression))
        self.assertAlmostEqual(scad.sin(value).evaluate(), math.sin(0.5))
        self.assertAlmostEqual(scad.asin(value).evaluate(), math.asin(0.5))
        self.assertIsNone(scad.infer_dimension(scad.sin(value)))
        self.assertIsNone(scad.infer_dimension(value + value))
        self.assertIsNone(scad.infer_dimension(scad.atan2(value, value)))


class TestUnitAwareMathAndTolerance(unittest.TestCase):
    def test_trigonometric_evaluation_uses_degrees_canonically(self):
        degrees = scad.var("degrees", 90.0, unit="deg")
        radians = scad.var("radians", math.pi / 2.0, unit="rad")
        ratio = scad.var("ratio", 50.0, unit="%")
        y = scad.var("y", 1.0, unit="in")
        x = scad.var("x", 25.4, unit="mm")

        self.assertAlmostEqual(scad.sin(degrees).evaluate(), 1.0)
        self.assertAlmostEqual(scad.sin(radians).evaluate(), 1.0)
        self.assertAlmostEqual(scad.asin(ratio).evaluate(), 30.0)
        self.assertAlmostEqual(scad.atan2(y, x).evaluate(), 45.0)

    def test_diagonal_tolerance_chain_reports_length_in_mm(self):
        width = scad.var(
            "width", 3.0, unit="cm", tolerance=0.1, tolerance_unit="mm"
        )
        height = scad.var("height", 40.0, unit="mm", tolerance=0.2)
        diagonal = scad.sqrt(width**2 + height**2)

        worst_case = scad.analyze_tolerance(diagonal)
        rss = scad.analyze_tolerance(diagonal, method="rss")

        self.assertEqual(worst_case.dimension, scad.LENGTH)
        self.assertEqual(worst_case.unit, scad.MM)
        self.assertAlmostEqual(worst_case.nominal, 50.0)
        self.assertLess(worst_case.lower_deviation, 0.0)
        self.assertGreater(worst_case.upper_deviation, 0.0)
        expected_rss = math.hypot(0.6 * 0.1, 0.8 * 0.2)
        self.assertAlmostEqual(rss.upper_deviation, expected_rss, places=12)
        self.assertTrue(all(item.source_unit == scad.MM for item in rss.contributions))

    def test_angle_tolerance_propagation_converts_derivatives(self):
        angle = scad.var("angle", 30.0, unit="deg", tolerance=1.0)
        result = scad.analyze_tolerance(scad.sin(angle), method="rss")
        expected = math.cos(math.radians(30.0)) * math.pi / 180.0

        self.assertEqual(result.dimension, scad.DIMENSIONLESS)
        self.assertEqual(result.unit, scad.ONE)
        self.assertAlmostEqual(result.nominal, 0.5)
        self.assertAlmostEqual(result.upper_deviation, expected, places=12)

    def test_inverse_trig_and_atan2_tolerances_report_degrees(self):
        ratio = scad.var("ratio", 50.0, unit="%", tolerance=1.0)
        y = scad.var("y", 10.0, unit="mm", tolerance=0.1)
        x = scad.var("x", 10.0, unit="mm", tolerance=0.1)

        asin_result = scad.analyze_tolerance(scad.asin(ratio), method="rss")
        atan2_result = scad.analyze_tolerance(scad.atan2(y, x), method="rss")

        self.assertEqual(asin_result.unit, scad.DEGREE)
        self.assertAlmostEqual(asin_result.nominal, 30.0)
        self.assertEqual(atan2_result.unit, scad.DEGREE)
        self.assertAlmostEqual(atan2_result.nominal, 45.0)

    def test_area_and_volume_analysis_are_inferred_but_not_requirements(self):
        width = scad.var("width", 2.0, unit="mm", tolerance=0.1)
        area = width**2
        volume = width**3

        self.assertEqual(scad.analyze_tolerance(area).dimension, scad.AREA)
        self.assertEqual(scad.analyze_tolerance(volume).dimension, scad.VOLUME)
        with self.assertRaisesRegex(ValueError, "Length or Angle"):
            scad.check_tolerance(area, 0.5, tolerance_unit="mm^2")


class TestUnitAwareRequirementsAndPersistence(unittest.TestCase):
    def test_requirement_tolerance_units_are_converted_before_comparison(self):
        width = scad.var(
            "width", 1.0, unit="in", tolerance=0.1, tolerance_unit="mm"
        )
        passing = scad.check_tolerance(width, 0.004, tolerance_unit="in")
        failing = scad.check_tolerance(width, 0.003, tolerance_unit="in")

        self.assertTrue(passing.passed)
        self.assertFalse(failing.passed)
        self.assertEqual(passing.requirement.tolerance_unit, scad.INCH)
        self.assertAlmostEqual(
            passing.requirement.canonical_tolerance.upper_deviation, 0.1016
        )

    def test_requirement_unit_validation(self):
        length = scad.var("length", 10.0, unit="mm", tolerance=0.1)
        legacy = scad.var("legacy", 10.0, tolerance=0.1)
        scalar = scad.var("scalar", 1.0, unit="1", tolerance=0.1)

        with self.assertRaisesRegex(ValueError, "incompatible"):
            scad.check_tolerance(length, 1.0, tolerance_unit="deg")
        with self.assertRaisesRegex(ValueError, "unit-aware"):
            scad.check_tolerance(legacy, 1.0, tolerance_unit="mm")
        with self.assertRaisesRegex(ValueError, "Length or Angle"):
            scad.check_tolerance(scalar, 0.1)

    def test_session_model_and_tolerance_graph_roundtrip_units(self):
        width = scad.var(
            "width", 1.0, unit="in", tolerance=0.1, tolerance_unit="mm"
        )
        with scad.GraphSession() as session:
            scad.make_box_rsolid(width, 2.0, 3.0)
            requirement = session.require_tolerance(
                width, 0.004, tolerance_unit="in", name="width"
            )

        raw = json.loads(scad.export_model_json(session))
        self.assertEqual(raw["expression_graph"]["nodes"][0]["unit"], "in")
        self.assertEqual(
            raw["expression_graph"]["nodes"][0]["tolerance_unit"], "mm"
        )
        self.assertEqual(
            raw["tolerance_graph"]["requirements"][0]["tolerance_unit"], "in"
        )
        self.assertEqual(
            raw["tolerance_graph"]["requirements"][0]["target_dimension"],
            scad.LENGTH.to_dict(),
        )

        imported = scad.import_model_json(json.dumps(raw))
        rebuilt = imported["tolerance_graph"].requirements[0]
        self.assertEqual(rebuilt, requirement)
        self.assertTrue(imported["tolerance_graph"].validate().passed)
        self.assertEqual(len(scad.replay_model_json(json.dumps(raw))), 1)

    def test_import_rejects_tampered_requirement_units_and_dimensions(self):
        width = scad.var("width", 10.0, unit="mm", tolerance=0.1)
        expressions = scad.ExpressionGraph()
        tolerances = scad.ToleranceGraph(expressions)
        tolerances.require(width, 0.1, tolerance_unit="mm", requirement_id="req")
        expression_payload = expressions.to_dict()

        wrong_unit = tolerances.to_dict()
        wrong_unit["requirements"][0]["tolerance_unit"] = "deg"
        with self.assertRaisesRegex(ValueError, "incompatible"):
            scad.ToleranceGraph.from_dict(
                wrong_unit, scad.ExpressionGraph.from_dict(expression_payload)
            )

        wrong_dimension = tolerances.to_dict()
        wrong_dimension["requirements"][0]["target_dimension"] = scad.ANGLE.to_dict()
        with self.assertRaisesRegex(ValueError, "does not match"):
            scad.ToleranceGraph.from_dict(
                wrong_dimension, scad.ExpressionGraph.from_dict(expression_payload)
            )

        missing_dimension = tolerances.to_dict()
        missing_dimension["requirements"][0]["target_dimension"] = None
        with self.assertRaisesRegex(ValueError, "does not match"):
            scad.ToleranceGraph.from_dict(
                missing_dimension, scad.ExpressionGraph.from_dict(expression_payload)
            )

    def test_legacy_payloads_and_requirements_remain_compatible(self):
        width = scad.var("width", 10.0, tolerance=0.1)
        graph = scad.ExpressionGraph()
        tolerance_graph = scad.ToleranceGraph(graph)
        tolerance_graph.require(width, 0.1, requirement_id="legacy")
        payload = tolerance_graph.to_dict()
        payload["requirements"][0].pop("tolerance_unit")
        payload["requirements"][0].pop("target_dimension")

        rebuilt = scad.ToleranceGraph.from_dict(payload, graph)
        requirement = rebuilt.requirements[0]
        self.assertIsNone(requirement.tolerance_unit)
        self.assertIsNone(requirement.target_dimension)
        self.assertTrue(rebuilt.validate().passed)


if __name__ == "__main__":
    unittest.main()
