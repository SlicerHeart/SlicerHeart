import os
import unittest
import logging
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

#
# Reconstruct4DCineMRI
#

class Reconstruct4DCineMRI(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Reconstruct 4D cine-MRI"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Andras Lasso (PerkLab)"]
    self.parent.helpText = """
This module can reconstruct 4D volume (sequence of 3D volumes) from a sequence of 2D MRI slices.
See more information in <a href="https://github.com/SlicerHeart/SlicerHeart">module documentation</a>.
"""
    # TODO: replace with organization, grant and thanks
    self.parent.acknowledgementText = """
This file was originally developed by Andras Lasso, PerkLab.
"""

#
# Reconstruct4DCineMRIWidget
#

class Reconstruct4DCineMRIWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.__init__(self, parent)
    VTKObservationMixin.__init__(self)  # needed for parameter node observation
    self.logic = None
    self._parameterNode = None
    self._updatingGUIFromParameterNode = False

  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    if int(slicer.app.revision) < 30097:
      # Requires DICOM volume sequences that contain triggerTime
      slicer.util.errorDisplay(f"This module requires Slicer core version\nSlicer-4.13.0-2021-08-08 (rev 30097) or later.",
        detailedText="In earlier Slicer versions, automatic detection of frame indices is not available.")

    # Load widget from .ui file (created by Qt Designer).
    # Additional widgets can be instantiated manually and added to self.layout.
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/Reconstruct4DCineMRI.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
    # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
    # "setMRMLScene(vtkMRMLScene*)" slot.
    uiWidget.setMRMLScene(slicer.mrmlScene)

    # Create logic class. Logic implements all computations that should be possible to run
    # in batch mode, without a graphical user interface.
    self.logic = Reconstruct4DCineMRILogic()
    self.logic.progressCallback = self.onProgress

    # Connections

    # These connections ensure that we update parameter node when scene is closed
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    self.ui.inputSequenceSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
    self.ui.inputRoiSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
    self.ui.outputSequenceSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
    self.ui.outputSpacingSpinBox.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
    self.ui.autoDetectFramesCheckBox.connect("stateChanged(int)", self.updateParameterNodeFromGUI)
    self.ui.framesTextEdit.connect("textChanged()", self.updateParameterNodeFromGUI)

    self.ui.progressBar.visible = False

    # Buttons
    self.ui.applyButton.connect('clicked(bool)', self.onApplyButton)

    # Make sure parameter node is initialized (needed for module reload)
    self.initializeParameterNode()

  def cleanup(self):
    """
    Called when the application closes and the module widget is destroyed.
    """
    self.removeObservers()

  def enter(self):
    """
    Called each time the user opens this module.
    """
    # Make sure parameter node exists and observed
    self.initializeParameterNode()

  def exit(self):
    """
    Called each time the user opens a different module.
    """
    # Do not react to parameter node changes (GUI wlil be updated when the user enters into the module)
    self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

  def onSceneStartClose(self, caller, event):
    """
    Called just before the scene is closed.
    """
    # Parameter node will be reset, do not use it anymore
    self.setParameterNode(None)

  def onSceneEndClose(self, caller, event):
    """
    Called just after the scene is closed.
    """
    # If this module is shown while the scene is closed then recreate a new parameter node immediately
    if self.parent.isEntered:
      self.initializeParameterNode()

  def initializeParameterNode(self):
    """
    Ensure parameter node exists and observed.
    """
    # Parameter node stores all user choices in parameter values, node selections, etc.
    # so that when the scene is saved and reloaded, these settings are restored.

    self.setParameterNode(self.logic.getParameterNode())

    # Select default input nodes if nothing is selected yet to save a few clicks for the user
    if not self._parameterNode.GetNodeReference("InputSequence"):
      volumeNodes = slicer.util.getNodesByClass('vtkMRMLScalarVolumeNode')
      for volumeNode in volumeNodes:
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(volumeNode)
        if browserNode:
          inputSequenceNode = browserNode.GetSequenceNode(volumeNode)
          if inputSequenceNode:
            self._parameterNode.SetNodeReferenceID("InputSequence", inputSequenceNode.GetID())
            break

  def setParameterNode(self, inputParameterNode):
    """
    Set and observe parameter node.
    Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
    """

    if inputParameterNode:
      self.logic.setDefaultParameters(inputParameterNode)

    # Unobserve previously selected parameter node and add an observer to the newly selected.
    # Changes of parameter node are observed so that whenever parameters are changed by a script or any other module
    # those are reflected immediately in the GUI.
    if self._parameterNode is not None:
      self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self._parameterNode = inputParameterNode
    if self._parameterNode is not None:
      self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    # Initial GUI update
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self, caller=None, event=None):
    """
    This method is called whenever parameter node is changed.
    The module GUI is updated to show the current state of the parameter node.
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
    self._updatingGUIFromParameterNode = True

    try:

      # Update node selectors and sliders
      self.ui.inputSequenceSelector.setCurrentNode(self._parameterNode.GetNodeReference("InputSequence"))
      self.ui.inputRoiSelector.setCurrentNode(self._parameterNode.GetNodeReference("InputROI"))
      self.ui.outputSequenceSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputSequence"))
      self.ui.outputSpacingSpinBox.value = float(self._parameterNode.GetParameter("OutputSpacing")) if self._parameterNode.GetParameter("OutputSpacing") else 1.0
      self.ui.autoDetectFramesCheckBox.checked = (self._parameterNode.GetParameter("AutoDetectFrames") == "true")
      if self.ui.framesTextEdit.plainText != self._parameterNode.GetParameter("FramesText"):
        self.ui.framesTextEdit.plainText = self._parameterNode.GetParameter("FramesText")

      # Update buttons states and tooltips
      if self._parameterNode.GetNodeReference("InputSequence") and self._parameterNode.GetNodeReference("InputROI"):
        self.ui.applyButton.toolTip = "Reconstruct output volume sequence"
        self.ui.applyButton.enabled = True
      else:
        self.ui.applyButton.toolTip = "Select input sequence and input region"
        self.ui.applyButton.enabled = False
    finally:
      # All the GUI updates are done
      self._updatingGUIFromParameterNode = False

  def updateParameterNodeFromGUI(self, caller=None, event=None):
    """
    This method is called when the user makes any change in the GUI.
    The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

    self._parameterNode.SetNodeReferenceID("InputSequence", self.ui.inputSequenceSelector.currentNodeID)
    self._parameterNode.SetNodeReferenceID("InputROI", self.ui.inputRoiSelector.currentNodeID)
    self._parameterNode.SetNodeReferenceID("OutputSequence", self.ui.outputSequenceSelector.currentNodeID)
    self._parameterNode.SetParameter("OutputSpacing", str(self.ui.outputSpacingSpinBox.value))
    self._parameterNode.SetParameter("AutoDetectFrames", "true" if self.ui.autoDetectFramesCheckBox.checked else "false")
    self._parameterNode.SetParameter("FramesText", str(self.ui.framesTextEdit.plainText))

    self._parameterNode.EndModify(wasModified)

  def onProgress(self, percentComplete):
    self.ui.progressBar.value = percentComplete
    self.ui.progressBar.visible = (percentComplete < 100)

  def onApplyButton(self):
    """
    Run processing when user clicks "Apply" button.
    """
    try:

      # Get frame indices (which frames are pasted into each volume)
      if self.ui.autoDetectFramesCheckBox.checked:
        try:
          frameIndices = Reconstruct4DCineMRILogic.getFrameIndices(self.ui.inputSequenceSelector.currentNode())
        except ValueError as e:
          slicer.util.errorDisplay(f"Failed to get frame indices automatically {str(e)}. Specify them manually in Advanced section.")
          frameIndices = [list(range(self.ui.inputSequenceSelector.currentNode().GetNumberOfDataNodes()))]
        self.ui.framesTextEdit.plainText = Reconstruct4DCineMRILogic.frameIndicesToText(frameIndices)
      else:
        frameIndices = Reconstruct4DCineMRILogic.frameIndicesFromText(self.ui.framesTextEdit.plainText)

      reconstructedVolumeSeqNode = self.logic.reconstructVolumeSequence(
        self.ui.inputSequenceSelector.currentNode(), self.ui.inputRoiSelector.currentNode(),
        self.ui.outputSequenceSelector.currentNode(),
        frameIndices, self.ui.outputSpacingSpinBox.value)

      self.ui.outputSequenceSelector.setCurrentNode(reconstructedVolumeSeqNode)

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()

    self.ui.progressBar.visible = False


