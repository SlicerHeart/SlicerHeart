"""Conversion between SlicerHeart 4D flow nodes and the arrays of the slicerheart_4dflow package.

slicerheart_4dflow (https://github.com/JolleyLab/slicerheart_4dflow) implements the 4D flow processing
algorithms (background phase correction, phase unwrapping, divergence-free filtering, encoding check,
quality report, flow quantification, pathlines, hemodynamics, wall shear stress, relative pressure) on
numpy arrays. Its conventions:

- arrays are indexed [k, j, i] (time first, vector components last), as slicer.util.arrayFromVolume
- image geometry is a 4x4 voxel_to_world matrix: here the IJK to RAS matrix, so world is RAS
- velocity is in mm/s (vector volume flow fields store the unit in their voxel value units, mm/s if not specified;
  flow fields stored in transforms, the legacy format, store m/s)

This module is the only place that knows about these conversions; both the Import 4D Flow and the
Analyze 4D Flow modules use it.
"""

import logging
import os
import sys

import numpy as np
import vtk
import vtk.util.numpy_support

import slicer

LIBRARY_NAME = "slicerheart_4dflow"
# Lowest version that has all the functions that the modules and their tests use (test case format 4, mask_fraction,
# estimate_lumen, testing_data for the clinical test data set)
MINIMUM_LIBRARY_VERSION = "0.5.0"
# Environment variable or application setting with the path of a slicerheart_4dflow source tree
# to install in editable mode (for development), instead of the released package.
LIBRARY_SOURCE_ENVIRONMENT_VARIABLE = "SLICERHEART_4DFLOW_SOURCE"
LIBRARY_SOURCE_SETTINGS_KEY = "SlicerHeart/slicerheart_4dflowSource"

M_PER_S_TO_MM_PER_S = 1000.0
# Velocity units that may be specified in the voxel value units of a vector volume flow field (same as Analyze 4D Flow)
VELOCITY_UNIT_TO_MM_PER_SEC = {"m/s": 1000.0, "cm/s": 10.0, "mm/s": 1.0}


def _versionTuple(version):
    """Release part of a version (development versions of a release count as that release)."""
    from packaging.version import Version
    return Version(version).release


def librarySource():
    """Path of a slicerheart_4dflow source tree to install from, or None to install the released package."""
    source = os.environ.get(LIBRARY_SOURCE_ENVIRONMENT_VARIABLE) or slicer.util.settingsValue(LIBRARY_SOURCE_SETTINGS_KEY, "")
    return source if source else None


def isLibraryAvailable():
    try:
        import slicerheart_4dflow
    except ImportError:
        return False
    version = getattr(slicerheart_4dflow, "__version__", "unknown")
    return version == "unknown" or _versionTuple(version) >= _versionTuple(MINIMUM_LIBRARY_VERSION)


