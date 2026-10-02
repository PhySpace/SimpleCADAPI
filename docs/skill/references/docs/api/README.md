# SimpleCAD API Index

This index includes generated docs for the public SimpleCAD API surface, including geometry operations, graph/model JSON workflows, durable product builds, the notebook runtime, inspection tools, expressions, QL, and export helpers.

## Import Surfaces

- Entries marked `top-level` are exported from `simplecadapi` and can be imported with `from simplecadapi import <name>`.
- Entries marked `submodule` are public through the listed submodule, such as `simplecadapi.ql`.
- Entries marked `inspection namespace` are available through `simplecadapi.inspect.brep` and cannot run inside `GraphSession`.
- Entries marked `drawing-inspection namespace` are available through `simplecadapi.inspect.drawing` and cannot run inside `GraphSession`.
- Entries marked `translator backend` are public only through `simplecadapi.translator.<backend>`.
- Entries marked `reverse-engineering evaluator` are available through `simplecadapi.inverse_engineer.brep`; their acceptance inputs and reports belong to the trusted harness, not participant code.

## Basic Creation

- [make_2d_cut_rface](make_2d_cut_rface.md) *(from operators/boolean.py)* `top-level`
- [make_2d_intersect_rface](make_2d_intersect_rface.md) *(from operators/boolean.py)* `top-level`
- [make_2d_union_rface](make_2d_union_rface.md) *(from operators/boolean.py)* `top-level`
- [make_angle_arc_redge](make_angle_arc_redge.md) *(from operators/geometry.py)* `top-level`
- [make_angle_arc_rwire](make_angle_arc_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_assembly_rassembly](make_assembly_rassembly.md) *(from operators/product.py)* `top-level`
- [make_bezier_surface_rface](make_bezier_surface_rface.md) *(from operators/geometry.py)* `top-level`
- [make_box_rsolid](make_box_rsolid.md) *(from operators/geometry.py)* `top-level`
- [make_circle_redge](make_circle_redge.md) *(from operators/geometry.py)* `top-level`
- [make_circle_rface](make_circle_rface.md) *(from operators/geometry.py)* `top-level`
- [make_circle_rwire](make_circle_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_compound_from_assembly_rcompound](make_compound_from_assembly_rcompound.md) *(from operators/product.py)* `top-level`
- [make_cone_rsolid](make_cone_rsolid.md) *(from operators/geometry.py)* `top-level`
- [make_connector_ref_rconnectorref](make_connector_ref_rconnectorref.md) *(from operators/product.py)* `top-level`
- [make_cylinder_rsolid](make_cylinder_rsolid.md) *(from operators/geometry.py)* `top-level`
- [make_cylindrical_surface_rface](make_cylindrical_surface_rface.md) *(from operators/geometry.py)* `top-level`
- [make_edge_connector_rconnector](make_edge_connector_rconnector.md) *(from operators/product.py)* `top-level`
- [make_ellipse_redge](make_ellipse_redge.md) *(from operators/geometry.py)* `top-level`
- [make_ellipse_rface](make_ellipse_rface.md) *(from operators/geometry.py)* `top-level`
- [make_ellipse_rwire](make_ellipse_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_face_connector_rconnector](make_face_connector_rconnector.md) *(from operators/product.py)* `top-level`
- [make_face_from_sketch_rface](make_face_from_sketch_rface.md) *(from operators/sketch.py)* `top-level`
- [make_face_from_wire_rface](make_face_from_wire_rface.md) *(from operators/geometry.py)* `top-level`
- [make_face_from_wires_rface](make_face_from_wires_rface.md) *(from operators/geometry.py)* `top-level`
- [make_gordon_surface_rface](make_gordon_surface_rface.md) *(from operators/geometry.py)* `top-level`
- [make_helix_redge](make_helix_redge.md) *(from operators/geometry.py)* `top-level`
- [make_helix_rwire](make_helix_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_interpolated_spline_redge](make_interpolated_spline_redge.md) *(from operators/geometry.py)* `top-level`
- [make_interpolated_spline_rwire](make_interpolated_spline_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_line_redge](make_line_redge.md) *(from operators/geometry.py)* `top-level`
- [make_material_rmaterial](make_material_rmaterial.md) *(from operators/product.py)* `top-level`
- [make_part_rpart](make_part_rpart.md) *(from operators/product.py)* `top-level`
- [make_periodic_spline_rwire](make_periodic_spline_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_placement_connector_rconnector](make_placement_connector_rconnector.md) *(from operators/product.py)* `top-level`
- [make_placement_rplacement](make_placement_rplacement.md) *(from operators/product.py)* `top-level`
- [make_point_rvertex](make_point_rvertex.md) *(from operators/geometry.py)* `top-level`
- [make_polyline_rwire](make_polyline_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_rectangle_rface](make_rectangle_rface.md) *(from operators/geometry.py)* `top-level`
- [make_rectangle_rwire](make_rectangle_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_ruled_surface_rface](make_ruled_surface_rface.md) *(from operators/geometry.py)* `top-level`
- [make_scalar_limit_rscalarlimit](make_scalar_limit_rscalarlimit.md) *(from operators/product.py)* `top-level`
- [make_segment_redge](make_segment_redge.md) *(from operators/geometry.py)* `top-level`
- [make_segment_rwire](make_segment_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_sketch_rsketch](make_sketch_rsketch.md) *(from operators/sketch.py)* `top-level`
- [make_solid_from_shell_rsolid](make_solid_from_shell_rsolid.md) *(from operators/geometry.py)* `top-level`
- [make_sphere_rsolid](make_sphere_rsolid.md) *(from operators/geometry.py)* `top-level`
- [make_spline_redge](make_spline_redge.md) *(from operators/geometry.py)* `top-level`
- [make_spline_rwire](make_spline_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_surface_patch_rface](make_surface_patch_rface.md) *(from operators/geometry.py)* `top-level`
- [make_three_point_arc_redge](make_three_point_arc_redge.md) *(from operators/geometry.py)* `top-level`
- [make_three_point_arc_rwire](make_three_point_arc_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_vertex_connector_rconnector](make_vertex_connector_rconnector.md) *(from operators/product.py)* `top-level`
- [make_wire_from_edges_rwire](make_wire_from_edges_rwire.md) *(from operators/geometry.py)* `top-level`
- [make_wire_from_sketch_rwire](make_wire_from_sketch_rwire.md) *(from operators/sketch.py)* `top-level`

