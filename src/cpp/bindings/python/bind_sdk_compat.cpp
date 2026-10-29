// Names the Python SDK exposes below its public surface that the layers staying in Python
// (build/, artifacts/, recording/serializer.py, scene/, ...) import from the lower modules:
// the non-recording assembly solver, connector resolution, and the helpers around Assembly.
// The Python package maps them into simplecadapi.product.{solver,connector,assembly}
// (simplecadapi/_native/compat.py).
#include "bind_product_args.hpp"
#include "bind_reactive_common.hpp"
#include "py_lifetime.hpp"
#include "scad/core/tolerance.hpp"
#include "scad/topo/diagnostic_image.hpp"

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopoDS.hxx>
#include <array>
#include <cmath>
#include <set>
#include <mutex>
#include <unordered_map>
#include <vector>
#include <BRepBuilderAPI_Transform.hxx>
#include <GCPnts_TangentialDeflection.hxx>
#include <TopLoc_Location.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Curve.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>
#include <gp_Circ.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Elips.hxx>
#include <gp_Lin.hxx>
#include <gp_Sphere.hxx>
#include <gp_Torus.hxx>
#include <gp_Ax1.hxx>
#include <TopAbs_Orientation.hxx>
#include <gp_Ax3.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>

#include "scad/kernel/curves.hpp"
#include "scad/product/resolve.hpp"
#include "scad/reactive/lineage.hpp"
#include "scad/topo/delta.hpp"
#include "scad/product/solver.hpp"

