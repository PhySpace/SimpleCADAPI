// Physical dimensions and engineering units: port of simplecadapi/params/units.py
// (the part that does not need expressions; dimension inference over
// expressions is in expr.hpp).
//
// Everything here is an immutable value.  The unit registry is a read-only
// table built on first use, so every function is safe to call from any thread.
#pragma once

#include <compare>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/reactive/errors.hpp"

namespace scad::reactive {

// Integer exponents of length and angle.
struct Dimension {
  int length = 0;
  int angle = 0;

  auto operator<=>(const Dimension&) const = default;

  std::string name() const;    // "Length", "Area", ... or the symbol
  std::string symbol() const;  // "L^-1 A^2"; "1" when dimensionless
  bool is_dimensionless() const noexcept { return length == 0 && angle == 0; }
  bool is_design_dimension() const noexcept { return (length == 1 && angle == 0) || (length == 0 && angle == 1); }

  Dimension multiply(Dimension other) const noexcept { return {length + other.length, angle + other.angle}; }
  Dimension divide(Dimension other) const noexcept { return {length - other.length, angle - other.angle}; }
  Dimension power(int exponent) const noexcept { return {length * exponent, angle * exponent}; }
  // UnitValidationError unless every exponent is even.
  Dimension square_root() const;

  Value to_value() const;
  // TypeError / ValueError for a malformed payload, like Dimension.from_dict.
  static Dimension from_value(const Value& payload);
};

inline constexpr Dimension kDimensionless{};
inline constexpr Dimension kLength{1, 0};
inline constexpr Dimension kArea{2, 0};
inline constexpr Dimension kVolume{3, 0};
inline constexpr Dimension kAngle{0, 1};

// A named unit with a scale to the canonical CAD units (mm, deg).
class Unit {
 public:
  // ValueError for an empty symbol or a scale that is not finite and > 0.
  Unit(std::string symbol, Dimension dimension, double scale_to_canonical);

  const std::string& symbol() const noexcept { return symbol_; }
  Dimension dimension() const noexcept { return dimension_; }
  double scale_to_canonical() const noexcept { return scale_; }

  // ValueError when the value is not finite or leaves the double range.
  double to_canonical(double value) const;
  double from_canonical(double value) const;

  bool operator==(const Unit&) const = default;

  Value to_value() const;  // {"symbol", "dimension", "scale_to_canonical"}
  static Unit from_value(const Value& payload);

 private:
  std::string symbol_;
  Dimension dimension_;
  double scale_ = 1.0;
};

// The registered units (the module constants of the Python SDK).
namespace units {
const Unit& mm();
const Unit& cm();
const Unit& m();
const Unit& inch();
const Unit& foot();
const Unit& degree();
const Unit& radian();
const Unit& one();
const Unit& percent();
const Unit& square_mm();
const Unit& square_cm();
const Unit& square_m();
const Unit& square_inch();
const Unit& square_foot();
const Unit& cubic_mm();
const Unit& cubic_cm();
const Unit& cubic_m();
const Unit& cubic_inch();
const Unit& cubic_foot();
}  // namespace units

// A built-in unit by symbol or alias ("mm", "inches", "deg", "ml", ...),
// case-insensitive and ignoring surrounding blanks.  ValueError for an unknown name.
Unit get_unit(std::string_view name);

// A registered unit serializes as its symbol, any other as its definition.
Value unit_to_payload(const Unit& unit);
Unit unit_from_payload(const Value& payload);

// mm / mm^2 / mm^3 / deg / 1 for the design dimensions, else a scale-1 unit
// named after the dimension.
Unit canonical_unit_for_dimension(Dimension dimension);

// UnitValidationError when the units' dimensions differ.
double convert_value(double value, const Unit& from, const Unit& to);
double convert_value(double value, std::string_view from, std::string_view to);

// Every registered symbol, sorted.
std::vector<std::string> registered_unit_symbols();

}  // namespace scad::reactive
