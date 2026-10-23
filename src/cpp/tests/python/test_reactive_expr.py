"""Expressions through the Python module: ports of test_expr_graph.py and the
expression parts of test_units.py / test_graph_lineage.py, with the ids, reprs
and payloads held against the reference SDK."""

import math

import pytest

import simplecadapi._cpp as scad
from ref import golden

EXPRESSIONS = [
    "scad.const(2)",
    "scad.const(0.1)",
    "scad.const(-0.0)",
    "scad.var('r', 5.0)",
    "scad.var('r', 5.0, unit='mm')",
    "scad.var('r', 5.0, 'a \\'quoted\\' comment', 0.1, unit='in', tolerance_unit='mm')",
    "scad.var('w', 1.5, comment='c', tolerance=(-0.1, 0.2))",
    "scad.var('r', 5.0, unit='mm') * 2 + 1",
    "scad.sin(scad.var('a', 30.0, unit='deg'))",
    "scad.sqrt(scad.var('x', 4.0)) ** 2",
    "-scad.var('x', 1.0)",
    "abs(scad.var('x', -1.0))",
    "2 - scad.var('x', 1.0)",
    "10 / scad.var('x', 4.0)",
    "2 ** scad.var('x', 3.0)",
    "scad.atan2(scad.var('y', 1.0), scad.var('x', 1.0))",
    "scad.acos(scad.var('p', 50.0, unit='%'))",
]


def build(source):
    return eval(source, {"scad": scad})


def test_ids_reprs_and_values_match_the_reference():
    expected = golden(
        "reactive_expressions",
        f"""
        sources = {EXPRESSIONS!r}
        result = {{}}
        for source in sources:
            node = eval(source, {{"scad": scad}})
            result[source] = {{"id": node.expr_id, "repr": repr(node), "value": float(node)}}
        """,
    )
    for source in EXPRESSIONS:
        node = build(source)
        assert node.expr_id == expected[source]["id"], source
        assert repr(node) == expected[source]["repr"], source
        assert float(node) == pytest.approx(expected[source]["value"]), source


def test_expression_graph_payload_matches_the_reference():
    expected = golden(
        "reactive_expression_graph",
        f"""
        graph = scad.ExpressionGraph()
        for source in {EXPRESSIONS!r}:
            graph.register(eval(source, {{"scad": scad}}))
        result = graph.to_dict()
        """,
    )
    graph = scad.ExpressionGraph()
    for source in EXPRESSIONS:
        graph.register(build(source))
    assert graph.to_dict() == expected
    rebuilt = scad.ExpressionGraph.from_dict(graph.to_dict())
    assert rebuilt.to_dict() == expected


def test_var_and_expr_roundtrip():
    graph = scad.ExpressionGraph()
    r = scad.var("r", 10.0)
    graph.register((r + 2) * 3)
    rebuilt = scad.ExpressionGraph.from_dict(graph.to_dict())
    assert graph.node_count == rebuilt.node_count
    assert rebuilt.node_count >= 4


def test_expr_evaluates_with_defaults_and_bindings():
    r = scad.var("r", 5.0)
    expr = r * 2 + 1
    assert float(expr) == pytest.approx(11.0)
    assert expr.evaluate({"r": 7}) == pytest.approx(15.0)
    assert scad.evaluate_scalar(expr, {"r": 1.0}) == pytest.approx(3.0)
    assert scad.evaluate_scalar(4) == 4.0
    assert scad.evaluate_value({"a": (r, [expr, 2]), "b": "text"}, {"r": 0.0}) == {"a": (0.0, [1.0, 2.0]), "b": "text"}
    with pytest.raises(ValueError):
        expr.evaluate({"r": math.inf})
    with pytest.raises(TypeError):
        expr.evaluate({"r": True})


def test_every_operator_has_a_reflected_form():
    x = scad.var("x", 4.0)
    assert float(1 + x) == 5.0 and float(x + 1) == 5.0
    assert float(10 - x) == 6.0 and float(x - 1) == 3.0
    assert float(3 * x) == 12.0 and float(x * 3) == 12.0
    assert float(8 / x) == 2.0 and float(x / 8) == 0.5
    assert float(2**x) == 16.0 and float(x**0.5) == 2.0
    assert float(-x) == -4.0 and float(abs(-x)) == 4.0
    assert float(scad.sqrt(x)) == 2.0
    assert float(scad.atan2(x, x)) == pytest.approx(math.pi / 4)
    assert isinstance((x + 1).args[0], scad.Var)
    assert (x + 1).op == "add"


def test_expressions_have_no_truthiness_and_reject_unsupported_operands():
    x = scad.var("x", 1.0)
    with pytest.raises(TypeError, match="truthiness"):
        bool(x)
    with pytest.raises(TypeError, match="Unsupported scalar expression value"):
        x + "a"
    with pytest.raises(TypeError, match="Boolean values"):
        x + True
    with pytest.raises(TypeError):
        scad.const(True)
    with pytest.raises(ValueError):
        scad.const(math.nan)


def test_equality_and_hash_follow_the_dataclass():
    a = scad.var("r", 5.0, unit="mm") * 2 + 1
    b = scad.var("r", 5.0, unit="mm") * 2 + 1
    c = scad.var("r", 6.0, unit="mm") * 2 + 1
    assert a == b and hash(a) == hash(b)
    assert a != c
    assert {a: 1}[b] == 1


def test_default_expression_ids_derive_from_content():
    first = scad.var("r", 5.0, unit="mm") * 2 + 1
    second = scad.var("r", 5.0, unit="mm") * 2 + 1
    assert first.expr_id == second.expr_id
    assert scad.var("r", 5.0).expr_id != scad.var("r", 6.0).expr_id
    assert scad.Var("r", 5.0, expr_id="radius").expr_id == "radius"


