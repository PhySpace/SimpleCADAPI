#include "bytes.hpp"

namespace scad::io::detail {

namespace {

constexpr std::uint8_t kNull = 0, kFalse = 1, kTrue = 2, kInt = 3, kDouble = 4, kString = 5, kArray = 6, kObject = 7;

std::uint64_t zigzag(std::int64_t v) {
  return (static_cast<std::uint64_t>(v) << 1) ^ static_cast<std::uint64_t>(v >> 63);
}
std::int64_t unzigzag(std::uint64_t v) {
  return static_cast<std::int64_t>(v >> 1) ^ -static_cast<std::int64_t>(v & 1U);
}

}  // namespace

void encode_value(ByteWriter& out, const Value& value) {
  if (value.is_null()) {
    out.u8(kNull);
  } else if (value.is_bool()) {
    out.u8(value.as_bool() ? kTrue : kFalse);
  } else if (value.is_int()) {
    out.u8(kInt);
    out.varuint(zigzag(value.as_int()));
  } else if (value.is_double()) {
    out.u8(kDouble);
    out.f64(value.as_double());
  } else if (value.is_string()) {
    out.u8(kString);
    out.str(value.as_string());
  } else if (value.is_array()) {
    out.u8(kArray);
    out.varuint(value.as_array().size());
    for (const Value& item : value.as_array())
      encode_value(out, item);
  } else {
    out.u8(kObject);
    out.varuint(value.as_object().size());
    for (const auto& [key, item] : value.as_object()) {
      out.str(key);
      encode_value(out, item);
    }
  }
}

Value decode_value(ByteReader& in, int max_depth) {
  if (max_depth < 0)
    throw ValueError("shape state is corrupt: nesting is too deep");
  switch (in.u8()) {
    case kNull:
      return Value();
    case kFalse:
      return Value(false);
    case kTrue:
      return Value(true);
    case kInt:
      return Value(unzigzag(in.varuint()));
    case kDouble:
      return Value(in.f64());
    case kString:
      return Value(std::string(in.str()));
    case kArray: {
      const std::uint64_t count = in.varuint();
      if (count > in.remaining())
        throw ValueError("shape state is corrupt: an array is longer than the data");
      Value::Array items;
      items.reserve(static_cast<std::size_t>(count));
      for (std::uint64_t i = 0; i < count; ++i)
        items.push_back(decode_value(in, max_depth - 1));
      return Value(std::move(items));
    }
    case kObject: {
      const std::uint64_t count = in.varuint();
      if (count > in.remaining())
        throw ValueError("shape state is corrupt: an object is longer than the data");
      Value::Object members;
      members.reserve(static_cast<std::size_t>(count));
      for (std::uint64_t i = 0; i < count; ++i) {
        std::string key(in.str());
        members.emplace_back(std::move(key), decode_value(in, max_depth - 1));
      }
      return Value(std::move(members));
    }
    default:
      throw ValueError("shape state is corrupt: unknown value tag");
  }
}

}  // namespace scad::io::detail
