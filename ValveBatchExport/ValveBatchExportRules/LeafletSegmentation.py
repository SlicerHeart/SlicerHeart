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

  BRIEF_USE = "Leaflet segmentation (.nrrd)"
  DETAILED_DESCRIPTION = "Export leaflet segmentation as 4D nrrd file (each 3D volume is one segment)"
  USER_INTERFACE = True

  CMD_FLAG = "-seg"
  CMD_FLAG_1 = "-ssep"  # individual segmentation file per segment

  OTHER_FLAGS = []
  ONE_FILE_PER_SEGMENT = False

  @classmethod
  def setupUI(cls, layout):

    def onModified(checked):
      cls.ONE_FILE_PER_SEGMENT = checked
      if checked:
        cls.OTHER_FLAGS.append(cls.CMD_FLAG_1)
      else:
        if cls.CMD_FLAG_1 in cls.OTHER_FLAGS:
          cls.OTHER_FLAGS.remove(cls.CMD_FLAG_1)

    checkbox = qt.QCheckBox("One file per segment")
    checkbox.stateChanged.connect(onModified)
    checkbox.checked = cls.ONE_FILE_PER_SEGMENT

    layout.addWidget(checkbox)

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

      if deleteValveMask(leafletSegmentationNode) is True:
        self.addLog(
          f"Found segment with id {HeartValveLib.Constants.VALVE_MASK_SEGMENT_ID}. Deleted segment for export")

      if self.ONE_FILE_PER_SEGMENT:
        self._saveSegmentsIntoSeparateFiles(leafletSegmentationNode, valveModelName)
      else:
        if leafletSegmentationNode.GetSegmentation().GetNumberOfSegments() > 1:
          self.addLog("Sorting individual leaflets")
          m = checkAndSortSegments(leafletSegmentationNode, valveModel.getValveType()) # sort segments
          if m:
            self.addLog(m)
          outputFileName = f"{valveModelName}_leaflets.seg.nrrd"
        else:
          self.addLog("Only single segmentation found")
          outputFileName = f"{valveModelName}_whole_valve.seg.nrrd"

        storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationStorageNode")
        storageNode.SetFileName(os.path.join(self.outputDir, outputFileName))

        if not storageNode.WriteData(leafletSegmentationNode):
          self.addLog(f"  Leaflet segmentation export skipped (file writing failed) - {valveModelName}")
        slicer.mrmlScene.RemoveNode(storageNode)

  def _saveSegmentsIntoSeparateFiles(self, segmentationNode, prefix):
    segmentationsLogic = slicer.modules.segmentations.logic()

    for segmentID in getAllSegmentIDs(segmentationNode):
      labelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
      showOnlySegmentWithSegmentID(segmentationNode, segmentID)
      segmentationsLogic.ExportVisibleSegmentsToLabelmapNode(segmentationNode, labelNode)
      segmentName = segmentationNode.GetSegmentation().GetSegment(segmentID).GetName()
      filename = f"{prefix}_{segmentName.replace(' ', '_')}.nii.gz"
      slicer.util.saveNode(labelNode, str(Path(self.outputDir) / filename))


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