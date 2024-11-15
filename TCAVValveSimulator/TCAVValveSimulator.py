import logging
import qt
import vtk
import numpy as np

import slicer
from slicer.ScriptedLoadableModule import *
from CardiacDeviceSimulator import CardiacDeviceSimulatorWidget, CardiacDeviceSimulatorLogic
from CardiacDeviceSimulatorUtils.widgethelper import UIHelper
from CardiacDeviceSimulatorUtils.devices import CylinderDevice, CylinderSkirtValveDevice
from TCAVDevices.devices import *

#
# TCAVValveSimulator
#


class TCAVValveSimulator(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  deviceClasses = \
    [ApicalTether, ApicalTetherPlug, AngularWinglets, RadialForce, CylinderDevice, CylinderSkirtValveDevice]

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "TCAV Valve Simulator"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["CardiacDeviceSimulator"]
    self.parent.contributors = ["Christian Herz (CHOP), Andras Lasso (PerkLab, Queen's University), Matt Jolley (CHOP/UPenn)"]
    self.parent.helpText = """
    Evaluate Transcatheter Atrio Ventricular (TCAV) devices for Mitral Valve replacement.
    """
    self.parent.acknowledgementText = """
    This file was originally developed by Christian Herz (CHOP) and Andras Lasso (PerkLab, Queen's University).
    """


#
# TCAVValveSimulatorWidget
#

class TCAVValveSimulatorWidget(CardiacDeviceSimulatorWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  DEVICE_DEFORMATION_NEEDED = False
  DEVICE_QUANTIFICATION_NEEDED = False

  def __init__(self, parent=None, deviceClasses=None):
    try:
      from CardiacDeviceSimulator import CardiacDeviceSimulatorWidget
      for deviceClass in TCAVValveSimulator.deviceClasses:
        CardiacDeviceSimulatorWidget.registerDevice(deviceClass)
    except ImportError:
      pass

    CardiacDeviceSimulatorWidget.__init__(self, parent, TCAVValveSimulator.deviceClasses)
    self.logic = TCAVValveSimulatorLogic()
    self.logic.interpolatorType = 'KochanekSpline' # Valid options: 'CardinalSpline', 'SCurveSpline', 'KochanekSpline'
    self.logic.moduleName = "TCAVValveSimulator"

  def setup(self):
    super(TCAVValveSimulatorWidget, self).setup()
    if not self.setupSuccessful:
      return
    self.devicePositioningWidget.vesselGroupBox.hide()
    self.addAnnulusContourSection()

  def addAnnulusContourSection(self):
    self.centerlineCurveNode = self.devicePositioningWidget.centerlineNodeSelector
    self.addAnnulusContourSelector()
    self.aorticaAnnulusHBox = UIHelper.createHLayout([qt.QLabel("Annulus contour: "),
                                                      self.aorticAnnulusSelector])
    self.devicePositioningWidget.centerlineGroupBox.layout().insertRow(1, self.aorticaAnnulusHBox)

  def addAnnulusContourSelector(self):
    self.aorticAnnulusSelector = slicer.qMRMLNodeComboBox()
    self.aorticAnnulusSelector.nodeTypes = ["vtkMRMLMarkupsFiducialNode"]
    self.aorticAnnulusSelector.setNodeTypeLabel(self.logic.moduleName, "vtkMRMLMarkupsFiducialNode")
    self.aorticAnnulusSelector.baseName = self.logic.moduleName
    self.aorticAnnulusSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", self.logic.moduleName)
    self.aorticAnnulusSelector.addEnabled = False
    self.aorticAnnulusSelector.removeEnabled = False
    self.aorticAnnulusSelector.noneEnabled = True
    self.aorticAnnulusSelector.showHidden = False
    self.aorticAnnulusSelector.renameEnabled = True
    self.aorticAnnulusSelector.setMRMLScene(slicer.mrmlScene)
    self.aorticAnnulusSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelectAorticAnnulusNode)

  def onSelectAorticAnnulusNode(self):
    aorticAnnulusNode = self.aorticAnnulusSelector.currentNode()
    self.logic.setAorticAnnulusFiducialNode(aorticAnnulusNode)


class TCAVValveSimulatorLogic(CardiacDeviceSimulatorLogic):

  @staticmethod
  def getProbeToRasTransform():
    try:
      return slicer.util.getNode('ProbeToRasTransform')
    except slicer.util.MRMLNodeNotFoundException:
      return None

  def __init__(self, parent=None):
    super().__init__(parent)
    self.aorticAnnulusFiducialNode = None

  def setCenterlineNode(self, centerlineCurveNode):
    super().setCenterlineNode(centerlineCurveNode)
    self.setAorticAnnulusFiducialNode(self.aorticAnnulusFiducialNode)

  def setAorticAnnulusFiducialNode(self, aorticAnnulusNode):
    self.aorticAnnulusFiducialNode = aorticAnnulusNode

    centerLineNode = self.getCenterlineNode()
    numberOfCenterLineFiducials = 0
    if centerLineNode:
      try:
        # Slicer-4.13 (February 2022) and later
        numberOfCenterLineFiducials = centerLineNode.GetNumberOfControlPoints()
      except:
        # fall back to older API
        numberOfCenterLineFiducials = centerLineNode.GetNumberOfFiducials()

    if centerLineNode and self.aorticAnnulusFiducialNode:
      try:
        # Slicer-4.13 (February 2022) and later
        numberOfAorticAnnulusFiducials = self.aorticAnnulusFiducialNode.GetNumberOfControlPoints()
      except:
        # fall back to older API
        numberOfAorticAnnulusFiducials = self.aorticAnnulusFiducialNode.GetNumberOfFiducials()

      if numberOfAorticAnnulusFiducials > 0 and numberOfCenterLineFiducials == 0:
        probeToRasTransformNode = self.getProbeToRasTransform()
        if probeToRasTransformNode:
          centerLineNode.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID()
                                                      if probeToRasTransformNode else None)
        aorticAnnulusCentroid = self.getAnnulusCentroidPosition(self.aorticAnnulusFiducialNode)
        centerLineNode.AddControlPoint(vtk.vtkVector3d(aorticAnnulusCentroid))
      else:
        logging.info("Aortic annulus has no points or center line already has more than 0 markups.")

  def getAnnulusCentroidPosition(self, markupsNode):
    return np.mean(np.array(self.getMarkupsPointPositions(markupsNode)), axis=0)

  def getMarkupsPointPositions(self, markupsNode):
    positions = []
    pos = [0, 0, 0]
    try:
      # Slicer-4.13 (February 2022) and later
      numberOfControlPoints = markupsNode.GetNumberOfControlPoints()
    except:
      # fall back to older API
      numberOfControlPoints = markupsNode.GetNumberOfFiducials()
    for pIdx in range(numberOfControlPoints):
      try:
        # Current API (Slicer-4.13 February 2022)
        markupsNode.GetNthControlPointPosition(pIdx, pos)
      except:
        # Legacy API
        markupsNode.GetNthFiducialPosition(pIdx, pos)
      positions.append(np.array(pos))
    return np.array(positions)
