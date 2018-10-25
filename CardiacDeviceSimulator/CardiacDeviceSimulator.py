import os
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
from CardiacDeviceSimulatorUtils.devices import *
from CardiacDeviceSimulatorUtils.helpers import UIHelper

#
# CardiacDeviceSimulator
#


class CardiacDeviceSimulator(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Cardiac device simulator"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Andras Lasso (PerkLab), Christian Herz (CHOP), Matt Jolley (UPenn)"]
    self.parent.helpText = """
    Create various models (stents, valves, etc) related to cardiac procedures.
    """
    self.parent.acknowledgementText = """
    This file was originally developed by Andras Lasso, PerkLab.
    """

#
# CardiacDeviceSimulatorWidget
#


class CardiacDeviceSimulatorWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  registeredDeviceClasses = [HarmonyDevice, CylinderDevice]

  @staticmethod
  def registerDevice(deviceClass):
    """Register a subclass of CardiacDeviceBase for additional measurements cardiac device models"""
    if not issubclass(deviceClass, CardiacDeviceBase):
      return
    if not deviceClass in CardiacDeviceSimulatorWidget.registeredDeviceClasses:
      CardiacDeviceSimulatorWidget.registeredDeviceClasses.append(deviceClass)

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    self.sliceSelectorSliderWidget = None

    self.logic = CardiacDeviceSimulatorLogic()
    self.updateMethod = None

    self.addGeneralSection()
    self.addVesselCenterlineSection()
    self.addDevicePositionSection()
    self.addDeviceDeformationSection()
    self.addQuantificationSection()

    if not hasattr(slicer.modules, 'volumereslicedriver'):
      slicer.util.messageBox("This modules requires SlicerIGT extension. Install SlicerIGT and restart Slicer.")
      self.parameterNodeSelector.setEnabled(False)

    if not hasattr(slicer.modules, 'markupstomodel'):
      slicer.util.messageBox("This modules requires MarkupsToModel extension. Install MarkupsToModel and restart Slicer.")
      self.parameterNodeSelector.setEnabled(False)

    defaultNode = slicer.mrmlScene.GetFirstNodeByName("CardiacDevice")
    if defaultNode:
      self.parameterNodeSelector.setCurrentNode(defaultNode)

    self.updateSliceSelectorWidget()
    self.updateButtonStates()

  def addGeneralSection(self):
    self.commonButtonsGroup = qt.QButtonGroup()
    self.commonButtonsGroup.connect("buttonToggled(int,bool)", self.onCommonSectionToggled)

    [lay, self.generalSection] = UIHelper.addCommonSection("General", self.layout, self.commonButtonsGroup,
                                                           collapsed=False)

    self.parameterNodeSelector = slicer.qMRMLNodeComboBox()
    self.parameterNodeSelector.nodeTypes = ["vtkMRMLScriptedModuleNode"]
    self.parameterNodeSelector.setNodeTypeLabel("CardiacDevice", "vtkMRMLScriptedModuleNode")
    self.parameterNodeSelector.baseName = "CardiacDevice"
    self.parameterNodeSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", "CardiacDeviceAnalysis")
    self.parameterNodeSelector.addEnabled = True
    self.parameterNodeSelector.removeEnabled = True
    self.parameterNodeSelector.noneEnabled = True
    self.parameterNodeSelector.showHidden = True  # scripted module nodes are hidden by default
    self.parameterNodeSelector.renameEnabled = True
    self.parameterNodeSelector.setMRMLScene(slicer.mrmlScene)
    self.parameterNodeSelector.setToolTip("Node referencing to all generated nodes")
    lay.addRow("Parameter node: ", self.parameterNodeSelector)
    self.parameterNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onParameterNodeSelectionChanged)

    self.handlesPerSliceSliderWidget = UIHelper.addSlider({
      "name": "Handles per slice:", "info": "Controls how many handles are generated for device deformation",
      "value": 8, "unit": "", "minimum": 4, "maximum": 12, "singleStep": 1, "pageStep": 1, "decimals": 0}, lay,
      self.onHandlesSettingsChanged)

    self.handlesSpacingSliderWidget = UIHelper.addSlider({
      "name": "Handles spacing:", "info": "Controls distance between handles", "value": 5, "unit": "mm", "minimum": 3,
      "maximum": 15, "singleStep": 1, "pageStep": 1, "decimals": 0}, lay, self.onHandlesSettingsChanged)

    self.addDeviceWidgets(lay)

  def addDeviceWidgets(self, lay):
    self.collapsibleButtonsGroup = qt.QButtonGroup()
    for deviceClass in self.registeredDeviceClasses:
      deviceWidget = CardiacDeviceWidget(deviceClass, self.logic, self.updateSliceSelectorWidget)
      lay.addWidget(deviceWidget)
      self.collapsibleButtonsGroup.addButton(deviceWidget)
      deviceWidget.connect('toggled(bool)', lambda toggle, name=deviceClass.NAME: self.onSwitchSection(name, toggle))

  def addVesselCenterlineSection(self):
    [lay, self.centerlineSection] = UIHelper.addCommonSection("Vessel centerline", self.layout, self.commonButtonsGroup,
                                                              collapsed=True)

    self.vesselSegmentSelector = slicer.qMRMLSegmentSelectorWidget()
    self.vesselSegmentSelector.setMRMLScene(slicer.mrmlScene)
    self.vesselSegmentSelector.setToolTip("Select vessel lumen (blood) segment. The segment must be a solid, filled "
                                          "model of the blood (not a shell).")
    lay.addRow("Vessel lumen: ", self.vesselSegmentSelector)
    self.vesselSegmentSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onVesselLumenSegmentSelectionChanged)
    self.vesselSegmentSelector.connect("currentSegmentChanged(QString)", self.onVesselLumenSegmentSelectionChanged)

    # Button to position device at closest centerline point
    self.processVesselSegmentButton = qt.QPushButton("Detect vessel centerline")
    self.processVesselSegmentButton.setToolTip("Extract centerline and lumen surface from vessel segment")
    lay.addRow(self.processVesselSegmentButton)
    self.processVesselSegmentButton.connect('clicked(bool)', self.onProcessVesselSegmentClicked)
    self.processVesselSegmentButton.enabled = False

  def addDevicePositionSection(self):
    [lay, self.devicePositionSection] = UIHelper.addCommonSection("Device position", self.layout,
                                                                  self.commonButtonsGroup, collapsed=True)
    # Centerline model selector
    self.centerlineModelNodeSelector = slicer.qMRMLNodeComboBox()
    self.centerlineModelNodeSelector.nodeTypes = ["vtkMRMLModelNode"]
    self.centerlineModelNodeSelector.setNodeTypeLabel("Centerline", "vtkMRMLModelNode")
    self.centerlineModelNodeSelector.baseName = "Centerline"
    self.centerlineModelNodeSelector.selectNodeUponCreation = False
    self.centerlineModelNodeSelector.addEnabled = False
    self.centerlineModelNodeSelector.removeEnabled = False
    self.centerlineModelNodeSelector.noneEnabled = True
    self.centerlineModelNodeSelector.showHidden = True
    self.centerlineModelNodeSelector.renameEnabled = True
    self.centerlineModelNodeSelector.setMRMLScene(slicer.mrmlScene)
    self.centerlineModelNodeSelector.setToolTip( "select the extracted centerline model to be used for positioning "
                                                 "the device")
    lay.addRow("Centerline model node: ", self.centerlineModelNodeSelector)
    self.centerlineModelNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)",
                                             self.onCenterlineModelNodeSelectionChanged)

    # Button to position device at closest centerline point
    self.positionDeviceAtCenterlineButton = qt.QPushButton("Position device at centerline")
    lay.addRow(self.positionDeviceAtCenterlineButton)
    self.positionDeviceAtCenterlineButton.connect('clicked(bool)', self.onPositionDeviceAtCenterlineClicked)
    self.positionDeviceAtCenterlineButton.enabled = False

    # Button to flip device orientation
    self.flipDeviceOrientationButton = qt.QPushButton("Flip device orientation")
    lay.addRow(self.flipDeviceOrientationButton)
    self.flipDeviceOrientationButton.connect('clicked(bool)', self.onFlipDeviceOrientationClicked)
    self.flipDeviceOrientationButton.enabled = False

    # Pick centerline model
    self.moveDeviceAlongCenterlineSliderWidget = UIHelper.addSlider({
      "name": "Move device along centerline:", "info": "Moves the device along extracted centerline", "value": 0,
      "unit": "", "minimum": 0, "maximum": 100, "singleStep": 0.1, "pageStep": 1, "decimals": 1}, lay,
      self.onMoveDeviceAlongCenterlineSliderChanged)
    self.moveDeviceAlongCenterlineSliderWidget.enabled = False

    # Position
    self.devicePositioningPositionSliderWidget = slicer.qMRMLTransformSliders()
    self.devicePositioningPositionSliderWidget.Title = 'Device position'
    self.devicePositioningPositionSliderWidget.TypeOfTransform = slicer.qMRMLTransformSliders.TRANSLATION
    self.devicePositioningPositionSliderWidget.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL
    self.devicePositioningPositionSliderWidget.setMRMLScene(slicer.mrmlScene)
    self.devicePositioningPositionSliderWidget.setMRMLTransformNode(None)
    self.devicePositioningPositionSliderWidget.findChildren(ctk.ctkCollapsibleGroupBox)[0].setChecked(False)
    lay.addRow(self.devicePositioningPositionSliderWidget)

    # Orientation
    self.devicePositioningOrientationSliderWidget = slicer.qMRMLTransformSliders()
    self.devicePositioningOrientationSliderWidget.Title = 'Device orientation'
    self.devicePositioningOrientationSliderWidget.setMRMLScene(slicer.mrmlScene)
    # Setting of qMRMLTransformSliders.TypeOfTransform is not robust: it has to be set after setMRMLScene and
    # has to be set twice (with setting the type to something else in between).
    # Therefore the following 3 lines are needed, and needed here:
    self.devicePositioningOrientationSliderWidget.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    self.devicePositioningOrientationSliderWidget.TypeOfTransform = slicer.qMRMLTransformSliders.TRANSLATION
    self.devicePositioningOrientationSliderWidget.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    self.devicePositioningOrientationSliderWidget.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL
    self.devicePositioningOrientationSliderWidget.minMaxVisible = False
    self.devicePositioningOrientationSliderWidget.setMRMLTransformNode(None)
    self.devicePositioningOrientationSliderWidget.findChildren(ctk.ctkCollapsibleGroupBox)[0].setChecked(False)
    lay.addRow(self.devicePositioningOrientationSliderWidget)

  def addDeviceDeformationSection(self):
    # self.createClosedSegmentsForAlreadyFittedDeviceButton = qt.QPushButton("Create closed segments for already fitted Harmony TCPV valve (temporary?)")
    # #lay.addRow(self.createClosedSegmentsForAlreadyFittedDeviceButton)
    # self.createClosedSegmentsForAlreadyFittedDeviceButton.connect('clicked(bool)', self.onCreateClosedSegmentsForAlreadyFittedHarmonyDevice)

    [lay, self.deviceDeformationSection] = UIHelper.addCommonSection("Device deformation", self.layout,
                                                                     self.commonButtonsGroup, collapsed=True)
    # Vessel model selector
    self.vesselModelNodeSelector = slicer.qMRMLNodeComboBox()
    self.vesselModelNodeSelector.nodeTypes = ["vtkMRMLModelNode"]
    self.vesselModelNodeSelector.setNodeTypeLabel("Vessel", "vtkMRMLModelNode")
    self.vesselModelNodeSelector.baseName = "Vessel"
    self.vesselModelNodeSelector.selectNodeUponCreation = False
    self.vesselModelNodeSelector.addEnabled = False
    self.vesselModelNodeSelector.removeEnabled = False
    self.vesselModelNodeSelector.noneEnabled = True
    self.vesselModelNodeSelector.showHidden = True
    self.vesselModelNodeSelector.renameEnabled = True
    self.vesselModelNodeSelector.setMRMLScene(slicer.mrmlScene)
    self.vesselModelNodeSelector.setToolTip("select the extracted centerline model to be used for positioning the device")
    lay.addRow("Vessel model node: ", self.vesselModelNodeSelector)
    self.vesselModelNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onVesselModelNodeSelectionChanged)

    # Radio button to choose whether to allow device expansion to fit vessel walls (some devices cannot be expanded beyond their native size, they can only be compressed
    self.allowDeviceExpansionToVesselWallsCheckbox = qt.QCheckBox()
    self.allowDeviceExpansionToVesselWallsCheckbox.setToolTip(
      "Some devices cannot be expanded beyond their native size in the vessel; they can only be compressed.")
    self.allowDeviceExpansionToVesselWallsCheckbox.setChecked(False)
    lay.addRow("Allow device to expand to vessel walls", self.allowDeviceExpansionToVesselWallsCheckbox)

    # Button to deform device to vessel walls
    self.deformDeviceToVesselWallsButton = qt.QPushButton("Fit device to vessel wall")
    lay.addRow(self.deformDeviceToVesselWallsButton)

    self.deformDeviceToVesselWallsButton.connect('clicked(bool)', self.onDeformDeviceToVesselWallsClicked)
    self.deformDeviceToVesselWallsButton.enabled = False
    self.sliceSelectorSliderWidget = UIHelper.addSlider({
      "name": "Slice:", "info": "Jumps to a slice containing handles", "value": 0,
      "unit": "", "minimum": 0, "maximum": 0, "singleStep": 1, "pageStep": 1, "decimals": 0}, lay,
      self.onSliceSelected)

    orthogonalSlicerRotationBox = qt.QHBoxLayout()
    lay.addRow(orthogonalSlicerRotationBox)
    self.previousSliceButton = qt.QPushButton()
    self.previousSliceButton.text = "<"
    self.previousSliceButton.setToolTip("Jump to previous slice. Keyboard shortcut: 'z'")
    orthogonalSlicerRotationBox.addWidget(self.previousSliceButton)
    self.previousSliceButton.connect('clicked(bool)', self.onPreviousSlice)

    self.nextSliceButton = qt.QPushButton()
    self.nextSliceButton.text = ">"
    self.nextSliceButton.setToolTip("Jump to next slice. Keyboard shortcut: 'x'")
    orthogonalSlicerRotationBox.addWidget(self.nextSliceButton)
    self.nextSliceButton.connect('clicked(bool)', self.onNextSlice)

  def addQuantificationSection(self):
    [lay, self.quantificationSection] = UIHelper.addCommonSection("Quantification", self.layout,
                                                                  self.commonButtonsGroup)
    self.colorTableRangeMmSliderWidget = UIHelper.addSlider({
      "name": "Color table range:", "info": "Maximum compression represented in the color table", "value": 10,
      "unit": "mm", "minimum": 0, "maximum": 20, "singleStep": 1, "pageStep": 1, "decimals": 0}, lay,
      self.onColorTableRangeChanged)
    self.computeMetricsButton = qt.QPushButton("Compute metrics")
    lay.addRow(self.computeMetricsButton)
    self.computeMetricsButton.connect('clicked(bool)', self.onComputeMetrics)
    self.measurementTree = slicer.qMRMLSubjectHierarchyTreeView()
    self.measurementTree.setMRMLScene(slicer.mrmlScene)
    qSize = qt.QSizePolicy()
    qSize.setHorizontalPolicy(qt.QSizePolicy.Expanding)
    qSize.setVerticalPolicy(qt.QSizePolicy.MinimumExpanding)
    qSize.setVerticalStretch(1)
    self.measurementTree.setSizePolicy(qSize)
    # self.measurementTree.editMenuActionVisible = True
    self.measurementTree.setColumnHidden(self.measurementTree.model().idColumn, True)
    self.measurementTree.setColumnHidden(self.measurementTree.model().transformColumn, True)
    # lay.addRow(self.measurementTree)
    self.layout.addWidget(self.measurementTree)

  def cleanup(self):
    pass

  def enter(self):
    """Runs whenever the module is reopened
    """
    self.installShortcutKeys()

  def exit(self):
    self.removeShortcutKeys()

  def installShortcutKeys(self):
    logging.debug('installShortcutKeys')
    self.shortcuts = []
    keysAndCallbacks = (
      ('z', self.onPreviousSlice),
      ('x', self.onNextSlice)
      )
    for key,callback in keysAndCallbacks:
      shortcut = qt.QShortcut(slicer.util.mainWindow())
      shortcut.setKey( qt.QKeySequence(key) )
      shortcut.connect( 'activated()', callback )
      self.shortcuts.append(shortcut)

  def removeShortcutKeys(self):
    logging.debug('removeShortcutKeys')
    for shortcut in self.shortcuts:
      shortcut.disconnect('activated()')
      shortcut.setParent(None)
    self.shortcuts = []

  def onParameterNodeSelectionChanged(self):

    self.logic.setParameterNode(self.parameterNodeSelector.currentNode())
    if self.logic.parameterNode:
      self.setupResliceDriver()

      self.colorTableRangeMmSliderWidget.value = float(self.logic.parameterNode.GetParameter("ColorTableRangeMm"))

      positioningTransform = self.logic.parameterNode.GetNodeReference('PositioningTransform')
      self.devicePositioningPositionSliderWidget.setMRMLTransformNode(positioningTransform)
      self.devicePositioningOrientationSliderWidget.setMRMLTransformNode(positioningTransform)
      self.vesselModelNodeSelector.setCurrentNode(self.logic.getVesselModelNode())
      self.centerlineModelNodeSelector.setCurrentNode(self.logic.getCenterlineModelNode())

      [vesselLumenSegmentationNode, vesselLumenSegmentId] = self.logic.getVesselLumenSegment()
      self.vesselSegmentSelector.setCurrentNode(vesselLumenSegmentationNode)
      self.vesselSegmentSelector.setCurrentSegmentID(vesselLumenSegmentId)

      wasBlocked = self.handlesPerSliceSliderWidget.blockSignals(True)
      self.handlesPerSliceSliderWidget.value = self.logic.getHandlesPerSlice()
      self.handlesPerSliceSliderWidget.blockSignals(wasBlocked)
      wasBlocked = self.handlesSpacingSliderWidget.blockSignals(True)
      self.handlesSpacingSliderWidget.value = self.logic.getHandlesSpacingMm()
      self.handlesSpacingSliderWidget.blockSignals(wasBlocked)

      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      parameterNodeShItem = shNode.GetItemByDataNode(self.logic.parameterNode)
      self.measurementTree.setRootItem(parameterNodeShItem)

    self.updateButtonStates()

  def updateButtonStates(self):
    guiEnabled = self.logic.parameterNode is not None
    for guiSection in [self.centerlineSection, self.devicePositionSection, self.deviceDeformationSection, self.quantificationSection]:
      guiSection.enabled = guiEnabled
    self.positionDeviceAtCenterlineButton.enabled = self.centerlineModelNodeSelector.currentNode() is not None
    self.flipDeviceOrientationButton.enabled = self.centerlineModelNodeSelector.currentNode() is not None
    self.moveDeviceAlongCenterlineSliderWidget.enabled = self.centerlineModelNodeSelector.currentNode() is not None
    if self.vesselModelNodeSelector.currentNode():
      self.deformDeviceToVesselWallsButton.enabled = True
    self.processVesselSegmentButton.enabled = (self.vesselSegmentSelector.currentNode() is not None)

  def onCommonSectionToggled(self, index, toggled):
    if self.quantificationSection.checked:
      # TODO: hie the expanding spacer if quantification section is open
      pass

  def onVesselLumenSegmentSelectionChanged(self):
    self.logic.setVesselLumenSegment(self.vesselSegmentSelector.currentNode(), self.vesselSegmentSelector.currentSegmentID())
    self.updateButtonStates()

  def onCenterlineModelNodeSelectionChanged(self):
    self.logic.setCenterlineModelNode(self.centerlineModelNodeSelector.currentNode())
    self.updateButtonStates()

  def onVesselModelNodeSelectionChanged(self):
    self.logic.setVesselModelNode(self.vesselModelNodeSelector.currentNode())
    self.updateButtonStates()

  def onProcessVesselSegmentClicked(self):
    if slicer.app.majorVersion == 4 and slicer.app.minorVersion <= 8:
      slicer.util.messageBox("Vessel centerline extraction requires Slicer 4.9 or later.")
      return
    self.logic.processVesselSegment()
    self.vesselModelNodeSelector.setCurrentNode(self.logic.getVesselModelNode())
    self.centerlineModelNodeSelector.setCurrentNode(self.logic.getCenterlineModelNode())
    [vesselLumenSegmentationNode, vesselLumenSegmentId] = self.logic.getVesselLumenSegment()
    # hide segment to make the semi-transparent vessel surface visible instead
    vesselLumenSegmentationNode.GetDisplayNode().SetVisibility(0)

  def onPositionDeviceAtCenterlineClicked(self):
    self.moveDeviceAlongCenterlineSliderWidget.enabled = self.centerlineModelNodeSelector.currentNode()

    logging.debug("positioning device at centerline endpoint")
    deviceCenter = self.logic.getDeviceCenter()
    closestPointID = self.logic.getClosestPointIDOnCenterline(deviceCenter)

    # calculate and adjust slider value
    centerlinePolyData = self.logic.getCenterlineModelNode().GetPolyData()
    centerlineVtkPoints = centerlinePolyData.GetPoints()
    numCenterlineVtkPoints = centerlineVtkPoints.GetNumberOfPoints()
    sliderValue = int(round((closestPointID * 100.0) / numCenterlineVtkPoints))
    self.moveDeviceAlongCenterlineSliderWidget.setValue(sliderValue)

    # position device at closest centerline point (based on current centre of device)
    self.logic.alignDeviceWithCenterlineDirection(closestPointID)

  def onFlipDeviceOrientationClicked(self):
    logging.debug("flipped device orientation")
    if not self.logic.deviceOrientationFlipped:
      self.logic.deviceOrientationFlipped = True
    else:
      self.logic.deviceOrientationFlipped = False

    # adjust device position
    self.onPositionDeviceAtCenterlineClicked()

  def onDeformDeviceToVesselWallsClicked(self):
    logging.debug("moving device handles to deform to vessel walls...")
    self.logic.deformHandlesToVesselWalls(self.allowDeviceExpansionToVesselWallsCheckbox.isChecked())

  def onMoveDeviceAlongCenterlineSliderChanged(self):

    sliderValue = self.moveDeviceAlongCenterlineSliderWidget.value
    self.logic.moveDeviceBasedOnSlider(sliderValue)

  def onComputeMetrics(self):
    if not self.logic.parameterNode:
      return

    qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
    tableNode = self.logic.computeMetrics()
    qt.QApplication.restoreOverrideCursor()

    # Show table
    #slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView)
    #slicer.app.applicationLogic().GetSelectionNode().SetReferenceActiveTableID(tableNode.GetID())
    #slicer.app.applicationLogic().PropagateTableSelection()

    # Show deformed surface model
    resultModel = self.logic.parameterNode.GetNodeReference("WholeDeformedSurfaceModel")
    resultModel.GetDisplayNode().SetVisibility(True)

    # Not sure why but it seems that the initial hiding of columns has no effect and we have to
    # repeat it here.
    self.measurementTree.setColumnHidden(self.measurementTree.model().idColumn, True)
    self.measurementTree.setColumnHidden(self.measurementTree.model().transformColumn, True)

  def onColorTableRangeChanged(self):
    if self.logic.parameterNode:
      self.logic.parameterNode.SetParameter("ColorTableRangeMm", str(self.colorTableRangeMmSliderWidget.value))

  def onSliceSelected(self):
    if not self.logic.parameterNode:
      return
    sliceNumber = int(self.sliceSelectorSliderWidget.value)
    fiducialNumber = sliceNumber
    handleMarkupsNodeId = self.logic.parameterNode.GetNodeReference('DeformedHandles').GetID()
    centered = False
    slicer.modules.markups.logic().JumpSlicesToNthPointInMarkup(handleMarkupsNodeId, fiducialNumber, centered)

  def onPreviousSlice(self):
    sliceNumber = int(self.sliceSelectorSliderWidget.value)-1
    if sliceNumber >= self.sliceSelectorSliderWidget.minimum:
      self.sliceSelectorSliderWidget.value = sliceNumber

  def onNextSlice(self):
    sliceNumber = int(self.sliceSelectorSliderWidget.value) + 1
    if sliceNumber <= self.sliceSelectorSliderWidget.maximum:
      self.sliceSelectorSliderWidget.value = sliceNumber

  def setupResliceDriver(self):
    if not self.logic.parameterNode:
      return
    resliceLogic = slicer.modules.volumereslicedriver.logic()
    resliceConfig = [
      ('vtkMRMLSliceNodeRed', resliceLogic.MODE_TRANSVERSE),
      ('vtkMRMLSliceNodeGreen', resliceLogic.MODE_INPLANE),
      ('vtkMRMLSliceNodeYellow', resliceLogic.MODE_INPLANE90)]
    for nodeName, resliceMode in resliceConfig:
      sliceNode = slicer.mrmlScene.GetNodeByID(nodeName)
      resliceLogic.SetDriverForSlice(self.logic.parameterNode.GetNodeReference('PositioningTransform').GetID(), sliceNode)
      resliceLogic.SetModeForSlice(resliceMode, sliceNode)

  def onSwitchSection(self, name, toggle):
    if not toggle:
      return
    self.logic.setModelType(name)
    self.updateSliceSelectorWidget()
    self.sliceSelectorSliderWidget.value = 0
    self.onSliceSelected() # force update, even if value is already 0

  def updateSliceSelectorWidget(self):
    if self.sliceSelectorSliderWidget is None:
      return
    numberOfSlices = self.logic.handleProfilePoints.GetNumberOfPoints()-1
    if numberOfSlices>0:
      self.sliceSelectorSliderWidget.maximum = numberOfSlices
      self.sliceSelectorSliderWidget.setEnabled(True)
    else:
      self.sliceSelectorSliderWidget.maximum = 0
      self.sliceSelectorSliderWidget.setEnabled(False)

  def onHandlesSettingsChanged(self):
    self.logic.setHandlesSettings(int(self.handlesPerSliceSliderWidget.value), self.handlesSpacingSliderWidget.value)
    self.updateSliceSelectorWidget()


