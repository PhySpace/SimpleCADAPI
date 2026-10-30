// Python bindings for the semantic area: the tag data model (simplecadapi.tagging), the public
// tag operators (operators/selection.py) and the private TaggedMixin surface of shapes.
//
// The ten tag enums are real `(str, Enum)` classes, as in Python: a function that takes one accepts
// the member or its string value ("local"), and returns members.  The casters below are the only
// ones for these types in the module.
#include "bindings.hpp"

#include <algorithm>
#include <type_traits>

#include "scad/core/error.hpp"
#include "scad/ql/selector.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/semantic/selection.hpp"
#include "scad/topo/tag_factories.hpp"

namespace scad::pybind {

// The Python class standing for each enum, and the facts needed to parse one.
template <class E>
struct EnumInfo;
template <>
struct EnumInfo<TagScope> {
  static constexpr const char* name = "TagScope";
  static constexpr const char* field = "tag scope";
  static constexpr int count = 4;
};
template <>
struct EnumInfo<TopologyPropagation> {
  static constexpr const char* name = "TopologyPropagation";
  static constexpr const char* field = "topology propagation";
  static constexpr int count = 2;
};
template <>
struct EnumInfo<LineagePolicy> {
  static constexpr const char* name = "LineagePolicy";
  static constexpr const char* field = "lineage policy";
  static constexpr int count = 4;
};
template <>
struct EnumInfo<LineageDerivation> {
  static constexpr const char* name = "LineageDerivation";
  static constexpr const char* field = "lineage derivation";
  static constexpr int count = 6;
};
template <>
struct EnumInfo<TagAttachment> {
  static constexpr const char* name = "TagAttachment";
  static constexpr const char* field = "attachment";
  static constexpr int count = 3;
};
template <>
struct EnumInfo<TagProducerKind> {
  static constexpr const char* name = "TagProducerKind";
  static constexpr const char* field = "producer kind";
  static constexpr int count = 4;
};
template <>
struct EnumInfo<TagTargetKind> {
  static constexpr const char* name = "TagTargetKind";
  static constexpr const char* field = "target kind";
  static constexpr int count = 4;
};
template <>
struct EnumInfo<TagEvidenceKind> {
  static constexpr const char* name = "TagEvidenceKind";
  static constexpr const char* field = "evidence kind";
  static constexpr int count = 6;
};
template <>
struct EnumInfo<TagCertainty> {
  static constexpr const char* name = "TagCertainty";
  static constexpr const char* field = "certainty";
  static constexpr int count = 2;
};
template <>
struct EnumInfo<TagLifecycle> {
  static constexpr const char* name = "TagLifecycle";
  static constexpr const char* field = "lifecycle";
  static constexpr int count = 3;
};

template <class E>
py::object& enum_class() {
  static py::object* cls = new py::object;  // never destroyed: static destructors run after Py_Finalize
  return *cls;
}

template <class E>
E parse_enum_text(const std::string& text) {
  if constexpr (std::is_same_v<E, TagScope>) {
    return normalize_tag_scope(text);
  } else {
    std::vector<std::string> allowed;
    for (int i = 0; i < EnumInfo<E>::count; ++i) {
      const E candidate = static_cast<E>(i);
      if (to_string(candidate) == text)
        return candidate;
      allowed.emplace_back(to_string(candidate));
    }
    std::sort(allowed.begin(), allowed.end());
    std::string joined;
    for (const auto& item : allowed)
      joined += (joined.empty() ? "" : ", ") + item;
    throw TagValidationError(std::string("unsupported ") + EnumInfo<E>::field + " '" + text +
                             "'; expected one of: " + joined);
  }
}

}  // namespace scad::pybind

namespace scad::pybind {

// One caster for all of them.  pybind11 3 has a generic caster for enums, so each type below gets
// an explicit specialization (which outranks it) that derives from this.
template <class E>
struct TagEnumCaster {
  PYBIND11_TYPE_CASTER(E, ::pybind11::detail::const_name("str"));

  bool load(py::handle src, bool) {
    if (!src)
      return false;
    if (py::isinstance<py::str>(src)) {
      value = parse_enum_text<E>(src.cast<std::string>());
      return true;
    }
    if (py::hasattr(src, "value") && py::isinstance<py::str>(src.attr("value"))) {
      value = parse_enum_text<E>(src.attr("value").template cast<std::string>());
      return true;
    }
    return false;
  }

  static py::handle cast(E v, py::return_value_policy, py::handle) {
    return enum_class<E>()(std::string(to_string(v))).release();
  }
};

}  // namespace scad::pybind

