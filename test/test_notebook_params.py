"""Notebook parameters, features and workspace scanning (read from files)."""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime.config import read_notebook_config
from simplecadapi.runtime.params import (
    apply_saved_params,
    commit_value,
    list_parameters,
    parameters_in_cell,
    read_saved_params,
    write_saved_params,
)
from simplecadapi.runtime.workspace import (
    features_in_cell,
    list_features,
    scan_workspace,
)

HEADER = '# /// script\n# [tool.simplecadapi]\n# id = "{id}"\n# ///\n'


def notebook(id: str, *cells: str) -> str:
    body = "".join(
        f"@app.cell\ndef _():\n{textwrap.indent(textwrap.dedent(c).strip(), '    ')}\n    return\n\n\n"
        for c in cells
    )
    return HEADER.format(id=id) + "import marimo\n\napp = marimo.App()\n\n\n" + body


class ParameterCommentTest(unittest.TestCase):
    def test_header_forms_and_inference(self) -> None:
        for header in ("# ---- params ----", "# ---- params: disc ----"):
            specs = parameters_in_cell(f"{header}\nA = 1.5\nN = 4\nF = True\nS = 'x'\n_t = 3\n")
            self.assertEqual([s.name for s in specs], ["A", "N", "F"])
            self.assertEqual([s.kind for s in specs], ["float", "int", "bool"])
            self.assertEqual([s.control for s in specs], ["number", "number", "toggle"])
        self.assertEqual(parameters_in_cell("# ---- params: disc ----\nA = 1\n")[0].group, "disc")
        self.assertEqual(parameters_in_cell("# ---- params ----\nA = 1\n")[0].group, "")

    def test_plain_constants_outside_a_params_cell_are_not_parameters(self) -> None:
        self.assertEqual(parameters_in_cell("X = 3.0\n"), [])

    def test_ui_comment_makes_a_parameter_anywhere(self) -> None:
        (spec,) = parameters_in_cell('W = 20.0  # ui: slider(10, 40, step=2, unit="mm", label="Width")\n')
        self.assertEqual(
            (spec.control, spec.min, spec.max, spec.step, spec.unit, spec.label),
            ("slider", 10, 40, 2, "mm", "Width"),
        )
        self.assertEqual(spec.issues, ())

    def test_scad_var_carries_unit_and_comment(self) -> None:
        (spec,) = parameters_in_cell(
            '# ---- params ----\nOD = scad.var("od", 100.0, comment="outer", unit="mm")  # ui: slider(50, 200)\n'
        )
        self.assertEqual((spec.declared, spec.unit, spec.comment), ("var", "mm", "outer"))
        self.assertEqual((spec.min, spec.max), (50, 200))

    def test_bad_ui_comments_fall_back_and_say_why(self) -> None:
        cases = {
            "A = 1.0  # ui: slider(5, 1)": "min 5 is above max 1",
            "A = 1.0  # ui: slider()": "slider needs min and max",
            "A = 1.0  # ui: dial(1, 2)": "must be one of",
            "A = 1  # ui: toggle()": "toggle needs a bool",
            "A = True  # ui: slider(1, 2)": "needs a number",
            "A = 1.0  # ui: number(step=0)": "step must be positive",
            "A = 1.0  # ui: number(speed=1)": "unknown ui option",
        }
        for code, message in cases.items():
            (spec,) = parameters_in_cell(code + "\n")
            self.assertTrue(any(message in issue for issue in spec.issues), (code, spec.issues))
            self.assertIn(spec.control, ("number", "toggle"), code)

    def test_list_parameters_reads_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.py"
            path.write_text(
                notebook("m", "# ---- params ----\nW = 20.0  # ui: slider(10, 40)\nFLAG = False"),
                encoding="utf-8",
            )
            specs = list_parameters(path)
            self.assertEqual([s.name for s in specs], ["W", "FLAG"])
            self.assertTrue(specs[0].cell.startswith("c"))


