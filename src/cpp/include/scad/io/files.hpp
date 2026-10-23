// Portable file access for the io area.
//
// Paths cross the Python boundary as UTF-8 text.  std::filesystem::path is the
// only path type used below that boundary: it is built from a char8_t string
// (so it is correct on Windows, where a narrow `char` path is the ANSI code
// page) and every stream is opened from the path object, never from a narrow
// string.  OpenCASCADE's own `const char*` file entry points are avoided for the
// same reason; the readers and writers here use their std::istream/std::ostream
// overloads.  (OCCT 7.4+ also treats its narrow names as UTF-8 on Windows, which
// is why the few remaining narrow-name calls would work, but a stream does not
// depend on that.)
//
// Files are read and written in binary mode.  Nothing here depends on the
// C locale.
#pragma once

#include <cstddef>
#include <filesystem>
#include <fstream>
#include <ostream>
#include <string>
#include <string_view>

namespace scad::io {

// A byte string.  std::string is the container of choice: it converts to and
// from Python `bytes` and OCCT streams without a copy of its own.
using Bytes = std::string;

inline constexpr std::size_t kDefaultMaxFileBytes = std::size_t{1} << 31;  // 2 GiB

// UTF-8 text <-> path.  Invalid UTF-8 is not rejected here; the file system
// decides what a path means.
std::filesystem::path path_from_utf8(std::string_view utf8);
std::string path_to_utf8(const std::filesystem::path& path);

// Lower-cased extension without the dot ("step" for "a/b.STEP"), "" if none.
std::string extension_of(const std::filesystem::path& path);

// Whole-file helpers.  They throw scad::RuntimeError with the path and the
// reason; the public operations wrap that into a scad::Error.
Bytes read_file(const std::filesystem::path& path, std::size_t max_bytes = kDefaultMaxFileBytes);

// Writes through a temporary file next to the destination and renames it over
// the destination, so a reader never sees a half-written file.
void write_file(const std::filesystem::path& path, std::string_view bytes);

std::ifstream open_for_read(const std::filesystem::path& path);
// Truncating binary output stream; the parent directory must exist.
std::ofstream open_for_write(const std::filesystem::path& path);

// A binary output file that becomes visible only when commit() succeeds: the
// bytes go to a temporary file next to the destination, commit() flushes and
// renames it over the destination, and destruction without commit() removes it.
class AtomicWriter {
 public:
  explicit AtomicWriter(std::filesystem::path destination);
  ~AtomicWriter();
  AtomicWriter(const AtomicWriter&) = delete;
  AtomicWriter& operator=(const AtomicWriter&) = delete;

  std::ostream& stream() noexcept { return out_; }
  void commit();

 private:
  std::filesystem::path destination_;
  std::filesystem::path temporary_;
  std::ofstream out_;
  bool committed_ = false;
};

}  // namespace scad::io
