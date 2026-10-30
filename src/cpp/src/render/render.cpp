#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>

#include "internal.hpp"
#include "scad/core/error.hpp"

namespace scad::render {

int default_threads() {
  const unsigned n = std::thread::hardware_concurrency();
  return n == 0 ? 1 : static_cast<int>(n);
}

AnchorResult Panel::project(const Vec3& p) const {
  const Camera::Projected q = camera.project(p);
  AnchorResult r;
  r.x = x + q.x * width;
  r.y = y + q.y * height;
  r.depth = q.depth;
  r.in_view = q.x >= 0.0 && q.x < 1.0 && q.y >= 0.0 && q.y < 1.0;
  return r;
}

namespace {

using Clock = std::chrono::steady_clock;
double ms_since(Clock::time_point t) {
  return std::chrono::duration<double, std::milli>(Clock::now() - t).count();
}

void validate_options(const RenderOptions& o) {
  if (o.width < 1 || o.height < 1)
    throw ValueError("image size must be greater than zero");
  if (o.supersample < 1 || o.supersample > 4)
    throw ValueError("supersample must be within 1..4");
  if (o.views.empty())
    throw ValueError("at least one render view is required");
  if (!(o.zoom > 0.0))
    throw ValueError("zoom must be greater than zero");
  if (o.legend_panel_fraction < 0.0 || o.legend_panel_fraction >= 1.0)
    throw ValueError("legend_panel_fraction must be in [0, 1)");
}

// Window background (also the legend strip).
void fill_window_background(std::vector<std::uint8_t>& big, Style style) {
  const bool studio = style == Style::Studio;
  const Rgb flat = studio ? Rgb{0, 0, 0} : Rgb{0.94f, 0.96f, 0.98f};
  for (std::size_t i = 0; i < big.size(); i += 4) {
    big[i] = static_cast<std::uint8_t>(flat[0] * 255.0f + 0.5f);
    big[i + 1] = static_cast<std::uint8_t>(flat[1] * 255.0f + 0.5f);
    big[i + 2] = static_cast<std::uint8_t>(flat[2] * 255.0f + 0.5f);
    big[i + 3] = 255;
  }
}

// Scene bounds (grown by the ink radius when edges are drawn as world-width ink) and their span.
struct SceneMeasures {
  Bounds bounds;
  double span;
};

SceneMeasures measure_scene(const Scene& scene, const RenderOptions& o, Frame& frame) {
  Bounds bounds = scene.bounds();
  double span = bounds.valid ? bounds.span() : 1.0;
  if (span <= 0.0)
    span = 1.0;
  bool has_ink = false;
  for (const auto& l : scene.lines())
    if (l.style.width_world < 0.0)
      has_ink = true;
  frame.ink_diameter = (has_ink && o.edge_width_scale > 0.0) ? 2.0 * o.edge_width_scale * span : 0.0;
  if (frame.ink_diameter > 0.0 && bounds.valid) {
    const double r = frame.ink_diameter * 0.5;
    bounds.add(bounds.min - Vec3{r, r, r});
    bounds.add(bounds.max + Vec3{r, r, r});
  }
  return {bounds, span};
}

// Panels: min(2, n) columns, left to right, top to bottom, in the part not taken by the legend strip.
void draw_panels(const Scene& scene, const RenderOptions& o, Frame& frame, const detail::Target& target,
                 const SceneMeasures& m, int threads) {
  const int n = static_cast<int>(o.views.size());
  const int columns = std::min(2, n), rows = (n + columns - 1) / columns;
  const int strip = static_cast<int>(std::lround(o.width * o.legend_panel_fraction));
  const int render_w = o.width - strip;
  for (int i = 0; i < n; ++i) {
    const int col = i % columns, row = i / columns;
    Panel panel;
    panel.x = static_cast<int>(std::lround(static_cast<double>(col) * render_w / columns));
    const int x1 = static_cast<int>(std::lround(static_cast<double>(col + 1) * render_w / columns));
    panel.y = static_cast<int>(std::lround(static_cast<double>(row) * o.height / rows));
    const int y1 = static_cast<int>(std::lround(static_cast<double>(row + 1) * o.height / rows));
    panel.width = x1 - panel.x;
    panel.height = y1 - panel.y;
    if (panel.width < 1 || panel.height < 1)
      throw ValueError("image too small for the requested views");
    const ViewSpec& v = o.views[static_cast<std::size_t>(i)];
    panel.label = v.label;
    panel.camera = fit_camera(v.elevation, v.azimuth, m.bounds, static_cast<double>(panel.width) / panel.height,
                              o.view_up, o.zoom);
    detail::PanelParams params;
    params.camera = panel.camera;
    params.rect = {panel.x, panel.y, panel.width, panel.height};
    params.style = o.style;
    params.bg_top = o.background_top;
    params.bg_bottom = o.background_bottom;
    params.span = m.span;
    params.ink_diameter = frame.ink_diameter;
    params.show_axes = o.show_axes;
    params.threads = threads;
    detail::draw_panel(scene, params, target, panel.axes_tips);
    frame.panels.push_back(std::move(panel));
  }
}

// An anchor is visible when the nearest surface at (or next to) its pixel is not in front of it.
void resolve_anchors(const RenderOptions& o, Frame& frame, double span) {
  const double tol = o.occlusion_tolerance * span;
  for (Panel& panel : frame.panels) {
    for (const Vec3& a : o.anchors) {
      AnchorResult r = panel.project(a);
      if (r.in_view) {
        const int px = static_cast<int>(std::floor(r.x)), py = static_cast<int>(std::floor(r.y));
        for (int dy = -1; dy <= 1 && !r.visible; ++dy)
          for (int dx = -1; dx <= 1; ++dx) {
            const int x = px + dx, y = py + dy;
            if (x < panel.x || y < panel.y || x >= panel.x + panel.width || y >= panel.y + panel.height)
              continue;
            if (frame.depth[static_cast<std::size_t>(y) * static_cast<std::size_t>(o.width) +
                            static_cast<std::size_t>(x)] >= r.depth - tol) {
              r.visible = true;
              break;
            }
          }
      }
      panel.anchors.push_back(r);
    }
  }
}

}  // namespace

Frame render_scene(const Scene& scene, const RenderOptions& o) {
  validate_options(o);
  const auto t0 = Clock::now();
  const int ss = o.supersample;
  const int threads = o.threads > 0 ? o.threads : default_threads();

  Frame frame;
  frame.width = o.width;
  frame.height = o.height;
  const std::size_t out_px = static_cast<std::size_t>(o.width) * static_cast<std::size_t>(o.height);
  frame.depth.assign(out_px, std::numeric_limits<float>::infinity());
  frame.mesh_id.assign(out_px, -1);
  frame.face_id.assign(out_px, -1);

  // The rasteriser draws into a supersampled RGBA buffer; depth and ids are written at output resolution.
  detail::Target target;
  target.ss = ss;
  target.width = o.width;
  target.height = o.height;
  target.ss_width = o.width * ss;
  target.ss_height = o.height * ss;
  std::vector<std::uint8_t> big(static_cast<std::size_t>(target.ss_width) * static_cast<std::size_t>(target.ss_height) *
                                4);
  target.rgba = big.data();
  target.depth = frame.depth.data();
  target.mesh_id = frame.mesh_id.data();
  target.face_id = frame.face_id.data();
  fill_window_background(big, o.style);

  const SceneMeasures measures = measure_scene(scene, o, frame);
  draw_panels(scene, o, frame, target, measures, threads);
  frame.render_ms = ms_since(t0);

  const auto t1 = Clock::now();
  frame.rgba.resize(out_px * 4);
  detail::reduce(big.data(), target.ss_width, target.ss_height, ss, o.resolve, frame.rgba.data(), threads);
  frame.resolve_ms = ms_since(t1);

  resolve_anchors(o, frame, measures.span);
  if (!o.want_ids) {
    frame.mesh_id.clear();
    frame.face_id.clear();
  }
  return frame;
}

}  // namespace scad::render
