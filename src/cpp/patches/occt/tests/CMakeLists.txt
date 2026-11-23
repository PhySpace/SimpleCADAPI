# Kernel-level checks of the OCCT patch set, built against an installed patched prefix:
#   cmake -S src/cpp/patches/occt/tests -B <build> -G Ninja -DOpenCASCADE_DIR=<prefix>/lib/cmake/opencascade
# With -DYPATCH_DEV=ON the overlay sources of this checkout are compiled in, so kernel edits
# can be tried without rebuilding the prefix (the prefix's own copies are then shadowed).
cmake_minimum_required(VERSION 3.20)
project(occt_patch_tests LANGUAGES CXX)
find_package(OpenCASCADE CONFIG REQUIRED)
option(YPATCH_DEV "compile the checkout's Y-patch overlay sources into the tools" OFF)
# with YPATCH_DEV: a directory holding the patched BRepFilletAPI_MakeFillet.hxx/.cxx (patch 0004
# applied), compiled in as well so that the tools exercise it
set(YPATCH_MAKEFILLET "" CACHE PATH "patched BRepFilletAPI_MakeFillet sources")
set(overlay ${CMAKE_CURRENT_SOURCE_DIR}/../overlay)
set(dev_sources)
if(YPATCH_DEV)
  set(dev_sources ${overlay}/BRepFilletAPI_YPatch.cxx ${overlay}/BRepFilletAPI_YPatchBuild.cxx)
  if(YPATCH_MAKEFILLET)
    list(APPEND dev_sources ${YPATCH_MAKEFILLET}/BRepFilletAPI_MakeFillet.cxx)
  endif()
endif()
foreach(name cases inspect check shellfillet wires sidetail)
  add_executable(${name} ${name}.cxx ${dev_sources})
  target_compile_features(${name} PRIVATE cxx_std_17)
  if(YPATCH_DEV)
    target_include_directories(${name} BEFORE PRIVATE ${overlay} ${YPATCH_MAKEFILLET})
    target_compile_definitions(${name} PRIVATE YPATCH_TRACE)
  endif()
  target_include_directories(${name} PRIVATE ${OpenCASCADE_INCLUDE_DIR})
  if(NOT OpenCASCADE_BUILD_SHARED_LIBS)
    target_compile_definitions(${name} PRIVATE OCCT_STATIC_BUILD _USE_MATH_DEFINES)
  endif()
  target_link_libraries(${name} PRIVATE TKOffset TKFillet TKDESTEP TKBool TKBO)
endforeach()
# graphpatch: BRepOffsetAPI_GraphPatch on planar and curved supports (cylinder and sphere windows,
# 3..6-sided holes in a B-spline sheet, plane holes, wall loops); exit status 1 on a refusal or a
# patch off its limits. With YPATCH_DEV the checkout's graph patch is compiled in, tracing its fit.
add_executable(graphpatch graphpatch.cxx)
if(YPATCH_DEV)
  target_sources(graphpatch PRIVATE ${overlay}/BRepOffsetAPI_GraphPatch.cxx)
  target_include_directories(graphpatch BEFORE PRIVATE ${overlay})
  target_compile_definitions(graphpatch PRIVATE GRAPHPATCH_TRACE)
endif()
target_compile_features(graphpatch PRIVATE cxx_std_17)
target_include_directories(graphpatch PRIVATE ${OpenCASCADE_INCLUDE_DIR})
if(NOT OpenCASCADE_BUILD_SHARED_LIBS)
  target_compile_definitions(graphpatch PRIVATE OCCT_STATIC_BUILD _USE_MATH_DEFINES)
endif()
target_link_libraries(graphpatch PRIVATE TKOffset TKFillet TKBool TKBO TKMesh)
