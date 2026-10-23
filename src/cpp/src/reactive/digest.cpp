#include "scad/reactive/digest.hpp"

#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace scad::reactive {

namespace {

constexpr std::array<std::uint32_t, 64> kRound = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

constexpr std::uint32_t rotr(std::uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

class Sha256 {
 public:
  void update(std::string_view data) {
    for (const char c : data) {
      block_[used_++] = static_cast<std::uint8_t>(c);
      if (used_ == 64) {
        compress();
        used_ = 0;
      }
    }
    length_ += data.size();
  }

  std::string finish() {
    const std::uint64_t bits = static_cast<std::uint64_t>(length_) * 8;
    block_[used_++] = 0x80;
    if (used_ > 56) {
      while (used_ < 64) block_[used_++] = 0;
      compress();
      used_ = 0;
    }
    while (used_ < 56) block_[used_++] = 0;
    for (int i = 7; i >= 0; --i) block_[used_++] = static_cast<std::uint8_t>(bits >> (8 * i));
    compress();
    static constexpr char kHex[] = "0123456789abcdef";
    std::string out;
    out.reserve(64);
    for (const std::uint32_t word : state_) {
      for (int i = 28; i >= 0; i -= 4) out += kHex[(word >> i) & 0xf];
    }
    return out;
  }

 private:
  void compress() {
    std::array<std::uint32_t, 64> w{};
    for (std::size_t i = 0; i < 16; ++i) {
      w[i] = (std::uint32_t{block_[4 * i]} << 24) | (std::uint32_t{block_[4 * i + 1]} << 16) |
             (std::uint32_t{block_[4 * i + 2]} << 8) | std::uint32_t{block_[4 * i + 3]};
    }
    for (std::size_t i = 16; i < 64; ++i) {
      const std::uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
      const std::uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    std::uint32_t a = state_[0], b = state_[1], c = state_[2], d = state_[3];
    std::uint32_t e = state_[4], f = state_[5], g = state_[6], h = state_[7];
    for (std::size_t i = 0; i < 64; ++i) {
      const std::uint32_t s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const std::uint32_t ch = (e & f) ^ (~e & g);
      const std::uint32_t t1 = h + s1 + ch + kRound[i] + w[i];
      const std::uint32_t s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const std::uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      const std::uint32_t t2 = s0 + maj;
      h = g;
      g = f;
      f = e;
      e = d + t1;
      d = c;
      c = b;
      b = a;
      a = t1 + t2;
    }
    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
  }

  std::array<std::uint32_t, 8> state_{0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  std::array<std::uint8_t, 64> block_{};
  std::size_t used_ = 0;
  std::size_t length_ = 0;
};

// The shortest decimal digits that read back as `value` (positive, finite),
// and the exponent of the first digit.
struct Shortest {
  std::string digits;
  int exponent10 = 0;
};

Shortest shortest_digits(double value) {
  char buf[48];
  for (int precision = 0; precision <= 16; ++precision) {
    std::snprintf(buf, sizeof buf, "%.*e", precision, value);
    if (std::strtod(buf, nullptr) == value || precision == 16) break;
  }
  Shortest out;
  const char* p = buf;
  for (; *p != 'e' && *p != '\0'; ++p) {
    if (*p != '.') out.digits += *p;
  }
  if (*p == 'e') out.exponent10 = std::atoi(p + 1);
  while (out.digits.size() > 1 && out.digits.back() == '0') out.digits.pop_back();
  return out;
}

}  // namespace

std::string sha256_hex(std::string_view data) {
  Sha256 hash;
  hash.update(data);
  return hash.finish();
}

std::string py_float_hex(double value) {
  if (std::isnan(value)) return "nan";
  if (std::isinf(value)) return value < 0 ? "-inf" : "inf";
  const auto bits = std::bit_cast<std::uint64_t>(value);
  const bool negative = (bits >> 63) != 0;
  const int biased = static_cast<int>((bits >> 52) & 0x7ff);
  const std::uint64_t fraction = bits & ((std::uint64_t{1} << 52) - 1);
  std::string out = negative ? "-0x" : "0x";
  if (biased == 0 && fraction == 0) return out + "0.0p+0";
  char buf[32];
  std::snprintf(buf, sizeof buf, "%013llx", static_cast<unsigned long long>(fraction));
  const int exponent = biased == 0 ? -1022 : biased - 1023;
  out += biased == 0 ? "0." : "1.";
  out += buf;
  out += exponent < 0 ? "p-" : "p+";
  out += std::to_string(exponent < 0 ? -exponent : exponent);
  return out;
}

std::string py_float_repr(double value) {
  if (std::isnan(value)) return "nan";
  if (std::isinf(value)) return value < 0 ? "-inf" : "inf";
  std::string sign = std::signbit(value) ? "-" : "";
  if (value == 0.0) return sign + "0.0";
  const Shortest s = shortest_digits(std::fabs(value));
  const int decpt = s.exponent10 + 1;  // position of the decimal point within the digits
  const int count = static_cast<int>(s.digits.size());
  if (decpt > -4 && decpt <= 16) {
    if (decpt <= 0) return sign + "0." + std::string(static_cast<std::size_t>(-decpt), '0') + s.digits;
    if (decpt >= count) {
      return sign + s.digits + std::string(static_cast<std::size_t>(decpt - count), '0') + ".0";
    }
    return sign + s.digits.substr(0, static_cast<std::size_t>(decpt)) + "." +
           s.digits.substr(static_cast<std::size_t>(decpt));
  }
  std::string out = sign + s.digits.substr(0, 1);
  if (count > 1) out += "." + s.digits.substr(1);
  const int exponent = decpt - 1;
  char buf[16];
  std::snprintf(buf, sizeof buf, "e%c%02d", exponent < 0 ? '-' : '+', exponent < 0 ? -exponent : exponent);
  return out + buf;
}

std::string py_str_repr(std::string_view text) {
  const bool has_single = text.find('\'') != std::string_view::npos;
  const bool has_double = text.find('"') != std::string_view::npos;
  const char quote = (has_single && !has_double) ? '"' : '\'';
  std::string out(1, quote);
  for (const char raw : text) {
    const auto c = static_cast<unsigned char>(raw);
    if (c == static_cast<unsigned char>(quote) || c == '\\') {
      out += '\\';
      out += raw;
    } else if (c == '\n') {
      out += "\\n";
    } else if (c == '\r') {
      out += "\\r";
    } else if (c == '\t') {
      out += "\\t";
    } else if (c < 0x20 || c == 0x7f) {
      char buf[8];
      std::snprintf(buf, sizeof buf, "\\x%02x", c);
      out += buf;
    } else {
      out += raw;
    }
  }
  out += quote;
  return out;
}

}  // namespace scad::reactive