def test_var_validation_messages():
    with pytest.raises(ValueError, match="non-empty string"):
        scad.var("", 1.0)
    with pytest.raises(ValueError, match="comment must be a string"):
        scad.var("x", 1.0, comment=3)
    with pytest.raises(ValueError, match="Variable default must be finite"):
        scad.var("x", math.inf)
    with pytest.raises(TypeError, match="real number"):
        scad.var("x", "1")
    with pytest.raises(TypeError, match="two-value sequence"):
        scad.var("x", 1.0, tolerance="a")
    with pytest.raises(ValueError, match="exactly two"):
        scad.var("x", 1.0, tolerance=(1, 2, 3))
    with pytest.raises(ValueError, match="less than or equal to zero"):
        scad.var("x", 1.0, tolerance=(0.5, 1.0))
    assert scad.var("x", 1, tolerance=0.25).tolerance == scad.DimensionTolerance(-0.25, 0.25)
    assert scad.var("x", 1.0, tolerance=scad.DimensionTolerance.symmetric(1)).tolerance.width == 2.0


def test_var_replace_keeps_unit_comment_and_derives_a_new_default():
    var = scad.var("od", 100.0, comment="outer", unit="mm")
    changed = var.with_default(120)
    assert (changed.default, changed.name, changed.unit, changed.comment) == (120.0, "od", var.unit, "outer")
    assert changed.expr_id != var.expr_id
    kept = var.replace(default=50.0)
    assert kept.default == 50.0 and kept.expr_id == var.expr_id  # dataclasses.replace keeps the id
    with pytest.raises(TypeError):
        var.replace(bogus=1)


def test_expression_canonicalization_does_not_promote_discrete_index_lists():
    graph = scad.ExpressionGraph()
    params, param_exprs = scad.canonicalize_params(
        {"selected_edge_indices": [0, 1, 2], "distance": scad.var("d", 2.0)}, graph
    )
    assert params["selected_edge_indices"] == [0, 1, 2]
    assert all(isinstance(v, int) for v in params["selected_edge_indices"])
    assert "distance" in param_exprs


def test_canonicalize_params_keeps_structure_like_the_reference():
    params_source = (
        "{'size': [doubled, 1], 'pair': (depth, 2.0), 'again': {'x': doubled, 'y': 3}, 'name': 'n', 'flag': True, 'count': 3}"
    )
    namespace_source = "doubled = scad.var('w', 2.0) * 2\ndepth = scad.var('d', 3.0)\n"
    expected = golden(
        "reactive_canonicalize",
        f"""
        exec({namespace_source!r}, globals())
        graph = scad.ExpressionGraph()
        from simplecadapi.params.expr import canonicalize_params, referenced_expressions
        numeric, exprs = canonicalize_params({params_source}, graph)
        found = referenced_expressions(exprs, graph)
        result = {{"numeric": numeric, "exprs": exprs, "found": [e.expr_id for e in found],
                   "kinds": {{"size": type(numeric["size"]).__name__, "pair": type(numeric["pair"]).__name__}}}}
        """,
    )
    scope = {"scad": scad}
    exec(namespace_source, scope)
    graph = scad.ExpressionGraph()
    numeric, exprs = scad.canonicalize_params(eval(params_source, scope), graph)
    found = scad.referenced_expressions(exprs, graph)
    assert [e.expr_id for e in found] == expected["found"]
    assert exprs == expected["exprs"]
    assert numeric["size"] == expected["numeric"]["size"] and numeric["again"] == expected["numeric"]["again"]
    assert list(numeric["pair"]) == expected["numeric"]["pair"]
    assert type(numeric["size"]).__name__ == expected["kinds"]["size"]
    assert type(numeric["pair"]).__name__ == expected["kinds"]["pair"]
    assert numeric["name"] == "n" and numeric["flag"] is True and numeric["count"] == 3

    with pytest.raises(KeyError):
        scad.referenced_expressions({"x": {"expr_id": "missing"}}, graph)


def test_expression_graph_register_is_atomic_and_rejects_id_clashes():
    length = scad.Var("length", 1.0, expr_id="same", unit=scad.MM)
    angle = scad.Var("angle", 1.0, expr_id="same", unit=scad.DEGREE)
    expression = scad.Expr("add", (length, angle))
    graph = scad.ExpressionGraph()
    with pytest.raises(scad.UnitValidationError):
        scad.infer_dimension(expression)
    with pytest.raises(ValueError, match="different node"):
        graph.register(expression)
    assert graph.node_count == 0


def test_expression_graph_from_dict_validates():
    for payload in ({"nodes": 3}, {"nodes": [3]}, {"nodes": [{"kind": "const", "value": 1}]},
                    {"nodes": [{"expr_id": "a", "kind": "wat"}]},
                    {"nodes": [{"expr_id": "a", "kind": "expr", "op": "add", "args": ["b", "b"]}]}):
        with pytest.raises((TypeError, ValueError)):
            scad.ExpressionGraph.from_dict(payload)
    assert scad.ExpressionGraph.from_dict({}).node_count == 0
    with pytest.raises(TypeError):
        scad.ExpressionGraph.from_dict(None)


def test_expressions_pass_through_the_scalar_caster():
    if not hasattr(scad, "make_sketch_rsketch"):
        pytest.skip("needs an operator that takes a Scalar (the sketch area)")
    w = scad.var("w", 3.0)
    sketch = scad.make_sketch_rsketch("s")
    sketch = scad.add_point_rsketch(sketch, "p0", w * 2, 0.0)  # an operator that takes a Scalar
    assert "p0" in sketch.entities
    assert isinstance(scad.ExprBase, type) and issubclass(scad.Var, scad.ExprBase)
