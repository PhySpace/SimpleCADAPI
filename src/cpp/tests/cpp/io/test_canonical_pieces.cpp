// The pieces of canonical_json the Python binding assembles itself (bindings/python/bind_canonical.cpp).
#include "doctest.h"

#include <cmath>
#include <limits>
#include <string>

#include "scad/core/error.hpp"
#include "scad/io/json.hpp"

using namespace scad;
using namespace scad::io;

namespace {
std::string text(std::string_view s) {
  std::string out;
  canonical_append_string(s, out);
  return out;
}
std::string number(double d) {
  std::string out;
  canonical_append_number(d, out);
  return out;
}
}  // namespace

TEST_CASE("canonical_append_string: minimal escapes, UTF-8 passes through") {
  CHECK(text("ab") == "\"ab\"");
  CHECK(text("a\"b\\c\b\f\n\r\t") == "\"a\\\"b\\\\c\\b\\f\\n\\r\\t\"");
  CHECK(text(std::string("\x01\x1f", 2)) == "\"\\u0001\\u001f\"");
  CHECK(text("\x7f\xc3\xa9\xf0\x9f\x98\x80") == "\"\x7f\xc3\xa9\xf0\x9f\x98\x80\"");
  CHECK(text("") == "\"\"");
}

TEST_CASE("canonical_append_number: ES6 text, JCS zero, no non-finite") {
  CHECK(number(0.0) == "0");
  CHECK(number(-0.0) == "0");
  CHECK(number(1.0) == "1");
  CHECK(number(0.1) == "0.1");
  CHECK(number(-4.35) == "-4.35");
  CHECK(number(1e21) == "1e+21");
  CHECK(number(1e20) == "100000000000000000000");
  CHECK(number(1.5e16) == "15000000000000000");
  CHECK(number(1e-6) == "0.000001");
  CHECK(number(1e-7) == "1e-7");
  CHECK(number(5e-324) == "5e-324");
  CHECK(number(1.7976931348623157e308) == "1.7976931348623157e+308");
  CHECK_THROWS_AS(number(std::numeric_limits<double>::quiet_NaN()), ValueError);
  CHECK_THROWS_AS(number(std::numeric_limits<double>::infinity()), ValueError);
}

TEST_CASE("canonical_key_less orders by UTF-16 code unit, not UTF-8 byte") {
  CHECK(canonical_key_less("a", "b"));
  CHECK_FALSE(canonical_key_less("b", "a"));
  CHECK_FALSE(canonical_key_less("a", "a"));
  CHECK(canonical_key_less("a", "ab"));
  CHECK(canonical_key_less("\xc3\xa9", "\xee\x80\x80"));  // U+00E9 < U+E000
  // U+10000 (surrogates D800 DC00) sorts before U+E000 in UTF-16 although its UTF-8 bytes are larger.
  CHECK(canonical_key_less("\xf0\x90\x80\x80", "\xee\x80\x80"));
  CHECK(canonical_key_less("\xf0\x90\x80\x80", "\xef\xbf\xbf"));
  CHECK_FALSE(canonical_key_less("\xef\xbf\xbf", "\xf0\x90\x80\x80"));
  CHECK(canonical_key_less("\xee\x80\x80", "\xef\xbf\xbf"));
}
