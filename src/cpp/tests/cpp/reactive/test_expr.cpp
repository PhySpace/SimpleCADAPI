// Port of test/test_expr_graph.py and the expression parts of
// test/test_graph_lineage.py; ids and reprs are the Python SDK's.
#include "doctest.h"

#include <cmath>

#include "scad/reactive/digest.hpp"
#include "scad/reactive/expr.hpp"
#include "scad/reactive/expr_graph.hpp"
#include "scad/reactive/param_path.hpp"

using namespace scad;
using namespace scad::reactive;

TEST_CASE("digest helpers produce Python's text forms") {
  CHECK(sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  CHECK(sha256_hex("").substr(0, 8) == "e3b0c442");
  // Block boundaries: 55, 56 and 64 bytes pad differently.
  CHECK(sha256_hex(std::string(55, 'a')) == "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318");
  CHECK(sha256_hex(std::string(56, 'a')) == "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a");
  CHECK(sha256_hex(std::string(64, 'a')) == "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb");

  CHECK(py_float_hex(0.1) == "0x1.999999999999ap-4");
  CHECK(py_float_hex(-2.5) == "-0x1.4000000000000p+1");
  CHECK(py_float_hex(5e-324) == "0x0.0000000000001p-1022");
  CHECK(py_float_hex(1e300) == "0x1.7e43c8800759cp+996");
  CHECK(py_float_hex(0.0) == "0x0.0p+0");
  CHECK(py_float_hex(-0.0) == "-0x0.0p+0");

  CHECK(py_float_repr(1e16) == "1e+16");
  CHECK(py_float_repr(1e-5) == "1e-05");
  CHECK(py_float_repr(123456789.123) == "123456789.123");
  CHECK(py_float_repr(1e22) == "1e+22");
  CHECK(py_float_repr(0.0001) == "0.0001");
  CHECK(py_float_repr(100.0) == "100.0");
  CHECK(py_float_repr(-1.5) == "-1.5");
  CHECK(py_float_repr(1e15) == "1000000000000000.0");
  CHECK(py_float_repr(0.1) == "0.1");
  CHECK(py_float_repr(-0.0) == "-0.0");
  CHECK(py_float_repr(1.2345e-7) == "1.2345e-07");

  CHECK(py_str_repr("r") == "'r'");
  CHECK(py_str_repr("it's") == "\"it's\"");
  CHECK(py_str_repr("both ' and \"") == "'both \\' and \"'");
  CHECK(py_str_repr("line\nbreak\\") == "'line\\nbreak\\\\'");
}

TEST_CASE("default expression ids derive from the content, exactly as in Python") {
  CHECK(make_const(2)->expr_id() == "const_c51de2f6cbbc2a1e");
  CHECK(make_const(0.1)->expr_id() == "const_052cbc9733f977d9");
  CHECK(make_const(-0.0)->expr_id() == "const_47aaa25271a02431");
  CHECK(make_const(5e-324)->expr_id() == "const_1e0d155f40fd3228");
  CHECK(make_const(1e300)->expr_id() == "const_0f137f9258cc7bc7");

  const Sym r = make_var("r", 5.0, std::nullopt, std::nullopt, units::mm());
  CHECK(r.expr_id() == "var_1dfda245614375fc");
  CHECK((r * 2 + 1).expr_id() == "expr_d44ad8ebee707556");
  CHECK(make_var("r", 5.0)->expr_id() == "var_c8fbc9d12f568139");
  CHECK(make_var("r", 6.0)->expr_id() == "var_e7d1064daca3321c");
  CHECK(
      make_var("r", 5.0, "a 'quoted' comment \xC3\xA9", DimensionTolerance::symmetric(0.1), units::inch(), units::mm())
          ->expr_id() == "var_c771e1954f6b9230");
  CHECK(make_var("w", 1.5, "c", DimensionTolerance(-0.1, 0.2))->expr_id() == "var_b548982a6a604e86");
  CHECK(sin(make_var("a", 30.0, std::nullopt, std::nullopt, units::degree())).expr_id() == "expr_465b7e98c446938a");
  CHECK(make_var("q\\n\"x'", 1.0)->expr_id() == "var_26fc11039389b6b8");

  // Equal content, equal id; an explicit id wins.
  const Sym first = make_var("r", 5.0, std::nullopt, std::nullopt, units::mm()) * 2 + 1;
  const Sym second = make_var("r", 5.0, std::nullopt, std::nullopt, units::mm()) * 2 + 1;
  CHECK(first.expr_id() == second.expr_id());
  CHECK(make_var("r", 5.0)->expr_id() != make_var("r", 6.0)->expr_id());
  CHECK(Var::make({.name = "r", .default_value = 5.0, .expr_id = "radius"})->expr_id() == "radius");
}

TEST_CASE("repr is the Python dataclass text") {
  const auto r = make_var("r", 5.0, std::nullopt, DimensionTolerance::symmetric(0.1), units::mm());
  CHECK(r->repr() ==
        "Var(name='r', default=5.0, comment=None, expr_id='var_3daca82442ac80a1', "
        "tolerance=DimensionTolerance(lower_deviation=-0.1, upper_deviation=0.1), "
        "unit=Unit(symbol='mm', dimension=Dimension(length=1, angle=0), scale_to_canonical=1.0), "
        "tolerance_unit=Unit(symbol='mm', dimension=Dimension(length=1, angle=0), scale_to_canonical=1.0))");
  CHECK(make_const(2)->repr() == "Const(value=2.0, expr_id='const_c51de2f6cbbc2a1e')");
  const Sym e = Sym(make_var("r", 5.0, std::nullopt, std::nullopt, units::mm())) * 2 + 1;
  CHECK(e.node()->repr().rfind("Expr(op='add', args=(Expr(op='mul', args=(Var(name='r', default=5.0, comment=None",
                               0) == 0);
  CHECK(e.node()->repr().find("expr_id='expr_2ece69357ab4b237'), Const(value=1.0, expr_id='const_abdce65477d1247f')), "
                              "expr_id='expr_d44ad8ebee707556')") != std::string::npos);
}

TEST_CASE("var and expr roundtrip through the expression graph") {
  ExpressionGraph graph;
  const Sym r = make_var("r", 10.0);
  graph.register_expr(((r + 2) * 3).node());

  const Value payload = graph.to_value();
  const ExpressionGraph rebuilt = ExpressionGraph::from_value(payload);

  CHECK(graph.node_count() == rebuilt.node_count());
  CHECK(rebuilt.node_count() >= 4);
  CHECK(rebuilt.to_value() == payload);
  // Operands come before the nodes that use them.
  std::unordered_map<std::string, std::size_t> position;
  const auto& nodes = payload.find("nodes")->as_array();
  for (std::size_t i = 0; i < nodes.size(); ++i)
    position[nodes[i].find("expr_id")->as_string()] = i;
  for (std::size_t i = 0; i < nodes.size(); ++i) {
    if (const Value* args = nodes[i].find("args")) {
      for (const Value& arg : args->as_array())
        CHECK(position[arg.as_string()] < i);
    }
  }
}

TEST_CASE("expressions evaluate with defaults and with bindings") {
  const Sym r = make_var("r", 5.0);
  const Sym expr = r * 2 + 1;
  CHECK(expr.value() == doctest::Approx(11.0));
  const Bindings bound{{"r", 7.0}};
  CHECK(expr.value(&bound) == doctest::Approx(15.0));
  CHECK((-r).value() == -5.0);
  CHECK(abs(Sym(-3.0)).value() == 3.0);
  CHECK(pow(Sym(2.0), 10).value() == 1024.0);
  CHECK((10 - r).value() == 5.0);
  CHECK((10 / r).value() == 2.0);
  CHECK_THROWS_AS((Sym(1.0) / Sym(0.0)).value(), ValueError);
  CHECK_THROWS_AS(sqrt(Sym(-1.0)).value(), ValueError);
  CHECK_THROWS_AS(acos(Sym(2.0)).value(), ValueError);
  const Bindings bad{{"r", HUGE_VAL}};
  CHECK_THROWS_AS(r.value(&bad), ValueError);
  // A literal Scalar and a symbolic one go through the foundation's evaluate_scalar.
  CHECK(evaluate_scalar(expr.scalar(), "depth") == doctest::Approx(11.0));
  CHECK(evaluate_scalar(Scalar(3.5), "depth") == 3.5);
  const Scalar nan_expr = (r / r).scalar();
  CHECK(nan_expr.value() == 1.0);
}

TEST_CASE("ambient bindings reach Scalar::value") {
  const Sym r = make_var("r", 5.0);
  const Scalar s = (r + 1).scalar();
  CHECK(s.value() == 6.0);
  const Bindings edited{{"r", 9.0}};
  {
    AmbientBindingsScope scope(&edited);
    CHECK(s.value() == 10.0);
    CHECK(evaluate_scalar(s, "r") == 10.0);
    const Bindings inner{{"r", 1.0}};
    AmbientBindingsScope nested(&inner);
    CHECK(s.value() == 2.0);
    CHECK(s.value(&edited) == 10.0);  // an explicit argument wins
  }
  CHECK(s.value() == 6.0);
}

TEST_CASE("expression construction validates") {
  CHECK_THROWS_AS(Expr::make("nope", {make_const(1)}), ValueError);
  CHECK_THROWS_AS(Expr::make("add", {make_const(1)}), ValueError);
  CHECK_THROWS_AS(Const::make(HUGE_VAL), ValueError);
  CHECK_THROWS_AS(make_const(std::nan("")), ValueError);
  CHECK_THROWS_AS(DimensionTolerance(0.5, 1.0), ValueError);
  CHECK_THROWS_AS(DimensionTolerance(-1.0, -0.5), ValueError);
  CHECK_THROWS_AS(DimensionTolerance::symmetric(-1.0), ValueError);
  CHECK(DimensionTolerance::symmetric(0.25).width() == 0.5);
}

TEST_CASE("structural equality follows the dataclass ==") {
  const Sym a = make_var("r", 5.0) * 2;
  const Sym b = make_var("r", 5.0) * 2;
  const Sym c = make_var("r", 6.0) * 2;
  CHECK(same_expression(*a.node(), *b.node()));
  CHECK_FALSE(same_expression(*a.node(), *c.node()));
}

TEST_CASE("referenced variables are listed once, in first-use order") {
  const auto w = make_var("w", 2.0);
  const auto d = make_var("d", 3.0);
  const Sym expr = (Sym(w) + Sym(d)) * Sym(w);
  const auto vars = referenced_vars(expr.node());
  REQUIRE(vars.size() == 2);
  CHECK(vars[0]->name() == "w");
  CHECK(vars[1]->name() == "d");
  CHECK(referenced_vars(Scalar(2.0)).empty());
}

// ---------------------------------------------------------------------------
// canonicalize_params / referenced_expressions
// ---------------------------------------------------------------------------

TEST_CASE("canonicalization does not promote discrete index lists") {
  ExpressionGraph graph;
  Value params = Value::object();
  Value indices = Value::array();
  for (int i = 0; i < 3; ++i)
    indices.push_back(i);
  params.set("selected_edge_indices", indices);
  params.set("distance", 2.0);
  params.set("count", 4);
  params.set("size", 7);
  const SymbolicParams symbolic{{"distance", Scalar(ExprPtr(make_var("d", 2.0)))}};

  const CanonicalParams out = canonicalize_params(params, symbolic, graph);

  CHECK(out.numeric.find("selected_edge_indices")->as_array()[0].is_int());
  CHECK(out.numeric.find("count")->is_int());
  CHECK(out.numeric.find("size")->is_double());  // an ordinary integer becomes a float
  CHECK(out.exprs.find("distance") != nullptr);
  CHECK(out.exprs.find("selected_edge_indices") == nullptr);
  CHECK(graph.node_count() == 1);
}

TEST_CASE("referenced expressions walk nested params in order") {
  ExpressionGraph graph;
  const Sym doubled = make_var("w", 2.0) * 2;
  const Sym depth = make_var("d", 3.0);
  Value params = Value::object();
  Value size = Value::array();
  size.push_back(4.0);
  size.push_back(1.0);
  params.set("size", size);
  params.set("depth", 3.0);
  Value again = Value::object();
  again.set("x", 4.0);
  params.set("again", again);
  const SymbolicParams symbolic{
      {"size[0]", doubled.scalar()}, {"depth", depth.scalar()}, {"again.x", doubled.scalar()}};

  const CanonicalParams out = canonicalize_params(params, symbolic, graph);
  const auto found = referenced_expressions(out.exprs, graph);

  REQUIRE(found.size() == 2);
  CHECK(found[0]->expr_id() == doubled.expr_id());
  CHECK(found[1]->expr_id() == depth.expr_id());
  // The list keeps a null where no expression sits.
  CHECK(out.exprs.find("size")->as_array()[1].is_null());
  Value missing = Value::object();
  Value ref = Value::object();
  ref.set("expr_id", "missing");
  missing.set("x", ref);
  CHECK_THROWS_AS(referenced_expressions(missing, graph), KeyError);
}

TEST_CASE("a symbolic position missing from the params is written with its value") {
  ExpressionGraph graph;
  const CanonicalParams out =
      canonicalize_params(Value::object(), {{"radius", Sym(make_var("r", 4.0)).scalar()}}, graph);
  CHECK(out.numeric.find("radius")->as_double() == 4.0);
}

TEST_CASE("param paths parse, find and set") {
  const ParamPath path = ParamPath::parse("points[2][0]");
  CHECK(path.key == "points");
  CHECK(path.steps.size() == 2);
  CHECK(path.str() == "points[2][0]");
  CHECK(ParamPath::parse("center.x").str() == "center.x");
  CHECK_THROWS_AS(ParamPath::parse(""), ValueError);
  CHECK_THROWS_AS(ParamPath::parse("[1]"), ValueError);
  CHECK_THROWS_AS(ParamPath::parse("a[x]"), ValueError);
  CHECK_THROWS_AS(ParamPath::parse("a."), ValueError);

  Value params = Value::object();
  set_param(params, path, Value(1.5));
  CHECK(find_param(params, path)->as_double() == 1.5);
  CHECK(find_param(params, ParamPath::parse("points[0]")) != nullptr);
  CHECK(find_param(params, ParamPath::parse("points[0]"))->is_null());
  CHECK(find_param(params, ParamPath::parse("points[3]")) == nullptr);
  CHECK(find_param(params, ParamPath::parse("other")) == nullptr);
  CHECK_THROWS_AS(set_param(params, ParamPath::parse("points.x"), Value(1.0)), ValueError);
}
