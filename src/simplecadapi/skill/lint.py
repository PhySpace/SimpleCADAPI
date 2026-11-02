"""Structure checks for the skill source tree (the contract is docs/skill-design.md).

``lint(project, source_files)`` returns a list of problems; ``skillbuild --check`` fails when it is not empty.
"""

from __future__ import annotations

import posixpath
import re
from collections import deque
from typing import Dict, List, Optional, Set

from .compiler import SkillProject, SourceFile, compile_text

MAX_PAGE_LINES = 300
MAX_ROUTER_LINES = 130
# SKILL.md + the always-read pages + the workflow outline + its Read now files, compiled.
READ_BUDGET_LINES = 1200
ALWAYS_READ = ("references/discipline/core-rules.md", "references/discipline/operating-modes.md")
GENERATED_PREFIXES = ("references/docs/api/", "references/docs/stdlib/", "references/docs/core/")
SECTION_READ_NOW = "## Read now (one parallel batch)"
SECTION_READ_WHEN = "## Read when"
SECTION_UNATTENDED = "## Unattended mode"
PARALLEL_HEADING = "## Reading in parallel"
PARALLEL_MARKER = {
    "claudecode": "one message",
    "zcode": "one message",
    "opencode": "one response",
    "codex": "tail -n +1",
}
TOP_DIRS = ("workflows/", "domains/", "discipline/", "docs/", "inspect/")
TOP_FILES = ("ql-playbook.md", "ql-recipes.md", "SDK_OVERVIEW.md", "scadpkg-format.md", "README.md")

