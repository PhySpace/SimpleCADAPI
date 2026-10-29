// Rasteriser: visibility per band of rows, deferred Phong shading, depth-tested ink lines and points,
// sorted translucent surfaces, corner axes.  Each band (a few rows of one panel) is private to one
// worker; triangles are visited in index order, so the image does not depend on the thread count.
#include <algorithm>
#include <cmath>
#include <limits>

#include "internal.hpp"

namespace scad::render::detail {
namespace {

constexpr std::uint32_t kNone = 0xFFFFFFFFu;
constexpr float kInf = std::numeric_limits<float>::infinity();

// ---------------------------------------------------------------------------
// Lighting
// ---------------------------------------------------------------------------
struct PowLut {
  std::vector<float> table;
  explicit PowLut(double power) : table(4097) {
    for (std::size_t i = 0; i < table.size(); ++i)
      table[i] = static_cast<float>(std::pow(static_cast<double>(i) / 4096.0, power));
  }
  float operator()(float x) const {
    const float f = std::clamp(x, 0.0f, 1.0f) * 4096.0f;
    const int i = std::min(4095, static_cast<int>(f));
    const float t = f - static_cast<float>(i);
    return table[static_cast<std::size_t>(i)] * (1.0f - t) + table[static_cast<std::size_t>(i) + 1] * t;
  }
};

struct Light {
  float dir[3];  // unit vector toward the light
  float rgb[3];  // colour * intensity
};

struct Material {
  float ka, kd, ks;
  float spec[3];  // specular colour; negative first entry = use the surface colour (vtkProperty::SetColor sets it too)
  const PowLut* lut;
};

struct Lighting {
  std::vector<Light> lights;
  float view[3];  // toward the eye
  PowLut standard_lut{28.0}, studio_lut{45.0};
  Material standard{0.24f, 0.72f, 0.22f, {-1, 0, 0}, &standard_lut};
  Material studio{0.17f, 0.62f, 0.50f, {1.0f, 0.97f, 0.92f}, &studio_lut};
};

Lighting make_lighting(const Camera& cam, Style style) {
  Lighting l;
  const Vec3 view = -cam.forward;
  l.view[0] = static_cast<float>(view.x);
  l.view[1] = static_cast<float>(view.y);
  l.view[2] = static_cast<float>(view.z);
  auto add = [&](const Vec3& dir, std::array<float, 3> color, float intensity) {
    const Vec3 d = dir.normalized();
    l.lights.push_back({{static_cast<float>(d.x), static_cast<float>(d.y), static_cast<float>(d.z)},
                        {color[0] * intensity, color[1] * intensity, color[2] * intensity}});
  };
  if (style == Style::Standard) {
    add(view, {1, 1, 1}, 1.0f);  // VTK's automatic headlight
    return l;
  }
  // render.py _studio_lights: warm key, cool fill, cool rim, derived from the camera pose.
  const Vec3 world_up{0, 0, 1};
  Vec3 right = view.cross(world_up);
  right = right / std::max(right.norm(), 1e-9);
  const Vec3 up = right.cross(view);
  add(view * 0.55 + right * 0.60 + up * 0.70, {1.00f, 0.96f, 0.90f}, 1.55f);
  add(view * 0.35 - right * 0.95 + up * 0.05, {0.60f, 0.70f, 0.85f}, 0.68f);
  add(-view * 0.90 + up * 0.60 - right * 0.15, {0.88f, 0.93f, 1.00f}, 1.05f);
  return l;
}

// ---------------------------------------------------------------------------
// Scene views
// ---------------------------------------------------------------------------
struct MeshView {
  const float* v;
  const float* n;
  const std::uint32_t* tri;
  const std::uint32_t* fid;
  const MeshStyle* style;
  std::uint32_t tri_count;
  std::uint32_t index;
  const Material* material;
  bool translucent;
};

struct Tri {
  float x[3], y[3], z[3];
  double A[3], B[3], C[3];  // barycentric weight i = A*px + B*py + C
  int x0, x1, y0, y1;       // inclusive pixel bounds
  std::uint32_t mesh, index;
  float bias;
};

struct Seg {
  float x0, y0, z0, x1, y1, z1;
  float hw, bias;
  std::uint8_t rgb[3];
  int x_lo, x_hi, y_lo, y_hi;
};

struct Csr {
  std::vector<std::uint32_t> offsets, items;
  void build(int bands, int band_h, const std::vector<std::pair<int, int>>& ranges) {
    offsets.assign(static_cast<std::size_t>(bands) + 1, 0);
    for (const auto& r : ranges)
      for (int b = r.first / band_h; r.first <= r.second && b <= r.second / band_h && b < bands; ++b)
        ++offsets[static_cast<std::size_t>(b) + 1];
    for (int b = 0; b < bands; ++b)
      offsets[static_cast<std::size_t>(b) + 1] += offsets[static_cast<std::size_t>(b)];
    items.resize(offsets.back());
    std::vector<std::uint32_t> cursor(offsets.begin(), offsets.end() - 1);
    for (std::size_t i = 0; i < ranges.size(); ++i) {
      const auto& r = ranges[i];
      for (int b = r.first / band_h; r.first <= r.second && b <= r.second / band_h && b < bands; ++b)
        items[cursor[static_cast<std::size_t>(b)]++] = static_cast<std::uint32_t>(i);
    }
  }
};

inline std::uint8_t to_u8(float v) {
  return static_cast<std::uint8_t>(std::clamp(v, 0.0f, 1.0f) * 255.0f + 0.5f);
}

// ---------------------------------------------------------------------------
// Triangle setup
// ---------------------------------------------------------------------------
struct Screen {
  const Camera* cam;
  double pw, ph, sx, sy;
  void operator()(const float* p, float& x, float& y, float& z) const {
    const Vec3 d{p[0] - cam->target.x, p[1] - cam->target.y, p[2] - cam->target.z};
    x = static_cast<float>(pw * (0.5 + d.dot(cam->right) * sx));
    y = static_cast<float>(ph * (0.5 - d.dot(cam->up) * sy));
    z = static_cast<float>(d.dot(cam->forward));
  }
};

bool setup_tri(const MeshView& m, std::uint32_t t, const Screen& screen, int pw, int ph, float bias, Tri& out) {
  const std::uint32_t* idx = m.tri + 3 * static_cast<std::size_t>(t);
  for (int k = 0; k < 3; ++k)
    screen(m.v + 3 * static_cast<std::size_t>(idx[k]), out.x[k], out.y[k], out.z[k]);
  for (int k = 0; k < 3; ++k)
    if (!std::isfinite(out.x[k]) || !std::isfinite(out.y[k]))
      return false;
  const double ax = out.x[0], ay = out.y[0], bx = out.x[1], by = out.y[1], cx = out.x[2], cy = out.y[2];
  const double area2 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
  if (std::abs(area2) < 1e-9)
    return false;
  const double inv = 1.0 / area2;
  // w0 over edge (v1,v2), w1 over (v2,v0), w2 over (v0,v1)
  const double px[3][2] = {{bx, by}, {cx, cy}, {ax, ay}};
  const double qx[3][2] = {{cx, cy}, {ax, ay}, {bx, by}};
  for (int i = 0; i < 3; ++i) {
    const double dx = qx[i][0] - px[i][0], dy = qx[i][1] - px[i][1];
    out.A[i] = -dy * inv;
    out.B[i] = dx * inv;
    out.C[i] = (-dx * px[i][1] + dy * px[i][0]) * inv;
  }
  const float minx = std::min({out.x[0], out.x[1], out.x[2]}), maxx = std::max({out.x[0], out.x[1], out.x[2]});
  const float miny = std::min({out.y[0], out.y[1], out.y[2]}), maxy = std::max({out.y[0], out.y[1], out.y[2]});
  out.x0 = std::max(0, static_cast<int>(std::floor(minx - 0.5f)));
  out.x1 = std::min(pw - 1, static_cast<int>(std::ceil(maxx - 0.5f)));
  out.y0 = std::max(0, static_cast<int>(std::floor(miny - 0.5f)));
  out.y1 = std::min(ph - 1, static_cast<int>(std::ceil(maxy - 0.5f)));
  if (out.x0 > out.x1 || out.y0 > out.y1)
    return false;
  out.mesh = m.index;
  out.index = t;
  out.bias = bias;
  return true;
}

// Calls emit(x, y, z, w1, w2) for every pixel centre inside the triangle on rows [y_lo, y_hi).
template <class Emit>
void raster_tri(const Tri& t, int y_lo, int y_hi, Emit&& emit) {
  constexpr double eps = 1e-9;
  const int ya = std::max(t.y0, y_lo), yb = std::min(t.y1, y_hi - 1);
  for (int y = ya; y <= yb; ++y) {
    const double py = y + 0.5;
    int lo = t.x0, hi = t.x1;
    bool empty = false;
    double k[3];
    for (int i = 0; i < 3 && !empty; ++i) {
      k[i] = t.B[i] * py + t.C[i];
      const double a = t.A[i];
      if (std::abs(a) < 1e-12) {
        if (k[i] < -eps)
          empty = true;
      } else {
        const double bound = (-eps - k[i]) / a - 0.5;  // x such that w_i(x + 0.5) = -eps
        if (a > 0)
          lo = std::max(lo, static_cast<int>(std::floor(bound)) - 1);
        else
          hi = std::min(hi, static_cast<int>(std::ceil(bound)) + 1);
      }
    }
    if (empty)
      continue;
    lo = std::max(lo, t.x0);
    hi = std::min(hi, t.x1);
    for (int x = lo; x <= hi; ++x) {
      const double px = x + 0.5;
      const double w0 = t.A[0] * px + k[0], w1 = t.A[1] * px + k[1], w2 = t.A[2] * px + k[2];
      if (w0 < -eps || w1 < -eps || w2 < -eps)
        continue;
      const float z = static_cast<float>(w0 * t.z[0] + w1 * t.z[1] + w2 * t.z[2]) - t.bias;
      emit(x, y, z, static_cast<float>(w1), static_cast<float>(w2));
    }
  }
}

// Calls emit(x, y, z) for pixel centres within the capsule of the segment.
template <class Emit>
void raster_seg(const Seg& s, int y_lo, int y_hi, Emit&& emit) {
  const double dx = s.x1 - s.x0, dy = s.y1 - s.y0;
  const double len2 = dx * dx + dy * dy;
  const double r2 = static_cast<double>(s.hw) * s.hw;
  const int ya = std::max(s.y_lo, y_lo), yb = std::min(s.y_hi, y_hi - 1);
  for (int y = ya; y <= yb; ++y) {
    const double py = y + 0.5;
    for (int x = s.x_lo; x <= s.x_hi; ++x) {
      const double px = x + 0.5;
      double t = len2 > 0 ? ((px - s.x0) * dx + (py - s.y0) * dy) / len2 : 0.0;
      t = std::clamp(t, 0.0, 1.0);
      const double ex = px - (s.x0 + t * dx), ey = py - (s.y0 + t * dy);
      if (ex * ex + ey * ey > r2)
        continue;
      emit(x, y, static_cast<float>(s.z0 + t * (s.z1 - s.z0)) - s.bias);
    }
  }
}

// ---------------------------------------------------------------------------
// Shading
// ---------------------------------------------------------------------------
void shade(const MeshView& m, std::uint32_t t, float w1, float w2, const Lighting& lighting, float out[3],
           float* alpha) {
  const std::uint32_t* idx = m.tri + 3 * static_cast<std::size_t>(t);
  const float w0 = 1.0f - w1 - w2;
  const float* n0 = m.n + 3 * static_cast<std::size_t>(idx[0]);
  const float* n1 = m.n + 3 * static_cast<std::size_t>(idx[1]);
  const float* n2 = m.n + 3 * static_cast<std::size_t>(idx[2]);
  float n[3] = {w0 * n0[0] + w1 * n1[0] + w2 * n2[0], w0 * n0[1] + w1 * n1[1] + w2 * n2[1],
                w0 * n0[2] + w1 * n1[2] + w2 * n2[2]};
  float len2 = n[0] * n[0] + n[1] * n[1] + n[2] * n[2];
  if (len2 < 1e-12f) {  // no normals from the mesher: use the flat triangle normal
    const float* p0 = m.v + 3 * static_cast<std::size_t>(idx[0]);
    const float* p1 = m.v + 3 * static_cast<std::size_t>(idx[1]);
    const float* p2 = m.v + 3 * static_cast<std::size_t>(idx[2]);
    const float a[3] = {p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]},
                b[3] = {p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]};
    n[0] = a[1] * b[2] - a[2] * b[1];
    n[1] = a[2] * b[0] - a[0] * b[2];
    n[2] = a[0] * b[1] - a[1] * b[0];
    len2 = n[0] * n[0] + n[1] * n[1] + n[2] * n[2];
  }
  const float inv = len2 > 0 ? 1.0f / std::sqrt(len2) : 0.0f;
  n[0] *= inv;
  n[1] *= inv;
  n[2] *= inv;
  const float* v = lighting.view;
  if (n[0] * v[0] + n[1] * v[1] + n[2] * v[2] < 0) {
    n[0] = -n[0];
    n[1] = -n[1];
    n[2] = -n[2];
  }

