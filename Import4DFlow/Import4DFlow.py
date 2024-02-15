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
from slicer import vtkMRMLTableNode

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
This file was originally developed by Andras Lasso, PerkLab.
"""


#
# Import4DFlowParameterNode
#

@parameterNodeWrapper
class Import4DFlowParameterNode:
    """
    The parameters needed by module.

    inputVolume - The volume to threshold.
    imageThreshold - The value at which to threshold the input volume.
    invertThreshold - If true, will invert the threshold.
    thresholdedVolume - The output volume that will contain the thresholded volume.
    invertedVolume - The output volume that will contain the inverted thresholded volume.
    """
    outputTransform: vtkMRMLTransformNode
    inputVolumeNodeSet: str
    exportDirectory: str
    inputPlane: vtkMRMLMarkupsPlaneNode
    outputSpeedProfileModel: vtkMRMLModelNode
    outputSpeedProfileTable: vtkMRMLTableNode
    samplingDistance: Annotated[float, WithinRange(0.01, 10)] = 2  # distance unit
    speedThreshold: Annotated[float, WithinRange(0.0, 3), SingleStep(0.01), Default(0.1)]  # m/sec

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
        #   - 'componentVolumeNodes': list of 3 volume nodes (x, y, z component)
        #   - 'magnitudeVolumeNode' magnitude volume node
        self._volumeNodesSets = {}

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

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = Import4DFlowLogic()
        self.logic.logCallback = self.addLog

        # Connections

        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        # Buttons
        self.ui.inputVolumeNodeSetSelector.connect('currentIndexChanged(int)', self.updateParameterNodeFromGUI)
        self.ui.exportPathLineEdit.connect('currentPathChanged(QString)', self.updateParameterNodeFromGUI)
        self.ui.inspectButton.connect('clicked(bool)', self.onInspectButton)
        self.ui.convertButton.connect('clicked(bool)', self.onConvertButton)
        self.ui.exportButton.connect('clicked(bool)', self.onExportButton)
        self.ui.applyButton.connect('clicked(bool)', self.onApplyButton)
        self.ui.showPlotButton.connect('clicked(bool)', self.onShowPlotButton)

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

        # Update apply button state and tooltip
        if self._parameterNode and self._parameterNode.inputVolumeNodeSet:
            self.ui.convertButton.toolTip = "Convert input flow image to flow field"
            self.ui.convertButton.enabled = True
        else:
            self.ui.convertButton.toolTip = "Select a valid input flow image"
            self.ui.convertButton.enabled = False

        self.ui.exportPathLineEdit.setCurrentPath(self._parameterNode.exportDirectory)

        # Update apply button state and tooltip
        if self._parameterNode and self._parameterNode.exportDirectory and self._parameterNode.outputTransform:
            self.ui.exportButton.toolTip = "Export flow field to NRRD files"
            self.ui.exportButton.enabled = True
        else:
            self.ui.exportButton.toolTip = "Select a valid input flow field and output directory"
            self.ui.exportButton.enabled = False


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
            #self._parameterNode.ComponentToExtract = self.ui.componentsSpinBox.value


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

            magnitudeVolumeNode = self._volumeNodesSets[self._parameterNode.inputVolumeNodeSet]['magnitudeVolumeNode']
            gridTransformNode = self.logic.convertImagesToDisplacementField(
                self._volumeNodesSets[self._parameterNode.inputVolumeNodeSet]['componentVolumeNodes'],
                magnitudeVolumeNode,
                self._volumeNodesSets[self._parameterNode.inputVolumeNodeSet]['venc'],
                self._parameterNode.outputTransform)

            self._parameterNode.outputTransform = gridTransformNode
            self._parameterNode.outputTransform.SetNodeReferenceID("magnitudeVolume", magnitudeVolumeNode.GetID())

            self.onInspectButton()


    def onExportButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to export the flow field to files.", waitCursor=True):
            self.logic.exportDisplacementFieldToFiles(self._parameterNode.outputTransform, self._parameterNode.exportDirectory)


    def onApplyButton(self) -> None:
        """
        Run processing when user clicks "Apply" button.
        """
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):

            self.addLog("Sample flow field...")
            self._parameterNode.outputSpeedProfileModel = self.logic.sampleFlowFieldWithPlane(
                self._parameterNode.inputPlane,
                self._parameterNode.outputTransform,
                self._parameterNode.outputTransform.GetNodeReference("magnitudeVolume"),
                self._parameterNode.samplingDistance,
                self._parameterNode.outputSpeedProfileModel)

            self.addLog("Compute speed profile table...")
            self._parameterNode.outputSpeedProfileTable = self.logic.computeSpeedProfileTable(
                self._parameterNode.outputSpeedProfileModel,
                self._parameterNode.speedThreshold,
                self._parameterNode.outputSpeedProfileTable)

    def onShowPlotButton(self) -> None:
        with slicer.util.tryWithErrorDisplay("Failed to create plot."):
            self.logic.createPlotFromTable(self._parameterNode.outputSpeedProfileTable)

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

    def __init__(self) -> None:
        """
        Called when the logic class is instantiated. Can be used for initializing member variables.
        """
        ScriptedLoadableModuleLogic.__init__(self)

        self.logCallback = None

        # Converts direction code (in the DICOM header) to axis index (x, y, z, magnitude)
        self.axisForDirectionCode = {
            'through': 0,
            'inplane_ap': 1,
            'inplane_fh': 2,
            'magnitude': 3,
        }

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

    def findVolumeNodeSets(self):
        # Map from {StudyInstanceUID}/{AcquisitionNumber} to volumesNodeSet:
        # {
        #   'name': 'Patient Name (study date) / 1',
        #   'componentVolumeNodes': [volumeNodeX, volumeNodeY, volumeNodeZ],
        #   'magnitudeVolumeNode': volumeNodeMagnitude,
        #   'venc': [150, 150, 150]  # velocity encoding, in cm/sec
        # }
        volumeNodesSets = {}

        import pydicom
        import traceback

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
                ds = pydicom.read_file(filename)
                if (0x0051,0x1014) in ds:
                    # flow vector component image
                    logging.debug(f"Found a flow vector component image: {volumeNode.GetName()}")
                    # The tag contains speed and direction, for example:
                    # 'v150_through', 'v150_inplane_ap', 'v150_inplane_fh'
                    speedAndDirectionCode = ds[0x0051,0x1014].value.decode().strip()
                    vencInput, directionCodeInput = speedAndDirectionCode.split('_', 1)
                    venc = float(vencInput[1:])
                    directionCode = directionCodeInput.strip()
                elif ("SequenceName" in ds) and ('fl3d' in ds["SequenceName"].value):  # 'WIP_fl3d1r2' or 'WIP_fl3d1r3'
                    # magnitude image
                    logging.debug(f"Found a magnitude image: {volumeNode.GetName()}")
                    directionCode = 'magnitude'
                    venc = 0
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
            acquisitionID = str(studyInstanceUID) + "/" + str(acquisitionNumber)
            if acquisitionID not in volumeNodesSets:
                acquisitionNumberSuffix =  f" / {acquisitionNumber}" if acquisitionNumber > 1 else ""
                volumeNodeSet = {
                    'name': f"{ds.PatientName.family_comma_given()} ({ds.StudyDate}){acquisitionNumberSuffix}",
                    'componentVolumeNodes': [None, None, None],  # x, y, z
                    'magnitudeVolumeNode': None,
                    'candidateMagnitudeVolumeNodes': [],  # temporary list used only during inspection, as there may be several candidates in the study
                    'venc': [None, None, None]  # velocity encoding, in cm/sec
                    }
                volumeNodesSets[acquisitionID] = volumeNodeSet

            if directionCode == 'magnitude':
                volumeNodesSets[acquisitionID]['candidateMagnitudeVolumeNodes'].append(volumeNode)
            else:
                volumeNodesSets[acquisitionID]['componentVolumeNodes'][self.axisForDirectionCode[directionCode]] = volumeNode
                volumeNodesSets[acquisitionID]['venc'][self.axisForDirectionCode[directionCode]] = venc

        validatedVolumeNodeSets = {}
        for volumeNodesSet in volumeNodesSets:
            volumeNodes = volumeNodesSets[volumeNodesSet]['componentVolumeNodes']
            valid = True
            numberOfFrames = None

            # Check component volumes
            for axis in range(len(volumeNodes)):
                if not volumeNodes[axis]:
                    logging.warning(f"Volume node set {volumeNodesSets[volumeNodesSet]['name']} is discarded: missing component ({axis})")
                    valid = False
                    break
                if numberOfFrames is None:
                    numberOfFrames = self._getNumberOfDataNodesInSequence(volumeNodes[axis])
                else:
                    currentNumberOfFrames = self._getNumberOfDataNodesInSequence(volumeNodes[axis])
                    if currentNumberOfFrames != numberOfFrames:
                        logging.warning(f"Volume node set {volumeNodesSets[volumeNodesSet]['name']} is discarded: inconsistent number of frames ({currentNumberOfFrames} vs {numberOfFrames})")
                        valid = False
                        break
            if not valid:
                continue

            # Check/select magnitude volume
            volumeNodes = volumeNodesSets[volumeNodesSet]['candidateMagnitudeVolumeNodes']
            for volumeNode in volumeNodes:
                currentNumberOfFrames = self._getNumberOfDataNodesInSequence(volumeNode)
                if currentNumberOfFrames != numberOfFrames:
                    logging.warning(f"Volume node set {volumeNodesSets[volumeNodesSet]['name']}: candidate magnitude volume {volumeNode.GetName()} discarded due to inconsistent number of frames ({currentNumberOfFrames} vs {numberOfFrames})")
                    continue
                # Found a good candidate magnitude volume, use it
                volumeNodesSets[volumeNodesSet]['magnitudeVolumeNode'] = volumeNode
                break

            if not volumeNodesSets[volumeNodesSet]['magnitudeVolumeNode']:
                logging.warning(f"Volume node set {volumeNodesSets[volumeNodesSet]['name']} is discarded: magnitude volume is not found")
                continue

            validatedVolumeNodeSets[volumeNodesSet] = volumeNodesSets[volumeNodesSet]

        return validatedVolumeNodeSets

    def convertImagesToDisplacementField(self, componentVolumeNodes: list, magnitudeVolumeNode: vtkMRMLScalarVolumeNode, venc: list, gridTransformNode: vtkMRMLTransformNode = None) -> [vtkMRMLTransformNode, vtkMRMLScalarVolumeNode]:
        volumeSequenceBrowserNodes = []
        volumeSequenceNodes = []
        volumeNodes = componentVolumeNodes + [magnitudeVolumeNode]
        print(volumeNodes)
        for axis, volumeSequenceProxyNode in enumerate(volumeNodes):
            if not volumeSequenceProxyNode:
                raise RuntimeError(f"Volume ({axis}) is invalid")
            volumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(volumeSequenceProxyNode)
            if not volumeSequenceBrowserNode:
                raise RuntimeError(f"Volume {volumeSequenceProxyNode.GetName()} is expected to be proxy node of a volume sequence")
            volumeSequenceNode = volumeSequenceBrowserNode.GetSequenceNode(volumeSequenceProxyNode)
            volumeSequenceBrowserNodes.append(volumeSequenceBrowserNode)
            volumeSequenceNodes.append(volumeSequenceNode)

        import numpy as np
        numberOfFrames = volumeSequenceNodes[0].GetNumberOfDataNodes()

        volumeSequenceProxyNode = volumeNodes[0]
        dims = slicer.util.arrayFromVolume(volumeSequenceProxyNode).shape

        displacementImage = vtk.vtkImageData()
        displacementImage.SetDimensions(dims[2], dims[1], dims[0])
        displacementImage.AllocateScalars(vtk.VTK_FLOAT, 3)

        gridTransform = slicer.vtkOrientedGridTransform()
        directionMatrix = vtk.vtkMatrix4x4()
        volumeSequenceProxyNode.GetIJKToRASDirectionMatrix(directionMatrix)
        gridTransform.SetGridDirectionMatrix(directionMatrix)
        displacementImage.SetSpacing(volumeSequenceProxyNode.GetSpacing())
        displacementImage.SetOrigin(volumeSequenceProxyNode.GetOrigin())
        gridTransform.SetDisplacementGridData(displacementImage)

        if not gridTransformNode:
            gridTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode")
        gridTransformNode.SetAndObserveTransformFromParent(gridTransform)

        displacementArray = slicer.util.arrayFromGridTransform(gridTransformNode)  # shape: (96, 160, 64, 3) = (i, j, k, c)

        magnitudeVolumeSequenceNode = volumeSequenceNodes[self.axisForDirectionCode['magnitude']]

        transformSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "4D flow")

        transformSequenceNode.SetIndexType(magnitudeVolumeSequenceNode.GetIndexType())
        transformSequenceNode.SetIndexName(magnitudeVolumeSequenceNode.GetIndexName())
        transformSequenceNode.SetIndexUnit(magnitudeVolumeSequenceNode.GetIndexUnit())

        # Use meter per sec as displacement value (divide by 100) because a typical 50 cm/sec speed
        # = 0.5 m/sec speed value can be visualized nicely as displacement field
        speedScaleMeterPerSec = [1 / 4096 * venc[i] / 100 for i in range(3)]

        # LPS to RAS conversion
        directions = [-1, -1, 1]

        for volumeIndex in range(numberOfFrames):
            magnitudeVoxelArray = slicer.util.arrayFromVolume(magnitudeVolumeSequenceNode.GetNthDataNode(volumeIndex)).copy()
            for axis in range(3):
                volumeSequenceNode = volumeSequenceNodes[axis]
                voxelArray = slicer.util.arrayFromVolume(volumeSequenceNode.GetNthDataNode(volumeIndex)).copy() * speedScaleMeterPerSec[axis] * directions[axis]
                #voxelArray = np.ones(voxelArrayX.shape) * 10
                voxelArray[abs(magnitudeVoxelArray) < 100] = 0
                displacementArray[:, :, :, axis] = voxelArray
            slicer.util.arrayFromGridTransformModified(gridTransformNode)
            indexValue = magnitudeVolumeSequenceNode.GetNthIndexValue(volumeIndex)
            # The transform stores "transform from parent", but visualization displays "transform to parent".
            # (We could not set transform to parent directly because arrayFromGridTransformModified
            # only works with "transform from parent"). Invert the field now to display "transform to parent".
            # This also greatly speeds up the display.
            gridTransformNode.Inverse()
            transformSequenceNode.SetDataNodeAtValue(gridTransformNode, indexValue)
            # Revert to "transform from parent"
            gridTransformNode.Inverse()

        # Create a sequence browser node for the new merged sequence
        transformSequenceBrowserNode = volumeSequenceBrowserNodes[self.axisForDirectionCode['magnitude']]
        transformSequenceBrowserNode.AddSynchronizedSequenceNode(transformSequenceNode)
        slicer.modules.sequences.toolBar().setActiveBrowserNode(transformSequenceBrowserNode)

        slicer.mrmlScene.RemoveNode(gridTransformNode)
        del gridTransformNode

        slicer.modules.sequences.logic().UpdateAllProxyNodes()
        gridTransformNode = transformSequenceBrowserNode.GetProxyNode(transformSequenceNode)

        # Place transform in the same subject hierarchy folder as the volume node
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        volumeParentItemId = shNode.GetItemParent(shNode.GetItemByDataNode(magnitudeVolumeNode))
        shNode.SetItemParent(shNode.GetItemByDataNode(gridTransformNode), volumeParentItemId)

        if not gridTransformNode.GetDisplayNode():
            transformDisplayNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformDisplayNode")
            gridTransformNode.AddAndObserveDisplayNodeID(transformDisplayNode.GetID())
            transformDisplayNode.SetVisibility(True)
            transformDisplayNode.SetVisibility2D(True)
            transformDisplayNode.SetVisibility3D(False)  # with small glyph spacing, updating of the glyphs in 3D can be slow
            transformDisplayNode.SetGlyphDisplayRangeMinMm(0.05) # meter/sec
            transformDisplayNode.SetGlyphSpacingMm(2.0)
            transformDisplayNode.SetGlyphDiameterMm(0.8)
            transformDisplayNode.SetGlyphScalePercent(500)
            transformDisplayNode.SetAndObserveRegionNode(magnitudeVolumeNode)

            # Create color node
            colorNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLProceduralColorNode")
            colorNode.UnRegister(None)  # to prevent memory leaks
            colorNode.SetName(slicer.mrmlScene.GenerateUniqueName("Speed"))
            colorNode.SetAttribute("Category", "Flow")
            # The color node is a procedural color node, which is saved using a storage node.
            # Hidden nodes are not saved if they use a storage node, therefore
            # the color node must be visible.
            colorNode.SetHideFromEditors(False)
            slicer.mrmlScene.AddNode(colorNode)
            # Add a transfer function with some default values
            colorMap = colorNode.GetColorTransferFunction()
            colorMap.AddRGBPoint(0.0, 0.0, 0.0, 0.0)
            colorMap.AddRGBPoint(1.5, 1.0, 1.0, 1.0)
            transformDisplayNode.SetAndObserveColorNodeID(colorNode.GetID())

            # Display color legend
            colorLegendDisplayNode = slicer.modules.colors.logic().AddDefaultColorLegendDisplayNode(transformDisplayNode)
            colorLegendDisplayNode.SetTitleText("speed")
            colorLegendDisplayNode.SetLabelFormat("%4.1f m/s")
            #colorLegendDisplayNode.SetScalarRange(0, 1.5)

        # Update colormap colors
        colorMap = gridTransformNode.GetDisplayNode().GetColorNode().GetColorTransferFunction()
        wasModified = gridTransformNode.GetDisplayNode().GetColorNode().StartModify()
        colorMap.RemoveAllPoints()
        colorTableRangeMm = max(venc) / 100  # m/sec
        colorMap.AddRGBPoint(colorTableRangeMm * 0.0, 0.0, 0.0, 1.0)
        colorMap.AddRGBPoint(colorTableRangeMm * 0.2, 0.0, 1.0, 1.0)
        colorMap.AddRGBPoint(colorTableRangeMm * 0.5, 1.0, 1.0, 0.0)
        colorMap.AddRGBPoint(colorTableRangeMm * 1.0, 1.0, 0.0, 0.0)
        gridTransformNode.GetDisplayNode().GetColorNode().EndModify(wasModified)

        # Delete imported component image series from the scene
        for axisIndex in range(3):
            slicer.mrmlScene.RemoveNode(volumeSequenceNodes[axisIndex])
            slicer.mrmlScene.RemoveNode(volumeNodes[axisIndex].GetDisplayNode())
            slicer.mrmlScene.RemoveNode(volumeNodes[axisIndex].GetStorageNode())
            slicer.mrmlScene.RemoveNode(volumeNodes[axisIndex])
            slicer.mrmlScene.RemoveNode(volumeSequenceBrowserNodes[axisIndex])

        return gridTransformNode

    def exportDisplacementFieldToFiles(self,
                                       gridTransformNode: vtkMRMLTransformNode,
                                       exportDirectory: str) -> None:
        transformSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(gridTransformNode)

        try:
            import nrrd
        except ImportError:
            slicer.util.pip_install('pynrrd')
            import nrrd

        originalItemNumber = transformSequenceBrowserNode.GetSelectedItemNumber()
        for itemNumber in range(transformSequenceBrowserNode.GetNumberOfItems()):
            transformSequenceBrowserNode.SetSelectedItemNumber(itemNumber)

            # Only "from parent" transform can be written to file, invert it temporarily
            gridTransformNode.Inverse()

            exportedFile = f"{exportDirectory}/transform_{itemNumber:02d}.nrrd"
            slicer.util.exportNode(gridTransformNode, exportedFile)

            # Patch the written file
            readdata, header = nrrd.read(exportedFile)
            # remove intent code (used by nifti)
            del header['intent_code']
            # store voxel value units
            header['sample units'] = 'm/s'
            header['TransformDirection'] = 'to parent'
            nrrd.write(exportedFile, readdata, header)

            # Revert the temporary inversion
            gridTransformNode.Inverse()

        transformSequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)

    def sampleFlowFieldWithPlane(
            self,
            crossSectionPlaneNode: vtkMRMLMarkupsPlaneNode,
            gridTransformNode: vtkMRMLTransformNode,
            magnitudeVolumeNode: vtkMRMLScalarVolumeNode,
            samplingDistanceMm: float = 2.0,
            samplingGridModelNode: vtkMRMLModelNode = None) -> vtkMRMLModelNode:

        transformSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(gridTransformNode)
        if not transformSequenceBrowserNode:
            raise RuntimeError("Input transform is not in a sequence")

        # Temporary nodes
        displacementImageNode = None
        probeVolumeCliNode = None

        try:

            # Turn off transform visibility to speed up browsing
            if gridTransformNode.GetDisplayNode():
                originalTransformVisibility = gridTransformNode.GetDisplayNode().GetVisibility()
                gridTransformNode.GetDisplayNode().SetVisibility(False)
            else:
                originalTransformVisibility = False

            originalItemNumber = transformSequenceBrowserNode.GetSelectedItemNumber()
            for itemNumber in range(transformSequenceBrowserNode.GetNumberOfItems()):
                self.log("Sampling flow field with plane... ({item}/{count})".format(item=itemNumber+1, count=transformSequenceBrowserNode.GetNumberOfItems()))

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
                if not samplingGridModelNode:
                    samplingGridModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "CrossSectionSamplingGrid")
                    samplingGridModelNode.CreateDefaultDisplayNodes()
                    displayNode = samplingGridModelNode.GetDisplayNode()
                    displayNode.SetColor(1, 1, 0)
                    displayNode.SetRepresentation(slicer.vtkMRMLModelDisplayNode.WireframeRepresentation)
                    displayNode.BackfaceCullingOff()
                    displayNode.LightingOff()  # don't make the grid darker if it is rotated

                # Add the model to the same sequence browser as the input 4D flow field

                # Make sure the model is in the same sequence browser as the transform sequence and
                # model is in not a proxy node of any other sequence browsers
                foundBrowserNodes = vtk.vtkCollection()
                sequencesLogic = slicer.modules.sequences.logic()
                sequencesLogic.GetBrowserNodesForProxyNode(samplingGridModelNode, foundBrowserNodes)
                modelSequenceNode = None
                for i in range(foundBrowserNodes.GetNumberOfItems()):
                    foundBrowserNode = foundBrowserNodes.GetItemAsObject(i)
                    foundSequenceNode = transformSequenceBrowserNode.GetSequenceNode(samplingGridModelNode)
                    if foundBrowserNode == transformSequenceBrowserNode:
                        # Store the sequence node corresponding to the transform sequence browser node
                        modelSequenceNode = foundSequenceNode
                    else:
                        # Remove model from other sequence browser nodes
                        foundBrowserNode.RemoveSynchronizedSequenceNode(foundSequenceNode.GetID())

                if not modelSequenceNode:
                    masterSequenceNode = transformSequenceBrowserNode.GetMasterSequenceNode()
                    modelSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "Cross-section model sequence")
                    modelSequenceNode.SetIndexType(masterSequenceNode.GetIndexType())
                    modelSequenceNode.SetIndexName(masterSequenceNode.GetIndexName())
                    modelSequenceNode.SetIndexUnit(masterSequenceNode.GetIndexUnit())
                    slicer.modules.sequences.logic().AddSynchronizedNode(modelSequenceNode, samplingGridModelNode, transformSequenceBrowserNode)
                    transformSequenceBrowserNode.SetSaveChanges(modelSequenceNode, True)

                objectToWorldTransformFilter.Update()
                samplingGridModelNode.SetAndObservePolyData(objectToWorldTransformFilter.GetOutput())

                # Sample displacement field with the model
                displacementImageNode = slicer.modules.transforms.logic().CreateDisplacementVolumeFromTransform(gridTransformNode, magnitudeVolumeNode, False)
                parameters = {}
                parameters["InputVolume"] = displacementImageNode
                parameters["InputModel"] = samplingGridModelNode
                parameters["OutputModel"] = samplingGridModelNode
                parameters["OutputArrayName"] = "displacement"
                probeVolumeWithModel = slicer.modules.probevolumewithmodel
                probeVolumeCliNode = slicer.cli.runSync(probeVolumeWithModel, probeVolumeCliNode, parameters)
                # Process results
                if probeVolumeCliNode.GetStatus() & probeVolumeCliNode.ErrorsMask:
                    # error
                    errorText = probeVolumeCliNode.GetErrorText()
                    raise ValueError("Probe 4D field execution failed: " + errorText)

                slicer.mrmlScene.RemoveNode(displacementImageNode)
                displacementImageNode = None

        finally:
            # Clean up
            if probeVolumeCliNode:
                slicer.mrmlScene.RemoveNode(probeVolumeCliNode)
            if displacementImageNode:
                slicer.mrmlScene.RemoveNode(displacementImageNode)
            transformSequenceBrowserNode.SetSelectedItemNumber(originalItemNumber)
            if originalTransformVisibility and gridTransformNode.GetDisplayNode():
                gridTransformNode.GetDisplayNode().SetVisibility(True)

        return samplingGridModelNode

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
        speedArray.SetName("speed")

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
            speed = slicer.util.arrayFromModelPointData(crossSectionModelNode, 'displacement')
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
        outputSpeedProfileTableNode.SetColumnUnitLabel(speedArray.GetName(), "cm/sec")  # TODO: verify the unit

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

        # Get/create input data

        import SampleData
        registerSampleData()
        inputVolume = SampleData.downloadSample('Import4DFlow1')
        self.delayDisplay('Loaded test data set')

        inputScalarRange = inputVolume.GetImageData().GetScalarRange()
        self.assertEqual(inputScalarRange[0], 0)
        self.assertEqual(inputScalarRange[1], 695)

        outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        threshold = 100

        # Test the module logic

        logic = Import4DFlowLogic()

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
