// Software renderer: known-geometry cases.
#include "doctest.h"

#include <algorithm>
#include <cmath>
#include <set>

#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <gp_Trsf.hxx>

#include "scad/core/error.hpp"
#include "scad/render/render.hpp"

using namespace scad;
using namespace scad::render;

namespace {

TopoDS_Shape box(double x, double y, double z, double ox = 0, double oy = 0, double oz = 0) {
  return BRepPrimAPI_MakeBox(gp_Pnt(ox, oy, oz), x, y, z).Solid();
}

RenderOptions options(int w, int h, double el, double az, int ss = 1) {
  RenderOptions o;
  o.width = w;
  o.height = h;
  o.supersample = ss;
  o.views = {{el, az, "v"}};
  o.style = Style::Standard;
  o.threads = 1;
  return o;
}

std::array<std::uint8_t, 3> pixel(const Frame& f, int x, int y) {
  const std::size_t o = (static_cast<std::size_t>(y) * static_cast<std::size_t>(f.width) + static_cast<std::size_t>(x)) * 4;
  return {f.rgba[o], f.rgba[o + 1], f.rgba[o + 2]};
}

std::int32_t face_at(const Frame& f, int x, int y) { return f.face_id[static_cast<std::size_t>(y) * static_cast<std::size_t>(f.width) + static_cast<std::size_t>(x)]; }

}  // namespace

TEST_CASE("a box seen from +Z fills the projected rectangle and nothing else") {
  Scene scene;
  scene.add_shape(box(10, 8, 4));
  RenderOptions o = options(400, 300, 90.0, 0.0);
  o.edge_width_scale = 0.0;
  const Frame f = render_scene(scene, o);
  const Panel& p = f.panels.at(0);
  const AnchorResult lo = p.project({0, 0, 4}), hi = p.project({10, 8, 4});
  const double x0 = std::min(lo.x, hi.x), x1 = std::max(lo.x, hi.x), y0 = std::min(lo.y, hi.y), y1 = std::max(lo.y, hi.y);
  const std::int32_t top = face_at(f, 200, 150);
  REQUIRE(top >= 0);
  int inside = 0, wrong = 0;
  for (int y = 0; y < f.height; ++y)
    for (int x = 0; x < f.width; ++x) {
      const bool in = x + 0.5 > x0 + 1 && x + 0.5 < x1 - 1 && y + 0.5 > y0 + 1 && y + 0.5 < y1 - 1;
      const bool out = x + 0.5 < x0 - 1 || x + 0.5 > x1 + 1 || y + 0.5 < y0 - 1 || y + 0.5 > y1 + 1;
      if (in) { ++inside; wrong += face_at(f, x, y) != top; }
      if (out) wrong += face_at(f, x, y) != -1;
    }
  CHECK(inside > 20000);
  CHECK(wrong == 0);
  // 8 / 10 of the width: the box is 10 wide in x (image x), 8 in y (image up): the rectangle keeps that ratio.
  CHECK((x1 - x0) / (y1 - y0) == doctest::Approx(10.0 / 8.0).epsilon(1e-6));
  // depth of the top face is constant and nearer than the background
  const float d = f.depth[150 * 400 + 200];
  CHECK(std::isfinite(d));
  CHECK(f.depth[0] == std::numeric_limits<float>::infinity());
}

TEST_CASE("the camera fit follows VTK's ResetCamera + Zoom(0.92)") {
  Bounds b;
  b.add({0, 0, 0});
  b.add({10, 8, 4});
  const Camera landscape = fit_camera(90, 0, b, 1.5);
  CHECK(landscape.half_height == doctest::Approx(0.5 * std::sqrt(100 + 64 + 16) / 0.92));
  const Camera portrait = fit_camera(90, 0, b, 0.5);
  CHECK(portrait.half_height == doctest::Approx(0.5 * std::sqrt(100 + 64 + 16) / 0.5 / 0.92));
  CHECK(view_preset("ISO").first == 25.0);
  CHECK_THROWS_AS(view_preset("nonsense"), ValueError);
}

