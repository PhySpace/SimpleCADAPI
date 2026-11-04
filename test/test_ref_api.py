"""``scad.ref``: stable references as public API (design-docs/stable-refs-design.md, sections 3.2, 4, 7).

A reference is written as plain keyword data (``scad.ref.face("base", "make_box_rsolid", role="box.top")``), resolves
through the recorded history of the shape it is resolved in, says how it went (ok / split / merged / lost), and is
used as a ``ql`` predicate or as the selection an operation takes.  A split or a lost reference is an error that
carries the candidates, through any operation; a choice is written back into the reference.
"""

from __future__ import annotations

import json
import math
import pickle
import subprocess
import sys
import textwrap

import pytest

import simplecadapi as scad
from simplecadapi import ql


def _top(shape, z=10.0):
    return ql.faces().where(ql.prop("geom.center.z", ">=", z - 1e-6)).where(ql.prop("geom.center.z", "<=", z + 1e-6)).resolve(shape)


def _rim_edges(shape, z=10.0):
    return ql.edges().where(ql.prop("geom.center.z", ">=", z - 1e-6)).where(ql.prop("geom.center.z", "<=", z + 1e-6)).resolve(shape)


TOP = scad.ref.face("base", "make_box_rsolid", role="box.top")


def _tool(namespace: str, make):
    """A tool made in a feature of its own (another cell), on the graph the next session shares."""
    from simplecadapi._glue.session import GraphSession

    with GraphSession(graph_id="refs", namespace=namespace, shared_lineage=True):
        return make()


def _session():
    from simplecadapi._glue.session import GraphSession

    return GraphSession(graph_id="refs", namespace="base", shared_lineage=True)


# ---------------------------------------------------------------------------
# The spelling
# ---------------------------------------------------------------------------


def test_a_reference_reads_as_code_and_parses_back():
    with scad.GraphSession(namespace="base"):
        box = scad.make_box_rsolid(40, 20, 10)
        (top,) = _top(box)
        ref = scad.ref.of(top, box)
        assert repr(ref) == "scad.ref.face('base', 'make_box_rsolid', role='box.top', guard=('PLANE', (0, 0, 10), 800, (0, 0, 1)))"
        assert scad.ref.parse(repr(ref)) == ref
        assert scad.ref.ElementRef.from_dict(json.loads(json.dumps(ref.to_dict()))) == ref
        assert pickle.loads(pickle.dumps(ref)) == ref
        # An edge is named by the two faces it lies between: readable, and found again after booleans.
        rim = scad.ref.of(_rim_edges(box)[0], box)
        assert rim.between is not None and rim.code().startswith("scad.ref.edge('base', 'make_box_rsolid', between=('box.")
        assert scad.ref.parse(rim.code()) == rim
    # The written forms, with every optional field.
    text = "scad.ref.face('hole', 'make_cut_rsolid', topo='face_7', occurrence=1, slot=2, piece=0, digest='ab12', guard=('PLANE', (0, 1.5, 8), 28.96), naming=2)"
    assert scad.ref.parse(text).code() == text
    nested = "scad.ref.edge(between=(scad.ref.face('base', 'make_box_rsolid', role='box.top'), scad.ref.face('bore', 'make_cylinder_rsolid', role='cylinder.side')))"
    assert scad.ref.parse(nested).code() == nested
    kind, refs = scad.ref.parse_selection(__import__("ast").parse("scad.ref.faces(" + text + ", " + repr(TOP) + ")", mode="eval").body)
    assert kind == "face" and refs == [scad.ref.parse(text), TOP]


@pytest.mark.parametrize(
    "text, message",
    [
        ("scad.ref.face('base', 'make_box_rsolid')", "role=, by topo="),
        ("scad.ref.face('base', 'make_box_rsolid', role='box.top', topo='face_1')", "exactly one"),
        ("scad.ref.face('base', 'make_box_rsolid', between=('a', 'b'))", "between= names an edge"),
        ("scad.ref.edge('base', 'make_box_rsolid', role='x', piece=-1)", "piece"),
        ("scad.ref.face('base', 'make_box_rsolid', role=__import__('os').name)", "literal values only"),
        ("scad.ref.face('base', 'make_box_rsolid', role='box.top', guard=('PLANE', (0, 0), 1))", "guard"),
        ("scad.ref.solid('base', 'make_box_rsolid', role='box')", "not a reference"),
    ],
)
def test_a_malformed_reference_is_refused(text, message):
    with pytest.raises(ValueError, match=message):
        scad.ref.parse(text)


