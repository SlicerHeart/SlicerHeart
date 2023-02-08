from typing import Optional

import numpy as np
import vtk
import HeartValveLib

import slicer
from .constants import LEAFLET_ORDER


def getSegmentationFromAnnulusContourNode(valveModel, tubeRadius=None):
  if not tubeRadius:
    avgSpacing = np.array(valveModel.getValveVolumeNode().GetSpacing()).mean()
    valveModel.annulusContourCurve.setTubeRadius(avgSpacing)
  annulusModelNode = valveModel.getAnnulusContourModelNode()
  segmentationNode = getNewSegmentationNodeFromModel(valveModel.getValveVolumeNode(), annulusModelNode)
  slicer.mrmlScene.RemoveNode(annulusModelNode)
  return segmentationNode


def getNewSegmentationNodeFromModel(valveVolume, modelNode):
  segmentationNode = createNewSegmentationNode(valveVolume)
  segmentationsLogic = slicer.modules.segmentations.logic()
  segmentationsLogic.ImportModelToSegmentationNode(modelNode, segmentationNode)
  return segmentationNode


def isEmpty(segNode):
  segmentationBounds = [0, -1, 0, -1, 0, -1]
  segNode.GetSegmentation().GetBounds(segmentationBounds)
  isEmpty = segmentationBounds[0] > segmentationBounds[1] or segmentationBounds[2] > segmentationBounds[3] or \
            segmentationBounds[4] > segmentationBounds[5]
  return isEmpty


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


def showOnlySegmentsWithKeywordInName(segmentationNode, keyword):
  hideAllSegments(segmentationNode)
  for segment, segmentID in zip(getAllSegments(segmentationNode), getAllSegmentIDs(segmentationNode)):
    if not keyword in segment.GetName():
      continue
    segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, True)


# def createLabelNodeFromVisibleSegments(segmentationNode, referenceVolumeNode, labelNodeName):
#   labelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", labelNodeName)
#   segmentationsLogic = slicer.modules.segmentations.logic()
#   segmentationsLogic.ExportVisibleSegmentsToLabelmapNode(segmentationNode, labelNode, referenceVolumeNode)
#   return labelNode


def hideAllSegments(segmentationNode):
  for segmentID in getAllSegmentIDs(segmentationNode):
    segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, False)


def showAllSegments(segmentationNode):
  for segmentID in getAllSegmentIDs(segmentationNode):
    segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, True)


def deleteValveMask(segmentationNode):
  segmentation = segmentationNode.GetSegmentation()
  valveMaskSegment = segmentationNode.GetSegmentation().GetSegment(HeartValveLib.Constants.VALVE_MASK_SEGMENT_ID)
  if valveMaskSegment:
    segmentation.RemoveSegment(valveMaskSegment)
    return True
  return False


def checkAndSortSegments(segmentationNode, valveType):
  expectedOrder = LEAFLET_ORDER[valveType]
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
  segmentation = segmentationNode.GetSegmentation()
  segmentInfos = getSortedSegmentInfos(segmentationNode, LEAFLET_ORDER[valveType])
  newSegmentIDs, segments = getSortedSegmentsAndIDs(segmentationNode, segmentInfos, valveType)
  segmentation.RemoveAllSegments()
  for newSegmentID, segment in zip(newSegmentIDs, segments):
    segmentation.AddSegment(segment, newSegmentID)


def getSortedSegmentInfos(segmentationNode, expectedOrder):
  segmentNames = getAllSegmentNames(segmentationNode)
  sortedSegmentNames = list()
  for location in expectedOrder:
    segmentName = getFirstMatchingListElement(segmentNames, location)
    if not segmentName:
      raise ValueError(f"Cannot find segment with keyword {location}. Following segments are available: {segmentNames}")
    sortedSegmentNames.append((segmentName, location))
  return sortedSegmentNames


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
    newSegmentIDs.append(f"{valveType}_{loc}_leaflet")
    segments.append(segmentation.GetSegment(segmentID))
  return newSegmentIDs, segments


def createNewSegmentationNode(masterVolumeNode):
  segmentationNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode')
  segmentationNode.CreateDefaultDisplayNodes()
  segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(masterVolumeNode)
  return segmentationNode


def createLabelNodeFromVisibleSegments(segmentationNode, valveModel, labelNodeName):
  labelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", labelNodeName)
  probeToRasTransform = valveModel.getProbeToRasTransformNode()
  labelNode.SetAndObserveTransformNodeID(probeToRasTransform.GetID())
  segmentationsLogic = slicer.modules.segmentations.logic()
  segmentationsLogic.ExportVisibleSegmentsToLabelmapNode(segmentationNode, labelNode, valveModel.getValveVolumeNode())
  return labelNode


def getLabelFromLandmarkPositions(name, positions, valveModel):
  import random
  segNode = createNewSegmentationNode(valveModel.getValveVolumeNode())
  probeToRasTransform = valveModel.getProbeToRasTransformNode()
  segNode.SetAndObserveTransformNodeID(probeToRasTransform.GetID())
  color = [random.uniform(0.0,1.0), random.uniform(0.0,1.0), random.uniform(0.0,1.0)]

  sphereSegment = slicer.vtkSegment()
  sphereSegment.SetName(name)
  sphereSegment.SetColor(*color)

  append = vtk.vtkAppendPolyData()
  for pos in positions:
    sphere = vtk.vtkSphereSource()
    sphere.SetCenter(*pos)
    sphere.SetRadius(1)
    append.AddInputConnection(sphere.GetOutputPort())
  append.Update()

  sphereSegment.AddRepresentation(
    slicer.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName(), append.GetOutput())
  segNode.GetSegmentation().AddSegment(sphereSegment)

  labelNode = createLabelNodeFromVisibleSegments(segNode, valveModel, name)
  slicer.mrmlScene.RemoveNode(segNode)
  return labelNode