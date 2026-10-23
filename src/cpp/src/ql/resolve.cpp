// Resolving a selector against a scope: the pipeline of ShapeSelector.resolve.
//
//   candidates -> predicate -> incident-face constraints -> order keys -> limit -> cardinality
//
// Every stage works on the one vector of Shape handles it was given; predicates
// and keys are already compiled, so the cost per candidate is the evaluation
// itself.  One EvalContext (a snapshot of the property resolvers) serves the
// whole run, including the nested selectors.
#include <algorithm>
#include <numeric>

#include "internal.hpp"
#include "scad/core/error.hpp"
#include "scad/ql/compare.hpp"
#include "scad/ql/diagnostics.hpp"
#include "scad/topo/recorder.hpp"
#include "selector_impl.hpp"

namespace scad::ql {

namespace {

std::vector<Face> incident_faces_of(const Shape& item) {
  return item.kind() == Kind::Edge ? Edge(item).incident_faces() : std::vector<Face>{};
}

// Does the edge's incident faces cover every face set with a different face for each?
// (a small bipartite matching; the sets are few)
bool distinct_witnesses(const std::vector<Face>& incident, const std::vector<IdentitySet>& sets, std::size_t index,
                        std::vector<char>& used) {
  if (index == sets.size()) return true;
  for (std::size_t i = 0; i < incident.size(); ++i) {
    if (used[i] != 0 || !sets[index].contains(incident[i])) continue;
    used[i] = 1;
    if (distinct_witnesses(incident, sets, index + 1, used)) return true;
    used[i] = 0;
  }
  return false;
}

bool has_incident_witnesses(const Shape& item, const std::vector<IdentitySet>& sets, bool distinct) {
  const std::vector<Face> incident = incident_faces_of(item);
  if (distinct) {
    std::vector<char> used(incident.size(), 0);
    return distinct_witnesses(incident, sets, 0, used);
  }
  return std::all_of(sets.begin(), sets.end(), [&](const IdentitySet& set) {
    return std::any_of(incident.begin(), incident.end(), [&](const Face& face) { return set.contains(face); });
  });
}

// (value is None, value) ordered ascending; null sorts after every value.
bool key_before(const Value& a, const Value& b) {
  const bool a_missing = a.is_null();
  const bool b_missing = b.is_null();
  if (a_missing || b_missing) return !a_missing && b_missing;
  switch (compare_values(a, b)) {
    case Ordering::Less: return true;
    case Ordering::Equal:
    case Ordering::Greater:
    case Ordering::Unordered: return false;
    case Ordering::Incomparable: break;
  }
  throw TypeError("'<' not supported between instances of '" + std::string(py_type_name(a)) + "' and '" +
                  std::string(py_type_name(b)) + "'");
}

// A stable sort on one key; `desc` keeps equal items in their original order, like sorted(reverse=True).
void sort_by(std::vector<Shape>& items, const Key& sort_key, bool desc, const EvalContext& ctx) {
  std::vector<Value> keys;
  keys.reserve(items.size());
  for (const Shape& item : items) keys.push_back(sort_key.evaluate(item, ctx));

  std::vector<std::size_t> order(items.size());
  std::iota(order.begin(), order.end(), std::size_t{0});
  std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
    return desc ? key_before(keys[b], keys[a]) : key_before(keys[a], keys[b]);
  });

  std::vector<Shape> sorted;
  sorted.reserve(items.size());
  for (const std::size_t index : order) sorted.push_back(std::move(items[index]));
  items = std::move(sorted);
}

std::optional<std::int64_t> asserted(const std::vector<std::pair<std::string, std::int64_t>>& cardinality,
                                     std::string_view mode) {
  for (const auto& [name, count] : cardinality)
    if (name == mode) return count;
  return std::nullopt;
}

}  // namespace

