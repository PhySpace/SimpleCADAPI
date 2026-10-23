// Small string helpers shared by the src/ql translation units.  Not installed.
#pragma once

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <string>
#include <string_view>
#include <vector>

namespace scad::ql::text {

inline std::string_view strip(std::string_view s) noexcept {
  constexpr std::string_view kSpace = " \t\n\r\f\v";
  const auto first = s.find_first_not_of(kSpace);
  if (first == std::string_view::npos) return {};
  return s.substr(first, s.find_last_not_of(kSpace) - first + 1);
}

inline std::string lower(std::string_view s) {
  std::string out(s);
  std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return out;
}

inline std::string upper(std::string_view s) {
  std::string out(s);
  std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
  return out;
}

inline std::string join(const std::vector<std::string>& parts, std::string_view separator) {
  std::string out;
  for (std::size_t i = 0; i < parts.size(); ++i) {
    if (i != 0) out += separator;
    out += parts[i];
  }
  return out;
}

// printf("%.<digits>g"): what Python's format spec ".<digits>g" prints.
inline std::string general(double v, int digits) {
  char buf[64];
  std::snprintf(buf, sizeof buf, "%.*g", digits, v);
  return buf;
}

}  // namespace scad::ql::text
