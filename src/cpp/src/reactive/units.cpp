#include "scad/reactive/units.hpp"

#include <cctype>
#include <cmath>
#include <initializer_list>
#include <numbers>
#include <set>
#include <unordered_map>

namespace scad::reactive {

// ---------------------------------------------------------------------------
// Dimension
// ---------------------------------------------------------------------------

std::string Dimension::name() const {
  if (*this == kDimensionless)
    return "Dimensionless";
  if (*this == kLength)
    return "Length";
  if (*this == kArea)
    return "Area";
  if (*this == kVolume)
    return "Volume";
  if (*this == kAngle)
    return "Angle";
  return symbol();
}

std::string Dimension::symbol() const {
  std::string out;
  const auto term = [&out](char letter, int exponent) {
    if (exponent == 0)
      return;
    if (!out.empty())
      out += ' ';
    out += letter;
    if (exponent != 1)
      out += "^" + std::to_string(exponent);
  };
  term('L', length);
  term('A', angle);
  return out.empty() ? "1" : out;
}

Dimension Dimension::square_root() const {
  if (length % 2 != 0 || angle % 2 != 0) {
    throw UnitValidationError("Cannot take sqrt of " + name() + "; every dimension exponent must be even");
  }
  return {length / 2, angle / 2};
}

Value Dimension::to_value() const {
  Value out = Value::object();
  out.set("length", length);
  out.set("angle", angle);
  return out;
}

Dimension Dimension::from_value(const Value& payload) {
  if (!payload.is_object())
    throw TypeError("Dimension payload must be an object");
  const Value* length = payload.find("length");
  const Value* angle = payload.find("angle");
  if (length == nullptr || angle == nullptr)
    throw ValueError("Dimension payload requires 'length' and 'angle'");
  if (!length->is_int())
    throw TypeError("Dimension length exponent must be an integer");
  if (!angle->is_int())
    throw TypeError("Dimension angle exponent must be an integer");
  return {static_cast<int>(length->as_int()), static_cast<int>(angle->as_int())};
}

// ---------------------------------------------------------------------------
// Unit
// ---------------------------------------------------------------------------

Unit::Unit(std::string symbol, Dimension dimension, double scale_to_canonical)
    : symbol_(std::move(symbol)), dimension_(dimension), scale_(scale_to_canonical) {
  if (symbol_.empty())
    throw ValueError("Unit symbol must be a non-empty string");
  if (!std::isfinite(scale_) || scale_ <= 0.0)
    throw ValueError("Unit scale must be finite and greater than zero");
}

double Unit::to_canonical(double value) const {
  if (!std::isfinite(value))
    throw ValueError("Value in " + symbol_ + " must be finite");
  const double result = value * scale_;
  if (!std::isfinite(result) || (value != 0.0 && result == 0.0)) {
    throw ValueError("Value in " + symbol_ + " is outside the supported range");
  }
  return result;
}

double Unit::from_canonical(double value) const {
  if (!std::isfinite(value))
    throw ValueError("Canonical value must be finite");
  const double result = value / scale_;
  if (!std::isfinite(result) || (value != 0.0 && result == 0.0)) {
    throw ValueError("Canonical value is outside the supported range for " + symbol_);
  }
  return result;
}

Value Unit::to_value() const {
  Value out = Value::object();
  out.set("symbol", symbol_);
  out.set("dimension", dimension_.to_value());
  out.set("scale_to_canonical", scale_);
  return out;
}

Unit Unit::from_value(const Value& payload) {
  if (!payload.is_object())
    throw TypeError("Unit payload must be an object");
  std::string missing;
  for (const char* key : {"dimension", "scale_to_canonical", "symbol"}) {
    if (payload.find(key) == nullptr)
      missing += (missing.empty() ? "" : ", ") + std::string(key);
  }
  if (!missing.empty())
    throw ValueError("Unit payload is missing required fields: " + missing);
  const Value& symbol = *payload.find("symbol");
  const Value& scale = *payload.find("scale_to_canonical");
  if (!symbol.is_string())
    throw ValueError("Unit symbol must be a non-empty string");
  if (!scale.is_number())
    throw TypeError("Unit scale must be a real number");
  return Unit(symbol.as_string(), Dimension::from_value(*payload.find("dimension")), scale.as_double());
}

// ---------------------------------------------------------------------------
// The registered units
// ---------------------------------------------------------------------------

namespace {

struct Builtins {
  Unit mm{"mm", kLength, 1.0};
  Unit cm{"cm", kLength, 10.0};
  Unit m{"m", kLength, 1000.0};
  Unit inch{"in", kLength, 25.4};
  Unit foot{"ft", kLength, 304.8};
  Unit degree{"deg", kAngle, 1.0};
  Unit radian{"rad", kAngle, 180.0 / std::numbers::pi};
  Unit one{"1", kDimensionless, 1.0};
  Unit percent{"%", kDimensionless, 0.01};
  Unit square_mm{"mm^2", kArea, 1.0};
  Unit square_cm{"cm^2", kArea, 100.0};
  Unit square_m{"m^2", kArea, 1'000'000.0};
  Unit square_inch{"in^2", kArea, 25.4 * 25.4};
  Unit square_foot{"ft^2", kArea, 304.8 * 304.8};
  Unit cubic_mm{"mm^3", kVolume, 1.0};
  Unit cubic_cm{"cm^3", kVolume, 1000.0};
  Unit cubic_m{"m^3", kVolume, 1'000'000'000.0};
  Unit cubic_inch{"in^3", kVolume, 25.4 * 25.4 * 25.4};
  Unit cubic_foot{"ft^3", kVolume, 304.8 * 304.8 * 304.8};
};

const Builtins& builtins() {
  static const Builtins table;
  return table;
}

std::string normalized(std::string_view text) {
  std::size_t begin = 0, end = text.size();
  while (begin < end && std::isspace(static_cast<unsigned char>(text[begin])))
    ++begin;
  while (end > begin && std::isspace(static_cast<unsigned char>(text[end - 1])))
    --end;
  std::string out(text.substr(begin, end - begin));
  for (char& c : out) {
    if (static_cast<unsigned char>(c) < 0x80)
      c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  }
  return out;
}

struct Aliases {
  std::unordered_map<std::string, const Unit*> by_token;
  std::set<std::string> symbols;

