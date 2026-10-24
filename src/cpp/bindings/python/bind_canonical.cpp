// Canonical JSON (RFC 8785) and artifact content hashes straight from Python containers.
//
// The Python SDK hashes every geometry-interface record, feature graph and definition through
// `canonical_bytes` (validate recursively, then rfc8785 recursively): ~25% of an arm6 build.
// These functions walk dict/list/tuple/str/int/float/bool/None objects once, in C++.
//
// Contract: a function returns the exact bytes (text) the Python implementation produces, or None
// when the value is outside the fast domain (non-dict mappings, subclasses of containers, integers
// beyond the safe range, non-finite floats, lone surrogates, non-string keys, deep nesting, cycles).
// The caller then runs the Python implementation, which raises the error it always raised -- so the
// error types and messages are the Python ones by construction, never re-implemented here.
#include <Python.h>

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "bindings.hpp"
#include "scad/io/hash.hpp"
#include "scad/io/json.hpp"

namespace {

constexpr long long kSafeInt = 9007199254740991LL;
constexpr int kMaxDepth = 48;  // deeper (or cyclic) values take the Python path, which reports them

class Walker {
 public:
  explicit Walker(bool safe_ints) : safe_ints_(safe_ints) { out_.reserve(256); }

  std::string& out() { return out_; }

  // False: outside the fast domain (out_ is then meaningless).
  bool walk(PyObject* o, int depth, const std::vector<std::string_view>* omit = nullptr) {
    if (o == Py_None) { out_ += "null"; return true; }
    if (PyBool_Check(o)) { out_ += o == Py_True ? "true" : "false"; return true; }
    if (PyLong_Check(o)) return integer(o);
    if (PyUnicode_Check(o)) {
      std::string_view text;
      if (!utf8(o, text)) return false;
      scad::io::canonical_append_string(text, out_);
      return true;
    }
    if (PyFloat_Check(o)) {
      const double d = PyFloat_AS_DOUBLE(o);
      if (!std::isfinite(d)) return false;
      scad::io::canonical_append_number(d, out_);
      return true;
    }
    if (depth >= kMaxDepth) return false;
    if (PyList_CheckExact(o)) {
      const Py_ssize_t n = PyList_GET_SIZE(o);
      out_.push_back('[');
      for (Py_ssize_t i = 0; i < n; ++i) {
        if (i) out_.push_back(',');
        if (!walk(PyList_GET_ITEM(o, i), depth + 1)) return false;
      }
      out_.push_back(']');
      return true;
    }
    if (PyTuple_CheckExact(o)) {
      const Py_ssize_t n = PyTuple_GET_SIZE(o);
      out_.push_back('[');
      for (Py_ssize_t i = 0; i < n; ++i) {
        if (i) out_.push_back(',');
        if (!walk(PyTuple_GET_ITEM(o, i), depth + 1)) return false;
      }
      out_.push_back(']');
      return true;
    }
    if (PyDict_CheckExact(o)) return dict(o, depth, omit);
    return false;
  }

 private:
  struct Member {
    std::string_view key;
    PyObject* value;
  };

  static bool utf8(PyObject* o, std::string_view& text) {
    Py_ssize_t size = 0;
    const char* data = PyUnicode_AsUTF8AndSize(o, &size);
    if (data == nullptr) {  // lone surrogate
      PyErr_Clear();
      return false;
    }
    text = std::string_view(data, static_cast<std::size_t>(size));
    return true;
  }

  bool integer(PyObject* o) {
    int overflow = 0;
    const long long v = PyLong_AsLongLongAndOverflow(o, &overflow);
    if (overflow == 0 && v == -1 && PyErr_Occurred()) { PyErr_Clear(); return false; }
    if (overflow == 0 && v <= kSafeInt && v >= -kSafeInt) {
      char buffer[24];
      const auto r = std::to_chars(buffer, buffer + sizeof buffer, v);
      out_.append(buffer, r.ptr);
      return true;
    }
    if (!safe_ints_) return false;
    // _json_safe: an integer outside the JSON safe range is hashed as the string "int:<decimal>".
    PyObject* text = PyObject_Str(o);
    if (text == nullptr) { PyErr_Clear(); return false; }
    std::string_view digits;
    const bool ok = utf8(text, digits);
    if (ok) scad::io::canonical_append_string(std::string("int:").append(digits), out_);
    Py_DECREF(text);
    return ok;
  }

