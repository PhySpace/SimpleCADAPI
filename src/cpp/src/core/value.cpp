#include "scad/core/value.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "scad/core/error.hpp"

namespace scad {

namespace {

[[noreturn]] void mismatch(const char* wanted) {
  throw TypeError(std::string("Value is not ") + wanted);
}

void dump_string(const std::string& s, std::string& out) {
  out += '"';
  for (const unsigned char c : s) {
    switch (c) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\r':
        out += "\\r";
        break;
      case '\t':
        out += "\\t";
        break;
      default:
        if (c < 0x20) {
          char buf[8];
          std::snprintf(buf, sizeof buf, "\\u%04x", c);
          out += buf;
        } else {
          out += static_cast<char>(c);
        }
    }
  }
  out += '"';
}

void dump_into(const Value& v, std::string& out) {
  if (v.is_null()) {
    out += "null";
  } else if (v.is_bool()) {
    out += v.as_bool() ? "true" : "false";
  } else if (v.is_int()) {
    out += std::to_string(v.as_int());
  } else if (v.is_double()) {
    const double d = v.as_double();
    if (!std::isfinite(d)) {
      out += "null";
    } else {
      char buf[40];
      std::snprintf(buf, sizeof buf, "%.17g", d);
      out += buf;
    }
  } else if (v.is_string()) {
    dump_string(v.as_string(), out);
  } else if (v.is_array()) {
    out += '[';
    bool first = true;
    for (const auto& item : v.as_array()) {
      if (!first)
        out += ',';
      first = false;
      dump_into(item, out);
    }
    out += ']';
  } else {
    out += '{';
    bool first = true;
    for (const auto& [key, item] : v.as_object()) {
      if (!first)
        out += ',';
      first = false;
      dump_string(key, out);
      out += ':';
      dump_into(item, out);
    }
    out += '}';
  }
}

}  // namespace

bool Value::as_bool() const {
  if (const auto* p = std::get_if<bool>(&data_))
    return *p;
  mismatch("a bool");
}
std::int64_t Value::as_int() const {
  if (const auto* p = std::get_if<std::int64_t>(&data_))
    return *p;
  mismatch("an integer");
}
double Value::as_double() const {
  if (const auto* p = std::get_if<double>(&data_))
    return *p;
  if (const auto* p = std::get_if<std::int64_t>(&data_))
    return static_cast<double>(*p);
  mismatch("a number");
}
const std::string& Value::as_string() const {
  if (const auto* p = std::get_if<std::string>(&data_))
    return *p;
  mismatch("a string");
}
const Value::Array& Value::as_array() const {
  if (const auto* p = std::get_if<Array>(&data_))
    return *p;
  if (const auto* p = std::get_if<Tuple>(&data_))
    return *p;
  mismatch("an array");
}
Value::Array& Value::as_array() {
  if (auto* p = std::get_if<Array>(&data_))
    return *p;
  if (auto* p = std::get_if<Tuple>(&data_))
    return *p;
  mismatch("an array");
}
const Value::Object& Value::as_object() const {
  if (const auto* p = std::get_if<Object>(&data_))
    return *p;
  mismatch("an object");
}
Value::Object& Value::as_object() {
  if (auto* p = std::get_if<Object>(&data_))
    return *p;
  mismatch("an object");
}

const Value* Value::find(std::string_view key) const noexcept {
  const auto* obj = std::get_if<Object>(&data_);
  if (obj == nullptr)
    return nullptr;
  for (const auto& member : *obj)
    if (member.first == key)
      return &member.second;
  return nullptr;
}

Value* Value::find(std::string_view key) noexcept {
  return const_cast<Value*>(static_cast<const Value*>(this)->find(key));
}

Value& Value::set(std::string key, Value value) {
  if (is_null())
    data_ = Object{};
  auto& obj = as_object();
  for (auto& member : obj) {
    if (member.first == key) {
      member.second = std::move(value);
      return member.second;
    }
  }
  obj.emplace_back(std::move(key), std::move(value));
  return obj.back().second;
}

bool Value::erase(std::string_view key) {
  auto* obj = std::get_if<Object>(&data_);
  if (obj == nullptr)
    return false;
  const auto it = std::find_if(obj->begin(), obj->end(), [&](const Member& m) { return m.first == key; });
  if (it == obj->end())
    return false;
  obj->erase(it);
  return true;
}

Value& Value::push_back(Value value) {
  if (is_null())
    data_ = Array{};
  auto& arr = as_array();
  arr.push_back(std::move(value));
  return arr.back();
}

std::size_t Value::size() const noexcept {
  if (const auto* a = std::get_if<Array>(&data_))
    return a->size();
  if (const auto* t = std::get_if<Tuple>(&data_))
    return t->size();
  if (const auto* o = std::get_if<Object>(&data_))
    return o->size();
  return 0;
}

bool Value::operator==(const Value& other) const {
  // 1 == 1.0, like Python.
  if (is_number() && other.is_number())
    return as_double() == other.as_double();
  if (is_array() && other.is_array())
    return as_array() == other.as_array();  // a tuple equals the list of its items
  return data_ == other.data_;
}

std::string Value::dump() const {
  std::string out;
  dump_into(*this, out);
  return out;
}

}  // namespace scad
