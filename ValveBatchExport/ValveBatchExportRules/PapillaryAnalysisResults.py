import os
import slicer
import logging
from pathlib import Path
from collections import OrderedDict

from .base import ValveBatchExportRule
from HeartValveLib.helpers import getSpecificHeartValveMeasurementNodes, getAllHeartValveModelNodes


class PapillaryAnalysisResultsExportRule(ValveBatchExportRule):

  BRIEF_USE = "Valve papillary analysis results (.csv)"
  DETAILED_DESCRIPTION = """
  Export results computed in Valve papillary analysis module. All metrics will be recomputed using current software 
  version
  """
  COLUMNS = ['Filename', 'Phase', 'Valve']
  QUANTIFICATION_RESULTS_IDENTIFIER = "Papillary measurement results"
  MEASUREMENT_PRESET_ID_SUFFIX = "PM"
  RESULTS_CSV_OUTPUT_FILENAME = 'PapillaryAnalysisResults.csv'
  UNITS_CSV_OUTPUT_FILENAME = 'PapillaryAnalysisUnits.csv'

  OUTPUT_CSV_FILES = [
    RESULTS_CSV_OUTPUT_FILENAME,
    UNITS_CSV_OUTPUT_FILENAME
  ]

  CMD_FLAG = "-pr"

  def __init__(self):
    super(PapillaryAnalysisResultsExportRule, self).__init__()

  def processStart(self):
    self._unitsDictionary = OrderedDict()
    self.resultsTableNode = self.createTableNode(*self.COLUMNS)
    self.valveQuantificationLogic = slicer.modules.valvequantification.widgetRepresentation().self().logic

  @classmethod
  def createTemporaryPMHeartValveNode(cls, valveModel):
    heartValveNode = valveModel.getHeartValveNode()
    heartValveMeasurementNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLScriptedModuleNode')
    heartValveMeasurementNode.SetAttribute("ModuleName", "HeartValveMeasurement")
    valveType = valveModel.getValveType()

    def isValidPreset(m):
      return m.QUANTIFICATION_RESULTS_IDENTIFIER == cls.QUANTIFICATION_RESULTS_IDENTIFIER \
             and m.id.lower().startswith(valveType)

    valveQuantificationLogic = slicer.modules.valvequantification.widgetRepresentation().self().logic
    presets = list(filter(lambda preset: isValidPreset(preset), valveQuantificationLogic.measurementPresets))

    if not presets:
      name = heartValveNode.GetName()
      raise ValueError(f"Cannot find PM preset for '{name}' with valve type '{valveModel.getValveType()}'")

    heartValveMeasurementNode.SetAttribute("MeasurementPreset", presets[0].id)
    presetId = heartValveMeasurementNode.GetAttribute("MeasurementPreset")
    measurementPreset = valveQuantificationLogic.getMeasurementPresetById(presetId)
    heartValveMeasurementNode.SetNodeReferenceID('Valve' + measurementPreset.inputValveIds[0], heartValveNode.GetID())

    # configure other heart valve nodes
    for inputValveId in measurementPreset.inputValveIds[1:]:
      valveType = measurementPreset.inputValveNames[inputValveId]
      cardiacCyclePhase = valveModel.getCardiacCyclePhase()
      phaseShortName = valveModel.cardiacCyclePhasePresets[cardiacCyclePhase]["shortname"]
      typeShortName = valveType.lower().split(" ")[0]
      from HeartValveLib.helpers import getFirstValveModelNodeMatchingPhaseAndType
      otherValveModel = getFirstValveModelNodeMatchingPhaseAndType(phaseShortName, typeShortName)
      otherHeartValveNode = otherValveModel.getHeartValveNode()
      heartValveMeasurementNode.SetNodeReferenceID(f'Valve{inputValveId}', otherHeartValveNode.GetID())

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    if heartValveMeasurementNode.GetHideFromEditors():
      heartValveMeasurementNode.SetHideFromEditors(False)
      shNode.RequestOwnerPluginSearch(heartValveMeasurementNode)
      shNode.SetItemAttribute(shNode.GetItemByDataNode(heartValveMeasurementNode), "ModuleName",
                              "HeartValveMeasurement")
    return heartValveMeasurementNode

  def processScene(self, sceneFileName):

    measurementNodes = getSpecificHeartValveMeasurementNodes(self.QUANTIFICATION_RESULTS_IDENTIFIER)

    if measurementNodes:
      self._processScene(sceneFileName, measurementNodes)
    else:
      for valveModel in getAllHeartValveModelNodes():
        cardiacCyclePhase = valveModel.getCardiacCyclePhase()
        shortname = valveModel.cardiacCyclePhasePresets[cardiacCyclePhase]["shortname"]
        if shortname in self.EXPORT_PHASES:
          logging.info(f"Creating temporary papillary measurement node for {shortname}")
          try:
            tempMeasurementNode = self.createTemporaryPMHeartValveNode(valveModel)
          except Exception as exc:
            logging.warning(f"{sceneFileName} failed with error message: \n{exc}")
            continue
          measurementNodes.append(tempMeasurementNode)

      self._processScene(sceneFileName, measurementNodes)

      for measurementNode in measurementNodes:
        slicer.mrmlScene.RemoveNode(measurementNode)

  def _processScene(self, sceneFileName, measurementNodes):
    for measurementNode in measurementNodes:
      cardiacCyclePhaseNames = self.valveQuantificationLogic.getMeasurementCardiacCyclePhaseShortNames(measurementNode)
      cardiacCyclePhaseName = ''
      if len(cardiacCyclePhaseNames) == 1:
        cardiacCyclePhaseName = cardiacCyclePhaseNames[0]
        if not cardiacCyclePhaseName in self.EXPORT_PHASES:
          continue
      elif len(cardiacCyclePhaseNames) > 1:
        cardiacCyclePhaseName = "multiple"
        if not all(phaseName in self.EXPORT_PHASES for phaseName in cardiacCyclePhaseNames):
          logging.debug(
            "Multiple phases compare measurement node found but selected phases don't match those. Skipping")
          continue

      # Recompute all measurements
      try:
        self.valveQuantificationLogic.computeMetrics(measurementNode)
      except Exception as exc:
        logging.warning(f"{sceneFileName} failed with error message: \n{exc}")
        continue

      measurementResultsTableNode = self.getTableNode(measurementNode, self.QUANTIFICATION_RESULTS_IDENTIFIER)
      measurementPresetId = self.valveQuantificationLogic.getMeasurementPresetId(measurementNode)
      valve = measurementPresetId.replace(self.MEASUREMENT_PRESET_ID_SUFFIX, "")

      filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
      resultsTableRowIndex = \
        self.addRowData(self.resultsTableNode, filename, cardiacCyclePhaseName, valve)

      if measurementResultsTableNode:
        numberOfMetrics = measurementResultsTableNode.GetNumberOfRows()
        for metricIndex in range(numberOfMetrics):
          metricName, metricValue, metricUnit = self.getColData(measurementResultsTableNode, metricIndex, range(3))
          self.setValueInTable(self.resultsTableNode, resultsTableRowIndex, metricName, metricValue)
          self._unitsDictionary[metricName] = metricUnit

  def processEnd(self):
    self._writeUnitsTable()
    self.writeTableNodeToCsv(self.resultsTableNode, self.RESULTS_CSV_OUTPUT_FILENAME)

  def _writeUnitsTable(self):
    unitsTableNode = self.createTableNode('Measurement', 'Unit')
    for metricName, metricUnit in self._unitsDictionary.items():
      self.addRowData(unitsTableNode, metricName, metricUnit)
    self.writeTableNodeToCsv(unitsTableNode, self.UNITS_CSV_OUTPUT_FILENAME, useStringDelimiter=True)

  def mergeTables(self, inputDirectories, outputDirectory):
    unitCSVs = self.findCorrespondingFilesInDirectories(inputDirectories, self.UNITS_CSV_OUTPUT_FILENAME)
    self.concatCSVsAndSave(unitCSVs, Path(outputDirectory) / self.UNITS_CSV_OUTPUT_FILENAME, removeDuplicateRows=True)

    resultCSVs = self.findCorrespondingFilesInDirectories(inputDirectories, self.RESULTS_CSV_OUTPUT_FILENAME)
    self.concatCSVsAndSave(resultCSVs, Path(outputDirectory) / self.RESULTS_CSV_OUTPUT_FILENAME)