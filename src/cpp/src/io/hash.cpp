#include "scad/io/hash.hpp"

#include <bit>
#include <cstring>

namespace scad::io {

namespace {

constexpr std::uint32_t rotr(std::uint32_t x, int n) { return std::rotr(x, n); }
constexpr std::uint32_t rotl(std::uint32_t x, int n) { return std::rotl(x, n); }

constexpr std::uint32_t kSha256K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

std::uint32_t load_be32(const unsigned char* p) {
  return (std::uint32_t{p[0]} << 24) | (std::uint32_t{p[1]} << 16) | (std::uint32_t{p[2]} << 8) | p[3];
}
void store_be32(unsigned char* p, std::uint32_t v) {
  p[0] = static_cast<unsigned char>(v >> 24);
  p[1] = static_cast<unsigned char>(v >> 16);
  p[2] = static_cast<unsigned char>(v >> 8);
  p[3] = static_cast<unsigned char>(v);
}
void store_be64(unsigned char* p, std::uint64_t v) {
  store_be32(p, static_cast<std::uint32_t>(v >> 32));
  store_be32(p + 4, static_cast<std::uint32_t>(v));
}

// Merkle-Damgard padding shared by SHA-1 and SHA-256: 0x80, zeros, 64-bit big-endian bit length.
std::string padded(std::string_view data) {
  std::string out(data);
  out.push_back(static_cast<char>(0x80));
  while (out.size() % 64 != 56) out.push_back('\0');
  unsigned char length[8];
  store_be64(length, static_cast<std::uint64_t>(data.size()) * 8U);
  out.append(reinterpret_cast<const char*>(length), 8);
  return out;
}

}  // namespace

Sha256Digest sha256(std::string_view data) noexcept {
  std::uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  const std::string message = padded(data);
  const auto* bytes = reinterpret_cast<const unsigned char*>(message.data());
  for (std::size_t offset = 0; offset < message.size(); offset += 64) {
    std::uint32_t w[64];
    for (int i = 0; i < 16; ++i) w[i] = load_be32(bytes + offset + 4 * static_cast<std::size_t>(i));
    for (int i = 16; i < 64; ++i) {
      const std::uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
      const std::uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    std::uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; ++i) {
      const std::uint32_t big1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const std::uint32_t ch = (e & f) ^ (~e & g);
      const std::uint32_t t1 = hh + big1 + ch + kSha256K[i] + w[i];
      const std::uint32_t big0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const std::uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      const std::uint32_t t2 = big0 + maj;
      hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }
  Sha256Digest digest{};
  for (std::size_t i = 0; i < 8; ++i) store_be32(digest.data() + 4 * i, h[i]);
  return digest;
}

Sha1Digest sha1(std::string_view data) noexcept {
  std::uint32_t h[5] = {0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0};
  const std::string message = padded(data);
  const auto* bytes = reinterpret_cast<const unsigned char*>(message.data());
  for (std::size_t offset = 0; offset < message.size(); offset += 64) {
    std::uint32_t w[80];
    for (int i = 0; i < 16; ++i) w[i] = load_be32(bytes + offset + 4 * static_cast<std::size_t>(i));
    for (int i = 16; i < 80; ++i) w[i] = rotl(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    std::uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4];
    for (int i = 0; i < 80; ++i) {
      std::uint32_t f, k;
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5A827999; }
      else if (i < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1; }
      else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDC; }
      else { f = b ^ c ^ d; k = 0xCA62C1D6; }
      const std::uint32_t t = rotl(a, 5) + f + e + k + w[i];
      e = d; d = c; c = rotl(b, 30); b = a; a = t;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e;
  }
  Sha1Digest digest{};
  for (std::size_t i = 0; i < 5; ++i) store_be32(digest.data() + 4 * i, h[i]);
  return digest;
}

std::string to_hex(const std::uint8_t* bytes, std::size_t count) {
  static constexpr char kDigits[] = "0123456789abcdef";
  std::string out;
  out.reserve(count * 2);
  for (std::size_t i = 0; i < count; ++i) {
    out.push_back(kDigits[bytes[i] >> 4]);
    out.push_back(kDigits[bytes[i] & 0x0f]);
  }
  return out;
}

std::string sha256_hex(std::string_view data) {
  const Sha256Digest digest = sha256(data);
  return to_hex(digest.data(), digest.size());
}

std::string sha256_tagged(std::string_view data) { return "sha256:" + sha256_hex(data); }

std::string uuid5_url_hex(std::string_view name) {
  // uuid.NAMESPACE_URL = 6ba7b811-9dad-11d1-80b4-00c04fd430c8
  static constexpr unsigned char kNamespaceUrl[16] = {0x6b, 0xa7, 0xb8, 0x11, 0x9d, 0xad, 0x11, 0xd1,
                                                      0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8};
  std::string input(reinterpret_cast<const char*>(kNamespaceUrl), sizeof kNamespaceUrl);
  input.append(name);
  const Sha1Digest digest = sha1(input);
  std::array<std::uint8_t, 16> uuid{};
  std::memcpy(uuid.data(), digest.data(), uuid.size());
  uuid[6] = static_cast<std::uint8_t>((uuid[6] & 0x0f) | 0x50);  // version 5
  uuid[8] = static_cast<std::uint8_t>((uuid[8] & 0x3f) | 0x80);  // RFC 4122 variant
  return to_hex(uuid.data(), uuid.size());
}

std::uint32_t crc32(std::string_view data, std::uint32_t seed) noexcept {
  static const auto kTable = [] {
    std::array<std::uint32_t, 256> table{};
    for (std::uint32_t i = 0; i < 256; ++i) {
      std::uint32_t c = i;
      for (int k = 0; k < 8; ++k) c = (c & 1U) ? (0xEDB88320U ^ (c >> 1)) : (c >> 1);
      table[i] = c;
    }
    return table;
  }();
  std::uint32_t crc = ~seed;
  for (const char ch : data) crc = kTable[(crc ^ static_cast<unsigned char>(ch)) & 0xffU] ^ (crc >> 8);
  return ~crc;
}

}  // namespace scad::io
