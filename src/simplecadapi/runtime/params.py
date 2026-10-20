"""Notebook parameters: what an editor can drive, and the values it saved.

A parameter is a top-level variable a cell assigns a literal (or a
``scad.var``), in a cell headed ``# ---- params ----`` (``# ---- params: <group> ----``
to name the group; the feature tree convention's header) or on a
line that carries a ``# ui:`` comment::

    # ---- params: flange ----
    OUTER_D = 100.0  # ui: slider(50, 200, step=1, unit="mm", label="Outer diameter")
    BOLTS = 6        # ui: number(3, 12, step=1)
    CHAMFER = True                       # no comment: a toggle, inferred
    width = scad.var("width", 20.0, unit="mm")  # ui: slider(10, 40)

The comment is optional: without it the control follows the literal
(a number box for numbers, a toggle for booleans).  Controls are
``slider(min, max, step=...)``, ``number(min=, max=, step=...)`` and
``toggle()``, each taking ``unit=`` and ``label=``.  Notebooks written
before this convention (a params cell of plain constants) list their
parameters with no change.

:func:`list_parameters` reads them from the file, without running it.

**Saved values.**  An editor that drives a slider keeps the values in
``params.json`` in the notebook's :func:`~.deps.state_dir`.  The editor's
kernel executor (:mod:`.executor`) applies them as the defining cell
finishes, so the cells that read the variable see the saved value and
marimo's dataflow reruns exactly those.  A saved value replaces a literal
and, for a ``scad.var``, the variable's default (its unit, tolerance and
comment stay).  A headless run (``sca run``, ``run_notebook``, ``use``)
takes only the overrides it is given, never the saved values: the notebook
file stays the one source of truth, and committing a value is an edit of
the file.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from ._marimo import parse_notebook
from .cells import cell_keys
from .config import NotebookConfig
from .deps import state_dir

_GROUP = re.compile(r"^#\s*-{2,}\s*params(?::\s*(.*?))?\s*-*\s*$", re.MULTILINE)
_UI = re.compile(r"#\s*ui:\s*(.+?)\s*$")
_CONTROLS = {"slider", "number", "toggle"}
_UI_KEYS = {"min", "max", "step", "unit", "label"}
_SAVED_SCHEMA = 1


@dataclass(frozen=True)
class ParamSpec:
    """One parameter of a notebook, as declared in its file."""

    name: str
    """The top-level variable."""
    group: str
    """The label of the ``# ---- params: ... ----`` header, or ``""``."""
    cell: str
    """Key of the declaring cell (see :func:`~.cells.cell_keys`)."""
    line: int
    """Line of the assignment within the cell's code, 1-based."""
    kind: str
    """``"float"``, ``"int"`` or ``"bool"``."""
    declared: str
    """``"literal"`` or ``"var"`` (a ``scad.var``)."""
    default: float | int | bool
    control: str
    """``"slider"``, ``"number"`` or ``"toggle"``."""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None
    label: str | None = None
    comment: str | None = None
    issues: tuple[str, ...] = field(default=())
    """Problems with the ``# ui:`` comment; the control fell back."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "group": self.group,
            "cell": self.cell,
            "line": self.line,
            "kind": self.kind,
            "declared": self.declared,
            "default": self.default,
            "control": self.control,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "unit": self.unit,
            "label": self.label or self.name.rsplit(".", 1)[-1],
            "comment": self.comment,
            "issues": list(self.issues),
        }


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_parameters(path: str | Path) -> list[ParamSpec]:
    """Return the parameters declared in the notebook file at *path*.

    The file is parsed, not run, so the answer is available before any cell
    has executed.  Cells that do not parse contribute nothing.
    """

    resolved = Path(path).expanduser().resolve()
    stat = resolved.stat()
    return list(_list_version(resolved, stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=32)
def _list_version(path: Path, _mtime_ns: int, _size: int) -> tuple[ParamSpec, ...]:
    try:
        notebook = parse_notebook(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return ()
    if notebook is None:
        return ()
    cells = list(notebook.cells)
    keys = cell_keys(cell.code for cell in cells)
    specs: list[ParamSpec] = []
    for cell, key in zip(cells, keys):
        specs.extend(parameters_in_cell(cell.code, key))
    return tuple(specs)


def parameters_in_cell(code: str, key: str = "") -> list[ParamSpec]:
    """Return the parameters one cell's *code* declares."""

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    header = _GROUP.search(code)
    comments = _line_comments(code)
    specs: list[ParamSpec] = []
    for statement in tree.body:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            continue
        name = statement.targets[0].id
        if name.startswith("_"):
            continue
        literal = _read_value(statement.value)
        if literal is None:
            continue
        ui = _ui_comment(statement, comments)
        if header is None and ui is None:
            continue  # an ordinary constant, not offered as a parameter
        specs.append(
            _spec(
                name,
                (header.group(1) or "") if header else "",
                key,
                statement.lineno,
                literal,
                ui,
            )
        )
    return specs