def ensureLibrary(askConfirmation=True):
    """Import slicerheart_4dflow, installing or upgrading it if needed. Returns the module.

    The package is installed from the source tree set in the SLICERHEART_4DFLOW_SOURCE environment
    variable (or application setting SlicerHeart/slicerheart_4dflowSource) in editable mode if set,
    otherwise from PyPI. Raises RuntimeError if the package is not available and the user cancels.
    """
    if sys.version_info < (3, 12):
        raise RuntimeError(f"{LIBRARY_NAME} requires Python 3.12 or later (this Slicer has Python {sys.version.split()[0]})."
                           " Use Slicer 5.10 or later.")
    if isLibraryAvailable():
        import slicerheart_4dflow
        return slicerheart_4dflow

    source = librarySource()
    requirement = f"{LIBRARY_NAME}[clinical]>={MINIMUM_LIBRARY_VERSION}"
    location = f"the source tree at {source}" if source else "the Python Package Index"
    if askConfirmation and not slicer.app.testingEnabled():
        if not slicer.util.confirmOkCancelDisplay(
                f"This feature requires the {LIBRARY_NAME} Python package (version {MINIMUM_LIBRARY_VERSION} or later)."
                f" Click OK to install it from {location}.",
                windowTitle="Install required package"):
            raise RuntimeError(f"{LIBRARY_NAME} Python package is required but it was not installed")
    if source:
        logging.info(f"Installing {LIBRARY_NAME} from {source}")
        slicer.util.pip_install(["--upgrade", "--editable", f"{source}[clinical]"])
    else:
        logging.info(f"Installing {requirement}")
        slicer.util.pip_install(["--upgrade", requirement])

    # Editable installs add the source tree to the path by a .pth file, which is only processed at startup
    import importlib
    import site
    for siteDirectory in site.getsitepackages() + [site.getusersitepackages()]:
        if os.path.isdir(siteDirectory):
            site.addsitedir(siteDirectory)
    importlib.invalidate_caches()
    for name in [name for name in sys.modules if name == LIBRARY_NAME or name.startswith(LIBRARY_NAME + ".")]:
        del sys.modules[name]
    import slicerheart_4dflow
    if not isLibraryAvailable():
        raise RuntimeError(f"{LIBRARY_NAME} {slicerheart_4dflow.__version__} was installed, but version"
                           f" {MINIMUM_LIBRARY_VERSION} or later is required. Set {LIBRARY_SOURCE_ENVIRONMENT_VARIABLE}"
                           " to a source tree to install a development version.")
    return slicerheart_4dflow


#
# Geometry
#

def voxelToWorld(volumeNode):
    """4x4 IJK to RAS matrix of a volume node as a numpy array (voxel_to_world of the library, world = RAS).
    Parent transforms are not applied: flow fields and their images are not expected to be transformed.
    """
    matrix = vtk.vtkMatrix4x4()
    volumeNode.GetIJKToRASMatrix(matrix)
    return slicer.util.arrayFromVTKMatrix(matrix)


def setVoxelToWorld(volumeNode, voxelToWorldMatrix):
    volumeNode.SetIJKToRASMatrix(slicer.util.vtkMatrixFromArray(np.asarray(voxelToWorldMatrix, float)))


#
# Sequences
#

def sequenceFromProxyNode(proxyNode):
    browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(proxyNode)
    if not browserNode:
        raise ValueError(f"{proxyNode.GetName()} is not the proxy node of a sequence")
    return browserNode.GetSequenceNode(proxyNode)


def sequenceIndexValues(sequenceNode):
    """Index values of a sequence as floats (trigger times in ms for 4D flow), or the item numbers if not numeric."""
    values = []
    for itemIndex in range(sequenceNode.GetNumberOfDataNodes()):
        try:
            values.append(float(sequenceNode.GetNthIndexValue(itemIndex)))
        except ValueError:
            values.append(float(itemIndex))
    return np.array(values)


def _flowFieldFrameArray(frameNode):
    """Velocity vectors (k, j, i, 3) of one flow field frame (m/s, RAS) without copying, from a vector volume
    or a grid transform node."""
    if frameNode.IsA("vtkMRMLVectorVolumeNode"):
        return slicer.util.arrayFromVolume(frameNode)
    # Frames in transform sequences store the displacement grid as "transform to parent" (see
    # Import4DFlowLogic._addFlowFieldFrameToSequence).
    gridTransform = frameNode.GetTransformToParentAs("vtkOrientedGridTransform", False)
    if gridTransform is None or gridTransform.GetInverseFlag():
        raise ValueError(f"Flow field frame {frameNode.GetName()} does not contain a displacement grid")
    import vtk.util.numpy_support
    image = gridTransform.GetDisplacementGrid()
    scalars = vtk.util.numpy_support.vtk_to_numpy(image.GetPointData().GetScalars())
    return scalars.reshape(*image.GetDimensions()[::-1], 3)


def flowFieldGeometryNode(flowFieldNode):
    """Volume node that defines the voxel grid of the flow field (the magnitude volume for flow fields
    created by Import 4D Flow, or the flow field itself if it is a vector volume)."""
    magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
    if magnitudeVolumeNode:
        return magnitudeVolumeNode
    if flowFieldNode.IsA("vtkMRMLVolumeNode"):
        return flowFieldNode
    raise ValueError("Flow field has no magnitude volume reference, cannot determine its voxel grid")