  void add(const Unit& unit, std::initializer_list<std::string_view> aliases) {
    by_token[normalized(unit.symbol())] = &unit;
    symbols.insert(unit.symbol());
    for (const std::string_view alias : aliases)
      by_token[normalized(alias)] = &unit;
  }
};

const Aliases& aliases() {
  static const Aliases table = [] {
    const Builtins& b = builtins();
    Aliases a;
    a.add(b.mm, {"millimeter", "millimeters"});
    a.add(b.cm, {"centimeter", "centimeters"});
    a.add(b.m, {"meter", "meters"});
    a.add(b.inch, {"inch", "inches"});
    a.add(b.foot, {"foot", "feet"});
    a.add(b.radian, {"radian", "radians"});
    a.add(b.degree, {"degree", "degrees", "\xC2\xB0"});
    a.add(b.one, {"dimensionless"});
    a.add(b.percent, {"percent"});
    a.add(b.square_mm, {"mm2"});
    a.add(b.square_cm, {"cm2"});
    a.add(b.square_m, {"m2"});
    a.add(b.square_inch, {"in2", "square inch", "square inches"});
    a.add(b.square_foot, {"ft2", "square foot", "square feet"});
    a.add(b.cubic_mm, {"mm3"});
    a.add(b.cubic_cm, {"cm3", "ml"});
    a.add(b.cubic_m, {"m3"});
    a.add(b.cubic_inch, {"in3", "cubic inch", "cubic inches"});
    a.add(b.cubic_foot, {"ft3", "cubic foot", "cubic feet"});
    return a;
  }();
  return table;
}

}  // namespace

namespace units {
const Unit& mm() {
  return builtins().mm;
}
const Unit& cm() {
  return builtins().cm;
}
const Unit& m() {
  return builtins().m;
}
const Unit& inch() {
  return builtins().inch;
}
const Unit& foot() {
  return builtins().foot;
}
const Unit& degree() {
  return builtins().degree;
}
const Unit& radian() {
  return builtins().radian;
}
const Unit& one() {
  return builtins().one;
}
const Unit& percent() {
  return builtins().percent;
}
const Unit& square_mm() {
  return builtins().square_mm;
}
const Unit& square_cm() {
  return builtins().square_cm;
}
const Unit& square_m() {
  return builtins().square_m;
}
const Unit& square_inch() {
  return builtins().square_inch;
}
const Unit& square_foot() {
  return builtins().square_foot;
}
const Unit& cubic_mm() {
  return builtins().cubic_mm;
}
const Unit& cubic_cm() {
  return builtins().cubic_cm;
}
const Unit& cubic_m() {
  return builtins().cubic_m;
}
const Unit& cubic_inch() {
  return builtins().cubic_inch;
}
const Unit& cubic_foot() {
  return builtins().cubic_foot;
}
}  // namespace units

std::vector<std::string> registered_unit_symbols() {
  const auto& symbols = aliases().symbols;
  return {symbols.begin(), symbols.end()};
}

Unit get_unit(std::string_view name) {
  const std::string token = normalized(name);
  if (token.empty())
    throw TypeError("Unit must be a non-empty string or Unit");
  const Aliases& table = aliases();
  const auto found = table.by_token.find(token);
  if (found == table.by_token.end()) {
    std::string supported;
    for (const std::string& symbol : table.symbols)
      supported += (supported.empty() ? "" : ", ") + symbol;
    throw ValueError("Unknown unit '" + std::string(name) + "'; supported units: " + supported);
  }
  return *found->second;
}

Value unit_to_payload(const Unit& unit) {
  const Aliases& table = aliases();
  const auto found = table.by_token.find(normalized(unit.symbol()));
  if (found != table.by_token.end() && *found->second == unit)
    return Value(unit.symbol());
  return unit.to_value();
}

Unit unit_from_payload(const Value& payload) {
  if (payload.is_object())
    return Unit::from_value(payload);
  if (payload.is_string())
    return get_unit(payload.as_string());
  throw TypeError("Unit must be a non-empty string or Unit");
}

Unit canonical_unit_for_dimension(Dimension dimension) {
  if (dimension == kDimensionless)
    return units::one();
  if (dimension == kLength)
    return units::mm();
  if (dimension == kArea)
    return units::square_mm();
  if (dimension == kVolume)
    return units::cubic_mm();
  if (dimension == kAngle)
    return units::degree();
  return Unit(dimension.symbol(), dimension, 1.0);
}

double convert_value(double value, const Unit& from, const Unit& to) {
  if (from.dimension() != to.dimension()) {
    throw UnitValidationError("Cannot convert " + from.dimension().name() + " unit '" + from.symbol() + "' to " +
                              to.dimension().name() + " unit '" + to.symbol() + "'");
  }
  return to.from_canonical(from.to_canonical(value));
}

double convert_value(double value, std::string_view from, std::string_view to) {
  return convert_value(value, get_unit(from), get_unit(to));
}

}  // namespace scad::reactive
