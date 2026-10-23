// Python bindings for the "render" area: the software renderer (see include/scad/render/render.hpp).
#include "bindings.hpp"

#include <cmath>
#include <memory>
#include <optional>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/render/render.hpp"
#include "scad/topo/shape.hpp"

namespace {

using namespace scad;
using namespace scad::render;

template <class Elem>
py::array view(const py::object& owner, const Elem* data, std::vector<py::ssize_t> shape) {
  std::vector<py::ssize_t> strides(shape.size());
  py::ssize_t stride = static_cast<py::ssize_t>(sizeof(Elem));
  for (std::size_t i = shape.size(); i-- > 0;) {
    strides[i] = stride;
    stride *= shape[i];
  }
  py::array array(py::dtype::of<Elem>(), shape, strides, data, owner);
  array.attr("setflags")(py::arg("write") = false);
  return array;
}

Rgb to_rgb(const std::array<double, 3>& c) { return {static_cast<float>(c[0]), static_cast<float>(c[1]), static_cast<float>(c[2])}; }

std::vector<float> flat_points(const py::array_t<float, py::array::c_style | py::array::forcecast>& a) {
  if (a.ndim() != 2 || a.shape(1) != 3) throw ValueError("expected an (n, 3) array of points");
  return std::vector<float>(a.data(), a.data() + a.size());
}

Style parse_style(const std::string& s) {
  if (s == "standard") return Style::Standard;
  if (s == "studio") return Style::Studio;
  throw ValueError("unknown render style: '" + s + "' (expected 'standard' or 'studio')");
}

MeshStyle mesh_style(const std::array<double, 3>& color, double opacity, bool studio_material, bool lit,
                     const std::optional<py::array_t<float, py::array::c_style | py::array::forcecast>>& face_colors) {
  MeshStyle s;
  s.color = to_rgb(color);
  s.opacity = static_cast<float>(opacity);
  s.studio_material = studio_material;
  s.lit = lit;
  if (face_colors) {
    const auto& a = *face_colors;
    if (a.ndim() != 2 || (a.shape(1) != 4 && a.shape(1) != 3)) throw ValueError("face_colors must be an (n, 4) rgba array (NaN alpha = default colour)");
    const std::size_t w = static_cast<std::size_t>(a.shape(1));
    for (py::ssize_t i = 0; i < a.shape(0); ++i) {
      const float* r = a.data() + static_cast<std::size_t>(i) * w;
      s.face_colors.push_back({r[0], r[1], r[2], w == 4 ? r[3] : 1.0f});
    }
  }
  return s;
}

LineStyle line_style(const std::array<double, 3>& color, std::optional<double> width_px, bool ink, std::optional<double> width_world,
                     std::optional<double> depth_bias) {
  LineStyle s;
  s.color = to_rgb(color);
  if (width_world) s.width_world = *width_world;
  else if (ink) s.width_world = -1.0;
  if (width_px) s.width_px = *width_px;
  s.depth_bias = depth_bias;
  return s;
}

}  // namespace

