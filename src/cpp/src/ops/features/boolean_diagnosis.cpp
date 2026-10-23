// Why a boolean failed: separated operands, or contact without volume (_diagnostics.py).
#include <algorithm>
#include <map>
#include <numeric>

#include "probes.hpp"
#include "scad/kernel/booleans.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ops/features/diagnostics.hpp"
#include "scad/ops/features/support.hpp"

namespace scad {

namespace {

using features_detail::ClosestApproach;
using features_detail::vector_display;

constexpr std::size_t kMaxPairProbes = 256;  // the quadratic probe is capped, not allowed to hang the failure path

std::string g4(double value) { return general_format(value, 4); }

Vec3 closure_vector(const ClosestApproach& approach) { return approach.point_b - approach.point_a; }

BooleanDiagnosis disjoint_diagnosis(const std::vector<Solid>& operands, std::size_t index_a, std::size_t index_b,
                                    const ClosestApproach& approach, double tol, std::string_view kind) {
  const std::string label_a = "operand " + std::to_string(index_a + 1), label_b = "operand " + std::to_string(index_b + 1);
  const Vec3 move = closure_vector(approach);
  BooleanDiagnosis out;
  out.failure_kind = "disjoint";
  out.what_happened = "separated solids: " + label_a + " and " + label_b + " never touch; nearest detected gap is " +
                      g4(approach.gap) + " mm (tolerance " + g4(tol) + ")";
  if (kind == "cut") {
    out.possible_causes = {"The tool never reaches the base solid, so the cut removes nothing.",
                           "A placement/translation moved the tool away from the base solid."};
    out.repair = {"Move the tool " + label_b + " by " + vector_display(move) + " (\xE2\x89\xA5 " + g4(approach.gap) +
                      " mm) so it reaches inside the base solid, or extend the tool across the gap.",
                  "Check the intended removal region: with this gap the cut is a no-op on the base solid."};
  } else if (kind == "intersect") {
    out.possible_causes = {"The operands are separated in space, so the intersection is empty.",
                           "A placement/translation moved one operand away from the other."};
    out.repair = {"Move " + label_b + " by " + vector_display(move) + " (\xE2\x89\xA5 " + g4(approach.gap) +
                  " mm) so the operands share a positive-volume overlap."};
  } else {
    out.possible_causes = {"The operands are separated in space, so the union cannot produce exactly one solid.",
                           "A placement/translation moved one operand away from the other."};
    out.repair = {"Move " + label_b + " by " + vector_display(move) + " (\xE2\x89\xA5 " + g4(approach.gap) +
                      " mm) so the operands touch, or extend one operand across the gap.",
                  "If the pieces are meant to stay separate, build an assembly (make_assembly_rassembly) instead of a "
                  "single-solid union."};
  }
  out.measurements = {{"min_gap", approach.gap, "mm"},
                      {"closest_point_a", approach.point_a.array(), "mm"},
                      {"closest_point_b", approach.point_b.array(), "mm"},
                      {"closure_vector_a_to_b", move.array(), "mm"}};
  out.evidence_shapes = {operands[index_a], operands[index_b]};
  out.evidence_caption = label_a + " and " + label_b + "; nearest gap " + g4(approach.gap) +
                         " mm between the two closest points (see measurements)";
  return out;
}

BooleanDiagnosis contact_diagnosis(const Solid& solid_a, const Solid& solid_b, const ClosestApproach& approach,
                                   double tol, std::string_view kind) {
  const Vec3 move = closure_vector(approach);
  BooleanDiagnosis out;
  out.failure_kind = "non_manifold_contact";
  out.what_happened = "operands meet only along an edge, vertex, or tangent (measured gap " + g4(approach.gap) +
                      " mm \xE2\x89\xA4 tol " + g4(tol) + "), which is not one manifold solid";
  out.possible_causes = {"The operands touch without a finite-area face or positive-volume overlap."};
  out.measurements = {{"min_gap", approach.gap, "mm"},
                      {"closest_point_a", approach.point_a.array(), "mm"},
                      {"closest_point_b", approach.point_b.array(), "mm"}};
  if (kind == "cut") {
    out.repair = {"The tool only grazes the base solid; translate the tool along " + vector_display(move) +
                  " by a working depth (e.g. 0.5 mm beyond touch) so it removes real volume."};
  } else if (kind == "intersect") {
    out.repair = {"The operands only graze each other; translate one along " + vector_display(move) +
                  " by a working depth (e.g. 0.5 mm beyond touch) to create a positive-volume overlap."};
  } else {
    out.repair = {"Give the contact a positive-volume overlap: translate one operand along " + vector_display(move) +
                      " by a working overlap (e.g. 0.5 mm beyond touch) and retry.",
                  "For intended face contact, make the shared face finite in area and coincident; no artificial "
                  "overlap is required."};
  }
  out.evidence_shapes = {solid_a, solid_b};
  out.evidence_caption = "operand 1 and operand 2 in edge/vertex/tangent-only contact";
  return out;
}

// Positive-volume intersection of two shapes; 0 when they are disjoint or merely touch.
double overlap_volume(const TopoDS_Shape& a, const TopoDS_Shape& b) {
  try {
    double total = 0.0;
    for (const TopoDS_Solid& solid : kernel::solids_of(kernel::common_shapes({a, b}))) total += kernel::volume(solid);
    return total;
  } catch (const std::exception&) {
    return 0.0;
  }
}

// Operands within `tol` of each other form one cluster (transitively).
class Clusters {
 public:
  explicit Clusters(std::size_t count) : parent_(count) { std::iota(parent_.begin(), parent_.end(), std::size_t{0}); }
  std::size_t find(std::size_t node) {
    while (parent_[node] != node) {
      parent_[node] = parent_[parent_[node]];
      node = parent_[node];
    }
    return node;
  }
  void join(std::size_t a, std::size_t b) {
    const std::size_t root_a = find(a), root_b = find(b);
    if (root_a != root_b) parent_[root_a] = root_b;
  }
  std::size_t count() {
    std::size_t roots = 0;
    for (std::size_t i = 0; i < parent_.size(); ++i) roots += find(i) == i ? 1 : 0;
    return roots;
  }

