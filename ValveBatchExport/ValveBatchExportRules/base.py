import os
import qt
import vtk
import logging
import slicer
from HeartValveLib.helpers import (
  getAllHeartValveModelNodes,
  getSpecificHeartValveModelNodes
)

from typing import Union


class ValveBatchExportPlugin(qt.QWidget):

  @property
  def activated(self):
    return self.checkbox.checked

  def __init__(self, ruleClass, checked=True):
    qt.QWidget.__init__(self)
    self.logic = ruleClass
    self._checked = checked
    self.setup()

  def setup(self):
    self.setLayout(qt.QGridLayout())

    self.checkbox = qt.QCheckBox()
    self.checkbox.checked = self._checked
    self.checkbox.setToolTip(self.logic.DETAILED_DESCRIPTION)

    self.layout().addWidget(self.checkbox)

  def getRuleClass(self):
    return self.logic

  def getDescription(self):
    return self.logic.BRIEF_USE

  def getOptionsLayout(self):
    import ctk
    self.collapsibleButton = ctk.ctkCollapsibleButton()
    self.collapsibleButton.text = "Options"
    self.collapsibleButton.collapsed = 1
    self.collapsibleButton.setEnabled(self._checked)
    layout = qt.QGridLayout()
    self.collapsibleButton.setLayout(layout)
    self.layout().addWidget(self.collapsibleButton)
    self.checkbox.stateChanged.connect(lambda c: self.collapsibleButton.setEnabled(c))
    return layout


class ValveBatchExportRule(object):

  class NoAssociatedFrameNumberFound(Exception):
    pass

  BRIEF_USE = ""
  DETAILED_DESCRIPTION = ""

  EXPORT_PHASES = [] # empty means all phases will be exported

  CMD_FLAG = None  # Necessary when running export via python script
  OTHER_FLAGS = []  # changed at runtime for additional options

  @classmethod
  def getAssociatedFrameNumber(cls, valveModel):
    frameNumber = valveModel.getValveVolumeSequenceIndex()
    if frameNumber == -1:
      raise cls.NoAssociatedFrameNumberFound(f"No associated frame found for {valveModel.getCardiacCyclePhase()}")
    return frameNumber

  @classmethod
  def setPhasesToExport(cls, phases : list):
    logging.debug("Phases to export set to: %s" % phases)
    cls.EXPORT_PHASES = phases

  def __init__(self):
    self.logCallback = None
    self.outputDir = None      # TODO: need to check when exporting if output dir was set and existing
    self.usedNames = set()

  def generateValveModelName(self, sceneFileName, valveModel, suffix=""):
    frameNumber = self.getAssociatedFrameNumber(valveModel)
    filename, _ = os.path.splitext(os.path.basename(sceneFileName))
    valveType = valveModel.getValveType()
    cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
    frame = f"frame_{frameNumber}" if frameNumber is not None and frameNumber > -1 else ""
    return self.generateUniqueName("_".join(filter(lambda c: c != "",
                                                   [filename, valveType, frame, cardiacCyclePhaseName, suffix])))

  def getHeartValveModelNodes(self):
    if self.EXPORT_PHASES:
      return getSpecificHeartValveModelNodes(self.EXPORT_PHASES)
    else:
      return getAllHeartValveModelNodes()

  def addLog(self, text):
    logging.info(text)
    if self.logCallback:
      self.logCallback(text)

  def generateUniqueName(self, name):
    if name in self.usedNames:
      nameCounter = 1
      while True:
        uniqueName = f"{name}_{nameCounter}"
        if uniqueName not in self.usedNames:
          break
        nameCounter += 1
    else:
      uniqueName = name
    self.usedNames.add(uniqueName)
    return uniqueName

  def processStart(self):
    pass

  def processScene(self, sceneFileName):
    """Scene is loaded and some rules might have been already processed the scene.
    All scene modifications should happen in this method."""
    pass

  def processEnd(self):
    pass


