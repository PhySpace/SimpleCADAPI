#!/usr/bin/env python3
"""Compile a skill tree into per-target harness builds.

The tree layout is the filesystem under the source root configured in
skillproj.toml. This tool adds nothing, moves nothing, and invents no
layout. Its single job is conditional compilation:

    <!-- skill:if omp,!claude -->
    harness-specific text
    <!-- skill:endif -->

A block is included in the build for target T iff T appears as a
positive name and not as a negated name. An expression with only
negations includes every target not negated. There is no else and no
nesting: complementary blocks express else, and a nesting need means
the file should be split.

Fail-loud contract:
  - a block naming a target absent from skillproj.toml fails the build
    (a one-character typo must never silently drop content);
  - unpaired, nested, or malformed directives fail the build;
  - directive-looking lines inside fenced code blocks are literal text;
  - every build asserts the output contains no live directives;
  - output directories must be disjoint from the source tree and must
    not contain the project root.

Usage:
    python tools/skillbuild.py               # build every target
    python tools/skillbuild.py --target omp  # build one target
    python tools/skillbuild.py --check       # validate only, no writes

Archive a build with tar:
    tar -C skills -czf simplecadapi.tar.gz simplecadapi
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "skillproj.toml"
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DIRECTIVE_PATTERN = re.compile(r"^\s*<!--\s*skill:(if|endif)\s*(.*?)\s*-->\s*$")
FENCE_PATTERN = re.compile(r"^\s{0,3}(?:`{3,}|~{3,})")
DENIED_DIR_NAMES = {"__pycache__"}


class SkillBuildError(Exception):
    """A fatal, user-facing build error."""


@dataclass(frozen=True)
class Condition:
    """A parsed skill:if expression: positive names and negated names."""

    positives: tuple[str, ...]
    negatives: tuple[str, ...]

    @classmethod
    def parse(
        cls,
        expression: str,
        targets: "frozenset[str]",
        where: str,
    ) -> "Condition":
        positives: list[str] = []
        negatives: list[str] = []
        seen: set[str] = set()
        for token in expression.split(","):
            token = token.strip()
            if not token:
                raise SkillBuildError(
                    f"{where}: empty name in conditional expression {expression!r}"
                )
            negated = token.startswith("!")
            name = token[1:] if negated else token
            if not NAME_PATTERN.fullmatch(name):
                raise SkillBuildError(f"{where}: invalid target name {name!r}")
            if name not in targets:
                declared = ", ".join(sorted(targets))
                raise SkillBuildError(
                    f"{where}: unknown target {name!r} (declared: {declared})"
                )
            if name in seen:
                raise SkillBuildError(
                    f"{where}: duplicate name {name!r} in expression {expression!r}"
                )
            seen.add(name)
            if negated:
                negatives.append(name)
            else:
                positives.append(name)
        if not positives and not negatives:
            raise SkillBuildError(
                f"{where}: empty conditional expression {expression!r}"
            )
        return Condition(tuple(positives), tuple(negatives))

    def includes(self, target: str) -> bool:
        if target in self.negatives:
            return False
        return not self.positives or target in self.positives

    def describe(self) -> str:
        parts = list(self.positives) + [f"!{name}" for name in self.negatives]
        return ",".join(parts)


@dataclass(frozen=True)
class ConditionalBlock:
    """One if..endif block; start/end are 0-based directive line indices."""

    start: int
    end: int
    condition: Condition


@dataclass(frozen=True)
class SkillProject:
    root: Path
    name: str
    source: Path
    targets: tuple[str, ...]
    outputs: dict
    lint: bool = False  # [lint] enabled = true: --check also enforces the structure contract


@dataclass(frozen=True)
class SourceFile:
    path: Path
    relative: Path
    text: "str | None"  # None -> binary, copied verbatim
    blocks: "list[ConditionalBlock] | None"  # None -> no directives


def find_project_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    raise SkillBuildError(f"no {CONFIG_NAME} found in {start} or any parent")


def load_project(root: Path) -> SkillProject:
    config_path = root / CONFIG_NAME
    if not config_path.is_file():
        raise SkillBuildError(f"missing {CONFIG_NAME} in {root}")
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SkillBuildError(f"{config_path}: {exc}") from exc

    skill = data.get("skill")
    if not isinstance(skill, dict):
        raise SkillBuildError(f"{config_path}: missing [skill] table")
    name = skill.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise SkillBuildError(
            f"{config_path}: [skill] name must be lowercase words joined by single hyphens"
        )
    source_value = skill.get("source")
    if not isinstance(source_value, str) or not source_value:
        raise SkillBuildError(f"{config_path}: [skill] source is required")
    source = (root / source_value).resolve()
    if not source.is_dir():
        raise SkillBuildError(f"{config_path}: source directory not found: {source}")

    build = data.get("build")
    if not isinstance(build, dict):
        raise SkillBuildError(f"{config_path}: missing [build] table")
    targets_value = build.get("targets")
    if not isinstance(targets_value, list) or not targets_value:
        raise SkillBuildError(
            f"{config_path}: [build] targets must be a non-empty list"
        )
    targets = []
    for item in targets_value:
        if not isinstance(item, str) or not NAME_PATTERN.fullmatch(item):
            raise SkillBuildError(f"{config_path}: invalid target name {item!r}")
        if item in targets:
            raise SkillBuildError(f"{config_path}: duplicate target {item!r}")
        targets.append(item)

    outputs_value = build.get("output")
    if not isinstance(outputs_value, dict):
        raise SkillBuildError(f"{config_path}: missing [build.output] table")
    outputs = {}
    for target in targets:
        entry = outputs_value.get(target)
        if not isinstance(entry, str) or not entry:
            raise SkillBuildError(
                f"{config_path}: [build.output] is missing target {target!r}"
            )
        outputs[target] = (root / entry).resolve()

    _validate_output_paths(root.resolve(), source, outputs)
    lint_table = data.get("lint", {})
    lint_on = isinstance(lint_table, dict) and lint_table.get("enabled") is True
    return SkillProject(root.resolve(), name, source, tuple(targets), outputs, lint_on)


def _validate_output_paths(root: Path, source: Path, outputs: dict) -> None:
    seen = {}
    for target, output in outputs.items():
        if output == root or output in root.parents:
            raise SkillBuildError(
                f"output for target {target!r} contains the project root: {output}"
            )
        if output == source or output in source.parents:
            raise SkillBuildError(
                f"output for target {target!r} contains the source tree: {output}"
            )
        if source in output.parents:
            raise SkillBuildError(
                f"output for target {target!r} is inside the source tree: {output}"
            )
        if output in seen:
            raise SkillBuildError(
                f"targets {seen[output]!r} and {target!r} share output {output}"
            )
        seen[output] = target


def _collect_blocks(
    text: str,
    targets: "frozenset[str]",
    where: str,
) -> "list[ConditionalBlock] | None":
    """Fence-aware directive scan; validates structure and target names."""
    lines = text.splitlines()
    blocks: list[ConditionalBlock] = []
    open_block: "tuple[int, Condition] | None" = None
    in_fence = False
    for index, line in enumerate(lines):
        if in_fence:
            if FENCE_PATTERN.match(line):
                in_fence = False
            continue
        if FENCE_PATTERN.match(line):
            in_fence = True
            continue
        match = DIRECTIVE_PATTERN.match(line)
        if match is None:
            continue
        kind, expression = match.group(1), match.group(2)
        location = f"{where}:{index + 1}"
        if kind == "if":
            if open_block is not None:
                raise SkillBuildError(
                    f"{location}: nested skill:if (nesting is not supported; "
                    "split the file)"
                )
            open_block = (index, Condition.parse(expression, targets, location))
        else:
            if expression:
                raise SkillBuildError(
                    f"{location}: skill:endif takes no expression"
                )
            if open_block is None:
                raise SkillBuildError(
                    f"{location}: skill:endif without matching skill:if"
                )
            start, condition = open_block
            blocks.append(ConditionalBlock(start, index, condition))
            open_block = None
    if open_block is not None:
        raise SkillBuildError(
            f"{where}:{open_block[0] + 1}: unclosed skill:if block"
        )
    return blocks or None


def compile_text(text: str, target: str, blocks: "list[ConditionalBlock]") -> str:
    """Resolve directives for one target; blank runs collapse to one line."""
    lines = text.splitlines()
    drop = set()
    for block in blocks:
        drop.add(block.start)
        drop.add(block.end)
        if not block.condition.includes(target):
            drop.update(range(block.start + 1, block.end))
    kept = [
        line for index, line in enumerate(lines) if index not in drop
    ]
    collapsed: list[str] = []
    for line in kept:
        if not line.strip() and collapsed and not collapsed[-1].strip():
            continue
        collapsed.append(line)
    while collapsed and not collapsed[0].strip():
        collapsed.pop(0)
    while collapsed and not collapsed[-1].strip():
        collapsed.pop()
    if not collapsed:
        return ""
    return "\n".join(collapsed) + "\n"


def collect_source_files(
    source: Path,
    targets: "frozenset[str]",
    root: Path,
) -> "list[SourceFile]":
    """Walk the source tree, validating every file's directives."""
    files: list[SourceFile] = []
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(
            name for name in dirnames
            if not name.startswith(".") and name not in DENIED_DIR_NAMES
        )
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            path = Path(dirpath) / filename
            relative = path.relative_to(source)
            where = str(path.relative_to(root))
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                files.append(SourceFile(path, relative, None, None))
                continue
            files.append(
                SourceFile(path, relative, text, _collect_blocks(text, targets, where))
            )
    return files