def velocityUnitScaleToMmPerSec(node):
    """Factor that converts stored velocity values of a flow field frame (or flow field proxy node) to mm/s.
    The unit is read from the voxel value units of a vector volume ("m/s", "cm/s" or "mm/s"); vector volumes without
    units are in mm/s. Flow fields stored in transforms (legacy format) are in m/s."""
    if not node.IsA("vtkMRMLScalarVolumeNode"):
        return M_PER_S_TO_MM_PER_S
    voxelValueUnits = node.GetVoxelValueUnits()
    velocityUnit = voxelValueUnits.GetCodeValue() if voxelValueUnits else None
    if not velocityUnit:
        return 1.0
    velocityUnit = velocityUnit.strip().lower().replace(" ", "")
    if velocityUnit not in VELOCITY_UNIT_TO_MM_PER_SEC:
        raise ValueError(f"Unsupported voxel value unit '{velocityUnit}' of flow field {node.GetName()}."
                         f" Supported velocity units: {', '.join(VELOCITY_UNIT_TO_MM_PER_SEC.keys())}")
    return VELOCITY_UNIT_TO_MM_PER_SEC[velocityUnit]


def _hasVoxelValueUnits(node):
    return node.IsA("vtkMRMLScalarVolumeNode") and node.GetVoxelValueUnits() is not None and bool(node.GetVoxelValueUnits().GetCodeValue())


def _frameScaleToMmPerSec(frameNode, flowFieldNode):
    """Unit scale of a frame node in a flow field sequence: its own voxel value units, those of the proxy node, or the
    SlicerHeart.velocityUnit attribute of the sequence (voxel value units of volumes are not kept in sequences in all
    Slicer versions). Without any of these, a vector volume frame is in mm/s (a transform frame in m/s)."""
    for node in [frameNode, flowFieldNode]:
        if _hasVoxelValueUnits(node):
            return velocityUnitScaleToMmPerSec(node)
    if frameNode.IsA("vtkMRMLScalarVolumeNode"):
        sequenceNode = sequenceFromProxyNode(flowFieldNode) if flowFieldNode.IsA("vtkMRMLScalarVolumeNode") else None
        velocityUnit = (sequenceNode.GetAttribute("SlicerHeart.velocityUnit") or "").strip().lower() if sequenceNode else ""
        if velocityUnit in VELOCITY_UNIT_TO_MM_PER_SEC:
            return VELOCITY_UNIT_TO_MM_PER_SEC[velocityUnit]
    return velocityUnitScaleToMmPerSec(frameNode)


def velocityArrayFromFlowField(flowFieldNode):
    """Velocity of all frames of a flow field. Returns (velocity_t, voxelToWorld, timesMs):
    velocity_t (nt, nk, nj, ni, 3) float32 in mm/s, RAS components; voxelToWorld (4x4) IJK to RAS.
    """
    sequenceNode = sequenceFromProxyNode(flowFieldNode)
    geometryNode = flowFieldGeometryNode(flowFieldNode)
    frameNodes = [sequenceNode.GetNthDataNode(itemIndex) for itemIndex in range(sequenceNode.GetNumberOfDataNodes())]
    velocity = np.stack([_flowFieldFrameArray(frameNode).astype(np.float32) * np.float32(_frameScaleToMmPerSec(frameNode, flowFieldNode))
                         for frameNode in frameNodes])
    if flowFieldNode.IsA("vtkMRMLVectorVolumeNode") and not flowFieldNode.GetNodeReference("magnitudeVolume"):
        voxelToWorldMatrix = voxelToWorld(sequenceNode.GetNthDataNode(0))
    else:
        voxelToWorldMatrix = voxelToWorld(geometryNode)
    return velocity, voxelToWorldMatrix, sequenceIndexValues(sequenceNode)


