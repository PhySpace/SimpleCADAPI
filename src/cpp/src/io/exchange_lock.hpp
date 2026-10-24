// OpenCASCADE's STEP/IGES translators read and write process-global parameters
// (Interface_Static).  Every STEP read or write takes this lock (internal).
#pragma once

#include <mutex>

namespace scad::io::detail {

inline std::mutex& data_exchange_mutex() {
  static std::mutex mutex;
  return mutex;
}

}  // namespace scad::io::detail
