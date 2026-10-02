"""Best-effort source callsites for recorded operation nodes."""

from __future__ import annotations

import ast
import dis
import hashlib
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import CodeType
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol, Tuple, TypeVar


_CALL_OPS = {
    "CALL",
    "CALL_FUNCTION",
    "CALL_FUNCTION_EX",
    "CALL_FUNCTION_KW",
    "CALL_KW",
    "CALL_METHOD",
}
_SOURCE_MODULE = Path(__file__).resolve()
# This module lives in simplecadapi/recording/, so the package root is two
# levels up; frames inside it are treated as internal implementation.
_PACKAGE_ROOT = _SOURCE_MODULE.parent.parent

# Code objects of definition-build wrappers (``@part``/``@assemble``). The
# frame walk stops at them: whoever called the build is not part of the
# definition, so its call site must never leak into the recorded graph.
_BOUNDARY_CODES: set[CodeType] = set()

_F = TypeVar("_F", bound=Callable[..., Any])


def source_boundary(function: _F) -> _F:
    """Mark *function* as a provenance boundary and return it unchanged.

    Operations recorded while *function* runs take their source from the
    first user frame *inside* it; an operation with no such frame (one the
    wrapper records itself) gets no source instead of the caller's line.
    Every closure made from one ``def`` shares a code object, so marking a
    decorator's inner wrapper once covers all functions it decorates.
    """

    code = getattr(function, "__code__", None)
    if not isinstance(code, CodeType):
        raise TypeError("source_boundary expects a plain Python function")
    _BOUNDARY_CODES.add(code)
    return function


@dataclass(frozen=True)
class ResolvedSource:
    """The code a frame runs, handed over instead of reading its file.

    Notebook cells compile under a temporary filename (marimo's editor) or
    share one file with every other cell (a notebook run as a script), so
    the notebook runtime supplies the cell's own code.  Recorded lines and
    columns are then relative to that code, which keeps them valid while
    cells above it change, and the record names the cell.
    """

    text: str
    """The cell's code; recorded positions are relative to it."""
    path: Path
    """The notebook file."""
    line_offset: int
    """Frame line numbers minus the matching line numbers in *text*."""
    cell: str
    """Key of the cell, recorded as ``source["cell"]``."""


@dataclass(frozen=True)
class CellPlacement:
    """Where a cell's code sits in the notebook file on disk."""

    path: Path
    line_offset: int
    """File line numbers minus the matching line numbers in the cell."""
    column_offset: int
    """Indentation of the cell body; marimo indents every line alike."""


class CellSourceMap(Protocol):
    """Source lookup for code that runs as notebook cells."""

    def resolve(self, filename: str, line: int) -> Optional[ResolvedSource]:
        """Return the cell code running at *filename*:*line*, if any."""

    def place(self, cell: str) -> Optional[CellPlacement]:
        """Return where cell *cell* sits in the saved file, if it is there."""


_cell_sources_var: ContextVar[Optional[CellSourceMap]] = ContextVar(
    "simplecad_cell_sources", default=None
)


@contextmanager
def cell_sources(sources: CellSourceMap) -> Iterator[None]:
    """Record and finalize cell-relative sources through *sources*."""

    token = _cell_sources_var.set(sources)
    try:
        yield
    finally:
        _cell_sources_var.reset(token)


def resolve_source(filename: str, line: int) -> Optional[ResolvedSource]:
    """Return the notebook cell running at *filename*:*line*, if any."""

    sources = _cell_sources_var.get()
    return sources.resolve(filename, line) if sources is not None else None


