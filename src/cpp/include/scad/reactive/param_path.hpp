// A position inside a recorded parameter set.
//
// An operation records its parameters as one JSON-like Value; the scalars among
// them that are symbolic are named by a path into it: "width", "size[1]",
// "center.x", "points[2][0]".  The first segment is the top-level parameter
// name, `[n]` indexes an array and `.name` an object member.  Parameter names
// of the SDK are identifiers, so no escaping exists: a member name may not
// contain '.', '[' or ']'.
#pragma once

#include <string>
#include <string_view>
#include <variant>
#include <vector>

#include "scad/core/value.hpp"

namespace scad::reactive {

struct ParamPath {
  using Step = std::variant<std::size_t, std::string>;

  std::string key;          // the top-level parameter
  std::vector<Step> steps;  // below it

  // ValueError for an empty or malformed path.
  static ParamPath parse(std::string_view text);
  std::string str() const;

  bool operator==(const ParamPath&) const = default;
};

// The value at `path`, or nullptr when the path does not exist.
const Value* find_param(const Value& params, const ParamPath& path);
Value* find_param(Value& params, const ParamPath& path);

// Store `value` at `path`, creating the objects and arrays on the way
// (arrays are padded with null).  ValueError when a step meets a value of the
// wrong shape (a member name on a number, ...).
void set_param(Value& params, const ParamPath& path, Value value);

}  // namespace scad::reactive
