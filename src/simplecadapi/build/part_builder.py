"""``@part``: build one single-solid Part definition in an isolated session."""

from __future__ import annotations

import inspect
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, Sequence, TypeVar, overload

from ..artifacts.canonical import (
    ArtifactValidationError,
    validate_logical_id,
    validate_revision,
)
from ..core import Solid
from ..operators import make_part_rpart
from ..product.part import Part
from ..recording.graph import GraphSession, isolated_recording
from ..recording.source_mapping import source_boundary
from .definition import finish_part_definition
from .dependencies import FileInput, snapshot_file_inputs
from .keys import infer_project_root
from .results import PartBuildResult

# The web editor's live runtime imports these two names from this module.
from .definition import _part_definition as _part_definition
from .keys import generator_profile as generator_profile

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _coerce_part(value: Any, definition_id: str) -> Part:
    if isinstance(value, Solid):
        return make_part_rpart(part_id=definition_id, body=value)
    if isinstance(value, Part):
        if value.part_id != definition_id:
            raise ArtifactValidationError(
                "definition_id_mismatch",
                "/result/part_id",
                f"expected {definition_id!r}, got {value.part_id!r}",
            )
        return value
    raise ArtifactValidationError(
        "solid_cardinality_invalid",
        "/result",
        "@part builder must return exactly one Solid or one Part",
    )


@overload
def part(func: Callable[_P, _R]) -> Callable[_P, PartBuildResult]: ...


@overload
def part(
    *,
    id: str | None = ...,
    revision: str = ...,
    inputs: Sequence[FileInput] = ...,
    project_root: str | Path | None = ...,
    tolerance_profile: str = ...,
) -> Callable[[Callable[_P, _R]], Callable[_P, PartBuildResult]]: ...


def part(
    func: Callable[_P, _R] | None = None,
    *,
    id: str | None = None,
    revision: str = "1.0.0",
    inputs: Sequence[FileInput] = (),
    project_root: str | Path | None = None,
    tolerance_profile: str = "simplecad-default",
) -> Callable[[Callable[_P, _R]], Callable[_P, PartBuildResult]] | Callable[_P, PartBuildResult]:
    """Decorate one synchronous builder as a single-solid product part.

    Every call runs the builder in a fresh session of its own and returns a
    ``PartBuildResult``. The call may happen while another session is
    recording (a notebook cell, an ``@assemble`` body): that session is set
    aside for the build, and the returned Part appears in it as an external
    definition when it is used there.
    """

    def decorate(function: Callable[_P, _R]) -> Callable[_P, PartBuildResult]:
        if inspect.iscoroutinefunction(function):
            raise TypeError("@part does not support async functions")
        # Any callable may be decorated; one without ``__name__`` needs ``id=``.
        name = id or getattr(function, "__name__", "")
        definition_id = validate_logical_id(name, "/definition_id")
        revision_value = validate_revision(revision)
        if not isinstance(tolerance_profile, str) or not tolerance_profile:
            raise ValueError("tolerance_profile must be a non-empty string")
        declared_inputs = tuple(inputs)
        if not all(isinstance(item, FileInput) for item in declared_inputs):
            raise TypeError("inputs must contain values returned by file_input()")
        root = infer_project_root(function, project_root)

        @source_boundary
        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> PartBuildResult:
            snapshots = snapshot_file_inputs(declared_inputs, project_root=root)
            with isolated_recording():
                session = GraphSession(graph_id=definition_id)
                with session:
                    built = _coerce_part(function(*args, **kwargs), definition_id)
                return finish_part_definition(
                    session,
                    built,
                    revision=revision_value,
                    tolerance_profile=tolerance_profile,
                    file_inputs=snapshots,
                    project_root=root,
                )

        return wrapped

    if func is None:
        return decorate
    return decorate(func)


__all__ = ["part"]
