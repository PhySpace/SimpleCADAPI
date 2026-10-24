#include "numfmt.hpp"

#include <charconv>
#include <cmath>
#include <locale>
#include <sstream>
#include <version>

namespace scad::io::detail {

namespace {

struct Decimal {
  bool negative = false;
  std::string digits;  // shortest round-trip digits, no leading/trailing zeros ("0" for zero)
  int exponent = 0;    // decimal exponent of the first digit: value = d.ddd x 10^exponent
};

Decimal shortest_decimal(double value) {
  Decimal d;
  d.negative = std::signbit(value);
  if (value == 0.0) {
    d.digits = "0";
    return d;
  }
  char buffer[64];
  const auto result = std::to_chars(buffer, buffer + sizeof buffer, std::fabs(value), std::chars_format::scientific);
  std::string text(buffer, result.ptr);  // "d.ddde+XX" or "de+XX"
  const std::size_t e = text.find('e');
  const std::string mantissa = text.substr(0, e);
  for (const char c : mantissa)
    if (c != '.') d.digits.push_back(c);
  d.exponent = std::stoi(text.substr(e + 1));
  while (d.digits.size() > 1 && d.digits.back() == '0') d.digits.pop_back();
  return d;
}

std::string exponent_suffix(int exponent, bool pad_two_digits) {
  std::string out = "e";
  out += exponent < 0 ? '-' : '+';
  std::string digits = std::to_string(std::abs(exponent));
  if (pad_two_digits && digits.size() < 2) digits.insert(digits.begin(), '0');
  return out + digits;
}

}  // namespace

std::string format_es6(double value) {
  if (value == 0.0) return "0";
  const Decimal d = shortest_decimal(value);
  const int k = static_cast<int>(d.digits.size());
  const int n = d.exponent + 1;  // ES6 "n": the decimal point sits after n digits
  std::string out = d.negative ? "-" : "";
  if (k <= n && n <= 21) {
    out += d.digits + std::string(static_cast<std::size_t>(n - k), '0');
  } else if (0 < n && n <= 21) {
    out += d.digits.substr(0, static_cast<std::size_t>(n)) + "." + d.digits.substr(static_cast<std::size_t>(n));
  } else if (-6 < n && n <= 0) {
    out += "0." + std::string(static_cast<std::size_t>(-n), '0') + d.digits;
  } else {
    out += d.digits.substr(0, 1);
    if (k > 1) out += "." + d.digits.substr(1);
    out += exponent_suffix(n - 1, false);
  }
  return out;
}

std::string format_python_repr(double value) {
  const Decimal d = shortest_decimal(value);
  const int k = static_cast<int>(d.digits.size());
  std::string out = d.negative ? "-" : "";
  if (value == 0.0) return out + "0.0";
  // float_repr_style 'short' uses exponent form outside -4 <= exp < 16.
  if (d.exponent < -4 || d.exponent >= 16) {
    out += d.digits.substr(0, 1);
    if (k > 1) out += "." + d.digits.substr(1);
    return out + exponent_suffix(d.exponent, true);
  }
  if (d.exponent >= 0) {
    const int integer_digits = d.exponent + 1;
    if (k <= integer_digits) return out + d.digits + std::string(static_cast<std::size_t>(integer_digits - k), '0') + ".0";
    return out + d.digits.substr(0, static_cast<std::size_t>(integer_digits)) + "." +
           d.digits.substr(static_cast<std::size_t>(integer_digits));
  }
  return out + "0." + std::string(static_cast<std::size_t>(-d.exponent - 1), '0') + d.digits;
}

std::string format_general(double value, int precision) {
  char buffer[64];
  const auto result = std::to_chars(buffer, buffer + sizeof buffer, value, std::chars_format::general, precision);
  return std::string(buffer, result.ptr);
}

bool parse_double(std::string_view text, double& out) {
  if (text.empty()) return false;
#if defined(__cpp_lib_to_chars) && __cpp_lib_to_chars >= 201611L
  const char* first = text.data();
  const char* last = text.data() + text.size();
  const auto result = std::from_chars(first, last, out);
  return result.ec == std::errc() && result.ptr == last;
#else
  // libc++ before LLVM 20 has no floating-point from_chars; a classic-locale
  // stream parses identically and does not look at the global locale.
  std::istringstream in{std::string(text)};
  in.imbue(std::locale::classic());
  in >> out;
  return !in.fail() && in.peek() == std::char_traits<char>::eof() && std::isfinite(out);
#endif
}

}  // namespace scad::io::detail