def magnitudeArray(flowFieldNode):
    """Magnitude images of all frames (nt, nk, nj, ni) float32."""
    sequenceNode = sequenceFromProxyNode(flowFieldNode.GetNodeReference("magnitudeVolume"))
    return np.stack([slicer.util.arrayFromVolume(sequenceNode.GetNthDataNode(i))
                     for i in range(sequenceNode.GetNumberOfDataNodes())]).astype(np.float32)


#
# Input (raw) flow field
#
# The input flow field contains the velocity as acquired (aliased, before any correction) in RAS components. It is created
# from the component images (Import4DFlowLogic.createInputFlowFieldFromComponentVolumes) or loaded from file. Its sequence
# stores the velocity encoding in attributes (see setRawEncoding). Output flow fields (processing results) reference their
# input flow field by the "inputFlowField" node reference.

RAW_ROLE_ATTRIBUTE = "SlicerHeart.FlowFieldRole"
VENC_ENCODED_ATTRIBUTE = "SlicerHeart.vencEncodedMmPerSec"
ENCODING_TO_WORLD_ATTRIBUTE = "SlicerHeart.encodingToWorld"
DIRECTION_CODES_ATTRIBUTE = "SlicerHeart.directionCodes"
COMPONENT_MAX_VALUES_ATTRIBUTE = "SlicerHeart.componentMaxValues"


def isRawFlowField(flowFieldNode):
    """True if the node is an input (raw) flow field: velocity as acquired, with velocity encoding information."""
    try:
        sequenceNode = sequenceFromProxyNode(flowFieldNode)
    except ValueError:
        return False
    return sequenceNode.GetAttribute(RAW_ROLE_ATTRIBUTE) == "raw"


def rawFlowFieldNode(flowFieldNode):
    """Input (raw) flow field of a flow field: the flow field itself if it is an input flow field, otherwise the flow field
    referenced as "inputFlowField" (output flow fields). Raises ValueError if there is none."""
    if flowFieldNode is None:
        raise ValueError("No flow field is specified")
    if isRawFlowField(flowFieldNode):
        return flowFieldNode
    inputFlowFieldNode = flowFieldNode.GetNodeReference("inputFlowField")
    if inputFlowFieldNode is not None:
        return inputFlowFieldNode
    raise ValueError(f"Flow field {flowFieldNode.GetName()} has no input flow field (velocity as acquired, with velocity encoding)")


def setRawEncoding(flowFieldNode, vencEncodedMmPerSec, encodingToWorldMatrix, directionCodes=None, componentMaxValues=None):
    """Mark a flow field as input (raw) flow field and store its velocity encoding in attributes of its sequence:
    vencEncodedMmPerSec: velocity encoding of the 3 encoded components (mm/s); encodingToWorldMatrix: 3x3, columns are the
    RAS directions of the encoded components; directionCodes: names of the encoded components (for example "through");
    componentMaxValues: stored value of the component images that corresponds to the velocity encoding (for reference)."""
    sequenceNode = sequenceFromProxyNode(flowFieldNode)
    sequenceNode.SetAttribute(RAW_ROLE_ATTRIBUTE, "raw")
    sequenceNode.SetAttribute(VENC_ENCODED_ATTRIBUTE, ",".join(f"{float(v):g}" for v in vencEncodedMmPerSec))
    sequenceNode.SetAttribute(ENCODING_TO_WORLD_ATTRIBUTE, ",".join(f"{float(v):g}" for v in np.asarray(encodingToWorldMatrix, float).ravel()))
    if directionCodes is not None:
        sequenceNode.SetAttribute(DIRECTION_CODES_ATTRIBUTE, ",".join(directionCodes))
    if componentMaxValues is not None:
        sequenceNode.SetAttribute(COMPONENT_MAX_VALUES_ATTRIBUTE, ",".join(f"{float(v):g}" for v in componentMaxValues))


def _rawAttributeValues(flowFieldNode, attributeName):
    value = sequenceFromProxyNode(rawFlowFieldNode(flowFieldNode)).GetAttribute(attributeName)
    return value.split(",") if value else None


