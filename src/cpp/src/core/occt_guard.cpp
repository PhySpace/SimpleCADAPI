#include <Standard_Failure.hxx>
#include <Standard_Type.hxx>

#include <exception>

#include "scad/core/error.hpp"

namespace scad {

void rethrow_occt_failure() {
  try {
    throw;
  } catch (const Standard_Failure& failure) {
    const char* message = failure.GetMessageString();
    throw KernelError(failure.DynamicType()->Name(), message != nullptr ? message : "");
  } catch (...) {
    throw KernelError("UnknownException", "a non-standard exception escaped OpenCASCADE");
  }
}

}  // namespace scad
