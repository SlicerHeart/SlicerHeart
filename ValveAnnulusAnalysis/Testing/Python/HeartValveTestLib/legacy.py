"""
LegacySceneBuilder: build old-format (pre-4D) SlicerHeart scenes with plain MRML calls.

The old format (master branch of SlicerHeart) stores one HeartValve parameter node per analyzed
cardiac phase. Each of them owns its own annulus contour, labels, ROI, leaflet volume/segmentation,
leaflet surfaces, coaptation and papillary nodes, all referenced from the HeartValve node with the
role names below and organised in subject hierarchy folders. This module reproduces that node graph
without using the branch API (HeartValveLib), so the conversion tests start from data that looks
exactly like a scene saved by the old modules.

Node roles, attributes, names and folders follow
``git show master:ValveAnnulusAnalysis/HeartValveLib/ValveModel.py`` (setHeartValveNodeDefaults,
createXxxNode, addLeafletModel, addCoaptationModel, updatePapillaryModel, updateValveNodeNames) and
``master:ValveQuantification/ValveQuantificationLib/MeasurementPreset.py`` (result tables).
"""

import numpy as np
import vtk
import slicer

from . import scene
from .newformat import NewFormatValveFactory


PHASE_SHORT_NAMES = {
  "unknown": "UN", "mid-systole": "MS", "end-systole": "ES", "mid-diastole": "MD", "end-diastole": "ED",
  "custom-systolic": "CS", "custom-transition": "CT", "custom-diastolic": "CD",
  "custom1": "P1", "custom2": "P2", "custom3": "P3", "custom4": "P4",
}

PHASE_COLORS = {
  "unknown": (0.3, 0.3, 1.0), "mid-systole": (1.0, 0.0, 0.0), "end-systole": (1.0, 1.0, 0.0),
  "mid-diastole": (0.0, 0.0, 1.0), "end-diastole": (0.0, 1.0, 1.0), "custom-systolic": (0.82, 0.09, 0.81),
  "custom-transition": (1.0, 0.56, 0.18), "custom-diastolic": (0.02, 0.76, 0.04), "custom1": (0.0, 1.0, 0.0),
  "custom2": (1.0, 0.0, 1.0), "custom3": (0.5, 0.5, 1.0), "custom4": (1.0, 0.5, 0.5),
}

PAPILLARY_NAMES = {
  "mitral": ["antero-lateral", "postero-medial"],
  "tricuspid": ["anterior", "posterior"],
  "aortic": ["papillary1", "papillary2", "papillary3"],
  "cavc": ["anterior", "posterior", "superior-lateral", "inferior-lateral"],
  "lavv": ["superior-lateral", "inferior-lateral"],
}

VALVE_MASK_SEGMENT_ID = "ValveMask"

DEFAULT_ROI_PARAMS = {"ValveRoiScale": 120, "ValveRoiTopDistance": 10, "ValveRoiTopScale": 50,
                      "ValveRoiBottomDistance": 30, "ValveRoiBottomScale": 50}


def valveTypeName(valveType):
  return valveType[0].upper() + valveType[1:]


def legacyValveNodeName(valveType, phase, frameIndex):
  """Name used by master ``ValveModel.updateValveNodeNames``: e.g. ``MitralValve-MS_f6``."""
  return f"{valveTypeName(valveType)}Valve-{PHASE_SHORT_NAMES[phase]}_f{frameIndex + 1}"


def expectedProxyName(valveType):
  """Name the converter gives the valve proxy (``MitralValve``)."""
  return f"{valveTypeName(valveType)}Valve"


def shNode():
  return slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)


def _tubeAround(points, radius=0.4):
  """Small tube polydata through the given (closed) points, like the legacy AnnulusContourModel."""
  vtkPoints = vtk.vtkPoints()
  for p in points:
    vtkPoints.InsertNextPoint(*p)
  lines = vtk.vtkCellArray()
  lines.InsertNextCell(len(points) + 1)
  for i in range(len(points)):
    lines.InsertCellPoint(i)
  lines.InsertCellPoint(0)
  poly = vtk.vtkPolyData()
  poly.SetPoints(vtkPoints)
  poly.SetLines(lines)
  tube = vtk.vtkTubeFilter()
  tube.SetInputData(poly)
  tube.SetRadius(radius)
  tube.SetNumberOfSides(8)
  tube.Update()
  return tube.GetOutput()


