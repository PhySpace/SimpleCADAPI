"""Transform operator implementations."""

from __future__ import annotations

from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy, BRepBuilderAPI_GTransform, BRepBuilderAPI_Transform
from OCP.gp import gp_GTrsf, gp_Trsf
from ._support import *

def translate_shape(shape: AnyShape, vector: Tuple[float, float, float]) -> AnyShape:
    """Translate a shape by an offset vector."""
    try:
        cs = get_current_cs()
        vector_value = cast(Tuple[float, float, float], evaluate_value(vector))
        global_vector = cs.transform_vector(np.array(vector_value))
        resolved_vector = tuple(float(value) for value in global_vector)
        if isinstance(shape, Solid):
            tracked = tracked_translate(shape, resolved_vector)
            translated = cast(Solid, tracked.shape)
            translated._metadata = shape._metadata.copy()
            _attach_lineage_from_source(
                shape,
                translated,
                derivation="continuation",
                op=_OP_MAKE_TRANSLATE_RSHAPE,
            )
            return _finalize_tracked_solid(
                translated,
                op=_OP_MAKE_TRANSLATE_RSHAPE,
                params={"vector": vector},
                source_solid=shape,
                delta=tracked.delta,
                delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
                input_shapes=[shape],
            )

        new_shape = translate_shape_ocp(shape, resolved_vector)

        new_shape._metadata = shape._metadata.copy()
        _copy_runtime_state(shape, new_shape)
        _attach_lineage_from_source(
            shape,
            new_shape,
            derivation="continuation",
            op=_OP_MAKE_TRANSLATE_RSHAPE,
        )
        record_operation_if_active(
            op=_OP_MAKE_TRANSLATE_RSHAPE,
            params={"vector": vector},
            outputs=new_shape,
            input_shapes=[shape],
            context=_current_context_metadata(),
        )

        return new_shape
    except Exception as e:
        _wrap_public_api_error(
            operation="translate_shape",
            what_happened="Failed to translate the shape.",
            possible_causes=[
                "The shape is invalid or has been corrupted by an earlier operation.",
                "The translation vector is not a valid finite 3D vector.",
                "The kernel rejected the transform.",
            ],
            how_to_fix=[
                "Pass a valid SimpleCAD shape object.",
                "Pass vector as a finite 3-element tuple or expression-backed vector.",
                "Inspect the shape and vector values before retrying.",
            ],
            error=e,
        )

def rotate_shape(
    shape: AnyShape,
    angle: ScalarLike,
    axis: Tuple[float, float, float] = (0, 0, 1),
    origin: Tuple[float, float, float] = (0, 0, 0),
) -> AnyShape:
    """Rotate a shape around an axis."""
    angle_value = evaluate_scalar(angle)
    if angle_value == 0:
        return shape
    else:
        try:
            cs = get_current_cs()
            axis_value = cast(Tuple[float, float, float], evaluate_value(axis))
            origin_value = cast(Tuple[float, float, float], evaluate_value(origin))
            global_axis = cs.transform_vector(np.array(axis_value))
            global_origin = cs.transform_point(np.array(origin_value))
            resolved_axis = tuple(float(value) for value in global_axis)
            resolved_origin = tuple(float(value) for value in global_origin)
            if isinstance(shape, Solid):
                tracked = tracked_rotate(
                        shape,
                        angle_value,
                        axis=resolved_axis,
                        origin=resolved_origin,
                    )
                rotated = cast(Solid, tracked.shape)
                rotated._metadata = shape._metadata.copy()
                _attach_lineage_from_source(
                    shape,
                    rotated,
                    derivation="continuation",
                    op=_OP_MAKE_ROTATE_RSHAPE,
                )
                return _finalize_tracked_solid(
                    rotated,
                    op=_OP_MAKE_ROTATE_RSHAPE,
                    params={"angle": angle, "axis": axis, "origin": origin},
                    source_solid=shape,
                    delta=tracked.delta,
                    delta_entries=cast(
                        Dict[str, Dict[str, object]], tracked.delta_entries
                    ),
                    input_shapes=[shape],
                )

            new_shape = rotate_shape_ocp(
                shape,
                angle_value,
                resolved_axis,
                resolved_origin,
            )

            new_shape._metadata = shape._metadata.copy()
            _copy_runtime_state(shape, new_shape)
            _attach_lineage_from_source(
                shape,
                new_shape,
                derivation="continuation",
                op=_OP_MAKE_ROTATE_RSHAPE,
            )
            record_operation_if_active(
                op=_OP_MAKE_ROTATE_RSHAPE,
                params={"angle": angle, "axis": axis, "origin": origin},
                outputs=new_shape,
                input_shapes=[shape],
                context=_current_context_metadata(),
            )

            return new_shape
        except Exception as e:
            _wrap_public_api_error(
                operation="rotate_shape",
                what_happened="Failed to rotate the shape.",
                possible_causes=[
                    "The shape is invalid.",
                    "The rotation angle is invalid or non-finite.",
                    "The axis or origin is not a valid finite 3D vector.",
                ],
                how_to_fix=[
                    "Pass a valid shape and a finite rotation angle.",
                    "Use a non-zero axis vector and a valid origin point.",
                    "Log the evaluated angle, axis, and origin before retrying.",
                ],
                error=e,
            )