#
# CardiacDeviceSimulatorLogic
#

class CardiacDeviceSimulatorLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual computation done by your module. The interface should be such that
  other python code can import this class and make use of the functionality without requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    ScriptedLoadableModuleLogic.__init__(self, parent)

    self.interpolatorType = 'KochanekSpline' # Valid options: 'CardinalSpline', 'SCurveSpline', 'KochanekSpline'

    self.parameterNode = None

    self.deviceOrientationFlipped = False

    self.handleProfilePoints = vtk.vtkPoints()
    self.handlesPerSlice = 4
    self.handlesSpacingMm = 5

    self.modelInfo = {}

    self.modelType = HarmonyDevice.NAME

  def setParameterNode(self, parameterNode):
    self.parameterNode = parameterNode
    if not self.parameterNode:
      return

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    if self.parameterNode.GetHideFromEditors():
      self.parameterNode.SetHideFromEditors(False)
      shNode.RequestOwnerPluginSearch(self.parameterNode)
      parameterNodeShItem = shNode.GetItemByDataNode(self.parameterNode)
      shNode.SetItemAttribute(parameterNodeShItem, "ModuleName", "CardiacDeviceAnalysis")
    else:
      parameterNodeShItem = shNode.GetItemByDataNode(self.parameterNode)

    if not self.parameterNode.GetParameter('ColorTableRangeMm'):
      self.parameterNode.SetParameter('ColorTableRangeMm', "10.0")

    if not self.parameterNode.GetParameter('NumberOfProfilePoints'):
      self.setNumberOfProfilePoints(50)
    if not self.parameterNode.GetParameter('NumberOfModelPointsPerSlice'):
      self.setNumberOfModelPointsPerSlice(60)

    handlesPerSlice = 8
    handlesSpacingMm = 5.0

    if not self.parameterNode.GetParameter('HandlesPerSlice'):
      originalHandlesNode = self.parameterNode.GetNodeReference("OriginalHandles")
      if originalHandlesNode:
        handlesPerSlice = 1
        # this is a legacy scene where this parameter was not saved as a parameter - compute it now
        # by getting the number of points that are in the same slice
        firstHandlePointPos = [0, 0, 0]
        originalHandlesNode.GetNthFiducialPosition(0, firstHandlePointPos)
        for fidIndex in range(1, originalHandlesNode.GetNumberOfFiducials()):
          currentHandlePointPos = [0, 0, 0]
          originalHandlesNode.GetNthFiducialPosition(fidIndex, currentHandlePointPos)
          if fidIndex==1:
            handlesSpacingMm = abs(firstHandlePointPos[2]-currentHandlePointPos[2])
          if abs(firstHandlePointPos[2]-currentHandlePointPos[2]) < 0.1:
            handlesPerSlice += 1

    if not self.parameterNode.GetParameter('HandlesPerSlice'):
      self.setHandlesPerSlice(handlesPerSlice)
    if not self.parameterNode.GetParameter('HandlesSpacingMm'):
      self.setHandlesSpacingMm(handlesSpacingMm)

    transformationFolderShItem = shNode.GetItemChildWithName(parameterNodeShItem, "Transformation")
    if not transformationFolderShItem:
      transformationFolderShItem = shNode.CreateFolderItem(parameterNodeShItem, "Transformation")
      shNode.SetItemExpanded(transformationFolderShItem, False)

    if not self.parameterNode.GetNodeReference('PositioningTransform'):
      n = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "PositioningTransform")

      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      shNode.SetItemParent(shNode.GetItemByDataNode(n), transformationFolderShItem)

      # set positioningMatrix to center of yellow slice (device will appear here)
      yellowSlice = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeYellow')
      sliceToRas = yellowSlice.GetSliceToRAS()
      x = sliceToRas.GetElement(0, 3)
      y = sliceToRas.GetElement(1, 3)
      z = sliceToRas.GetElement(2, 3)

      positioningMatrix = vtk.vtkMatrix4x4()
      positioningMatrix.Identity()
      positioningMatrix.SetElement(0, 3, x)
      positioningMatrix.SetElement(1, 3, y)
      positioningMatrix.SetElement(2, 3, z)

      n.SetMatrixTransformToParent(positioningMatrix)
      self.parameterNode.SetNodeReferenceID('PositioningTransform', n.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(n), transformationFolderShItem)

    if not self.parameterNode.GetNodeReference('DeformingTransform'):
      n = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", "DeformingTransform")
      n.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      self.parameterNode.SetNodeReferenceID('DeformingTransform', n.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(n), transformationFolderShItem)

    if not self.parameterNode.GetNodeReference('OriginalModel'):
      n = self.createModelNode('OriginalModel', [1,0,0])
      dn = n.GetDisplayNode()
      dn.SetRepresentation(dn.WireframeRepresentation)
      n.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      self.parameterNode.SetNodeReferenceID('OriginalModel', n.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(n), parameterNodeShItem)

    if not self.parameterNode.GetNodeReference('DeformedModel'):
      n = self.createModelNode('DeformedModel', [0.5,0.5,1.0])
      n.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('DeformingTransform').GetID())
      self.parameterNode.SetNodeReferenceID('DeformedModel', n.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(n), parameterNodeShItem)

    if not self.parameterNode.GetNodeReference('DisplacementToColorNode'):
      n = slicer.mrmlScene.CreateNodeByClass("vtkMRMLProceduralColorNode")
      n.UnRegister(None)
      n.SetName(slicer.mrmlScene.GenerateUniqueName("Radial compression (mm)"))
      n.SetAttribute("Category", "CardiacDeviceSimulator")
      # The color node is a procedural color node, which is saved using a storage node.
      # Hidden nodes are not saved if they use a storage node, therefore
      # the color node must be visible.
      n.SetHideFromEditors(False)
      slicer.mrmlScene.AddNode(n)
      self.parameterNode.SetNodeReferenceID('DisplacementToColorNode', n.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(n), parameterNodeShItem)

    if not self.parameterNode.GetNodeReference('OriginalHandles'):
      n = self.createMarkupsNode('OriginalHandles', [1, 0, 0])
      n.GetDisplayNode().SetVisibility(0)
      n.GetDisplayNode().SetTextScale(0)
      n.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      self.parameterNode.SetNodeReferenceID('OriginalHandles', n.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(n), transformationFolderShItem)

    if not self.parameterNode.GetNodeReference('DeformedHandles'):
      n = self.createMarkupsNode('DeformedHandles', [0.5,0.5,1.0])
      n.GetDisplayNode().SetTextScale(0)
      n.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      self.parameterNode.SetNodeReferenceID('DeformedHandles', n.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(n), transformationFolderShItem)

    if not self.parameterNode.GetNodeReference('FiducialRegistrationNode'):
      n = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLFiducialRegistrationWizardNode")
      n.SetRegistrationModeToWarping()
      # compute ToParent transform, to make model transformation faster and more accurate
      # (computed ToParent is computed directly, not by inverting FromParent)
      try:
        n.WarpingTransformFromParentOff()
      except AttributeError:
        pass
      n.SetAndObserveFromFiducialListNodeId(self.parameterNode.GetNodeReference('OriginalHandles').GetID())
      n.SetAndObserveToFiducialListNodeId(self.parameterNode.GetNodeReference('DeformedHandles').GetID())
      n.SetOutputTransformNodeId(self.parameterNode.GetNodeReference('DeformingTransform').GetID())
      self.parameterNode.SetNodeReferenceID('FiducialRegistrationNode', n.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(n), transformationFolderShItem)

    # if probeToRasTransform is set, set to identity matrix (probeToRas matrix is not needed for RVOT positioning)
    positioningTransformNode = self.parameterNode.GetNodeReference('PositioningTransform')
    probeToRasTransformNode = slicer.mrmlScene.GetFirstNodeByName("ProbeToRasTransform")
    if (probeToRasTransformNode is not None) and positioningTransformNode.GetTransformNodeID():

      # first apply the inverse of probeToRas to positioning transform
      probeToRasMatrix = vtk.vtkMatrix4x4()
      probeToRasTransformNode.GetMatrixTransformToWorld(probeToRasMatrix)

      rasToProbeMatrix = vtk.vtkMatrix4x4()
      rasToProbeMatrix.DeepCopy(probeToRasMatrix)
      rasToProbeMatrix.Invert()

      positioningTransformNode = self.parameterNode.GetNodeReference('PositioningTransform')
      positioningTransformNode.ApplyTransformMatrix(rasToProbeMatrix)

      # set probeToRas transform to identity
      identityMatrix = vtk.vtkMatrix4x4()
      probeToRasTransformNode.SetMatrixTransformFromParent(identityMatrix)

      # reset slice views and 3d views (to refocus on RVOT model)
      manager = slicer.app.layoutManager()
      manager.resetSliceViews()
      manager.resetThreeDViews()

  def getQuantificationResultsFolderShItem(self, subfolderName=None):
    if not self.parameterNode:
      return None
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    parameterNodeShItem = shNode.GetItemByDataNode(self.parameterNode)
    quantificationResultsFolderShItem = shNode.GetItemChildWithName(parameterNodeShItem, "Quantification results")
    if not quantificationResultsFolderShItem:
      quantificationResultsFolderShItem = shNode.CreateFolderItem(parameterNodeShItem, "Quantification results")
    if not subfolderName:
      return quantificationResultsFolderShItem
    subfolderShItem = shNode.GetItemChildWithName(quantificationResultsFolderShItem, subfolderName)
    if not subfolderShItem:
      subfolderShItem = shNode.CreateFolderItem(quantificationResultsFolderShItem, subfolderName)
    return subfolderShItem

  def getNumberOfProfilePoints(self):
    return int(self.parameterNode.GetParameter('NumberOfProfilePoints'))

  def getNumberOfModelPointsPerSlice(self):
    return int(self.parameterNode.GetParameter('NumberOfModelPointsPerSlice'))

  def getHandlesPerSlice(self):
    return int(self.parameterNode.GetParameter('HandlesPerSlice'))

  def getHandlesSpacingMm(self):
    return float(self.parameterNode.GetParameter('HandlesSpacingMm'))

  def setNumberOfProfilePoints(self, n):
    self.parameterNode.SetParameter('NumberOfProfilePoints', str(n))

  def setNumberOfModelPointsPerSlice(self, n):
    self.parameterNode.SetParameter('NumberOfModelPointsPerSlice', str(n))

  def setHandlesPerSlice(self, n):
    self.parameterNode.SetParameter('HandlesPerSlice', str(n))

  def setHandlesSpacingMm(self, n):
    self.parameterNode.SetParameter('HandlesSpacingMm', str(n))

  def setCenterlineModelNode(self, centerlineModelNode):
    if not self.parameterNode:
      return
    self.parameterNode.SetNodeReferenceID("CenterlineModel", centerlineModelNode.GetID() if centerlineModelNode else None)

  def getCenterlineModelNode(self):
    return self.parameterNode.GetNodeReference("CenterlineModel")

  def setVesselLumenSegment(self, vesselLumenSegmentationNode, vesselLumenSegmentId):
    if not self.parameterNode:
      return
    self.parameterNode.SetNodeReferenceID("VesselLumenSegmentation", vesselLumenSegmentationNode.GetID() if vesselLumenSegmentationNode else None)
    self.parameterNode.SetAttribute("VesselLumenSegmentID", vesselLumenSegmentId)

  def getVesselLumenSegment(self):
    if not self.parameterNode:
      return
    vesselLumenSegmentationNode = self.parameterNode.GetNodeReference("VesselLumenSegmentation")
    vesselLumenSegmentId = self.parameterNode.GetAttribute("VesselLumenSegmentID")
    return [vesselLumenSegmentationNode, vesselLumenSegmentId]

  def setVesselModelNode(self, vesselModelNode):
    if not self.parameterNode:
      return
    self.parameterNode.SetNodeReferenceID("VesselModel", vesselModelNode.GetID() if vesselModelNode else None)

  def getVesselModelNode(self):
    return self.parameterNode.GetNodeReference("VesselModel")

  def setModelType(self, modelType):
    self.modelType = modelType
    self.updateModel()

  def setHandlesSettings(self, handlesPerSlice, handlesSpacingMm):
    if handlesPerSlice == self.getHandlesPerSlice() and handlesSpacingMm == self.getHandlesSpacingMm():
      return
    self.setHandlesPerSlice(handlesPerSlice)
    self.setHandlesSpacingMm(handlesSpacingMm)
    self.updateModel()

  def setModelParameters(self, modelType, params):
    self.modelInfo[modelType]['parameters'] = params
    if self.parameterNode:
      modelTypeId = modelType.replace(" ", "_")
      self.parameterNode.SetParameter("ModelType", modelTypeId)
      for key in params.keys():
        self.parameterNode.SetParameter(modelTypeId+"_"+key, str(params[key]))
      self.updateModel()

  def computeMetrics(self):

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    quantificationResultsFolderShItem = self.getQuantificationResultsFolderShItem()
    shNode.RemoveItemChildren(quantificationResultsFolderShItem)

    # Create color table and show the scalar bar widget

    colorTableRangeMm = float(self.parameterNode.GetParameter("ColorTableRangeMm"))
    colorNode = self.parameterNode.GetNodeReference('DisplacementToColorNode')

    colorWidget = slicer.modules.colors.widgetRepresentation()
    colorWidget.setCurrentColorNode(colorNode)
    ctkScalarBarWidget = slicer.util.findChildren(colorWidget, name='VTKScalarBar')[0]
    ctkScalarBarWidget.setDisplay(1)
    ctkScalarBarWidget.setTitle("Radial\nCompression\n")
    ctkScalarBarWidget.setMaxNumberOfColors(256)
    ctkScalarBarWidget.setLabelsFormat('%4.1f mm')

    colorMap = colorNode.GetColorTransferFunction()
    colorMap.RemoveAllPoints()
    colorMap.AddRGBPoint(colorTableRangeMm * 0.0, 0.0, 0.0, 1.0)
    colorMap.AddRGBPoint(colorTableRangeMm * 0.2, 0.0, 1.0, 1.0)
    colorMap.AddRGBPoint(colorTableRangeMm * 0.5, 1.0, 1.0, 0.0)
    colorMap.AddRGBPoint(colorTableRangeMm * 1.0, 1.0, 0.0, 0.0)

    # Create table for quantitative results

    tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "QuantificationSummary")
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    shNode.SetItemParent(shNode.GetItemByDataNode(tableNode), quantificationResultsFolderShItem)

    col = tableNode.AddColumn()
    col.SetName("Metric")
    modelSegments = ['whole'] + self.modelInfo[self.modelType]['segments']
    for seg in modelSegments:
      col = tableNode.AddColumn(vtk.vtkDoubleArray())
      col.SetName(seg.capitalize() + "Model")

    # Surface differences
    #####################

    self.createOriginalAndDeformedSegmentModels(False) # surface

    startRow = tableNode.GetNumberOfRows()
    countColumns = 1
    tableNode.AddEmptyRow()
    tableNode.AddEmptyRow()
    tableNode.AddEmptyRow()
    tableNode.SetCellText(startRow + 0, 0, 'Contact area (mm2)')
    tableNode.SetCellText(startRow + 1, 0, 'Area of deformed model (mm2)')
    tableNode.SetCellText(startRow + 2, 0, 'Percent contact (%)')

    # Compute statistics
    countColumns = 1
    for seg in modelSegments:
      originalModel = self.parameterNode.GetNodeReference(seg.capitalize() + "OriginalSurfaceModel")
      deformedModel = self.parameterNode.GetNodeReference(seg.capitalize() + "DeformedSurfaceModel")
      contactSurfaceModel = self.parameterNode.GetNodeReference(seg.capitalize() + "DeformedContactSurfaceModel")

      # Create a separate table for displacements
      displacementTableName = seg.capitalize() + "DisplacementTable"
      self.updateDisplacementTable(displacementTableName, originalModel.GetPolyData(), deformedModel.GetPolyData(), 'Distance')

      # Fill in contact area measurement results

      massPropertiesOriginal = vtk.vtkMassProperties()
      massPropertiesOriginal.SetInputData(contactSurfaceModel.GetPolyData())
      surfaceAreaMm2 = massPropertiesOriginal.GetSurfaceArea()
      tableNode.SetCellText(startRow + 0, countColumns, "{0:0.1f}".format(surfaceAreaMm2))

      massPropertiesDeformed = vtk.vtkMassProperties()
      massPropertiesDeformed.SetInputData(deformedModel.GetPolyData())
      deformedSurfaceAreaMm2 = massPropertiesDeformed.GetSurfaceArea()
      tableNode.SetCellText(startRow + 1, countColumns, "{0:0.1f}".format(deformedSurfaceAreaMm2))

      # get volume difference
      contactAreaPercent = (float(surfaceAreaMm2) / deformedSurfaceAreaMm2) * 100
      tableNode.SetCellText(startRow + 2, countColumns, "{0:0.1f}".format(contactAreaPercent))

      countColumns += 1

    # Create compression chart

    compressionChartNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", "CompressionChart")
    self.parameterNode.SetNodeReferenceID("CompressionChart", compressionChartNode.GetID())
    shNode.SetItemParent(shNode.GetItemByDataNode(compressionChartNode), quantificationResultsFolderShItem)
    compressionChartNode.SetTitle('Compression along device axis')
    compressionChartNode.SetXAxisTitle('Compression [%]')
    compressionChartNode.SetYAxisTitle('Distal - Mid - Proximal')

    displacementTableNode = self.parameterNode.GetNodeReference("WholeDisplacementTable")
    for plotName in ["Displacement mean [%]", "Displacement min [%]", "Displacement max [%]"]:
      seriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", plotName)
      seriesNode.SetAndObserveTableNodeID(displacementTableNode.GetID())
      seriesNode.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
      seriesNode.SetXColumnName(plotName)
      seriesNode.SetYColumnName("Position [mm]")
      if "mean" in plotName:
        seriesNode.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
        seriesNode.SetLineWidth(6)
      else:
        seriesNode.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleDash)
        seriesNode.SetLineWidth(3)
      seriesNode.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleNone)
      #seriesNode.SetUniqueColor()
      shNode.SetItemParent(shNode.GetItemByDataNode(seriesNode), quantificationResultsFolderShItem)
      compressionChartNode.AddAndObservePlotSeriesNodeID(seriesNode.GetID())

    logging.debug("Surface area differences are computed")

    # Volume differences
    #####################

    self.createOriginalAndDeformedSegmentModels(True) # volumetric

    # Compute volumes
    startRow = tableNode.GetNumberOfRows()
    countColumns = 1
    tableNode.AddEmptyRow()
    tableNode.AddEmptyRow()
    tableNode.AddEmptyRow()
    tableNode.SetCellText(startRow + 0, 0, 'Original Volume (mm3)')
    tableNode.SetCellText(startRow + 1, 0, 'Deformed Volume (mm3)')
    tableNode.SetCellText(startRow + 2, 0, 'Volume Difference (mm3)')

    for seg in modelSegments:

      originalModel = self.parameterNode.GetNodeReference(seg.capitalize() + "OriginalVolumeModel")
      deformedModel = self.parameterNode.GetNodeReference(seg.capitalize() + "DeformedVolumeModel")

      # get original volume
      massPropertiesOriginal = vtk.vtkMassProperties()
      massPropertiesOriginal.SetInputData(originalModel.GetPolyData())
      originalVolumeMm3 = massPropertiesOriginal.GetVolume()
      tableNode.SetCellText(startRow, countColumns, "{0:0.1f}".format(originalVolumeMm3))
      logging.debug(originalModel.GetName() + " has volume " + "{0:0.1f}".format(originalVolumeMm3) + " mm3")

      # get deformed volume (need to create copy of the polydata and harden the deforming transform)
      massPropertiesDeformed = vtk.vtkMassProperties()
      massPropertiesDeformed.SetInputData(deformedModel.GetPolyData())
      deformedVolumeMm3 = massPropertiesDeformed.GetVolume()
      tableNode.SetCellText(startRow + 1, countColumns, "{0:0.1f}".format(deformedVolumeMm3))

      # get volume difference
      volumeDifferenceMm3 = originalVolumeMm3 - deformedVolumeMm3
      tableNode.SetCellText(startRow + 2, countColumns, "{0:0.1f}".format(volumeDifferenceMm3))

      countColumns += 1

    logging.debug("Volume differences are computed")

    return tableNode

  def updateDisplacementTable(self, tableName, polyData, warpedPolyData, scalarName):
    import math

    displacementTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", tableName)
    self.parameterNode.SetNodeReferenceID(tableName, displacementTable.GetID())
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    quantificationResultsFolderShItem = self.getQuantificationResultsFolderShItem()
    shNode.SetItemParent(shNode.GetItemByDataNode(displacementTable), quantificationResultsFolderShItem)

    numberOfPointsPerSlice = self.getNumberOfModelPointsPerSlice()
    numberOfSlices = self.getNumberOfProfilePoints() # 50

    slicePositionArray = vtk.vtkDoubleArray()
    slicePositionArray.SetName("Position [mm]")
    slicePositionArray.SetNumberOfValues(numberOfSlices)

    originalSliceRadiusArray = vtk.vtkDoubleArray()
    originalSliceRadiusArray.SetName("Original radius [mm]")
    originalSliceRadiusArray.SetNumberOfValues(numberOfSlices)
    originalSlicePerimeterArray = vtk.vtkDoubleArray()
    originalSlicePerimeterArray.SetName("Original perimeter [mm]")
    originalSlicePerimeterArray.SetNumberOfValues(numberOfSlices)
    originalSliceAreaArray = vtk.vtkDoubleArray()
    originalSliceAreaArray.SetName("Original area [mm*mm]")
    originalSliceAreaArray.SetNumberOfValues(numberOfSlices)

    deformedSliceRadiusArray = vtk.vtkDoubleArray()
    deformedSliceRadiusArray.SetName("Deformed radius [mm]")
    deformedSliceRadiusArray.SetNumberOfValues(numberOfSlices)
    deformedSlicePerimeterArray = vtk.vtkDoubleArray()
    deformedSlicePerimeterArray.SetName("Deformed perimeter [mm]")
    deformedSlicePerimeterArray.SetNumberOfValues(numberOfSlices)
    deformedSliceAreaArray = vtk.vtkDoubleArray()
    deformedSliceAreaArray.SetName("Deformed area [mm*mm]")
    deformedSliceAreaArray.SetNumberOfValues(numberOfSlices)

    compressionSliceRadiusArray = vtk.vtkDoubleArray()
    compressionSliceRadiusArray.SetName("Radius compression [%]")
    compressionSliceRadiusArray.SetNumberOfValues(numberOfSlices)
    compressionSlicePerimeterArray = vtk.vtkDoubleArray()
    compressionSlicePerimeterArray.SetName("Perimeter compression [%]")
    compressionSlicePerimeterArray.SetNumberOfValues(numberOfSlices)
    compressionSliceAreaArray = vtk.vtkDoubleArray()
    compressionSliceAreaArray.SetName("Area compression [%]")
    compressionSliceAreaArray.SetNumberOfValues(numberOfSlices)

    # Create a polygon for area computation    
    polygon = vtk.vtkPolygon()
    polygon.GetPointIds().SetNumberOfIds(numberOfPointsPerSlice)
    polygon.GetPoints().SetNumberOfPoints(numberOfPointsPerSlice)
    for i in range(numberOfPointsPerSlice):
      polygon.GetPointIds().SetId(i,i)

    for sliceIndex in range(numberOfSlices):
      slicePosition = polyData.GetPoints().GetPoint(sliceIndex)
      slicePositionArray.SetValue(sliceIndex, slicePosition[2])
      originalSliceRadius = math.sqrt(slicePosition[0]*slicePosition[0]+slicePosition[1]*slicePosition[1])
      originalSlicePerimeter = 2*originalSliceRadius*math.pi
      originalSliceArea = originalSliceRadius*originalSliceRadius*math.pi
      originalSliceRadiusArray.SetValue(sliceIndex, originalSliceRadius)
      originalSlicePerimeterArray.SetValue(sliceIndex, originalSlicePerimeter)
      originalSliceAreaArray.SetValue(sliceIndex, originalSliceArea)
     
      # Initialize previous point to be the last point in the polygon
      # so that we don't miss the segment that connects the last and first point.
      averageRadius = 0
      polygonPerimeter = 0
      previousPoint = warpedPolyData.GetPoints().GetPoint((numberOfPointsPerSlice - 1) * numberOfSlices + sliceIndex)
      for angleIndex in range(numberOfPointsPerSlice):
        point = warpedPolyData.GetPoints().GetPoint(angleIndex * numberOfSlices + sliceIndex)
        averageRadius += math.sqrt(point[0] * point[0] + point[1] * point[1])
        polygonPerimeter += math.sqrt(vtk.vtkMath.Distance2BetweenPoints(point,previousPoint))
        polygon.GetPoints().SetPoint(angleIndex, point)
        previousPoint = point
      averageRadius /= numberOfPointsPerSlice
      polygonArea = polygon.ComputeArea()

      deformedSliceRadiusArray.SetValue(sliceIndex, averageRadius)
      deformedSlicePerimeterArray.SetValue(sliceIndex, polygonPerimeter)
      deformedSliceAreaArray.SetValue(sliceIndex, polygonArea)

      compressionSliceRadiusArray.SetValue(sliceIndex, (originalSliceRadius-averageRadius)/originalSliceRadius*100.0)
      compressionSlicePerimeterArray.SetValue(sliceIndex, (originalSlicePerimeter-polygonPerimeter)/originalSlicePerimeter*100.0)
      compressionSliceAreaArray.SetValue(sliceIndex, (originalSliceArea-polygonArea)/originalSliceArea*100.0)
      
    displacementTable.AddColumn(slicePositionArray)
    displacementTable.AddColumn(compressionSliceRadiusArray)
    displacementTable.AddColumn(compressionSlicePerimeterArray)
    displacementTable.AddColumn(compressionSliceAreaArray)

    displacementTable.AddColumn(originalSliceRadiusArray)
    displacementTable.AddColumn(originalSlicePerimeterArray)
    displacementTable.AddColumn(originalSliceAreaArray)

    displacementTable.AddColumn(deformedSliceRadiusArray)
    displacementTable.AddColumn(deformedSliceAreaArray)
    displacementTable.AddColumn(deformedSlicePerimeterArray)

    minDistanceArray = vtk.vtkDoubleArray()
    minDistanceArray.SetName("Displacement min [mm]")
    minDistanceArray.SetNumberOfValues(numberOfSlices)
    maxDistanceArray = vtk.vtkDoubleArray()
    maxDistanceArray.SetName("Displacement max [mm]")
    maxDistanceArray.SetNumberOfValues(numberOfSlices)
    meanDistanceArray = vtk.vtkDoubleArray()
    meanDistanceArray.SetName("Displacement mean [mm]")
    meanDistanceArray.SetNumberOfValues(numberOfSlices)
    displacementTable.AddColumn(minDistanceArray)
    displacementTable.AddColumn(maxDistanceArray)
    displacementTable.AddColumn(meanDistanceArray)

    minDistancePercentArray = vtk.vtkDoubleArray()
    minDistancePercentArray.SetName("Displacement min [%]")
    minDistancePercentArray.SetNumberOfValues(numberOfSlices)
    maxDistancePercentArray = vtk.vtkDoubleArray()
    maxDistancePercentArray.SetName("Displacement max [%]")
    maxDistancePercentArray.SetNumberOfValues(numberOfSlices)
    meanDistancePercentArray = vtk.vtkDoubleArray()
    meanDistancePercentArray.SetName("Displacement mean [%]")
    meanDistancePercentArray.SetNumberOfValues(numberOfSlices)
    displacementTable.AddColumn(minDistancePercentArray)
    displacementTable.AddColumn(maxDistancePercentArray)
    displacementTable.AddColumn(meanDistancePercentArray)

    firstDisplacementColumnIndex = displacementTable.GetNumberOfColumns()
    for angleIndex in range(numberOfPointsPerSlice):
      distanceArray = vtk.vtkDoubleArray()
      distanceArray.SetName("Displacement (%.2fdeg) [mm]" % (360.0 / float(numberOfPointsPerSlice) * angleIndex))
      distanceArray.SetNumberOfValues(numberOfSlices)
      for sliceIndex in range(numberOfSlices):
        distance = polyData.GetPointData().GetScalars().GetValue(angleIndex * numberOfSlices + sliceIndex)
        distanceArray.SetValue(sliceIndex, distance)
      displacementTable.AddColumn(distanceArray)

    for sliceIndex in range(numberOfSlices):
      meanDistance = 0
      for angleIndex in range(numberOfPointsPerSlice):
        distanceArray = displacementTable.GetTable().GetColumn(firstDisplacementColumnIndex+angleIndex)
        distance = distanceArray.GetValue(sliceIndex)
        if angleIndex == 0:
          minDistance = distance
          maxDistance = distance
        else:
          if distance < minDistance:
            minDistance = distance
          if distance > maxDistance:
            maxDistance = distance
        meanDistance += distance
      meanDistance /= numberOfPointsPerSlice
      radius = originalSliceRadiusArray.GetValue(sliceIndex)
      minDistanceArray.SetValue(sliceIndex, minDistance)
      maxDistanceArray.SetValue(sliceIndex, maxDistance)
      meanDistanceArray.SetValue(sliceIndex, meanDistance)
      minDistancePercentArray.SetValue(sliceIndex, minDistance/radius*100)
      maxDistancePercentArray.SetValue(sliceIndex, maxDistance/radius*100)
      meanDistancePercentArray.SetValue(sliceIndex, meanDistance/radius*100)

  def updateModel(self):

    if not self.parameterNode:
      return

    getProfilePointsMethod = self.modelInfo[self.modelType]['getProfilePointsMethod']
    modelParameters = self.modelInfo[self.modelType]['parameters']
    modelSegments = self.modelInfo[self.modelType]['segments'] # some models have distal/middle/proximal sections

    # Create whole (open) original and deformed models
    profilePoints = getProfilePointsMethod(modelParameters)

    modelProfilePoints = vtk.vtkPoints()
    self.fitCurve(profilePoints, modelProfilePoints, self.getNumberOfProfilePoints(), self.modelInfo[self.modelType]['interpolationSmoothness'])
    self.updateModelWithProfile(self.parameterNode.GetNodeReference('OriginalModel'), modelProfilePoints, self.getNumberOfModelPointsPerSlice())
    self.updateModelWithProfile(self.parameterNode.GetNodeReference('DeformedModel'), modelProfilePoints, self.getNumberOfModelPointsPerSlice())

    self.handleProfilePoints.Reset()
    self.resampleCurve(modelProfilePoints, self.handleProfilePoints, self.getHandlesSpacingMm())
    self.updateHandlesWithProfile(self.parameterNode.GetNodeReference('OriginalHandles'), self.handleProfilePoints, self.getHandlesPerSlice())
    self.updateHandlesWithProfile(self.parameterNode.GetNodeReference('DeformedHandles'), self.handleProfilePoints, self.getHandlesPerSlice())

    logging.debug("updating segment original and deformed models")

  def createOriginalAndDeformedSegmentModels(self, volumetric=False):
    if volumetric:
      typeName = "Volume"
    else:
      typeName = "Surface"

    resultsFolderShItem = self.getQuantificationResultsFolderShItem(typeName + " models")
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    if volumetric:
      shNode.SetItemExpanded(resultsFolderShItem, False)

    getProfilePointsMethod = self.modelInfo[self.modelType]['getProfilePointsMethod']
    modelParameters = self.modelInfo[self.modelType]['parameters']

    modelSegments = self.modelInfo[self.modelType]['segments'] # some models have distal/middle/proximal sections
    for seg in modelSegments + ['whole']:
      profilePoints = getProfilePointsMethod(modelParameters, seg, not volumetric)
      modelProfilePoints = vtk.vtkPoints()
      self.fitCurve(profilePoints, modelProfilePoints, self.getNumberOfProfilePoints(),
      self.modelInfo[self.modelType]['interpolationSmoothness'])

      originalSegmentName = seg.capitalize() + "Original" + typeName + "Model"
      originalModel = self.createModelNode(originalSegmentName, [1, 0, 0])
      originalModel.SetName(originalSegmentName)
      dn = originalModel.GetDisplayNode()
      dn.SetVisibility(False)
      dn.SetRepresentation(dn.WireframeRepresentation)
      originalModel.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      self.parameterNode.SetNodeReferenceID(originalSegmentName, originalModel.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(originalModel), resultsFolderShItem)
      self.updateModelWithProfile(originalModel, modelProfilePoints, self.getNumberOfModelPointsPerSlice())

      deformedSegmentName = seg.capitalize() + "Deformed" + typeName + "Model"
      deformedModel = self.createModelNode(deformedSegmentName, [0.5,0.5,1.0])
      deformedModel.SetName(deformedSegmentName)
      deformedModel.GetDisplayNode().SetVisibility(False)
      deformedModel.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      deformingTransform = self.parameterNode.GetNodeReference('DeformingTransform').GetTransformToParent()
      transformFilter = vtk.vtkTransformPolyDataFilter()
      transformFilter.SetInputData(originalModel.GetPolyData())
      transformFilter.SetTransform(deformingTransform)
      transformFilter.Update()
      deformedModel.SetAndObservePolyData(transformFilter.GetOutput())
      self.parameterNode.SetNodeReferenceID(deformedSegmentName, deformedModel.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(deformedModel), resultsFolderShItem)

      if not volumetric:

        distanceFilter = vtk.vtkDistancePolyDataFilter()
        distanceFilter.SetInputConnection(0, originalModel.GetPolyDataConnection())
        distanceFilter.SetInputConnection(1, deformedModel.GetPolyDataConnection())
        distanceFilter.SignedDistanceOn()

        # Generate outputs (distanceOutput and secondDistanceOutput)
        # with inverted distance values (so that positive value always mean compression)
        distanceFilter.Update()
        distanceOutput = vtk.vtkPolyData()
        distanceOutput.DeepCopy(distanceFilter.GetOutput())
        distanceFilter.NegateDistanceOn()
        distanceFilter.Update()
        secondDistanceOutput = distanceFilter.GetSecondDistanceOutput()

        originalModel.SetAndObservePolyData(distanceOutput)
        deformedModel.SetAndObservePolyData(secondDistanceOutput)

        # Cut along specified threshold value (smooth cut through cells)
        threshold = vtk.vtkClipPolyData()
        threshold.SetInputData(secondDistanceOutput)
        # a bit more than 0 to not include parts that are less than 0 due to numerical inaccuracy
        threshold.SetValue(0.5)
        threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "Distance")
        threshold.InsideOutOff()
        threshold.Update()

        contactSegmentName = seg.capitalize() + "DeformedContactSurfaceModel"
        contactModel = self.createModelNode(contactSegmentName, [0.5, 0.5, 1.0])
        contactModel.SetName(deformedSegmentName)
        contactModel.GetDisplayNode().SetVisibility(False)
        contactModel.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
        contactModel.SetAndObservePolyData(threshold.GetOutput())
        shNode.SetItemParent(shNode.GetItemByDataNode(contactModel), resultsFolderShItem)
        self.parameterNode.SetNodeReferenceID(contactSegmentName, contactModel.GetID())

        # Update models to use displacement color node
        colorNode = self.parameterNode.GetNodeReference('DisplacementToColorNode')
        colorNodeID = colorNode.GetID()
        colorTableRangeMm = float(self.parameterNode.GetParameter("ColorTableRangeMm"))
        for model in [originalModel, deformedModel, contactModel]:
          model.GetDisplayNode().SetActiveScalarName('Distance')
          model.GetDisplayNode().ScalarVisibilityOn()
          model.GetDisplayNode().AutoScalarRangeOn()
          model.GetDisplayNode().SetAndObserveColorNodeID(colorNodeID)
          # Use the color exactly as defined in the colormap
          model.GetDisplayNode().SetScalarRangeFlag(model.GetDisplayNode().UseColorNodeScalarRange)
          model.GetDisplayNode().AutoScalarRangeOff()
          model.GetDisplayNode().SetScalarRange(0, colorTableRangeMm)


  def createModelNode(self, name, color):
    modelsLogic = slicer.modules.models.logic()
    polyData = vtk.vtkPolyData()
    modelNode = modelsLogic.AddModel(polyData)
    modelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name))
    displayNode = modelNode.GetDisplayNode()
    displayNode.SetColor(color)
    displayNode.SetBackfaceCulling(False)
    displayNode.SetEdgeVisibility(True)
    displayNode.SetSliceIntersectionVisibility(True)
    displayNode.SetSliceIntersectionThickness(2)
    return modelNode

  def createMarkupsNode(self, name, color):
    markupsLogic = slicer.modules.markups.logic()
    markupsNodeId = markupsLogic.AddNewFiducialNode(name)
    markupsNode = slicer.mrmlScene.GetNodeByID(markupsNodeId)
    markupsNode.GetDisplayNode().SetColor(color)
    markupsNode.GetDisplayNode().SetSelectedColor(color)
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    shNode.SetItemParent(shNode.GetItemByDataNode(markupsNode), shNode.GetItemByDataNode(self.parameterNode))
    return markupsNode

  def fitCurve(self, controlPoints, interpolatedPoints, nInterpolatedPoints = 30, interpolationSmoothness = 0.0):
    # One spline for each direction.

    if self.interpolatorType == 'CardinalSpline':
      aSplineX = vtk.vtkCardinalSpline()
      aSplineY = vtk.vtkCardinalSpline()
      aSplineZ = vtk.vtkCardinalSpline()
    elif self.interpolatorType == 'KochanekSpline':
      aSplineX = vtk.vtkKochanekSpline()
      aSplineY = vtk.vtkKochanekSpline()
      aSplineZ = vtk.vtkKochanekSpline()
      aSplineX.SetDefaultContinuity(interpolationSmoothness)
      aSplineY.SetDefaultContinuity(interpolationSmoothness)
      aSplineZ.SetDefaultContinuity(interpolationSmoothness)
    if self.interpolatorType == 'SCurveSpline':
      aSplineX = vtk.vtkSCurveSpline()
      aSplineY = vtk.vtkSCurveSpline()
      aSplineZ = vtk.vtkSCurveSpline()

    aSplineX.SetClosed(False)
    aSplineY.SetClosed(False)
    aSplineZ.SetClosed(False)

    pos = [0.0, 0.0, 0.0]
    nOfControlPoints = controlPoints.GetNumberOfPoints()
    pointIndices = range(nOfControlPoints)
    for i, pointId in enumerate(pointIndices):
      controlPoints.GetPoint(pointId, pos)
      aSplineX.AddPoint(i, pos[0])
      aSplineY.AddPoint(i, pos[1])
      aSplineZ.AddPoint(i, pos[2])

    curveParameterRange = [0.0, 0.0]
    aSplineX.GetParametricRange(curveParameterRange)

    curveParameter = curveParameterRange[0]
    curveParameterStep = (curveParameterRange[1]-curveParameterRange[0])/(nInterpolatedPoints-1)

    for nInterpolatedPointIndex in range(nInterpolatedPoints):
      interpolatedPoints.InsertNextPoint(aSplineX.Evaluate(curveParameter), aSplineY.Evaluate(curveParameter),
                                         aSplineZ.Evaluate(curveParameter))
      curveParameter += curveParameterStep

  def resampleCurve(self, curvePoints, sampledPoints, samplingDistance = 5.0):
    import numpy as np

    distanceFromLastSampledPoint = 0
    nOfCurvePoints = curvePoints.GetNumberOfPoints()
    previousPoint = np.array(curvePoints.GetPoint(0))
    sampledPoints.InsertNextPoint(previousPoint)
    for pointId in range(1, nOfCurvePoints):
      currentPoint = np.array(curvePoints.GetPoint(pointId))
      lastSegmentLength = np.linalg.norm(currentPoint - previousPoint)
      if distanceFromLastSampledPoint+lastSegmentLength >= samplingDistance:
        distanceFromLastInterpolatedPoint = samplingDistance-distanceFromLastSampledPoint
        newControlPoint = previousPoint + (currentPoint-previousPoint) * distanceFromLastInterpolatedPoint/lastSegmentLength
        sampledPoints.InsertNextPoint(newControlPoint)
        distanceFromLastSampledPoint = lastSegmentLength - distanceFromLastInterpolatedPoint
        if distanceFromLastSampledPoint>samplingDistance:
          distanceFromLastSampledPoint = samplingDistance
      else:
        distanceFromLastSampledPoint += lastSegmentLength
      previousPoint = currentPoint.copy()

    if distanceFromLastSampledPoint>samplingDistance/2.0:
      # if last point was far enough then add a point at the last position
      sampledPoints.InsertNextPoint(currentPoint)
    else:
      # last point was quite close, just adjust its position
      sampledPoints.SetPoint(sampledPoints.GetNumberOfPoints()-1, currentPoint)

  def updateModelWithProfile(self, modelNode, points, resolution=30):

    lines = vtk.vtkCellArray()
    lines.InsertNextCell(points.GetNumberOfPoints())
    for pointIndex in range(points.GetNumberOfPoints()):
      lines.InsertCellPoint(pointIndex)

    profile = vtk.vtkPolyData()
    profile.SetPoints(points)
    profile.SetLines(lines)

    # Rotate profile around Z axis to create surface
    extrude = vtk.vtkRotationalExtrusionFilter()
    extrude.SetInputData(profile)
    extrude.SetResolution(resolution)
    extrude.Update()

    # Triangulation is necessary to avoid discontinuous lines
    # in model/slice intersection display
    triangles = vtk.vtkTriangleFilter()
    triangles.SetInputConnection(extrude.GetOutputPort())

    modelNode.SetPolyDataConnection(triangles.GetOutputPort())

    if not modelNode.GetDisplayNode():
      modelNode.CreateDefaultDisplayNodes()
      displayNode = modelNode.GetDisplayNode()
      displayNode.SetBackfaceCulling(False)
      displayNode.SetEdgeVisibility(True)
      displayNode.SetColor(0.5,0.5,1.0)
      displayNode.SetSliceIntersectionVisibility(True)
      displayNode.SetSliceIntersectionThickness(2)

  def updateHandlesWithProfile(self, markupsNode, points, resolution=4):
    lines = vtk.vtkCellArray()
    lines.InsertNextCell(points.GetNumberOfPoints())
    for pointIndex in range(points.GetNumberOfPoints()):
      lines.InsertCellPoint(pointIndex)

    profile = vtk.vtkPolyData()
    profile.SetPoints(points)
    profile.SetLines(lines)

    # Rotate profile around Z axis
    extrude = vtk.vtkRotationalExtrusionFilter()
    extrude.SetInputData(profile)
    extrude.SetResolution(resolution)

    extrude.Update()
    curvePoints = extrude.GetOutput().GetPoints()

    # Update markup node with points
    wasModifying = markupsNode.StartModify()
    markupsNode.RemoveAllMarkups()
    n = curvePoints.GetNumberOfPoints()
    pos = [0.0, 0.0, 0.0]
    for i in range(resolution * points.GetNumberOfPoints()):
      curvePoints.GetPoint(i, pos)
      fidIndex = markupsNode.AddFiducial(pos[0], pos[1], pos[2])
    markupsNode.EndModify(wasModifying)

  def moveDeviceBasedOnSlider(self, sliderValue):
    #center of device is the translation part of the PositioningTransformMatrix
    centerlinePolyData = self.getCenterlineModelNode().GetPolyData()
    centerlineVtkPoints = centerlinePolyData.GetPoints()
    numCenterlineVtkPoints = centerlineVtkPoints.GetNumberOfPoints()

    #position model to corresponding point along centerline
    deviceCenterPointIndex = int(round(((numCenterlineVtkPoints / 100.0) * sliderValue)))
    if deviceCenterPointIndex == numCenterlineVtkPoints:
      deviceCenterPointIndex -= 1 #otherwise point index will be out of range

    self.alignDeviceWithCenterlineDirection(deviceCenterPointIndex)
    return

  def getClosestPointIDOnCenterline(self, point):
    centerlinePolyData = self.getCenterlineModelNode().GetPolyData()
    curvePointsLocator = vtk.vtkPointLocator() # could try using vtk.vtkStaticPointLocator() if need to optimize
    curvePointsLocator.SetDataSet(centerlinePolyData)
    curvePointsLocator.BuildLocator()
    closestPointId = curvePointsLocator.FindClosestPoint(point)
    return closestPointId

  def getClosestPointCoordinatesOnCenterline(self, point):
    centerlinePolyData = self.getCenterlineModelNode().GetPolyData()
    curvePointsLocator = vtk.vtkPointLocator() # could try using vtk.vtkStaticPointLocator() if need to optimize
    curvePointsLocator.SetDataSet(centerlinePolyData)
    curvePointsLocator.BuildLocator()
    closestPointId = curvePointsLocator.FindClosestPoint(point)
    closestPoint = centerlinePolyData.GetPoints().GetPoint(closestPointId)
    return closestPoint

  def getDeviceCenter(self):
    #get center of device from the translation portion of the PositioningTransform
    deviceToCenterlineTransform = self.parameterNode.GetNodeReference('PositioningTransform')
    deviceToCenterlineTransformMatrix = vtk.vtkMatrix4x4()
    deviceToCenterlineTransform.GetMatrixTransformToParent(deviceToCenterlineTransformMatrix)

    deviceCenter = [0,0,0]
    deviceCenter[0] = deviceToCenterlineTransformMatrix.GetElement(0, 3)
    deviceCenter[1] = deviceToCenterlineTransformMatrix.GetElement(1, 3)
    deviceCenter[2] = deviceToCenterlineTransformMatrix.GetElement(2, 3)

    return deviceCenter

  def alignDeviceWithCenterlineDirection(self, deviceCenterPointIndex):
    import HeartValveLib
    import numpy as np

    # get the length of the device
    modelParameters = self.modelInfo[self.modelType]['parameters']
    if self.modelType == HarmonyDevice.NAME:
      lengthMm = (modelParameters['distalStraightLengthMm'] + modelParameters['distalCurvedLengthMm']
                  + modelParameters['midLengthMm']
                  + modelParameters['proximalCurvedLengthMm'] + modelParameters['proximalStraightLengthMm'])
    else:
      lengthMm = modelParameters['lengthMm']

    centerlinePoints = slicer.util.arrayFromModelPoints(self.getCenterlineModelNode())

    # Find point index at half distance in both directions along the curve
    distanceFromCenterPoint = 0
    startPointIndex = 0
    for startPointIndex in range(deviceCenterPointIndex-1, 0, -1):
      distanceFromCenterPoint += np.linalg.norm(centerlinePoints[startPointIndex] - centerlinePoints[startPointIndex+1])
      if distanceFromCenterPoint >= lengthMm / 2:
        break

    distanceFromCenterPoint = 0
    endPointIndex = len(centerlinePoints)-1
    for endPointIndex in range(deviceCenterPointIndex+1, len(centerlinePoints)):
      distanceFromCenterPoint += np.linalg.norm(centerlinePoints[endPointIndex-1] - centerlinePoints[endPointIndex])
      if distanceFromCenterPoint >= lengthMm / 2:
        break

    centerlinePointsAlongDevice = centerlinePoints[startPointIndex:endPointIndex]
    [linePosition, lineDirectionVector] = HeartValveLib.lineFit(centerlinePointsAlongDevice)

    if self.deviceOrientationFlipped:
      deviceZAxisInRas = lineDirectionVector
    else:
      deviceZAxisInRas = -lineDirectionVector

    deviceCenterPoint = linePosition

    deviceZAxisInRasUnitVector = deviceZAxisInRas / np.linalg.norm(deviceZAxisInRas)

    # "PositioningTransform" is initially identity matrix; then changed by using the positioning sliders
    deviceToCenterlineTransform = self.parameterNode.GetNodeReference('PositioningTransform')
    rotateDeviceToAlignWithCenterlineTransform = HeartValveLib.getVtkTransformPlaneToWorld(deviceCenterPoint, deviceZAxisInRasUnitVector)
    deviceToCenterlineTransform.SetAndObserveTransformToParent(rotateDeviceToAlignWithCenterlineTransform)

    #for nodeId in ['DeformingTransform', 'OriginalModel', 'OriginalModelDist', 'DeformedModelDist', 'DeformedModelContactSurface']:
    #  #\ + segmentDistNames + segmentContactSurfaceNames:
    #  n = self.parameterNode.GetNodeReference(nodeId)
    #  n.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())

  def deformHandlesToVesselWalls(self, allowDeviceExpansionToVesselWalls):
    import numpy as np

    # Initialize handle positions before warping
    self.updateModel()

    originalHandlesNode = self.parameterNode.GetNodeReference("OriginalHandles")
    deformedHandlesNode = self.parameterNode.GetNodeReference("DeformedHandles")
    numHandlePoints = deformedHandlesNode.GetNumberOfFiducials()

    # transform vessel model to device coordinate system
    vesselModel = self.getVesselModelNode()
    vesselToDeviceTransform = vtk.vtkGeneralTransform()
    slicer.vtkMRMLTransformNode().GetTransformBetweenNodes(vesselModel.GetParentTransformNode(),
      originalHandlesNode.GetParentTransformNode(), vesselToDeviceTransform)
    transformFilter = vtk.vtkTransformPolyDataFilter()
    transformFilter.SetInputData(vesselModel.GetPolyData())
    transformFilter.SetTransform(vesselToDeviceTransform)
    transformFilter.Update()
    vesselPolyData_device = transformFilter.GetOutput()

    # Create localizer for finding vessel surface intersection points
    localizer = vtk.vtkModifiedBSPTree()
    localizer.SetDataSet(vesselPolyData_device)
    localizerTol = 0.1
    foundIntersectionPoints = vtk.vtkPoints()
    foundIntersectionCellIds = vtk.vtkIdList()
    localizer.BuildLocator()

    wasModifying = deformedHandlesNode.StartModify()

    for handleID in range(numHandlePoints):
      # all points are defined in device coordinate system
      originalHandlePoint = [0,0,0]
      originalHandlesNode.GetNthFiducialPosition(handleID, originalHandlePoint)
      pointOnCenterline = np.array([0, 0, originalHandlePoint[2]])  # point on centerline

      maxDistanceFactor = 5.0  # max distance of vessel wall (factor of device radius)
      intersectionLineEndPoint = np.array([originalHandlePoint[0]*maxDistanceFactor, originalHandlePoint[1]*maxDistanceFactor, originalHandlePoint[2]])
      localizer.IntersectWithLine(pointOnCenterline, intersectionLineEndPoint, localizerTol, foundIntersectionPoints, foundIntersectionCellIds)
      if foundIntersectionPoints.GetNumberOfPoints()>0:
        pointOnVessel = foundIntersectionPoints.GetPoint(0)
      else:
        pointOnVessel = originalHandlePoint

      if allowDeviceExpansionToVesselWalls:
        deformedHandlesNode.SetNthFiducialPositionFromArray(handleID, pointOnVessel)
      else:
        # Check if handle point is outside of vessel walls; only deform (shrink) if it is. Device should not be expanded to fit
        # vessel walls because most/all RVOT devices cannot be expanded beyond their native form; they can only be compressed.
        distanceDeviceToCenterline = np.linalg.norm(originalHandlePoint-pointOnCenterline)
        distanceVesselToCenterline = np.linalg.norm(pointOnVessel-pointOnCenterline)
        if distanceVesselToCenterline < distanceDeviceToCenterline:
          deformedHandlesNode.SetNthFiducialPositionFromArray(handleID, pointOnVessel)
        else:
          deformedHandlesNode.SetNthFiducialPositionFromArray(handleID, originalHandlePoint)

    deformedHandlesNode.EndModify(wasModifying)

    # make original model transparent after deforming
    originalModelNode = self.parameterNode.GetNodeReference('OriginalModel')
    originalModelNode.GetDisplayNode().SetOpacity(0.1)

  def processVesselSegment(self):

    # Export vessel lumen segment to labelmap
    slicer.util.showStatusMessage("Exporting segment to labelmap...", 3000)
    [vesselLumenSegmentationNode, vesselLumenSegmentId] = self.getVesselLumenSegment()
    exportedSegmentIds = vtk.vtkStringArray()
    exportedSegmentIds.InsertNextValue(vesselLumenSegmentId)
    vesselLumenLabelMapNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode', 'VesselLumenLabelMapTemp')
    slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(vesselLumenSegmentationNode, exportedSegmentIds, vesselLumenLabelMapNode)

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    parameterNodeShItem = shNode.GetItemByDataNode(self.parameterNode)
    centerlineFolderShItem = shNode.GetItemChildWithName(parameterNodeShItem, "Centerline")
    if not centerlineFolderShItem:
      centerlineFolderShItem = shNode.CreateFolderItem(parameterNodeShItem, "Centerline")

    # Export vessel lumen segment to model
    vesselLumenModelNode = self.getVesselModelNode()
    if not vesselLumenModelNode:
      vesselLumenModelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', 'VesselLumenModel')
      vesselLumenModelNode.CreateDefaultDisplayNodes()
      vesselLumenModelNode.SetAndObserveTransformNodeID(vesselLumenSegmentationNode.GetTransformNodeID())
      vesselLumenModelNode.GetDisplayNode().SetOpacity(0.5)
      shNode.SetItemParent(shNode.GetItemByDataNode(vesselLumenModelNode), centerlineFolderShItem)
      self.setVesselModelNode(vesselLumenModelNode)
    slicer.modules.segmentations.logic().ExportSegmentToRepresentationNode(
      vesselLumenSegmentationNode.GetSegmentation().GetSegment(vesselLumenSegmentId), vesselLumenModelNode)

    # Extract skeleton
    slicer.util.showStatusMessage("Extracting centerline, this may take a few minutes...", 3000)
    parameters = {}
    parameters["InputImageFileName"] = vesselLumenLabelMapNode.GetID()
    vesselCenterlineOutputLabelMapNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode', 'VesselCenterlineLabelMapTemp')
    parameters["OutputImageFileName"] = vesselCenterlineOutputLabelMapNode.GetID()
    vesselCenterlineMarkupsNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsFiducialNode', 'VesselCenterlineMarkupsTemp')
    parameters["OutputFiducialsFileName"] = vesselCenterlineMarkupsNode.GetID()
    parameters["NumberOfPoints"] = 300
    centerlineExtractor = slicer.modules.extractskeleton
    qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
    cliNode = slicer.cli.runSync(centerlineExtractor, None, parameters)
    qt.QApplication.restoreOverrideCursor()

    # Create centerline curve
    slicer.util.showStatusMessage("Creating centerline curve...", 3000)
    markupsToModelLogic = slicer.modules.markupstomodel.logic()
    centerlineModelNode = self.getCenterlineModelNode()
    if not centerlineModelNode:
      centerlineModelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', 'VesselCenterlineModel')
      centerlineModelNode.CreateDefaultDisplayNodes()
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      shNode.SetItemParent(shNode.GetItemByDataNode(centerlineModelNode), centerlineFolderShItem)
      self.setCenterlineModelNode(centerlineModelNode)
    markupsToModelLogic.UpdateOutputCurveModel(vesselCenterlineMarkupsNode, self.getCenterlineModelNode(),
                                               slicer.vtkMRMLMarkupsToModelNode.Linear,  # interpolation
                                               False,  # loop
                                               0.0  # radius = 0 means no tube will be generated, just a line
                                               )

    # Delete temporary nodes
    slicer.mrmlScene.RemoveNode(vesselLumenLabelMapNode)
    slicer.mrmlScene.RemoveNode(vesselCenterlineMarkupsNode)
    slicer.mrmlScene.RemoveNode(vesselCenterlineOutputLabelMapNode)
    slicer.mrmlScene.RemoveNode(cliNode)
    slicer.util.showStatusMessage("Vessel centerline creation completed", 3000)


class CardiacDeviceSimulatorTest(ScriptedLoadableModuleTest):
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
    self.test_CardiacDeviceSimulator1()

  def test_CardiacDeviceSimulator1(self):
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
    #
    # first, get some data
    #
    import urllib
    downloads = (
        ('http://slicer.kitware.com/midas3/download?items=5767', 'FA.nrrd', slicer.util.loadVolume),
        )

    for url,name,loader in downloads:
      filePath = slicer.app.temporaryPath + '/' + name
      if not os.path.exists(filePath) or os.stat(filePath).st_size == 0:
        logging.info('Requesting download %s from %s...\n' % (name, url))
        urllib.urlretrieve(url, filePath)
      if loader:
        logging.info('Loading %s...' % (name,))
        loader(filePath)
    self.delayDisplay('Finished with download and loading')

    volumeNode = slicer.mrmlScene.GetFirstNodeByName("FA")
    logic = CardiacDeviceSimulatorLogic()
    self.assertIsNotNone( logic.hasImageData(volumeNode) )
    self.delayDisplay('Test passed!')