@dataclass(frozen=True)
class _Value:
    default: float | int | bool
    declared: str
    unit: str | None = None
    comment: str | None = None


def _read_value(node: ast.expr) -> _Value | None:
    """A literal number or bool, or ``var(name, default, ...)`` of them."""

    literal = _literal(node)
    if literal is not None:
        return _Value(literal, "literal")
    if (
        isinstance(node, ast.Call)
        and _callee(node.func) == "var"
        and _var_default_node(node) is not None
    ):
        default = _literal(_var_default_node(node))
        if default is None or isinstance(default, bool):
            return None
        unit = comment = None
        for keyword in node.keywords:
            if keyword.arg == "unit" and isinstance(keyword.value, ast.Constant):
                unit = keyword.value.value if isinstance(keyword.value.value, str) else None
            if keyword.arg == "comment" and isinstance(keyword.value, ast.Constant):
                comment = keyword.value.value if isinstance(keyword.value.value, str) else None
        if comment is None and len(node.args) >= 3:
            third = node.args[2]
            if isinstance(third, ast.Constant) and isinstance(third.value, str):
                comment = third.value
        return _Value(default, "var", unit, comment)
    return None


def _var_default_node(call: ast.Call) -> ast.expr | None:
    """The default argument of ``var(name, default, ...)``, positional or ``default=``."""

    if len(call.args) >= 2:
        return call.args[1]
    for keyword in call.keywords:
        if keyword.arg == "default":
            return keyword.value
    return None


def _callee(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal(node: ast.expr) -> float | int | bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, float)):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.USub, ast.UAdd))
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
        and not isinstance(node.operand.value, bool)
    ):
        value = node.operand.value
        return -value if isinstance(node.op, ast.USub) else value
    return None


def _line_comments(code: str) -> dict[int, str]:
    comments: dict[int, str] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(code).readline):
            if token.type == tokenize.COMMENT:
                comments[token.start[0]] = token.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return comments


def _ui_comment(statement: ast.Assign, comments: dict[int, str]) -> str | None:
    end = statement.end_lineno or statement.lineno
    for line in range(statement.lineno, end + 1):
        match = _UI.search(comments.get(line, ""))
        if match:
            return match.group(1)
    return None


def _spec(
    name: str,
    group: str,
    cell: str,
    line: int,
    value: _Value,
    ui: str | None,
) -> ParamSpec:
    default = value.default
    kind = "bool" if isinstance(default, bool) else "int" if isinstance(default, int) else "float"
    control = "toggle" if kind == "bool" else "number"
    options: dict[str, Any] = {}
    issues: list[str] = []
    if ui is not None:
        parsed = _parse_ui(ui, issues)
        if parsed is not None:
            requested, options = parsed
            if kind == "bool" and requested != "toggle":
                issues.append(f"{requested} needs a number; {name} is a bool")
            elif kind != "bool" and requested == "toggle":
                issues.append(f"toggle needs a bool; {name} is a number")
            elif requested == "slider" and ("min" not in options or "max" not in options):
                issues.append("slider needs min and max")
            else:
                control = requested
    lower, upper = options.get("min"), options.get("max")
    if lower is not None and upper is not None and lower > upper:
        issues.append(f"min {lower} is above max {upper}")
        lower = upper = None
        control = "number" if kind != "bool" else control
    return ParamSpec(
        name=name,
        group=group,
        cell=cell,
        line=line,
        kind=kind,
        declared=value.declared,
        default=default,
        control=control,
        min=lower,
        max=upper,
        step=options.get("step"),
        unit=options.get("unit", value.unit),
        label=options.get("label"),
        comment=value.comment,
        issues=tuple(issues),
    )