void bind_render(py::module_& m) {
  using FaceColors = std::optional<py::array_t<float, py::array::c_style | py::array::forcecast>>;
  using Color = std::array<double, 3>;

  py::class_<Scene, std::shared_ptr<Scene>>(
      m, "RenderScene",
      "The input of the software renderer: surface meshes (with per-face colours), line sets and point sets.")
      .def(py::init<>())
      .def(
          "add_mesh",
          [](Scene& s, const std::shared_ptr<io::Mesh>& mesh, Color color, double opacity, bool studio_material, bool lit,
             const FaceColors& face_colors) { return s.add_mesh(mesh, mesh_style(color, opacity, studio_material, lit, face_colors)); },
          py::arg("mesh"), py::arg("color") = Color{0.55, 0.64, 0.73}, py::arg("opacity") = 1.0, py::arg("studio_material") = false,
          py::arg("lit") = true, py::arg("face_colors") = py::none(),
          "Add a Mesh (the result of mesh(shape)); returns its index in the id buffer.  face_colors is an (n, 4) float array indexed by\n"
          "face id; a NaN alpha means 'use color'.")
      .def(
          "add_mesh_arrays",
          [](Scene& s, const py::array_t<float, py::array::c_style | py::array::forcecast>& vertices,
             const py::array_t<float, py::array::c_style | py::array::forcecast>& normals,
             const py::array_t<std::uint32_t, py::array::c_style | py::array::forcecast>& triangles,
             const py::array_t<std::uint32_t, py::array::c_style | py::array::forcecast>& face_ids, Color color, double opacity,
             bool studio_material, bool lit, const FaceColors& face_colors) {
            if (vertices.ndim() != 2 || vertices.shape(1) != 3 || normals.shape(0) != vertices.shape(0) || triangles.ndim() != 2 ||
                triangles.shape(1) != 3 || face_ids.size() != triangles.shape(0))
              throw ValueError("add_mesh_arrays: expected vertices (n,3), normals (n,3), triangles (m,3), face_ids (m,)");
            auto mesh = std::make_shared<io::Mesh>();
            mesh->vertices.assign(vertices.data(), vertices.data() + vertices.size());
            mesh->normals.assign(normals.data(), normals.data() + normals.size());
            mesh->triangles.assign(triangles.data(), triangles.data() + triangles.size());
            mesh->face_ids.assign(face_ids.data(), face_ids.data() + face_ids.size());
            for (std::uint32_t i : mesh->triangles)
              if (i >= vertices.shape(0)) throw ValueError("add_mesh_arrays: triangle index out of range");
            return s.add_mesh(std::move(mesh), mesh_style(color, opacity, studio_material, lit, face_colors));
          },
          py::arg("vertices"), py::arg("normals"), py::arg("triangles"), py::arg("face_ids"), py::arg("color") = Color{0.55, 0.64, 0.73},
          py::arg("opacity") = 1.0, py::arg("studio_material") = false, py::arg("lit") = true, py::arg("face_colors") = py::none())
      .def(
          "add_shape",
          [](Scene& s, const Shape& shape, Color color, double opacity, bool studio_material, bool lit, const FaceColors& face_colors,
             double linear_deflection, double angular_deflection, bool edges, Color edge_color, bool ink,
             std::optional<double> edge_width_px, std::optional<double> edge_deflection) {
            const TopoDS_Shape wrapped = shape.wrapped();
            io::MeshParameters mp;
            mp.linear_deflection = linear_deflection;
            mp.angular_deflection = angular_deflection;
            mp.validate();
            const MeshStyle ms = mesh_style(color, opacity, studio_material, lit, face_colors);
            const LineStyle ls = line_style(edge_color, edge_width_px, ink, std::nullopt, std::nullopt);
            std::shared_ptr<io::Mesh> mesh;
            Polylines lines;
            {
              py::gil_scoped_release release;
              mesh = std::make_shared<io::Mesh>(io::mesh(wrapped, mp));
              if (edges) lines = edge_polylines(wrapped, edge_deflection.value_or(std::min(linear_deflection, 0.04)));
            }
            const int index = s.add_mesh(std::move(mesh), ms);
            if (edges) s.add_lines(std::move(lines), ls);
            return index;
          },
          py::arg("shape"), py::arg("color") = Color{0.55, 0.64, 0.73}, py::arg("opacity") = 1.0, py::arg("studio_material") = false,
          py::arg("lit") = true, py::arg("face_colors") = py::none(), py::arg("linear_deflection") = io::kDefaultLinearDeflection,
          py::arg("angular_deflection") = io::kDefaultAngularDeflection, py::arg("edges") = true,
          py::arg("edge_color") = Color{0.16, 0.21, 0.27}, py::arg("ink") = true, py::arg("edge_width_px") = py::none(),
          py::arg("edge_deflection") = py::none(),
          "Tessellate `shape` and (by default) add its B-rep edges as ink.  Returns the mesh index.")
      .def(
          "add_edges",
          [](Scene& s, const Shape& shape, Color color, bool ink, std::optional<double> width_px, double deflection, int sample_count) {
            const TopoDS_Shape wrapped = shape.wrapped();
            Polylines lines;
            {
              py::gil_scoped_release release;
              lines = edge_polylines(wrapped, deflection, sample_count);
            }
            return s.add_lines(std::move(lines), line_style(color, width_px, ink, std::nullopt, std::nullopt));
          },
          py::arg("shape"), py::arg("color") = Color{0.16, 0.21, 0.27}, py::arg("ink") = false, py::arg("width_px") = 4.5,
          py::arg("deflection") = 0.04, py::arg("sample_count") = 0,
          "Add the edges of `shape` (an edge, a wire, a solid ...) as depth-tested lines of `width_px` output pixels (or ink).")
      .def(
          "add_polylines",
          [](Scene& s, const py::array_t<float, py::array::c_style | py::array::forcecast>& points,
             const std::optional<py::array_t<std::uint32_t, py::array::c_style | py::array::forcecast>>& starts, Color color, bool ink,
             std::optional<double> width_px, std::optional<double> depth_bias) {
            Polylines p;
            p.points = flat_points(points);
            const std::uint32_t n = static_cast<std::uint32_t>(p.points.size() / 3);
            if (starts) p.starts.assign(starts->data(), starts->data() + starts->size());
            else p.starts = {0, n};
            return s.add_lines(std::move(p), line_style(color, width_px, ink, std::nullopt, depth_bias));
          },
          py::arg("points"), py::arg("starts") = py::none(), py::arg("color") = Color{0.16, 0.21, 0.27}, py::arg("ink") = false,
          py::arg("width_px") = 4.5, py::arg("depth_bias") = py::none())
      .def(
          "add_points",
          [](Scene& s, const py::array_t<float, py::array::c_style | py::array::forcecast>& points, Color color, double size_px) {
            PointStyle ps;
            ps.color = to_rgb(color);
            ps.size_px = size_px;
            return s.add_points(flat_points(points), ps);
          },
          py::arg("points"), py::arg("color") = Color{0.78, 0.0, 0.0}, py::arg("size_px") = 15.0)
      .def("bounds",
           [](const Scene& s) {
             const Bounds b = s.bounds();
             return py::make_tuple(py::make_tuple(b.min.x, b.min.y, b.min.z), py::make_tuple(b.max.x, b.max.y, b.max.z));
           })
      .def_property_readonly("mesh_count", &Scene::mesh_count)
      .def_property_readonly("triangle_count", &Scene::triangle_count);

  py::class_<Panel>(m, "RenderPanel")
      .def_readonly("x", &Panel::x)
      .def_readonly("y", &Panel::y)
      .def_readonly("width", &Panel::width)
      .def_readonly("height", &Panel::height)
      .def_readonly("label", &Panel::label)
      .def_property_readonly("anchors",
                             [](const Panel& p) {
                               py::list out;
                               for (const AnchorResult& a : p.anchors) out.append(py::make_tuple(a.x, a.y, a.depth, a.in_view, a.visible));
                               return out;
                             },
                             "One (x, y, depth, in_view, visible) per requested anchor; x, y in output pixels (y down).")
      .def_property_readonly("axes_tips",
                             [](const Panel& p) {
                               py::list out;
                               for (const auto& t : p.axes_tips) out.append(py::make_tuple(t[0], t[1]));
                               return out;
                             })
      .def_property_readonly("camera",
                             [](const Panel& p) {
                               py::dict d;
                               auto t3 = [](const Vec3& v) { return py::make_tuple(v.x, v.y, v.z); };
                               d["target"] = t3(p.camera.target);
                               d["right"] = t3(p.camera.right);
                               d["up"] = t3(p.camera.up);
                               d["forward"] = t3(p.camera.forward);
                               d["half_height"] = p.camera.half_height;
                               d["aspect"] = p.camera.aspect;
                               return d;
                             })
      .def("project",
           [](const Panel& p, Vec3 point) {
             const AnchorResult a = p.project(point);
             return py::make_tuple(a.x, a.y, a.depth, a.in_view);
           },
           py::arg("point"), "(x, y, depth, in_view) of a world point in output pixels.");

  py::class_<Frame, std::shared_ptr<Frame>>(m, "RenderFrame",
                                            "A rendered image: rgba (h, w, 4) uint8, depth (h, w) float32 (+inf = background), mesh_id and\n"
                                            "face_id (h, w) int32 (-1 = background), the panels and their projected anchors.  Arrays are\n"
                                            "read-only views of the frame's memory.")
      .def_readonly("width", &Frame::width)
      .def_readonly("height", &Frame::height)
      .def_readonly("panels", &Frame::panels)
      .def_readonly("ink_diameter", &Frame::ink_diameter)
      .def_readonly("render_ms", &Frame::render_ms)
      .def_readonly("resolve_ms", &Frame::resolve_ms)
      .def_property_readonly("rgba", [](const py::object& self) {
        const auto& f = self.cast<const Frame&>();
        return view<std::uint8_t>(self, f.rgba.data(), {f.height, f.width, 4});
      })
      .def_property_readonly("depth", [](const py::object& self) {
        const auto& f = self.cast<const Frame&>();
        return view<float>(self, f.depth.data(), {f.height, f.width});
      })
      .def_property_readonly("mesh_id", [](const py::object& self) {
        const auto& f = self.cast<const Frame&>();
        return view<std::int32_t>(self, f.mesh_id.data(), {f.height, f.width});
      })
      .def_property_readonly("face_id", [](const py::object& self) {
        const auto& f = self.cast<const Frame&>();
        return view<std::int32_t>(self, f.face_id.data(), {f.height, f.width});
      });

  m.def(
      "render_scene",
      [](const Scene& scene, int width, int height, int supersample, const std::string& style,
         const std::vector<std::tuple<double, double, std::string>>& views, double legend_panel_fraction,
         std::optional<Vec3> view_up, double zoom, double edge_width_scale, bool show_axes, const std::vector<Vec3>& anchors,
         int threads, const std::string& resolve, std::optional<Color> background_top, std::optional<Color> background_bottom,
         double occlusion_tolerance) {
        RenderOptions o;
        o.width = width;
        o.height = height;
        o.supersample = supersample;
        o.style = parse_style(style);
        o.views.clear();
        for (const auto& [el, az, label] : views) o.views.push_back({el, az, label});
        o.legend_panel_fraction = legend_panel_fraction;
        o.view_up = view_up;
        o.zoom = zoom;
        o.edge_width_scale = edge_width_scale;
        o.show_axes = show_axes;
        o.anchors = anchors;
        o.threads = threads;
        if (resolve == "lanczos") o.resolve = Resolve::Lanczos;
        else if (resolve == "box") o.resolve = Resolve::Box;
        else throw ValueError("resolve must be 'lanczos' or 'box'");
        if (background_top) o.background_top = to_rgb(*background_top);
        if (background_bottom) o.background_bottom = to_rgb(*background_bottom);
        o.occlusion_tolerance = occlusion_tolerance;
        Frame frame;
        {
          py::gil_scoped_release release;
          frame = render_scene(scene, o);
        }
        return std::make_shared<Frame>(std::move(frame));
      },
      py::arg("scene"), py::arg("width") = 1400, py::arg("height") = 900, py::arg("supersample") = 2, py::arg("style") = "studio",
      py::arg("views") = std::vector<std::tuple<double, double, std::string>>{{28.0, -45.0, "isometric"}},
      py::arg("legend_panel_fraction") = 0.0, py::arg("view_up") = py::none(), py::arg("zoom") = 1.0,
      py::arg("edge_width_scale") = 0.0019, py::arg("show_axes") = false, py::arg("anchors") = std::vector<Vec3>{},
      py::arg("threads") = 0, py::arg("resolve") = "lanczos", py::arg("background_top") = py::none(),
      py::arg("background_bottom") = py::none(), py::arg("occlusion_tolerance") = 0.002,
      "Render `scene` into a grid of (elevation_deg, azimuth_deg, label) views (orthographic, supersampled, depth-tested).\n"
      "`zoom` multiplies the SDK's 0.92 fit; a single-view screenshot with the SDK's zoom=4 default is zoom=1.");

  m.def("render_view_preset", [](const std::string& name) { auto p = view_preset(name); return py::make_tuple(p.first, p.second); },
        py::arg("name"), "(elevation, azimuth) of a named view ('iso', 'top', 'front_right', ...).");
  m.def("render_auto_view", [](Vec3 spans) { auto p = auto_view(spans); return py::make_tuple(p.first, p.second); }, py::arg("spans"),
        "The 'auto' view for a model with these x/y/z extents.");
  m.def("render_edge_polylines",
        [](const Shape& shape, double deflection, int sample_count) {
          const Polylines p = edge_polylines(shape.wrapped(), deflection, sample_count);
          py::array_t<float> pts({static_cast<py::ssize_t>(p.points.size() / 3), static_cast<py::ssize_t>(3)});
          std::copy(p.points.begin(), p.points.end(), pts.mutable_data());
          py::array_t<std::uint32_t> starts(static_cast<py::ssize_t>(p.starts.size()));
          std::copy(p.starts.begin(), p.starts.end(), starts.mutable_data());
          return py::make_tuple(pts, starts);
        },
        py::arg("shape"), py::arg("deflection") = 0.04, py::arg("sample_count") = 0,
        "(points (n,3) float32, starts (k+1,) uint32): each unique B-rep edge of `shape` as a polyline.");
  m.def("render_default_threads", &default_threads);
}
