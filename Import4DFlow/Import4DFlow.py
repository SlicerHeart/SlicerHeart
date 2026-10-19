import enum
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
Import Siemens CS 4D flow images from DICOM.

See more information in <a href="https://github.com/JolleyLab/SlicerHeartPrivate#import-4d-flow">module documentation</a>.
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

class UnwrapModeEnum(enum.Enum):
    TemporalUnwrap = 1
    LaplacianUnwrap = 2
    NoUnwrap = 3

    def label(self):
        if self is UnwrapModeEnum.TemporalUnwrap:
            return "temporal"
        elif self is UnwrapModeEnum.LaplacianUnwrap:
            return "laplacian"
        elif self is UnwrapModeEnum.NoUnwrap:
            return "none"
        raise ValueError("Unknown enum value")

class BackgroundSubtractionMethodEnum(enum.Enum):
    NoSubtraction = 1
    LinearFit = 2
    QuadraticFit = 3

    def label(self):
        if self is BackgroundSubtractionMethodEnum.NoSubtraction:
            return "no subtraction"
        elif self is BackgroundSubtractionMethodEnum.LinearFit:
            return "linear fit"
        elif self is BackgroundSubtractionMethodEnum.QuadraticFit:
            return "quadratic fit"
        raise ValueError("Unknown enum value")

