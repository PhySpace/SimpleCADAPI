"""A cached cell whose lineage record belongs to another graph is a miss, not a failure.

A notebook run under several ids (a part family: ``use("child.py", id="member")``) keeps one cache per id, and the
nodes of a cell belong to the graph of that id.  A record saved under another id (an interrupted run, a cache copied
between ids) registers its nodes under that other graph, and the values restored beside it then name nodes nobody
registered: ``ValueError: value contains graph node '...' not owned by active graph '<id>'``.  The cell has to run
again instead.
"""

from __future__ import annotations

import glob
import pickle
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi._glue.session import GraphSession
from simplecadapi.runtime import lineage, run_notebook
from simplecadapi.runtime.config import read_notebook_config
from simplecadapi.runtime.deps import state_dir

pytest.importorskip("marimo")

CELL = "    base = scad.cut_rsolid(base, scad.make_box_rsolid(2, 2, 500, bottom_face_center=(3.0, 0.0, -100.0)))\n    return (base,)"


class LineageGraphTest(unittest.TestCase):
    def test_load_refuses_a_record_of_another_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with GraphSession(graph_id="alpha", namespace="cell1", shared_lineage=True) as session:
                scad.cut_rsolid(scad.make_box_rsolid(10, 10, 10), scad.make_box_rsolid(2, 2, 40, bottom_face_center=(3, 3, -10)))
            lineage.save(Path(tmp), "cell-a", session)
            self.assertFalse(lineage.load(Path(tmp), "cell-a", "beta"))
            self.assertTrue(lineage.load(Path(tmp), "cell-a", "alpha"))
            self.assertTrue(lineage.load(Path(tmp), "cell-a"))  # no graph asked for: as before

    def test_a_family_member_with_a_foreign_record_runs_again(self) -> None:
        from simplecadapi.editor.templates import create_notebook

        with tempfile.TemporaryDirectory() as tmp:
            notebook = create_notebook(Path(tmp), "child", "part")
            source = Path(notebook).read_text().replace("    return (base,)", CELL, 1)
            Path(notebook).write_text(source)
            for ident in ("child", "member"):
                run_notebook(notebook, id=ident)
            config = read_notebook_config(notebook)
            records = glob.glob(str(state_dir(replace(config, id="member")) / "cache" / "*" / "lineage.*"))
            self.assertTrue(records)
            for record in records:  # the member's records say they belong to the default graph
                document = pickle.loads(zlib.decompress(Path(record).read_bytes()))
                document["graph_id"] = "child"
                Path(record).write_bytes(zlib.compress(pickle.dumps(document, protocol=5), 1))
            # A fresh process: nothing registered by the runs above masks the missing nodes.
            code = textwrap.dedent(
                f"""
                from simplecadapi.runtime import run_notebook
                run = run_notebook({str(notebook)!r}, id="member")
                print("STATUSES", ",".join(cell.status for cell in run.cells))
                """
            )
            done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr[-800:])
            statuses = next(line for line in done.stdout.splitlines() if line.startswith("STATUSES")).split()[1].split(",")
            self.assertIn("ran", statuses[1:])  # the poisoned cells ran again instead of being restored


if __name__ == "__main__":
    unittest.main()


class MissingRecordHealsTest(unittest.TestCase):
    """Cached values without their lineage record: the cell runs once more and the next run restores it."""

    def test_a_cell_whose_record_is_missing_is_a_miss_once(self) -> None:
        from simplecadapi.editor.templates import create_notebook

        with tempfile.TemporaryDirectory() as tmp:
            notebook = create_notebook(Path(tmp), "child", "part")
            Path(notebook).write_text(Path(notebook).read_text().replace("    return (base,)", CELL, 1))
            run_notebook(notebook)
            config = read_notebook_config(notebook)
            records = glob.glob(str(state_dir(config) / "cache" / "*" / "lineage.*"))
            self.assertTrue(records)
            for record in records:
                Path(record).unlink()
            code = textwrap.dedent(
                f"""
                from simplecadapi.runtime import run_notebook
                run = run_notebook({str(notebook)!r})
                print("STATUSES", ",".join(cell.status for cell in run.cells))
                """
            )

            def statuses() -> list[str]:
                done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
                self.assertEqual(done.returncode, 0, done.stderr[-800:])
                return next(line for line in done.stdout.splitlines() if line.startswith("STATUSES")).split()[1].split(",")

            repaired = statuses()
            self.assertIn("ran", repaired[1:])  # the record was missing: the cells ran
            again = statuses()
            self.assertNotIn("ran", again[1:])  # and wrote it: the next run restores them


class UnrestorableEntryTest(unittest.TestCase):
    """An entry that names classes which are gone is deleted, not kept: it used to cost every later run all its cells.

    marimo restores such a value as a stub and only makes the entry miss for the rest of the process; the runner
    dropped the whole cache for the run and left the entry as it was, so every later run found the same stubs.
    """

    def test_discard_deletes_the_manifest_and_the_blobs_of_the_restored_entry(self) -> None:
        from types import SimpleNamespace

        from simplecadapi.runtime.cache import CellCache

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root / "dg1" / "cells"
            (entry / "Ab_cD-1").mkdir(parents=True)
            (entry / "Ab_cD-1" / "bearing.pickle").write_bytes(b"x")
            (entry / "Ab_cD-1").joinpath("other.pickle").write_bytes(b"x")
            (entry / "C_Ab_cD-1.jsonl").write_text("{}")
            (entry / "Zz9").mkdir()
            (entry / "C_Zz9.jsonl").write_text("{}")  # another entry of the same digest: untouched
            cache = CellCache.__new__(CellCache)
            cache._root = root
            cache._digest_for = lambda cell: "dg1"
            cache._restored_keys = {"cellA": "cells/C_Ab_cD-1.jsonl"}
            cache.restored = {"cellA"}
            cache.discard(SimpleNamespace(cell_id="cellA"))
            self.assertFalse((entry / "C_Ab_cD-1.jsonl").exists())
            self.assertFalse((entry / "Ab_cD-1").exists())
            self.assertTrue((entry / "C_Zz9.jsonl").exists())
            self.assertTrue((entry / "Zz9").exists())
            self.assertEqual(cache.restored, set())
            cache.discard(SimpleNamespace(cell_id="cellA"))  # nothing restored under it any more: a no-op
