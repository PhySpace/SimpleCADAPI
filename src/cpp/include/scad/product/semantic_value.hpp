// SemanticValueMixin: the runtime metadata hooks every semantic product value shares.
//
// A Python product value is a frozen dataclass whose metadata and runtime dicts are still
// mutable, so `part.set_metadata(...)` works on a frozen part.  The same holds here: the
// two dictionaries are mutable members, and copies get their own.
#pragma once

#include <string>
#include <string_view>
#include <utility>

#include "scad/core/value.hpp"

namespace scad::product {

class SemanticValue {
 public:
  void set_metadata(std::string key, Value value) const { metadata_.set(std::move(key), std::move(value)); }
  Value get_metadata(std::string_view key, Value fallback = {}) const {
    return lookup(metadata_, key, std::move(fallback));
  }
  void set_runtime(std::string key, Value value) const { runtime_.set(std::move(key), std::move(value)); }
  Value get_runtime(std::string_view key, Value fallback = {}) const {
    return lookup(runtime_, key, std::move(fallback));
  }

  const Value& metadata() const noexcept { return metadata_; }
  const Value& runtime() const noexcept { return runtime_; }

  // dict(self._metadata): a derived value starts with its parent's metadata and its own runtime.
  void inherit_metadata(const SemanticValue& parent) const { metadata_ = parent.metadata_; }
  void replace_runtime(Value runtime) const { runtime_ = std::move(runtime); }

 protected:
  SemanticValue() = default;
  SemanticValue(const SemanticValue&) = default;
  SemanticValue& operator=(const SemanticValue&) = default;
  ~SemanticValue() = default;

 private:
  static Value lookup(const Value& dict, std::string_view key, Value fallback) {
    const Value* found = dict.find(key);
    return found != nullptr ? *found : std::move(fallback);
  }

  mutable Value metadata_ = Value::object();
  mutable Value runtime_ = Value::object();
};

}  // namespace scad::product
