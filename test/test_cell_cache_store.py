"""What the cell cache puts on disk: compressed, and still reading what it
wrote before it compressed."""

from __future__ import annotations

import zlib

from simplecadapi.runtime import run_notebook
from simplecadapi.runtime.deps import state_dir
from test_notebook_runtime import NotebookTestCase, cell, notebook_text

DRILLED = notebook_text(
    cell(
        """
        plate = scad.make_box_rsolid(60.0, 40.0, 6.0)
        for _i in range(24):
            _hole = scad.make_cylinder_rsolid(
                radius=1.5, height=20.0, bottom_face_center=(5.0 + _i % 6 * 9, 5.0 + _i // 6 * 9, -5.0)
            )
            plate = scad.cut_rsolid(plate, _hole)
        """,
        returns="plate",
    ),
    cell("part = scad.Part(part_id='drilled', body=plate)", reads="plate", returns="part"),
    table='id = "drilled"',
)


class TestCellCacheStore(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.nb = self.write("drilled.py", DRILLED)

    def entries(self, run):
        return [item for item in (state_dir(run.config) / "cache").rglob("*") if item.is_file() and item.name != "_runs.json"]

    def test_entries_are_stored_compressed(self) -> None:
        run = run_notebook(self.nb)
        stored = sum(item.stat().st_size for item in self.entries(run))
        plain = 0
        for item in self.entries(run):
            data = item.read_bytes()
            plain += len(zlib.decompress(data[4:])) if data.startswith(b"SCZ2") else len(data)
        self.assertGreater(plain, 100_000)
        self.assertLess(stored, plain // 2)

    def test_entries_written_before_compression_are_still_hit(self) -> None:
        first = run_notebook(self.nb)
        for item in self.entries(first):
            data = item.read_bytes()
            if data.startswith(b"SCZ2"):
                item.write_bytes(zlib.decompress(data[4:]))
        second = run_notebook(self.nb)
        self.assertEqual(self.statuses(second), ["ran", "cached", "cached"])
        self.assertEqual(first.definition.content_hash, second.definition.content_hash)

