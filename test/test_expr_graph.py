"""Focused tests for the 2.0 expression graph layer."""

from __future__ import annotations

import unittest

import simplecadapi as scad


class TestExpressionGraph(unittest.TestCase):
    def test_var_and_expr_roundtrip(self):
        graph = scad.ExpressionGraph()
        r = scad.var("r", 10.0)
        expr = (r + 2) * 3
        graph.register(expr)

        payload = graph.to_dict()
        rebuilt = scad.ExpressionGraph.from_dict(payload)

        self.assertEqual(graph.node_count, rebuilt.node_count)
        self.assertGreaterEqual(rebuilt.node_count, 4)

    def test_expr_evaluates_with_defaults(self):
        r = scad.var("r", 5.0)
        expr = r * 2 + 1
        self.assertAlmostEqual(float(expr), 11.0)

    def test_expression_canonicalization_does_not_promote_discrete_index_lists(self):
        from simplecadapi.params.expr import ExpressionGraph, canonicalize_params

        graph = ExpressionGraph()
        params, param_exprs = canonicalize_params(
            {
                "selected_edge_indices": [0, 1, 2],
                "distance": scad.var("d", 2.0),
            },
            graph,
        )

        self.assertEqual(params["selected_edge_indices"], [0, 1, 2])
        self.assertTrue(
            all(isinstance(v, int) for v in params["selected_edge_indices"])
        )
        self.assertIn("distance", param_exprs)

    def test_default_expression_ids_derive_from_content(self):
        # Equal expressions get equal ids, so a content hash is reproducible
        # across processes; a different value or comment is a different node.
        first = scad.var("r", 5.0, unit="mm") * 2 + 1
        second = scad.var("r", 5.0, unit="mm") * 2 + 1
        self.assertEqual(first.expr_id, second.expr_id)
        self.assertNotEqual(
            scad.var("r", 5.0).expr_id, scad.var("r", 6.0).expr_id
        )
        from simplecadapi.params.expr import Var

        self.assertEqual(Var("r", 5.0, expr_id="radius").expr_id, "radius")


if __name__ == "__main__":
    unittest.main()
