// tracked_loft / tracked_sweep / tracked_twisted_sweep: solids built along a
// path or through sections.
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_PipeError.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepFill_TypeOfContact.hxx>
#include <BRepLib.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <GCE2d_MakeSegment.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax3.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>

#include <algorithm>
#include <cmath>
#include <unordered_set>

#include "scad/core/tolerance.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/cast.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/kernel/transforms.hpp"
#include "scad/semantic/tracking.hpp"
#include "tracking_detail.hpp"

namespace scad {

// ===========================================================================
// loft
// ===========================================================================

TrackedResult tracked_loft(const std::vector<Shape>& profiles, bool ruled) {
  // ThruSections crashes the process on a single section instead of failing.
  if (profiles.size() < 2)
    throw ValueError("Loft requires at least two profiles");
  return occt_guard([&] {
    BRepOffsetAPI_ThruSections loft(/*isSolid=*/true, ruled);
    loft.CheckCompatibility(true);
    for (const Shape& profile : profiles) {
      switch (profile.kind()) {
        case Kind::Vertex:
          loft.AddVertex(TopoDS::Vertex(profile.wrapped()));
          break;
        case Kind::Wire:
          loft.AddWire(TopoDS::Wire(profile.wrapped()));
          break;
        default:
          throw TypeError("loft profiles must be wires or vertices");
      }
    }
    loft.Build();
    if (!loft.IsDone())
      throw ValueError("Loft failed: OCC build did not complete");

    const Solid result(kernel::as_solid(loft.Shape()));
    tracking::DeltaBuilder delta;
    kernel::SubShapeIndex in_result(result.wrapped());

    if (tracking::history_wanted()) {
      tracking::BuilderHistory history(loft);
      for (std::size_t i = 0; i < profiles.size(); ++i) {
        if (profiles[i].kind() == Kind::Vertex)
          continue;
        const std::string origin = "profile_" + std::to_string(i);
        tracking::QuerySpec spec;
        spec.origin_role = origin;
        spec.kind = Kind::Edge;
        spec.result = &in_result;
        spec.generated_role = "loft.side";
        spec.project_source_tags = true;
        tracking::query_sub_shape_history(history, profiles[i].wrapped(), TopAbs_EDGE, spec, delta.witnesses);
      }
      tracking::add_roles_from_history(delta.roles, delta.witnesses, "Generated");
    }

    const bool starts_with_wire = profiles.front().kind() == Kind::Wire;
    const bool ends_with_wire = profiles.back().kind() == Kind::Wire;
    if (starts_with_wire && ends_with_wire) {
      tracking::add_operation_role(delta.roles, in_result, loft.FirstShape(), "loft.start", "FirstShape");
      tracking::add_operation_role(delta.roles, in_result, loft.LastShape(), "loft.end", "LastShape");
    } else if (tracking::history_wanted()) {
      // A point end has no cap: the cap faces are the ones no side role claimed.
      std::unordered_set<std::string> side_faces;
      for (const tracking::RoleWitness& role : delta.roles) {
        if (role.role == "loft.side" && role.kind == Kind::Face)
          side_faces.insert(role.topo_id);
      }
      std::vector<TopoDS_Shape> caps;
      for (const TopoDS_Face& face : kernel::faces_of(result.wrapped())) {
        if (!side_faces.contains(kernel_topo_id(face)))
          caps.push_back(face);
      }
      std::vector<std::string_view> cap_roles;
      if (starts_with_wire)
        cap_roles.push_back("loft.start");
      if (ends_with_wire)
        cap_roles.push_back("loft.end");
      if (caps.size() != cap_roles.size()) {
        throw ValueError("Loft point-profile topology did not produce the expected endpoint caps");
      }
      for (std::size_t i = 0; i < caps.size(); ++i) {
        tracking::add_operation_role(delta.roles, in_result, caps[i], cap_roles[i], "NonSideEndpointCap");
      }
    }
    return tracking::to_result(result, std::move(delta));
  });
}

// ===========================================================================
// sweep
// ===========================================================================

TrackedResult tracked_sweep(const Face& profile, const Wire& path, bool is_frenet) {
  return occt_guard([&] {
    const TopoDS_Face face = TopoDS::Face(profile.wrapped());
    if (!kernel::inner_wires_of(face).empty()) {
      throw ValueError(
          "Sweep profiles with inner wires are unsupported because PipeShell only receives the outer profile wire");
    }
    const TopoDS_Wire outer = kernel::outer_wire_of(face);
    BRepOffsetAPI_MakePipeShell sweep(TopoDS::Wire(path.wrapped()));
    sweep.SetMode(is_frenet);
    sweep.Add(outer, /*WithContact=*/false, /*WithCorrection=*/false);
    sweep.Build();
    if (!sweep.IsDone())
      throw ValueError("Sweep failed: OCC build did not complete");
    if (!sweep.MakeSolid())
      throw ValueError("Sweep failed: OCC solid conversion did not complete");

    const Solid result(kernel::as_solid(sweep.Shape()));
    tracking::DeltaBuilder delta;
    kernel::SubShapeIndex in_result(result.wrapped());

    if (tracking::history_wanted()) {
      tracking::BuilderHistory history(sweep);
      tracking::QuerySpec spec;
      spec.origin_role = "profile";
      spec.kind = Kind::Edge;
      spec.result = &in_result;
      spec.generated_role = "sweep.side";
      spec.project_source_tags = true;
      tracking::query_sub_shape_history(history, outer, TopAbs_EDGE, spec, delta.witnesses);
      tracking::add_roles_from_history(delta.roles, delta.witnesses, "Generated");
    }
    tracking::add_operation_role(delta.roles, in_result, sweep.FirstShape(), "sweep.start", "FirstShape");
    tracking::add_operation_role(delta.roles, in_result, sweep.LastShape(), "sweep.end", "LastShape");
    return tracking::to_result(result, std::move(delta));
  });
}

// ===========================================================================
// twisted sweep
// ===========================================================================

namespace {

std::string_view pipe_error_name(BRepBuilderAPI_PipeError status) noexcept {
  switch (status) {
    case BRepBuilderAPI_PipeDone:
      return "BRepBuilderAPI_PipeDone";
    case BRepBuilderAPI_PipeNotDone:
      return "BRepBuilderAPI_PipeNotDone";
    case BRepBuilderAPI_PlaneNotIntersectGuide:
      return "BRepBuilderAPI_PlaneNotIntersectGuide";
    case BRepBuilderAPI_ImpossibleContact:
      return "BRepBuilderAPI_ImpossibleContact";
  }
  return "BRepBuilderAPI_PipeNotDone";
}

// The planar cap whose vertices all sit at one station along `axis`
// (measured from the global origin, as the Python SDK does), if exactly one does.
bool axial_cap_face(const TopoDS_Shape& solid, const Vec3& axis, double axial_coordinate, TopoDS_Shape& out) {
  int matches = 0;
  for (const TopoDS_Face& face : kernel::faces_of(solid)) {
    double worst = 0.0;
    bool any = false;
    for (const TopoDS_Vertex& vertex : kernel::vertices_of(face)) {
      worst = std::max(worst, std::abs(kernel::vertex_point(vertex).dot(axis) - axial_coordinate));
      any = true;
    }
    if (any && worst < 1.0e-7) {
      ++matches;
      out = face;
    }
  }
  return matches == 1;
}

struct SkinnedWire {
  TopoDS_Shape shape;
  double surface_error = 0.0;
};

}  // namespace

TrackedResult tracked_twisted_sweep(const Face& profile, const Vec3& axis, const Vec3& origin, double distance,
                                    double twist_angle, double guide_radius) {
  return occt_guard([&] {
    const TopoDS_Face face = TopoDS::Face(profile.wrapped());
    if (BRepAdaptor_Surface(face, true).GetType() != GeomAbs_Plane) {
      throw ValueError("Twisted sweep requires a planar profile");
    }
    if (std::abs(profile.normal_at().dot(axis)) < 1.0 - 1.0e-8) {
      throw ValueError("Twisted sweep profile must be normal to the sweep axis");
    }
    const double axial_offset = (profile.center() - origin).dot(axis);
    if (std::abs(axial_offset) > std::max(1.0e-7, distance * 1.0e-9)) {
      throw ValueError("Twisted sweep profile must lie at the sweep origin");
    }

    // A reference direction perpendicular to the axis fixes the guide cylinder's seam.
    const gp_Dir axis_dir = kernel::to_dir(axis, "twisted sweep axis");
    const Vec3 seed = std::abs(axis.x) < 0.9 ? Vec3{1.0, 0.0, 0.0} : Vec3{0.0, 1.0, 0.0};
    const gp_Dir reference_dir = kernel::to_dir(seed - axis * seed.dot(axis), "twisted sweep reference");

    const gp_Pnt start = kernel::to_pnt(origin);
    const gp_Pnt end = kernel::to_pnt(origin + axis * distance);
    BRepBuilderAPI_MakeEdge spine_edge_builder(start, end);
    if (!spine_edge_builder.IsDone())
      throw ValueError("Twisted sweep failed to build its straight spine");
    const TopoDS_Edge spine_edge = spine_edge_builder.Edge();
    BRepBuilderAPI_MakeWire spine_builder(spine_edge);
    if (!spine_builder.IsDone())
      throw ValueError("Twisted sweep failed to build its spine wire");
    const TopoDS_Wire spine = spine_builder.Wire();

    // The rotation law: a straight line on a cylinder around the axis, whose
    // u runs through `twist_angle` while v runs the length of the sweep.
    const opencascade::handle<Geom_CylindricalSurface> cylinder =
        new Geom_CylindricalSurface(gp_Ax3(start, axis_dir, reference_dir), guide_radius);
    const GCE2d_MakeSegment guide_curve(gp_Pnt2d(0.0, 0.0), gp_Pnt2d(twist_angle * kPi / 180.0, distance));
    BRepBuilderAPI_MakeEdge guide_edge_builder(guide_curve.Value(), cylinder);
    if (!guide_edge_builder.IsDone())
      throw ValueError("Twisted sweep failed to build its rotation guide");
    BRepBuilderAPI_MakeWire guide_builder(guide_edge_builder.Edge());
    if (!guide_builder.IsDone())
      throw ValueError("Twisted sweep failed to build its rotation guide wire");
    const TopoDS_Wire guide = guide_builder.Wire();
    BRepLib::BuildCurves3d(guide, 1.0e-7, GeomAbs_C1, 14, 2000);

    const TopoDS_Vertex spine_start = TopExp::FirstVertex(spine_edge, true);
    const auto skin = [&](const TopoDS_Wire& wire) {
      BRepOffsetAPI_MakePipeShell sweep(spine);
      sweep.SetTolerance(1.0e-6, 1.0e-6, 1.0e-4);
      sweep.SetMaxDegree(11);
      sweep.SetMaxSegments(200);
      sweep.SetMode(guide, /*CurvilinearEquivalence=*/true, BRepFill_NoContact);
      sweep.Add(wire, spine_start, /*WithContact=*/false, /*WithCorrection=*/false);
      sweep.Build();
      if (!sweep.IsDone()) {
        throw ValueError("Twisted sweep failed: " + std::string(pipe_error_name(sweep.GetStatus())));
      }
      return SkinnedWire{sweep.Shape(), sweep.ErrorOnSurface()};
    };

    // Every wire of the profile -- outer and holes -- is swept into its own skin.
    std::vector<TopoDS_Wire> wires{kernel::outer_wire_of(face)};
    for (const TopoDS_Wire& inner : kernel::inner_wires_of(face))
      wires.push_back(inner);
    std::vector<TopoDS_Shape> skins;
    double surface_error = 0.0;
    for (const TopoDS_Wire& wire : wires) {
      SkinnedWire skinned = skin(wire);
      surface_error = std::max(surface_error, skinned.surface_error);
      skins.push_back(std::move(skinned.shape));
    }

    gp_Trsf rotation;
    rotation.SetRotation(gp_Ax1(start, axis_dir), twist_angle * kPi / 180.0);
    gp_Trsf translation;
    translation.SetTranslation(gp_Vec(axis.x * distance, axis.y * distance, axis.z * distance));
    const TopoDS_Shape end_face = kernel::apply_transform(face, translation.Multiplied(rotation));

    // The skins plus a cap at each end close into a shell.
    BRepBuilderAPI_Sewing sewing(tol::kSewing, true);
    for (const TopoDS_Shape& skinned : skins)
      sewing.Add(skinned);
    sewing.Add(face);
    sewing.Add(end_face);
    sewing.Perform();
    const TopoDS_Shape sewed = sewing.SewedShape();

    TopoDS_Shell shell;
    if (!sewed.IsNull() && sewed.ShapeType() == TopAbs_SHELL) {
      shell = TopoDS::Shell(sewed);
    } else if (!sewed.IsNull() && sewed.ShapeType() == TopAbs_COMPOUND) {
      const TopExp_Explorer explorer(sewed, TopAbs_SHELL);
      if (explorer.More())
        shell = TopoDS::Shell(explorer.Current());
    }
    if (shell.IsNull())
      throw ValueError("Twisted sweep failed to sew its shells into a closed skin");

    BRepBuilderAPI_MakeSolid solid_builder(shell);
    if (!solid_builder.IsDone())
      throw ValueError("Twisted sweep failed to convert its shell into a solid");
    TopoDS_Solid solid = solid_builder.Solid();
    BRepLib::OrientClosedSolid(solid);

    Solid result(solid);
    if (!BRepCheck_Analyzer(result.wrapped(), true).IsValid()) {
      throw ValueError("Twisted sweep produced an invalid solid");
    }
    Value kernel_meta = Value::object();
    kernel_meta.set("surface_error", surface_error);
    result.set_metadata("twisted_sweep.kernel", std::move(kernel_meta));

    tracking::DeltaBuilder delta;
    kernel::SubShapeIndex in_result(result.wrapped());
    TopoDS_Shape start_cap, end_cap;
    const bool has_start = axial_cap_face(result.wrapped(), axis, 0.0, start_cap);
    const bool has_end = axial_cap_face(result.wrapped(), axis, distance, end_cap);
    std::unordered_set<std::string> cap_ids;
    if (has_start)
      cap_ids.insert(kernel_topo_id(start_cap));
    if (has_end)
      cap_ids.insert(kernel_topo_id(end_cap));

    for (const TopoDS_Face& wall : kernel::faces_of(result.wrapped())) {
      if (cap_ids.contains(kernel_topo_id(wall)))
        continue;
      tracking::add_operation_role(delta.roles, in_result, wall, "twisted_sweep.side", "SewnSide");
    }
    if (has_start)
      tracking::add_operation_role(delta.roles, in_result, start_cap, "twisted_sweep.start", "sewn_cap");
    if (has_end)
      tracking::add_operation_role(delta.roles, in_result, end_cap, "twisted_sweep.end", "sewn_cap");
    return tracking::to_result(result, std::move(delta));
  });
}

}  // namespace scad
