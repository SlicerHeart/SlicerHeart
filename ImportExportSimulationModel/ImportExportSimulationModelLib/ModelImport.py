"""Import of simulation mesh files into the scene."""

import os

import vtk

import slicer
from slicer.i18n import tr as _

from ImportExportSimulationModelLib import MeshReduction
from ImportExportSimulationModelLib.Units import (
    COORDINATE_SYSTEMS, DIMENSIONLESS_QUANTITY, SCENE_COORDINATE_SYSTEM, SCENE_UNIT_SYSTEM,
    simulationUnitByQuantity, UNIT_SYSTEMS,
)
from ImportExportSimulationModelLib.MeshArrays import (
    ATTRIBUTE_PREFIX, conversionDescriptions, getArrayInfosFromMesh, POINT_LOCATION,
    POSITION_LOCATION, setModelArrayUnits,
)
from ImportExportSimulationModelLib.OperationMonitor import OperationMonitor
from ImportExportSimulationModelLib.MeshConversion import convertMesh, imageIjkToRasMatrix
from ImportExportSimulationModelLib.MeshReduction import (
    DEFAULT_DECIMATION_BOUNDARY_WEIGHT, DEFAULT_DECIMATION_CELL_COUNT_THRESHOLD,
    DEFAULT_DECIMATION_TARGET_REDUCTION, TetrahedralMeshDecimator, UniformMeshResampler,
)


