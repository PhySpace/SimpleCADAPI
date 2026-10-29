// What an editor needs to drive a parameter: port of the ParamSpec model and
// the `# ui:` comment grammar of simplecadapi/runtime/params.py.
//
// The Python runtime reads these from notebook source (an AST walk over
// `# ---- params ----` cells); that scanning stays in Python.  What is kept
// here is the data model and the grammar, so a Var created through the C++
// API (or the bindings) carries the same slider/number/toggle description an
// editor would otherwise get from a comment:
//
//     W = scad.var("w", 20.0, unit="mm")  # ui: slider(10, 40, step=2, label="Width")
//     w = scad.var("w", 20.0, unit="mm", ui="slider(10, 40, step=2, label='Width')")
//
// A bad description never throws: the control falls back (a number box, a
// toggle) and `issues` says why.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/value.hpp"

namespace scad::reactive {

// A number written in a ui description; keeps whether it was written as an int.
struct UiNumber {
  double value = 0.0;
  bool integral = false;

  bool operator==(const UiNumber&) const = default;
  std::string text() const;  // "5" or "0.5", like Python prints it
  Value to_value() const;
};

// The slider / number / toggle description of one parameter.
struct ParamUi {
  std::string control;  // requested: "slider" | "number" | "toggle"; empty = follow the value
  std::optional<UiNumber> min, max, step;
  std::optional<std::string> unit;  // display label; wins over the variable's own unit
  std::optional<std::string> label;
  std::string group;
  std::vector<std::string> issues;  // problems parsing the description

  bool operator==(const ParamUi&) const = default;
  bool empty() const noexcept {
    return control.empty() && !min && !max && !step && !unit && !label && group.empty() && issues.empty();
  }
};

// Parse the text after `# ui:` ("slider(1, 5, step=1, unit='mm')").  Problems
// go to `issues`; the other fields then stay empty.
ParamUi parse_ui_comment(std::string_view text);

enum class ParamKind { Float, Int, Bool };
std::string_view to_string(ParamKind kind) noexcept;  // "float" | "int" | "bool"

// One parameter as an editor lists it (runtime.params.ParamSpec).
struct ParamSpec {
  std::string name;
  std::string group;
  std::string cell;
  int line = 0;
  ParamKind kind = ParamKind::Float;
  std::string declared = "literal";  // "literal" | "var"
  Value default_value;               // bool, int or double
  std::string control = "number";    // "slider" | "number" | "toggle"
  std::optional<UiNumber> min, max, step;
  std::optional<std::string> unit;
  std::optional<std::string> label;
  std::optional<std::string> comment;
  std::vector<std::string> issues;

  Value to_value() const;  // ParamSpec.to_dict()
};

// ParamSpec from the declared value and an optional ui description
// (runtime.params._spec): the control follows the value unless the
// description asks for a compatible one.
ParamSpec make_param_spec(std::string name, ParamKind kind, Value default_value, const ParamUi& ui,
                          std::string declared = "literal", std::optional<std::string> unit = std::nullopt,
                          std::optional<std::string> comment = std::nullopt);

}  // namespace scad::reactive
