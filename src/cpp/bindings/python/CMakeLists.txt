find_package(Python 3.10 COMPONENTS Interpreter Development.Module REQUIRED)
find_package(pybind11 CONFIG REQUIRED)

file(GLOB _bind_sources CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/occt/*.cpp")
pybind11_add_module(_native MODULE ${_bind_sources})
scad_apply_compile_options(_native)
target_link_libraries(_native PRIVATE scad::scad)
# Static OCCT + hidden visibility: the module exports PyInit__native and nothing else,
# so it cannot clash with a second OCCT in the same process (cadquery-ocp, say).
set_target_properties(_native PROPERTIES CXX_VISIBILITY_PRESET hidden)

# The extension is the module ``simplecadapi._cpp._native``: it lives in the Python package, next to its Python files
# (src/simplecadapi/_cpp/).  A wheel build installs it there; a development build writes it there directly, so a
# checkout (``src`` on the path, or an editable install) imports it without any further step.  One file per Python
# version (``_native.cpython-312-darwin.so``): several builds can share the directory.
get_filename_component(_package_dir "${PROJECT_SOURCE_DIR}/../simplecadapi/_cpp" ABSOLUTE)
if(SKBUILD)
  install(TARGETS _native LIBRARY DESTINATION simplecadapi/_cpp)
else()
  set_target_properties(_native PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${_package_dir}")
endif()
