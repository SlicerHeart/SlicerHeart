"""Conversion of meshes and images between unit systems and coordinate systems."""

import vtk
from vtk.util import numpy_support

from ImportExportSimulationModelLib.Units import (
    DIMENSIONLESS_QUANTITY, LENGTH_QUANTITY, simulationUnitByQuantity,
    unitSystemConversionFactor,
)
from ImportExportSimulationModelLib.MeshArrays import (
    CELL_LOCATION, flippedComponentIndices, POINT_LOCATION, POSITION_ARRAY_NAME,
    POSITION_LOCATION,
)


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
        _convertImageGeometry(convertedMesh, positionFlippedIndices, positionScale)
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
                array = _replaceWithDoubleArray(attributes, name)
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


def imageIjkToRasMatrix(image):
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
