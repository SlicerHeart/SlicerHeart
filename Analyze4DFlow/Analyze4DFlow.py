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

            # TODO: Experimental
            # self.unwrap(self._parameterNode.inputFlowField)

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

    @staticmethod
    def _arrayFromGridTransformToParent(gridTransformNode):
        """In slicer.util, the method works with transform _from_ parent; we need transform _to_ parent"""
        transformGrid = gridTransformNode.GetTransformToParent()
        displacementGrid = transformGrid.GetDisplacementGrid()
        nshape = tuple(reversed(displacementGrid.GetDimensions()))
        import vtk.util.numpy_support
        nshape = nshape + (3,)
        narray = vtk.util.numpy_support.vtk_to_numpy(displacementGrid.GetPointData().GetScalars()).reshape(nshape)
        return narray

    @staticmethod
    def _arrayFromGridTransformToParentModified(gridTransformNode):
        """In slicer.util, the method works with transform _from_ parent; we need transform _to_ parent"""
        transformGrid = gridTransformNode.GetTransformToParent()
        displacementGrid = transformGrid.GetDisplacementGrid()
        displacementGrid.GetPointData().GetScalars().Modified()
        displacementGrid.Modified()

    def unwrap(self, gridTransformNode: vtkMRMLTransformNode):
        """
        Unwrap the displacement field so that the displacement is continuous across the volume.
        """
        import numpy as np

        transformSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(gridTransformNode)
        if not transformSequenceBrowserNode:
            raise RuntimeError("Input transform is not in a sequence")

        try:

            # Turn off transform visibility to speed up browsing
            if gridTransformNode.GetDisplayNode():
                originalTransformVisibility = gridTransformNode.GetDisplayNode().GetVisibility()
                gridTransformNode.GetDisplayNode().SetVisibility(False)
            else:
                originalTransformVisibility = False

            originalItemNumber = transformSequenceBrowserNode.GetSelectedItemNumber()
            numberOfItems = transformSequenceBrowserNode.GetNumberOfItems()
            velocityField4d = None
            for itemNumber in range(numberOfItems):
                self.log("Unwrapping (prepare)... ({item}/{count})".format(item=itemNumber+1, count=numberOfItems))

                transformSequenceBrowserNode.SetSelectedItemNumber(itemNumber)
                displacementImageArray = Import4DFlowLogic._arrayFromGridTransformToParent(gridTransformNode)
                if velocityField4d is None:
                    velocityField4d = np.zeros([displacementImageArray.shape[0], displacementImageArray.shape[1], displacementImageArray.shape[2], numberOfItems, 3], dtype=float)
                velocityField4d[:, :, :, itemNumber] = displacementImageArray

            # Unwrap speed vectors

            # velocityField4d has its vectors in meters, so convert spacing and velocity encoding to meters

            vencCmPerSecStrList = gridTransformNode.GetAttribute("SlicerHeart.vencCmPerSec").split(',')  # list of velocity encoding, in cm/sec
            vencMeterPerSecList = [float(vencCmPerSecStr) / 100 for vencCmPerSecStr in vencCmPerSecStrList]   # velocity encoding, in m/sec

            gridTransform = gridTransformNode.GetTransformToParent()  # vtkOrientedGridTransform
            displacementImage = gridTransform.GetDisplacementGrid()
            spacingMm = displacementImage.GetSpacing()
            spacingMeter = [spacingMm[0] / 1000, spacingMm[1] / 1000, spacingMm[2] / 1000]

            frameRateFps = 1.0  # TODO: get from DICOM
            unwwrapper = Unwrapper(velocityField4d, spacingMeter, 1/frameRateFps, vencMeterPerSecList)

            # TODO: use the frame with lowest average speed (or something more sophisticated)
            temporalReferenceTimeIndex = 0  # time point that has no phase wrapping (e.g., end-diastole)
            # unwwrapper.unwrap_temporal(temporalReferenceTimeIndex) # TODO: uncomment
            velocityField4d = unwwrapper.velocity_field

            # Update transform sequence from unwrapped 4D velocity field
            for itemNumber in range(numberOfItems):
                self.log("Unwrapping (update)... ({item}/{count})".format(item=itemNumber+1, count=numberOfItems))
                transformSequenceBrowserNode.SetSelectedItemNumber(itemNumber)
                displacementImageArray = Import4DFlowLogic._arrayFromGridTransformToParent(gridTransformNode)
                displacementImageArray[:] = velocityField4d[:, :, :, itemNumber]
                Import4DFlowLogic._arrayFromGridTransformToParentModified(gridTransformNode)
                gridTransformNode.Modified()

        finally:
            # Clean up
            transformSequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)
            if originalTransformVisibility and gridTransformNode.GetDisplayNode():
                gridTransformNode.GetDisplayNode().SetVisibility(True)

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
#
# The class is based on MIT-licensed code published at:
# https://git.web.rug.nl/p305235/Phase_Unwrapping_Comparison/src/branch/main/python_code/unwrapper.py
# as supplementary material to the paper: https://onlinelibrary.wiley.com/doi/10.1002/mrm.29767
#
# 3D+t gradient-based unwrapping ("Probability" method in the implementation) is skipped due to its
# low performance and long execution time.

