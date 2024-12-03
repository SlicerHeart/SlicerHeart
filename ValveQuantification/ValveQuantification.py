import vtk, qt, ctk, slicer
import HeartValveLib
from slicer.ScriptedLoadableModule import *
import HeartValveLib.SmoothCurve
from ValveQuantificationLib.MeasurementPreset import *
import ValveQuantificationLib

#
# ValveQuantification
#

ThreeDTableViewLayoutId = 1511


class ValveQuantification(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Valve Quantification"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Andras Lasso (PerkLab), Christian Herz (CHOP), Matt Jolley (UPenn)"]
    self.parent.helpText = """
    This is an example of scripted loadable module bundled in an extension.
    It performs a simple thresholding on the input volume and optionally captures a screenshot.
    """
    self.parent.acknowledgementText = """
    This file was originally developed by Andras Lasso, PerkLab.
"""


class ValveQuantificationWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  @staticmethod
  def clearLayout(layout):
    for i in reversed(range(layout.count())):
      widgetToRemove = layout.itemAt(i).widget()
      # get it out of the layout list
      layout.removeWidget(widgetToRemove)
      # remove it form the gui
      if widgetToRemove:
        widgetToRemove.setParent(None)

  @staticmethod
  def reloadPackageWithSubmodules(packageName, submoduleNames):
    import imp
    f, filename, description = imp.find_module(packageName)
    package = imp.load_module(packageName, f, filename, description)
    for submoduleName in submoduleNames:
      f, filename, description = imp.find_module(submoduleName, package.__path__)
      try:
        imp.load_module(packageName + '.' + submoduleName, f, filename, description)
      finally:
        f.close()

  def __init__(self, parent):
    ScriptedLoadableModuleWidget.__init__(self, parent)

    self.logic = ValveQuantificationLogic()

    self.parameterNode = None
    self.parameterNodeObserver = None

    self.annulusLabelsMarkupNodes = []
    self.annulusLabelsMarkupNodeObservers = []

    self.measurementPreset = None

    # Widgets that are dynamically added and removed depending on preset
    self.inputValveNodeLabels = []
    self.inputValveNodeSelectors = []
    self.inputReferenceRequiredCheckBoxes = []
    self.inputReferenceNameLabels = []
    self.inputReferencePointPlaceWidgets = []
    self.inputReferenceResetButtons = []
    self.inputReferenceValueSliders = []

    self.maxNumberPointFields = 10
    self.pointFieldMarkupsNode = []

    self.valueEditWidgets = {}
    self.nodeSelectorWidgets = {}

    self.inputValveModels = {}
    self.inputFieldValues = {}

  def onReload(self):
    print("Reloading ValveQuantification")

    packageName='HeartValveLib'
    submoduleNames=['LeafletModel', 'SmoothCurve', 'ValveModel', 'ValveRoi', 'PapillaryModel', 'CoaptationModel']

    self.reloadPackageWithSubmodules(packageName, submoduleNames)

    packageName='ValveQuantificationLib'
    submoduleNames=['MeasurementPreset',
                    'MeasurementPresetCavc',
                    'MeasurementPresetGenericValve',
                    'MeasurementPresetMitralValve',
                    'MeasurementPresetTricuspidValve',
                    'MeasurementPresetsPapillary',
                    'MeasurementPresetPhaseCompare',
                    'MeasurementPresetLavv']

    self.reloadPackageWithSubmodules(packageName, submoduleNames)

    ScriptedLoadableModuleWidget.onReload(self)

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Create MRML nodes that act as widgets
    # We have to create separate markups node for each point field to be able to activate each
    # point place widget separately.
    markupsLogic = slicer.modules.markups.logic()
    for i in range(self.maxNumberPointFields):
      markupNode = slicer.mrmlScene.GetNodeByID(markupsLogic.AddNewFiducialNode())
      markupNode.SetHideFromEditors(True)
      markupNode.SetAttribute(slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyExcludeFromTreeAttributeName(), "1") # prevent the node from showing up in SH
      markupNode.SetName(slicer.mrmlScene.GetUniqueNameByString("ValveQuantificationPointPlace"+str(i)))
      markupNode.SetSingletonTag("ValveQuantificationPointPlace"+str(i)) # don't delete it if scene is closed
      markupNode.SetSaveWithScene(False)
      markupNode.GetDisplayNode().SetName(slicer.mrmlScene.GetUniqueNameByString("ValveQuantificationPointPlaceDisplay"+str(i)))
      markupNode.GetDisplayNode().SetSingletonTag("ValveQuantificationPointPlace"+str(i)) # don't delete it if scene is closed
      markupNode.GetDisplayNode().SetHideFromEditors(True)
      markupNode.GetDisplayNode().SetSaveWithScene(False)
      markupNode.SetMarkupLabelFormat("") # don't add labels
      self.pointFieldMarkupsNode.append(markupNode)

    valveFormLayout = qt.QFormLayout()
    self.layout.addLayout(valveFormLayout)

    self.setupHeartValveMeasurementSelector(valveFormLayout)
    self.setupValvesSection()
    self.setupFieldsSection()
    self.setupOutputSection()
    self.setupDefinitionsSection()
    self.setupCollapsibleButtonGroup()

    self.valvesCollapsibleButton.setChecked(True)

    # Define list of widgets for updateGUIFromParameterNode, updateParameterNodeFromGUI, and addGUIObservers
    self.valueEditWidgets = {}
    self.nodeSelectorWidgets = {"HeartValveMeasurement": self.heartValveMeasurementSelector}

    # Use singleton parameter node (it is created if does not exist yet)
    parameterNode = self.logic.getParameterNode()
    # Set parameter node (widget will observe it and also updates GUI)
    self.setAndObserveParameterNode(parameterNode)

    self.onHeartValveMeasurementSelect(self.heartValveMeasurementSelector.currentNode())

    self.addGUIObservers()

  def setupHeartValveMeasurementSelector(self, valveFormLayout):
    self.heartValveMeasurementSelector = slicer.qMRMLNodeComboBox()
    self.heartValveMeasurementSelector.nodeTypes = ["vtkMRMLScriptedModuleNode"]
    self.heartValveMeasurementSelector.setNodeTypeLabel("Measurement", "vtkMRMLScriptedModuleNode")
    self.heartValveMeasurementSelector.baseName = "Measurement"
    self.heartValveMeasurementSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", "HeartValveMeasurement")
    self.heartValveMeasurementSelector.addEnabled = True
    self.heartValveMeasurementSelector.removeEnabled = True
    self.heartValveMeasurementSelector.noneEnabled = False
    self.heartValveMeasurementSelector.showHidden = True  # subject hierarchy nodes are hidden by default
    self.heartValveMeasurementSelector.renameEnabled = True
    self.heartValveMeasurementSelector.setMRMLScene(slicer.mrmlScene)
    self.heartValveMeasurementSelector.setToolTip("Select node where heart valve measurement results will be stored in")
    valveFormLayout.addRow("Measurement: ", self.heartValveMeasurementSelector)
    self.heartValveMeasurementSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onHeartValveMeasurementSelect)

  def setupValvesSection(self):
    self.valvesCollapsibleButton = ctk.ctkCollapsibleButton()
    self.valvesCollapsibleButton.objectName = "Valves"
    self.valvesCollapsibleButton.text = "Valves"
    self.layout.addWidget(self.valvesCollapsibleButton)
    self.valvesCollapsibleButton.connect('toggled(bool)',
                                         lambda toggle: self.onWorkflowStepChanged(self.valvesCollapsibleButton,
                                                                                   toggle))
    valvesFormLayout = qt.QFormLayout(self.valvesCollapsibleButton)
    self.presetSelector = qt.QComboBox()
    for preset in self.logic.measurementPresets:
      self.presetSelector.addItem(preset.name, preset.id)
    valvesFormLayout.addRow("Preset", self.presetSelector)
    self.presetSelector.connect('currentIndexChanged(int)', self.onPresetChanged)
    # Input valve selectors will be inserted into this frame
    self.valveSelectorsFrame = qt.QFrame()
    self.valveSelectorsFrame.setFrameShape(qt.QFrame.NoFrame)
    self.valveSelectorsFormLayout = qt.QFormLayout(self.valveSelectorsFrame)
    self.valveSelectorsFormLayout.setContentsMargins(0, 0, 0, 0)
    valvesFormLayout.addRow(self.valveSelectorsFrame)

  def setupFieldsSection(self):
    self.fieldsCollapsibleButton = ctk.ctkCollapsibleButton()
    self.fieldsCollapsibleButton.objectName = "ReferencePoints"
    self.fieldsCollapsibleButton.text = "Reference points"
    self.fieldsCollapsibleButton.setToolTip(
      "Mark reference points in 2D or 3D views.\nHold down Shift key while moving the mouse pointer to synchronize mouse pointer in all views.")
    self.layout.addWidget(self.fieldsCollapsibleButton)
    self.fieldsCollapsibleButton.connect('toggled(bool)',
                                         lambda toggle: self.onWorkflowStepChanged(self.fieldsCollapsibleButton,
                                                                                   toggle))
    fieldsFormLayout = qt.QFormLayout(self.fieldsCollapsibleButton)
    self.inputFieldsCommentLabel = qt.QLabel()
    self.wordWrap = True
    self.inputFieldsCommentLabel.enabled = False  # make it gray
    self.inputFieldsCommentLabel.hide()
    fieldsFormLayout.addRow(self.inputFieldsCommentLabel)
    # Input field editor widgets be inserted into this frame
    self.fieldsWidgetsFrame = qt.QFrame()
    self.fieldsWidgetsFrame.setFrameShape(qt.QFrame.NoFrame)
    self.fieldsWidgetsGridLayout = qt.QGridLayout(self.fieldsWidgetsFrame)
    self.fieldsWidgetsGridLayout.setContentsMargins(0, 0, 0, 0)
    fieldsFormLayout.addRow(self.fieldsWidgetsFrame)

  def setupOutputSection(self):
    self.outputCollapsibleButton = ctk.ctkCollapsibleButton()
    self.outputCollapsibleButton.objectName = "Output"
    self.outputCollapsibleButton.text = "Output"
    self.layout.addWidget(self.outputCollapsibleButton)
    self.outputCollapsibleButton.connect('toggled(bool)',
                                         lambda toggle: self.onWorkflowStepChanged(self.outputCollapsibleButton,
                                                                                   toggle))
    outputFormLayout = qt.QFormLayout(self.outputCollapsibleButton)
    self.computeStatusTextEdit = qt.QPlainTextEdit()
    self.computeStatusTextEdit.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
    self.computeStatusTextEdit.maximumHeight = 75
    outputFormLayout.addRow(self.computeStatusTextEdit)
    self.measurementTree = slicer.qMRMLSubjectHierarchyTreeView()
    self.measurementTree.setMRMLScene(slicer.mrmlScene)
    qSize = qt.QSizePolicy()
    qSize.setHorizontalPolicy(qt.QSizePolicy.MinimumExpanding)
    qSize.setVerticalPolicy(qt.QSizePolicy.MinimumExpanding)
    qSize.setVerticalStretch(1)
    self.measurementTree.setSizePolicy(qSize)
    self.measurementTree.setColumnHidden(self.measurementTree.model().idColumn, True)
    self.measurementTree.setColumnHidden(self.measurementTree.model().transformColumn, True)
    outputFormLayout.addRow(self.measurementTree)

  def setupDefinitionsSection(self):
    self.definitionsCollapsibleButton = ctk.ctkCollapsibleButton()
    self.definitionsCollapsibleButton.objectName = "Definitions"
    self.definitionsCollapsibleButton.text = "Definitions"
    self.definitionsCollapsibleButton.collapsed = False
    self.layout.addWidget(self.definitionsCollapsibleButton)
    definitionsFormLayout = qt.QGridLayout(self.definitionsCollapsibleButton)
    self.definitionsWidget = slicer.qSlicerWebWidget()
    definitionsFormLayout.addWidget(self.definitionsWidget)

  def setupCollapsibleButtonGroup(self):
    """" Making sure only one collapsible button is open at a time."""
    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.valvesCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.fieldsCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.outputCollapsibleButton)

  def cleanup(self):
    self.removeGUIObservers()
    self.setAndObserveParameterNode(None)

    for i in range(self.maxNumberPointFields):
      markupsNode = self.pointFieldMarkupsNode[i]
      slicer.mrmlScene.RemoveNode(markupsNode)

  def setGuiEnabled(self, enable):
    self.valvesCollapsibleButton.setEnabled(enable)
    self.fieldsCollapsibleButton.setEnabled(enable)
    self.outputCollapsibleButton.setEnabled(enable)

  def setAndObserveParameterNode(self, parameterNode):
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
      self.parameterNodeObserver = self.parameterNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onParameterNodeModified)
    # Update GUI
    self.updateGUIFromParameterNode()

  def getParameterNode(self):
    return self.parameterNode

  def onParameterNodeModified(self, observer, eventid):
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self):
    parameterNode = self.getParameterNode()
    if not parameterNode:
      return
    for parameterName in self.valueEditWidgets:
      oldBlockSignalsState = self.valueEditWidgets[parameterName].blockSignals(True)
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName=="QCheckBox":
        checked = (int(parameterNode.GetParameter(parameterName)) != 0)
        self.valueEditWidgets[parameterName].setChecked(checked)
      elif widgetClassName=="QSpinBox":
        self.valueEditWidgets[parameterName].setValue(float(parameterNode.GetParameter(parameterName)))
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
      if widgetClassName=="QCheckBox":
        if self.valueEditWidgets[parameterName].checked:
          parameterNode.SetParameter(parameterName, "1")
        else:
          parameterNode.SetParameter(parameterName, "0")
      elif widgetClassName=="QSpinBox":
        parameterNode.SetParameter(parameterName, str(self.valueEditWidgets[parameterName].value))
      else:
        raise Exception("Unexpected widget class: {0}".format(widgetClassName))
    for parameterName in self.nodeSelectorWidgets:
      parameterNode.SetNodeReferenceID(parameterName, self.nodeSelectorWidgets[parameterName].currentNodeID)
    parameterNode.EndModify(oldModifiedState)

  def addGUIObservers(self):
    for parameterName in self.valueEditWidgets:
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName=="QSpinBox":
        self.valueEditWidgets[parameterName].connect("valueChanged(int)", self.updateParameterNodeFromGUI)
      elif widgetClassName=="QCheckBox":
        self.valueEditWidgets[parameterName].connect("clicked()", self.updateParameterNodeFromGUI)
    for parameterName in self.nodeSelectorWidgets:
      self.nodeSelectorWidgets[parameterName].connect("currentNodeIDChanged(QString)", self.updateParameterNodeFromGUI)

  def removeGUIObservers(self):
    for parameterName in self.valueEditWidgets:
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName=="QSpinBox":
        self.valueEditWidgets[parameterName].disconnect("valueChanged(int)", self.updateParameterNodeFromGUI)
      elif widgetClassName=="QCheckBox":
        self.valueEditWidgets[parameterName].disconnect("clicked()", self.updateParameterNodeFromGUI)
    for parameterName in self.nodeSelectorWidgets:
      self.nodeSelectorWidgets[parameterName].disconnect("currentNodeIDChanged(QString)", self.updateParameterNodeFromGUI)

  def onHeartValveMeasurementSelect(self, node):
    logging.debug("Selected heart valve measurement node: {0}".format(node.GetName() if node else "None"))
    self.setHeartValveMeasurementNode(node)

  def setHeartValveMeasurementNode(self, heartValveMeasurementNode):
    if heartValveMeasurementNode:
      index = self.presetSelector.findData(self.logic.getMeasurementPresetId(heartValveMeasurementNode))
      self._configureMeasurementTree(heartValveMeasurementNode)
    else:
      index = -1
      self.measurementTree.visible = False

    self.presetSelector.setCurrentIndex(index)
    self.setGuiEnabled(heartValveMeasurementNode is not None)
    self.computeStatusTextEdit.plainText = ""

    self.onPresetChanged()

  def getHeartValveMeasurementNode(self):
    return self.heartValveMeasurementSelector.currentNode()

  def _configureMeasurementTree(self, heartValveMeasurementNode):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    if heartValveMeasurementNode.GetHideFromEditors():
      heartValveMeasurementNode.SetHideFromEditors(False)
      shNode.RequestOwnerPluginSearch(heartValveMeasurementNode)
      shNode.SetItemAttribute(shNode.GetItemByDataNode(heartValveMeasurementNode), "ModuleName",
                              "HeartValveMeasurement")
    self.measurementTree.setRootItem(shNode.GetSceneItemID())
    self.measurementTree.visible = True
    self.measurementTree.setRootItem(shNode.GetItemByDataNode(heartValveMeasurementNode))

  def setDefinitionUrl(self, url):
    if self.definitionsWidget:
      self.definitionsWidget.webView().url = url

  def onPresetChanged(self, presetIndex=-1):
    slicer.presetSelector = self.presetSelector
    presetId = self.presetSelector.itemData(self.presetSelector.currentIndex)
    heartValveMeasurementNode = self.getHeartValveMeasurementNode()
    if heartValveMeasurementNode:
      heartValveMeasurementNode.SetAttribute('MeasurementPreset', presetId if presetId else "")
    self.measurementPreset = self.logic.getMeasurementPresetById(presetId)

    # Hide all valve node selectors and field selectors
    for widget in self.inputValveNodeLabels + self.inputValveNodeSelectors + \
        self.inputReferenceRequiredCheckBoxes + self.inputReferenceNameLabels + \
        self.inputReferencePointPlaceWidgets + self.inputReferenceResetButtons + \
        self.inputReferenceValueSliders + [self.inputFieldsCommentLabel]:
      widget.hide()

    if not self.measurementPreset:
      self.setDefinitionUrl(qt.QUrl())
      return

    if self.definitionsWidget.url != self.measurementPreset.definitionsUrl:
      self.setDefinitionUrl(qt.QUrl(self.measurementPreset.definitionsUrl))

    if self.measurementPreset.inputFieldsComment:
      self.inputFieldsCommentLabel.text = self.measurementPreset.inputFieldsComment
      self.inputFieldsCommentLabel.show()

    # Add new valve selectors (reuse/hide cached selectors and labels,
    # as removing widgets from the layout is very tricky)
    inputValveIds = self.measurementPreset.inputValveIds
    for inputValveIndex in range(len(inputValveIds)):
      if inputValveIndex >= len(self.inputValveNodeSelectors):
        valveLabel = qt.QLabel()
        valveSelector = slicer.qMRMLNodeComboBox()
        valveSelector.nodeTypes = ["vtkMRMLScriptedModuleNode"]
        valveSelector.setNodeTypeLabel("HeartValve", "vtkMRMLScriptedModuleNode")
        valveSelector.addAttribute( "vtkMRMLScriptedModuleNode", "ModuleName", "HeartValve" )
        valveSelector.addEnabled = False
        valveSelector.removeEnabled = True
        valveSelector.noneEnabled = True
        valveSelector.showHidden = True # scripted module nodes are hidden by default
        valveSelector.renameEnabled = True
        valveSelector.setMRMLScene(slicer.mrmlScene)
        valveSelector.setToolTip("Select heart valve")
        self.valveSelectorsFormLayout.addRow(valveLabel, valveSelector)
        self.inputValveNodeLabels.append(valveLabel)
        self.inputValveNodeSelectors.append(valveSelector)
        self.annulusLabelsMarkupNodes.append(None)
        self.annulusLabelsMarkupNodeObservers.append([])
        valveSelector.connect("currentNodeChanged(vtkMRMLNode*)",
          lambda valveNode, inputValveIndex=inputValveIndex: self.onValveNodeSelect(inputValveIndex, valveNode))
      else:
        valveLabel = self.inputValveNodeLabels[inputValveIndex]
        valveSelector = self.inputValveNodeSelectors[inputValveIndex]
      valveLabel.text = self.measurementPreset.inputValveNames[inputValveIds[inputValveIndex]]
      valveLabel.show()
      heartValveMeasurementNode = self.getHeartValveMeasurementNode()
      valveNode = heartValveMeasurementNode.GetNodeReference('Valve'+inputValveIds[inputValveIndex])
      valveSelector.setCurrentNode(valveNode)
      self.onValveNodeSelect(inputValveIndex, valveNode)
      valveSelector.show()

    # Add field selectors (reuse/hide cached widgets, as removing widgets from the layout is very tricky)
    inputFields = self.measurementPreset.inputFields
    self.inputFieldValues = {}

    self.fieldsCollapsibleButton.enabled = len(inputFields) != 0

    for inputFieldIndex in range(len(inputFields)):

      # Get widgets
      if inputFieldIndex >= len(self.inputReferenceRequiredCheckBoxes):
        # need to add a new field
        requiredCheckBox = qt.QCheckBox()
        nameLabel = qt.QLabel()
        pointPlaceWidget = slicer.qSlicerMarkupsPlaceWidget()
        pointPlaceWidget.setButtonsVisible(False)
        pointPlaceWidget.placeButton().show()
        pointPlaceWidget.setMRMLScene(slicer.mrmlScene)
        pointPlaceWidget.placeMultipleMarkups = slicer.qSlicerMarkupsPlaceWidget.ForcePlaceSingleMarkup
        pointPlaceWidget.connect('activeMarkupsFiducialPlaceModeChanged(bool)',
          lambda enable, inputFieldIndex=inputFieldIndex: self.onReferencePointMarkupPlace(inputFieldIndex, enable))
        resetButton = qt.QPushButton("Reset")
        resetButton.connect('clicked()',
          lambda inputFieldIndex=inputFieldIndex: self.onFieldValueReset(inputFieldIndex))
        valueSlider = ctk.ctkSliderWidget()
        valueSlider.connect('valueChanged(double)',
          lambda value, inputFieldIndex=inputFieldIndex: self.onInputFieldValueChanged(inputFieldIndex, value))
        self.fieldsWidgetsGridLayout.addWidget(requiredCheckBox, inputFieldIndex, 0)
        self.fieldsWidgetsGridLayout.addWidget(nameLabel, inputFieldIndex, 1)
        # Put the pointPlaceWidget and resetButton in the same grid cell, as either one or the other is shown
        hFrame = qt.QFrame()
        hBoxLayout = qt.QHBoxLayout()
        hFrame.setLayout(hBoxLayout)
        pointPlaceWidget.hide() # only one of widgets will be shown
        resetButton.hide() # only one of widgets will be shown
        hBoxLayout.addWidget(pointPlaceWidget)
        hBoxLayout.addWidget(resetButton)
        resetButton.checked = True # to be in sync with enabled status of other widgets
        requiredCheckBox.connect('toggled(bool)', resetButton, 'setEnabled(bool)')
        requiredCheckBox.connect('toggled(bool)', valueSlider, 'setEnabled(bool)')
        requiredCheckBox.connect('toggled(bool)',
          lambda enable, inputFieldIndex=inputFieldIndex: self.onFieldValueEnabled(inputFieldIndex, enable))
        self.fieldsWidgetsGridLayout.addWidget(hFrame, inputFieldIndex, 2)
        self.fieldsWidgetsGridLayout.addWidget(valueSlider, inputFieldIndex, 3)
        self.inputReferenceRequiredCheckBoxes.append(requiredCheckBox)
        self.inputReferenceNameLabels.append(nameLabel)
        self.inputReferencePointPlaceWidgets.append(pointPlaceWidget)
        self.inputReferenceResetButtons.append(resetButton)
        self.inputReferenceValueSliders.append(valueSlider)
      else:
        requiredCheckBox = self.inputReferenceRequiredCheckBoxes[inputFieldIndex]
        nameLabel = self.inputReferenceNameLabels[inputFieldIndex]
        pointPlaceWidget = self.inputReferencePointPlaceWidgets[inputFieldIndex]
        resetButton = self.inputReferenceResetButtons[inputFieldIndex]
        valueSlider = self.inputReferenceValueSliders[inputFieldIndex]

      sliderWasBlocked = valueSlider.blockSignals(True)
      checkBoxWasBlocked = requiredCheckBox.blockSignals(True)

      field = inputFields[inputFieldIndex]
      fieldType = field[FIELD_TYPE]
      required = FIELD_REQUIRED in field.keys() and field[FIELD_REQUIRED]
      requiredCheckBox.show()
      if fieldType == FIELD_TYPE_POINT:
        # Reference point
        valveId = field[FIELD_VALVE_ID]
        valveModel = self.inputValveModels[valveId] if valveId in self.inputValveModels.keys() else None
        pointPositionAnnulus = valveModel.getAnnulusMarkupPositionByLabel(field[FIELD_NAME]) if valveModel else None

        requiredCheckBox.checked = pointPositionAnnulus is not None
        requiredCheckBox.enabled = True

        nameLabel.text = field[FIELD_NAME] + ' point'
        nameLabel.show()

        pointPlaceWidget.setCurrentNode(self.pointFieldMarkupsNode[inputFieldIndex])
        pointPlaceWidget.enabled = True
        pointPlaceWidget.show()

        if valveId:
          # point is constrained to the annulus contour, show slider to allow adjustment
          if pointPositionAnnulus is not None:
            [_, closestPointIdOnAnnulusCurve] = valveModel.annulusContourCurve.getClosestPoint(pointPositionAnnulus)
            pointDistanceAlongCurve = valveModel.annulusContourCurve.getCurveLength(closestPointIdOnAnnulusCurve)
            valueSlider.minimum = pointDistanceAlongCurve-20
            valueSlider.maximum = pointDistanceAlongCurve+20
            valueSlider.value = pointDistanceAlongCurve
          else:
            valueSlider.minimum = 0
            valueSlider.maximum = 0
            valueSlider.value = 0
          valueSlider.singleStep = 0.1
          valueSlider.pageStep = 1.0
          valueSlider.suffix = 'mm'
          valueSlider.enabled = requiredCheckBox.checked
          valueSlider.show()
      elif fieldType == FIELD_TYPE_SCALAR:
        requiredCheckBox.checked = required
        requiredCheckBox.enabled = not required
        # Reference value
        nameLabel.text = field[FIELD_NAME]
        nameLabel.show()
        resetButton.show()
        resetButton.enabled = required
        valueSlider.minimum = field[FIELD_MIN_VALUE]
        valueSlider.maximum = field[FIELD_MAX_VALUE]
        valueSlider.value = field[FIELD_DEFAULT_VALUE]
        if required:
          self.inputFieldValues[field[FIELD_ID]] = valueSlider.value
        valueSlider.singleStep = field[FIELD_STEP_SIZE]
        valueSlider.pageStep = valueSlider.singleStep*5
        valueSlider.suffix = field[KEY_UNIT]
        valueSlider.enabled = required
        valueSlider.show()

      valueSlider.blockSignals(sliderWasBlocked)
      requiredCheckBox.blockSignals(checkBoxWasBlocked)

  def onValveNodeSelect(self, inputValveIndex, valveNode):
    # Remove observers to old labels markup node
    if self.annulusLabelsMarkupNodes[inputValveIndex] and self.annulusLabelsMarkupNodeObservers[inputValveIndex]:
      for observer in self.annulusLabelsMarkupNodeObservers[inputValveIndex]:
        self.annulusLabelsMarkupNodes[inputValveIndex].RemoveObserver(observer)
      self.annulusLabelsMarkupNodes[inputValveIndex] = None
      self.annulusLabelsMarkupNodeObservers[inputValveIndex] = []

    if not self.measurementPreset:
      return
    inputValveIds = self.measurementPreset.inputValveIds

    # Store selected valve
    if valveNode:
      valveModel = HeartValveLib.HeartValves.getValveModel(valveNode)
      self.inputValveModels[inputValveIds[inputValveIndex]] = valveModel
    else:
      valveModel = None
      self.inputValveModels.pop(inputValveIds[inputValveIndex], None)
    heartValveMeasurementNode = self.getHeartValveMeasurementNode()
    if heartValveMeasurementNode:
      heartValveMeasurementNode.SetNodeReferenceID('Valve'+inputValveIds[inputValveIndex], valveNode.GetID() if valveNode else None)

    # Set and observe new labels markup node
    labelsMarkupNode = valveModel.getAnnulusLabelsMarkupNode() if valveModel else None
    self.annulusLabelsMarkupNodes[inputValveIndex] = labelsMarkupNode
    if labelsMarkupNode:
      self.annulusLabelsMarkupNodeObservers[inputValveIndex].append(
        labelsMarkupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                                     lambda caller, event, valveId=inputValveIds[inputValveIndex]:
                                     self.onAnnulusLabelMarkupModified(valveId)))

  def onAnnulusLabelMarkupModified(self, valveId):
    if not self.measurementPreset:
      return

    # TODO: update GUI from MRML in one method (currently in onPresetChanged, onAnnulusLabelMarkupModified, onInputFieldValueChanged)

    # Update GUI from label markups (markup points may have been added or deleted)
    inputFields = self.measurementPreset.inputFields
    for inputFieldIndex in range(len(inputFields)):
      field = inputFields[inputFieldIndex]
      if field[FIELD_TYPE] != FIELD_TYPE_POINT:
        continue
      if FIELD_VALVE_ID not in field.keys():
        continue
      if valveId != field[FIELD_VALVE_ID]:
        continue

      positionSlider = self.inputReferenceValueSliders[inputFieldIndex]
      if positionSlider.hasFocus():
        # the user adjusting point position using this slider right now
        continue

      valveModel = self.inputValveModels[valveId]
      pointPositionAnnulus = valveModel.getAnnulusMarkupPositionByLabel(field[FIELD_NAME])
      if pointPositionAnnulus is None:
        # landmark is not present
        if positionSlider.minimum != positionSlider.maximum:
          sliderWasBlocked = positionSlider.blockSignals(True)
          positionSlider.minimum = 0
          positionSlider.maximum = 0
          positionSlider.value = 0
          positionSlider.blockSignals(sliderWasBlocked)
      else:
        # landmark is present
        if positionSlider.minimum == positionSlider.maximum:
          # Previously it was not present, update slider
          [_, closestPointIdOnAnnulusCurve] = valveModel.annulusContourCurve.getClosestPoint(pointPositionAnnulus)
          pointDistanceAlongCurve = valveModel.annulusContourCurve.getCurveLength(closestPointIdOnAnnulusCurve)
          wasBlocked = positionSlider.blockSignals(True)
          positionSlider.minimum = pointDistanceAlongCurve-20
          positionSlider.maximum = pointDistanceAlongCurve+20
          positionSlider.value = pointDistanceAlongCurve
          positionSlider.blockSignals(wasBlocked)
          requiredCheckBox = self.inputReferenceRequiredCheckBoxes[inputFieldIndex]
          if not requiredCheckBox.checked:
            requiredCheckBox.checked = True

  def updateOutput(self):

    # Compute metrics and populate the output table
    heartValveMeasurementNode = self.getHeartValveMeasurementNode()

    messages = self.logic.computeMetrics(heartValveMeasurementNode)

    self.computeStatusTextEdit.plainText = '\n'.join(messages)

    # Not sure why but it seems that the initial hiding of columns has no effect and we have to
    # repeat it here.
    self.measurementTree.setColumnHidden(self.measurementTree.model().idColumn, True)
    self.measurementTree.setColumnHidden(self.measurementTree.model().transformColumn, True)

    self.measurementTree.resizeColumnToContents(0)

  def onReferencePointMarkupPlace(self, fieldIndex, enable):
    # Get markup label
    field = self.measurementPreset.inputFields[fieldIndex]

    useSlicer413api = hasattr(slicer.vtkMRMLMarkupsFiducialNode,'RemoveAllControlPoints')

    # Get valve model from selected valve node
    valveId = field[FIELD_VALVE_ID]
    if not valveId in self.inputValveModels.keys():
      logging.error('onReferencePointMarkupPlace failed: no {0} valve node is selected'.format(valveId))
      if useSlicer413api:
        qt.QTimer.singleShot(0, self.pointFieldMarkupsNode[fieldIndex].RemoveAllControlPoints)
      else:
        qt.QTimer.singleShot(0, self.pointFieldMarkupsNode[fieldIndex].RemoveAllMarkups)
      return
    valveModel = self.inputValveModels[valveId]

    label = field[FIELD_NAME]
    if enable:
      # Point placement activated - remove old markup
      valveModel.removeAnnulusMarkupLabel(label)
      if useSlicer413api:
        self.pointFieldMarkupsNode[fieldIndex].RemoveAllControlPoints()
      else:
        self.pointFieldMarkupsNode[fieldIndex].RemoveAllMarkups()
    else:
      # Point placement completed add new markup on the contour
      if self.pointFieldMarkupsNode[fieldIndex].GetNumberOfMarkups()==0:
        # duplicate update event
        return

      # Get point from temporary markup node
      pointPositionWorld = [0,0,0]
      self.pointFieldMarkupsNode[fieldIndex].GetNthControlPointPositionWorld(0,pointPositionWorld)

      if useSlicer413api:
        qt.QTimer.singleShot(0, self.pointFieldMarkupsNode[fieldIndex].RemoveAllControlPoints)
      else:
        qt.QTimer.singleShot(0, self.pointFieldMarkupsNode[fieldIndex].RemoveAllMarkups)

      # Add label on closest point on contour
      worldToProbeTransform = vtk.vtkGeneralTransform()
      valveModel.getProbeToRasTransformNode().GetTransformFromWorld(worldToProbeTransform)
      pointPositionAnnulus = worldToProbeTransform.TransformDoublePoint(pointPositionWorld[0:3])

      if field[FIELD_ON_ANNULUS_CONTOUR] is True:
        [closestPointOnAnnulusCurve, _] = valveModel.annulusContourCurve.getClosestPoint(pointPositionAnnulus)
        pointPosition = closestPointOnAnnulusCurve
      else:
        # NB: no snapping or restriction
        pointPosition = pointPositionAnnulus

      valveModel.setAnnulusMarkupLabel(label, pointPosition)
      self.measurementPreset.onInputFieldChanged(field[FIELD_ID], self.inputValveModels, self.inputFieldValues, computeDependentValues=True)

  def onInputFieldValueChanged(self, fieldIndex, value):
    if not self.fieldsCollapsibleButton.checked:
      return
    field = self.measurementPreset.inputFields[fieldIndex]
    if field[FIELD_TYPE]==FIELD_TYPE_POINT:
      valveModel = self.inputValveModels[field[FIELD_VALVE_ID]]
      if value is not None:
        updatedPointPos = valveModel.annulusContourCurve.getPointAlongCurve(value)
        valveModel.setAnnulusMarkupLabel(field[FIELD_NAME], updatedPointPos)
      else:
        valveModel.removeAnnulusMarkupLabel(field[FIELD_NAME])
    else:
      self.inputFieldValues[field[FIELD_ID]] = value
    self.measurementPreset.onInputFieldChanged(field[FIELD_ID], self.inputValveModels, self.inputFieldValues)

  def onFieldValueEnabled(self, inputFieldIndex, enable):
    if not self.fieldsCollapsibleButton.checked:
      return
    field = self.measurementPreset.inputFields[inputFieldIndex]

    if field[FIELD_TYPE] == FIELD_TYPE_POINT:
      valveModel = self.inputValveModels[field[FIELD_VALVE_ID]]
      if enable:
        pointPositionAnnulus = valveModel.getAnnulusMarkupPositionByLabel(field[FIELD_NAME])
        if pointPositionAnnulus is None:
          # Give a chance to compute this value automatically
          self.measurementPreset.onResetInputField(field[FIELD_ID], self.inputValveModels, self.inputFieldValues)
          pointPositionAnnulus = valveModel.getAnnulusMarkupPositionByLabel(field[FIELD_NAME])
          if pointPositionAnnulus is None:
            # landmark is not present, add it
            pointPos = valveModel.annulusContourCurve.getPointAlongCurve(0)
            valveModel.setAnnulusMarkupLabel(field[FIELD_NAME], pointPos)
            positionSlider = self.inputReferenceValueSliders[inputFieldIndex]
            sliderWasBlocked = positionSlider.blockSignals(True)
            positionSlider.minimum = 0
            positionSlider.maximum = valveModel.annulusContourCurve.getCurveLength()
            positionSlider.value = 0
            positionSlider.blockSignals(sliderWasBlocked)
            self.onInputFieldValueChanged(inputFieldIndex, 0)
        else:
          # TODO: initialize slider
          pass
      else:
        self.onInputFieldValueChanged(inputFieldIndex, None) # remove

    elif field[FIELD_TYPE] == FIELD_TYPE_SCALAR:
      if enable:
        self.onInputFieldValueChanged(inputFieldIndex, self.inputReferenceValueSliders[inputFieldIndex].value)
      else:
        self.onInputFieldValueChanged(inputFieldIndex, None)

  def onFieldValueReset(self, inputFieldIndex):
    field = self.measurementPreset.inputFields[inputFieldIndex]
    self.inputReferenceValueSliders[inputFieldIndex].setValue(field[FIELD_DEFAULT_VALUE])
    self.measurementPreset.onResetInputField(field[FIELD_ID], self.inputValveModels, self.inputFieldValues)

  def onWorkflowStepChanged(self, widget, toggle):
    if toggle:
      if widget==self.valvesCollapsibleButton:
        layoutManager = slicer.app.layoutManager()
        layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
        HeartValveLib.showSlices(False)
      elif widget==self.fieldsCollapsibleButton:
        HeartValveLib.setupDefaultLayout()
        HeartValveLib.showSlices(False)
        self.measurementPreset.onInputFieldChanged(None, self.inputValveModels, self.inputFieldValues)
      elif widget==self.outputCollapsibleButton:
        self.updateOutput()


class ValveQuantificationLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  measurementPresets = [ValveQuantificationLib.MeasurementPresetCavc(),
                        ValveQuantificationLib.MeasurementPresetGenericValve(),
                        ValveQuantificationLib.MeasurementPresetMitralValve(),
                        ValveQuantificationLib.MeasurementPresetTricuspidValve(),
                        ValveQuantificationLib.MeasurementPresetPapillaryMitralValve(),
                        ValveQuantificationLib.MeasurementPresetPapillaryTricuspidValve(),
                        ValveQuantificationLib.MeasurementPresetPapillaryCavc(),
                        ValveQuantificationLib.MeasurementPresetPapillaryLAVValve(),
                        ValveQuantificationLib.MeasurementPresetLavv(),
                        ValveQuantificationLib.MeasurementPresetPhaseCompare()]

  @classmethod
  def registerPreset(cls, preset):
    if all(isinstance(p, preset) is False for p in cls.measurementPresets):
      cls.measurementPresets.append(preset())
    else:
      logging.warning("Preset %s is already registered" % str(preset))

  @staticmethod
  def getPointProjectedToAnnularPlane(valveModel, pointPosition):
    import numpy as np
    annulusPlanePosition, annulusPlaneNormal = valveModel.getAnnulusContourPlane()
    point2D = np.zeros([3, 1])
    point2D[:, 0] = np.array(pointPosition)
    pointsArrayProjected_World, _, _ = HeartValveLib.getPointsProjectedToPlane(point2D, annulusPlanePosition,
                                                                               annulusPlaneNormal)
    return pointsArrayProjected_World[:, 0]

  @staticmethod
  def getMeasurementPresetId(heartValveMeasurementNode):
    return heartValveMeasurementNode.GetAttribute('MeasurementPreset')

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)

  def getPresetNames(self):
    presetNames = []
    for preset in self.measurementPresets:
      presetNames.append(preset.name)
    return presetNames

  def getMeasurementPresetById(self, presetId):
    for preset in self.measurementPresets:
      if preset.id == presetId:
        return preset
    return None

  def getMeasurementPresetByMeasurementNode(self, measurementNode):
    presetId = self.getMeasurementPresetId(measurementNode)
    if not presetId:
      return None
    return self.getMeasurementPresetById(presetId)

  def computeMetrics(self, heartValveMeasurementNode):
    slicer.app.pauseRender()
    try:
      measurementPreset = self.getMeasurementPreset(heartValveMeasurementNode)
      messages = measurementPreset.computeMetricsForMeasurementNode(heartValveMeasurementNode)
    finally:
      slicer.app.resumeRender()
    return messages

  def getMeasurementPreset(self, heartValveMeasurementNode):
    measurementPresetId = self.getMeasurementPresetId(heartValveMeasurementNode)
    measurementPreset = self.getMeasurementPresetById(measurementPresetId)
    return measurementPreset

  def getMeasurementCardiacCyclePhaseShortNames(self, heartValveMeasurementNode):
    phaseShortNames = []
    measurementPreset = self.getMeasurementPreset(heartValveMeasurementNode)
    for inputValveId in measurementPreset.inputValveIds:
      heartValveNode = heartValveMeasurementNode.GetNodeReference('Valve' + inputValveId)
      if not heartValveNode:
        # this valve is not specified
        continue
      valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)
      cardiacCyclePhasePreset = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]
      phaseShortNames.append(cardiacCyclePhasePreset['shortname'])
    # Make elements unique, keeping order
    from collections import OrderedDict
    phaseShortNames = list(OrderedDict.fromkeys(phaseShortNames))
    return phaseShortNames


class ValveQuantificationTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    pass

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_ValveQuantificationMitral()

  def getHeartValveNode(self, nameFragment):
    """Find heart valve node in the scene that contins the specified name fragment in its name"""

    for scriptedModuleNode in slicer.util.getNodesByClass('vtkMRMLScriptedModuleNode'):
      if scriptedModuleNode.GetAttribute("ModuleName") != "HeartValve":
        continue
      if nameFragment not in scriptedModuleNode.GetName():
        continue
      # Found
      return scriptedModuleNode

    # Not found
    return None


  def test_ValveQuantificationMitral(self):

    self.delayDisplay("Start test_ValveQuantificationMitral.")

    presetName = "Mitral valve"

    mitralValveNode = self.getHeartValveNode("Mitral")
    self.assertIsNotNone(mitralValveNode)

    aorticValveNode = self.getHeartValveNode("Aortic")
    self.assertIsNotNone(aorticValveNode)

    valveNodes = [mitralValveNode, aorticValveNode]

    # Obtained by copying AnnulusLabelsMarkup points from markups module's control points table,
    # using only the point label and coordinates values.
    referencePoints = [["A", [-94.850341796875, -76.15013122558594, 104.09174346923828], 93.2],
                       ["P", [-113.81173706054688, -100.89620971679688, 96.8191146850586], None],
                       ["PM", [-88.52909851074219, -95.75225830078125, 95.63932800292969], 16.6],
                       ["AL", [-116.85599517822266, -81.13494110107422, 92.84961700439453], None]]

    self.runSingleCase(presetName, valveNodes, referencePoints)

  def runSingleCase(self, presetName, valveNodes, referencePoints):

    valveQuantificationGui = slicer.modules.ValveQuantificationWidget

    self.delayDisplay("Create new measurement.")
    measurementNode = valveQuantificationGui.heartValveMeasurementSelector.addNode()
    valveQuantificationGui.heartValveMeasurementSelector.setCurrentNode(measurementNode)

    self.delayDisplay("Select measurement type.")
    valveQuantificationGui.presetSelector.currentText = presetName

    self.delayDisplay("Select input valves.")
    for nodeSelectorIndex, heartValveNode in enumerate(valveNodes):
      valveQuantificationGui.inputValveNodeSelectors[nodeSelectorIndex].setCurrentNode(heartValveNode)

    self.delayDisplay("Set reference points.")
    valveQuantificationGui.fieldsCollapsibleButton.collapsed = False
    for pointLabel, pointCoordinate, sliderPosition in referencePoints:
      self.delayDisplay(f"Define reference point {pointLabel}")

      # Find reference point index
      foundPoint = False
      for pointIndex in range(len(valveQuantificationGui.inputReferenceNameLabels)):
        if valveQuantificationGui.inputReferenceNameLabels[pointIndex].text == f"{pointLabel} point":
          foundPoint = True
          break
      self.assertTrue(foundPoint, f"Reference point {pointLabel} not found")

      #valveQuantificationGui.inputReferenceRequiredCheckBoxes[pointIndex].checked = True
      slicer.app.processEvents()
      valveQuantificationGui.inputReferenceRequiredCheckBoxes[pointIndex].click()
      slicer.app.processEvents()
      if sliderPosition is not None:
        valveQuantificationGui.inputReferenceValueSliders[pointIndex].value = sliderPosition

      #valveQuantificationGui.inputReferencePointPlaceWidgets = []
      #valveQuantificationGui.inputReferenceResetButtons = []
      #valveQuantificationGui.inputReferenceValueSliders[pointIndex].value += 5 + pointIndex * 0.3

      # slicer.modules.ValveQuantificationWidget.inputReferenceRequiredCheckBoxes[0].click()
      # slicer.modules.ValveQuantificationWidget.inputReferenceValueSliders[0].value = 93

    self.delayDisplay("Compute results.")
    valveQuantificationGui.outputCollapsibleButton.collapsed = False

    self.delayDisplay("Completed test_ValveQuantificationMitral.")