class CommitValueTest(unittest.TestCase):
    CODE = (
        "# ---- params ----\n"
        'W = 20.0  # ui: slider(10, 40)\n'
        "N = 4\n"
        "F = False\n"
        'OD = scad.var("od", 100.0, comment="é", unit="mm")  # 外径\n'
        "T = scad.var(\n    't', 3.0)\n"
    )

    def test_literals_keep_the_rest_of_the_line(self) -> None:
        out = commit_value(self.CODE, "W", 25)
        assert out is not None
        self.assertIn("W = 25.0  # ui: slider(10, 40)", out)
        self.assertIn("N = 7", commit_value(self.CODE, "N", 7.0) or "")
        self.assertIn("F = True", commit_value(self.CODE, "F", True) or "")

    def test_var_default_is_replaced_not_the_name(self) -> None:
        out = commit_value(self.CODE, "OD", 120)
        assert out is not None
        self.assertIn('OD = scad.var("od", 120.0, comment="é", unit="mm")  # 外径', out)

    def test_refuses_what_does_not_fit(self) -> None:
        self.assertIsNone(commit_value(self.CODE, "MISSING", 1))
        self.assertIsNone(commit_value(self.CODE, "F", 1.0))
        self.assertIsNone(commit_value(self.CODE, "W", True))

    def test_a_declaration_spanning_lines_is_edited_where_the_value_is(self) -> None:
        self.assertIn("'t', 4.0)", commit_value(self.CODE, "T", 4.0) or "")


class FeatureHeaderTest(unittest.TestCase):
    def test_header_parts(self) -> None:
        (feature,) = features_in_cell(
            "# ---- feature: base-plate (build, profile=sketch) ----\nx = 1\n", "c1"
        )
        self.assertEqual(
            (feature.slug, feature.role, feature.tags, feature.cell),
            ("base-plate", "build", (("profile", "sketch"),), "c1"),
        )
        (bare,) = features_in_cell("\n# ---- feature: boss ----\n")
        self.assertEqual((bare.slug, bare.role, bare.line), ("boss", "", 2))

    def test_list_features_in_cell_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.py"
            path.write_text(
                notebook("m", "# ---- feature: a (build) ----\na = 1", "# ---- feature: b (add) ----\nb = 2"),
                encoding="utf-8",
            )
            self.assertEqual([f.slug for f in list_features(path)], ["a", "b"])


class SavedParamsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "m.py"
        path.write_text(notebook("m", "# ---- params ----\nW = 1.0"), encoding="utf-8")
        config = read_notebook_config(path)
        assert config is not None
        self.config = config

    def test_round_trip_and_clear(self) -> None:
        self.assertEqual(read_saved_params(self.config), {})
        write_saved_params(self.config, {"W": 2.5, "N": 3, "F": True})
        self.assertEqual(read_saved_params(self.config), {"W": 2.5, "N": 3, "F": True})
        write_saved_params(self.config, {"W": 9.0})
        self.assertEqual(read_saved_params(self.config), {"W": 9.0})
        write_saved_params(self.config, {})
        self.assertEqual(read_saved_params(self.config), {})

    def test_corrupt_file_is_ignored(self) -> None:
        write_saved_params(self.config, {"W": 2.0})
        from simplecadapi.runtime.params import saved_params_file

        saved_params_file(self.config).write_text("{not json", encoding="utf-8")
        self.assertEqual(read_saved_params(self.config), {})

    def test_apply_keeps_type_and_var_declaration(self) -> None:
        var = scad.var("od", 100.0, comment="outer", unit="mm")
        glbls = {"OD": var, "N": 6, "F": False, "S": 1.5, "OTHER": 1.0}
        write_saved_params(self.config, {"OD": 120, "N": 8.0, "F": True, "S": True, "OTHER": 9.0})
        applied = apply_saved_params(self.config, {"OD", "N", "F", "S"}, glbls)
        self.assertEqual(sorted(applied), ["F", "N", "OD"])  # S: a bool for a number is refused
        self.assertEqual(glbls["OD"].default, 120.0)
        self.assertEqual((glbls["OD"].name, glbls["OD"].unit, glbls["OD"].comment),
                         ("od", var.unit, "outer"))
        self.assertEqual((glbls["N"], type(glbls["N"])), (8, int))
        self.assertIs(glbls["F"], True)
        self.assertEqual(glbls["S"], 1.5)
        self.assertEqual(glbls["OTHER"], 1.0)  # not defined by the cell


class ScratchCellTest(unittest.TestCase):
    def test_scratch_cells_are_not_recorded(self) -> None:
        from simplecadapi.runtime.cells import NotebookCells

        cells = NotebookCells(Path("m.py"), [])
        self.assertNotIn("__scratch__", cells)


