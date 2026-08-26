import logging
import os
import re

import vtk
from vtk.util import numpy_support

import ctk
import qt
import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *


#
# Unit systems
#

# Unit systems that meshes can be read from and written to. Mass (g) and time (s) units are the
# same in all supported systems, only the length unit differs, therefore a single number - the
# length of one length unit expressed in mm - fully defines the conversion between two systems
# (see unitSystemConversionFactor).
UNIT_SYSTEMS = {
    "cgs": {"name": "CGS (cm-g-s)", "lengthUnitInMm": 10.0},
    "mmgs": {"name": "mm-g-s", "lengthUnitInMm": 1.0},
}

# Unit system that models are stored in in the scene. Slicer works in mm, therefore imported
# meshes are always converted to this system.
SCENE_UNIT_SYSTEM = "mmgs"

# Coordinate system that models are stored in in the scene.
SCENE_COORDINATE_SYSTEM = "RAS"

COORDINATE_SYSTEMS = ["RAS", "LPS"]


class SimulationUnit:
    """Unit of a mesh coordinate set or data array, in each supported unit system.

    `lengthExponent` is the power of the length unit in the quantity: 0 if the quantity is not
    spatial (e.g., 1/s), 1 if length appears in the numerator (e.g., cm/s), -1 if length appears
    in the denominator (e.g., g/(cm*s)), -2 if length^2 appears in the denominator, etc.
    Because the mass and time units are the same in all supported systems, this exponent is all
    that is needed to convert a value between the systems.
    """

    def __init__(self, quantity, lengthExponent, units, description=""):
        self.quantity = quantity
        self.lengthExponent = lengthExponent
        # unit system name -> unit string. An unrecognized unit (read from a model that was not
        # created by this module) is represented by a single entry that is used in every system.
        self.units = units
        self.description = description

    def unit(self, unitSystem):
        """Unit string in the given unit system, e.g., 'cm/s'. Empty string for dimensionless."""
        if unitSystem in self.units:
            return self.units[unitSystem]
        # Unrecognized unit: it is not known how to express it in other unit systems.
        return next(iter(self.units.values()))

    def unitLabel(self, unitSystem):
        """Unit string for display, where dimensionless quantities are explicitly labeled."""
        return self.unit(unitSystem) or _("(none)")


# Quantities that a mesh coordinate set or data array may represent. Only one entry is needed for
# quantities that share the same unit (e.g., pressure, traction, wall shear stress, and stress),
# because the unit and the length exponent are all that the conversion depends on.
SIMULATION_UNITS = [
    SimulationUnit("dimensionless", 0, {"cgs": "", "mmgs": ""},
                   _("Dimensionless quantity or identifier (not scaled)")),
    SimulationUnit("length", 1, {"cgs": "cm", "mmgs": "mm"},
                   _("Length: coordinate, displacement, thickness, distance, radius")),
    SimulationUnit("velocity", 1, {"cgs": "cm/s", "mmgs": "mm/s"},
                   _("Velocity, speed")),
    SimulationUnit("acceleration", 1, {"cgs": "cm/s2", "mmgs": "mm/s2"},
                   _("Acceleration")),
    SimulationUnit("area", 2, {"cgs": "cm2", "mmgs": "mm2"},
                   _("Area")),
    SimulationUnit("volume", 3, {"cgs": "cm3", "mmgs": "mm3"},
                   _("Volume")),
    SimulationUnit("flowRate", 3, {"cgs": "cm3/s", "mmgs": "mm3/s"},
                   _("Flow rate")),
    SimulationUnit("pressure", -1, {"cgs": "dyn/cm2", "mmgs": "g/(mm*s2)"},
                   _("Pressure, traction, wall shear stress, stress, elastic modulus")),
    SimulationUnit("density", -3, {"cgs": "g/cm3", "mmgs": "g/mm3"},
                   _("Mass density")),
    SimulationUnit("dynamicViscosity", -1, {"cgs": "g/(cm*s)", "mmgs": "g/(mm*s)"},
                   _("Dynamic viscosity")),
    SimulationUnit("kinematicViscosity", 2, {"cgs": "cm2/s", "mmgs": "mm2/s"},
                   _("Kinematic viscosity, diffusion coefficient")),
    SimulationUnit("force", 1, {"cgs": "dyn", "mmgs": "g*mm/s2"},
                   _("Force")),
    SimulationUnit("resistance", -4, {"cgs": "dyn*s/cm5", "mmgs": "g/(mm4*s)"},
                   _("Flow resistance")),
    SimulationUnit("compliance", 4, {"cgs": "cm5/dyn", "mmgs": "mm4*s2/g"},
                   _("Compliance, capacitance")),
    SimulationUnit("mass", 0, {"cgs": "g", "mmgs": "g"},
                   _("Mass")),
    SimulationUnit("time", 0, {"cgs": "s", "mmgs": "s"},
                   _("Time")),
    SimulationUnit("frequency", 0, {"cgs": "1/s", "mmgs": "1/s"},
                   _("Rate: frequency, vorticity, strain rate, divergence")),
]

DIMENSIONLESS_QUANTITY = "dimensionless"
LENGTH_QUANTITY = "length"

# Quantity guessed for an array based on its name. Each rule lists the words that identify a
# quantity; a rule matches if one of its words occurs as a whole word anywhere in the array
# name, which ignores any prefix and any suffix ('Stress_xx' and 'mean_stress' are both a
# stress) and avoids matching a word that only happens to be a part of another one ('ratio'
# inside 'acceleration', for example). A rule word that contains an underscore matches a
# sequence of words, e.g. 'wall_shear_stress' matches 'WallShearStress' and 'wall_shear_stress'.
# The first matching rule wins, so more specific rules must come first.
ARRAY_NAME_QUANTITY_RULES = [
    (r"(ids?|region|domain|zone|label|marker|flag|mask|partition|proc)", DIMENSIONLESS_QUANTITY),
    (r"(strain|jacobian|fraction|ratio|index|criterion|coefficient|number)", DIMENSIONLESS_QUANTITY),
    (r"(wss|wall_shear|wall_shear_stress)", "pressure"),
    (r"(traction)", "pressure"),
    (r"(stress|pressure|pres|modulus|elastance|stiffness)", "pressure"),
    (r"(velocity|veloc|vel|speed)", "velocity"),
    (r"(acceleration|accel)", "acceleration"),
    (r"(displacement|disp|coordinate|coordinates|position|centroid|thickness|radius|diameter"
     r"|distance|length|perimeter|circumference)", LENGTH_QUANTITY),
    (r"(density|rho)", "density"),
    (r"(kinematic_viscosity|diffusivity|diffusion)", "kinematicViscosity"),
    (r"(viscosity|mu)", "dynamicViscosity"),
    (r"(flow|flow_rate|flowrate|discharge|q)", "flowRate"),
    (r"(resistance)", "resistance"),
    (r"(compliance|capacitance)", "compliance"),
    (r"(force|reaction)", "force"),
    (r"(volume)", "volume"),
    (r"(area)", "area"),
    (r"(vorticity|divergence|rate|strain_rate|frequency)", "frequency"),
    (r"(time|times|timestep|dt|period|duration)", "time"),
    (r"(mass)", "mass"),
]


def normalizedArrayName(name):
    """Array name with the words separated by single underscores, in lower case.

    'GlobalNodeID' -> 'global_node_id', 'vWSS' -> 'v_wss', 'Q-Criterion' -> 'q_criterion'.
    This makes it possible to match whole words in the array names, whatever naming convention
    the simulation software uses.
    """
    # Split camel case names ('NodeID' -> 'Node_ID', 'WSSValue' -> 'WSS_Value').
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    normalized = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", normalized)
    # Any other separator (space, hyphen, dot, ...) becomes an underscore.
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized)
    return normalized.strip("_").lower()


def simulationUnitByQuantity(quantity):
    """Return the SimulationUnit with the given quantity name, or the dimensionless unit."""
    for simulationUnit in SIMULATION_UNITS:
        if simulationUnit.quantity == quantity:
            return simulationUnit
    return SIMULATION_UNITS[0]


def simulationUnitByUnitString(unitString):
    """Return the SimulationUnit that uses the given unit string in any unit system, or None."""
    if not unitString:
        return SIMULATION_UNITS[0]
    for simulationUnit in SIMULATION_UNITS:
        if unitString in simulationUnit.units.values():
            return simulationUnit
    return None


def guessSimulationUnit(arrayName, isFloatingPoint=True):
    """Guess the quantity that an array contains, from its name.

    Prefixes and suffixes are ignored: the name is split into words (see normalizedArrayName)
    and a rule matches if its word - or sequence of words - occurs anywhere in the name. So the
    quantity is recognized wherever it is in the name, whatever the simulation software puts
    before or after it:

      Stress, Stress_xx, Stress_yz, solid_Stress_1  -> pressure
      Strain_xz, PrincipalStrain_1, VonMisesStrain  -> dimensionless (strain)
      average_pressure, vinplane_traction           -> pressure

    Integer arrays are always considered dimensionless: they store identifiers, labels, or
    counts, which must not be scaled.
    """
    if not isFloatingPoint:
        return SIMULATION_UNITS[0]
    normalized = normalizedArrayName(arrayName)
    for pattern, quantity in ARRAY_NAME_QUANTITY_RULES:
        # A rule matches only whole words, so a prefix or a suffix that merely contains the
        # letters of a rule word does not match it.
        if re.search(r"(^|_)" + pattern + r"($|_)", normalized):
            return simulationUnitByQuantity(quantity)
    return SIMULATION_UNITS[0]


#
# Coordinate system conversion
#

AXIS_NAMES = "xyz"

# RAS and LPS differ by a 180 degree rotation about the third axis, so the conversion between
# them negates the first two axes. A component of a vector or a tensor is negated if the product
# of the signs of the axes that it refers to is negative: a vector component v(i) is negated if
# the sign of axis i is negative, a tensor component T(i,j) is negated if exactly one of the
# signs of the axes i and j is negative (T transforms as R*T*R', where R is the rotation).
COORDINATE_SYSTEM_AXIS_SIGNS = (-1, -1, 1)

# Axes that each stored component of an array refers to. VTK stores vectors as (X, Y, Z),
# symmetric tensors as (XX, YY, ZZ, XY, YZ, XZ), and full tensors in row-major order.
VECTOR_COMPONENT_AXES = [(0,), (1,), (2,)]
SYMMETRIC_TENSOR_COMPONENT_AXES = [(0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (0, 2)]
TENSOR_COMPONENT_AXES = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)]

# A single tensor component is often stored in an array of its own, named after the component
# (Stress_xx, Strain_xz, sigma_yz, ...).
TENSOR_COMPONENT_NAME_PATTERN = r"_([xyz])([xyz])$"


def arrayComponentAxes(arrayName, numberOfComponents, isFloatingPoint=True):
    """Axes that each component of an array refers to, or None if the array is not directional.

    Directional arrays are the ones whose values are rotated with the coordinate system:
    3-component vectors, 6-component symmetric tensors, 9-component tensors, and single tensor
    components stored in a 1-component array named after the component.

    Scalars that do not depend on the coordinate system (pressure, von Mises stress, principal
    stresses and strains, and any other invariant) are not directional: None is returned for
    them, so they are left unchanged by the coordinate system conversion.
    """
    if not isFloatingPoint:
        # Integer arrays store identifiers, labels, or counts.
        return None
    if numberOfComponents == 3:
        return VECTOR_COMPONENT_AXES
    if numberOfComponents == 6:
        return SYMMETRIC_TENSOR_COMPONENT_AXES
    if numberOfComponents == 9:
        return TENSOR_COMPONENT_AXES
    if numberOfComponents == 1:
        match = re.search(TENSOR_COMPONENT_NAME_PATTERN, normalizedArrayName(arrayName))
        if match:
            return [(AXIS_NAMES.index(match.group(1)), AXIS_NAMES.index(match.group(2)))]
    return None


