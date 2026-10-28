"""The editor kernel keeps what its cells made: a cache hit on a value this process holds is not unpickled again."""

from __future__ import annotations

import unittest

import pytest

pytest.importorskip("marimo")

import simplecadapi as scad
from simplecadapi.runtime import cache as cache_module
from simplecadapi.runtime._marimo import InternalApp, load_notebook
from simplecadapi.runtime.config import read_notebook_config
from simplecadapi.runtime.runner import _cell_prefix
from test_notebook_runtime import NotebookTestCase, cell, notebook_text
from simplecadapi.runtime.cache import CellDigests, _CellMemory, _attempt_with_memory, _shareable


class Loader:
    sca_memory: _CellMemory | None = None


class Key:
    def __init__(self, hash_: str) -> None:
        self.hash = hash_
        self.cache_type = "ContentAddressed"


class FakeAttempt:
    """What a loader answers on a hit, as far as the memory touches it."""

    def __init__(self, key: Key, restored: dict, hit: bool = True, stateful: set | None = None) -> None:
        self.key = key
        self.hit = hit
        self.stateful_refs = stateful or set()
        self.meta: dict = {"return": None}
        self._disk = restored
        self.disk_restores = 0

        def restore(scope: dict) -> None:
            self.disk_restores += 1
            scope.update(self._disk)
            self.meta["return"] = "output"

        self.restore = restore

    def contextual_defs(self) -> dict:
        return {(name, name): None for name in self._disk}


class FakeLoader(Loader):
    """A loader whose ``cache_attempt`` is what the disk would answer."""

    def __init__(self, memory: _CellMemory) -> None:
        self.sca_memory = memory
        self.asked: list[str] = []
        self.next: FakeAttempt | None = None

    def cache_attempt(self, defs, key, stateful_refs, glbls=None):
        self.asked.append(key.hash)
        assert self.next is not None
        return self.next


class FakeHasher:
    key = Key("h1")
    defs: dict = {}
    stateful_refs: set = set()

    def __init__(self, **kwargs) -> None:
        pass


class ShareableTest(unittest.TestCase):
    def test_sdk_values_and_plain_data_are_shared_and_containers_that_a_cell_could_change_are_not(self) -> None:
        box = scad.make_box_rsolid(1, 1, 1)
        part = scad.make_part_rpart(part_id="p", body=box, name="p")
        for value in (None, 1, 2.5, "x", True, box, part, (box, part, 1)):
            self.assertTrue(_shareable(value), value)
        for value in ([box], {"a": box}, {1, 2}, object(), lambda: 1):
            self.assertFalse(_shareable(value), value)


class MemoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = _CellMemory(limit=2)
        self.loader = FakeLoader(self.memory)
        self.box = scad.make_box_rsolid(2, 2, 2)
        original = cache_module.BlockHasher
        cache_module.BlockHasher = FakeHasher  # type: ignore[assignment]
        self.addCleanup(setattr, cache_module, "BlockHasher", original)

    def attempt(self, hash_: str = "h1", restored: dict | None = None, **kwargs) -> FakeAttempt:
        """Ask for the entry *hash_*: the memory first, the disk (the fake loader) when the memory lacks it."""
        FakeHasher.key = Key(hash_)
        FakeHasher.stateful_refs = kwargs.get("stateful") or set()
        self.loader.next = FakeAttempt(Key(hash_), {"body": self.box} if restored is None else restored, **kwargs)
        return _attempt_with_memory(None, None, "cell", {}, loader=self.loader)

    def test_the_second_ask_for_an_entry_is_answered_from_memory_without_asking_the_disk(self) -> None:
        first = self.attempt()
        scope: dict = {}
        first.restore(scope)
        self.assertEqual(self.loader.asked, ["h1"])
        second = self.attempt()
        again: dict = {}
        second.restore(again)
        self.assertEqual(self.loader.asked, ["h1"])  # the disk was not asked again
        self.assertIs(again["body"], scope["body"])
        self.assertEqual(second.meta["return"], "output")  # the cell's output comes back with it
        self.assertTrue(second.hit)

    def test_another_entry_or_another_loader_is_not_taken_for_it(self) -> None:
        self.attempt("h1").restore({})
        other = self.attempt("h2")
        self.assertEqual(self.loader.asked, ["h1", "h2"])  # a different entry: the disk answered
        other.restore({})
        self.loader = FakeLoader(self.memory)  # a different loader: its entries are not this one's
        self.attempt("h1").restore({})
        self.assertEqual(self.loader.asked, ["h1"])

    def test_values_a_cell_could_change_and_stateful_cells_are_not_kept(self) -> None:
        self.attempt("h1", {"items": [self.box]}).restore({})
        self.attempt("h1", {"items": [self.box]}).restore({})
        self.assertEqual(self.loader.asked, ["h1", "h1"])  # a list is not shared: the disk answered both times
        self.attempt("h3", stateful={"ui"}).restore({})
        self.assertEqual(len(self.memory), 0)

    def test_a_miss_is_left_alone(self) -> None:
        miss = self.attempt("h9", hit=False)
        self.assertFalse(miss.hit)
        self.assertEqual(len(self.memory), 0)

    def test_a_loader_without_memory_goes_to_the_disk(self) -> None:
        plain = FakeLoader(self.memory)
        plain.sca_memory = None  # type: ignore[assignment]
        original = cache_module._marimo_attempt
        seen = []
        cache_module._marimo_attempt = lambda *a, **k: seen.append(k["loader"]) or "from marimo"  # type: ignore[assignment]
        self.addCleanup(setattr, cache_module, "_marimo_attempt", original)
        self.assertEqual(_attempt_with_memory(None, None, "cell", {}, loader=plain), "from marimo")
        self.assertEqual(seen, [plain])

    def test_the_oldest_entry_goes_when_there_are_too_many(self) -> None:
        for name in ("a", "b", "c"):
            self.attempt(name).restore({})
        self.assertEqual(len(self.memory), 2)
        self.assertIsNone(self.memory.recall(self.loader, Key("a")))
        self.assertIsNotNone(self.memory.recall(self.loader, Key("c")))



class SavedValuesFollowWhatACellReadsTest(unittest.TestCase):
    """A saved value is in the digest of the cells it reaches, not of every cell below the cell that defines it."""

    def sources(self):
        from simplecadapi.runtime.deps import CellSource

        def cell(key, refs, defs):
            return CellSource(key, "", frozenset(refs), frozenset(defs))

        # the six-axis arm's shape: one parameter cell, a chain of parts and mates, joints that read the angles
        return [
            cell("params", [], ["J1", "J2", "OPEN", "LENGTH"]),
            cell("gripper", ["OPEN"], ["grip"]),
            cell("link", ["LENGTH"], ["ulink"]),
            cell("components", ["grip", "ulink"], ["components"]),
            cell("mates", ["components"], ["mates"]),
            cell("joints", ["J1", "J2", "mates"], ["joints"]),
            cell("solve", ["joints"], ["solved"]),
        ]

    def names(self, saved):
        from simplecadapi.runtime.cache import saved_names_by_cell

        return saved_names_by_cell(self.sources(), saved)

    def test_a_joint_angle_reaches_the_cells_that_read_it_and_those_below_them(self) -> None:
        names = self.names({"J1"})
        self.assertEqual({key for key, found in names.items() if "J1" in found}, {"params", "joints", "solve"})

    def test_a_length_reaches_the_part_it_sizes_and_everything_built_from_it(self) -> None:
        names = self.names({"LENGTH"})
        self.assertEqual(
            {key for key, found in names.items() if "LENGTH" in found},
            {"params", "link", "components", "mates", "joints", "solve"},
        )
        self.assertNotIn("LENGTH", names["gripper"])  # a sibling that does not read it

    def test_the_cell_that_defines_a_saved_value_always_carries_it(self) -> None:
        self.assertEqual(self.names({"OPEN"})["params"], {"OPEN"})

    def test_nothing_saved_means_nothing_to_carry(self) -> None:
        self.assertTrue(all(not found for found in self.names(set()).values()))


