# Compiler flags shared by every scad target.
#
# Portable on purpose: this file is the only place that knows about MSVC vs
# GCC/Clang, so the sources stay free of compiler-specific switches.

function(scad_apply_compile_options target)
  if(MSVC)
    target_compile_options(${target} PRIVATE
      /W4 /permissive- /utf-8 /EHsc /Zc:__cplusplus /bigobj
      # OCCT headers trigger these and they are not actionable here.
      /wd4251 /wd4275 /wd4100 /wd4127 /wd4244 /wd4267 /wd4996)
    target_compile_definitions(${target} PRIVATE
      NOMINMAX WIN32_LEAN_AND_MEAN _USE_MATH_DEFINES _CRT_SECURE_NO_WARNINGS)
    if(SCAD_WARNINGS_AS_ERRORS)
      target_compile_options(${target} PRIVATE /WX)
    endif()
  else()
    target_compile_options(${target} PRIVATE
      -Wall -Wextra -Wpedantic -Wshadow -Wnon-virtual-dtor -Woverloaded-virtual
      -Wconversion -Wno-sign-conversion
      # Option structs are brace-initialised with trailing members left defaulted; GCC
      # (unlike Clang) warns about that under -Wextra.
      -Wno-missing-field-initializers
      # OCCT headers are not -Wconversion clean; keep the noise out of our own diagnostics.
      -Wno-deprecated-declarations)
    if(SCAD_WARNINGS_AS_ERRORS)
      target_compile_options(${target} PRIVATE -Werror)
    endif()
    # Debug builds bounds-check the standard library on both implementations (each macro is
    # inert on the other), so an out-of-range vector[] fails at the access, on macOS as on Linux.
    target_compile_definitions(${target} PRIVATE
      $<$<CONFIG:Debug>:_GLIBCXX_ASSERTIONS>
      $<$<CONFIG:Debug>:_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE>)
    if(SCAD_SANITIZE)
      target_compile_options(${target} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
      target_link_options(${target} PRIVATE -fsanitize=address,undefined)
    endif()
  endif()
endfunction()
