// loft_rshell: an open loft Shell through Wire sections, with named endpoint wires.
#include <algorithm>

#include <BRepFill_ThruSectionErrorStatus.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <TopoDS.hxx>

#include "finalize.hpp"
#include "internal.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/semantic/tracking.hpp"
#include "scad/surface/hooks.hpp"
#include "scad/surface/operators.hpp"

namespace scad {

using namespace surface::detail;

namespace {

constexpr const char* kOp = "make_loft_rshell";  // the recorded name; errors say loft_rshell

const char* status_name(BRepFill_ThruSectionErrorStatus status) {
  switch (status) {
    case BRepFill_ThruSectionErrorStatus_Done:
      return "BRepFill_ThruSectionErrorStatus_Done";
    case BRepFill_ThruSectionErrorStatus_NotDone:
      return "BRepFill_ThruSectionErrorStatus_NotDone";
    case BRepFill_ThruSectionErrorStatus_NotSameTopology:
      return "BRepFill_ThruSectionErrorStatus_NotSameTopology";
    case BRepFill_ThruSectionErrorStatus_ProfilesInconsistent:
      return "BRepFill_ThruSectionErrorStatus_ProfilesInconsistent";
    case BRepFill_ThruSectionErrorStatus_WrongUsage:
      return "BRepFill_ThruSectionErrorStatus_WrongUsage";
    case BRepFill_ThruSectionErrorStatus_Null3DCurve:
      return "BRepFill_ThruSectionErrorStatus_Null3DCurve";
    case BRepFill_ThruSectionErrorStatus_Failed:
      return "BRepFill_ThruSectionErrorStatus_Failed";
  }
  return "unknown";
}

const Shape& section_shape(const LoftSection& section) {
  return std::visit([](const auto& s) -> const Shape& { return s; }, section);
}

// _validated_loft_sections
void validate_sections(const std::vector<LoftSection>& sections) {
  if (sections.size() < 2)
    throw ValueError("loft_rshell requires at least two sections");
  const auto is_wire = [](const LoftSection& s) { return std::holds_alternative<Wire>(s); };
  if (std::none_of(sections.begin(), sections.end(), is_wire))
    throw ValueError("loft_rshell requires at least one Wire section");
  if (std::any_of(sections.begin() + 1, sections.end() - 1, [&](const LoftSection& s) { return !is_wire(s); }))
    throw ValueError("loft_rshell allows Vertex sections only at the start or end");
}

TopoDS_Shell make_loft_shell(const std::vector<LoftSection>& sections, bool ruled) {
  BRepOffsetAPI_ThruSections builder(false, ruled);
  builder.CheckCompatibility(true);
  for (const LoftSection& section : sections) {
    if (const Vertex* vertex = std::get_if<Vertex>(&section))
      builder.AddVertex(TopoDS::Vertex(vertex->wrapped()));
    else
      builder.AddWire(TopoDS::Wire(std::get<Wire>(section).wrapped()));
  }
  builder.Build();
  if (!builder.IsDone())
    throw ValueError(std::string("OCP surface loft failed with status ") + status_name(builder.GetStatus()));
  const TopoDS_Shape shape = builder.Shape();
  if (shape.ShapeType() == TopAbs_SHELL)
    return TopoDS::Shell(shape);
  const std::vector<TopoDS_Shape> shells = kernel::explore(shape, TopAbs_SHELL);
  if (shells.size() != 1)
    throw ValueError("surface loft must create exactly one shell, got " + std::to_string(shells.size()));
  return TopoDS::Shell(shells.front());
}

// _pending_loft_role: a kernel-proven role of one face or wire of the result.
TopoRoleEntry proven_role(const Shape& member, const char* role, const char* method) {
  TopoRoleEntry entry;
  entry.ref.kind = member.kind();
  entry.ref.topo_id = kernel_topo_id(member.wrapped());
  entry.role = role;
  entry.metadata = Value::object();
  entry.metadata.set("coverage", "complete");
  entry.metadata.set("status", "proven");
  entry.metadata.set("evidence_kind", "kernel_operation_role");
  entry.metadata.set("evidence_method", method);
  return entry;
}

// _matching_shell_boundary: the one free boundary of `shell` made of exactly the profile's edges.
Wire matching_shell_boundary(const Shell& shell, const Wire& profile) {
  const std::vector<TopoDS_Edge> profile_edges = kernel::edges_of(profile.wrapped());
  std::vector<Wire> matches;
  for (const Wire& boundary : shell.wires()) {
    const std::vector<TopoDS_Edge> edges = kernel::edges_of(boundary.wrapped());
    const bool same =
        edges.size() == profile_edges.size() &&
        std::all_of(profile_edges.begin(), profile_edges.end(), [&](const TopoDS_Edge& wanted) {
          return std::any_of(edges.begin(), edges.end(), [&](const TopoDS_Edge& e) { return e.IsSame(wanted); });
        });
    if (same)
      matches.push_back(boundary);
  }
  if (matches.size() != 1)
    throw ValueError("loft endpoint profile must match exactly one result boundary, got " +
                     std::to_string(matches.size()));
  return matches.front();
}

}  // namespace

Shell loft_rshell(const std::vector<LoftSection>& sections, bool ruled, const LoftShellTags& tags) {
  static const ErrorSpec kSpec{
      "loft_rshell",
      "Failed to create the surface loft shell.",
      {"Sections are incompatible or a Vertex was used away from an endpoint.", "The kernel loft algorithm failed."},
      {"Pass at least two Wire or endpoint Vertex sections in loft order."}};
  return guarded(kSpec, [&]() -> Shell {
    try {
      return occt_guard([&] {
        validate_sections(sections);
        const bool start_is_wire = std::holds_alternative<Wire>(sections.front());
        const bool end_is_wire = std::holds_alternative<Wire>(sections.back());
        if (tags.start_wire_tag && !start_is_wire)
          throw ValueError("start_wire_tag requires a Wire start section");
        if (tags.end_wire_tag && !end_is_wire)
          throw ValueError("end_wire_tag requires a Wire end section");
        // Bad tag names fail before any geometry is built.
        (void)plan_output_tags(kOp, {.tag_prefix = tags.tag_prefix,
                                     .result_tag = tags.result_tag,
                                     .roles = {{"loft.start_wire", tags.start_wire_tag},
                                               {"loft.end_wire", tags.end_wire_tag},
                                               {"loft.side", tags.side_faces_tag}}});

        const Shell result{make_loft_shell(sections, ruled)};
        LoftOutput output;
        for (const Face& face : result.faces())
          output.delta.roles.push_back(proven_role(face, "loft.side", "ResultSideFace"));
        if (start_is_wire)
          output.delta.roles.push_back(proven_role(matching_shell_boundary(result, std::get<Wire>(sections.front())),
                                                   "loft.start_wire", "EndpointBoundary"));
        if (end_is_wire)
          output.delta.roles.push_back(proven_role(matching_shell_boundary(result, std::get<Wire>(sections.back())),
                                                   "loft.end_wire", "EndpointBoundary"));

        output.tags = tags;
        output.has_start = start_is_wire;
        output.has_end = end_is_wire;
        output.record.op = kOp;
        output.record.params = Value::object();
        output.record.params.set("section_count", static_cast<std::int64_t>(sections.size()));
        output.record.params.set("ruled", ruled);
        output.record.params.set("tag_prefix", to_value(tags.tag_prefix));
        for (const LoftSection& section : sections)
          output.record.inputs.push_back({section_shape(section), "section"});
        return finalize_surface_output(result, std::move(output));
      });
    } catch (const Error&) {
      throw;
    } catch (const std::exception&) {
      // The kernel's "did not complete" names nothing; a section-compatibility verdict does.
      diagnose_loft_failure(sections, "loft_rshell");
      throw;
    }
  });
}

}  // namespace scad
