import qt, vtk
import logging
import slicer
from CardiacDeviceSimulatorUtils.widgethelper import UIHelper
from CardiacDeviceSimulatorUtils.widgethelper import DeviceWidget
from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase


class DeviceDeformationWidget(DeviceWidget):
  """Shows list of devices (as button row), presets, and sliders to modify presets
  """

  def __init__(self, parent=None):
    DeviceWidget.__init__(self, parent)
    self.observedParameterNodeEvents = [vtk.vtkCommand.ModifiedEvent, CardiacDeviceBase.DEVICE_PROFILE_MODIFIED_EVENT]
    self.setup()
    resliceLogic = slicer.modules.volumereslicedriver.logic()
    self.resliceConfig = [
      ('vtkMRMLSliceNodeRed', resliceLogic.MODE_TRANSVERSE),
      ('vtkMRMLSliceNodeGreen', resliceLogic.MODE_CORONAL),
      ('vtkMRMLSliceNodeYellow', resliceLogic.MODE_SAGITTAL)]

  def setup(self):
    self.setLayout(qt.QFormLayout())

    # self.createClosedSegmentsForAlreadyFittedDeviceButton = qt.QPushButton("Create closed segments for already fitted Harmony TCPV valve (temporary?)")
    # #lay.addRow(self.createClosedSegmentsForAlreadyFittedDeviceButton)
    # self.createClosedSegmentsForAlreadyFittedDeviceButton.connect('clicked(bool)', self.onCreateClosedSegmentsForAlreadyFittedHarmonyDevice)

    lay = self.layout()

    self.handlesPerSliceSliderWidget = UIHelper.addSlider({
      "name": "Handles per slice:", "info": "Controls how many handles are generated for device deformation",
      "value": 8, "unit": "", "minimum": 4, "maximum": 12, "singleStep": 2, "pageStep": 1, "decimals": 0}, lay,
      self.onHandlesSettingsChanged)

    self.handlesSpacingSliderWidget = UIHelper.addSlider({
      "name": "Handles spacing:", "info": "Controls distance between handles", "value": 5, "unit": "mm", "minimum": 3,
      "maximum": 15, "singleStep": 1, "pageStep": 1, "decimals": 0}, lay, self.onHandlesSettingsChanged)

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
    self.vesselModelNodeSelector.connect('currentNodeChanged(bool)', self.deformDeviceToVesselWallsButton, 'setEnabled(bool)')

    self.deformDeviceToVesselWallsButton.connect('clicked(bool)', self.onDeformDeviceToVesselWallsClicked)
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

  def enter(self):
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

  def setParameterNode(self, parameterNode):
    DeviceWidget.setParameterNode(self, parameterNode)
    if self.parameterNode:
      self.setupResliceDriver()

  def updateGUIFromMRML(self, caller=None, event=None):
    wasBlocked = self.vesselModelNodeSelector.blockSignals(True)
    self.vesselModelNodeSelector.setCurrentNode(self.logic.getVesselModelNode())
    self.vesselModelNodeSelector.blockSignals(wasBlocked)
    if self.logic.parameterNode:
      wasBlocked = self.handlesPerSliceSliderWidget.blockSignals(True)
      self.handlesPerSliceSliderWidget.value = self.logic.getHandlesPerSlice()
      self.handlesPerSliceSliderWidget.blockSignals(wasBlocked)
      wasBlocked = self.handlesSpacingSliderWidget.blockSignals(True)
      self.handlesSpacingSliderWidget.value = self.logic.getHandlesSpacingMm()
      self.handlesSpacingSliderWidget.blockSignals(wasBlocked)
      numberOfSlices = self.logic.handleProfilePoints.GetNumberOfPoints()-1
    else:
      numberOfSlices = 0
    wasBlocked = self.sliceSelectorSliderWidget.blockSignals(True)
    if numberOfSlices>0:
      self.sliceSelectorSliderWidget.maximum = numberOfSlices
      self.sliceSelectorSliderWidget.setEnabled(True)
    else:
      self.sliceSelectorSliderWidget.maximum = 0
      self.sliceSelectorSliderWidget.setEnabled(False)
    self.sliceSelectorSliderWidget.blockSignals(wasBlocked)
    self.deformDeviceToVesselWallsButton.enabled = (self.vesselModelNodeSelector.currentNode() is not None)

  def onVesselModelNodeSelectionChanged(self):
    self.logic.setVesselModelNode(self.vesselModelNodeSelector.currentNode())
    #self.updateButtonStates()

  def onSliceSelected(self):
    if not self.logic.parameterNode:
      return
    sliceNumber = int(self.sliceSelectorSliderWidget.value)
    controlPointNumber = sliceNumber
    handleMarkupsNodeId = self.logic.parameterNode.GetNodeReference('DeformedHandles').GetID()
    centered = False
    slicer.modules.markups.logic().JumpSlicesToNthPointInMarkup(handleMarkupsNodeId, controlPointNumber, centered)

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
    # VolumeResliceDriver module is provided by SlierIGT extension
    resliceLogic = slicer.modules.volumereslicedriver.logic()
    for nodeName, resliceMode in self.resliceConfig:
      sliceNode = slicer.mrmlScene.GetNodeByID(nodeName)
      resliceLogic.SetDriverForSlice(self.logic.parameterNode.GetNodeReference('PositioningTransform').GetID(), sliceNode)
      resliceLogic.SetModeForSlice(resliceMode, sliceNode)

  def onHandlesSettingsChanged(self):
    self.logic.setHandlesSettings(int(self.handlesPerSliceSliderWidget.value), self.handlesSpacingSliderWidget.value)

  def onDeformDeviceToVesselWallsClicked(self):
    logging.debug("moving device handles to deform to vessel walls...")
    self.logic.deformHandlesToVesselWalls(self.allowDeviceExpansionToVesselWallsCheckbox.isChecked())
