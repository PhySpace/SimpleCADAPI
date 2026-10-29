// extrude_until_rsolid (operators/features.py): a prism, cut to length by a surface of the target.
//
// The prism is made long enough to cross the target.  Its intersection with the target gives, by
// the kernel's history, the target's boundary faces that actually touch it; those are sewn into
// contact surfaces, one is chosen by the termination mode, and the prism is split on it and the
// part on the requested side kept.
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRepGProp_Face.hxx>
#include <BRepPrimAPI_MakeHalfSpace.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepTools.hxx>
#include <BRepTools_History.hxx>
#include <BRep_Builder.hxx>
#include <GProp_GProps.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Iterator.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

#include <algorithm>
#include <cctype>
#include <cmath>

#include "internal.hpp"
#include "scad/core/tolerance.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ops/features/extrusion.hpp"

namespace scad {

namespace {

TopoDS_Compound compound_of(const std::vector<TopoDS_Shape>& shapes) {
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);
  for (const TopoDS_Shape& shape : shapes)
    builder.Add(compound, shape);
  return compound;
}

// Every non-compound shape below `shape`.
void top_level(const TopoDS_Shape& shape, std::vector<TopoDS_Shape>& out) {
  if (shape.ShapeType() != TopAbs_COMPOUND) {
    out.push_back(shape);
    return;
  }
  for (TopoDS_Iterator it(shape); it.More(); it.Next())
    top_level(it.Value(), out);
}

// Side walls parallel to the extrusion (including coincident ones) are not termination surfaces.
bool crosses_direction(const TopoDS_Face& face, const Vec3& axis) {
  double u0, u1, v0, v1;
  BRepTools::UVBounds(face, u0, u1, v0, v1);
  const BRepGProp_Face properties(face);
  for (const double u : {0.25, 0.5, 0.75}) {
    for (const double v : {0.25, 0.5, 0.75}) {
      gp_Pnt point;
      gp_Vec normal;
      properties.Normal(u0 + u * (u1 - u0), v0 + v * (v1 - v0), point, normal);
      const double length = normal.Magnitude();
      if (length > tol::kUndefinedNormal &&
          std::abs(normal.X() * axis.x + normal.Y() * axis.y + normal.Z() * axis.z) / length > 1e-8)
        return true;
    }
  }
  return false;
}

// The target's boundary faces the prism touches, sewn into surfaces.
// occt_guard: the caller extrude_until_rsolid runs this inside occt_guard.
std::vector<TopoDS_Shape> contact_surfaces(const TopoDS_Shape& target, const TopoDS_Shape& prism, const Vec3& axis) {
  BRepAlgoAPI_Common common(target, prism);
  common.Build();
  const std::vector<TopoDS_Face> intersection_faces =
      common.IsDone() ? kernel::faces_of(common.Shape()) : std::vector<TopoDS_Face>{};
  if (intersection_faces.empty())
    throw ValueError("No intersection: extrusion does not contact target");

  const opencascade::handle<BRepTools_History> history = common.History();
  std::vector<TopoDS_Face> touched;
  for (const TopoDS_Face& face : kernel::faces_of(target)) {
    bool modified = false;
    for (const TopoDS_Shape& item : history->Modified(face)) {
      modified = true;
      if (item.ShapeType() == TopAbs_FACE)
        touched.push_back(TopoDS::Face(item));
    }
    if (modified)
      continue;
    // A target lying wholly inside the prism keeps its unchanged boundary faces as contact surfaces.
    const bool in_intersection = std::any_of(intersection_faces.begin(), intersection_faces.end(),
                                             [&](const TopoDS_Face& f) { return f.IsSame(face); });
    if (!history->IsRemoved(face) && in_intersection)
      touched.push_back(face);
  }
  if (touched.empty())
    throw ValueError("No target boundary surfaces found in extrusion intersection");

  BRepBuilderAPI_Sewing sewing(tol::kSewing);
  for (const TopoDS_Face& face : touched) {
    if (crosses_direction(face, axis))
      sewing.Add(face);
  }
  sewing.Perform();
  std::vector<TopoDS_Shape> surfaces;
  top_level(sewing.SewedShape(), surfaces);
  const bool all_surfaces = std::all_of(surfaces.begin(), surfaces.end(), [](const TopoDS_Shape& part) {
    return part.ShapeType() == TopAbs_FACE || part.ShapeType() == TopAbs_SHELL;
  });
  if (surfaces.empty() || !all_surfaces)
    throw ValueError("Kernel could not sew target contact surfaces");
  return surfaces;
}

// The parts of the prism on one side of `surface`: the near (`keep_top`) or the far one.
// occt_guard: the caller extrude_until_rsolid runs this inside occt_guard.
std::vector<TopoDS_Solid> split_on_surface(const TopoDS_Shape& prism, const TopoDS_Shape& surface, bool keep_top) {
  TopTools_ListOfShape arguments, tools;
  arguments.Append(prism);
  tools.Append(surface);
  BRepAlgoAPI_Splitter splitter;
  splitter.SetArguments(arguments);
  splitter.SetTools(tools);
  splitter.Build();
  if (!splitter.IsDone())
    throw ValueError("Kernel could not split extrusion on target surface");

  const TopoDS_Face reference_face =
      surface.ShapeType() == TopAbs_FACE ? TopoDS::Face(surface) : kernel::faces_of(surface).front();
  double u0, u1, v0, v1;
  BRepTools::UVBounds(reference_face, u0, u1, v0, v1);
  gp_Pnt point;
  gp_Vec normal;
  BRepGProp_Face(reference_face).Normal((u0 + u1) / 2, (v0 + v1) / 2, point, normal);
  if (normal.Magnitude() <= tol::kUndefinedNormal)
    throw ValueError("Undefined normal on termination surface");
  normal.Normalize();
  const gp_Pnt reference = point.Translated(normal);
  const TopoDS_Solid halfspace = surface.ShapeType() == TopAbs_FACE
                                     ? BRepPrimAPI_MakeHalfSpace(TopoDS::Face(surface), reference).Solid()
                                     : BRepPrimAPI_MakeHalfSpace(TopoDS::Shell(surface), reference).Solid();

  std::vector<TopoDS_Solid> candidates;
  for (const TopoDS_Solid& part : kernel::solids_of(splitter.Shape())) {
    BRepAlgoAPI_Common common(part, halfspace);
    common.Build();
    if (!common.IsDone())
      throw ValueError("Kernel could not classify the termination side");
    GProp_GProps properties;
    BRepGProp::LinearProperties(common.Shape(), properties);
    const bool is_top = properties.Mass() >= 1e-6;
    if (is_top == keep_top)
      candidates.push_back(part);
  }
  return candidates;
}

}  // namespace