namespace pybind11::detail {

template <>
struct type_caster<scad::TagScope> : scad::pybind::TagEnumCaster<scad::TagScope> {};
template <>
struct type_caster<scad::TopologyPropagation> : scad::pybind::TagEnumCaster<scad::TopologyPropagation> {};
template <>
struct type_caster<scad::LineagePolicy> : scad::pybind::TagEnumCaster<scad::LineagePolicy> {};
template <>
struct type_caster<scad::LineageDerivation> : scad::pybind::TagEnumCaster<scad::LineageDerivation> {};
template <>
struct type_caster<scad::TagAttachment> : scad::pybind::TagEnumCaster<scad::TagAttachment> {};
template <>
struct type_caster<scad::TagProducerKind> : scad::pybind::TagEnumCaster<scad::TagProducerKind> {};
template <>
struct type_caster<scad::TagTargetKind> : scad::pybind::TagEnumCaster<scad::TagTargetKind> {};
template <>
struct type_caster<scad::TagEvidenceKind> : scad::pybind::TagEnumCaster<scad::TagEvidenceKind> {};
template <>
struct type_caster<scad::TagCertainty> : scad::pybind::TagEnumCaster<scad::TagCertainty> {};
template <>
struct type_caster<scad::TagLifecycle> : scad::pybind::TagEnumCaster<scad::TagLifecycle> {};

}  // namespace pybind11::detail

