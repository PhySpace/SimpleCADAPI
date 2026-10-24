// Argument checks shared by the standard parts.
//
// The Python factories do not agree on their wording, and the messages are part of what a
// caller sees, so there are two families: the gear and bearing factories say "must be finite"
// or "must be positive" (one check at a time), the chain and fastener factories say
// "must be positive and finite".  Every failure is a plain ValueError, as in Python.
#pragma once

#include <string_view>

namespace scad::stdlib {

// gear.py / bearing.py: _validate_positive_finite, _validate_non_negative_finite.
double validate_positive(std::string_view name, double value);
double validate_non_negative(std::string_view name, double value);

// chain.py / fastener.py: _positive_finite, _non_negative_finite.
double positive_finite(std::string_view name, double value);
double non_negative_finite(std::string_view name, double value);

// Python's math.radians / math.degrees, which scale by pi/180 and 180/pi in that order
// (x * kPi / 180 rounds differently, and the tooth angles are compared bit for bit).
double radians(double deg) noexcept;
double degrees(double rad) noexcept;

}  // namespace scad::stdlib
