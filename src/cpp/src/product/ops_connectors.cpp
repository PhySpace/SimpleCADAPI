// Connector operators and the small value constructors that go with them.
#include "scad/core/error.hpp"
#include "scad/product/guard.hpp"
#include "scad/product/operators.hpp"
#include "scad/reactive/lineage.hpp"
#include "scad/reactive/session.hpp"
#include "record.hpp"

namespace scad::product {

using namespace detail;

namespace {

Value optional_name(const OptionalString& name) {
  return name ? Value(*name) : Value();
}

// The graph node a connector's geometry was picked from, when a session is recording: a face or
// edge of a recorded output gets its selection node here (the operator that follows would create it
// anyway), so the connector can name it.
OptionalString source_node_id(const Shape& shape) {
  reactive::Session* session = reactive::Session::active_session();
  if (session == nullptr || current_recorder() != session)
    return std::nullopt;
  if (const auto lineage = reactive::lineage_of(shape))
    return lineage->node_id;
  if (const auto ref = reactive::topo_ref_of(shape)) {
    // Recording the pick is best effort: the shape's producer may belong to another session (a cell's value restored
    // from the cache), which this one does not hold outputs for.
    try {
      session->record_selection(session->output(ref->node_id, ref->output_slot), {shape}, "");
    } catch (const reactive::KeyError&) {
      return std::nullopt;
    }
    if (const auto picked = reactive::lineage_of(shape))
      return picked->node_id;
  }
  return std::nullopt;
}

Connector geometry_connector(const char* op, const std::string& connector_id, const Shape& shape,
                             const OptionalString& name, bool flip) {
  const OptionalString source = source_node_id(shape);
  GeometryRef ref(shape_kind_token(shape), source, make_geo_selector(shape), flip);
  Connector connector(connector_id, std::move(ref), name);
  record_value(
      [&] {
        OpRecord record = op_record(op, connector.to_dict());
        record.inputs.push_back(OpInput{shape, "shape"});
        return record;
      },
      connector);
  return connector;
}

}  // namespace

Connector make_face_connector_rconnector(const std::string& connector_id, const Face& face, const OptionalString& name,
                                         bool flip) {
  return guard_operation("make_face_connector_rconnector", [&] {
    return geometry_connector("make_face_connector_rconnector", connector_id, face, name, flip);
  });
}

Connector make_edge_connector_rconnector(const std::string& connector_id, const Edge& edge, const OptionalString& name,
                                         bool flip) {
  return guard_operation("make_edge_connector_rconnector", [&] {
    return geometry_connector("make_edge_connector_rconnector", connector_id, edge, name, flip);
  });
}

Connector make_vertex_connector_rconnector(const std::string& connector_id, const Vertex& vertex,
                                           const OptionalString& name, bool flip) {
  return guard_operation("make_vertex_connector_rconnector", [&] {
    return geometry_connector("make_vertex_connector_rconnector", connector_id, vertex, name, flip);
  });
}

Connector make_placement_connector_rconnector(const std::string& connector_id, const Placement& placement,
                                              const OptionalString& name) {
  return guard_operation("make_placement_connector_rconnector", [&] {
    Connector connector(connector_id, std::nullopt, name, ConnectorAnchor(placement));
    record_value(
        [&] {
          Value params = Value::object();
          params.set("connector_id", connector.connector_id());
          params.set("placement", placement.to_dict());
          params.set("name", optional_name(connector.name()));
          return op_record("make_placement_connector_rconnector", std::move(params));
        },
        connector, placement);
    return connector;
  });
}

PartPtr add_connector_rpart(const Part& part, const Connector& connector) {
  return guard_operation("add_connector_rpart", [&] {
    auto result = std::make_shared<const Part>(part.with_connector(connector));
    record_value(
        [&] {
          Value params = Value::object();
          params.set("part_id", part.part_id());
          params.set("connector_id", connector.connector_id());
          OpRecord record = op_record("make_add_connector_rpart", std::move(params));
          Value metadata = Value::object();
          metadata.set("connector", connector.to_dict());
          record.semantic_delta = semantic_modified("Part", part.part_id(), std::move(metadata));
          return record;
        },
        result, part, connector);
    return result;
  });
}

AssemblyPtr set_public_connector_rassembly(const Assembly& assembly, const std::string& public_connector_id,
                                           const std::string& source_component_id,
                                           const std::string& source_connector_id, const OptionalString& name) {
  return guard_operation("set_public_connector_rassembly", [&] {
    const PublicConnectorRef pub(public_connector_id, source_component_id, source_connector_id, name);
    std::shared_ptr<const Assembly> result;
    try {
      result = std::make_shared<const Assembly>(assembly.with_public_connector(pub));
    } catch (const reactive::KeyError& error) {
      throw ValueError("missing component or connector for public connector: " + python_repr(error.what()));
    }
    record_value(
        [&] {
          Value params = Value::object();
          params.set("assembly_id", assembly.assembly_id());
          params.set("public_connector_id", pub.public_connector_id);
          params.set("source_component_id", pub.component_id);
          params.set("source_connector_id", pub.connector_id);
          params.set("name", optional_name(pub.name));
          OpRecord record = op_record("make_set_public_connector_rassembly", std::move(params));
          Value metadata = Value::object();
          metadata.set("public_connector", pub.to_dict());
          record.semantic_delta = semantic_modified("Assembly", assembly.assembly_id(), std::move(metadata));
          return record;
        },
        result, assembly);
    return result;
  });
}

ConnectorRef make_connector_ref_rconnectorref(const std::string& component_id, const std::string& connector_id) {
  return guard_operation("make_connector_ref_rconnectorref", [&] {
    ConnectorRef ref(component_id, connector_id);
    record_value([&] { return op_record("make_connector_ref_rconnectorref", ref.to_dict()); }, ref);
    return ref;
  });
}

ScalarLimit make_scalar_limit_rscalarlimit(const Scalar& lower_value, const Scalar& upper_value) {
  return guard_operation("make_scalar_limit_rscalarlimit", [&] {
    ScalarLimit limit(scalar_float(lower_value), scalar_float(upper_value));
    record_value([&] { return op_record("make_scalar_limit_rscalarlimit", limit.to_dict()); }, limit);
    return limit;
  });
}

}  // namespace scad::product
