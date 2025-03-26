import logging
import os
import unittest

import ctk
import qt
import slicer
import vtk
import numpy as np
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

#
# PDAQuantification
#

class PDAQuantification(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "PDA Quantification"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Csaba Pinter (Pixel Medical)"]
    self.parent.helpText = """
This module makes measurements on a PDA and extracts it from a segmented cardiac vasculature.
"""
    # TODO: replace with organization, grant and thanks
    self.parent.acknowledgementText = """
This file was originally developed by Csaba Pinter (Pixel Medical).
"""

#
# PDAQuantificationWidget
#

class PDAQuantificationWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.__init__(self, parent)
    VTKObservationMixin.__init__(self)  # needed for parameter node observation
    self.logic = None
    self._parameterNode = None
    self._updatingGUIFromParameterNode = False

    self.iconsDirectoryPath = slicer.modules.pdaquantification.path.replace('PDAQuantification.py', '/Resources/Icons/')

  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    if int(slicer.app.revision) < 29787:
      # Requires fix in markups measurements (integrated on March 19, 2021)
      slicer.util.errorDisplay(f"PDA Quantification module requires Slicer core version\nSlicer-4.13.0-2021-03-20 (rev 29787) or later.",
        detailedText="In earlier Slicer versions, measurement calculation and curvature display will be unstable.")
    if not hasattr(slicer.modules, 'valveannulusanalysis'):
      slicer.util.messageBox("This modules requires the SlicerHeart extension. Install SlicerHeart and restart Slicer.")
      return ''
    if not hasattr(slicer.modules, 'extractcenterline'):
      slicer.util.messageBox("This modules requires the SlicerVMTK extension. Install SlicerVMTK and restart Slicer.")
      return ''

    # Load widget from .ui file (created by Qt Designer).
    # Additional widgets can be instantiated manually and added to self.layout.
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/PDAQuantification.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
    # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's "setMRMLScene(vtkMRMLScene*)" slot.
    uiWidget.setMRMLScene(slicer.mrmlScene)

    # Create logic class. Logic implements all computations that should be possible to run
    # in batch mode, without a graphical user interface.
    self.logic = PDAQuantificationLogic()

    # Customize widgets
    self.ui.vesselsSubjectHierarchyTreeView.setColumnHidden(self.ui.vesselsSubjectHierarchyTreeView.model().idColumn, True)
    self.ui.vesselsSubjectHierarchyTreeView.setColumnHidden(self.ui.vesselsSubjectHierarchyTreeView.model().transformColumn, True)
    self.ui.vesselsSubjectHierarchyTreeView.multiSelection = True

    self.ui.anatomyListWidget.setIconSize(qt.QSize(192, 192))
    for anatomyTypeID in self.logic.anatomyTypeIDs:
      anatomyImagePath = self.logic.getTerminologyFilePath(anatomyTypeID, 'jpg')
      if not os.path.exists(anatomyImagePath):
        anatomyImagePath = self.logic.getTerminologyFilePath(anatomyTypeID, 'png')
      imageItem = qt.QListWidgetItem(qt.QIcon(anatomyImagePath), anatomyTypeID)
      imageItem.setData(qt.Qt.UserRole, anatomyTypeID)
      self.ui.anatomyListWidget.addItem(imageItem)

    self.ui.anglesTableWidget.visible = False # Hide as long as empty
    self.ui.addAngleFromSelectionButton.enabled = False # Disable until user selects two curves
    self.ui.addPredefinedAnglesButton.visible = False # Hide until terminology type is selected
    self.ui.saveMeasurementsToCsvButton.enabled = False # Disable until measurements are available
    self.ui.copyMeasurementsToClipboardButton.enabled = False # Disable until measurements are available

    # Connections

    # These connections ensure that we update parameter node when scene is closed
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)
    # Update GUI based on scene when import ended
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndImportEvent, self.onSceneEndImport)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    self.ui.inputSegmentSelector.currentNodeChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.inputSegmentSelector.currentSegmentChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.inputEndpointsNodeComboBox.currentNodeChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.inputPDAIndicatorFiducialNodeComboBox.currentNodeChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.outputCenterlineCurveNodeComboBox.currentNodeChanged.connect(self.updateParameterNodeFromGUI)

    self.ui.anatomyListWidget.currentItemChanged.connect(self.onCurrentAnatomyTypeChanged)
    self.ui.vesselsSubjectHierarchyTreeView.currentItemChanged.connect(self.onVesselSubjectHierarchyTreeViewCurrentItemsChanged)
    self.ui.outputPDAModelNodeComboBox.currentNodeChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.outputTrimmedCurveNodeComboBox.currentNodeChanged.connect(self.updateParameterNodeFromGUI)

    # Buttons
    self.ui.applyButton.clicked.connect(self.onApplyButton)
    self.ui.addAngleFromSelectionButton.clicked.connect(self.onAddAngleFromSelectionButton)
    self.ui.addPredefinedAnglesButton.clicked.connect(self.onAddPredefinedAngles)
    self.ui.calculateButton.clicked.connect(self.onCalculateButton)
    self.ui.curvatureRadioButton.clicked.connect(self.onShowCurvatureScalarsOnPDA)
    self.ui.torsionRadioButton.clicked.connect(self.onShowTorsionScalarsOnPDA)
    self.ui.saveMeasurementsToCsvButton.clicked.connect(self.onSaveMeasurementsToCsvButton)
    self.ui.copyMeasurementsToClipboardButton.clicked.connect(self.onCopyMeasurementsToClipboardButton)

    # Load terminologies
    terminologiesLogic = slicer.modules.terminologies.logic()
    for anatomyTypeID in self.logic.anatomyTypeIDs:
      terminologyFilePath = self.logic.getTerminologyFilePath(anatomyTypeID)
      if terminologiesLogic.LoadTerminologyFromFile(terminologyFilePath) == '':
        logging.error('Failed to load terminology from file %s' % terminologyFilePath)

    # Make sure parameter node is initialized (needed for module reload)
    self.initializeParameterNode()

  def cleanup(self):
    """
    Called when the application closes and the module widget is destroyed.
    """
    self.removeObservers()

  def enter(self):
    """
    Called each time the user opens this module.
    """
    if slicer.app.majorVersion * 10 + slicer.app.minorVersion < 53:
      slicer.util.errorDisplay('To use the PDA Quantification module, Slicer 5.3 or later is needed')
      return

    # Make sure parameter node exists and observed
    self.initializeParameterNode()

  def exit(self):
    """
    Called each time the user opens a different module.
    """
    # Do not react to parameter node changes (GUI wlil be updated when the user enters into the module)
    self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

  def onSceneStartClose(self, caller, event):
    """
    Called just before the scene is closed.
    """
    # Parameter node will be reset, do not use it anymore
    self.setParameterNode(None)

  def onSceneEndClose(self, caller, event):
    """
    Called just after the scene is closed.
    """
    # If this module is shown while the scene is closed then recreate a new parameter node immediately
    if self.parent.isEntered:
      self.initializeParameterNode()

  def onSceneEndImport(self, caller, event):
    """
    Called just after a scene is imported.
    """
    if self.parent.isEntered:
      self.initializeParameterNode()

  def initializeParameterNode(self):
    """
    Ensure parameter node exists and observed.
    """
    # Parameter node stores all user choices in parameter values, node selections, etc.
    # so that when the scene is saved and reloaded, these settings are restored.

    self.setParameterNode(self.logic.getParameterNode())

    # Select default input nodes if nothing is selected yet to save a few clicks for the user
    if not self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_InputSegmentationNode):
      firstSegmentationNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")
      if firstSegmentationNode:
        self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_InputSegmentationNode, firstSegmentationNode.GetID())
    if not self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_InputEndpointsFiducials):
      firstFiducialNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLMarkupsFiducialNode")
      if firstFiducialNode:
        self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_InputEndpointsFiducials, firstFiducialNode.GetID())
    # Create default output nodes if there are no nodes of that type in the scene
    if slicer.mrmlScene.GetNumberOfNodesByClass('vtkMRMLModelNode') == 3: # The three slice models
      outputPDAModelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode')
      outputPDAModelNode.SetName(self.ui.outputPDAModelNodeComboBox.baseName)
      self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_OutputPDAModel, outputPDAModelNode.GetID())
    if slicer.mrmlScene.GetNumberOfNodesByClass('vtkMRMLMarkupsCurveNode') == 0:
      outputCenterlineCurveNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode')
      outputCenterlineCurveNode.SetName(self.ui.outputCenterlineCurveNodeComboBox.baseName)
      self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_OutputCenterlineCurve, outputCenterlineCurveNode.GetID())
      outputTrimmedPDACurveNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode')
      outputTrimmedPDACurveNode.SetName(self.ui.outputTrimmedCurveNodeComboBox.baseName)
      self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_OutputTrimmedPDACurve, outputTrimmedPDACurveNode.GetID())

  def setParameterNode(self, inputParameterNode):
    """
    Set and observe parameter node.
    Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
    """
    if inputParameterNode:
      self.logic.setDefaultParameters(inputParameterNode)

    # Unobserve previously selected parameter node and add an observer to the newly selected.
    # Changes of parameter node are observed so that whenever parameters are changed by a script or any other module
    # those are reflected immediately in the GUI.
    if self._parameterNode is not None:
      self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self._parameterNode = inputParameterNode
    if self._parameterNode is not None:
      self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    # Initial GUI update
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self, caller=None, event=None):
    """
    This method is called whenever parameter node is changed.
    The module GUI is updated to show the current state of the parameter node.
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
    self._updatingGUIFromParameterNode = True

    # Update node selectors and sliders
    self.ui.inputSegmentSelector.setCurrentNode(self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_InputSegmentationNode))
    self.ui.inputSegmentSelector.setCurrentSegmentID(self._parameterNode.GetParameter(self.logic.parameter_InputSegmentID))
    self.ui.inputEndpointsNodeComboBox.setCurrentNode(self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_InputEndpointsFiducials))
    self.ui.inputPDAIndicatorFiducialNodeComboBox.setCurrentNode(self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_InputPDAIndicatorFiducial))
    self.ui.outputCenterlineCurveNodeComboBox.setCurrentNode(self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_OutputCenterlineCurve))

    self.ui.outputPDAModelNodeComboBox.setCurrentNode(self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_OutputPDAModel))
    self.ui.outputTrimmedCurveNodeComboBox.setCurrentNode(self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_OutputTrimmedPDACurve))

    # Update anatomy type selector
    anatomyTypeSet = False
    if self.logic.parameter_AnatomyTypeID in self._parameterNode.GetParameterNames():
      anatomyTypeID = self._parameterNode.GetParameter(self.logic.parameter_AnatomyTypeID)
      for index in range(self.ui.anatomyListWidget.count):
        currentItem = self.ui.anatomyListWidget.item(index)
        itemAnatomyTypeID = currentItem.data(qt.Qt.UserRole)
        if anatomyTypeID == itemAnatomyTypeID:
          self.ui.anatomyListWidget.setCurrentItem(currentItem)
          anatomyTypeSet = True
          break
      if not anatomyTypeSet:
        logging.error('Failed to find anatomy type by ID %s' % anatomyTypeID)
    else:
      self.ui.anatomyListWidget.clearSelection()

    # Update vessel curves tree
    curveFolderItemID = self.logic.getCurveFolderItemID(self._parameterNode)
    if curveFolderItemID != 0 and anatomyTypeSet:
      self.ui.vesselsSubjectHierarchyTreeView.enabled = True
      self.ui.vesselsSubjectHierarchyTreeView.setRootItem(curveFolderItemID)
    else:
      self.ui.vesselsSubjectHierarchyTreeView.enabled = False

    # Update angles table
    self.updateAnglesTableFromParameterNode(self._parameterNode)

    # Measurements
    measurementsLabelText = self.updateMeasurementsLabel(self._parameterNode)

    # Update buttons states and tooltips
    if self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_InputSegmentationNode) and \
       self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_InputEndpointsFiducials) and \
       self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_InputPDAIndicatorFiducial) and \
       self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_OutputCenterlineCurve) and \
       self._parameterNode.GetParameter(self.logic.parameter_InputSegmentID) != '':
      self.ui.applyButton.toolTip = "Extract PDA from segmentation"
      self.ui.applyButton.enabled = True
    else:
      self.ui.applyButton.toolTip = "Select input and output"
      self.ui.applyButton.enabled = False

    pdaCurveNode = self.logic.getCurveNodeByCodeValue(self._parameterNode, self.logic.pdaCodeValue)
    if len(self.ui.anatomyListWidget.selectedItems()) and pdaCurveNode is not None:
      self.ui.calculateButton.text = "Calculate PDA metrics"
      self.ui.calculateButton.enabled = True
    else:
      self.ui.calculateButton.text = "Select anatomy type and identify vessels"
      self.ui.calculateButton.enabled = False

    if self._parameterNode.GetParameter(self.logic.parameter_ScalarArrayToShowOnPDA) == 'Curvature':
      self.ui.curvatureRadioButton.checked = True
    elif self._parameterNode.GetParameter(self.logic.parameter_ScalarArrayToShowOnPDA) == 'Torsion':
      self.ui.torsionRadioButton.checked = True

    self.ui.saveMeasurementsToCsvButton.enabled = len(measurementsLabelText) > 0
    self.ui.copyMeasurementsToClipboardButton.enabled = len(measurementsLabelText) > 0

    # All the GUI updates are done
    self._updatingGUIFromParameterNode = False

  def updateAnglesTableFromParameterNode(self, parameterNode):
    """
    Populate angles table based on parameter node content
    """
    self.ui.anglesTableWidget.clear()
    if not parameterNode:
      return

    # Get defined angle measurements
    angleMeasurementNames = self.logic.getAngleMeasurementNames(parameterNode)
    self.ui.anglesTableWidget.visible = angleMeasurementNames
    self.ui.angleInstructionLabel.visible = not angleMeasurementNames
    if not angleMeasurementNames:
      return

    # Add rows for each angle
    maximumAngleLabelWidth = 0
    self.ui.anglesTableWidget.setRowCount(len(angleMeasurementNames))
    for row, angleMeasurementName in enumerate(angleMeasurementNames):
      angleName = parameterNode.GetParameter(self.logic.getMeasurementLabelParameterName(angleMeasurementName))
      label = qt.QLabel(angleName)
      labelWidth = label.sizeHint.width()
      if labelWidth > maximumAngleLabelWidth:
        maximumAngleLabelWidth = labelWidth
      self.ui.anglesTableWidget.setCellWidget(row, 0, label)
      self.ui.anglesTableWidget.setRowHeight(row, label.sizeHint.height())

      angleValue = parameterNode.GetParameter(self.logic.getMeasurementValueParameterName(angleMeasurementName))
      item1 = qt.QTableWidgetItem('[Click calculate]' if not angleValue else angleValue)
      self.ui.anglesTableWidget.setItem(row, 1, item1)

    self.ui.anglesTableWidget.setColumnWidth(0, maximumAngleLabelWidth)

  def updateMeasurementsLabel(self, parameterNode):
    """
    Generate measurements label based on measurements stored in the parameter node
    """
    measurementsLabelText = self.logic.getMeasurementsText(parameterNode)
    self.ui.measurementsLabel.text = measurementsLabelText
    return measurementsLabelText

  def updateParameterNodeFromGUI(self, caller=None, event=None):
    """
    This method is called when the user makes any change in the GUI.
    The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

    if self.ui.inputSegmentSelector.currentNodeID():
      self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_InputSegmentationNode, self.ui.inputSegmentSelector.currentNodeID())
    if self.ui.inputSegmentSelector.currentSegmentID():
      self._parameterNode.SetParameter(self.logic.parameter_InputSegmentID, self.ui.inputSegmentSelector.currentSegmentID())
    if self.ui.inputEndpointsNodeComboBox.currentNodeID:
      self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_InputEndpointsFiducials, self.ui.inputEndpointsNodeComboBox.currentNodeID)
    if self.ui.inputPDAIndicatorFiducialNodeComboBox.currentNodeID:
      self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_InputPDAIndicatorFiducial, self.ui.inputPDAIndicatorFiducialNodeComboBox.currentNodeID)
    if self.ui.outputCenterlineCurveNodeComboBox.currentNodeID:
      self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_OutputCenterlineCurve, self.ui.outputCenterlineCurveNodeComboBox.currentNodeID)

    if self.ui.outputPDAModelNodeComboBox.currentNodeID:
      self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_OutputPDAModel, self.ui.outputPDAModelNodeComboBox.currentNodeID)
    if self.ui.outputTrimmedCurveNodeComboBox.currentNodeID:
      self._parameterNode.SetNodeReferenceID(self.logic.parameterNodeRef_OutputTrimmedPDACurve, self.ui.outputTrimmedCurveNodeComboBox.currentNodeID)

    if self.ui.curvatureRadioButton.checked:
      self._parameterNode.SetParameter(self.logic.parameter_ScalarArrayToShowOnPDA, 'Curvature')
    elif self.ui.torsionRadioButton.checked:
      self._parameterNode.SetParameter(self.logic.parameter_ScalarArrayToShowOnPDA, 'Torsion')

    self._parameterNode.EndModify(wasModified)

  def onCurrentAnatomyTypeChanged(self, currentItem, previousItem):
    """
    Set the terminology corresponding to the current anatomy and set selection in the parameter set node
    """
    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    currentAnatomyTypeID_GUI = currentItem.data(qt.Qt.UserRole)
    currentAnatomyTypeID_Scene = self._parameterNode.GetParameter(self.logic.parameter_AnatomyTypeID)
    if currentAnatomyTypeID_GUI == currentAnatomyTypeID_Scene:
      return

    # Warn user that terminology needs to be redefined if a valid selection has been changed
    curveFolderItem = self.logic.getCurveFolderItemID(self._parameterNode)
    if previousItem is not None and curveFolderItem:
      result = slicer.util.confirmYesNoDisplay('The initial anatomy type selection is about to be modified,'
        'in which case terminology will need to be re-defined for each of the curves.\n\n'
        'Are you sure you want to change anatomy type?', 'Anatomy type change')
      if not result:
        qt.QTimer.singleShot(0, lambda: self.ui.anatomyListWidget.setCurrentItem(previousItem))
        return

    logging.info('Changing to terminology for anatomy type %s' % currentAnatomyTypeID_GUI)
    self._parameterNode.SetParameter(self.logic.parameter_AnatomyTypeID, currentAnatomyTypeID_GUI)

    # Show button that adds pre-defined angles for specific anatomy types
    self.ui.addPredefinedAnglesButton.visible = (currentAnatomyTypeID_GUI != 'Other')

    # Get PDA curve node so that in case it has already been defined, the terminology can be restored
    pdaCurveNode = self.logic.getCurveNodeByCodeValue(self._parameterNode, self.logic.pdaCodeValue)

    # Set terminology for existing curves
    self.logic.setupTerminologyInCenterlineCurveTree(self._parameterNode)

    # Restore PDA terminology if PDA curve has already been identified
    if pdaCurveNode:
      self.logic.setupPDACurveTerminology(pdaCurveNode)

    # Clear defined angles
    self.logic.removeAngleMeasurements(self._parameterNode)

  def onVesselSubjectHierarchyTreeViewCurrentItemsChanged(self, currentItems):
    """
    Allow adding angle when two items are selected

    :param QList<vtkIdType> currentItems: Selected items. In Python this argument is always None (probably
      due to incorrect wrapping of this data type), so in the function we get the selection directly.
    """
    currentItemsList = vtk.vtkIdList()
    self.ui.vesselsSubjectHierarchyTreeView.currentItems(currentItemsList)

    self.ui.addAngleFromSelectionButton.enabled = (currentItemsList.GetNumberOfIds() == 2)

    # Hide angles table if empty, so that the empty table does not show up as an empty spaceholder that makes
    # the add button appear much lower
    self.ui.anglesTableWidget.visible = (self.ui.anglesTableWidget.rowCount > 0)

  def onApplyButton(self):
    """
    Extract PDA when user clicks "Apply" button.
    """
    try:
      # Prevent the user from accidentally running branch extraction on the whole vasculature
      if self._parameterNode:
        inputSegmentationNode = self._parameterNode.GetNodeReference(self.logic.parameterNodeRef_InputSegmentationNode)
        if inputSegmentationNode:
          if 'whole' in inputSegmentationNode.GetName().lower():
            message = f'Are you sure you want to run branch extraction on segmentation named {inputSegmentationNode.GetName()}?'
            if not slicer.util.confirmYesNoDisplay(message, 'Wrong input selection?'):
              return

      qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)

      # Compute output
      self.logic.extractBranches(self._parameterNode)

      qt.QApplication.restoreOverrideCursor()

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results:\n\n" + str(e))
      import traceback
      traceback.print_exc()
      qt.QApplication.restoreOverrideCursor()

  def onAddAngleFromSelectionButton(self):
    """
    Add angle entry in parameter node based on selected curves when clicking the add button
    """
    if self._parameterNode is None:
      logging.error('Failed to add angle due to invalid parameter node')
      return

    currentItemsList = vtk.vtkIdList()
    self.ui.vesselsSubjectHierarchyTreeView.currentItems(currentItemsList)
    if currentItemsList.GetNumberOfIds() != 2:
      logging.error('New angle can only be added with two curves selected in the vessels tree')
      return

    # Get curve nodes by subject hierarchy selection
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    curve1Item = currentItemsList.GetId(0)
    curve1Node = shNode.GetItemDataNode(curve1Item)
    curve2Item = currentItemsList.GetId(1)
    curve2Node = shNode.GetItemDataNode(curve2Item)

    # Add angle measurement based on selected curve nodes
    self.logic.addAngleMeasurement(self._parameterNode, curve1Node, curve2Node)

    # Make sure the new angle appears on the GUI
    self.updateAnglesTableFromParameterNode(self._parameterNode)

  def onAddPredefinedAngles(self):
    """
    Remove all angle measurements and add pre-defined angles for selected anatomy type if any
    """
    if self._parameterNode is None:
      logging.error('Failed to add pre-defined angles due to invalid parameter node')
      return

    try:
      self.logic.resetAngleMeasurementsForAnatomyType(self._parameterNode)
    except ValueError:
      slicer.util.warningDisplay('Failed to add pre-defined angles.\n\n\
Make sure the vessel terminologies are set by double-clicking its color or right-clicking the curve in the view')

  def onCalculateButton(self):
    """
    Calculate PDA metrics when user clicks "Calculate" button.
    """
    try:
      qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)

      # Compute output
      wasModified = self._parameterNode.StartModify()
      self.logic.calculateMetrics(self._parameterNode)
      self._parameterNode.EndModify(wasModified)

      qt.QApplication.restoreOverrideCursor()

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: " + str(e))
      import traceback
      traceback.print_exc()
      qt.QApplication.restoreOverrideCursor()

  def onSaveMeasurementsToCsvButton(self):
    """
    Save measurements in CSV file
    """
    measurementsTextCsv = self.logic.getMeasurementsText(self._parameterNode, 'csv')
    if measurementsTextCsv in [None, '']:
      slicer.util.errorDisplay('Failed to generate measurements for CSV export')
      return

    filter = "Comma Separated Value files (*.csv)"
    # self.setStyleSheet("QFileDialog { background-color: #909191 }")
    filePath = qt.QFileDialog.getSaveFileName(slicer.util.mainWindow(), "Save measurements to CSV", qt.QStandardPaths.writableLocation(qt.QStandardPaths.HomeLocation), filter)
    if filePath in [None, '']:
      return

    # Add file path suffix .csv if it does not exist
    if not filePath[-4:] == '.csv' and not filePath[-4:] == '.CSV':
      filePath += ".csv"

    # Write to file
    with open(filePath, "w") as csvFile:
      csvFile.write(measurementsTextCsv)

  def onCopyMeasurementsToClipboardButton(self):
    """
    Copy measurements text to clipboard
    """
    measurementsTextCsv = self.logic.getMeasurementsText(self._parameterNode, 'tsv')
    if measurementsTextCsv in [None, '']:
      slicer.util.errorDisplay('Failed to copy measurements to the clipboard')
      return

    qt.QApplication.clipboard().setText(measurementsTextCsv)

  def onShowCurvatureScalarsOnPDA(self):
    self._parameterNode.SetParameter(self.logic.parameter_ScalarArrayToShowOnPDA, 'Curvature')
    self.logic.updatePDAScalarDisplay(self._parameterNode)

  def onShowTorsionScalarsOnPDA(self):
    self._parameterNode.SetParameter(self.logic.parameter_ScalarArrayToShowOnPDA, 'Torsion')
    self.logic.updatePDAScalarDisplay(self._parameterNode)


