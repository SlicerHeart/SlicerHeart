from slicer.util import VTKObservationMixin
import vtk, qt, ctk, slicer
import numpy as np
from slicer.ScriptedLoadableModule import *
import logging
from CardiacDeviceSimulatorUtils.devices import *
from CardiacDeviceSimulatorUtils.widgethelper import UIHelper
from CardiacDeviceSimulatorUtils.DeviceCompressionQuantificationWidget import DeviceCompressionQuantificationWidget
from CardiacDeviceSimulatorUtils.DeviceDataTreeWidget import DeviceDataTreeWidget
from CardiacDeviceSimulatorUtils.DeviceDeformationWidget import DeviceDeformationWidget
from CardiacDeviceSimulatorUtils.DevicePositioningWidget import DevicePositioningWidget
from CardiacDeviceSimulatorUtils.DeviceSelectorWidget import DeviceSelectorWidget

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
    self.parent.contributors = ["Andras Lasso (PerkLab, Queen's University), Christian Herz (CHOP), Matt Jolley (CHOP/UPenn)"]
    self.parent.helpText = """
    Create various models (stents, valves, etc) related to cardiac procedures.
    """
    self.parent.acknowledgementText = """
    This file was originally developed by Andras Lasso (PerkLab, Queen's University).
    """

    for deviceClass in [HarmonyDevice, CylinderDevice, CylinderSkirtValveDevice]:
      CardiacDeviceSimulatorWidget.registerDevice(deviceClass)

    def initSubjectHierarchyPlugin():
      import CardiacDeviceSimulatorUtils.CardiacDeviceSubjectHierarchyPlugin as hvp
      scriptedPlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
      scriptedPlugin.setPythonSource(hvp.CardiacDeviceSubjectHierarchyPlugin.filePath)

    slicer.app.startupCompleted.connect(initSubjectHierarchyPlugin)

#
# CardiacDeviceSimulatorWidget
#

class CardiacDeviceSimulatorWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  registeredDeviceClasses = []

  DEVICE_POSITIONING_NEEDED = True
  DEVICE_DEFORMATION_NEEDED = True
  DEVICE_QUANTIFICATION_NEEDED = True

  @staticmethod
  def registerDevice(deviceClass):
    """Register a subclass of CardiacDeviceBase for additional measurements cardiac device models"""
    if not issubclass(deviceClass, CardiacDeviceBase):
      return
    if not deviceClass in CardiacDeviceSimulatorWidget.registeredDeviceClasses:
      CardiacDeviceSimulatorWidget.registeredDeviceClasses.append(deviceClass)

  def __init__(self, parent=None, deviceClasses=None):
    ScriptedLoadableModuleWidget.__init__(self, parent)
    if deviceClasses:
      self.deviceClasses = deviceClasses
    else:
      self.deviceClasses = CardiacDeviceSimulatorWidget.registeredDeviceClasses
    self.deviceWidgets = []
    self.logic = CardiacDeviceSimulatorLogic()
    self.setupSuccessful = False
    self._parameterNode = None
    self._parameterNodeObserverTag = None

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    if not hasattr(slicer.modules, 'volumereslicedriver'):
      slicer.util.messageBox("This modules requires SlicerIGT extension. Install SlicerIGT and restart Slicer.")
      return

    self.setupSuccessful = True

    self.moduleSectionButtonsGroup = qt.QButtonGroup()
    self.moduleSectionButtonsGroup.connect("buttonToggled(QAbstractButton*,bool)", self.onModuleSectionToggled)

    self.parameterNodeSelector = slicer.qMRMLNodeComboBox()
    self.parameterNodeSelector.nodeTypes = ["vtkMRMLScriptedModuleNode"]
    self.parameterNodeSelector.setNodeTypeLabel(self.logic.moduleName, "vtkMRMLScriptedModuleNode")
    self.parameterNodeSelector.baseName = self.logic.moduleName
    self.parameterNodeSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", self.logic.moduleName)
    self.parameterNodeSelector.addEnabled = True
    self.parameterNodeSelector.removeEnabled = True
    self.parameterNodeSelector.noneEnabled = True
    self.parameterNodeSelector.showHidden = True  # scripted module nodes are hidden by default
    self.parameterNodeSelector.renameEnabled = True
    self.parameterNodeSelector.setMRMLScene(slicer.mrmlScene)
    self.parameterNodeSelector.setToolTip("Node referencing to all generated nodes")
    hbox = qt.QHBoxLayout()
    hbox.addWidget(qt.QLabel("Parameter node: "))
    hbox.addWidget(self.parameterNodeSelector)
    self.layout.addLayout(hbox)
    self.parameterNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onParameterNodeSelectionChanged)

    self.deviceSelectorWidget = DeviceSelectorWidget(self.deviceClasses)
    _, self.deviceSelectionSection = UIHelper.addCommonSection("Device selection", self.layout, self.moduleSectionButtonsGroup,
      collapsed=False, widget=self.deviceSelectorWidget)

    self.deviceWidgets = [self.deviceSelectorWidget]

    self.devicePositioningSection = None
    if self.DEVICE_POSITIONING_NEEDED:
      self.devicePositioningWidget = DevicePositioningWidget()
      _, self.devicePositioningSection = UIHelper.addCommonSection("Device positioning", self.layout, self.moduleSectionButtonsGroup,
        collapsed=True, widget=self.devicePositioningWidget)
      self.deviceWidgets.append(self.devicePositioningWidget)
      self.devicePositioningSection.toggled.connect(self.onDevicePositioningToggled)

    self.deviceDeformationSection = None
    if self.DEVICE_DEFORMATION_NEEDED:
      self.deviceDeformationWidget = DeviceDeformationWidget()
      _, self.deviceDeformationSection = UIHelper.addCommonSection("Device deformation", self.layout, self.moduleSectionButtonsGroup,
        collapsed=True, widget=self.deviceDeformationWidget)
      self.deviceWidgets.append(self.deviceDeformationWidget)

    self.quantificationSection = None
    if self.DEVICE_QUANTIFICATION_NEEDED:
      self.deviceQuantificationWidget = DeviceCompressionQuantificationWidget()
      _, self.quantificationSection = UIHelper.addCommonSection("Quantification", self.layout, self.moduleSectionButtonsGroup,
        collapsed=True, widget=self.deviceQuantificationWidget)
      self.deviceWidgets.append(self.deviceQuantificationWidget)

    self.dataTreeWidget = DeviceDataTreeWidget()
    self.layout.addWidget(self.dataTreeWidget)
    self.deviceWidgets.append(self.dataTreeWidget)

    for deviceWidget in self.deviceWidgets:
      deviceWidget.setLogic(self.logic)

    self.updateButtonStates()

  def cleanup(self):
    for deviceWidget in self.deviceWidgets:
      deviceWidget.cleanup()
    self._observeParameterNode(None)

  def enter(self):
    """Runs whenever the module is reopened
    """
    defaultNode = self.logic.getParameterNode()
    self.parameterNodeSelector.setCurrentNode(defaultNode)

    for deviceWidget in self.deviceWidgets:
      deviceWidget.enter()

  def exit(self):
    for deviceWidget in self.deviceWidgets:
      deviceWidget.exit()

  def _observeParameterNode(self, parameterNode):
    if self.parameterNodeSelector.currentNode() == self._parameterNode:
      return
    if self._parameterNode and self._parameterNodeObserverTag:
      self._parameterNode.RemoveObserver(self._parameterNodeObserverTag)
      self._parameterNodeObserverTag = None
    if parameterNode:
      self._parameterNode = parameterNode
      self._parameterNodeObserverTag = self._parameterNode.AddObserver(CardiacDeviceBase.DEVICE_CLASS_MODIFIED_EVENT, self.onDeviceClassModified)

  def onParameterNodeSelectionChanged(self):
    self._observeParameterNode(self.parameterNodeSelector.currentNode())
    self.logic.setParameterNode(self.parameterNodeSelector.currentNode())
    for deviceWidget in self.deviceWidgets:
      deviceWidget.setParameterNode(self.logic.parameterNode)
    self.updateButtonStates()

  def updateButtonStates(self):
    guiEnabled = self.logic.parameterNode is not None
    # self.deviceSelectionSection is always enabled, it creates a parameter node
    for guiSection in self.deviceWidgets:
      if guiSection is self.deviceSelectorWidget:
        continue
      guiSection.enabled = guiEnabled

  def onDeviceClassModified(self, caller, event):
    # Used in derived classes
    pass

  def onDevicePositioningToggled(self, toggled):
    transformNode = self.logic.parameterNode.GetNodeReference('PositioningTransform')
    if not transformNode:
      return

    transformNode.CreateDefaultDisplayNodes()
    transformNode.SetDisplayVisibility(toggled)
    dNode = transformNode.GetDisplayNode()
    if dNode:
      dNode.SetEditorVisibility(toggled)

  def onModuleSectionToggled(self, button, toggled):

    if button == self.deviceSelectionSection:

      if self.parameterNodeSelector.currentNode() is None:
        self.parameterNodeSelector.addNode()

      # Only allow update of deformed models when common section is active (not collapsed)
      self.logic.updateDeformedModelsEnabled = not toggled

      originalModel = self.logic.parameterNode.GetNodeReference('OriginalModel')
      if originalModel:
        originalModel.SetDisplayVisibility(True)

      if not toggled and self.logic.updateDeformedModelsPending:
        # While we are in device selection section, only the original model is updated.
        # We are exiting the device selection section now, so make sure all the deformed models are updated.
        # Update of model resets deformation markers, so only do it if the model actually changed
        self.logic.updateModel()

    if toggled:
      self.logic.showDeformedModel(button != self.deviceSelectionSection)
      self.logic.setCenterlineEditingEnabled(button == self.devicePositioningSection)
      self.logic.showDeformationHandles(button == self.deviceDeformationSection)


#
# CardiacDeviceSimulatorLogic
#