std::vector<Shape> ShapeSelector::resolve_with(const Scope& scope, const EvalContext& ctx) const {
  const Impl& m = *impl_;
  std::vector<Shape> items;

  if (m.set_operation) {
    if (*m.set_operation != "intersection" || m.operands.size() < 2)
      throw ValueError("unsupported selector set operation: " + *m.set_operation);
    items = m.operands.front().resolve_with(scope, ctx);
    std::vector<IdentitySet> others;
    for (std::size_t i = 1; i < m.operands.size(); ++i) {
      const std::vector<Shape> resolved = m.operands[i].resolve_with(scope, ctx);
      others.emplace_back(resolved.begin(), resolved.end());
    }
    std::erase_if(items, [&](const Shape& item) {
      return !std::all_of(others.begin(), others.end(), [&](const IdentitySet& set) { return set.contains(item); });
    });
  } else if (!m.source_selector) {
    items = detail::scope_items(scope, m.target_kind);
  } else {
    if (!m.traversal) throw ValueError("traversal selector is missing traversal metadata");
    const std::vector<Shape> sources = m.source_selector->resolve_with(scope, ctx);
    if (m.traversal->relation != "boundary")
      throw ValueError("unsupported traversal relation: " + m.traversal->relation);
    items = detail::traverse_items(sources, m.target_kind);
  }

  if (m.predicate) {
    const Predicate& keep = *m.predicate;
    std::erase_if(items, [&](const Shape& item) { return !keep.matches(item, ctx); });
  }

  if (!m.incident_face_selectors.empty()) {
    std::vector<IdentitySet> face_sets;
    for (const ShapeSelector& selector : m.incident_face_selectors) {
      const std::vector<Shape> faces = selector.resolve_with(scope, ctx);
      face_sets.emplace_back(faces.begin(), faces.end());
    }
    std::erase_if(items, [&](const Shape& item) {
      return !has_incident_witnesses(item, face_sets, m.incident_faces_distinct);
    });
  }

  if (m.incident_face_cardinality) {
    const std::int64_t wanted = *m.incident_face_cardinality;
    std::erase_if(items, [&](const Shape& item) {
      const std::vector<Face> incident = incident_faces_of(item);
      return static_cast<std::int64_t>(IdentitySet(incident.begin(), incident.end()).size()) != wanted;
    });
  }

  // Sort by the last key first: stable passes leave the first key most significant.
  if (!m.order_keys.empty()) {
    for (auto it = m.order_keys.rbegin(); it != m.order_keys.rend(); ++it) sort_by(items, it->first, it->second, ctx);
  } else if (m.order_key) {
    sort_by(items, *m.order_key, m.order_desc, ctx);
  }

  if (m.limit_count) {  // items[:limit]: a negative limit (possible only from a payload) drops from the end
    const auto size = static_cast<std::int64_t>(items.size());
    const std::int64_t keep = *m.limit_count < 0 ? std::max<std::int64_t>(size + *m.limit_count, 0) : *m.limit_count;
    if (keep < size) items.erase(items.begin() + static_cast<std::ptrdiff_t>(keep), items.end());
  }

  const auto count = static_cast<std::int64_t>(items.size());
  if (const auto exact = asserted(m.cardinality, "exactly"); exact && count != *exact)
    raise_cardinality_failure(m.target_kind, items, *exact, "exactly", scope);
  if (const auto least = asserted(m.cardinality, "at_least"); least && count < *least)
    raise_cardinality_failure(m.target_kind, items, *least, "at_least", scope);
  if (const auto most = asserted(m.cardinality, "at_most"); most && count > *most)
    raise_cardinality_failure(m.target_kind, items, *most, "at_most", scope);
  return items;
}

std::vector<Shape> ShapeSelector::resolve(const Scope& scope) const {
  const EvalContext ctx;
  return resolve_with(scope, ctx);
}

std::vector<Shape> ShapeSelector::resolve(const Shape& scope) const { return resolve(Scope(scope)); }

std::vector<Shape> ShapeSelector::resolve_recorded(const Shape& scope) const {
  std::vector<Shape> picked = resolve(scope);
  if (Recorder* recorder = current_recorder(); recorder != nullptr && !picked.empty())
    recorder->record_selection(scope, picked, impl_->target_kind);
  return picked;
}

}  // namespace scad::ql
