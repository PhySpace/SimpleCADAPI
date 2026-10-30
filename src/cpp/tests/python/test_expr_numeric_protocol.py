"""A Var or an Expr behaves like a number wherever Python asks for one (the numeric protocol).

The matrix runs each usage with a plain number and with a Var / Expr of the same value and asserts the same answer:
comparisons, int(), round(), range(), indexing, formatting, max/min/sorted, numpy scalars as operands.  Arithmetic stays symbolic (an Expr
that keeps the link to the parameters); decisions read the value the expression has now.  Recorded exceptions: bool()
stays an error (2.2.6 pins it), json.dumps cannot take a Var (loud, not silent), and there is no __array__ (the last test).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import simplecadapi as scad

X = 5.0
N = 3


def operands():
    var = scad.var(name="r", default=X, unit="mm")
    count = scad.var(name="n", default=N, unit="1")
    return {
        "number": (X, N),
        "var": (var, count),
        "expr": (var * 1.0, count * 1),  # the value of a computed expression
    }


# (label, usage(x, n)) -- the answer must be the same for a number, a Var and an Expr
CASES = [
    ("int", lambda x, n: int(x)),
    ("round", lambda x, n: round(x)),
    ("round digits", lambda x, n: round(x / 3, 2)),
    ("floor", lambda x, n: math.floor(x / 3)),
    ("ceil", lambda x, n: math.ceil(x / 3)),
    ("trunc", lambda x, n: math.trunc(x / 3)),
    ("floordiv", lambda x, n: float(x // 2)),
    ("rfloordiv", lambda x, n: float(17 // x)),
    ("mod", lambda x, n: float(x % 3)),
    ("rmod", lambda x, n: float(17 % x)),
    ("lt", lambda x, n: x < 6),
    ("le", lambda x, n: x <= 5),
    ("gt", lambda x, n: x > 4),
    ("ge", lambda x, n: x >= 6),
    ("eq number", lambda x, n: x == 5.0),
    ("ne number", lambda x, n: x != 5.0),
    ("in list", lambda x, n: x in [1.0, 5.0]),
    ("max", lambda x, n: float(max(x, 3))),
    ("min", lambda x, n: float(min(x, 3))),
    ("sorted", lambda x, n: [float(v) for v in sorted([x, 2, 9.5])]),
    ("range", lambda x, n: list(range(n))),
    ("repeat list", lambda x, n: len([0] * n)),
    ("repeat string", lambda x, n: "ab" * n),
    ("index", lambda x, n: [10, 20, 30, 40][n - 1]),
    ("slice", lambda x, n: [10, 20, 30, 40][:n]),
    ("f-string", lambda x, n: f"{x}"),
    ("f-string spec", lambda x, n: f"{x:.2f}"),
    ("format", lambda x, n: format(x, "08.3f")),
    ("str", lambda x, n: str(x)),
    ("percent", lambda x, n: "%.1f" % x),
    ("math", lambda x, n: math.sqrt(x)),
    ("sum", lambda x, n: float(sum([x, x, 1]))),
    ("numpy scalar operand", lambda x, n: float(x * np.float64(2.0))),
    ("numpy int operand", lambda x, n: float(x * np.int64(3))),
    ("compare numpy", lambda x, n: bool(x < np.float64(6.0))),
]


@pytest.mark.parametrize("label,usage", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("kind", ["var", "expr"])
def test_a_var_or_expr_answers_like_the_number(kind, label, usage):
    ops = operands()
    expected = usage(*ops["number"])
    got = usage(*ops[kind])
    assert got == expected and type(got) is type(expected)


def test_arithmetic_keeps_the_formula():
    ops = operands()
    x, _ = ops["var"]
    area = math.pi * x * x
    assert type(area).__name__ == "Expr" and float(area) == pytest.approx(math.pi * 25.0)
    assert float(x * np.int64(3)) == 15.0 and type(x * np.int64(3)).__name__ == "Expr"


def test_two_expressions_compare_by_formula_and_a_number_by_value():
    r = scad.var(name="r", default=5.0, unit="mm")
    other_r = scad.var(name="r", default=5.0, unit="mm")
    assert (r * 2 + 1) == (other_r * 2 + 1)  # the same formula
    assert (r * 2) != (r * 3)
    assert r == 5.0 and r != 6.0 and (r * 2) == 10.0
    assert not (r == True)  # noqa: E712  (a bool is not a number here, as in arithmetic)


def test_a_count_must_be_a_whole_number():
    half = scad.var(name="half", default=2.5, unit="1")
    with pytest.raises(TypeError, match="not a whole number"):
        range(half)
    with pytest.raises(TypeError, match="not a whole number"):
        [0] * half


def test_the_recorded_exceptions_stay_loud():
    r = scad.var(name="r", default=5.0, unit="mm")
    with pytest.raises(TypeError, match="truthiness"):
        bool(r)  # 2.2.6 pins this (an old test); compare explicitly instead
    with pytest.raises(TypeError, match="Unsupported scalar expression value"):
        r + "a"
    with pytest.raises(TypeError, match="Boolean values"):
        r + True
    with pytest.raises(TypeError):  # never a silent wrong answer
        __import__("json").dumps(r)


def test_operators_still_take_the_expression_and_keep_the_link():
    r = scad.var(name="r", default=5.0, unit="mm")
    solid = scad.make_cylinder_rsolid(r, 10)
    assert solid.get_volume() == pytest.approx(math.pi * 25.0 * 10.0, rel=1e-9)


def test_a_var_has_no_array_protocol_because_the_cell_cache_would_key_it_by_value_alone():
    """marimo hashes an object with __array__ as a numpy array: by value.  A Var must stay keyed by its declaration."""
    r = scad.var(name="r", default=5.0, unit="mm")
    assert not hasattr(r, "__array__")
    assert float(np.sqrt(float(r))) == pytest.approx(math.sqrt(5.0))  # numpy takes float(r)
