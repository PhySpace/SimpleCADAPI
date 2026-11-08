"""A tag follows its entity as a reference does: a split names the pieces <tag>.split<i>; solids have history and refs.

The pieces of a split are numbered when the operation is recorded (by centre, then size), the order a split reference
lists its candidates in; the split is reported (list_tag_splits, the cell's TagSplitWarning, the run report).
"""

from __future__ import annotations

import json
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi.runtime import run_notebook
from test_notebook_runtime import NotebookTestCase, cell, notebook_text

ql = scad.ql


def _tags(shape, prefix: str) -> list[str]:
    return sorted(t for f in ql.faces().resolve(shape) for t in f._list_tags() if t.startswith(prefix))


def _top(box):
    return scad.apply_tag_rselection(box, ql.faces().where(ql.prop("geom.center.z", ">=", 9.9)).exactly(1), "mount.top")


def test_a_split_tagged_face_names_its_pieces_and_the_tag_none_of_them():
    with scad.GraphSession():
        box = _top(scad.make_box_rsolid(40.0, 10.0, 10.0))
        grooved = scad.cut_rsolid(box, scad.make_box_rsolid(2.0, 20.0, 4.0, bottom_face_center=(0.0, 0.0, 8.0)))
        assert _tags(grooved, "mount") == ["mount.top.split1", "mount.top.split2"]
        assert ql.faces().where(ql.tag("mount.top")).resolve(grooved) == []
        assert len(ql.faces().where(ql.tag("mount.top.*")).resolve(grooved)) == 2
        left = ql.faces().where(ql.tag("mount.top.split1")).exactly(1).resolve(grooved)[0]
        assert left.get_center().x < 0  # piece 1 is the one with the smaller centre
        [row] = scad.list_tag_splits(grooved)
        assert (row["tag"], row["into"], row["op"]) == ("mount.top", ["mount.top.split1", "mount.top.split2"], "make_cut_rsolid")
        # a hole is no split: the face keeps its tag
        drilled = scad.cut_rsolid(box, scad.make_cylinder_rsolid(1.0, 30.0, (10.0, 0.0, -5.0)))
        assert _tags(drilled, "mount") == ["mount.top"] and scad.list_tag_splits(drilled) == []


def test_the_pieces_follow_on_and_a_second_split_numbers_again():
    with scad.GraphSession():
        box = _top(scad.make_box_rsolid(40.0, 10.0, 10.0))
        halves = scad.cut_rsolid(box, scad.make_box_rsolid(2.0, 20.0, 20.0))  # splits the body, and the top face
        moved = scad.translate_shape(halves, (0.0, 0.0, 1.0))
        assert [_tags(piece, "mount") for piece in moved] == [["mount.top.split1"], ["mount.top.split2"]]
        quarter = scad.cut_rsolid(moved[1], scad.make_box_rsolid(2.0, 20.0, 20.0, bottom_face_center=(10.0, 0.0, -5.0)))
        assert sorted(_tags(piece, "mount") for piece in quarter) == [["mount.top.split2.split1"], ["mount.top.split2.split2"]]


def test_a_solid_is_continued_by_one_solid_operations_merged_by_a_union_and_split_by_a_cut():
    with scad.GraphSession():
        box = scad.apply_tag_rselection(scad.make_box_rsolid(40.0, 10.0, 10.0), ql.solids().exactly(1), "part.base")
        rounded = scad.fillet_rsolid(box, ql.edges().where(ql.prop("geom.center.z", ">=", 9.9)), 1.0)
        moved = scad.translate_shape(rounded, (1.0, 0.0, 0.0))
        assert "part.base" in moved._list_tags()
        joined = scad.union_rsolid(moved, scad.make_cylinder_rsolid(2.0, 20.0))  # another op: no second box to confuse it with
        reference = scad.ref.of(rounded, rounded)
        assert reference.kind == "solid" and reference.resolve(joined).status in ("ok", "merged")
        pieces = scad.cut_rsolid(moved, scad.make_box_rsolid(2.0, 20.0, 20.0, bottom_face_center=(1.0, 0.0, -5.0)))
        assert [sorted(t for t in p._list_tags() if t.startswith("part")) for p in pieces] == [["part.base.split1"], ["part.base.split2"]]
        resolved = reference.resolve(pieces)
        assert resolved.status == "split" and resolved.bodies == [0, 1]


def test_a_solid_reference_names_one_piece_through_later_operations():
    with scad.GraphSession():
        box = scad.make_box_rsolid(40.0, 10.0, 10.0)
        # made before the cut's tool box exists: two make_box_rsolid nodes later, and the history tells them apart
        early = scad.ref.of(box, box)
        pieces = scad.cut_rsolid(box, scad.make_box_rsolid(2.0, 20.0, 20.0))
        assert early.resolve(pieces).status == "split"
        right = scad.ref.of(pieces[1], pieces[1])
        assert right.kind == "solid" and right.slot == 1 and scad.ref.parse(repr(right)) == right
        moved = scad.translate_shape(pieces, (0.0, 0.0, 3.0))
        assert right.one(moved).get_center().x > 0
        assert right.resolve(moved[0]).status == "lost"
        with pytest.raises(ValueError, match="a solid has no kernel role"):
            scad.ref.parse("scad.ref.solid('base', 'make_box_rsolid', role='box')")


