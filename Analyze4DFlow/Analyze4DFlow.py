import logging
import os
from typing import Annotated, Optional

import vtk

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    Default,
    SingleStep,
    WithinRange
)

from slicer import vtkMRMLScalarVolumeNode
from slicer import vtkMRMLTransformNode
from slicer import vtkMRMLMarkupsPlaneNode
from slicer import vtkMRMLModelNode
from slicer import vtkMRMLSegmentationNode
from slicer import vtkMRMLTableNode

#
# Analyze4DFlow
#

class Analyze4DFlow(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Analyze 4D Flow"
        self.parent.categories = ["Cardiac"]
        self.parent.dependencies = []
        self.parent.contributors = ["Andras Lasso (PerkLab)"]
        self.parent.helpText = """
Analyze 4D flow fields.

See more information in <a href="https://github.com/JolleyLab/SlicerHeartPrivate#analyze-4d-flow">module documentation</a>.
"""
        self.parent.acknowledgementText = """
This file was originally developed by Andras Lasso (PerkLab, Queen's University).
"""


#
# Analyze4DFlowParameterNode
#

@parameterNodeWrapper
class Analyze4DFlowParameterNode:
    """
    The parameters needed by module.
    """
    inputFlowField: vtkMRMLTransformNode
    inputPlane: vtkMRMLMarkupsPlaneNode
    inputMaskSegmentation: vtkMRMLSegmentationNode
    inputMaskSegmentID: str
    outputStreamlinesModel: vtkMRMLModelNode
    outputSpeedProfileModel: vtkMRMLModelNode
    outputSpeedProfileTable: vtkMRMLTableNode
    outputSpeedVolume: vtkMRMLScalarVolumeNode
    samplingDistance: Annotated[float, WithinRange(0.01, 10)] = 2  # distance unit
    speedThreshold: Annotated[float, WithinRange(0.0, 3), SingleStep(0.01), Default(0.1)]  # m/sec
    streamlinesMaximumLength: Annotated[float, WithinRange(10, 300)] = 200  # distance unit
    streamlinesBidirectional: bool = True
    streamlinesComputeAllMetrics: bool = False
    speedVolumeProjectedToPlane: bool = False  # if True then signed speed vector is projected to the measurement plane normal

#
# Analyze4DFlowWidget
#

class Analyze4DFlowWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None) -> None:
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)  # needed for parameter node observation
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None
        self._updatingGUIFromParameterNode = False
        # Dict that maps from {StudyInstanceUID}/{AcquisitionNumber} to volumesNodeSet.
        # volumeNodeSet contains:
        #   - 'name': displayable name of the node set
        #   - 'componentVolumeNodes': list of 3 volume nodes (R, A, S component)
        #   - 'componentVolumeNodesScaleToCmPerSec': list of 3 scaling factors to convert raw values to speed in cm/sec and RAS direction
        #   - 'magnitudeVolumeNode' magnitude volume node
        self._volumeNodesSets = {}

    def setup(self) -> None:
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.setup(self)

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath('UI/Analyze4DFlow.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.ui.inputFlowFieldSelector.noneDisplay = "Select flow field"
        self.ui.inputFlowFieldSelector.setNodeTypeLabel ("Flow Field", "vtkMRMLTransformNode")
        self.ui.inputFlowFieldSelector.noneEnabled = False
        self.ui.inputFlowFieldSelector.addAttribute("vtkMRMLTransformNode", "SlicerHeart.Type", "FlowField")

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = Analyze4DFlowLogic()
        self.logic.logCallback = self.addLog

        # Connections

        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        # Buttons
        self.ui.inputMaskSegmentSelectorWidget.connect('currentNodeChanged(bool)', self.updateParameterNodeFromGUI)
        self.ui.inputMaskSegmentSelectorWidget.connect('currentSegmentChanged(QString)', self.updateParameterNodeFromGUI)
        self.ui.analyzeButton.connect('clicked(bool)', self.onAnalyzeButton)
        self.ui.showPlotButton.connect('clicked(bool)', self.onShowPlotButton)

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()

    def cleanup(self) -> None:
        """
        Called when the application closes and the module widget is destroyed.
        """
        self.removeObservers()

    def enter(self) -> None:
        """
        Called each time the user opens this module.
        """
        # Make sure parameter node exists and observed
        self.initializeParameterNode()

        #ttt
        #if self._parameterNode and not self._parameterNode.inputFlowField:
        #    ttt slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLTransformNode")


    def exit(self) -> None:
        """
        Called each time the user opens a different module.
        """
        # Do not react to parameter node changes (GUI will be updated when the user enters into the module)
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self._parameterNodeGuiTag = None
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    def addLog(self, text):
        """Display log message
        """
        slicer.util.showStatusMessage(text, 3000)
        slicer.app.processEvents()  # force update

    def onSceneStartClose(self, caller, event) -> None:
        """
        Called just before the scene is closed.
        """
        # Parameter node will be reset, do not use it anymore
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        """
        Called just after the scene is closed.
        """
        # If this module is shown while the scene is closed then recreate a new parameter node immediately
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        """
        Ensure parameter node exists and observed.
        """
        # Parameter node stores all user choices in parameter values, node selections, etc.
        # so that when the scene is saved and reloaded, these settings are restored.

        self.setParameterNode(self.logic.getParameterNode())

    def setParameterNode(self, inputParameterNode: Optional[Analyze4DFlowParameterNode]) -> None:
        """
        Set and observe parameter node.
        Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
        """

        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        self._parameterNode = inputParameterNode
        if self._parameterNode:
            # Note: in the .ui file, a Qt dynamic property called "SlicerParameterName" is set on each
            # ui element that needs connection.
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
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

        self.ui.inputMaskSegmentSelectorWidget.setCurrentNode(self._parameterNode.inputMaskSegmentation)
        self.ui.inputMaskSegmentSelectorWidget.setCurrentSegmentID(self._parameterNode.inputMaskSegmentID)

        # All the GUI updates are done
        self._updatingGUIFromParameterNode = False


    def updateParameterNodeFromGUI(self, caller=None, event=None):
        """
        This method is called when the user makes any change in the GUI.
        The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
        """

        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return

        # Modify all properties in a single batch
        with slicer.util.NodeModify(self._parameterNode):
            #self._parameterNode.ComponentToExtract = self.ui.componentsSpinBox.value
            self._parameterNode.inputMaskSegmentation = self.ui.inputMaskSegmentSelectorWidget.currentNode()
            self._parameterNode.inputMaskSegmentID = self.ui.inputMaskSegmentSelectorWidget.currentSegmentID()


    def onAnalyzeButton(self) -> None:
        """
        Run processing when user clicks "Analyze" button.
        """
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):

            self.addLog("Analyze flow field...")
            self.logic.sampleFlowFieldWithPlane(
                self._parameterNode.inputPlane,
                self._parameterNode.inputFlowField,
                self._parameterNode.inputFlowField.GetNodeReference("magnitudeVolume"),
                self._parameterNode.samplingDistance,
                self._parameterNode.outputStreamlinesModel,
                self._parameterNode.outputSpeedProfileModel,
                self._parameterNode.inputMaskSegmentation,
                self._parameterNode.inputMaskSegmentID,
                self._parameterNode.streamlinesMaximumLength,
                self._parameterNode.streamlinesBidirectional,
                self._parameterNode.streamlinesComputeAllMetrics,
                self._parameterNode.speedThreshold,
                self._parameterNode.outputSpeedVolume,
                self._parameterNode.speedVolumeProjectedToPlane)

            if self._parameterNode.outputSpeedProfileTable:
                self.addLog("Compute speed profile table...")
                self.logic.computeSpeedProfileTable(
                    self._parameterNode.outputSpeedProfileModel,
                    self._parameterNode.speedThreshold,
                    self._parameterNode.outputSpeedProfileTable)

    def onShowPlotButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to create plot."):
            self.logic.createPlotFromTable(self._parameterNode.outputSpeedProfileTable)

#
# Analyze4DFlowLogic
#

