import os
import qt
import vtk
import logging
import slicer
from HeartValveLib.helpers import getAllHeartValveModelNodes, getSpecificHeartValveModelNodes
from typing import Union


class ValveBatchExportPlugin(qt.QWidget):

  _RULE_CLASS = None

  @property
  def activated(self):
    return self.checkbox.checked

  def __init__(self, ruleClass=None, checked=True):
    qt.QWidget.__init__(self)

    if ruleClass:
      assert issubclass(ruleClass, ValveBatchExportRule)
      self._RULE_CLASS = ruleClass

    self._checked =  checked

    assert self._RULE_CLASS is not None
    self.setup()

  def setup(self):
    self.setLayout(qt.QGridLayout())

    self.checkbox = qt.QCheckBox()
    self.checkbox.checked = self._checked
    self.checkbox.setToolTip(self._RULE_CLASS.DETAILED_DESCRIPTION)

    self.layout().addWidget(self.checkbox)

    if self._RULE_CLASS.USER_INTERFACE is True:
      import ctk
      self.collapsibleButton = ctk.ctkCollapsibleButton()
      self.collapsibleButton.text = "Options"
      self.collapsibleButton.collapsed = 1
      self.collapsibleButton.setEnabled(self._checked)
      layout = qt.QGridLayout()
      self.collapsibleButton.setLayout(layout)
      self.layout().addWidget(self.collapsibleButton)
      self.checkbox.stateChanged.connect(lambda c: self.collapsibleButton.setEnabled(c))
      self._RULE_CLASS.setupUI(layout)

  def getRuleClass(self):
    return self._RULE_CLASS

  def getDescription(self):
    return self._RULE_CLASS.BRIEF_USE


class ValveBatchExportRule(object):

  class NoAssociatedFrameNumberFound(Exception):
    pass

  BRIEF_USE = ""
  DETAILED_DESCRIPTION = ""
  USER_INTERFACE = False

  EXPORT_PHASES = [] # empty means all phases will be exported
  OUTPUT_CSV_FILES = []

  CMD_FLAG = None  # Necessary when running export via python script
  OTHER_FLAGS = []  # changed at runtime for additional options

  @classmethod
  def getAssociatedFrameNumber(cls, valveModel):
    frameNumber = valveModel.getValveVolumeSequenceIndex()
    if frameNumber == -1:
      raise cls.NoAssociatedFrameNumberFound(f"No associated frame found for {valveModel.getCardiacCyclePhase()}")
    return frameNumber

  def generateValveModelName(self, filename, valveType, cardiacCyclePhaseName, frameNumber=None, suffix=""):
    frame = f"frame_{frameNumber}" if frameNumber is not None and frameNumber > -1 else ""
    return self.generateUniqueName("_".join(filter(lambda c: c != "",
                                                   [filename, valveType, frame, cardiacCyclePhaseName, suffix])))

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

  @classmethod
  def setPhasesToExport(cls, phases):
    logging.debug("Phases to export set to: %s" % phases)
    cls.EXPORT_PHASES = phases

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

  def __init__(self):
    self.logCallback = None
    self.outputDir = None
    self.usedNames = set()

  @classmethod
  def setupUI(cls, layout):
    raise NotImplementedError("Method needs to be implemented if class member `USER_INTERFACE` set to True")

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

  def processStart(self):
    pass

  def processScene(self, sceneFileName):
    """Scene is loaded but and some rules might have been already processed the scene.
    All scene modifications should happen in this method."""
    pass

  def afterProcessScene(self, sceneFileName):
    """Scene is loaded and all processing completed.
    No processing should be performed in this method."""
    pass

  def processEnd(self):
    pass


def getNewSegmentationNode(masterVolumeNode):
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