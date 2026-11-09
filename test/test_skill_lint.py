"""The skill's structure contract (docs/skill-design.md): each rule fails on a tree that breaks it."""

from __future__ import annotations

from pathlib import Path

import pytest

from simplecadapi.skill.compiler import collect_source_files, load_project
from simplecadapi.skill.lint import lint

ROUTER = """---
name: demo
description: demo
---

# Demo

Start with `references/README.md`, `references/discipline/core-rules.md` and
`references/discipline/operating-modes.md`.

## Reading in parallel

<!-- skill:if claudecode,zcode -->
Issue all Read calls of the batch in one message.
<!-- skill:endif -->
<!-- skill:if opencode -->
Issue all read calls of the batch in one response.
<!-- skill:endif -->
<!-- skill:if codex -->
Run `tail -n +1 a.md b.md`.
<!-- skill:endif -->
<!-- skill:if omp,dsh,kimicode -->
Request the whole batch together.
<!-- skill:endif -->

| Goal | Workflow | Read now |
| --- | --- | --- |
| Model a part | `references/workflows/part.md` | `references/workflows/part.md` `references/domains/d.md` |
"""

WORKFLOW = """# Workflow: part

## Read now (one parallel batch)

| File | Why |
| --- | --- |
| `domains/d.md` | the domain |

## Read when

| When | File |
| --- | --- |
| later | `discipline/core-rules.md` |

## Unattended mode

No gate asks a person.
"""

PAGES = {
    "SKILL.md": ROUTER,
    "references/README.md": "workflows/part.md domains/d.md discipline/core-rules.md discipline/operating-modes.md\n",
    "references/workflows/part.md": WORKFLOW,
    "references/domains/d.md": "# D\n\n**Read when:** a part is made.\n",
    "references/discipline/core-rules.md": "# Core\n\n**Read when:** always.\n",
    "references/discipline/operating-modes.md": "# Modes\n\n**Read when:** always.\n",
}
TARGETS = ["claudecode", "zcode", "opencode", "codex", "omp", "dsh", "kimicode"]


def _problems(root: Path, pages: dict) -> list:
    source = root / "docs" / "skill"
    for name, text in pages.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    outputs = "\n".join(f'{t} = "skills/demo-{t}"' for t in TARGETS)
    (root / "skillproj.toml").write_text(
        '[skill]\nname = "demo"\nsource = "docs/skill"\n\n[build]\n'
        f"targets = {TARGETS!r}\n\n[build.output]\n{outputs}\n".replace("'", '"')
    )
    project = load_project(root)
    return lint(project, collect_source_files(project.source, frozenset(project.targets), root))


def test_a_consistent_tree_has_no_problems(tmp_path):
    assert _problems(tmp_path, PAGES) == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda p: p.update({"references/domains/d.md": "# D\n"}), "no **Read when:**"),
        (
            lambda p: p.update({"references/workflows/part.md": WORKFLOW.replace("## Unattended mode", "## Other")}),
            "missing section '## Unattended mode'",
        ),
        (
            lambda p: p.update({"references/workflows/part.md": WORKFLOW + "\nSee `domains/missing.md`.\n"}),
            "does not exist",
        ),
        (
            lambda p: p.update({"references/domains/orphan.md": "# O\n\n**Read when:** never.\n"}),
            "not reachable",
        ),
        (lambda p: p.update({"references/README.md": "workflows/part.md\n"}), "does not list"),
        (
            lambda p: p.update({"references/domains/d.md": "# D\n\n**Read when:** x.\n" + "x\n" * 300}),
            "limit 300",
        ),
        (
            lambda p: p.update({"SKILL.md": ROUTER.replace(" `references/domains/d.md`", "")}),
            "differs from its Read now set",
        ),
        (lambda p: p.update({"SKILL.md": ROUTER.replace("## Reading in parallel", "## Reading")}), "no '## Reading in parallel'"),
        (lambda p: p.update({"SKILL.md": ROUTER.replace("in one message", "together")}), "lacks 'one message'"),
    ],
)
def test_each_rule_fails_on_a_tree_that_breaks_it(tmp_path, mutate, expected):
    pages = dict(PAGES)
    mutate(pages)
    if expected == "not reachable":
        pages["references/README.md"] += "domains/orphan.md\n"
    problems = _problems(tmp_path, pages)
    assert any(expected in p for p in problems), problems


def test_the_first_batch_budget_is_enforced(tmp_path):
    pages = dict(PAGES)
    pages["references/domains/d.md"] = "# D\n\n**Read when:** x.\n" + "x\n" * 294
    pages["references/discipline/core-rules.md"] = "# C\n\n**Read when:** x.\n" + "x\n" * 294
    pages["references/discipline/operating-modes.md"] = "# M\n\n**Read when:** x.\n" + "x\n" * 294
    pages["references/workflows/part.md"] = WORKFLOW + "x\n" * 285
    problems = _problems(tmp_path, pages)
    assert any("first batch is" in p for p in problems), problems


def test_the_real_skill_tree_satisfies_its_contract():
    root = Path(__file__).resolve().parents[1]
    if not (root / "skillproj.toml").exists():
        pytest.skip("not a source checkout")
    project = load_project(root)
    files = collect_source_files(project.source, frozenset(project.targets), root)
    assert lint(project, files) == []
