from slicer.ScriptedLoadableModule import *
import ctk
import qt
import slicer
import vtk
import numpy as np
import math
from CardiacDeviceSimulator import CardiacDeviceSimulatorWidget, CardiacDeviceSimulatorLogic
from CardiacDeviceSimulatorUtils.widgethelper import UIHelper
from FluoroSimulatorLib.PositionerAngleViewWidget import PositionerAngleViewWidget

import logging
from FluoroDevices.devices import *

#
# FluoroSimulator
#

class FluoroSimulator(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  deviceClasses = [GenericFluoro, BiplaneFluoro]

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Fluoro Simulator"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["CardiacDeviceSimulator"]
    self.parent.contributors = ["Andras Lasso (PerkLab)", "Matt Jolley (UPenn)", "Kyle Sunderland (PerkLab)"]
    self.parent.helpText = """
    Module for evaluating mitral valve clip device placement.
    """
    self.parent.acknowledgementText = """
    This work was supported by NIH R01 HL153166, the Cora Topolewski Cardiac Research Fund at the Children's Hospital of Philadelphia (CHOP),
    a CHOP Frontier Grant (Pediatric Valve Center), and CANARIE's Research Software Program..
    """

    try:
      from CardiacDeviceSimulator import CardiacDeviceSimulatorWidget
      for deviceClass in FluoroSimulator.deviceClasses:
        CardiacDeviceSimulatorWidget.registerDevice(deviceClass)
    except ImportError:
      pass

    slicer.app.connect("startupCompleted()", self.onStartupCompleted)

  def onStartupCompleted(self):
    """
    Initialize module presets after startup completed
    """
    FluoroSimulatorLogic.addVolumeRenderingPreset()
    FluoroSimulatorLogic.addViewLayouts()

#
# FluoroSimulatorWidget
#

class FluoroSimulatorWidget(CardiacDeviceSimulatorWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  DEVICE_POSITIONING_NEEDED = True
  DEVICE_DEFORMATION_NEEDED = False
  DEVICE_QUANTIFICATION_NEEDED = False

  def __init__(self, parent=None, deviceClasses=None):

    CardiacDeviceSimulatorWidget.__init__(self, parent, FluoroSimulator.deviceClasses)
    self.logic = FluoroSimulatorLogic(self)
    self.logic.moduleName = "FluoroSimulator"
    self.deviceControlshortcuts = []

  def setup(self):
    super(FluoroSimulatorWidget, self).setup()
    if not self.setupSuccessful:
      return

    if int(slicer.app.revision) < 29848:
      # Requires fix in markups curve coordinate systems (integrated around April 10, 2021)
      slicer.util.errorDisplay(f"ValveClip Device Simulator module requires Slicer core version\nSlicer-4.13.0-2021-04-16 (rev 29848) or later.",
        detailedText="In earlier Slicer versions, device clip motion may be unstable.")

    #self.devicePositioningWidget.vesselGroupBox.hide()
    self.devicePositioningWidget.parent().hide()

    self.deviceControlSection = ctk.ctkCollapsibleButton()
    self.deviceControlSection.text = "Device control"
    self.layout.insertWidget(3, self.deviceControlSection)
    deviceControlSectionLayout = qt.QVBoxLayout(self.deviceControlSection)

    # Load widget from .ui file (created by Qt Designer)
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/FluoroSimulator.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)
    deviceControlSectionLayout.addWidget(uiWidget)

    self.ui.volumeNodeComboBox.setMRMLScene(slicer.mrmlScene)
    self.ui.volumePropertiesCollapsibleGroupBox.visible = False

    self.ui.focalPointPlaceWidget.findChild("ctkColorPickerButton", "ColorButton").visible = False
    self.ui.focalPointPlaceWidget.deleteAllControlPointsOptionVisible = False
    self.ui.focalPointPlaceWidget.findChild("QAction", "ActionFixedNumberOfControlPoints").visible = False
    self.ui.focalPointPlaceWidget.setMRMLScene(slicer.mrmlScene)

    self.ui.volumeRenderingPresetWidget.setMRMLScene(slicer.mrmlScene)
    self.ui.segmentationComboBox.setMRMLScene(slicer.mrmlScene)
    self.ui.roiNodeSelector.setMRMLScene(slicer.mrmlScene)
    self.ui.softEdgeSlider.setMRMLScene(slicer.mrmlScene)

    for child in self.ui.volumeRenderingPresetWidget.children():
      if child.name == "PresetsLabel" or child.name == "PresetComboBox":
        child.visible = False

    # Display warning if Lights module (provided by Sandbox extension) is not available
    lightsModuleAvailable = hasattr(slicer.modules, 'lights')
    self.ui.sandboxExtensionWarningLabel.setVisible(not lightsModuleAvailable)

    presets = FluoroSimulatorLogic.getVolumeRenderingPresetNames()
    for preset in presets:
      self.ui.volumeRenderingPresetComboBox.addItem(preset, preset)
    self.ui.volumeRenderingPresetComboBox.addItem("CT-X-ray", "CT-X-ray")

    self.setupConnections()

  def setupConnections(self):
    self.ui.volumeNodeComboBox.connect('currentNodeChanged(vtkMRMLNode*)', self.updateMRMLFromGUI)
    self.ui.volumeRenderingPresetComboBox.connect('currentIndexChanged(int)', self.updateMRMLFromGUI)
    self.ui.volumeRenderingPresetWidget.connect("presetOffsetChanged(double, double, bool)", self.onPresetOffsetChanged)
    self.ui.applySegmentationButton.connect("clicked()", self.onApplySegmentationClicked)
    self.ui.resetSegmentationButton.connect("clicked()", self.onResetSegmentationClicked)
    self.ui.frontalHeightSpinBox.connect("valueChanged(int)", self.onImageSpinBoxChanged)
    self.ui.lateralHeightSpinBox.connect("valueChanged(int)", self.onImageSpinBoxChanged)
    self.ui.roiNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onROINodeChanged)
    self.ui.roiNodeSelector.connect('nodeAddedByUser(vtkMRMLNode*)', self.onROINodeAdded)
    self.ui.enableCropCheckBox.connect("clicked()", self.onEnableCropClicked)
    self.ui.displayROICheckBox.connect("clicked()", self.onDisplayROIClicked)
    self.ui.fitROIToVolumeButton.connect("clicked()", self.onFitROIToVolumeClicked)
    self.ui.softEdgeSlider.connect("valueChanged(double)", self.updateMRMLFromGUI)

  def disconnect(self):
    self.ui.volumeNodeComboBox.disconnect('currentNodeChanged(vtkMRMLNode*)', self.updateMRMLFromGUI)
    self.ui.volumeRenderingPresetComboBox.disconnect('currentIndexChanged(int)', self.updateMRMLFromGUI)
    self.ui.volumeRenderingPresetWidget.disconnect("presetOffsetChanged(double, double, bool)", self.onPresetOffsetChanged)
    self.ui.applySegmentationButton.disconnect("clicked()", self.onApplySegmentationClicked)
    self.ui.resetSegmentationButton.disconnect("clicked()", self.onResetSegmentationClicked)
    self.ui.roiNodeSelector.disconnect('currentNodeChanged(vtkMRMLNode*)', self.onROINodeChanged)
    self.ui.roiNodeSelector.disconnect('nodeAddedByUser(vtkMRMLNode*)', self.onROINodeAdded)
    self.ui.enableCropCheckBox.disconnect("clicked()", self.onEnableCropClicked)
    self.ui.displayROICheckBox.disconnect("clicked()", self.onDisplayROIClicked)
    self.ui.fitROIToVolumeButton.disconnect("clicked()", self.onFitROIToVolumeClicked)
    self.ui.softEdgeSlider.disconnect("valueChanged(double)", self.updateMRMLFromGUI)

  def cleanup(self):
    self.removeDeviceControlShortcutKeys()
    CardiacDeviceSimulatorWidget.cleanup(self)
    self.disconnect()

  def updateMRMLFromGUI(self):
    parameterNode = self.logic.getParameterNode()
    if not parameterNode:
      return

    with slicer.util.NodeModify(parameterNode):
      inputVolumeNode = self.ui.volumeNodeComboBox.currentNode()
      oldVolumeNode = parameterNode.GetNodeReference(self.logic.INPUT_VOLUME_REFERENCE)
      parameterNode.SetNodeReferenceID(self.logic.INPUT_VOLUME_REFERENCE, inputVolumeNode.GetID() if inputVolumeNode else None)
      if inputVolumeNode != oldVolumeNode:
        parameterNode.InvokeCustomModifiedEvent(FluoroSimulatorLogic.INPUT_VOLUME_CHANGED_EVENT)

      preset = parameterNode.GetParameter(self.logic.VOLUME_RENDERING_PRESET_PARAMETER_NAME)
      if preset != self.ui.volumeRenderingPresetComboBox.currentText:
        parameterNode.SetParameter(self.logic.VOLUME_RENDERING_PRESET_PARAMETER_NAME, self.ui.volumeRenderingPresetComboBox.currentText)
        parameterNode.InvokeCustomModifiedEvent(FluoroSimulatorLogic.VOLUME_RENDERING_PRESET_CHANGED_EVENT)

      parameterNode.SetParameter(self.logic.FRONTAL_DETECTOR_HEIGHT_PARAMETER, str(self.ui.frontalHeightSpinBox.value))
      parameterNode.SetParameter(self.logic.LATERAL_DETECTOR_HEIGHT_PARAMETER, str(self.ui.lateralHeightSpinBox.value))

      roiNode = self.ui.roiNodeSelector.currentNode()
      self.logic.setVolumeRenderingROINode(roiNode)

      softEdgeMm = self.ui.softEdgeSlider.value
      parameterNode.SetParameter(self.logic.SOFT_EDGE_MM_PARAMETER, str(softEdgeMm))

  def updateGUIFromMRML(self, caller=None, event=None):
    """
    Set selections and other settings on the GUI based on the parameter node.
    """
    # Get parameter node
    parameterNode = self.logic.getParameterNode()

    wasBlocking = self.ui.volumeNodeComboBox.blockSignals(True)
    volumeNode = parameterNode.GetNodeReference(self.logic.INPUT_VOLUME_REFERENCE) if parameterNode else None
    self.ui.volumeNodeComboBox.setCurrentNode(volumeNode)
    self.ui.volumeNodeComboBox.enabled = not parameterNode is None
    self.ui.volumeNodeComboBox.blockSignals(wasBlocking)

    preset = parameterNode.GetParameter(self.logic.VOLUME_RENDERING_PRESET_PARAMETER_NAME)
    index = self.ui.volumeRenderingPresetComboBox.findData(preset)
    wasBlocking = self.ui.volumeRenderingPresetComboBox.blockSignals(True)
    self.ui.volumeRenderingPresetComboBox.currentIndex = index
    self.ui.volumeRenderingPresetComboBox.blockSignals(wasBlocking)

    volumePropertyNode = None
    displayNode = None
    volumeToDisplayNode = self.logic.getVolumeToDisplay()
    if volumeToDisplayNode:
      for i in range(volumeToDisplayNode.GetNumberOfDisplayNodes()):
        displayNode = volumeToDisplayNode.GetNthDisplayNode(i)
        if not displayNode or not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
          continue
        roleAttribute = displayNode.GetAttribute(self.logic.VOLUME_RENDERING_ROLE_ATTRIBUTE_NAME)
        if roleAttribute == self.logic.VOLUME_RENDERING_ROLE_X_RAY:
          volumePropertyNode = displayNode.GetVolumePropertyNode()
          break

    wasBlocking = self.ui.volumePropertyNodeWidget.blockSignals(True)
    self.ui.volumePropertyNodeWidget.setMRMLVolumePropertyNode(volumePropertyNode)
    self.ui.volumePropertyNodeWidget.blockSignals(False)

    wasBlocking = self.ui.volumeRenderingPresetWidget.blockSignals(True)
    self.ui.volumeRenderingPresetWidget.setMRMLVolumePropertyNode(volumePropertyNode)
    self.ui.volumeRenderingPresetWidget.blockSignals(False)

    focalPointNode = parameterNode.GetNodeReference(self.logic.FOCAL_POINT_REFERENCE if parameterNode else None)
    if focalPointNode != self.ui.focalPointPlaceWidget.currentNode():
      self.ui.focalPointPlaceWidget.setCurrentNode(focalPointNode)

    wasBlocking = self.ui.frontalHeightSpinBox.blockSignals(True)
    self.ui.frontalHeightSpinBox.value = int(parameterNode.GetParameter(self.logic.FRONTAL_DETECTOR_HEIGHT_PARAMETER))
    self.ui.frontalHeightSpinBox.blockSignals(wasBlocking)

    wasBlocking = self.ui.lateralHeightSpinBox.blockSignals(True)
    self.ui.lateralHeightSpinBox.value = int(parameterNode.GetParameter(self.logic.LATERAL_DETECTOR_HEIGHT_PARAMETER))
    self.ui.lateralHeightSpinBox.blockSignals(wasBlocking)

    roiNode = self.logic.getVolumeRenderingROINode()

    wasBlocking = self.ui.roiNodeSelector.blockSignals(True)
    self.ui.roiNodeSelector.setCurrentNode(roiNode)
    self.ui.roiNodeSelector.blockSignals(wasBlocking)

    wasBlocking = self.ui.displayROICheckBox.blockSignals(True)
    self.ui.displayROICheckBox.checked = roiNode.GetDisplayVisibility() if roiNode else False
    self.ui.displayROICheckBox.enabled = roiNode is not None
    self.ui.displayROICheckBox.blockSignals(wasBlocking)

    cropping = False
    vrDisplayNode = None
    if volumeToDisplayNode:
      for i in range(volumeToDisplayNode.GetNumberOfDisplayNodes()):
        displayNode = volumeToDisplayNode.GetNthDisplayNode(i)
        if displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
          vrDisplayNode = displayNode
          break
    if vrDisplayNode:
      cropping = vrDisplayNode.GetCroppingEnabled()
    wasBlocking = self.ui.enableCropCheckBox.blockSignals(True)
    self.ui.enableCropCheckBox.checked = cropping
    self.ui.enableCropCheckBox.enabled = roiNode is not None
    self.ui.enableCropCheckBox.blockSignals(wasBlocking)

    wasBlocking = self.ui.enableCropCheckBox.blockSignals(True)
    softEdgeMm = float(parameterNode.GetParameter(self.logic.SOFT_EDGE_MM_PARAMETER))
    self.ui.softEdgeSlider.value = softEdgeMm
    self.ui.enableCropCheckBox.blockSignals(wasBlocking)

    self.ui.fitROIToVolumeButton.enabled = roiNode is not None

  def onImageSpinBoxChanged(self):
    self.updateMRMLFromGUI()
    self.logic.renderToVolume()

  def onParameterNodeSelectionChanged(self, node=None):
    super().onParameterNodeSelectionChanged()
    self.updateGUIFromMRML()

  def onDevicePlacementParameterChanged(self, name, value):
    self.logic.setDevicePlacementParameter(name, value)

  def onPresetOffsetChanged(self, x, y, dontMoveFirstAndLast):
    self.ui.volumePropertyNodeWidget.moveAllPoints(x,y,dontMoveFirstAndLast)
    self.logic.renderToVolume()

  def onApplySegmentationClicked(self):
    currentNode = self.ui.segmentationComboBox.currentNode()
    if currentNode is None:
      return
    if currentNode.IsA("vtkMRMLSegmentationNode"):
      self.logic.addSegmentationToModifiedVolume(currentNode, self.ui.segmentationReplaceValueSpinBox.value)
    elif currentNode.IsA("vtkMRMLModelNode"):
      self.logic.addModelToModifiedVolume(currentNode, self.ui.segmentationReplaceValueSpinBox.value)

  def onResetSegmentationClicked(self):
    self.logic.resetModifiedVolume()

  def onROINodeChanged(self, roiNode):
      self.logic.setVolumeRenderingROINode(roiNode)
      self.updateGUIFromMRML()

  def onROINodeAdded(self, roiNode):
    if roiNode is None:
      return
    roiNode.CreateDefaultDisplayNodes()
    self.logic.setVolumeRenderingROINode(roiNode)
    self.logic.fitROINodeToVolume()
    self.updateGUIFromMRML()

  def onDisplayROIClicked(self):
    self.logic.setROIVisibility(self.ui.displayROICheckBox.checked)

  def onEnableCropClicked(self):
    self.logic.setVolumeRenderingCropEnabled(self.ui.enableCropCheckBox.checked)

  def onFitROIToVolumeClicked(self):
    self.logic.fitROINodeToVolume()

  def installDeviceControlShortcutKeys(self):
    logging.debug('installShortcutKeys: '+str(type(self)))
    self.removeDeviceControlShortcutKeys()
    smallStep = 1
    largeStep = 5
    # TODO: update for C-arm simulation
    keysAndCallbacks = (
      ('w', lambda: self.adjustSlider("sleeveTipDeflectionML",largeStep)),
      ('s', lambda: self.adjustSlider("sleeveTipDeflectionML",-largeStep)),
      ('d', lambda: self.adjustSlider("sleeveTipDeflectionAP",largeStep)),
      ('a', lambda: self.adjustSlider("sleeveTipDeflectionAP",-largeStep)),
      ('e', lambda: self.adjustSlider("sleeveTranslation",largeStep)),
      ('q', lambda: self.adjustSlider("sleeveTranslation",-largeStep)),
      ('t', lambda: self.adjustSlider("catheterTranslation",largeStep)),
      ('g', lambda: self.adjustSlider("catheterTranslation",-largeStep)),
      ('h', lambda: self.adjustSlider("catheterRotation",largeStep)),
      ('f', lambda: self.adjustSlider("catheterRotation",-largeStep)),
      ('l', lambda: self.adjustSlider("guideRotation",largeStep)),
      ('j', lambda: self.adjustSlider("guideRotation",-largeStep)),
      ('i', lambda: self.adjustSlider("guideTipDeflection",largeStep)),
      ('k', lambda: self.adjustSlider("guideTipDeflection",-largeStep)),
      ('Shift+w', lambda: self.adjustSlider("sleeveTipDeflectionML",smallStep)),
      ('Shift+s', lambda: self.adjustSlider("sleeveTipDeflectionML",-smallStep)),
      ('Shift+d', lambda: self.adjustSlider("sleeveTipDeflectionAP",smallStep)),
      ('Shift+a', lambda: self.adjustSlider("sleeveTipDeflectionAP",-smallStep)),
      ('Shift+e', lambda: self.adjustSlider("sleeveTranslation",smallStep)),
      ('Shift+q', lambda: self.adjustSlider("sleeveTranslation",-smallStep)),
      ('Shift+t', lambda: self.adjustSlider("catheterTranslation",smallStep)),
      ('Shift+g', lambda: self.adjustSlider("catheterTranslation",-smallStep)),
      ('Shift+h', lambda: self.adjustSlider("catheterRotation",smallStep)),
      ('Shift+f', lambda: self.adjustSlider("catheterRotation",-smallStep)),
      ('Shift+l', lambda: self.adjustSlider("guideRotation",smallStep)),
      ('Shift+j', lambda: self.adjustSlider("guideRotation",-smallStep)),
      ('Shift+i', lambda: self.adjustSlider("guideTipDeflection",smallStep)),
      ('Shift+k', lambda: self.adjustSlider("guideTipDeflection",-smallStep)),
      )
    for key,callback in keysAndCallbacks:
      shortcut = qt.QShortcut(slicer.util.mainWindow())
      shortcut.setKey(qt.QKeySequence(key))
      shortcut.connect('activated()', callback)
      self.deviceControlshortcuts.append(shortcut)

  def removeDeviceControlShortcutKeys(self):
    logging.debug('removeShortcutKeys')
    for shortcut in self.deviceControlshortcuts:
      shortcut.disconnect('activated()')
      shortcut.setParent(None)
    self.deviceControlshortcuts = []

  def adjustSlider(self, paramName, offset):
    if not self.logic.getDeviceClass() or not self.logic.parameterNode:
      return
    deviceClassID = self.logic.parameterNode.GetParameter('DeviceClassId')
    deviceImplantWidget = self.deviceSelectorWidget.deviceWidgetFrames[deviceClassID]
    sliderWidget = getattr(deviceImplantWidget, "{}SliderWidget".format(paramName))
    sliderWidget.value += offset

  def enter(self):
    """
    Called each time the user opens this module.
    """
    super().enter()
    self.installDeviceControlShortcutKeys()

  def exit(self):
    """
    Called each time the user opens a different module.
    """
    super().exit()
    self.removeDeviceControlShortcutKeys()

  def onCurvatureCalculationToggled(self, on):
    # Enable curvature calculation and scalar color display
    self.logic.setCurvatureCalculationEnabled(on)

    # Setup curvature measurement display
    self.ui.curvatureValuesFrame.visible = on

    # Manage observations
    guideCurveNode = self.logic.parameterNode.GetNodeReference('GuideCurve')
    for index in range(guideCurveNode.GetNumberOfMeasurements()):
      currentMeasurement = guideCurveNode.GetNthMeasurement(index)
      if not currentMeasurement or not currentMeasurement.GetEnabled():
        continue
      if currentMeasurement.GetName() == slicer.vtkCurveMeasurementsCalculator.GetMeanCurvatureName():
        if on:
          self.logic.guideCurvatureMeanObserverTag = currentMeasurement.AddObserver(
            vtk.vtkCommand.ModifiedEvent, lambda caller, event: self.ui.guideCurvatureMeanValueLabel.setText(caller.GetValueWithUnitsAsPrintableString()))
          self.ui.guideCurvatureMeanValueLabel.setText(currentMeasurement.GetValueWithUnitsAsPrintableString())
        else:
          currentMeasurement.RemoveObserver(self.logic.guideCurvatureMeanObserverTag)
      elif currentMeasurement.GetName() == slicer.vtkCurveMeasurementsCalculator.GetMaxCurvatureName():
        if on:
          self.logic.guideCurvatureMaxObserverTag = currentMeasurement.AddObserver(
            vtk.vtkCommand.ModifiedEvent, lambda caller, event: self.ui.guideCurvatureMaxValueLabel.setText(caller.GetValueWithUnitsAsPrintableString()))
          self.ui.guideCurvatureMaxValueLabel.setText(currentMeasurement.GetValueWithUnitsAsPrintableString())
        else:
          currentMeasurement.RemoveObserver(self.logic.guideCurvatureMaxObserverTag)
    centerlineNode = self.logic.getCenterlineNode()
    for index in range(centerlineNode.GetNumberOfMeasurements()):
      currentMeasurement = centerlineNode.GetNthMeasurement(index)
      if not currentMeasurement or not currentMeasurement.GetEnabled():
        continue
      if currentMeasurement.GetName() == slicer.vtkCurveMeasurementsCalculator.GetMeanCurvatureName():
        if on:
          self.logic.centerlineCurvatureMeanObserverTag = currentMeasurement.AddObserver(
            vtk.vtkCommand.ModifiedEvent, lambda caller, event: self.ui.catheterCurvatureMeanValueLabel.setText(caller.GetValueWithUnitsAsPrintableString()))
          self.ui.catheterCurvatureMeanValueLabel.setText(currentMeasurement.GetValueWithUnitsAsPrintableString())
        else:
          currentMeasurement.RemoveObserver(self.logic.centerlineCurvatureMeanObserverTag)
      elif currentMeasurement.GetName() == slicer.vtkCurveMeasurementsCalculator.GetMaxCurvatureName():
        if on:
          self.logic.centerlineCurvatureMaxObserverTag = currentMeasurement.AddObserver(
            vtk.vtkCommand.ModifiedEvent, lambda caller, event: self.ui.catheterCurvatureMaxValueLabel.setText(caller.GetValueWithUnitsAsPrintableString()))
          self.ui.catheterCurvatureMaxValueLabel.setText(currentMeasurement.GetValueWithUnitsAsPrintableString())
        else:
          currentMeasurement.RemoveObserver(self.logic.centerlineCurvatureMaxObserverTag)

  def onCurvatureColorInterpolationToggled(self, on):
    # Get parameter node
    parameterNode = self.logic.getParameterNode()
    if not parameterNode:
      return

    parameterNode.SetParameter('CurvatureColorInterpolation', str(on))

    self.logic.setupCurvatureColorNodes()


