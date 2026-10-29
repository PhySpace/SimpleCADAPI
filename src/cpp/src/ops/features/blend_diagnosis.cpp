// Why a fillet or chamfer failed: the probes of operators/_diagnostics.py, in its order.
#include <BRepAdaptor_Surface.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopoDS.hxx>

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "probes.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ops/features/diagnostics.hpp"
#include "scad/ops/features/support.hpp"

namespace scad {

namespace {

using features_detail::EdgeFaceAdjacency;
using features_detail::vector_display;

constexpr std::size_t kMaxRerunEdges = 64;  // the per-edge diagnostic rerun budget

struct SizeWords {
  std::string size, blend;  // "radius" / "fillet", "distance" / "leg"
};

SizeWords size_words(std::string_view operation_kind) {
  return operation_kind == "chamfer" ? SizeWords{"distance", "leg"} : SizeWords{"radius", "fillet"};
}

std::string fixed2(double value) {
  char buffer[32];
  std::snprintf(buffer, sizeof buffer, "%.2f", value);
  return buffer;
}

std::string scientific2(double value) {
  char buffer[32];
  std::snprintf(buffer, sizeof buffer, "%.2e", value);
  return buffer;
}

std::string g4(double value) {
  return general_format(value, 4);
}

void add_edge_ends(std::vector<ErrorMeasurement>& measurements, const Edge& edge) {
  if (const auto ends = features_detail::edge_endpoints(edge.wrapped())) {
    measurements.push_back({"edge_start", ends->first.array(), "mm"});
    measurements.push_back({"edge_end", ends->second.array(), "mm"});
  }
}

// What a probe needs to know about the operation, bundled so the probes stay short.
struct Case {
  const Solid& solid;
  const TopoDS_Solid topo_solid;
  const std::vector<Edge>& edges;
  double size_value;
  SizeWords words;
  EdgeFaceAdjacency adjacency;

  Case(const Solid& solid_, const std::vector<Edge>& edges_, double size, std::string_view kind)
      : solid(solid_),
        topo_solid(TopoDS::Solid(solid_.wrapped())),
        edges(edges_),
        size_value(size),
        words(size_words(kind)),
        adjacency(solid_.wrapped()) {}

