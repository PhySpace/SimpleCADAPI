#include "scad/core/packed_value.hpp"

#include <cstring>

#include "scad/core/error.hpp"
#include "scad/core/symbol.hpp"

namespace scad {

namespace {

enum Tag : unsigned char { kNull, kFalse, kTrue, kInt, kDouble, kSymbol, kText, kArray, kObject, kDigits, kRecipe = 0xFE };

ValueRecipe g_recipes[8] = {};

// Vocabulary (repeats across shapes and operations) is interned; per-shape or per-operation ids
// (kernel topo ids are decimal hashes, graph/node ids are g_/n_ + hex) would only grow the table.
bool interned_text(const std::string& s) {
  if (s.empty() || s.size() > 48) return false;
  const char c = s.front();
  if (c >= '0' && c <= '9') return false;
  if (s.size() > 1 && s[1] == '_' && (c == 'g' || c == 'n')) return false;
  return Symbol::count() < (1u << 20);
}

void put_varint(std::string& out, std::uint64_t v) {
  while (v >= 0x80) {
    out.push_back(static_cast<char>(v | 0x80));
    v >>= 7;
  }
  out.push_back(static_cast<char>(v));
}

std::uint64_t get_varint(std::string_view in, std::size_t& at) {
  std::uint64_t v = 0;
  int shift = 0;
  while (true) {
    if (at >= in.size()) throw ValueError("corrupt packed value");
    const auto byte = static_cast<unsigned char>(in[at++]);
    v |= static_cast<std::uint64_t>(byte & 0x7F) << shift;
    if ((byte & 0x80) == 0) return v;
    shift += 7;
  }
}

// A decimal numeral without sign or leading zero that fits an int64 (kernel topo ids are such
// hashes): stored as a number, rendered back to the same text.
bool is_canonical_numeral(const std::string& s, std::uint64_t& value) {
  if (s.empty() || s.size() > 18 || s.front() == '0') return false;
  value = 0;
  for (const char c : s) {
    if (c < '0' || c > '9') return false;
    value = value * 10 + static_cast<std::uint64_t>(c - '0');
  }
  return true;
}

void put_symbol(std::string& out, const std::string& text) { put_varint(out, Symbol(text).index()); }

void pack(std::string& out, const Value& v) {
  if (v.is_null()) {
    out.push_back(kNull);
  } else if (v.is_bool()) {
    out.push_back(v.as_bool() ? kTrue : kFalse);
  } else if (v.is_int()) {
    out.push_back(kInt);
    const std::int64_t i = v.as_int();
    put_varint(out, (static_cast<std::uint64_t>(i) << 1) ^ static_cast<std::uint64_t>(i >> 63));
  } else if (v.is_double()) {
    out.push_back(kDouble);
    const double d = v.as_double();
    char raw[sizeof d];
    std::memcpy(raw, &d, sizeof d);
    out.append(raw, sizeof d);
  } else if (v.is_string()) {
    const std::string& s = v.as_string();
    std::uint64_t numeral = 0;
    if (is_canonical_numeral(s, numeral)) {
      out.push_back(kDigits);
      put_varint(out, numeral);
    } else if (interned_text(s)) {
      out.push_back(kSymbol);
      put_symbol(out, s);
    } else {
      out.push_back(kText);
      put_varint(out, s.size());
      out.append(s);
    }
  } else if (v.is_array()) {
    out.push_back(kArray);
    put_varint(out, v.as_array().size());
    for (const Value& item : v.as_array()) pack(out, item);
  } else {
    out.push_back(kObject);
    put_varint(out, v.as_object().size());
    for (const auto& [key, item] : v.as_object()) {
      put_symbol(out, key);  // keys are schema vocabulary
      pack(out, item);
    }
  }
}

Value unpack(std::string_view in, std::size_t& at) {
  if (at >= in.size()) throw ValueError("corrupt packed value");
  switch (static_cast<unsigned char>(in[at++])) {
    case kNull: return Value();
    case kFalse: return Value(false);
    case kTrue: return Value(true);
    case kInt: {
      const std::uint64_t z = get_varint(in, at);
      return Value(static_cast<std::int64_t>((z >> 1) ^ (~(z & 1) + 1)));
    }
    case kDouble: {
      double d;
      if (at + sizeof d > in.size()) throw ValueError("corrupt packed value");
      std::memcpy(&d, in.data() + at, sizeof d);
      at += sizeof d;
      return Value(d);
    }
    case kRecipe: {
      if (at >= in.size()) throw ValueError("corrupt packed value");
      const unsigned char id = static_cast<unsigned char>(in[at++]);
      Value args = unpack(in, at);
      if (id >= 8 || g_recipes[id] == nullptr) throw ValueError("packed value names an unregistered recipe");
      return g_recipes[id](args);
    }
    case kDigits: return Value(std::to_string(get_varint(in, at)));
    case kSymbol: return Value(Symbol::from_index(static_cast<std::uint32_t>(get_varint(in, at))).str());
    case kText: {
      const std::uint64_t n = get_varint(in, at);
      if (at + n > in.size()) throw ValueError("corrupt packed value");
      Value text(std::string(in.substr(at, static_cast<std::size_t>(n))));
      at += static_cast<std::size_t>(n);
      return text;
    }
    case kArray: {
      const std::uint64_t n = get_varint(in, at);
      Value::Array items;
      items.reserve(static_cast<std::size_t>(n));
      for (std::uint64_t i = 0; i < n; ++i) items.push_back(unpack(in, at));
      return Value(std::move(items));
    }
    case kObject: {
      const std::uint64_t n = get_varint(in, at);
      Value::Object members;
      members.reserve(static_cast<std::size_t>(n));
      for (std::uint64_t i = 0; i < n; ++i) {
        std::string key = Symbol::from_index(static_cast<std::uint32_t>(get_varint(in, at))).str();
        members.emplace_back(std::move(key), unpack(in, at));
      }
      return Value(std::move(members));
    }
    default: break;
  }
  throw ValueError("corrupt packed value");
}

}  // namespace

void PackedValue::register_recipe(unsigned char id, ValueRecipe expand) {
  if (id < 8) g_recipes[id] = expand;
}

PackedValue PackedValue::from_recipe(unsigned char id, const Value& args) {
  PackedValue out;
  out.bytes_.push_back(static_cast<char>(kRecipe));
  out.bytes_.push_back(static_cast<char>(id));
  pack(out.bytes_, args);
  return out;
}

PackedValue::PackedValue(const Value& value) {
  pack(bytes_, value);
  bytes_.shrink_to_fit();
}

Value PackedValue::unpack() const { return unpack_bytes(bytes_); }

Value PackedValue::unpack_bytes(std::string_view bytes) {
  std::size_t at = 0;
  return scad::unpack(bytes, at);
}

}  // namespace scad
