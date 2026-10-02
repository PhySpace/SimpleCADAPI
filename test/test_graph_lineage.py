"""Graph-layer support for cell-level caching.

Covers the pieces the notebook runtime builds on: node pickling and
deep-copying, namespaced ids, adopting lineage produced by another cell's
session, and the expression/frame/tolerance data a node or requirement
carries so a product can be projected into a fresh session.
"""

from __future__ import annotations

import copy
import pickle
import unittest
from dataclasses import replace

import simplecadapi as scad
from simplecadapi.params.expr import (
    ExpressionGraph,
    canonicalize_params,
    referenced_expressions,
)
from simplecadapi.params.frame import FrameGraph, FrameNode
from simplecadapi.params.tolerance import ToleranceRequirement
from simplecadapi.recording.graph import GraphSession
from simplecadapi.topology.model import (
    OperationGraph,
    StaleLineageError,
    same_node_content,
    upstream_closure,
)


def _chain(graph: OperationGraph, length: int):
    node = graph.add_node("root", {"x": 0.0})
    for index in range(length):
        node = graph.add_node("step", {"i": index}, inputs=[node])
    return node


def _diamonds(graph: OperationGraph, depth: int):
    """Stack *depth* diamonds; the closure is linear but has 2**depth paths."""

    node = graph.add_node("root")
    for index in range(depth):
        left = graph.add_node("left", {"i": index}, inputs=[node])
        right = graph.add_node("right", {"i": index}, inputs=[node])
        node = graph.add_node("join", {"i": index}, inputs=[left, right])
    return node


class TestUpstreamClosure(unittest.TestCase):
    def test_postorder_visits_shared_inputs_once(self):
        graph = OperationGraph("g")
        top = _diamonds(graph, 3)

        closure = upstream_closure((top,))

        self.assertEqual(len(closure), 10)
        self.assertEqual(len({node.node_id for node in closure}), 10)
        self.assertIs(closure[-1], top)
        position = {node.node_id: index for index, node in enumerate(closure)}
        for node in closure:
            for item in node.inputs:
                self.assertLess(position[item.node_id], position[node.node_id])

    def test_two_versions_of_one_node_raise_stale_lineage(self):
        graph = OperationGraph("g")
        base = graph.add_node("root", {"x": 1.0})
        stale = replace(base, params={"x": 2.0})
        join = graph.add_node("join", inputs=[base])
        other = replace(join, node_id="other", inputs=(stale,))

        with self.assertRaises(StaleLineageError) as caught:
            upstream_closure((join, other))
        self.assertEqual(caught.exception.node_id, base.node_id)


class TestNodePickle(unittest.TestCase):
    def test_deep_chain_round_trips_without_recursion(self):
        graph = OperationGraph("g")
        tip = _chain(graph, 5000)

        restored = pickle.loads(pickle.dumps(tip))

        closure = upstream_closure((restored,))
        self.assertEqual(len(closure), 5001)
        self.assertTrue(same_node_content(restored, tip))
        self.assertEqual(closure[0].params, {"x": 0.0})

    def test_diamond_keeps_shared_inputs_shared(self):
        graph = OperationGraph("g")
        top = _diamonds(graph, 60)

        restored = pickle.loads(pickle.dumps(top))

        left, right = restored.inputs
        self.assertIs(left.inputs[0], right.inputs[0])
        self.assertEqual(len(upstream_closure((restored,))), 181)

    def test_separately_pickled_values_restore_to_shared_nodes(self):
        # Two cells pickle their outputs independently; loading both must
        # give one object for the lineage they have in common.
        graph = OperationGraph("g")
        base = graph.add_node("root")
        first = graph.add_node("a", inputs=[base])
        second = graph.add_node("b", inputs=[base])

        first_back = pickle.loads(pickle.dumps(first))
        second_back = pickle.loads(pickle.dumps(second))

        self.assertIs(first_back.inputs[0], second_back.inputs[0])
        self.assertIs(pickle.loads(pickle.dumps(first)), first_back)

    def test_changed_input_does_not_reuse_stale_downstream_node(self):
        graph = OperationGraph("changed")
        base = graph.add_node("root", {"x": 1.0})
        tip = graph.add_node("step", inputs=[base])
        old_tip = pickle.loads(pickle.dumps(tip))

        # A re-run changed the root but reproduced the step verbatim.
        new_base = replace(base, params={"x": 2.0})
        new_tip = pickle.loads(pickle.dumps(replace(tip, inputs=(new_base,))))

        self.assertIsNot(new_tip, old_tip)
        self.assertEqual(new_tip.inputs[0].params, {"x": 2.0})

    def test_restored_node_keeps_expressions_and_frame(self):
        width = scad.var("w", 20.0)
        with GraphSession("nb", namespace="ca"):
            box = scad.make_box_rsolid(width, 10.0, 5.0)

        node = pickle.loads(pickle.dumps(box))._get_runtime("graph.node")

        self.assertIn(width.expr_id, [expr.expr_id for expr in node.expressions])
        self.assertIsNotNone(node.frame)
        self.assertEqual(node.frame.frame_id, f"frame:{node.node_id}")


