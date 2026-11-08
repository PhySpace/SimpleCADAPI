// The geometry swap behind every edit; see swap.hpp.
#include "swap.hpp"

#include <algorithm>
#include <map>

#include <Adaptor3d_CurveOnSurface.hxx>
#include <BRepBuilderAPI_ModifyShape.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepLib.hxx>
#include <BRepTools_Modification.hxx>
#include <BRep_Tool.hxx>
#include <Geom2dAdaptor_Curve.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom2d_Line.hxx>
#include <GeomAdaptor_Surface.hxx>
#include <GeomLib.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Vertex.hxx>

#include "scad/core/error.hpp"

namespace scad::surface::editing {

namespace {

// How close a recomputed 3D boundary curve must follow the edited surface along its pcurve.
constexpr double kBoundaryTolerance = 1e-7;

// The exact 3D curve of a pcurve that is an iso line u = c (direction +v) or v = c (direction +u) with the edge's
// parameter equal to the surface parameter along it; null otherwise.
Handle(Geom_Curve) exact_iso_curve(const Handle(Geom2d_Curve) & pcurve, const Handle(Geom_Surface) & surface) {
  const Handle(Geom2d_Line) line = Handle(Geom2d_Line)::DownCast(pcurve);
  if (line.IsNull())
    return {};
  const gp_Pnt2d origin = line->Location();
  const gp_Dir2d direction = line->Direction();
  constexpr double kExact = 1e-14;
  if (std::abs(direction.X()) < kExact && std::abs(direction.Y() - 1.0) < kExact && std::abs(origin.Y()) < kExact)
    return surface->UIso(origin.X());
  if (std::abs(direction.Y()) < kExact && std::abs(direction.X() - 1.0) < kExact && std::abs(origin.X()) < kExact)
    return surface->VIso(origin.Y());
  return {};
}

class GeometrySwap final : public BRepTools_Modification {
 public:
  GeometrySwap(TopoDS_Face face, Handle(Geom_Surface) surface, TopLoc_Location location)
      : face_(std::move(face)), surface_(std::move(surface)), location_(std::move(location)) {
    TopExp::MapShapes(face_, TopAbs_EDGE, edges_);
    TopExp::MapShapes(face_, TopAbs_VERTEX, vertices_);
  }
  GeometrySwap(TopoDS_Edge edge, Handle(Geom_Curve) curve, TopLoc_Location location)
      : edge_(std::move(edge)), curve_(std::move(curve)), location_(std::move(location)) {
    edges_.Add(edge_);
    TopExp::MapShapes(edge_, TopAbs_VERTEX, vertices_);
  }

  Standard_Boolean NewSurface(const TopoDS_Face& F, Handle(Geom_Surface) & S, TopLoc_Location& L, Standard_Real& Tol,
                              Standard_Boolean& RevWires, Standard_Boolean& RevFace) override {
    if (face_.IsNull() || !F.IsSame(face_))
      return Standard_False;
    S = surface_;
    L = location_;
    Tol = BRep_Tool::Tolerance(F);
    RevWires = Standard_False;
    RevFace = Standard_False;
    return Standard_True;
  }

  Standard_Boolean NewCurve(const TopoDS_Edge& E, Handle(Geom_Curve) & C, TopLoc_Location& L,
                            Standard_Real& Tol) override {
    if (!edges_.Contains(E))
      return Standard_False;
    if (face_.IsNull()) {
      C = curve_;
      L = location_;
      Tol = BRep_Tool::Tolerance(E);
      return Standard_True;
    }
    if (BRep_Tool::Degenerated(E))
      return Standard_False;
    double deviation = 0.0;
    C = boundary_curve(E, deviation);
    L = location_;
    Tol = std::max(BRep_Tool::Tolerance(E), deviation);
    return Standard_True;
  }

  Standard_Boolean NewPoint(const TopoDS_Vertex& V, gp_Pnt& P, Standard_Real& Tol) override {
    if (!vertices_.Contains(V))
      return Standard_False;
    if (face_.IsNull()) {
      P = curve_->Value(BRep_Tool::Parameter(V, edge_)).Transformed(location_.Transformation());
    } else {
      const gp_Pnt2d uv = BRep_Tool::Parameters(V, face_);
      P = surface_->Value(uv.X(), uv.Y()).Transformed(location_.Transformation());
    }
    Tol = BRep_Tool::Tolerance(V);
    return Standard_True;
  }

