// Digests the io formats and the provenance bindings need.
//
// Self-contained (no OpenSSL, no OCCT): SHA-256 for artifact integrity, SHA-1
// only because uuid5 is defined over it (the Python SDK derives deterministic
// tag-binding ids with uuid.uuid5), CRC-32 for the shape serialization frame.
#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <string_view>

namespace scad::io {

using Sha256Digest = std::array<std::uint8_t, 32>;
using Sha1Digest = std::array<std::uint8_t, 20>;

Sha256Digest sha256(std::string_view data) noexcept;
std::string sha256_hex(std::string_view data);       // 64 lower-case hex characters
std::string sha256_tagged(std::string_view data);    // "sha256:<hex>", the artifact digest spelling
Sha1Digest sha1(std::string_view data) noexcept;

std::string to_hex(const std::uint8_t* bytes, std::size_t count);

// uuid.uuid5(uuid.NAMESPACE_URL, name).hex -- 32 lower-case hex characters.
std::string uuid5_url_hex(std::string_view name);

// CRC-32 (IEEE 802.3, the zlib/PNG polynomial).
std::uint32_t crc32(std::string_view data, std::uint32_t seed = 0) noexcept;

}  // namespace scad::io
