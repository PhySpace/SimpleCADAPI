// Shared by the renderer's translation units.  Not installed.
#pragma once

#include <atomic>
#include <cstdint>
#include <thread>
#include <vector>

#include "scad/render/render.hpp"

namespace scad::render::detail {

// Runs f(i) for i in [0, n) on `threads` workers, items handed out dynamically.  f must only touch
// state private to item i (or disjoint output), which is what makes results independent of `threads`.
template <class F>
void parallel_for(int n, int threads, F&& f) {
  if (n <= 0) return;
  threads = std::max(1, std::min(threads, n));
  if (threads == 1) {
    for (int i = 0; i < n; ++i) f(i);
    return;
  }
  std::atomic<int> next{0};
  auto worker = [&] {
    for (int i = next.fetch_add(1); i < n; i = next.fetch_add(1)) f(i);
  };
  std::vector<std::thread> pool;
  pool.reserve(static_cast<std::size_t>(threads - 1));
  for (int t = 1; t < threads; ++t) pool.emplace_back(worker);
  worker();
  for (auto& t : pool) t.join();
}

struct Rect {
  int x = 0, y = 0, w = 0, h = 0;
};

// The full-window target of one render call.  `rgba` is at supersampled resolution; depth/ids at output
// resolution (one sample per ss x ss block: the centre one).
struct Target {
  int ss = 1;
  int ss_width = 0, ss_height = 0;
  int width = 0, height = 0;
  std::uint8_t* rgba = nullptr;
  float* depth = nullptr;
  std::int32_t* mesh_id = nullptr;
  std::int32_t* face_id = nullptr;
};

struct PanelParams {
  Camera camera;
  Rect rect;                 // output pixels
  Style style = Style::Studio;
  std::optional<Rgb> bg_top, bg_bottom;
  double span = 1.0;         // scene span (ink radius, tolerances)
  double ink_diameter = 0.0;
  bool show_axes = false;
  int threads = 1;
};

// Draws the panel: background, surfaces, lines, points, translucent surfaces, axes.
void draw_panel(const Scene& scene, const PanelParams& params, const Target& target, std::array<std::array<double, 2>, 3>& axes_tips);

// PIL-compatible reduction of an RGBA8 image by an integer factor.
void reduce(const std::uint8_t* src, int src_w, int src_h, int factor, Resolve mode, std::uint8_t* dst, int threads);

}  // namespace scad::render::detail
