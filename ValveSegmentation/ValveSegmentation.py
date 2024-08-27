import vtk, qt, ctk, slicer
import logging
from slicer.ScriptedLoadableModule import *

SMALL_SCREEN = 'SMALL_SCREEN'
LARGE_SCREEN = 'LARGE_SCREEN'
DUAL_SCREEN = 'DUAL_SCREEN'

#
# ValveSegmentation
#

class ValveSegmentation(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Valve Segmentation"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["ValveAnnulusAnalysis"]
    self.parent.contributors = ["Andras Lasso (PerkLab), Christian Herz (CHOP), Matt Jolley (UPenn)"]
    self.parent.helpText = """
    This is an example of scripted loadable module bundled in an extension.
    It performs a simple thresholding on the input volume and optionally captures a screenshot.
    """
    self.parent.acknowledgementText = """
    This file was originally developed by Andras Lasso, PerkLab.
    """  # replace with organization, grant and thanks.


#
# ValveSegmentationWidget
#

class ValveSegmentationWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModuleWidget.__init__(self, parent)

    try:
      global HeartValveLib
      import HeartValveLib
      import HeartValveLib.SmoothCurve
    except ImportError as exc:
      logging.error("{}: {}".format(self.moduleName, exc.message))

    self.logic = ValveSegmentationLogic()

    self.parameterNode = None
    self.parameterNodeObserver = None

    # Stores the currently selected HeartValveNode (scripted loadable module node)
    # and also provides methods to operate on it.
    self.valveModel = None

    self.annulusMarkupNode = None
    self.annulusMarkupNodeObserver = None

    # Used for delayed node delete
    self.nodesToRemove = []

    # Maps from ROI geometry parameter name to editing widget
    self.roiGeometryWidgets = {}

    self.inverseVolumeRendering = False

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Load widget from .ui file (created by Qt Designer)
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/ValveSegmentation.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Connect widgets

    self.ui.heartValveSelector.setNodeTypeLabel("HeartValve", "vtkMRMLScriptedModuleNode")
    self.ui.heartValveSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", "HeartValve")
    self.ui.heartValveSelector.setMRMLScene(slicer.mrmlScene)
    self.ui.heartValveSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onHeartValveSelect)

    self.ui.valveVolumeSelector.setMRMLScene(slicer.mrmlScene)
    self.ui.valveVolumeSelector.enabled = False
    self.ui.showSegmentedVolumeButton.clicked.connect(self.onShowSegmentedVolumeButtonClicked)
    self.ui.hideSlicerHeartDataButton.clicked.connect(self.onHideSlicerHeartDataClicked)

    # initial state is inconsistent, need to switch to reverse before we can set
    # the desired state reliably
    self.ui.clippingCollapsibleButton.collapsed = False
    self.ui.clippingCollapsibleButton.collapsed = True

    from HeartValveLib import ValveRoi
    self.roiGeometryWidgets[ValveRoi.PARAM_SCALE] = self.ui.clippingModelScaleSliderWidget
    self.roiGeometryWidgets[ValveRoi.PARAM_TOP_DISTANCE] = self.ui.clippingModelTopDistanceSliderWidget
    self.roiGeometryWidgets[ValveRoi.PARAM_TOP_SCALE] = self.ui.clippingModelTopScaleSliderWidget
    self.roiGeometryWidgets[ValveRoi.PARAM_BOTTOM_DISTANCE] = self.ui.clippingModelBottomDistanceSliderWidget
    self.roiGeometryWidgets[ValveRoi.PARAM_BOTTOM_SCALE] = self.ui.clippingModelBottomScaleSliderWidget

    self.ui.clippingModelUseAsEditorMaskButton.clicked.connect(self.onClippingModelUseAsEditorMaskClicked)
    self.ui.clippingModelSequenceApplyButton.clicked.connect(self.onClippingModelSequenceApplyClicked)

    # Get/create parameter node
    valveSegmentationSingletonTag = "ValveSegmentation"
    segmentEditorNode = slicer.mrmlScene.GetSingletonNode(valveSegmentationSingletonTag, "vtkMRMLSegmentEditorNode")
    if segmentEditorNode is None:
      segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
      segmentEditorNode.SetName('ValveSegmentationEditor')
      segmentEditorNode.SetHideFromEditors(True)
      segmentEditorNode.SetSingletonTag(valveSegmentationSingletonTag)
      segmentEditorNode = slicer.mrmlScene.AddNode(segmentEditorNode)

    self.ui.segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
    self.ui.segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
    self.configureDefaultTerminology()

    self.ui.displayConfigurationSelector.addItem('Small screen', SMALL_SCREEN)
    # TODO: LARGE_SCREEN setting can probably be removed.
    # LARGE_SCREEN uses the same amount of screen space as dual screen but with a different layout
    # (which is not optimized for cardiac).
    # self.ui.displayConfigurationSelector.addItem('Large screen', LARGE_SCREEN)
    self.ui.displayConfigurationSelector.addItem('Dual screen', DUAL_SCREEN)
    # Read default settings from application settings
    settings = qt.QSettings()
    displayConfiguration = settings.value('SlicerHeart/DisplayConfiguration', SMALL_SCREEN)
    displayConfigurationIndex = self.ui.displayConfigurationSelector.findData(displayConfiguration)
    self.ui.displayConfigurationSelector.setCurrentIndex(displayConfigurationIndex)

    self.ui.switchScreenConfigurationButton.clicked.connect(self.onSwitchScreenConfigurationClicked)

    self.ui.segmentOpacity2DFillSliderWidget.connect('valueChanged(double)', self.setSegmentOpacity2DFill)

    self.ui.showVolumeRenderingCheckbox.connect("stateChanged(int)", self.onShowVolumeRenderingChanged)

    # Adding GUI panels to group. This makes sure only one is open at a time.
    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.ui.clippingCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.ui.segmentationEditingCollapsibleButton)

    self.collapsibleButtonsGroup.buttonToggled.connect(self.onWorkflowStepChanged)

    # Add vertical spacer
    self.layout.addStretch(1)

    # Define list of widgets for updateGUIFromParameterNode, updateParameterNodeFromGUI, and addGUIObservers
    self.valueEditWidgets = {}  # {"DisplayConfiguration": self.ui.displayConfigurationSelector}
    self.nodeSelectorWidgets = {"HeartValve": self.ui.heartValveSelector}

    # Use singleton parameter node (it is created if does not exist yet)
    parameterNode = self.logic.getParameterNode()
    # Set parameter node (widget will observe it and also updates GUI)
    self.setAndObserveParameterNode(parameterNode)

    self.onHeartValveSelect(self.ui.heartValveSelector.currentNode())

    self.addGUIObservers()

    for paramName in self.roiGeometryWidgets.keys():
      widget = self.roiGeometryWidgets[paramName]
      widget.connect('valueChanged(double)', self.updateLeafletClippingModel)

    self.ui.clippingCollapsibleButton.collapsed = False

  def configureDefaultTerminology(self):
    tlogic = slicer.modules.terminologies.logic()
    terminologyName = tlogic.LoadTerminologyFromFile(HeartValveLib.getTerminologyFile())
    terminologyEntry = slicer.vtkSlicerTerminologyEntry()
    terminologyEntry.SetTerminologyContextName(terminologyName)

    # NB: GetNthCategoryInTerminology was introduced after Slicer 4.11 06.04 and will cause errors in older versions
    if not hasattr(tlogic, "GetNthCategoryInTerminology"):
      return
    tlogic.GetNthCategoryInTerminology(terminologyName, 0, terminologyEntry.GetCategoryObject())
    tlogic.GetNthTypeInTerminologyCategory(terminologyName, terminologyEntry.GetCategoryObject(), 0,
                                           terminologyEntry.GetTypeObject())
    defaultTerminologyEntry = tlogic.SerializeTerminologyEntry(terminologyEntry)
    self.ui.segmentEditorWidget.defaultTerminologyEntrySettingsKey = "SlicerHeart/DefaultTerminologyEntry"
    self.ui.segmentEditorWidget.defaultTerminologyEntry = defaultTerminologyEntry

  def cleanup(self):
    # Exit from any special workflow step
    self.removeGUIObservers()
    self.removeNodeObservers()
    self.setAndObserveParameterNode()

  def removeNodeObservers(self):
    self.setAndObserveAnnulusMarkupNode()

  def enter(self):
    self.ui.clippingCollapsibleButton.collapsed = False

  def exit(self):
    self.ui.segmentEditorWidget.uninstallKeyboardShortcuts()
    self.ui.segmentEditorWidget.setActiveEffect(None)

  def setGuiEnabled(self, enable):
    self.ui.clippingCollapsibleButton.setEnabled(enable)
    self.ui.segmentationEditingCollapsibleButton.setEnabled(enable)

  def onWorkflowStepChanged(self, widget, toggle):
    leafletClippingModel = self.getLeafletClippingModelNode()
    leafletClippingModelDisplayNode = leafletClippingModel.GetDisplayNode() if leafletClippingModel else None

    if widget == self.ui.segmentationEditingCollapsibleButton:
      if toggle:
        if leafletClippingModelDisplayNode:
          leafletClippingModelDisplayNode.SetVisibility(False)
        self.ui.segmentEditorWidget.installKeyboardShortcuts()
        self.setupScreen()
      else:
        self.ui.segmentEditorWidget.uninstallKeyboardShortcuts()
        self.ui.segmentEditorWidget.setActiveEffect(None)
        self.ui.segmentationEditingCollapsibleButton.text = "Leaflet segmentation"
    elif widget == self.ui.clippingCollapsibleButton:
      if leafletClippingModelDisplayNode:
        leafletClippingModelDisplayNode.SetVisibility(True)

  def setAndObserveParameterNode(self, parameterNode=None):
    if parameterNode is self.parameterNode and self.parameterNodeObserver:
      # no change and node is already observed
      return
    # Remove observer to old parameter node
    if self.parameterNode and self.parameterNodeObserver:
      self.parameterNode.RemoveObserver(self.parameterNodeObserver)
      self.parameterNodeObserver = None
    # Set and observe new parameter node
    self.parameterNode = parameterNode
    if self.parameterNode:
      self.parameterNodeObserver = self.parameterNode.AddObserver(vtk.vtkCommand.ModifiedEvent,
                                                                  self.onParameterNodeModified)
    # Update GUI
    self.updateGUIFromParameterNode()

  def getParameterNode(self):
    return self.parameterNode

  def onParameterNodeModified(self, observer, eventid):
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self):
    parameterNode = self.getParameterNode()
    if not parameterNode:
      self.setAndObserveAnnulusMarkupNode()
      return
    for parameterName in self.valueEditWidgets:
      oldBlockSignalsState = self.valueEditWidgets[parameterName].blockSignals(True)
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      parameterValue = parameterNode.GetParameter(parameterName)
      if not parameterValue:
        logging.debug("No value is available for parameter " + parameterName + ", keep current value on GUI")
        continue
      if widgetClassName in ["QCheckBox"]:
        self.valueEditWidgets[parameterName].checked = (parameterValue.lower() == 'True'.lower())
      elif widgetClassName in ["ctkCollapsibleButton"]:
        self.valueEditWidgets[parameterName].collapsed = not (parameterValue.lower() == 'True'.lower())
      elif widgetClassName in ["QSpinBox", "ctkSliderWidget"]:
        self.valueEditWidgets[parameterName].setValue(float(parameterValue))
      elif widgetClassName in ["QComboBox"]:
        selectedIndex = self.valueEditWidgets[parameterName].findData(parameterValue)
        self.valueEditWidgets[parameterName].setCurrentIndex(selectedIndex)
      else:
        raise Exception("Unexpected widget class: {0}".format(widgetClassName))
      self.valueEditWidgets[parameterName].blockSignals(oldBlockSignalsState)
    for parameterName in self.nodeSelectorWidgets:
      oldBlockSignalsState = self.nodeSelectorWidgets[parameterName].blockSignals(True)
      self.nodeSelectorWidgets[parameterName].setCurrentNodeID(parameterNode.GetNodeReferenceID(parameterName))
      self.nodeSelectorWidgets[parameterName].blockSignals(oldBlockSignalsState)

  def updateParameterNodeFromGUI(self):
    parameterNode = self.getParameterNode()
    oldModifiedState = parameterNode.StartModify()
    for parameterName in self.valueEditWidgets:
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName in ["QCheckBox"]:
        parameterNode.SetParameter(parameterName, 'True' if self.valueEditWidgets[parameterName].checked else 'False')
      elif widgetClassName in ["ctkCollapsibleButton"]:
        parameterNode.SetParameter(parameterName, 'False' if self.valueEditWidgets[parameterName].collapsed else 'True')
      elif widgetClassName in ["QSpinBox", "ctkSliderWidget"]:
        parameterNode.SetParameter(parameterName, str(self.valueEditWidgets[parameterName].value))
      elif widgetClassName in ["QComboBox"]:
        userData = ''
        if self.valueEditWidgets[parameterName].currentIndex >= 0:
          userData = self.valueEditWidgets[parameterName].itemData(self.valueEditWidgets[parameterName].currentIndex)
        parameterNode.SetParameter(parameterName, str(userData))
      else:
        raise Exception("Unexpected widget class: {0}".format(widgetClassName))
    for parameterName in self.nodeSelectorWidgets:
      parameterNode.SetNodeReferenceID(parameterName, self.nodeSelectorWidgets[parameterName].currentNodeID)
    parameterNode.EndModify(oldModifiedState)

  def addGUIObservers(self):
    for parameterName in self.valueEditWidgets:
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName == "QCheckBox":
        self.valueEditWidgets[parameterName].connect("clicked()", self.updateParameterNodeFromGUI)
      elif widgetClassName == "QSpinBox":
        self.valueEditWidgets[parameterName].connect("valueChanged(int)", self.updateParameterNodeFromGUI)
      elif widgetClassName == "ctkSliderWidget":
        self.valueEditWidgets[parameterName].connect("valueChanged(double)", self.updateParameterNodeFromGUI)
      elif widgetClassName == "ctkCollapsibleButton":
        self.valueEditWidgets[parameterName].connect("contentsCollapsed(bool)", self.updateParameterNodeFromGUI)
      elif widgetClassName == "QComboBox":
        self.valueEditWidgets[parameterName].connect("currentIndexChanged(int)", self.updateParameterNodeFromGUI)
      else:
        raise Exception("Unexpected widget class: {0}".format(widgetClassName))
    for parameterName in self.nodeSelectorWidgets:
      self.nodeSelectorWidgets[parameterName].connect("currentNodeIDChanged(QString)", self.updateParameterNodeFromGUI)

  def removeGUIObservers(self):
    for parameterName in self.valueEditWidgets:
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName == "QCheckBox":
        self.valueEditWidgets[parameterName].disconnect("clicked()", self.updateParameterNodeFromGUI)
      elif widgetClassName == "QSpinBox":
        self.valueEditWidgets[parameterName].disconnect("valueChanged(int)", self.updateParameterNodeFromGUI)
      elif widgetClassName == "ctkSliderWidget":
        self.valueEditWidgets[parameterName].disconnect("valueChanged(double)", self.updateParameterNodeFromGUI)
    for parameterName in self.nodeSelectorWidgets:
      self.nodeSelectorWidgets[parameterName].disconnect("currentNodeIDChanged(QString)",
                                                         self.updateParameterNodeFromGUI)

  def onHeartValveSelect(self, node):
    logging.debug("Selected heart valve node: {0}".format(node.GetName() if node else "None"))
    self.setHeartValveNode(node)

  def setHeartValveNode(self, heartValveNode):
    if self.valveModel and self.valveModel.getHeartValveNode() == heartValveNode:
      return

    self.valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)

    if self.valveModel:
      self._setupValveVolume()
      self._updateRoiGeometryGui()
      self._updateDisplaySettingsGui()

    # Observe nodes
    annulusMarkupNode = self.valveModel.getAnnulusContourMarkupNode() if self.valveModel else None
    self.setAndObserveAnnulusMarkupNode(annulusMarkupNode)

    # Update GUI button enabled/disabled state
    self.setGuiEnabled(heartValveNode is not None)
    valveVolumeNode = self.valveModel.getValveVolumeNode() if self.valveModel else None
    self.ui.clippingModelSequenceApplyButton.setDisabled(valveVolumeNode is None)

    HeartValveLib.goToAnalyzedFrame(self.valveModel)
    segmentationNode = None
    if self.valveModel:
      HeartValveLib.useCurrentValveVolumeAsLeafletVolume(self.valveModel)
      segmentationNode = self.valveModel.getLeafletSegmentationNode()

    self._setSegmentationNode(segmentationNode)
    if not self.ui.segmentationEditingCollapsibleButton.collapsed:
      self.ui.clippingCollapsibleButton.collapsed = False
    if self.ui.hideSlicerHeartDataButton.checked:
      self.onHideSlicerHeartDataClicked()

  def _setSegmentationNode(self, segNode):
    # NB: sometimes segmentation node is already set within mrmlSegmentEditorNode which is why the segment list doesnt
    #     get updated. Setting it to None or firing Modified flag works.
    self.ui.segmentEditorWidget.setSegmentationNode(None)
    if segNode is None:
      return
    # ensure the leaflet volume is the master node and not the sequence proxy
    movingVolumeNode = self.valveModel.getValveVolumeNode()
    fixedVolumeNode = self.valveModel.getLeafletVolumeNode()
    currentMasterVolumeNode = segNode.GetNodeReference(segNode.GetReferenceImageGeometryReferenceRole())
    if currentMasterVolumeNode is None or currentMasterVolumeNode is movingVolumeNode:
      if currentMasterVolumeNode is not None:
        logging.info(f"Sequence browser proxy was set as master volume node. Correcting that...")
      segNode.SetNodeReferenceID(segNode.GetReferenceImageGeometryReferenceRole(), fixedVolumeNode.GetID())

    self.ui.segmentEditorWidget.setSegmentationNode(segNode)

  def _setupValveVolume(self):
    self.ui.valveVolumeSelector.setCurrentNode(self.valveModel.getValveVolumeNode())
    valveVolumeSequenceIndexStr = self.valveModel.getVolumeSequenceIndexAsDisplayedString(
      self.valveModel.getValveVolumeSequenceIndex())
    self.ui.valveVolumeSequenceIndexValue.setText(valveVolumeSequenceIndexStr)

  def _updateRoiGeometryGui(self):
    roiGeometry = self.valveModel.valveRoi.getRoiGeometry()
    for paramName in self.roiGeometryWidgets.keys():
      widget = self.roiGeometryWidgets[paramName]
      wasBlocked = widget.blockSignals(True)
      widget.value = roiGeometry[paramName]
      widget.blockSignals(wasBlocked)

  def _updateDisplaySettingsGui(self):
    segmentationNode = self.valveModel.getLeafletSegmentationNode()
    segmentationDisplayNode = segmentationNode.GetDisplayNode() if segmentationNode else None
    if segmentationDisplayNode and segmentationNode.GetSegmentation().GetNumberOfSegments() > 0:
      firstVisibleSegmentId = self.getFirstVisibleSegmentId()
      if firstVisibleSegmentId:
        fillPercent = segmentationDisplayNode.GetSegmentOpacity2DFill(self.getFirstVisibleSegmentId()) * 100.0
      else:
        fillPercent = 50.0
      wasBlocked = self.ui.segmentOpacity2DFillSliderWidget.blockSignals(True)
      self.ui.segmentOpacity2DFillSliderWidget.value = fillPercent
      self.ui.segmentOpacity2DFillSliderWidget.blockSignals(wasBlocked)
    volumeRenderingVisible = False
    if self.valveModel.getClippedVolumeNode():
      clippedVolumeNode = self.valveModel.getClippedVolumeNode()
      vrLogic = slicer.modules.volumerendering.logic()
      try:
        displayNode = vrLogic.GetFirstVolumeRenderingDisplayNode(clippedVolumeNode)
        volumeRenderingVisible = displayNode.GetVisibility()
      except AttributeError:
        logging.warning("{}: has clipped volume node, but no "
                        "volume rendering display node was found.".format(self.valveModel.heartValveNode.GetName()))
    wasBlocked = self.ui.showVolumeRenderingCheckbox.blockSignals(True)
    self.ui.showVolumeRenderingCheckbox.checked = volumeRenderingVisible
    self.ui.showVolumeRenderingCheckbox.blockSignals(wasBlocked)

  def onShowSegmentedVolumeButtonClicked(self):
    HeartValveLib.goToAnalyzedFrame(self.valveModel)

  def onHideSlicerHeartDataClicked(self):
    from HeartValveLib.helpers import hideAllSlicerHeartData, setValveModelDataVisibility
    hideAllSlicerHeartData()
    if self.valveModel is not None:
      setValveModelDataVisibility(self.valveModel, annulus=True, segmentation=True, roi=True)

  def getFirstVisibleSegmentId(self):
    segmentationNode = self.valveModel.getLeafletSegmentationNode()
    segmentationDisplayNode = segmentationNode.GetDisplayNode()
    segmentIDs = vtk.vtkStringArray()
    segmentationNode.GetSegmentation().GetSegmentIDs(segmentIDs)
    for index in range(segmentIDs.GetNumberOfValues()):
      segmentID = segmentIDs.GetValue(index)
      if segmentationDisplayNode.GetSegmentVisibility(segmentID):
        return segmentID
    return None

  def setAndObserveAnnulusMarkupNode(self, annulusMarkupNode=None):
    logging.debug(
      "Observe annulus markup node: {0}".format(annulusMarkupNode.GetName() if annulusMarkupNode else "None"))
    if annulusMarkupNode == self.annulusMarkupNode and self.annulusMarkupNodeObserver:
      # no change and node is already observed
      logging.debug("Already observed")
      return
    # Remove observer to old node
    if self.annulusMarkupNode and self.annulusMarkupNodeObserver:
      self.annulusMarkupNode.RemoveObserver(self.annulusMarkupNodeObserver)
      self.annulusMarkupNodeObserver = None
    # Set and observe new node
    self.annulusMarkupNode = annulusMarkupNode
    if self.annulusMarkupNode:
      self.annulusMarkupNodeObserver = \
        self.annulusMarkupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                                           self.onAnnulusMarkupNodeModified)

    # Update model
    self.onAnnulusMarkupNodeModified()

  def onAnnulusMarkupNodeModified(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    if not self.annulusMarkupNode:
      return
    self.valveModel.updateAnnulusContourModel()
    self.updateLeafletClippingModel()

  def onClippingModelUseAsEditorMaskClicked(self):
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.valveModel.getLeafletSegmentationNode()
    segmentation = segmentationNode.GetSegmentation()
    valveMaskSegment = segmentation.GetSegment(HeartValveLib.VALVE_MASK_SEGMENT_ID)
    leafletMaskOrientedImageData = self.logic.getLeafletVolumeClippedAxisAligned(self.valveModel)
    if valveMaskSegment:
      self._updateMaskSegment(leafletMaskOrientedImageData, segmentationNode)
    else:
      self._createNewMaskSegment(segmentationNode)

    # Switch to editor
    self.ui.segmentationEditingCollapsibleButton.collapsed = False

    self._configureMaskSegment(segmentationNode)
    self._setupMaskedEditing()

    volumeIjkToRasMatrix = vtk.vtkMatrix4x4()
    leafletMaskOrientedImageData.GetImageToWorldMatrix(volumeIjkToRasMatrix)
    leafletMaskOrientedImageDataGeometry = \
      vtkSegmentationCore.vtkSegmentationConverter.SerializeImageGeometry(volumeIjkToRasMatrix,
                                                                          leafletMaskOrientedImageData)

    segmentation.SetConversionParameter(
      vtkSegmentationCore.vtkSegmentationConverter.GetReferenceImageGeometryParameterName(),
      leafletMaskOrientedImageDataGeometry)

  def _updateMaskSegment(self, leafletMaskOrientedImageData, segmentationNode):
    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(leafletMaskOrientedImageData,
                                                                        segmentationNode,
                                                                        HeartValveLib.VALVE_MASK_SEGMENT_ID)

  def _createNewMaskSegment(self, segmentationNode):
    import vtkSegmentationCorePython as vtkSegmentationCore
    leafletMaskOrientedImageData = self.logic.getLeafletVolumeClippedAxisAligned(self.valveModel)
    valveMaskSegment = vtkSegmentationCore.vtkSegment()
    valveMaskSegment.SetName("Annulus mask")
    valveMaskSegment.AddRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName(),
      leafletMaskOrientedImageData)
    segmentation = segmentationNode.GetSegmentation()
    segmentation.AddSegment(valveMaskSegment, HeartValveLib.VALVE_MASK_SEGMENT_ID)

  def _configureMaskSegment(self, segmentationNode):
    # Hide mask segment (and set some default display settings, just in case the segment is manually
    # switched to visible)
    segmentation = segmentationNode.GetSegmentation()
    valveMaskSegment = segmentation.GetSegment(HeartValveLib.VALVE_MASK_SEGMENT_ID)
    valveMaskSegment.SetTag(valveMaskSegment.GetTerminologyEntryTagName(),
                            self.ui.segmentEditorWidget.defaultTerminologyEntry)

    valveMaskSegment.SetColor(vtk.vtkVector3d([0, 0, 1]))
    sdn = segmentationNode.GetDisplayNode()
    sdn.SetSegmentOpacity(HeartValveLib.VALVE_MASK_SEGMENT_ID, 0.3)
    sdn.SetSegmentVisibility2DOutline(HeartValveLib.VALVE_MASK_SEGMENT_ID, False)
    sdn.SetSegmentVisibility3D(HeartValveLib.VALVE_MASK_SEGMENT_ID, False)
    sdn.SetSegmentVisibility(HeartValveLib.VALVE_MASK_SEGMENT_ID, False)

  def _setupMaskedEditing(self):
    # Set up masking: draw only inside the valve area, don't overwrite hidden segments (valve mask)
    segmentEditorNode = self.ui.segmentEditorWidget.mrmlSegmentEditorNode()
    segmentEditorNode.SetMaskSegmentID(HeartValveLib.VALVE_MASK_SEGMENT_ID)
    segmentEditorNode.SetMaskMode(slicer.vtkMRMLSegmentationNode.EditAllowedInsideSingleSegment)
    segmentEditorNode.SetOverwriteMode(segmentEditorNode.OverwriteVisibleSegments)

  def onClippingModelSequenceApplyClicked(self):
    self.setupVolumeRendering()

  def setupVolumeRendering(self):
    leafletClippingModel = self.getLeafletClippingModelNode()
    if leafletClippingModel is None:
      logging.error("setupVolumeRendering failed: no clipping model is defined")
      return
    volumeNode = self.valveModel.getValveVolumeNode()
    if volumeNode is None:
      logging.error("setupVolumeRendering failed: input volume is invalid")
      return

    volumeSequenceBrowserNode = HeartValveLib.HeartValves.getSequenceBrowserNodeForMasterOutputNode(volumeNode)
    volumeSequenceNode = volumeSequenceBrowserNode.GetMasterSequenceNode() if volumeSequenceBrowserNode is not None else None
    if volumeSequenceNode is None:
      # valve volume is not part of a sequence, create a simple volume as clipped volume
      clippedVolumeNode = self.valveModel.getClippedVolumeNode()
      if clippedVolumeNode is None:
        clippedVolumeNode = slicer.modules.volumes.logic().CloneVolume(volumeNode, volumeNode.GetName() + "-clipped")
        self.valveModel.setClippedVolumeNode(clippedVolumeNode)
      else:
        clippedVolumeNodeOriginalDisplayNodeId = clippedVolumeNode.GetDisplayNodeID()
        clippedVolumeNode.Copy(volumeNode)
        clippedVolumeNode.SetName(volumeNode.GetName() + "-clipped")
        clippedVolumeNode.SetAndObserveDisplayNodeID(clippedVolumeNodeOriginalDisplayNodeId)
        self.valveModel.setClippedVolumeNode(clippedVolumeNode)
      self.valveModel.valveRoi.clipVolumeWithModel(volumeNode, clippedVolumeNode, reduceExtent=True)
    else:
      # input is a sequence, need to clip the entire sequence
      clippedVolumeSequenceNode = volumeSequenceBrowserNode.GetSequenceNode(self.valveModel.getClippedVolumeNode())
      if not clippedVolumeSequenceNode:
        # create a clipped sequence
        clippedVolumeSequenceNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLSequenceNode")
        clippedVolumeSequenceNode.UnRegister(None)
        clippedVolumeSequenceNode.SetName(volumeSequenceNode.GetName() + "-clipped")
        clippedVolumeSequenceNode.SetIndexName(volumeSequenceNode.GetIndexName())
        clippedVolumeSequenceNode.SetIndexUnit(volumeSequenceNode.GetIndexUnit())
        clippedVolumeSequenceNode.SetIndexType(volumeSequenceNode.GetIndexType())
        slicer.mrmlScene.AddNode(clippedVolumeSequenceNode)
        volumeSequenceBrowserNode.AddSynchronizedSequenceNode(clippedVolumeSequenceNode.GetID())

      rasToModel = vtk.vtkMatrix4x4()
      slicer.vtkMRMLTransformNode.GetMatrixTransformBetweenNodes(volumeNode.GetParentTransformNode(),
                                                                 leafletClippingModel.GetParentTransformNode(),
                                                                 rasToModel)
      clippingPolyData = leafletClippingModel.GetPolyData()
      inputVolumeIjkToRas = vtk.vtkMatrix4x4()
      outputVolumeIjkToRas = vtk.vtkMatrix4x4()

      # This can be a long operation - indicate it to the user
      qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
      try:

        clippedVolumeSequenceNodeWasModified = clippedVolumeSequenceNode.StartModify()
        clippedVolumeSequenceNode.RemoveAllDataNodes()  # we recreate all the vtkImageData anyway, so we would not save much by keeping existing nodes
        for itemIndex in range(volumeSequenceNode.GetNumberOfDataNodes()):
          inputVolumeNode = volumeSequenceNode.GetNthDataNode(itemIndex)
          inputImageData = inputVolumeNode.GetImageData()
          inputVolumeNode.GetIJKToRASMatrix(inputVolumeIjkToRas)
          outputImageData = vtk.vtkImageData()
          self.valveModel.valveRoi.clipImageWithPolyData(inputImageData, outputImageData, clippingPolyData, rasToModel,
                                                         inputVolumeIjkToRas,
                                                         outputVolumeIjkToRas, reduceExtent=True,
                                                         fillValue=255 if self.inverseVolumeRendering else 0)
          outputVolumeNode = slicer.vtkMRMLScalarVolumeNode()
          outputVolumeNode.SetAndObserveImageData(outputImageData)
          outputVolumeNode.SetIJKToRASMatrix(outputVolumeIjkToRas)
          clippedVolumeSequenceNode.SetDataNodeAtValue(outputVolumeNode, volumeSequenceNode.GetNthIndexValue(itemIndex))
        clippedVolumeSequenceNode.EndModify(clippedVolumeSequenceNodeWasModified)

      except Exception as exc:
        qt.QApplication.restoreOverrideCursor()
        raise exc

      qt.QApplication.restoreOverrideCursor()

      sequencesModule = slicer.modules.sequences
      sequencesModule.logic().UpdateProxyNodesFromSequences(volumeSequenceBrowserNode)
      clippedVolumeNode = volumeSequenceBrowserNode.GetProxyNode(clippedVolumeSequenceNode)
      self.valveModel.setClippedVolumeNode(clippedVolumeNode)

    if clippedVolumeNode.GetDisplayNodeID() is None:
      self.addDisplayNode(clippedVolumeNode)  # make sure a display node is present
      clippedVolumeNode.GetDisplayNode().Copy(volumeNode.GetDisplayNode())

    # Setup VR display node
    vrLogic = slicer.modules.volumerendering.logic()
    displayNode = vrLogic.GetFirstVolumeRenderingDisplayNode(clippedVolumeNode)
    if not displayNode:
      # Create and set up a new display node

      # Use default VR display node stored in the settings
      settings = qt.QSettings()
      vrRenderingDisplayNodeClassName = settings.value('VolumeRendering/RenderingMethod')
      # gpuMemorySize = int(settings.value('VolumeRendering/GPUMemorySize'))
      displayNode = slicer.mrmlScene.CreateNodeByClass(vrRenderingDisplayNodeClassName)
      displayNode.UnRegister(None)

      slicer.mrmlScene.AddNode(displayNode)
      wasModifying = displayNode.StartModify()
      # displayNode.SetGPUMemorySize(gpuMemorySize) # this method is now in view node

      propNode = slicer.vtkMRMLVolumePropertyNode()
      slicer.mrmlScene.AddNode(propNode)
      displayNode.SetAndObserveVolumePropertyNodeID(propNode.GetID())

      presetsScene = vrLogic.GetPresetsScene()
      if self.inverseVolumeRendering:
        presetNodes = presetsScene.GetNodesByName('US-InverseGreen')
      else:
        presetNodes = presetsScene.GetNodesByName('US-Red-Tinge')
      presetNodes.UnRegister(None)
      if presetNodes.GetNumberOfItems() > 0:
        presetNode = presetNodes.GetItemAsObject(0)
        propNode.Copy(presetNode)

      # logic.CopyDisplayToVolumeRenderingDisplayNode(displayNode)
      displayNode.EndModify(wasModifying)
      clippedVolumeNode.AddAndObserveDisplayNodeID(displayNode.GetID())

      # Wait for an initial rendering to be completed
      lm = slicer.app.layoutManager()
      if lm.threeDViewCount > 0:
        view = lm.threeDWidget(0).threeDView()
        rw = view.renderWindow()
        rw.Render()

    volumeRenderingVisible = True
    displayNode.SetVisibility(volumeRenderingVisible)
    wasBlocked = self.ui.showVolumeRenderingCheckbox.blockSignals(True)
    self.ui.showVolumeRenderingCheckbox.checked = volumeRenderingVisible
    self.ui.showVolumeRenderingCheckbox.blockSignals(wasBlocked)

  @staticmethod
  def addDisplayNode(outputVolume):
    if outputVolume.GetDisplayNode() is None:
      displayNode = slicer.vtkMRMLScalarVolumeDisplayNode()
      displayNode.SetAndObserveColorNodeID("vtkMRMLColorTableNodeGrey")
      slicer.mrmlScene.AddNode(displayNode)
      outputVolume.SetAndObserveDisplayNodeID(displayNode.GetID())

  def copySegmentation(self, sourceLabelNode, destinationLabelNode, pixelType, interpolationMethod, invertTransform):

    params = {'inputVolume': sourceLabelNode.GetID(),
              'outputVolume': destinationLabelNode.GetID(),
              'referenceVolume': destinationLabelNode.GetID(),
              'pixelType': pixelType,
              'interpolationMode': interpolationMethod,
              'inverseTransform': invertTransform,
              'warpTransform': self.valveModel.getProbeToRasTransformNode().GetID()}

    paramNode = slicer.cli.createNode(slicer.modules.brainsresample, params)
    logic = slicer.modules.brainsresample.logic()
    logic.SetDeleteTemporaryFiles(1)
    logic.ApplyAndWait(paramNode, False)  # do not display output, it would ruin the FOV setting

    slicer.mrmlScene.RemoveNode(paramNode)

    # Copy colormap
    destinationLabelNode.GetDisplayNode().SetAndObserveColorNodeID(sourceLabelNode.GetDisplayNode().GetColorNodeID())

  def setupScreen(self):
    displayConfiguration = self.ui.displayConfigurationSelector.itemData(
      self.ui.displayConfigurationSelector.currentIndex)

    # Set layout
    if displayConfiguration == SMALL_SCREEN:
      HeartValveLib.setupDefaultLayout(HeartValveLib.CardiacFourUpViewLayoutId)
    elif displayConfiguration == LARGE_SCREEN:
      HeartValveLib.setupDefaultLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourOverFourView)
    elif displayConfiguration == DUAL_SCREEN:
      HeartValveLib.setupDefaultLayout(HeartValveLib.CardiacEightUpViewLayoutId)

    self.ui.segmentationEditingCollapsibleButton.text = \
      f"Leaflet segmentation ({self.valveModel.getLeafletVolumeNode().GetName()})"

    fixedVolumeNode = self.valveModel.getLeafletVolumeNode()
    movingVolumeNode = self.valveModel.getValveVolumeNode()

    valveVolumeBrowserNode = HeartValveLib.HeartValves.getSequenceBrowserNodeForMasterOutputNode(
      self.valveModel.getValveVolumeNode())
    if valveVolumeBrowserNode is not None:
      sequencesModule = slicer.modules.sequences
      sequencesModule.widgetRepresentation().setActiveBrowserNode(valveVolumeBrowserNode)

    primarySliceViewNames = ['Red', 'Yellow', 'Green']
    secondarySliceViewNames = ['Slice4', 'Slice5', 'Slice6']
    if displayConfiguration == SMALL_SCREEN:
      # Unlock
      self.setSliceViewsLink(primarySliceViewNames, False, False)
      # Primary
      self.setSliceViewsBackgroundVolume(primarySliceViewNames, movingVolumeNode)
      self.setSliceViewsForegroundVolume(primarySliceViewNames, fixedVolumeNode, 0.0)
      self.setSliceViewsLabelVolume(primarySliceViewNames)
      self.setSliceViewsDefaultOrientation(primarySliceViewNames)
      # Lock
      self.setSliceViewsLink(primarySliceViewNames, True, True)
    elif displayConfiguration == LARGE_SCREEN or displayConfiguration == DUAL_SCREEN:
      # Unlock
      self.setSliceViewsLink(primarySliceViewNames + secondarySliceViewNames, False, False)
      # Primary
      self.setSliceViewsBackgroundVolume(primarySliceViewNames, fixedVolumeNode)
      # NB: don't show movingVolumeNode because it would slow down replay speed
      self.setSliceViewsForegroundVolume(primarySliceViewNames, volumeNode=None)
      self.setSliceViewsLabelVolume(primarySliceViewNames)
      self.setSliceViewsDefaultOrientation(primarySliceViewNames)
      # Secondary
      self.setSliceViewsBackgroundVolume(secondarySliceViewNames, movingVolumeNode)
      # NB: don't show fixedVolumeNode to reduce confusion
      self.setSliceViewsForegroundVolume(secondarySliceViewNames, volumeNode=None)
      self.setSliceViewsLabelVolume(secondarySliceViewNames)
      self.setSliceViewsDefaultOrientation(secondarySliceViewNames)
      self.setSliceViewsHeartOrientationmarker(secondarySliceViewNames)
      # Lock
      self.setSliceViewsLink(primarySliceViewNames + secondarySliceViewNames, True, True)
      # propagate FOV to secondary views
      self.touchSliceViewsFieldOfView(primarySliceViewNames)

  @staticmethod
  def setSliceViewsBackgroundVolume(viewNames, volumeNode):
    layoutManager = slicer.app.layoutManager()
    for sliceViewName in viewNames:
      sliceLogic = layoutManager.sliceWidget(sliceViewName).sliceLogic()
      sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
      sliceCompositeNode.SetBackgroundVolumeID(volumeNode.GetID() if volumeNode else None)

  @staticmethod
  def setSliceViewsForegroundVolume(viewNames, volumeNode=None, foregroundOpacity=0.0):
    layoutManager = slicer.app.layoutManager()
    for sliceViewName in viewNames:
      sliceLogic = layoutManager.sliceWidget(sliceViewName).sliceLogic()
      sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
      sliceCompositeNode.SetForegroundVolumeID(volumeNode.GetID() if volumeNode else None)
      sliceCompositeNode.SetForegroundOpacity(foregroundOpacity)

  @staticmethod
  def setSliceViewsLabelVolume(viewNames, volumeNode=None):
    layoutManager = slicer.app.layoutManager()
    for sliceViewName in viewNames:
      sliceLogic = layoutManager.sliceWidget(sliceViewName).sliceLogic()
      sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
      sliceCompositeNode.SetLabelVolumeID(volumeNode.GetID() if volumeNode else None)
      sliceViewNode = sliceLogic.GetSliceNode()
      sliceViewNode.SetUseLabelOutline(True)

  @staticmethod
  def setSliceViewsLink(viewNames, link, hotlink):
    layoutManager = slicer.app.layoutManager()
    for sliceViewName in viewNames:
      sliceLogic = layoutManager.sliceWidget(sliceViewName).sliceLogic()
      sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
      sliceCompositeNode.SetLinkedControl(link)
      sliceCompositeNode.SetHotLinkedControl(hotlink)

  def setSliceViewsDefaultOrientation(self, viewNames):
    if viewNames is None:
      return
    resetFov = True
    HeartValveLib.setupDefaultSliceOrientation(resetFov=resetFov, valveModel=self.valveModel,
                                               axialSliceName=viewNames[0],
                                               ortho1SliceName=viewNames[1],
                                               ortho2SliceName=viewNames[2],
                                               show3DSliceName=None)

  @staticmethod
  def setSliceViewsHeartOrientationmarker(viewNames):
    layoutManager = slicer.app.layoutManager()
    for sliceViewName in viewNames:
      sliceLogic = layoutManager.sliceWidget(sliceViewName).sliceLogic()
      sliceViewNode = sliceLogic.GetSliceNode()
      HeartValveLib.HeartValves.setHeartOrientationmarker(sliceViewNode.GetID())

  @staticmethod
  def touchSliceViewsFieldOfView(viewNames):
    """
    indicates a change in the field of view without actually changing it
    useful for propagation of field of view to linked views
    """
    if viewNames is None:
      return
    layoutManager = slicer.app.layoutManager()
    for sliceViewName in viewNames:
      sliceLogic = layoutManager.sliceWidget(sliceViewName).sliceLogic()
      sliceLogic.StartSliceNodeInteraction(slicer.vtkMRMLSliceNode.FieldOfViewFlag)
      sliceLogic.EndSliceNodeInteraction()
      sliceLogic.StartSliceOffsetInteraction()
      sliceLogic.EndSliceOffsetInteraction()

  def onSwitchScreenConfigurationClicked(self):
    self.saveDisplayConfigurationSettings()
    self.setupScreen()

  def saveDisplayConfigurationSettings(self):
    displayConfiguration = self.ui.displayConfigurationSelector.itemData(
      self.ui.displayConfigurationSelector.currentIndex)
    settings = qt.QSettings()
    settings.setValue('SlicerHeart/DisplayConfiguration', displayConfiguration)

  def updateLeafletClippingModel(self):

    leafletClippingModel = self.getLeafletClippingModelNode()

    # Get ROI geometry from widgets and update ROI based on that
    roiGeometry = {}
    for paramName in self.roiGeometryWidgets.keys():
      roiGeometry[paramName] = self.roiGeometryWidgets[paramName].value
    self.valveModel.valveRoi.setRoiGeometry(roiGeometry)

    leafletClippingModel.GetDisplayNode().SetVisibility(True)

  def getLeafletClippingModelNode(self):
    if not self.valveModel or not self.valveModel.getValveRoiModelNode():
      return None
    return self.valveModel.getValveRoiModelNode()

  def setSegmentOpacity2DFill(self, fillPercent):
    segmentationNode = self.valveModel.getLeafletSegmentationNode() if self.valveModel else None
    if not segmentationNode:
      return
    segmentationDisplayNode = segmentationNode.GetDisplayNode()
    if not segmentationNode:
      return
    fillRatio = fillPercent * 0.01
    # NB: True flag: change visible segments opacity only
    segmentationDisplayNode.SetAllSegmentsOpacity2DFill(fillRatio, True)

  def onShowVolumeRenderingChanged(self, state):
    if not self.valveModel:
      return

    clippedVolumeNode = self.valveModel.getClippedVolumeNode()
    if not clippedVolumeNode:
      if not state:
        # show is not requested, just return
        return
      self.setupVolumeRendering()
      clippedVolumeNode = self.valveModel.getClippedVolumeNode()

    vrLogic = slicer.modules.volumerendering.logic()
    displayNode = vrLogic.GetFirstVolumeRenderingDisplayNode(clippedVolumeNode)
    if not displayNode:
      if not state:
        # show is not requested, just return
        return
      self.setupVolumeRendering()
      displayNode = vrLogic.GetFirstVolumeRenderingDisplayNode(clippedVolumeNode)

    displayNode.SetVisibility(self.ui.showVolumeRenderingCheckbox.checked)

  def onReload(self):
    logging.debug("Reloading ValveSegmentation")

    packageName = 'HeartValveLib'
    submoduleNames = ['LeafletModel', 'SmoothCurve', 'ValveRoi', 'ValveModel', 'HeartValves']
    import imp
    f, filename, description = imp.find_module(packageName)
    package = imp.load_module(packageName, f, filename, description)
    for submoduleName in submoduleNames:
      f, filename, description = imp.find_module(submoduleName, package.__path__)
      try:
        imp.load_module(packageName + '.' + submoduleName, f, filename, description)
      finally:
        f.close()

    ScriptedLoadableModuleWidget.onReload(self)


