// STEP assemblies with product structure, names, colours, materials and metadata.
//
// The core of simplecadapi/exporter/step.py (export_product_package_to_step),
// without the package plumbing around it: callers (the product area) describe
// their definitions and occurrences, and this module drives OpenCASCADE's XCAF
// document and STEPCAFControl writer exactly as the Python exporter does --
// AP242 (AP242DIS) schema, one XCAF label per definition (shared by every
// occurrence), AddComponent with the placement as the location, TDataStd_Name /
// TDataStd_Comment per label, XCAF material and surface colour, and the
// "SimpleCAD metadata" property definition carrying every metadata record as a
// named descriptive item of sorted-key JSON.
//
// The reader is the other direction: a STEP file into a tree of named, placed,
// coloured nodes (STEPCAFControl_Reader).
#pragma once

#include <array>
#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <TopoDS_Shape.hxx>

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/io/files.hpp"

namespace scad::io {

// A rigid placement: the columns of the rotation matrix and the translation.
struct StepPlacement {
  Vec3 origin{0, 0, 0};
  Vec3 x_axis{1, 0, 0};
  Vec3 y_axis{0, 1, 0};
  Vec3 z_axis{0, 0, 1};
};

struct StepMaterial {
  std::string id;                       // materials with the same id share one XCAF material
  std::string name;
  Value description = Value::object();  // written as sorted-key JSON in the material's description
  std::optional<double> density;
  std::string density_unit;             // e.g. "kg/m^3"; only used with a density
};

struct StepComponent {
  std::string id;             // identity within the parent (names the metadata record)
  std::string name;
  std::string definition_id;  // the StepDefinition it places
  StepPlacement placement;
  Value metadata = Value::object();  // occurrence record (written as comment + property item)
};

struct StepDefinition {
  std::string id;
  std::string kind = "single_solid";  // "single_solid" or "assembly": part of the metadata record's name
  std::string name;
  TopoDS_Shape shape;                 // a part's body; null for an assembly
  std::vector<StepComponent> components;
  std::optional<std::array<double, 3>> color;  // linear RGB in [0, 1], applied as the surface colour
  std::optional<StepMaterial> material;
  Value metadata = Value::object();  // definition record
};

struct StepAssemblyOptions {
  std::string schema = "AP242DIS";   // value of OCCT's write.step.schema
  bool metadata_properties = true;   // inject the "SimpleCAD metadata" property definition
};

struct StepAssemblyReport {
  std::string schema;
  std::vector<std::string> definition_ids;  // in first-visit order
  std::size_t occurrence_count = 0;
  std::vector<std::string> material_ids;    // sorted
  std::size_t metadata_item_count = 0;
};

// Operation "export_step_assembly".  `root_id` names the definition to export;
// every definition it reaches must be in `definitions`.  Throws scad::Error.
Bytes step_assembly_bytes(const std::vector<StepDefinition>& definitions, std::string_view root_id,
                          const StepAssemblyOptions& options = {}, StepAssemblyReport* report = nullptr);
StepAssemblyReport export_step_assembly(const std::vector<StepDefinition>& definitions, std::string_view root_id,
                                        const std::filesystem::path& path, const StepAssemblyOptions& options = {});

// ---------------------------------------------------------------------------
// Reading
// ---------------------------------------------------------------------------
struct StepNode {
  std::string name;
  TopoDS_Shape shape;  // the part's own body (null for an assembly node)
  StepPlacement placement;  // relative to the parent (identity for roots)
  std::optional<std::array<double, 3>> color;  // surface colour set on this label
  std::vector<StepNode> children;
};

// Operation "import_step_assembly": the free shapes of the document as a tree.
std::vector<StepNode> read_step_assembly_bytes(std::string_view bytes, const std::string& name = "model.step");
std::vector<StepNode> read_step_assembly(const std::filesystem::path& path);

}  // namespace scad::io
