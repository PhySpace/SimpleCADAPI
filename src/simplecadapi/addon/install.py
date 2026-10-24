"""Addon fetch, validation, install, update, and removal flows.

Contract highlights (see ``docs/skill/references/domains/addon-development.md``):

* the naming standard is enforced at install: repository name ==
  ``[addon].name`` == SKILL.md frontmatter name;
* ``[runtime].command_prefix`` (optional) is a shell prelude joined in
  front of ``check_cmd`` and every ``sca addon use`` dispatch;
  ``{addon_dir}`` resolves to the installed addon directory, and the
  runtime probe runs against the final installed layout;
* hard failures (descriptor invalid, name mismatch, ``[compat] sca``
  mismatch, platform unsupported, name collision, foreign skill directory)
  abort with a named cause;
* a failing ``check_cmd`` is a loud warning, never an install blocker —
  the runtime can be installed afterwards;
* GitHub addons install from the codeload tarball by default (no git
  binary needed, no ``.git`` to strip, byte-exact files); ``--method
  clone`` is the escape hatch for private repositories.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as _dist_version
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from . import AddonError
from .descriptor import AddonDescriptor, load_descriptor
from .home import ResolvedPaths, require_initialized, runtime_dir_for
from .platforms import PLATFORMS, detect_platform
from .registry import (
    drop_record,
    get_record,
    load_registry,
    now_iso,
    put_record,
    save_registry,
)
from .versions import VersionRange, compare_versions

_GITHUB_SPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
# Local checkouts carry authoring-machine state a published addon never
# needs: virtualenvs (the addon provisions its own inside the addon home)
# and tool caches. Everything else — vendor/ binaries included — ships.
_LOCAL_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".DS_Store",
    ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
)
_CHECK_TIMEOUT_SECONDS = 10.0


def _substitute_placeholders(text: str, addon_dir: Path, runtime_dir: Path) -> str:
    return (
        text
        .replace("{addon_dir}", str(addon_dir))
        .replace("{runtime_dir}", str(runtime_dir))
    )


def effective_command(prefix: str, addon_dir: Path, runtime_dir: Path, cmd: str) -> str:
    """Join a descriptor command prefix with ``cmd`` into one shell line.

    The prefix is a shell prelude (env assignments, PATH edits, `cd`, …)
    and may reference two placeholders: ``{addon_dir}`` (the installed addon
    payload, replaced wholesale on every update) and ``{runtime_dir}`` (the
    addon's private runtime-state directory beside the addon home, created
    at install and never touched by updates). An empty prefix returns
    ``cmd`` unchanged.
    """
    prelude = _substitute_placeholders(prefix, addon_dir, runtime_dir).strip()
    return f"{prelude} {cmd}" if prelude else cmd


def skill_dir_name(addon_name: str) -> str:
    """Install-directory name for an addon skill (``sca-`` marked, no doubling)."""
    return addon_name if addon_name.startswith("sca-") else f"sca-{addon_name}"


def _skill_frontmatter_name(skill_dir: Path) -> str:
    """Read the ``name:`` field from a SKILL.md frontmatter block."""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise AddonError(
            f"{skill_dir / 'SKILL.md'} has no frontmatter block; a skill must "
            "start with '---' delimited YAML carrying at least name and description"
        )
    for line in text.split("\n")[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    raise AddonError(
        f"{skill_dir / 'SKILL.md'} frontmatter has no 'name:' field — the "
        "skill name must match [addon].name in sca-addon.toml"
    )


def _local_repo_identity(path: Path) -> str:
    """Best-available repository identity for a local checkout.

    The basename of the git ``origin`` URL wins (a checkout dir may be
    named anything); without git or a remote, fall back to the directory
    name.
    """
    git = shutil.which("git")
    if git is not None and (path / ".git").exists():
        completed = subprocess.run(
            [git, "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True, text=True,
        )
        if completed.returncode == 0:
            url = completed.stdout.strip().rstrip("/")
            return re.sub(r"\.git$", "", url.rsplit("/", 1)[-1])
    return path.name


def _check_name_consistency(descriptor: AddonDescriptor, source: Source) -> None:
    """Enforce the naming standard: addon name == skill name == repo name."""
    if isinstance(source, GitHubSource):
        repo_identity = source.repo
    else:
        repo_identity = _local_repo_identity(source.path)
    if repo_identity != descriptor.name:
        raise AddonError(
            f"repository name {repo_identity!r} does not match [addon].name "
            f"{descriptor.name!r} — the naming standard requires the repository, "
            "the descriptor, and the skill frontmatter to share one name"
        )


def sca_version() -> str:
    """Version of the installed ``simplecadapi`` distribution."""
    try:
        return _dist_version("simplecadapi")
    except PackageNotFoundError as exc:  # pragma: no cover - dev edge case
        raise AddonError(
            "cannot determine the installed simplecadapi version: the "
            "simplecadapi distribution is not importable in this environment"
        ) from exc


@dataclass(frozen=True)
class GitHubSource:
    kind: str = "github"
    owner: str = ""
    repo: str = ""
    ref: str = "HEAD"

    @property
    def spec(self) -> str:
        base = f"{self.owner}/{self.repo}"
        return base if self.ref == "HEAD" else f"{base}@{self.ref}"

    def url(self) -> str:
        return f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/{self.ref}"


@dataclass(frozen=True)
class LocalSource:
    kind: str = "local"
    path: Path = Path()


Source = GitHubSource | LocalSource


def parse_source(spec: str) -> Source:
    """Classify ``owner/repo[@ref]`` vs a local directory path.

    An existing directory wins over the GitHub shape so a local
    ``examples/foo`` checkout is never mistaken for ``examples/foo`` on
    GitHub; prefix local relative paths with ``./`` when a directory of
    the same shape does not exist yet.
    """
    text = spec.strip()
    if not text:
        raise AddonError("addon source must not be empty")
    if "@" in text:
        base, _, ref = text.partition("@")
        ref = ref.strip()
        if not ref:
            raise AddonError(
                f"invalid source {text!r}: empty @ref (pin a tag, branch, or commit)"
            )
    else:
        base, ref = text, None
    candidate = Path(text).expanduser()
    if candidate.is_dir():
        if ref is not None:
            raise AddonError(
                f"invalid source {text!r}: @ref pinning does not apply to local paths"
            )
        return LocalSource(path=candidate.resolve())
    if _GITHUB_SPEC_RE.match(base):
        owner, _, repo = base.partition("/")
        return GitHubSource(owner=owner, repo=repo, ref=ref or "HEAD")
    raise AddonError(
        f"invalid addon source {text!r}: expected owner/repo[@ref] or an existing "
        f"local directory ({text!r} is neither)"
    )


def source_from_record(record: Mapping[str, Any]) -> Source:
    stored = dict(record.get("source") or {})
    kind = stored.get("kind")
    if kind == "github":
        return GitHubSource(
            owner=str(stored.get("owner", "")),
            repo=str(stored.get("repo", "")),
            ref=str(stored.get("ref", "HEAD")),
        )
    if kind == "local":
        path = Path(str(stored.get("path", "")))
        if not path.is_dir():
            raise AddonError(
                f"addon was installed from {path} but that directory no longer "
                "exists; remove the addon and re-add it from its current location"
            )
        return LocalSource(path=path)
    raise AddonError(f"registry entry has unsupported source kind {kind!r}")


def _safe_extract_tarball(payload: bytes, dest: Path) -> None:
    """Extract a tarball refusing anything but plain files/dirs inside dest."""

    def _relative(name: str) -> Path:
        candidate = PurePosixPath(name)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise AddonError(f"refusing tarball member {name!r}: escapes the extract directory")
        return Path(candidate)

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise AddonError("tarball is empty")
        tops = {member.name.split("/", 1)[0] for member in members}
        if len(tops) != 1:
            raise AddonError(
                f"unexpected tarball layout: expected a single top-level directory, "
                f"found {', '.join(sorted(tops))}"
            )
        for member in members:
            if member.issym() or member.islnk():
                raise AddonError(
                    f"refusing tarball member {member.name!r}: links are not allowed"
                )
            if not (member.isfile() or member.isdir()):
                raise AddonError(
                    f"refusing tarball member {member.name!r}: only regular files "
                    "and directories are allowed"
                )
            remainder = member.name.split("/", 1)
            if len(remainder) == 1:
                continue  # the top-level directory itself
            relative = _relative(remainder[1])
            if member.isdir():
                (dest / relative).mkdir(parents=True, exist_ok=True)
                continue
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:  # pragma: no cover - guarded by isfile above
                raise AddonError(f"tarball member {member.name!r} has no payload")
            with stream, open(target, "wb") as handle:
                shutil.copyfileobj(stream, handle)


def _fetch_github_tarball(source: GitHubSource, dest: Path) -> None:
    request = urllib.request.Request(
        source.url(), headers={"User-Agent": "simplecadapi-sca-addon"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        hint = (
            " (private repository? use --method clone with configured git "
            "credentials)" if exc.code in (403, 404) else ""
        )
        raise AddonError(
            f"cannot fetch {source.url()}: HTTP {exc.code}{hint}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise AddonError(f"cannot fetch {source.url()}: {exc}") from exc
    _safe_extract_tarball(payload, dest)


def _run_git(arguments: list[str], *, cwd: Path | None = None) -> None:
    executable = shutil.which("git")
    if executable is None:
        raise AddonError(
            "git is not on PATH but is required by --method clone; install git "
            "or use the default tarball method"
        )
    completed = subprocess.run(
        [executable, *arguments], cwd=cwd, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise AddonError(
            f"git {' '.join(arguments)} failed with exit code "
            f"{completed.returncode}: {(completed.stderr or '').strip()}"
        )


def _fetch_github_clone(source: GitHubSource, dest: Path) -> None:
    remote = f"https://github.com/{source.owner}/{source.repo}.git"
    _run_git(["clone", "--quiet", remote, str(dest)])
    if source.ref != "HEAD":
        _run_git(["checkout", "--quiet", source.ref], cwd=dest)
    shutil.rmtree(dest / ".git", ignore_errors=True)


def _fetch_local(source: LocalSource, dest: Path) -> None:
    shutil.copytree(source.path, dest, ignore=_LOCAL_IGNORE, dirs_exist_ok=False)


def _fetch(source: Source, dest: Path, *, method: str) -> None:
    if isinstance(source, LocalSource):
        _fetch_local(source, dest)
    elif method == "clone":
        _fetch_github_clone(source, dest)
    else:
        _fetch_github_tarball(source, dest)


def run_check_cmd(cmd: str, *, timeout: float = _CHECK_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run a runtime probe: exit 0 means usable; name the failure otherwise."""
    if sys.platform == "win32":
        argv: str | list[str] = cmd
        shell = True
        launcher = "cmd"
    else:
        argv = ["sh", "-c", cmd]
        shell = False
        launcher = argv[0]
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, shell=shell
        )
    except FileNotFoundError as exc:
        return {
            "passed": False,
            "exit_code": None,
            "output_tail": f"could not launch {launcher!r}: {exc}",
        }
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "exit_code": None,
            "output_tail": f"timed out after {timeout:.0f}s — check_cmd must be fast",
        }
    tail = f"{completed.stdout}\n{completed.stderr}".strip()
    return {
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "output_tail": tail[-600:],
    }


