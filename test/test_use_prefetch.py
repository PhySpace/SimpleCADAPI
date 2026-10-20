"""Running the notebooks a cell uses side by side.

OpenCASCADE does not let go of the interpreter lock, so threads would not
help: the ``use`` calls of a cell that is about to run are started in worker
processes, which only fill the notebooks' cell caches.  The cell then runs its
``use`` calls as it always did, and finds the work done.  Whatever the workers
do (or fail to do), the result is the one a serial run gives.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from simplecadapi.runtime import prefetch, run_notebook
from test_notebook_runtime import NotebookTestCase, notebook_text
from test_use_digests import ASSEMBLE, child, parent


class TestPlan(unittest.TestCase):
    root = Path("/proj")

    def plan(self, code: str, scope: dict | None = None):
        return prefetch.plan_uses(code, scope or {}, self.root)

    def test_literal_paths_and_values_known_before_the_cell_runs(self) -> None:
        requests = self.plan(
            'a = scad.use("child_a.py")\nb = scad.use("sub/b.py", id="x", WIDTH=float(W), N=3)',
            {"W": 4},
        )
        self.assertEqual([r.path for r in requests], [self.root / "child_a.py", self.root / "sub/b.py"])
        self.assertEqual((requests[1].id, requests[1].overrides), ("x", {"WIDTH": 4.0, "N": 3}))

    def test_the_id_of_the_running_notebook_is_known(self) -> None:
        requests = prefetch.plan_uses(
            'a = scad.use("c.py", id=scad.notebook_id() + "-body", LENGTH=float(L))', {"L": 2}, self.root, notebook_id="arm"
        )
        self.assertEqual([(r.id, dict(r.overrides)) for r in requests], [("arm-body", {"LENGTH": 2.0})])
        self.assertEqual(self.plan('a = scad.use("c.py", id=scad.notebook_id())'), [])  # not told which

    def test_what_cannot_be_known_is_left_to_the_cell(self) -> None:
        for code in (
            'a = scad.use(name + ".py")',  # computed path
            'a = scad.use("c.py") if flag else None',  # may not run
            'for n in names:\n    scad.use("c.py")',  # a loop
            'a = scad.use("c.py", LENGTH=other.size())',  # a call the plan will not make
            'a = scad.use("c.py", LENGTH=missing)',  # a name the cell defines itself
            "def f():\n    return scad.use('c.py')",  # not run by the cell
        ):
            with self.subTest(code=code):
                self.assertEqual(self.plan(code, {"flag": True, "names": [1], "other": object()}), [])

    def test_two_requests_for_one_run_are_one(self) -> None:
        requests = self.plan('a = scad.use("c.py", W=1.0)\nb = scad.use("c.py", W=1.0)\nc = scad.use("c.py", W=2.0)')
        self.assertEqual(len({r.key for r in requests}), 2)


class TestPrefetchedRun(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"SCA_JOBS": "2"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(prefetch.shutdown)
        prefetch.reset_stats()
        self.write("child_a.py", child("child_a", 10.0))
        self.write("child_b.py", child("child_b", 6.0))
        self.top = self.write("top.py", self.parent_text())

    @staticmethod
    def parent_text() -> str:
        # both uses in one cell, as in a real assembly
        return notebook_text(
            "@app.cell\ndef _():\n    a = scad.use('child_a.py')\n    b = scad.use('child_b.py')\n    return a, b\n",
            "@app.cell\ndef _(a, b):\n" + ASSEMBLE.rstrip("\n") + "\n    return (top,)\n",
            table='id = "top"',
        )

    def test_a_cell_with_two_uses_starts_them_together_and_gives_the_serial_result(self) -> None:
        run = run_notebook(self.top)
        self.assertEqual(sorted(Path(p).name for p in prefetch.stats()["submitted"]), ["child_a.py", "child_b.py"])
        serial = run_notebook(self.top, cache=False)
        self.assertEqual(run.definition.content_hash, serial.definition.content_hash)

    def test_a_notebook_that_has_not_changed_since_it_last_ran_is_not_started_again(self) -> None:
        run_notebook(self.top)
        prefetch.reset_stats()
        run_notebook(self.top, cache=False)  # the cell runs again; the children are as they were
        self.assertEqual(prefetch.stats()["submitted"], [])

    def stamped(self, seconds: float) -> None:
        """Make both children look like they last took *seconds* to build."""

        from simplecadapi.runtime.config import read_notebook_config

        for name in ("child_a.py", "child_b.py"):
            stamp = prefetch._stamp_file(read_notebook_config(self.root / name))
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(json.dumps({"signature": "stale", "seconds": seconds}))

    def test_notebooks_that_build_in_moments_are_not_worth_a_worker(self) -> None:
        # a worker takes seconds to start; two builds of a fifth of a second do not repay it
        self.stamped(0.2)
        run_notebook(self.top)
        self.assertEqual(prefetch.stats()["submitted"], [])

    def test_notebooks_that_took_long_are_started_together(self) -> None:
        self.stamped(20.0)
        run_notebook(self.top)
        self.assertEqual(len(prefetch.stats()["submitted"]), 2)

    def test_a_run_remembers_how_long_it_took_to_build(self) -> None:
        from simplecadapi.runtime.config import read_notebook_config

        run_notebook(self.root / "child_a.py")
        stamp = json.loads(prefetch._stamp_file(read_notebook_config(self.root / "child_a.py")).read_text())
        self.assertGreater(stamp["seconds"], 0.0)
        # a run that only restores does not make it look cheap
        run_notebook(self.root / "child_a.py", cache=True)
        again = json.loads(prefetch._stamp_file(read_notebook_config(self.root / "child_a.py")).read_text())
        self.assertEqual(again["seconds"], stamp["seconds"])

    def test_a_failing_child_is_reported_by_the_run_that_uses_it(self) -> None:
        self.write("child_b.py", child("child_b", 6.0).replace("make_box_rsolid(width, 4.0, 4.0)", "make_box_rsolid(width, -4.0, 4.0)"))
        with self.assertRaises(Exception) as caught:
            run_notebook(self.top)
        # the error of the child itself, not something about a worker
        self.assertIn("greater than zero", str(caught.exception))

    def test_one_use_is_not_worth_a_worker(self) -> None:
        one = notebook_text(
            "@app.cell\ndef _():\n    a = scad.use('child_a.py')\n    return (a,)\n",
            "@app.cell\ndef _(a):\n"
            '    _asm = scad.make_assembly_rassembly(assembly_id="single", name="single")\n'
            '    single = scad.add_component_rassembly(assembly=_asm, item=a, component_id="a", '
            "placement=scad.identity_placement_rplacement())\n"
            "    return (single,)\n",
            table='id = "single"',
        )
        run_notebook(self.write("single.py", one))
        self.assertEqual(prefetch.stats()["submitted"], [])

    def test_the_command_line_prints_only_its_report(self) -> None:
        chatty = child("child_a", 10.0).replace("width = 10.0", "print('from the child')\n    width = 10.0")
        self.write("child_a.py", chatty)
        done = subprocess.run(
            [sys.executable, "-c", "import sys; from simplecadapi.cli import main; sys.exit(main(['run', sys.argv[1]]))", str(self.top)],
            capture_output=True, text=True, env={**os.environ, "SCA_JOBS": "2"}, timeout=300,
        )
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        lines = [line for line in done.stdout.splitlines() if line.strip()]
        self.assertEqual(json.loads(lines[-1])["definition_id"], "top")
        self.assertNotIn("from the child", done.stdout)  # a worker's output goes nowhere
