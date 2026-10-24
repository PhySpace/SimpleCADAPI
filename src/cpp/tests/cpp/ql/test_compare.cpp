#include <cmath>
#include <limits>

#include "doctest.h"
#include "scad/core/error.hpp"
#include "scad/ql/compare.hpp"

using namespace scad;
using namespace scad::ql;

TEST_CASE("numbers compare across bool, int and float like Python") {
  CHECK(values_equal(Value(7), Value(7.0)));
  CHECK(values_equal(Value(true), Value(1)));
  CHECK_FALSE(values_equal(Value(true), Value(2)));
  CHECK(compare_values(Value(1), Value(2.5)) == Ordering::Less);
  CHECK(compare_values(Value(3.0), Value(3)) == Ordering::Equal);
  CHECK(compare_values(Value(std::int64_t{9}), Value(false)) == Ordering::Greater);
}

TEST_CASE("NaN is unordered and unequal") {
  const Value nan(std::numeric_limits<double>::quiet_NaN());
  CHECK_FALSE(values_equal(nan, nan));
  CHECK(compare_values(nan, Value(1)) == Ordering::Unordered);
  CHECK_FALSE(compare(nan, CompareOp::Ge, ">=", Value(1)));
  CHECK_FALSE(compare(Value(1), CompareOp::Le, "<=", nan));
}

TEST_CASE("strings and lists order lexicographically") {
  CHECK(compare_values(Value("abc"), Value("abd")) == Ordering::Less);
  CHECK(compare_values(Value("b"), Value("a")) == Ordering::Greater);
  const Value one = Value(Value::Array{Value(1), Value(2)});
  const Value two = Value(Value::Array{Value(1), Value(3)});
  const Value longer = Value(Value::Array{Value(1), Value(2), Value(0)});
  CHECK(compare_values(one, two) == Ordering::Less);
  CHECK(compare_values(one, longer) == Ordering::Less);
  CHECK(values_equal(one, Value(Value::Array{Value(1), Value(2.0)})));
}

TEST_CASE("objects are equal regardless of member order and are not orderable") {
  Value a = Value::object();
  a.set("x", 1);
  a.set("y", "t");
  Value b = Value::object();
  b.set("y", "t");
  b.set("x", 1.0);
  CHECK(values_equal(a, b));
  CHECK(compare_values(a, b) == Ordering::Equal);
  b.set("x", 2);
  CHECK_FALSE(values_equal(a, b));
  CHECK(compare_values(a, b) == Ordering::Incomparable);
}

TEST_CASE("unrelated types are not orderable and never equal") {
  CHECK(compare_values(Value("a"), Value(1)) == Ordering::Incomparable);
  CHECK(compare_values(Value(), Value(1)) == Ordering::Incomparable);
  CHECK_FALSE(values_equal(Value("1"), Value(1)));
  CHECK(compare_values(Value(), Value()) == Ordering::Equal);
}

TEST_CASE("_compare: None only satisfies == and !=; ordering across types is false") {
  CHECK(compare(Value(), CompareOp::Eq, "==", Value()));
  CHECK_FALSE(compare(Value(), CompareOp::Eq, "==", Value(1)));
  CHECK(compare(Value(), CompareOp::Ne, "!=", Value(1)));
  CHECK_FALSE(compare(Value(), CompareOp::Gt, ">", Value(1)));
  CHECK_FALSE(compare(Value("a"), CompareOp::Lt, "<", Value(1)));
  CHECK(compare(Value(2), CompareOp::Ge, ">=", Value(2.0)));
  CHECK(compare(Value(2), CompareOp::Le, "<=", Value(2.0)));
}

TEST_CASE("an unsupported operator is an error only once there is a value to compare") {
  CHECK(parse_compare_op("~") == CompareOp::Unsupported);
  CHECK_FALSE(compare(Value(), CompareOp::Unsupported, "~", Value(1)));
  CHECK_THROWS_WITH_AS((void)compare(Value(1), CompareOp::Unsupported, "~", Value(1)), "unsupported op: ~", ValueError);
}

TEST_CASE("py_str renders values the way str() does") {
  CHECK(py_str(Value()) == "None");
  CHECK(py_str(Value(true)) == "True");
  CHECK(py_str(Value(3)) == "3");
  CHECK(py_str(Value(2.5)) == "2.5");
  CHECK(py_str(Value(2.0)) == "2.0");
  CHECK(py_str(Value("s")) == "s");
  CHECK(py_str(Value(Value::Array{Value(1), Value("a")})) == "[1, 'a']");
}