  Rgb base = m.style->color;
  float a = 1.0f;
  const std::uint32_t face = m.fid[t];
  if (face < m.style->face_colors.size()) {
    const Rgba& fc = m.style->face_colors[face];
    if (!std::isnan(fc[3])) {
      base = {fc[0], fc[1], fc[2]};
      a = fc[3];
    }
  }
  if (alpha)
    *alpha = a * m.style->opacity;
  if (!m.style->lit) {
    out[0] = base[0];
    out[1] = base[1];
    out[2] = base[2];
    return;
  }
  const Material& mat = *m.material;
  float diffuse[3] = {0, 0, 0}, specular[3] = {0, 0, 0};
  for (const Light& l : lighting.lights) {
    const float ndl = n[0] * l.dir[0] + n[1] * l.dir[1] + n[2] * l.dir[2];
    if (ndl <= 0)
      continue;
    for (int c = 0; c < 3; ++c)
      diffuse[c] += ndl * l.rgb[c];
    const float r[3] = {2 * ndl * n[0] - l.dir[0], 2 * ndl * n[1] - l.dir[1], 2 * ndl * n[2] - l.dir[2]};
    const float rv = r[0] * v[0] + r[1] * v[1] + r[2] * v[2];
    if (rv > 0) {
      const float s = (*mat.lut)(rv);
      for (int c = 0; c < 3; ++c)
        specular[c] += s * l.rgb[c];
    }
  }
  for (int c = 0; c < 3; ++c)
    out[c] = std::clamp(base[static_cast<std::size_t>(c)] * (mat.ka + mat.kd * diffuse[c]) +
                            mat.ks * (mat.spec[0] < 0 ? base[static_cast<std::size_t>(c)] : mat.spec[c]) * specular[c],
                        0.0f, 1.0f);
}

}  // namespace

