import logging
import os

import vtk

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin


#
# OrificeArea
#

class OrificeArea(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Orifice Area"
        self.parent.categories = ["Cardiac"]
        self.parent.dependencies = []
        self.parent.contributors = ["Andras Lasso (PerkLab, Queen's University)", "Matt Jolley (CHOP/UPenn)"]
        self.parent.helpText = """
Compute area of a hole in a surface mesh, inside the orifice boundary curve drawn on the mesh.

See more information in <a href="https://github.com/SlicerHeart/SlicerHeart/Docs/OrificeArea.md#orifice-area">module documentation</a>.
"""
        # TODO: replace with organization, grant and thanks
        self.parent.acknowledgementText = """
This work was supported by a Children's Hospital of Philadelphia (CHOP) Cardiac Center Innovation Grant, and NIH R01 HL153166.
"""


#
# OrificeAreaWidget
#

class OrificeAreaWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
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

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath('UI/OrificeArea.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = OrificeAreaLogic()

        # Connections

        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
        # (in the selected parameter node).
        self.ui.inputSurfaceModelSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.inputBoundaryCurveSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.outputThickSurfaceModelSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.outputOrificeModelSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.outputStreamLinesModelSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.outputOrificePointsSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.surfaceThicknessSliderWidget.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
        self.ui.shrinkWrapIterationsSliderWidget.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
        self.ui.streamLineLengthSliderWidget.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
        self.ui.distanceFromStreamLineSliderWidget.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
        self.ui.keepIntermediateResultsCheckBox.connect("toggled(bool)", self.updateParameterNodeFromGUI)

        # Buttons
        self.ui.createAllOutputsToolButton.connect('clicked(bool)', self.onCreateAllOutputs)
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
        if not self._parameterNode.GetNodeReference("InputSurfaceModel"):
            # Find first model node that is not a slice model
            modelNodes = slicer.util.getNodesByClass("vtkMRMLModelNode")
            for modelNode in modelNodes:
                if not slicer.vtkMRMLSliceLogic.IsSliceModelNode(modelNode):
                    self._parameterNode.SetNodeReferenceID("InputSurfaceModel", modelNode.GetID())
                    break
        if not self._parameterNode.GetNodeReference("InputBoundaryCurve"):
            firstNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLMarkupsClosedCurveNode")
            if firstNode:
                self._parameterNode.SetNodeReferenceID("InputBoundaryCurve", firstNode.GetID())

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

        # Update node selectors and sliders
        self.ui.inputSurfaceModelSelector.setCurrentNode(self._parameterNode.GetNodeReference("InputSurfaceModel"))
        self.ui.inputBoundaryCurveSelector.setCurrentNode(self._parameterNode.GetNodeReference("InputBoundaryCurve"))
        self.ui.outputThickSurfaceModelSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputThickSurfaceModel"))
        self.ui.outputOrificeModelSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputOrificeModel"))
        self.ui.outputStreamLinesModelSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputStreamLinesModel"))
        self.ui.outputOrificePointsSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputOrificePoints"))
        self.ui.surfaceThicknessSliderWidget.value = float(self._parameterNode.GetParameter("SurfaceThickness"))
        self.ui.shrinkWrapIterationsSliderWidget.value = int(float(self._parameterNode.GetParameter("ShrinkWrapIterations")))
        self.ui.streamLineLengthSliderWidget.value = float(self._parameterNode.GetParameter("StreamLineLength"))
        self.ui.distanceFromStreamLineSliderWidget.value = float(self._parameterNode.GetParameter("DistanceFromStreamLine"))
        self.ui.keepIntermediateResultsCheckBox.checked = (self._parameterNode.GetParameter("KeepIntermediateResults") == "true")

        # Update buttons states and tooltips
        if self._parameterNode.GetNodeReference("InputSurfaceModel") and self._parameterNode.GetNodeReference("InputBoundaryCurve"):
            self.ui.applyButton.toolTip = "Compute orifice area"
            self.ui.applyButton.enabled = True
        else:
            self.ui.applyButton.toolTip = "Select input Surface and Orifice boundary"
            self.ui.applyButton.enabled = False

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

        self._parameterNode.SetNodeReferenceID("InputSurfaceModel", self.ui.inputSurfaceModelSelector.currentNodeID)
        self._parameterNode.SetNodeReferenceID("InputBoundaryCurve", self.ui.inputBoundaryCurveSelector.currentNodeID)
        self._parameterNode.SetNodeReferenceID("OutputThickSurfaceModel", self.ui.outputThickSurfaceModelSelector.currentNodeID)
        self._parameterNode.SetNodeReferenceID("OutputOrificeModel", self.ui.outputOrificeModelSelector.currentNodeID)
        self._parameterNode.SetNodeReferenceID("OutputStreamLinesModel", self.ui.outputStreamLinesModelSelector.currentNodeID)
        self._parameterNode.SetNodeReferenceID("OutputOrificePoints", self.ui.outputOrificePointsSelector.currentNodeID)
        self._parameterNode.SetParameter("SurfaceThickness", str(self.ui.surfaceThicknessSliderWidget.value))
        self._parameterNode.SetParameter("StreamLineLength", str(self.ui.streamLineLengthSliderWidget.value))
        self._parameterNode.SetParameter("ShrinkWrapIterations", str(self.ui.shrinkWrapIterationsSliderWidget.value))
        self._parameterNode.SetParameter("DistanceFromStreamLine", str(self.ui.distanceFromStreamLineSliderWidget.value))
        self._parameterNode.SetParameter("KeepIntermediateResults", "true" if self.ui.keepIntermediateResultsCheckBox.checked else "false")

        self._parameterNode.EndModify(wasModified)

    def logMessage(self, message):
        logging.info(message)
        slicer.util.showStatusMessage(message, 3000)
        slicer.app.processEvents()

    def onApplyButton(self):
        """
        Run processing when user clicks "Apply" button.
        """

        self.ui.orificeAreaSpinBox.value = 0

        # install required pyacvd package
        try:
            import pyacvd
        except ModuleNotFoundError as e:
            if slicer.util.confirmOkCancelDisplay("This module requires 'pyacvd' Python package. Click OK to install it now."):
                slicer.util.pip_install("pyacvd")
            else:
                return

        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):

            # Compute output
            self.logic.logCallback = self.logMessage
            self.logic.keepIntermediateResults = self.ui.keepIntermediateResultsCheckBox.checked
            orificeArea = self.logic.process(self.ui.inputSurfaceModelSelector.currentNode(), self.ui.inputBoundaryCurveSelector.currentNode(),
                               self.ui.outputThickSurfaceModelSelector.currentNode(), self.ui.outputOrificeModelSelector.currentNode(),
                               self.ui.outputStreamLinesModelSelector.currentNode(),  self.ui.outputOrificePointsSelector.currentNode(),
                               self.ui.surfaceThicknessSliderWidget.value, int(self.ui.shrinkWrapIterationsSliderWidget.value),
                               self.ui.streamLineLengthSliderWidget.value,  self.ui.distanceFromStreamLineSliderWidget.value)
            self.ui.orificeAreaSpinBox.value = orificeArea

    def onCreateAllOutputs(self):
        outputNodeSelectors = [
            self.ui.outputThickSurfaceModelSelector,
            self.ui.outputOrificeModelSelector,
            self.ui.outputStreamLinesModelSelector,
            self.ui.outputOrificePointsSelector
        ]
        nameSuffix = f" {self.ui.inputSurfaceModelSelector.currentNode().GetName()}" if self.ui.inputSurfaceModelSelector.currentNode() else " "
        for nodeSelector in outputNodeSelectors:
            if not nodeSelector.currentNode():
                outputNode = slicer.mrmlScene.AddNewNodeByClass(nodeSelector.nodeTypes[0], nodeSelector.baseName + nameSuffix)
                nodeSelector.setCurrentNode(outputNode)


#
# OrificeAreaLogic
#

class OrificeAreaLogic(ScriptedLoadableModuleLogic):
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
        self.keepIntermediateResults = False
        self.logCallback = None

    def log(self, message):
        if self.logCallback:
            self.logCallback(message)

    def setDefaultParameters(self, parameterNode):
        """
        Initialize parameter node with default settings.
        """
        if not parameterNode.GetParameter("SurfaceThickness"):
            parameterNode.SetParameter("SurfaceThickness", "0.4")
        if not parameterNode.GetParameter("ShrinkWrapIterations"):
            parameterNode.SetParameter("ShrinkWrapIterations", "40")
        if not parameterNode.GetParameter("StreamLineLength"):
            parameterNode.SetParameter("StreamLineLength", "30")
        if not parameterNode.GetParameter("DistanceFromStreamLine"):
            parameterNode.SetParameter("DistanceFromStreamLine", "1.0")
        if not parameterNode.GetParameter("KeepIntermediateResults"):
            parameterNode.SetParameter("KeepIntermediateResults", "false")

    def process(self, inputSurfaceModel, inputBoundaryCurve,
                outputThickSurfaceModel, outputOrificeModel, outputStreamLinesModel, outputOrificePoints,
                surfaceThickness=0.4, shrinkWrapIterations=40, streamLineLength=30.0, distanceFromStreamLine=1.0):
        """
        Run the processing algorithm.
        Can be used without GUI widget.
        :return: total orifice area
        """

        # This value usually does not require tuning. It just adds 40% of the surface thickness when thresholding the distance
        # between the original surface and the shrink-wrapped surface.
        distanceMarginPercent = 40

        if not inputSurfaceModel or not inputBoundaryCurve:
            raise ValueError("Input or output volume is invalid")

        import time
        startTime = time.time()
        self.log('Processing started')

        # It is easier to shrink-wrap the medial surface, as it has less narrow valleys
        medialSurfaceMesh = self.getMedialSurface(inputSurfaceModel)
        thickSurface = self.createThickSurface(medialSurfaceMesh, outputThickSurfaceModel, surfaceThickness)
        gradientVolumeNode = self.createGradientVolume(thickSurface)
        initialShrinkWrapSurface = self.createInitialShrinkWrapSurface(inputBoundaryCurve)
        shrunkSurface = self.shrinkWrap(initialShrinkWrapSurface, medialSurfaceMesh, shrinkWrapIterations, gradientVolumeNode)
        # Slicer crashes when comes across this node, so always delete it
        slicer.mrmlScene.RemoveNode(gradientVolumeNode)

        self.log("Get potential orifice surface")
        orificeSurface = self.createOrificeSurface(medialSurfaceMesh, shrunkSurface, surfaceThickness, distanceMarginPercent)

        self.log("Find streamlines")
        # We shoot lines `streamLineLength` distance to all directions on both sides of the orifice.
        # If the line does not hit a wall on either side then there is a hole in the surface at that position.
        self.computeStreamLineLengths(orificeSurface, thickSurface, streamLineLength, outputStreamLinesModel)

        self.log("Split orifice surface")
        # Each connected component of the potential orifice surface is filtered: regions that are farther
        # away from streamlines by more than `distanceFromStreamLine` distance will be cut off.
        # The remaining area is considered as an orifice region.
        regions = self.splitOrificeSurface(orificeSurface, streamLineLength, distanceFromStreamLine, minimumSurfaceArea=surfaceThickness*surfaceThickness)

        self.log("Create total orifice surface")
        append = vtk.vtkAppendPolyData()
        if outputOrificePoints:
            outputOrificePoints.RemoveAllControlPoints()
            outputOrificePoints.GetDisplayNode().SetOccludedVisibility(True)  # make sure all points are visible, even if occludedin current view
        for regionIndex, [position, surfaceArea, surfaceMesh] in enumerate(regions):
            regionName = f"Or{regionIndex+1}"

            # Add a point scalar that allows us to distinguish orifice mesh regions
            componentIndexArray = vtk.vtkIntArray()
            componentIndexArray.SetName("OrificeRegion")
            componentIndexArray.SetNumberOfValues(surfaceMesh.GetNumberOfPoints())
            componentIndexArray.FillComponent(0, regionIndex+1)
            surfaceMesh.GetPointData().AddArray(componentIndexArray)

            append.AddInputData(surfaceMesh)
            if outputOrificePoints:
                outputOrificePoints.AddControlPoint(position, f"{regionName}: area={surfaceArea/100.0:.2f}cm2")

        append.Update()
        totalOrificeMesh = append.GetOutput()

        if outputOrificeModel:
            if not outputOrificeModel.GetMesh():
                # initial update
                outputOrificeModel.CreateDefaultDisplayNodes()
                outputOrificeModel.GetDisplayNode().SetColor(0, 0, 1)
                outputOrificeModel.GetDisplayNode().SetEdgeVisibility(True)
                outputOrificeModel.GetDisplayNode().SetVisibility2D(True)
                outputOrificeModel.GetDisplayNode().SetVisibility(True)
                outputOrificeModel.GetDisplayNode().SetActiveScalar("OrificeRegion", vtk.vtkAssignAttribute.POINT_DATA)
                outputOrificeModel.GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorNodeRandom")
                outputOrificeModel.GetDisplayNode().SetScalarVisibility(True)
            outputOrificeModel.SetAndObservePolyData(totalOrificeMesh)

        orificeSurfaceArea = OrificeAreaLogic.surfaceArea(totalOrificeMesh)
        logging.info(f"Total orifice surface area: {orificeSurfaceArea}")

        stopTime = time.time()
        logging.info(f'Processing completed in {stopTime-startTime:.2f} seconds')

        return orificeSurfaceArea

    def saveIntermediateResult(self, name, surface, visible=False, color=None):
        if not self.keepIntermediateResults:
            return None
        surfaceCopy = vtk.vtkPolyData()
        surfaceCopy.DeepCopy(surface)
        modelNode = slicer.modules.models.logic().AddModel(surfaceCopy)
        modelNode.SetName(name)
        modelNode.CreateDefaultDisplayNodes()
        modelNode.GetDisplayNode().SetVisibility2D(True)
        modelNode.GetDisplayNode().SetVisibility(visible)
        modelNode.GetDisplayNode().SetEdgeVisibility(True)
        if color is not None:
            modelNode.GetDisplayNode().SetColor(color)
        return modelNode

    def getMedialSurface(self, inputSurfaceModel):

        # Input may be an unstructured grid from FE simulation that we need to convert to surface mesh
        medialSurfaceMesh = inputSurfaceModel.GetPolyData()
        if not medialSurfaceMesh:
            femMesh = inputSurfaceModel.GetMesh()
            extractSurface = vtk.vtkGeometryFilter()
            extractSurface.SetInputData(femMesh)
            extractSurface.Update()
            medialSurfaceMesh = extractSurface.GetOutput()
            # Remove lines (such as chords) that may have been added in FE simulation
            medialSurfaceMesh.SetLines(None)

        # Ensure we have surface normals
        if not medialSurfaceMesh.GetPointData() or not medialSurfaceMesh.GetPointData().GetArray("Normals"):
            normals = vtk.vtkPolyDataNormals()
            normals.SetInputData(medialSurfaceMesh)
            normals.Update()
            medialSurfaceMesh = normals.GetOutput()

        self.saveIntermediateResult("MedialSurface", medialSurfaceMesh)

        return medialSurfaceMesh

    def createThickSurface(self, medialSurfaceMesh, outputThickSurfaceModel, surfaceThickness):

        # Create a thickened mesh
        surfaceMeshCopy = vtk.vtkPolyData()
        surfaceMeshCopy.DeepCopy(medialSurfaceMesh)
        medialSurfaceMesh = surfaceMeshCopy

        medialSurfaceMesh.GetPointData().SetActiveVectors("Normals")
        warpVector = vtk.vtkWarpVector()
        warpVector.SetInputData(medialSurfaceMesh)
        warpVector.SetScaleFactor(surfaceThickness * 0.5)
        warpVector.Update()
        frontSurfaceMesh = warpVector.GetOutput()

        extrude = vtk.vtkLinearExtrusionFilter()
        extrude.SetInputData(frontSurfaceMesh)
        extrude.SetExtrusionTypeToNormalExtrusion()
        extrude.SetScaleFactor(surfaceThickness)

        triangleFilter = vtk.vtkTriangleFilter()
        triangleFilter.SetInputConnection(extrude.GetOutputPort())

        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(triangleFilter.GetOutputPort())
        normals.AutoOrientNormalsOn()
        normals.Update()
        thickSurface = normals.GetOutput()

        if outputThickSurfaceModel:
            if not outputThickSurfaceModel.GetMesh():
                # initial update
                outputThickSurfaceModel.CreateDefaultDisplayNodes()
                outputThickSurfaceModel.GetDisplayNode().SetColor(0, 1, 0)
                outputThickSurfaceModel.GetDisplayNode().SetVisibility2D(True)
                outputThickSurfaceModel.GetDisplayNode().SetVisibility(True)
                outputThickSurfaceModel.GetDisplayNode().SetEdgeVisibility(True)
            outputThickSurfaceModel.SetAndObservePolyData(thickSurface)
        elif self.keepIntermediateResults:
            self.saveIntermediateResult("ThickSurface", thickSurface, True, [0, 1, 0])

        return thickSurface

    def createGradientVolume(self, thickSurface):

        # Export thick surface to labelmap - useful for troubleshooting (labelmap can be browsed in slice views)
        self.log("Create thick surface labelmap")
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        # Resolution of the segmentation can be made finer by uncommenting the next line,
        # but it seems that currently the default resolution (250x250x250 voxels) is sufficient.
        #segmentationNode.GetSegmentation().SetConversionParameter("Oversampling factor", "2")
        thickSurfaceModelNodeTmp = slicer.modules.models.logic().AddModel(thickSurface)
        slicer.modules.segmentations.logic().ImportModelToSegmentationNode(thickSurfaceModelNodeTmp, segmentationNode)
        labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(segmentationNode, labelmapVolumeNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY)
        slicer.mrmlScene.RemoveNode(segmentationNode)
        slicer.mrmlScene.RemoveNode(thickSurfaceModelNodeTmp)

        thresh = vtk.vtkImageThreshold()
        thresh.SetInputData(labelmapVolumeNode.GetImageData())
        thresh.ThresholdByUpper(1)
        thresh.SetInValue(0)
        thresh.SetOutValue(1)
        thresh.Update()

        ijkToRas = vtk.vtkMatrix4x4()
        labelmapVolumeNode.GetIJKToRASMatrix(ijkToRas)

        distanceMap = vtk.vtkImageEuclideanDistance()
        distanceMap.SetInputData(thresh.GetOutput())
        distanceMap.Update()
        if self.keepIntermediateResults:
            distancemapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Distance map")
            distancemapVolumeNode.SetAndObserveImageData(distanceMap.GetOutput())
            distancemapVolumeNode.SetIJKToRASMatrix(ijkToRas)
            slicer.util.setSliceViewerLayers(labelmapVolumeNode, fit=True)
        else:
            slicer.mrmlScene.RemoveNode(labelmapVolumeNode)

        gradient = vtk.vtkImageGradient()
        gradient.SetDimensionality(3)
        gradient.SetInputConnection(distanceMap.GetOutputPort())

        # Normalize the gradient field so that only the direction is kept (it makes it easier to scale step size)
        normalize = vtk.vtkImageNormalize()
        normalize.SetInputConnection(gradient.GetOutputPort())
        normalize.Update()

        gradientVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        gradientVolumeNode.SetAndObserveImageData(normalize.GetOutput())
        gradientVolumeNode.SetIJKToRASMatrix(ijkToRas)

        return gradientVolumeNode

    def createInitialShrinkWrapSurface(self, inputBoundaryCurve):
        areaMeasurement = inputBoundaryCurve.GetMeasurement("area")
        wasAreaMeasurementEnabled = areaMeasurement.GetEnabled()
        areaMeasurement.SetEnabled(True)
        initialShrinkWrapSurface = vtk.vtkPolyData()
        initialShrinkWrapSurface.DeepCopy(areaMeasurement.GetMeshValue())
        areaMeasurement.SetEnabled(wasAreaMeasurementEnabled)
        self.saveIntermediateResult("ShrinkWrapSurface-Initial", initialShrinkWrapSurface, color=[0,0,1])
        return initialShrinkWrapSurface

    def remeshPolydata(self, surface, subdivide=0, clusters=10000):
        import pyacvd
        import pyvista as pv
        inputMesh = pv.wrap(surface)
        clus = pyacvd.Clustering(inputMesh)
        if subdivide > 1:
            clus.subdivide(subdivide)
        clus.cluster(clusters)
        remesh = clus.create_mesh()
        return remesh

    def shrinkWrap(self, shrunkSurface, surface, shrinkwrapIterations, gradientVolumeNode):

        # Step size larger and the mesh is less smooth until the last few iterations.
        # numberOfCooldownIterations determines how many iterations are used for final
        # convergence to refine and smooth the mesh.
        numberOfCooldownIterations = 3

        for iterationIndex in range(shrinkwrapIterations):
            self.log(f"Shrink-wrapping iteration {iterationIndex+1} / {shrinkwrapIterations}")

            import time
            startTime = time.time()

            # shrink
            if shrunkSurface.GetNumberOfPoints()<=1 or surface.GetNumberOfPoints()<=1:
                # we must not feed empty polydata into vtkSmoothPolyDataFilter because it would crash the application
                raise ValueError("Mesh has become empty during shrink-wrap iterations")
            smoothFilter = vtk.vtkSmoothPolyDataFilter()
            smoothFilter.SetNumberOfIterations(40)  # default: 20
            relax = 0.05 if iterationIndex < shrinkwrapIterations - numberOfCooldownIterations else 0.01
            smoothFilter.SetRelaxationFactor(relax)  # default: 0.01
            smoothFilter.SetInputData(0, shrunkSurface)
            #smoothFilter.SetInputData(1, surface)  # constrain smoothed points to the input surface
            smoothFilter.Update()
            shrunkSurface = vtk.vtkPolyData()
            shrunkSurface.DeepCopy(smoothFilter.GetOutput())
            self.saveIntermediateResult(f"Shrunk {iterationIndex}", shrunkSurface)

            # remesh
            clusters = 10000 if iterationIndex < shrinkwrapIterations - numberOfCooldownIterations else 20000
            remeshedSurface = self.remeshPolydata(shrunkSurface, subdivide=2, clusters=clusters)
            shrunkSurface = vtk.vtkPolyData()
            shrunkSurface.DeepCopy(remeshedSurface)
            self.saveIntermediateResult(f"Remeshed {iterationIndex}", shrunkSurface)

            if iterationIndex < shrinkwrapIterations - 1:

                # Transform the model into the volume's IJK space
                modelTransformerRasToIjk = vtk.vtkTransformFilter()
                transformRasToIjk = vtk.vtkTransform()
                ijkToRas = vtk.vtkMatrix4x4()
                gradientVolumeNode.GetIJKToRASMatrix(ijkToRas)
                ijkToRas.Invert()
                transformRasToIjk.SetMatrix(ijkToRas)
                modelTransformerRasToIjk.SetTransform(transformRasToIjk)
                modelTransformerRasToIjk.SetInputData(shrunkSurface)

                probe = vtk.vtkProbeFilter()
                probe.SetSourceData(gradientVolumeNode.GetImageData())
                probe.SetInputConnection(modelTransformerRasToIjk.GetOutputPort())

                # Transform the model back into RAS space
                modelTransformerIjkToRas = vtk.vtkTransformFilter()
                modelTransformerIjkToRas.SetTransform(transformRasToIjk.GetInverse())
                modelTransformerIjkToRas.SetInputConnection(probe.GetOutputPort())
                modelTransformerIjkToRas.Update()

                shrunkSurface = modelTransformerIjkToRas.GetOutput()

                shrunkSurface.GetPointData().SetActiveVectors("ImageScalarsGradient")
                warpVector = vtk.vtkWarpVector()
                warpVector.SetInputData(shrunkSurface)
                stepSize = 0.5 if iterationIndex < shrinkwrapIterations - numberOfCooldownIterations else 0.1
                warpVector.SetScaleFactor(-stepSize)
                warpVector.Update()
                shrunkSurface = vtk.vtkPolyData()
                shrunkSurface.DeepCopy(warpVector.GetOutput())

                self.saveIntermediateResult(f"Offset {iterationIndex}", shrunkSurface)

            stopTime = time.time()
            logging.info(f'Shrink-wrapping iteration {iterationIndex+1} / {shrinkwrapIterations} completed in {stopTime-startTime:.2f} seconds')

        shrinkWrapSurfaceNode = self.saveIntermediateResult("ShrinkWrapSurface-final", shrunkSurface)
        return shrunkSurface

    def createOrificeSurface(self, surfaceMesh, shrunkSurface, surfaceThickness, distanceMarginPercent):
        self.log("Compute distance map")

        import time
        startTime = time.time()
        distance = vtk.vtkDistancePolyDataFilter()
        distance.SetInputData(0, shrunkSurface)
        distance.SetInputData(1, surfaceMesh)
        distance.SignedDistanceOff ()
        distance.Update()
        stopTime = time.time()
        logging.info(f'Mesh distance computation completed in {stopTime-startTime:.2f} seconds')

        surfaceWithDistance = distance.GetOutput()

        orificeSurfaceNode = self.saveIntermediateResult("ShrinkWrapSurface-distance", surfaceWithDistance, False)

        self.log("Threshold orifice surface")
        threshold = vtk.vtkThreshold()
        threshold.SetLowerThreshold(surfaceThickness * (1.0 + distanceMarginPercent / 100.0) / 2.0)  # margin is added to remove areas added just because of noise
        threshold.SetInputData(surfaceWithDistance)
        threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS, "Distance")
        threshold.Update()
        extractSurface = vtk.vtkDataSetSurfaceFilter()
        extractSurface.SetInputData(threshold.GetOutput())
        extractSurface.Update()
        orificeSurface = extractSurface.GetOutput()

        self.saveIntermediateResult("PotentialOrificeSurface", orificeSurface, True, [0, 0, 1])

        return orificeSurface

    @staticmethod
    def surfaceArea(surface):
        properties = vtk.vtkMassProperties()
        properties.SetInputData(surface)
        properties.Update()
        return properties.GetSurfaceArea()

    def computeStreamLineLengths(self, orificeSurface, thickSurface, streamLineLength, outputStreamLinesModel):
        """Compute longest length of a streamline that traverses through the orifice"""
        self.log("Compute streamlines")

        outputOrificeSurface = orificeSurface
        import time
        startTime = time.time()

        import math
        import numpy as np
        import vtk
        import vtk.util.numpy_support

        #locator = vtk.vtkStaticCellLocator()
        locator = vtk.vtkModifiedBSPTree()
        locator.SetDataSet(thickSurface)

        # Ensure we have surface normals
        if not orificeSurface.GetPointData() or not orificeSurface.GetPointData().GetArray("Normals"):
            normals = vtk.vtkPolyDataNormals()
            normals.SplittingOff()  # make sure the number of points are preserved
            normals.SetInputData(orificeSurface)
            normals.Update()
            orificeSurface = normals.GetOutput()

        # Get orifice point positions and normals as numpy arrays
        orificePoints = vtk.util.numpy_support.vtk_to_numpy(orificeSurface.GetPoints().GetData())
        orificePointNormals = vtk.util.numpy_support.vtk_to_numpy(orificeSurface.GetPointData().GetArray("Normals"))

        # Add result array
        freeDistanceArray = vtk.vtkFloatArray()
        freeDistanceArray.SetName("StreamLineLength")
        freeDistanceArray.SetNumberOfValues(orificeSurface.GetNumberOfPoints())

        # Generate spherical distribution
        # The distribution is not uniform, sampling is more dense near the normal direction, but that is desirable,
        # as we expect the piercing streamline to be approximately in the normal direction.
        angularResolution = 20
        # coordinates in "Orifice" coordinate system: origin is the orifice point, z axis is the surface normal
        # (homogeneous coordinates, so that we can easily transform them)
        lineEndpoints_Orifice = np.zeros([4, angularResolution * angularResolution + 1])
        lineEndpoints_Orifice[:, 0] = [0.0, 0.0, streamLineLength, 1.0]
        numberOfLineEndPoints = 1
        for phiDeg in np.arange(4.0, 24.0, 20.0/angularResolution):
            for thetaDeg in np.arange(0.0, 360.0, 360.0/angularResolution):
                theta = thetaDeg / 180.0 * math.pi
                phi = phiDeg / 180.0 * math.pi
                if phi == 0:
                    phi = 50.0/2.0/angularResolution
                x = streamLineLength * math.sin(phi) * math.cos(theta)
                y = streamLineLength * math.sin(phi) * math.sin(theta)
                z = streamLineLength * math.cos(phi)
                lineEndpoints_Orifice[:, numberOfLineEndPoints] = [x, y, z, 1.0]
                numberOfLineEndPoints += 1

        # # Visualize endpoints
        # markups = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
        # markups.CreateDefaultDisplayNodes()
        # markups.GetDisplayNode().SetPointLabelsVisibility(False)
        # slicer.util.updateMarkupsControlPointsFromArray(markups, lineEndpoints_Orifice[:3,:].T)

        # will be used for IntersectWithLine
        intersectionTolerance = 0.1
        intersectionT = vtk.mutable(0)
        intersectionX = [0.0, 0.0, 0.0]
        intersectionPcoords = [0.0, 0.0, 0.0]
        intersectionSubId = vtk.mutable(0)

        createStreamLinesModel = (outputStreamLinesModel != None) or self.saveIntermediateResult
        if createStreamLinesModel:
            longestStreamLinesPoints = vtk.vtkPoints()
            longestStreamLinesLines = vtk.vtkCellArray()

        reportingPeriod = int(orificeSurface.GetNumberOfPoints() / 20 + 0.5)  # report at 5% increments
        for pointIndex in range(orificeSurface.GetNumberOfPoints()):
            if pointIndex % reportingPeriod == 0:
                self.log(f"Compute streamlines {int(100 * pointIndex / orificeSurface.GetNumberOfPoints() + 0.5)}%")
            orificePoint = orificePoints[pointIndex]
            orificeNormal = orificePointNormals[pointIndex]
            # Transform line endpoints from Orifice coordinate system to world coordinate system
            p1 = orificePoint
            zAxis = orificeNormal / np.linalg.norm(orificeNormal)
            xAxis = np.array([0,0,1])
            yAxis = np.cross(zAxis, xAxis)
            if np.linalg.norm(yAxis) < 0.1:
                xAxis = np.array([0,1,0])
                yAxis = np.cross(zAxis, xAxis)
            xAxis = np.cross(yAxis, zAxis)
            xAxis /= np.linalg.norm(xAxis)
            yAxis /= np.linalg.norm(yAxis)

            def getLongestFreeDistance(xaxis, yaxis, zaxis):
                longestPathEndPoint = None
                orificeToWorld = np.array([
                    [xaxis[0], yaxis[0], zaxis[0], 0.0],
                    [xaxis[1], yaxis[1], zaxis[1], 0.0],
                    [xaxis[2], yaxis[2], zaxis[2], 0.0],
                    [0.0,      0.0,      0.0,      1.0]])
                lineEndpoints = np.dot(orificeToWorld, lineEndpoints_Orifice)
                longestFreeDistance = 0.0
                for lineEndPoint in lineEndpoints.T:  # iterate through the columns of lineEndpoints
                    p2 = p1 + lineEndPoint[:3]
                    intersected = locator.IntersectWithLine(p1, p2, intersectionTolerance, intersectionT, intersectionX, intersectionPcoords, intersectionSubId)
                    if intersected:
                        freeDistance = np.linalg.norm(p1-intersectionX)
                        if freeDistance > longestFreeDistance:
                            longestFreeDistance = freeDistance
                            longestPathEndPoint = p2.copy()
                    else:
                        longestFreeDistance = streamLineLength
                        longestPathEndPoint = p2.copy()
                    if longestFreeDistance >= streamLineLength:
                        break
                return longestFreeDistance, longestPathEndPoint

            longestFreeDistance1, longestPathEndPoint1 = getLongestFreeDistance(xAxis, yAxis, zAxis)
            longestFreeDistance2, longestPathEndPoint2 = getLongestFreeDistance(yAxis, xAxis, -zAxis)
            longestFreeDistance = min(longestFreeDistance1, longestFreeDistance2)
            if self.saveIntermediateResult and longestFreeDistance >= streamLineLength:
                numberOfPoints = longestStreamLinesPoints.GetNumberOfPoints()
                longestStreamLinesLines.InsertNextCell(3)
                longestStreamLinesLines.InsertCellPoint(numberOfPoints)
                longestStreamLinesLines.InsertCellPoint(numberOfPoints + 1)
                longestStreamLinesLines.InsertCellPoint(numberOfPoints + 2)
                longestStreamLinesPoints.InsertNextPoint(longestPathEndPoint1)
                longestStreamLinesPoints.InsertNextPoint(p1)
                longestStreamLinesPoints.InsertNextPoint(longestPathEndPoint2)

            freeDistanceArray.SetValue(pointIndex, longestFreeDistance)

        if  createStreamLinesModel:
            longestStreamLinesPoly = vtk.vtkPolyData()
            longestStreamLinesPoly.SetPoints(longestStreamLinesPoints)
            longestStreamLinesPoly.SetLines(longestStreamLinesLines)
            if outputStreamLinesModel:
                if not outputStreamLinesModel.GetMesh():
                    # initial update
                    outputStreamLinesModel.CreateDefaultDisplayNodes()
                    outputStreamLinesModel.GetDisplayNode().SetOpacity(0.5)
                    outputStreamLinesModel.GetDisplayNode().SetColor(1, 0.3, 0.3)
                    outputStreamLinesModel.GetDisplayNode().SetVisibility2D(True)
                    outputStreamLinesModel.GetDisplayNode().SetVisibility(True)
                    outputStreamLinesModel.GetDisplayNode().SetEdgeVisibility(True)
                outputStreamLinesModel.SetAndObservePolyData(longestStreamLinesPoly)
            elif self.keepIntermediateResults:
                self.saveIntermediateResult("StreamLines", longestStreamLinesPoly, True, [0, 1, 1])

        outputOrificeSurface.GetPointData().AddArray(freeDistanceArray)
        self.saveIntermediateResult("OrificeSurfaceWithStreamLineLength", outputOrificeSurface, True, [0, 0, 1])

        stopTime = time.time()
        logging.info(f'Streamlines computation completed in {stopTime - startTime:.2f} seconds')

    def splitOrificeSurface(self, orificeSurface, minimumStreamLineLength, distanceFromStreamLine, minimumSurfaceArea):
        """Return list of [position, surfaceArea, surfaceMesh] tuples"""
        self.log("Split orifice surface to connected components")
        import numpy as np
        import vtk
        import vtk.util.numpy_support

        streamLineLengths = vtk.util.numpy_support.vtk_to_numpy(orificeSurface.GetPointData().GetArray("StreamLineLength"))
        piercingPointIndices = np.where(streamLineLengths > minimumStreamLineLength * 0.99)[0]
        if len(piercingPointIndices) == 0:
            return []

        distanceArrayName = "DistanceFromStreamLines"
        distanceFromStreamLines = slicer.vtkFastMarchingGeodesicDistance()
        distanceFromStreamLines.SetFieldDataName(distanceArrayName)
        distanceFromStreamLines.SetDistanceStopCriterion(distanceFromStreamLine)
        distanceFromStreamLines.SetInputData(orificeSurface)
        seeds = vtk.vtkIdList()
        for piercingPointIndex in piercingPointIndices:
            seeds.InsertNextId(piercingPointIndex)
        distanceFromStreamLines.SetSeeds(seeds)
        distanceFromStreamLines.Update()

        # Cut off parts that are too far from piercing points
        threshold = vtk.vtkThreshold()
        threshold.SetInputData(distanceFromStreamLines.GetOutput())
        threshold.SetLowerThreshold(-1e-5)
        threshold.SetUpperThreshold(distanceFromStreamLine)
        threshold.SetThresholdFunction(vtk.vtkThreshold.THRESHOLD_BETWEEN)
        threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, distanceArrayName)
        threshold.Update()
        extractSurface = vtk.vtkDataSetSurfaceFilter()
        extractSurface.SetInputData(threshold.GetOutput())
        extractSurface.Update()

        connect = vtk.vtkPolyDataConnectivityFilter()
        connect.SetInputData(extractSurface.GetOutput())
        connect.SetExtractionModeToAllRegions()
        connect.Update()

        numberOfRegions = connect.GetNumberOfExtractedRegions()
        connect.SetExtractionModeToSpecifiedRegions()
        connect.Update()

        regions = []  # list of [position, area, polydata]
        for regionIndex in range(numberOfRegions):
            connect.InitializeSpecifiedRegionList()
            connect.AddSpecifiedRegion(regionIndex)
            connect.Update()
            component = connect.GetOutput()

            surfaceArea = OrificeAreaLogic.surfaceArea(component)
            if surfaceArea < minimumSurfaceArea:
                # skip almost-zero area regions
                continue

            # Remove orphan points
            cleaner = vtk.vtkCleanPolyData()
            cleaner.SetInputData(component)
            cleaner.Update()
            regionSurface = cleaner.GetOutput()

            # Get center of gravity of points
            pointData = regionSurface.GetPoints().GetData()
            points = vtk.util.numpy_support.vtk_to_numpy(pointData)
            position = points.mean(0)

            pointsLocator = vtk.vtkPointLocator() # could try using vtk.vtkStaticPointLocator() if need to optimize
            pointsLocator.SetDataSet(component)
            pointsLocator.BuildLocator()
            closestPointId = pointsLocator.FindClosestPoint(position)
            position = component.GetPoint(closestPointId)

            regions.append([position, surfaceArea, regionSurface])

        regions = sorted(regions, key=lambda x: x[1], reverse=True)

        return regions


#
# OrificeAreaTest
#

class OrificeAreaTest(ScriptedLoadableModuleTest):
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
        self.test_OrificeArea1()

    def test_OrificeArea1(self):
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
        inputVolume = SampleData.downloadSample('OrificeArea1')
        self.delayDisplay('Loaded test data set')

        inputScalarRange = inputVolume.GetImageData().GetScalarRange()
        self.assertEqual(inputScalarRange[0], 0)
        self.assertEqual(inputScalarRange[1], 695)

        outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        threshold = 100

        # Test the module logic

        logic = OrificeAreaLogic()

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