def _resolve_check_cmd(descriptor: AddonDescriptor, host_platform: str) -> str | None:
    if descriptor.check_cmd is None:
        return None
    return descriptor.check_overrides.get(host_platform, descriptor.check_cmd)


def _run_probe(effective: str, host_platform: str, cmd: str) -> dict[str, Any]:
    """Run one runtime probe and stamp it with when/how it ran."""
    check = run_check_cmd(effective)
    check["platform"] = host_platform
    check["cmd"] = cmd
    check["effective_cmd"] = effective
    check["checked_at"] = now_iso()
    return check


def _check_compat(descriptor: AddonDescriptor) -> None:
    installed = sca_version()
    parsed = VersionRange.parse(descriptor.sca_compat)
    if not parsed.matches(installed):
        raise AddonError(
            f"addon {descriptor.name!r} requires simplecadapi {descriptor.sca_compat} "
            f"but this environment has {installed}; upgrade simplecadapi or use a "
            "matching addon release"
        )


def _check_platform(descriptor: AddonDescriptor) -> str:
    host_platform = detect_platform()
    if descriptor.platforms and host_platform not in descriptor.platforms:
        raise AddonError(
            f"addon {descriptor.name!r} does not support {host_platform} "
            f"(declared: {', '.join(descriptor.platforms)}); pick a release for "
            "this platform or skip the install"
        )
    return host_platform


