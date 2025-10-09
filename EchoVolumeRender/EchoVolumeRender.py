import os
import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging

#
# EchoVolumeRender
#

class EchoVolumeRender(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Echo Volume Render"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Simon Drouin (Brigham and Women's Hospital)"]
    self.parent.helpText = """
Use custom shaders for depth-dependent coloring for volume rendering of 3D/4D ultrasound images.
"""
    self.parent.helpText += self.getDefaultModuleDocumentationLink()
    self.parent.acknowledgementText = """
This file was originally developed by Simon Drouin of the Brigham and Women's Hospital, Boston, MA.
"""

#
# EchoVolumeRenderWidget
#

class EchoVolumeRenderWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    self.logic = EchoVolumeRenderLogic()

    # Load widget from .ui file (created by Qt Designer)
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/EchoVolumeRender.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    self.ui.processingInputVolumeSelector.setMRMLScene(slicer.mrmlScene)
    self.ui.processingVelocityVolumeSelector.setMRMLScene(slicer.mrmlScene)
    self.ui.processingOutputVolumeSelector.setMRMLScene(slicer.mrmlScene)
    self.ui.renderingInputVolumeSelector.setMRMLScene(slicer.mrmlScene)

    # connections
    self.ui.renderingInputVolumeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelectRenderingInputVolume)
    self.ui.thresholdSlider.valueChanged.connect(lambda value: self.logic._setRenderingParameterValue("threshold", value))
    self.ui.edgeSmoothingSlider.valueChanged.connect(lambda value: self.logic._setRenderingParameterValue("edgeSmoothing", value))
    self.ui.depthRangeSlider.valuesChanged.connect(lambda minValue, maxValue: self.logic._setRenderingParameterValue("depthRange", [minValue, maxValue]))
    self.ui.depthDarkeningSlider.valueChanged.connect(lambda value: self.logic._setRenderingParameterValue("depthDarkening", value))
    self.ui.depthColoringRangeSlider.valuesChanged.connect(lambda minValue, maxValue: self.logic._setRenderingParameterValue("depthColoringRange", [minValue, maxValue]))
    self.ui.brightnessScaleSlider.valueChanged.connect(lambda value: self.logic._setRenderingParameterValue("brightnessScale", value))
    self.ui.saturationScaleSlider.valueChanged.connect(lambda value: self.logic._setRenderingParameterValue("saturationScale", value))
    self.ui.volumeRenderingVisibleCheckBox.stateChanged.connect(lambda state: self.logic.setVolumeRenderingVisible(state == qt.Qt.Checked))
    self.ui.processingInputVolumeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelectProcessingInputVolume)
    self.ui.smoothingFactorSlider.valueChanged.connect(lambda value: self.onSmoothingChanged(value))
    self.ui.processButton.connect("clicked()", self.onProcessVolume)
    self.ui.croppingToggleCheckBox.connect("toggled(bool)", self.onCroppingToggle)
    self.ui.croppingToggleROIVisibilityCheckBox.connect("toggled(bool)", self.onCroppingToggleROIVisibility)
    self.ui.croppingFitToVolume.connect("clicked()", self.onCroppingFitToVolume)
    self.ui.cropEchoCheckBox.connect("clicked()", self.updateCroppingComponents)
    self.ui.cropVelocityCheckBox.connect("clicked()", self.updateCroppingComponents)

    # Enable hot update when slider is moved
    self.smoothingAutoUpdate = False

    # Add vertical spacer
    self.layout.addStretch(1)

    self.updateGui()

  def cleanup(self):
    pass

  def onSelectProcessingInputVolume(self):
    self.smoothingAutoUpdate = False
    self.updateGui()

  def onSelectRenderingInputVolume(self):
    volume = self.ui.renderingInputVolumeSelector.currentNode()
    self.logic.inputVolumeNode = volume
    self.updateGui()

  def onSmoothingChanged(self, value):
    # If in single-volume update mode, then update is fast enough
    # to do perform filtering immediately
    if not self.ui.applyToSequenceCheckBox.checked and self.smoothingAutoUpdate:
      self.onProcessVolume()

  def updateCroppingComponents(self):
    clippingComponents = self.logic.clippingComponents
    clippingComponents[0] = 1.0 if self.ui.cropEchoCheckBox.checked else 0.0
    clippingComponents[1] = 1.0 if self.ui.cropVelocityCheckBox.checked else 0.0
    self.logic._setRenderingParameterValue("clippingComponents", clippingComponents)

  def onProcessVolume(self):
    with slicer.util.RenderBlocker():
      inputVolumeNode = self.ui.processingInputVolumeSelector.currentNode()
      temporaryNode = None
      volumeToSmooth = inputVolumeNode

      outputVolumeNode = self.logic.smoothVolume(volumeToSmooth, self.ui.processingOutputVolumeSelector.currentNode(),
        self.ui.applyToSequenceCheckBox.checked, self.ui.smoothingFactorSlider.value)

      if not self.ui.processingVelocityVolumeSelector.currentNode() is None:
        temporaryNode = outputVolumeNode
        outputVolumeNode = EchoVolumeRenderLogic.combineVolumesSequence(outputVolumeNode, self.ui.processingVelocityVolumeSelector.currentNode(),
          self.ui.applyToSequenceCheckBox.checked)

      if temporaryNode:
        # Erase the intermediate volume and sequence nodes
        [_, combinedSequenceNode] = self.logic.sequenceFromVolume(temporaryNode)
        if combinedSequenceNode:
          slicer.mrmlScene.RemoveNode(combinedSequenceNode)
        slicer.mrmlScene.RemoveNode(temporaryNode)

      self.ui.processingOutputVolumeSelector.setCurrentNode(outputVolumeNode)
      self.ui.renderingInputVolumeSelector.setCurrentNode(outputVolumeNode)
      self.smoothingAutoUpdate = True

      self.logic.updateShaderReplacement(outputVolumeNode)
      self.logic.updateVolumeProperty()

  def onCroppingToggle(self, toggled):
    vrDisplayNode = self.logic.volumeRenderingDisplayNode
    vrDisplayNode.SetCroppingEnabled(toggled)
    self.logic.updateShaderReplacement(self.logic.inputVolumeNode)

  def onCroppingToggleROIVisibility(self, toggled):
    roiDisplayNode = self.logic.volumeRenderingDisplayNode.GetMarkupsROINode().GetDisplayNode()
    roiDisplayNode.SetVisibility(toggled)

  def onCroppingFitToVolume(self):
    vrDisplayNode = self.logic.volumeRenderingDisplayNode
    slicer.modules.volumerendering.logic().FitROIToVolume(vrDisplayNode)

  def updateGui(self):

    processingInputVolume = self.ui.processingInputVolumeSelector.currentNode()
    [browserNode, sequenceNode] = self.logic.sequenceFromVolume(processingInputVolume)
    self.ui.applyToSequenceCheckBox.enabled = (sequenceNode is not None)
    self.ui.processButton.enabled = (processingInputVolume is not None)

    # Enable / disable GUI elements based on availability of volume
    controlsEnabled = (self.logic.inputVolumeNode != None)
    self.ui.thresholdSlider.setEnabled(controlsEnabled)
    self.ui.edgeSmoothingSlider.setEnabled(controlsEnabled)
    self.ui.depthRangeSlider.setEnabled(controlsEnabled)
    self.ui.depthDarkeningSlider.setEnabled(controlsEnabled)
    self.ui.depthColoringRangeSlider.setEnabled(controlsEnabled)
    self.ui.brightnessScaleSlider.setEnabled(controlsEnabled)
    self.ui.saturationScaleSlider.setEnabled(controlsEnabled)
    self.ui.croppingToggleCheckBox.setEnabled(controlsEnabled)
    self.ui.croppingToggleROIVisibilityCheckBox.setEnabled(controlsEnabled)
    self.ui.croppingFitToVolume.setEnabled(controlsEnabled)
    self.ui.cropEchoCheckBox.setEnabled(controlsEnabled)
    self.ui.cropVelocityCheckBox.setEnabled(controlsEnabled)

    prev = self.ui.thresholdSlider.blockSignals(True)
    self.ui.thresholdSlider.value = self.logic.threshold
    self.ui.thresholdSlider.blockSignals( prev )

    prev = self.ui.edgeSmoothingSlider.blockSignals(True)
    self.ui.edgeSmoothingSlider.value = self.logic.edgeSmoothing
    self.ui.edgeSmoothingSlider.blockSignals( prev )

    prev = self.ui.depthRangeSlider.blockSignals(True)
    self.ui.depthRangeSlider.minimumValue = self.logic.depthRange[0]
    self.ui.depthRangeSlider.maximumValue = self.logic.depthRange[1]
    self.ui.depthRangeSlider.blockSignals( prev )

    prev = self.ui.depthDarkeningSlider.blockSignals(True)
    self.ui.depthDarkeningSlider.setValue( self.logic.depthDarkening)
    self.ui.depthDarkeningSlider.blockSignals( prev )

    prev = self.ui.depthColoringRangeSlider.blockSignals(True)
    self.ui.depthColoringRangeSlider.minimumValue = self.logic.depthColoringRange[0]
    self.ui.depthColoringRangeSlider.maximumValue = self.logic.depthColoringRange[1]
    self.ui.depthColoringRangeSlider.blockSignals( prev )

    prev = self.ui.brightnessScaleSlider.blockSignals(True)
    self.ui.brightnessScaleSlider.setValue(self.logic.brightnessScale)
    self.ui.brightnessScaleSlider.blockSignals(prev)

    prev = self.ui.saturationScaleSlider.blockSignals(True)
    self.ui.saturationScaleSlider.setValue(self.logic.saturationScale)
    self.ui.saturationScaleSlider.blockSignals(prev)

    prev = self.ui.volumeRenderingVisibleCheckBox.blockSignals(True)
    volumeRenderingVisible = self.logic.volumeRenderingDisplayNode.GetVisibility() if self.logic.volumeRenderingDisplayNode else False
    self.ui.volumeRenderingVisibleCheckBox.setChecked(volumeRenderingVisible)
    self.ui.volumeRenderingVisibleCheckBox.blockSignals(prev)

    prev = self.ui.cropEchoCheckBox.blockSignals(True)
    self.ui.cropEchoCheckBox.setChecked(self.logic.clippingComponents[0] > 0)
    self.ui.cropEchoCheckBox.blockSignals(prev)

    prev = self.ui.cropVelocityCheckBox.blockSignals(True)
    self.ui.cropVelocityCheckBox.setChecked(self.logic.clippingComponents[1] > 0)
    self.ui.cropVelocityCheckBox.blockSignals(prev)

    vrDisplayNode = self.logic.volumeRenderingDisplayNode
    if vrDisplayNode:

      prev = self.ui.croppingToggleCheckBox.blockSignals(True)
      self.ui.croppingToggleCheckBox.setChecked(vrDisplayNode.GetCroppingEnabled())
      self.ui.croppingToggleCheckBox.blockSignals(prev)

      if vrDisplayNode.GetMarkupsROINode():
        prev = self.ui.croppingToggleROIVisibilityCheckBox.blockSignals(True)
        self.ui.croppingToggleROIVisibilityCheckBox.setChecked(vrDisplayNode.GetMarkupsROINode().GetDisplayNode().GetVisibility())
        self.ui.croppingToggleROIVisibilityCheckBox.blockSignals(prev)

