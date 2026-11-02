// project_rsketch: reference geometry from another sketch, or from the edges of shapes, in the plane of a sketch.
//
// Every point goes through the plane frames: u = (P - origin) . x_axis, v = (P - origin) . y_axis of the target sketch,
// P being the world position of a point of the source (a source sketch is solved first and placed through its own
// frame).  A projected entity is a copy that is construction by default and fixed at its projected coordinates, so the
// sketch can be constrained to it.  Nothing is guessed: an entity that cannot be projected exactly is refused by name.
#include <BRepAdaptor_Curve.hxx>
#include <BRep_Tool.hxx>
#include <GeomAbs_CurveType.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Circ.hxx>

#include <algorithm>
#include <cmath>
#include <map>
#include <set>

#include "scad/core/error.hpp"
#include "scad/core/vec.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/sketch/operators.hpp"
#include "scad/topo/value_lineage.hpp"

namespace scad {

namespace {

constexpr double kTol = 1e-6;
constexpr double kTwoPi = 2.0 * kPi;
constexpr double kParallel = 1e-7;  // |n1 . n2| within this of 1 (or 0): the planes are parallel (perpendicular)
using Pt = SketchPoint2;

double wrap(double angle) {
  angle = std::fmod(angle, kTwoPi);
  if (angle < 0.0)
    angle += kTwoPi;
  return angle >= kTwoPi ? 0.0 : angle;
}

// A projected thing, in the coordinates of the target sketch.
struct Prim {
  enum class Kind { Point, Line, Circle, Arc, Ellipse } kind = Kind::Point;
  std::string entity;  // what it came from: a source entity id, or the topo id of an edge
  Pt a{0, 0};          // point | line start | arc start | ellipse major point
  Pt b{0, 0};          // line end | arc end | ellipse minor point
  Pt c{0, 0};          // circle / arc / ellipse centre
  double radius = 0.0;
};

// The frame of the sketch plane, and the projection onto it.
struct Frame {
  Vec3 origin, x, y, normal;
  Pt uv(const Vec3& p) const { return {(p - origin).dot(x), (p - origin).dot(y)}; }
  Pt direction_uv(const Vec3& d) const { return {d.dot(x), d.dot(y)}; }
};

Frame frame_of(const Sketch& sketch) {
  const SketchPlaneFrame f = sketch.plane_frame();
  return {f.origin, f.x_axis, f.y_axis, f.normal};
}

// A circle, or an arc running counter-clockwise about `normal` from `start` to `end`, in space.
struct Round {
  Vec3 center, normal, e1, e2;
  double radius = 0.0;
  bool full = true;
  Vec3 start, end;
};

Prim point_prim(const std::string& entity, Pt p) {
  Prim out;
  out.kind = Prim::Kind::Point;
  out.entity = entity;
  out.a = p;
  return out;
}

Prim line_prim(const std::string& entity, Pt a, Pt b) {
  if (std::hypot(a.first - b.first, a.second - b.second) < kTol)
    return point_prim(entity, {0.5 * (a.first + b.first), 0.5 * (a.second + b.second)});  // seen end on
  Prim out;
  out.kind = Prim::Kind::Line;
  out.entity = entity;
  out.a = a;
  out.b = b;
  return out;
}

// The projection of a circle / arc onto the target plane.
Prim project_round(const Frame& target, const Round& round, const std::string& entity, const char* what) {
  const double dot = round.normal.dot(target.normal);
  const Pt center = target.uv(round.center);
  if (std::abs(std::abs(dot) - 1.0) < kParallel) {
    Prim out;
    out.entity = entity;
    out.c = center;
    out.radius = round.radius;
    if (round.full) {
      out.kind = Prim::Kind::Circle;
      return out;
    }
    out.kind = Prim::Kind::Arc;
    const Pt s = target.uv(round.start);
    const Pt e = target.uv(round.end);
    // counter-clockwise about the source normal is clockwise about the target's when they are opposite
    out.a = dot > 0.0 ? s : e;
    out.b = dot > 0.0 ? e : s;
    return out;
  }
  if (std::abs(dot) < kParallel) {
    // seen edge on: a segment along the line where the two planes meet
    const Vec3 along = round.normal.cross(target.normal).normalized();
    if (round.full)
      return line_prim(entity, target.uv(round.center - along * round.radius),
                       target.uv(round.center + along * round.radius));
    const auto angle_of = [&](const Vec3& p) {
      return std::atan2((p - round.center).dot(round.e2), (p - round.center).dot(round.e1));
    };
    const double start = angle_of(round.start);
    const double sweep = wrap(angle_of(round.end) - start);
    const double phi = std::atan2(along.dot(round.e2), along.dot(round.e1));
    std::vector<double> reach{(round.start - round.center).dot(along), (round.end - round.center).dot(along)};
    for (const double extreme : {phi, phi + kPi})
      if (wrap(extreme - start) <= sweep)
        reach.push_back(round.radius * std::cos(extreme - phi));
    const auto [low, high] = std::minmax_element(reach.begin(), reach.end());
    return line_prim(entity, target.uv(round.center + along * *low), target.uv(round.center + along * *high));
  }
  if (!round.full)
    throw ValueError(std::string(what) + " '" + entity +
                     "' is an arc in a plane oblique to the sketch: it would project to an elliptical arc, which a "
                     "sketch cannot hold (project the full circle, or a view of the arc in a parallel plane)");
  // an oblique circle is an ellipse: its axes are the singular vectors of the projected in-plane frame
  const Pt v1 = target.direction_uv(round.e1);
  const Pt v2 = target.direction_uv(round.e2);
  const double p = v1.first * v1.first + v2.first * v2.first;
  const double s = v1.second * v1.second + v2.second * v2.second;
  const double q = v1.first * v1.second + v2.first * v2.second;
  const double mean = 0.5 * (p + s);
  const double spread = std::sqrt(0.25 * (p - s) * (p - s) + q * q);
  const double alpha = 0.5 * std::atan2(2.0 * q, p - s);
  Prim out;
  out.kind = Prim::Kind::Ellipse;
  out.entity = entity;
  out.c = center;
  const double major = round.radius * std::sqrt(mean + spread);
  const double minor = round.radius * std::sqrt(std::max(mean - spread, 0.0));
  out.a = {center.first + major * std::cos(alpha), center.second + major * std::sin(alpha)};
  out.b = {center.first - minor * std::sin(alpha), center.second + minor * std::cos(alpha)};
  return out;
}

bool uses_point(const SketchEntity& entity, const std::string& point_id) {
  for (const char* role : {"start", "end", "center", "major", "minor"}) {
    const Value* value = entity.data.find(role);
    if (value != nullptr && value->is_string() && value->as_string() == point_id)
      return true;
  }
  if (entity.kind == kBSplineKind) {
    for (const SketchPole& pole : entity.bspline().poles)
      if (pole.is_point() && pole.point_id == point_id)
        return true;
  }
  return false;
}

bool projectable_kind(const std::string& kind) {
  return kind == kPointKind || kind == kLineKind || kind == kCircleKind || kind == kArcKind;
}

const char* curve_name(GeomAbs_CurveType type) {
  switch (type) {
    case GeomAbs_Line:
      return "line";
    case GeomAbs_Circle:
      return "circle";
    case GeomAbs_Ellipse:
      return "ellipse";
    case GeomAbs_Hyperbola:
      return "hyperbola";
    case GeomAbs_Parabola:
      return "parabola";
    case GeomAbs_BezierCurve:
      return "Bezier";
    case GeomAbs_BSplineCurve:
      return "B-spline";
    case GeomAbs_OffsetCurve:
      return "offset";
    default:
      return "other";
  }
}

Vec3 vec_of(const gp_Pnt& p) {
  return {p.X(), p.Y(), p.Z()};
}
Vec3 vec_of(const gp_Dir& d) {
  return {d.X(), d.Y(), d.Z()};
}

}  // namespace

class SketchProjection {
 public:
  explicit SketchProjection(const Sketch& target) : work_(target.clone(false)), frame_(frame_of(work_)) {
    for (const auto& [id, entity] : work_.entities_)
      taken_.insert(id);
    for (const SketchConstraint& constraint : work_.constraints_)
      taken_constraints_.insert(constraint.id);
    if (const Value* list = work_.metadata().find("projections"); list != nullptr && list->is_array())
      projections_ = *list;
  }

