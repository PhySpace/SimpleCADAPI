// Why a loft failed: the section compatibility check of _diagnostics.py.  The kernel reports a
// bare "build did not complete"; re-reading the sections gives verdicts it never names.
#include <TopoDS.hxx>

#include <algorithm>
#include <array>
#include <cmath>
#include <set>

#include "probes.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ops/features/diagnostics.hpp"
#include "scad/ops/features/support.hpp"

namespace scad {

namespace {

using features_detail::vector_display;

// What the probe reads off one section.
struct SectionFacts {
  std::string id;  // "S1", "S2", ...
  int edge_count = 0;  // 0: a vertex cap
  std::optional<bool> closed;
  std::optional<bool> planar;
  Vec3 centroid;
};

using Symmetric3 = std::array<std::array<double, 3>, 3>;

// The eigenvalues of a symmetric 3x3 matrix by cyclic Jacobi rotations, ascending.
std::array<double, 3> eigenvalues(Symmetric3 a) {
  for (int sweep = 0; sweep < 32; ++sweep) {
    const double off = std::abs(a[0][1]) + std::abs(a[0][2]) + std::abs(a[1][2]);
    if (off < 1e-300) break;
    for (std::size_t p = 0; p < 2; ++p) {
      for (std::size_t q = p + 1; q < 3; ++q) {
        if (std::abs(a[p][q]) < 1e-300) continue;
        const double theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q]);
        const double t = (theta >= 0 ? 1.0 : -1.0) / (std::abs(theta) + std::sqrt(theta * theta + 1.0));
        const double c = 1.0 / std::sqrt(t * t + 1.0), s = t * c;
        for (std::size_t k = 0; k < 3; ++k) {
          const double akp = a[k][p], akq = a[k][q];
          a[k][p] = c * akp - s * akq;
          a[k][q] = s * akp + c * akq;
        }
        for (std::size_t k = 0; k < 3; ++k) {
          const double apk = a[p][k], aqk = a[q][k];
          a[p][k] = c * apk - s * aqk;
          a[q][k] = s * apk + c * aqk;
        }
      }
    }
  }
  std::array<double, 3> values{a[0][0], a[1][1], a[2][2]};
  std::sort(values.begin(), values.end());
  return values;
}

// Planar when the out-of-plane spread (the smallest singular value of the centred samples) is
// negligible next to the in-plane extent.  Fewer than three samples have no such spread.
std::optional<bool> is_planar(const std::vector<Vec3>& points, const Vec3& centroid) {
  if (points.size() < 3) return std::nullopt;
  Symmetric3 covariance{};
  for (const Vec3& p : points) {
    const std::array<double, 3> d{p.x - centroid.x, p.y - centroid.y, p.z - centroid.z};
    for (std::size_t i = 0; i < 3; ++i)
      for (std::size_t j = 0; j < 3; ++j) covariance[i][j] += d[i] * d[j];
  }
  const std::array<double, 3> values = eigenvalues(covariance);
  const double largest = std::sqrt(std::max(values[2], 0.0)), smallest = std::sqrt(std::max(values[0], 0.0));
  return smallest <= std::max(largest, 1e-12) * 1e-6;
}

std::optional<SectionFacts> section_facts(const Shape& section, std::size_t index) {
  SectionFacts facts;
  facts.id = "S" + std::to_string(index + 1);
  if (section.kind() == Kind::Vertex) {
    facts.centroid = kernel::vertex_point(TopoDS::Vertex(section.wrapped()));
    return facts;
  }
  if (section.kind() != Kind::Wire) return std::nullopt;
  const std::vector<TopoDS_Edge> edges = kernel::edges_of(section.wrapped());
  std::vector<Vec3> points;
  for (const TopoDS_Edge& edge : edges) {
    for (const Vec3& p : features_detail::sample_edge_polyline(edge)) points.push_back(p);
  }
  if (points.empty()) return std::nullopt;
  Vec3 sum;
  for (const Vec3& p : points) sum += p;
  facts.centroid = sum / static_cast<double>(points.size());
  facts.edge_count = static_cast<int>(edges.size());
  facts.closed = Wire(section).is_closed();
  facts.planar = is_planar(points, facts.centroid);
  return facts;
}

std::string g3(double value) { return general_format(value, 3); }

}  // namespace