#
# EchoVolumeRenderLogic
#

class EchoVolumeRenderLogic(ScriptedLoadableModuleLogic):
  """Implements the functionality to apply echo-specific volume
  rendering effects to the volume selected in the interface and
  modify the parameters of the effects.
  """

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)
    self._inputVolumeNode = None

    # Cached for faster access
    self.volumeRenderingDisplayNode = None
    self.shaderPropertyNode = None

    self.defaultShaderParameters = {
      'threshold': 20.0,
      'edgeSmoothing': 5.0,
      'depthRange': [-120.0, 10.0],
      'depthDarkening': 30,
      'depthColoringRange': [-24, 23],
      'brightnessScale': 120.0,
      'saturationScale': 120.0,
      'clippingComponents': [1.0, 1.0, 1.0]
      }

    # Parameters that needs to trigger volume property update when changed
    self._volumePropertyParameterNames = ['threshold', 'edgeSmoothing']

    # Shader replacement is slightly differs between VTK8/VTK9
    vtkVersion = vtk.VTK_MAJOR_VERSION * 100 + vtk.VTK_MINOR_VERSION
    if vtkVersion < 900: # VTK 8.x
      self.computeColorReplacementSingleComponent = self.ComputeColorReplacementVTK8SingleComponent
      self.computeColorReplacementMultiComponent = self.ComputeColorReplacementVTK8MultiComponent
    elif vtkVersion < 902:  # VTK 9.0-9.1
      self.computeColorReplacementSingleComponent = self.ComputeColorReplacementVTK900SingleComponent
      self.computeColorReplacementMultiComponent = self.ComputeColorReplacementVTK900MultiComponent
    else:  # VTK >= 9.2
      self.computeColorReplacementSingleComponent = self.ComputeColorReplacementVTK902SingleComponent
      self.computeColorReplacementMultiComponent = self.ComputeColorReplacementVTK902MultiComponent

  @staticmethod
  def sequenceFromVolume(proxyNode):
    if not proxyNode:
      return [None, None]
    for browserNode in slicer.util.getNodesByClass('vtkMRMLSequenceBrowserNode'):
      sequenceNode = browserNode.GetSequenceNode(proxyNode)
      if sequenceNode:
        return [browserNode, sequenceNode]
    return [None, None]

  @staticmethod
  def combineVolumesSequence(echoVolumeNode, velocityVolumeNode, allowSequenceSmoothing):
    """
    Combine two volume nodes into a new volume node with two components.
    The first component will contain the data from echoVolumeNode and the second
    component will contain the data from velocityVolumeNode.
    :param echoVolumeNode: First input volume node
    :param velocityVolumeNode: Second input volume node
    :return: New volume node with combined data
    Example use:

        EchoVolumeRender.EchoVolumeRenderLogic.combineVolumes(getNode('*echo*'), getNode('*velocity*'))
    """

    # Create a new volume node to store the combined volume
    combinedVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
    combinedVolumeNode.SetName(echoVolumeNode.GetName() + " + " + velocityVolumeNode.GetName())
    combinedVolumeNode.SetAndObserveTransformNodeID(echoVolumeNode.GetTransformNodeID())
    if not allowSequenceSmoothing:
      EchoVolumeRenderLogic.combineVolumes(echoVolumeNode, velocityVolumeNode, combinedVolumeNode)
      return combinedVolumeNode

    [seqBrowser, echoVolumeSequence] = EchoVolumeRenderLogic.sequenceFromVolume(echoVolumeNode)
    [_, velocityVolumeSequence] = EchoVolumeRenderLogic.sequenceFromVolume(velocityVolumeNode)

    if slicer.app.majorVersion*100+slicer.app.minorVersion < 411:
      sequencesModule = slicer.modules.sequencebrowser
    else:
      sequencesModule = slicer.modules.sequences

    try:
      qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)

      combinedVolumeSequenceNode = sequencesModule.logic().AddSynchronizedNode(None, combinedVolumeNode, seqBrowser)

      tempCombinedVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
      tempCombinedVolumeNode.Copy(combinedVolumeNode)

      numberOfDataNodes = echoVolumeSequence.GetNumberOfDataNodes()
      for seqItemNumber in range(numberOfDataNodes):
        slicer.app.processEvents(qt.QEventLoop.ExcludeUserInputEvents)

        echoVolumeDataNode = echoVolumeSequence.GetDataNodeAtValue(echoVolumeSequence.GetNthIndexValue(seqItemNumber))
        velocityVolumeDataNode = velocityVolumeSequence.GetDataNodeAtValue(velocityVolumeSequence.GetNthIndexValue(seqItemNumber))
        EchoVolumeRenderLogic.combineVolumes(echoVolumeDataNode, velocityVolumeDataNode, tempCombinedVolumeNode)
        combinedVolumeSequenceNode.SetDataNodeAtValue(tempCombinedVolumeNode, echoVolumeSequence.GetNthIndexValue(seqItemNumber))

      slicer.mrmlScene.RemoveNode(tempCombinedVolumeNode)

    finally:
      qt.QApplication.restoreOverrideCursor()

    return combinedVolumeNode

  @staticmethod
  def combineVolumes(echoVolumeNode, velocityVolumeNode, outputVolumeNode=None):
    """
    Combine two volume nodes into a new volume node with two components.
    The first component will contain the data from echoVolumeNode and the second
    component will contain the data from velocityVolumeNode.
    :param echoVolumeNode: First input volume node
    :param velocityVolumeNode: Second input volume node
    :return: New volume node with combined data
    Example use:

        EchoVolumeRender.EchoVolumeRenderLogic.combineVolumes(getNode('*echo*'), getNode('*velocity*'))
    """

    # Get image data from the input volumes
    imageData1 = echoVolumeNode.GetImageData()
    imageData2 = velocityVolumeNode.GetImageData()

    # Ensure the dimensions of the input volumes are the same
    if imageData1.GetDimensions() != imageData2.GetDimensions():
      raise ValueError("Input volumes must have the same dimensions.")

    appendComponents = vtk.vtkImageAppendComponents()
    appendComponents.AddInputData(imageData1)
    appendComponents.AddInputData(imageData2)
    appendComponents.Update()

    # Create a new volume node to store the combined volume
    if outputVolumeNode:
      combinedVolumeNode = outputVolumeNode
    else:
      combinedVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
    combinedVolumeNode.SetAndObserveImageData(appendComponents.GetOutput())
    ijkToRAS = vtk.vtkMatrix4x4()
    echoVolumeNode.GetIJKToRASMatrix(ijkToRAS)
    combinedVolumeNode.SetIJKToRASMatrix(ijkToRAS)

    return combinedVolumeNode

  def smoothVolume(self, inputVolume, outputVolume, allowSequenceSmoothing, smoothingStandardDeviation):
    """
    Run the actual algorithm
    """

    logging.info('Processing started')

    newOutputVolume = False
    outputNodeName = f"{inputVolume.GetName()} filtered"
    if not outputVolume:
      outputVolume = slicer.mrmlScene.AddNewNodeByClass(inputVolume.GetClassName(), outputNodeName)
      outputVolume.SetAndObserveTransformNodeID(inputVolume.GetTransformNodeID())
      inputVolume.CreateDefaultDisplayNodes()
      inputVolumeDisplayNode = inputVolume.GetScalarVolumeDisplayNode()
      outputVolume.CreateDefaultDisplayNodes()
      outputVolume.GetScalarVolumeDisplayNode().SetWindowLevelMinMax(
        inputVolumeDisplayNode.GetWindowLevelMin(),
        inputVolumeDisplayNode.GetWindowLevelMax())
      newOutputVolume = True
    else:
      outputVolume.SetName(outputNodeName)

    if allowSequenceSmoothing:
      [inputVolSeqBrowser, inputVolSeq] = self.sequenceFromVolume(inputVolume)
      [outputVolSeqBrowser, outputVolSeq] = self.sequenceFromVolume(outputVolume)
    else:
      inputVolSeq = None
      outputVolSeq = None

    if inputVolSeq is None:
      # Process a single volume
      inputImageData = inputVolume.GetImageData()
      spacing = inputVolume.GetSpacing()
      gaussianFilter = vtk.vtkImageGaussianSmooth()
      gaussianFilter.SetStandardDeviations(smoothingStandardDeviation / spacing[0],
                                           smoothingStandardDeviation / spacing[1],
                                           smoothingStandardDeviation / spacing[2])
      gaussianFilter.SetInputData(inputImageData)
      gaussianFilter.Update()
      ijkToRas = vtk.vtkMatrix4x4()
      inputVolume.GetIJKToRASMatrix(ijkToRas)
      outputVolume.SetIJKToRASMatrix(ijkToRas)
      outputVolume.SetAndObserveImageData(gaussianFilter.GetOutput())
      logging.info('Processing completed')
      if newOutputVolume:
        slicer.util.setSliceViewerLayers(background=outputVolume)
      return outputVolume

    # Process a sequence

    seqBrowser = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode")
    seqBrowser.SetAndObserveMasterSequenceNodeID(inputVolSeq.GetID())
    seqBrowser.SetSaveChanges(inputVolSeq, True)  # allow modifying node in the sequence

    seqBrowser.SetSelectedItemNumber(0)
    if slicer.app.majorVersion*100+slicer.app.minorVersion < 411:
      sequencesModule = slicer.modules.sequencebrowser
    else:
      sequencesModule = slicer.modules.sequences
    sequencesModule.logic().UpdateAllProxyNodes()
    slicer.app.processEvents()
    tempInputVolume = seqBrowser.GetProxyNode(inputVolSeq)

    if not outputVolSeq:
      outputVolSeq = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", inputVolSeq.GetName()+" filtered")

    if outputVolSeq != inputVolSeq:
      # Initialize output sequence
      outputVolSeq.RemoveAllDataNodes()
      outputVolSeq.SetIndexType(inputVolSeq.GetIndexType())
      outputVolSeq.SetIndexName(inputVolSeq.GetIndexName())
      outputVolSeq.SetIndexUnit(inputVolSeq.GetIndexUnit())
      tempOutputVolume = slicer.mrmlScene.AddNewNodeByClass(outputVolume.GetClassName())

    try:
      qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
      numberOfDataNodes = inputVolSeq.GetNumberOfDataNodes()
      for seqItemNumber in range(numberOfDataNodes):
        slicer.app.processEvents(qt.QEventLoop.ExcludeUserInputEvents)
        seqBrowser.SetSelectedItemNumber(seqItemNumber)
        sequencesModule.logic().UpdateProxyNodesFromSequences(seqBrowser)

        inputImageData = tempInputVolume.GetImageData()
        spacing = inputVolume.GetSpacing()
        gaussianFilter = vtk.vtkImageGaussianSmooth()
        gaussianFilter.SetStandardDeviations(smoothingStandardDeviation / spacing[0],
                                             smoothingStandardDeviation / spacing[1],
                                             smoothingStandardDeviation / spacing[2])
        gaussianFilter.SetInputData(inputImageData)
        gaussianFilter.Update()
        ijkToRas = vtk.vtkMatrix4x4()
        tempInputVolume.GetIJKToRASMatrix(ijkToRas)
        tempOutputVolume.SetIJKToRASMatrix(ijkToRas)
        tempOutputVolume.SetAndObserveImageData(gaussianFilter.GetOutput())

        if outputVolSeq != inputVolSeq:
          outputVolSeq.SetDataNodeAtValue(tempOutputVolume, inputVolSeq.GetNthIndexValue(seqItemNumber))

    finally:
      qt.QApplication.restoreOverrideCursor()

      # Temporary input browser node
      slicer.mrmlScene.RemoveNode(seqBrowser)
      slicer.mrmlScene.RemoveNode(tempInputVolume)
      slicer.mrmlScene.RemoveNode(tempOutputVolume)

      if sequencesModule.logic().GetFirstBrowserNodeForSequenceNode(outputVolSeq):
        # Refresh proxy node
        seqBrowser = sequencesModule.logic().GetFirstBrowserNodeForSequenceNode(outputVolSeq)
        sequencesModule.logic().UpdateProxyNodesFromSequences(seqBrowser)
      else:
        # Move output sequence node in the same browser node as the input volume sequence
        # if not in a sequence browser node already.

        # Add output sequence to a sequence browser
        seqBrowser = sequencesModule.logic().GetFirstBrowserNodeForSequenceNode(inputVolSeq)
        if not seqBrowser:
          seqBrowser = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode")
        seqBrowser.AddSynchronizedSequenceNode(outputVolSeq)
        seqBrowser.AddProxyNode(outputVolume, outputVolSeq, False)
        seqBrowser.SetSaveChanges(outputVolSeq, True)

        # Show output in slice views
        sequencesModule.logic().UpdateAllProxyNodes()
        slicer.app.processEvents()
        slicer.util.setSliceViewerLayers(background=outputVolume)

    logging.info('Processing completed')

    return outputVolume

  def hasImageData(self, volumeNode):
    if not volumeNode:
      logging.debug('hasImageData failed: no volume node')
      return False
    if volumeNode.GetImageData() is None:
      logging.debug('hasImageData failed: no image data in volume node')
      return False
    return True

  @property
  def inputVolumeNode(self):
    return self._inputVolumeNode

  @inputVolumeNode.setter
  def inputVolumeNode(self, volumeNode):
    if volumeNode == self._inputVolumeNode:
      return

    self._inputVolumeNode = volumeNode
    self.volumeRenderingDisplayNode = self._setupVolumeRenderingDisplayNode(volumeNode)
    self.updateShaderReplacement(volumeNode)
    self.shaderPropertyNode = self.volumeRenderingDisplayNode.GetOrCreateShaderPropertyNode(slicer.mrmlScene) if self.volumeRenderingDisplayNode else None

    # Update volume rendering
    self.updateVolumeProperty()

  def _setupVolumeRenderingDisplayNode(self, volumeNode):
    """Sets up volume rendering display node and associated property and ROI nodes.
    If the nodes already exist and valid then nothing is changed.
    :param volumeNode: input volume node
    :return: volume rendering display node
    """

    # Make sure the volume node has image data
    if self.hasImageData(volumeNode) == False:
      return None

    # Make sure the volume node has a volume rendering display node
    volRenLogic = slicer.modules.volumerendering.logic()
    volumeRenderingDisplayNode = volRenLogic.GetFirstVolumeRenderingDisplayNode(volumeNode)
    if not volumeRenderingDisplayNode:
      volumeRenderingDisplayNode = volRenLogic.CreateDefaultVolumeRenderingNodes(volumeNode)

    # Make sure GPU volume rendering is used
    if not volumeRenderingDisplayNode.IsA("vtkMRMLGPURayCastVolumeRenderingDisplayNode"):
      gpuVolumeRenderingDisplayNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLGPURayCastVolumeRenderingDisplayNode")
      roiNode = volumeRenderingDisplayNode.GetROINodeID()
      gpuVolumeRenderingDisplayNode.SetAndObserveROINodeID(roiNode)
      gpuVolumeRenderingDisplayNode.SetAndObserveVolumePropertyNodeID(volumeRenderingDisplayNode.GetVolumePropertyNodeID())
      gpuVolumeRenderingDisplayNode.SetAndObserveShaderPropertyNodeID(volumeRenderingDisplayNode.GetShaderPropertyNodeID())
      gpuVolumeRenderingDisplayNode.SetCroppingEnabled(volumeRenderingDisplayNode.GetCroppingEnabled())
      gpuVolumeRenderingDisplayNode.SetThreshold(volumeRenderingDisplayNode.GetThreshold())
      gpuVolumeRenderingDisplayNode.SetWindowLevel(volumeRenderingDisplayNode.GetWindowLevel())
      gpuVolumeRenderingDisplayNode.SetFollowVolumeDisplayNode(volumeRenderingDisplayNode.GetFollowVolumeDisplayNode())
      gpuVolumeRenderingDisplayNode.SetIgnoreVolumeDisplayNodeThreshold(volumeRenderingDisplayNode.GetIgnoreVolumeDisplayNodeThreshold())
      gpuVolumeRenderingDisplayNode.SetUseSingleVolumeProperty(volumeRenderingDisplayNode.GetUseSingleVolumeProperty())
      volumeNode.AddAndObserveDisplayNodeID(gpuVolumeRenderingDisplayNode.GetID())
      slicer.modules.volumerendering.logic().UpdateDisplayNodeFromVolumeNode(gpuVolumeRenderingDisplayNode, volumeNode)
      slicer.mrmlScene.RemoveNode(volumeRenderingDisplayNode)
      volumeRenderingDisplayNode = gpuVolumeRenderingDisplayNode

    # Keep only first volume rendering display node, delete all the others
    displayNodes = []
    for displayNodeIndex in range(volumeNode.GetNumberOfDisplayNodes()):
      displayNodes.append(volumeNode.GetNthDisplayNode(displayNodeIndex))
    alreadyAdded = False
    for displayNode in displayNodes:
      if not displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
        continue
      if displayNode == volumeRenderingDisplayNode:
        alreadyAdded = True
        continue
      slicer.mrmlScene.RemoveNode(displayNode)

    # Make sure markups ROI node is used (if Slicer is recent enough)
    if vtk.vtkVersion().GetVTKMajorVersion() >= 9:
      if not volumeRenderingDisplayNode.GetMarkupsROINode():
        markupsRoiNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsROINode', volumeNode.GetName()+' ROI')
        markupsRoiNode.CreateDefaultDisplayNodes()
        markupsRoiNode.GetDisplayNode().SetVisibility(False)
        markupsRoiNode.GetDisplayNode().SetPropertiesLabelVisibility(False)
        markupsRoiNode.GetDisplayNode().SetRotationHandleVisibility(True)
        markupsRoiNode.GetDisplayNode().SetTranslationHandleVisibility(True)
        markupsRoiNode.GetDisplayNode().FillVisibilityOff()
        annotationRoiNode = volumeRenderingDisplayNode.GetROINode()
        volumeRenderingDisplayNode.SetAndObserveROINodeID(markupsRoiNode.GetID())
        if annotationRoiNode:
          roiCenter = [0.0, 0.0, 0.0]
          roiRadius = [1.0, 1.0, 1.0]
          annotationRoiNode.GetXYZ(roiCenter)
          annotationRoiNode.GetRadiusXYZ(roiRadius)
          markupsRoiNode.SetXYZ(roiCenter)
          markupsRoiNode.SetRadiusXYZ(roiRadius)
          slicer.mrmlScene.RemoveNode(annotationRoiNode)
        else:
          slicer.modules.volumerendering.logic().FitROIToVolume(volumeRenderingDisplayNode)

    self.resetRenderingParametersToDefault(volumeRenderingDisplayNode, force=False)
    return volumeRenderingDisplayNode

  def updateShaderReplacement(self, volumeNode):
    volRenLogic = slicer.modules.volumerendering.logic()
    volumeRenderingDisplayNode = volRenLogic.GetFirstVolumeRenderingDisplayNode(volumeNode)
    if not volumeRenderingDisplayNode:
      return

    shaderPropertyNode = volumeRenderingDisplayNode.GetOrCreateShaderPropertyNode(slicer.mrmlScene)
    sp = shaderPropertyNode.GetShaderProperty()
    sp.ClearAllShaderReplacements()

    if volumeNode.GetImageData() is None or volumeNode.GetImageData().GetNumberOfScalarComponents() == 1:
      computeColorReplacement = self.computeColorReplacementSingleComponent
    else:
      computeColorReplacement = self.computeColorReplacementMultiComponent
    sp.AddShaderReplacement(vtk.vtkShader.Fragment, "//VTK::ComputeColor::Dec", True, computeColorReplacement, True)

    clippingEnabled = volumeRenderingDisplayNode.GetCroppingEnabled()
    if clippingEnabled:
      sp.AddShaderReplacement(vtk.vtkShader.Fragment, "//VTK::Clipping::Dec", True, self.ClippingDecReplacement, True)
      sp.AddShaderReplacement(vtk.vtkShader.Fragment, "//VTK::Clipping::Init", True, "", True)
      sp.AddShaderReplacement(vtk.vtkShader.Fragment, "//VTK::Cropping::Impl", True, self.CroppingImplReplacement, True)
      sp.AddShaderReplacement(vtk.vtkShader.Fragment, "//VTK::Shading::Impl", True, self.ShadingImplReplacement, True)
      sp.AddShaderReplacement(vtk.vtkShader.Fragment, "//VTK::ComputeGradient::Dec", True, self.ComputeGradientDecReplacement, True)

  def resetRenderingParametersToDefault(self, volumeRenderingDisplayNode, force=True):
    shaderPropertyNode = volumeRenderingDisplayNode.GetOrCreateShaderPropertyNode(slicer.mrmlScene)
    uniforms = shaderPropertyNode.GetFragmentUniforms()
    if force:
      uniforms.RemoveAllUniforms()
    for name in self.defaultShaderParameters:
      if force or uniforms.GetUniformTupleType(name) == vtk.vtkUniforms.TupleTypeInvalid:
        if isinstance(self.defaultShaderParameters[name], list):
          if len(self.defaultShaderParameters[name]) == 2:
            uniforms.SetUniform2f(name, self.defaultShaderParameters[name])
          elif len(self.defaultShaderParameters[name]) == 3:
            uniforms.SetUniform3f(name, self.defaultShaderParameters[name])
        elif isinstance(self.defaultShaderParameters[name], bool):
          uniforms.SetUniformi(name, int(self.defaultShaderParameters[name]))
        elif isinstance(self.defaultShaderParameters[name], int):
          uniforms.SetUniformi(name, int(self.defaultShaderParameters[name]))
        else:
          uniforms.SetUniformf(name, self.defaultShaderParameters[name])

  def setVolumeRenderingVisible(self, visible):
    self.volumeRenderingDisplayNode.SetVisibility(visible)

  def _getRenderingParameterValue(self, name):
    if not self.shaderPropertyNode:
      return self.defaultShaderParameters[name]
    uniforms = self.shaderPropertyNode.GetFragmentUniforms()
    if uniforms.GetUniformTupleType(name) == vtk.vtkUniforms.TupleTypeVector:
      numberOfComponents = uniforms.GetUniformNumberOfComponents(name)
      value = [0.0] * numberOfComponents
      if numberOfComponents == 2:
        uniforms.GetUniform2f(name, value)
      elif numberOfComponents == 3:
        uniforms.GetUniform3f(name, value)
      elif numberOfComponents == 4:
        uniforms.GetUniform4f(name, value)
      return value
    else:
      value = vtk.mutable(0)
      uniforms.GetUniformf(name, value)
      return value.get()

  def _setRenderingParameterValue(self, name, value):
    uniforms = self.shaderPropertyNode.GetFragmentUniforms()
    if uniforms.GetUniformTupleType(name) == vtk.vtkUniforms.TupleTypeVector:
      if len(value) == 2:
        uniforms.SetUniform2f(name, value)
      elif len(value) == 3:
        uniforms.SetUniform3f(name, value)
      elif len(value) == 4:
        uniforms.SetUniform4f(name, value)
    else:
      uniforms.SetUniformf(name, value)
    if name in self._volumePropertyParameterNames:
      self.updateVolumeProperty()

  @property
  def threshold(self):
    return self._getRenderingParameterValue("threshold")

  @threshold.setter
  def threshold(self, value):
    self._setRenderingParameterValue("threshold", value)
    self.updateVolumeProperty()

  @property
  def edgeSmoothing(self):
    return self._getRenderingParameterValue("edgeSmoothing")

  @edgeSmoothing.setter
  def edgeSmoothing(self, value):
    self._setRenderingParameterValue("edgeSmoothing", value)
    self.updateVolumeProperty()

  @property
  def depthRange(self):
    return self._getRenderingParameterValue("depthRange")

  @depthRange.setter
  def depthRange(self, valueRange):
    self._setRenderingParameterValue("depthRange", valueRange)

  @property
  def depthDarkening(self):
    return self._getRenderingParameterValue("depthDarkening")

  @depthDarkening.setter
  def depthDarkening(self, value):
    self._setRenderingParameterValue("depthDarkening", value)

  @property
  def depthColoringRange(self):
    return self._getRenderingParameterValue("depthColoringRange")

  @depthColoringRange.setter
  def depthColoringRange(self, valueRange):
    self._setRenderingParameterValue("depthColoringRange", valueRange)

  @property
  def brightnessScale(self):
    return self._getRenderingParameterValue("brightnessScale")

  @brightnessScale.setter
  def brightnessScale(self, value):
    self._setRenderingParameterValue("brightnessScale", value)

  @property
  def saturationScale(self):
    return self._getRenderingParameterValue("saturationScale")

  @saturationScale.setter
  def saturationScale(self, value):
    self._setRenderingParameterValue("saturationScale", value)

  @property
  def clippingComponents(self):
    return self._getRenderingParameterValue("clippingComponents")

  @clippingComponents.setter
  def clippingComponents(self, value):
    self._setRenderingParameterValue("clippingComponents", value)

  def updateVolumeProperty(self):

    if not self.volumeRenderingDisplayNode:
      return

    # retrieve scalar opacity transfer function
    volPropNode = self.volumeRenderingDisplayNode.GetVolumePropertyNode()
    if not volPropNode:
      volPropNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVolumePropertyNode")
      self.volumeRenderingDisplayNode.SetAndObserveVolumePropertyNodeID(volPropNode.GetID())
    disableModify = volPropNode.StartModify()

    volPropNode.GetVolumeProperty().SetInterpolationTypeToNearest()

    # Set up lighting/material
    volPropNode.GetVolumeProperty().ShadeOn(0)
    volPropNode.GetVolumeProperty().SetAmbient(0, 0.1)
    volPropNode.GetVolumeProperty().SetDiffuse(0, 0.9)
    volPropNode.GetVolumeProperty().SetSpecular(0, 0.2)
    volPropNode.GetVolumeProperty().SetSpecularPower(0, 10.0)

    # disable shading for the second component (velocity)
    volPropNode.GetVolumeProperty().ShadeOff(1)
    volPropNode.GetVolumeProperty().SetDiffuse(1, 1.0)
    volPropNode.GetVolumeProperty().SetAmbient(1, 1.0)
    volPropNode.GetVolumeProperty().SetSpecular(1, 0.0)
    volPropNode.GetVolumeProperty().SetSpecularPower(1, 10.0)

    slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLViewNode").SetVolumeRenderingSurfaceSmoothing(True)

    # compute parameters of the piecewise opacity function
    #volRange = self.getCurrentVolumeNode().GetImageData().GetScalarRange()
    volRange = [0,255] # set fixed range so that absolute threshold value does not change as we switch volumes

    eps = 1e-3  # to make sure rampeStart<rampEnd
    volRangeWidth = ( volRange[1] - volRange[0] )
    edgeSmoothing = max(eps, self.edgeSmoothing)

    rampCenter = volRange[0] + self.threshold * 0.01 * volRangeWidth
    rampStart = rampCenter - edgeSmoothing * 0.01 * volRangeWidth
    rampEnd = rampCenter + edgeSmoothing * 0.01 * volRangeWidth

    # build opacity function
    scalarOpacity = vtk.vtkPiecewiseFunction()
    scalarOpacity.AddPoint(min(volRange[0],rampStart),0.0)
    scalarOpacity.AddPoint(rampStart,0.0)
    scalarOpacity.AddPoint(rampCenter,0.2)
    scalarOpacity.AddPoint(rampCenter+eps,0.8)
    scalarOpacity.AddPoint(rampEnd,0.95)
    scalarOpacity.AddPoint(max(volRange[1],rampEnd),0.95)

    # build color transfer function
    darkBrown = [84.0/255.0, 51.0/255.0, 42.0/255.0]
    green = [0.5, 1.0, 0.5]
    colorTransferFunction = vtk.vtkColorTransferFunction()
    colorTransferFunction.AddRGBPoint(min(volRange[0],rampStart), 0.0, 0.0, 0.0)
    colorTransferFunction.AddRGBPoint((rampStart+rampCenter)/2.0, *darkBrown)
    colorTransferFunction.AddRGBPoint(rampCenter, *green)
    colorTransferFunction.AddRGBPoint(rampEnd, *green)
    colorTransferFunction.AddRGBPoint(max(volRange[1],rampEnd), *green)

    volPropNode.GetVolumeProperty().GetScalarOpacity().DeepCopy(scalarOpacity)
    volPropNode.GetVolumeProperty().GetRGBTransferFunction().DeepCopy(colorTransferFunction)

    # Transfer functions for the second channel
    # TODO: expose parameters on the GUI
    try:
      colorTable = slicer.util.getNode("Speed") # TODO
      colorTransferFunction = vtk.vtkColorTransferFunction()
      scalarOpacity = vtk.vtkPiecewiseFunction()
      points = list(range(0, 256, 5))
      points.append(127)
      points.append(128)
      for i in points:
        color = [0.0, 0.0, 0.0, 0.0]
        colorTable.GetColor(i, color)
        colorTransferFunction.AddRGBPoint(i, color[0], color[1], color[2])
      colorTransferFunction.AddRGBPoint(127.5, 1.0, 1.0, 1.0)

      opacityFunction = {
        0.0: 0.0,
        40.0: 0.0,
        55.0: 0.1,
        127.5: 0.1,
        205.0: 0.1,
        220.0: 0.0,
        255.0: 0.0
      }
      for x in opacityFunction:
        scalarOpacity.AddPoint(x, opacityFunction[x])

      volPropNode.GetVolumeProperty().GetScalarOpacity(1).DeepCopy(scalarOpacity)
      volPropNode.GetVolumeProperty().GetRGBTransferFunction(1).DeepCopy(colorTransferFunction)
      volPropNode.EndModify(disableModify)
      volPropNode.GetVolumeProperty().GetScalarOpacity(1).Modified()
      volPropNode.GetVolumeProperty().GetRGBTransferFunction(1).Modified()
      volPropNode.GetVolumeProperty().Modified()
      volPropNode.Modified()
    except Exception as e:
      logging.warning("Failed to set transfer functions for the second component: "+str(e))

  ComputeColorReplacementSingleComponentFunction = """
vec4 computeColor(vec4 scalar, float opacity)
{
"""

  ComputeColorReplacementMultiComponentFunction = """
vec4 computeColor(vec4 scalar, float opacity, int component)
{
    // Get base color from color transfer function (defines darkening of transparent voxels and neutral color)

    if (component > 0)
    {
      return clamp(
        computeLighting(
          vec4(texture2D(in_colorTransferFunc_0[component], vec2(scalar[component], 0.0)).xyz, opacity), component, 0.0),
          0.0,
          1.0);
    }
"""

  ComputeColorReplacement = """
    vec3 baseColorRgb = texture2D(in_colorTransferFunc_0[0], vec2(scalar.w, 0.0)).xyz;
    vec3 baseColorHsv = rgb2hsv(baseColorRgb);

    // Modulate hue and brightness depending on distance

    float hueFar = clamp(baseColorHsv.x-depthColoringRange.x*0.01, 0.0, 1.0);
    float hueNear = clamp(baseColorHsv.x-depthColoringRange.y*0.01, 0.0, 1.0);
    float sat = clamp(saturationScale*0.01*baseColorHsv.y,0.0,1.0);
    float brightnessNear = brightnessScale*0.01*baseColorHsv.z;
    float brightnessFar = clamp(brightnessScale*0.01*(baseColorHsv.z-depthDarkening*0.01), 0.0, 1.0);

    // Determine the ratio (dist) that serves to interpolate between the near
    // color and the far color. depthRange specifies the depth range, in voxel
    // coordinates, between the front color and back color.
    vec3 camInTexCoord = (ip_inverseTextureDataAdjusted * vec4(g_eyePosObj.xyz,1.0) ).xyz;
    float depthRangeInTexCoordStart = (ip_inverseTextureDataAdjusted * vec4(0,0,depthRange.x,1.0) ).z;
    float depthRangeInTexCoordEnd = (ip_inverseTextureDataAdjusted * vec4(0,0,depthRange.y,1.0) ).z;
    vec3 dp = g_dataPos - camInTexCoord;
    vec3 dv = vec3(0.5,0.5,0.5) - camInTexCoord;
    float lv = length(dv);
    float lp = dot(dp, dv) / lv;
    float dist = (lp - lv - depthRangeInTexCoordStart) / ( depthRangeInTexCoordEnd - depthRangeInTexCoordStart);
    dist = clamp( dist, 0.0, 1.0 );

    vec3 rgbNear = hsv2rgb(vec3( hueNear, sat, brightnessNear));
    vec3 rgbFar = hsv2rgb(vec3( hueFar, sat, brightnessFar));
    vec3 rgbDepthModulated = mix( rgbNear, rgbFar, dist );

    vec4 color = vec4(rgbDepthModulated, opacity);
"""

  # Code for color shader replacement
  # Separate functions are required for single and multi-component volumes
  # (component is only available if the volume has multiple channels)
  ComputeColorReplacementCommon = """
vec3 rgb2hsv(vec3 c)
{
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));

    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c)
{
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}
"""
  ComputeColorReplacementCommonSingleComponent = ComputeColorReplacementCommon + ComputeColorReplacementSingleComponentFunction + ComputeColorReplacement
  ComputeColorReplacementCommonMultiComponent  = ComputeColorReplacementCommon + ComputeColorReplacementMultiComponentFunction  + ComputeColorReplacement

  ################################################################
  # Shader replacement code for VTK 8.x
  ComputeColorReplacementVTK8Uniform = "uniform sampler2D in_colorTransferFunc_0[1];\n"
  ComputeColorReplacementVTK8Return = """
    return computeLighting(color, 0);
}
"""
  ComputeColorReplacementVTK8SingleComponent = ComputeColorReplacementVTK8Uniform + ComputeColorReplacementCommonSingleComponent + ComputeColorReplacementVTK8Return
  ComputeColorReplacementVTK8MultiComponent = ComputeColorReplacementVTK8Uniform + ComputeColorReplacementCommonMultiComponent + ComputeColorReplacementVTK8Return

  ##################################################################
  # Shader replacement code for VTK 9.0-9.1
  ComputeColorReplacementVTK900Uniform = "uniform sampler2D in_colorTransferFunc_0[1];\n"
  ComputeColorReplacementVTK900Return = """
    return computeLighting(color, 0, 0.0);
}
"""
  ComputeColorReplacementVTK900SingleComponent = ComputeColorReplacementVTK900Uniform + ComputeColorReplacementCommonSingleComponent + ComputeColorReplacementVTK900Return
  ComputeColorReplacementVTK900MultiComponent = ComputeColorReplacementVTK900Uniform + ComputeColorReplacementCommonMultiComponent + ComputeColorReplacementVTK900Return

  ###################################################################
  # Shader replacement code for VTK 9.2 and later
  # in_colorTransferFunc_0 is already included in VTK>=9.2
  ComputeColorReplacementVTK902Return = """
    return computeLighting(color, 0, 0.0);
}
"""
  ComputeColorReplacementVTK902SingleComponent = ComputeColorReplacementCommonSingleComponent + ComputeColorReplacementVTK902Return
  ComputeColorReplacementVTK902MultiComponent = ComputeColorReplacementCommonMultiComponent + ComputeColorReplacementVTK902Return

  ClippingDecReplacement = """
//VTK::Clipping::Dec

// isPointInROI: returns true if pointTex lies inside (or on) all clipping planes.
// Planes layout:
//   in_clippingPlanes[0] = 6 * numPlanes
//   For each plane k:
//     origin: in_clippingPlanes[1 + 6*k + 0..2]
//     normal: in_clippingPlanes[1 + 6*k + 3..5]  (object space)
bool isPointInROI(vec3 pointTex)
{
  int clip_numPlanes = int(in_clippingPlanes[0]);
  if (clip_numPlanes <= 0)
  {
    return true;
  }

  clip_texToObjMat = in_volumeMatrix[0] * inverse(ip_inverseTextureDataAdjusted);
  clip_objToTexMat = ip_inverseTextureDataAdjusted * in_inverseVolumeMatrix[0];

  vec4 pointPosObj = vec4(0.0);
  {
      pointPosObj = clip_texToObjMat * vec4(pointTex, 1.0);
      pointPosObj = pointPosObj / pointPosObj.w;
      pointPosObj.w = 1.0;
  }

  for (int i = 0; i < clip_numPlanes; i = i + 6)
  {
    vec3 planeOrigin = vec3(in_clippingPlanes[i + 1],
                            in_clippingPlanes[i + 2],
                            in_clippingPlanes[i + 3]);
    vec3 planeNormal = normalize(vec3(in_clippingPlanes[i + 4],
                                      in_clippingPlanes[i + 5],
                                      in_clippingPlanes[i + 6]));
    float distance = dot(planeNormal, planeOrigin - pointPosObj.xyz);
    if (distance > 0.0)
    {
      return false;
    }
  }
  return true;
}
"""
  CroppingImplReplacement = """
    vec4 local_componentWeight = in_componentWeight;
    for (int c = 0; c < in_noOfComponents; ++c)
    {
      if (clippingComponents[c] > 0 && !isPointInROI(g_dataPos))
      {
        local_componentWeight[c] = 0.0;
      }
    }
"""
  ShadingImplReplacement = """
    if (!g_skip)
    {
      vec4 scalar;

      scalar = texture3D(in_volume[0], g_dataPos);

      scalar = scalar * in_volume_scale[0] + in_volume_bias[0];
      vec4 color[4]; vec4 tmp = vec4(0.0);
      float totalAlpha = 0.0;
      for (int i = 0; i < in_noOfComponents; ++i)
        {
        // Data fetching from the red channel of volume texture
        color[i][3] = computeOpacity(scalar, i);
        color[i] = computeColor(scalar, color[i][3], i);
        totalAlpha += color[i][3] * local_componentWeight[i];
        }
      if (totalAlpha > 0.0)
        {
        for (int i = 0; i < in_noOfComponents; ++i)
          {
          // Only let visible components contribute to the final color
          if (local_componentWeight[i] <= 0) continue;

          tmp.x += color[i].x * color[i].w * local_componentWeight[i];
          tmp.y += color[i].y * color[i].w * local_componentWeight[i];
          tmp.z += color[i].z * color[i].w * local_componentWeight[i];
          tmp.w += ((color[i].w * color[i].w)/totalAlpha);
          }
        }
      g_fragColor = (1.0f - g_fragColor.a) * tmp + g_fragColor;
    }
"""
  ComputeGradientDecReplacement = """
vec4 computeGradient(in vec3 texPos, in int c, in sampler3D volume,in int index)
{
  // Approximate Nabla(F) derivatives with central differences.
  vec3 g1; // F_front
  vec3 g2; // F_back
  vec3 xvec = vec3(in_cellStep[index].x, 0.0, 0.0);
  vec3 yvec = vec3(0.0, in_cellStep[index].y, 0.0);
  vec3 zvec = vec3(0.0, 0.0, in_cellStep[index].z);
  vec3 texPosPvec[3];
  texPosPvec[0] = texPos + xvec;
  texPosPvec[1] = texPos + yvec;
  texPosPvec[2] = texPos + zvec;
  vec3 texPosNvec[3];
  texPosNvec[0] = texPos - xvec;
  texPosNvec[1] = texPos - yvec;
  texPosNvec[2] = texPos - zvec;
  g1.x = texture3D(volume, vec3(texPosPvec[0]))[c];
  g1.y = texture3D(volume, vec3(texPosPvec[1]))[c];
  g1.z = texture3D(volume, vec3(texPosPvec[2]))[c];
  g2.x = texture3D(volume, vec3(texPosNvec[0]))[c];
  g2.y = texture3D(volume, vec3(texPosNvec[1]))[c];
  g2.z = texture3D(volume, vec3(texPosNvec[2]))[c];

  for (int j = 0; j < 3; ++j)
  {
    if (clippingComponents[c] > 0 && !isPointInROI(texPosPvec[j].xyz))
    {
      g1[j] = in_clippedVoxelIntensity;
    }
    if (clippingComponents[c] > 0 && !isPointInROI(texPosNvec[j].xyz))
    {
      g2[j] = in_clippedVoxelIntensity;
    }
  }

  // Apply scale and bias to the fetched values.
  g1 = g1 * in_volume_scale[index][c] + in_volume_bias[index][c];
  g2 = g2 * in_volume_scale[index][c] + in_volume_bias[index][c];

  // Scale values the actual scalar range.
  float range = in_scalarsRange[4*index+c][1] - in_scalarsRange[4*index+c][0];
  g1 = in_scalarsRange[4*index+c][0] + range * g1;
  g2 = in_scalarsRange[4*index+c][0] + range * g2;

  // Central differences: (F_front - F_back) / 2h
  g2 = g1 - g2;

  float avgSpacing = (in_cellSpacing[index].x +
   in_cellSpacing[index].y + in_cellSpacing[index].z) / 3.0;
  vec3 aspect = in_cellSpacing[index] * 2.0 / avgSpacing;
  g2 /= aspect;
  float grad_mag = length(g2);

  // Handle normalizing with grad_mag == 0.0
  g2 = grad_mag > 0.0 ? normalize(g2) : vec3(0.0);

  // Since the actual range of the gradient magnitude is unknown,
  // assume it is in the range [0, 0.25 * dataRange].
  range = range != 0 ? range : 1.0;
  grad_mag = grad_mag / (0.25 * range);
  grad_mag = clamp(grad_mag, 0.0, 1.0);

  return vec4(g2.xyz, grad_mag);
}
"""

#
# EchoVolumeRenderTest
#
class EchoVolumeRenderTest(ScriptedLoadableModuleTest):
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
    self.test_EchoVolumeRender1()

  def test_EchoVolumeRender1(self):
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

    volumeNode = slicer.util.getNode(pattern="FA")
    logic = EchoVolumeRenderLogic()
    self.assertIsNotNone( logic.hasImageData(volumeNode) )
    self.delayDisplay('Test passed!')
