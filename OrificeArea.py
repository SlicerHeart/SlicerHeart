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
Compute area of a hole in a surface mesh.
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
        self.ui.outputOrificeModelSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.outputOrificePointsSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.surfaceThicknessSliderWidget.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
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
        self.ui.outputOrificeModelSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputOrificeModel"))
        self.ui.outputOrificePointsSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputOrificePoints"))
        self.ui.surfaceThicknessSliderWidget.value = float(self._parameterNode.GetParameter("SurfaceThickness"))
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
        self._parameterNode.SetNodeReferenceID("OutputOrificeModel", self.ui.outputOrificeModelSelector.currentNodeID)
        self._parameterNode.SetNodeReferenceID("OutputOrificePoints", self.ui.outputOrificePointsSelector.currentNodeID)
        self._parameterNode.SetParameter("SurfaceThickness", str(self.ui.surfaceThicknessSliderWidget.value))
        self._parameterNode.SetParameter("ShrinkWrapIterations", str(self.ui.shrinkWrapIterationsSliderWidget.value))
        self._parameterNode.SetParameter("KeepIntermediateResults", "true" if self.ui.keepIntermediateResultsCheckBox.checked else "false")

        self._parameterNode.EndModify(wasModified)

    def onApplyButton(self):
        """
        Run processing when user clicks "Apply" button.
        """
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):

            # Compute output
            self.logic.keepIntermediateResults = self.ui.keepIntermediateResultsCheckBox.checked
            orificeArea = self.logic.process(self.ui.inputSurfaceModelSelector.currentNode(), self.ui.inputBoundaryCurveSelector.currentNode(),
                               self.ui.outputOrificeModelSelector.currentNode(), self.ui.outputOrificePointsSelector.currentNode(),
                               self.ui.surfaceThicknessSliderWidget.value, int(self.ui.shrinkWrapIterationsSliderWidget.value))
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

    def setDefaultParameters(self, parameterNode):
        """
        Initialize parameter node with default settings.
        """
        if not parameterNode.GetParameter("SurfaceThickness"):
            parameterNode.SetParameter("SurfaceThickness", "0.4")
        if not parameterNode.GetParameter("ShrinkWrapIterations"):
            parameterNode.SetParameter("ShrinkWrapIterations", "8")
        if not parameterNode.GetParameter("KeepIntermediateResults"):
            parameterNode.SetParameter("KeepIntermediateResults", "false")

    def process(self, inputSurfaceModel, inputBoundaryCurve,
                               outputOrificeModel, outputOrificePoints,
                               surfaceThickness, shrinkWrapIterations):
        """
        Run the processing algorithm.
        Can be used without GUI widget.
        :return: total orifice area
        """

        if not inputSurfaceModel or not inputBoundaryCurve:
            raise ValueError("Input or output volume is invalid")

        import time
        startTime = time.time()
        logging.info('Processing started')

        surfaceMesh, thickSurface = self.createThickSurface(inputSurfaceModel, surfaceThickness)
        initialShrinkWrapSurface = self.createInitialShrinkWrapSurface(inputBoundaryCurve)
        shrunkSurface = self.shrinkWrap(initialShrinkWrapSurface, thickSurface, shrinkWrapIterations, maxLen=0.5, maxArea=5.0)
        orificeSurface = self.createOrificeSurface(surfaceMesh, shrunkSurface, surfaceThickness, outputOrificeModel)

        slicer.util.showStatusMessage("Get orifice surface area", 3000)
        slicer.app.processEvents()
        orificeSurfaceArea = OrificeAreaLogic.surfaceArea(orificeSurface)

        if outputOrificePoints:
            self.splitOrificeSurface(orificeSurface, outputOrificePoints)

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
        if color is not None:
            modelNode.GetDisplayNode().SetColor(color)
        return modelNode

    def createThickSurface(self, inputSurfaceModel, surfaceThickness):

        # Input may be an unstructured grid from FE simulation that we need to convert to surface mesh
        surfaceMesh = inputSurfaceModel.GetPolyData()
        if not surfaceMesh:
            femMesh = inputSurfaceModel.GetMesh()
            extractSurface = vtk.vtkGeometryFilter()
            extractSurface.SetInputData(femMesh)
            extractSurface.Update()
            surfaceMesh = extractSurface.GetOutput()
            # Remove lines (such as chords) that may have been added in FE simulation
            surfaceMesh.SetLines(None)

        # Ensure we have surface normals
        if not surfaceMesh.GetPointData() or not surfaceMesh.GetPointData().GetArray("Normals"):
            normals = vtk.vtkPolyDataNormals()
            normals.SetInputData(surfaceMesh)
            normals.Update()
            surfaceMesh = normals.GetOutput()

        self.saveIntermediateResult("MedialSurface", surfaceMesh)

        # Create a thickened mesh

        surfaceMesh.GetPointData().SetActiveVectors("Normals")
        warpVector = vtk.vtkWarpVector()
        warpVector.SetInputData(surfaceMesh)
        warpVector.SetScaleFactor(surfaceThickness * 0.5)
        warpVector.Update()
        shrunkSurface = vtk.vtkPolyData()
        shrunkSurface.DeepCopy(warpVector.GetOutput())

        extrude = vtk.vtkLinearExtrusionFilter()
        extrude.SetInputData(surfaceMesh)
        extrude.SetExtrusionTypeToNormalExtrusion()
        extrude.SetScaleFactor(surfaceThickness)

        triangleFilter = vtk.vtkTriangleFilter()
        triangleFilter.SetInputConnection(extrude.GetOutputPort())

        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(triangleFilter.GetOutputPort())
        normals.AutoOrientNormalsOn()
        normals.Update()
        thickSurface = normals.GetOutput()

        self.saveIntermediateResult("ThickLeafletSurface", thickSurface, color=[0,1,0])

        if self.saveIntermediateResult:
            # Export thick surface to labelmap - useful for troubleshooting (labelmap can be browsed in slice views)
            segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            thickSurfaceModelNodeTmp = slicer.modules.models.logic().AddModel(thickSurface)
            slicer.modules.segmentations.logic().ImportModelToSegmentationNode(thickSurfaceModelNodeTmp, segmentationNode)
            labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(segmentationNode, labelmapVolumeNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY)
            slicer.mrmlScene.RemoveNode(segmentationNode)
            slicer.mrmlScene.RemoveNode(thickSurfaceModelNodeTmp)
            slicer.util.setSliceViewerLayers(labelmapVolumeNode, fit=True)

        return surfaceMesh, thickSurface


    def createInitialShrinkWrapSurface(self, inputBoundaryCurve):
        areaMeasurement = inputBoundaryCurve.GetMeasurement("area")
        areaMeasurement.SetEnabled(True)
        initialShrinkWrapSurface = areaMeasurement.GetMeshValue()
        self.saveIntermediateResult("ShrinkWrapSurface-Initial", initialShrinkWrapSurface, color=[0,0,1])
        return initialShrinkWrapSurface


    def remeshPolydata(self, surface, maxLen, maxArea):
        subdivide = vtk.vtkAdaptiveSubdivisionFilter()
        subdivide.SetMaximumTriangleArea(maxArea)
        subdivide.SetMaximumEdgeLength(maxLen)
        subdivide.SetInputData(surface)
        subdivide.Update()
        return subdivide.GetOutput()


    def shrinkWrap(self, shrunkSurface, surface, shrinkwrapIterations=1, maxLen=2.0, maxArea=5.0, saveIntermediateResult=False):

        for iterationIndex in range(shrinkwrapIterations):

            import time
            startTime = time.time()

            # shrink
            slicer.util.showStatusMessage(f"Shrinking {iterationIndex+1} / {shrinkwrapIterations}", 3000)
            slicer.app.processEvents()
            if shrunkSurface.GetNumberOfPoints()<=1 or surface.GetNumberOfPoints()<=1:
                # we must not feed empty polydata into vtkSmoothPolyDataFilter because it would crash the application
                raise ValueError("Mesh has become empty during shrink-wrap iterations")
            smoothFilter = vtk.vtkSmoothPolyDataFilter()
            smoothFilter.SetNumberOfIterations(20)  # default: 20
            smoothFilter.SetRelaxationFactor(0.04)  # default: 0.01
            smoothFilter.SetInputData(0, shrunkSurface)
            smoothFilter.SetInputData(1, surface)  # constrain smoothed points to the input surface
            smoothFilter.Update()
            shrunkSurface = vtk.vtkPolyData()
            shrunkSurface.DeepCopy(smoothFilter.GetOutput())
            self.saveIntermediateResult(f"Shrunk {iterationIndex}", shrunkSurface)

            cleaner = vtk.vtkCleanPolyData()
            cleaner.SetInputData(smoothFilter.GetOutput())
            cleaner.PointMergingOn()
            cleaner.SetAbsoluteTolerance(maxLen/2.0)
            cleaner.Update()
            shrunkSurface = cleaner.GetOutput()
            
            # remesh
            slicer.util.showStatusMessage(f"Remeshing {iterationIndex+1} / {shrinkwrapIterations}", 3000)
            slicer.app.processEvents()
            remeshedSurface = self.remeshPolydata(shrunkSurface, maxLen, maxArea)
            shrunkSurface = vtk.vtkPolyData()
            shrunkSurface.DeepCopy(remeshedSurface)
            self.saveIntermediateResult(f"Remeshed {iterationIndex}", shrunkSurface)

            stopTime = time.time()
            logging.info(f'Shrinkwrap iteration {iterationIndex+1} / {shrinkwrapIterations} completed in {stopTime-startTime:.2f} seconds')


        shrinkWrapSurfaceNode = self.saveIntermediateResult("ShrinkWrapSurface-final", shrunkSurface)
        if shrinkWrapSurfaceNode:
            shrinkWrapSurfaceNode.GetDisplayNode().SetEdgeVisibility(True)

        return shrunkSurface


    def createOrificeSurface(self, surfaceMesh, shrunkSurface, surfaceThickness, outputOrificeModel):
        slicer.util.showStatusMessage("Compute distance", 3000)
        slicer.app.processEvents()

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

        orificeSurfaceNode = self.saveIntermediateResult("ShrinkWrapSurface-distance", surfaceWithDistance, True)
        if orificeSurfaceNode:
            orificeSurfaceNode.GetDisplayNode().SetEdgeVisibility(True)

        slicer.util.showStatusMessage("Threshold orifice surface", 3000)
        slicer.app.processEvents()
        threshold = vtk.vtkThreshold()
        threshold.SetLowerThreshold(surfaceThickness)
        #threshold.SetUpperThreshold(surfaceThickness)
        threshold.SetInputData(surfaceWithDistance)
        threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "Distance")
        threshold.Update()
        exractSurface = vtk.vtkDataSetSurfaceFilter()
        exractSurface.SetInputData(threshold.GetOutput())
        exractSurface.Update()
        orificeSurface = exractSurface.GetOutput()

        if outputOrificeModel:
            if not outputOrificeModel.GetMesh():
                # initial update
                outputOrificeModel.CreateDefaultDisplayNodes()
                outputOrificeModel.GetDisplayNode().SetVisibility2D(True)
                outputOrificeModel.GetDisplayNode().SetVisibility(True)
                outputOrificeModel.GetDisplayNode().SetColor(0, 0, 1)
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


    def splitOrificeSurface(self, orificeSurface, outputOrificePoints, minimumArea=5.0):
        slicer.util.showStatusMessage("Split orifice surface to connected components", 3000)
        slicer.app.processEvents()
        import vtk
        connect = vtk.vtkPolyDataConnectivityFilter()
        connect.SetInputData(orificeSurface)
        connect.SetExtractionModeToAllRegions()
        connect.Update()

        numberOfRegions = connect.GetNumberOfExtractedRegions()
        connect.SetExtractionModeToSpecifiedRegions()
        connect.Update()

        outputOrificePoints.RemoveAllControlPoints()

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

            outputOrificePoints.AddControlPoint(position, f"O{outputOrificePoints.GetNumberOfControlPoints()+1}: area={surfaceArea/100.0:.2f}cm2")


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
