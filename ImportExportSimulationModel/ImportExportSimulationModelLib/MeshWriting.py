"""Writing of simulation mesh files."""

import os

import vtk

from slicer.i18n import tr as _

from ImportExportSimulationModelLib.OperationMonitor import (
    OperationCancelledError, OperationMonitor,
)


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


# Extensions of the files that can be written
WRITE_FILE_EXTENSIONS = [".vtu", ".vtp", ".vtk", ".stl", ".ply", ".obj"]
# Formats that cannot store data arrays
GEOMETRY_ONLY_FILE_EXTENSIONS = [".stl", ".ply", ".obj"]


def writeFileNameFilter():
    """File name filter of the files that can be written, for file selection dialogs."""
    return _("Simulation meshes") + " (" + " ".join(
        "*" + extension for extension in WRITE_FILE_EXTENSIONS) + ")"


#
# Writing
#


def writeMesh(mesh, filePath, logCallback=None, monitor=None):
    """Write a mesh to file, without any conversion.

    :param logCallback: called with a warning if something cannot be stored in the file.
    :param monitor: OperationMonitor that reports the progress, and lets the writing be cancelled.
    :raises OperationCancelledError: if the writing was cancelled. The incomplete file is removed.
    """
    if monitor is None:
        monitor = OperationMonitor()

    def log(text):
        if logCallback:
            logCallback(text)

    extension = os.path.splitext(filePath)[1].lower()
    if extension not in WRITE_FILE_EXTENSIONS:
        raise ValueError(_("Unsupported file format: {filePath}").format(filePath=filePath))
    if extension in GEOMETRY_ONLY_FILE_EXTENSIONS and (
            mesh.GetPointData().GetNumberOfArrays() or mesh.GetCellData().GetNumberOfArrays()):
        log(_("Warning: the {extension} file format cannot store data arrays, "
              "only the geometry is written.").format(extension=extension))
    if extension == ".vtu":
        writer = vtk.vtkXMLUnstructuredGridWriter()
        mesh = _asUnstructuredGrid(mesh, monitor)
    elif extension == ".vtp":
        writer = vtk.vtkXMLPolyDataWriter()
        mesh = _asPolyData(mesh, log, monitor)
    elif extension == ".vtk":
        if isinstance(mesh, vtk.vtkUnstructuredGrid):
            writer = vtk.vtkUnstructuredGridWriter()
        else:
            writer = vtk.vtkPolyDataWriter()
            mesh = _asPolyData(mesh, log, monitor)
        writer.SetFileTypeToBinary()
    elif extension == ".stl":
        writer = vtk.vtkSTLWriter()
        mesh = _asPolyData(mesh, log, monitor)
        writer.SetFileTypeToBinary()
    elif extension == ".ply":
        writer = vtk.vtkPLYWriter()
        mesh = _asPolyData(mesh, log, monitor)
        writer.SetFileTypeToBinary()
    else:
        writer = vtk.vtkOBJWriter()
        mesh = _asPolyData(mesh, log, monitor)
    directory = os.path.dirname(filePath)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    writer.SetFileName(filePath)
    writer.SetInputData(mesh)
    try:
        isWritten = monitor.update(writer, writer.Write)
    except OperationCancelledError:
        # The file may be incomplete.
        if os.path.isfile(filePath):
            os.remove(filePath)
        raise
    if not isWritten:
        raise RuntimeError(_("Failed to write {filePath}").format(filePath=filePath))


def _asPolyData(mesh, log, monitor):
    if isinstance(mesh, vtk.vtkPolyData):
        return mesh
    log(_("Warning: the mesh is converted to a surface mesh, volumetric cells are not written."))
    geometryFilter = vtk.vtkGeometryFilter()
    geometryFilter.SetInputData(mesh)
    monitor.update(geometryFilter)
    return geometryFilter.GetOutput()


def _asUnstructuredGrid(mesh, monitor):
    if isinstance(mesh, vtk.vtkUnstructuredGrid):
        return mesh
    appendFilter = vtk.vtkAppendFilter()
    appendFilter.SetInputData(mesh)
    monitor.update(appendFilter)
    return appendFilter.GetOutput()
