import os
from pathlib import Path
import qt
import vtk

import HeartValveLib.Constants
import slicer
from .base import ValveBatchExportRule

from typing import Optional


LEAFLET_ORDER = {
  "mitral": ['anterior', 'posterior'],
  "tricuspid": ['anterior', 'posterior', 'septal'],
  "cavc": ['superior', 'right', 'inferior', 'left']
}


class LeafletSegmentationExportRule(ValveBatchExportRule):

  BRIEF_USE = "Segmentation"
  DETAILED_DESCRIPTION = "Export individual segments"
  USER_INTERFACE = True

  CMD_FLAG = "-seg"
  CMD_FLAG_LABELMAP = "-segl"
  CMD_FLAG_MODEL = "-segm"
  CMD_FLAG_MODEL_HOLE_SIZE = "-seghs"

  OTHER_FLAGS = []
  EXPORT_SEGMENTS_AS_LABELMAP = True
  EXPORT_SEGMENTS_AS_MODEL = False

  @classmethod
  def setupUI(cls, layout):
    labelmapCheckbox = qt.QCheckBox("Export as segmentation")
    modelCheckbox = qt.QCheckBox("Export as model (.vtk)")

    def onLabelmapCheckboxModified(checked):
      cls.EXPORT_SEGMENTS_AS_LABELMAP = checked
      cls.setOptionFlag(cls.CMD_FLAG_LABELMAP, checked)

    def onModelCheckboxModified(checked):
      cls.EXPORT_SEGMENTS_AS_MODEL = checked
      cls.setOptionFlag(cls.CMD_FLAG_MODEL, checked)

    labelmapCheckbox.stateChanged.connect(onLabelmapCheckboxModified)
    labelmapCheckbox.checked = cls.EXPORT_SEGMENTS_AS_LABELMAP

    modelCheckbox.stateChanged.connect(onModelCheckboxModified)
    modelCheckbox.checked = cls.EXPORT_SEGMENTS_AS_MODEL

    cls.setOptionFlag(cls.CMD_FLAG_LABELMAP, cls.EXPORT_SEGMENTS_AS_LABELMAP)
    cls.setOptionFlag(cls.CMD_FLAG_MODEL, cls.EXPORT_SEGMENTS_AS_MODEL)

    layout.addWidget(labelmapCheckbox)
    layout.addWidget(modelCheckbox)

  @classmethod
  def setOptionFlag(cls, flag, enabled):
    if enabled and flag not in cls.OTHER_FLAGS:
      cls.OTHER_FLAGS.append(flag)
    elif not enabled and flag in cls.OTHER_FLAGS:
      cls.OTHER_FLAGS.remove(flag)

  def processScene(self, sceneFileName):

    for valveModel in self.getHeartValveModelNodes():
      frameNumber = self.getAssociatedFrameNumber(valveModel)
      filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
      valveType = valveModel.heartValveNode.GetAttribute('ValveType')
      cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
      valveModelName = self.generateValveModelName(filename, valveType, cardiacCyclePhaseName, frameNumber)
      leafletSegmentationNode = valveModel.getLeafletSegmentationNode()

      if leafletSegmentationNode is None:
        self.addLog(f"  Leaflet segmentation export skipped (segmentation is missing) - {valveModelName}")
        continue
      segmentationBounds = [0, -1, 0, -1, 0, -1]
      leafletSegmentationNode.GetSegmentation().GetBounds(segmentationBounds)
      if segmentationBounds[0] > segmentationBounds[1] or \
        segmentationBounds[2] > segmentationBounds[3] or \
        segmentationBounds[4] > segmentationBounds[5]:
        self.addLog(f"  Leaflet segmentation export skipped (empty segmentation) - {valveModelName}")
        continue

      self._saveSegmentsIntoSeparateFiles(valveModel, valveModelName)

  def _saveSegmentsIntoSeparateFiles(self, valveModel, prefix):
    segmentationNode = valveModel.getLeafletSegmentationNode()
    segmentationsLogic = slicer.modules.segmentations.logic()

    labelNode = None
    if self.EXPORT_SEGMENTS_AS_LABELMAP:
      labelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")

    for segmentID in getAllSegmentIDs(segmentationNode):
      from HeartValveLib.Constants import VALVE_MASK_SEGMENT_ID
      if segmentID == VALVE_MASK_SEGMENT_ID:
        self.addLog(f"    Skipping Segmentation export for segment with id '{VALVE_MASK_SEGMENT_ID}'")
        continue
      showOnlySegmentWithSegmentID(segmentationNode, segmentID)
      segmentName = segmentationNode.GetSegmentation().GetSegment(segmentID).GetName()
      filenamePrefix = f"{prefix}_{segmentName.replace(' ', '_')}"
      if self.EXPORT_SEGMENTS_AS_LABELMAP:
        segmentationsLogic.ExportVisibleSegmentsToLabelmapNode(segmentationNode, labelNode,
                                                               valveModel.getLeafletVolumeNode())
        slicer.util.saveNode(labelNode, str(Path(self.outputDir) / f"{filenamePrefix}.{self.IMAGE_FILE_EXTENSION}"))
      if self.EXPORT_SEGMENTS_AS_MODEL:
        self._saveSegmentAsModel(segmentationNode, segmentID, valveModel.getLeafletVolumeNode(), filenamePrefix)

    if labelNode:
      slicer.mrmlScene.RemoveNode(labelNode)

  def _saveSegmentAsModel(self, segmentationNode, segmentID, sourceVolumeNode, filenamePrefix):
    modelSegmentationNode = self._createModelExportSegmentation(segmentationNode, segmentID, sourceVolumeNode)
    try:
      modelSegmentationNode.RemoveClosedSurfaceRepresentation()
      modelSegmentationNode.CreateClosedSurfaceRepresentation()
      self._saveSegmentClosedSurfaceAsModel(modelSegmentationNode, segmentID, filenamePrefix)
    finally:
      slicer.mrmlScene.RemoveNode(modelSegmentationNode)

  def _createModelExportSegmentation(self, segmentationNode, segmentID, sourceVolumeNode):
    modelSegmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    modelSegmentationNode.CreateDefaultDisplayNodes()
    modelSegmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(sourceVolumeNode)
    modelSegmentationNode.SetAndObserveTransformNodeID(segmentationNode.GetTransformNodeID())
    modelSegmentationNode.GetSegmentation().CopySegmentFromSegmentation(segmentationNode.GetSegmentation(), segmentID)
    return modelSegmentationNode

  def _saveSegmentClosedSurfaceAsModel(self, segmentationNode, segmentID, filenamePrefix):
    polyData = vtk.vtkPolyData()
    if not segmentationNode.GetClosedSurfaceRepresentation(segmentID, polyData) or polyData.GetNumberOfPoints() == 0:
      self.addLog(f"    Skipping model export for segment '{segmentID}' (closed surface is empty)")
      return

    modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", filenamePrefix)
    modelNode.SetAndObservePolyData(polyData)
    modelNode.SetAndObserveTransformNodeID(segmentationNode.GetTransformNodeID())
    slicer.util.saveNode(modelNode, str(Path(self.outputDir) / f"{filenamePrefix}.vtk"))
    slicer.mrmlScene.RemoveNode(modelNode)


