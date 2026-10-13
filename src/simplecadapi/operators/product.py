"""Product operator implementations."""

from __future__ import annotations

from ._support import *

def make_material_rmaterial(
    material_id: str,
    name: Optional[str] = None,
    density: Optional[float] = None,
    density_unit: Optional[str] = None,
    color: Optional[Tuple[float, float, float]] = None,
) -> Material:
    """Create a material definition for later Part assignment.

    Material is deliberately separate from `make_part_rpart(...)`; the only
    correct workflow is to create a material and then assign it to a Part with
    `assign_material_rpart(...)`.
    """

    try:
        material = Material(
            material_id,
            name=name,
            density=density,
            density_unit=density_unit,
            color=color,
        )
        _reserve_semantic_id("material", material.material_id)
        record_operation_if_active(
            _OP_MAKE_MATERIAL_RMATERIAL,
            _material_params(material),
            outputs=material,
            semantic_delta=_semantic_created(
                "Material", material.material_id, material.to_dict()
            ),
            context=_current_context_metadata(),
        )
        return material
    except Exception as e:
        _wrap_public_api_error(
            operation="make_material_rmaterial",
            what_happened="Failed to create the material definition.",
            possible_causes=[
                "The material_id is empty or uses unsupported characters.",
                "The density is non-finite, non-positive, or missing a density_unit.",
                "The color is not a 3-tuple in the [0.0, 1.0] range.",
            ],
            how_to_fix=[
                "Use a stable identifier such as 'aluminum_6061'.",
                "Provide density and density_unit together, or omit both.",
                "Pass RGB color components as floats between 0.0 and 1.0.",
            ],
            error=e,
        )

def make_placement_rplacement(
    origin: Tuple[float, float, float],
    x_axis: Tuple[float, float, float] = (1.0, 0.0, 0.0),
    y_axis: Tuple[float, float, float] = (0.0, 1.0, 0.0),
) -> Placement:
    """Create a canonical right-handed placement in the active workplane."""

    try:
        cs = get_current_cs()
        origin_global = cs.transform_point(np.asarray(origin, dtype=float))
        x_axis_global = cs.transform_vector(np.asarray(x_axis, dtype=float))
        y_axis_global = cs.transform_vector(np.asarray(y_axis, dtype=float))
        placement = Placement(
            tuple(float(value) for value in origin_global),
            x_axis=tuple(float(value) for value in x_axis_global),
            y_axis=tuple(float(value) for value in y_axis_global),
        )
        record_operation_if_active(
            _OP_MAKE_PLACEMENT_RPLACEMENT,
            {"origin": origin, "x_axis": x_axis, "y_axis": y_axis},
            outputs=placement,
            context=_current_context_metadata(),
        )
        return placement
    except Exception as e:
        _wrap_public_api_error(
            operation="make_placement_rplacement",
            what_happened="Failed to create the placement.",
            possible_causes=[
                "The origin is not a finite 3D point.",
                "One of the axes is zero-length or non-finite.",
                "x_axis and y_axis are not orthogonal.",
            ],
            how_to_fix=[
                "Pass origin, x_axis, and y_axis as finite 3-element tuples.",
                "Use one canonical representation; do not mix Euler, quaternion, or axis-angle payloads.",
                "Make sure x_axis and y_axis form a right-handed frame.",
            ],
            error=e,
        )

def identity_placement_rplacement() -> Placement:
    """Create the identity placement of the active workplane."""

    try:
        cs = get_current_cs()
        placement = Placement(
            tuple(float(value) for value in cs.origin),
            x_axis=tuple(float(value) for value in cs.x_axis),
            y_axis=tuple(float(value) for value in cs.y_axis),
        )
        record_operation_if_active(
            _OP_MAKE_IDENTITY_PLACEMENT_RPLACEMENT,
            {},
            outputs=placement,
            context=_current_context_metadata(),
        )
        return placement
    except Exception as e:
        _wrap_public_api_error(
            operation="identity_placement_rplacement",
            what_happened="Failed to create the identity placement.",
            possible_causes=["Internal placement validation failed."],
            how_to_fix=["Report this as a SimpleCADAPI bug if it reproduces."],
            error=e,
        )

