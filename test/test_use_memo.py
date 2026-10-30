"""``use`` hands out the product of the last run of a child while nothing it depends on has changed."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pytest

pytest.importorskip("marimo")

from simplecadapi.editor.templates import create_notebook
from simplecadapi.runtime import runner, usememo


class UseMemoTest(unittest.TestCase):
    def setUp(self) -> None:
        usememo.clear()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.child = Path(create_notebook(self.root, "child", "part"))
        self.runs: list[tuple] = []
        original = runner.run_notebook

        def spy(path, *, id=None, overrides=None, **kwargs):
            self.runs.append((Path(path).name, id, dict(overrides or {})))
            return original(path, id=id, overrides=overrides, **kwargs)

        runner.run_notebook = spy  # type: ignore[assignment]
        self.addCleanup(setattr, runner, "run_notebook", original)

    def test_the_same_call_runs_the_child_once_and_returns_the_same_product(self) -> None:
        first = runner.use(self.child)
        second = runner.use(self.child)
        self.assertIs(first, second)
        self.assertEqual(len(self.runs), 1)

    def test_other_overrides_run_again_and_replace_the_entry(self) -> None:
        runner.use(self.child, RADIUS=11.0, HEIGHT=5.0)
        runner.use(self.child, RADIUS=11.0, HEIGHT=5.0)
        runner.use(self.child, RADIUS=12.0, HEIGHT=5.0)
        runner.use(self.child, RADIUS=12.0, HEIGHT=5.0)
        self.assertEqual([run[2]["RADIUS"] for run in self.runs], [11.0, 12.0])
        runner.use(self.child, RADIUS=11.0, HEIGHT=5.0)  # the entry is the last run's: this one runs again
        self.assertEqual(len(self.runs), 3)

    def test_an_id_is_its_own_entry(self) -> None:
        a = runner.use(self.child, id="alpha")
        b = runner.use(self.child, id="beta")
        self.assertIsNot(a, b)
        self.assertIs(runner.use(self.child, id="alpha"), a)
        self.assertEqual(len(self.runs), 2)

    def test_editing_the_child_runs_it_again(self) -> None:
        runner.use(self.child)
        self.child.write_text(self.child.read_text() + "\n# edited\n")
        runner.use(self.child)
        self.assertEqual(len(self.runs), 2)

    def test_overrides_that_are_not_plain_data_are_not_kept(self) -> None:
        self.assertIsNotNone(usememo._signature(self.child, {"RADIUS": 1.0, "NAME": "a", "FLAGS": [1, True]}))
        for value in (object(), float("nan"), {1, 2}):
            self.assertIsNone(usememo._signature(self.child, {"X": value}), value)

    def test_it_can_be_turned_off(self) -> None:
        import os

        os.environ["SCA_NO_USE_MEMO"] = "1"
        self.addCleanup(os.environ.pop, "SCA_NO_USE_MEMO", None)
        runner.use(self.child)
        runner.use(self.child)
        self.assertEqual(len(self.runs), 2)

    def test_the_dependencies_of_the_run_are_still_recorded(self) -> None:
        recorded: list[set] = []
        original = runner.record_dependencies
        runner.record_dependencies = lambda paths: recorded.append(set(paths))  # type: ignore[assignment]
        self.addCleanup(setattr, runner, "record_dependencies", original)
        runner.use(self.child)
        runner.use(self.child)
        self.assertEqual(len(recorded), 2)
        self.assertEqual(recorded[0], recorded[1])
        self.assertIn(self.child.resolve(), {path.resolve() for path in recorded[1]})

    def test_two_children_under_one_id_do_not_both_stay_kept(self) -> None:
        other = Path(create_notebook(self.root, "other", "part"))
        first = runner.use(self.child, id="shared")
        runner.use(other, id="shared")  # registers its nodes under "shared", replacing the first run's
        again = runner.use(self.child, id="shared")
        self.assertIsNot(again, first)  # the first run's nodes are gone from the registry: it has to run again
        self.assertEqual([run[0] for run in self.runs], ["child.py", "other.py", "child.py"])

    def test_a_key_kept_again_under_another_graph_id_does_not_leave_its_old_owner(self) -> None:
        runner.use(self.child, id="one")
        owners = dict(usememo._owners)
        self.assertEqual(len(owners), 1)
        # the same key, now under another graph id (the child's header id was edited)
        key = next(iter(usememo._entries))
        kept = usememo._entries[key][1]
        usememo.keep(self.child, "one", {}, usememo.Kept(kept.product, kept.path, kept.dependencies, "other-graph"))
        self.assertEqual(set(usememo._owners), {"other-graph"})
        self.assertEqual(usememo._owners["other-graph"], key)

    def test_eviction_forgets_the_owner_of_the_evicted_entry_only(self) -> None:
        original = usememo._MAX_ENTRIES
        usememo._MAX_ENTRIES = 2
        self.addCleanup(setattr, usememo, "_MAX_ENTRIES", original)
        for name in ("a", "b", "c"):
            runner.use(self.child, id=name)
        self.assertEqual(len(usememo._entries), 2)
        self.assertEqual(set(usememo._owners.values()), set(usememo._entries))


if __name__ == "__main__":
    unittest.main()
