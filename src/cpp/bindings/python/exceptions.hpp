// The module's exception handlers (see common.cpp).  Kept apart from bindings.hpp so that the raw-OCCT shim, which
// does not use the SDK types, can register its Standard_Failure handler.
#pragma once

#include <exception>
#include <functional>

namespace scad::pybind {

// The module has ONE exception translator (installed by register_exceptions) that asks its handlers in priority
// order, most specific first, whatever the order the bindings were registered in.  pybind11 itself asks translators
// newest first, which would make the result depend on import order wherever one exception type derives from another
// (UnitValidationError is an Error, StaleLineageError a ValueError).
enum class ExceptionPriority : int {
  Specific = 0,  // one named exception type of one area (reactive errors)
  Occt = 10,     // Standard_Failure: OCCT's exceptions are not std::exception
  General = 20,  // scad::Error -> simplecadapi._cpp.SimpleCADError, scad::Exception -> the matching builtin
};

// A handler rethrows `p`, and when it recognises the type sets the Python error and returns true; returning false
// means "not mine", and the next handler is asked.  Anything no handler takes reaches pybind11's own translators.
using ExceptionHandler = std::function<bool(std::exception_ptr p)>;
void add_exception_handler(ExceptionPriority priority, ExceptionHandler handler);

}  // namespace scad::pybind
