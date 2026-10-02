"""``@assemble``: build one Assembly definition over declared child definitions."""

from __future__ import annotations

import inspect
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping, ParamSpec, Sequence, TypeVar

from ..artifacts.assembly_definition import AssemblyDefinition
from ..artifacts.assembly_io import attached_definition, materialize_definition
from ..artifacts.canonical import (
    ArtifactValidationError,
    validate_logical_id,
    validate_revision,
)
from ..artifacts.part_definition import PartDefinition
from ..product.assembly import Assembly
from ..product.part import Part
from ..recording.graph import GraphSession, isolated_recording
from ..recording.source_mapping import source_boundary
from .definition import (
    Definition,
    check_declared_profiles,
    finish_assembly_definition,
)
from .keys import infer_project_root
from .results import AssemblyBuildResult

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _definition_value(value: Any) -> Definition:
    """Accept a build result, a definition, or a Part/Assembly that carries one."""

    if isinstance(value, (PartDefinition, AssemblyDefinition)):
        return value
    definition = attached_definition(value) or getattr(value, "definition", None)
    if not isinstance(definition, (PartDefinition, AssemblyDefinition)):
        raise TypeError(
            "definitions must contain PartBuildResult, AssemblyBuildResult, "
            "PartDefinition, AssemblyDefinition, or built Part/Assembly values"
        )
    return definition


def _runtime_value(value: Any, definition: Definition) -> Part | Assembly:
    if isinstance(value, (Part, Assembly)):
        return value
    runtime = getattr(value, "value", None)
    if isinstance(runtime, (Part, Assembly)):
        return runtime
    return materialize_definition(definition)


def _item_id(item: Part | Assembly) -> str:
    return item.part_id if isinstance(item, Part) else item.assembly_id


def declared_definitions(
    values: Sequence[Any],
) -> tuple[tuple[Definition, ...], Mapping[str, Part | Assembly]]:
    """Deduplicate declared children and pair each with its runtime value."""

    by_id: dict[str, Definition] = {}
    runtime_by_id: dict[str, Part | Assembly] = {}
    for value in values:
        definition = _definition_value(value)
        prior = by_id.get(definition.definition_id)
        if prior is not None and (
            prior.definition_kind != definition.definition_kind
            or prior.content_hash != definition.content_hash
        ):
            raise ArtifactValidationError(
                "reference_identity_conflict",
                "/definitions",
                f"definition_id {definition.definition_id!r} has multiple identities",
            )
        by_id[definition.definition_id] = definition
        runtime = _runtime_value(value, definition)
        if _item_id(runtime) != definition.definition_id:
            raise ArtifactValidationError(
                "definition_id_mismatch",
                "/definitions",
                f"runtime value {_item_id(runtime)!r} differs from definition "
                f"{definition.definition_id!r}",
            )
        runtime_by_id[definition.definition_id] = runtime
    definitions = tuple(
        sorted(by_id.values(), key=lambda item: item.definition_id.encode("utf-8"))
    )
    return definitions, runtime_by_id


def _check_component_identities(
    raw: Assembly, runtime_by_id: Mapping[str, Part | Assembly]
) -> None:
    """Every component of a declared id must carry that declared definition."""

    for component in raw.components:
        declared_runtime = runtime_by_id.get(_item_id(component.item))
        if declared_runtime is None:
            continue
        if isinstance(component.item, Part) != isinstance(declared_runtime, Part):
            raise ArtifactValidationError(
                "definition_kind_invalid",
                f"/instances/{component.component_id}",
                "runtime component kind differs from declared definition",
            )
        expected_hash = declared_runtime._get_runtime("definition.content_hash")
        actual_hash = component.item._get_runtime("definition.content_hash")
        if expected_hash is None or actual_hash != expected_hash:
            raise ArtifactValidationError(
                "reference_identity_mismatch",
                f"/instances/{component.component_id}",
                "runtime component does not carry the declared definition identity",
            )


def assemble(
    func: Callable[_P, _R] | None = None,
    *,
    id: str | None = None,
    revision: str = "1.0.0",
    definitions: Sequence[Any] = (),
    project_root: str | Path | None = None,
    tolerance_profile: str = "simplecad-default",
) -> (
    Callable[[Callable[_P, _R]], Callable[_P, AssemblyBuildResult]]
    | Callable[_P, AssemblyBuildResult]
):
    """Decorate one assembly builder with explicit external definitions.

    The builder returns the authored Assembly; it is solved strictly, the
    solve is recorded, and the result is frozen into an ``AssemblyDefinition``
    that references *definitions* by content hash. Like ``@part``, the call
    runs in a session of its own and may be nested inside another recording.
    """

    def decorate(function: Callable[_P, _R]) -> Callable[_P, AssemblyBuildResult]:
        if inspect.iscoroutinefunction(function):
            raise TypeError("@assemble does not support async functions")
        # Any callable may be decorated; one without ``__name__`` needs ``id=``.
        name = id or getattr(function, "__name__", "")
        definition_id = validate_logical_id(name, "/definition_id")
        revision_value = validate_revision(revision)
        if not isinstance(tolerance_profile, str) or not tolerance_profile:
            raise ValueError("tolerance_profile must be a non-empty string")
        declared, runtime_by_id = declared_definitions(tuple(definitions))
        check_declared_profiles(declared, tolerance_profile)
        root = infer_project_root(function, project_root)

        @source_boundary
        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> AssemblyBuildResult:
            with isolated_recording():
                session = GraphSession(
                    graph_id=definition_id,
                    allow_external_definitions=True,
                )
                with session:
                    for definition in declared:
                        session.register_external_definition(
                            value=runtime_by_id[definition.definition_id],
                            definition_kind=definition.definition_kind,
                            definition_id=definition.definition_id,
                            revision=definition.revision,
                            content_hash=definition.content_hash,
                        )
                    raw = function(*args, **kwargs)
                if not isinstance(raw, Assembly):
                    raise ArtifactValidationError(
                        "assembly_cardinality_invalid",
                        "/result",
                        "@assemble builder must return exactly one Assembly",
                    )
                if raw.assembly_id != definition_id:
                    raise ArtifactValidationError(
                        "definition_id_mismatch",
                        "/result/assembly_id",
                        f"expected {definition_id!r}, got {raw.assembly_id!r}",
                    )
                _check_component_identities(raw, runtime_by_id)
                return finish_assembly_definition(
                    session,
                    raw,
                    declared=declared,
                    revision=revision_value,
                    tolerance_profile=tolerance_profile,
                    project_root=root,
                )

        return wrapped

    if func is None:
        return decorate
    return decorate(func)


__all__ = ["assemble", "declared_definitions"]
