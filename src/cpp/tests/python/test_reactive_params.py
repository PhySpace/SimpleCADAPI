"""Editor metadata of parameters: the `# ui:` grammar and ParamSpec
(runtime/params.py), held against the reference's parameters_in_cell."""

import pytest

import simplecadapi._cpp as scad
from ref import golden

# (name, kind, default literal, ui description)
CASES = [
    ("W", "float", "20.0", 'slider(10, 40, step=2, unit="mm", label="Width")'),
    ("W", "float", "20.0", "slider(10.5, 40, step=0.5)"),
    ("N", "int", "4", "number(3, 12, step=1)"),
    ("N", "int", "4", "number(min=1, max=9)"),
    ("F", "bool", "True", "toggle()"),
    ("A", "float", "1.0", "slider(5, 1)"),
    ("A", "float", "1.0", "slider()"),
    ("A", "float", "1.0", "slider(1)"),
    ("A", "float", "1.0", "dial(1, 2)"),
    ("A", "int", "1", "toggle()"),
    ("A", "bool", "True", "slider(1, 2)"),
    ("A", "float", "1.0", "number(step=0)"),
    ("A", "float", "1.0", "number(speed=1)"),
    ("A", "float", "1.0", "slider(1,2,3)"),
    ("A", "float", "1.0", "slider(1, x)"),
    ("A", "float", "1.0", "slider(1"),
    ("A", "float", "1.0", "slider"),
    ("A", "float", "1.0", "number(min='a')"),
    ("A", "float", "1.0", "number(unit=3)"),
    ("A", "float", "1.0", "number(label=\"it's\")"),
    ("A", "float", "1.0", "number(min=-5, max=+5.5e1)"),
    ("A", "float", "1.0", "number(min=True)"),
    ("A", "float", "1.0", "slider(3, 2, step=1)"),
]


def _code(name, default, ui):
    return f"{name} = {default}  # ui: {ui}\n"


def test_ui_comments_parse_like_the_reference():
    expected = golden(
        "reactive_param_specs",
        f"""
        from simplecadapi.runtime.params import parameters_in_cell
        result = []
        for name, kind, default, ui in {CASES!r}:
            (spec,) = parameters_in_cell(f"{{name}} = {{default}}  # ui: {{ui}}\\n")
            result.append(spec.to_dict())
        """,
    )
    for (name, kind, default, ui), want in zip(CASES, expected):
        got = scad.make_param_spec(name, kind, eval(default), ui)
        for key in ("name", "kind", "default", "control", "min", "max", "step", "unit", "label", "issues"):
            assert got[key] == want[key], (name, kind, default, ui, key)
        # An int stays an int, a float a float, in what the editor is told.
        for key in ("min", "max", "step"):
            assert type(got[key]) is type(want[key]), (ui, key)


def test_no_ui_comment_follows_the_value():
    assert scad.make_param_spec("A", "float", 1.5)["control"] == "number"
    assert scad.make_param_spec("A", "int", 4)["control"] == "number"
    assert scad.make_param_spec("F", "bool", True)["control"] == "toggle"
    assert scad.make_param_spec("Dims.L", "float", 80.0)["label"] == "L"


def test_parse_ui_comment_reports_its_pieces():
    parsed = scad.parse_ui_comment('slider(10, 40, step=2, unit="mm", label="Width")')
    assert parsed == {"control": "slider", "min": 10, "max": 40, "step": 2, "unit": "mm", "label": "Width", "issues": []}
    assert scad.parse_ui_comment("dial(1)")["issues"] == ["ui comment must be one of ['number', 'slider', 'toggle']: 'dial(1)'"]


def test_var_carries_its_editor_description():
    var = scad.var("od", 100.0, comment="outer", unit="mm", ui="slider(50, 200)")
    spec = var.param_spec()
    assert (spec["declared"], spec["unit"], spec["comment"]) == ("var", "mm", "outer")
    assert (spec["control"], spec["min"], spec["max"]) == ("slider", 50, 200)
    assert spec["label"] == "od" and spec["default"] == 100.0

    by_keyword = scad.var("w", 20.0, control="slider", min=10, max=40, step=2.5, label="Width", group="flange")
    spec = by_keyword.param_spec()
    assert (spec["control"], spec["min"], spec["max"], spec["step"], spec["label"], spec["group"]) == (
        "slider", 10, 40, 2.5, "Width", "flange")

    broken = scad.var("w", 20.0, ui="slider(5, 1)").param_spec()
    assert broken["control"] == "number" and broken["issues"] == ["min 5 is above max 1"]


def test_the_description_is_not_part_of_the_identity():
    plain = scad.var("w", 20.0, unit="mm")
    described = scad.var("w", 20.0, unit="mm", ui="slider(10, 40)")
    assert plain.expr_id == described.expr_id
    assert plain == described
    assert described.with_default(25.0).param_spec()["control"] == "slider"  # kept across an edit
