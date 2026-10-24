// tracked_fillet / tracked_chamfer / tracked_shell: features that rewrite faces
// of one solid in place.
#include <BRepFilletAPI_LocalOperation.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepOffsetAPI_MakeThickSolid.hxx>
#include <BRepOffset_Mode.hxx>
#include <GeomAbs_JoinType.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>

#include <cmath>
#include <unordered_set>

#include "scad/core/error.hpp"
#include "scad/kernel/cast.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/semantic/tracking.hpp"
#include "tracking_detail.hpp"

namespace scad {

namespace {

// The edges OCCT actually blended: each seed expands to its whole contour
// (a seed on a tangent chain drags the chain along).
std::vector<TopoDS_Shape> actual_contour_edges(BRepFilletAPI_LocalOperation& op, const std::vector<Edge>& seeds) {
  std::vector<TopoDS_Shape> out;
  std::unordered_set<int> seen_contours;
  for (const Edge& seed : seeds) {
    const int contour = op.Contour(TopoDS::Edge(seed.wrapped()));
    if (contour <= 0 || !seen_contours.insert(contour).second) continue;
    for (int i = 1, n = op.NbEdges(contour); i <= n; ++i) out.push_back(op.Edge(contour, i));
  }
  return out;
}

// What a fillet or chamfer did: the solid's faces (origin "body"), then the
// contour edges that were blended (origin "contour_edge", whose generated
// faces are the blend patches).
TrackedResult track_blend(BRepFilletAPI_LocalOperation& op, const Solid& solid, const std::vector<Edge>& seeds,
                          std::string_view patch_role) {
  const Solid result(kernel::as_solid(op.Shape()));
  tracking::DeltaBuilder delta;

  if (tracking::history_wanted()) {
    tracking::BuilderHistory history(op);
    kernel::SubShapeIndex answer(op.Shape());
    kernel::SubShapeIndex solid_only(result.wrapped());
    // The kernel's answer is normally the solid itself; only index twice when it is not.
    kernel::SubShapeIndex& for_edges = op.Shape().IsSame(result.wrapped()) ? answer : solid_only;

    tracking::QuerySpec faces;
    faces.origin_role = "body";
    faces.kind = Kind::Face;
    faces.result = &answer;
    tracking::query_sub_shape_history(history, solid.wrapped(), TopAbs_FACE, faces, delta.witnesses);
    delta.yielding_prefix = delta.witnesses.size();

    tracking::QuerySpec contours;
    contours.origin_role = "contour_edge";
    contours.kind = Kind::Edge;
    contours.result = &for_edges;
    contours.generated_role = patch_role;
    contours.project_source_tags = true;
    tracking::query_list_history(history, actual_contour_edges(op, seeds), contours, delta.witnesses);
    tracking::add_roles_from_history(delta.roles, delta.witnesses, "Generated", delta.yielding_prefix);
  }
  return tracking::to_result(result, std::move(delta));
}

}  // namespace

TrackedResult tracked_fillet(const Solid& solid, const std::vector<Edge>& edges, double radius) {
  return occt_guard([&] {
    BRepFilletAPI_MakeFillet fillet(solid.wrapped());
    for (const Edge& edge : edges) fillet.Add(radius, TopoDS::Edge(edge.wrapped()));
    fillet.Build();
    if (!fillet.IsDone()) throw ValueError("Fillet failed: OCC build did not complete");
    return track_blend(fillet, solid, edges, "fillet.patch");
  });
}

TrackedResult tracked_chamfer(const Solid& solid, const std::vector<Edge>& edges, double distance,
                              std::optional<double> distance2,
                              const std::vector<std::pair<Face, Face>>& edge_face_pairs) {
  return occt_guard([&] {
    BRepFilletAPI_MakeChamfer chamfer(solid.wrapped());
    if (distance2) {
      if (edge_face_pairs.size() != edges.size()) {
        throw ValueError("An asymmetric chamfer requires one (face1, face2) pair per edge");
      }
      for (std::size_t i = 0; i < edges.size(); ++i) {
        const TopoDS_Edge edge = TopoDS::Edge(edges[i].wrapped());
        chamfer.Add(edge);
        // OCCT puts the first distance on the face it is given; the second
        // lands on the adjacent one.
        chamfer.SetDists(distance, *distance2, chamfer.Contour(edge),
                         TopoDS::Face(edge_face_pairs[i].first.wrapped()));
      }
    } else {
      for (const Edge& edge : edges) chamfer.Add(distance, TopoDS::Edge(edge.wrapped()));
    }
    chamfer.Build();
    if (!chamfer.IsDone()) throw ValueError("Chamfer failed: OCC build did not complete");
    return track_blend(chamfer, solid, edges, "chamfer.patch");
  });
}

TrackedResult tracked_shell(const Solid& solid, const std::vector<Face>& faces_to_remove, double thickness,
                            double tol) {
  return occt_guard([&] {
    TopTools_ListOfShape closing;
    std::vector<TopoDS_Shape> selected;
    selected.reserve(faces_to_remove.size());
    for (const Face& face : faces_to_remove) {
      closing.Append(face.wrapped());
      selected.push_back(face.wrapped());
    }

    BRepOffsetAPI_MakeThickSolid shell;
    shell.MakeThickSolidByJoin(solid.wrapped(), closing, -std::abs(thickness), tol, BRepOffset_Skin,
                               /*Intersection=*/false, /*SelfInter=*/false, GeomAbs_Arc,
                               /*RemoveIntEdges=*/false);
    shell.Build();
    if (!shell.IsDone()) throw ValueError("Shell failed: OCC build did not complete");

    const Solid result(kernel::as_solid(shell.Shape()));
    tracking::DeltaBuilder delta;
    if (tracking::history_wanted()) {
      tracking::BuilderHistory history(shell);
      kernel::SubShapeIndex in_result(result.wrapped());

      // Faces that stay: every face of the solid except those removed.
      TopTools_IndexedMapOfShape removed;
      for (const TopoDS_Shape& face : selected) removed.Add(face);
      TopTools_IndexedMapOfShape all_faces;
      TopExp::MapShapes(solid.wrapped(), TopAbs_FACE, all_faces);
      std::vector<TopoDS_Shape> remaining;
      for (int i = 1; i <= all_faces.Extent(); ++i) {
        if (!removed.Contains(all_faces.FindKey(i))) remaining.push_back(all_faces.FindKey(i));
      }

      tracking::QuerySpec body;
      body.origin_role = "body";
      body.kind = Kind::Face;
      body.result = &in_result;
      body.preserved_role = "shell.body_face";
      body.modified_role = "shell.body_face";
      body.generated_role = "shell.offset_face";
      body.project_source_tags = true;
      tracking::query_list_history(history, remaining, body, delta.witnesses);

      tracking::QuerySpec closing_faces;
      closing_faces.origin_role = "closing_face";
      closing_faces.kind = Kind::Face;
      closing_faces.result = &in_result;
      closing_faces.result_role = "shell.closing_descendant";
      closing_faces.project_source_tags = true;
      tracking::query_list_history(history, selected, closing_faces, delta.witnesses);

      std::vector<TopoDS_Shape> boundary;
      for (const TopoDS_Shape& face : selected) {
        TopTools_IndexedMapOfShape edges;
        TopExp::MapShapes(face, TopAbs_EDGE, edges);
        for (int i = 1; i <= edges.Extent(); ++i) boundary.push_back(edges.FindKey(i));
      }
      tracking::QuerySpec walls;
      walls.origin_role = "closing_boundary";
      walls.kind = Kind::Edge;
      walls.result = &in_result;
      walls.generated_role = "shell.wall";
      walls.project_source_tags = true;
      tracking::query_list_history(history, boundary, walls, delta.witnesses);

      tracking::add_roles_from_history(delta.roles, delta.witnesses, "GeneratedOrModified");
    }
    return tracking::to_result(result, std::move(delta));
  });
}

}  // namespace scad
