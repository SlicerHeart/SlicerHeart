"""Reading of simulation mesh files."""

import copy
import os

import vtk

from slicer.i18n import tr as _

from ImportExportSimulationModelLib.MeshArrays import (
    getArrayInfosFromMesh, mergeArrayInfos, POSITION_LOCATION,
)
from ImportExportSimulationModelLib.OperationMonitor import OperationMonitor


# The arrays table shows approximate value ranges of VTKHDF files with more cells than this,
# computed from this many partitions, if the file has more partitions than this.
APPROXIMATE_RANGE_CELL_COUNT_THRESHOLD = 1000000
APPROXIMATE_RANGE_PARTITION_COUNT = 8


class MeshFileReader:
    """Reads simulation mesh files, and lists the arrays that they contain.

    The meshes are not converted: they are in the coordinate system and unit system of the file.

    Meshes that are read for listing the arrays of files (getArrayInfosFromFiles) are kept in a
    cache, so that the files do not have to be read again when they are imported (getCachedMesh).
    """

    VTKHDF_FILE_EXTENSIONS = [".vtkhdf", ".vtkhdf5"]
    # Number of groups that the partitions of a time point of a VTKHDF file are read in.
    VTKHDF_PARTITION_GROUP_COUNT = 10
    READ_FILE_EXTENSIONS = [".vtu", ".vtp", ".vtk", ".vtkhdf", ".vtkhdf5", ".vti", ".stl", ".ply", ".obj"]

    def __init__(self, logCallback=None, monitor=None) -> None:
        """
        :param logCallback: called with each message that describes what is being done.
        :param monitor: OperationMonitor that reports the progress of reading, and lets it be cancelled.
        """
        self.logCallback = logCallback
        self.monitor = monitor if monitor is not None else OperationMonitor()
        # Input files are read when the arrays table is populated. The meshes are kept so that
        # importing does not have to read the (potentially large) files again.
        self._meshCache = {}
        # Approximate array information of large VTKHDF files, for which no mesh is kept in the cache.
        self._approximateArrayInfoCache = {}

    def _log(self, text) -> None:
        if self.logCallback:
            self.logCallback(text)

    # ------------------------------------------------------------------ reading

    @classmethod
    def readFileNameFilter(cls):
        return _("Simulation meshes") + " (" + " ".join(
            "*" + extension for extension in cls.READ_FILE_EXTENSIONS) + ")"

    def readMesh(self, filePath):
        """Read a mesh from file, without any conversion.

        Returns vtkPolyData or vtkUnstructuredGrid, or vtkImageData for a .vti file. Only the last
        time point of a VTKHDF file is returned: this is what the arrays table is populated from,
        because the first time point of a simulation result is often just an empty initial state.
        """
        if not os.path.isfile(filePath):
            raise ValueError(_("Input file not found: {filePath}").format(filePath=filePath))
        extension = os.path.splitext(filePath)[1].lower()
        if extension in self.VTKHDF_FILE_EXTENSIONS:
            timeValues = self.getVtkHdfTimeValues(filePath)
            reader = self.createVtkHdfReader(filePath)
            return self.readVtkHdfMesh(reader, timeValues[-1] if timeValues else None, filePath)
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
        self.monitor.update(reader)
        mesh = reader.GetOutput()
        if mesh is None or mesh.GetNumberOfPoints() == 0:
            raise ValueError(_("Failed to read mesh from {filePath}").format(filePath=filePath))
        if extension == ".vti":
            return mesh
        return self._asModelMesh(mesh)

    def _asModelMesh(self, mesh):
        """Return the mesh as vtkPolyData or vtkUnstructuredGrid.

        Any other data set type (structured grid, rectilinear grid, ...) is converted to a
        surface mesh, because that is what a model node can store.
        """
        if isinstance(mesh, (vtk.vtkPolyData, vtk.vtkUnstructuredGrid)):
            return mesh
        geometryFilter = vtk.vtkGeometryFilter()
        geometryFilter.SetInputData(mesh)
        self.monitor.update(geometryFilter)
        return geometryFilter.GetOutput()

    # ------------------------------------------------------------------ VTKHDF files

    @staticmethod
    def createVtkHdfReader(filePath):
        reader = vtk.vtkHDFReader()
        if not reader.CanReadFile(filePath):
            raise ValueError(_("Failed to read mesh from {filePath}").format(filePath=filePath))
        reader.SetFileName(filePath)
        reader.UpdateInformation()
        return reader

    @staticmethod
    def getVtkHdfTimeValues(filePath):
        """Time value of each time point of a VTKHDF file. Empty if the file has only one mesh."""
        reader = MeshFileReader.createVtkHdfReader(filePath)
        timeStepsKey = vtk.vtkStreamingDemandDrivenPipeline.TIME_STEPS()
        outputInformation = reader.GetOutputInformation(0)
        if not outputInformation.Has(timeStepsKey):
            return []
        timeValues = outputInformation.Get(timeStepsKey)
        return list(timeValues) if len(timeValues) > 1 else []

    def readVtkHdfMesh(self, reader, timeValue, filePath):
        """Read one time point of a VTKHDF file into a single mesh (timeValue=None if not temporal)."""
        if isinstance(reader.GetOutputDataObject(0), vtk.vtkPartitionedDataSet):
            mesh = self._appendedPartitions(self._readVtkHdfPartitions(reader, timeValue))
        else:
            self._updateVtkHdfReader(reader, timeValue)
            self.monitor.check()
            mesh = self._mergedPartitions(reader.GetOutputDataObject(0))
        if mesh is None or mesh.GetNumberOfPoints() == 0:
            raise ValueError(_("Failed to read mesh from {filePath}").format(filePath=filePath))
        return self._asModelMesh(mesh)

    def _readVtkHdfPartitions(self, reader, timeValue):
        """Read the partitions of a time point of a VTKHDF file, in the order they are in the file.

        The reader does not report its progress, so reading cannot be cancelled while it is
        running. Therefore the partitions are not read all at once but in several groups, and
        reading can be cancelled between them.
        """
        numberOfGroups = self.VTKHDF_PARTITION_GROUP_COUNT
        groups = []
        for groupIndex in range(numberOfGroups):
            # The reader takes every numberOfGroups-th partition of the file, starting from groupIndex.
            self._updateVtkHdfReader(reader, timeValue, groupIndex, numberOfGroups)
            partitioned = reader.GetOutputDataObject(0)
            groups.append([partitioned.GetPartition(index)
                           for index in range(partitioned.GetNumberOfPartitions())])
            self.monitor.check((groupIndex + 1) / numberOfGroups)
        partitions = []
        for indexInGroup in range(max(len(group) for group in groups)):
            partitions.extend(group[indexInGroup] for group in groups if indexInGroup < len(group))
        return partitions

    @staticmethod
    def _updateVtkHdfReader(reader, timeValue, piece=0, numberOfPieces=1):
        """Read a time point (timeValue=None if not temporal), or only one piece of it."""
        if timeValue is None:
            reader.UpdatePiece(piece, numberOfPieces, 0)
        else:
            reader.UpdateTimeStep(timeValue, piece, numberOfPieces, 0)

    def _approximateVtkHdfArrayInfos(self, filePath, cellCountThreshold):
        """Array information of the last time point of a large VTKHDF file, reading only a part of it.

        Value ranges are not stored in the file, and most of the time of reading a time point is
        spent on the data arrays. Therefore only the geometry is read, which gives the exact range
        of the point coordinates, and the data arrays of a few evenly spaced partitions, which
        give approximate value ranges.

        Returns None if the file should be read completely: it is small, or it does not have
        more partitions than what would be sampled.
        """
        timeValues = self.getVtkHdfTimeValues(filePath)
        timeValue = timeValues[-1] if timeValues else None

        reader = self.createVtkHdfReader(filePath)
        if not isinstance(reader.GetOutputDataObject(0), vtk.vtkPartitionedDataSet):
            return None
        reader.GetPointDataArraySelection().DisableAllArrays()
        reader.GetCellDataArraySelection().DisableAllArrays()
        geometryPartitions = self._readVtkHdfPartitions(reader, timeValue)
        numberOfPartitions = len(geometryPartitions)
        # A partition may be empty if a solver process had no part of the mesh assigned to it.
        partitions = [(index, partition) for index, partition in enumerate(geometryPartitions)
                      if partition is not None and partition.GetNumberOfPoints() > 0]
        numberOfCells = sum(partition.GetNumberOfCells() for _index, partition in partitions)
        if numberOfCells <= cellCountThreshold or len(partitions) <= APPROXIMATE_RANGE_PARTITION_COUNT:
            return None
        boundingBox = vtk.vtkBoundingBox()
        for _index, partition in partitions:
            boundingBox.AddBounds(partition.GetBounds())
        bounds = [0.0] * 6
        boundingBox.GetBounds(bounds)
        sampledPartitionIndices = [partitions[sampleIndex * len(partitions) // APPROXIMATE_RANGE_PARTITION_COUNT][0]
                                   for sampleIndex in range(APPROXIMATE_RANGE_PARTITION_COUNT)]
        # The geometry of the whole time point is not needed any more.
        del partitions, geometryPartitions, reader

        sampledArrayInfos = []
        for sampleIndex, partitionIndex in enumerate(sampledPartitionIndices):
            reader = self.createVtkHdfReader(filePath)
            self._updateVtkHdfReader(reader, timeValue, partitionIndex, numberOfPartitions)
            partition = self._mergedPartitions(reader.GetOutputDataObject(0))
            if partition is not None:
                sampledArrayInfos.append(getArrayInfosFromMesh(partition))
            self.monitor.check((sampleIndex + 1) / len(sampledPartitionIndices))
        arrayInfos = mergeArrayInfos(sampledArrayInfos)
        for arrayInfo in arrayInfos:
            if arrayInfo.location == POSITION_LOCATION:
                arrayInfo.componentRanges = [(bounds[0], bounds[1]), (bounds[2], bounds[3]),
                                             (bounds[4], bounds[5])]
            else:
                arrayInfo.isRangeApproximate = True
        return arrayInfos

    def _mergedPartitions(self, dataObject):
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
            partitions.append(iterator.GetCurrentDataObject())
            iterator.GoToNextItem()
        return self._appendedPartitions(partitions)

    def _appendedPartitions(self, partitions):
        """Append meshes into a single mesh, without merging points. None if they are all empty."""
        # A partition may be empty if a solver process had no part of the mesh assigned to it.
        partitions = [partition for partition in partitions
                      if partition is not None and partition.GetNumberOfPoints() > 0]
        if not partitions:
            return None
        if all(isinstance(partition, vtk.vtkPolyData) for partition in partitions):
            appendFilter = vtk.vtkAppendPolyData()
        else:
            appendFilter = vtk.vtkAppendFilter()
        for partition in partitions:
            appendFilter.AddInputData(partition)
        self.monitor.update(appendFilter)
        return appendFilter.GetOutput()

    # ------------------------------------------------------------------ cache

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

    def releaseCachedMesh(self, filePath) -> None:
        """Release the mesh of a file, for example because the file will be read in a different way."""
        self._meshCache.pop(os.path.normpath(filePath), None)

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

    def _isFileCached(self, filePath, approximateRangeCellCountThreshold):
        """True if the array information of the file is available without reading the file."""
        filePath = os.path.normpath(filePath)
        fileKey = self._fileCacheKey(filePath)
        if fileKey is None:
            return False
        cachedMesh = self._meshCache.get(filePath)
        if cachedMesh is not None and cachedMesh[0] == fileKey:
            return True
        cachedArrayInfos = self._approximateArrayInfoCache.get(filePath)
        return (approximateRangeCellCountThreshold is not None and cachedArrayInfos is not None
                and cachedArrayInfos[0] == (fileKey, approximateRangeCellCountThreshold)
                and cachedArrayInfos[1] is not None)

    def clearCache(self) -> None:
        self._meshCache = {}
        self._approximateArrayInfoCache = {}

    # ------------------------------------------------------------------ arrays of files

    def getArrayInfosFromFiles(self, filePaths, approximateRangeCellCountThreshold=None,
                               fileCompletedCallback=None):
        """Coordinates and data arrays of all input files, merged into a single list.

        Arrays that are present in several files are listed once, with the value range extended
        to cover all files, so that the same unit is used for all of them.

        :param approximateRangeCellCountThreshold: VTKHDF files with more cells than this are not
            read completely, and the value ranges of their data arrays are only approximate.
            None to always compute the exact ranges.
        :param fileCompletedCallback: called when a file has been processed, with the file path
            and the merged array information of the files that have been processed by then.
        :raises OperationCancelledError: if the operation is cancelled using the monitor. The
            files that have been read by then do not have to be read again.
        """
        self.monitor.reset()
        # Meshes of files that are no longer needed are released, so that the cache does not
        # keep growing as files are added to and removed from the input file list.
        normalizedFilePaths = [os.path.normpath(filePath) for filePath in filePaths]
        for cache in (self._meshCache, self._approximateArrayInfoCache):
            for cachedFilePath in list(cache):
                if cachedFilePath not in normalizedFilePaths:
                    del cache[cachedFilePath]

        mergedArrayInfos = []
        for filePath in filePaths:
            if not self._isFileCached(filePath, approximateRangeCellCountThreshold):
                self._log(_("Reading {filePath}").format(filePath=filePath))
            arrayInfos = None
            if approximateRangeCellCountThreshold is not None:
                arrayInfos = self._cachedApproximateArrayInfos(filePath, approximateRangeCellCountThreshold)
            if arrayInfos is None:
                arrayInfos = getArrayInfosFromMesh(self.getCachedMesh(filePath))
            mergedArrayInfos = mergeArrayInfos([mergedArrayInfos, arrayInfos])
            if fileCompletedCallback is not None:
                fileCompletedCallback(filePath, mergedArrayInfos)
            self.monitor.check()
        return mergedArrayInfos
