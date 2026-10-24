// Holding Python objects from C++ objects that outlive the interpreter.
//
// A registry with static storage (the reactive ExecutorRegistry, the sketch solver backends, ...)
// is destroyed from exit(), AFTER Py_Finalize.  Releasing a Python reference then must not touch
// the interpreter: acquiring the GIL creates a thread state (PyThreadState_New) on a finalized
// runtime and crashes the process on its way out.  Use drop_python_reference() in every
// destructor that owns a py::object / py::function; at shutdown it leaks the one reference,
// which is the right thing to do for a process that is exiting.
#pragma once

#include <Python.h>

#include <pybind11/pybind11.h>

namespace scad::pybind {

inline bool python_alive() noexcept {
  if (Py_IsInitialized() == 0) return false;
#if PY_VERSION_HEX >= 0x030D0000
  return Py_IsFinalizing() == 0;
#else
  return _Py_IsFinalizing() == 0;
#endif
}

template <class PyObj>
void drop_python_reference(PyObj& object) noexcept {
  if (!python_alive()) {
    object.release();  // forget the reference without decrementing it
    return;
  }
  const pybind11::gil_scoped_acquire gil;
  object = PyObj();
}

}  // namespace scad::pybind