def linear_pattern_rsolidlist(
    shape: AnyShape, direction: Tuple[float, float, float], count: int, spacing: float
) -> List[Solid]:
    """Create a linear pattern of solids."""
    try:
        if count <= 0:
            raise ValueError("阵列数量必须大于0")
        if spacing <= 0:
            raise ValueError("阵列间距必须大于0")

        direction_value = cast(Tuple[float, float, float], evaluate_value(direction))
        direction_array = np.asarray(direction_value, dtype=float)
        direction_norm = float(np.linalg.norm(direction_array))
        if direction_norm <= 1e-15 or not np.isfinite(direction_norm):
            raise ValueError("阵列方向不能是零向量")
        local_direction = direction_array / direction_norm

        if get_active_session() is not None:
            rv: List[Solid] = []
            for i in range(count):
                offset = local_direction * (spacing * i)
                translated_shape = translate_shape(
                    shape, (float(offset[0]), float(offset[1]), float(offset[2]))
                )
                translated_shape._apply_tag("solid.pattern.linear", propagate=False)
                geo = dict(translated_shape.get_metadata("geo", {}))
                geo["pattern"] = {"type": "linear", "index": i + 1}
                translated_shape.set_metadata("geo", geo)
                _attach_track_summary(translated_shape, op="linear_pattern")
                rv.append(cast(Solid, translated_shape))
            return rv

        shapes = []
        with suspend_graph_recording():
            for i in range(count):
                offset = local_direction * (spacing * i)
                translated_shape = translate_shape(
                    shape, (float(offset[0]), float(offset[1]), float(offset[2]))
                )
                shapes.append(translated_shape)

        rv = []
        for i, s in enumerate(shapes):
            s._apply_tag("solid.pattern.linear", propagate=False)
            geo = dict(s.get_metadata("geo", {}))
            geo["pattern"] = {"type": "linear", "index": i + 1}
            s.set_metadata("geo", geo)
            _attach_track_summary(s, op="linear_pattern")
            rv.append(s)

        record_operation_if_active(
            op="linear_pattern",
            params={
                "direction": direction,
                "count": count,
                "spacing": spacing,
            },
            outputs=rv,
            input_shapes=[shape],
            context=_current_context_metadata(),
        )

        return rv

    except Exception as e:
        _wrap_public_api_error(
            operation="linear_pattern_rsolidlist",
            what_happened="Failed to create the linear pattern.",
            possible_causes=[
                "The count is not a positive integer.",
                "The spacing is not positive.",
                "The direction vector is invalid.",
            ],
            how_to_fix=[
                "Use count >= 1.",
                "Use spacing > 0.",
                "Pass a valid finite direction vector.",
            ],
            error=e,
        )