@parameterNodeWrapper
class Import4DFlowParameterNode:
    """
    The parameters needed by module.
    """
    # Flow field is stored either in a sequence of grid transform nodes (legacy format)
    # or in a sequence of vector volume nodes (3-component image, velocity vector in each voxel)
    outputFlowField: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode, None]
    inputVolumeNodeSet: str
    exportDirectory: str
    exportFormat: str
    unwrapMode: UnwrapModeEnum
    backgroundSubtractionMethod: BackgroundSubtractionMethodEnum
    noiseMagnitudeThresholdPercent: Annotated[float, WithinRange(0.0, 50.0)] = 5.0  # magnitude image threshold to filter out background noise (speed values below this threshold are set to zero in the flow field)
    stationaryTissueSpeedThresholdVencPercent: Annotated[float, WithinRange(0.0, 50.0)] = 10.0  # speed threshold to filter out stationary tissue as percentage of venc (speed values below this threshold are set to zero in the flow field)
    temporalUnwrapReferenceFrame: int = 0  # frame number to use as reference for temporal unwrapping

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
        # Application setting (not saved in the scene) that selects the flow field storage format
        self.storeInTransformSettingsKey = "Import4DFlow/StoreFlowFieldInTransform"

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

        self.ui.outputTransformSelector.setNodeTypeLabel("Flow Field", "vtkMRMLTransformNode")
        self.ui.outputTransformSelector.setNodeTypeLabel("Flow Field", "vtkMRMLVectorVolumeNode")
        self.ui.outputTransformSelector.addAttribute("vtkMRMLTransformNode", "SlicerHeart.Type", "FlowField")
        self.ui.outputTransformSelector.addAttribute("vtkMRMLVectorVolumeNode", "SlicerHeart.Type", "FlowField")

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

        # Restore flow field storage format from application settings (store in transform by default)
        self.ui.storeInTransformCheckBox.checked = slicer.util.settingsValue(
            self.storeInTransformSettingsKey, True, converter=slicer.util.toBool)

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
        self.ui.storeInTransformCheckBox.connect('toggled(bool)', self.onStoreInTransformToggled)
        self.ui.computePhaseUnwrappingButton.connect('clicked(bool)', self.onComputePhaseUnwrappingButton)
        self.ui.exportButton.connect('clicked(bool)', self.onExportButton)

        self.ui.showFlowFieldButton.connect('clicked(bool)', self.onShowFlowFieldButton)
        self.ui.showMagnitudeVolumeButton.connect('clicked(bool)', self.onShowMagnitudeVolumeButton)
        self.ui.showComponentVolume1Button.connect('clicked(bool)', lambda: self.onShowComponentVolumeButton(0))
        self.ui.showComponentVolume2Button.connect('clicked(bool)', lambda: self.onShowComponentVolumeButton(1))
        self.ui.showComponentVolume3Button.connect('clicked(bool)', lambda: self.onShowComponentVolumeButton(2))
        self.ui.recomputeFlowFieldButton.connect('clicked(bool)', self.onRecomputeFlowFieldButton)

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

        self.ui.exportPathLineEdit.setCurrentPath(self._parameterNode.exportDirectory)
        exportFormatIndex = self.ui.exportFormatComboBox.findData(self._parameterNode.exportFormat)
        self.ui.exportFormatComboBox.setCurrentIndex(exportFormatIndex if exportFormatIndex >= 0 else 0)

        for component in range(3):
            directionCode = None
            if self._parameterNode.outputFlowField:
                componentVolume = self._parameterNode.outputFlowField.GetNthNodeReference("componentVolume", component)
                if componentVolume:
                    directionCode = self.logic._getSequenceAttribute(componentVolume, "SlicerHeart.directionCode")
            showVolumeButton = getattr(self.ui, f"showComponentVolume{component+1}Button")
            if directionCode:
                showVolumeButton.text = directionCode
            else:
                showVolumeButton.text = f"C{component+1}"

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


    def onStoreInTransformToggled(self, checked: bool) -> None:
        slicer.app.settings().setValue(self.storeInTransformSettingsKey, bool(checked))

    def onConvertButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to convert image to flow field.", waitCursor=True):

            outputFlowField = self.logic.createFlowFieldFromComponentVolumes(
                self._volumeNodesSets[self._parameterNode.inputVolumeNodeSet]["componentVolumeNodes"],
                self._volumeNodesSets[self._parameterNode.inputVolumeNodeSet]["componentVolumeNodesInvertToRasDirection"],
                self._volumeNodesSets[self._parameterNode.inputVolumeNodeSet]['magnitudeVolumeNode'],
                storeInTransform=self.ui.storeInTransformCheckBox.checked)

            if not outputFlowField:
                slicer.util.errorDisplay("Failed to create flow field")
                return
            if not self.logic._getSequenceFromProxyNode(outputFlowField):
                raise RuntimeError("Flow field is not in a sequence")

            # Compute default result using temporal unwrapping
            self.logic.temporalUnwrap(outputFlowField, self._parameterNode.temporalUnwrapReferenceFrame, self._parameterNode.noiseMagnitudeThresholdPercent)

            # Compute flow from input component volumes and phase unwrapping map
            self.logic.updateFlowFieldFromComponentVolumes(outputFlowField, self._parameterNode.noiseMagnitudeThresholdPercent, self._parameterNode.backgroundSubtractionMethod, self._parameterNode.stationaryTissueSpeedThresholdVencPercent)
            self.logic.setFlowFieldVisualizationToDefault(outputFlowField)

            # Set active browser node to the transform sequence
            transformSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(outputFlowField)
            slicer.modules.sequences.toolBar().setActiveBrowserNode(transformSequenceBrowserNode)

            self._parameterNode.outputFlowField = outputFlowField

            self.onInspectButton()
            self.updateGUIFromParameterNode()

    def onComputePhaseUnwrappingButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to convert image to flow field.", waitCursor=True):
            # Compute phase unwrapping map
            if self._parameterNode.unwrapMode == UnwrapModeEnum.TemporalUnwrap:
                self.logic.temporalUnwrap(self._parameterNode.outputFlowField, self._parameterNode.temporalUnwrapReferenceFrame, self._parameterNode.noiseMagnitudeThresholdPercent)
            elif self._parameterNode.unwrapMode == UnwrapModeEnum.LaplacianUnwrap:
                self.logic.laplacianUnwrap(self._parameterNode.outputFlowField)
            else:
                self.logic.resetUnwrap(self._parameterNode.outputFlowField)


    def onShowFlowFieldButton(self) -> None:
        displayNode = self.logic.getFlowFieldDisplayNode(self._parameterNode.outputFlowField)
        if not displayNode:
            # Flow vectors have never been shown for this flow field
            self.logic.setFlowFieldVisualizationToDefault(self._parameterNode.outputFlowField)
            return
        displayNode.SetVisibility(not displayNode.GetVisibility())

    def onShowMagnitudeVolumeButton(self) -> None:
        slicer.util.setSliceViewerLayers(background=self._parameterNode.outputFlowField.GetNodeReference("magnitudeVolume"))
        self.setSegmentationVisibility(True)

    def onShowComponentVolumeButton(self, component) -> None:
        componentVolume = self._parameterNode.outputFlowField.GetNthNodeReference("componentVolume", component)
        slicer.util.setSliceViewerLayers(background=componentVolume)
        self.setSegmentationVisibility(False)
        self.setSegmentationVisibility(True, component)
        segmentation = self._parameterNode.outputFlowField.GetNthNodeReference("phaseWrapSegmentation", component)
        if segmentation:
            self.ui.segmentEditorWidget.setSegmentationNode(segmentation)
            if componentVolume:
                self.ui.segmentEditorWidget.setSourceVolumeNode(componentVolume)

    def setSegmentationVisibility(self, visibility, component=-1):
        for currentComponent in range(3):
            if (component >= 0 and currentComponent != component):
                continue
            segmentation = self._parameterNode.outputFlowField.GetNthNodeReference("phaseWrapSegmentation", currentComponent)
            if not segmentation:
                continue
            segmentation.GetDisplayNode().SetVisibility(visibility)

    def onRecomputeFlowFieldButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to recompute flow field.", waitCursor=True):
            if not self._parameterNode.outputFlowField:
                raise RuntimeError("Flow field is not created yet")

            self.logic.updateFlowFieldFromComponentVolumes(self._parameterNode.outputFlowField, self._parameterNode.noiseMagnitudeThresholdPercent, self._parameterNode.backgroundSubtractionMethod, self._parameterNode.stationaryTissueSpeedThresholdVencPercent)

    def onExportButton(self) -> None:
        if not self._parameterNode.exportDirectory:
            self.ui.exportPathLineEdit.setCurrentPath(slicer.mrmlScene.GetRootDirectory())
            slicer.app.processEvents()

        success = False
        with slicer.util.tryWithErrorDisplay("Failed to export the flow field to files.", waitCursor=True):
            self.logic.exportDisplacementFieldToFiles(self._parameterNode.outputFlowField, self._parameterNode.exportDirectory, self._parameterNode.exportFormat)
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
    # All export formats, in the order they are listed in the module GUI
    EXPORT_FORMATS = [EXPORT_FORMAT_ANONYMIZED_SCENE, EXPORT_FORMAT_NRRD_STACK, EXPORT_FORMAT_NRRD_5D]
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

        # for current Siemens CS4D flow images this can be hardcoded
        self.magnitudeVolumeRange = 255
        self.componentVolumeMaxValueSiemensCS4DFlow = 4096

        self.maxWraps = 3

        self.dopplerLutRange = [-2, 2]
        self.dopplerLutThreshold = [-0.25, 0.25]

        # Use positive side of the Doppler color table for absolute speed
        # Set to false, because the multicolor colormap can better distinguish speed differences.
        self.useDopplerColorTableForAbsoluteSpeed = False

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
        import traceback

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
                elif ("SequenceName" in ds) and (('fl3d1r2' in ds["SequenceName"].value) or ('fl3d1r3' in ds["SequenceName"].value)):
                    if '_v' in ds["SequenceName"].value:
                        # component image (contain speed specification)
                        # Examples: 'fl3d1_v150in', 'fl3d1_v150ap', 'fl3d1_v150fh'
                        # In freerunning flow sequence, all the directions may be under the same series
                        logging.debug(f"Found a flow vector component image candidate: {volumeNode.GetName()}")
                        speedAndDirectionCode = ds["SequenceName"].value.split('_v')[-1]  # 150in
                        # directionCodeInput: last two characters
                        # vencCmPerSecInput: all characters except the last two
                        vencCmPerSecInput = float(speedAndDirectionCode[:-2])
                        directionCodeInput = speedAndDirectionCode[-2:]
                    else:
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

    @staticmethod
    def isFlowFieldStoredInTransform(flowFieldNode) -> bool:
        """A flow field is stored either in a sequence of grid transform nodes (legacy format) or in a sequence
        of vector volume nodes (3-component image, with the velocity vector in each voxel).
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

    def createFlowFieldFromComponentVolumes(self, componentVolumeNodes, componentVolumeNodesInvertToRasDirection, magnitudeVolumeNode, storeInTransform=True):
        """Create the flow field node (and the sequence that will store its frames) from the component and magnitude volumes.
        If storeInTransform is True then the flow field is stored in a sequence of grid transform nodes (legacy format),
        otherwise in a sequence of vector volume nodes. The flow field frames are computed by updateFlowFieldFromComponentVolumes.
        """

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

        flowFieldNodeClassName = "vtkMRMLTransformNode" if storeInTransform else "vtkMRMLVectorVolumeNode"
        flowFieldNode = slicer.mrmlScene.AddNewNodeByClass(flowFieldNodeClassName, "FlowField")
        flowFieldNode.SetAttribute("SlicerHeart.Type", "FlowField")
        flowFieldNode.SetNodeReferenceID("magnitudeVolume", magnitudeVolumeNode.GetID())
        for component in range(3):
            componentVolumeNode = componentVolumeNodes[component]
            flowFieldNode.SetNthNodeReferenceID("componentVolume", component, componentVolumeNode.GetID())

        # Create sequence node to store the time-varying flow field
        flowFieldSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "4D flow")
        flowFieldSequenceNode.SetIndexType(magnitudeVolumeSequenceNode.GetIndexType())
        flowFieldSequenceNode.SetIndexName(magnitudeVolumeSequenceNode.GetIndexName())
        flowFieldSequenceNode.SetIndexUnit(magnitudeVolumeSequenceNode.GetIndexUnit())

        # Create a sequence browser node for the new merged sequence
        magnitudeVolumeSequenceBrowserNode.AddProxyNode(flowFieldNode, flowFieldSequenceNode, False)
        magnitudeVolumeSequenceBrowserNode.SetSaveChanges(flowFieldSequenceNode, True)  # Allow updating the flow field
        magnitudeVolumeSequenceBrowserNode.SetOverwriteProxyName(flowFieldSequenceNode, True)  # show index in node name

        # Place flow field in the same subject hierarchy folder as the volume node
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        volumeParentItemId = shNode.GetItemParent(shNode.GetItemByDataNode(magnitudeVolumeNode))
        shNode.SetItemParent(shNode.GetItemByDataNode(flowFieldNode), volumeParentItemId)

        return flowFieldNode

    def _getComponentBackground(self, magnitudeVoxelArray, componentVoxelArray, noiseMagnitudeThreshold, backgroundSubtractionMethod, componentThreshold):
        import numpy as np

        background_3d = np.zeros_like(componentVoxelArray)
        if backgroundSubtractionMethod == BackgroundSubtractionMethodEnum.NoSubtraction:
            return background_3d

        from scipy.optimize import curve_fit

        data = componentVoxelArray

        # Mask array (True for values to be used in fitting)
        mask = np.logical_and(magnitudeVoxelArray > noiseMagnitudeThreshold, np.abs(componentVoxelArray) < componentThreshold)

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

    def updateFlowFieldFromComponentVolumes(self, flowFieldNode, noiseMagnitudeThresholdPercent, backgroundSubtractionMethod, stationaryTissueSpeedThresholdVencPercent):
        """Compute the velocity field of each frame from the component volumes and store them in the flow field sequence.
        The flow field node can be a transform or a vector volume (see createFlowFieldFromComponentVolumes).
        Velocity vectors are stored in m/s, in RAS coordinate system.
        """

        # Compute physical speed from encoding speed
        componentVolumeNodesScaleToCmPerSec = []
        componentVolumeMaxValues = []
        componentVolumeNodes = []
        componentVolumeSequenceNodes = []
        vencCmPerSecList = []
        for axis in range(3):
            componentVolumeNode = flowFieldNode.GetNthNodeReference("componentVolume", axis)
            componentVolumeSequenceNode = self._getSequenceFromProxyNode(componentVolumeNode)
            vencCmPerSec = float(componentVolumeSequenceNode.GetAttribute("SlicerHeart.vencCmPerSec"))
            componentVolumeMaxValue = float(componentVolumeSequenceNode.GetAttribute("SlicerHeart.maxValue"))
            invertToRasDirection = (componentVolumeSequenceNode.GetAttribute("SlicerHeart.invertToRasDirection") == "true")
            scaleToCmPerSec = 1 / componentVolumeMaxValue * vencCmPerSec
            if invertToRasDirection:
                scaleToCmPerSec = -scaleToCmPerSec
            componentVolumeMaxValues.append(componentVolumeMaxValue)
            componentVolumeNodesScaleToCmPerSec.append(scaleToCmPerSec)
            componentVolumeNodes.append(componentVolumeNode)
            componentVolumeSequenceNodes.append(componentVolumeSequenceNode)
            vencCmPerSecList.append(componentVolumeSequenceNode.GetAttribute("SlicerHeart.vencCmPerSec"))

        flowFieldSequenceNode = self._getSequenceFromProxyNode(flowFieldNode)
        storeInTransform = self.isFlowFieldStoredInTransform(flowFieldNode)

        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
        magnitudeVolumeSequenceNode = self._getSequenceFromProxyNode(magnitudeVolumeNode)
        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "___temp1___")

        colorTableNode = slicer.vtkMRMLColorTableNode()
        colorTableNode.SetTypeToUser()
        colorTableNode.SaveWithSceneOff()
        colorTableNode.SetAttribute("Category", "Flow")
        colorTableNode.SetAttribute("SlicerHeart.ColorMappingType", "SpeedComponent")
        colorTableNode.SetName("___temp1_color___")
        colorTableNode = slicer.mrmlScene.AddNode(colorTableNode)

        for volumeIndex in range(magnitudeVolumeSequenceNode.GetNumberOfDataNodes()):
            magnitudeVolumeNodeInSequence = magnitudeVolumeSequenceNode.GetNthDataNode(volumeIndex)
            magnitudeVoxelArray = slicer.util.arrayFromVolume(magnitudeVolumeNodeInSequence)

            # Node that stores the flow field of this frame, with the geometry of the magnitude volume
            flowFieldNodeInSequence, displacementArray = self._createFlowFieldFrameNode(storeInTransform, magnitudeVolumeNodeInSequence)
            for axis in range(3):
                volumeSequenceNode = componentVolumeSequenceNodes[axis]

                # Use m/sec as vector value in the transform (divide cm/sec by 100) because a typical 50 cm/sec speed
                # = 0.5 m/sec speed value can be visualized nicely as displacement field with typical image spacing
                scaleToMeterPerSec = componentVolumeNodesScaleToCmPerSec[axis] / 100
                componentVolumeNodeInSequence = volumeSequenceNode.GetNthDataNode(volumeIndex)

                componentVoxelArray = slicer.util.arrayFromVolume(componentVolumeNodeInSequence).copy()

                # Discard low values
                noiseMagnitudeThreshold = noiseMagnitudeThresholdPercent / 100 * self.magnitudeVolumeRange
                componentVoxelArray[magnitudeVoxelArray < noiseMagnitudeThreshold] = 0

                # Apply phase unwrapping
                segmentationNode = flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", axis)
                if segmentationNode:
                    segmentationSequenceNode = self._getSequenceFromProxyNode(segmentationNode)
                    segmentationNodeInSequence = segmentationSequenceNode.GetNthDataNode(volumeIndex)
                    segmentIds = self._getSegmentIds()
                    slicer.vtkSlicerSegmentationsModuleLogic.ExportSegmentsToLabelmapNode(segmentationNodeInSequence, segmentIds, labelmapNode, magnitudeVolumeNode, slicer.vtkSegmentation.EXTENT_UNION_OF_EFFECTIVE_SEGMENTS, colorTableNode)
                    segmentationArray = slicer.util.arrayFromVolume(labelmapNode)

                    for wrapIndex in range(1, self.maxWraps):
                        componentVolumeMaxValue = componentVoxelArray.dtype.type(componentVolumeMaxValues[axis])
                        # Find voxels with phase wraps
                        # Negative wrap (segment indices: 1, 3, 5)
                        componentVoxelArray[segmentationArray == wrapIndex * 2 - 1] -= wrapIndex * 2 * componentVolumeMaxValue
                        # Positive wrap (segment indices: 2, 4, 6)
                        componentVoxelArray[segmentationArray == wrapIndex * 2] += wrapIndex * 2 * componentVolumeMaxValue

                stationaryTissueSpeedThreshold = stationaryTissueSpeedThresholdVencPercent / 100 * self.componentVolumeMaxValueSiemensCS4DFlow
                componentVoxelBackgroundArray = self._getComponentBackground(magnitudeVoxelArray, slicer.util.arrayFromVolume(componentVolumeNodeInSequence), noiseMagnitudeThreshold, backgroundSubtractionMethod, stationaryTissueSpeedThreshold)

                displacementArray[:, :, :, axis] = (componentVoxelArray - componentVoxelBackgroundArray) * scaleToMeterPerSec

            indexValue = magnitudeVolumeSequenceNode.GetNthIndexValue(volumeIndex)
            self._addFlowFieldFrameToSequence(flowFieldSequenceNode, flowFieldNodeInSequence, indexValue)

        flowFieldSequenceNode.SetAttribute("SlicerHeart.vencCmPerSec", ','.join(vencCmPerSecList))  # velocity encoding, in cm/sec
        flowFieldSequenceNode.SetAttribute("SlicerHeart.velocityUnit", "m/s")

        if labelmapNode.GetDisplayNode():
            slicer.mrmlScene.RemoveNode(labelmapNode.GetDisplayNode().GetColorNode())
        slicer.mrmlScene.RemoveNode(labelmapNode)


    def _createFlowFieldFrameNode(self, storeInTransform, referenceVolumeNode):
        """Create a node that stores the velocity field of one frame, on the voxel grid of the reference volume.
        Returns the node (not added to the scene) and a numpy array view of its velocity vectors (shape: k, j, i, component).
        After the array is filled, call _addFlowFieldFrameToSequence.
        """
        dims = referenceVolumeNode.GetImageData().GetDimensions()
        velocityImage = vtk.vtkImageData()
        velocityImage.SetDimensions(dims[0], dims[1], dims[2])
        velocityImage.AllocateScalars(vtk.VTK_FLOAT, 3)
        if storeInTransform:
            frameNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLTransformNode")
            frameNode.UnRegister(None)  # Prevent memory leak
            gridTransform = slicer.vtkOrientedGridTransform()
            directionMatrix = vtk.vtkMatrix4x4()
            referenceVolumeNode.GetIJKToRASDirectionMatrix(directionMatrix)
            gridTransform.SetGridDirectionMatrix(directionMatrix)
            velocityImage.SetSpacing(referenceVolumeNode.GetSpacing())
            velocityImage.SetOrigin(referenceVolumeNode.GetOrigin())
            gridTransform.SetDisplacementGridData(velocityImage)
            frameNode.SetAndObserveTransformFromParent(gridTransform)
            velocityArray = slicer.util.arrayFromGridTransform(frameNode)
        else:
            frameNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLVectorVolumeNode")
            frameNode.UnRegister(None)  # Prevent memory leak
            frameNode.CopyOrientation(referenceVolumeNode)
            # Voxels store velocity vectors with RAS components. Marking them as spatial vectors makes
            # Slicer convert them to LPS when writing to file and back to RAS when reading.
            frameNode.SetVoxelVectorType(slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial)
            frameNode.SetAndObserveImageData(velocityImage)
            velocityArray = slicer.util.arrayFromVolume(frameNode)
        frameNode.SetAttribute("SlicerHeart.Type", "FlowField")
        return frameNode, velocityArray

    def _addFlowFieldFrameToSequence(self, flowFieldSequenceNode, frameNode, indexValue):
        """Store a frame created by _createFlowFieldFrameNode in the flow field sequence."""
        if frameNode.IsA("vtkMRMLTransformNode"):
            slicer.util.arrayFromGridTransformModified(frameNode)
            # The transform stores "transform from parent", but visualization displays "transform to parent".
            # (We could not set transform to parent directly because arrayFromGridTransformModified
            # only works with "transform from parent"). Invert the field now to display "transform to parent".
            # This also greatly speeds up the display.
            frameNode.Inverse()
            flowFieldSequenceNode.SetDataNodeAtValue(frameNode, indexValue)
            # Revert to "transform from parent"
            frameNode.Inverse()
        else:
            slicer.util.arrayFromVolumeModified(frameNode)
            flowFieldSequenceNode.SetDataNodeAtValue(frameNode, indexValue)

    def setFlowFieldVisualizationToDefault(self, flowFieldNode: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode]) -> None:
        """Show the flow field as glyphs in slice views, colored by speed."""
        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
        displayNode = self.getFlowFieldDisplayNode(flowFieldNode)
        if self.isFlowFieldStoredInTransform(flowFieldNode):
            if not displayNode:
                displayNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformDisplayNode")
                flowFieldNode.AddAndObserveDisplayNodeID(displayNode.GetID())
            displayNode.SetGlyphDisplayRangeMinMm(0.05) # meter/sec
            displayNode.SetGlyphSpacingMm(2.0)
            displayNode.SetGlyphDiameterMm(0.8)
            displayNode.SetGlyphScalePercent(500)
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
            displayNode.SetMaskingMode(slicer.vtkMRMLVectorFieldDisplayNode.MaskingModeFixedSpacing)
            displayNode.SetThresholdRange(0.05, 100.0)  # meter/sec, hide glyphs where there is no flow
            displayNode.SetThresholdEnabled(True)
            displayNode.SetEffectiveSamplingSpacingMm(2.0)
            displayNode.SetGlyphDiameterAbsolute(True)
            displayNode.SetGlyphDiameterMm(0.8)
            displayNode.SetScaleFactor(5.0)

        displayNode.SetVisibility(True)
        displayNode.SetVisibility2D(True)
        displayNode.SetVisibility3D(False)  # with small glyph spacing, updating of the glyphs in 3D can be slow
        displayNode.SetAndObserveRegionNode(magnitudeVolumeNode)

        colorNode = displayNode.GetColorNode()
        if not colorNode or colorNode.GetAttribute("Category") != "Flow":
            # Create color node
            colorNode = self._createSpeedColorNode()
            displayNode.SetAndObserveColorNodeID(colorNode.GetID())
            # Display color legend
            colorLegendDisplayNode = slicer.modules.colors.logic().AddDefaultColorLegendDisplayNode(displayNode)
            colorLegendDisplayNode.SetTitleText("Speed")
            colorLegendDisplayNode.SetLabelFormat("%4.1f m/s")
            #colorLegendDisplayNode.SetScalarRange(0, 1.5)
        if not self.isFlowFieldStoredInTransform(flowFieldNode):
            # Color the glyphs by the color map range (speed in m/s) and not by the data range, so that colors
            # are consistent across frames and acquisitions (transform display node always does this).
            # Set after the color node is assigned, as the scalar range is updated from the color node immediately.
            displayNode.SetScalarRangeFlag(slicer.vtkMRMLDisplayNode.UseColorNodeScalarRange)

        # Update colormap colors
        colorMap = colorNode.GetColorTransferFunction()
        wasModified = colorNode.StartModify()
        colorMap.RemoveAllPoints()
        # Determine color map range based on velocity encoding, so that the color map is consistent across different acquisitions
        # that use the same velocity encoding (venc) setting.
        maxVencCmPerSec = 0
        for component in range(3):
            vencCmPerSec = float(self._getSequenceAttribute(flowFieldNode.GetNthNodeReference("componentVolume", component), "SlicerHeart.vencCmPerSec"))
            maxVencCmPerSec = max(maxVencCmPerSec, vencCmPerSec)
        colorTableRangeMeterPerSec = maxVencCmPerSec / 100  # m/sec

        if self.useDopplerColorTableForAbsoluteSpeed:
            dopplerColorNode = Import4DFlowLogic.dopplerColdToHotColorTableNode()
            speed0Index = (dopplerColorNode.GetNumberOfColors() - 1) / 2
            speedMaxIndex = dopplerColorNode.GetNumberOfColors() - 1
            colorMapResolution = 25
            rgba = [0, 0, 0, 0]
            for i in range(colorMapResolution):
                colorIndex = int(speed0Index + i / (colorMapResolution - 1) * (speedMaxIndex - speed0Index))
                dopplerColorNode.GetColor(colorIndex, rgba)
                colorMap.AddRGBPoint(colorTableRangeMeterPerSec * i / colorMapResolution, rgba[0], rgba[1], rgba[2])
        else:
            # Use jet color (blue, green, red)
            colorMap.AddRGBPoint(colorTableRangeMeterPerSec * 0.0, 0.0, 0.0, 1.0)
            colorMap.AddRGBPoint(colorTableRangeMeterPerSec * 0.2, 0.0, 1.0, 1.0)
            colorMap.AddRGBPoint(colorTableRangeMeterPerSec * 0.5, 1.0, 1.0, 0.0)
            colorMap.AddRGBPoint(colorTableRangeMeterPerSec * 1.0, 1.0, 0.0, 0.0)

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
        else:
            raise ValueError(f"Unsupported export format: {exportFormat}")

    def createVectorVolumeSequenceFromFlowField(self, flowFieldNode: Union[vtkMRMLTransformNode, vtkMRMLVectorVolumeNode], name: str = "4D flow velocity"):
        """Create a vector volume sequence (added to the scene) from a flow field: each frame is a 3-component image
        with the velocity vector (m/s, RAS) in each voxel, on the voxel grid of the magnitude volume.
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
        Velocity vectors are in m/s, in RAS coordinate system (stored as LPS in the file, as any other NRRD volume).
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
            header['sample units'] = 'm/s'
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

    def _getComponentSegmentationNode(self, outputFlowField, component):
        segmentationNode = outputFlowField.GetNthNodeReference("phaseWrapSegmentation", component)
        if segmentationNode:
            return segmentationNode

        componentVolumeNode = outputFlowField.GetNthNodeReference("componentVolume", component)

        sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(outputFlowField)
        # Create new segmentation node and add it to the sequence
        directionCode = self._getSequenceAttribute(componentVolumeNode, "SlicerHeart.directionCode")
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", f"Phase wrap C{component+1} {directionCode}")
        outputFlowField.SetNthNodeReferenceID("phaseWrapSegmentation", component, segmentationNode.GetID())
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(componentVolumeNode)
        segmentationNode.CreateDefaultDisplayNodes()
        segmentationNode.GetDisplayNode().SetOpacity2DFill(0.2)
        segmentationNode.GetDisplayNode().SetSliceIntersectionThickness(5)
        segmentationSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", segmentationNode.GetName())
        componentVolumeSequenceNode = self._getSequenceFromProxyNode(componentVolumeNode)
        segmentationSequenceNode.SetIndexType(componentVolumeSequenceNode.GetIndexType())
        segmentationSequenceNode.SetIndexName(componentVolumeSequenceNode.GetIndexName())
        segmentationSequenceNode.SetIndexUnit(componentVolumeSequenceNode.GetIndexUnit())
        sequenceBrowserNode.AddProxyNode(segmentationNode, segmentationSequenceNode, False)
        sequenceBrowserNode.PlaybackActiveOff()
        sequenceBrowserNode.SetRecording(segmentationSequenceNode, False)
        sequenceBrowserNode.SetSaveChanges(segmentationSequenceNode, True)
        sequenceBrowserNode.SetOverwriteProxyName(segmentationSequenceNode, True)  # show index in node name

        # Place segmentation in the same subject hierarchy folder as the flow field node
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        parentItemId = shNode.GetItemParent(shNode.GetItemByDataNode(outputFlowField))
        shNode.SetItemParent(shNode.GetItemByDataNode(segmentationNode), parentItemId)

        return segmentationNode

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

    def backgroundCorrection(self, outputFlowField):
        """Remove background phase offset from the flow field."""
        for component in range(3):
            componentVolumeNode = outputFlowField.GetNthNodeReference("componentVolume", component)
            componentVolumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(componentVolumeNode)
            componentVolumeSequenceNode = componentVolumeSequenceBrowserNode.GetSequenceNode(componentVolumeNode)
            componentVolumeArray = slicer.util.arrayFromVolume(componentVolumeSequenceNode.GetNthDataNode(0))
            backgroundPhase = np.median(componentVolumeArray[componentVolumeArray > 0])
            componentVolumeArray -= backgroundPhase
            slicer.util.updateVolumeFromArray(componentVolumeSequenceNode.GetNthDataNode(0), componentVolumeArray)

    def laplacianUnwrap(self, outputFlowField):
        raise NotImplementedError("Laplacian unwrapping is not implemented yet")

    def resetUnwrap(self, outputFlowField):
        """Remove phase wrap segmentation nodes and sequences."""
        for component in [2, 1, 0]:  # delete the last component first to avoid index shift
            segmentationNode = self._getComponentSegmentationNode(outputFlowField, component)
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
        """
        if indexWithoutWrapping != 0:
            raise RuntimeError("Temporal unwrapping is only implemented for the first frame")

        import numpy as np
        # Get magnitude volume sequence node
        magnitudeVolumeNode = outputFlowField.GetNodeReference("magnitudeVolume")
        magnitudeVolumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(magnitudeVolumeNode)
        magnitudeVolumeSequenceNode = magnitudeVolumeSequenceBrowserNode.GetSequenceNode(magnitudeVolumeNode)
        # Temporary labelmap node for storing the phase wrap map
        labelmapNode = None
        segmentIds = self._getSegmentIds()
        originalItemNumber = magnitudeVolumeSequenceBrowserNode.GetSelectedItemNumber()
        # Compute phase wrap map
        for component in range(3):
            componentVolume = outputFlowField.GetNthNodeReference("componentVolume", component)
            componentVolumeMaxValue = float(self._getSequenceAttribute(componentVolume, "SlicerHeart.maxValue"))
            componentVolumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(componentVolume)
            componentVolumeSequenceNode = componentVolumeSequenceBrowserNode.GetSequenceNode(componentVolume)
            if labelmapNode is None:
                labelmapNode = slicer.modules.volumes.logic().CreateAndAddLabelVolume(slicer.mrmlScene, componentVolume, "___temp2___")
            voxelArray = None
            phaseWrapMap = None
            segmentationNode = self._getComponentSegmentationNode(outputFlowField, component)
            for index in range(indexWithoutWrapping, componentVolumeSequenceNode.GetNumberOfDataNodes()):
                # TODO: probably we could do it without browsing. ImportLabelmapToSegmentationNode would not be able to handle different
                # parent transforms, but we are not supposed to have parent transforms
                componentVolumeSequenceBrowserNode.SetSelectedItemNumber(index)
                segmentationNode.GetSegmentation().RemoveAllSegments()
                previousVoxelArray = voxelArray
                previousPhaseWrapMap = phaseWrapMap
                voxelArray = slicer.util.arrayFromVolume(componentVolumeSequenceNode.GetNthDataNode(index)).copy()

                magnitudeVolumeArray = slicer.util.arrayFromVolume(magnitudeVolumeSequenceNode.GetNthDataNode(index))
                voxelArray[magnitudeVolumeArray < noiseMagnitudeThresholdPercent / 100 * self.magnitudeVolumeRange] = 0

                if previousVoxelArray is None:
                    # First frame is never wrapped around
                    phaseWrapMap = np.zeros(voxelArray.shape, dtype=np.int8)
                    slicer.util.updateVolumeFromArray(labelmapNode, phaseWrapMap)
                    slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode, segmentIds)
                    continue
                phaseWrapMap = np.copy(previousPhaseWrapMap)
                # Unwrap by comparing with the previous frame
                diff = voxelArray - previousVoxelArray

                # Wrap negative (step down)
                # For example, sequence of values (for max value of 1000): -880 -960 [980]
                phaseWrapMap[diff > componentVolumeMaxValue] -= 1
                # Wrap positive (step up)
                # For example, sequence of values (for max value of 1000): 900 980 [-960]
                phaseWrapMap[diff < -componentVolumeMaxValue] += 1

                # Phase wrap map has no wrap 0, ngeative wraps -1, -2, ..., positive wraps 1, 2, ...
                # Segment indices are all positive: 1x negative wrap, 1x positive wrap, 2x negative wrap, 2x positive wrap, etc. (see self._getSegmentIds)
                phaseWrapSegmentation = phaseWrapMap.copy()

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
                slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode, segmentIds)
                slicer.app.processEvents()
        if labelmapNode:
            slicer.mrmlScene.RemoveNode(labelmapNode)

        magnitudeVolumeSequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)


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

    def runTest(self):
        """Run as few or as many tests as needed here.
        """
        self.setUp()
        self.test_Import4DFlow1()
        self.setUp()
        self.test_FindVolumeNodeSetCandidatesInScene()
        self.setUp()
        self.test_CreateFlowFieldInTransformAndVectorVolume()

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

    def _velocityArrayFromFlowFieldFrame(self, frameNode):
        """Get the velocity vectors stored in a flow field frame (transform or vector volume) as a numpy array."""
        if frameNode.IsA("vtkMRMLTransformNode"):
            # The same coefficients are returned regardless of the transform direction
            return slicer.util.arrayFromGridTransform(frameNode)
        return slicer.util.arrayFromVolume(frameNode)

    def test_CreateFlowFieldInTransformAndVectorVolume(self):
        """The flow field can be stored in a sequence of grid transforms (legacy) or vector volumes,
        both must contain the same velocity vectors, be displayable, and be exportable to a 5D NRRD file.
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

        # Expected velocity (m/s, RAS) from the raw component values, with no background subtraction
        expectedVelocity = []
        for frame in range(numberOfFrames):
            velocity = np.zeros(tuple(reversed(dims)) + (3,), dtype=np.float32)
            for component in range(3):
                scaleToMeterPerSec = vencsCmPerSec[component] / logic.componentVolumeMaxValueSiemensCS4DFlow / 100.0
                if invertToRasDirection[component]:
                    scaleToMeterPerSec = -scaleToMeterPerSec
                velocity[..., component] = componentArrays[frame][component] * scaleToMeterPerSec
            expectedVelocity.append(velocity)

        tempDir = tempfile.mkdtemp(prefix="Import4DFlowTest_", dir=slicer.app.temporaryPath)
        try:
            for storeInTransform in [True, False]:
                storageName = "transform" if storeInTransform else "vector volume"
                self.delayDisplay(f"Create flow field stored in {storageName}")
                flowFieldNode = logic.createFlowFieldFromComponentVolumes(
                    componentVolumeNodes, invertToRasDirection, magnitudeVolumeNode, storeInTransform=storeInTransform)
                self.assertEqual(flowFieldNode.IsA("vtkMRMLTransformNode"), storeInTransform)
                self.assertEqual(flowFieldNode.IsA("vtkMRMLVectorVolumeNode"), not storeInTransform)
                self.assertEqual(logic.isFlowFieldStoredInTransform(flowFieldNode), storeInTransform)
                self.assertEqual(flowFieldNode.GetAttribute("SlicerHeart.Type"), "FlowField")
                self.assertEqual(flowFieldNode.GetNodeReference("magnitudeVolume"), magnitudeVolumeNode)
                flowFieldSequenceNode = logic._getSequenceFromProxyNode(flowFieldNode)
                self.assertIsNotNone(flowFieldSequenceNode)

                logic.updateFlowFieldFromComponentVolumes(
                    flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
                self.assertEqual(flowFieldSequenceNode.GetNumberOfDataNodes(), numberOfFrames)
                self.assertEqual(flowFieldSequenceNode.GetAttribute("SlicerHeart.velocityUnit"), "m/s")
                for frame in range(numberOfFrames):
                    frameNode = flowFieldSequenceNode.GetNthDataNode(frame)
                    self.assertEqual(frameNode.IsA("vtkMRMLTransformNode"), storeInTransform)
                    np.testing.assert_allclose(self._velocityArrayFromFlowFieldFrame(frameNode), expectedVelocity[frame], rtol=1e-5)
                    if not storeInTransform:
                        np.testing.assert_allclose(frameNode.GetSpacing(), magnitudeVolumeNode.GetSpacing())
                        np.testing.assert_allclose(frameNode.GetOrigin(), magnitudeVolumeNode.GetOrigin())

                self.delayDisplay(f"Show flow field stored in {storageName}")
                logic.setFlowFieldVisualizationToDefault(flowFieldNode)
                displayNode = logic.getFlowFieldDisplayNode(flowFieldNode)
                self.assertIsNotNone(displayNode)
                self.assertTrue(displayNode.IsA("vtkMRMLTransformDisplayNode") or displayNode.IsA("vtkMRMLVectorFieldDisplayNode"))
                self.assertTrue(displayNode.GetVisibility())
                self.assertEqual(displayNode.GetColorNode().GetAttribute("Category"), "Flow")

                self.delayDisplay(f"Export flow field stored in {storageName} to 5D NRRD")
                exportDirectory = os.path.join(tempDir, storageName.replace(" ", "_"))
                os.makedirs(exportDirectory)
                exportedFile = logic.exportFlowFieldToNrrd5D(flowFieldNode, exportDirectory)
                self.assertTrue(os.path.exists(exportedFile))
                with open(exportedFile, "rb") as exportedFileHandle:
                    header = exportedFileHandle.read(1000).decode("ascii", "replace")
                self.assertIn("dimension: 5", header)
                self.assertIn("kinds: vector domain domain domain list", header)
                loadedSequenceNode = slicer.util.loadNodeFromFile(exportedFile, "SequenceFile")
                self.assertEqual(loadedSequenceNode.GetNumberOfDataNodes(), numberOfFrames)
                for frame in range(numberOfFrames):
                    loadedFrameNode = loadedSequenceNode.GetNthDataNode(frame)
                    self.assertTrue(loadedFrameNode.IsA("vtkMRMLVectorVolumeNode"))
                    np.testing.assert_allclose(slicer.util.arrayFromVolume(loadedFrameNode), expectedVelocity[frame], rtol=1e-5)
                    np.testing.assert_allclose(loadedFrameNode.GetSpacing(), magnitudeVolumeNode.GetSpacing())
                    np.testing.assert_allclose(loadedFrameNode.GetOrigin(), magnitudeVolumeNode.GetOrigin(), atol=1e-6)
        finally:
            shutil.rmtree(tempDir, ignore_errors=True)

        self.delayDisplay("Test passed")