class TestNodeDeepCopy(unittest.TestCase):
    def test_copy_is_new_objects_with_same_sharing(self):
        graph = OperationGraph("g")
        top = _diamonds(graph, 60)

        copied = copy.deepcopy(top)

        self.assertIsNot(copied, top)
        self.assertTrue(same_node_content(copied, top))
        left, right = copied.inputs
        self.assertIsNot(left, top.inputs[0])
        self.assertIs(left.inputs[0], right.inputs[0])
        copied.params["i"] = -1
        self.assertEqual(top.params["i"], 59)

    def test_graph_copy_points_edges_at_copied_nodes(self):
        graph = OperationGraph("g")
        top = _diamonds(graph, 4)

        copied = copy.deepcopy(graph)

        node = copied.get_node(top.node_id)
        assert node is not None
        self.assertIsNot(node, top)
        self.assertIs(node.inputs[0], copied.get_node(top.inputs[0].node_id))


class TestNamespaceAndAdopt(unittest.TestCase):
    def test_namespace_prefixes_node_and_object_ids(self):
        graph = OperationGraph("g", namespace="c1234abcd")
        self.assertEqual(graph.add_node("root").node_id, "c1234abcd_node_00000001")

        session = GraphSession("nb", namespace="c1234abcd")
        self.assertEqual(
            session.allocate_object_id("sketch"), "c1234abcd_sketch_00000001"
        )
        with self.assertRaises(ValueError):
            OperationGraph("g", namespace="")

    def test_adopt_inserts_closure_and_reuses_equal_nodes(self):
        source = OperationGraph("g", namespace="ca")
        tip = _chain(source, 10)
        restored = pickle.loads(pickle.dumps(tip))

        target = OperationGraph("g", namespace="cb")
        self.assertIs(target.adopt(restored), restored)
        self.assertEqual(target.node_count, 11)
        self.assertTrue(target.is_dag())

        # A shallow-equal copy of an owned node resolves to the owned one.
        self.assertIs(target.adopt(replace(restored)), restored)
        self.assertEqual(target.node_count, 11)

    def test_adopt_rejects_changed_node_and_foreign_graph(self):
        source = OperationGraph("g")
        tip = _chain(source, 3)
        target = OperationGraph("g")
        target.adopt(tip)

        with self.assertRaises(StaleLineageError):
            target.adopt(replace(tip, params={"i": -1}))
        with self.assertRaises(ValueError):
            OperationGraph("other").adopt(tip)

    def test_shared_lineage_session_builds_on_another_cells_value(self):
        with GraphSession("nb", namespace="ca", shared_lineage=True):
            box = scad.make_box_rsolid(20.0, 10.0, 5.0)
        restored = pickle.loads(pickle.dumps(box))

        with GraphSession("nb", namespace="cb", shared_lineage=True) as session:
            scad.cut_rsolid(restored, scad.make_cylinder_rsolid(2.0, 10.0))

        node_ids = [node.node_id for node in session.graph.topological_order()]
        self.assertIn(restored._get_runtime("graph.node").node_id, node_ids)
        self.assertEqual(sum(item.startswith("cb_") for item in node_ids), 2)

    def test_strict_session_rejects_another_cells_value(self):
        with GraphSession("nb", namespace="ca", shared_lineage=True):
            box = scad.make_box_rsolid(20.0, 10.0, 5.0)

        with self.assertRaises(Exception):
            with GraphSession("nb"):
                scad.cut_rsolid(box, scad.make_cylinder_rsolid(2.0, 10.0))


class TestExpressionFrameAndTolerance(unittest.TestCase):
    def test_referenced_expressions_walk_nested_params_in_order(self):
        graph = ExpressionGraph()
        doubled = scad.var("w", 2.0) * 2
        depth = scad.var("d", 3.0)
        _, param_exprs = canonicalize_params(
            {"size": [doubled, 1.0], "depth": depth, "again": {"x": doubled}},
            graph,
        )

        found = referenced_expressions(param_exprs, graph)

        self.assertEqual(
            [expr.expr_id for expr in found], [doubled.expr_id, depth.expr_id]
        )
        with self.assertRaises(KeyError):
            referenced_expressions({"x": {"expr_id": "missing"}}, graph)

    def test_frame_graph_add_replaces_by_id(self):
        graph = FrameGraph()
        axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        first = FrameNode("f", (0.0, 0.0, 0.0), *axes)
        second = FrameNode("f", (1.0, 0.0, 0.0), *axes)

        self.assertIs(graph.add(first), first)
        graph.add(second)

        self.assertEqual(graph.node_count, 1)
        self.assertEqual(graph.to_dict()["nodes"][0]["origin"], (1.0, 0.0, 0.0))

    def test_requirement_keeps_target_and_gets_namespaced_default_id(self):
        width = scad.var("width", 10.0, tolerance=(-0.1, 0.2))
        with GraphSession("nb", namespace="ca") as session:
            requirement = session.require_tolerance(width * 2.0, (-0.2, 0.4))

        self.assertTrue(requirement.requirement_id.startswith("ca_tolreq_"))
        assert requirement.target is not None
        self.assertEqual(requirement.target.expr_id, requirement.target_expr_id)
        # The target is carried alongside the payload, not inside it.
        self.assertEqual(requirement, replace(requirement, target=None))

        with self.assertRaises(ValueError):
            ToleranceRequirement(
                requirement_id="r",
                target_expr_id="not-the-target",
                tolerance=requirement.tolerance,
                name="r",
                target=requirement.target,
            )


if __name__ == "__main__":
    unittest.main()
