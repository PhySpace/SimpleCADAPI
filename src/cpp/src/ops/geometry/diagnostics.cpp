#include "scad/ops/geometry/diagnostics.hpp"
#include "scad/topo/diagnostic_image.hpp"

#include <algorithm>
#include <cmath>
#include <array>
#include <cstdio>
#include <limits>
#include <numeric>
#include <string>
#include <vector>

#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/topology.hpp"

namespace scad {

namespace {

struct EdgeEnds {
  Vec3 start, end;
};

// Both end points of an edge, in explorer order; nullopt for a degenerate edge.
std::optional<EdgeEnds> edge_ends(const Edge& edge) {
  std::vector<Vec3> points;
  for (TopExp_Explorer explorer(edge.wrapped(), TopAbs_VERTEX); explorer.More() && points.size() < 2; explorer.Next()) {
    points.push_back(kernel::vertex_point(TopoDS::Vertex(explorer.Current())));
  }
  if (points.size() != 2) return std::nullopt;
  return EdgeEnds{points[0], points[1]};
}

std::string four_digits(double value) {
  char buffer[32];
  std::snprintf(buffer, sizeof buffer, "%.4g", value);
  return buffer;
}

std::string vector_display(const Vec3& v) {
  return "(" + four_digits(v.x) + ", " + four_digits(v.y) + ", " + four_digits(v.z) + ")";
}

struct Dangling {
  std::size_t edge;
  Vec3 point;
};

// Disjoint-set over the edges: two edges join when an end of one matches an end of the other.
class Chains {
 public:
  explicit Chains(std::size_t count) : parent_(count) { std::iota(parent_.begin(), parent_.end(), std::size_t{0}); }
  std::size_t find(std::size_t index) {
    while (parent_[index] != index) {
      parent_[index] = parent_[parent_[index]];
      index = parent_[index];
    }
    return index;
  }
  void join(std::size_t a, std::size_t b) {
    const std::size_t root_a = find(a), root_b = find(b);
    if (root_a != root_b) parent_[root_a] = root_b;
  }
  int count() {
    int roots = 0;
    for (std::size_t i = 0; i < parent_.size(); ++i) roots += find(i) == i ? 1 : 0;
    return roots;
  }

