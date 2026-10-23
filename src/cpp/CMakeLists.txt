cmake_minimum_required(VERSION 3.20)

project(simplecadapi._cpp
  VERSION 0.1.0
  DESCRIPTION "SimpleCADAPI on OpenCASCADE, in C++ with a pybind11 front"
  LANGUAGES CXX)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------
option(SCAD_BUILD_PYTHON "Build the pybind11 extension module" ON)
option(SCAD_BUILD_TESTS "Build the C++ unit tests" ON)
option(SCAD_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)
option(SCAD_BUILD_BENCH "Build the developer probes in tools/bench" OFF)
option(SCAD_SANITIZE "Build with AddressSanitizer + UBSan (GCC/Clang only)" OFF)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

include(ScadCompile)
include(ScadOcct)

# --------------------------------------------------------------------------
# The library: everything below the Python boundary.
# --------------------------------------------------------------------------
add_subdirectory(src)

if(SCAD_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests/cpp)
endif()

if(SCAD_BUILD_BENCH)
  add_subdirectory(tools/bench)
endif()

if(SCAD_BUILD_PYTHON)
  add_subdirectory(bindings/python)
endif()

# ---- the Python distribution -------------------------------------------------------------------------------------------
# Built by scikit-build-core from the repository root (pyproject.toml): besides the compiled module (installed by
# bindings/python) the wheel carries the resource files the ``simplecadapi`` package serves (the agent skill, the example
# notebooks ``sca example`` copies out).
if(SKBUILD)
  get_filename_component(_repo "${PROJECT_SOURCE_DIR}/../.." ABSOLUTE)
  install(FILES "${_repo}/skillproj.toml" DESTINATION simplecadapi/skill/resources)
  install(DIRECTORY "${_repo}/docs/skill/" DESTINATION simplecadapi/skill/resources/docs/skill)
  foreach(_f u_link.py shell.py u_link_motor_mount.py dimensions.py common.py)
    install(FILES "${_repo}/examples/u_link_motor_mount/${_f}"
            DESTINATION simplecadapi/example/resources/u_link_motor_mount)
  endforeach()
endif()