# {
#   "dt": 0.030,
#   "spacing": [0.25, 0.25, 0.25],
#   "VENC": 77,
#   "unwrapping": {
#     "Temporal": {
#       "apply": True,
#       "t_ref": 0,
#       "path_addon": "temporal/"
#     },
#     "lap3d": {
#       "apply": True,
#       "path_addon": "lap3d/"
#     },
#     "lap4d": {
#       "apply": True,
#       "path_addon": "lap4d/"
#     },
# }

# # Import modules here

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
    def __init__(self, velocity_field, spacing, dt, vencList):
        """
        velocity_field: 4d numpy array with dimensions (x, y, z, time, 3)
        """
        self.velocity_field = velocity_field
        self.venc = vencList
        self.dt = dt  # time step
        self.spacing = spacing

    def unwrap_laplacian(self, nd = 3):
        """
        Args (numpy array): wrapped phase
        nd: 3, 4, or 0
        Return (numpy array): unwrapped phase
        """
        import numpy as np
        vx = self.u
        phiwin = np.asarray(vx * pi / self.venc)

        si = [phiwin.shape[0], phiwin.shape[1], phiwin.shape[2], phiwin.shape[3]]
        phiw = phiwin

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

    def unwrap_temporal(self, t_ref = 0):
        """
        Unwrap with the temporal method described in Xiang, 1995. Result is stored in self.velocity_field.
        t_ref: time point index that does not have aliasing
        """
        import numpy as np

        method = "numpy"

        if method == "numpy":
            # TODO: reorder time points so that t_ref is the first
            for axis in range(3):
                self.velocity_field[:,:,:,:,axis] = np.unwrap(self.velocity_field[:,:,:,:,axis], axis=3, period=self.venc[axis])
        else:

            def wrap(u):
                ''' wraps all values of u into the interval (-pi, pi)'''
                u_array = u.copy()
                for axis in range(3):
                    u_array[u > self.venc[axis]] -= 2 * self.venc[axis]
                    u_array[u < -self.venc[axis]] += 2 * self.venc[axis]
                return u_array

            number_of_time_steps = self.velocity_field.shape[3]
            velocity_field = self.velocity_field.copy()
            for axis in range(3):
                for t in range(t_ref, number_of_time_steps-1):
                    velocity_field_diff = wrap(self.velocity_field[:,:,:,t+1,axis] - self.velocity_field[:,:,:,t,axis])
                    velocity_field[:,:,:,t+1,axis] = velocity_field[:,:,:,t,axis] + velocity_field_diff
                for t in reversed(range(0, t_ref)):
                    velocity_field_diff = wrap(self.velocity_field[:,:,:,t+1,axis] - self.velocity_field[:,:,:,t,axis])
                    velocity_field[:,:,:,t,axis] = velocity_field[:,:,:,t+1,axis] - velocity_field_diff
            self.velocity_field[:,:,:,:,:] = velocity_field

        # number_of_time_steps = self.velocity_field.shape[3]  # dimensions: x, y, z, t, 3
        # for t in range(t_ref, number_of_time_steps-2):
        #     for axis in range(3):
        #         diff = self.velocity_field[:, :, :, t+1, axis] - self.velocity_field[:, :, :, t, axis]
        #         diff = np.unwrap(diff, axis=axis, period=self.venc[axis])
        #         self.velocity_field[:, :, :, t+1, axis] = self.velocity_field[:, :, :, t, axis] + diff
        # for t in reversed(range(0, t_ref)):
        #     for axis in range(3):
        #         diff = self.velocity_field[:, :, :, t+1, axis] - self.velocity_field[:, :, :, t, axis]
        #         diff = np.unwrap(diff, axis=axis, period=self.venc[axis])
        #         self.velocity_field[:, :, :, t, axis] = self.velocity_field[:, :, :, t+1, axis] - diff


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