#
# Reconstruct4DCineMRILogic
#

class Reconstruct4DCineMRILogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)
    self.progressCallback = None

  def setDefaultParameters(self, parameterNode):
    """
    Initialize parameter node with default settings.
    """
    if not parameterNode.GetParameter("AutoDetectFrames"):
      parameterNode.SetParameter("AutoDetectFrames", "true")
    if not parameterNode.GetParameter("OutputSpacing"):
      parameterNode.SetParameter("OutputSpacing", "1.0")

  @staticmethod
  def frameIndicesToText(frameIndices):
    frameIndicesStr = ""
    for frameIndicesForSingleVolume in frameIndices:
      frameIndicesStr += ' '.join([str(frameIndex) for frameIndex in frameIndicesForSingleVolume]) + "\n"
    return frameIndicesStr

  @staticmethod
  def frameIndicesFromText(frameIndicesText):
    import re
    frameIndices = []
    for frameIndicesForSingleVolumeStr in frameIndicesText.split('\n'):
      if not frameIndicesForSingleVolumeStr:
        continue
      frameIndices.append([int(frameIndexStr) for frameIndexStr in re.split(' +', frameIndicesForSingleVolumeStr)])
    return frameIndices

  @staticmethod
  def reconstructVolume(sequenceNode, roiNode, outputSpacing):
    # Create sequence browser node
    sequenceBrowserNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSequenceBrowserNode', 'TempReconstructionVolumeBrowser')
    sequenceBrowserNode.AddSynchronizedSequenceNode(sequenceNode)
    slicer.modules.sequences.logic().UpdateAllProxyNodes()  # ensure that proxy node is created
    # Reconstruct
    volumeReconstructionNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVolumeReconstructionNode")
    if not volumeReconstructionNode:
      raise ValueError("Volume reconstruction requires SlicerIGSIO extension. Please install SlicerIGSIO extension using the Extensions Manager.")
    volumeReconstructionNode.SetOutputSpacing(outputSpacing, outputSpacing, outputSpacing)
    volumeReconstructionNode.SetAndObserveInputSequenceBrowserNode(sequenceBrowserNode)
    proxyNode = sequenceBrowserNode.GetProxyNode(sequenceNode)
    volumeReconstructionNode.SetAndObserveInputVolumeNode(proxyNode)
    volumeReconstructionNode.SetAndObserveInputROINode(roiNode)
    volumeReconstructionNode.SetFillHoles(True)
    slicer.modules.volumereconstruction.logic().ReconstructVolumeFromSequence(volumeReconstructionNode)
    reconstructedVolume = volumeReconstructionNode.GetOutputVolumeNode()
    # Cleanup
    slicer.mrmlScene.RemoveNode(volumeReconstructionNode)
    slicer.mrmlScene.RemoveNode(sequenceBrowserNode)
    slicer.mrmlScene.RemoveNode(proxyNode)
    return reconstructedVolume

  @staticmethod
  def getFrameIndices(inputVolumeSequenceNode):
    lastTriggerTime = None
    outputVolumeIndex = 0
    triggerTimes = []
    triggerTimesLastVolume = []
    for inputVolumeIndex in range(inputVolumeSequenceNode.GetNumberOfDataNodes()):
      volumeNode = inputVolumeSequenceNode.GetNthDataNode(inputVolumeIndex)
      if not volumeNode.IsA("vtkMRMLScalarVolumeNode"):
        raise ValueError("Input sequence must contain scalar volume nodes")
      triggerTimeStr = volumeNode.GetAttribute("DICOM.triggerTime")
      if not triggerTimeStr:
        raise ValueError("Trigger Time DICOM tag is not found in the input sequence")
      triggerTime = float(triggerTimeStr)
      if lastTriggerTime is None or triggerTime < lastTriggerTime:
        # trigger time wrapped around
        outputVolumeIndex = 0
      if len(triggerTimes) <= outputVolumeIndex:
        triggerTimes.append([])
      triggerTimes[outputVolumeIndex].append(inputVolumeIndex)
      outputVolumeIndex += 1
      lastTriggerTime = triggerTime
    return triggerTimes

  def reconstructVolumeSequence(self, inputVolumeSequenceNode, roiNode, reconstructedVolumeSeqNode, frameIndices=None, outputSpacing=1.0, showResult=True):
    """
    Reconstruct 4D volume sequence from a list of frames.
    :param inputSequenceNode: input sequence of frames
    :param inputRoiNode: region of interest to reconstruct the volume in
    :param outputSequenceNode: output volume sequence
    :param frameIndices: list that contain list of input sequence indices for each output volume
    :param outputSpacing: resolution of the output volume, smaller value means finer details and slower reconstruction
    :param showResult: show output volume in slice viewers
    """

    if not inputVolumeSequenceNode or not roiNode:
      raise ValueError("Input sequence or ROI is invalid")
    if reconstructedVolumeSeqNode == inputVolumeSequenceNode:
      raise ValueError("Output sequence must not be the same as the input sequence")

    import time
    startTime = time.time()
    logging.info('Processing started')

    # Set inputs
    inputVolumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForSequenceNode(inputVolumeSequenceNode)

    # This will store the reconstructed 4D volume
    if reconstructedVolumeSeqNode:
      reconstructedVolumeSeqNode.RemoveAllDataNodes()
    else:
      reconstructedVolumeSeqNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSequenceNode', inputVolumeSequenceNode.GetName()+' reconstructed')
      reconstructedVolumeSeqNode.SetIndexName("frame")
      reconstructedVolumeSeqNode.SetIndexUnit("")
      reconstructedVolumeSeqNode.SetIndexType(reconstructedVolumeSeqNode.NumericIndex)

    for reconstructedVolumeIndex, frameIndicesInSingleVolume in enumerate(frameIndices):
      if self.progressCallback:
        self.progressCallback(int(100.0 * reconstructedVolumeIndex / len(frameIndices)))
      print(f"Reconstructing start instance number {frameIndicesInSingleVolume[0]}")
      slicer.app.processEvents()
      # Create a temporary sequence that contains all instances belonging to the same time point
      singleReconstructedVolumeSeqNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSequenceNode', 'TempReconstructedVolumeSeq')
      for outputFrameIndex, frameIndex in enumerate(frameIndicesInSingleVolume):
        singleReconstructedVolumeSeqNode.SetDataNodeAtValue(
          inputVolumeSequenceNode.GetNthDataNode(frameIndex), str(outputFrameIndex))
      # Save reconstructed volume into a sequence
      reconstructedVolume = Reconstruct4DCineMRILogic.reconstructVolume(singleReconstructedVolumeSeqNode, roiNode, outputSpacing)
      reconstructedVolumeSeqNode.SetDataNodeAtValue(reconstructedVolume, str(reconstructedVolumeIndex))
      slicer.mrmlScene.RemoveNode(reconstructedVolume)
      slicer.mrmlScene.RemoveNode(singleReconstructedVolumeSeqNode)

    if showResult:
      # Create a sequence browser node for the reconstructed volume sequence
      reconstructedVolumeBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(reconstructedVolume)
      if not reconstructedVolumeBrowserNode:
        reconstructedVolumeBrowserNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSequenceBrowserNode', inputVolumeSequenceNode.GetName() + ' reconstructed browser')
        reconstructedVolumeBrowserNode.AddSynchronizedSequenceNode(reconstructedVolumeSeqNode)
      slicer.modules.sequences.logic().UpdateAllProxyNodes()  # ensure that proxy node is created
      reconstructedVolumeProxyNode = reconstructedVolumeBrowserNode.GetProxyNode(reconstructedVolumeSeqNode)
      slicer.util.setSliceViewerLayers(background=reconstructedVolumeProxyNode)
      slicer.modules.sequences.showSequenceBrowser(reconstructedVolumeBrowserNode)

    stopTime = time.time()
    logging.info(f'Processing completed in {stopTime-startTime:.2f} seconds')

    return reconstructedVolumeSeqNode


