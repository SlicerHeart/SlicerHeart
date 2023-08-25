import logging
import os
from typing import Annotated, Optional

import vtk

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)

from slicer import vtkMRMLScalarVolumeNode
from slicer import vtkMRMLTransformNode
from slicer import vtkMRMLMarkupsPlaneNode
from slicer import vtkMRMLModelNode

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

<h2>Convert image to flow field</h2>

Converts velocity component images to a "flow field" - a grid transform that stores the velocity vector for each voxel in m/s.
<p>
Load a Siemens cardiac 4D flow study, for example: "MR HEART W & W O IV CONTRAST" study, with 4 series
(the 3 series contain the 3 speed components and the 4th series is the magnitude image):
"112: CS4Dflow_R7.7_retro_post 1.6 x 1.6_P", "113: CS4Dflow_R7.7_retro_post 1.6 x 1.6_P", "114: CS4Dflow_R7.7_retro_post 1.6 x 1.6_P",
and "115: CS4Dflow_R7.7_retro_post 1.6 x 1.6".
<p>
Click "Refresh" button, make sure a flow study is selected "Input flow image" and click "Convert".

<h2>Export flow field to file</h2>

Exports the "flow field" to a set of .nrrd files. Make sure a "Flow field" is selected at the top of the module,
select an output directory, and click "Export".

Voxel values are in m/s.
The file does not contain any patient information.

<p>

If the file is read back into Slicer as a transform, invert the transform after reading it,
to make sure the transform is used as "transform to parent"
(not "transform from parent" - as it is assumed when reading a displacement field from file).

<h2>Flow field profile</h2>

To get numpy array that contains displacement values and position:

<pre>
crossSectionModelNode = getNode("CrossSectionSamplingGrid")
displacements = arrayFromModelPointData(crossSectionModelNode, 'displacement')
positions = arrayFromModelPoints(crossSectionModelNode)
</pre>

