"""load_brep_region_rsolid / load_brep_region_rshell against the reference, on the io area's snapshots."""

import base64
import hashlib
import json

import pytest

import simplecadapi._cpp as scad
from io_snippets import SCADBREP_SNIPPET
from ops_geometry_support import parity
from ref import golden


@pytest.fixture(scope="module")
def artifacts():
    return golden("io_scadbrep_reference", SCADBREP_SNIPPET)


def _source(artifacts):
    box, top, cylinder = artifacts["box"], artifacts["box_top"], artifacts["cylinder"]
    return f"""
        import base64, json, os, tempfile
        BOX, BOX_SHA = {box["artifact_b64"]!r}, {box["sha256"]!r}
        TOP, TOP_SHA = {top["artifact_b64"]!r}, {top["sha256"]!r}
        CYLINDER, CYLINDER_SHA = {cylinder["artifact_b64"]!r}, {cylinder["sha256"]!r}
        folder = tempfile.mkdtemp()

        def sidecar(b64, name="region.scadbrep"):
            path = os.path.join(folder, name)
            with open(path, "wb") as handle:
                handle.write(base64.b64decode(b64))
            return path

        def faces_of(shape):
            return shape._iter_faces() if hasattr(shape, "_iter_faces") else shape.faces()

        def provenance(shape):
            return {{
                "region": shape.get_metadata("brep_region"),
                "faces": [face.get_metadata("provenance") for face in faces_of(shape)],
                "face_tags": [sorted(face._list_tags(scope="local")) for face in faces_of(shape)],
            }}
    """


def test_loading_solids(artifacts):
    parity("brep_region_solids", prelude=_source(artifacts), source="""
        box = scad.load_brep_region_rsolid(sidecar(BOX), BOX_SHA)
        cylinder = scad.load_brep_region_rsolid(sidecar(CYLINDER), CYLINDER_SHA, tag_prefix="shaft")
        result = {
            "box": describe(box), "box_provenance": provenance(box),
            "cylinder": describe(cylinder), "cylinder_provenance": provenance(cylinder),
        }
    """)


def test_loading_a_shell(artifacts):
    parity("brep_region_shell", prelude=_source(artifacts), source="""
        shell = scad.load_brep_region_rshell(sidecar(TOP), TOP_SHA, tag_prefix="lid")
        result = {"shell": describe(shell), "provenance": provenance(shell)}
    """)


def test_failures(artifacts):
    parity("brep_region_failures", prelude=_source(artifacts), source="""
        good = sidecar(BOX)
        result = {
            "wrong_hash": failure(lambda: scad.load_brep_region_rsolid(good, "sha256:" + "0" * 64)),
            "shell_as_solid": failure(lambda: scad.load_brep_region_rsolid(sidecar(TOP, "top.scadbrep"), TOP_SHA)),
            "solid_as_shell": failure(lambda: scad.load_brep_region_rshell(good, BOX_SHA)),
            "extension": failure(lambda: scad.load_brep_region_rsolid(sidecar(BOX, "region.step"), BOX_SHA)),
            "colon": failure(lambda: scad.load_brep_region_rsolid(sidecar(BOX, "a:b.scadbrep"), BOX_SHA)),
            "bad_prefix": failure(lambda: scad.load_brep_region_rsolid(good, BOX_SHA, tag_prefix="Bad Prefix")),
        }
        missing = failure(lambda: scad.load_brep_region_rsolid(os.path.join(folder, "none.scadbrep"), BOX_SHA))
        result["missing"] = json.loads(json.dumps(missing).replace(folder, "<dir>"))
    """)


def test_loading_in_a_session_needs_a_relative_path(artifacts, tmp_path, monkeypatch):
    box = artifacts["box"]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "region.scadbrep").write_bytes(base64.b64decode(box["artifact_b64"]))
    with scad.GraphSession() as session:
        solid = scad.load_brep_region_rsolid("region.scadbrep", box["sha256"])
        for locator in (str(tmp_path / "region.scadbrep"), "../region.scadbrep", "dir\\region.scadbrep"):
            with pytest.raises(scad.SimpleCADError) as info:
                scad.load_brep_region_rsolid(locator, box["sha256"])
            assert info.value.operation == "load_brep_region_rsolid"
    (node,) = session.graph.nodes
    assert node.op == "load_brep_region_rsolid"
    assert node.params == {"path": "region.scadbrep", "sha256": box["sha256"], "tag_prefix": None}
    assert solid.get_volume() == pytest.approx(box["volume"])

    # A parameter-free node reruns from its recorded locator.
    assert session.recompute().ok
    assert session.current(solid).get_volume() == pytest.approx(box["volume"])


def test_pathlike_paths_are_accepted(artifacts, tmp_path):
    box = artifacts["box"]
    path = tmp_path / "region.scadbrep"
    path.write_bytes(base64.b64decode(box["artifact_b64"]))
    assert scad.load_brep_region_rsolid(path, box["sha256"]).get_volume() == pytest.approx(box["volume"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == box["sha256"].split(":")[1]