def _cylinder(radius=3.0, height=6.0, center=(0, 0, 0)):
  source = vtk.vtkCylinderSource()
  source.SetRadius(radius)
  source.SetHeight(height)
  source.SetCenter(*center)
  source.SetResolution(16)
  source.Update()
  return source.GetOutput()


def _stripBetween(pointsA, pointsB):
  points = vtk.vtkPoints()
  for p in list(pointsA) + list(pointsB):
    points.InsertNextPoint(*p)
  strips = vtk.vtkCellArray()
  strips.InsertNextCell(len(pointsA) * 2)
  for i in range(len(pointsA)):
    strips.InsertCellPoint(i)
    strips.InsertCellPoint(len(pointsA) + i)
  poly = vtk.vtkPolyData()
  poly.SetPoints(points)
  poly.SetStrips(strips)
  tri = vtk.vtkTriangleFilter()
  tri.SetInputData(poly)
  tri.Update()
  return tri.GetOutput()


class LegacyValveRecord:
  """Everything the builder created for one legacy valve phase, plus the expected data."""

  def __init__(self):
    self.node = None
    self.valveType = None
    self.phase = None
    self.frameIndex = None
    self.indexValue = None
    self.contourPoints = None
    self.labels = None
    self.roiParams = None
    self.axialMatrix = None
    self.segmentIds = []
    self.segmentNames = {}
    self.segmentColors = {}
    self.leafletVolumeValue = None
    self.nodes = {}          # role -> node or list of nodes (Nth roles)
    self.leafletOrder = []
    self.papillaryPoints = {}
    self.coaptationPoints = None
    self.boundaryPoints = {}


