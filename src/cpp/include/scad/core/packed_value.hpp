// PackedValue: a Value, stored as a compact byte string and expanded on demand.
//
// Structured evidence that is written once and almost never read (the tracking payload on every
// face and edge an operator touches) does not need to sit in memory as a tree of heap
// nodes.  Packing keeps it exactly: key order, int-vs-double, and every string survive the round
// trip.  Object keys and short vocabulary strings are interned symbols (a couple of bytes each);
// ids that are unique per shape are stored inline.
#pragma once

#include <string>
#include <string_view>

#include "scad/core/value.hpp"

namespace scad {

// A recipe is a Value that is a pure function of a few small arguments (the "unknown tracking
// payload" of an edge: operation, topo id, kind).  It is stored as the recipe id and the packed
// arguments -- a dozen bytes instead of the whole tree -- and expanded by the registered function.
using ValueRecipe = Value (*)(const Value& args);

class PackedValue {
 public:
  // Register the function behind recipe `id` (ids are small and fixed by the registering module).
  static void register_recipe(unsigned char id, ValueRecipe expand);
  static PackedValue from_recipe(unsigned char id, const Value& args);

  PackedValue() = default;
  explicit PackedValue(const Value& value);

  Value unpack() const;
  static Value unpack_bytes(std::string_view bytes);
  std::string_view bytes() const noexcept { return bytes_; }
  bool empty() const noexcept { return bytes_.empty(); }
  std::size_t byte_size() const noexcept { return bytes_.size(); }

 private:
  std::string bytes_;
};

}  // namespace scad
