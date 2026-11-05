// offset_rsolid, draft_rsolid, inset_face_rsolid (operators/features.py).
#include <algorithm>
#include <BRepAdaptor_Surface.hxx>
#include <BRepFeat_SplitShape.hxx>
#include <BRepOffsetAPI_MakeOffset.hxx>
#include <BRepOffsetAPI_DraftAngle.hxx>
#include <BRepOffsetAPI_MakeThickSolid.hxx>
#include <BRepTools_History.hxx>
#include <GeomAbs_JoinType.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Pln.hxx>

#include <cmath>
#include <set>

#include "internal.hpp"
#include "scad/core/tolerance.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ops/features/blends.hpp"
#include "scad/semantic/tracking.hpp"

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

  BRepTools_History history;
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
    TopTools_ListOfShape input;
    input.Append(solid.wrapped());
    history = BRepTools_History(input, builder);
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
  // An offset face is the input face moved: it keeps the identity (generated_faces_continue).
  TopoDelta delta = modification_delta(history, solid.wrapped(), built, "fragment", /*generated_faces_continue=*/true);
  return finish_solid(solid, built, std::move(rec).take(), std::move(delta));
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

  BRepTools_History history;  // empty for a zero angle: every face is preserved
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
    TopTools_ListOfShape input;
    input.Append(solid.wrapped());
    history = BRepTools_History(input, builder);
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
  // OCCT reports a drafted face as generated (the tilted face replaces it): it is the same face, so it continues.
  TopoDelta delta = modification_delta(history, solid.wrapped(), built, "fragment", /*generated_faces_continue=*/true);
  return finish_solid(solid, built, std::move(rec).take(), std::move(delta));
}

namespace {

// A kernel-proven role of one face of the result (as the surface operations record theirs).
TopoRoleEntry face_role(const TopoDS_Shape& face, const char* role, const char* method) {
  TopoRoleEntry entry;
  entry.ref.kind = Kind::Face;
  entry.ref.topo_id = kernel_topo_id(face);
  entry.role = role;
  entry.metadata = Value::object();
  entry.metadata.set("coverage", "complete");
  entry.metadata.set("status", "proven");
  entry.metadata.set("evidence_kind", "kernel_operation_role");
  entry.metadata.set("evidence_method", method);
  return entry;
}

// The role written on the face itself as well (its `track` metadata): what the output-role selectors and the replay
// check read.
void stamp_face_role(Solid& result, const TopoDS_Shape& piece, const char* role) {
  for (Face face : result.faces()) {
    if (!face.wrapped().IsSame(piece))
      continue;
    Value track = face.get_metadata("track", Value::object());
    if (!track.is_object())
      track = Value::object();
    Value roles = Value::array();
    roles.push_back(std::string(role));
    track.set("op", "make_inset_face_rsolid");
    track.set("topo_id", kernel_topo_id(piece));
    track.set("kind", "FACE");
    track.set("coverage", "complete");
    track.set("status", "proven");
    track.set("result_roles", std::move(roles));
    face.set_metadata("track", std::move(track));
  }
}

}  // namespace

