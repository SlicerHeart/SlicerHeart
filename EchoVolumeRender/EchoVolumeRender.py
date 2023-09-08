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

  def onProcessVolume(self):
    outputVolumeNode = self.logic.smoothVolume(self.ui.processingInputVolumeSelector.currentNode(), self.ui.processingOutputVolumeSelector.currentNode(),
      self.ui.applyToSequenceCheckBox.checked, self.ui.smoothingFactorSlider.value)
    self.ui.processingOutputVolumeSelector.setCurrentNode(outputVolumeNode)
    self.ui.renderingInputVolumeSelector.setCurrentNode(outputVolumeNode)
    self.smoothingAutoUpdate = True

  def onCroppingToggle(self, toggled):
    vrDisplayNode = self.logic.volumeRenderingDisplayNode
    vrDisplayNode.SetCroppingEnabled(toggled)

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
      'saturationScale': 120.0
      }

    # Parameters that needs to trigger volume property update when changed
    self._volumePropertyParameterNames = ['threshold', 'edgeSmoothing']

    # Shader replacement is slightly differs between VTK8/VTK9
    vtkVersion = vtk.VTK_MAJOR_VERSION * 100 + vtk.VTK_MINOR_VERSION
    if vtkVersion < 900: # VTK 8.x
      self.computeColorReplacement = self.ComputeColorReplacementVTK8
    elif vtkVersion < 902:  # VTK 9.0-9.1
      self.computeColorReplacement = self.ComputeColorReplacementVTK900
    else:  # VTK >= 9.2
      self.computeColorReplacement = self.ComputeColorReplacementVTK902

  def sequenceFromVolume(self, proxyNode):
    if not proxyNode:
      return [None, None]
    for browserNode in slicer.util.getNodesByClass('vtkMRMLSequenceBrowserNode'):
      sequenceNode = browserNode.GetSequenceNode(proxyNode)
      if sequenceNode:
        return [browserNode, sequenceNode]
    return [None, None]
    
  def smoothVolume(self, inputVolume, outputVolume, allowSequenceSmoothing, smoothingStandardDeviation):
    """
    Run the actual algorithm
    """

    logging.info('Processing started')

    newOutputVolume = False
    if not outputVolume:
      outputVolume = slicer.mrmlScene.AddNewNodeByClass(inputVolume.GetClassName(), inputVolume.GetName()+' filtered')
      outputVolume.SetAndObserveTransformNodeID(inputVolume.GetTransformNodeID())
      inputVolume.CreateDefaultDisplayNodes()
      inputVolumeDisplayNode = inputVolume.GetScalarVolumeDisplayNode()
      outputVolume.CreateDefaultDisplayNodes()
      outputVolume.GetScalarVolumeDisplayNode().SetWindowLevelMinMax(
        inputVolumeDisplayNode.GetWindowLevelMin(),
        inputVolumeDisplayNode.GetWindowLevelMax())
      newOutputVolume = True

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
      tempOutputVolume = slicer.mrmlScene.AddNewNodeByClass(tempInputVolume.GetClassName())

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
        #seqBrowser.AddSynchronizedSequenceNode(outputVolSeq)
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

    shaderPropertyNode = volumeRenderingDisplayNode.GetOrCreateShaderPropertyNode(slicer.mrmlScene)
    sp = shaderPropertyNode.GetShaderProperty()
    sp.ClearAllShaderReplacements()
    sp.AddShaderReplacement(vtk.vtkShader.Fragment, "//VTK::ComputeColor::Dec", True, self.computeColorReplacement, True)

    return volumeRenderingDisplayNode

  def resetRenderingParametersToDefault(self, volumeRenderingDisplayNode, force=True):
    shaderPropertyNode = volumeRenderingDisplayNode.GetOrCreateShaderPropertyNode(slicer.mrmlScene)
    uniforms = shaderPropertyNode.GetFragmentUniforms()
    if force:
      uni.RemoveAllUniforms()
    for name in self.defaultShaderParameters:
      if force or uniforms.GetUniformTupleType(name) == vtk.vtkUniforms.TupleTypeInvalid:
        if isinstance(self.defaultShaderParameters[name], list):
          uniforms.SetUniform2f(name, self.defaultShaderParameters[name])
        else:
          uniforms.SetUniformf(name, self.defaultShaderParameters[name])

  def setVolumeRenderingVisible(self, visible):
    self.volumeRenderingDisplayNode.SetVisibility(visible)

  def _getRenderingParameterValue(self, name):
    if not self.shaderPropertyNode:
      return self.defaultShaderParameters[name]
    uniforms = self.shaderPropertyNode.GetFragmentUniforms()
    if uniforms.GetUniformTupleType(name) == vtk.vtkUniforms.TupleTypeVector:
      value = [0.0, 0.0]
      uniforms.GetUniform2f(name, value)
      return value
    else:
      value = vtk.mutable(0)
      uniforms.GetUniformf(name, value)
      return value.get()

  def _setRenderingParameterValue(self, name, value):
    uniforms = self.shaderPropertyNode.GetFragmentUniforms()
    if uniforms.GetUniformTupleType(name) == vtk.vtkUniforms.TupleTypeVector:
      uniforms.SetUniform2f(name, value)
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

  def updateVolumeProperty(self):
    
    if not self.volumeRenderingDisplayNode:
      return

    # retrieve scalar opacity transfer function
    volPropNode = self.volumeRenderingDisplayNode.GetVolumePropertyNode()
    if not volPropNode:
      volPropNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVolumePropertyNode")
      self.volumeRenderingDisplayNode.SetAndObserveVolumePropertyNodeID(volPropNode.GetID())
    disableModify = volPropNode.StartModify()

    # Set up lighting/material
    volPropNode.GetVolumeProperty().ShadeOn()
    #volPropNode.GetVolumeProperty().SetAmbient(0.5)
    #volPropNode.GetVolumeProperty().SetDiffuse(0.5)
    #volPropNode.GetVolumeProperty().SetSpecular(0.5)
    volPropNode.GetVolumeProperty().SetAmbient(0.1)
    volPropNode.GetVolumeProperty().SetDiffuse(0.9)
    volPropNode.GetVolumeProperty().SetSpecular(0.2)
    volPropNode.GetVolumeProperty().SetSpecularPower(10)

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

    volPropNode.EndModify(disableModify)
    volPropNode.Modified()

  
  # Code for color shader replacement
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

vec4 computeColor(vec4 scalar, float opacity)
{
    // Get base color from color transfer function (defines darkening of transparent voxels and neutral color)

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

  ComputeColorReplacementVTK8 = "uniform sampler2D in_colorTransferFunc_0[1];\n" + ComputeColorReplacementCommon + """
    return computeLighting(color, 0);
}
"""

  ComputeColorReplacementVTK900 = "uniform sampler2D in_colorTransferFunc_0[1];\n" + ComputeColorReplacementCommon + """
    return computeLighting(color, 0, 0.0);
}
"""

  # in_colorTransferFunc_0 is already included in VTK>=9.2
  ComputeColorReplacementVTK902 = ComputeColorReplacementCommon + """
    return computeLighting(color, 0, 0.0);
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
