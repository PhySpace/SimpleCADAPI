#include "scad/ql/diagnostics.hpp"

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRep_Tool.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <Geom_Surface.hxx>
#include <TopoDS.hxx>
#include <gp_Cone.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Sphere.hxx>
#include <gp_Torus.hxx>

#include <algorithm>
#include <cmath>
#include <mutex>
#include <numeric>
#include <unordered_map>

#include "internal.hpp"
#include "scad/kernel/properties.hpp"
#include "text.hpp"

namespace scad::ql {

namespace {

using text::general;

std::string class_name(Kind kind) {
  std::string name(kind_name(kind));
  if (!name.empty())
    name[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(name[0])));
  return name;
}

// ---- inventory lines ------------------------------------------------------------------------------------
// "x=[0, 7]": the extent along the surface axis when there is one (the coordinate that tells two
// pieces of one split cylinder apart), else along the longest bounding-box axis.
std::string face_span(const TopoDS_Shape& face, const gp_Dir* axis) {
  try {
    const kernel::BoundingBox box = kernel::bounding_box(face);
    const double low[3] = {box.xmin, box.ymin, box.zmin};
    const double high[3] = {box.xmax, box.ymax, box.zmax};
    double measure[3];
    for (int i = 0; i < 3; ++i)
      measure[i] = axis != nullptr ? 0.0 : high[i] - low[i];
    if (axis != nullptr) {
      measure[0] = std::abs(axis->X());
      measure[1] = std::abs(axis->Y());
      measure[2] = std::abs(axis->Z());
    }
    const int index = static_cast<int>(std::max_element(measure, measure + 3) - measure);
    return std::string(1, "xyz"[index]) + "=[" + general(low[index], 4) + ", " + general(high[index], 4) + "]";
  } catch (const std::exception&) {
    return "n/a";
  }
}

std::string face_summary(const TopoDS_Face& face) {
  const BRepAdaptor_Surface adaptor(face);
  std::string summary;
  std::optional<gp_Dir> axis;  // the rotational axis, when the surface has one
  switch (adaptor.GetType()) {
    case GeomAbs_Plane: {
      const gp_Dir n = adaptor.Plane().Axis().Direction();
      summary = "plane, normal (" + general(n.X(), 3) + ", " + general(n.Y(), 3) + ", " + general(n.Z(), 3) + ")";
      break;
    }
    case GeomAbs_Cylinder: {
      const gp_Cylinder cylinder = adaptor.Cylinder();
      const gp_Dir a = cylinder.Axis().Direction();
      const gp_Pnt p = cylinder.Location();
      summary = "cylinder r=" + general(cylinder.Radius(), 4) + ", axis (" + general(a.X(), 2) + "," +
                general(a.Y(), 2) + "," + general(a.Z(), 2) + ") @ (" + general(p.X(), 3) + "," + general(p.Y(), 3) +
                "," + general(p.Z(), 3) + ")";
      axis = a;
      break;
    }
    case GeomAbs_Cone: {
      const gp_Cone cone = adaptor.Cone();
      summary = "cone half-angle " + general(cone.SemiAngle() * 180.0 / kPi, 3) +
                " deg, r_ref=" + general(cone.RefRadius(), 4);
      axis = cone.Axis().Direction();
      break;
    }
    case GeomAbs_Sphere:
      summary = "sphere r=" + general(adaptor.Sphere().Radius(), 4);
      break;
    case GeomAbs_Torus: {
      const gp_Torus torus = adaptor.Torus();
      summary = "torus R=" + general(torus.MajorRadius(), 4) + ", r=" + general(torus.MinorRadius(), 4);
      break;
    }
    default:
      return "freeform surface, spans " + face_span(face, nullptr);
  }
  return summary + ", spans " + face_span(face, axis ? &*axis : nullptr);
}

std::string edge_summary(const Shape& item) {
  const BRepAdaptor_Curve adaptor(TopoDS::Edge(item.wrapped()));
  const std::string length = general(Edge(item).length(), 4) + " mm";
  switch (adaptor.GetType()) {
    case GeomAbs_Line:
      return "line, length " + length;
    case GeomAbs_Circle:
      return "circular arc r=" + general(adaptor.Circle().Radius(), 4) + ", length " + length;
    default:
      return "curve, length " + length;
  }
}

// ---- logical surfaces -------------------------------------------------------------------------------------------
// What decides whether two faces lie on one quadric surface, measured once per face.
struct SurfaceKey {
  bool valid = false;
  GeomAbs_SurfaceType type = GeomAbs_OtherSurface;
  gp_Pln plane;
  gp_Cylinder cylinder;
  gp_Sphere sphere;
  Handle(Geom_Surface) handle;  // cone / torus: the very same underlying surface object
};

SurfaceKey surface_key(const Shape& face) {
  SurfaceKey key;
  try {
    const TopoDS_Face f = TopoDS::Face(face.wrapped());
    const BRepAdaptor_Surface adaptor(f);
    key.type = adaptor.GetType();
    switch (key.type) {
      case GeomAbs_Plane:
        key.plane = adaptor.Plane();
        break;
      case GeomAbs_Cylinder:
        key.cylinder = adaptor.Cylinder();
        break;
      case GeomAbs_Sphere:
        key.sphere = adaptor.Sphere();
        break;
      case GeomAbs_Cone:
      case GeomAbs_Torus:
        key.handle = BRep_Tool::Surface(f);
        break;
      default:
        break;
    }
    key.valid = true;
  } catch (const Standard_Failure&) {
    key.valid = false;
  }
  return key;
}

bool same_surface(const SurfaceKey& a, const SurfaceKey& b) {
  if (!a.valid || !b.valid || a.type != b.type)
    return false;
  switch (a.type) {
    case GeomAbs_Plane: {
      const double parallel = std::abs(a.plane.Axis().Direction().Dot(b.plane.Axis().Direction()));
      return parallel >= 0.999 && std::abs(a.plane.Distance(b.plane.Location())) < 1e-6;
    }
    case GeomAbs_Cylinder: {
      if (std::abs(a.cylinder.Radius() - b.cylinder.Radius()) > 1e-7)
        return false;
      const gp_Dir da = a.cylinder.Axis().Direction();
      if (std::abs(da.Dot(b.cylinder.Axis().Direction())) < 0.999)
        return false;
      const gp_Pnt oa = a.cylinder.Axis().Location();
      const gp_Pnt ob = b.cylinder.Axis().Location();
      const double delta[3] = {ob.X() - oa.X(), ob.Y() - oa.Y(), ob.Z() - oa.Z()};
      const double along = delta[0] * da.X() + delta[1] * da.Y() + delta[2] * da.Z();
      const double off[3] = {delta[0] - along * da.X(), delta[1] - along * da.Y(), delta[2] - along * da.Z()};
      return std::sqrt(off[0] * off[0] + off[1] * off[1] + off[2] * off[2]) < 1e-6;
    }
    case GeomAbs_Sphere:
      return a.sphere.Location().Distance(b.sphere.Location()) < 1e-6 &&
             std::abs(a.sphere.Radius() - b.sphere.Radius()) < 1e-7;
    case GeomAbs_Cone:
    case GeomAbs_Torus:
      return !a.handle.IsNull() && a.handle.get() == b.handle.get();
    default:
      return false;
  }
}

// ---- evidence hook
// -----------------------------------------------------------------------------------------------------
struct EvidenceSlot {
  std::mutex mutex;
  EvidenceProvider provider;
};

EvidenceSlot& evidence_slot() {
  static EvidenceSlot slot;
  return slot;
}

std::vector<ErrorEvidence> collect_evidence(const EvidenceRequest& request) {
  EvidenceProvider provider;
  {
    const std::lock_guard<std::mutex> lock(evidence_slot().mutex);
    provider = evidence_slot().provider;
  }
  if (!provider)
    return {};
  try {
    return provider(request);
  } catch (const std::exception&) {
    return {};
  }
}

// ---- the cardinality message
// ---------------------------------------------------------------------------------------------- One letter per kind,
// so error text and rendered evidence can say "F3" and "E7" unambiguously.
std::string symbol_prefix(const std::string& target_kind) {
  if (target_kind == "face")
    return "F";
  if (target_kind == "edge")
    return "E";
  if (target_kind == "vertex")
    return "V";
  if (target_kind == "shell")
    return "S";
  if (target_kind == "wire")
    return "W";
  if (target_kind == "body")
    return "B";
  if (target_kind.empty())
    throw ValueError("empty target kind");
  return text::upper(std::string_view(target_kind).substr(0, 1));
}

[[noreturn]] void cardinality_failure(const std::string& target_kind, const std::vector<Shape>& matched,
                                      std::int64_t expected, const std::string& mode, const Scope& scope) {
  const std::vector<Shape> candidates = detail::scope_items(scope, target_kind);
  const std::string prefix = symbol_prefix(target_kind);
  const IdentitySet matched_set(matched.begin(), matched.end());
  const auto matched_count = static_cast<std::int64_t>(matched.size());

  // Symbols follow the candidate enumeration, so hits and near misses share one naming for the scope.
  std::vector<InventoryEntry> inventory;
  std::vector<char> is_hit(candidates.size(), 0);
  std::size_t near_misses_listed = 0;
  for (std::size_t i = 0; i < candidates.size(); ++i) {
    const bool hit = matched_set.contains(candidates[i]);
    if (hit) {
      is_hit[i] = 1;
    } else {
      if (near_misses_listed >= 8)
        continue;
      ++near_misses_listed;
    }
    inventory.push_back(
        {prefix + std::to_string(i + 1), hit ? "hit" : "near_miss", entity_geometry_summary(candidates[i])});
  }

  const std::vector<std::vector<std::size_t>> groups = target_kind == "face" && matched.size() > 1
                                                           ? face_logical_groups(matched)
                                                           : std::vector<std::vector<std::size_t>>{};

  std::vector<ErrorMeasurement> measurements = {
      {"matched_count", static_cast<double>(matched.size()), ""},
      {"candidate_count", static_cast<double>(candidates.size()), ""},
      {"expected_count", static_cast<double>(expected), ""},
  };

  std::unordered_map<Shape, std::size_t, IdentityHash, IdentityEqual> candidate_index;
  for (std::size_t i = 0; i < candidates.size(); ++i)
    candidate_index[candidates[i]] = i;

  std::vector<std::string> repair;
  if (matched_count > expected && !groups.empty()) {
    std::vector<std::string> group_symbols;
    for (const auto& group : groups) {
      std::vector<std::size_t> indices;
      for (const std::size_t position : group)
        indices.push_back(candidate_index.at(matched[position]));
      if (std::all_of(indices.begin(), indices.end(), [&](std::size_t i) { return is_hit[i] != 0; })) {
        std::vector<std::string> names;
        for (const std::size_t i : indices)
          names.push_back(prefix + std::to_string(i + 1));
        group_symbols.push_back(text::join(names, "+"));
      }
    }
    if (!group_symbols.empty())
      repair.push_back(text::join(group_symbols, ", ") +
                       " lie on one logical surface split by a seam \xE2\x80\x94 select the whole group (drop "
                       "the exactly(1) assertion) or target it via a role tag.");
  }
  if (matched_count > expected)
    repair.push_back(
        "Tighten the predicate (position/axis/tag constraints) or take an explicit member with "
        ".first()/.take(n) instead of exactly().");
  if (matched_count < expected) {
    repair.push_back(
        "No entity satisfies the full predicate; the near-miss inventory above lists what actually exists "
        "\xE2\x80\x94 align predicate values with those measured geometries.");
    repair.push_back(
        "Booleans and fillets re-split topology; re-derive the selector from the newest shape instead of "
        "reusing one resolved earlier.");
  }

  std::vector<Shape> near_misses;
  for (const Shape& candidate : candidates) {
    if (near_misses.size() == 3)
      break;
    if (!matched_set.contains(candidate))
      near_misses.push_back(candidate);
  }
  const EvidenceRequest request{
      scope,
      matched,
      near_misses,
      target_kind,
      mode,
      expected,
      "ql|" + target_kind + "|" + mode + "|" + std::to_string(expected) + "|" + std::to_string(matched.size())};

  std::string spaced_mode = mode;
  std::replace(spaced_mode.begin(), spaced_mode.end(), '_', ' ');
  std::string what = "QL selector expected " + spaced_mode + " " + std::to_string(expected) + " " + target_kind +
                     "(s), got " + std::to_string(matched.size());
  if (!groups.empty())
    what += "; the matched faces include " + std::to_string(groups.size()) + " logical surface group(s) split by seams";

  const std::string operation = "ql." + target_kind + ".resolve";
  ErrorGuidance guidance;
  guidance.what_happened = std::move(what);
  guidance.possible_causes = {"The predicate does not match the actual geometry values.",
                              "OCCT split one logical face into several at a seam after a boolean.",
                              "The selector was resolved against an older shape state."};
  guidance.how_to_fix = {"Read the inventory: hit = matched, near_miss = what exists instead.",
                         "Re-derive selectors from the newest shape after topology-changing ops."};
  guidance.documentation_hint = "For full usage details, run help(" + operation + ").";
  guidance.measurements = std::move(measurements);
  guidance.evidence = collect_evidence(request);
  guidance.repair = std::move(repair);
  guidance.inventory = std::move(inventory);
  throw Error(operation, std::move(guidance));
}

}  // namespace

