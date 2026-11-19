"""Tests of merging of duplicate points, mesh decimation, and uniform resampling of the ImportExportSimulationModel module.

Run from the Slicer Python console:

    import slicer.testing
    slicer.testing.runUnitTest([r"<path>/ImportExportSimulationModel/Testing/Python"], "ImportExportSimulationModelMeshReductionTest")
"""

import os

import numpy as np
import vtk
from vtk.util import numpy_support

import slicer
import slicer.ScriptedLoadableModule

from ImportExportSimulationModel import ImportExportSimulationModelLogic
from ImportExportSimulationModelLib.MeshReduction import (
    mergeDuplicatePoints, TetrahedralMeshDecimator, UniformMeshResampler,
)


class ImportExportSimulationModelMeshReductionTest(slicer.ScriptedLoadableModule.ScriptedLoadableModuleTest):

    def setUp(self):
        slicer.mrmlScene.Clear()

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
            merged = mergeDuplicatePoints(mesh)
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
        self.assertEqual(mergeDuplicatePoints(positionsOnly).GetNumberOfPoints(), 4)

        # The import option
        filePath = os.path.join(tempfile.mkdtemp(), "duplicates.vtu")
        logic = ImportExportSimulationModelLogic()
        logic.writeMesh(grid, filePath)
        mergedNode = logic.importFiles([filePath], "RAS", "mmgs")[0]
        self.assertEqual(mergedNode.GetMesh().GetNumberOfPoints(), 5)
        notMergedNode = logic.importFiles([filePath], "RAS", "mmgs", mergeDuplicatePoints=False)[0]
        self.assertEqual(notMergedNode.GetMesh().GetNumberOfPoints(), 6)

        self.delayDisplay("Merge duplicate points test passed")
