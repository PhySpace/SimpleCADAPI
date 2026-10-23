#include "scad/io/step_assembly.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <sstream>

#include <BRep_Builder.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <Interface_InterfaceModel.hxx>
#include <Interface_Static.hxx>
#include <NCollection_UtfString.hxx>
#include <Quantity_Color.hxx>
#include <STEPCAFControl_Reader.hxx>
#include <STEPCAFControl_Writer.hxx>
#include <STEPControl_Writer.hxx>
#include <StepBasic_ProductDefinition.hxx>
#include <StepData_StepModel.hxx>
#include <StepRepr_CharacterizedDefinition.hxx>
#include <StepRepr_DescriptiveRepresentationItem.hxx>
#include <StepRepr_HArray1OfRepresentationItem.hxx>
#include <StepRepr_ProductDefinitionShape.hxx>
#include <StepRepr_PropertyDefinition.hxx>
#include <StepRepr_PropertyDefinitionRepresentation.hxx>
#include <StepRepr_Representation.hxx>
#include <StepRepr_RepresentedDefinition.hxx>
#include <StepShape_ShapeDefinitionRepresentation.hxx>
#include <TCollection_ExtendedString.hxx>
#include <TCollection_HAsciiString.hxx>
#include <TDF_Label.hxx>
#include <TDF_LabelSequence.hxx>
#include <TDataStd_Comment.hxx>
#include <TDataStd_Name.hxx>
#include <TDocStd_Document.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS_Compound.hxx>
#include <XCAFApp_Application.hxx>
#include <XCAFDoc_ColorTool.hxx>
#include <XCAFDoc_ColorType.hxx>
#include <XCAFDoc_DocumentTool.hxx>
#include <XCAFDoc_MaterialTool.hxx>
#include <XCAFDoc_ShapeTool.hxx>
#include <XSControl_WorkSession.hxx>
#include <gp_Trsf.hxx>

#include "bytes.hpp"
#include "exchange_lock.hpp"
#include "occt_messages.hpp"
#include "scad/core/error.hpp"
#include "scad/io/json.hpp"

