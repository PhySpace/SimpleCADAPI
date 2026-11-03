"""Tests for Phase 5 (QL sugar) and Phase 6 (DAG session recorder)."""

import unittest

import simplecadapi as scad
from simplecadapi import ql as Q
from simplecadapi.topology import OperationGraph, OperationNode
from simplecadapi.recording.graph import GraphSession, record_operation, get_active_session
from simplecadapi.topology.tracking import tracked_cut, tracked_union
from simplecadapi.topology.autotag import apply_tracking_tags_to_delta


class TestQLSugar(unittest.TestCase):
    """Test QL sugar helpers for tracking-based queries."""

    def test_op_predicate(self):
        pred = Q.op("cut", "generated")
        obj = type(
            "Obj",
            (),
            {"_metadata": {"track": {"op": "make_cut_rsolid", "event": "generated"}}},
        )()
        self.assertTrue(pred(obj))

    def test_op_predicate_wildcard(self):
        pred = Q.op("cut")
        obj = type(
            "Obj",
            (),
            {"_metadata": {"track": {"op": "make_cut_rsolid", "events": ["modified"]}}},
        )()
        self.assertTrue(pred(obj))

    def test_op_predicate_matches_generic_operation_alias(self):
        obj = type(
            "Obj",
            (),
            {
                "_metadata": {
                    "track": {
                        "op": "make_translate_rsolid",
                        "operation": "translate",
                        "event": "modified",
                    }
                }
            },
        )()

        self.assertTrue(Q.op("translate", "modified")(obj))
        self.assertTrue(Q.op("make_translate_rsolid", "modified")(obj))

    def test_origin_predicate(self):
        pred = Q.origin("tool")
        obj = type(
            "Obj", (), {"_metadata": {"track": {"origin_roles": ["body", "tool"]}}}
        )()
        self.assertTrue(pred(obj))

    def test_origin_predicate_no_match(self):
        pred = Q.origin("tool")
        obj = type("Obj", (), {"_metadata": {"track": {"origin_role": "body"}}})()
        self.assertFalse(pred(obj))

    def test_op_and_origin_do_not_fall_back_to_flat_tags(self):
        obj = type(
            "Obj",
            (),
            {"_metadata": {}, "_tags": {"op.cut.generated", "origin.tool"}},
        )()

        self.assertFalse(Q.op("cut", "generated")(obj))
        self.assertFalse(Q.origin("tool")(obj))

    def test_typed_tracking_predicates_roundtrip(self):
        operation = Q.operation_event("cut", "modified")
        origin = Q.origin_role("tool")

        self.assertEqual(
            Q.SerializablePredicate.from_dict(operation.to_dict()).to_dict(),
            operation.to_dict(),
        )
        self.assertEqual(
            Q.SerializablePredicate.from_dict(origin.to_dict()).to_dict(),
            origin.to_dict(),
        )

    def test_role_predicate(self):
        pred = Q.role("section")
        obj = type("Obj", (), {"_tags": {"role.section.face"}})()
        self.assertTrue(pred(obj))

    def test_select_faces_by_op(self):
        body = scad.make_box_rsolid(10, 10, 10)
        body.auto_tag_faces("box")
        tool = scad.make_cylinder_rsolid(2.0, 15.0, bottom_face_center=(3, 3, -2.5))
        result = tracked_cut(body, tool)
        tagged = apply_tracking_tags_to_delta(
            result.solid, result.delta, result.delta_entries, op="cut"
        )
        modified = Q.select(tagged._iter_faces()).where(Q.op("cut", "modified")).all()
        self.assertGreater(len(modified), 0)

    def test_select_faces_by_origin(self):
        body = scad.make_box_rsolid(10, 10, 10)
        tool = scad.make_cylinder_rsolid(2.0, 15.0, bottom_face_center=(3, 3, -2.5))
        result = tracked_cut(body, tool)
        tagged = apply_tracking_tags_to_delta(
            result.solid, result.delta, result.delta_entries, op="cut"
        )
        tool_faces = Q.select(tagged._iter_faces()).where(Q.origin("tool")).all()
        self.assertGreater(len(tool_faces), 0)


