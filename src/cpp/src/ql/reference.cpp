// ql::ref and the reference resolver slot (scad/ql/reference.hpp).
#include "scad/ql/reference.hpp"

#include <memory>
#include <mutex>
#include <utility>

#include "scad/core/error.hpp"

namespace scad::ql {

namespace {

struct ResolverSlot {
  std::mutex mutex;
  std::shared_ptr<const ReferenceResolver> resolver;
};

ResolverSlot& resolver_slot() {
  static ResolverSlot slot;
  return slot;
}

}  // namespace

void set_reference_resolver(ReferenceResolver resolver) {
  std::shared_ptr<const ReferenceResolver> installed;
  if (resolver)
    installed = std::make_shared<const ReferenceResolver>(std::move(resolver));
  std::shared_ptr<const ReferenceResolver> retired;  // released after the lock
  const std::lock_guard<std::mutex> lock(resolver_slot().mutex);
  retired = std::exchange(resolver_slot().resolver, std::move(installed));
}

std::vector<Shape> resolve_reference(const Shape& scope, const Value& record) {
  std::shared_ptr<const ReferenceResolver> resolver;
  {
    const std::lock_guard<std::mutex> lock(resolver_slot().mutex);
    resolver = resolver_slot().resolver;
  }
  if (!resolver)
    throw ValueError("ql.ref needs the reference resolver of simplecadapi.ref (import simplecadapi)");
  return (*resolver)(scope, record);
}

Predicate ref(Value record) {
  if (!record.is_object())
    throw ValueError("ql.ref: a reference record must be an object");
  Value data = Value::object();
  data.set("ref", std::move(record));
  return Predicate("ref", std::move(data));
}

}  // namespace scad::ql