  Standard_Boolean NewCurve2d(const TopoDS_Edge& E, const TopoDS_Face& F, const TopoDS_Edge&, const TopoDS_Face&,
                              Handle(Geom2d_Curve) & C, Standard_Real& Tol) override {
    if (face_.IsNull() || !F.IsSame(face_))
      return Standard_False;
    double first = 0.0, last = 0.0;
    const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(E, F, first, last);
    if (pcurve.IsNull())
      return Standard_False;
    C = Handle(Geom2d_Curve)::DownCast(pcurve->Copy());
    Tol = BRep_Tool::Tolerance(E);
    return Standard_True;
  }

  Standard_Boolean NewParameter(const TopoDS_Vertex& V, const TopoDS_Edge& E, Standard_Real& P,
                                Standard_Real& Tol) override {
    if (!edges_.Contains(E) || !vertices_.Contains(V))
      return Standard_False;
    P = BRep_Tool::Parameter(V, E);
    Tol = BRep_Tool::Tolerance(V);
    return Standard_True;
  }

  GeomAbs_Shape Continuity(const TopoDS_Edge& E, const TopoDS_Face& F1, const TopoDS_Face& F2, const TopoDS_Edge&,
                           const TopoDS_Face&, const TopoDS_Face&) override {
    return BRep_Tool::Continuity(E, F1, F2);
  }

 private:
  // The edge's 3D curve on the new surface, from its pcurve on the face: exact for an iso line, otherwise
  // approximated with the edge's own parameters (GeomLib::BuildCurve3d keeps the edge same-parameter).
  Handle(Geom_Curve) boundary_curve(const TopoDS_Edge& edge, double& deviation) {
    const auto key = edge.TShape().get();
    if (const auto found = curves_.find(key); found != curves_.end()) {
      deviation = found->second.second;
      return found->second.first;
    }
    double first = 0.0, last = 0.0;
    const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, face_, first, last);
    if (pcurve.IsNull())
      throw ValueError("a boundary edge of the face has no curve in the face's (u, v) space");
    Handle(Geom_Curve) curve = exact_iso_curve(pcurve, surface_);
    deviation = 0.0;
    if (curve.IsNull()) {
      Adaptor3d_CurveOnSurface on_surface(new Geom2dAdaptor_Curve(pcurve, first, last),
                                          new GeomAdaptor_Surface(surface_));
      double average = 0.0;
      GeomLib::BuildCurve3d(kBoundaryTolerance, on_surface, first, last, curve, deviation, average, GeomAbs_C1, 14, 64);
      if (curve.IsNull())
        throw ValueError("a boundary edge of the face could not be rebuilt on the edited surface");
    }
    curves_.emplace(key, std::pair{curve, deviation});
    return curve;
  }

  TopoDS_Face face_;
  Handle(Geom_Surface) surface_;
  TopoDS_Edge edge_;
  Handle(Geom_Curve) curve_;
  TopLoc_Location location_;
  TopTools_IndexedMapOfShape edges_, vertices_;
  std::map<const void*, std::pair<Handle(Geom_Curve), double>> curves_;  // per edge TShape (a seam is computed once)
};

// BRepBuilderAPI_ModifyShape with our modification: a MakeShape, so its history is BRepTools_History(args, builder).
class SwapBuilder final : public BRepBuilderAPI_ModifyShape {
 public:
  SwapBuilder(const TopoDS_Shape& shape, const Handle(BRepTools_Modification) & modification)
      : BRepBuilderAPI_ModifyShape(shape, modification) {}
};

Swapped run(const TopoDS_Shape& input, const Handle(BRepTools_Modification) & modification, const char* what) {
  SwapBuilder builder(input, modification);
  if (!builder.IsDone() || builder.Shape().IsNull())
    throw ValueError(std::string("the kernel could not rebuild the ") + what + " on the edited geometry");
  TopoDS_Shape shape = builder.Shape();
  if (!BRepCheck_Analyzer(shape).IsValid()) {
    BRepLib::SameParameter(shape, 1e-5, Standard_True);
    if (!BRepCheck_Analyzer(shape).IsValid())
      throw ValueError(std::string("the rebuilt ") + what + " is not valid; the edit folds or breaks its boundary");
  }
  TopTools_ListOfShape arguments;
  arguments.Append(input);
  return {shape, BRepTools_History(arguments, builder)};
}

}  // namespace

Swapped swap_face_surface(const TopoDS_Face& face, const Handle(Geom_Surface) & surface,
                          const TopLoc_Location& location) {
  return run(face, new GeometrySwap(face, surface, location), "face");
}

Swapped swap_edge_curve(const TopoDS_Edge& edge, const Handle(Geom_Curve) & curve, const TopLoc_Location& location) {
  return run(edge, new GeometrySwap(edge, curve, location), "edge");
}

}  // namespace scad::surface::editing