def make_part_rpart(
    part_id: str,
    body: Solid,
    name: Optional[str] = None,
) -> Part:
    """Wrap exactly one Solid as a semantic single-body Part."""

    try:
        part = Part(part_id, body, name=name)
        _reserve_semantic_id("part", part.part_id)
        _ensure_geo_selection_input_nodes([body])
        record_operation_if_active(
            _OP_MAKE_PART_RPART,
            {**_part_params(part), "input_refs": _serialize_shape_refs([body])},
            outputs=part,
            input_shapes=[body],
            semantic_delta=_semantic_created("Part", part.part_id, part.to_dict()),
            context=_current_context_metadata(),
        )
        return part
    except Exception as e:
        _wrap_public_api_error(
            operation="make_part_rpart",
            what_happened="Failed to create the single-body Part.",
            possible_causes=[
                "The part_id is empty or uses unsupported characters.",
                "The body is not a Solid.",
                "A Part with the same part_id already exists in the active GraphSession.",
            ],
            how_to_fix=[
                "Pass a stable part_id such as 'base_plate'.",
                "Union intended multiple bodies into one Solid before creating the Part.",
                "Do not pass material to make_part_rpart; use assign_material_rpart instead.",
            ],
            error=e,
        )

def assign_material_rpart(part: Part, material: Material) -> Part:
    """Assign a Material to a Part and return the updated Part."""

    try:
        if not isinstance(part, Part):
            raise TypeError("part must be a Part")
        if not isinstance(material, Material):
            raise TypeError("material must be a Material")
        result = part.with_material(material)
        record_operation_if_active(
            _OP_MAKE_ASSIGN_MATERIAL_RPART,
            {
                "part_id": part.part_id,
                "material_id": material.material_id,
                "material": _material_params(material),
            },
            outputs=result,
            input_shapes=[part, material],
            semantic_delta=_semantic_modified(
                "Part",
                part.part_id,
                {"material_id": material.material_id},
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="assign_material_rpart",
            what_happened="Failed to assign the material to the Part.",
            possible_causes=[
                "The part input is not a Part.",
                "The material input is not a Material.",
            ],
            how_to_fix=[
                "Create parts with make_part_rpart(...).",
                "Create materials with make_material_rmaterial(...).",
            ],
            error=e,
        )

def make_assembly_rassembly(
    assembly_id: str,
    name: Optional[str] = None,
) -> Assembly:
    """Create an empty assembly product structure."""

    try:
        assembly = Assembly(assembly_id, name=name)
        _reserve_semantic_id("assembly", assembly.assembly_id)
        record_operation_if_active(
            _OP_MAKE_ASSEMBLY_RASSEMBLY,
            _assembly_params(assembly),
            outputs=assembly,
            semantic_delta=_semantic_created(
                "Assembly", assembly.assembly_id, assembly.to_dict()
            ),
            context=_current_context_metadata(),
        )
        return assembly
    except Exception as e:
        _wrap_public_api_error(
            operation="make_assembly_rassembly",
            what_happened="Failed to create the assembly.",
            possible_causes=[
                "The assembly_id is empty or uses unsupported characters.",
                "An Assembly with the same assembly_id already exists in the active GraphSession.",
            ],
            how_to_fix=["Pass a stable assembly_id such as 'fixture_assembly'."],
            error=e,
        )

def add_component_rassembly(
    assembly: Assembly,
    item: Union[Part, Assembly],
    component_id: str,
    placement: Placement,
    name: Optional[str] = None,
) -> Assembly:
    """Add a placed Part or subassembly component instance to an Assembly."""

    try:
        if not isinstance(assembly, Assembly):
            raise TypeError("assembly must be an Assembly")
        if not isinstance(item, (Part, Assembly)):
            raise TypeError("item must be a Part or Assembly")
        if not isinstance(placement, Placement):
            raise TypeError("placement must be a Placement")
        component = Component(component_id, item, placement, name=name)
        result = assembly.with_component(component)
        item_kind = "assembly" if isinstance(item, Assembly) else "part"
        item_id = item.assembly_id if isinstance(item, Assembly) else item.part_id
        record_operation_if_active(
            _OP_MAKE_ADD_COMPONENT_RASSEMBLY,
            {
                "assembly_id": assembly.assembly_id,
                "component_id": component.component_id,
                "name": component.name,
                "item_kind": item_kind,
                "item_id": item_id,
                "placement": placement.to_dict(),
            },
            outputs=result,
            input_shapes=[assembly, item, placement],
            semantic_delta=SemanticDelta(
                created=(
                    SemanticRef(
                        graph_id="pending",
                        node_id="pending",
                        entity_type="Component",
                        entity_id=f"{assembly.assembly_id}:{component.component_id}",
                    ),
                ),
                modified=(
                    SemanticRef(
                        graph_id="pending",
                        node_id="pending",
                        entity_type="Assembly",
                        entity_id=assembly.assembly_id,
                    ),
                ),
                metadata={"component": component.to_dict()},
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="add_component_rassembly",
            what_happened="Failed to add the component to the assembly.",
            possible_causes=[
                "The assembly input is not an Assembly.",
                "The item input is not a Part or Assembly.",
                "The component_id is empty, malformed, or duplicated in the assembly.",
                "The placement is invalid or missing.",
                "Adding this subassembly would create an assembly cycle.",
            ],
            how_to_fix=[
                "Wrap solids explicitly with make_part_rpart before adding them to assemblies.",
                "Use a unique component_id within the parent assembly.",
                "Create placements with make_placement_rplacement or identity_placement_rplacement.",
            ],
            error=e,
        )

def place_component_rassembly(
    assembly: Assembly,
    component_id: str,
    placement: Placement,
) -> Assembly:
    """Move an existing assembly component by replacing its placement."""

    try:
        if not isinstance(assembly, Assembly):
            raise TypeError("assembly must be an Assembly")
        if not isinstance(placement, Placement):
            raise TypeError("placement must be a Placement")
        result = assembly.with_component_placement(component_id, placement)
        record_operation_if_active(
            _OP_MAKE_PLACE_COMPONENT_RASSEMBLY,
            {
                "assembly_id": assembly.assembly_id,
                "component_id": component_id,
                "placement": placement.to_dict(),
            },
            outputs=result,
            input_shapes=[assembly, placement],
            semantic_delta=_semantic_modified(
                "Component",
                f"{assembly.assembly_id}:{component_id}",
                {"placement": placement.to_dict()},
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="place_component_rassembly",
            what_happened="Failed to place the assembly component.",
            possible_causes=[
                "The assembly input is not an Assembly.",
                "The component_id does not exist in the assembly.",
                "The placement is invalid or missing.",
            ],
            how_to_fix=[
                "Use add_component_rassembly before placing a component.",
                "Use a component_id returned in assembly.component_ids().",
                "Create placements with make_placement_rplacement.",
            ],
            error=e,
        )

def _make_geometry_backed_connector(
    connector_id: str,
    shape: AnyShape,
    *,
    op: str,
    operation_name: str,
    name: Optional[str] = None,
    flip: bool = False,
) -> Connector:
    source_shape = _selection_source_for_shape(shape) or shape
    node_ids = _ensure_geo_selection_node_ids(source_shape, [shape])
    source_node_id = node_ids[0] if node_ids else None
    geo_selector = _make_geo_selector(shape, source_shape=source_shape)
    kind = _shape_kind_token(shape)
    geometry_ref = GeometryRef(
        kind=kind,
        source_node_id=source_node_id,
        geo_selector=geo_selector,
        flip=bool(flip),
    )
    connector = Connector(connector_id, geometry_ref, name=name)
    record_operation_if_active(
        op,
        _connector_params(connector),
        outputs=connector,
        input_shapes=[shape],
        context=_current_context_metadata(),
    )
    return connector

def make_face_connector_rconnector(
    connector_id: str,
    face: Face,
    name: Optional[str] = None,
    flip: bool = False,
) -> Connector:
    """Create a connector anchored to a Face.

    Z axis follows the face normal; origin is the face center.
    Set flip=True to negate the Z axis (point it opposite to the normal).
    """
    try:
        if not isinstance(face, Face):
            raise TypeError("face must be a Face")
        return _make_geometry_backed_connector(
            connector_id,
            face,
            op=_OP_MAKE_FACE_CONNECTOR_RCONNECTOR,
            operation_name="make_face_connector_rconnector",
            name=name,
            flip=flip,
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_face_connector_rconnector",
            what_happened="Failed to create the face connector.",
            possible_causes=[
                "The connector_id is empty or malformed.",
                "The face is not a valid Face object.",
            ],
            how_to_fix=[
                "Use a stable connector_id such as 'mount_face'.",
                "Select a face via ql.faces().where(...).resolve(solid), or an indexed pick solid.get_faces(index).",
            ],
            error=e,
        )

def make_edge_connector_rconnector(
    connector_id: str,
    edge: Edge,
    name: Optional[str] = None,
    flip: bool = False,
) -> Connector:
    """Create a connector anchored to an Edge.

    Z axis follows the edge direction (start->end); origin is the edge midpoint.
    Set flip=True to negate the Z axis.
    """
    try:
        if not isinstance(edge, Edge):
            raise TypeError("edge must be an Edge")
        return _make_geometry_backed_connector(
            connector_id,
            edge,
            op=_OP_MAKE_EDGE_CONNECTOR_RCONNECTOR,
            operation_name="make_edge_connector_rconnector",
            name=name,
            flip=flip,
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_edge_connector_rconnector",
            what_happened="Failed to create the edge connector.",
            possible_causes=[
                "The connector_id is empty or malformed.",
                "The edge is not a valid Edge object.",
            ],
            how_to_fix=[
                "Use a stable connector_id such as 'hinge_axis'.",
                "Select an edge via ql.edges().where(...).resolve(solid), or an indexed pick solid.get_edges(index).",
            ],
            error=e,
        )

def make_vertex_connector_rconnector(
    connector_id: str,
    vertex: Vertex,
    name: Optional[str] = None,
    flip: bool = False,
) -> Connector:
    """Create a connector anchored to a Vertex.

    Origin is the vertex point; axes are identity.
    flip has no effect on vertex connectors (no direction).
    """
    try:
        if not isinstance(vertex, Vertex):
            raise TypeError("vertex must be a Vertex")
        return _make_geometry_backed_connector(
            connector_id,
            vertex,
            op=_OP_MAKE_VERTEX_CONNECTOR_RCONNECTOR,
            operation_name="make_vertex_connector_rconnector",
            name=name,
            flip=flip,
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_vertex_connector_rconnector",
            what_happened="Failed to create the vertex connector.",
            possible_causes=[
                "The connector_id is empty or malformed.",
                "The vertex is not a valid Vertex object.",
            ],
            how_to_fix=[
                "Use a stable connector_id such as 'pivot_point'.",
                "Select a vertex via ql.vertices().where(...).resolve(solid), or an indexed pick solid.get_vertices(index).",
            ],
            error=e,
        )

def make_placement_connector_rconnector(
    connector_id: str,
    placement: Placement,
    name: Optional[str] = None,
) -> Connector:
    """Create a connector anchored to an explicit local placement frame.

    Use this when a datum should be defined by a stable coordinate frame
    instead of a selected BREP face, edge, or vertex.
    """

    try:
        if not isinstance(placement, Placement):
            raise TypeError("placement must be a Placement")
        anchor = ConnectorAnchor("placement", placement=placement)
        connector = Connector(connector_id, None, name=name, anchor=anchor)
        record_operation_if_active(
            _OP_MAKE_PLACEMENT_CONNECTOR_RCONNECTOR,
            {
                "connector_id": connector.connector_id,
                "placement": placement.to_dict(),
                "name": connector.name,
            },
            outputs=connector,
            input_shapes=[placement],
            context=_current_context_metadata(),
        )
        return connector
    except Exception as e:
        _wrap_public_api_error(
            operation="make_placement_connector_rconnector",
            what_happened="Failed to create the placement connector.",
            possible_causes=[
                "The connector_id is empty or malformed.",
                "The placement input is not a Placement.",
            ],
            how_to_fix=[
                "Create placements with make_placement_rplacement.",
                "Use a stable connector_id such as 'bearing_axis'.",
            ],
            error=e,
        )

def add_connector_rpart(part: Part, connector: Connector) -> Part:
    """Attach a connector datum frame to a Part definition."""

    try:
        if not isinstance(part, Part):
            raise TypeError("part must be a Part")
        result = part.with_connector(connector)
        record_operation_if_active(
            _OP_MAKE_ADD_CONNECTOR_RPART,
            {"part_id": part.part_id, "connector_id": connector.connector_id},
            outputs=result,
            input_shapes=[part, connector],
            semantic_delta=_semantic_modified(
                "Part", part.part_id, {"connector": connector.to_dict()}
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="add_connector_rpart",
            what_happened="Failed to add the connector to the Part.",
            possible_causes=[
                "The part input is not a Part.",
                "The connector input is not a Connector.",
                "The connector_id is duplicated in the Part.",
            ],
            how_to_fix=[
                "Create a connector with make_face_connector_rconnector, make_edge_connector_rconnector, or make_vertex_connector_rconnector.",
                "Use unique connector ids within one Part.",
            ],
            error=e,
        )

def set_public_connector_rassembly(
    assembly: Assembly,
    public_connector_id: str,
    source_component_id: str,
    source_connector_id: str,
    name: Optional[str] = None,
) -> Assembly:
    """Expose an existing connector on a direct child component."""

    try:
        if not isinstance(assembly, Assembly):
            raise TypeError("assembly must be an Assembly")
        public = PublicConnectorRef(
            public_connector_id=public_connector_id,
            component_id=source_component_id,
            connector_id=source_connector_id,
            name=name,
        )
        try:
            result = assembly.with_public_connector(public)
        except KeyError as error:
            raise ValueError(f"missing component or connector for public connector: {error}") from error
        record_operation_if_active(
            _OP_MAKE_SET_PUBLIC_CONNECTOR_RASSEMBLY,
            {
                "assembly_id": assembly.assembly_id,
                "public_connector_id": public.public_connector_id,
                "source_component_id": public.component_id,
                "source_connector_id": public.connector_id,
                "name": public.name,
            },
            outputs=result,
            input_shapes=[assembly],
            semantic_delta=_semantic_modified(
                "Assembly",
                assembly.assembly_id,
                {"public_connector": public.to_dict()},
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="set_public_connector_rassembly",
            what_happened="Failed to expose the component connector publicly.",
            possible_causes=[
                "The assembly input is not an Assembly.",
                "The component is not a direct child of the Assembly.",
                "The connector does not exist on the child component.",
                "The public connector ID is already used in the Assembly.",
            ],
            how_to_fix=[
                "Add the direct child component before exposing its connector.",
                "Create the connector on the child Part or expose it on the child Assembly first.",
                "Expose each public connector ID at most once per Assembly.",
            ],
            error=e,
        )

def make_connector_ref_rconnectorref(
    component_id: str, connector_id: str
) -> ConnectorRef:
    """Reference a connector through a component instance."""

    try:
        connector_ref = ConnectorRef(component_id, connector_id)
        record_operation_if_active(
            _OP_MAKE_CONNECTOR_REF_RCONNECTORREF,
            _connector_ref_params(connector_ref),
            outputs=connector_ref,
            context=_current_context_metadata(),
        )
        return connector_ref
    except Exception as e:
        _wrap_public_api_error(
            operation="make_connector_ref_rconnectorref",
            what_happened="Failed to create the connector reference.",
            possible_causes=["The component_id or connector_id is empty or malformed."],
            how_to_fix=["Use stable ids from the owning Assembly and component item."],
            error=e,
        )

def make_scalar_limit_rscalarlimit(
    lower_value: float, upper_value: float
) -> ScalarLimit:
    """Create a closed scalar limit for driven constraint coordinates."""

    try:
        limit = ScalarLimit(lower_value, upper_value)
        record_operation_if_active(
            _OP_MAKE_SCALAR_LIMIT_RSCALARLIMIT,
            _scalar_limit_params(limit),
            outputs=limit,
            context=_current_context_metadata(),
        )
        return limit
    except Exception as e:
        _wrap_public_api_error(
            operation="make_scalar_limit_rscalarlimit",
            what_happened="Failed to create the scalar limit.",
            possible_causes=[
                "One of the limit values is non-finite.",
                "lower_value is greater than upper_value.",
            ],
            how_to_fix=["Pass finite lower and upper values in increasing order."],
            error=e,
        )

def ground_component_rassembly(assembly: Assembly, component_id: str) -> Assembly:
    """Ground a component at its current authored placement."""

    try:
        if not isinstance(assembly, Assembly):
            raise TypeError("assembly must be an Assembly")
        result = assembly.with_grounded_component(component_id)
        record_operation_if_active(
            _OP_MAKE_GROUND_COMPONENT_RASSEMBLY,
            {"assembly_id": assembly.assembly_id, "component_id": component_id},
            outputs=result,
            input_shapes=[assembly],
            semantic_delta=_semantic_modified(
                "Assembly",
                assembly.assembly_id,
                {"grounded_component_id": component_id},
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="ground_component_rassembly",
            what_happened="Failed to ground the assembly component.",
            possible_causes=[
                "The assembly input is not an Assembly.",
                "The component_id does not exist in the Assembly.",
            ],
            how_to_fix=["Use a component_id already added to the Assembly."],
            error=e,
        )

def unground_component_rassembly(assembly: Assembly, component_id: str) -> Assembly:
    """Remove a component grounding marker."""

    try:
        if not isinstance(assembly, Assembly):
            raise TypeError("assembly must be an Assembly")
        result = assembly.without_grounded_component(component_id)
        record_operation_if_active(
            _OP_MAKE_UNGROUND_COMPONENT_RASSEMBLY,
            {"assembly_id": assembly.assembly_id, "component_id": component_id},
            outputs=result,
            input_shapes=[assembly],
            semantic_delta=_semantic_modified(
                "Assembly",
                assembly.assembly_id,
                {"ungrounded_component_id": component_id},
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="unground_component_rassembly",
            what_happened="Failed to unground the assembly component.",
            possible_causes=[
                "The assembly input is not an Assembly.",
                "The component_id does not exist in the Assembly.",
            ],
            how_to_fix=["Use a component_id already added to the Assembly."],
            error=e,
        )

def add_fixed_constraint_rassembly(
    assembly: Assembly,
    constraint_id: str,
    connector_a: ConnectorRef,
    connector_b: ConnectorRef,
    name: Optional[str] = None,
) -> Assembly:
    """Constrain two component connectors to the same frame."""

    return _add_constraint_rassembly(
        assembly,
        Constraint(
            constraint_id,
            "fixed",
            connector_a,
            connector_b,
            name=name,
        ),
        _OP_MAKE_FIXED_CONSTRAINT_RASSEMBLY,
        "add_fixed_constraint_rassembly",
    )

def add_revolute_constraint_rassembly(
    assembly: Assembly,
    constraint_id: str,
    connector_a: ConnectorRef,
    connector_b: ConnectorRef,
    drive_angle_degrees: Optional[float] = None,
    angle_limit: Optional[ScalarLimit] = None,
    name: Optional[str] = None,
) -> Assembly:
    """Constrain two connectors as a revolute axis pair."""

    return _add_constraint_rassembly(
        assembly,
        Constraint(
            constraint_id,
            "revolute",
            connector_a,
            connector_b,
            drive_angle_degrees=drive_angle_degrees,
            angle_limit=angle_limit,
            name=name,
        ),
        _OP_MAKE_REVOLUTE_CONSTRAINT_RASSEMBLY,
        "add_revolute_constraint_rassembly",
    )

def add_prismatic_constraint_rassembly(
    assembly: Assembly,
    constraint_id: str,
    connector_a: ConnectorRef,
    connector_b: ConnectorRef,
    drive_distance: Optional[float] = None,
    distance_limit: Optional[ScalarLimit] = None,
    name: Optional[str] = None,
) -> Assembly:
    """Constrain two connectors as a prismatic slider pair."""

    return _add_constraint_rassembly(
        assembly,
        Constraint(
            constraint_id,
            "prismatic",
            connector_a,
            connector_b,
            drive_distance=drive_distance,
            distance_limit=distance_limit,
            name=name,
        ),
        _OP_MAKE_PRISMATIC_CONSTRAINT_RASSEMBLY,
        "add_prismatic_constraint_rassembly",
    )

def add_gear_constraint_rassembly(
    assembly: Assembly,
    constraint_id: str,
    connector_a: ConnectorRef,
    connector_b: ConnectorRef,
    pitch_radius_a: float,
    pitch_radius_b: float,
    phase_offset: Optional[float] = None,
    name: Optional[str] = None,
) -> Assembly:
    """Couple two revolute axes as meshing gears with inverse rotation."""

    constraint = Constraint(
        constraint_id,
        "gear",
        connector_a,
        connector_b,
        pitch_radius_a=pitch_radius_a,
        pitch_radius_b=pitch_radius_b,
        phase_offset=phase_offset,
        name=name,
    )
    if phase_offset is None:
        constraint = Constraint(
            constraint_id,
            "gear",
            connector_a,
            connector_b,
            pitch_radius_a=pitch_radius_a,
            pitch_radius_b=pitch_radius_b,
            phase_offset=coupling_phase_offset(assembly, constraint),
            name=name,
        )
    return _add_constraint_rassembly(
        assembly,
        constraint,
        _OP_MAKE_GEAR_CONSTRAINT_RASSEMBLY,
        "add_gear_constraint_rassembly",
    )

def add_belt_constraint_rassembly(
    assembly: Assembly,
    constraint_id: str,
    connector_a: ConnectorRef,
    connector_b: ConnectorRef,
    pulley_radius_a: float,
    pulley_radius_b: float,
    phase_offset: Optional[float] = None,
    name: Optional[str] = None,
) -> Assembly:
    """Couple two revolute axes as belt-linked pulleys with same-direction rotation."""

    constraint = Constraint(
        constraint_id,
        "belt",
        connector_a,
        connector_b,
        pulley_radius_a=pulley_radius_a,
        pulley_radius_b=pulley_radius_b,
        phase_offset=phase_offset,
        name=name,
    )
    if phase_offset is None:
        constraint = Constraint(
            constraint_id,
            "belt",
            connector_a,
            connector_b,
            pulley_radius_a=pulley_radius_a,
            pulley_radius_b=pulley_radius_b,
            phase_offset=coupling_phase_offset(assembly, constraint),
            name=name,
        )
    return _add_constraint_rassembly(
        assembly,
        constraint,
        _OP_MAKE_BELT_CONSTRAINT_RASSEMBLY,
        "add_belt_constraint_rassembly",
    )

def add_rack_pinion_constraint_rassembly(
    assembly: Assembly,
    constraint_id: str,
    rack_connector: ConnectorRef,
    pinion_connector: ConnectorRef,
    pitch_radius: float,
    phase_offset: Optional[float] = None,
    name: Optional[str] = None,
) -> Assembly:
    """Couple a prismatic rack axis to a revolute pinion axis."""

    constraint = Constraint(
        constraint_id,
        "rack_pinion",
        rack_connector,
        pinion_connector,
        pitch_radius=pitch_radius,
        phase_offset=phase_offset,
        name=name,
    )
    if phase_offset is None:
        constraint = Constraint(
            constraint_id,
            "rack_pinion",
            rack_connector,
            pinion_connector,
            pitch_radius=pitch_radius,
            phase_offset=coupling_phase_offset(assembly, constraint),
            name=name,
        )
    return _add_constraint_rassembly(
        assembly,
        constraint,
        _OP_MAKE_RACK_PINION_CONSTRAINT_RASSEMBLY,
        "add_rack_pinion_constraint_rassembly",
    )

def _add_constraint_rassembly(
    assembly: Assembly,
    constraint: Constraint,
    op_name: str,
    public_name: str,
) -> Assembly:
    try:
        if not isinstance(assembly, Assembly):
            raise TypeError("assembly must be an Assembly")
        result = assembly.with_constraint(constraint)
        inputs: List[object] = [
            assembly,
            constraint.connector_a,
            constraint.connector_b,
        ]
        if constraint.distance_limit is not None:
            inputs.append(constraint.distance_limit)
        if constraint.angle_limit is not None:
            inputs.append(constraint.angle_limit)
        record_operation_if_active(
            op_name,
            _constraint_params(constraint),
            outputs=result,
            input_shapes=inputs,
            semantic_delta=_semantic_modified(
                "Assembly", assembly.assembly_id, {"constraint": constraint.to_dict()}
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation=public_name,
            what_happened="Failed to add the assembly constraint.",
            possible_causes=[
                "The assembly input is not an Assembly.",
                "A connector ref references a missing component or connector.",
                "The constraint_id is duplicated in the Assembly.",
                "A drive value violates its scalar limit.",
            ],
            how_to_fix=[
                "Create connector refs with make_connector_ref_rconnectorref.",
                "Add connectors to Parts or Assemblies before adding constrained components.",
                "Use unique constraint ids within one Assembly.",
            ],
            error=e,
        )

def solve_assembly_constraints_rassembly(
    assembly: Assembly, strict: bool = True
) -> Assembly:
    """Solve fixed, revolute, and prismatic assembly constraints.

    Solving is limit-aware: when a constraint carries a ``ScalarLimit``
    (``angle_limit`` or ``distance_limit``), the drive scalar is clamped
    into the closed range before placement propagation.  When no drive
    scalar is present but a limit exists, the current relative-frame
    scalar is projected into the bounds.  Unresolvable closed kinematic
    loops fall back to a golden-section search over the limit bounds.

    A ``ConstraintReport`` is recorded on the returned assembly under the
    ``constraint_report`` runtime key for later inspection via
    ``inspect_assembly_constraints_rassembly``.
    """

    try:
        result = solve_assembly_constraints(assembly, strict=bool(strict))
        solved_component_placements = {
            component.component_id: component.placement.to_dict()
            for component in result.components
        }
        record_operation_if_active(
            _OP_MAKE_SOLVE_ASSEMBLY_CONSTRAINTS_RASSEMBLY,
            {
                "assembly_id": assembly.assembly_id,
                "strict": bool(strict),
                "component_placements": solved_component_placements,
            },
            outputs=result,
            input_shapes=[assembly],
            semantic_delta=_semantic_modified(
                "Assembly", assembly.assembly_id, {"constraints_solved": True}
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="solve_assembly_constraints_rassembly",
            what_happened="Failed to solve the assembly constraints.",
            possible_causes=[
                "No component is grounded.",
                "A constraint graph references missing connectors.",
                "A connected component cannot be reached from a grounded component.",
                "A closed-loop residual exceeds tolerance.",
            ],
            how_to_fix=[
                "Ground at least one component with ground_component_rassembly.",
                "Ensure every constrained component has the required connectors.",
                "Inspect constraint residuals before strict solving.",
            ],
            error=e,
        )

def measure_constraint_residual_rconstraintresidual(
    assembly: Assembly, constraint_id: str
) -> ConstraintResidual:
    """Measure residual for one assembly constraint without mutating the assembly."""

    return measure_constraint_residual(assembly, constraint_id)

def inspect_assembly_constraints_rconstraintreport(
    assembly: Assembly,
) -> ConstraintReport:
    """Inspect all assembly constraint residuals without mutating the assembly."""

    return inspect_assembly_constraints(assembly)

def _placed_solids_from_item(
    item: Union[Part, Assembly], placement: Placement
) -> List[Solid]:
    if isinstance(item, Part):
        placed = place_shape_ocp(
            item.body,
            placement.origin,
            placement.x_axis,
            placement.y_axis,
            placement.z_axis,
        )
        return [cast(Solid, placed)]
    if isinstance(item, Assembly):
        solids: List[Solid] = []
        for component in item.components:
            solids.extend(
                _placed_solids_from_item(
                    component.item,
                    compose_placements(placement, component.placement),
                )
            )
        return solids
    raise TypeError("item must be a Part or Assembly")

def make_compound_from_assembly_rcompound(assembly: Assembly) -> Compound:
    """Project an Assembly into an explicit flattened Compound geometry value."""

    try:
        if not isinstance(assembly, Assembly):
            raise TypeError("assembly must be an Assembly")
        if not assembly.components:
            raise ValueError("assembly must contain at least one component to project")
        solids = _placed_solids_from_item(assembly, identity_placement())
        if not solids:
            raise ValueError("assembly projection produced no solids")
        compound = Compound(make_compound_always([solid.wrapped for solid in solids]))
        compound.set_metadata(
            "assembly_projection",
            {
                "assembly_id": assembly.assembly_id,
                "component_count": len(assembly.components),
                "solid_count": len(solids),
            },
        )
        record_operation_if_active(
            _OP_MAKE_COMPOUND_FROM_ASSEMBLY_RCOMPOUND,
            {
                "assembly_id": assembly.assembly_id,
                "component_count": len(assembly.components),
            },
            outputs=compound,
            input_shapes=[assembly],
            semantic_delta=_semantic_modified(
                "Assembly",
                assembly.assembly_id,
                {"projection": "compound", "solid_count": len(solids)},
            ),
            context=_current_context_metadata(),
        )
        return compound
    except Exception as e:
        _wrap_public_api_error(
            operation="make_compound_from_assembly_rcompound",
            what_happened="Failed to project the assembly into a Compound.",
            possible_causes=[
                "The input is not an Assembly.",
                "The assembly has no components.",
                "A component placement is invalid.",
                "The kernel could not transform or combine the component bodies.",
            ],
            how_to_fix=[
                "Create an assembly with make_assembly_rassembly and add at least one component.",
                "Ensure every component references a valid Part or subassembly.",
                "Validate placements before projection.",
            ],
            error=e,
        )

__all__ = tuple(name for name in globals() if not name.startswith("__"))