#
# ValveSegmentationLogic
#

class ValveSegmentationLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  @staticmethod
  def getLeafletVolumeClippedAxisAligned(valveModel, volumeSpacing=0.3):
    """
    :returns vtkOrientedImageData (defined in the Probe coordinate system) on success. None on failure.
    """
    import vtkSegmentationCorePython as vtkSegmentationCore

    valveVolumeNode = valveModel.getValveVolumeNode()
    if not valveVolumeNode:
      logging.error('createLeafletSegmentationAxisAligned failed: valve volume node is not selected')
      return None

    leafletVolumeClippedAxisAlignedNode = slicer.vtkMRMLScalarVolumeNode()
    leafletVolumeClippedAxisAlignedNode.SetName(slicer.mrmlScene.GetUniqueNameByString("ValveVolumeEdited"))

    # leafletVolumeClippedAxisAlignedNode will be used as a reference volume
    # (that defines the output geometry) and also as output volume
    # (where the resampled input volume is copied to)

    volumeToAxialSlice = vtk.vtkMatrix4x4()
    slicer.vtkMRMLTransformNode.GetMatrixTransformBetweenNodes(valveVolumeNode.GetParentTransformNode(),
                                                               valveModel.getAxialSliceToRasTransformNode(),
                                                               volumeToAxialSlice)

    leafletBounds_AxialSlice = [0, 0, 0, 0, 0, 0]
    clippingEnabled = True
    if clippingEnabled:
      leafletClippingModel = valveModel.getValveRoiModelNode()
      volumeToAxialSliceTransformFilter = vtk.vtkTransformPolyDataFilter()
      volumeToAxialSliceTransformFilter.SetInputConnection(leafletClippingModel.GetPolyDataConnection())
      volumeToAxialSliceTransform = vtk.vtkTransform()
      volumeToAxialSliceTransform.SetMatrix(volumeToAxialSlice)
      volumeToAxialSliceTransformFilter.SetTransform(volumeToAxialSliceTransform)
      volumeToAxialSliceTransformFilter.Update()
      volumeToAxialSliceTransformFilter.GetOutput().GetBounds(leafletBounds_AxialSlice)
    else:
      # volumeBounds_Ijk = [0, -1, 0, -1, 0, -1]
      volumeBounds_Ijk = valveVolumeNode.GetImageData().GetExtent()
      volumeCorners_Ijk = [[volumeBounds_Ijk[0], volumeBounds_Ijk[2], volumeBounds_Ijk[4]],
                           [volumeBounds_Ijk[0], volumeBounds_Ijk[2], volumeBounds_Ijk[5]],
                           [volumeBounds_Ijk[0], volumeBounds_Ijk[3], volumeBounds_Ijk[4]],
                           [volumeBounds_Ijk[0], volumeBounds_Ijk[3], volumeBounds_Ijk[5]],
                           [volumeBounds_Ijk[1], volumeBounds_Ijk[2], volumeBounds_Ijk[4]],
                           [volumeBounds_Ijk[1], volumeBounds_Ijk[2], volumeBounds_Ijk[5]],
                           [volumeBounds_Ijk[1], volumeBounds_Ijk[3], volumeBounds_Ijk[4]],
                           [volumeBounds_Ijk[1], volumeBounds_Ijk[3], volumeBounds_Ijk[5]]]
      ijkToAxialSliceTransform = vtk.vtkTransform()
      valveVolumeIjkToRasMatrix = vtk.vtkMatrix4x4()
      valveVolumeNode.GetIJKToRASMatrix(valveVolumeIjkToRasMatrix)
      ijkToAxialSliceTransform.Concatenate(valveVolumeIjkToRasMatrix)
      ijkToAxialSliceTransform.Concatenate(volumeToAxialSlice)
      leafletBoundingBox_AxialSlice = vtk.vtkBoundingBox()
      for volumeCorner_Ijk in volumeCorners_Ijk:
        volumeCorner_AxialSlice = [0, 0, 0]
        ijkToAxialSliceTransform.TransformPoint(volumeCorner_Ijk, volumeCorner_AxialSlice)
        leafletBoundingBox_AxialSlice.AddPoint(volumeCorner_AxialSlice)
      leafletBoundingBox_AxialSlice.GetBounds(leafletBounds_AxialSlice)

    # leafletVolumeClippedAxisAligned is in the AxialSlice coordinate system
    leafletVolumeClippedAxisAligned = vtkSegmentationCore.vtkOrientedImageData()
    leafletVolumeClippedAxisAligned.SetDimensions(
      int((leafletBounds_AxialSlice[1] - leafletBounds_AxialSlice[0] + 2) / volumeSpacing),
      int((leafletBounds_AxialSlice[3] - leafletBounds_AxialSlice[2] + 2) / volumeSpacing),
      int((leafletBounds_AxialSlice[5] - leafletBounds_AxialSlice[4] + 2) / volumeSpacing))
    leafletVolumeClippedAxisAligned.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    leafletVolumeClippedAxisAligned.SetSpacing(volumeSpacing, volumeSpacing, volumeSpacing)
    leafletVolumeClippedAxisAligned.SetOrigin(leafletBounds_AxialSlice[0] - 1, leafletBounds_AxialSlice[2] - 1,
                                              leafletBounds_AxialSlice[4] - 1)
    volumeToAxialSliceDirections = vtk.vtkMatrix4x4()
    leafletVolumeClippedAxisAligned.SetDirectionMatrix(volumeToAxialSliceDirections)

    axisAlignedVolumeIjkToAxialSlice = vtk.vtkMatrix4x4()
    axisAlignedVolumeIjkToVolume = vtk.vtkMatrix4x4()
    leafletVolumeClippedAxisAligned.GetImageToWorldMatrix(axisAlignedVolumeIjkToAxialSlice)
    axialSliceToVolume = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Invert(volumeToAxialSlice, axialSliceToVolume)
    vtk.vtkMatrix4x4.Multiply4x4(axialSliceToVolume, axisAlignedVolumeIjkToAxialSlice, axisAlignedVolumeIjkToVolume)
    leafletVolumeClippedAxisAligned.SetGeometryFromImageToWorldMatrix(axisAlignedVolumeIjkToVolume)

    segmentationNode = valveModel.getLeafletSegmentationNode()
    segmentationNode.SetAndObserveTransformNodeID(valveVolumeNode.GetParentTransformNode().GetID())

    # self.copySegmentation(valveVolumeNode, leafletVolumeClippedAxisAlignedNode, 'uchar', 'Linear', False)
    vtkSegmentationCore.vtkOrientedImageDataResample.FillImage(leafletVolumeClippedAxisAligned, 1,
                                                               leafletVolumeClippedAxisAligned.GetExtent())

    if clippingEnabled:
      valveModel.valveRoi.clipOrientedImageWithModel(leafletVolumeClippedAxisAligned,
                                                     segmentationNode.GetParentTransformNode(),
                                                     leafletVolumeClippedAxisAligned,
                                                     segmentationNode.GetParentTransformNode())

    # Match window/level of the full volume
    # windowLevelMin = valveVolumeNode.GetDisplayNode().GetWindowLevelMin()
    # windowLevelMax = valveVolumeNode.GetDisplayNode().GetWindowLevelMax()
    # displayNode.SetAutoWindowLevel(False)
    # displayNode.SetWindowLevelMinMax(windowLevelMin, windowLevelMax)

    return leafletVolumeClippedAxisAligned

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)

  def createParameterNode(self):
    # Set default parameters
    node = ScriptedLoadableModuleLogic.createParameterNode(self)
    node.SetName(slicer.mrmlScene.GetUniqueNameByString(self.moduleName))
    return node


class ValveSegmentationTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_ValveSegmentation1()

  def test_ValveSegmentation1(self):
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

    self.delayDisplay("No tests are implemented")