namespace {

using namespace scad;
using scad::pybind::value_from_python;
using scad::pybind::value_to_python;

py::object shape_to_py(const Shape& s) {
  switch (s.kind()) {
    case Kind::Vertex:
      return py::cast(Vertex(s));
    case Kind::Edge:
      return py::cast(Edge(s));
    case Kind::Wire:
      return py::cast(Wire(s));
    case Kind::Face:
      return py::cast(Face(s));
    case Kind::Shell:
      return py::cast(Shell(s));
    case Kind::Solid:
      return py::cast(Solid(s));
    case Kind::Compound:
      return py::cast(Compound(s));
  }
  return py::none();
}

template <class E>
void make_enum(py::module_& m, std::initializer_list<const char*> values) {
  py::list members;
  for (const char* value : values) {
    std::string name = value;
    for (char& c : name)
      c = static_cast<char>(c >= 'a' && c <= 'z' ? c - 'a' + 'A' : c);
    members.append(py::make_tuple(name, value));
  }
  py::dict kwargs;
  kwargs["type"] = py::module_::import("builtins").attr("str");
  kwargs["module"] = "simplecadapi._cpp";
  py::object cls = py::module_::import("enum").attr("Enum")(scad::pybind::EnumInfo<E>::name, members, **kwargs);
  scad::pybind::enum_class<E>() = cls;
  m.attr(scad::pybind::EnumInfo<E>::name) = cls;
}

void bind_enums(py::module_& m) {
  make_enum<TagScope>(m, {"local", "inherited", "effective", "lineage"});
  make_enum<TopologyPropagation>(m, {"local", "downward"});
  make_enum<LineagePolicy>(m, {"none", "continuation", "continuation_fragment", "explicit"});
  make_enum<LineageDerivation>(m, {"continuation", "fragment", "merge", "intersection", "boundary", "replacement"});
  make_enum<TagAttachment>(m, {"local", "inherited", "effective_legacy"});
  make_enum<TagProducerKind>(m, {"user_operation", "auto_rule", "imported_sidecar", "legacy_import"});
  make_enum<TagTargetKind>(m, {"selection_query", "scope_root", "explicit_refs", "legacy_effective"});
  make_enum<TagEvidenceKind>(m, {"user_assertion", "query_execution", "topology_change", "geometry_classification",
                                 "imported_sidecar", "legacy_snapshot"});
  make_enum<TagCertainty>(m, {"asserted", "proven"});
  make_enum<TagLifecycle>(m, {"assertion", "recompute", "snapshot"});
}

// ---- the data classes ------------------------------------------------------------------------------------

// The data classes validate when they are built, like the Python dataclasses; the wire parsers hold the rules.
TagTarget checked(const TagTarget& target) {
  return tag_target_from_value(target.to_value());
}
TagPropagation checked(const TagPropagation& p) {
  return tag_propagation_from_value(p.to_value());
}
TagProducer checked(const TagProducer& p) {
  return tag_producer_from_value(p.to_value());
}

void bind_records(py::module_& m) {
  py::class_<TagBindingScope>(m, "TagBindingScope", "Snapshot boundary in which an assignment target is evaluated.")
      .def(py::init([](std::optional<std::string> node_id, int output_slot) {
             if (node_id && node_id->empty())
               throw TagValidationError("scope.node_id must be null or a non-empty string");
             if (output_slot < 0)
               throw TagValidationError("scope.output_slot must be >= 0");
             return TagBindingScope{std::move(node_id), output_slot};
           }),
           py::arg("node_id") = py::none(), py::arg("output_slot") = 0)
      .def_property_readonly("node_id", [](const TagBindingScope& s) { return s.node_id; })
      .def_property_readonly("output_slot", [](const TagBindingScope& s) { return s.output_slot; })
      .def("to_dict", [](const TagBindingScope& s) { return value_to_python(s.to_value()); })
      .def_static("from_dict",
                  [](const py::object& data) { return tag_binding_scope_from_value(value_from_python(data)); })
      .def("__eq__", [](const TagBindingScope& a, const TagBindingScope& b) { return a.to_value() == b.to_value(); })
      .def("__hash__", [](const TagBindingScope& s) { return py::hash(py::make_tuple(s.node_id, s.output_slot)); })
      .def("__repr__", [](const TagBindingScope& s) {
        return "TagBindingScope(node_id=" + (s.node_id ? "'" + *s.node_id + "'" : std::string("None")) +
               ", output_slot=" + std::to_string(s.output_slot) + ")";
      });

  py::class_<TagProducer>(m, "TagProducer", "Identity of the operation, rule, or import that made an assertion.")
      .def(py::init([](TagProducerKind kind, std::optional<std::string> node_id, std::optional<std::string> rule_id,
                       std::optional<std::string> rule_version) {
             TagProducer p;
             p.kind = kind;
             p.node_id = std::move(node_id);
             p.rule_id = std::move(rule_id);
             p.rule_version = std::move(rule_version);
             return checked(p);
           }),
           py::arg("kind"), py::arg("node_id") = py::none(), py::arg("rule_id") = py::none(),
           py::arg("rule_version") = py::none())
      .def_property_readonly("kind", [](const TagProducer& p) { return p.kind; })
      .def_property_readonly("node_id", [](const TagProducer& p) { return p.node_id; })
      .def_property_readonly("rule_id", [](const TagProducer& p) { return p.rule_id; })
      .def_property_readonly("rule_version", [](const TagProducer& p) { return p.rule_version; })
      .def("to_dict", [](const TagProducer& p) { return value_to_python(p.to_value()); })
      .def_static("from_dict", [](const py::object& data) { return tag_producer_from_value(value_from_python(data)); })
      .def("__eq__", [](const TagProducer& a, const TagProducer& b) { return a == b; })
      .def("__repr__", [](const TagProducer& p) { return "TagProducer(" + p.to_value().dump() + ")"; });

  py::class_<TagTarget>(m, "TagTarget", "Serializable assignment intent, separate from execution evidence.")
      .def(
          py::init([](TagTargetKind kind, std::optional<std::string> query_hash,
                      std::optional<std::string> binding_hash, std::optional<Value> selector, std::vector<Value> refs) {
            TagTarget t;
            t.kind = kind;
            t.query_hash = std::move(query_hash);
            t.binding_hash = std::move(binding_hash);
            if (selector && !selector->is_null()) {
              if (!selector->is_object())
                throw TagValidationError("target.selector must be an object");
              t.selector = std::move(selector);
            }
            for (const Value& ref : refs)
              if (!ref.is_object())
                throw TagValidationError("target.refs must be a tuple of objects");
            t.refs = std::move(refs);
            return checked(t);
          }),
          py::arg("kind") = TagTargetKind::ScopeRoot, py::arg("query_hash") = py::none(),
          py::arg("binding_hash") = py::none(), py::arg("selector") = py::none(), py::arg("refs") = py::tuple())
      .def_property_readonly("kind", [](const TagTarget& t) { return t.kind; })
      .def_property_readonly("query_hash", [](const TagTarget& t) { return t.query_hash; })
      .def_property_readonly("binding_hash", [](const TagTarget& t) { return t.binding_hash; })
      .def_property_readonly(
          "selector",
          [](const TagTarget& t) { return t.selector ? value_to_python(*t.selector) : py::object(py::none()); })
      .def_property_readonly("refs",
                             [](const TagTarget& t) {
                               py::list refs;
                               for (const Value& r : t.refs)
                                 refs.append(value_to_python(r));
                               return py::tuple(refs);
                             })
      .def("to_dict", [](const TagTarget& t) { return value_to_python(t.to_value()); })
      .def_static("from_dict", [](const py::object& data) { return tag_target_from_value(value_from_python(data)); })
      .def("__eq__", [](const TagTarget& a, const TagTarget& b) { return a.to_value() == b.to_value(); })
      .def("__repr__", [](const TagTarget& t) { return "TagTarget(" + t.to_value().dump() + ")"; });

  py::class_<TagPropagation>(m, "TagPropagation", "How a tag travels through topology and history.")
      .def(
          py::init([](TopologyPropagation topology, LineagePolicy lineage, std::vector<LineageDerivation> derivations) {
            TagPropagation p;
            p.topology = topology;
            p.lineage = lineage;
            p.explicit_derivations = std::move(derivations);
            return checked(p);
          }),
          py::arg("topology") = TopologyPropagation::Local, py::arg("lineage") = LineagePolicy::ContinuationFragment,
          py::arg("explicit_derivations") = py::tuple())
      .def_property_readonly("topology", [](const TagPropagation& p) { return p.topology; })
      .def_property_readonly("lineage", [](const TagPropagation& p) { return p.lineage; })
      .def_property_readonly("explicit_derivations",
                             [](const TagPropagation& p) {
                               py::list items;
                               for (const auto d : p.explicit_derivations)
                                 items.append(py::cast(d));
                               return py::tuple(items);
                             })
      .def("to_dict", [](const TagPropagation& p) { return value_to_python(p.to_value()); })
      .def_static("from_dict",
                  [](const py::object& data) { return tag_propagation_from_value(value_from_python(data)); })
      .def("__eq__", [](const TagPropagation& a, const TagPropagation& b) { return a.to_value() == b.to_value(); })
      .def("__repr__", [](const TagPropagation& p) { return "TagPropagation(" + p.to_value().dump() + ")"; });

  py::class_<TagEvidence>(m, "TagEvidence", "Typed evidence payload for a binding or a lineage witness.")
      .def(py::init([](TagEvidenceKind kind, std::optional<Value> data) {
             TagEvidence e;
             e.kind = kind;
             if (data && !data->is_null()) {
               if (!data->is_object())
                 throw TagValidationError("evidence data must be an object");
               if (data->find("kind") != nullptr)
                 throw TagValidationError("evidence data cannot redefine kind");
               e.data = std::move(*data);
             }
             return e;
           }),
           py::arg("kind"), py::arg("data") = py::none())
      .def_property_readonly("kind", [](const TagEvidence& e) { return e.kind; })
      .def_property_readonly("data", [](const TagEvidence& e) { return value_to_python(e.data); })
      .def("to_dict", [](const TagEvidence& e) { return value_to_python(e.to_value()); })
      .def_static("from_dict", [](const py::object& data) { return tag_evidence_from_value(value_from_python(data)); })
      .def("__eq__", [](const TagEvidence& a, const TagEvidence& b) { return a.to_value() == b.to_value(); })
      .def("__repr__", [](const TagEvidence& e) { return "TagEvidence(" + e.to_value().dump() + ")"; });

  py::class_<TagBinding>(m, "TagBinding", "Canonical, source-preserving Semantic Binding Schema 1.0 assignment.")
      .def(py::init([](const std::string& tag, TagProducer producer, std::optional<TagBindingScope> scope,
                       std::optional<TagTarget> target, std::optional<TagPropagation> propagation,
                       std::optional<TagEvidence> evidence, TagAttachment attachment, TagCertainty certainty,
                       TagLifecycle lifecycle, std::optional<std::string> binding_id,
                       const std::string& schema_version) {
             TagBinding b;
             try {
               b.tag = normalize_tag(tag, true);
             } catch (const ValueError& e) {
               throw TagValidationError(e.what());
             }
             b.policy.mut().producer = std::move(producer);
             if (scope)
               b.policy.mut().scope = std::move(*scope);
             if (target)
               b.policy.mut().target = std::move(*target);
             if (propagation)
               b.policy.mut().propagation = std::move(*propagation);
             b.evidence = evidence ? std::move(*evidence) : TagEvidence{};
             b.attachment = attachment;
             b.certainty = certainty;
             b.lifecycle = lifecycle;
             b.binding_id = binding_id ? BindingId(*binding_id) : new_binding_id();
             b.policy.mut().schema_version = schema_version;
             b.validate();
             return b;
           }),
           py::arg("tag"), py::arg("producer"), py::arg("scope") = py::none(), py::arg("target") = py::none(),
           py::arg("propagation") = py::none(), py::arg("evidence") = py::none(),
           py::arg("attachment") = TagAttachment::Local, py::arg("certainty") = TagCertainty::Asserted,
           py::arg("lifecycle") = TagLifecycle::Assertion, py::arg("binding_id") = py::none(),
           py::arg("schema_version") = std::string(kTagBindingSchemaVersion))
      .def_property_readonly("tag", [](const TagBinding& b) { return b.tag.str(); })
      .def_property_readonly("producer", [](const TagBinding& b) { return b.producer(); })
      .def_property_readonly("scope", [](const TagBinding& b) { return b.scope(); })
      .def_property_readonly("target", [](const TagBinding& b) { return b.target(); })
      .def_property_readonly("propagation", [](const TagBinding& b) { return b.propagation(); })
      .def_property_readonly("evidence", [](const TagBinding& b) { return *b.evidence; })
      .def_property_readonly("attachment", [](const TagBinding& b) { return b.attachment; })
      .def_property_readonly("certainty", [](const TagBinding& b) { return b.certainty; })
      .def_property_readonly("lifecycle", [](const TagBinding& b) { return b.lifecycle; })
      .def_property_readonly("binding_id", [](const TagBinding& b) { return b.binding_id.str(); })
      .def_property_readonly("schema_version", [](const TagBinding& b) { return b.schema_version().str(); })
      .def("to_dict", [](const TagBinding& b) { return value_to_python(b.to_value()); })
      .def_static("from_dict", [](const py::object& data) { return tag_binding_from_value(value_from_python(data)); })
      .def("__eq__", [](const TagBinding& a, const TagBinding& b) { return a == b; })
      .def("__hash__", [](const TagBinding& b) { return py::hash(py::str(b.binding_id.str())); })
      .def("__repr__", [](const TagBinding& b) {
        return "TagBinding(tag='" + b.tag.str() + "', binding_id='" + b.binding_id.str() + "')";
      });

  py::class_<TagLineageWitness>(m, "TagLineageWitness",
                                "Evidence that makes a source binding visible in lineage scope.")
      .def(py::init([](TagBinding binding, LineageDerivation derivation, std::string source_topo_id,
                       std::string target_topo_id, TagEvidence evidence, std::string coverage) {
             TagLineageWitness w;
             w.binding = std::move(binding);
             w.derivation = derivation;
             w.source_topo_id = std::move(source_topo_id);
             w.target_topo_id = std::move(target_topo_id);
             w.evidence = std::move(evidence);
             w.coverage = std::move(coverage);
             w.validate();
             return w;
           }),
           py::arg("binding"), py::arg("derivation"), py::arg("source_topo_id"), py::arg("target_topo_id"),
           py::arg("evidence"), py::arg("coverage") = "complete")
      .def_property_readonly("binding", [](const TagLineageWitness& w) { return w.binding; })
      .def_property_readonly("derivation", [](const TagLineageWitness& w) { return w.derivation; })
      .def_property_readonly("source_topo_id", [](const TagLineageWitness& w) { return w.source_topo_id; })
      .def_property_readonly("target_topo_id", [](const TagLineageWitness& w) { return w.target_topo_id; })
      .def_property_readonly("evidence", [](const TagLineageWitness& w) { return *w.evidence; })
      .def_property_readonly("coverage", [](const TagLineageWitness& w) { return w.coverage; })
      .def("to_dict", [](const TagLineageWitness& w) { return value_to_python(w.to_value()); })
      .def_static("from_dict",
                  [](const py::object& data) { return tag_lineage_witness_from_value(value_from_python(data)); })
      .def("__eq__", [](const TagLineageWitness& a, const TagLineageWitness& b) { return a == b; })
      .def("__repr__", [](const TagLineageWitness& w) { return "TagLineageWitness(" + w.to_value().dump() + ")"; });

  py::class_<TagPolicy>(m, "TagPolicy", "Legacy token registry hints; canonical assignments do not consult this.")
      .def(py::init<>())
      .def_readonly("propagate_prefixes", &TagPolicy::propagate_prefixes)
      .def_readonly("propagate_exact", &TagPolicy::propagate_exact)
      .def_readonly("block_prefixes", &TagPolicy::block_prefixes)
      .def_readonly("block_exact", &TagPolicy::block_exact)
      .def("should_propagate", &TagPolicy::should_propagate, py::arg("tag"));

  py::class_<SemanticRef>(m, "SemanticRef")
      .def(py::init([](std::string graph_id, std::string node_id, std::string entity_type, std::string entity_id) {
             return SemanticRef{std::move(graph_id), std::move(node_id), std::move(entity_type), std::move(entity_id)};
           }),
           py::arg("graph_id"), py::arg("node_id"), py::arg("entity_type"), py::arg("entity_id"))
      .def_readonly("graph_id", &SemanticRef::graph_id)
      .def_readonly("node_id", &SemanticRef::node_id)
      .def_readonly("entity_type", &SemanticRef::entity_type)
      .def_readonly("entity_id", &SemanticRef::entity_id)
      .def("__eq__", [](const SemanticRef& a, const SemanticRef& b) { return a == b; })
      .def("__repr__", [](const SemanticRef& r) {
        return "SemanticRef(graph_id='" + r.graph_id + "', node_id='" + r.node_id + "', entity_type='" + r.entity_type +
               "', entity_id='" + r.entity_id + "')";
      });

  py::class_<SemanticDelta>(m, "SemanticDelta")
      .def(py::init([](std::vector<SemanticRef> created, std::vector<SemanticRef> modified,
                       std::vector<SemanticRef> deleted, std::optional<Value> metadata) {
             SemanticDelta d;
             d.created = std::move(created);
             d.modified = std::move(modified);
             d.deleted = std::move(deleted);
             if (metadata)
               d.metadata = std::move(*metadata);
             return d;
           }),
           py::arg("created") = py::tuple(), py::arg("modified") = py::tuple(), py::arg("deleted") = py::tuple(),
           py::arg("metadata") = py::none())
      .def_readonly("created", &SemanticDelta::created)
      .def_readonly("modified", &SemanticDelta::modified)
      .def_readonly("deleted", &SemanticDelta::deleted)
      .def_property_readonly("metadata", [](const SemanticDelta& d) { return value_to_python(d.metadata); });
}

// ---- the tagging namespace: factories and rules ----------------------------------------------------------------

void bind_tagging_functions(py::module_& m, py::module_& tagging) {
  tagging.def(
      "user_tag_binding",
      [](const std::string& tag, std::optional<std::string> node_id, std::optional<std::string> scope_node_id,
         int output_slot, std::optional<TagTarget> target, TopologyPropagation topology, LineagePolicy lineage,
         std::vector<LineageDerivation> explicit_derivations, std::optional<TagEvidence> evidence) {
        UserTagOptions o;
        o.node_id = std::move(node_id);
        o.scope_node_id = std::move(scope_node_id);
        o.output_slot = output_slot;
        o.target = std::move(target);
        o.topology = topology;
        o.lineage = lineage;
        o.explicit_derivations = std::move(explicit_derivations);
        o.evidence = std::move(evidence);
        return user_tag_binding(tag, o);
      },
      py::arg("tag"), py::kw_only(), py::arg("node_id") = py::none(), py::arg("scope_node_id") = py::none(),
      py::arg("output_slot") = 0, py::arg("target") = py::none(), py::arg("topology") = TopologyPropagation::Local,
      py::arg("lineage") = LineagePolicy::ContinuationFragment, py::arg("explicit_derivations") = py::tuple(),
      py::arg("evidence") = py::none());
  tagging.def(
      "internal_tag_binding",
      [](const std::string& tag, TopologyPropagation topology, const std::string& rule_id,
         const std::string& rule_version, std::optional<Value> evidence) {
        InternalTagOptions o;
        o.topology = topology;
        o.rule_id = rule_id;
        o.rule_version = rule_version;
        if (evidence)
          o.evidence = std::move(*evidence);
        return internal_tag_binding(tag, o);
      },
      py::arg("tag"), py::kw_only(), py::arg("topology") = TopologyPropagation::Local,
      py::arg("rule_id") = "simplecad.compat.internal_annotation", py::arg("rule_version") = "1.0",
      py::arg("evidence") = py::none());
  tagging.def("operation_role_tag_binding", &operation_role_tag_binding, py::arg("tag"), py::kw_only(),
              py::arg("operation"), py::arg("role"), py::arg("target_topo_id"), py::arg("evidence_method"));
  tagging.def("projected_tag_binding", &projected_tag_binding, py::arg("source"), py::kw_only(), py::arg("operation"),
              py::arg("role"), py::arg("source_topo_id"), py::arg("target_topo_id"), py::arg("evidence_method"),
              py::arg("topology") = TopologyPropagation::Local);
  tagging.def(
      "legacy_tag_binding",
      [](const std::string& tag, std::optional<std::string> diagnostic) {
        return legacy_tag_binding(tag, diagnostic ? std::optional<std::string_view>(*diagnostic) : std::nullopt);
      },
      py::arg("tag"), py::kw_only(), py::arg("diagnostic") = py::none());
  tagging.def(
      "lineage_policy_allows",
      [](const py::object& policy, LineageDerivation derivation) {
        if (py::isinstance<TagPropagation>(policy))
          return lineage_policy_allows(policy.cast<const TagPropagation&>(), derivation);
        return lineage_policy_allows(policy.cast<LineagePolicy>(), derivation);
      },
      py::arg("policy"), py::arg("derivation"));
  tagging.def(
      "is_normalized_tag",
      [](const py::object& tag) { return py::isinstance<py::str>(tag) && is_normalized_tag(tag.cast<std::string>()); },
      py::arg("tag"));
  tagging.def(
      "normalize_tag",
      [](const py::object& tag, bool strict) {
        if (!py::isinstance<py::str>(tag))
          throw TypeError("tag must be a string");
        return normalize_tag(tag.cast<std::string>(), strict);
      },
      py::arg("tag"), py::kw_only(), py::arg("strict") = true);
  tagging.def(
      "normalize_tag_scope",
      [](const py::object& scope) {
        if (py::isinstance<py::str>(scope))
          return normalize_tag_scope(scope.cast<std::string>());
        throw TypeError("tag scope must be a string or TagScope");
      },
      py::arg("scope"));
  tagging.def("resolve_anchor_tag_candidates", &resolve_anchor_tag_candidates, py::arg("tag"));
  tagging.attr("DEFAULT_TAG_POLICY") = py::cast(default_tag_policy());
  tagging.attr("TAG_BINDING_SCHEMA_VERSION") = std::string(kTagBindingSchemaVersion);
  py::set scopes;
  for (const char* scope : {"local", "inherited", "effective", "lineage"})
    scopes.add(scope);
  tagging.attr("VALID_TAG_SCOPES") = py::frozenset(scopes);

  // The error families are one Python class in this module: every scad::Error arrives as SimpleCADError.
  py::object error = py::module_::import("simplecadapi._cpp.errors").attr("SimpleCADError");
  tagging.attr("TagValidationError") = error;
  tagging.attr("SemanticCapabilityError") = error;
  tagging.attr("UnsupportedQueryCapabilityError") = error;

  for (const char* name :
       {"TagScope", "TopologyPropagation", "LineagePolicy", "LineageDerivation", "TagAttachment", "TagProducerKind",
        "TagTargetKind", "TagEvidenceKind", "TagCertainty", "TagLifecycle", "TagBinding", "TagBindingScope",
        "TagProducer", "TagTarget", "TagPropagation", "TagEvidence", "TagLineageWitness", "TagPolicy"})
    tagging.attr(name) = m.attr(name);
  // The short aliases tagging.py keeps for the model names.
  for (const auto& [alias, target] :
       std::initializer_list<std::pair<const char*, const char*>>{{"BindingScope", "TagBindingScope"},
                                                                  {"Propagation", "TagPropagation"},
                                                                  {"Lineage", "LineagePolicy"},
                                                                  {"Attachment", "TagAttachment"},
                                                                  {"Producer", "TagProducer"},
                                                                  {"ProducerKind", "TagProducerKind"},
                                                                  {"Target", "TagTarget"},
                                                                  {"TargetKind", "TagTargetKind"},
                                                                  {"Evidence", "TagEvidence"},
                                                                  {"EvidenceKind", "TagEvidenceKind"},
                                                                  {"Certainty", "TagCertainty"},
                                                                  {"Lifecycle", "TagLifecycle"}})
    tagging.attr(alias) = m.attr(target);
}

// ---- the public operators ---------------------------------------------------------------------------------------

TagTargets targets_from_py(const py::object& targets) {
  if (py::isinstance<ql::ShapeSelector>(targets))
    return TagTargets(targets.cast<const ql::ShapeSelector&>().shared());
  if (py::isinstance<py::str>(targets) || py::isinstance<py::bytes>(targets) || !py::hasattr(targets, "__iter__"))
    throw TypeError("targets must be a ShapeSelector or shape sequence");
  std::vector<Shape> shapes;
  for (const py::handle item : targets) {
    if (!py::isinstance<Shape>(item))
      throw TypeError("tag assignment targets must contain only shapes");
    shapes.push_back(item.cast<const Shape&>());
  }
  return TagTargets(std::move(shapes));
}

void bind_operators(py::module_& m) {
  m.def(
      "apply_tag",
      [](const py::object& shape, const std::string& tag) {
        if (!py::isinstance<Shape>(shape)) {
          static const ErrorSpec spec{
              "apply_tag",
              "Failed to attach the tag to the shape.",
              {"The shape is invalid.", "The tag value is empty or malformed."},
              {"Pass a valid shape object.",
               "Use a normalized tag string such as 'role.mounting_surface' or 'group.fasteners'."}};
          raise_harness_error(spec, TypeError("expected a SimpleCAD shape"));
        }
        apply_tag(shape.cast<const Shape&>(), tag);
        return shape;  // the same object, as in Python
      },
      py::arg("shape"), py::arg("tag"), "Attach a local user tag with continuation/fragment lineage policy.");

  m.def(
      "apply_tag_rselection",
      [](const Shape& scope, const py::object& targets, const std::string& tag, TopologyPropagation topology,
         LineagePolicy lineage) {
        static const ErrorSpec spec{
            "apply_tag_rselection",
            "Failed to attach the tag to the selected shapes.",
            {"The assignment scope or target selection is invalid.", "The tag value is empty or malformed.",
             "The selector resolved no targets or references foreign topology."},
            {"Pass a valid scope and a non-empty ShapeSelector or shape sequence.",
             "Use a normalized tag string such as 'role.mounting_surface' or 'group.fasteners'.",
             "Ensure every explicit target belongs to the assignment scope."}};
        return shape_to_py(guarded(
            spec, [&] { return apply_tag_rselection(scope, targets_from_py(targets), tag, topology, lineage); }));
      },
      py::arg("scope"), py::arg("targets"), py::arg("tag"),
      py::arg("topology_propagation") = TopologyPropagation::Local,
      py::arg("lineage_policy") = LineagePolicy::ContinuationFragment,
      "Return a semantic shape view with a canonical tag assignment.");

  m.def(
      "list_tags", [](const Shape& shape, TagScope scope) { return list_tags(shape, scope); }, py::arg("shape"),
      py::arg("scope") = TagScope::Effective, "Return shape tags in deterministic sorted order for one scope.");
  m.def(
      "explain_tag",
      [](const Shape& shape, const std::string& tag, TagScope scope) { return explain_tag(shape, tag, scope); },
      py::arg("shape"), py::arg("tag"), py::arg("scope") = TagScope::Effective,
      "Explain every visible binding that produces a tag token.");
  m.def(
      "select_faces_by_tag",
      [](const Solid& solid, const std::string& tag, TagScope scope) { return select_faces_by_tag(solid, tag, scope); },
      py::arg("solid"), py::arg("tag"), py::arg("scope") = TagScope::Effective, "Select faces by tag.");
  m.def(
      "select_edges_by_tag",
      [](const Shape& shape, const std::string& tag, TagScope scope) { return select_edges_by_tag(shape, tag, scope); },
      py::arg("shape"), py::arg("tag"), py::arg("scope") = TagScope::Effective, "Select edges by tag.");
}

// ---- TaggedMixin's private surface, on every shape class
// --------------------------------------------------------------

void bind_shape_methods(py::module_& m) {
  py::object cls = m.attr("AnyShape");
  const auto method = [&cls](const char* name, auto fn, auto... extras) {
    cls.attr(name) = py::cpp_function(std::move(fn), py::name(name), py::is_method(cls), extras...);
  };

  method(
      "_apply_user_tag",
      [](Shape& s, const std::string& tag, TopologyPropagation topology, LineagePolicy lineage,
         std::optional<std::string> producer_node_id) {
        UserTagOptions o;
        o.node_id = std::move(producer_node_id);
        o.topology = topology;
        o.lineage = lineage;
        TagBinding binding = user_tag_binding(normalize_tag(tag, true), o);
        s.add_binding(binding);
        return binding;
      },
      py::arg("tag"), py::kw_only(), py::arg("topology_propagation") = TopologyPropagation::Local,
      py::arg("lineage_policy") = LineagePolicy::ContinuationFragment, py::arg("producer_node_id") = py::none());
  method("_add_tag_binding", [](Shape& s, const TagBinding& b) { s.add_binding(b); }, py::arg("binding"));
  method(
      "_add_tag_lineage",
      [](Shape& s, const TagBinding& binding, LineageDerivation derivation, const std::string& source_topo_id,
         const TagEvidence& evidence,
         const std::string& coverage) { s.add_tag_lineage(binding, derivation, source_topo_id, evidence, coverage); },
      py::arg("binding"), py::kw_only(), py::arg("derivation"), py::arg("source_topo_id"), py::arg("evidence"),
      py::arg("coverage") = "complete");
  method(
      "_remove_tag",
      [](Shape& s, const std::string& tag, const py::object& matching) {
        if (py::isinstance<TagProducer>(matching))
          return static_cast<int>(s.remove_tag_bindings(tag, matching.cast<const TagProducer&>()));
        return static_cast<int>(s.remove_tag_bindings(tag, matching.cast<TagProducerKind>()));
      },
      py::arg("tag"), py::kw_only(), py::arg("matching_producer") = TagProducerKind::UserOperation);
  method(
      "_remove_tag_binding", [](Shape& s, const std::string& id) { return s.remove_tag_binding(id); },
      py::arg("binding_id"));
  method("_local_tag_bindings", [](const Shape& s) { return s.local_tag_bindings(); });
  method("_legacy_effective_bindings", [](const Shape& s) { return s.legacy_effective_bindings(); });
  method("_inherited_tag_bindings", [](const Shape& s) { return s.inherited_tag_bindings(); });
  method("_lineage_tag_bindings", [](const Shape& s) { return s.lineage_tag_bindings(); });
  method(
      "_list_tag_bindings", [](const Shape& s, TagScope scope) { return s.list_tag_bindings(scope); },
      py::arg("scope") = TagScope::Effective);
  method(
      "_replace_local_tag_bindings",
      [](Shape& s, std::vector<TagBinding> bindings) { s.replace_local_tag_bindings(std::move(bindings)); },
      py::arg("bindings"));
  method(
      "_copy_tag_state_from", [](Shape& s, const Shape& source) { s.copy_tag_state_from(source); }, py::arg("source"));
  method(
      "_copy_semantic_state_from", [](Shape& s, const Shape& source) { s.copy_semantic_state_from(source); },
      py::arg("source"));
  method(
      "_refresh_tag_cache", [](Shape& s, bool recursive) { s.refresh_tag_cache(recursive); }, py::kw_only(),
      py::arg("recursive") = false);

  const py::object property = py::module_::import("builtins").attr("property");
  cls.attr("_tag_bindings") = property(py::cpp_function([](const Shape& s) { return s.local_bindings(); }));
  cls.attr("_tag_lineage") = property(py::cpp_function([](const Shape& s) { return s.lineage_witnesses(); }));
  cls.attr("_tags") =
      property(py::cpp_function([](const Shape& s) { return py::set(py::cast(s.list_tags())); }),
               py::cpp_function([](Shape& s, const py::object& tags) {
                 if (py::isinstance<py::str>(tags) || py::isinstance<py::bytes>(tags) || !py::hasattr(tags, "__iter__"))
                   throw TypeError("_tags compatibility cache must be assigned an iterable");
                 std::vector<std::string> names;
                 for (const py::handle item : tags)
                   names.push_back(item.cast<std::string>());
                 s.set_legacy_tags(names);
               }));
}

}  // namespace

void bind_semantic(py::module_& m) {
  bind_enums(m);
  bind_records(m);
  py::module_ tagging = m.def_submodule("tagging", "The tag data model: bindings, factories, lineage rules.");
  bind_tagging_functions(m, tagging);
  bind_operators(m);
  bind_shape_methods(m);
}
