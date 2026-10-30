// Port of test/test_units.py (dimensions, units, variables with units,
// dimension inference).
#include "doctest.h"

#include <cmath>
#include <numbers>

#include "scad/reactive/expr.hpp"
#include "scad/reactive/expr_graph.hpp"
#include "scad/reactive/units.hpp"

using namespace scad;
using namespace scad::reactive;

TEST_CASE("named dimensions and dimension algebra") {
  CHECK(kDimensionless.name() == "Dimensionless");
  CHECK(kLength.name() == "Length");
  CHECK(kArea.name() == "Area");
  CHECK(kVolume.name() == "Volume");
  CHECK(kAngle.name() == "Angle");
  CHECK(kLength.multiply(kLength) == kArea);
  CHECK(kVolume.divide(kLength) == kArea);
  CHECK(kLength.power(3) == kVolume);
  CHECK(kArea.square_root() == kLength);
  CHECK(Dimension{-1, 2}.symbol() == "L^-1 A^2");
  CHECK(kDimensionless.symbol() == "1");
  CHECK(kDimensionless.is_dimensionless());
  CHECK(kLength.is_design_dimension());
  CHECK(kAngle.is_design_dimension());
  CHECK_FALSE(kArea.is_design_dimension());
  CHECK_THROWS_AS(kLength.square_root(), UnitValidationError);
}

TEST_CASE("dimension payloads validate like Dimension.from_dict") {
  CHECK(Dimension::from_value(kVolume.to_value()) == kVolume);
  Value only_length = Value::object();
  only_length.set("length", 1);
  CHECK_THROWS_AS(Dimension::from_value(Value()), TypeError);
  CHECK_THROWS_AS(Dimension::from_value(Value::object()), ValueError);
  CHECK_THROWS_AS(Dimension::from_value(only_length), ValueError);
  Value bool_length = Value::object();
  bool_length.set("length", true);
  bool_length.set("angle", 0);
  CHECK_THROWS_AS(Dimension::from_value(bool_length), TypeError);
  Value fractional = Value::object();
  fractional.set("length", 1);
  fractional.set("angle", 0.5);
  CHECK_THROWS_AS(Dimension::from_value(fractional), TypeError);
}

TEST_CASE("every registered unit converts to canonical units") {
  struct Row {
    const Unit* unit;
    double scale;
  };
  const Row rows[] = {
      {&units::mm(), 1.0},
      {&units::cm(), 10.0},
      {&units::m(), 1000.0},
      {&units::inch(), 25.4},
      {&units::foot(), 304.8},
      {&units::degree(), 1.0},
      {&units::radian(), 180.0 / std::numbers::pi},
      {&units::one(), 1.0},
      {&units::percent(), 0.01},
      {&units::square_mm(), 1.0},
      {&units::square_cm(), 100.0},
      {&units::square_m(), 1e6},
      {&units::square_inch(), 25.4 * 25.4},
      {&units::square_foot(), 304.8 * 304.8},
      {&units::cubic_mm(), 1.0},
      {&units::cubic_cm(), 1000.0},
      {&units::cubic_m(), 1e9},
      {&units::cubic_inch(), 25.4 * 25.4 * 25.4},
      {&units::cubic_foot(), 304.8 * 304.8 * 304.8},
  };
  for (const Row& row : rows) {
    CAPTURE(row.unit->symbol());
    CHECK(row.unit->to_canonical(1.0) == doctest::Approx(row.scale));
    CHECK(row.unit->from_canonical(row.scale) == doctest::Approx(1.0));
    CHECK(get_unit(row.unit->symbol()) == *row.unit);
    CHECK(canonical_unit_for_dimension(row.unit->dimension()).dimension() == row.unit->dimension());
  }
}