std::string entity_geometry_summary(const Shape& shape) {
  try {
    return occt_guard([&]() -> std::string {
      switch (shape.kind()) {
        case Kind::Face:
          return face_summary(TopoDS::Face(shape.wrapped()));
        case Kind::Edge:
          return edge_summary(shape);
        case Kind::Vertex: {
          const Vec3 p = Vertex(shape).coordinates();
          return "(" + general(p.x, 4) + ", " + general(p.y, 4) + ", " + general(p.z, 4) + ")";
        }
        default:
          return std::string(kind_name(shape.kind()));
      }
    });
  } catch (const std::exception&) {
    return class_name(shape.kind());
  }
}

std::vector<std::vector<std::size_t>> face_logical_groups(const std::vector<Shape>& faces) {
  std::vector<SurfaceKey> keys;
  keys.reserve(faces.size());
  for (const Shape& face : faces)
    keys.push_back(surface_key(face));

  std::vector<std::size_t> parent(faces.size());
  std::iota(parent.begin(), parent.end(), std::size_t{0});
  const auto find = [&](std::size_t node) {
    while (parent[node] != node) {
      parent[node] = parent[parent[node]];
      node = parent[node];
    }
    return node;
  };
  for (std::size_t i = 0; i < faces.size(); ++i) {
    for (std::size_t j = i + 1; j < faces.size(); ++j) {
      if (!same_surface(keys[i], keys[j]))
        continue;
      const std::size_t root_i = find(i);
      const std::size_t root_j = find(j);
      if (root_i != root_j)
        parent[root_i] = root_j;
    }
  }

  // Groups in order of their first member, as Python's insertion-ordered dict yields them.
  std::vector<std::vector<std::size_t>> groups;
  std::unordered_map<std::size_t, std::size_t> slot_of_root;
  for (std::size_t i = 0; i < faces.size(); ++i) {
    const std::size_t root = find(i);
    const auto [it, inserted] = slot_of_root.try_emplace(root, groups.size());
    if (inserted)
      groups.emplace_back();
    groups[it->second].push_back(i);
  }
  std::erase_if(groups, [](const std::vector<std::size_t>& g) { return g.size() < 2; });
  return groups;
}

void set_evidence_provider(EvidenceProvider provider) {
  const std::lock_guard<std::mutex> lock(evidence_slot().mutex);
  evidence_slot().provider = std::move(provider);
}

void raise_cardinality_failure(const std::string& target_kind, const std::vector<Shape>& matched, std::int64_t expected,
                               const std::string& mode, const Scope& scope) {
  try {
    cardinality_failure(target_kind, matched, expected, mode, scope);
  } catch (const Error&) {
    throw;
  } catch (const std::exception&) {
    // The diagnosis must never mask the failure it describes.
    throw ValueError("QL selector expected " + mode + " " + std::to_string(expected) + " " + target_kind + "(s), got " +
                     std::to_string(matched.size()));
  }
}

}  // namespace scad::ql