namespace {

using namespace scad;
using namespace scad::product_binding;

void bind_product_internals(py::module_& m) {
  m.def(
      "solve_assembly_constraints",
      [](const py::object& assembly, const py::object& strict) {
        if (!py::isinstance<sp::Assembly>(assembly))
          throw TypeError("assembly must be an Assembly");
        return sp::solve_assembly_constraints(assembly.cast<sp::AssemblyPtr>(), truthy(strict));
      },
      py::arg("assembly"), py::arg("strict") = true, "Solve the assembly constraints without recording a graph node.");
  m.def(
      "inspect_assembly_constraints",
      [](const py::object& assembly) {
        return sp::inspect_assembly_constraints(typed<sp::Assembly>(assembly, "assembly must be an Assembly"));
      },
      py::arg("assembly"), "Residuals of every constraint and the components the grounded ones reach.");
  m.def(
      "constraint_reports_match",
      [](const py::object& actual, const py::object& expected) {
        return sp::constraint_reports_match(pybind::value_from_python(actual), pybind::value_from_python(expected));
      },
      py::arg("actual"), py::arg("expected"), "Two ConstraintReport dicts agree within the solver tolerances.");

  m.def(
      "resolve_connector",
      [](const py::object& assembly, const py::object& ref) {
        return sp::resolve_connector(typed<sp::Assembly>(assembly, "assembly must be an Assembly"),
                                     typed<sp::ConnectorRef>(ref, "connector_ref must be a ConnectorRef"));
      },
      py::arg("assembly"), py::arg("connector_ref"));
  m.def(
      "resolve_item_connector",
      [](const py::object& item, const py::object& connector_id) {
        return sp::resolve_item_connector(item_of(item), text(connector_id, "connector_id"));
      },
      py::arg("item"), py::arg("connector_id"));
  m.def(
      "resolve_item_connector_placement",
      [](const py::object& item, const py::object& connector_id) {
        return sp::resolve_item_connector_placement(item_of(item), text(connector_id, "connector_id"));
      },
      py::arg("item"), py::arg("connector_id"));
  m.def(
      "resolve_connector_ref_placement",
      [](const py::object& assembly, const py::object& ref) {
        return sp::resolve_connector_ref_placement(
            typed<sp::Assembly>(assembly, "assembly must be an Assembly"),
            typed<sp::ConnectorRef>(ref, "connector_ref must be a ConnectorRef"));
      },
      py::arg("assembly"), py::arg("connector_ref"));
  m.def(
      "resolve_connector_placement",
      [](const py::object& connector) {
        return sp::resolve_connector_placement(typed<sp::Connector>(connector, "connector must be a Connector"));
      },
      py::arg("connector"));

  py::class_<sp::Assembly, py::smart_holder> assembly =
      py::reinterpret_borrow<py::class_<sp::Assembly, py::smart_holder>>(m.attr("Assembly"));
  assembly.def(
      "_with_component_path_placement",
      [](const sp::Assembly& self, const std::vector<std::string>& path, const py::object& placement) {
        return self.with_component_path_placement(path,
                                                  typed<sp::Placement>(placement, "placement must be a Placement"));
      },
      py::arg("component_path"), py::arg("placement"));
}

// The semantic state of a topology entity as plain dictionaries: what the artifact layer of
// the Python SDK (topology snapshots) reads and writes, and what no accessor handed out whole.
template <class T>
void add_state_dicts(py::module_& m, const char* name) {
  py::class_<T, py::smart_holder> cls = py::reinterpret_borrow<py::class_<T, py::smart_holder>>(m.attr(name));
  cls.def("_metadata_dict", [](const T& value) { return pybind::value_to_python(value.metadata()); });
  cls.def("_runtime_dict", [](const T& value) { return pybind::value_to_python(value.runtime()); });
}

// BRepBndLib::AddOptimal on a trimmed torus or B-spline face costs 10-15 ms, and the geometry-interface
// fingerprint measures the same faces again every time a part is captured, restored or re-hashed.  The
// box of a face depends only on its TShape and Location (not on tags or orientation), so it is memoised
// on that pair.  The entry keeps the TShape alive: a freed address can never be mistaken for a new face.
kernel::BoundingBox face_bounding_box(const Shape& s) {
  if (s.kind() != Kind::Face)
    return s.bounding_box();
  struct Entry {
    TopoDS_Shape keep;
    kernel::BoundingBox box;
  };
  static std::mutex mutex;
  static std::unordered_map<const void*, std::vector<Entry>> cache;
  static std::size_t entries = 0;
  constexpr std::size_t kMaxEntries = 8192;
  const TopoDS_Shape& shape = s.wrapped();
  const void* tshape = shape.TShape().get();
  {
    std::lock_guard<std::mutex> lock(mutex);
    const auto it = cache.find(tshape);
    if (it != cache.end())
      for (const Entry& e : it->second)
        if (e.keep.Location() == shape.Location())
          return e.box;
  }
  const kernel::BoundingBox box = s.bounding_box();
  std::lock_guard<std::mutex> lock(mutex);
  if (entries >= kMaxEntries) {
    cache.clear();
    entries = 0;
  }
  cache[tshape].push_back({shape, box});
  ++entries;
  return box;
}

void bind_shape_internals(py::module_& m) {
  add_state_dicts<sp::Part>(m, "Part");
  add_state_dicts<sp::Assembly>(m, "Assembly");
  add_state_dicts<sp::Placement>(m, "Placement");
  add_state_dicts<sp::Material>(m, "Material");
  add_state_dicts<sp::Connector>(m, "Connector");
  add_state_dicts<sp::ConnectorRef>(m, "ConnectorRef");
  add_state_dicts<sp::GeometryRef>(m, "GeometryRef");
  add_state_dicts<sp::ConnectorAnchor>(m, "ConnectorAnchor");
  add_state_dicts<sp::Constraint>(m, "Constraint");
  add_state_dicts<sp::ScalarLimit>(m, "ScalarLimit");
  py::class_<Shape> any = py::reinterpret_borrow<py::class_<Shape>>(m.attr("AnyShape"));
  any.def("_metadata_dict", [](const Shape& s) { return pybind::value_to_python(s.metadata()); });
  any.def("_runtime_dict", [](const Shape& s) { return pybind::value_to_python(s.runtime()); });
  any.def(
      "_bounds",
      [](const Shape& s) {
        const auto b = face_bounding_box(s);
        return py::make_tuple(b.xmin, b.ymin, b.zmin, b.xmax, b.ymax, b.zmax);
      },
      "(xmin, ymin, zmin, xmax, ymax, zmax) of the shape.");
  any.def(
      "_shape_key",
      [](const Shape& s) {
        // Identity of the geometry (TShape address, Location, Orientation): equal keys on live handles mean the
        // same OCCT shape.  Callers that memoise on it must hold the handle so the address cannot be reused.
        const TopoDS_Shape& shape = s.wrapped();
        const gp_Trsf t = shape.Location().Transformation();
        return py::make_tuple(reinterpret_cast<std::uintptr_t>(shape.TShape().get()),
                              static_cast<int>(shape.Orientation()), t.ScaleFactor(), static_cast<int>(t.Form()),
                              t.Value(1, 1), t.Value(1, 2), t.Value(1, 3), t.Value(1, 4), t.Value(2, 1), t.Value(2, 2),
                              t.Value(2, 3), t.Value(2, 4), t.Value(3, 1), t.Value(3, 2), t.Value(3, 3), t.Value(3, 4));
      },
      "Identity key of the underlying OCCT shape (see the memo in artifacts' geometry interface).");
  any.def(
      "_geom_type",
      [](const Shape& s) -> py::object {
        if (s.kind() == Kind::Face) {
          switch (BRepAdaptor_Surface(TopoDS::Face(s.wrapped()), true).GetType()) {
            case GeomAbs_Plane:
              return py::str("PLANE");
            case GeomAbs_Cylinder:
              return py::str("CYLINDER");
            case GeomAbs_Cone:
              return py::str("CONE");
            case GeomAbs_Sphere:
              return py::str("SPHERE");
            case GeomAbs_Torus:
              return py::str("TORUS");
            case GeomAbs_BezierSurface:
              return py::str("BEZIER");
            case GeomAbs_BSplineSurface:
              return py::str("BSPLINE");
            case GeomAbs_SurfaceOfRevolution:
              return py::str("REVOLUTION");
            case GeomAbs_SurfaceOfExtrusion:
              return py::str("EXTRUSION");
            case GeomAbs_OffsetSurface:
              return py::str("OFFSET");
            default:
              return py::str("OTHER");
          }
        }
        if (s.kind() == Kind::Edge) {
          switch (BRepAdaptor_Curve(TopoDS::Edge(s.wrapped())).GetType()) {
            case GeomAbs_Line:
              return py::str("LINE");
            case GeomAbs_Circle:
              return py::str("CIRCLE");
            case GeomAbs_Ellipse:
              return py::str("ELLIPSE");
            case GeomAbs_Hyperbola:
              return py::str("HYPERBOLA");
            case GeomAbs_Parabola:
              return py::str("PARABOLA");
            case GeomAbs_BezierCurve:
              return py::str("BEZIER");
            case GeomAbs_BSplineCurve:
              return py::str("BSPLINE");
            case GeomAbs_OffsetCurve:
              return py::str("OFFSET");
            default:
              return py::str("OTHER");
          }
        }
        return py::none();
      },
      "The geometric type of a face's surface or an edge's curve, or None.");
  any.def(
      "_polyline",
      [](const Shape& s, double linear, double angular) {
        // The edge as the scene renders it: forward oriented, its location baked in, sampled by tangential deflection.
        if (s.kind() != Kind::Edge)
          throw TypeError("_polyline needs an Edge");
        TopoDS_Shape prepared = s.wrapped().Oriented(TopAbs_FORWARD);
        const TopLoc_Location location = prepared.Location();
        TopoDS_Shape unlocated = prepared.Located(TopLoc_Location(), Standard_False);
        if (!location.IsIdentity()) {
          BRepBuilderAPI_Transform builder(unlocated, location.Transformation(), Standard_True, Standard_False);
          builder.Build();
          if (!builder.IsDone())
            throw ValueError("location bake failed");
          unlocated = builder.Shape();
        }
        BRepAdaptor_Curve adaptor(TopoDS::Edge(unlocated));
        GCPnts_TangentialDeflection sampler(adaptor, adaptor.FirstParameter(), adaptor.LastParameter(), angular, linear,
                                            2, 1e-9, 1e-7);
        py::list out;
        for (int i = 1; i <= sampler.NbPoints(); ++i) {
          const gp_Pnt p = sampler.Value(i);
          out.append(py::make_tuple(p.X(), p.Y(), p.Z()));
        }
        return out;
      },
      py::arg("linear"), py::arg("angular"));
  any.def(
      "_orientation",
      [](const Shape& s) {
        switch (s.wrapped().Orientation()) {
          case TopAbs_REVERSED:
            return "reversed";
          case TopAbs_INTERNAL:
            return "internal";
          case TopAbs_EXTERNAL:
            return "external";
          default:
            return "forward";
        }
      },
      "The orientation of this occurrence in its container: forward, reversed, internal or external.");
  any.def(
      "_geometry",
      [](const Shape& s) -> py::object {
        const auto point = [](const gp_Pnt& p) { return py::make_tuple(p.X(), p.Y(), p.Z()); };
        const auto dir = [](const gp_Dir& d) { return py::make_tuple(d.X(), d.Y(), d.Z()); };
        py::dict out;
        if (s.kind() == Kind::Face) {
          BRepAdaptor_Surface a(TopoDS::Face(s.wrapped()), true);
          switch (a.GetType()) {
            case GeomAbs_Cylinder: {
              const gp_Cylinder v = a.Cylinder();
              out["origin"] = point(v.Location());
              out["axis"] = dir(v.Axis().Direction());
              out["x_direction"] = dir(v.XAxis().Direction());
              out["radius"] = v.Radius();
              return out;
            }
            case GeomAbs_Sphere: {
              const gp_Sphere v = a.Sphere();
              out["center"] = point(v.Location());
              out["axis"] = dir(v.Position().Direction());
              out["x_direction"] = dir(v.XAxis().Direction());
              out["radius"] = v.Radius();
              return out;
            }
            case GeomAbs_Torus: {
              const gp_Torus v = a.Torus();
              out["center"] = point(v.Location());
              out["axis"] = dir(v.Axis().Direction());
              out["x_direction"] = dir(v.XAxis().Direction());
              out["major_radius"] = std::max(v.MajorRadius(), v.MinorRadius());
              out["minor_radius"] = std::min(v.MajorRadius(), v.MinorRadius());
              return out;
            }
            default:
              return py::none();
          }
        }
        if (s.kind() == Kind::Edge) {
          BRepAdaptor_Curve a(TopoDS::Edge(s.wrapped()));
          switch (a.GetType()) {
            case GeomAbs_Line: {
              const gp_Lin v = a.Line();
              out["origin"] = point(v.Location());
              out["direction"] = dir(v.Direction());
              return out;
            }
            case GeomAbs_Circle: {
              const gp_Circ v = a.Circle();
              out["center"] = point(v.Location());
              out["normal"] = dir(v.Axis().Direction());
              out["x_direction"] = dir(v.XAxis().Direction());
              out["radius"] = v.Radius();
              return out;
            }
            case GeomAbs_Ellipse: {
              const gp_Elips v = a.Ellipse();
              out["center"] = point(v.Location());
              out["normal"] = dir(v.Axis().Direction());
              out["x_direction"] = dir(v.XAxis().Direction());
              out["major_radius"] = v.MajorRadius();
              out["minor_radius"] = v.MinorRadius();
              return out;
            }
            case GeomAbs_BSplineCurve: {
              const Handle(Geom_BSplineCurve) v = a.BSpline();
              out["degree"] = v->Degree();
              out["rational"] = static_cast<bool>(v->IsRational());
              out["periodic"] = static_cast<bool>(v->IsPeriodic());
              out["poles_count"] = v->NbPoles();
              out["knots_count"] = v->NbKnots();
              return out;
            }
            default:
              return py::none();
          }
        }
        return py::none();
      },
      "The analytic parameters of a face's surface (cylinder, sphere, torus) or an edge's curve, or None.");
  any.def(
      "_topo_ref",
      [](const Shape& s) -> py::object {
        const auto ref = reactive::topo_ref_of(s);
        return ref ? pybind::value_to_python(to_value(*ref)) : py::object(py::none());
      },
      "The durable reference (graph, node, slot, kind, topo id) of an entity of a recorded output, or None.");
  any.def(
      "_keep_topology_owner", [](const Shape& s) { reactive::keep_topology_owner(s); },
      "Before a tag node re-attributes the shape: its contents stay named by the nodes that made them.");
}

// ---------------------------------------------------------------------------
// B-spline data for the translators (kept in Python).
// ---------------------------------------------------------------------------
py::list pole_list(const Handle(Geom_BSplineCurve) & c) {
  py::list out;
  for (int i = 1; i <= c->NbPoles(); ++i) {
    const gp_Pnt p = c->Pole(i);
    out.append(py::make_tuple(p.X(), p.Y(), p.Z()));
  }
  return out;
}

py::dict bspline_curve_dict(const Handle(Geom_BSplineCurve) & c) {
  py::dict d;
  d["control_points"] = pole_list(c);
  d["degree"] = c->Degree();
  py::list knots, mults, weights;
  for (int i = 1; i <= c->NbKnots(); ++i) {
    knots.append(c->Knot(i));
    mults.append(c->Multiplicity(i));
  }
  for (int i = 1; i <= c->NbPoles(); ++i)
    weights.append(c->Weight(i));
  d["knots"] = knots;
  d["multiplicities"] = mults;
  d["weights"] = weights;
  d["rational"] = static_cast<bool>(c->IsRational());
  d["periodic"] = static_cast<bool>(c->IsPeriodic());
  return d;
}

// loft_geometry._curve_value: a curve segment as an editable-sketch recipe.
py::dict loft_curve_value(const Handle(Geom_Curve) & curve, double first, double last) {
  Handle(Geom_BSplineCurve) copy = Handle(Geom_BSplineCurve)::DownCast(curve->Copy());
  if (copy.IsNull())
    throw TypeError("iso-curve of a B-spline surface is not a B-spline");
  copy->Segment(first, last);
  py::dict d;
  d["kind"] = "edge";
  if (copy->Degree() == 1 && copy->NbPoles() == 2) {
    const gp_Pnt a = copy->Pole(1), b = copy->Pole(2);
    d["type"] = "line";
    d["start"] = py::make_tuple(a.X(), a.Y(), a.Z());
    d["end"] = py::make_tuple(b.X(), b.Y(), b.Z());
    return d;
  }
  d["type"] = "spline";
  py::dict data = bspline_curve_dict(copy);
  d["controls"] = data["control_points"];
  d["degree"] = data["degree"];
  d["knots"] = data["knots"];
  d["multiplicities"] = data["multiplicities"];
  d["weights"] = data["weights"];
  d["periodic"] = data["periodic"];
  return d;
}

// loft_geometry.canonical_guided_loft over a native shape; None when no face is a B-spline surface.
py::object guided_loft_recipe(const Shape& shape) {
  std::vector<BRepAdaptor_Surface> sides;
  for (TopExp_Explorer ex(shape.wrapped(), TopAbs_FACE); ex.More(); ex.Next()) {
    BRepAdaptor_Surface surface(TopoDS::Face(ex.Current()));
    if (surface.GetType() == GeomAbs_BSplineSurface)
      sides.push_back(std::move(surface));
  }
  if (sides.empty())
    return py::none();
  constexpr int kStations = 9;
  std::vector<py::list> profiles(kStations);
  py::list guides;
  std::set<std::array<double, 9>> guide_keys;
  const auto rounded = [](double v) { return std::round(v * 1e8) / 1e8; };
  for (const BRepAdaptor_Surface& surface : sides) {
    const Handle(Geom_BSplineSurface) spline = surface.BSpline();
    const double u0 = surface.FirstUParameter(), u1 = surface.LastUParameter();
    const double v0 = surface.FirstVParameter(), v1 = surface.LastVParameter();
    for (int index = 0; index < kStations; ++index) {
      const double v = v0 + (v1 - v0) * index / (kStations - 1);
      profiles[static_cast<std::size_t>(index)].append(loft_curve_value(spline->VIso(v), u0, u1));
    }
    const int count = surface.UDegree() == 1 ? 1 : 16;
    for (int index = 0; index <= count; ++index) {
      const double u = u0 + (u1 - u0) * index / count;
      const Handle(Geom_Curve) curve = spline->UIso(u);
      std::array<double, 9> key{};
      int slot = 0;
      for (const double fraction : {0.0, 0.5, 1.0}) {
        const gp_Pnt p = curve->Value(v0 + (v1 - v0) * fraction);
        key[static_cast<std::size_t>(slot++)] = rounded(p.X());
        key[static_cast<std::size_t>(slot++)] = rounded(p.Y());
        key[static_cast<std::size_t>(slot++)] = rounded(p.Z());
      }
      if (!guide_keys.insert(key).second)
        continue;
      guides.append(loft_curve_value(curve, v0, v1));
    }
  }
  py::list wires;
  for (py::list& edges : profiles) {
    py::dict wire;
    wire["kind"] = "wire";
    wire["edges"] = edges;
    wires.append(wire);
  }
  py::dict out;
  out["profiles"] = wires;
  out["guides"] = guides;
  return out;
}

}  // namespace