namespace scad::io {

namespace {

constexpr const char* kSchemaKey = "write.step.schema";

const ErrorSpec& export_spec() {
  static const ErrorSpec spec{"export_step_assembly",
                              "Failed to export the assembly as STEP.",
                              {"A component refers to a definition that was not provided, or the assembly is cyclic.",
                               "A placement is not a rigid transform (its axes are not orthonormal).",
                               "OpenCASCADE rejected the schema or could not translate the document."},
                              {"Provide every referenced definition and avoid cycles.",
                               "Use orthonormal, right-handed placement axes.",
                               "Use schema AP242DIS, AP214IS or AP203."}};
  return spec;
}

const ErrorSpec& import_spec() {
  static const ErrorSpec spec{"import_step_assembly",
                              "Failed to read the STEP assembly.",
                              {"The file does not exist or is not ISO 10303-21 text.",
                               "The file holds no transferable shapes."},
                              {"Check the path.", "Open the file in a CAD viewer to confirm it holds geometry."}};
  return spec;
}

TCollection_ExtendedString extended(const std::string& utf8) { return TCollection_ExtendedString(utf8.c_str(), true); }
Handle(TCollection_HAsciiString) ascii(const std::string& text) { return new TCollection_HAsciiString(text.c_str()); }

std::string utf8_of(const TCollection_ExtendedString& text) {
  const NCollection_Utf16String utf16(text.ToExtString());
  const NCollection_Utf8String utf8 = utf16.ToUtf8();
  return std::string(utf8.ToCString());
}

// gp_Trsf::SetValues quietly accepts a scaling or sheared matrix; a placement must be a rotation.
void require_rigid(const StepPlacement& p, const std::string& where) {
  constexpr double kTolerance = 1e-9;
  const bool unit = std::fabs(p.x_axis.norm() - 1.0) < kTolerance && std::fabs(p.y_axis.norm() - 1.0) < kTolerance &&
                    std::fabs(p.z_axis.norm() - 1.0) < kTolerance;
  const bool orthogonal = std::fabs(p.x_axis.dot(p.y_axis)) < kTolerance && std::fabs(p.y_axis.dot(p.z_axis)) < kTolerance &&
                          std::fabs(p.z_axis.dot(p.x_axis)) < kTolerance;
  const bool right_handed = p.x_axis.cross(p.y_axis).dot(p.z_axis) > 0.0;
  if (!(unit && orthogonal && right_handed && p.origin.is_finite()))
    throw ValueError("the placement of " + where + " is not a rigid transform: its axes must be unit length, mutually "
                     "orthogonal and right-handed, and its origin finite");
}

gp_Trsf to_trsf(const StepPlacement& p) {
  gp_Trsf t;
  t.SetValues(p.x_axis.x, p.y_axis.x, p.z_axis.x, p.origin.x,  //
              p.x_axis.y, p.y_axis.y, p.z_axis.y, p.origin.y,  //
              p.x_axis.z, p.y_axis.z, p.z_axis.z, p.origin.z);
  return t;
}

StepPlacement from_trsf(const gp_Trsf& t) {
  StepPlacement p;
  p.x_axis = {t.Value(1, 1), t.Value(2, 1), t.Value(3, 1)};
  p.y_axis = {t.Value(1, 2), t.Value(2, 2), t.Value(3, 2)};
  p.z_axis = {t.Value(1, 3), t.Value(2, 3), t.Value(3, 3)};
  p.origin = {t.Value(1, 4), t.Value(2, 4), t.Value(3, 4)};
  return p;
}

std::string metadata_text(const Value& value) { return python_json_dumps(value, /*sort_keys=*/true, /*ensure_ascii=*/true); }

// ---------------------------------------------------------------------------
// Writing
// ---------------------------------------------------------------------------
class AssemblyBuilder {
 public:
  AssemblyBuilder(const std::vector<StepDefinition>& definitions) {
    for (const StepDefinition& d : definitions) {
      if (!by_id_.emplace(d.id, &d).second) throw ValueError("duplicate definition id '" + d.id + "'");
    }
    XCAFApp_Application::GetApplication();
    document_ = new TDocStd_Document(TCollection_ExtendedString("BinXCAF"));
    shape_tool_ = XCAFDoc_DocumentTool::ShapeTool(document_->Main());
    color_tool_ = XCAFDoc_DocumentTool::ColorTool(document_->Main());
    material_tool_ = XCAFDoc_DocumentTool::MaterialTool(document_->Main());
  }

  TDF_Label build(const std::string& root_id) {
    const TDF_Label root = definition_label(root_id);
    shape_tool_->UpdateAssemblies();
    shape_tool_->ComputeShapes(root);
    return root;
  }

  const std::vector<std::pair<std::string, Value>>& metadata_records() const { return metadata_; }
  std::size_t occurrence_count() const { return occurrences_; }
  const std::vector<std::string>& visited() const { return visited_; }
  std::vector<std::string> material_ids() const {
    std::vector<std::string> ids;
    for (const auto& [id, label] : material_labels_) ids.push_back(id);
    return ids;  // std::map keeps them sorted
  }

 private:
  void set_name(const TDF_Label& label, const std::string& name) { TDataStd_Name::Set(label, extended(name)); }
  void set_comment(const TDF_Label& label, const Value& payload) {
    TDataStd_Comment::Set(label, extended(metadata_text(payload)));
  }

  TDF_Label material_label(const StepMaterial& material) {
    const auto found = material_labels_.find(material.id);
    if (found != material_labels_.end()) return found->second;
    const double density = material.density.value_or(0.0);
    const std::string density_name = material.density ? material.density_unit : std::string();
    const std::string density_type = material.density ? "mass density" : std::string();
    const TDF_Label label = material_tool_->AddMaterial(ascii(material.name.empty() ? material.id : material.name),
                                                        ascii(metadata_text(material.description)), density,
                                                        ascii(density_name), ascii(density_type));
    material_labels_.emplace(material.id, label);
    return label;
  }