class QuantitativeValveBatchExportRule(ValveBatchExportRule):

  OUTPUT_CSV_FILES = []

  @staticmethod
  def addRowData(tableNode, *args):
    rowIndex = tableNode.AddEmptyRow()
    for colIdx, value in enumerate(args):
      tableNode.SetCellText(rowIndex, colIdx, value)
    return rowIndex

  @staticmethod
  def getColData(tableNode, rowIndex: int, colIndices: Union[list, range]):
    return [tableNode.GetCellText(rowIndex, colIdx) for colIdx in colIndices]

  @staticmethod
  def createTableNode(*columns):
    tableNode = slicer.vtkMRMLTableNode()
    for col in columns:
      tableNode.AddColumn().SetName(col)
    return tableNode

  @staticmethod
  def getTableNode(measurementNode, identifier):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    measurementResultTableItems = vtk.vtkIdList()
    shNode.GetItemChildren(shNode.GetItemByDataNode(measurementNode), measurementResultTableItems, "vtkMRMLTableNode")
    numberOfMeasurementTables = measurementResultTableItems.GetNumberOfIds()
    for measurementTableIndex in range(numberOfMeasurementTables):
      itemId = measurementResultTableItems.GetId(measurementTableIndex)
      if shNode.GetItemName(itemId) == identifier:
        return shNode.GetItemDataNode(itemId)
    raise ValueError(f"vtkMRMLTableNode with id {identifier} not found for given measurement node.")

  @staticmethod
  def setValueInTable(tableNode, rowIndex, columnName, value):
    resultsArray = tableNode.GetTable().GetColumnByName(columnName)
    if not resultsArray:
      resultsArray = tableNode.AddColumn()
      resultsArray.SetName(columnName)
      n = tableNode.GetNumberOfRows()
      resultsArray.SetNumberOfValues(n)
      for j in range(n):
        resultsArray.SetValue(j, '')
    resultsArray.SetValue(rowIndex, value)

  @staticmethod
  def findCorrespondingFilesInDirectories(dirs: list, filename: str):
    from pathlib import Path
    files = []

    for d in dirs:
      f = (Path(d) / filename)
      if f.exists():
        files.append(str(f))

    return files

  @classmethod
  def concatCSVsAndSave(cls, inputCSVs, outFile, removeDuplicateRows=False):
    import pandas as pd

    dfs = cls.loadCSVs(inputCSVs)
    if len(dfs) == 0:
      raise ValueError("No CSV files found for merging")
    if len(dfs) > 1:
      df = pd.concat(dfs)
      if removeDuplicateRows:
        df = df.drop_duplicates()
    else:
      df = dfs[0]
    cls.saveCSV(df, outFile)

  @staticmethod
  def loadCSVs(inputCSVs: list) -> list:
    import pandas as pd
    return [pd.read_csv(f) for f in inputCSVs]

  @staticmethod
  def saveCSV(df, outputFile):
    df.to_csv(str(outputFile), index=False)

  def writeTableNodeToCsv(self, tableNode, filename, useStringDelimiter = False):
    """
    Write table node to CSV file
    :param tableNode:
    :param filename:
    :param useStringDelimiter: if True then quotes will be placed around each value
    """
    writer = vtk.vtkDelimitedTextWriter()
    filepath = os.path.join(self.outputDir, filename)
    writer.SetFileName(filepath)
    writer.SetInputData(tableNode.GetTable())
    writer.SetFieldDelimiter(",")
    writer.SetUseStringDelimiter(useStringDelimiter)
    if not writer.Write():
      raise Exception('Failed to write file: ' + filepath)

  def mergeTables(self, inputDirectories: list, outputDirectory: str):
    """ takes input directories and looks for specific file(s) defined per class
    """
    pass


class ImageValveBatchExportRule(ValveBatchExportRule):

  FILE_FORMAT_OPTIONS = [".nrrd",
                         ".nii.gz"]
  FILE_FORMAT = ".nrrd"


