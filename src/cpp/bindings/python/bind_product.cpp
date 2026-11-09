// Python bindings for the "product" area: the 28 operators of simplecadapi/operators/product.py
// under their Python names, argument names and defaults.  The value classes are bound in
// bind_product_values.cpp.
//
// Every operator takes py::object for the arguments whose type Python checks inside its wrapped
// body, and converts them inside guard_operation, so a wrong type is the operation's
// SimpleCADError exactly as in Python (see bind_product_args.hpp).  The py::object arrives as a
// `AnyOf<Name>` (semantic_types.hpp), so the signature still says what each argument is.
#include "bind_product_args.hpp"

#include "scad/reactive/registry.hpp"

namespace {

using namespace scad;
using namespace scad::product_binding;
using sp::guard_operation;

// What each argument is, for the signature; the bodies still receive the py::object and check it themselves.
namespace names {
using py::detail::const_name;
using scad::pybind::kOr;
using scad::pybind::kOrNone;
using scad::pybind::type_name;
SCAD_SIGNATURE_NAME(Text, const_name("str"));
SCAD_SIGNATURE_NAME(TextOrNone, const_name("str | None"));
SCAD_SIGNATURE_NAME(Number, const_name("float | Expr"));
SCAD_SIGNATURE_NAME(NumberOrNone, const_name("float | Expr | None"));
SCAD_SIGNATURE_NAME(Bool, const_name("bool"));
SCAD_SIGNATURE_NAME(Color, scad::pybind::ColorTag::name + kOrNone);
SCAD_SIGNATURE_NAME(Length, scad::pybind::LengthTag::name);
SCAD_SIGNATURE_NAME(LengthOrNone, scad::pybind::LengthTag::name + kOrNone);
SCAD_SIGNATURE_NAME(AngleOrNone, scad::pybind::AngleTag::name + kOrNone);
SCAD_SIGNATURE_NAME(Point, scad::pybind::PointTag::name);
SCAD_SIGNATURE_NAME(PointOrNone, scad::pybind::PointTag::name + kOrNone);
SCAD_SIGNATURE_NAME(Direction, scad::pybind::DirectionTag::name);
SCAD_SIGNATURE_NAME(DirectionOrNone, scad::pybind::DirectionTag::name + kOrNone);
SCAD_SIGNATURE_NAME(Directions, const_name("dict[str, ") + scad::pybind::DirectionTag::name + const_name("] | None"));
SCAD_SIGNATURE_NAME(Weights, const_name("dict[str, float | Expr] | None"));
SCAD_SIGNATURE_NAME(Solid, type_name<scad::Solid>());
// make_part_rpart: one Solid (or the single piece of a split cut).
SCAD_SIGNATURE_NAME(SolidOrPieces, type_name<scad::Solid>() + kOr + const_name("collections.abc.Sequence[") +
                                       type_name<scad::Solid>() + const_name("]"));
SCAD_SIGNATURE_NAME(Face, type_name<scad::Face>());
SCAD_SIGNATURE_NAME(Edge, type_name<scad::Edge>());
SCAD_SIGNATURE_NAME(Vertex, type_name<scad::Vertex>());
SCAD_SIGNATURE_NAME(Part, type_name<sp::Part>());
SCAD_SIGNATURE_NAME(Assembly, type_name<sp::Assembly>());
SCAD_SIGNATURE_NAME(Item, type_name<sp::Part>() + kOr + type_name<sp::Assembly>());
SCAD_SIGNATURE_NAME(Placement, type_name<sp::Placement>());
SCAD_SIGNATURE_NAME(Material, type_name<sp::Material>());
SCAD_SIGNATURE_NAME(Connector, type_name<sp::Connector>());
SCAD_SIGNATURE_NAME(Ref, type_name<sp::ConnectorRef>());
SCAD_SIGNATURE_NAME(Limit, type_name<sp::ScalarLimit>() + kOrNone);
}  // namespace names

using scad::pybind::AnyOf;
using TextArg = AnyOf<names::Text>;
using NameArg = AnyOf<names::TextOrNone>;  // anything str() takes: a display name
using TextOrNoneArg = AnyOf<names::TextOrNone>;
using NumberArg = AnyOf<names::Number>;
using NumberOrNoneArg = AnyOf<names::NumberOrNone>;
using BoolArg = AnyOf<names::Bool>;  // any object, read by its truth value
using ColorArg = AnyOf<names::Color>;
using LengthArg = AnyOf<names::Length>;
using LengthOrNoneArg = AnyOf<names::LengthOrNone>;
using AngleOrNoneArg = AnyOf<names::AngleOrNone>;
using PointArg = AnyOf<names::Point>;
using PointOrNoneArg = AnyOf<names::PointOrNone>;
using DirectionArg = AnyOf<names::Direction>;
using DirectionOrNoneArg = AnyOf<names::DirectionOrNone>;
using DirectionsArg = AnyOf<names::Directions>;
using WeightsArg = AnyOf<names::Weights>;
using SolidArg = AnyOf<names::Solid>;
using SolidOrPiecesArg = AnyOf<names::SolidOrPieces>;
using FaceArg = AnyOf<names::Face>;
using EdgeArg = AnyOf<names::Edge>;
using VertexArg = AnyOf<names::Vertex>;
using PartArg = AnyOf<names::Part>;
using AssemblyArg = AnyOf<names::Assembly>;
using ItemArg = AnyOf<names::Item>;
using PlacementArg = AnyOf<names::Placement>;
using MaterialArg = AnyOf<names::Material>;
using ConnectorArg = AnyOf<names::Connector>;
using RefArg = AnyOf<names::Ref>;
using LimitArg = AnyOf<names::Limit>;

const sp::Assembly& assembly_arg(const py::object& value) {
  return typed<sp::Assembly>(value, "assembly must be an Assembly");
}
const sp::Placement& placement_arg(const py::object& value) {
  return typed<sp::Placement>(value, "placement must be a Placement");
}
const sp::Part& part_arg(const py::object& value) {
  return typed<sp::Part>(value, "part must be a Part");
}
sp::AssemblyPtr assembly_ptr_arg(const py::object& value) {
  if (!py::isinstance<sp::Assembly>(value))
    throw TypeError("assembly must be an Assembly");
  return value.cast<sp::AssemblyPtr>();
}

// The assembly of an add_*_constraint operator: its type is checked by the guarded wrapper in
// Python, after the Constraint has been built.
const sp::Assembly& constraint_assembly(const char* operation, const py::object& value) {
  if (!py::isinstance<sp::Assembly>(value)) {
    guard_operation(operation, [&]() -> int { throw TypeError("assembly must be an Assembly"); });
  }
  return value.cast<const sp::Assembly&>();
}

Scalar3 point_arg(const py::object& value, const char* field) {
  return converted<Scalar3>(value, (std::string(field) + " must be a 3-element tuple of numbers").c_str());
}

void bind_structure(py::module_& m) {
  m.def(
      "make_material_rmaterial",
      [](const TextArg& material_id, const NameArg& name, const NumberOrNoneArg& density,
         const TextOrNoneArg& density_unit, const ColorArg& color) {
        return guard_operation("make_material_rmaterial", [&] {
          sp::OptionalString unit;
          if (!density_unit.is_none())
            unit = py::isinstance<py::str>(density_unit) ? density_unit.cast<std::string>() : std::string();
          return sp::make_material_rmaterial(text(material_id, "material_id"), optional_name(name),
                                             optional_scalar(density, "density"), unit, optional_vec3(color, "color"));
        });
      },
      py::arg("material_id"), py::arg("name") = py::none(), py::arg("density") = py::none(),
      py::arg("density_unit") = py::none(), py::arg("color") = py::none(),
      "Create a material definition for later Part assignment.\n\n"
      "Material is deliberately separate from `make_part_rpart(...)`; the only\n"
      "correct workflow is to create a material and then assign it to a Part with\n"
      "`assign_material_rpart(...)`.");

  m.def(
      "make_placement_rplacement",
      [](const PointArg& origin, const DirectionArg& x_axis, const DirectionArg& y_axis) {
        return guard_operation("make_placement_rplacement", [&] {
          return sp::make_placement_rplacement(point_arg(origin, "origin"), point_arg(x_axis, "x_axis"),
                                               point_arg(y_axis, "y_axis"));
        });
      },
      py::arg("origin"), py::arg("x_axis") = py::make_tuple(1.0, 0.0, 0.0),
      py::arg("y_axis") = py::make_tuple(0.0, 1.0, 0.0),
      "Create a canonical right-handed placement in the active workplane.");
  m.def("identity_placement_rplacement", &sp::identity_placement_rplacement,
        "Create the identity placement of the active workplane.");

  m.def(
      "make_part_rpart",
      [](const TextArg& part_id, const SolidOrPiecesArg& body, const NameArg& name) {
        return guard_operation("make_part_rpart", [&] {
          const std::string id = text(part_id, "part_id");
          return sp::make_part_rpart(id, single_solid(body, id), optional_name(name));
        });
      },
      py::arg("part_id"), py::arg("body"), py::arg("name") = py::none(),
      "Wrap one Solid (body) as a semantic Part. A Part holds exactly one solid.");
  m.def(
      "assign_material_rpart",
      [](const PartArg& part, const MaterialArg& material) {
        return guard_operation("assign_material_rpart", [&] {
          return sp::assign_material_rpart(part_arg(part),
                                           typed<sp::Material>(material, "material must be a Material"));
        });
      },
      py::arg("part"), py::arg("material"), "Assign a Material to a Part and return the updated Part.");
  m.def(
      "set_body_appearance_rpart",
      [](const PartArg& part, const TextArg& body_id, const ColorArg& color, const NumberOrNoneArg& opacity,
         const NameArg& name, const BoolArg& reset) {
        return guard_operation("set_body_appearance_rpart", [&] {
          return sp::set_body_appearance_rpart(
              part_arg(part), text(body_id, "body_id"), optional_vec3(color, "color"),
              opacity.is_none() ? sp::OptionalDouble{} : sp::OptionalDouble{number(opacity, "opacity")},
              optional_name(name), truthy(reset));
        });
      },
      py::arg("part"), py::arg("body_id") = sp::kDefaultBodyId, py::kw_only(), py::arg("color") = py::none(),
      py::arg("opacity") = py::none(), py::arg("name") = py::none(), py::arg("reset") = false,
      "Set the display colour, opacity and display name of one body of a Part and return the updated Part.");

  m.def(
      "make_assembly_rassembly",
      [](const TextArg& assembly_id, const NameArg& name) {
        return guard_operation("make_assembly_rassembly", [&] {
          return sp::make_assembly_rassembly(text(assembly_id, "assembly_id"), optional_name(name));
        });
      },
      py::arg("assembly_id"), py::arg("name") = py::none(), "Create an empty assembly product structure.");
  m.def(
      "add_component_rassembly",
      [](const AssemblyArg& assembly, const ItemArg& item, const TextArg& component_id, const PlacementArg& placement,
         const NameArg& name) {
        return guard_operation("add_component_rassembly", [&] {
          const sp::Assembly& target = assembly_arg(assembly);
          const sp::Item chosen = item_of(item);
          return sp::add_component_rassembly(target, chosen, text(component_id, "component_id"),
                                             placement_arg(placement), optional_name(name));
        });
      },
      py::arg("assembly"), py::arg("item"), py::arg("component_id"), py::arg("placement"), py::arg("name") = py::none(),
      "Add a placed Part or subassembly component instance to an Assembly.");
  m.def(
      "place_component_rassembly",
      [](const AssemblyArg& assembly, const TextArg& component_id, const PlacementArg& placement) {
        return guard_operation("place_component_rassembly", [&] {
          const sp::Assembly& target = assembly_arg(assembly);
          return sp::place_component_rassembly(target, text(component_id, "component_id"), placement_arg(placement));
        });
      },
      py::arg("assembly"), py::arg("component_id"), py::arg("placement"),
      "Move an existing assembly component by replacing its placement.");
  m.def(
      "explode_rassembly",
      [](const AssemblyArg& assembly, const NumberArg& factor, const PointOrNoneArg& center,
         const DirectionOrNoneArg& axis, const DirectionsArg& directions, const WeightsArg& weights) {
        return guard_operation("explode_rassembly", [&] {
          const sp::Assembly& target = assembly_arg(assembly);
          std::map<std::string, Vec3> direction_map;
          if (!directions.is_none()) {
            if (!py::isinstance<py::dict>(directions))
              throw TypeError("directions must be a dict of component_id -> direction");
            for (const auto& item : py::reinterpret_borrow<py::dict>(directions))
              direction_map[text(py::reinterpret_borrow<py::object>(item.first), "a directions key")] =
                  vec3(py::reinterpret_borrow<py::object>(item.second), "a direction");
          }
          std::map<std::string, double> weight_map;
          if (!weights.is_none()) {
            if (!py::isinstance<py::dict>(weights))
              throw TypeError("weights must be a dict of component_id -> number");
            for (const auto& item : py::reinterpret_borrow<py::dict>(weights))
              weight_map[text(py::reinterpret_borrow<py::object>(item.first), "a weights key")] =
                  number(py::reinterpret_borrow<py::object>(item.second), "a weight");
          }
          return sp::explode_rassembly(target, scalar(factor, "factor"), optional_vec3(center, "center"),
                                       optional_vec3(axis, "axis"), direction_map, weight_map);
        });
      },
      py::arg("assembly"), py::arg("factor"), py::kw_only(), py::arg("center") = py::none(),
      py::arg("axis") = py::none(), py::arg("directions") = py::none(), py::arg("weights") = py::none(),
      "Return a display copy of the assembly with its components pushed apart for an exploded view.");
}

void bind_connectors(py::module_& m) {
  m.def(
      "make_face_connector_rconnector",
      [](const TextArg& connector_id, const FaceArg& face, const NameArg& name, const BoolArg& flip) {
        return guard_operation("make_face_connector_rconnector", [&] {
          const Face& target = typed<Face>(face, "face must be a Face");
          return sp::make_face_connector_rconnector(text(connector_id, "connector_id"), target, optional_name(name),
                                                    truthy(flip));
        });
      },
      py::arg("connector_id"), py::arg("face"), py::arg("name") = py::none(), py::arg("flip") = false,
      "Create a connector anchored to a Face.\n\nZ axis follows the face normal; origin is the face center.\n"
      "Set flip=True to negate the Z axis (point it opposite to the normal).");
  m.def(
      "make_edge_connector_rconnector",
      [](const TextArg& connector_id, const EdgeArg& edge, const NameArg& name, const BoolArg& flip) {
        return guard_operation("make_edge_connector_rconnector", [&] {
          const Edge& target = typed<Edge>(edge, "edge must be an Edge");
          return sp::make_edge_connector_rconnector(text(connector_id, "connector_id"), target, optional_name(name),
                                                    truthy(flip));
        });
      },
      py::arg("connector_id"), py::arg("edge"), py::arg("name") = py::none(), py::arg("flip") = false,
      "Create a connector anchored to an Edge.\n\nZ axis follows the edge direction (start->end); origin is the edge "
      "midpoint.\n"
      "Set flip=True to negate the Z axis.");
  m.def(
      "make_vertex_connector_rconnector",
      [](const TextArg& connector_id, const VertexArg& vertex, const NameArg& name, const BoolArg& flip) {
        return guard_operation("make_vertex_connector_rconnector", [&] {
          const Vertex& target = typed<Vertex>(vertex, "vertex must be a Vertex");
          return sp::make_vertex_connector_rconnector(text(connector_id, "connector_id"), target, optional_name(name),
                                                      truthy(flip));
        });
      },
      py::arg("connector_id"), py::arg("vertex"), py::arg("name") = py::none(), py::arg("flip") = false,
      "Create a connector anchored to a Vertex.\n\nOrigin is the vertex point; axes are identity.\n"
      "flip has no effect on vertex connectors (no direction).");
  m.def(
      "make_placement_connector_rconnector",
      [](const TextArg& connector_id, const PlacementArg& placement, const NameArg& name) {
        return guard_operation("make_placement_connector_rconnector", [&] {
          const sp::Placement& frame = placement_arg(placement);
          return sp::make_placement_connector_rconnector(text(connector_id, "connector_id"), frame,
                                                         optional_name(name));
        });
      },
      py::arg("connector_id"), py::arg("placement"), py::arg("name") = py::none(),
      "Create a connector anchored to an explicit local placement frame.");
  m.def(
      "add_connector_rpart",
      [](const PartArg& part, const ConnectorArg& connector) {
        return guard_operation("add_connector_rpart", [&] {
          const sp::Part& target = part_arg(part);
          return sp::add_connector_rpart(target, typed<sp::Connector>(connector, "connector must be a Connector"));
        });
      },
      py::arg("part"), py::arg("connector"), "Attach a connector datum frame to a Part definition.");
  m.def(
      "set_public_connector_rassembly",
      [](const AssemblyArg& assembly, const TextArg& public_id, const TextArg& component_id,
         const TextArg& connector_id, const NameArg& name) {
        return guard_operation("set_public_connector_rassembly", [&] {
          const sp::Assembly& target = assembly_arg(assembly);
          return sp::set_public_connector_rassembly(target, text(public_id, "public_connector_id"),
                                                    text(component_id, "component_id"),
                                                    text(connector_id, "connector_id"), optional_name(name));
        });
      },
      py::arg("assembly"), py::arg("public_connector_id"), py::arg("source_component_id"),
      py::arg("source_connector_id"), py::arg("name") = py::none(),
      "Expose an existing connector on a direct child component.");
  m.def(
      "make_connector_ref_rconnectorref",
      [](const TextArg& component_id, const TextArg& connector_id) {
        return guard_operation("make_connector_ref_rconnectorref", [&] {
          return sp::make_connector_ref_rconnectorref(text(component_id, "component_id"),
                                                      text(connector_id, "connector_id"));
        });
      },
      py::arg("component_id"), py::arg("connector_id"), "Reference a connector through a component instance.");
  m.def(
      "make_scalar_limit_rscalarlimit",
      [](const NumberArg& lower_value, const NumberArg& upper_value) {
        return guard_operation("make_scalar_limit_rscalarlimit", [&] {
          return sp::make_scalar_limit_rscalarlimit(scalar(lower_value, "lower_value"),
                                                    scalar(upper_value, "upper_value"));
        });
      },
      py::arg("lower_value"), py::arg("upper_value"),
      "Create a closed scalar limit for driven constraint coordinates.");
}

// The constraint operators convert their arguments outside guard_operation: Python builds the
// Constraint before the guarded part, so those errors are not wrapped.
void bind_constraints(py::module_& m) {
  m.def(
      "ground_component_rassembly",
      [](const AssemblyArg& assembly, const TextArg& component_id) {
        return guard_operation("ground_component_rassembly", [&] {
          const sp::Assembly& target = assembly_arg(assembly);
          return sp::ground_component_rassembly(target, text(component_id, "component_id"));
        });
      },
      py::arg("assembly"), py::arg("component_id"), "Ground a component at its current authored placement.");
  m.def(
      "unground_component_rassembly",
      [](const AssemblyArg& assembly, const TextArg& component_id) {
        return guard_operation("unground_component_rassembly", [&] {
          const sp::Assembly& target = assembly_arg(assembly);
          return sp::unground_component_rassembly(target, text(component_id, "component_id"));
        });
      },
      py::arg("assembly"), py::arg("component_id"), "Remove a component grounding marker.");

  const auto ref = [](const py::object& value, const char* field) -> const sp::ConnectorRef& {
    return typed<sp::ConnectorRef>(value, (std::string(field) + " must be a ConnectorRef").c_str());
  };
  const auto limit = [](const py::object& value, const char* message) -> sp::OptionalLimit {
    if (value.is_none())
      return std::nullopt;
    return typed<sp::ScalarLimit>(value, message);
  };

  m.def(
      "add_fixed_constraint_rassembly",
      [ref](const AssemblyArg& assembly, const TextArg& constraint_id, const RefArg& a, const RefArg& b,
            const NameArg& name) {
        return sp::add_fixed_constraint_rassembly(constraint_assembly("add_fixed_constraint_rassembly", assembly),
                                                  text(constraint_id, "constraint_id"), ref(a, "connector_a"),
                                                  ref(b, "connector_b"), optional_name(name));
      },
      py::arg("assembly"), py::arg("constraint_id"), py::arg("connector_a"), py::arg("connector_b"),
      py::arg("name") = py::none(), "Constrain two component connectors to the same frame.");
  m.def(
      "add_revolute_constraint_rassembly",
      [ref, limit](const AssemblyArg& assembly, const TextArg& constraint_id, const RefArg& a, const RefArg& b,
                   const AngleOrNoneArg& drive_angle_degrees, const LimitArg& angle_limit, const NameArg& name) {
        return sp::add_revolute_constraint_rassembly(
            constraint_assembly("add_revolute_constraint_rassembly", assembly), text(constraint_id, "constraint_id"),
            ref(a, "connector_a"), ref(b, "connector_b"), optional_scalar(drive_angle_degrees, "drive_angle_degrees"),
            limit(angle_limit, "angle_limit must be a ScalarLimit"), optional_name(name));
      },
      py::arg("assembly"), py::arg("constraint_id"), py::arg("connector_a"), py::arg("connector_b"),
      py::arg("drive_angle_degrees") = py::none(), py::arg("angle_limit") = py::none(), py::arg("name") = py::none(),
      "Constrain two connectors as a revolute axis pair.");
  m.def(
      "add_prismatic_constraint_rassembly",
      [ref, limit](const AssemblyArg& assembly, const TextArg& constraint_id, const RefArg& a, const RefArg& b,
                   const LengthOrNoneArg& drive_distance, const LimitArg& distance_limit, const NameArg& name) {
        return sp::add_prismatic_constraint_rassembly(
            constraint_assembly("add_prismatic_constraint_rassembly", assembly), text(constraint_id, "constraint_id"),
            ref(a, "connector_a"), ref(b, "connector_b"), optional_scalar(drive_distance, "drive_distance"),
            limit(distance_limit, "distance_limit must be a ScalarLimit"), optional_name(name));
      },
      py::arg("assembly"), py::arg("constraint_id"), py::arg("connector_a"), py::arg("connector_b"),
      py::arg("drive_distance") = py::none(), py::arg("distance_limit") = py::none(), py::arg("name") = py::none(),
      "Constrain two connectors as a prismatic slider pair.");
  m.def(
      "add_gear_constraint_rassembly",
      [ref](const AssemblyArg& assembly, const TextArg& constraint_id, const RefArg& a, const RefArg& b,
            const LengthArg& pitch_radius_a, const LengthArg& pitch_radius_b, const LengthOrNoneArg& phase_offset,
            const NameArg& name) {
        return sp::add_gear_constraint_rassembly(constraint_assembly("add_gear_constraint_rassembly", assembly),
                                                 text(constraint_id, "constraint_id"), ref(a, "connector_a"),
                                                 ref(b, "connector_b"), scalar(pitch_radius_a, "pitch_radius_a"),
                                                 scalar(pitch_radius_b, "pitch_radius_b"),
                                                 optional_scalar(phase_offset, "phase_offset"), optional_name(name));
      },
      py::arg("assembly"), py::arg("constraint_id"), py::arg("connector_a"), py::arg("connector_b"),
      py::arg("pitch_radius_a"), py::arg("pitch_radius_b"), py::arg("phase_offset") = py::none(),
      py::arg("name") = py::none(), "Couple two revolute axes as meshing gears with inverse rotation.");
  m.def(
      "add_belt_constraint_rassembly",
      [ref](const AssemblyArg& assembly, const TextArg& constraint_id, const RefArg& a, const RefArg& b,
            const LengthArg& pulley_radius_a, const LengthArg& pulley_radius_b, const LengthOrNoneArg& phase_offset,
            const NameArg& name) {
        return sp::add_belt_constraint_rassembly(constraint_assembly("add_belt_constraint_rassembly", assembly),
                                                 text(constraint_id, "constraint_id"), ref(a, "connector_a"),
                                                 ref(b, "connector_b"), scalar(pulley_radius_a, "pulley_radius_a"),
                                                 scalar(pulley_radius_b, "pulley_radius_b"),
                                                 optional_scalar(phase_offset, "phase_offset"), optional_name(name));
      },
      py::arg("assembly"), py::arg("constraint_id"), py::arg("connector_a"), py::arg("connector_b"),
      py::arg("pulley_radius_a"), py::arg("pulley_radius_b"), py::arg("phase_offset") = py::none(),
      py::arg("name") = py::none(), "Couple two revolute axes as belt-linked pulleys with same-direction rotation.");
  m.def(
      "add_rack_pinion_constraint_rassembly",
      [ref](const AssemblyArg& assembly, const TextArg& constraint_id, const RefArg& rack, const RefArg& pinion,
            const LengthArg& pitch_radius, const LengthOrNoneArg& phase_offset, const NameArg& name) {
        return sp::add_rack_pinion_constraint_rassembly(
            constraint_assembly("add_rack_pinion_constraint_rassembly", assembly), text(constraint_id, "constraint_id"),
            ref(rack, "connector_a"), ref(pinion, "connector_b"), scalar(pitch_radius, "pitch_radius"),
            optional_scalar(phase_offset, "phase_offset"), optional_name(name));
      },
      py::arg("assembly"), py::arg("constraint_id"), py::arg("rack_connector"), py::arg("pinion_connector"),
      py::arg("pitch_radius"), py::arg("phase_offset") = py::none(), py::arg("name") = py::none(),
      "Couple a prismatic rack axis to a revolute pinion axis.");
}

void bind_solving(py::module_& m) {
  m.def(
      "solve_assembly_constraints_rassembly",
      [](const AssemblyArg& assembly, const BoolArg& strict) {
        return guard_operation("solve_assembly_constraints_rassembly", [&] {
          return sp::solve_assembly_constraints_rassembly(assembly_ptr_arg(assembly), truthy(strict));
        });
      },
      py::arg("assembly"), py::arg("strict") = true,
      "Solve fixed, revolute, and prismatic assembly constraints.\n\n"
      "Solving is limit-aware: when a constraint carries a ``ScalarLimit``\n"
      "(``angle_limit`` or ``distance_limit``), the drive scalar is clamped\n"
      "into the closed range before placement propagation.  When no drive\n"
      "scalar is present but a limit exists, the current relative-frame\n"
      "scalar is projected into the bounds.  Unresolvable closed kinematic\n"
      "loops fall back to a golden-section search over the limit bounds.\n\n"
      "A ``ConstraintReport`` is recorded on the returned assembly under the\n"
      "``constraint_report`` runtime key for later inspection via\n"
      "``inspect_assembly_constraints_rassembly``.");
  m.def(
      "measure_constraint_residual_rconstraintresidual",
      [](const AssemblyArg& assembly, const TextArg& constraint_id) {
        return sp::measure_constraint_residual_rconstraintresidual(assembly_arg(assembly),
                                                                   text(constraint_id, "constraint_id"));
      },
      py::arg("assembly"), py::arg("constraint_id"),
      "Measure residual for one assembly constraint without mutating the assembly.");
  m.def(
      "inspect_assembly_constraints_rconstraintreport",
      [](const AssemblyArg& assembly) {
        return sp::inspect_assembly_constraints_rconstraintreport(assembly_arg(assembly));
      },
      py::arg("assembly"), "Inspect all assembly constraint residuals without mutating the assembly.");
  m.def(
      "make_compound_from_assembly_rcompound",
      [](const AssemblyArg& assembly) {
        return guard_operation("make_compound_from_assembly_rcompound",
                               [&] { return sp::make_compound_from_assembly_rcompound(assembly_arg(assembly)); });
      },
      py::arg("assembly"), "Project an Assembly into an explicit flattened Compound geometry value.");
}

}  // namespace

void bind_product(py::module_& m) {
  bind_product_values(m);
  bind_structure(m);
  bind_connectors(m);
  bind_constraints(m);
  bind_solving(m);
  scad::product::register_product_executors(scad::reactive::ExecutorRegistry::global());
}