def radial_pattern_rsolidlist(
    shape: AnyShape,
    center: Tuple[float, float, float],
    axis: Tuple[float, float, float],
    count: int,
    total_rotation_angle: float,
) -> List[Solid]:
    """Create a radial pattern of solids."""
    try:
        if count <= 0:
            raise ValueError("阵列数量必须大于0")
        if total_rotation_angle <= 0:
            raise ValueError("角度必须大于0")

        shapes = []
        angle_step = total_rotation_angle / count  # 修正角度计算，均匀分布

        if get_active_session() is not None:
            rv: List[Solid] = []
            for i in range(count):
                rotation_angle = angle_step * i
                rotated_shape = (
                    cast(Solid, translate_shape(shape, (0.0, 0.0, 0.0)))
                    if i == 0
                    else cast(Solid, rotate_shape(shape, rotation_angle, axis, center))
                )
                rotated_shape._apply_tag("solid.pattern.radial", propagate=False)
                geo = dict(rotated_shape.get_metadata("geo", {}))
                geo["pattern"] = {"type": "radial", "index": i + 1}
                rotated_shape.set_metadata("geo", geo)
                _attach_track_summary(rotated_shape, op="radial_pattern")
                rv.append(rotated_shape)
            return rv

        with suspend_graph_recording():
            for i in range(count):
                rotation_angle = angle_step * i
                rotated_shape = rotate_shape(shape, rotation_angle, axis, center)
                shapes.append(rotated_shape)

        rv = []
        for i, s in enumerate(shapes):
            s._apply_tag("solid.pattern.radial", propagate=False)
            geo = dict(s.get_metadata("geo", {}))
            geo["pattern"] = {"type": "radial", "index": i + 1}
            s.set_metadata("geo", geo)
            _attach_track_summary(s, op="radial_pattern")
            rv.append(s)

        record_operation_if_active(
            op="radial_pattern",
            params={
                "center": center,
                "axis": axis,
                "count": count,
                "total_rotation_angle": total_rotation_angle,
            },
            outputs=rv,
            input_shapes=[shape],
            context=_current_context_metadata(),
        )

        return rv
    except Exception as e:
        _wrap_public_api_error(
            operation="radial_pattern_rsolidlist",
            what_happened="Failed to create the radial pattern.",
            possible_causes=[
                "The count is not a positive integer.",
                "The total rotation angle is not positive.",
                "The center or axis is invalid.",
            ],
            how_to_fix=[
                "Use count >= 1.",
                "Use a total rotation angle greater than zero.",
                "Pass a valid center point and a non-zero axis vector.",
            ],
            error=e,
        )

def mirror_shape(
    shape: AnyShape,
    plane_origin: Tuple[float, float, float],
    plane_normal: Tuple[float, float, float],
) -> AnyShape:
    """Mirror a shape across a plane."""
    try:
        cs = get_current_cs()
        plane_origin_value = cast(
            Tuple[float, float, float], evaluate_value(plane_origin)
        )
        plane_normal_value = cast(
            Tuple[float, float, float], evaluate_value(plane_normal)
        )
        global_origin = cs.transform_point(np.array(plane_origin_value))
        global_normal = cs.transform_vector(np.array(plane_normal_value))

        # 确保法向量不是零向量
        if np.linalg.norm(global_normal) < 1e-10:
            raise ValueError("镜像平面法向量不能是零向量")

        if isinstance(shape, Solid):
            resolved_origin = tuple(float(value) for value in global_origin)
            resolved_normal = tuple(float(value) for value in global_normal)
            tracked = tracked_mirror(
                    shape,
                    resolved_origin,
                    resolved_normal,
                )
            new_shape = cast(Solid, tracked.shape)
            new_shape._metadata = shape._metadata.copy()
            _attach_lineage_from_source(
                shape,
                new_shape,
                derivation="continuation",
                op=_OP_MAKE_MIRROR_RSHAPE,
            )
            new_shape._apply_tag("solid.transform.mirrored", propagate=False)
            return _finalize_tracked_solid(
                new_shape,
                op=_OP_MAKE_MIRROR_RSHAPE,
                params={
                    "plane_origin": plane_origin,
                    "plane_normal": plane_normal,
                },
                source_solid=shape,
                delta=tracked.delta,
                delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
                input_shapes=[shape],
            )

        else:
            new_shape = mirror_shape_ocp(
                shape,
                (
                    float(global_origin[0]),
                    float(global_origin[1]),
                    float(global_origin[2]),
                ),
                (
                    float(global_normal[0]),
                    float(global_normal[1]),
                    float(global_normal[2]),
                ),
            )

        new_shape._metadata = shape._metadata.copy()
        _attach_lineage_from_source(
            shape,
            new_shape,
            derivation="continuation",
            op=_OP_MAKE_MIRROR_RSHAPE,
        )
        new_shape._apply_tag("solid.transform.mirrored", propagate=False)

        _attach_track_summary(new_shape, op=_OP_MAKE_MIRROR_RSHAPE)
        record_operation_if_active(
            op=_OP_MAKE_MIRROR_RSHAPE,
            params={
                "plane_origin": plane_origin,
                "plane_normal": plane_normal,
            },
            outputs=new_shape,
            input_shapes=[shape],
            context=_current_context_metadata(),
        )

        return new_shape
    except Exception as e:
        _wrap_public_api_error(
            operation="mirror_shape",
            what_happened="Failed to mirror the shape across the plane.",
            possible_causes=[
                "The plane origin or plane normal is invalid.",
                "The plane normal is zero-length.",
                "The kernel rejected the mirror transform.",
            ],
            how_to_fix=[
                "Pass a valid plane origin and a non-zero plane normal.",
                "Validate the shape before mirroring.",
                "If the plane is computed dynamically, inspect the evaluated values first.",
            ],
            error=e,
        )


