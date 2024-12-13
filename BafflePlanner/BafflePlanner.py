import os
import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import logging

#
# BafflePlanner
#

class BafflePlanner(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Baffle Planner"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Andras Lasso (PerkLab, Queen's University), Csaba Pinter (Pixel Medical)"]
    self.parent.helpText = """
This module creates a curved baffle surface from a closed curve and surface points. Details are described in paper
<a href="https://www.sciencedirect.com/science/article/pii/S0003497521004574">
Modeling Tool for Rapid Virtual Planning of the Intracardiac Baffle in Double Outlet Right Ventricle</a>.
"""
    self.parent.acknowledgementText = """
This work was supported by a Children's Hospital of Philadelphia (CHOP) Cardiac Center Innovation Grant,
a CHOP Cardiac Center Research Grant, a CHOP Frontier Grant, NIH R01 HL153166 and T32GM008562,
and by CANARIE's Research Software Program.
"""

#
# BafflePlannerWidget
#

class BafflePlannerWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    ScriptedLoadableModuleWidget.__init__(self, parent)
    VTKObservationMixin.__init__(self)  # needed for parameter node observation
    self.logic = None
    self._parameterNode = None
    self._inputCurveNode = None
    self._updatingParameterNodeFromGUI = False

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Load widget from .ui file (created by Qt Designer)
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/BafflePlanner.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Hide the clipping section for now - it is not implemented yet, only the GUI has been designed
    self.ui.clipModelCollapsibleButton.visible = False
    # Hide the NURBS section for now - it is not fully functional yet
    self.ui.nurbsCollapsibleButton.visible = False

    # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
    # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
    # "setMRMLScene(vtkMRMLScene*)" slot.
    uiWidget.setMRMLScene(slicer.mrmlScene)

    # Create logic class. Logic implements all computations that should be possible to run
    # in batch mode, without a graphical user interface.
    self.logic = BafflePlannerLogic()

    # Connections

    # These connections ensure that we update parameter node when scene is closed
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    self.ui.inputCurveSelector.currentNodeChanged.connect(self.inputCurveNodeSelected)
    self.ui.outputBaffleModelSelector.currentNodeChanged.connect(lambda node: self.logic.setOutputBaffleModelNode(node))
    self.ui.nurbsSurfaceSelector.currentNodeChanged.connect(lambda node: self.logic.setOutputNurbsMarkupsSurfaceNode(node))
    self.ui.flattenedModelSelector.currentNodeChanged.connect(lambda node: self.logic.setOutputFlattenedModelNode(node))
    #self.ui.flattenedBaffleImageFilePathLineEdit.currentPathChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.radiusScalingFactorSlider.valueChanged.connect(lambda value: self.logic.setRadiusScalingFactor(value))
    self.ui.thicknessSliderWidgetPositive.valueChanged.connect(lambda value: self.logic.setSurfaceThicknessPositive(value))
    self.ui.thicknessSliderWidgetNegative.valueChanged.connect(lambda value: self.logic.setSurfaceThicknessNegative(value))

    # Buttons
    self.ui.updateButton.clicked.connect(self.onUpdateButton)
    self.ui.updateButton.checkBoxToggled.connect(self.onUpdateButtonToggled)
    self.ui.nurbsConvertCancelButton.clicked.connect(self.onNurbsConvertCancelButton)
    self.ui.flattenButton.clicked.connect(self.onFlattenButton)
    self.ui.saveFlattenedBaffleButton.clicked.connect(self.onSaveFlattenedBaffleButton)

    # Add vertical spacer
    self.layout.addStretch(1)

    # Make sure parameter node is initialized (needed for module reload)
    self.initializeParameterNode()

  def cleanup(self):
    """
    Called when the application closes and the module widget is destroyed.
    """
    self.removeObservers()
    self.logic = None

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
    self.removeObserver(self._inputCurveNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

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
    if not self.logic:
      # the module was unloaded, ignore initialization request
      return
    self.setParameterNode(self.logic.getParameterNode())
    # Here we could select default input nodes to save a few clicks for the user

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

    inputCurveNode = self.logic.getParameterNode().GetNodeReference('InputCurve')
    if inputCurveNode != self._inputCurveNode:
      if self._inputCurveNode is not None:
        self.removeObserver(self._inputCurveNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
      self._inputCurveNode = inputCurveNode
      if self._inputCurveNode is not None:
        self.addObserver(self._inputCurveNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    # Update node selectors and sliders
    self.ui.inputCurveSelector.setCurrentNode(self.logic.getInputCurveNode())
    self.ui.outputBaffleModelSelector.setCurrentNode(self.logic.getOutputBaffleModelNode())
    self.ui.flattenedModelSelector.setCurrentNode(self.logic.getOutputFlattenedModelNode())
    self.ui.nurbsSurfaceSelector.setCurrentNode(self.logic.getOutputNurbsMarkupNode())
    self.ui.surfacePointsPlaceWidget.setCurrentNode(self.logic.getSurfacePointsNode())
    self.ui.fixedPointsPlaceWidget.setCurrentNode(self.logic.getInputFixedPointsNode())

    # Update buttons states and tooltips
    self.ui.updateButton.enabled = self.ui.inputCurveSelector.currentNode() and self.ui.outputBaffleModelSelector.currentNode()
    self.ui.nurbsConvertCancelButton.enabled = \
      self.ui.inputCurveSelector.currentNode() and self.ui.outputBaffleModelSelector.currentNode() and self.ui.nurbsSurfaceSelector.currentNode()
    self.ui.nurbsConvertCancelButton.text = \
      'Cancel' if not self.ui.nurbsSurfaceSelector.currentNode() or self.ui.nurbsSurfaceSelector.currentNode().GetNumberOfControlPoints() > 0 else 'Convert'
    self.ui.flattenButton.enabled = self.ui.outputBaffleModelSelector.currentNode() and self.ui.flattenedModelSelector.currentNode()
    self.ui.radiusScalingFactorSlider.enabled = self.ui.outputBaffleModelSelector.currentNode() is not None
    self.ui.thicknessSliderWidgetPositive.enabled = self.ui.outputBaffleModelSelector.currentNode() is not None
    self.ui.thicknessSliderWidgetNegative.enabled = self.ui.outputBaffleModelSelector.currentNode() is not None
    self.ui.saveFlattenedBaffleButton.enabled = self.ui.flattenButton.enabled
    #self.ui.saveFlattenedBaffleButton.enabled = self.ui.flattenedModelSelector.currentNode() and self.ui.flattenedBaffleImageFilePathLineEdit.currentPath != ''
    self.ui.updateButton.checkState = qt.Qt.Checked if self.logic.getAutoUpdateEnabled() else qt.Qt.Unchecked

    self.ui.radiusScalingFactorSlider.value = self.logic.getRadiusScalingFactor()
    self.ui.thicknessSliderWidgetPositive.value = self.logic.getSurfaceThicknessPositive()
    self.ui.thicknessSliderWidgetNegative.value = self.logic.getSurfaceThicknessNegative()

    # # All the GUI updates are done
    # self._updatingParameterNodeFromGUI = False

  def inputCurveNodeSelected(self, caller=None, event=None):
    if not self.logic:
      # shutting down
      return
    inputCurveNode = self.ui.inputCurveSelector.currentNode()
    if inputCurveNode == self._inputCurveNode:
      return
    if self._inputCurveNode is not None:
      self.removeObserver(self._inputCurveNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self._inputCurveNode = inputCurveNode
    if self._inputCurveNode is not None:
      self.addObserver(self._inputCurveNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self.logic.setInputCurveNode(inputCurveNode)
    self.updateGUIFromParameterNode()

  def onUpdateButton(self):
    try:
      self.logic.updateOutputBaffleModel()
    except Exception as e:
      import traceback
      traceback.print_exc()
      slicer.util.errorDisplay("Error updating surface: "+str(e))

  def onUpdateButtonToggled(self, toggle):
    self.logic.setAutoUpdateEnabled(toggle)

  def onFlattenProgress(self, text):
    self.ui.flattenButton.text = "Flattening in progress... " + text
    slicer.app.processEvents()

  def onNurbsConvertCancelButton(self):
    if not hasattr(slicer.modules, 'nurbsfitting'):
      slicer.util.messageBox("The NURBS conversion requires the NurbsFitting module in the SlicerHeartPrivate extension. Install SlicerHeartPrivate and restart Slicer.")
      return

  def onFlattenButton(self):
    try:
      self.ui.flattenButton.enabled = False
      self.ui.flattenButton.text = "Flattening in progress..."
      self.logic.flattenOutputBaffleModel(self.onFlattenProgress)
    except Exception as e:
      import traceback
      traceback.print_exc()
      slicer.util.errorDisplay("Error flattening baffle image: "+str(e))
    self.ui.flattenButton.text = "Flatten"
    self.ui.flattenButton.enabled = True

  def onSaveFlattenedBaffleButton(self):
    try:
      filePath = self.ui.flattenedBaffleImageFilePathLineEdit.currentPath
      if filePath[len(filePath)-4:].lower() != ".png":
        filePath += '.png'
        self.ui.flattenedBaffleImageFilePathLineEdit.currentPath = filePath
      self.ui.flattenedBaffleImageFilePathLineEdit.addCurrentPathToHistory()
      self.logic.generatePixmapForPrinting(filePath)
    except Exception as e:
      import traceback
      traceback.print_exc()
      slicer.util.errorDisplay("Error saving flattened baffle image: "+str(e))


#
# BafflePlannerLogic
#

class BafflePlannerLogic(ScriptedLoadableModuleLogic):
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

    self.inputCurveNode = None
    self.inputCurveNodeObservations = []
    self.inputSurfacePointsNode = None
    self.inputSurfacePointsNodeObservations = []

    self.numberOfCurveLandmarkPoints = 80

    self.printThreeDViewNode = None
    self.printThreeDWidget = None
    self.printViewWidth = 1024
    self.printViewHeight = 1024
    self.printXResolutionDpi = 300
    self.printYResolutionDpi = 300
    self.printScale = 2.0 #TODO: Workaround for scaling problem, see https://github.com/SlicerFab/SlicerFab/issues/13
    self.printTransparentBackground = False

    # Create triangulated flat disk that will be warped

    self.surfaceUnitDisk = vtk.vtkDiskSource()
    self.surfaceUnitDisk.SetOuterRadius(1.0)
    self.surfaceUnitDisk.SetInnerRadius(0.0)
    self.surfaceUnitDisk.SetCircumferentialResolution(self.numberOfCurveLandmarkPoints)
    self.surfaceUnitDisk.SetRadialResolution(60)

    self.surfaceTriangulator = vtk.vtkDelaunay2D()
    self.surfaceTriangulator.SetTolerance(0.01) # get rid of the small triangles near the center of the unit disk
    self.surfaceTriangulator.SetInputConnection(self.surfaceUnitDisk.GetOutputPort())

    # Prepare transform object

    # points on the unit disk (circumference and surface)
    self.surfaceTransformSourcePoints = vtk.vtkPoints()

    self.surfaceTransformSourceCurvePoints = vtk.vtkPoints()
    self.surfaceTransformSourceCurvePoints.SetNumberOfPoints(self.numberOfCurveLandmarkPoints)
    import math
    angleIncrement = 2.0 * math.pi / float(self.numberOfCurveLandmarkPoints)
    for pointIndex in range(self.numberOfCurveLandmarkPoints):
      angle = float(pointIndex) * angleIncrement
      self.surfaceTransformSourceCurvePoints.SetPoint(pointIndex, math.cos(angle), math.sin(angle), 0)

    # points on the warped surface (curve points and surface points)
    self.surfaceTransformTargetPoints = vtk.vtkPoints()

    self.surfaceTransform = vtk.vtkThinPlateSplineTransform()
    self.surfaceTransform.SetSourceLandmarks(self.surfaceTransformSourcePoints)
    self.surfaceTransform.SetTargetLandmarks(self.surfaceTransformTargetPoints)

    # Transform polydata

    self.surfaceTransformFilter = vtk.vtkTransformPolyDataFilter()
    self.surfaceTransformFilter.SetTransform(self.surfaceTransform)
    self.surfaceTransformFilter.SetInputConnection(self.surfaceTriangulator.GetOutputPort())

    self.cleanPolyDataFilter = vtk.vtkCleanPolyData()
    self.cleanPolyDataFilter.SetInputConnection(self.surfaceTransformFilter.GetOutputPort())

    #

    self.surfacePolyDataNormalsThin = vtk.vtkPolyDataNormals()
    self.surfacePolyDataNormalsThin.SetInputConnection(self.cleanPolyDataFilter.GetOutputPort())
    # There are a few triangles in the triangulated unit disk with inconsistent
    # orientation. Enabling consistency check fixes them.
    self.surfacePolyDataNormalsThin.ConsistencyOn()  # TODO: check if needed, probably not
    self.surfacePolyDataNormalsThin.SplittingOff()  # this prevents stray normals at the edge  TODO: check

    # Add thickness to warped surface (if needed)

    # self.surfacePolyDataNormals = vtk.vtkPolyDataNormals()
    # self.surfacePolyDataNormals.SetInputConnection(self.cleanPolyDataFilter.GetOutputPort())
    # self.surfacePolyDataNormals.SplittingOff()  # this prevents stray normals at the edge  TODO: check

    self.surfaceOffset = vtk.vtkWarpVector()
    self.surfaceOffset.SetInputConnection(self.surfacePolyDataNormalsThin.GetOutputPort())
    self.surfaceOffset.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, vtk.vtkDataSetAttributes.NORMALS)

    self.surfaceExtrude = vtk.vtkLinearExtrusionFilter()
    self.surfaceExtrude.SetInputConnection(self.surfaceOffset.GetOutputPort())
    self.surfaceExtrude.SetExtrusionTypeToNormalExtrusion()

    self.surfacePolyDataNormalsThick = vtk.vtkPolyDataNormals()
    self.surfacePolyDataNormalsThick.SetInputConnection(self.surfaceExtrude.GetOutputPort())
    self.surfacePolyDataNormalsThick.AutoOrientNormalsOn()

  def __del__(self):
    for observation in self.inputSurfacePointsNodeObservations:
      self.inputSurfacePointsNode.RemoveObserver(observation)
    for observation in self.inputCurveNodeObservations:
      self.inputCurveNode.RemoveObserver(observation)

  def setDefaultParameters(self, parameterNode):
    """
    Initialize parameter node with default settings.
    """
    pass

  def getAutoUpdateEnabled(self):
    if not self.inputCurveNode:
      return False
    return self.inputCurveNode.GetAttribute("AutoUpdate") == "true"

  def setAutoUpdateEnabled(self, enabled):
    if self.inputCurveNode:
      self.inputCurveNode.SetAttribute("AutoUpdate", "true" if enabled else "false")
      self.updatePointPlaceMode()

  def updatePointPlaceMode(self):
    # Do not snap these points to surface in auto-update mode - it would make placement very difficult
    if self.getAutoUpdateEnabled() and self.getOutputBaffleModelNode():
      pointPlaceMode = slicer.vtkMRMLMarkupsDisplayNode.SnapModeUnconstrained
    else:
      pointPlaceMode = slicer.vtkMRMLMarkupsDisplayNode.SnapModeToVisibleSurface
    for pointsNode in (self.getInputCurveNode(), self.getSurfacePointsNode()):
      if pointsNode:
        pointsNode.GetDisplayNode().SetSnapMode(pointPlaceMode)

    self.onInputPointsModified()

  def getSurfacePointsNode(self):
    return self.inputSurfacePointsNode

  def setSurfacePointsNode(self, surfacePointsNode):
    # Remove any old observers
    if self.inputSurfacePointsNode and self.inputSurfacePointsNode != surfacePointsNode:
      for observation in self.inputSurfacePointsNodeObservations:
        self.inputSurfacePointsNode.RemoveObserver(observation)
      self.inputSurfacePointsNodeObservations = []
      self.inputSurfacePointsNode = None

    if self.inputSurfacePointsNode == surfacePointsNode:
      return

    self.inputSurfacePointsNode = surfacePointsNode
    if self.inputSurfacePointsNode:
      self.inputSurfacePointsNodeObservations.append(self.inputSurfacePointsNode.AddObserver(
        slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onInputPointsModified))
      if self.inputCurveNode:
        self.inputCurveNode.SetAndObserveNodeReferenceID('SurfacePoints', self.inputSurfacePointsNode.GetID() if self.inputSurfacePointsNode else None)
      self.onInputCurveParametersModified()
      self.onInputPointsModified()

  def getInputCurveNode(self):
    return self.inputCurveNode

  def setInputCurveNode(self, inputCurveNode):
    # Remove any old observers
    if self.inputCurveNode:
      for observation in self.inputCurveNodeObservations:
        self.inputCurveNode.RemoveObserver(observation)
      self.inputCurveNodeObservations = []
      self.inputCurveNode = None
      self.setSurfacePointsNode(None)

    self.inputCurveNode = inputCurveNode

    if self.inputCurveNode:
      if not self.inputCurveNode.GetAttribute("AutoUpdate"):
        self.inputCurveNode.SetAttribute("AutoUpdate", "true")
      self.inputCurveNodeObservations.append(self.inputCurveNode.AddObserver(
        slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onInputPointsModified))
      self.inputCurveNodeObservations.append(self.inputCurveNode.AddObserver(
        vtk.vtkCommand.ModifiedEvent, self.onInputCurveParametersModified))

      self.onInputCurveParametersModified()

      # For user convenience, we do not ask the user to select a node but create automatically (if not created already)
      surfacePointsNode = self.getSurfacePointsNode()
      if (not surfacePointsNode) and self.getInputCurveNode():
        surfacePointsNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", self.getInputCurveNode().GetName() + " surface points")
        surfacePointsNode.CreateDefaultDisplayNodes()
        surfacePointsNode.GetDisplayNode().SetPointLabelsVisibility(False)
        self.setSurfacePointsNode(surfacePointsNode)

      self.onInputPointsModified()

    self.getParameterNode().SetAndObserveNodeReferenceID('InputCurve', self.inputCurveNode.GetID() if self.inputCurveNode else None)

  def getOutputBaffleModelNode(self):
    if not self.inputCurveNode:
      return None
    return self.inputCurveNode.GetNodeReference('BaffleModel')

  def setOutputBaffleModelNode(self, outputBaffleModelNode):
    if not self.inputCurveNode:
      if outputBaffleModelNode:
        raise ValueError("inputCurveNode must be set before setting output baffle model node")
      return
    if outputBaffleModelNode:
      outputBaffleModelNode.CreateDefaultDisplayNodes()
      outputBaffleModelNode.GetDisplayNode().BackfaceCullingOff()
      outputBaffleModelNode.GetDisplayNode().SetVisibility2D(True)
      outputBaffleModelNode.GetDisplayNode().SetColor(self.inputCurveNode.GetDisplayNode().GetSelectedColor())
    self.inputCurveNode.SetAndObserveNodeReferenceID('BaffleModel', outputBaffleModelNode.GetID() if outputBaffleModelNode else None)
    self.updatePointPlaceMode()
    self.onInputPointsModified()

  def onInputPointsModified(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    if self.getAutoUpdateEnabled():
      self.updateOutputBaffleModel()

  def onInputCurveParametersModified(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    if self.inputCurveNode:
      self.setSurfacePointsNode(self.inputCurveNode.GetNodeReference("SurfacePoints"))
      self.setOutputBaffleModelNode(self.inputCurveNode.GetNodeReference("BaffleModel"))
      self.setOutputFlattenedModelNode(self.inputCurveNode.GetNodeReference("FlattenedModel"))
    else:
      self.setSurfacePointsNode(None)

  def updateOutputBaffleModel(self):
    """
    Create a "soap bubble" surface that fits on the input curve and surface point list
    :param annulusPoints: points to fit the surface to
    :param radiusScalingFactor: size of the surface. Value of 1.0 (default) means the surface edge fits on the points.
     Larger values increase the generated soap bubble outer radius, which may be useful to avoid coincident points
     when using this surface for cutting another surface.
    :return:
    """

    if not self.inputCurveNode or not self.getOutputBaffleModelNode():
      return

    curvePoints = self.inputCurveNode.GetCurvePointsWorld()
    curveLengthMm = self.inputCurveNode.GetCurveLengthWorld()
    numberOfCurvePoints = curvePoints.GetNumberOfPoints() if curvePoints else 0
    success = False
    if curvePoints and numberOfCurvePoints > 1 and curveLengthMm > 0.0:
      # subtract a little bit (0.1 = 10th of a sampling distance) to make sure we don't go over the curve length
      # because we could then get one less sample point
      samplingDistance = curveLengthMm / (self.numberOfCurveLandmarkPoints-0.1)
      success = slicer.vtkMRMLMarkupsCurveNode.ResamplePoints(curvePoints, self.surfaceTransformTargetPoints, samplingDistance, True)
    if not success:
      # clear the surface
      surfacePoly = self.getOutputBaffleModelNode().GetPolyData()
      if surfacePoly:
        surfacePoly.Reset()
      return

    self.surfaceTransformSourcePoints.DeepCopy(self.surfaceTransformSourceCurvePoints)
    self.surfaceTransformFilter.Update() # warp based on contour points only
    contourWarpedSurface = self.surfaceTransformFilter.GetOutput()
    locator = vtk.vtkPointLocator()
    locator.SetDataSet(contourWarpedSurface)
    locator.Update()

    numberOfSurfacePoints = self.inputSurfacePointsNode.GetNumberOfControlPoints() if self.inputSurfacePointsNode else 0
    unitDiskPoints = self.surfaceTriangulator.GetOutput().GetPoints()
    for pointIndex in range(numberOfSurfacePoints):
      pointOnSurface = [0, 0, 0]
      self.inputSurfacePointsNode.GetNthControlPointPositionWorld(pointIndex, pointOnSurface)
      closestPointId = locator.FindClosestPoint(pointOnSurface)
      pointOnUnitDisk = unitDiskPoints.GetPoint(closestPointId)
      self.surfaceTransformSourcePoints.InsertNextPoint(pointOnUnitDisk)
      self.surfaceTransformTargetPoints.InsertNextPoint(pointOnSurface)

    radiusScalingFactor = self.getRadiusScalingFactor()
    self.surfaceUnitDisk.SetOuterRadius(radiusScalingFactor)

    self.surfaceTransformSourcePoints.Modified()
    self.surfaceTransformTargetPoints.Modified()

    # We will copy the computation result into the model node (instead of setting the filter output directly in the model node)
    # to allow having multiple baffles in the same scene.
    if not self.getOutputBaffleModelNode().GetPolyData():
        self.getOutputBaffleModelNode().SetAndObservePolyData(vtk.vtkPolyData())

    thicknessPos = self.getSurfaceThicknessPositive()
    thicknessNeg = self.getSurfaceThicknessNegative()
    if thicknessPos > 0 or thicknessNeg > 0:
      self.surfaceOffset.SetScaleFactor(-thicknessNeg)
      self.surfaceOffset.Update()

      # Copy normals from input
      offsetSurface = self.surfaceOffset.GetOutput()
      offsetSurface.GetPointData().SetNormals(
        self.surfacePolyDataNormalsThin.GetOutput().GetPointData().GetNormals())

      self.surfaceExtrude.SetInputData(offsetSurface)
      self.surfaceExtrude.SetScaleFactor(thicknessNeg+thicknessPos)

      self.surfacePolyDataNormalsThick.Update()
      self.getOutputBaffleModelNode().GetPolyData().DeepCopy(self.surfacePolyDataNormalsThick.GetOutput())

    else:
      self.surfacePolyDataNormalsThin.Update()
      self.getOutputBaffleModelNode().GetPolyData().DeepCopy(self.surfacePolyDataNormalsThin.GetOutput())

  def getInputFixedPointsNode(self):
    if not self.inputCurveNode:
      return None
    return self.inputCurveNode.GetNodeReference('FixedPoints')

  def setInputFixedPointsNode(self, fixedPointsNode):
    if not self.inputCurveNode:
      raise ValueError("inputCurveNode must be set before setting inputFixedPointsNode")
    self.inputCurveNode.SetAndObserveNodeReferenceID('FixedPoints', fixedPointsNode.GetID() if fixedPointsNode else None)

  def getOutputFlattenedFixedPointsNode(self):
    if not self.inputCurveNode:
      return None
    return self.inputCurveNode.GetNodeReference('FlattenedFixedPoints')

  def setOutputFlattenedFixedPointsNode(self, outputFlattenedFixedPointsNode):
    if not self.inputCurveNode:
      raise ValueError("inputCurveNode must be set before setting outputFlattenedFixedPointsNode")
    self.inputCurveNode.SetAndObserveNodeReferenceID('FlattenedFixedPoints', outputFlattenedFixedPointsNode.GetID() if outputFlattenedFixedPointsNode else None)

  def setSurfaceThicknessPositive(self, thickness):
    if not self.inputCurveNode:
      return 0.0
    self.inputCurveNode.SetAttribute("BaffleSurfaceThicknessPositive", str(thickness))

  def getRadiusScalingFactor(self):
    if not self.inputCurveNode:
      return 1.0
    radiusScalingFactorStr = self.inputCurveNode.GetAttribute("RadiusScalingFactor")
    radiusScalingFactor = float(radiusScalingFactorStr) if radiusScalingFactorStr else 1.0
    return radiusScalingFactor

  def setRadiusScalingFactor(self, radiusScalingFactor):
    if not self.inputCurveNode:
      return 1.0
    self.inputCurveNode.SetAttribute("RadiusScalingFactor", str(radiusScalingFactor))

  def getSurfaceThicknessPositive(self):
    if not self.inputCurveNode:
      return 0.0
    thicknessStr = self.inputCurveNode.GetAttribute("BaffleSurfaceThicknessPositive")
    thickness = float(thicknessStr) if thicknessStr else 0.0
    return thickness

  def setSurfaceThicknessNegative(self, thickness):
    if not self.inputCurveNode:
      return 0.0
    self.inputCurveNode.SetAttribute("BaffleSurfaceThicknessNegative", str(thickness))

  def getSurfaceThicknessNegative(self):
    if not self.inputCurveNode:
      return 0.0
    thicknessStr = self.inputCurveNode.GetAttribute("BaffleSurfaceThicknessNegative")
    thickness = float(thicknessStr) if thicknessStr else 0.0
    return thickness

  def setOutputNurbsMarkupsSurfaceNode(self, outputNurbsMarkupsNode):
    baffleModelNode = self.getOutputBaffleModelNode()
    if not self.inputCurveNode or not baffleModelNode:
      if outputNurbsMarkupsNode:
        raise ValueError("input curve node and output baffle model must be set before setting output NURBS markup node")
      return
    if not baffleModelNode.GetPolyData() or baffleModelNode.GetPolyData().GetNumberOfPoints() == 0 and outputNurbsMarkupsNode:
      raise ValueError("Baffle model must be computed before setting output NURBS markup node")

    if outputNurbsMarkupsNode:
      # Setup NURBS markups node
      pass #TODO: Color, other properties...

    self.inputCurveNode.SetAndObserveNodeReferenceID('NurbsMarkupsSurface', outputNurbsMarkupsNode.GetID() if outputNurbsMarkupsNode else None)

  def getOutputNurbsMarkupNode(self):
    if not self.inputCurveNode:
      return None
    return self.inputCurveNode.GetNodeReference('NurbsMarkupsSurface')

  def setOutputFlattenedModelNode(self, outputFlattenedModelNode):
    if not self.inputCurveNode:
      if outputFlattenedModelNode:
        raise ValueError("inputCurveNode must be set before setting output flattened model node")
      return
    if outputFlattenedModelNode:
      outputFlattenedModelNode.CreateDefaultDisplayNodes()
      outputFlattenedModelNode.GetDisplayNode().BackfaceCullingOff()
      outputFlattenedModelNode.GetDisplayNode().SetVisibility2D(True)
      outputFlattenedModelNode.GetDisplayNode().SetColor(self.inputCurveNode.GetDisplayNode().GetSelectedColor())
      # we don't recompute normals, and it is a plane anyway, so just show it with flat shading
      outputFlattenedModelNode.GetDisplayNode().SetInterpolation(slicer.vtkMRMLDisplayNode.FlatInterpolation)
      outputFlattenedModelNode.GetDisplayNode().SetColor(0.1, 0.1, 0.8)

      # For user convenience, we do not ask the user to select a node but create automatically (if not created already)
      fixedPointsNode = self.getInputFixedPointsNode()
      if (not fixedPointsNode) and outputFlattenedModelNode:
        fixedPointsNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", outputFlattenedModelNode.GetName() + " fixed points")
        fixedPointsNode.CreateDefaultDisplayNodes()
        fixedPointsNode.SetMarkupLabelFormat('F-%d')
        fixedPointsNode.GetDisplayNode().SetPointLabelsVisibility(True)
        fixedPointsNode.GetDisplayNode().SetGlyphType(slicer.vtkMRMLMarkupsDisplayNode.Sphere3D)
        self.setInputFixedPointsNode(fixedPointsNode)
      outputFlattenedFixedPointsNode = self.getOutputFlattenedFixedPointsNode()
      if (not outputFlattenedFixedPointsNode) and outputFlattenedModelNode:
        outputFlattenedFixedPointsNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", outputFlattenedModelNode.GetName() + " flattened fixed points")
        outputFlattenedFixedPointsNode.CreateDefaultDisplayNodes()
        outputFlattenedFixedPointsNode.GetDisplayNode().SetPointLabelsVisibility(True)
        outputFlattenedFixedPointsNode.GetDisplayNode().SetSelectedColor(0.9,0.6,0.9)
        outputFlattenedFixedPointsNode.GetDisplayNode().SetGlyphType(slicer.vtkMRMLMarkupsDisplayNode.Sphere3D)
        try:
          # Enable shadow (only available in Slicer-4.13)
          slicer.vtkMRMLMarkupsDisplayNode.UpdateTextPropertyFromString('font-weight:bold;text-shadow:2px 2px 2px rgba(0,0,0,1.0)',
            outputFlattenedFixedPointsNode.GetDisplayNode().GetTextProperty())
        except:
          pass
        self.setOutputFlattenedFixedPointsNode(outputFlattenedFixedPointsNode)

    self.inputCurveNode.SetAndObserveNodeReferenceID('FlattenedModel', outputFlattenedModelNode.GetID() if outputFlattenedModelNode else None)

  def getOutputFlattenedModelNode(self):
    if not self.inputCurveNode:
      return None
    return self.inputCurveNode.GetNodeReference('FlattenedModel')

  @staticmethod
  def getClosestVerticesForFiducials(modelNode, markupsFiducialNode):
    closestVertices = []
    pointLocator = vtk.vtkPointLocator()
    pointLocator.SetDataSet(modelNode.GetPolyData())
    try:
      # Slicer-4.13 (February 2022) and later
      numberOfControlPoints = markupsFiducialNode.GetNumberOfControlPoints()
    except:
      # fall back to older API
      numberOfControlPoints = markupsFiducialNode.GetNumberOfFiducials()
    for fiducialIndex in range(numberOfControlPoints):
      fiducialPos = [0]*3
      try:
        # Current API (Slicer-4.13 February 2022)
        markupsFiducialNode.GetNthControlPointPosition(fiducialIndex, fiducialPos)
      except:
        # Legacy API
        markupsFiducialNode.GetNthFiducialPosition(fiducialIndex, fiducialPos)
      closestVertexIndex = pointLocator.FindClosestPoint(fiducialPos)
      if closestVertexIndex >= 0:
        closestVertices.append(closestVertexIndex)
    return closestVertices

  def flattenOutputBaffleModel(self, progressCallback=None):
    if not self.getInputFixedPointsNode():
      raise ValueError("Fixed points fidicuals list is not assigned")
    try:
      # Current API (Slicer-4.13 February 2022)
      numberOfFiducials = self.getInputFixedPointsNode().GetNthControlPointPosition()
    except:
      # Legacy API
      numberOfFiducials = self.getInputFixedPointsNode().GetNumberOfFiducials()
    if numberOfFiducials < 2:
      raise ValueError("At least two fixed point fiducials are required")

    flattenedModelNode = self.getOutputFlattenedModelNode()
    if not self.getOutputBaffleModelNode() or not flattenedModelNode:
      raise ValueError("Missing parameters to flatten baffle model")

    # Hide flattened baffle model until rescaling to prevent flickering between initial size and final size
    flattenedModelNode.SetDisplayVisibility(False)

    parameters = {}
    parameters["inputModel"] = self.getOutputBaffleModelNode().GetID()
    parameters["fixedPoints"] = self.getInputFixedPointsNode().GetID()
    # Arbitrary value for the first two fixed points. Baffle will be scaled later
    parameters["fixedPointTextureCoords"] = "0 0 100 0"
    parameters["outputModel"] = flattenedModelNode.GetID()

    self.cliConformalTextureMapping = None
    self.cliConformalTextureMapping = slicer.cli.run(slicer.modules.conformaltexturemapping, None, parameters)
    waitTime = 0 # Total amount of time we wait until we give up waiting
    waitCycle = 0.1 # Amount of time we wait between checking if it finished
    import time
    while self.cliConformalTextureMapping.GetStatusString() != 'Completed' and waitTime < 20:
      time.sleep(waitCycle)
      waitTime += waitCycle
      if progressCallback:
        progressCallback(str(waitTime))

    if self.cliConformalTextureMapping.GetStatusString() != 'Completed':
      self.cliConformalTextureMapping.Cancel()
      raise ValueError('Flattening baffle failed')

    # Scale the flattened baffle to actual size
    massProperties = vtk.vtkMassProperties()
    massProperties.SetInputConnection(self.getOutputBaffleModelNode().GetPolyDataConnection())
    massProperties.Update()
    baffleArea = massProperties.GetSurfaceArea()
    massProperties.SetInputConnection(flattenedModelNode.GetPolyDataConnection())
    massProperties.Update()
    flattenedUnscaledBaffleArea = massProperties.GetSurfaceArea()
    import math
    scale = math.sqrt(baffleArea / flattenedUnscaledBaffleArea)
    flattenedBaffleToScaledFlattenedBaffleTransform = vtk.vtkTransform()
    flattenedBaffleToScaledFlattenedBaffleTransform.Scale(scale, scale, scale)
    transformFilter = vtk.vtkTransformPolyDataFilter()
    transformFilter.SetInputData(flattenedModelNode.GetPolyData())
    transformFilter.SetTransform(flattenedBaffleToScaledFlattenedBaffleTransform)
    transformFilter.Update()
    flattenedModelNode.SetAndObservePolyData(transformFilter.GetOutput())
    flattenedModelNode.SetDisplayVisibility(True)

    # Update flattened fixed points markup node
    flattenedFixedPointsNode = self.getOutputFlattenedFixedPointsNode()
    inputFixedPointsNode = self.getInputFixedPointsNode()
    flattenedFixedPointsNode.RemoveAllControlPoints()
    closestVertexIndices = BafflePlannerLogic.getClosestVerticesForFiducials(self.getOutputBaffleModelNode(), inputFixedPointsNode)
    flattenedPolyDataPoints = flattenedModelNode.GetPolyData().GetPoints()
    # Set the flattened fixed node points size based on the model size
    bounds = [0,0,0,0,0,0]
    self.getOutputBaffleModelNode().GetRASBounds(bounds)
    modelDiameter = pow(pow(bounds[1]-bounds[0], 2)+pow(bounds[3]-bounds[2], 2)+pow(bounds[5]-bounds[4], 2), 0.5)
    flattenedFixedPointsNode.GetDisplayNode().SetUseGlyphScale(False)
    flattenedFixedPointsNode.GetDisplayNode().SetGlyphSize(modelDiameter*0.05)
    flattenedFixedPointsNode.GetDisplayNode().SetTextScale(5.0)
    for pointIndex, vertIdx in enumerate(closestVertexIndices):
      p = flattenedPolyDataPoints.GetPoint(vertIdx)
      flattenedFixedPointsNode.AddControlPointWorld(vtk.vtkVector3d(p), inputFixedPointsNode.GetNthControlPointLabel(pointIndex))

  def generatePixmapForPrinting(self, filePath):
    if not self.getOutputFlattenedModelNode():
      raise ValueError("Failed to access flattened baffle model")

    flattenedBaffleNode = self.getOutputFlattenedModelNode()
    flattenedFixedPointsNode = self.getOutputFlattenedFixedPointsNode()
    vtkImage = self.generatePixmapFromFlatModel(flattenedBaffleNode, flattenedFixedPointsNode)

    # Write to file with custom DPI
    # (use Qt file writer to allow saving DPI values)
    qImage = qt.QImage()
    slicer.qMRMLUtils().vtkImageDataToQImage(vtkImage, qImage)
    inchesPerMeter = 1000/25.4
    qImage.setDotsPerMeterX(self.printXResolutionDpi*inchesPerMeter)
    qImage.setDotsPerMeterY(self.printYResolutionDpi*inchesPerMeter)
    imagePixmap = qt.QPixmap.fromImage(qImage)
    imagePixmap.save(filePath)

  def generatePixmapFromFlatModel(self, flatModelNode, fiducialsNode, showRuler=True, customPrintScale=None, customPrintViewSize=None):
    if not flatModelNode:
      raise ValueError('Must give a valid flat model node')

    if not self.printThreeDViewNode:
      self.printThreeDViewNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLViewNode")
      self.printThreeDViewNode.UnRegister(None)
      self.printThreeDViewNode.SetSingletonTag("FlattenedModelPrinter")
      self.printThreeDViewNode.SetName("FlattenedModelPrinter")
      self.printThreeDViewNode.SetLayoutName("FlattenedModelPrinter")
      self.printThreeDViewNode.SetLayoutLabel("FlattenedModelPrinter")
      self.printThreeDViewNode.SetLayoutColor(1, 1, 0)
      self.printThreeDViewNode.SetAndObserveParentLayoutNodeID(flatModelNode.GetID())
      if showRuler:
        self.printThreeDViewNode.SetRulerType(slicer.vtkMRMLAbstractViewNode.RulerTypeThin)
        self.printThreeDViewNode.SetRulerColor(slicer.vtkMRMLAbstractViewNode.RulerColorBlack)
      else:
        self.printThreeDViewNode.SetRulerType(slicer.vtkMRMLAbstractViewNode.RulerTypeNone)
      self.printThreeDViewNode = slicer.mrmlScene.AddNode(self.printThreeDViewNode)

    if not self.printThreeDWidget:
      self.printThreeDWidget = slicer.qMRMLThreeDWidget()
      self.printThreeDWidget.setObjectName("self.printThreeDWidget"+self.printThreeDViewNode.GetLayoutLabel())
      self.printThreeDWidget.viewLabel = self.printThreeDViewNode.GetLayoutLabel()
      self.printThreeDWidget.viewColor = qt.QColor.fromRgbF(*self.printThreeDViewNode.GetLayoutColor())
      self.printThreeDWidget.setMRMLScene(slicer.mrmlScene)
      self.printThreeDWidget.setMRMLViewNode(self.printThreeDViewNode)

    self.printThreeDViewNode.SetAndObserveParentLayoutNodeID(flatModelNode.GetID())
    self.printThreeDWidget.setMRMLViewNode(self.printThreeDViewNode)

    # Configure view and widget
    self.printThreeDViewNode.SetBoxVisible(0)
    self.printThreeDViewNode.SetAxisLabelsVisible(0)
    self.printThreeDViewNode.SetRenderMode(slicer.vtkMRMLViewNode.Orthographic)
    self.printThreeDViewNode.SetBackgroundColor((1,1,1))
    self.printThreeDViewNode.SetBackgroundColor2((1,1,1))

    # Set color and shading of flattened model and fixed points
    flattenedModelDisplayNode = flatModelNode.GetDisplayNode()
    flattenedModelOriginalColor = flattenedModelDisplayNode.GetColor()
    flattenedModelDisplayNode.SetColor(0.0, 0.0, 0.0)

    if fiducialsNode:
      fiducialsDisplayNode = fiducialsNode.GetDisplayNode()
      fiducialsOriginalVisibility = fiducialsDisplayNode.GetVisibility()
      fiducialsDisplayNode.SetVisibility(True)
      fiducialsOriginalColor = fiducialsDisplayNode.GetColor()
      fiducialsDisplayNode.SetColor(1.0, 0.5, 0.5)
    else:
      fiducialsDisplayNode = None

    # Make sure nothing is visible in the print view other than the model and the fixed landmarks
    hiddenDisplayNodes = []
    layoutThreeDViewNode = slicer.app.layoutManager().threeDWidget(0).viewLogic().GetViewNode()
    allDisplayNodes = slicer.util.getNodesByClass('vtkMRMLDisplayNode')
    for displayNode in allDisplayNodes:
      if displayNode is not flattenedModelDisplayNode and displayNode is not fiducialsDisplayNode:
        displayNode.AddViewNodeID(layoutThreeDViewNode.GetID())
        hiddenDisplayNodes.append(displayNode)

    # Show 3D view
    if customPrintViewSize is None:
      printViewSize = [self.printViewWidth, self.printViewHeight]
    else:
      printViewSize = customPrintViewSize
    self.printThreeDWidget.resize(printViewSize[0], printViewSize[1])
    self.printThreeDWidget.show()

    # Determine ROI for flattened model
    flatModelPolyData = flatModelNode.GetPolyData()
    bounds = [0]*6
    flatModelPolyData.GetBounds(bounds)
    center = [ (bounds[0]+bounds[1])/2.0, (bounds[2]+bounds[3])/2.0, (bounds[4]+bounds[5])/2.0 ]

    # Setup camera
    cameraPositionOffset = 100.0
    cameraNode = slicer.modules.cameras.logic().GetViewActiveCameraNode(self.printThreeDViewNode)
    cameraNode.SetFocalPoint(center)
    cameraNode.SetPosition(center[0], center[1], center[2] + bounds[5]-bounds[4] + cameraPositionOffset)
    cameraNode.SetViewUp(0, 1, 0)
    cameraNode.GetCamera().SetClippingRange(cameraPositionOffset/2.0, (bounds[5]-bounds[4]) * 2 + cameraPositionOffset * 2.0)

    windowSizeInPixels = self.printThreeDWidget.threeDView().renderWindow().GetSize()

    if customPrintScale is None:
      printScale = self.printScale
    else:
      printScale = customPrintScale
    pixelSizeInMm =  25.4 / self.printYResolutionDpi
    printViewHeightOfViewportInMm = windowSizeInPixels[1] * pixelSizeInMm / printScale
    cameraNode.SetParallelScale(printViewHeightOfViewportInMm)

    threeDView = self.printThreeDWidget.threeDView()
    renderWindow = threeDView.renderWindow()
    renderer = renderWindow.GetRenderers().GetFirstRenderer()

    originalCameraUserTransform = cameraNode.GetCamera().GetUserTransform()
    # originalPixelAspect = renderer.GetPixelAspect()
    cameraUserTransform = vtk.vtkTransform()
    cameraUserTransform.Scale(self.printXResolutionDpi/self.printYResolutionDpi,1.0,1.0)
    cameraNode.GetCamera().SetUserTransform(cameraUserTransform)

    if self.printTransparentBackground:
      originalAlphaBitPlanes = renderWindow.GetAlphaBitPlanes()
      renderWindow.SetAlphaBitPlanes(1)
      originalGradientBackground = renderer.GetGradientBackground()
      renderer.SetGradientBackground(False)

    # Render
    threeDView.forceRender()
    windowToImage = vtk.vtkWindowToImageFilter()
    if self.printTransparentBackground:
      windowToImage.SetInputBufferTypeToRGBA()
      renderWindow.Render()

    windowToImage.SetInput(renderWindow)
    windowToImage.Update()
    vtkImage = windowToImage.GetOutput()

    # Restore settings
    self.printThreeDWidget.hide()

    cameraNode.GetCamera().SetUserTransform(originalCameraUserTransform)
    flattenedModelDisplayNode.SetColor(flattenedModelOriginalColor)
    if fiducialsDisplayNode:
      fiducialsDisplayNode.SetVisibility(fiducialsOriginalVisibility)
      fiducialsDisplayNode.SetColor(fiducialsOriginalColor)
    for displayNode in hiddenDisplayNodes:
      displayNode.RemoveAllViewNodeIDs()

    if self.printTransparentBackground:
      renderWindow.SetAlphaBitPlanes(originalAlphaBitPlanes)
      renderer.SetGradientBackground(originalGradientBackground)

    return vtkImage


class BafflePlannerTest(ScriptedLoadableModuleTest):
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
    self.test_BafflePlanner1()

  def test_BafflePlanner1(self):
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
    logic = BafflePlannerLogic()
    self.delayDisplay('Test passed')
