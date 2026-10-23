import enum
import json
import logging
import os
from typing import Annotated, Optional, Union

import numpy as np
import qt
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
from slicer import vtkMRMLSegmentationNode

from Import4DFlowLib import FlowLibraryBridge

#
# Import4DFlow
#

class Import4DFlow(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Import 4D Flow"
        self.parent.categories = ["Cardiac"]
        self.parent.dependencies = []
        self.parent.contributors = ["Andras Lasso (PerkLab)"]
        self.parent.helpText = """
Convert 4D flow MRI phase-contrast images (Siemens CS 4D flow DICOM images) into a flow field and correct it
(phase unwrapping, noise masking, background phase correction, divergence-free filtering).

See more information in <a href="https://github.com/SlicerHeart/SlicerHeart/blob/master/Docs/Import4DFlow.md">module documentation</a>.
"""
        self.parent.acknowledgementText = """
This file was originally developed by Andras Lasso (PerkLab, Queen's University).
"""

        slicer.app.connect("startupCompleted()", self.onStartupCompleted)

    def onStartupCompleted(self):

        # Add required color table to the scene
        Import4DFlowLogic.dopplerColdToHotColorTableNode()


#
# Import4DFlowParameterNode
#

# Methods marked with (slicerheart_4dflow) are implemented in the slicerheart_4dflow Python package
# (https://github.com/JolleyLab/slicerheart_4dflow), which is installed when first used.
# Enum values are stored in the scene, so existing values must not be changed.

class UnwrapModeEnum(enum.Enum):
    TemporalUnwrap = 1
    LaplacianUnwrap = 2
    LaplacianThenTemporalUnwrap = 5
    Laplacian4DUnwrap = 4
    NoUnwrap = 3

    def label(self):
        return {
            UnwrapModeEnum.TemporalUnwrap: "temporal",
            UnwrapModeEnum.LaplacianUnwrap: "Laplacian 3D (slicerheart_4dflow)",
            UnwrapModeEnum.LaplacianThenTemporalUnwrap: "Laplacian 3D + temporal (slicerheart_4dflow)",
            UnwrapModeEnum.Laplacian4DUnwrap: "Laplacian 4D (slicerheart_4dflow)",
            UnwrapModeEnum.NoUnwrap: "none",
        }[self]

    def libraryMethod(self):
        """Method name in slicerheart_4dflow.unwrap_velocity, None if not a slicerheart_4dflow method."""
        return {
            UnwrapModeEnum.LaplacianUnwrap: "laplacian3d",
            UnwrapModeEnum.LaplacianThenTemporalUnwrap: "laplacian_then_temporal",
            UnwrapModeEnum.Laplacian4DUnwrap: "laplacian4d",
        }.get(self)

class BackgroundSubtractionMethodEnum(enum.Enum):
    NoSubtraction = 1
    LinearFit = 2
    QuadraticFit = 3
    WarMsacFit = 7
    MsacFit = 5
    WrlsFit = 6
    OlsFit = 4

    def label(self):
        return {
            BackgroundSubtractionMethodEnum.NoSubtraction: "no subtraction",
            BackgroundSubtractionMethodEnum.LinearFit: "linear fit",
            BackgroundSubtractionMethodEnum.QuadraticFit: "quadratic fit",
            BackgroundSubtractionMethodEnum.WarMsacFit: "robust fit: wrap-around rejection + MSAC (slicerheart_4dflow)",
            BackgroundSubtractionMethodEnum.MsacFit: "robust fit: MSAC (slicerheart_4dflow)",
            BackgroundSubtractionMethodEnum.WrlsFit: "robust fit: weighted least squares (slicerheart_4dflow)",
            BackgroundSubtractionMethodEnum.OlsFit: "least squares fit (slicerheart_4dflow)",
        }[self]

    def libraryMethod(self):
        """Method name in slicerheart_4dflow.correct_background_phase, None if not a slicerheart_4dflow method."""
        return {
            BackgroundSubtractionMethodEnum.WarMsacFit: "war+msac",
            BackgroundSubtractionMethodEnum.MsacFit: "msac",
            BackgroundSubtractionMethodEnum.WrlsFit: "wrls",
            BackgroundSubtractionMethodEnum.OlsFit: "ols",
        }.get(self)

class NoiseMaskMethodEnum(enum.Enum):
    MagnitudeThreshold = 1
    BockNoiseMask = 2

    def label(self):
        return {
            NoiseMaskMethodEnum.MagnitudeThreshold: "magnitude threshold",
            NoiseMaskMethodEnum.BockNoiseMask: "magnitude and velocity noise (slicerheart_4dflow)",
        }[self]

class DivergenceFilterMethodEnum(enum.Enum):
    NoFilter = 1
    FdmProjection = 2
    RelaxedProjection = 3
    LerayProjection = 4
    DivergenceFreeWavelet = 5

    def label(self):
        return {
            DivergenceFilterMethodEnum.NoFilter: "none",
            DivergenceFilterMethodEnum.FdmProjection: "finite difference projection (slicerheart_4dflow)",
            DivergenceFilterMethodEnum.RelaxedProjection: "relaxed projection (slicerheart_4dflow)",
            DivergenceFilterMethodEnum.LerayProjection: "Leray projection (slicerheart_4dflow)",
            DivergenceFilterMethodEnum.DivergenceFreeWavelet: "divergence-free wavelet denoising (slicerheart_4dflow)",
        }[self]

    def libraryMethod(self):
        """Method name in slicerheart_4dflow.divergence_free_sequence, None if no filtering."""
        return {
            DivergenceFilterMethodEnum.FdmProjection: "fdm",
            DivergenceFilterMethodEnum.RelaxedProjection: "relaxed",
            DivergenceFilterMethodEnum.LerayProjection: "leray",
            DivergenceFilterMethodEnum.DivergenceFreeWavelet: "dfw",
        }.get(self)

@parameterNodeWrapper
class Import4DFlowParameterNode:
    """
    The parameters needed by module.
    """
    # Input flow field: velocity as acquired (created from the component images or loaded from file), vector volume sequence.
    # All corrections are computed from it into the output flow field.
    inputFlowField: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode, None]
    # Output flow field (corrected velocity) is stored either in a sequence of grid transform nodes (legacy format)
    # or in a sequence of vector volume nodes (3-component image, velocity vector in each voxel)
    outputFlowField: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode, None]
    # Remove the component images after the input flow field is created from them (they are not needed after that)
    removeInputImageAfterConversion: bool = True
    # Velocity-weighted phase-contrast MR angiogram of the flow field
    pcmraVolume: Optional[vtkMRMLScalarVolumeNode]
    inputVolumeNodeSet: str
    exportDirectory: str
    exportFormat: str
    # Laplacian + temporal unwrapping is the default: temporal unwrapping alone accumulates false wraps in noisy voxels.
    # If slicerheart_4dflow is not available then temporal unwrapping is used (see Import4DFlowWidget.computePhaseUnwrapping).
    unwrapMode: Annotated[UnwrapModeEnum, Default(UnwrapModeEnum.LaplacianThenTemporalUnwrap)]
    backgroundSubtractionMethod: BackgroundSubtractionMethodEnum
    noiseMagnitudeThresholdPercent: Annotated[float, WithinRange(0.0, 50.0)] = 5.0  # magnitude image threshold to filter out background noise (speed values below this threshold are set to zero in the flow field)
    stationaryTissueSpeedThresholdVencPercent: Annotated[float, WithinRange(0.0, 50.0)] = 10.0  # speed threshold to filter out stationary tissue as percentage of venc (speed values below this threshold are set to zero in the flow field)
    temporalUnwrapReferenceFrame: int = 0  # frame number to use as reference for temporal unwrapping
    noiseMaskMethod: NoiseMaskMethodEnum
    backgroundPolynomialOrder: Annotated[int, WithinRange(1, 3)] = 2  # polynomial order of slicerheart_4dflow background fits
    backgroundPerFrame: bool = False  # fit slicerheart_4dflow background to each frame (instead of the time average)
    divergenceFilterMethod: DivergenceFilterMethodEnum
    # Vessel lumen, used by slicerheart_4dflow methods (excluded from background fitting, divergence filter region,
    # encoding check, quality report). Segment ID is stored in lumenSegmentID.
    lumenSegmentation: Optional[vtkMRMLSegmentationNode]
    lumenSegmentID: str

#
# Import4DFlowWidget
#

class Import4DFlowWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
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
        #   - 'componentVolumeNodesInvertToRasDirection': list of 3 Booleans, which tell is the component has to be inverted to get velocity RAS direction
        #   - 'magnitudeVolumeNode' magnitude volume node
        self._volumeNodesSets = {}
        self.segmentEditorSingletonTag = "Import3DFlow.SegmentEditor"

    def setup(self) -> None:
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.setup(self)

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath('UI/Import4DFlow.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Any transform or vector volume can be selected as flow field (same as in Analyze 4D Flow),
        # not only flow fields that were created by this module
        for selector in [self.ui.inputFlowFieldSelector, self.ui.outputTransformSelector]:
            selector.setNodeTypeLabel("Flow Field", "vtkMRMLTransformNode")
            selector.setNodeTypeLabel("Flow Field", "vtkMRMLVectorVolumeNode")

        segmentEditorNode = slicer.mrmlScene.GetSingletonNode(self.segmentEditorSingletonTag, "vtkMRMLSegmentEditorNode")
        if segmentEditorNode is None:
            segmentEditorNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLSegmentEditorNode")
            segmentEditorNode.SetName("Import4DFlowSegmentEditor")
            segmentEditorNode.UnRegister(None)
            segmentEditorNode.SetSingletonTag(self.segmentEditorSingletonTag)
            segmentEditorNode = slicer.mrmlScene.AddNode(segmentEditorNode)
        self.ui.segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
        self.initializeSegmentEditorNode()

        # Hide unnecessary segment editor features to simplify GUI
        if hasattr(self.ui.segmentEditorWidget, "maskingSectionVisible"):
            self.ui.segmentEditorWidget.maskingSectionVisible = False
        if hasattr(self.ui.segmentEditorWidget, "specifyGeometryButtonVisible"):
            self.ui.segmentEditorWidget.specifyGeometryButtonVisible = False
        if hasattr(self.ui.segmentEditorWidget, "show3DButtonVisible"):
            self.ui.segmentEditorWidget.show3DButtonVisible = False
        if hasattr(self.ui.segmentEditorWidget, "addRemoveSegmentButtonsVisible"):
            self.ui.segmentEditorWidget.addRemoveSegmentButtonsVisible = False

        # There should be no need to edit display settings, so hide "Switch to Segmentation" button
        self.ui.segmentEditorWidget.setSwitchToSegmentationsButtonVisible(False)

        # Only show relevant segment editor effects
        self.ui.segmentEditorWidget.setEffectNameOrder(['Flood filling', 'Paint', 'Draw', 'Erase', 'Threshold'])
        self.ui.segmentEditorWidget.unorderedEffectsVisible = False

        floodFillingEffect = self.ui.segmentEditorWidget.effectByName("Flood filling")
        if floodFillingEffect:
            if hasattr(floodFillingEffect.self(), "autoUpdateParametersFromSourceVolume"):
                floodFillingEffect.self().autoUpdateParametersFromSourceVolume = False
        else:
            logging.warning("Flood filling effect not found. Please install SegmentEditorExtraEffects extension to make 'Flood filling' effect available.")

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = Import4DFlowLogic()
        self.logic.logCallback = self.addLog

        # Export format combobox items are listed in the .ui file in the same order as in EXPORT_FORMATS
        for index, exportFormat in enumerate(self.logic.EXPORT_FORMATS):
            self.ui.exportFormatComboBox.setItemData(index, exportFormat)


        # Connections

        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        # Buttons
        self.ui.inputVolumeNodeSetSelector.connect('currentIndexChanged(int)', self.updateParameterNodeFromGUI)
        self.ui.exportPathLineEdit.connect('currentPathChanged(QString)', self.updateParameterNodeFromGUI)
        self.ui.exportFormatComboBox.connect('currentIndexChanged(int)', self.updateParameterNodeFromGUI)
        self.ui.inspectButton.connect('clicked(bool)', self.onInspectButton)
        self.ui.convertButton.connect('clicked(bool)', self.onConvertButton)
        self.ui.computePhaseUnwrappingButton.connect('clicked(bool)', self.onComputePhaseUnwrappingButton)
        self.ui.exportButton.connect('clicked(bool)', self.onExportButton)

        self.ui.showFlowFieldButton.connect('clicked(bool)', self.onShowFlowFieldButton)
        self.ui.showMagnitudeVolumeButton.connect('clicked(bool)', self.onShowMagnitudeVolumeButton)
        self.ui.showComponentVolume1Button.connect('clicked(bool)', lambda: self.onShowComponentVolumeButton(0))
        self.ui.showComponentVolume2Button.connect('clicked(bool)', lambda: self.onShowComponentVolumeButton(1))
        self.ui.showComponentVolume3Button.connect('clicked(bool)', lambda: self.onShowComponentVolumeButton(2))
        self.ui.recomputeFlowFieldButton.connect('clicked(bool)', self.onRecomputeFlowFieldButton)
        if self.developerMode:
            # Loading a test case is a developer tool, therefore it is in the developer section ("Reload & Test") at the top
            self.loadTestCaseButton = qt.QPushButton("Load test case...")
            self.loadTestCaseButton.toolTip = ("Load a 4D flow test case without DICOM import: select a case folder (inputs/<case> or"
                " outputs/<case> in the folder of a test case data set, written by the Test case export format). The input flow field,"
                " phase wrap segmentations, lumen and measurement planes are loaded, and the output flow field is computed.")
            self.loadTestCaseButton.connect('clicked(bool)', self.onLoadTestCaseButton)
            self.reloadCollapsibleButton.layout().addRow(self.loadTestCaseButton)
        self.ui.lumenSegmentSelectorWidget.connect('currentNodeChanged(vtkMRMLNode*)', self.updateParameterNodeFromGUI)
        self.ui.lumenSegmentSelectorWidget.connect('currentSegmentChanged(QString)', self.updateParameterNodeFromGUI)
        self.ui.computeLumenButton.connect('clicked(bool)', self.onComputeLumenButton)
        self.ui.computePcmraButton.connect('clicked(bool)', self.onComputePcmraButton)
        self.ui.deleteInputFlowFieldButton.connect('clicked(bool)', self.onDeleteInputFlowFieldButton)
        self.ui.magnitudeVolumeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onMagnitudeVolumeSelected)
        self.ui.checkEncodingButton.connect('clicked(bool)', self.onCheckEncodingButton)
        self.ui.computeQualityReportButton.connect('clicked(bool)', self.onComputeQualityReportButton)

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()

        self.onInspectButton()

        if slicer.app.majorVersion * 100 + slicer.app.minorVersion < 5.40:
            slicer.util.warningDisplay("This module requires Slicer-5.4 or later version for proper loading of 4D flow files from DICOM.")

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

        # Select flow fields if none is selected yet (the same way as in Analyze 4D Flow)
        if self._parameterNode:
            with slicer.util.NodeModify(self._parameterNode):
                if not self._parameterNode.inputFlowField:
                    inputFlowFieldNode = self.logic.findFirstInputFlowFieldNode()
                    if inputFlowFieldNode:
                        self._parameterNode.inputFlowField = inputFlowFieldNode
                if not self._parameterNode.outputFlowField and self._parameterNode.inputFlowField:
                    self._parameterNode.outputFlowField = self.logic.findOutputFlowFieldNode(self._parameterNode.inputFlowField)

        self.onInspectButton()

    def exit(self) -> None:
        """
        Called each time the user opens a different module.
        """
        # Do not react to parameter node changes (GUI will be updated when the user enters into the module)
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self._parameterNodeGuiTag = None
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        self.ui.segmentEditorWidget.setActiveEffect(None)

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
        self.initializeSegmentEditorNode()

    def initializeSegmentEditorNode(self):
        segmentEditorNode = slicer.mrmlScene.GetSingletonNode(self.segmentEditorSingletonTag, "vtkMRMLSegmentEditorNode")
        if segmentEditorNode:
            print("Initialize segment editor node")
            # Set up flood filling effect
            # wraparound is typically causes a large intensity difference, so we can set a large tolerance
            segmentEditorNode.SetAttribute("Flood filling.IntensityTolerance", "1000")
            # intensity difference is large enough so we don't need to prevent leaking
            # (and we want to mark very small regions), therefore there is no minimum neighborhood size
            segmentEditorNode.SetAttribute("Flood filling.NeighborhoodSizeMm", "0")
            # User may be surprised that erasing requires setting a specific segment, so erase everything by default
            segmentEditorNode.SetAttribute("Erase.EraseAllSegments", "1")

    def initializeParameterNode(self) -> None:
        """
        Ensure parameter node exists and observed.
        """
        # Parameter node stores all user choices in parameter values, node selections, etc.
        # so that when the scene is saved and reloaded, these settings are restored.

        self.setParameterNode(self.logic.getParameterNode())

    def setParameterNode(self, inputParameterNode: Optional[Import4DFlowParameterNode]) -> None:
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

        # Update node selectors and sliders
        self.ui.inputVolumeNodeSetSelector.setCurrentIndex(
            self.ui.inputVolumeNodeSetSelector.findData(self._parameterNode.inputVolumeNodeSet))

        # Update buttons state and tooltip
        if self._parameterNode and self._parameterNode.inputVolumeNodeSet:
            self.ui.convertButton.toolTip = "Convert input flow image to flow field"
            self.ui.convertButton.enabled = True
        else:
            self.ui.convertButton.toolTip = "Select a valid input flow image"
            self.ui.convertButton.enabled = False

        self.ui.lumenSegmentSelectorWidget.setCurrentNode(self._parameterNode.lumenSegmentation)
        self.ui.lumenSegmentSelectorWidget.setCurrentSegmentID(self._parameterNode.lumenSegmentID)

        # Polynomial order and per-frame fitting only apply to slicerheart_4dflow background fits
        libraryBackground = self._parameterNode.backgroundSubtractionMethod.libraryMethod() is not None
        for widget in [self.ui.backgroundPolynomialOrderLabel, self.ui.backgroundPolynomialOrderSpinBox,
                       self.ui.backgroundPerFrameLabel, self.ui.backgroundPerFrameCheckBox]:
            widget.enabled = libraryBackground
        # Stationary tissue speed threshold only applies to SlicerHeart background fits
        slicerHeartBackground = self._parameterNode.backgroundSubtractionMethod in (BackgroundSubtractionMethodEnum.LinearFit, BackgroundSubtractionMethodEnum.QuadraticFit)
        self.ui.label_6.enabled = slicerHeartBackground
        self.ui.stationaryTissueSpeedThresholdSlider.enabled = slicerHeartBackground

        # Corrections, phase wrap editing, and the quality report require an input flow field (velocity as acquired);
        # PC-MRA and lumen estimation require the magnitude images. Other flow fields (for example velocity vector volumes
        # loaded from file) can still be checked and exported.
        inputFlowFieldNode = self._parameterNode.inputFlowField
        outputFlowFieldNode = self._parameterNode.outputFlowField
        flowFieldNode = self._flowField()
        hasInput = inputFlowFieldNode is not None
        hasMagnitudeImage = flowFieldNode is not None and flowFieldNode.GetNodeReference("magnitudeVolume") is not None
        self.ui.deleteInputFlowFieldButton.enabled = hasInput
        # Magnitude image of the input flow field (stored in its magnitudeVolume reference)
        wasBlocked = self.ui.magnitudeVolumeSelector.blockSignals(True)
        self.ui.magnitudeVolumeSelector.setCurrentNode(inputFlowFieldNode.GetNodeReference("magnitudeVolume") if hasInput else None)
        self.ui.magnitudeVolumeSelector.blockSignals(wasBlocked)
        self.ui.magnitudeVolumeSelector.enabled = hasInput
        for widget in [self.ui.recomputeFlowFieldButton, self.ui.computePhaseUnwrappingButton, self.ui.showComponentVolume1Button,
                       self.ui.showComponentVolume2Button, self.ui.showComponentVolume3Button]:
            widget.enabled = hasInput
        self.ui.showMagnitudeVolumeButton.enabled = hasMagnitudeImage
        self.ui.showFlowFieldButton.enabled = flowFieldNode is not None
        for button in [self.ui.computeLumenButton, self.ui.computePcmraButton]:
            button.enabled = hasMagnitudeImage
        self.ui.computeQualityReportButton.enabled = hasInput and outputFlowFieldNode is not None
        self.ui.checkEncodingButton.enabled = flowFieldNode is not None
        self.ui.exportButton.enabled = flowFieldNode is not None

        self.ui.exportPathLineEdit.setCurrentPath(self._parameterNode.exportDirectory)
        exportFormatIndex = self.ui.exportFormatComboBox.findData(self._parameterNode.exportFormat)
        self.ui.exportFormatComboBox.setCurrentIndex(exportFormatIndex if exportFormatIndex >= 0 else 0)

        directionCodes = FlowLibraryBridge.directionCodes(inputFlowFieldNode) if inputFlowFieldNode else [f"C{c + 1}" for c in range(3)]
        for component in range(3):
            getattr(self.ui, f"showComponentVolume{component+1}Button").text = directionCodes[component] or f"C{component + 1}"

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
            volumeNodeSet = self.ui.inputVolumeNodeSetSelector.currentData
            self._parameterNode.inputVolumeNodeSet = volumeNodeSet if volumeNodeSet else ""
            self._parameterNode.exportDirectory = self.ui.exportPathLineEdit.currentPath
            self._parameterNode.exportFormat = self.ui.exportFormatComboBox.currentData
            self._parameterNode.lumenSegmentation = self.ui.lumenSegmentSelectorWidget.currentNode()
            self._parameterNode.lumenSegmentID = self.ui.lumenSegmentSelectorWidget.currentSegmentID() or ""


    def onInspectButton(self) -> None:
        self._volumeNodesSets = self.logic.findVolumeNodeSets()
        self.ui.inputVolumeNodeSetSelector.clear()
        if self._volumeNodesSets:
            for volumeNodeSet in self._volumeNodesSets:
                self.ui.inputVolumeNodeSetSelector.addItem(self._volumeNodesSets[volumeNodeSet]["name"], volumeNodeSet)
            self.ui.inputVolumeNodeSetSelector.enabled = True
        else:
            self.ui.inputVolumeNodeSetSelector.addItem("(Not found in the scene)")
            self.ui.inputVolumeNodeSetSelector.setToolTip("No Siemens CS 4D flow found in the scene that could be converted to flow field.")
            self.ui.inputVolumeNodeSetSelector.enabled = False


    def onConvertButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to convert image to flow field.", waitCursor=True):
            volumeNodeSet = self._volumeNodesSets[self._parameterNode.inputVolumeNodeSet]
            inputFlowFieldNode = self.logic.createInputFlowFieldFromComponentVolumes(
                volumeNodeSet["componentVolumeNodes"], volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"])
            if self._parameterNode.removeInputImageAfterConversion:
                self.logic.removeComponentVolumes(volumeNodeSet["componentVolumeNodes"])
            with slicer.util.NodeModify(self._parameterNode):
                self._parameterNode.inputFlowField = inputFlowFieldNode
                self._parameterNode.outputFlowField = None
            # Compute the output flow field with the selected corrections (phase unwrapping is computed for the new flow field)
            outputFlowFieldNode = self._requireOutputFlowField()
            self.updateFlowField(outputFlowFieldNode)
            self.logic.setFlowFieldVisualizationToDefault(outputFlowFieldNode)
            browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(outputFlowFieldNode)
            slicer.modules.sequences.toolBar().setActiveBrowserNode(browserNode)
            self.onInspectButton()
            self.updateGUIFromParameterNode()

    def _flowField(self):
        """Flow field to show and check: the output flow field, or the input flow field if there is no output flow field."""
        return self._parameterNode.outputFlowField or self._parameterNode.inputFlowField

    def _requireInputFlowField(self):
        inputFlowFieldNode = self._parameterNode.inputFlowField
        if not inputFlowFieldNode:
            raise RuntimeError("Select an input flow field")
        if not FlowLibraryBridge.isRawFlowField(inputFlowFieldNode):
            # Flow field created by an earlier version of this module (references the component images)
            # or a velocity field loaded from file
            rawFlowFieldNode = self.logic.ensureInputFlowField(inputFlowFieldNode)
            if rawFlowFieldNode is None:
                rawFlowFieldNode = self.logic.markAsInputFlowField(inputFlowFieldNode)
            if rawFlowFieldNode is not inputFlowFieldNode:
                with slicer.util.NodeModify(self._parameterNode):
                    self._parameterNode.outputFlowField = inputFlowFieldNode
                    self._parameterNode.inputFlowField = rawFlowFieldNode
            inputFlowFieldNode = rawFlowFieldNode
        return inputFlowFieldNode

    def _requireOutputFlowField(self):
        """Output flow field of the input flow field: the selected one, or a new one (with phase unwrapping computed)."""
        inputFlowFieldNode = self._requireInputFlowField()
        outputFlowFieldNode = self._parameterNode.outputFlowField
        if outputFlowFieldNode is not None and outputFlowFieldNode.GetNodeReference("inputFlowField") is not inputFlowFieldNode:
            if outputFlowFieldNode.GetNodeReference("inputFlowField") is None and outputFlowFieldNode is not inputFlowFieldNode \
                    and not FlowLibraryBridge.isRawFlowField(outputFlowFieldNode) and outputFlowFieldNode.IsA("vtkMRMLVectorVolumeNode"):
                # Selected output flow field is not computed from an input flow field yet: compute it from the selected input
                outputFlowFieldNode.SetNodeReferenceID("inputFlowField", inputFlowFieldNode.GetID())
            else:
                outputFlowFieldNode = None
        if outputFlowFieldNode is not None and self.logic.isFlowFieldStoredInTransform(outputFlowFieldNode):
            # Flow fields stored in transforms (legacy format) can be read but not written
            outputFlowFieldNode = None
        if outputFlowFieldNode is None or outputFlowFieldNode is inputFlowFieldNode:
            outputFlowFieldNode = self.logic.createOutputFlowField(inputFlowFieldNode, name=slicer.mrmlScene.GenerateUniqueName("FlowField"))
            self._parameterNode.outputFlowField = outputFlowFieldNode
            self.computePhaseUnwrapping(outputFlowFieldNode)
        return outputFlowFieldNode

    def computePhaseUnwrapping(self, flowFieldNode) -> None:
        """Compute phase unwrapping map with the unwrapping method selected in the parameter node.
        If a slicerheart_4dflow method is selected but the package cannot be installed then temporal unwrapping is used.
        A warning is displayed if the unwrapped velocity is implausible."""
        unwrapMode = self._parameterNode.unwrapMode
        if unwrapMode.libraryMethod():
            try:
                FlowLibraryBridge.ensureLibrary()
            except Exception as e:
                logging.warning(f"{unwrapMode.label()} is not available ({e}), temporal unwrapping is used instead")
                slicer.util.showStatusMessage("slicerheart_4dflow is not available, temporal unwrapping is used", 5000)
                unwrapMode = UnwrapModeEnum.TemporalUnwrap
        if unwrapMode == UnwrapModeEnum.TemporalUnwrap:
            warnings = self.logic.temporalUnwrap(flowFieldNode, self._parameterNode.temporalUnwrapReferenceFrame, self._parameterNode.noiseMagnitudeThresholdPercent)
        elif unwrapMode.libraryMethod():
            warnings = self.logic.laplacianUnwrap(flowFieldNode, unwrapMode, self._parameterNode.noiseMagnitudeThresholdPercent, self._parameterNode.noiseMaskMethod)
        else:
            self.logic.resetUnwrap(flowFieldNode)
            warnings = []
        if warnings and not slicer.app.testingEnabled():
            slicer.util.warningDisplay("\n\n".join(warnings), windowTitle="Phase unwrapping")

    def lumenMask(self, flowFieldNode):
        return self.logic.getLumenMask(flowFieldNode, self._parameterNode.lumenSegmentation, self._parameterNode.lumenSegmentID)

    def updateFlowField(self, flowFieldNode) -> None:
        """Compute the output flow field from its input flow field with the correction methods selected in the parameter node."""
        self.logic.computeOutputFlowField(
            flowFieldNode,
            self._parameterNode.noiseMagnitudeThresholdPercent,
            self._parameterNode.backgroundSubtractionMethod,
            self._parameterNode.stationaryTissueSpeedThresholdVencPercent,
            noiseMaskMethod=self._parameterNode.noiseMaskMethod,
            backgroundPolynomialOrder=self._parameterNode.backgroundPolynomialOrder,
            backgroundPerFrame=self._parameterNode.backgroundPerFrame,
            divergenceFilterMethod=self._parameterNode.divergenceFilterMethod,
            lumenMask=self.lumenMask(flowFieldNode))

    def onComputePhaseUnwrappingButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to compute phase unwrapping.", waitCursor=True):
            outputFlowFieldNode = self._parameterNode.outputFlowField
            isNewOutput = outputFlowFieldNode is None or outputFlowFieldNode.GetNodeReference("inputFlowField") is not self._parameterNode.inputFlowField
            outputFlowFieldNode = self._requireOutputFlowField()
            if not isNewOutput:  # phase unwrapping is computed for new output flow fields
                self.computePhaseUnwrapping(outputFlowFieldNode)


    def onShowFlowFieldButton(self) -> None:
        flowFieldNode = self._flowField()
        displayNode = self.logic.getFlowFieldDisplayNode(flowFieldNode)
        if not displayNode:
            # Flow vectors have never been shown for this flow field
            self.logic.setFlowFieldVisualizationToDefault(flowFieldNode)
            return
        displayNode.SetVisibility(not displayNode.GetVisibility())

    def onShowMagnitudeVolumeButton(self) -> None:
        slicer.util.setSliceViewerLayers(background=self._flowField().GetNodeReference("magnitudeVolume"))
        self.setSegmentationVisibility(True)

    def onShowComponentVolumeButton(self, component) -> None:
        """Show an encoded velocity component of the input flow field (velocity as acquired) with its phase wrap
        segmentation, and set them up in the segment editor for manual phase wrap correction."""
        with slicer.util.tryWithErrorDisplay("Failed to show velocity component.", waitCursor=True):
            inputFlowFieldNode = self._requireInputFlowField()
            componentVolume = self.logic.getRawComponentVolume(inputFlowFieldNode, component)
            slicer.util.setSliceViewerLayers(background=componentVolume)
            self.setSegmentationVisibility(False)
            self.setSegmentationVisibility(True, component)
            outputFlowFieldNode = self._parameterNode.outputFlowField
            segmentation = outputFlowFieldNode.GetNthNodeReference("phaseWrapSegmentation", component) if outputFlowFieldNode else None
            if segmentation:
                self.ui.segmentEditorWidget.setSegmentationNode(segmentation)
                self.ui.segmentEditorWidget.setSourceVolumeNode(componentVolume)

    def setSegmentationVisibility(self, visibility, component=-1):
        outputFlowFieldNode = self._parameterNode.outputFlowField
        if not outputFlowFieldNode:
            return
        for currentComponent in range(3):
            if (component >= 0 and currentComponent != component):
                continue
            segmentation = outputFlowFieldNode.GetNthNodeReference("phaseWrapSegmentation", currentComponent)
            if not segmentation:
                continue
            segmentation.GetDisplayNode().SetVisibility(visibility)

    def onRecomputeFlowFieldButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to recompute flow field.", waitCursor=True):
            self.updateFlowField(self._requireOutputFlowField())

    def _requireFlowField(self):
        flowFieldNode = self._flowField()
        if not flowFieldNode:
            raise RuntimeError("Select a flow field")
        return flowFieldNode

    def onMagnitudeVolumeSelected(self, magnitudeVolumeNode) -> None:
        if self._updatingGUIFromParameterNode or not self._parameterNode or not self._parameterNode.inputFlowField:
            return
        if magnitudeVolumeNode is self._parameterNode.inputFlowField.GetNodeReference("magnitudeVolume"):
            return
        with slicer.util.tryWithErrorDisplay("Failed to set the magnitude image of the input flow field.", waitCursor=True):
            try:
                self.logic.setMagnitudeVolume(self._requireInputFlowField(), magnitudeVolumeNode)
            finally:
                self.updateGUIFromParameterNode()

    def onDeleteInputFlowFieldButton(self) -> None:
        inputFlowFieldNode = self._parameterNode.inputFlowField
        if not inputFlowFieldNode:
            return
        if not slicer.app.testingEnabled() and not slicer.util.confirmOkCancelDisplay(
                f"Delete the input flow field '{inputFlowFieldNode.GetName()}' (velocity as acquired)?"
                " Output flow fields that were computed from it cannot be recomputed after this.", windowTitle="Delete input flow field"):
            return
        with slicer.util.tryWithErrorDisplay("Failed to delete input flow field.", waitCursor=True):
            self._parameterNode.inputFlowField = None
            self.logic.deleteFlowField(inputFlowFieldNode)

    def onComputeLumenButton(self) -> None:
        """Compute the lumen segmentation into the selected segment (overwritten); a new segmentation or segment is created
        (and selected) if none is selected."""
        with slicer.util.tryWithErrorDisplay("Failed to compute lumen segmentation.", waitCursor=True):
            segmentationNode, segmentId, lumen = self.logic.createLumenSegmentation(self._requireFlowField(), self._parameterNode.lumenSegmentation,
                                                                                    self._parameterNode.lumenSegmentID or None, returnEstimate=True)
            with slicer.util.NodeModify(self._parameterNode):
                self._parameterNode.lumenSegmentation = segmentationNode
                self._parameterNode.lumenSegmentID = segmentId
            message = "Lumen segmentation is computed from the flow field."
            if not lumen["grownToWall"]:
                message += (f" It is not grown toward the vessel wall ({lumen['growthSkippedReason']}), only the PC-MRA threshold"
                            " is used, which may be inside the vessel wall.")
            self.ui.qualityReportTextBrowser.setPlainText(message + " Review and edit it in Segment Editor before using it for measurements.")

    def onComputePcmraButton(self) -> None:
        """Compute the PC-MRA into the selected volume (overwritten); a new volume is created (and selected) if none is selected."""
        with slicer.util.tryWithErrorDisplay("Failed to compute PC-MRA volume.", waitCursor=True):
            pcmraVolumeNode = self.logic.createPcmraVolume(self._requireFlowField(), self._parameterNode.pcmraVolume)
            self._parameterNode.pcmraVolume = pcmraVolumeNode
            slicer.util.setSliceViewerLayers(background=pcmraVolumeNode, fit=True)

    def onCheckEncodingButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to check encoding directions.", waitCursor=True):
            flowFieldNode = self._requireFlowField()
            result = self.logic.checkEncodingDirections(flowFieldNode, self.lumenMask(flowFieldNode))
            summary = self.logic.encodingCheckSummary(result)
            self.ui.qualityReportTextBrowser.setPlainText(summary)
            if not result["consistent"] and not slicer.app.testingEnabled():
                slicer.util.warningDisplay(summary, windowTitle="Velocity encoding check")

    def onComputeQualityReportButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to compute quality report.", waitCursor=True):
            flowFieldNode = self._requireFlowField()
            report = self.logic.computeQualityReport(flowFieldNode, self.lumenMask(flowFieldNode))
            self.ui.qualityReportTextBrowser.setMarkdown(self.logic.qualityReportToMarkdown(report))
            tableName = f"{flowFieldNode.GetName()} quality report"
            tableNode = slicer.mrmlScene.GetFirstNodeByName(tableName)
            if not tableNode:
                tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", tableName)
            self.logic.qualityReportToTable(report, tableNode)

    def onLoadTestCaseButton(self) -> None:
        caseDirectory = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(),
            "Select the folder of the test case (inputs/<case> in the folder of the data set)",
            self._parameterNode.exportDirectory or slicer.mrmlScene.GetRootDirectory())
        if not caseDirectory:
            return
        try:
            datasetDirectory, caseId = Import4DFlowLogic.testCaseFromDirectory(caseDirectory)
        except ValueError as e:
            slicer.util.errorDisplay(f"Failed to load test case: {e}")
            return
        self.loadTestCase(datasetDirectory, caseId)

    def loadTestCase(self, datasetDirectory, caseId):
        with slicer.util.tryWithErrorDisplay("Failed to load test case.", waitCursor=True):
            loaded = self.logic.loadTestCase(datasetDirectory, caseId)
            flowFieldNode = loaded["flowFieldNode"]
            self.logic.setFlowFieldVisualizationToDefault(flowFieldNode)
            browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
            slicer.modules.sequences.toolBar().setActiveBrowserNode(browserNode)
            with slicer.util.NodeModify(self._parameterNode):
                self._parameterNode.inputFlowField = loaded["inputFlowFieldNode"]
                self._parameterNode.outputFlowField = flowFieldNode
                if loaded["lumenSegmentationNode"]:
                    segmentation = loaded["lumenSegmentationNode"].GetSegmentation()
                    self._parameterNode.lumenSegmentation = loaded["lumenSegmentationNode"]
                    self._parameterNode.lumenSegmentID = segmentation.GetSegmentIdBySegmentName("lumen") or segmentation.GetNthSegmentID(0)
                self.setProcessingParametersFromFlowField(flowFieldNode)
            slicer.util.setSliceViewerLayers(background=loaded["magnitudeVolumeNode"], fit=True)
            return loaded

    def setProcessingParametersFromFlowField(self, flowFieldNode):
        """Set the correction settings in the GUI to those the flow field was computed with (SlicerHeart.processing
        attribute), so that recomputing it reproduces it. Settings that are not recorded are left unchanged."""
        sequenceNode = self.logic._getSequenceFromProxyNode(flowFieldNode)
        processing = json.loads((sequenceNode.GetAttribute("SlicerHeart.processing") if sequenceNode else None) or "{}")
        enumParameters = {"noiseMask": ("noiseMaskMethod", NoiseMaskMethodEnum),
                          "backgroundSubtraction": ("backgroundSubtractionMethod", BackgroundSubtractionMethodEnum),
                          "divergenceFilter": ("divergenceFilterMethod", DivergenceFilterMethodEnum),
                          "phaseUnwrapping": ("unwrapMode", UnwrapModeEnum)}
        valueParameters = {"noiseMagnitudeThresholdPercent": float, "stationaryTissueSpeedThresholdVencPercent": float,
                           "backgroundPolynomialOrder": int, "backgroundPerFrame": bool}
        with slicer.util.NodeModify(self._parameterNode):
            for key, (parameterName, enumClass) in enumParameters.items():
                if processing.get(key) in enumClass.__members__:
                    setattr(self._parameterNode, parameterName, enumClass[processing[key]])
            for key, valueType in valueParameters.items():
                if processing.get(key) is not None:
                    setattr(self._parameterNode, key, valueType(processing[key]))


    def askTestCaseId(self, datasetDirectory):
        """Ask the ID of a new test case of the data set (an anonymized identifier: it is the name of the case folders).
        Returns the ID, or None if canceled."""
        caseId = qt.QInputDialog.getText(slicer.util.mainWindow(), "Export test case",
            "Case ID (anonymized identifier, the name of the case folders in the data set):", qt.QLineEdit.Normal,
            Import4DFlowLogic.nextTestCaseId(datasetDirectory))
        caseId = caseId.strip() if caseId else ""
        return caseId or None

    def onExportButton(self) -> None:
        if not self._parameterNode.exportDirectory:
            self.ui.exportPathLineEdit.setCurrentPath(slicer.mrmlScene.GetRootDirectory())
            slicer.app.processEvents()

        success = False
        with slicer.util.tryWithErrorDisplay("Failed to export the flow field to files.", waitCursor=True):
            if self._parameterNode.exportFormat == Import4DFlowLogic.EXPORT_FORMAT_TEST_CASE:
                # The export folder is the folder of the data set; the case is added to it
                caseId = self.askTestCaseId(self._parameterNode.exportDirectory)
                if not caseId:
                    return
                self.logic.exportTestCaseWithFlows(self._requireFlowField(), self._parameterNode.exportDirectory, caseId,
                    lumenSegmentationNode=self._parameterNode.lumenSegmentation, lumenSegmentId=self._parameterNode.lumenSegmentID)
            else:
                self.logic.exportDisplacementFieldToFiles(self._requireFlowField(), self._parameterNode.exportDirectory, self._parameterNode.exportFormat)
            success = True
        if success:
            slicer.util.infoDisplay("Export successfully completed.")


