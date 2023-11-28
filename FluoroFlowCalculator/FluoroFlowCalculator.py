import logging

import ctk
import qt
import vtk

import slicer
from slicer.ScriptedLoadableModule import *


#
# FluoroFlowCalculator - based on the CropVolumeSequence module
#

class FluoroFlowCalculator(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Fluoro Flow Calculator"
    self.parent.categories = ["Sequences"]
    self.parent.dependencies = []
    self.parent.contributors = ["Yuval Barak-Corren (CHOP), Andras Lasso (PerkLab, Queen's University)"]
    self.parent.helpText = """This module can extract frame-by-frame statistics for a sequence"""
    self.parent.acknowledgementText = """
This file was originally developed by Andras Lasso and modified by Yuval Barak-Corren
"""


#
# FluoroFlowCalculatorWidget
#

class FluoroFlowCalculatorWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Instantiate and connect widgets ...

    #
    # Parameters Area
    #
    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(parametersCollapsibleButton)

    # Layout within the dummy collapsible button
    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    #
    # input volume selector
    #
    self.inputSelector = slicer.qMRMLNodeComboBox()
    self.inputSelector.nodeTypes = ["vtkMRMLSequenceNode"]
    self.inputSelector.addEnabled = False
    self.inputSelector.removeEnabled = False
    self.inputSelector.noneEnabled = False
    self.inputSelector.showHidden = False
    self.inputSelector.showChildNodeTypes = False
    self.inputSelector.setMRMLScene(slicer.mrmlScene)
    self.inputSelector.setToolTip("Pick a sequence node of volumes that will be analyzed.")
    parametersFormLayout.addRow("Input volume/2D sequence: ", self.inputSelector)

    # Sequence start index
    self.sequenceStartItemIndexWidget = ctk.ctkSliderWidget()
    self.sequenceStartItemIndexWidget.minimum = 0
    self.sequenceStartItemIndexWidget.decimals = 0
    self.sequenceStartItemIndexWidget.setToolTip("First frame of contrast injection")
    parametersFormLayout.addRow("Start frame index:", self.sequenceStartItemIndexWidget)

    # Sequence end index
    self.sequenceEndItemIndexWidget = ctk.ctkSliderWidget()
    self.sequenceEndItemIndexWidget.minimum = 0
    self.sequenceEndItemIndexWidget.decimals = 0
    self.sequenceEndItemIndexWidget.setToolTip("Last frame of contrast injection")
    parametersFormLayout.addRow("End frame index:", self.sequenceEndItemIndexWidget)


    # Segmentation selector
    self.segmentationSelector = slicer.qMRMLNodeComboBox()
    self.segmentationSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
    self.segmentationSelector.addEnabled = False
    self.segmentationSelector.removeEnabled = True
    self.segmentationSelector.renameEnabled = True
    self.segmentationSelector.setMRMLScene(slicer.mrmlScene)
    self.segmentationSelector.setToolTip("Pick the segmentation to compute statistics for")
    parametersFormLayout.addRow("Segmentation:", self.segmentationSelector)

    # Output dir for CSV file selector
    self.outputDirSelector = ctk.ctkPathLineEdit()
    self.outputDirSelector.filters = ctk.ctkPathLineEdit.Dirs
    self.outputDirSelector.settingKey = 'csvTableExportOutputDir'
    self.outputDirSelector.setToolTip("Directory that will contain summary csv table")
    parametersFormLayout.addRow("Output directory:", self.outputDirSelector)

    # Selectors removed from the original module (crop-volume-sequence)
    # self.outputSelector
    # self.cropParametersSelector
    # self.editCropParametersButton

    #
    # Create Segmentation Button
    #
    self.createSegmentationButton = qt.QPushButton("Create Segmentation")
    self.createSegmentationButton.toolTip = "Split the screen into 2 segmentations - right & left"
    self.createSegmentationButton.enabled = (self.inputSelector.currentNode() is not None)
    parametersFormLayout.addRow(self.createSegmentationButton)

    #
    # Apply Button
    #
    self.applyButton = qt.QPushButton("Apply")
    self.applyButton.toolTip = "Run the algorithm."
    self.applyButton.enabled = False
    parametersFormLayout.addRow(self.applyButton)

    # connections
    self.applyButton.connect('clicked(bool)', self.onApplyButton)
    self.createSegmentationButton.connect('clicked(bool)', self.onCreateSegmentationButton)
    self.inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelect)
    self.segmentationSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onNodeSelectionChanged)
    self.sequenceStartItemIndexWidget.connect('valueChanged(double)', self.setSequenceItemIndex)
    self.sequenceEndItemIndexWidget.connect('valueChanged(double)', self.setSequenceItemIndex)


    # Add vertical spacer
    self.layout.addStretch(1)

    # Refresh Apply button state
    self.onSelect()

  def cleanup(self):
    pass

  def onSelect(self):
    self.applyButton.enabled = (self.inputSelector.currentNode() and self.segmentationSelector.currentNode())

    if not self.inputSelector.currentNode():
      numberOfDataNodes = 0
    else:
      numberOfDataNodes = self.inputSelector.currentNode().GetNumberOfDataNodes()

    for sequenceItemSelectorWidget in [self.sequenceStartItemIndexWidget, self.sequenceEndItemIndexWidget]:
      if numberOfDataNodes < 1:
        sequenceItemSelectorWidget.maximum = 0
        sequenceItemSelectorWidget.enabled = False
      else:
        sequenceItemSelectorWidget.maximum = numberOfDataNodes-1
        sequenceItemSelectorWidget.enabled = True

    self.sequenceStartItemIndexWidget.value =  0
    self.sequenceEndItemIndexWidget.value = self.sequenceEndItemIndexWidget.maximum


  def onNodeSelectionChanged(self):
    self.applyButton.enabled = (self.segmentationSelector.currentNode() is not None)
    self.createSegmentationButton.enabled = (self.inputSelector.currentNode() is not None)
    # if self.segmentationSelector.currentNode():
    #     self.outputTableSelector.baseName = self.segmentationSelector.currentNode().GetName() + ' statistics'

  def findBrowserForSequence(self, sequenceNode):
    browserNodes = slicer.util.getNodesByClass("vtkMRMLSequenceBrowserNode")
    for browserNode in browserNodes:
      if browserNode.IsSynchronizedSequenceNode(sequenceNode, True):
        return browserNode
    return None


  def setSequenceItemIndex(self, index):
    sequenceBrowserNode = self.findBrowserForSequence(self.inputSelector.currentNode())
    sequenceBrowserNode.SetSelectedItemNumber(int(index))


  def onApplyButton(self):
    logic = FluoroFlowCalculatorLogic()
    self.outputDirSelector.addCurrentPathToHistory()

    startFrameIndex = int(self.sequenceStartItemIndexWidget.value)
    endFrameIndex = int(self.sequenceEndItemIndexWidget.value)

    logic.run(self.inputSelector.currentNode(),
              self.segmentationSelector.currentNode(),
              self.outputDirSelector.currentPath,
              startFrameIndex,
              endFrameIndex)

  def onCreateSegmentationButton(self):

    sequenceNode = self.inputSelector.currentNode()
    seqBrowser = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode")
    seqBrowser.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
    volumeNode = seqBrowser.GetProxyNode(sequenceNode)

    try:
      if (self.segmentationSelector.currentNode() is not None):
        segmentationNode = self.segmentationSelector.currentNode()
      else:
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode')
        segmentationNode.CreateDefaultDisplayNodes()
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(volumeNode)

      if segmentationNode.GetSegmentation().GetSegmentIdBySegmentName('left') != '':
        leftSegmentId = segmentationNode.GetSegmentation().GetSegmentIdBySegmentName('left')
      else:
        leftSegmentId = segmentationNode.GetSegmentation().AddEmptySegment("left")

      if segmentationNode.GetSegmentation().GetSegmentIdBySegmentName('right') != '':
        rightSegmentId = segmentationNode.GetSegmentation().GetSegmentIdBySegmentName('right')
      else:
        rightSegmentId = segmentationNode.GetSegmentation().AddEmptySegment("right")

      segmentId = leftSegmentId
      segmentArray = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId, volumeNode)
      segmentArray[:, :, :] = 0 # clear the existing segment
      # The segmentArray dimensions are of the form of [depth=1,height=512,width=512]
      segmentArray[0, :, int(segmentArray.shape[2] / 2):] = 1  # fill region using numpy indexing
      slicer.util.updateSegmentBinaryLabelmapFromArray(segmentArray, segmentationNode, segmentId, volumeNode)

      segmentId = rightSegmentId
      segmentArray = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId, volumeNode)
      segmentArray[:, :, :] = 0 # clear the existing segment
      # The segmentArray dimensions are of the form of [depth=1,height=512,width=512]
      segmentArray[0, :, 0:int(segmentArray.shape[2] / 2)] = 1  # fill region using numpy indexing
      slicer.util.updateSegmentBinaryLabelmapFromArray(segmentArray, segmentationNode, segmentId, volumeNode)
    finally:
      slicer.mrmlScene.RemoveNode(seqBrowser)
      slicer.mrmlScene.RemoveNode(volumeNode)

