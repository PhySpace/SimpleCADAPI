# Gordon surfaces for the surface area: DLR's occ_gordon, vendored in
# third_party/occ_gordon (Apache-2.0, OpenCASCADE-only, see its README.scad.md).
#
# Included from src/CMakeLists.txt after scad_surface is defined.  With the option
# OFF (or the sources absent) scad_surface compiles a stub and
# make_gordon_surface_rface reports that the build has no Gordon support.

option(SCAD_WITH_GORDON "Build the vendored occ_gordon library (make_gordon_surface_rface)" ON)

set(_scad_gordon_root "${PROJECT_SOURCE_DIR}/third_party/occ_gordon/src")

if(SCAD_WITH_GORDON AND NOT EXISTS "${_scad_gordon_root}/occ_gordon/occ_gordon.cpp")
  message(WARNING "SCAD_WITH_GORDON is ON but third_party/occ_gordon is missing; building without Gordon surfaces")
  set(SCAD_WITH_GORDON OFF)
endif()

if(SCAD_WITH_GORDON AND TARGET scad_surface)
  file(GLOB _scad_gordon_sources CONFIGURE_DEPENDS
    "${_scad_gordon_root}/internal/*.cpp" "${_scad_gordon_root}/occ_gordon/*.cpp")
  add_library(scad_occ_gordon STATIC ${_scad_gordon_sources})
  target_include_directories(scad_occ_gordon
    PUBLIC "${_scad_gordon_root}"
    PRIVATE "${_scad_gordon_root}/internal")
  target_link_libraries(scad_occ_gordon PUBLIC scad::occt)
  # The library uses M_PI; MSVC needs _USE_MATH_DEFINES for it.
  target_compile_definitions(scad_occ_gordon PRIVATE _USE_MATH_DEFINES)
  # Upstream code, not held to our warning level.
  if(MSVC)
    target_compile_options(scad_occ_gordon PRIVATE /w)
  else()
    target_compile_options(scad_occ_gordon PRIVATE -w)
  endif()
  target_link_libraries(scad_surface PRIVATE scad_occ_gordon)
  target_compile_definitions(scad_surface PRIVATE SCAD_WITH_GORDON=1)
  message(STATUS "Gordon surfaces: vendored occ_gordon")
else()
  message(STATUS "Gordon surfaces: disabled (make_gordon_surface_rface reports it)")
endif()
