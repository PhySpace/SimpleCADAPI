"""Turn a notebook's product value into its definition.

A notebook records each cell in a session of its own, and those sessions
are gone once the cells ran (or were restored from the cache).  What is
left are values: the product and everything it was built from, reachable
through the operation nodes the values carry.  Projection rebuilds one
definition session from them:

1. The product is the one top-level Part or Assembly whose id is the
   notebook id and that no other cell reads (:func:`find_product`).
2. A fresh session adopts the product's nodes and everything upstream of
   them (:meth:`GraphSession.validate_graph_ownership` on a shared-lineage
   session).  Nodes that do not lead to the product — previews,
   experiments — are never reached, so they stay out of the definition.
3. The expressions and frames the adopted nodes recorded, and the
   notebook's tolerance requirements, are registered with the session.
4. The session is finished by the code ``@part`` and ``@assemble`` use
   (:mod:`simplecadapi.build.definition`), with the notebook's cells
   installed so cell-relative source positions become file positions.

Projection attaches the definition to the product in place (and, for a
Part, re-points its lineage at the frozen feature graph).  Callers that
also cache the notebook's values must flush the cache first.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set as AbstractSet

from ..artifacts.assembly_io import attached_definition
from ..build.assembly_builder import declared_definitions
from ..build.definition import (
    check_declared_profiles,
    finish_assembly_definition,
    finish_part_definition,
)
from ..build.dependencies import snapshot_file_inputs
from ..build.results import AssemblyBuildResult, PartBuildResult
import weakref
from typing import Any

from simplecadapi._cpp import Assembly, find_registered_node, isolated_recording, Part, SimpleWorkplane, Solid
from simplecadapi._glue.session import lineage_of
from ..product.bodies import part_from_bodies
from simplecadapi._glue.session import GraphSession
from ..recording.source_mapping import cell_sources
from .cells import NotebookCells, bound_requirements
from .config import NotebookConfig

Product = Part | Assembly


class ProductNotFoundError(ValueError):
    """No top-level value, or more than one, is the notebook's product."""


def _product_id(value: Product) -> str:
    return value.part_id if isinstance(value, Part) else value.assembly_id


def _as_product(value: object) -> Product | None:
    if isinstance(value, (PartBuildResult, AssemblyBuildResult)):
        return value.value
    if isinstance(value, (Part, Assembly)):
        return value
    return None


def product_reads(cells: Iterable[Any], values: Mapping[str, object]) -> frozenset[str]:
    """The names the cells read, as :func:`find_product` and :func:`open_bodies` take them (*read*).

    A cell whose values are all workplanes reads a body without building on it (a workplane on the top face of ``base``
    is a datum, not a feature of the body): its reads leave the body open.
    """

    out: set[str] = set()
    for cell in cells:
        made = [values[name] for name in cell.defs if name in values]
        if made and all(isinstance(value, SimpleWorkplane) for value in made):
            continue
        out.update(cell.refs)
    return frozenset(out)


def find_product(
    config: NotebookConfig,
    values: Mapping[str, object],
    read: AbstractSet[str] = frozenset(),
) -> Product:
    """Return the value in *values* (top-level names) with the notebook id.

    A ``PartBuildResult``/``AssemblyBuildResult`` counts as its value; one
    object bound to several names counts once.  An assembly built up over
    several cells has the notebook id in every cell; of several such
    values, the ones another cell reads (*read*: the names the cells
    reference) are intermediates, and the product is the one left.
    """

    matches: dict[int, tuple[str, Product]] = {}
    others: list[str] = []
    for name, value in values.items():
        product = _as_product(value)
        if product is None:
            continue
        if _product_id(product) == config.id:
            matches.setdefault(id(product), (name, product))
        else:
            others.append(f"{name} (id {_product_id(product)!r})")
    if len(matches) > 1:
        final = {key: match for key, match in matches.items() if match[0] not in read}
        if len(final) == 1:
            matches = final
    if len(matches) == 1:
        return next(iter(matches.values()))[1]
    if matches:
        names = sorted(name for name, _ in matches.values())
        raise ProductNotFoundError(
            f"{config.path.name}: several top-level values have the notebook "
            f"id {config.id!r} and none is the only one no other cell reads: "
            f"{', '.join(names)}"
        )
    if config.kind == "part" and not others:
        implicit = _implicit_part(config, values, read)
        if implicit is not None:
            return implicit
    found = ", ".join(sorted(others)) if others else "none"
    raise ProductNotFoundError(
        f"{config.path.name}: no top-level Part or Assembly has the notebook "
        f"id {config.id!r}; Parts and Assemblies found: {found}"
    )


