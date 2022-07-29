import os
import logging
import slicer
from pathlib import Path

from collections import OrderedDict
from .base import ValveBatchExportRule
from HeartValveLib.helpers import getSpecificHeartValveMeasurementNodes, getAllFilesWithExtension


class QuantificationResultsExportRule(ValveBatchExportRule):

  BRIEF_USE = "Valve quantification results (.csv)"
  DETAILED_DESCRIPTION = """Export results computed in Valve quantification module. All metrics will be 
  recomputed using current software version
  """
  WIDE_COLUMNS = ['Filename', 'Phase', 'Measurement']
  LONG_COLUMNS = WIDE_COLUMNS + ['Value']
  UNIT_COLUMNS = ['Measurement','Unit']

  WIDE_CSV_OUTPUT_FILENAME = 'QuantificationResults_wide.csv'
  LONG_CSV_OUTPUT_FILENAME = 'QuantificationResults_long.csv'
  HYBRID_CSV_OUTPUT_FILENAME = 'QuantificationResults_hybrid.csv'
  UNITS_CSV_OUTPUT_FILENAME = 'QuantificationUnits.csv'

  OUTPUT_CSV_FILES = [
    WIDE_CSV_OUTPUT_FILENAME,
    LONG_CSV_OUTPUT_FILENAME,
    HYBRID_CSV_OUTPUT_FILENAME,
    UNITS_CSV_OUTPUT_FILENAME
  ]

  CMD_FLAG = "-qr"

  QUANTIFICATION_RESULTS_IDENTIFIER = 'Quantification results'

  def processStart(self):
    self.unitsDictionary = OrderedDict()

    self.wideResultsTableNode = self.createTableNode(*self.WIDE_COLUMNS)
    self.longResultsTableNode = self.createTableNode(*self.LONG_COLUMNS)
    self.hybridTempValues = dict()
    self.valveQuantificationLogic = slicer.modules.valvequantification.widgetRepresentation().self().logic

  def processScene(self, sceneFileName):
    for measurementNode in getSpecificHeartValveMeasurementNodes(self.QUANTIFICATION_RESULTS_IDENTIFIER):

      cardiacCyclePhaseNames = self.valveQuantificationLogic.getMeasurementCardiacCyclePhaseShortNames(measurementNode)
      cardiacCyclePhaseName = ''
      if len(cardiacCyclePhaseNames) == 1:
        cardiacCyclePhaseName = cardiacCyclePhaseNames[0]
        if not cardiacCyclePhaseName in self.EXPORT_PHASES:
          continue
      elif len(cardiacCyclePhaseNames) > 1:
        cardiacCyclePhaseName = "multiple"
        if not all(phaseName in self.EXPORT_PHASES for phaseName in cardiacCyclePhaseNames):
          logging.debug("Multiple phases compare measurement node found but selected phases don't match those. Skipping")
          continue

      # Recompute all measurements
      try:
        self.addLog(f"Computing metrics for '{cardiacCyclePhaseName}'")
        self.valveQuantificationLogic.computeMetrics(measurementNode)
      except Exception as exc:
        logging.warning(f"{sceneFileName} failed with error message: \n{exc}")
        import traceback
        traceback.print_exc()
        continue

      quantificationResultsTableNode = \
        self.getTableNode(measurementNode, self.QUANTIFICATION_RESULTS_IDENTIFIER)

      measurementPresetId = self.valveQuantificationLogic.getMeasurementPresetId(measurementNode)
      if quantificationResultsTableNode:
        filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
        # long data table
        self.addRowData(self.longResultsTableNode, filename, cardiacCyclePhaseName, "ValveType", measurementPresetId)

        # wide table
        resultsTableRowIndex = \
          self.addRowData(self.wideResultsTableNode, filename, cardiacCyclePhaseName, measurementPresetId)

        numberOfMetrics = quantificationResultsTableNode.GetNumberOfRows()
        for metricIndex in range(numberOfMetrics):
          metricName, metricValue, metricUnit = self.getColData(quantificationResultsTableNode, metricIndex, range(3))

          # wide data table
          self.setValueInTable(self.wideResultsTableNode, resultsTableRowIndex, metricName, metricValue)

          # long data table
          self.addRowData(self.longResultsTableNode, filename, cardiacCyclePhaseName, metricName, metricValue)

          # hybrid data table
          if not metricName in list(self.hybridTempValues.keys()):
            self.hybridTempValues[metricName] = dict()
          if not filename in list(self.hybridTempValues[metricName].keys()):
            self.hybridTempValues[metricName][filename] = dict()
          self.hybridTempValues[metricName][filename][cardiacCyclePhaseName] = metricValue

          self.unitsDictionary[metricName] = metricUnit

  def processEnd(self):
    self._writeUnitsTable()
    self.writeTableNodeToCsv(self.wideResultsTableNode, self.WIDE_CSV_OUTPUT_FILENAME, useStringDelimiter=True)
    self.writeTableNodeToCsv(self.longResultsTableNode, self.LONG_CSV_OUTPUT_FILENAME, useStringDelimiter=True)

    def getPhases():
      _phases = list()
      for _filenames in self.hybridTempValues.values():
        for __phases in _filenames.values():
          _phases.extend(list(__phases.keys()))
      return set(_phases)

    # hybrid data table
    phases = sorted(getPhases())
    resultsHybridTableNode = self.createTableNode('Measurement', 'Filename', *phases)

    for metricName, filenames in self.hybridTempValues.items():
      for filename, values in filenames.items():
        phaseValues = [values[phase] if phase in values.keys() else "" for phase in phases]
        self.addRowData(resultsHybridTableNode, metricName, filename, *phaseValues)

    self.writeTableNodeToCsv(resultsHybridTableNode, self.HYBRID_CSV_OUTPUT_FILENAME, useStringDelimiter=True)

  def _writeUnitsTable(self):
    unitsTableNode = self.createTableNode(*self.UNIT_COLUMNS)
    # iterate over units dict
    for metricName, metricUnit in self.unitsDictionary.items():
      self.addRowData(unitsTableNode, metricName, metricUnit)
    self.writeTableNodeToCsv(unitsTableNode, self.UNITS_CSV_OUTPUT_FILENAME, useStringDelimiter=True)

  def mergeTables(self, inputDirectories, outputDirectory):
    unitCSVs = self.findCorrespondingFilesInDirectories(inputDirectories, self.UNITS_CSV_OUTPUT_FILENAME)
    self.concatCSVsAndSave(unitCSVs, Path(outputDirectory) / self.UNITS_CSV_OUTPUT_FILENAME, removeDuplicateRows=True)

    longCSVs = self.findCorrespondingFilesInDirectories(inputDirectories, self.LONG_CSV_OUTPUT_FILENAME)
    self.concatCSVsAndSave(longCSVs, Path(outputDirectory) / self.LONG_CSV_OUTPUT_FILENAME)

    wideCSVs = self.findCorrespondingFilesInDirectories(inputDirectories, self.WIDE_CSV_OUTPUT_FILENAME)
    self.concatCSVsAndSave(wideCSVs, Path(outputDirectory) / self.WIDE_CSV_OUTPUT_FILENAME)

    hybridCSVs = self.findCorrespondingFilesInDirectories(inputDirectories, self.HYBRID_CSV_OUTPUT_FILENAME)
    self.concatCSVsAndSave(hybridCSVs, Path(outputDirectory) / self.HYBRID_CSV_OUTPUT_FILENAME)