def test_a_reference_selection_works_over_the_pieces_and_refuses_one_that_finds_nothing():
    with scad.GraphSession():
        box = scad.make_box_rsolid(40.0, 10.0, 10.0)
        pieces = scad.cut_rsolid(box, scad.make_box_rsolid(2.0, 20.0, 20.0))
        moved = scad.translate_shape(pieces, (0.0, 0.0, 3.0))
        rim = ql.edges().where(ql.prop("geom.center.x", ">=", 15)).where(ql.prop("geom.center.z", ">=", 9)).resolve(pieces[1])[0]
        edge = scad.ref.of(rim, pieces[1])
        rounded = scad.fillet_rsolid(moved, scad.ref.edges(edge), 0.3)
        assert rounded[0].get_volume() == pytest.approx(moved[0].get_volume())
        assert rounded[1].get_volume() < moved[1].get_volume()
        top = scad.ref.of(ql.faces().where(ql.prop("geom.center.z", ">=", 12)).resolve(moved[0])[0], moved[0])
        shelled = scad.shell_rsolid(moved, scad.ref.faces(top), 0.5)
        assert shelled[0].get_volume() < moved[0].get_volume()
        assert shelled[1].get_volume() == pytest.approx(moved[1].get_volume())
        with pytest.raises(scad.ref.ElementRefError):
            scad.fillet_rsolid(moved[0], scad.ref.edges(edge), 0.3)  # one piece, the edge is on the other


SPLIT = notebook_text(
    cell(
        "box = scad.apply_tag_rselection(scad.make_box_rsolid(40.0, 10.0, 10.0),"
        " scad.ql.faces().where(scad.ql.prop('geom.center.z', '>=', 9.9)).exactly(1), 'mount.top')",
        returns="box",
    ),
    cell(
        "grooved = scad.cut_rsolid(box, scad.make_box_rsolid(2.0, 20.0, 4.0, bottom_face_center=(0.0, 0.0, 8.0)))",
        reads="box",
        returns="grooved",
    ),
    cell("part = scad.make_part_rpart(part_id='grooved', body=grooved)", reads="grooved", returns="part"),
    table='id = "grooved"',
)


class TestTheRunReportsTheSplit(NotebookTestCase):
    def test_a_split_is_reported_by_the_cell_that_made_it_ran_or_restored(self) -> None:
        nb = self.write("grooved.py", SPLIT)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            first = run_notebook(nb)
        assert any(issubclass(w.category, scad.TagSplitWarning) and "mount.top.split1" in str(w.message) for w in caught)
        second = run_notebook(nb)
        for run in (first, second):
            splits = {report.key.split(".")[0]: report.tag_splits for report in run.cells if report.tag_splits}
            assert len(splits) == 1
            [rows] = splits.values()
            assert [row["into"] for row in rows] == [["mount.top.split1", "mount.top.split2"]]
        assert self.statuses(second)[2] == "cached"
        report = subprocess.run(
            [sys.executable, "-m", "simplecadapi.cli", "run", str(nb)], capture_output=True, text=True, check=True
        )
        cells = json.loads(report.stdout.strip().splitlines()[-1])["cells"]
        assert [c["tag_splits"] for c in cells if "tag_splits" in c] == [
            [{"tag": "mount.top", "into": ["mount.top.split1", "mount.top.split2"], "op": "make_cut_rsolid"}]
        ]


def test_the_preview_scene_lists_the_entities_of_each_piece():
    from simplecadapi.runtime.live import scene_tag_splits
    from simplecadapi.scene.preview import compile_preview

    with scad.GraphSession():
        box = _top(scad.make_box_rsolid(40.0, 10.0, 10.0))
        grooved = scad.cut_rsolid(box, scad.make_box_rsolid(2.0, 20.0, 4.0, bottom_face_center=(0.0, 0.0, 8.0)))
        part = scad.make_part_rpart(part_id="grooved", body=grooved)
    [row] = scene_tag_splits(compile_preview(part))
    assert row["into"] == ["mount.top.split1", "mount.top.split2"]
    assert sorted(p["piece"] for p in row["pieces"]) == [0, 1]
    assert all(p["entity_id"].startswith("entity/grooved/face/") for p in row["pieces"])


def test_a_tag_given_to_several_entities_names_a_set_and_keeps_its_pieces():
    with scad.GraphSession():
        profile = scad.make_rectangle_rface(40.0, 10.0)
        solid = scad.extrude_rsolid(profile=profile, direction=(0.0, 0.0, 1.0), distance=10.0, side_faces_tag="ex.side", end_face_tag="ex.end")
        # a slot through the whole bar splits the end face and the two long side faces
        halves = scad.cut_rsolid(solid, scad.make_box_rsolid(2.0, 20.0, 20.0, bottom_face_center=(0.0, 0.0, -5.0)))
        sides = [len(ql.faces().where(ql.tag("ex.side")).resolve(half)) for half in halves]
        assert sides == [3, 3]  # every piece of a side face is still a side face
        assert [_tags(half, "ex.end") for half in halves] == [["ex.end.split1"], ["ex.end.split2"]]
        assert [row["tag"] for row in scad.list_tag_splits(halves[0])] == ["ex.end"]