#
# FluoroFlowCalculatorLogic
#

class FluoroFlowCalculatorLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def transformForSequence(self, volumeSeq):
    seqBrowser = slicer.modules.sequences.logic().GetFirstBrowserNodeForSequenceNode(volumeSeq)
    if not seqBrowser:
      return None
    proxyVolume = seqBrowser.GetProxyNode(volumeSeq)
    if not proxyVolume:
      return None
    return proxyVolume.GetTransformNodeID()

  #
  # Create the output table - create table with 0 rows and one column per each available segmentation
  # within the selected segmentation node.
  #
  def initializeTable(self, table, selectedSegmentation):

    # Get the list of all segments within the selected segmentation node
    selectedSegmentIds = vtk.vtkStringArray()
    selectedSegmentation.GetSegmentation().GetSegmentIDs(selectedSegmentIds)

    # start creating the table
    tableWasModified = table.StartModify()
    table.RemoveAllColumns()

    col = table.AddColumn()  # AddColumn(vtk.vtkDoubleArray())
    col.SetName("Frame")

    # For each segmentation create a table column with the segmentation name as header
    columnIndex = 1
    for segmentIndex in range(selectedSegmentIds.GetNumberOfValues()):
      segmentID = selectedSegmentIds.GetValue(segmentIndex)
      segment = selectedSegmentation.GetSegmentation().GetSegment(segmentID)

      col = table.AddColumn() # AddColumn(vtk.vtkDoubleArray())
      col.SetName(segment.GetName())
      columnIndex += 1

    table.Modified()
    table.EndModify(tableWasModified)

  def appendToTable(self, frame_number, statistics, table):
    """
    Export statistics to table node
    """
    tableWasModified = table.StartModify()

    # Fill table with stats
    rowIndex = table.AddEmptyRow()

    table.GetTable().GetColumn(0).SetValue(rowIndex, str(frame_number))

    columnIndex = 1
    for segmentID in statistics["SegmentIDs"]:
      # Option 1: get the median intensity level
      # value = statistics[segmentID, 'ScalarVolumeSegmentStatisticsPlugin.median']
      # Option 2: get the 'total' contrast in the segment (volume * mean)
      value = statistics[segmentID, 'ScalarVolumeSegmentStatisticsPlugin.volume_mm3'] * (255-statistics[segmentID, 'ScalarVolumeSegmentStatisticsPlugin.mean'])
      table.GetTable().GetColumn(columnIndex).SetValue(rowIndex, str(value))
      columnIndex += 1

    table.Modified()
    table.EndModify(tableWasModified)

  def showTable(self, table):
    """
    Switch to a layout where tables are visible and show the selected table
    """
    currentLayout = slicer.app.layoutManager().layout
    layoutWithTable = slicer.modules.tables.logic().GetLayoutWithTable(currentLayout)
    slicer.app.layoutManager().setLayout(layoutWithTable)
    slicer.app.applicationLogic().GetSelectionNode().SetActiveTableID(table.GetID())
    slicer.app.applicationLogic().PropagateTableSelection()


  def calcStatsForSeqBrowser(self, frame_number, segStatLogic, tbl):
    # Compute statistics
    segStatLogic.computeStatistics()
    statistics = segStatLogic.getStatistics()

    # add stats to table
    self.appendToTable(frame_number, statistics, tbl)
    self.showTable(tbl)

  def run(self, inputVolSeq, selectedSegmentation, outputDir, startFrameIndex, endFrameIndex):

    import SegmentStatistics

    # initialize the results table - each segmentation gets a unique column
    resultsTableNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTableNode')
    self.initializeTable(resultsTableNode, selectedSegmentation)

    seqBrowser = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode")
    seqBrowser.SetAndObserveMasterSequenceNodeID(inputVolSeq.GetID())
    # seqBrowser.SetSaveChanges(inputVolSeq, True)  # allow modifying node in the sequence

    seqBrowser.SetSelectedItemNumber(0)
    slicer.modules.sequences.logic().UpdateAllProxyNodes()
    slicer.app.processEvents()
    inputVolume = seqBrowser.GetProxyNode(inputVolSeq)
    # inputVolume.SetAndObserveTransformNodeID(inputVolTransformNodeID)
    try:
      qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
      numberOfDataNodes = inputVolSeq.GetNumberOfDataNodes()

      # For each frame in the sequence
      for seqItemNumber in range(0, min(numberOfDataNodes,endFrameIndex)):
        slicer.app.processEvents(qt.QEventLoop.ExcludeUserInputEvents)
        seqBrowser.SetSelectedItemNumber(seqItemNumber)
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(seqBrowser)

        segStatLogic = SegmentStatistics.SegmentStatisticsLogic()
        segStatLogic.getParameterNode().SetParameter("Segmentation", selectedSegmentation.GetID())
        segStatLogic.getParameterNode().SetParameter("ScalarVolume", seqBrowser.GetProxyNode(inputVolSeq).GetID() )

        self.calcStatsForSeqBrowser(seqItemNumber - startFrameIndex, segStatLogic, resultsTableNode)
        logging.info(f'seqItemNumber={seqItemNumber}')

      # save output table as csv file into output folder
      slicer.util.saveNode(resultsTableNode, f'{outputDir}/{inputVolSeq.GetName()}.csv')
      # logging.info(f'{outputDir}{inputVolSeq.GetName()}.csv')

      # Calculate relative perfusion
      import numpy as np

      table = resultsTableNode.GetTable()
      baseline_left = []
      baseline_right = []
      total_left = 0
      total_right = 0

      for i in range(table.GetNumberOfRows()):
        frame_num = (table.GetValueByName(i, 'Frame')).ToInt()
        left = (table.GetValueByName(i, 'left')).ToDouble()
        right = (table.GetValueByName(i, 'right')).ToDouble()
        if(frame_num < 0):
          baseline_left.append(left)
          baseline_right.append(right)
        if (frame_num >= 0):
          total_left = (left - np.mean(baseline_left) )
          total_right = (right - np.mean(baseline_right))

      prcnt_to_left =  round(100 * (total_left / (total_left + total_right)), 0)
      prcnt_to_right = round(100 * (total_right / (total_left + total_right)), 0)
      slicer.util.messageBox(f"The calculated flow-split is: Left={prcnt_to_left}%, Right={prcnt_to_right}%")

    finally:
      qt.QApplication.restoreOverrideCursor()
      slicer.mrmlScene.RemoveNode(seqBrowser)
      slicer.mrmlScene.RemoveNode(inputVolume)
      seqBrowser = slicer.modules.sequences.logic().GetFirstBrowserNodeForSequenceNode(inputVolSeq)
      slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(seqBrowser)




class FluoroFlowCalculatorTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)


