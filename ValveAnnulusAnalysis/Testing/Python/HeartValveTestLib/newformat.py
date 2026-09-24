"""
NewFormatValveFactory: build heart valve annotations through the branch (sequence) API.

Everything here goes through HeartValveLib (ValveBrowser / ValveModel) exactly the way the modules
do, so the tests exercise production code paths rather than re-implementing them.
"""

import slicer

from . import scene


class NewFormatValveFactory:
  """Creates valve browsers on a (synthetic by default) volume sequence.

  Coordinates given to the helpers are in the *Probe* coordinate system (the parent transform of
  every valve node), so they can be small numbers around the origin regardless of probe position.
  """

  # Two-leaflet default segmentation: (segmentId, name, color, center)
  DEFAULT_SEGMENTS = [
    ("Anterior", "Anterior leaflet", (1.0, 0.0, 0.0), (1.2, 0.0, 0.0)),
    ("Posterior", "Posterior leaflet", (0.0, 1.0, 0.0), (-1.2, 0.0, 0.0)),
  ]

  def __init__(self, volumeBrowserNode=None, numFrames=6, name="SyntheticUS"):
    if volumeBrowserNode is None:
      volumeBrowserNode, _, _ = scene.createSyntheticVolumeSequence(numFrames=numFrames, name=name)
    self.volumeBrowserNode = volumeBrowserNode
    self.volumeSequenceNode = volumeBrowserNode.GetMasterSequenceNode()
    self.volumeProxyNode = volumeBrowserNode.GetProxyNode(self.volumeSequenceNode)

  # ---------------------------------------------------------------------------------------------
  # Browser / time points
  # ---------------------------------------------------------------------------------------------

  def indexValue(self, frameIndex):
    return self.volumeSequenceNode.GetNthIndexValue(frameIndex)

  def numberOfFrames(self):
    return self.volumeSequenceNode.GetNumberOfDataNodes()

  def createValveBrowser(self, valveType="mitral", probePosition="TTE_APICAL", name=None):
    """Create a valve browser the way the ValveAnnulusAnalysis node selector does (the selector
    stamps ``ModuleName=HeartValve`` on the new browser node; HeartValveLib does not)."""
    import HeartValveLib
    browserName = name or f"{valveType.capitalize()}ValveBrowser"
    valveBrowserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", browserName)
    valveBrowserNode.SetAttribute("ModuleName", "HeartValve")
    valveBrowser = HeartValveLib.HeartValves.getValveBrowser(valveBrowserNode)
    valveBrowser.valveVolumeNode = self.volumeProxyNode
    valveBrowser.valveType = valveType
    if probePosition is not None:
      valveBrowser.probePosition = probePosition
    return valveBrowser

  def selectFrame(self, frameIndex):
    scene.selectVolumeFrame(self.volumeBrowserNode, frameIndex)

  def addTimePoint(self, valveBrowser, frameIndex, phase=None):
    """Add (or switch to) the valve time point annotating volume frame *frameIndex*.

    Uses ``addTimePointAtCurrentFrame`` like the "Add time point" button does.
    :returns: index value of the time point
    """
    self.selectFrame(frameIndex)
    indexValue = valveBrowser.addTimePointAtCurrentFrame()
    if indexValue is None:
      raise RuntimeError(f"addTimePointAtCurrentFrame failed for frame {frameIndex}")
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(valveBrowser.valveBrowserNode)
    if phase is not None:
      valveBrowser.valveModel.setCardiacCyclePhase(phase)
    return indexValue

  def switchTo(self, valveBrowser, frameIndex):
    """Switch the valve browser (and the volume browser) to the time point of *frameIndex*."""
    indexValue = self.indexValue(frameIndex)
    scene.selectIndexValue(valveBrowser.valveBrowserNode, indexValue)
    self.selectFrame(frameIndex)

  def currentFrame(self, valveBrowser):
    return valveBrowser.valveModel.getValveVolumeSequenceIndex()

  # ---------------------------------------------------------------------------------------------
  # Annotations for the current time point
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def contourPoints(frameIndex, numPoints=12):
    """Deterministic, frame-specific ellipse (Probe coordinates, inside the synthetic volume)."""
    return scene.ellipsePoints(numPoints=numPoints, radiusX=2.5, radiusY=2.0, center=(0.0, 0.0, 0.0),
                               tilt=0.3, phaseOffset=0.1 * frameIndex)

  @staticmethod
  def labelPoints(frameIndex):
    return scene.landmarkLabels(NewFormatValveFactory.contourPoints(frameIndex))

  def setContour(self, valveBrowser, frameIndex=None):
    if frameIndex is None:
      frameIndex = self.currentFrame(valveBrowser)
    points = self.contourPoints(frameIndex)
    node = valveBrowser.valveModel.setAnnulusContourPoints(points)
    if node is None:
      raise RuntimeError("setAnnulusContourPoints failed")
    return points

  def setLabels(self, valveBrowser, frameIndex=None):
    if frameIndex is None:
      frameIndex = self.currentFrame(valveBrowser)
    labeled = self.labelPoints(frameIndex)
    node = valveBrowser.valveModel.setValveLabels(labeled)
    if node is None:
      raise RuntimeError("setValveLabels failed")
    return labeled

  def addRoi(self, valveBrowser):
    """Ensure a valve ROI model exists for the current time point (mirrors the ValveSegmentation
    'Add ROI' button) and return it."""
    valveModel = valveBrowser.valveModel
    roiNode = valveModel.valveRoiModelNode
    if not roiNode:
      if valveModel.valveRoiSequenceNode is None:
        roiNode = valveModel.createValveRoiModelNode()
      else:
        valveBrowser.addCurrentTimePointToSequence(valveModel.valveRoiSequenceNode)
        roiNode = valveModel.valveRoiModelNode
    valveModel.valveRoi.setAnnulusContourCurve(valveModel.annulusContourCurveNode)
    valveModel.valveRoi.updateRoi()
    return roiNode

  def addSegmentation(self, valveBrowser, segments=None, withGeometry=True):
    """Create the leaflet segmentation for the current time point with the given segments.

    :param segments: list of ``(segmentId, name, color, center)``; default two leaflets.
    :param withGeometry: add a small sphere per segment (else empty segments)
    """
    if segments is None:
      segments = self.DEFAULT_SEGMENTS
    valveModel = valveBrowser.valveModel
    segmentationNode = valveModel.initializeLeafletSegmentation()
    if segmentationNode is None:
      raise RuntimeError("initializeLeafletSegmentation failed")
    segmentation = segmentationNode.GetSegmentation()
    for segmentId, name, color, center in segments:
      if segmentation.GetSegment(segmentId):
        segment = segmentation.GetSegment(segmentId)
        segment.SetName(name)
        segment.SetColor(*color)
        if withGeometry:
          segmentation.RemoveSegment(segmentId)
          scene.addSphereSegment(segmentationNode, segmentId, name, center, radius=1.2, color=color)
      elif withGeometry:
        scene.addSphereSegment(segmentationNode, segmentId, name, center, radius=1.2, color=color)
      else:
        newId = segmentation.AddEmptySegment(segmentId, name, color)
        segmentation.GetSegment(newId).SetName(name)
    valveModel.updateLeafletModelsFromSegmentation()
    return segmentationNode

  def addPapillaryMuscles(self, valveBrowser):
    """Create the papillary muscle line markups for the valve type and place 3 points each."""
    valveModel = valveBrowser.valveModel
    valveModel.updatePapillaryModels()
    placed = []
    for i, papillaryModel in enumerate(valveModel.papillaryModels):
      x = 3.0 if i % 2 == 0 else -3.0
      points = [[x, 0.0, -3.0], [x * 0.8, 0.0, -1.5], [x * 0.4, 0.0, 0.0]]
      node = valveModel.setPapillaryLinePoints(papillaryModel, points)
      if node is None:
        raise RuntimeError("setPapillaryLinePoints failed")
      placed.append(points)
    return placed

  def addCoaptation(self, valveBrowser, coaptationIndex=-1):
    """Add a coaptation model with base and margin lines for the current time point."""
    valveModel = valveBrowser.valveModel
    coaptationModel = valveModel.addCoaptationModel(coaptationIndex)
    basePoints = [[-1.0, -1.5, 0.0], [0.0, -1.5, 0.0], [1.0, -1.5, 0.0]]
    marginPoints = [[-1.0, -1.5, -1.0], [0.0, -1.5, -1.0], [1.0, -1.5, -1.0]]
    # The time point has to be added to every sequence BEFORE the proxy nodes are edited (like the
    # LeafletAnalysis module does in onAddCoaptationTimePoint): with SaveChanges the Sequences logic
    # reverts an edit of a proxy at a time point without item immediately.
    for node in (coaptationModel.baseLine, coaptationModel.marginLine, coaptationModel.surfaceModelNode):
      sequenceNode = valveBrowser.valveBrowserNode.GetSequenceNode(node)
      if sequenceNode:
        valveBrowser.addCurrentTimePointToSequence(sequenceNode)
    for markupNode, points in ((coaptationModel.baseLine, basePoints), (coaptationModel.marginLine, marginPoints)):
      markupNode.SetLocked(False)
      wasModify = markupNode.StartModify()
      markupNode.RemoveAllControlPoints()
      for p in points:
        markupNode.AddControlPoint(p[0], p[1], p[2])
      markupNode.EndModify(wasModify)
      markupNode.SetLocked(True)
    coaptationModel.updateSurface()
    return coaptationModel

  # ---------------------------------------------------------------------------------------------
  # Convenience
  # ---------------------------------------------------------------------------------------------

  def createAnnotatedValve(self, valveType="mitral", frames=(1, 3), phases=("mid-systole", "end-diastole"),
                           contour=True, labels=True, roi=False, segmentation=False, probePosition="TTE_APICAL"):
    """Create a valve browser with one annotated time point per frame; leaves the browser at the
    last frame. :returns: the ValveBrowser."""
    valveBrowser = self.createValveBrowser(valveType, probePosition=probePosition)
    for frameIndex, phase in zip(frames, list(phases) + [None] * len(frames)):
      self.addTimePoint(valveBrowser, frameIndex, phase=phase)
      if contour:
        self.setContour(valveBrowser, frameIndex)
      if labels:
        self.setLabels(valveBrowser, frameIndex)
      if roi:
        self.addRoi(valveBrowser)
      if segmentation:
        self.addSegmentation(valveBrowser)
    return valveBrowser