def getAllSegmentNames(segmentationNode):
  return [segment.GetName() for segment in getAllSegments(segmentationNode)]


def getAllSegments(segmentationNode):
  segmentation = segmentationNode.GetSegmentation()
  return [segmentation.GetSegment(segmentID) for segmentID in getAllSegmentIDs(segmentationNode)]


def getAllSegmentIDs(segmentationNode):
  segmentIDs = vtk.vtkStringArray()
  segmentation = segmentationNode.GetSegmentation()
  segmentation.GetSegmentIDs(segmentIDs)
  return [segmentIDs.GetValue(idx) for idx in range(segmentIDs.GetNumberOfValues())]


def showOnlySegmentWithSegmentID(segmentationNode, segmentID):
  hideAllSegments(segmentationNode)
  segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, True)


def hideAllSegments(segmentationNode):
  for segmentID in getAllSegmentIDs(segmentationNode):
    segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, False)


def deleteValveMask(segmentationNode):
  segmentation = segmentationNode.GetSegmentation()
  valveMaskSegment = segmentationNode.GetSegmentation().GetSegment(HeartValveLib.Constants.VALVE_MASK_SEGMENT_ID)
  if valveMaskSegment:
    segmentation.RemoveSegment(valveMaskSegment)
    return True
  return False


def getLeafletOrderDefinition(valveType):
  try:
    return LEAFLET_ORDER[valveType.lower()]
  except KeyError:
    raise ValueError("valve type %s not supported " % valveType)


def checkAndSortSegments(segmentationNode, valveType):
  expectedOrder = getLeafletOrderDefinition(valveType)
  segmentIDs = getAllSegmentIDs(segmentationNode)
  segmentNames = getAllSegmentNames(segmentationNode)
  message = ""
  if not isSorted(expectedOrder, segmentIDs) or not isSorted(expectedOrder, segmentNames):
    message = "Leaflet names don't match up with segment IDs. Sorting segments."
    sortSegments(segmentationNode, valveType)
  return message


def isSorted(expectedOrder : list, currentOrder : list) -> bool:
  """ returns if the current list of strings has the expected order of elements

  :param expectedOrder: list of keywords as expected in the specific element
  :param currentOrder: list of strings to check for order
  :return: true if ordered, otherwise false
  """
  return all(expectedOrder[i] in currentOrder[i] for i in range(len(expectedOrder)))


def sortSegments(segmentationNode, valveType):
  expectedOrder = getLeafletOrderDefinition(valveType)
  segmentation = segmentationNode.GetSegmentation()
  segmentInfos = getSortedSegmentInfos(segmentationNode, expectedOrder)
  newSegmentIDs, segments = getSortedSegmentsAndIDs(segmentationNode, segmentInfos, valveType)
  segmentation.RemoveAllSegments()
  for newSegmentID, segment in zip(newSegmentIDs, segments):
    segmentation.AddSegment(segment, newSegmentID)


def getSortedSegmentInfos(segmentationNode, expectedOrder):
  segmentNames = getAllSegmentNames(segmentationNode)
  orderedSegmentNames = list()
  for location in expectedOrder:
    segmentName = getFirstMatchingListElement(segmentNames, location)
    if not segmentName:
      raise ValueError(f"Cannot find segment with name {location}. Following segments are available: {segmentNames}")
    orderedSegmentNames.append((segmentName, location))
  return orderedSegmentNames


def getFirstMatchingListElement(elements : list, keyword : str) -> Optional[str]:
  """ Returns first element with the keyword in it

  :param elements: list of strings
  :param keyword:
  :return: None if none was found, otherwise the first matching element
  """
  for elem in elements:
    if keyword in elem:
      return elem
  return None


def getSortedSegmentsAndIDs(segmentationNode, segmentInfos, valveType):
  segmentation = segmentationNode.GetSegmentation()
  newSegmentIDs = list()
  segments = list()
  for segmentName, loc in segmentInfos:
    segmentID = segmentation.GetSegmentIdBySegmentName(segmentName)
    newSegmentID = f"{valveType}_{loc}_leaflet"
    newSegmentIDs.append(newSegmentID)
    segments.append(segmentation.GetSegment(segmentID))
  return newSegmentIDs, segments
