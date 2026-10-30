#include "scad/sketch/diagnostics.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <set>

#include "scad/core/error.hpp"
#include "scad/sketch/sketch.hpp"
#include "scad/topo/diagnostic_image.hpp"

namespace scad {

namespace {

// Inventory caps: the failed set and its partners are the actionable signal;
// satisfied constraints collapse into a single count row beyond this window.
constexpr std::size_t kMaxRelatedConstraints = 8;
constexpr std::size_t kMaxInventoryOkRows = 8;

std::string general(double value) {
  char buffer[64];
  std::snprintf(buffer, sizeof buffer, "%.4g", value);
  return buffer;
}

std::optional<double> numeric(const SketchConstraint& constraint) {
  if (!constraint.value)
    return std::nullopt;
  try {
    return evaluate_scalar(*constraint.value, "value");
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

std::set<std::string> target_ids(const SketchConstraint& constraint) {
  std::set<std::string> ids;
  for (const SketchRef& target : constraint.targets)
    ids.insert(target.entity_id);
  return ids;
}

bool intersects(const std::set<std::string>& a, const std::set<std::string>& b) {
  return std::any_of(a.begin(), a.end(), [&b](const std::string& id) { return b.count(id) != 0; });
}

// distance(p1, p2 = 5): subentities are folded into the symbol.
std::string describe(const SketchConstraint& constraint) {
  std::string rendered;
  for (const SketchRef& target : constraint.targets) {
    if (!rendered.empty())
      rendered += ", ";
    rendered += target.entity_id;
    if (!target.subentity.empty() && target.subentity != "geometry")
      rendered += "." + target.subentity;
  }
  if (const auto value = numeric(constraint))
    rendered += " = " + general(*value);
  return constraint.kind + "(" + rendered + ")";
}

std::vector<InventoryEntry> constraint_inventory(const Sketch& sketch,
                                                 const std::vector<const SketchConstraint*>& failed,
                                                 const std::vector<const SketchConstraint*>& related) {
  std::vector<InventoryEntry> entries;
  std::set<std::string> listed;
  for (const SketchConstraint* constraint : failed) {
    entries.push_back({constraint->id, "failed", describe(*constraint)});
    listed.insert(constraint->id);
  }
  for (const SketchConstraint* constraint : related) {
    entries.push_back({constraint->id, "near miss", describe(*constraint) + " (shares entities with the failed set)"});
    listed.insert(constraint->id);
  }
  std::vector<const SketchConstraint*> uninvolved;
  for (const SketchConstraint& constraint : sketch.constraints()) {
    if (listed.count(constraint.id) == 0)
      uninvolved.push_back(&constraint);
  }
  for (std::size_t i = 0; i < uninvolved.size() && i < kMaxInventoryOkRows; ++i) {
    entries.push_back({uninvolved[i]->id, "ok", describe(*uninvolved[i])});
  }
  if (uninvolved.size() > kMaxInventoryOkRows) {
    entries.push_back({"(" + std::to_string(uninvolved.size() - kMaxInventoryOkRows) + " more)", "ok",
                       "constraints not implicated by the solver"});
  }
  return entries;
}

std::string join(const std::vector<std::string>& parts, const std::string& separator) {
  std::string out;
  for (const std::string& part : parts) {
    if (!out.empty())
      out += separator;
    out += part;
  }
  return out;
}

}  // namespace

// The picture of a failing sketch: its geometry at the solver's positions, what the failure implicates in orange, what
// is related in purple (diagnostic_image: drawn by whoever registered a provider; nothing without one).
static std::optional<ErrorEvidence> sketch_picture(
    const Sketch& sketch, const SketchSolveResult& result, const std::string& mode, const std::string& caption,
    const std::set<std::string>& highlight, const std::set<std::string>& neighbours,
    const std::vector<std::pair<std::string, std::string>>& constraint_labels, const std::string& dedup_key) {
  DiagnosticImage image;
  image.kind = "sketch_render";
  image.operation = "sketch_solve";
  image.view = "sketch plane";
  image.caption = caption;
  image.dedup_key = dedup_key;
  const auto names = [](const std::set<std::string>& ids) {
    Value out = Value::array();
    for (const std::string& id : ids)
      out.push_back(Value(id));
    return out;
  };
  Value points = Value::object();
  for (const auto& [id, point] : result.solved_points) {
    Value xy = Value::array();
    xy.push_back(Value(point.first));
    xy.push_back(Value(point.second));
    points.set(id, std::move(xy));
  }
  Value labels = Value::array();
  for (const auto& [id, text] : constraint_labels) {
    Value pair = Value::array();
    pair.push_back(Value(id));
    pair.push_back(Value(text));
    labels.push_back(std::move(pair));
  }
  image.payload.set("mode", mode);
  image.payload.set("sketch", sketch.to_value());
  image.payload.set("solved_points", std::move(points));
  Value scalars = Value::object();
  for (const auto& [id, value] : result.solved_scalars)
    scalars.set(id, Value(value));
  image.payload.set("solved_scalars", std::move(scalars));
  image.payload.set("highlight", names(highlight));
  image.payload.set("near", names(neighbours));
  image.payload.set("constraint_labels", std::move(labels));
  return diagnostic_image(image);
}

namespace {

// The constraints a failed solve named, and the ones that share entities with them.
struct SolveFailure {
  std::vector<const SketchConstraint*> failed;
  std::set<std::string> implicated;  // entity ids touched by a failed constraint
  std::vector<const SketchConstraint*> related;
};

SolveFailure classify_failure(const Sketch& sketch, const SketchSolveResult& result) {
  SolveFailure f;
  std::set<std::string> failed_ids;
  for (const auto& diagnostic : result.diagnostics) {
    if (diagnostic.severity == "error" && diagnostic.constraint_id && !diagnostic.constraint_id->empty()) {
      failed_ids.insert(*diagnostic.constraint_id);
    }
  }
  for (const SketchConstraint& constraint : sketch.constraints()) {
    if (failed_ids.count(constraint.id) != 0)
      f.failed.push_back(&constraint);
  }

  // Related = not itself failed but shares an entity with a failed constraint:
  // the direct conflict partners the solver could not name individually.
  for (const SketchConstraint* constraint : f.failed) {
    const auto ids = target_ids(*constraint);
    f.implicated.insert(ids.begin(), ids.end());
  }
  for (const SketchConstraint& constraint : sketch.constraints()) {
    if (failed_ids.count(constraint.id) != 0)
      continue;
    if (intersects(target_ids(constraint), f.implicated))
      f.related.push_back(&constraint);
  }
  if (f.related.size() > kMaxRelatedConstraints)
    f.related.resize(kMaxRelatedConstraints);
  return f;
}

// One "Delete or relax ..." line per failed constraint, then general advice (dimension vs geometric).
std::vector<std::string> failure_repair_lines(const SolveFailure& f) {
  std::vector<std::string> repair;
  for (const SketchConstraint* constraint : f.failed) {
    std::vector<std::string> partners;
    const auto own = target_ids(*constraint);
    for (const SketchConstraint* partner : f.related) {
      if (intersects(target_ids(*partner), own))
        partners.push_back(partner->id);
    }
    std::string line = "Delete or relax " + constraint->id + "(" + describe(*constraint) + ")";
    if (!partners.empty()) {
      line += " \xE2\x80\x94 it constrains the same entities together with " + join(partners, ", ") +
              ", making them a direct conflict pair";
    }
    repair.push_back(std::move(line));
  }
  if (!f.failed.empty()) {
    static const std::set<std::string> kDimensionKinds{"distance", "distance_x", "distance_y", "length",
                                                       "radius",   "diameter",   "angle",      "ratio"};
    std::vector<std::string> dimension_side;
    for (const SketchConstraint* constraint : f.failed) {
      if (kDimensionKinds.count(constraint->kind) != 0)
        dimension_side.push_back(constraint->id);
    }
    if (!dimension_side.empty()) {
      repair.push_back("Prefer relaxing dimension-type constraints first (" + join(dimension_side, ", ") +
                       ") and keep geometric ones (coincident/tangent/parallel/horizontal/vertical) "
                       "\xE2\x80\x94 the geometric intent is usually the design intent");
    } else {
      repair.push_back(
          "The conflict set is entirely geometric: delete the weakest one (usually the last added), or lift "
          "the fix constraint on its target entities first");
    }
  } else {
    repair.push_back(
        "The solver did not name individual constraints: bisect the constraint set (disable the second half "
        "first, then the first) to locate the conflict pair, or rerun "
        "inspect_sketch_rsketchresult(strict=False) for per-constraint diagnostics");
  }
  repair.push_back(
      "Rerun inspect_sketch_rsketchresult(sketch, strict=False) to get per-constraint diagnostics without raising");
  return repair;
}

std::string failure_what_happened(const SketchSolveResult& result, const SolveFailure& f) {
  std::string what_happened =
      "Sketch solve failed with status '" + result.status + "' (backend " + result.backend + ")";
  if (!f.failed.empty()) {
    std::vector<std::string> described;
    for (const SketchConstraint* constraint : f.failed)
      described.push_back(constraint->id + "(" + describe(*constraint) + ")");
    what_happened +=
        "; the solver named " + std::to_string(f.failed.size()) + " failing constraint(s): " + join(described, "; ");
  } else {
    what_happened += "; the solver did not name individual constraints";
  }
  return what_happened;
}

// The annotated sketch picture: implicated entities in orange, entities of related constraints in purple.
std::vector<ErrorEvidence> failure_evidence(const Sketch& sketch, const SketchSolveResult& result,
                                            const SolveFailure& f) {
  std::vector<ErrorEvidence> evidence;
  std::set<std::string> neighbours;
  for (const SketchConstraint* constraint : f.related) {
    const auto ids = target_ids(*constraint);
    neighbours.insert(ids.begin(), ids.end());
  }
  for (const std::string& id : f.implicated)
    neighbours.erase(id);
  std::vector<std::pair<std::string, std::string>> labels;
  std::vector<std::string> failed_names;
  for (const SketchConstraint* constraint : f.failed) {
    labels.emplace_back(constraint->id, describe(*constraint));
    failed_names.push_back(constraint->id);
  }
  std::sort(failed_names.begin(), failed_names.end());
  const std::string caption =
      "status=" + result.status + ", backend=" + result.backend +
      ": orange = entities implicated by failed constraints (" +
      (failed_names.empty() ? std::string("solver did not name any") : join(failed_names, ", ")) +
      "), purple = related constraints sharing those entities";
  if (auto picture =
          sketch_picture(sketch, result, result.status, caption, f.implicated, neighbours, labels,
                         "sketch:" + sketch.sketch_id() + ":" + result.status + ":" + join(failed_names, ",")))
    evidence.push_back(std::move(*picture));
  return evidence;
}

}  // namespace

void raise_sketch_solve_failure(const Sketch& sketch, const SketchSolveResult& result) {
  const SolveFailure f = classify_failure(sketch, result);

  std::vector<ErrorMeasurement> measurements{
      {"constraint count", static_cast<double>(sketch.constraints().size()), ""},
      {"entity count", static_cast<double>(sketch.entities().size()), ""},
      {"conflicting constraints", static_cast<double>(f.failed.size()), ""},
      {"solver DOF at failure", static_cast<double>(result.dof), ""},
  };
  for (const SketchConstraint* constraint : f.failed) {
    if (const auto value = numeric(*constraint)) {
      measurements.push_back({"constraint " + constraint->id + " value", *value, ""});
    }
  }

  std::vector<std::string> repair = failure_repair_lines(f);
  const std::string what_happened = failure_what_happened(result, f);
  std::vector<ErrorEvidence> evidence = failure_evidence(sketch, result, f);
  const ErrorSpec spec{
      "sketch_solve",
      what_happened,
      {"Two or more constraints impose incompatible requirements on the same entities.",
       "A dimension contradicts a geometric constraint (e.g. a distance smaller than a tangency allows).",
       "A constraint references entities whose solved positions cannot satisfy it."},
      {"Read the Inventory rows marked [failed] and [near miss]: they share entities and conflict there.",
       "Relax or delete one constraint from each conflicting pair (see the repair lines)."}};
  raise_harness_error(spec,
                      "sketch_id=" + sketch.sketch_id() + ", backend=" + result.backend + ", backend_status_code=" +
                          (result.backend_status_code ? std::to_string(*result.backend_status_code) : "None"),
                      std::move(measurements), std::move(repair), constraint_inventory(sketch, f.failed, f.related),
                      std::move(evidence));
}

void raise_sketch_underconstrained(const Sketch& sketch, const SketchSolveResult& result) {
  std::set<std::string> referenced;
  for (const SketchConstraint& constraint : sketch.constraints()) {
    const auto ids = target_ids(constraint);
    referenced.insert(ids.begin(), ids.end());
  }
  std::vector<std::string> unreferenced;
  for (const auto& [id, entity] : sketch.entities()) {
    if (referenced.count(id) == 0)
      unreferenced.push_back(id);
  }

  std::vector<ErrorMeasurement> measurements{
      {"remaining DOF", static_cast<double>(result.dof), ""},
      {"constraint count", static_cast<double>(sketch.constraints().size()), ""},
      {"unconstrained entities", static_cast<double>(unreferenced.size()), ""},
  };

  std::vector<std::string> repair;
  if (!unreferenced.empty()) {
    const std::vector<std::string> shown(
        unreferenced.begin(),
        unreferenced.begin() + static_cast<std::ptrdiff_t>(std::min<std::size_t>(12, unreferenced.size())));
    const std::string more =
        unreferenced.size() > 12 ? " (+" + std::to_string(unreferenced.size() - 12) + " more)" : "";
    repair.push_back("These entities are not referenced by any constraint \xE2\x80\x94 fix or dimension them first: " +
                     join(shown, ", ") + more + " (constrain_fix_rsketch / constrain_distance_rsketch and friends)");
  }
  repair.push_back(
      "DOF accounting reference: each free point is 2 DOF, a free circle is 3 (center 2 + radius 1), a free line is 4");
  repair.push_back(
      "Express symmetry intent with geometric constraints (horizontal/vertical/parallel) and leave only final "
      "dimensions to dimension constraints");
  repair.push_back(
      "Rerun inspect_sketch_rsketchresult(sketch) and confirm the DOF reaches 0 before requiring full constraint");

  std::vector<InventoryEntry> inventory;
  const std::size_t listed = std::min(unreferenced.size(), kMaxInventoryOkRows + 8);
  for (std::size_t i = 0; i < listed; ++i) {
    inventory.push_back(
        {unreferenced[i], "unconstrained",
         sketch.entities().at(unreferenced[i]).kind + " \xE2\x80\x94 not referenced by any constraint"});
  }
  if (!referenced.empty()) {
    inventory.push_back(
        {"(" + std::to_string(referenced.size()) + " constrained)", "ok",
         "entities referenced by at least one constraint (may still be partially free \xE2\x80\x94 see DOF)"});
  }

  std::string what_happened = "Sketch solve succeeded geometrically but " + std::to_string(result.dof) +
                              " degrees of freedom remain; a fully constrained result was required";
  if (!unreferenced.empty()) {
    what_happened += " and " + std::to_string(unreferenced.size()) + " entities are not referenced by any constraint";
  }
  std::vector<ErrorEvidence> evidence;
  {
    const std::string caption = std::to_string(result.dof) +
                                " DOF remain: orange = entities no constraint references (certainly free); the solver "
                                "accepted the geometry but cannot hold it";
    if (auto picture =
            sketch_picture(sketch, result, "underconstrained", caption,
                           std::set<std::string>(unreferenced.begin(), unreferenced.end()), {}, {},
                           "sketch:" + sketch.sketch_id() + ":underconstrained:" + std::to_string(result.dof)))
      evidence.push_back(std::move(*picture));
  }
  const ErrorSpec spec{"sketch_solve",
                       what_happened,
                       {"Points or curves were added without fix/dimension constraints.",
                        "require_fully_constrained=True was set before the profile's dimensions were fully specified."},
                       {"Constrain the entities listed as [unconstrained] in the inventory.",
                        "Re-inspect with inspect_sketch_rsketchresult until the DOF reaches 0."}};
  raise_harness_error(spec, "sketch_id=" + sketch.sketch_id() + ", backend=" + result.backend, std::move(measurements),
                      std::move(repair), std::move(inventory), std::move(evidence));
}

}  // namespace scad
