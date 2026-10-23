"""Contract tests: bare topology enumeration is forbidden; reads go through QL.

Plural topology getters accept only an index. The no-argument form raises a
guidance error pointing at QL selectors; indexed picks remain recorded as
graph selection nodes.
"""

from __future__ import annotations

import json
import unittest

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.core import Compound


class TestTopologyGetterContract(unittest.TestCase):
    def setUp(self):
        self.box = scad.make_box_rsolid(3.0, 2.0, 1.0)
        self.face = ql.faces().resolve(self.box)[0]
        self.wire = self.face.get_outer_wire()
        self.edge = ql.edges().resolve(self.wire)[0]
        self.shell = scad.sew_faces_rshell(self.box._iter_faces())
        self.compound = Compound([self.box, self.box])

    def _assert_enumeration_forbidden(self, owner, method_name):
        with self.assertRaises(scad.SimpleCADError) as ctx:
            getattr(owner, method_name)()
        message = str(ctx.exception)
        self.assertIn("ql.", message)
        self.assertIn("index", message)

    def test_every_plural_getter_forbids_bare_enumeration(self):
        cases = [
            (self.edge, "get_vertices"),
            (self.wire, "get_edges"),
            (self.face, "get_wires"),
            (self.face, "get_inner_wires"),
            (self.face, "get_edges"),
            (self.shell, "get_faces"),
            (self.shell, "get_wires"),
            (self.shell, "get_edges"),
            (self.box, "get_faces"),
            (self.box, "get_edges"),
            (self.box, "get_edge_occurrences"),
            (self.compound, "get_solids"),
            (self.compound, "get_faces"),
            (self.compound, "get_edges"),
        ]
        for owner, method_name in cases:
            with self.subTest(shape=type(owner).__name__, method=method_name):
                self._assert_enumeration_forbidden(owner, method_name)

    def test_indexed_pick_returns_shape_and_records_select_node(self):
        # The source shape must itself be a recorded graph node, so build it
        # inside the session the pick is recorded against.
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(3.0, 2.0, 1.0)
            picked = box.get_edges(0)
            self.assertEqual(
                picked.get_length(), ql.edges().resolve(box)[0].get_length()
            )
            scad.chamfer_rsolid(solid=box, edges=[picked], distance=0.1)
            payload = json.loads(scad.export_model_json(session))

        select_ops = [
            node["op"]
            for node in payload["graph"]["nodes"]
            if node["op"] == "make_select_redge"
        ]
        self.assertGreaterEqual(len(select_ops), 1)

    def test_ql_bare_enumeration_replaces_list_getters(self):
        self.assertEqual(len(ql.faces().resolve(self.box)), 6)
        self.assertEqual(len(ql.edges().resolve(self.box)), 12)
        self.assertEqual(len(ql.edges().resolve(self.wire)), 4)
        self.assertEqual(len(ql.solids().resolve(self.compound)), 2)

    def test_ql_predicate_and_cardinality_contract(self):
        bottom = (
            ql.faces()
            .where(ql.prop("geom.normal.z", "<=", -0.999))
            .take(1)
            .exactly(1)
            .resolve(self.box)
        )
        self.assertAlmostEqual(bottom[0].get_area(), 6.0, places=6)


if __name__ == "__main__":
    unittest.main()