## Transforms

- [mirror_shape](mirror_shape.md) *(from operators/transform.py)* `top-level`
- [rotate_shape](rotate_shape.md) *(from operators/transform.py)* `top-level`
- [translate_shape](translate_shape.md) *(from operators/transform.py)* `top-level`

## 3D Operations

- [extrude_rsolid](extrude_rsolid.md) *(from operators/features.py)* `top-level`
- [loft_rshell](loft_rshell.md) *(from operators/geometry.py)* `top-level`
- [loft_rsolid](loft_rsolid.md) *(from operators/features.py)* `top-level`
- [revolve_rsolid](revolve_rsolid.md) *(from operators/features.py)* `top-level`
- [sweep_rsolid](sweep_rsolid.md) *(from operators/features.py)* `top-level`

## Tagging and Selection

- [apply_tag](apply_tag.md) *(from operators/selection.py)* `top-level`
- [apply_tag_rselection](apply_tag_rselection.md) *(from operators/selection.py)* `top-level`
- [list_tags](list_tags.md) *(from operators/selection.py)* `top-level`
- [select_edges_by_tag](select_edges_by_tag.md) *(from operators/selection.py)* `top-level`
- [select_faces_by_tag](select_faces_by_tag.md) *(from operators/selection.py)* `top-level`

## Boolean Operations

- [cut_rsolid](cut_rsolid.md) *(from operators/boolean.py)* `top-level`
- [intersect_rsolid](intersect_rsolid.md) *(from operators/boolean.py)* `top-level`
- [union_rsolid](union_rsolid.md) *(from operators/boolean.py)* `top-level`

## Export

- [ProductMJCFExportReport](ProductMJCFExportReport.md) *(from exporter/mjcf.py)* `exporter namespace`
- [ProductOBJExportReport](ProductOBJExportReport.md) *(from exporter/obj.py)* `exporter namespace`
- [ProductSTEPExportReport](ProductSTEPExportReport.md) *(from exporter/step.py)* `exporter namespace`
- [ProductSTLExportReport](ProductSTLExportReport.md) *(from exporter/stl.py)* `exporter namespace`
- [export_product_package_to_mjcf](export_product_package_to_mjcf.md) *(from exporter/mjcf.py)* `exporter namespace`
- [export_product_package_to_obj](export_product_package_to_obj.md) *(from exporter/obj.py)* `exporter namespace`
- [export_product_package_to_step](export_product_package_to_step.md) *(from exporter/step.py)* `exporter namespace`
- [export_product_package_to_stl](export_product_package_to_stl.md) *(from exporter/stl.py)* `exporter namespace`

## Translator Backends