def finalize_source(source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return *source* positioned in its file, as a definition stores it.

    A record without a ``cell`` key already is.  A cell-relative record is
    moved to the cell's place in the saved notebook, with the ``cell`` key
    dropped and the callsite id recomputed; ``None`` means the cell is not
    in the saved file (edited but not saved), so the position is unknown.
    """

    cell = source.get("cell")
    if cell is None:
        return source
    sources = _cell_sources_var.get()
    placement = sources.place(str(cell)) if sources is not None else None
    if placement is None:
        return None
    payload = dict(source)
    del payload["cell"]
    path_value, path_kind = _portable_path(placement.path)
    payload.update(path=path_value, path_kind=path_kind, local_path=str(placement.path))
    for key in ("line", "end_line"):
        payload[key] = int(payload[key]) + placement.line_offset
    for key in ("column", "end_column"):
        payload[key] = int(payload[key]) + placement.column_offset
    payload["callsite_id"] = _callsite_id(
        path_value=_callsite_path(path_value, path_kind, None),
        start_line=payload["line"],
        start_column=payload["column"],
        end_line=payload["end_line"],
        end_column=payload["end_column"],
        call_text=str(payload.get("call_text", "")),
    )
    return payload


def capture_source_provenance() -> Optional[Dict[str, Any]]:
    """Capture provenance for the first non-SimpleCAD caller frame.

    The walk ends at a :func:`source_boundary` frame without a result.

    Source discovery is intentionally failure-tolerant.  Interactive shells,
    generated code, frozen applications, and deleted source files can all
    produce a valid CAD graph without a source mapping.
    """

    frame = inspect.currentframe()
    try:
        frame = frame.f_back if frame is not None else None
        while frame is not None:
            if frame.f_code in _BOUNDARY_CODES:
                return None
            if not _is_internal_filename(frame.f_code.co_filename):
                return _capture_frame(frame)
            frame = frame.f_back
    finally:
        # Do not retain a reference cycle through frame locals.
        del frame
    return None


def canonical_source_payload(source: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the portable form stored in graph JSON.

    ``local_path`` is a runtime-only hint.  A source file outside the detected
    project cannot be assigned a truthful project-relative path, so its
    absolute path is also removed at the interchange boundary.
    """

    if source is None:
        return None
    payload = dict(source)
    payload.pop("local_path", None)
    if payload.get("path_kind") == "absolute":
        payload["path"] = None
        payload["path_kind"] = "unresolved"
    return payload


def _is_internal_filename(filename: str) -> bool:
    if not filename or filename.startswith("<"):
        return True
    try:
        path = Path(filename).resolve()
        path.relative_to(_PACKAGE_ROOT)
        return True
    except (OSError, ValueError):
        return False


def _capture_frame(frame: Any) -> Optional[Dict[str, Any]]:
    code = frame.f_code
    resolved = resolve_source(code.co_filename, frame.f_lineno)
    cell: Optional[str] = None
    line_offset = 0
    if resolved is None:
        try:
            path = Path(code.co_filename).resolve()
            source = _read_file(path)
        except (OSError, UnicodeError):
            return None
    else:
        path, source = resolved.path, resolved.text
        line_offset, cell = resolved.line_offset, resolved.cell

    try:
        calls, parents = _indexed_calls(
            source, code.co_name, int(code.co_firstlineno) - line_offset
        )
    except SyntaxError:
        return None
    if not calls:
        return None

    call = _select_call(calls, frame, line_offset)
    if call is None:
        return None

    path_value, path_kind = _portable_path(path)
    call_text = ast.get_source_segment(source, call) or ""
    start_line = int(call.lineno)
    end_line = int(getattr(call, "end_lineno", start_line))
    start_column = _character_column(source, start_line, int(call.col_offset))
    end_column = _character_column(
        source,
        end_line,
        int(getattr(call, "end_col_offset", call.col_offset)),
    )
    record: Dict[str, Any] = {
        "schema_version": "1.0",
        "path": path_value,
        "path_kind": path_kind,
        "local_path": str(path),
        "line": start_line,
        "column": start_column,
        "end_line": end_line,
        "end_column": end_column,
        "call_text": call_text,
        "callsite_id": _callsite_id(
            path_value=_callsite_path(path_value, path_kind, cell),
            start_line=start_line,
            start_column=start_column,
            end_line=end_line,
            end_column=end_column,
            call_text=call_text,
        ),
        "assignment_targets": _assignment_targets(call, source, parents),
    }
    if cell is not None:
        record["cell"] = cell
    return record


def _callsite_path(
    path_value: Optional[str], path_kind: Optional[str], cell: Optional[str]
) -> Optional[str]:
    """Path material of a callsite id; cell-relative spans also name the cell."""

    path = path_value if path_kind == "project_relative" else None
    if cell is None:
        return path
    return f"{path or ''}#{cell}"


def _read_file(path: Path) -> str:
    stat = path.stat()
    return _read_file_version(
        path,
        int(stat.st_mtime_ns),
        int(stat.st_size),
        int(getattr(stat, "st_ino", 0)),
    )


@lru_cache(maxsize=128)
def _read_file_version(path: Path, _mtime_ns: int, _size: int, _inode: int) -> str:
    return path.read_text(encoding="utf-8")


def _portable_path(path: Path) -> Tuple[Optional[str], str]:
    root = _project_root(path)
    if root is None:
        return str(path), "absolute"
    return path.relative_to(root).as_posix(), "project_relative"


def _project_root(path: Path) -> Optional[Path]:
    for parent in (path.parent, *path.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def _find_scope(
    tree: ast.AST, code_name: str, first_line: int
) -> Tuple[ast.AST, Optional[str]]:
    if code_name == "<module>":
        return tree, None

    candidates: List[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != code_name:
            continue
        decorator_lines = [
            int(decorator.lineno) for decorator in node.decorator_list
        ]
        start_line = min([int(node.lineno), *decorator_lines])
        end_line = int(getattr(node, "end_lineno", node.lineno))
        if start_line <= first_line <= end_line:
            candidates.append(node)
    if not candidates:
        return tree, code_name
    scope = min(
        candidates,
        key=lambda node: int(getattr(node, "end_lineno", node.lineno)) - node.lineno,
    )
    return scope, code_name


@lru_cache(maxsize=128)
def _parse(source: str) -> ast.AST:
    return ast.parse(source)


@lru_cache(maxsize=256)
def _indexed_calls(
    source: str, code_name: str, first_line: int
) -> Tuple[List[ast.Call], Dict[int, ast.AST]]:
    tree = _parse(source)
    scope, _function_name = _find_scope(tree, code_name, first_line)
    return _collect_calls(scope, root_is_module=scope is tree)


class _CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: List[ast.Call] = []
        self.parents: Dict[int, ast.AST] = {}

    def visit(self, node: ast.AST) -> Any:
        for child in ast.iter_child_nodes(node):
            self.parents[id(child)] = node
        return super().visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        # Calls are appended after their children, matching Python's normal
        # evaluation order for nested calls and disassembled CALL opcodes.
        self.generic_visit(node)
        self.calls.append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> Any:
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        return None


def _collect_calls(
    scope: ast.AST, *, root_is_module: bool
) -> Tuple[List[ast.Call], Dict[int, ast.AST]]:
    collector = _CallCollector()
    if root_is_module:
        for node in getattr(scope, "body", ()):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            collector.visit(node)
    else:
        for node in getattr(scope, "body", ()):
            collector.visit(node)
    # The visitor's post-order append is the execution order within a source
    # statement, while statement traversal already preserves file order.
    return collector.calls, collector.parents


def _select_call(
    calls: List[ast.Call], frame: Any, line_offset: int
) -> Optional[ast.Call]:
    # *calls* are positioned in the parsed source, the frame in its code
    # object; the two differ by *line_offset* for a resolved cell.
    line = int(frame.f_lineno) - line_offset
    line_calls = [call for call in calls if int(call.lineno) == line]
    if not line_calls:
        nearest_distance = min(abs(int(call.lineno) - line) for call in calls)
        line_calls = [
            call for call in calls if abs(int(call.lineno) - line) == nearest_distance
        ]
    if len(line_calls) == 1:
        return line_calls[0]

    ordinal = _call_ordinal(frame, line + line_offset)
    if ordinal is None or ordinal < 1 or ordinal > len(line_calls):
        return None
    return line_calls[ordinal - 1]


def _call_ordinal(frame: Any, line: int) -> Optional[int]:
    current_offset = int(frame.f_lasti)
    call_offsets = _call_offsets_by_line(frame.f_code).get(line, ())
    if current_offset in call_offsets:
        return call_offsets.index(current_offset) + 1

    # CPython 3.11 and 3.12 leave f_lasti at an inline CACHE entry after
    # CALL, while dis.get_instructions() hides CACHE entries by default.
    completed_offsets = [offset for offset in call_offsets if offset < current_offset]
    if not completed_offsets:
        return None
    return call_offsets.index(completed_offsets[-1]) + 1


@lru_cache(maxsize=128)
def _call_offsets_by_line(code: Any) -> Dict[int, Tuple[int, ...]]:
    line_by_offset = dict(dis.findlinestarts(code))
    offsets_by_line: Dict[int, List[int]] = {}
    for instruction in dis.get_instructions(code):
        if instruction.opname not in _CALL_OPS:
            continue
        line = _instruction_line(instruction.offset, line_by_offset, 0)
        offsets_by_line.setdefault(line, []).append(instruction.offset)
    return {line: tuple(offsets) for line, offsets in offsets_by_line.items()}


def _instruction_line(offset: int, line_by_offset: Dict[int, int], fallback: int) -> int:
    starts = [start for start in line_by_offset if start <= offset]
    return line_by_offset[max(starts)] if starts else int(fallback)


def _assignment_targets(
    call: ast.Call, source: str, parents: Dict[int, ast.AST]
) -> List[str]:
    parent = parents.get(id(call))
    targets: List[ast.AST] = []
    if isinstance(parent, ast.Assign) and parent.value is call:
        targets = list(parent.targets)
    elif isinstance(parent, ast.AnnAssign) and parent.value is call:
        targets = [parent.target]
    elif isinstance(parent, ast.NamedExpr) and parent.value is call:
        targets = [parent.target]

    return [
        expression
        for target in targets
        for expression in _target_expressions(target, source)
        if expression
    ]


def _target_expressions(target: ast.AST, source: str) -> List[str]:
    if isinstance(target, (ast.Tuple, ast.List)):
        return [
            expression
            for item in target.elts
            for expression in _target_expressions(item, source)
        ]
    if isinstance(target, ast.Starred):
        return _target_expressions(target.value, source)
    expression = ast.get_source_segment(source, target)
    return [expression] if expression else []


def _character_column(source: str, line: int, byte_column: int) -> int:
    lines = source.splitlines()
    if line < 1 or line > len(lines):
        return byte_column
    prefix = lines[line - 1].encode("utf-8")[:byte_column]
    return len(prefix.decode("utf-8", errors="ignore"))


def _callsite_id(
    *,
    path_value: Optional[str],
    start_line: int,
    start_column: int,
    end_line: int,
    end_column: int,
    call_text: str,
) -> str:
    material = "\x1f".join(
        [
            path_value or "",
            str(start_line),
            str(start_column),
            str(end_line),
            str(end_column),
            call_text,
        ]
    )
    return "callsite_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
