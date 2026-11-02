"""A cell's nodes are restored by the cache entry the values came from, not by the cell.

A cell has one cache entry per combination of the values it reads (an assembly that ``use`` s a part with other
overrides runs the part's cells under the same graph id, digest and cell, with other inputs).  The ids of the nodes
count from the cell's code, so two entries carry the same ids with other contents.  The nodes were written beside the
cell, so the entry run last replaced the record of the others: restoring another entry then registered nodes that
did not belong to its values, and a later cell that read them failed with "not owned by active graph" (the ids the
other run did not have) or bound to the other run's node of the same id (the ids it had).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pytest

pytest.importorskip("marimo")

import simplecadapi as scad
import simplecadapi._cpp as native
from simplecadapi.runtime import runner
from test_notebook_runtime import cell, notebook_text

PART = notebook_text(
    cell("LINK_L = 60.0", returns="LINK_L"),
    cell("STEPS = 4", returns="STEPS"),
    cell(
        """
        beam = scad.make_box_rsolid(LINK_L, 10.0, 5.0)
        for _i in range(STEPS):
            beam = scad.union_rsolid(beam, scad.make_cylinder_rsolid(2.0, 8.0))
        """,
        reads="LINK_L, STEPS",
        returns="beam",
    ),
    cell('link = scad.Part(part_id="link", body=beam)', reads="beam", returns="link"),
    table='id = "link"',
)


def cut_like_a_cell(beam):
    """What the next cell of the notebook does with the value (a cell session that accepts other cells' nodes)."""

    with scad.GraphSession(graph_id="link", namespace="cCUT", shared_lineage=True) as session:
        scad.cut_rsolid(beam, scad.make_cylinder_rsolid(1.0, 20.0))
    return session.graph


class EntryRecordTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).resolve() / "link.py"
        self.path.write_text(PART, encoding="utf-8")
        native.forget_graph_nodes("link")
        self.addCleanup(native.forget_graph_nodes, "link")

    def after_another_run(self, **overrides):
        """The editor's own values, restored from the disk after a child run with *overrides* wrote its entries."""

        runner.run_notebook(self.path)
        runner.run_notebook(self.path, overrides=overrides)
        native.forget_graph_nodes("link")  # a new process: only the records of the disk register nodes
        run = runner.run_notebook(self.path)
        self.assertEqual({report.status for report in run.cells[1:]}, {"cached"})
        return run.values["beam"]

    def test_values_restored_after_a_run_with_fewer_nodes_find_their_nodes(self) -> None:
        graph = cut_like_a_cell(self.after_another_run(STEPS=1))
        self.assertIn("make_union_rsolid", {node.op for node in graph.nodes})
        self.assertEqual(sum(node.op == "make_union_rsolid" for node in graph.nodes), 4)

    def test_values_restored_after_a_run_with_the_same_nodes_bind_to_their_own(self) -> None:
        graph = cut_like_a_cell(self.after_another_run(LINK_L=90.0))
        boxes = [node for node in graph.nodes if node.op == "make_box_rsolid"]
        self.assertEqual([box.params["width"] for box in boxes], [60.0])