class WorkspaceScanTest(unittest.TestCase):
    def test_scan_lists_only_simplecad_notebooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "parts").mkdir()
            (root / "parts" / "bar.py").write_text(notebook("bar", "b = 1"), encoding="utf-8")
            (root / "parts" / "dims.py").write_text("X = 1\n", encoding="utf-8")
            (root / "product.py").write_text(
                notebook("product", 'p = scad.use("parts/bar.py", id="a")\np2 = scad.use("parts/gone.py")'),
                encoding="utf-8",
            )
            (root / "__marimo__").mkdir()
            (root / "__marimo__" / "x.py").write_text(notebook("x", "b = 1"), encoding="utf-8")
            (root / "plain.py").write_text("import marimo\n", encoding="utf-8")
            entries = {entry.path: entry for entry in scan_workspace(root)}
            self.assertEqual(sorted(entries), ["parts/bar.py", "product.py"])
            self.assertEqual(entries["parts/bar.py"].kind, "part")
            product = entries["product.py"]
            self.assertEqual(product.kind, "assembly")
            self.assertEqual(product.uses, ("parts/bar.py", "parts/gone.py"))
            json.dumps(product.to_dict())

    def test_examples_are_a_workspace_without_changes(self) -> None:
        examples = Path(__file__).resolve().parents[1] / "examples"
        entries = {entry.path: entry for entry in scan_workspace(examples)}
        link = entries["four_bar_linkage/link_bar.py"]
        self.assertEqual((link.id, link.kind), ("link_bar", "part"))
        assembly = entries["four_bar_linkage/four_bar_linkage.py"]
        self.assertEqual(assembly.kind, "assembly")
        self.assertIn("four_bar_linkage/link_bar.py", assembly.uses)
        names = [spec.name for spec in list_parameters(examples / "flange_plate" / "flange_plate.py")]
        self.assertIn("FLANGE_OD", names)


if __name__ == "__main__":
    unittest.main()


class ModuleParametersTest(unittest.TestCase):
    CODE = (
        "from dataclasses import dataclass\n\n"
        'TAG = "x"\n'
        "WALL = 2.0  # ui: slider(1, 5, step=0.5, unit=\"mm\")\n"
        "TABLE = 3\n\n\n"
        "@dataclass(frozen=True)\n"
        "class Dims:\n"
        "    L: float = 80.0  # arm span\n"
        "    N: int = 4  # ui: slider(2, 8)\n"
        "    name: str = 'a'\n\n"
        "    @property\n"
        "    def r(self) -> float:\n"
        "        return self.L / 2\n\n\n"
        "class Plain:\n"
        "    K: float = 1.0\n"
    )

    def test_dataclass_fields_and_commented_constants_are_parameters(self) -> None:
        from simplecadapi.runtime.params import parameters_in_module

        specs = {spec.name: spec for spec in parameters_in_module(self.CODE)}
        self.assertEqual(sorted(specs), ["Dims.L", "Dims.N", "WALL"])
        self.assertEqual((specs["WALL"].control, specs["WALL"].unit, specs["WALL"].group), ("slider", "mm", "module"))
        self.assertEqual((specs["Dims.N"].kind, specs["Dims.N"].control), ("int", "slider"))
        self.assertEqual(specs["Dims.L"].to_dict()["label"], "L")

    def test_values_are_written_where_they_are_declared(self) -> None:
        from simplecadapi.runtime.params import commit_field_value

        out = commit_field_value(self.CODE, "Dims", "L", 100)
        assert out is not None
        self.assertIn("L: float = 100.0  # arm span", out)
        self.assertIsNone(commit_field_value(self.CODE, "Plain", "K", 2))  # not a dataclass
        self.assertIsNone(commit_field_value(self.CODE, "Dims", "name", 2))
        self.assertIn("WALL = 3.5  # ui:", commit_value(self.CODE, "WALL", 3.5) or "")


class VertexScopeTest(unittest.TestCase):
    def test_vertices_resolve_through_a_solid_and_a_face(self) -> None:
        import simplecadapi as scad

        solid = scad.make_box_rsolid(10.0, 20.0, 30.0)
        self.assertEqual(len(scad.ql.vertices().resolve(solid)), 8)
        face = scad.ql.faces().where(scad.ql.prop("geom.center.z", "<=", 0.01)).exactly(1).resolve(solid)[0]
        self.assertEqual(len(scad.ql.vertices().resolve(face)), 4)
