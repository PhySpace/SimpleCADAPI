#include "scad/ql/query.hpp"

#include <algorithm>

#include "scad/ql/compare.hpp"
#include "scad/core/error.hpp"

namespace scad::ql {

Query Query::where(const Test& test) const {
  std::vector<Shape> kept;
  for (const Shape& item : items_)
    if (test(item)) kept.push_back(item);
  return Query(std::move(kept));
}

Query Query::order_by(const KeyFn& sort_key, bool desc) const {
  std::vector<Value> keys;
  keys.reserve(items_.size());
  for (const Shape& item : items_) keys.push_back(sort_key(item));

  // (key is None, key): null sorts after every value; unrelated types do not compare.
  const auto before = [&](std::size_t a, std::size_t b) {
    const bool a_missing = keys[a].is_null();
    const bool b_missing = keys[b].is_null();
    if (a_missing || b_missing) return !a_missing && b_missing;
    switch (compare_values(keys[a], keys[b])) {
      case Ordering::Less: return true;
      case Ordering::Incomparable:
        throw TypeError("'<' not supported between instances of '" + std::string(py_type_name(keys[a])) + "' and '" +
                        std::string(py_type_name(keys[b])) + "'");
      default: return false;
    }
  };
  std::vector<std::size_t> order(items_.size());
  for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;
  std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) { return desc ? before(b, a) : before(a, b); });

  std::vector<Shape> sorted;
  sorted.reserve(items_.size());
  for (const std::size_t index : order) sorted.push_back(items_[index]);
  return Query(std::move(sorted));
}

Query Query::limit(std::int64_t count) const {
  if (count <= 0) return Query({});
  const auto keep = std::min(static_cast<std::size_t>(count), items_.size());
  return Query(std::vector<Shape>(items_.begin(), items_.begin() + static_cast<std::ptrdiff_t>(keep)));
}

std::optional<Shape> Query::first() const {
  if (items_.empty()) return std::nullopt;
  return items_.front();
}

}  // namespace scad::ql