def vencEncodedMmPerSec(flowFieldNode):
    """Velocity encoding of the 3 encoded velocity components of the input flow field (mm/s).
    If the input flow field has no velocity encoding information (for example, loaded from a file without it), the
    largest absolute raw velocity of each component is used, as the raw velocity is within [-venc, venc]."""
    values = _rawAttributeValues(flowFieldNode, VENC_ENCODED_ATTRIBUTE)
    if values:
        return np.array([float(v) for v in values])
    return np.abs(rawEncodedVelocity(flowFieldNode)).reshape(-1, 3).max(axis=0).astype(float)


def encodingToWorld(flowFieldNode):
    """3x3 matrix whose columns are the RAS directions of the encoded velocity components (identity if not specified)."""
    values = _rawAttributeValues(flowFieldNode, ENCODING_TO_WORLD_ATTRIBUTE)
    return np.array([float(v) for v in values]).reshape(3, 3) if values else np.eye(3)


def directionCodes(flowFieldNode):
    """Names of the encoded velocity components (for example ["through", "inplane_ap", "inplane_fh"])."""
    try:
        values = _rawAttributeValues(flowFieldNode, DIRECTION_CODES_ATTRIBUTE)
    except ValueError:
        values = None
    return values if values else [f"C{component + 1}" for component in range(3)]


def componentEncoding(flowFieldNode):
    """Velocity encoding of the input flow field. Returns (scalesMmPerSecPerValue, vencMmPerSec, invertToRas):
    stored value of the component images * scale = encoded velocity (scale is 1 if the component images are not known),
    invertToRas[c] is True if the encoded component `c` points opposite to its RAS axis."""
    vencs = vencEncodedMmPerSec(flowFieldNode)
    maxValues = _rawAttributeValues(flowFieldNode, COMPONENT_MAX_VALUES_ATTRIBUTE)
    scales = vencs / np.array([float(v) for v in maxValues]) if maxValues else np.ones(3)
    invertToRas = np.diag(encodingToWorld(flowFieldNode)) < 0
    return scales, vencs, invertToRas


def rawWorldVelocity(flowFieldNode):
    """Raw velocity (as acquired: aliased, before any correction) of the input flow field: (nt, nk, nj, ni, 3) float32
    mm/s, RAS components."""
    velocity, _, _ = velocityArrayFromFlowField(rawFlowFieldNode(flowFieldNode))
    return velocity


def rawEncodedVelocity(flowFieldNode):
    """Raw velocity as encoded components: (nt, nk, nj, ni, 3) float32 mm/s, each component aliased in [-venc, venc).
    Component c is the velocity along encodingToWorld(flowFieldNode)[:, c] (orthonormal encoding directions)."""
    return rawWorldVelocity(flowFieldNode) @ encodingToWorld(flowFieldNode).astype(np.float32)


#
# Segmentations, markups, outputs
#

def _segmentBinaryLabelmap(segmentationNode, segmentId):
    """Binary labelmap (0/1, unsigned char) of a segment in its own geometry. Segments may share a labelmap, where each
    segment has its own label value, therefore the voxels of the segment's label value are selected."""
    labelmap = slicer.vtkOrientedImageData()
    slicer.vtkSlicerSegmentationsModuleLogic.GetSegmentBinaryLabelmapRepresentation(segmentationNode, segmentId, labelmap)
    extent = labelmap.GetExtent()
    if extent[1] < extent[0] or extent[3] < extent[2] or extent[5] < extent[4] or not labelmap.GetPointData().GetScalars():
        return None
    labelValue = segmentationNode.GetSegmentation().GetSegment(segmentId).GetLabelValue()
    voxels = vtk.util.numpy_support.vtk_to_numpy(labelmap.GetPointData().GetScalars())
    binary = slicer.vtkOrientedImageData()
    binary.ShallowCopy(labelmap)
    binary.CopyDirections(labelmap)
    binary.SetSpacing(labelmap.GetSpacing())
    binary.SetOrigin(labelmap.GetOrigin())
    binaryScalars = vtk.util.numpy_support.numpy_to_vtk((voxels == labelValue).astype(np.uint8), deep=True,
                                                        array_type=vtk.VTK_UNSIGNED_CHAR)
    binary.GetPointData().SetScalars(binaryScalars)
    return binary