// An evidence dict from the Python provider as the C++ ErrorEvidence.
ErrorEvidence evidence_of(const py::object& item) {
  ErrorEvidence out;
  const auto text = [&](const char* key) {
    return item.contains(key) && !item[key].is_none() ? py::str(item[key]).cast<std::string>() : std::string();
  };
  out.kind = text("kind");
  out.path = text("path");
  out.view = text("view");
  out.caption = text("caption");
  if (item.contains("symbols") && !item["symbols"].is_none())
    for (const py::handle pair : item["symbols"]) {
      const py::sequence entry = py::reinterpret_borrow<py::sequence>(pair);
      out.symbols.emplace_back(py::str(entry[0]).cast<std::string>(), py::str(entry[1]).cast<std::string>());
    }
  return out;
}

// The Python callable a C++ registry keeps: released without touching the interpreter once it has gone.
class KeptCallable {
 public:
  explicit KeptCallable(py::object fn) : fn_(std::move(fn)) {}
  KeptCallable(const KeptCallable&) = delete;
  KeptCallable& operator=(const KeptCallable&) = delete;
  ~KeptCallable() { scad::pybind::drop_python_reference(fn_); }
  const py::object& get() const { return fn_; }

 private:
  py::object fn_;
};

void bind_sdk_compat(py::module_& m) {
  bind_product_internals(m);
  bind_shape_internals(m);
  m.def(
      "_set_diagnostic_image_provider",
      [](const py::object& provider) {
        if (provider.is_none()) {
          set_diagnostic_image_provider({});
          return;
        }
        const auto callable = std::make_shared<KeptCallable>(provider);
        set_diagnostic_image_provider([callable](const DiagnosticImage& request) -> std::optional<ErrorEvidence> {
          const py::gil_scoped_acquire gil;  // the operation that failed may be running without the GIL
          py::list shapes;
          for (const Shape& shape : request.shapes)
            shapes.append(scad::pybind::reactive::shape_to_python(shape));
          const py::object picture =
              callable->get()(request.kind, request.operation, request.view, request.caption, request.dedup_key, shapes,
                              scad::pybind::value_to_python(request.payload));
          if (picture.is_none())
            return std::nullopt;
          return evidence_of(picture);
        });
      },
      py::arg("provider"),
      "Install provider(kind, operation, view, caption, dedup_key, shapes, payload) -> evidence dict or None: it "
      "draws the pictures a failing operation asks for.  None removes it.");
  m.def(
      "_sample_edge_points",
      [](const Shape& edge, int samples) {
        if (edge.kind() != Kind::Edge)
          throw TypeError("_sample_edge_points needs an Edge");
        const BRepAdaptor_Curve curve(TopoDS::Edge(edge.wrapped()));
        const int count = std::max(2, samples);
        std::vector<std::array<double, 3>> out;
        out.reserve(static_cast<std::size_t>(count));
        const double first = curve.FirstParameter(), last = curve.LastParameter();
        for (int i = 0; i < count; ++i) {
          const gp_Pnt p = curve.Value(first + (last - first) * i / (count - 1));
          out.push_back({p.X(), p.Y(), p.Z()});
        }
        return out;
      },
      py::arg("edge"), py::arg("samples") = 16, "Points along an edge, evenly in parameter.");
  m.def("_guided_loft_recipe", &guided_loft_recipe, py::arg("shape"),
        "Boundary profiles and guide curves of the B-spline faces of a loft (translator recipe), or None.");
  m.def(
      "_interpolated_bspline_edge",
      [](const std::vector<std::array<double, 3>>& points, bool periodic, double tolerance) {
        std::vector<Vec3> pts;
        pts.reserve(points.size());
        for (const auto& p : points)
          pts.push_back(Vec3{p[0], p[1], p[2]});
        return Edge(kernel::make_interpolated_bspline_edge(pts, periodic, tolerance));
      },
      py::arg("points"), py::kw_only(), py::arg("periodic") = false, py::arg("tolerance") = tol::kSplineInterpolation,
      "An interpolating B-spline edge through the points (GeomAPI_Interpolate).");
  m.def(
      "_bspline_curve_of",
      [](const Shape& edge) {
        if (edge.kind() != Kind::Edge)
          throw TypeError("_bspline_curve_of needs an Edge");
        BRepAdaptor_Curve adaptor(TopoDS::Edge(edge.wrapped()));
        if (adaptor.GetType() != GeomAbs_BSplineCurve)
          throw ValueError("the edge's curve is not a B-spline");
        return bspline_curve_dict(adaptor.BSpline());
      },
      py::arg("edge"), "Poles, degree, knots, multiplicities, weights of an edge's B-spline curve.");
}
