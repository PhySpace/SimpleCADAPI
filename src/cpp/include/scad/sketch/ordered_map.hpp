// A string-keyed map that remembers insertion order: Python's dict, which the
// sketch document, solve results and serialized forms all rely on (entity order
// decides profile order and wire direction).
#pragma once

#include <cstddef>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "scad/core/error.hpp"

namespace scad {

template <class V>
class OrderedMap {
 public:
  using Item = std::pair<std::string, V>;
  using iterator = typename std::vector<Item>::iterator;
  using const_iterator = typename std::vector<Item>::const_iterator;

  bool empty() const noexcept { return items_.empty(); }
  std::size_t size() const noexcept { return items_.size(); }
  bool contains(std::string_view key) const { return find(key) != nullptr; }

  // nullptr when absent.
  const V* find(std::string_view key) const {
    const auto it = index_.find(std::string(key));
    return it == index_.end() ? nullptr : &items_[it->second].second;
  }
  V* find(std::string_view key) {
    const auto it = index_.find(std::string(key));
    return it == index_.end() ? nullptr : &items_[it->second].second;
  }

  // KeyError when absent (dict[key]).
  const V& at(std::string_view key) const {
    if (const V* value = find(key))
      return *value;
    throw Exception(PyKind::KeyError, "'" + std::string(key) + "'");
  }
  V& at(std::string_view key) {
    if (V* value = find(key))
      return *value;
    throw Exception(PyKind::KeyError, "'" + std::string(key) + "'");
  }

  // Insert or overwrite, keeping the first-insertion position.
  V& set(std::string key, V value) {
    if (V* existing = find(key)) {
      *existing = std::move(value);
      return *existing;
    }
    index_.emplace(key, items_.size());
    items_.emplace_back(std::move(key), std::move(value));
    return items_.back().second;
  }
  V& operator[](std::string_view key) {
    if (V* existing = find(key))
      return *existing;
    return set(std::string(key), V{});
  }

  std::vector<std::string> keys() const {
    std::vector<std::string> out;
    out.reserve(items_.size());
    for (const auto& item : items_)
      out.push_back(item.first);
    return out;
  }

  const_iterator begin() const noexcept { return items_.begin(); }
  const_iterator end() const noexcept { return items_.end(); }
  iterator begin() noexcept { return items_.begin(); }
  iterator end() noexcept { return items_.end(); }
  const Item& item(std::size_t position) const { return items_.at(position); }

  bool operator==(const OrderedMap& other) const { return items_ == other.items_; }

 private:
  std::vector<Item> items_;
  std::unordered_map<std::string, std::size_t> index_;
};

}  // namespace scad