class TestGraphSession(unittest.TestCase):
    """Test the DAG session recorder."""

    def test_session_lifecycle(self):
        session = GraphSession()
        session.start()
        self.assertIsNotNone(get_active_session())
        session.stop()
        self.assertIsNone(get_active_session())

    def test_record_primitive(self):
        session = GraphSession()
        session.start()
        node = record_operation(
            "make_line_redge", {"start": (0, 0, 0), "end": (10, 0, 0)}
        )
        self.assertEqual(node.op, "make_line_redge")
        self.assertEqual(session.graph.node_count, 1)
        session.stop()

    def test_record_with_inputs(self):
        session = GraphSession()
        session.start()
        n1 = record_operation(
            "make_line_redge", {"start": (0, 0, 0), "end": (10, 0, 0)}
        )
        n2 = record_operation(
            "make_line_redge", {"start": (10, 0, 0), "end": (10, 10, 0)}
        )
        n3 = record_operation(
            "make_wire_from_edges_rwire", {"edge_count": 2}, inputs=[n1, n2]
        )
        self.assertEqual(session.graph.node_count, 3)
        self.assertEqual(len(n3.inputs), 2)
        session.stop()

    def test_record_with_topo_delta(self):
        body = scad.make_box_rsolid(10, 10, 10)
        tool = scad.make_cylinder_rsolid(2.0, 15.0, bottom_face_center=(3, 3, -2.5))
        result = tracked_cut(body, tool)

        session = GraphSession()
        session.start()
        body_node = record_operation(
            "make_extrude_rsolid",
            {"direction": (0, 0, 1), "distance": 10.0},
        )
        tool_node = record_operation(
            "make_extrude_rsolid",
            {"direction": (0, 0, 1), "distance": 15.0},
        )
        cut_node = record_operation(
            "make_cut_rsolid",
            {},
            inputs=[body_node, tool_node],
            topo_delta=result.delta,
        )
        self.assertIsNotNone(cut_node.topo_delta)
        self.assertGreater(len(cut_node.topo_delta.modified), 0)
        session.stop()

    def test_context_manager(self):
        with GraphSession() as session:
            n1 = record_operation(
                "make_extrude_rsolid", {"direction": (0, 0, 1), "distance": 1.0}
            )
            n2 = record_operation(
                "make_extrude_rsolid", {"direction": (0, 0, 1), "distance": 2.0}
            )
            record_operation("make_union_rsolid", {}, inputs=[n1, n2])
        self.assertEqual(session.graph.node_count, 3)

    def test_no_session_raises(self):
        with self.assertRaises(RuntimeError):
            record_operation("make_line_redge", {})

    def test_graph_is_dag(self):
        with GraphSession() as session:
            n1 = record_operation(
                "make_line_redge", {"start": (0, 0, 0), "end": (1, 0, 0)}
            )
            n2 = record_operation(
                "make_line_redge", {"start": (1, 0, 0), "end": (1, 1, 0)}
            )
            n3 = record_operation(
                "make_wire_from_edges_rwire", {"edge_count": 2}, inputs=[n1, n2]
            )
        self.assertTrue(session.graph.is_dag())

    def test_graph_topological_order(self):
        with GraphSession() as session:
            n1 = record_operation(
                "make_line_redge", {"start": (0, 0, 0), "end": (1, 0, 0)}
            )
            n2 = record_operation(
                "make_line_redge", {"start": (1, 0, 0), "end": (1, 1, 0)}
            )
            n3 = record_operation(
                "make_wire_from_edges_rwire", {"edge_count": 2}, inputs=[n1, n2]
            )
            n4 = record_operation("make_face_from_wire_rface", {}, inputs=[n3])
        order = session.graph.topological_order()
        self.assertEqual(len(order), 4)
        idx = {node.node_id: i for i, node in enumerate(order)}
        self.assertLess(idx[n1.node_id], idx[n3.node_id])
        self.assertLess(idx[n3.node_id], idx[n4.node_id])


if __name__ == "__main__":
    unittest.main()
