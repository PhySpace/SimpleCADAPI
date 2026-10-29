#include "scad/io/files.hpp"

#include <atomic>
#include <cctype>
#include <chrono>
#include <system_error>

#include "scad/core/error.hpp"

namespace scad::io {

namespace fs = std::filesystem;

namespace {

[[noreturn]] void fail(const char* what, const fs::path& path, const std::string& reason) {
  throw RuntimeError(std::string(what) + " '" + path_to_utf8(path) + "': " + reason);
}

std::string errno_text(const std::error_code& ec) {
  return ec ? ec.message() : "unknown error";
}

// "<name>.<pid-free unique>.tmp" next to the destination; unique per process
// and call, which is all that is needed for a rename-into-place scheme.
fs::path temporary_name(const fs::path& destination) {
  static std::atomic<unsigned long long> counter{0};
  const auto stamp = static_cast<unsigned long long>(std::chrono::steady_clock::now().time_since_epoch().count());
  fs::path name = destination.filename();
  name += fs::path(".scad-" + std::to_string(stamp) + "-" + std::to_string(counter.fetch_add(1)) + ".tmp");
  fs::path result = destination;
  result.replace_filename(name);
  return result;
}

}  // namespace

fs::path path_from_utf8(std::string_view utf8) {
  const std::u8string text(reinterpret_cast<const char8_t*>(utf8.data()), utf8.size());
  return fs::path(text);
}

std::string path_to_utf8(const fs::path& path) {
  const std::u8string text = path.u8string();
  return std::string(reinterpret_cast<const char*>(text.data()), text.size());
}

std::string extension_of(const fs::path& path) {
  std::string ext = path_to_utf8(path.extension());
  if (!ext.empty() && ext.front() == '.')
    ext.erase(ext.begin());
  for (char& c : ext)
    c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  return ext;
}

Bytes read_file(const fs::path& path, std::size_t max_bytes) {
  std::error_code ec;
  const auto status = fs::status(path, ec);
  if (ec || !fs::exists(status))
    fail("cannot read", path, ec ? errno_text(ec) : "no such file");
  if (!fs::is_regular_file(status))
    fail("cannot read", path, "not a regular file");
  std::ifstream in(path, std::ios::binary);
  if (!in)
    fail("cannot open", path, "the file could not be opened for reading");
  in.seekg(0, std::ios::end);
  const std::streamoff size = in.tellg();
  if (size < 0)
    fail("cannot read", path, "the file size could not be determined");
  if (static_cast<unsigned long long>(size) > max_bytes)
    fail("cannot read", path, "the file is larger than the allowed " + std::to_string(max_bytes) + " bytes");
  in.seekg(0, std::ios::beg);
  Bytes data(static_cast<std::size_t>(size), '\0');
  if (size > 0)
    in.read(data.data(), size);
  if (!in && !in.eof())
    fail("cannot read", path, "a read error occurred");
  if (in.gcount() != size)
    fail("cannot read", path, "the file changed while it was being read");
  return data;
}

void write_file(const fs::path& path, std::string_view bytes) {
  AtomicWriter writer(path);
  writer.stream().write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
  writer.commit();
}

std::ifstream open_for_read(const fs::path& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in)
    fail("cannot open", path, "the file could not be opened for reading");
  return in;
}

std::ofstream open_for_write(const fs::path& path) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out)
    fail("cannot open", path, "the file could not be opened for writing");
  return out;
}

AtomicWriter::AtomicWriter(fs::path destination) : destination_(std::move(destination)) {
  std::error_code ec;
  if (fs::is_directory(destination_, ec))
    fail("cannot write", destination_, "it is a directory");
  temporary_ = temporary_name(destination_);
  out_.open(temporary_, std::ios::binary | std::ios::trunc);
  if (!out_) {
    fail("cannot write", destination_, "the file could not be created (does the directory exist and is it writable?)");
  }
}

AtomicWriter::~AtomicWriter() {
  if (committed_)
    return;
  out_.close();
  std::error_code ignored;
  fs::remove(temporary_, ignored);
}

void AtomicWriter::commit() {
  out_.flush();
  if (!out_)
    fail("cannot write", destination_, "a write error occurred (disk full?)");
  out_.close();
  if (out_.fail())
    fail("cannot write", destination_, "closing the file failed");
  std::error_code ec;
  fs::rename(temporary_, destination_, ec);
  if (ec)
    fail("cannot write", destination_, "renaming the finished file into place failed: " + errno_text(ec));
  committed_ = true;
}

}  // namespace scad::io
