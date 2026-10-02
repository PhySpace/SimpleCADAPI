"""Assembly structure and immutable component updates."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

from .._internal.semantic import SemanticValueMixin, _validate_identifier
from .connector import ConnectorRef, resolve_connector, resolve_item_connector
from .constraint import Constraint, _validate_constraints
from .part import Part
from .placement import Placement, placement_from_canonical, placement_ticks

_AUTHORED_PLACEMENTS_RUNTIME_KEY = "assembly.authored_component_placements"


def _assembly_authored_runtime(value: SemanticValueMixin) -> Dict[str, Any]:
    authored = value._get_runtime(_AUTHORED_PLACEMENTS_RUNTIME_KEY)
    if authored is None:
        return {}
    return {_AUTHORED_PLACEMENTS_RUNTIME_KEY: authored}


AssemblyItem = Union[Part, "Assembly"]
@dataclass(frozen=True)
class PublicConnectorRef:
    """Public alias for an existing connector on a direct child component."""

    public_connector_id: str
    component_id: str
    connector_id: str
    name: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "public_connector_id",
            _validate_identifier(
                self.public_connector_id,
                field_name="public_connector_id",
            ),
        )
        object.__setattr__(
            self,
            "component_id",
            _validate_identifier(self.component_id, field_name="component_id"),
        )
        object.__setattr__(
            self,
            "connector_id",
            _validate_identifier(self.connector_id, field_name="connector_id"),
        )
        if self.name is not None:
            name = str(self.name).strip()
            if not name:
                raise ValueError("name must not be empty when provided")
            object.__setattr__(self, "name", name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "public_connector_id": self.public_connector_id,
            "component_id": self.component_id,
            "connector_id": self.connector_id,
            "name": self.name,
        }




@dataclass(frozen=True)
class Component:
    """Assembly-local instance of a Part or subassembly."""

    component_id: str
    item: AssemblyItem
    placement: Placement
    name: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_id",
            _validate_identifier(self.component_id, field_name="component_id"),
        )
        if not isinstance(self.item, (Part, Assembly)):
            raise TypeError("item must be a Part or Assembly")
        if not isinstance(self.placement, Placement):
            raise TypeError("placement must be a Placement")
        if self.name is not None:
            name = str(self.name).strip()
            if not name:
                raise ValueError("name must not be empty when provided")
            object.__setattr__(self, "name", name)

    def to_dict(self) -> Dict[str, Any]:
        item_kind = "assembly" if isinstance(self.item, Assembly) else "part"
        item_id = (
            self.item.assembly_id
            if isinstance(self.item, Assembly)
            else self.item.part_id
        )
        return {
            "component_id": self.component_id,
            "name": self.name,
            "item_kind": item_kind,
            "item_id": item_id,
            "placement": self.placement.to_dict(),
        }


@dataclass(frozen=True)
class Assembly(SemanticValueMixin):
    """Product structure containing placed Part or subassembly components."""

    assembly_id: str
    name: Optional[str] = None
    components: Tuple[Component, ...] = ()
    public_connectors: Tuple[PublicConnectorRef, ...] = ()
    constraints: Tuple[Constraint, ...] = ()
    grounded_component_ids: Tuple[str, ...] = ()
    _metadata: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    _runtime: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assembly_id",
            _validate_identifier(self.assembly_id, field_name="assembly_id"),
        )
        if self.name is not None:
            name = str(self.name).strip()
            if not name:
                raise ValueError("name must not be empty when provided")
            object.__setattr__(self, "name", name)
        components = tuple(self.components or ())
        for component in components:
            if not isinstance(component, Component):
                raise TypeError("components must contain Component values")
        object.__setattr__(self, "components", components)
        ids = [component.component_id for component in components]
        duplicates = sorted(
            component_id for component_id, count in Counter(ids).items() if count > 1
        )
        if duplicates:
            raise ValueError(
                "duplicate component_id in assembly: " + ", ".join(duplicates)
            )
        public_connectors = tuple(self.public_connectors or ())
        for public in public_connectors:
            if not isinstance(public, PublicConnectorRef):
                raise TypeError(
                    "public_connectors must contain PublicConnectorRef values"
                )
        public_ids = [public.public_connector_id for public in public_connectors]
        duplicates = sorted(
            public_id for public_id, count in Counter(public_ids).items() if count > 1
        )
        if duplicates:
            raise ValueError(
                "duplicate public_connector_id in assembly: "
                + ", ".join(duplicates)
            )
        object.__setattr__(self, "public_connectors", public_connectors)
        for public in public_connectors:
            component = self.get_component(public.component_id)
            resolve_item_connector(component.item, public.connector_id)
        constraints = _validate_constraints(self.constraints)
        object.__setattr__(self, "constraints", constraints)
        for constraint in constraints:
            _validate_constraint_refs(self, constraint)
        grounded = tuple(
            _validate_identifier(component_id, field_name="component_id")
            for component_id in self.grounded_component_ids
        )
        unknown_grounded = sorted(set(grounded) - set(ids))
        if unknown_grounded:
            raise ValueError(
                "grounded component_id not found in assembly: "
                + ", ".join(unknown_grounded)
            )
        object.__setattr__(
            self, "grounded_component_ids", tuple(dict.fromkeys(grounded))
        )

    def component_ids(self) -> Tuple[str, ...]:
        return tuple(component.component_id for component in self.components)

    def get_component(self, component_id: str) -> Component:
        target = _validate_identifier(component_id, field_name="component_id")
        for component in self.components:
            if component.component_id == target:
                return component
        raise KeyError(f"assembly has no component_id '{target}'")

    def with_component(self, component: Component) -> "Assembly":
        if not isinstance(component, Component):
            raise TypeError("component must be a Component")
        if component.component_id in self.component_ids():
            raise ValueError(
                f"duplicate component_id in assembly: {component.component_id}"
            )
        if isinstance(component.item, Assembly):
            _assert_no_assembly_cycle(self, component.item)
        return Assembly(
            self.assembly_id,
            name=self.name,
            components=(*self.components, component),
            public_connectors=self.public_connectors,
            constraints=self.constraints,
            grounded_component_ids=self.grounded_component_ids,
            _metadata=dict(self._metadata),
            _runtime={},
        )

    def with_component_placement(
        self, component_id: str, placement: Placement
    ) -> "Assembly":
        if not isinstance(placement, Placement):
            raise TypeError("placement must be a Placement")
        target = _validate_identifier(component_id, field_name="component_id")
        found = False
        components = []
        for component in self.components:
            if component.component_id == target:
                found = True
                components.append(
                    Component(
                        component.component_id,
                        component.item,
                        placement,
                        name=component.name,
                    )
                )
            else:
                components.append(component)
        if not found:
            raise KeyError(f"assembly has no component_id '{target}'")
        return Assembly(
            self.assembly_id,
            name=self.name,
            components=tuple(components),
            public_connectors=self.public_connectors,
            constraints=self.constraints,
            grounded_component_ids=self.grounded_component_ids,
            _metadata=dict(self._metadata),
            _runtime={},
        )

    def public_connector_ids(self) -> Tuple[str, ...]:
        return tuple(
            public.public_connector_id for public in self.public_connectors
        )

    def get_public_connector(self, public_connector_id: str) -> PublicConnectorRef:
        target = _validate_identifier(
            public_connector_id,
            field_name="public_connector_id",
        )
        for public in self.public_connectors:
            if public.public_connector_id == target:
                return public
        raise KeyError(f"assembly has no public_connector_id '{target}'")

    def with_public_connector(self, public: PublicConnectorRef) -> "Assembly":
        if not isinstance(public, PublicConnectorRef):
            raise TypeError("public must be a PublicConnectorRef")
        if public.public_connector_id in self.public_connector_ids():
            raise ValueError(
                "duplicate public_connector_id in assembly: "
                f"{public.public_connector_id}"
            )
        component = self.get_component(public.component_id)
        resolve_item_connector(component.item, public.connector_id)
        return Assembly(
            self.assembly_id,
            name=self.name,
            components=self.components,
            public_connectors=(*self.public_connectors, public),
            constraints=self.constraints,
            grounded_component_ids=self.grounded_component_ids,
            _metadata=dict(self._metadata),
            _runtime=_assembly_authored_runtime(self),
        )

    def constraint_ids(self) -> Tuple[str, ...]:
        return tuple(constraint.constraint_id for constraint in self.constraints)

    def get_constraint(self, constraint_id: str) -> Constraint:
        target = _validate_identifier(constraint_id, field_name="constraint_id")
        for constraint in self.constraints:
            if constraint.constraint_id == target:
                return constraint
        raise KeyError(f"assembly has no constraint_id '{target}'")

    def with_constraint(self, constraint: Constraint) -> "Assembly":
        if not isinstance(constraint, Constraint):
            raise TypeError("constraint must be a Constraint")
        if constraint.constraint_id in self.constraint_ids():
            raise ValueError(
                f"duplicate constraint_id in assembly: {constraint.constraint_id}"
            )
        _validate_constraint_refs(self, constraint)
        return Assembly(
            self.assembly_id,
            name=self.name,
            components=self.components,
            public_connectors=self.public_connectors,
            constraints=(*self.constraints, constraint),
            grounded_component_ids=self.grounded_component_ids,
            _metadata=dict(self._metadata),
            _runtime=_assembly_authored_runtime(self),
        )

    def with_grounded_component(self, component_id: str) -> "Assembly":
        target = _validate_identifier(component_id, field_name="component_id")
        self.get_component(target)
        if target in self.grounded_component_ids:
            return self
        return Assembly(
            self.assembly_id,
            name=self.name,
            components=self.components,
            public_connectors=self.public_connectors,
            constraints=self.constraints,
            grounded_component_ids=(*self.grounded_component_ids, target),
            _metadata=dict(self._metadata),
            _runtime=_assembly_authored_runtime(self),
        )

    def without_grounded_component(self, component_id: str) -> "Assembly":
        target = _validate_identifier(component_id, field_name="component_id")
        self.get_component(target)
        grounded = tuple(
            existing for existing in self.grounded_component_ids if existing != target
        )
        return Assembly(
            self.assembly_id,
            name=self.name,
            components=self.components,
            public_connectors=self.public_connectors,
            constraints=self.constraints,
            grounded_component_ids=grounded,
            _metadata=dict(self._metadata),
            _runtime=_assembly_authored_runtime(self),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assembly_id": self.assembly_id,
            "name": self.name,
            "components": [component.to_dict() for component in self.components],
            "public_connectors": [
                public.to_dict() for public in self.public_connectors
            ],
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "grounded_component_ids": list(self.grounded_component_ids),
        }


def _component_occurrence_placements(
    assembly: Assembly,
) -> Tuple[Dict[str, Any], ...]:
    records: list[Dict[str, Any]] = []

    def visit(owner: Assembly, prefix: Tuple[str, ...]) -> None:
        for component in sorted(
            owner.components,
            key=lambda item: item.component_id.encode("utf-8"),
        ):
            component_path = (*prefix, component.component_id)
            records.append(
                {
                    "component_path": list(component_path),
                    "placement": placement_ticks(component.placement),
                }
            )
            if isinstance(component.item, Assembly):
                visit(component.item, component_path)

    visit(assembly, ())
    return tuple(records)


def _with_component_path_placement(
    assembly: Assembly,
    component_path: Tuple[str, ...],
    placement: Placement,
) -> Assembly:
    if not component_path:
        raise ValueError("component path must not be empty")
    if not isinstance(placement, Placement):
        raise TypeError("placement must be a Placement")
    component = assembly.get_component(component_path[0])
    if len(component_path) == 1:
        replacement = Component(
            component.component_id,
            component.item,
            placement,
            name=component.name,
        )
    else:
        if not isinstance(component.item, Assembly):
            raise ValueError("component path crosses a non-assembly component")
        replacement = Component(
            component.component_id,
            _with_component_path_placement(
                component.item,
                component_path[1:],
                placement,
            ),
            component.placement,
            name=component.name,
        )
    components = tuple(
        replacement if item.component_id == replacement.component_id else item
        for item in assembly.components
    )
    return Assembly(
        assembly.assembly_id,
        name=assembly.name,
        components=components,
        public_connectors=assembly.public_connectors,
        constraints=assembly.constraints,
        grounded_component_ids=assembly.grounded_component_ids,
        _metadata=dict(assembly._metadata),
        _runtime=dict(assembly._runtime),
    )


def _restore_component_occurrence_placements(
    assembly: Assembly,
    records: Sequence[Mapping[str, Any]],
) -> Assembly:
    expected_paths = {
        tuple(record["component_path"])
        for record in _component_occurrence_placements(assembly)
    }
    by_path: Dict[Tuple[str, ...], Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {
            "component_path",
            "placement",
        }:
            raise ValueError("invalid occurrence placement record")
        raw_path = record["component_path"]
        if (
            not isinstance(raw_path, list)
            or not raw_path
            or not all(isinstance(item, str) and item for item in raw_path)
        ):
            raise ValueError("component_path must be a non-empty string array")
        component_path = tuple(raw_path)
        if component_path in by_path:
            raise ValueError("duplicate component occurrence path")
        placement = record["placement"]
        if not isinstance(placement, Mapping):
            raise ValueError("occurrence placement must be an object")
        by_path[component_path] = placement
    if set(by_path) != expected_paths:
        raise ValueError("occurrence placement paths differ from the assembly tree")
    memo: Dict[Tuple[int, Tuple[Any, ...]], Assembly] = {}

    def placement_key(placement: Mapping[str, Any]) -> Tuple[Any, ...]:
        value = placement_from_canonical(placement)
        return (
            value.origin,
            value.x_axis,
            value.y_axis,
            value.z_axis,
        )

    def rebuild(owner: Assembly, prefix: Tuple[str, ...]) -> Assembly:
        signature = tuple(
            (
                component.component_id,
                placement_key(by_path[(*prefix, component.component_id)]),
                (
                    rebuild_signature(
                        component.item,
                        (*prefix, component.component_id),
                    )
                    if isinstance(component.item, Assembly)
                    else None
                ),
            )
            for component in owner.components
        )
        memo_key = (id(owner), signature)
        existing = memo.get(memo_key)
        if existing is not None:
            return existing
        changed = False
        components = []
        for component in owner.components:
            component_path = (*prefix, component.component_id)
            placement = placement_from_canonical(by_path[component_path])
            item = (
                rebuild(component.item, component_path)
                if isinstance(component.item, Assembly)
                else component.item
            )
            if placement != component.placement or item is not component.item:
                changed = True
            components.append(
                Component(
                    component.component_id,
                    item,
                    placement,
                    name=component.name,
                )
            )
        result = (
            Assembly(
                owner.assembly_id,
                name=owner.name,
                components=tuple(components),
                public_connectors=owner.public_connectors,
                constraints=owner.constraints,
                grounded_component_ids=owner.grounded_component_ids,
                _metadata=dict(owner._metadata),
                _runtime=dict(owner._runtime),
            )
            if changed
            else owner
        )
        memo[memo_key] = result
        return result

    def rebuild_signature(
        owner: Assembly,
        prefix: Tuple[str, ...],
    ) -> Tuple[Any, ...]:
        return tuple(
            (
                component.component_id,
                placement_key(by_path[(*prefix, component.component_id)]),
                (
                    rebuild_signature(
                        component.item,
                        (*prefix, component.component_id),
                    )
                    if isinstance(component.item, Assembly)
                    else None
                ),
            )
            for component in owner.components
        )

    return rebuild(assembly, ())


def _validate_constraint_refs(assembly: Assembly, constraint: Constraint) -> None:
    resolve_connector(assembly, constraint.connector_a)
    resolve_connector(assembly, constraint.connector_b)


def _assert_no_assembly_cycle(parent: Assembly, child: Assembly) -> None:
    if child.assembly_id == parent.assembly_id:
        raise ValueError(f"assembly cycle detected for '{parent.assembly_id}'")
    for component in child.components:
        if isinstance(component.item, Assembly):
            _assert_no_assembly_cycle(parent, component.item)


__all__ = ["Assembly", "Component", "PublicConnectorRef"]