class LegacySceneBuilder:
  """Builds old-format multi-phase heart valve annotations on a volume sequence."""

  def __init__(self, volumeBrowserNode=None, numFrames=6, name="SyntheticUS"):
    if volumeBrowserNode is None:
      volumeBrowserNode, _, _ = scene.createSyntheticVolumeSequence(numFrames=numFrames, name=name)
    self.volumeBrowserNode = volumeBrowserNode
    self.volumeSequenceNode = volumeBrowserNode.GetMasterSequenceNode()
    self.volumeProxyNode = volumeBrowserNode.GetProxyNode(self.volumeSequenceNode)
    self.valves = []
    self.measurements = []
    self.devices = []
    # The old ValveModel.setValveVolumeNode created a ProbeToRasTransform under the volume
    self.probeToRasTransformNode = self.volumeProxyNode.GetParentTransformNode()
    if self.probeToRasTransformNode is None:
      self.probeToRasTransformNode = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLLinearTransformNode", slicer.mrmlScene.GetUniqueNameByString("ProbeToRasTransform"))
      self.volumeProxyNode.SetAndObserveTransformNodeID(self.probeToRasTransformNode.GetID())
      sh = shNode()
      sh.SetItemParent(sh.GetItemByDataNode(self.probeToRasTransformNode), sh.GetItemByDataNode(self.volumeProxyNode))

  # ---------------------------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------------------------

  def indexValue(self, frameIndex):
    return self.volumeSequenceNode.GetNthIndexValue(frameIndex)

  def _applyProbe(self, node):
    node.SetAndObserveTransformNodeID(self.probeToRasTransformNode.GetID())

  def _moveToValveFolder(self, valveNode, node, subfolderName=None):
    sh = shNode()
    valveItemId = sh.GetItemByDataNode(valveNode)
    if subfolderName:
      folderItemId = sh.GetItemChildWithName(valveItemId, subfolderName)
      if not folderItemId:
        folderItemId = sh.CreateFolderItem(valveItemId, subfolderName)
    else:
      folderItemId = valveItemId
    sh.SetItemParent(sh.GetItemByDataNode(node), folderItemId)

  def _uniqueName(self, name, uniquify):
    return slicer.mrmlScene.GetUniqueNameByString(name) if uniquify else name

  def _fiducialNode(self, name, points, labels=None, locked=False, uniquify=True):
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", self._uniqueName(name, uniquify))
    node.CreateDefaultDisplayNodes()
    node.SetMarkupLabelFormat("")
    for i, p in enumerate(points):
      idx = node.AddControlPoint(p[0], p[1], p[2])
      if labels:
        node.SetNthControlPointLabel(idx, labels[i])
      else:
        node.SetNthControlPointLabel(idx, "")
    node.SetLocked(locked)
    self._applyProbe(node)
    return node

  def _curveNode(self, className, name, points, uniquify=True):
    node = slicer.mrmlScene.AddNewNodeByClass(className, self._uniqueName(name, uniquify))
    node.CreateDefaultDisplayNodes()
    node.SetMarkupLabelFormat("")
    for p in points:
      node.AddControlPoint(p[0], p[1], p[2])
    self._applyProbe(node)
    return node

  def _modelNode(self, name, polyData, color=(1, 1, 1), uniquify=True):
    node = slicer.modules.models.logic().AddModel(polyData)
    node.SetName(self._uniqueName(name, uniquify))
    node.GetDisplayNode().SetColor(*color)
    self._applyProbe(node)
    return node

  # ---------------------------------------------------------------------------------------------
  # Valves
  # ---------------------------------------------------------------------------------------------

  def addLegacyValve(self, valveType="mitral", frameIndex=1, phase="mid-systole", contour=True, labels=True,
                     roi=True, segmentation=True, leaflets=True, coaptation=False, papillary=False,
                     clippedVolume=False, segmentIds=("Anterior", "Posterior"), leafletOrder=None,
                     legacyFiducialContour=True, probePosition="TTE_APICAL", frameIndexAttribute=None,
                     uniquifyNames=True, extraAttributes=None):
    """Create one old-format HeartValve node (one analyzed phase) with its referenced nodes.

    :param legacyFiducialContour: True -> annulus contour stored as vtkMRMLMarkupsFiducialNode plus
      an AnnulusContourModel tube (very old scenes); False -> closed curve node (scenes saved after
      the markups-curve migration but before the 4D format).
    :param leafletOrder: order in which leaflet references are added (defaults to *segmentIds*)
    :param frameIndexAttribute: override the ValveVolumeSequenceIndex attribute string (e.g. "-1",
      "abc"); the volume frame used for the leaflet volume is still *frameIndex* when valid.
    :returns: LegacyValveRecord
    """
    record = LegacyValveRecord()
    record.valveType = valveType
    record.phase = phase
    record.frameIndex = frameIndex
    record.indexValue = self.indexValue(frameIndex) if 0 <= frameIndex < self.volumeSequenceNode.GetNumberOfDataNodes() else None
    sh = shNode()

    valveNode = slicer.vtkMRMLScriptedModuleNode()
    valveNode.SetHideFromEditors(False)
    valveNode.SetAttribute("ModuleName", "HeartValve")
    slicer.mrmlScene.AddNode(valveNode)
    valveNode.SetName(slicer.mrmlScene.GetUniqueNameByString(legacyValveNodeName(valveType, phase, frameIndex)))
    valveNode.SetAttribute("ValveType", valveType)
    valveNode.SetAttribute("CardiacCyclePhase", phase)
    valveNode.SetAttribute("ValveVolumeSequenceIndex", str(frameIndex) if frameIndexAttribute is None else frameIndexAttribute)
    valveNode.SetAttribute("AnnulusContourRadius", "0.5")
    valveNode.SetAttribute("ProbePosition", probePosition)
    for key, value in (extraAttributes or {}).items():
      valveNode.SetAttribute(key, value)
    sh.RequestOwnerPluginSearch(valveNode)
    valveItemId = sh.GetItemByDataNode(valveNode)
    if not valveItemId:
      valveItemId = sh.CreateItem(sh.GetSceneItemID(), valveNode)
    sh.SetItemAttribute(valveItemId, "ModuleName", "HeartValve")
    record.node = valveNode
    valveNode.SetNodeReferenceID("ValveVolume", self.volumeProxyNode.GetID())
    record.nodes["ValveVolume"] = self.volumeProxyNode

    # Axial slice orientation, distinct per phase
    axial = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode",
                                               self._uniqueName("AxialSliceToRasTransform", uniquifyNames))
    matrix = scene.rotationMatrixZ(15.0 * frameIndex + 5.0, translation=(0.5 * frameIndex, 0.0, 0.0))
    axial.SetMatrixTransformToParent(matrix)
    sh.SetItemAttribute(sh.GetItemByDataNode(axial),
                        slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyExcludeFromTreeAttributeName(), "1")
    self._moveToValveFolder(valveNode, axial)
    valveNode.SetNodeReferenceID("AxialSliceToRasTransform", axial.GetID())
    record.axialMatrix = matrix
    record.nodes["AxialSliceToRasTransform"] = axial

    phaseColor = PHASE_COLORS[phase]
    if contour:
      points = NewFormatValveFactory.contourPoints(frameIndex)
      record.contourPoints = points
      if legacyFiducialContour:
        contourNode = self._fiducialNode("AnnulusContourMarkup", points, uniquify=uniquifyNames)
        contourNode.GetDisplayNode().SetColor(*phaseColor)
        contourNode.GetDisplayNode().SetSelectedColor(*phaseColor)
        contourModel = self._modelNode("AnnulusContourModel", _tubeAround(points), color=phaseColor, uniquify=uniquifyNames)
        self._moveToValveFolder(valveNode, contourModel)
        valveNode.SetNodeReferenceID("AnnulusContourModel", contourModel.GetID())
        record.nodes["AnnulusContourModel"] = contourModel
      else:
        contourNode = self._curveNode("vtkMRMLMarkupsClosedCurveNode", "AnnulusContourMarkup", points, uniquify=uniquifyNames)
        contourNode.GetDisplayNode().SetColor(*phaseColor)
        contourNode.GetDisplayNode().SetSelectedColor(*phaseColor)
      self._moveToValveFolder(valveNode, contourNode)
      valveNode.SetNodeReferenceID("AnnulusContourPoints", contourNode.GetID())
      record.nodes["AnnulusContourPoints"] = contourNode
      # Old ValveModel.storeAnnulusContour kept the backup on the valve node
      valveNode.SetAttribute("AnnulusContourCoordinates", str(np.array(points, dtype=np.float64).tobytes()))

    if labels:
      labeled = NewFormatValveFactory.labelPoints(frameIndex)
      record.labels = labeled
      labelsNode = self._fiducialNode("AnnulusLabelsMarkup", [lp[1:] for lp in labeled],
                                      labels=[lp[0] for lp in labeled], locked=True, uniquify=uniquifyNames)
      self._moveToValveFolder(valveNode, labelsNode)
      valveNode.SetNodeReferenceID("AnnulusLabelsPoints", labelsNode.GetID())
      record.nodes["AnnulusLabelsPoints"] = labelsNode

    if roi:
      params = dict(DEFAULT_ROI_PARAMS)
      params["ValveRoiScale"] = 100 + 10 * frameIndex
      params["ValveRoiTopDistance"] = 4 + frameIndex
      record.roiParams = params
      roiNode = self._modelNode("ValveRoiModel", _cylinder(radius=3.0 * params["ValveRoiScale"] / 100.0, height=6.0),
                                color=(0, 0, 1), uniquify=uniquifyNames)
      roiNode.GetDisplayNode().SetVisibility(False)
      roiNode.GetDisplayNode().SetVisibility2D(True)
      roiNode.GetDisplayNode().SetOpacity(0.1)
      for key, value in params.items():
        roiNode.SetAttribute(key, str(value))
      self._moveToValveFolder(valveNode, roiNode)
      valveNode.SetNodeReferenceID("ValveRoiModel", roiNode.GetID())
      record.nodes["ValveRoiModel"] = roiNode

    if segmentation:
      # Leaflet volume: clone of the analyzed frame, named "<valve>-segmented"
      frameForVolume = frameIndex if 0 <= frameIndex < self.volumeSequenceNode.GetNumberOfDataNodes() else 0
      leafletVolume = scene.createVolumeNode(slicer.mrmlScene.GetUniqueNameByString(f"{valveNode.GetName()}-segmented"),
                                             voxelValue=frameForVolume + 1)
      self._applyProbe(leafletVolume)
      self._moveToValveFolder(valveNode, leafletVolume)
      valveNode.SetNodeReferenceID("LeafletVolume", leafletVolume.GetID())
      record.nodes["LeafletVolume"] = leafletVolume
      record.leafletVolumeValue = frameForVolume + 1

      segName = f"{valveTypeName(valveType)}Valve-Segmentation-{PHASE_SHORT_NAMES[phase]}_f{frameIndex + 1}"
      segNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", slicer.mrmlScene.GetUniqueNameByString(segName))
      segNode.CreateDefaultDisplayNodes()
      segNode.SetNodeReferenceID(segNode.GetReferenceImageGeometryReferenceRole(), leafletVolume.GetID())
      # Without a reference geometry the closed surfaces below are rasterized at a default resolution
      # (250 voxels per axis), which is neither what the old modules produced nor practical
      segNode.SetReferenceImageGeometryParameterFromVolumeNode(leafletVolume)
      self._applyProbe(segNode)
      colors = {"Anterior": (1.0, 0.0, 0.0), "Posterior": (0.0, 1.0, 0.0), "Septal": (0.0, 0.0, 1.0),
                "Lateral": (1.0, 1.0, 0.0)}
      centers = {"Anterior": (1.2, 0.0, 0.0), "Posterior": (-1.2, 0.0, 0.0), "Septal": (0.0, 1.2, 0.0),
                 "Lateral": (0.0, -1.2, 0.0)}
      for segmentId in segmentIds:
        color = colors.get(segmentId, (0.5, 0.5, 0.5))
        center = centers.get(segmentId, (0.0, 0.0, 0.0))
        center = (center[0], center[1], center[2] + 0.2 * frameIndex)  # per-phase shift
        scene.addSphereSegment(segNode, segmentId, f"{segmentId} leaflet", center, radius=1.2, color=color)
        record.segmentIds.append(segmentId)
        record.segmentNames[segmentId] = f"{segmentId} leaflet"
        record.segmentColors[segmentId] = color
      scene.addSphereSegment(segNode, VALVE_MASK_SEGMENT_ID, "Annulus mask", (0, 0, 0), radius=3.0, color=(0, 0, 1))
      self._moveToValveFolder(valveNode, segNode)
      valveNode.SetNodeReferenceID("LeafletSegmentation", segNode.GetID())
      record.nodes["LeafletSegmentation"] = segNode

      if leaflets:
        order = list(leafletOrder) if leafletOrder else list(segmentIds)
        record.leafletOrder = order
        record.nodes["LeafletSurfaceModel"] = []
        record.nodes["LeafletSurfaceBoundaryMarkup"] = []
        record.nodes["LeafletSurfaceBoundaryModel"] = []
        for segmentId in order:
          color = colors.get(segmentId, (0.5, 0.5, 0.5))
          center = centers.get(segmentId, (0.0, 0.0, 0.0))
          surface = self._modelNode(f"{segmentId} leafletSurfaceModel", scene.sphereSource(center, 1.0), color=color,
                                    uniquify=uniquifyNames)
          surface.SetAttribute("SegmentID", segmentId)
          self._moveToValveFolder(valveNode, surface, "LeafletSurface")
          valveNode.AddNodeReferenceID("LeafletSurfaceModel", surface.GetID())
          record.nodes["LeafletSurfaceModel"].append(surface)

          boundaryPoints = [[center[0] + 1.0, center[1], 0.1 * frameIndex], [center[0], center[1] + 1.0, 0.1 * frameIndex],
                            [center[0] - 1.0, center[1], 0.1 * frameIndex], [center[0], center[1] - 1.0, 0.1 * frameIndex]]
          record.boundaryPoints[segmentId] = boundaryPoints
          boundary = self._fiducialNode(f"{segmentId} leafletSurfaceBoundaryMarkup", boundaryPoints, locked=True,
                                        uniquify=uniquifyNames)
          boundary.SetAttribute("SegmentID", segmentId)
          boundary.SetAttribute("ValvePlanePosition", "0.0 0.0 0.0")
          boundary.SetAttribute("ValvePlaneNormal", "0.0 0.0 1.0")
          self._moveToValveFolder(valveNode, boundary, "LeafletSurfaceEdit")
          valveNode.AddNodeReferenceID("LeafletSurfaceBoundaryMarkup", boundary.GetID())
          record.nodes["LeafletSurfaceBoundaryMarkup"].append(boundary)

          boundaryModel = self._modelNode(f"{segmentId} leafletSurfaceBoundaryModel", _tubeAround(boundaryPoints, 0.2),
                                          color=(0, 0, 1), uniquify=uniquifyNames)
          boundaryModel.SetAttribute("SegmentID", segmentId)
          self._moveToValveFolder(valveNode, boundaryModel, "LeafletSurfaceEdit")
          valveNode.AddNodeReferenceID("LeafletSurfaceBoundaryModel", boundaryModel.GetID())
          record.nodes["LeafletSurfaceBoundaryModel"].append(boundaryModel)

    if coaptation:
      base = [[-1.0, -1.5, 0.1 * frameIndex], [0.0, -1.5, 0.1 * frameIndex], [1.0, -1.5, 0.1 * frameIndex]]
      margin = [[-1.0, -1.5, -1.0], [0.0, -1.5, -1.0], [1.0, -1.5, -1.0]]
      record.coaptationPoints = (base, margin)
      surface = self._modelNode("Coaptation1SurfaceModel", _stripBetween(base, margin), color=(0.5, 1, 0.5),
                                uniquify=uniquifyNames)
      self._moveToValveFolder(valveNode, surface, "Coaptation")
      valveNode.SetNthNodeReferenceID("CoaptationSurfaceModel", 0, surface.GetID())
      baseMarkup = self._fiducialNode("Coaptation1BaseLineMarkup", base, locked=True, uniquify=uniquifyNames)
      self._moveToValveFolder(valveNode, baseMarkup, "CoaptationEdit")
      valveNode.SetNthNodeReferenceID("CoaptationBaseLineMarkup", 0, baseMarkup.GetID())
      baseModel = self._modelNode("Coaptation1BaseLineModel", _tubeAround(base, 0.2), color=(0, 0, 1), uniquify=uniquifyNames)
      self._moveToValveFolder(valveNode, baseModel, "CoaptationEdit")
      valveNode.SetNthNodeReferenceID("CoaptationBaseLineModel", 0, baseModel.GetID())
      marginMarkup = self._fiducialNode("Coaptation1MarginLineMarkup", margin, locked=True, uniquify=uniquifyNames)
      self._moveToValveFolder(valveNode, marginMarkup, "CoaptationEdit")
      valveNode.SetNthNodeReferenceID("CoaptationMarginLineMarkup", 0, marginMarkup.GetID())
      marginModel = self._modelNode("Coaptation1MarginLineModel", _tubeAround(margin, 0.2), color=(1, 0.5, 0), uniquify=uniquifyNames)
      self._moveToValveFolder(valveNode, marginModel, "CoaptationEdit")
      valveNode.SetNthNodeReferenceID("CoaptationMarginLineModel", 0, marginModel.GetID())
      record.nodes["CoaptationSurfaceModel"] = [surface]
      record.nodes["CoaptationBaseLineMarkup"] = [baseMarkup]
      record.nodes["CoaptationBaseLineModel"] = [baseModel]
      record.nodes["CoaptationMarginLineMarkup"] = [marginMarkup]
      record.nodes["CoaptationMarginLineModel"] = [marginModel]

    if papillary:
      record.nodes["PapillaryLineMarkup"] = []
      record.nodes["PapillaryLineModel"] = []
      for i, muscleName in enumerate(PAPILLARY_NAMES.get(valveType, ["papillary1", "papillary2"])):
        x = 3.0 if i % 2 == 0 else -3.0
        points = [[x, 0.0, -3.0 + 0.1 * frameIndex], [x * 0.8, 0.0, -1.5], [x * 0.4, 0.0, 0.0]]
        record.papillaryPoints[muscleName] = points
        markup = self._fiducialNode(f"PapillaryMarkup-{muscleName}", points, locked=True, uniquify=uniquifyNames)
        markup.GetDisplayNode().SetColor(0.5, 0, 1)
        self._moveToValveFolder(valveNode, markup, "PapillaryMusclesEdit")
        valveNode.SetNthNodeReferenceID("PapillaryLineMarkup", i, markup.GetID())
        model = self._modelNode(f"{muscleName} papillary muscle", _tubeAround(points, 0.2), color=phaseColor,
                                uniquify=uniquifyNames)
        model.GetDisplayNode().SetVisibility2D(True)
        self._moveToValveFolder(valveNode, model, "PapillaryMuscles")
        valveNode.SetNthNodeReferenceID("PapillaryLineModel", i, model.GetID())
        record.nodes["PapillaryLineMarkup"].append(markup)
        record.nodes["PapillaryLineModel"].append(model)

    if clippedVolume:
      clipped = scene.createVolumeNode(slicer.mrmlScene.GetUniqueNameByString(f"{valveNode.GetName()}-clipped"),
                                       voxelValue=77)
      self._applyProbe(clipped)
      self._moveToValveFolder(valveNode, clipped)
      valveNode.SetNodeReferenceID("ClippedVolume", clipped.GetID())
      record.nodes["ClippedVolume"] = clipped

    self.valves.append(record)
    return record

  def addLegacyValves(self, valveType="mitral", phases=(("mid-systole", 1), ("end-systole", 3), ("mid-diastole", 5)),
                      **kwargs):
    """Create several phases of one valve. *phases*: iterable of ``(phase, frameIndex)``."""
    return [self.addLegacyValve(valveType=valveType, frameIndex=frameIndex, phase=phase, **kwargs)
            for phase, frameIndex in phases]

  # ---------------------------------------------------------------------------------------------
  # Measurements
  # ---------------------------------------------------------------------------------------------

  def addLegacyMeasurement(self, presetId, valveRoles, name=None, hidden=False, withTable=True,
                           resultModelCount=2, tableAsReference=False, tableRole="QuantificationResultsTable",
                           tableRows=(("Annulus area (3D)", "123.4", "mm*mm"), ("Annulus circumference (3D)", "45.6", "mm"))):
    """Create an old-format HeartValveMeasurement node.

    :param valveRoles: ``{"Valve<inputValveId>": LegacyValveRecord or valve node}``
    :param tableAsReference: also reference the table from the measurement node (the old modules
      attached results only as subject hierarchy children; the converter handles referenced tables)
    :returns: dict with node, table, resultModels
    """
    sh = shNode()
    measurementNode = slicer.vtkMRMLScriptedModuleNode()
    measurementNode.SetHideFromEditors(hidden)
    measurementNode.SetAttribute("ModuleName", "HeartValveMeasurement")
    measurementNode.SetAttribute("MeasurementPreset", presetId)
    slicer.mrmlScene.AddNode(measurementNode)
    measurementNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name or f"{presetId}-Measurement"))
    for role, valve in valveRoles.items():
      valveNode = valve.node if isinstance(valve, LegacyValveRecord) else valve
      measurementNode.SetNodeReferenceID(role, valveNode.GetID())
    sh.RequestOwnerPluginSearch(measurementNode)
    itemId = sh.GetItemByDataNode(measurementNode)
    if not itemId:
      itemId = sh.CreateItem(sh.GetSceneItemID(), measurementNode)
    sh.SetItemAttribute(itemId, "ModuleName", "HeartValveMeasurement")

    result = {"node": measurementNode, "table": None, "resultModels": [], "rows": list(tableRows)}
    if withTable:
      tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Quantification results")
      table = tableNode.GetTable()
      for columnName in ("Metric", "Value", "Unit"):
        column = vtk.vtkStringArray()
        column.SetName(columnName)
        table.AddColumn(column)
      for row in tableRows:
        rowIndex = tableNode.AddEmptyRow()
        for c, value in enumerate(row):
          tableNode.SetCellText(rowIndex, c, value)
      tableNode.Modified()
      sh.SetItemParent(sh.GetItemByDataNode(tableNode), itemId)
      if tableAsReference:
        measurementNode.SetNodeReferenceID(tableRole, tableNode.GetID())
      result["table"] = tableNode
    for i in range(resultModelCount):
      model = self._modelNode(f"{presetId} result model {i + 1}", scene.sphereSource((0, 0, 0), 0.5 + 0.1 * i),
                              color=(1, 0.5, 0))
      model.GetDisplayNode().SetVisibility(False)
      sh.SetItemParent(sh.GetItemByDataNode(model), itemId)
      result["resultModels"].append(model)
    self.measurements.append(result)
    return result

  # ---------------------------------------------------------------------------------------------
  # Devices
  # ---------------------------------------------------------------------------------------------

  def addLegacyDevice(self, name="ASD_Device_1", volumeNode=None, attributes=None):
    """Create an old-format CardiacDeviceAnalysis node referencing a volume (role contains 'Volume')."""
    deviceNode = slicer.vtkMRMLScriptedModuleNode()
    deviceNode.SetHideFromEditors(False)
    deviceNode.SetAttribute("ModuleName", "CardiacDeviceAnalysis")
    slicer.mrmlScene.AddNode(deviceNode)
    deviceNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name))
    if volumeNode is None:
      volumeNode = self.volumeProxyNode
    if volumeNode:
      deviceNode.SetNodeReferenceID("InputVolume", volumeNode.GetID())
    for key, value in (attributes or {"DeviceClassId": "Amplatzer"}).items():
      deviceNode.SetAttribute(key, value)
    deviceModel = self._modelNode(f"{name}Model", scene.sphereSource((0, 0, 0), 1.0), color=(0.8, 0.8, 0.2))
    deviceNode.SetNodeReferenceID("DeviceModel", deviceModel.GetID())
    record = {"node": deviceNode, "model": deviceModel, "volume": volumeNode}
    self.devices.append(record)
    return record
