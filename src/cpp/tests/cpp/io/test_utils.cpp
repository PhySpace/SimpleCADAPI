// Hashes, JSON and file access.
#include "doctest.h"

#include <clocale>
#include <filesystem>
#include <locale>

#include <BRepPrimAPI_MakeBox.hxx>

#include "scad/core/error.hpp"
#include "scad/io/exchange.hpp"
#include "scad/io/files.hpp"
#include "scad/io/hash.hpp"
#include "scad/io/json.hpp"

using namespace scad;
using namespace scad::io;
namespace fs = std::filesystem;

TEST_CASE("sha256, sha1, crc32 and uuid5 match the reference values") {
  CHECK(sha256_hex("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  CHECK(sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  CHECK(sha256_tagged("abc").rfind("sha256:ba7816bf", 0) == 0);
  // 1000 bytes spans several blocks and the padding boundary.
  CHECK(sha256_hex(std::string(1000, 'a')) == "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3");
  const Sha1Digest digest = sha1("abc");
  CHECK(to_hex(digest.data(), digest.size()) == "a9993e364706816aba3e25717850c26c9cd0d89d");
  CHECK(crc32("123456789") == 0xCBF43926U);
  CHECK(uuid5_url_hex("simplecad.brep_region.root|sha256:abc|solid") == "94c1475a560f52eabe4a981c2b65f9b5");
}

TEST_CASE("canonical JSON is RFC 8785 byte for byte (output of the Python rfc8785 package)") {
  Value v = Value::object();
  v.set("b", 1);
  Value a = Value::array();
  for (const double d : {1.5, 1e21, 1e-7}) a.push_back(d);
  a.push_back(std::string("\xC3\xA9\n\x01\""));
  for (const double d : {0.1, 100.0, 1e16, 123456789012345678.0, -0.0, 5e-324, 1.7976931348623157e308, 0.000001, 1e22,
                         12345.6789})
    a.push_back(d);
  v.set("a", a);
  Value c = Value::object();
  c.set("z", Value());
  c.set("a", true);
  v.set("c", c);
  v.set("\xF0\x9F\x98\x80", 1);  // U+1F600: sorts before U+FFFF in UTF-16 order
  v.set("\xEF\xBF\xBF", 2);
  CHECK(canonical_json(v) ==
        "{\"a\":[1.5,1e+21,1e-7,\"\xC3\xA9\\n\\u0001\\\"\",0.1,100,10000000000000000,123456789012345680,0,5e-324,"
        "1.7976931348623157e+308,0.000001,1e+22,12345.6789],\"b\":1,\"c\":{\"a\":true,\"z\":null},"
        "\"\xF0\x9F\x98\x80\":1,\"\xEF\xBF\xBF\":2}");
}

TEST_CASE("python_json_dumps matches json.dumps") {
  Value v = Value::object();
  Value a = Value::array();
  for (const double d : {1.0, 1e16, 1e-5, 0.1, -0.0, 1e15, 123456789.123456789, 2.5e-7, 1e100}) a.push_back(d);
  v.set("a", a);
  v.set("\xC3\xA9", std::string("\xC3\xBC\x7f"));
  CHECK(python_json_dumps(v, /*sort_keys=*/true, /*ensure_ascii=*/true) ==
        "{\"a\": [1.0, 1e+16, 1e-05, 0.1, -0.0, 1000000000000000.0, 123456789.12345679, 2.5e-07, 1e+100], "
        "\"\\u00e9\": \"\\u00fc\\u007f\"}");
  Value emoji = Value::object();
  emoji.set("\xEF\xBF\xBF", 2);
  emoji.set("\xF0\x9F\x98\x80", 1);
  CHECK(python_json_dumps(emoji, true, true) == "{\"\\uffff\": 2, \"\\ud83d\\ude00\": 1}");
}

TEST_CASE("parse_json is strict and round-trips canonical text") {
  const std::string text = "{\"a\":[1,2.5,true,null,\"x\\u00e9\\ud83d\\ude00\"],\"b\":{\"c\":-12}}";
  const Value v = parse_json(text);
  CHECK(v.find("a")->as_array()[0].is_int());
  CHECK(v.find("a")->as_array()[1].is_double());
  CHECK(canonical_json(v) == "{\"a\":[1,2.5,true,null,\"x\xC3\xA9\xF0\x9F\x98\x80\"],\"b\":{\"c\":-12}}");
  CHECK_THROWS_AS((void)parse_json("{\"a\":1,\"a\":2}"), ValueError);
  CHECK_THROWS_AS((void)parse_json("{\"a\":NaN}"), ValueError);
  CHECK_THROWS_AS((void)parse_json("[1,]"), ValueError);
  CHECK_THROWS_AS((void)parse_json("[1] x"), ValueError);
  CHECK_THROWS_AS((void)parse_json("\"\\ud800\""), ValueError);
  CHECK_THROWS_AS((void)parse_json("\"\xC0\xAF\""), ValueError);
  CHECK_THROWS_AS((void)parse_json("01"), ValueError);
  CHECK_THROWS_AS((void)parse_json("1e999"), ValueError);
  CHECK_THROWS_AS((void)parse_json(std::string(500, '[')), ValueError);
  CHECK(parse_json("9223372036854775808").is_double());  // beyond int64
  CHECK(parse_json("{\"a\":1,\"a\":2}", JsonParseOptions{false, 128}).find("a")->as_int() == 2);
}

TEST_CASE("files: UTF-8 paths, atomic writes, binary fidelity") {
  namespace fs = std::filesystem;
  const fs::path dir = fs::temp_directory_path() / path_from_utf8("scad_io_t\xC3\xA9st_\xE4\xB8\xAD\xE6\x96\x87");
  fs::remove_all(dir);
  fs::create_directories(dir);
  const fs::path file = dir / path_from_utf8("d\xC3\xA1ta.bin");
  const std::string payload("a\r\nb\0c\n\x1a\xff", 9);  // CR LF, NUL, ^Z: untouched by a text-mode stream
  write_file(file, payload);
  CHECK(read_file(file) == payload);
  CHECK(path_to_utf8(file.filename()) == "d\xC3\xA1ta.bin");
  CHECK(extension_of(path_from_utf8("x/Model.STEP")) == "step");
  CHECK(extension_of(path_from_utf8("x/noext")).empty());

  // Overwrite is atomic: no temporary file is left behind and the content is replaced.
  write_file(file, "second");
  CHECK(read_file(file) == "second");
  std::size_t entries = 0;
  for (const auto& e : fs::directory_iterator(dir)) { (void)e; ++entries; }
  CHECK(entries == 1);

  {
    AtomicWriter writer(dir / "abandoned.txt");
    writer.stream() << "never committed";
  }
  CHECK_FALSE(fs::exists(dir / "abandoned.txt"));

  CHECK_THROWS_AS((void)read_file(dir / "missing"), RuntimeError);
  CHECK_THROWS_AS((void)read_file(dir), RuntimeError);
  CHECK_THROWS_AS(write_file(dir / "no_such_dir" / "f", "x"), RuntimeError);
  CHECK_THROWS_AS((void)read_file(file, 3), RuntimeError);
  fs::remove_all(dir);
}

TEST_CASE("number formatting and parsing ignore the C and C++ locales") {
  // A comma-decimal locale, when the machine has one; otherwise this only checks the C locale.
  const std::string previous_c = std::setlocale(LC_NUMERIC, nullptr);
  const std::locale previous_cpp = std::locale::global(std::locale::classic());
  bool switched = false;
  for (const char* name : {"de_DE.UTF-8", "de_DE", "fr_FR.UTF-8", "ru_RU.UTF-8"}) {
    if (std::setlocale(LC_NUMERIC, name) != nullptr) {
      switched = true;
      break;
    }
  }
  try {
    std::locale::global(std::locale(switched ? "de_DE.UTF-8" : "C"));
  } catch (const std::runtime_error&) {
    // no such C++ locale: the C locale switch alone is still a valid check
  }
  Value v = Value::array();
  v.push_back(1.5);
  v.push_back(1234567.25);
  CHECK(canonical_json(v) == "[1.5,1234567.25]");
  CHECK(python_json_dumps(v) == "[1.5, 1234567.25]");
  CHECK(parse_json("[1.5,2.25e2]").as_array()[1].as_double() == 225.0);
  CHECK(parse_json("1234567.25").as_double() == 1234567.25);

  // The writers format every number themselves, so a grouping or comma-decimal locale cannot reach a file.
  const TopoDS_Shape box = BRepPrimAPI_MakeBox(1.5, 2.0, 3.25).Solid();
  const Bytes obj = obj_bytes(tessellate_solid(box));
  CHECK(obj.find(',') == std::string::npos);
  CHECK(obj.find("v 1.5 2 3.25\n") != std::string::npos);
  const fs::path stl = fs::temp_directory_path() / "scad_io_locale_probe.stl";
  export_stl_shape(box, stl);
  const Bytes ascii = read_file(stl);
  fs::remove(stl);
  CHECK(ascii.find(',') == std::string::npos);
  CHECK(ascii.find("1.50000000e+00") != std::string::npos);

  std::locale::global(previous_cpp);
  std::setlocale(LC_NUMERIC, previous_c.c_str());
}
