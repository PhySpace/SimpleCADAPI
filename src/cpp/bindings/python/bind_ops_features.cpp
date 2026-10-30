// Python bindings for the "ops_features" area: the operators of operators/{features,boolean,
// transform}.py under the Python names, argument names and defaults (keyword-only where
// Python is keyword-only).
//
// The GIL is released around the kernel work, except while a ql selector is being resolved
// (a property resolver registered from Python is called back from there).
#include "bindings.hpp"

#include <optional>
#include <string>
#include <vector>

#include "scad/core/tolerance.hpp"
#include "scad/core/error.hpp"
#include "scad/ops/features/features.hpp"
#include "scad/ql/ql.hpp"
#include "scad/reactive/registry.hpp"

namespace {

using namespace scad;

// ---- conversions ---------------------------------------------------------------------------------------------
py::object shape_to_py(const Shape& s) {
  switch (s.kind()) {
    case Kind::Vertex:
      return py::cast(Vertex(s));
    case Kind::Edge:
      return py::cast(Edge(s));
    case Kind::Wire:
      return py::cast(Wire(s));
    case Kind::Face:
      return py::cast(Face(s));
    case Kind::Shell:
      return py::cast(Shell(s));
    case Kind::Solid:
      return py::cast(Solid(s));
    case Kind::Compound:
      return py::cast(Compound(s));
  }
  return py::none();
}

py::list shapes_to_py(const std::vector<Shape>& shapes) {
  py::list out;
  for (const Shape& shape : shapes)
    out.append(shape_to_py(shape));
  return out;
}

py::list solids_to_py(const std::vector<Solid>& solids) {
  py::list out;
  for (const Solid& solid : solids)
    out.append(py::cast(solid));
  return out;
}

// A list of shapes of one kind, or a ql selector that finds them.
template <class T>
Selection<T> selection_from(const py::object& value) {
  if (py::isinstance<ql::ShapeSelector>(value))
    return Selection<T>(value.cast<const ql::ShapeSelector&>());
  std::vector<T> items;
  for (const py::handle item : value) {
    if (!py::isinstance<T>(item)) {
      throw TypeError(std::string("expected a ") + std::string(kind_name(T::kKind)) + " or a QL selector");
    }
    items.push_back(item.cast<T>());
  }
  return Selection<T>(std::move(items));
}

// A 3-vector argument that Python validates itself: any sequence of numbers, ValueError unless it
// holds exactly three.
Scalar3 vector_arg(const py::object& value, const char* name) {
  const std::string message = std::string(name) + " must contain three finite numbers";
  if ((py::isinstance<py::str>(value) || py::isinstance<py::bytes>(value)) || !py::hasattr(value, "__len__") ||
      !py::hasattr(value, "__getitem__"))
    throw ValueError(message);
  const py::sequence items = py::reinterpret_borrow<py::sequence>(value);
  if (items.size() != 3)
    throw ValueError(message);
  Scalar3 out;
  for (std::size_t i = 0; i < 3; ++i)
    out[i] = items[i].cast<Scalar>();
  return out;
}

std::vector<Shape> shape_list(const py::object& value, const char* complaint) {
  std::vector<Shape> out;
  for (const py::handle item : value) {
    if (!py::isinstance<Shape>(item))
      throw TypeError(complaint);
    out.push_back(item.cast<Shape>());
  }
  return out;
}

// An operator that takes `tracking_policy`: the enum member or its string value.
std::string policy_text(const py::object& value) {
  if (py::isinstance<py::str>(value))
    return value.cast<std::string>();
  if (py::hasattr(value, "value"))
    return py::str(value.attr("value")).cast<std::string>();
  return py::str(value).cast<std::string>();
}

// Runs `body` with the GIL released unless `keep_gil`.  An exception leaves with the GIL back.
template <class F>
auto unlocked(bool keep_gil, F&& body) {
  std::optional<py::gil_scoped_release> release;
  if (!keep_gil)
    release.emplace();
  return body();
}

py::tuple unit_z() {
  return py::make_tuple(0, 0, 1);
}
py::tuple origin() {
  return py::make_tuple(0, 0, 0);
}

// ---- sweeps of a profile ------------------------------------------------------------------------------------
SweepTags sweep_tags(OptionalString tag_prefix, OptionalString result_tag, OptionalString start, OptionalString end,
                     OptionalString side) {
  return {std::move(tag_prefix), std::move(result_tag), std::move(start), std::move(end), std::move(side)};
}

void bind_extrusion(py::module_& m) {
  m.def(
      "extrude_rsolid",
      [](const Shape& profile, const Scalar3& direction, const Scalar& distance, OptionalString tag_prefix,
         OptionalString result_tag, OptionalString start_face_tag, OptionalString end_face_tag,
         OptionalString side_faces_tag) {
        const SweepTags tags = sweep_tags(std::move(tag_prefix), std::move(result_tag), std::move(start_face_tag),
                                          std::move(end_face_tag), std::move(side_faces_tag));
        return unlocked(false, [&] { return extrude_rsolid(profile, direction, distance, tags); });
      },
      py::arg("profile"), py::arg("direction"), py::arg("distance"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      py::arg("result_tag") = py::none(), py::arg("start_face_tag") = py::none(), py::arg("end_face_tag") = py::none(),
      py::arg("side_faces_tag") = py::none(), "Create a solid by extruding a profile, with optional role-based tags.");

  m.def(
      "revolve_rsolid",
      [](const Shape& profile, const Scalar3& axis, const Scalar& angle, const Scalar3& origin,
         OptionalString tag_prefix, OptionalString result_tag, OptionalString start_face_tag,
         OptionalString end_face_tag, OptionalString side_faces_tag) {
        const SweepTags tags = sweep_tags(std::move(tag_prefix), std::move(result_tag), std::move(start_face_tag),
                                          std::move(end_face_tag), std::move(side_faces_tag));
        return unlocked(false, [&] { return revolve_rsolid(profile, axis, angle, origin, tags); });
      },
      py::arg("profile"), py::arg("axis") = unit_z(), py::arg("angle") = 360, py::arg("origin") = origin(),
      py::kw_only(), py::arg("tag_prefix") = py::none(), py::arg("result_tag") = py::none(),
      py::arg("start_face_tag") = py::none(), py::arg("end_face_tag") = py::none(),
      py::arg("side_faces_tag") = py::none(), "Create a revolved solid, with optional kernel-role-based tags.");
}

// ---- local features ------------------------------------------------------------------------------------------
void bind_blends(py::module_& m) {
  m.def(
      "fillet_rsolid",
      [](const Solid& solid, const py::object& edges, const Scalar& radius, OptionalString result_tag,
         OptionalString generated_faces_tag) {
        const EdgeSelection selection = selection_from<Edge>(edges);
        const BlendTags tags{std::move(result_tag), std::move(generated_faces_tag)};
        return unlocked(selection.is_selector(), [&] { return fillet_rsolid(solid, selection, radius, tags); });
      },
      py::arg("solid"), py::arg("edges"), py::arg("radius"), py::kw_only(), py::arg("result_tag") = py::none(),
      py::arg("generated_faces_tag") = py::none(),
      "Apply fillets, with optional tagging of kernel-proven patch faces.");

  m.def(
      "chamfer_rsolid",
      [](const Solid& solid, const py::object& edges, const Scalar& distance, std::optional<double> angle,
         std::optional<Vec3> reference_direction, OptionalString result_tag, OptionalString generated_faces_tag) {
        const EdgeSelection selection = selection_from<Edge>(edges);
        const ChamferOptions options{
            angle, reference_direction, {std::move(result_tag), std::move(generated_faces_tag)}};
        return unlocked(selection.is_selector(), [&] { return chamfer_rsolid(solid, selection, distance, options); });
      },
      py::arg("solid"), py::arg("edges"), py::arg("distance"), py::kw_only(), py::arg("angle") = py::none(),
      py::arg("reference_direction") = py::none(), py::arg("result_tag") = py::none(),
      py::arg("generated_faces_tag") = py::none(),
      "Apply chamfers, with optional tagging of kernel-proven patch faces.\n\nWithout ``angle`` the chamfer is "
      "symmetric. "
      "With ``angle`` (degrees between the chamfer face and the reference face) the second leg is "
      "``distance * tan(angle)``; ``reference_direction`` picks the reference face per edge.");

  m.def(
      "shell_rsolid",
      [](const Solid& solid, const py::object& faces_to_remove, const Scalar& thickness, OptionalString result_tag,
         OptionalString body_faces_tag, OptionalString offset_faces_tag, OptionalString closing_faces_tag,
         OptionalString wall_edges_tag) {
        const FaceSelection selection = selection_from<Face>(faces_to_remove);
        const ShellTags tags{std::move(result_tag), std::move(body_faces_tag), std::move(offset_faces_tag),
                             std::move(closing_faces_tag), std::move(wall_edges_tag)};
        return unlocked(selection.is_selector(), [&] { return shell_rsolid(solid, selection, thickness, tags); });
      },
      py::arg("solid"), py::arg("faces_to_remove"), py::arg("thickness"), py::kw_only(),
      py::arg("result_tag") = py::none(), py::arg("body_faces_tag") = py::none(),
      py::arg("offset_faces_tag") = py::none(), py::arg("closing_faces_tag") = py::none(),
      py::arg("wall_edges_tag") = py::none(), "Shell a solid, with optional kernel-role-based face tags.");
}

// ---- sweeps through sections ---------------------------------------------------------------------------------
void bind_sweeps(py::module_& m) {
  m.def(
      "loft_rsolid",
      [](const py::object& profiles, bool ruled, const py::object& tracking_policy, OptionalString tag_prefix,
         OptionalString result_tag, OptionalString start_face_tag, OptionalString end_face_tag,
         OptionalString side_faces_tag) {
        const std::vector<Shape> sections =
            shape_list(profiles, "loft_rsolid sections must contain only Wire or Vertex objects");
        const LoftOptions options{policy_text(tracking_policy),
                                  sweep_tags(std::move(tag_prefix), std::move(result_tag), std::move(start_face_tag),
                                             std::move(end_face_tag), std::move(side_faces_tag))};
        return unlocked(false, [&] { return loft_rsolid(sections, ruled, options); });
      },
      py::arg("profiles"), py::arg("ruled") = false, py::kw_only(), py::arg("tracking_policy") = "full",
      py::arg("tag_prefix") = py::none(), py::arg("result_tag") = py::none(), py::arg("start_face_tag") = py::none(),
      py::arg("end_face_tag") = py::none(), py::arg("side_faces_tag") = py::none(),
      "Create a lofted solid, with optional kernel-role-based tags.");

  m.def(
      "sweep_rsolid",
      [](const Face& profile, const Wire& path, bool is_frenet, OptionalString tag_prefix, OptionalString result_tag,
         OptionalString start_face_tag, OptionalString end_face_tag, OptionalString side_faces_tag) {
        const SweepTags tags = sweep_tags(std::move(tag_prefix), std::move(result_tag), std::move(start_face_tag),
                                          std::move(end_face_tag), std::move(side_faces_tag));
        return unlocked(false, [&] { return sweep_rsolid(profile, path, is_frenet, tags); });
      },
      py::arg("profile"), py::arg("path"), py::arg("is_frenet") = false, py::kw_only(),
      py::arg("tag_prefix") = py::none(), py::arg("result_tag") = py::none(), py::arg("start_face_tag") = py::none(),
      py::arg("end_face_tag") = py::none(), py::arg("side_faces_tag") = py::none(),
      "Create a swept solid, with optional kernel-role-based tags.");

  m.def(
      "twisted_sweep_rsolid",
      [](const Shape& profile, const Scalar& distance, const Scalar& twist_angle, const Scalar3& axis,
         const Scalar3& origin, const Scalar& guide_radius, OptionalString tag_prefix, OptionalString result_tag,
         OptionalString start_face_tag, OptionalString end_face_tag, OptionalString side_faces_tag) {
        const TwistedSweepOptions options{
            guide_radius, sweep_tags(std::move(tag_prefix), std::move(result_tag), std::move(start_face_tag),
                                     std::move(end_face_tag), std::move(side_faces_tag))};
        return unlocked(false,
                        [&] { return twisted_sweep_rsolid(profile, distance, twist_angle, axis, origin, options); });
      },
      py::arg("profile"), py::arg("distance"), py::arg("twist_angle"), py::arg("axis") = unit_z(),
      py::arg("origin") = origin(), py::kw_only(), py::arg("guide_radius") = 1.0, py::arg("tag_prefix") = py::none(),
      py::arg("result_tag") = py::none(), py::arg("start_face_tag") = py::none(), py::arg("end_face_tag") = py::none(),
      py::arg("side_faces_tag") = py::none(),
      "Sweep a planar profile along a straight axis with linear rotation (twist_angle in degrees).");

  m.def(
      "helical_sweep_rsolid",
      [](const Wire& profile, const Scalar& pitch, const Scalar& height, const Scalar& radius, const Scalar3& center,
         const Scalar3& dir, const std::string& handedness) {
        return unlocked(false,
                        [&] { return helical_sweep_rsolid(profile, pitch, height, radius, center, dir, handedness); });
      },
      py::arg("profile"), py::arg("pitch"), py::arg("height"), py::arg("radius"), py::arg("center") = origin(),
      py::arg("dir") = unit_z(), py::kw_only(), py::arg("handedness") = "Right",
      "Create a solid by sweeping a profile along a helical path.");

  m.def(
      "sweep_multisection_rsolid",
      [](const py::object& profiles, const Wire& path, bool is_frenet, const py::object& binormal) {
        const std::vector<Shape> sections = shape_list(profiles, "sections must be Face or Wire");
        std::optional<Binormal> aux;
        if (py::isinstance<Wire>(binormal))
          aux = Binormal(binormal.cast<Wire>());
        else if (!binormal.is_none())
          aux = Binormal(vector_arg(binormal, "binormal"));
        return unlocked(false, [&] { return sweep_multisection_rsolid(sections, path, is_frenet, aux); });
      },
      py::arg("profiles"), py::arg("path"), py::arg("is_frenet") = false, py::arg("binormal") = py::none(),
      "Sweep through explicit ordered sections along a continuous path.");
}

// ---- derived solids ---------------------------------------------------------------------------------------------
void bind_derived(py::module_& m) {
  m.def(
      "offset_rsolid",
      [](const Solid& solid, const Scalar& amount, const py::object& openings, double tolerance,
         const std::string& kind) {
        const FaceSelection selection = selection_from<Face>(openings);
        return unlocked(selection.is_selector(),
                        [&] { return offset_rsolid(solid, amount, selection, {tolerance, kind}); });
      },
      py::arg("solid"), py::arg("amount"), py::arg("openings") = py::tuple(), py::kw_only(),
      py::arg("tolerance") = tol::kOffsetTolerance, py::arg("kind") = "ARC",
      "Offset a solid outward (positive) or inward (negative).");

  m.def(
      "draft_rsolid",
      [](const Solid& solid, const py::object& faces_to_draft, const Scalar& angle, const py::object& plane_origin,
         const py::object& plane_normal) {
        const FaceSelection selection = selection_from<Face>(faces_to_draft);
        const Scalar3 origin_value = vector_arg(plane_origin, "plane_origin"),
                      normal_value = vector_arg(plane_normal, "plane_normal");
        return unlocked(selection.is_selector(),
                        [&] { return draft_rsolid(solid, selection, angle, origin_value, normal_value); });
      },
      py::arg("solid"), py::arg("faces_to_draft"), py::arg("angle"), py::arg("plane_origin") = origin(),
      py::arg("plane_normal") = unit_z(),
      "Draft planar, cylindrical or conical faces by a signed angle in degrees about a neutral plane.");

  m.def(
      "extrude_taper_rsolid",
      [](const Face& profile, const py::object& vector, const Scalar& taper, bool flip_inner) {
        const Scalar3 direction = vector_arg(vector, "vector");
        return unlocked(false, [&] { return extrude_taper_rsolid(profile, direction, taper, flip_inner); });
      },
      py::arg("profile"), py::arg("vector"), py::arg("taper"), py::arg("flip_inner") = true,
      "Extrude a planar sketch face by a vector, with a taper in degrees.");

  m.def(
      "extrude_until_rsolid",
      [](const Face& profile, const py::object& target, const py::object& direction, const py::object& until) {
        std::vector<Solid> targets;
        if (py::isinstance<Solid>(target)) {
          targets.push_back(target.cast<Solid>());
        } else {
          for (const py::handle item : target) {
            if (!py::isinstance<Solid>(item))
              throw TypeError("target must be a Solid or a sequence of Solid");
            targets.push_back(item.cast<Solid>());
          }
        }
        const Scalar3 axis = vector_arg(direction, "direction");
        const std::string mode = py::str(py::hasattr(until, "name") ? until.attr("name") : until).cast<std::string>();
        return unlocked(false, [&] { return extrude_until_rsolid(profile, targets, axis, mode); });
      },
      py::arg("profile"), py::arg("target"), py::arg("direction") = unit_z(), py::arg("until") = "NEXT",
      "Extrude a planar face until a target surface, including curved surfaces.");

  m.def(
      "scale_rsolid",
      [](const Solid& solid, const py::object& factors, const py::object& center) {
        const Scalar3 scale = vector_arg(factors, "factors"), about = vector_arg(center, "center");
        return unlocked(false, [&] { return scale_rsolid(solid, scale, about); });
      },
      py::arg("solid"), py::arg("factors"), py::arg("center") = origin(),
      "Scale a solid along the current coordinate system's axes about a center.");

  m.def(
      "transform_rsolid",
      [](const Solid& solid, const std::vector<std::vector<Scalar>>& matrix) {
        return unlocked(false, [&] { return transform_rsolid(solid, matrix); });
      },
      py::arg("solid"), py::arg("matrix"),
      "Apply a finite nonsingular 4x4 affine matrix in the current coordinate system.");
}

// ---- tracking policy and the failure diagnoses ------------------------------------------------------------------
// `with tracking_policy_scope(TrackingPolicy.GRAPH): ...`
class PolicyScope {
 public:
  explicit PolicyScope(TrackingPolicy policy) : policy_(policy) {}
  PolicyScope& enter() {
    scope_.emplace(policy_);
    return *this;
  }
  void exit() { scope_.reset(); }

 private:
  TrackingPolicy policy_;
  std::optional<TrackingPolicyScope> scope_;
};

void bind_tracking_policy(py::module_& m) {
  py::list members;
  members.append(py::make_tuple("FULL", "full"));
  members.append(py::make_tuple("GRAPH", "graph"));
  py::dict kwargs;
  kwargs["type"] = py::module_::import("builtins").attr("str");
  kwargs["module"] = "simplecadapi._cpp";
  m.attr("TrackingPolicy") = py::module_::import("enum").attr("Enum")("TrackingPolicy", members, **kwargs);

  py::class_<PolicyScope, std::shared_ptr<PolicyScope>>(m, "_TrackingPolicyScope")
      .def("__enter__",
           [](const std::shared_ptr<PolicyScope>& scope) {
             scope->enter();
             return scope;
           })
      .def("__exit__", [](PolicyScope& scope, const py::args&) { scope.exit(); });
  m.def(
      "tracking_policy_scope",
      [](const py::object& policy) {
        const std::string text = policy_text(policy);
        if (text == "full")
          return std::make_shared<PolicyScope>(TrackingPolicy::Full);
        if (text == "graph")
          return std::make_shared<PolicyScope>(TrackingPolicy::Graph);
        throw ValueError("'" + text + "' is not a valid TrackingPolicy");
      },
      py::arg("policy"), "Run a block with graph-only or full topology tracking.");
  m.def("current_tracking_policy", [] { return std::string(to_string(current_tracking_policy())); });
}

py::list measurements_to_py(const std::vector<ErrorMeasurement>& measurements) {
  py::list out;
  for (const ErrorMeasurement& item : measurements) {
    py::dict entry;
    entry["name"] = item.name;
    if (const auto* number = std::get_if<double>(&item.value))
      entry["value"] = *number;
    else {
      const auto& v = std::get<std::array<double, 3>>(item.value);
      entry["value"] = py::make_tuple(v[0], v[1], v[2]);
    }
    entry["unit"] = item.unit;
    out.append(entry);
  }
  return out;
}

template <class Diagnosis>
void bind_diagnosis(py::module_& m, const char* name) {
  py::class_<Diagnosis>(m, name)
      .def_readonly("failure_kind", &Diagnosis::failure_kind)
      .def_readonly("what_happened", &Diagnosis::what_happened)
      .def_readonly("possible_causes", &Diagnosis::possible_causes)
      .def_readonly("repair", &Diagnosis::repair)
      .def_property_readonly("measurements", [](const Diagnosis& d) { return measurements_to_py(d.measurements); });
}

void bind_diagnostics(py::module_& m) {
  bind_diagnosis<BlendDiagnosis>(m, "BlendDiagnosis");
  bind_diagnosis<BooleanDiagnosis>(m, "BooleanDiagnosis");

  m.def(
      "diagnose_blend_failure",
      [](const Solid& solid, const py::list& edges, double size_value, const std::string& operation_kind,
         const py::object& retry_single) {
        std::vector<Edge> items;
        for (const py::handle item : edges)
          items.push_back(item.cast<Edge>());
        BlendRetry retry;
        if (!retry_single.is_none())
          retry = [&](const Edge& edge) { return py::bool_(retry_single(py::cast(edge))).cast<bool>(); };
        return diagnose_blend_failure(solid, items, size_value, operation_kind, retry);
      },
      py::arg("solid"), py::arg("edges"), py::kw_only(), py::arg("size_value"), py::arg("operation_kind"),
      py::arg("retry_single") = py::none(), "Classify a fillet/chamfer failure; None when no probe explains it.");

  m.def(
      "assert_blend_volume_monotonic",
      [](const Solid& source, const Solid& result, const std::string&, const std::string& operation_kind,
         std::optional<double> size_value, const py::list& edges) {
        std::vector<Edge> items;
        for (const py::handle item : edges)
          items.push_back(item.cast<Edge>());
        assert_blend_volume_monotonic(source, result, operation_kind, size_value, items);
      },
      py::arg("source"), py::arg("result"), py::kw_only(), py::arg("operation"), py::arg("operation_kind"),
      py::arg("size_value"), py::arg("edges"),
      "Raise when an all-convex blend returned more material than it was given.");

  m.def(
      "diagnose_boolean_failure",
      [](const py::list& operands, std::optional<double> effective_tol, const std::string& operation_kind) {
        std::vector<Solid> solids;
        for (const py::handle item : operands)
          solids.push_back(item.cast<Solid>());
        return diagnose_boolean_failure(solids, effective_tol, operation_kind);
      },
      py::arg("operands"), py::kw_only(), py::arg("effective_tol"), py::arg("operation_kind") = "union",
      "Classify a boolean failure from its operands; None when none explains it.");

  m.def(
      "raise_loft_failure_if_diagnosed",
      [](const py::object& sections, const std::string& operation) {
        raise_loft_failure_if_diagnosed(shape_list(sections, "loft sections must be shapes"), operation);
      },
      py::arg("sections"), py::arg("operation"), "Explain a failed loft from its sections, when they do.");
}

// ---- booleans ------------------------------------------------------------------------------------------------
// The Solids of `args`, nested lists and tuples flattened; anything else is the operator's own error.
void flatten_solids(const py::handle& value, std::string_view operation, std::vector<Solid>& out) {
  if (py::isinstance<Solid>(value)) {
    out.push_back(value.cast<Solid>());
  } else if (py::isinstance<py::list>(value) || py::isinstance<py::tuple>(value)) {
    for (const py::handle item : value)
      flatten_solids(item, operation, out);
  } else {
    reject_boolean_operand(operation);
  }
}

std::vector<Solid> flattened(const py::args& args, std::string_view operation) {
  std::vector<Solid> out;
  for (const py::handle item : args)
    flatten_solids(item, operation, out);
  return out;
}

std::vector<Solid> solid_group(const py::object& group) {
  std::vector<Solid> out;
  for (const py::handle item : group) {
    if (!py::isinstance<Solid>(item))
      throw TypeError("boolean groups must contain Solid values");
    out.push_back(item.cast<Solid>());
  }
  return out;
}

void bind_booleans(py::module_& m) {
  m.def(
      "union_rsolid",
      [](const py::args& solids, bool clean, bool glue, std::optional<double> tol, const py::object& tracking_policy) {
        const std::vector<Solid> operands = flattened(solids, "union_rsolid");
        const UnionOptions options{clean, glue, tol, policy_text(tracking_policy)};
        return unlocked(false, [&] { return union_rsolid(operands, options); });
      },
      py::kw_only(), py::arg("clean") = true, py::arg("glue") = false, py::arg("tol") = py::none(),
      py::arg("tracking_policy") = "full", "Compute the boolean union and return one manifold solid.");

  m.def(
      "cut_rsolid",
      [](const py::args& solids, bool skip_non_intersecting, const py::object& tracking_policy) {
        const std::vector<Solid> operands = flattened(solids, "cut_rsolid");
        const CutOptions options{skip_non_intersecting, policy_text(tracking_policy)};
        return unlocked(false, [&] { return cut_rsolid(operands, options); });
      },
      py::kw_only(), py::arg("skip_non_intersecting") = true, py::arg("tracking_policy") = "full",
      "Compute the boolean difference of solids: the first is the base, the rest are subtracted in order.");

  m.def(
      "cut_rsolid_list",
      [](const py::args& solids, bool skip_non_intersecting, const py::object& tracking_policy) {
        const std::vector<Solid> operands = flattened(solids, "cut_rsolid_list");
        const CutOptions options{skip_non_intersecting, policy_text(tracking_policy)};
        return solids_to_py(unlocked(false, [&] { return cut_rsolid_list(operands, options); }));
      },
      py::kw_only(), py::arg("skip_non_intersecting") = true, py::arg("tracking_policy") = "full",
      "Compute the boolean difference of solids and keep every piece: a cut that splits the body returns each part, "
      "and one that consumes the body returns an empty list.");

  m.def(
      "intersect_rsolid",
      [](const py::args& solids) {
        const std::vector<Solid> operands = flattened(solids, "intersect_rsolid");
        return unlocked(false, [&] { return intersect_rsolid(operands); });
      },
      "Compute the boolean intersection of solids.");

  m.def(
      "boolean_rsolidlist",
      [](const py::object& left, const py::object& right, const std::string& operation) {
        if (operation != "cut" && operation != "intersect" && operation != "union") {
          throw ValueError("operation must be cut, intersect or union");
        }
        const std::vector<Solid> lhs = solid_group(left), rhs = solid_group(right);
        return solids_to_py(unlocked(false, [&] { return boolean_rsolidlist(lhs, rhs, operation); }));
      },
      py::arg("left"), py::arg("right"), py::arg("operation"),
      "Apply a set boolean to two body groups, retaining every result solid.");

  const auto bind_2d = [&m](const char* name, Face (*fn)(const Shape&, const Shape&), const char* first,
                            const char* second, const char* doc) {
    m.def(
        name,
        [fn, name, first, second](const py::object& a, const py::object& b) {
          if (!py::isinstance<Shape>(a))
            reject_face_operand(name, first);
          if (!py::isinstance<Shape>(b))
            reject_face_operand(name, second);
          const Shape& left = a.cast<const Shape&>();
          const Shape& right = b.cast<const Shape&>();
          return unlocked(false, [&] { return fn(left, right); });
        },
        py::arg(first), py::arg(second), doc);
  };
  bind_2d("make_2d_cut_rface", &make_2d_cut_rface, "body", "tool", "Subtract one 2D face from another.");
  bind_2d("make_2d_union_rface", &make_2d_union_rface, "face_a", "face_b",
          "Compute the boolean union of two 2D faces.");
  bind_2d("make_2d_intersect_rface", &make_2d_intersect_rface, "face_a", "face_b",
          "Compute the boolean intersection of two 2D faces.");
}

// ---- transforms and patterns ----------------------------------------------------------------------------------
void bind_transforms(py::module_& m) {
  m.def(
      "translate_shape",
      [](const Shape& shape, const Scalar3& vector) {
        return shape_to_py(unlocked(false, [&] { return translate_shape(shape, vector); }));
      },
      py::arg("shape"), py::arg("vector"), "Translate a shape by an offset vector.");

  m.def(
      "rotate_shape",
      [](const Shape& shape, const Scalar& angle, const Scalar3& axis, const Scalar3& origin) {
        return shape_to_py(unlocked(false, [&] { return rotate_shape(shape, angle, axis, origin); }));
      },
      py::arg("shape"), py::arg("angle"), py::arg("axis") = unit_z(), py::arg("origin") = origin(),
      "Rotate a shape around an axis.");

  m.def(
      "mirror_shape",
      [](const Shape& shape, const Scalar3& plane_origin, const Scalar3& plane_normal) {
        return shape_to_py(unlocked(false, [&] { return mirror_shape(shape, plane_origin, plane_normal); }));
      },
      py::arg("shape"), py::arg("plane_origin"), py::arg("plane_normal"), "Mirror a shape across a plane.");

  m.def(
      "linear_pattern_rsolidlist",
      [](const Shape& shape, const Scalar3& direction, int count, const Scalar& spacing) {
        return shapes_to_py(
            unlocked(false, [&] { return linear_pattern_rsolidlist(shape, direction, count, spacing); }));
      },
      py::arg("shape"), py::arg("direction"), py::arg("count"), py::arg("spacing"),
      "Create a linear pattern of solids.");

  m.def(
      "radial_pattern_rsolidlist",
      [](const Shape& shape, const Scalar3& center, const Scalar3& axis, int count,
         const Scalar& total_rotation_angle) {
        return shapes_to_py(unlocked(
            false, [&] { return radial_pattern_rsolidlist(shape, center, axis, count, total_rotation_angle); }));
      },
      py::arg("shape"), py::arg("center"), py::arg("axis"), py::arg("count"), py::arg("total_rotation_angle"),
      "Create a radial pattern of solids.");
}

}  // namespace

void bind_ops_features(py::module_& m) {
  bind_extrusion(m);
  bind_blends(m);
  bind_booleans(m);
  bind_transforms(m);
  bind_sweeps(m);
  bind_derived(m);
  bind_tracking_policy(m);
  bind_diagnostics(m);
  register_features_executors(reactive::ExecutorRegistry::global());
}
