"""Description of the point coordinates and the data arrays of meshes, and of their units."""

import re

import vtk

from slicer.i18n import tr as _

from ImportExportSimulationModelLib.Units import (
    COORDINATE_SYSTEMS, DIMENSIONLESS_QUANTITY, guessSimulationUnit, LENGTH_QUANTITY,
    normalizedArrayName, SCENE_COORDINATE_SYSTEM, SCENE_UNIT_SYSTEM, SIMULATION_UNITS,
    SimulationUnit, simulationUnitByQuantity, simulationUnitByUnitString, UNIT_SYSTEMS,
    unitSystemConversionFactor,
)


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
# Arrays of a mesh
#


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


def mergeArrayInfos(arrayInfoLists):
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


def conversionDescriptions(arrayInfos, fromUnitSystem, toUnitSystem, flipFirstTwoComponents):
    """Describe how the values of arrays change when they are converted, for display.

    :return: list of texts, one for each array that changes.
    """
    descriptions = []
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
        if changes:
            descriptions.append("{name} ({location}): {changes}".format(
                name=arrayInfo.name, location=LOCATION_LABELS[arrayInfo.location],
                changes="; ".join(changes)))
    return descriptions


#
# Units stored in nodes
#

# Units of the point coordinates and of the data arrays of an imported model are stored in
# attributes of its node, so that the model can be exported to any unit system later:
#
#   SimulationModel.CoordinateSystem              coordinate system of the model in the scene
#   SimulationModel.UnitSystem                    unit system of the model in the scene
#   SimulationModel.SourceFile                    file the model was imported from
#   SimulationModel.TimeValue                     time in seconds, if a single time point of a
#                                                 time series was imported
#   SimulationModel.Position.Unit                 unit of the point coordinates, e.g. mm
#   SimulationModel.Position.LengthExponent       length exponent of the point coordinates
#   SimulationModel.Position.Quantity             quantity name, e.g. length
#   SimulationModel.PointArray.<name>.Unit        unit of a point data array, e.g. mm/s
#   SimulationModel.PointArray.<name>.*           length exponent and quantity, as above
#   SimulationModel.CellArray.<name>.*            the same, for cell data arrays
ATTRIBUTE_PREFIX = "SimulationModel."


def _attributeBaseName(location, name):
    if location == POSITION_LOCATION:
        return ATTRIBUTE_PREFIX + "Position"
    locationName = "PointArray" if location == POINT_LOCATION else "CellArray"
    return ATTRIBUTE_PREFIX + locationName + "." + name


def setModelArrayUnits(modelNode, arrayInfos, unitSystem, coordinateSystem):
    """Store the unit and the length exponent of each array in the model node."""
    modelNode.SetAttribute(ATTRIBUTE_PREFIX + "CoordinateSystem", coordinateSystem)
    modelNode.SetAttribute(ATTRIBUTE_PREFIX + "UnitSystem", unitSystem)
    for arrayInfo in arrayInfos:
        baseName = _attributeBaseName(arrayInfo.location, arrayInfo.name)
        simulationUnit = arrayInfo.simulationUnit
        modelNode.SetAttribute(baseName + ".Unit", simulationUnit.unit(unitSystem))
        modelNode.SetAttribute(baseName + ".LengthExponent", str(simulationUnit.lengthExponent))
        if simulationUnit.quantity:
            modelNode.SetAttribute(baseName + ".Quantity", simulationUnit.quantity)


def getModelUnitSystem(modelNode):
    """Unit system that the model is stored in, mm-g-s if it is not specified in the model."""
    if modelNode is None:
        return SCENE_UNIT_SYSTEM
    unitSystem = modelNode.GetAttribute(ATTRIBUTE_PREFIX + "UnitSystem")
    return unitSystem if unitSystem in UNIT_SYSTEMS else SCENE_UNIT_SYSTEM


def getModelCoordinateSystem(modelNode):
    """Coordinate system that the model is stored in, RAS if it is not specified in the model."""
    if modelNode is None:
        return SCENE_COORDINATE_SYSTEM
    coordinateSystem = modelNode.GetAttribute(ATTRIBUTE_PREFIX + "CoordinateSystem")
    return coordinateSystem if coordinateSystem in COORDINATE_SYSTEMS else SCENE_COORDINATE_SYSTEM


def getArrayInfosFromModel(modelNode):
    """Coordinates and data arrays of a model, with the units stored in the model node.

    Arrays that have no unit stored in the model node (for example, because the model was
    not imported by this module) get their unit guessed from the array name.
    """
    mesh = modelNode.GetMesh() if modelNode else None
    if mesh is None:
        return []
    arrayInfos = getArrayInfosFromMesh(mesh)
    unitSystem = getModelUnitSystem(modelNode)
    for arrayInfo in arrayInfos:
        baseName = _attributeBaseName(arrayInfo.location, arrayInfo.name)
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
