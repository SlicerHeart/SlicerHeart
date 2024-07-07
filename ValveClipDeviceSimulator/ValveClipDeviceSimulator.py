from slicer.ScriptedLoadableModule import *
import ctk
import qt
import slicer
import vtk
import numpy as np
from CardiacDeviceSimulator import CardiacDeviceSimulatorWidget, CardiacDeviceSimulatorLogic
from CardiacDeviceSimulatorUtils.widgethelper import UIHelper

import logging
from ValveClipDevices.devices import *

#
# ValveClipDeviceSimulator
#

class ValveClipDeviceSimulator(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  deviceClasses = [GenericValveClip, MitraClipG4NT, MitraClipG4NTW, MitraClipG4XT, MitraClipG4XTW]

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ValveClip Device Simulator"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["CardiacDeviceSimulator"]
    self.parent.contributors = ["Andras Lasso (PerkLab)", "Csaba Pinter (Pixel Medical)", "Christian Herz (CHOP)", "Matt Jolley (UPenn)"]
    self.parent.helpText = """
    Module for evaluating mitral valve clip device placement.
    """
    self.parent.acknowledgementText = """
    This work was supported by NIH R01 HL153166, the Cora Topolewski Cardiac Research Fund at the Children’s Hospital of Philadelphia (CHOP),
    a CHOP Frontier Grant (Pediatric Valve Center), and CANARIE’s Research Software Program..
    """


#
# ValveClipDeviceSimulatorWidget
#

class ValveClipDeviceSimulatorWidget(CardiacDeviceSimulatorWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  DEVICE_POSITIONING_NEEDED = True
  DEVICE_DEFORMATION_NEEDED = False
  DEVICE_QUANTIFICATION_NEEDED = False

  def __init__(self, parent=None, deviceClasses=None):
    try:
      from CardiacDeviceSimulator import CardiacDeviceSimulatorWidget
      for deviceClass in ValveClipDeviceSimulator.deviceClasses:
        CardiacDeviceSimulatorWidget.registerDevice(deviceClass)
    except ImportError:
      pass

    CardiacDeviceSimulatorWidget.__init__(self, parent, ValveClipDeviceSimulator.deviceClasses)
    self.logic = ValveClipDeviceSimulatorLogic(self)
    self.logic.interpolatorType = 'KochanekSpline' # Valid options: 'CardinalSpline', 'SCurveSpline', 'KochanekSpline'
    self.logic.moduleName = "ValveClipDeviceSimulator"
    self.deviceControlshortcuts = []

  def setup(self):
    super(ValveClipDeviceSimulatorWidget, self).setup()
    if not self.setupSuccessful:
      return

    self.devicePositioningWidget.parent().hide()

    self.deviceControlSection = ctk.ctkCollapsibleButton()
    self.deviceControlSection.text = "Device control"
    self.layout.insertWidget(3, self.deviceControlSection)
    deviceControlSectionLayout = qt.QVBoxLayout(self.deviceControlSection)

    # Load widget from .ui file (created by Qt Designer)
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/ValveClipDeviceSimulator.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)
    deviceControlSectionLayout.addWidget(uiWidget)

    MitraClipG4Base.APPLY_FABRIC_TEXTURE = False # Disable texture for MitraClipG4 clips

    # Setup device control section widgets
    self.ui.guideCurvePlaceWidget.setMRMLScene(slicer.mrmlScene)
    self.ui.curvatureColorInterpolationCheckbox.checked = True

    # Only show the curvature section if it is available in the Slicer version used
    curvatureAvailable = hasattr(slicer.vtkCurveMeasurementsCalculator, 'GetMaxCurvatureName')
    self.ui.curvatureFrame.visible = curvatureAvailable

    self.setupConnections()

  def setupConnections(self):
    self.ui.curvatureCalculationCheckBox.toggled.connect(self.onCurvatureCalculationToggled)
    self.ui.curvatureColorInterpolationCheckbox.toggled.connect(self.onCurvatureColorInterpolationToggled)

  def disconnect(self):
    self.ui.curvatureCalculationCheckBox.toggled.disconnect()
    self.ui.curvatureColorInterpolationCheckbox.toggled.disconnect()

  def cleanup(self):
    self.removeDeviceControlShortcutKeys()
    CardiacDeviceSimulatorWidget.cleanup(self)
    self.disconnect()

  def updateGUIFromMRML(self, caller=None, event=None):
    """
    Set selections and other settings on the GUI based on the parameter node.
    """
    # Get parameter node
    parameterNode = self.logic.getParameterNode()
    if not parameterNode:
      return

    self.ui.guideCurvePlaceWidget.setCurrentNode(self.logic.getGuideInteractionCurveNode())
    self.ui.curvatureColorInterpolationCheckbox.checked = (parameterNode.GetParameter('CurvatureColorInterpolation') == 'True')

  def onParameterNodeSelectionChanged(self, node=None):
    super().onParameterNodeSelectionChanged()
    self.updateGUIFromMRML()

  def onDevicePlacementParameterChanged(self, name, value):
    self.logic.setDevicePlacementParameter(name, value)

  def installDeviceControlShortcutKeys(self):
    logging.debug('installShortcutKeys: '+str(type(self)))
    self.removeDeviceControlShortcutKeys()
    smallStep = 1
    largeStep = 5
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


class ValveClipDeviceSimulatorLogic(CardiacDeviceSimulatorLogic):

  def __init__(self, widgetInstance, parent=None):
    CardiacDeviceSimulatorLogic.__init__(self, parent)

    # To connect parameter node changes to widget update function
    self.valveClipDeviceSimulatorWidget = widgetInstance

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
      self.removeObserver(self.parameterNode, vtk.vtkCommand.ModifiedEvent, self.valveClipDeviceSimulatorWidget.updateGUIFromMRML)
      self.removeObserver(self.parameterNode, CardiacDeviceBase.DEVICE_CLASS_MODIFIED_EVENT, lambda caller, event: self.computeCenterline())
    guideInteractionCurveNode = self.getGuideInteractionCurveNode()
    if guideInteractionCurveNode:
      self.removeObserver(guideInteractionCurveNode, slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onGuideInteractionCurveModified)
    clipPositioningPlaneNode = self.getClipPositioningPlaneNode()
    if clipPositioningPlaneNode:
      self.removeObserver(clipPositioningPlaneNode, slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onClipPositioningPlaneModified)

    # Set parameter node in base class (and set parameter node member variable)
    CardiacDeviceSimulatorLogic.setParameterNode(self, parameterNode)

    if parameterNode:
      # Setup device model
      self.setupDeviceModel()

  def setupDeviceModel(self):
    parameterNode = self.getParameterNode()
    if not parameterNode:
      logging.error('Unable to access parameter node for setting up device model')
      return

    if self.getDeviceClass():
      self.getDeviceClass().setupDeviceModel()

    # Make sure observations are set if device was not set up when setting parameter node
    guideInteractionCurveNode = self.getGuideInteractionCurveNode()
    if guideInteractionCurveNode:
      if not self.hasObserver(guideInteractionCurveNode, slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onGuideInteractionCurveModified):
        self.addObserver(guideInteractionCurveNode, slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onGuideInteractionCurveModified)

    clipPositioningPlaneNode = self.parameterNode.GetNodeReference('ClipPositioningPlane')
    if clipPositioningPlaneNode:
      if not self.hasObserver(clipPositioningPlaneNode, slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onClipPositioningPlaneModified):
        self.addObserver(clipPositioningPlaneNode, slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onClipPositioningPlaneModified)

    if not self.hasObserver(self.parameterNode, vtk.vtkCommand.ModifiedEvent, self.valveClipDeviceSimulatorWidget.updateGUIFromMRML):
      self.addObserver(self.parameterNode, vtk.vtkCommand.ModifiedEvent, self.valveClipDeviceSimulatorWidget.updateGUIFromMRML)
    if not self.hasObserver(self.parameterNode, CardiacDeviceBase.DEVICE_CLASS_MODIFIED_EVENT, lambda caller, event: self.computeCenterline()):
      self.addObserver(self.parameterNode, CardiacDeviceBase.DEVICE_CLASS_MODIFIED_EVENT, lambda caller, event: self.computeCenterline())

    self.parameterNode.Modified() # Trigger GUI update

  def getGuideInteractionCurveNode(self):
    if self.getDeviceClass():
      return self.getDeviceClass().getGuideInteractionCurveNode()
    return None

  def getGuideCurveNode(self):
    if self.getDeviceClass():
      return self.getDeviceClass().getGuideCurveNode()
    return None

  def getClipPositioningPlaneNode(self):
    if self.getDeviceClass():
      return self.getDeviceClass().getClipPositioningPlaneNode()
    return None

  def onGuideInteractionCurveModified(self, caller=None, event=None):
    # Compute and apply geometry of the guide tip
    self.computeGuideTip()

    # Compute catheter and sleeve inside of guide according to parameters
    self.computeCenterline()

  def onClipPositioningPlaneModified(self, caller=None, event=None):
    self.computeCenterline()

  def computeCenterline(self):
    if self.getDeviceClass():
      self.getDeviceClass().computeCenterline()

  def computeGuideTip(self):
    if self.getDeviceClass():
      self.getDeviceClass().computeGuideTip()

  def setCurvatureCalculationEnabled(self, on):
    """
    Enable curvature calculation and scalar display
    """
    parameterNode = self.getParameterNode()
    if not parameterNode:
      logging.error('Unable to access parameter node setting up curvature calculation')
      return
    if not self.getDeviceClass():
      return
    parameterValues = self.getDeviceClass().getParameterValuesFromNode(parameterNode)

    if on:
      [guideCurvatureColorNodeID, catheterCurvatureColorNodeID] = self.setupCurvatureColorNodes()

    guideCurveNode = self.parameterNode.GetNodeReference('GuideCurve')
    guideMaxCurvatureMeasurement = guideCurveNode.GetMeasurement(slicer.vtkCurveMeasurementsCalculator.GetMaxCurvatureName())
    guideMaxCurvatureMeasurement.SetEnabled(on)
    guideMeanCurvatureMeasurement = guideCurveNode.GetMeasurement(slicer.vtkCurveMeasurementsCalculator.GetMeanCurvatureName())
    guideMeanCurvatureMeasurement.SetEnabled(on)
    guideCurveDisplayNode = guideCurveNode.GetDisplayNode()
    if on:
      if guideCurvatureColorNodeID not in [None, '']:
        guideCurveDisplayNode.SetAndObserveColorNodeID(guideCurvatureColorNodeID)
      else:
        guideCurveDisplayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeFileViridis.txt')
      self.parameterNode.GetNodeReference('GuideCurvatureColor').GetID()
      guideCurveDisplayNode.SetActiveScalarName('Curvature')
      guideCurveDisplayNode.SetScalarRangeFlagFromString('UseManual')
      guideCurveDisplayNode.SetScalarRange(0, parameterValues["guidePhysicalCurvatureThreshold"])
    guideCurveDisplayNode.SetScalarVisibility(on)
    guideCurveDisplayNode.UpdateAssignedAttribute()

    centerlineNode = self.getCenterlineNode()
    centerlineMaxCurvatureMeasurement = centerlineNode.GetMeasurement(slicer.vtkCurveMeasurementsCalculator.GetMaxCurvatureName())
    centerlineMaxCurvatureMeasurement.SetEnabled(on)
    centerlineMeanCurvatureMeasurement = centerlineNode.GetMeasurement(slicer.vtkCurveMeasurementsCalculator.GetMeanCurvatureName())
    centerlineMeanCurvatureMeasurement.SetEnabled(on)
    centerlineDisplayNode = centerlineNode.GetDisplayNode()
    if on:
      if catheterCurvatureColorNodeID not in [None, '']:
        centerlineDisplayNode.SetAndObserveColorNodeID(catheterCurvatureColorNodeID)
      else:
        centerlineDisplayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeFileViridis.txt')
      centerlineDisplayNode.SetActiveScalarName('Curvature')
      centerlineDisplayNode.SetScalarRangeFlagFromString('UseManual')
      centerlineDisplayNode.SetScalarRange(0, parameterValues["catheterPhysicalCurvatureThreshold"])
    centerlineDisplayNode.SetScalarVisibility(on)
    centerlineDisplayNode.UpdateAssignedAttribute()

    # Make sleeve semi-transparent so that curvature coloring is visible underneath
    sleeveModelNode = self.parameterNode.GetNodeReference('SleeveModel')
    sleeveModelDisplayNode = sleeveModelNode.GetDisplayNode()
    if on:
      sleeveModelDisplayNode.SetOpacity(0.4)
    else:
      sleeveModelDisplayNode.SetOpacity(1.0)

  def setupCurvatureColorNodes(self):
    parameterNode = self.getParameterNode()
    if not parameterNode:
      logging.error('Unable to access parameter node for setting up curvature color nodes')
      return [None, None]
    if not self.getDeviceClass():
      return
    parameterValues = self.getDeviceClass().getParameterValuesFromNode(parameterNode)

    # Create color nodes if they do not exist yet
    guideCurvatureColorNode = self.parameterNode.GetNodeReference('GuideCurvatureColor')
    if not guideCurvatureColorNode:
      guideCurvatureColorNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLProceduralColorNode', 'GuideCurvatureColor')
      self.parameterNode.SetNodeReferenceID('GuideCurvatureColor', guideCurvatureColorNode.GetID())

    catheterCurvatureColorNode = self.parameterNode.GetNodeReference('CatheterCurvatureColor')
    if not catheterCurvatureColorNode:
      catheterCurvatureColorNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLProceduralColorNode', 'CatheterCurvatureColor')
      self.parameterNode.SetNodeReferenceID('CatheterCurvatureColor', catheterCurvatureColorNode.GetID())

    # Setup color nodes based on stored thresholds
    curvatureColorInterpolationOn = (parameterNode.GetParameter('CurvatureColorInterpolation') == 'True')
    sharpness = (0.0 if curvatureColorInterpolationOn else 1.0)

    if self.parameterNode.GetParameter('DeviceClassId') not in [None, '']:
      guideColorTransferFunction = vtk.vtkColorTransferFunction()
      guideColorTransferFunction.AddRGBPoint(0.0, 0.0, 0.5, 0.0, 0.5, sharpness)
      guideColorTransferFunction.AddRGBPoint(parameterValues["guideClinicalCurvatureThreshold"], 0.9, 0.9, 0.0, 0.5, sharpness)
      guideColorTransferFunction.AddRGBPoint(parameterValues["guidePhysicalCurvatureThreshold"], 0.9, 0.0, 0.0, 0.5, sharpness)
      guideCurvatureColorNode.SetAndObserveColorTransferFunction(guideColorTransferFunction)

      catheterColorTransferFunction = vtk.vtkColorTransferFunction()
      catheterColorTransferFunction.AddRGBPoint(0.0, 0.0, 0.5, 0.0, 0.5, sharpness)
      catheterColorTransferFunction.AddRGBPoint(parameterValues["catheterClinicalCurvatureThreshold"], 0.9, 0.9, 0.0, 0.5, sharpness)
      catheterColorTransferFunction.AddRGBPoint(parameterValues["catheterPhysicalCurvatureThreshold"], 0.9, 0.0, 0.0, 0.5, sharpness)
      catheterCurvatureColorNode.SetAndObserveColorTransferFunction(catheterColorTransferFunction)

    return [guideCurvatureColorNode.GetID(), catheterCurvatureColorNode.GetID()]