  bool dict(PyObject* o, int depth, const std::vector<std::string_view>* omit) {
    std::vector<Member> members;
    members.reserve(static_cast<std::size_t>(PyDict_GET_SIZE(o)));
    Py_ssize_t pos = 0;
    PyObject *key = nullptr, *value = nullptr;
    while (PyDict_Next(o, &pos, &key, &value)) {
      if (!PyUnicode_Check(key)) return false;
      std::string_view name;
      if (!utf8(key, name)) return false;
      if (omit != nullptr && std::find(omit->begin(), omit->end(), name) != omit->end()) continue;
      members.push_back({name, value});
    }
    std::sort(members.begin(), members.end(),
              [](const Member& a, const Member& b) { return scad::io::canonical_key_less(a.key, b.key); });
    out_.push_back('{');
    bool first = true;
    for (const Member& member : members) {
      if (!first) out_.push_back(',');
      first = false;
      scad::io::canonical_append_string(member.key, out_);
      out_.push_back(':');
      if (!walk(member.value, depth + 1)) return false;
    }
    out_.push_back('}');
    return true;
  }

  std::string out_;
  bool safe_ints_;
};

// The keys content_hash drops from the top level.  Values stay owned by the tuple the caller passed.
bool read_omit(const py::handle& omit, std::vector<std::string_view>& out) {
  if (omit.is_none()) return true;
  if (!PyTuple_Check(omit.ptr()) && !PyList_Check(omit.ptr())) return false;
  for (py::handle item : py::reinterpret_borrow<py::sequence>(omit)) {
    if (!PyUnicode_Check(item.ptr())) return false;
    Py_ssize_t size = 0;
    const char* data = PyUnicode_AsUTF8AndSize(item.ptr(), &size);
    if (data == nullptr) { PyErr_Clear(); return false; }
    out.emplace_back(data, static_cast<std::size_t>(size));
  }
  return true;
}

py::object canonical_bytes(const py::handle& value, bool safe_ints) {
  Walker walker(safe_ints);
  if (!walker.walk(value.ptr(), 0)) return py::none();
  return py::reinterpret_steal<py::object>(PyBytes_FromStringAndSize(walker.out().data(),
                                                                      static_cast<Py_ssize_t>(walker.out().size())));
}

py::object canonical_hash(const py::handle& value, const py::handle& omit, bool safe_ints) {
  std::vector<std::string_view> omitted;
  if (!read_omit(omit, omitted)) return py::none();
  if (!omitted.empty() && !PyDict_CheckExact(value.ptr())) return py::none();
  Walker walker(safe_ints);
  if (!walker.walk(value.ptr(), 0, omitted.empty() ? nullptr : &omitted)) return py::none();
  return py::str(scad::io::sha256_tagged(walker.out()));
}

}  // namespace

void bind_canonical(py::module_& m) {
  m.def("canonical_bytes", &canonical_bytes, py::arg("value"), py::arg("safe_ints") = false,
        "RFC 8785 bytes of a JSON-like Python value (what artifacts.canonical.canonical_bytes returns), or None "
        "when the value needs the Python implementation (it raises the error). safe_ints: integers outside "
        "+-(2**53-1) become the string 'int:<n>' (geometry_interface._json_safe).");
  m.def("canonical_hash", &canonical_hash, py::arg("value"), py::arg("omit") = py::none(), py::arg("safe_ints") = false,
        "'sha256:<hex>' of the canonical bytes of `value` without the top-level keys in `omit` (artifacts.canonical."
        "content_hash), or None when the value needs the Python implementation.");
}