class FluoroSimulatorLogic(CardiacDeviceSimulatorLogic):

  C_ARM_FRONTAL_VIEW_NAME = "CArmFrontal"
  C_ARM_LATERAL_VIEW_NAME = "CArmLateral"
  C_ARM_FRONTAL_SLICE_VIEW_NAME = f"{C_ARM_FRONTAL_VIEW_NAME}Slice"
  C_ARM_LATERAL_SLICE_VIEW_NAME = f"{C_ARM_LATERAL_VIEW_NAME}Slice"

  RED_SLICE_LAYOUT_ITEM = """
    <item>
      <view class="vtkMRMLSliceNode" singletontag="Red">
        <property name="orientation" action="default">Axial</property>
        <property name="viewlabel" action="default">R</property>
        <property name="viewcolor" action="default">#F34A33</property>
      </view>
    </item>"""

  GREEN_SLICE_LAYOUT_ITEM = """
    <item>
     <view class="vtkMRMLSliceNode" singletontag="Green">
      <property name="orientation" action="default">Coronal</property>
      <property name="viewlabel" action="default">G</property>
      <property name="viewcolor" action="default">#6EB04B</property>
     </view>
    </item>"""

  YELLOW_SLICE_LAYOUT_ITEM = """
    <item>
      <view class="vtkMRMLSliceNode" singletontag="Yellow">
        <property name="orientation" action="default">Sagittal</property>
        <property name="viewlabel" action="default">Y</property>
        <property name="viewcolor" action="default">#EDD54C</property>
     </view>
    </item>"""

  THREED_VIEW_LAYOUT_ITEM = """
    <item>
     <view class="vtkMRMLViewNode" singletontag="1">
       <property name="viewlabel" action="default">1</property>"
     </view>
    </item>
    """
  C_ARM_FRONTAL_LAYOUT_ITEM = f"""
    <item>
     <view class="vtkMRMLViewNode" singletontag="{C_ARM_FRONTAL_VIEW_NAME}">
       <property name="viewlabel" action="default">F</property>"
       <property name="viewcolor" action="default">#C3B1E1</property>
     </view>
    </item>
    """
  C_ARM_FRONTAL_SLICE_LAYOUT_ITEM = f"""
    <item>
      <view class="vtkMRMLSliceNode" singletontag="{C_ARM_FRONTAL_SLICE_VIEW_NAME}">
        <property name="orientation" action="default">Axial</property>
        <property name="viewlabel" action="default">C</property>
        <property name="viewcolor" action="default">#C3B1E1</property>
     </view>
    </item>"""
  C_ARM_LATERAL_LAYOUT_ITEM = f"""
    <item>
      <view class="vtkMRMLViewNode" singletontag="{C_ARM_LATERAL_VIEW_NAME}">
        <property name="viewlabel" action="default">L</property>"
        <property name="viewcolor" action="default">#FAC898</property>
      </view>
    </item>
    """
  C_ARM_LATERAL_SLICE_LAYOUT_ITEM = f"""
    <item>
      <view class="vtkMRMLSliceNode" singletontag="{C_ARM_LATERAL_SLICE_VIEW_NAME}">
        <property name="orientation" action="default">Axial</property>
        <property name="viewlabel" action="default">L</property>
        <property name="viewcolor" action="default">#FAC898</property>
     </view>
    </item>"""

  C_ARM_GENERIC_LAYOUT_DESCRIPTION = f"""
    <layout type="vertical" split="true" >
      <item splitSize="500">
        <layout type="horizontal">
          {THREED_VIEW_LAYOUT_ITEM}
          {C_ARM_FRONTAL_SLICE_LAYOUT_ITEM}
        </layout>
      </item>
      <item splitSize="350">
        <layout type="horizontal">
          {RED_SLICE_LAYOUT_ITEM}
          {GREEN_SLICE_LAYOUT_ITEM}
          {YELLOW_SLICE_LAYOUT_ITEM}
        </layout>
      </item>
      <item splitSize="0">
        <layout type="horizontal">
          {C_ARM_FRONTAL_LAYOUT_ITEM}
        </layout>
      </item>
    </layout>
    """
  C_ARM_GENERIC_LAYOUT_ID = 1020

  C_ARM_BIPLANE_LAYOUT_DESCRIPTION = f"""
    <layout type="vertical" split="true" >
      <item splitSize="500">
        <layout type="horizontal">
          {THREED_VIEW_LAYOUT_ITEM}
          {C_ARM_FRONTAL_SLICE_LAYOUT_ITEM}
          {C_ARM_LATERAL_SLICE_LAYOUT_ITEM}
        </layout>
      </item>
      <item splitSize="350">
        <layout type="horizontal">
          {RED_SLICE_LAYOUT_ITEM}
          {GREEN_SLICE_LAYOUT_ITEM}
          {YELLOW_SLICE_LAYOUT_ITEM}
        </layout>
      </item>
      <item splitSize="0">
        <layout type="horizontal">
          {C_ARM_FRONTAL_LAYOUT_ITEM}
          {C_ARM_LATERAL_LAYOUT_ITEM}
        </layout>
      </item>
    </layout>
    """
  C_ARM_BIPLANE_LAYOUT_ID = 1021

  INPUT_VOLUME_CHANGED_EVENT = 20500
  VOLUME_RENDERING_PRESET_CHANGED_EVENT = 20501

  VOLUME_RENDERING_ROLE_ATTRIBUTE_NAME = "VolumeRenderingRole"
  VOLUME_RENDERING_ROLE_CT_HIGH_CONTRAST = "CTHighContrast"
  VOLUME_RENDERING_ROLE_X_RAY = "XRay"

  VOLUME_RENDERING_PRESET_PARAMETER_NAME = "VolumeRenderingPreset"

  INPUT_VOLUME_REFERENCE = "InputVolume"
  MODIFIED_VOLUME_REFERENCE = "ModifiedVolume"
  CT_TO_TABLE_TRANSFORM_REFERENCE = "ct-to-table"
  GANTRY_TO_RAS_REFERENCE = "gantry-to-ras"
  FOCAL_POINT_REFERENCE = "FocalPoint"

  POSITIONING_TRANSFORM_REFERENCE = "PositioningTransform"
  FRONTAL_CAMERA_TRANSFORM_REFERENCE = "frontal-camera-to-frontal-detector"
  LATERAL_CAMERA_TRANSFORM_REFERENCE = "lateral-camera-to-lateral-detector"
  TABLE_LONGITUDINAL_TRANSFORM_REFERENCE = "table-longitudinal-transform"

  FRONTAL_IMAGE_REFERENCE = "CArmFrontalXRay"
  LATERAL_IMAGE_REFERENCE = "CArmLateralXRay"

  FRONTAL_DETECTOR_HEIGHT_MM = 400.4 # Determined by measuring the model
  FRONTAL_DETECTOR_WIDTH_MM = 293.7 # Determined by measuring the model

  LATERAL_DETECTOR_HEIGHT_MM = 232.5 # Determined by measuring the model
  LATERAL_DETECTOR_WIDTH_MM = 234.5 # Determined by measuring the model

  FRONTAL_DETECTOR_HEIGHT_PARAMETER = "FrontalDetectorHeight"
  FRONTAL_DETECTOR_HEIGHT_DEFAULT_PX = int(FRONTAL_DETECTOR_HEIGHT_MM * 2)
  LATERAL_DETECTOR_HEIGHT_PARAMETER = "LateralDetectorHeight"
  LATERAL_DETECTOR_HEIGHT_DEFAULT_PX = int(LATERAL_DETECTOR_HEIGHT_MM * 2)

  SOFT_EDGE_MM_PARAMETER = "SoftEdgeMm"

  def __init__(self, widgetInstance, parent=None):
    CardiacDeviceSimulatorLogic.__init__(self, parent)

    # To connect parameter node changes to widget update function
    self.FluoroSimulatorWidget = widgetInstance

    layoutManager = slicer.app.layoutManager()
    layoutManager.connect('layoutChanged(int)', self.onLayoutChanged)
    self.positionerAngleViewWidgets = {}

    self.renderTimer = qt.QTimer()
    renderFPS = 15
    self.renderTimer.setInterval(1000.0 / renderFPS)
    self.renderTimer.setSingleShot(True)
    self.renderTimer.connect("timeout()", self.renderToVolumeInternal)
    self.renderRequested = False

    self.updateCurrentLayout()

  @classmethod
  def addViewLayouts(cls):
    layoutManager = slicer.app.layoutManager()
    layoutLogic = layoutManager.layoutLogic()
    if not layoutLogic.GetLayoutNode().SetLayoutDescription(FluoroSimulatorLogic.C_ARM_GENERIC_LAYOUT_ID, FluoroSimulatorLogic.C_ARM_GENERIC_LAYOUT_DESCRIPTION):
      layoutLogic.GetLayoutNode().AddLayoutDescription(FluoroSimulatorLogic.C_ARM_GENERIC_LAYOUT_ID, FluoroSimulatorLogic.C_ARM_GENERIC_LAYOUT_DESCRIPTION)
    if not layoutLogic.GetLayoutNode().SetLayoutDescription(FluoroSimulatorLogic.C_ARM_BIPLANE_LAYOUT_ID, FluoroSimulatorLogic.C_ARM_BIPLANE_LAYOUT_DESCRIPTION):
      layoutLogic.GetLayoutNode().AddLayoutDescription(FluoroSimulatorLogic.C_ARM_BIPLANE_LAYOUT_ID, FluoroSimulatorLogic.C_ARM_BIPLANE_LAYOUT_DESCRIPTION)

  @classmethod
  def getVolumeRenderingPresetNames(cls):
    return [
      "FluoroRenderingPreset_01",
      "FluoroRenderingPreset_02",
      "FluoroRenderingPreset_03",
    ]

  @classmethod
  def addVolumeRenderingPreset(cls):
    presetNames = FluoroSimulatorLogic.getVolumeRenderingPresetNames()
    for presetName in presetNames:
      fluoroSimulatorDir = os.path.dirname(slicer.modules.fluorosimulator.path)
      fluoroRenderingFile = os.path.join(fluoroSimulatorDir, f'Resources/VolumeRendering/{presetName}.vp')
      fluoroVolumeProperty = slicer.modules.volumerendering.logic().AddVolumePropertyFromFile(fluoroRenderingFile)
      slicer.modules.volumerendering.logic().AddPreset(fluoroVolumeProperty)
      slicer.mrmlScene.RemoveNode(fluoroVolumeProperty)

  def onDeviceClassModified(self, caller=None, event=None):
    CardiacDeviceSimulatorLogic.onDeviceClassModified(self, caller, event)

    # Change clip to solid display
    deviceModelNode = self.parameterNode.GetNodeReference('OriginalModel')
    displayNode = deviceModelNode.GetDisplayNode()
    displayNode.SetRepresentation(displayNode.SurfaceRepresentation)
    displayNode.SetEdgeVisibility(False)
    displayNode.SetColor(0.5, 0.5, 0.5)

    # Setup device model
    self.setupDeviceModel()

  def setParameterNode(self, parameterNode):
    # Remove old parameter node observations
    if self.parameterNode is not None:
      self.removeObserver(self.parameterNode, vtk.vtkCommand.ModifiedEvent, self.FluoroSimulatorWidget.updateGUIFromMRML)
      self.removeObserver(self.parameterNode, CardiacDeviceBase.DEVICE_CLASS_MODIFIED_EVENT, lambda caller, event: self.computeCenterline())
      self.removeObserver(self.parameterNode, FluoroSimulatorLogic.INPUT_VOLUME_CHANGED_EVENT, lambda caller, event: self.onVolumeNodeChanged())
      self.removeObserver(self.parameterNode, FluoroSimulatorLogic.VOLUME_RENDERING_PRESET_CHANGED_EVENT, lambda caller, event: self.onPresetChanged())

    # Set parameter node in base class (and set parameter node member variable)
    CardiacDeviceSimulatorLogic.setParameterNode(self, parameterNode)
    if parameterNode:
      self.setDefaultParameters(parameterNode)

    if parameterNode:
      # Setup device model
      self.setupDeviceModel()
      self.addObserver(self.parameterNode, vtk.vtkCommand.ModifiedEvent, self.FluoroSimulatorWidget.updateGUIFromMRML)
      self.addObserver(self.parameterNode, FluoroSimulatorLogic.INPUT_VOLUME_CHANGED_EVENT, lambda caller, event: self.onVolumeNodeChanged())
      self.addObserver(self.parameterNode, FluoroSimulatorLogic.VOLUME_RENDERING_PRESET_CHANGED_EVENT, lambda caller, event: self.onPresetChanged())
      self.updateFocalPointObservers()
      self.onVolumeNodeChanged()

  def setDefaultParameters(self, parameterNode):
    if not parameterNode.GetParameter(self.FRONTAL_DETECTOR_HEIGHT_PARAMETER):
      parameterNode.SetParameter(self.FRONTAL_DETECTOR_HEIGHT_PARAMETER, str(self.FRONTAL_DETECTOR_HEIGHT_DEFAULT_PX))
    if not parameterNode.GetParameter(self.LATERAL_DETECTOR_HEIGHT_PARAMETER):
      parameterNode.SetParameter(self.LATERAL_DETECTOR_HEIGHT_PARAMETER, str(self.LATERAL_DETECTOR_HEIGHT_DEFAULT_PX))
    if not parameterNode.GetParameter(self.SOFT_EDGE_MM_PARAMETER):
      parameterNode.SetParameter(self.SOFT_EDGE_MM_PARAMETER, str(0.0))

  def updateFocalPointObservers(self):
    """
    Update observers on the focal point markups node.
    """
    self.removeObservers(self.onFocalPointChanged)
    if self.parameterNode is None:
      return

    focalPointNode = self.getFocalPointNode()
    if focalPointNode is None:
      return

    self.addObserver(focalPointNode, slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, self.onFocalPointChanged)
    self.addObserver(focalPointNode, slicer.vtkMRMLMarkupsNode.PointPositionUndefinedEvent, self.onFocalPointChanged)
    self.addObserver(focalPointNode, slicer.vtkMRMLMarkupsNode.PointEndInteractionEvent, self.onFocalPointChanged)
    self.onFocalPointChanged(focalPointNode)

  def updateGantryToRASTransform(self):
    """
    Updates the gantry_to_ras transform to account for the table motion.
    The focal point of the table coordinate system (0,0,0) should remain aligned with the focal point fiducial position in RAS
    This ensures that that the position of the table remains the same relative to the RAS volume.
    This motion shifts the entire gantry model in RAS.
    """
    tableToRAS = vtk.vtkGeneralTransform()
    tableLongitudinalTransform = self.parameterNode.GetNodeReference(self.TABLE_LONGITUDINAL_TRANSFORM_REFERENCE)
    slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(tableLongitudinalTransform, None, tableToRAS)

    tableOrigin_RAS = [0.0, 0.0, 0.0]
    tableOrigin_RAS = np.array(tableToRAS.TransformPoint(tableOrigin_RAS))

    gantryToRASTransformNode = self.parameterNode.GetNodeReference(self.GANTRY_TO_RAS_REFERENCE)
    if gantryToRASTransformNode is None:
      gantryToRASTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", self.GANTRY_TO_RAS_REFERENCE)
      self.parameterNode.SetNodeReferenceID(self.GANTRY_TO_RAS_REFERENCE, gantryToRASTransformNode.GetID())

    focalPoint_RAS = np.zeros(3)
    focalPointNode = self.getFocalPointNode()
    if focalPointNode.GetNumberOfControlPoints() > 0 and focalPointNode.GetNthControlPointPositionStatus(0) == slicer.vtkMRMLMarkupsNode.PositionDefined:
      focalPoint_RAS = np.array(focalPointNode.GetNthControlPointPositionWorld(0))

    gantryToRASMatrix = vtk.vtkMatrix4x4()
    gantryToRASTransformNode.GetMatrixTransformToParent(gantryToRASMatrix)

    newGantryToRASTransform = vtk.vtkTransform()
    newGantryToRASTransform.PostMultiply()
    newGantryToRASTransform.Concatenate(gantryToRASMatrix)
    newGantryToRASTransform.Translate(focalPoint_RAS - tableOrigin_RAS)
    gantryToRASTransformNode.SetMatrixTransformToParent(newGantryToRASTransform.GetMatrix())

    positioningTransform = self.parameterNode.GetNodeReference(self.POSITIONING_TRANSFORM_REFERENCE)
    if positioningTransform:
      positioningTransform.SetAndObserveTransformNodeID(gantryToRASTransformNode.GetID())

  def onFocalPointChanged(self, focalPointNode, event=None):
    """
    Called when the position of the focal point fiducial is changed.
    """
    self.updateGantryToRASTransform()
    self.renderToVolume()

  def getFocalPointNode(self):
    """
    Returns the focal point node for the current parameter node.
    """
    if self.parameterNode is None:
      return None
    focalPointNode = self.parameterNode.GetNodeReference(self.FOCAL_POINT_REFERENCE)
    if focalPointNode is None:
      focalPointNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "FocalPoint")
      focalPointNode.SetMaximumNumberOfControlPoints(1)
      focalPointNode.SetRequiredNumberOfControlPoints(1)
      focalPointNode.SetControlPointLabelFormat("Focal point")
      focalPointNode.CreateDefaultDisplayNodes()
      focalPointNode.GetDisplayNode().SetViewNodeIDs(["vtkMRMLViewNode1", "vtkMRMLSliceNodeRed", "vtkMRMLSliceNodeGreen", "vtkMRMLSliceNodeYellow"])
      self.parameterNode.SetNodeReferenceID(self.FOCAL_POINT_REFERENCE, focalPointNode.GetID())
    return focalPointNode

  def setupDeviceModel(self):
    parameterNode = self.getParameterNode()
    if not parameterNode:
      logging.error('Unable to access parameter node for setting up device model')
      return

    deviceClass = self.getDeviceClass()
    if deviceClass:
      self.getDeviceClass().setupDeviceModel()

    if deviceClass and deviceClass.ID == GenericFluoro.ID:
      slicer.app.layoutManager().setLayout(self.C_ARM_GENERIC_LAYOUT_ID)
    elif deviceClass and deviceClass.ID == BiplaneFluoro.ID:
      slicer.app.layoutManager().setLayout(self.C_ARM_BIPLANE_LAYOUT_ID)

    with slicer.util.RenderBlocker():
      self.setupCameraTransforms()
      self.updateVolumeRendering()
      self.updateAllCameraPositions()
      self.updateGantryToRASTransform()
      self.renderToVolume()
    self.parameterNode.Modified() # Trigger GUI update

  def onVolumeNodeChanged(self):
    """
    Called when the input volume node is changed
    """
    self.updateVolumeRendering()
    self.removeObservers(self.onVolumeNodeModified)
    inputVolume = self.getInputVolumeNode()
    if inputVolume:
      self.addObserver(inputVolume, slicer.vtkMRMLScalarVolumeNode.ImageDataModifiedEvent , self.onVolumeNodeModified)

  def onVolumeNodeModified(self, caller=None, event=None):
    self.renderToVolume()

  def onPresetChanged(self):
    volumeToDisplayNode = self.getVolumeToDisplay()
    if volumeToDisplayNode is None:
      return

    xRayDisplayNode = self.getVolumeRenderingDisplayNode(volumeToDisplayNode, self.VOLUME_RENDERING_ROLE_X_RAY)
    if xRayDisplayNode is None:
      return

    presetName = self.parameterNode.GetParameter(self.VOLUME_RENDERING_PRESET_PARAMETER_NAME)
    self.updateVolumePropertyFromPreset(xRayDisplayNode.GetVolumePropertyNode(), presetName)
    self.updateCurrentLayout()

  def setupCameraTransforms(self):
    """
    Create and initialize transform for controlling camera position.
    """
    fluoroSimulatorDir = os.path.dirname(slicer.modules.fluorosimulator.path)

    frontalCameraTransform = self.parameterNode.GetNodeReference(self.FRONTAL_CAMERA_TRANSFORM_REFERENCE)
    if frontalCameraTransform is None:
      frontalCameraTransform = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", self.FRONTAL_CAMERA_TRANSFORM_REFERENCE)
      frontalCameraTransform.AddDefaultStorageNode()
      self.parameterNode.SetNodeReferenceID(self.FRONTAL_CAMERA_TRANSFORM_REFERENCE, frontalCameraTransform.GetID())

      frontalCameraTransformFilename = os.path.join(fluoroSimulatorDir, 'Resources/Transforms/frontal_camera_to_frontal_source.h5')
      storageNode = frontalCameraTransform.GetStorageNode()
      storageNode.SetFileName(frontalCameraTransformFilename)
      storageNode.ReadData(frontalCameraTransform)
      slicer.mrmlScene.RemoveNode(storageNode)

    frontalDetectorTransformID = self.parameterNode.GetNodeReferenceID("frontal-arm-c-rotation-transform")
    frontalCameraTransform.SetAndObserveTransformNodeID(frontalDetectorTransformID)

    lateralCameraTransform = self.parameterNode.GetNodeReference(self.LATERAL_CAMERA_TRANSFORM_REFERENCE)
    if lateralCameraTransform is None:
      lateralCameraTransform = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", self.LATERAL_CAMERA_TRANSFORM_REFERENCE)
      lateralCameraTransform.AddDefaultStorageNode()
      self.parameterNode.SetNodeReferenceID(self.LATERAL_CAMERA_TRANSFORM_REFERENCE, lateralCameraTransform.GetID())

      lateralCameraTransformFilename = os.path.join(fluoroSimulatorDir, 'Resources/Transforms/lateral_camera_to_lateral_source.h5')
      storageNode = lateralCameraTransform.GetStorageNode()
      storageNode.SetFileName(lateralCameraTransformFilename)
      storageNode.ReadData(lateralCameraTransform)
      slicer.mrmlScene.RemoveNode(storageNode)

    lateralDetectorTransformID = self.parameterNode.GetNodeReferenceID("lateral-arm-c-rotation-transform")
    lateralCameraTransform.SetAndObserveTransformNodeID(lateralDetectorTransformID)

  def updateModel(self):
    with slicer.util.RenderBlocker():
      super().updateModel()
      self.updateGantryToRASTransform()
      self.updateAllCameraPositions()
      self.renderToVolume()

  def setVolumeRenderingROINode(self, roiNode):
    inputVolumeNode = self.getInputVolumeNode()
    if inputVolumeNode:
      for i in range(inputVolumeNode.GetNumberOfDisplayNodes()):
        displayNode = inputVolumeNode.GetNthDisplayNode(i)
        if not displayNode or not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
          continue
        displayNode.SetAndObserveROINodeID(roiNode.GetID() if roiNode else None)

    modifiedVolumeNode = self.getModifiedVolumeNode()
    if modifiedVolumeNode:
      for i in range(modifiedVolumeNode.GetNumberOfDisplayNodes()):
        displayNode = modifiedVolumeNode.GetNthDisplayNode(i)
        if not displayNode or not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
          continue
        displayNode.SetAndObserveROINodeID(roiNode.GetID() if roiNode else None)

    if roiNode:
      roiNode.GetDisplayNode().SetViewNodeIDs(["vtkMRMLViewNode1", "vtkMRMLSliceNodeRed", "vtkMRMLSliceNodeGreen", "vtkMRMLSliceNodeYellow"])

    self.renderToVolume()
    self.updateROINodeObservers()

  def updateROINodeObservers(self):
    self.removeObservers(self.onROINodeModified)
    roiNode = self.getVolumeRenderingROINode()
    if roiNode:
      self.addObserver(roiNode, vtk.vtkCommand.ModifiedEvent, self.onROINodeModified)

  def onROINodeModified(self, caller=None, event=None, callData=None):
    self.renderToVolume()

  def getVolumeRenderingROINode(self):
    inputVolumeNode = self.getInputVolumeNode()
    if inputVolumeNode is None:
      return None

    for i in range(inputVolumeNode.GetNumberOfDisplayNodes()):
      displayNode = inputVolumeNode.GetNthDisplayNode(i)
      if not displayNode or not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
        continue
      return displayNode.GetROINode()

  def updateVolumeRendering(self):
    """
    Initialize and display volume rendering for the input volume node, and hides all other volume rendering nodes.
    Displays volume using high contrast CT in the room-scale 3D view, and shows the volume using the X-ray preset in the C-arm views.
    """
    with slicer.util.RenderBlocker():
      volumeRenderingDisplayNodes = slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode")
      for displayNode in volumeRenderingDisplayNodes:
        displayNode.SetVisibility(False)

      volumeNode = self.getInputVolumeNode()
      displayVolumeNode = self.getVolumeToDisplay()
      if volumeNode is None:
        return

      cardiacDisplayNode = self.getVolumeRenderingDisplayNode(displayVolumeNode, self.VOLUME_RENDERING_ROLE_CT_HIGH_CONTRAST)
      xRayDisplayNode = self.getVolumeRenderingDisplayNode(displayVolumeNode, self.VOLUME_RENDERING_ROLE_X_RAY)

      volumeRenderingLogic = slicer.modules.volumerendering.logic()
      if cardiacDisplayNode is None:
        cardiacDisplayNode = slicer.modules.volumerendering.logic().CreateVolumeRenderingDisplayNode()
        slicer.mrmlScene.AddNode(cardiacDisplayNode)
        cardiacDisplayNode.UnRegister(None)

        propertyNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVolumePropertyNode")
        propertyNode.Copy(volumeRenderingLogic.GetPresetByName("CT-Chest-Contrast-Enhanced"))
        cardiacDisplayNode.SetAndObserveVolumePropertyNodeID(propertyNode.GetID())
        cardiacDisplayNode.SetViewNodeIDs(["vtkMRMLViewNode1"]) # Only display in regular 3D view
        cardiacDisplayNode.SetAttribute(self.VOLUME_RENDERING_ROLE_ATTRIBUTE_NAME, self.VOLUME_RENDERING_ROLE_CT_HIGH_CONTRAST)
        displayVolumeNode.AddAndObserveDisplayNodeID(cardiacDisplayNode.GetID())
      cardiacDisplayNode.SetVisibility(True)

      if xRayDisplayNode is None:
        if volumeNode == displayVolumeNode:
          propertyNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVolumePropertyNode")
        else:
          inputVolumeXRayDisplayNode = self.getVolumeRenderingDisplayNode(volumeNode, self.VOLUME_RENDERING_ROLE_X_RAY)
          propertyNode = inputVolumeXRayDisplayNode.GetVolumePropertyNode()

        xRayDisplayNode = slicer.modules.volumerendering.logic().CreateVolumeRenderingDisplayNode()
        slicer.mrmlScene.AddNode(xRayDisplayNode)
        xRayDisplayNode.UnRegister(None)
        xRayDisplayNode.SetAndObserveVolumePropertyNodeID(propertyNode.GetID())
        xRayDisplayNode.SetViewNodeIDs(["vtkMRMLViewNodeCArmFrontal", "vtkMRMLViewNodeCArmLateral"]) # Only display in regular 3D view
        xRayDisplayNode.SetAttribute(self.VOLUME_RENDERING_ROLE_ATTRIBUTE_NAME, self.VOLUME_RENDERING_ROLE_X_RAY)
        displayVolumeNode.AddAndObserveDisplayNodeID(xRayDisplayNode.GetID())

      currentPreset = self.getParameterNode().GetParameter(self.VOLUME_RENDERING_PRESET_PARAMETER_NAME)
      if currentPreset == "":
        currentPreset = "FluoroRenderingPreset_01"
        self.getParameterNode().SetParameter(self.VOLUME_RENDERING_PRESET_PARAMETER_NAME, currentPreset)
        self.getParameterNode().InvokeCustomModifiedEvent(FluoroSimulatorLogic.VOLUME_RENDERING_PRESET_CHANGED_EVENT)
      xRayDisplayNode.SetVisibility(True)

      roiNode = self.getVolumeRenderingROINode()
      if roiNode:
        cardiacDisplayNode.SetAndObserveROINodeID(roiNode.GetID())
        xRayDisplayNode.SetAndObserveROINodeID(roiNode.GetID())
      else:
        cardiacDisplayNode.SetAndObserveROINodeID(None)

  def getVolumeRenderingDisplayNode(self, volumeNode, roleAttribute):
    if volumeNode is None:
      return

    for i in range(volumeNode.GetNumberOfDisplayNodes()):
      displayNode = volumeNode.GetNthDisplayNode(i)

      if not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
        continue

      currentRoleAttribute = displayNode.GetAttribute(self.VOLUME_RENDERING_ROLE_ATTRIBUTE_NAME)
      if currentRoleAttribute == roleAttribute:
        return displayNode

    return None

  def updateVolumePropertyFromPreset(self, propertyNode, presetName):
    volumeRenderingLogic = slicer.modules.volumerendering.logic()
    presetNode = volumeRenderingLogic.GetPresetByName(presetName)
    if propertyNode and presetNode:
      propertyNode.Copy(presetNode)

  def updateAllCameraPositions(self):
    """
    Updates the position of all C-arm cameras.
    """
    deviceClass = self.getDeviceClass()
    if deviceClass is None:
      return

    deviceParams = deviceClass.getParameterValuesFromNode(self.parameterNode)

    # Update frontal view
    viewNode = slicer.mrmlScene.GetSingletonNode(self.C_ARM_FRONTAL_VIEW_NAME, "vtkMRMLViewNode")
    if viewNode:
      cameraNode = slicer.modules.cameras.logic().GetViewActiveCameraNode(viewNode)
      transformNode = self.parameterNode.GetNodeReference(self.FRONTAL_CAMERA_TRANSFORM_REFERENCE)
      frontalDetectorHeightMm = self.FRONTAL_DETECTOR_HEIGHT_MM
      frontalSIDMm = deviceParams['frontalSourceToImageDistance']
      frontalSODMm = deviceParams['frontalSourceToObjectDistance']
      self.updateCameraPosition(cameraNode, transformNode, frontalDetectorHeightMm, frontalSIDMm, frontalSODMm)

    if deviceClass.ID == BiplaneFluoro.ID:
      # Update lateral view
      viewNode = slicer.mrmlScene.GetSingletonNode(self.C_ARM_LATERAL_VIEW_NAME, "vtkMRMLViewNode")
      if viewNode:
        cameraNode = slicer.modules.cameras.logic().GetViewActiveCameraNode(viewNode)
        transformNode = self.parameterNode.GetNodeReference(self.LATERAL_CAMERA_TRANSFORM_REFERENCE)
        lateralDetectorHeightMm = self.LATERAL_DETECTOR_HEIGHT_MM
        lateralSIDMm = deviceParams['lateralSourceToImageDistance']
        lateralSODMm = deviceParams['lateralSourceToObjectDistance']
        self.updateCameraPosition(cameraNode, transformNode, lateralDetectorHeightMm, lateralSIDMm, lateralSODMm)

  def renderToVolume(self):
    """
    Schedule a rendering of the contents of the 3D X-ray views.
    """
    if self.renderTimer.remainingTime <= 0:
      # We are ready to render again.
      self.renderRequested = True
      self.renderToVolumeInternal()
      self.renderTimer.start()
    else:
      # Not ready to render. Wait until timer elapses.
      self.renderRequested = True

  def renderToVolumeInternal(self):
    """
    Render the contents of the 3D X-ray views to scalar volumes.
    """
    if self.parameterNode is None:
      return
    if not self.renderRequested:
      return
    self.renderRequested = False

    layoutManager = slicer.app.layoutManager()
    for threeDViewIndex in range(layoutManager.threeDViewCount):
      widget = layoutManager.threeDWidget(threeDViewIndex)
      view = widget.threeDView()

      threeDViewNode = view.mrmlViewNode()
      if not threeDViewNode.IsViewVisibleInLayout():
        # Don't render a view if it isn't in the current layout.
        continue

      singletonTag = threeDViewNode.GetSingletonTag()
      if singletonTag != self.C_ARM_FRONTAL_VIEW_NAME and singletonTag != self.C_ARM_LATERAL_VIEW_NAME:
        # Only apply to C-arm views
        continue

      renderWindow = view.renderWindow()

      mmToPixels = 1.0
      widthMm = 500
      heightMm = 500
      volumeNode = None
      if singletonTag == self.C_ARM_FRONTAL_VIEW_NAME:
        widthMm = self.FRONTAL_DETECTOR_WIDTH_MM
        heightMm = self.FRONTAL_DETECTOR_HEIGHT_MM
        volumeNode = self.getFrontalCArmVolumeNode()
        mmToPixels = float(self.parameterNode.GetParameter(self.FRONTAL_DETECTOR_HEIGHT_PARAMETER)) / self.FRONTAL_DETECTOR_HEIGHT_MM
      elif singletonTag == self.C_ARM_LATERAL_VIEW_NAME:
        widthMm = self.LATERAL_DETECTOR_WIDTH_MM
        heightMm = self.LATERAL_DETECTOR_HEIGHT_MM
        volumeNode = self.getLateralCArmVolumeNode()
        mmToPixels = float(self.parameterNode.GetParameter(self.LATERAL_DETECTOR_HEIGHT_PARAMETER)) / self.LATERAL_DETECTOR_HEIGHT_MM

      if volumeNode is None:
        return

      widthPx = int(widthMm * mmToPixels)
      heightPx = int(heightMm * mmToPixels)

      oldSize = widget.size
      widget.resize(widthPx, heightPx)
      renderWindow.SetSize(widthPx, heightPx)
      renderWindow.Render()

      windowToImageFilter = vtk.vtkWindowToImageFilter()
      windowToImageFilter.SetInput(renderWindow)

      luminanceFilter = vtk.vtkImageLuminance()
      luminanceFilter.SetInputConnection(windowToImageFilter.GetOutputPort())

      with slicer.util.NodeModify(volumeNode):
        outputImageData = volumeNode.GetImageData()
        if outputImageData is None:
          outputImageData = vtk.vtkImageData()
          volumeNode.SetAndObserveImageData(outputImageData)

        filterOutput = luminanceFilter
        filterOutput.SetOutput(outputImageData)
        filterOutput.Update()

        widget.resize(oldSize)
        slicer.util.arrayFromVolumeModified(volumeNode)

        with slicer.util.RenderBlocker():
          self.updateImageSpacing(threeDViewNode)

  def updateImageSpacing(self, threeDViewNode):
    deviceClass = self.getDeviceClass()
    if deviceClass is None:
      return
    deviceParams = deviceClass.getParameterValuesFromNode(self.parameterNode)

    singletonTag = threeDViewNode.GetSingletonTag()
    if singletonTag == self.C_ARM_LATERAL_VIEW_NAME:
      detectorHeightMm = self.LATERAL_DETECTOR_HEIGHT_MM
      detectorHeightPxParameter = self.LATERAL_DETECTOR_HEIGHT_PARAMETER
      detectorVolumeNode = self.getLateralCArmVolumeNode()
      sidMm = deviceParams['lateralSourceToImageDistance']
      sodMm = deviceParams['lateralSourceToObjectDistance']
    else:
      detectorHeightMm = self.FRONTAL_DETECTOR_HEIGHT_MM
      detectorVolumeNode = self.getFrontalCArmVolumeNode()
      detectorHeightPxParameter = self.FRONTAL_DETECTOR_HEIGHT_PARAMETER
      sidMm = deviceParams['frontalSourceToImageDistance']
      sodMm = deviceParams['frontalSourceToObjectDistance']

    scaleFactor = sodMm / sidMm
    imageHeight = detectorHeightMm * scaleFactor
    mmToPixels = float(self.parameterNode.GetParameter(detectorHeightPxParameter)) / imageHeight
    pixelsToMM = 1.0 / mmToPixels

    oldSpacing = detectorVolumeNode.GetSpacing()
    newSpacing = [pixelsToMM, pixelsToMM, 1.0]
    detectorVolumeNode.SetSpacing(newSpacing)
    dimensions = detectorVolumeNode.GetImageData().GetDimensions()
    if singletonTag == self.C_ARM_LATERAL_VIEW_NAME:
      detectorVolumeNode.SetOrigin(dimensions[0] * pixelsToMM/2.0, -dimensions[1] * pixelsToMM/2.0, 0.0)
    else:
      detectorVolumeNode.SetOrigin(-dimensions[0] * pixelsToMM/2.0, -dimensions[1] * pixelsToMM/2.0, 0.0)

    layoutManager = slicer.app.layoutManager()
    sliceWidget = layoutManager.sliceWidget(f"{threeDViewNode.GetSingletonTag()}Slice")
    sliceNode = sliceWidget.mrmlSliceNode()
    oldFov = sliceNode.GetFieldOfView()
    newFov = [0,0,1.0]
    for i in range(2):
      fovScale = newSpacing[i] / oldSpacing[i]
      newFov[i] = oldFov[i] * fovScale
    sliceNode.SetFieldOfView(newFov[0], newFov[1], newFov[2])

  def resetSliceViews(self, fitSliceToVolume=True):
    """
    Makes the frontal and lateral slice views display the frontal/lateral X-ray image.
    When the image is displayed for the first time, the slice view is fit to the image.
    """

    volumeToDisplay = self.getVolumeToDisplay()
    volumeToDisplayID = volumeToDisplay.GetID() if volumeToDisplay else None
    frontalVolumeNodeID = self.getFrontalCArmVolumeNode().GetID()
    lateralVolumeNodeID = self.getLateralCArmVolumeNode().GetID()

    layoutManager = slicer.app.layoutManager()
    for sliceViewName in layoutManager.sliceViewNames():

      sliceWidget = layoutManager.sliceWidget(sliceViewName)
      sliceNode = None
      if sliceWidget:
        sliceNode = sliceWidget.mrmlSliceNode()

      if sliceNode:
        if not sliceNode.IsMappedInLayout():
          continue

        sliceLogic = slicer.app.applicationLogic().GetSliceLogic(sliceNode)
        compositeNode = sliceLogic.GetSliceCompositeNode()

      if compositeNode is None:
        continue

      if sliceViewName == f"{self.C_ARM_FRONTAL_VIEW_NAME}Slice":
        if compositeNode.GetBackgroundVolumeID() != frontalVolumeNodeID:
          compositeNode.SetBackgroundVolumeID(frontalVolumeNodeID)
          if fitSliceToVolume:
            sliceWidget.sliceController().fitSliceToBackground()
      elif sliceViewName == f"{self.C_ARM_LATERAL_VIEW_NAME}Slice":
        if compositeNode.GetBackgroundVolumeID() != lateralVolumeNodeID:
          compositeNode.SetBackgroundVolumeID(lateralVolumeNodeID)
          if fitSliceToVolume:
            sliceWidget.sliceController().fitSliceToBackground()
      elif compositeNode.GetBackgroundVolumeID() != volumeToDisplayID:
        compositeNode.SetBackgroundVolumeID(volumeToDisplayID)

  def getInputVolumeNode(self):
    if self.parameterNode is None:
      return None
    return self.parameterNode.GetNodeReference(self.INPUT_VOLUME_REFERENCE)

  def getModifiedVolumeNode(self):
    if self.parameterNode is None:
      return None
    return self.parameterNode.GetNodeReference(self.MODIFIED_VOLUME_REFERENCE)

  def getVolumeToDisplay(self):
    if self.parameterNode is None:
      return None
    displayVolume = self.getModifiedVolumeNode()
    if displayVolume is None:
      displayVolume = self.getInputVolumeNode()
    return displayVolume

  def addModelToModifiedVolume(self, modelNode, fillValue):
    if modelNode is None:
      return
    inputVolumeNode = self.getInputVolumeNode()
    if inputVolumeNode is None:
      return

    # Convert model to labelmap
    segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(inputVolumeNode)
    slicer.modules.segmentations.logic().ImportModelToSegmentationNode(modelNode, segmentationNode)
    segmentationNode.CreateBinaryLabelmapRepresentation()
    self.addSegmentationToModifiedVolume(segmentationNode, fillValue)
    slicer.mrmlScene.RemoveNode(segmentationNode)

    self.updateVolumeRendering()
    self.renderToVolume()

  def addSegmentationToModifiedVolume(self, segmentationNode, fillValue):
    logging.info("Add segmentation to modified CT volume")

    if self.parameterNode is None:
      return None

    inputVolumeNode = self.getInputVolumeNode()
    if inputVolumeNode is None:
      return

    modifiedVolumeNode = self.getModifiedVolumeNode()
    if modifiedVolumeNode is None:
      name = f"{inputVolumeNode.GetName()}_ModifiedVolume"
      modifiedVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
      modifiedVolumeNode.CopyContent(inputVolumeNode)
      self.parameterNode.SetNodeReferenceID(self.MODIFIED_VOLUME_REFERENCE, modifiedVolumeNode.GetID())

    # Create segment editor to get access to effects
    segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
    # To show segment editor widget (useful for debugging): segmentEditorWidget.show()
    segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
    segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
    slicer.mrmlScene.AddNode(segmentEditorNode)
    segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
    segmentEditorWidget.setSegmentationNode(segmentationNode)
    segmentEditorWidget.setSourceVolumeNode(modifiedVolumeNode)

    # Set up masking parameters
    segmentEditorWidget.setActiveEffectByName("Mask volume")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("FillValue", str(fillValue))
    # Fill out voxels that are inside the segment
    effect.setParameter("Operation", "FILL_INSIDE")
    effect.setParameter("SoftEdgeMm", self.parameterNode.GetParameter(self.SOFT_EDGE_MM_PARAMETER))
    effect.self().outputVolumeSelector.setCurrentNode(modifiedVolumeNode)

    for segmentIndex in range(segmentationNode.GetSegmentation().GetNumberOfSegments()):
      # Set active segment
      segmentID = segmentationNode.GetSegmentation().GetNthSegmentID(segmentIndex)
      segmentEditorWidget.setCurrentSegmentID(segmentID)
      # Apply mask
      effect.self().onApply()

    self.updateCurrentLayout()
    self.updateVolumeRendering()
    self.renderToVolume()
    self.resetSliceViews(False)
    self.getParameterNode().Modified()

  def resetModifiedVolume(self):
    logging.info("Reset modified CT volume")
    if self.parameterNode is None:
      return None

    modifiedVolumeNode = self.getModifiedVolumeNode()
    if modifiedVolumeNode is None:
      return
    slicer.mrmlScene.RemoveNode(modifiedVolumeNode)

    self.updateCurrentLayout()
    self.updateVolumeRendering()
    self.renderToVolume()
    self.resetSliceViews(False)
    self.getParameterNode().Modified()

  def getFrontalCArmVolumeNode(self):
    """
    Returns the frontal C-arm image node. Creates the node if it doesn't exist.
    """
    if self.parameterNode is None:
      return None
    frontalVolumeNode = self.parameterNode.GetNodeReference(self.FRONTAL_IMAGE_REFERENCE)
    if frontalVolumeNode is None:
      frontalVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", self.FRONTAL_IMAGE_REFERENCE)
      frontalVolumeNode.SetAndObserveImageData(vtk.vtkImageData())
      frontalVolumeNode.CreateDefaultDisplayNodes()
      displayNode = frontalVolumeNode.GetDisplayNode()
      displayNode.AutoWindowLevelOff()
      displayNode.SetWindowLevelMinMax(0, 255)
      self.parameterNode.SetNodeReferenceID(self.FRONTAL_IMAGE_REFERENCE, frontalVolumeNode.GetID())
    return frontalVolumeNode

  def getLateralCArmVolumeNode(self):
    """
    Returns the lateral C-arm image node. Creates the node if it doesn't exist.
    """
    if self.parameterNode is None:
      return None
    lateralVolumeNode = self.parameterNode.GetNodeReference(self.LATERAL_IMAGE_REFERENCE)
    if lateralVolumeNode is None:
      lateralVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", self.LATERAL_IMAGE_REFERENCE)
      lateralVolumeNode.SetAndObserveImageData(vtk.vtkImageData())
      lateralVolumeNode.CreateDefaultDisplayNodes()
      lateralVolumeNode.SetIJKToRASDirections(-1.0, 0.0, 0.0,
                                               0.0, 1.0, 0.0,
                                               0.0, 0.0, 1.0)
      displayNode = lateralVolumeNode.GetDisplayNode()
      displayNode.AutoWindowLevelOff()
      displayNode.SetWindowLevelMinMax(0, 255)
      self.parameterNode.SetNodeReferenceID(self.LATERAL_IMAGE_REFERENCE, lateralVolumeNode.GetID())
    return lateralVolumeNode

  def updateCameraPosition(self, cameraNode, transformNode, detectorHeightMm, sourceImageDistance, sourceObjectDistance):
    """
    Update the position, view direction and angle of a C-arm camera.
    """
    with slicer.util.NodeModify(cameraNode):
      detectorToWorld = vtk.vtkGeneralTransform()
      slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(transformNode, None, detectorToWorld)
      position_Detector = [0.0, 0.0, 0.0]
      cameraPosition_RAS = detectorToWorld.TransformPoint(position_Detector)
      cameraNode.SetPosition(cameraPosition_RAS)

      viewDirection_Detector = [0.0, 1.0, 0.0] # Look towards +Y direction of camera transform
      viewDirection_RAS = detectorToWorld.TransformVectorAtPoint([0.0, 0.0, 0.0], viewDirection_Detector)
      focalPoint_RAS = np.array(cameraPosition_RAS) + np.array(viewDirection_RAS) * sourceObjectDistance
      cameraNode.SetFocalPoint(focalPoint_RAS)

      viewUp_Detector = [0.0, 0.0, 1.0] # View up faces towards +Z direction of camera transform
      viewUp_RAS = detectorToWorld.TransformVectorAtPoint([0.0, 0.0, 0.0], viewUp_Detector)
      cameraNode.SetViewUp(viewUp_RAS)

      viewAngle = 2.0 * math.degrees(math.atan(detectorHeightMm / 2.0 / sourceImageDistance))
      cameraNode.SetViewAngle(viewAngle)

      cameraNode.SetAndObserveTransformNodeID(transformNode.GetID() if transformNode else None)
      cameraNode.ResetClippingRange()

  def onLayoutChanged(self):
    """
    Called whenever the view layout changes.
    """
    # Ensure that the view widgets are all displayed before attempting to reset
    slicer.app.processEvents()
    self.updateCurrentLayout()
    self.resetSliceViews()

  def updateCurrentLayout(self):
    """
    Update C-arm view settings and add   angle positioner widgets
    """
    layoutManager = slicer.app.layoutManager()
    for threeDViewIndex in range(layoutManager.threeDViewCount):
      view = layoutManager.threeDWidget(threeDViewIndex).threeDView()

      threeDViewNode = view.mrmlViewNode()
      if threeDViewNode.GetSingletonTag() != self.C_ARM_FRONTAL_VIEW_NAME and threeDViewNode.GetSingletonTag() != self.C_ARM_LATERAL_VIEW_NAME:
        # Only apply to C-arm views
        continue

      # Setup dislay settings form C-arm view
      presetName = self.getParameterNode().GetParameter(self.VOLUME_RENDERING_PRESET_PARAMETER_NAME)
      color = [1.0, 1.0, 1.0] # White
      if presetName == "CT-X-ray":
        color = [0.0, 0.0, 0.0] # Black
      threeDViewNode.SetBackgroundColor(color)
      threeDViewNode.SetBackgroundColor2(color)
      threeDViewNode.SetAxisLabelsVisible(False)
      threeDViewNode.SetBoxVisible(False)

      # Add angle positioner widget
      sliceWidget = layoutManager.sliceWidget(f"{threeDViewNode.GetSingletonTag()}Slice")
      sliceNode = None
      if sliceWidget:
        sliceNode = sliceWidget.mrmlSliceNode()
      if self.positionerAngleViewWidgets.get(threeDViewNode) is None:
        if sliceNode:
          cameraNode = slicer.modules.cameras.logic().GetViewActiveCameraNode(threeDViewNode)
          positionerAngleViewWidget = PositionerAngleViewWidget(sliceNode, cameraNode)
          self.positionerAngleViewWidgets[threeDViewNode] = positionerAngleViewWidget

    self.updateAllCameraPositions()
    self.renderToVolume()

  def setROIVisibility(self, visibility):
    roiNode = self.getVolumeRenderingROINode()
    if roiNode is None:
      return
    roiNode.SetDisplayVisibility(visibility)
    self.renderToVolume()

  def setVolumeRenderingCropEnabled(self, enabled):
    inputVolume = self.getInputVolumeNode()
    if inputVolume:
      for i in range(inputVolume.GetNumberOfDisplayNodes()):
        displayNode = inputVolume.GetNthDisplayNode(i)
        if not displayNode or not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
          continue
        displayNode.SetCroppingEnabled(enabled)

    modifiedVolumeNode = self.getModifiedVolumeNode()
    if modifiedVolumeNode:
      for i in range(modifiedVolumeNode.GetNumberOfDisplayNodes()):
        displayNode = modifiedVolumeNode.GetNthDisplayNode(i)
        if not displayNode or not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
          continue
        displayNode.SetCroppingEnabled(enabled)
    self.renderToVolume()

  def fitROINodeToVolume(self):
    volumeRenderingLogic = slicer.modules.volumerendering.logic()
    inputVolume = self.getInputVolumeNode()
    if inputVolume:
      for i in range(inputVolume.GetNumberOfDisplayNodes()):
        displayNode = inputVolume.GetNthDisplayNode(i)
        if not displayNode or not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
          continue
        volumeRenderingLogic.FitROIToVolume(displayNode)

    modifiedVolumeNode = self.getModifiedVolumeNode()
    if modifiedVolumeNode:
      for i in range(modifiedVolumeNode.GetNumberOfDisplayNodes()):
        displayNode = modifiedVolumeNode.GetNthDisplayNode(i)
        if not displayNode or not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
          continue
        volumeRenderingLogic.FitROIToVolume(displayNode)
    self.renderToVolume()
