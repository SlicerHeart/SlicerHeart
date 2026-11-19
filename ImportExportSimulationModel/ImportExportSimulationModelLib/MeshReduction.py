"""Reduction of the size of meshes: merging of duplicate points, decimation, and uniform resampling."""

import hashlib
import time

import numpy as np
import vtk
from vtk.util import numpy_support

from slicer.i18n import tr as _

from ImportExportSimulationModelLib.OperationMonitor import OperationMonitor


#
# Merging of duplicate points
#


def mergeDuplicatePoints(mesh, monitor=None):
    """Return the mesh with the points merged that have the same position and the same values.

    Points that are at the same position but have a different value in any point data array
    are kept separate, so no value is changed or lost. Cells and their data are not changed.

    :param monitor: OperationMonitor that reports the progress, and lets the operation be cancelled.
    """
    if monitor is None:
        monitor = OperationMonitor()
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
    monitor.update(mergeFilter)
    mergedMesh = mergeFilter.GetOutput()
    mergedMesh.GetPointData().RemoveArray(mergingArrayName)
    return mergedMesh


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

    # Loops over the points of a mesh let the operation be cancelled after this many points.
    CANCEL_CHECK_POINT_COUNT = 10000

    def __init__(self, logCallback=None, monitor=None):
        self.logCallback = logCallback
        self.monitor = monitor if monitor is not None else OperationMonitor()
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

    def _findNearestPoints(self, mesh, geometry):
        locator = vtk.vtkStaticPointLocator()
        locator.SetDataSet(mesh)
        locator.BuildLocator()
        points = numpy_support.vtk_to_numpy(geometry.GetPoints().GetData()).astype(float).tolist()
        nearestPointIds = []
        for firstIndex in range(0, len(points), self.CANCEL_CHECK_POINT_COUNT):
            self.monitor.check(firstIndex / len(points))
            nearestPointIds.extend(
                locator.FindClosestPoint(point)
                for point in points[firstIndex:firstIndex + self.CANCEL_CHECK_POINT_COUNT])
        return np.array(nearestPointIds, dtype=np.int64)

    def _findSourceCells(self, mesh, geometry):
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
        self.monitor.update(cellCenters)
        centers = cellCenters.GetOutput()
        probe = vtk.vtkProbeFilter()
        probe.SetInputData(centers)
        probe.SetSourceData(source)
        self.monitor.update(probe)
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
            for count, index in enumerate(np.nonzero(~isValid)[0].tolist()):
                if count % self.CANCEL_CHECK_POINT_COUNT == 0:
                    self.monitor.check()
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
            if pointIndex % self.CANCEL_CHECK_POINT_COUNT == 0:
                self.monitor.check(pointIndex / numberOfPoints)
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
                 boundaryWeight=DEFAULT_DECIMATION_BOUNDARY_WEIGHT, logCallback=None, monitor=None):
        super().__init__(logCallback, monitor)
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
        self.monitor.update(mergeFilter)
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
            # The filter does not report its progress, so cancelling stops it between two passes.
            self.monitor.update(decimationFilter)
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

    def __init__(self, spacing, logCallback=None, monitor=None):
        """:param spacing: size of the cubes, in the length unit of the meshes."""
        super().__init__(logCallback, monitor)
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
        self.monitor.update(probe)
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