def arrayComponentNames(arrayName, numberOfComponents, isFloatingPoint=True):
    """Name of each component of a directional array, e.g. ['x', 'y', 'z'] or ['xx', 'yy', ...]."""
    componentAxes = arrayComponentAxes(arrayName, numberOfComponents, isFloatingPoint)
    if componentAxes is None:
        return []
    return ["".join(AXIS_NAMES[axis] for axis in axes) for axes in componentAxes]


def flippedComponentIndices(arrayName, numberOfComponents, isFloatingPoint=True):
    """Indices of the components that must be negated to convert between RAS and LPS."""
    componentAxes = arrayComponentAxes(arrayName, numberOfComponents, isFloatingPoint)
    if componentAxes is None:
        return []
    flippedIndices = []
    for index, axes in enumerate(componentAxes):
        sign = 1
        for axis in axes:
            sign *= COORDINATE_SYSTEM_AXIS_SIGNS[axis]
        if sign < 0:
            flippedIndices.append(index)
    return flippedIndices


def flippedComponentNames(arrayName, numberOfComponents, isFloatingPoint=True):
    """Name of each component that is negated when converting between RAS and LPS."""
    componentNames = arrayComponentNames(arrayName, numberOfComponents, isFloatingPoint)
    return [componentNames[index] for index in flippedComponentIndices(
        arrayName, numberOfComponents, isFloatingPoint)]


def coordinateSystemConversionDescription(arrayName, numberOfComponents, isFloatingPoint=True):
    """Description of how the RAS/LPS conversion affects an array, for tooltips and logging."""
    negatedNames = flippedComponentNames(arrayName, numberOfComponents, isFloatingPoint)
    if not negatedNames:
        return _("not affected by the coordinate system conversion")
    if numberOfComponents == 3:
        kind = _("vector")
    elif numberOfComponents in (6, 9):
        kind = _("tensor")
    else:
        kind = _("tensor component")
    if len(negatedNames) == 1:
        return _("{kind}, the {components} component is negated").format(
            kind=kind, components=negatedNames[0])
    return _("{kind}, the {components} components are negated").format(
        kind=kind, components=", ".join(negatedNames))


def unitSystemConversionFactor(lengthExponent, fromUnitSystem, toUnitSystem):
    """Factor that a value with the given length exponent must be multiplied by to convert it
    from one unit system to another.

    For example, converting a velocity (length exponent 1) from CGS to mm-g-s gives 10
    (1 cm/s = 10 mm/s), converting a pressure (length exponent -1) gives 0.1
    (1 dyn/cm2 = 1 g/(cm*s2) = 0.1 g/(mm*s2)).
    """
    if lengthExponent == 0 or fromUnitSystem == toUnitSystem:
        return 1.0
    fromLengthInMm = UNIT_SYSTEMS[fromUnitSystem]["lengthUnitInMm"]
    toLengthInMm = UNIT_SYSTEMS[toUnitSystem]["lengthUnitInMm"]
    return float(fromLengthInMm / toLengthInMm) ** lengthExponent


#
# Mesh array description
#

POSITION_LOCATION = "position"
POINT_LOCATION = "point"
CELL_LOCATION = "cell"

LOCATION_LABELS = {
    POSITION_LOCATION: _("position"),
    POINT_LOCATION: _("point"),
    CELL_LOCATION: _("cell"),
}

# Name used for the point coordinates in the arrays table and in node attributes.
POSITION_ARRAY_NAME = "Position"


class MeshArrayInfo:
    """Description of the point coordinates or of a data array of a mesh."""

    def __init__(self, name, location, numberOfComponents, isFloatingPoint=True):
        self.name = name
        self.location = location
        self.numberOfComponents = numberOfComponents
        self.isFloatingPoint = isFloatingPoint
        # (minimum, maximum) for each component
        self.componentRanges = []
        self.simulationUnit = SIMULATION_UNITS[0]

    @property
    def key(self):
        return (self.location, self.name)

    def scale(self, fromUnitSystem, toUnitSystem):
        return unitSystemConversionFactor(self.simulationUnit.lengthExponent,
                                          fromUnitSystem, toUnitSystem)

    def rangeString(self, maximumComponents=3):
        """Value range of each component, e.g. '[-31.2, 28.4] [-11.9, 40.1] [0, 92.7]'."""
        if not self.componentRanges:
            return ""
        parts = ["[%.4g, %.4g]" % (valueRange[0], valueRange[1])
                 for valueRange in self.componentRanges[:maximumComponents]]
        if len(self.componentRanges) > maximumComponents:
            parts.append("...")
        return " ".join(parts)

    def mergeRanges(self, other):
        """Extend the value ranges so that they include the ranges of another array as well.

        Used when the same array is present in several input files.
        """
        if len(self.componentRanges) != len(other.componentRanges):
            return
        self.componentRanges = [(min(a[0], b[0]), max(a[1], b[1]))
                                for a, b in zip(self.componentRanges, other.componentRanges)]


def formatScale(value):
    """Format a scale factor for display, e.g. 10, 0.1, 0.001, 1e-06."""
    return "%g" % value


#
# File formats
#


class SimulationModelFileFormat:
    """File format that a model can be exported to.

    The file extension is not a property of the format alone: a surface mesh (vtkPolyData) and
    a volumetric mesh (vtkUnstructuredGrid) are stored in different file types by the VTK
    formats, so the extension is determined by the mesh of the model that is written.
    """

    def __init__(self, formatId, name, polyDataExtension, unstructuredGridExtension):
        self.formatId = formatId
        self.name = name
        self.polyDataExtension = polyDataExtension
        self.unstructuredGridExtension = unstructuredGridExtension

    def extension(self, mesh):
        """File extension to use for a mesh."""
        if isinstance(mesh, vtk.vtkUnstructuredGrid):
            return self.unstructuredGridExtension
        return self.polyDataExtension

    @property
    def extensions(self):
        return sorted({self.polyDataExtension, self.unstructuredGridExtension})


# The XML and the classic VTK formats can store both surface and volumetric meshes. PLY, OBJ,
# and STL can only store a surface mesh, and no data arrays.
SIMULATION_MODEL_FILE_FORMATS = [
    SimulationModelFileFormat("vtkxml", _("VTK (XML)"), ".vtp", ".vtu"),
    SimulationModelFileFormat("vtkclassic", _("VTK (classic)"), ".vtk", ".vtk"),
    SimulationModelFileFormat("ply", _("PLY"), ".ply", ".ply"),
    SimulationModelFileFormat("obj", _("OBJ"), ".obj", ".obj"),
    SimulationModelFileFormat("stl", _("STL"), ".stl", ".stl"),
]


def simulationModelFileFormatById(formatId):
    """Return the file format with the given identifier, or None."""
    for fileFormat in SIMULATION_MODEL_FILE_FORMATS:
        if fileFormat.formatId == formatId:
            return fileFormat
    return None


#
# ImportExportSimulationModel
#


class ImportExportSimulationModel(ScriptedLoadableModule):
    """Import and export simulation meshes, converting between coordinate and unit systems."""

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Import/export simulation model")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Cardiac")]
        self.parent.dependencies = []
        self.parent.contributors = ["Andras Lasso (PerkLab, Queen's University)"]
        self.parent.helpText = _("""
This module imports simulation meshes (surface or volumetric) into the scene and exports models
from the scene, converting between coordinate systems and unit systems. Several files can be
imported at once, and several models can be selected for export in the subject hierarchy tree:
each of them is written to a separate file in the output folder, named after the model.

<b>Coordinate system:</b> models are always stored in the scene in <b>RAS</b>. If the file uses
<b>LPS</b> (the default assumption, unless the file specifies the coordinate system) then the
first two axes are negated, and every array is rotated accordingly:
<ul>
<li><b>Point coordinates and 3-component vectors</b> (velocity, displacement, WSS, ...): the x
and y components are negated.</li>
<li><b>Tensors</b> stored as 6-component (symmetric) or 9-component arrays: the components that
mix the third axis with one of the first two are negated (yz, xz, and for a full tensor zy, zx),
which is the T -&gt; R*T*R' rotation of the tensor.</li>
<li><b>Single tensor components</b> stored in an array of their own, named after the component
(Stress_xz, Strain_yz, sigma_xz, ...): negated if that component is negated.</li>
<li><b>Invariants and other scalars</b> (pressure, von Mises stress and strain, principal
stresses and strains, Jacobian, ...) and integer arrays: left unchanged, because they do not
depend on the coordinate system.</li>
</ul>
The tooltip of each array name in the table shows how that array is transformed.

<b>Unit system:</b> models are always stored in the scene in the <b>mm-g-s</b> system, because
Slicer works in mm. Values read from a file in the <b>CGS</b> (cm-g-s) system are scaled by
10<sup>e</sup>, where <i>e</i> is the length exponent of the quantity (for example, x10 for a
velocity in cm/s, x0.1 for a pressure in dyn/cm2, x0.001 for a density in g/cm3). The mass (g)
and time (s) units are the same in both systems, so the length exponent alone determines the
conversion factor.

The quantity of each array is guessed from the array name and can be corrected in the arrays
table before importing. Any prefix and any suffix of the name is ignored, so the quantity is
recognized wherever it is in the name: <i>Stress</i>, <i>Stress_xx</i>, <i>solid_Stress_1</i>,
and <i>VonMisesStress</i> are all recognized as a stress. The unit and the length exponent of the point coordinates and of every
array are stored in the imported model as node attributes (visible in the Data module), and are
used when the model is exported again.

<b>Supported file formats:</b> .vtu, .vtp, .vtk, .stl, .ply, and .obj can be read. For writing,
the format is selected by name and the extension follows from the mesh: <b>VTK (XML)</b> writes a
surface mesh to .vtp and a volumetric mesh to .vtu, <b>VTK (classic)</b> writes both to .vtk, and
<b>PLY</b>, <b>OBJ</b>, and <b>STL</b> store a surface only, without data arrays.
""")
        self.parent.acknowledgementText = _("""
This file was originally developed by Andras Lasso (PerkLab, Queen's University).
""")


#
# ImportExportSimulationModelWidget
#


