// Content digests and the Python text forms they are computed over.
//
// Expression ids are derived from the content of a node, in the exact text the
// Python SDK hashes (the repr of a tuple of strings, ints, None and
// `float.hex()` texts), so a model built here and one built by the Python SDK
// name the same expression the same way.  The reactive engine reuses the
// digest for its memo keys.
#pragma once

#include <string>
#include <string_view>

namespace scad::reactive {

// Lower-case hex SHA-256 of `data` (64 characters).
std::string sha256_hex(std::string_view data);

// float.hex(): "0x1.4000000000000p+2".
std::string py_float_hex(double value);

// repr(float): the shortest text that reads back as `value`, with Python's
// choice between fixed and exponent notation ("1e-05", "100.0", "1e+16").
std::string py_float_repr(double value);

// repr(str): quoted the way Python quotes it.  Non-ASCII text is assumed
// printable and kept as it is.
std::string py_str_repr(std::string_view text);

}  // namespace scad::reactive