#
# Import4DFlowLogic
#

class Import4DFlowLogic(ScriptedLoadableModuleLogic):
    """This class should implement all the actual
    computation done by your module.  The interface
    should be such that other python code can import
    this class and make use of the functionality without
    requiring an instance of the Widget.
    Uses ScriptedLoadableModuleLogic base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    EXPORT_FORMAT_ANONYMIZED_SCENE = "ANONYMIZED_SCENE"
    EXPORT_FORMAT_NRRD_STACK = "NRRD_STACK"
    EXPORT_FORMAT_NRRD_5D = "NRRD_5D"
    EXPORT_FORMAT_TEST_CASE = "TEST_CASE"
    # Value of the "SlicerHeart.Type" attribute of input flow fields (velocity as acquired). Output flow fields (processing
    # results) are "FlowField", so that Analyze 4D Flow selects them, not the input flow field.
    RAW_FLOW_FIELD_TYPE = "RawFlowField"
    # All export formats, in the order they are listed in the module GUI
    EXPORT_FORMATS = [EXPORT_FORMAT_ANONYMIZED_SCENE, EXPORT_FORMAT_NRRD_STACK, EXPORT_FORMAT_NRRD_5D, EXPORT_FORMAT_TEST_CASE]
    DOPPLER_COLD_TO_HOT_SINGLETON_TAG = "SlicerHeart.DopplerColdToHot"

    def __init__(self) -> None:
        """
        Called when the logic class is instantiated. Can be used for initializing member variables.
        """
        ScriptedLoadableModuleLogic.__init__(self)

        self.logCallback = None

        # Converts direction code (in the DICOM header) to axis index (L, P, S)
        # rl: right-left, ap: anterior-posterior, fh: foot-head
        # For each configuration: list of (directionCode, invertToRasDirection) triplets (one for each axis).
        # invertToRasDirection is True if the direction should be inverted to convert to RAS coordinate system.
        self.axisForDirectionCodes = [
            [("through", True), ("inplane_ap", True), ('inplane_fh', False)],
            [("inplane_rl", False), ("through", True), ('inplane_fh', False)],
            # We have not encountered the following configuration yet, but based on the first two cases (observed in real data sets) it seems possible.
            # Need to verify the invertToRasDirection flags.
            [("inplane_rl", True), ("inplane_ap", True), ('through', False)],
        ]

        # Converts direction code in the SequenceName DICOM field (for example, "in" in "fl3d1_v150in")
        # to direction code used in the private DICOM tag (for example, "through" in "v150_through").
        self.sequenceNameDirectionCodes = {"in": "through", "rl": "inplane_rl", "ap": "inplane_ap", "fh": "inplane_fh"}

        # for current Siemens CS4D flow images this can be hardcoded
        self.magnitudeVolumeRange = 255
        self.componentVolumeMaxValueSiemensCS4DFlow = 4096

        self.maxWraps = 3

        self.dopplerLutRange = [-2, 2]
        self.dopplerLutThreshold = [-0.25, 0.25]

        # Use positive side of the Doppler color table for absolute speed
        # Set to false, because the multicolor colormap can better distinguish speed differences.
        self.useDopplerColorTableForAbsoluteSpeed = False

    def _log(self, message):
        logging.info(message)
        if self.logCallback:
            self.logCallback(message)

    @staticmethod
    def dopplerColdToHotColorTableNode():

        dopplerColdToHotColorTableNode = slicer.mrmlScene.GetSingletonNode(Import4DFlowLogic.DOPPLER_COLD_TO_HOT_SINGLETON_TAG, "vtkMRMLColorTableNode")
        if dopplerColdToHotColorTableNode:
            # already registered
            return dopplerColdToHotColorTableNode

        node = slicer.vtkMRMLColorTableNode()
        node.SetTypeToFile()
        # Do not save the color table to the scene file, assume that the Import4DFlow module provides it
        node.SaveWithSceneOff()
        node.HideFromEditorsOn()
        node.SetAttribute("Category", "Flow")
        node.SetAttribute("SlicerHeart.ColorMappingType", "SpeedComponent")
        node.SetSingletonTag(Import4DFlowLogic.DOPPLER_COLD_TO_HOT_SINGLETON_TAG)
        node.SetName("DopplerColdToHot")
        node = slicer.mrmlScene.AddNode(node)

        colorStorageNode = slicer.vtkMRMLColorTableStorageNode()
        colorStorageNode.SaveWithSceneOn()
        slicer.mrmlScene.AddNode(colorStorageNode)
        node.SetAndObserveStorageNodeID(colorStorageNode.GetID())

        resourcesPath = os.path.join(os.path.dirname(__file__), "Resources")
        colorTableFilePath = os.path.join(resourcesPath, "DopplerColdToHot.ctbl")
        colorStorageNode.SetFileName(colorTableFilePath)

        if colorStorageNode.ReadData(node) == 0:
            raise ValueError(f"Failed to read DopplerColdToHot color table from file {colorTableFilePath}")

        # Force creation of a new default storage node (do not overwrite the file in the extension)
        node.SetAndObserveStorageNodeID(None)
        slicer.mrmlScene.RemoveNode(colorStorageNode)

        return node


    def log(self, text):
        logging.info(text)
        if self.logCallback:
            self.logCallback(text)

    def getParameterNode(self):
        return Import4DFlowParameterNode(super().getParameterNode())

    def _getNumberOfDataNodesInSequence(self, proxyVolumeNode):
        volumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(proxyVolumeNode)
        if not volumeSequenceBrowserNode:
            # not a proxy node of a sequence
            return 1
        volumeSequenceNode = volumeSequenceBrowserNode.GetSequenceNode(proxyVolumeNode)
        return volumeSequenceNode.GetNumberOfDataNodes()

    def _getSequenceFromProxyNode(self, proxyNode):
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(proxyNode)
        if not browserNode:
            raise RuntimeError(f"Volume {proxyNode.GetName()} is expected to be proxy node of a volume sequence")
        sequenceNode = browserNode.GetSequenceNode(proxyNode)
        return sequenceNode

    def _findVolumeNodeSetCandidatesInScene(self):
        import pydicom
        import re
        import traceback

        # Velocity encoding and direction code at the end of SequenceName, for example "150" and "in" in "fl3d1_v150in"
        sequenceNameComponentPattern = r"_v(\d+(?:\.\d+)?)(in|rl|ap|fh)$"

        volumeNodesSets = {}
        unsortedVolumeNodes = slicer.util.getNodesByClass('vtkMRMLScalarVolumeNode')
        for volumeNode in unsortedVolumeNodes:
            try:
                instUidsStr = volumeNode.GetAttribute("DICOM.instanceUIDs")
                if not instUidsStr:
                    # not loaded from DICOM
                    logging.debug(f"{volumeNode.GetName()} has no DICOM.instanceUIDs - skip")
                    continue
                instUids = instUidsStr.split()
                filename = slicer.dicomDatabase.fileForInstance(instUids[0])
                if not filename:
                    # DICOM files are not in the Slicer DICOM database
                    logging.debug(f"{volumeNode.GetName()} is not found in the DICOM database - skip")
                    continue
                ds = pydicom.dcmread(filename)

                # Find DICOM tag that stores speedAndDirectionCode.
                # On Siemens Avanto, it is (0x0051,0x1014), on newer Siemens Avanto Fit, it is (0x0021,0x1129).
                speedAndDirectionCodeTag = None
                for tag in [(0x0051,0x1014), (0x0021,0x1129)]:
                    if tag in ds:
                        speedAndDirectionCodeTag = tag
                        break

                # Get heart rate information if available
                try:
                    heartRateBpm = 60000.0 / float(ds["NominalInterval"].value)
                except Exception:
                    heartRateBpm = None

                if speedAndDirectionCodeTag:
                    # flow vector component image
                    try:
                        speedAndDirectionCode = ds[speedAndDirectionCodeTag].value.decode().strip()
                    except AttributeError:
                        speedAndDirectionCode = ds[speedAndDirectionCodeTag].value.strip()
                    vencCmPerSecInput, directionCodeInput = speedAndDirectionCode.split('_', 1)
                    vencCmPerSec = float(vencCmPerSecInput[1:])
                    directionCode = directionCodeInput.strip()
                    logging.debug(f"Found a flow vector component image candidate [{directionCode}]: {volumeNode.GetName()}")
                    # The tag contains speed and direction, for example:
                    # 'v150_through', 'v150_inplane_ap', 'v150_inplane_fh'
                    volumeSequenceNode = self._getSequenceFromProxyNode(volumeNode)
                    volumeSequenceNode.SetAttribute("SlicerHeart.vencCmPerSec", str(vencCmPerSec))  # velocity encoding, in cm/sec
                    volumeSequenceNode.SetAttribute("SlicerHeart.maxValue", str(self.componentVolumeMaxValueSiemensCS4DFlow))
                elif ("SequenceName" in ds) and re.search(sequenceNameComponentPattern, ds["SequenceName"].value.strip()):
                    # component image (contain speed specification)
                    # Examples: 'fl3d1_v150in', 'fl3d1_v150ap', 'fl3d1_v150fh', 'WIP_f_v150fh'
                    # In freerunning flow sequence, all the directions may be under the same series
                    logging.debug(f"Found a flow vector component image candidate: {volumeNode.GetName()}")
                    match = re.search(sequenceNameComponentPattern, ds["SequenceName"].value.strip())
                    vencCmPerSec = float(match.group(1))
                    # Convert to the same direction codes as used in the private tag (and axisForDirectionCodes)
                    directionCode = self.sequenceNameDirectionCodes[match.group(2)]
                    volumeSequenceNode = self._getSequenceFromProxyNode(volumeNode)
                    volumeSequenceNode.SetAttribute("SlicerHeart.vencCmPerSec", str(vencCmPerSec))  # velocity encoding, in cm/sec
                    volumeSequenceNode.SetAttribute("SlicerHeart.maxValue", str(self.componentVolumeMaxValueSiemensCS4DFlow))
                elif ("SequenceName" in ds) and (('fl3d1r2' in ds["SequenceName"].value) or ('fl3d1r3' in ds["SequenceName"].value)):
                    # magnitude image
                    # Examples: '*fl3d1r2' or 'fl3d1r2' or 'WIP_fl3d1r2' or 'WIP_fl3d1r3'
                    logging.debug(f"Found an magnitude image candidate: {volumeNode.GetName()}")
                    directionCode = 'magnitude'
                else:
                    # something else
                    logging.debug(f"Unknown image: {volumeNode.GetName()} - skip")
                    continue
            except Exception as e:
                # error accessing DICOM fields
                logging.debug(f"Error while processing image: {volumeNode.GetName()} - skip")
                print(traceback.format_exc())
                continue

            studyInstanceUID = ds["StudyInstanceUID"].value.strip()
            acquisitionNumber = ds["AcquisitionNumber"].value

            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            studyShItemId = shNode.GetItemParent(shNode.GetItemByDataNode(volumeNode))
            # use studyShItemId to ensure unique acquisitionID even if the same study is loaded multiple times
            acquisitionID = f"{studyShItemId}-{studyInstanceUID}/{acquisitionNumber}"

            if acquisitionID not in volumeNodesSets:
                acquisitionNumberSuffix =  f" / {acquisitionNumber}" if acquisitionNumber > 1 else ""
                volumeNodeSet = {
                    'name': f"{ds.PatientName.family_comma_given()} ({ds.StudyDate}){acquisitionNumberSuffix}",
                    'candidateVolumeNodes': [],  # list of potential component or magnitude volume nodes - there may be several candidates in the study
                    }
                volumeNodesSets[acquisitionID] = volumeNodeSet

            volumeSequenceNode = self._getSequenceFromProxyNode(volumeNode)
            volumeSequenceNode.SetAttribute("SlicerHeart.directionCode", directionCode)
            if heartRateBpm:
                volumeSequenceNode.SetAttribute("SlicerHeart.heartRateBpm", str(heartRateBpm))
            volumeNodesSets[acquisitionID]['candidateVolumeNodes'].append(volumeNode)

        return volumeNodesSets

    def _getSequenceAttribute(self, proxyNode, attributeName):
        sequenceNode = self._getSequenceFromProxyNode(proxyNode)
        return sequenceNode.GetAttribute(attributeName)

    def _findComponentVolumeNodes(self, volumeNodesSet):
        """
        Returns a list of 3 volume nodes (x, y, z) and for each if the component values need to be reversed (ix, iy, iz).
        If not found, then returns (None, None).
        """
        # Find if there is a axisForDirectionCode mapping which has a corresponding volume
        # for each component
        for axisForDirectionCode in self.axisForDirectionCodes:
            componentVolumeNodes = [None, None, None]
            invertToRasDirections = [False, False, False]
            # axisForDirectionCode example: [("through", True), ("inplane_ap", True), ('inplane_fh', False)]
            for axis, (directionCode, invertToRasDirection) in enumerate(axisForDirectionCode):
                for volumeNode in volumeNodesSet['candidateVolumeNodes']:
                    if self._getSequenceAttribute(volumeNode, "SlicerHeart.directionCode") == directionCode:
                        # Found a volume for this direction
                        componentVolumeNodes[axis] = volumeNode
                        invertToRasDirections[axis] = invertToRasDirection
                        break
            if not all(componentVolumeNodes):
                continue

            # Check if number of frames is consistent across component volumes
            numberOfFrames = None
            valid = True
            for axis in range(len(componentVolumeNodes)):
                if numberOfFrames is None:
                    numberOfFrames = self._getNumberOfDataNodesInSequence(componentVolumeNodes[axis])
                else:
                    currentNumberOfFrames = self._getNumberOfDataNodesInSequence(componentVolumeNodes[axis])
                    if currentNumberOfFrames != numberOfFrames:
                        logging.warning(f"Volumes {[volumeNode.GetName() for volumeNode in componentVolumeNodes]} in node set {volumeNodesSet['name']} are discarded: inconsistent number of frames ({currentNumberOfFrames} vs {numberOfFrames})")
                        valid = False
                        break
            if not valid:
                continue

            # Component volumes are found and have consistent number of frames
            return componentVolumeNodes, invertToRasDirections

        return None, None

    def _findMagnitudeVolumeNode(self, volumeNodesSet, componentVolumeNodes):
        numberOfFrames = self._getNumberOfDataNodesInSequence(componentVolumeNodes[0])
        candidateMagnitudeVolumes = [volumeNode for volumeNode in volumeNodesSet['candidateVolumeNodes'] if self._getSequenceAttribute(volumeNode, "SlicerHeart.directionCode") == "magnitude"]
        for volumeNode in candidateMagnitudeVolumes:

            # Check number of frames
            currentNumberOfFrames = self._getNumberOfDataNodesInSequence(volumeNode)
            if currentNumberOfFrames != numberOfFrames:
                logging.debug(f"Volume node set {volumeNodesSet['name']}: candidate magnitude volume {volumeNode.GetName()} discarded due to inconsistent number of frames ({currentNumberOfFrames} vs {numberOfFrames})")
                continue

            # Found a suitable magnitude volume
            return volumeNode

        return None

    def findVolumeNodeSets(self):
        # Map from {StudyInstanceUID}/{AcquisitionNumber} to volumesNodeSet:
        # {
        #   'name': 'Patient Name (study date) / 1',
        #   'candidateVolumeNodes': result of _findVolumeNodeSetCandidatesInScene, contain volume nodes
        #       with SlicerHeart.directionCode and SlicerHeart.vencCmPerSec (velocity encoding, in cm/sec) attributes
        #   'componentVolumeNodes': [volumeNodeX, volumeNodeY, volumeNodeZ]
        #   'componentVolumeNodesInvertToRasDirection': [ix, iy, iz] if scalar value needs to be reversed to get directions in RAS
        #   'magnitudeVolumeNode': volumeNodeMagnitude
        # }
        candidateVolumeNodesSets = self._findVolumeNodeSetCandidatesInScene()
        volumeNodesSets = {}
        for acquisitionID in candidateVolumeNodesSets:
            volumeNodeSet = candidateVolumeNodesSets[acquisitionID]

            componentVolumeNodes, componentVolumeNodesInvertToRasDirection = self._findComponentVolumeNodes(volumeNodeSet)
            if componentVolumeNodes is None or componentVolumeNodesInvertToRasDirection is None:
                directionCodes = [self._getSequenceAttribute(volumeNode, "SlicerHeart.directionCode") for volumeNode in volumeNodeSet['candidateVolumeNodes']]
                logging.debug(f"Volume node set {volumeNodeSet['name']} is discarded: cannot find volume for all directions (found direction: {directionCodes})")
                continue

            magnitudeVolumeNode = self._findMagnitudeVolumeNode(volumeNodeSet, componentVolumeNodes)
            if not magnitudeVolumeNode:
                directionCodes = [self._getSequenceAttribute(volumeNode, "SlicerHeart.directionCode") for volumeNode in volumeNodeSet['candidateVolumeNodes']]
                logging.debug(f"Volume node set {volumeNodeSet['name']} is discarded: missing magnitude volume")
                continue

            volumeNodesSets[acquisitionID] = {
                "name": volumeNodeSet['name'],
                "componentVolumeNodes": componentVolumeNodes,
                "componentVolumeNodesInvertToRasDirection": componentVolumeNodesInvertToRasDirection,
                "magnitudeVolumeNode": magnitudeVolumeNode,
            }

        return volumeNodesSets

    # Unit of the velocity values of the flow fields created by this module (vector volumes, declared in their voxel value
    # units). Flow fields in other units (m/s, cm/s) can be read, see FlowLibraryBridge.velocityUnitScaleToMmPerSec.
    VELOCITY_UNIT = "mm/s"
    VELOCITY_UNIT_MEANINGS = {"m/s": "meter per second", "cm/s": "centimeter per second", "mm/s": "millimeter per second"}

    @staticmethod
    def isFlowFieldStoredInTransform(flowFieldNode) -> bool:
        """Flow fields are stored in a sequence of vector volume nodes (3-component image, with the velocity vector in each
        voxel). Flow fields stored in a sequence of grid transform nodes (legacy format, velocity in m/s) can be read
        (visualized, analyzed, exported), but processing results are not written into them.
        """
        return flowFieldNode.IsA("vtkMRMLTransformNode")

    @staticmethod
    def getFlowFieldDisplayNode(flowFieldNode):
        """Get the display node that shows the flow vectors: the transform display node of a transform,
        or the vector field display node of a vector volume (the vector volume may have other display nodes, too).
        Returns None if the flow field does not have such a display node.
        """
        for displayNodeIndex in range(flowFieldNode.GetNumberOfDisplayNodes()):
            displayNode = flowFieldNode.GetNthDisplayNode(displayNodeIndex)
            if not displayNode:
                continue
            if displayNode.IsA("vtkMRMLTransformDisplayNode") or displayNode.IsA("vtkMRMLVectorFieldDisplayNode"):
                return displayNode
        return None

    def _prepareComponentVolumes(self, componentVolumeNodes, componentVolumeNodesInvertToRasDirection, magnitudeVolumeNode):
        """Move the component image sequences into the sequence browser of the magnitude images and use the frame times
        (trigger times) as index values. Returns the sequence browser node."""

        magnitudeVolumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(magnitudeVolumeNode)
        if not magnitudeVolumeSequenceBrowserNode:
            raise RuntimeError(f"Magnitude volume {magnitudeVolumeNode.GetName()} is expected to be proxy node of a volume sequence")
        magnitudeVolumeSequenceNode = magnitudeVolumeSequenceBrowserNode.GetSequenceNode(magnitudeVolumeNode)

        # Set input nodes of the flow field based on current selection
        for component in range(3):
            componentVolumeNode = componentVolumeNodes[component]

            # Turn off interpolation to see wrapped voxels better
            componentVolumeNode.GetScalarVolumeDisplayNode().InterpolateOff()

            componentVolumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(componentVolumeNode)
            if not componentVolumeSequenceBrowserNode:
                raise RuntimeError(f"Volume {componentVolumeNode.GetName()} is expected to be proxy node of a volume sequence")
            componentVolumeSequenceNode = componentVolumeSequenceBrowserNode.GetSequenceNode(componentVolumeNode)

            # Add direction code to the name to make it easier to identify the component images
            directionCode = self._getSequenceAttribute(componentVolumeNode, 'SlicerHeart.directionCode')
            sequenceName = componentVolumeSequenceNode.GetName()
            componentVolumeSequenceNode.SetName(f"{sequenceName} - C{component+1} {directionCode}")

            invertToRasDirection = componentVolumeNodesInvertToRasDirection[component]
            # It could make sense to store this information as node reference attribute, but the feature is not yet available in Slicer Stable Release
            componentVolumeSequenceNode.SetAttribute("SlicerHeart.invertToRasDirection", "true" if invertToRasDirection else "false")

            # Move component images to the same sequence browser node
            if componentVolumeSequenceBrowserNode != magnitudeVolumeSequenceBrowserNode:
                # Remove old sequence browser node
                slicer.mrmlScene.RemoveNode(componentVolumeSequenceBrowserNode)
                # Add to common sequence browser node
                magnitudeVolumeSequenceBrowserNode.AddProxyNode(componentVolumeNode, componentVolumeSequenceNode, False)
                magnitudeVolumeSequenceBrowserNode.SetSaveChanges(componentVolumeSequenceNode, True)  # faster browsing
                magnitudeVolumeSequenceBrowserNode.SetRecording(componentVolumeSequenceNode, False)  # no need for live recording
                magnitudeVolumeSequenceBrowserNode.SetOverwriteProxyName(componentVolumeSequenceNode, True)  # show index in node name


        # Replace frame indices by frame times

        try:
            frameIdentifyingDICOMTagName = self._getSequenceAttribute(magnitudeVolumeNode, "MultiVolume.FrameIdentifyingDICOMTagName")
            frameIdentifyingDICOMTagUnits = self._getSequenceAttribute(magnitudeVolumeNode, "MultiVolume.FrameIdentifyingDICOMTagUnits")
            frameLabelsStrList = self._getSequenceAttribute(magnitudeVolumeNode, "MultiVolume.FrameLabels").split(',')
            frameLabels = [float(frameLabel) for frameLabel in frameLabelsStrList]
            numberOfFrames = int(self._getSequenceAttribute(magnitudeVolumeNode, "MultiVolume.NumberOfFrames"))
            if frameIdentifyingDICOMTagName != "TriggerTime":
                raise RuntimeWarning(f"frameIdentifyingDICOMTagName={frameIdentifyingDICOMTagName}, expected 'TriggerTime'")
            if frameIdentifyingDICOMTagUnits != "ms":
                raise RuntimeWarning(f"frameIdentifyingDICOMTagUnits={frameIdentifyingDICOMTagUnits}, expected 'ms'")
            if len(frameLabels) != numberOfFrames:
                raise RuntimeWarning(f"len(frameLabels)={len(frameLabels)}, expected {numberOfFrames}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            logging.warning(f"Failed to get frame times from sequence node: {e}")
            frameLabels = None

        if frameLabels:
            # Replace frame indices by frame times
            proxyNodes = [magnitudeVolumeNode] + componentVolumeNodes
            sequenceNodes = [self._getSequenceFromProxyNode(proxyNode) for proxyNode in proxyNodes]
            # Skip sequences that already use frame times as index (for example, if a flow field has been already created
            # from these images)
            sequenceNodes = [sequenceNode for sequenceNode in sequenceNodes
                if [sequenceNode.GetNthIndexValue(i) for i in range(sequenceNode.GetNumberOfDataNodes())] != frameLabelsStrList]

            # Temporarily disable saving of proxy node changes into all synchronized sequences (for example, flow fields
            # that were created earlier from the same images), because proxy nodes would be saved into
            # the sequences at the temporary index values.
            synchronizedSequenceNodes = vtk.vtkCollection()
            magnitudeVolumeSequenceBrowserNode.GetSynchronizedSequenceNodes(synchronizedSequenceNodes, True)
            savedSaveChanges = {}
            for synchronizedSequenceNode in [synchronizedSequenceNodes.GetItemAsObject(i) for i in range(synchronizedSequenceNodes.GetNumberOfItems())]:
                savedSaveChanges[synchronizedSequenceNode.GetID()] = magnitudeVolumeSequenceBrowserNode.GetSaveChanges(synchronizedSequenceNode)
                magnitudeVolumeSequenceBrowserNode.SetSaveChanges(synchronizedSequenceNode, False)

            # Temporary disable playback to avoid updating the index values
            for sequenceNode in sequenceNodes:
                magnitudeVolumeSequenceBrowserNode.SetPlayback(sequenceNode, False)

            for sequenceNode in sequenceNodes:
                sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.TextIndex)
                sequenceNode.SetIndexName("time")
                sequenceNode.SetIndexUnit("ms")
                # We cannot rename from the old value to the new value because in theory some of the new values
                # could be the same as some of the new values
                for frameIndex in range(numberOfFrames):
                    oldIndexValue = sequenceNode.GetNthIndexValue(frameIndex)
                    temporaryIndexValue = f"___frame{frameIndex}"
                    sequenceNode.UpdateIndexValue(oldIndexValue, temporaryIndexValue)
                for frameIndex in range(numberOfFrames):
                    temporaryIndexValue = f"___frame{frameIndex}"
                    newIndexValue = frameLabelsStrList[frameIndex]
                    sequenceNode.UpdateIndexValue(temporaryIndexValue, newIndexValue)
                sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.NumericIndex)

            # Restore playback state
            for sequenceNode in sequenceNodes:
                magnitudeVolumeSequenceBrowserNode.SetPlayback(sequenceNode, True)

            # Restore saving of proxy node changes
            for synchronizedSequenceNodeID, saveChanges in savedSaveChanges.items():
                magnitudeVolumeSequenceBrowserNode.SetSaveChanges(slicer.mrmlScene.GetNodeByID(synchronizedSequenceNodeID), saveChanges)

        return magnitudeVolumeSequenceBrowserNode

    def _addFlowFieldSequence(self, flowFieldNode, name, browserNode, referenceSequenceNode, saveChanges=True):
        """Create the sequence that stores the frames of a flow field and add it to the sequence browser."""
        flowFieldSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
        flowFieldSequenceNode.SetIndexType(referenceSequenceNode.GetIndexType())
        flowFieldSequenceNode.SetIndexName(referenceSequenceNode.GetIndexName())
        flowFieldSequenceNode.SetIndexUnit(referenceSequenceNode.GetIndexUnit())
        browserNode.AddProxyNode(flowFieldNode, flowFieldSequenceNode, False)
        browserNode.SetSaveChanges(flowFieldSequenceNode, saveChanges)
        browserNode.SetOverwriteProxyName(flowFieldSequenceNode, True)  # show index in node name
        return flowFieldSequenceNode

    @staticmethod
    def _placeInSameFolder(node, referenceNode):
        """Place a node in the same subject hierarchy folder as the reference node."""
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        shNode.SetItemParent(shNode.GetItemByDataNode(node), shNode.GetItemParent(shNode.GetItemByDataNode(referenceNode)))

    def createInputFlowFieldFromComponentVolumes(self, componentVolumeNodes, componentVolumeNodesInvertToRasDirection, magnitudeVolumeNode,
                                                 name="Input flow field"):
        """Create the input flow field from the component images: the velocity as acquired (aliased, before any correction),
        in RAS components, in a vector volume sequence that is browsed with the magnitude images. The velocity encoding is
        stored in the flow field (see FlowLibraryBridge.setRawEncoding), so the component images are not needed after this.
        Returns the input flow field (proxy node)."""
        browserNode = self._prepareComponentVolumes(componentVolumeNodes, componentVolumeNodesInvertToRasDirection, magnitudeVolumeNode)
        vencsMmPerSec, maxValues, directionCodes, componentSequenceNodes = [], [], [], []
        for componentVolumeNode in componentVolumeNodes:
            vencsMmPerSec.append(float(self._getSequenceAttribute(componentVolumeNode, "SlicerHeart.vencCmPerSec")) * 10.0)
            maxValues.append(float(self._getSequenceAttribute(componentVolumeNode, "SlicerHeart.maxValue")))
            directionCodes.append(self._getSequenceAttribute(componentVolumeNode, "SlicerHeart.directionCode") or "")
            componentSequenceNodes.append(self._getSequenceFromProxyNode(componentVolumeNode))
        signs = np.where(np.asarray(componentVolumeNodesInvertToRasDirection, bool), -1.0, 1.0)

        def rawWorldFrame(frameIndex):
            # Encoded component c is along RAS axis c (inverted if invertToRasDirection)
            return np.stack([slicer.util.arrayFromVolume(componentSequenceNodes[component].GetNthDataNode(frameIndex)).astype(np.float32)
                             * np.float32(vencsMmPerSec[component] / maxValues[component] * signs[component])
                             for component in range(3)], axis=-1)

        inputFlowFieldNode = self._createInputFlowField(rawWorldFrame, magnitudeVolumeNode, browserNode, name)
        FlowLibraryBridge.setRawEncoding(inputFlowFieldNode, vencsMmPerSec, np.diag(signs), directionCodes, maxValues)
        return inputFlowFieldNode

    def createInputFlowFieldFromArrays(self, rawWorldVelocityMmPerSec, magnitudeVolumeNode, vencEncodedMmPerSec, encodingToWorld,
                                       directionCodes=None, componentMaxValues=None, name="Input flow field"):
        """Create the input flow field from raw velocity (t, k, j, i, 3) mm/s RAS (as acquired), on the voxel grid of the
        magnitude volume sequence, browsed with the magnitude images. encodingToWorld: 3x3, columns are the RAS directions
        of the encoded components. Returns the input flow field (proxy node)."""
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(magnitudeVolumeNode)
        if not browserNode:
            raise RuntimeError(f"Magnitude volume {magnitudeVolumeNode.GetName()} is expected to be proxy node of a volume sequence")
        inputFlowFieldNode = self._createInputFlowField(lambda frameIndex: rawWorldVelocityMmPerSec[frameIndex], magnitudeVolumeNode, browserNode, name)
        FlowLibraryBridge.setRawEncoding(inputFlowFieldNode, vencEncodedMmPerSec, encodingToWorld, directionCodes, componentMaxValues)
        return inputFlowFieldNode

    def _createInputFlowField(self, rawWorldFrameMmPerSec, magnitudeVolumeNode, browserNode, name):
        """Create an input flow field (vector volume sequence, mm/s) with frames rawWorldFrameMmPerSec(frameIndex) on the voxel
        grid of the magnitude images."""
        magnitudeSequenceNode = self._getSequenceFromProxyNode(magnitudeVolumeNode)
        inputFlowFieldNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", name)
        inputFlowFieldNode.SetAttribute("SlicerHeart.Type", self.RAW_FLOW_FIELD_TYPE)
        inputFlowFieldNode.SetNodeReferenceID("magnitudeVolume", magnitudeVolumeNode.GetID())
        sequenceNode = self._addFlowFieldSequence(inputFlowFieldNode, name, browserNode, magnitudeSequenceNode, saveChanges=False)
        for frameIndex in range(magnitudeSequenceNode.GetNumberOfDataNodes()):
            frameNode, velocityArray = self._createFlowFieldFrameNode(magnitudeSequenceNode.GetNthDataNode(frameIndex))
            frameNode.SetAttribute("SlicerHeart.Type", self.RAW_FLOW_FIELD_TYPE)
            velocityArray[:] = rawWorldFrameMmPerSec(frameIndex)
            self._addFlowFieldFrameToSequence(sequenceNode, frameNode, magnitudeSequenceNode.GetNthIndexValue(frameIndex))
        self._placeInSameFolder(inputFlowFieldNode, magnitudeVolumeNode)
        return inputFlowFieldNode

    def createOutputFlowField(self, inputFlowFieldNode, name="FlowField"):
        """Create an output flow field (processing results) for an input flow field: a sequence of vector volumes (mm/s),
        browsed with the input flow field. The frames are computed by computeOutputFlowField. Returns the output flow field
        (proxy node)."""
        inputBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(inputFlowFieldNode)
        if not inputBrowserNode:
            raise RuntimeError(f"Input flow field {inputFlowFieldNode.GetName()} is expected to be proxy node of a sequence")
        outputFlowFieldNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", name)
        outputFlowFieldNode.SetAttribute("SlicerHeart.Type", "FlowField")
        outputFlowFieldNode.SetNodeReferenceID("inputFlowField", inputFlowFieldNode.GetID())
        magnitudeVolumeNode = inputFlowFieldNode.GetNodeReference("magnitudeVolume")
        if magnitudeVolumeNode:
            outputFlowFieldNode.SetNodeReferenceID("magnitudeVolume", magnitudeVolumeNode.GetID())
        self._addFlowFieldSequence(outputFlowFieldNode, "4D flow", inputBrowserNode, self._getSequenceFromProxyNode(inputFlowFieldNode))
        self._placeInSameFolder(outputFlowFieldNode, inputFlowFieldNode)
        return outputFlowFieldNode

    def createFlowFieldFromComponentVolumes(self, componentVolumeNodes, componentVolumeNodesInvertToRasDirection, magnitudeVolumeNode):
        """Create the input flow field from the component images (createInputFlowFieldFromComponentVolumes) and an output flow
        field for it (createOutputFlowField). The output flow field frames are computed by computeOutputFlowField
        (or updateFlowFieldFromComponentVolumes). Returns the output flow field."""
        inputFlowFieldNode = self.createInputFlowFieldFromComponentVolumes(componentVolumeNodes, componentVolumeNodesInvertToRasDirection, magnitudeVolumeNode)
        return self.createOutputFlowField(inputFlowFieldNode)

    def ensureInputFlowField(self, flowFieldNode):
        """Return the input flow field of a flow field. Flow fields created by earlier versions of this module reference
        the component images instead of an input flow field: for these, the input flow field is created from the component
        images. Returns None if the flow field has no input flow field and no component images."""
        try:
            return FlowLibraryBridge.rawFlowFieldNode(flowFieldNode)
        except ValueError:
            pass
        componentVolumeNodes = [flowFieldNode.GetNthNodeReference("componentVolume", component) for component in range(3)]
        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
        if not all(componentVolumeNodes) or not magnitudeVolumeNode:
            return None
        invertToRas = [self._getSequenceAttribute(node, "SlicerHeart.invertToRasDirection") == "true" for node in componentVolumeNodes]
        inputFlowFieldNode = self.createInputFlowFieldFromComponentVolumes(componentVolumeNodes, invertToRas, magnitudeVolumeNode)
        flowFieldNode.SetNodeReferenceID("inputFlowField", inputFlowFieldNode.GetID())
        for component in range(3):
            flowFieldNode.RemoveNthNodeReferenceID("componentVolume", 0)
        return inputFlowFieldNode

    @staticmethod
    def _removeSequenceAndProxy(proxyNode):
        """Remove a proxy node and its sequence (from its sequence browser too). The sequence browser is removed if it does
        not browse any other sequences."""
        if proxyNode is None:
            return
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(proxyNode)
        sequenceNode = browserNode.GetSequenceNode(proxyNode) if browserNode else None
        if browserNode and sequenceNode:
            browserNode.RemoveSynchronizedSequenceNode(sequenceNode.GetID())
        for node in [sequenceNode, proxyNode]:
            if node is None:
                continue
            for nodeToRemove in ([node.GetStorageNode()] if hasattr(node, "GetStorageNode") else []) + \
                                ([node.GetDisplayNode()] if hasattr(node, "GetDisplayNode") else []) + [node]:
                if nodeToRemove is not None:
                    slicer.mrmlScene.RemoveNode(nodeToRemove)
        if browserNode:
            synchronizedSequenceNodes = vtk.vtkCollection()
            browserNode.GetSynchronizedSequenceNodes(synchronizedSequenceNodes, True)
            if synchronizedSequenceNodes.GetNumberOfItems() == 0:
                slicer.mrmlScene.RemoveNode(browserNode)

    def removeComponentVolumes(self, componentVolumeNodes):
        """Remove the component images (sequences and proxy nodes). They are not needed after the input flow field is created."""
        for componentVolumeNode in componentVolumeNodes:
            self._removeSequenceAndProxy(componentVolumeNode)

    def deleteFlowField(self, flowFieldNode):
        """Remove a flow field: its sequence and proxy node, and the component volumes that were created from it for display."""
        for component in range(3):
            self._removeSequenceAndProxy(flowFieldNode.GetNodeReference(f"rawComponentVolume{component}"))
        self._removeSequenceAndProxy(flowFieldNode)

    def _getComponentBackground(self, magnitudeVoxelArray, componentVoxelArray, noiseMagnitudeThreshold, backgroundSubtractionMethod, stationaryTissueMask):
        """Compute background phase offset of a component image by fitting a smooth function to the stationary tissue voxels.
        stationaryTissueMask: voxels where the speed is low (computed from all velocity components), only these
        voxels are used for fitting (voxels below the noise magnitude threshold are excluded, too).
        """
        import numpy as np

        # Use floating-point background values (rounding to integer would add a bias)
        background_3d = np.zeros(componentVoxelArray.shape, dtype=np.float64)
        if backgroundSubtractionMethod == BackgroundSubtractionMethodEnum.NoSubtraction:
            return background_3d

        from scipy.optimize import curve_fit

        data = componentVoxelArray

        # Mask array (True for values to be used in fitting)
        mask = np.logical_and(magnitudeVoxelArray > noiseMagnitudeThreshold, stationaryTissueMask)

        # Get the indices and values of the masked elements
        indices = np.array(np.nonzero(mask))
        values = data[mask]

        # Define a linear function for fitting
        def linear(x, a, b, c, d):
            return a * x[0] + b * x[1] + c * x[2] + d

        # Define a second-order polynomial function for fitting
        def quadratic(x, a, b, c, d, e, f, g, h, i, j):
            return (a * x[0]**2 + b * x[1]**2 + c * x[2]**2 +
                    d * x[0] * x[1] + e * x[0] * x[2] + f * x[1] * x[2] +
                    g * x[0] + h * x[1] + i * x[2] + j)

        if backgroundSubtractionMethod == BackgroundSubtractionMethodEnum.LinearFit:
            fitFunction = linear
        elif backgroundSubtractionMethod == BackgroundSubtractionMethodEnum.QuadraticFit:
            fitFunction = quadratic
        else:
            raise ValueError(f"Unsupported background subtraction method: {backgroundSubtractionMethod}")

        # Fit the second-order polynomial model to the masked values
        params, _ = curve_fit(fitFunction, indices, values)
        print(f"Fit parameters: {params}")
        # Compute the background using the fitted parameters
        backgroundIndices = np.array(np.nonzero(magnitudeVoxelArray >= noiseMagnitudeThreshold))  # Compute background for non-noise regions
        background = fitFunction(backgroundIndices, *params)

        background_3d[magnitudeVoxelArray >= noiseMagnitudeThreshold] = background

        return background_3d

    def updateFlowFieldFromComponentVolumes(self, flowFieldNode, noiseMagnitudeThresholdPercent, backgroundSubtractionMethod, stationaryTissueSpeedThresholdVencPercent,
                                            noiseMaskMethod=NoiseMaskMethodEnum.MagnitudeThreshold, backgroundPolynomialOrder=2, backgroundPerFrame=False,
                                            divergenceFilterMethod=DivergenceFilterMethodEnum.NoFilter, lumenMask=None):
        """Compute the output flow field flowFieldNode from its input flow field (see computeOutputFlowField).
        Flow fields of earlier versions of this module that reference the component images get an input flow field first."""
        if self.ensureInputFlowField(flowFieldNode) is None:
            raise ValueError(f"Flow field {flowFieldNode.GetName()} has no input flow field")
        self.computeOutputFlowField(flowFieldNode, noiseMagnitudeThresholdPercent, backgroundSubtractionMethod, stationaryTissueSpeedThresholdVencPercent,
                                    noiseMaskMethod, backgroundPolynomialOrder, backgroundPerFrame, divergenceFilterMethod, lumenMask)

    def computeOutputFlowField(self, outputFlowFieldNode, noiseMagnitudeThresholdPercent, backgroundSubtractionMethod, stationaryTissueSpeedThresholdVencPercent,
                               noiseMaskMethod=NoiseMaskMethodEnum.MagnitudeThreshold, backgroundPolynomialOrder=2, backgroundPerFrame=False,
                               divergenceFilterMethod=DivergenceFilterMethodEnum.NoFilter, lumenMask=None):
        """Compute the velocity field of each frame of the output flow field from its input flow field (velocity as acquired,
        see createOutputFlowField) and store them in the output flow field sequence. Only the input flow field and the magnitude
        images are used. The output flow field is a vector volume; velocity vectors are stored in mm/s, in RAS.

        Processing steps on the encoded velocity components: noise masking, phase unwrapping (by the phase wrap segmentations
        of the output flow field), background phase subtraction, then optionally divergence-free filtering.

        noiseMaskMethod: voxels below the magnitude threshold (MagnitudeThreshold) or the slicerheart_4dflow noise mask
          (low magnitude or random phase, BockNoiseMask) are set to zero velocity.
        backgroundSubtractionMethod: SlicerHeart polynomial fits (per frame, stationary tissue selected by the speed
          threshold) or slicerheart_4dflow robust fits (static tissue selected automatically, fitted to the time average
          or, if backgroundPerFrame is True, to each frame, polynomial order backgroundPolynomialOrder).
        divergenceFilterMethod: divergence-free filter applied inside lumenMask (required for filtering).
        lumenMask: optional (k, j, i) bool array of the vessel lumen on the voxel grid of the flow field. Used by
          slicerheart_4dflow methods: excluded from background fitting, region of divergence-free filtering.
        """
        if noiseMaskMethod is None:
            noiseMaskMethod = NoiseMaskMethodEnum.MagnitudeThreshold
        if divergenceFilterMethod is None:
            divergenceFilterMethod = DivergenceFilterMethodEnum.NoFilter
        libraryBackgroundMethod = backgroundSubtractionMethod.libraryMethod()
        divergenceMethod = divergenceFilterMethod.libraryMethod()
        if divergenceMethod and lumenMask is None:
            raise ValueError("Divergence-free filtering requires a lumen segmentation")

        inputFlowFieldNode = FlowLibraryBridge.rawFlowFieldNode(outputFlowFieldNode)
        inputSequenceNode = self._getSequenceFromProxyNode(inputFlowFieldNode)
        rawEncodedVelocity = FlowLibraryBridge.rawEncodedVelocity(outputFlowFieldNode)  # (t, k, j, i, 3) mm/s
        _, vencs, _ = FlowLibraryBridge.componentEncoding(outputFlowFieldNode)
        encodingToWorld = FlowLibraryBridge.encodingToWorld(outputFlowFieldNode).astype(np.float32)
        magnitudeVolumeNode = outputFlowFieldNode.GetNodeReference("magnitudeVolume")
        magnitude = FlowLibraryBridge.magnitudeArray(outputFlowFieldNode) if magnitudeVolumeNode else None
        if magnitude is None and (backgroundSubtractionMethod != BackgroundSubtractionMethodEnum.NoSubtraction
                                  or noiseMaskMethod == NoiseMaskMethodEnum.BockNoiseMask):
            raise ValueError("Background correction and the slicerheart_4dflow noise mask require the magnitude images, but the input flow field"
                             " has no magnitude images. Set background subtraction to none and noise mask to magnitude threshold"
                             " (not applied without magnitude images).")
        wrapCounts = self.getWrapCounts(outputFlowFieldNode)  # (t, k, j, i, 3) or None

        # Library methods that need all frames at once
        staticNoiseMask = None  # (k, j, i), True = noise
        libraryBackground = None  # background velocity of the encoded components (mm/s): (k, j, i, 3) or (t, k, j, i, 3)
        if noiseMaskMethod == NoiseMaskMethodEnum.BockNoiseMask or libraryBackgroundMethod:
            library = FlowLibraryBridge.ensureLibrary()
            if noiseMaskMethod == NoiseMaskMethodEnum.BockNoiseMask:
                # Noise is detected from the temporal variation of the velocity, therefore wraps must not be included
                self._log("Computing noise mask...")
                unwrapped = rawEncodedVelocity if wrapCounts is None else rawEncodedVelocity + wrapCounts * (2 * vencs).astype(np.float32)
                staticNoiseMask = library.noise_mask(magnitude, unwrapped)
                del unwrapped
            if libraryBackgroundMethod:
                self._log(f"Computing background phase ({libraryBackgroundMethod})...")
                corrected, info = library.correct_background_phase(
                    rawEncodedVelocity, magnitude, method=libraryBackgroundMethod, order=int(backgroundPolynomialOrder),
                    lumen_mask=lumenMask, per_frame=bool(backgroundPerFrame))
                libraryBackground = rawEncodedVelocity - corrected
                if not backgroundPerFrame:
                    libraryBackground = libraryBackground[0]
                for line in info.get("report", []):
                    logging.info(f"Background phase fit: {line}")
                del corrected

        noiseMagnitudeThreshold = noiseMagnitudeThresholdPercent / 100 * self.magnitudeVolumeRange
        stationaryTissueSpeedThresholdMmPerSec = stationaryTissueSpeedThresholdVencPercent / 100 * float(np.max(vencs))
        if self.isFlowFieldStoredInTransform(outputFlowFieldNode):
            raise ValueError(f"Flow field {outputFlowFieldNode.GetName()} is stored in transforms (legacy format), which can be read"
                             " but not written. Select a vector volume output flow field or create a new one.")
        outputSequenceNode = self._getSequenceFromProxyNode(outputFlowFieldNode)
        magnitudeSequenceNode = self._getSequenceFromProxyNode(magnitudeVolumeNode) if magnitudeVolumeNode else None

        # Frames are added to the sequence after all of them are computed, as divergence-free filtering needs all frames
        frames = []  # (frame node, velocity array view, index value)
        for frameIndex in range(inputSequenceNode.GetNumberOfDataNodes()):
            rawFrame = rawEncodedVelocity[frameIndex]
            if staticNoiseMask is not None:
                noiseVoxels = staticNoiseMask
            elif magnitude is not None:
                noiseVoxels = magnitude[frameIndex] < noiseMagnitudeThreshold
            else:
                noiseVoxels = np.zeros(rawFrame.shape[:3], bool)

            # Node that stores the flow field of this frame, on the voxel grid of the input flow field
            referenceVolumeNode = magnitudeSequenceNode.GetNthDataNode(frameIndex) if magnitudeSequenceNode else inputSequenceNode.GetNthDataNode(frameIndex)
            frameNode, velocityArray = self._createFlowFieldFrameNode(referenceVolumeNode)

            # Stationary tissue (used for background phase fitting): where the speed (computed from all velocity components)
            # is below the threshold. Using each component separately would include blood that flows mainly along other axes.
            stationaryTissueMask = None
            if backgroundSubtractionMethod in (BackgroundSubtractionMethodEnum.LinearFit, BackgroundSubtractionMethodEnum.QuadraticFit):
                stationaryTissueMask = np.sum(rawFrame ** 2, axis=-1) < stationaryTissueSpeedThresholdMmPerSec ** 2

            encodedFrame = np.zeros(rawFrame.shape, np.float32)
            for component in range(3):
                # Phase unwrapping
                componentValues = rawFrame[..., component].copy()
                componentValues[noiseVoxels] = 0
                if wrapCounts is not None:
                    componentValues += wrapCounts[frameIndex, ..., component] * np.float32(2 * vencs[component])
                # Background phase
                if libraryBackground is not None:
                    background = (libraryBackground[frameIndex] if backgroundPerFrame else libraryBackground)[..., component]
                elif magnitude is not None:
                    background = self._getComponentBackground(magnitude[frameIndex], rawFrame[..., component], noiseMagnitudeThreshold,
                                                              backgroundSubtractionMethod, stationaryTissueMask)
                else:
                    background = 0
                encodedFrame[..., component] = componentValues - background

            # Background is not subtracted in noise regions
            encodedFrame[noiseVoxels] = 0
            velocityArray[:] = encodedFrame @ encodingToWorld.T
            frames.append((frameNode, velocityArray, inputSequenceNode.GetNthIndexValue(frameIndex)))
        del rawEncodedVelocity, magnitude

        if divergenceMethod:
            library = FlowLibraryBridge.ensureLibrary()
            self._log(f"Divergence-free filtering ({divergenceMethod})...")
            velocity = np.stack([velocityArray for _, velocityArray, _ in frames])
            voxelToWorld = FlowLibraryBridge.voxelToWorld(FlowLibraryBridge.flowFieldGeometryNode(inputFlowFieldNode))
            filtered, infos = library.divergence_free_sequence(velocity, lumenMask, voxelToWorld, method=divergenceMethod)
            for (_, velocityArray, _), filteredFrame in zip(frames, filtered):
                velocityArray[lumenMask] = filteredFrame[lumenMask]
            for frameIndex, info in enumerate(infos):
                logging.info(f"Divergence-free filtering frame {frameIndex}: divergence RMS {info['div_rms_before']:.4g} -> {info['div_rms_after']:.4g} 1/s")
            del velocity, filtered

        for frameNode, _, indexValue in frames:
            self._addFlowFieldFrameToSequence(outputSequenceNode, frameNode, indexValue)

        outputSequenceNode.SetAttribute("SlicerHeart.vencCmPerSec", ",".join(str(float(venc) / 10.0) for venc in vencs))  # velocity encoding, in cm/sec
        # Unit of the velocity vectors. Vector volume frames also store it in their voxel value units, but those are not kept
        # in sequences in all Slicer versions.
        outputSequenceNode.SetAttribute("SlicerHeart.velocityUnit", self.VELOCITY_UNIT)
        outputSequenceNode.SetAttribute("SlicerHeart.processing", json.dumps({
            "noiseMask": noiseMaskMethod.name,
            "noiseMagnitudeThresholdPercent": noiseMagnitudeThresholdPercent,
            "backgroundSubtraction": backgroundSubtractionMethod.name,
            "stationaryTissueSpeedThresholdVencPercent": stationaryTissueSpeedThresholdVencPercent,
            "backgroundPolynomialOrder": int(backgroundPolynomialOrder) if libraryBackgroundMethod else None,
            "backgroundPerFrame": bool(backgroundPerFrame) if libraryBackgroundMethod else None,
            "divergenceFilter": divergenceFilterMethod.name,
            "phaseUnwrapping": outputSequenceNode.GetAttribute("SlicerHeart.phaseUnwrapping") or "None",
            }))

    @staticmethod
    def createVelocityUnits(unit=None):
        """Coded entry for the unit of the velocity values stored in vector volume flow fields (default: VELOCITY_UNIT).
        It is stored in the "units" field of the component axis when the volume is written to NRRD file."""
        unit = unit or Import4DFlowLogic.VELOCITY_UNIT
        velocityUnits = slicer.vtkCodedEntry()
        velocityUnits.SetValueSchemeMeaning(unit, "UCUM", Import4DFlowLogic.VELOCITY_UNIT_MEANINGS[unit])
        return velocityUnits

    def _createFlowFieldFrameNode(self, referenceVolumeNode):
        """Create a node that stores the velocity field of one frame, on the voxel grid of the reference volume.
        Returns the node (not added to the scene) and a numpy array view of its velocity vectors (shape: k, j, i, component).
        After the array is filled, call _addFlowFieldFrameToSequence.
        """
        dims = referenceVolumeNode.GetImageData().GetDimensions()
        velocityImage = vtk.vtkImageData()
        velocityImage.SetDimensions(dims[0], dims[1], dims[2])
        velocityImage.AllocateScalars(vtk.VTK_FLOAT, 3)
        frameNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLVectorVolumeNode")
        frameNode.UnRegister(None)  # Prevent memory leak
        frameNode.CopyOrientation(referenceVolumeNode)
        # Voxels store velocity vectors with RAS components. Marking them as spatial vectors makes
        # Slicer convert them to LPS when writing to file and back to RAS when reading.
        frameNode.SetVoxelVectorType(slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial)
        # Voxel values are velocity vectors in mm/s (stored in the "units" field of the component axis in NRRD files)
        frameNode.SetVoxelValueUnits(self.createVelocityUnits())
        # Stored in the "labels" field of the component axis in NRRD files
        frameNode.SetVoxelValueQuantity(Import4DFlowLogic.createVelocityQuantity())
        frameNode.SetAndObserveImageData(velocityImage)
        velocityArray = slicer.util.arrayFromVolume(frameNode)
        frameNode.SetAttribute("SlicerHeart.Type", "FlowField")
        return frameNode, velocityArray

    def _addFlowFieldFrameToSequence(self, flowFieldSequenceNode, frameNode, indexValue):
        """Store a frame created by _createFlowFieldFrameNode in the flow field sequence."""
        slicer.util.arrayFromVolumeModified(frameNode)
        flowFieldSequenceNode.SetDataNodeAtValue(frameNode, indexValue)

    def setFlowFieldVisualizationToDefault(self, flowFieldNode: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode]) -> None:
        """Show the flow field as glyphs in slice views, colored by speed."""
        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
        displayNode = self.getFlowFieldDisplayNode(flowFieldNode)
        # Glyph and color settings are in the unit of the stored velocity values: m/s for transforms (legacy format),
        # the voxel value unit for vector volumes (mm/s for flow fields created by this module)
        unitToMmPerSec = FlowLibraryBridge.velocityUnitScaleToMmPerSec(flowFieldNode)
        unitName = {1.0: "mm/s", 10.0: "cm/s", 1000.0: "m/s"}.get(unitToMmPerSec, "")
        if self.isFlowFieldStoredInTransform(flowFieldNode):
            if not displayNode:
                displayNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformDisplayNode")
                flowFieldNode.AddAndObserveDisplayNodeID(displayNode.GetID())
            displayNode.SetGlyphDisplayRangeMinMm(0.05) # meter/sec
            displayNode.SetGlyphSpacingMm(2.0)
            displayNode.SetGlyphDiameterMm(0.8)
            displayNode.SetGlyphScalePercent(500)
            displayNode.SetAndObserveRegionNode(magnitudeVolumeNode)
        else:
            if not hasattr(slicer, "vtkMRMLVectorFieldDisplayNode"):
                logging.warning("Flow vectors of a vector volume flow field cannot be displayed in this Slicer version"
                                " (vector field display node is not available). The flow field is still computed and can be shown as a volume.")
                return
            # Vector volume display node for showing the volume in slice views, vector field display node for the glyphs
            flowFieldNode.CreateDefaultDisplayNodes()
            if not displayNode:
                displayNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorFieldDisplayNode")
                flowFieldNode.AddAndObserveDisplayNodeID(displayNode.GetID())
            displayNode.SetThresholdRange(50.0 / unitToMmPerSec, 100000.0 / unitToMmPerSec)  # hide glyphs where there is no flow (below 5 cm/s)
            displayNode.SetThresholdEnabled(True)
            displayNode.SetGlyphDiameterAbsolute(True)
            if hasattr(displayNode, "SetSamplingSpacing"):
                # Current vector field display node API
                displayNode.SetSamplingPattern(slicer.vtkMRMLVectorFieldDisplayNode.SamplingPatternRegular)
                displayNode.SetSamplingSpacing(2.0)
                displayNode.SetGlyphDiameter(0.8)
                displayNode.SetGlyphScaleFactor(5.0 * unitToMmPerSec / 1000.0)  # 5 mm long glyph for 1 m/s
                displayNode.SetAndObserveSamplingRegionNode(magnitudeVolumeNode)
            else:
                # Earlier vector field display node API
                displayNode.SetMaskingMode(slicer.vtkMRMLVectorFieldDisplayNode.MaskingModeFixedSpacing)
                displayNode.SetEffectiveSamplingSpacingMm(2.0)
                displayNode.SetGlyphDiameterMm(0.8)
                displayNode.SetScaleFactor(5.0 * unitToMmPerSec / 1000.0)
                displayNode.SetAndObserveRegionNode(magnitudeVolumeNode)

        displayNode.SetVisibility(True)
        displayNode.SetVisibility2D(True)
        displayNode.SetVisibility3D(False)  # with small glyph spacing, updating of the glyphs in 3D can be slow

        colorNode = displayNode.GetColorNode()
        if not colorNode or colorNode.GetAttribute("Category") != "Flow":
            # Create color node
            colorNode = self._createSpeedColorNode()
            displayNode.SetAndObserveColorNodeID(colorNode.GetID())
            # Display color legend
            colorLegendDisplayNode = slicer.modules.colors.logic().AddDefaultColorLegendDisplayNode(displayNode)
            colorLegendDisplayNode.SetTitleText("Speed")
            colorLegendDisplayNode.SetLabelFormat(f"%4.0f {unitName}" if unitToMmPerSec < 1000.0 else f"%4.1f {unitName}")
            #colorLegendDisplayNode.SetScalarRange(0, 1.5)
        if not self.isFlowFieldStoredInTransform(flowFieldNode):
            # Color the glyphs by the color map range (speed) and not by the data range, so that colors
            # are consistent across frames and acquisitions (transform display node always does this).
            # Set after the color node is assigned, as the scalar range is updated from the color node immediately.
            displayNode.SetScalarRangeFlag(slicer.vtkMRMLDisplayNode.UseColorNodeScalarRange)

        # Update colormap colors
        colorMap = colorNode.GetColorTransferFunction()
        wasModified = colorNode.StartModify()
        colorMap.RemoveAllPoints()
        # Determine color map range based on velocity encoding, so that the color map is consistent across different acquisitions
        # that use the same velocity encoding (venc) setting.
        try:
            _, vencsMmPerSec, _ = FlowLibraryBridge.componentEncoding(flowFieldNode)
            colorTableRangeMmPerSec = float(np.max(vencsMmPerSec))
        except ValueError:
            # No input flow field (for example, a flow field loaded from file): typical velocity encoding
            colorTableRangeMmPerSec = 1500.0
        colorTableRange = colorTableRangeMmPerSec / unitToMmPerSec  # in the unit of the stored velocity values

        if self.useDopplerColorTableForAbsoluteSpeed:
            dopplerColorNode = Import4DFlowLogic.dopplerColdToHotColorTableNode()
            speed0Index = (dopplerColorNode.GetNumberOfColors() - 1) / 2
            speedMaxIndex = dopplerColorNode.GetNumberOfColors() - 1
            colorMapResolution = 25
            rgba = [0, 0, 0, 0]
            for i in range(colorMapResolution):
                colorIndex = int(speed0Index + i / (colorMapResolution - 1) * (speedMaxIndex - speed0Index))
                dopplerColorNode.GetColor(colorIndex, rgba)
                colorMap.AddRGBPoint(colorTableRange * i / colorMapResolution, rgba[0], rgba[1], rgba[2])
        else:
            # Use jet color (blue, green, red)
            colorMap.AddRGBPoint(colorTableRange * 0.0, 0.0, 0.0, 1.0)
            colorMap.AddRGBPoint(colorTableRange * 0.2, 0.0, 1.0, 1.0)
            colorMap.AddRGBPoint(colorTableRange * 0.5, 1.0, 1.0, 0.0)
            colorMap.AddRGBPoint(colorTableRange * 1.0, 1.0, 0.0, 0.0)

        colorNode.EndModify(wasModified)

    def _deleteComponentVolumeNodes(self, componentVolumeNodes):
        # Delete imported component image series from the scene
        for axis, componentVolumeSequenceProxyNode in enumerate(componentVolumeNodes):
            if not componentVolumeSequenceProxyNode:
                raise RuntimeError(f"Volume ({axis}) is invalid")
            componentVolumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(componentVolumeSequenceProxyNode)
            if not componentVolumeSequenceBrowserNode:
                raise RuntimeError(f"Volume {componentVolumeSequenceProxyNode.GetName()} is expected to be proxy node of a volume sequence")
            componentVolumeSequenceNode = componentVolumeSequenceBrowserNode.GetSequenceNode(componentVolumeSequenceProxyNode)
            slicer.mrmlScene.RemoveNode(componentVolumeSequenceNode.GetStorageNode())
            slicer.mrmlScene.RemoveNode(componentVolumeSequenceNode)
            slicer.mrmlScene.RemoveNode(componentVolumeSequenceProxyNode.GetDisplayNode())
            slicer.mrmlScene.RemoveNode(componentVolumeSequenceProxyNode.GetStorageNode())
            slicer.mrmlScene.RemoveNode(componentVolumeSequenceProxyNode)
            slicer.mrmlScene.RemoveNode(componentVolumeSequenceBrowserNode)

    def exportDisplacementFieldToFiles(self,
                                       flowFieldNode: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode],
                                       exportDirectory: str,
                                       exportFormat: str) -> None:
        if exportFormat == Import4DFlowLogic.EXPORT_FORMAT_NRRD_STACK:
            self.exportDisplacementFieldToNrrdStack(flowFieldNode, exportDirectory)
        elif exportFormat == Import4DFlowLogic.EXPORT_FORMAT_NRRD_5D:
            self.exportFlowFieldToNrrd5D(flowFieldNode, exportDirectory)
        elif exportFormat == Import4DFlowLogic.EXPORT_FORMAT_ANONYMIZED_SCENE:
            self.exportDisplacementFieldToAnonymizedScene(exportDirectory)
        elif exportFormat == Import4DFlowLogic.EXPORT_FORMAT_TEST_CASE:
            # The export folder is the folder of the data set; the case gets the next free case ID
            self.exportTestCaseWithFlows(flowFieldNode, exportDirectory, self.nextTestCaseId(exportDirectory))
        else:
            raise ValueError(f"Unsupported export format: {exportFormat}")

    def createVectorVolumeSequenceFromFlowField(self, flowFieldNode: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode], name: str = "4D flow velocity"):
        """Create a vector volume sequence (added to the scene) from a flow field: each frame is a 3-component image
        with the velocity vector (RAS, in the unit of the flow field: mm/s, or m/s for transforms) in each voxel, on the voxel grid
        of the magnitude volume.
        If the flow field is already stored in vector volumes then a copy of its sequence is returned.
        """
        flowFieldSequenceNode = self._getSequenceFromProxyNode(flowFieldNode)
        volumeSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
        try:
            volumeSequenceNode.SetIndexType(flowFieldSequenceNode.GetIndexType())
            volumeSequenceNode.SetIndexName(flowFieldSequenceNode.GetIndexName())
            volumeSequenceNode.SetIndexUnit(flowFieldSequenceNode.GetIndexUnit())
            for attributeName in flowFieldSequenceNode.GetAttributeNames():
                volumeSequenceNode.SetAttribute(attributeName, flowFieldSequenceNode.GetAttribute(attributeName))

            if not self.isFlowFieldStoredInTransform(flowFieldNode):
                for frameIndex in range(flowFieldSequenceNode.GetNumberOfDataNodes()):
                    frameVolumeNode = volumeSequenceNode.SetDataNodeAtValue(flowFieldSequenceNode.GetNthDataNode(frameIndex), flowFieldSequenceNode.GetNthIndexValue(frameIndex))
                    # Frames created before the voxel vector type was set store RAS components too
                    frameVolumeNode.SetVoxelVectorType(slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial)
                    if not frameVolumeNode.GetVoxelValueUnits():
                        # Vector volumes without declared unit are in mm/s (see FlowLibraryBridge.velocityUnitScaleToMmPerSec)
                        frameVolumeNode.SetVoxelValueUnits(self.createVelocityUnits(
                            flowFieldSequenceNode.GetAttribute("SlicerHeart.velocityUnit") or "mm/s"))
                return volumeSequenceNode

            # Sample the displacement field of each frame on the magnitude volume grid.
            # The sequence is browsed so that the transform and the magnitude volume are both in the scene (proxy nodes).
            browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
            magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
            if not magnitudeVolumeNode:
                raise RuntimeError("Flow field has no magnitude volume reference, cannot determine the voxel grid")
            displayNode = self.getFlowFieldDisplayNode(flowFieldNode)
            wasVisible = displayNode.GetVisibility() if displayNode else False
            originalItemNumber = browserNode.GetSelectedItemNumber()
            frameVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "___temp_flowfield_frame___")
            try:
                if displayNode:
                    displayNode.SetVisibility(False)  # speed up browsing
                for itemNumber in range(browserNode.GetNumberOfItems()):
                    browserNode.SetSelectedItemNumber(itemNumber)
                    indexValue = browserNode.GetMasterSequenceNode().GetNthIndexValue(itemNumber)
                    if not slicer.modules.transforms.logic().CreateDisplacementVolumeFromTransform(flowFieldNode, magnitudeVolumeNode, False, frameVolumeNode):
                        raise RuntimeError(f"Failed to compute velocity vectors of frame {itemNumber}")
                    frameVolumeNode.SetAttribute("SlicerHeart.Type", "FlowField")
                    # Transforms (legacy format) store velocity vectors in m/s
                    frameVolumeNode.SetVoxelValueUnits(self.createVelocityUnits("m/s"))
                    volumeSequenceNode.SetDataNodeAtValue(frameVolumeNode, indexValue)
            finally:
                slicer.mrmlScene.RemoveNode(frameVolumeNode)
                browserNode.SetSelectedItemNumber(originalItemNumber)
                if displayNode:
                    displayNode.SetVisibility(wasVisible)
        except Exception:
            slicer.mrmlScene.RemoveNode(volumeSequenceNode)
            raise
        return volumeSequenceNode

    def exportFlowFieldToNrrd5D(self,
                                flowFieldNode: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode],
                                exportDirectory: str) -> str:
        """Write all frames of the flow field into a single 5D NRRD file (velocity components, 3 spatial axes, time).
        The file is written by Slicer's volume sequence writer, so it can be loaded back into Slicer as a vector volume sequence.
        Velocity vectors are in the unit of the flow field (mm/s; m/s for transforms, the legacy format), recorded in the units
        field of the file, in RAS coordinate system (stored as LPS in the file, as any other NRRD volume).
        Returns the path of the written file.
        """
        exportedFile = os.path.join(exportDirectory, "flowfield.seq.nrrd")
        volumeSequenceNode = self.createVectorVolumeSequenceFromFlowField(flowFieldNode)
        storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVolumeSequenceStorageNode")
        try:
            storageNode.SetFileName(exportedFile)
            if not storageNode.WriteData(volumeSequenceNode):
                errorMessage = f"Failed to write flow field to {exportedFile}"
                userMessages = storageNode.GetUserMessages()
                if userMessages.GetNumberOfMessages() > 0:
                    errorMessage += "\n" + userMessages.GetAllMessagesAsString()
                raise RuntimeError(errorMessage)
        finally:
            slicer.mrmlScene.RemoveNode(storageNode)
            slicer.mrmlScene.RemoveNode(volumeSequenceNode)
        return exportedFile

    def exportDisplacementFieldToAnonymizedScene(self, exportDirectory: str) -> None:

        oldRootDirectory = slicer.mrmlScene.GetRootDirectory()
        try:
            if slicer.mrmlScene.GetURL():
                filename = os.path.basename(slicer.mrmlScene.GetURL())
                baseFileName = os.path.splitext(filename)[0]
            else:
                baseFileName = "4DFlow"

            # Make a copy of the scene by writing to MRB and reading it back
            temporaryAnonymizedSceneFilePath = f"{exportDirectory}/temp-{baseFileName}.mrb"
            logging.info(f"Saving scene to {temporaryAnonymizedSceneFilePath}")

            userMessages = slicer.vtkMRMLMessageCollection()
            if not slicer.mrmlScene.WriteToMRB(temporaryAnonymizedSceneFilePath, None, userMessages):
                errorMessage = f"Initial saving of anonymized scene failed: {temporaryAnonymizedSceneFilePath}"
                if userMessages.GetNumberOfMessages() > 0:
                    errorMessage += "\n" + userMessages.GetAllMessagesAsString()
                raise RuntimeError(errorMessage)

            # Set up new scene that will contain the anonymized content
            anonymizedScene = slicer.vtkMRMLScene()
            slicer.mrmlScene.CopyRegisteredNodesToScene(anonymizedScene)
            anonymizedScene.SetDataIOManager(slicer.mrmlScene.GetDataIOManager())
            layoutNode = slicer.mrmlScene.GetSingletonNode('vtkMRMLLayoutNode', 'vtkMRMLLayoutNode')
            anonymizedLayoutNode = slicer.vtkMRMLLayoutNode()
            anonymizedLayoutNode.Copy(layoutNode)
            anonymizedScene.AddNode(anonymizedLayoutNode)

            logging.info(f"Loading scene from {temporaryAnonymizedSceneFilePath}")
            userMessages = slicer.vtkMRMLMessageCollection()
            if not anonymizedScene.ReadFromMRB(temporaryAnonymizedSceneFilePath, True, userMessages):
                errorMessage = f"Reloading of anonymized scene failed: {temporaryAnonymizedSceneFilePath}"
                if userMessages.GetNumberOfMessages() > 0:
                    errorMessage += "\n" + userMessages.GetAllMessagesAsString()
                raise RuntimeError(errorMessage)

            # Remove the temporary scene file to free up disk space before writing the final anonymized scene file
            if os.path.exists(temporaryAnonymizedSceneFilePath):
                os.remove(temporaryAnonymizedSceneFilePath)

            self.anonymizeScene(anonymizedScene)
            slicer.anonymizedScene = anonymizedScene

            anonymizedSceneFilePath = f"{exportDirectory}/{baseFileName}-anon.mrb"
            logging.info(f"Saving anonymized scene from {anonymizedSceneFilePath}")
            userMessages = slicer.vtkMRMLMessageCollection()
            if not anonymizedScene.WriteToMRB(anonymizedSceneFilePath, None, userMessages):
                errorMessage = f"Saving after anonymization failed: {anonymizedSceneFilePath}"
                if userMessages.GetNumberOfMessages() > 0:
                    errorMessage += "\n" + userMessages.GetAllMessagesAsString()
                raise RuntimeError(errorMessage)

        finally:
            if os.path.exists(temporaryAnonymizedSceneFilePath):
                os.remove(temporaryAnonymizedSceneFilePath)
            oldRootDirectory = slicer.mrmlScene.GetRootDirectory()

    def anonymizeScene(self, scene: slicer.vtkMRMLScene) -> None:
        """Remove all known patient identifying information from the scene.
        """

        if not hasattr(slicer.vtkMRMLSubjectHierarchyNode, "GetItemUIDNames"):
            raise RuntimeError("Anonymization feature requires a recent Slicer-5.7 version or later.")

        # Anonymize nodes
        nodes = scene.GetNodes()
        for i in range(nodes.GetNumberOfItems()):
            node = nodes.GetItemAsObject(i)
            # Remove MultiVolume.FrameFileList attribute from sequence nodes because they contain absolute file paths
            # that could potentially reveal patient name or IDs
            node.RemoveAttribute("MultiVolume.FrameFileList")
            # Remove all attributes that start with DICOM (DICOM.ContentDate, DICOM.ContentTime, DICOM.FrameOfReferenceUID, etc.).
            attributeNames = node.GetAttributeNames()
            for attributeName in attributeNames:
                if attributeName.startswith("DICOM"):
                    node.RemoveAttribute(attributeName)

        # Anonymize subject hierarchy items
        shNode = scene.GetSubjectHierarchyNode()
        childrenIds = vtk.vtkIdList()
        shNode.GetItemChildren(shNode.GetSceneItemID(), childrenIds, True)
        for i in range(childrenIds.GetNumberOfIds()):
            childId = childrenIds.GetId(i)
            # Replace patient name with "Anonymous"
            if shNode.GetItemLevel(childId) == "Patient":
                shNode.SetItemName(childId, "Anonymous")
            # Remove all UIDs that start with DICOM (e.g., DICOM, DICOMInstanceUID)
            uidNames = shNode.GetItemUIDNames(childId)
            for uidName in uidNames:
                if uidName.startswith("DICOM"):
                    shNode.RemoveItemUID(childId, uidName)
            # Remove all attributes that start with DICOM (DICOM.ContentDate, DICOM.ContentTime, DICOM.FrameOfReferenceUID, etc.).
            attributeNames = shNode.GetItemAttributeNames(childId)
            for attributeName in attributeNames:
                if attributeName.startswith("DICOM"):
                    shNode.RemoveItemAttribute(childId, attributeName)


    def exportDisplacementFieldToNrrdStack(self,
                                           flowFieldNode: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode],
                                           exportDirectory: str) -> None:
        """Write each frame of the flow field into a separate NRRD file (transform_NN.nrrd for a transform,
        velocity_NN.nrrd for a vector volume flow field).
        """

        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        storeInTransform = self.isFlowFieldStoredInTransform(flowFieldNode)

        try:
            import nrrd
        except ImportError:
            slicer.util.pip_install('pynrrd')
            import nrrd

        originalItemNumber = sequenceBrowserNode.GetSelectedItemNumber()
        for itemNumber in range(sequenceBrowserNode.GetNumberOfItems()):
            sequenceBrowserNode.SetSelectedItemNumber(itemNumber)

            if storeInTransform:
                # Only "from parent" transform can be written to file, invert it temporarily
                flowFieldNode.Inverse()
                exportedFile = f"{exportDirectory}/transform_{itemNumber:02d}.nrrd"
            else:
                exportedFile = f"{exportDirectory}/velocity_{itemNumber:02d}.nrrd"
            slicer.util.exportNode(flowFieldNode, exportedFile)

            # Patch the written file
            readdata, header = nrrd.read(exportedFile)
            # remove intent code (used by nifti)
            header.pop('intent_code', None)
            # store voxel value units
            unitToMmPerSec = FlowLibraryBridge.velocityUnitScaleToMmPerSec(flowFieldNode)
            header['sample units'] = {1.0: "mm/s", 10.0: "cm/s", 1000.0: "m/s"}[unitToMmPerSec]
            if storeInTransform:
                header['TransformDirection'] = 'to parent'
            nrrd.write(exportedFile, readdata, header)

            if storeInTransform:
                # Revert the temporary inversion
                flowFieldNode.Inverse()

        sequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)

    def _createSpeedColorNode(self):
        """Create a color node that maps (absolute) speed to color.
        """
        colorNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLProceduralColorNode")
        colorNode.UnRegister(None)  # to prevent memory leaks
        colorNode.SetName(slicer.mrmlScene.GenerateUniqueName("Speed"))
        colorNode.SetAttribute("Category", "Flow")
        colorNode.SetAttribute("SlicerHeart.ColorMappingType", "Speed")
        # The color node is a procedural color node, which is saved using a storage node.
        # Hidden nodes are not saved if they use a storage node, therefore
        # the color node must be visible.
        colorNode.SetHideFromEditors(False)
        slicer.mrmlScene.AddNode(colorNode)
        # Add a transfer function with some default values
        colorMap = colorNode.GetColorTransferFunction()
        colorMap.AddRGBPoint(0.0, 0.0, 0.0, 0.0)
        colorMap.AddRGBPoint(1.5, 1.0, 1.0, 1.0)

        return colorNode

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

    def _flowFieldGeometryVolume(self, flowFieldNode):
        """Volume node (proxy) that defines the voxel grid of a flow field: the magnitude volume, or the input flow field."""
        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
        if magnitudeVolumeNode:
            return magnitudeVolumeNode
        return FlowLibraryBridge.rawFlowFieldNode(flowFieldNode)

    def _getComponentSegmentationNode(self, outputFlowField, component):
        """Phase wrap segmentation of an encoded velocity component of the output flow field (created if it does not exist).
        It is a segmentation sequence, browsed with the flow field, on the voxel grid of the flow field."""
        segmentationNode = outputFlowField.GetNthNodeReference("phaseWrapSegmentation", component)
        if segmentationNode:
            return segmentationNode

        geometryVolumeNode = self._flowFieldGeometryVolume(outputFlowField)
        inputSequenceNode = self._getSequenceFromProxyNode(FlowLibraryBridge.rawFlowFieldNode(outputFlowField))
        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(outputFlowField)
        # Create new segmentation node and add it to the sequence
        directionCode = FlowLibraryBridge.directionCodes(outputFlowField)[component]
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", f"Phase wrap C{component+1} {directionCode}")
        outputFlowField.SetNthNodeReferenceID("phaseWrapSegmentation", component, segmentationNode.GetID())
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(geometryVolumeNode)
        segmentationNode.CreateDefaultDisplayNodes()
        segmentationNode.GetDisplayNode().SetOpacity2DFill(0.2)
        segmentationNode.GetDisplayNode().SetSliceIntersectionThickness(5)
        segmentationSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", segmentationNode.GetName())
        segmentationSequenceNode.SetIndexType(inputSequenceNode.GetIndexType())
        segmentationSequenceNode.SetIndexName(inputSequenceNode.GetIndexName())
        segmentationSequenceNode.SetIndexUnit(inputSequenceNode.GetIndexUnit())
        sequenceBrowserNode.AddProxyNode(segmentationNode, segmentationSequenceNode, False)
        sequenceBrowserNode.PlaybackActiveOff()
        sequenceBrowserNode.SetRecording(segmentationSequenceNode, False)
        sequenceBrowserNode.SetSaveChanges(segmentationSequenceNode, True)
        sequenceBrowserNode.SetOverwriteProxyName(segmentationSequenceNode, True)  # show index in node name
        self._placeInSameFolder(segmentationNode, outputFlowField)
        return segmentationNode

    def getRawComponentVolume(self, flowFieldNode, component):
        """Scalar volume sequence (proxy node) of an encoded velocity component of the input flow field, as acquired (mm/s,
        aliased in [-venc, venc]), for display and for editing the phase wrap segmentations. It is created from the input
        flow field the first time it is requested, and it is browsed with the flow field."""
        inputFlowFieldNode = FlowLibraryBridge.rawFlowFieldNode(flowFieldNode)
        # One reference role per component (n-th references of a role cannot have gaps)
        componentVolumeNode = inputFlowFieldNode.GetNodeReference(f"rawComponentVolume{component}")
        if componentVolumeNode:
            return componentVolumeNode
        rawEncodedVelocity = FlowLibraryBridge.rawEncodedVelocity(inputFlowFieldNode)
        _, vencs, _ = FlowLibraryBridge.componentEncoding(inputFlowFieldNode)
        geometryVolumeNode = self._flowFieldGeometryVolume(inputFlowFieldNode)
        inputSequenceNode = self._getSequenceFromProxyNode(inputFlowFieldNode)
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(inputFlowFieldNode)
        name = f"{inputFlowFieldNode.GetName()} C{component + 1} {FlowLibraryBridge.directionCodes(inputFlowFieldNode)[component]}"
        componentVolumeNode = FlowLibraryBridge.createScalarVolumeSequenceInBrowser(
            name, rawEncodedVelocity[..., component], FlowLibraryBridge.voxelToWorld(geometryVolumeNode),
            FlowLibraryBridge.sequenceIndexValues(inputSequenceNode), browserNode=browserNode)
        inputFlowFieldNode.SetNodeReferenceID(f"rawComponentVolume{component}", componentVolumeNode.GetID())
        displayNode = componentVolumeNode.GetScalarVolumeDisplayNode()
        displayNode.InterpolateOff()  # wrapped voxels are seen better
        displayNode.AutoWindowLevelOff()
        displayNode.SetWindowLevelMinMax(-vencs[component], vencs[component])
        self._placeInSameFolder(componentVolumeNode, inputFlowFieldNode)
        return componentVolumeNode

    # def _getBackgroundCorrectionSegmentationNode(self, outputFlowField):
    #     segmentationNode = outputFlowField.GetNodeReference("backgroundCorrectionSegmentation")
    #     if segmentationNode:
    #         return segmentationNode

    #     magnitudeVolumeNode = outputFlowField.GetNthNodeReference("magnitudeVolume")

    #     sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(outputFlowField)
    #     # Create new segmentation node and add it to the sequence
    #     segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", f"Background subtraction")
    #     outputFlowField.SetNodeReferenceID("backgroundCorrectionSegmentation", segmentationNode.GetID())
    #     segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(magnitudeVolumeNode)
    #     segmentationNode.CreateDefaultDisplayNodes()
    #     segmentationNode.GetDisplayNode().SetOpacity2DFill(0.8)
    #     segmentationSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", segmentationNode.GetName())
    #     sequenceBrowserNode.AddProxyNode(segmentationNode, segmentationSequenceNode, False)
    #     sequenceBrowserNode.PlaybackActiveOff()
    #     sequenceBrowserNode.SetRecording(segmentationSequenceNode, False)
    #     sequenceBrowserNode.SetSaveChanges(segmentationSequenceNode, True)
    #     sequenceBrowserNode.SetOverwriteProxyName(segmentationSequenceNode, True)  # show index in node name

    #     # Place segmentation in the same subject hierarchy folder as the flow field node
    #     shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    #     parentItemId = shNode.GetItemParent(shNode.GetItemByDataNode(outputFlowField))
    #     shNode.SetItemParent(shNode.GetItemByDataNode(segmentationNode), parentItemId)

    #     return segmentationNode

    def _getSegmentIds(self):
        """In phase wrap segmentation, order of segments: no wrap = 0, positive wraps 1x = 1, 2x = 2, 3x = 3, ..., negative wraps 3x = 4, 2x = 5, 1x = 6, ..."""
        segmentIds = vtk.vtkStringArray()
        for wrap in range(self.maxWraps):
            segmentIds.InsertNextValue(f"Wrap-Neg-{wrap+1}x")
            segmentIds.InsertNextValue(f"Wrap-Pos-{wrap+1}x")
        return segmentIds

    def laplacianUnwrap(self, outputFlowField, unwrapMode=UnwrapModeEnum.LaplacianUnwrap, noiseMagnitudeThresholdPercent=5.0,
                        noiseMaskMethod=NoiseMaskMethodEnum.MagnitudeThreshold):
        """Compute the phase wrap segmentations by Laplacian phase unwrapping (slicerheart_4dflow), spatially (3D),
        spatiotemporally (4D), or spatially followed by temporal correction, depending on unwrapMode.
        Only voxels with signal (not noise) are unwrapped. Results can be edited in the phase wrap segmentations,
        as for temporal unwrapping. Returns warnings if the result is implausible (see checkPhaseUnwrapping).
        """
        method = unwrapMode.libraryMethod()
        if not method:
            raise ValueError(f"{unwrapMode} is not a Laplacian unwrapping method")
        library = FlowLibraryBridge.ensureLibrary()
        rawEncodedVelocity = FlowLibraryBridge.rawEncodedVelocity(outputFlowField)
        _, vencs, _ = FlowLibraryBridge.componentEncoding(outputFlowField)
        magnitude = FlowLibraryBridge.magnitudeArray(outputFlowField) if outputFlowField.GetNodeReference("magnitudeVolume") else None
        if magnitude is None:
            # Without magnitude images (e.g., velocity loaded from file) noise cannot be detected: all voxels are unwrapped
            signalMask = np.ones(rawEncodedVelocity.shape[1:4], bool)
        elif noiseMaskMethod == NoiseMaskMethodEnum.BockNoiseMask:
            # Before unwrapping, aliased voxels have high temporal velocity variation, so only the magnitude criterion is used
            signalMask = ~library.noise_mask(magnitude, rawEncodedVelocity, velocity_std_percentile=100.0)
        else:
            # Random phase in noise voxels inside the mask makes the Laplacian solve add false wraps, and the noise
            # magnitude threshold (a few percent of the range) keeps most of the air and low-signal tissue. Therefore only
            # voxels above the Otsu threshold of the time-averaged magnitude (body, separated from air) are unwrapped.
            meanMagnitude = magnitude.mean(axis=0)
            signalMask = ((meanMagnitude >= noiseMagnitudeThresholdPercent / 100 * self.magnitudeVolumeRange)
                          & (meanMagnitude > library.otsu_threshold(meanMagnitude)))
        self._log(f"Phase unwrapping ({method})...")
        voxelToWorld = FlowLibraryBridge.voxelToWorld(self._flowFieldGeometryVolume(outputFlowField))
        unwrapped = library.unwrap_velocity(rawEncodedVelocity, vencs, voxelToWorld, method=method, mask=signalMask, max_wraps=self.maxWraps)
        wrapCounts = np.rint((unwrapped - rawEncodedVelocity) / (2 * vencs)).astype(np.int8)
        wrapCounts[:, ~signalMask] = 0
        self.setWrapCounts(outputFlowField, wrapCounts)
        self._getSequenceFromProxyNode(outputFlowField).SetAttribute("SlicerHeart.phaseUnwrapping", unwrapMode.name)
        return self.checkPhaseUnwrapping(outputFlowField, wrapCounts, noiseMagnitudeThresholdPercent, unwrapMode)

    # Unwrapped blood speed above this is not physiological (mm/s): unwrapping has failed
    MAXIMUM_PLAUSIBLE_SPEED_MM_PER_SEC = 7000.0
    # Wraps should be resolved at the end of the cardiac cycle (late diastole, slow flow); wraps that remain in more than this
    # fraction of the signal voxels in the last frame are likely false wraps
    MAXIMUM_LAST_FRAME_WRAPPED_FRACTION = 0.01

    def checkPhaseUnwrapping(self, outputFlowField, wrapCounts, noiseMagnitudeThresholdPercent=5.0, unwrapMode=UnwrapModeEnum.TemporalUnwrap):
        """Check that the wraps give plausible velocities in voxels with signal (magnitude above the noise threshold).
        Returns a list of warning messages (empty if the result is plausible). The messages are also logged and stored in the
        SlicerHeart.phaseUnwrappingWarnings attribute of the flow field sequence."""
        rawEncodedVelocity = FlowLibraryBridge.rawEncodedVelocity(outputFlowField)
        _, vencs, _ = FlowLibraryBridge.componentEncoding(outputFlowField)
        if outputFlowField.GetNodeReference("magnitudeVolume"):
            signal = FlowLibraryBridge.magnitudeArray(outputFlowField) >= noiseMagnitudeThresholdPercent / 100 * self.magnitudeVolumeRange
        else:
            signal = np.ones(rawEncodedVelocity.shape[:4], bool)  # without magnitude images all voxels are checked
        peakSpeed = 0.0
        for frameIndex in range(wrapCounts.shape[0]):
            if not signal[frameIndex].any():
                continue
            speed = np.linalg.norm(rawEncodedVelocity[frameIndex] + 2 * vencs * wrapCounts[frameIndex], axis=-1)
            peakSpeed = max(peakSpeed, float(np.percentile(speed[signal[frameIndex]], 99.9)))
        lastFrameWrapped = np.any(wrapCounts[-1] != 0, axis=-1)[signal[-1]]
        lastFrameWrappedFraction = float(lastFrameWrapped.mean()) if lastFrameWrapped.size else 0.0
        recommendation = (" Laplacian 3D + temporal unwrapping (slicerheart_4dflow) is recommended."
                          if unwrapMode == UnwrapModeEnum.TemporalUnwrap else " Review the phase wrap segmentations.")
        warnings = []
        if peakSpeed > self.MAXIMUM_PLAUSIBLE_SPEED_MM_PER_SEC:
            warnings.append(f"Phase unwrapping ({unwrapMode.label()}) gives implausible velocities: {peakSpeed / 1000:.1f} m/s"
                            f" (99.9th percentile of the speed in voxels with signal; velocity encoding: {vencs.max() / 1000:.1f} m/s)."
                            + recommendation)
        if lastFrameWrappedFraction > self.MAXIMUM_LAST_FRAME_WRAPPED_FRACTION:
            warnings.append(f"Phase wraps remain in {100 * lastFrameWrappedFraction:.1f}% of the voxels with signal in the last frame,"
                            " where flow is expected to be slow. These are likely false wraps." + recommendation)
        for warning in warnings:
            logging.warning(warning)
        self._getSequenceFromProxyNode(outputFlowField).SetAttribute("SlicerHeart.phaseUnwrappingWarnings", json.dumps(warnings))
        return warnings

    def setWrapCounts(self, outputFlowField, wrapCounts):
        """Store phase wrap counts (t, k, j, i, component) int array in the phase wrap segmentations of the flow field.
        Positive values mean that 2 * venc has to be added to the encoded velocity component.
        """
        import numpy as np
        segmentIds = self._getSegmentIds()
        geometryVolumeNode = self._flowFieldGeometryVolume(outputFlowField)
        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(outputFlowField)
        originalItemNumber = sequenceBrowserNode.GetSelectedItemNumber()
        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "___temp2___")
        try:
            for component in range(3):
                segmentationNode = self._getComponentSegmentationNode(outputFlowField, component)
                for index in range(wrapCounts.shape[0]):
                    # The segmentation proxy node is updated, which is saved into the segmentation sequence
                    sequenceBrowserNode.SetSelectedItemNumber(index)
                    segmentationNode.GetSegmentation().RemoveAllSegments()

                    # Phase wrap map has no wrap 0, negative wraps -1, -2, ..., positive wraps 1, 2, ...
                    # Segment indices are all positive: 1x negative wrap, 1x positive wrap, 2x negative wrap, 2x positive wrap, etc. (see self._getSegmentIds)
                    phaseWrapSegmentation = wrapCounts[index, ..., component].astype(np.int8)

                    tooManyNegativeWrapsCount = np.count_nonzero(phaseWrapSegmentation < -self.maxWraps)
                    if tooManyNegativeWrapsCount > 0:
                        print(f"More than {self.maxWraps} negative wraparounds were found in component {component+1} in frame {index}: {tooManyNegativeWrapsCount} voxels")
                        phaseWrapSegmentation[phaseWrapSegmentation < -self.maxWraps] = -self.maxWraps

                    tooManyPositiveWrapsCount = np.count_nonzero(phaseWrapSegmentation > self.maxWraps)
                    if tooManyPositiveWrapsCount > 0:
                        print(f"More than {self.maxWraps} positive wraparounds found in component {component+1} in frame {index}: {tooManyPositiveWrapsCount} voxels")
                        phaseWrapSegmentation[phaseWrapSegmentation > self.maxWraps] = self.maxWraps

                    # Move up negative values to positive range, as segment indices should be all positive
                    phaseWrapSegmentation *= 2  # label values: -6 -4 -2 0 2 4 6
                    phaseWrapSegmentation[phaseWrapSegmentation < 0] += 1  # label values: -5 -3 -1 0 2 4 6
                    phaseWrapSegmentation[phaseWrapSegmentation < 0] *= -1  # label values: 0 1 2 3 4 5 6

                    slicer.util.updateVolumeFromArray(labelmapNode, phaseWrapSegmentation)
                    labelmapNode.CopyOrientation(geometryVolumeNode)
                    slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode, segmentIds)
                    slicer.app.processEvents()
        finally:
            slicer.mrmlScene.RemoveNode(labelmapNode)
            sequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)

    def getWrapCounts(self, outputFlowField):
        """Phase wrap counts (t, k, j, i, component) int8 array from the phase wrap segmentations of the flow field
        (None if there are no phase wrap segmentations)."""
        import numpy as np
        if not any(outputFlowField.GetNthNodeReference("phaseWrapSegmentation", component) for component in range(3)):
            return None
        inputSequenceNode = self._getSequenceFromProxyNode(FlowLibraryBridge.rawFlowFieldNode(outputFlowField))
        referenceVolumeNode = self._flowFieldGeometryVolume(outputFlowField)
        dims = referenceVolumeNode.GetImageData().GetDimensions()
        wrapCounts = np.zeros((inputSequenceNode.GetNumberOfDataNodes(), dims[2], dims[1], dims[0], 3), np.int8)
        # Segments are exported to a temporary labelmap volume node that has an editable (User type) color table in the
        # scene. Otherwise the export creates a color table for each segment in the scene of the segmentation, which for
        # sequence items is the internal scene of the sequence: the labelmap display node cannot find it (warnings for
        # each segment of each frame) and the color tables are left in the sequence.
        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "__temp_phase_wrap__")
        colorTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLColorTableNode", "__temp_phase_wrap_colors__")
        try:
            colorTableNode.SetTypeToUser()
            labelmapNode.CreateDefaultDisplayNodes()
            labelmapNode.GetDisplayNode().SetAndObserveColorNodeID(colorTableNode.GetID())
            for component in range(3):
                segmentationNode = outputFlowField.GetNthNodeReference("phaseWrapSegmentation", component)
                if not segmentationNode:
                    continue
                segmentationSequenceNode = self._getSequenceFromProxyNode(segmentationNode)
                for frameIndex in range(inputSequenceNode.GetNumberOfDataNodes()):
                    segmentationFrame = segmentationSequenceNode.GetDataNodeAtValue(inputSequenceNode.GetNthIndexValue(frameIndex))
                    if not segmentationFrame:
                        continue
                    segmentation = segmentationFrame.GetSegmentation()
                    for wrapIndex in range(1, self.maxWraps + 1):
                        for segmentId, wrapSign in [(f"Wrap-Neg-{wrapIndex}x", -1), (f"Wrap-Pos-{wrapIndex}x", +1)]:
                            if not segmentation.GetSegment(segmentId):
                                continue
                            if not slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                                    segmentationFrame, [segmentId], labelmapNode, referenceVolumeNode):
                                raise RuntimeError(f"Failed to export phase wrap segment {segmentId} of frame {frameIndex}")
                            wrapMask = slicer.util.arrayFromVolume(labelmapNode) > 0
                            wrapCounts[frameIndex, ..., component][wrapMask] += wrapSign * wrapIndex
        finally:
            slicer.mrmlScene.RemoveNode(labelmapNode.GetDisplayNode())
            slicer.mrmlScene.RemoveNode(labelmapNode)
            slicer.mrmlScene.RemoveNode(colorTableNode)
        return wrapCounts

    def resetUnwrap(self, outputFlowField):
        """Remove phase wrap segmentation nodes and sequences."""
        self._getSequenceFromProxyNode(outputFlowField).RemoveAttribute("SlicerHeart.phaseUnwrapping")
        for component in [2, 1, 0]:  # delete the last component first to avoid index shift
            segmentationNode = outputFlowField.GetNthNodeReference("phaseWrapSegmentation", component)
            if not segmentationNode:
                continue
            browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(segmentationNode)
            segmentationSequenceNode = browserNode.GetSequenceNode(segmentationNode)
            browserNode.RemoveSynchronizedSequenceNode(segmentationSequenceNode.GetID())
            slicer.mrmlScene.RemoveNode(segmentationNode)
            slicer.mrmlScene.RemoveNode(segmentationSequenceNode)

    def temporalUnwrap(self, outputFlowField, indexWithoutWrapping, noiseMagnitudeThresholdPercent):
        """
        indexWithoutWrapping: index of the frame that is assumet to not have any wraparounds
        noiseMagnitudeThresholdPercent: voxels with magnitude below this threshold are considered noise and are not used for phase unwrapping
        Returns warnings if the result is implausible (see checkPhaseUnwrapping): temporal unwrapping counts a wrap where
        the velocity changes by more than the velocity encoding between frames, so random phase noise in voxels with low
        signal accumulates false wraps over the cardiac cycle.
        """
        if indexWithoutWrapping != 0:
            raise RuntimeError("Temporal unwrapping is only implemented for the first frame")

        import numpy as np
        rawEncodedVelocity = FlowLibraryBridge.rawEncodedVelocity(outputFlowField)  # (t, k, j, i, 3) mm/s
        _, vencs, _ = FlowLibraryBridge.componentEncoding(outputFlowField)
        magnitude = FlowLibraryBridge.magnitudeArray(outputFlowField) if outputFlowField.GetNodeReference("magnitudeVolume") else None
        numberOfFrames = rawEncodedVelocity.shape[0]
        wrapCounts = np.zeros(rawEncodedVelocity.shape, dtype=np.int8)
        # Compute phase wrap map
        for component in range(3):
            values = None
            phaseWrapMap = np.zeros(rawEncodedVelocity.shape[1:4], dtype=np.int8)  # first frame is never wrapped around
            for index in range(indexWithoutWrapping, numberOfFrames):
                previousValues = values
                values = rawEncodedVelocity[index, ..., component].copy()
                if magnitude is not None:
                    values[magnitude[index] < noiseMagnitudeThresholdPercent / 100 * self.magnitudeVolumeRange] = 0
                if previousValues is not None:
                    phaseWrapMap = np.copy(phaseWrapMap)
                    # Unwrap by comparing with the previous frame
                    diff = values - previousValues
                    # Wrap negative (step down), for example (venc = 1000): -880 -960 [980]
                    phaseWrapMap[diff > vencs[component]] -= 1
                    # Wrap positive (step up), for example (venc = 1000): 900 980 [-960]
                    phaseWrapMap[diff < -vencs[component]] += 1
                wrapCounts[index, ..., component] = phaseWrapMap

        self.setWrapCounts(outputFlowField, wrapCounts)
        self._getSequenceFromProxyNode(outputFlowField).SetAttribute("SlicerHeart.phaseUnwrapping", UnwrapModeEnum.TemporalUnwrap.name)
        return self.checkPhaseUnwrapping(outputFlowField, wrapCounts, noiseMagnitudeThresholdPercent, UnwrapModeEnum.TemporalUnwrap)

    #
    # Quality checks (slicerheart_4dflow)
    #

    def getLumenMask(self, flowFieldNode, segmentationNode, segmentId):
        """Lumen mask (k, j, i) bool array on the voxel grid of the flow field, None if no segment is specified."""
        if not segmentationNode or not segmentId:
            return None
        if not segmentationNode.GetSegmentation().GetSegment(segmentId):
            raise ValueError(f"Segment {segmentId} is not found in {segmentationNode.GetName()}")
        return FlowLibraryBridge.maskFromSegment(segmentationNode, segmentId, FlowLibraryBridge.flowFieldGeometryNode(flowFieldNode))

    def heartRateBpm(self, flowFieldNode):
        """Heart rate stored in the magnitude volume sequence (set from DICOM NominalInterval or by the user), None if not available."""
        try:
            heartRateBpm = float(self._getSequenceAttribute(flowFieldNode.GetNodeReference("magnitudeVolume"), "SlicerHeart.heartRateBpm"))
        except (TypeError, ValueError, RuntimeError, AttributeError):
            return None
        return heartRateBpm if heartRateBpm > 0 else None

    @staticmethod
    def findFirstFlowFieldNode():
        """Return the first flow field in the scene that this module can process: a transform or vector volume node tagged
        with "SlicerHeart.Type"="FlowField", otherwise the first vector volume that looks like a velocity field (for
        example, loaded from file). Same as Analyze4DFlowLogic.findFirstFlowFieldNode, except that models are not used."""
        for nodeClassName in ["vtkMRMLTransformNode", "vtkMRMLVectorVolumeNode"]:
            for node in slicer.util.getNodesByClass(nodeClassName):
                if node.GetAttribute("SlicerHeart.Type") == "FlowField":
                    return node
        import Analyze4DFlow
        for vectorVolumeNode in slicer.util.getNodesByClass("vtkMRMLVectorVolumeNode"):
            if Analyze4DFlow.Analyze4DFlowLogic.isVelocityVectorVolume(vectorVolumeNode):
                return vectorVolumeNode
        return None

    @staticmethod
    def findFirstInputFlowFieldNode():
        """Return the first input flow field in the scene (velocity as acquired), otherwise the first flow field that can be
        used as input (see findFirstFlowFieldNode)."""
        for node in slicer.util.getNodesByClass("vtkMRMLVectorVolumeNode"):
            if node.GetAttribute("SlicerHeart.Type") == Import4DFlowLogic.RAW_FLOW_FIELD_TYPE or FlowLibraryBridge.isRawFlowField(node):
                return node
        flowFieldNode = Import4DFlowLogic.findFirstFlowFieldNode()
        if flowFieldNode is not None and flowFieldNode.GetNodeReference("inputFlowField"):
            return flowFieldNode.GetNodeReference("inputFlowField")
        return flowFieldNode

    @staticmethod
    def findOutputFlowFieldNode(inputFlowFieldNode):
        """Return the first output flow field that is computed from the input flow field (None if there is none)."""
        for nodeClassName in ["vtkMRMLVectorVolumeNode", "vtkMRMLTransformNode"]:
            for node in slicer.util.getNodesByClass(nodeClassName):
                if node.GetNodeReference("inputFlowField") is inputFlowFieldNode:
                    return node
        return None

    def setMagnitudeVolume(self, inputFlowFieldNode, magnitudeVolumeNode):
        """Set the magnitude images of an input flow field (and of the output flow fields computed from it).
        magnitudeVolumeNode must be the proxy node of a volume sequence with the same number of frames and voxel grid as
        the input flow field (or None, to remove the magnitude images). If the frame times (index values) of the two
        sequences are the same, the magnitude sequence is moved into the sequence browser of the input flow field, so that
        they are browsed together. Returns True if the sequence browsers were merged."""
        flowFieldNodes = [inputFlowFieldNode] + [node for className in ["vtkMRMLTransformNode", "vtkMRMLVectorVolumeNode"]
                                                 for node in slicer.util.getNodesByClass(className)
                                                 if node is not inputFlowFieldNode and node.GetNodeReference("inputFlowField") is inputFlowFieldNode]
        if magnitudeVolumeNode is None:
            for flowFieldNode in flowFieldNodes:
                flowFieldNode.RemoveNodeReferenceIDs("magnitudeVolume")
            return False

        sequencesLogic = slicer.modules.sequences.logic()
        inputBrowserNode = sequencesLogic.GetFirstBrowserNodeForProxyNode(inputFlowFieldNode)
        inputSequenceNode = inputBrowserNode.GetSequenceNode(inputFlowFieldNode) if inputBrowserNode else None
        magnitudeBrowserNode = sequencesLogic.GetFirstBrowserNodeForProxyNode(magnitudeVolumeNode)
        magnitudeSequenceNode = magnitudeBrowserNode.GetSequenceNode(magnitudeVolumeNode) if magnitudeBrowserNode else None
        if inputSequenceNode is None:
            raise ValueError(f"Input flow field {inputFlowFieldNode.GetName()} is not the proxy node of a sequence")
        if magnitudeSequenceNode is None:
            raise ValueError(f"Magnitude image {magnitudeVolumeNode.GetName()} is not the proxy node of a sequence")
        numberOfFrames = inputSequenceNode.GetNumberOfDataNodes()
        if magnitudeSequenceNode.GetNumberOfDataNodes() != numberOfFrames:
            raise ValueError(f"Magnitude image has {magnitudeSequenceNode.GetNumberOfDataNodes()} frames, but the input flow field has {numberOfFrames}")
        magnitudeDimensions = magnitudeSequenceNode.GetNthDataNode(0).GetImageData().GetDimensions()
        flowFieldDimensions = FlowLibraryBridge._flowFieldFrameArray(inputSequenceNode.GetNthDataNode(0)).shape[2::-1]
        if tuple(magnitudeDimensions) != tuple(flowFieldDimensions):
            raise ValueError(f"Magnitude image size {tuple(magnitudeDimensions)} is different from the input flow field size {tuple(flowFieldDimensions)}")

        for flowFieldNode in flowFieldNodes:
            flowFieldNode.SetNodeReferenceID("magnitudeVolume", magnitudeVolumeNode.GetID())

        # Browse them together if they have the same frame times
        if magnitudeBrowserNode is inputBrowserNode:
            return False

        def indexValues(sequenceNode):
            try:
                return np.array([float(sequenceNode.GetNthIndexValue(i)) for i in range(sequenceNode.GetNumberOfDataNodes())])
            except ValueError:
                return [sequenceNode.GetNthIndexValue(i) for i in range(sequenceNode.GetNumberOfDataNodes())]

        inputIndexValues, magnitudeIndexValues = indexValues(inputSequenceNode), indexValues(magnitudeSequenceNode)
        if isinstance(inputIndexValues, np.ndarray) and isinstance(magnitudeIndexValues, np.ndarray):
            sameIndexValues = np.allclose(inputIndexValues, magnitudeIndexValues, atol=1e-3)
        else:
            sameIndexValues = list(inputIndexValues) == list(magnitudeIndexValues)
        if not sameIndexValues or inputSequenceNode.GetIndexUnit() != magnitudeSequenceNode.GetIndexUnit():
            logging.info(f"Magnitude image {magnitudeVolumeNode.GetName()} has different frame times than the input flow field,"
                         " it is not moved into the sequence browser of the flow field")
            return False
        if magnitudeBrowserNode.GetNumberOfSynchronizedSequenceNodes() > 1:
            magnitudeBrowserNode.RemoveSynchronizedSequenceNode(magnitudeSequenceNode.GetID())
        else:
            slicer.mrmlScene.RemoveNode(magnitudeBrowserNode)
        inputBrowserNode.AddProxyNode(magnitudeVolumeNode, magnitudeSequenceNode, False)
        inputBrowserNode.SetSaveChanges(magnitudeSequenceNode, False)
        inputBrowserNode.SetRecording(magnitudeSequenceNode, False)
        sequencesLogic.UpdateProxyNodesFromSequences(inputBrowserNode)
        return True

    def markAsInputFlowField(self, flowFieldNode):
        """Use a velocity field (for example, loaded from file) as input flow field: velocity as acquired. If the velocity
        encoding is not known, it is estimated from the largest velocity of each component (see
        FlowLibraryBridge.vencEncodedMmPerSec). Returns the flow field."""
        if not flowFieldNode.IsA("vtkMRMLVectorVolumeNode"):
            raise ValueError("Only a vector volume sequence can be used as input flow field")
        FlowLibraryBridge.sequenceFromProxyNode(flowFieldNode).SetAttribute(FlowLibraryBridge.RAW_ROLE_ATTRIBUTE, "raw")
        flowFieldNode.SetAttribute("SlicerHeart.Type", self.RAW_FLOW_FIELD_TYPE)
        return flowFieldNode

    def computePcmra(self, flowFieldNode):
        """Velocity-weighted phase-contrast MR angiogram (k, j, i) of the flow field (Bock 2010)."""
        library = FlowLibraryBridge.ensureLibrary()
        velocity, _, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        return library.pcmra(FlowLibraryBridge.magnitudeArray(flowFieldNode), velocity).astype(np.float32)

    def createPcmraVolume(self, flowFieldNode, outputVolumeNode=None):
        """Create (or update) a scalar volume with the PC-MRA of the flow field. Returns the volume node."""
        pcmra = self.computePcmra(flowFieldNode)
        if outputVolumeNode is None:
            outputVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", slicer.mrmlScene.GenerateUniqueName(f"{flowFieldNode.GetName()} PC-MRA"))
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            shNode.SetItemParent(shNode.GetItemByDataNode(outputVolumeNode), shNode.GetItemParent(shNode.GetItemByDataNode(flowFieldNode)))
        slicer.util.updateVolumeFromArray(outputVolumeNode, pcmra)
        FlowLibraryBridge.setVoxelToWorld(outputVolumeNode, FlowLibraryBridge.voxelToWorld(FlowLibraryBridge.flowFieldGeometryNode(flowFieldNode)))
        outputVolumeNode.CreateDefaultDisplayNodes()
        return outputVolumeNode

    # Automatic lumen segmentation (slicerheart_4dflow.estimate_lumen): on a grid this many times finer than the image
    LUMEN_OVERSAMPLING = 2

    @staticmethod
    def estimateLumen(pcmra, voxelToWorld, velocity=None, magnitude=None, minimumComponentVolumeMl=1.0):
        """Automatic blood pool segmentation (slicerheart_4dflow.estimate_lumen): Otsu threshold of the log PC-MRA on a
        grid twice as fine as the image, grown toward the vessel wall into voxels with flow (if velocity, in mm/s, and
        magnitude are given), since the PC-MRA threshold alone cuts inside the wall. Growing requires the velocity noise,
        which is estimated in static tissue selected by the magnitude; if it cannot be estimated (for example, images
        without stationary tissue contrast) then only the PC-MRA threshold is used. A starting point for review and
        editing. Returns the dictionary of estimate_lumen (mask and voxel_to_world: fine grid, fraction and lumen: image
        grid) and grownToWall (True if the lumen was grown toward the vessel wall), growthSkippedReason."""
        library = FlowLibraryBridge.ensureLibrary()
        estimate = lambda velocity_t, magnitude_t: library.estimate_lumen(
            pcmra, voxelToWorld, velocity_t=velocity_t, magnitude_t=magnitude_t,
            oversampling=Import4DFlowLogic.LUMEN_OVERSAMPLING, minimum_component_ml=minimumComponentVolumeMl)
        if velocity is None:
            lumen = estimate(None, None)
            lumen.update(grownToWall=False, growthSkippedReason="velocity is not specified")
            return lumen
        try:
            lumen = estimate(velocity, magnitude)
            lumen.update(grownToWall=True, growthSkippedReason=None)
        except ValueError as e:
            logging.warning(f"Lumen is not grown toward the vessel wall ({e}), only the PC-MRA threshold is used")
            lumen = estimate(None, None)
            lumen.update(grownToWall=False, growthSkippedReason=str(e))
        return lumen

    def estimateLumenFromFlowField(self, flowFieldNode, minimumComponentVolumeMl=1.0):
        """estimateLumen from the PC-MRA, velocity and magnitude of a flow field."""
        library = FlowLibraryBridge.ensureLibrary()
        velocity, voxelToWorld, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        magnitude = FlowLibraryBridge.magnitudeArray(flowFieldNode)
        pcmra = library.pcmra(magnitude, velocity).astype(np.float32)
        return self.estimateLumen(pcmra, voxelToWorld, velocity, magnitude, minimumComponentVolumeMl)

    def createLumenSegmentation(self, flowFieldNode, segmentationNode=None, segmentId="lumen", returnEstimate=False):
        """Create (or replace) a lumen segment estimated from the flow field (see estimateLumen), on a grid twice as fine
        as the image (the segmentation keeps that resolution for editing). The segment is overwritten if it exists; a new
        segmentation is created if segmentationNode is None, and a new segment ("lumen") if segmentId is None.
        Returns (segmentationNode, segmentId), and the estimateLumen result if returnEstimate is True."""
        lumen = self.estimateLumenFromFlowField(flowFieldNode)
        if segmentationNode is None:
            segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", slicer.mrmlScene.GenerateUniqueName(f"{flowFieldNode.GetName()} lumen"))
            segmentationNode.CreateDefaultDisplayNodes()
            self._placeInSameFolder(segmentationNode, flowFieldNode)
        if not segmentId:
            segmentId = segmentationNode.GetSegmentation().GenerateUniqueSegmentID("lumen")
        FlowLibraryBridge.setSegmentFromMask(segmentationNode, segmentId, lumen["mask"], lumen["voxel_to_world"], name="lumen")
        if returnEstimate:
            return segmentationNode, segmentId, lumen
        return segmentationNode, segmentId

    def checkEncodingDirections(self, flowFieldNode, lumenMask=None):
        """Check that the velocity component directions and signs are consistent with mass conservation
        (slicerheart_4dflow.encoding_check): all 48 signed permutations of the components are ranked by the
        divergence of the time-averaged velocity in the lumen. If no lumen mask is given, it is estimated from the PC-MRA.
        Returns the encoding_check result dictionary (best mapping, 'consistent', 'conclusive', 'note')."""
        library = FlowLibraryBridge.ensureLibrary()
        velocity, voxelToWorld, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        if lumenMask is None:
            if not flowFieldNode.GetNodeReference("magnitudeVolume"):
                raise ValueError("The lumen cannot be estimated, because the flow field has no magnitude image. Select a lumen segmentation.")
            lumenMask = self.estimateLumenFromFlowField(flowFieldNode)["lumen"]
        return library.encoding_check(velocity, lumenMask, voxelToWorld)

    @staticmethod
    def encodingCheckSummary(result):
        """Human-readable summary of a checkEncodingDirections result."""
        permutation, signs = result["best"]
        axisNames = "RAS"
        bestMapping = ", ".join(f"{'-' if sign < 0 else '+'}{axisNames[axis]}" for axis, sign in zip(permutation, signs))
        status = "consistent" if result["consistent"] else "INCONSISTENT"
        if not result.get("conclusive", True):
            status += " (inconclusive)"
        return (f"Velocity encoding directions: {status}.\n"
                f"Lowest divergence mapping of components (R, A, S): {bestMapping}"
                f" (divergence ratio of the current mapping to the best: {result['ratio']:.2f}).\n{result.get('note', '')}")

    def computeQualityReport(self, flowFieldNode, lumenMask=None, studyId=None):
        """Quality report of the flow field (slicerheart_4dflow.quality_report): venc adequacy, velocity noise,
        residual background offset, divergence, encoding. Returns the report dictionary."""
        library = FlowLibraryBridge.ensureLibrary()
        rawVelocity = FlowLibraryBridge.rawWorldVelocity(flowFieldNode)
        velocity, voxelToWorld, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        magnitude = FlowLibraryBridge.magnitudeArray(flowFieldNode)
        _, vencs, _ = FlowLibraryBridge.componentEncoding(flowFieldNode)
        wrapCounts = self.getWrapCounts(flowFieldNode)
        if wrapCounts is not None:
            wrapCounts = wrapCounts * np.diag(FlowLibraryBridge.encodingToWorld(flowFieldNode)).astype(np.int8)
        heartRateBpm = self.heartRateBpm(flowFieldNode)
        return library.quality_report(rawVelocity, velocity, magnitude, vencs, voxelToWorld, lumen_mask=lumenMask,
                                      wrap_count=wrapCounts, study_id=studyId or flowFieldNode.GetName(),
                                      rr_ms=60000.0 / heartRateBpm if heartRateBpm else None)

    @staticmethod
    def qualityReportToMarkdown(report):
        library = FlowLibraryBridge.ensureLibrary()
        return library.to_markdown(report)

    @staticmethod
    def qualityReportToTable(report, tableNode):
        """Write the quality report as a two-column (item, value) table."""
        rows = []

        def flatten(prefix, value):
            if isinstance(value, dict):
                for key, item in value.items():
                    flatten(f"{prefix}.{key}" if prefix else str(key), item)
            elif isinstance(value, (list, tuple)) and value and all(isinstance(item, (int, float, np.number)) for item in value):
                rows.append((prefix, ", ".join(f"{float(item):.4g}" for item in value)))
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    flatten(f"{prefix}[{index}]", item)
            elif isinstance(value, (bool, np.bool_)):
                rows.append((prefix, "yes" if value else "no"))
            elif isinstance(value, (int, float, np.number)):
                rows.append((prefix, f"{float(value):.4g}"))
            elif value is not None:
                rows.append((prefix, str(value)))

        flatten("", report)
        FlowLibraryBridge.updateTableFromColumns(tableNode, {"Item": [r[0] for r in rows], "Value": [r[1] for r in rows]})
        return tableNode

    #
    # Test cases in Slicer-native file format, for testing slicerheart_4dflow (and this module) without DICOM import
    #

    # Test case data set (format version 4, read by slicerheart_4dflow.slicer_io): manifest.json at the root describes the
    # data set; inputs/<case>/ holds what the processing starts from: acquisition/ (data converted from DICOM without any
    # processing, and the description of the acquisition), annotations/ (lumen segmentation and measurement planes,
    # annotations.json describes how they were created) and optional references/<source>/flows.json (plane flows measured
    # independently, not written by SlicerHeart); outputs/<case>/ holds the results of the processing and its
    # description. The case ID is the name of the case folder. File names are those of slicerheart_4dflow.slicer_io.
    TEST_CASE_FORMAT_VERSION = 4
    TEST_CASE_LUMEN_FILE = "lumen.seg.nrrd"

    @staticmethod
    def testCasePath(datasetDirectory, caseId, key):
        """Path of a file of a test case: "manifest" (of the data set), a key of slicerheart_4dflow.slicer_io.INPUT_FILES
        (in inputs/<case>) or of OUTPUT_FILES (in outputs/<case>)."""
        slicerIo = FlowLibraryBridge.ensureLibrary().slicer_io
        if key == "manifest":
            return os.path.join(datasetDirectory, slicerIo.DATASET_MANIFEST)
        inputDirectory, outputDirectory = slicerIo.case_directories(datasetDirectory, caseId)
        if key in slicerIo.INPUT_FILES:
            return os.path.join(str(inputDirectory), slicerIo.INPUT_FILES[key])
        return os.path.join(str(outputDirectory), slicerIo.OUTPUT_FILES[key])

    @staticmethod
    def testCaseAnnotationsDirectory(datasetDirectory, caseId):
        slicerIo = FlowLibraryBridge.ensureLibrary().slicer_io
        return os.path.join(str(slicerIo.case_directories(datasetDirectory, caseId)[0]), slicerIo.ANNOTATIONS_DIR)

    @staticmethod
    def testCaseRelativePath(datasetDirectory, caseId, key):
        """Path of a file of a test case relative to the data set (as recorded in annotations.json)."""
        return os.path.relpath(Import4DFlowLogic.testCasePath(datasetDirectory, caseId, key), datasetDirectory).replace(os.sep, "/")

    @staticmethod
    def testCaseFromDirectory(directory):
        """(data set folder, case ID) of a case folder (inputs/<case> or outputs/<case> of a test case data set).
        Raises ValueError if the folder is not a case folder of a data set."""
        slicerIo = FlowLibraryBridge.ensureLibrary().slicer_io
        directory = os.path.normpath(directory)
        caseId = os.path.basename(directory)
        area = os.path.basename(os.path.dirname(directory))
        datasetDirectory = os.path.dirname(os.path.dirname(directory))
        if area not in (slicerIo.INPUTS_DIR, slicerIo.OUTPUTS_DIR) or not os.path.isfile(os.path.join(datasetDirectory, slicerIo.DATASET_MANIFEST)):
            raise ValueError(f"{directory} is not a case folder of a test case data set (inputs/<case> or outputs/<case>,"
                             f" with {slicerIo.DATASET_MANIFEST} in the data set folder)")
        return datasetDirectory, caseId

    @staticmethod
    def nextTestCaseId(datasetDirectory, prefix="Case"):
        """A case ID that is not used in the data set yet: prefix followed by a 4-digit number."""
        slicerIo = FlowLibraryBridge.ensureLibrary().slicer_io
        used = set(slicerIo.dataset_cases(datasetDirectory)) if os.path.isdir(datasetDirectory) else set()
        number = 1
        while f"{prefix}{number:04d}" in used:
            number += 1
        return f"{prefix}{number:04d}"

    @staticmethod
    def readTestCaseJson(datasetDirectory, caseId, key, default=None):
        """Read a JSON file of a test case (see testCasePath). Returns default if the file does not exist."""
        path = Import4DFlowLogic.testCasePath(datasetDirectory, caseId, key)
        if not os.path.isfile(path):
            return default
        with open(path, encoding="utf-8") as file:
            return json.load(file)

    @staticmethod
    def writeTestCaseJson(datasetDirectory, caseId, key, content):
        """Write a JSON file of a test case (see testCasePath)."""
        path = Import4DFlowLogic.testCasePath(datasetDirectory, caseId, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as file:
            json.dump(content, file, indent=2)
            file.write("\n")

    @staticmethod
    def testCaseSoftware(moduleName):
        """Software description for the test case description files."""
        library = FlowLibraryBridge.ensureLibrary()
        return {"name": f"SlicerHeart {moduleName}", "slicer": slicer.app.applicationVersion, "slicerheart_4dflow": library.__version__}

    @staticmethod
    def testCaseAnnotationDescription(method, software, algorithm=None):
        """Description of how an annotation of a test case was created (stored in annotations/annotations.json).
        method: "automatic" or "manual"; algorithm: name, description, parameters, inputs (only for automatic annotations).
        Whether a person has reviewed the annotation ("reviewed") and whether it was edited (method "automatic, manually edited")
        is set by that person in annotations.json."""
        description = {"method": method, "reviewed": False, "software": software}
        if algorithm:
            description["algorithm"] = algorithm
        return description

    @staticmethod
    def createVelocityQuantity():
        """Coded entry that describes velocity voxel values (vtkMRMLScalarVolumeNode.SetVoxelValueQuantity).
        Slicer writes it into the "labels" field of the component axis in NRRD files (Slicer versions that support it)."""
        quantity = slicer.vtkCodedEntry()
        quantity.SetValueSchemeMeaning("velocity", "", "velocity")
        return quantity

    @staticmethod
    def _volumeNodeFromArray(array, voxelToWorld, vector=False, velocity=False, spatial=True):
        """Volume node (not in the scene) with a copy of the array (k, j, i) or (k, j, i, 3) for vectors.
        Spatial vectors have RAS components (converted to LPS when written to file, with a measurement frame); other vectors
        (spatial=False), such as values per velocity encoding direction, are written as they are.
        If velocity is set then the voxel value quantity is velocity and the unit is mm/s."""
        import vtk.util.numpy_support
        array = np.ascontiguousarray(array)
        imageData = vtk.vtkImageData()
        imageData.SetDimensions(array.shape[2], array.shape[1], array.shape[0])
        vtkArray = vtk.util.numpy_support.numpy_to_vtk(array.reshape(-1, 3) if vector else array.reshape(-1), deep=True,
                                                     array_type=vtk.util.numpy_support.get_vtk_array_type(array.dtype))
        imageData.GetPointData().SetScalars(vtkArray)
        volumeNode = slicer.vtkMRMLVectorVolumeNode() if vector else slicer.vtkMRMLScalarVolumeNode()
        volumeNode.SetAndObserveImageData(imageData)
        FlowLibraryBridge.setVoxelToWorld(volumeNode, voxelToWorld)
        if vector and spatial:
            # Spatial vectors are converted from RAS to LPS when written to file
            volumeNode.SetVoxelVectorType(slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial)
        if velocity:
            volumeNode.SetVoxelValueQuantity(Import4DFlowLogic.createVelocityQuantity())
            velocityUnits = slicer.vtkCodedEntry()
            velocityUnits.SetValueSchemeMeaning("mm/s", "UCUM", "millimeter per second")
            volumeNode.SetVoxelValueUnits(velocityUnits)
        return volumeNode

    def _writeVolumeSequenceFile(self, path, arrays_t, voxelToWorld, indexValues, vector=False, velocity=False, spatial=True):
        """Write a volume sequence (.seq.nrrd) from arrays (t, k, j, i) or (t, k, j, i, 3) (vectors; spatial vectors have RAS
        components). Note: Slicer 5.12 writes no file for 8-bit integer vector volume sequences, use 16-bit integers."""
        sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "__temp_export__")
        storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVolumeSequenceStorageNode")
        try:
            sequenceNode.SetIndexName("time")
            sequenceNode.SetIndexUnit("ms")
            sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.NumericIndex)
            for frameIndex in range(arrays_t.shape[0]):
                sequenceNode.SetDataNodeAtValue(self._volumeNodeFromArray(arrays_t[frameIndex], voxelToWorld, vector, velocity, spatial),
                                                f"{float(indexValues[frameIndex]):g}")
            storageNode.SetFileName(path)
            # WriteData may report success without writing the file (for example, for 8-bit integer vector volumes)
            if not storageNode.WriteData(sequenceNode) or not os.path.isfile(path):
                raise RuntimeError(f"Failed to write {path}: {storageNode.GetUserMessages().GetAllMessagesAsString()}")
        finally:
            slicer.mrmlScene.RemoveNode(storageNode)
            slicer.mrmlScene.RemoveNode(sequenceNode)

    def _dicomMetadata(self, flowFieldNode):
        """Non-identifying acquisition metadata (vendor, scanner model, software version, field strength) from the DICOM
        header of the magnitude image, if it is available in the DICOM database."""
        metadata = {}
        try:
            magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            instanceUIDs = shNode.GetItemUID(shNode.GetItemByDataNode(magnitudeVolumeNode), "DICOMInstanceUID")
            filename = slicer.dicomDatabase.fileForInstance(instanceUIDs.split()[0]) if instanceUIDs and slicer.dicomDatabase else None
            if filename:
                import pydicom
                ds = pydicom.dcmread(filename, stop_before_pixels=True)
                metadata = {
                    "vendor": str(ds.get("Manufacturer", "")).strip().split()[0].lower() if ds.get("Manufacturer") else "unknown",
                    "scanner": " ".join(str(ds.get(tag, "")).strip() for tag in ("Manufacturer", "ManufacturerModelName")).strip(),
                    "software_version": str(ds.get("SoftwareVersions", "")).strip(),
                    "field_strength_t": float(ds.MagneticFieldStrength) if "MagneticFieldStrength" in ds else None,
                }
        except Exception as e:
            logging.debug(f"DICOM metadata is not available: {e}")
        return metadata

    # Default processing of test cases (exported from DICOM, or outputs regenerated from the inputs)
    TEST_CASE_DEFAULT_UNWRAP_MODE = "LaplacianThenTemporalUnwrap"
    TEST_CASE_NOISE_MAGNITUDE_THRESHOLD_PERCENT = 5.0
    TEST_CASE_STATIONARY_TISSUE_SPEED_THRESHOLD_VENC_PERCENT = 10.0

    def applyDefaultTestCaseProcessing(self, flowFieldNode, unwrapMode=None):
        """Process a flow field as the test cases are processed: phase unwrapping (unwrapMode, a name of UnwrapModeEnum;
        default TEST_CASE_DEFAULT_UNWRAP_MODE) and a quadratic background fit."""
        mode = UnwrapModeEnum[unwrapMode or self.TEST_CASE_DEFAULT_UNWRAP_MODE]
        threshold = self.TEST_CASE_NOISE_MAGNITUDE_THRESHOLD_PERCENT
        if mode == UnwrapModeEnum.TemporalUnwrap:
            self.temporalUnwrap(flowFieldNode, 0, threshold)
        else:
            self.laplacianUnwrap(flowFieldNode, mode, threshold)
        self.updateFlowFieldFromComponentVolumes(flowFieldNode, threshold, BackgroundSubtractionMethodEnum.QuadraticFit,
                                                 self.TEST_CASE_STATIONARY_TISSUE_SPEED_THRESHOLD_VENC_PERCENT)

    def exportTestCase(self, flowFieldNode, datasetDirectory, caseId, lumenSegmentationNode=None, lumenSegmentId=None, metadata=None,
                       overwriteLumen=False):
        """Write the flow field as a test case of a data set in 3D Slicer native file formats, which can be read without
        Slicer by slicerheart_4dflow.slicer_io.load_case and loaded into Slicer by loadTestCase (layout: see testCasePath and
        slicerheart_4dflow tests/clinical/README.md): the inputs (writeTestCaseInputs), the lumen (writeTestCaseLumen) and the
        outputs of the processing (writeTestCaseOutputs). Measurement planes and plane flows are written by
        Analyze4DFlowLogic.writeTestCaseFlows. Returns the path of the inputs folder of the case."""
        self._log(f"Writing test case {caseId} to {datasetDirectory}...")
        arrays = self.writeTestCaseInputs(flowFieldNode, datasetDirectory, caseId, metadata)
        outputs = self.writeTestCaseOutputs(flowFieldNode, datasetDirectory, caseId)
        self.writeTestCaseLumen(datasetDirectory, caseId, flowFieldNode, lumenSegmentationNode, lumenSegmentId, overwriteLumen,
                                pcmra=outputs["pcmra"], velocity=outputs["velocity"], magnitude=arrays["magnitude"],
                                voxelToWorld=arrays["voxelToWorld"])
        return os.path.dirname(os.path.dirname(self.testCasePath(datasetDirectory, caseId, "acquisition")))

    def writeTestCaseInputs(self, flowFieldNode, datasetDirectory, caseId, metadata=None):
        """Write the acquisition of a test case (inputs/<case>/acquisition: magnitude and raw velocity as acquired, the
        description of the acquisition), and the manifest of the data set if it does not have one yet.
        Only image data and geometry are written (no DICOM header fields, names, dates, or UIDs), the case is identified
        by caseId. Velocities are in mm/s; vector components are LPS in the files (as any Slicer volume file).
        metadata: additional fields of the acquisition description, for example from _dicomMetadata.
        Returns dict: magnitude (t, k, j, i) float32, voxelToWorld (RAS)."""
        path = lambda key: self.testCasePath(datasetDirectory, caseId, key)
        os.makedirs(os.path.dirname(path("acquisition")), exist_ok=True)
        geometryNode = FlowLibraryBridge.flowFieldGeometryNode(flowFieldNode)
        voxelToWorld = FlowLibraryBridge.voxelToWorld(geometryNode)
        _, _, timesMs = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        magnitudeSequenceNode = self._getSequenceFromProxyNode(flowFieldNode.GetNodeReference("magnitudeVolume"))
        magnitudeFrames = np.stack([slicer.util.arrayFromVolume(magnitudeSequenceNode.GetNthDataNode(i))
                                    for i in range(magnitudeSequenceNode.GetNumberOfDataNodes())])
        encodingToWorld = FlowLibraryBridge.encodingToWorld(flowFieldNode)
        rawVelocity = FlowLibraryBridge.rawWorldVelocity(flowFieldNode)
        self._writeVolumeSequenceFile(path("magnitude"), magnitudeFrames, voxelToWorld, timesMs)
        self._writeVolumeSequenceFile(path("velocity_raw"), rawVelocity, voxelToWorld, timesMs, vector=True, velocity=True)

        scales, vencs, invertToRas = FlowLibraryBridge.componentEncoding(flowFieldNode)
        directionCodes = FlowLibraryBridge.directionCodes(flowFieldNode)
        lpsFromRas = np.diag([-1.0, -1.0, 1.0])
        componentEncodings = []
        for component in range(3):
            componentEncodings.append({
                "direction_code": directionCodes[component],
                # Stored value of the component images that corresponds to the velocity encoding
                "max_value": float(vencs[component] / scales[component]),
                "invert_to_ras": bool(invertToRas[component]),
                })
        heartRateBpm = self.heartRateBpm(flowFieldNode)
        acquisition = {
            "vendor": "unknown",
            "scanner": "",
            "software_version": "",
            "rr_ms": 60000.0 / heartRateBpm if heartRateBpm else None,
            # Velocity encoding of the encoded components (columns of encoding_to_world), in mm/s
            "venc_encoded_mm_s": [float(v) for v in vencs],
            # Columns: LPS directions of the encoded (acquired) velocity components
            "encoding_to_world": (lpsFromRas @ encodingToWorld).tolist(),
            "component_encoding": componentEncodings,
            }
        acquisition.update(self._dicomMetadata(flowFieldNode))
        if metadata:
            acquisition.update(metadata)
        self.writeTestCaseJson(datasetDirectory, caseId, "acquisition", acquisition)

        if not os.path.isfile(path("manifest")):
            self.writeTestCaseJson(datasetDirectory, caseId, "manifest", {
                "format_version": self.TEST_CASE_FORMAT_VERSION,
                "name": os.path.basename(os.path.normpath(datasetDirectory)),
                "license": "internal",
                "doi": None,
                })
        return {"magnitude": magnitudeFrames.astype(np.float32), "voxelToWorld": voxelToWorld}

    def writeTestCaseOutputs(self, flowFieldNode, datasetDirectory, caseId):
        """Write the outputs of the processing of a test case (outputs/<case>: processed velocity, wrap counts, PC-MRA, the
        description of the processing). The plane flows and the quality report are written by
        Analyze4DFlowLogic.writeTestCaseFlows. Returns dict: velocity (t, k, j, i, 3) mm/s RAS, pcmra."""
        library = FlowLibraryBridge.ensureLibrary()
        path = lambda key: self.testCasePath(datasetDirectory, caseId, key)
        os.makedirs(os.path.dirname(path("velocity")), exist_ok=True)
        geometryNode = FlowLibraryBridge.flowFieldGeometryNode(flowFieldNode)
        voxelToWorld = FlowLibraryBridge.voxelToWorld(geometryNode)
        velocity, _, timesMs = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        wrapCountsEncoded = self.getWrapCounts(flowFieldNode)
        if wrapCountsEncoded is None:
            wrapCountsEncoded = np.zeros(velocity.shape, np.int8)
        self._writeVolumeSequenceFile(path("velocity"), velocity, voxelToWorld, timesMs, vector=True, velocity=True)
        # Wrap counts are integers per velocity encoding direction (component c: encoding_to_world[:, c]), not spatial vectors
        self._writeVolumeSequenceFile(path("wrap_count"), wrapCountsEncoded.astype(np.int16), voxelToWorld, timesMs, vector=True, spatial=False)
        magnitude = FlowLibraryBridge.magnitudeArray(flowFieldNode)
        pcmra = library.pcmra(magnitude, velocity).astype(np.float32)
        pcmraNode = self._volumeNodeFromArray(pcmra, voxelToWorld)
        slicer.mrmlScene.AddNode(pcmraNode)
        try:
            if not slicer.util.saveNode(pcmraNode, path("pcmra")):
                raise RuntimeError(f"Failed to write {path('pcmra')}")
        finally:
            slicer.mrmlScene.RemoveNode(pcmraNode)
        flowFieldSequenceNode = self._getSequenceFromProxyNode(flowFieldNode)
        self.writeTestCaseJson(datasetDirectory, caseId, "processing", {
            "software": {"slicer": slicer.app.applicationVersion, "slicerheart_4dflow": library.__version__},
            "processing": json.loads(flowFieldSequenceNode.GetAttribute("SlicerHeart.processing") or "{}"),
            # Plausibility warnings of the phase unwrapping (see checkPhaseUnwrapping), empty if the result is plausible
            "phase_unwrapping_warnings": json.loads(flowFieldSequenceNode.GetAttribute("SlicerHeart.phaseUnwrappingWarnings") or "[]"),
            })
        return {"velocity": velocity, "pcmra": pcmra}

    def exportTestCaseWithFlows(self, flowFieldNode, datasetDirectory, caseId, lumenSegmentationNode=None, lumenSegmentId=None,
                                planeNodes=None, metadata=None):
        """Export a test case (exportTestCase), then write measurement planes (automatically placed if not specified
        and the case has none yet) and plane flows computed by Analyze 4D Flow (Analyze4DFlowLogic.writeTestCaseFlows).
        Returns the path of the inputs folder of the case."""
        caseDirectory = self.exportTestCase(flowFieldNode, datasetDirectory, caseId, lumenSegmentationNode or None,
                                            lumenSegmentId or None, metadata)
        import Analyze4DFlow
        Analyze4DFlow.Analyze4DFlowLogic().writeTestCaseFlows(datasetDirectory, caseId, flowFieldNode, planeNodes)
        return caseDirectory

    def writeTestCaseLumen(self, datasetDirectory, caseId, flowFieldNode, lumenSegmentationNode=None, lumenSegmentId=None,
                           overwriteLumen=False, pcmra=None, velocity=None, magnitude=None, voxelToWorld=None):
        """Write the lumen segmentation of a test case (inputs/<case>/annotations/lumen.seg.nrrd) and its description in
        annotations.json: the specified segment (in its own resolution), otherwise the existing lumen of the case
        (which may have been edited by the user) unless overwriteLumen is set, otherwise the automatic lumen (estimateLumen,
        on a grid twice as fine as the image). pcmra, velocity (mm/s), magnitude and voxelToWorld are computed from the flow
        field if not given. Returns True if the lumen file was written."""
        annotations = self.readTestCaseJson(datasetDirectory, caseId, "annotations", {})
        lumenPath = os.path.join(self.testCaseAnnotationsDirectory(datasetDirectory, caseId), self.TEST_CASE_LUMEN_FILE)
        os.makedirs(os.path.dirname(lumenPath), exist_ok=True)
        written = True
        if lumenSegmentationNode and lumenSegmentId:
            # In the resolution of the segmentation (which may be finer than the image)
            lumenMask, lumenVoxelToWorld = FlowLibraryBridge.segmentLabelmap(lumenSegmentationNode, lumenSegmentId)
            if lumenMask is None:
                raise ValueError(f"Lumen segment {lumenSegmentId} is empty")
            self._writeLumenSegmentation(lumenPath, lumenMask, lumenVoxelToWorld)
            annotations["lumen"] = self.testCaseAnnotationDescription("manual", self.testCaseSoftware("Import 4D Flow"))
        elif os.path.isfile(lumenPath) and annotations.get("lumen") and not overwriteLumen:
            written = False  # keep the existing lumen segmentation and its description
        else:
            if velocity is None or magnitude is None or voxelToWorld is None:
                library = FlowLibraryBridge.ensureLibrary()
                velocity, voxelToWorld, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
                magnitude = FlowLibraryBridge.magnitudeArray(flowFieldNode)
            if pcmra is None:
                pcmra = FlowLibraryBridge.ensureLibrary().pcmra(magnitude, velocity).astype(np.float32)
            minimumComponentVolumeMl = 1.0
            lumen = self.estimateLumen(pcmra, voxelToWorld, velocity, magnitude, minimumComponentVolumeMl)
            self._writeLumenSegmentation(lumenPath, lumen["mask"], lumen["voxel_to_world"])
            # Growth is computed with the default growth noise factor of the installed slicerheart_4dflow version
            import inspect
            growthNoiseFactor = inspect.signature(FlowLibraryBridge.ensureLibrary().estimate_lumen).parameters["growth_noise_factor"].default
            annotations["lumen"] = self.testCaseAnnotationDescription("automatic", self.testCaseSoftware("Import 4D Flow"), {
                "name": "slicerheart_4dflow.estimate_lumen",
                "description": "Otsu threshold of the log PC-MRA within the bright half of the image, on a grid twice as fine as the"
                               " image (resampled with VTK), opening and closing by one image voxel, connected components of at least"
                               " the minimum volume that are not mostly at the image border, holes filled slice by slice"
                               + ("; then grown toward the vessel wall, by at most 1.5 image voxels, into voxels whose RMS speed over"
                                  f" the cycle is above {growthNoiseFactor:g} times that of the velocity noise" if lumen["grownToWall"] else
                                  f" (not grown toward the vessel wall: {lumen['growthSkippedReason']})")
                               + ". Meant as a starting point for review and editing.",
                "parameters": dict({"minimumComponentVolumeMl": minimumComponentVolumeMl, "oversampling": self.LUMEN_OVERSAMPLING},
                                   **({"growthVoxels": 1.5, "growthNoiseFactor": growthNoiseFactor} if lumen["grownToWall"] else {"grownToWall": False})),
                # the files it was computed from (relative to the data set), as they were at this time
                "inputs": [self.testCaseRelativePath(datasetDirectory, caseId, key) for key in ("pcmra", "velocity", "magnitude")],
                })
        annotations["lumen"] = dict({"file": self.TEST_CASE_LUMEN_FILE, "segment": "lumen"}, **annotations["lumen"])
        self.writeTestCaseJson(datasetDirectory, caseId, "annotations", annotations)
        return written

    def _writeLumenSegmentation(self, path, mask, voxelToWorld):
        """Write a lumen mask on the grid of voxelToWorld (IJK to RAS; may be finer than the image) as a segmentation."""
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "lumen")
        try:
            FlowLibraryBridge.setSegmentFromMask(segmentationNode, "lumen", mask, voxelToWorld, name="lumen")
            if not slicer.util.saveNode(segmentationNode, path):
                raise RuntimeError(f"Failed to write {path}")
        finally:
            slicer.mrmlScene.RemoveNode(segmentationNode)

    def loadTestCase(self, datasetDirectory, caseId, applyProcessing=True, useOutputs=True, unwrapMode=None):
        """Load a test case written by exportTestCase into the scene, without DICOM import.

        The magnitude images are loaded as a volume sequence and the raw velocity (as acquired) as the input flow field, so
        all Import 4D Flow processing can be applied to the output flow field. If useOutputs is set and the case has outputs, the phase wrap segmentations are restored
        from its wrap counts and the flow field is computed with the processing settings recorded in processing.json, which
        reproduces the outputs (for review). Otherwise only the inputs are used: the flow field is processed with the
        default processing of test cases (applyDefaultTestCaseProcessing, unwrapMode), as for regenerating the outputs.
        Processing is applied only if applyProcessing is set.
        The lumen segmentation and measurement planes are loaded from their files, so that after editing they can be
        saved back to the test case (File / Save data).

        Returns a dictionary: flowFieldNode (output flow field), inputFlowFieldNode, magnitudeVolumeNode, lumenSegmentationNode,
        planeNodes (list), manifest, acquisition, processing, annotations.
        """
        library = FlowLibraryBridge.ensureLibrary()
        case = library.load_case(datasetDirectory, caseId, world="RAS")
        useOutputs = useOutputs and case["has_outputs"]
        manifest, acquisition, annotations = case["manifest"], case["acquisition"], case["annotations"]
        processing = case["processing"].get("processing", {})
        voxelToWorld = case["voxel_to_world"]
        timesMs = case["time_ms"]
        frameLabels = ",".join(f"{float(t):g}" for t in timesMs)

        def createSequence(name, frames, attributes):
            # Index values are the frame times (trigger times), as for images imported from DICOM
            sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
            sequenceNode.SetIndexName("time")
            sequenceNode.SetIndexUnit("ms")
            sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.NumericIndex)
            for frameIndex, frame in enumerate(frames):
                sequenceNode.SetDataNodeAtValue(self._volumeNodeFromArray(frame, voxelToWorld), f"{float(timesMs[frameIndex]):g}")
            sequenceNode.SetAttribute("MultiVolume.FrameIdentifyingDICOMTagName", "TriggerTime")
            sequenceNode.SetAttribute("MultiVolume.FrameIdentifyingDICOMTagUnits", "ms")
            sequenceNode.SetAttribute("MultiVolume.FrameLabels", frameLabels)
            sequenceNode.SetAttribute("MultiVolume.NumberOfFrames", str(len(frames)))
            for key, value in attributes.items():
                sequenceNode.SetAttribute(key, value)
            browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", name + " browser")
            browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
            slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
            proxyNode = browserNode.GetProxyNode(sequenceNode)
            proxyNode.CreateDefaultDisplayNodes()
            return proxyNode

        magnitudeAttributes = {"SlicerHeart.directionCode": "magnitude"}
        if case["rr_ms"]:
            magnitudeAttributes["SlicerHeart.heartRateBpm"] = str(60000.0 / case["rr_ms"])
        magnitudeVolumeNode = createSequence(f"{caseId} magnitude", case["magnitude_t"], magnitudeAttributes)

        componentEncodings = acquisition.get("component_encoding", [])
        inputFlowFieldNode = self.createInputFlowFieldFromArrays(
            case["velocity_raw_t"], magnitudeVolumeNode, case["venc_encoded_mm_s"], case["encoding_to_world"],
            directionCodes=[encoding.get("direction_code", f"C{component + 1}") for component, encoding in enumerate(componentEncodings)] or None,
            componentMaxValues=[encoding["max_value"] for encoding in componentEncodings] if all("max_value" in encoding for encoding in componentEncodings) and componentEncodings else None,
            name=f"{caseId} input flow field")
        flowFieldNode = self.createOutputFlowField(inputFlowFieldNode)
        flowFieldNode.SetName(f"{caseId} flow field")

        wrapCountsEncoded = case["wrap_count_t"].astype(np.int8) if useOutputs else None  # per encoded component
        if wrapCountsEncoded is not None and np.any(wrapCountsEncoded != 0):
            self.setWrapCounts(flowFieldNode, wrapCountsEncoded)
            self._getSequenceFromProxyNode(flowFieldNode).SetAttribute("SlicerHeart.phaseUnwrapping", processing.get("phaseUnwrapping", "TemporalUnwrap"))

        annotationsDirectory = self.testCaseAnnotationsDirectory(datasetDirectory, caseId)
        lumenSegmentationNode = None
        lumenDescription = annotations.get("lumen", {})
        if lumenDescription.get("file") and os.path.isfile(os.path.join(annotationsDirectory, lumenDescription["file"])):
            lumenSegmentationNode = slicer.util.loadSegmentation(os.path.join(annotationsDirectory, lumenDescription["file"]))
        planeNodes = []
        for filename in annotations.get("planes", {}).get("files", []):
            planeNodes.append(slicer.util.loadMarkups(os.path.join(annotationsDirectory, filename)))

        if applyProcessing and not useOutputs:
            self.applyDefaultTestCaseProcessing(flowFieldNode, unwrapMode)
        elif applyProcessing:
            lumenMask = None
            if lumenSegmentationNode:
                lumenSegmentId = lumenSegmentationNode.GetSegmentation().GetSegmentIdBySegmentName(lumenDescription.get("segment", "lumen")) \
                    or lumenSegmentationNode.GetSegmentation().GetNthSegmentID(0)
                lumenMask = self.getLumenMask(flowFieldNode, lumenSegmentationNode, lumenSegmentId)
            divergenceFilterMethod = DivergenceFilterMethodEnum[processing.get("divergenceFilter", "NoFilter")]
            self.updateFlowFieldFromComponentVolumes(
                flowFieldNode,
                processing.get("noiseMagnitudeThresholdPercent", 5.0),
                BackgroundSubtractionMethodEnum[processing.get("backgroundSubtraction", "NoSubtraction")],
                processing.get("stationaryTissueSpeedThresholdVencPercent", 10.0),
                noiseMaskMethod=NoiseMaskMethodEnum[processing.get("noiseMask", "MagnitudeThreshold")],
                backgroundPolynomialOrder=processing.get("backgroundPolynomialOrder") or 2,
                backgroundPerFrame=bool(processing.get("backgroundPerFrame")),
                divergenceFilterMethod=divergenceFilterMethod,
                lumenMask=lumenMask if divergenceFilterMethod.libraryMethod() else None)
        return {"flowFieldNode": flowFieldNode, "inputFlowFieldNode": inputFlowFieldNode, "magnitudeVolumeNode": magnitudeVolumeNode,
                "lumenSegmentationNode": lumenSegmentationNode, "planeNodes": planeNodes, "manifest": manifest,
                "acquisition": acquisition, "processing": case["processing"], "annotations": annotations}


#
# Import4DFlowTest
#

class Import4DFlowTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        """ Do whatever is needed to reset the state - typically a scene clear will be enough.
        """
        slicer.mrmlScene.Clear()

    @staticmethod
    def _voxelValueUnitsKeptInSequence():
        """Voxel value units of volumes are kept when they are stored in a sequence and written to NRRD files (not in
        Slicer versions before 5.13): otherwise the units of flow fields stored in sequences cannot be checked."""
        volumeNode = slicer.vtkMRMLScalarVolumeNode()
        volumeNode.SetVoxelValueUnits(Import4DFlowLogic.createVelocityUnits("mm/s"))
        storedNode = slicer.vtkMRMLSequenceNode().SetDataNodeAtValue(volumeNode, "0")
        storedUnits = storedNode.GetVoxelValueUnits() if storedNode else None
        return bool(storedUnits and storedUnits.GetCodeValue() == "mm/s")

    def runTest(self):
        """Run as few or as many tests as needed here.
        """
        self.setUp()
        self.test_Import4DFlow1()
        self.setUp()
        self.test_FindVolumeNodeSetCandidatesInScene()
        self.setUp()
        self.test_CreateVectorVolumeFlowField()

    def test_Import4DFlow1(self):
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

        # # Get/create input data

        # import SampleData
        # registerSampleData()
        # inputVolume = SampleData.downloadSample('Import4DFlow1')
        # self.delayDisplay('Loaded test data set')

        # inputScalarRange = inputVolume.GetImageData().GetScalarRange()
        # self.assertEqual(inputScalarRange[0], 0)
        # self.assertEqual(inputScalarRange[1], 695)

        # outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        # threshold = 100

        # # Test the module logic

        # logic = Import4DFlowLogic()

        # # Test algorithm with non-inverted threshold
        # logic.process(inputVolume, outputVolume, threshold, True)
        # outputScalarRange = outputVolume.GetImageData().GetScalarRange()
        # self.assertEqual(outputScalarRange[0], inputScalarRange[0])
        # self.assertEqual(outputScalarRange[1], threshold)

        # # Test algorithm with inverted threshold
        # logic.process(inputVolume, outputVolume, threshold, False)
        # outputScalarRange = outputVolume.GetImageData().GetScalarRange()
        # self.assertEqual(outputScalarRange[0], inputScalarRange[0])
        # self.assertEqual(outputScalarRange[1], inputScalarRange[1])

        self.delayDisplay('Test passed')

    def test_FindVolumeNodeSetCandidatesInScene(self):
        """Volumes loaded from DICOM must be recognized as 4D flow candidates.

        Regression test for reading DICOM headers with pydicom: the candidate scan
        swallows per-volume errors, so a broken pydicom call (such as the
        pydicom.read_file function that was removed in pydicom 3) does not raise
        but silently returns no candidates.
        """
        import shutil
        import tempfile
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid
        from DICOMLib import DICOMUtils

        self.delayDisplay("Create a magnitude image of a Siemens 4D flow acquisition")
        sopInstanceUID = generate_uid()
        ds = Dataset()
        ds.PatientName = "Test^Patient"
        ds.PatientID = "Import4DFlowTest"
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.SOPInstanceUID = sopInstanceUID
        ds.SOPClassUID = MRImageStorage
        ds.Modality = "MR"
        ds.StudyDate = "20240102"
        ds.SeriesNumber = 1
        ds.InstanceNumber = 1
        ds.AcquisitionNumber = 1
        ds.SequenceName = "fl3d1r2"
        ds.NominalInterval = 1000  # msec, 60 bpm
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

        tempDir = tempfile.mkdtemp(prefix="Import4DFlowTest_", dir=slicer.app.temporaryPath)
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

                # The candidate scan only accepts proxy nodes of volume sequences
                volumeNode = slicer.vtkMRMLScalarVolumeNode()
                volumeNode.SetName("Magnitude")
                sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "MagnitudeSequence")
                sequenceNode.SetDataNodeAtValue(volumeNode, "0")
                browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "MagnitudeBrowser")
                browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
                slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
                proxyVolumeNode = browserNode.GetProxyNode(sequenceNode)
                self.assertIsNotNone(proxyVolumeNode)
                proxyVolumeNode.SetAttribute("DICOM.instanceUIDs", sopInstanceUID)

                self.delayDisplay("Find 4D flow candidate volumes")
                logic = Import4DFlowLogic()
                volumeNodesSets = logic._findVolumeNodeSetCandidatesInScene()
        finally:
            shutil.rmtree(tempDir, ignore_errors=True)

        self.assertEqual(len(volumeNodesSets), 1)
        volumeNodesSet = next(iter(volumeNodesSets.values()))
        self.assertEqual(volumeNodesSet["name"], "Test, Patient (20240102)")
        self.assertEqual(volumeNodesSet["candidateVolumeNodes"], [proxyVolumeNode])
        self.assertEqual(sequenceNode.GetAttribute("SlicerHeart.directionCode"), "magnitude")
        self.assertAlmostEqual(float(sequenceNode.GetAttribute("SlicerHeart.heartRateBpm")), 60.0)

        self.delayDisplay("Test passed")

    def _createSyntheticFlowImages(self, dims, numberOfFrames, vencsCmPerSec, directionCodes):
        """Create magnitude and component volume sequences, similar to what the DICOM importer produces for a
        Siemens 4D flow acquisition. All volumes are proxy nodes of the same sequence browser.
        Returns (magnitudeVolumeNode, componentVolumeNodes, componentArrays), where componentArrays[frame][component]
        holds the raw voxel values of a component image.
        """
        import numpy as np

        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "FlowBrowser")
        componentArrays = [[None] * 3 for frame in range(numberOfFrames)]

        def createSequence(name, component):
            sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
            sequenceNode.SetIndexName("frame")
            for frame in range(numberOfFrames):
                volumeNode = slicer.vtkMRMLScalarVolumeNode()
                volumeNode.SetName(name)
                image = vtk.vtkImageData()
                image.SetDimensions(dims)
                image.AllocateScalars(vtk.VTK_SHORT, 1)
                volumeNode.SetAndObserveImageData(image)
                volumeNode.SetSpacing(1.5, 2.0, 2.5)
                volumeNode.SetOrigin(-10.0, 20.0, 30.0)
                voxels = slicer.util.arrayFromVolume(volumeNode)
                if component is None:
                    voxels[:] = 200  # magnitude well above the noise threshold everywhere
                else:
                    # Phase values that vary by voxel, frame and component (well below the wraparound limit)
                    k, j, i = np.indices(voxels.shape)
                    voxels[:] = (component + 1) * 300 + frame * 100 + 10 * i - 20 * j + 30 * k
                    componentArrays[frame][component] = voxels.copy()
                slicer.util.arrayFromVolumeModified(volumeNode)
                sequenceNode.SetDataNodeAtValue(volumeNode, str(frame))
            return sequenceNode

        magnitudeSequenceNode = createSequence("Magnitude", None)
        browserNode.SetAndObserveMasterSequenceNodeID(magnitudeSequenceNode.GetID())
        componentSequenceNodes = []
        for component in range(3):
            componentSequenceNode = createSequence(f"Component {component + 1}", component)
            componentSequenceNode.SetAttribute("SlicerHeart.directionCode", directionCodes[component])
            componentSequenceNode.SetAttribute("SlicerHeart.vencCmPerSec", str(vencsCmPerSec[component]))
            componentSequenceNode.SetAttribute("SlicerHeart.maxValue", str(Import4DFlowLogic().componentVolumeMaxValueSiemensCS4DFlow))
            browserNode.AddSynchronizedSequenceNodeID(componentSequenceNode.GetID())
            componentSequenceNodes.append(componentSequenceNode)
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)

        magnitudeVolumeNode = browserNode.GetProxyNode(magnitudeSequenceNode)
        componentVolumeNodes = [browserNode.GetProxyNode(sequenceNode) for sequenceNode in componentSequenceNodes]
        for volumeNode in [magnitudeVolumeNode] + componentVolumeNodes:
            self.assertIsNotNone(volumeNode)
            volumeNode.CreateDefaultDisplayNodes()
        return magnitudeVolumeNode, componentVolumeNodes, componentArrays

    def test_CreateVectorVolumeFlowField(self):
        """The flow field is stored in a sequence of vector volumes (mm/s, declared in the voxel value units), which must
        contain the expected velocity vectors, be displayable, and be exportable to a 5D NRRD file.
        """
        import numpy as np
        import shutil
        import tempfile

        dims = (4, 3, 2)
        numberOfFrames = 2
        vencsCmPerSec = [150.0, 150.0, 200.0]
        directionCodes = ["through", "inplane_ap", "inplane_fh"]
        invertToRasDirection = [True, True, False]

        self.delayDisplay("Create synthetic 4D flow component images")
        magnitudeVolumeNode, componentVolumeNodes, componentArrays = self._createSyntheticFlowImages(
            dims, numberOfFrames, vencsCmPerSec, directionCodes)

        logic = Import4DFlowLogic()

        # Expected velocity (mm/s, RAS) from the raw component values, with no background subtraction
        expectedVelocity = []
        for frame in range(numberOfFrames):
            velocity = np.zeros(tuple(reversed(dims)) + (3,), dtype=np.float32)
            for component in range(3):
                scaleToMmPerSec = vencsCmPerSec[component] * 10.0 / logic.componentVolumeMaxValueSiemensCS4DFlow
                if invertToRasDirection[component]:
                    scaleToMmPerSec = -scaleToMmPerSec
                velocity[..., component] = componentArrays[frame][component] * scaleToMmPerSec
            expectedVelocity.append(velocity)

        tempDir = tempfile.mkdtemp(prefix="Import4DFlowTest_", dir=slicer.app.temporaryPath)
        try:
            self.delayDisplay("Create flow field")
            flowFieldNode = logic.createFlowFieldFromComponentVolumes(componentVolumeNodes, invertToRasDirection, magnitudeVolumeNode)
            self.assertTrue(flowFieldNode.IsA("vtkMRMLVectorVolumeNode"))
            self.assertFalse(logic.isFlowFieldStoredInTransform(flowFieldNode))
            self.assertEqual(flowFieldNode.GetAttribute("SlicerHeart.Type"), "FlowField")
            self.assertEqual(flowFieldNode.GetNodeReference("magnitudeVolume"), magnitudeVolumeNode)
            flowFieldSequenceNode = logic._getSequenceFromProxyNode(flowFieldNode)
            self.assertIsNotNone(flowFieldSequenceNode)

            logic.updateFlowFieldFromComponentVolumes(
                flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
            self.assertEqual(flowFieldSequenceNode.GetNumberOfDataNodes(), numberOfFrames)
            self.assertEqual(flowFieldSequenceNode.GetAttribute("SlicerHeart.velocityUnit"), "mm/s")
            for frame in range(numberOfFrames):
                frameNode = flowFieldSequenceNode.GetNthDataNode(frame)
                self.assertTrue(frameNode.IsA("vtkMRMLVectorVolumeNode"))
                np.testing.assert_allclose(slicer.util.arrayFromVolume(frameNode), expectedVelocity[frame], rtol=1e-5)
                np.testing.assert_allclose(frameNode.GetSpacing(), magnitudeVolumeNode.GetSpacing())
                np.testing.assert_allclose(frameNode.GetOrigin(), magnitudeVolumeNode.GetOrigin())
                if self._voxelValueUnitsKeptInSequence():
                    self.assertEqual(frameNode.GetVoxelValueUnits().GetCodeValue(), "mm/s")

            self.delayDisplay("Show flow field")
            logic.setFlowFieldVisualizationToDefault(flowFieldNode)
            displayNode = logic.getFlowFieldDisplayNode(flowFieldNode)
            if hasattr(slicer, "vtkMRMLVectorFieldDisplayNode"):
                self.assertIsNotNone(displayNode)
                self.assertTrue(displayNode.IsA("vtkMRMLVectorFieldDisplayNode"))
                self.assertTrue(displayNode.GetVisibility())
                self.assertEqual(displayNode.GetColorNode().GetAttribute("Category"), "Flow")

            self.delayDisplay("Export flow field to 5D NRRD")
            exportDirectory = os.path.join(tempDir, "vector_volume")
            os.makedirs(exportDirectory)
            exportedFile = logic.exportFlowFieldToNrrd5D(flowFieldNode, exportDirectory)
            self.assertTrue(os.path.exists(exportedFile))
            with open(exportedFile, "rb") as exportedFileHandle:
                header = exportedFileHandle.read(1000).decode("ascii", "replace")
            self.assertIn("dimension: 5", header)
            self.assertIn("kinds: vector domain domain domain list", header)
            if self._voxelValueUnitsKeptInSequence():
                self.assertIn('units: "mm/s"', header)  # unit of the velocity values, in the standard NRRD field of the component axis
            loadedSequenceNode = slicer.util.loadNodeFromFile(exportedFile, "SequenceFile")
            self.assertEqual(loadedSequenceNode.GetNumberOfDataNodes(), numberOfFrames)
            for frame in range(numberOfFrames):
                loadedFrameNode = loadedSequenceNode.GetNthDataNode(frame)
                self.assertTrue(loadedFrameNode.IsA("vtkMRMLVectorVolumeNode"))
                if self._voxelValueUnitsKeptInSequence():
                    self.assertEqual(loadedFrameNode.GetVoxelValueUnits().GetCodeValue(), "mm/s")
                np.testing.assert_allclose(slicer.util.arrayFromVolume(loadedFrameNode), expectedVelocity[frame], rtol=1e-5)
                np.testing.assert_allclose(loadedFrameNode.GetSpacing(), magnitudeVolumeNode.GetSpacing())
                np.testing.assert_allclose(loadedFrameNode.GetOrigin(), magnitudeVolumeNode.GetOrigin(), atol=1e-6)
        finally:
            shutil.rmtree(tempDir, ignore_errors=True)

        self.delayDisplay("Test passed")