class Analyze4DFlowLogic(ScriptedLoadableModuleLogic):
    """This class should implement all the actual
    computation done by your module.  The interface
    should be such that other python code can import
    this class and make use of the functionality without
    requiring an instance of the Widget.
    Uses ScriptedLoadableModuleLogic base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self) -> None:
        """
        Called when the logic class is instantiated. Can be used for initializing member variables.
        """
        ScriptedLoadableModuleLogic.__init__(self)

        self.logCallback = None

        # raw magnitude image intensity threshold
        # (speed values below this threshold are set to zero in the flow field to reduce clutter during visualization)
        self.magnitudeThreshold = 60

        self.dopplerLutRange = [-2, 2]
        self.dopplerLutThreshold = [-0.25, 0.25]

    def log(self, text):
        logging.info(text)
        if self.logCallback:
            self.logCallback(text)

    def getParameterNode(self):
        return Analyze4DFlowParameterNode(super().getParameterNode())

    def _addNodeToSequenceBrowser(self, node, sequenceBrowserNode):
        # Make sure output models are in the same sequence browser as the transform sequence and
        # model is in not a proxy node of any other sequence browsers
        foundBrowserNodes = vtk.vtkCollection()
        sequencesLogic = slicer.modules.sequences.logic()
        sequencesLogic.GetBrowserNodesForProxyNode(node, foundBrowserNodes)

        sequenceNode = None
        for i in range(foundBrowserNodes.GetNumberOfItems()):
            foundBrowserNode = foundBrowserNodes.GetItemAsObject(i)
            foundSequenceNode = sequenceBrowserNode.GetSequenceNode(node)
            if foundBrowserNode == sequenceBrowserNode:
                # Store the sequence node corresponding to the transform sequence browser node
                sequenceNode = foundSequenceNode
            else:
                # Remove model from other sequence browser nodes
                foundBrowserNode.RemoveSynchronizedSequenceNode(foundSequenceNode.GetID())

        if not sequenceNode:
            masterSequenceNode = sequenceBrowserNode.GetMasterSequenceNode()
            sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", node.GetName() + " Sequence")
            sequenceNode.SetIndexType(masterSequenceNode.GetIndexType())
            sequenceNode.SetIndexName(masterSequenceNode.GetIndexName())
            sequenceNode.SetIndexUnit(masterSequenceNode.GetIndexUnit())
            slicer.modules.sequences.logic().AddSynchronizedNode(sequenceNode, node, sequenceBrowserNode)
            sequenceBrowserNode.SetSaveChanges(sequenceNode, True)

    def sampleFlowFieldWithPlane(
            self,
            crossSectionPlaneNode: vtkMRMLMarkupsPlaneNode,
            gridTransformNode: vtkMRMLTransformNode,
            magnitudeVolumeNode: vtkMRMLScalarVolumeNode,
            samplingDistanceMm: float = 2.0,
            outputStreamlinesModel: vtkMRMLModelNode = None,
            outputSpeedProfileModel: vtkMRMLModelNode = None,
            maskSegmentationNode: vtkMRMLSegmentationNode = None,
            maskSegmentID: str = None,
            streamlinesMaximumLengthMm: int = 100,
            streamlinesBidirectional: bool = True,
            streamlinesComputeAllMetrics: bool = False,
            streamlinesSpeedThresholdMPerSec: float = 0.01,
            outputSpeedVolume: vtkMRMLScalarVolumeNode = None,
            speedVolumeProjectedToPlane: bool = False) -> vtkMRMLModelNode:

        import numpy as np

        if not crossSectionPlaneNode:
            raise ValueError("Measurement plane node is invalid")

        transformSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(gridTransformNode)
        if not transformSequenceBrowserNode:
            raise RuntimeError("Input transform is not in a sequence")

        # Temporary nodes
        displacementImageNode = None
        maskLabelmapNode = None
        probeVolumeCliNode = None

        try:

            # Turn off transform visibility to speed up browsing
            if gridTransformNode.GetDisplayNode():
                originalTransformVisibility = gridTransformNode.GetDisplayNode().GetVisibility()
                gridTransformNode.GetDisplayNode().SetVisibility(False)
            else:
                originalTransformVisibility = False

            originalItemNumber = transformSequenceBrowserNode.GetSelectedItemNumber()
            numberOfItems = transformSequenceBrowserNode.GetNumberOfItems()
            deleteOutputSpeedProfileModel = False
            for itemNumber in range(numberOfItems):
                self.log("Sampling flow field with plane... ({item}/{count})".format(item=itemNumber+1, count=numberOfItems))

                transformSequenceBrowserNode.SetSelectedItemNumber(itemNumber)

                # Create sampling plane
                planeBoundsMm = crossSectionPlaneNode.GetPlaneBounds()
                import math
                # Floor towards zero to get number of grid points within the plane's boundary
                planeBoundsGrid = [math.floor(boundMm/samplingDistanceMm) if boundMm >= 0 else math.ceil(boundMm/samplingDistanceMm) for boundMm in planeBoundsMm]
                samplingGrid_Object = vtk.vtkPlaneSource()
                # Resolution: how many part the plane is divided into (2 means 1 dividing line in the middle)
                samplingGrid_Object.SetXResolution(abs(planeBoundsGrid[1]-planeBoundsGrid[0]))
                samplingGrid_Object.SetYResolution(abs(planeBoundsGrid[3]-planeBoundsGrid[2]))
                samplingGrid_Object.SetOrigin(planeBoundsGrid[0] * samplingDistanceMm, planeBoundsGrid[2] * samplingDistanceMm, 0)
                samplingGrid_Object.SetPoint1(planeBoundsGrid[1] * samplingDistanceMm, planeBoundsGrid[2] * samplingDistanceMm, 0)
                samplingGrid_Object.SetPoint2(planeBoundsGrid[0] * samplingDistanceMm, planeBoundsGrid[3] * samplingDistanceMm, 0)

                # Transform plane to world coordinate system
                objectToWorldMatrix = vtk.vtkMatrix4x4()
                crossSectionPlaneNode.GetObjectToWorldMatrix(objectToWorldMatrix)
                objectToWorldTransform = vtk.vtkTransform()
                objectToWorldTransform.SetMatrix(objectToWorldMatrix)
                objectToWorldTransformFilter = vtk.vtkTransformPolyDataFilter()
                objectToWorldTransformFilter.SetTransform(objectToWorldTransform)
                objectToWorldTransformFilter.SetInputConnection(samplingGrid_Object.GetOutputPort())

                # Save model to plane
                modelsLogic = slicer.modules.models.logic()
                if not outputSpeedProfileModel:
                    # Create model node for the output speed profile, if not provided then we create a temporary one
                    outputSpeedProfileModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "__tmp__Speed Profile")
                    deleteOutputSpeedProfileModel = True
                if not outputSpeedProfileModel.GetDisplayNode():
                    # Initialize model display node
                    outputSpeedProfileModel.CreateDefaultDisplayNodes()
                    displayNode = outputSpeedProfileModel.GetDisplayNode()
                    displayNode.SetColor(1, 1, 0)
                    displayNode.SetEdgeVisibility(True)
                    displayNode.BackfaceCullingOff()
                    displayNode.LightingOff()  # don't make the grid darker if it is rotated

                # Add the output nodes to the same sequence browser as the input 4D flow field
                resultProxyNodes = [outputStreamlinesModel, outputSpeedVolume]
                if not deleteOutputSpeedProfileModel:
                    # only create sequence and proxy node if the speed profile model is not temporary
                    resultProxyNodes.append(outputSpeedProfileModel)
                for node in resultProxyNodes:
                    if not node:
                        continue
                    self._addNodeToSequenceBrowser(node, transformSequenceBrowserNode)

                objectToWorldTransformFilter.Update()
                outputSpeedProfileModel.SetAndObservePolyData(objectToWorldTransformFilter.GetOutput())

                # Sample displacement field with the model
                displacementImageNode = slicer.modules.transforms.logic().CreateDisplacementVolumeFromTransform(
                    gridTransformNode, magnitudeVolumeNode, False, slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode"))

                parameters = {}

                if maskSegmentationNode and maskSegmentID:
                    # Export mask segment to labelmap node
                    maskLabelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                    slicer.vtkSlicerSegmentationsModuleLogic.ExportSegmentsToLabelmapNode(maskSegmentationNode, [maskSegmentID], maskLabelmapNode, displacementImageNode)
                    slicer.mrmlScene.RemoveNode(maskLabelmapNode.GetDisplayNode().GetColorNode())

                    # Probe mask image with model
                    parameters["InputVolume"] = maskLabelmapNode
                    parameters["InputModel"] = outputSpeedProfileModel
                    parameters["OutputModel"] = outputSpeedProfileModel
                    parameters["OutputArrayName"] = "insideMask"
                    probeVolumeWithModel = slicer.modules.probevolumewithmodel
                    probeVolumeCliNode = slicer.cli.runSync(probeVolumeWithModel, probeVolumeCliNode, parameters)
                    if probeVolumeCliNode.GetStatus() & probeVolumeCliNode.ErrorsMask:
                        # error
                        errorText = probeVolumeCliNode.GetErrorText()
                        raise ValueError("Probe 4D field execution failed: " + errorText)

                    # slicer.displacementImageArray = slicer.util.arrayFromVolume(displacementImageNode).copy()
                    # slicer.maskImageArray = slicer.util.arrayFromVolume(maskLabelmapNode).copy()

                    displacementImageArray = slicer.util.arrayFromVolume(displacementImageNode)
                    maskImageArray = slicer.util.arrayFromVolume(maskLabelmapNode)
                    displacementImageArray[maskImageArray==0, :] = 0

                    # Clean up
                    if maskLabelmapNode:
                        slicer.mrmlScene.RemoveNode(maskLabelmapNode)
                        maskLabelmapNode = None

                    # Save mask array
                    insideMaskArray = slicer.util.arrayFromModelPointData(outputSpeedProfileModel, 'insideMask').copy()
                else:
                    insideMaskArray = None

                parameters["InputVolume"] = displacementImageNode
                parameters["InputModel"] = outputSpeedProfileModel
                parameters["OutputModel"] = outputSpeedProfileModel
                parameters["OutputArrayName"] = "Speed"
                probeVolumeWithModel = slicer.modules.probevolumewithmodel
                probeVolumeCliNode = slicer.cli.runSync(probeVolumeWithModel, probeVolumeCliNode, parameters)
                if probeVolumeCliNode.GetStatus() & probeVolumeCliNode.ErrorsMask:
                    # error
                    errorText = probeVolumeCliNode.GetErrorText()
                    raise ValueError("Probe 4D field execution failed: " + errorText)

                if insideMaskArray is not None:
                    # Set all displacements outside the mask to zero
                    displacementArray = slicer.util.arrayFromModelPointData(outputSpeedProfileModel, 'Speed')
                    displacementArray[insideMaskArray==0] = (0,0,0)

                # Update streamlines
                if outputStreamlinesModel:
                    speedImageNodeMPerSec = displacementImageNode  # "displacement image" actually stores a speed vector field
                    streamlinesSeedModel = outputSpeedProfileModel  # the plane profile is also used for generating seed points
                    self._createStreamlines(outputStreamlinesModel, speedImageNodeMPerSec, streamlinesSeedModel,
                        streamlinesMaximumLengthMm, streamlinesBidirectional, streamlinesComputeAllMetrics, streamlinesSpeedThresholdMPerSec)
                    if not outputStreamlinesModel.GetDisplayNode() or not outputStreamlinesModel.GetDisplayNode().GetScalarVisibility():
                        # Initialize streamlines model display node
                        outputStreamlinesModel.CreateDefaultDisplayNodes()
                        displayNode = outputStreamlinesModel.GetDisplayNode()
                        displayNode.SetColor(0, 0, 1)
                        displayNode.SetEdgeVisibility(True)
                        displayNode.BackfaceCullingOff()
                        displayNode.LightingOff()  # don't make the lines darker depending on orientation
                        displayNode.SetActiveScalarName('Speed')
                        if gridTransformNode.GetDisplayNode():
                            # Use the same color table and scaling as the transform node
                            displayNode.SetAndObserveColorNodeID(gridTransformNode.GetDisplayNode().GetColorNodeID())
                            displayNode.SetScalarRangeFlag(displayNode.UseColorNodeScalarRange)
                        else:
                            displayNode.SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileViridis.txt")
                        displayNode.ScalarVisibilityOn()

                if outputSpeedVolume:
                    ijkToRAS = vtk.vtkMatrix4x4()
                    displacementImageNode.GetIJKToRASMatrix(ijkToRAS)
                    outputSpeedVolume.SetIJKToRASMatrix(ijkToRAS)
                    displacementImageArray = slicer.util.arrayFromVolume(displacementImageNode)
                    if speedVolumeProjectedToPlane:
                        # Project speed vector to the plane
                        # Get plane normal
                        planeNormal = crossSectionPlaneNode.GetNormal()
                        # Compute dot product of each element of displacementImageArray by planeNormal.
                        # Do not iterate through points one by one because it would be too slow
                        # (use numpy operations instead).
                        speedVolumeArray = np.sum(displacementImageArray * planeNormal, axis=3)
                    else:
                        speedVolumeArray = np.linalg.norm(displacementImageArray, axis=3)
                    slicer.util.updateVolumeFromArray(outputSpeedVolume, speedVolumeArray)

                    if not outputSpeedVolume.GetScalarVolumeDisplayNode():
                        speedVolumeArray.CreateDefaultDisplayNodes()
                    colorNode = outputSpeedVolume.GetScalarVolumeDisplayNode().GetColorNode()
                    # colorMappingType is Speed (for absolute speed) or SpeedComponent (for Doppler-like signed speed)
                    currentColorMappingType = colorNode.GetAttribute("SlicerHeart.ColorMappingType") if colorNode else None
                    requiredColorMappingType = "SpeedComponent" if speedVolumeProjectedToPlane else "Speed"
                    if currentColorMappingType != requiredColorMappingType:
                        # Update color table
                        if currentColorMappingType:
                            # We need to switch to a different color mapping type, but keep reference to this color node
                            outputSpeedVolume.SetNodeReferenceID("SlicerHeart."+currentColorMappingType, colorNode.GetID())
                        colorNode = outputSpeedVolume.GetNodeReference("SlicerHeart." + requiredColorMappingType)
                        if colorNode:
                            # There is a saved color table that we can use
                            colorNodeID = colorNode.GetID()
                        else:
                            # Need to create new color node
                            if speedVolumeProjectedToPlane:
                                colorNodeID = self._createSpeedComponentColorNode().GetID()
                            else:
                                if gridTransformNode.GetDisplayNode():
                                    # Use the same color table and scaling as the transform node
                                    colorNodeID = gridTransformNode.GetDisplayNode().GetColorNodeID()
                                else:
                                    colorNodeID = "vtkMRMLColorTableNodeFileViridis.txt"
                        speedVolumeDisplayNode = outputSpeedVolume.GetScalarVolumeDisplayNode()
                        speedVolumeDisplayNode.SetAndObserveColorNodeID(colorNodeID)

                        # Set default window/level and threshold settings
                        # (it could make sense to not overwrite it once it is set by the user, but for now we always set it to default)
                        if speedVolumeProjectedToPlane:
                            speedVolumeDisplayNode.SetAutoWindowLevel(False)
                            speedVolumeDisplayNode.SetWindowLevelMinMax(*self.dopplerLutRange)
                            speedVolumeDisplayNode.SetApplyThreshold(False)
                        else:
                            # Use the transform color node's range
                            speedVolumeDisplayNode.SetAutoWindowLevel(False)
                            scalarRange = speedVolumeDisplayNode.GetColorNode().GetScalarsToColors().GetRange()
                            speedVolumeDisplayNode.SetWindowLevelMinMax(*scalarRange)
                            speedVolumeDisplayNode.SetApplyThreshold(True)
                            speedVolumeDisplayNode.SetThreshold(streamlinesSpeedThresholdMPerSec, scalarRange[1])


                slicer.mrmlScene.RemoveNode(displacementImageNode)
                displacementImageNode = None

        finally:
            # Clean up
            if probeVolumeCliNode:
                slicer.mrmlScene.RemoveNode(probeVolumeCliNode)
            if displacementImageNode:
                slicer.mrmlScene.RemoveNode(displacementImageNode)
            if maskLabelmapNode:
                slicer.mrmlScene.RemoveNode(maskLabelmapNode)
            transformSequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)
            if originalTransformVisibility and gridTransformNode.GetDisplayNode():
                gridTransformNode.GetDisplayNode().SetVisibility(True)
            if deleteOutputSpeedProfileModel and outputSpeedProfileModel:
                slicer.mrmlScene.RemoveNode(outputSpeedProfileModel.GetDisplayNode())
                slicer.mrmlScene.RemoveNode(outputSpeedProfileModel)
            if outputStreamlinesModel:
                # Hack, it is not clear why this is needed, but without this, streamlines are not always displayed
                displayNode = outputStreamlinesModel.GetDisplayNode()
                displayNode.SetThresholdEnabled(not displayNode.GetThresholdEnabled())
                displayNode.SetThresholdEnabled(not displayNode.GetThresholdEnabled())


    def _getSpeedComponentTransferFunctions(self):
        # Create color and opacity functions for Doppler-like visualization
        lutRange = self.dopplerLutRange
        lutThreshold = self.dopplerLutThreshold

        colorMap = vtk.vtkColorTransferFunction()
        colorMap.AddRGBPoint(lutRange[0],        0/255, 255/255, 255/255)  # cyan
        colorMap.AddRGBPoint(lutRange[0]*0.05,   0/255,   0/255, 255/255)  # blue
        colorMap.AddRGBPoint(                       0,   0/255,   0/255,   0/255)
        colorMap.AddRGBPoint(lutRange[1]*0.05, 255/255,   0/255,   0/255)  # red
        colorMap.AddRGBPoint(lutRange[1],      255/255, 255/255,   0/255)  # yellow

        opacityMap = vtk.vtkPiecewiseFunction()
        transitionWidth = (lutThreshold[1] - lutThreshold[0]) * 0.1
        opacityMap.AddPoint(lutRange[0], 1.0)
        opacityMap.AddPoint(lutThreshold[0], 1.0)
        opacityMap.AddPoint(lutThreshold[0]+transitionWidth, 0.0)
        opacityMap.AddPoint(lutThreshold[1]-transitionWidth, 0.0)
        opacityMap.AddPoint(lutThreshold[1], 1.0)
        opacityMap.AddPoint(lutRange[1], 1.0)

        return colorMap, opacityMap

    def _createSpeedComponentColorNode(self):
        """Create a color node that maps (signed) speed component to color
        for Doppler-like visualization.
        """

        colorMap, opacityMap = self._getSpeedComponentTransferFunctions()

        # Fill lookup table with the color map and opacity
        colorTableSize = 256
        lut = vtk.vtkLookupTable()
        lut.SetNumberOfTableValues(colorTableSize)
        for i in range(colorTableSize):
            x = self.dopplerLutRange[0] + i / (colorTableSize-1) * (self.dopplerLutRange[1] - self.dopplerLutRange[0])
            rgb = colorMap.GetColor(x)
            lut.SetTableValue(i, rgb[0], rgb[1], rgb[2], opacityMap.GetValue(x))
        lut.SetRange(self.dopplerLutRange[0], self.dopplerLutRange[1])

        # Set up color node
        colorNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLColorTableNode")
        colorNode.UnRegister(None)  # to prevent memory leaks
        colorNode.SetName(slicer.mrmlScene.GenerateUniqueName("Speed Component"))
        colorNode.SetAttribute("Category", "Flow")
        colorNode.SetAttribute("SlicerHeart.ColorMappingType", "SpeedComponent")
        colorNode.SetType(slicer.vtkMRMLColorTableNode.User)
        # The color node is a procedural color node, which is saved using a storage node.
        # Hidden nodes are not saved if they use a storage node, therefore
        # the color node must be visible.
        colorNode.SetHideFromEditors(False)
        # Store LUT
        colorNode.SetNumberOfColors(colorTableSize)
        colorNode.SetAndObserveLookupTable(lut)
        # Save in the scene
        slicer.mrmlScene.AddNode(colorNode)

        return colorNode

    def _createStreamlines(self, outputStreamlinesModel, speedImageNodeMPerSec, seedPointsModel, maximumLengthMm, bidirectional, computeAllMetrics, speedThresholdMPerSec):
        import vtkAddon
        import numpy as np

        seedPoints = seedPointsModel.GetPolyData()

        ijkToRAS = vtk.vtkMatrix4x4()
        speedImageNodeMPerSec.GetIJKToRASMatrix(ijkToRAS)

        # Get IJK to RAS matrix scale factors
        spacing = [1, 1, 1]
        for column in range(3):
            spacing[column] = np.linalg.norm([ijkToRAS.GetElement(row, column) for row in range(3)])

        # Canonical: axis directions are IJK, origin is at (0,0,0), spacing is the same as in ijkToRAS
        ijkToCanonical = vtk.vtkMatrix4x4()
        for column in range(3):
            ijkToCanonical.SetElement(column, column, spacing[column])

        # Get IJK to canonical matrix
        rasToIJK = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Invert(ijkToRAS, rasToIJK)
        rasToCanonical = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Multiply4x4(ijkToCanonical, rasToIJK, rasToCanonical)

        # Transform seed points to canonical space
        transformFromRasToCanonicalFilter = vtk.vtkTransformPolyDataFilter()
        transformFromRasToCanonicalFilter.SetInputData(seedPoints)
        transformFromRasToCanonical = vtk.vtkTransform()
        transformFromRasToCanonical.SetMatrix(rasToCanonical)
        transformFromRasToCanonicalFilter.SetTransform(transformFromRasToCanonical)
        transformFromRasToCanonicalFilter.Update()
        seedPointsCanonical = transformFromRasToCanonicalFilter.GetOutput()

        # Define the image in canonical space
        speedImageData = vtk.vtkImageData()
        speedImageData.DeepCopy(speedImageNodeMPerSec.GetImageData())
        speedImageData.SetSpacing(spacing)

        rasToCanonicalDirection = vtk.vtkMatrix3x3()
        vtkAddon.vtkAddonMathUtilities.GetOrientationMatrix(rasToCanonical, rasToCanonicalDirection)
        vtk.vtkImageTransform.TransformVectors(rasToCanonicalDirection, [1,1,1], speedImageData.GetPointData().GetScalars())

        streamLine = vtk.vtkStreamTracer()
        streamLine.SetInputData(speedImageData)
        streamLine.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, vtk.vtkDataSetAttributes.SCALARS)
        streamLine.SetSourceData(seedPointsCanonical)
        streamLine.SetMaximumPropagation(maximumLengthMm)
        streamLine.SetInitialIntegrationStep(0.1)
        if bidirectional:
            streamLine.SetIntegrationDirectionToBoth()
        else:
            streamLine.SetIntegrationDirectionToForward()
        streamLine.SetTerminalSpeed(speedThresholdMPerSec)
        streamLine.Update()

        # Transform results to RAS space
        canonicalToRas = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Invert(rasToCanonical, canonicalToRas)
        transformFromCanonicalToRasFilter = vtk.vtkTransformPolyDataFilter()
        transformFromCanonicalToRasFilter.SetInputData(streamLine.GetOutput())
        transformCanonicalToRas = vtk.vtkTransform()
        transformCanonicalToRas.SetMatrix(canonicalToRas)
        transformFromCanonicalToRasFilter.SetTransform(transformCanonicalToRas)
        transformFromCanonicalToRasFilter.Update()
        streamLinesRas = transformFromCanonicalToRasFilter.GetOutput()
        pointData = streamLinesRas.GetPointData()
        # Rename the input array to "Velocity"
        pointData.GetArray('ImageScalars').SetName('Velocity')

        # Compute the speed (velocity magnitude) for coloring.
        # If the velocity vector was used for coloring then the streamlines would be colored by
        # the first component of the velocity vector, which would not be correct.
        # The "Speed" array should be used for coloring instead.
        acalc = vtk.vtkArrayCalculator()
        acalc.AddVectorArrayName("Velocity")
        acalc.SetResultArrayName("Speed")
        acalc.SetFunction("mag(Velocity)")
        acalc.SetInputData(streamLinesRas)
        acalc.Update()

        polydata = acalc.GetOutput()
        pd = acalc.GetOutput().GetPointData()
        cd = acalc.GetOutput().GetCellData()

        # Remove non-essential arrays
        if not computeAllMetrics:
            pd.RemoveArray('AngularVelocity')
            pd.RemoveArray('Rotation')
            pd.RemoveArray('Vorticity')
            pd.RemoveArray('IntegrationTime')
            pd.RemoveArray('Normals')
            pd.RemoveArray('Velocity')
            cd.RemoveArray('ReasonForTermination')
            cd.RemoveArray('SeedIds')

        # Convert arrays to float to reduce file size
        for i in range(pd.GetNumberOfArrays()):
            dataArray = pd.GetArray(i)
            if dataArray.GetDataType() == vtk.VTK_DOUBLE:
                floatArray = vtk.vtkFloatArray()
                floatArray.DeepCopy(dataArray)
                pd.AddArray(floatArray)

        outputStreamlinesModel.SetAndObservePolyData(polydata)

    def computeSpeedProfileTable(
            self,
            crossSectionModelNode: vtkMRMLMarkupsPlaneNode,
            speedThreshold: float = 0.1,
            outputSpeedProfileTableNode: vtkMRMLTableNode = None) -> vtkMRMLTableNode:

        import numpy as np

        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(crossSectionModelNode)
        sequenceNode = sequenceBrowserNode.GetSequenceNode(crossSectionModelNode)

        timeArray = vtk.vtkDoubleArray()
        timeArray.SetName("time")
        speedArray = vtk.vtkDoubleArray()
        speedArray.SetName("Speed")

        # Turn off transform visibility to speed up browsing
        gridTransformNode = None
        proxyNodes = vtk.vtkCollection()
        sequenceBrowserNode.GetAllProxyNodes(proxyNodes)
        for i in range(proxyNodes.GetNumberOfItems()):
            proxyNode = proxyNodes.GetItemAsObject(i)
            if proxyNode.IsA("vtkMRMLTransformNode"):
                gridTransformNode = proxyNode
                break
        if gridTransformNode and gridTransformNode.GetDisplayNode():
            originalTransformVisibility = gridTransformNode.GetDisplayNode().GetVisibility()
            gridTransformNode.GetDisplayNode().SetVisibility(False)
        else:
            originalTransformVisibility = False

        originalItemNumber = sequenceBrowserNode.GetSelectedItemNumber()
        for itemNumber in range(sequenceBrowserNode.GetNumberOfItems()):
            self.log("Computing speed profile... ({item}/{count})".format(item=itemNumber+1, count=sequenceBrowserNode.GetNumberOfItems()))

            sequenceBrowserNode.SetSelectedItemNumber(itemNumber)
            speed = slicer.util.arrayFromModelPointData(crossSectionModelNode, 'Speed')
            valuesAboveThreshold = speed[speed>speedThreshold]
            if len(valuesAboveThreshold) > 0:
                averageSpeed = valuesAboveThreshold.mean()
            else:
                averageSpeed = np.NaN  # no values above threshold
            # TODO: check unit of threshold and make sure consistent with GUI
            timeArray.InsertNextValue(float(sequenceNode.GetNthIndexValue(itemNumber)))
            speedArray.InsertNextValue(averageSpeed)

        sequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)
        if gridTransformNode and originalTransformVisibility and gridTransformNode.GetDisplayNode():
            gridTransformNode.GetDisplayNode().SetVisibility(True)


        if not outputSpeedProfileTableNode:
            outputSpeedProfileTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")

        outputSpeedProfileTableNode.RemoveAllColumns()
        outputSpeedProfileTable = outputSpeedProfileTableNode.GetTable()

        outputSpeedProfileTable.AddColumn(timeArray)
        outputSpeedProfileTableNode.SetColumnUnitLabel(timeArray.GetName(), "sec")  # TODO: verify if the unit is in sec

        outputSpeedProfileTable.AddColumn(speedArray)
        outputSpeedProfileTableNode.SetColumnDescription(
            speedArray.GetName(),
            f"Average speed in the plane cross-section above threshold {speedThreshold}")
        outputSpeedProfileTableNode.SetColumnUnitLabel(speedArray.GetName(), "m/sec")  # TODO: verify the unit

        return outputSpeedProfileTableNode


    @staticmethod
    def createPlotFromTable(speedProfileTableNode: vtkMRMLTableNode) -> None:

        # Create plot
        plotSeriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", speedProfileTableNode.GetName() + " plot")
        plotSeriesNode.SetAndObserveTableNodeID(speedProfileTableNode.GetID())
        plotSeriesNode.SetXColumnName(speedProfileTableNode.GetTable().GetColumnName(0))  # time
        plotSeriesNode.SetYColumnName(speedProfileTableNode.GetTable().GetColumnName(1))  # speed
        plotSeriesNode.SetPlotType(plotSeriesNode.PlotTypeScatter)
        plotSeriesNode.SetColor(0, 0.6, 1.0)

        # Create chart and add plot
        plotChartNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode")
        plotChartNode.AddAndObservePlotSeriesNodeID(plotSeriesNode.GetID())

        # Show plot in layout
        slicer.modules.plots.logic().ShowChartInLayout(plotChartNode)

#
# 4D MRI phase unwrapping
# The class is based on MIT-licensed code published at:
# https://git.web.rug.nl/p305235/Phase_Unwrapping_Comparison/src/branch/main/python_code/unwrapper.py
# as supplementary material to the paper: https://onlinelibrary.wiley.com/doi/10.1002/mrm.29767
#

{
  "mesh_file": "../data/slice_Hz5.7.h5",
  "dt": 0.030,
  "VENC": 77,
  "shape": "scalar", #only scalar data right now
  "io": {
    "in_file": "../data/slice5.7/GroundTruth_meas/postprocess/SNR6V60/", #path to file to unwrap
    "savepath": "../results/slice5.7/SNR6V60_30ms/", #path to folder where to save results
    "write_checkpoints": False,
    "write_xdmf": True
  },
  "realizations": {
    "apply": True,
    "seed_init": 100,
    "total_number": 50,
    "save_all_errors": True
  },
  "unwrapping": {
    "Temporal": {
      "apply": True,
      "t_ref": 0,
      "path_addon": "temporal/"
    },
    "lap3d": {
      "apply": True,
      "path_addon": "lap3d/"
    },
    "lap4d": {
      "apply": True,
      "path_addon": "lap4d/"
    },
    "Probability": {
      "apply": True,
      "nlow": 10,
      "nhigh": 10,
      "t_low": 0.32,
      "t_high": 0.75,
      "w_s": 1.0,
      "w_t": 2.5,
      "path_addon": "prob/"
    },
    "omme": {
      "apply": True,
      "apply_to_previous": False,
      "high_venc": 126,
      "mid_venc": 38,
      "highvenc_file": "../data/slice5.7/GroundTruth_meas/",
      "midvenc_file": "../data/slice5.7/GroundTruth_meas/postprocess/SNR6V60/",
      "path_addon": "omme/"
    },
    "lee": {
      "apply": False,
      "apply_to_previous": False,
      "highvenc_file": "../data/slice5.7/GroundTruth_meas/",
      "lowvenc_file": "../data/slice5.7/GroundTruth_meas/postprocess/SNR12V60_s100/",
      "path_addon": "lee/"
    }
  },
  "eval": {
    "apply": True,
    "eval_omme": False,
    "ground_file": "../data/slice5.7/GroundTruth_meas/",
    "method": "error",
    "lumen": True,
    "save_errors": True
  },
  "mesh": {
    "mesh_type": "slice",
    "dxs": [0.25, 0.25, 0.25]
  }
}

# # Import modules here
# from __future__ import print_function
# import numpy as np
# import math
# from fenics import *
# from numpy.core.fromnumeric import shape
# from numpy.lib.npyio import save
# import scipy.sparse as sp
# from scipy.sparse import csc_matrix
# from scipy.sparse.linalg import spsolve
# import decimal
# import time

class Unwrapper:
    def __init__(self, options):
        #self.method = options['method']
        self.in_file = options['io']['in_file']
        self.savepath = options['io']['savepath']
        self.save_checkpoints = options['io']['write_checkpoints']
        self.save_xdmf = options['io']['write_xdmf']
        self.venc = options['VENC']
        self.dt = options['dt']
        self.mesh_options = options['mesh']

        #get method-specific parameters from the options

        if 'Temporal' in options['unwrapping']:
            self.t_ref = options['unwrapping']['Temporal']['t_ref']
        #if self.method == 'Probability':
        if 'Probability' in options['unwrapping']:
            self.n_low = options['unwrapping']['Probability']['nlow']
            self.n_high = options['unwrapping']['Probability']['nhigh']
            self.t_low = options['unwrapping']['Probability']['t_low']
            self.t_high = options['unwrapping']['Probability']['t_high']
            self.w_s = options['unwrapping']['Probability']['w_s']
            self.w_t = options['unwrapping']['Probability']['w_t']

        self.path_addons = {}
        for method in options['unwrapping']:
            self.path_addons[method] = options['unwrapping'][method]['path_addon']

        #get mesh from the input file, with  boundaries
        self.mesh = Mesh()
        h5 = HDF5File(self.mesh.mpi_comm(), options['mesh_file'], 'r')
        h5.read(self.mesh, 'mesh', False)
        if h5.has_dataset('boundaries'):
            self.bnds = MeshFunction('size_t', self.mesh, self.mesh.topology().dim()-1)
            h5.read(self.bnds, 'boundaries')

        #assuming we only ever work in one function space
        self.mesh_type = self.mesh_options['mesh_type']
        if self.mesh_type == 'slice':
            self.V = FunctionSpace(self.mesh, 'DG', 0)
        else:
            self.V = FunctionSpace(self.mesh, 'P', 1)

    def set_method(self, new_method):
        self.method = new_method

    def save(self, u_list, filelist, save_checkpoints = False, savepath = False):
        comm = self.mesh.mpi_comm()
        if not savepath:
            savepath = str(self.savepath)
        xdmf_u = XDMFFile(savepath + 'u.xdmf')
        u = Function(self.V)
        u.rename('velocity', 'u')
        for l in range(len(u_list)):
            # writing xdmf
            u.assign(u_list[l])
            xdmf_u.write(u, l*self.dt)
            # writing checkpoint
            if save_checkpoints:
                if filelist:
                    print('saving checkpoint', l)
                    ckpath = filelist[l].replace(self.in_file, savepath)
                    hdf = HDF5File(comm, ckpath, 'w')
                    hdf.write(u, '/u', float(l*self.dt))
                    hdf.close()
                else:
                    print('saving checkpoint', l)
                    ckpath = savepath
                    name = '/u{i}'.format(i = math.ceil(l*self.dt*1000)) + '.h5'
                    hdf = HDF5File(comm, ckpath + name, 'w')
                    hdf.write(u, '/u', float(l*self.dt))
                    hdf.close()

    def make_numpy_box(self, velocity, save_numpy = True, save_box = False):
        '''
        makes numpy array from fenics functions on aorta mesh
        Args (list): velocity input
        Return (list): numpy array
        can also save intermittent fenics function on box mesh
        '''
        #this only works for scalar data for now!
        #find mesh dimensions and stuff
        self.Lt = len(velocity)
        coords = self.mesh.coordinates()
        [x0, x1] = [np.min(coords[:, 0]), np.max(coords[:, 0])]
        [y0, y1] = [np.min(coords[:, 1]), np.max(coords[:, 1])]
        [z0, z1] = [np.min(coords[:, 2]), np.max(coords[:, 2])]
        [dx, dy, dz] = self.mesh_options['dxs']
        [Lx, Ly, Lz] = [math.ceil((x1-x0)/dx), math.ceil((y1-y0)/dy), math.ceil((z1 - z0)/dz)]
        # new spatial coordinates for the box-mesh
        deltax = (dx*(Lx) - (x1 - x0))/2
        deltay = (dy*(Ly) - (y1 - y0))/2
        deltaz = (dz*(Lz) - (z1 - z0))/2
        x0_new = x0 - deltax
        x1_new = x1 + deltax
        y0_new = y0 - deltay
        y1_new = y1 + deltay
        z0_new = z0 - deltaz
        z1_new = z1 + deltaz
        # Defining the box-mesh
        if self.mesh_type == 'aorta':
            boxmesh = BoxMesh(Point(x0_new,y0_new,z0_new),Point(x1_new,y1_new,z1_new),Lx,Ly,Lz)
            Vbox = FunctionSpace(boxmesh, 'P', 1)
            Xt = Vbox.tabulate_dof_coordinates()
        else:
            Xt = self.V.tabulate_dof_coordinates()

        # This array contains indexes instead of coordinates
        SqXt = np.zeros(Xt.shape)
        decimal.getcontext().rounding = decimal.ROUND_HALF_UP
        for k in range(Xt.shape[0]):
            xkprime = round((Xt[k][0] - x0_new)/dx, 2)
            xk = int(decimal.Decimal(xkprime).to_integral_value())
            ykprime = round((Xt[k][1] - y0_new)/dy, 2)
            yk = int(decimal.Decimal(ykprime).to_integral_value())
            zkprime = round((Xt[k][2] - z0_new)/dx, 2)
            zk = int(decimal.Decimal(zkprime).to_integral_value())
            SqXt[k, 0] = int(xk)
            SqXt[k, 1] = int(yk)
            SqXt[k, 2] = int(zk)
        SqXt = SqXt.astype(int)

        u = Function(self.V)
        S = np.zeros((Lx+1, Ly+1, Lz+1, self.Lt))
        t = 0
        velocity_box = {}
        print('interpolating...')
        for t in range(self.Lt):
            u = velocity[t]
            if self.mesh_type == 'aorta':
                ubox = Function(Vbox)
                LagrangeInterpolator.interpolate(ubox, u)
                u2 = Function(Vbox)
                u2.assign(ubox)
                velocity_box[t] = u2
                values = ubox.vector()[:]
            else:
                values = u.vector()[:]

            for k in range(Xt.shape[0]):
                S[SqXt[k, 0], SqXt[k,1], SqXt[k,2], t] = values[k]
            t+=1
        if save_box == True:
            print('saving new meshes')
            xdmf = XDMFFile(self.in_file + 'ubox.xdmf')
            for t in range(self.Lt):
                velocity_box[t].rename('velocity', 'u')
                xdmf.write(velocity_box[t], t*self.dt)
        if save_numpy == True:
            np.save(self.in_file + 'u', S)
        return S

    def make_aorta_mesh(self, S, save_aorta = True, save_box = False):
        '''
        interpolate numpy array into aorta mesh
        Args(numpy array): S input data
        Return (list of fenics functions): same data, in aorta mesh
        can also save an intermittent fenics function on a box mesh
        '''
        #this only works for scalar data for now!
        coords = self.mesh.coordinates()
        [x0, x1] = [np.min(coords[:, 0]), np.max(coords[:, 0])]
        [y0, y1] = [np.min(coords[:, 1]), np.max(coords[:, 1])]
        [z0, z1] = [np.min(coords[:, 2]), np.max(coords[:, 2])]

        [dx, dy, dz] = self.mesh_options['dxs']
        [Lx, Ly, Lz] = [math.ceil((x1-x0)/dx), math.ceil((y1-y0)/dy), math.ceil((z1 - z0)/dz)]
        # new spatial coordinates for the box-mesh
        deltax = (dx*(Lx) - (x1 - x0))/2
        deltay = (dy*(Ly) - (y1 - y0))/2
        deltaz = (dz*(Lz) - (z1 - z0))/2
        x0_new = x0 - deltax
        x1_new = x1 + deltax
        y0_new = y0 - deltay
        y1_new = y1 + deltay
        z0_new = z0 - deltaz
        z1_new = z1 + deltaz
        # Defining the box-mesh
        mesh0 = BoxMesh(Point(x0_new,y0_new,z0_new),Point(x1_new,y1_new,z1_new),Lx,Ly,Lz)
        P1 = FunctionSpace(mesh0, 'P', 1)
        Xt = P1.tabulate_dof_coordinates()

        # This array contains indexes instead of coordinates
        SqXt = np.zeros(Xt.shape)
        decimal.getcontext().rounding = decimal.ROUND_HALF_UP
        for k in range(Xt.shape[0]):
            xkprime = round((Xt[k][0] - x0_new)/dx, 2)
            xk = int(decimal.Decimal(xkprime).to_integral_value())
            ykprime = round((Xt[k][1] - y0_new)/dy, 2)
            yk = int(decimal.Decimal(ykprime).to_integral_value())
            zkprime = round((Xt[k][2] - z0_new)/dx, 2)
            zk = int(decimal.Decimal(zkprime).to_integral_value())
            SqXt[k,0] = int(xk)
            SqXt[k,1] = int(yk)
            SqXt[k,2] = int(zk)

        SqXt = SqXt.astype(int) # To ensure int values!
        v = Function(self.V)
        velocity = [Function(self.V) for i in range(self.Lt)]
        velocity_box = [Function(P1) for i in range(self.Lt)]
        for t in range(self.Lt):
            v1 = Function(P1)
            values = np.zeros(v1.vector()[:].shape)
            for k in range(Xt.shape[0]):
                values[k] = S[SqXt[k, 0], SqXt[k, 1], SqXt[k, 2], t]
            v1.vector()[:] = values
            velocity_box[t] = v1
            v = Function(self.V)
            LagrangeInterpolator.interpolate(v, v1)
            if self.mesh_type == 'slice':
                #due to problems with interpolating into hexahedral meshes (it interpolates with fake zeros somehow?)
                #this multiplication is necessary for the slices
                v.vector()[:] *= 2
            velocity[t] = v
        if save_aorta == True:
            self.save(velocity, False, False, savepath=self.savepath + 'aorta/')
        if save_box == True:
            self.save(velocity_box, False, False, savepath = self.savepath + 'box/')
        return velocity

    def lap_unwrap(self, phiwin, nd = 3):
        '''
        Args (numpy array): wrapped phase
        Return (numpy array): unwrapped phase
        '''
        si = [phiwin.shape[0], phiwin.shape[1], phiwin.shape[2], phiwin.shape[3]]
        phiw = phiwin
        if self.mesh_type == 'slice':
            if nd == 3:
                [X, Y] = np.mgrid[-si[0]/2:si[0]/2, -si[1]/2:si[1]/2]
                ss = 4
                mod = 2*np.cos(pi*X/si[0]) + 2*np.cos(pi*Y/si[1]) - 4
                modi = 2*np.cos(pi*X/si[0]) + 2*np.cos(pi*Y/si[1]) - 4
                modi[math.floor(si[0]/2), math.floor(si[1]/2)] = 1
            else:
                [X, Y, T] = np.mgrid[-si[0]/2:si[0]/2, -si[1]/2:si[1]/2, -si[3]/2:si[3]/2]
                ss = 4
                ts = 2
                mod = 2*np.cos(pi*X/si[0]) + 2*np.cos(pi*Y/si[1]) + ts*np.cos(pi*T/si[3]) - ss - ts
                modi = 2*np.cos(pi*X/si[0]) + 2*np.cos(pi*Y/si[1]) + ts*np.cos(pi*T/si[3]) - ss - ts
                modi[math.floor(si[0]/2), math.floor(si[1]/2), math.floor(si[3]/2)] = 1
            phiw = phiwin[:, :, 1, :]
            si = [si[0], si[1], si[3]]
            def lap(phi):
                '''computes laplacian with priorly defined stencil'''
                K = np.fft.fftshift(np.fft.fftn(np.fft.ifftshift(phi)))
                K = np.multiply(K, mod)
                return np.real(np.fft.fftshift(np.fft.ifftn(np.fft.ifftshift(K))))
            def ilap(phi):
                K = np.fft.fftshift(np.fft.fftn(np.fft.ifftshift(phi)))
                K = K / modi
                return np.real(np.fft.fftshift(np.fft.ifftn(np.fft.ifftshift(K))))
            lap_phiw = np.zeros(si)
            lap_phi_vec = np.zeros(si)
            phi_vec = np.zeros(si)
            nr = np.zeros(si)
            if nd == 3:
                for t in range(self.Lt):
                    #compute Laplacian of the correct phase
                    lap_phi_vec[:,:,t] = np.cos(phiw[:,:,t])*lap(np.sin(phiw[:,:,t])) - np.sin(phiw[:,:,t])*lap(np.cos(phiw[:,:,t]))
                    lap_phiw[:, :, t] = lap(phiw[:, :, t])
                    phi_vec[:, :, t] = ilap(lap_phi_vec[:, :, t] - lap_phiw[:, :, t])
            if nd == 4:
                lap_phiw = lap(phiw)
                lap_phi_vec = np.cos(phiw)*lap(np.sin(phiw)) - np.sin(phiw)*lap(np.cos(phiw))
                phi_vec = ilap(lap_phi_vec - lap_phiw)
            nr = np.round(phi_vec/(2*pi))
            nrout = np.zeros(phiwin.shape)
            nrout[:, :, 1, :] = nr
            print(np.count_nonzero(nr))
            u = self.make_aorta_mesh((phiwin + 2*pi*nrout)*self.venc/pi, False, False)
            return u
        if nd <=3:
            [X, Y, Z] = np.mgrid[-si[0]/2:si[0]/2, -si[1]/2:si[1]/2, -si[2]/2:si[2]/2]
            ss = 6
            mod = 2*np.cos(pi*X/si[0]) + 2*np.cos(pi*Y/si[1]) - ss + 2*np.cos(pi*Z/si[2])
            modi = 2*np.cos(pi*X/si[0]) + 2*np.cos(pi*Y/si[1]) - ss + 2*np.cos(pi*Z/si[2])
            modi[math.floor(si[0]/2), math.floor(si[1]/2), math.floor(si[2]/2)] = 1
            def lap(phi):
                '''computes laplacian with priorly defined stencil'''
                K = np.fft.fftshift(np.fft.fftn(np.fft.ifftshift(phi)))
                K = np.multiply(K, mod)
                return np.real(np.fft.fftshift(np.fft.ifftn(np.fft.ifftshift(K))))
            def ilap(phi):
                K = np.fft.fftshift(np.fft.fftn(np.fft.ifftshift(phi)))
                K = K / modi
                return np.real(np.fft.fftshift(np.fft.ifftn(np.fft.ifftshift(K))))
            lap_phiw = np.zeros(si)
            lap_phi_vec = np.zeros(si)
            phi_vec = np.zeros(si)
            nr = np.zeros(si)
            for t in range(self.Lt):
                #compute Laplacian of the correct phase
                lap_phi_vec[:,:,:,t] = np.cos(phiw[:,:,:,t])*lap(np.sin(phiw[:,:,:,t])) - np.sin(phiw[:,:,:,t])*lap(np.cos(phiw[:,:,:,t]))
                lap_phiw[:, :, :, t] = lap(phiw[:, :, :, t])
                phi_vec[:, :, :, t] = ilap(lap_phi_vec[:, :, :, t] - lap_phiw[:, :, :, t])
            nr = np.round(phi_vec/(2*pi))
            nrout = np.zeros(phiwin.shape)
            nrout = nr
            print(np.count_nonzero(nr))
            if nd == 3:
                u = self.make_aorta_mesh((phiwin + 2*pi*nrout)*self.venc/pi, False, False)
                return u
            else:
                #define boundary conditions
                if self.mesh_type == 'slice':
                    lap_phi_out = np.zeros(phiwin.shape)
                    lap_phi_out[:,:,1,:] = lap_phi_vec[:,:,0,:]
                    lap_phiw_out = np.zeros(phiwin.shape)
                    lap_phiw_out[:,:,1,:] = lap_phiw[:,:,0,:]
                else:
                    lap_phi_out = lap_phi_vec
                    lap_phiw_out = lap_phiw
                lap_phi = self.make_aorta_mesh(lap_phi_out, False, False)
                phi_w= self.make_aorta_mesh(phiwin, False, False)
                lap_phi_w = self.make_aorta_mesh(lap_phiw_out, False, False)
                u = [Function(self.V) for i in range(self.Lt)]
                def boundary_D(x, on_boundary):
                    return on_boundary
                for t in range(self.Lt):
                    if self.mesh_type == 'aorta':
                        bc_phi = DirichletBC(self.V, phi_w[t], self.bnds, 1)
                    else:
                        bc_phi = DirichletBC(self.V, phi_w[t], boundary_D)
                    #bc_phi = DirichletBC(self.V, Constant(0.0), self.bnds, 1)
                    ds = Measure("ds", subdomain_data=self.bnds)
                    g_phi = Constant(0.0)
                    phi = TrialFunction(self.V)
                    v = TestFunction(self.V)
                    a = dot(grad(phi), grad(v))*dx
                    #L = (lap_phi[t] - lap_phi_w[t])*v*dx + g_phi*v*ds
                    L = lap_phi[t]*v*dx
                    phi = Function(self.V)
                    solve(a == L, phi, bc_phi)
                    nr = Function(self.V)
                    nr.vector()[:] = np.round((phi.vector()[:])/(2*pi))
                    #u[t].assign(phi_w[t]*self.venc/pi + nr*2*self.venc)
                    u[t].assign(phi*self.venc/pi)
                return u
        if nd == 4:
            [X, Y, Z, T] = np.mgrid[-si[0]/2:si[0]/2, -si[1]/2:si[1]/2, -si[2]/2:si[2]/2, -si[3]/2:si[3]/2]
            ts = 2
            ss = 6
            if self.mesh_type == 'slice':
                ss = 4
            mod = 2*np.cos(pi*X/si[0]) + 2*np.cos(pi*Y/si[1]) + 2*np.cos(pi*Z/si[2]) + ts*np.cos(pi*T/si[3]) - ss - ts
            modi = 2*np.cos(pi*X/si[0]) + 2*np.cos(pi*Y/si[1]) + 2*np.cos(pi*Z/si[2]) + ts*np.cos(pi*T/si[3]) - ss - ts
            modi[math.floor(si[0]/2), math.floor(si[1]/2), math.floor(si[2]/2), math.floor(si[3]/2)] = 1
            def lap(phi):
                '''computes laplacian with priorly defined stencil'''
                K = np.fft.fftshift(np.fft.fftn(np.fft.ifftshift(phi)))
                K = np.multiply(K, mod)
                return np.real(np.fft.fftshift(np.fft.ifftn(np.fft.ifftshift(K))))
            def ilap(phi):
                K = np.fft.fftshift(np.fft.fftn(np.fft.ifftshift(phi)))
                K = K / modi
                return np.real(np.fft.fftshift(np.fft.ifftn(np.fft.ifftshift(K))))
            lap_phiw = lap(phiw)
            lap_phi_vec = np.cos(phiw)*lap(np.sin(phiw)) - np.sin(phiw)*lap(np.cos(phiw))
            phi_vec = ilap(lap_phi_vec - lap_phiw)
            nr = np.round(phi_vec/(2*pi))
            nrout = nr
            print(np.count_nonzero(nr))
            u = self.make_aorta_mesh((phiwin + 2*pi*nrout)*self.venc/pi, False, False)
            return u

    def temporal_unwrap(self, phi_w):
        '''
        unwrapping with the temporal method described in Xiang, 1995
        Args (list): wrapped phase
        Return (list): unwrapped phase
        '''
        def wrap(u):
            ''' wraps all values of u into the interval (-pi, pi)'''
            u_array = u.vector()[:]
            for i, x in enumerate(u_array):
                while x<-pi or x>pi:
                    if x>pi:
                        u_array[i] = x - 2*pi
                        x = x - 2*pi
                    if x<-pi:
                        u_array[i] = x + 2*pi
                        x = x + 2*pi
            u.vector()[:] = u_array
            return u
        phi_diff = [Function(self.V) for i in range(len(phi_w))]
        phi = [Function(self.V) for i in range(len(phi_w))]
        phi[self.t_ref] = phi_w[self.t_ref]
        for t in range(self.t_ref, len(phi_w)-1):
            phi_diff[t].vector()[:] = phi_w[t+1].vector()[:] - phi_w[t].vector()[:]
            phi_diff[t] = wrap(phi_diff[t])
            phi[t+1] = phi[t] + phi_diff[t]
        for t in reversed(range(0, self.t_ref)):
            phi_diff[t].vector()[:] = phi_w[t+1].vector()[:] - phi_w[t].vector()[:]
            phi_diff[t] = wrap(phi_diff[t])
            phi[t] = phi[t+1] - phi_diff[t]
        return phi

    def probability_unwrap(self, phi_w):
        '''
        unwraps with probability-based method described in Loecher et al., 2011
        Args (list): wrapped phase
        Return (list): unwrapped phase
        '''
        timesteps = len(phi_w)
        if self.mesh_type == 'aorta':
            def prob_pass(phi_w, threshold, v_to_d, mesh, neighborhoods, w_s, w_t):
                '''
                performs one single pass over all vertices, estimating probability that they're wrapped and unwrapping if necessary
                '''
                coords = mesh.coordinates()
                prob = [[0]*mesh.num_vertices() for i in range(timesteps+1)]
                phi = phi_w

                for v in vertices(mesh):
                    for t in range(0, timesteps):
                        #sum the gradients of the neighbours
                        grad_sum = 0
                        dofs = v_to_d[v.index()]
                        value = phi_w[t].vector()[dofs]
                        for idx in neighborhoods[v.index()]:
                            grad_sum = grad_sum + w_s * (phi_w[t](coords[idx]) - value)
                        if t>0:
                            grad_sum = grad_sum + w_t*(phi_w[t-1].vector()[dofs] - value)
                        if t < timesteps-1:
                            grad_sum = grad_sum + w_t*(phi_w[t+1].vector()[dofs] - value)
                        #calculate probability
                        tot = max(0.000001, w_s*len(neighborhoods[v.index()]) + w_t*int(t>0) + w_t*int(t<timesteps+1))
                        prob[t][v.index()] = grad_sum/(2*pi*tot)
                        if prob[t][v.index()] > threshold:
                            phi[t].vector()[dofs] = phi_w[t].vector()[dofs] + 2*pi
                        if prob[t][v.index()] < -threshold:
                            phi[t].vector()[dofs] = phi_w[t].vector()[dofs] - 2*pi
                return phi

            #prepare vertex-dof maps
            v_to_d=vertex_to_dof_map(self.V)

            #find all neighborhood vertices
            neighborhoods = [0]*self.mesh.num_vertices()
            for v in vertices(self.mesh):
                neighborhood = [Edge(self.mesh, i).entities(0) for i in v.entities(1)]
                neighborhood = np.array(neighborhood).flatten()
                neighborhood = neighborhood[np.where(neighborhood != v.index())[0]]
                neighborhoods[v.index()] = neighborhood

            #low threshold passes
            phi = prob_pass(phi_w, self.t_low, v_to_d, self.mesh, neighborhoods, self.w_s, self.w_t)
            for i in range(self.n_low-1):
                phi = prob_pass(phi, self.t_low, v_to_d, self.mesh, neighborhoods, self.w_s, self.w_t)
            #high threshold passes
            for i in range(self.n_high):
                phi = prob_pass(phi, self.t_high, v_to_d, self.mesh, neighborhoods, self.w_s, self.w_t)
            return phi
        else:
            phiw = self.make_numpy_box(phi_w, False, False)
            si = phiw.shape
            def prob_pass(phiw, threshold, w_s, w_t):
                phi = np.copy(phiw)
                pw = 0
                for x in range(si[0]):
                    for y in range(si[1]):
                        for z in range(si[2]):
                            for t in range(si[3]):
                                grad_sum = 0
                                val = phiw[x, y, z, t]
                                tot = 0
                                if 0<x:
                                    grad_sum += w_s*(phiw[x-1, y, z, t] - val)
                                    tot +=w_s
                                if x<si[0]-1:
                                    grad_sum += w_s*(phiw[x+1, y, z, t] - val)
                                    tot +=w_s
                                if 0<y:
                                    grad_sum += w_s*(phiw[x, y-1, z, t] - val)
                                    tot +=w_s
                                if y<si[1]-1:
                                    grad_sum += w_s*(phiw[x, y+1, z, t] - val)
                                    tot +=w_s
                                if 0<z:
                                    grad_sum += w_s*(phiw[x, y, z-1, t] - val)
                                    tot +=w_s
                                if z<si[2]-1:
                                    grad_sum += w_s*(phiw[x, y, z+1, t] - val)
                                    tot +=w_s
                                if 0<t:
                                    grad_sum += w_t*(phiw[x, y, z, t-1] - val)
                                    tot +=w_t
                                if t<si[3]-1:
                                    grad_sum += w_t*(phiw[x, y, z, t+1] - val)
                                    tot +=w_t
                                prob = grad_sum /(2*pi*tot)
                                if prob > threshold:
                                    phi[x, y, z, t] = val + 2*pi
                                    pw +=1
                                if prob < -threshold:
                                    phi[x, y, z, t] = val - 2*pi
                                    pw +=1
                print('wrapped pixels: ', pw)
                return phi

            phi = prob_pass(phiw, self.t_low, self.w_s, self.w_t)
            for i in range(self.n_low - 1):
                phi = prob_pass(phi, self.t_low, self.w_s, self.w_t)
            for i in range(self.n_high):
                phi = prob_pass(phi, self.t_high, self.w_s, self.w_t)
            r_phi = self.make_aorta_mesh(phi, False, False)
            return r_phi

    def dual_venc(self, high_venc_files, low_venc_files, addon = False):
        print('unwrapping with dual venc')
        if not addon:
            addon = self.path_addons['lee']
        #read files with low venc
        t = 0
        u = Function(self.V)
        low_venc = [Function(self.V) for i in range(len(low_venc_files))]
        for file in low_venc_files:
            h5u = HDF5File(self.mesh.mpi_comm(), file, 'r')
            h5u.read(u, 'u')
            low_venc[t].assign(u)
            t +=1
        #read files with high venc
        t = 0
        u = Function(self.V)
        high_venc = [Function(self.V) for i in range(len(high_venc_files))]
        for file in high_venc_files:
            if isinstance(file, str):
                h5u = HDF5File(self.mesh.mpi_comm(), file, 'r')
                h5u.read(u, 'u')
                high_venc[t].assign(u)
            else:
                high_venc[t].assign(file)
            t +=1
        self.Lt = len(low_venc_files)
        u = low_venc
        for t in range(self.Lt):
            diff = high_venc[t].vector()[:] - low_venc[t].vector()[:]
            n = np.round(diff/self.venc)
            u[t].vector()[:] += n*self.venc
        if self.save_xdmf:
            self.save(u, False, self.save_checkpoints, self.savepath + addon)
        return u

    def omme(self, velocities, vencs):
        uw = Function(self.V)
        uw_vec = np.zeros(velocities[0].shape)
        #venc_uw = np.lcm.reduce(vencs)
        venc_uw = np.max(vencs)
        min_ind = np.argmin(vencs)
        min_venc = np.min(vencs)
        nb_samples = math.ceil(venc_uw/min_venc)+2
        range_u = np.arange(-nb_samples, nb_samples+1)*min_venc
        u = np.outer(velocities[min_ind][:],np.ones((1, len(range_u)))) + np.outer(np.ones((len(velocities[0][:]), 1)),range_u)
        for k in range(len(velocities[0])):
            J = 0
            u_k = u[k, abs(u[k,:]) <= venc_uw]
            for v_ind in range(len(vencs)):
                J = J - np.cos(np.pi * (velocities[v_ind][k] - u_k)/vencs[v_ind])
            ind_k = np.argmin(J)
            uw_vec[k] = u_k[ind_k]
        uw.vector()[:] = uw_vec
        return uw

    def multi_venc(self, venc_files, vencs, addon = False):
        if not addon:
            addon = self.path_addons['omme']
        self.Lt = len(venc_files[0])
        print('unwrapping with %i vencs'%len(vencs))
        uw = []
        for t in range(self.Lt):
            velocities = []
            for filelist in venc_files:
                if isinstance(filelist[t], str):
                    u = Function(self.V)
                    h5u = HDF5File(self.mesh.mpi_comm(), filelist[t], 'r')
                    h5u.read(u, 'u')
                    velocities.append(u.vector()[:])
                else:
                    velocities.append(filelist[t].vector()[:])
            uw.append(self.omme(velocities, vencs))
        if self.save_xdmf:
            self.save(uw, False, self.save_checkpoints, self.savepath + addon)
        print('done!')
        return uw

    def unwrap(self, filelist, method = 'Temporal'):
        '''
        unwraps the velocity data :)
        Args (list/numpy array): filelist, list of files to unwrap OR one numpy array to unwrap
        Return (list): unwrapped velocity
        '''
        #get files from file list
        if isinstance(filelist, str) and (filelist.endswith('npy') or filelist.endswith('npz')):
            #using numpy array saves with default folder structure, ie all h5 files in one folder
            if filelist.endswith('npy'):
                u_in = np.load(filelist)
            if filelist.endswith('npz'):
                S = np.load(filelist)
                u_in = S['u']
            filelist = False
            self.Lt = u_in.shape[3]
        else:
            t = 0
            u = Function(self.V)
            u_in = [Function(self.V) for i in range(len(filelist))]
            for file in filelist:
                h5u = HDF5File(self.mesh.mpi_comm(), file, 'r')
                h5u.read(u, 'u')
                u_in[t].assign(u)
                t +=1
            self.Lt = len(filelist)
        if self.Lt == 0:
            raise Exception('No input files found!')
        if method.startswith('lap'):
            if type(u_in) == np.ndarray:
                vx = u_in
            else:
                print('transforming to numpy array')
                vx = self.make_numpy_box(u_in, save_numpy = False, save_box = False)
            #transform to phase
            print('unwrapping with laplacian method...')
            start_l = time.time()
            phase = np.asarray(vx * pi / self.venc)
            if method.endswith('3d'):
                u_list = self.lap_unwrap(phase, nd=3)
            if method.endswith('4d'):
                u_list = self.lap_unwrap(phase, nd=4)
            if method.endswith('fenics'):
                u_list = self.lap_unwrap(phase, nd=0)
            end_l = time.time()
            print('done!')
            print('total time for Laplacian: ' + str(end_l - start_l))
        if method == 'Temporal':
            if type(u_in) == np.ndarray:
                print('transforming to aorta mesh')
                u_wrapped = self.make_aorta_mesh(u_in, save_aorta=False, save_box=False)
            else:
                u_wrapped = u_in
            print('unwrapping with temporal method...')
            phi_w = [Function(self.V) for i in range(len(u_wrapped))]
            u_list = [Function(self.V) for i in range(len(u_wrapped))]
            for t, u in enumerate(u_wrapped):
                phi_w[t].assign(u * pi / self.venc)
            phi = self.temporal_unwrap(phi_w)
            for t, phit in enumerate(phi):
                u_list[t].assign(phit * self.venc / pi)
            print('done!')
        if method == 'Probability':
            if type(u_in) == np.ndarray:
                print('transforming to aorta mesh')
                u_wrapped = self.make_aorta_mesh(u_in, save_aorta=False, save_box=False)
            else:
                u_wrapped = u_in
            print('unwrapping with probability method...')
            phi_w = [Function(self.V) for i in range(len(u_wrapped))]
            u_list = [Function(self.V) for i in range(len(u_wrapped))]
            for t, u in enumerate(u_wrapped):
                phi_w[t].assign(u_wrapped[t] * pi/ self.venc)
            phi = self.probability_unwrap(phi_w)
            for t, phit in enumerate(phi):
                u_list[t].assign(phit * self.venc / pi)
            print('done!')
        if self.save_xdmf:
            self.save(u_in, filelist, self.save_checkpoints, self.savepath + 'wrapped/')
            self.save(u_list, filelist, self.save_checkpoints, self.savepath + self.path_addons[method])
        return u_list

    def get_lumen(self, ground_truth):
       #separate only lumen voxels here
        lumen_indxs = []
        for k in range(len(ground_truth[0].vector()[:])):
            for t in range(self.Lt):
                #not-lumen voxels should always be zero in ground truth
                if ground_truth[t].vector()[k] != 0:
                    lumen_indxs.append(k)
                    break
        self.lumen_indxs = lumen_indxs
        return lumen_indxs

    def eval(self, wrapped, ground_truth, method = 'error'):
        lumen_indxs = getattr(self, 'lumen_indxs', range(len(ground_truth[0].vector()[:])))
        if method == 'number':
            n = 0
            for t in range(self.Lt):
                for k in lumen_indxs:
                    if abs(wrapped[t].vector()[k] - ground_truth[t].vector()[k]) > 0.1:
                        n += 1
            print('number of wraps: ', n)
            print('percentage of wraps:', n / (self.Lt * len(lumen_indxs)) * 100)
            return n
        if method == 'error':
            #concatenate all timesteps together
            length = len(ground_truth[0].vector()[lumen_indxs])
            ground = np.zeros((self.Lt*length))
            u = np.zeros((self.Lt*length))
            for t in range(self.Lt):
                ground[t*length:(t+1)*length] = ground_truth[t].vector()[lumen_indxs]
                u[t*length:(t+1)*length] = wrapped[t].vector()[lumen_indxs]
            #compute norms
            error = np.linalg.norm(u-ground)/np.linalg.norm(ground)
            print('error: ', error)
            return error
        return 0

#
# Analyze4DFlowTest
#

class Analyze4DFlowTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        """ Do whatever is needed to reset the state - typically a scene clear will be enough.
        """
        slicer.mrmlScene.Clear()

    def runTest(self):
        """Run as few or as many tests as needed here.
        """
        self.setUp()
        self.test_Analyze4DFlow1()

    def test_Analyze4DFlow1(self):
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
        inputVolume = SampleData.downloadSample('Analyze4DFlow1')
        self.delayDisplay('Loaded test data set')

        inputScalarRange = inputVolume.GetImageData().GetScalarRange()
        self.assertEqual(inputScalarRange[0], 0)
        self.assertEqual(inputScalarRange[1], 695)

        outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        threshold = 100

        # Test the module logic

        logic = Analyze4DFlowLogic()

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
