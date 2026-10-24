# Developer probes (cmake -DSCAD_BUILD_BENCH=ON).  Not part of the product.
add_executable(probe probe.cpp)
scad_apply_compile_options(probe)
target_include_directories(probe PRIVATE "${PROJECT_SOURCE_DIR}/src/topo")
target_link_libraries(probe PRIVATE scad_ops_features scad_ops_geometry scad_ql scad_reactive)