# ---------------------------------------------------------------------------
# Statuses: ok, split, merged, lost
# ---------------------------------------------------------------------------


def test_ok_through_a_boolean_as_a_query_predicate_and_an_operation_selection():
    with scad.GraphSession(namespace="base"):
        box = scad.make_box_rsolid(40, 20, 10)
        cut = scad.cut_rsolid(box, scad.make_cylinder_rsolid(3, 30))
        resolution = TOP.resolve(cut)
        assert resolution.status == "ok" and resolution.bodies == [0]
        assert TOP.one(cut).get_area() == pytest.approx(800 - 9 * math.pi)
        (face,) = ql.faces().where(ql.ref(TOP)).exactly(1).resolve(cut)
        assert face == TOP.one(cut)
        # The edges picked on the box are found after the cut through the faces they lie between.
        rims = [scad.ref.of(e, box) for e in _rim_edges(box)]
        rounded = scad.fillet_rsolid(cut, scad.ref.edges(rims), 1.0)
        assert rounded.get_volume() < cut.get_volume()
        assert TOP.one(rounded).get_area() == pytest.approx(38 * 18 - 9 * math.pi, rel=1e-6)
        # The record travels in the selector (to_dict) and with it when pickled.
        selector = scad.ref.faces(TOP)
        assert selector.to_dict()["predicate"]["kind"] == "ref"
        assert pickle.loads(pickle.dumps(selector)) == selector


def test_a_split_is_an_error_with_the_pieces_through_any_operation_and_a_choice_writes_piece():
    slot = _tool("groove", lambda: scad.make_box_rsolid(4, 30, 4, (0, 0, 8)))
    with _session():
        box = scad.make_box_rsolid(40, 20, 10)
        cut = scad.cut_rsolid(box, slot)
        with pytest.raises(scad.ElementRefError) as caught:
            TOP.one(cut)
        assert caught.value.status == "split"
        assert [round(c.center[0], 6) for c in caught.value.candidates] == [-11.0, 11.0]
        # The same error, with its candidates, reaches the caller of a C++ operation that resolved the reference.
        with pytest.raises(scad.ElementRefError) as through:
            scad.shell_rsolid(cut, scad.ref.faces(TOP), 1.0)
        assert through.value.status == "split" and len(through.value.candidates) == 2
        with pytest.raises(scad.ElementRefError):
            ql.faces().where(ql.ref(TOP)).resolve(cut)

        chosen = TOP.choose(1, cut)
        assert chosen.piece == 1 and chosen.code().endswith("role='box.top', piece=1)")
        assert chosen.one(cut).get_center().x == pytest.approx(11.0)
        shelled = scad.shell_rsolid(cut, scad.ref.faces(chosen), 1.0)
        assert shelled.get_volume() < cut.get_volume()


def test_a_coplanar_union_is_merged_and_still_one_face():
    wing = _tool("wing", lambda: scad.make_box_rsolid(20, 20, 10, (25, 0, 0)))
    with _session():
        box = scad.make_box_rsolid(40, 20, 10)
        joined = scad.union_rsolid(box, wing)
        resolution = TOP.resolve(joined)
        assert resolution.status == "merged"
        assert TOP.one(joined).get_area() == pytest.approx(1100.0)


