"""Tests for tools/skillbuild.py — conditional skill compilation."""

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "skillbuild.py"
MODULE_SPEC = importlib.util.spec_from_file_location("skillbuild", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")

skillbuild = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules["skillbuild"] = skillbuild
MODULE_SPEC.loader.exec_module(skillbuild)


def make_project(tmp_path, files, targets=("omp", "generic"), outputs=None):
    root = tmp_path / "proj"
    source = root / "skill-src"
    for relative, content in files.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    output_table = outputs or {name: f"out/{name}" for name in targets}
    output_lines = "\n".join(
        f'{name} = "{value}"' for name, value in output_table.items()
    )
    target_list = ", ".join(f'"{name}"' for name in targets)
    (root / "skillproj.toml").write_text(
        f'[skill]\nname = "demo"\nsource = "skill-src"\n\n'
        f"[build]\ntargets = [{target_list}]\n\n"
        f"[build.output]\n{output_lines}\n",
        encoding="utf-8",
    )
    return root


def load(root):
    project = skillbuild.load_project(root)
    files = skillbuild.collect_source_files(
        project.source, frozenset(project.targets), project.root
    )
    return project, files


def build_one(root, target):
    project, files = load(root)
    return project, skillbuild.build_target(project, files, target)


def read(path):
    return path.read_text(encoding="utf-8")


SIMPLE = (
    "# Demo\n"
    "\n"
    "<!-- skill:if omp -->\n"
    "omp-only line\n"
    "<!-- skill:endif -->\n"
    "<!-- skill:if !omp -->\n"
    "other-harness line\n"
    "<!-- skill:endif -->\n"
    "\n"
    "shared line\n"
)


class TestConditionSemantics:
    def test_positive_included_only_for_listed_target(self, tmp_path):
        root = make_project(tmp_path, {"SKILL.md": SIMPLE})
        _, omp = build_one(root, "omp")
        _, generic = build_one(root, "generic")
        assert "omp-only line" in read(omp / "SKILL.md")
        assert "omp-only line" not in read(generic / "SKILL.md")

    def test_negation_selects_complement(self, tmp_path):
        root = make_project(tmp_path, {"SKILL.md": SIMPLE})
        _, omp = build_one(root, "omp")
        _, generic = build_one(root, "generic")
        assert "other-harness line" in read(generic / "SKILL.md")
        assert "other-harness line" not in read(omp / "SKILL.md")

    def test_multi_positive_included_in_both(self, tmp_path):
        content = (
            "<!-- skill:if omp,generic -->\nshared block\n<!-- skill:endif -->\n"
        )
        root = make_project(tmp_path, {"a.md": content})
        _, omp = build_one(root, "omp")
        _, generic = build_one(root, "generic")
        assert "shared block" in read(omp / "a.md")
        assert "shared block" in read(generic / "a.md")

    def test_mixed_positive_and_negation_never_contradictory(self):
        # omp,!omp is rejected at parse time (duplicate name), so mixed
        # expressions always mean "these positives minus these negatives".
        with pytest.raises(skillbuild.SkillBuildError, match="duplicate"):
            skillbuild.Condition.parse(
                "omp,!omp", frozenset({"omp"}), "a.md:1"
            )


class TestOutputShape:
    def test_markers_removed_even_when_block_kept(self, tmp_path):
        root = make_project(tmp_path, {"a.md": SIMPLE})
        _, omp = build_one(root, "omp")
        text = read(omp / "a.md")
        assert "skill:if" not in text
        assert "skill:endif" not in text

    def test_blank_runs_collapse_after_removal(self, tmp_path):
        content = "above\n\n<!-- skill:if generic -->\ninside\n<!-- skill:endif -->\n\nbelow\n"
        root = make_project(tmp_path, {"a.md": content})
        _, omp = build_one(root, "omp")
        assert read(omp / "a.md") == "above\n\nbelow\n"

    def test_files_without_directives_copied_verbatim(self, tmp_path):
        plain = "byte\nidentical\ntext\n"
        root = make_project(tmp_path, {"plain.md": plain, "a.md": SIMPLE})
        project, files = load(root)
        skillbuild.build_target(project, files, "omp")
        assert (project.root / "out/omp/plain.md").read_bytes() == (
            project.source / "plain.md"
        ).read_bytes()

    def test_binary_file_copied_verbatim(self, tmp_path):
        root = make_project(tmp_path, {"a.md": SIMPLE})
        binary = root / "skill-src" / "blob.bin"
        binary.write_bytes(b"\xff\xfe\x00not-utf8")
        project, files = load(root)
        skillbuild.build_target(project, files, "omp")
        copied = project.root / "out/omp/blob.bin"
        assert copied.read_bytes() == b"\xff\xfe\x00not-utf8"

    def test_denied_entries_excluded(self, tmp_path):
        root = make_project(tmp_path, {"a.md": SIMPLE})
        source = root / "skill-src"
        (source / "__pycache__" / "junk.pyc").parent.mkdir(parents=True)
        (source / "__pycache__" / "junk.pyc").write_text("x")
        (source / ".hidden").write_text("x")
        (source / ".DS_Store").write_text("x")
        project, files = load(root)
        output = skillbuild.build_target(project, files, "omp")
        assert not (output / "__pycache__").exists()
        assert not (output / ".hidden").exists()
        assert not (output / ".DS_Store").exists()

    def test_subdirectory_layout_preserved(self, tmp_path):
        root = make_project(tmp_path, {"refs/deep/nested.md": SIMPLE})
        project, files = load(root)
        output = skillbuild.build_target(project, files, "omp")
        assert (output / "refs/deep/nested.md").is_file()


class TestFences:
    def test_directives_inside_fences_are_literal(self, tmp_path):
        content = (
            "# Doc\n"
            "\n"
            "```text\n"
            "<!-- skill:if omp -->\n"
            "example marker\n"
            "<!-- skill:endif -->\n"
            "```\n"
        )
        root = make_project(tmp_path, {"a.md": content})
        _, omp = build_one(root, "omp")
        _, generic = build_one(root, "generic")
        for output in (omp, generic):
            text = read(output / "a.md")
            assert "example marker" in text
            assert "<!-- skill:if omp -->" in text

    def test_fence_inside_block_scopes_correctly(self, tmp_path):
        content = (
            "<!-- skill:if omp -->\n"
            "```python\n"
            "<!-- skill:endif -->\n"
            "```\n"
            "<!-- skill:endif -->\n"
        )
        root = make_project(tmp_path, {"a.md": content})
        _, omp = build_one(root, "omp")
        text = read(omp / "a.md")
        assert "<!-- skill:endif -->" in text  # the fenced one is literal
        assert text.count("skill:endif") == 1


class TestFailLoud:
    def test_unknown_target_name_rejected(self, tmp_path):
        content = "<!-- skill:if opm -->\nx\n<!-- skill:endif -->\n"
        root = make_project(tmp_path, {"a.md": content})
        with pytest.raises(skillbuild.SkillBuildError, match="unknown target 'opm'"):
            load(root)

    def test_unknown_check_runs_even_when_building_single_target(self, tmp_path):
        content = "<!-- skill:if opm -->\nx\n<!-- skill:endif -->\n"
        root = make_project(tmp_path, {"a.md": content})
        project = skillbuild.load_project(root)
        with pytest.raises(skillbuild.SkillBuildError, match="unknown target"):
            skillbuild.collect_source_files(
                project.source, frozenset(project.targets), project.root
            )

    def test_nested_if_rejected(self, tmp_path):
        content = (
            "<!-- skill:if omp -->\n"
            "<!-- skill:if generic -->\n"
            "<!-- skill:endif -->\n"
            "<!-- skill:endif -->\n"
        )
        root = make_project(tmp_path, {"a.md": content})
        with pytest.raises(skillbuild.SkillBuildError, match="nested"):
            load(root)

    def test_stray_endif_rejected(self, tmp_path):
        root = make_project(tmp_path, {"a.md": "<!-- skill:endif -->\n"})
        with pytest.raises(skillbuild.SkillBuildError, match="without matching"):
            load(root)

    def test_unclosed_if_rejected(self, tmp_path):
        root = make_project(tmp_path, {"a.md": "<!-- skill:if omp -->\nx\n"})
        with pytest.raises(skillbuild.SkillBuildError, match="unclosed"):
            load(root)

    def test_endif_with_expression_rejected(self, tmp_path):
        content = "<!-- skill:if omp -->\nx\n<!-- skill:endif omp -->\n"
        root = make_project(tmp_path, {"a.md": content})
        with pytest.raises(skillbuild.SkillBuildError, match="takes no expression"):
            load(root)

    def test_empty_expression_rejected(self, tmp_path):
        content = "<!-- skill:if -->\nx\n<!-- skill:endif -->\n"
        root = make_project(tmp_path, {"a.md": content})
        with pytest.raises(skillbuild.SkillBuildError):
            load(root)

    def test_output_inside_source_rejected(self, tmp_path):
        outputs = {"omp": "skill-src/out", "generic": "out/generic"}
        root = make_project(tmp_path, {"a.md": SIMPLE}, outputs=outputs)
        with pytest.raises(skillbuild.SkillBuildError, match="inside the source"):
            skillbuild.load_project(root)

    def test_output_containing_source_rejected(self, tmp_path):
        outputs = {"omp": ".", "generic": "out/generic"}
        root = make_project(tmp_path, {"a.md": SIMPLE}, outputs=outputs)
        with pytest.raises(skillbuild.SkillBuildError):
            skillbuild.load_project(root)

    def test_shared_output_rejected(self, tmp_path):
        outputs = {"omp": "out/x", "generic": "out/x"}
        root = make_project(tmp_path, {"a.md": SIMPLE}, outputs=outputs)
        with pytest.raises(skillbuild.SkillBuildError, match="share output"):
            skillbuild.load_project(root)

    def test_missing_output_entry_rejected(self, tmp_path):
        root = make_project(tmp_path, {"a.md": SIMPLE})
        config = root / "skillproj.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                'generic = "out/generic"', ""
            ),
            encoding="utf-8",
        )
        with pytest.raises(skillbuild.SkillBuildError, match="missing target 'generic'"):
            skillbuild.load_project(root)

    def test_skill_md_frontmatter_name_mismatch_rejected(self, tmp_path):
        content = "---\nname: wrong-name\n---\n\nbody\n"
        root = make_project(tmp_path, {"SKILL.md": content})
        project, files = load(root)
        with pytest.raises(skillbuild.SkillBuildError, match="frontmatter name"):
            skillbuild.build_target(project, files, "omp")


