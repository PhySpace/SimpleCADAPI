#include "scad/sketch/sketch.hpp"
#include "scad/topo/recorder.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <random>
#include <set>

#include "scad/core/error.hpp"
#include "scad/sketch/bspline_params.hpp"
#include "scad/sketch/diagnostics.hpp"
#include "scad/sketch/solver.hpp"

namespace scad {

namespace {

constexpr double kPointEps = 1e-9;

thread_local const SketchIdAllocatorScope::Allocator* g_id_allocator = nullptr;

std::string random_sketch_id() {
  thread_local std::mt19937_64 engine{std::random_device{}()};
  char buffer[16];
  std::snprintf(buffer, sizeof buffer, "%08x", static_cast<unsigned>(engine() & 0xffffffffu));
  return std::string("sketch_") + buffer;
}

std::string fresh_id(const std::string& prefix, const std::set<std::string>& existing) {
  for (int index = 0;; ++index) {
    std::string candidate = prefix + "_" + std::to_string(index);
    if (existing.count(candidate) == 0)
      return candidate;
  }
}

double distance(const SketchPoint2& a, const SketchPoint2& b) {
  return std::hypot(a.first - b.first, a.second - b.second);
}

std::array<double, 3> vector3(const Value& plane, const char* key, const std::array<double, 3>& fallback) {
  const Value* value = plane.find(key);
  if (value == nullptr)
    return fallback;
  const bool ok = value->is_array() && value->as_array().size() == 3;
  if (!ok)
    throw ValueError("Sketch plane origin and axes must be 3-D vectors");
  std::array<double, 3> out{};
  for (std::size_t i = 0; i < 3; ++i) {
    const Value& item = value->as_array()[i];
    if (!item.is_number())
      throw ValueError("Sketch plane origin and axes must be 3-D vectors");
    out[i] = item.as_double();
  }
  return out;
}

}  // namespace

// ---- id allocation --------------------------------------------------------
SketchIdAllocatorScope::SketchIdAllocatorScope(Allocator allocate)
    : allocate_(std::move(allocate)), previous_(g_id_allocator) {
  g_id_allocator = &allocate_;
}
SketchIdAllocatorScope::~SketchIdAllocatorScope() {
  g_id_allocator = previous_;
}

std::optional<std::string> allocate_sketch_id() {
  if (g_id_allocator != nullptr && *g_id_allocator)
    return (*g_id_allocator)();
  // Inside a recorded session an unnamed sketch is named by the session (make_sketch_rsketch).
  if (Recorder* recorder = current_recorder())
    return recorder->reserve_object_id("sketch");
  return std::nullopt;
}

// ---- construction ---------------------------------------------------------
Sketch::Sketch(std::optional<std::string> name, Value plane, std::optional<std::string> sketch_id)
    : name_(std::move(name)), plane_(std::move(plane)) {
  if (sketch_id && !sketch_id->empty()) {
    sketch_id_ = *sketch_id;
  } else if (auto allocated = allocate_sketch_id(); allocated && !allocated->empty()) {
    sketch_id_ = *allocated;
  } else {
    sketch_id_ = random_sketch_id();
  }
  (void)plane_frame();  // reject a bad plane up front, like Sketch.__init__
}

Sketch Sketch::clone(bool include_solve) const {
  Sketch copy = *this;
  copy.runtime_ = Value::object();  // a copy is not the recorded value
  if (!include_solve)
    copy.last_solve_.reset();
  return copy;
}

Value Sketch::to_value() const {
  Value out = Value::object();
  out.set("sketch_id", sketch_id_);
  out.set("name", name_ ? Value(*name_) : Value());
  out.set("plane", plane_);
  Value::Array entity_values;
  for (const auto& [id, entity] : entities_)
    entity_values.push_back(entity.to_value());
  out.set("entities", Value(std::move(entity_values)));
  Value::Array constraint_values;
  for (const auto& constraint : constraints_)
    constraint_values.push_back(constraint.to_value());
  out.set("constraints", Value(std::move(constraint_values)));
  return out;
}

Sketch Sketch::from_value(const Value& data) {
  const Value* name_value = data.find("name");
  std::optional<std::string> name;
  if (name_value != nullptr && !name_value->is_null())
    name = name_value->as_string();
  const Value* plane_value = data.find("plane");
  Value plane = plane_value != nullptr ? *plane_value : Value("XY");

  std::string sketch_id = "sketch";
  if (const Value* id_value = data.find("sketch_id");
      id_value != nullptr && id_value->is_string() && !id_value->as_string().empty()) {
    sketch_id = id_value->as_string();
  } else if (name && !name->empty()) {
    sketch_id = *name;
  }
  Sketch sketch(name, std::move(plane), sketch_id);

  if (const Value* entities = data.find("entities")) {
    for (const Value& item : entities->as_array()) {
      SketchEntity entity;
      entity.id = item.find("id")->as_string();
      entity.kind = item.find("kind")->as_string();
      if (const Value* construction = item.find("construction"))
        entity.construction = construction->as_bool();
      for (const auto& [key, value] : item.as_object()) {
        if (key == "id" || key == "kind" || key == "construction")
          continue;
        entity.data.set(key, value);
      }
      sketch.add_entity(std::move(entity));
    }
  }
  if (const Value* constraints = data.find("constraints")) {
    for (const Value& item : constraints->as_array()) {
      SketchConstraint constraint;
      constraint.id = item.find("id")->as_string();
      constraint.kind = item.find("kind")->as_string();
      if (const Value* targets = item.find("targets")) {
        for (const Value& target : targets->as_array())
          constraint.targets.push_back(SketchRef::from_value(target));
      }
      if (const Value* value = item.find("value"); value != nullptr && !value->is_null()) {
        if (!value->is_number())
          throw TypeError("Sketch constraint values must be numbers");
        constraint.value = Scalar(value->as_double());
      }
      if (const Value* driving = item.find("driving"))
        constraint.driving = driving->as_bool();
      if (const Value* metadata = item.find("metadata"))
        constraint.metadata = *metadata;
      sketch.constraints_.push_back(std::move(constraint));
    }
  }
  return sketch;
}

// ---- refs -----------------------------------------------------------------
SketchRef Sketch::ref(const std::string& entity_id, const std::optional<std::string>& kind,
                      const std::string& subentity) const {
  const SketchEntity* entity = entities_.find(entity_id);
  if (entity == nullptr)
    throw ValueError("Unknown sketch entity '" + entity_id + "'");
  return SketchRef{sketch_id_, entity_id, kind ? *kind : entity->kind, subentity};
}

SketchRef Sketch::point_ref(const std::string& path) const {
  if (const auto dot = path.find('.'); dot != std::string::npos) {
    const std::string entity_id = path.substr(0, dot);
    const std::string subentity = path.substr(dot + 1);
    const SketchEntity* entity = entities_.find(entity_id);
    if (entity == nullptr)
      throw ValueError("Unknown sketch entity '" + entity_id + "'");
    static const std::map<std::string, std::set<std::string>, std::less<>> kValid{
        {"line", {"start", "end"}},
        {"circle", {"center"}},
        {"arc", {"start", "end", "center"}},
        {"bspline", {"start", "end"}},
        {"ellipse", {"center", "major", "minor"}},
    };
    const auto valid = kValid.find(entity->kind);
    if (valid == kValid.end() || valid->second.count(subentity) == 0) {
      throw ValueError("Sketch entity '" + entity_id + "' has no point subentity '" + subentity + "'");
    }
    return SketchRef{sketch_id_, entity_id, "point", subentity};
  }
  const SketchEntity* entity = entities_.find(path);
  if (entity == nullptr)
    throw ValueError("Unknown sketch point '" + path + "'");
  if (entity->kind != kPointKind) {
    throw ValueError("Sketch entity '" + path + "' is kind '" + entity->kind + "', not 'point'");
  }
  return SketchRef{sketch_id_, path, "point", "geometry"};
}

SketchRef Sketch::resolve_target(const SketchTarget& target, const std::vector<std::string>& expected) const {
  const std::set<std::string> expected_kinds(expected.begin(), expected.end());
  SketchRef resolved;
  if (target.is_ref()) {
    resolved = target.ref();
  } else {
    const std::string& path = target.path();
    if (path.find('.') != std::string::npos || expected_kinds == std::set<std::string>{"point"}) {
      resolved = point_ref(path);
    } else {
      const SketchEntity* entity = entities_.find(path);
      if (entity == nullptr)
        throw ValueError("Unknown sketch entity '" + path + "'");
      resolved = entity->kind == kPointKind ? point_ref(path) : ref(path);
    }
  }
  validate_ref(resolved);
  if (!expected_kinds.empty() && expected_kinds.count(resolved.kind) == 0) {
    std::string label;
    for (const std::string& kind : expected_kinds) {  // std::set iterates sorted, like sorted()
      if (!label.empty())
        label += ", ";
      label += kind;
    }
    throw ValueError("Sketch target '" + resolved.entity_id + "' is kind '" + resolved.kind + "', expected " + label);
  }
  return resolved;
}

void Sketch::validate_ref(const SketchRef& ref) const {
  if (ref.sketch_id != sketch_id_)
    throw ValueError("SketchRef belongs to a different sketch");
  const SketchEntity* entity = entities_.find(ref.entity_id);
  if (entity == nullptr)
    throw ValueError("Unknown sketch entity '" + ref.entity_id + "'");
  if (ref.kind == kPointKind) {
    (void)resolve_point_id(ref);
  } else if (ref.kind == kLineKind || ref.kind == kCircleKind || ref.kind == kArcKind || ref.kind == kBSplineKind ||
             ref.kind == kEllipseKind) {
    if (entity->kind != ref.kind) {
      throw ValueError("SketchRef '" + ref.entity_id + "' is kind '" + entity->kind + "', not '" + ref.kind + "'");
    }
  }
}

std::string Sketch::resolve_point_id(const SketchRef& ref) const {
  if (ref.sketch_id != sketch_id_)
    throw ValueError("SketchRef belongs to a different sketch");
  const SketchEntity* entity = entities_.find(ref.entity_id);
  if (entity == nullptr)
    throw ValueError("Unknown sketch entity '" + ref.entity_id + "'");
  const std::string& sub = ref.subentity;
  if (ref.kind == kPointKind && entity->kind == kPointKind)
    return ref.entity_id;
  const auto is_one_of = [&sub](std::initializer_list<const char*> names) {
    return std::any_of(names.begin(), names.end(), [&sub](const char* name) { return sub == name; });
  };
  if ((entity->kind == kLineKind && is_one_of({"start", "end"})) ||
      (entity->kind == kCircleKind && is_one_of({"center"})) ||
      (entity->kind == kArcKind && is_one_of({"start", "end", "center"})) ||
      (entity->kind == kBSplineKind && is_one_of({"start", "end"})) ||
      (entity->kind == kEllipseKind && is_one_of({"center", "major", "minor"}))) {
    return entity->point_id(sub);
  }
  throw ValueError("Cannot resolve " + ref.repr() + " to a sketch point");
}

// ---- building -------------------------------------------------------------
void Sketch::add_entity(SketchEntity entity) {
  if (entities_.contains(entity.id))
    throw ValueError("Duplicate sketch entity id '" + entity.id + "'");
  const std::string id = entity.id;
  entities_.set(id, std::move(entity));
}

SketchPoint2 Sketch::entity_xy(const std::string& point_id) const {
  const SketchEntity& entity = entities_.at(point_id);
  if (entity.kind != kPointKind)
    throw ValueError("Sketch entity '" + point_id + "' is not a point");
  return {entity.number("x"), entity.number("y")};
}

SketchRef Sketch::add_point(const std::string& point_id, const Scalar& x, const Scalar& y) {
  SketchEntity entity;
  entity.id = point_id;
  entity.kind = std::string(kPointKind);
  entity.data.set("x", Value(evaluate_scalar(x, "x")));
  entity.data.set("y", Value(evaluate_scalar(y, "y")));
  if (x.symbolic())
    entity.scalars.emplace("x", x);
  if (y.symbolic())
    entity.scalars.emplace("y", y);
  add_entity(std::move(entity));
  return point_ref(point_id);
}

Sketch& Sketch::add_line(const std::string& entity_id, const SketchRef& start, const SketchRef& end,
                         bool construction) {
  const std::string start_id = resolve_point_id(start);
  const std::string end_id = resolve_point_id(end);
  if (start_id == end_id)
    throw ValueError("A sketch line requires two distinct point refs");
  SketchEntity entity;
  entity.id = entity_id;
  entity.kind = std::string(kLineKind);
  entity.construction = construction;
  entity.data.set("start", start_id);
  entity.data.set("end", end_id);
  add_entity(std::move(entity));
  return *this;
}

Sketch& Sketch::add_circle(const std::string& entity_id, const SketchRef& center, const Scalar& radius,
                           bool construction) {
  const std::string center_id = resolve_point_id(center);
  const double radius_value = evaluate_scalar(radius, "radius");
  if (radius_value <= 0.0)
    throw ValueError("A sketch circle radius must be positive");
  SketchEntity entity;
  entity.id = entity_id;
  entity.kind = std::string(kCircleKind);
  entity.construction = construction;
  entity.data.set("center", center_id);
  entity.data.set("radius", Value(radius_value));
  if (radius.symbolic())
    entity.scalars.emplace("radius", radius);
  add_entity(std::move(entity));
  return *this;
}

Sketch& Sketch::add_arc(const std::string& entity_id, const SketchRef& start, const SketchRef& end,
                        const SketchRef& center, bool construction) {
  const std::string start_id = resolve_point_id(start);
  const std::string end_id = resolve_point_id(end);
  const std::string center_id = resolve_point_id(center);
  if (start_id == end_id)
    throw ValueError("A sketch arc requires two distinct endpoint refs");
  SketchEntity entity;
  entity.id = entity_id;
  entity.kind = std::string(kArcKind);
  entity.construction = construction;
  entity.data.set("start", start_id);
  entity.data.set("end", end_id);
  entity.data.set("center", center_id);
  add_entity(std::move(entity));
  return *this;
}

Sketch& Sketch::add_ellipse(const std::string& entity_id, const SketchRef& center, const SketchRef& major_point,
                            const SketchRef& minor_point, bool construction) {
  const std::string center_id = resolve_point_id(center);
  const std::string major_id = resolve_point_id(major_point);
  const std::string minor_id = resolve_point_id(minor_point);
  if (std::set<std::string>{center_id, major_id, minor_id}.size() != 3) {
    throw ValueError("A sketch ellipse requires three distinct axis points");
  }
  const SketchPoint2 center_xy = entity_xy(center_id);
  const double major_radius = distance(center_xy, entity_xy(major_id));
  const double minor_radius = distance(center_xy, entity_xy(minor_id));
  if (major_radius <= kPointEps || minor_radius <= kPointEps) {
    throw ValueError("A sketch ellipse requires non-degenerate axes");
  }
  if (minor_radius > major_radius) {
    throw ValueError("A sketch ellipse requires the minor axis not to exceed the major axis");
  }
  SketchEntity entity;
  entity.id = entity_id;
  entity.kind = std::string(kEllipseKind);
  entity.construction = construction;
  entity.data.set("center", center_id);
  entity.data.set("major", major_id);
  entity.data.set("minor", minor_id);
  add_entity(std::move(entity));
  return *this;
}

Sketch& Sketch::add_bspline(const std::string& entity_id, const SketchRef& start, const SketchRef& end,
                            const std::vector<SketchControlPoint>& control_points, int degree,
                            const std::optional<std::vector<Scalar>>& knots,
                            const std::optional<std::vector<int>>& multiplicities,
                            const std::optional<std::vector<Scalar>>& weights, bool periodic, bool construction) {
  const std::string start_id = resolve_point_id(start);
  const std::string end_id = resolve_point_id(end);
  if (degree < 1 || degree > 25)
    throw ValueError("degree must be between 1 and 25");
  if (static_cast<int>(control_points.size()) < degree + 1) {
    throw ValueError("bspline requires at least degree+1 control points, got " + std::to_string(control_points.size()));
  }

  // Each normalized pole is either {"point_id": id} or a literal [x, y].
  std::vector<Value> poles;
  std::vector<SketchPoint2> resolved;
  for (const SketchControlPoint& control : control_points) {
    if (control.point) {
      const SketchRef point = resolve_target(*control.point, {"point"});
      const std::string point_id = resolve_point_id(point);
      Value pole = Value::object();
      pole.set("point_id", point_id);
      poles.push_back(std::move(pole));
      resolved.push_back(entity_xy(point_id));
    } else {
      poles.push_back(Value(Value::Array{Value(control.xy[0]), Value(control.xy[1])}));
      resolved.emplace_back(control.xy[0], control.xy[1]);
    }
  }

  const auto evaluate_all = [](const std::optional<std::vector<Scalar>>& values,
                               const char* label) -> std::optional<std::vector<double>> {
    if (!values)
      return std::nullopt;
    std::vector<double> out;
    out.reserve(values->size());
    for (const Scalar& value : *values)
      out.push_back(evaluate_scalar(value, label));
    return out;
  };
  const int control_count = static_cast<int>(poles.size());
  const BSplineKnots resolved_knots =
      normalize_bspline_knots(control_count, degree, periodic, evaluate_all(knots, "knot"), multiplicities);
  const auto resolved_weights = normalize_bspline_weights(evaluate_all(weights, "weight"), control_count);

  const SketchPoint2 start_point = entity_xy(start_id);
  const SketchPoint2 end_point = entity_xy(end_id);
  const auto literal = [](const SketchPoint2& p) { return Value(Value::Array{Value(p.first), Value(p.second)}); };
  if (!periodic) {
    if (poles.front().is_object()) {
      if (poles.front().find("point_id")->as_string() != start_id) {
        throw ValueError("The first B-spline control-point ref must match start");
      }
    } else {
      poles.front() = literal(start_point);
    }
    if (poles.back().is_object()) {
      if (poles.back().find("point_id")->as_string() != end_id) {
        throw ValueError("The last B-spline control-point ref must match end");
      }
    } else {
      poles.back() = literal(end_point);
    }
  }

  SketchEntity entity;
  entity.id = entity_id;
  entity.kind = std::string(kBSplineKind);
  entity.construction = construction;
  entity.data.set("start", start_id);
  entity.data.set("end", end_id);
  entity.data.set("control_points", Value(Value::Array(poles.begin(), poles.end())));
  entity.data.set("degree", degree);
  Value::Array knot_values;
  for (const double knot : resolved_knots.knots)
    knot_values.emplace_back(knot);
  entity.data.set("knots", Value(std::move(knot_values)));
  Value::Array multiplicity_values;
  for (const int mult : resolved_knots.multiplicities)
    multiplicity_values.emplace_back(mult);
  entity.data.set("multiplicities", Value(std::move(multiplicity_values)));
  if (resolved_weights) {
    Value::Array weight_values;
    for (const double weight : *resolved_weights)
      weight_values.emplace_back(weight);
    entity.data.set("weights", Value(std::move(weight_values)));
  } else {
    entity.data.set("weights", Value());
  }
  entity.data.set("periodic", periodic);
  add_entity(std::move(entity));
  return *this;
}

Sketch& Sketch::add_constraint(const std::string& kind, const std::vector<SketchRef>& targets,
                               const std::optional<Scalar>& value, const std::optional<std::string>& constraint_id,
                               bool driving, Value metadata) {
  for (const SketchRef& target : targets)
    validate_ref(target);
  std::set<std::string> existing;
  for (const auto& constraint : constraints_)
    existing.insert(constraint.id);
  const std::string id = constraint_id && !constraint_id->empty() ? *constraint_id : fresh_id("c_" + kind, existing);
  if (existing.count(id) != 0)
    throw ValueError("Duplicate sketch constraint id '" + id + "'");
  SketchConstraint constraint;
  constraint.id = id;
  constraint.kind = kind;
  constraint.targets = targets;
  constraint.value = value;
  constraint.driving = driving;
  constraint.metadata = metadata.is_null() ? Value::object() : std::move(metadata);
  constraints_.push_back(std::move(constraint));
  return *this;
}

// ---- solving --------------------------------------------------------------
SketchSolveResult Sketch::solve(const SketchSolveRequest& request) {
  const std::shared_ptr<SketchSolverBackend> backend =
      request.backend ? request.backend : get_default_sketch_solver_backend();
  SketchSolverOptions options;
  options.tolerance = request.tolerance;
  options.max_iterations = request.max_iterations;
  SketchSolveResult result = backend->solve(*this, options);
  last_solve_ = result;
  if (request.strict && (result.status == "conflicting" || result.status == "failed")) {
    raise_sketch_solve_failure(*this, result);
  }
  if (request.require_fully_constrained && result.dof > 0)
    raise_sketch_underconstrained(*this, result);
  return result;
}

const SketchSolveResult& Sketch::solved_result() {
  if (!last_solve_)
    (void)solve(SketchSolveRequest{});
  return *last_solve_;
}

// ---- plane ----------------------------------------------------------------
SketchPlaneFrame Sketch::plane_frame() const {
  if (plane_.is_string()) {
    std::string token = plane_.as_string();
    std::transform(token.begin(), token.end(), token.begin(),
                   [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    if (token == "XY")
      return {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    if (token == "XZ")
      return {{0, 0, 0}, {1, 0, 0}, {0, 0, 1}, {0, -1, 0}};
    if (token == "YZ")
      return {{0, 0, 0}, {0, 1, 0}, {0, 0, 1}, {1, 0, 0}};
  }
  if (plane_.is_object()) {
    const Vec3 origin(vector3(plane_, "origin", {0.0, 0.0, 0.0}));
    Vec3 x_axis(vector3(plane_, "x_axis", {1.0, 0.0, 0.0}));
    Vec3 y_axis(vector3(plane_, "y_axis", {0.0, 1.0, 0.0}));
    for (const Vec3& v : {origin, x_axis, y_axis}) {
      if (!v.is_finite())
        throw ValueError("Sketch plane origin and axes must contain finite values");
    }
    const double x_length = x_axis.norm();
    if (x_length <= 1.0e-15)
      throw ValueError("Sketch plane x_axis must be non-zero");
    x_axis = x_axis / x_length;
    y_axis = y_axis - x_axis * y_axis.dot(x_axis);
    const double y_length = y_axis.norm();
    if (y_length <= 1.0e-15)
      throw ValueError("Sketch plane x_axis and y_axis must not be parallel");
    y_axis = y_axis / y_length;
    Vec3 normal = x_axis.cross(y_axis);
    normal = normal / normal.norm();
    return {origin, x_axis, y_axis, normal};
  }
  throw ValueError("Sketch plane must be 'XY', 'XZ', 'YZ', or a plane mapping");
}

Vec3 Sketch::point3(const SketchPoint2& point) const {
  const SketchPlaneFrame frame = plane_frame();
  return frame.origin + frame.x_axis * point.first + frame.y_axis * point.second;
}

Vec3 Sketch::plane_normal() const {
  return plane_frame().normal;
}

// ---- legacy curve container -------------------------------------------------
Sketch& Sketch::add_curve(const Shape& curve) {
  if (curve.kind() != Kind::Edge && curve.kind() != Kind::Wire) {
    throw ValueError("Sketch only supports Edge or Wire curve inputs");
  }
  curves_.push_back(curve);
  return *this;
}

std::vector<Wire> Sketch::closed_wires() const {
  std::vector<Wire> out;
  for (const Shape& curve : curves_) {
    if (curve.kind() != Kind::Wire)
      continue;
    Wire wire(curve);
    if (wire.is_closed())
      out.push_back(std::move(wire));
  }
  return out;
}

}  // namespace scad