TEST_CASE("an isometric view shows three faces, each with its own id") {
  Scene scene;
  scene.add_shape(box(10, 8, 4));
  RenderOptions o = options(300, 300, 35.0, 45.0);
  const Frame f = render_scene(scene, o);
  std::set<std::int32_t> ids;
  for (std::int32_t v : f.face_id)
    if (v >= 0) ids.insert(v);
  CHECK(ids.size() == 3);
  for (std::int32_t m : f.mesh_id) CHECK(m <= 0);
}

TEST_CASE("the nearer box occludes anchors on the farther one") {
  Scene scene;
  scene.add_shape(box(4, 10, 10, 0, 0, 0));    // front (x = 0..4), seen from +X
  scene.add_shape(box(4, 2, 2, -8, 4, 4));     // behind it, hidden
  scene.add_shape(box(4, 2, 2, -8, 20, 4));    // behind but off to the side: visible
  RenderOptions o = options(400, 400, 0.0, 0.0);
  o.anchors = {{4, 5, 5}, {-4, 5, 5}, {-4, 21, 5}};
  const Frame f = render_scene(scene, o);
  const auto& a = f.panels.at(0).anchors;
  CHECK(a[0].visible);    // on the front face of the near box
  CHECK_FALSE(a[1].visible);  // the far box's +X face is behind the near box
  CHECK(a[2].visible);
  CHECK(a[1].in_view);
  CHECK(face_at(f, static_cast<int>(a[0].x), static_cast<int>(a[0].y)) >= 0);
}

TEST_CASE("per-face highlight colours and opacity") {
  const TopoDS_Shape shape = box(10, 8, 4);
  Scene scene;
  MeshStyle style;
  style.face_colors.assign(6, {std::nanf(""), 0, 0, std::nanf("")});
  // find the +Z face: the one at the image centre of a top view
  RenderOptions o = options(200, 200, 90.0, 0.0);
  o.edge_width_scale = 0.0;
  {
    Scene probe;
    probe.add_shape(shape);
    const Frame f = render_scene(probe, o);
    const std::int32_t top = face_at(f, 100, 100);
    REQUIRE(top >= 0);
    style.face_colors[static_cast<std::size_t>(top)] = {1.0f, 0.0f, 0.0f, 1.0f};
  }
  scene.add_shape(shape, style, {}, false);
  const Frame f = render_scene(scene, o);
  const auto c = pixel(f, 100, 100);
  CHECK(c[0] > 200);
  CHECK(c[1] < 90);  // only VTK's white specular term lifts the other channels
  CHECK(c[2] < 90);
  // translucent: the same face at 30% over the gradient background mixes both
  Scene glass;
  MeshStyle clear;
  clear.color = {1.0f, 0.0f, 0.0f};
  clear.opacity = 0.3f;
  glass.add_shape(shape, clear, {}, false);
  const auto m = pixel(render_scene(glass, o), 100, 100);
  CHECK(m[0] > 200);          // red + light background
  CHECK(m[1] > 100);
  CHECK(m[1] < 230);
}

TEST_CASE("edges are ink on visible edges and absent behind the solid") {
  Scene scene;
  scene.add_shape(box(10, 8, 4), {}, {}, true, [] { LineStyle s; s.width_world = -1; return s; }());
  RenderOptions o = options(500, 500, 30.0, 30.0, 2);
  o.edge_width_scale = 0.01;
  const Frame f = render_scene(scene, o);
  const Panel& p = f.panels.at(0);
  auto ink = [&](const Vec3& a, const Vec3& b) {
    const AnchorResult m = p.project((a + b) * 0.5);
    const auto c = pixel(f, static_cast<int>(m.x), static_cast<int>(m.y));
    return std::abs(int(c[0]) - 41) < 20 && std::abs(int(c[1]) - 54) < 20 && std::abs(int(c[2]) - 69) < 20;
  };
  // the eye sits at +x +y +z: the +X, +Y and +Z faces are seen
  CHECK(ink({0, 8, 4}, {10, 8, 4}));          // top edge of the +Y face
  CHECK(ink({10, 8, 0}, {0, 8, 0}));          // bottom edge of the +Y face
  CHECK_FALSE(ink({0, 0, 0}, {10, 0, 0}));    // bottom edge of the hidden -Y face
}