def _parse_ui(text: str, issues: list[str]) -> tuple[str, dict[str, Any]] | None:
    """Parse ``slider(1, 5, step=1, unit="mm")`` into control and options."""

    try:
        call = ast.parse(text, mode="eval").body
    except SyntaxError:
        issues.append(f"cannot parse ui comment {text!r}")
        return None
    if not isinstance(call, ast.Call) or _callee(call.func) not in _CONTROLS:
        issues.append(f"ui comment must be one of {sorted(_CONTROLS)}: {text!r}")
        return None
    control = _callee(call.func)
    assert control is not None
    options: dict[str, Any] = {}
    positional = ("min", "max") if control != "toggle" else ()
    if len(call.args) > len(positional):
        issues.append(f"too many positional arguments for {control}")
        return None
    pairs = [(key, arg) for key, arg in zip(positional, call.args)]
    pairs += [(keyword.arg, keyword.value) for keyword in call.keywords]
    for key, node in pairs:
        if key not in _UI_KEYS:
            issues.append(f"unknown ui option {key!r}")
            return None
        try:
            value = ast.literal_eval(node)
        except (ValueError, SyntaxError):
            issues.append(f"ui option {key} must be a literal")
            return None
        if key in ("min", "max", "step"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                issues.append(f"ui option {key} must be a number")
                return None
        elif not isinstance(value, str):
            issues.append(f"ui option {key} must be a string")
            return None
        options[key] = value
    if options.get("step") is not None and options["step"] <= 0:
        issues.append("step must be positive")
        return None
    return control, options


# ---------------------------------------------------------------------------
# Parameters of a plain module: the fields of its dataclasses
# ---------------------------------------------------------------------------


def list_module_parameters(path: str | Path) -> list[ParamSpec]:
    """Return the parameter fields of the dataclasses in the module at *path*.

    A notebook that imports shared dimensions (``DIMS = ULinkDimensions()``)
    has no parameter cell; the numbers live in the module.  Every field of a
    ``@dataclass`` with a literal default (a number or bool) is a parameter,
    named ``<Class>.<field>``, and so is a top-level constant that carries a
    ``# ui:`` comment (named as itself, group ``module``); the comment picks
    the control exactly as it does in a notebook cell.  Editing a value means
    editing the default in the file (:func:`commit_field_value`,
    :func:`commit_value`).
    """

    resolved = Path(path).expanduser().resolve()
    stat = resolved.stat()
    return list(_module_version(resolved, stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=32)
def _module_version(path: Path, _mtime_ns: int, _size: int) -> tuple[ParamSpec, ...]:
    try:
        return tuple(parameters_in_module(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError):
        return ()


def parameters_in_module(code: str) -> list[ParamSpec]:
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    comments = _line_comments(code)
    specs: list[ParamSpec] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and not node.targets[0].id.startswith("_")
        ):
            # A module constant is a parameter only when it says so (`# ui:`):
            # most are tags and tables, not numbers to tune.
            literal = _read_value(node.value)
            ui = _ui_comment(node, comments)
            if literal is not None and literal.declared == "literal" and ui is not None:
                specs.append(_spec(node.targets[0].id, "module", "", node.lineno, literal, ui))
            continue
        if not (isinstance(node, ast.ClassDef) and _is_dataclass(node)):
            continue
        for statement in node.body:
            if not (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.value is not None
                and not statement.target.id.startswith("_")
            ):
                continue
            literal = _read_value(statement.value)
            if literal is None or literal.declared != "literal":
                continue
            ui = _ui_comment(statement, comments)  # type: ignore[arg-type]
            specs.append(
                _spec(f"{node.name}.{statement.target.id}", node.name, "", statement.lineno, literal, ui)
            )
    return specs


def _is_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _callee(target) == "dataclass":
            return True
    return False


def commit_field_value(code: str, class_name: str, field: str, value: float | int | bool) -> str | None:
    """Return *code* with the default of ``<class_name>.<field>`` set to *value*.

    The literal is replaced in place; the rest of the line (type annotation,
    comments) is kept.  ``None`` if the module has no such dataclass field or
    *value* does not fit its kind.
    """

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == class_name and _is_dataclass(node)):
            continue
        for statement in node.body:
            if not (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.target.id == field
                and statement.value is not None
            ):
                continue
            declared = _read_value(statement.value)
            if declared is None or declared.declared != "literal":
                return None
            text = _format_value(declared.default, value)
            target = statement.value
            if text is None or target.end_lineno != target.lineno:
                return None
            lines = code.splitlines(keepends=True)
            line = lines[target.lineno - 1].encode("utf-8")
            replaced = line[: target.col_offset] + text.encode("utf-8") + line[target.end_col_offset :]
            lines[target.lineno - 1] = replaced.decode("utf-8")
            return "".join(lines)
    return None


# ---------------------------------------------------------------------------
# Saved values
# ---------------------------------------------------------------------------


def saved_params_file(config: NotebookConfig) -> Path:
    return state_dir(config) / "params.json"


def read_saved_params(config: NotebookConfig) -> dict[str, float | int | bool]:
    """Return the values the editor saved for the notebook; none if absent."""

    path = saved_params_file(config)
    try:
        stat = path.stat()
    except OSError:
        return {}
    return dict(_read_saved_version(path, stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=64)
def _read_saved_version(
    path: Path, _mtime_ns: int, _size: int
) -> dict[str, float | int | bool]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != _SAVED_SCHEMA:
        return {}
    values = data.get("values")
    if not isinstance(values, dict):
        return {}
    return {
        name: value
        for name, value in values.items()
        if isinstance(name, str) and isinstance(value, (bool, int, float))
    }


def write_saved_params(
    config: NotebookConfig, values: dict[str, float | int | bool]
) -> None:
    """Replace the saved values; an empty mapping removes the file."""

    path = saved_params_file(config)
    if not values:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": _SAVED_SCHEMA, "values": dict(sorted(values.items()))}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def apply_saved_params(
    config: NotebookConfig, defined: set[str], glbls: dict[str, Any]
) -> list[str]:
    """Replace the variables a cell just defined with their saved values.

    Returns the names replaced.  A saved value of the wrong kind for the
    variable (a number for a bool) is ignored.
    """

    saved = read_saved_params(config)
    applied: list[str] = []
    for name in defined & saved.keys():
        if name not in glbls:
            continue
        replacement = _replace(glbls[name], saved[name])
        if replacement is not _NO_REPLACEMENT:
            glbls[name] = replacement
            applied.append(name)
    return applied


_NO_REPLACEMENT = object()


def _replace(current: Any, saved: float | int | bool) -> Any:
    from ..params.expr import Var

    if isinstance(current, Var):
        if isinstance(saved, bool):
            return _NO_REPLACEMENT
        return replace(current, default=float(saved), expr_id="")
    if isinstance(current, bool):
        return saved if isinstance(saved, bool) else _NO_REPLACEMENT
    if isinstance(saved, bool):
        return _NO_REPLACEMENT
    if isinstance(current, int):
        return int(saved) if float(saved).is_integer() else float(saved)
    if isinstance(current, float):
        return float(saved)
    return _NO_REPLACEMENT


# ---------------------------------------------------------------------------
# Committing a value to the source
# ---------------------------------------------------------------------------


def commit_value(code: str, name: str, value: float | int | bool) -> str | None:
    """Return *code* with the declaration of parameter *name* set to *value*.

    The literal (or the default argument of a ``scad.var``) is replaced in
    place; the rest of the line, a ``# ui:`` comment included, is kept.
    Returns ``None`` if the cell does not declare *name* as a parameter or
    *value* does not fit its kind.
    """

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    for statement in tree.body:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
        ):
            continue
        declared = _read_value(statement.value)
        if declared is None:
            return None
        node = statement.value
        if declared.declared == "var":
            assert isinstance(node, ast.Call)
            node = _var_default_node(node)
            assert node is not None
        text = _format_value(declared.default, value)
        if text is None or node.end_lineno != node.lineno:
            return None
        lines = code.splitlines(keepends=True)
        line = lines[node.lineno - 1].encode("utf-8")
        # ast offsets count UTF-8 bytes.
        replaced = line[: node.col_offset] + text.encode("utf-8") + line[node.end_col_offset :]
        lines[node.lineno - 1] = replaced.decode("utf-8")
        return "".join(lines)
    return None


def _format_value(
    current: float | int | bool, value: float | int | bool
) -> str | None:
    if isinstance(current, bool):
        return repr(value) if isinstance(value, bool) else None
    if isinstance(value, bool):
        return None
    if isinstance(current, int) and float(value).is_integer():
        return str(int(value))
    return repr(float(value))


__all__ = [
    "ParamSpec",
    "apply_saved_params",
    "commit_field_value",
    "commit_value",
    "list_module_parameters",
    "list_parameters",
    "parameters_in_cell",
    "parameters_in_module",
    "read_saved_params",
    "saved_params_file",
    "write_saved_params",
]
