"""OCP-native STEP/BREP inspection utilities.

These functions are diagnostic tools, not modeling operations. They do not
record graph nodes and are not supported inside replayable modeling scripts.
Import the namespace as ``simplecadapi.inspect.brep``.
"""

from .compare import (
    BRepComparison,
    InspectionSummaryComparison,
    compare_inspections_rinspectionsummarycomparison,
    compare_shapes_rbrepcomparison,
    compare_steps_rbrepcomparison,
)
from .diagnostics import (
    compare_boundary_distance_rdescriptor,
    compare_entities_rdescriptor,
    compare_global_properties_rdescriptor,
    compare_material_region_rdescriptor,
    compare_material_rdescriptor,
    compare_sections_batch_rdescriptor,
    compare_sections_rdescriptor,
    evaluate_reconstruction_rdescriptor,
    inspect_difference_regions_rdescriptor,
    inspect_nearby_entities_rdescriptor,
)
from .inspect import (
    BRepInspection,
    inspect_shape_rbrepinspection,
    inspect_step_rbrepinspection,
)
from .io import load_step_rshape
from .fitting import fit_face_analytic_rdescriptor
from .manufacturing import (
    inspect_manufacturing_hints_rdescriptor,
    render_manufacturing_hints_rpath,
)
from .section_tracking import track_section_contours_rdescriptor
from .model import (
    BRepEntityError,
    BRepModel,
    clear_step_model_cache_rnone,
    index_shape_rbrepmodel,
    inspect_step_entity_rdescriptor,
    inspect_step_rsummary,
    load_step_rbrepmodel,
)
from .parity import (
    EntityInspectionParity,
    compare_model_to_inspection_rentityinspectionparity,
    compare_step_to_inspection_rentityinspectionparity,
)
from .queries import (
    inspect_face_boundaries_rdescriptor,
    inspect_point_rdescriptor,
    inspect_section_rdescriptor,
    inspect_topology_neighborhood_rdescriptor,
    measure_entity_relation_rdescriptor,
    select_region_entities_rdescriptor,
)
from .render import (
    DEFAULT_VIEWS,
    inspect_step_components_rdescriptorlist,
    render_entity_kind_maps_rpath,
    render_entity_map_rpath,
    render_region_rpath,
    render_shape_views_rpath,
    render_step_components_colored_rpath,
    render_step_components_rpath,
    render_step_comparison_rpath,
    render_step_views_rpath,
)
from .slices import (
    SliceComparison,
    SlicePanelResult,
    SliceSpec,
    compare_shape_slices_rslicecomparison,
    compare_step_slices_rslicecomparison,
    make_center_slice_specs_rslicespeclist,
)
from .persistence import validate_step_roundtrip_rdescriptor
from .snapshots import copy_step_region_rpath
from .topology_inspection import inspect_topology_rdescriptor

__all__ = [
    "BRepComparison",
    "BRepEntityError",
    "BRepInspection",
    "BRepModel",
    "DEFAULT_VIEWS",
    "EntityInspectionParity",
    "InspectionSummaryComparison",
    "SliceComparison",
    "SlicePanelResult",
    "SliceSpec",
    "clear_step_model_cache_rnone",
    "compare_boundary_distance_rdescriptor",
    "compare_entities_rdescriptor",
    "compare_global_properties_rdescriptor",
    "compare_inspections_rinspectionsummarycomparison",
    "compare_material_rdescriptor",
    "compare_material_region_rdescriptor",
    "compare_model_to_inspection_rentityinspectionparity",
    "compare_sections_rdescriptor",
    "compare_sections_batch_rdescriptor",
    "compare_shape_slices_rslicecomparison",
    "compare_shapes_rbrepcomparison",
    "compare_step_slices_rslicecomparison",
    "compare_step_to_inspection_rentityinspectionparity",
    "compare_steps_rbrepcomparison",
    "copy_step_region_rpath",
    "evaluate_reconstruction_rdescriptor",
    "fit_face_analytic_rdescriptor",
    "index_shape_rbrepmodel",
    "inspect_difference_regions_rdescriptor",
    "inspect_face_boundaries_rdescriptor",
    "inspect_manufacturing_hints_rdescriptor",
    "inspect_nearby_entities_rdescriptor",
    "inspect_point_rdescriptor",
    "inspect_section_rdescriptor",
    "inspect_shape_rbrepinspection",
    "inspect_step_components_rdescriptorlist",
    "inspect_step_entity_rdescriptor",
    "inspect_step_rbrepinspection",
    "inspect_step_rsummary",
    "inspect_topology_neighborhood_rdescriptor",
    "inspect_topology_rdescriptor",
    "load_step_rbrepmodel",
    "load_step_rshape",
    "make_center_slice_specs_rslicespeclist",
    "track_section_contours_rdescriptor",
    "render_entity_kind_maps_rpath",
    "render_entity_map_rpath",
    "render_manufacturing_hints_rpath",
    "render_region_rpath",
    "render_shape_views_rpath",
    "render_step_components_colored_rpath",
    "render_step_components_rpath",
    "render_step_comparison_rpath",
    "render_step_views_rpath",
    "select_region_entities_rdescriptor",
    "validate_step_roundtrip_rdescriptor",
]

# Inspection is an evidence-gathering boundary, not a modeling operation. Patch
# the defining modules too so direct submodule imports enforce the same rule.
from functools import wraps as _wraps
from inspect import isfunction as _isfunction
import sys as _sys

from simplecadapi._cpp import get_active_session as _get_active_session
from simplecadapi._glue.bridge import accepts_ocp as _accepts_ocp


def _outside_model_graph(function):
    @_wraps(function)
    def checked(*args, **kwargs):
        if _get_active_session() is not None:
            raise RuntimeError(
                "simplecadapi.inspect.brep tools cannot run inside an active "
                "GraphSession; inspect exported geometry outside the modeling script"
            )
        return function(*args, **kwargs)

    return checked


for _public_name in __all__:
    _public_value = globals()[_public_name]
    if not _isfunction(_public_value):
        continue
    # a raw shape may be an OCP one (`shape.wrapped` is, when OCP is installed): the queries work on the SDK's own
    # OCCT, so such a shape is converted on the way in
    _checked_value = _accepts_ocp(_outside_model_graph(_public_value))
    globals()[_public_name] = _checked_value
    setattr(_sys.modules[_public_value.__module__], _public_name, _checked_value)

del _accepts_ocp, _checked_value, _isfunction, _outside_model_graph, _public_name, _public_value
