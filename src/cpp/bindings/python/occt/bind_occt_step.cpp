// Data exchange and documents: STEPControl_*, STEPCAFControl_*, IFSelect_*, Interface_Static, XSControl_*, XCAF*,
// TDF_*, TDocStd_*, TDataStd_*, TCollection_*, Quantity_*, the Step* data-model classes the SDK touches, BinTools, and
// the stream-taking BRepTools.Write_s / Read_s.  Names and call shapes follow OCP (see OCCT_BINDINGS.md).
#include <BRepTools.hxx>
#include <BRep_Builder.hxx>
#include <BinTools.hxx>
#include <BinTools_FormatVersion.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <IFSelect_WorkSession.hxx>
#include <Interface_InterfaceModel.hxx>
#include <Interface_Static.hxx>
#include <Quantity_Color.hxx>
#include <Quantity_ColorRGBA.hxx>
#include <Quantity_TypeOfColor.hxx>
#include <STEPCAFControl_Reader.hxx>
#include <STEPCAFControl_Writer.hxx>
#include <STEPControl_Reader.hxx>
#include <STEPControl_StepModelType.hxx>
#include <STEPControl_Writer.hxx>
#include <Standard_GUID.hxx>
#include <Standard_Transient.hxx>
#include <StepBasic_ProductDefinition.hxx>
#include <StepData_StepModel.hxx>
#include <StepRepr_CharacterizedDefinition.hxx>
#include <StepRepr_DescriptiveRepresentationItem.hxx>
#include <StepRepr_HArray1OfRepresentationItem.hxx>
#include <StepRepr_ProductDefinitionShape.hxx>
#include <StepRepr_PropertyDefinition.hxx>
#include <StepRepr_PropertyDefinitionRepresentation.hxx>
#include <StepRepr_Representation.hxx>
#include <StepRepr_RepresentationContext.hxx>
#include <StepRepr_RepresentationItem.hxx>
#include <StepRepr_RepresentedDefinition.hxx>
#include <StepShape_ShapeDefinitionRepresentation.hxx>
#include <TCollection_AsciiString.hxx>
#include <TCollection_ExtendedString.hxx>
#include <TCollection_HAsciiString.hxx>
#include <TCollection_HExtendedString.hxx>
#include <TDF_Attribute.hxx>
#include <TDF_Label.hxx>
#include <TDF_LabelSequence.hxx>
#include <TDataStd_Comment.hxx>
#include <TDataStd_GenericExtString.hxx>
#include <TDataStd_Name.hxx>
#include <TDocStd_Document.hxx>
#include <TopLoc_Location.hxx>
#include <TopTools_FormatVersion.hxx>
#include <TopoDS_Shape.hxx>
#include <XCAFApp_Application.hxx>
#include <XCAFDoc_ColorTool.hxx>
#include <XCAFDoc_ColorType.hxx>
#include <XCAFDoc_DocumentTool.hxx>
#include <XCAFDoc_MaterialTool.hxx>
#include <XCAFDoc_ShapeTool.hxx>
#include <XCAFPrs.hxx>
#include <XCAFPrs_DocumentExplorer.hxx>
#include <XCAFPrs_DocumentNode.hxx>
#include <XCAFPrs_IndexedDataMapOfShapeStyle.hxx>
#include <XCAFPrs_Style.hxx>
#include <XSControl_Reader.hxx>
#include <XSControl_WorkSession.hxx>

#include <cstdint>
#include <sstream>
#include <string>

#include "occt.hpp"