class SimulationModelImporter:
    """Imports simulation mesh files into the scene, one file at a time.

    A mesh is loaded as a model node, a VTKHDF file with several time points as a sequence of
    models with a sequence browser, and a .vti image as volume nodes. Nodes are always loaded in
    the coordinate system and the unit system of the scene, and the units of their arrays are
    stored in the nodes (see MeshArrays.setModelArrayUnits).

    The files are imported with the options that are given to the constructor.
    """

    def __init__(self, reader, coordinateSystem, unitSystem, arrayQuantities=None,
                 mergeDuplicatePoints=True,
                 decimationCellCountThreshold=DEFAULT_DECIMATION_CELL_COUNT_THRESHOLD,
                 decimationTargetReduction=DEFAULT_DECIMATION_TARGET_REDUCTION,
                 decimationBoundaryWeight=DEFAULT_DECIMATION_BOUNDARY_WEIGHT,
                 keepEveryNthTimePoint=1, firstTimePointIndex=0, resampleSpacing=None,
                 logCallback=None, monitor=None):
        """
        :param reader: MeshFileReader that the files are read with. A mesh that it has in its cache
            is not read again.
        :param coordinateSystem: coordinate system of the files (RAS or LPS).
        :param unitSystem: unit system of the files.
        :param arrayQuantities: (location, name) -> quantity name. Arrays that are not in the
            dictionary get their unit guessed from the array name.
        :param mergeDuplicatePoints: merge the points of meshes that have the same position and the
            same values, see MeshReduction.mergeDuplicatePoints.
        :param decimationCellCountThreshold: tetrahedral meshes that have more cells than this are
            decimated, see TetrahedralMeshDecimator. None disables decimation.
        :param decimationTargetReduction: fraction of the cells to remove from a decimated mesh.
        :param decimationBoundaryWeight: how strongly the boundary of a decimated mesh is preserved.
        :param keepEveryNthTimePoint: load only the first of every N time points of a time series.
        :param firstTimePointIndex: index of the first time point to load from a time series,
            starting from 0.
        :param resampleSpacing: replace the cells of volumetric meshes with cubes of this size, in
            mm, instead of decimating them. None to not resample.
        :param logCallback: called with each message that describes what is being done.
        :param monitor: OperationMonitor that reports the progress, and lets the import be cancelled.
        """
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

        self.reader = reader
        self.unitSystem = unitSystem
        self.flipFirstTwoComponents = (coordinateSystem != SCENE_COORDINATE_SYSTEM)
        self.arrayQuantities = arrayQuantities
        self.mergeDuplicatePoints = mergeDuplicatePoints
        self.decimationCellCountThreshold = decimationCellCountThreshold
        self.decimationTargetReduction = decimationTargetReduction
        self.decimationBoundaryWeight = decimationBoundaryWeight
        self.keepEveryNthTimePoint = keepEveryNthTimePoint
        self.firstTimePointIndex = firstTimePointIndex
        self.resampleSpacing = resampleSpacing
        self.logCallback = logCallback
        self.monitor = monitor if monitor is not None else OperationMonitor()

    def _log(self, text):
        if self.logCallback:
            self.logCallback(text)

    def importFile(self, filePath):
        """Load a file into the scene.

        :return: list of the created nodes: a model node (the proxy model node of a sequence, if
            the file has several time points) or the volume nodes of an image.
        :raises OperationCancelledError: if the import was cancelled, see OperationMonitor. Nothing
            is added to the scene then.
        """
        self._log(_("Importing {filePath}").format(filePath=filePath))
        nodeName = os.path.splitext(os.path.basename(filePath))[0]
        extension = os.path.splitext(filePath)[1].lower()
        reduceMesh = self._meshReductionFunction()
        timeValues = self.reader.getVtkHdfTimeValues(filePath) \
            if extension in self.reader.VTKHDF_FILE_EXTENSIONS else []
        if timeValues:
            keptTimeValues = timeValues[self.firstTimePointIndex::self.keepEveryNthTimePoint]
            if not keptTimeValues:
                raise ValueError(_("Index of the first time point ({index}) is too large, {filePath} "
                                   "has {count} time points (the index of the first one is 0).").format(
                    index=self.firstTimePointIndex, filePath=filePath, count=len(timeValues)))
            if len(keptTimeValues) < len(timeValues):
                self._log(_("  Keeping {kept} of {count} time points").format(
                    kept=len(keptTimeValues), count=len(timeValues)))
            if len(keptTimeValues) > 1:
                return [self._importTimeSeries(filePath, nodeName, keptTimeValues, reduceMesh)]
            # A sequence of a single time point would be of no use, a model is loaded instead.
            singleTimeValue = keptTimeValues[0]
            self.reader.releaseCachedMesh(filePath)
            mesh = self.reader.readVtkHdfMesh(
                self.reader.createVtkHdfReader(filePath), singleTimeValue, filePath)
        else:
            singleTimeValue = None
            mesh = self.reader.getCachedMesh(filePath)
        if isinstance(mesh, vtk.vtkImageData):
            return self._importImage(filePath, nodeName, mesh)
        return [self._importMesh(filePath, nodeName, mesh, singleTimeValue, reduceMesh)]

    # ------------------------------------------------------------------ conversion

    def _meshReductionFunction(self):
        """Return a function that reduces the size of the meshes of a file, as requested.

        All the time points of a file use the same function, so that they can share the result of
        the time-consuming decimation if their geometry is the same.
        """
        decimator = TetrahedralMeshDecimator(
            self.decimationTargetReduction, self.decimationBoundaryWeight, self.logCallback, self.monitor)
        # The resolution of resampling is specified in mm, the resampler needs it in the length
        # unit of the meshes. A resampled mesh is not decimated and it has no duplicate points.
        resampler = None if self.resampleSpacing is None else UniformMeshResampler(
            self.resampleSpacing / UNIT_SYSTEMS[self.unitSystem]["lengthUnitInMm"],
            self.logCallback, self.monitor)

        def reduceMesh(mesh):
            if resampler is not None and resampler.canResample(mesh):
                return resampler.resample(mesh)
            if (self.decimationCellCountThreshold is not None
                    and mesh.GetNumberOfCells() > self.decimationCellCountThreshold
                    and decimator.canDecimate(mesh)):
                # The decimated mesh has no duplicate points.
                return decimator.decimate(mesh)
            if not self.mergeDuplicatePoints:
                return mesh
            mergedMesh = MeshReduction.mergeDuplicatePoints(mesh, self.monitor)
            self._log(_("  Merged duplicate points: {before} -> {after}").format(
                before=mesh.GetNumberOfPoints(), after=mergedMesh.GetNumberOfPoints()))
            return mergedMesh

        return reduceMesh

    def _convertedMesh(self, mesh):
        """Convert a mesh or an image of the file to the coordinate and unit system of the scene.

        Arrays that the caller did not specify a unit for (for example, arrays that are only
        present in some of the files) get their unit guessed from the array name.

        :return: the converted mesh, and the description of its arrays with the units that were
            used for the conversion.
        """
        quantities = {}
        for arrayInfo in getArrayInfosFromMesh(mesh):
            quantities[arrayInfo.key] = arrayInfo.simulationUnit.quantity
        if self.arrayQuantities:
            quantities.update(self.arrayQuantities)
        convertedMesh = convertMesh(mesh, quantities, self.flipFirstTwoComponents,
                                    self.unitSystem, SCENE_UNIT_SYSTEM)
        arrayInfos = getArrayInfosFromMesh(convertedMesh)
        for arrayInfo in arrayInfos:
            arrayInfo.simulationUnit = simulationUnitByQuantity(
                quantities.get(arrayInfo.key, DIMENSIONLESS_QUANTITY))
        return convertedMesh, arrayInfos

    def _logConversion(self, arrayInfos):
        for description in conversionDescriptions(
                arrayInfos, self.unitSystem, SCENE_UNIT_SYSTEM, self.flipFirstTwoComponents):
            self._log("  " + description)

    # ------------------------------------------------------------------ mesh

    def _importMesh(self, filePath, nodeName, mesh, timeValue, reduceMesh):
        """Load a mesh into a model node.

        :param timeValue: time of the mesh, if it is a time point of a time series. None otherwise.
        :param reduceMesh: function that reduces the size of a mesh, see _meshReductionFunction.
        :return: the created model node.
        """
        mesh = reduceMesh(mesh)
        self.monitor.check()
        convertedMesh, arrayInfos = self._convertedMesh(mesh)
        self.monitor.check()
        modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", nodeName)
        modelNode.SetAndObserveMesh(convertedMesh)
        modelNode.CreateDefaultDisplayNodes()

        setModelArrayUnits(modelNode, arrayInfos, SCENE_UNIT_SYSTEM, SCENE_COORDINATE_SYSTEM)
        modelNode.SetAttribute(ATTRIBUTE_PREFIX + "SourceFile", filePath)
        if timeValue is not None:
            modelNode.SetAttribute(ATTRIBUTE_PREFIX + "TimeValue", "%.10g" % timeValue)
        self._logConversion(arrayInfos)
        return modelNode

    # ------------------------------------------------------------------ time series

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

    def _importTimeSeries(self, filePath, nodeName, timeValues, reduceMesh):
        """Load each time point of a VTKHDF file into a sequence of models, add a sequence browser.

        :param reduceMesh: function that reduces the size of a mesh, see _meshReductionFunction.
        :return: the proxy model node of the sequence browser.
        """
        # All the time points will be read, the one read for the arrays table is not needed.
        self.reader.releaseCachedMesh(filePath)

        sequenceNode = self._createTimeSequenceNode(nodeName, timeValues)
        indexValues = self._timeIndexValues(timeValues)
        try:
            vtkHdfReader = self.reader.createVtkHdfReader(filePath)
            for timePointIndex, timeValue in enumerate(timeValues):
                self.monitor.check()
                self._log(_("Reading time point {index}/{count} (time: {time:g}s)").format(
                    index=timePointIndex + 1, count=len(timeValues), time=timeValue))
                mesh = reduceMesh(self.reader.readVtkHdfMesh(vtkHdfReader, timeValue, filePath))
                self.monitor.check()
                convertedMesh, arrayInfos = self._convertedMesh(mesh)
                self.monitor.check()

                frameNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLModelNode")
                frameNode.UnRegister(None)  # Prevent memory leak
                setModelArrayUnits(frameNode, arrayInfos, SCENE_UNIT_SYSTEM, SCENE_COORDINATE_SYSTEM)
                frameNode.SetAttribute(ATTRIBUTE_PREFIX + "SourceFile", filePath)
                # The sequence stores a deep copy of the node it receives. A time point can take
                # up gigabytes of memory, so the mesh is only set after the node has been copied.
                sequenceDataNode = sequenceNode.SetDataNodeAtValue(frameNode, indexValues[timePointIndex])
                sequenceDataNode.SetAndObserveMesh(convertedMesh)
                if timePointIndex == 0:
                    self._logConversion(arrayInfos)
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

    # ------------------------------------------------------------------ image

    def _importImage(self, filePath, nodeName, image):
        """Load each point data array of an image into a volume node, in the scene coordinate
        and unit system.

        :return: list of the created volume nodes.
        """
        if image.GetCellData().GetNumberOfArrays():
            self._log(_("Warning: cell data arrays of the image are not loaded."))
        convertedImage, arrayInfos = self._convertedMesh(image)
        ijkToRas = imageIjkToRasMatrix(convertedImage)
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
            setModelArrayUnits(volumeNode, positionInfos + [arrayInfo],
                               SCENE_UNIT_SYSTEM, SCENE_COORDINATE_SYSTEM)
            volumeNode.SetAttribute(ATTRIBUTE_PREFIX + "SourceFile", filePath)
            volumeNodes.append(volumeNode)
        self._logConversion(arrayInfos)
        slicer.util.setSliceViewerLayers(background=volumeNodes[0], fit=True)
        return volumeNodes
