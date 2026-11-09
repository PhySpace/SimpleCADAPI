"""The drawing workflow and exact API pages ship for every dev skill target."""

from dataclasses import replace
from pathlib import Path

import pytest

from simplecadapi.inspect import drawing
from test_skill_build import skillbuild

ROOT = Path(__file__).resolve().parents[1]
PROJECT = skillbuild.load_project(ROOT)


@pytest.mark.parametrize("target", PROJECT.targets)
def test_drawing_workflow_is_complete_in_each_host_build(target, tmp_path):
    sources = skillbuild.collect_source_files(
        PROJECT.source, frozenset(PROJECT.targets), PROJECT.root
    )
    project = replace(
        PROJECT,
        root=tmp_path,
        outputs={name: tmp_path / name for name in PROJECT.targets},
    )
    output = skillbuild.build_target(project, sources, target)
    router = (output / "SKILL.md").read_text(encoding="utf-8")
    assert "references/workflows/drawing-reconstruction.md" in router
    assert "references/domains/addon-development.md" in router
    # the workflow is an outline plus one page per stage (docs/skill-design.md)
    pages = [output / "references/workflows/drawing-reconstruction.md"]
    pages += sorted((output / "references/workflows/drawing-reconstruction").glob("*.md"))
    pages += [output / "references/domains/drawing-inspection-evidence.md"]
    workflow = "\n".join(page.read_text(encoding="utf-8") for page in pages)
    assert "section_checks" in workflow and "measurement_contract" in workflow
    assert "Host binding:" in workflow
    assert "<!-- skill:" not in workflow
    assert (output / "references/domains/drawing-inspection.md").is_file()
    for name in drawing.__all__:
        page = output / "references/docs/api" / f"{name}.md"
        assert page.is_file(), f"{target}: missing {name} API page"
        assert "drawing-inspection namespace" in page.read_text(encoding="utf-8")