class ImportExportSimulationModelWidget(ScriptedLoadableModuleWidget):

    SETTINGS_PREFIX = "ImportExportSimulationModel/"

    NAME_COLUMN = 0
    LOCATION_COLUMN = 1
    COMPONENTS_COLUMN = 2
    RANGE_COLUMN = 3
    UNIT_COLUMN = 4
    SCALE_COLUMN = 5

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        self.logic = None
        self._importArrayInfos = []
        self._exportArrayInfos = []
        self._updatingGui = False
        self._updatingSections = False
        self._dropEventFilter = None

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/ImportExportSimulationModel.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = ImportExportSimulationModelLogic()
        self.logic.logCallback = self.addLog

        for comboBox in (self.ui.inputCoordinateSystemComboBox, self.ui.outputCoordinateSystemComboBox):
            for coordinateSystem in COORDINATE_SYSTEMS:
                comboBox.addItem(coordinateSystem, coordinateSystem)
        for comboBox in (self.ui.inputUnitSystemComboBox, self.ui.outputUnitSystemComboBox):
            for unitSystem, properties in UNIT_SYSTEMS.items():
                comboBox.addItem(properties["name"], unitSystem)

        # Import scales the values from the unit system of the file to the one of the scene,
        # export scales them the other way round.
        self._setupTable(self.ui.importTableWidget, _("Scale to Slicer"))
        self._setupTable(self.ui.exportTableWidget, _("Scale from Slicer"))

        # Files can be dropped on the file list. Virtual method overrides of Qt classes are not
        # available in Python, therefore drag and drop is implemented in an event filter.
        self._dropEventFilter = _FileDropEventFilter(
            ImportExportSimulationModelLogic.READ_FILE_EXTENSIONS, self.addInputFiles)
        self.ui.inputFilesListWidget.installEventFilter(self._dropEventFilter)

        # Several models can be selected for export. Selecting a folder exports everything in it.
        treeView = self.ui.exportModelTreeView
        treeView.nodeTypes = ["vtkMRMLModelNode"]
        treeView.multiSelection = True
        treeView.setColumnHidden(treeView.model().transformColumn, True)
        treeView.setColumnHidden(treeView.model().idColumn, True)

        self.ui.outputFolderPathLineEdit.filters = ctk.ctkPathLineEdit.Dirs
        for index, fileFormat in enumerate(SIMULATION_MODEL_FILE_FORMATS):
            self.ui.outputFileFormatComboBox.addItem(fileFormat.name, fileFormat.formatId)
            self.ui.outputFileFormatComboBox.setItemData(
                index, _("File extension: {extensions}").format(
                    extensions=", ".join(fileFormat.extensions)), qt.Qt.ToolTipRole)

        self.ui.addFilesButton.connect("clicked(bool)", self.onAddFilesButton)
        self.ui.removeFilesButton.connect("clicked(bool)", self.onRemoveFilesButton)
        self.ui.inputCoordinateSystemComboBox.connect("currentIndexChanged(int)", self._onImportOptionChanged)
        self.ui.inputUnitSystemComboBox.connect("currentIndexChanged(int)", self._onImportUnitSystemChanged)
        self.ui.importButton.connect("clicked(bool)", self.onImportButton)

        self.ui.exportModelTreeView.connect("currentItemsChanged(QList<vtkIdType>)",
                                            self._onExportModelChanged)
        self.ui.outputCoordinateSystemComboBox.connect("currentIndexChanged(int)", self._onExportOptionChanged)
        self.ui.outputUnitSystemComboBox.connect("currentIndexChanged(int)", self._onExportOptionChanged)
        self.ui.outputFileFormatComboBox.connect("currentIndexChanged(int)", self._onExportOptionChanged)
        self.ui.outputFolderPathLineEdit.connect("currentPathChanged(QString)", self._onExportOptionChanged)
        self.ui.exportButton.connect("clicked(bool)", self.onExportButton)

        # Importing and exporting are separate tasks, so only one section is open at a time.
        self.ui.importCollapsibleButton.connect(
            "contentsCollapsed(bool)",
            lambda collapsed: self._onSectionCollapsed(collapsed, self.ui.exportCollapsibleButton))
        self.ui.exportCollapsibleButton.connect(
            "contentsCollapsed(bool)",
            lambda collapsed: self._onSectionCollapsed(collapsed, self.ui.importCollapsibleButton))

        self._restoreSettings()
        self._updateImportTable()
        self._updateExportTable()

    def cleanup(self) -> None:
        """Release everything that keeps a reference to this widget, to the scene, or to the
        meshes that were read.

        This is called when the module is unloaded, which may happen after the widgets have
        already been destroyed, and it may be called more than once.
        """
        try:
            if self._dropEventFilter is not None:
                self.ui.inputFilesListWidget.removeEventFilter(self._dropEventFilter)
            # The tree view observes the scene, release it so that the scene can be destroyed.
            self.ui.exportModelTreeView.setMRMLScene(None)
        except (ValueError, RuntimeError):
            # The widgets have already been destroyed, so they hold nothing any more.
            pass
        if self._dropEventFilter is not None:
            self._dropEventFilter.onFilesDropped = None
            self._dropEventFilter = None
        if self.logic is not None:
            self.logic.logCallback = None
            self.logic.clearCache()
        self._importArrayInfos = []
        self._exportArrayInfos = []

    def _onSectionCollapsed(self, collapsed, otherSection) -> None:
        """Close the other section when a section is opened, so only one of them is open.

        Closing a section does not open the other one: the user may want to see neither.
        """
        if collapsed or self._updatingGui or self._updatingSections:
            return
        self._updatingSections = True
        try:
            otherSection.collapsed = True
        finally:
            self._updatingSections = False
        self._saveSettings()

    def _setupTable(self, tableWidget, scaleColumnLabel) -> None:
        tableWidget.columnCount = 6
        tableWidget.setHorizontalHeaderLabels([
            _("Name"), _("Location"), _("Components"), _("Range"), _("Unit"), scaleColumnLabel])
        tableWidget.verticalHeader().visible = False
        tableWidget.horizontalHeader().setSectionResizeMode(qt.QHeaderView.ResizeToContents)
        tableWidget.horizontalHeader().setSectionResizeMode(self.RANGE_COLUMN, qt.QHeaderView.Stretch)
        tableWidget.editTriggers = qt.QAbstractItemView.NoEditTriggers

    # ------------------------------------------------------------------ settings

    def _saveSettings(self) -> None:
        settings = slicer.app.userSettings()
        settings.setValue(self.SETTINGS_PREFIX + "inputCoordinateSystem", self.inputCoordinateSystem)
        settings.setValue(self.SETTINGS_PREFIX + "inputUnitSystem", self.inputUnitSystem)
        settings.setValue(self.SETTINGS_PREFIX + "outputCoordinateSystem", self.outputCoordinateSystem)
        settings.setValue(self.SETTINGS_PREFIX + "outputUnitSystem", self.outputUnitSystem)
        settings.setValue(self.SETTINGS_PREFIX + "outputFileFormat", self.outputFileFormat)
        settings.setValue(self.SETTINGS_PREFIX + "outputFolder",
                          self.ui.outputFolderPathLineEdit.currentPath)
        if not self.ui.importCollapsibleButton.collapsed:
            openSection = "import"
        elif not self.ui.exportCollapsibleButton.collapsed:
            openSection = "export"
        else:
            openSection = "none"
        settings.setValue(self.SETTINGS_PREFIX + "openSection", openSection)

    def _restoreSettings(self) -> None:
        self._updatingGui = True
        try:
            # LPS and CGS are the most common conventions in simulation software, therefore they
            # are the defaults.
            self._setComboBoxValue(self.ui.inputCoordinateSystemComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "inputCoordinateSystem", "LPS"))
            self._setComboBoxValue(self.ui.inputUnitSystemComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "inputUnitSystem", "cgs"))
            self._setComboBoxValue(self.ui.outputCoordinateSystemComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "outputCoordinateSystem", "LPS"))
            self._setComboBoxValue(self.ui.outputUnitSystemComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "outputUnitSystem", "cgs"))
            self._setComboBoxValue(self.ui.outputFileFormatComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "outputFileFormat", "vtkxml"))
            self.ui.outputFolderPathLineEdit.currentPath = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "outputFolder", "")
            openSection = slicer.util.settingsValue(self.SETTINGS_PREFIX + "openSection", "import")
            self.ui.importCollapsibleButton.collapsed = (openSection != "import")
            self.ui.exportCollapsibleButton.collapsed = (openSection != "export")
        finally:
            self._updatingGui = False

    @staticmethod
    def _setComboBoxValue(comboBox, value) -> None:
        index = comboBox.findData(value)
        if index >= 0:
            comboBox.currentIndex = index

    # ------------------------------------------------------------------ current GUI state

    @property
    def inputCoordinateSystem(self):
        return self.ui.inputCoordinateSystemComboBox.currentData

    @property
    def inputUnitSystem(self):
        return self.ui.inputUnitSystemComboBox.currentData

    @property
    def outputCoordinateSystem(self):
        return self.ui.outputCoordinateSystemComboBox.currentData

    @property
    def outputUnitSystem(self):
        return self.ui.outputUnitSystemComboBox.currentData

    @property
    def outputFileFormat(self):
        return self.ui.outputFileFormatComboBox.currentData

    @property
    def selectedExportModelNodes(self):
        """Model nodes selected in the tree view, including the contents of selected folders."""
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        if subjectHierarchyNode is None:
            return []
        selectedItemIds = vtk.vtkIdList()
        self.ui.exportModelTreeView.currentItems(selectedItemIds)

        # Selecting a folder (or the scene) means exporting every model in it.
        itemIds = []
        for index in range(selectedItemIds.GetNumberOfIds()):
            itemId = selectedItemIds.GetId(index)
            itemIds.append(itemId)
            childItemIds = vtk.vtkIdList()
            subjectHierarchyNode.GetItemChildren(itemId, childItemIds, True)
            for childIndex in range(childItemIds.GetNumberOfIds()):
                itemIds.append(childItemIds.GetId(childIndex))

        modelNodes = []
        for itemId in itemIds:
            node = subjectHierarchyNode.GetItemDataNode(itemId)
            if node is not None and node.IsA("vtkMRMLModelNode") and node not in modelNodes:
                modelNodes.append(node)
        # The selection order is the order in which the items were clicked, sort by name so that
        # the exported files are listed and reported in a predictable order.
        modelNodes.sort(key=lambda node: node.GetName())
        return modelNodes

    @property
    def inputFilePaths(self):
        listWidget = self.ui.inputFilesListWidget
        return [listWidget.item(row).data(qt.Qt.UserRole) for row in range(listWidget.count)]

    # ------------------------------------------------------------------ input file list

    def addInputFiles(self, filePaths) -> None:
        """Add files to the input file list, skipping files that are already in the list."""
        existingFilePaths = self.inputFilePaths
        addedFilePaths = []
        for filePath in filePaths:
            filePath = os.path.normpath(filePath)
            if filePath in existingFilePaths or filePath in addedFilePaths:
                continue
            addedFilePaths.append(filePath)
            item = qt.QListWidgetItem(os.path.basename(filePath))
            item.setData(qt.Qt.UserRole, filePath)
            item.setToolTip(filePath)
            self.ui.inputFilesListWidget.addItem(item)
        if addedFilePaths:
            self._updateImportTable()

    def onAddFilesButton(self) -> None:
        lastDirectory = slicer.util.settingsValue(self.SETTINGS_PREFIX + "lastInputDirectory", "")
        filePaths = qt.QFileDialog.getOpenFileNames(
            self.parent, _("Select simulation mesh files"), lastDirectory,
            ImportExportSimulationModelLogic.readFileNameFilter())
        if not filePaths:
            return
        slicer.app.userSettings().setValue(
            self.SETTINGS_PREFIX + "lastInputDirectory", os.path.dirname(filePaths[0]))
        self.addInputFiles(filePaths)

    def onRemoveFilesButton(self) -> None:
        listWidget = self.ui.inputFilesListWidget
        selectedItems = listWidget.selectedItems()
        if not selectedItems:
            listWidget.clear()
        else:
            for item in selectedItems:
                listWidget.takeItem(listWidget.row(item))
        self._updateImportTable()

    # ------------------------------------------------------------------ import table

    def _onImportOptionChanged(self, *unused) -> None:
        if self._updatingGui:
            return
        self._saveSettings()
        # Which components are negated depends on the input coordinate system.
        self._updateImportNameTooltips()

    def _updateImportNameTooltips(self) -> None:
        flipFirstTwoComponents = self.inputCoordinateSystem != SCENE_COORDINATE_SYSTEM
        for row, arrayInfo in enumerate(self._importArrayInfos):
            item = self.ui.importTableWidget.item(row, self.NAME_COLUMN)
            if item is not None:
                item.setToolTip(self._nameTooltip(arrayInfo, flipFirstTwoComponents))

    def _onImportUnitSystemChanged(self, *unused) -> None:
        if self._updatingGui:
            return
        self._saveSettings()
        # Only the displayed units and scales change, the arrays themselves do not,
        # therefore the input files do not have to be read again.
        self._updateImportUnitColumns()

    def _updateImportTable(self) -> None:
        """Read the input files and show their coordinates and data arrays in the table."""
        filePaths = self.inputFilePaths
        self._importArrayInfos = []
        if filePaths:
            with slicer.util.tryWithErrorDisplay(_("Failed to read input files."), waitCursor=True):
                self._importArrayInfos = self.logic.getArrayInfosFromFiles(filePaths)

        tableWidget = self.ui.importTableWidget
        tableWidget.clearContents()
        tableWidget.rowCount = len(self._importArrayInfos)
        flipFirstTwoComponents = self.inputCoordinateSystem != SCENE_COORDINATE_SYSTEM
        for row, arrayInfo in enumerate(self._importArrayInfos):
            self._fillTableRow(tableWidget, row, arrayInfo, flipFirstTwoComponents)
            # The quantity is only guessed from the array name, therefore it must be possible
            # to correct it.
            unitComboBox = qt.QComboBox()
            for index, simulationUnit in enumerate(SIMULATION_UNITS):
                unitComboBox.addItem(simulationUnit.unitLabel(self.inputUnitSystem),
                                     simulationUnit.quantity)
                unitComboBox.setItemData(index, simulationUnit.description, qt.Qt.ToolTipRole)
            unitComboBox.currentIndex = unitComboBox.findData(arrayInfo.simulationUnit.quantity)
            unitComboBox.connect("currentIndexChanged(int)",
                                 lambda index, row=row: self._onImportUnitChanged(row))
            tableWidget.setCellWidget(row, self.UNIT_COLUMN, unitComboBox)
            self._updateImportScaleCell(row)

        self.ui.importButton.enabled = bool(filePaths) and bool(self._importArrayInfos)

    def _updateImportUnitColumns(self) -> None:
        """Update the unit and scale columns after the input unit system changed."""
        tableWidget = self.ui.importTableWidget
        for row in range(tableWidget.rowCount):
            unitComboBox = tableWidget.cellWidget(row, self.UNIT_COLUMN)
            if unitComboBox is None:
                continue
            wasBlocked = unitComboBox.blockSignals(True)
            for index, simulationUnit in enumerate(SIMULATION_UNITS):
                unitComboBox.setItemText(index, simulationUnit.unitLabel(self.inputUnitSystem))
            unitComboBox.blockSignals(wasBlocked)
            self._updateImportScaleCell(row)

    def _onImportUnitChanged(self, row) -> None:
        unitComboBox = self.ui.importTableWidget.cellWidget(row, self.UNIT_COLUMN)
        if unitComboBox is None:
            return
        self._importArrayInfos[row].simulationUnit = simulationUnitByQuantity(unitComboBox.currentData)
        self._updateImportScaleCell(row)

    def _updateImportScaleCell(self, row) -> None:
        arrayInfo = self._importArrayInfos[row]
        scale = arrayInfo.scale(self.inputUnitSystem, SCENE_UNIT_SYSTEM)
        item = qt.QTableWidgetItem(formatScale(scale))
        item.setToolTip(_("Values are multiplied by this factor to convert them from {fromUnit} to "
                          "{toUnit} (length exponent: {lengthExponent}).").format(
            fromUnit=arrayInfo.simulationUnit.unitLabel(self.inputUnitSystem),
            toUnit=arrayInfo.simulationUnit.unitLabel(SCENE_UNIT_SYSTEM),
            lengthExponent=arrayInfo.simulationUnit.lengthExponent))
        self.ui.importTableWidget.setItem(row, self.SCALE_COLUMN, item)

    @staticmethod
    def _nameTooltip(arrayInfo, flipFirstTwoComponents) -> str:
        """Array name and, if the coordinate system changes, how the array is transformed."""
        if not flipFirstTwoComponents:
            return arrayInfo.name
        return arrayInfo.name + "\n" + coordinateSystemConversionDescription(
            arrayInfo.name, arrayInfo.numberOfComponents, arrayInfo.isFloatingPoint)

    @staticmethod
    def _fillTableRow(tableWidget, row, arrayInfo, flipFirstTwoComponents) -> None:
        """Fill the columns that are the same in the import and the export table."""
        nameItem = qt.QTableWidgetItem(arrayInfo.name)
        nameItem.setToolTip(ImportExportSimulationModelWidget._nameTooltip(
            arrayInfo, flipFirstTwoComponents))
        tableWidget.setItem(row, ImportExportSimulationModelWidget.NAME_COLUMN, nameItem)
        tableWidget.setItem(row, ImportExportSimulationModelWidget.LOCATION_COLUMN,
                            qt.QTableWidgetItem(LOCATION_LABELS[arrayInfo.location]))
        tableWidget.setItem(row, ImportExportSimulationModelWidget.COMPONENTS_COLUMN,
                            qt.QTableWidgetItem(str(arrayInfo.numberOfComponents)))
        rangeItem = qt.QTableWidgetItem(arrayInfo.rangeString())
        rangeItem.setToolTip(arrayInfo.rangeString(maximumComponents=arrayInfo.numberOfComponents))
        tableWidget.setItem(row, ImportExportSimulationModelWidget.RANGE_COLUMN, rangeItem)

    def onImportButton(self) -> None:
        with slicer.util.tryWithErrorDisplay(_("Failed to import simulation model."), waitCursor=True):
            self.clearLog()
            quantities = {arrayInfo.key: arrayInfo.simulationUnit.quantity
                          for arrayInfo in self._importArrayInfos}
            modelNodes = self.logic.importFiles(
                self.inputFilePaths, self.inputCoordinateSystem, self.inputUnitSystem, quantities)
            if modelNodes:
                # Preselect the imported models for export.
                itemIds = vtk.vtkIdList()
                subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                if subjectHierarchyNode is not None:
                    for modelNode in modelNodes:
                        itemIds.InsertNextId(subjectHierarchyNode.GetItemByDataNode(modelNode))
                    self.ui.exportModelTreeView.setCurrentItems(itemIds)

    # ------------------------------------------------------------------ export table

    def _onExportModelChanged(self, *unused) -> None:
        self._updateExportTable()

    def _onExportOptionChanged(self, *unused) -> None:
        if self._updatingGui:
            return
        self._saveSettings()
        self._updateExportTable()

    def _updateExportTable(self) -> None:
        """Show the coordinates and data arrays of all selected models in the export table.

        An array that several models have is listed once, with the value range covering all of
        them, the same way as arrays of several input files are listed in the import table.
        """
        modelNodes = self.selectedExportModelNodes
        self._exportArrayInfos = []
        # Unit system and coordinate system that each listed array is stored in. Models are
        # normally all in the scene unit system, but a model may have been changed by hand.
        arrayUnitSystems = []
        arrayInfosByKey = {}
        for modelNode in modelNodes:
            modelUnitSystem = self.logic.getModelUnitSystem(modelNode)
            for arrayInfo in self.logic.getArrayInfosFromModel(modelNode):
                existingArrayInfo = arrayInfosByKey.get(arrayInfo.key)
                if existingArrayInfo is None:
                    arrayInfosByKey[arrayInfo.key] = arrayInfo
                    self._exportArrayInfos.append(arrayInfo)
                    arrayUnitSystems.append(modelUnitSystem)
                else:
                    existingArrayInfo.mergeRanges(arrayInfo)

        tableWidget = self.ui.exportTableWidget
        tableWidget.clearContents()
        tableWidget.rowCount = len(self._exportArrayInfos)
        for row, arrayInfo in enumerate(self._exportArrayInfos):
            modelUnitSystem = arrayUnitSystems[row]
            flipFirstTwoComponents = any(
                self.outputCoordinateSystem != self.logic.getModelCoordinateSystem(modelNode)
                for modelNode in modelNodes)
            self._fillTableRow(tableWidget, row, arrayInfo, flipFirstTwoComponents)
            # Units are not editable here: they are the units stored in the model at import time.
            unitItem = qt.QTableWidgetItem(arrayInfo.simulationUnit.unitLabel(self.outputUnitSystem))
            unitItem.setToolTip(_("Stored in the model as: {unit}").format(
                unit=arrayInfo.simulationUnit.unitLabel(modelUnitSystem)))
            tableWidget.setItem(row, self.UNIT_COLUMN, unitItem)
            scale = arrayInfo.scale(modelUnitSystem, self.outputUnitSystem)
            scaleItem = qt.QTableWidgetItem(formatScale(scale))
            scaleItem.setToolTip(_("Values are multiplied by this factor to convert them from "
                                   "{fromUnit} to {toUnit} (length exponent: {lengthExponent}).").format(
                fromUnit=arrayInfo.simulationUnit.unitLabel(modelUnitSystem),
                toUnit=arrayInfo.simulationUnit.unitLabel(self.outputUnitSystem),
                lengthExponent=arrayInfo.simulationUnit.lengthExponent))
            tableWidget.setItem(row, self.SCALE_COLUMN, scaleItem)

        self.ui.exportButton.text = (_("Export {count} models").format(count=len(modelNodes))
                                     if len(modelNodes) > 1 else _("Export"))
        self.ui.exportButton.enabled = (bool(modelNodes)
                                        and bool(self.ui.outputFolderPathLineEdit.currentPath))

    def onExportButton(self) -> None:
        with slicer.util.tryWithErrorDisplay(_("Failed to export simulation model."), waitCursor=True):
            self.clearLog()
            self.logic.exportModels(
                self.selectedExportModelNodes,
                self.ui.outputFolderPathLineEdit.currentPath,
                self.outputFileFormat,
                self.outputCoordinateSystem, self.outputUnitSystem)

    # ------------------------------------------------------------------ log

    def clearLog(self) -> None:
        self.ui.statusTextEdit.plainText = ""
        slicer.app.processEvents()

    def addLog(self, text) -> None:
        self.ui.statusTextEdit.appendPlainText(text)
        slicer.app.processEvents()