 private:
  std::vector<std::size_t> parent_;
};

}  // namespace

std::optional<WireGapDiagnosis> diagnose_open_wire(const Wire& wire) {
  try {
    const std::vector<Edge> edges = wire.edges();
    if (edges.empty()) return std::nullopt;
    std::vector<EdgeEnds> ends;
    ends.reserve(edges.size());
    for (const Edge& edge : edges) {
      const std::optional<EdgeEnds> probed = edge_ends(edge);
      if (!probed) return std::nullopt;
      ends.push_back(*probed);
    }

    // Matching tolerance: the kernel precision scaled to the wire's extent, floored so a
    // single tiny edge still chains.
    double lowest = std::numeric_limits<double>::infinity(), highest = -lowest;
    for (const EdgeEnds& e : ends) {
      for (const Vec3& p : {e.start, e.end}) {
        for (const double v : {p.x, p.y, p.z}) {
          lowest = std::min(lowest, v);
          highest = std::max(highest, v);
        }
      }
    }
    const double tolerance = std::max(std::max(highest - lowest, 1e-9) * 1e-6, 1e-9);

    const auto end_of = [&](std::size_t edge, int end) -> const Vec3& { return end == 0 ? ends[edge].start : ends[edge].end; };
    std::vector<std::array<bool, 2>> matched(edges.size(), {false, false});
    Chains chains(edges.size());
    for (std::size_t a = 0; a < edges.size(); ++a) {
      for (int end_a = 0; end_a < 2; ++end_a) {
        for (std::size_t b = a + 1; b < edges.size(); ++b) {
          for (int end_b = 0; end_b < 2; ++end_b) {
            const auto ia = static_cast<std::size_t>(end_a), ib = static_cast<std::size_t>(end_b);
            if (!matched[a][ia] && !matched[b][ib] && end_of(a, end_a).distance(end_of(b, end_b)) <= tolerance) {
              matched[a][ia] = matched[b][ib] = true;
              chains.join(a, b);
            }
          }
        }
      }
    }

    std::vector<Dangling> dangling;
    for (std::size_t edge = 0; edge < edges.size(); ++edge) {
      for (int end = 0; end < 2; ++end) {
        if (!matched[edge][static_cast<std::size_t>(end)]) dangling.push_back({edge, end_of(edge, end)});
      }
    }
    if (dangling.size() < 2) return std::nullopt;

    // The closest dangling pair; a lone segment's own two ends are a legitimate pair.
    double best = std::numeric_limits<double>::infinity();
    std::size_t first = 0, second = 1;
    for (std::size_t a = 0; a < dangling.size(); ++a) {
      for (std::size_t b = a + 1; b < dangling.size(); ++b) {
        const double distance = dangling[a].point.distance(dangling[b].point);
        if (distance < best) {
          best = distance;
          first = a;
          second = b;
        }
      }
    }
    return WireGapDiagnosis{best,
                            dangling[first].point,
                            dangling[second].point,
                            static_cast<int>(edges.size()),
                            chains.count(),
                            static_cast<int>(dangling.size())};
  } catch (const std::exception&) {
    return std::nullopt;  // best effort: the caller degrades to a closedness-only message
  }
}

void raise_open_wire_failure(std::string_view operation, const Wire& wire, std::string_view purpose) {
  const std::optional<WireGapDiagnosis> diagnosis = diagnose_open_wire(wire);
  std::vector<ErrorMeasurement> measurements;
  std::vector<std::string> repair;
  std::vector<ErrorEvidence> evidence;
  std::string what_happened = "the given wire is not closed, so it cannot be used to " + std::string(purpose);

  if (diagnosis) {
    const std::string p1 = vector_display(diagnosis->point_a), p2 = vector_display(diagnosis->point_b);
    measurements = {{"gap", diagnosis->gap_distance, "mm"},
                    {"gap end P1", diagnosis->point_a.array(), "mm"},
                    {"gap end P2", diagnosis->point_b.array(), "mm"},
                    {"edge count", static_cast<double>(diagnosis->edge_count), ""}};
    repair.push_back("the gap is " + four_digits(diagnosis->gap_distance) + " mm between " + p1 + " and " + p2 +
                     ": add a segment (or arc) across the two ends to close the profile, then retry");
    if (diagnosis->chain_count > 1) {
      measurements.push_back({"chain count", static_cast<double>(diagnosis->chain_count), ""});
      repair.push_back("the wire splits into " + std::to_string(diagnosis->chain_count) +
                       " disconnected chains — check for missing connecting geometry first instead of only "
                       "patching the shortest gap");
    }
    if (diagnosis->dangling_count > 2) {
      repair.push_back("there are " + std::to_string(diagnosis->dangling_count) +
                       " dangling endpoints (more than one opening): close each of them before you " +
                       std::string(purpose));
    }
    what_happened += "; measured gap " + four_digits(diagnosis->gap_distance) + " mm";
    // A picture of the wire with its two loose ends marked (best effort: no provider, no picture).
    DiagnosticImage image;
    image.kind = "wire_plan_render";
    image.operation = std::string(operation);
    image.view = "best-fit plane projection";
    image.caption = "orange edges mark the gap ends: " + four_digits(diagnosis->gap_distance) + " mm apart at " + p1 +
                    " <-> " + p2;
    image.dedup_key = std::string(operation) + "|open_wire|" + four_digits(diagnosis->gap_distance);
    image.shapes = {wire};
    Value marks = Value::array();
    for (const auto& [point, label] : {std::pair<Vec3, const char*>{diagnosis->point_a, "P1"}, {diagnosis->point_b, "P2"}}) {
      Value mark = Value::object();
      Value coordinates = Value::array();
      for (const double component : point.array()) coordinates.push_back(Value(component));
      mark.set("point", std::move(coordinates));
      mark.set("label", std::string(label));
      mark.set("tone", "highlight");
      marks.push_back(std::move(mark));
    }
    image.payload.set("marks", std::move(marks));
    if (auto picture = diagnostic_image(image)) evidence.push_back(std::move(*picture));
  } else {
    repair.push_back("check that the wire's endpoints meet head-to-tail in order");
  }

  const ErrorSpec spec{std::string(operation),
                       what_happened,
                       {"The wire's endpoints do not meet head-to-tail, leaving a gap.",
                        "The wire consists of several disconnected pieces.",
                        "A sketch profile was promoted before it was closed."},
                       {"Locate the gap ends from the P1/P2 coordinates in Measurements and bridge them."}};
  raise_harness_error(spec, std::string{}, std::move(measurements), std::move(repair), {}, std::move(evidence));
}

}  // namespace scad