def _validate_skill_dir(repo_root: Path, descriptor: AddonDescriptor) -> Path:
    skill_dir = repo_root / Path(descriptor.skill_path)
    if not skill_dir.is_dir():
        raise AddonError(
            f"[addon].skill_path {descriptor.skill_path!r} does not name a "
            f"directory in the repository (looked for {skill_dir})"
        )
    if not (skill_dir / "SKILL.md").is_file():
        raise AddonError(
            f"skill directory {skill_dir} has no SKILL.md — an addon skill must "
            "be a directory containing SKILL.md"
        )
    skill_name = _skill_frontmatter_name(skill_dir)
    if skill_name != descriptor.name:
        raise AddonError(
            f"{skill_dir / 'SKILL.md'} frontmatter name {skill_name!r} does not "
            f"match [addon].name {descriptor.name!r} — the naming standard "
            "requires the repository, the descriptor, and the skill frontmatter "
            "to share one name"
        )
    return skill_dir


_PAYLOAD_DIRNAME = "payload"


def _stage_fetch(source: Source, home: Path, *, method: str) -> Path:
    """Fetch ``source`` into a fresh staging directory; return the staging root.

    All fetch methods land in ``<staging>/payload`` so the payload can be
    moved into place wholesale on commit.
    """
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=home))
    try:
        _fetch(source, staging / _PAYLOAD_DIRNAME, method=method)
    except AddonError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise AddonError(f"cannot fetch addon into {staging}: {exc}") from exc
    return staging