See more information in <a href="https://github.com/SlicerHeart/SlicerHeart#Import4DFlow">module documentation</a>.
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
    samplingDistance: Annotated[float, WithinRange(0.01, 10)] = 2

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
        # volumeNodeSet contains 'name' (displayable name of the node set) and 'volumeNodes' (list of 4 nodes: x, y, z, magnitude)
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

            gridTransformNode, magnitudeVolumeNode = self.logic.convertImagesToDisplacementField(
                self._volumeNodesSets[self._parameterNode.inputVolumeNodeSet]['volumeNodes'],
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

            outputModel = self.logic.sampleFlowFieldWithPlane(
                self._parameterNode.inputPlane,
                self._parameterNode.outputTransform,
                self._parameterNode.outputTransform.GetNodeReference("magnitudeVolume"),
                self._parameterNode.samplingDistance,
                self._parameterNode.outputSpeedProfileModel)
            
            if not self._parameterNode.outputSpeedProfileModel:
                self._parameterNode.outputSpeedProfileModel = outputModel


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

        # Converts direction code (in the DICOM header) to axis index (x, y, z, magnitude)
        self.axisForDirectionCode = {
            'through': 0,
            'inplane_ap': 1,
            'inplane_fh': 2,
            'magnitude': 3,
        }


    def getParameterNode(self):
        return Import4DFlowParameterNode(super().getParameterNode())

    def findVolumeNodeSets(self):
        # Map from {StudyInstanceUID}/{AcquisitionNumber} to volumesNodeSet:
        # {
        #   'name': 'Patient Name (study date) / 1',
        #   'volumeNodes': [volumeNodeX, volumeNodeY, volumeNodeZ, volumeNodeMagnitude],
        #   'venc': [150, 150, 150, 0]  # velocity encoding, in cm/sec
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
                    continue
                instUids = instUidsStr.split()
                filename = slicer.dicomDatabase.fileForInstance(instUids[0])
                ds = pydicom.read_file(filename)
                if (0x0051,0x1014) in ds:
                    # flow vector component image
                    # The tag contains speed and direction, for example:
                    # 'v150_through', 'v150_inplane_ap', 'v150_inplane_fh'
                    speedAndDirectionCode = ds[0x0051,0x1014].value.decode().strip()
                    vencInput, directionCodeInput = speedAndDirectionCode.split('_', 1)
                    venc = float(vencInput[1:])
                    directionCode = directionCodeInput.strip()
                elif ("SequenceName" in ds) and (ds["SequenceName"].value == 'WIP_fl3d1r2'):
                    # magnitude image
                    directionCode = 'magnitude'
                    venc = 0
                else:
                    # something else
                    continue
            except Exception as e:
                # error accessing DICOM fields
                print(traceback.format_exc())
                continue

            studyInstanceUID = ds["StudyInstanceUID"].value.strip()
            acquisitionNumber = ds["AcquisitionNumber"].value
            acquisitionID = str(studyInstanceUID) + "/" + str(acquisitionNumber)
            if acquisitionID not in volumeNodesSets:
                acquisitionNumberSuffix =  f" / {acquisitionNumber}" if acquisitionNumber > 1 else ""
                volumeNodeSet = {
                    'name': f"{ds.PatientName.family_comma_given()} ({ds.StudyDate}){acquisitionNumberSuffix}",
                    'volumeNodes': [None, None, None, None],  # x, y, z, magnitude
                    'venc': [None, None, None, 0]  # velocity encoding, in cm/sec (not applicable to magnitude image)
                    }
                volumeNodesSets[acquisitionID] = volumeNodeSet

            volumeNodesSets[acquisitionID]['volumeNodes'][self.axisForDirectionCode[directionCode]] = volumeNode
            volumeNodesSets[acquisitionID]['venc'][self.axisForDirectionCode[directionCode]] = venc

        validatedVolumeNodeSets = {}
        for volumeNodesSet in volumeNodesSets:
            volumeNodes = volumeNodesSets[volumeNodesSet]['volumeNodes']
            valid = True
            for axis in range(len(volumeNodes)):
                if not volumeNodes[axis]:
                    logging.info(f"Volume node set {volumeNodesSets[volumeNodesSet]['name']} is discarded: missing component ({axis})")
                    valid = False
                    break
            if valid:
                validatedVolumeNodeSets[volumeNodesSet] = volumeNodesSets[volumeNodesSet]

        return validatedVolumeNodeSets

    def convertImagesToDisplacementField(self, volumeNodes: list, venc: list, gridTransformNode: vtkMRMLTransformNode = None) -> [vtkMRMLTransformNode, vtkMRMLScalarVolumeNode]:
        volumeSequenceBrowserNodes = []
        volumeSequenceNodes = []
        for axis in range(len(volumeNodes)):
            volumeSequenceProxyNode = volumeNodes[axis]
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
            # volumeIndex = 7
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

        magnitudeVolumeNode = volumeNodes[self.axisForDirectionCode['magnitude']]

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

        return gridTransformNode, magnitudeVolumeNode

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

    def sampleFlowFieldWithPlane(self,
                            crossSectionPlaneNode: vtkMRMLMarkupsPlaneNode,
                            gridTransformNode: vtkMRMLTransformNode,
                            magnitudeVolumeNode: vtkMRMLScalarVolumeNode,
                            samplingDistanceMm: float = 2.0,
                            samplingGridModelNode: vtkMRMLModelNode = None) -> vtkMRMLModelNode:

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
            samplingGridModelNode = modelsLogic.AddModel(objectToWorldTransformFilter.GetOutputPort())
        samplingGridModelNode.SetName("CrossSectionSamplingGrid")
        displayNode = samplingGridModelNode.GetDisplayNode()
        displayNode.SetColor(1, 1, 0)
        displayNode.SetRepresentation(slicer.vtkMRMLModelDisplayNode.WireframeRepresentation)
        displayNode.BackfaceCullingOff()
        displayNode.LightingOff()  # don't make the grid darker if it is rotated

        # Sample displacement field with the model
        displacementImageNode = slicer.modules.transforms.logic().CreateDisplacementVolumeFromTransform(gridTransformNode, magnitudeVolumeNode, False)
        parameters = {}
        parameters["InputVolume"] = displacementImageNode
        parameters["InputModel"] = samplingGridModelNode
        parameters["OutputModel"] = samplingGridModelNode
        parameters["OutputArrayName"] = "displacement"
        probeVolumeWithModel = slicer.modules.probevolumewithmodel
        cliNode = slicer.cli.runSync(probeVolumeWithModel, None, parameters)
        # Process results
        if cliNode.GetStatus() & cliNode.ErrorsMask:
            # error
            errorText = cliNode.GetErrorText()
            slicer.mrmlScene.RemoveNode(cliNode)
            raise ValueError("CLI execution failed: " + errorText)
        # success
        slicer.mrmlScene.RemoveNode(cliNode)
        slicer.mrmlScene.RemoveNode(displacementImageNode)

        return samplingGridModelNode

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