class TestCli:
    def test_default_builds_all_targets(self, tmp_path, capsys):
        root = make_project(tmp_path, {"a.md": SIMPLE})
        code = skillbuild.main(["--project-root", str(root)])
        assert code == 0
        assert (root / "out/omp/a.md").is_file()
        assert (root / "out/generic/a.md").is_file()
        out = capsys.readouterr().out
        assert "built omp" in out
        assert "built generic" in out

    def test_single_target_flag(self, tmp_path):
        root = make_project(tmp_path, {"a.md": SIMPLE})
        code = skillbuild.main(["--project-root", str(root), "--target", "omp"])
        assert code == 0
        assert (root / "out/omp/a.md").is_file()
        assert not (root / "out/generic").exists()

    def test_unknown_cli_target_rejected(self, tmp_path, capsys):
        root = make_project(tmp_path, {"a.md": SIMPLE})
        code = skillbuild.main(["--project-root", str(root), "--target", "nope"])
        assert code == 1
        assert "unknown --target 'nope'" in capsys.readouterr().err

    def test_check_writes_nothing(self, tmp_path, capsys):
        root = make_project(tmp_path, {"a.md": SIMPLE})
        code = skillbuild.main(["--project-root", str(root), "--check"])
        assert code == 0
        assert "OK:" in capsys.readouterr().out
        assert not (root / "out").exists()

    def test_check_detects_broken_tree(self, tmp_path, capsys):
        root = make_project(tmp_path, {"a.md": "<!-- skill:if omp -->\n"})
        code = skillbuild.main(["--project-root", str(root), "--check"])
        assert code == 1
        assert "unclosed" in capsys.readouterr().err

    def test_project_root_discovered_by_walking_up(self, tmp_path, monkeypatch):
        root = make_project(tmp_path, {"a.md": SIMPLE})
        nested = root / "skill-src" / "sub"
        nested.mkdir(exist_ok=True)
        monkeypatch.chdir(nested)
        assert skillbuild.find_project_root(Path.cwd()) == root.resolve()


def test_live_project_config_builds():
    """The live tree may contain blocks; each target build must resolve them."""
    repo_root = MODULE_PATH.parents[1]
    project = skillbuild.load_project(repo_root)
    files = skillbuild.collect_source_files(
        project.source, frozenset(project.targets), project.root
    )
    assert any(entry.relative == Path("SKILL.md") for entry in files)
    assert any(entry.blocks for entry in files), "live tree should exercise conditional compilation"

    for target in project.targets:
        output = skillbuild.build_target(project, files, target)
        assert output.is_dir()
