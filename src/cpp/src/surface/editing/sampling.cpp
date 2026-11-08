// sample_curve_rcurvature / sample_surface_risocurves: what an editor draws over a curve (a curvature comb) or a
// surface (its isocurves, clipped to the face's trimming).  Diagnostic: nothing is recorded.
#include <cmath>

#include <BRepTools.hxx>
#include <BRepTopAdaptor_FClass2d.hxx>
#include <GeomLProp_CLProps.hxx>
#include <TopoDS.hxx>

#include "access.hpp"
#include "finish.hpp"
#include "fit.hpp"
#include "scad/surface/editing.hpp"

namespace scad {

using namespace surface::editing;

namespace {

constexpr int kMaxSamples = 10000;

void check_count(int value, int low, const char* label) {
  if (value < low || value > kMaxSamples)
    throw ValueError(std::string(label) + " must be between " + std::to_string(low) + " and " +
                     std::to_string(kMaxSamples));
}

Value vector_value(const Vec3& v) {
  return Value(Value::Array{v.x, v.y, v.z});
}

}  // namespace

Value sample_curve_rcurvature(const Edge& edge, int count) {
  static const ErrorSpec kSpec{"sample_curve_rcurvature",
                               "Failed to sample the curvature of the edge.",
                               {"The edge is degenerated or count is out of range."},
                               {"Pass an edge with a 3D curve and 2 <= count <= 10000."}};
  return edit_scope(kSpec, [&] {
    if (edge.wrapped().IsNull())
      throw ValueError("edge must not be null");
    check_count(count, 2, "count");
    const CurveRep rep = curve_rep(TopoDS::Edge(edge.wrapped()));
    GeomLProp_CLProps props(rep.curve, 2, 1e-9);
    Value::Array parameters, points, tangents, normals, curvatures;
    double max_curvature = 0.0;
    for (double t : even_parameters(rep.first, rep.last, count)) {
      props.SetParameter(t);
      parameters.emplace_back(t);
      points.push_back(point_value(user_point(props.Value(), rep.location)));
      Vec3 tangent{0, 0, 0}, normal{0, 0, 0};
      double curvature = 0.0;
      if (props.IsTangentDefined()) {
        gp_Dir d;
        props.Tangent(d);
        tangent = user_vector(gp_Vec(d), rep.location);
        curvature = props.Curvature();
        if (curvature > 1e-12) {
          gp_Dir n;
          props.Normal(n);
          normal = user_vector(gp_Vec(n), rep.location);
        }
      }
      tangents.push_back(vector_value(tangent));
      normals.push_back(vector_value(normal));
      curvatures.emplace_back(curvature);
      max_curvature = std::max(max_curvature, curvature);
    }
    Value out = Value::object();
    out.set("parameters", Value(std::move(parameters)));
    out.set("points", Value(std::move(points)));
    out.set("tangents", Value(std::move(tangents)));
    out.set("normals", Value(std::move(normals)));
    out.set("curvatures", Value(std::move(curvatures)));
    out.set("max_curvature", max_curvature);
    return out;
  });
}

Value sample_surface_risocurves(const Face& face, int u_count, int v_count, int samples) {
  static const ErrorSpec kSpec{"sample_surface_risocurves",
                               "Failed to sample the isocurves of the face.",
                               {"The face has no surface or a count is out of range."},
                               {"Pass a valid face, counts >= 0 and 2 <= samples <= 10000."}};
  return edit_scope(kSpec, [&] {
    if (face.wrapped().IsNull())
      throw ValueError("face must not be null");
    check_count(u_count, 0, "u_count");
    check_count(v_count, 0, "v_count");
    check_count(samples, 2, "samples");
    const TopoDS_Face f = TopoDS::Face(face.wrapped());
    const SurfaceRep rep = surface_rep(f);
    double u1 = 0, u2 = 0, v1 = 0, v2 = 0;
    BRepTools::UVBounds(f, u1, u2, v1, v2);
    BRepTopAdaptor_FClass2d classifier(f, 1e-9);

    // One family: lines at `count` parameters strictly inside [low, high], each sampled along the other direction
    // and cut into the runs that lie on the face.
    const auto family = [&](int count, bool constant_u) {
      Value::Array lines;
      const double low = constant_u ? u1 : v1, high = constant_u ? u2 : v2;
      const double other_low = constant_u ? v1 : u1, other_high = constant_u ? v2 : u2;
      for (int i = 1; i <= count; ++i) {
        const double c = low + (high - low) * i / (count + 1);
        Value::Array segments, current;
        for (double s : even_parameters(other_low, other_high, samples)) {
          const gp_Pnt2d uv = constant_u ? gp_Pnt2d(c, s) : gp_Pnt2d(s, c);
          const TopAbs_State state = classifier.Perform(uv);
          if (state == TopAbs_IN || state == TopAbs_ON) {
            current.push_back(point_value(user_point(rep.surface->Value(uv.X(), uv.Y()), rep.location)));
          } else if (!current.empty()) {
            if (current.size() > 1)
              segments.emplace_back(std::move(current));
            current = {};
          }
        }
        if (current.size() > 1)
          segments.emplace_back(std::move(current));
        Value line = Value::object();
        line.set("parameter", c);
        line.set("segments", Value(std::move(segments)));
        lines.push_back(std::move(line));
      }
      return Value(std::move(lines));
    };
    Value out = Value::object();
    out.set("u", family(u_count, true));
    out.set("v", family(v_count, false));
    out.set("uv_bounds", Value(Value::Array{u1, u2, v1, v2}));
    return out;
  });
}

}  // namespace scad
