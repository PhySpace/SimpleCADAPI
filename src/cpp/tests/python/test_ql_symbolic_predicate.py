"""A symbolic value (an Expr from scad.var arithmetic) in a ql predicate is evaluated, not compared as an object.

2.2.6.post2 matches nothing here (see docs/DEVIATIONS.md): this is a recorded deviation, in the permissive direction.
"""

from __future__ import annotations

import math

import simplecadapi as scad
from simplecadapi import ql


def test_a_var_expression_in_a_predicate_matches_like_the_float() -> None:
    radius = scad.var(name="plate_radius", default=50.0, unit="mm")
    solid = scad.make_cylinder_rsolid(float(radius), 10)

    def rims(length) -> int:
        selector = ql.edges().where(
            ql.and_(ql.prop("geom.length", ">=", length * 0.999), ql.prop("geom.length", "<=", length * 1.001))
        )
        return len(ql.select(selector.resolve(solid)).all())

    assert rims(2 * math.pi * 50.0) == 2
    assert rims(2 * math.pi * radius) == 2
    assert rims(2 * math.pi * float(radius)) == 2
