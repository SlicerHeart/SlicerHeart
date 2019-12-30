import ctk, qt, vtk
import slicer
import logging
from CardiacDeviceSimulatorUtils.widgethelper import UIHelper
from CardiacDeviceSimulatorUtils.widgethelper import DeviceWidget

class DevicePositioningWidget(DeviceWidget):
  """
  """

  def __init__(self, parent=None):
    DeviceWidget.__init__(self, parent)
    self.observedParameterNodeEvents = [vtk.vtkCommand.ModifiedEvent]
    self.setup()

  def setup(self):
    self.setLayout(qt.QFormLayout())

    lay = self.layout()

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
    self.processVesselSegmentButton.enabled = bool(self.vesselSegmentSelector.currentSegmentID())


    # Centerline curve node selector
    self.centerlineNodeSelector = slicer.qMRMLNodeComboBox()
    self.centerlineNodeSelector.nodeTypes = ["vtkMRMLMarkupsCurveNode"]
    self.centerlineNodeSelector.setNodeTypeLabel("Centerline", "vtkMRMLMarkupsCurveNode")
    self.centerlineNodeSelector.baseName = "Centerline"
    self.centerlineNodeSelector.selectNodeUponCreation = False
    self.centerlineNodeSelector.addEnabled = False
    self.centerlineNodeSelector.removeEnabled = False
    self.centerlineNodeSelector.noneEnabled = True
    self.centerlineNodeSelector.showHidden = True
    self.centerlineNodeSelector.renameEnabled = True
    self.centerlineNodeSelector.setMRMLScene(slicer.mrmlScene)
    self.centerlineNodeSelector.setToolTip("Select a curve to be used for positioning the device")
    lay.addRow("Centerline: ", self.centerlineNodeSelector)
    self.centerlineNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)",
                                             self.onCenterlineNodeSelectionChanged)

    # Button to position device at closest centerline point
    self.positionDeviceAtCenterlineButton = qt.QPushButton("Position device at centerline")
    lay.addRow(self.positionDeviceAtCenterlineButton)
    self.positionDeviceAtCenterlineButton.connect('clicked(bool)', self.onPositionDeviceAtCenterlineClicked)
    self.positionDeviceAtCenterlineButton.enabled = (self.centerlineNodeSelector.currentNode() is not None)

    # Button to flip device orientation
    self.flipDeviceOrientationButton = qt.QPushButton("Flip device orientation")
    lay.addRow(self.flipDeviceOrientationButton)
    self.flipDeviceOrientationButton.connect('clicked(bool)', self.onFlipDeviceOrientationClicked)
    self.flipDeviceOrientationButton.enabled = (self.centerlineNodeSelector.currentNode() is not None)

    # Pick centerline model
    self.moveDeviceAlongCenterlineSliderWidget = UIHelper.addSlider({
      "name": "Move device along centerline:", "info": "Moves the device along extracted centerline", "value": 0,
      "unit": "", "minimum": 0, "maximum": 100, "singleStep": 0.1, "pageStep": 1, "decimals": 1}, lay,
      self.onMoveDeviceAlongCenterlineSliderChanged)
    self.moveDeviceAlongCenterlineSliderWidget.enabled = (self.centerlineNodeSelector.currentNode() is not None)

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

    self.vesselSegmentSelector.connect('currentNodeChanged(bool)', self.processVesselSegmentButton, 'setEnabled(bool)')
    self.centerlineNodeSelector.connect('currentNodeChanged(bool)', self.positionDeviceAtCenterlineButton, 'setEnabled(bool)')
    self.centerlineNodeSelector.connect('currentNodeChanged(bool)', self.flipDeviceOrientationButton, 'setEnabled(bool)')
    self.centerlineNodeSelector.connect('currentNodeChanged(bool)', self.moveDeviceAlongCenterlineSliderWidget, 'setEnabled(bool)')

  def setParameterNode(self, parameterNode):
    DeviceWidget.setParameterNode(self, parameterNode)

  def updateGUIFromMRML(self, caller=None, event=None):
    positioningTransform = self.parameterNode.GetNodeReference('PositioningTransform') if self.parameterNode else None
    self.devicePositioningPositionSliderWidget.setMRMLTransformNode(positioningTransform)
    self.devicePositioningOrientationSliderWidget.setMRMLTransformNode(positioningTransform)
    self.centerlineNodeSelector.setCurrentNode(self.logic.getCenterlineNode())
    segment = self.logic.getVesselLumenSegment()
    [vesselLumenSegmentationNode, vesselLumenSegmentId] = segment if segment else [None, ""]
    self.vesselSegmentSelector.setCurrentNode(vesselLumenSegmentationNode)
    self.vesselSegmentSelector.setCurrentSegmentID(vesselLumenSegmentId)

  def onCenterlineNodeSelectionChanged(self):
    self.logic.setCenterlineNode(self.centerlineNodeSelector.currentNode())

  def onProcessVesselSegmentClicked(self):
    if slicer.app.majorVersion == 4 and slicer.app.minorVersion <= 8:
      slicer.util.messageBox("Vessel centerline extraction requires Slicer 4.9 or later.")
      return
    self.logic.processVesselSegment()
    self.centerlineNodeSelector.setCurrentNode(self.logic.getCenterlineNode())
    [vesselLumenSegmentationNode, vesselLumenSegmentId] = self.logic.getVesselLumenSegment()

    # Optimize visibility
    vesselLumenModelNode = self.logic.getVesselModelNode()
    if vesselLumenModelNode:
      # hide segment to make the semi-transparent vessel surface visible instead
      vesselLumenSegmentationNode.GetDisplayNode().SetVisibility(False)

  def onPositionDeviceAtCenterlineClicked(self):
    logging.debug("positioning device at centerline endpoint")
    deviceCenter = self.logic.getDeviceCenter()
    normalizedPosition = self.logic.getNormalizedPositionAlongCenterline(deviceCenter)
    sliderValue = int(round(normalizedPosition*100.0))
    self.moveDeviceAlongCenterlineSliderWidget.setValue(sliderValue)
    # Force snapping, even if the slider value did not change
    self.onMoveDeviceAlongCenterlineSliderChanged()

  def onFlipDeviceOrientationClicked(self):
    logging.debug("flipped device orientation")
    self.logic.setDeviceOrientationFlippedOnCenterline(not self.logic.getDeviceOrientationFlippedOnCenterline())
    self.onMoveDeviceAlongCenterlineSliderChanged()  # force refresh

  def onMoveDeviceAlongCenterlineSliderChanged(self):
    sliderValue = self.moveDeviceAlongCenterlineSliderWidget.value
    self.logic.setDeviceNormalizedPositionAlongCenterline(sliderValue * 0.01)

  def onVesselLumenSegmentSelectionChanged(self):
    self.logic.setVesselLumenSegment(self.vesselSegmentSelector.currentNode(), self.vesselSegmentSelector.currentSegmentID())
