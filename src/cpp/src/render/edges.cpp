// B-rep edge polylines without OCP: BRepAdaptor_Curve + GCPnts, the same sampling as render.py _sample_edge.
#include <BRepAdaptor_Curve.hxx>
#include <BRep_Tool.hxx>
#include <GCPnts_QuasiUniformDeflection.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>

#include "scad/core/error.hpp"
#include "scad/render/render.hpp"

namespace scad::render {

namespace {
void push_point(std::vector<float>& out, const gp_Pnt& p) {
  out.push_back(static_cast<float>(p.X()));
  out.push_back(static_cast<float>(p.Y()));
  out.push_back(static_cast<float>(p.Z()));
}
}  // namespace

Polylines edge_polylines(const TopoDS_Shape& shape, double deflection, int sample_count) {
  if (shape.IsNull()) throw ValueError("edge_polylines: null shape");
  if (sample_count == 0 && !(deflection > 0.0)) throw ValueError("edge deflection must be greater than zero");
  if (sample_count == 1 || sample_count < 0) throw ValueError("edge sample count must be at least two");
  Polylines out;
  out.starts.push_back(0);
  occt_guard([&] {
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(shape, TopAbs_EDGE, edges);
    for (int i = 1; i <= edges.Extent(); ++i) {
      const TopoDS_Edge edge = TopoDS::Edge(edges.FindKey(i));
      if (BRep_Tool::Degenerated(edge)) continue;
      BRepAdaptor_Curve curve(edge);
      const std::size_t before = out.points.size();
      const double first = curve.FirstParameter(), last = curve.LastParameter();
      if (sample_count >= 2) {
        for (int k = 0; k < sample_count; ++k)
          push_point(out.points, curve.Value(first + (last - first) * k / (sample_count - 1)));
      } else {
        GCPnts_QuasiUniformDeflection sampler(curve, deflection);
        if (sampler.IsDone() && sampler.NbPoints() >= 2) {
          for (int k = 1; k <= sampler.NbPoints(); ++k) push_point(out.points, sampler.Value(k));
        } else {
          push_point(out.points, curve.Value(first));
          push_point(out.points, curve.Value(last));
        }
      }
      if ((out.points.size() - before) / 3 < 2) {
        out.points.resize(before);
        continue;
      }
      out.starts.push_back(static_cast<std::uint32_t>(out.points.size() / 3));
    }
  });
  return out;
}

}  // namespace scad::render
