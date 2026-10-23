// Error model.
//
// Mirrors simplecadapi/errors.py: every public operator failure carries
// structured, repair-oriented guidance (what happened / possible causes / how
// to fix) and renders to the same text layout, because that text is read by
// language-model agents, not only by people.
#pragma once

#include <array>
#include <exception>
#include <initializer_list>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace scad {

// The Python exception family a C++ exception maps to.  Used for the
// "Technical details" line of a wrapped error and by the pybind11 translator.
enum class PyKind { ValueError, TypeError, IndexError, KeyError, RuntimeError, NotImplementedError };

std::string_view py_kind_name(PyKind kind) noexcept;

// ---------------------------------------------------------------------------
// Plain exceptions (the analogues of ValueError / TypeError / ...).
// ---------------------------------------------------------------------------
class Exception : public std::runtime_error {
 public:
  Exception(PyKind kind, const std::string& message) : std::runtime_error(message), kind_(kind) {}
  PyKind py_kind() const noexcept { return kind_; }

 private:
  PyKind kind_;
};

class ValueError : public Exception {
 public:
  explicit ValueError(const std::string& message) : Exception(PyKind::ValueError, message) {}
};
class TypeError : public Exception {
 public:
  explicit TypeError(const std::string& message) : Exception(PyKind::TypeError, message) {}
};
class IndexError : public Exception {
 public:
  explicit IndexError(const std::string& message) : Exception(PyKind::IndexError, message) {}
};
class RuntimeError : public Exception {
 public:
  explicit RuntimeError(const std::string& message) : Exception(PyKind::RuntimeError, message) {}
};
class NotImplementedError : public Exception {
 public:
  explicit NotImplementedError(const std::string& message)
      : Exception(PyKind::NotImplementedError, message) {}
};

// An OpenCASCADE exception (Standard_Failure family) caught at a kernel boundary.
class KernelError : public RuntimeError {
 public:
  KernelError(std::string occt_class, const std::string& message)
      : RuntimeError(message), occt_class_(std::move(occt_class)) {}
  const std::string& occt_class() const noexcept { return occt_class_; }

 private:
  std::string occt_class_;
};

// ---------------------------------------------------------------------------
// Structured guidance.
// ---------------------------------------------------------------------------
struct ErrorMeasurement {
  std::string name;
  std::variant<double, std::array<double, 3>> value;
  std::string unit;

  // "name: 1.234 mm" / "name: (1, 2, 3)" -- %.4g like the Python original.
  std::string display() const;
};

struct ErrorEvidence {
  std::string kind;  // "render" today
  std::string path;
  std::string view;
  std::string caption;
  std::vector<std::pair<std::string, std::string>> symbols;
};

struct InventoryEntry {
  std::string symbol;
  std::string status;  // hit / near_miss / unmatched
  std::string description;
};

struct ErrorGuidance {
  std::string what_happened;
  std::vector<std::string> possible_causes;
  std::vector<std::string> how_to_fix;
  std::string technical_details;     // empty = absent
  std::string signature;             // empty = absent; filled lazily by the Python layer
  std::string documentation_hint;    // empty = absent
  std::vector<ErrorMeasurement> measurements;
  std::vector<ErrorEvidence> evidence;
  std::vector<std::string> repair;
  std::vector<InventoryEntry> inventory;
};

// The Python module users import this library through ("simplecadapi._cpp"):
// error text points them at help(<module>.<operation>).  Set once at import.
void set_error_module_name(std::string name);
const std::string& error_module_name();

// The text a failing operation shows its caller.
std::string format_llm_error(std::string_view operation, const ErrorGuidance& guidance);

// simplecadapi.SimpleCADError: a ValueError that carries guidance.
class Error : public ValueError {
 public:
  Error(std::string operation, ErrorGuidance guidance);

  const std::string& operation() const noexcept { return operation_; }
  const ErrorGuidance& guidance() const noexcept { return guidance_; }
  ErrorGuidance& mutable_guidance() noexcept { return guidance_; }

 private:
  std::string operation_;
  ErrorGuidance guidance_;
};

// SimpleCADMessageError: message-first Error families (tagging, sketch, ...).
// The structured guidance stays available; only what_happened is filled.
class MessageError : public Error {
 public:
  MessageError(std::string operation, const std::string& message)
      : Error(std::move(operation), ErrorGuidance{message, {}, {}, {}, {}, {}, {}, {}, {}, {}}) {}
};

class TagValidationError : public MessageError {
 public:
  explicit TagValidationError(const std::string& message) : MessageError("tagging", message) {}
};
class SemanticCapabilityError : public MessageError {
 public:
  explicit SemanticCapabilityError(const std::string& message) : MessageError("semantic_query", message) {}
};
class UnsupportedQueryCapabilityError : public SemanticCapabilityError {
 public:
  using SemanticCapabilityError::SemanticCapabilityError;
};

// The static, per-operator half of a wrapped failure: written once next to the
// operator, reused on every failure.
struct ErrorSpec {
  std::string operation;
  std::string what_happened;
  std::vector<std::string> possible_causes;
  std::vector<std::string> how_to_fix;

  ErrorSpec(std::string operation_, std::string what_happened_,
            std::initializer_list<std::string> causes, std::initializer_list<std::string> fixes)
      : operation(std::move(operation_)),
        what_happened(std::move(what_happened_)),
        possible_causes(causes),
        how_to_fix(fixes) {}
};

// "ValueError: message" for any caught exception; OCCT failures keep their class.
std::string technical_details_of(const std::exception& error);

// Throw an Error built from `spec` and the exception being handled.  An
// existing scad::Error passes through unchanged (it already says what it needs to).
[[noreturn]] void raise_harness_error(const ErrorSpec& spec, const std::exception& cause,
                                      std::vector<ErrorMeasurement> measurements = {},
                                      std::vector<std::string> repair = {},
                                      std::vector<InventoryEntry> inventory = {},
                                      std::vector<ErrorEvidence> evidence = {});

// Throw an Error with no underlying exception.
[[noreturn]] void raise_harness_error(const ErrorSpec& spec, std::string technical_details = {},
                                      std::vector<ErrorMeasurement> measurements = {},
                                      std::vector<std::string> repair = {},
                                      std::vector<InventoryEntry> inventory = {},
                                      std::vector<ErrorEvidence> evidence = {});

// Run `body`; any exception leaves as a scad::Error described by `spec`.
// Cost on the success path: nothing.
template <class F>
decltype(auto) guarded(const ErrorSpec& spec, F&& body) {
  try {
    return std::forward<F>(body)();
  } catch (const Error&) {
    throw;
  } catch (const std::exception& e) {
    raise_harness_error(spec, e);
  }
}

// Catch OCCT's exceptions at a kernel boundary and rethrow them as KernelError.
// Defined in src/core/occt_guard.cpp so this header stays OCCT-free.
[[noreturn]] void rethrow_occt_failure();

// Wrap `body` so OCCT exceptions become KernelError.  Use this around every
// direct OCCT call sequence: OCCT's Standard_Failure does not derive from
// std::exception.
template <class F>
decltype(auto) occt_guard(F&& body) {
  try {
    return std::forward<F>(body)();
  } catch (const std::exception&) {
    throw;
  } catch (...) {
    rethrow_occt_failure();
  }
}

}  // namespace scad