 private:
  std::vector<std::size_t> parent_;
};

}  // namespace

std::optional<BooleanDiagnosis> diagnose_boolean_failure(const std::vector<Solid>& operands,
                                                         std::optional<double> effective_tol,
                                                         std::string_view operation_kind) {
  try {
    const std::size_t count = operands.size();
    if (count < 2) return std::nullopt;
    const double tol = effective_tol.value_or(0.0);
    // Unprobed pairs might connect the clusters, so a nearest-pair claim could misattribute.
    if (count * (count - 1) / 2 > kMaxPairProbes) return std::nullopt;

    std::map<std::pair<std::size_t, std::size_t>, ClosestApproach> approaches;
    for (std::size_t i = 0; i < count; ++i) {
      for (std::size_t j = i + 1; j < count; ++j) {
        if (const auto approach = features_detail::closest_approach(operands[i].wrapped(), operands[j].wrapped())) {
          approaches.emplace(std::make_pair(i, j), *approach);
        }
      }
    }

    Clusters clusters(count);
    for (const auto& [pair, approach] : approaches) {
      if (approach.gap <= tol) clusters.join(pair.first, pair.second);
    }

    if (clusters.count() > 1) {
      const std::pair<const std::pair<std::size_t, std::size_t>, ClosestApproach>* best = nullptr;
      for (const auto& entry : approaches) {
        if (clusters.find(entry.first.first) == clusters.find(entry.first.second)) continue;
        if (best == nullptr || entry.second.gap < best->second.gap) best = &entry;
      }
      if (best == nullptr) return std::nullopt;
      return disjoint_diagnosis(operands, best->first.first, best->first.second, best->second, tol, operation_kind);
    }

    for (const auto& [pair, approach] : approaches) {
      if (approach.gap <= tol && overlap_volume(operands[pair.first].wrapped(), operands[pair.second].wrapped()) < 1e-12) {
        return contact_diagnosis(operands[pair.first], operands[pair.second], approach, tol, operation_kind);
      }
    }
    return std::nullopt;
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

}  // namespace scad
