import os
import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging

#
# ValveView
#

class ValveView(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Valve View"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Andras Lasso (PerkLab)"]
    self.parent.helpText = """
    """
    self.parent.acknowledgementText = """
    This file was originally developed by Andras Lasso, PerkLab.
""" # replace with organization, grant and thanks.

#
# ValveViewWidget
#

class ValveViewWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    self.markupsNodeObservations = []

    # Instantiate and connect widgets ...

    #
    # Parameters Area
    #
    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(parametersCollapsibleButton)

    # Layout within the dummy collapsible button
    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    #
    # slice role selector
    #

    self.axialSliceSelector = slicer.qMRMLNodeComboBox()
    self.axialSliceSelector.nodeTypes = ( ("vtkMRMLSliceNode"), "" )
    self.axialSliceSelector.selectNodeUponCreation = False
    self.axialSliceSelector.addEnabled = False
    self.axialSliceSelector.removeEnabled = False
    self.axialSliceSelector.noneEnabled = True
    self.axialSliceSelector.showHidden = False
    self.axialSliceSelector.showChildNodeTypes = False
    self.axialSliceSelector.setMRMLScene( slicer.mrmlScene )
    self.axialSliceSelector.setToolTip( "Pick the slice that will show the transverse view." )
    parametersFormLayout.addRow("Axial view: ", self.axialSliceSelector)
    self.axialSliceSelector.setCurrentNode(slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeRed'))

    self.orthogonalSlice1Selector = slicer.qMRMLNodeComboBox()
    self.orthogonalSlice1Selector.nodeTypes = ( ("vtkMRMLSliceNode"), "" )
    self.orthogonalSlice1Selector.selectNodeUponCreation = False
    self.orthogonalSlice1Selector.addEnabled = False
    self.orthogonalSlice1Selector.removeEnabled = False
    self.orthogonalSlice1Selector.noneEnabled = True
    self.orthogonalSlice1Selector.showHidden = False
    self.orthogonalSlice1Selector.showChildNodeTypes = False
    self.orthogonalSlice1Selector.setMRMLScene( slicer.mrmlScene )
    self.orthogonalSlice1Selector.setToolTip( "Pick the slice that will show a plane orthogonal to the axial slice." )
    parametersFormLayout.addRow("Orthogonal view 1: ", self.orthogonalSlice1Selector)
    self.orthogonalSlice1Selector.setCurrentNode(slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeYellow'))

    self.orthogonalSlice2Selector = slicer.qMRMLNodeComboBox()
    self.orthogonalSlice2Selector.nodeTypes = ( ("vtkMRMLSliceNode"), "" )
    self.orthogonalSlice2Selector.selectNodeUponCreation = False
    self.orthogonalSlice2Selector.addEnabled = False
    self.orthogonalSlice2Selector.removeEnabled = False
    self.orthogonalSlice2Selector.noneEnabled = True
    self.orthogonalSlice1Selector.showHidden = False
    self.orthogonalSlice2Selector.showChildNodeTypes = False
    self.orthogonalSlice2Selector.setMRMLScene( slicer.mrmlScene )
    self.orthogonalSlice2Selector.setToolTip( "Pick the slice that will show a plane orthogonal to the two other slices." )
    parametersFormLayout.addRow("Orthogonal view 2: ", self.orthogonalSlice2Selector)
    self.orthogonalSlice2Selector.setCurrentNode(slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeGreen'))
    
    #
    # Orthogonal slice rotation
    #
    
    self.lastOrthogonalSlicerRotationVale = 0
    
    self.orthogonalSlicerRotationSliderWidget = ctk.ctkSliderWidget()
    self.orthogonalSlicerRotationSliderWidget.singleStep = 1
    self.orthogonalSlicerRotationSliderWidget.minimum = -360
    self.orthogonalSlicerRotationSliderWidget.maximum = 360
    self.orthogonalSlicerRotationSliderWidget.value = self.lastOrthogonalSlicerRotationVale
    self.orthogonalSlicerRotationSliderWidget.setToolTip("Rotation angle of the orthogonal views")
    parametersFormLayout.addRow("Rotation angle", self.orthogonalSlicerRotationSliderWidget)
    
    orthogonalSlicerRotationBox = qt.QHBoxLayout()
    
    self.orthogonalSlicerRotationStepSizeSpinBox = qt.QDoubleSpinBox()
    self.orthogonalSlicerRotationStepSizeSpinBox.setToolTip("Increment value by that a single button press changes the orthogonal view angle")
    self.orthogonalSlicerRotationStepSizeSpinBox.value = 20
    self.orthogonalSlicerRotationStepSizeSpinBox.minimum = 0.1
    self.orthogonalSlicerRotationStepSizeSpinBox.maximum = 90
    self.orthogonalSlicerRotationStepSizeSpinBox.singleStep = 5
    self.orthogonalSlicerRotationStepSizeSpinBox.decimals = 1
    orthogonalSlicerRotationBox.addWidget(self.orthogonalSlicerRotationStepSizeSpinBox)

    self.orthogonalSliceRotationAngleDecButton = qt.QPushButton()
    self.orthogonalSliceRotationAngleDecButton.text = "<"
    orthogonalSlicerRotationBox.addWidget(self.orthogonalSliceRotationAngleDecButton)
    
    self.orthogonalSliceRotationAngleIncButton = qt.QPushButton()
    self.orthogonalSliceRotationAngleIncButton.text = ">"
    orthogonalSlicerRotationBox.addWidget(self.orthogonalSliceRotationAngleIncButton)

    parametersFormLayout.addRow("", orthogonalSlicerRotationBox)

    #
    # Parameters Area
    #
    autoRotateCollapsibleButton = ctk.ctkCollapsibleButton()
    autoRotateCollapsibleButton.text = "Auto-rotate"
    autoRotateFormLayout = qt.QFormLayout(autoRotateCollapsibleButton)
    self.layout.addWidget(autoRotateCollapsibleButton)

    self.markupsNodeSelector = slicer.qMRMLNodeComboBox()
    self.markupsNodeSelector.nodeTypes = ["vtkMRMLMarkupsClosedCurveNode"]
    self.markupsNodeSelector.addEnabled = False
    self.markupsNodeSelector.removeEnabled = True
    self.markupsNodeSelector.noneEnabled = True
    self.markupsNodeSelector.setMRMLScene( slicer.mrmlScene )
    self.markupsNodeSelector.setToolTip("Pick a closed curve node that should make the rotation advance automatically upon point placement." )
    autoRotateFormLayout.addRow("Closed curve node: ", self.markupsNodeSelector)

    # connections
    self.orthogonalSliceRotationAngleDecButton.connect('clicked(bool)', self.onOrthogonalSlicerRotationAngleDec)
    self.orthogonalSliceRotationAngleIncButton.connect('clicked(bool)', self.onOrthogonalSlicerRotationAngleInc)
    self.orthogonalSlicerRotationSliderWidget.connect('valueChanged(double)', self.onOrthogonalSlicerRotationAngleChanged)
    self.markupsNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onMarkupsNodeSelectionChanged)

    # Add vertical spacer
    self.layout.addStretch(1)

    # Refresh Apply button state
    self.onSelect()

  def cleanup(self):
    pass

  def onSelect(self):
    #self.applyButton.enabled = self.inputSelector.currentNode() and self.transverseSliceSelector.currentNode()
    pass

  def onOrthogonalSlicerRotationAngleDec(self):
    orthogonalSliceRotationValue = self.orthogonalSlicerRotationSliderWidget.value
    orthogonalSliceRotationValue = orthogonalSliceRotationValue - self.orthogonalSlicerRotationStepSizeSpinBox.value
    # wrap around
    if orthogonalSliceRotationValue < self.orthogonalSlicerRotationSliderWidget.minimum:
      orthogonalSliceRotationValue = orthogonalSliceRotationValue + (self.orthogonalSlicerRotationSliderWidget.maximum - self.orthogonalSlicerRotationSliderWidget.minimum)
    self.orthogonalSlicerRotationSliderWidget.value = orthogonalSliceRotationValue

  def onOrthogonalSlicerRotationAngleInc(self):
    orthogonalSliceRotationValue = self.orthogonalSlicerRotationSliderWidget.value
    orthogonalSliceRotationValue = orthogonalSliceRotationValue + self.orthogonalSlicerRotationStepSizeSpinBox.value
    # wrap around
    if orthogonalSliceRotationValue > self.orthogonalSlicerRotationSliderWidget.maximum:
      orthogonalSliceRotationValue = orthogonalSliceRotationValue - (self.orthogonalSlicerRotationSliderWidget.maximum - self.orthogonalSlicerRotationSliderWidget.minimum)
    self.orthogonalSlicerRotationSliderWidget.value = orthogonalSliceRotationValue

  def onOrthogonalSlicerRotationAngleChanged(self, newRotationValue):
    rotationAngleChangeDeg = newRotationValue-self.lastOrthogonalSlicerRotationVale
    logic = ValveViewLogic()
    logic.rotateOrthogonalSlicesDeg(self.axialSliceSelector.currentNode(), self.orthogonalSlice1Selector.currentNode(), self.orthogonalSlice2Selector.currentNode(), rotationAngleChangeDeg)
    self.lastOrthogonalSlicerRotationVale = newRotationValue

  def onMarkupsNodeSelectionChanged(self, markupsNode):
    for node, observation in self.markupsNodeObservations:
      node.RemoveObserver(observation)
    self.markupsNodeObservations = []
    if markupsNode is None:
      return
    for evt in [slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent]:
      self.markupsNodeObservations.append([markupsNode, markupsNode.AddObserver(evt, lambda caller, eventId: self.onOrthogonalSlicerRotationAngleInc())])

#
# ValveViewLogic
#

class ValveViewLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def getPlaneIntersectionPoint(self, axialNode, ortho1Node, ortho2Node):
    # Compute the center of rotation (common intersection point of the three planes)
    # http://mathworld.wolfram.com/Plane-PlaneIntersection.html
        
    #axialNode = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeRed')
    #ortho1Node = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeYellow')
    #ortho2Node = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeGreen')

    axialSliceToRas = axialNode.GetSliceToRAS()
    n1 = [axialSliceToRas.GetElement(0,2),axialSliceToRas.GetElement(1,2),axialSliceToRas.GetElement(2,2)]
    x1 = [axialSliceToRas.GetElement(0,3),axialSliceToRas.GetElement(1,3),axialSliceToRas.GetElement(2,3)]

    ortho1SliceToRas = ortho1Node.GetSliceToRAS()
    n2 = [ortho1SliceToRas.GetElement(0,2),ortho1SliceToRas.GetElement(1,2),ortho1SliceToRas.GetElement(2,2)]
    x2 = [ortho1SliceToRas.GetElement(0,3),ortho1SliceToRas.GetElement(1,3),ortho1SliceToRas.GetElement(2,3)]

    ortho2SliceToRas = ortho2Node.GetSliceToRAS()
    n3 = [ortho2SliceToRas.GetElement(0,2),ortho2SliceToRas.GetElement(1,2),ortho2SliceToRas.GetElement(2,2)]
    x3 = [ortho2SliceToRas.GetElement(0,3),ortho2SliceToRas.GetElement(1,3),ortho2SliceToRas.GetElement(2,3)]

    # Computed intersection point of all planes
    x = [0,0,0]    

    n2_xp_n3 = [0,0,0]
    x1_dp_n1 = vtk.vtkMath.Dot(x1,n1)
    vtk.vtkMath.Cross(n2,n3,n2_xp_n3)
    vtk.vtkMath.MultiplyScalar(n2_xp_n3, x1_dp_n1)
    vtk.vtkMath.Add(x,n2_xp_n3,x)

    n3_xp_n1 = [0,0,0]
    x2_dp_n2 = vtk.vtkMath.Dot(x2,n2)
    vtk.vtkMath.Cross(n3,n1,n3_xp_n1)
    vtk.vtkMath.MultiplyScalar(n3_xp_n1, x2_dp_n2)
    vtk.vtkMath.Add(x,n3_xp_n1,x)

    n1_xp_n2 = [0,0,0]
    x3_dp_n3 = vtk.vtkMath.Dot(x3,n3)
    vtk.vtkMath.Cross(n1,n2,n1_xp_n2)
    vtk.vtkMath.MultiplyScalar(n1_xp_n2, x3_dp_n3)
    vtk.vtkMath.Add(x,n1_xp_n2,x)

    normalMatrix = vtk.vtkMatrix3x3()
    normalMatrix.SetElement(0,0,n1[0])
    normalMatrix.SetElement(1,0,n1[1])
    normalMatrix.SetElement(2,0,n1[2])
    normalMatrix.SetElement(0,1,n2[0])
    normalMatrix.SetElement(1,1,n2[1])
    normalMatrix.SetElement(2,1,n2[2])
    normalMatrix.SetElement(0,2,n3[0])
    normalMatrix.SetElement(1,2,n3[1])
    normalMatrix.SetElement(2,2,n3[2])
    normalMatrixDeterminant = normalMatrix.Determinant()
    
    if abs(normalMatrixDeterminant)>0.01:
      # there is an intersection point
      vtk.vtkMath.MultiplyScalar(x, 1/normalMatrixDeterminant)
    else:
      # no intersection point can be determined, use just the position of the axial slice
      x = x1
    
    return x
  
  def rotateOrthogonalSlicesDeg(self, axialNode, ortho1Node, ortho2Node, rotationChangeDeg):
    """
    Rotate the orthogonal nodes around the common intersection point, around the normal of the axial node
    """
    
    # All points and vectors are in RAS coordinate system
    
    intersectionPoint = self.getPlaneIntersectionPoint(axialNode, ortho1Node, ortho2Node)
    
    axialSliceToRas = axialNode.GetSliceToRAS()
    rotationTransform = vtk.vtkTransform()
    rotationTransform.RotateZ(rotationChangeDeg)
    
    #rotatedAxialSliceToRas = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Multiply4x4(axialSliceToRas, rotationTransform.GetMatrix(), axialSliceToRas)
    
    # Invert the direction of the two vectors so that by default they produce the same slice orientation as Slicer's
    # "sagittal" and "coronal" slice orientation if the axial node is in "axial" orientation
    axialSliceNormal = [-axialSliceToRas.GetElement(0,2),-axialSliceToRas.GetElement(1,2),-axialSliceToRas.GetElement(2,2)]
    axialSliceAxisX = [-axialSliceToRas.GetElement(0,0),-axialSliceToRas.GetElement(1,0),-axialSliceToRas.GetElement(2,0)]

    paraSagittalOrientationCode = 1
    paraCoronalOrientationCode = 2
    
    ortho1Node.SetSliceToRASByNTP(axialSliceNormal[0],axialSliceNormal[1],axialSliceNormal[2], axialSliceAxisX[0],axialSliceAxisX[1],axialSliceAxisX[2], intersectionPoint[0], intersectionPoint[1], intersectionPoint[2], paraSagittalOrientationCode)
    
    ortho2Node.SetSliceToRASByNTP(axialSliceNormal[0],axialSliceNormal[1],axialSliceNormal[2], axialSliceAxisX[0],axialSliceAxisX[1],axialSliceAxisX[2], intersectionPoint[0], intersectionPoint[1], intersectionPoint[2], paraCoronalOrientationCode)
    
    return True


class ValveViewTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_ValveView1()

  def test_ValveView1(self):
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

    self.delayDisplay("No tests are implemented")