TEST_CASE("unit aliases and conversion") {
  CHECK(get_unit("millimeters") == units::mm());
  CHECK(get_unit("centimeter") == units::cm());
  CHECK(get_unit("meters") == units::m());
  CHECK(get_unit("inches") == units::inch());
  CHECK(get_unit("feet") == units::foot());
  CHECK(get_unit("degrees") == units::degree());
  CHECK(get_unit("radians") == units::radian());
  CHECK(get_unit("percent") == units::percent());
  CHECK(get_unit("square feet") == units::square_foot());
  CHECK(get_unit("cubic inches") == units::cubic_inch());
  CHECK(get_unit("ml") == units::cubic_cm());
  CHECK(get_unit("  MM ") == units::mm());
  CHECK(get_unit("\xC2\xB0") == units::degree());
  CHECK(convert_value(1.0, "in", "mm") == doctest::Approx(25.4));
  CHECK(convert_value(180.0, "deg", "rad") == doctest::Approx(std::numbers::pi));
  CHECK(convert_value(1.0, "ft^2", "in^2") == doctest::Approx(144.0));
  CHECK_THROWS_AS(convert_value(1.0, "mm", "deg"), UnitValidationError);
  try {
    get_unit("parsec");
    FAIL("expected an error");
  } catch (const ValueError& e) {
    CHECK(std::string(e.what()).find("Unknown unit") != std::string::npos);
    CHECK(std::string(e.what()).find("supported units: %, 1, cm,") != std::string::npos);
  }
  CHECK_THROWS_AS(get_unit(""), TypeError);
}

TEST_CASE("unit validation and range checks") {
  CHECK_THROWS_AS(Unit("", kLength, 1.0), ValueError);
  CHECK_THROWS_AS(Unit("bad", kLength, 0.0), ValueError);
  CHECK_THROWS_AS(Unit("bad", kLength, HUGE_VAL), ValueError);
  CHECK_THROWS_AS(units::mm().to_canonical(HUGE_VAL), ValueError);
  CHECK_THROWS_AS(units::m().to_canonical(1e308), ValueError);
  CHECK_THROWS_AS(Unit("tiny", kLength, 5e-324).to_canonical(0.5), ValueError);
  CHECK_THROWS_AS(Unit("tiny", kLength, 5e-324).from_canonical(1.0), ValueError);
  CHECK_THROWS_AS(Unit("huge", kLength, 1e308).from_canonical(5e-324), ValueError);
  CHECK_THROWS_AS(Unit::from_value(Value()), TypeError);
  CHECK_THROWS_AS(unit_from_payload(Value(3)), TypeError);
}

TEST_CASE("a custom unit roundtrips through the expression graph") {
  const Unit thou("thou", kLength, 0.0254);
  const auto width = make_var("width", 1000.0, std::nullopt, DimensionTolerance(-2.0, 2.0), thou, thou);
  ExpressionGraph graph;
  graph.register_expr(ScalarPtr(width));
  const Value payload = graph.to_value();
  const Value& unit_payload = *payload.find("nodes")->as_array()[0].find("unit");
  CHECK(unit_payload.is_object());

  const ExpressionGraph rebuilt = ExpressionGraph::from_value(payload);
  const auto node = std::dynamic_pointer_cast<const Var>(rebuilt.get(width->expr_id()));
  REQUIRE(node);
  CHECK(*node->unit() == thou);
  CHECK(*node->tolerance_unit() == thou);
  CHECK(node->eval(nullptr) == doctest::Approx(25.4));
  CHECK(node->canonical_tolerance()->upper_deviation() == doctest::Approx(0.0508));
}

TEST_CASE("unknown compound dimensions use a canonical scale-one unit") {
  const Dimension d{-1, 2};
  const Unit unit = canonical_unit_for_dimension(d);
  CHECK(unit.symbol() == "L^-1 A^2");
  CHECK(unit.dimension() == d);
  CHECK(unit.scale_to_canonical() == 1.0);
}

TEST_CASE("malformed custom unit payloads are rejected") {
  for (const char* field : {"symbol", "dimension", "scale_to_canonical"}) {
    Value unit = Unit("custom", kLength, 2.0).to_value();
    unit.erase(field);
    Value node = Value::object();
    node.set("expr_id", "var_x");
    node.set("kind", "var");
    node.set("name", "x");
    node.set("default", 1.0);
    node.set("unit", unit);
    Value nodes = Value::array();
    nodes.push_back(node);
    Value payload = Value::object();
    payload.set("nodes", nodes);
    CAPTURE(field);
    CHECK_THROWS_AS(ExpressionGraph::from_value(payload), ValueError);
  }
}

// ---------------------------------------------------------------------------
// Variables with units
// ---------------------------------------------------------------------------