  Sketch from_sketch(const Sketch& source, const std::optional<std::vector<std::string>>& entities, bool construction) {
    if (source.sketch_id() == work_.sketch_id())
      throw ValueError("'" + source.sketch_id() + "' cannot be projected onto itself");
    Sketch solved_copy = source.clone(false);
    SketchSolveRequest request;  // strict: a conflicting source has no geometry to project
    const SketchSolveResult solved = solved_copy.solve(request);
    const Frame from = frame_of(solved_copy);
    const auto world = [&](const std::string& id) { return solved_copy.point3(solved.solved_points.at(id)); };
    const auto point_of = [&](const SketchEntity& entity, const char* role) { return world(entity.point_id(role)); };

    std::vector<std::string> ids;
    if (entities) {
      std::set<std::string> seen;
      for (const std::string& id : *entities) {
        const SketchEntity* entity = source.entities().find(id);
        if (entity == nullptr)
          throw ValueError("entities names '" + id + "', which is not an entity of the source sketch '" +
                           source.sketch_id() + "'");
        if (!projectable_kind(entity->kind))
          throw ValueError("entities names '" + id + "', a " + entity->kind +
                           ": only points, lines, circles and arcs can be projected");
        if (seen.insert(id).second)
          ids.push_back(id);
      }
      if (ids.empty())
        throw ValueError("entities is empty: name the source entities to project, or leave it out for all of them");
    } else {
      for (const auto& [id, entity] : source.entities()) {
        if (entity.kind == kPointKind) {
          const bool owned = std::any_of(source.entities().begin(), source.entities().end(),
                                         [&](const auto& other) { return uses_point(other.second, id); });
          if (!owned)
            ids.push_back(id);
        } else if (projectable_kind(entity.kind)) {
          ids.push_back(id);
        } else {
          notes_.push_back("skipped " + id + " (" + entity.kind + "): only points, lines, circles and arcs project");
        }
      }
      if (ids.empty())
        throw ValueError("the source sketch '" + source.sketch_id() + "' has nothing to project");
    }

    std::vector<Prim> prims;
    for (const std::string& id : ids) {
      const SketchEntity& entity = source.entities().at(id);
      if (entity.kind == kPointKind) {
        prims.push_back(point_prim(id, frame_.uv(world(id))));
      } else if (entity.kind == kLineKind) {
        prims.push_back(line_prim(id, frame_.uv(point_of(entity, "start")), frame_.uv(point_of(entity, "end"))));
      } else {
        Round round;
        round.center = point_of(entity, "center");
        round.normal = from.normal;
        round.e1 = from.x;
        round.e2 = from.y;
        if (entity.kind == kCircleKind) {
          round.radius = solved.solved_scalars.at("circle:" + id + ":radius");
        } else {
          round.full = false;
          round.start = point_of(entity, "start");
          round.end = point_of(entity, "end");
          round.radius = (round.start - round.center).norm();
        }
        prims.push_back(project_round(frame_, round, id, "arc"));
      }
    }
    return emit(prims, source.sketch_id(), construction, "sketch");
  }