def scale_rsolid(
    solid: Solid,
    factors: Sequence[float],
    center: Sequence[float] = (0, 0, 0),
) -> Solid:
    """Scale a solid along the current coordinate system's axes about a center.

    The three factors must be finite and nonzero. A uniform scale preserves
    analytic curves and surfaces; a nonuniform scale uses the CAD kernel's
    general affine transform. The source solid stays unchanged. The operation
    is recorded as ``make_scale_rsolid`` for graph replay; topology tag lineage
    is conservatively partial.

    Args:
        solid: The solid to scale.
        factors: Scale factors along the x, y and z axes of the current
            coordinate system; finite and nonzero.
        center: The fixed point of the scaling, in current coordinate-system
            coordinates.

    Returns:
        The scaled solid.

    Raises:
        ValueError: A factor is zero or not finite, or the kernel could not
            scale the solid.
    """
    values = _finite_vector(factors, "factors")
    center_value = _finite_vector(center, "center")
    if any(v == 0 for v in values):
        raise ValueError("scale factors must be nonzero")
    cs = get_current_cs()
    global_center = cs.transform_point(np.array(center_value))
    if values[0] == values[1] == values[2]:
        transform = gp_Trsf()
        transform.SetScale(gp_Pnt(*global_center), values[0])
        builder = BRepBuilderAPI_Transform(solid.wrapped, transform, True)
    else:
        basis = np.column_stack([cs.transform_vector(np.eye(3)[i]) for i in range(3)])
        matrix = basis @ np.diag(values) @ basis.T
        translation = global_center - matrix @ global_center
        transform = gp_GTrsf()
        for row in range(3):
            for col in range(3):
                transform.SetValue(row + 1, col + 1, float(matrix[row, col]))
            transform.SetValue(row + 1, 4, float(translation[row]))
        # GTransform's copy flag copies topology, but can retain shared curve
        # geometry from boolean/fillet history. Isolate that geometry first:
        # otherwise OCCT 7.9 can produce invalid p-curves and crash its checker.
        copied = BRepBuilderAPI_Copy(solid.wrapped, True, False).Shape()
        builder = BRepBuilderAPI_GTransform(copied, transform, True)
    builder.Build()
    if not builder.IsDone():
        raise ValueError("kernel could not scale the solid")
    return _finish(solid, builder.Shape(), "make_scale_rsolid",
                   {"factors": factors, "center": center}, [solid])


def transform_rsolid(solid: Solid, matrix: Sequence[Sequence[float]]) -> Solid:
    """Apply a finite nonsingular 4x4 affine matrix in the current coordinate system.

    The matrix may include shear, reflection and nonuniform scale. Perspective
    matrices and singular maps cannot define a solid and are rejected. The
    input geometry stays unchanged. The operation is recorded as
    ``make_transform_rsolid`` for graph replay; topology tag lineage is partial.

    Args:
        solid: The solid to transform.
        matrix: A 4x4 affine matrix (row-major, last row ``0 0 0 1``), finite
            and nonsingular, in current coordinate-system coordinates.

    Returns:
        The transformed solid.

    Raises:
        ValueError: The matrix is not a finite 4x4 affine matrix, is singular
            or a perspective map, or the kernel could not transform the solid.
    """
    values = np.asarray(evaluate_value(matrix), dtype=float)
    if values.shape != (4, 4) or not np.isfinite(values).all():
        raise ValueError("matrix must be a finite 4x4 affine matrix")
    if not np.allclose(values[3], (0, 0, 0, 1), rtol=0, atol=1e-12):
        raise ValueError("perspective transforms cannot define an affine solid")
    if abs(float(np.linalg.det(values[:3, :3]))) < 1e-14:
        raise ValueError("matrix must be nonsingular")
    cs = get_current_cs()
    basis = np.column_stack([cs.transform_vector(np.eye(3)[i]) for i in range(3)])
    origin = cs.transform_point(np.zeros(3))
    linear = basis @ values[:3, :3] @ basis.T
    translation = origin + basis @ values[:3, 3] - linear @ origin
    transform = gp_GTrsf()
    for row in range(3):
        for col in range(3):
            transform.SetValue(row + 1, col + 1, float(linear[row, col]))
        transform.SetValue(row + 1, 4, float(translation[row]))
    copied = BRepBuilderAPI_Copy(solid.wrapped, True, False).Shape()
    builder = BRepBuilderAPI_GTransform(copied, transform, True)
    builder.Build()
    if not builder.IsDone():
        raise ValueError("kernel could not transform the solid")
    return _finish(solid, builder.Shape(), "make_transform_rsolid", {"matrix": matrix}, [solid])

__all__ = tuple(name for name in globals() if not name.startswith("__"))
