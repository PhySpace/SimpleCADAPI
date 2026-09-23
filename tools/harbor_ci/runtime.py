"""Build a local Harbor runtime from the current CADIR checkout."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .agents import AgentConfig

SOURCE_ITEMS = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "MANIFEST.in",
    "skillproj.toml",
    "src",
    "docs",
)
REQUIRED_SOURCE = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "MANIFEST.in",
    "skillproj.toml",
    "docs/skill/SKILL.md",
)


def _reject_links(path: Path) -> None:
    for root, directories, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in [*directories, *files]:
            candidate = root_path / name
            if candidate.is_symlink():
                raise ValueError(
                    f"CADIR build input must not contain links: {candidate}"
                )


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode())
            digest.update(b"\0")
            digest.update(item.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def runtime_build_digest(
    source_digest: str,
    dockerfile: bytes,
    agent_name: str,
    agent_version: str,
) -> str:
    """Identify every input that changes the benchmark runtime image."""
    return hashlib.sha256(
        source_digest.encode()
        + b"\0"
        + dockerfile
        + b"\0"
        + agent_name.encode()
        + b"\0"
        + agent_version.encode()
    ).hexdigest()


def snapshot_source(source: Path, destination: Path) -> str:
    source = source.resolve(strict=True)
    for relative in REQUIRED_SOURCE:
        candidate = source / relative
        if not candidate.exists() or candidate.is_symlink():
            raise ValueError(f"required CADIR source is missing or linked: {relative}")

    destination.mkdir(parents=True)
    for relative in SOURCE_ITEMS:
        candidate = source / relative
        if not candidate.exists():
            continue
        _reject_links(candidate)
        target = destination / relative
        if candidate.is_dir():
            shutil.copytree(candidate, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)
    return _tree_digest(destination)


def build_runtime(
    repo_root: Path,
    *,
    agent: AgentConfig,
    image_prefix: str = "cadir-ci/runtime",
) -> dict[str, str]:
    repo_root = repo_root.resolve(strict=True)
    dockerfile = repo_root / "tools/harbor_ci" / agent.dockerfile
    if not dockerfile.is_file():
        raise FileNotFoundError(dockerfile)

    with tempfile.TemporaryDirectory(prefix="cadir-harbor-ci-") as temporary:
        context = Path(temporary)
        source_digest = snapshot_source(repo_root, context / "source")
        build_digest = runtime_build_digest(
            source_digest,
            dockerfile.read_bytes(),
            agent.name,
            agent.version,
        )
        image = f"{image_prefix}:{build_digest[:20]}"
        command = ["docker", "build", "-f", str(dockerfile), "-t", image]
        for name, value in agent.docker_build_args:
            command.extend(["--build-arg", f"{name}={value}"])
        command.append(str(context))
        subprocess.run(command, check=True)

    image_id = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "image": image,
        "image_id": image_id,
        "source_sha256": source_digest,
        "build_sha256": build_digest,
    }
