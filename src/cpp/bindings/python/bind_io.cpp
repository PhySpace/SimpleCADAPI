// Python bindings for the "io" area: tessellation, import/export, BREP bytes,
// shape serialization and BREP region snapshots.
//
// Everything that takes a path accepts str / os.PathLike (pybind11's
// std::filesystem::path caster converts through the file-system encoding, wide
// characters on Windows).  Heavy work runs with the GIL released on a copy of the
// TopoDS_Shape handle -- the semantic state is only touched while the GIL is held.
#include "bindings.hpp"

#include <pybind11/stl/filesystem.h>

#include <memory>
#include <optional>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/io/brep.hpp"
#include "scad/io/brep_region.hpp"
#include "scad/io/exchange.hpp"
#include "scad/io/mesh.hpp"
#include "scad/io/serialize.hpp"
#include "scad/io/step_assembly.hpp"
#include "scad/topo/shape.hpp"

namespace {

using namespace scad;
namespace io = scad::io;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
py::object cast_shape(const Shape& shape) {
  switch (shape.kind()) {
    case Kind::Vertex: return py::cast(Vertex(shape));
    case Kind::Edge: return py::cast(Edge(shape));
    case Kind::Wire: return py::cast(Wire(shape));
    case Kind::Face: return py::cast(Face(shape));
    case Kind::Shell: return py::cast(Shell(shape));
    case Kind::Solid: return py::cast(Solid(shape));
    case Kind::Compound: return py::cast(Compound(shape));
  }
  throw RuntimeError("unknown shape kind");
}

py::bytes to_py_bytes(const io::Bytes& bytes) { return py::bytes(bytes.data(), bytes.size()); }

io::Bytes from_py_bytes(const py::bytes& bytes) {
  char* data = nullptr;
  Py_ssize_t size = 0;
  if (PYBIND11_BYTES_AS_STRING_AND_SIZE(bytes.ptr(), &data, &size) != 0) throw py::error_already_set();
  return io::Bytes(data, static_cast<std::size_t>(size));
}

// A Shape or a sequence of Shapes -> TopoDS_Shapes.
std::vector<TopoDS_Shape> shapes_from(const py::object& arg) {
  if (py::isinstance<Shape>(arg)) return {arg.cast<const Shape&>().wrapped()};
  std::vector<TopoDS_Shape> out;
  for (const py::handle item : arg) {
    if (!py::isinstance<Shape>(item))
      throw TypeError("expected a shape or a sequence of shapes, got " +
                      std::string(py::str(py::type::of(item).attr("__name__"))));
    out.push_back(item.cast<const Shape&>().wrapped());
  }
  return out;
}

// A read-only numpy view of rows x width elements of `Elem` (a 1-d array when width is 1),
// kept alive by `owner`.
template <class Elem>
py::array view(const py::object& owner, const Elem* data, std::size_t rows, std::size_t width) {
  std::vector<py::ssize_t> shape{static_cast<py::ssize_t>(rows)};
  std::vector<py::ssize_t> strides{static_cast<py::ssize_t>(width * sizeof(Elem))};
  if (width > 1) {
    shape.push_back(static_cast<py::ssize_t>(width));
    strides.push_back(static_cast<py::ssize_t>(sizeof(Elem)));
  }
  py::array array(py::dtype::of<Elem>(), shape, strides, data, owner);
  array.attr("setflags")(py::arg("write") = false);
  return array;
}

io::MeshParameters mesh_parameters(double linear, double angular, bool relative, bool parallel) {
  io::MeshParameters p;
  p.linear_deflection = linear;
  p.angular_deflection = angular;
  p.relative = relative;
  p.parallel = parallel;
  return p;
}

py::dict surface_report(const io::SurfaceExportReport& r) {
  py::dict d;
  d["output_path"] = py::str(io::path_to_utf8(r.output_path));
  d["solid_count"] = r.solid_count;
  d["vertex_count"] = r.vertex_count;
  d["triangle_count"] = r.triangle_count;
  d["linear_deflection"] = r.parameters.linear_deflection;
  d["angular_deflection_degrees"] = r.parameters.angular_deflection_degrees;
  d["relative"] = r.parameters.relative;
  d["tessellation_backend"] = "opencascade-brep-tessellation";
  return d;
}

io::SurfaceMeshParameters surface_parameters(double linear, double angular_degrees, bool relative) {
  io::SurfaceMeshParameters p;
  p.linear_deflection = linear;
  p.angular_deflection_degrees = angular_degrees;
  p.relative = relative;
  return p;
}

io::RegionRootKind root_kind(const std::string& name) {
  if (name == "solid") return io::RegionRootKind::Solid;
  if (name == "shell") return io::RegionRootKind::Shell;
  throw ValueError("root_kind must be 'solid' or 'shell'");
}

// ---------------------------------------------------------------------------
// Mesh classes
// ---------------------------------------------------------------------------
void bind_mesh(py::module_& m) {
  py::class_<io::Mesh, std::shared_ptr<io::Mesh>>(
      m, "Mesh",
      "A triangle mesh: float32 vertices (n, 3), per-vertex normals (n, 3), uint32 triangles (m, 3) and the face\n"
      "index of each triangle (m,).  The arrays are read-only views of the mesh's own memory (no copy); they keep\n"
      "the mesh alive.")
      .def_property_readonly("vertices", [](const py::object& self) {
        const auto& mesh = self.cast<const io::Mesh&>();
        return view<float>(self, mesh.vertices.data(), mesh.vertex_count(), 3);
      })
      .def_property_readonly("normals", [](const py::object& self) {
        const auto& mesh = self.cast<const io::Mesh&>();
        return view<float>(self, mesh.normals.data(), mesh.vertex_count(), 3);
      })
      .def_property_readonly("triangles", [](const py::object& self) {
        const auto& mesh = self.cast<const io::Mesh&>();
        return view<std::uint32_t>(self, mesh.triangles.data(), mesh.triangle_count(), 3);
      })
      .def_property_readonly("face_ids", [](const py::object& self) {
        const auto& mesh = self.cast<const io::Mesh&>();
        return view<std::uint32_t>(self, mesh.face_ids.data(), mesh.face_ids.size(), 1);
      })
      .def_property_readonly(
          "face_ranges",
          [](const py::object& self) {
            const auto& mesh = self.cast<const io::Mesh&>();
            static_assert(sizeof(io::FaceRange) == 3 * sizeof(std::uint32_t));
            return view<std::uint32_t>(self, reinterpret_cast<const std::uint32_t*>(mesh.face_ranges.data()),
                                       mesh.face_ranges.size(), 3);
          },
          "(face_index, first_triangle, triangle_count) for every face, in face order.")
      .def_property_readonly("vertex_count", [](const io::Mesh& mesh) { return mesh.vertex_count(); })
      .def_property_readonly("triangle_count", [](const io::Mesh& mesh) { return mesh.triangle_count(); })
      .def_property_readonly("bounds",
                             [](const io::Mesh& mesh) {
                               const auto b = mesh.bounds();
                               return py::make_tuple(py::make_tuple(b[0][0], b[0][1], b[0][2]),
                                                     py::make_tuple(b[1][0], b[1][1], b[1][2]));
                             })
      .def("__repr__", [](const io::Mesh& mesh) {
        return "Mesh(vertices=" + std::to_string(mesh.vertex_count()) +
               ", triangles=" + std::to_string(mesh.triangle_count()) + ")";
      });

  m.def(
      "mesh",
      [](const Shape& shape, double linear_deflection, double angular_deflection, bool relative, bool parallel) {
        const TopoDS_Shape wrapped = shape.wrapped();
        const io::MeshParameters parameters = mesh_parameters(linear_deflection, angular_deflection, relative, parallel);
        io::Mesh result;
        {
          py::gil_scoped_release release;
          result = io::mesh(wrapped, parameters);
        }
        return std::make_shared<io::Mesh>(std::move(result));
      },
      py::arg("shape"), py::arg("linear_deflection") = io::kDefaultLinearDeflection,
      py::arg("angular_deflection") = io::kDefaultAngularDeflection, py::kw_only(), py::arg("relative") = false,
      py::arg("parallel") = true,
      "Tessellate `shape` (copy-on-mesh: the argument is not modified) into a Mesh.\n"
      "Faces keep their own vertices, so normals stay sharp across edges; triangles wind outward.");

  // _internal.mesh: the double-precision mesh with per-corner normals.
  py::module_ internal = m.def_submodule("_internal_mesh", "simplecadapi._internal.mesh");
  internal.attr("DEFAULT_LINEAR_TOLERANCE") = io::kDefaultLinearDeflection;
  internal.attr("DEFAULT_ANGULAR_TOLERANCE") = io::kDefaultAngularDeflection;
  internal.attr("MESH_RUNTIME_KEY") = "mesh.default";
  internal.attr("MESH_ERROR_RUNTIME_KEY") = "mesh.error";

  py::class_<io::FaceTriangleRange>(internal, "FaceTriangleRange")
      .def_readonly("face_index", &io::FaceTriangleRange::face_index)
      .def_readonly("start", &io::FaceTriangleRange::start)
      .def_readonly("count", &io::FaceTriangleRange::count)
      .def_readonly("source_topo_id", &io::FaceTriangleRange::source_topo_id);

  py::class_<io::TriMesh, std::shared_ptr<io::TriMesh>>(internal, "TriMesh")
      .def_property_readonly("vertices", [](const py::object& self) {
        const auto& mesh = self.cast<const io::TriMesh&>();
        return view<double>(self, mesh.vertices.data(), mesh.vertex_count(), 3);
      })
      .def_property_readonly("triangles", [](const py::object& self) {
        const auto& mesh = self.cast<const io::TriMesh&>();
        return view<std::int64_t>(self, mesh.triangles.data(), mesh.triangle_count(), 3);
      })
      .def_property_readonly("corner_normals",
                             [](const py::object& self) {
                               const auto& mesh = self.cast<const io::TriMesh&>();
                               py::array flat = view<double>(self, mesh.corner_normals.data(), mesh.triangle_count() * 3, 3);
                               return flat.attr("reshape")(py::make_tuple(mesh.triangle_count(), 3, 3));
                             })
      .def_readonly("face_triangle_ranges", &io::TriMesh::face_triangle_ranges)
      .def_readonly("linear_tolerance", &io::TriMesh::linear_tolerance)
      .def_readonly("angular_tolerance", &io::TriMesh::angular_tolerance)
      .def_property_readonly("vertex_count", [](const io::TriMesh& mesh) { return mesh.vertex_count(); })
      .def_property_readonly("triangle_count", [](const io::TriMesh& mesh) { return mesh.triangle_count(); })
      .def_property_readonly("bounds", [](const io::TriMesh& mesh) {
        const auto b = mesh.bounds();
        return py::make_tuple(py::make_tuple(b[0].x, b[0].y, b[0].z), py::make_tuple(b[1].x, b[1].y, b[1].z));
      });

  internal.def(
      "cached_mesh",
      [](const Shape& solid, double linear_tolerance, double angular_tolerance) {
        // The mesh is shared with the cache and exposed read-only, so handing it out un-const is safe.
        return std::const_pointer_cast<io::TriMesh>(io::cached_mesh(solid, linear_tolerance, angular_tolerance));
      },
      py::arg("solid"), py::kw_only(), py::arg("linear_tolerance") = io::kDefaultLinearDeflection,
      py::arg("angular_tolerance") = io::kDefaultAngularDeflection);
  internal.def(
      "build_solid_trimesh",
      [](const Shape& solid, double linear_tolerance, double angular_tolerance) {
        return std::make_shared<io::TriMesh>(io::build_solid_trimesh(solid, linear_tolerance, angular_tolerance));
      },
      py::arg("solid"), py::kw_only(), py::arg("linear_tolerance") = io::kDefaultLinearDeflection,
      py::arg("angular_tolerance") = io::kDefaultAngularDeflection);
  internal.def(
      "mesh_error",
      [](const Shape& solid) -> py::object {
        const std::string text = io::mesh_error(solid);
        return text.empty() ? py::none() : py::object(py::str(text));
      },
      py::arg("solid"));
}

// ---------------------------------------------------------------------------
// BREP bytes, serialization, pickling
// ---------------------------------------------------------------------------
void bind_bytes(py::module_& m) {
  const std::string to_brep_doc =
      "to_brep() -> bytes\n"
      "BinTools binary, format version 4, geometry only (no triangulation): bit-exact doubles, readable by every\n"
      "OpenCASCADE >= 7.3.  Hand these bytes to OCP with BinTools.Read_s(shape, io.BytesIO(data)).";
  py::object any_shape = m.attr("AnyShape");

  any_shape.attr("to_brep") = py::cpp_function(
      [](const Shape& shape) {
        const TopoDS_Shape wrapped = shape.wrapped();
        io::Bytes bytes;
        {
          py::gil_scoped_release release;
          bytes = io::to_brep_bytes(wrapped);
        }
        return to_py_bytes(bytes);
      },
      py::name("to_brep"), py::is_method(any_shape), py::doc(to_brep_doc.c_str()));
  any_shape.attr("from_brep") = py::staticmethod(py::cpp_function(
      [](const py::bytes& data, bool require_valid) {
        const io::Bytes bytes = from_py_bytes(data);
        io::BrepReadOptions options;
        options.require_valid = require_valid;
        TopoDS_Shape shape;
        {
          py::gil_scoped_release release;
          shape = io::from_brep_bytes(bytes, options);
        }
        return cast_shape(Shape::from_occt(shape));
      },
      py::name("from_brep"), py::arg("data"), py::arg("require_valid") = false,
      py::doc("from_brep(data: bytes) -> Shape\nThe shape (Solid, Face, ...) stored in BinTools or ASCII BRep bytes.")));
  m.attr("from_brep") = any_shape.attr("from_brep");
  m.def(
      "canonical_brep_bytes",
      [](const Shape& shape) {
        const TopoDS_Shape wrapped = shape.wrapped();
        io::Bytes bytes;
        {
          py::gil_scoped_release release;
          bytes = io::canonical_brep_bytes(wrapped);
        }
        return to_py_bytes(bytes);
      },
      py::arg("shape"),
      "The deterministic BREP encoding to hash (artifacts.brep.write_brep_bytes): the smallest member of the\n"
      "encode/decode cycle.");

  m.def(
      "serialize_shape", [](const Shape& shape) { return to_py_bytes(io::serialize(shape)); }, py::arg("shape"),
      "Geometry (BinTools V4) plus the tags, bindings, lineage, metadata and runtime values of every entity, in the\n"
      "versioned 'SCADSHAP' container (docs/io.md).");
  m.def(
      "deserialize_shape", [](const py::bytes& data) { return cast_shape(io::deserialize(from_py_bytes(data))); },
      py::arg("data"), "Inverse of serialize_shape.");
  m.def(
      "clone_semantic_view", [](const Shape& shape) { return cast_shape(shape.clone_view()); }, py::arg("shape"),
      "A new root over the same geometry in which every entity carries a copy of the source entity's complete state\n"
      "(tags, bindings, lineage, metadata, graph attachments) under the same topo id.");
  m.def(
      "_from_occt", [](const TopoDS_Shape& shape) { return cast_shape(Shape::from_occt(shape)); }, py::arg("shape"),
      "A native shape for an OCCT shape (the way back from `.wrapped`).");
  // pickle / copy: reduce through the container.
  const py::object deserialize = m.attr("deserialize_shape");
  any_shape.attr("__reduce__") = py::cpp_function(
      [deserialize](const Shape& shape) {
        return py::make_tuple(deserialize, py::make_tuple(to_py_bytes(io::serialize(shape))));
      },
      py::name("__reduce__"), py::is_method(any_shape));
}


// ---------------------------------------------------------------------------
// STEP assemblies: definitions arrive as plain dicts (see exporter/step.py).
// ---------------------------------------------------------------------------
Vec3 vec3_from(const py::handle& obj) {
  const auto values = py::cast<std::vector<double>>(obj);
  if (values.size() != 3) throw ValueError("expected three numbers");
  return Vec3{values[0], values[1], values[2]};
}

io::StepPlacement placement_from(const py::dict& d) {
  io::StepPlacement p;
  p.origin = vec3_from(d["origin"]);
  p.x_axis = vec3_from(d["x_axis"]);
  p.y_axis = vec3_from(d["y_axis"]);
  p.z_axis = vec3_from(d["z_axis"]);
  return p;
}

std::vector<io::StepDefinition> definitions_from(const py::sequence& items) {
  std::vector<io::StepDefinition> out;
  for (const py::handle handle : items) {
    const py::dict d = py::reinterpret_borrow<py::dict>(handle);
    io::StepDefinition def;
    def.id = d["id"].cast<std::string>();
    if (d.contains("kind")) def.kind = d["kind"].cast<std::string>();
    def.name = d["name"].cast<std::string>();
    if (d.contains("shape") && !d["shape"].is_none()) def.shape = d["shape"].cast<const Shape&>().wrapped();
    if (d.contains("metadata")) def.metadata = pybind::value_from_python(d["metadata"]);
    if (d.contains("color") && !d["color"].is_none()) {
      const Vec3 c = vec3_from(d["color"]);
      def.color = std::array<double, 3>{c.x, c.y, c.z};
    }
    if (d.contains("material") && !d["material"].is_none()) {
      const py::dict m = d["material"].cast<py::dict>();
      io::StepMaterial material;
      material.id = m["id"].cast<std::string>();
      material.name = m["name"].cast<std::string>();
      material.description = pybind::value_from_python(m["description"]);
      if (m.contains("density") && !m["density"].is_none()) material.density = m["density"].cast<double>();
      if (m.contains("density_unit")) material.density_unit = m["density_unit"].cast<std::string>();
      def.material = std::move(material);
    }
    if (d.contains("components")) {
      for (const py::handle ch : d["components"]) {
        const py::dict c = py::reinterpret_borrow<py::dict>(ch);
        io::StepComponent component;
        component.id = c["id"].cast<std::string>();
        component.name = c["name"].cast<std::string>();
        component.definition_id = c["definition_id"].cast<std::string>();
        component.placement = placement_from(c["placement"].cast<py::dict>());
        component.metadata = pybind::value_from_python(c["metadata"]);
        def.components.push_back(std::move(component));
      }
    }
    out.push_back(std::move(def));
  }
  return out;
}

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------
void bind_files(py::module_& m) {
  m.def(
      "export_step",
      [](const py::object& shapes, const std::filesystem::path& path) {
        const auto list = shapes_from(shapes);
        py::gil_scoped_release release;
        io::export_step_shapes(list, path);
      },
      py::arg("shapes"), py::arg("path"), "Write a shape, or a list of shapes (as one compound), to a STEP file.");
  m.def(
      "step_bytes",
      [](const py::object& shapes) {
        const auto list = shapes_from(shapes);
        io::Bytes bytes;
        {
          py::gil_scoped_release release;
          bytes = io::step_bytes(list);
        }
        return to_py_bytes(bytes);
      },
      py::arg("shapes"));
  m.def(
      "import_step",
      [](const std::filesystem::path& path, bool require_single_root, bool require_valid) {
        io::StepReadOptions options;
        options.require_single_root = require_single_root;
        options.require_valid = require_valid;
        io::StepReadResult result;
        {
          py::gil_scoped_release release;
          result = io::read_step(path, options);
        }
        return cast_shape(Shape::from_occt(result.shape));
      },
      py::arg("path"), py::kw_only(), py::arg("require_single_root") = false, py::arg("require_valid") = false,
      "Read a STEP file: the single root, or a compound of every root.");

  m.def(
      "tessellate_solid",
      [](const Shape& shape, double linear_deflection, double angular_deflection_degrees, bool relative) {
        const TopoDS_Shape occ = shape.wrapped();
        const io::SurfaceMeshParameters parameters =
            surface_parameters(linear_deflection, angular_deflection_degrees, relative);
        io::WeldedMesh mesh;
        {
          py::gil_scoped_release release;
          mesh = io::tessellate_solid(occ, parameters);
        }
        const std::size_t nv = mesh.vertex_count();
        py::array_t<double> vertices({static_cast<py::ssize_t>(nv), py::ssize_t{3}});
        std::copy(mesh.vertices.begin(), mesh.vertices.end(), vertices.mutable_data());
        py::array_t<std::int32_t> triangles({static_cast<py::ssize_t>(mesh.triangles.size()), py::ssize_t{3}});
        auto* out = triangles.mutable_data();
        for (const auto& t : mesh.triangles) {
          *out++ = t[0];
          *out++ = t[1];
          *out++ = t[2];
        }
        return py::make_tuple(vertices, triangles);
      },
      py::arg("shape"), py::kw_only(), py::arg("linear_deflection") = 0.1,
      py::arg("angular_deflection_degrees") = 20.0, py::arg("relative") = false,
      "(vertices Nx3 float64, triangles Mx3 int32): the shape's surface tessellated, vertices welded.");
  m.def(
      "export_step_assembly",
      [](const py::sequence& definitions, const std::string& root_id, const std::filesystem::path& path,
         const std::string& schema, bool metadata_properties) {
        const auto defs = definitions_from(definitions);
        io::StepAssemblyOptions options;
        options.schema = schema;
        options.metadata_properties = metadata_properties;
        io::StepAssemblyReport report;
        {
          py::gil_scoped_release release;
          report = io::export_step_assembly(defs, root_id, path, options);
        }
        py::dict d;
        d["schema"] = report.schema;
        d["definition_ids"] = report.definition_ids;
        d["occurrence_count"] = report.occurrence_count;
        d["material_ids"] = report.material_ids;
        d["metadata_item_count"] = report.metadata_item_count;
        return d;
      },
      py::arg("definitions"), py::arg("root_id"), py::arg("path"), py::kw_only(), py::arg("schema") = "AP242DIS",
      py::arg("metadata_properties") = true,
      "AP242 STEP of a product structure (XCAF names, colours, materials, metadata properties).");
  m.def(
      "export_stl",
      [](const py::object& shapes, const std::filesystem::path& path, double linear_deflection,
         double angular_deflection_degrees, bool relative, bool ascii) -> py::object {
        const auto list = shapes_from(shapes);
        if (ascii) {
          const io::MeshParameters parameters = mesh_parameters(
              linear_deflection, angular_deflection_degrees * kPi / 180.0, relative, /*parallel=*/false);
          {
            py::gil_scoped_release release;
            io::export_stl_ascii(list, path, parameters);
          }
          return py::none();
        }
        io::SurfaceExportReport report;
        {
          py::gil_scoped_release release;
          report = io::export_stl(list, path, surface_parameters(linear_deflection, angular_deflection_degrees, relative));
        }
        return surface_report(report);
      },
      py::arg("shapes"), py::arg("path"), py::kw_only(), py::arg("linear_deflection") = 0.1,
      py::arg("angular_deflection_degrees") = 20.0, py::arg("relative") = false, py::arg("ascii") = false,
      "Binary STL of the solids' surface (vertices welded per solid) and a report dict; ascii=True writes\n"
      "unwelded ASCII facets (kernel export_stl_shape) and returns None.");
  m.def(
      "import_stl",
      [](const std::filesystem::path& path) {
        io::Mesh mesh;
        {
          py::gil_scoped_release release;
          mesh = io::read_stl(path);
        }
        return std::make_shared<io::Mesh>(std::move(mesh));
      },
      py::arg("path"), "Read a binary or ASCII STL as a Mesh (coincident vertices merged).");
  m.def(
      "import_stl_shape",
      [](const std::filesystem::path& path, double sewing_tolerance) {
        return cast_shape(io::import_stl_shape(path, sewing_tolerance));
      },
      py::arg("path"), py::arg("sewing_tolerance") = 1e-6,
      "Read an STL as a faceted BREP (a Solid when the triangles close up).");
  m.def(
      "export_obj",
      [](const py::object& shapes, const std::filesystem::path& path, double linear_deflection,
         double angular_deflection_degrees, bool relative) {
        const auto list = shapes_from(shapes);
        io::SurfaceExportReport report;
        {
          py::gil_scoped_release release;
          report = io::export_obj(list, path, surface_parameters(linear_deflection, angular_deflection_degrees, relative));
        }
        return surface_report(report);
      },
      py::arg("shapes"), py::arg("path"), py::kw_only(), py::arg("linear_deflection") = 0.1,
      py::arg("angular_deflection_degrees") = 20.0, py::arg("relative") = false);
  m.def(
      "export_glb",
      [](const py::object& shapes, const std::filesystem::path& path, double linear_deflection,
         double angular_deflection, bool relative) {
        const auto list = shapes_from(shapes);
        const io::MeshParameters parameters = mesh_parameters(linear_deflection, angular_deflection, relative, true);
        py::gil_scoped_release release;
        io::export_glb(list, path, parameters);
      },
      py::arg("shapes"), py::arg("path"), py::kw_only(), py::arg("linear_deflection") = 0.1,
      py::arg("angular_deflection") = 0.5, py::arg("relative") = false,
      "Write a glTF 2.0 binary (.glb): one mesh, positions + normals + triangle indices.\n"
      "Defaults are the kernel exporter's (0.1 linear, 0.5 rad angular).");
  m.def(
      "export_brep", [](const Shape& shape, const std::filesystem::path& path) { io::export_brep(shape, path); },
      py::arg("shape"), py::arg("path"), "Write BinTools V4 BREP bytes to a file.");
  m.def(
      "import_brep",
      [](const std::filesystem::path& path, bool require_valid) {
        io::BrepReadOptions options;
        options.require_valid = require_valid;
        return cast_shape(io::import_brep(path, options));
      },
      py::arg("path"), py::arg("require_valid") = false);
}

// ---------------------------------------------------------------------------
// Region snapshots
// ---------------------------------------------------------------------------
void bind_region(py::module_& m) {
  py::module_ region = m.def_submodule("_brep_region", "simplecadapi._internal.brep_region");
  region.attr("MAGIC") = py::bytes(std::string(io::kBRegionMagic));
  region.attr("MAJOR_VERSION") = io::kBRegionMajorVersion;
  region.attr("MINOR_VERSION") = io::kBRegionMinorVersion;
  region.def("default_ocp_version", &io::default_ocp_version);
  region.def("region_profile", &io::region_profile, py::arg("ocp_version"));
  region.def(
      "read_artifact",
      [](const std::filesystem::path& path, const std::string& sha256, const std::string& expected_root_kind,
         const std::optional<std::filesystem::path>& replay_root) {
        io::RegionFile file = io::read_artifact(path, sha256, root_kind(expected_root_kind), replay_root);
        return py::make_tuple(cast_shape(Shape::from_occt(file.shape)), py::cast(file.manifest), file.sha256);
      },
      py::arg("path"), py::arg("sha256"), py::kw_only(), py::arg("expected_root_kind"),
      py::arg("replay_root") = py::none(),
      "(shape, manifest, sha256) of a hash-pinned .scadbrep file.");
  region.def(
      "decode_artifact",
      [](const py::bytes& data, const std::optional<std::string>& expected_root_kind) {
        io::DecodedRegion decoded = io::decode_artifact(
            from_py_bytes(data), expected_root_kind ? std::optional(root_kind(*expected_root_kind)) : std::nullopt);
        return py::make_tuple(cast_shape(Shape::from_occt(decoded.shape)), py::cast(decoded.manifest));
      },
      py::arg("data"), py::kw_only(), py::arg("expected_root_kind") = py::none());
  region.def(
      "copy_step_region_rpath",
      [](const std::filesystem::path& path, const std::filesystem::path& output_path,
         const std::optional<std::string>& ocp_version) {
        return io::copy_step_solid_region(path, output_path, ocp_version.value_or(""));
      },
      py::arg("path"), py::arg("output_path"), py::kw_only(), py::arg("ocp_version") = py::none(),
      "Copy one STEP solid into a .scadbrep snapshot (the whole-solid form of the Python function).");
  region.def("checked_region_path", &io::checked_region_path, py::arg("path"), py::arg("for_graph"));
}

}  // namespace

void bind_io(py::module_& m) {
  bind_mesh(m);
  bind_bytes(m);
  bind_files(m);
  bind_region(m);
}