- [FreeCADTranslator](FreeCADTranslator.md) *(from translator/freecad_translator/translator.py)* `translator backend`
- [Fusion360Translator](Fusion360Translator.md) *(from translator/fusion360_translator/translator.py)* `translator backend`
- [SolidWorksTranslator](SolidWorksTranslator.md) *(from translator/solidworks_translator/translator.py)* `translator backend`
- [export_model_json_to_solidworks_step](export_model_json_to_solidworks_step.md) *(from translator/solidworks_translator/api.py)* `translator backend`
- [translate_model_json_to_fcstd](translate_model_json_to_fcstd.md) *(from translator/freecad_translator/api.py)* `translator backend`
- [translate_model_json_to_freecad_script](translate_model_json_to_freecad_script.md) *(from translator/freecad_translator/api.py)* `translator backend`
- [translate_model_json_to_solidworks_script](translate_model_json_to_solidworks_script.md) *(from translator/solidworks_translator/api.py)* `translator backend`
- [translate_product_package_to_fcstd](translate_product_package_to_fcstd.md) *(from translator/freecad_translator/api.py)* `translator backend`
- [translate_product_package_to_freecad_script](translate_product_package_to_freecad_script.md) *(from translator/freecad_translator/api.py)* `translator backend`
- [translate_product_package_to_fusion360_script](translate_product_package_to_fusion360_script.md) *(from translator/fusion360_translator/api.py)* `translator backend`
- [translate_product_package_to_solidworks_script](translate_product_package_to_solidworks_script.md) *(from translator/solidworks_translator/api.py)* `translator backend`

## Math Helpers

- [BSplineFitResult](BSplineFitResult.md) *(from math.py)* `top-level`
- [fit_cubic_bspline_control_points](fit_cubic_bspline_control_points.md) *(from math.py)* `top-level`

## Modeling Graph and Replay

- [GraphSession](GraphSession.md) *(from recording/graph.py)* `top-level`
- [export_graph_json](export_graph_json.md) *(from recording/serializer.py)* `top-level`
- [export_model_json](export_model_json.md) *(from recording/serializer.py)* `top-level`
- [export_session_json](export_session_json.md) *(from recording/serializer.py)* `top-level`
- [get_active_session](get_active_session.md) *(from recording/graph.py)* `top-level`
- [import_graph_json](import_graph_json.md) *(from recording/serializer.py)* `top-level`
- [import_model_json](import_model_json.md) *(from recording/serializer.py)* `top-level`
- [import_session_json](import_session_json.md) *(from recording/serializer.py)* `top-level`
- [replay_graph](replay_graph.md) *(from recording/serializer.py)* `top-level`
- [replay_model_json](replay_model_json.md) *(from recording/serializer.py)* `top-level`
- [suspend_graph_recording](suspend_graph_recording.md) *(from recording/graph.py)* `top-level`

## Expressions and Parameters

- [Const](Const.md) *(from params/expr.py)* `top-level`
- [DimensionTolerance](DimensionTolerance.md) *(from params/expr.py)* `top-level`
- [Expr](Expr.md) *(from params/expr.py)* `top-level`
- [ExpressionGraph](ExpressionGraph.md) *(from params/expr.py)* `top-level`
- [ToleranceAnalysis](ToleranceAnalysis.md) *(from params/tolerance.py)* `top-level`
- [ToleranceAnalysisError](ToleranceAnalysisError.md) *(from params/tolerance.py)* `top-level`
- [ToleranceCheck](ToleranceCheck.md) *(from params/tolerance.py)* `top-level`
- [ToleranceContribution](ToleranceContribution.md) *(from params/tolerance.py)* `top-level`
- [ToleranceGraph](ToleranceGraph.md) *(from params/tolerance.py)* `top-level`
- [ToleranceReport](ToleranceReport.md) *(from params/tolerance.py)* `top-level`
- [ToleranceRequirement](ToleranceRequirement.md) *(from params/tolerance.py)* `top-level`
- [ToleranceValidationError](ToleranceValidationError.md) *(from params/tolerance.py)* `top-level`
- [Var](Var.md) *(from params/expr.py)* `top-level`
- [analyze_tolerance](analyze_tolerance.md) *(from params/tolerance.py)* `top-level`
- [check_tolerance](check_tolerance.md) *(from params/tolerance.py)* `top-level`
- [const](const_function.md) *(from params/expr.py)* `top-level`
- [var](var_function.md) *(from params/expr.py)* `top-level`

## Physical Units

- [Dimension](Dimension.md) *(from params/units.py)* `top-level`
- [Unit](Unit.md) *(from params/units.py)* `top-level`
- [UnitValidationError](UnitValidationError.md) *(from params/units.py)* `top-level`
- [canonical_unit_for_dimension](canonical_unit_for_dimension.md) *(from params/units.py)* `top-level`
- [convert_value](convert_value.md) *(from params/units.py)* `top-level`
- [expression_uses_units](expression_uses_units.md) *(from params/units.py)* `top-level`
- [get_unit](get_unit.md) *(from params/units.py)* `top-level`
- [infer_dimension](infer_dimension.md) *(from params/units.py)* `top-level`

