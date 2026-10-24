// The product value classes, under the names and attributes simplecadapi exports:
// Placement, Material, Part, Assembly, Component, PublicConnectorRef, Connector, ConnectorAnchor,
// ConnectorRef, GeometryRef, Constraint, ConstraintReport, ConstraintResidual, ScalarLimit.
#include "bind_product_args.hpp"

namespace {

using namespace scad;
using namespace scad::product_binding;
using namespace pybind11::literals;

// Python's repr(float).
std::string float_repr(double value) { return py::repr(py::float_(value)).cast<std::string>(); }
std::string str_repr(const std::string& value) { return py::repr(py::str(value)).cast<std::string>(); }
std::string opt_str_repr(const sp::OptionalString& value) { return value ? str_repr(*value) : "None"; }
std::string opt_float_repr(const sp::OptionalDouble& value) { return value ? float_repr(*value) : "None"; }

std::string tuple_repr(const Vec3& v) {
  return "(" + float_repr(v.x) + ", " + float_repr(v.y) + ", " + float_repr(v.z) + ")";
}

py::object optional_object(const sp::OptionalString& value) { return value ? py::object(py::str(*value)) : py::none(); }
py::object optional_float(const sp::OptionalDouble& value) { return value ? py::object(py::float_(*value)) : py::none(); }

// The SemanticValueMixin methods.
template <class T, class Cls>
void bind_semantic_value(Cls& cls) {
  cls.def("set_metadata", [](const T& self, const std::string& key, const Value& value) { self.set_metadata(key, value); })
      .def("get_metadata", [](const T& self, const std::string& key, const Value& fallback) { return self.get_metadata(key, fallback); },
           py::arg("key"), py::arg("default") = Value())
      .def("_set_runtime", [](const T& self, const std::string& key, const Value& value) { self.set_runtime(key, value); })
      .def("_get_runtime", [](const T& self, const std::string& key, const Value& fallback) { return self.get_runtime(key, fallback); },
           py::arg("key"), py::arg("default") = Value());
}

template <class T>
py::int_ hash_of(const T& self, const std::string& text) {
  (void)self;
  return py::int_(py::hash(py::str(text)));
}

void bind_placement(py::module_& m) {
  using sp::Placement;
  py::class_<Placement, py::smart_holder> cls(m, "Placement", "Right-handed placement mapping child-local coordinates to parent coordinates.");
  cls.def(py::init([](const py::object& origin, const py::object& x_axis, const py::object& y_axis, const py::object&) {
            return Placement(vec3(origin, "origin"), vec3(x_axis, "x_axis"), vec3(y_axis, "y_axis"));
          }),
          py::arg("origin"), py::arg("x_axis") = py::make_tuple(1.0, 0.0, 0.0), py::arg("y_axis") = py::make_tuple(0.0, 1.0, 0.0),
          py::arg("z_axis") = py::make_tuple(0.0, 0.0, 1.0))
      .def_property_readonly("origin", &Placement::origin)
      .def_property_readonly("x_axis", &Placement::x_axis)
      .def_property_readonly("y_axis", &Placement::y_axis)
      .def_property_readonly("z_axis", &Placement::z_axis)
      .def("transform_point", [](const Placement& self, const py::object& point) { return self.transform_point(vec3(point, "point")); },
           py::arg("point"))
      .def("transform_vector", [](const Placement& self, const py::object& vector) { return self.transform_vector(vec3(vector, "vector")); },
           py::arg("vector"))
      .def("compose", [](const Placement& self, const py::object& child) {
             return self.compose(typed<Placement>(child, "child must be a Placement"));
           }, py::arg("child"))
      .def_static("from_exact_frame", [](const py::object& o, const py::object& x, const py::object& y, const py::object& z) {
             return Placement::from_exact_frame(vec3(o, "origin"), vec3(x, "x_axis"), vec3(y, "y_axis"), vec3(z, "z_axis"));
           }, py::arg("origin"), py::arg("x_axis"), py::arg("y_axis"), py::arg("z_axis"))
      .def("to_dict", [](const Placement& self) { return self.to_dict(); })
      .def("__eq__", [](const Placement& a, const py::object& b) { return py::isinstance<Placement>(b) && a == b.cast<const Placement&>(); },
           py::is_operator())
      .def("__hash__", [](const Placement& self) {
        return hash_of(self, tuple_repr(self.origin()) + tuple_repr(self.x_axis()) + tuple_repr(self.y_axis()));
      })
      .def("__repr__", [](const Placement& self) {
        return "Placement(origin=" + tuple_repr(self.origin()) + ", x_axis=" + tuple_repr(self.x_axis()) +
               ", y_axis=" + tuple_repr(self.y_axis()) + ", z_axis=" + tuple_repr(self.z_axis()) + ")";
      });
  bind_semantic_value<Placement>(cls);
}

void bind_material(py::module_& m) {
  using sp::Material;
  py::class_<Material, py::smart_holder> cls(m, "Material", "Material definition assigned to a Part through `assign_material_rpart`.");
  cls.def(py::init([](const py::object& material_id, const py::object& name, const py::object& density,
                      const py::object& density_unit, const py::object& color) {
            sp::OptionalString unit;
            if (!density_unit.is_none()) unit = py::isinstance<py::str>(density_unit) ? density_unit.cast<std::string>() : std::string();
            std::optional<double> density_value;
            if (!density.is_none()) density_value = number(density, "density");
            return Material(text(material_id, "material_id"), optional_name(name), density_value, unit,
                            optional_vec3(color, "color"));
          }),
          py::arg("material_id"), py::arg("name") = py::none(), py::arg("density") = py::none(),
          py::arg("density_unit") = py::none(), py::arg("color") = py::none())
      .def_property_readonly("material_id", &Material::material_id)
      .def_property_readonly("name", [](const Material& self) { return optional_object(self.name()); })
      .def_property_readonly("density", [](const Material& self) { return optional_float(self.density()); })
      .def_property_readonly("density_unit", [](const Material& self) { return optional_object(self.density_unit()); })
      .def_property_readonly("color", [](const Material& self) -> py::object {
        return self.color() ? py::cast(*self.color()) : py::none();
      })
      .def("to_dict", [](const Material& self) { return self.to_dict(); })
      .def("__eq__", [](const Material& a, const py::object& b) { return py::isinstance<Material>(b) && a == b.cast<const Material&>(); },
           py::is_operator())
      .def("__hash__", [](const Material& self) { return hash_of(self, self.to_dict().dump()); })
      .def("__repr__", [](const Material& self) {
        return "Material(material_id=" + str_repr(self.material_id()) + ", name=" + opt_str_repr(self.name()) +
               ", density=" + opt_float_repr(self.density()) + ", density_unit=" + opt_str_repr(self.density_unit()) +
               ", color=" + (self.color() ? tuple_repr(*self.color()) : "None") + ")";
      });
  bind_semantic_value<Material>(cls);
}

void bind_limit_and_refs(py::module_& m) {
  using sp::ConnectorRef;
  using sp::ScalarLimit;
  py::class_<ScalarLimit, py::smart_holder> limit(m, "ScalarLimit", "Closed scalar range for a constraint drive coordinate.");
  limit.def(py::init([](const py::object& lower, const py::object& upper) {
              return ScalarLimit(number(lower, "lower_value"), number(upper, "upper_value"));
            }), py::arg("lower_value"), py::arg("upper_value"))
      .def_property_readonly("lower_value", &ScalarLimit::lower_value)
      .def_property_readonly("upper_value", &ScalarLimit::upper_value)
      .def("contains", [](const ScalarLimit& self, const py::object& value) { return self.contains(number(value, "value")); },
           py::arg("value"))
      .def("to_dict", [](const ScalarLimit& self) { return self.to_dict(); })
      .def("__eq__", [](const ScalarLimit& a, const py::object& b) { return py::isinstance<ScalarLimit>(b) && a == b.cast<const ScalarLimit&>(); },
           py::is_operator())
      .def("__hash__", [](const ScalarLimit& self) { return hash_of(self, self.to_dict().dump()); })
      .def("__repr__", [](const ScalarLimit& self) {
        return "ScalarLimit(lower_value=" + float_repr(self.lower_value()) + ", upper_value=" + float_repr(self.upper_value()) + ")";
      });
  bind_semantic_value<ScalarLimit>(limit);

  py::class_<ConnectorRef, py::smart_holder> ref(m, "ConnectorRef", "Reference to a connector through a component instance.");
  ref.def(py::init([](const py::object& component_id, const py::object& connector_id) {
            return ConnectorRef(text(component_id, "component_id"), text(connector_id, "connector_id"));
          }), py::arg("component_id"), py::arg("connector_id"))
      .def_property_readonly("component_id", &ConnectorRef::component_id)
      .def_property_readonly("connector_id", &ConnectorRef::connector_id)
      .def("to_dict", [](const ConnectorRef& self) { return self.to_dict(); })
      .def("__eq__", [](const ConnectorRef& a, const py::object& b) { return py::isinstance<ConnectorRef>(b) && a == b.cast<const ConnectorRef&>(); },
           py::is_operator())
      .def("__hash__", [](const ConnectorRef& self) { return hash_of(self, self.component_id() + "/" + self.connector_id()); })
      .def("__repr__", [](const ConnectorRef& self) {
        return "ConnectorRef(component_id=" + str_repr(self.component_id()) + ", connector_id=" + str_repr(self.connector_id()) + ")";
      });
  bind_semantic_value<ConnectorRef>(ref);
}

void bind_connectors(py::module_& m) {
  using namespace sp;
  py::class_<GeometryRef, py::smart_holder> geometry(m, "GeometryRef", "Serializable reference to a sub-shape selected via QL.");
  geometry.def(py::init([](const py::object& kind, const py::object& source_node_id, const py::object& geo_selector, const py::object& flip) {
                 if (!py::isinstance<py::dict>(geo_selector)) throw scad::TypeError("geo_selector must be a dict");
                 sp::OptionalString source;
                 if (!source_node_id.is_none()) source = py::str(source_node_id).cast<std::string>();
                 return GeometryRef(py::str(kind).cast<std::string>(), source, geo_selector.cast<Value>(), truthy(flip));
               }),
               py::arg("kind"), py::arg("source_node_id"), py::arg("geo_selector"), py::arg("flip") = false)
      .def_property_readonly("kind", &GeometryRef::kind)
      .def_property_readonly("source_node_id", [](const GeometryRef& self) { return optional_object(self.source_node_id()); })
      .def_property_readonly("geo_selector", [](const GeometryRef& self) { return self.geo_selector(); })
      .def_property_readonly("flip", &GeometryRef::flip)
      .def("to_dict", [](const GeometryRef& self) { return self.to_dict(); })
      .def("__eq__", [](const GeometryRef& a, const py::object& b) { return py::isinstance<GeometryRef>(b) && a == b.cast<const GeometryRef&>(); },
           py::is_operator());
  bind_semantic_value<GeometryRef>(geometry);

  py::class_<ConnectorAnchor, py::smart_holder> anchor(m, "ConnectorAnchor", "Serializable source for a connector datum frame.");
  anchor.def(py::init([](const py::object& anchor_kind, const py::object& geometry_ref, const py::object& placement) {
               std::optional<GeometryRef> geometry;
               std::optional<Placement> frame;
               if (!geometry_ref.is_none()) geometry = typed<GeometryRef>(geometry_ref, "geometry anchors require geometry_ref");
               if (!placement.is_none()) frame = typed<Placement>(placement, "placement anchors require placement");
               return ConnectorAnchor(py::str(anchor_kind).cast<std::string>(), geometry, frame);
             }),
             py::arg("anchor_kind"), py::arg("geometry_ref") = py::none(), py::arg("placement") = py::none())
      .def_property_readonly("anchor_kind", &ConnectorAnchor::anchor_kind)
      .def_property_readonly("geometry_ref", [](const ConnectorAnchor& self) -> py::object {
        return self.geometry_ref() ? py::cast(*self.geometry_ref()) : py::none();
      })
      .def_property_readonly("placement", [](const ConnectorAnchor& self) -> py::object {
        return self.placement() ? py::cast(*self.placement()) : py::none();
      })
      .def("to_dict", [](const ConnectorAnchor& self) { return self.to_dict(); })
      .def("__eq__", [](const ConnectorAnchor& a, const py::object& b) { return py::isinstance<ConnectorAnchor>(b) && a == b.cast<const ConnectorAnchor&>(); },
           py::is_operator());
  bind_semantic_value<ConnectorAnchor>(anchor);

  py::class_<Connector, py::smart_holder> connector(m, "Connector", "Semantic datum frame anchored by geometry or an explicit placement.");
  connector.def(py::init([](const py::object& connector_id, const py::object& geometry_ref, const py::object& name, const py::object& anchor_value) {
                  std::optional<GeometryRef> geometry;
                  std::optional<ConnectorAnchor> anchor_of;
                  if (!geometry_ref.is_none()) geometry = typed<GeometryRef>(geometry_ref, "geometry_ref must be a GeometryRef when anchor is omitted");
                  if (!anchor_value.is_none()) anchor_of = typed<ConnectorAnchor>(anchor_value, "anchor must be a ConnectorAnchor");
                  return Connector(text(connector_id, "connector_id"), geometry, optional_name(name), anchor_of);
                }),
                py::arg("connector_id"), py::arg("geometry_ref") = py::none(), py::arg("name") = py::none(), py::arg("anchor") = py::none())
      .def_property_readonly("connector_id", &Connector::connector_id)
      .def_property_readonly("geometry_ref", [](const Connector& self) -> py::object {
        return self.geometry_ref() ? py::cast(*self.geometry_ref()) : py::none();
      })
      .def_property_readonly("name", [](const Connector& self) { return optional_object(self.name()); })
      .def_property_readonly("anchor", [](const Connector& self) { return self.anchor(); })
      .def_property_readonly("anchor_kind", &Connector::anchor_kind)
      .def_property_readonly("placement", &Connector::placement)
      .def("to_dict", [](const Connector& self) { return self.to_dict(); })
      .def("__eq__", [](const Connector& a, const py::object& b) { return py::isinstance<Connector>(b) && a == b.cast<const Connector&>(); },
           py::is_operator());
  bind_semantic_value<Connector>(connector);
}

sp::OptionalDouble opt_number(const py::object& value, const char* field) {
  if (value.is_none()) return std::nullopt;
  return number(value, field);
}

sp::OptionalLimit opt_limit(const py::object& value, const char* message) {
  if (value.is_none()) return std::nullopt;
  return typed<sp::ScalarLimit>(value, message);
}

void bind_constraints(py::module_& m) {
  using namespace sp;
  py::class_<Constraint, py::smart_holder> cls(m, "Constraint", "Connector-to-connector assembly constraint.");
  cls.def(py::init([](const py::object& constraint_id, const py::object& constraint_kind, const py::object& a, const py::object& b,
                      const py::object& drive_distance, const py::object& distance_limit, const py::object& drive_angle_degrees,
                      const py::object& angle_limit, const py::object& pitch_radius_a, const py::object& pitch_radius_b,
                      const py::object& pulley_radius_a, const py::object& pulley_radius_b, const py::object& pitch_radius,
                      const py::object& phase_offset, const py::object& name) {
            ConstraintSettings s;
            s.drive_distance = opt_number(drive_distance, "drive_distance");
            s.distance_limit = opt_limit(distance_limit, "distance_limit must be a ScalarLimit");
            s.drive_angle_degrees = opt_number(drive_angle_degrees, "drive_angle_degrees");
            s.angle_limit = opt_limit(angle_limit, "angle_limit must be a ScalarLimit");
            s.pitch_radius_a = opt_number(pitch_radius_a, "pitch_radius_a");
            s.pitch_radius_b = opt_number(pitch_radius_b, "pitch_radius_b");
            s.pulley_radius_a = opt_number(pulley_radius_a, "pulley_radius_a");
            s.pulley_radius_b = opt_number(pulley_radius_b, "pulley_radius_b");
            s.pitch_radius = opt_number(pitch_radius, "pitch_radius");
            s.phase_offset = opt_number(phase_offset, "phase_offset");
            s.name = optional_name(name);
            return Constraint(text(constraint_id, "constraint_id"), py::str(constraint_kind).cast<std::string>(),
                              typed<ConnectorRef>(a, "connector_a must be a ConnectorRef"),
                              typed<ConnectorRef>(b, "connector_b must be a ConnectorRef"), std::move(s));
          }),
          py::arg("constraint_id"), py::arg("constraint_kind"), py::arg("connector_a"), py::arg("connector_b"),
          py::arg("drive_distance") = py::none(), py::arg("distance_limit") = py::none(),
          py::arg("drive_angle_degrees") = py::none(), py::arg("angle_limit") = py::none(),
          py::arg("pitch_radius_a") = py::none(), py::arg("pitch_radius_b") = py::none(),
          py::arg("pulley_radius_a") = py::none(), py::arg("pulley_radius_b") = py::none(),
          py::arg("pitch_radius") = py::none(), py::arg("phase_offset") = py::none(), py::arg("name") = py::none())
      .def_property_readonly("constraint_id", &Constraint::constraint_id)
      .def_property_readonly("constraint_kind", &Constraint::constraint_kind)
      .def_property_readonly("connector_a", &Constraint::connector_a)
      .def_property_readonly("connector_b", &Constraint::connector_b)
      .def_property_readonly("drive_distance", [](const Constraint& c) { return optional_float(c.drive_distance()); })
      .def_property_readonly("distance_limit", [](const Constraint& c) -> py::object { return c.distance_limit() ? py::cast(*c.distance_limit()) : py::none(); })
      .def_property_readonly("drive_angle_degrees", [](const Constraint& c) { return optional_float(c.drive_angle_degrees()); })
      .def_property_readonly("angle_limit", [](const Constraint& c) -> py::object { return c.angle_limit() ? py::cast(*c.angle_limit()) : py::none(); })
      .def_property_readonly("pitch_radius_a", [](const Constraint& c) { return optional_float(c.pitch_radius_a()); })
      .def_property_readonly("pitch_radius_b", [](const Constraint& c) { return optional_float(c.pitch_radius_b()); })
      .def_property_readonly("pulley_radius_a", [](const Constraint& c) { return optional_float(c.pulley_radius_a()); })
      .def_property_readonly("pulley_radius_b", [](const Constraint& c) { return optional_float(c.pulley_radius_b()); })
      .def_property_readonly("pitch_radius", [](const Constraint& c) { return optional_float(c.pitch_radius()); })
      .def_property_readonly("phase_offset", [](const Constraint& c) { return optional_float(c.phase_offset()); })
      .def_property_readonly("name", [](const Constraint& c) { return optional_object(c.name()); })
      .def("to_dict", [](const Constraint& self) { return self.to_dict(); })
      .def("__eq__", [](const Constraint& a, const py::object& b) { return py::isinstance<Constraint>(b) && a == b.cast<const Constraint&>(); },
           py::is_operator());
  bind_semantic_value<Constraint>(cls);

  py::class_<ConstraintResidual, py::smart_holder>(m, "ConstraintResidual", "Residual for a single assembly constraint.")
      .def(py::init([](std::string constraint_id, double translation_error, double angular_error_degrees, bool within_tolerance) {
             return ConstraintResidual{std::move(constraint_id), translation_error, angular_error_degrees, within_tolerance};
           }),
           py::arg("constraint_id"), py::arg("translation_error"), py::arg("angular_error_degrees"), py::arg("within_tolerance"))
      .def_readonly("constraint_id", &ConstraintResidual::constraint_id)
      .def_readonly("translation_error", &ConstraintResidual::translation_error)
      .def_readonly("angular_error_degrees", &ConstraintResidual::angular_error_degrees)
      .def_readonly("within_tolerance", &ConstraintResidual::within_tolerance)
      .def("to_dict", [](const ConstraintResidual& self) { return self.to_dict(); })
      .def("__eq__", [](const ConstraintResidual& a, const py::object& b) { return py::isinstance<ConstraintResidual>(b) && a == b.cast<const ConstraintResidual&>(); },
           py::is_operator())
      .def("__repr__", [](const ConstraintResidual& r) {
        return "ConstraintResidual(constraint_id=" + str_repr(r.constraint_id) + ", translation_error=" + float_repr(r.translation_error) +
               ", angular_error_degrees=" + float_repr(r.angular_error_degrees) + ", within_tolerance=" + (r.within_tolerance ? "True" : "False") + ")";
      });

  py::class_<ConstraintReport, py::smart_holder>(m, "ConstraintReport", "Assembly constraint inspection report.")
      .def(py::init([](bool solved, std::vector<std::string> grounded, std::vector<std::string> solved_ids,
                       std::vector<std::string> unsolved_ids, std::vector<ConstraintResidual> residuals) {
             return ConstraintReport{solved, std::move(grounded), std::move(solved_ids), std::move(unsolved_ids), std::move(residuals)};
           }),
           py::arg("solved"), py::arg("grounded_component_ids"), py::arg("solved_component_ids"),
           py::arg("unsolved_component_ids"), py::arg("residuals"))
      .def_readonly("solved", &ConstraintReport::solved)
      .def_property_readonly("grounded_component_ids", [](const ConstraintReport& r) { return to_tuple(r.grounded_component_ids); })
      .def_property_readonly("solved_component_ids", [](const ConstraintReport& r) { return to_tuple(r.solved_component_ids); })
      .def_property_readonly("unsolved_component_ids", [](const ConstraintReport& r) { return to_tuple(r.unsolved_component_ids); })
      .def_property_readonly("residuals", [](const ConstraintReport& r) { return to_tuple(r.residuals); })
      .def("to_dict", [](const ConstraintReport& self) { return self.to_dict(); })
      .def("__eq__", [](const ConstraintReport& a, const py::object& b) { return py::isinstance<ConstraintReport>(b) && a == b.cast<const ConstraintReport&>(); },
           py::is_operator());
}

void bind_part(py::module_& m) {
  using namespace sp;
  py::class_<Part, py::smart_holder> cls(m, "Part", "Single-body product item wrapping exactly one Solid.");
  cls.def(py::init([](const py::object& part_id, const py::object& body, const py::object& name, const py::object& material,
                      const py::object& connectors) {
            std::optional<Material> material_value;
            if (!material.is_none()) material_value = typed<Material>(material, "material must be a Material");
            std::vector<Connector> connector_values;
            if (!connectors.is_none()) {
              for (const py::handle item : connectors) {
                connector_values.push_back(typed<Connector>(py::reinterpret_borrow<py::object>(item), "connectors must contain Connector values"));
              }
            }
            return std::make_shared<Part>(text(part_id, "part_id"), typed<Solid>(body, "body must be a Solid"), optional_name(name),
                                          material_value, std::move(connector_values));
          }),
          py::arg("part_id"), py::arg("body"), py::arg("name") = py::none(), py::arg("material") = py::none(),
          py::arg("connectors") = py::tuple())
      .def_property_readonly("part_id", &Part::part_id)
      .def_property_readonly("body", &Part::body)
      .def_property_readonly("name", [](const Part& self) { return optional_object(self.name()); })
      .def_property_readonly("material", [](const Part& self) -> py::object { return self.material() ? py::cast(*self.material()) : py::none(); })
      .def_property_readonly("connectors", [](const Part& self) { return to_tuple(self.connectors()); })
      .def("with_material", [](const Part& self, const py::object& material) {
             return std::make_shared<const Part>(self.with_material(typed<Material>(material, "material must be a Material")));
           }, py::arg("material"))
      .def("connector_ids", [](const Part& self) { return to_tuple(self.connector_ids()); })
      .def("get_connector", [](const Part& self, const py::object& id) { return self.get_connector(text(id, "connector_id")); },
           py::arg("connector_id"))
      .def("with_connector", [](const Part& self, const py::object& connector) {
             return std::make_shared<const Part>(self.with_connector(typed<Connector>(connector, "connector must be a Connector")));
           }, py::arg("connector"))
      .def("to_dict", [](const Part& self) { return self.to_dict(); })
      .def("__repr__", [](const Part& self) { return "Part(part_id=" + str_repr(self.part_id()) + ", name=" + opt_str_repr(self.name()) + ")"; });
  bind_semantic_value<Part>(cls);
}

void bind_assembly(py::module_& m) {
  using namespace sp;
  py::class_<PublicConnectorRef, py::smart_holder>(m, "PublicConnectorRef", "Public alias for an existing connector on a direct child component.")
      .def(py::init([](const py::object& public_id, const py::object& component_id, const py::object& connector_id, const py::object& name) {
             return PublicConnectorRef(text(public_id, "public_connector_id"), text(component_id, "component_id"),
                                       text(connector_id, "connector_id"), optional_name(name));
           }),
           py::arg("public_connector_id"), py::arg("component_id"), py::arg("connector_id"), py::arg("name") = py::none())
      .def_readonly("public_connector_id", &PublicConnectorRef::public_connector_id)
      .def_readonly("component_id", &PublicConnectorRef::component_id)
      .def_readonly("connector_id", &PublicConnectorRef::connector_id)
      .def_property_readonly("name", [](const PublicConnectorRef& self) { return optional_object(self.name); })
      .def("to_dict", [](const PublicConnectorRef& self) { return self.to_dict(); })
      .def("__eq__", [](const PublicConnectorRef& a, const py::object& b) { return py::isinstance<PublicConnectorRef>(b) && a == b.cast<const PublicConnectorRef&>(); },
           py::is_operator());

  py::class_<Component, py::smart_holder>(m, "Component", "Assembly-local instance of a Part or subassembly.")
      .def(py::init([](const py::object& component_id, const py::object& item, const py::object& placement, const py::object& name) {
             return Component(text(component_id, "component_id"), item_of(item), typed<Placement>(placement, "placement must be a Placement"),
                              optional_name(name));
           }),
           py::arg("component_id"), py::arg("item"), py::arg("placement"), py::arg("name") = py::none())
      .def_readonly("component_id", &Component::component_id)
      .def_property_readonly("item", [](const Component& self) { return py_item(self.item); })
      .def_readonly("placement", &Component::placement)
      .def_property_readonly("name", [](const Component& self) { return optional_object(self.name); })
      .def("to_dict", [](const Component& self) { return self.to_dict(); });

  py::class_<Assembly, py::smart_holder> cls(m, "Assembly", "Product structure containing placed Part or subassembly components.");
  cls.def(py::init([](const py::object& assembly_id, const py::object& name, const py::object& components, const py::object& publics,
                      const py::object& constraints, const py::object& grounded) {
            std::vector<Component> component_values;
            std::vector<PublicConnectorRef> public_values;
            std::vector<Constraint> constraint_values;
            std::vector<std::string> grounded_values;
            if (!components.is_none()) {
              for (const py::handle item : components) {
                component_values.push_back(typed<Component>(py::reinterpret_borrow<py::object>(item), "components must contain Component values"));
              }
            }
            if (!publics.is_none()) {
              for (const py::handle item : publics) {
                public_values.push_back(typed<PublicConnectorRef>(py::reinterpret_borrow<py::object>(item), "public_connectors must contain PublicConnectorRef values"));
              }
            }
            if (!constraints.is_none()) {
              for (const py::handle item : constraints) {
                constraint_values.push_back(typed<Constraint>(py::reinterpret_borrow<py::object>(item), "constraints must contain Constraint values"));
              }
            }
            if (!grounded.is_none()) {
              for (const py::handle item : grounded) grounded_values.push_back(text(py::reinterpret_borrow<py::object>(item), "component_id"));
            }
            return std::make_shared<Assembly>(text(assembly_id, "assembly_id"), optional_name(name), std::move(component_values),
                                              std::move(public_values), std::move(constraint_values), std::move(grounded_values));
          }),
          py::arg("assembly_id"), py::arg("name") = py::none(), py::arg("components") = py::tuple(),
          py::arg("public_connectors") = py::tuple(), py::arg("constraints") = py::tuple(),
          py::arg("grounded_component_ids") = py::tuple())
      .def_property_readonly("assembly_id", &Assembly::assembly_id)
      .def_property_readonly("name", [](const Assembly& self) { return optional_object(self.name()); })
      .def_property_readonly("components", [](const Assembly& self) { return to_tuple(self.components()); })
      .def_property_readonly("public_connectors", [](const Assembly& self) { return to_tuple(self.public_connectors()); })
      .def_property_readonly("constraints", [](const Assembly& self) { return to_tuple(self.constraints()); })
      .def_property_readonly("grounded_component_ids", [](const Assembly& self) { return to_tuple(self.grounded_component_ids()); })
      .def("component_ids", [](const Assembly& self) { return to_tuple(self.component_ids()); })
      .def("get_component", [](const Assembly& self, const py::object& id) { return self.get_component(text(id, "component_id")); },
           py::arg("component_id"))
      .def("with_component", [](const Assembly& self, const py::object& component) {
             return std::make_shared<const Assembly>(self.with_component(typed<Component>(component, "component must be a Component")));
           }, py::arg("component"))
      .def("with_component_placement", [](const Assembly& self, const py::object& id, const py::object& placement) {
             return std::make_shared<const Assembly>(self.with_component_placement(
                 text(id, "component_id"), typed<Placement>(placement, "placement must be a Placement")));
           }, py::arg("component_id"), py::arg("placement"))
      .def("public_connector_ids", [](const Assembly& self) { return to_tuple(self.public_connector_ids()); })
      .def("get_public_connector", [](const Assembly& self, const py::object& id) {
             return self.get_public_connector(text(id, "public_connector_id"));
           }, py::arg("public_connector_id"))
      .def("with_public_connector", [](const Assembly& self, const py::object& pub) {
             return std::make_shared<const Assembly>(self.with_public_connector(typed<PublicConnectorRef>(pub, "public must be a PublicConnectorRef")));
           }, py::arg("public"))
      .def("constraint_ids", [](const Assembly& self) { return to_tuple(self.constraint_ids()); })
      .def("get_constraint", [](const Assembly& self, const py::object& id) { return self.get_constraint(text(id, "constraint_id")); },
           py::arg("constraint_id"))
      .def("with_constraint", [](const Assembly& self, const py::object& constraint) {
             return std::make_shared<const Assembly>(self.with_constraint(typed<Constraint>(constraint, "constraint must be a Constraint")));
           }, py::arg("constraint"))
      .def("with_grounded_component", [](const Assembly& self, const py::object& id) {
             return std::make_shared<const Assembly>(self.with_grounded_component(text(id, "component_id")));
           }, py::arg("component_id"))
      .def("without_grounded_component", [](const Assembly& self, const py::object& id) {
             return std::make_shared<const Assembly>(self.without_grounded_component(text(id, "component_id")));
           }, py::arg("component_id"))
      .def("to_dict", [](const Assembly& self) { return self.to_dict(); })
      .def("__repr__", [](const Assembly& self) { return "Assembly(assembly_id=" + str_repr(self.assembly_id()) + ", name=" + opt_str_repr(self.name()) + ")"; });
  bind_semantic_value<Assembly>(cls);
}

}  // namespace

void bind_product_values(py::module_& m) {
  bind_placement(m);
  bind_material(m);
  bind_limit_and_refs(m);
  bind_connectors(m);
  bind_constraints(m);
  bind_part(m);
  bind_assembly(m);
}