  Sketch from_shapes(const std::vector<Shape>& shapes, bool construction) {
    if (shapes.empty())
      throw ValueError("source is empty: pass a shape, or a list of edges, to project");
    std::vector<Prim> prims;
    for (const Shape& shape : shapes) {
      if (shape.kind() == Kind::Vertex) {
        const gp_Pnt p = occt_guard([&] { return BRep_Tool::Pnt(TopoDS::Vertex(shape.wrapped())); });
        prims.push_back(point_prim(shape.topo_id(), frame_.uv(vec_of(p))));
        continue;
      }
      occt_guard([&] {
        TopTools_IndexedMapOfShape edges;
        TopExp::MapShapes(shape.wrapped(), TopAbs_EDGE, edges);
        if (edges.Extent() == 0)
          throw ValueError("a " + std::string(kind_name(shape.kind())) + " source has no edges to project");
        for (int i = 1; i <= edges.Extent(); ++i)
          project_edge(shape.sub(edges(i)), prims);
      });
    }
    return emit(prims, "shape", construction, "shapes");
  }

 private:
  void project_edge(const Shape& edge_shape, std::vector<Prim>& out) {
    const TopoDS_Edge edge = TopoDS::Edge(edge_shape.wrapped());
    const std::string id = edge_shape.topo_id();
    if (BRep_Tool::Degenerated(edge)) {
      notes_.push_back("skipped " + id + ": a degenerate edge has no extent");
      return;
    }
    BRepAdaptor_Curve curve(edge);
    const double first = curve.FirstParameter();
    const double last = curve.LastParameter();
    if (curve.GetType() == GeomAbs_Line) {
      out.push_back(line_prim(id, frame_.uv(vec_of(curve.Value(first))), frame_.uv(vec_of(curve.Value(last)))));
    } else if (curve.GetType() == GeomAbs_Circle) {
      const gp_Circ circle = curve.Circle();
      Round round;
      round.center = vec_of(circle.Location());
      round.normal = vec_of(circle.Axis().Direction());
      round.e1 = vec_of(circle.XAxis().Direction());
      round.e2 = vec_of(circle.YAxis().Direction());
      round.radius = circle.Radius();
      round.full = std::abs((last - first) - kTwoPi) < 1e-9;
      if (!round.full) {
        round.start = vec_of(curve.Value(first));
        round.end = vec_of(curve.Value(last));
      }
      out.push_back(project_round(frame_, round, id, "edge"));
    } else {
      throw ValueError("edge '" + id + "' is a " + curve_name(curve.GetType()) +
                       " curve: only lines and circles / arcs project (pass the line and circle edges you need, for "
                       "example from a ql selection)");
    }
  }