def _frontmatter_name(text: str) -> "str | None":
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return None


def verify_output(output: Path, project: SkillProject, target: str) -> None:
    """Assert the built tree contains no live directives and a sane SKILL.md."""
    for path in sorted(p for p in output.rglob("*") if p.is_file()):
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        where = f"{path} (target {target!r})"
        blocks = _collect_blocks(text, frozenset(project.targets), where)
        if blocks:
            raise SkillBuildError(
                f"{where}:{blocks[0].start + 1}: directive survived compilation"
            )
    skill_md = output / "SKILL.md"
    if skill_md.is_file():
        declared = _frontmatter_name(skill_md.read_text(encoding="utf-8"))
        if declared is not None and declared != project.name:
            raise SkillBuildError(
                f"target {target!r}: SKILL.md frontmatter name {declared!r} "
                f"does not match [skill] name {project.name!r}"
            )


def build_target(
    project: SkillProject,
    source_files: "list[SourceFile]",
    target: str,
    *,
    quiet: bool = False,
) -> Path:
    output = project.outputs[target]
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    included = 0
    excluded = 0
    for entry in source_files:
        destination = output / entry.relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if entry.text is None or entry.blocks is None:
            shutil.copyfile(entry.path, destination)
            continue
        destination.write_bytes(
            compile_text(entry.text, target, entry.blocks).encode("utf-8")
        )
        for block in entry.blocks:
            if block.condition.includes(target):
                included += 1
            else:
                excluded += 1
    verify_output(output, project, target)
    if not quiet:
        print(
            f"built {target}: {len(source_files)} files -> {output} "
            f"({included + excluded} blocks: {included} kept, {excluded} dropped)"
        )
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="skillbuild",
        description="Compile a skill tree into per-target harness builds",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="project root containing skillproj.toml (default: search upward)",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        help="build only this target (repeatable; default: all)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the tree without writing outputs",
    )
    parser.add_argument(
        "--read-budget",
        action="store_true",
        help="print the compiled size of each route's first read batch and exit",
    )
    args = parser.parse_args(argv)

    try:
        root = args.project_root.resolve() if args.project_root else find_project_root(Path.cwd())
        project = load_project(root)
        source_files = collect_source_files(
            project.source, frozenset(project.targets), project.root
        )
        if args.read_budget:
            from .lint import read_budget_report

            print("\n".join(read_budget_report(project, source_files)))
            return 0
        if args.check:
            from .lint import lint

            problems = lint(project, source_files) if project.lint else []
            if problems:
                for problem in problems:
                    print(f"skill lint: {problem}", file=sys.stderr)
                print(f"error: {len(problems)} skill lint problem(s)", file=sys.stderr)
                return 1
            conditional = sum(1 for entry in source_files if entry.blocks)
            print(
                f"OK: {len(source_files)} files, {conditional} with conditional "
                f"blocks, targets: {', '.join(project.targets)}"
            )
            return 0
        selected = args.target or list(project.targets)
        for target in selected:
            if target not in project.outputs:
                declared = ", ".join(project.targets)
                raise SkillBuildError(
                    f"unknown --target {target!r} (declared: {declared})"
                )
        for target in selected:
            build_target(project, source_files, target)
    except SkillBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