class _FileDropEventFilter(qt.QObject):
    """Accepts files with the given extensions dropped on a widget.

    Qt virtual methods (such as dropEvent) cannot be overridden in Python in Slicer, therefore
    drag and drop support is added to an existing widget with this event filter.
    """

    def __init__(self, extensions, onFilesDropped):
        qt.QObject.__init__(self)
        self.extensions = [extension.lower() for extension in extensions]
        self.onFilesDropped = onFilesDropped

    def eventFilter(self, obj, event):
        eventType = event.type()
        if eventType in (qt.QEvent.DragEnter, qt.QEvent.DragMove):
            if not self._filePaths(event):
                return False
            event.acceptProposedAction()
            return True
        if eventType == qt.QEvent.Drop:
            filePaths = self._filePaths(event)
            if not filePaths:
                return False
            event.acceptProposedAction()
            self.onFilesDropped(filePaths)
            return True
        return False

    def _filePaths(self, event):
        mimeData = event.mimeData()
        if not mimeData.hasUrls():
            return []
        filePaths = []
        for url in mimeData.urls():
            filePath = url.toLocalFile()
            if filePath and os.path.splitext(filePath)[1].lower() in self.extensions:
                filePaths.append(filePath)
        return filePaths


#
# ImportExportSimulationModelLogic
#