// ---------------------------------------------------------------------------
// One panel
// ---------------------------------------------------------------------------
namespace {

// Pixel geometry of one panel in supersampled (ss) units, shared by all stages of draw_panel.
struct PanelGeom {
  int ss, pw, ph;  // supersample factor, panel size in ss pixels
  int ox, oy;      // panel origin in the target, ss pixels
  int band_h, bands;
};

// Address of the RGBA pixel (x, y) of the panel inside the supersampled target.
std::uint8_t* target_px(const Target& T, const PanelGeom& g, int x, int y) {
  return T.rgba + (static_cast<std::size_t>(g.oy + y) * static_cast<std::size_t>(T.ss_width) +
                   static_cast<std::size_t>(g.ox + x)) *
                      4;
}

std::vector<MeshView> make_mesh_views(const Scene& scene, const Lighting& lighting) {
  std::vector<MeshView> views;
  views.reserve(scene.meshes().size());
  for (std::size_t i = 0; i < scene.meshes().size(); ++i) {
    const auto& e = scene.meshes()[i];
    const io::Mesh& mesh = *e.mesh;
    const Material* mat = e.style.studio_material ? &lighting.studio : &lighting.standard;
    views.push_back({mesh.vertices.data(), mesh.normals.data(), mesh.triangles.data(), mesh.face_ids.data(), &e.style,
                     static_cast<std::uint32_t>(mesh.triangle_count()), static_cast<std::uint32_t>(i), mat,
                     e.style.opacity < 0.999f});
  }
  return views;
}

// Projects every triangle (in parallel chunks, concatenated in mesh/triangle order so the result does
// not depend on the thread count) into screen space; translucent ones are sorted far to near.
void setup_triangles(const std::vector<MeshView>& views, const PanelParams& P, const Screen& screen, const PanelGeom& g,
                     std::vector<Tri>& opaque, std::vector<Tri>& translucent) {
  constexpr std::uint32_t chunk = 8192;
  for (int pass = 0; pass < 2; ++pass) {
    std::vector<std::pair<std::size_t, std::uint32_t>> jobs;  // (mesh, first triangle)
    for (std::size_t i = 0; i < views.size(); ++i)
      if (views[i].translucent == (pass == 1))
        for (std::uint32_t t = 0; t < views[i].tri_count; t += chunk)
          jobs.push_back({i, t});
    std::vector<std::vector<Tri>> parts(jobs.size());
    parallel_for(static_cast<int>(jobs.size()), P.threads, [&](int j) {
      const MeshView& m = views[jobs[static_cast<std::size_t>(j)].first];
      const std::uint32_t first = jobs[static_cast<std::size_t>(j)].second;
      // Bias grows with the mesh index: z is eye distance, so on coplanar overlaps the later mesh wins.
      const float bias = static_cast<float>(2e-6 * P.span * m.index);
      auto& out = parts[static_cast<std::size_t>(j)];
      Tri tri;
      for (std::uint32_t t = first; t < std::min(first + chunk, m.tri_count); ++t)
        if (setup_tri(m, t, screen, g.pw, g.ph, bias, tri))
          out.push_back(tri);
    });
    auto& dst = pass == 0 ? opaque : translucent;
    for (auto& p : parts)
      dst.insert(dst.end(), p.begin(), p.end());
  }
  // Far to near; ties by original order, so the blend is deterministic.
  std::stable_sort(translucent.begin(), translucent.end(),
                   [](const Tri& a, const Tri& b) { return (a.z[0] + a.z[1] + a.z[2]) > (b.z[0] + b.z[1] + b.z[2]); });
}

// Appends one capsule segment (points are degenerate segments); culled when it misses the panel.
void add_seg(std::vector<Seg>& segs, const Screen& screen, const PanelGeom& g, const float* a, const float* b,
             double width_px_ss, float bias, const Rgb& color) {
  Seg s{};
  float za, zb;
  screen(a, s.x0, s.y0, za);
  screen(b, s.x1, s.y1, zb);
  s.z0 = za;
  s.z1 = zb;
  s.hw = static_cast<float>(std::max(0.5, width_px_ss * 0.5));
  s.bias = bias;
  for (int c = 0; c < 3; ++c)
    s.rgb[c] = to_u8(color[static_cast<std::size_t>(c)]);
  const float r = s.hw + 1.0f;
  s.x_lo = std::max(0, static_cast<int>(std::floor(std::min(s.x0, s.x1) - r)));
  s.x_hi = std::min(g.pw - 1, static_cast<int>(std::ceil(std::max(s.x0, s.x1) + r)));
  s.y_lo = std::max(0, static_cast<int>(std::floor(std::min(s.y0, s.y1) - r)));
  s.y_hi = std::min(g.ph - 1, static_cast<int>(std::ceil(std::max(s.y0, s.y1) + r)));
  if (s.x_lo > s.x_hi || s.y_lo > s.y_hi)
    return;
  segs.push_back(s);
}

// Ink lines (width and depth bias from the line style, the panel ink diameter, or one pixel) and points.
std::vector<Seg> collect_segments(const Scene& scene, const PanelParams& P, const Screen& screen, const PanelGeom& g,
                                  double px_per_world) {
  std::vector<Seg> segs;
  for (const auto& entry : scene.lines()) {
    const LineStyle& st = entry.style;
    double width_ss;
    float bias;
    if (st.width_world < 0.0 && P.ink_diameter > 0.0) {
      width_ss = P.ink_diameter * px_per_world;
      bias = static_cast<float>(st.depth_bias.value_or(P.ink_diameter * 0.5));
    } else if (st.width_world > 0.0) {
      width_ss = st.width_world * px_per_world;
      bias = static_cast<float>(st.depth_bias.value_or(st.width_world * 0.5));
    } else {
      width_ss = st.width_world < 0.0 ? g.ss : st.width_px * g.ss;
      bias = static_cast<float>(st.depth_bias.value_or(0.001 * P.span));
    }
    const auto& L = entry.lines;
    for (std::size_t p = 0; p < L.count(); ++p)
      for (std::uint32_t k = L.starts[p]; k + 1 < L.starts[p + 1]; ++k)
        add_seg(segs, screen, g, &L.points[3 * static_cast<std::size_t>(k)],
                &L.points[3 * static_cast<std::size_t>(k) + 3], width_ss, bias, st.color);
  }
  for (const auto& entry : scene.points())
    for (std::size_t k = 0; k + 2 < entry.xyz.size(); k += 3)
      add_seg(segs, screen, g, &entry.xyz[k], &entry.xyz[k], entry.style.size_px * g.ss,
              static_cast<float>(0.002 * P.span), entry.style.color);
  return segs;
}

// Everything the per-band worker reads; all members outlive the parallel_for.
struct BandInputs {
  const PanelParams& P;
  const Target& T;
  const PanelGeom& g;
  const Lighting& lighting;
  const std::vector<MeshView>& views;
  const std::vector<Tri>& opaque;
  const std::vector<Tri>& translucent;
  const std::vector<Seg>& segs;
  const Csr& opaque_bins;
  const Csr& translucent_bins;
  const Csr& seg_bins;
  Rgb top, bottom;
};

// Background gradient (bottom -> top) for rows [y0, y1).
void fill_background(const BandInputs& in, int y0, int y1) {
  const PanelGeom& g = in.g;
  for (int y = y0; y < y1; ++y) {
    const float f = 1.0f - (static_cast<float>(y) + 0.5f) / static_cast<float>(g.ph);  // 0 at the bottom
    std::uint8_t c[3];
    for (int k = 0; k < 3; ++k)
      c[k] = to_u8(in.bottom[static_cast<std::size_t>(k)] +
                   (in.top[static_cast<std::size_t>(k)] - in.bottom[static_cast<std::size_t>(k)]) * f);
    std::uint8_t* row = target_px(in.T, g, 0, y);
    for (int x = 0; x < g.pw; ++x) {
      row[4 * x] = c[0];
      row[4 * x + 1] = c[1];
      row[4 * x + 2] = c[2];
      row[4 * x + 3] = 255;
    }
  }
}

// Output-resolution depth and ids: the centre sample of each ss x ss block.
void write_depth_and_ids(const BandInputs& in, int y0, int y1, const std::vector<float>& depth,
                         const std::vector<std::uint32_t>& id) {
  const PanelGeom& g = in.g;
  const Target& T = in.T;
  const int ss = g.ss, fw = in.P.rect.w;  // fw: panel width in output pixels
  for (int fy = y0 / ss; fy < y1 / ss; ++fy) {
    const int local_row = fy * ss + ss / 2 - y0;
    for (int fx = 0; fx < fw; ++fx) {
      const std::size_t p = static_cast<std::size_t>(local_row) * static_cast<std::size_t>(g.pw) +
                            static_cast<std::size_t>(fx * ss + ss / 2);
      const std::size_t o = static_cast<std::size_t>(in.P.rect.y + fy) * static_cast<std::size_t>(T.width) +
                            static_cast<std::size_t>(in.P.rect.x + fx);
      T.depth[o] = depth[p];
      if (id[p] == kNone) {
        T.mesh_id[o] = -1;
        T.face_id[o] = -1;
      } else {
        const Tri& t = in.opaque[id[p]];
        T.mesh_id[o] = static_cast<std::int32_t>(t.mesh);
        T.face_id[o] = static_cast<std::int32_t>(in.views[t.mesh].fid[t.index]);
      }
    }
  }
}

// Renders one band of rows: background, opaque visibility + deferred shading, ink, translucent blend.
void render_band(const BandInputs& in, int band) {
  const PanelGeom& g = in.g;
  const int pw = g.pw;
  const int y0 = band * g.band_h, y1 = std::min(g.ph, y0 + g.band_h), rows = y1 - y0;
  thread_local std::vector<float> depth, bw1, bw2;
  thread_local std::vector<std::uint32_t> id;
  const std::size_t count = static_cast<std::size_t>(rows) * static_cast<std::size_t>(pw);
  depth.assign(count, kInf);
  id.assign(count, kNone);
  bw1.resize(count);
  bw2.resize(count);

  fill_background(in, y0, y1);

  // visibility
  for (std::uint32_t k = in.opaque_bins.offsets[static_cast<std::size_t>(band)];
       k < in.opaque_bins.offsets[static_cast<std::size_t>(band) + 1]; ++k) {
    const std::uint32_t ti = in.opaque_bins.items[k];
    raster_tri(in.opaque[ti], y0, y1, [&](int x, int y, float z, float w1, float w2) {
      const std::size_t p =
          static_cast<std::size_t>(y - y0) * static_cast<std::size_t>(pw) + static_cast<std::size_t>(x);
      if (z < depth[p]) {
        depth[p] = z;
        id[p] = ti;
        bw1[p] = w1;
        bw2[p] = w2;
      }
    });
  }
  // shading
  for (int y = y0; y < y1; ++y) {
    std::uint8_t* row = target_px(in.T, g, 0, y);
    for (int x = 0; x < pw; ++x) {
      const std::size_t p =
          static_cast<std::size_t>(y - y0) * static_cast<std::size_t>(pw) + static_cast<std::size_t>(x);
      if (id[p] == kNone)
        continue;
      const Tri& t = in.opaque[id[p]];
      float rgb[3];
      shade(in.views[t.mesh], t.index, bw1[p], bw2[p], in.lighting, rgb, nullptr);
      for (int c = 0; c < 3; ++c)
        row[4 * x + c] = to_u8(rgb[c]);
    }
  }
  // ink lines and points: depth-tested against the surfaces, no depth writes
  for (std::uint32_t k = in.seg_bins.offsets[static_cast<std::size_t>(band)];
       k < in.seg_bins.offsets[static_cast<std::size_t>(band) + 1]; ++k) {
    const Seg& s = in.segs[in.seg_bins.items[k]];
    raster_seg(s, y0, y1, [&](int x, int y, float z) {
      const std::size_t p =
          static_cast<std::size_t>(y - y0) * static_cast<std::size_t>(pw) + static_cast<std::size_t>(x);
      if (z > depth[p])
        return;
      std::uint8_t* px = target_px(in.T, g, x, y);
      px[0] = s.rgb[0];
      px[1] = s.rgb[1];
      px[2] = s.rgb[2];
    });
  }
  // translucent surfaces, far to near
  for (std::uint32_t k = in.translucent_bins.offsets[static_cast<std::size_t>(band)];
       k < in.translucent_bins.offsets[static_cast<std::size_t>(band) + 1]; ++k) {
    const Tri& t = in.translucent[in.translucent_bins.items[k]];
    raster_tri(t, y0, y1, [&](int x, int y, float z, float w1, float w2) {
      const std::size_t p =
          static_cast<std::size_t>(y - y0) * static_cast<std::size_t>(pw) + static_cast<std::size_t>(x);
      if (z >= depth[p])
        return;
      float rgb[3], a;
      shade(in.views[t.mesh], t.index, w1, w2, in.lighting, rgb, &a);
      std::uint8_t* px = target_px(in.T, g, x, y);
      for (int c = 0; c < 3; ++c)
        px[c] = to_u8(static_cast<float>(px[c]) / 255.0f * (1.0f - a) + rgb[c] * a);
    });
  }
  if (in.T.depth)
    write_depth_and_ids(in, y0, y1, depth, id);
}

std::vector<std::pair<int, int>> tri_ranges(const std::vector<Tri>& tris) {
  std::vector<std::pair<int, int>> r;
  r.reserve(tris.size());
  for (const Tri& t : tris)
    r.push_back({t.y0, t.y1});
  return r;
}

// vtkAxesActor look-alike: three capsule-built arrows in a 20% viewport, drawn over the finished panel.
void draw_corner_axes(const PanelParams& P, const Target& T, const PanelGeom& g,
                      std::array<std::array<double, 2>, 3>& axes_tips) {
  const Camera& cam = P.camera;
  const int ss = g.ss, pw = g.pw, ph = g.ph;
  const int aw = static_cast<int>(std::lround(pw * 0.2)), ah = static_cast<int>(std::lround(ph * 0.2));
  const int ax0 = pw - aw, ay0 = ph - ah;
  const double ppw = ah / 2.0;  // pixels per world unit: half_height 1
  const Vec3 axes[3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
  const Rgb colors[3] = {{1.0f, 0.0f, 0.0f}, {0.0f, 1.0f, 0.0f}, {0.0f, 0.0f, 1.0f}};
  int order[3] = {0, 1, 2};
  std::sort(order, order + 3, [&](int a, int b) { return axes[a].dot(cam.forward) > axes[b].dot(cam.forward); });
  for (int i : order) {
    const double u = axes[i].dot(cam.right) / (2.0 * (static_cast<double>(aw) / ah)), v = axes[i].dot(cam.up) / 2.0;
    const float cx = static_cast<float>(ax0 + aw * (0.5 + u)), cy = static_cast<float>(ay0 + ah * (0.5 - v));
    const float ox0 = static_cast<float>(ax0 + aw * 0.5), oy0 = static_cast<float>(ay0 + ah * 0.5);
    axes_tips[static_cast<std::size_t>(i)] = {(P.rect.x * ss + static_cast<double>(cx)) / ss,
                                              (P.rect.y * ss + static_cast<double>(cy)) / ss};
    // shaft to 80%, then a cone approximated by four shrinking capsules
    for (int part = 0; part < 5; ++part) {
      const float f0 = part == 0 ? 0.0f : 0.8f + 0.05f * static_cast<float>(part - 1);
      const float f1 = part == 0 ? 0.8f : f0 + 0.05f;
      const double width = part == 0 ? 0.08 : 0.17 * (1.0 - 0.22 * (part - 1));
      Seg s{};
      s.x0 = ox0 + (cx - ox0) * f0;
      s.y0 = oy0 + (cy - oy0) * f0;
      s.x1 = ox0 + (cx - ox0) * f1;
      s.y1 = oy0 + (cy - oy0) * f1;
      s.hw = static_cast<float>(std::max(0.5, width * ppw * 0.5));
      for (int c = 0; c < 3; ++c)
        s.rgb[c] = to_u8(colors[i][static_cast<std::size_t>(c)]);
      s.x_lo = std::max(0, static_cast<int>(std::floor(std::min(s.x0, s.x1) - s.hw - 1)));
      s.x_hi = std::min(pw - 1, static_cast<int>(std::ceil(std::max(s.x0, s.x1) + s.hw + 1)));
      s.y_lo = std::max(0, static_cast<int>(std::floor(std::min(s.y0, s.y1) - s.hw - 1)));
      s.y_hi = std::min(ph - 1, static_cast<int>(std::ceil(std::max(s.y0, s.y1) + s.hw + 1)));
      raster_seg(s, 0, ph, [&](int x, int y, float) {
        std::uint8_t* px = target_px(T, g, x, y);
        px[0] = s.rgb[0];
        px[1] = s.rgb[1];
        px[2] = s.rgb[2];
      });
    }
  }
}

}  // namespace

void draw_panel(const Scene& scene, const PanelParams& P, const Target& T,
                std::array<std::array<double, 2>, 3>& axes_tips) {
  const int ss = T.ss;
  const int pw = P.rect.w * ss, ph = P.rect.h * ss;
  const int band_h = 8 * ss;
  const PanelGeom g{ss, pw, ph, P.rect.x * ss, P.rect.y * ss, band_h, (ph + band_h - 1) / band_h};
  const Camera& cam = P.camera;
  const Screen screen{&cam, static_cast<double>(pw), static_cast<double>(ph),
                      1.0 / (2.0 * cam.half_height * cam.aspect), 1.0 / (2.0 * cam.half_height)};
  const double px_per_world = ph / (2.0 * cam.half_height);
  const Lighting lighting = make_lighting(cam, P.style);

  // Backgrounds are drawn per band.
  const Rgb top = P.bg_top ? *P.bg_top : (P.style == Style::Studio ? Rgb{0, 0, 0} : Rgb{0.78f, 0.84f, 0.90f});
  const Rgb bottom = P.bg_bottom ? *P.bg_bottom : (P.style == Style::Studio ? Rgb{0, 0, 0} : Rgb{0.94f, 0.96f, 0.98f});

  const std::vector<MeshView> views = make_mesh_views(scene, lighting);
  std::vector<Tri> opaque, translucent;
  setup_triangles(views, P, screen, g, opaque, translucent);
  Csr opaque_bins, translucent_bins, seg_bins;
  opaque_bins.build(g.bands, band_h, tri_ranges(opaque));
  translucent_bins.build(g.bands, band_h, tri_ranges(translucent));

  const std::vector<Seg> segs = collect_segments(scene, P, screen, g, px_per_world);
  {
    std::vector<std::pair<int, int>> r;
    r.reserve(segs.size());
    for (const Seg& s : segs)
      r.push_back({s.y_lo, s.y_hi});
    seg_bins.build(g.bands, band_h, r);
  }

  const BandInputs in{P,        T,   g,     lighting, views, opaque, translucent, segs, opaque_bins, translucent_bins,
                      seg_bins, top, bottom};
  parallel_for(g.bands, P.threads, [&](int band) { render_band(in, band); });

  if (P.show_axes)
    draw_corner_axes(P, T, g, axes_tips);
}

}  // namespace scad::render::detail