## Types and Errors

- [SimpleCADError](SimpleCADError.md) *(from errors.py)* `top-level`
- [Sketch](Sketch.md) *(from sketch.py)* `top-level`
- [SketchConstraint](SketchConstraint.md) *(from sketch.py)* `top-level`
- [SketchConstraintDiagnostic](SketchConstraintDiagnostic.md) *(from sketch.py)* `top-level`
- [SketchRef](SketchRef.md) *(from sketch.py)* `top-level`
- [SketchSolveResult](SketchSolveResult.md) *(from sketch.py)* `top-level`

## Advanced Features

- [chamfer_rsolid](chamfer_rsolid.md) *(from operators/features.py)* `top-level`
- [fillet_rsolid](fillet_rsolid.md) *(from operators/features.py)* `top-level`
- [helical_sweep_rsolid](helical_sweep_rsolid.md) *(from operators/features.py)* `top-level`
- [shell_rsolid](shell_rsolid.md) *(from operators/features.py)* `top-level`

## STEP/BREP Inspection

- [BRepComparison](BRepComparison.md) *(from inspect/brep/compare.py)* `inspection namespace`
- [BRepEntityError](BRepEntityError.md) *(from inspect/brep/model.py)* `inspection namespace`
- [BRepInspection](BRepInspection.md) *(from inspect/brep/inspect.py)* `inspection namespace`
- [BRepModel](BRepModel.md) *(from inspect/brep/model.py)* `inspection namespace`
- [EntityInspectionParity](EntityInspectionParity.md) *(from inspect/brep/parity.py)* `inspection namespace`
- [InspectionSummaryComparison](InspectionSummaryComparison.md) *(from inspect/brep/compare.py)* `inspection namespace`
- [SliceSpec](SliceSpec.md) *(from inspect/brep/slices.py)* `inspection namespace`
- [clear_step_model_cache_rnone](clear_step_model_cache_rnone.md) *(from inspect/brep/model.py)* `inspection namespace`
- [compare_boundary_distance_rdescriptor](compare_boundary_distance_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [compare_entities_rdescriptor](compare_entities_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [compare_global_properties_rdescriptor](compare_global_properties_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [compare_inspections_rinspectionsummarycomparison](compare_inspections_rinspectionsummarycomparison.md) *(from inspect/brep/compare.py)* `inspection namespace`
- [compare_material_rdescriptor](compare_material_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [compare_material_region_rdescriptor](compare_material_region_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [compare_model_to_inspection_rentityinspectionparity](compare_model_to_inspection_rentityinspectionparity.md) *(from inspect/brep/parity.py)* `inspection namespace`
- [compare_sections_batch_rdescriptor](compare_sections_batch_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [compare_sections_rdescriptor](compare_sections_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [compare_shape_slices_rslicecomparison](compare_shape_slices_rslicecomparison.md) *(from inspect/brep/slices.py)* `inspection namespace`
- [compare_shapes_rbrepcomparison](compare_shapes_rbrepcomparison.md) *(from inspect/brep/compare.py)* `inspection namespace`
- [compare_step_slices_rslicecomparison](compare_step_slices_rslicecomparison.md) *(from inspect/brep/slices.py)* `inspection namespace`
- [compare_step_to_inspection_rentityinspectionparity](compare_step_to_inspection_rentityinspectionparity.md) *(from inspect/brep/parity.py)* `inspection namespace`
- [compare_steps_rbrepcomparison](compare_steps_rbrepcomparison.md) *(from inspect/brep/compare.py)* `inspection namespace`
- [copy_step_region_rpath](copy_step_region_rpath.md) *(from inspect/brep/snapshots.py)* `inspection namespace`
- [evaluate_reconstruction_rdescriptor](evaluate_reconstruction_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [fit_face_analytic_rdescriptor](fit_face_analytic_rdescriptor.md) *(from inspect/brep/fitting.py)* `inspection namespace`
- [index_shape_rbrepmodel](index_shape_rbrepmodel.md) *(from inspect/brep/model.py)* `inspection namespace`
- [inspect_difference_regions_rdescriptor](inspect_difference_regions_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [inspect_face_boundaries_rdescriptor](inspect_face_boundaries_rdescriptor.md) *(from inspect/brep/queries.py)* `inspection namespace`
- [inspect_manufacturing_hints_rdescriptor](inspect_manufacturing_hints_rdescriptor.md) *(from inspect/brep/manufacturing.py)* `inspection namespace`
- [inspect_nearby_entities_rdescriptor](inspect_nearby_entities_rdescriptor.md) *(from inspect/brep/diagnostics.py)* `inspection namespace`
- [inspect_point_rdescriptor](inspect_point_rdescriptor.md) *(from inspect/brep/queries.py)* `inspection namespace`
- [inspect_section_rdescriptor](inspect_section_rdescriptor.md) *(from inspect/brep/queries.py)* `inspection namespace`
- [inspect_shape_rbrepinspection](inspect_shape_rbrepinspection.md) *(from inspect/brep/inspect.py)* `inspection namespace`
- [inspect_step_components_rdescriptorlist](inspect_step_components_rdescriptorlist.md) *(from inspect/brep/render.py)* `inspection namespace`
- [inspect_step_entity_rdescriptor](inspect_step_entity_rdescriptor.md) *(from inspect/brep/model.py)* `inspection namespace`
- [inspect_step_rbrepinspection](inspect_step_rbrepinspection.md) *(from inspect/brep/inspect.py)* `inspection namespace`
- [inspect_step_rsummary](inspect_step_rsummary.md) *(from inspect/brep/model.py)* `inspection namespace`
- [inspect_topology_neighborhood_rdescriptor](inspect_topology_neighborhood_rdescriptor.md) *(from inspect/brep/queries.py)* `inspection namespace`
- [inspect_topology_rdescriptor](inspect_topology_rdescriptor.md) *(from inspect/brep/topology_inspection.py)* `inspection namespace`
- [load_step_rbrepmodel](load_step_rbrepmodel.md) *(from inspect/brep/model.py)* `inspection namespace`
- [load_step_rshape](load_step_rshape.md) *(from inspect/brep/io.py)* `inspection namespace`
- [make_center_slice_specs_rslicespeclist](make_center_slice_specs_rslicespeclist.md) *(from inspect/brep/slices.py)* `inspection namespace`
- [measure_entity_relation_rdescriptor](measure_entity_relation_rdescriptor.md) *(from inspect/brep/queries.py)* `inspection namespace`
- [measure_shape_mass_rtuple](measure_shape_mass_rtuple.md) *(from inspect/brep/io.py)* `inspection namespace`
- [render_entity_kind_maps_rpath](render_entity_kind_maps_rpath.md) *(from inspect/brep/render.py)* `inspection namespace`
- [render_entity_map_rpath](render_entity_map_rpath.md) *(from inspect/brep/render.py)* `inspection namespace`
- [render_manufacturing_hints_rpath](render_manufacturing_hints_rpath.md) *(from inspect/brep/manufacturing.py)* `inspection namespace`
- [render_region_rpath](render_region_rpath.md) *(from inspect/brep/render.py)* `inspection namespace`
- [render_shape_views_rpath](render_shape_views_rpath.md) *(from inspect/brep/render.py)* `inspection namespace`
- [render_step_comparison_rpath](render_step_comparison_rpath.md) *(from inspect/brep/render.py)* `inspection namespace`
- [render_step_components_colored_rpath](render_step_components_colored_rpath.md) *(from inspect/brep/render.py)* `inspection namespace`
- [render_step_components_rpath](render_step_components_rpath.md) *(from inspect/brep/render.py)* `inspection namespace`
- [render_step_views_rpath](render_step_views_rpath.md) *(from inspect/brep/render.py)* `inspection namespace`
- [select_region_entities_rdescriptor](select_region_entities_rdescriptor.md) *(from inspect/brep/queries.py)* `inspection namespace`
- [track_section_contours_rdescriptor](track_section_contours_rdescriptor.md) *(from inspect/brep/section_tracking.py)* `inspection namespace`
- [validate_step_roundtrip_rdescriptor](validate_step_roundtrip_rdescriptor.md) *(from inspect/brep/persistence.py)* `inspection namespace`

## Drawing Inspection

- [DrawingCalibration](DrawingCalibration.md) *(from inspect/drawing/calibrate.py)* `drawing-inspection namespace`
- [DrawingMeasurements](DrawingMeasurements.md) *(from inspect/drawing/calibrate.py)* `drawing-inspection namespace`
- [DrawingSectionDimensions](DrawingSectionDimensions.md) *(from inspect/drawing/section.py)* `drawing-inspection namespace`
- [DrawingStrokes](DrawingStrokes.md) *(from inspect/drawing/geometry.py)* `drawing-inspection namespace`
- [DrawingSummary](DrawingSummary.md) *(from inspect/drawing/summary.py)* `drawing-inspection namespace`
- [DrawingText](DrawingText.md) *(from inspect/drawing/text.py)* `drawing-inspection namespace`
- [assess_dimension_rverdict](assess_dimension_rverdict.md) *(from inspect/drawing/evidence.py)* `drawing-inspection namespace`
- [build_section_annotation_rrecord](build_section_annotation_rrecord.md) *(from inspect/drawing/evidence.py)* `drawing-inspection namespace`
- [calibrate_drawing_scale_rcalibration](calibrate_drawing_scale_rcalibration.md) *(from inspect/drawing/calibrate.py)* `drawing-inspection namespace`
- [extract_drawing_primitives_rstrokes](extract_drawing_primitives_rstrokes.md) *(from inspect/drawing/geometry.py)* `drawing-inspection namespace`
- [extract_drawing_text_rwords](extract_drawing_text_rwords.md) *(from inspect/drawing/text.py)* `drawing-inspection namespace`
- [inspect_drawing_coordinates_rreport](inspect_drawing_coordinates_rreport.md) *(from inspect/drawing/preflight.py)* `drawing-inspection namespace`
- [inspect_drawing_rsummary](inspect_drawing_rsummary.md) *(from inspect/drawing/summary.py)* `drawing-inspection namespace`
- [measure_drawing_rmeasurements](measure_drawing_rmeasurements.md) *(from inspect/drawing/calibrate.py)* `drawing-inspection namespace`
- [measure_model_section_rdimensions](measure_model_section_rdimensions.md) *(from inspect/drawing/section.py)* `drawing-inspection namespace`
- [render_drawing_view_rpath](render_drawing_view_rpath.md) *(from inspect/drawing/render.py)* `drawing-inspection namespace`
- [render_model_section_rpath](render_model_section_rpath.md) *(from inspect/drawing/section.py)* `drawing-inspection namespace`
- [summarize_dimension_coverage_rreport](summarize_dimension_coverage_rreport.md) *(from inspect/drawing/evidence.py)* `drawing-inspection namespace`
- [validate_section_annotations_rreport](validate_section_annotations_rreport.md) *(from inspect/drawing/evidence.py)* `drawing-inspection namespace`

## Product Build

- [AssemblyBuildResult](AssemblyBuildResult.md) *(from build/results.py)* `top-level`
- [FileInput](FileInput.md) *(from build/dependencies.py)* `top-level`
- [PartBuildResult](PartBuildResult.md) *(from build/results.py)* `top-level`
- [assemble](assemble.md) *(from build/assembly_builder.py)* `top-level`
- [file_input](file_input.md) *(from build/dependencies.py)* `top-level`
- [part](part_function.md) *(from build/part_builder.py)* `top-level`

## Notebook Runtime

- [CellReport](CellReport.md) *(from runtime/runner.py)* `notebook runtime`
- [NotebookConfig](NotebookConfig.md) *(from runtime/config.py)* `notebook runtime`
- [NotebookRun](NotebookRun.md) *(from runtime/runner.py)* `notebook runtime`
- [notebook_id](notebook_id.md) *(from runtime/executor.py)* `top-level`
- [run_notebook](run_notebook.md) *(from runtime/runner.py)* `notebook runtime`
- [use](use.md) *(from runtime/runner.py)* `top-level`

## Reconstruction Evaluation

- [EvaluationConfig](EvaluationConfig.md) *(from inverse_engineer/brep/evaluation.py)* `reverse-engineering evaluator`
- [SectionEvaluationConfig](SectionEvaluationConfig.md) *(from inverse_engineer/brep/evaluation.py)* `reverse-engineering evaluator`
- [classify_benchmark_result](classify_benchmark_result.md) *(from inverse_engineer/brep/evaluation.py)* `reverse-engineering evaluator`
- [inspect_benchmark_step](inspect_benchmark_step.md) *(from inverse_engineer/brep/evaluation.py)* `reverse-engineering evaluator`
- [run_comparison_bundle](run_comparison_bundle.md) *(from inverse_engineer/brep/evaluation.py)* `reverse-engineering evaluator`

## Engineering Drawings

- [CenterDecl](CenterDecl.md) *(from dxf_engine/model.py)* `submodule:dxf_engine/model`
- [DatumDecl](DatumDecl.md) *(from dxf_engine/model.py)* `submodule:dxf_engine/model`
- [DimDecl](DimDecl.md) *(from dxf_engine/model.py)* `submodule:dxf_engine/model`
- [LeaderDecl](LeaderDecl.md) *(from dxf_engine/model.py)* `submodule:dxf_engine/model`
- [Resolved](Resolved.md) *(from dxf_engine/planner.py)* `submodule:dxf_engine/planner`
- [SheetDecl](SheetDecl.md) *(from dxf_engine/model.py)* `submodule:dxf_engine/model`
- [SheetPlan](SheetPlan.md) *(from dxf_engine/planner.py)* `submodule:dxf_engine/planner`
- [ViewDecl](ViewDecl.md) *(from dxf_engine/model.py)* `submodule:dxf_engine/model`
- [render_plan](render_plan.md) *(from dxf_engine/render.py)* `submodule:dxf_engine/render`

## Other

- [Assembly](Assembly.md) *(from product/assembly.py)* `top-level`
- [CaptureResult](CaptureResult.md) *(from product/capture.py)* `top-level`
- [Component](Component.md) *(from product/assembly.py)* `top-level`
- [Connector](Connector.md) *(from product/connector.py)* `top-level`
- [ConnectorAnchor](ConnectorAnchor.md) *(from product/connector.py)* `top-level`
- [ConnectorRef](ConnectorRef.md) *(from product/connector.py)* `top-level`
- [Constraint](Constraint.md) *(from product/constraint.py)* `top-level`
- [ConstraintReport](ConstraintReport.md) *(from product/constraint.py)* `top-level`
- [ConstraintResidual](ConstraintResidual.md) *(from product/constraint.py)* `top-level`
- [GeometryRef](GeometryRef.md) *(from product/connector.py)* `top-level`
- [Material](Material.md) *(from product/material.py)* `top-level`
- [Part](Part.md) *(from product/part.py)* `top-level`
- [Placement](Placement.md) *(from product/placement.py)* `top-level`
- [ProductPackage](ProductPackage.md) *(from product/packages.py)* `top-level`
- [ProductPackageError](ProductPackageError.md) *(from product/packages.py)* `top-level`
- [PublicConnectorRef](PublicConnectorRef.md) *(from product/assembly.py)* `top-level`
- [ScalarLimit](ScalarLimit.md) *(from product/constraint.py)* `top-level`
- [SemanticDelta](SemanticDelta.md) *(from topology/model.py)* `top-level`
- [SemanticRef](SemanticRef.md) *(from topology/model.py)* `top-level`
- [SurfaceBoundary](SurfaceBoundary.md) *(from operators/geometry.py)* `top-level`
- [SurfaceFillingSettings](SurfaceFillingSettings.md) *(from operators/geometry.py)* `top-level`
- [add_arc_rsketch](add_arc_rsketch.md) *(from operators/sketch.py)* `top-level`
- [add_belt_constraint_rassembly](add_belt_constraint_rassembly.md) *(from operators/product.py)* `top-level`
- [add_bspline_rsketch](add_bspline_rsketch.md) *(from operators/sketch.py)* `top-level`
- [add_circle_rsketch](add_circle_rsketch.md) *(from operators/sketch.py)* `top-level`
- [add_component_rassembly](add_component_rassembly.md) *(from operators/product.py)* `top-level`
- [add_connector_rpart](add_connector_rpart.md) *(from operators/product.py)* `top-level`
- [add_ellipse_rsketch](add_ellipse_rsketch.md) *(from operators/sketch.py)* `top-level`
- [add_fixed_constraint_rassembly](add_fixed_constraint_rassembly.md) *(from operators/product.py)* `top-level`
- [add_gear_constraint_rassembly](add_gear_constraint_rassembly.md) *(from operators/product.py)* `top-level`
- [add_line_rsketch](add_line_rsketch.md) *(from operators/sketch.py)* `top-level`
- [add_point_rsketch](add_point_rsketch.md) *(from operators/sketch.py)* `top-level`
- [add_prismatic_constraint_rassembly](add_prismatic_constraint_rassembly.md) *(from operators/product.py)* `top-level`
- [add_rack_pinion_constraint_rassembly](add_rack_pinion_constraint_rassembly.md) *(from operators/product.py)* `top-level`
- [add_revolute_constraint_rassembly](add_revolute_constraint_rassembly.md) *(from operators/product.py)* `top-level`
- [and_](and_.md) *(from ql.py)* `submodule:ql`
- [assign_material_rpart](assign_material_rpart.md) *(from operators/product.py)* `top-level`
- [canonical_frame](canonical_frame.md) *(from product/placement.py)* `submodule:product/placement`
- [capture](capture.md) *(from product/capture.py)* `top-level`
- [constrain_angle_rsketch](constrain_angle_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_coincident_rsketch](constrain_coincident_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_collinear_rsketch](constrain_collinear_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_concentric_rsketch](constrain_concentric_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_connect_rsketch](constrain_connect_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_diameter_rsketch](constrain_diameter_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_distance_rsketch](constrain_distance_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_distance_x_rsketch](constrain_distance_x_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_distance_y_rsketch](constrain_distance_y_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_equal_length_rsketch](constrain_equal_length_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_equal_radius_rsketch](constrain_equal_radius_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_fix_rsketch](constrain_fix_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_horizontal_rsketch](constrain_horizontal_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_length_rsketch](constrain_length_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_line_distance_rsketch](constrain_line_distance_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_major_radius_rsketch](constrain_major_radius_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_midpoint_points_rsketch](constrain_midpoint_points_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_midpoint_rsketch](constrain_midpoint_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_minor_radius_rsketch](constrain_minor_radius_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_mirror_rsketch](constrain_mirror_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_normal_rsketch](constrain_normal_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_parallel_rsketch](constrain_parallel_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_perpendicular_rsketch](constrain_perpendicular_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_point_on_rsketch](constrain_point_on_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_points_horizontal_rsketch](constrain_points_horizontal_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_points_vertical_rsketch](constrain_points_vertical_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_radius_rsketch](constrain_radius_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_symmetric_rsketch](constrain_symmetric_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_tangent_rsketch](constrain_tangent_rsketch.md) *(from operators/sketch.py)* `top-level`
- [constrain_vertical_rsketch](constrain_vertical_rsketch.md) *(from operators/sketch.py)* `top-level`
- [explain_tag](explain_tag.md) *(from operators/selection.py)* `top-level`
- [fill_holes_rshell](fill_holes_rshell.md) *(from operators/geometry.py)* `top-level`
- [fit_point_grid_rface](fit_point_grid_rface.md) *(from operators/geometry.py)* `top-level`
- [free_boundaries_rwirelist](free_boundaries_rwirelist.md) *(from operators/geometry.py)* `top-level`
- [geo](geo.md) *(from ql.py)* `submodule:ql`
- [get_sketch_entity_rsketchref](get_sketch_entity_rsketchref.md) *(from operators/sketch.py)* `top-level`
- [get_sketch_point_rsketchref](get_sketch_point_rsketchref.md) *(from operators/sketch.py)* `top-level`
- [ground_component_rassembly](ground_component_rassembly.md) *(from operators/product.py)* `top-level`
- [identity_placement_rplacement](identity_placement_rplacement.md) *(from operators/product.py)* `top-level`
- [inspect_assembly_constraints_rconstraintreport](inspect_assembly_constraints_rconstraintreport.md) *(from operators/product.py)* `top-level`
- [inspect_sketch_rsketchresult](inspect_sketch_rsketchresult.md) *(from operators/sketch.py)* `top-level`
- [linear_pattern_rsolidlist](linear_pattern_rsolidlist.md) *(from operators/transform.py)* `top-level`
- [load_brep_region_rshell](load_brep_region_rshell.md) *(from operators/geometry.py)* `top-level`
- [load_brep_region_rsolid](load_brep_region_rsolid.md) *(from operators/geometry.py)* `top-level`
- [measure_constraint_residual_rconstraintresidual](measure_constraint_residual_rconstraintresidual.md) *(from operators/product.py)* `top-level`
- [meta](meta.md) *(from ql.py)* `submodule:ql`
- [not_](not_.md) *(from ql.py)* `submodule:ql`
- [operation_event](operation_event.md) *(from ql.py)* `submodule:ql`
- [or_](or_.md) *(from ql.py)* `submodule:ql`
- [origin_role](origin_role.md) *(from ql.py)* `submodule:ql`
- [output_role](output_role.md) *(from ql.py)* `submodule:ql`
- [place_component_rassembly](place_component_rassembly.md) *(from operators/product.py)* `top-level`
- [placement_frame_mm](placement_frame_mm.md) *(from product/placement.py)* `submodule:product/placement`
- [placement_from_canonical](placement_from_canonical.md) *(from product/placement.py)* `submodule:product/placement`
- [placement_ticks](placement_ticks.md) *(from product/placement.py)* `submodule:product/placement`
- [radial_pattern_rsolidlist](radial_pattern_rsolidlist.md) *(from operators/transform.py)* `top-level`
- [render_screenshot_rpath](render_screenshot_rpath.md) *(from operators/features.py)* `top-level`
- [select](select.md) *(from ql.py)* `submodule:ql`
- [set_public_connector_rassembly](set_public_connector_rassembly.md) *(from operators/product.py)* `top-level`
- [sew_faces_rshell](sew_faces_rshell.md) *(from operators/geometry.py)* `top-level`
- [shells](shells.md) *(from ql.py)* `submodule:ql`
- [solve_assembly_constraints_rassembly](solve_assembly_constraints_rassembly.md) *(from operators/product.py)* `top-level`
- [source_binding](source_binding.md) *(from ql.py)* `submodule:ql`
- [source_topology](source_topology.md) *(from ql.py)* `submodule:ql`
- [tag](tag.md) *(from ql.py)* `submodule:ql`
- [trim_surface_rface](trim_surface_rface.md) *(from operators/geometry.py)* `top-level`
- [twisted_sweep_rsolid](twisted_sweep_rsolid.md) *(from operators/features.py)* `top-level`
- [unground_component_rassembly](unground_component_rassembly.md) *(from operators/product.py)* `top-level`
- [validate_placement_ticks](validate_placement_ticks.md) *(from product/placement.py)* `submodule:product/placement`
- [value](value.md) *(from ql.py)* `submodule:ql`