class ImportExportSimulationModelLogic(ScriptedLoadableModuleLogic):
    """Reads and writes simulation meshes, converting between coordinate and unit systems.

    Units of the point coordinates and of the data arrays of an imported model are stored in
    node attributes, so that the model can be exported to any unit system later:

      SimulationModel.CoordinateSystem              coordinate system of the model in the scene
      SimulationModel.UnitSystem                    unit system of the model in the scene
      SimulationModel.SourceFile                    file the model was imported from
      SimulationModel.Position.Unit                 unit of the point coordinates, e.g. mm
      SimulationModel.Position.LengthExponent       length exponent of the point coordinates
      SimulationModel.Position.Quantity             quantity name, e.g. length
      SimulationModel.PointArray.<name>.Unit        unit of a point data array, e.g. mm/s
      SimulationModel.PointArray.<name>.*           length exponent and quantity, as above
      SimulationModel.CellArray.<name>.*            the same, for cell data arrays
    """

    ATTRIBUTE_PREFIX = "SimulationModel."

    READ_FILE_EXTENSIONS = [".vtu", ".vtp", ".vtk", ".stl", ".ply", ".obj"]
    WRITE_FILE_EXTENSIONS = [".vtu", ".vtp", ".vtk", ".stl", ".ply", ".obj"]
    # Formats that cannot store data arrays.
    GEOMETRY_ONLY_FILE_EXTENSIONS = [".stl", ".ply", ".obj"]

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)
        self.logCallback = None
        # Input files are read when the arrays table is populated. The meshes are kept so that
        # importing does not have to read the (potentially large) files again.
        self._meshCache = {}

    def addLog(self, text) -> None:
        logging.info(text)
        if self.logCallback:
            self.logCallback(text)

    # ------------------------------------------------------------------ file name filters

    @classmethod
    def readFileNameFilter(cls):
        return _("Simulation meshes") + " (" + " ".join(
            "*" + extension for extension in cls.READ_FILE_EXTENSIONS) + ")"

    @classmethod
    def writeFileNameFilter(cls):
        return _("Simulation meshes") + " (" + " ".join(
            "*" + extension for extension in cls.WRITE_FILE_EXTENSIONS) + ")"

    # ------------------------------------------------------------------ reading and writing

    @staticmethod
    def readMesh(filePath):
        """Read a mesh from file, without any conversion. Returns vtkPolyData or vtkUnstructuredGrid."""
        if not os.path.isfile(filePath):
            raise ValueError(_("Input file not found: {filePath}").format(filePath=filePath))
        extension = os.path.splitext(filePath)[1].lower()
        if extension == ".vtu":
            reader = vtk.vtkXMLUnstructuredGridReader()
        elif extension == ".vtp":
            reader = vtk.vtkXMLPolyDataReader()
        elif extension == ".vtk":
            # Legacy files may contain any data set type.
            reader = vtk.vtkDataSetReader()
            reader.ReadAllScalarsOn()
            reader.ReadAllVectorsOn()
            reader.ReadAllNormalsOn()
            reader.ReadAllTensorsOn()
            reader.ReadAllTCoordsOn()
            reader.ReadAllFieldsOn()
        elif extension == ".stl":
            reader = vtk.vtkSTLReader()
        elif extension == ".ply":
            reader = vtk.vtkPLYReader()
        elif extension == ".obj":
            reader = vtk.vtkOBJReader()
        else:
            raise ValueError(_("Unsupported file format: {filePath}").format(filePath=filePath))
        reader.SetFileName(filePath)
        reader.Update()
        mesh = reader.GetOutput()
        if mesh is None or mesh.GetNumberOfPoints() == 0:
            raise ValueError(_("Failed to read mesh from {filePath}").format(filePath=filePath))
        if isinstance(mesh, (vtk.vtkPolyData, vtk.vtkUnstructuredGrid)):
            return mesh
        # Any other data set type (structured grid, rectilinear grid, ...) is converted to a
        # surface mesh, because that is what a model node can store.
        geometryFilter = vtk.vtkGeometryFilter()
        geometryFilter.SetInputData(mesh)
        geometryFilter.Update()
        return geometryFilter.GetOutput()

    def writeMesh(self, mesh, filePath):
        """Write a mesh to file, without any conversion."""
        extension = os.path.splitext(filePath)[1].lower()
        if extension not in self.WRITE_FILE_EXTENSIONS:
            raise ValueError(_("Unsupported file format: {filePath}").format(filePath=filePath))
        if extension in self.GEOMETRY_ONLY_FILE_EXTENSIONS and (
                mesh.GetPointData().GetNumberOfArrays() or mesh.GetCellData().GetNumberOfArrays()):
            self.addLog(_("Warning: the {extension} file format cannot store data arrays, "
                          "only the geometry is written.").format(extension=extension))
        if extension == ".vtu":
            writer = vtk.vtkXMLUnstructuredGridWriter()
            mesh = self._asUnstructuredGrid(mesh)
        elif extension == ".vtp":
            writer = vtk.vtkXMLPolyDataWriter()
            mesh = self._asPolyData(mesh)
        elif extension == ".vtk":
            if isinstance(mesh, vtk.vtkUnstructuredGrid):
                writer = vtk.vtkUnstructuredGridWriter()
            else:
                writer = vtk.vtkPolyDataWriter()
                mesh = self._asPolyData(mesh)
            writer.SetFileTypeToBinary()
        elif extension == ".stl":
            writer = vtk.vtkSTLWriter()
            mesh = self._asPolyData(mesh)
            writer.SetFileTypeToBinary()
        elif extension == ".ply":
            writer = vtk.vtkPLYWriter()
            mesh = self._asPolyData(mesh)
            writer.SetFileTypeToBinary()
        else:
            writer = vtk.vtkOBJWriter()
            mesh = self._asPolyData(mesh)
        directory = os.path.dirname(filePath)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        writer.SetFileName(filePath)
        writer.SetInputData(mesh)
        if not writer.Write():
            raise RuntimeError(_("Failed to write {filePath}").format(filePath=filePath))

    def _asPolyData(self, mesh):
        if isinstance(mesh, vtk.vtkPolyData):
            return mesh
        self.addLog(_("Warning: the mesh is converted to a surface mesh, "
                      "volumetric cells are not written."))
        geometryFilter = vtk.vtkGeometryFilter()
        geometryFilter.SetInputData(mesh)
        geometryFilter.Update()
        return geometryFilter.GetOutput()

    @staticmethod
    def _asUnstructuredGrid(mesh):
        if isinstance(mesh, vtk.vtkUnstructuredGrid):
            return mesh
        appendFilter = vtk.vtkAppendFilter()
        appendFilter.SetInputData(mesh)
        appendFilter.Update()
        return appendFilter.GetOutput()

    def getCachedMesh(self, filePath):
        """Read a mesh from file, reusing the previously read mesh if the file is unchanged."""
        filePath = os.path.normpath(filePath)
        try:
            fileStatus = os.stat(filePath)
            cacheKey = (fileStatus.st_mtime, fileStatus.st_size)
        except OSError:
            cacheKey = None
        cached = self._meshCache.get(filePath)
        if cached is not None and cacheKey is not None and cached[0] == cacheKey:
            return cached[1]
        mesh = self.readMesh(filePath)
        self._meshCache[filePath] = (cacheKey, mesh)
        return mesh

    def clearCache(self) -> None:
        self._meshCache = {}

    # ------------------------------------------------------------------ mesh inspection

    @staticmethod
    def getArrayInfosFromMesh(mesh):
        """List of MeshArrayInfo describing the point coordinates and all data arrays of a mesh.

        The unit of each array is guessed from the array name.
        """
        arrayInfos = []

        points = mesh.GetPoints()
        if points is not None:
            positionInfo = MeshArrayInfo(POSITION_ARRAY_NAME, POSITION_LOCATION, 3)
            positionInfo.simulationUnit = simulationUnitByQuantity(LENGTH_QUANTITY)
            bounds = [0.0] * 6
            mesh.GetBounds(bounds)
            positionInfo.componentRanges = [(bounds[0], bounds[1]), (bounds[2], bounds[3]),
                                            (bounds[4], bounds[5])]
            arrayInfos.append(positionInfo)

        for location, attributes in ((POINT_LOCATION, mesh.GetPointData()),
                                     (CELL_LOCATION, mesh.GetCellData())):
            for arrayIndex in range(attributes.GetNumberOfArrays()):
                array = attributes.GetArray(arrayIndex)
                if array is None:
                    # Not a numeric array (for example, a string array): it cannot be converted.
                    continue
                name = array.GetName()
                if not name:
                    continue
                isFloatingPoint = array.GetDataType() in (vtk.VTK_FLOAT, vtk.VTK_DOUBLE)
                arrayInfo = MeshArrayInfo(name, location, array.GetNumberOfComponents(),
                                          isFloatingPoint)
                arrayInfo.simulationUnit = guessSimulationUnit(name, isFloatingPoint)
                arrayInfo.componentRanges = [
                    tuple(array.GetRange(componentIndex))
                    for componentIndex in range(array.GetNumberOfComponents())]
                arrayInfos.append(arrayInfo)

        return arrayInfos

    def getArrayInfosFromFiles(self, filePaths):
        """Coordinates and data arrays of all input files, merged into a single list.

        Arrays that are present in several files are listed once, with the value range extended
        to cover all files, so that the same unit is used for all of them.
        """
        # Meshes of files that are no longer needed are released, so that the cache does not
        # keep growing as files are added to and removed from the input file list.
        normalizedFilePaths = [os.path.normpath(filePath) for filePath in filePaths]
        for cachedFilePath in list(self._meshCache):
            if cachedFilePath not in normalizedFilePaths:
                del self._meshCache[cachedFilePath]

        mergedArrayInfos = []
        mergedArrayInfosByKey = {}
        for filePath in filePaths:
            mesh = self.getCachedMesh(filePath)
            for arrayInfo in self.getArrayInfosFromMesh(mesh):
                existingArrayInfo = mergedArrayInfosByKey.get(arrayInfo.key)
                if existingArrayInfo is None:
                    mergedArrayInfosByKey[arrayInfo.key] = arrayInfo
                    mergedArrayInfos.append(arrayInfo)
                else:
                    existingArrayInfo.mergeRanges(arrayInfo)
        return mergedArrayInfos

    # ------------------------------------------------------------------ conversion

    @staticmethod
    def convertMesh(mesh, arrayQuantities, flipFirstTwoComponents, fromUnitSystem, toUnitSystem):
        """Return a converted copy of a mesh.

        :param arrayQuantities: (location, name) -> quantity name. Arrays that are not in the
            dictionary are not scaled.
        :param flipFirstTwoComponents: negate the first two components of the point coordinates
            and of all 3-component floating-point point and cell arrays (RAS <-> LPS conversion).
        """
        convertedMesh = mesh.NewInstance()
        convertedMesh.DeepCopy(mesh)

        def scaleFor(location, name, defaultQuantity=DIMENSIONLESS_QUANTITY):
            quantity = arrayQuantities.get((location, name), defaultQuantity)
            return unitSystemConversionFactor(
                simulationUnitByQuantity(quantity).lengthExponent, fromUnitSystem, toUnitSystem)

        points = convertedMesh.GetPoints()
        if points is not None and points.GetNumberOfPoints() > 0:
            # Point coordinates are lengths, unless the user explicitly set something else.
            positionScale = scaleFor(POSITION_LOCATION, POSITION_ARRAY_NAME, LENGTH_QUANTITY)
            positionFlippedIndices = flippedComponentIndices(POSITION_ARRAY_NAME, 3) \
                if flipFirstTwoComponents else []
            if positionFlippedIndices or positionScale != 1.0:
                pointsArray = numpy_support.vtk_to_numpy(points.GetData())
                if positionFlippedIndices:
                    pointsArray[:, positionFlippedIndices] *= -1.0
                if positionScale != 1.0:
                    pointsArray *= positionScale
                points.GetData().Modified()
                points.Modified()
                convertedMesh.Modified()

        for location, attributes in ((POINT_LOCATION, convertedMesh.GetPointData()),
                                     (CELL_LOCATION, convertedMesh.GetCellData())):
            # Arrays are looked up by name, because replacing an integer array with a
            # floating-point one changes the index of the arrays that follow it.
            arrayNames = [attributes.GetArrayName(arrayIndex)
                          for arrayIndex in range(attributes.GetNumberOfArrays())]
            for name in arrayNames:
                if not name:
                    continue
                array = attributes.GetArray(name)
                if array is None:
                    # Not a numeric array (for example, a string array): it cannot be converted.
                    continue
                isFloatingPoint = array.GetDataType() in (vtk.VTK_FLOAT, vtk.VTK_DOUBLE)
                # Vectors, tensors, and single tensor components are rotated with the coordinate
                # system; invariants (von Mises and principal values, for example) are not.
                flippedIndices = flippedComponentIndices(
                    name, array.GetNumberOfComponents(), isFloatingPoint) \
                    if flipFirstTwoComponents else []
                scale = scaleFor(location, name)
                if not flippedIndices and scale == 1.0:
                    continue
                if not isFloatingPoint:
                    # An integer array cannot be scaled in place without losing precision,
                    # so it is replaced with a floating-point array.
                    array = ImportExportSimulationModelLogic._replaceWithDoubleArray(
                        attributes, name)
                values = numpy_support.vtk_to_numpy(array)
                if flippedIndices:
                    if values.ndim == 1:
                        # A 1-component array holding a single tensor component.
                        values *= -1.0
                    else:
                        values[:, flippedIndices] *= -1.0
                if scale != 1.0:
                    values *= scale
                array.Modified()

        return convertedMesh

    @staticmethod
    def _replaceWithDoubleArray(attributes, name):
        """Replace an array with a double precision copy of itself, in place."""
        array = attributes.GetArray(name)
        attributeType = -1
        for arrayIndex in range(attributes.GetNumberOfArrays()):
            if attributes.GetArrayName(arrayIndex) == name:
                # The array may be the active scalars, vectors, ... of the mesh; the replacement
                # must take over that role.
                attributeType = attributes.IsArrayAnAttribute(arrayIndex)
                break
        doubleArray = vtk.vtkDoubleArray()
        doubleArray.SetName(array.GetName())
        doubleArray.SetNumberOfComponents(array.GetNumberOfComponents())
        doubleArray.SetNumberOfTuples(array.GetNumberOfTuples())
        for componentIndex in range(array.GetNumberOfComponents()):
            doubleArray.CopyComponent(componentIndex, array, componentIndex)
        attributes.RemoveArray(array.GetName())
        attributes.AddArray(doubleArray)
        if attributeType >= 0:
            attributes.SetActiveAttribute(doubleArray.GetName(), attributeType)
        return doubleArray

    # ------------------------------------------------------------------ model attributes

    @classmethod
    def _attributeBaseName(cls, location, name):
        if location == POSITION_LOCATION:
            return cls.ATTRIBUTE_PREFIX + "Position"
        locationName = "PointArray" if location == POINT_LOCATION else "CellArray"
        return cls.ATTRIBUTE_PREFIX + locationName + "." + name

    @classmethod
    def setModelArrayUnits(cls, modelNode, arrayInfos, unitSystem, coordinateSystem):
        """Store the unit and the length exponent of each array in the model node."""
        modelNode.SetAttribute(cls.ATTRIBUTE_PREFIX + "CoordinateSystem", coordinateSystem)
        modelNode.SetAttribute(cls.ATTRIBUTE_PREFIX + "UnitSystem", unitSystem)
        for arrayInfo in arrayInfos:
            baseName = cls._attributeBaseName(arrayInfo.location, arrayInfo.name)
            simulationUnit = arrayInfo.simulationUnit
            modelNode.SetAttribute(baseName + ".Unit", simulationUnit.unit(unitSystem))
            modelNode.SetAttribute(baseName + ".LengthExponent", str(simulationUnit.lengthExponent))
            if simulationUnit.quantity:
                modelNode.SetAttribute(baseName + ".Quantity", simulationUnit.quantity)

    @classmethod
    def getModelUnitSystem(cls, modelNode):
        """Unit system that the model is stored in, mm-g-s if it is not specified in the model."""
        if modelNode is None:
            return SCENE_UNIT_SYSTEM
        unitSystem = modelNode.GetAttribute(cls.ATTRIBUTE_PREFIX + "UnitSystem")
        return unitSystem if unitSystem in UNIT_SYSTEMS else SCENE_UNIT_SYSTEM

    @classmethod
    def getModelCoordinateSystem(cls, modelNode):
        """Coordinate system that the model is stored in, RAS if it is not specified in the model."""
        if modelNode is None:
            return SCENE_COORDINATE_SYSTEM
        coordinateSystem = modelNode.GetAttribute(cls.ATTRIBUTE_PREFIX + "CoordinateSystem")
        return coordinateSystem if coordinateSystem in COORDINATE_SYSTEMS else SCENE_COORDINATE_SYSTEM

    @classmethod
    def getArrayInfosFromModel(cls, modelNode):
        """Coordinates and data arrays of a model, with the units stored in the model node.

        Arrays that have no unit stored in the model node (for example, because the model was
        not imported by this module) get their unit guessed from the array name.
        """
        mesh = modelNode.GetMesh() if modelNode else None
        if mesh is None:
            return []
        arrayInfos = cls.getArrayInfosFromMesh(mesh)
        unitSystem = cls.getModelUnitSystem(modelNode)
        for arrayInfo in arrayInfos:
            baseName = cls._attributeBaseName(arrayInfo.location, arrayInfo.name)
            quantity = modelNode.GetAttribute(baseName + ".Quantity")
            unit = modelNode.GetAttribute(baseName + ".Unit")
            lengthExponent = modelNode.GetAttribute(baseName + ".LengthExponent")
            if quantity:
                arrayInfo.simulationUnit = simulationUnitByQuantity(quantity)
            elif unit is not None:
                simulationUnit = simulationUnitByUnitString(unit)
                if simulationUnit is None:
                    # The unit is not one of the units known by this module. It is still possible
                    # to convert values if the length exponent is known.
                    try:
                        exponent = int(lengthExponent)
                    except (TypeError, ValueError):
                        exponent = 0
                    simulationUnit = SimulationUnit(None, exponent, {unitSystem: unit},
                                                    _("Unit stored in the model"))
                arrayInfo.simulationUnit = simulationUnit
        return arrayInfos

    # ------------------------------------------------------------------ import and export

    def importFiles(self, filePaths, coordinateSystem, unitSystem, arrayQuantities=None):
        """Load mesh files into the scene as model nodes.

        :param coordinateSystem: coordinate system of the files (RAS or LPS). Models are always
            loaded into the scene in RAS.
        :param unitSystem: unit system of the files. Models are always loaded into the scene in
            the mm-g-s system.
        :param arrayQuantities: (location, name) -> quantity name. Arrays that are not in the
            dictionary get their unit guessed from the array name.
        :return: list of the created model nodes.
        """
        if not filePaths:
            raise ValueError(_("No input file is specified"))
        if coordinateSystem not in COORDINATE_SYSTEMS:
            raise ValueError(_("Invalid coordinate system: {coordinateSystem}").format(
                coordinateSystem=coordinateSystem))
        if unitSystem not in UNIT_SYSTEMS:
            raise ValueError(_("Invalid unit system: {unitSystem}").format(unitSystem=unitSystem))

        flipFirstTwoComponents = (coordinateSystem != SCENE_COORDINATE_SYSTEM)
        modelNodes = []
        for filePath in filePaths:
            self.addLog(_("Importing {filePath}").format(filePath=filePath))
            mesh = self.getCachedMesh(filePath)
            # Arrays that the caller did not specify a unit for (for example, arrays that are
            # only present in some of the files) get their unit guessed from the array name.
            quantities = {}
            for arrayInfo in self.getArrayInfosFromMesh(mesh):
                quantities[arrayInfo.key] = arrayInfo.simulationUnit.quantity
            if arrayQuantities:
                quantities.update(arrayQuantities)

            convertedMesh = self.convertMesh(mesh, quantities, flipFirstTwoComponents,
                                             unitSystem, SCENE_UNIT_SYSTEM)
            modelNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLModelNode", os.path.splitext(os.path.basename(filePath))[0])
            modelNode.SetAndObserveMesh(convertedMesh)
            modelNode.CreateDefaultDisplayNodes()

            arrayInfos = self.getArrayInfosFromMesh(convertedMesh)
            for arrayInfo in arrayInfos:
                arrayInfo.simulationUnit = simulationUnitByQuantity(
                    quantities.get(arrayInfo.key, DIMENSIONLESS_QUANTITY))
            self.setModelArrayUnits(modelNode, arrayInfos, SCENE_UNIT_SYSTEM, SCENE_COORDINATE_SYSTEM)
            modelNode.SetAttribute(self.ATTRIBUTE_PREFIX + "SourceFile", filePath)
            self._logConversion(arrayInfos, unitSystem, SCENE_UNIT_SYSTEM, flipFirstTwoComponents)
            modelNodes.append(modelNode)

        # Simulation meshes can be very large (hundreds of MB), therefore the meshes that were
        # read for populating the arrays table are released as soon as they have been imported.
        # The arrays table remains valid, it does not need the meshes any more.
        self.clearCache()

        self.addLog(_("Imported {count} model(s).").format(count=len(modelNodes)))
        return modelNodes

    @staticmethod
    def fileNameFromNodeName(nodeName):
        """File name (without extension) for a model, safe to use on any file system."""
        fileName = re.sub(r'[\\\\/:*?"<>|]+', "_", nodeName).strip(" .")
        return fileName or "model"

    def exportModels(self, modelNodes, outputDirectory, fileFormatId,
                     coordinateSystem, unitSystem):
        """Write each model to a separate file in the output folder, named after the model.

        The file extension is determined by the file format and by the mesh of each model: a
        surface mesh and a volumetric mesh are written to different file types by the VTK
        formats (.vtp and .vtu for VTK (XML), for example).

        :return: list of the written file paths.
        """
        if not modelNodes:
            raise ValueError(_("No model is selected"))
        if not outputDirectory:
            raise ValueError(_("No output folder is specified"))
        fileFormat = simulationModelFileFormatById(fileFormatId)
        if fileFormat is None:
            raise ValueError(_("Unsupported file format: {fileFormatId}").format(
                fileFormatId=fileFormatId))
        if not os.path.isdir(outputDirectory):
            os.makedirs(outputDirectory)

        filePaths = []
        usedFileNames = set()
        for modelNode in modelNodes:
            fileName = self.fileNameFromNodeName(modelNode.GetName())
            extension = fileFormat.extension(modelNode.GetMesh())
            # Two nodes may have the same name; make sure that they do not overwrite each other.
            uniqueFileName = fileName
            index = 1
            while (uniqueFileName + extension).lower() in usedFileNames:
                index += 1
                uniqueFileName = "%s_%d" % (fileName, index)
            usedFileNames.add((uniqueFileName + extension).lower())
            filePath = os.path.join(outputDirectory, uniqueFileName + extension)
            self.exportModel(modelNode, filePath, coordinateSystem, unitSystem)
            filePaths.append(filePath)

        self.addLog(_("Exported {count} model(s) to {outputDirectory}").format(
            count=len(filePaths), outputDirectory=outputDirectory))
        return filePaths

    def exportModel(self, modelNode, filePath, coordinateSystem, unitSystem):
        """Write a model to file, converting it to the given coordinate and unit system."""
        if modelNode is None:
            raise ValueError(_("No model is selected"))
        if not filePath:
            raise ValueError(_("No output file is specified"))
        if coordinateSystem not in COORDINATE_SYSTEMS:
            raise ValueError(_("Invalid coordinate system: {coordinateSystem}").format(
                coordinateSystem=coordinateSystem))
        if unitSystem not in UNIT_SYSTEMS:
            raise ValueError(_("Invalid unit system: {unitSystem}").format(unitSystem=unitSystem))
        mesh = modelNode.GetMesh()
        if mesh is None:
            raise ValueError(_("The selected model contains no mesh"))

        modelUnitSystem = self.getModelUnitSystem(modelNode)
        modelCoordinateSystem = self.getModelCoordinateSystem(modelNode)
        flipFirstTwoComponents = (coordinateSystem != modelCoordinateSystem)

        arrayInfos = self.getArrayInfosFromModel(modelNode)
        # Units that are not known by this module (custom units read from the model node) have no
        # quantity name, so their length exponent is passed to the conversion using a temporary
        # quantity that has the same exponent.
        quantities = {}
        for arrayInfo in arrayInfos:
            simulationUnit = arrayInfo.simulationUnit
            quantity = simulationUnit.quantity
            if quantity is None:
                quantity = self._quantityWithLengthExponent(simulationUnit.lengthExponent)
            quantities[arrayInfo.key] = quantity

        self.addLog(_("Exporting {name} to {filePath}").format(
            name=modelNode.GetName(), filePath=filePath))
        convertedMesh = self.convertMesh(mesh, quantities, flipFirstTwoComponents,
                                         modelUnitSystem, unitSystem)
        self.writeMesh(convertedMesh, filePath)
        self._logConversion(arrayInfos, modelUnitSystem, unitSystem, flipFirstTwoComponents)

    @staticmethod
    def _quantityWithLengthExponent(lengthExponent):
        for simulationUnit in SIMULATION_UNITS:
            if simulationUnit.lengthExponent == lengthExponent:
                return simulationUnit.quantity
        return DIMENSIONLESS_QUANTITY

    def _logConversion(self, arrayInfos, fromUnitSystem, toUnitSystem, flipFirstTwoComponents):
        for arrayInfo in arrayInfos:
            changes = []
            scale = arrayInfo.scale(fromUnitSystem, toUnitSystem)
            if scale != 1.0:
                changes.append(_("{fromUnit} -> {toUnit}, scale: {scale}").format(
                    fromUnit=arrayInfo.simulationUnit.unitLabel(fromUnitSystem),
                    toUnit=arrayInfo.simulationUnit.unitLabel(toUnitSystem),
                    scale=formatScale(scale)))
            if flipFirstTwoComponents:
                negatedNames = flippedComponentNames(
                    arrayInfo.name, arrayInfo.numberOfComponents, arrayInfo.isFloatingPoint)
                if negatedNames:
                    changes.append(_("negated: {components}").format(
                        components=", ".join(negatedNames)))
            if not changes:
                continue
            self.addLog("  {name} ({location}): {changes}".format(
                name=arrayInfo.name, location=LOCATION_LABELS[arrayInfo.location],
                changes="; ".join(changes)))


