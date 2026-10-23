// JSON for the io formats.
//
// Three needs, three entry points:
//  - parse_json: strict RFC 8259 (duplicate members and non-finite numbers are
//    rejected), used for the .scadbrep manifest;
//  - canonical_json: RFC 8785 (JCS), the byte-exact form the manifest is hashed
//    and compared in -- shared with the Python SDK's `rfc8785` output;
//  - python_json_dumps: the text `json.dumps(value, sort_keys=..., ensure_ascii=...)`
//    produces, for strings the Python exporters embed in STEP files.
// None of them looks at the C locale.
#pragma once

#include <string>
#include <string_view>

#include "scad/core/value.hpp"

namespace scad::io {

struct JsonParseOptions {
  bool reject_duplicate_members = true;
  int max_depth = 128;
};

// Throws scad::ValueError (with a byte offset) on malformed input.  Integers
// without fraction/exponent that fit in 64 bits become Value ints, everything
// else a double.
Value parse_json(std::string_view text, const JsonParseOptions& options = {});

// RFC 8785.  Members sorted by UTF-16 code unit, ES6 number text, minimal
// string escapes.  Throws ValueError on a non-finite number.
std::string canonical_json(const Value& value);

// The building blocks of canonical_json, for callers that walk containers that are not a Value
// (the Python binding serialises dict/list objects without converting them first).
void canonical_append_string(std::string_view utf8, std::string& out);   // quoted, RFC 8785 minimal escapes
void canonical_append_number(double value, std::string& out);            // ES6 text; throws ValueError if non-finite
bool canonical_key_less(std::string_view a, std::string_view b);         // UTF-16 code unit order of two UTF-8 keys

// json.dumps(value, ensure_ascii=..., sort_keys=...) with the default
// separators (", " and ": "); doubles in Python's repr form.
std::string python_json_dumps(const Value& value, bool sort_keys = false, bool ensure_ascii = true);

}  // namespace scad::io