def test_a_lost_reference_offers_look_alikes_and_accepting_one_writes_a_new_reference():
    cutter = _tool("trim", lambda: scad.make_box_rsolid(50, 30, 5, (0, 0, 6)))
    with _session():
        box = scad.make_box_rsolid(40, 20, 10)
        top = scad.ref.of(_top(box)[0], box)  # with its guard
        trimmed = scad.cut_rsolid(box, cutter)
        resolution = top.resolve(trimmed)
        assert resolution.status == "lost" and resolution.reason == "deleted"
        assert resolution.candidates and resolution.candidates[0].center[2] == pytest.approx(6.0)
        described = resolution.describe()
        assert described["status"] == "lost" and described["candidates"][0]["geom_type"] == "PLANE"
        with pytest.raises(scad.ElementRefError) as caught:
            ql.faces().where(ql.ref(top)).resolve(trimmed)
        assert caught.value.status == "lost" and caught.value.candidates
        accepted = top.choose(0, trimmed)
        assert accepted != top
        assert accepted.one(trimmed).get_center().z == pytest.approx(6.0)
        with pytest.raises(ValueError, match="nothing to choose"):
            accepted.choose(0, trimmed)


def test_an_edge_between_faces_that_no_longer_meet_is_lost():
    with scad.GraphSession(namespace="base"):
        box = scad.make_box_rsolid(40, 20, 10)
        rim = scad.ref.of(_rim_edges(box)[0], box)
        rounded = scad.fillet_rsolid(box, scad.ref.edges(rim), 2.0)  # the faces now meet through the fillet patch
        resolution = rim.resolve(rounded)
        assert resolution.status == "lost" and resolution.reason == "not_adjacent"
        assert resolution.candidates  # look-alikes by its guard


def test_a_pick_made_by_a_later_cell_does_not_hide_the_history_of_the_value_it_read():
    # Cell "cup" picks the top of base (recording the pick re-stamps the shared face, SDK_DEFECTS 56); cell "groove"
    # cuts base afterwards: its history names the pick as the parent, and the reference still follows the face.
    from simplecadapi._glue.session import GraphSession

    with GraphSession(graph_id="picks", namespace="base.c1", shared_lineage=True):
        base = scad.make_box_rsolid(40, 20, 10)
    with GraphSession(graph_id="picks", namespace="cup.c2", shared_lineage=True):
        scad.apply_tag_rselection(base, scad.ref.faces(TOP), "lid")
    with GraphSession(graph_id="picks", namespace="groove.c3", shared_lineage=True):
        groove = scad.cut_rsolid(base, scad.make_box_rsolid(4, 30, 4, (0, 0, 8)))
    resolution = TOP.resolve(groove)
    assert resolution.status == "split", (resolution.reason, resolution.lost_at)


def test_multi_body_results_say_which_body():
    saw = _tool("saw", lambda: scad.make_box_rsolid(4, 30, 30, (0, 0, -10)))
    with _session():
        box = scad.make_box_rsolid(40, 20, 10)
        pieces = scad.cut_rsolid_list(box, saw)
        assert len(pieces) == 2
        halves = [TOP.resolve(piece) for piece in pieces]
        assert [r.status for r in halves] == ["ok", "ok"]
        assert all(r.bodies == [0] for r in halves)
        assert sorted(round(TOP.one(piece).get_center().x, 6) for piece in pieces) == [-11.0, 11.0]


def test_a_reference_predicate_needs_a_shape_to_resolve_in():
    with scad.GraphSession(namespace="base"):
        box = scad.make_box_rsolid(40, 20, 10)
        predicate = ql.ref(TOP)
        assert predicate.kind == "ref" and predicate.data["ref"]["role"] == "box.top"
        with pytest.raises(ValueError, match="resolves in one shape"):
            predicate(_top(box)[0])
        with pytest.raises(ValueError, match="takes face references"):
            scad.ref.faces(scad.ref.edge("base", "make_box_rsolid", between=("box.top", "box.front")))


def test_a_feature_cell_namespace_names_the_feature_by_its_slug():
    # A feature cell's key is "<slug>.<code digest>" (runtime/cells.py): references name the slug, so an edit of the
    # cell's code (another key) keeps them.
    from simplecadapi.runtime.cells import cell_keys, feature_of_key

    (key,) = cell_keys(["# ---- feature: base (build) ----\nbase = scad.make_box_rsolid(40, 20, 10)"])
    assert key.startswith("base.c") and feature_of_key(key) == "base"
    for code in ("base = scad.make_box_rsolid(40, 20, 10)", "base = scad.make_box_rsolid(55, 20, 10)"):
        with scad.GraphSession(namespace=cell_keys([f"# ---- feature: base (build) ----\n{code}"])[0]):
            box = scad.make_box_rsolid(40 if "40" in code else 55, 20, 10)
            assert scad.ref.of(_top(box)[0], box, guard=False) == TOP
            assert TOP.one(box).get_area() == pytest.approx(box.get_volume() / 10)


