""" collection of functions that are useful for several classes but non-specific to any """

import contextlib
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
  """ Valve models of the given valve type that are annotated with one of the given phase short names.

  In sequence scenes a valve has a single proxy node for all of its time points, so the same valve
  model is returned once per matching time point, and the valve browser is left at the time point of
  the LAST returned model. Use getValveTimePointsMatchingPhase / valveTimePointSelected to work with
  a specific phase of a valve.
  :param sort: order the models by the position of their phase in `phases` (else by valve, then phase)
  """
  matches = []  # (valve order in the scene, index of the phase in phases, valve model, time point)
  for valveOrder, valveModel in enumerate(getAllHeartValveModelNodes()):
    if valveModel.getValveType() != valveType:
      continue
    valveNode = valveModel.heartValveNode
    if not getValveBrowserNode(valveNode):
      shortName = getValvePhaseShortName(valveModel)
      if shortName in phases:
        matches.append((valveOrder, phases.index(shortName), valveModel, -1))
      continue
    for phaseIndex, phase in enumerate(phases):
      for itemNumber in getValveTimePointsMatchingPhase(valveNode, phase):
        matches.append((valveOrder, phaseIndex, valveModel, itemNumber))
  if sort:
    matches.sort(key=lambda match: (match[1], match[0]))
  valveModels = []
  for _, _, valveModel, itemNumber in matches:
    selectValveTimePoint(valveModel.heartValveNode, itemNumber)
    valveModels.append(valveModel)
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
  """ First valve annotated at volume frame seqIdx, shown at that time point (see
  getValveModelNodesMatchingSequenceIndex). Raises ValueError if there is none. """
  for valveModel in getValveModelNodesMatchingSequenceIndex(seqIdx):
    return valveModel
  raise ValueError(f"Could not find valve for sequence index {seqIdx}")


def getFirstValveModelNodeMatchingSequenceIndexAndValveType(seqIdx: int, valveType: str):
  """ First valve of the given type annotated at volume frame seqIdx, shown at that time point (see
  getValveModelNodesMatchingSequenceIndex). Raises ValueError if there is none. """
  for valveModel in getValveModelNodesMatchingSequenceIndex(seqIdx):
    if valveModel.getValveType() == valveType:
      return valveModel
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


def getValveTimePointMatchingSequenceIndex(valveNode, seqIdx):
  """ Browser item number of the time point of valveNode that annotates volume frame seqIdx (0-based
  item number of the valve volume sequence), or -1 if the valve has no time point at that frame or
  the scene is not in sequence format. """
  browserNode = getValveBrowserNode(valveNode)
  if not browserNode:
    return -1
  import HeartValves
  volumeSequenceNode = HeartValves.getValveBrowser(browserNode).volumeSequenceNode
  masterSequenceNode = browserNode.GetMasterSequenceNode()
  if not volumeSequenceNode or not masterSequenceNode:
    return -1
  if seqIdx < 0 or seqIdx >= volumeSequenceNode.GetNumberOfDataNodes():
    return -1
  return masterSequenceNode.GetItemNumberFromIndexValue(volumeSequenceNode.GetNthIndexValue(seqIdx), True)


def selectValveTimePoint(valveNode, itemNumber):
  """ Show the given time point (browser item number) of a valve. Nothing is done for a negative item
  number or for a valve that is not in sequence format. """
  browserNode = getValveBrowserNode(valveNode)
  if browserNode and itemNumber >= 0 and browserNode.GetSelectedItemNumber() != itemNumber:
    browserNode.SetSelectedItemNumber(itemNumber)


@contextlib.contextmanager
def valveTimePointSelected(valveNode, itemNumber):
  """ Show the given time point of a valve for the duration of the block and restore the time point
  that was shown before afterwards (also when the block raises). """
  browserNode = getValveBrowserNode(valveNode)
  originalItemNumber = browserNode.GetSelectedItemNumber() if browserNode else -1
  selectValveTimePoint(valveNode, itemNumber)
  try:
    yield
  finally:
    if browserNode and originalItemNumber >= 0:
      browserNode.SetSelectedItemNumber(originalItemNumber)


def getValveModelNodesMatchingSequenceIndex(seqIdx):
  """ Yield a valve model for every valve annotated at volume frame seqIdx.

  As in getValveModelNodesMatchingPhase, the valve browser is moved to the matching time point before
  the (shared proxy) valve model is yielded, so results must be consumed one at a time. Valves that are
  not in sequence format are matched by their ValveVolumeSequenceIndex attribute.
  """
  import HeartValves
  for valveModel in getAllHeartValveModelNodes():
    valveNode = valveModel.heartValveNode
    if not getValveBrowserNode(valveNode):
      if _legacyValveVolumeSequenceIndex(valveNode) == seqIdx:
        yield valveModel
      continue
    itemNumber = getValveTimePointMatchingSequenceIndex(valveNode, seqIdx)
    if itemNumber < 0:
      continue
    selectValveTimePoint(valveNode, itemNumber)
    yield HeartValves.getValveModel(valveNode)


def _legacyValveVolumeSequenceIndex(valveNode):
  """ Frame of a valve node that is not in sequence format (-1 if undefined). """
  try:
    return int(valveNode.GetAttribute("ValveVolumeSequenceIndex"))
  except (TypeError, ValueError):
    return -1


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


def getAllMeasurementNodesForHeartValveNode(heartValveNode: slicer.vtkMRMLScriptedModuleNode):
  from ValveQuantification import ValveQuantificationLogic
  l = ValveQuantificationLogic()

  matchingMeasurementNodes = []
  for measurementNode in getAllHeartValveMeasurementNodes():
    preset = l.getMeasurementPresetByMeasurementNode(measurementNode)
    if not preset:
      continue
    for inputValveId in preset.inputValveIds:
      role = 'Valve' + inputValveId
      assocHeartValveNode = measurementNode.GetNodeReference(role)
      if assocHeartValveNode and assocHeartValveNode is heartValveNode:
        matchingMeasurementNodes.append(measurementNode)
  return matchingMeasurementNodes


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
  if segmentationNode is None:
    # would match any valve that has no leaflet segmentation
    return None
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