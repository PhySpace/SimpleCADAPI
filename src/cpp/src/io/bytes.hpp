// Byte-level building blocks for the io formats (internal).
#pragma once

#include <bit>
#include <cstdint>
#include <cstring>
#include <istream>
#include <streambuf>
#include <string>
#include <string_view>

#include "scad/core/error.hpp"
#include "scad/core/value.hpp"

namespace scad::io::detail {

// A read-only std::istream over memory: lets OCCT's stream readers consume a
// buffer without copying it into an istringstream.
class ViewBuf final : public std::streambuf {
 public:
  explicit ViewBuf(std::string_view view) {
    char* begin = const_cast<char*>(view.data());  // never written through: input only
    setg(begin, begin, begin + view.size());
  }

 protected:
  pos_type seekoff(off_type off, std::ios_base::seekdir dir, std::ios_base::openmode which) override {
    if ((which & std::ios_base::in) == 0)
      return pos_type(off_type(-1));
    char* base = eback();
    off_type target = 0;
    switch (dir) {
      case std::ios_base::beg:
        target = off;
        break;
      case std::ios_base::cur:
        target = (gptr() - base) + off;
        break;
      case std::ios_base::end:
        target = (egptr() - base) + off;
        break;
      default:
        return pos_type(off_type(-1));
    }
    if (target < 0 || target > egptr() - base)
      return pos_type(off_type(-1));
    setg(base, base + target, egptr());
    return pos_type(target);
  }
  pos_type seekpos(pos_type pos, std::ios_base::openmode which) override {
    return seekoff(off_type(pos), std::ios_base::beg, which);
  }
};

class ViewStream final : public std::istream {
 public:
  explicit ViewStream(std::string_view view) : std::istream(nullptr), buf_(view) { rdbuf(&buf_); }

 private:
  ViewBuf buf_;
};

// Big-endian writer.
class ByteWriter {
 public:
  void u8(std::uint8_t v) { out_.push_back(static_cast<char>(v)); }
  void u16(std::uint16_t v) { be(v); }
  void u32(std::uint32_t v) { be(v); }
  void u64(std::uint64_t v) { be(v); }
  void f64(double v) { u64(std::bit_cast<std::uint64_t>(v)); }
  // LEB128 unsigned varint.
  void varuint(std::uint64_t v) {
    while (v >= 0x80) {
      u8(static_cast<std::uint8_t>(v | 0x80));
      v >>= 7;
    }
    u8(static_cast<std::uint8_t>(v));
  }
  void raw(std::string_view bytes) { out_.append(bytes); }
  void str(std::string_view s) {
    varuint(s.size());
    raw(s);
  }
  std::string& buffer() noexcept { return out_; }
  std::string take() { return std::move(out_); }

 private:
  template <class T>
  void be(T v) {
    for (int shift = static_cast<int>(sizeof(T)) * 8 - 8; shift >= 0; shift -= 8)
      out_.push_back(static_cast<char>((v >> shift) & 0xFF));
  }
  std::string out_;
};

// Big-endian reader; every read is bounds-checked and throws ValueError.
class ByteReader {
 public:
  explicit ByteReader(std::string_view data, std::string what = "data") : data_(data), what_(std::move(what)) {}

  std::size_t remaining() const noexcept { return data_.size() - pos_; }
  std::size_t position() const noexcept { return pos_; }

  std::uint8_t u8() { return static_cast<std::uint8_t>(take(1)[0]); }
  std::uint16_t u16() { return static_cast<std::uint16_t>(be(2)); }
  std::uint32_t u32() { return static_cast<std::uint32_t>(be(4)); }
  std::uint64_t u64() { return be(8); }
  double f64() { return std::bit_cast<double>(u64()); }
  std::uint64_t varuint() {
    std::uint64_t value = 0;
    for (int shift = 0; shift < 64; shift += 7) {
      const std::uint8_t byte = u8();
      value |= static_cast<std::uint64_t>(byte & 0x7F) << shift;
      if ((byte & 0x80) == 0)
        return value;
    }
    throw ValueError(what_ + " is corrupt: an integer is too long");
  }
  std::string_view bytes(std::size_t count) { return take(count); }
  std::string_view str() {
    const std::uint64_t length = varuint();
    if (length > remaining())
      truncated();
    return take(static_cast<std::size_t>(length));
  }

 private:
  [[noreturn]] void truncated() const { throw ValueError(what_ + " is truncated"); }
  std::string_view take(std::size_t count) {
    if (count > remaining())
      truncated();
    const std::string_view view = data_.substr(pos_, count);
    pos_ += count;
    return view;
  }
  std::uint64_t be(std::size_t count) {
    const std::string_view view = take(count);
    std::uint64_t value = 0;
    for (const char c : view)
      value = (value << 8) | static_cast<unsigned char>(c);
    return value;
  }

  std::string_view data_;
  std::string what_;
  std::size_t pos_ = 0;
};

// scad::Value <-> bytes.  Tags: 0 null, 1 false, 2 true, 3 int (zigzag varint),
// 4 double (IEEE-754 bits, big-endian), 5 string, 6 array, 7 object (insertion order).
void encode_value(ByteWriter& out, const Value& value);
Value decode_value(ByteReader& in, int max_depth = 64);

}  // namespace scad::io::detail