  TDF_Label definition_label(const std::string& id) {
    // A definition is registered as soon as its label exists, so the cycle check must come first:
    // an assembly that contains itself would otherwise find its own half-built label and recurse
    // without end inside OpenCASCADE.
    if (in_progress_.count(id) != 0) throw ValueError("definition '" + id + "' contains itself");
    if (const auto found = labels_.find(id); found != labels_.end()) return found->second;
    const auto def = by_id_.find(id);
    if (def == by_id_.end()) throw ValueError("definition '" + id + "' is not among the provided definitions");
    in_progress_.insert(id);
    const StepDefinition& d = *def->second;
    visited_.push_back(id);

    const bool is_part = !d.shape.IsNull();
    TDF_Label label;
    if (is_part) {
      label = shape_tool_->AddShape(d.shape, /*makeAssembly=*/Standard_False, /*makePrepare=*/Standard_False);
    } else {
      BRep_Builder builder;
      TopoDS_Compound empty;
      builder.MakeCompound(empty);
      label = shape_tool_->AddShape(empty, Standard_False, Standard_False);
    }
    labels_.emplace(id, label);
    set_name(label, d.name.empty() ? d.id : d.name);
    set_comment(label, d.metadata);
    metadata_.emplace_back("SimpleCAD:definition:" + d.kind + ":" + d.id, d.metadata);

    if (is_part) {
      if (d.material) {
        material_tool_->SetMaterial(label, material_label(*d.material));
      }
      if (d.color) {
        color_tool_->SetColor(label, Quantity_Color((*d.color)[0], (*d.color)[1], (*d.color)[2], Quantity_TOC_RGB),
                              XCAFDoc_ColorSurf);
      }
    } else {
      for (const StepComponent& c : d.components) {
        require_rigid(c.placement, "component '" + c.id + "' of '" + d.id + "'");
        const TDF_Label child = definition_label(c.definition_id);
        const TDF_Label component = shape_tool_->AddComponent(label, child, TopLoc_Location(to_trsf(c.placement)));
        set_name(component, c.name.empty() ? c.id : c.name);
        set_comment(component, c.metadata);
        metadata_.emplace_back("SimpleCAD:occurrence:" + d.id + ":" + c.id, c.metadata);
        ++occurrences_;
      }
      shape_tool_->UpdateAssemblies();
      shape_tool_->ComputeShapes(label);
    }
    in_progress_.erase(id);
    return label;
  }

  std::map<std::string, const StepDefinition*> by_id_;
  Handle(TDocStd_Document) document_;
  Handle(XCAFDoc_ShapeTool) shape_tool_;
  Handle(XCAFDoc_ColorTool) color_tool_;
  Handle(XCAFDoc_MaterialTool) material_tool_;
  std::map<std::string, TDF_Label> labels_;
  std::map<std::string, TDF_Label> material_labels_;
  std::set<std::string> in_progress_;
  std::vector<std::string> visited_;
  std::vector<std::pair<std::string, Value>> metadata_;
  std::size_t occurrences_ = 0;

