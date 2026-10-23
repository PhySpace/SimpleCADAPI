# A quick way to develop the OCCT bindings (bindings/python/occt/): just those sources, linked against OCCT and
# nothing of scad -- a build takes minutes, not the full library's.  The module is `_occt_dev` (the same classes as
# `simplecadapi._cpp._native._occt`, which is where they end up).
#
#   cmake -S src/cpp/occt_dev -B src/cpp/build/occt-dev && cmake --build src/cpp/build/occt-dev
#   PYTHONPATH=src/cpp/build/occt-dev python -c "import _occt_dev; ..."
cmake_minimum_required(VERSION 3.20)
project(occt_dev LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/../cmake")
include(ScadOcct)

find_package(Python 3.10 COMPONENTS Interpreter Development.Module REQUIRED)
find_package(pybind11 CONFIG REQUIRED)

file(GLOB _sources CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/../bindings/python/occt/*.cpp")
pybind11_add_module(_occt_dev MODULE main.cpp ${_sources})
target_link_libraries(_occt_dev PRIVATE scad::occt)
set_target_properties(_occt_dev PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