def segmentLabelmap(segmentationNode, segmentId):
    """Binary labelmap of a segment in its own geometry (the resolution of the segmentation's labelmap, which may be
    finer than the image, cropped to the segment): (mask (nk, nj, ni) bool, voxelToWorld 4x4 IJK to RAS).
    The parent transform of the segmentation is not applied. Returns (None, None) for an empty segment."""
    labelmap = _segmentBinaryLabelmap(segmentationNode, segmentId)
    if labelmap is None:
        return None, None
    extent = labelmap.GetExtent()
    imageToWorld = vtk.vtkMatrix4x4()
    labelmap.GetImageToWorldMatrix(imageToWorld)
    voxelToWorldMatrix = slicer.util.arrayFromVTKMatrix(imageToWorld)
    # Index (0, 0, 0) of the array is the first voxel of the extent
    voxelToWorldMatrix = voxelToWorldMatrix @ np.array([[1, 0, 0, extent[0]], [0, 1, 0, extent[2]], [0, 0, 1, extent[4]], [0, 0, 0, 1]], float)
    dims = (extent[5] - extent[4] + 1, extent[3] - extent[2] + 1, extent[1] - extent[0] + 1)
    mask = vtk.util.numpy_support.vtk_to_numpy(labelmap.GetPointData().GetScalars()).reshape(dims) > 0
    return mask, voxelToWorldMatrix


def setSegmentFromMask(segmentationNode, segmentId, mask, voxelToWorldMatrix, name=None, color=(0.85, 0.2, 0.2)):
    """Replace the content of a segment (added if it does not exist) by a mask (nk, nj, ni) on the grid of
    voxelToWorldMatrix (IJK to RAS), which may be finer than the image grid. The grid becomes the reference geometry of
    the segmentation, so that editing (Segment Editor) and saving keep its resolution."""
    labelmap = slicer.vtkOrientedImageData()
    nk, nj, ni = mask.shape
    labelmap.SetDimensions(ni, nj, nk)
    labelmap.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    vtk.util.numpy_support.vtk_to_numpy(labelmap.GetPointData().GetScalars())[:] = np.asarray(mask).astype(np.uint8).ravel()
    labelmap.SetImageToWorldMatrix(slicer.util.vtkMatrixFromArray(np.asarray(voxelToWorldMatrix, float)))
    segmentation = segmentationNode.GetSegmentation()
    segmentation.SetConversionParameter(slicer.vtkSegmentationConverter.GetReferenceImageGeometryParameterName(),
                                        slicer.vtkSegmentationConverter.SerializeImageGeometry(labelmap))
    if not segmentation.GetSegment(segmentId):
        segmentation.AddEmptySegment(segmentId, name or segmentId, list(color))
    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(
        labelmap, segmentationNode, segmentId, slicer.vtkSlicerSegmentationsModuleLogic.MODE_REPLACE, labelmap.GetExtent())


def maskFractionFromSegment(segmentationNode, segmentId, referenceVolumeNode):
    """Fraction (nk, nj, ni) float32 of each voxel of the reference volume inside a segment. A segment on a finer grid
    (as Import4DFlow creates the lumen) gives partial voxels at its boundary; resampled in world space with VTK
    (slicerheart_4dflow.mask_fraction), not with nearest neighbour, which is ambiguous where the voxel centers of the
    reference lie on the boundaries of the finer voxels."""
    dims = referenceVolumeNode.GetImageData().GetDimensions()
    shape = (dims[2], dims[1], dims[0])
    mask, maskVoxelToWorld = segmentLabelmap(segmentationNode, segmentId)
    if mask is None:
        return np.zeros(shape, np.float32)
    return ensureLibrary().mask_fraction(mask, maskVoxelToWorld, shape, voxelToWorld(referenceVolumeNode))


