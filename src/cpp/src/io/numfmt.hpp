// Locale-independent number <-> text, shared by the JSON and mesh writers.
//
// printf/strtod consult the C locale (a comma decimal separator in de_DE would
// corrupt every file and every manifest).  <charconv> does not.
#pragma once

#include <string>
#include <string_view>

namespace scad::io::detail {

// The three double spellings the io formats use.  All take a finite value.
//  - es6:     ECMAScript Number::toString, which RFC 8785 (JCS) mandates.
//  - python:  Python's repr(float): "1.0", "1e-05", "1.5e+16".
//  - general: "%.{precision}g" (precision 17 round-trips a double).
std::string format_es6(double value);
std::string format_python_repr(double value);
std::string format_general(double value, int precision);

// Parses the whole of `text` as a double in the C locale.  False on any junk,
// on an empty string, or on overflow to infinity.
bool parse_double(std::string_view text, double& out);

}  // namespace scad::io::detail