Solid inset_face_rsolid(const Solid& solid, const FaceSelection& face, const Scalar& distance) {
  const double inset = evaluate_finite(distance);
  if (!std::isfinite(inset) || inset <= 0)
    throw ValueError("distance must be finite and positive: how far inside the face the loop runs");
  const std::vector<Face> resolved = face.resolve(solid);
  if (resolved.size() != 1)
    throw ValueError("inset_face takes exactly one face, got " + std::to_string(resolved.size()));
  const Face target = resolved.front();
  const std::vector<Face> own_faces = solid.faces();
  if (std::none_of(own_faces.begin(), own_faces.end(), [&](const Face& f) { return f.wrapped().IsSame(target.wrapped()); }))
    throw ValueError("the face must belong to the input solid");
  const TopoDS_Face source = TopoDS::Face(target.wrapped());
  if (occt_guard([&] { return BRepAdaptor_Surface(source).GetType(); }) != GeomAbs_Plane)
    throw ValueError("inset_face needs a planar face");

  BRepTools_History history;
  std::vector<TopoDS_Shape> inner, ring;
  const TopoDS_Shape built = occt_guard([&]() -> TopoDS_Shape {
    // every loop of the face (its outline and its holes) moved inside it by `inset`, in its plane
    BRepOffsetAPI_MakeOffset offsetter(source, GeomAbs_Intersection);
    offsetter.Perform(-inset);
    if (!offsetter.IsDone())
      throw ValueError("the inset does not fit in the face: the loop collapses at this distance");
    const std::vector<TopoDS_Wire> loops = kernel::wires_of(offsetter.Shape());
    if (loops.empty())
      throw ValueError("the inset does not fit in the face: nothing is left inside it at this distance");
    BRepFeat_SplitShape splitter(solid.wrapped());
    for (const TopoDS_Wire& loop : loops)
      splitter.Add(loop, source);
    splitter.Build();
    if (!splitter.IsDone())
      throw ValueError("kernel could not imprint the inset loop on the face");
    TopTools_ListOfShape input;
    input.Append(solid.wrapped());
    history = BRepTools_History(input, splitter);
    // the piece bounded by the offset loops alone is the inner face; a piece that keeps an edge of the face's own
    // outline is the ring
    TopTools_IndexedMapOfShape outline;
    TopExp::MapShapes(source, TopAbs_EDGE, outline);
    TopTools_IndexedMapOfShape kept;
    for (int i = 1; i <= outline.Extent(); ++i) {
      const TopTools_ListOfShape& images = history.Modified(outline(i));
      if (images.IsEmpty() && !history.IsRemoved(outline(i)))
        kept.Add(outline(i));
      for (TopTools_ListIteratorOfListOfShape it(images); it.More(); it.Next())
        kept.Add(it.Value());
    }
    for (TopTools_ListIteratorOfListOfShape it(history.Modified(source)); it.More(); it.Next()) {
      TopTools_IndexedMapOfShape edges;
      TopExp::MapShapes(it.Value(), TopAbs_EDGE, edges);
      bool touches = false;
      for (int i = 1; i <= edges.Extent() && !touches; ++i)
        touches = kept.Contains(edges(i));
      (touches ? ring : inner).push_back(it.Value());
    }
    if (inner.empty() || ring.empty())
      throw ValueError("the inset loop did not split the face");
    return splitter.Shape();
  });

  FeatureRecord rec("make_inset_face_rsolid");
  rec.scalar("distance", distance);
  rec.param("selected_face_count", Value(static_cast<std::int64_t>(1)));
  if (rec.recording()) {
    const PickParams picks = capture_picks(solid, std::vector<Face>{target}, solid.faces(), /*refs_first=*/false);
    picks.apply_refs(rec, "selected_faces");
    picks.apply_ids(rec, "selected_face_node_ids", {});
  }
  rec.input(solid, "body").inputs(std::vector<Face>{target}, "face");
  // the face is split in two pieces (fragments of it); the kernel says which is which
  TopoDelta delta = modification_delta(history, solid.wrapped(), built, "fragment");
  for (const TopoDS_Shape& piece : inner)
    delta.roles.push_back(face_role(piece, "inset.inner", "OffsetLoopInterior"));
  for (const TopoDS_Shape& piece : ring)
    delta.roles.push_back(face_role(piece, "inset.ring", "OffsetLoopExterior"));
  Solid result = finish_solid(solid, built, std::move(rec).take(), std::move(delta));
  for (const TopoDS_Shape& piece : inner)
    stamp_face_role(result, piece, "inset.inner");
  for (const TopoDS_Shape& piece : ring)
    stamp_face_role(result, piece, "inset.ring");
  return result;
}

}  // namespace scad