  std::string free_id(const std::string& prefix) {
    while (true) {
      std::string candidate = prefix + std::to_string(++counter_);
      if (taken_.insert(candidate).second)
        return candidate;
    }
  }

  std::string free_constraint(const std::string& kind) {
    for (int n = 0;; ++n) {
      std::string candidate = "c_" + kind + "_" + std::to_string(n);
      if (taken_constraints_.insert(candidate).second)
        return candidate;
    }
  }

  SketchRef ref(const std::string& id, std::string_view kind) const {
    return SketchRef{work_.sketch_id(), id, std::string(kind), "geometry"};
  }

  // A point of an earlier projection at (x, y), else a new fixed-by-its-curve point.
  std::string point_at(const Pt& at, const std::string& prefix, bool construction, bool* created = nullptr) {
    for (const auto& [id, entity] : work_.entities_)
      if (entity.kind == kPointKind && id.rfind("proj_", 0) == 0 &&
          std::hypot(entity.number("x") - at.first, entity.number("y") - at.second) < kTol)
        return id;
    const std::string id = free_id(prefix);
    work_.add_point(id, Scalar(at.first), Scalar(at.second));
    work_.entities_.at(id).construction = construction;
    if (created != nullptr)
      *created = true;
    return id;
  }

  // The projected entity that already is this one (same kind, same points), or "".
  std::string existing(const std::string& kind, const std::vector<std::pair<std::string, std::string>>& roles,
                       double radius) const {
    for (const auto& [id, entity] : work_.entities_) {
      if (id.rfind("proj_", 0) != 0 || entity.kind != kind)
        continue;
      bool same = true;
      for (const auto& [role, point] : roles)
        same = same && entity.point_id(role) == point;
      if (kind == kCircleKind)
        same = same && std::abs(entity.number("radius") - radius) < kTol;
      if (same)
        return id;
    }
    return {};
  }

  Sketch emit(const std::vector<Prim>& prims, const std::string& label, bool construction, const char* source_kind) {
    const std::string prefix = "proj_" + label + "_";
    std::size_t projected = 0;
    for (const Prim& prim : prims) {
      std::string result;
      bool fresh = false;
      switch (prim.kind) {
        case Prim::Kind::Point: {
          result = point_at(prim.a, prefix, construction, &fresh);
          if (fresh)
            fix(ref(result, kPointKind));
          break;
        }
        case Prim::Kind::Line: {
          const std::string s = point_at(prim.a, prefix, construction);
          const std::string e = point_at(prim.b, prefix, construction);
          result = existing(std::string(kLineKind), {{"start", s}, {"end", e}}, 0.0);
          if (result.empty())
            result = existing(std::string(kLineKind), {{"start", e}, {"end", s}}, 0.0);
          if (result.empty()) {
            result = free_id(prefix);
            work_.add_line(result, ref(s, kPointKind), ref(e, kPointKind), construction);
            fix(ref(result, kLineKind));
            fresh = true;
          }
          break;
        }
        case Prim::Kind::Circle: {
          const std::string c = point_at(prim.c, prefix, construction);
          result = existing(std::string(kCircleKind), {{"center", c}}, prim.radius);
          if (result.empty()) {
            result = free_id(prefix);
            work_.add_circle(result, ref(c, kPointKind), Scalar(prim.radius), construction);
            fix(ref(result, kCircleKind));
            fresh = true;
          }
          break;
        }
        case Prim::Kind::Arc: {
          const std::string s = point_at(prim.a, prefix, construction);
          const std::string e = point_at(prim.b, prefix, construction);
          const std::string c = point_at(prim.c, prefix, construction);
          result = existing(std::string(kArcKind), {{"start", s}, {"end", e}, {"center", c}}, 0.0);
          if (result.empty()) {
            result = free_id(prefix);
            work_.add_arc(result, ref(s, kPointKind), ref(e, kPointKind), ref(c, kPointKind), construction);
            fix(ref(result, kArcKind));
            fresh = true;
          }
          break;
        }
        case Prim::Kind::Ellipse: {
          const std::string c = point_at(prim.c, prefix, construction);
          const std::string major = point_at(prim.a, prefix, construction);
          const std::string minor = point_at(prim.b, prefix, construction);
          result = existing(std::string(kEllipseKind), {{"center", c}, {"major", major}, {"minor", minor}}, 0.0);
          if (result.empty()) {
            result = free_id(prefix);
            work_.add_ellipse(result, ref(c, kPointKind), ref(major, kPointKind), ref(minor, kPointKind), construction);
            fix(ref(result, kEllipseKind));
            fresh = true;
          }
          break;
        }
      }
      Value entry = Value::object();
      entry.set("source", label);
      entry.set("entity", prim.entity);
      entry.set("projected", result);
      bool listed = false;
      for (const Value& old : projections_.as_array())
        listed = listed || old == entry;
      if (!listed)
        projections_.as_array().push_back(entry);
      if (fresh)
        ++projected;
      else
        notes_.push_back(prim.entity + " was already projected as " + result);
    }
    notes_.insert(notes_.begin(), std::to_string(projected) + " of " + std::to_string(prims.size()) +
                                      " projected entities are new (" + source_kind + " source)");
    work_.metadata().set("projections", projections_);
    Value notes = Value(Value::Array{});
    for (const std::string& note : notes_)
      notes.as_array().emplace_back(note);
    Value edit = Value::object();
    edit.set("operation", "project_rsketch");
    edit.set("notes", notes);
    work_.metadata().set("last_edit", edit);
    work_.clear_solve_result();
    return std::move(work_);
  }