TEST_CASE("nominal and tolerance units are canonicalized independently") {
  const auto width = make_var("width", 1.0, std::nullopt, DimensionTolerance(-0.1, 0.2), units::inch(), units::mm());
  const auto inherited = make_var("inherited", 1.0, std::nullopt, DimensionTolerance::symmetric(0.01), units::inch());
  CHECK(width->default_value() == 1.0);
  CHECK(*width->unit() == units::inch());
  CHECK(*width->tolerance_unit() == units::mm());
  CHECK(width->canonical_default() == doctest::Approx(25.4));
  CHECK(*width->canonical_tolerance() == DimensionTolerance(-0.1, 0.2));
  CHECK(*inherited->tolerance_unit() == units::inch());
  CHECK(inherited->canonical_tolerance()->upper_deviation() == doctest::Approx(0.254));
}

TEST_CASE("bindings use the variable's declared unit") {
  const Sym width = make_var("width", 1.0, std::nullopt, std::nullopt, units::inch());
  const Bindings two{{"width", 2.0}};
  CHECK(width.value(&two) == doctest::Approx(50.8));
  CHECK((width + 1.0).value(&two) == doctest::Approx(51.8));
}

TEST_CASE("invalid variable unit combinations are rejected") {
  const auto tol = DimensionTolerance::symmetric(0.1);
  CHECK_THROWS_AS(make_var("x", 1.0, std::nullopt, tol, std::nullopt, units::mm()), ValueError);
  CHECK_THROWS_AS(make_var("x", 1.0, std::nullopt, std::nullopt, units::mm(), units::mm()), ValueError);
  CHECK_THROWS_AS(make_var("x", 1.0, std::nullopt, tol, units::mm(), units::degree()), ValueError);
  CHECK_THROWS_AS(make_var("x", 1e308, std::nullopt, std::nullopt, units::m()), ValueError);
  CHECK_THROWS_AS(make_var("x", 1.0, std::nullopt, DimensionTolerance::symmetric(1e308), units::mm(), units::m()),
                  ValueError);
  CHECK_THROWS_AS(make_var("", 1.0), ValueError);
  CHECK_THROWS_AS(make_var("x", HUGE_VAL), ValueError);
}

TEST_CASE("the expression graph roundtrip keeps registered units") {
  const auto angle = make_var("angle", std::numbers::pi / 2.0, std::nullopt, DimensionTolerance::symmetric(0.5),
                              units::radian(), units::degree());
  const Sym expression = sin(Sym(ScalarPtr(angle)));
  ExpressionGraph graph;
  graph.register_expr(expression.node());
  const ExpressionGraph rebuilt = ExpressionGraph::from_value(graph.to_value());
  const auto back = std::dynamic_pointer_cast<const Var>(rebuilt.get(angle->expr_id()));
  REQUIRE(back);
  CHECK(*back->unit() == units::radian());
  CHECK(*back->tolerance_unit() == units::degree());
  CHECK(rebuilt.get(expression.expr_id())->eval(nullptr) == doctest::Approx(1.0));
}

// ---------------------------------------------------------------------------
// Dimension inference
// ---------------------------------------------------------------------------

namespace {
struct Quantities {
  Sym length = make_var("length", 3.0, std::nullopt, std::nullopt, units::mm());
  Sym other_length = make_var("other_length", 4.0, std::nullopt, std::nullopt, units::cm());
  Sym angle = make_var("angle", 90.0, std::nullopt, std::nullopt, units::degree());
  Sym scalar = make_var("scalar", 50.0, std::nullopt, std::nullopt, units::percent());
};
std::optional<Dimension> dim(const Sym& s) {
  return infer_dimension(s.node());
}
}  // namespace

TEST_CASE("addition, subtraction and contextual constants") {
  Quantities q;
  CHECK(dim(q.length + q.other_length) == kLength);
  CHECK(dim(q.length - 1.0) == kLength);
  CHECK(dim(1.0 + q.angle) == kAngle);
  CHECK((q.length + q.other_length).value() == doctest::Approx(43.0));
}

TEST_CASE("multiplication, division and powers") {
  Quantities q;
  CHECK(dim(q.length * q.other_length) == kArea);
  CHECK(dim(q.length * q.other_length * q.length) == kVolume);
  CHECK(dim(q.length / q.other_length) == kDimensionless);
  CHECK(dim(Sym(1.0) / q.length) == Dimension{-1, 0});
  CHECK(dim(pow(q.length, 3)) == kVolume);
  CHECK(dim(pow(q.length, 0)) == kDimensionless);
  const Sym power = make_var("power", 2.0, std::nullopt, std::nullopt, units::one());
  CHECK(dim(pow(q.scalar, power)) == kDimensionless);
}