Solid extrude_until_rsolid(const Face& profile, const std::vector<Solid>& targets, const Scalar3& direction,
                           std::string_view until) {
  if (targets.empty())
    throw ValueError("target must contain at least one Solid");
  std::string mode(until);
  std::transform(mode.begin(), mode.end(), mode.begin(),
                 [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
  if (mode != "NEXT" && mode != "LAST" && mode != "PREVIOUS" && mode != "FIRST") {
    throw ValueError("until must be NEXT, LAST, PREVIOUS, or FIRST");
  }
  const Vec3 values = finite_vector(direction, "direction");
  const Vec3 global_direction = features_detail::place_vector(values);
  const double magnitude = global_direction.norm();
  if (!std::isfinite(magnitude) || magnitude <= tol::kUndefinedNormal)
    throw ValueError("direction must be a finite nonzero vector");
  Vec3 axis = global_direction / magnitude;
  if (mode == "PREVIOUS" || mode == "FIRST")
    axis = -axis;

  const bool nearest = mode == "NEXT" || mode == "PREVIOUS";
  const TopoDS_Shape chosen = occt_guard([&]() -> TopoDS_Shape {
    std::vector<TopoDS_Shape> target_shapes;
    for (const Solid& target : targets)
      target_shapes.push_back(target.wrapped());
    const TopoDS_Compound bound_target = compound_of(target_shapes);
    const kernel::BoundingBox box = kernel::bounding_box(compound_of({profile.wrapped(), bound_target}));
    const double length = std::sqrt(box.xlen() * box.xlen() + box.ylen() * box.ylen() + box.zlen() * box.zlen());
    if (length <= tol::kDegenerateNorm)
      throw ValueError("Degenerate profile and target bounds");

    const TopoDS_Shape prism = BRepPrimAPI_MakePrism(profile.wrapped(), kernel::to_vec(axis * length)).Shape();
    std::vector<TopoDS_Shape> surfaces = contact_surfaces(bound_target, prism, axis);
    std::vector<std::pair<double, TopoDS_Shape>> by_distance;
    for (const TopoDS_Shape& surface : surfaces)
      by_distance.emplace_back(kernel::distance(surface, profile.wrapped()), surface);
    std::stable_sort(by_distance.begin(), by_distance.end(),
                     [](const auto& a, const auto& b) { return a.first < b.first; });
    const TopoDS_Shape& surface = nearest ? by_distance.front().second : by_distance.back().second;

    const std::vector<TopoDS_Solid> candidates = split_on_surface(prism, surface, nearest);
    if (candidates.empty())
      throw ValueError("Extrusion produced no solid on the requested side of the target");
    const Vec3 origin = kernel::center_of_mass(profile.wrapped());
    const TopoDS_Solid* best = nullptr;
    double best_key = 0.0;
    for (const TopoDS_Solid& part : candidates) {
      const double key = (kernel::center_of_mass(part) - origin).dot(axis);
      if (best == nullptr || key < best_key) {
        best = &part;
        best_key = key;
      }
    }
    const double prism_volume = kernel::volume(prism), chosen_volume = kernel::volume(*best);
    if (std::abs(chosen_volume - prism_volume) <= std::max(1e-8, std::abs(prism_volume) * 1e-9)) {
      throw ValueError("Target termination surface does not completely cover the extrusion profile");
    }
    if (chosen_volume <= tol::kEmptyVolume || !BRepCheck_Analyzer(*best).IsValid()) {
      throw ValueError("Target surface did not completely cover a valid limited extrusion");
    }
    return *best;
  });

  FeatureRecord rec("make_extrude_until_rsolid");
  rec.point("direction", direction);
  rec.param("until", Value(mode)).param("target_count", Value(static_cast<std::int64_t>(targets.size())));
  rec.input(profile, "profile").inputs(targets, "target");
  Solid result = finish_solid(profile, chosen, std::move(rec).take());
  result.apply_tag("solid.extrusion", false);
  return result;
}

}  // namespace scad