  const std::vector<TopoDS_Face>* faces_of(const Edge& edge) const { return adjacency.faces_of(edge.wrapped()); }
};

std::optional<BlendDiagnosis> classify_tiny_edges(const Case& c) {
  if (c.edges.size() < 2)
    return std::nullopt;
  std::vector<std::pair<const Edge*, double>> lengths;
  try {
    for (const Edge& edge : c.edges)
      lengths.emplace_back(&edge, edge.length());
  } catch (const std::exception&) {
    return std::nullopt;
  }
  std::vector<double> ordered;
  for (const auto& entry : lengths)
    ordered.push_back(entry.second);
  std::sort(ordered.begin(), ordered.end());
  const double median = ordered[ordered.size() / 2];
  const double threshold = std::max(1e-3, median * 1e-3);  // sub-micron slivers against the selection's scale
  std::size_t tiny = 0;
  double shortest = 0.0;
  const Edge* shortest_edge = nullptr;
  for (const auto& entry : lengths) {
    if (entry.second > threshold)
      continue;
    if (tiny == 0 || entry.second < shortest) {
      shortest = entry.second;
      shortest_edge = entry.first;
    }
    ++tiny;
  }
  if (tiny == 0 || tiny == lengths.size())
    return std::nullopt;

  BlendDiagnosis out;
  out.failure_kind = "sliver_edges_in_selection";
  out.what_happened = std::to_string(tiny) + " of " + std::to_string(c.edges.size()) +
                      " selected edges are slivers (shortest " + scientific2(shortest) + " mm vs selection median " +
                      g4(median) + " mm); the kernel cannot blend degenerate edges";
  out.possible_causes = {"A boolean left splitter debris in the topology and the selection swept it in.",
                         "The selector matched by a property that sliver edges also satisfy."};
  out.measurements = {{"shortest_selected_edge", shortest, "mm"}, {"selection_median_edge", median, "mm"}};
  out.repair = {"Drop the sliver edges from the selection (filter by feature intent, not by a blanket selector).",
                "Re-select with a QL predicate that excludes sub-micron edges before the " + c.words.blend + "."};
  out.evidence_edges = {*shortest_edge};
  out.evidence_caption = "orange line marks the shortest sliver edge; see measurements";
  return out;
}

std::optional<BlendDiagnosis> classify_tangent_adjacency(const Case& c) {
  for (const Edge& edge : c.edges) {
    const auto* faces = c.faces_of(edge);
    if (faces == nullptr || faces->size() < 2)
      continue;
    const auto dihedral =
        features_detail::dihedral_angle_along_edge((*faces)[0], (*faces)[1], TopoDS::Edge(edge.wrapped()));
    if (!dihedral)
      continue;
    // An interior angle near 180 degrees is a smooth junction: the blend wedge has no opening.
    if (std::abs(*dihedral - 180.0) > 1.0)
      continue;

    BlendDiagnosis out;
    out.failure_kind = "tangent_adjacent_faces";
    out.what_happened = "the faces meeting at a selected edge are already tangent (interior angle " +
                        fixed2(*dihedral) + "\xC2\xB0), so the " + c.words.blend +
                        " surface degenerates to zero width for any " + c.words.size;
    out.possible_causes = {
        "The profile or upstream blend produced a smooth (G1) junction; there is no corner for the "
        "blend to fill."};
    out.measurements = {{"dihedral_angle", *dihedral, "deg"}};
    add_edge_ends(out.measurements, edge);
    out.repair = {"Remove that junction edge from the selection: there is no corner to blend.",
                  "If a visual transition is required there, it already exists \xE2\x80\x94 the faces are tangent by "
                  "construction."};
    out.evidence_edges = {edge};
    out.evidence_caption = "orange line marks the tangent junction edge; see measurements";
    return out;
  }
  return std::nullopt;
}

std::optional<BlendDiagnosis> classify_blend_room(const Case& c) {
  for (const Edge& edge : c.edges) {
    const auto* faces = c.faces_of(edge);
    if (faces == nullptr)
      continue;
    for (const TopoDS_Face& face : *faces) {
      const auto extent = features_detail::face_extent_from_edge(face, edge.wrapped());
      // Meeting the room exactly counts: the strip left on the face has no width.
      if (!extent || *extent <= 0 || c.size_value < *extent)
        continue;

      BlendDiagnosis out;
      out.failure_kind = "size_exceeds_face";
      out.what_happened = c.words.size + " " + g4(c.size_value) + " mm meets or exceeds the " + g4(*extent) +
                          " mm of face room between the failing edge and the opposite boundary of an adjacent face";
      out.possible_causes = {
          "The " + c.words.blend + " " + c.words.size + " is larger than the adjacent face can carry.",
          "The selected edge runs along a narrow face."};
      out.measurements = {{c.words.size, c.size_value, "mm"}, {"available_face_room", *extent, "mm"}};
      add_edge_ends(out.measurements, edge);
      out.repair = {"Reduce the " + c.words.size + " to below " + g4(*extent) + " mm (e.g. " + g4(*extent * 0.95) +
                        ") and retry.",
                    "Or select a different edge with more room on its adjacent faces."};
      out.evidence_edges = {edge};
      out.evidence_caption =
          "orange line marks the failing edge; see measurements for its endpoints and the available face room";
      return out;
    }
  }
  return std::nullopt;
}

bool is_selected(const Case& c, const TopoDS_Shape& edge) {
  return std::any_of(c.edges.begin(), c.edges.end(), [&](const Edge& e) { return e.wrapped().IsSame(edge); });
}

std::optional<BlendDiagnosis> classify_partial_smooth_chain(const Case& c) {
  for (const Edge& edge : c.edges) {
    const auto* faces = c.faces_of(edge);
    if (faces == nullptr)
      continue;
    const TopoDS_Edge topo_edge = TopoDS::Edge(edge.wrapped());
    for (const TopoDS_Face& face : *faces) {
      const GeomAbs_SurfaceType type = BRepAdaptor_Surface(face).GetType();
      if (type != GeomAbs_Cylinder && type != GeomAbs_Torus && type != GeomAbs_Sphere)
        continue;
      for (const TopoDS_Shape& other : kernel::explore(face, TopAbs_EDGE)) {
        if (is_selected(c, other) || other.IsSame(topo_edge))
          continue;
        if (!features_detail::edges_tangent_at_shared_vertex(topo_edge, TopoDS::Edge(other)))
          continue;
        BlendDiagnosis out;
        // Without measurable end points the finding is not reported (as in the Python SDK).
        if (!features_detail::edge_endpoints(topo_edge))
          continue;
        out.failure_kind = "partial_smooth_chain_on_periodic_face";
        out.what_happened =
            "the selected edge is one segment of a smooth (tangent) chain on a periodic face "
            "(cylinder/torus/sphere); blending a partial chain fails because the blend cannot end "
            "mid-chain";
        out.possible_causes = {
            "A boolean seam split one smooth intersection curve into several edges and the "
            "selection caught only part of it."};
        add_edge_ends(out.measurements, edge);
        out.repair = {
            "Select the entire smooth chain: every tangent-continuous segment of that curve, then blend them "
            "together in one call.",
            "Enumerate with QL and extend the selection across the shared vertices before retrying."};
        out.evidence_edges = {edge};
        out.evidence_caption = "orange line marks the partially selected chain segment";
        return out;
      }
    }
  }
  return std::nullopt;
}

BlendDiagnosis tangency_critical(const Case& c, const Edge& edge, double extent) {
  BlendDiagnosis out;
  out.failure_kind = "blends_tangency_critical";
  out.what_happened = "adjacent " + c.words.blend + " surfaces meet tangentially: 2\xC3\x97" + c.words.size + " = " +
                      g4(2 * c.size_value) + " mm equals or exceeds the " + g4(extent) +
                      " mm face room between opposite edges, leaving a zero-width face strip (degenerate)";
  out.possible_causes = {"Blending many edges with the same " + c.words.size + " consumes the shared faces entirely.",
                         "The critical size equals half the narrowest adjacent face."};
  out.measurements = {{c.words.size, c.size_value, "mm"},
                      {"combined_blend_width", 2 * c.size_value, "mm"},
                      {"available_face_room", extent, "mm"}};
  add_edge_ends(out.measurements, edge);
  out.repair = {"Reduce the " + c.words.size + " below " + g4(extent / 2) +
                    " mm (half the narrowest shared face) so adjacent blend surfaces leave material between them.",
                "Or blend the edges in two passes with different sizes."};
  out.evidence_edges = {edge};
  out.evidence_caption = "orange line marks the critical edge; see measurements";
  return out;
}

std::optional<BlendDiagnosis> classify_tangency_critical(const Case& c) {
  for (const Edge& edge : c.edges) {
    const auto* faces = c.faces_of(edge);
    if (faces == nullptr)
      continue;
    for (const TopoDS_Face& face : *faces) {
      const auto extent = features_detail::face_extent_from_edge(face, edge.wrapped());
      if (!extent || *extent <= 0)
        continue;
      if (2 * c.size_value >= *extent)
        return tangency_critical(c, edge, *extent);
    }
  }
  return std::nullopt;
}

// Corner blending where several edges converge is the classic kernel failure.
std::optional<BlendDiagnosis> classify_vertex_conflict(const Case& c) {
  struct Corner {
    TopoDS_Shape vertex;
    std::vector<const Edge*> incident;
  };
  std::vector<Corner> corners;  // in first-seen order
  for (const Edge& edge : c.edges) {
    for (const TopoDS_Shape& vertex : kernel::explore(edge.wrapped(), TopAbs_VERTEX)) {
      auto at = std::find_if(corners.begin(), corners.end(), [&](const Corner& k) { return k.vertex.IsSame(vertex); });
      if (at == corners.end())
        at = corners.insert(corners.end(), Corner{vertex, {}});
      at->incident.push_back(&edge);
    }
  }

  for (const Corner& corner : corners) {
    std::vector<bool> convexities;
    for (const Edge* edge : corner.incident) {
      const auto* faces = c.faces_of(*edge);
      if (faces == nullptr || faces->size() < 2)
        continue;
      const auto concave =
          features_detail::edge_is_concave(c.topo_solid, (*faces)[0], (*faces)[1], TopoDS::Edge(edge->wrapped()));
      if (concave)
        convexities.push_back(!*concave);
    }
    const bool mixed = !convexities.empty() && std::any_of(convexities.begin(), convexities.end(),
                                                           [&](bool v) { return v != convexities.front(); });
    // Three alike edges at a corner (a plain box corner) are routine; only crowded or mixed corners explain failures.
    if (corner.incident.size() < 4 && !mixed)
      continue;

    std::string counts = std::to_string(corner.incident.size()) + " selected edges meet at one vertex";
    if (mixed)
      counts += " with mixed convex/concave edges";
    BlendDiagnosis out;
    out.failure_kind = "vertex_blend_conflict";
    out.what_happened =
        counts + "; blending such corners is where the rolling-ball " + c.words.blend + " fails to close";
    out.possible_causes = {"Fillet/chamfer corner vertex with many converging blended edges."};
    if (mixed)
      out.possible_causes.push_back("Convex and concave edges meet at the same vertex.");
    out.measurements = {{"edges_at_vertex", static_cast<double>(corner.incident.size()), ""}};
    out.repair = {
        "Blend the converging edges in separate passes: hardest edges first, then the remainder with a "
        "smaller size.",
        "Or drop the corner edge from this pass and blend it alone afterwards."};
    for (std::size_t i = 0; i < corner.incident.size() && i < 3; ++i)
      out.evidence_edges.push_back(*corner.incident[i]);
    out.evidence_caption = "orange lines mark the edges converging at the corner vertex";
    return out;
  }
  return std::nullopt;
}

}  // namespace

std::optional<BlendDiagnosis> diagnose_blend_failure(const Solid& solid, const std::vector<Edge>& edges,
                                                     double size_value, std::string_view operation_kind,
                                                     const BlendRetry& retry_single) {
  try {
    if (edges.empty())
      return std::nullopt;
    const Case c(solid, edges, size_value, operation_kind);

    if (auto found = classify_tiny_edges(c))
      return found;
    if (auto found = classify_tangent_adjacency(c))
      return found;
    if (auto found = classify_blend_room(c))
      return found;
    if (auto found = classify_partial_smooth_chain(c))
      return found;

    if (retry_single && edges.size() > 1 && edges.size() <= kMaxRerunEdges) {
      // An edge that fails alone should have been explained above: stay silent rather than guess.
      if (std::any_of(edges.begin(), edges.end(), [&](const Edge& edge) { return !retry_single(edge); }))
        return std::nullopt;
    }

    if (auto found = classify_tangency_critical(c))
      return found;
    // The generic corner conflict goes last: three convex edges at a box corner are routine and
    // must not shadow a specific explanation.
    return classify_vertex_conflict(c);
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

// ---------------------------------------------------------------------------
// The exit check
// ---------------------------------------------------------------------------
namespace {

// True only when every selected edge is provably convex: a concave edge legitimately gains
// material, and an edge that cannot be judged means the check cannot prove impossibility.
bool all_edges_convex(const Solid& solid, const std::vector<Edge>& edges) {
  const TopoDS_Solid topo_solid = TopoDS::Solid(solid.wrapped());
  const EdgeFaceAdjacency adjacency(solid.wrapped());
  for (const Edge& edge : edges) {
    const auto* faces = adjacency.faces_of(edge.wrapped());
    if (faces == nullptr || faces->size() < 2)
      return false;
    const auto concave =
        features_detail::edge_is_concave_side_probe(topo_solid, (*faces)[0], (*faces)[1], TopoDS::Edge(edge.wrapped()));
    if (!concave || *concave)
      return false;
  }
  return true;
}

std::string size_text(std::optional<double> size_value) {
  return size_value ? python_float_repr(*size_value) : "None";
}

}  // namespace

void assert_blend_volume_monotonic(const Solid& source, const Solid& result, std::string_view operation_kind,
                                   std::optional<double> size_value, const std::vector<Edge>& edges) {
  // A blend removes a visible share of the volume: when a quick estimate is clearly on the
  // legitimate side of both thresholds, the precise volumes cannot change the verdict (they are
  // only needed for the message when it throws).
  try {
    const double quick_source = kernel::volume_estimate(source.wrapped());
    const double quick_result = kernel::volume_estimate(result.wrapped());
    const double margin = 1e-3 * std::abs(quick_source);
    if (quick_source > 0.0 && quick_result > margin && quick_result < quick_source - margin)
      return;
  } catch (const std::exception&) {
    // fall through to the precise measurement
  }
  double source_volume = 0.0, result_volume = 0.0;
  try {
    source_volume = kernel::volume(source.wrapped());
    result_volume = kernel::volume(result.wrapped());
  } catch (const std::exception&) {
    return;  // never block a legitimate result because a measurement could not be taken
  }
  const std::string where =
      " (size=" + size_text(size_value) + ", selected_edges=" + std::to_string(edges.size()) + ")";
  if (result_volume <= 0.0) {
    throw BlendVolumeViolation(std::string(operation_kind) + " result volume is " + general_format(result_volume, 6) +
                               ": the kernel returned an empty/degenerate solid" + where);
  }
  const double tolerance = std::max(1e-9, std::abs(source_volume) * 1e-6);
  if (result_volume > source_volume + tolerance && all_edges_convex(source, edges)) {
    throw BlendVolumeViolation(std::string(operation_kind) + " result volume " + general_format(result_volume, 6) +
                               " exceeds the input volume " + general_format(source_volume, 6) +
                               ": the blend can only remove material, so the kernel silently returned degenerate "
                               "geometry" +
                               where);
  }
}

}  // namespace scad
