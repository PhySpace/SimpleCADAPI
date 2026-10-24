""".scadbrep region snapshots: artifacts written by the Python SDK and by this library."""

import base64
import hashlib

import pytest

import simplecadapi._cpp as scad
from simplecadapi._cpp import _native, _testing
from io_snippets import SCADBREP_SNIPPET
from ref import golden
from test_io_support import need_reference, ref_eval

region = _native._brep_region


@pytest.fixture(scope="module")
def reference():
    return golden("io_scadbrep_reference", SCADBREP_SNIPPET)


def write(tmp_path, reference, name):
    path = tmp_path / f"{name}.scadbrep"
    path.write_bytes(base64.b64decode(reference[name]["artifact_b64"]))
    return path


def test_python_written_snapshots_decode(reference):
    for name in ("box", "cylinder"):
        shape, manifest = region.decode_artifact(base64.b64decode(reference[name]["artifact_b64"]), expected_root_kind="solid")
        assert isinstance(shape, scad.Solid)
        assert shape.get_volume() == pytest.approx(reference[name]["volume"], rel=1e-9)
        assert manifest == reference[name]["manifest"]
    shell, manifest = region.decode_artifact(base64.b64decode(reference["box_top"]["artifact_b64"]))
    assert isinstance(shell, scad.Shell)
    assert manifest["region"]["source_face_ids"] == [f"face:{reference['box_top']['face']}"]


def test_read_artifact_pins_the_digest_and_confines_replay(reference, tmp_path):
    path = write(tmp_path, reference, "box")
    digest = reference["box"]["sha256"]
    shape, manifest, actual = region.read_artifact(path, digest, expected_root_kind="solid")
    assert actual == digest and isinstance(shape, scad.Solid)
    assert manifest["profile"].startswith("scadbrep-1-ocp-")
    shape, _, _ = region.read_artifact(path.name, digest.split(":")[1], expected_root_kind="solid", replay_root=tmp_path)
    assert shape.get_volume() == pytest.approx(reference["box"]["volume"])
    with pytest.raises(scad.SimpleCADError, match="SHA-256"):
        region.read_artifact(path, "sha256:" + "0" * 64, expected_root_kind="solid")
    with pytest.raises(scad.SimpleCADError, match="expected solid|contains"):
        region.read_artifact(write(tmp_path, reference, "box_top"), reference["box_top"]["sha256"], expected_root_kind="solid")
    with pytest.raises(scad.SimpleCADError, match="escapes"):
        region.read_artifact("../x.scadbrep", digest, expected_root_kind="solid", replay_root=tmp_path)


def test_a_tampered_snapshot_is_rejected(reference, tmp_path):
    data = bytearray(base64.b64decode(reference["cylinder"]["artifact_b64"]))
    data[-10] ^= 0xFF
    with pytest.raises(scad.SimpleCADError) as info:
        region.decode_artifact(bytes(data))
    assert info.value.operation == "brep_region"


def test_copy_step_region_round_trip(tmp_path):
    scad.export_step(_testing.box(10, 20, 30), tmp_path / "t.step")
    region.copy_step_region_rpath(tmp_path / "t.step", tmp_path / "t.scadbrep")
    data = (tmp_path / "t.scadbrep").read_bytes()
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    shape, manifest, _ = region.read_artifact(tmp_path / "t.scadbrep", digest, expected_root_kind="solid")
    assert shape.get_volume() == pytest.approx(6000.0)
    assert manifest["generator"]["ocp_version"] == region.default_ocp_version()
    assert manifest["source"]["name"] == "t.step"


def test_the_reference_sdk_accepts_our_snapshot(tmp_path):
    need_reference()
    scad.export_step(_testing.box(10, 20, 30), tmp_path / "t.step")
    version = "7.9.3.1"  # the cadquery-ocp wheel the reference SDK runs on
    region.copy_step_region_rpath(tmp_path / "t.step", tmp_path / "t.scadbrep", ocp_version=version)
    digest = "sha256:" + hashlib.sha256((tmp_path / "t.scadbrep").read_bytes()).hexdigest()
    result = ref_eval(
        f"""
        from simplecadapi._internal.brep_region import read_artifact
        shape, manifest, actual = read_artifact({str(tmp_path / "t.scadbrep")!r}, {digest!r}, expected_root_kind="solid")
        result = {{"faces": len(manifest["region"]["source_face_ids"]), "volume": manifest["shape"]["volume"]}}
        """
    )
    assert result["faces"] == 6
    assert result["volume"] == pytest.approx(6000.0)


def test_locator_checks():
    check = region.checked_region_path
    assert check("models/body.scadbrep", True) == "models/body.scadbrep"
    for bad in ("body:hidden.scadbrep", "/abs/body.scadbrep", "../body.scadbrep", "a\\b.scadbrep"):
        with pytest.raises(ValueError):
            check(bad, True)
    with pytest.raises(ValueError, match="must end"):
        check("body.step", False)