TEST_CASE("square root requires even dimension exponents") {
  Quantities q;
  const Sym diagonal = sqrt(pow(q.length, 2) + pow(q.other_length, 2));
  CHECK(dim(diagonal) == kLength);
  CHECK(diagonal.value() == doctest::Approx(std::sqrt(1609.0)));
  CHECK(dim(sqrt(q.scalar)) == kDimensionless);
  CHECK_THROWS_AS(dim(sqrt(q.length)), UnitValidationError);
  CHECK_THROWS_AS(dim(pow(q.length, 0.5)), UnitValidationError);
}

TEST_CASE("unary and trigonometric dimensions") {
  Quantities q;
  CHECK(dim(-q.length) == kLength);
  CHECK(dim(abs(q.length)) == kLength);
  CHECK(dim(sin(q.angle)) == kDimensionless);
  CHECK(dim(cos(q.angle)) == kDimensionless);
  CHECK(dim(tan(q.angle)) == kDimensionless);
  CHECK(dim(asin(q.scalar)) == kAngle);
  CHECK(dim(acos(q.scalar)) == kAngle);
  CHECK(dim(atan(q.scalar)) == kAngle);
  CHECK(dim(atan2(q.length, q.other_length)) == kAngle);
}

TEST_CASE("invalid physical expressions are rejected") {
  Quantities q;
  const Sym legacy = make_var("legacy", 1.0);
  const Sym invalid[] = {q.length + q.angle,      q.length + q.scalar,    q.length + legacy,       q.length * legacy,
                         pow(q.length, q.scalar), pow(q.length, q.angle), pow(q.length, legacy),   pow(q.length, 0.25),
                         sin(q.length),           asin(q.length),         atan2(q.length, q.angle)};
  for (const Sym& expression : invalid) {
    CAPTURE(expression.node()->repr());
    CHECK_THROWS_AS(infer_dimension(expression.node()), UnitValidationError);
  }
  // Building never throws; evaluating does.
  CHECK_THROWS_AS((q.length + q.angle).value(), UnitValidationError);
}

TEST_CASE("duplicate ids do not hide a dimension conflict") {
  const auto length = Var::make({.name = "length", .default_value = 1.0, .unit = units::mm(), .expr_id = "same"});
  const auto angle = Var::make({.name = "angle", .default_value = 1.0, .unit = units::degree(), .expr_id = "same"});
  const auto expression = Expr::make("add", {length, angle});
  CHECK_THROWS_AS(infer_dimension(ScalarPtr(expression)), UnitValidationError);
  ExpressionGraph graph;
  try {
    graph.register_expr(ScalarPtr(expression));
    FAIL("expected a ValueError");
  } catch (const ValueError& e) {
    CHECK(std::string(e.what()).find("different node") != std::string::npos);
  }
  CHECK(graph.node_count() == 0);  // atomic
}

TEST_CASE("legacy expressions keep radian math and an unknown dimension") {
  const Sym value = make_var("legacy", 0.5);
  const Sym expression = pow(value, make_var("legacy_power", 2.0));
  CHECK_FALSE(infer_dimension(expression.node()).has_value());
  CHECK_FALSE(expression_uses_units(expression.node()));
  CHECK(sin(value).value() == doctest::Approx(std::sin(0.5)));
  CHECK(asin(value).value() == doctest::Approx(std::asin(0.5)));
  CHECK_FALSE(infer_dimension((value + value).node()).has_value());
  CHECK_FALSE(infer_dimension(atan2(value, value).node()).has_value());
}

TEST_CASE("trigonometric evaluation uses degrees canonically") {
  const Sym degrees = make_var("degrees", 90.0, std::nullopt, std::nullopt, units::degree());
  const Sym radians = make_var("radians", std::numbers::pi / 2.0, std::nullopt, std::nullopt, units::radian());
  const Sym ratio = make_var("ratio", 50.0, std::nullopt, std::nullopt, units::percent());
  const Sym y = make_var("y", 1.0, std::nullopt, std::nullopt, units::inch());
  const Sym x = make_var("x", 25.4, std::nullopt, std::nullopt, units::mm());
  CHECK(sin(degrees).value() == doctest::Approx(1.0));
  CHECK(sin(radians).value() == doctest::Approx(1.0));
  CHECK(asin(ratio).value() == doctest::Approx(30.0));
  CHECK(atan2(y, x).value() == doctest::Approx(45.0));
}
