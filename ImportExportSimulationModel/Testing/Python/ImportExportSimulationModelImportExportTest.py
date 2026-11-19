"""Tests of reading, importing, and exporting files of the ImportExportSimulationModel module.

Run from the Slicer Python console:

    import slicer.testing
    slicer.testing.runUnitTest([r"<path>/ImportExportSimulationModel/Testing/Python"], "ImportExportSimulationModelImportExportTest")
"""

import os

import numpy as np
import vtk
from vtk.util import numpy_support

import slicer
import slicer.ScriptedLoadableModule

from ImportExportSimulationModel import ImportExportSimulationModelLogic
from ImportExportSimulationModelLib.Units import LENGTH_QUANTITY, simulationUnitByQuantity
from ImportExportSimulationModelLib.MeshArrays import (
    POINT_LOCATION, POSITION_ARRAY_NAME, POSITION_LOCATION,
)
from ImportExportSimulationModelLib.OperationMonitor import OperationCancelledError
from ImportExportSimulationModelLib.MeshReading import (
    APPROXIMATE_RANGE_PARTITION_COUNT, MeshFileReader,
)
from ImportExportSimulationModelLib.ModelImport import SimulationModelImporter


class ImportExportSimulationModelImportExportTest(slicer.ScriptedLoadableModule.ScriptedLoadableModuleTest):

    def setUp(self):
        slicer.mrmlScene.Clear()

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
        self.assertIn(os.path.normpath(filePath), logic.reader._meshCache)

        # Every other partition is sampled, so the last one is not, but the coordinates are exact.
        logic = ImportExportSimulationModelLogic()
        # Partial reading of the file can be cancelled, and it can be repeated after that.
        progressValues = []

        def cancelAtSecondProgress(progress):
            progressValues.append(progress)
            if len(progressValues) == 2:
                logic.monitor.cancel()

        logic.monitor.callbackInterval = 0.0
        logic.monitor.progressCallback = cancelAtSecondProgress
        with self.assertRaises(OperationCancelledError):
            logic.getArrayInfosFromFiles([filePath], 0)
        logic.monitor.progressCallback = None
        approximate = arrayInfoByKey(logic.getArrayInfosFromFiles([filePath], 0))
        self.assertEqual(set(approximate), set(exact))
        self.assertEqual(approximate[pressureKey].numberOfComponents, 1)
        self.assertEqual(approximate[pressureKey].componentRanges, [(0.0, numberOfPartitions - 2.0)])
        self.assertTrue(approximate[pressureKey].isRangeApproximate)
        self.assertTrue(approximate[pressureKey].rangeString().startswith("~"))
        self.assertEqual(approximate[positionKey].componentRanges, exact[positionKey].componentRanges)
        self.assertFalse(approximate[positionKey].isRangeApproximate)
        self.assertNotIn(os.path.normpath(filePath), logic.reader._meshCache)

        # The cached information must be protected from changes made by the caller.
        approximate[pressureKey].simulationUnit = simulationUnitByQuantity(LENGTH_QUANTITY)
        repeated = arrayInfoByKey(logic.getArrayInfosFromFiles([filePath], 0))
        self.assertNotEqual(repeated[pressureKey].simulationUnit.quantity, LENGTH_QUANTITY)

        # The import must load the whole file, even if only a sample of it was read for the table.
        modelNode = logic.importFiles([filePath], "RAS", "mmgs", mergeDuplicatePoints=False)[0]
        self.assertEqual(modelNode.GetMesh().GetNumberOfCells(), numberOfPartitions * 6)
        self.assertEqual(modelNode.GetMesh().GetPointData().GetArray("Pressure").GetRange(),
                         (0.0, numberOfPartitions - 1.0))
        # The partitions are read in groups, and they must remain in the order they are in the file.
        self.assertGreater(numberOfPartitions, logic.reader.VTKHDF_PARTITION_GROUP_COUNT)
        importedPressure = numpy_support.vtk_to_numpy(modelNode.GetMesh().GetPointData().GetArray("Pressure"))
        self.assertTrue(np.all(np.diff(importedPressure) >= 0))

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
        timeValues = logic.reader.getVtkHdfTimeValues(filePath)
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
        reader = MeshFileReader.createVtkHdfReader(filePath)
        distinctPoints = set()
        for index, timeValue in enumerate(timeValues):
            self.assertAlmostEqual(float(sequenceNode.GetNthIndexValue(index)), timeValue)
            fileMesh = logic.reader.readVtkHdfMesh(reader, timeValue, filePath)
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
            closeSequenceNode = SimulationModelImporter._createTimeSequenceNode(
                "closeTimes", closeTimeValues)
            frameNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLModelNode")
            frameNode.UnRegister(None)
            indexValues = SimulationModelImporter._timeIndexValues(closeTimeValues)
            for indexValue in indexValues:
                closeSequenceNode.SetDataNodeAtValue(frameNode, indexValue)
            self.assertEqual(closeSequenceNode.GetNumberOfDataNodes(), len(closeTimeValues), closeTimeValues)
        self.assertEqual(SimulationModelImporter._timeIndexValues([0.9369999999999883, 4.685]),
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
            fileMesh = logic.reader.readVtkHdfMesh(reader, timeValues[firstIndex], filePath)
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

    def test_Cancel(self):
        """Import and export must stop when cancelled, also while a single file is being processed."""
        self.delayDisplay("Starting cancel test")

        import tempfile

        image = vtk.vtkImageData()
        image.SetDimensions(20, 20, 20)
        tetrahedralize = vtk.vtkDataSetTriangleFilter()
        tetrahedralize.SetInputData(image)
        tetrahedralize.Update()
        mesh = tetrahedralize.GetOutput()
        pressure = numpy_support.numpy_to_vtk(np.arange(mesh.GetNumberOfPoints(), dtype=np.float32), deep=True)
        pressure.SetName("Pressure")
        mesh.GetPointData().AddArray(pressure)
        temporaryDirectory = tempfile.mkdtemp()
        meshFilePath = os.path.join(temporaryDirectory, "mesh.vtu")

        timeSource = vtk.vtkTimeSourceExample()
        timeSource.UpdateInformation()
        timeSeriesFilePath = os.path.join(temporaryDirectory, "timeSeries.vtkhdf")
        timeSeriesWriter = vtk.vtkHDFWriter()
        timeSeriesWriter.SetInputConnection(timeSource.GetOutputPort())
        timeSeriesWriter.SetFileName(timeSeriesFilePath)
        timeSeriesWriter.SetWriteAllTimeSteps(True)
        self.assertTrue(timeSeriesWriter.Write())

        logic = ImportExportSimulationModelLogic()
        logic.writeMesh(mesh, meshFilePath)
        # The progress is reported every time, so that the test does not depend on the speed of the computer.
        logic.monitor.callbackInterval = 0.0

        def reportedProgress(operation, cancelAtCall=None):
            """Run an operation, cancel it when the progress is reported for the given time."""
            progressValues = []

            def onProgress(progress):
                progressValues.append(progress)
                if len(progressValues) == cancelAtCall:
                    logic.monitor.cancel()

            logic.monitor.progressCallback = onProgress
            try:
                operation()
            finally:
                logic.monitor.progressCallback = None
            return progressValues

        def numberOfNodes():
            return [slicer.mrmlScene.GetNumberOfNodesByClass(className)
                    for className in ("vtkMRMLModelNode", "vtkMRMLSequenceNode", "vtkMRMLSequenceBrowserNode")]

        def assertCancellable(operation):
            """The operation must stop whenever it is cancelled, without adding anything to the scene."""
            progressValues = reportedProgress(operation)
            self.assertGreater(len(progressValues), 2)
            for cancelAtCall in (1, len(progressValues) // 2, len(progressValues)):
                numberOfNodesBefore = numberOfNodes()
                with self.assertRaises(OperationCancelledError):
                    reportedProgress(operation, cancelAtCall)
                self.assertEqual(numberOfNodes(), numberOfNodesBefore)
            return progressValues

        # Reading a file must report how far it is, so that it can be cancelled before it ends.
        progressValues = assertCancellable(lambda: logic.importFiles([meshFilePath], "LPS", "cgs"))
        self.assertTrue(any(progress is not None and 0.0 < progress < 1.0 for progress in progressValues))
        # Reading the files that are added to the input file list
        assertCancellable(lambda: (logic.clearCache(), logic.getArrayInfosFromFiles([meshFilePath])))
        # Mesh reduction and time series
        assertCancellable(lambda: logic.importFiles([meshFilePath], "LPS", "cgs", decimationCellCountThreshold=0))
        assertCancellable(lambda: logic.importFiles([meshFilePath], "LPS", "cgs", resampleSpacing=20.0))
        assertCancellable(lambda: logic.importFiles([timeSeriesFilePath], "LPS", "cgs"))

        # A cancel request that came too late to stop an operation must not stop the next one.
        logic.monitor.cancel()
        modelNode = logic.importFiles([meshFilePath], "LPS", "cgs")[0]
        self.assertEqual(modelNode.GetMesh().GetNumberOfCells(), mesh.GetNumberOfCells())

        # A file must not be left behind if writing it was cancelled.
        outputDirectory = os.path.join(temporaryDirectory, "exported")
        assertCancellable(lambda: logic.exportModels([modelNode], outputDirectory, "vtkxml", "LPS", "cgs"))
        self.assertEqual(os.listdir(outputDirectory), [])
        exportedFilePaths = logic.exportModels([modelNode], outputDirectory, "vtkxml", "LPS", "cgs")
        self.assertEqual(logic.readMesh(exportedFilePaths[0]).GetNumberOfCells(), mesh.GetNumberOfCells())

        self.delayDisplay("Cancel test passed")