#
# Reconstruct4DCineMRITest
#

class Reconstruct4DCineMRITest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear()

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_Reconstruct4DCineMRI1()

  def test_Reconstruct4DCineMRI1(self):
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

    # Get/create input data

    import SampleData
    registerSampleData()
    inputVolume = SampleData.downloadSample('Reconstruct4DCineMRI1')
    self.delayDisplay('Loaded test data set')

    inputScalarRange = inputVolume.GetImageData().GetScalarRange()
    self.assertEqual(inputScalarRange[0], 0)
    self.assertEqual(inputScalarRange[1], 695)

    outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
    threshold = 100

    # Test the module logic

    logic = Reconstruct4DCineMRILogic()

    # Test algorithm with non-inverted threshold
    logic.process(inputVolume, outputVolume, threshold, True)
    outputScalarRange = outputVolume.GetImageData().GetScalarRange()
    self.assertEqual(outputScalarRange[0], inputScalarRange[0])
    self.assertEqual(outputScalarRange[1], threshold)

    # Test algorithm with inverted threshold
    logic.process(inputVolume, outputVolume, threshold, False)
    outputScalarRange = outputVolume.GetImageData().GetScalarRange()
    self.assertEqual(outputScalarRange[0], inputScalarRange[0])
    self.assertEqual(outputScalarRange[1], inputScalarRange[1])

    self.delayDisplay('Test passed')