  void fix(const SketchRef& target) { work_.add_constraint("fix", {target}, std::nullopt, free_constraint("fix")); }

  Sketch work_;
  Frame frame_;
  std::set<std::string> taken_;
  std::set<std::string> taken_constraints_;
  std::vector<std::string> notes_;
  Value projections_ = Value(Value::Array{});
  int counter_ = 0;
};

// ---- the operators
// ------------------------------------------------------------------------------------------------------

namespace {

const ErrorSpec& project_spec() {
  static const ErrorSpec kSpec{
      "project_rsketch",
      "Failed to project geometry into the sketch.",
      {"The source is neither a Sketch nor a shape (or list of edges).",
       "entities names something that is not a point, line, circle or arc of the source sketch.",
       "An arc lies in a plane oblique to the sketch, or an edge is not a line or circle / arc.",
       "The source sketch has conflicting constraints, so it has no geometry to project.",
       "The source is the sketch itself."},
      {"Pass another Sketch, or a Solid / Face / Wire / Edge or the list a ql selection resolves to.",
       "Name the entities with entities=[...] (a source sketch only), or pick the edges you need.",
       "Inspect the source with inspect_sketch_rsketchresult(..., strict=False) and fix its constraints first."}};
  return kSpec;
}

void record_projection(const Sketch& target, const Sketch* source, const std::vector<Shape>& shapes, Value params,
                       const Sketch& updated) {
  OpRecord record;
  record.op = "project_rsketch";
  record.params = std::move(params);
  for (const Shape& shape : shapes)
    record.inputs.push_back(OpInput{shape, "source"});
  std::vector<ValueLineage> inputs;
  if (auto lineage = value_lineage_of(target))
    inputs.push_back(std::move(*lineage));
  if (source != nullptr)
    if (auto lineage = value_lineage_of(*source))
      inputs.push_back(std::move(*lineage));
  if (const auto lineage = finalize_runtime_object(std::move(record), "Sketch", inputs))
    attach_value_lineage(updated, *lineage, "project_rsketch");
}

}  // namespace

void project_rsketch_refuse(const std::string& reason) {
  raise_harness_error(project_spec(), reason);
}

Sketch project_rsketch(const Sketch& sketch, const Sketch& source,
                       const std::optional<std::vector<std::string>>& entities, bool construction) {
  return guarded(project_spec(), [&] {
    Sketch updated = SketchProjection(sketch).from_sketch(source, entities, construction);
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("source_kind", "sketch");
    params.set("source", source.sketch_id());
    if (entities) {
      Value::Array ids;
      for (const std::string& id : *entities)
        ids.emplace_back(id);
      params.set("entities", Value(std::move(ids)));
    } else {
      params.set("entities", Value());
    }
    params.set("construction", construction);
    record_projection(sketch, &source, {}, std::move(params), updated);
    return updated;
  });
}

Sketch project_rsketch(const Sketch& sketch, const std::vector<Shape>& source, bool construction) {
  return guarded(project_spec(), [&] {
    Sketch updated = SketchProjection(sketch).from_shapes(source, construction);
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("source_kind", "shapes");
    params.set("source", static_cast<std::int64_t>(source.size()));
    params.set("entities", Value());
    params.set("construction", construction);
    record_projection(sketch, nullptr, source, std::move(params), updated);
    return updated;
  });
}

}  // namespace scad
