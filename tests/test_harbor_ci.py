import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
agents = importlib.import_module("tools.harbor_ci.agents")
results = importlib.import_module("tools.harbor_ci.results")
run = importlib.import_module("tools.harbor_ci.run")
runtime = importlib.import_module("tools.harbor_ci.runtime")


def _source_tree(root: Path) -> Path:
    for directory in ("src/simplecadapi", "docs/skill"):
        (root / directory).mkdir(parents=True)
    for name in (
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "MANIFEST.in",
        "skillproj.toml",
    ):
        (root / name).write_text(name)
    (root / "src/simplecadapi/__init__.py").write_text("")
    (root / "docs/skill/SKILL.md").write_text("skill")
    return root


def test_runtime_snapshot_is_content_addressed_and_rejects_links(tmp_path):
    source = _source_tree(tmp_path / "source")
    first = runtime.snapshot_source(source, tmp_path / "first")
    second = runtime.snapshot_source(source, tmp_path / "second")
    assert first == second

    (source / "docs/skill/link").symlink_to(source / "README.md")
    with pytest.raises(ValueError):
        runtime.snapshot_source(source, tmp_path / "linked")


def test_runtime_build_identity_includes_agent_and_version():
    first = runtime.runtime_build_digest("source", b"dockerfile", "codex", "0.155.1")
    second = runtime.runtime_build_digest("source", b"dockerfile", "codex", "0.156.0")
    other_agent = runtime.runtime_build_digest(
        "source", b"dockerfile", "future-agent", "0.155.1"
    )
    assert first != second
    assert first != other_agent


def test_agent_config_is_generic_but_only_codex_is_supported():
    agent = agents.resolve_agent("codex", "0.155.1")
    assert agent.harbor_kwargs == ("version=0.155.1",)
    assert agent.docker_build_args == (("CODEX_VERSION", "0.155.1"),)

    with pytest.raises(ValueError, match="unsupported Harbor agent"):
        agents.resolve_agent("future-agent", "1.0.0")


def test_empty_actions_variables_use_defaults(monkeypatch):
    for name in (
        "HARBOR_CI_DATASET",
        "HARBOR_CI_AGENT",
        "HARBOR_CI_AGENT_VERSION",
        "HARBOR_CI_N_CONCURRENT",
        "HARBOR_CI_N_ATTEMPTS",
        "HARBOR_CI_MAX_RETRIES",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(sys, "argv", ["harbor-ci"])

    args = run.parse_args()

    assert args.dataset == run.DEFAULT_DATASET
    assert args.agent == agents.DEFAULT_AGENT
    assert args.agent_version == agents.DEFAULT_AGENT_VERSION
    assert args.n_concurrent == run.DEFAULT_N_CONCURRENT
    assert args.n_attempts == run.DEFAULT_N_ATTEMPTS
    assert args.max_retries == run.DEFAULT_MAX_RETRIES


def test_harbor_job_settings_from_environment_and_cli(monkeypatch):
    monkeypatch.setenv("HARBOR_CI_N_CONCURRENT", "2")
    monkeypatch.setenv("HARBOR_CI_N_ATTEMPTS", "3")
    monkeypatch.setenv("HARBOR_CI_MAX_RETRIES", "4")
    monkeypatch.setattr(sys, "argv", ["harbor-ci", "--n-concurrent", "5"])

    args = run.parse_args()

    assert (args.n_concurrent, args.n_attempts, args.max_retries) == (5, 3, 4)


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--n-concurrent", "0"),
        ("--n-attempts", "0"),
        ("--max-retries", "-1"),
        ("--n-concurrent", "abc"),
    ],
)
def test_harbor_job_settings_reject_invalid_values(monkeypatch, flag, value):
    monkeypatch.setattr(sys, "argv", ["harbor-ci", flag, value])
    with pytest.raises(SystemExit, match="2"):
        run.parse_args()


def test_invalid_actions_job_setting_fails_before_run(monkeypatch):
    monkeypatch.setenv("HARBOR_CI_N_ATTEMPTS", "0")
    monkeypatch.setattr(sys, "argv", ["harbor-ci"])
    with pytest.raises(SystemExit, match="2"):
        run.parse_args()