 public:
  const Handle(TDocStd_Document) & document() const { return document_; }
};

// _inject_metadata_properties: one PropertyDefinitionRepresentation on the root
// product definition whose items are the named JSON records.
void inject_metadata_properties(STEPCAFControl_Writer& writer,
                                const std::vector<std::pair<std::string, Value>>& records) {
  if (records.empty()) return;
  const Handle(Interface_InterfaceModel) model = writer.ChangeWriter().WS()->Model();
  Handle(StepBasic_ProductDefinition) root_definition;
  Handle(StepRepr_RepresentationContext) context;
  for (int index = 1; index <= model->NbEntities(); ++index) {
    const Handle(StepShape_ShapeDefinitionRepresentation) entity =
        Handle(StepShape_ShapeDefinitionRepresentation)::DownCast(model->Value(index));
    if (entity.IsNull()) continue;
    const Handle(StepRepr_ProductDefinitionShape) represented =
        Handle(StepRepr_ProductDefinitionShape)::DownCast(entity->Definition().Value());
    if (represented.IsNull()) continue;
    const Handle(StepBasic_ProductDefinition) characterized =
        Handle(StepBasic_ProductDefinition)::DownCast(represented->Definition().Value());
    if (characterized.IsNull()) continue;
    root_definition = characterized;
    context = entity->UsedRepresentation()->ContextOfItems();
    break;
  }
  if (root_definition.IsNull() || context.IsNull())
    throw RuntimeError("STEPCAF transfer did not create a root product definition");

  Handle(StepRepr_HArray1OfRepresentationItem) items =
      new StepRepr_HArray1OfRepresentationItem(1, static_cast<int>(records.size()));
  int slot = 1;
  for (const auto& [name, payload] : records) {
    Handle(StepRepr_DescriptiveRepresentationItem) item = new StepRepr_DescriptiveRepresentationItem();
    item->Init(ascii(name), ascii(metadata_text(payload)));
    items->SetValue(slot++, item);
  }
  Handle(StepRepr_Representation) representation = new StepRepr_Representation();
  representation->Init(ascii("SimpleCAD metadata"), items, context);
  StepRepr_CharacterizedDefinition characterized_definition;
  characterized_definition.SetValue(root_definition);
  Handle(StepRepr_PropertyDefinition) property_definition = new StepRepr_PropertyDefinition();
  property_definition->Init(ascii("SimpleCAD metadata"), Standard_True,
                            ascii("Canonical product definition and occurrence metadata"), characterized_definition);
  StepRepr_RepresentedDefinition represented_definition;
  represented_definition.SetValue(property_definition);
  Handle(StepRepr_PropertyDefinitionRepresentation) property_representation =
      new StepRepr_PropertyDefinitionRepresentation();
  property_representation->Init(represented_definition, representation);
  model->AddWithRefs(property_representation);
}

// Restores a process-global OCCT parameter when the export is over.
class SchemaScope {
 public:
  explicit SchemaScope(const std::string& schema) : prior_(Interface_Static::IVal(kSchemaKey)) {
    if (!Interface_Static::SetCVal(kSchemaKey, schema.c_str()))
      throw ValueError("the OpenCASCADE STEP writer does not accept the schema '" + schema + "'");
  }
  ~SchemaScope() { Interface_Static::SetIVal(kSchemaKey, prior_); }
  SchemaScope(const SchemaScope&) = delete;
  SchemaScope& operator=(const SchemaScope&) = delete;