def open_bodies(values: Mapping[str, object], read: AbstractSet[str]) -> list[str]:
    """The public top-level solids nothing else is built from, in cell order: the bodies a part notebook leaves at the end.

    A solid another cell reads is not open; nor is one that another candidate was made from (a tool cut out in the same cell
    that keeps it under a name): the operation graph the values carry says so.
    """

    seen: set[int] = set()
    candidates: list[tuple[str, object]] = []
    for name, value in values.items():
        pieces = isinstance(value, (list, tuple)) and bool(value) and all(isinstance(v, Solid) for v in value)
        if name.startswith("_") or name in read or not (isinstance(value, Solid) or pieces) or id(value) in seen:
            continue
        seen.add(id(value))
        if pieces:  # the pieces of a split cut: one candidate, its lineage is the first piece's
            seen.update(id(v) for v in value)  # type: ignore[union-attr]
        candidates.append((name, value))
    if len(candidates) < 2:
        return [name for name, _ in candidates]
    nodes = {name: _node(value[0] if isinstance(value, (list, tuple)) else value) for name, value in candidates}
    upstream: set[str] = set()
    for name, node in nodes.items():
        if node is not None:
            upstream |= _ancestors(node)
    return [name for name, _ in candidates if nodes[name] is None or nodes[name].node_id not in upstream]


def _node(value: object) -> Any:
    found = lineage_of(value)
    if found is None:
        return None
    graph_id, node_id = found
    return find_registered_node(graph_id, node_id)


def _ancestors(node: Any) -> set[str]:
    """The ids of the nodes *node* was made from (not itself)."""

    out: set[str] = set()
    stack = list(node.inputs)
    while stack:
        item = stack.pop()
        if item.node_id in out:
            continue
        out.add(item.node_id)
        stack.extend(item.inputs)
    return out


def _implicit_part(config: NotebookConfig, values: Mapping[str, object], read: AbstractSet[str]) -> Part | None:
    """The product of a ``kind = "part"`` notebook without a cell that builds it: its open bodies, as a Part with the notebook id.

    One open body is a one-body Part (body id ``"body"``); several are the bodies of one Part, named by their variables
    (the pieces of a split cut ``<name>_1..n``).  ``None`` when there is no body yet.
    """

    names = open_bodies(values, read)
    if not names:
        return None
    part = part_from_bodies(config.id, {name: values[name] for name in names})
    _IMPLICIT[id(part)] = part
    return part


_IMPLICIT: "weakref.WeakValueDictionary[int, Part]" = weakref.WeakValueDictionary()
"""The Parts :func:`_implicit_part` made (outside any cell): :func:`project_product` records them in the definition."""


def project_product(
    product: Product,
    *,
    config: NotebookConfig,
    cells: NotebookCells,
    values: Iterable[object],
) -> Product:
    """Return *product* with its definition attached.

    *values* are the notebook's top-level values; every tolerance
    requirement they hold is part of the definition.  A product that
    already carries a definition (a ``@part`` result, a ``use``\\ d child)
    is returned as it is.
    """

    if attached_definition(product) is not None:
        return product
    session = GraphSession(
        graph_id=config.id,
        allow_external_definitions=True,
        shared_lineage=True,
    )
    # Adopting outside ``isolated_recording`` would be harmless, but finishing
    # an assembly records its solve, which must not see the caller's session
    # or coordinate system.
    with isolated_recording(), cell_sources(cells):
        if _IMPLICIT.get(id(product)) is product:
            # the implicit Part of a kind = "part" notebook was made outside any cell: make it here, recorded, so the
            # definition has its one result node (the Part), whatever the number of bodies
            with session:
                product = part_from_bodies(product.part_id, {body.body_id: body.solid for body in product.bodies})
        session.validate_graph_ownership(product)
        for node in session.graph.topological_order():
            for expression in node.expressions:
                session.expression_graph.register(expression)
            if node.frame is not None:
                session.frame_graph.add(node.frame)
        for requirement in bound_requirements(values):
            session.tolerance_graph.add(requirement)
        if isinstance(product, Part):
            return finish_part_definition(
                session,
                product,
                revision=config.revision,
                tolerance_profile=config.tolerance_profile,
                file_inputs=snapshot_file_inputs(
                    config.inputs, project_root=config.directory
                ),
                project_root=config.directory,
            ).value
        declared, _ = declared_definitions(
            [component.item for component in product.components]
        )
        check_declared_profiles(declared, config.tolerance_profile)
        return finish_assembly_definition(
            session,
            product,
            declared=declared,
            revision=config.revision,
            tolerance_profile=config.tolerance_profile,
            project_root=config.directory,
        ).value


__all__ = ["Product", "ProductNotFoundError", "find_product", "project_product"]