#
# ImportExportSimulationModelTest
#


class ImportExportSimulationModelTest(ScriptedLoadableModuleTest):

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_UnitConversionFactors()
        self.test_ArrayNameQuantityGuess()
        self.test_TensorConversion()
        self.test_IntegerArrayScaling()

    def test_TensorConversion(self):
        """Stress and strain arrays must be rotated with the coordinate system."""
        self.delayDisplay("Starting tensor conversion test")

        # RAS <-> LPS negates the first two axes, so a tensor component is negated if exactly
        # one of the axes it refers to is one of those two.
        self.assertEqual(flippedComponentNames("Velocity", 3), ["x", "y"])
        self.assertEqual(flippedComponentNames("Stress", 6), ["yz", "xz"])
        self.assertEqual(flippedComponentNames("Stress", 9), ["xz", "yz", "zx", "zy"])
        # Components stored in arrays of their own, one component per array.
        for arrayName, isNegated in (("Stress_xx", False), ("Stress_xy", False),
                                     ("Stress_xz", True), ("Stress_yy", False),
                                     ("Stress_yz", True), ("Stress_zz", False),
                                     ("Strain_xz", True), ("Strain_zx", True),
                                     ("sigma_yz", True), ("StressXZ", True)):
            self.assertEqual(bool(flippedComponentIndices(arrayName, 1)), isNegated, arrayName)
        # Invariants do not depend on the coordinate system.
        for arrayName in ("VonMisesStress", "VonMisesStrain", "PrincipalStress_1",
                          "PrincipalStrain_1", "Pressure", "Jacobian"):
            self.assertEqual(flippedComponentIndices(arrayName, 1), [], arrayName)
        # An integer array is never transformed.
        self.assertEqual(flippedComponentIndices("Stress_xz", 1, isFloatingPoint=False), [])

        # Build a mesh that holds the same tensor in every supported representation.
        tensorComponents = {"xx": 1.0, "yy": 2.0, "zz": 3.0, "xy": 4.0, "yz": 5.0, "xz": 6.0}
        points = vtk.vtkPoints()
        points.InsertNextPoint(0.0, 0.0, 0.0)
        mesh = vtk.vtkPolyData()
        mesh.SetPoints(points)

        for componentName, value in tensorComponents.items():
            array = vtk.vtkDoubleArray()
            array.SetName("Stress_" + componentName)
            array.InsertNextTuple1(value)
            mesh.GetPointData().AddArray(array)

        symmetricTensor = vtk.vtkDoubleArray()
        symmetricTensor.SetName("StressTensor")
        symmetricTensor.SetNumberOfComponents(6)
        # VTK order: XX, YY, ZZ, XY, YZ, XZ
        symmetricTensor.InsertNextTuple([tensorComponents[name]
                                         for name in ("xx", "yy", "zz", "xy", "yz", "xz")])
        mesh.GetPointData().AddArray(symmetricTensor)

        for arrayName, value in (("VonMisesStress", 7.0), ("PrincipalStress_1", 8.0),
                                 ("VonMisesStrain", 0.5), ("PrincipalStrain_1", 0.25)):
            array = vtk.vtkDoubleArray()
            array.SetName(arrayName)
            array.InsertNextTuple1(value)
            mesh.GetPointData().AddArray(array)

        # Convert between coordinate systems only, so that the values are not scaled as well.
        quantities = {}
        convertedMesh = ImportExportSimulationModelLogic.convertMesh(
            mesh, quantities, True, "mmgs", "mmgs")
        pointData = convertedMesh.GetPointData()

        for componentName, value in tensorComponents.items():
            expectedValue = -value if componentName in ("xz", "yz") else value
            self.assertAlmostEqual(pointData.GetArray("Stress_" + componentName).GetTuple1(0),
                                   expectedValue, msg="Stress_" + componentName)

        expectedTensor = [tensorComponents["xx"], tensorComponents["yy"], tensorComponents["zz"],
                          tensorComponents["xy"], -tensorComponents["yz"], -tensorComponents["xz"]]
        self.assertEqual(list(pointData.GetArray("StressTensor").GetTuple(0)), expectedTensor)

        # Von Mises and principal values are invariants: they must not change.
        self.assertAlmostEqual(pointData.GetArray("VonMisesStress").GetTuple1(0), 7.0)
        self.assertAlmostEqual(pointData.GetArray("PrincipalStress_1").GetTuple1(0), 8.0)
        self.assertAlmostEqual(pointData.GetArray("VonMisesStrain").GetTuple1(0), 0.5)
        self.assertAlmostEqual(pointData.GetArray("PrincipalStrain_1").GetTuple1(0), 0.25)

        # Converting back must restore the original values.
        restoredMesh = ImportExportSimulationModelLogic.convertMesh(
            convertedMesh, quantities, True, "mmgs", "mmgs")
        restoredPointData = restoredMesh.GetPointData()
        for componentName, value in tensorComponents.items():
            self.assertAlmostEqual(
                restoredPointData.GetArray("Stress_" + componentName).GetTuple1(0), value)

        # Stress is scaled as a pressure, strain is dimensionless: check that the scaling and the
        # negation are applied together.
        quantities = {(POINT_LOCATION, "Stress_xz"): "pressure",
                      (POINT_LOCATION, "Stress_xx"): "pressure"}
        scaledMesh = ImportExportSimulationModelLogic.convertMesh(
            mesh, quantities, True, "cgs", "mmgs")
        scaledPointData = scaledMesh.GetPointData()
        self.assertAlmostEqual(scaledPointData.GetArray("Stress_xx").GetTuple1(0), 0.1)
        self.assertAlmostEqual(scaledPointData.GetArray("Stress_xz").GetTuple1(0), -0.6)

        self.delayDisplay("Tensor conversion test passed")
        self.test_ImportExport()

    def test_IntegerArrayScaling(self):
        """Scaling an integer array must not disturb the other arrays."""
        self.delayDisplay("Starting integer array scaling test")

        points = vtk.vtkPoints()
        points.InsertNextPoint(0.0, 0.0, 0.0)
        mesh = vtk.vtkPolyData()
        mesh.SetPoints(points)

        for name, arrayType in (("first", vtk.vtkDoubleArray), ("counts", vtk.vtkIntArray),
                                ("last", vtk.vtkDoubleArray)):
            array = arrayType()
            array.SetName(name)
            array.InsertNextTuple1(3)
            mesh.GetPointData().AddArray(array)
        mesh.GetPointData().SetActiveScalars("counts")

        # All three arrays are lengths, so all of them must be scaled by 10 (cm -> mm) exactly
        # once, even though the integer array has to be replaced with a floating-point array.
        quantities = {(POINT_LOCATION, name): LENGTH_QUANTITY
                      for name in ("first", "counts", "last")}
        convertedMesh = ImportExportSimulationModelLogic.convertMesh(
            mesh, quantities, False, "cgs", "mmgs")

        pointData = convertedMesh.GetPointData()
        self.assertEqual(pointData.GetNumberOfArrays(), 3)
        for name in ("first", "counts", "last"):
            self.assertAlmostEqual(pointData.GetArray(name).GetTuple1(0), 30.0)
        self.assertEqual(pointData.GetArray("counts").GetDataType(), vtk.VTK_DOUBLE)
        # The replaced array must remain the active scalars of the mesh.
        self.assertEqual(pointData.GetScalars().GetName(), "counts")
        # The original mesh must not be modified.
        self.assertEqual(mesh.GetPointData().GetArray("first").GetTuple1(0), 3.0)

        self.delayDisplay("Integer array scaling test passed")

    def test_UnitConversionFactors(self):
        self.delayDisplay("Starting unit conversion factor test")

        # Conversion factors from CGS to mm-g-s, computed from the length exponent of each quantity.
        expectedFactors = {
            "length": 10.0,           # 1 cm = 10 mm
            "velocity": 10.0,         # 1 cm/s = 10 mm/s
            "pressure": 0.1,          # 1 dyn/cm2 = 1 g/(cm*s2) = 0.1 g/(mm*s2)
            "density": 1e-3,          # 1 g/cm3 = 0.001 g/mm3
            "dynamicViscosity": 0.1,  # 1 g/(cm*s) = 0.1 g/(mm*s)
            "flowRate": 1000.0,       # 1 cm3/s = 1000 mm3/s
            "force": 10.0,            # 1 dyn = 1 g*cm/s2 = 10 g*mm/s2
            "resistance": 1e-4,       # 1 dyn*s/cm5 = 1 g/(cm4*s) = 1e-4 g/(mm4*s)
            "compliance": 1e4,        # 1 cm5/dyn = 1 cm4*s2/g = 1e4 mm4*s2/g
            "dimensionless": 1.0,
            "time": 1.0,
            "mass": 1.0,
        }
        for quantity, expectedFactor in expectedFactors.items():
            simulationUnit = simulationUnitByQuantity(quantity)
            self.assertEqual(simulationUnit.quantity, quantity)
            factor = unitSystemConversionFactor(simulationUnit.lengthExponent, "cgs", "mmgs")
            self.assertAlmostEqual(factor / expectedFactor, 1.0, places=9)
            # The inverse conversion must restore the original value.
            inverseFactor = unitSystemConversionFactor(simulationUnit.lengthExponent, "mmgs", "cgs")
            self.assertAlmostEqual(factor * inverseFactor, 1.0, places=9)

        self.delayDisplay("Unit conversion factor test passed")

    def test_ArrayNameQuantityGuess(self):
        self.delayDisplay("Starting array name test")

        self.assertEqual(normalizedArrayName("GlobalNodeID"), "global_node_id")
        self.assertEqual(normalizedArrayName("vWSS"), "v_wss")
        self.assertEqual(normalizedArrayName("Q-Criterion"), "q_criterion")
        self.assertEqual(normalizedArrayName("VonMisesStress"), "von_mises_stress")

        # Prefixes and suffixes are ignored: the quantity is recognized wherever it is in the
        # name. Every component of a tensor is therefore recognized as the same quantity.
        for componentName in ("xx", "xy", "xz", "yy", "yz", "zz"):
            self.assertEqual(guessSimulationUnit("Stress_" + componentName).quantity, "pressure")
            self.assertEqual(guessSimulationUnit("Strain_" + componentName).quantity,
                             "dimensionless")
        for arrayName in ("Stress", "Stress_xx", "solid_Stress", "solid_Stress_1",
                          "mean_stress_xy", "VonMisesStress", "PrincipalStress_1",
                          "average_pressure", "vinplane_traction"):
            self.assertEqual(guessSimulationUnit(arrayName).quantity, "pressure", arrayName)
        for arrayName in ("Strain", "Strain_xz", "PrincipalStrain_1", "VonMisesStrain",
                          "mean_strain_xy", "solid_Strain_1"):
            self.assertEqual(guessSimulationUnit(arrayName).quantity, "dimensionless", arrayName)
        for arrayName in ("Velocity", "Velocity_1", "fluid_Velocity", "average_speed"):
            self.assertEqual(guessSimulationUnit(arrayName).quantity, "velocity", arrayName)

        expectedQuantities = {
            # Array names of svFSI/SimVascular results.
            "Velocity": "velocity",
            "Pressure": "pressure",
            "Displacement": "length",
            "Acceleration": "acceleration",
            "WSS": "pressure",
            "vWSS": "pressure",
            "Vorticity": "frequency",
            "Divergence": "frequency",
            "Stress_xx": "pressure",
            "VonMisesStress": "pressure",
            "PrincipalStress_1": "pressure",
            "Strain_xx": "dimensionless",
            "VonMisesStrain": "dimensionless",
            "PrincipalStrain_1": "dimensionless",
            "Jacobian": "dimensionless",
            "Q-Criterion": "dimensionless",
            "GlobalNodeID": "dimensionless",
            "GlobalElementID": "dimensionless",
            "ModelFaceID": "dimensionless",
            "ModelRegionID": "dimensionless",
            "Density": "density",
            "Viscosity": "dynamicViscosity",
            "flow_rate": "flowRate",
            "Area": "area",
            "Time": "time",
            # Camel case names with several words are matched word by word, and so are the
            # same names written with underscores.
            "WallShearStress": "pressure",
            "wall_shear_stress": "pressure",
            "KinematicViscosity": "kinematicViscosity",
            "kinematic_viscosity": "kinematicViscosity",
            "FlowRate": "flowRate",
            # The quantity may be anywhere in the name.
            "average_pressure": "pressure",
            "average_speed": "velocity",
            "vinplane_traction": "pressure",
            # A name that matches no rule must not be scaled.
            "attribute": "dimensionless",
            "SomethingUnknown": "dimensionless",
        }
        for arrayName, expectedQuantity in expectedQuantities.items():
            quantity = guessSimulationUnit(arrayName).quantity
            self.assertEqual(quantity, expectedQuantity,
                             "%s: expected %s, got %s" % (arrayName, expectedQuantity, quantity))

        # A word that is only a part of another word must not match: 'acceleration' contains
        # 'ratio', 'duration' contains 'ratio', 'linear' contains 'area' backwards, and so on.
        self.assertEqual(guessSimulationUnit("Acceleration").quantity, "acceleration")
        self.assertEqual(guessSimulationUnit("Duration").quantity, "time")
        self.assertEqual(guessSimulationUnit("Concentration").quantity, "dimensionless")

        # Integer arrays are never scaled, whatever their name is.
        self.assertEqual(guessSimulationUnit("Velocity", isFloatingPoint=False).quantity,
                         "dimensionless")

        self.delayDisplay("Array name test passed")

    def test_ImportExport(self):
        self.delayDisplay("Starting import/export test")

        import tempfile

        # Create a test mesh in LPS, in the CGS unit system: a single point at (1, 2, 3) cm with
        # a velocity of (1, 2, 3) cm/s and a pressure of 1 dyn/cm2.
        points = vtk.vtkPoints()
        points.InsertNextPoint(1.0, 2.0, 3.0)
        mesh = vtk.vtkPolyData()
        mesh.SetPoints(points)
        vertices = vtk.vtkCellArray()
        vertices.InsertNextCell(1)
        vertices.InsertCellPoint(0)
        mesh.SetVerts(vertices)
        velocity = vtk.vtkDoubleArray()
        velocity.SetName("Velocity")
        velocity.SetNumberOfComponents(3)
        velocity.InsertNextTuple3(1.0, 2.0, 3.0)
        mesh.GetPointData().AddArray(velocity)
        pressure = vtk.vtkDoubleArray()
        pressure.SetName("Pressure")
        pressure.InsertNextTuple1(1.0)
        mesh.GetPointData().AddArray(pressure)

        temporaryDirectory = tempfile.mkdtemp()
        inputFilePath = os.path.join(temporaryDirectory, "testMesh.vtp")
        logic = ImportExportSimulationModelLogic()
        logic.writeMesh(mesh, inputFilePath)

        modelNodes = logic.importFiles([inputFilePath], "LPS", "cgs")
        self.assertEqual(len(modelNodes), 1)
        modelNode = modelNodes[0]
        importedMesh = modelNode.GetMesh()

        # Coordinates: x10 (cm -> mm), first two components negated (LPS -> RAS).
        self.assertEqual(list(importedMesh.GetPoint(0)), [-10.0, -20.0, 30.0])
        # Velocity: x10 (cm/s -> mm/s), first two components negated.
        importedVelocity = list(importedMesh.GetPointData().GetArray("Velocity").GetTuple3(0))
        self.assertEqual(importedVelocity, [-10.0, -20.0, 30.0])
        # Pressure: x0.1 (dyn/cm2 -> g/(mm*s2)), 1 component so it is not negated.
        self.assertAlmostEqual(importedMesh.GetPointData().GetArray("Pressure").GetTuple1(0), 0.1)

        # Units are stored in the model node.
        prefix = ImportExportSimulationModelLogic.ATTRIBUTE_PREFIX
        self.assertEqual(modelNode.GetAttribute(prefix + "UnitSystem"), "mmgs")
        self.assertEqual(modelNode.GetAttribute(prefix + "CoordinateSystem"), "RAS")
        self.assertEqual(modelNode.GetAttribute(prefix + "Position.Unit"), "mm")
        self.assertEqual(modelNode.GetAttribute(prefix + "Position.LengthExponent"), "1")
        self.assertEqual(modelNode.GetAttribute(prefix + "PointArray.Velocity.Unit"), "mm/s")
        self.assertEqual(modelNode.GetAttribute(prefix + "PointArray.Velocity.LengthExponent"), "1")
        self.assertEqual(modelNode.GetAttribute(prefix + "PointArray.Pressure.Unit"), "g/(mm*s2)")
        self.assertEqual(modelNode.GetAttribute(prefix + "PointArray.Pressure.LengthExponent"), "-1")

        # Exporting back to LPS/CGS must restore the original values.
        outputFilePath = os.path.join(temporaryDirectory, "exportedMesh.vtp")
        logic.exportModel(modelNode, outputFilePath, "LPS", "cgs")
        exportedMesh = logic.readMesh(outputFilePath)
        exportedPoint = list(exportedMesh.GetPoint(0))
        for value, expectedValue in zip(exportedPoint, [1.0, 2.0, 3.0]):
            self.assertAlmostEqual(value, expectedValue)
        exportedVelocity = list(exportedMesh.GetPointData().GetArray("Velocity").GetTuple3(0))
        for value, expectedValue in zip(exportedVelocity, [1.0, 2.0, 3.0]):
            self.assertAlmostEqual(value, expectedValue)
        self.assertAlmostEqual(exportedMesh.GetPointData().GetArray("Pressure").GetTuple1(0), 1.0)

        # Exporting to RAS/mm-g-s must write the values as they are stored in the scene.
        outputFilePath2 = os.path.join(temporaryDirectory, "exportedMeshRas.vtp")
        logic.exportModel(modelNode, outputFilePath2, "RAS", "mmgs")
        exportedMesh2 = logic.readMesh(outputFilePath2)
        self.assertEqual(list(exportedMesh2.GetPoint(0)), [-10.0, -20.0, 30.0])

        self.delayDisplay("Import/export test passed")