def maskFromSegment(segmentationNode, segmentId, referenceVolumeNode):
    """Binary mask (nk, nj, ni) bool of a segment on the voxel grid of the reference volume: the voxels at least half in
    the segment (see maskFractionFromSegment)."""
    return maskFractionFromSegment(segmentationNode, segmentId, referenceVolumeNode) >= 0.5


def planeParameters(planeNode, radiusMm=None):
    """Centre, unit normal (RAS) and disc radius (half of the smaller plane size, if not specified) of a markups plane."""
    centre = np.array(planeNode.GetCenterWorld())
    normal = np.array(planeNode.GetNormalWorld())
    if radiusMm is None:
        size = planeNode.GetSize()
        radiusMm = 0.5 * min(size[0], size[1])
        if radiusMm <= 0:
            bounds = planeNode.GetPlaneBounds()
            radiusMm = 0.5 * min(bounds[1] - bounds[0], bounds[3] - bounds[2])
    return dict(centre=centre, normal=normal / np.linalg.norm(normal), radius=float(radiusMm))


def updateScalarVolumeSequence(sequenceNode, arrays_t, voxelToWorldMatrix, indexValues, name=None):
    """Replace the content of a sequence node with scalar volumes created from arrays_t (nt, nk, nj, ni)."""
    sequenceNode.RemoveAllDataNodes()
    for itemIndex, array in enumerate(arrays_t):
        volumeNode = slicer.vtkMRMLScalarVolumeNode()
        slicer.util.updateVolumeFromArray(volumeNode, np.ascontiguousarray(array))
        setVoxelToWorld(volumeNode, voxelToWorldMatrix)
        if name:
            volumeNode.SetName(name)
        sequenceNode.SetDataNodeAtValue(volumeNode, _indexString(indexValues[itemIndex]))
    return sequenceNode


def _indexString(value):
    value = float(value)
    return f"{value:g}"


def createScalarVolumeSequenceInBrowser(name, arrays_t, voxelToWorldMatrix, indexValues, browserNode=None, existingProxyNode=None):
    """Create (or update) a scalar volume sequence and show it in a sequence browser.
    If browserNode is given then the sequence is synchronized with it, so it is browsed together with the flow field.
    Returns the proxy (scalar volume) node."""
    sequenceNode = None
    if existingProxyNode:
        existingBrowser = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(existingProxyNode)
        if existingBrowser:
            sequenceNode = existingBrowser.GetSequenceNode(existingProxyNode)
            browserNode = existingBrowser
    if sequenceNode is None:
        sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
        sequenceNode.SetIndexName("time")
        sequenceNode.SetIndexUnit("ms")
        sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.NumericIndex)
    updateScalarVolumeSequence(sequenceNode, arrays_t, voxelToWorldMatrix, indexValues, name)
    if browserNode is None:
        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", name + " browser")
        browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
    elif not browserNode.IsSynchronizedSequenceNode(sequenceNode, True):
        browserNode.AddSynchronizedSequenceNodeID(sequenceNode.GetID())
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
    proxyNode = browserNode.GetProxyNode(sequenceNode)
    if proxyNode and not proxyNode.GetDisplayNode():
        proxyNode.CreateDefaultDisplayNodes()
    return proxyNode


def updateModelFromPolyData(modelNode, polyData):
    modelNode.SetAndObservePolyData(polyData)
    if not modelNode.GetDisplayNode():
        modelNode.CreateDefaultDisplayNodes()
    return modelNode


def updateTableFromColumns(tableNode, columns):
    """Replace the content of a table node with columns {name: list of numbers or strings} (all the same length)."""
    table = tableNode.GetTable()
    tableNode.RemoveAllColumns()
    for name, values in columns.items():
        values = list(values)
        if values and isinstance(values[0], str):
            array = vtk.vtkStringArray()
            for value in values:
                array.InsertNextValue(value)
        else:
            array = vtk.vtkDoubleArray()
            for value in values:
                array.InsertNextValue(float("nan") if value is None else float(value))
        array.SetName(name)
        table.AddColumn(array)
    tableNode.Modified()
    return tableNode