_BACKTICK = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\]\(([^)\s#]+\.md)(?:#[^)]*)?\)")


def _normalise(token: str) -> Optional[str]:
    """A source-relative path for a backticked token that looks like a reference path, else None."""
    token = token.strip()
    if not token.endswith(".md") or any(c in token for c in "<>*{}$ ") or "..." in token:
        return None
    if token.startswith("references/"):
        return token
    if token.startswith(TOP_DIRS) or token in TOP_FILES:
        return "references/" + token
    if token == "SKILL.md":
        return token
    return None


def _refs(page: str, text: str, known: Set[str]) -> Set[str]:
    out: Set[str] = set()
    for token in _BACKTICK.findall(text):
        path = _normalise(token)
        if path:
            out.add(path)
    for target in _LINK.findall(text):
        if "://" in target:
            continue
        joined = posixpath.normpath(posixpath.join(posixpath.dirname(page), target))
        out.add(joined)
    return out


def _table_paths(text: str, heading: str) -> List[str]:
    """Paths in backticks in the table under ``heading``, first column or any column, in order."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return []
    paths: List[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            for token in _BACKTICK.findall(line):
                path = _normalise(token)
                if path:
                    paths.append(path)
    return paths


def _compiled_lines(entry: SourceFile, target: str) -> int:
    text = compile_text(entry.text, target, entry.blocks or [])
    return len(text.splitlines())


def lint(project: SkillProject, files: List[SourceFile]) -> List[str]:
    problems: List[str] = []
    source = {
        "/".join(entry.relative.parts): entry
        for entry in files
        if entry.text is not None and entry.relative.suffix == ".md"
    }
    hand = {
        name: entry
        for name, entry in source.items()
        if not name.startswith(GENERATED_PREFIXES) and name != "references/LICENSE.txt"
    }
    known = set(source)

    # 1. every named path exists; 3. reachability
    graph: Dict[str, Set[str]] = {}
    for name, entry in hand.items():
        refs = _refs(name, entry.text, known)
        graph[name] = {r for r in refs if not r.startswith(GENERATED_PREFIXES)}
        for ref in sorted(refs):
            if ref in known or ref.startswith(GENERATED_PREFIXES) or ref.endswith("/"):
                continue
            problems.append(f"{name}: names {ref}, which does not exist")
    if "SKILL.md" in hand:
        seen = {"SKILL.md"}
        queue = deque(["SKILL.md"])
        while queue:
            for nxt in graph.get(queue.popleft(), ()):
                if nxt in hand and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        for name in sorted(set(hand) - seen):
            problems.append(f"{name}: not reachable from SKILL.md")
    else:
        problems.append("SKILL.md is missing")

    # 4. line limits
    for name, entry in hand.items():
        if "\nContract ID:" in "\n".join(entry.text.splitlines()[:6]):
            continue  # a versioned run contract is read whole by an external harness, not routed
        limit = MAX_ROUTER_LINES if name == "SKILL.md" else MAX_PAGE_LINES
        count = len(entry.text.splitlines())
        if count > limit:
            problems.append(f"{name}: {count} lines (limit {limit})")

    # 2. README lists every workflow, domain and discipline page
    readme = hand.get("references/README.md")
    listed = readme.text if readme else ""
    for name in sorted(hand):
        if name.startswith(("references/workflows/", "references/domains/", "references/discipline/")):
            short = name[len("references/") :]
            if short not in listed:
                problems.append(f"references/README.md does not list {short}")

    # 5. section and header contracts
    workflows = {
        n: e for n, e in hand.items() if n.startswith("references/workflows/") and n.count("/") == 2
    }
    for name, entry in workflows.items():
        for heading in (SECTION_READ_NOW, SECTION_READ_WHEN, SECTION_UNATTENDED):
            if heading not in entry.text.splitlines():
                problems.append(f"{name}: missing section '{heading}'")
    for name, entry in hand.items():
        if name.startswith(("references/domains/", "references/discipline/")):
            head = "\n".join(entry.text.splitlines()[:8])
            if "**Read when:**" not in head:
                problems.append(f"{name}: no **Read when:** line in the first 8 lines")

    # 6. route table agrees with each workflow's Read now set
    router = hand.get("SKILL.md")
    read_now: Dict[str, List[str]] = {}
    if router:
        for line in router.text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 3:
                continue
            wf = [p for p in (_normalise(t) for t in _BACKTICK.findall(cells[1])) if p]
            if not wf or not wf[0].startswith("references/workflows/"):
                continue
            row = [p for p in (_normalise(t) for t in _BACKTICK.findall(cells[2])) if p]
            read_now[wf[0]] = row
        for name in workflows:
            if name not in read_now:
                problems.append(f"SKILL.md: route table has no row for {name}")
        for name, row in read_now.items():
            entry = workflows.get(name)
            if entry is None:
                continue
            expected = [name] + _table_paths(entry.text, SECTION_READ_NOW)
            if sorted(set(row)) != sorted(set(expected)):
                extra = sorted(set(row) - set(expected))
                lack = sorted(set(expected) - set(row))
                problems.append(
                    f"SKILL.md route for {name} differs from its Read now set (extra {extra}, missing {lack})"
                )

    # 7. read budget, per route and target
    for name, row in read_now.items():
        for target in project.targets:
            batch = ["SKILL.md", *ALWAYS_READ, *row]
            total = 0
            for item in dict.fromkeys(batch):
                entry = source.get(item)
                if entry is not None:
                    total += _compiled_lines(entry, target)
            if total > READ_BUDGET_LINES:
                problems.append(
                    f"{name} on {target}: first batch is {total} compiled lines (budget {READ_BUDGET_LINES})"
                )

    # 8. parallel-read instruction; 9. directives are resolved by compile_text, so check leftovers
    if router:
        for target in project.targets:
            compiled = compile_text(router.text, target, router.blocks or [])
            if PARALLEL_HEADING not in compiled:
                problems.append(f"SKILL.md on {target}: no '{PARALLEL_HEADING}' section")
            marker = PARALLEL_MARKER.get(target)
            if marker and marker not in compiled:
                problems.append(f"SKILL.md on {target}: parallel-read text lacks '{marker}'")
            if "skill:if" in compiled or "skill:endif" in compiled:
                problems.append(f"SKILL.md on {target}: unresolved skill directive")
    return problems


def read_budget_report(project: SkillProject, files: List[SourceFile]) -> List[str]:
    """One line per route and target with the compiled size of its first batch (for reviewers)."""
    source = {"/".join(e.relative.parts): e for e in files if e.text is not None}
    router = source.get("SKILL.md")
    out: List[str] = []
    if router is None:
        return out
    for line in router.text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) < 3:
            continue
        wf = [p for p in (_normalise(t) for t in _BACKTICK.findall(cells[1])) if p]
        if not wf:
            continue
        row = [p for p in (_normalise(t) for t in _BACKTICK.findall(cells[2])) if p]
        for target in project.targets:
            batch = list(dict.fromkeys(["SKILL.md", *ALWAYS_READ, *row]))
            total = sum(_compiled_lines(source[i], target) for i in batch if i in source)
            out.append(f"{wf[0]:60s} {target:10s} {len(batch):2d} files {total:5d} lines")
    return out
