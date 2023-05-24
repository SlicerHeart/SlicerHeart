import os
from pathlib import Path
import qt

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
      segNode = valveModel.getLeafletSegmentationNode()

      if segNode is None:
        self.addLog(f"  Leaflet segmentation export skipped (segmentation is missing) - {valveModelName}")
        continue

      segmentation = segNode.GetSegmentation()
      deletedSegments = deleteNonLeafletSegments(segNode)

      for segId, segName in deletedSegments:
        self.addLog(f"Found segment with id {segId} and name {segName}. Deleted segment for export")

      segmentationBounds = [0, -1, 0, -1, 0, -1]
      segmentation.GetBounds(segmentationBounds)
      if segmentationBounds[0] > segmentationBounds[1] or \
        segmentationBounds[2] > segmentationBounds[3] or \
        segmentationBounds[4] > segmentationBounds[5]:
        self.addLog(f"  Leaflet segmentation export skipped (empty segmentation) - {valveModelName}")
        continue

      if segmentation.GetNumberOfSegments() != len(LEAFLET_ORDER[valveModel.getValveType().lower()]):
        self.addLog(f"  Missing leaflets - {valveModelName}: Found segment names: {getAllSegmentNames(segNode)}")
        continue

      ext = ".nrrd" # ".nii.gz"

      showAllSegments(segNode)

      if self.ONE_FILE_PER_SEGMENT:
        self._saveSegmentsIntoSeparateFiles(valveModel, valveModelName, ext)
      else:
        self.addLog("Sorting individual leaflets")
        m = checkAndSortSegments(segNode, valveModel.getValveType())
        if m:
          self.addLog(m)  # sort segments

        self._saveSegmentsIntoOneFile(valveModel, valveModelName, ext)

  def _saveSegmentsIntoOneFile(self, valveModel, prefix, ext):
    segmentationNode = valveModel.getLeafletSegmentationNode()
    showOnlySegmentsWithKeywordInNameOrID(segmentationNode)
    labelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(segmentationNode, labelNode,
                                                                             valveModel.getLeafletVolumeNode())
    outputFileName = f"{prefix}_leaflets.seg{ext}"
    slicer.util.saveNode(labelNode, os.path.join(self.outputDir, outputFileName))
    slicer.mrmlScene.RemoveNode(labelNode)

  def _saveSegmentsIntoSeparateFiles(self, valveModel, prefix, fileExtension):
    segmentationNode = valveModel.getLeafletSegmentationNode()
    segmentationsLogic = slicer.modules.segmentations.logic()

    from HeartValveLib.util import getAllSegmentIDs
    labelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    for segmentID in getAllSegmentIDs(segmentationNode):
      showOnlySegmentWithSegmentID(segmentationNode, segmentID)
      segmentationsLogic.ExportVisibleSegmentsToLabelmapNode(segmentationNode, labelNode,
                                                             valveModel.getLeafletVolumeNode())
      segmentName = segmentationNode.GetSegmentation().GetSegment(segmentID).GetName()
      filename = f"{prefix}_{segmentName.replace(' ', '_')}{fileExtension}"
      slicer.util.saveNode(labelNode, str(Path(self.outputDir) / filename))
    slicer.mrmlScene.RemoveNode(labelNode)


def getAllSegmentNames(segmentationNode):
  return [segment.GetName() for segment in getAllSegments(segmentationNode)]


def getAllSegments(segmentationNode):
  segmentation = segmentationNode.GetSegmentation()
  from HeartValveLib.util import getAllSegmentIDs
  return [segmentation.GetSegment(segmentID) for segmentID in getAllSegmentIDs(segmentationNode)]


def showOnlySegmentWithSegmentID(segmentationNode, segmentID):
  hideAllSegments(segmentationNode)
  segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, True)
  
  
def showOnlySegmentsWithKeywordInNameOrID(segmentationNode, keyword="leaflet"):
  from HeartValveLib.util import getAllSegmentIDs
  for segment, segmentID in zip(getAllSegments(segmentationNode), getAllSegmentIDs(segmentationNode)):
    segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID,
                                                           isKeywordInSegmentNameOrID(segmentationNode, segmentID,
                                                                                      keyword))


def showAllSegments(segmentationNode):
  from HeartValveLib.util import getAllSegmentIDs
  for segmentID in getAllSegmentIDs(segmentationNode):
    segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, True)


def hideAllSegments(segmentationNode):
  from HeartValveLib.util import getAllSegmentIDs
  for segmentID in getAllSegmentIDs(segmentationNode):
    segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, False)


def deleteNonLeafletSegments(segmentationNode, keyword="leaflet"):
  segmentation = segmentationNode.GetSegmentation()
  deletedSegments = []
  from HeartValveLib.util import getAllSegmentIDs
  for segmentID in getAllSegmentIDs(segmentationNode):
    segment = segmentation.GetSegment(segmentID)
    if isKeywordInSegmentNameOrID(segmentationNode, segmentID, keyword):
      continue
    deletedSegments.append([segmentID, segment.GetName()])
    segmentation.RemoveSegment(segment)
  return deletedSegments


def isKeywordInSegmentNameOrID(segmentationNode, segmentID, keyword):
  segmentation = segmentationNode.GetSegmentation()
  segment = segmentation.GetSegment(segmentID)
  segmentName = segment.GetName()
  return any(keyword.lower() in n for n in [segmentID.lower(), segmentName.lower()])



def getLeafletOrderDefinition(valveType):
  try:
    return LEAFLET_ORDER[valveType.lower()]
  except KeyError:
    raise ValueError("valve type %s not supported " % valveType)


def checkAndSortSegments(segmentationNode, valveType):
  from HeartValveLib.util import getAllSegmentIDs
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