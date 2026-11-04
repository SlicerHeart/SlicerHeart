import copy
import hashlib
import logging
import os
import re
import time

import numpy as np
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

# Arrays that hold scalars even if they have several components, so they are not rotated with the
# coordinate system. Q-criterion is a scalar, but some solvers write it in a 3-component array.
NON_DIRECTIONAL_ARRAY_NAME_PATTERN = r"(^|_)q_?criterion($|_)"


def arrayComponentAxes(arrayName, numberOfComponents, isFloatingPoint=True):
    """Axes that each component of an array refers to, or None if the array is not directional.

    Directional arrays are the ones whose values are rotated with the coordinate system:
    2-component vectors of 2D simulations, 3-component vectors, 6-component symmetric tensors,
    9-component tensors, and single tensor components stored in a 1-component array named after
    the component.

    Scalars that do not depend on the coordinate system (pressure, von Mises stress, principal
    stresses and strains, and any other invariant) are not directional: None is returned for
    them, so they are left unchanged by the coordinate system conversion.

    A 2-component array is only considered a vector if its name identifies a physical quantity,
    because 2 components may store something else, such as texture coordinates.
    """
    if not isFloatingPoint:
        # Integer arrays store identifiers, labels, or counts.
        return None
    if re.search(NON_DIRECTIONAL_ARRAY_NAME_PATTERN, normalizedArrayName(arrayName)):
        return None
    if numberOfComponents == 2:
        if guessSimulationUnit(arrayName).quantity == DIMENSIONLESS_QUANTITY:
            return None
        return VECTOR_COMPONENT_AXES[:2]
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
    if numberOfComponents in (2, 3):
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
        # True if the ranges were computed from only a part of the values
        self.isRangeApproximate = False
        self.simulationUnit = SIMULATION_UNITS[0]

    @property
    def key(self):
        return (self.location, self.name)

    def scale(self, fromUnitSystem, toUnitSystem):
        return unitSystemConversionFactor(self.simulationUnit.lengthExponent,
                                          fromUnitSystem, toUnitSystem)

    def rangeString(self, maximumComponents=3):
        """Value range of each component, e.g. '[-31.2, 28.4] [-11.9, 40.1] [0, 92.7]'.

        An approximate range starts with '~'.
        """
        if not self.componentRanges:
            return ""
        parts = ["[%.4g, %.4g]" % (valueRange[0], valueRange[1])
                 for valueRange in self.componentRanges[:maximumComponents]]
        if len(self.componentRanges) > maximumComponents:
            parts.append("...")
        return ("~" if self.isRangeApproximate else "") + " ".join(parts)

    def mergeRanges(self, other):
        """Extend the value ranges so that they include the ranges of another array as well.

        Used when the same array is present in several input files.
        """
        self.isRangeApproximate = self.isRangeApproximate or other.isRangeApproximate
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
        self.parent.dependencies = ["Sequences"]
        self.parent.contributors = ["Andras Lasso (PerkLab, Queen's University)"]
        self.parent.helpText = _("""
This module imports simulation meshes (surface or volumetric) into the scene and exports models
from the scene, converting between coordinate systems and unit systems. Several files can be
imported at once, and several models can be selected for export in the subject hierarchy tree:
each of them is written to a separate file in the output folder, named after the model.
<p>See the <a href="https://github.com/SlicerHeart/SlicerHeart/blob/master/Docs/ImportExportSimulationModel.md">module documentation</a>
for details on unit guessing, conversion rules, stored unit information, and supported file formats.</p>

<b>Coordinate system:</b> models are always stored in the scene in <b>RAS</b>. If the file uses
<b>LPS</b> (the default assumption, unless the file specifies the coordinate system) then the
first two axes are negated, and every array is rotated accordingly:
<ul>
<li><b>Point coordinates and vectors</b> (velocity, displacement, WSS, ...): the x and y
components are negated. A 2-component array is considered a vector if its quantity is recognized
from its name.</li>
<li><b>Tensors</b> stored as 6-component (symmetric) or 9-component arrays: the components that
mix the third axis with one of the first two are negated (yz, xz, and for a full tensor zy, zx),
which is the T -&gt; R*T*R' rotation of the tensor.</li>
<li><b>Single tensor components</b> stored in an array of their own, named after the component
(Stress_xz, Strain_yz, sigma_xz, ...): negated if that component is negated.</li>
<li><b>Invariants and other scalars</b> (pressure, von Mises stress and strain, principal
stresses and strains, Jacobian, Q-criterion even if stored in several components, ...) and
integer arrays: left unchanged, because they do not depend on the coordinate system.</li>
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

<b>Merge duplicate points:</b> simulation results often store a separate copy of a point for each
cell that uses it. By default, copies at the same position with exactly the same values in all
point data arrays are merged on import, which can reduce the memory use several-fold without
changing any value. The option is in the Advanced section of the import section.

<b>Decimate large meshes:</b> by default, tetrahedral meshes with more cells than a threshold are
decimated on import. The shape of the boundary is preserved and data arrays are transferred to the
result, but this reduces the resolution of the data, unlike merging duplicate points. The threshold,
the target reduction, and the boundary weight can be set in the Advanced section.

<b>Resample uniformly:</b> optionally, volumetric meshes are replaced on import by cubes of the
chosen size, aligned with the axes. The volume is preserved, but the boundary becomes a staircase
and details smaller than a cube are lost. Decimation is not used for meshes that are resampled.

<b>First time point, keep 1 of every N time points:</b> the Advanced section can also reduce the
number of time points that are loaded from a VTKHDF file. By default, all of them are loaded.

<b>Approximate scalar ranges:</b> by default, a large VTKHDF file is listed in the arrays table
without reading all of its data, so that adding the file takes seconds. The range of the point
coordinates remains exact, but the ranges of data arrays are computed from a sample of the file,
they are marked with ~ and can be much narrower than the true ranges. This does not affect the import.

<b>Crop to ROI:</b> optionally, only the part of the meshes that is inside the selected ROI is
imported, or written when exporting. Cells at the boundary of the ROI are cut, except that a resampled
mesh keeps its cubes. Exporting does not change the models in the scene, and images are not cropped.

<b>Supported file formats:</b> .vtu, .vtp, .vtk, .vtkhdf, .vtkhdf5, .vti, .stl, .ply, and .obj can
be read. A .vtkhdf or .vtkhdf5 file with several time points is loaded as a sequence of models with
a sequence browser, each time point converted the same way. A .vti file is loaded as a volume, with
its origin and spacing converted to the coordinate and unit system of the scene. For writing,
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
        self.ui.mergeDuplicatePointsCheckBox.connect("toggled(bool)", self._onImportOptionChanged)
        self.ui.decimateCheckBox.connect("toggled(bool)", self._onDecimateToggled)
        self.ui.decimationThresholdSpinBox.connect("valueChanged(int)", self._onImportOptionChanged)
        self.ui.decimationTargetReductionSpinBox.connect("valueChanged(int)", self._onImportOptionChanged)
        self.ui.decimationBoundaryWeightSpinBox.connect("valueChanged(double)", self._onImportOptionChanged)
        self.ui.firstTimePointIndexSpinBox.connect("valueChanged(int)", self._onImportOptionChanged)
        self.ui.keepEveryNthTimePointSpinBox.connect("valueChanged(int)", self._onImportOptionChanged)
        self.ui.resampleCheckBox.connect("toggled(bool)", self._onResampleToggled)
        self.ui.resampleSpacingSpinBox.connect("valueChanged(double)", self._onImportOptionChanged)
        self.ui.approximateRangesCheckBox.connect("toggled(bool)", self._onApproximateRangesToggled)
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
            # These widgets observe the scene, release it so that the scene can be destroyed.
            self.ui.exportModelTreeView.setMRMLScene(None)
            self.ui.importCropRoiNodeComboBox.setMRMLScene(None)
            self.ui.exportCropRoiNodeComboBox.setMRMLScene(None)
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
        settings.setValue(self.SETTINGS_PREFIX + "mergeDuplicatePoints",
                          self.ui.mergeDuplicatePointsCheckBox.checked)
        settings.setValue(self.SETTINGS_PREFIX + "decimate", self.ui.decimateCheckBox.checked)
        settings.setValue(self.SETTINGS_PREFIX + "decimationThreshold",
                          self.ui.decimationThresholdSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "decimationTargetReductionPercent",
                          self.ui.decimationTargetReductionSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "decimationBoundaryWeight",
                          self.ui.decimationBoundaryWeightSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "resample", self.ui.resampleCheckBox.checked)
        settings.setValue(self.SETTINGS_PREFIX + "resampleSpacing", self.ui.resampleSpacingSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "firstTimePointIndex",
                          self.ui.firstTimePointIndexSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "keepEveryNthTimePoint",
                          self.ui.keepEveryNthTimePointSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "approximateRanges",
                          self.ui.approximateRangesCheckBox.checked)
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
            self.ui.mergeDuplicatePointsCheckBox.checked = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "mergeDuplicatePoints", True, converter=slicer.util.toBool)
            self.ui.decimateCheckBox.checked = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "decimate", True, converter=slicer.util.toBool)
            self.ui.decimationThresholdSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "decimationThreshold", DEFAULT_DECIMATION_CELL_COUNT_THRESHOLD,
                converter=int)
            self.ui.decimationTargetReductionSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "decimationTargetReductionPercent",
                int(DEFAULT_DECIMATION_TARGET_REDUCTION * 100), converter=int)
            self.ui.decimationBoundaryWeightSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "decimationBoundaryWeight", DEFAULT_DECIMATION_BOUNDARY_WEIGHT,
                converter=float)
            self.ui.resampleCheckBox.checked = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "resample", False, converter=slicer.util.toBool)
            self.ui.resampleSpacingSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "resampleSpacing", DEFAULT_RESAMPLE_SPACING_MM, converter=float)
            self._updateDecimationWidgets()
            self.ui.firstTimePointIndexSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "firstTimePointIndex", 0, converter=int)
            self.ui.keepEveryNthTimePointSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "keepEveryNthTimePoint", 1, converter=int)
            self.ui.approximateRangesCheckBox.checked = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "approximateRanges", True, converter=slicer.util.toBool)
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

    def _onApproximateRangesToggled(self, *unused) -> None:
        if self._updatingGui:
            return
        self._saveSettings()
        self._updateImportTable()

    def _onDecimateToggled(self, *unused) -> None:
        self._updateDecimationWidgets()
        self._onImportOptionChanged()

    def _onResampleToggled(self, *unused) -> None:
        self._updateDecimationWidgets()
        self._onImportOptionChanged()

    def _updateDecimationWidgets(self) -> None:
        # Every mesh that could be decimated is resampled instead, if resampling is enabled.
        resample = self.ui.resampleCheckBox.checked
        self.ui.label_decimate.enabled = not resample
        self.ui.decimateCheckBox.enabled = not resample
        enabled = self.ui.decimateCheckBox.checked and not resample
        for widget in (self.ui.label_decimationThreshold, self.ui.decimationThresholdSpinBox,
                       self.ui.label_decimationTargetReduction, self.ui.decimationTargetReductionSpinBox,
                       self.ui.label_decimationBoundaryWeight, self.ui.decimationBoundaryWeightSpinBox):
            widget.enabled = enabled
        self.ui.label_resampleSpacing.enabled = resample
        self.ui.resampleSpacingSpinBox.enabled = resample

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
                self._importArrayInfos = self.logic.getArrayInfosFromFiles(
                    filePaths,
                    APPROXIMATE_RANGE_CELL_COUNT_THRESHOLD if self.ui.approximateRangesCheckBox.checked else None)

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
        rangeTooltip = arrayInfo.rangeString(maximumComponents=arrayInfo.numberOfComponents)
        if arrayInfo.isRangeApproximate:
            rangeTooltip += "\n" + _("Approximate: computed from a sample of the file, the true range can be "
                                     "much wider. Disable 'Approximate scalar ranges' in the Advanced section "
                                     "to compute the exact range.")
        rangeItem.setToolTip(rangeTooltip)
        tableWidget.setItem(row, ImportExportSimulationModelWidget.RANGE_COLUMN, rangeItem)

    def onImportButton(self) -> None:
        with slicer.util.tryWithErrorDisplay(_("Failed to import simulation model."), waitCursor=True):
            self.clearLog()
            quantities = {arrayInfo.key: arrayInfo.simulationUnit.quantity
                          for arrayInfo in self._importArrayInfos}
            importedNodes = self.logic.importFiles(
                self.inputFilePaths, self.inputCoordinateSystem, self.inputUnitSystem, quantities,
                self.ui.mergeDuplicatePointsCheckBox.checked,
                self.ui.decimationThresholdSpinBox.value if self.ui.decimateCheckBox.checked else None,
                self.ui.decimationTargetReductionSpinBox.value / 100.0,
                self.ui.decimationBoundaryWeightSpinBox.value,
                self.ui.keepEveryNthTimePointSpinBox.value,
                self.ui.firstTimePointIndexSpinBox.value,
                self.ui.resampleSpacingSpinBox.value if self.ui.resampleCheckBox.checked else None,
                self.ui.importCropRoiNodeComboBox.currentNode())
            # Only models can be exported, volumes that were imported from images cannot.
            modelNodes = [node for node in importedNodes if node.IsA("vtkMRMLModelNode")]
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
                self.outputCoordinateSystem, self.outputUnitSystem,
                self.ui.exportCropRoiNodeComboBox.currentNode())

    # ------------------------------------------------------------------ log

    def clearLog(self) -> None:
        self.ui.statusTextEdit.plainText = ""
        slicer.app.processEvents()

    def addLog(self, text) -> None:
        # Keep showing the latest message, unless the user has scrolled up to read earlier ones.
        scrollBar = self.ui.statusTextEdit.verticalScrollBar()
        wasAtEnd = scrollBar.value >= scrollBar.maximum
        self.ui.statusTextEdit.appendPlainText(text)
        if wasAtEnd:
            scrollBar.value = scrollBar.maximum
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
# Approximate value ranges
#

# The arrays table shows approximate value ranges of VTKHDF files with more cells than this,
# computed from this many partitions, if the file has more partitions than this.
APPROXIMATE_RANGE_CELL_COUNT_THRESHOLD = 1000000
APPROXIMATE_RANGE_PARTITION_COUNT = 8


#
# Mesh decimation
#

# Default settings of the decimation of tetrahedral meshes during import.
DEFAULT_DECIMATION_CELL_COUNT_THRESHOLD = 1000000
DEFAULT_DECIMATION_TARGET_REDUCTION = 0.75
DEFAULT_DECIMATION_BOUNDARY_WEIGHT = 100.0


class MeshGeometryReplacer:
    """Base class of the classes that replace the cells of a mesh, keeping its data arrays.

    The new geometry is created once and the data arrays of the input mesh are transferred to the
    result, therefore the time points of a sequence that have the same geometry get the same
    new geometry, and the time-consuming creation of it is not repeated for them.
    """

    def __init__(self, logCallback=None):
        self.logCallback = logCallback
        self._geometryHash = None
        self._geometry = None
        # For each point and cell of the new geometry: nearest point and cell of the input
        self._nearestPointIds = None
        self._sourceCellIds = None
        # Interpolation of each point of the new geometry: points and weights of an input cell
        self._interpolationPointIds = None
        self._interpolationWeights = None

    def _replaceGeometry(self, mesh):
        """Return a copy of a mesh with the new geometry, with all its data arrays."""
        geometryHash = self._computeGeometryHash(mesh)
        if geometryHash != self._geometryHash:
            self._updateGeometry(mesh)
            self._geometryHash = geometryHash
        return self._transferArrays(mesh)

    def _updateGeometry(self, mesh):
        """Create the new geometry of the mesh and pass it to _setGeometry."""
        raise NotImplementedError()

    def _setGeometry(self, mesh, geometry):
        self._geometry = geometry
        self._nearestPointIds = self._findNearestPoints(mesh, geometry)
        self._sourceCellIds = self._findSourceCells(mesh, geometry)
        self._findInterpolation(mesh, geometry)

    @staticmethod
    def _computeGeometryHash(mesh):
        hasher = hashlib.blake2b()
        hasher.update(numpy_support.vtk_to_numpy(mesh.GetPoints().GetData()))
        hasher.update(numpy_support.vtk_to_numpy(mesh.GetCells().GetConnectivityArray()))
        return hasher.digest()

    def _log(self, text):
        if self.logCallback:
            self.logCallback(text)

    @staticmethod
    def _findNearestPoints(mesh, geometry):
        locator = vtk.vtkStaticPointLocator()
        locator.SetDataSet(mesh)
        locator.BuildLocator()
        points = numpy_support.vtk_to_numpy(geometry.GetPoints().GetData()).astype(float)
        return np.array([locator.FindClosestPoint(point) for point in points.tolist()], dtype=np.int64)

    @staticmethod
    def _findSourceCells(mesh, geometry):
        """Find the input cell that contains the center of each new cell."""
        cellIdsName = "_SourceCellIds"
        source = vtk.vtkUnstructuredGrid()
        source.ShallowCopy(mesh)
        source.GetPointData().Initialize()
        source.GetCellData().Initialize()
        cellIds = numpy_support.numpy_to_vtkIdTypeArray(np.arange(mesh.GetNumberOfCells(), dtype=np.int64), deep=True)
        cellIds.SetName(cellIdsName)
        source.GetCellData().AddArray(cellIds)

        cellCenters = vtk.vtkCellCenters()
        cellCenters.SetInputData(geometry)
        cellCenters.Update()
        centers = cellCenters.GetOutput()
        probe = vtk.vtkProbeFilter()
        probe.SetInputData(centers)
        probe.SetSourceData(source)
        probe.Update()
        probeOutput = probe.GetOutput().GetPointData()
        sourceCellIds = numpy_support.vtk_to_numpy(probeOutput.GetArray(cellIdsName)).astype(np.int64)
        isValid = numpy_support.vtk_to_numpy(probeOutput.GetArray(probe.GetValidPointMaskArrayName())).astype(bool)

        # The center of a cell at a curved boundary may be slightly outside of the input mesh.
        if not isValid.all():
            locator = vtk.vtkStaticCellLocator()
            locator.SetDataSet(source)
            locator.BuildLocator()
            closestPoint = [0.0, 0.0, 0.0]
            cell = vtk.vtkGenericCell()
            cellId = vtk.reference(0)
            subId = vtk.reference(0)
            squaredDistance = vtk.reference(0.0)
            for index in np.nonzero(~isValid)[0].tolist():
                locator.FindClosestPoint(centers.GetPoint(index), closestPoint, cell, cellId, subId, squaredDistance)
                sourceCellIds[index] = cellId.get()
        return sourceCellIds

    def _findInterpolation(self, mesh, geometry):
        """Find how to interpolate the values of the input mesh at each point of the new geometry.

        A point of a curved boundary may be out of the input mesh in the new geometry. The value
        of such a point is interpolated at the closest position of the closest input cell.

        vtkProbeFilter is not used for this because, when it runs on multiple threads, it may miss
        the cell of a point inside the mesh, differently in each run. Such a point would get the
        value 0 in only some of the time points.
        """
        source = vtk.vtkUnstructuredGrid()
        source.ShallowCopy(mesh)
        source.GetPointData().Initialize()
        source.GetCellData().Initialize()
        locator = vtk.vtkStaticCellLocator()
        locator.SetDataSet(source)
        locator.BuildLocator()

        numberOfPoints = geometry.GetNumberOfPoints()
        maximumCellSize = mesh.GetMaxCellSize()
        self._interpolationPointIds = np.zeros((numberOfPoints, maximumCellSize), dtype=np.int64)
        self._interpolationWeights = np.zeros((numberOfPoints, maximumCellSize))
        closestPoint = [0.0, 0.0, 0.0]
        cell = vtk.vtkGenericCell()
        cellId = vtk.reference(0)
        subId = vtk.reference(0)
        squaredDistance = vtk.reference(0.0)
        parametricCoordinates = [0.0, 0.0, 0.0]
        weights = [0.0] * maximumCellSize
        evaluatedPoint = [0.0, 0.0, 0.0]
        points = numpy_support.vtk_to_numpy(geometry.GetPoints().GetData()).astype(float).tolist()
        for pointIndex, point in enumerate(points):
            if locator.FindCell(point, 0.0, cell, parametricCoordinates, weights) < 0:
                locator.FindClosestPoint(point, closestPoint, cell, cellId, subId, squaredDistance)
                # The locator leaves the last cell that it examined in the cell object, not the closest.
                source.GetCell(cellId.get(), cell)
                if cell.EvaluatePosition(closestPoint, evaluatedPoint, subId, parametricCoordinates,
                                         squaredDistance, weights) < 0:
                    # The closest cell is degenerate, there are no weights for it.
                    weights[:] = [1.0] + [0.0] * (maximumCellSize - 1)
            numberOfCellPoints = cell.GetNumberOfPoints()
            for corner in range(numberOfCellPoints):
                self._interpolationPointIds[pointIndex, corner] = cell.GetPointId(corner)
            self._interpolationWeights[pointIndex, :numberOfCellPoints] = weights[:numberOfCellPoints]

        # A closest position is on the boundary of its cell, so rounding errors can make its weights
        # slightly negative. An interpolated value must be within the range of the values of the cell.
        self._interpolationWeights = np.maximum(self._interpolationWeights, 0.0)
        self._interpolationWeights /= self._interpolationWeights.sum(axis=1, keepdims=True)

    def _transferArrays(self, mesh):
        """Return the new geometry with the data arrays of the mesh.

        Floating-point arrays are interpolated. Identifiers and other integers cannot be
        interpolated, so they are taken from the nearest point of the input mesh.
        """
        newMesh = vtk.vtkUnstructuredGrid()
        newMesh.ShallowCopy(self._geometry)

        pointData = mesh.GetPointData()
        for arrayIndex in range(pointData.GetNumberOfArrays()):
            array = pointData.GetArray(arrayIndex)
            if array is None or not array.GetName():
                continue
            sourceValues = numpy_support.vtk_to_numpy(array)
            if array.GetDataType() in (vtk.VTK_FLOAT, vtk.VTK_DOUBLE):
                cornerValues = sourceValues[self._interpolationPointIds]
                weights = self._interpolationWeights.reshape(
                    self._interpolationWeights.shape + (1,) * (cornerValues.ndim - 2))
                values = (cornerValues * weights).sum(axis=1)
            else:
                values = sourceValues[self._nearestPointIds]
            newMesh.GetPointData().AddArray(self._arrayFromValues(array, values))

        cellData = mesh.GetCellData()
        for arrayIndex in range(cellData.GetNumberOfArrays()):
            array = cellData.GetArray(arrayIndex)
            if array is None or not array.GetName():
                continue
            values = numpy_support.vtk_to_numpy(array)[self._sourceCellIds]
            newMesh.GetCellData().AddArray(self._arrayFromValues(array, values))
        return newMesh

    @staticmethod
    def _arrayFromValues(sourceArray, values):
        array = vtk.vtkDataArray.CreateDataArray(sourceArray.GetDataType())
        array.UnRegister(None)  # Prevent memory leak
        array.SetName(sourceArray.GetName())
        array.SetNumberOfComponents(sourceArray.GetNumberOfComponents())
        array.SetNumberOfTuples(len(values))
        numpy_support.vtk_to_numpy(array)[:] = values
        return array


class TetrahedralMeshDecimator(MeshGeometryReplacer):
    """Reduces the number of cells of tetrahedral meshes, preserving the shape of the boundary."""

    # Decimation stops when a pass removes less than this fraction of the cells.
    MINIMUM_REDUCTION_PER_PASS = 0.002

    def __init__(self, targetReduction=DEFAULT_DECIMATION_TARGET_REDUCTION,
                 boundaryWeight=DEFAULT_DECIMATION_BOUNDARY_WEIGHT, logCallback=None):
        super().__init__(logCallback)
        self.targetReduction = targetReduction
        self.boundaryWeight = boundaryWeight
        self.numberOfDecimations = 0

    @staticmethod
    def canDecimate(mesh):
        return (isinstance(mesh, vtk.vtkUnstructuredGrid) and mesh.GetNumberOfCells() > 0
                and mesh.IsHomogeneous() and mesh.GetCellType(0) == vtk.VTK_TETRA)

    def decimate(self, mesh):
        """Return a decimated copy of a mesh, with all its data arrays."""
        return self._replaceGeometry(mesh)

    def _updateGeometry(self, mesh):
        self.numberOfDecimations += 1
        startTime = time.time()

        # Cells must be connected through their points, whatever the point values are.
        geometry = vtk.vtkUnstructuredGrid()
        geometry.ShallowCopy(mesh)
        geometry.GetPointData().Initialize()
        geometry.GetCellData().Initialize()
        geometry.GetFieldData().Initialize()
        mergeFilter = vtk.vtkStaticCleanUnstructuredGrid()
        mergeFilter.SetInputData(geometry)
        mergeFilter.Update()
        geometry = mergeFilter.GetOutput()

        # The filter selects the edges to collapse using rand() % numberOfCells. Where rand() is
        # limited to 32767 (on Windows) it can only reach the beginning of the list of cells and
        # stops early if there are many cells. Therefore, the filter is run repeatedly, with the
        # cells in a different random order in each pass.
        numberOfInputCells = mesh.GetNumberOfCells()
        targetCellCount = max(int(numberOfInputCells * (1.0 - self.targetReduction)), 1)
        randomGenerator = np.random.default_rng(0)
        passIndex = 0
        while geometry.GetNumberOfCells() > targetCellCount:
            passIndex += 1
            numberOfCellsBefore = geometry.GetNumberOfCells()
            decimationFilter = vtk.vtkUnstructuredGridQuadricDecimation()
            decimationFilter.SetInputData(self._shuffledCellsWithScalars(geometry, randomGenerator))
            decimationFilter.SetNumberOfTetsOutput(targetCellCount)
            decimationFilter.SetBoundaryWeight(self.boundaryWeight)
            decimationFilter.Update()
            geometry = decimationFilter.GetOutput()
            self._log(_("  Decimation pass {index}: {before} -> {after} cells").format(
                index=passIndex, before=numberOfCellsBefore, after=geometry.GetNumberOfCells()))
            if (geometry.GetNumberOfCells() > targetCellCount
                    and numberOfCellsBefore - geometry.GetNumberOfCells()
                    < numberOfCellsBefore * self.MINIMUM_REDUCTION_PER_PASS):
                self._log(_("  Warning: the target number of cells ({target}) cannot be reached. Most of "
                            "the remaining cells are at the boundary, which is preserved according to "
                            "the boundary weight.").format(target=targetCellCount))
                break
        geometry.GetPointData().Initialize()

        self._setGeometry(mesh, geometry)
        self._log(_("  Decimated {before} -> {after} cells, {points} points ({seconds:.0f}s)").format(
            before=numberOfInputCells, after=geometry.GetNumberOfCells(),
            points=geometry.GetNumberOfPoints(), seconds=time.time() - startTime))

    @staticmethod
    def _shuffledCellsWithScalars(geometry, randomGenerator):
        tetrahedra = numpy_support.vtk_to_numpy(geometry.GetCells().GetConnectivityArray()).reshape(-1, 4)
        tetrahedra = tetrahedra[randomGenerator.permutation(len(tetrahedra))]
        cells = vtk.vtkCellArray()
        cells.SetData(
            numpy_support.numpy_to_vtkIdTypeArray(np.arange(0, tetrahedra.size + 1, 4, dtype=np.int64), deep=True),
            numpy_support.numpy_to_vtkIdTypeArray(tetrahedra.ravel().astype(np.int64), deep=True))
        shuffled = vtk.vtkUnstructuredGrid()
        shuffled.SetPoints(geometry.GetPoints())
        shuffled.SetCells(vtk.VTK_TETRA, cells)
        # The filter requires a scalar array. A constant makes the decimation depend on the
        # geometry only, so that the same result can be used for all the time points.
        scalars = vtk.vtkFloatArray()
        scalars.SetName("scalars")
        scalars.SetNumberOfTuples(geometry.GetNumberOfPoints())
        scalars.Fill(0.0)
        shuffled.GetPointData().SetScalars(scalars)
        return shuffled


#
# Uniform resampling
#

# Default distance of the grid points of uniform resampling during import, in mm.
DEFAULT_RESAMPLE_SPACING_MM = 1.0


class UniformMeshResampler(MeshGeometryReplacer):
    """Replaces the cells of a volumetric mesh with axis-aligned cubes of the same size.

    A cube of a regular grid is kept if its center is inside the mesh, so the boundary becomes a
    staircase but the volume of the mesh is preserved. Its corners are the points of the result,
    with values interpolated from the mesh. The grid points are at integer multiples of the
    spacing, so the time points of a sequence use the same grid even if the mesh moves.
    """

    # Number of cubes in the bounding box of the mesh above which the resolution is rejected
    MAXIMUM_GRID_CELL_COUNT = 200000000

    def __init__(self, spacing, logCallback=None):
        """:param spacing: size of the cubes, in the length unit of the meshes."""
        super().__init__(logCallback)
        self.spacing = spacing
        self.numberOfResamplings = 0

    @staticmethod
    def canResample(mesh):
        return (isinstance(mesh, vtk.vtkUnstructuredGrid) and mesh.GetNumberOfCells() > 0
                and mesh.GetMaxSpatialDimension() == 3)

    def resample(self, mesh):
        """Return a resampled copy of a mesh, with all its data arrays."""
        return self._replaceGeometry(mesh)

    def _updateGeometry(self, mesh):
        self.numberOfResamplings += 1
        startTime = time.time()

        bounds = np.array(mesh.GetBounds())
        gridStart = np.floor(bounds[0::2] / self.spacing).astype(np.int64)
        gridEnd = np.ceil(bounds[1::2] / self.spacing).astype(np.int64)
        gridCellCounts = np.maximum(gridEnd - gridStart, 1)
        if np.prod(gridCellCounts.astype(float)) > self.MAXIMUM_GRID_CELL_COUNT:
            raise ValueError(_("The resampling resolution is too fine: it would need a grid of "
                               "{x} x {y} x {z} cells. Use a larger value.").format(
                x=gridCellCounts[0], y=gridCellCounts[1], z=gridCellCounts[2]))

        cellCenters = vtk.vtkImageData()
        cellCenters.SetDimensions(*gridCellCounts.tolist())
        cellCenters.SetSpacing(self.spacing, self.spacing, self.spacing)
        cellCenters.SetOrigin(*((gridStart + 0.5) * self.spacing).tolist())
        source = vtk.vtkUnstructuredGrid()
        source.ShallowCopy(mesh)
        source.GetPointData().Initialize()
        source.GetCellData().Initialize()
        probe = vtk.vtkProbeFilter()
        probe.SetInputData(cellCenters)
        probe.SetSourceData(source)
        probe.Update()
        isInside = numpy_support.vtk_to_numpy(
            probe.GetOutput().GetPointData().GetArray(probe.GetValidPointMaskArrayName())).astype(bool)
        keptCells = np.nonzero(isInside)[0]
        if len(keptCells) == 0:
            raise ValueError(_("The resampling resolution is too coarse: the center of no grid cell "
                               "is inside the mesh. Use a smaller value."))

        # Grid indices of the cells, as they are stored in the image
        cellK, cellJ, cellI = np.unravel_index(keptCells, gridCellCounts[::-1])
        cornerOffsets = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                                  [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=np.int64)
        gridPointCounts = gridCellCounts + 1
        cornerGridIds = ((cellI[:, np.newaxis] + cornerOffsets[:, 0])
                         + (cellJ[:, np.newaxis] + cornerOffsets[:, 1]) * gridPointCounts[0]
                         + (cellK[:, np.newaxis] + cornerOffsets[:, 2]) * gridPointCounts[0] * gridPointCounts[1])
        usedGridIds, connectivity = np.unique(cornerGridIds, return_inverse=True)
        pointK, pointJ, pointI = np.unravel_index(usedGridIds, gridPointCounts[::-1])
        coordinates = (np.column_stack((pointI, pointJ, pointK)) + gridStart) * self.spacing

        points = vtk.vtkPoints()
        points.SetData(numpy_support.numpy_to_vtk(
            coordinates.astype(numpy_support.vtk_to_numpy(mesh.GetPoints().GetData()).dtype), deep=True))
        cells = vtk.vtkCellArray()
        cells.SetData(
            numpy_support.numpy_to_vtkIdTypeArray(
                np.arange(0, connectivity.size + 1, 8, dtype=np.int64), deep=True),
            numpy_support.numpy_to_vtkIdTypeArray(connectivity.ravel().astype(np.int64), deep=True))
        geometry = vtk.vtkUnstructuredGrid()
        geometry.SetPoints(points)
        geometry.SetCells(vtk.VTK_HEXAHEDRON, cells)

        self._setGeometry(mesh, geometry)
        self._log(_("  Resampled {before} -> {after} cells, {points} points ({seconds:.0f}s)").format(
            before=mesh.GetNumberOfCells(), after=geometry.GetNumberOfCells(),
            points=geometry.GetNumberOfPoints(), seconds=time.time() - startTime))



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
      SimulationModel.TimeValue                     time in seconds, if a single time point of a
                                                    time series was imported
      SimulationModel.Position.Unit                 unit of the point coordinates, e.g. mm
      SimulationModel.Position.LengthExponent       length exponent of the point coordinates
      SimulationModel.Position.Quantity             quantity name, e.g. length
      SimulationModel.PointArray.<name>.Unit        unit of a point data array, e.g. mm/s
      SimulationModel.PointArray.<name>.*           length exponent and quantity, as above
      SimulationModel.CellArray.<name>.*            the same, for cell data arrays
    """

    ATTRIBUTE_PREFIX = "SimulationModel."

    VTKHDF_FILE_EXTENSIONS = [".vtkhdf", ".vtkhdf5"]
    READ_FILE_EXTENSIONS = [".vtu", ".vtp", ".vtk", ".vtkhdf", ".vtkhdf5", ".vti", ".stl", ".ply", ".obj"]
    WRITE_FILE_EXTENSIONS = [".vtu", ".vtp", ".vtk", ".stl", ".ply", ".obj"]
    # Formats that cannot store data arrays.
    GEOMETRY_ONLY_FILE_EXTENSIONS = [".stl", ".ply", ".obj"]

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)
        self.logCallback = None
        # Input files are read when the arrays table is populated. The meshes are kept so that
        # importing does not have to read the (potentially large) files again.
        self._meshCache = {}
        # Approximate array information of large VTKHDF files, for which no mesh is kept in the cache.
        self._approximateArrayInfoCache = {}

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
        """Read a mesh from file, without any conversion.

        Returns vtkPolyData or vtkUnstructuredGrid, or vtkImageData for a .vti file. Only the last
        time point of a VTKHDF file is returned: this is what the arrays table is populated from,
        because the first time point of a simulation result is often just an empty initial state.
        """
        if not os.path.isfile(filePath):
            raise ValueError(_("Input file not found: {filePath}").format(filePath=filePath))
        extension = os.path.splitext(filePath)[1].lower()
        if extension in ImportExportSimulationModelLogic.VTKHDF_FILE_EXTENSIONS:
            timeValues = ImportExportSimulationModelLogic.getVtkHdfTimeValues(filePath)
            reader = ImportExportSimulationModelLogic._createVtkHdfReader(filePath)
            return ImportExportSimulationModelLogic._readVtkHdfMesh(
                reader, timeValues[-1] if timeValues else None, filePath)
        if extension == ".vtu":
            reader = vtk.vtkXMLUnstructuredGridReader()
        elif extension == ".vtp":
            reader = vtk.vtkXMLPolyDataReader()
        elif extension == ".vti":
            reader = vtk.vtkXMLImageDataReader()
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
        if extension == ".vti":
            return mesh
        return ImportExportSimulationModelLogic._asModelMesh(mesh)

    @staticmethod
    def _asModelMesh(mesh):
        """Return the mesh as vtkPolyData or vtkUnstructuredGrid.

        Any other data set type (structured grid, rectilinear grid, ...) is converted to a
        surface mesh, because that is what a model node can store.
        """
        if isinstance(mesh, (vtk.vtkPolyData, vtk.vtkUnstructuredGrid)):
            return mesh
        geometryFilter = vtk.vtkGeometryFilter()
        geometryFilter.SetInputData(mesh)
        geometryFilter.Update()
        return geometryFilter.GetOutput()

    @staticmethod
    def _createVtkHdfReader(filePath):
        reader = vtk.vtkHDFReader()
        if not reader.CanReadFile(filePath):
            raise ValueError(_("Failed to read mesh from {filePath}").format(filePath=filePath))
        reader.SetFileName(filePath)
        reader.UpdateInformation()
        return reader

    @staticmethod
    def getVtkHdfTimeValues(filePath):
        """Time value of each time point of a VTKHDF file. Empty if the file has only one mesh."""
        reader = ImportExportSimulationModelLogic._createVtkHdfReader(filePath)
        timeStepsKey = vtk.vtkStreamingDemandDrivenPipeline.TIME_STEPS()
        outputInformation = reader.GetOutputInformation(0)
        if not outputInformation.Has(timeStepsKey):
            return []
        timeValues = outputInformation.Get(timeStepsKey)
        return list(timeValues) if len(timeValues) > 1 else []

    @staticmethod
    def _readVtkHdfMesh(reader, timeValue, filePath):
        """Read one time point of a VTKHDF file into a single mesh (timeValue=None if not temporal)."""
        ImportExportSimulationModelLogic._updateVtkHdfReader(reader, timeValue)
        mesh = ImportExportSimulationModelLogic._mergedPartitions(reader.GetOutputDataObject(0))
        if mesh is None or mesh.GetNumberOfPoints() == 0:
            raise ValueError(_("Failed to read mesh from {filePath}").format(filePath=filePath))
        return ImportExportSimulationModelLogic._asModelMesh(mesh)

    @staticmethod
    def _updateVtkHdfReader(reader, timeValue, piece=0, numberOfPieces=1):
        """Read a time point (timeValue=None if not temporal), or only one piece of it."""
        if timeValue is None:
            reader.UpdatePiece(piece, numberOfPieces, 0)
        else:
            reader.UpdateTimeStep(timeValue, piece, numberOfPieces, 0)

    @staticmethod
    def _approximateVtkHdfArrayInfos(filePath, cellCountThreshold):
        """Array information of the last time point of a large VTKHDF file, reading only a part of it.

        Value ranges are not stored in the file, and most of the time of reading a time point is
        spent on the data arrays. Therefore only the geometry is read, which gives the exact range
        of the point coordinates, and the data arrays of a few evenly spaced partitions, which
        give approximate value ranges.

        Returns None if the file should be read completely: it is small, or it does not have
        more partitions than what would be sampled.
        """
        logic = ImportExportSimulationModelLogic
        timeValues = logic.getVtkHdfTimeValues(filePath)
        timeValue = timeValues[-1] if timeValues else None

        reader = logic._createVtkHdfReader(filePath)
        reader.GetPointDataArraySelection().DisableAllArrays()
        reader.GetCellDataArraySelection().DisableAllArrays()
        logic._updateVtkHdfReader(reader, timeValue)
        geometry = reader.GetOutputDataObject(0)
        if not isinstance(geometry, vtk.vtkPartitionedDataSet):
            return None
        numberOfPartitions = geometry.GetNumberOfPartitions()
        partitions = [(index, geometry.GetPartition(index)) for index in range(numberOfPartitions)]
        # A partition may be empty if a solver process had no part of the mesh assigned to it.
        partitions = [(index, partition) for index, partition in partitions
                      if partition is not None and partition.GetNumberOfPoints() > 0]
        numberOfCells = sum(partition.GetNumberOfCells() for _index, partition in partitions)
        if numberOfCells <= cellCountThreshold or len(partitions) <= APPROXIMATE_RANGE_PARTITION_COUNT:
            return None
        bounds = [0.0] * 6
        geometry.GetBounds(bounds)
        sampledPartitionIndices = [partitions[sampleIndex * len(partitions) // APPROXIMATE_RANGE_PARTITION_COUNT][0]
                                   for sampleIndex in range(APPROXIMATE_RANGE_PARTITION_COUNT)]
        # The geometry of the whole time point is not needed any more.
        del partitions, geometry, reader

        sampledArrayInfos = []
        for partitionIndex in sampledPartitionIndices:
            reader = logic._createVtkHdfReader(filePath)
            logic._updateVtkHdfReader(reader, timeValue, partitionIndex, numberOfPartitions)
            partition = logic._mergedPartitions(reader.GetOutputDataObject(0))
            if partition is not None:
                sampledArrayInfos.append(logic.getArrayInfosFromMesh(partition))
        arrayInfos = logic._mergedArrayInfos(sampledArrayInfos)
        for arrayInfo in arrayInfos:
            if arrayInfo.location == POSITION_LOCATION:
                arrayInfo.componentRanges = [(bounds[0], bounds[1]), (bounds[2], bounds[3]),
                                             (bounds[4], bounds[5])]
            else:
                arrayInfo.isRangeApproximate = True
        return arrayInfos

    @staticmethod
    def _mergedPartitions(dataObject):
        """Append the partitions that a parallel solver wrote separately into a single mesh.

        Points are not merged, so the values of the points are preserved as they are in the file.
        """
        if dataObject is None or not dataObject.IsA("vtkCompositeDataSet"):
            return dataObject
        partitions = []
        iterator = vtk.vtkDataObjectTreeIterator()
        iterator.SetDataSet(dataObject)
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            partition = iterator.GetCurrentDataObject()
            # A partition may be empty if a solver process had no part of the mesh assigned to it.
            if partition is not None and partition.GetNumberOfPoints() > 0:
                partitions.append(partition)
            iterator.GoToNextItem()
        if not partitions:
            return None
        if all(isinstance(partition, vtk.vtkPolyData) for partition in partitions):
            appendFilter = vtk.vtkAppendPolyData()
        else:
            appendFilter = vtk.vtkAppendFilter()
        for partition in partitions:
            appendFilter.AddInputData(partition)
        appendFilter.Update()
        return appendFilter.GetOutput()

    @staticmethod
    def mergeDuplicatePoints(mesh):
        """Return the mesh with the points merged that have the same position and the same values.

        Points that are at the same position but have a different value in any point data array
        are kept separate, so no value is changed or lost. Cells and their data are not changed.
        """
        arrayValues = []
        pointData = mesh.GetPointData()
        for arrayIndex in range(pointData.GetNumberOfArrays()):
            array = pointData.GetArray(arrayIndex)
            if array is not None:
                values = numpy_support.vtk_to_numpy(array)
                arrayValues.append(values.reshape(len(values), -1))

        # The merge filter can only compare the values of one array, so all the values are put
        # into a temporary array. A shallow copy is used for not adding it to the input mesh.
        mergingMesh = mesh.NewInstance()
        mergingMesh.ShallowCopy(mesh)
        mergingArrayName = "_MergingValues"
        if arrayValues:
            mergingArray = numpy_support.numpy_to_vtk(np.concatenate(arrayValues, axis=1), deep=False)
            mergingArray.SetName(mergingArrayName)
            mergingMesh.GetPointData().AddArray(mergingArray)

        if isinstance(mesh, vtk.vtkPolyData):
            mergeFilter = vtk.vtkStaticCleanPolyData()
        else:
            mergeFilter = vtk.vtkStaticCleanUnstructuredGrid()
        mergeFilter.SetInputData(mergingMesh)
        mergeFilter.SetRemoveUnusedPoints(False)
        mergeFilter.SetMergingArray(mergingArrayName if arrayValues else "")
        mergeFilter.Update()
        mergedMesh = mergeFilter.GetOutput()
        mergedMesh.GetPointData().RemoveArray(mergingArrayName)
        return mergedMesh

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
        cacheKey = self._fileCacheKey(filePath)
        cached = self._meshCache.get(filePath)
        if cached is not None and cacheKey is not None and cached[0] == cacheKey:
            return cached[1]
        mesh = self.readMesh(filePath)
        self._meshCache[filePath] = (cacheKey, mesh)
        return mesh

    @staticmethod
    def _fileCacheKey(filePath):
        """Value that changes if the file changes, None if the file is not accessible."""
        try:
            fileStatus = os.stat(filePath)
        except OSError:
            return None
        return (fileStatus.st_mtime, fileStatus.st_size)

    def _cachedApproximateArrayInfos(self, filePath, cellCountThreshold):
        """Approximate array information of a file. None if it should be read completely instead."""
        filePath = os.path.normpath(filePath)
        if os.path.splitext(filePath)[1].lower() not in self.VTKHDF_FILE_EXTENSIONS:
            return None
        fileKey = self._fileCacheKey(filePath)
        if fileKey is None:
            return None
        cacheKey = (fileKey, cellCountThreshold)
        cached = self._approximateArrayInfoCache.get(filePath)
        if cached is None or cached[0] != cacheKey:
            cached = (cacheKey, self._approximateVtkHdfArrayInfos(filePath, cellCountThreshold))
            self._approximateArrayInfoCache[filePath] = cached
        if cached[1] is None:
            return None
        # A mesh that was read while the option was disabled would only take up memory now.
        self._meshCache.pop(filePath, None)
        # The caller may modify the returned objects.
        return [copy.copy(arrayInfo) for arrayInfo in cached[1]]

    def clearCache(self) -> None:
        self._meshCache = {}
        self._approximateArrayInfoCache = {}

    # ------------------------------------------------------------------ mesh inspection

    @staticmethod
    def getArrayInfosFromMesh(mesh):
        """List of MeshArrayInfo describing the point coordinates and all data arrays of a mesh.

        The unit of each array is guessed from the array name.
        """
        arrayInfos = []

        # Points of an image are implicit, they must not be requested from it because that would
        # allocate a coordinate for every voxel.
        isImage = isinstance(mesh, vtk.vtkImageData)
        if isImage or mesh.GetPoints() is not None:
            positionInfo = MeshArrayInfo(POSITION_ARRAY_NAME, POSITION_LOCATION, 3)
            positionInfo.simulationUnit = simulationUnitByQuantity(LENGTH_QUANTITY)
            bounds = [0.0] * 6
            mesh.GetBounds(bounds)
            positionInfo.componentRanges = [(bounds[0], bounds[1]), (bounds[2], bounds[3]),
                                            (bounds[4], bounds[5])]
            arrayInfos.append(positionInfo)

        for location, attributes in ((POINT_LOCATION, mesh.GetPointData()),
                                     (CELL_LOCATION, mesh.GetCellData())):
            if isImage and location == CELL_LOCATION:
                # A volume node stores voxel values, which are point data of the image.
                continue
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

    def getArrayInfosFromFiles(self, filePaths, approximateRangeCellCountThreshold=None):
        """Coordinates and data arrays of all input files, merged into a single list.

        Arrays that are present in several files are listed once, with the value range extended
        to cover all files, so that the same unit is used for all of them.

        :param approximateRangeCellCountThreshold: VTKHDF files with more cells than this are not
            read completely, and the value ranges of their data arrays are only approximate.
            None to always compute the exact ranges.
        """
        # Meshes of files that are no longer needed are released, so that the cache does not
        # keep growing as files are added to and removed from the input file list.
        normalizedFilePaths = [os.path.normpath(filePath) for filePath in filePaths]
        for cache in (self._meshCache, self._approximateArrayInfoCache):
            for cachedFilePath in list(cache):
                if cachedFilePath not in normalizedFilePaths:
                    del cache[cachedFilePath]

        fileArrayInfos = []
        for filePath in filePaths:
            arrayInfos = None
            if approximateRangeCellCountThreshold is not None:
                arrayInfos = self._cachedApproximateArrayInfos(filePath, approximateRangeCellCountThreshold)
            if arrayInfos is None:
                arrayInfos = self.getArrayInfosFromMesh(self.getCachedMesh(filePath))
            fileArrayInfos.append(arrayInfos)
        return self._mergedArrayInfos(fileArrayInfos)

    @staticmethod
    def _mergedArrayInfos(arrayInfoLists):
        """Merge lists of array information into one, extending the ranges of the same array."""
        mergedArrayInfos = []
        mergedArrayInfosByKey = {}
        for arrayInfos in arrayInfoLists:
            for arrayInfo in arrayInfos:
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
        """Return a converted copy of a mesh or image.

        The geometry of an image is defined by its origin, spacing, and direction, so these are
        converted the same way as the point coordinates of a mesh.

        :param arrayQuantities: (location, name) -> quantity name. Arrays that are not in the
            dictionary are not scaled.
        :param flipFirstTwoComponents: negate the first two components of the point coordinates
            and rotate all directional point and cell arrays (RAS <-> LPS conversion), see
            arrayComponentAxes.
        """
        convertedMesh = mesh.NewInstance()
        convertedMesh.DeepCopy(mesh)

        def scaleFor(location, name, defaultQuantity=DIMENSIONLESS_QUANTITY):
            quantity = arrayQuantities.get((location, name), defaultQuantity)
            return unitSystemConversionFactor(
                simulationUnitByQuantity(quantity).lengthExponent, fromUnitSystem, toUnitSystem)

        # Point coordinates are lengths, unless the user explicitly set something else.
        positionScale = scaleFor(POSITION_LOCATION, POSITION_ARRAY_NAME, LENGTH_QUANTITY)
        positionFlippedIndices = flippedComponentIndices(POSITION_ARRAY_NAME, 3) \
            if flipFirstTwoComponents else []
        if isinstance(convertedMesh, vtk.vtkImageData):
            ImportExportSimulationModelLogic._convertImageGeometry(
                convertedMesh, positionFlippedIndices, positionScale)
        else:
            points = convertedMesh.GetPoints()
            if (points is not None and points.GetNumberOfPoints() > 0
                    and (positionFlippedIndices or positionScale != 1.0)):
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
    def _convertImageGeometry(image, flippedIndices, scale):
        """Apply a coordinate system flip and a length scale to the geometry of an image, in place.

        A voxel is at origin + direction * (spacing * ijk). The scale applies to the origin and the
        spacing, the flip applies to the origin and to the rows of the direction matrix.
        """
        signs = [-1.0 if axis in flippedIndices else 1.0 for axis in range(3)]
        origin = image.GetOrigin()
        image.SetOrigin([signs[axis] * origin[axis] * scale for axis in range(3)])
        image.SetSpacing([spacing * scale for spacing in image.GetSpacing()])
        direction = vtk.vtkMatrix3x3()
        direction.DeepCopy(image.GetDirectionMatrix())
        for row in range(3):
            for column in range(3):
                direction.SetElement(row, column, signs[row] * direction.GetElement(row, column))
        image.SetDirectionMatrix(direction)

    @staticmethod
    def _imageIjkToRasMatrix(image):
        """IJK to RAS matrix of an image in the scene, for voxel indices that start from 0."""
        origin = image.GetOrigin()
        spacing = image.GetSpacing()
        direction = image.GetDirectionMatrix()
        extent = image.GetExtent()
        ijkToRas = vtk.vtkMatrix4x4()
        for row in range(3):
            # An extent that does not start from 0 is equivalent to an offset of the origin.
            position = origin[row]
            for column in range(3):
                columnScale = direction.GetElement(row, column) * spacing[column]
                ijkToRas.SetElement(row, column, columnScale)
                position += columnScale * extent[column * 2]
            ijkToRas.SetElement(row, 3, position)
        return ijkToRas

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

    def importFiles(self, filePaths, coordinateSystem, unitSystem, arrayQuantities=None,
                    mergeDuplicatePoints=True,
                    decimationCellCountThreshold=DEFAULT_DECIMATION_CELL_COUNT_THRESHOLD,
                    decimationTargetReduction=DEFAULT_DECIMATION_TARGET_REDUCTION,
                    decimationBoundaryWeight=DEFAULT_DECIMATION_BOUNDARY_WEIGHT,
                    keepEveryNthTimePoint=1, firstTimePointIndex=0, resampleSpacing=None, roiNode=None):
        """Load mesh and image files into the scene.

        A mesh is loaded as a model node. A VTKHDF file with several time points is loaded as a
        sequence of models with a sequence browser. A .vti image is loaded as a volume node.

        :param coordinateSystem: coordinate system of the files (RAS or LPS). Nodes are always
            loaded into the scene in RAS.
        :param unitSystem: unit system of the files. Nodes are always loaded into the scene in
            the mm-g-s system.
        :param arrayQuantities: (location, name) -> quantity name. Arrays that are not in the
            dictionary get their unit guessed from the array name.
        :param mergeDuplicatePoints: merge the points of meshes that have the same position and the
            same values, see mergeDuplicatePoints.
        :param decimationCellCountThreshold: tetrahedral meshes that have more cells than this are
            decimated, see TetrahedralMeshDecimator. None disables decimation.
        :param decimationTargetReduction: fraction of the cells to remove from a decimated mesh.
        :param decimationBoundaryWeight: how strongly the boundary of a decimated mesh is preserved.
        :param keepEveryNthTimePoint: load only the first of every N time points of a time series.
        :param firstTimePointIndex: index of the first time point to load from a time series,
            starting from 0.
        :param resampleSpacing: replace the cells of volumetric meshes with cubes of this size, in
            mm, instead of decimating them. None to not resample.
        :param roiNode: markups ROI node to crop the meshes to, compared to the position that the
            meshes will have in the scene. Images are not cropped. None to not crop.
        :return: list of the created model nodes (the proxy model node of a sequence) and volume
            nodes.
        """
        if not filePaths:
            raise ValueError(_("No input file is specified"))
        if coordinateSystem not in COORDINATE_SYSTEMS:
            raise ValueError(_("Invalid coordinate system: {coordinateSystem}").format(
                coordinateSystem=coordinateSystem))
        if unitSystem not in UNIT_SYSTEMS:
            raise ValueError(_("Invalid unit system: {unitSystem}").format(unitSystem=unitSystem))
        if keepEveryNthTimePoint < 1:
            raise ValueError(_("Invalid number of time points to keep: 1 of {count}").format(
                count=keepEveryNthTimePoint))
        if firstTimePointIndex < 0:
            raise ValueError(_("Invalid index of the first time point: {index}").format(
                index=firstTimePointIndex))
        if resampleSpacing is not None and resampleSpacing <= 0:
            raise ValueError(_("Invalid resampling resolution: {spacing}").format(spacing=resampleSpacing))

        flipFirstTwoComponents = (coordinateSystem != SCENE_COORDINATE_SYSTEM)
        importedNodes = []
        for filePath in filePaths:
            self.addLog(_("Importing {filePath}").format(filePath=filePath))
            nodeName = os.path.splitext(os.path.basename(filePath))[0]
            extension = os.path.splitext(filePath)[1].lower()
            reduceMesh = self._meshReductionFunction(
                mergeDuplicatePoints, decimationCellCountThreshold, decimationTargetReduction,
                decimationBoundaryWeight,
                None if resampleSpacing is None else resampleSpacing / UNIT_SYSTEMS[unitSystem]["lengthUnitInMm"],
                roiNode, None if roiNode is None else self._roiPlanesInFileCoordinates(
                    roiNode, coordinateSystem, unitSystem, arrayQuantities), nodeName)
            timeValues = self.getVtkHdfTimeValues(filePath) \
                if extension in self.VTKHDF_FILE_EXTENSIONS else []
            if timeValues:
                keptTimeValues = timeValues[firstTimePointIndex::keepEveryNthTimePoint]
                if not keptTimeValues:
                    raise ValueError(_("Index of the first time point ({index}) is too large, {filePath} "
                                       "has {count} time points (the index of the first one is 0).").format(
                        index=firstTimePointIndex, filePath=filePath, count=len(timeValues)))
                if len(keptTimeValues) < len(timeValues):
                    self.addLog(_("  Keeping {kept} of {count} time points").format(
                        kept=len(keptTimeValues), count=len(timeValues)))
                if len(keptTimeValues) > 1:
                    importedNodes.append(self._importTimeSeries(
                        filePath, nodeName, keptTimeValues, flipFirstTwoComponents, unitSystem, arrayQuantities,
                        reduceMesh))
                    continue
                # A sequence of a single time point would be of no use, a model is loaded instead.
                singleTimeValue = keptTimeValues[0]
                self._meshCache.pop(os.path.normpath(filePath), None)
                mesh = self._readVtkHdfMesh(self._createVtkHdfReader(filePath), singleTimeValue, filePath)
            else:
                singleTimeValue = None
                mesh = self.getCachedMesh(filePath)
            if isinstance(mesh, vtk.vtkImageData):
                if roiNode is not None:
                    self.addLog(_("Warning: images are not cropped to the ROI."))
                importedNodes.extend(self._importImage(
                    filePath, nodeName, mesh, flipFirstTwoComponents, unitSystem, arrayQuantities))
                continue

            mesh = reduceMesh(mesh)
            quantities = self._fileArrayQuantities(mesh, arrayQuantities)
            convertedMesh = self.convertMesh(mesh, quantities, flipFirstTwoComponents,
                                             unitSystem, SCENE_UNIT_SYSTEM)
            modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", nodeName)
            modelNode.SetAndObserveMesh(convertedMesh)
            modelNode.CreateDefaultDisplayNodes()

            arrayInfos = self._convertedArrayInfos(convertedMesh, quantities)
            self.setModelArrayUnits(modelNode, arrayInfos, SCENE_UNIT_SYSTEM, SCENE_COORDINATE_SYSTEM)
            modelNode.SetAttribute(self.ATTRIBUTE_PREFIX + "SourceFile", filePath)
            if singleTimeValue is not None:
                modelNode.SetAttribute(self.ATTRIBUTE_PREFIX + "TimeValue", "%.10g" % singleTimeValue)
            self._logConversion(arrayInfos, unitSystem, SCENE_UNIT_SYSTEM, flipFirstTwoComponents)
            importedNodes.append(modelNode)

        # Simulation meshes can be very large (hundreds of MB), therefore the meshes that were
        # read for populating the arrays table are released as soon as they have been imported.
        # The arrays table remains valid, it does not need the meshes any more.
        self.clearCache()

        self.addLog(_("Imported {count} node(s).").format(count=len(importedNodes)))
        return importedNodes

    def _meshReductionFunction(self, mergeDuplicatePoints, decimationCellCountThreshold,
                               decimationTargetReduction, decimationBoundaryWeight, resampleSpacing=None,
                               roiNode=None, roiPlanes=None, meshName=""):
        """Return a function that reduces the size of the meshes of a file, as requested.

        All the time points of a file use the same function, so that they can share the result of
        the time-consuming decimation if their geometry is the same.

        :param resampleSpacing: resolution of uniform resampling in the length unit of the meshes,
            None to not resample. A resampled mesh is not decimated and it has no duplicate points.
        :param roiNode: ROI to crop the meshes to, None to not crop.
        :param roiPlanes: planes of the ROI in the coordinate system of the meshes.
        :param meshName: name of the meshes, for reporting that one is outside of the ROI.
        """
        decimator = TetrahedralMeshDecimator(decimationTargetReduction, decimationBoundaryWeight, self.addLog)
        resampler = None if resampleSpacing is None else UniformMeshResampler(resampleSpacing, self.addLog)

        def cropToRoi(mesh, cropFunction=self.cropMesh):
            if roiNode is None:
                return mesh
            croppedMesh = cropFunction(mesh, roiPlanes)
            if croppedMesh.GetNumberOfCells() == 0:
                raise ValueError(_("No part of the model {modelName} is inside the ROI {roiName}.").format(
                    modelName=meshName, roiName=roiNode.GetName()))
            self.addLog(_("  Cropped to {roiName}: {before} -> {after} cells").format(
                roiName=roiNode.GetName(), before=mesh.GetNumberOfCells(), after=croppedMesh.GetNumberOfCells()))
            return croppedMesh

        def reduceMesh(mesh):
            if resampler is not None and resampler.canResample(mesh):
                # The result must consist of cubes, so they are not cut, only selected. The mesh is not
                # cut before resampling either, because a cut can create almost flat cells near the ROI
                # boundary, and points inside such cells are not found, which would leave out cubes.
                return cropToRoi(resampler.resample(mesh), self._hexahedraWithCenterInsideFunctions)
            if decimationCellCountThreshold is not None and decimator.canDecimate(mesh):
                # Only tetrahedra can be decimated, but cutting a mesh creates other types of cells.
                # So at this point only the tetrahedra are removed that are outside of the ROI, which
                # also makes the decimation faster, and the mesh is cut after it is decimated.
                meshToDecimate = mesh if roiNode is None else self._cellsNotOutsideFunctions(mesh, roiPlanes)
                if meshToDecimate.GetNumberOfCells() > decimationCellCountThreshold:
                    # The decimated mesh has no duplicate points.
                    return cropToRoi(decimator.decimate(meshToDecimate))
            mesh = cropToRoi(mesh)
            if not mergeDuplicatePoints:
                return mesh
            mergedMesh = self.mergeDuplicatePoints(mesh)
            self.addLog(_("  Merged duplicate points: {before} -> {after}").format(
                before=mesh.GetNumberOfPoints(), after=mergedMesh.GetNumberOfPoints()))
            return mergedMesh

        return reduceMesh

    def _fileArrayQuantities(self, mesh, arrayQuantities):
        """Quantity of each array of a mesh: the one specified by the caller, or else a guess.

        Arrays that the caller did not specify a unit for (for example, arrays that are only
        present in some of the files) get their unit guessed from the array name.
        """
        quantities = {}
        for arrayInfo in self.getArrayInfosFromMesh(mesh):
            quantities[arrayInfo.key] = arrayInfo.simulationUnit.quantity
        if arrayQuantities:
            quantities.update(arrayQuantities)
        return quantities

    def _convertedArrayInfos(self, convertedMesh, quantities):
        """Arrays of a converted mesh, with the quantities that were used for the conversion."""
        arrayInfos = self.getArrayInfosFromMesh(convertedMesh)
        for arrayInfo in arrayInfos:
            arrayInfo.simulationUnit = simulationUnitByQuantity(
                quantities.get(arrayInfo.key, DIMENSIONLESS_QUANTITY))
        return arrayInfos

    @staticmethod
    def _timeIndexValues(timeValues):
        """Sequence index value of each time point: the shortest text that keeps them distinct."""
        for significantDigits in range(10, 17):
            indexValues = ["%.*g" % (significantDigits, timeValue) for timeValue in timeValues]
            if len(set(indexValues)) == len(timeValues):
                return indexValues
        return [repr(timeValue) for timeValue in timeValues]

    @staticmethod
    def _createTimeSequenceNode(nodeName, timeValues):
        """Create a sequence node that can store an item for each of the given time values."""
        sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", nodeName)
        sequenceNode.SetIndexName("time")
        sequenceNode.SetIndexUnit("s")
        # Index values that differ by less than the tolerance refer to the same item. The default
        # tolerance (0.001) is larger than the time step of many simulations.
        timeSteps = [abs(second - first) for first, second in zip(timeValues, timeValues[1:])
                     if second != first]
        if timeSteps:
            sequenceNode.SetNumericIndexValueTolerance(
                min(sequenceNode.GetNumericIndexValueTolerance(), min(timeSteps) * 0.01))
        return sequenceNode

    def _importTimeSeries(self, filePath, nodeName, timeValues, flipFirstTwoComponents, unitSystem,
                          arrayQuantities, reduceMesh):
        """Load each time point of a VTKHDF file into a sequence of models, add a sequence browser.

        :param reduceMesh: function that reduces the size of a mesh, see _meshReductionFunction.
        :return: the proxy model node of the sequence browser.
        """
        # All the time points will be read, the one read for the arrays table is not needed.
        self._meshCache.pop(os.path.normpath(filePath), None)

        sequenceNode = self._createTimeSequenceNode(nodeName, timeValues)
        indexValues = self._timeIndexValues(timeValues)
        try:
            reader = self._createVtkHdfReader(filePath)
            for timePointIndex, timeValue in enumerate(timeValues):
                self.addLog(_("Reading time point {index}/{count} (time: {time:g}s)").format(
                    index=timePointIndex + 1, count=len(timeValues), time=timeValue))
                mesh = reduceMesh(self._readVtkHdfMesh(reader, timeValue, filePath))
                quantities = self._fileArrayQuantities(mesh, arrayQuantities)
                convertedMesh = self.convertMesh(mesh, quantities, flipFirstTwoComponents,
                                                 unitSystem, SCENE_UNIT_SYSTEM)
                arrayInfos = self._convertedArrayInfos(convertedMesh, quantities)

                frameNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLModelNode")
                frameNode.UnRegister(None)  # Prevent memory leak
                self.setModelArrayUnits(frameNode, arrayInfos, SCENE_UNIT_SYSTEM, SCENE_COORDINATE_SYSTEM)
                frameNode.SetAttribute(self.ATTRIBUTE_PREFIX + "SourceFile", filePath)
                # The sequence stores a deep copy of the node it receives. A time point can take
                # up gigabytes of memory, so the mesh is only set after the node has been copied.
                sequenceDataNode = sequenceNode.SetDataNodeAtValue(frameNode, indexValues[timePointIndex])
                sequenceDataNode.SetAndObserveMesh(convertedMesh)
                if timePointIndex == 0:
                    self._logConversion(arrayInfos, unitSystem, SCENE_UNIT_SYSTEM, flipFirstTwoComponents)
            # Setting a data node replaces any item that has the same index value, without an error.
            if sequenceNode.GetNumberOfDataNodes() != len(timeValues):
                raise ValueError(_("Time points of {filePath} do not have distinct time values").format(
                    filePath=filePath))
        except Exception:
            slicer.mrmlScene.RemoveNode(sequenceNode)
            raise

        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", nodeName + " browser")
        browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
        # With this option the proxy node shares the mesh of the selected time point. Otherwise the
        # whole mesh would be copied whenever a different time point is selected.
        browserNode.SetSaveChanges(sequenceNode, True)
        proxyNode = browserNode.GetProxyNode(sequenceNode)
        proxyNode.CreateDefaultDisplayNodes()
        slicer.modules.sequences.setToolBarActiveBrowserNode(browserNode)
        return proxyNode

    def _importImage(self, filePath, nodeName, image, flipFirstTwoComponents, unitSystem, arrayQuantities):
        """Load each point data array of an image into a volume node, in the scene coordinate
        and unit system.

        :return: list of the created volume nodes.
        """
        if image.GetCellData().GetNumberOfArrays():
            self.addLog(_("Warning: cell data arrays of the image are not loaded."))
        quantities = self._fileArrayQuantities(image, arrayQuantities)
        convertedImage = self.convertMesh(image, quantities, flipFirstTwoComponents,
                                          unitSystem, SCENE_UNIT_SYSTEM)
        ijkToRas = self._imageIjkToRasMatrix(convertedImage)
        arrayInfos = self._convertedArrayInfos(convertedImage, quantities)
        voxelArrayInfos = [arrayInfo for arrayInfo in arrayInfos if arrayInfo.location == POINT_LOCATION]
        if not voxelArrayInfos:
            raise ValueError(_("No voxel values found in {filePath}").format(filePath=filePath))
        positionInfos = [arrayInfo for arrayInfo in arrayInfos if arrayInfo.location == POSITION_LOCATION]

        volumeNodes = []
        for arrayInfo in voxelArrayInfos:
            # The geometry is stored in the volume node, the image of a volume node has unit
            # spacing, zero origin, and an extent that starts from 0.
            volumeImage = vtk.vtkImageData()
            volumeImage.SetDimensions(convertedImage.GetDimensions())
            volumeImage.GetPointData().SetScalars(convertedImage.GetPointData().GetArray(arrayInfo.name))
            isScalar = arrayInfo.numberOfComponents == 1
            volumeNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLScalarVolumeNode" if isScalar else "vtkMRMLVectorVolumeNode",
                nodeName if len(voxelArrayInfos) == 1 else nodeName + "_" + arrayInfo.name)
            volumeNode.SetIJKToRASMatrix(ijkToRas)
            volumeNode.SetAndObserveImageData(volumeImage)
            if arrayInfo.numberOfComponents == 3 and arrayInfo.isFloatingPoint:
                volumeNode.SetVoxelVectorType(slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial)
            volumeNode.CreateDefaultDisplayNodes()
            self.setModelArrayUnits(volumeNode, positionInfos + [arrayInfo],
                                    SCENE_UNIT_SYSTEM, SCENE_COORDINATE_SYSTEM)
            volumeNode.SetAttribute(self.ATTRIBUTE_PREFIX + "SourceFile", filePath)
            volumeNodes.append(volumeNode)
        self._logConversion(arrayInfos, unitSystem, SCENE_UNIT_SYSTEM, flipFirstTwoComponents)
        slicer.util.setSliceViewerLayers(background=volumeNodes[0], fit=True)
        return volumeNodes

    @staticmethod
    def fileNameFromNodeName(nodeName):
        """File name (without extension) for a model, safe to use on any file system."""
        fileName = re.sub(r'[\\\\/:*?"<>|]+', "_", nodeName).strip(" .")
        return fileName or "model"

    def exportModels(self, modelNodes, outputDirectory, fileFormatId,
                     coordinateSystem, unitSystem, roiNode=None):
        """Write each model to a separate file in the output folder, named after the model.

        The file extension is determined by the file format and by the mesh of each model: a
        surface mesh and a volumetric mesh are written to different file types by the VTK
        formats (.vtp and .vtu for VTK (XML), for example).

        :param roiNode: markups ROI node to crop the written meshes to, None to not crop.
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
            self.exportModel(modelNode, filePath, coordinateSystem, unitSystem, roiNode)
            filePaths.append(filePath)

        self.addLog(_("Exported {count} model(s) to {outputDirectory}").format(
            count=len(filePaths), outputDirectory=outputDirectory))
        return filePaths

    def exportModel(self, modelNode, filePath, coordinateSystem, unitSystem, roiNode=None):
        """Write a model to file, converting it to the given coordinate and unit system.

        :param roiNode: markups ROI node to crop the written mesh to, None to not crop.
        """
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
        if roiNode is not None:
            # The ROI is compared to the model as it is displayed, so this has to be done before
            # the conversion to the coordinate and unit system of the file.
            croppedMesh = self.cropMesh(mesh, self._roiPlanesInModelCoordinates(modelNode, roiNode))
            if croppedMesh.GetNumberOfCells() == 0:
                raise ValueError(_("No part of the model {modelName} is inside the ROI {roiName}.").format(
                    modelName=modelNode.GetName(), roiName=roiNode.GetName()))
            self.addLog(_("  Cropped to {roiName}: {before} -> {after} cells").format(
                roiName=roiNode.GetName(), before=mesh.GetNumberOfCells(), after=croppedMesh.GetNumberOfCells()))
            mesh = croppedMesh
        convertedMesh = self.convertMesh(mesh, quantities, flipFirstTwoComponents,
                                         modelUnitSystem, unitSystem)
        self.writeMesh(convertedMesh, filePath)
        self._logConversion(arrayInfos, modelUnitSystem, unitSystem, flipFirstTwoComponents)

    @staticmethod
    def _roiPlanes(roiNode, meshToWorld):
        """Planes of the sides of an ROI, negative inside the ROI, for points of a mesh.

        :param meshToWorld: transform from the coordinate system of the mesh to the world, or None.
        """
        roiPlanes = vtk.vtkPlanes()
        roiNode.GetPlanesWorld(roiPlanes)
        planes = []
        for planeIndex in range(roiPlanes.GetNumberOfPlanes()):
            plane = vtk.vtkPlane()
            roiPlanes.GetPlane(planeIndex, plane)
            plane.SetTransform(meshToWorld)
            planes.append(plane)
        return planes

    @staticmethod
    def _roiPlanesInModelCoordinates(modelNode, roiNode):
        """Planes of an ROI for the mesh of a model, which is stored without the transform of the model."""
        modelToWorld = None
        transformNode = modelNode.GetParentTransformNode()
        if transformNode is not None:
            modelToWorld = vtk.vtkGeneralTransform()
            transformNode.GetTransformToWorld(modelToWorld)
            modelToWorld.Update()
        return ImportExportSimulationModelLogic._roiPlanes(roiNode, modelToWorld)

    @staticmethod
    def _roiPlanesInFileCoordinates(roiNode, coordinateSystem, unitSystem, arrayQuantities):
        """Planes of an ROI for a mesh read from a file, which is not yet converted to the scene.

        The conversion must be the same as the conversion of the point coordinates in convertMesh.
        """
        quantity = (arrayQuantities or {}).get((POSITION_LOCATION, POSITION_ARRAY_NAME), LENGTH_QUANTITY)
        scale = unitSystemConversionFactor(
            simulationUnitByQuantity(quantity).lengthExponent, unitSystem, SCENE_UNIT_SYSTEM)
        signs = (1, 1, 1) if coordinateSystem == SCENE_COORDINATE_SYSTEM else COORDINATE_SYSTEM_AXIS_SIGNS
        fileToScene = vtk.vtkTransform()
        fileToScene.Scale(signs[0] * scale, signs[1] * scale, signs[2] * scale)
        return ImportExportSimulationModelLogic._roiPlanes(roiNode, fileToScene)

    @staticmethod
    def _cellsNotOutsideFunctions(mesh, implicitFunctions):
        """Return a tetrahedral mesh without the cells that are completely outside of a function.

        A cell is removed only if a function is positive at all of its points. This keeps every cell
        that has a part inside the region where no function is positive, even if none of the points
        of the cell are in that region, and it may keep some more cells around it.

        :param implicitFunctions: functions that are linear in the coordinates of the mesh.
        :return: tetrahedral mesh, with all the data arrays. The input is not modified.
        """
        tetrahedra = numpy_support.vtk_to_numpy(mesh.GetCells().GetConnectivityArray()).reshape(-1, 4)
        isKept = np.ones(len(tetrahedra), dtype=np.uint8)
        for implicitFunction in implicitFunctions:
            values = ImportExportSimulationModelLogic._functionValues(implicitFunction, mesh.GetPoints().GetData())
            isKept &= (values[tetrahedra] <= 0.0).any(axis=1).astype(np.uint8)
        return ImportExportSimulationModelLogic._meshWithCells(mesh, isKept)

    @staticmethod
    def _functionValues(implicitFunction, positions):
        """Return the values of an implicit function at positions stored in a VTK array, as a numpy array."""
        values = vtk.vtkDoubleArray()
        # Without a transform a plane writes to the output array without allocating it.
        values.SetNumberOfTuples(positions.GetNumberOfTuples())
        implicitFunction.FunctionValue(positions, values)
        return numpy_support.vtk_to_numpy(values)

    @staticmethod
    def _hexahedraWithCenterInsideFunctions(mesh, implicitFunctions):
        """Return a hexahedral mesh with only the cells whose center is where no function is positive.

        :return: hexahedral mesh, with all the data arrays. The input is not modified.
        """
        hexahedra = numpy_support.vtk_to_numpy(mesh.GetCells().GetConnectivityArray()).reshape(-1, 8)
        points = numpy_support.vtk_to_numpy(mesh.GetPoints().GetData()).astype(float)
        centers = numpy_support.numpy_to_vtk(points[hexahedra].mean(axis=1), deep=True)
        isKept = np.ones(len(hexahedra), dtype=np.uint8)
        for implicitFunction in implicitFunctions:
            values = ImportExportSimulationModelLogic._functionValues(implicitFunction, centers)
            isKept &= (values <= 0.0).astype(np.uint8)
        return ImportExportSimulationModelLogic._meshWithCells(mesh, isKept)

    @staticmethod
    def _meshWithCells(mesh, isKept):
        """Return an unstructured grid with the cells of a mesh that are marked in a numpy array."""
        # A shallow copy is used for not adding the temporary array to the input mesh.
        keptArrayName = "_IsKept"
        keptArray = numpy_support.numpy_to_vtk(isKept, deep=True)
        keptArray.SetName(keptArrayName)
        markedMesh = vtk.vtkUnstructuredGrid()
        markedMesh.ShallowCopy(mesh)
        markedMesh.GetCellData().AddArray(keptArray)
        threshold = vtk.vtkThreshold()
        threshold.SetInputData(markedMesh)
        threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS, keptArrayName)
        threshold.SetUpperThreshold(0.5)
        threshold.SetThresholdFunction(vtk.vtkThreshold.THRESHOLD_UPPER)
        threshold.Update()
        keptMesh = threshold.GetOutput()
        keptMesh.GetCellData().RemoveArray(keptArrayName)
        return keptMesh

    @staticmethod
    def cropMesh(mesh, implicitFunctions):
        """Return the part of a mesh where none of the implicit functions is positive.

        The mesh is cut with one function at a time. A clip filter evaluates its function at the
        points of the mesh and interpolates linearly between them, so a single function of a box
        would bevel the cells that contain an edge or a corner of the box, which reduces the volume.
        vtkClipDataSet is not used, because it cuts the wedges in its own output incorrectly, so the
        result of the second cut would already have the wrong volume and bounds.

        Cells that cross the boundary are cut, so a volumetric cell may be replaced by cells of
        other types (tetrahedra, pyramids, wedges, hexahedra), and the faces of neighboring cut cells
        may not match. Cells that are completely inside are not changed. Cell arrays are copied from
        the cell that was cut. At the new points floating-point point arrays are interpolated,
        identifiers and other integers cannot be interpolated, so they are taken from the nearest
        point of the input mesh.

        :param implicitFunctions: functions that are linear in the coordinates of the mesh, to
            have the cut exactly where a function is 0.
        :return: mesh of the same type as the input, which is not modified.
        """
        croppedMesh = mesh
        for implicitFunction in implicitFunctions:
            if isinstance(mesh, vtk.vtkPolyData):
                clipFilter = vtk.vtkClipPolyData()
            else:
                clipFilter = vtk.vtkTableBasedClipDataSet()
            clipFilter.SetInputData(croppedMesh)
            clipFilter.SetClipFunction(implicitFunction)
            clipFilter.InsideOutOn()
            clipFilter.Update()
            croppedMesh = clipFilter.GetOutput()

        pointData = mesh.GetPointData()
        croppedPointData = croppedMesh.GetPointData()
        integerArrayNames = []
        for arrayIndex in range(pointData.GetNumberOfArrays()):
            array = pointData.GetArray(arrayIndex)
            if (array is not None and array.GetName() and array.GetDataType() not in (vtk.VTK_FLOAT, vtk.VTK_DOUBLE)
                    and croppedPointData.GetArray(array.GetName()) is not None):
                integerArrayNames.append(array.GetName())
        if integerArrayNames and croppedMesh.GetNumberOfPoints() > 0:
            nearestPointIds = MeshGeometryReplacer._findNearestPoints(mesh, croppedMesh)
            for name in integerArrayNames:
                numpy_support.vtk_to_numpy(croppedPointData.GetArray(name))[:] = (
                    numpy_support.vtk_to_numpy(pointData.GetArray(name))[nearestPointIds])
                croppedPointData.GetArray(name).Modified()
        return croppedMesh

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
        self.test_ImportVtkHdfTimeSeries()
        self.test_ImportImage()
        self.test_MergeDuplicatePoints()
        self.test_NonVectorArrayConversion()
        self.test_DecimateTetrahedra()
        self.test_ApproximateRanges()
        self.test_ResampleUniformly()
        self.test_CropToRoi()
        self.test_ImportCropToRoi()

    def test_ImportCropToRoi(self):
        """Imported meshes must be cropped at the position that they will have in the scene."""
        self.delayDisplay("Starting import crop to ROI test")

        import tempfile

        def writeMesh(mesh):
            filePath = os.path.join(tempfile.mkdtemp(), "mesh.vtu")
            writer = vtk.vtkXMLUnstructuredGridWriter()
            writer.SetInputData(mesh)
            writer.SetFileName(filePath)
            self.assertTrue(writer.Write())
            return filePath

        # Tetrahedra filling the box [0, 4] x [0, 4] x [0, 4], with arrays that depend on the position
        image = vtk.vtkImageData()
        image.SetDimensions(9, 9, 9)
        image.SetSpacing(0.5, 0.5, 0.5)
        image.AllocateScalars(vtk.VTK_FLOAT, 1)
        tetrahedralize = vtk.vtkDataSetTriangleFilter()
        tetrahedralize.SetInputData(image)
        tetrahedralize.Update()
        mesh = vtk.vtkUnstructuredGrid()
        mesh.DeepCopy(tetrahedralize.GetOutput())
        mesh.GetPointData().Initialize()
        filePoints = numpy_support.vtk_to_numpy(mesh.GetPoints().GetData())
        for name, values in (("Pressure", filePoints[:, 0] + 2.0 * filePoints[:, 1] - filePoints[:, 2]),
                             ("Velocity", filePoints * 3.0),
                             ("NodeID", np.arange(len(filePoints), dtype=np.int32))):
            array = numpy_support.numpy_to_vtk(values, deep=True)
            array.SetName(name)
            mesh.GetPointData().AddArray(array)
        regionId = numpy_support.numpy_to_vtk(np.full(mesh.GetNumberOfCells(), 5, dtype=np.int32), deep=True)
        regionId.SetName("RegionID")
        mesh.GetCellData().AddArray(regionId)
        filePath = writeMesh(mesh)

        def volumeOf(mesh):
            sizeFilter = vtk.vtkCellSizeFilter()
            sizeFilter.SetInputData(mesh)
            sizeFilter.ComputeSumOn()
            sizeFilter.Update()
            return sizeFilter.GetOutput().GetFieldData().GetArray("Volume").GetValue(0)

        def assertBoundsEqual(mesh, expectedBounds):
            np.testing.assert_allclose(mesh.GetBounds(), expectedBounds, atol=1e-3)

        logic = ImportExportSimulationModelLogic()
        roiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsROINode", "roi")

        # The ROI is in the scene (RAS, mm), the file is in LPS and cm, which puts the mesh into
        # [-40, 0] x [-40, 0] x [0, 40]. A wrong conversion would leave nothing in this ROI.
        roiNode.SetCenter(-20.0, -20.0, 20.0)
        roiNode.SetSize(22.0, 17.0, 13.0)
        modelNode = logic.importFiles([filePath], "LPS", "cgs", decimationCellCountThreshold=None, roiNode=roiNode)[0]
        croppedMesh = modelNode.GetMesh()
        assertBoundsEqual(croppedMesh, (-31.0, -9.0, -28.5, -11.5, 13.5, 26.5))
        self.assertAlmostEqual(volumeOf(croppedMesh), 22.0 * 17.0 * 13.0, places=2)
        points = numpy_support.vtk_to_numpy(croppedMesh.GetPoints().GetData())
        np.testing.assert_allclose(
            numpy_support.vtk_to_numpy(croppedMesh.GetPointData().GetArray("Velocity")), points * 3.0, atol=1e-2)
        np.testing.assert_allclose(
            numpy_support.vtk_to_numpy(croppedMesh.GetPointData().GetArray("Pressure")),
            0.1 * (-points[:, 0] / 10.0 - 2.0 * points[:, 1] / 10.0 - points[:, 2] / 10.0), atol=1e-4)
        self.assertEqual(croppedMesh.GetCellData().GetArray("RegionID").GetRange(), (5.0, 5.0))
        self.assertEqual(croppedMesh.GetPointData().GetArray("NodeID").GetDataType(), vtk.VTK_INT)
        self.assertEqual(modelNode.GetAttribute("SimulationModel.Position.Unit"), "mm")

        # A file that is already in the coordinate and unit system of the scene
        roiNode.SetCenter(2.0, 2.0, 2.0)
        roiNode.SetSize(2.2, 1.7, 1.3)
        modelNode = logic.importFiles([filePath], "RAS", "mmgs", decimationCellCountThreshold=None, roiNode=roiNode)[0]
        assertBoundsEqual(modelNode.GetMesh(), (0.9, 3.1, 1.15, 2.85, 1.35, 2.65))

        # The position of the mesh depends on the quantity selected for the point coordinates.
        roiNode.SetCenter(-2.0, -2.0, 2.0)
        roiNode.SetSize(2.0, 2.0, 2.0)
        modelNode = logic.importFiles(
            [filePath], "LPS", "cgs", {(POSITION_LOCATION, POSITION_ARRAY_NAME): DIMENSIONLESS_QUANTITY},
            decimationCellCountThreshold=None, roiNode=roiNode)[0]
        assertBoundsEqual(modelNode.GetMesh(), (-3.0, -1.0, -3.0, -1.0, 1.0, 3.0))

        # The ROI must be used as it is displayed: here it is rotated by a transform.
        rotation = vtk.vtkTransform()
        rotation.Translate(-20.0, -20.0, 20.0)
        rotation.RotateZ(45.0)
        rotation.Translate(20.0, 20.0, -20.0)
        transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode")
        transformNode.SetMatrixTransformToParent(rotation.GetMatrix())
        roiNode.SetAndObserveTransformNodeID(transformNode.GetID())
        roiNode.SetCenter(-20.0, -20.0, 20.0)
        roiNode.SetSize(20.0, 20.0, 20.0)
        modelNode = logic.importFiles([filePath], "LPS", "cgs", decimationCellCountThreshold=None, roiNode=roiNode)[0]
        halfDiagonal = 10.0 * np.sqrt(2.0)
        assertBoundsEqual(modelNode.GetMesh(), (-20.0 - halfDiagonal, -20.0 + halfDiagonal,
                                                -20.0 - halfDiagonal, -20.0 + halfDiagonal, 10.0, 30.0))
        self.assertAlmostEqual(volumeOf(modelNode.GetMesh()), 8000.0, places=2)
        roiNode.SetAndObserveTransformNodeID(None)

        # A resampled mesh must consist of cubes, only inside of the ROI. Sides of this ROI are at
        # points of the mesh, where a cut would create almost flat cells.
        modelNode = logic.importFiles([filePath], "LPS", "cgs", resampleSpacing=5.0, roiNode=roiNode)[0]
        resampledMesh = modelNode.GetMesh()
        self.assertEqual(resampledMesh.GetNumberOfCells(), 4 * 4 * 4)
        self.assertEqual(resampledMesh.GetNumberOfPoints(), 5 * 5 * 5)
        self.assertTrue(resampledMesh.IsHomogeneous())
        self.assertEqual(resampledMesh.GetCellType(0), vtk.VTK_HEXAHEDRON)
        assertBoundsEqual(resampledMesh, (-30.0, -10.0, -30.0, -10.0, 10.0, 30.0))
        # Values must be the ones of the original mesh at each corner of each cube.
        points = numpy_support.vtk_to_numpy(resampledMesh.GetPoints().GetData())
        np.testing.assert_allclose(
            numpy_support.vtk_to_numpy(resampledMesh.GetPointData().GetArray("Velocity")), points * 3.0, atol=1e-2)
        self.assertEqual(resampledMesh.GetCellData().GetArray("RegionID").GetRange(), (5.0, 5.0))
        self.assertIsNone(resampledMesh.GetCellData().GetArray("_IsKept"))
        # A cube is kept if its center is in the ROI, so an ROI that ends inside of a cube includes
        # the cube if it contains the center, and the result can extend outside of the ROI.
        roiNode.SetCenter(-20.0, -20.0, 20.0)
        roiNode.SetSize(16.0, 20.0, 20.0)
        modelNode = logic.importFiles([filePath], "LPS", "cgs", resampleSpacing=5.0, roiNode=roiNode)[0]
        assertBoundsEqual(modelNode.GetMesh(), (-30.0, -10.0, -30.0, -10.0, 10.0, 30.0))
        roiNode.SetSize(14.0, 20.0, 20.0)
        modelNode = logic.importFiles([filePath], "LPS", "cgs", resampleSpacing=5.0, roiNode=roiNode)[0]
        assertBoundsEqual(modelNode.GetMesh(), (-25.0, -15.0, -30.0, -10.0, 10.0, 30.0))

        # Removing the cells outside of the ROI must keep a cell that the ROI is completely inside of,
        # even though none of its points are in the ROI.
        tetrahedronPoints = vtk.vtkPoints()
        for point in ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 0.0, 10.0)):
            tetrahedronPoints.InsertNextPoint(point)
        tetrahedron = vtk.vtkUnstructuredGrid()
        tetrahedron.SetPoints(tetrahedronPoints)
        tetrahedronIds = vtk.vtkIdList()
        for pointIndex in range(4):
            tetrahedronIds.InsertNextId(pointIndex)
        tetrahedron.InsertNextCell(vtk.VTK_TETRA, tetrahedronIds)
        roiNode.SetCenter(2.0, 2.0, 2.0)
        roiNode.SetSize(0.5, 0.5, 0.5)
        roiPlanes = logic._roiPlanes(roiNode, None)
        self.assertEqual(logic._cellsNotOutsideFunctions(tetrahedron, roiPlanes).GetNumberOfCells(), 1)
        self.assertAlmostEqual(volumeOf(logic.cropMesh(tetrahedron, roiPlanes)), 0.125, places=5)
        roiNode.SetCenter(100.0, 100.0, 100.0)
        self.assertEqual(
            logic._cellsNotOutsideFunctions(tetrahedron, logic._roiPlanes(roiNode, None)).GetNumberOfCells(), 0)

        # A mesh that would be decimated must still be decimated, because the cut comes after that.
        roiNode.SetCenter(-20.0, -20.0, 20.0)
        roiNode.SetSize(22.0, 22.0, 22.0)
        undecimatedCellCount = logic.importFiles(
            [filePath], "LPS", "cgs", decimationCellCountThreshold=None, roiNode=roiNode)[0].GetMesh().GetNumberOfCells()
        logMessages = []
        logic.logCallback = logMessages.append
        modelNode = logic.importFiles([filePath], "LPS", "cgs", decimationCellCountThreshold=0,
                                      decimationTargetReduction=0.5, roiNode=roiNode)[0]
        logic.logCallback = None
        self.assertTrue(any("Decimated" in message for message in logMessages), logMessages)
        self.assertLess(modelNode.GetMesh().GetNumberOfCells(), undecimatedCellCount)
        bounds = np.array(modelNode.GetMesh().GetBounds())
        roiBounds = np.array((-31.0, -9.0, -31.0, -9.0, 9.0, 31.0))
        self.assertTrue(np.all(bounds[0::2] >= roiBounds[0::2] - 1e-3) and np.all(bounds[1::2] <= roiBounds[1::2] + 1e-3),
                        bounds)
        self.assertAlmostEqual(volumeOf(modelNode.GetMesh()) / 22.0 ** 3, 1.0, delta=0.05)
        # Whether a mesh is decimated depends on the number of cells near the ROI.
        logMessages = []
        logic.logCallback = logMessages.append
        logic.importFiles([filePath], "LPS", "cgs", decimationCellCountThreshold=mesh.GetNumberOfCells() - 1,
                          roiNode=roiNode)
        logic.logCallback = None
        self.assertFalse(any("Decimated" in message for message in logMessages), logMessages)

        # A surface mesh must remain a surface mesh.
        cube = vtk.vtkCubeSource()
        cube.SetBounds(0.0, 4.0, 0.0, 4.0, 0.0, 4.0)
        triangulate = vtk.vtkTriangleFilter()
        triangulate.SetInputConnection(cube.GetOutputPort())
        triangulate.Update()
        surfaceFilePath = os.path.join(tempfile.mkdtemp(), "surface.vtp")
        surfaceWriter = vtk.vtkXMLPolyDataWriter()
        surfaceWriter.SetInputData(triangulate.GetOutput())
        surfaceWriter.SetFileName(surfaceFilePath)
        self.assertTrue(surfaceWriter.Write())
        roiNode.SetCenter(0.0, -20.0, 20.0)
        roiNode.SetSize(20.0, 20.0, 20.0)
        surfaceMesh = logic.importFiles([surfaceFilePath], "LPS", "cgs", roiNode=roiNode)[0].GetMesh()
        self.assertIsInstance(surfaceMesh, vtk.vtkPolyData)
        assertBoundsEqual(surfaceMesh, (0.0, 0.0, -30.0, -10.0, 10.0, 30.0))

        # Each time point of a time series must be cropped.
        timeSource = vtk.vtkTimeSourceExample()
        timeSource.SetXAmplitude(5.0)
        timeSource.UpdateInformation()
        timeSeriesFilePath = os.path.join(tempfile.mkdtemp(), "timeSeries.vtkhdf5")
        timeSeriesWriter = vtk.vtkHDFWriter()
        timeSeriesWriter.SetInputConnection(timeSource.GetOutputPort())
        timeSeriesWriter.SetFileName(timeSeriesFilePath)
        timeSeriesWriter.SetWriteAllTimeSteps(True)
        self.assertTrue(timeSeriesWriter.Write())
        timeValues = logic.getVtkHdfTimeValues(timeSeriesFilePath)
        lastMesh = logic.readMesh(timeSeriesFilePath)
        fileBounds = lastMesh.GetBounds()
        # The ROI contains the whole range of positions along the first two axes, and half of the third.
        sceneMiddleZ = 10.0 * (fileBounds[4] + fileBounds[5]) / 2.0
        sceneHeight = 10.0 * (fileBounds[5] - fileBounds[4])
        roiNode.SetCenter(0.0, 0.0, sceneMiddleZ)
        roiNode.SetSize(1000.0, 1000.0, sceneHeight / 2.0)
        proxyNode = logic.importFiles([timeSeriesFilePath], "LPS", "cgs", roiNode=roiNode)[0]
        sequenceNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(proxyNode).GetMasterSequenceNode()
        self.assertEqual(sequenceNode.GetNumberOfDataNodes(), len(timeValues))
        for index in range(sequenceNode.GetNumberOfDataNodes()):
            frameBounds = sequenceNode.GetNthDataNode(index).GetMesh().GetBounds()
            self.assertAlmostEqual(frameBounds[4], sceneMiddleZ - sceneHeight / 4.0, places=3)
            self.assertAlmostEqual(frameBounds[5], sceneMiddleZ + sceneHeight / 4.0, places=3)

        # A mesh that is completely outside of the ROI must be reported, and nothing must be left
        # in the scene, also when it is a time series.
        roiNode.SetCenter(5000.0, 5000.0, 5000.0)
        roiNode.SetSize(1.0, 1.0, 1.0)
        for outsideFilePath in (filePath, timeSeriesFilePath):
            numberOfNodes = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLModelNode")
            numberOfSequenceNodes = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSequenceNode")
            with self.assertRaises(ValueError):
                logic.importFiles([outsideFilePath], "LPS", "cgs", roiNode=roiNode)
            self.assertEqual(slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLModelNode"), numberOfNodes)
            self.assertEqual(slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSequenceNode"), numberOfSequenceNodes)
        logic.clearCache()

        # An image is not cropped, and this must be reported.
        imageFilePath = os.path.join(tempfile.mkdtemp(), "image.vti")
        imageWriter = vtk.vtkXMLImageDataWriter()
        imageWriter.SetInputData(image)
        imageWriter.SetFileName(imageFilePath)
        self.assertTrue(imageWriter.Write())
        logMessages = []
        logic.logCallback = logMessages.append
        volumeNode = logic.importFiles([imageFilePath], "LPS", "cgs", roiNode=roiNode)[0]
        logic.logCallback = None
        self.assertEqual(volumeNode.GetImageData().GetDimensions(), (9, 9, 9))
        self.assertTrue(any("not cropped" in message for message in logMessages), logMessages)

        # Without an ROI the whole mesh must be imported.
        modelNode = logic.importFiles([filePath], "LPS", "cgs", decimationCellCountThreshold=None)[0]
        self.assertEqual(modelNode.GetMesh().GetNumberOfCells(), mesh.GetNumberOfCells())

        # The module widget must pass the selected ROI to the import.
        widget = slicer.util.getModuleWidget("ImportExportSimulationModel")
        self.assertEqual(widget.ui.importCropRoiNodeComboBox.nodeTypes, ("vtkMRMLMarkupsROINode",))
        roiNode.SetCenter(-20.0, -20.0, 20.0)
        roiNode.SetSize(20.0, 20.0, 20.0)
        widget.ui.importCropRoiNodeComboBox.setCurrentNode(roiNode)
        # The test must not change the import options that the user has saved in the settings.
        widget._updatingGui = True
        try:
            coordinateSystem = widget.inputCoordinateSystem
            unitSystem = widget.inputUnitSystem
            decimate = widget.ui.decimateCheckBox.checked
            resample = widget.ui.resampleCheckBox.checked
            widget._setComboBoxValue(widget.ui.inputCoordinateSystemComboBox, "LPS")
            widget._setComboBoxValue(widget.ui.inputUnitSystemComboBox, "cgs")
            widget.ui.decimateCheckBox.checked = False
            widget.ui.resampleCheckBox.checked = False
            widget.addInputFiles([filePath])
            widget.onImportButton()
        finally:
            widget.ui.inputFilesListWidget.clear()
            widget._updateImportTable()
            widget._setComboBoxValue(widget.ui.inputCoordinateSystemComboBox, coordinateSystem)
            widget._setComboBoxValue(widget.ui.inputUnitSystemComboBox, unitSystem)
            widget.ui.decimateCheckBox.checked = decimate
            widget.ui.resampleCheckBox.checked = resample
            widget.ui.importCropRoiNodeComboBox.setCurrentNode(None)
            widget._updatingGui = False
        models = slicer.util.getNodesByClass("vtkMRMLModelNode")
        importedMesh = [node for node in models if node.GetName() == "mesh"][-1].GetMesh()
        assertBoundsEqual(importedMesh, (-30.0, -10.0, -30.0, -10.0, 10.0, 30.0))

        self.delayDisplay("Import crop to ROI test passed")

    def test_CropToRoi(self):
        """Exported meshes must be cut at the ROI, as it is displayed, keeping the data arrays."""
        self.delayDisplay("Starting crop to ROI test")

        import tempfile

        def addArrays(mesh):
            """Add arrays that are linear functions of the position."""
            points = numpy_support.vtk_to_numpy(mesh.GetPoints().GetData())
            for name, values in (("Pressure", points[:, 0] + 2.0 * points[:, 1] - points[:, 2]),
                                 ("Velocity", points * 3.0),
                                 ("NodeID", np.arange(len(points), dtype=np.int32))):
                array = numpy_support.numpy_to_vtk(values, deep=True)
                array.SetName(name)
                mesh.GetPointData().AddArray(array)
            regionId = numpy_support.numpy_to_vtk(np.full(mesh.GetNumberOfCells(), 5, dtype=np.int32), deep=True)
            regionId.SetName("RegionID")
            mesh.GetCellData().AddArray(regionId)
            return mesh

        # Tetrahedra filling the box [0, 4] x [0, 4] x [0, 4]
        image = vtk.vtkImageData()
        image.SetDimensions(9, 9, 9)
        image.SetSpacing(0.5, 0.5, 0.5)
        image.AllocateScalars(vtk.VTK_FLOAT, 1)
        tetrahedralize = vtk.vtkDataSetTriangleFilter()
        tetrahedralize.SetInputData(image)
        tetrahedralize.Update()
        volumetricMesh = vtk.vtkUnstructuredGrid()
        volumetricMesh.DeepCopy(tetrahedralize.GetOutput())
        volumetricMesh.GetPointData().Initialize()
        addArrays(volumetricMesh)
        numberOfCells = volumetricMesh.GetNumberOfCells()

        def volumeOf(mesh):
            sizeFilter = vtk.vtkCellSizeFilter()
            sizeFilter.SetInputData(mesh)
            sizeFilter.ComputeSumOn()
            sizeFilter.Update()
            return sizeFilter.GetOutput().GetFieldData().GetArray("Volume").GetValue(0)

        def readMesh(filePath):
            return ImportExportSimulationModelLogic.readMesh(filePath)

        def assertBoundsEqual(mesh, expectedBounds):
            np.testing.assert_allclose(mesh.GetBounds(), expectedBounds, atol=1e-4)

        logic = ImportExportSimulationModelLogic()
        outputDirectory = tempfile.mkdtemp()
        filePath = os.path.join(outputDirectory, "cropped.vtu")

        modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "volumetric")
        modelNode.SetAndObserveMesh(volumetricMesh)
        roiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsROINode", "roi")
        roiNode.SetCenter(2.0, 2.0, 2.0)
        roiNode.SetSize(2.0, 2.0, 2.0)

        # The mesh must be cut at the ROI, and the mesh in the scene must not change.
        logic.exportModel(modelNode, filePath, "RAS", "mmgs", roiNode)
        croppedMesh = readMesh(filePath)
        self.assertIsInstance(croppedMesh, vtk.vtkUnstructuredGrid)
        assertBoundsEqual(croppedMesh, (1.0, 3.0, 1.0, 3.0, 1.0, 3.0))
        self.assertAlmostEqual(volumeOf(croppedMesh), 8.0, places=4)
        self.assertEqual(modelNode.GetMesh().GetNumberOfCells(), numberOfCells)

        # This ROI cuts cells: their cut point values must be correct.
        roiNode.SetCenter(2.0, 2.0, 2.0)
        roiNode.SetSize(2.2, 1.7, 1.3)
        logic.exportModel(modelNode, filePath, "RAS", "mmgs", roiNode)
        croppedMesh = readMesh(filePath)
        assertBoundsEqual(croppedMesh, (0.9, 3.1, 1.15, 2.85, 1.35, 2.65))
        self.assertAlmostEqual(volumeOf(croppedMesh), 2.2 * 1.7 * 1.3, places=4)
        points = numpy_support.vtk_to_numpy(croppedMesh.GetPoints().GetData())
        np.testing.assert_allclose(
            numpy_support.vtk_to_numpy(croppedMesh.GetPointData().GetArray("Pressure")),
            points[:, 0] + 2.0 * points[:, 1] - points[:, 2], atol=1e-4)
        np.testing.assert_allclose(
            numpy_support.vtk_to_numpy(croppedMesh.GetPointData().GetArray("Velocity")), points * 3.0, atol=1e-4)
        self.assertEqual(croppedMesh.GetCellData().GetArray("RegionID").GetRange(), (5.0, 5.0))
        # Integers must not be interpolated: each one is the identifier of the nearest input point.
        nodeIds = croppedMesh.GetPointData().GetArray("NodeID")
        self.assertEqual(nodeIds.GetDataType(), vtk.VTK_INT)
        inputPoints = numpy_support.vtk_to_numpy(volumetricMesh.GetPoints().GetData())
        distances = np.linalg.norm(inputPoints[numpy_support.vtk_to_numpy(nodeIds)] - points, axis=1)
        self.assertLessEqual(distances.max(), 0.5 * np.sqrt(3.0) / 2.0 + 1e-4)
        self.assertLess(
            np.count_nonzero(~np.isin(numpy_support.vtk_to_numpy(nodeIds),
                                      numpy_support.vtk_to_numpy(volumetricMesh.GetPointData().GetArray("NodeID")))), 1)

        # The written mesh must be converted after cropping.
        logic.exportModel(modelNode, filePath, "LPS", "cgs", roiNode)
        assertBoundsEqual(readMesh(filePath), (-0.31, -0.09, -0.285, -0.115, 0.135, 0.265))

        # The ROI must be used as it is displayed: here it is rotated by a transform.
        roiNode.SetSize(2.0, 2.0, 2.0)
        rotation = vtk.vtkTransform()
        rotation.Translate(2.0, 2.0, 2.0)
        rotation.RotateZ(45.0)
        rotation.Translate(-2.0, -2.0, -2.0)
        roiTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode")
        roiTransformNode.SetMatrixTransformToParent(rotation.GetMatrix())
        roiNode.SetAndObserveTransformNodeID(roiTransformNode.GetID())
        logic.exportModel(modelNode, filePath, "RAS", "mmgs", roiNode)
        croppedMesh = readMesh(filePath)
        halfDiagonal = np.sqrt(2.0)
        assertBoundsEqual(croppedMesh, (2.0 - halfDiagonal, 2.0 + halfDiagonal,
                                        2.0 - halfDiagonal, 2.0 + halfDiagonal, 1.0, 3.0))
        self.assertAlmostEqual(volumeOf(croppedMesh), 8.0, places=4)
        roiNode.SetAndObserveTransformNodeID(None)

        # The model must be used as it is displayed, but the mesh is written without its transform.
        modelTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode")
        translation = vtk.vtkTransform()
        translation.Translate(10.0, 0.0, 0.0)
        modelTransformNode.SetMatrixTransformToParent(translation.GetMatrix())
        modelNode.SetAndObserveTransformNodeID(modelTransformNode.GetID())
        roiNode.SetCenter(12.0, 2.0, 2.0)
        logic.exportModel(modelNode, filePath, "RAS", "mmgs", roiNode)
        assertBoundsEqual(readMesh(filePath), (1.0, 3.0, 1.0, 3.0, 1.0, 3.0))
        modelNode.SetAndObserveTransformNodeID(None)

        # Meshes of other cell types must be cut as well.
        hexahedralMesh = UniformMeshResampler(1.0).resample(volumetricMesh)
        hexahedralModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "hexahedral")
        hexahedralModelNode.SetAndObserveMesh(hexahedralMesh)
        roiNode.SetCenter(2.0, 2.0, 2.0)
        roiNode.SetSize(1.5, 2.0, 2.5)
        logic.exportModel(hexahedralModelNode, filePath, "RAS", "mmgs", roiNode)
        croppedMesh = readMesh(filePath)
        assertBoundsEqual(croppedMesh, (1.25, 2.75, 1.0, 3.0, 0.75, 3.25))
        self.assertAlmostEqual(volumeOf(croppedMesh), 1.5 * 2.0 * 2.5, places=4)

        # A surface mesh must remain a surface mesh, with all its data arrays.
        cube = vtk.vtkCubeSource()
        cube.SetBounds(0.0, 4.0, 0.0, 4.0, 0.0, 4.0)
        triangulate = vtk.vtkTriangleFilter()
        triangulate.SetInputConnection(cube.GetOutputPort())
        triangulate.Update()
        surfaceMesh = vtk.vtkPolyData()
        surfaceMesh.DeepCopy(triangulate.GetOutput())
        surfaceMesh.GetPointData().Initialize()
        surfaceMesh.GetCellData().Initialize()
        addArrays(surfaceMesh)
        surfaceModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "surface")
        surfaceModelNode.SetAndObservePolyData(surfaceMesh)
        roiNode.SetCenter(0.0, 2.0, 2.0)
        roiNode.SetSize(2.0, 2.0, 2.0)
        filePaths = logic.exportModels([surfaceModelNode], outputDirectory, "vtkxml", "RAS", "mmgs", roiNode)
        self.assertEqual(os.path.splitext(filePaths[0])[1], ".vtp")
        croppedMesh = readMesh(filePaths[0])
        self.assertIsInstance(croppedMesh, vtk.vtkPolyData)
        # The ROI only reaches the side of the cube at x=0, where it cuts out a 2 x 2 square.
        assertBoundsEqual(croppedMesh, (0.0, 0.0, 1.0, 3.0, 1.0, 3.0))
        massProperties = vtk.vtkMassProperties()
        massProperties.SetInputData(croppedMesh)
        massProperties.Update()
        self.assertAlmostEqual(massProperties.GetSurfaceArea(), 4.0, places=4)
        self.assertEqual(croppedMesh.GetCellData().GetArray("RegionID").GetRange(), (5.0, 5.0))
        self.assertEqual(croppedMesh.GetPointData().GetArray("NodeID").GetDataType(), vtk.VTK_INT)
        points = numpy_support.vtk_to_numpy(croppedMesh.GetPoints().GetData())
        np.testing.assert_allclose(
            numpy_support.vtk_to_numpy(croppedMesh.GetPointData().GetArray("Pressure")),
            points[:, 0] + 2.0 * points[:, 1] - points[:, 2], atol=1e-4)

        # A model that is completely outside of the ROI must be reported, not written empty.
        roiNode.SetCenter(100.0, 100.0, 100.0)
        emptyFilePath = os.path.join(outputDirectory, "empty.vtu")
        with self.assertRaises(ValueError):
            logic.exportModel(modelNode, emptyFilePath, "RAS", "mmgs", roiNode)
        self.assertFalse(os.path.exists(emptyFilePath))

        # Without an ROI the whole mesh must be written.
        logic.exportModel(modelNode, filePath, "RAS", "mmgs")
        self.assertEqual(readMesh(filePath).GetNumberOfCells(), numberOfCells)

        # The module widget must pass the selected ROI to the export.
        widget = slicer.util.getModuleWidget("ImportExportSimulationModel")
        self.assertEqual(widget.ui.exportCropRoiNodeComboBox.nodeTypes, ("vtkMRMLMarkupsROINode",))
        widget.ui.exportCropRoiNodeComboBox.setCurrentNode(roiNode)
        self.assertEqual(widget.ui.exportCropRoiNodeComboBox.currentNode(), roiNode)
        roiNode.SetCenter(2.0, 2.0, 2.0)
        roiNode.SetSize(2.0, 2.0, 2.0)
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        itemIds = vtk.vtkIdList()
        itemIds.InsertNextId(subjectHierarchyNode.GetItemByDataNode(modelNode))
        widget.ui.exportModelTreeView.setCurrentItems(itemIds)
        # The test must not change the export options that the user has saved in the settings.
        widget._updatingGui = True
        try:
            outputFolder = widget.ui.outputFolderPathLineEdit.currentPath
            coordinateSystem = widget.outputCoordinateSystem
            unitSystem = widget.outputUnitSystem
            fileFormat = widget.outputFileFormat
            widget.ui.outputFolderPathLineEdit.currentPath = outputDirectory
            widget._setComboBoxValue(widget.ui.outputCoordinateSystemComboBox, "RAS")
            widget._setComboBoxValue(widget.ui.outputUnitSystemComboBox, "mmgs")
            widget._setComboBoxValue(widget.ui.outputFileFormatComboBox, "vtkxml")
            widget.onExportButton()
        finally:
            widget.ui.outputFolderPathLineEdit.currentPath = outputFolder
            widget._setComboBoxValue(widget.ui.outputCoordinateSystemComboBox, coordinateSystem)
            widget._setComboBoxValue(widget.ui.outputUnitSystemComboBox, unitSystem)
            widget._setComboBoxValue(widget.ui.outputFileFormatComboBox, fileFormat)
            widget.ui.exportCropRoiNodeComboBox.setCurrentNode(None)
            widget._updatingGui = False
        assertBoundsEqual(readMesh(os.path.join(outputDirectory, "volumetric.vtu")),
                          (1.0, 3.0, 1.0, 3.0, 1.0, 3.0))

        self.delayDisplay("Crop to ROI test passed")

    def test_ResampleUniformly(self):
        """Resampling must produce uniform cubes, preserve the volume, and transfer the data arrays."""
        self.delayDisplay("Starting uniform resampling test")

        import tempfile

        def createMesh(cornerOffset, dimension=9, cellSize=0.5):
            """Tetrahedra filling a box, with arrays that are linear functions of the position."""
            image = vtk.vtkImageData()
            image.SetDimensions(dimension, dimension, dimension)
            image.SetSpacing(cellSize, cellSize, cellSize)
            image.SetOrigin(cornerOffset, cornerOffset, cornerOffset)
            image.AllocateScalars(vtk.VTK_FLOAT, 1)
            tetrahedralize = vtk.vtkDataSetTriangleFilter()
            tetrahedralize.SetInputData(image)
            tetrahedralize.Update()
            mesh = vtk.vtkUnstructuredGrid()
            mesh.DeepCopy(tetrahedralize.GetOutput())
            mesh.GetPointData().Initialize()
            points = numpy_support.vtk_to_numpy(mesh.GetPoints().GetData())
            for name, values in (("Pressure", points[:, 0] + 2.0 * points[:, 1] - points[:, 2]),
                                 ("Velocity", points * 3.0),
                                 ("NodeID", np.arange(len(points), dtype=np.int32))):
                array = numpy_support.numpy_to_vtk(values, deep=True)
                array.SetName(name)
                mesh.GetPointData().AddArray(array)
            regionId = numpy_support.numpy_to_vtk(np.full(mesh.GetNumberOfCells(), 5, dtype=np.int32), deep=True)
            regionId.SetName("RegionID")
            mesh.GetCellData().AddArray(regionId)
            return mesh

        # A box of size 4, not aligned with the grid: the centers of 4 x 4 x 4 cubes are inside.
        mesh = createMesh(0.3)
        self.assertTrue(UniformMeshResampler.canResample(mesh))
        resampler = UniformMeshResampler(1.0)
        resampledMesh = resampler.resample(mesh)
        self.assertEqual(resampledMesh.GetNumberOfCells(), 4 * 4 * 4)
        self.assertEqual(resampledMesh.GetNumberOfPoints(), 5 * 5 * 5)
        self.assertTrue(resampledMesh.IsHomogeneous())
        self.assertEqual(resampledMesh.GetCellType(0), vtk.VTK_HEXAHEDRON)
        self.assertEqual(resampledMesh.GetBounds(), (0.0, 4.0, 0.0, 4.0, 0.0, 4.0))
        # Cell points must be in the order of a hexahedron, which results in a positive volume.
        for cellId in range(resampledMesh.GetNumberOfCells()):
            self.assertAlmostEqual(vtk.vtkMeshQuality.HexVolume(resampledMesh.GetCell(cellId)), 1.0)

        # Inside the mesh the interpolation of a linear function must be exact.
        points = numpy_support.vtk_to_numpy(resampledMesh.GetPoints().GetData())
        pressure = numpy_support.vtk_to_numpy(resampledMesh.GetPointData().GetArray("Pressure"))
        velocity = numpy_support.vtk_to_numpy(resampledMesh.GetPointData().GetArray("Velocity"))
        isInside = np.all((points > 0.3) & (points < 4.3), axis=1)
        self.assertEqual(int(isInside.sum()), 4 * 4 * 4)
        np.testing.assert_allclose(pressure[isInside], (points[:, 0] + 2.0 * points[:, 1] - points[:, 2])[isInside],
                                   atol=1e-4)
        np.testing.assert_allclose(velocity[isInside], (points * 3.0)[isInside], atol=1e-4)
        # Corners outside of the mesh must get the value at the closest position of the mesh.
        closestPoints = np.clip(points, 0.3, 4.3)
        np.testing.assert_allclose(pressure, closestPoints[:, 0] + 2.0 * closestPoints[:, 1] - closestPoints[:, 2],
                                   atol=1e-4)
        # Integers must not be interpolated, and all the arrays must be present.
        self.assertEqual(resampledMesh.GetPointData().GetArray("NodeID").GetDataType(), vtk.VTK_INT)
        self.assertEqual(resampledMesh.GetCellData().GetArray("RegionID").GetRange(), (5.0, 5.0))

        # Interpolation must not extrapolate: values must remain in the range of the input.
        self.assertGreaterEqual(resampler._interpolationWeights.min(), 0.0)
        self.assertLessEqual(resampler._interpolationWeights.max(), 1.0 + 1e-9)
        np.testing.assert_allclose(resampler._interpolationWeights.sum(axis=1), 1.0)
        inputRange = mesh.GetPointData().GetArray("Pressure").GetRange()
        self.assertGreaterEqual(pressure.min(), inputRange[0] - 1e-4)
        self.assertLessEqual(pressure.max(), inputRange[1] + 1e-4)

        # The weights of outside points must belong to the closest cell, also if the locator has
        # to examine many cells. The box is the same as above, but it has many more cells.
        fineMesh = createMesh(0.3, dimension=41, cellSize=0.1)
        fineResampled = UniformMeshResampler(1.0).resample(fineMesh)
        finePoints = numpy_support.vtk_to_numpy(fineResampled.GetPoints().GetData())
        fineClosestPoints = np.clip(finePoints, 0.3, 4.3)
        np.testing.assert_allclose(
            numpy_support.vtk_to_numpy(fineResampled.GetPointData().GetArray("Pressure")),
            fineClosestPoints[:, 0] + 2.0 * fineClosestPoints[:, 1] - fineClosestPoints[:, 2], atol=1e-3)

        # The result must be repeatable: multi-threaded probing leaves random points at 0.
        for repeat in range(20):
            repeatedMesh = UniformMeshResampler(1.0).resample(mesh)
            np.testing.assert_array_equal(
                numpy_support.vtk_to_numpy(repeatedMesh.GetPointData().GetArray("Pressure")), pressure)

        # Time points with the same geometry share the result, and a moved mesh uses the same grid.
        resampler.resample(mesh)
        self.assertEqual(resampler.numberOfResamplings, 1)
        movedMesh = resampler.resample(createMesh(1.3))
        self.assertEqual(resampler.numberOfResamplings, 2)
        self.assertEqual(movedMesh.GetBounds(), (1.0, 5.0, 1.0, 5.0, 1.0, 5.0))

        # The resolution is rejected if the result would be empty or the grid would be too large.
        with self.assertRaises(ValueError):
            UniformMeshResampler(100.0).resample(createMesh(0.3, dimension=2))
        with self.assertRaises(ValueError):
            UniformMeshResampler(0.001).resample(mesh)

        # Surface meshes cannot be resampled. Meshes of other cell types can be.
        cube = vtk.vtkCubeSource()
        cube.Update()
        self.assertFalse(UniformMeshResampler.canResample(cube.GetOutput()))
        appendFilter = vtk.vtkAppendFilter()
        appendFilter.SetInputData(cube.GetOutput())
        appendFilter.Update()
        self.assertFalse(UniformMeshResampler.canResample(appendFilter.GetOutput()))
        hexahedralMesh = UniformMeshResampler(0.5).resample(resampledMesh)
        self.assertEqual(hexahedralMesh.GetNumberOfCells(), 8 * 8 * 8)
        hexahedralPoints = numpy_support.vtk_to_numpy(hexahedralMesh.GetPoints().GetData())
        isInterior = np.all((hexahedralPoints >= 1.0) & (hexahedralPoints <= 4.0), axis=1)
        self.assertGreater(int(isInterior.sum()), 0)
        hexahedralPressure = numpy_support.vtk_to_numpy(hexahedralMesh.GetPointData().GetArray("Pressure"))
        np.testing.assert_allclose(
            hexahedralPressure[isInterior],
            (hexahedralPoints[:, 0] + 2.0 * hexahedralPoints[:, 1] - hexahedralPoints[:, 2])[isInterior], atol=1e-4)

        # The resolution is specified in mm, whatever the unit of the file is. Resampling replaces
        # decimation: the threshold would decimate this mesh.
        filePath = os.path.join(tempfile.mkdtemp(), "mesh.vtu")
        writer = vtk.vtkXMLUnstructuredGridWriter()
        writer.SetInputData(mesh)
        writer.SetFileName(filePath)
        self.assertTrue(writer.Write())
        logic = ImportExportSimulationModelLogic()
        modelNode = logic.importFiles([filePath], "LPS", "cgs", decimationCellCountThreshold=0, resampleSpacing=5.0)[0]
        self.assertEqual(modelNode.GetMesh().GetNumberOfCells(), 8 * 8 * 8)
        self.assertEqual(modelNode.GetMesh().GetCellType(0), vtk.VTK_HEXAHEDRON)
        bounds = modelNode.GetMesh().GetBounds()
        self.assertAlmostEqual(bounds[1] - bounds[0], 40.0, places=4)
        self.assertAlmostEqual(modelNode.GetMesh().GetPoint(0)[2] % 5.0, 0.0, places=4)
        self.assertEqual(modelNode.GetAttribute("SimulationModel.UnitSystem"), "mmgs")
        with self.assertRaises(ValueError):
            logic.importFiles([filePath], "LPS", "cgs", resampleSpacing=0.0)

        # By default the mesh must not be resampled.
        modelNode = logic.importFiles([filePath], "LPS", "cgs", decimationCellCountThreshold=None,
                                      mergeDuplicatePoints=False)[0]
        self.assertEqual(modelNode.GetMesh().GetNumberOfCells(), mesh.GetNumberOfCells())

        self.delayDisplay("Uniform resampling test passed")

    def test_ApproximateRanges(self):
        """A large VTKHDF file must be listed from a sample of its partitions, without affecting the import."""
        self.delayDisplay("Starting approximate ranges test")

        import tempfile

        def writePartitionedFile(fileName, numberOfPartitions):
            """Each partition is a cube with the index of the partition as position and value."""
            partitioned = vtk.vtkPartitionedDataSet()
            partitioned.SetNumberOfPartitions(numberOfPartitions)
            for partitionIndex in range(numberOfPartitions):
                cube = vtk.vtkCubeSource()
                cube.SetCenter(partitionIndex * 2.0, 0.0, 0.0)
                appendFilter = vtk.vtkAppendFilter()
                appendFilter.SetInputConnection(cube.GetOutputPort())
                appendFilter.Update()
                partition = appendFilter.GetOutput()
                values = vtk.vtkFloatArray()
                values.SetName("Pressure")
                for pointIndex in range(partition.GetNumberOfPoints()):
                    values.InsertNextValue(partitionIndex)
                partition.GetPointData().Initialize()
                partition.GetPointData().AddArray(values)
                partition.GetCellData().Initialize()
                partitioned.SetPartition(partitionIndex, partition)
            filePath = os.path.join(tempfile.mkdtemp(), fileName)
            writer = vtk.vtkHDFWriter()
            writer.SetInputData(partitioned)
            writer.SetFileName(filePath)
            self.assertTrue(writer.Write())
            return filePath

        def arrayInfoByKey(arrayInfos):
            return {arrayInfo.key: arrayInfo for arrayInfo in arrayInfos}

        pressureKey = (POINT_LOCATION, "Pressure")
        positionKey = (POSITION_LOCATION, POSITION_ARRAY_NAME)
        numberOfPartitions = APPROXIMATE_RANGE_PARTITION_COUNT * 2
        filePath = writePartitionedFile("partitioned.vtkhdf", numberOfPartitions)
        logic = ImportExportSimulationModelLogic()

        exact = arrayInfoByKey(logic.getArrayInfosFromFiles([filePath]))
        self.assertEqual(exact[pressureKey].componentRanges, [(0.0, numberOfPartitions - 1.0)])
        self.assertFalse(exact[pressureKey].isRangeApproximate)
        self.assertFalse(exact[pressureKey].rangeString().startswith("~"))
        self.assertIn(os.path.normpath(filePath), logic._meshCache)

        # Every other partition is sampled, so the last one is not, but the coordinates are exact.
        logic = ImportExportSimulationModelLogic()
        approximate = arrayInfoByKey(logic.getArrayInfosFromFiles([filePath], 0))
        self.assertEqual(set(approximate), set(exact))
        self.assertEqual(approximate[pressureKey].numberOfComponents, 1)
        self.assertEqual(approximate[pressureKey].componentRanges, [(0.0, numberOfPartitions - 2.0)])
        self.assertTrue(approximate[pressureKey].isRangeApproximate)
        self.assertTrue(approximate[pressureKey].rangeString().startswith("~"))
        self.assertEqual(approximate[positionKey].componentRanges, exact[positionKey].componentRanges)
        self.assertFalse(approximate[positionKey].isRangeApproximate)
        self.assertNotIn(os.path.normpath(filePath), logic._meshCache)

        # The cached information must be protected from changes made by the caller.
        approximate[pressureKey].simulationUnit = simulationUnitByQuantity(LENGTH_QUANTITY)
        repeated = arrayInfoByKey(logic.getArrayInfosFromFiles([filePath], 0))
        self.assertNotEqual(repeated[pressureKey].simulationUnit.quantity, LENGTH_QUANTITY)

        # The import must load the whole file, even if only a sample of it was read for the table.
        modelNode = logic.importFiles([filePath], "RAS", "mmgs", mergeDuplicatePoints=False)[0]
        self.assertEqual(modelNode.GetMesh().GetNumberOfCells(), numberOfPartitions * 6)
        self.assertEqual(modelNode.GetMesh().GetPointData().GetArray("Pressure").GetRange(),
                         (0.0, numberOfPartitions - 1.0))

        # Small meshes, and files that have no more partitions than the sample, are read completely.
        logic = ImportExportSimulationModelLogic()
        smallMesh = arrayInfoByKey(logic.getArrayInfosFromFiles([filePath], numberOfPartitions * 6))
        self.assertFalse(smallMesh[pressureKey].isRangeApproximate)
        self.assertEqual(smallMesh[pressureKey].componentRanges, exact[pressureKey].componentRanges)
        fewPartitionsFilePath = writePartitionedFile("fewPartitions.vtkhdf", APPROXIMATE_RANGE_PARTITION_COUNT)
        fewPartitions = arrayInfoByKey(logic.getArrayInfosFromFiles([fewPartitionsFilePath], 0))
        self.assertFalse(fewPartitions[pressureKey].isRangeApproximate)

        # Other file formats are not affected, and an approximate file marks the merged range.
        vtuFilePath = os.path.join(tempfile.mkdtemp(), "mesh.vtu")
        vtuWriter = vtk.vtkXMLUnstructuredGridWriter()
        vtuWriter.SetInputData(modelNode.GetMesh())
        vtuWriter.SetFileName(vtuFilePath)
        self.assertTrue(vtuWriter.Write())
        vtuOnly = arrayInfoByKey(logic.getArrayInfosFromFiles([vtuFilePath], 0))
        self.assertFalse(vtuOnly[pressureKey].isRangeApproximate)
        merged = arrayInfoByKey(logic.getArrayInfosFromFiles([filePath, vtuFilePath], 0))
        self.assertTrue(merged[pressureKey].isRangeApproximate)

        self.delayDisplay("Approximate ranges test passed")

    def test_DecimateTetrahedra(self):
        """Decimation must reach the target, keep the shape, and transfer the data arrays."""
        self.delayDisplay("Starting tetrahedral mesh decimation test")

        import tempfile

        def createTetrahedralMesh(dimension):
            image = vtk.vtkImageData()
            image.SetDimensions(dimension, dimension, dimension)
            image.SetSpacing(1.0, 1.0, 1.0)
            image.AllocateScalars(vtk.VTK_FLOAT, 1)
            tetrahedralize = vtk.vtkDataSetTriangleFilter()
            tetrahedralize.SetInputData(image)
            tetrahedralize.Update()
            mesh = vtk.vtkUnstructuredGrid()
            mesh.DeepCopy(tetrahedralize.GetOutput())
            mesh.GetPointData().Initialize()
            points = numpy_support.vtk_to_numpy(mesh.GetPoints().GetData())
            for name, values in (("Pressure", points[:, 0] + 2.0 * points[:, 1] - points[:, 2]),
                                 ("Velocity", points * 3.0),
                                 ("NodeID", np.arange(len(points), dtype=np.int32))):
                array = numpy_support.numpy_to_vtk(values, deep=True)
                array.SetName(name)
                mesh.GetPointData().AddArray(array)
            regionId = numpy_support.numpy_to_vtk(
                np.full(mesh.GetNumberOfCells(), 5, dtype=np.int32), deep=True)
            regionId.SetName("RegionID")
            mesh.GetCellData().AddArray(regionId)
            return mesh

        # More cells than what rand() can select from on Windows (32767), so several passes are needed.
        mesh = createTetrahedralMesh(21)
        self.assertGreater(mesh.GetNumberOfCells(), 32767)
        self.assertTrue(TetrahedralMeshDecimator.canDecimate(mesh))
        decimator = TetrahedralMeshDecimator(targetReduction=0.5)
        decimatedMesh = decimator.decimate(mesh)

        self.assertLessEqual(decimatedMesh.GetNumberOfCells(), mesh.GetNumberOfCells() * 0.51)
        self.assertLess(decimatedMesh.GetNumberOfPoints(), mesh.GetNumberOfPoints())
        self.assertTrue(TetrahedralMeshDecimator.canDecimate(decimatedMesh))
        for actual, expected in zip(decimatedMesh.GetBounds(), mesh.GetBounds()):
            self.assertAlmostEqual(actual, expected, places=4)

        # Linear fields are reproduced exactly by interpolation, wherever the points are moved.
        points = numpy_support.vtk_to_numpy(decimatedMesh.GetPoints().GetData())
        pressure = numpy_support.vtk_to_numpy(decimatedMesh.GetPointData().GetArray("Pressure"))
        self.assertLess(np.abs(pressure - (points[:, 0] + 2.0 * points[:, 1] - points[:, 2])).max(), 1e-3)
        velocity = numpy_support.vtk_to_numpy(decimatedMesh.GetPointData().GetArray("Velocity"))
        self.assertLess(np.abs(velocity - points * 3.0).max(), 1e-3)

        # Identifiers must not be interpolated: each one must be an identifier of the input mesh.
        nodeIds = decimatedMesh.GetPointData().GetArray("NodeID")
        self.assertEqual(nodeIds.GetDataType(), mesh.GetPointData().GetArray("NodeID").GetDataType())
        nodeIdValues = numpy_support.vtk_to_numpy(nodeIds)
        self.assertTrue(((nodeIdValues >= 0) & (nodeIdValues < mesh.GetNumberOfPoints())).all())
        regionIds = numpy_support.vtk_to_numpy(decimatedMesh.GetCellData().GetArray("RegionID"))
        self.assertEqual(len(regionIds), decimatedMesh.GetNumberOfCells())
        self.assertTrue((regionIds == 5).all())
        # The input must not be changed.
        self.assertEqual(mesh.GetPointData().GetNumberOfArrays(), 3)

        # Time points with the same geometry reuse the decimated geometry, but not the values.
        laterMesh = vtk.vtkUnstructuredGrid()
        laterMesh.DeepCopy(mesh)
        numpy_support.vtk_to_numpy(laterMesh.GetPointData().GetArray("Velocity"))[:] *= 2.0
        laterDecimatedMesh = decimator.decimate(laterMesh)
        self.assertEqual(decimator.numberOfDecimations, 1)
        self.assertEqual(laterDecimatedMesh.GetNumberOfCells(), decimatedMesh.GetNumberOfCells())
        laterVelocity = numpy_support.vtk_to_numpy(laterDecimatedMesh.GetPointData().GetArray("Velocity"))
        self.assertLess(np.abs(laterVelocity - points * 6.0).max(), 1e-3)
        self.assertLess(np.abs(velocity - points * 3.0).max(), 1e-3)

        # A different geometry must be decimated again.
        movedMesh = vtk.vtkUnstructuredGrid()
        movedMesh.DeepCopy(mesh)
        numpy_support.vtk_to_numpy(movedMesh.GetPoints().GetData())[:] += 1.0
        movedMesh.GetPoints().Modified()
        movedDecimatedMesh = decimator.decimate(movedMesh)
        self.assertEqual(decimator.numberOfDecimations, 2)
        self.assertAlmostEqual(movedDecimatedMesh.GetBounds()[0], mesh.GetBounds()[0] + 1.0, places=4)

        # Import options
        filePath = os.path.join(tempfile.mkdtemp(), "tetrahedra.vtu")
        logic = ImportExportSimulationModelLogic()
        smallMesh = createTetrahedralMesh(6)
        logic.writeMesh(smallMesh, filePath)
        numberOfCells = smallMesh.GetNumberOfCells()
        # The default threshold is not reached.
        defaultNode = logic.importFiles([filePath], "RAS", "mmgs")[0]
        self.assertEqual(defaultNode.GetMesh().GetNumberOfCells(), numberOfCells)
        # At the threshold the mesh is not decimated, only above it.
        atThresholdNode = logic.importFiles([filePath], "RAS", "mmgs", decimationCellCountThreshold=numberOfCells)[0]
        self.assertEqual(atThresholdNode.GetMesh().GetNumberOfCells(), numberOfCells)
        decimatedNode = logic.importFiles([filePath], "RAS", "mmgs", decimationCellCountThreshold=numberOfCells - 1,
                                          decimationTargetReduction=0.5)[0]
        self.assertLess(decimatedNode.GetMesh().GetNumberOfCells(), numberOfCells)
        disabledNode = logic.importFiles([filePath], "RAS", "mmgs", decimationCellCountThreshold=None)[0]
        self.assertEqual(disabledNode.GetMesh().GetNumberOfCells(), numberOfCells)

        # Only tetrahedra can be decimated.
        surfaceFilter = vtk.vtkDataSetSurfaceFilter()
        surfaceFilter.SetInputData(smallMesh)
        surfaceFilter.Update()
        self.assertFalse(TetrahedralMeshDecimator.canDecimate(surfaceFilter.GetOutput()))
        triangles = vtk.vtkAppendFilter()
        triangles.SetInputData(surfaceFilter.GetOutput())
        triangles.Update()
        self.assertFalse(TetrahedralMeshDecimator.canDecimate(triangles.GetOutput()))

        self.delayDisplay("Tetrahedral mesh decimation test passed")

    def test_NonVectorArrayConversion(self):
        """2-component vectors must be flipped, Q-criterion and unknown 2-component arrays must not."""
        self.delayDisplay("Starting 2-component and Q-criterion conversion test")

        self.assertEqual(flippedComponentNames("Velocity", 2), ["x", "y"])
        self.assertEqual(flippedComponentNames("Displacement", 2), ["x", "y"])
        self.assertEqual(flippedComponentNames("TCoords", 2), [])
        self.assertEqual(flippedComponentNames("SomethingUnknown", 2), [])
        self.assertEqual(flippedComponentNames("Velocity", 2, isFloatingPoint=False), [])
        for arrayName in ("Q-Criterion", "QCriterion", "q_criterion", "fluid_Q-Criterion"):
            for numberOfComponents in (1, 3):
                self.assertEqual(flippedComponentNames(arrayName, numberOfComponents), [], arrayName)

        points = vtk.vtkPoints()
        points.InsertNextPoint(1.0, 2.0, 0.0)
        mesh = vtk.vtkPolyData()
        mesh.SetPoints(points)
        for name, values in (("Velocity", (1.0, 2.0)), ("TCoords", (0.25, 0.5)),
                             ("Q-Criterion", (3.0, 4.0, 5.0))):
            array = vtk.vtkDoubleArray()
            array.SetName(name)
            array.SetNumberOfComponents(len(values))
            array.InsertNextTuple(values)
            mesh.GetPointData().AddArray(array)
        pointData = ImportExportSimulationModelLogic.convertMesh(mesh, {}, True, "mmgs", "mmgs").GetPointData()
        self.assertEqual(pointData.GetArray("Velocity").GetTuple(0), (-1.0, -2.0))
        self.assertEqual(pointData.GetArray("TCoords").GetTuple(0), (0.25, 0.5))
        self.assertEqual(pointData.GetArray("Q-Criterion").GetTuple(0), (3.0, 4.0, 5.0))

        self.delayDisplay("2-component and Q-criterion conversion test passed")

    def test_MergeDuplicatePoints(self):
        """Points must only be merged if their position and all their values are the same."""
        self.delayDisplay("Starting merge duplicate points test")

        import tempfile

        # Two triangles with a separate copy of each point, sharing the edge between
        # (1, 0, 0) and (0, 1, 0). The value is continuous at (1, 0, 0) but not at (0, 1, 0).
        pointCoordinates = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        pressureValues = [1.0, 2.0, 3.0, 2.0, 4.0, 5.0]

        def fillMesh(mesh):
            points = vtk.vtkPoints()
            points.SetDataTypeToFloat()
            pressure = vtk.vtkFloatArray()
            pressure.SetName("Pressure")
            velocity = vtk.vtkFloatArray()
            velocity.SetName("Velocity")
            velocity.SetNumberOfComponents(3)
            for coordinates, value in zip(pointCoordinates, pressureValues):
                points.InsertNextPoint(coordinates)
                pressure.InsertNextTuple1(value)
                # Same at every copy of a point: this array alone would not prevent merging.
                velocity.InsertNextTuple3(*coordinates)
            mesh.SetPoints(points)
            mesh.GetPointData().AddArray(pressure)
            mesh.GetPointData().AddArray(velocity)
            cellData = vtk.vtkIntArray()
            cellData.SetName("attribute")
            cellData.InsertNextTuple1(7)
            cellData.InsertNextTuple1(8)
            mesh.GetCellData().AddArray(cellData)

        grid = vtk.vtkUnstructuredGrid()
        fillMesh(grid)
        grid.Allocate(2)
        grid.InsertNextCell(vtk.VTK_TRIANGLE, 3, [0, 1, 2])
        grid.InsertNextCell(vtk.VTK_TRIANGLE, 3, [3, 4, 5])
        surface = vtk.vtkPolyData()
        fillMesh(surface)
        surface.Allocate(2)
        surface.InsertNextCell(vtk.VTK_TRIANGLE, 3, [0, 1, 2])
        surface.InsertNextCell(vtk.VTK_TRIANGLE, 3, [3, 4, 5])

        for mesh in (grid, surface):
            merged = ImportExportSimulationModelLogic.mergeDuplicatePoints(mesh)
            # Only one of the two duplicated positions can be merged.
            self.assertEqual(merged.GetNumberOfPoints(), 5, mesh.GetClassName())
            self.assertEqual(merged.GetNumberOfCells(), 2)
            self.assertEqual(merged.GetPoints().GetDataType(), vtk.VTK_FLOAT)
            # The temporary array must not remain in the output or the input.
            self.assertEqual(merged.GetPointData().GetNumberOfArrays(), 2)
            self.assertEqual(mesh.GetPointData().GetNumberOfArrays(), 2)
            self.assertEqual(mesh.GetNumberOfPoints(), 6)
            self.assertEqual(merged.GetCellData().GetArray("attribute").GetTuple1(1), 8)
            # Each cell corner must have the same position and value as in the input mesh.
            mergedPressure = merged.GetPointData().GetArray("Pressure")
            for cellIndex in range(2):
                mergedCellPoints = vtk.vtkIdList()
                merged.GetCellPoints(cellIndex, mergedCellPoints)
                for corner in range(3):
                    inputPointIndex = cellIndex * 3 + corner
                    mergedPointIndex = mergedCellPoints.GetId(corner)
                    self.assertEqual(merged.GetPoint(mergedPointIndex), pointCoordinates[inputPointIndex])
                    self.assertEqual(mergedPressure.GetTuple1(mergedPointIndex), pressureValues[inputPointIndex])

        # Mesh without any point data: only the positions are compared
        positionsOnly = vtk.vtkUnstructuredGrid()
        positionsOnly.DeepCopy(grid)
        positionsOnly.GetPointData().Initialize()
        self.assertEqual(ImportExportSimulationModelLogic.mergeDuplicatePoints(positionsOnly).GetNumberOfPoints(), 4)

        # The import option
        filePath = os.path.join(tempfile.mkdtemp(), "duplicates.vtu")
        logic = ImportExportSimulationModelLogic()
        logic.writeMesh(grid, filePath)
        mergedNode = logic.importFiles([filePath], "RAS", "mmgs")[0]
        self.assertEqual(mergedNode.GetMesh().GetNumberOfPoints(), 5)
        notMergedNode = logic.importFiles([filePath], "RAS", "mmgs", mergeDuplicatePoints=False)[0]
        self.assertEqual(notMergedNode.GetMesh().GetNumberOfPoints(), 6)

        self.delayDisplay("Merge duplicate points test passed")

    def test_ImportVtkHdfTimeSeries(self):
        """Each time point of a VTKHDF file must be converted and stored in a browsable sequence."""
        self.delayDisplay("Starting VTKHDF time series import test")

        import tempfile

        # The time source moves its mesh along the x axis, so the time points are all different.
        timeSource = vtk.vtkTimeSourceExample()
        timeSource.SetXAmplitude(5.0)
        timeSource.UpdateInformation()
        filePath = os.path.join(tempfile.mkdtemp(), "timeSeries.vtkhdf5")
        writer = vtk.vtkHDFWriter()
        writer.SetInputConnection(timeSource.GetOutputPort())
        writer.SetFileName(filePath)
        writer.SetWriteAllTimeSteps(True)
        self.assertTrue(writer.Write())

        logic = ImportExportSimulationModelLogic()
        timeValues = logic.getVtkHdfTimeValues(filePath)
        self.assertGreater(len(timeValues), 1)

        # Points are compared one by one with the file below, so they must not be merged.
        importedNodes = logic.importFiles([filePath], "LPS", "cgs", mergeDuplicatePoints=False)
        self.assertEqual(len(importedNodes), 1)
        proxyNode = importedNodes[0]
        self.assertTrue(proxyNode.IsA("vtkMRMLModelNode"))
        self.assertIsNotNone(proxyNode.GetDisplayNode())

        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(proxyNode)
        self.assertIsNotNone(browserNode)
        sequenceNode = browserNode.GetMasterSequenceNode()
        self.assertEqual(sequenceNode.GetNumberOfDataNodes(), len(timeValues))
        self.assertEqual(sequenceNode.GetIndexName(), "time")
        self.assertEqual(sequenceNode.GetIndexUnit(), "s")

        # Every time point must be converted from LPS/cm to RAS/mm, compared to the file content.
        reader = ImportExportSimulationModelLogic._createVtkHdfReader(filePath)
        distinctPoints = set()
        for index, timeValue in enumerate(timeValues):
            self.assertAlmostEqual(float(sequenceNode.GetNthIndexValue(index)), timeValue)
            fileMesh = ImportExportSimulationModelLogic._readVtkHdfMesh(reader, timeValue, filePath)
            frameNode = sequenceNode.GetNthDataNode(index)
            self.assertEqual(frameNode.GetAttribute("SimulationModel.UnitSystem"), "mmgs")
            frameMesh = frameNode.GetMesh()
            self.assertEqual(frameMesh.GetNumberOfPoints(), fileMesh.GetNumberOfPoints())
            filePoint = fileMesh.GetPoint(0)
            framePoint = frameMesh.GetPoint(0)
            for actual, expected in zip(framePoint, (-filePoint[0] * 10, -filePoint[1] * 10, filePoint[2] * 10)):
                self.assertAlmostEqual(actual, expected, places=4)
            distinctPoints.add(round(filePoint[0], 6))
        self.assertGreater(len(distinctPoints), 1, "Time points of the test data must differ")

        # Selecting a time point in the browser must show that mesh in the proxy node.
        lastIndex = len(timeValues) - 1
        browserNode.SetSelectedItemNumber(lastIndex)
        lastFrameMesh = sequenceNode.GetNthDataNode(lastIndex).GetMesh()
        self.assertEqual(proxyNode.GetMesh().GetPoint(0), lastFrameMesh.GetPoint(0))
        self.assertEqual(proxyNode.GetAttribute("SimulationModel.Position.Unit"), "mm")

        # Time points that are closer than the default index tolerance of the sequence node, and
        # that only differ after many digits, must all get an item of their own.
        for closeTimeValues in ([0.0, 0.001, 0.002, 0.003], [1e-6, 2e-6, 3e-6],
                                [1000.0000001, 1000.0000002, 1000.0000003]):
            closeSequenceNode = ImportExportSimulationModelLogic._createTimeSequenceNode(
                "closeTimes", closeTimeValues)
            frameNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLModelNode")
            frameNode.UnRegister(None)
            indexValues = ImportExportSimulationModelLogic._timeIndexValues(closeTimeValues)
            for indexValue in indexValues:
                closeSequenceNode.SetDataNodeAtValue(frameNode, indexValue)
            self.assertEqual(closeSequenceNode.GetNumberOfDataNodes(), len(closeTimeValues), closeTimeValues)
        self.assertEqual(ImportExportSimulationModelLogic._timeIndexValues([0.9369999999999883, 4.685]),
                         ["0.937", "4.685"])

        # Keeping 1 of N time points starts from the first time point.
        for keepEveryNth in (2, 3):
            keptProxyNode = logic.importFiles([filePath], "LPS", "cgs", keepEveryNthTimePoint=keepEveryNth)[0]
            keptSequenceNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(
                keptProxyNode).GetMasterSequenceNode()
            keptTimeValues = timeValues[::keepEveryNth]
            self.assertEqual(keptSequenceNode.GetNumberOfDataNodes(), len(keptTimeValues))
            for index, timeValue in enumerate(keptTimeValues):
                self.assertAlmostEqual(float(keptSequenceNode.GetNthIndexValue(index)), timeValue)
        with self.assertRaises(ValueError):
            logic.importFiles([filePath], "LPS", "cgs", keepEveryNthTimePoint=0)

        # The first time point to load can be selected, also together with keeping 1 of N.
        for firstIndex, keepEveryNth in ((1, 1), (1, 2)):
            keptProxyNode = logic.importFiles([filePath], "LPS", "cgs", keepEveryNthTimePoint=keepEveryNth,
                                              firstTimePointIndex=firstIndex)[0]
            keptSequenceNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(
                keptProxyNode).GetMasterSequenceNode()
            keptTimeValues = timeValues[firstIndex::keepEveryNth]
            self.assertEqual(keptSequenceNode.GetNumberOfDataNodes(), len(keptTimeValues))
            for index, timeValue in enumerate(keptTimeValues):
                self.assertAlmostEqual(float(keptSequenceNode.GetNthIndexValue(index)), timeValue)
        numberOfSequenceNodes = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSequenceNode")
        for invalidIndex in (-1, len(timeValues)):
            with self.assertRaises(ValueError):
                logic.importFiles([filePath], "LPS", "cgs", firstTimePointIndex=invalidIndex)
        self.assertEqual(slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSequenceNode"), numberOfSequenceNodes)

        # If a single time point remains then it is loaded as a model, without a sequence.
        numberOfBrowserNodes = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSequenceBrowserNode")
        for firstIndex, keepEveryNth in ((len(timeValues) - 1, 1), (0, len(timeValues) + 5), (1, len(timeValues))):
            modelNode = logic.importFiles([filePath], "LPS", "cgs", keepEveryNthTimePoint=keepEveryNth,
                                          firstTimePointIndex=firstIndex, mergeDuplicatePoints=False)[0]
            self.assertTrue(modelNode.IsA("vtkMRMLModelNode"))
            self.assertIsNone(slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(modelNode))
            self.assertAlmostEqual(float(modelNode.GetAttribute("SimulationModel.TimeValue")), timeValues[firstIndex])
            # The model must contain the selected time point, converted to RAS and mm.
            fileMesh = ImportExportSimulationModelLogic._readVtkHdfMesh(reader, timeValues[firstIndex], filePath)
            filePoint = fileMesh.GetPoint(0)
            for actual, expected in zip(modelNode.GetMesh().GetPoint(0),
                                        (-filePoint[0] * 10, -filePoint[1] * 10, filePoint[2] * 10)):
                self.assertAlmostEqual(actual, expected, places=4)
        self.assertEqual(slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSequenceNode"), numberOfSequenceNodes)
        self.assertEqual(slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSequenceBrowserNode"), numberOfBrowserNodes)

        self.delayDisplay("VTKHDF time series import test passed")

    def test_ImportImage(self):
        """Geometry of a .vti image must be converted to RAS and mm, intensities must be kept."""
        self.delayDisplay("Starting image import test")

        import tempfile

        # The extent intentionally does not start from 0.
        image = vtk.vtkImageData()
        image.SetExtent(1, 3, 0, 2, 0, 1)
        image.SetOrigin(1.0, 2.0, 3.0)
        image.SetSpacing(0.5, 0.25, 2.0)
        image.AllocateScalars(vtk.VTK_SHORT, 1)
        image.GetPointData().GetScalars().SetName("ImageScalars")
        image.GetPointData().GetScalars().Fill(7)
        filePath = os.path.join(tempfile.mkdtemp(), "testImage-cm.vti")
        writer = vtk.vtkXMLImageDataWriter()
        writer.SetInputData(image)
        writer.SetFileName(filePath)
        self.assertTrue(writer.Write())

        logic = ImportExportSimulationModelLogic()
        arrayInfos = logic.getArrayInfosFromFiles([filePath])
        self.assertEqual([arrayInfo.key for arrayInfo in arrayInfos],
                         [(POSITION_LOCATION, POSITION_ARRAY_NAME), (POINT_LOCATION, "ImageScalars")])

        importedNodes = logic.importFiles([filePath], "LPS", "cgs")
        self.assertEqual(len(importedNodes), 1)
        volumeNode = importedNodes[0]
        self.assertTrue(volumeNode.IsA("vtkMRMLScalarVolumeNode"))
        self.assertEqual(volumeNode.GetName(), "testImage-cm")

        # Voxel (i, j, k) of the file is at (1 + 0.5 * i, 2 + 0.25 * j, 3 + 2 * k) cm in LPS, and
        # the first voxel of the volume is voxel (1, 0, 0) of the file.
        ijkToRas = vtk.vtkMatrix4x4()
        volumeNode.GetIJKToRASMatrix(ijkToRas)
        firstVoxelRas = ijkToRas.MultiplyPoint((0, 0, 0, 1))[:3]
        for actual, expected in zip(firstVoxelRas, (-15.0, -20.0, 30.0)):
            self.assertAlmostEqual(actual, expected)
        lastVoxelRas = ijkToRas.MultiplyPoint((2, 2, 1, 1))[:3]
        for actual, expected in zip(lastVoxelRas, (-25.0, -25.0, 50.0)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(volumeNode.GetSpacing(), (5.0, 2.5, 20.0)):
            self.assertAlmostEqual(actual, expected)

        # Voxel values have no unit that could be guessed from their name, so they must not change.
        volumeImage = volumeNode.GetImageData()
        self.assertEqual(volumeImage.GetExtent(), (0, 2, 0, 2, 0, 1))
        self.assertEqual(volumeImage.GetSpacing(), (1.0, 1.0, 1.0))
        self.assertEqual(volumeImage.GetOrigin(), (0.0, 0.0, 0.0))
        self.assertEqual(volumeImage.GetScalarType(), vtk.VTK_SHORT)
        self.assertEqual(volumeImage.GetScalarRange(), (7.0, 7.0))
        self.assertEqual(volumeNode.GetAttribute("SimulationModel.Position.Unit"), "mm")

        self.delayDisplay("Image import test passed")

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
