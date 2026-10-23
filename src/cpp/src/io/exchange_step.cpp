// STEP and BREP file exchange, compounds.
#include <sstream>

#include <BRepCheck_Analyzer.hxx>
#include <BRep_Builder.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <STEPControl_Reader.hxx>
#include <STEPControl_StepModelType.hxx>
#include <STEPControl_Writer.hxx>
#include <TopoDS_Compound.hxx>

#include "bytes.hpp"
#include "exchange_lock.hpp"
#include "occt_messages.hpp"
#include "scad/core/error.hpp"
#include "scad/io/exchange.hpp"

namespace scad::io {

namespace {

const char* status_name(IFSelect_ReturnStatus status) {
  switch (status) {
    case IFSelect_RetVoid: return "RetVoid (nothing to do)";
    case IFSelect_RetDone: return "RetDone";
    case IFSelect_RetError: return "RetError";
    case IFSelect_RetFail: return "RetFail";
    case IFSelect_RetStop: return "RetStop";
  }
  return "unknown";
}

const ErrorSpec& export_step_spec() {
  static const ErrorSpec spec{"export_step_shapes",
                              "Failed to export the shapes as STEP.",
                              {"The shape list is empty or contains a null shape.",
                               "OpenCASCADE could not translate the geometry to STEP entities.",
                               "The destination is not writable."},
                              {"Pass at least one valid shape.",
                               "Check the shape with a validity query before exporting.",
                               "Write to a directory that exists and is writable."}};
  return spec;
}

const ErrorSpec& import_step_spec() {
  static const ErrorSpec spec{"import_step",
                              "Failed to read the STEP file.",
                              {"The file does not exist, is not readable, or is not a STEP file.",
                               "The file holds no transferable solid, shell, or face geometry.",
                               "A single root was required but the file has several."},
                              {"Check the path and that the file is ISO 10303-21 text.",
                               "Open the file in a CAD viewer to confirm it holds geometry.",
                               "Relax require_single_root to import every root as a compound."}};
  return spec;
}

const ErrorSpec& export_brep_spec() {
  static const ErrorSpec spec{"export_brep",
                              "Failed to write the BREP file.",
                              {"The shape is null.", "The destination is not writable."},
                              {"Pass a valid shape.", "Write to a directory that exists and is writable."}};
  return spec;
}

const ErrorSpec& import_brep_spec() {
  static const ErrorSpec spec{"import_brep",
                              "Failed to read the BREP file.",
                              {"The file does not exist or is not an OpenCASCADE BREP (binary or ASCII).",
                               "The BREP is truncated, or its topology is invalid."},
                              {"Check the path and the file's origin.",
                               "Re-export the shape from its source."}};
  return spec;
}

std::string with_messages(const std::string& what, const detail::MessageCapture& messages) {
  const std::string text = messages.text();
  return text.empty() ? what : what + "\nOpenCASCADE reported:\n" + text;
}

std::string transfer_into(STEPControl_Writer& writer, const TopoDS_Shape& compound) {
  const IFSelect_ReturnStatus status = writer.Transfer(compound, STEPControl_AsIs);
  if (status != IFSelect_RetDone) return std::string("STEP transfer failed: ") + status_name(status);
  return {};
}

Bytes write_step_stream(const std::vector<TopoDS_Shape>& shapes) {
  const TopoDS_Shape compound = make_compound(shapes);
  const std::lock_guard<std::mutex> lock(detail::data_exchange_mutex());
  const detail::MessageCapture messages;
  return occt_guard([&]() -> Bytes {
    STEPControl_Writer writer;
    if (const std::string failure = transfer_into(writer, compound); !failure.empty())
      throw ValueError(with_messages(failure, messages));
    std::ostringstream out(std::ios::binary);
    const IFSelect_ReturnStatus status = writer.WriteStream(out);
    if (status != IFSelect_RetDone)
      throw ValueError(with_messages(std::string("STEP write failed: ") + status_name(status), messages));
    return std::move(out).str();
  });
}

StepReadResult read_step_stream(std::istream& in, const std::string& name, const StepReadOptions& options) {
  const std::lock_guard<std::mutex> lock(detail::data_exchange_mutex());
  const detail::MessageCapture messages;
  return occt_guard([&] {
    STEPControl_Reader reader;
    const IFSelect_ReturnStatus status = reader.ReadStream(name.c_str(), in);
    if (status != IFSelect_RetDone)
      throw ValueError(with_messages("could not read STEP file " + name + ": " + status_name(status), messages));
    StepReadResult result;
    result.transferred_roots = static_cast<int>(reader.TransferRoots());
    result.shape_count = reader.NbShapes();
    if (result.transferred_roots < 1 || result.shape_count < 1)
      throw ValueError(with_messages("STEP file " + name + " transferred no shapes", messages));
    if (options.require_single_root && (result.transferred_roots != 1 || result.shape_count != 1))
      throw ValueError("expected one STEP root in " + name + ", got transferred=" +
                       std::to_string(result.transferred_roots) + ", shapes=" + std::to_string(result.shape_count));
    result.shape = options.require_single_root ? reader.Shape(1) : reader.OneShape();
    if (result.shape.IsNull()) throw ValueError("STEP file " + name + " produced a null shape");
    if (options.require_valid && !BRepCheck_Analyzer(result.shape).IsValid())
      throw ValueError("STEP BREP is invalid: " + name);
    return result;
  });
}

}  // namespace

TopoDS_Shape make_compound_always(const std::vector<TopoDS_Shape>& shapes) {
  if (shapes.empty()) throw ValueError("No shapes to export");
  return occt_guard([&] {
    BRep_Builder builder;
    TopoDS_Compound compound;
    builder.MakeCompound(compound);
    for (const TopoDS_Shape& shape : shapes) {
      if (shape.IsNull()) throw ValueError("cannot export a null shape");
      builder.Add(compound, shape);
    }
    return TopoDS_Shape(compound);
  });
}

TopoDS_Shape make_compound(const std::vector<TopoDS_Shape>& shapes) {
  if (shapes.empty()) throw ValueError("No shapes to export");
  if (shapes.size() == 1) {
    if (shapes.front().IsNull()) throw ValueError("cannot export a null shape");
    return shapes.front();
  }
  return make_compound_always(shapes);
}

Bytes step_bytes(const std::vector<TopoDS_Shape>& shapes) {
  return guarded(export_step_spec(), [&] { return write_step_stream(shapes); });
}

void export_step_shapes(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path) {
  guarded(export_step_spec(), [&] {
    const Bytes bytes = write_step_stream(shapes);
    write_file(path, bytes);
  });
}

StepReadResult read_step_bytes(std::string_view bytes, const std::string& name, const StepReadOptions& options) {
  return guarded(import_step_spec(), [&] {
    detail::ViewStream in(bytes);
    return read_step_stream(in, name, options);
  });
}

StepReadResult read_step(const std::filesystem::path& path, const StepReadOptions& options) {
  return guarded(import_step_spec(), [&] {
    const Bytes bytes = read_file(path);
    detail::ViewStream in(bytes);
    return read_step_stream(in, path_to_utf8(path.filename()), options);
  });
}

Shape import_step(const std::filesystem::path& path, const StepReadOptions& options) {
  return guarded(import_step_spec(), [&] { return Shape::from_occt(read_step(path, options).shape); });
}

void export_brep(const Shape& shape, const std::filesystem::path& path) {
  guarded(export_brep_spec(), [&] { write_brep(path, shape.wrapped()); });
}

Shape import_brep(const std::filesystem::path& path, const BrepReadOptions& options) {
  return guarded(import_brep_spec(), [&] { return Shape::from_occt(read_brep(path, options)); });
}

}  // namespace scad::io
