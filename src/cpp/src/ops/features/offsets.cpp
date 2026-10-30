// offset_rsolid, draft_rsolid (operators/features.py).
#include <algorithm>
#include <BRepAdaptor_Surface.hxx>
#include <BRepOffsetAPI_DraftAngle.hxx>
#include <BRepOffsetAPI_MakeThickSolid.hxx>
#include <GeomAbs_JoinType.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopTools_ListOfShape.hxx>
#include <gp_Pln.hxx>

#include <cmath>
#include <set>

#include "internal.hpp"
#include "scad/core/tolerance.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/ops/features/blends.hpp"

namespace scad {

Solid offset_rsolid(const Solid& solid, const Scalar& amount, const FaceSelection& openings,
                    const OffsetOptions& options) {
  const double distance = evaluate_finite(amount);
  if (!std::isfinite(distance) || distance == 0)
    throw ValueError("amount must be finite and nonzero");
  if (!std::isfinite(options.tolerance) || options.tolerance <= 0)
    throw ValueError("tolerance must be finite and positive");
  if (options.kind != "ARC" && options.kind != "INTERSECTION")
    throw ValueError("kind must be ARC or INTERSECTION");
  const GeomAbs_JoinType join = options.kind == "ARC" ? GeomAbs_Arc : GeomAbs_Intersection;
  const std::vector<Face> faces = openings.resolve(solid);

  const TopoDS_Shape built = occt_guard([&]() -> TopoDS_Shape {
    TopTools_ListOfShape open;
    for (const Face& face : faces)
      open.Append(face.wrapped());
    BRepOffsetAPI_MakeThickSolid builder;
    builder.MakeThickSolidByJoin(solid.wrapped(), open, distance, options.tolerance, BRepOffset_Skin,
                                 /*Intersection=*/true, /*SelfInter=*/false, join, /*RemoveIntEdges=*/true);
    builder.Build();
    if (!builder.IsDone())
      throw ValueError("kernel could not offset the solid");
    return builder.Shape();
  });

  FeatureRecord rec("make_offset_rsolid");
  rec.scalar("amount", amount);
  rec.param("tolerance", Value(options.tolerance))
      .param("kind", Value(options.kind))
      .param("removed_face_count", Value(static_cast<std::int64_t>(faces.size())));
  if (rec.recording()) {
    const PickParams picks = capture_picks(solid, faces, solid.faces(), /*refs_first=*/false);
    picks.apply_refs(rec, "selected_faces");
    picks.apply_ids(rec, "selected_face_node_ids", {});
  }
  rec.input(solid, "body").inputs(faces, "face");
  return finish_solid(solid, built, std::move(rec).take());
}

Solid draft_rsolid(const Solid& solid, const FaceSelection& faces_to_draft, const Scalar& angle,
                   const Scalar3& plane_origin, const Scalar3& plane_normal) {
  const double degrees = evaluate_finite(angle);
  if (!std::isfinite(degrees) || std::abs(degrees) >= 90) {
    throw ValueError("angle must be finite and strictly between -90 and 90 degrees");
  }
  const Vec3 origin = finite_vector(plane_origin, "plane_origin");
  const Vec3 normal = finite_vector(plane_normal, "plane_normal");
  const Vec3 global_origin = features_detail::place_point(origin);
  Vec3 global_normal = features_detail::place_vector(normal);
  const double magnitude = global_normal.norm();
  if (magnitude <= tol::kUndefinedNormal)
    throw ValueError("plane_normal must be nonzero");
  global_normal = global_normal / magnitude;

  const std::vector<Face> resolved = faces_to_draft.resolve(solid);
  if (resolved.empty())
    throw ValueError("draft requires at least one selected face");
  const std::vector<Face> own_faces = solid.faces();
  std::vector<Face> selected;  // repeated references dropped, order kept
  std::set<std::string> seen;
  for (const Face& face : resolved) {
    const bool belongs = std::any_of(own_faces.begin(), own_faces.end(),
                                     [&](const Face& f) { return f.wrapped().IsSame(face.wrapped()); });
    if (!belongs)
      throw ValueError("selected draft faces must belong to the input solid");
    const GeomAbs_SurfaceType type =
        occt_guard([&] { return BRepAdaptor_Surface(TopoDS::Face(face.wrapped())).GetType(); });
    if (type != GeomAbs_Plane && type != GeomAbs_Cylinder && type != GeomAbs_Cone) {
      throw ValueError("draft supports only planar, cylindrical, and conical faces");
    }
    if (seen.insert(face.topo_id()).second)
      selected.push_back(face);
  }

  const TopoDS_Shape built = degrees == 0 ? solid.wrapped() : occt_guard([&]() -> TopoDS_Shape {
    const gp_Dir direction = kernel::to_dir(global_normal, "plane_normal");
    const gp_Pln plane(kernel::to_pnt(global_origin), direction);
    BRepOffsetAPI_DraftAngle builder(solid.wrapped());
    for (const Face& face : selected) {
      builder.Add(TopoDS::Face(face.wrapped()), direction, degrees * kPi / 180.0, plane, true);
      if (!builder.AddDone())
        throw ValueError("kernel could not add the requested draft angle to a selected face");
    }
    builder.Build();
    if (!builder.IsDone())
      throw ValueError("kernel could not build the drafted solid");
    return builder.Shape();
  });

  FeatureRecord rec("make_draft_rsolid");
  rec.scalar("angle", angle);
  rec.point("plane_origin", plane_origin);
  rec.point("plane_normal", plane_normal);
  rec.param("selected_face_count", Value(static_cast<std::int64_t>(selected.size())));
  if (rec.recording()) {
    const PickParams picks = capture_picks(solid, selected, solid.faces(), /*refs_first=*/false);
    picks.apply_refs(rec, "selected_faces");
    picks.apply_ids(rec, "selected_face_node_ids", {});
  }
  rec.input(solid, "body").inputs(selected, "face");
  return finish_solid(solid, built, std::move(rec).take());
}

}  // namespace scad