void raise_loft_failure_if_diagnosed(const std::vector<Shape>& sections, std::string_view operation) {
  std::vector<SectionFacts> facts;
  try {
    for (std::size_t i = 0; i < sections.size(); ++i) {
      const std::optional<SectionFacts> one = section_facts(sections[i], i);
      if (!one) return;
      facts.push_back(*one);
    }
  } catch (const std::exception&) {
    return;  // a diagnosis never replaces the error it explains
  }
  if (facts.size() < 2) return;

  std::vector<std::string> findings, repair;
  std::set<std::string> implicated;

  // Coincident consecutive stations: the usual cause of "did not complete" when sections were
  // authored at the same height.
  for (std::size_t i = 0; i + 1 < facts.size(); ++i) {
    const SectionFacts &a = facts[i], &b = facts[i + 1];
    const double distance = a.centroid.distance(b.centroid);
    if (distance > 1e-9) continue;
    findings.push_back(b.id + " coincides with " + a.id + " (centroid distance " + g3(distance) + " mm)");
    implicated.insert({a.id, b.id});
    repair.push_back(a.id + " and " + b.id +
                     " sit at the same location: a loft needs its sections distributed along the generation direction "
                     "\xE2\x80\x94 remove the duplicate section or fix the station placements");
  }

  // Correspondence-based skinning needs comparable station topology.
  std::vector<const SectionFacts*> wires;
  for (const SectionFacts& fact : facts) {
    if (fact.edge_count > 0) wires.push_back(&fact);
  }
  if (!wires.empty()) {
    std::set<int> counts;
    for (const SectionFacts* fact : wires) counts.insert(fact->edge_count);
    if (counts.size() > 1) {
      std::string described;
      for (const SectionFacts* fact : wires) {
        described += (described.empty() ? "" : ", ") + fact->id + "=" + std::to_string(fact->edge_count);
        implicated.insert(fact->id);
      }
      findings.push_back("edge counts differ across stations: " + described);
      repair.push_back("Make the edge count consistent across stations (split or approximate curve stations when mixing "
                       "with straight-line stations), or split the loft at stations where the topology undergoes "
                       "birth/death/split/merge");
    }
  }

  // A solid loft needs closed loops.
  for (const SectionFacts* fact : wires) {
    if (fact->closed != std::optional<bool>(false)) continue;
    findings.push_back(fact->id + " is not closed");
    implicated.insert(fact->id);
    repair.push_back(fact->id + " is an open wire: close that section before lofting");
  }

  // Station order: project the centroids on the first-to-last axis; any backtrack is out of order.
  const Vec3 first = facts.front().centroid, last = facts.back().centroid;
  const double axis_norm = first.distance(last);
  if (axis_norm > 1e-9 && facts.size() > 2) {
    const Vec3 axis = last - first;
    std::vector<double> projections;
    for (const SectionFacts& fact : facts) projections.push_back((fact.centroid - first).dot(axis) / axis_norm);
    std::vector<std::string> backtracks;
    for (std::size_t i = 1; i < projections.size(); ++i) {
      if (projections[i] < projections[i - 1] - 1e-9) backtracks.push_back(facts[i].id);
    }
    if (!backtracks.empty()) {
      std::string joined;
      for (const std::string& id : backtracks) joined += (joined.empty() ? "" : ", ") + id;
      findings.push_back("section centroids backtrack along the first-to-last axis (likely out of order): " + joined);
      implicated.insert(backtracks.begin(), backtracks.end());
      repair.push_back(joined + " step backwards along the generation direction: reorder the section list");
    }
  }

  if (findings.empty()) return;

  std::vector<InventoryEntry> inventory;
  for (const SectionFacts& fact : facts) {
    const std::string description =
        fact.edge_count == 0
            ? "vertex cap, at " + vector_display(fact.centroid)
            : std::to_string(fact.edge_count) + " edges, " + (fact.closed.value_or(false) ? "closed" : "OPEN") + ", " +
                  (fact.planar.value_or(false) ? "planar" : "non-planar") + ", centroid " + vector_display(fact.centroid);
    inventory.push_back({fact.id, implicated.count(fact.id) != 0 ? "implicated" : "ok", description});
  }

  std::string what = "the " + std::string(operation) + " kernel build did not complete; the section compatibility check found: ";
  for (std::size_t i = 0; i < findings.size(); ++i) what += (i == 0 ? "" : "; ") + findings[i];
  const ErrorSpec spec{std::string(operation),
                       what,
                       {"Two adjacent sections sit at the same location (no generation direction to skin across).",
                        "Edge counts differ too much across stations for the kernel to establish point correspondence.",
                        "A section is open, or the list order disagrees with the generation direction."},
                       {"Check every station against its Inventory row (edges / closure / centroid)."}};
  raise_harness_error(spec, "kernel reported: loft build did not complete; section count=" + std::to_string(facts.size()),
                      {}, std::move(repair), std::move(inventory));
}

}  // namespace scad
