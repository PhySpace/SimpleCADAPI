// Software renderer for the 3D layer of the SDK's inspection screenshots.
//
// Orthographic z-buffered triangles with per-face colors, Phong lighting
// (VTK's headlight for the "standard" style, the key/fill/rim rig of the
// "studio" style), B-rep edges as depth-tested "ink" lines, n x n
// supersampling with PIL's Lanczos reduction, a grid of panels, a depth buffer
// and a per-pixel (mesh, face) id buffer.  Text (titles, legends, callout
// labels) is not drawn here: the result carries the projected anchor points
// with their visibility so the caller can place labels on top.
//
// Determinism: every pixel is computed by exactly one worker from the same
// ordered triangle list, so the output is bit-identical for any thread count.
//
// No OCP/VTK anywhere: tessellation is scad::io::mesh, edges are discretised
// here with BRepAdaptor_Curve / GCPnts.
#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <TopoDS_Shape.hxx>

#include "scad/core/vec.hpp"
#include "scad/io/mesh.hpp"

namespace scad::render {

using Rgb = std::array<float, 3>;
using Rgba = std::array<float, 4>;

struct Bounds {
  Vec3 min{0, 0, 0};
  Vec3 max{0, 0, 0};
  bool valid = false;
  void add(const Vec3& p);
  void add(const Bounds& other);
  Vec3 center() const { return (min + max) * 0.5; }
  Vec3 spans() const { return max - min; }
  double span() const;  // largest extent
};

// ---------------------------------------------------------------------------
// Camera (render.py _set_camera + vtkRenderer::ResetCamera + Zoom(0.92))
// ---------------------------------------------------------------------------
struct Camera {
  Vec3 target;
  Vec3 right, up, forward;  // orthonormal; forward points from the eye into the scene
  double half_height = 1.0;  // world units from the image centre to its top edge
  double aspect = 1.0;       // width / height

  Vec3 eye(double distance) const { return target - forward * distance; }
  // Image position in [0,1]^2 (x right, y DOWN, like pixels) and the distance along `forward`.
  struct Projected { double x, y, depth; };
  Projected project(const Vec3& p) const;
};

// Preset name -> (elevation, azimuth) degrees.  Throws ValueError for unknown names.
std::pair<double, double> view_preset(std::string_view name);
// "auto": elevation 22 or 35 by the spans, azimuth 35 or 125 (_screenshot_view_angles).
std::pair<double, double> auto_view(const Vec3& spans);

// `zoom` multiplies the standard 0.92 fit (1 = SDK default for a grid panel; a
// single-view screenshot passes zoom_param / 4).
Camera fit_camera(double elevation_deg, double azimuth_deg, const Bounds& bounds, double aspect,
                  const std::optional<Vec3>& view_up = std::nullopt, double zoom = 1.0);

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------
enum class Style { Standard, Studio };

struct MeshStyle {
  Rgb color{0.55f, 0.64f, 0.73f};
  float opacity = 1.0f;
  bool studio_material = false;  // ambient .17 / diffuse .62 / specular .5 power 45 instead of .24/.72/.22/28
  bool lit = true;
  // Optional colour per face id (rgba; NaN alpha = use `color`).  Alpha multiplies the opacity.
  std::vector<Rgba> face_colors;
};

struct LineStyle {
  Rgb color{0.16f, 0.21f, 0.27f};
  // width_world > 0: explicit world diameter; < 0: "ink" (diameter = 2 * edge_width_scale * scene span, the
  // tube radius of the VTK path); 0: `width_px` in OUTPUT pixels.
  double width_world = 0.0;
  double width_px = 1.0;
  // Lines are pulled toward the camera by this much (world) when depth-tested;
  // the default for ink is its radius, for pixel lines 0.1% of the scene span.
  std::optional<double> depth_bias;
};

struct PointStyle {
  Rgb color{0.78f, 0.0f, 0.0f};
  double size_px = 15.0;  // output pixels, round
};

struct Polylines {
  std::vector<float> points;           // xyz
  std::vector<std::uint32_t> starts;   // polyline i = points[starts[i], starts[i+1]); size = count + 1
  std::size_t count() const { return starts.empty() ? 0 : starts.size() - 1; }
};

// B-rep edges of `shape` (each unique edge once, degenerate ones skipped),
// discretised with the given chord deflection (render.py caps it at 0.04), or
// `sample_count` uniform parameter samples when positive.
Polylines edge_polylines(const TopoDS_Shape& shape, double deflection = 0.04, int sample_count = 0);

class Scene {
 public:
  // Returns the mesh index (the value in the id buffer).
  int add_mesh(std::shared_ptr<const io::Mesh> mesh, MeshStyle style = {});
  int add_lines(Polylines lines, LineStyle style = {});
  int add_points(std::vector<float> xyz, PointStyle style = {});
  // Tessellate + extract edges in one go.  Returns the mesh index.
  int add_shape(const TopoDS_Shape& shape, MeshStyle style = {}, const io::MeshParameters& mesh_parameters = {},
                bool edges = true, const LineStyle& edge_style = {});