def _payload(staging: Path) -> Path:
    return staging / _PAYLOAD_DIRNAME


def _commit_install(
    staging: Path, addon_dir: Path, skill_dir: Path, skill_target: Path
) -> None:
    # Copy the skill out first: the payload move below invalidates skill_dir.
    if skill_target.exists():
        shutil.rmtree(skill_target)
    shutil.copytree(skill_dir, skill_target)
    payload = _payload(staging)
    # Legacy compatibility: addons authored before {runtime_dir} provisioned
    # their venv INSIDE the payload and reference it as {addon_dir}/.venv.
    # Keep that venv across the wholesale payload replacement so updating an
    # unmigrated addon does not destroy its provisioned environment.
    legacy_venv = None
    if (addon_dir / ".venv").is_dir():
        legacy_venv = staging.parent / ".legacy-venv"
        shutil.move(str(addon_dir / ".venv"), str(legacy_venv))
    if addon_dir.exists():
        shutil.rmtree(addon_dir)
    payload.replace(addon_dir)
    if legacy_venv is not None:
        shutil.move(str(legacy_venv), str(addon_dir / ".venv"))
    shutil.rmtree(staging, ignore_errors=True)


def _build_record(
    descriptor: AddonDescriptor,
    source: Source,
    resolved: ResolvedPaths,
    host_platform: str,
    check: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(source, GitHubSource):
        stored_source: dict[str, Any] = {
            "kind": "github",
            "owner": source.owner,
            "repo": source.repo,
            "ref": source.ref,
        }
    else:
        stored_source = {"kind": "local", "path": str(source.path)}
    return {
        "name": descriptor.name,
        "version": descriptor.version,
        "source": stored_source,
        "addon_relpath": descriptor.name,
        "runtime_dir": str(runtime_dir_for(resolved, descriptor.name)),
        "skill_install": {
            "dir_name": skill_dir_name(descriptor.name),
            "skills_dir": str(resolved.skills_dir),
        },
        "platforms": list(descriptor.platforms),
        "runtime": {
            "kind": descriptor.runtime_kind,
            "check_cmd": descriptor.check_cmd,
            "command_prefix": descriptor.command_prefix,
        },
        "runtime_check": dict(check) if check is not None else None,
        "sca_version_at_install": sca_version(),
        "installed_at": now_iso(),
        "checked_platform": host_platform,
    }


def install_addon(
    resolved: ResolvedPaths,
    source: Source,
    *,
    method: str = "tarball",
) -> dict[str, Any]:
    """`sca addon add`: fetch, validate hard gates, install skill + registry."""
    require_initialized(resolved)
    registry = load_registry(resolved.home)
    staging = _stage_fetch(source, resolved.home, method=method)
    try:
        descriptor = load_descriptor(_payload(staging))
        _check_name_consistency(descriptor, source)
        _check_compat(descriptor)
        host_platform = _check_platform(descriptor)
        skill_dir = _validate_skill_dir(_payload(staging), descriptor)
        if get_record(registry, descriptor.name) is not None:
            raise AddonError(
                f"addon {descriptor.name!r} is already installed; use "
                f"`sca addon update {descriptor.name}` to move to a new release"
            )
        skill_target = resolved.skills_dir / skill_dir_name(descriptor.name)
        if skill_target.exists():
            raise AddonError(
                f"skill directory {skill_target} already exists but is not "
                "recorded as an installed addon; refusing to overwrite it — "
                "move it away or rename the addon"
            )
        addon_dir = resolved.home / descriptor.name
        resolved.skills_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir = runtime_dir_for(resolved, descriptor.name)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        _commit_install(staging, addon_dir, skill_dir, skill_target)
        # Probe the FINAL installed layout: placeholders ({addon_dir},
        # {runtime_dir}) only resolve after the payload is in place. A
        # failing probe stays a loud warning, never an install blocker —
        # the runtime can be provisioned afterwards (`sca addon check`
        # re-probes once it is).
        check = None
        cmd = _resolve_check_cmd(descriptor, host_platform)
        if cmd is not None:
            cmd = _substitute_placeholders(cmd, addon_dir, runtime_dir)
            effective = effective_command(descriptor.command_prefix, addon_dir,
                                          runtime_dir, cmd)
            check = _run_probe(effective, host_platform, cmd)
    except AddonError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    put_record(registry, _build_record(descriptor, source, resolved, host_platform, check))
    save_registry(resolved.home, registry)
    report: dict[str, Any] = {
        "action": "add",
        "name": descriptor.name,
        "version": descriptor.version,
        "source": _source_display(source),
        "addon_dir": str(addon_dir),
        "runtime_dir": str(runtime_dir),
        "skill_dir": str(skill_target),
        "runtime_check": check,
    }
    return report


def update_addon(resolved: ResolvedPaths, name: str) -> dict[str, Any]:
    """`sca addon update NAME`: re-fetch the recorded source and re-install."""
    require_initialized(resolved)
    registry = load_registry(resolved.home)
    record = get_record(registry, name)
    if record is None:
        installed = sorted(registry.get("addons", {}))
        listing = ", ".join(installed) if installed else "(none installed)"
        raise AddonError(f"addon {name!r} is not installed; installed: {listing}")
    source = source_from_record(record)
    previous_version = str(record.get("version", "?"))
    staging = _stage_fetch(source, resolved.home, method="tarball")
    try:
        descriptor = load_descriptor(_payload(staging))
        if descriptor.name != name:
            raise AddonError(
                f"update of {name!r} fetched a descriptor naming "
                f"{descriptor.name!r}; the addon was renamed upstream — remove "
                f"it and add {descriptor.name!r} explicitly"
            )
        _check_name_consistency(descriptor, source)
        _check_compat(descriptor)
        host_platform = _check_platform(descriptor)
        skill_dir = _validate_skill_dir(_payload(staging), descriptor)
        skill_install = dict(record.get("skill_install") or {})
        skill_target = (
            Path(str(skill_install.get("skills_dir", resolved.skills_dir)))
            / str(skill_install.get("dir_name", skill_dir_name(name)))
        )
        addon_dir = resolved.home / name
        skill_target.parent.mkdir(parents=True, exist_ok=True)
        runtime_dir = runtime_dir_for(resolved, name)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        _commit_install(staging, addon_dir, skill_dir, skill_target)
        check = None
        cmd = _resolve_check_cmd(descriptor, host_platform)
        if cmd is not None:
            cmd = _substitute_placeholders(cmd, addon_dir, runtime_dir)
            effective = effective_command(descriptor.command_prefix, addon_dir,
                                          runtime_dir, cmd)
            check = _run_probe(effective, host_platform, cmd)
    except AddonError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    new_record = _build_record(descriptor, source, resolved, host_platform, check)
    put_record(registry, new_record)
    save_registry(resolved.home, registry)
    warnings: list[str] = []
    if compare_versions(descriptor.version, previous_version) < 0:
        warnings.append(
            f"update is a downgrade: {previous_version} → {descriptor.version}"
        )
    report: dict[str, Any] = {
        "action": "update",
        "name": name,
        "version": descriptor.version,
        "previous_version": previous_version,
        "source": _source_display(source),
        "addon_dir": str(resolved.home / name),
        "runtime_dir": str(runtime_dir),
        "skill_dir": str(skill_target),
        "runtime_check": check,
        "warnings": warnings,
    }
    return report


def check_addon(resolved: ResolvedPaths, name: str) -> dict[str, Any]:
    """`sca addon check NAME`: re-probe the installed runtime NOW.

    The install/update probe records the state of the machine at that
    moment — often before the runtime was provisioned. This verb re-runs
    the descriptor's check_cmd against the installed layout, refreshes the
    registry record, and returns the result, so "is the runtime usable
    right now?" has an answer that is not a stale cache.
    """
    require_initialized(resolved)
    registry = load_registry(resolved.home)
    record = get_record(registry, name)
    if record is None:
        installed = sorted(registry.get("addons", {}))
        listing = ", ".join(installed) if installed else "(none installed)"
        raise AddonError(f"addon {name!r} is not installed; installed: {listing}")
    addon_dir = resolved.home / str(record.get("addon_relpath", name))
    if not addon_dir.is_dir():
        raise AddonError(
            f"addon directory {addon_dir} is missing from the addon home — "
            f"reinstall with `sca addon update {name}` or `sca addon add`"
        )
    # The installed descriptor is the source of truth: it may have been
    # re-provisioned or edited after install without re-adding.
    descriptor = load_descriptor(addon_dir)
    runtime_dir = Path(str(record.get("runtime_dir") or runtime_dir_for(resolved, name)))
    host_platform = detect_platform()
    cmd = _resolve_check_cmd(descriptor, host_platform)
    if cmd is None:
        return {
            "action": "check",
            "name": name,
            "runtime_dir": str(runtime_dir),
            "runtime_check": None,
        }
    cmd = _substitute_placeholders(cmd, addon_dir, runtime_dir)
    effective = effective_command(descriptor.command_prefix, addon_dir, runtime_dir, cmd)
    check = _run_probe(effective, host_platform, cmd)
    record["runtime_check"] = check
    put_record(registry, record)
    save_registry(resolved.home, registry)
    return {
        "action": "check",
        "name": name,
        "runtime_dir": str(runtime_dir),
        "runtime_check": check,
    }


def check_all_addons(resolved: ResolvedPaths) -> dict[str, Any]:
    """`sca addon check` (no name): re-probe every installed addon."""
    require_initialized(resolved)
    registry = load_registry(resolved.home) if resolved.home.is_dir() else {"addons": {}}
    names = sorted(registry.get("addons", {}))
    if not names:
        raise AddonError("no addons installed; nothing to check")
    return {"action": "check-all", "checked": [check_addon(resolved, n) for n in names]}


def remove_addon(resolved: ResolvedPaths, name: str) -> dict[str, Any]:
    """`sca addon remove NAME`: delete exactly what the registry recorded."""
    require_initialized(resolved)
    registry = load_registry(resolved.home)
    record = get_record(registry, name)
    if record is None:
        installed = sorted(registry.get("addons", {}))
        listing = ", ".join(installed) if installed else "(none installed)"
        raise AddonError(f"addon {name!r} is not installed; installed: {listing}")
    warnings: list[str] = []
    addon_dir = resolved.home / str(record.get("addon_relpath", name))
    if addon_dir.is_dir():
        shutil.rmtree(addon_dir)
    else:
        warnings.append(f"addon directory was already missing: {addon_dir}")
    # Runtime state was provisioned by the user (often an expensive venv);
    # removal deletes it with everything else the registry recorded, and
    # says so, so nothing orphans silently. Records from before the
    # runtime-dir layout carry no path at all — never fall back to "."
    # (Path("") is the CWD, and rmtree-ing it is catastrophic).
    raw_runtime_dir = str(record.get("runtime_dir") or "").strip()
    runtime_dir = Path(raw_runtime_dir) if raw_runtime_dir else None
    removed_runtime = False
    if runtime_dir is not None and runtime_dir.is_dir():
        shutil.rmtree(runtime_dir)
        removed_runtime = True
    elif runtime_dir is not None:
        warnings.append(f"runtime directory was already missing: {runtime_dir}")
    skill_install = dict(record.get("skill_install") or {})
    skill_target = (
        Path(str(skill_install.get("skills_dir", "")))
        / str(skill_install.get("dir_name", skill_dir_name(name)))
        if skill_install.get("skills_dir")
        else None
    )
    if skill_target is not None:
        if skill_target.is_dir():
            shutil.rmtree(skill_target)
        else:
            warnings.append(f"skill directory was already missing: {skill_target}")
    drop_record(registry, name)
    save_registry(resolved.home, registry)
    return {
        "action": "remove",
        "name": name,
        "removed": [
            str(path)
            for path in (addon_dir, runtime_dir if removed_runtime else None, skill_target)
            if path is not None
        ],
        "warnings": warnings,
    }


def list_addons(resolved: ResolvedPaths) -> dict[str, Any]:
    """`sca addon list`: registry contents with on-disk drift marked."""
    require_initialized(resolved)
    registry = load_registry(resolved.home)
    entries: list[dict[str, Any]] = []
    for name in sorted(registry.get("addons", {})):
        record = dict(registry["addons"][name])
        skill_install = dict(record.get("skill_install") or {})
        skill_dir = (
            Path(str(skill_install.get("skills_dir", "")))
            / str(skill_install.get("dir_name", ""))
        )
        drift: list[str] = []
        if not (resolved.home / str(record.get("addon_relpath", name))).is_dir():
            drift.append("addon directory missing from home")
        if skill_install and not skill_dir.is_dir():
            drift.append(f"skill directory missing: {skill_dir}")
        try:
            source_display = _source_display(source_from_record(record))
        except AddonError as exc:
            source_display = "unavailable"
            drift.append(str(exc))
        check = record.get("runtime_check")
        if isinstance(check, dict) and check.get("checked_at"):
            # surface the cache's age so nobody mistakes list output for a
            # fresh probe — `sca addon check NAME` is the refresh verb
            state = ("ok" if check.get("passed") else "FAILED") + \
                f" (cached {check['checked_at']})"
        else:
            state = "-" if check is None else ("ok" if check.get("passed") else "FAILED")
        entries.append(
            {
                "name": name,
                "version": record.get("version"),
                "source": source_display,
                "skill_dir": str(skill_dir) if skill_install else None,
                "runtime_dir": record.get("runtime_dir"),
                "runtime_state": state,
                "runtime_check": check,
                "drift": drift,
            }
        )
    return {"addons": entries}


def _source_display(source: Source) -> str:
    if isinstance(source, GitHubSource):
        return source.spec
    return str(source.path)
