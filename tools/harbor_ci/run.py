"""Run the public CADIR benchmark from Harbor Hub on this runner."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .agents import DEFAULT_AGENT, DEFAULT_AGENT_VERSION, AgentConfig, resolve_agent
from .results import summarize, write_reports
from .runtime import build_runtime

DEFAULT_DATASET = "au12321ua/cadir-ci-benchmark"
DEFAULT_N_CONCURRENT = 1
DEFAULT_N_ATTEMPTS = 1
DEFAULT_MAX_RETRIES = 0


def environment_default(name: str, fallback: str) -> str:
    """Treat an unset or empty Actions variable as absent."""
    return os.environ.get(name) or fallback


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return number


def git_identity(repo_root: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return commit, dirty


def endpoint_host(environment: dict[str, str]) -> str | None:
    endpoint = environment.get("OPENAI_BASE_URL") or environment.get("OPENAI_API_BASE")
    if not endpoint:
        return None
    return urlparse(endpoint if "://" in endpoint else f"https://{endpoint}").hostname


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", default=environment_default("HARBOR_CI_DATASET", DEFAULT_DATASET)
    )
    parser.add_argument(
        "--agent", default=environment_default("HARBOR_CI_AGENT", DEFAULT_AGENT)
    )
    parser.add_argument(
        "--agent-version",
        default=environment_default("HARBOR_CI_AGENT_VERSION", DEFAULT_AGENT_VERSION),
    )
    parser.add_argument("--model", default=os.environ.get("BENCH_MODEL"))
    parser.add_argument(
        "--n-concurrent",
        type=positive_int,
        default=environment_default(
            "HARBOR_CI_N_CONCURRENT", str(DEFAULT_N_CONCURRENT)
        ),
        help="Maximum number of trials running at once (default: 1)",
    )
    parser.add_argument(
        "--n-attempts",
        type=positive_int,
        default=environment_default("HARBOR_CI_N_ATTEMPTS", str(DEFAULT_N_ATTEMPTS)),
        help="Number of independent attempts per task (default: 1)",
    )
    parser.add_argument(
        "--max-retries",
        type=nonnegative_int,
        default=environment_default("HARBOR_CI_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)),
        help="Maximum retries after trial exceptions (default: 0)",
    )
    parser.add_argument(
        "--agent-kwarg", action="append", default=[], metavar="KEY=VALUE"
    )
    parser.add_argument("--allow-agent-host", action="append", default=[])
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--job-name")
    parser.add_argument("--output-dir", type=Path, default=Path(".harbor-ci"))
    parser.add_argument("--require-pass", action="store_true")
    parser.add_argument("--cleanup-runtime", action="store_true")
    return parser.parse_args()


def agent_kwargs(items: list[str], agent: AgentConfig) -> list[str]:
    """Validate extra arguments and reserve adapter-owned argument names."""
    validated: list[str] = []
    reserved = {item.partition("=")[0] for item in agent.harbor_kwargs}
    for item in items:
        key, separator, _ = item.partition("=")
        if not separator or not key:
            raise ValueError(f"--agent-kwarg must be KEY=VALUE: {item}")
        if key in reserved:
            raise ValueError(f"--agent-kwarg {key!r} is managed by --agent-version")
        validated.append(item)
    return [*validated, *agent.harbor_kwargs]


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    agent = resolve_agent(args.agent, args.agent_version)
    kwargs = agent_kwargs(args.agent_kwarg, agent)
    if not args.model:
        raise ValueError(f"{agent.name} requires --model or BENCH_MODEL")

    commit, dirty = git_identity(repo_root)
    runtime = build_runtime(repo_root, agent=agent)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_commit = re.sub(r"[^A-Za-z0-9_.-]", "-", commit[:12])
    job_name = args.job_name or f"cadir-ci-{short_commit}-{timestamp}"

    output_dir = args.output_dir.resolve()
    jobs_dir = output_dir / "jobs"
    reports_dir = output_dir / "reports"
    config_dir = output_dir / "configs"
    for directory in (jobs_dir, reports_dir, config_dir):
        directory.mkdir(parents=True, exist_ok=True)

    config_path = config_dir / f"{job_name}.json"
    config_path.write_text(
        json.dumps(
            {
                "environment": {
                    "env": {
                        "CAD_BENCH_AGENT_IMAGE": runtime["image"],
                        "CAD_BENCH_VERIFIER_IMAGE": runtime["image"],
                    }
                }
            },
            indent=2,
        )
        + "\n"
    )

    command = [
        "harbor",
        "run",
        "-c",
        str(config_path),
        "-d",
        args.dataset,
        "-a",
        agent.name,
        "--n-concurrent",
        str(args.n_concurrent),
        "--n-attempts",
        str(args.n_attempts),
        "--max-retries",
        str(args.max_retries),
        "--job-name",
        job_name,
        "--jobs-dir",
        str(jobs_dir),
    ]
    if args.model:
        command.extend(["-m", args.model])

    for item in kwargs:
        command.extend(["--ak", item])

    if args.env_file:
        command.extend(["--env-file", str(args.env_file.resolve())])
    allowed_hosts = list(args.allow_agent_host)
    host = endpoint_host(dict(os.environ))
    if host and host != "api.openai.com" and host not in allowed_hosts:
        allowed_hosts.append(host)
    for host in allowed_hosts:
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            raise ValueError(f"invalid --allow-agent-host: {host}")
        command.extend(["--allow-agent-host", host])

    harbor_exit = subprocess.run(command, cwd=repo_root, check=False).returncode
    metadata = {
        "dataset": args.dataset,
        "cadir_commit": commit,
        "cadir_dirty": dirty,
        "runtime_image": runtime["image"],
        "runtime_image_id": runtime["image_id"],
        "cadir_source_sha256": runtime["source_sha256"],
        "runtime_build_sha256": runtime["build_sha256"],
        "agent": agent.name,
        "agent_version": agent.version,
        "model": args.model,
        "n_concurrent": args.n_concurrent,
        "n_attempts": args.n_attempts,
        "max_retries": args.max_retries,
        "harbor_command_exit": harbor_exit,
    }
    report = summarize(jobs_dir / job_name, metadata)
    write_reports(report, reports_dir)
    summary_path = reports_dir / "summary.md"
    print(f"CADIR benchmark: {report['overall']}")
    print(f"Summary: {summary_path}")
    print(summary_path.read_text(), end="")
    if args.cleanup_runtime:
        subprocess.run(["docker", "image", "rm", runtime["image"]], check=False)

    if report["overall"] == "ERROR":
        return 2
    if report["overall"] == "FAIL" and args.require_pass:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
