#include "scad/reactive/param_path.hpp"

#include <cctype>

#include "scad/core/error.hpp"

namespace scad::reactive {

ParamPath ParamPath::parse(std::string_view text) {
  const auto malformed = [&text](const char* why) {
    return ValueError("malformed parameter path '" + std::string(text) + "': " + why);
  };
  if (text.empty())
    throw malformed("it is empty");
  ParamPath path;
  std::size_t i = 0;
  while (i < text.size() && text[i] != '[' && text[i] != '.')
    ++i;
  path.key = std::string(text.substr(0, i));
  if (path.key.empty())
    throw malformed("it has no parameter name");
  while (i < text.size()) {
    if (text[i] == '.') {
      const std::size_t start = ++i;
      while (i < text.size() && text[i] != '[' && text[i] != '.')
        ++i;
      if (i == start)
        throw malformed("empty member name");
      path.steps.emplace_back(std::string(text.substr(start, i - start)));
    } else if (text[i] == '[') {
      const std::size_t start = ++i;
      std::size_t index = 0;
      while (i < text.size() && std::isdigit(static_cast<unsigned char>(text[i])))
        index = index * 10 + static_cast<std::size_t>(text[i++] - '0');
      if (i == start || i >= text.size() || text[i] != ']')
        throw malformed("expected [index]");
      ++i;
      path.steps.emplace_back(index);
    } else {
      throw malformed("unexpected character");
    }
  }
  return path;
}

std::string ParamPath::str() const {
  std::string out = key;
  for (const Step& step : steps) {
    if (const auto* index = std::get_if<std::size_t>(&step)) {
      out += "[" + std::to_string(*index) + "]";
    } else {
      out += "." + std::get<std::string>(step);
    }
  }
  return out;
}

namespace {

template <class V>
V* find_in(V& params, const ParamPath& path) {
  V* current = params.find(path.key);
  for (const ParamPath::Step& step : path.steps) {
    if (current == nullptr)
      return nullptr;
    if (const auto* index = std::get_if<std::size_t>(&step)) {
      if (!current->is_array() || *index >= current->size())
        return nullptr;
      current = &current->as_array()[*index];
    } else {
      current = current->find(std::get<std::string>(step));
    }
  }
  return current;
}

}  // namespace

Value* find_param(Value& params, const ParamPath& path) {
  return find_in(params, path);
}
const Value* find_param(const Value& params, const ParamPath& path) {
  return find_in(params, path);
}

void set_param(Value& params, const ParamPath& path, Value value) {
  if (!params.is_object() && !params.is_null())
    throw ValueError("parameters must be an object to set '" + path.str() + "'");
  if (params.is_null())
    params = Value::object();
  Value* current = params.find(path.key);
  if (current == nullptr) {
    params.set(path.key, Value());
    current = params.find(path.key);
  }
  for (const ParamPath::Step& step : path.steps) {
    if (const auto* index = std::get_if<std::size_t>(&step)) {
      if (current->is_null())
        *current = Value::array();
      if (!current->is_array())
        throw ValueError("cannot index '" + path.str() + "': not an array");
      Value::Array& items = current->as_array();
      if (items.size() <= *index)
        items.resize(*index + 1);
      current = &items[*index];
    } else {
      if (current->is_null())
        *current = Value::object();
      if (!current->is_object())
        throw ValueError("cannot take a member of '" + path.str() + "': not an object");
      const std::string& name = std::get<std::string>(step);
      if (current->find(name) == nullptr)
        current->set(name, Value());
      current = current->find(name);
    }
  }
  *current = std::move(value);
}

}  // namespace scad::reactive