class CardiacDeviceSimulatorLogic(VTKObservationMixin, ScriptedLoadableModuleLogic):
  """This class should implement all the actual computation done by your module. The interface should be such that
  other python code can import this class and make use of the functionality without requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    VTKObservationMixin.__init__(self)
    ScriptedLoadableModuleLogic.__init__(self, parent)
    self.interpolatorType = 'KochanekSpline' # Valid options: 'CardinalSpline', 'SCurveSpline', 'KochanekSpline'
    self.parameterNode = None
    self.handleProfilePoints = vtk.vtkPoints()
    # For performance reasons, we can temporarily disable deformed models update.
    # If original model is updated while updateDeformedModelsEnabled is set to False
    # then updateDeformedModelsPending flag is set.
    self.updateDeformedModelsEnabled = True
    self.updateDeformedModelsPending = False
    # Set NodeAboutToBeRemovedEvent observation priority to higher than default to ensure it is called
    # before subject hierarchy's observer (that would remove the subject hierarchy item and so we
    # would not have a chance to delete children nodes)
    self.addObserver(slicer.mrmlScene, slicer.vtkMRMLScene.NodeAboutToBeRemovedEvent, self.onNodeAboutToBeRemoved, priority = 10.0)

  def cleanup(self):
    # TODO: check if it is called
    self.removeObservers()

  @vtk.calldata_type(vtk.VTK_OBJECT)
  def onNodeAboutToBeRemoved(self, caller, event, node):
    if isinstance(node, slicer.vtkMRMLScriptedModuleNode) and node.GetAttribute('ModuleName') == self.moduleName:
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      shItem = shNode.GetItemByDataNode(node)
      shNode.RemoveItemChildren(shItem)

  def setParameterNode(self, parameterNode):
    if self.parameterNode:
      self.removeObserver(self.parameterNode, CardiacDeviceBase.DEVICE_CLASS_MODIFIED_EVENT, self.onDeviceClassModified)
      self.removeObserver(self.parameterNode, CardiacDeviceBase.DEVICE_PARAMETER_VALUE_MODIFIED_EVENT, self.onDeviceParameterValueModified)

    self.parameterNode = parameterNode
    if not self.parameterNode:
      return

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    self.parameterNode.SetHideFromEditors(False)
    shNode.RequestOwnerPluginSearch(self.parameterNode)
    parameterNodeShItem = shNode.GetItemByDataNode(self.parameterNode)
    shNode.SetItemAttribute(parameterNodeShItem, "ModuleName", self.moduleName)

    self.updateDeformedModelsEnabled = False
    # Not using the parameter node for this anymore (but updateDeformedModelsEnabled member variable)
    self.parameterNode.SetParameter('UpdateDeformedModelsEnabled', '')

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
        try:
          # Current API (Slicer-4.13 February 2022)
          originalHandlesNode.GetNthControlPointPosition(0, firstHandlePointPos)
        except:
          # Legacy API
          originalHandlesNode.GetNthFiducialPosition(0, firstHandlePointPos)
        for fidIndex in range(1, originalHandlesNode.GetNumberOfFiducials()):
          currentHandlePointPos = [0, 0, 0]
          try:
            # Current API (Slicer-4.13 February 2022)
            originalHandlesNode.GetNthControlPointPosition(fidIndex, currentHandlePointPos)
          except:
            # Legacy API
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

    positioningTransform = self.parameterNode.GetNodeReference('PositioningTransform')
    if not positioningTransform:
      positioningTransform = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "PositioningTransform")

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

      positioningTransform.SetMatrixTransformToParent(positioningMatrix)
      self.parameterNode.SetNodeReferenceID('PositioningTransform', positioningTransform.GetID())
    shNode.SetItemParent(shNode.GetItemByDataNode(positioningTransform), transformationFolderShItem)

    deformingTransform = self.parameterNode.GetNodeReference('DeformingTransform')
    if not deformingTransform:
      deformingTransform = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", "DeformingTransform")
      deformingTransform.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      self.parameterNode.SetNodeReferenceID('DeformingTransform', deformingTransform.GetID())
    shNode.SetItemParent(shNode.GetItemByDataNode(deformingTransform), transformationFolderShItem)

    originalModel = self.parameterNode.GetNodeReference('OriginalModel')
    if not originalModel:
      originalModel = self.createModelNode('OriginalModel', [1,0,0])
      dn = originalModel.GetDisplayNode()
      dn.SetRepresentation(dn.WireframeRepresentation)
      originalModel.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      self.parameterNode.SetNodeReferenceID('OriginalModel', originalModel.GetID())
    shNode.SetItemParent(shNode.GetItemByDataNode(originalModel), parameterNodeShItem)

    deformedModel = self.parameterNode.GetNodeReference('DeformedModel')
    if not deformedModel:
      deformedModel = self.createModelNode('DeformedModel', [0.5,0.5,1.0])
      deformedModel.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('DeformingTransform').GetID())
      self.parameterNode.SetNodeReferenceID('DeformedModel', deformedModel.GetID())
    shNode.SetItemParent(shNode.GetItemByDataNode(deformedModel), parameterNodeShItem)

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
      # color node does not show up in subject hierarchy, so there is no need to set its parent

    originalHandles = self.parameterNode.GetNodeReference('OriginalHandles')
    if not originalHandles:
      originalHandles = self.createMarkupsNode('OriginalHandles', [1, 0, 0])
      originalHandles.GetDisplayNode().SetVisibility(0)
      try:
        # Slicer-4.11
        originalHandles.GetDisplayNode().SetPointLabelsVisibility(False)
      except:
        # Slicer-4.10
        originalHandles.GetDisplayNode().SetTextScale(0)
      originalHandles.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      self.parameterNode.SetNodeReferenceID('OriginalHandles', originalHandles.GetID())
    shNode.SetItemParent(shNode.GetItemByDataNode(originalHandles), transformationFolderShItem)

    # Workaround for Slicer Preview Releases before 2019-10-30 (where invisible markups could be picked)
    self.parameterNode.GetNodeReference('OriginalHandles').SetLocked(True)

    deformedHandles = self.parameterNode.GetNodeReference('DeformedHandles')
    if not deformedHandles:
      deformedHandles = self.createMarkupsNode('DeformedHandles', [0.5,0.5,1.0])
      try:
        # Slicer-4.11
        deformedHandles.GetDisplayNode().SetPointLabelsVisibility(False)
      except:
        # Slicer-4.10
        deformedHandles.GetDisplayNode().SetTextScale(0)
      deformedHandles.SetAndObserveTransformNodeID(self.parameterNode.GetNodeReference('PositioningTransform').GetID())
      self.parameterNode.SetNodeReferenceID('DeformedHandles', deformedHandles.GetID())
    shNode.SetItemParent(shNode.GetItemByDataNode(deformedHandles), transformationFolderShItem)

    # Workaround for Slicer Preview Releases before 2019-10-31 (where point labels could be still shown,
    # even if text scale was set to 0)
    try:
      self.parameterNode.GetNodeReference('OriginalHandles').GetDisplayNode().SetPointLabelsVisibility(False)
      self.parameterNode.GetNodeReference('DeformedHandles').GetDisplayNode().SetPointLabelsVisibility(False)
    except:
      pass

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
      # registration node does not show up in subject hierarchy, so there is no need to set its parent

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

    self.addObserver(self.parameterNode, CardiacDeviceBase.DEVICE_CLASS_MODIFIED_EVENT, self.onDeviceClassModified)
    self.addObserver(self.parameterNode, CardiacDeviceBase.DEVICE_PARAMETER_VALUE_MODIFIED_EVENT, self.onDeviceParameterValueModified)

  def onDeviceClassModified(self, caller=None, event=None):
    deviceClass = self.getDeviceClass()
    if deviceClass:
      originalModel = self.parameterNode.GetNodeReference('OriginalModel')
      if originalModel:
        originalModel.SetName(deviceClass.ID + " model")
      deformedModel = self.parameterNode.GetNodeReference('DeformedModel')
      if deformedModel:
        deformedModel.SetName(deviceClass.ID + " deformed model")
    self.updateModel()

  def onDeviceParameterValueModified(self, caller=None, event=None):
    self.updateModel()

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

  def setCenterlineNode(self, centerlineCurveNode):
    if not self.parameterNode:
      return
    self.parameterNode.SetNodeReferenceID("CenterlineCurve", centerlineCurveNode.GetID() if centerlineCurveNode else None)
    if centerlineCurveNode:
      centerlineCurveNode.CreateDefaultDisplayNodes()
      centerlineCurveNode.GetDisplayNode().SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeUnconstrained)

  def getCenterlineNode(self):
    return self.parameterNode.GetNodeReference("CenterlineCurve") if self.parameterNode else None

  def setDeviceCenterlinePosition(self, value):
    if not self.parameterNode:
      return
    self.parameterNode.SetParameter("CenterlineCurvePosition", str(value))

  def getDeviceCenterlinePosition(self):
    value = self.parameterNode.GetParameter("CenterlineCurvePosition") if self.parameterNode else None
    return float(value) if value else None

  def setDeviceOrientationAdjustedOnCenterline(self, adjusted):
    self.parameterNode.SetParameter('DeviceOrientationAdjustedOnCenterline', 'true' if adjusted else 'false')

  def getDeviceOrientationAdjustedOnCenterline(self):
    value = self.parameterNode.GetParameter("DeviceOrientationAdjustedOnCenterline") if self.parameterNode else None
    return True if not value else value == 'true'

  def setDeviceOrientationFlippedOnCenterline(self, flipped):
    self.parameterNode.SetParameter('DeviceOrientationFlippedOnCenterline', 'true' if flipped else 'false')

  def getDeviceOrientationFlippedOnCenterline(self):
    return self.parameterNode.GetParameter('DeviceOrientationFlippedOnCenterline') == 'true'

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
    return self.parameterNode.GetNodeReference("VesselModel") if self.parameterNode else None

  def setDeviceClassId(self, deviceClassId):
    self.parameterNode.SetParameter("DeviceClassId", deviceClassId)
    self.updateModel()

  def getDeviceClassId(self):
    deviceClassId = self.parameterNode.GetParameter("DeviceClassId")
    return deviceClassId

  def getDeviceClass(self):
    if not self.parameterNode:
      return None
    deviceClassId = self.parameterNode.GetParameter("DeviceClassId")
    for deviceClass in CardiacDeviceSimulatorWidget.registeredDeviceClasses:
      if deviceClass.ID == deviceClassId:
        return deviceClass
    return None

  def setHandlesSettings(self, handlesPerSlice, handlesSpacingMm):
    if handlesPerSlice == self.getHandlesPerSlice() and handlesSpacingMm == self.getHandlesSpacingMm():
      return
    self.setHandlesPerSlice(handlesPerSlice)
    self.setHandlesSpacingMm(handlesSpacingMm)
    self.updateModel()

  def computeMetrics(self):

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    quantificationResultsFolderShItem = self.getQuantificationResultsFolderShItem()
    shNode.RemoveItemChildren(quantificationResultsFolderShItem)

    # Create color table and show the scalar bar widget

    colorTableRangeMm = float(self.parameterNode.GetParameter("ColorTableRangeMm"))
    colorNode = self.parameterNode.GetNodeReference('DisplacementToColorNode')

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
    modelSegments = ['whole'] + self.getDeviceClass().getSegments()
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

      compressionSliceRadiusArray.SetValue(sliceIndex, (originalSliceRadius-averageRadius)/originalSliceRadius*100.0
                                           if originalSliceRadius != 0.0 else 0.0)
      compressionSlicePerimeterArray.SetValue(sliceIndex, (originalSlicePerimeter-polygonPerimeter)/originalSlicePerimeter*100.0
                                              if originalSlicePerimeter != 0.0 else 0.0)
      compressionSliceAreaArray.SetValue(sliceIndex, (originalSliceArea-polygonArea)/originalSliceArea*100.0
                                         if originalSliceArea != 0.0 else 0.0)

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
      minDistancePercentArray.SetValue(sliceIndex, minDistance/radius*100 if radius !=0.0 else 0.0)
      maxDistancePercentArray.SetValue(sliceIndex, maxDistance/radius*100 if radius !=0.0 else 0.0)
      meanDistancePercentArray.SetValue(sliceIndex, meanDistance/radius*100 if radius !=0.0 else 0.0)

  def updateModel(self):

    if not self.parameterNode:
      return

    deviceClass = self.getDeviceClass()

    try:
      # Use device's updateModel method if implemented
      deviceClass.updateModel(self.parameterNode.GetNodeReference('OriginalModel'), self.parameterNode)

    except NotImplementedError:
      # Create whole (open) original and deformed models from profile
      modelParameters = deviceClass.getParameterValuesFromNode(self.parameterNode)

      # Get profile
      profilePoints = deviceClass.getProfilePoints(modelParameters)
      modelProfilePoints = vtk.vtkPoints()
      self.fitCurve(profilePoints, modelProfilePoints, self.getNumberOfProfilePoints(), deviceClass.getInternalParameters()['interpolationSmoothness'])

      # Update original model
      self.updateModelWithProfile(self.parameterNode.GetNodeReference('OriginalModel'), modelProfilePoints, self.getNumberOfModelPointsPerSlice())

      # Update deformed model
      # (if adjusting basic parameters then just update the original model)
      if self.updateDeformedModelsEnabled:
        self.updateModelWithProfile(self.parameterNode.GetNodeReference('DeformedModel'), modelProfilePoints, self.getNumberOfModelPointsPerSlice())
        self.handleProfilePoints.Reset()
        self.resampleCurve(modelProfilePoints, self.handleProfilePoints, self.getHandlesSpacingMm())
        self.updateHandlesWithProfile(self.parameterNode.GetNodeReference('OriginalHandles'), self.handleProfilePoints, self.getHandlesPerSlice())
        self.updateHandlesWithProfile(self.parameterNode.GetNodeReference('DeformedHandles'), self.handleProfilePoints, self.getHandlesPerSlice())
        self.updateDeformedModelsPending = False
        self.parameterNode.InvokeCustomModifiedEvent(CardiacDeviceBase.DEVICE_PROFILE_MODIFIED_EVENT)
      else:
        self.updateDeformedModelsPending = True

  def showDeformedModel(self, show):
      deformedModel = self.parameterNode.GetNodeReference('DeformedModel')
      if deformedModel:
        deformedModel.GetDisplayNode().SetVisibility(show)

  def showDeformationHandles(self, show):
      deformedHandles = self.parameterNode.GetNodeReference('DeformedHandles')
      if deformedHandles:
        deformedHandles.GetDisplayNode().SetVisibility(show)

  def setCenterlineEditingEnabled(self, enable):
    centerlineNode = self.getCenterlineNode()
    if not centerlineNode:
      return
    centerlineNode.SetLocked(not enable)
    numberOfcontrolPoints = centerlineNode.GetNumberOfControlPoints()
    wasModify = centerlineNode.StartModify()
    for i in range(numberOfcontrolPoints):
      centerlineNode.SetNthControlPointVisibility(i, enable)
    centerlineNode.EndModify(wasModify)

  def createOriginalAndDeformedSegmentModels(self, volumetric=False):
    if volumetric:
      typeName = "Volume"
    else:
      typeName = "Surface"

    resultsFolderShItem = self.getQuantificationResultsFolderShItem(typeName + " models")
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    if volumetric:
      shNode.SetItemExpanded(resultsFolderShItem, False)

    deviceClass = self.getDeviceClass()
    modelParameters = deviceClass.getParameterValuesFromNode(self.parameterNode)
    modelSegments = ['whole'] + self.getDeviceClass().getSegments()

    for seg in modelSegments:
      profilePoints = deviceClass.getProfilePoints(modelParameters, seg, not volumetric)
      modelProfilePoints = vtk.vtkPoints()
      self.fitCurve(profilePoints, modelProfilePoints, self.getNumberOfProfilePoints(), deviceClass.getInternalParameters()['interpolationSmoothness'])

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
          colorLegendDisplayNode = slicer.modules.colors.logic().AddDefaultColorLegendDisplayNode(model)
          colorLegendDisplayNode.SetTitleText("Radial\nCompression\n")
          colorLegendDisplayNode.SetMaxNumberOfColors(256)
          colorLegendDisplayNode.SetLabelFormat('%4.1f mm')


  def createModelNode(self, name, color):
    modelsLogic = slicer.modules.models.logic()
    polyData = vtk.vtkPolyData()
    modelNode = modelsLogic.AddModel(polyData)
    modelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name))
    displayNode = modelNode.GetDisplayNode()
    displayNode.SetColor(color)
    displayNode.SetBackfaceCulling(False)
    displayNode.SetEdgeVisibility(True)
    if slicer.app.majorVersion*100+slicer.app.minorVersion < 411:
      displayNode.SetSliceIntersectionVisibility(True)
    else:
      displayNode.SetVisibility2D(True)
    displayNode.SetSliceIntersectionThickness(2)
    return modelNode

  def createMarkupsNode(self, name, color):
    markupsLogic = slicer.modules.markups.logic()
    markupsNodeId = markupsLogic.AddNewFiducialNode(name)
    markupsNode = slicer.mrmlScene.GetNodeByID(markupsNodeId)
    markupsNode.GetDisplayNode().SetColor(color)
    markupsNode.GetDisplayNode().SetSelectedColor(color)
    markupsNode.GetDisplayNode().SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeUnconstrained)
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
      if slicer.app.majorVersion*100+slicer.app.minorVersion < 411:
        displayNode.SetSliceIntersectionVisibility(True)
      else:
        displayNode.SetVisibility2D(True)
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
    try:
      # Current API (Slicer-4.13 February 2022)
      markupsNode.RemoveAllControlPoints()
    except:
      # Legacy API
      markupsNode.RemoveAllMarkups()
    n = curvePoints.GetNumberOfPoints()
    pos = [0.0, 0.0, 0.0]
    for i in range(resolution * points.GetNumberOfPoints()):
      curvePoints.GetPoint(i, pos)
      try:
        # Current API (Slicer-4.13 February 2022)
        fidIndex = markupsNode.AddControlPoint(pos[0], pos[1], pos[2])
      except:
        # Legacy API
        fidIndex = markupsNode.AddFiducial(pos[0], pos[1], pos[2])
    markupsNode.EndModify(wasModifying)

  def setDeviceNormalizedPositionAlongCenterline(self, normalizedPosition, adjustOrientation):
    """normalizedPosition is between 0..1
    """
    positionOffset = self.getCenterlineNode().GetCurveLengthWorld() * normalizedPosition
    self.alignDeviceWithCenterline(positionOffset, adjustOrientation)

  def getNormalizedPositionAlongCenterline(self, point):
    """Returns normalized position (0->1) along the line
    """
    centerlineNode = self.getCenterlineNode()
    curvePointIndex = centerlineNode.GetClosestCurvePointIndexToPositionWorld(point)
    # curvePointIndex+1 is needed because this parameter is the number of curve points (not the curve point index)
    lengthToUntilPointPosition = centerlineNode.GetCurveLengthWorld(0, curvePointIndex + 1)
    totalLength = centerlineNode.GetCurveLengthWorld()
    return lengthToUntilPointPosition/totalLength

  def getClosestPointCoordinatesOnCenterline(self, point):
    closestPoint = [0,0,0]
    self.getCenterlineNode().GetClosestPointPositionAlongCurveWorld(point,closestPoint)
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

  def alignDeviceWithCenterline(self, deviceCenterOffset, adjustOrientation=True):

    # Get the distance of the two endpoints of the device from the origin
    originalModelNode = self.parameterNode.GetNodeReference('OriginalModel')
    originalModelNodePoints = slicer.util.arrayFromModelPoints(originalModelNode)
    originalModelNodePointsZMin = originalModelNodePoints[:,2].min()
    originalModelNodePointsZMax = originalModelNodePoints[:,2].max()

    centerlineCurveNode = self.getCenterlineNode()

    # Find point index corresponding to device endpoints in both directions along the curve
    startPointIndex = centerlineCurveNode.GetCurvePointIndexAlongCurveWorld(0, deviceCenterOffset + originalModelNodePointsZMin)
    endPointIndex = centerlineCurveNode.GetCurvePointIndexAlongCurveWorld(0, deviceCenterOffset + originalModelNodePointsZMax)

    centerlinePoints = slicer.util.arrayFromMarkupsCurvePoints(centerlineCurveNode, world=True)
    # Ensure that there are at least two curve points (to determine line orientation)
    if startPointIndex == endPointIndex:
      if startPointIndex > 0:
        startPointIndex -= 1
      else:
        endPointIndex += 1
    centerlinePointsAlongDevice = centerlinePoints[startPointIndex:endPointIndex+1]
    [linePosition, lineDirectionVector] = lineFit(centerlinePointsAlongDevice)
    # linePosition is set to center of gravity of fitted points,
    # which is not in the center of the model when we are at the start or end
    # of the curve, therefore we now get a more accurate position directly from the curve
    self.getCenterlineNode().GetPositionAlongCurveWorld(linePosition, 0, deviceCenterOffset)

    deviceCenterPoint = linePosition
    deviceToCenterlineTransform = self.parameterNode.GetNodeReference('PositioningTransform')

    if adjustOrientation:
      parentTransform = self.getDeviceCenterlineTransform(deviceCenterPoint, lineDirectionVector)
    else:
      parentTransform = self.getDeviceCenterLineTranslationOnly(deviceCenterPoint, deviceToCenterlineTransform)
      if self.getDeviceOrientationFlippedOnCenterline():
        deviceZAxisInRas = lineDirectionVector
      else:
        deviceZAxisInRas = -lineDirectionVector

    deviceToCenterlineTransform.SetAndObserveTransformToParent(parentTransform)

  def getDeviceCenterlineTransform(self, deviceCenterPoint, lineDirectionVector):
    if self.getDeviceOrientationFlippedOnCenterline():
      deviceZAxisInRas = lineDirectionVector
    else:
      deviceZAxisInRas = -lineDirectionVector
    deviceZAxisInRasUnitVector = deviceZAxisInRas / np.linalg.norm(deviceZAxisInRas)
    # "PositioningTransform" is overwritten with translation and orientation
    parentTransform = getVtkTransformPlaneToWorld(deviceCenterPoint, deviceZAxisInRasUnitVector)
    return parentTransform

  def getDeviceCenterLineTranslationOnly(self, deviceCenterPoint, deviceToCenterlineTransform):
    parentTransform = vtk.vtkTransform()
    centerLineTransform = deviceToCenterlineTransform.GetMatrixTransformToParent()
    centerLineTransform.SetElement(0, 3, deviceCenterPoint[0])
    centerLineTransform.SetElement(1, 3, deviceCenterPoint[1])
    centerLineTransform.SetElement(2, 3, deviceCenterPoint[2])
    parentTransform.SetMatrix(centerLineTransform)
    return parentTransform

  def deformHandlesToVesselWalls(self, allowDeviceExpansionToVesselWalls):
    import numpy as np

    # Initialize handle positions before warping
    self.updateModel()

    originalHandlesNode = self.parameterNode.GetNodeReference("OriginalHandles")
    deformedHandlesNode = self.parameterNode.GetNodeReference("DeformedHandles")
    try:
      # Slicer-4.13 (February 2022) and later
      numHandlePoints = deformedHandlesNode.GetNumberOfControlPoints()
    except:
      # fall back to older API
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
      try:
        # Current API (Slicer-4.13 February 2022)
        originalHandlesNode.GetNthControlPointPosition(handleID, originalHandlePoint)
      except:
        # Legacy API
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

        try:
          # Current API (Slicer-4.13 February 2022)
          deformedHandlesNode.SetNthFiducialPosition(handleID, pointOnVessel)
        except:
          # Legacy API
          deformedHandlesNode.SetNthControlPointPosition(handleID, pointOnVessel)
      else:
        # Check if handle point is outside of vessel walls; only deform (shrink) if it is. Device should not be expanded to fit
        # vessel walls because most/all RVOT devices cannot be expanded beyond their native form; they can only be compressed.
        distanceDeviceToCenterline = np.linalg.norm(originalHandlePoint-pointOnCenterline)
        distanceVesselToCenterline = np.linalg.norm(pointOnVessel-pointOnCenterline)
        try:
          # Current API (Slicer-4.13 February 2022)
          if distanceVesselToCenterline < distanceDeviceToCenterline:
            deformedHandlesNode.SetNthFiducialPosition(handleID, pointOnVessel)
          else:
            deformedHandlesNode.SetNthFiducialPosition(handleID, originalHandlePoint)
        except:
          # Legacy API
          if distanceVesselToCenterline < distanceDeviceToCenterline:
            deformedHandlesNode.SetNthControlPointPosition(handleID, pointOnVessel)
          else:
            deformedHandlesNode.SetNthControlPointPosition(handleID, originalHandlePoint)

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

      if slicer.app.majorVersion*100+slicer.app.minorVersion < 411:
        vesselLumenModelNode.GetDisplayNode().SliceIntersectionVisibilityOn()
      else:
        vesselLumenModelNode.GetDisplayNode().SetVisibility2D(True)
      self.setVesselModelNode(vesselLumenModelNode)
    slicer.modules.segmentations.logic().ExportSegmentToRepresentationNode(
      vesselLumenSegmentationNode.GetSegmentation().GetSegment(vesselLumenSegmentId), vesselLumenModelNode)
    shNode.SetItemParent(shNode.GetItemByDataNode(vesselLumenModelNode), centerlineFolderShItem)

    # Create centerline curve
    centerlineCurveNode = self.getCenterlineNode()
    if not centerlineCurveNode:
      centerlineCurveNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode', 'VesselCenterlineCurve')
      centerlineCurveNode.CreateDefaultDisplayNodes()
      self.setCenterlineNode(centerlineCurveNode)
    shNode.SetItemParent(shNode.GetItemByDataNode(centerlineCurveNode), centerlineFolderShItem)

    # Extract skeleton
    slicer.util.showStatusMessage("Extracting centerline, this may take a few minutes...", 3000)
    parameters = {}
    parameters["InputImageFileName"] = vesselLumenLabelMapNode.GetID()
    vesselCenterlineOutputLabelMapNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode', 'VesselCenterlineLabelMapTemp')
    parameters["OutputImageFileName"] = vesselCenterlineOutputLabelMapNode.GetID()
    parameters["OutputFiducialsFileName"] = centerlineCurveNode.GetID()
    parameters["NumberOfPoints"] = 100
    centerlineExtractor = slicer.modules.extractskeleton
    qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
    cliNode = slicer.cli.runSync(centerlineExtractor, None, parameters)
    qt.QApplication.restoreOverrideCursor()

    # Hide control points
    for i in range(centerlineCurveNode.GetNumberOfControlPoints()):
      centerlineCurveNode.SetNthControlPointVisibility(i, False)

    # Delete temporary nodes
    slicer.mrmlScene.RemoveNode(vesselLumenLabelMapNode)
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


#
# Utility functions copied from HeartValveLib to avoid dependencies.
# TODO: These functions can be removed when HeartValveLib is publicly released.
#

def lineFit(points):
  """
  Given an array, points, of shape (...,3)
  representing points in 3-dimensional space,
  fit a line to the points.
  Return a point on the plane (the point-cloud centroid),
  and the direction vector.

  :param points:
  :return: point on line, direction vector
  """

  import numpy as np

  # Calculate the mean of the points, i.e. the 'center' of the cloud
  pointsmean = points.mean(axis=0)

  # Do an SVD on the mean-centered data.
  uu, dd, vv = np.linalg.svd(points - pointsmean)

  # Now vv[0] contains the first principal component, i.e. the direction
  # vector of the 'best fit' line in the least squares sense.

  # Normalize direction vector to point towards end point
  approximateForwardDirection = points[-1] - points[0]
  approximateForwardDirection = approximateForwardDirection / np.linalg.norm(approximateForwardDirection)
  if np.dot(vv[0], approximateForwardDirection) >= 0:
    lineDirectionVector = vv[0]
  else:
    lineDirectionVector = -vv[0]

  return pointsmean, lineDirectionVector

def getVtkTransformPlaneToWorld(planePosition, planeNormal):
  import numpy as np
  transformPlaneToWorldVtk = vtk.vtkTransform()
  transformWorldToPlaneMatrix = getTransformToPlane(planePosition, planeNormal)
  transformPlaneToWorldMatrix = np.linalg.inv(transformWorldToPlaneMatrix)
  transformWorldToPlaneMatrixVtk = slicer.util.vtkMatrixFromArray(transformPlaneToWorldMatrix)
  transformPlaneToWorldVtk.SetMatrix(transformWorldToPlaneMatrixVtk)
  return transformPlaneToWorldVtk

def getTransformToPlane(planePosition, planeNormal):
  """Returns transform matrix from World to Plane coordinate systems.
  Plane is defined in the World coordinate system by planePosition and planeNormal.
  Plane coordinate system: origin is planePosition, z axis is planeNormal, x and y axes are orthogonal to z.
  """
  import numpy as np
  import math

  # Determine the plane coordinate system axes.
  planeZ_World = planeNormal/np.linalg.norm(planeNormal)

  # Generate a plane Y axis by generating an orthogonal vector to
  # plane Z axis vector by cross product plane Z axis vector with
  # an arbitrarily chosen vector (that is not parallel to the plane Z axis).
  unitX_World = np.array([0,0,1])
  angle = math.acos(np.dot(planeZ_World,unitX_World))
  # Normalize between -pi/2 .. +pi/2
  if angle>math.pi/2:
    angle -= math.pi
  elif angle<-math.pi/2:
    angle += math.pi
  if abs(angle)*180.0/math.pi>20.0:
    # unitX is not parallel to planeZ, we can use it
    planeY_World = np.cross(planeZ_World, unitX_World)
  else:
    # unitX is parallel to planeZ, use unitY instead
    unitY_World = np.array([0,1,0])
    planeY_World = np.cross(planeZ_World, unitY_World)

  planeY_World = planeY_World/np.linalg.norm(planeY_World)

  # X axis: orthogonal to tool's Y axis and Z axis
  planeX_World = np.cross(planeY_World, planeZ_World)
  planeX_World = planeX_World/np.linalg.norm(planeX_World)

  transformPlaneToWorld = np.row_stack((np.column_stack((planeX_World, planeY_World, planeZ_World, planePosition)),
                                        (0, 0, 0, 1)))
  transformWorldToPlane = np.linalg.inv(transformPlaneToWorld)

  return transformWorldToPlane