  Bounds bounds() const;
  std::size_t mesh_count() const { return meshes_.size(); }
  std::size_t triangle_count() const;

  struct MeshEntry { std::shared_ptr<const io::Mesh> mesh; MeshStyle style; };
  struct LineEntry { Polylines lines; LineStyle style; };
  struct PointEntry { std::vector<float> xyz; PointStyle style; };
  const std::vector<MeshEntry>& meshes() const { return meshes_; }
  const std::vector<LineEntry>& lines() const { return lines_; }
  const std::vector<PointEntry>& points() const { return points_; }

 private:
  std::vector<MeshEntry> meshes_;
  std::vector<LineEntry> lines_;
  std::vector<PointEntry> points_;
};

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
struct ViewSpec {
  double elevation = 28.0;
  double azimuth = -45.0;
  std::string label;
};

enum class Resolve { Lanczos, Box };

struct RenderOptions {
  int width = 1400;
  int height = 900;
  int supersample = 2;  // 1..4
  Style style = Style::Studio;
  std::vector<ViewSpec> views{{28.0, -45.0, "isometric"}};  // grid: min(2, n) columns
  // Width of the strip on the right reserved for a legend (fraction of the image); panels use the rest.
  double legend_panel_fraction = 0.0;
  std::optional<Vec3> view_up;
  double zoom = 1.0;
  // Ink radius as a fraction of the scene span (render.py edge_width_scale) for line sets with
  // width_world < 0.  <= 0 draws those as 1 px lines.
  double edge_width_scale = 0.0019;
  bool show_axes = false;
  std::optional<Rgb> background_top, background_bottom;
  Resolve resolve = Resolve::Lanczos;
  int threads = 0;  // 0 = hardware concurrency
  // World points whose projection/visibility is wanted in every panel.
  std::vector<Vec3> anchors;
  double occlusion_tolerance = 0.002;  // fraction of the scene span (render.py _view_ray_occluded)
  bool want_ids = true;
};

struct AnchorResult {
  double x = 0, y = 0;   // output pixels (full image, y down)
  double depth = 0;
  bool in_view = false;
  bool visible = false;  // in view and not behind the nearest surface at its pixel
};

struct Panel {
  int x = 0, y = 0, width = 0, height = 0;  // output pixels, y down
  Camera camera;
  std::string label;
  std::vector<AnchorResult> anchors;
  std::array<std::array<double, 2>, 3> axes_tips{};  // output px of the +X/+Y/+Z tips (when show_axes)
  // Output-pixel position of a world point in this panel.
  AnchorResult project(const Vec3& p) const;
};

struct Frame {
  int width = 0, height = 0;
  std::vector<std::uint8_t> rgba;     // height * width * 4, row 0 = top
  std::vector<float> depth;           // height * width, distance along the view; +inf = background
  std::vector<std::int32_t> mesh_id;  // -1 = background
  std::vector<std::int32_t> face_id;  // face id inside that mesh, -1 = none
  std::vector<Panel> panels;
  double ink_diameter = 0;            // world
  double render_ms = 0, resolve_ms = 0;
};

Frame render_scene(const Scene& scene, const RenderOptions& options);

// Number of worker threads `threads = 0` resolves to.
int default_threads();

}  // namespace scad::render