# ---------------------------------------------------------------------------
# Persistence: model JSON replay, the cell cache in a fresh process
# ---------------------------------------------------------------------------


def test_a_model_with_references_replays_from_its_json():
    with scad.GraphSession(namespace="base") as session:
        box = scad.make_box_rsolid(40, 20, 10)
        rims = [scad.ref.of(e, box) for e in _rim_edges(box)]
        cut = scad.cut_rsolid(box, scad.make_cylinder_rsolid(3, 30))
        rounded = scad.fillet_rsolid(cut, scad.ref.edges(rims), 1.0)
        tagged = scad.apply_tag_rselection(rounded, scad.ref.faces(TOP), "mount.face")
        payload = scad.export_model_json(session)
    replayed = scad.replay_model_json(payload)[-1]
    assert replayed.get_volume() == pytest.approx(tagged.get_volume())
    (face,) = ql.faces().where(ql.tag("mount.face")).resolve(replayed)
    assert face.get_area() == pytest.approx(TOP.one(tagged).get_area())


NOTEBOOK = '''\
# /// script
# [tool.simplecadapi]
# id = "refs"
# kind = "part"
# ///
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- feature: base (build) ----
    base = scad.make_box_rsolid(WIDTH, 20.0, 10.0)
    return (base,)


@app.cell
def _(base):
    # ---- feature: bore (subtract) ----
    _tool = scad.make_cylinder_rsolid(3.0, 30.0)
    bore = scad.cut_rsolid(base, _tool)
    return (bore,)


@app.cell
def _(bore):
    # ---- feature: rounded (modifier) ----
    _edges = scad.ref.edges(scad.ref.edge("base", "make_box_rsolid", between=("box.front", "box.top")))
    rounded = scad.fillet_rsolid(solid=bore, edges=_edges, radius=1.0)
    return (rounded,)


@app.cell
def _(rounded):
    # ---- feature: cup (modifier) ----
    top = scad.ref.face("base", "make_box_rsolid", role="box.top")
    cup = scad.apply_tag_rselection(rounded, scad.ref.faces(top), "mount.face")
    return (cup, top)


if __name__ == "__main__":
    app.run()
'''


def test_references_resolve_through_the_cell_cache_in_a_fresh_process(tmp_path):
    path = tmp_path / "refs.py"
    script = textwrap.dedent(
        """
        import json, sys
        import simplecadapi as scad
        from simplecadapi.runtime import run_notebook
        run = run_notebook(sys.argv[1])
        top = run.values["top"]
        print(json.dumps({"statuses": [c.status for c in run.cells], "volume": run.values["cup"].get_volume(),
                          "tagged": [f.get_area() for f in scad.ql.faces().where(scad.ql.tag("mount.face")).resolve(run.values["cup"])],
                          "top": repr(top),
                          "status": top.resolve(run.values["rounded"]).status}))
        """
    )

    def run() -> dict:
        done = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True, timeout=600, cwd=tmp_path)
        assert done.returncode == 0, done.stderr[-2000:]
        return json.loads(done.stdout.strip().splitlines()[-1])

    path.write_text(NOTEBOOK.replace("WIDTH", "40.0"), encoding="utf-8")
    first = run()
    second = run()  # a fresh process: every cell comes from the cache, the references resolve on restored values
    assert "cached" in second["statuses"] and second["statuses"].count("cached") >= 3
    assert second["volume"] == pytest.approx(first["volume"])
    assert second["status"] == "ok" and second["top"] == "scad.ref.face('base', 'make_box_rsolid', role='box.top')"
    assert len(second["tagged"]) == 1 and second["tagged"] == pytest.approx(first["tagged"])
    # An edit of the base cell's code (another key) keeps every reference into it: they name the feature's slug.
    path.write_text(NOTEBOOK.replace("WIDTH", "55.0"), encoding="utf-8")
    edited = run()
    assert edited["status"] == "ok" and edited["volume"] > first["volume"]
