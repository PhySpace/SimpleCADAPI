"""The pure stage-2 boundary and batch input discovery contracts."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools/research/build123dftc"
sys.path.insert(0, str(TOOLS))


def _script(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_translate_writes_reviewable_source_and_sidecars(tmp_path):
    payload = {"schema_version": "1.0", "stem": "box", "b3d_status": "ok",
               "unsupported": [], "steps": [{"id": "base", "op": "box", "inputs": [],
                "parameters": {"length": 10, "width": 8, "height": 4}}],
               "result_refs": ["base"], "b3d_volume": 320,
               "b3d_bbox": [0, 0, 0, 10, 8, 4], "solid_count": 1}
    trace = tmp_path / "box.trace.json"
    trace.write_text(json.dumps(payload))
    stem, source, meta = _script("build123d_to_ftc").translate_trace_file(trace, tmp_path / "out")
    assert stem == "box"
    assert meta["status"] == "ok"
    assert "feature:" in source and "make_box_rsolid" in source
    assert (tmp_path / "out/box.ftc.py").exists()
    assert (tmp_path / "out/box.meta.json").exists()
    assert (tmp_path / "out/box.sketches.json").exists()


@pytest.mark.parametrize("stem", ["../escape", "/absolute", "..", "nested/file"])
def test_trace_cannot_write_outside_output_directory(tmp_path, stem):
    trace = tmp_path / "bad.trace.json"
    trace.write_text(json.dumps({"schema_version": "1.0", "stem": stem, "steps": []}))
    with pytest.raises(ValueError):
        _script("build123d_to_ftc").translate_trace_file(trace, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_future_schema_is_not_silently_reinterpreted(tmp_path):
    trace = tmp_path / "bad.trace.json"
    trace.write_text(json.dumps({"schema_version": "999", "steps": []}))
    with pytest.raises(ValueError, match="schema"):
        _script("build123d_to_ftc").translate_trace_file(trace, tmp_path / "out")


def test_manifest_resolves_only_declared_models(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    for name in ("one.py", "two.py", "extra.py"):
        (models / name).write_text("")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"examples": [{"file": "models/one.py"}, {"file": "models/two.py"}]}))
    actual = _script("build123d_trace").discover_inputs(manifest=manifest)
    assert [p.name for p in actual] == ["one.py", "two.py"]


@pytest.mark.parametrize("timeout", ["nan", "inf", "0", "-1"])
def test_capture_rejects_unbounded_or_invalid_timeouts(timeout):
    with pytest.raises(SystemExit) as error:
        _script("build123d_trace").main(["--input", "unused.py", "--timeout", timeout])
    assert error.value.code == 2


def test_validator_cli_reports_failure_with_nonzero_exit(tmp_path, monkeypatch):
    module = _script("build123d_validate")
    report = {"rows": [{"stem": "broken", "quality": "rejected", "build": "build_error",
                        "reasons": ["build_failed"]}],
              "counts": {"accepted": 0, "partial": 0, "rejected": 1}}
    monkeypatch.setattr(module, "validate_directory", lambda *a, **kw: report)
    output = tmp_path / "report.json"
    assert module.main(["--ftc-dir", str(tmp_path), "--traces-dir", str(tmp_path),
                        "--report", str(output)]) == 1
    assert json.loads(output.read_text())["counts"]["rejected"] == 1


@pytest.mark.parametrize("timeout", ["nan", "inf", "-1", "0"])
def test_validator_cli_rejects_nonfinite_or_nonpositive_timeout(tmp_path, timeout):
    with pytest.raises(SystemExit) as exc:
        _script("build123d_validate").main(["--ftc-dir", str(tmp_path), "--traces-dir", str(tmp_path),
                                            "--timeout", timeout])
    assert exc.value.code == 2
