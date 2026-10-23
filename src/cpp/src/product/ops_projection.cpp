// make_compound_from_assembly_rcompound: an assembly flattened into one Compound.
#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/transforms.hpp"
#include "scad/product/guard.hpp"
#include "scad/product/operators.hpp"
#include "record.hpp"

namespace scad::product {

using namespace detail;

namespace {

// Every Part body below `item`, placed by `placement` composed with the component chain.
void collect_placed_solids(const Item& item, const Placement& placement, std::vector<Solid>& out) {
  if (const auto* part = std::get_if<PartPtr>(&item)) {
    out.emplace_back(kernel::place_shape((*part)->body().wrapped(), placement.origin(), placement.x_axis(),
                                         placement.y_axis(), placement.z_axis()));
    return;
  }
  for (const Component& component : std::get<AssemblyPtr>(item)->components()) {
    collect_placed_solids(component.item, placement.compose(component.placement), out);
  }
}

}  // namespace

Compound make_compound_from_assembly_rcompound(const Assembly& assembly) {
  return guard_operation("make_compound_from_assembly_rcompound", [&] {
    if (assembly.components().empty()) throw ValueError("assembly must contain at least one component to project");
    std::vector<Solid> solids;
    const Placement identity = identity_placement();
    for (const Component& component : assembly.components()) {
      collect_placed_solids(component.item, identity.compose(component.placement), solids);
    }
    if (solids.empty()) throw ValueError("assembly projection produced no solids");

    BRep_Builder builder;
    TopoDS_Compound shape;
    builder.MakeCompound(shape);
    for (const Solid& solid : solids) builder.Add(shape, solid.wrapped());
    Compound compound(shape);

    Value projection = Value::object();
    projection.set("assembly_id", assembly.assembly_id());
    projection.set("component_count", static_cast<std::int64_t>(assembly.components().size()));
    projection.set("solid_count", static_cast<std::int64_t>(solids.size()));
    compound.set_metadata("assembly_projection", std::move(projection));

    record_shape(compound, [&] {
      Value params = Value::object();
      params.set("assembly_id", assembly.assembly_id());
      params.set("component_count", static_cast<std::int64_t>(assembly.components().size()));
      OpRecord record = op_record("make_compound_from_assembly_rcompound", std::move(params));
      Value metadata = Value::object();
      metadata.set("projection", "compound");
      metadata.set("solid_count", static_cast<std::int64_t>(solids.size()));
      record.semantic_delta = semantic_modified("Assembly", assembly.assembly_id(), std::move(metadata));
      return record;
    });
    return compound;
  });
}

}  // namespace scad::product