 private:
  int prior_;
};

}  // namespace

Bytes step_assembly_bytes(const std::vector<StepDefinition>& definitions, std::string_view root_id,
                          const StepAssemblyOptions& options, StepAssemblyReport* report) {
  return guarded(export_spec(), [&]() -> Bytes {
    const std::lock_guard<std::mutex> lock(detail::data_exchange_mutex());
    const detail::MessageCapture messages;
    return occt_guard([&]() -> Bytes {
      AssemblyBuilder builder(definitions);
      const TDF_Label root = builder.build(std::string(root_id));

      STEPCAFControl_Writer writer;
      writer.SetNameMode(Standard_True);
      writer.SetColorMode(Standard_True);
      writer.SetMaterialMode(Standard_True);
      writer.SetPropsMode(Standard_True);
      const SchemaScope schema(options.schema);
      if (!writer.Transfer(root)) throw RuntimeError("STEPCAF transfer failed: " + messages.text());
      if (options.metadata_properties) inject_metadata_properties(writer, builder.metadata_records());
      std::ostringstream out(std::ios::binary);
      const IFSelect_ReturnStatus status = writer.WriteStream(out);
      if (status != IFSelect_RetDone) throw RuntimeError("STEPCAF write failed: " + messages.text());
      Bytes bytes = std::move(out).str();
      if (bytes.empty()) throw RuntimeError("STEPCAF export produced an empty STEP file");

      if (report != nullptr) {
        report->schema = options.schema;
        report->definition_ids = builder.visited();
        report->occurrence_count = builder.occurrence_count();
        report->material_ids = builder.material_ids();
        report->metadata_item_count = options.metadata_properties ? builder.metadata_records().size() : 0;
      }
      return bytes;
    });
  });
}

StepAssemblyReport export_step_assembly(const std::vector<StepDefinition>& definitions, std::string_view root_id,
                                        const std::filesystem::path& path, const StepAssemblyOptions& options) {
  return guarded(export_spec(), [&] {
    StepAssemblyReport report;
    write_file(path, step_assembly_bytes(definitions, root_id, options, &report));
    return report;
  });
}

// ---------------------------------------------------------------------------
// Reading
// ---------------------------------------------------------------------------
namespace {

std::string label_name(const TDF_Label& label) {
  Handle(TDataStd_Name) name;
  if (label.FindAttribute(TDataStd_Name::GetID(), name)) return utf8_of(name->Get());
  return {};
}

std::optional<std::array<double, 3>> label_color(const Handle(XCAFDoc_ColorTool)& tool, const TDF_Label& label) {
  Quantity_Color color;
  if (!tool->GetColor(label, XCAFDoc_ColorSurf, color) && !tool->GetColor(label, XCAFDoc_ColorGen, color))
    return std::nullopt;
  return std::array<double, 3>{color.Red(), color.Green(), color.Blue()};
}

StepNode build_node(const Handle(XCAFDoc_ShapeTool)& shapes, const Handle(XCAFDoc_ColorTool)& colors,
                    const TDF_Label& label, const TDF_Label& instance, int depth) {
  if (depth > 64) throw ValueError("the STEP assembly is nested too deeply");
  StepNode node;
  node.name = label_name(instance.IsNull() ? label : instance);
  if (node.name.empty()) node.name = label_name(label);
  if (!instance.IsNull()) node.placement = from_trsf(XCAFDoc_ShapeTool::GetLocation(instance).Transformation());
  node.color = label_color(colors, label);
  if (XCAFDoc_ShapeTool::IsAssembly(label)) {
    TDF_LabelSequence components;
    XCAFDoc_ShapeTool::GetComponents(label, components);
    for (int i = 1; i <= components.Length(); ++i) {
      TDF_Label referred;
      if (!XCAFDoc_ShapeTool::GetReferredShape(components.Value(i), referred)) continue;
      node.children.push_back(build_node(shapes, colors, referred, components.Value(i), depth + 1));
    }
  } else {
    node.shape = XCAFDoc_ShapeTool::GetShape(label);
  }
  return node;
}

std::vector<StepNode> read_tree(std::istream& in, const std::string& name) {
  const std::lock_guard<std::mutex> lock(detail::data_exchange_mutex());
  const detail::MessageCapture messages;
  return occt_guard([&] {
    XCAFApp_Application::GetApplication();
    Handle(TDocStd_Document) document = new TDocStd_Document(TCollection_ExtendedString("BinXCAF"));
    STEPCAFControl_Reader reader;
    reader.SetColorMode(Standard_True);
    reader.SetNameMode(Standard_True);
    const IFSelect_ReturnStatus status = reader.ReadStream(name.c_str(), in);
    if (status != IFSelect_RetDone) throw ValueError("could not read STEP file " + name + ": " + messages.text());
    if (!reader.Transfer(document)) throw ValueError("STEP file " + name + " transferred no shapes: " + messages.text());
    const Handle(XCAFDoc_ShapeTool) shapes = XCAFDoc_DocumentTool::ShapeTool(document->Main());
    const Handle(XCAFDoc_ColorTool) colors = XCAFDoc_DocumentTool::ColorTool(document->Main());
    TDF_LabelSequence roots;
    shapes->GetFreeShapes(roots);
    if (roots.Length() < 1) throw ValueError("STEP file " + name + " contains no free shapes");
    std::vector<StepNode> tree;
    for (int i = 1; i <= roots.Length(); ++i) tree.push_back(build_node(shapes, colors, roots.Value(i), TDF_Label(), 0));
    return tree;
  });
}

}  // namespace

std::vector<StepNode> read_step_assembly_bytes(std::string_view bytes, const std::string& name) {
  return guarded(import_spec(), [&] {
    detail::ViewStream in(bytes);
    return read_tree(in, name);
  });
}

std::vector<StepNode> read_step_assembly(const std::filesystem::path& path) {
  return guarded(import_spec(), [&] {
    const Bytes bytes = read_file(path);
    detail::ViewStream in(bytes);
    return read_tree(in, path_to_utf8(path.filename()));
  });
}

}  // namespace scad::io
