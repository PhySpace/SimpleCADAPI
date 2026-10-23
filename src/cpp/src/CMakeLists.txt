# The scad library, built as one static library per area so that a broken or
# unfinished area never blocks building (or testing) another.
#
#   scad_core      errors, Vec3, CoordinateSystem, Scalar, Value
#   scad_kernel    OCCT-level algorithms, no semantic state
#   scad_topo      Shape handles, tags, entity registry
#   scad_<area>    one per operator family; see scad_add_area calls below
#
# Sources are globbed per area directory (CONFIGURE_DEPENDS re-globs on each
# build), so adding a .cpp needs no CMake edit.

function(scad_add_area name)
  cmake_parse_arguments(A "" "DIR" "DEPS" ${ARGN})
  if(NOT A_DIR)
    set(A_DIR ${name})
  endif()
  file(GLOB_RECURSE _srcs CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/${A_DIR}/*.cpp")
  if(_srcs)
    add_library(scad_${name} STATIC ${_srcs})
  else()
    # An area with no sources yet is still a valid link dependency.
    add_library(scad_${name} INTERFACE)
  endif()
  get_target_property(_type scad_${name} TYPE)
  set(_vis PUBLIC)
  if(_type STREQUAL "INTERFACE_LIBRARY")
    set(_vis INTERFACE)
  else()
    scad_apply_compile_options(scad_${name})
    target_include_directories(scad_${name} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/${A_DIR}")
  endif()
  target_include_directories(scad_${name} ${_vis} "${PROJECT_SOURCE_DIR}/include")
  target_link_libraries(scad_${name} ${_vis} scad::occt ${A_DEPS})
  add_library(scad::${name} ALIAS scad_${name})
endfunction()

scad_add_area(core)
scad_add_area(kernel DEPS scad_core)
scad_add_area(topo DEPS scad_kernel scad_core)

# Areas.  Dependencies run downward: nothing in an area may include a header from
# an area listed above it in this table.
#
#   semantic       tags, lineage, tracking, the finalize pipeline   (needs topo)
#   reactive       expressions, units, the reactive graph/recorder   (needs topo)
#   io             import / export / mesh                           (needs topo)
#   ql             the selector query language (edges().where(...))  (needs semantic)
#   render         software renderer: shaded faces, edges, highlights, id buffer (needs io)
#   sketch         constrained sketches and the solver              (needs topo)
#   surface        surface and shell operators                      (needs semantic)
#   ops_geometry   primitives, curves, wires, faces                 (needs semantic)
#   ops_features   extrude/revolve/sweep/loft/fillet/boolean/...    (needs semantic)
#   std            gears, bearings, fasteners                       (needs ops, sketch, product)
#   product        parts, assemblies, constraints                   (needs ops)
scad_add_area(semantic DEPS scad_topo)
scad_add_area(reactive DEPS scad_topo)
scad_add_area(io DEPS scad_topo)
scad_add_area(ql DEPS scad_topo scad_semantic)
scad_add_area(render DEPS scad_topo scad_io)
scad_add_area(sketch DEPS scad_topo scad_semantic)
scad_add_area(surface DEPS scad_semantic)
include(ScadGordon)  # SCAD_WITH_GORDON: vendored occ_gordon for the surface area
scad_add_area(ops_geometry DIR ops/geometry DEPS scad_semantic scad_reactive scad_io)
scad_add_area(ops_features DIR ops/features DEPS scad_semantic scad_ql scad_ops_geometry)
scad_add_area(std DEPS scad_ops_features scad_ops_geometry scad_sketch scad_reactive scad_product)
scad_add_area(product DEPS scad_ops_features scad_ops_geometry scad_reactive)

# The whole library, for the Python module and for users linking C++.
set(SCAD_AREAS semantic reactive io ql render sketch surface ops_geometry ops_features std product)
set(SCAD_AREAS ${SCAD_AREAS} PARENT_SCOPE)  # tests/cpp registers one test per area
add_library(scad INTERFACE)
add_library(scad::scad ALIAS scad)
foreach(_a IN LISTS SCAD_AREAS)
  target_link_libraries(scad INTERFACE scad_${_a})
endforeach()
target_link_libraries(scad INTERFACE scad_topo scad_kernel scad_core)
