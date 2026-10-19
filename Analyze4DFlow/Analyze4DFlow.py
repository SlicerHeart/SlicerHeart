import logging
import os
from typing import Annotated, Optional, Union

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
from slicer import vtkMRMLVectorVolumeNode
from slicer import vtkMRMLMarkupsPlaneNode
from slicer import vtkMRMLModelNode
from slicer import vtkMRMLPlotChartNode
from slicer import vtkMRMLPlotSeriesNode
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
    inputFlowField: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode, None]
    inputPlane: vtkMRMLMarkupsPlaneNode
    inputMaskSegmentation: vtkMRMLSegmentationNode
    inputMaskSegmentID: str
    outputMaskedFlowField: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode, None]
    outputStreamlinesModel: vtkMRMLModelNode
    outputFlowMetricsModel: vtkMRMLModelNode
    outputFlowMetricsTable: vtkMRMLTableNode
    outputFlowMetricsSummaryTable: vtkMRMLTableNode
    outputSpeedVolume: vtkMRMLScalarVolumeNode
    samplingDistance: Annotated[float, WithinRange(0.01, 10)] = 2  # distance unit
    speedThreshold: Annotated[float, WithinRange(0.0, 3), SingleStep(0.01), Default(0.1)]  # m/sec
    streamlinesMaximumLength: Annotated[float, WithinRange(10, 300)] = 200  # distance unit
    streamlinesBidirectional: bool = True
    streamlinesComputeAllMetrics: bool = False
    speedVolumeProjectedToPlane: bool = False  # if True then signed speed vector is projected to the measurement plane normal
    outputFlowMetricsPlotChart: vtkMRMLPlotChartNode

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
        self.ui.inputFlowFieldSelector.setNodeTypeLabel("Flow Field (model)", "vtkMRMLModelNode")
        self.ui.inputFlowFieldSelector.setNodeTypeLabel("Flow Field (grid transform)", "vtkMRMLTransformNode")
        self.ui.inputFlowFieldSelector.setNodeTypeLabel("Flow Field (vector volume)", "vtkMRMLVectorVolumeNode")
        self.ui.inputFlowFieldSelector.noneEnabled = False
        # For now, we do not require "FlowField" attribute for model nodes to make it easy to use any model node as input.
        # self.ui.inputFlowFieldSelector.addAttribute("vtkMRMLModelNode", "SlicerHeart.Type", "FlowField")
        self.ui.inputFlowFieldSelector.addAttribute("vtkMRMLTransformNode", "SlicerHeart.Type", "FlowField")
        self.ui.inputFlowFieldSelector.addAttribute("vtkMRMLVectorVolumeNode", "SlicerHeart.Type", "FlowField")

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
        self.ui.showFlowMetricsPlotButton.connect('clicked(bool)', self.onShowFlowMetricsPlotButton)
        self.ui.sequenceRegistrationPushButton.connect('clicked(bool)', self.onSequenceRegistrationPushButton)
        self.ui.setHeartRateFromDicomButton.connect('clicked(bool)', self.onSetHeartRateFromDicomButton)
        self.ui.setHeartRateFromLengthButton.connect('clicked(bool)', self.onSetHeartRateFromLengthButton)
        self.ui.heartRateBpmDoubleSpinBox.connect('editingFinished()', self.onHeartRateEdited)

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

        if self._parameterNode and not self._parameterNode.inputFlowField:
            flowFieldNode = self.logic.findFirstFlowFieldNode()
            if flowFieldNode:
                self._parameterNode.inputFlowField = flowFieldNode


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

        if self._parameterNode.outputFlowMetricsSummaryTable:
            self.ui.FlowMetricsSummaryTableView.setMRMLTableNode(self._parameterNode.outputFlowMetricsSummaryTable)
            #self.ui.FlowMetricsSummaryTableView.transposed = True

        if self._parameterNode.outputFlowMetricsTable:
            self.ui.FlowMetricsTableView.setMRMLTableNode(self._parameterNode.outputFlowMetricsTable)
            #self.ui.FlowMetricsTableView.firstRowLocked = True
            self.ui.FlowMetricsTableView.firstRowLocked = False

        heartRateBpm = 0.0
        try:
            heartRateBpm = self.logic.heartRateBpm(self._parameterNode.inputFlowField)
        except:
            pass
        self.ui.heartRateBpmDoubleSpinBox.value = heartRateBpm

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

    def onSetHeartRateFromDicomButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to set heart rate from DICOM."):
            flowFieldNode = self._parameterNode.inputFlowField
            heartRateBpm = self.logic.computeHeartRateBpmFromDicom(flowFieldNode)
            self.logic.setHeartRateBpm(flowFieldNode, heartRateBpm, "dicom-nominal-interval")
            self.ui.heartRateBpmDoubleSpinBox.value = heartRateBpm

    def onSetHeartRateFromLengthButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to set heart rate from acquisition length."):
            flowFieldNode = self._parameterNode.inputFlowField
            heartRateBpm = self.logic.computeHeartRateBpmFromAcquisitionLength(flowFieldNode)
            self.logic.setHeartRateBpm(flowFieldNode, heartRateBpm, "acquisition-length")
            self.ui.heartRateBpmDoubleSpinBox.value = heartRateBpm

    def onHeartRateEdited(self) -> None:
        if self._updatingGUIFromParameterNode:
            return

        with slicer.util.tryWithErrorDisplay("Failed to update heart rate."):
            flowFieldNode = self._parameterNode.inputFlowField
            heartRateBpm = self.ui.heartRateBpmDoubleSpinBox.value
            self.logic.setHeartRateBpm(flowFieldNode, heartRateBpm, "user-specified")

    def onAnalyzeButton(self) -> None:
        """
        Run processing when user clicks "Analyze" button.
        """
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):

            if not self._parameterNode.inputFlowField:
                raise ValueError("Please select 'Flow field' input.")

            # Heart rate is only needed for the time-resolved flow metrics summary (forward/backward volume,
            # volume per minute, etc.), which requires the flow field to be in a sequence.
            if self._parameterNode.outputFlowMetricsSummaryTable and self.ui.heartRateBpmDoubleSpinBox.value <= 0:
                raise ValueError("Please set a valid heart rate value for computing output flow metrics.")

            self.addLog("Analyze flow field...")
            self.logic.sampleFlowFieldWithPlane(
                self._parameterNode.inputPlane,
                self._parameterNode.inputFlowField,
                self._parameterNode.samplingDistance,
                self._parameterNode.outputStreamlinesModel,
                self._parameterNode.outputFlowMetricsModel,
                self._parameterNode.inputMaskSegmentation,
                self._parameterNode.inputMaskSegmentID,
                self._parameterNode.streamlinesMaximumLength,
                self._parameterNode.streamlinesBidirectional,
                self._parameterNode.streamlinesComputeAllMetrics,
                self._parameterNode.speedThreshold,
                self._parameterNode.outputSpeedVolume,
                self._parameterNode.speedVolumeProjectedToPlane,
                self._parameterNode.outputMaskedFlowField)

            if self._parameterNode.outputFlowMetricsTable or self._parameterNode.outputFlowMetricsSummaryTable:
                self.addLog("Compute flow metrics table...")
                self.logic.computeFlowMetricsTable(
                    self._parameterNode.outputFlowMetricsModel,
                    self._parameterNode.inputPlane,
                    self._parameterNode.inputFlowField,
                    self._parameterNode.speedThreshold,
                    self._parameterNode.outputFlowMetricsTable,
                    self._parameterNode.outputFlowMetricsSummaryTable)

    def onShowFlowMetricsPlotButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to create plot."):
            self.logic.createPlotFromTable(self._parameterNode.outputFlowMetricsTable)

    def onSequenceRegistrationPushButton(self) -> None:
        """
        Called when the user clicks on the "Sequence registration" button.
        """
        with slicer.util.tryWithErrorDisplay("Motion compensation failed."):
            self.logic.setupSequenceRegistration()

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

        self.dopplerLutRange = [-0.6, 0.6]  # m/s
        self.dopplerLutThreshold = [-0.15, 0.15]  # m/s

        # For testing, it forces resetting color map on each run
        self.forceColorMappingReset = True

    def log(self, text):
        logging.info(text)
        if self.logCallback:
            self.logCallback(text)

    def getParameterNode(self):
        return Analyze4DFlowParameterNode(super().getParameterNode())

    def setupSequenceRegistration(self):
        if not hasattr(slicer.modules, "sequenceregistration"):
            raise RuntimeError("'Sequence registration' extension is not installed. Please install it from the Extension Manager.")

        flowFieldNode = self.getParameterNode().inputFlowField
        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume") if flowFieldNode else None
        if not magnitudeVolumeNode:
            raise RuntimeError("Sequence registration is only supported when the flow field has a magnitude volume"
                               " (4D flow MRI imported as grid transform or vector volume sequence),"
                               " because it registers the magnitude volume sequence, which a model-based flow field does not have.")

        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        if not sequenceBrowserNode:
            raise RuntimeError("Input transform is not in a sequence")

        segmentationNode = self.getParameterNode().inputMaskSegmentation
        if not segmentationNode:
            raise RuntimeError("Input mask segmentation is not set")

        slicer.util.selectModule("SequenceRegistration")
        sequenceRegistrationGui = slicer.util.getModuleWidget("SequenceRegistration")

        segmentationTransformNode = segmentationNode.GetParentTransformNode()
        segmentationTransformSequenceNode = None
        if segmentationTransformNode:
            segmentationTransformSequenceNode = sequenceBrowserNode.GetSequenceNode(segmentationTransformNode)
        if not segmentationTransformNode or not segmentationTransformSequenceNode:
            # Add transform sequence node for the sequence registration result
            segmentationTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", segmentationNode.GetName() + " Transform")
            segmentationTransformSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", segmentationTransformNode.GetName() + " Sequence")
            segmentationTransformSequenceNode.SetIndexType(sequenceBrowserNode.GetMasterSequenceNode().GetIndexType())
            segmentationTransformSequenceNode.SetIndexName(sequenceBrowserNode.GetMasterSequenceNode().GetIndexName())
            segmentationTransformSequenceNode.SetIndexUnit(sequenceBrowserNode.GetMasterSequenceNode().GetIndexUnit())
            slicer.modules.sequences.logic().AddSynchronizedNode(segmentationTransformSequenceNode, segmentationTransformNode, sequenceBrowserNode)
            sequenceBrowserNode.SetSaveChanges(segmentationTransformSequenceNode, True)
            sequenceBrowserNode.SetOverwriteProxyName(segmentationTransformSequenceNode, True)

            # Transform the segmentation node with it
            segmentationNode.SetAndObserveTransformNodeID(segmentationTransformNode.GetID())

        # Set the magnitude volume sequence as input
        magnitudeVolumeSequenceNode = sequenceBrowserNode.GetSequenceNode(magnitudeVolumeNode)
        sequenceRegistrationGui.inputSelector.setCurrentNode(magnitudeVolumeSequenceNode)

        # No need to generate motion-corrected output volume
        sequenceRegistrationGui.outputVolumesSelector.setCurrentNode(None)

        # Set the transform sequence node as output
        sequenceRegistrationGui.outputTransformSelector.setCurrentNode(segmentationTransformSequenceNode)

        # Set registration direction to "fixed frame to moving frames"
        sequenceRegistrationGui.transformDirectionSelector.currentIndex = 1
        # Set fixed frame to current frame
        sequenceRegistrationGui.sequenceFixedItemIndexWidget.value = sequenceBrowserNode.GetSelectedItemNumber()

    def _addNodeToSequenceBrowser(self, node, sequenceBrowserNode):
        # Make sure output models are in the same sequence browser as the flow field sequence and
        # model is in not a proxy node of any other sequence browsers
        foundBrowserNodes = vtk.vtkCollection()
        sequencesLogic = slicer.modules.sequences.logic()
        sequencesLogic.GetBrowserNodesForProxyNode(node, foundBrowserNodes)

        sequenceNode = None
        for i in range(foundBrowserNodes.GetNumberOfItems()):
            foundBrowserNode = foundBrowserNodes.GetItemAsObject(i)
            foundSequenceNode = foundBrowserNode.GetSequenceNode(node)
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

    @staticmethod
    def _addPointDataArray(modelNode, arrayName, arrayValues, arrayType):
        import vtk.util.numpy_support

        # Create a new data array of type arrayType
        dataArray = vtk.vtkDataArray.CreateDataArray(arrayType)
        dataArray.SetName(arrayName)
        dataArray.SetNumberOfComponents(arrayValues.shape[1] if len(arrayValues.shape) > 1 else 1)
        dataArray.SetNumberOfTuples(len(arrayValues))

        narray = vtk.util.numpy_support.vtk_to_numpy(dataArray)
        narray[:] = arrayValues  # deep copy

        modelData = modelNode.GetMesh().GetPointData()
        modelData.AddArray(dataArray)

    @staticmethod
    def _flowFieldKind(flowFieldNode):
        """Flow field storage kind: "transform" (grid transform sequence, legacy 4D flow MRI format),
        "volume" (vector volume with a velocity vector in each voxel) or "model" (mesh with a velocity
        point data array, e.g. CFD result)."""
        if flowFieldNode.IsA("vtkMRMLTransformNode"):
            return "transform"
        if flowFieldNode.IsA("vtkMRMLVolumeNode"):
            return "volume"
        return "model"

    @staticmethod
    def _getGlyphDisplayNodes(node):
        """Return the display nodes of a node that draw a vector field with glyphs (transform display nodes and
        vector field display nodes). These can be very slow to render, and they define the flow field's color mapping."""
        displayNodes = []
        if not node or not node.IsA("vtkMRMLDisplayableNode"):
            return displayNodes
        for displayNodeIndex in range(node.GetNumberOfDisplayNodes()):
            displayNode = node.GetNthDisplayNode(displayNodeIndex)
            if displayNode and (displayNode.IsA("vtkMRMLTransformDisplayNode") or displayNode.IsA("vtkMRMLVectorFieldDisplayNode")):
                displayNodes.append(displayNode)
        return displayNodes

    @staticmethod
    def _flowFieldDisplayNode(flowFieldNode):
        """Display node that defines the flow field's color mapping: the glyph display node if there is one
        (a vector volume flow field may also have a plain volume display node), otherwise the first display node."""
        glyphDisplayNodes = Analyze4DFlowLogic._getGlyphDisplayNodes(flowFieldNode)
        if glyphDisplayNodes:
            return glyphDisplayNodes[0]
        return flowFieldNode.GetDisplayNode()

    @staticmethod
    def _saveAndHideFlowFieldVisibility(flowFieldNode, additionalNodes=None):
        """Hide the glyph display nodes (transform and vector field display nodes) of all proxy nodes in the same
        sequence browser as flowFieldNode. Only glyph displays are hidden (not other displayable nodes such as
        models or volumes), because glyph visualization can be very slow to render.
        Returns a {displayNodeID: wasVisible} dict for later restoration by _restoreFlowFieldVisibility."""
        savedState = {}
        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        if not sequenceBrowserNode:
            return savedState
        proxyNodes = vtk.vtkCollection()
        sequenceBrowserNode.GetAllProxyNodes(proxyNodes)
        nodesToProcess = [proxyNodes.GetItemAsObject(i) for i in range(proxyNodes.GetNumberOfItems())]
        if additionalNodes:
            nodesToProcess.extend(n for n in additionalNodes if n is not None)
        for node in nodesToProcess:
            for displayNode in Analyze4DFlowLogic._getGlyphDisplayNodes(node):
                if displayNode.GetID() in savedState:
                    continue
                savedState[displayNode.GetID()] = displayNode.GetVisibility()
                displayNode.SetVisibility(False)
        return savedState

    @staticmethod
    def _restoreFlowFieldVisibility(savedState):
        """Restore display node visibility from state saved by _saveAndHideFlowFieldVisibility."""
        for displayNodeID, wasVisible in savedState.items():
            if not wasVisible:
                continue
            displayNode = slicer.mrmlScene.GetNodeByID(displayNodeID)
            if displayNode:
                displayNode.SetVisibility(True)

    @staticmethod
    def _getMeshInWorld(modelNode):
        """Return the model node's mesh (e.g. vtkUnstructuredGrid or vtkPolyData) transformed to world coordinates."""
        mesh = modelNode.GetMesh()
        parentTransformNode = modelNode.GetParentTransformNode()
        if not parentTransformNode:
            return mesh
        meshToWorld = vtk.vtkGeneralTransform()
        parentTransformNode.GetTransformToWorld(meshToWorld)
        transformFilter = vtk.vtkTransformFilter()
        transformFilter.SetTransform(meshToWorld)
        # Transform velocity vectors, too (by default only the active vectors would be transformed)
        transformFilter.TransformAllInputVectorsOn()
        transformFilter.SetInputData(mesh)
        transformFilter.Update()
        return transformFilter.GetOutput()

    @staticmethod
    def _closedSurfaceInWorld(segmentationNode, segmentID):
        """Return the closed surface representation of a segment, transformed to world coordinates."""
        segmentationNode.CreateClosedSurfaceRepresentation()
        polyData = vtk.vtkPolyData()
        segmentationNode.GetClosedSurfaceRepresentation(segmentID, polyData)
        parentTransformNode = segmentationNode.GetParentTransformNode()
        if parentTransformNode:
            segmentationToWorld = vtk.vtkGeneralTransform()
            parentTransformNode.GetTransformToWorld(segmentationToWorld)
            transformFilter = vtk.vtkTransformPolyDataFilter()
            transformFilter.SetInputData(polyData)
            transformFilter.SetTransform(segmentationToWorld)
            transformFilter.Update()
            polyData = transformFilter.GetOutput()
        return polyData

    @staticmethod
    def _computeInsideSegmentMask(pointsWorld, maskSegmentationNode, maskSegmentID):
        """Returns a 0/1 numpy array, one value per point in `pointsWorld` (vtkPoints, in world coordinates),
        indicating whether the point is inside the closed surface representation of the given segment."""
        import vtk.util.numpy_support

        closedSurfacePolyData = Analyze4DFlowLogic._closedSurfaceInWorld(maskSegmentationNode, maskSegmentID)

        pointsPolyData = vtk.vtkPolyData()
        pointsPolyData.SetPoints(pointsWorld)

        enclosedPointsFilter = vtk.vtkSelectEnclosedPoints()
        enclosedPointsFilter.SetInputData(pointsPolyData)
        enclosedPointsFilter.SetSurfaceData(closedSurfacePolyData)
        enclosedPointsFilter.Update()

        insideArray = enclosedPointsFilter.GetOutput().GetPointData().GetArray("SelectedPoints")
        return vtk.util.numpy_support.vtk_to_numpy(insideArray).copy()

    @staticmethod
    def _getVelocityArrayName(pointData):
        """Return the name of the velocity point data array ("V" or "Velocity", whichever is available)."""
        for name in ("V", "Velocity"):
            if pointData.GetArray(name):
                return name
        return None

    @staticmethod
    def findFirstFlowFieldNode():
        """Return the first flow field node found in the scene: a transform or vector volume node tagged with
        "SlicerHeart.Type"="FlowField", or otherwise the first model node whose mesh is an
        unstructured grid with a supported velocity array ("V" or "Velocity")."""
        for nodeClassName in ["vtkMRMLTransformNode", "vtkMRMLVectorVolumeNode"]:
            for node in slicer.util.getNodesByClass(nodeClassName):
                if node.GetAttribute("SlicerHeart.Type") == "FlowField":
                    return node

        for modelNode in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            mesh = modelNode.GetMesh()
            if not mesh or not mesh.IsA("vtkUnstructuredGrid"):
                continue
            if Analyze4DFlowLogic._getVelocityArrayName(mesh.GetPointData()) is not None:
                return modelNode

        return None

    @staticmethod
    def _initializeSpeedVolumeGeometry(outputSpeedVolume, flowFieldNode, meshWorld, objectToWorldMatrix, totalVoxelCount=256**3):
        """Initialize outputSpeedVolume's geometry for a model-based (e.g. CFD) flow field:
        - the volume is placed under the same parent transform as flowFieldNode
        - the IJK axes are aligned with objectToWorldMatrix (the measurement plane orientation),
          with the K axis pointing along the plane normal
        - the bounds cover meshWorld's world-space bounding box
        - the spacing is uniform (isotropic), chosen so the grid has about totalVoxelCount voxels
        Returns an (empty) vtkImageData grid, in world coordinates, ready to be probed.
        """
        import numpy as np

        axisI = np.array([objectToWorldMatrix.GetElement(r, 0) for r in range(3)])
        axisJ = np.array([objectToWorldMatrix.GetElement(r, 1) for r in range(3)])
        axisK = np.array([objectToWorldMatrix.GetElement(r, 2) for r in range(3)])
        axisI = axisI / np.linalg.norm(axisI)
        axisJ = axisJ / np.linalg.norm(axisJ)
        axisK = axisK / np.linalg.norm(axisK)

        # Compute the mesh's oriented bounding box along (axisI, axisJ, axisK)
        boundsWorld = meshWorld.GetBounds()
        cornersLocal = []
        for x in boundsWorld[0:2]:
            for y in boundsWorld[2:4]:
                for z in boundsWorld[4:6]:
                    corner = np.array([x, y, z])
                    cornersLocal.append([np.dot(corner, axisI), np.dot(corner, axisJ), np.dot(corner, axisK)])
        cornersLocal = np.array(cornersLocal)
        minLocal = cornersLocal.min(axis=0)
        maxLocal = cornersLocal.max(axis=0)
        extent = maxLocal - minLocal
        originWorld = axisI * minLocal[0] + axisJ * minLocal[1] + axisK * minLocal[2]

        extentVolume = extent[0] * extent[1] * extent[2]
        spacing = (extentVolume / totalVoxelCount) ** (1.0 / 3.0) if extentVolume > 0 else 1.0
        dims = [max(1, int(round(extent[i] / spacing))) for i in range(3)]

        # Place the speed volume under the same parent transform as the input flow field, and express
        # the grid geometry (below) in that same (untransformed) coordinate system.
        parentTransformNode = flowFieldNode.GetParentTransformNode()
        outputSpeedVolume.SetAndObserveTransformNodeID(parentTransformNode.GetID() if parentTransformNode else None)

        worldToParent = vtk.vtkGeneralTransform()
        if parentTransformNode:
            parentTransformNode.GetTransformFromWorld(worldToParent)
        else:
            worldToParent.Identity()

        originParent = [0.0, 0.0, 0.0]
        worldToParent.TransformPoint(originWorld, originParent)
        axisIParent = [0.0, 0.0, 0.0]
        worldToParent.TransformVectorAtPoint(originWorld, axisI, axisIParent)
        axisJParent = [0.0, 0.0, 0.0]
        worldToParent.TransformVectorAtPoint(originWorld, axisJ, axisJParent)
        axisKParent = [0.0, 0.0, 0.0]
        worldToParent.TransformVectorAtPoint(originWorld, axisK, axisKParent)

        ijkToRAS = vtk.vtkMatrix4x4()
        ijkToRAS.Identity()
        for r in range(3):
            ijkToRAS.SetElement(r, 0, axisIParent[r] * spacing)
            ijkToRAS.SetElement(r, 1, axisJParent[r] * spacing)
            ijkToRAS.SetElement(r, 2, axisKParent[r] * spacing)
            ijkToRAS.SetElement(r, 3, originParent[r])
        outputSpeedVolume.SetIJKToRASMatrix(ijkToRAS)

        # Build the (unfilled) probing grid in world coordinates, oriented with the same I, J, K axes
        directionMatrix = vtk.vtkMatrix3x3()
        for r in range(3):
            directionMatrix.SetElement(r, 0, axisI[r])
            directionMatrix.SetElement(r, 1, axisJ[r])
            directionMatrix.SetElement(r, 2, axisK[r])

        imageData = vtk.vtkImageData()
        imageData.SetDimensions(dims)
        imageData.SetSpacing(spacing, spacing, spacing)
        imageData.SetOrigin(originWorld[0], originWorld[1], originWorld[2])
        imageData.SetDirectionMatrix(directionMatrix)
        return imageData

    @staticmethod
    def _buildCrossSectionSamplePolyDataWorld(crossSectionPlaneNode, samplingDistanceMm):
        """Build a regular grid of sample points covering the measurement plane's bounds, transformed
        to world coordinates. Returns (samplePolyDataWorld, objectToWorldMatrix)."""
        import math

        planeBoundsMm = crossSectionPlaneNode.GetPlaneBounds()
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
        objectToWorldTransformFilter.Update()

        return objectToWorldTransformFilter.GetOutput(), objectToWorldMatrix

    @staticmethod
    def _prepareOutputFlowMetricsModel(outputFlowMetricsModel, samplePolyDataWorld):
        """Ensure outputFlowMetricsModel exists (creating a temporary one if needed) and has a default
        display node, then set its polydata to samplePolyDataWorld.
        Returns (outputFlowMetricsModel, createdTemporary)."""
        createdTemporary = False
        if not outputFlowMetricsModel:
            # Create model node for the output flow metrics, if not provided then we create a temporary one
            outputFlowMetricsModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "__tmp__Flow metrics")
            createdTemporary = True
        if not outputFlowMetricsModel.GetDisplayNode():
            # Initialize model display node
            outputFlowMetricsModel.CreateDefaultDisplayNodes()
            displayNode = outputFlowMetricsModel.GetDisplayNode()
            displayNode.SetColor(1, 1, 0)
            displayNode.SetEdgeVisibility(True)
            displayNode.BackfaceCullingOff()
            displayNode.LightingOff()  # don't make the grid darker if it is rotated
        outputFlowMetricsModel.SetAndObservePolyData(samplePolyDataWorld)
        return outputFlowMetricsModel, createdTemporary

    def _addOutputNodesToSequenceBrowser(self, sequenceBrowserNode, outputStreamlinesModel, outputSpeedVolume,
            outputMaskedFlowField, outputFlowMetricsModel, includeFlowMetricsModel):
        """Add the given output nodes to the same sequence browser as the input flow field."""
        resultProxyNodes = [outputStreamlinesModel, outputSpeedVolume, outputMaskedFlowField]
        if includeFlowMetricsModel:
            resultProxyNodes.append(outputFlowMetricsModel)
        for node in resultProxyNodes:
            if not node:
                continue
            self._addNodeToSequenceBrowser(node, sequenceBrowserNode)

    @staticmethod
    def _createVelocityImageFromFlowField(flowFieldNode, magnitudeVolumeNode):
        """Create a temporary vector volume node (added to the scene, in world coordinates) that holds the velocity
        vectors (m/s) of the current frame of an image-based flow field. For a grid transform, the displacement field
        is sampled on the magnitude volume grid. For a vector volume flow field, the voxels are copied, so that the
        copy can be masked without changing the input."""
        if flowFieldNode.IsA("vtkMRMLTransformNode"):
            velocityImageNode = slicer.modules.transforms.logic().CreateDisplacementVolumeFromTransform(
                flowFieldNode, magnitudeVolumeNode, False, slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode"))
            if not velocityImageNode:
                raise RuntimeError("Failed to compute velocity vectors from the flow field transform")
            # The displacement volume is marked as spatial vectors, which would make Slicer convert the vectors to LPS
            # when the volume is passed to a CLI module (probe volume with model), but the probed vectors are not
            # converted back to RAS. Process the RAS vectors as generic vectors, the same way as vector volume flow fields.
            if hasattr(velocityImageNode, "SetVoxelVectorType"):
                velocityImageNode.SetVoxelVectorType(slicer.vtkMRMLVolumeNode.VoxelVectorTypeUndefined)
            return velocityImageNode
        if flowFieldNode.GetParentTransformNode():
            raise RuntimeError("Vector volume flow field under a parent transform is not supported. Harden or remove the parent transform of the flow field.")
        imageData = flowFieldNode.GetImageData()
        if not imageData or imageData.GetNumberOfScalarComponents() != 3:
            raise RuntimeError("Vector volume flow field must have 3 scalar components (velocity vector in each voxel).")
        velocityImageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "__tmp__Velocity image")
        velocityImageNode.CopyOrientation(flowFieldNode)
        velocityImage = vtk.vtkImageData()
        velocityImage.DeepCopy(imageData)
        velocityImageNode.SetAndObserveImageData(velocityImage)
        return velocityImageNode

    @staticmethod
    def _setVectorVolumeFromDisplacementImage(vectorVolumeNode, displacementImageNode):
        """Copy the velocity vectors and geometry of displacementImageNode (in world coordinates) into vectorVolumeNode."""
        vectorVolumeNode.SetAndObserveTransformNodeID(None)
        vectorVolumeNode.CopyOrientation(displacementImageNode)
        velocityImage = vtk.vtkImageData()
        velocityImage.DeepCopy(displacementImageNode.GetImageData())
        vectorVolumeNode.SetAndObserveImageData(velocityImage)

    def _sampleImageFrame(self, flowFieldNode, magnitudeVolumeNode, outputFlowMetricsModel,
            maskSegmentationNode, maskSegmentID, streamlinesSpeedThresholdMPerSec,
            outputStreamlinesModel, outputSpeedVolume, outputMaskedFlowField, probeVolumeCliNode):
        """Sample the velocity field of an image-based flow field (grid transform or vector volume) onto
        outputFlowMetricsModel's points ("Speed" array), compute the vessel mask ("insideVessel"/"SpeedMasked"
        arrays), optionally mask the full 3D velocity image (needed for streamlines / speed volume / masked output),
        and write outputMaskedFlowField if requested.
        Returns (displacementImageNode, probeVolumeCliNode). The caller owns displacementImageNode and
        must remove it after use; probeVolumeCliNode is reused across frames and should only be removed
        once the whole sequence has been processed."""
        import numpy as np

        displacementImageNode = self._createVelocityImageFromFlowField(flowFieldNode, magnitudeVolumeNode)

        maskLabelmapNode = None
        try:
            parameters = {}
            parameters["InputVolume"] = displacementImageNode
            parameters["InputModel"] = outputFlowMetricsModel
            parameters["OutputModel"] = outputFlowMetricsModel
            parameters["OutputArrayName"] = "Speed"
            probeVolumeWithModel = slicer.modules.probevolumewithmodel
            probeVolumeCliNode = slicer.cli.runSync(probeVolumeWithModel, probeVolumeCliNode, parameters)
            if probeVolumeCliNode.GetStatus() & probeVolumeCliNode.ErrorsMask:
                # error
                errorText = probeVolumeCliNode.GetErrorText()
                slicer.mrmlScene.RemoveNode(probeVolumeCliNode)
                raise ValueError("Probe 4D field execution failed: " + errorText)

            if maskSegmentationNode and maskSegmentID:
                # Vessel mask is set by segmentation

                # Export mask segment to labelmap node
                maskLabelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "__tmp__Mask labelmap")
                slicer.vtkSlicerSegmentationsModuleLogic.ExportSegmentsToLabelmapNode(maskSegmentationNode, [maskSegmentID], maskLabelmapNode, displacementImageNode)
                slicer.mrmlScene.RemoveNode(maskLabelmapNode.GetDisplayNode().GetColorNode())

                # Probe mask image with model
                parameters["InputVolume"] = maskLabelmapNode
                parameters["InputModel"] = outputFlowMetricsModel
                tempOutputFlowMetricsMaskModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "__tmp__Mask model")
                parameters["OutputModel"] = tempOutputFlowMetricsMaskModel
                parameters["OutputArrayName"] = "insideVessel"
                probeVolumeCliNode = slicer.cli.runSync(probeVolumeWithModel, probeVolumeCliNode, parameters)
                if probeVolumeCliNode.GetStatus() & probeVolumeCliNode.ErrorsMask:
                    # error
                    errorText = probeVolumeCliNode.GetErrorText()
                    slicer.mrmlScene.RemoveNode(tempOutputFlowMetricsMaskModel)
                    slicer.mrmlScene.RemoveNode(probeVolumeCliNode)
                    raise ValueError("Probe 4D field execution failed: " + errorText)

                # Save mask array
                insideVesselArray = slicer.util.arrayFromModelPointData(tempOutputFlowMetricsMaskModel, 'insideVessel').copy()
                slicer.mrmlScene.RemoveNode(tempOutputFlowMetricsMaskModel)

            else:
                # Generate mask based on speed magnitude
                maskLabelmapNode = None

                # Get displacement magnitude array
                displacementArray = slicer.util.arrayFromModelPointData(outputFlowMetricsModel, 'Speed')
                displacementMagnitudeArray = np.linalg.norm(displacementArray, axis=1)
                insideVesselArray = displacementMagnitudeArray > streamlinesSpeedThresholdMPerSec

            # Save mask array into the flow metrics model
            Analyze4DFlowLogic._addPointDataArray(outputFlowMetricsModel, "insideVessel", insideVesselArray, vtk.VTK_UNSIGNED_SHORT)

            # Set all displacements outside the mask to zero
            displacementArray = slicer.util.arrayFromModelPointData(outputFlowMetricsModel, 'Speed')
            maskedDisplacementArray = displacementArray.copy()
            maskedDisplacementArray[insideVesselArray==0, :] = 0
            Analyze4DFlowLogic._addPointDataArray(outputFlowMetricsModel, "SpeedMasked", maskedDisplacementArray, vtk.VTK_FLOAT)

            # Apply mask to displacement image if further processing is requested
            if maskLabelmapNode and (outputStreamlinesModel or outputSpeedVolume or outputMaskedFlowField):
                displacementImageArray = slicer.util.arrayFromVolume(displacementImageNode)
                maskImageArray = slicer.util.arrayFromVolume(maskLabelmapNode)
                displacementImageArray[maskImageArray==0, :] = 0
            elif outputMaskedFlowField and not maskLabelmapNode:
                # No segmentation mask — apply speed threshold as a 3D mask
                displacementImageArray = slicer.util.arrayFromVolume(displacementImageNode)
                displacementMagnitudeArray = np.linalg.norm(displacementImageArray, axis=3)
                displacementImageArray[displacementMagnitudeArray <= streamlinesSpeedThresholdMPerSec, :] = 0

            if outputMaskedFlowField:
                if outputMaskedFlowField.IsA("vtkMRMLTransformNode"):
                    self._setTransformFromDisplacementImage(outputMaskedFlowField, displacementImageNode)
                else:
                    self._setVectorVolumeFromDisplacementImage(outputMaskedFlowField, displacementImageNode)
                outputMaskedFlowField.Modified()

        except Exception:
            # The caller only takes ownership of displacementImageNode on a successful return,
            # so clean it up here if we bail out early.
            slicer.mrmlScene.RemoveNode(displacementImageNode)
            raise
        finally:
            if maskLabelmapNode:
                slicer.mrmlScene.RemoveNode(maskLabelmapNode)

        return displacementImageNode, probeVolumeCliNode

    def _sampleModelFrame(self, flowFieldNode, outputFlowMetricsModel, maskSegmentationNode, maskSegmentID,
            streamlinesSpeedThresholdMPerSec, needMaskedMesh):
        """Sample the flow field model's velocity field onto outputFlowMetricsModel's points ("Speed"
        array), compute the vessel mask ("insideVessel"/"SpeedMasked" arrays), and optionally build a
        masked copy of the full flow field mesh (needed for streamlines / speed volume / masked output).
        Returns (flowFieldMeshWorld, velocityArrayName, maskedFlowFieldMesh-or-None)."""
        import numpy as np
        import vtk.util.numpy_support

        # Sample the velocity field ("V" or "Velocity" point data array) of the flow field mesh onto the cross-section sample points
        flowFieldMeshWorld = self._getMeshInWorld(flowFieldNode)
        velocityArrayName = self._getVelocityArrayName(flowFieldMeshWorld.GetPointData())
        if velocityArrayName is None:
            raise ValueError("Input flow field model does not contain a point data array named 'V' or 'Velocity'")
        probeFilter = vtk.vtkProbeFilter()
        probeFilter.SetInputData(outputFlowMetricsModel.GetPolyData())
        probeFilter.SetSourceData(flowFieldMeshWorld)
        probeFilter.Update()
        velocityArray = probeFilter.GetOutput().GetPointData().GetArray(velocityArrayName)
        Analyze4DFlowLogic._addPointDataArray(outputFlowMetricsModel, "Speed",
            vtk.util.numpy_support.vtk_to_numpy(velocityArray), vtk.VTK_FLOAT)

        # Determine which sample points are inside the vessel of interest
        if maskSegmentationNode and maskSegmentID:
            # Vessel mask is set by segmentation
            insideVesselArray = self._computeInsideSegmentMask(
                outputFlowMetricsModel.GetPolyData().GetPoints(), maskSegmentationNode, maskSegmentID)
        else:
            # Generate mask based on speed magnitude
            displacementArray = slicer.util.arrayFromModelPointData(outputFlowMetricsModel, 'Speed')
            displacementMagnitudeArray = np.linalg.norm(displacementArray, axis=1)
            insideVesselArray = displacementMagnitudeArray > streamlinesSpeedThresholdMPerSec

        # Save mask array into the flow metrics model
        Analyze4DFlowLogic._addPointDataArray(outputFlowMetricsModel, "insideVessel", insideVesselArray, vtk.VTK_UNSIGNED_SHORT)

        # Set all displacements outside the mask to zero
        displacementArray = slicer.util.arrayFromModelPointData(outputFlowMetricsModel, 'Speed')
        maskedDisplacementArray = displacementArray.copy()
        maskedDisplacementArray[insideVesselArray==0, :] = 0
        Analyze4DFlowLogic._addPointDataArray(outputFlowMetricsModel, "SpeedMasked", maskedDisplacementArray, vtk.VTK_FLOAT)

        # Prepare a masked copy of the full flow field mesh for streamlines / masked output / speed volume
        maskedFlowFieldMesh = None
        if needMaskedMesh:
            maskedFlowFieldMesh = flowFieldMeshWorld.NewInstance()
            maskedFlowFieldMesh.DeepCopy(flowFieldMeshWorld)
            fullVelocityArray = vtk.util.numpy_support.vtk_to_numpy(maskedFlowFieldMesh.GetPointData().GetArray(velocityArrayName))
            if maskSegmentationNode and maskSegmentID:
                insideVesselArrayFull = self._computeInsideSegmentMask(
                    maskedFlowFieldMesh.GetPoints(), maskSegmentationNode, maskSegmentID)
            else:
                speedMagnitudeFull = np.linalg.norm(fullVelocityArray, axis=1)
                insideVesselArrayFull = speedMagnitudeFull > streamlinesSpeedThresholdMPerSec
            fullVelocityArray[insideVesselArrayFull == 0, :] = 0
            maskedFlowFieldMesh.GetPointData().GetArray(velocityArrayName).Modified()

        return flowFieldMeshWorld, velocityArrayName, maskedFlowFieldMesh

    @staticmethod
    def _initializeStreamlinesDisplayNode(outputStreamlinesModel, flowFieldNode):
        """Set up the streamlines model's display node (color/edges/lighting, colored by "Speed",
        reusing the flow field's color table if it has one), unless already initialized."""
        if outputStreamlinesModel.GetDisplayNode() and outputStreamlinesModel.GetDisplayNode().GetScalarVisibility():
            return
        outputStreamlinesModel.CreateDefaultDisplayNodes()
        displayNode = outputStreamlinesModel.GetDisplayNode()
        displayNode.SetColor(0, 0, 1)
        displayNode.SetEdgeVisibility(True)
        displayNode.BackfaceCullingOff()
        displayNode.LightingOff()  # don't make the lines darker depending on orientation
        displayNode.SetActiveScalarName('Speed')
        flowFieldDisplayNode = Analyze4DFlowLogic._flowFieldDisplayNode(flowFieldNode)
        if flowFieldDisplayNode and flowFieldDisplayNode.GetColorNodeID():
            # Use the same color table and scaling as the flow field
            displayNode.SetAndObserveColorNodeID(flowFieldDisplayNode.GetColorNodeID())
            displayNode.SetScalarRangeFlag(displayNode.UseColorNodeScalarRange)
        else:
            displayNode.SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileViridis.txt")
        displayNode.ScalarVisibilityOn()

    @staticmethod
    def _computeSpeedVolumeScalarArray(vectorImageArray, speedVolumeProjectedToPlane, planeNormal):
        """Compute the scalar speed volume array from a vector field image array: either the speed
        magnitude, or (if speedVolumeProjectedToPlane) the signed component along planeNormal."""
        import numpy as np
        if speedVolumeProjectedToPlane:
            # Project speed vector to the plane.
            # Compute dot product of each element of vectorImageArray by planeNormal.
            # Do not iterate through points one by one because it would be too slow
            # (use numpy operations instead).
            return np.sum(vectorImageArray * planeNormal, axis=3)
        else:
            return np.linalg.norm(vectorImageArray, axis=3)

    def _updateSpeedVolumeColorMapping(self, outputSpeedVolume, flowFieldNode, speedVolumeProjectedToPlane, streamlinesSpeedThresholdMPerSec):
        """Set up (or refresh) outputSpeedVolume's color table and window/level for Doppler-like visualization."""
        if not outputSpeedVolume.GetScalarVolumeDisplayNode():
            outputSpeedVolume.CreateDefaultDisplayNodes()
        colorNode = outputSpeedVolume.GetScalarVolumeDisplayNode().GetColorNode()
        # colorMappingType is Speed (for absolute speed) or SpeedComponent (for Doppler-like signed speed)
        currentColorMappingType = colorNode.GetAttribute("SlicerHeart.ColorMappingType") if colorNode else None
        requiredColorMappingType = "SpeedComponent" if speedVolumeProjectedToPlane else "Speed"
        if currentColorMappingType == requiredColorMappingType and not self.forceColorMappingReset:
            return

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
                flowFieldDisplayNode = self._flowFieldDisplayNode(flowFieldNode)
                if flowFieldDisplayNode and flowFieldDisplayNode.GetColorNodeID():
                    # Use the same color table and scaling as the flow field
                    colorNodeID = flowFieldDisplayNode.GetColorNodeID()
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
            # Use the color node's range
            speedVolumeDisplayNode.SetAutoWindowLevel(False)
            scalarRange = speedVolumeDisplayNode.GetColorNode().GetScalarsToColors().GetRange()
            speedVolumeDisplayNode.SetWindowLevelMinMax(*scalarRange)
            speedVolumeDisplayNode.SetApplyThreshold(True)
            speedVolumeDisplayNode.SetThreshold(streamlinesSpeedThresholdMPerSec, scalarRange[1])

    @staticmethod
    def _finalizeOutputMaskedFlowField(outputMaskedFlowField, flowFieldNode):
        """After the per-frame loop, position outputMaskedFlowField next to flowFieldNode in the subject
        hierarchy and copy display settings (and the color legend, if any) from flowFieldNode."""
        # Move the masked flow field into next to the input flow field in the subject hierarchy
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        inputItem = shNode.GetItemByDataNode(flowFieldNode)
        outputItem = shNode.GetItemByDataNode(outputMaskedFlowField)
        if inputItem and outputItem:
            shNode.SetItemParent(outputItem, shNode.GetItemParent(inputItem))

        if not outputMaskedFlowField.GetDisplayNode():
            sourceDisplayNode = Analyze4DFlowLogic._flowFieldDisplayNode(flowFieldNode)
            if sourceDisplayNode:
                newDisplayNode = slicer.mrmlScene.AddNewNodeByClass(sourceDisplayNode.GetClassName())
                newDisplayNode.CopyContent(sourceDisplayNode)
                newDisplayNode.SetVisibility(False)
                if sourceDisplayNode.IsA("vtkMRMLTransformDisplayNode") or sourceDisplayNode.IsA("vtkMRMLVectorFieldDisplayNode"):
                    # Copy the glyph display node's region references too (CopyContent does not copy node references).
                    # Transform display node uses "region", vector field display node uses "samplingRegion"
                    # (or "region" in earlier Slicer versions) and "maskingRegion" reference role.
                    for referenceRole in ["region", "samplingRegion", "maskingRegion"]:
                        regionNodeID = sourceDisplayNode.GetNodeReferenceID(referenceRole)
                        if regionNodeID:
                            newDisplayNode.SetNodeReferenceID(referenceRole, regionNodeID)
                outputMaskedFlowField.SetAndObserveDisplayNodeID(newDisplayNode.GetID())
            elif not outputMaskedFlowField.IsA("vtkMRMLTransformNode"):
                outputMaskedFlowField.CreateDefaultDisplayNodes()
                outputMaskedFlowField.GetDisplayNode().SetVisibility(False)

        # Copy the color legend display node
        for i in range(flowFieldNode.GetNumberOfDisplayNodes()):
            dn = flowFieldNode.GetNthDisplayNode(i)
            if dn and dn.IsA("vtkMRMLColorLegendDisplayNode"):
                existingIDs = [outputMaskedFlowField.GetNthDisplayNodeID(j)
                               for j in range(outputMaskedFlowField.GetNumberOfDisplayNodes())]
                if dn.GetID() not in existingIDs:
                    outputMaskedFlowField.AddAndObserveDisplayNodeID(dn.GetID())
                break

    def sampleFlowFieldWithPlane(
            self,
            crossSectionPlaneNode: vtkMRMLMarkupsPlaneNode,
            flowFieldNode: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode],
            samplingDistanceMm: float = 2.0,
            outputStreamlinesModel: vtkMRMLModelNode = None,
            outputFlowMetricsModel: vtkMRMLModelNode = None,
            maskSegmentationNode: vtkMRMLSegmentationNode = None,
            maskSegmentID: str = None,
            streamlinesMaximumLengthMm: int = 100,
            streamlinesBidirectional: bool = True,
            streamlinesComputeAllMetrics: bool = False,
            streamlinesSpeedThresholdMPerSec: float = 0.01,
            outputSpeedVolume: vtkMRMLScalarVolumeNode = None,
            speedVolumeProjectedToPlane: bool = False,
            outputMaskedFlowField: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode] = None) -> vtkMRMLModelNode:

        import vtk.util.numpy_support

        if not crossSectionPlaneNode:
            raise ValueError("Measurement plane node is invalid")

        # The flow field can be a grid transform (legacy 4D flow MRI format, with a "magnitudeVolume" node reference),
        # a vector volume (velocity vector in each voxel), or a model whose mesh has a "V"/"Velocity" point data array
        # (e.g. CFD results). Grid transforms and vector volumes are processed the same way (image-based path).
        flowFieldKind = self._flowFieldKind(flowFieldNode)
        isTransformInput = (flowFieldKind == "transform")
        isImageInput = (flowFieldKind != "model")
        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume") if isTransformInput else None

        if outputMaskedFlowField and self._flowFieldKind(outputMaskedFlowField) != flowFieldKind:
            raise ValueError("Output masked flow field must be the same node type (model, grid transform, or vector volume) as the input flow field.")

        # The flow field may optionally be a proxy node of a Sequence (one frame per time point).
        # If it is not in a sequence then it is treated as a single static frame (grid transforms
        # are always expected to be time-resolved, so they still require a sequence).
        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        if isTransformInput and not sequenceBrowserNode:
            raise RuntimeError("Input transform is not in a sequence")

        needMaskedField = bool(outputStreamlinesModel or outputSpeedVolume or outputMaskedFlowField)
        probeVolumeCliNode = None  # reused across frames by the image-based path
        deleteOutputFlowMetricsModel = False

        try:

            # Turn off transform visibility to speed up browsing
            savedTransformVisibility = self._saveAndHideFlowFieldVisibility(flowFieldNode, [outputMaskedFlowField])

            if sequenceBrowserNode:
                originalItemNumber = sequenceBrowserNode.GetSelectedItemNumber()
                numberOfItems = sequenceBrowserNode.GetNumberOfItems()
            else:
                originalItemNumber = None
                numberOfItems = 1
            for itemNumber in range(numberOfItems):
                self.log("Sampling flow field with plane... ({item}/{count})".format(item=itemNumber+1, count=numberOfItems))

                if sequenceBrowserNode:
                    sequenceBrowserNode.SetSelectedItemNumber(itemNumber)

                samplePolyDataWorld, objectToWorldMatrix = self._buildCrossSectionSamplePolyDataWorld(crossSectionPlaneNode, samplingDistanceMm)
                outputFlowMetricsModel, createdTemporary = self._prepareOutputFlowMetricsModel(outputFlowMetricsModel, samplePolyDataWorld)
                if createdTemporary:
                    deleteOutputFlowMetricsModel = True

                if sequenceBrowserNode:
                    # Add the output nodes to the same sequence browser as the input 4D flow field
                    # (only add the flow metrics model if it is not temporary)
                    self._addOutputNodesToSequenceBrowser(sequenceBrowserNode, outputStreamlinesModel, outputSpeedVolume,
                        outputMaskedFlowField, outputFlowMetricsModel, not deleteOutputFlowMetricsModel)

                if isImageInput:
                    # ============================================================
                    # Image-based (grid transform or vector volume, 4D flow MRI) path
                    # ============================================================
                    displacementImageNode, probeVolumeCliNode = self._sampleImageFrame(
                        flowFieldNode, magnitudeVolumeNode, outputFlowMetricsModel, maskSegmentationNode, maskSegmentID,
                        streamlinesSpeedThresholdMPerSec, outputStreamlinesModel, outputSpeedVolume, outputMaskedFlowField,
                        probeVolumeCliNode)
                    try:
                        # Update streamlines
                        if outputStreamlinesModel:
                            speedImageNodeMPerSec = displacementImageNode  # "displacement image" actually stores a speed vector field
                            self._createStreamlinesFromImage(outputStreamlinesModel, speedImageNodeMPerSec, outputFlowMetricsModel,
                                streamlinesMaximumLengthMm, streamlinesBidirectional, streamlinesComputeAllMetrics, streamlinesSpeedThresholdMPerSec)
                            self._initializeStreamlinesDisplayNode(outputStreamlinesModel, flowFieldNode)

                        # Create speed volume for Doppler-like visualization
                        if outputSpeedVolume:
                            ijkToRAS = vtk.vtkMatrix4x4()
                            displacementImageNode.GetIJKToRASMatrix(ijkToRAS)
                            outputSpeedVolume.SetIJKToRASMatrix(ijkToRAS)
                            displacementImageArray = slicer.util.arrayFromVolume(displacementImageNode)
                            speedVolumeArray = self._computeSpeedVolumeScalarArray(
                                displacementImageArray, speedVolumeProjectedToPlane, crossSectionPlaneNode.GetNormalWorld())
                            slicer.util.updateVolumeFromArray(outputSpeedVolume, speedVolumeArray)
                            self._updateSpeedVolumeColorMapping(outputSpeedVolume, flowFieldNode, speedVolumeProjectedToPlane, streamlinesSpeedThresholdMPerSec)
                    finally:
                        slicer.mrmlScene.RemoveNode(displacementImageNode)

                else:
                    # ============================================================
                    # Model (e.g. CFD result) path
                    # ============================================================
                    flowFieldMeshWorld, velocityArrayName, maskedFlowFieldMesh = self._sampleModelFrame(
                        flowFieldNode, outputFlowMetricsModel, maskSegmentationNode, maskSegmentID,
                        streamlinesSpeedThresholdMPerSec, needMaskedField)

                    if outputMaskedFlowField:
                        outputMaskedFlowField.SetAndObserveMesh(maskedFlowFieldMesh)
                        outputMaskedFlowField.Modified()

                    # Update streamlines
                    if outputStreamlinesModel:
                        self._createStreamlinesFromMesh(outputStreamlinesModel, maskedFlowFieldMesh, velocityArrayName, outputFlowMetricsModel,
                            streamlinesMaximumLengthMm, streamlinesBidirectional, streamlinesComputeAllMetrics, streamlinesSpeedThresholdMPerSec)
                        self._initializeStreamlinesDisplayNode(outputStreamlinesModel, flowFieldNode)

                    # Create speed volume for Doppler-like visualization
                    if outputSpeedVolume:
                        speedVolumeGrid = self._initializeSpeedVolumeGeometry(
                            outputSpeedVolume, flowFieldNode, flowFieldMeshWorld, objectToWorldMatrix)
                        probeFilter = vtk.vtkProbeFilter()
                        probeFilter.SetInputData(speedVolumeGrid)
                        probeFilter.SetSourceData(maskedFlowFieldMesh)
                        probeFilter.Update()
                        resampledImageData = probeFilter.GetOutput()
                        dims = resampledImageData.GetDimensions()
                        velocityImageArray = vtk.util.numpy_support.vtk_to_numpy(
                            resampledImageData.GetPointData().GetArray(velocityArrayName)).reshape([dims[2], dims[1], dims[0], 3])
                        speedVolumeArray = self._computeSpeedVolumeScalarArray(
                            velocityImageArray, speedVolumeProjectedToPlane, crossSectionPlaneNode.GetNormalWorld())
                        slicer.util.updateVolumeFromArray(outputSpeedVolume, speedVolumeArray)
                        self._updateSpeedVolumeColorMapping(outputSpeedVolume, flowFieldNode, speedVolumeProjectedToPlane, streamlinesSpeedThresholdMPerSec)

            if outputMaskedFlowField:
                self._finalizeOutputMaskedFlowField(outputMaskedFlowField, flowFieldNode)

        finally:
            # Clean up
            if probeVolumeCliNode:
                slicer.mrmlScene.RemoveNode(probeVolumeCliNode)
            if sequenceBrowserNode:
                sequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)
            self._restoreFlowFieldVisibility(savedTransformVisibility)
            if deleteOutputFlowMetricsModel and outputFlowMetricsModel:
                slicer.mrmlScene.RemoveNode(outputFlowMetricsModel.GetDisplayNode())
                slicer.mrmlScene.RemoveNode(outputFlowMetricsModel)
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

        import Import4DFlow
        dopplerColorNode = Import4DFlow.Import4DFlowLogic.dopplerColdToHotColorTableNode()
        colorMapResolution = 25
        rgba = [0, 0, 0, 0]
        for i in range(colorMapResolution):
            colorIndex = int(i / (colorMapResolution - 1) * (dopplerColorNode.GetNumberOfColors() - 1))
            dopplerColorNode.GetColor(colorIndex, rgba)
            colorMap.AddRGBPoint(lutRange[0] + i / (colorMapResolution - 1) * (lutRange[1] - lutRange[0]), rgba[0], rgba[1], rgba[2])

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

    @staticmethod
    def _setTransformFromDisplacementImage(transformNode, displacementImageNode):
        import numpy as np
        import vtkAddon

        spacing = list(displacementImageNode.GetSpacing())
        origin = list(displacementImageNode.GetOrigin())

        ijkToRAS = vtk.vtkMatrix4x4()
        displacementImageNode.GetIJKToRASMatrix(ijkToRAS)
        directionMatrix = vtk.vtkMatrix4x4()
        for c in range(3):
            col_norm = np.linalg.norm([ijkToRAS.GetElement(r, c) for r in range(3)])
            for r in range(3):
                directionMatrix.SetElement(r, c, ijkToRAS.GetElement(r, c) / col_norm if col_norm > 0 else 0)

        gridImageData = vtk.vtkImageData()
        gridImageData.DeepCopy(displacementImageNode.GetImageData())
        gridImageData.SetOrigin(origin)
        gridImageData.SetSpacing(spacing)

        gridTransform = vtkAddon.vtkOrientedGridTransform()
        gridTransform.SetDisplacementGridData(gridImageData)
        gridTransform.SetGridDirectionMatrix(directionMatrix)
        gridTransform.SetInterpolationModeToCubic()

        transformNode.SetAndObserveTransformToParent(gridTransform)

    def _createStreamlinesFromImage(self, outputStreamlinesModel, speedImageNodeMPerSec, seedPointsModel, maximumLengthMm, bidirectional, computeAllMetrics, speedThresholdMPerSec):
        import vtkAddon
        import numpy as np

        seedPointsAll = seedPointsModel.GetPolyData()

        # Only keep seed points that are inside the vessel
        threshold = vtk.vtkThresholdPoints()
        threshold.SetInputData(seedPointsAll)
        threshold.ThresholdByUpper(0.5)  # Keep values > 0
        threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "insideVessel")
        threshold.Update()
        seedPoints = threshold.GetOutput()

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

        # Note: various streamlines, pathlines, etc. are described here: http://www.vmtk.org/tutorials/ParticleTracing.html
        # vtkParticleTracerBase is available for particle tracing in unsteady vector fields        #
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
        if pointData.GetArray('ImageScalars'):
            # Rename the input array to "Velocity"
            pointData.GetArray('ImageScalars').SetName('Velocity')

        if pointData.GetArray('Velocity'):
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

    def _createStreamlinesFromMesh(self, outputStreamlinesModel, flowFieldMesh, velocityArrayName, seedPointsModel, maximumLengthMm, bidirectional, computeAllMetrics, speedThresholdMPerSec):
        seedPointsAll = seedPointsModel.GetPolyData()

        # Only keep seed points that are inside the vessel
        threshold = vtk.vtkThresholdPoints()
        threshold.SetInputData(seedPointsAll)
        threshold.ThresholdByUpper(0.5)  # Keep values > 0
        threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "insideVessel")
        threshold.Update()
        seedPoints = threshold.GetOutput()

        # Note: various streamlines, pathlines, etc. are described here: http://www.vmtk.org/tutorials/ParticleTracing.html
        # vtkParticleTracerBase is available for particle tracing in unsteady vector fields
        streamLine = vtk.vtkStreamTracer()
        streamLine.SetInputData(flowFieldMesh)
        streamLine.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, velocityArrayName)
        streamLine.SetSourceData(seedPoints)
        streamLine.SetMaximumPropagation(maximumLengthMm)
        streamLine.SetInitialIntegrationStep(0.1)
        if bidirectional:
            streamLine.SetIntegrationDirectionToBoth()
        else:
            streamLine.SetIntegrationDirectionToForward()
        streamLine.SetTerminalSpeed(speedThresholdMPerSec)
        streamLine.Update()

        streamLinesWorld = streamLine.GetOutput()
        pointData = streamLinesWorld.GetPointData()

        if pointData.GetArray(velocityArrayName):
            # Compute the speed (velocity magnitude) for coloring.
            # If the velocity vector was used for coloring then the streamlines would be colored by
            # the first component of the velocity vector, which would not be correct.
            # The "Speed" array should be used for coloring instead.
            # vtkArrayCalculator needs the vector array to be named "Velocity"; if the source array is
            # already named that way, use it directly instead of adding a (then removing a) duplicate.
            addedVelocityAlias = velocityArrayName != 'Velocity'
            if addedVelocityAlias:
                velocityAliasArray = vtk.vtkFloatArray()
                velocityAliasArray.DeepCopy(pointData.GetArray(velocityArrayName))
                velocityAliasArray.SetName('Velocity')
                pointData.AddArray(velocityAliasArray)

            acalc = vtk.vtkArrayCalculator()
            acalc.AddVectorArrayName("Velocity")
            acalc.SetResultArrayName("Speed")
            acalc.SetFunction("mag(Velocity)")
            acalc.SetInputData(streamLinesWorld)
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
                if addedVelocityAlias:
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

    @staticmethod
    def _heartRateAttributeStorageNode(flowFieldNode: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode]):
        """Heart rate is stored as an attribute. For backward compatibility, if the flow field has a
        "magnitudeVolume" reference (4D flow MRI, stored in a grid transform or vector volume sequence), it is
        stored on the magnitude volume's sequence node, as before. Otherwise it is stored on the flow field's own
        sequence node, if it is in a sequence, or directly on the flow field node itself (single static frame)."""
        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
        if magnitudeVolumeNode:
            sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(magnitudeVolumeNode)
            if sequenceBrowserNode:
                return sequenceBrowserNode.GetSequenceNode(magnitudeVolumeNode)
        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        if sequenceBrowserNode:
            return sequenceBrowserNode.GetSequenceNode(flowFieldNode)
        return flowFieldNode

    def heartRateBpm(self, flowFieldNode: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode]):
        attributeStorageNode = self._heartRateAttributeStorageNode(flowFieldNode)
        heartRateBpmStr = attributeStorageNode.GetAttribute("SlicerHeart.heartRateBpm")
        try:
            heartRateBpm = float(heartRateBpmStr)
        except Exception as e:
            raise RuntimeError("Heart rate information is not available for this flow field.")
        if heartRateBpm <= 0:
            raise RuntimeError("Heart rate information for this flow field is invalid.")
        return heartRateBpm

    def setHeartRateBpm(self, flowFieldNode: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode], heartRateBpm: float, source: str):
        attributeStorageNode = self._heartRateAttributeStorageNode(flowFieldNode)
        attributeStorageNode.SetAttribute("SlicerHeart.heartRateBpm", str(heartRateBpm))
        attributeStorageNode.SetAttribute("SlicerHeart.heartRateSource", source)

    def computeHeartRateBpmFromAcquisitionLength(self, flowFieldNode: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode]):
        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        if not sequenceBrowserNode:
            raise RuntimeError("Acquisition length cannot be computed because the flow field is not in a sequence.")
        flowFieldSequenceNode = sequenceBrowserNode.GetSequenceNode(flowFieldNode)
        firstFrameTime = float(flowFieldSequenceNode.GetNthIndexValue(0))
        lastFrameTime = float(flowFieldSequenceNode.GetNthIndexValue(flowFieldSequenceNode.GetNumberOfDataNodes()-1))
        timeIntervalMsec = lastFrameTime - firstFrameTime
        heartRateBpm = 60000 / timeIntervalMsec
        return heartRateBpm

    def computeHeartRateBpmFromDicom(self, flowFieldNode: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode]):
        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
        if not magnitudeVolumeNode:
            raise RuntimeError("DICOM-based heart rate detection requires a magnitude volume reference"
                               " (only available for 4D flow MRI flow fields, stored in a grid transform or vector volume sequence).")
        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(magnitudeVolumeNode)
        magnitudeVolumeSequenceNode = sequenceBrowserNode.GetSequenceNode(magnitudeVolumeNode) if sequenceBrowserNode else None
        if not magnitudeVolumeSequenceNode:
            raise RuntimeError("Magnitude volume sequence node not found")

        # Get subject hierarchy ID to get DICOM series instance UID
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        shItemID = shNode.GetItemByDataNode(magnitudeVolumeNode)
        if not shItemID:
            raise RuntimeError("Subject hierarchy item not found for magnitude volume node")
        instanceUIDs = shNode.GetItemUID(shItemID, "DICOMInstanceUID")
        if not instanceUIDs:
            raise RuntimeError("DICOM instance UIDs not found for magnitude volume node subject hierarchy item")
        instanceUID = instanceUIDs.split(" ")[0]  # use the first instance UID

        # Get NominalInterval DICOM field
        filename = slicer.dicomDatabase.fileForInstance(instanceUID)
        if not filename:
            raise RuntimeError("DICOM file not found in database for instance UID: " + instanceUID)
        import pydicom
        ds = pydicom.dcmread(filename)
        try:
            nominalInterval = float(ds["NominalInterval"].value)
        except Exception as e:
            raise RuntimeError("Failed to get heart rate from DICOM file: " + str(e))

        # Compute heart rate
        heartRateBpm = 60000.0 / nominalInterval
        logging.debug(f"Computed heart rate for {magnitudeVolumeNode.GetName()} from DICOM NominalInterval: {heartRateBpm:.2f} bpm")
        return heartRateBpm

    def computeFlowMetricsTable(
            self,
            crossSectionModelNode: vtkMRMLModelNode,
            crossSectionPlaneNode: vtkMRMLMarkupsPlaneNode,
            flowFieldNode: Union[vtkMRMLModelNode, vtkMRMLTransformNode, vtkMRMLVectorVolumeNode] = None,
            speedThresholdMPerSec: float = 0.1,
            outputFlowMetricsTableNode: vtkMRMLTableNode = None,
            outputFlowMetricsSummaryTableNode: vtkMRMLTableNode = None):

        if (outputFlowMetricsTableNode is None) and (outputFlowMetricsSummaryTableNode is None):
            # nothing to do
            return

        import numpy as np
        import vtk

        # crossSectionModelNode may optionally be a proxy node of a Sequence (one frame per time point).
        # If it is not in a sequence then it is treated as a single static frame.
        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(crossSectionModelNode)
        sequenceNode = sequenceBrowserNode.GetSequenceNode(crossSectionModelNode) if sequenceBrowserNode else None

        # Turn off transform visibility to speed up browsing
        savedTransformVisibility = self._saveAndHideFlowFieldVisibility(flowFieldNode) if flowFieldNode else {}

        triangulate = vtk.vtkTriangleFilter()
        triangulate.SetInputData(crossSectionModelNode.GetPolyData())

        modelProperties = vtk.vtkMassProperties()
        modelProperties.SetInputConnection(triangulate.GetOutputPort())
        modelProperties.Update()
        totalAreaMm2 = modelProperties.GetSurfaceArea()
        numberOfPoints = crossSectionModelNode.GetPolyData().GetNumberOfCells()
        areaPerPointMm2 = totalAreaMm2 / numberOfPoints

        # Get plane normal
        planeNormal = crossSectionPlaneNode.GetNormalWorld()  # sampled velocity vectors are in world coordinate system

        metricNames = ["Time", "Area", "PositiveArea", "NegativeArea",
                       "FlowRate", "PositiveFlowRate", "NegativeFlowRate",
                       "MeanVelocity", "MaxVelocity", "MinVelocity", "StdDevVelocity", "ProjectedSpeed",
                       "Percentile1Velocity", "Percentile5Velocity", "Percentile95Velocity", "Percentile99Velocity",
                       "PositiveVolume", "NegativeVolume"]
        numberOfItems = sequenceBrowserNode.GetNumberOfItems() if sequenceBrowserNode else 1
        metrics = np.zeros([numberOfItems, len(metricNames)])

        originalItemNumber = sequenceBrowserNode.GetSelectedItemNumber() if sequenceBrowserNode else None
        for itemNumber in range(numberOfItems):
            self.log("Computing flow metrics... ({item}/{count})".format(item=itemNumber+1, count=numberOfItems))

            if sequenceBrowserNode:
                sequenceBrowserNode.SetSelectedItemNumber(itemNumber)
            allSpeedMPerSec = slicer.util.arrayFromModelPointData(crossSectionModelNode, 'Speed')
            insideVessel = slicer.util.arrayFromModelPointData(crossSectionModelNode, 'insideVessel')

            speedMPerSec = allSpeedMPerSec[insideVessel != 0]

            if len(speedMPerSec) > 0:

                # Project speed vector to the plane
                # Compute dot product of each element of displacementImageArray by planeNormal.
                # Do not iterate through points one by one because it would be too slow
                # (use numpy operations instead).
                projectedSpeedMPerSec = np.sum(speedMPerSec * planeNormal, axis=1)

                velocitySign = np.sign(projectedSpeedMPerSec)
                velocityMagnitudeMPerSec = np.linalg.norm(speedMPerSec, axis=1)
                signedVelocityMagnitudeMPerSec = velocitySign * velocityMagnitudeMPerSec

                meanVelocityMPerSec = velocityMagnitudeMPerSec.mean()
                minVelocityMPerSec = velocityMagnitudeMPerSec.min()
                maxVelocityMPerSec = velocityMagnitudeMPerSec.max()
                stdDevSpeedMPerSec = velocityMagnitudeMPerSec.std()
                percentile1VelocityMPerSec = np.percentile(velocityMagnitudeMPerSec, 1)
                percentile5VelocityMPerSec = np.percentile(velocityMagnitudeMPerSec, 5)
                percentile95VelocityMPerSec = np.percentile(velocityMagnitudeMPerSec, 95)
                percentile99VelocityMPerSec = np.percentile(velocityMagnitudeMPerSec, 99)

                areaMm2 = len(speedMPerSec) * areaPerPointMm2
                areaPositiveMm2 = np.sum(signedVelocityMagnitudeMPerSec >= 0) * areaPerPointMm2
                areaNegativeMm2 = areaMm2 - areaPositiveMm2

                # Forward/backward flow: flux of the velocity field through the plane, i.e., the velocity component
                # normal to the plane is integrated over the cross-section. Using the velocity magnitude instead would
                # overestimate the flow if the plane is not perpendicular to the flow direction.
                positiveFlowRateMlPerSec = np.sum(projectedSpeedMPerSec[projectedSpeedMPerSec>0]) * areaPerPointMm2
                negativeFlowRateMlPerSec = np.sum(projectedSpeedMPerSec[projectedSpeedMPerSec<0]) * areaPerPointMm2

                # TODO: max acceleration (cm/s/s) / min acceleration (cm/s/s) - to be worked on later

            else:
                # no values above threshold
                areaMm2 = 0
                areaPositiveMm2 = 0
                areaNegativeMm2 = 0
                positiveFlowRateMlPerSec = 0
                negativeFlowRateMlPerSec = 0
                meanVelocityMPerSec = 0
                maxVelocityMPerSec = 0
                minVelocityMPerSec = 0
                stdDevSpeedMPerSec = 0
                percentile1VelocityMPerSec = 0
                percentile5VelocityMPerSec = 0
                percentile95VelocityMPerSec = 0
                percentile99VelocityMPerSec = 0

            metrics[itemNumber, metricNames.index("Time")] = float(sequenceNode.GetNthIndexValue(itemNumber)) if sequenceNode else 0.0
            metrics[itemNumber, metricNames.index("Area")] = areaMm2
            metrics[itemNumber, metricNames.index("PositiveArea")] = areaPositiveMm2
            metrics[itemNumber, metricNames.index("NegativeArea")] = areaNegativeMm2
            metrics[itemNumber, metricNames.index("FlowRate")] = positiveFlowRateMlPerSec + negativeFlowRateMlPerSec
            metrics[itemNumber, metricNames.index("PositiveFlowRate")] = positiveFlowRateMlPerSec
            metrics[itemNumber, metricNames.index("NegativeFlowRate")] = negativeFlowRateMlPerSec  # can be negative
            metrics[itemNumber, metricNames.index("MeanVelocity")] = meanVelocityMPerSec
            metrics[itemNumber, metricNames.index("MinVelocity")] = minVelocityMPerSec
            metrics[itemNumber, metricNames.index("MaxVelocity")] = maxVelocityMPerSec
            metrics[itemNumber, metricNames.index("StdDevVelocity")] = stdDevSpeedMPerSec
            metrics[itemNumber, metricNames.index("Percentile1Velocity")] = percentile1VelocityMPerSec
            metrics[itemNumber, metricNames.index("Percentile5Velocity")] = percentile5VelocityMPerSec
            metrics[itemNumber, metricNames.index("Percentile95Velocity")] = percentile95VelocityMPerSec
            metrics[itemNumber, metricNames.index("Percentile99Velocity")] = percentile99VelocityMPerSec

        if sequenceBrowserNode:
            sequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)
        self._restoreFlowFieldVisibility(savedTransformVisibility)

        if outputFlowMetricsTableNode:
            savedMetrics = [
                ["Time", 1, "ms", ""],
                ["Area", 1, "mm2", ""],
                ["PositiveArea", 1, "mm2", ""],
                ["NegativeArea", 1, "mm2", ""],
                ["FlowRate", 1, "ml/s", f"Sum of positive and negative flow through the plane cross-section (velocity component normal to the plane integrated over the cross-section)"],
                ["PositiveFlowRate", 1, "ml/s", f"Flow in the plane cross-section in forward flow direction"],
                ["NegativeFlowRate", 1, "ml/s", f"Flow in the plane cross-section in backward flow direction"],
                ["MeanVelocity", 100, "cm/s", f"Average speed in the plane cross-section"],
                ["MaxVelocity", 100, "cm/s", f"Maximum speed in the plane cross-section"],
                ["MinVelocity", 100, "cm/s", f"Minimum speed in the plane cross-section"],
                ["Percentile1Velocity", 100, "cm/s", f"1st percentile speed in the plane cross-section"],
                ["Percentile5Velocity", 100, "cm/s", f"5th percentile speed in the plane cross-section"],
                ["Percentile95Velocity", 100, "cm/s", f"95th percentile speed in the plane cross-section"],
                ["Percentile99Velocity", 100, "cm/s", f"99th percentile speed in the plane cross-section"],
                ["StdDevVelocity", 100, "cm/s", f"Standard deviation of flow speed in the plane cross-section"],
            ]

            outputFlowMetricsTableNode.RemoveAllColumns()
            outputFlowMetricsTable = outputFlowMetricsTableNode.GetTable()

            for name, scale, unit, description in savedMetrics:
                dataArray = vtk.vtkDoubleArray()
                dataArray.SetName(name)

                # Bulk copy metric values to the table
                arrayValues = metrics[:, metricNames.index(name)]
                dataArray.SetNumberOfTuples(len(arrayValues))
                import vtk.util.numpy_support
                narray = vtk.util.numpy_support.vtk_to_numpy(dataArray)
                narray[:] = scale * arrayValues  # deep copy

                # Add the array to the table and set metadata
                outputFlowMetricsTable.AddColumn(dataArray)
                outputFlowMetricsTableNode.SetColumnUnitLabel(name, unit)
                outputFlowMetricsTableNode.SetColumnDescription(name, description)

        if outputFlowMetricsSummaryTableNode:

            if not sequenceBrowserNode:
                raise RuntimeError("Flow metrics summary requires the flow field to be in a sequence (it needs heart rate and multiple time points).")

            outputFlowMetricsSummaryTableNode.RemoveAllColumns()
            outputFlowMetricsSummaryTable = outputFlowMetricsSummaryTableNode.GetTable()

            # Get heart rate from the flow field sequence (if available)
            try:
                heartRateBpm = self.heartRateBpm(flowFieldNode)
            except RuntimeError as e:
                raise RuntimeError("Invalid heart rate, cannot compute flow metrics summary: " + str(e))

            # VolumeMl = integral of FlowRate[ml/s] Time[s] = integral of FlowRate[ml/s] 0.001 * Time[ms]
            forwardVolumeMl, backwardVolumeMl = Analyze4DFlowLogic.trapezoidAreaSplitZero(0.001 * metrics[:, metricNames.index("Time")], metrics[:, metricNames.index("FlowRate")])
            totalVolumeMl = forwardVolumeMl + backwardVolumeMl

            volumeLiterPerMin = forwardVolumeMl / 1000 * heartRateBpm
            volumeEffectiveLiterPerMin = totalVolumeMl / 1000 * heartRateBpm
            regurgitationFractionPercent = -backwardVolumeMl / forwardVolumeMl * 100 if forwardVolumeMl > 0 else 0

            # np.trapz was renamed to np.trapezoid in numpy 2.0 (and removed later)
            trapezoid = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
            netPositiveVolumeMl = trapezoid(metrics[:, metricNames.index("PositiveFlowRate")], 0.001 * metrics[:, metricNames.index("Time")])
            netNegativeVolumeMl = trapezoid(metrics[:, metricNames.index("NegativeFlowRate")], 0.001 * metrics[:, metricNames.index("Time")])

            # Simplified Bernoulli equation (https://www.e-echocardiography.com/calculators/miscellaneous/simplified-bernoulli-equation)
            maxVelocityMPerSec = metrics[:, metricNames.index("MaxVelocity")].max()
            maxPressureGradient = (4 * maxVelocityMPerSec**2)  # mmHg

            maxFlowRateMlPerSec = np.max(metrics[:, metricNames.index("FlowRate")])  # ml/s

            savedSummaryMetrics = [
                ["ForwardVolume", "ml", f"Positive area under FlowRate(time) curve", forwardVolumeMl],
                ["BackwardVolume", "ml", f"Negative area under FlowRate(time) curve", backwardVolumeMl],
                ["TotalVolume", "ml", f"Sum of forward and backward volume", totalVolumeMl],
                ["RegurgitationFraction", "%", f"Backward volume divided by the forward volume, expressed in percent (0-100)", regurgitationFractionPercent],
                ["VolPerMinute", "l/min", f"Forward volume per minute (computed from heart rate stored in the DICOM image metadata and forward volume)", volumeLiterPerMin],
                ["EffectiveVolPerMinute", "l/min", f"Total volume per minute (computed from heart rate stored in the DICOM image metadata and total volume)", volumeEffectiveLiterPerMin],
                ["PeakVelocity", "cm/s", f"Maximum of MaxVelocity values", maxVelocityMPerSec * 100],
                ["MaxPressureGradient", "mmHg", f"Maximum pressure gradient computed from PeakVelocity", maxPressureGradient],
                ["MaxFlow", "ml/s", f"Maximum of FlowRate values", maxFlowRateMlPerSec],
                ["NetPositiveVolume", "ml", f"Area under PositiveFlowRate(time) curve", netPositiveVolumeMl],
                ["NetNegativeVolume", "ml", f"Area under NegativeFlowRate(time) curve", netNegativeVolumeMl],
            ]

            for name, unit, description, value in savedSummaryMetrics:
                dataArray = vtk.vtkDoubleArray()
                dataArray.SetName(name)
                dataArray.InsertNextValue(value)
                outputFlowMetricsSummaryTable.AddColumn(dataArray)
                outputFlowMetricsSummaryTableNode.SetColumnUnitLabel(name, unit)
                outputFlowMetricsSummaryTableNode.SetColumnDescription(name, description)

            outputFlowMetricsSummaryTableNode.Modified()

    def createPlotFromTable(self, flowMetricsTableNode: vtkMRMLTableNode) -> list[vtkMRMLPlotSeriesNode]:

        parameterNode = self.getParameterNode()

        metricNamesUnits = [("Area", "mm2"), ("PositiveArea", "mm2"), ("NegativeArea", "mm2"),
                       ("FlowRate", "ml/s"), ("PositiveFlowRate", "ml/s"), ("NegativeFlowRate", "ml/s"),
                       ("MeanVelocity", "cm/s"), ("MaxVelocity", "cm/s"), ("MinVelocity", "cm/s"), ("StdDevVelocity", "cm/s"), ("ProjectedSpeed", "cm/s"),
                       ("Percentile1Velocity", "cm/s"), ("Percentile5Velocity", "cm/s"), ("Percentile95Velocity", "cm/s"), ("Percentile99Velocity", "cm/s"),
                       ("PositiveVolume", "ml"), ("NegativeVolume", "ml")]

        # Create chart and add plots
        plotChartNode = parameterNode.outputFlowMetricsPlotChart
        if not plotChartNode:
            plotChartNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode")
            parameterNode.outputFlowMetricsPlotChart = plotChartNode
        plotChartNode.SetTitle("Flow Metrics")
        plotChartNode.SetXAxisTitle("time [ms]")

        plotSeriesNodes = []
        for metricName, unit in metricNamesUnits:
            if flowMetricsTableNode.GetColumnIndex(metricName) < 0:
                continue  # metric not available

            # Check if plot series node already exists
            plotSeriesNode = None
            addToPlot = False
            numberOfSeries = plotChartNode.GetNumberOfPlotSeriesNodes()
            for seriesIndex in range(numberOfSeries):
                aPlotSeriesNode = plotChartNode.GetNthPlotSeriesNode(seriesIndex)
                if aPlotSeriesNode.GetYColumnName() == metricName:
                    plotSeriesNode = aPlotSeriesNode
                    break
            if not plotSeriesNode:
                plotSeriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode")
                addToPlot = True
            plotSeriesNodes.append(plotSeriesNode)

            # Set up the plot series
            plotSeriesNode.SetName(f"{metricName} [{unit}]")
            plotSeriesNode.SetAndObserveTableNodeID(flowMetricsTableNode.GetID())
            plotSeriesNode.SetXColumnName("Time")
            plotSeriesNode.SetYColumnName(metricName)
            plotSeriesNode.SetPlotType(plotSeriesNode.PlotTypeScatter)

            # Set color
            chartColorNode = slicer.mrmlScene.GetNodeByID('vtkMRMLColorTableNodeFileMediumChartColors.txt')

            rgba = [0, 0, 0, 1]
            chartColorNode.GetColor(len(plotSeriesNodes) % chartColorNode.GetNumberOfColors(), rgba)
            plotSeriesNode.SetColor(rgba[0], rgba[1], rgba[2])

            if addToPlot:
                plotChartNode.AddAndObservePlotSeriesNodeID(plotSeriesNode.GetID())

        # Show plot in layout
        slicer.modules.plots.logic().ShowChartInLayout(plotChartNode)

        return plotSeriesNodes

    @staticmethod
    def trapezoidAreaSplitZero(x_vals, y_vals):
        """
        Compute the positive and negative areas under a curve using the trapezoid rule.
        If a trapezoid interval crosses zero, it is split at the zero crossing
        so that the positive and negative contributions are accurately counted.

        Parameters:
            x_vals (list of float): x-coordinates of the function samples (must be ordered).
            y_vals (list of float): y-coordinates of the function samples.

        Returns:
            tuple:
                pos_area (float): Total area where y > 0
                neg_area (float): Total area where y < 0 (negative value)
        """
        pos_area = 0
        neg_area = 0

        for i in range(len(x_vals)-1):
            x0, x1 = x_vals[i], x_vals[i+1]
            y0, y1 = y_vals[i], y_vals[i+1]

            # If the interval does not cross zero
            if y0 * y1 >= 0:
                area = 0.5 * (y0 + y1) * (x1 - x0)
                if area > 0:
                    pos_area += area
                else:
                    neg_area += area
            else:
                # Interval crosses zero: split it
                # Find zero crossing using linear interpolation
                x_zero = x0 - y0 * (x1 - x0) / (y1 - y0)

                # Area from x0 to zero crossing
                area1 = 0.5 * (y0 + 0) * (x_zero - x0)
                if area1 > 0:
                    pos_area += area1
                else:
                    neg_area += area1

                # Area from zero crossing to x1
                area2 = 0.5 * (0 + y1) * (x1 - x_zero)
                if area2 > 0:
                    pos_area += area2
                else:
                    neg_area += area2

        return pos_area, neg_area


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
        self.setUp()
        self.test_ComputeHeartRateBpmFromDicom()
        self.setUp()
        self.test_AnalyzeTransformAndVectorVolumeFlowField()

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

    def test_ComputeHeartRateBpmFromDicom(self):
        """Heart rate must be read from the NominalInterval field of the magnitude image.

        Regression test for reading DICOM headers with pydicom (the pydicom.read_file
        function was removed in pydicom 3).
        """
        import shutil
        import tempfile
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid
        from DICOMLib import DICOMUtils

        self.delayDisplay("Create a magnitude image with a nominal RR interval of 800 msec")
        sopInstanceUID = generate_uid()
        ds = Dataset()
        ds.PatientName = "Test^Patient"
        ds.PatientID = "Analyze4DFlowTest"
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.SOPInstanceUID = sopInstanceUID
        ds.SOPClassUID = MRImageStorage
        ds.Modality = "MR"
        ds.StudyDate = "20240102"
        ds.SeriesNumber = 1
        ds.InstanceNumber = 1
        ds.NominalInterval = 800  # msec, 75 bpm
        ds.Rows = 2
        ds.Columns = 2
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.PixelData = bytes(ds.Rows * ds.Columns * 2)
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
        ds.file_meta.MediaStorageSOPInstanceUID = sopInstanceUID
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

        tempDir = tempfile.mkdtemp(prefix="Analyze4DFlowTest_", dir=slicer.app.temporaryPath)
        try:
            dicomDir = os.path.join(tempDir, "dicom")
            os.makedirs(dicomDir)
            dicomFilePath = os.path.join(dicomDir, "magnitude.dcm")
            try:
                ds.save_as(dicomFilePath, enforce_file_format=True)  # pydicom >= 3.0
            except TypeError:
                ds.is_little_endian = True
                ds.is_implicit_VR = False
                ds.save_as(dicomFilePath, write_like_original=False)  # pydicom 2.x

            with DICOMUtils.TemporaryDICOMDatabase(os.path.join(tempDir, "DICOMDatabase")) as db:
                self.assertTrue(DICOMUtils.importDicom(dicomDir, db))
                self.assertTrue(db.fileForInstance(sopInstanceUID))

                # The magnitude volume must be a proxy node of a volume sequence
                volumeNode = slicer.vtkMRMLScalarVolumeNode()
                volumeNode.SetName("Magnitude")
                sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "MagnitudeSequence")
                sequenceNode.SetDataNodeAtValue(volumeNode, "0")
                browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "MagnitudeBrowser")
                browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
                slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
                proxyVolumeNode = browserNode.GetProxyNode(sequenceNode)
                self.assertIsNotNone(proxyVolumeNode)
                shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                shItemID = shNode.GetItemByDataNode(proxyVolumeNode)
                self.assertTrue(shItemID)
                shNode.SetItemUID(shItemID, "DICOMInstanceUID", sopInstanceUID)

                flowFieldNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLGridTransformNode", "FlowField")
                flowFieldNode.SetNodeReferenceID("magnitudeVolume", proxyVolumeNode.GetID())

                self.delayDisplay("Compute heart rate from DICOM header")
                logic = Analyze4DFlowLogic()
                heartRateBpm = logic.computeHeartRateBpmFromDicom(flowFieldNode)
        finally:
            shutil.rmtree(tempDir, ignore_errors=True)

        self.assertAlmostEqual(heartRateBpm, 75.0)

        self.delayDisplay("Test passed")

    def _createSyntheticFlowFields(self, dims, spacingMm, originMm, frameSpeedsMPerSec):
        """Create a sequence browser with a magnitude volume sequence and the same synthetic flow field stored both
        as a grid transform sequence and as a vector volume sequence. The flow is along the S axis, with the given
        speed in each frame inside a central column (|R| and |A| below a quarter of the volume size) and zero elsewhere.
        Returns (transformFlowFieldNode, vectorVolumeFlowFieldNode, velocityArrays), where velocityArrays[frame] is the
        velocity image of a frame (k, j, i, component)."""
        import numpy as np

        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "FlowBrowser")

        def createSequenceNode(name):
            sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
            sequenceNode.SetIndexName("time")
            sequenceNode.SetIndexUnit("ms")
            return sequenceNode

        magnitudeSequenceNode = createSequenceNode("Magnitude")
        transformSequenceNode = createSequenceNode("Flow field transform")
        vectorVolumeSequenceNode = createSequenceNode("Flow field vector volume")

        velocityArrays = []
        k, j, i = np.indices(tuple(reversed(dims)))
        insideColumn = np.logical_and(np.abs(i - (dims[0] - 1) / 2.0) * spacingMm[0] <= dims[0] * spacingMm[0] / 4.0,
                                      np.abs(j - (dims[1] - 1) / 2.0) * spacingMm[1] <= dims[1] * spacingMm[1] / 4.0)
        for frame, speedMPerSec in enumerate(frameSpeedsMPerSec):
            indexValue = str(100 * frame)

            magnitudeVolumeNode = slicer.vtkMRMLScalarVolumeNode()
            magnitudeImage = vtk.vtkImageData()
            magnitudeImage.SetDimensions(dims)
            magnitudeImage.AllocateScalars(vtk.VTK_SHORT, 1)
            magnitudeVolumeNode.SetAndObserveImageData(magnitudeImage)
            magnitudeVolumeNode.SetSpacing(spacingMm)
            magnitudeVolumeNode.SetOrigin(originMm)
            slicer.util.arrayFromVolume(magnitudeVolumeNode)[:] = 100
            slicer.util.arrayFromVolumeModified(magnitudeVolumeNode)
            magnitudeSequenceNode.SetDataNodeAtValue(magnitudeVolumeNode, indexValue)

            vectorVolumeNode = slicer.vtkMRMLVectorVolumeNode()
            velocityImage = vtk.vtkImageData()
            velocityImage.SetDimensions(dims)
            velocityImage.AllocateScalars(vtk.VTK_FLOAT, 3)
            vectorVolumeNode.SetAndObserveImageData(velocityImage)
            vectorVolumeNode.CopyOrientation(magnitudeVolumeNode)
            vectorVolumeNode.SetAttribute("SlicerHeart.Type", "FlowField")
            velocityArray = slicer.util.arrayFromVolume(vectorVolumeNode)
            velocityArray[:] = 0.0
            velocityArray[insideColumn, 2] = speedMPerSec
            slicer.util.arrayFromVolumeModified(vectorVolumeNode)
            velocityArrays.append(velocityArray.copy())
            vectorVolumeSequenceNode.SetDataNodeAtValue(vectorVolumeNode, indexValue)

            transformNode = slicer.vtkMRMLTransformNode()
            transformNode.SetAttribute("SlicerHeart.Type", "FlowField")
            Analyze4DFlowLogic._setTransformFromDisplacementImage(transformNode, vectorVolumeNode)
            transformSequenceNode.SetDataNodeAtValue(transformNode, indexValue)

        browserNode.SetAndObserveMasterSequenceNodeID(magnitudeSequenceNode.GetID())
        browserNode.AddSynchronizedSequenceNodeID(transformSequenceNode.GetID())
        browserNode.AddSynchronizedSequenceNodeID(vectorVolumeSequenceNode.GetID())
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)

        magnitudeVolumeNode = browserNode.GetProxyNode(magnitudeSequenceNode)
        transformFlowFieldNode = browserNode.GetProxyNode(transformSequenceNode)
        vectorVolumeFlowFieldNode = browserNode.GetProxyNode(vectorVolumeSequenceNode)
        for flowFieldNode in [transformFlowFieldNode, vectorVolumeFlowFieldNode]:
            self.assertIsNotNone(flowFieldNode)
            flowFieldNode.SetAttribute("SlicerHeart.Type", "FlowField")
            flowFieldNode.SetNodeReferenceID("magnitudeVolume", magnitudeVolumeNode.GetID())
        return transformFlowFieldNode, vectorVolumeFlowFieldNode, velocityArrays

    def test_AnalyzeTransformAndVectorVolumeFlowField(self):
        """The same flow field stored as a grid transform sequence and as a vector volume sequence
        must give the same flow metrics, speed volume, and masked flow field.
        """
        import numpy as np

        dims = (20, 20, 10)
        spacingMm = (2.0, 2.0, 2.0)
        originMm = (-19.0, -19.0, -9.0)
        frameSpeedsMPerSec = [0.5, 0.25]

        self.delayDisplay("Create synthetic flow fields")
        transformFlowFieldNode, vectorVolumeFlowFieldNode, velocityArrays = self._createSyntheticFlowFields(
            dims, spacingMm, originMm, frameSpeedsMPerSec)
        logic = Analyze4DFlowLogic()
        self.assertEqual(logic.findFirstFlowFieldNode().GetAttribute("SlicerHeart.Type"), "FlowField")
        self.assertEqual(logic._flowFieldKind(transformFlowFieldNode), "transform")
        self.assertEqual(logic._flowFieldKind(vectorVolumeFlowFieldNode), "volume")

        # Heart rate is stored on the magnitude volume sequence for both storage types
        logic.setHeartRateBpm(vectorVolumeFlowFieldNode, 60.0, "user-specified")
        self.assertAlmostEqual(logic.heartRateBpm(transformFlowFieldNode), 60.0)
        self.assertAlmostEqual(logic.heartRateBpm(vectorVolumeFlowFieldNode), 60.0)

        # Measurement plane perpendicular to the flow, in the middle of the volume
        planeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "Plane")
        planeNode.SetPlaneType(planeNode.PlaneTypePointNormal)
        planeNode.AddControlPointWorld(vtk.vtkVector3d(0.0, 0.0, 0.0))
        planeNode.SetNormal([0.0, 0.0, 1.0])
        planeNode.SetSizeMode(planeNode.SizeModeAbsolute)
        planeNode.SetSize(12.0, 12.0)
        speedThresholdMPerSec = 0.01

        results = {}
        for flowFieldNode in [transformFlowFieldNode, vectorVolumeFlowFieldNode]:
            kind = logic._flowFieldKind(flowFieldNode)
            self.delayDisplay(f"Analyze flow field stored in {kind}")
            outputFlowMetricsModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", f"Flow metrics {kind}")
            outputSpeedVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", f"Speed {kind}")
            outputMaskedFlowField = slicer.mrmlScene.AddNewNodeByClass(flowFieldNode.GetClassName(), f"Masked {kind}")
            logic.sampleFlowFieldWithPlane(planeNode, flowFieldNode, 2.0, None, outputFlowMetricsModel, None, None,
                100, True, False, speedThresholdMPerSec, outputSpeedVolume, False, outputMaskedFlowField)

            # A different-kind masked output is rejected
            wrongKindMaskedOutput = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Wrong kind")
            with self.assertRaises(ValueError):
                logic.sampleFlowFieldWithPlane(planeNode, flowFieldNode, 2.0, None, None, None, None,
                    100, True, False, speedThresholdMPerSec, None, False, wrongKindMaskedOutput)

            flowMetricsTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"Flow metrics table {kind}")
            summaryTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"Summary table {kind}")
            logic.computeFlowMetricsTable(outputFlowMetricsModel, planeNode, flowFieldNode, speedThresholdMPerSec,
                flowMetricsTableNode, summaryTableNode)

            metrics = {}
            table = flowMetricsTableNode.GetTable()
            for columnIndex in range(table.GetNumberOfColumns()):
                column = table.GetColumn(columnIndex)
                metrics[column.GetName()] = [column.GetValue(row) for row in range(column.GetNumberOfTuples())]
            summary = {}
            summaryTable = summaryTableNode.GetTable()
            for columnIndex in range(summaryTable.GetNumberOfColumns()):
                column = summaryTable.GetColumn(columnIndex)
                summary[column.GetName()] = column.GetValue(0)

            # Speed volume and masked flow field of the last frame
            browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
            browserNode.SetSelectedItemNumber(browserNode.GetNumberOfItems() - 1)
            speedVolumeArray = slicer.util.arrayFromVolume(outputSpeedVolume).copy()
            if outputMaskedFlowField.IsA("vtkMRMLTransformNode"):
                maskedVelocityArray = slicer.util.arrayFromGridTransform(outputMaskedFlowField).copy()
            else:
                maskedVelocityArray = slicer.util.arrayFromVolume(outputMaskedFlowField).copy()
            results[kind] = (metrics, summary, speedVolumeArray, maskedVelocityArray)

        # Sanity check against the known flow (the plane is fully inside the flow column)
        for kind, (metrics, summary, speedVolumeArray, maskedVelocityArray) in results.items():
            np.testing.assert_allclose(metrics["MeanVelocity"], [100 * speed for speed in frameSpeedsMPerSec], rtol=1e-4, err_msg=kind)
            np.testing.assert_allclose(metrics["NegativeFlowRate"], [0.0, 0.0], atol=1e-6, err_msg=kind)
            areaMm2 = metrics["Area"][0]
            self.assertGreater(areaMm2, 0.0, kind)
            np.testing.assert_allclose(metrics["FlowRate"], [speed * areaMm2 for speed in frameSpeedsMPerSec], rtol=1e-4, err_msg=kind)
            self.assertAlmostEqual(summary["PeakVelocity"], 100 * max(frameSpeedsMPerSec), places=3, msg=kind)
            self.assertAlmostEqual(speedVolumeArray.max(), frameSpeedsMPerSec[-1], places=5, msg=kind)
            # Every voxel with flow is above the speed threshold, so masking does not change the field
            np.testing.assert_allclose(maskedVelocityArray, velocityArrays[-1], atol=1e-6, err_msg=kind)

        # Both storage types must give the same results
        transformMetrics, transformSummary, transformSpeedVolume, _ = results["transform"]
        volumeMetrics, volumeSummary, volumeSpeedVolume, _ = results["volume"]
        for name in transformMetrics:
            np.testing.assert_allclose(volumeMetrics[name], transformMetrics[name], rtol=1e-5, atol=1e-6, err_msg=name)
        for name in transformSummary:
            np.testing.assert_allclose(volumeSummary[name], transformSummary[name], rtol=1e-5, atol=1e-6, err_msg=name)
        np.testing.assert_allclose(volumeSpeedVolume, transformSpeedVolume, atol=1e-6)

        self.delayDisplay("Test passed")
