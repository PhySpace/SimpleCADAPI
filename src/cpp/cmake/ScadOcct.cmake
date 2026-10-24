# Locate OpenCASCADE and expose it as one INTERFACE target, scad::occt.
#
# Development builds use the system install (Homebrew `opencascade`, Debian/Ubuntu
# `libocct-*-dev`).  Release wheels use a static OCCT built by
# tools/build_occt.py and selected with -DSCAD_OCCT_PREFIX=<install prefix>, so
# every platform ships the same kernel version.

set(SCAD_OCCT_PREFIX "" CACHE PATH
  "Install prefix of an OpenCASCADE build (the one holding lib/cmake/opencascade)")
set(SCAD_OCCT_MIN_VERSION 7.8)

if(SCAD_OCCT_PREFIX)
  list(PREPEND CMAKE_PREFIX_PATH "${SCAD_OCCT_PREFIX}")
endif()

# OCCT's version file only accepts an exact major.minor match, so find any
# version and enforce the minimum here.
find_package(OpenCASCADE CONFIG REQUIRED)
if(OpenCASCADE_VERSION VERSION_LESS SCAD_OCCT_MIN_VERSION)
  message(FATAL_ERROR
    "OpenCASCADE ${OpenCASCADE_VERSION} is too old; scad needs >= ${SCAD_OCCT_MIN_VERSION} "
    "(the Python SDK this ports runs on 7.9).")
endif()
message(STATUS "OpenCASCADE ${OpenCASCADE_VERSION} (${OpenCASCADE_DIR})")

# Only the toolkits scad uses.  Keeping this list explicit keeps static links
# small and makes a missing toolkit fail at configure time, not at link time.
set(SCAD_OCCT_TOOLKITS
  # Foundation classes
  TKernel TKMath
  # Modeling data
  TKG2d TKG3d TKGeomBase TKBRep
  # Modeling algorithms
  TKGeomAlgo TKTopAlgo TKPrim TKBO TKBool TKShHealing TKFillet TKOffset TKFeat TKMesh TKHLR
  # Data exchange: STEP / STL / BREP-adjacent readers and writers
  TKDE TKXSBase TKDESTEP TKDESTL TKDEIGES
  # XCAF is what STEP assemblies read into.
  TKXCAF TKCAF TKLCAF TKCDF TKService TKRWMesh TKXmlXCAF TKBinXCAF TKBin TKBinL TKXml TKXmlL TKStd TKStdL TKVCAF TKV3d)

add_library(scad_occt INTERFACE)
add_library(scad::occt ALIAS scad_occt)

set(_scad_missing "")
foreach(_tk IN LISTS SCAD_OCCT_TOOLKITS)
  if(TARGET ${_tk})
    target_link_libraries(scad_occt INTERFACE ${_tk})
  else()
    list(APPEND _scad_missing ${_tk})
  endif()
endforeach()
if(_scad_missing)
  message(STATUS "OCCT toolkits not present in this build (skipped): ${_scad_missing}")
endif()

# Every scad source includes OCCT headers by their flat name.
if(OpenCASCADE_INCLUDE_DIR)
  target_include_directories(scad_occt SYSTEM INTERFACE "${OpenCASCADE_INCLUDE_DIR}")
endif()