#
# PDAQuantificationLogic
#

class PDAQuantificationLogic(ScriptedLoadableModuleLogic, VTKObservationMixin):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)
    VTKObservationMixin.__init__(self)  # needed for curve nodes observation

    # Parameter node reference roles
    self.parameterNodeRef_InputSegmentationNode = 'InputSegmentationNode'
    self.parameterNodeRef_InputEndpointsFiducials = 'InputEndpointsFiducialsNode'
    self.parameterNodeRef_InputPDAIndicatorFiducial = 'InputPDAIndicatorFiducialNode'
    self.parameterNodeRef_OutputCenterlineModel1 = 'OutputCenterlineModel1'
    self.parameterNodeRef_OutputCenterlineModel2 = 'OutputCenterlineModel2'
    self.parameterNodeRef_OutputCenterlineCurve = 'OutputCenterlineCurve'
    self.parameterNodeRef_OutputSecondTempBranchCenterlineCurve = 'OutputSecondTempBranchCenterlineCurve'
    self.parameterNodeRef_OutputBranchesModel1 = 'OutputBranchesModel1'
    self.parameterNodeRef_OutputBranchesModel2 = 'OutputBranchesModel2'
    self.parameterNodeRef_OutputPDAModel = 'OutputPDAModel'
    self.parameterNodeRef_OutputTrimmedPDACurve = 'OutputTrimmedPDACurve'
    self.parameterNodeRef_OutputClippedPDABranchModel = 'OutputClippedPDABranchModel'
    self.parameterNodeRefPrefix_OutputAngle = 'OutputAngle_'
    # Parameter node parameter names
    self.parameter_InputSegmentID = 'InputSegment'
    self.parameter_AnatomyTypeID = 'AnatomyTypeID'
    self.parameter_ScalarArrayToShowOnPDA = 'ScalarArrayToShowOnPDA'
    # Measurements
    self.measurementParameterPrefix = 'Measurement_'
    self.measurementParameterValuePostfix = '_Value'
    self.measurementParameterLabelPostfix = '_Label'
    self.angleMeasurementNamePrefix = 'Angle-'
    self.angleMeasurementParameter_Curve1Prefix = 'Curve1CodeValue_'
    self.angleMeasurementParameter_Curve2Prefix = 'Curve2CodeValue_'

    # Constants
    self.blankingArrayName = 'Blanking'
    self.radiusArrayName = 'Radius'  # maximum inscribed sphere radius
    self.groupIdsArrayName = 'GroupIds'
    self.firstInputPDAGroupIdAttribute = 'GroupId1'
    self.secondInputPDAGroupIdAttribute = 'GroupId2'
    self.centerlineIdsArrayName = 'CenterlineIds'
    self.tractIdsArrayName = 'TractIds'
    self.centerlineCurveFolderName = 'Centerline curves'
    self.pdaCodeValue = 'sh-pda-pda'
    self.pdaCodeMeaning = 'PDA'
    self.distalTransverseAortaCodeValue = 'sh-pda-a-distal-transverse-aorta'
    self.proximalTransverseAortaCodeValue = 'sh-pda-a-proximal-transverse-aorta'
    self.transverseAortaCodeValue = 'sh-pda-b-transverse-aorta'
    self.descendingAortaCodeValue = 'sh-pda-descending-aorta'
    self.ascendingAortaCodeValue = 'sh-pda-ascending-aorta'
    self.proximalLpaCodeValue = 'sh-pda-proximal-lpa'
    self.rpaCodeValue = 'sh-pda-rpa'
    # Terminologies
    self.anatomyTypeIDs = ['A', 'B', 'C', 'Other']
    self.terminologyCodingSchemeDesignator = 'SlicerHeart'
    self.terminologyNames = {'A':'SlicerHeart PDA vessels anatomy type A category and type', \
      'B':'SlicerHeart PDA vessels anatomy type B category and type', \
      'C':'SlicerHeart PDA vessels anatomy type C category and type', \
      'Other':'SlicerHeart PDA vessels generic anatomy category and type' }
    self.terminologyCategoryCodeValues = {'A':'85756008', \
      'B':'85756009', 'C':'85756010', 'Other':'85756011'}
    self.terminologyCategoryCodeMeanings = {'A':'PDA adjacent vessels (A - Normal)', \
      'B':'PDA adjacent vessels (B - Common brachiobicephalic trunk)', \
      'C':'PDA adjacent vessels (C - Right aortic arch)', \
      'Other':'PDA adjacent vessels (Other - Generic terminology)' }

  def setDefaultParameters(self, parameterNode):
    """
    Initialize parameter node with default settings.
    """
    if not parameterNode.GetParameter(self.parameter_InputSegmentID):
      parameterNode.SetParameter(self.parameter_InputSegmentID, '')
    if not parameterNode.GetParameter(self.parameter_ScalarArrayToShowOnPDA):
      parameterNode.SetParameter(self.parameter_ScalarArrayToShowOnPDA, 'Curvature')

  def getTerminologyFilePath(self, anatomyID, extension='json'):
    """
    Get path to terminology file
    :param string anatomyID: A or B (defined in PDAQuantificationLogic.anatomyTypeIDs)
    :param string extension: Extension of the terminology file (JSON or JPG)
    :
    """
    valveAnnulusAnalysisModuleDir = os.path.dirname(slicer.modules.valveannulusanalysis.path)
    if anatomyID == 'A':
      terminologyFile = os.path.join(valveAnnulusAnalysisModuleDir, 'Resources', 'SlicerHeartPDAVesselsCategoryTypeModifier_A_Normal.' + extension)
    elif anatomyID == 'B':
      terminologyFile = os.path.join(valveAnnulusAnalysisModuleDir, 'Resources', 'SlicerHeartPDAVesselsCategoryTypeModifier_B_CommonBrachioBicephalicTrunk.' + extension)
    elif anatomyID == 'C':
      terminologyFile = os.path.join(valveAnnulusAnalysisModuleDir, 'Resources', 'SlicerHeartPDAVesselsCategoryTypeModifier_C_RightAorticArch.' + extension)
    elif anatomyID == 'Other':
      terminologyFile = os.path.join(valveAnnulusAnalysisModuleDir, 'Resources', 'SlicerHeartPDAVesselsCategoryTypeModifier_Other.' + extension)
    else:
      logging.error('Invalid anatomy ID %s given. Only acceptable values: %s' % (anatomyID, self.anatomyTypeIDs))
      return None

    return terminologyFile

  def getReferencedNode(self, parameterNode, referenceRole, nodeClass, nodeName=None):
    """
    Get a given referenced node, create it if does not exist

    :param vtkMRMLScriptedModuleNode parameterNode: Parameter node
    :param string referenceRole: The reference role (which also serves as name if not given) for the referenced node
    :param string nodeClass: Node class string for the referenced node in case it needs to be created
      (e.g. for landmarks it is 'vtkMRMLMarkupsFiducialNode')
    :param string nodeName: Name of the new node if need to be created. If None then the reference role will be set as name
    :return: Referenced node
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")

    nodeID = parameterNode.GetNodeReferenceID(referenceRole)
    if nodeID not in [None, '']:
      # Node is found, return it
      node = slicer.mrmlScene.GetNodeByID(nodeID)
      return node

    # Create node if does not exist yet and if name is provided
    node = slicer.mrmlScene.AddNewNodeByClass(nodeClass)
    node.SetName(nodeName if nodeName else referenceRole)
    parameterNode.SetAndObserveNodeReferenceID(referenceRole, node.GetID())

    return node

  def getMeasurementValueParameterName(self, measurementName):
    """
    Get parameter name containing a value for a measurement
    :param string measurementName: Name of the measurement (e.g. PDALength)
    :return string: Name of the value parameter that can be used to get the value from the parameter node
    """
    if not measurementName or ' ' in measurementName or '_' in measurementName:
      logging.error('Invalid measurement name %s' % measurementName)
      return None
    return self.measurementParameterPrefix + measurementName + self.measurementParameterValuePostfix

  def getMeasurementLabelParameterName(self, measurementName):
    """
    Get parameter name containing a human readable name for a measurement
    :param string measurementName: Name of the measurement (e.g. PDALength)
    :return string: Name of the label parameter that can be used to get the label from the parameter node
    """
    if not measurementName or ' ' in measurementName or '_' in measurementName:
      logging.error('Invalid measurement name %s' % measurementName)
      return None
    return self.measurementParameterPrefix + measurementName + self.measurementParameterLabelPostfix

  def getAngleMeasurementNames(self, parameterNode):
    """
    Get angle measurement names that have a defined value. Also check if they have their code values defined.
    The parameter names need to be accessed via getMeasurementValueParameterName and getMeasurementLabelParameterName.
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    # Get defined angle measurements
    parameterNames = parameterNode.GetParameterNames()
    angleMeasurementNames = []
    for parameterName in parameterNames:
      if not parameterName.startswith(self.measurementParameterPrefix) or not parameterName.endswith(self.measurementParameterValuePostfix):
        continue
      measurementName = parameterName.split('_')[1]
      if not measurementName.startswith(self.angleMeasurementNamePrefix):
        continue
      if self.angleMeasurementParameter_Curve1Prefix + measurementName not in parameterNames or \
         self.angleMeasurementParameter_Curve2Prefix + measurementName not in parameterNames:
         logging.error('No curve terminology is defined for angle measurement %s' % measurementName)
         continue
      angleMeasurementNames.append(measurementName)
    return angleMeasurementNames

  def getMaxAngleId(self, parameterNode):
    """
    Get largest angle ID number.
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    maxAngleId = -1
    angleMeasurementNames = self.getAngleMeasurementNames(parameterNode)
    for measurementName in angleMeasurementNames:
      try:
        angleId = int(measurementName[len(self.angleMeasurementNamePrefix):])
        if angleId > maxAngleId:
          maxAngleId = angleId
      except ValueError:
        logging.error('Cannot parse angle ID from angle measurement %s' % measurementName)
        continue
    return maxAngleId

  def getUnselectedControlPointIndicesFromMarkupsFiducial(self, markupsFiducialNode):
    """
    Get index of unselected control points of a given markups fiducial as a list of integers
    """
    if not markupsFiducialNode:
      return []

    unselectedControlPointIndices = []
    for i in range(markupsFiducialNode.GetNumberOfControlPoints()):
      if not markupsFiducialNode.GetNthControlPointSelected(i):
        unselectedControlPointIndices.append(i)

    return unselectedControlPointIndices

  def extractBranches(self, parameterNode):
    """
    Extract branches from PDA segmentation
    """
    # Get and check input
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    inputSegmentationNode = parameterNode.GetNodeReference(self.parameterNodeRef_InputSegmentationNode)
    inputSegmentID = parameterNode.GetParameter(self.parameter_InputSegmentID)
    inputEndpointsFiducialsNode = parameterNode.GetNodeReference(self.parameterNodeRef_InputEndpointsFiducials)
    outputCenterlineCurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputCenterlineCurve)
    if not inputSegmentationNode:
      raise ValueError("Input segmentation not selected")
    if inputSegmentID == '':
      raise ValueError("Input segment ID not specified")
    if not inputEndpointsFiducialsNode:
      raise ValueError("Input endpoint fiducials not selected")
    if not outputCenterlineCurveNode:
      raise ValueError("Output centerline curve not selected")

    # Make sure two points are selected as endpoints
    # (technically these are the unselected points because selected state is default and when user toggles they are unselected)
    sourceEndpointIndices = self.getUnselectedControlPointIndicesFromMarkupsFiducial(inputEndpointsFiducialsNode)
    if len(sourceEndpointIndices) != 2:
      raise ValueError("Need to select exactly two endpoints in input endpoints fiducial markups node")

    # Measure time
    import time
    startTime = time.time()
    logging.info('Extracting branches started')

    # Do branch extraction with one endpoint first
    outputCenterlineModelNode1 = self.getReferencedNode(parameterNode, self.parameterNodeRef_OutputCenterlineModel1, 'vtkMRMLModelNode')
    outputBranchesModelNode1 = self.getReferencedNode(parameterNode, self.parameterNodeRef_OutputBranchesModel1, 'vtkMRMLModelNode')
    self.extractBranchesWithEndpoint(parameterNode, inputSegmentationNode, inputSegmentID, inputEndpointsFiducialsNode, sourceEndpointIndices[0],
      outputCenterlineModelNode1, outputCenterlineCurveNode, outputBranchesModelNode1)

    # Create second centerline curve node and run extaction from second endpoint
    tempSecondCenterlineCurveNode = self.getReferencedNode(parameterNode, self.parameterNodeRef_OutputSecondTempBranchCenterlineCurve, 'vtkMRMLMarkupsCurveNode')
    outputCenterlineModelNode2 = self.getReferencedNode(parameterNode, self.parameterNodeRef_OutputCenterlineModel2, 'vtkMRMLModelNode')
    outputBranchesModelNode2 = self.getReferencedNode(parameterNode, self.parameterNodeRef_OutputBranchesModel2, 'vtkMRMLModelNode')
    self.extractBranchesWithEndpoint(parameterNode, inputSegmentationNode, inputSegmentID, inputEndpointsFiducialsNode, sourceEndpointIndices[1],
      outputCenterlineModelNode2, tempSecondCenterlineCurveNode, outputBranchesModelNode2)

    # Make sure centerline curve trees have a root folder before merging
    self.getCenterlineCurveTreeFolderForRootCurve(outputCenterlineCurveNode)
    self.getCenterlineCurveTreeFolderForRootCurve(tempSecondCenterlineCurveNode)

    # Cut and stitch tree halves
    self.mergeCenterlineCurveTrees(parameterNode)

    # Report time
    stopTime = time.time()
    logging.info('Extracting branches completed in {0:.2f} seconds'.format(stopTime-startTime))

  def extractBranchesWithEndpoint(self, parameterNode, inputSegmentationNode, inputSegmentID, inputEndpointsFiducialsNode,
      sourceEndpointIndex, outputCenterlineModelNode, outputCenterlineCurveNode, outputBranchesModelNode):
    """
    Single run of branch extraction starting from an endpoint specified with control point index
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    import vtkvmtkComputationalGeometryPython as vtkvmtkComputationalGeometry

    surfacePolyData = inputSegmentationNode.GetClosedSurfaceInternalRepresentation(inputSegmentID)
    endPointsMarkupsNode = inputEndpointsFiducialsNode # To be able to keep the below copy-pasted snippet intact

    # Expand `centerlinePolyData, voronoiDiagramPolyData = self.logic.extractCenterline(preprocessedPolyData, endPointsMarkupsNode)` (ExtractCenterline.py)

    numberOfControlPoints = endPointsMarkupsNode.GetNumberOfControlPoints()
    sourceIdList = vtk.vtkIdList()
    targetIdList = vtk.vtkIdList()

    pointLocator = vtk.vtkPointLocator()
    pointLocator.SetDataSet(surfacePolyData)
    pointLocator.BuildLocator()

    pos = [0.0, 0.0, 0.0]
    for controlPointIndex in range(numberOfControlPoints):
      endPointsMarkupsNode.GetNthControlPointPosition(controlPointIndex, pos)
      # locate the point on the surface
      pointId = pointLocator.FindClosestPoint(pos)
      if controlPointIndex != sourceEndpointIndex:
        targetIdList.InsertNextId(pointId)
      else:
        sourceIdList.InsertNextId(pointId)

    if sourceIdList.GetNumberOfIds() == 0:
      raise ValueError('Failed to find source endpoint for centerline extraction')

    centerlineFilter = vtkvmtkComputationalGeometry.vtkvmtkPolyDataCenterlines()
    centerlineFilter.SetInputData(surfacePolyData)
    centerlineFilter.SetSourceSeedIds(sourceIdList)
    centerlineFilter.SetTargetSeedIds(targetIdList)
    centerlineFilter.SetRadiusArrayName(self.radiusArrayName)
    centerlineFilter.SetCostFunction('1/R')  # this makes path search prefer go through points with large radius
    centerlineFilter.SetFlipNormals(False)
    centerlineFilter.SetAppendEndPointsToCenterlines(0)
    centerlineFilter.SetSimplifyVoronoi(0)  # this slightly improves connectivity #TODO: Needed to be disabled due this feature not being supported in VTK9
    centerlineFilter.SetCenterlineResampling(0)
    centerlineFilter.SetResamplingStepLength(1.0)
    centerlineFilter.Update()

    centerlinePolyData = vtk.vtkPolyData()
    centerlinePolyData.DeepCopy(centerlineFilter.GetOutput())
    outputCenterlineModelNode.SetAndObservePolyData(centerlinePolyData)
    outputCenterlineModelNode.CreateDefaultDisplayNodes()
    outputCenterlineModelNode.GetDisplayNode().SetColor(0.0, 1.0, 0.0)
    outputCenterlineModelNode.GetDisplayNode().SetLineWidth(3)
    outputCenterlineModelNode.SetDisplayVisibility(False) # Hide it so that the user can focus on the curves
    inputSegmentationNode.GetDisplayNode().SetOpacity(0.4)

    # Expand self.logic.createCurveTreeFromCenterline(centerlinePolyData, centerlineCurveNode, centerlinePropertiesTableNode) (ExtractCenterline.py)

    branchExtractor = vtkvmtkComputationalGeometry.vtkvmtkCenterlineBranchExtractor()
    branchExtractor.SetInputData(centerlinePolyData)
    branchExtractor.SetBlankingArrayName(self.blankingArrayName)
    branchExtractor.SetRadiusArrayName(self.radiusArrayName)
    branchExtractor.SetGroupIdsArrayName(self.groupIdsArrayName)
    branchExtractor.SetCenterlineIdsArrayName(self.centerlineIdsArrayName)
    branchExtractor.SetTractIdsArrayName(self.tractIdsArrayName)
    branchExtractor.Update()
    centerlines = branchExtractor.GetOutput()

    mergeCenterlines = vtkvmtkComputationalGeometry.vtkvmtkMergeCenterlines()
    mergeCenterlines.SetInputData(centerlines)
    mergeCenterlines.SetRadiusArrayName(self.radiusArrayName)
    mergeCenterlines.SetGroupIdsArrayName(self.groupIdsArrayName)
    mergeCenterlines.SetCenterlineIdsArrayName(self.centerlineIdsArrayName)
    mergeCenterlines.SetTractIdsArrayName(self.tractIdsArrayName)
    mergeCenterlines.SetBlankingArrayName(self.blankingArrayName)
    mergeCenterlines.SetResamplingStepLength(1.0)
    mergeCenterlines.SetMergeBlanked(True)
    mergeCenterlines.Update()
    mergedCenterlines = mergeCenterlines.GetOutput()

    #
    # Create branch curves tree
    #
    try:
      extractCenterlineLogic = slicer.modules.extractcenterline.widgetRepresentation().self().logic
      extractCenterlineLogic.addCenterlineCurves(mergedCenterlines, outputCenterlineCurveNode)
    except:
      logging.error('Failed to create branch curves tree')

    #
    # Show branch model as points
    #
    outputBranchesModelNode.SetAndObservePolyData(mergedCenterlines)
    if False: # Disabled, can enable for debugging by changing False to True
      outputBranchesModelNode.CreateDefaultDisplayNodes()
      outputBranchesModelDisplayNode = outputBranchesModelNode.GetDisplayNode()
      outputBranchesModelDisplayNode.SetRepresentation(slicer.vtkMRMLDisplayNode.PointsRepresentation)
      outputBranchesModelDisplayNode.SetPointSize(6)
      outputBranchesModelDisplayNode.SetAmbient(0.5)
      outputBranchesModelDisplayNode.SetScalarRangeFlag(slicer.vtkMRMLDisplayNode.UseColorNodeScalarRange)
      outputBranchesModelDisplayNode.SetActiveScalarName('GroupIds')
      outputBranchesModelDisplayNode.SetActiveAttributeLocation(vtk.vtkAssignAttribute.CELL_DATA)
      outputBranchesModelDisplayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeRandom')
      outputBranchesModelDisplayNode.SetScalarVisibility(1)

  def mergeCenterlineCurveTrees(self, parameterNode):
    """
    Cut and stitch two centerline curve tree halves
    """
    # Get and check input
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    inputEndpointsFiducialsNode = parameterNode.GetNodeReference(self.parameterNodeRef_InputEndpointsFiducials)
    inputPDAIndicatorFiducialNode = parameterNode.GetNodeReference(self.parameterNodeRef_InputPDAIndicatorFiducial)
    outputCenterlineCurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputCenterlineCurve)
    outputCenterlineModelNode1 = parameterNode.GetNodeReference(self.parameterNodeRef_OutputCenterlineModel1)
    outputBranchesModelNode1 = parameterNode.GetNodeReference(self.parameterNodeRef_OutputBranchesModel1)
    tempSecondCenterlineCurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputSecondTempBranchCenterlineCurve)
    outputCenterlineModelNode2 = parameterNode.GetNodeReference(self.parameterNodeRef_OutputCenterlineModel2)
    outputBranchesModelNode2 = parameterNode.GetNodeReference(self.parameterNodeRef_OutputBranchesModel2)
    if not inputEndpointsFiducialsNode:
      raise ValueError("Input endpoint fiducials not selected")
    if not inputPDAIndicatorFiducialNode or inputPDAIndicatorFiducialNode.GetNumberOfControlPoints() < 1:
      raise ValueError("Input PDA indicator point not selected")
    if not outputCenterlineCurveNode:
      raise ValueError("Output centerline curve not selected")
    if not outputCenterlineModelNode1 or not outputBranchesModelNode1 or not tempSecondCenterlineCurveNode \
       or not outputCenterlineModelNode2 or not outputBranchesModelNode2:
      raise ValueError("Some of the intermediate output nodes failed to be created")

    tempSecondTreeFolderItem = self.getCenterlineCurveTreeFolderForRootCurve(tempSecondCenterlineCurveNode)

    #
    # Stitch the two PDA curves in the middle
    #

    # Identify PDA curve in both trees
    def getClosestPointInCurve(curve, position):
      pointIndex = curve.GetClosestControlPointIndexToPositionWorld(position)
      closestPointPos = np.zeros(3)
      curve.GetNthControlPointPosition(pointIndex, closestPointPos)
      distance = np.linalg.norm(position-closestPointPos)
      return [pointIndex, distance]

    def findClosestCurvePoint(rootCurve, pointPos):
      treeFolderItem = self.getCenterlineCurveTreeFolderForRootCurve(rootCurve)
      treeCurveItems = vtk.vtkIdList()
      shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
      shNode.GetItemChildren(treeFolderItem, treeCurveItems, True)
      distances = [0.0] * treeCurveItems.GetNumberOfIds()
      pointIndices = [0] * treeCurveItems.GetNumberOfIds()
      for i in range(treeCurveItems.GetNumberOfIds()):
        curveItem = treeCurveItems.GetId(i)
        curveNode = shNode.GetItemDataNode(curveItem)
        [pointIndex, distance] = getClosestPointInCurve(curveNode, pointPos)
        distances[i] = distance
        pointIndices[i] = pointIndex
      minDistanceCurveIndex = distances.index(min(distances))
      minDistancePointIndex = pointIndices[minDistanceCurveIndex]
      minDistanceCurveNode = shNode.GetItemDataNode(treeCurveItems.GetId(minDistanceCurveIndex))
      return [minDistanceCurveNode, minDistancePointIndex]

    pdaIndicatorPointPos = np.zeros(3)
    inputPDAIndicatorFiducialNode.GetNthControlPointPosition(0, pdaIndicatorPointPos)

    # Find midpoint of first PDA curve (closest to the PDA indicator point)
    [firstPdaCurveNode, firstPdaCurveMidPointIndex] = \
      findClosestCurvePoint(outputCenterlineCurveNode, pdaIndicatorPointPos)
    if not firstPdaCurveNode:
      raise ValueError('Failed to find PDA curve based on indicator point in output centerline curve tree')
    firstPdaCurveMidPointPos = np.zeros(3)
    firstPdaCurveNode.GetNthControlPointPosition(firstPdaCurveMidPointIndex, firstPdaCurveMidPointPos)

    # Find midpoint in second PDA (closest to the midpoint found in the first PDA)
    [secondPdaCurveNode, secondPdaCurveMidPointIndex] = \
      findClosestCurvePoint(tempSecondCenterlineCurveNode, firstPdaCurveMidPointPos)
    if not secondPdaCurveNode:
      raise ValueError('Failed to find PDA curve based on first PDA mid-point (%s) in second temporary centerline curve tree' % str(firstPdaCurveMidPointPos))

    # Make sure the midpoint defined this way in the second PDA is not "going backwards"
    firstPdaMidPointPrevPos = np.zeros(3)
    firstPdaCurveNode.GetNthControlPointPosition(firstPdaCurveMidPointIndex-1, firstPdaMidPointPrevPos)
    firstPdaForwardsVector = firstPdaMidPointPrevPos - firstPdaCurveMidPointPos  # Vector point from the point before the identified midpoint to the midpoint in the first curve
    secondPdaMidPointPos = np.zeros(3)
    secondPdaCurveNode.GetNthControlPointPosition(secondPdaCurveMidPointIndex, secondPdaMidPointPos)
    firstMidPointToSecondMidPointVector = firstPdaCurveMidPointPos - secondPdaMidPointPos
    if np.dot(firstPdaForwardsVector, firstMidPointToSecondMidPointVector) < 0:
      # If the midpoint found in the second PDA "goes backwards", then use the previous point on the second PDA curve (the previous
      # because the second PDA is going in the opposite direction as the first)
      secondPdaCurveMidPointIndex = secondPdaCurveMidPointIndex-1

    # Construct stiched PDA from the points and lines of both sides and a new line between the points of stitching
    stitchedPdaCurveNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode')
    for pointIndex in range(firstPdaCurveMidPointIndex + 1):
      stitchedPdaCurveNode.AddControlPointWorld(vtk.vtkVector3d(
        firstPdaCurveNode.GetCurveWorld().GetPoint(pointIndex)))
    for pointIndex in range(secondPdaCurveMidPointIndex + 1):
      stitchedPdaCurveNode.AddControlPointWorld(vtk.vtkVector3d(
        secondPdaCurveNode.GetCurveWorld().GetPoint(secondPdaCurveMidPointIndex - pointIndex)))

    # Save group ID for the two original PDA curves in the stitched PDA curve to be able to extract PDA model from both input trees
    firstPDAGroupIdAttribute = firstPdaCurveNode.GetAttribute('GroupId')
    secondPDAGroupIdAttribute = secondPdaCurveNode.GetAttribute('GroupId')
    stitchedPdaCurveNode.SetAttribute(self.firstInputPDAGroupIdAttribute, firstPDAGroupIdAttribute)
    stitchedPdaCurveNode.SetAttribute(self.secondInputPDAGroupIdAttribute, secondPDAGroupIdAttribute)

    #
    # Construct complete tree
    #
    # Collect curves from both trees that are not the children of the PDA.
    # The children curve nodes of the PDA are those that are distal to the PDA looking from the endpoint.
    # So if we include these curves and the stiched PDA in the merged tree, then it will contain all the
    # proximal halves of the tree to the two endpoints.
    #

    # Remove PDA curve and its children from the first (output) tree, leaving the rest of the tree intact
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    firstPdaCurveItem = shNode.GetItemByDataNode(firstPdaCurveNode)
    firstPdaParentItem = shNode.GetItemParent(firstPdaCurveItem)
    shNode.RemoveItem(firstPdaCurveItem)

    # Add stiched PDA
    stitchedPdaCurveItem = shNode.GetItemByDataNode(stitchedPdaCurveNode)
    shNode.SetItemParent(stitchedPdaCurveItem, firstPdaParentItem)

    # Add curves recursively. We start with curve A being the stitched PDA in the output tree,
    # and curve B the PDA of the second (temporary) tree.
    # 1. If parent of curve B is the folder item, stop
    # 2. Add siblings of curve B as children to the curve A
    # 3. Add parent of curve B as child to curve A
    # 4. Parent curve of B becomes the new curve A in the output tree and curve B (now non-existent there) in the second tree
    def getParentAndSiblings(item):
      parent = shNode.GetItemParent(item)
      siblings = []
      siblingsIdList = vtk.vtkIdList()
      shNode.GetItemChildren(parent, siblingsIdList, False)
      for i in range(siblingsIdList.GetNumberOfIds()):
        currentSibling = siblingsIdList.GetId(i)
        if currentSibling != item:
          siblings.append(currentSibling)
      return parent, siblings

    curveA = stitchedPdaCurveItem
    curveB = shNode.GetItemByDataNode(secondPdaCurveNode)
    curveBParent, curveBSiblings = getParentAndSiblings(curveB)
    shNode.RemoveItem(curveB) # Remove PDA curve and its children from the second (temporary) tree

    while not shNode.IsItemLevel(curveBParent, slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder()):
      # Determine parent and siblings for the next iteration before doing the reparenting of the next curve B
      nextCurveBParent, nextCurveBSiblings = getParentAndSiblings(curveBParent)
      # Move siblings to output tree
      for sibling in curveBSiblings:
        shNode.SetItemParent(sibling, curveA)
      # Move parent to output tree
      shNode.SetItemParent(curveBParent, curveA)
      # Set new curves of interest
      curveA = curveBParent
      curveBParent = nextCurveBParent
      curveBSiblings = nextCurveBSiblings

    # Remove the now empty root folder item of the second temporary tree
    shNode.RemoveItem(tempSecondTreeFolderItem)

    # Setup output curve tree (display and terminology)
    self.setupCenterlineCurveTree(parameterNode)

    # Set terminology for stitched PDA curve
    self.setupPDACurveTerminology(stitchedPdaCurveNode)

  def setupCenterlineCurveTree(self, parameterNode, curveReference=None):
    """
    Setup centerline curve visualization and add them to a subject hierarchy folder for easy show/hide.

    :param curveReference: Reference role of the curve whose tree is to be set up. If left as default, then
      the default is parameterNodeRef_OutputCenterlineCurve. Used for debugging of the temporary second tree.
    """
    # Get and check input
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    if not curveReference:
      curveReference = self.parameterNodeRef_OutputCenterlineCurve
    outputCenterlineCurveNode = parameterNode.GetNodeReference(curveReference)
    if not outputCenterlineCurveNode:
      raise ValueError("Output centerine curve is not selected")

    # Make sure centerline curves are in a folder for easy show/hide of all
    curveFolderItem = self.getCenterlineCurveTreeFolderForRootCurve(outputCenterlineCurveNode)

    # Individual setup of each curve
    childCurveItems = vtk.vtkIdList()
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    shNode.GetItemChildren(curveFolderItem, childCurveItems, True)
    for i in range(childCurveItems.GetNumberOfIds()):
      curveItem = childCurveItems.GetId(i)
      curveNode = shNode.GetItemDataNode(curveItem)

      # Increase line thickness for all the curves and set name and color to auto-generated
      curveNode.GetDisplayNode().SetLineThickness(0.5)
      curveNode.GetDisplayNode().SetTextScale(2.75)

      # Workaround because if all control point visibilities are false then the "properties label" is not shown although its visibility is on
      curveNode.SetNthControlPointVisibility(0, True)

      # Observe modified event so that GUI is updated when terminology is set
      if not self.hasObserver(curveNode, vtk.vtkCommand.ModifiedEvent, lambda c, e: parameterNode.Modified()):
        self.addObserver(curveNode, vtk.vtkCommand.ModifiedEvent, lambda c, e: parameterNode.Modified())

    self.setupTerminologyInCenterlineCurveTree(parameterNode)

    # Trigger GUI update
    parameterNode.Modified()

  def getCenterlineCurveTreeFolderForRootCurve(self, rootCurveNode):
    """
    Get folder containing a centerline curve tree
    :param rootCurveNode: The root node of the centerline curve tree (i.e. the output centerline given on the UI)
    :return int: The folder item found or if not, then created for the centerline curve tree
    """
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    rootCurveItem = shNode.GetItemByDataNode(rootCurveNode)
    parentItem = shNode.GetItemParent(rootCurveItem)
    if shNode.GetItemOwnerPluginName(parentItem) != 'Folder' or shNode.GetItemName(parentItem) != self.centerlineCurveFolderName:
      curveFolderItem = shNode.CreateFolderItem(parentItem, self.centerlineCurveFolderName)
      shNode.SetItemParent(rootCurveItem, curveFolderItem)
    else:
      curveFolderItem = parentItem
    return curveFolderItem

  def setupTerminologyInCenterlineCurveTree(self, parameterNode):
    """
    Set current terminology for centerline curves
    """
    # Get and check input
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    if not self.parameter_AnatomyTypeID in parameterNode.GetParameterNames():
      # Terminology not selected yet, nothing to set up
      return
    outputCenterlineCurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputCenterlineCurve)
    curveFolderItem = self.getCurveFolderItemID(parameterNode)
    if not outputCenterlineCurveNode or curveFolderItem == 0:
      # Centerline curves not generated yet, cannot set them up
      return

    terminologiesLogic = slicer.modules.terminologies.logic()
    currentAnatomyTypeID = parameterNode.GetParameter(self.parameter_AnatomyTypeID)

    # Set current terminology to all the curves
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    childCurveItems = vtk.vtkIdList()
    shNode.GetItemChildren(curveFolderItem, childCurveItems, True)
    for i in range(childCurveItems.GetNumberOfIds()):
      curveItem = childCurveItems.GetId(i)
      curveNode = shNode.GetItemDataNode(curveItem)
      if not curveNode.GetName().startswith('Centerline curve'):
        # Reset name if terminology has been changed
        curveNode.SetName('Centerline curve (?)')

      terminologyEntry = slicer.vtkSlicerTerminologyEntry()
      terminologyEntry.SetTerminologyContextName(self.terminologyNames[currentAnatomyTypeID])
      terminologyEntry.GetCategoryObject().SetCodingSchemeDesignator(self.terminologyCodingSchemeDesignator)
      terminologyEntry.GetCategoryObject().SetCodeValue(self.terminologyCategoryCodeValues[currentAnatomyTypeID])
      terminologyEntry.GetCategoryObject().SetCodeMeaning(self.terminologyCategoryCodeMeanings[currentAnatomyTypeID])
      terminologyEntryStr = terminologiesLogic.SerializeTerminologyEntry(terminologyEntry)
      curveNode.SetAttribute('Terminologies.AutoUpdateNodeName', 'true')
      curveNode.SetAttribute('Terminologies.AutoUpdateNodeColor', 'true')
      curveNode.SetAttribute('TerminologyEntry', terminologyEntryStr)

  def setupPDACurveTerminology(self, pdaCurveNode):
    """
    Set PDA terminology to given curve node
    """
    pdaTerminologyEntryStr = pdaCurveNode.GetAttribute('TerminologyEntry')

    terminologiesLogic = slicer.modules.terminologies.logic()
    pdaTerminologyEntry = slicer.vtkSlicerTerminologyEntry()
    if pdaTerminologyEntryStr not in ['', None]:
      terminologiesLogic.DeserializeTerminologyEntry(pdaTerminologyEntryStr, pdaTerminologyEntry)

    pdaTerminologyEntry.GetTypeObject().SetCodingSchemeDesignator(self.terminologyCodingSchemeDesignator)
    pdaTerminologyEntry.GetTypeObject().SetCodeValue(self.pdaCodeValue) # Same in all anatomy types
    pdaTerminologyEntry.GetTypeObject().SetCodeMeaning(self.pdaCodeMeaning)

    pdaTerminologyEntryStr = terminologiesLogic.SerializeTerminologyEntry(pdaTerminologyEntry)
    pdaCurveNode.SetAttribute('TerminologyEntry', pdaTerminologyEntryStr)
    pdaCurveNode.SetName(self.pdaCodeMeaning)

  def getCurveFolderItemID(self, parameterNode):
    """
    Get subject hierarchy item ID of the folder that contains the centerline curves
    """
    if not parameterNode:
      return 0

    centerlineCurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputCenterlineCurve)
    if not centerlineCurveNode:
      return 0

    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    centerlineCurveItemID = shNode.GetItemByDataNode(centerlineCurveNode)
    centerlineParentItem = shNode.GetItemParent(centerlineCurveItemID)
    if not shNode.IsItemLevel(centerlineParentItem, 'Folder'):
      return 0

    return centerlineParentItem

  def getCurveNodeByCodeValue(self, parameterNode, codeValue):
    """
    Get tree curve node by terminology code value

    :return int: SH item ID corresponding to the code value, 0 if not found
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")

    curveFolderItem = self.getCurveFolderItemID(parameterNode)
    if curveFolderItem == 0:
      return None

    childCurveItems = vtk.vtkIdList()
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    shNode.GetItemChildren(curveFolderItem, childCurveItems, True)

    terminologiesLogic = slicer.modules.terminologies.logic()
    import vtkSlicerTerminologiesModuleLogicPython
    terminologyEntry = vtkSlicerTerminologiesModuleLogicPython.vtkSlicerTerminologyEntry()

    for i in range(childCurveItems.GetNumberOfIds()):
      curveItem = childCurveItems.GetId(i)
      curveNode = shNode.GetItemDataNode(curveItem)
      if not curveNode:
        continue

      terminologyString = curveNode.GetAttribute('TerminologyEntry')
      if terminologyString:
        terminologiesLogic.DeserializeTerminologyEntry(terminologyString, terminologyEntry)
        if terminologyEntry.GetTypeObject().GetCodeValue() == codeValue:
          return curveNode

    return None

  def addAngleMeasurement(self, parameterNode, curve1Node, curve2Node):
    """
    Add parameter entry for angle measurement in parameter node for two curves
    """
    terminologiesLogic = slicer.modules.terminologies.logic()
    import vtkSlicerTerminologiesModuleLogicPython

    # Get terminology code value for first curve
    terminologyString = curve1Node.GetAttribute('TerminologyEntry')
    if not terminologyString:
      logging.error('Cannot add curve without defined terminology: %s' % curve1Node.GetName())
      return
    terminologyEntry_Curve1 = vtkSlicerTerminologiesModuleLogicPython.vtkSlicerTerminologyEntry()
    terminologiesLogic.DeserializeTerminologyEntry(terminologyString, terminologyEntry_Curve1)
    curve1CodeValue = terminologyEntry_Curve1.GetTypeObject().GetCodeValue()
    if not curve1CodeValue:
      slicer.util.warningDisplay('Cannot add angle for curve %s!\n\n\
Terminology needs to be defined first by double-clicking its color or right-clicking the curve in the view' % curve1Node.GetName())
      return

    # Get terminology code value for second curve
    terminologyString = curve2Node.GetAttribute('TerminologyEntry')
    if not terminologyString:
      logging.error('Cannot add curve without defined terminology: %s' % curve2Node.GetName())
      return
    terminologyEntry_Curve2 = vtkSlicerTerminologiesModuleLogicPython.vtkSlicerTerminologyEntry()
    terminologiesLogic.DeserializeTerminologyEntry(terminologyString, terminologyEntry_Curve2)
    curve2CodeValue = terminologyEntry_Curve2.GetTypeObject().GetCodeValue()
    if not curve2CodeValue:
      slicer.util.warningDisplay('Cannot add angle for curve %s!\n\n\
Terminology needs to be defined first by double-clicking its color or right-clicking the curve in the view' % curve2Node.GetName())
      return

    # Check if angle has been added already
    angleMeasurementNames = self.getAngleMeasurementNames(parameterNode)
    for measurementName in angleMeasurementNames:
      currentCurve1CodeValue = parameterNode.GetParameter(self.angleMeasurementParameter_Curve1Prefix + measurementName)
      currentCurve2CodeValue = parameterNode.GetParameter(self.angleMeasurementParameter_Curve2Prefix + measurementName)
      if (currentCurve1CodeValue == curve1CodeValue and currentCurve2CodeValue == curve2CodeValue) or \
         (currentCurve1CodeValue == curve2CodeValue and currentCurve2CodeValue == curve1CodeValue):
        slicer.util.warningDisplay('Angle already added!')
        return

    # Set code value parameters for angle
    newAngleId = self.getMaxAngleId(parameterNode) + 1
    newAngleMeasurementName = self.angleMeasurementNamePrefix + str(newAngleId)

    wasModified = parameterNode.StartModify()
    parameterNode.SetParameter(
      self.angleMeasurementParameter_Curve1Prefix + newAngleMeasurementName, curve1CodeValue)
    parameterNode.SetParameter(
      self.angleMeasurementParameter_Curve2Prefix + newAngleMeasurementName, curve2CodeValue)
    # Add empty angle value parameter
    parameterNode.SetParameter(
      self.getMeasurementValueParameterName(newAngleMeasurementName), 'tempValue') # Only added with non-empty string
    parameterNode.SetParameter(
      self.getMeasurementValueParameterName(newAngleMeasurementName), '')
    # Set label parameter
    angleName = curve1Node.GetName() + ' - ' + curve2Node.GetName()
    parameterNode.SetParameter(
      self.getMeasurementLabelParameterName(newAngleMeasurementName), angleName)
    parameterNode.EndModify(wasModified)

  def removeAngleMeasurements(self, parameterNode):
    """
    Remove all angle measurements
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")

    # Remove all angle measurements
    angleMeasurementNames = self.getAngleMeasurementNames(parameterNode)
    for measurementName in angleMeasurementNames:
      # Remove parameters
      parameterNode.UnsetParameter(self.angleMeasurementParameter_Curve1Prefix + measurementName)
      parameterNode.UnsetParameter(self.angleMeasurementParameter_Curve2Prefix + measurementName)
      parameterNode.UnsetParameter(self.getMeasurementValueParameterName(measurementName))
      parameterNode.UnsetParameter(self.getMeasurementLabelParameterName(measurementName))

      # Remove corresponding angle node
      outputAngleNode = parameterNode.GetNodeReference(self.parameterNodeRefPrefix_OutputAngle + measurementName)
      if not outputAngleNode:
        continue
      slicer.mrmlScene.RemoveNode(outputAngleNode)

  def resetAngleMeasurementsForAnatomyType(self, parameterNode):
    """
    Remove all angle measurements and add pre-defined angles for selected anatomy type if any
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")

    # Remove all angle measurements
    self.removeAngleMeasurements(parameterNode)

    # Add pre-defined angles for selected terminology
    currentAnatomyType = parameterNode.GetParameter(self.parameter_AnatomyTypeID)
    if currentAnatomyType == 'A' or currentAnatomyType == 'B' or currentAnatomyType == 'C':
      pdaCurveNode = self.getCurveNodeByCodeValue(parameterNode, self.pdaCodeValue)
      descendingAortaCurveNode = self.getCurveNodeByCodeValue(parameterNode, self.descendingAortaCodeValue)
      aorta2CurveNode = self.getCurveNodeByCodeValue(parameterNode, self.transverseAortaCodeValue)
      if not aorta2CurveNode: # Handle A anatomy type
        aorta2CurveNode = self.getCurveNodeByCodeValue(parameterNode, self.distalTransverseAortaCodeValue)
      if not aorta2CurveNode: # Handle C anatomy type
        aorta2CurveNode = self.getCurveNodeByCodeValue(parameterNode, self.ascendingAortaCodeValue)
      paCurveNode = self.getCurveNodeByCodeValue(parameterNode, self.proximalLpaCodeValue)
      if not paCurveNode: # Handle C anatomy type
        paCurveNode = self.getCurveNodeByCodeValue(parameterNode, self.rpaCodeValue)
      if not pdaCurveNode or not aorta2CurveNode or not descendingAortaCurveNode or not paCurveNode:
        raise ValueError('Failed to get curves for adding pre-defined angle measurements')

      self.addAngleMeasurement(parameterNode, pdaCurveNode, descendingAortaCurveNode)
      self.addAngleMeasurement(parameterNode, pdaCurveNode, aorta2CurveNode)
      self.addAngleMeasurement(parameterNode, pdaCurveNode, paCurveNode)

  def calculateMetrics(self, parameterNode):
    """
    Calculate PDA metrics
    """
    # Get and check input
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    inputSegmentationNode = parameterNode.GetNodeReference(self.parameterNodeRef_InputSegmentationNode)
    inputSegmentID = parameterNode.GetParameter(self.parameter_InputSegmentID)
    outputCenterlineCurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputCenterlineCurve)
    outputBranchesModelNode1 = parameterNode.GetNodeReference(self.parameterNodeRef_OutputBranchesModel1)
    outputTrimmedPDACurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputTrimmedPDACurve)
    outputPDAModelNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputPDAModel)
    pdaCurveNode = self.getCurveNodeByCodeValue(parameterNode, self.pdaCodeValue)
    if not inputSegmentationNode:
      raise ValueError("Input segmentation not selected")
    if inputSegmentID == '':
      raise ValueError("Input segment ID not specified")
    if not outputCenterlineCurveNode:
      raise ValueError("Output centerline curve not selected")
    if not outputBranchesModelNode1:
      raise ValueError("Output branches model not selected")
    if not outputTrimmedPDACurveNode:
      raise ValueError("Output trimmed PDA curve not selected")
    if not outputPDAModelNode:
      raise ValueError("Output PDA model not selected")
    if not pdaCurveNode:
      raise ValueError("PDA curve not selected")

    # Measure time
    import time
    startTime = time.time()
    logging.info('Calculating metrics started')

    #
    # Extract PDA model
    #
    import vtkvmtkComputationalGeometryPython as vtkvmtkComputationalGeometry
    surfacePolyData = inputSegmentationNode.GetClosedSurfaceInternalRepresentation(inputSegmentID)
    clipper = vtkvmtkComputationalGeometry.vtkvmtkPolyDataCenterlineGroupsClipper()
    clipper.SetInputData(surfacePolyData)
    clipper.SetCenterlines(outputBranchesModelNode1.GetPolyData())
    clipper.SetCenterlineGroupIdsArrayName(self.groupIdsArrayName)
    clipper.SetGroupIdsArrayName(self.groupIdsArrayName)
    clipper.SetCenterlineRadiusArrayName(self.radiusArrayName)
    clipper.SetBlankingArrayName(self.blankingArrayName)
    # clipper.SetCutoffRadiusFactor(self.CutoffRadiusFactor)
    # clipper.SetClipValue(0) # self.ClipValue)
    groupIdAttributeStr = pdaCurveNode.GetAttribute(self.firstInputPDAGroupIdAttribute)
    if groupIdAttributeStr != '':
      try:
        groupId = int(groupIdAttributeStr)
        centerlineGroupIds = vtk.vtkIdList()
        centerlineGroupIds.InsertNextId(groupId)
        clipper.SetCenterlineGroupIds(centerlineGroupIds)
        clipper.ClipAllCenterlineGroupIdsOff() #TODO: Needed?

        logging.info('Extracting PDA model using group ID %d' % (groupId))
        clipper.Update()
        outputPDAPolyData = vtk.vtkPolyData()
        outputPDAPolyData.DeepCopy(clipper.GetOutput())
        outputPDAModelNode.SetAndObservePolyData(outputPDAPolyData)
        outputPDAModelNode.CreateDefaultDisplayNodes()
        outputPDAModelDisplayNode = outputPDAModelNode.GetDisplayNode()
        outputPDAModelDisplayNode.SetColor(pdaCurveNode.GetDisplayNode().GetSelectedColor())
        outputPDAModelDisplayNode.SetOpacity(0.8)

        # Clip also the branches model for torsion calculation
        clippedPDABranchModelNode = self.getReferencedNode(parameterNode,
          self.parameterNodeRef_OutputClippedPDABranchModel, 'vtkMRMLModelNode', 'Clipped PDA branch model')
        clipper.SetInputData(outputBranchesModelNode1.GetPolyData())
        clipper.Update()
        clippedPDABranchModelNode.SetAndObservePolyData(clipper.GetOutput())
      except ValueError:
        logging.error('Failed to parse group ID attribute in PDA curve node (%s)' % (groupIdAttributeStr))
        raise
    else:
      logging.error('Failed to find group ID for selected centerline curve')

    #
    # Trim PDA curve to exclude the two endpoints
    #
    outputTrimmedPDACurveNode.RemoveAllControlPoints()
    for pointIndex in range(1, pdaCurveNode.GetNumberOfControlPoints()-1):
      pointPos = np.zeros(3)
      pdaCurveNode.GetNthControlPointPosition(pointIndex, pointPos)
      outputTrimmedPDACurveNode.AddControlPoint(pointPos)
    # outputTrimmedPDACurveNode.CopyContent(pdaCurveNode)  #TODO: It seems that it does not add the observers to the copied measurements
    # outputTrimmedPDACurveNode.RemoveNthControlPoint(outputTrimmedPDACurveNode.GetNumberOfControlPoints()-1)
    # outputTrimmedPDACurveNode.RemoveNthControlPoint(0)
    outputTrimmedPDACurveDisplayNode = outputTrimmedPDACurveNode.GetDisplayNode()
    outputTrimmedPDACurveDisplayNode.SetLineThickness(1.0)
    outputTrimmedPDACurveDisplayNode.SetTextScale(2.75)

    #
    # Calculate length measurements
    #
    self.calculateLengthMetrics(parameterNode)

    #
    # Calculate PDA tortuosity
    #
    try:
      pdaLength = float(parameterNode.GetParameter(self.getMeasurementValueParameterName('PDALength')))
      pdaEuclidianLength = float(parameterNode.GetParameter(self.getMeasurementValueParameterName('PDAEuclidianLength')))
      if pdaLength <= 0.0 or pdaEuclidianLength <= 0.0:
        raise ValueError('PDA length (%.4f) or Euclidean length (%.4f) invalid' % (pdaLength, pdaEuclidianLength))
      pdaTortuosity = pdaEuclidianLength / pdaLength #TODO: Use other formulas as well?
      parameterNode.SetParameter(self.getMeasurementValueParameterName('PDATortuosityIndex'), '%.4f'  % pdaTortuosity)
      label = 'PDA tortuosity index'
      parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDATortuosityIndex'), label)
      logging.info('%s %.2f' % (label, pdaTortuosity))
    except ValueError:
      parameterNode.SetParameter(self.getMeasurementValueParameterName('PDATortuosityIndex'), '')
      logging.error('Failed to calculate PDA tortuosity')
      raise

    #
    # Calculate diameter metrics
    #
    self.calculateDiameterMetrics(parameterNode)

    #
    # Calculate angle measurements
    #
    self.calculateAngleMeasurements(parameterNode)

    #
    # Curvature measurements
    #
    meanCurvatureMeasurement = outputTrimmedPDACurveNode.GetMeasurement(slicer.vtkCurveMeasurementsCalculator.GetMeanCurvatureName())
    meanCurvatureMeasurement.SetEnabled(True)
    maxCurvatureMeasurement = outputTrimmedPDACurveNode.GetMeasurement(slicer.vtkCurveMeasurementsCalculator.GetMaxCurvatureName())
    maxCurvatureMeasurement.SetEnabled(True)

    meanCurvature = meanCurvatureMeasurement.GetValue()
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAMeanCurvature'), '%.4f'  % meanCurvature)
    label = 'PDA mean curvature (mm-1)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAMeanCurvature'), label)
    logging.info('%s %.2f' % (label, meanCurvature))

    maxCurvature = maxCurvatureMeasurement.GetValue()
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAMaxCurvature'), '%.4f'  % maxCurvature)
    label = 'PDA maximum curvature (mm-1)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAMaxCurvature'), label)
    logging.info('%s %.2f' % (label, maxCurvature))

    # Calculate torsion
    meanTorsionMeasurement = outputTrimmedPDACurveNode.GetMeasurement(slicer.vtkCurveMeasurementsCalculator.GetMeanTorsionName())
    meanTorsionMeasurement.SetEnabled(True)
    maxTorsionMeasurement = outputTrimmedPDACurveNode.GetMeasurement(slicer.vtkCurveMeasurementsCalculator.GetMaxTorsionName())
    maxTorsionMeasurement.SetEnabled(True)

    meanTorsion = meanTorsionMeasurement.GetValue()
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAMeanTorsion'), '%.4f'  % meanTorsion)
    label = 'PDA average torsion (mm-1)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAMeanTorsion'), label)

    maxTorsion = maxTorsionMeasurement.GetValue()
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAMaxTorsion'), '%.4f'  % maxTorsion)
    label = 'PDA maximum torsion (mm-1)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAMaxTorsion'), label)

    # Show scalars
    self.updatePDAScalarDisplay(parameterNode)

    # Report time
    stopTime = time.time()
    logging.info('Calculating metrics completed in {0:.2f} seconds'.format(stopTime-startTime))

  def calculateLengthMetrics(self, parameterNode):
    """
    Calculate length of curves of interest
    """
    # Get and check input
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    pdaCurveNode = self.getCurveNodeByCodeValue(parameterNode, self.pdaCodeValue)
    outputTrimmedPDACurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputTrimmedPDACurve)
    if not pdaCurveNode:
      raise ValueError("PDA curve is not selected")
    if not outputTrimmedPDACurveNode:
      raise ValueError("Output trimmed PDA curve is not selected")
    transverseAortaCurveNode = self.getCurveNodeByCodeValue(parameterNode, self.transverseAortaCodeValue)
    distalTransverseAortaCurveNode = self.getCurveNodeByCodeValue(parameterNode, self.distalTransverseAortaCodeValue)
    proximalTransverseAortaCurveNode = self.getCurveNodeByCodeValue(parameterNode, self.proximalTransverseAortaCodeValue)

    # Calculate PDA length excluding the two endpoints
    pdaLength = 0.0
    lengthMeasurement = outputTrimmedPDACurveNode.GetMeasurement('length')
    lengthMeasurement.SetEnabled(True)
    pdaLength = lengthMeasurement.GetValue()
    if pdaLength > 0.0:
      parameterNode.SetParameter(self.getMeasurementValueParameterName('PDALength'), '%.4f'  % pdaLength)
      label = 'PDA length (mm)'
      parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDALength'), label)
      logging.info('%s %.2f' % (label, pdaLength))
    else:
      logging.error('Failed to calculate PDA length')
      parameterNode.SetParameter(self.getMeasurementValueParameterName('PDALength'), '')
      parameterNode.SetParameter(self.getMeasurementValueParameterName('PDATortuosityIndex'), '')

    # Calculate PDA Euclidian length
    pdaFirstPointPos = np.zeros(3)
    outputTrimmedPDACurveNode.GetNthControlPointPosition(0, pdaFirstPointPos)
    pdaLastPointPos = np.zeros(3)
    outputTrimmedPDACurveNode.GetNthControlPointPosition(outputTrimmedPDACurveNode.GetNumberOfControlPoints()-1, pdaLastPointPos)
    pdaEuclidianLength = np.linalg.norm(pdaLastPointPos - pdaFirstPointPos)
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAEuclidianLength'), '%.4f'  % pdaEuclidianLength)
    label = 'PDA Euclidian length (mm)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAEuclidianLength'), label)
    logging.info('%s %.2f' % (label, pdaEuclidianLength))

    # Calculate transverse aorta lengths
    def calculateCurveLength(curveNode, measurementName, measurementHumanReadableName):
      if not curveNode:
        return
      lengthMeasurement = curveNode.GetMeasurement('length')
      lengthMeasurement.SetEnabled(True)
      length = lengthMeasurement.GetValue()
      if length > 0.0:
        parameterNode.SetParameter(self.getMeasurementValueParameterName(measurementName), '%.4f'  % length)
        label = measurementHumanReadableName + ' (mm)'
        parameterNode.SetParameter(self.getMeasurementLabelParameterName(measurementName), label)
        logging.info('%s %.2f' % (label, length))
      else:
        logging.error('Failed to calculate %s' % measurementHumanReadableName)
        parameterNode.SetParameter(self.getMeasurementValueParameterName(measurementName), '')

    if transverseAortaCurveNode:
      calculateCurveLength(transverseAortaCurveNode, 'TransverseAortaLength', 'Transverse aorta length')
    if distalTransverseAortaCurveNode:
      calculateCurveLength(distalTransverseAortaCurveNode, 'DistalTransverseAortaLength', 'Distal transverse aorta length')
    if proximalTransverseAortaCurveNode:
      calculateCurveLength(proximalTransverseAortaCurveNode, 'ProximalTransverseAortaLength', 'Proximal transverse aorta length')

  def calculateDiameterMetrics(self, parameterNode):
    """
    Calculate PDA diameter metrics
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    branchesModelNode1 = parameterNode.GetNodeReference(self.parameterNodeRef_OutputBranchesModel1)
    trimmedPDACurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputTrimmedPDACurve)
    if not trimmedPDACurveNode or not branchesModelNode1:
      raise ValueError("Diameter metrics cannot be calculated because not all input is valid")

    # Get radius array
    radiusArray = self.getPointDataArrayWithName(branchesModelNode1.GetPolyData(), self.radiusArrayName)
    if not radiusArray:
      return

    # Get centerline point IDs corresponding to the trimmed curve control points
    numOfPoints = trimmedPDACurveNode.GetNumberOfControlPoints()
    loc = vtk.vtkPointLocator()
    loc.SetDataSet(branchesModelNode1.GetPolyData())
    controlPointPos = np.zeros(3)
    diameterArray = np.zeros(numOfPoints)
    for controlPointIdx in range(numOfPoints):
      trimmedPDACurveNode.GetNthControlPointPosition(controlPointIdx, controlPointPos)
      modelPointIndex = loc.FindClosestPoint(controlPointPos)
      diameterArray[controlPointIdx] = radiusArray.GetValue(modelPointIndex) * 2.0

    meanDiameter = np.mean(diameterArray)
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAMeanDiameter'), '%.4f'  % meanDiameter)
    label = 'PDA mean diameter (mm)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAMeanDiameter'), label)
    logging.info('%s %.2f' % (label, meanDiameter))

    maxDiameter = np.max(diameterArray)
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAMaxDiameter'), '%.4f'  % maxDiameter)
    label = 'PDA maximum diameter (mm)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAMaxDiameter'), label)
    logging.info('%s %.2f' % (label, maxDiameter))

    minDiameter = np.min(diameterArray)
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAMinDiameter'), '%.4f'  % minDiameter)
    label = 'PDA minimum diameter (mm)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAMinDiameter'), label)
    logging.info('%s %.2f' % (label, minDiameter))

    percentile25Diameter = np.percentile(diameterArray, 25)
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAPercentile25Diameter'), '%.4f'  % percentile25Diameter)
    label = 'PDA 25th percentile diameter (mm)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAPercentile25Diameter'), label)
    logging.info('%s %.2f' % (label, percentile25Diameter))

    percentile75Diameter = np.percentile(diameterArray, 75)
    parameterNode.SetParameter(self.getMeasurementValueParameterName('PDAPercentile75Diameter'), '%.4f'  % percentile75Diameter)
    label = 'PDA 75th percentile diameter (mm)'
    parameterNode.SetParameter(self.getMeasurementLabelParameterName('PDAPercentile75Diameter'), label)
    logging.info('%s %.2f' % (label, percentile75Diameter))

  def calculateAngleMeasurements(self, parameterNode):
    """
    Calculate angle measurements between PDA and adjacent vessels
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")

    # Get angle measurements from parameter node
    angleMeasurementNames = self.getAngleMeasurementNames(parameterNode)
    for measurementName in angleMeasurementNames:
      curve1CodeValue = parameterNode.GetParameter(self.angleMeasurementParameter_Curve1Prefix + measurementName)
      curve2CodeValue = parameterNode.GetParameter(self.angleMeasurementParameter_Curve2Prefix + measurementName)
      curve1Node = self.getCurveNodeByCodeValue(parameterNode, curve1CodeValue)
      curve2Node = self.getCurveNodeByCodeValue(parameterNode, curve2CodeValue)
      if not curve1Node or not curve2Node:
        logging.error('Failed to get curve nodes for angle measurement %s by code values "%s" and "%s"' % (measurementName, curve1CodeValue, curve2CodeValue))
        continue

      # Determine matching curve endpoints
      curve1PointPos_0 = np.zeros(3)
      curve1PointPos_1 = np.zeros(3)
      curve1PointPos_N_1 = np.zeros(3)
      curve1PointPos_N = np.zeros(3)
      curve1Node.GetNthControlPointPosition(0, curve1PointPos_0)
      curve1Node.GetNthControlPointPosition(1, curve1PointPos_1)
      curve1Node.GetNthControlPointPosition(curve1Node.GetNumberOfControlPoints()-2, curve1PointPos_N_1)
      curve1Node.GetNthControlPointPosition(curve1Node.GetNumberOfControlPoints()-1, curve1PointPos_N)

      curve2PointPos_0 = np.zeros(3)
      curve2PointPos_1 = np.zeros(3)
      curve2PointPos_N = np.zeros(3)
      curve2PointPos_N_1 = np.zeros(3)
      curve2Node.GetNthControlPointPosition(0, curve2PointPos_0)
      curve2Node.GetNthControlPointPosition(1, curve2PointPos_1)
      curve2Node.GetNthControlPointPosition(curve2Node.GetNumberOfControlPoints()-2, curve2PointPos_N_1)
      curve2Node.GetNthControlPointPosition(curve2Node.GetNumberOfControlPoints()-1, curve2PointPos_N)

      anglePointPos_Center = np.zeros(3)
      anglePointPos_End0 = np.zeros(3)
      anglePointPos_End1 = np.zeros(3)

      if np.allclose(curve1PointPos_0, curve2PointPos_0) or np.allclose(curve1PointPos_0, curve2PointPos_N):
        # Curve1 point 0 is on the side of Curve2
        anglePointPos_Center = curve1PointPos_0
        anglePointPos_End0 = curve1PointPos_1
        if np.allclose(curve1PointPos_0, curve2PointPos_0):
          anglePointPos_End1 = curve2PointPos_1
        else:
          anglePointPos_End1 = curve2PointPos_N_1

      elif np.allclose(curve1PointPos_N, curve2PointPos_0) or np.allclose(curve1PointPos_N, curve2PointPos_N):
        # Curve1 point N is on the side of Curve2
        anglePointPos_Center = curve1PointPos_N
        anglePointPos_End0 = curve1PointPos_N_1
        if np.allclose(curve1PointPos_N, curve2PointPos_0):
          anglePointPos_End1 = curve2PointPos_1
        else:
          anglePointPos_End1 = curve2PointPos_N_1
      else:
        logging.error('Curves in angle measurement %s do not touch, skipping' % measurementName)
        parameterNode.SetParameter(self.getMeasurementValueParameterName(measurementName), 'No angle')
        continue

      # Get angle markups node
      measurementLabel = parameterNode.GetParameter(self.getMeasurementLabelParameterName(measurementName))
      outputAngleNode = self.getReferencedNode(parameterNode,
        self.parameterNodeRefPrefix_OutputAngle + measurementName, 'vtkMRMLMarkupsAngleNode', measurementLabel)

      # Setup angle markups
      outputAngleNode.RemoveAllControlPoints()
      outputAngleNode.AddControlPoint(vtk.vtkVector3d(anglePointPos_End0))
      outputAngleNode.AddControlPoint(vtk.vtkVector3d(anglePointPos_Center))
      outputAngleNode.AddControlPoint(vtk.vtkVector3d(anglePointPos_End1))

      # Get measurements
      angleMeasurement = outputAngleNode.GetMeasurement('angle')
      angle = angleMeasurement.GetValue()
      if angle > 0.0:
        parameterNode.SetParameter(self.getMeasurementValueParameterName(measurementName), '%.4f'  % angle)
        logging.info('%s %.2f' % (measurementLabel, angle))
      else:
        logging.error('Failed to calculate PDA-Aorta angle')
        parameterNode.SetParameter(self.getMeasurementValueParameterName(measurementName), '')

  def getMeasurementsText(self, parameterNode, type='label'):
    """
    Assemble text containing the measurements.
    :param type: Type of the generated text. It can be 'label' or 'csv'
    """
    if not parameterNode:
      raise ValueError("Parameter node is invalid")

    # Define separators based on export type
    if type == 'label':
      measurementLabelValueSeparator = ': '
    elif type == 'csv':
      measurementLabelValueSeparator = ', '
    elif type == 'tsv':
      measurementLabelValueSeparator = '\t'
    else:
      raise ValueError('Invalid export type %s' % type)

    # Get measurement parameters
    measurementsText = ''
    parameterNames = parameterNode.GetParameterNames()
    for parameterName in parameterNames:
      if not parameterName.startswith(self.measurementParameterPrefix) or not parameterName.endswith(self.measurementParameterValuePostfix):
        continue
      measurementName = parameterName.split('_')[1]
      # Skip angles
      if measurementName.startswith(self.angleMeasurementNamePrefix):
        continue
      # Check if label is defined
      measurementLabelParameterName = self.measurementParameterPrefix + measurementName + self.measurementParameterLabelPostfix
      if measurementLabelParameterName not in parameterNames:
        logging.warning('Failed to find label for measurement %s' % measurementName)
        continue
      # Add measurement text
      measurementsText += \
        parameterNode.GetParameter(measurementLabelParameterName) + measurementLabelValueSeparator + parameterNode.GetParameter(parameterName) + '\n'

    return measurementsText

  def transferCurvePointMeasurementToSurface(self, curveNode, modelNode, arrayName):
    """
    Transfer point measurement from curve to a model node. The points of the model
    node will get a scalar array with the same name as in the curve, with the values
    of the closest curve point for each surface point.
    """
    if not curveNode or not curveNode.IsA('vtkMRMLMarkupsCurveNode') or not modelNode or not modelNode.IsA('vtkMRMLModelNode'):
      logging.error(f'Invalid inputs for transferring point measurement')
      return

    polyData = modelNode.GetPolyData()
    curveArray = self.getPointDataArrayWithName(curveNode.GetCurveWorld(), arrayName)
    if not curveArray:
      return
    modelArray = vtk.vtkDoubleArray()
    modelArray.SetName(arrayName)
    modelArray.SetNumberOfValues(polyData.GetNumberOfPoints())
    loc = vtk.vtkPointLocator()
    loc.SetDataSet(curveNode.GetCurveWorld())
    for pdaPointIdx in range(polyData.GetNumberOfPoints()):
      pdaPointPos = polyData.GetPoint(pdaPointIdx)
      curvePointIndex = loc.FindClosestPoint(pdaPointPos)
      pointMeasurementValue = curveArray.GetValue(curvePointIndex)
      modelArray.SetValue(pdaPointIdx, pointMeasurementValue)
    polyData.GetPointData().AddArray(modelArray)

  def getPointDataArrayWithName(self, polyData, arrayName):
    """
    Get an array with specified name from the point data of a polydata.
    """
    pointData = polyData.GetPointData()
    numOfArrays = pointData.GetNumberOfArrays()
    foundArrayIdx = -1
    for arrayIdx in range(numOfArrays):
      if pointData.GetArrayName(arrayIdx) == arrayName:
        foundArrayIdx = arrayIdx
        break
    if foundArrayIdx == -1:
      logging.error(f'Failed to find array named {arrayName}')
      return None
    return pointData.GetArray(foundArrayIdx)

  def updatePDAScalarDisplay(self, parameterNode):
    if not parameterNode:
      raise ValueError("Parameter node is invalid")
    outputTrimmedPDACurveNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputTrimmedPDACurve)
    outputTrimmedPDACurveDisplayNode = outputTrimmedPDACurveNode.GetDisplayNode()
    outputPDAModelNode = parameterNode.GetNodeReference(self.parameterNodeRef_OutputPDAModel)
    outputPDAModelDisplayNode = outputPDAModelNode.GetDisplayNode()
    if not outputTrimmedPDACurveNode or not outputTrimmedPDACurveDisplayNode:
      raise ValueError("Output trimmed PDA curve not selected or has an invalid display node")
    if not outputPDAModelNode or not outputPDAModelDisplayNode:
      raise ValueError("Output PDA model not selected or has an invalid display node")

    scalarArrayToShow = parameterNode.GetParameter(self.parameter_ScalarArrayToShowOnPDA)

    outputTrimmedPDACurveDisplayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeWarm1')
    outputTrimmedPDACurveDisplayNode.SetScalarVisibility(True)
    outputTrimmedPDACurveDisplayNode.SetActiveScalarName(scalarArrayToShow)
    outputTrimmedPDACurveDisplayNode.UpdateAssignedAttribute()

    # Transfer trimmed PDA curvature data to PDA model for better visualization
    self.transferCurvePointMeasurementToSurface(outputTrimmedPDACurveNode, outputPDAModelNode, scalarArrayToShow)
    outputPDAModelDisplayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeWarm1')
    outputPDAModelDisplayNode.SetScalarVisibility(True)
    outputPDAModelDisplayNode.SetActiveScalarName(scalarArrayToShow)
    outputPDAModelDisplayNode.UpdateAssignedAttribute()

#
# PDAQuantificationTest
#

class PDAQuantificationTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear()

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_PDAQuantification1()

  def test_PDAQuantification1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("Starting the test")

    self.delayDisplay('Test passed')