namespace scad::pybind::occt {

namespace {

template <class T>
using H = opencascade::handle<T>;

// ---- Python file objects as C++ streams -----------------------------------------------------------------------
// OCP hands a Python `BytesIO` to `std::istream&` / `std::ostream&`; here the stream is drained / filled in one piece.
std::string drain(const py::object& stream) {
  py::object data = stream.attr("read")();
  if (py::isinstance<py::str>(data))
    throw py::type_error("a binary stream (BytesIO) is required");
  return py::bytes(data);
}

void fill(const py::object& stream, const std::string& data) {
  stream.attr("write")(py::bytes(data));
}

// `Cls.name` becomes a static method that tries the new overload first and the ones registered before it next
// (the other agent's file may already define the same name on a class created earlier).
template <class F, class... Extra>
void add_static(py::object cls, const char* name, F&& f, const Extra&... extra) {
  py::object previous = py::getattr(cls, name, py::none());
  py::cpp_function fn(std::forward<F>(f), py::name(name), py::scope(cls), py::sibling(previous), extra...);
  cls.attr(name) = py::staticmethod(fn);
}

// UTF-8 <-> TCollection_ExtendedString (16 bit code units).
TCollection_ExtendedString to_extended(const std::string& s) {
  return TCollection_ExtendedString(s.c_str(), true);
}

py::str from_extended(const TCollection_ExtendedString& s) {
  const int n = s.Length();
  if (n == 0)
    return py::str("");
  int byteorder = -1;  // little endian; flipped below on a big-endian host
  const std::uint16_t probe = 1;
  if (*reinterpret_cast<const unsigned char*>(&probe) == 0)
    byteorder = 1;
  PyObject* u = PyUnicode_DecodeUTF16(reinterpret_cast<const char*>(s.ToExtString()), static_cast<Py_ssize_t>(n) * 2,
                                      "replace", &byteorder);
  if (!u)
    throw py::error_already_set();
  return py::reinterpret_steal<py::str>(u);
}

template <class T>
bool find_attr(const TDF_Label& label, const Standard_GUID& id, H<T> out) {
  H<TDF_Attribute> found;
  if (!label.FindAttribute(id, found))
    return false;
  H<T> typed = H<T>::DownCast(found);
  if (typed.IsNull())
    return false;
  // OCP mutates the handle in place; pybind keeps the object pointer apart from the holder, so the attribute the
  // caller already holds takes over the state of the one found.
  if (!out.IsNull())
    out->Restore(typed);
  return true;
}

}  // namespace

void bind_step(py::module_& m) {
  // ---- Standard_Transient: the root of the reference-counted classes below --------------------------------------
  if (!py::detail::get_type_info(typeid(Standard_Transient))) {
    py::class_<Standard_Transient, H<Standard_Transient>>(m, "Standard_Transient");
  }

  // ---- enums ---------------------------------------------------------------------------------------------------
  py::enum_<IFSelect_ReturnStatus>(m, "IFSelect_ReturnStatus")
      .value("IFSelect_RetVoid", IFSelect_RetVoid)
      .value("IFSelect_RetDone", IFSelect_RetDone)
      .value("IFSelect_RetError", IFSelect_RetError)
      .value("IFSelect_RetFail", IFSelect_RetFail)
      .value("IFSelect_RetStop", IFSelect_RetStop)
      .export_values();
  py::enum_<STEPControl_StepModelType>(m, "STEPControl_StepModelType")
      .value("STEPControl_AsIs", STEPControl_AsIs)
      .value("STEPControl_ManifoldSolidBrep", STEPControl_ManifoldSolidBrep)
      .value("STEPControl_BrepWithVoids", STEPControl_BrepWithVoids)
      .value("STEPControl_FacetedBrep", STEPControl_FacetedBrep)
      .value("STEPControl_FacetedBrepAndBrepWithVoids", STEPControl_FacetedBrepAndBrepWithVoids)
      .value("STEPControl_ShellBasedSurfaceModel", STEPControl_ShellBasedSurfaceModel)
      .value("STEPControl_GeometricCurveSet", STEPControl_GeometricCurveSet)
      .value("STEPControl_Hybrid", STEPControl_Hybrid)
      .export_values();
  py::enum_<Quantity_TypeOfColor>(m, "Quantity_TypeOfColor")
      .value("Quantity_TOC_RGB", Quantity_TOC_RGB)
      .value("Quantity_TOC_sRGB", Quantity_TOC_sRGB)
      .value("Quantity_TOC_HLS", Quantity_TOC_HLS)
      .value("Quantity_TOC_CIELab", Quantity_TOC_CIELab)
      .value("Quantity_TOC_CIELch", Quantity_TOC_CIELch)
      .export_values();
  py::enum_<XCAFDoc_ColorType>(m, "XCAFDoc_ColorType")
      .value("XCAFDoc_ColorGen", XCAFDoc_ColorGen)
      .value("XCAFDoc_ColorSurf", XCAFDoc_ColorSurf)
      .value("XCAFDoc_ColorCurv", XCAFDoc_ColorCurv)
      .export_values();
  py::enum_<BinTools_FormatVersion>(m, "BinTools_FormatVersion")
      .value("BinTools_FormatVersion_VERSION_1", BinTools_FormatVersion_VERSION_1)
      .value("BinTools_FormatVersion_VERSION_2", BinTools_FormatVersion_VERSION_2)
      .value("BinTools_FormatVersion_VERSION_3", BinTools_FormatVersion_VERSION_3)
      .value("BinTools_FormatVersion_VERSION_4", BinTools_FormatVersion_VERSION_4)
      .export_values();
  m.attr("BinTools_FormatVersion_CURRENT") = m.attr("BinTools_FormatVersion_VERSION_4");
  m.attr("BinTools_FormatVersion_LOWER") = m.attr("BinTools_FormatVersion_VERSION_1");
  m.attr("BinTools_FormatVersion_UPPER") = m.attr("BinTools_FormatVersion_VERSION_4");
  // XCAFPrs_DocumentExplorerFlags: OCP takes plain ints.
  m.attr("XCAFPrs_DocumentExplorerFlags_None") = py::int_(static_cast<int>(XCAFPrs_DocumentExplorerFlags_None));
  m.attr("XCAFPrs_DocumentExplorerFlags_OnlyLeafNodes") =
      py::int_(static_cast<int>(XCAFPrs_DocumentExplorerFlags_OnlyLeafNodes));
  m.attr("XCAFPrs_DocumentExplorerFlags_NoStyle") = py::int_(static_cast<int>(XCAFPrs_DocumentExplorerFlags_NoStyle));

  // ---- TCollection ---------------------------------------------------------------------------------------------
  py::class_<TCollection_AsciiString>(m, "TCollection_AsciiString")
      .def(py::init<>())
      .def(py::init([](const std::string& s) { return TCollection_AsciiString(s.c_str()); }))
      .def("ToCString", [](const TCollection_AsciiString& s) { return std::string(s.ToCString()); })
      .def("Length", &TCollection_AsciiString::Length)
      .def("IsEmpty", &TCollection_AsciiString::IsEmpty)
      .def("__str__", [](const TCollection_AsciiString& s) { return std::string(s.ToCString()); })
      .def(
          "__eq__", [](const TCollection_AsciiString& a, const TCollection_AsciiString& b) { return a.IsEqual(b); },
          py::is_operator())
      .def("__hash__", [](const TCollection_AsciiString& s) { return std::hash<TCollection_AsciiString>{}(s); });

  py::class_<TCollection_ExtendedString>(m, "TCollection_ExtendedString")
      .def(py::init<>())
      .def(py::init([](const std::string& s) { return to_extended(s); }))
      .def("ToExtString", [](const TCollection_ExtendedString& s) { return from_extended(s); })
      .def("Length", &TCollection_ExtendedString::Length)
      .def("IsEmpty", &TCollection_ExtendedString::IsEmpty)
      .def("__str__", [](const TCollection_ExtendedString& s) { return from_extended(s); })
      .def(
          "__eq__",
          [](const TCollection_ExtendedString& a, const TCollection_ExtendedString& b) { return a.IsEqual(b); },
          py::is_operator());

  py::class_<TCollection_HAsciiString, H<TCollection_HAsciiString>, Standard_Transient>(m, "TCollection_HAsciiString")
      .def(py::init([]() { return new TCollection_HAsciiString(); }))
      .def(py::init([](const std::string& s) { return new TCollection_HAsciiString(s.c_str()); }))
      .def("ToCString", [](const TCollection_HAsciiString& s) { return std::string(s.ToCString()); })
      .def("Length", &TCollection_HAsciiString::Length)
      .def("IsEmpty", &TCollection_HAsciiString::IsEmpty)
      .def("String", [](const TCollection_HAsciiString& s) { return s.String(); });

  py::class_<TCollection_HExtendedString, H<TCollection_HExtendedString>, Standard_Transient>(
      m, "TCollection_HExtendedString")
      .def(py::init([]() { return new TCollection_HExtendedString(); }))
      .def(py::init([](const std::string& s) { return new TCollection_HExtendedString(to_extended(s)); }))
      .def("ToExtString", [](const TCollection_HExtendedString& s) { return from_extended(s.String()); })
      .def("Length", &TCollection_HExtendedString::Length)
      .def("IsEmpty", &TCollection_HExtendedString::IsEmpty)
      .def("String", [](const TCollection_HExtendedString& s) { return s.String(); });

  // ---- Quantity ------------------------------------------------------------------------------------------------
  py::class_<Quantity_Color>(m, "Quantity_Color")
      .def(py::init<>())
      .def(py::init<double, double, double, Quantity_TypeOfColor>(), py::arg("theC1"), py::arg("theC2"),
           py::arg("theC3"), py::arg("theType"))
      .def("Red", &Quantity_Color::Red)
      .def("Green", &Quantity_Color::Green)
      .def("Blue", &Quantity_Color::Blue)
      .def("Hue", &Quantity_Color::Hue)
      .def("Light", &Quantity_Color::Light)
      .def("IsDifferent", &Quantity_Color::IsDifferent)
      .def("IsEqual", &Quantity_Color::IsEqual)
      .def(
          "SetValues",
          [](Quantity_Color& c, double a, double b, double d, Quantity_TypeOfColor t) { c.SetValues(a, b, d, t); },
          py::arg("theC1"), py::arg("theC2"), py::arg("theC3"), py::arg("theType"))
      .def(
          "Values",
          [](const Quantity_Color& c, Quantity_TypeOfColor type) {
            double a, b, d;
            c.Values(a, b, d, type);
            return py::make_tuple(a, b, d);
          },
          py::arg("theType"))
      .def("__eq__", [](const Quantity_Color& a, const Quantity_Color& b) { return a.IsEqual(b); }, py::is_operator());

  py::class_<Quantity_ColorRGBA>(m, "Quantity_ColorRGBA")
      .def(py::init<>())
      .def(py::init<const Quantity_Color&>())
      .def(py::init<const Quantity_Color&, float>())
      .def(py::init<float, float, float, float>())
      .def("GetRGB", [](const Quantity_ColorRGBA& c) { return c.GetRGB(); })
      .def("SetRGB", [](Quantity_ColorRGBA& c, const Quantity_Color& v) { c.SetRGB(v); })
      .def("Alpha", &Quantity_ColorRGBA::Alpha)
      .def("SetAlpha", &Quantity_ColorRGBA::SetAlpha)
      .def("IsEqual", &Quantity_ColorRGBA::IsEqual)
      .def(
          "__eq__", [](const Quantity_ColorRGBA& a, const Quantity_ColorRGBA& b) { return a.IsEqual(b); },
          py::is_operator());

  // ---- Standard_GUID, TDF, TDataStd, TDocStd -------------------------------------------------------------------
  py::class_<Standard_GUID>(m, "Standard_GUID")
      .def(py::init<>())
      .def(py::init([](const std::string& s) { return Standard_GUID(s.c_str()); }))
      .def("ToCString",
           [](const Standard_GUID& g) {
             Standard_Character buf[Standard_GUID_SIZE_ALLOC];
             g.ToCString(buf);
             return std::string(buf);
           })
      .def("__str__",
           [](const Standard_GUID& g) {
             Standard_Character buf[Standard_GUID_SIZE_ALLOC];
             g.ToCString(buf);
             return std::string(buf);
           })
      .def("IsSame", &Standard_GUID::IsSame)
      .def(
          "__eq__", [](const Standard_GUID& a, const Standard_GUID& b) { return a == b; }, py::is_operator())
      .def("__hash__", [](const Standard_GUID& g) {
        Standard_Character buf[Standard_GUID_SIZE_ALLOC];
        g.ToCString(buf);
        return std::hash<std::string>{}(std::string(buf));
      });

  py::class_<TDF_Attribute, H<TDF_Attribute>, Standard_Transient>(m, "TDF_Attribute")
      .def("ID", [](const TDF_Attribute& a) { return a.ID(); })
      .def("Label", [](const TDF_Attribute& a) { return a.Label(); })
      .def("IsValid", &TDF_Attribute::IsValid);

  py::class_<TDF_Label>(m, "TDF_Label")
      .def(py::init<>())
      .def("IsNull", &TDF_Label::IsNull)
      .def("IsRoot", &TDF_Label::IsRoot)
      .def("Tag", &TDF_Label::Tag)
      .def("Depth", &TDF_Label::Depth)
      .def("HasAttribute", &TDF_Label::HasAttribute)
      .def("NbAttributes", &TDF_Label::NbAttributes)
      .def("HasChild", &TDF_Label::HasChild)
      .def("NbChildren", &TDF_Label::NbChildren)
      .def("Father", &TDF_Label::Father)
      .def("IsEqual", &TDF_Label::IsEqual)
      .def("IsDifferent", &TDF_Label::IsDifferent)
      .def("FindChild", &TDF_Label::FindChild, py::arg("aTag"), py::arg("create") = true)
      .def("FindAttribute", &find_attr<TDataStd_Name>, py::arg("anID"), py::arg("anAttribute"))
      .def("FindAttribute", &find_attr<TDataStd_Comment>, py::arg("anID"), py::arg("anAttribute"))
      .def(
          "__eq__", [](const TDF_Label& a, const TDF_Label& b) { return a.IsEqual(b); }, py::is_operator())
      .def("__hash__", [](const TDF_Label& l) { return std::hash<TDF_Label>{}(l); });

  py::class_<TDF_LabelSequence>(m, "TDF_LabelSequence")
      .def(py::init<>())
      .def("Length", &TDF_LabelSequence::Length)
      .def("Size", &TDF_LabelSequence::Size)
      .def("IsEmpty", &TDF_LabelSequence::IsEmpty)
      .def("Clear", [](TDF_LabelSequence& s) { s.Clear(); })
      .def("Append", [](TDF_LabelSequence& s, const TDF_Label& l) { s.Append(l); })
      .def("Prepend", [](TDF_LabelSequence& s, const TDF_Label& l) { s.Prepend(l); })
      .def("Value",
           [](const TDF_LabelSequence& s, int i) {
             if (i < 1 || i > s.Length())
               throw std::out_of_range("TDF_LabelSequence::Value");
             return s.Value(i);
           })
      .def("First", [](const TDF_LabelSequence& s) { return s.First(); })
      .def("Last", [](const TDF_LabelSequence& s) { return s.Last(); })
      .def("__len__", &TDF_LabelSequence::Length);

  py::class_<TDataStd_GenericExtString, H<TDataStd_GenericExtString>, TDF_Attribute>(m, "TDataStd_GenericExtString")
      .def("Get", [](const TDataStd_GenericExtString& a) { return a.Get(); })
      .def("SetID", [](TDataStd_GenericExtString& a, const Standard_GUID& id) { a.SetID(id); });

  py::class_<TDataStd_Name, H<TDataStd_Name>, TDataStd_GenericExtString>(m, "TDataStd_Name")
      .def(py::init([]() { return new TDataStd_Name(); }))
      .def_static("GetID_s", []() { return TDataStd_Name::GetID(); })
      .def_static("Set_s",
                  [](const TDF_Label& l, const TCollection_ExtendedString& s) { return TDataStd_Name::Set(l, s); })
      .def_static("Set_s", [](const TDF_Label& l, const Standard_GUID& g, const TCollection_ExtendedString& s) {
        return TDataStd_Name::Set(l, g, s);
      });

  py::class_<TDataStd_Comment, H<TDataStd_Comment>, TDataStd_GenericExtString>(m, "TDataStd_Comment")
      .def(py::init([]() { return new TDataStd_Comment(); }))
      .def_static("GetID_s", []() { return TDataStd_Comment::GetID(); })
      .def_static("Set_s",
                  [](const TDF_Label& l, const TCollection_ExtendedString& s) { return TDataStd_Comment::Set(l, s); });
  ;

  py::class_<TDocStd_Document, H<TDocStd_Document>, Standard_Transient>(m, "TDocStd_Document")
      .def(py::init([](const TCollection_ExtendedString& format) { return new TDocStd_Document(format); }))
      .def("Main", [](const TDocStd_Document& d) { return d.Main(); })
      .def("IsEmpty", &TDocStd_Document::IsEmpty)
      .def("IsValid", &TDocStd_Document::IsValid);

  // ---- XCAF ----------------------------------------------------------------------------------------------------
  py::class_<XCAFApp_Application, H<XCAFApp_Application>, Standard_Transient>(m, "XCAFApp_Application")
      .def_static("GetApplication_s", []() { return XCAFApp_Application::GetApplication(); })
      .def("InitDocument", [](const XCAFApp_Application& a, const H<TDocStd_Document>& d) { a.InitDocument(d); })
      // OCP: NewDocument(format, doc) fills `doc`'s handle; a pybind object cannot change its pointer, so the new
      // document is returned instead (the one-argument form).
      .def("NewDocument", [](XCAFApp_Application& a, const TCollection_ExtendedString& format) {
        H<TDocStd_Document> doc;
        a.NewDocument(format, doc);
        return doc;
      });

  py::class_<XCAFDoc_ShapeTool, H<XCAFDoc_ShapeTool>, TDF_Attribute>(m, "XCAFDoc_ShapeTool")
      .def("AddShape", &XCAFDoc_ShapeTool::AddShape, py::arg("S"), py::arg("makeAssembly") = true,
           py::arg("makePrototype") = true)
      .def("GetFreeShapes", [](const XCAFDoc_ShapeTool& t, TDF_LabelSequence& out) { t.GetFreeShapes(out); })
      .def("GetShapes", [](const XCAFDoc_ShapeTool& t, TDF_LabelSequence& out) { t.GetShapes(out); })
      .def("GetOneShape", [](const XCAFDoc_ShapeTool& t) { return t.GetOneShape(); })
      .def_static("GetShape_s", [](const TDF_Label& l) { return XCAFDoc_ShapeTool::GetShape(l); })
      .def_static("GetShape_s", [](const TDF_Label& l, TopoDS_Shape& s) { return XCAFDoc_ShapeTool::GetShape(l, s); })
      .def("AddComponent", [](XCAFDoc_ShapeTool& t, const TDF_Label& assembly, const TDF_Label& comp,
                              const TopLoc_Location& loc) { return t.AddComponent(assembly, comp, loc); })
      .def(
          "AddComponent",
          [](XCAFDoc_ShapeTool& t, const TDF_Label& assembly, const TopoDS_Shape& comp, bool expand) {
            return t.AddComponent(assembly, comp, expand);
          },
          py::arg("assembly"), py::arg("comp"), py::arg("expand") = false)
      .def("UpdateAssemblies", &XCAFDoc_ShapeTool::UpdateAssemblies)
      .def("ComputeShapes", &XCAFDoc_ShapeTool::ComputeShapes)
      .def_static("IsFree_s", [](const TDF_Label& l) { return XCAFDoc_ShapeTool::IsFree(l); })
      .def_static("IsAssembly_s", [](const TDF_Label& l) { return XCAFDoc_ShapeTool::IsAssembly(l); })
      .def_static("IsComponent_s", [](const TDF_Label& l) { return XCAFDoc_ShapeTool::IsComponent(l); })
      .def_static("IsSimpleShape_s", [](const TDF_Label& l) { return XCAFDoc_ShapeTool::IsSimpleShape(l); })
      .def_static("IsReference_s", [](const TDF_Label& l) { return XCAFDoc_ShapeTool::IsReference(l); })
      .def_static("IsShape_s", [](const TDF_Label& l) { return XCAFDoc_ShapeTool::IsShape(l); })
      .def("IsTopLevel", [](const XCAFDoc_ShapeTool& t, const TDF_Label& l) { return t.IsTopLevel(l); });

  py::class_<XCAFDoc_ColorTool, H<XCAFDoc_ColorTool>, TDF_Attribute>(m, "XCAFDoc_ColorTool")
      .def("SetColor", [](XCAFDoc_ColorTool& t, const TDF_Label& l, const Quantity_Color& c,
                          XCAFDoc_ColorType type) { t.SetColor(l, c, type); })
      .def("SetColor", [](XCAFDoc_ColorTool& t, const TDF_Label& l, const Quantity_ColorRGBA& c,
                          XCAFDoc_ColorType type) { t.SetColor(l, c, type); })
      .def("SetColor", [](XCAFDoc_ColorTool& t, const TDF_Label& l, const TDF_Label& color,
                          XCAFDoc_ColorType type) { t.SetColor(l, color, type); })
      .def("SetColor", [](XCAFDoc_ColorTool& t, const TopoDS_Shape& s, const Quantity_Color& c,
                          XCAFDoc_ColorType type) { return t.SetColor(s, c, type); })
      .def("SetColor", [](XCAFDoc_ColorTool& t, const TopoDS_Shape& s, const Quantity_ColorRGBA& c,
                          XCAFDoc_ColorType type) { return t.SetColor(s, c, type); })
      .def_static("GetColor_s", [](const TDF_Label& l, Quantity_Color& c) { return XCAFDoc_ColorTool::GetColor(l, c); })
      .def_static("GetColor_s",
                  [](const TDF_Label& l, Quantity_ColorRGBA& c) { return XCAFDoc_ColorTool::GetColor(l, c); })
      .def_static("GetColor_s", [](const TDF_Label& l, XCAFDoc_ColorType type,
                                   Quantity_Color& c) { return XCAFDoc_ColorTool::GetColor(l, type, c); })
      .def_static("GetColor_s", [](const TDF_Label& l, XCAFDoc_ColorType type,
                                   Quantity_ColorRGBA& c) { return XCAFDoc_ColorTool::GetColor(l, type, c); })
      .def("GetColor", [](XCAFDoc_ColorTool& t, const TopoDS_Shape& s, XCAFDoc_ColorType type,
                          Quantity_Color& c) { return t.GetColor(s, type, c); })
      .def("GetColor", [](XCAFDoc_ColorTool& t, const TopoDS_Shape& s, XCAFDoc_ColorType type,
                          Quantity_ColorRGBA& c) { return t.GetColor(s, type, c); })
      .def("IsSet", [](XCAFDoc_ColorTool& t, const TDF_Label& l, XCAFDoc_ColorType type) { return t.IsSet(l, type); })
      .def("AddColor", [](XCAFDoc_ColorTool& t, const Quantity_Color& c) { return t.AddColor(c); })
      .def("AddColor", [](XCAFDoc_ColorTool& t, const Quantity_ColorRGBA& c) { return t.AddColor(c); });

  py::class_<XCAFDoc_MaterialTool, H<XCAFDoc_MaterialTool>, TDF_Attribute>(m, "XCAFDoc_MaterialTool")
      .def("AddMaterial",
           [](XCAFDoc_MaterialTool& t, const H<TCollection_HAsciiString>& name, const H<TCollection_HAsciiString>& desc,
              double density, const H<TCollection_HAsciiString>& dname,
              const H<TCollection_HAsciiString>& dvt) { return t.AddMaterial(name, desc, density, dname, dvt); })
      .def("SetMaterial",
           [](XCAFDoc_MaterialTool& t, const TDF_Label& l, const TDF_Label& mat) { t.SetMaterial(l, mat); })
      .def("SetMaterial",
           [](XCAFDoc_MaterialTool& t, const TDF_Label& l, const H<TCollection_HAsciiString>& name,
              const H<TCollection_HAsciiString>& desc, double density, const H<TCollection_HAsciiString>& dname,
              const H<TCollection_HAsciiString>& dvt) { t.SetMaterial(l, name, desc, density, dname, dvt); });

  py::class_<XCAFDoc_DocumentTool>(m, "XCAFDoc_DocumentTool")
      .def_static("ShapeTool_s", [](const TDF_Label& l) { return XCAFDoc_DocumentTool::ShapeTool(l); })
      .def_static("ColorTool_s", [](const TDF_Label& l) { return XCAFDoc_DocumentTool::ColorTool(l); })
      .def_static("MaterialTool_s", [](const TDF_Label& l) { return XCAFDoc_DocumentTool::MaterialTool(l); });

  py::class_<XCAFPrs_Style>(m, "XCAFPrs_Style")
      .def(py::init<>())
      .def("IsEmpty", &XCAFPrs_Style::IsEmpty)
      .def("IsVisible", &XCAFPrs_Style::IsVisible)
      .def("SetVisibility", &XCAFPrs_Style::SetVisibility)
      .def("IsSetColorSurf", &XCAFPrs_Style::IsSetColorSurf)
      .def("GetColorSurf", [](const XCAFPrs_Style& s) { return s.GetColorSurf(); })
      .def("GetColorSurfRGBA", [](const XCAFPrs_Style& s) { return s.GetColorSurfRGBA(); })
      .def("SetColorSurf", [](XCAFPrs_Style& s, const Quantity_Color& c) { s.SetColorSurf(c); })
      .def("SetColorSurf", [](XCAFPrs_Style& s, const Quantity_ColorRGBA& c) { s.SetColorSurf(c); })
      .def("UnSetColorSurf", &XCAFPrs_Style::UnSetColorSurf)
      .def("IsSetColorCurv", &XCAFPrs_Style::IsSetColorCurv)
      .def("GetColorCurv", [](const XCAFPrs_Style& s) { return s.GetColorCurv(); })
      .def("SetColorCurv", &XCAFPrs_Style::SetColorCurv)
      .def("UnSetColorCurv", &XCAFPrs_Style::UnSetColorCurv)
      .def("IsEqual", &XCAFPrs_Style::IsEqual)
      .def("__eq__", [](const XCAFPrs_Style& a, const XCAFPrs_Style& b) { return a.IsEqual(b); }, py::is_operator());

  py::class_<XCAFPrs_IndexedDataMapOfShapeStyle>(m, "XCAFPrs_IndexedDataMapOfShapeStyle")
      .def(py::init<>())
      .def("Extent", &XCAFPrs_IndexedDataMapOfShapeStyle::Extent)
      .def("Size", &XCAFPrs_IndexedDataMapOfShapeStyle::Size)
      .def("IsEmpty", &XCAFPrs_IndexedDataMapOfShapeStyle::IsEmpty)
      .def("Clear", [](XCAFPrs_IndexedDataMapOfShapeStyle& d) { d.Clear(); })
      .def("Add", [](XCAFPrs_IndexedDataMapOfShapeStyle& d, const TopoDS_Shape& k,
                     const XCAFPrs_Style& v) { return d.Add(k, v); })
      .def("Contains", [](const XCAFPrs_IndexedDataMapOfShapeStyle& d, const TopoDS_Shape& k) { return d.Contains(k); })
      .def("FindIndex",
           [](const XCAFPrs_IndexedDataMapOfShapeStyle& d, const TopoDS_Shape& k) { return d.FindIndex(k); })
      .def("FindKey",
           [](const XCAFPrs_IndexedDataMapOfShapeStyle& d, int i) {
             if (i < 1 || i > d.Extent())
               throw std::out_of_range("XCAFPrs_IndexedDataMapOfShapeStyle::FindKey");
             return shape_to_python(d.FindKey(i));
           })
      .def("FindFromIndex",
           [](const XCAFPrs_IndexedDataMapOfShapeStyle& d, int i) {
             if (i < 1 || i > d.Extent())
               throw std::out_of_range("XCAFPrs_IndexedDataMapOfShapeStyle::FindFromIndex");
             return d.FindFromIndex(i);
           })
      .def("FindFromKey", [](const XCAFPrs_IndexedDataMapOfShapeStyle& d, const TopoDS_Shape& k) {
        if (!d.Contains(k))
          throw std::out_of_range("XCAFPrs_IndexedDataMapOfShapeStyle::FindFromKey");
        return d.FindFromKey(k);
      });

  py::class_<XCAFPrs_DocumentNode>(m, "XCAFPrs_DocumentNode")
      .def(py::init<>())
      .def_readonly("Id", &XCAFPrs_DocumentNode::Id)
      .def_readonly("Label", &XCAFPrs_DocumentNode::Label)
      .def_readonly("RefLabel", &XCAFPrs_DocumentNode::RefLabel)
      .def_readonly("Style", &XCAFPrs_DocumentNode::Style)
      .def_readonly("Location", &XCAFPrs_DocumentNode::Location)
      .def_readonly("LocalTrsf", &XCAFPrs_DocumentNode::LocalTrsf)
      .def_readonly("IsAssembly", &XCAFPrs_DocumentNode::IsAssembly);

  py::class_<XCAFPrs_DocumentExplorer>(m, "XCAFPrs_DocumentExplorer")
      .def(py::init<>())
      .def(py::init([](const H<TDocStd_Document>& d, int flags, const XCAFPrs_Style& style) {
             return new XCAFPrs_DocumentExplorer(d, static_cast<XCAFPrs_DocumentExplorerFlags>(flags), style);
           }),
           py::arg("theDocument"), py::arg("theFlags"), py::arg("theDefStyle") = XCAFPrs_Style())
      .def(py::init([](const H<TDocStd_Document>& d, const TDF_LabelSequence& roots, int flags,
                       const XCAFPrs_Style& style) {
             return new XCAFPrs_DocumentExplorer(d, roots, static_cast<XCAFPrs_DocumentExplorerFlags>(flags), style);
           }),
           py::arg("theDocument"), py::arg("theRoots"), py::arg("theFlags"), py::arg("theDefStyle") = XCAFPrs_Style())
      .def(
          "Init",
          [](XCAFPrs_DocumentExplorer& e, const H<TDocStd_Document>& d, const TDF_LabelSequence& roots, int flags,
             const XCAFPrs_Style& style) {
            e.Init(d, roots, static_cast<XCAFPrs_DocumentExplorerFlags>(flags), style);
          },
          py::arg("theDocument"), py::arg("theRoots"), py::arg("theFlags"), py::arg("theDefStyle") = XCAFPrs_Style())
      .def(
          "Init",
          [](XCAFPrs_DocumentExplorer& e, const H<TDocStd_Document>& d, const TDF_Label& root, int flags,
             const XCAFPrs_Style& style) { e.Init(d, root, static_cast<XCAFPrs_DocumentExplorerFlags>(flags), style); },
          py::arg("theDocument"), py::arg("theRoot"), py::arg("theFlags"), py::arg("theDefStyle") = XCAFPrs_Style())
      .def("More", &XCAFPrs_DocumentExplorer::More)
      .def("Next", &XCAFPrs_DocumentExplorer::Next)
      .def("CurrentDepth", &XCAFPrs_DocumentExplorer::CurrentDepth)
      .def("Current", [](const XCAFPrs_DocumentExplorer& e) { return e.Current(); })
      .def(
          "Current", [](const XCAFPrs_DocumentExplorer& e, int depth) { return e.Current(depth); }, py::arg("theDepth"))
      .def_static("DefineChildId_s",
                  [](const TDF_Label& l, const TCollection_AsciiString& parent) {
                    return XCAFPrs_DocumentExplorer::DefineChildId(l, parent);
                  })
      .def_static("FindShapeFromPathId_s", [](const H<TDocStd_Document>& d, const TCollection_AsciiString& path) {
        return XCAFPrs_DocumentExplorer::FindShapeFromPathId(d, path);
      });

  py::class_<XCAFPrs>(m, "XCAFPrs")
      .def_static("CollectStyleSettings_s",
                  [](const TDF_Label& l, const TopLoc_Location& loc, XCAFPrs_IndexedDataMapOfShapeStyle& settings) {
                    XCAFPrs::CollectStyleSettings(l, loc, settings);
                  });

  // ---- IFSelect / XSControl / Interface_Static -----------------------------------------------------------------
  py::class_<Interface_InterfaceModel, H<Interface_InterfaceModel>, Standard_Transient>(m, "Interface_InterfaceModel")
      .def("NbEntities", &Interface_InterfaceModel::NbEntities)
      .def("Entity",
           [](const Interface_InterfaceModel& mo, int i) {
             if (i < 1 || i > mo.NbEntities())
               throw std::out_of_range("Interface_InterfaceModel::Entity");
             return mo.Value(i);
           })
      .def("AddEntity", [](Interface_InterfaceModel& mo, const H<Standard_Transient>& e) { mo.AddEntity(e); })
      .def(
          "AddWithRefs",
          [](Interface_InterfaceModel& mo, const H<Standard_Transient>& e, int level, bool listall) {
            mo.AddWithRefs(e, level, listall);
          },
          py::arg("anent"), py::arg("level") = 0, py::arg("listall") = false)
      .def("Clear", &Interface_InterfaceModel::Clear);

  py::class_<StepData_StepModel, H<StepData_StepModel>, Interface_InterfaceModel>(m, "StepData_StepModel");

  py::class_<IFSelect_WorkSession, H<IFSelect_WorkSession>, Standard_Transient>(m, "IFSelect_WorkSession")
      .def("Model", [](const IFSelect_WorkSession& w) { return w.Model(); })
      .def("HasModel", [](const IFSelect_WorkSession& w) { return !w.Model().IsNull(); });
  py::class_<XSControl_WorkSession, H<XSControl_WorkSession>, IFSelect_WorkSession>(m, "XSControl_WorkSession");

  py::class_<Interface_Static>(m, "Interface_Static")
      .def_static("CVal_s", [](const char* name) { return Interface_Static::CVal(name); })
      .def_static("SetCVal_s", [](const char* name, const char* v) { return Interface_Static::SetCVal(name, v); })
      .def_static("IVal_s", [](const char* name) { return Interface_Static::IVal(name); })
      .def_static("SetIVal_s", [](const char* name, int v) { return Interface_Static::SetIVal(name, v); })
      .def_static("RVal_s", [](const char* name) { return Interface_Static::RVal(name); })
      .def_static("SetRVal_s", [](const char* name, double v) { return Interface_Static::SetRVal(name, v); })
      .def_static("IsPresent_s", [](const char* name) { return Interface_Static::IsPresent(name); })
      .def_static(
          "IsSet_s", [](const char* name, bool proper) { return Interface_Static::IsSet(name, proper); },
          py::arg("name"), py::arg("proper") = false)
      .def_static("Init_s", [](const char* family, const char* name, char type, const char* init) {
        return Interface_Static::Init(family, name, type, init);
      });

  // ---- STEP readers / writers ----------------------------------------------------------------------------------
  py::class_<XSControl_Reader>(m, "XSControl_Reader")
      .def("ReadFile", [](XSControl_Reader& r, const char* f) { return r.ReadFile(f); })
      .def("NbRootsForTransfer", [](XSControl_Reader& r) { return r.NbRootsForTransfer(); })
      .def(
          "TransferOneRoot", [](XSControl_Reader& r, int n) { return r.TransferOneRoot(n); }, py::arg("num") = 1)
      .def("TransferOne", [](XSControl_Reader& r, int n) { return r.TransferOne(n); })
      .def("TransferRoots", [](XSControl_Reader& r) { return r.TransferRoots(); })
      .def("NbShapes", &XSControl_Reader::NbShapes)
      .def(
          "Shape", [](XSControl_Reader& r, int n) { return r.Shape(n); }, py::arg("num") = 1)
      .def("OneShape", [](XSControl_Reader& r) { return r.OneShape(); })
      .def("ClearShapes", &XSControl_Reader::ClearShapes)
      .def("WS", [](const XSControl_Reader& r) { return r.WS(); })
      .def("Model", [](const XSControl_Reader& r) { return r.Model(); });

  py::class_<STEPControl_Reader, XSControl_Reader>(m, "STEPControl_Reader")
      .def(py::init<>())
      .def("ReadStream",
           [](STEPControl_Reader& r, const std::string& name, const py::object& stream) {
             std::istringstream in(drain(stream), std::ios::in | std::ios::binary);
             return r.ReadStream(name.c_str(), in);
           })
      .def("StepModel", [](const STEPControl_Reader& r) { return r.StepModel(); });

  py::class_<STEPControl_Writer>(m, "STEPControl_Writer")
      .def(py::init<>())
      .def(
          "Transfer",
          [](STEPControl_Writer& w, const TopoDS_Shape& s, STEPControl_StepModelType mode, bool compgraph) {
            return w.Transfer(s, mode, compgraph);
          },
          py::arg("sh"), py::arg("mode"), py::arg("compgraph") = true)
      .def("Write", [](STEPControl_Writer& w, const char* f) { return w.Write(f); })
      .def("SetTolerance", &STEPControl_Writer::SetTolerance)
      .def("UnsetTolerance", &STEPControl_Writer::UnsetTolerance)
      .def("WS", [](const STEPControl_Writer& w) { return w.WS(); })
      .def("Model", [](STEPControl_Writer& w, bool newone) { return w.Model(newone); }, py::arg("newone") = false);

  py::class_<STEPCAFControl_Reader>(m, "STEPCAFControl_Reader")
      .def(py::init<>())
      .def("ReadFile", [](STEPCAFControl_Reader& r, const char* f) { return r.ReadFile(f); })
      .def("ReadStream",
           [](STEPCAFControl_Reader& r, const std::string& name, const py::object& stream) {
             std::istringstream in(drain(stream), std::ios::in | std::ios::binary);
             return r.ReadStream(name.c_str(), in);
           })
      .def("NbRootsForTransfer", [](STEPCAFControl_Reader& r) { return r.NbRootsForTransfer(); })
      .def("Transfer",
           [](STEPCAFControl_Reader& r, const H<TDocStd_Document>& d) {
             H<TDocStd_Document> doc = d;
             return r.Transfer(doc);
           })
      .def("Perform",
           [](STEPCAFControl_Reader& r, const std::string& f, const H<TDocStd_Document>& d) {
             H<TDocStd_Document> doc = d;
             return r.Perform(f.c_str(), doc);
           })
      .def(
          "ChangeReader", [](STEPCAFControl_Reader& r) -> STEPControl_Reader& { return r.ChangeReader(); },
          py::return_value_policy::reference_internal)
      .def(
          "Reader", [](const STEPCAFControl_Reader& r) -> const STEPControl_Reader& { return r.Reader(); },
          py::return_value_policy::reference_internal)
#define SCAD_MODE(NAME)                                           \
  .def("Set" #NAME "Mode", [](STEPCAFControl_Reader& r, bool v) { \
    r.Set##NAME##Mode(v);                                         \
  }).def("Get" #NAME "Mode", [](const STEPCAFControl_Reader& r) { return r.Get##NAME##Mode(); })
          SCAD_MODE(Color) SCAD_MODE(Name) SCAD_MODE(Layer) SCAD_MODE(Props) SCAD_MODE(Meta) SCAD_MODE(ProductMeta)
              SCAD_MODE(SHUO) SCAD_MODE(GDT) SCAD_MODE(Mat) SCAD_MODE(View)
#undef SCAD_MODE
      ;

  py::class_<STEPCAFControl_Writer>(m, "STEPCAFControl_Writer")
      .def(py::init<>())
      .def(
          "Transfer",
          [](STEPCAFControl_Writer& w, const H<TDocStd_Document>& d, STEPControl_StepModelType mode) {
            return w.Transfer(d, mode);
          },
          py::arg("doc"), py::arg("mode") = STEPControl_AsIs)
      .def(
          "Transfer",
          [](STEPCAFControl_Writer& w, const TDF_Label& l, STEPControl_StepModelType mode) {
            return w.Transfer(l, mode);
          },
          py::arg("L"), py::arg("mode") = STEPControl_AsIs)
      .def(
          "Transfer",
          [](STEPCAFControl_Writer& w, const TDF_LabelSequence& l, STEPControl_StepModelType mode) {
            return w.Transfer(l, mode);
          },
          py::arg("labels"), py::arg("mode") = STEPControl_AsIs)
      .def("Write", [](STEPCAFControl_Writer& w, const char* f) { return w.Write(f); })
      .def("Perform", [](STEPCAFControl_Writer& w, const H<TDocStd_Document>& d,
                         const std::string& f) { return w.Perform(d, f.c_str()); })
      .def(
          "ChangeWriter", [](STEPCAFControl_Writer& w) -> STEPControl_Writer& { return w.ChangeWriter(); },
          py::return_value_policy::reference_internal)
      .def(
          "Writer", [](const STEPCAFControl_Writer& w) -> const STEPControl_Writer& { return w.Writer(); },
          py::return_value_policy::reference_internal)
#define SCAD_MODE(NAME)                                           \
  .def("Set" #NAME "Mode", [](STEPCAFControl_Writer& w, bool v) { \
    w.Set##NAME##Mode(v);                                         \
  }).def("Get" #NAME "Mode", [](const STEPCAFControl_Writer& w) { return w.Get##NAME##Mode(); })
          SCAD_MODE(Color) SCAD_MODE(Name) SCAD_MODE(Layer) SCAD_MODE(Props) SCAD_MODE(SHUO) SCAD_MODE(DimTol)
              SCAD_MODE(Material)
#undef SCAD_MODE
      ;

  // ---- Step* data model ----------------------------------------------------------------------------------------
  py::class_<StepRepr_RepresentationContext, H<StepRepr_RepresentationContext>, Standard_Transient>(
      m, "StepRepr_RepresentationContext");

  py::class_<StepRepr_RepresentationItem, H<StepRepr_RepresentationItem>, Standard_Transient>(
      m, "StepRepr_RepresentationItem")
      .def("Name", [](const StepRepr_RepresentationItem& i) { return i.Name(); })
      .def("SetName", [](StepRepr_RepresentationItem& i, const H<TCollection_HAsciiString>& n) { i.SetName(n); });

  py::class_<StepRepr_DescriptiveRepresentationItem, H<StepRepr_DescriptiveRepresentationItem>,
             StepRepr_RepresentationItem>(m, "StepRepr_DescriptiveRepresentationItem")
      .def(py::init([]() { return new StepRepr_DescriptiveRepresentationItem(); }))
      .def("Init", [](StepRepr_DescriptiveRepresentationItem& i, const H<TCollection_HAsciiString>& name,
                      const H<TCollection_HAsciiString>& description) { i.Init(name, description); })
      .def("Description", [](const StepRepr_DescriptiveRepresentationItem& i) { return i.Description(); })
      .def("SetDescription", [](StepRepr_DescriptiveRepresentationItem& i, const H<TCollection_HAsciiString>& d) {
        i.SetDescription(d);
      });

  py::class_<StepRepr_HArray1OfRepresentationItem, H<StepRepr_HArray1OfRepresentationItem>, Standard_Transient>(
      m, "StepRepr_HArray1OfRepresentationItem")
      .def(py::init([](int lo, int up) { return new StepRepr_HArray1OfRepresentationItem(lo, up); }))
      .def("Length", [](const StepRepr_HArray1OfRepresentationItem& a) { return a.Length(); })
      .def("Lower", [](const StepRepr_HArray1OfRepresentationItem& a) { return a.Lower(); })
      .def("Upper", [](const StepRepr_HArray1OfRepresentationItem& a) { return a.Upper(); })
      .def("SetValue",
           [](StepRepr_HArray1OfRepresentationItem& a, int i, const H<StepRepr_RepresentationItem>& v) {
             if (i < a.Lower() || i > a.Upper())
               throw std::out_of_range("StepRepr_HArray1OfRepresentationItem::SetValue");
             a.SetValue(i, v);
           })
      .def("Value", [](const StepRepr_HArray1OfRepresentationItem& a, int i) {
        if (i < a.Lower() || i > a.Upper())
          throw std::out_of_range("StepRepr_HArray1OfRepresentationItem::Value");
        return a.Value(i);
      });

  py::class_<StepRepr_Representation, H<StepRepr_Representation>, Standard_Transient>(m, "StepRepr_Representation")
      .def(py::init([]() { return new StepRepr_Representation(); }))
      .def("Init", [](StepRepr_Representation& r, const H<TCollection_HAsciiString>& name,
                      const H<StepRepr_HArray1OfRepresentationItem>& items,
                      const H<StepRepr_RepresentationContext>& ctx) { r.Init(name, items, ctx); })
      .def("Name", [](const StepRepr_Representation& r) { return r.Name(); })
      .def("Items", [](const StepRepr_Representation& r) { return r.Items(); })
      .def("ContextOfItems", [](const StepRepr_Representation& r) { return r.ContextOfItems(); });

  py::class_<StepRepr_CharacterizedDefinition>(m, "StepRepr_CharacterizedDefinition")
      .def(py::init<>())
      .def("SetValue", [](StepRepr_CharacterizedDefinition& d, const H<Standard_Transient>& v) { d.SetValue(v); })
      .def("Value", [](const StepRepr_CharacterizedDefinition& d) { return d.Value(); });

  py::class_<StepRepr_RepresentedDefinition>(m, "StepRepr_RepresentedDefinition")
      .def(py::init<>())
      .def("SetValue", [](StepRepr_RepresentedDefinition& d, const H<Standard_Transient>& v) { d.SetValue(v); })
      .def("Value", [](const StepRepr_RepresentedDefinition& d) { return d.Value(); });

  py::class_<StepBasic_ProductDefinition, H<StepBasic_ProductDefinition>, Standard_Transient>(
      m, "StepBasic_ProductDefinition")
      .def(py::init([]() { return new StepBasic_ProductDefinition(); }))
      .def("Id", [](const StepBasic_ProductDefinition& p) { return p.Id(); })
      .def("Description", [](const StepBasic_ProductDefinition& p) { return p.Description(); });

  py::class_<StepRepr_PropertyDefinition, H<StepRepr_PropertyDefinition>, Standard_Transient>(
      m, "StepRepr_PropertyDefinition")
      .def(py::init([]() { return new StepRepr_PropertyDefinition(); }))
      .def("Init",
           [](StepRepr_PropertyDefinition& p, const H<TCollection_HAsciiString>& name, bool has_description,
              const H<TCollection_HAsciiString>& description, const StepRepr_CharacterizedDefinition& definition) {
             p.Init(name, has_description, description, definition);
           })
      .def("Name", [](const StepRepr_PropertyDefinition& p) { return p.Name(); })
      .def("Description", [](const StepRepr_PropertyDefinition& p) { return p.Description(); })
      .def("HasDescription", [](const StepRepr_PropertyDefinition& p) { return p.HasDescription(); })
      .def("Definition", [](const StepRepr_PropertyDefinition& p) { return p.Definition(); });

  py::class_<StepRepr_ProductDefinitionShape, H<StepRepr_ProductDefinitionShape>, StepRepr_PropertyDefinition>(
      m, "StepRepr_ProductDefinitionShape")
      .def(py::init([]() { return new StepRepr_ProductDefinitionShape(); }));

  py::class_<StepRepr_PropertyDefinitionRepresentation, H<StepRepr_PropertyDefinitionRepresentation>,
             Standard_Transient>(m, "StepRepr_PropertyDefinitionRepresentation")
      .def(py::init([]() { return new StepRepr_PropertyDefinitionRepresentation(); }))
      .def("Init", [](StepRepr_PropertyDefinitionRepresentation& p, const StepRepr_RepresentedDefinition& definition,
                      const H<StepRepr_Representation>& used) { p.Init(definition, used); })
      .def("Definition", [](const StepRepr_PropertyDefinitionRepresentation& p) { return p.Definition(); })
      .def("UsedRepresentation",
           [](const StepRepr_PropertyDefinitionRepresentation& p) { return p.UsedRepresentation(); });

  py::class_<StepShape_ShapeDefinitionRepresentation, H<StepShape_ShapeDefinitionRepresentation>,
             StepRepr_PropertyDefinitionRepresentation>(m, "StepShape_ShapeDefinitionRepresentation")
      .def(py::init([]() { return new StepShape_ShapeDefinitionRepresentation(); }));

  // ---- BinTools, and the stream-taking BRepTools statics -------------------------------------------------------
  py::class_<BinTools>(m, "BinTools")
      .def_static(
          "Write_s", [](const TopoDS_Shape& s, const std::string& file) { return BinTools::Write(s, file.c_str()); },
          py::arg("theShape"), py::arg("theFile"))
      .def_static(
          "Write_s",
          [](const TopoDS_Shape& s, const std::string& file, bool tri, bool normals, BinTools_FormatVersion v) {
            return BinTools::Write(s, file.c_str(), tri, normals, v);
          },
          py::arg("theShape"), py::arg("theFile"), py::arg("theWithTriangles"), py::arg("theWithNormals"),
          py::arg("theVersion"))
      .def_static(
          "Write_s",
          [](const TopoDS_Shape& s, const py::object& stream) {
            std::ostringstream out(std::ios::out | std::ios::binary);
            BinTools::Write(s, out);
            fill(stream, out.str());
          },
          py::arg("theShape"), py::arg("theStream"))
      .def_static(
          "Write_s",
          [](const TopoDS_Shape& s, const py::object& stream, bool tri, bool normals, BinTools_FormatVersion v) {
            std::ostringstream out(std::ios::out | std::ios::binary);
            BinTools::Write(s, out, tri, normals, v);
            fill(stream, out.str());
          },
          py::arg("theShape"), py::arg("theStream"), py::arg("theWithTriangles"), py::arg("theWithNormals"),
          py::arg("theVersion"))
      .def_static(
          "Read_s", [](TopoDS_Shape& s, const std::string& file) { return BinTools::Read(s, file.c_str()); },
          py::arg("theShape"), py::arg("theFile"))
      .def_static(
          "Read_s",
          [](TopoDS_Shape& s, const py::object& stream) {
            std::istringstream in(drain(stream), std::ios::in | std::ios::binary);
            BinTools::Read(s, in);
          },
          py::arg("theShape"), py::arg("theStream"));

  // BRepTools belongs to the geometry/query area; its stream statics live here.  Added to that class when it is
  // there, overload-chained after whatever it already defines under the same name.
  py::object brep_tools;
  if (py::hasattr(m, "BRepTools")) {
    brep_tools = m.attr("BRepTools");
  } else {
    brep_tools = py::class_<BRepTools>(m, "BRepTools");
  }
  add_static(
      brep_tools, "Write_s",
      [](const TopoDS_Shape& s, const py::object& stream) {
        std::ostringstream out(std::ios::out | std::ios::binary);
        BRepTools::Write(s, out);
        fill(stream, out.str());
      },
      py::arg("theShape"), py::arg("theStream"));
  add_static(
      brep_tools, "Write_s",
      [](const TopoDS_Shape& s, const py::object& stream, bool tri, bool normals, TopTools_FormatVersion v) {
        std::ostringstream out(std::ios::out | std::ios::binary);
        BRepTools::Write(s, out, tri, normals, v);
        fill(stream, out.str());
      },
      py::arg("theShape"), py::arg("theStream"), py::arg("theWithTriangles"), py::arg("theWithNormals"),
      py::arg("theVersion"));
  add_static(
      brep_tools, "Read_s",
      [](TopoDS_Shape& s, const py::object& stream, const BRep_Builder& b) {
        std::istringstream in(drain(stream), std::ios::in | std::ios::binary);
        BRepTools::Read(s, in, b);
      },
      py::arg("Sh"), py::arg("S"), py::arg("B"));
}

}  // namespace scad::pybind::occt
