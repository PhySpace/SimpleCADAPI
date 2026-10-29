#include "scad/io/json.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <limits>
#include <utility>
#include <vector>

#include "numfmt.hpp"
#include "scad/core/error.hpp"

namespace scad::io {

namespace {

// ---------------------------------------------------------------------------
// UTF-8 / UTF-16 helpers
// ---------------------------------------------------------------------------
// Decodes one code point starting at text[i]; returns false on malformed input
// (overlong forms, surrogates, > U+10FFFF).  Advances i past the sequence.
bool decode_utf8(std::string_view text, std::size_t& i, std::uint32_t& cp) {
  const auto b = [&](std::size_t k) { return static_cast<unsigned char>(text[k]); };
  const unsigned char lead = b(i);
  std::size_t extra = 0;
  std::uint32_t min = 0;
  if (lead < 0x80) {
    cp = lead;
    ++i;
    return true;
  }
  if ((lead & 0xE0) == 0xC0) {
    extra = 1;
    cp = lead & 0x1F;
    min = 0x80;
  } else if ((lead & 0xF0) == 0xE0) {
    extra = 2;
    cp = lead & 0x0F;
    min = 0x800;
  } else if ((lead & 0xF8) == 0xF0) {
    extra = 3;
    cp = lead & 0x07;
    min = 0x10000;
  } else
    return false;
  if (i + extra >= text.size())
    return false;
  for (std::size_t k = 1; k <= extra; ++k) {
    if ((b(i + k) & 0xC0) != 0x80)
      return false;
    cp = (cp << 6) | (b(i + k) & 0x3F);
  }
  if (cp < min || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF))
    return false;
  i += extra + 1;
  return true;
}

void append_utf8(std::string& out, std::uint32_t cp) {
  if (cp < 0x80) {
    out.push_back(static_cast<char>(cp));
  } else if (cp < 0x800) {
    out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
    out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else if (cp < 0x10000) {
    out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
    out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else {
    out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
    out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  }
}

std::u16string to_utf16(std::string_view utf8) {
  std::u16string out;
  std::size_t i = 0;
  while (i < utf8.size()) {
    std::uint32_t cp = 0;
    if (!decode_utf8(utf8, i, cp)) {  // a Value string is expected to be UTF-8; keep going on garbage
      cp = 0xFFFD;
      ++i;
    }
    if (cp >= 0x10000) {
      cp -= 0x10000;
      out.push_back(static_cast<char16_t>(0xD800 + (cp >> 10)));
      out.push_back(static_cast<char16_t>(0xDC00 + (cp & 0x3FF)));
    } else {
      out.push_back(static_cast<char16_t>(cp));
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------
class Parser {
 public:
  Parser(std::string_view text, const JsonParseOptions& options) : text_(text), options_(options) {}

  Value parse() {
    skip_space();
    Value value = parse_value(0);
    skip_space();
    if (pos_ != text_.size())
      fail("unexpected data after the JSON document");
    return value;
  }

 private:
  [[noreturn]] void fail(const std::string& what) const {
    throw ValueError("invalid JSON at byte " + std::to_string(pos_) + ": " + what);
  }

  void skip_space() {
    while (pos_ < text_.size()) {
      const char c = text_[pos_];
      if (c != ' ' && c != '\t' && c != '\n' && c != '\r')
        break;
      ++pos_;
    }
  }

  bool consume(char expected) {
    if (pos_ < text_.size() && text_[pos_] == expected) {
      ++pos_;
      return true;
    }
    return false;
  }

  void expect_word(std::string_view word) {
    if (text_.substr(pos_, word.size()) != word)
      fail("unknown literal");
    pos_ += word.size();
  }

  Value parse_value(int depth) {
    if (depth > options_.max_depth)
      fail("nesting is too deep");
    if (pos_ >= text_.size())
      fail("unexpected end of input");
    switch (text_[pos_]) {
      case '{':
        return parse_object(depth);
      case '[':
        return parse_array(depth);
      case '"':
        return Value(parse_string());
      case 't':
        expect_word("true");
        return Value(true);
      case 'f':
        expect_word("false");
        return Value(false);
      case 'n':
        expect_word("null");
        return Value();
      default:
        return parse_number();
    }
  }

  Value parse_object(int depth) {
    ++pos_;  // '{'
    Value object = Value::object();
    skip_space();
    if (consume('}'))
      return object;
    while (true) {
      skip_space();
      if (pos_ >= text_.size() || text_[pos_] != '"')
        fail("expected an object member name");
      std::string key = parse_string();
      skip_space();
      if (!consume(':'))
        fail("expected ':' after a member name");
      skip_space();
      Value member = parse_value(depth + 1);
      if (options_.reject_duplicate_members && object.find(key) != nullptr)
        fail("duplicate object member '" + key + "'");
      object.set(std::move(key), std::move(member));
      skip_space();
      if (consume(','))
        continue;
      if (consume('}'))
        return object;
      fail("expected ',' or '}' in an object");
    }
  }

  Value parse_array(int depth) {
    ++pos_;  // '['
    Value array = Value::array();
    skip_space();
    if (consume(']'))
      return array;
    while (true) {
      skip_space();
      array.push_back(parse_value(depth + 1));
      skip_space();
      if (consume(','))
        continue;
      if (consume(']'))
        return array;
      fail("expected ',' or ']' in an array");
    }
  }

  std::uint32_t parse_hex4() {
    if (pos_ + 4 > text_.size())
      fail("truncated \\u escape");
    std::uint32_t value = 0;
    for (int i = 0; i < 4; ++i) {
      const char c = text_[pos_++];
      value <<= 4;
      if (c >= '0' && c <= '9')
        value |= static_cast<std::uint32_t>(c - '0');
      else if (c >= 'a' && c <= 'f')
        value |= static_cast<std::uint32_t>(c - 'a' + 10);
      else if (c >= 'A' && c <= 'F')
        value |= static_cast<std::uint32_t>(c - 'A' + 10);
      else
        fail("bad hex digit in a \\u escape");
    }
    return value;
  }

  std::string parse_string() {
    ++pos_;  // opening quote
    std::string out;
    while (true) {
      if (pos_ >= text_.size())
        fail("unterminated string");
      const auto c = static_cast<unsigned char>(text_[pos_]);
      if (c == '"') {
        ++pos_;
        return out;
      }
      if (c < 0x20)
        fail("unescaped control character in a string");
      if (c != '\\') {
        std::size_t next = pos_;
        std::uint32_t cp = 0;
        if (!decode_utf8(text_, next, cp))
          fail("invalid UTF-8");
        out.append(text_.substr(pos_, next - pos_));
        pos_ = next;
        continue;
      }
      ++pos_;
      if (pos_ >= text_.size())
        fail("unterminated escape");
      const char e = text_[pos_++];
      switch (e) {
        case '"':
          out.push_back('"');
          break;
        case '\\':
          out.push_back('\\');
          break;
        case '/':
          out.push_back('/');
          break;
        case 'b':
          out.push_back('\b');
          break;
        case 'f':
          out.push_back('\f');
          break;
        case 'n':
          out.push_back('\n');
          break;
        case 'r':
          out.push_back('\r');
          break;
        case 't':
          out.push_back('\t');
          break;
        case 'u': {
          std::uint32_t cp = parse_hex4();
          if (cp >= 0xD800 && cp <= 0xDBFF) {
            if (text_.substr(pos_, 2) != "\\u")
              fail("lone high surrogate");
            pos_ += 2;
            const std::uint32_t low = parse_hex4();
            if (low < 0xDC00 || low > 0xDFFF)
              fail("invalid low surrogate");
            cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
          } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
            fail("lone low surrogate");
          }
          append_utf8(out, cp);
          break;
        }
        default:
          fail("unknown escape sequence");
      }
    }
  }

  Value parse_number() {
    const std::size_t start = pos_;
    consume('-');
    if (pos_ >= text_.size())
      fail("expected a number");
    if (text_[pos_] == '0') {
      ++pos_;
    } else if (text_[pos_] >= '1' && text_[pos_] <= '9') {
      while (pos_ < text_.size() && text_[pos_] >= '0' && text_[pos_] <= '9')
        ++pos_;
    } else {
      fail("expected a value");
    }
    bool integral = true;
    if (pos_ < text_.size() && text_[pos_] == '.') {
      integral = false;
      ++pos_;
      const std::size_t digits = pos_;
      while (pos_ < text_.size() && text_[pos_] >= '0' && text_[pos_] <= '9')
        ++pos_;
      if (pos_ == digits)
        fail("expected digits after the decimal point");
    }
    if (pos_ < text_.size() && (text_[pos_] == 'e' || text_[pos_] == 'E')) {
      integral = false;
      ++pos_;
      if (pos_ < text_.size() && (text_[pos_] == '+' || text_[pos_] == '-'))
        ++pos_;
      const std::size_t digits = pos_;
      while (pos_ < text_.size() && text_[pos_] >= '0' && text_[pos_] <= '9')
        ++pos_;
      if (pos_ == digits)
        fail("expected digits in the exponent");
    }
    const std::string_view token = text_.substr(start, pos_ - start);
    if (integral) {
      std::int64_t value = 0;
      const char* first = token.data();
      const auto result = std::from_chars(first, first + token.size(), value);
      if (result.ec == std::errc() && result.ptr == first + token.size())
        return Value(value);
    }
    double value = 0.0;
    if (!detail::parse_double(token, value) || !std::isfinite(value))
      fail("number is out of range");
    return Value(value);
  }

  std::string_view text_;
  const JsonParseOptions& options_;
  std::size_t pos_ = 0;
};

// ---------------------------------------------------------------------------
// Writers
// ---------------------------------------------------------------------------
void escape_minimal(std::string_view s, std::string& out) {  // RFC 8785 section 3.2.2.2
  out.push_back('"');
  for (const char ch : s) {
    const auto c = static_cast<unsigned char>(ch);
    switch (c) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\b':
        out += "\\b";
        break;
      case '\t':
        out += "\\t";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\f':
        out += "\\f";
        break;
      case '\r':
        out += "\\r";
        break;
      default:
        if (c < 0x20) {
          static constexpr char kHex[] = "0123456789abcdef";
          out += "\\u00";
          out.push_back(kHex[c >> 4]);
          out.push_back(kHex[c & 0x0f]);
        } else {
          out.push_back(ch);
        }
    }
  }
  out.push_back('"');
}

void escape_python(std::string_view s, bool ensure_ascii, std::string& out) {
  static constexpr char kHex[] = "0123456789abcdef";
  const auto unit = [&](std::uint32_t u) {
    out += "\\u";
    for (int shift = 12; shift >= 0; shift -= 4)
      out.push_back(kHex[(u >> shift) & 0xF]);
  };
  out.push_back('"');
  std::size_t i = 0;
  while (i < s.size()) {
    std::uint32_t cp = 0;
    const std::size_t begin = i;
    if (!decode_utf8(s, i, cp)) {
      cp = 0xFFFD;
      i = begin + 1;
    }
    switch (cp) {
      case '"':
        out += "\\\"";
        continue;
      case '\\':
        out += "\\\\";
        continue;
      case '\n':
        out += "\\n";
        continue;
      case '\r':
        out += "\\r";
        continue;
      case '\t':
        out += "\\t";
        continue;
      case '\b':
        out += "\\b";
        continue;
      case '\f':
        out += "\\f";
        continue;
      default:
        break;
    }
    if (cp >= 0x20 && cp < 0x7f) {
      out.push_back(static_cast<char>(cp));
    } else if (!ensure_ascii && cp >= 0x80) {
      append_utf8(out, cp);
    } else if (cp >= 0x10000) {
      const std::uint32_t v = cp - 0x10000;
      unit(0xD800 + (v >> 10));
      unit(0xDC00 + (v & 0x3FF));
    } else {
      unit(cp);
    }
  }
  out.push_back('"');
}

struct CanonicalStyle {
  static void number(double d, std::string& out) {
    if (!std::isfinite(d))
      throw ValueError("JSON cannot represent a non-finite number");
    out += detail::format_es6(d);
  }
  static void string(const std::string& s, std::string& out) { escape_minimal(s, out); }
  static constexpr const char* kItemSeparator = ",";
  static constexpr const char* kKeySeparator = ":";
  static bool less(const std::string& a, const std::string& b) { return to_utf16(a) < to_utf16(b); }
};

struct PythonStyle {
  bool ensure_ascii;
  bool sort_keys;
  void number(double d, std::string& out) const {
    if (std::isnan(d))
      out += "NaN";
    else if (std::isinf(d))
      out += d > 0 ? "Infinity" : "-Infinity";
    else
      out += detail::format_python_repr(d);
  }
  void string(const std::string& s, std::string& out) const { escape_python(s, ensure_ascii, out); }
  static constexpr const char* kItemSeparator = ", ";
  static constexpr const char* kKeySeparator = ": ";
  static bool less(const std::string& a, const std::string& b) { return a < b; }  // UTF-8 order == code point order
};

template <class Style>
void write(const Value& v, std::string& out, const Style& style, bool sort_members) {
  if (v.is_null()) {
    out += "null";
  } else if (v.is_bool()) {
    out += v.as_bool() ? "true" : "false";
  } else if (v.is_int()) {
    out += std::to_string(v.as_int());
  } else if (v.is_double()) {
    style.number(v.as_double(), out);
  } else if (v.is_string()) {
    style.string(v.as_string(), out);
  } else if (v.is_array()) {
    out.push_back('[');
    bool first = true;
    for (const Value& item : v.as_array()) {
      if (!first)
        out += Style::kItemSeparator;
      first = false;
      write(item, out, style, sort_members);
    }
    out.push_back(']');
  } else {
    std::vector<const Value::Member*> members;
    for (const auto& member : v.as_object())
      members.push_back(&member);
    if (sort_members) {
      std::stable_sort(members.begin(), members.end(),
                       [](const Value::Member* a, const Value::Member* b) { return Style::less(a->first, b->first); });
    }
    out.push_back('{');
    bool first = true;
    for (const Value::Member* member : members) {
      if (!first)
        out += Style::kItemSeparator;
      first = false;
      style.string(member->first, out);
      out += Style::kKeySeparator;
      write(member->second, out, style, sort_members);
    }
    out.push_back('}');
  }
}

}  // namespace

Value parse_json(std::string_view text, const JsonParseOptions& options) {
  return Parser(text, options).parse();
}

std::string canonical_json(const Value& value) {
  std::string out;
  write(value, out, CanonicalStyle{}, true);
  return out;
}

void canonical_append_string(std::string_view utf8, std::string& out) {
  escape_minimal(utf8, out);
}

void canonical_append_number(double value, std::string& out) {
  CanonicalStyle::number(value, out);
}

bool canonical_key_less(std::string_view a, std::string_view b) {
  // UTF-8 byte order is code point order; UTF-16 code unit order differs only where a supplementary
  // character (lead byte >= 0xF0) meets U+E000..U+FFFF (lead bytes 0xEE, 0xEF).
  const auto high = [](std::string_view s) {
    for (const char c : s)
      if (static_cast<unsigned char>(c) >= 0xEE)
        return true;
    return false;
  };
  if (!high(a) || !high(b))
    return a < b;
  return to_utf16(a) < to_utf16(b);
}

std::string python_json_dumps(const Value& value, bool sort_keys, bool ensure_ascii) {
  std::string out;
  write(value, out, PythonStyle{ensure_ascii, sort_keys}, sort_keys);
  return out;
}

}  // namespace scad::io