TEST_CASE("the image does not depend on the thread count") {
  Scene scene;
  BRepFilletAPI_MakeFillet fillet(box(10, 8, 4));
  for (TopExp_Explorer ex(box(1, 1, 1), TopAbs_EDGE); false && ex.More(); ex.Next()) {}
  TopoDS_Shape b = box(10, 8, 4);
  BRepFilletAPI_MakeFillet mk(b);
  for (TopExp_Explorer ex(b, TopAbs_EDGE); ex.More(); ex.Next()) mk.Add(1.0, TopoDS::Edge(ex.Current()));
  scene.add_shape(mk.Shape(), {}, {}, true, [] { LineStyle s; s.width_world = -1; return s; }());
  scene.add_shape(BRepPrimAPI_MakeCylinder(2.0, 9.0).Shape(), [] { MeshStyle s; s.color = {0.9f, 0.2f, 0.2f}; return s; }());
  RenderOptions o = options(321, 243, 28.0, -45.0, 3);
  o.style = Style::Studio;
  o.show_axes = true;
  o.views = {{28, -45, "a"}, {90, -90, "b"}, {0, -90, "c"}, {0, 0, "d"}};
  o.anchors = {{1, 1, 1}};
  o.threads = 1;
  const Frame ref = render_scene(scene, o);
  for (int threads : {2, 3, 8}) {
    o.threads = threads;
    const Frame f = render_scene(scene, o);
    CHECK(f.rgba == ref.rgba);
    CHECK(f.depth == ref.depth);
    CHECK(f.face_id == ref.face_id);
    CHECK(f.mesh_id == ref.mesh_id);
  }
}

TEST_CASE("supersampling keeps the output size and flat regions unchanged") {
  Scene scene;
  scene.add_shape(box(10, 8, 4), {}, {}, false);
  for (int ss : {1, 2, 3, 4}) {
    RenderOptions o = options(160, 120, 90.0, 0.0, ss);
    const Frame f = render_scene(scene, o);
    CHECK(f.width == 160);
    CHECK(f.rgba.size() == 160u * 120u * 4u);
    CHECK(pixel(f, 80, 60)[0] > 100);
    // Lanczos of a constant region is the constant
    const auto a = pixel(f, 80, 60), b = pixel(f, 81, 61);
    CHECK(a == b);
  }
  RenderOptions bad = options(10, 10, 0, 0);
  bad.supersample = 5;
  CHECK_THROWS_AS(render_scene(scene, bad), ValueError);
}

TEST_CASE("multi-view layout, legend strip and projected anchors") {
  Scene scene;
  scene.add_shape(box(10, 8, 4));
  RenderOptions o = options(800, 600, 0, 0);
  o.views = {{28, -45, "a"}, {90, -90, "b"}, {0, -90, "c"}};
  o.legend_panel_fraction = 0.25;
  o.anchors = {{5, 4, 2}};
  const Frame f = render_scene(scene, o);
  REQUIRE(f.panels.size() == 3);
  CHECK(f.panels[0].x == 0);
  CHECK(f.panels[1].x == 300);
  CHECK(f.panels[0].y == 0);
  CHECK(f.panels[2].y == 300);
  CHECK(f.panels[2].width == 300);
  // the strip stays background: no face ids there
  CHECK(face_at(f, 700, 300) == -1);
  // the box centre projects to the panel centre
  for (const Panel& p : f.panels) {
    CHECK(p.anchors[0].x == doctest::Approx(p.x + p.width / 2.0).epsilon(0.01));
    CHECK(p.anchors[0].y == doctest::Approx(p.y + p.height / 2.0).epsilon(0.01));
  }
}
