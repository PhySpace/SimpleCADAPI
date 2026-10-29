// Materials, placements, parts, and the assembly structure operators.
#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/ops/geometry/params.hpp"
#include "scad/product/guard.hpp"
#include "scad/product/operators.hpp"
#include "scad/reactive/lineage.hpp"
#include "record.hpp"

namespace scad::product {

using namespace detail;

namespace {

// The recorded reference of a Part's body, as `_serialize_shape_refs` writes it.
Value input_refs(const Shape& body) {
  std::optional<TopoRef> ref = reactive::topo_ref_of(body);
  if (!ref) {
    if (const auto lineage = reactive::lineage_of(body)) {
      ref = TopoRef{lineage->graph_id, lineage->node_id, lineage->output_slot, body.kind(), body.topo_id()};
    }
  }
  Value refs = Value::array();
  if (!ref)
    return refs;
  const kernel::BoundingBox box = body.bounding_box();
  Value hint = Value::object();
  hint.set("kind", std::string(kind_name(body.kind())));
  Value tags = Value::array();
  for (const std::string& tag : body.list_tags())
    tags.push_back(tag);
  hint.set("tags", std::move(tags));
  hint.set("volume", Solid(body).volume());
  Value bounds = Value::object();
  bounds.set("min", to_array({box.xmin, box.ymin, box.zmin}));
  bounds.set("max", to_array({box.xmax, box.ymax, box.zmax}));
  hint.set("bbox", std::move(bounds));
  Value data = to_value(*ref);
  data.set("selector_hint", std::move(hint));
  refs.push_back(std::move(data));
  return refs;
}

// A coordinate triple as np.asarray(dtype=float) reads it: a NaN literal passes, and is rejected by
// the coordinate system's own structured error, as in Python.
Vec3 raw_point(const Scalar3& point) {
  const auto number = [](const Scalar& s) { return s.symbolic() ? s.value() : s.literal(); };
  return {number(point[0]), number(point[1]), number(point[2])};
}

Value optional_name(const OptionalString& name) {
  return name ? Value(*name) : Value();
}

}  // namespace

Material make_material_rmaterial(const std::string& material_id, const OptionalString& name,
                                 const std::optional<Scalar>& density, const OptionalString& density_unit,
                                 const std::optional<Vec3>& color) {
  return guard_operation("make_material_rmaterial", [&] {
    OptionalDouble density_value;
    if (density)
      density_value = scalar_float(*density);
    Material material(material_id, name, density_value, density_unit, color);
    reserve_semantic_id("material", material.material_id());
    record_value(
        [&] {
          OpRecord record = op_record("make_material_rmaterial", material.to_dict());
          record.semantic_delta = semantic_created("Material", material.material_id(), material.to_dict());
          return record;
        },
        material);
    return material;
  });
}

Placement make_placement_rplacement(const Scalar3& origin, const Scalar3& x_axis, const Scalar3& y_axis) {
  return guard_operation("make_placement_rplacement", [&] {
    const CoordinateSystem& cs = current_cs();
    Placement placement(cs.transform_point(raw_point(origin)), cs.transform_vector(raw_point(x_axis)),
                        cs.transform_vector(raw_point(y_axis)));
    record_value(
        [&] {
          return OpParams("make_placement_rplacement")
              .point("origin", origin)
              .point("x_axis", x_axis)
              .point("y_axis", y_axis)
              .take();
        },
        placement);
    return placement;
  });
}

Placement identity_placement_rplacement() {
  return guard_operation("identity_placement_rplacement", [&] {
    const CoordinateSystem& cs = current_cs();
    Placement placement(cs.origin(), cs.x_axis(), cs.y_axis());
    record_value([&] { return op_record("make_identity_placement_rplacement", Value::object()); }, placement);
    return placement;
  });
}

PartPtr make_part_rpart(const std::string& part_id, const Solid& body, const OptionalString& name) {
  return guard_operation("make_part_rpart", [&] {
    auto part = std::make_shared<const Part>(part_id, body, name);
    reserve_semantic_id("part", part->part_id());
    record_value(
        [&] {
          Value params = Value::object();
          params.set("part_id", part->part_id());
          params.set("name", optional_name(part->name()));
          params.set("input_refs", input_refs(body));
          OpRecord record = op_record("make_part_rpart", std::move(params));
          record.inputs.push_back(OpInput{body, "body"});
          record.semantic_delta = semantic_created("Part", part->part_id(), part->to_dict());
          return record;
        },
        part);
    return part;
  });
}

PartPtr assign_material_rpart(const Part& part, const Material& material) {
  return guard_operation("assign_material_rpart", [&] {
    auto result = std::make_shared<const Part>(part.with_material(material));
    record_value(
        [&] {
          Value params = Value::object();
          params.set("part_id", part.part_id());
          params.set("material_id", material.material_id());
          params.set("material", material.to_dict());
          OpRecord record = op_record("make_assign_material_rpart", std::move(params));
          Value metadata = Value::object();
          metadata.set("material_id", material.material_id());
          record.semantic_delta = semantic_modified("Part", part.part_id(), std::move(metadata));
          return record;
        },
        result, part, material);
    return result;
  });
}

AssemblyPtr make_assembly_rassembly(const std::string& assembly_id, const OptionalString& name) {
  return guard_operation("make_assembly_rassembly", [&] {
    auto assembly = std::make_shared<const Assembly>(assembly_id, name);
    reserve_semantic_id("assembly", assembly->assembly_id());
    record_value(
        [&] {
          Value params = Value::object();
          params.set("assembly_id", assembly->assembly_id());
          params.set("name", optional_name(assembly->name()));
          OpRecord record = op_record("make_assembly_rassembly", std::move(params));
          record.semantic_delta = semantic_created("Assembly", assembly->assembly_id(), assembly->to_dict());
          return record;
        },
        assembly);
    return assembly;
  });
}

AssemblyPtr add_component_rassembly(const Assembly& assembly, const Item& item, const std::string& component_id,
                                    const Placement& placement, const OptionalString& name) {
  return guard_operation("add_component_rassembly", [&] {
    const Component component(component_id, item, placement, name);
    auto result = std::make_shared<const Assembly>(assembly.with_component(component));
    record_value(
        [&] {
          Value params = Value::object();
          params.set("assembly_id", assembly.assembly_id());
          params.set("component_id", component.component_id);
          params.set("name", optional_name(component.name));
          params.set("item_kind", std::string(item_kind(item)));
          params.set("item_id", item_id(item));
          params.set("placement", placement.to_dict());
          OpRecord record = op_record("make_add_component_rassembly", std::move(params));
          SemanticDelta delta;
          delta.created.push_back(
              {"pending", "pending", "Component", assembly.assembly_id() + ":" + component.component_id});
          delta.modified.push_back({"pending", "pending", "Assembly", assembly.assembly_id()});
          delta.metadata.set("component", component.to_dict());
          record.semantic_delta = std::move(delta);
          return record;
        },
        result, assembly, item, placement);
    return result;
  });
}

AssemblyPtr place_component_rassembly(const Assembly& assembly, const std::string& component_id,
                                      const Placement& placement) {
  return guard_operation("place_component_rassembly", [&] {
    auto result = std::make_shared<const Assembly>(assembly.with_component_placement(component_id, placement));
    record_value(
        [&] {
          Value params = Value::object();
          params.set("assembly_id", assembly.assembly_id());
          params.set("component_id", component_id);
          params.set("placement", placement.to_dict());
          OpRecord record = op_record("make_place_component_rassembly", std::move(params));
          Value metadata = Value::object();
          metadata.set("placement", placement.to_dict());
          record.semantic_delta =
              semantic_modified("Component", assembly.assembly_id() + ":" + component_id, std::move(metadata));
          return record;
        },
        result, assembly, placement);
    return result;
  });
}

}  // namespace scad::product
