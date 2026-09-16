""" collection of functions that are useful for several classes but non-specific to any """

import slicer
import logging


def getBinaryLabelmapRepresentation(segmentationNode, segmentID: str):
  segmentLabelmap = slicer.vtkOrientedImageData()
  segmentationNode.GetBinaryLabelmapRepresentation(segmentID, segmentLabelmap)
  return segmentLabelmap


def getSpecificHeartValveModelNodes(phases: list):
  """ Generator: see getValveModelNodesMatchingPhase for why results must be consumed one at a time. """
  for phase in phases:
    try:
      yield from getValveModelNodesMatchingPhase(phase)
    except ValueError as exc:
      logging.warning(exc)


def getSpecificHeartValveModelNodesMatchingPhaseAndType(phases: list, valveType: str, sort:bool=True):
  valveModels = []
  for valveModel in getAllHeartValveModelNodes():
    if valveModel.getValveType() == valveType and getValvePhaseShortName(valveModel) in phases:
      valveModels.append(valveModel)
  if sort:
    return sorted(valveModels, key=lambda vm: phases.index(getValvePhaseShortName(vm)))
  return valveModels


def getAllHeartValveModelsForValveType(valveType: str):
  valveModels = []
  for valveModel in getAllHeartValveModelNodes():
    if valveModel.getValveType() == valveType:
      valveModels.append(valveModel)
  return sorted(valveModels, key=lambda vm: vm.getValveVolumeSequenceIndex())


def getSpecificHeartValveMeasurementNodes(identifier):
  valveQuantificationLogic = slicer.modules.valvequantification.widgetRepresentation().self().logic
  validMeasurementNodes = []
  for measurementNode in getAllHeartValveMeasurementNodes():
    measurementPreset = valveQuantificationLogic.getMeasurementPresetByMeasurementNode(measurementNode)
    if not measurementPreset or measurementPreset.QUANTIFICATION_RESULTS_IDENTIFIER != identifier:
      continue
    validMeasurementNodes.append(measurementNode)
  return validMeasurementNodes


def getFirstValveModelNodeMatchingPhase(phase='MS'):
  for valveModelNode in getAllHeartValveModelNodes():
    if getValvePhaseShortName(valveModelNode) == phase:
      return valveModelNode
  raise ValueError("Could not find valve for phase %s" % phase)


def getFirstValveModelNodeMatchingSequenceIndex(seqIdx):
  for valveModelNode in getAllHeartValveModelNodes():
    if valveModelNode.getValveVolumeSequenceIndex() == seqIdx:
      return valveModelNode
  raise ValueError(f"Could not find valve for sequence index {seqIdx}")


def getFirstValveModelNodeMatchingSequenceIndexAndValveType(seqIdx: int, valveType: str):
  for valveModelNode in getAllHeartValveModelNodes():
    if valveModelNode.getValveVolumeSequenceIndex() == seqIdx and valveModelNode.getValveType() == valveType:
      return valveModelNode
  raise ValueError(f"Could not find valve of type '{valveType}' for sequence index {seqIdx}")


def getValveBrowserNode(valveNode):
  """ Sequence browser driving valveNode, or None if the scene is not in sequence format. """
  return slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(valveNode)


def getValveTimePointsMatchingPhase(valveNode, phase):
  """ Browser item numbers whose stored valve is annotated with the given phase short name. """
  from HeartValveLib.Constants import CARDIAC_CYCLE_PHASE_PRESETS
  browserNode = getValveBrowserNode(valveNode)
  if not browserNode:
    return []
  sequenceNode = browserNode.GetSequenceNode(valveNode)
  masterSequenceNode = browserNode.GetMasterSequenceNode()
  if not sequenceNode or not masterSequenceNode:
    return []
  itemNumbers = []
  for index in range(sequenceNode.GetNumberOfDataNodes()):
    dataNode = sequenceNode.GetNthDataNode(index)
    if dataNode is None:
      # Sequence reports the item but its stored node is missing, e.g. data that failed to load.
      logging.warning(f"{sequenceNode.GetName()} has no data node at item {index}, skipping")
      continue
    cardiacCyclePhase = dataNode.GetAttribute("CardiacCyclePhase")
    preset = CARDIAC_CYCLE_PHASE_PRESETS.get(cardiacCyclePhase) if cardiacCyclePhase else None
    if preset and preset["shortname"] == phase:
      itemNumber = masterSequenceNode.GetItemNumberFromIndexValue(sequenceNode.GetNthIndexValue(index), False)
      if itemNumber >= 0:
        itemNumbers.append(itemNumber)
  return itemNumbers