def test_harbor_job_settings_reach_command_and_report(monkeypatch, tmp_path):
    monkeypatch.setenv("BENCH_MODEL", "test-model")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harbor-ci",
            "--n-concurrent",
            "2",
            "--n-attempts",
            "3",
            "--max-retries",
            "4",
            "--output-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(run, "git_identity", lambda _: ("a" * 40, False))
    monkeypatch.setattr(
        run,
        "build_runtime",
        lambda *_args, **_kwargs: {
            "image": "test-image",
            "image_id": "test-id",
            "source_sha256": "source",
            "build_sha256": "build",
        },
    )
    commands = []

    def fake_subprocess(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run.subprocess, "run", fake_subprocess)
    reports = []
    monkeypatch.setattr(
        run,
        "summarize",
        lambda _path, metadata: {"overall": "PASS", "metadata": metadata},
    )

    def fake_write_reports(report, report_dir):
        reports.append(report)
        (report_dir / "summary.md").write_text("PASS\n")

    monkeypatch.setattr(run, "write_reports", fake_write_reports)

    assert run.main() == 0
    command = commands[0]
    assert command[command.index("--n-concurrent") + 1] == "2"
    assert command[command.index("--n-attempts") + 1] == "3"
    assert command[command.index("--max-retries") + 1] == "4"
    assert reports[0]["metadata"]["n_concurrent"] == 2
    assert reports[0]["metadata"]["n_attempts"] == 3
    assert reports[0]["metadata"]["max_retries"] == 4


def test_agent_version_cannot_be_overridden_by_agent_kwarg():
    agent = agents.resolve_agent("codex", "0.155.1")
    assert run.agent_kwargs(["reasoning_effort=high"], agent) == [
        "reasoning_effort=high",
        "version=0.155.1",
    ]
    with pytest.raises(ValueError, match="managed by --agent-version"):
        run.agent_kwargs(["version=latest"], agent)


def test_result_summary_reads_native_trial_directories(tmp_path):
    job = tmp_path / "job"
    trial = job / "trial-one"
    trial.mkdir(parents=True)
    (job / "result.json").write_text(json.dumps({"n_total_trials": 1}))
    (trial / "result.json").write_text(
        json.dumps(
            {
                "task_name": "example/task",
                "trial_name": "trial-one",
                "exception_info": None,
                "verifier_result": {"rewards": {"reward": 1.0}},
            }
        )
    )
    report = results.summarize(job, {"dataset": "example@1.0"})
    assert report["overall"] == "PASS"
    assert report["trials"][0]["status"] == "PASS"


def test_result_summary_distinguishes_failure_and_error(tmp_path):
    job = tmp_path / "job"
    trial = job / "trial-one"
    trial.mkdir(parents=True)
    (job / "result.json").write_text(json.dumps({"n_total_trials": 1}))
    result = {
        "task_name": "example/task",
        "trial_name": "trial-one",
        "exception_info": None,
        "verifier_result": {"rewards": {"reward": 0.0}},
    }
    (trial / "result.json").write_text(json.dumps(result))
    assert results.summarize(job, {})["overall"] == "FAIL"

    verifier = trial / "verifier"
    verifier.mkdir()
    (verifier / "status.json").write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "artifact.required",
                        "gating": True,
                        "passed": False,
                        "actual": {"reason": "missing model.step"},
                    }
                ]
            }
        )
    )
    report = results.summarize(job, {})
    assert report["trials"][0]["failed_checks"] == [
        {
            "id": "artifact.required",
            "gating": True,
            "detail": "missing model.step",
        }
    ]
    results.write_reports(report, tmp_path / "reports")
    summary = (tmp_path / "reports" / "summary.md").read_text()
    assert "failed `artifact.required` (gating): missing model.step" in summary

    result["exception_info"] = {"exception_type": "RuntimeError"}
    (trial / "result.json").write_text(json.dumps(result))
    assert results.summarize(job, {})["overall"] == "ERROR"


@pytest.mark.parametrize("reward", [True, float("nan"), float("inf"), -0.1, 1.1])
def test_result_summary_rejects_malformed_binary_rewards(tmp_path, reward):
    job = tmp_path / "job"
    trial = job / "trial-one"
    trial.mkdir(parents=True)
    (job / "result.json").write_text(json.dumps({"n_total_trials": 1}))
    (trial / "result.json").write_text(
        json.dumps(
            {
                "task_name": "example/task",
                "trial_name": "trial-one",
                "exception_info": None,
                "verifier_result": {"rewards": {"reward": reward}},
            }
        )
    )
    assert results.summarize(job, {})["overall"] == "ERROR"
