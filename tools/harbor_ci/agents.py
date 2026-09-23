"""Resolve Harbor agent settings to the runtime-specific implementation."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_AGENT = "codex"
DEFAULT_AGENT_VERSION = "0.155.1"


@dataclass(frozen=True)
class AgentConfig:
    """Validated agent settings used by Harbor and the runtime image build."""

    name: str
    version: str
    dockerfile: str
    docker_build_args: tuple[tuple[str, str], ...]
    harbor_kwargs: tuple[str, ...]


def resolve_agent(name: str, version: str) -> AgentConfig:
    """Return the installed adapter or reject an unsupported agent explicitly."""
    name = name.strip()
    version = version.strip()
    if name != "codex":
        raise ValueError(
            f"unsupported Harbor agent {name!r}; currently supported: {DEFAULT_AGENT}"
        )
    if not version:
        raise ValueError("Codex requires --agent-version or HARBOR_CI_AGENT_VERSION")
    return AgentConfig(
        name=name,
        version=version,
        dockerfile="runtime.Dockerfile",
        docker_build_args=(("CODEX_VERSION", version),),
        harbor_kwargs=(f"version={version}",),
    )
