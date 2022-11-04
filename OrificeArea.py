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

See more information in <a href="https://github.com/SlicerHeart/SlicerHeart#orifice-area">module documentation</a>.
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
        self.ui.outputOrificePointsSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.surfaceThicknessSliderWidget.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
        self.ui.distanceMarginPercentSliderWidget.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
        self.ui.shrinkWrapIterationsSliderWidget.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
        self.ui.keepIntermediateResultsCheckBox.connect("toggled(bool)", self.updateParameterNodeFromGUI)

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
        if not self._parameterNode.GetNodeReference("InputSurfaceModel"):
            firstNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLModelNode")
            if firstNode:
                self._parameterNode.SetNodeReferenceID("InputSurfaceModel", firstNode.GetID())
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
        self.ui.outputOrificePointsSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputOrificePoints"))
        self.ui.surfaceThicknessSliderWidget.value = float(self._parameterNode.GetParameter("SurfaceThickness"))
        self.ui.distanceMarginPercentSliderWidget.value = float(self._parameterNode.GetParameter("DistanceMarginPercent"))
        self.ui.shrinkWrapIterationsSliderWidget.value = int(float(self._parameterNode.GetParameter("ShrinkWrapIterations")))
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
        self._parameterNode.SetNodeReferenceID("OutputOrificePoints", self.ui.outputOrificePointsSelector.currentNodeID)
        self._parameterNode.SetParameter("SurfaceThickness", str(self.ui.surfaceThicknessSliderWidget.value))
        self._parameterNode.SetParameter("DistanceMarginPercent", str(self.ui.distanceMarginPercentSliderWidget.value))
        self._parameterNode.SetParameter("ShrinkWrapIterations", str(self.ui.shrinkWrapIterationsSliderWidget.value))
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
                               self.ui.outputThickSurfaceModelSelector.currentNode(), self.ui.outputOrificeModelSelector.currentNode(), self.ui.outputOrificePointsSelector.currentNode(),
                               self.ui.surfaceThicknessSliderWidget.value, self.ui.distanceMarginPercentSliderWidget.value, int(self.ui.shrinkWrapIterationsSliderWidget.value))
            self.ui.orificeAreaSpinBox.value = orificeArea


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
        if not parameterNode.GetParameter("DistanceMarginPercent"):
            parameterNode.SetParameter("DistanceMarginPercent", "40")
        if not parameterNode.GetParameter("ShrinkWrapIterations"):
            parameterNode.SetParameter("ShrinkWrapIterations", "20")
        if not parameterNode.GetParameter("KeepIntermediateResults"):
            parameterNode.SetParameter("KeepIntermediateResults", "false")

    def process(self, inputSurfaceModel, inputBoundaryCurve,
                               outputThickSurfaceModel, outputOrificeModel, outputOrificePoints,
                               surfaceThickness, distanceMarginPercent, shrinkWrapIterations, minimumArea=1.0):
        """
        Run the processing algorithm.
        Can be used without GUI widget.
        :return: total orifice area
        """

        if not inputSurfaceModel or not inputBoundaryCurve:
            raise ValueError("Input or output volume is invalid")

        import time
        startTime = time.time()
        self.log('Processing started')

        # It is easier to shrink-wrap the medial surface, as it has less narrow valleys
        medialSurfaceMesh = self.getMedialSurface(inputSurfaceModel)
        gradientVolumeNode = self.createGradientVolume(medialSurfaceMesh, outputThickSurfaceModel, surfaceThickness)
        initialShrinkWrapSurface = self.createInitialShrinkWrapSurface(inputBoundaryCurve)
        shrunkSurface = self.shrinkWrap(initialShrinkWrapSurface, medialSurfaceMesh, shrinkWrapIterations, gradientVolumeNode)
        # Slicer crashes when comes across this node, so always delete it
        slicer.mrmlScene.RemoveNode(gradientVolumeNode)

        self.log("Get orifice surface")
        orificeSurface = self.createOrificeSurface(medialSurfaceMesh, shrunkSurface, surfaceThickness, outputOrificeModel, distanceMarginPercent)

        self.log("Split orifice surface")
        positionsAreas = self.splitOrificeSurface(orificeSurface, minimumArea)
        orificeSurfaceArea = sum([positionArea[1] for positionArea in positionsAreas])
        if outputOrificePoints:
            outputOrificePoints.RemoveAllControlPoints()
            outputOrificePoints.GetDisplayNode().SetOccludedVisibility(True)  # make sure all points are visible, even if occludedin current view
            for position, surfaceArea in positionsAreas:
                outputOrificePoints.AddControlPoint(position, f"Or{outputOrificePoints.GetNumberOfControlPoints()+1}: area={surfaceArea/100.0:.2f}cm2")

        stopTime = time.time()
        self.log(f'Processing completed in {stopTime-startTime:.2f} seconds')

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

    def createGradientVolume(self, medialSurfaceMesh, outputThickSurfaceModel, surfaceThickness):

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
            outputThickSurfaceModel

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
        slicer.util.setSliceViewerLayers(labelmapVolumeNode, fit=True)

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
        areaMeasurement.SetEnabled(True)
        initialShrinkWrapSurface = areaMeasurement.GetMeshValue()
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

            import time
            startTime = time.time()

            # shrink
            self.log(f"Shrinking {iterationIndex+1} / {shrinkwrapIterations}")
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
            self.log(f"Remeshing {iterationIndex+1} / {shrinkwrapIterations}")
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
            self.log(f'Shrinkwrap iteration {iterationIndex+1} / {shrinkwrapIterations} completed in {stopTime-startTime:.2f} seconds')

        shrinkWrapSurfaceNode = self.saveIntermediateResult("ShrinkWrapSurface-final", shrunkSurface)
        return shrunkSurface


    def createOrificeSurface(self, surfaceMesh, shrunkSurface, surfaceThickness, outputOrificeModel, distanceMarginPercent):
        self.log("Compute distance map")

        import time
        startTime = time.time()
        distance = vtk.vtkDistancePolyDataFilter()
        distance.SetInputData(0, shrunkSurface)
        distance.SetInputData(1, surfaceMesh)
        distance.SignedDistanceOff ()
        distance.Update()
        stopTime = time.time()
        self.log(f'Mesh distance computation completed in {stopTime-startTime:.2f} seconds')

        surfaceWithDistance = distance.GetOutput()

        orificeSurfaceNode = self.saveIntermediateResult("ShrinkWrapSurface-distance", surfaceWithDistance, False)

        self.log("Threshold orifice surface")
        threshold = vtk.vtkThreshold()
        threshold.SetLowerThreshold(surfaceThickness * (1.0 + distanceMarginPercent / 100.0) / 2.0)  # margin is added to remove areas added just because of noise
        threshold.SetInputData(surfaceWithDistance)
        threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS, "Distance")
        threshold.Update()
        exractSurface = vtk.vtkDataSetSurfaceFilter()
        exractSurface.SetInputData(threshold.GetOutput())
        exractSurface.Update()
        orificeSurface = exractSurface.GetOutput()

        if outputOrificeModel:
            if not outputOrificeModel.GetMesh():
                # initial update
                outputOrificeModel.CreateDefaultDisplayNodes()
                outputOrificeModel.GetDisplayNode().SetColor(0, 0, 1)
                outputOrificeModel.GetDisplayNode().SetEdgeVisibility(True)
                outputOrificeModel.GetDisplayNode().SetVisibility2D(True)
                outputOrificeModel.GetDisplayNode().SetVisibility(True)
            outputOrificeModel.SetAndObservePolyData(orificeSurface)
        elif self.keepIntermediateResults:
            self.saveIntermediateResult("OrificeSurface", orificeSurface, True, [0, 0, 1])

        return orificeSurface


    @staticmethod
    def surfaceArea(surface):
        properties = vtk.vtkMassProperties()
        properties.SetInputData(surface)
        properties.Update()
        return properties.GetSurfaceArea()


    def splitOrificeSurface(self, orificeSurface, minimumArea):
        self.log("Split orifice surface to connected components")
        import vtk
        connect = vtk.vtkPolyDataConnectivityFilter()
        connect.SetInputData(orificeSurface)
        connect.SetExtractionModeToAllRegions()
        connect.Update()

        numberOfRegions = connect.GetNumberOfExtractedRegions()
        connect.SetExtractionModeToSpecifiedRegions()
        connect.Update()

        positionsAreas = []
        import vtk.util.numpy_support
        for regionIndex in range(numberOfRegions):
            connect.InitializeSpecifiedRegionList()
            connect.AddSpecifiedRegion(regionIndex)
            connect.Update()
            component = connect.GetOutput()

            surfaceArea = OrificeAreaLogic.surfaceArea(component)
            if surfaceArea < minimumArea:
                continue

            # Remove orphan points
            cleaner = vtk.vtkCleanPolyData()
            cleaner.SetInputData(component)
            cleaner.Update()
            # Get center of gravity of points
            pointData = cleaner.GetOutput().GetPoints().GetData()
            points = vtk.util.numpy_support.vtk_to_numpy(pointData)
            position = points.mean(0)

            pointsLocator = vtk.vtkPointLocator() # could try using vtk.vtkStaticPointLocator() if need to optimize
            pointsLocator.SetDataSet(component)
            pointsLocator.BuildLocator()
            closestPointId = pointsLocator.FindClosestPoint(position)
            position = component.GetPoint(closestPointId)

            positionsAreas.append([position, surfaceArea])

        positionsAreas = sorted(positionsAreas, key=lambda x: x[1], reverse=True)

        return positionsAreas
            


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