def getValveModelNodesMatchingPhase(phase):
  """ Yield a valve model for every valve annotated with the given phase short name.

  In sequence scenes a valve type has a single proxy node whose CardiacCyclePhase reflects the frame
  the browser is on, so the browser is moved to the matching time point before yielding. Results must
  therefore be consumed one at a time - the proxy node is reused across iterations.
  """
  import HeartValves
  for valveModelNode in getAllHeartValveModelNodes():
    valveNode = valveModelNode.heartValveNode
    browserNode = getValveBrowserNode(valveNode)
    if not browserNode:
      if getValvePhaseShortName(valveModelNode) == phase:
        yield valveModelNode
      continue
    for itemNumber in getValveTimePointsMatchingPhase(valveNode, phase):
      browserNode.SetSelectedItemNumber(itemNumber)
      yield HeartValves.getValveModel(valveNode)


def getFirstValveModelNodeMatchingPhaseAndType(phase, valveType):
  for valveModel in getValveModelNodesMatchingPhase(phase):
    if valveModel.getValveType() == valveType:
      return valveModel
  raise ValueError(f"Could not find valve with type {valveType} for phase {phase}")


def getValveModelNodesMatchingPhaseAndType(phase, valveType):
  valveModels = []
  for valveModel in getValveModelNodesMatchingPhase(phase):
    if valveModel.getValveType() == valveType:
      valveModels.append(valveModel)
  return valveModels


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


def getValveModelForSegmentationNode(segmentationNode):
  for valveModel in getAllHeartValveModelNodes():
    if valveModel.getLeafletSegmentationNode() is segmentationNode:
      return valveModel
  return None


def getValvePhaseShortName(valveModel):
  cardiacPhase = valveModel.getCardiacCyclePhase()
  cardiacCyclePhasePreset = valveModel.cardiacCyclePhasePresets[cardiacPhase]
  return cardiacCyclePhasePreset['shortname']


def hideAllSlicerHeartData():
  for valveModel in getAllHeartValveModelNodes():
    setValveModelDataVisibility(valveModel)


def setValveModelDataVisibility(valveModel, **kwargs):
  """ set visibility of SlicerHeart data for a specific valve model. By default everything will be hidden
  :param valveModel:
  :param kwargs: {
    annulus: False,
    annulusLabels:False,
    segmentation:False,
    roi:False,
    leafletModels:False,
    papillaryModels:False,
    coaptationModels:False}
  :return:
  """
  # TODO: add papillary models and coaptations
  annulusContourMarkupNode = valveModel.getAnnulusContourMarkupNode()
  if annulusContourMarkupNode:
    annulusContourMarkupNode.SetDisplayVisibility(kwargs.get("annulus", False))

  annulusLabelsMarkupNode = valveModel.getAnnulusLabelsMarkupNode()
  if annulusLabelsMarkupNode:
    annulusLabelsMarkupNode.SetDisplayVisibility(kwargs.get("annulusLabels", False))

  leafletSegmentationNode = valveModel.getLeafletSegmentationNode()
  if leafletSegmentationNode:
    leafletSegmentationNode.SetDisplayVisibility(kwargs.get("segmentation", False))

  valveRoiModelNode = valveModel.getValveRoiModelNode()
  if valveRoiModelNode:
    valveRoiModelNode.SetDisplayVisibility(kwargs.get("roi", False))

  for leafletModel in valveModel.leafletModels:
    # TODO
    show = kwargs.get("leafletModels", False)
  for papModel in valveModel.papillaryModels:
    # TODO
    show = kwargs.get("papillaryModels", False)
  for coaptModel in valveModel.coaptationModels:
    # TODO
    show = kwargs.get("coaptationModels", False)