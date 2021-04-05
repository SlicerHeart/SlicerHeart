""" collection of functions that are useful for several classes but non-specific to any """

import slicer
import logging


def getBinaryLabelmapRepresentation(segmentationNode, segmentID: str):
  segmentLabelmap = slicer.vtkOrientedImageData()
  segmentationNode.GetBinaryLabelmapRepresentation(segmentID, segmentLabelmap)
  return segmentLabelmap


def getSpecificHeartValveModelNodes(phases: list):
  heartValveModelNodes = []
  for phase in phases:
    try:
      heartValveModelNodes.append(getValveModelNode(phase))
    except ValueError as exc:
      logging.warning(exc)
  return heartValveModelNodes


def getSpecificHeartValveMeasurementNodes(identifier):
  valveQuantificationLogic = slicer.modules.valvequantification.widgetRepresentation().self().logic
  validMeasurementNodes = []
  for measurementNode in getAllHeartValveMeasurementNodes():
    measurementPreset = valveQuantificationLogic.getMeasurementPresetByMeasurementNode(measurementNode)
    if not measurementPreset or measurementPreset.QUANTIFICATION_RESULTS_IDENTIFIER != identifier:
      continue
    validMeasurementNodes.append(measurementNode)
  return validMeasurementNodes


def getValveModelNode(phase='MS'):
  for valveModelNode in getAllHeartValveModelNodes():
    if valveModelNode.cardiacCyclePhasePresets[valveModelNode.getCardiacCyclePhase()]["shortname"] == phase:
      return valveModelNode
  raise ValueError("Could not find valve for phase %s" % phase)


def getAllHeartValveModelNodes():
  import HeartValves
  return map(HeartValves.getValveModel, getAllHeartValveNodes())


def getAllHeartValveNodes():
  return getAllModuleSpecificScriptableNodes('HeartValve')


def getAllHeartValveMeasurementNodes():
  return getAllModuleSpecificScriptableNodes('HeartValveMeasurement')


def getAllModuleSpecificScriptableNodes(moduleName):
  return filter(lambda node: node.GetAttribute('ModuleName') == moduleName,
                slicer.util.getNodesByClass('vtkMRMLScriptedModuleNode'))


def getHeartValveMeasurementNode(phase):
  for measurementNode in getAllHeartValveMeasurementNodes():
    cardiacCyclePhaseNames = getMeasurementCardiacCyclePhaseShortNames(measurementNode)
    if len(cardiacCyclePhaseNames) == 1 and cardiacCyclePhaseNames[0] == phase:
      return measurementNode


def getMeasurementCardiacCyclePhaseShortNames(measurementNode):
  import ValveQuantification
  valveQuantificationLogic = ValveQuantification.ValveQuantificationLogic()
  return valveQuantificationLogic.getMeasurementCardiacCyclePhaseShortNames(measurementNode)


def getAllFilesWithExtension(directory, extension, file_name_only=False):
  import os
  import fnmatch
  files = []
  for root, dirnames, filenames in os.walk(directory):
    for filename in fnmatch.filter(filenames, '*{}'.format(extension)):
      files.append(filename if file_name_only else os.path.join(root, filename))
  return files


def isMRBFile(mrb_file):
  import os
  return os.path.isfile(mrb_file) and mrb_file.lower().endswith(".mrb")