class SavedValuesInTheDigestsOfARealNotebookTest(NotebookTestCase):
    """What the editor applies to a variable changes the digest of the cells that get it, through any chain of cells."""

    def digests(self, saved):
        path = self.write(
            "arm.py",
            notebook_text(
                cell("A = 1.0\nB = 2.0", returns="A, B"),
                cell("half = A / 2", reads="A", returns="half"),
                cell("quarter = half / 2", reads="half", returns="quarter"),
                cell("other = B + 1", reads="B", returns="other"),
            ),
        )
        config = read_notebook_config(path)
        internal = InternalApp(load_notebook(path, cell_prefix=_cell_prefix(config)))
        ordered = [internal.graph.cells[i] for i in internal.cell_manager.cell_ids() if i in internal.graph.cells]
        setup = internal.graph.cells.get(internal.cell_manager.setup_cell_id)
        found = CellDigests(config, ordered, setup, saved=saved, kernel=True)
        return {cell_.code.split(" =")[0].split("\n")[0]: found.digest(cell_.cell_id) for cell_ in ordered}

    def test_a_value_reaches_a_cell_that_only_reads_it_through_another(self) -> None:
        before, after = self.digests({"A": 1.0}), self.digests({"A": 5.0})
        self.assertNotEqual(before["half"], after["half"])
        self.assertNotEqual(before["quarter"], after["quarter"])  # reads `half`, which reads `A`
        self.assertEqual(before["other"], after["other"])  # reads only `B`

    def test_the_same_saved_values_give_the_same_digests(self) -> None:
        self.assertEqual(self.digests({"A": 5.0}), self.digests({"A": 5.0}))


class MarimoHookTest(unittest.TestCase):
    def test_marimo_asks_the_function_the_memory_replaced(self) -> None:
        """The cell memory re-implements the first half of marimo's ``cache_attempt_from_hash``: a marimo whose
        signature changed (the upgrade this would break on) has to fail here, not quietly lose the memory."""
        import inspect

        from simplecadapi.runtime import cache
        from simplecadapi.runtime._marimo import marimo_cached

        self.assertTrue(cache._MEMORY_NEEDS <= set(inspect.signature(cache._marimo_attempt).parameters))
        self.assertIs(marimo_cached.cache_attempt_from_hash, cache._attempt_with_memory)


class AValueAnotherCellChangedIsNotHandedOutTest(unittest.TestCase):
    """``set_metadata`` and ``auto_tag_faces`` change a value in place: what a cell did to a value it was given must
    not be seen by a later run that restores the entry (the disk copy is a fresh object each time)."""

    def setUp(self) -> None:
        self.memory = _CellMemory(limit=4)
        self.loader = object()

    def test_a_value_changed_in_place_after_it_was_kept_is_a_miss(self) -> None:
        import simplecadapi as scad

        box = scad.make_box_rsolid(2, 2, 2)
        self.memory.remember(self.loader, Key("e"), {"box": box}, {})
        self.assertIsNotNone(self.memory.recall(self.loader, Key("e")))
        box.set_metadata("note", "changed by a later cell")
        self.assertIsNone(self.memory.recall(self.loader, Key("e")))
        self.assertEqual(len(self.memory), 0)  # and the entry is gone, not just skipped

    def test_a_value_kept_again_after_a_change_is_the_new_state(self) -> None:
        import simplecadapi as scad

        box = scad.make_box_rsolid(2, 2, 2)
        box.set_metadata("note", "before")
        self.memory.remember(self.loader, Key("e"), {"box": box}, {})
        self.assertIsNotNone(self.memory.recall(self.loader, Key("e")))


if __name__ == "__main__":
    unittest.main()
