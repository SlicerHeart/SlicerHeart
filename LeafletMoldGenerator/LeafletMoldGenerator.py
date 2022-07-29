import vtk
import qt
import ctk
import slicer
from slicer.ScriptedLoadableModule import *
import logging
import math
import numpy as np
#
# LeafletMoldGenerator
#

class LeafletMoldGenerator(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Leaflet Mold Generator"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["ValveAnnulusAnalysis"]
    self.parent.contributors = ["Anna Ilina (PerkLab), Andras Lasso (PerkLab), Matt Jolley (UPenn)"]
    self.parent.helpText = """Generate a 3D-printable mold for leaflet phantom"""
    self.parent.acknowledgementText = """This file was originally developed by Anna Ilina, PerkLab."""

#
# LeafletMoldGeneratorWidget
#

class LeafletMoldGeneratorWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModuleWidget.__init__(self, parent)

    self.logic = LeafletMoldGeneratorLogic()

    self.parameterNode = None
    self.parameterNodeObserver = None

    # Stores the currently selected HeartValveNode (scripted loadable module node)
    # and also provides methods to operate on it.
    self.valveModel = None

    self.leafletIDs = None

    self.numberAirTunnels = 10 # should be an even number (to evenly alternate skirt and rim tunnels)

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Instantiate and connect widgets ...

    #
    # moldMeasurements section
    #
    valveFormLayout = qt.QFormLayout()
    self.layout.addLayout(valveFormLayout)

    self.heartValveSelector = slicer.qMRMLNodeComboBox()
    self.heartValveSelector.nodeTypes = ["vtkMRMLScriptedModuleNode"]
    self.heartValveSelector.setNodeTypeLabel("HeartValve", "vtkMRMLScriptedModuleNode")
    self.heartValveSelector.baseName = "HeartValve"
    self.heartValveSelector.addAttribute( "vtkMRMLScriptedModuleNode", "ModuleName", "HeartValve" )
    self.heartValveSelector.addEnabled = True
    self.heartValveSelector.removeEnabled = True
    self.heartValveSelector.noneEnabled = False
    self.heartValveSelector.showHidden = True # scripted module nodes are hidden by default
    self.heartValveSelector.renameEnabled = True
    self.heartValveSelector.setMRMLScene(slicer.mrmlScene)
    self.heartValveSelector.setToolTip("Select heart valve node with annulus contour and leaflets specified")
    valveFormLayout.addRow("Heart valve: ", self.heartValveSelector)
    self.heartValveSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onHeartValveSelect)

    #
    # Mold Measurements section
    #buttons added based on based on 'Sampling distance' selector in ValveAnnulusAnalysis.py
    #
    self.moldMeasurementsCollapsibleButton = ctk.ctkCollapsibleButton()
    self.moldMeasurementsCollapsibleButton.objectName = "Mold Measurements"
    self.moldMeasurementsCollapsibleButton.text = "Mold Measurements"
    self.layout.addWidget(self.moldMeasurementsCollapsibleButton)
    moldMeasurementsFormLayout = qt.QFormLayout(self.moldMeasurementsCollapsibleButton)

    # Leaflet thickness selector
    self.leafletThicknessSpinBox = qt.QDoubleSpinBox()
    self.leafletThicknessSpinBox.setToolTip("Desired leaflet thickness (in mm), to be grown from extracted leaflet top surface")
    self.leafletThicknessSpinBox.minimum = 0.0
    self.leafletThicknessSpinBox.maximum = 10.0
    self.leafletThicknessSpinBox.value = 0.5
    moldMeasurementsFormLayout.addRow("Leaflet thickness (mm):", self.leafletThicknessSpinBox)

    # Gap between grown leaflets selector
    self.gapBetweenLeafletsSpinBox = qt.QDoubleSpinBox()
    self.gapBetweenLeafletsSpinBox.setToolTip("Desired gap (mm) between grown leaflets, for printing the mold")
    self.gapBetweenLeafletsSpinBox.minimum = 0.0
    self.gapBetweenLeafletsSpinBox.maximum = 10.0
    self.gapBetweenLeafletsSpinBox.value = 1.0
    moldMeasurementsFormLayout.addRow("Gap between grown leaflets (mm):", self.gapBetweenLeafletsSpinBox)

    # Add a radio button to choose whether to grow leaflets from extracted top surface or use segmented leaflets
    self.useGrownLeafletsToMakeMoldButton = qt.QRadioButton()
    self.useGrownLeafletsToMakeMoldButton.setToolTip ("If yes, leaflets for mold generation will be grown from extracted top surface. Otherwise, will use segmented leaflets.")
    self.useGrownLeafletsToMakeMoldButton.setChecked(True)
    moldMeasurementsFormLayout.addRow("Use grown leaflets from extracted top surface for mold?", self.useGrownLeafletsToMakeMoldButton)

    # Rim Size Selector
    self.shrinkRimSpinBox = qt.QDoubleSpinBox()
    self.shrinkRimSpinBox.setToolTip("If necessary, bring the rim in this many mm to close the gap between grown leaflets and rim (temporary fix)")
    self.shrinkRimSpinBox.minimum = 0.0
    self.shrinkRimSpinBox.maximum = 10.0
    self.shrinkRimSpinBox.value = 0.0
    moldMeasurementsFormLayout.addRow("Shrink rim (mm):", self.shrinkRimSpinBox)


    # Rim Size Selector
    self.rimSizeSpinBox = qt.QDoubleSpinBox()
    self.rimSizeSpinBox.setToolTip("Radius of rim surround valve annulus (in mm)")
    self.rimSizeSpinBox.minimum = 0.0
    self.rimSizeSpinBox.maximum = 5.0
    self.rimSizeSpinBox.value = 2.0
    moldMeasurementsFormLayout.addRow("Rim radius (mm):", self.rimSizeSpinBox)

    # Rim stiffener selector
    self.rimStiffenerLengthSpinBox = qt.QDoubleSpinBox()
    self.rimStiffenerLengthSpinBox.setToolTip("Length (in mm) of rim stiffener that protrudes downwards from valve rim")
    self.rimStiffenerLengthSpinBox.minimum = 0.0
    self.rimStiffenerLengthSpinBox.maximum = 40.0
    self.rimStiffenerLengthSpinBox.value = 10.0
    moldMeasurementsFormLayout.addRow("Rim stiffener length (mm):", self.rimStiffenerLengthSpinBox)

    # Skirt Parameter Selectors
    skirtParametersBox = qt.QHBoxLayout()

    self.skirtThicknessLabel = qt.QLabel('Skirt thickness (mm):')
    skirtParametersBox.addWidget(self.skirtThicknessLabel)

    self.skirtThicknessSpinBox = qt.QDoubleSpinBox()
    self.skirtThicknessSpinBox.setToolTip("Thickness of skirt surrounding the valve rim (in mm). Adjust by preference")
    self.skirtThicknessSpinBox.minimum = 0.0
    self.skirtThicknessSpinBox.maximum = 5.0
    self.skirtThicknessSpinBox.value = 2.0
    #moldMeasurementsFormLayout.addRow("Skirt thickness (mm):", self.skirtThicknessSpinBox)
    skirtParametersBox.addWidget(self.skirtThicknessSpinBox)

    self.skirtOuterRadiusLabel = qt.QLabel('Skirt outer radius (mm):')
    skirtParametersBox.addWidget(self.skirtOuterRadiusLabel)

    self.skirtOuterRadiusSpinBox = qt.QDoubleSpinBox()
    self.skirtOuterRadiusSpinBox.setToolTip("Radius of the skirt surrounding the valve rim (in mm). Adjust to fit valve holder.")
    self.skirtOuterRadiusSpinBox.minimum = 30.0
    self.skirtOuterRadiusSpinBox.maximum = 40.0
    self.skirtOuterRadiusSpinBox.value = 36.0
    #moldMeasurementsFormLayout.addRow("Skirt outer radius (mm):", self.skirtOuterRadiusSpinBox)
    skirtParametersBox.addWidget(self.skirtOuterRadiusSpinBox)

    moldMeasurementsFormLayout.addRow(skirtParametersBox)

    # Mold Height Selectors
    moldHeightsBox = qt.QHBoxLayout()

    self.moldTopHeightLabel = qt.QLabel('Top mold height (mm):')
    moldHeightsBox.addWidget(self.moldTopHeightLabel)

    self.moldTopHeightSpinBox = qt.QDoubleSpinBox()
    self.moldTopHeightSpinBox.setToolTip("Height of the top mold (in mm). Adjust based on valve segmentation.")
    self.moldTopHeightSpinBox.minimum = 10.0
    self.moldTopHeightSpinBox.maximum = 30.0
    self.moldTopHeightSpinBox.value = 12.0
    #moldMeasurementsFormLayout.addRow("Top mold height (mm):", self.moldTopHeightSpinBox)
    moldHeightsBox.addWidget(self.moldTopHeightSpinBox)

    self.moldBottomHeightLabel = qt.QLabel('Bottom mold height (mm):')
    moldHeightsBox.addWidget(self.moldBottomHeightLabel)

    self.moldBottomHeightSpinBox = qt.QDoubleSpinBox()
    self.moldBottomHeightSpinBox.setToolTip("Height of the bottom mold (in mm). Adjust based on valve segmentation.")
    self.moldBottomHeightSpinBox.minimum = 6.0
    self.moldBottomHeightSpinBox.maximum = 30.0
    self.moldBottomHeightSpinBox.value = 18.0
    #moldMeasurementsFormLayout.addRow("Bottom mold height (mm):", self.moldBottomHeightSpinBox)
    moldHeightsBox.addWidget(self.moldBottomHeightSpinBox)

    moldMeasurementsFormLayout.addRow(moldHeightsBox)

    #Wedge and border height selector

    wedgeAndBorderHeightsBox = qt.QHBoxLayout()

    self.wedgeHeightLabel = qt.QLabel('Wedge height (mm):')
    wedgeAndBorderHeightsBox.addWidget(self.wedgeHeightLabel)

    self.wedgeHeightSpinBox = qt.QDoubleSpinBox()
    self.wedgeHeightSpinBox.setToolTip("Height of the wedge between top and bottom molds. Adjust by preference.")
    self.wedgeHeightSpinBox.minimum = 0.0
    self.wedgeHeightSpinBox.maximum = 15.0
    self.wedgeHeightSpinBox.value = 10.0
    #moldMeasurementsFormLayout.addRow("Wedge height (mm):", self.wedgeHeightSpinBox)
    wedgeAndBorderHeightsBox.addWidget(self.wedgeHeightSpinBox)

    self.borderHeightLabel = qt.QLabel('Border height (mm):')
    wedgeAndBorderHeightsBox.addWidget(self.borderHeightLabel)

    self.borderHeightSpinBox = qt.QDoubleSpinBox()
    self.borderHeightSpinBox.setToolTip("Height of the border attached to the bottom mold. Adjust by preference.")
    self.borderHeightSpinBox.minimum = 0.0
    self.borderHeightSpinBox.maximum = 20.0
    self.borderHeightSpinBox.value = 6.0
    wedgeAndBorderHeightsBox.addWidget(self.borderHeightSpinBox)

    moldMeasurementsFormLayout.addRow(wedgeAndBorderHeightsBox)

    # Buttons
    self.growLeafletsFromTopSurfaceButton = qt.QPushButton("1) Grow leaflets from extracted top surface")
    moldMeasurementsFormLayout.addRow(self.growLeafletsFromTopSurfaceButton)
    self.growLeafletsFromTopSurfaceButton.connect('clicked(bool)', self.onGrowLeafletsFromTopSurface)

    self.placeButton = qt.QPushButton("2) Generate rim and skirt around valve")
    moldMeasurementsFormLayout.addRow(self.placeButton)
    self.placeButton.connect('clicked(bool)', self.onCreateMoldModels)

    self.combineMoldPartsButton = qt.QPushButton("3) Combine mold parts to create top and bottom molds")
    moldMeasurementsFormLayout.addRow(self.combineMoldPartsButton)
    self.combineMoldPartsButton.connect('clicked(bool)', self.onCombineSegmentPartsToCreateMoldWithAutomaticMoldSeparation)

    self.exportFinalSegmentsAsModelsButton = qt.QPushButton("4) Export 'Final' top, bottom, phantom segments as models")
    self.exportFinalSegmentsAsModelsButton.setToolTip ("Use this if the 'Final' segments needed manual editing")
    moldMeasurementsFormLayout.addRow(self.exportFinalSegmentsAsModelsButton)
    self.exportFinalSegmentsAsModelsButton.connect('clicked(bool)', self.onExportFinalSegmentsAsModels)

    # #test air tunnels
    # self.testAirTunnelsButton = qt.QPushButton("Test Air Tubes with Reservoir")
    # moldMeasurementsFormLayout.addRow(self.testAirTunnelsButton)
    # self.testAirTunnelsButton.connect('clicked(bool)', self.onTestAirTunnels) # TEMPORARY

    # #test orientation markers
    # self.testOrientationMarkersTSPButton = qt.QPushButton("Test Orientation Markers using TSP")
    # moldMeasurementsFormLayout.addRow(self.testOrientationMarkersTSPButton)
    # self.testOrientationMarkersTSPButton.connect('clicked(bool)', self.onTestOrientationMarkersTSP) # TEMPORARY

    # Add vertical spacer
    self.layout.addStretch(1)

    # Define list of widgets for updateGUIFromParameterNode, updateParameterNodeFromGUI, and addGUIObservers
    self.valueEditWidgets = {} #{"ClipOutsideSurface": self.clipOutsideSurfaceCheckBox, "FillValue": self.fillValueEdit}
    self.nodeSelectorWidgets = {"HeartValve": self.heartValveSelector}

    # Use singleton parameter node (it is created if does not exist yet)
    parameterNode = self.logic.getParameterNode()
    # Set parameter node (widget will observe it and also updates GUI)
    self.setAndObserveParameterNode(parameterNode)

    self.addGUIObservers()

  def cleanup(self):
    # Exit from any special workflow step
    self.removeGUIObservers()
    self.setAndObserveParameterNode(None)

  def updateGuiEnabled(self):
    valveModuleSelected = self.valveModel is not None
    volumeSelected = self.valveModel is not None and self.valveModel.getValveVolumeNode() is not None
    self.moldMeasurementsCollapsibleButton.setEnabled(valveModuleSelected)

  def getAnnulusContourModelNode(self):
    if self.valveModel is None:
      return None
    return self.valveModel.getAnnulusContourModelNode()

  def setAndObserveParameterNode(self, parameterNode):
    if parameterNode == self.parameterNode and self.parameterNodeObserver:
      # no change and node is already observed
      return
    # Remove observer to old parameter node
    if self.parameterNode and self.parameterNodeObserver:
      self.parameterNode.RemoveObserver(self.parameterNodeObserver)
      self.parameterNodeObserver = None
    # Set and observe new parameter node
    self.parameterNode = parameterNode
    if self.parameterNode:
      self.parameterNodeObserver = self.parameterNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onParameterNodeModified)
    # Update GUI
    self.updateGUIFromParameterNode()

  def getParameterNode(self):
    return self.parameterNode

  def onParameterNodeModified(self, observer, eventid):
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self):
    parameterNode = self.getParameterNode()
    if not parameterNode:
      return
    for parameterName in self.valueEditWidgets:
      oldBlockSignalsState = self.valueEditWidgets[parameterName].blockSignals(True)
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName=="QCheckBox":
        checked = (int(parameterNode.GetParameter(parameterName)) != 0)
        self.valueEditWidgets[parameterName].setChecked(checked)
      elif widgetClassName=="QSpinBox":
        self.valueEditWidgets[parameterName].setValue(float(parameterNode.GetParameter(parameterName)))
      else:
        raise Exception("Unexpected widget class: {0}".format(widgetClassName))
      self.valueEditWidgets[parameterName].blockSignals(oldBlockSignalsState)
    for parameterName in self.nodeSelectorWidgets:
      oldBlockSignalsState = self.nodeSelectorWidgets[parameterName].blockSignals(True)
      self.nodeSelectorWidgets[parameterName].setCurrentNodeID(parameterNode.GetNodeReferenceID(parameterName))
      self.nodeSelectorWidgets[parameterName].blockSignals(oldBlockSignalsState)

  def updateParameterNodeFromGUI(self):
    parameterNode = self.getParameterNode()
    oldModifiedState = parameterNode.StartModify()
    for parameterName in self.valueEditWidgets:
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName=="QCheckBox":
        if self.valueEditWidgets[parameterName].checked:
          parameterNode.SetParameter(parameterName, "1")
        else:
          parameterNode.SetParameter(parameterName, "0")
      elif widgetClassName=="QSpinBox":
        parameterNode.SetParameter(parameterName, str(self.valueEditWidgets[parameterName].value))
      else:
        raise Exception("Unexpected widget class: {0}".format(widgetClassName))
    for parameterName in self.nodeSelectorWidgets:
      parameterNode.SetNodeReferenceID(parameterName, self.nodeSelectorWidgets[parameterName].currentNodeID)
    parameterNode.EndModify(oldModifiedState)

  def addGUIObservers(self):
    for parameterName in self.valueEditWidgets:
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName=="QSpinBox":
        self.valueEditWidgets[parameterName].connect("valueChanged(int)", self.updateParameterNodeFromGUI)
      elif widgetClassName=="QCheckBox":
        self.valueEditWidgets[parameterName].connect("clicked()", self.updateParameterNodeFromGUI)
    for parameterName in self.nodeSelectorWidgets:
      self.nodeSelectorWidgets[parameterName].connect("currentNodeIDChanged(QString)", self.updateParameterNodeFromGUI)

  def removeGUIObservers(self):
    for parameterName in self.valueEditWidgets:
      widgetClassName = self.valueEditWidgets[parameterName].metaObject().className()
      if widgetClassName=="QSpinBox":
        self.valueEditWidgets[parameterName].disconnect("valueChanged(int)", self.updateParameterNodeFromGUI)
      elif widgetClassName=="QCheckBox":
        self.valueEditWidgets[parameterName].disconnect("clicked()", self.updateParameterNodeFromGUI)
    for parameterName in self.nodeSelectorWidgets:
      self.nodeSelectorWidgets[parameterName].disconnect("currentNodeIDChanged(QString)", self.updateParameterNodeFromGUI)

  def onHeartValveSelect(self, node):
    logging.debug(f"Selected heart valve node: {node.GetName() if node else 'None'}")

    # Go to display step before switching to another valve
    self.setHeartValveNode(node)
    self.updateGuiEnabled()

  def setHeartValveNode(self, heartValveNode):
    import HeartValveLib
    if self.valveModel and self.valveModel.getHeartValveNode() == heartValveNode:
      return

    self.valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)
    self.initializeMoldSegmentation()

    if self.valveModel:
      self.leafletIDs = self.getLeafletIDs()

    self.updateGuiEnabled()

  def initializeMoldSegmentation(self):
    if not self.valveModel.heartValveNode:
      logging.error("setMoldSegmentationNode failed: invalid heartValveNode")
      return

    if not self.getMoldSegmentationNode():
      logging.debug("Did not find leaflet segmentation node, create a new one")

      segmentationNode = self.logic.cloneMRMLNode(self.valveModel.getLeafletSegmentationNode())
      segmentationNode.SetName("MoldSegmentation")
      segmentationNode.CreateDefaultDisplayNodes()
      self.valveModel.heartValveNode.SetNodeReferenceID("MoldSegmentation",
                                                        segmentationNode.GetID() if segmentationNode else None)

  def getMoldSegmentationNode(self):
    return self.valveModel.heartValveNode.GetNodeReference("MoldSegmentation") if self.valveModel.heartValveNode else None

  # if not self.getLeafletSegmentationNode():
  #   logging.debug("Did not find leaflet sgementation node, create a new one")
  #   self.setLeafletSegmentationNode(self.createLeafletSegmentationNode())

  ## before, used self.valveModel.getLeafletSegmentationNode()

  # Rim contour line
  def getValveRimModelNode(self):
    return self.valveModel.heartValveNode.GetNodeReference("valveRim") if self.valveModel.heartValveNode else None

  # def copySegmentationColourNode(self, sourceLabelNode, destinationLabelNode):
  #   destinationLabelNode.GetDisplayNode().SetAndObserveColorNodeID(sourceLabelNode.GetDisplayNode().GetColorNodeID())

  def setValveRimModelNode(self, modelNode):
    if not self.valveModel.heartValveNode:
      logging.error("setvalveRimModelNode failed: invalid heartValveNode")
      return
    self.valveModel.heartValveNode.SetNodeReferenceID("valveRim", modelNode.GetID() if modelNode else None)
    if modelNode:
      probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
      modelNode.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

  def createValveRimModelNode(self):
    modelsLogic = slicer.modules.models.logic()
    polyData = vtk.vtkPolyData()
    modelNode = modelsLogic.AddModel(polyData)
    #modelNode.SetName(slicer.mrmlScene.GetUniqueNameByString("valveRimModel"))
    modelNode.SetName("valveRim")
    self.valveModel.moveNodeToHeartValveFolder(modelNode)
    modelNode.GetDisplayNode().SetColor(0.5, 0, 0.5)  # rgb pink
    return modelNode

  # annulusContourCurve replaced with valveRim everywhere

  # Annulus contour points
  def getValveRimMarkupNode(self):
    return self.valveModel.heartValveNode.GetNodeReference("valveRimPoints") if self.valveModel.heartValveNode else None

  def setValveRimMarkupNode(self, valveRimMarkupNode):
    if not self.valveModel.heartValveNode:
      logging.error("setvalveRimMarkupNode failed: invalid heartValveNode")
      return
    self.valveModel.heartValveNode.SetNodeReferenceID("valveRimPoints",
                                            valveRimMarkupNode.GetID() if valveRimMarkupNode else None)
    if valveRimMarkupNode:
      probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
      valveRimMarkupNode.SetAndObserveTransformNodeID(
        probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

  def createValveRimMarkupNode(self):
    # i could change 'annulus' to 'valveRim' here but no point since we're just returning a node
    markupsLogic = slicer.modules.markups.logic()
    valveRimMarkupNodeId = markupsLogic.AddNewFiducialNode()
    valveRimMarkupNode = slicer.mrmlScene.GetNodeByID(valveRimMarkupNodeId)
    valveRimMarkupNode.SetName(slicer.mrmlScene.GetUniqueNameByString("valveRimMarkup"))
    valveRimMarkupNode.SetMarkupLabelFormat("")  # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
    self.valveModel.moveNodeToHeartValveFolder(valveRimMarkupNode)
    valveRimMarkupDisplayNode = valveRimMarkupNode.GetDisplayNode()  # .SetColor(51,255,51)# rgb green
    valveRimMarkupDisplayNode.SetGlyphScale(self.valveModel.defaultAnnulusContourRadius * self.valveModel.annulusContourMarkupScale * 2)
    valveRimMarkupDisplayNode.SetColor(50, 255, 0.3)  # rgb pale yellow
    valveRimMarkupDisplayNode.SetVisibility(False) # added this
    return valveRimMarkupNode

  #flat wide skirt around rim
  def getValveSkirtModelNode(self):
    return self.valveModel.heartValveNode.GetNodeReference("valveSkirt") if self.valveModel.heartValveNode else None


  def setValveRimDefaults(self, valveRim):
    import HeartValveLib
    from HeartValveLib import SmoothCurve
    rimRadius = self.rimSizeSpinBox.value  # used to be 3
    valveRim.setInterpolationMethod(SmoothCurve.InterpolationSpline)
    valveRim.setClosed(True)
    valveRim.setTubeRadius(rimRadius)
    valveRim.setCurveModelNode(None)
    valveRim.controlPointsMarkupNode = None

  # calculates the factor by which you have to multiply the annulus points in plane
  # to shift them out so the inner edge of the rim is at the center of the annulus
  def calculateShiftFactor(self, annulusPlanePoints, sizeToShrink):
    # calculate length of each point/vector
    lengthsArray = np.sqrt((annulusPlanePoints ** 2).sum(axis=0))
    averageLength = np.average(lengthsArray)  # assuming this is in mm. Is this correct?
    shiftFactor = (averageLength + sizeToShrink) / averageLength
    return shiftFactor

  def getAverageValveRadius(self):
    import HeartValveLib
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    numberOfPoints = annulusControlPoints.shape[1]
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    transformWorldToPlaneMatrix = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    # Move annulus control points to valve plane
    annulusControlPoints_World = np.row_stack((annulusControlPoints, np.ones(numberOfPoints)))
    annulusControlPoints_Plane = np.dot(transformWorldToPlaneMatrix, annulusControlPoints_World)
    annulusControlPoints_Plane = annulusControlPoints_Plane[0:3, :]
    # calculate length of each point/vector and take average
    lengthsArray = np.sqrt((annulusControlPoints_Plane ** 2).sum(axis=0))
    averageLength = np.average(lengthsArray)
    return averageLength

  def createRimTube(self):
    import HeartValveLib
    from HeartValveLib import SmoothCurve
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    numberOfPoints = annulusControlPoints.shape[1]
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    transformWorldToPlaneMatrix = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    valveRim = SmoothCurve.SmoothCurve()
    self.setValveRimDefaults(valveRim)
    # STEP 1: Move annulus control points to valve plane
    # Concatenate a 4th line containing 1s so that we can transform the positions using
    # a single matrix multiplication.
    annulusControlPoints_World = np.row_stack((annulusControlPoints, np.ones(numberOfPoints)))
    # Control point positions in the plane coordinate system
    annulusControlPoints_Plane = np.dot(transformWorldToPlaneMatrix, annulusControlPoints_World)
    # remove the last row (all ones)
    annulusControlPoints_Plane = annulusControlPoints_Plane[0:3, :]
    # after translation center is negligible; very close to [0,0,0]
    # STEP 2: Shift points outwards so that inner edge of rim is at center of annulus
    rimControlPoints_Plane = np.empty((3, numberOfPoints,))
    rimControlPoints_Plane[:] = np.NAN
    # move it out by tubeRadius mm, then bring it back in by shrinkRim mm ######################################
    shiftFactor = self.calculateShiftFactor(annulusControlPoints_Plane, valveRim.tubeRadius - self.shrinkRimSpinBox.value)
    rimControlPoints_Plane[0:2, :] = shiftFactor * annulusControlPoints_Plane[0:2, :]
    rimControlPoints_Plane[2, :] = annulusControlPoints_Plane[2, :]  # do not scale z axis
    # STEP 3: Move shifted points back to original plane
    rimControlPoints_Plane = np.row_stack((rimControlPoints_Plane, np.ones(numberOfPoints)))
    rimControlPoints_World = np.dot(np.linalg.inv(transformWorldToPlaneMatrix), rimControlPoints_Plane)
    rimControlPoints_World = rimControlPoints_World[0:3, :]

    if slicer.mrmlScene.GetFirstNodeByName("valveRim"):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName("valveRim"))
    self.setValveRimModelNode(self.createValveRimModelNode())
    #
    valveRim.setCurveModelNode(self.getValveRimModelNode())  # moved here from end of setvalveRimModelNode
    # setting valve.controlPointsMarkupNode
    if not slicer.mrmlScene.GetFirstNodeByName("valveRimMarkup"):
      self.setValveRimMarkupNode(self.createValveRimMarkupNode())
    else:
      self.setValveRimMarkupNode(self.getValveRimMarkupNode())
    valveRim.setControlPointsMarkupNode(self.getValveRimMarkupNode())  # moved here from end of SetvalveRimMarkupNode
    valveRim.setControlPointsFromArray(rimControlPoints_World)
    valveRim.updateCurve()
    return valveRim

  #If needed, shrink the rim/skirt to close the gap between rim and grown leaflets
  #temporary fix, until surface extraction of leaflets is improved
  #todo: finish this
  def shrinkTargetPoints(self, points, numberOfPoints, sizeToShrink):
    #transform points to plane
    #bring them in towards the center of gravity
    #transform back to 3D

    #similar to what is done in createSkirt function above
    import HeartValveLib
    annulusControlPoints = points
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    transformWorldToPlaneMatrix = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    # STEP 1: Move annulus control points to valve plane
    annulusControlPoints_World = np.row_stack((annulusControlPoints, np.ones(numberOfPoints)))
    annulusControlPoints_Plane = np.dot(transformWorldToPlaneMatrix, annulusControlPoints_World)
    annulusControlPoints_Plane = annulusControlPoints_Plane[0:3, :]
    # after translation center is negligible; very close to [0,0,0]
    # STEP 2: Shift points outwards so that inner edge of rim is at center of annulus
    #shift rim inwards to delete gap between grown leaflets and rim
    rimControlPoints_Plane = np.empty((3, numberOfPoints,))
    rimControlPoints_Plane[:] = np.NAN
    shiftFactor = self.calculateShiftFactor(annulusControlPoints_Plane, -sizeToShrink)
    rimControlPoints_Plane[0:2, :] = shiftFactor * annulusControlPoints_Plane[0:2, :]
    rimControlPoints_Plane[2, :] = annulusControlPoints_Plane[2, :]
    # STEP 3: Move shifted points back to original plane
    rimControlPoints_Plane = np.row_stack((rimControlPoints_Plane, np.ones(numberOfPoints)))
    rimControlPoints_World = np.dot(np.linalg.inv(transformWorldToPlaneMatrix), rimControlPoints_Plane)
    rimControlPoints_World = rimControlPoints_World[0:3, :]

    return rimControlPoints_World

  def createRimStiffener(self, valveRimTopHeight, valveRimBottomHeight):
    import HeartValveLib
    from HeartValveLib import SmoothCurve
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    numberOfPoints = annulusControlPoints.shape[1]
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    transformWorldToPlaneMatrix = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    numberOfLandmarkPoints = 80
    ProbeToAnnulusTransform = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    AnnulusToProbeTransform = np.linalg.inv(ProbeToAnnulusTransform)

    # generate a circle with radius 'averageValveRadius' and find closest point on annulusContour for each point
    averageValveRadius = self.getAverageValveRadius()
    valveRadiusSizeCirclePoints_Annulus = np.empty((4,numberOfLandmarkPoints,))
    closestCorrespondingAnnulusPoints_Probe = np.empty((4, numberOfLandmarkPoints,))
    # get points for a circle with radius 'averageValveRadius' (in Annulus plane)
    for pointIndex in range(numberOfLandmarkPoints):
      angle = float(pointIndex) / numberOfLandmarkPoints * 2.0 * math.pi
      pointOnCircle = [averageValveRadius*math.cos(angle), averageValveRadius*math.sin(angle),0,1]
      valveRadiusSizeCirclePoints_Annulus[:,pointIndex] = pointOnCircle
    # convert circle points to Probe plane
    valveRadiusSizeCirclePoints_Probe = np.dot(AnnulusToProbeTransform, valveRadiusSizeCirclePoints_Annulus)
    # find the corresponding closest points on the annulus (in Probe plane)
    for pointIndex in range(numberOfLandmarkPoints):
      pointOnCircle = valveRadiusSizeCirclePoints_Probe[0:3,pointIndex]
      [closestCorrespondingAnnulusPoints_Probe[0:3,pointIndex], _] = self.valveModel.annulusContourCurve.getClosestPoint(pointOnCircle)
      closestCorrespondingAnnulusPoints_Probe[3,pointIndex] = 1

    ###########
    if self.shrinkRimSpinBox.value > 0:
      closestCorrespondingAnnulusPointsShrunk = self.shrinkTargetPoints(closestCorrespondingAnnulusPoints_Probe[0:3], numberOfLandmarkPoints, self.shrinkRimSpinBox.value)
    else:
      closestCorrespondingAnnulusPointsShrunk = closestCorrespondingAnnulusPoints_Probe[0:3,:]
    ##########

    sourceLandmarkPoints = vtk.vtkPoints()
    sourceLandmarkPoints.SetNumberOfPoints(numberOfLandmarkPoints)
    targetLandmarkPoints = vtk.vtkPoints()
    targetLandmarkPoints.SetNumberOfPoints(numberOfLandmarkPoints)

    # set inner source/target points
    for pointIndex in range(numberOfLandmarkPoints):
      angle = float(pointIndex) / numberOfLandmarkPoints * 2.0 * math.pi  # angles evenly spaced around a circle (2*pi)
      sourceLandmarkPoints.SetPoint(pointIndex, math.cos(angle), math.sin(angle), 0)  # disk source point at that angle
      targetLandmarkPoints.SetPoint(numberOfLandmarkPoints - 1 - pointIndex, closestCorrespondingAnnulusPointsShrunk[:,pointIndex])

    # set up transform matrix for nonlinear warping to fit to shape
    tsp = vtk.vtkThinPlateSplineTransform()
    tsp.SetSourceLandmarks(sourceLandmarkPoints)
    tsp.SetTargetLandmarks(targetLandmarkPoints)

    unitDisk = vtk.vtkDiskSource()
    unitDisk.SetOuterRadius(1.2)
    unitDisk.SetInnerRadius(1.0)
    unitDisk.SetCircumferentialResolution(80)
    unitDisk.SetRadialResolution(15)
    #
    polyTransformToRim = vtk.vtkTransformPolyDataFilter()  # transforms points and associated normals and vectors
    polyTransformToRim.SetTransform(tsp)
    polyTransformToRim.SetInputConnection(unitDisk.GetOutputPort())
    #
    polyDataNormals = vtk.vtkPolyDataNormals()  # computes cell normals
    polyDataNormals.SetInputConnection(polyTransformToRim.GetOutputPort())
    # There are a few triangles in the triangulated unit disk with inconsistent
    # orientation. Enabling consistency check fixes them.
    polyDataNormals.ConsistencyOn()
    #
    extrusion = vtk.vtkLinearExtrusionFilter()
    extrusion.SetInputConnection(polyDataNormals.GetOutputPort()) # use GetOutput() to get vtkPolyData object (NOT GetOutputport())
    rimThickness = valveRimTopHeight + valveRimBottomHeight
    extrusion.SetScaleFactor(rimThickness)
    extrusion.SetExtrusionTypeToVectorExtrusion()
    extrusion.SetVector(planeNormal)
    extrusion.CappingOn()

    translateTransform = vtk.vtkTransform()
    planeNormalUnitVector = (1/np.linalg.norm(planeNormal))*planeNormal
    translateTransform.Translate(-planeNormalUnitVector * valveRimBottomHeight)

    polyTransformToRepositionRim = vtk.vtkTransformPolyDataFilter()
    polyTransformToRepositionRim.SetTransform(translateTransform)
    polyTransformToRepositionRim.SetInputConnection(extrusion.GetOutputPort())

    if slicer.mrmlScene.GetFirstNodeByName("valveRimStiffener"):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName("valveRimStiffener"))

    modelsLogic = slicer.modules.models.logic()
    rimModelNode = modelsLogic.AddModel(polyTransformToRepositionRim.GetOutputPort())
    rimModelNode.SetName("valveRimStiffener")
    self.valveModel.moveNodeToHeartValveFolder(rimModelNode)
    rimModelNode.GetDisplayNode().SetVisibility(True)
    rimModelNode.GetDisplayNode().SetColor(0.9, 0.3, 0.9)
    rimModelNode.GetDisplayNode().SetOpacity(1.0)  # can play with these settings
    rimModelNode.GetDisplayNode().SetAmbient(0.1)
    rimModelNode.GetDisplayNode().SetDiffuse(0.9)
    rimModelNode.GetDisplayNode().SetSpecular(0.1)
    rimModelNode.GetDisplayNode().SetPower(10)
    rimModelNode.GetDisplayNode().BackfaceCullingOff()
    #
    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    rimModelNode.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)
    #
    return rimModelNode

  def onTestOrientationMarkersTSP(self, pushed):
    valveRim = self.createRimTube()
    skirtOuterRadius = self.skirtOuterRadiusSpinBox.value # so diameter is 7.2cm
    skirtThickness = self.skirtThicknessSpinBox.value

    valveSkirt = self.makeSkirtAroundRim(valveRim, skirtOuterRadius, skirtThickness)
    return

  #returns the 'norm' or 'magnitude' of a vector
  def norm(self, vector):
    return math.sqrt(np.dot(vector, vector))

  # normalizes a vector so it is unit length
  def normalizeVector(self, vector): # should pass in a 3d vector, non-homogenized
    magnitude = self.norm(vector)
    return [vector[i]/magnitude for i in range(len(vector))]

  # project a vector onto a plane defined by it's normal
  def projectVectorOntoPlane(self, vector, planeNormal):
    # To project vector onto plane: project the vector onto the normal of the plane and subtract that from the vector.
    # formula at https://www.maplesoft.com/support/help/Maple/view.aspx?path=MathApps/ProjectionOfVectorOntoPlane
    scalingFactor = np.dot(vector, planeNormal)/self.norm(planeNormal)
    projectionOntoPlaneNormal = [scalingFactor * self.normalizeVector(planeNormal)[i] for i in range (len(planeNormal))]
    return [vector[i] - projectionOntoPlaneNormal[i] for i in range(len(vector))]

  def makeOrientationMarkerUsingSkirtWarp(self, markerText, markerRasVector, scaledDiskToProbeTspTransform):
    import HeartValveLib
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)

    # before warping, skirt had inner radius 'averageValveRadius' and outer radius 'skirtOuterRadius'
    skirtOuterRadius = self.skirtOuterRadiusSpinBox.value  # so diameter is 7.2cm
    letterSize = 5 #letters will be 5mm x 5mm
    distanceFromEdgeOfSkirt = letterSize + 2 # margin of 2mm
    distanceFromCenter = skirtOuterRadius - distanceFromEdgeOfSkirt # distance of orientation marker from center of valve, in mm

    vector_RAS = markerRasVector #initialize
    vector_Probe = [0.0, 0.0, 0.0, 0.0] #initialize

    # get rasToProbe transform
    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    rasToProbeMatrix = vtk.vtkMatrix4x4()
    probeToRasTransformNode.GetMatrixTransformFromWorld(rasToProbeMatrix)
    # apply rasToProbe transform
    rasToProbeMatrix.MultiplyPoint(vector_RAS, vector_Probe)
    directionVector_Probe = vector_Probe[0:3]

    #project the direction vector onto the skirt to get location for marker
    directionVectorProjectedOntoAnnulusPlane_Probe = self.projectVectorOntoPlane(directionVector_Probe, planeNormal)
    directionVectorProjectedOntoAnnulusPlane_Probe = self.normalizeVector(directionVectorProjectedOntoAnnulusPlane_Probe)
    #logging.debug ("directionVectorProjectedOntoAnnulusPlane_Probe", directionVectorProjectedOntoAnnulusPlane_Probe)
    ROrientationMarkerLocation_Probe = [
      planePosition[0] + directionVectorProjectedOntoAnnulusPlane_Probe[0] * distanceFromCenter,
      planePosition[1] + directionVectorProjectedOntoAnnulusPlane_Probe[1] * distanceFromCenter,
      planePosition[2] + directionVectorProjectedOntoAnnulusPlane_Probe[2] * distanceFromCenter]

    ROrientationMarkerLocation_scaledDisk = scaledDiskToProbeTspTransform.GetInverse().TransformPoint(ROrientationMarkerLocation_Probe)

    text = vtk.vtkVectorText()
    text.SetText(markerText)

    # scale marker and translate to desired location on skirt
    scaleAndTranslateTransform = vtk.vtkTransform()
    scaleAndTranslateTransform.Translate(ROrientationMarkerLocation_scaledDisk)
    scaleAndTranslateTransform.Scale(letterSize, letterSize, 1)  # letters will be 5mm large
    scaleAndTranslateTransform.Translate(-0.5, -0.5, 0)  # center the unit letter

    polyScaleTransform = vtk.vtkTransformPolyDataFilter()
    polyScaleTransform.SetTransform(scaleAndTranslateTransform)
    polyScaleTransform.SetInputConnection(text.GetOutputPort())

    # apply warp transform (same as applied to skirt)
    polyTransformToRim = vtk.vtkTransformPolyDataFilter()  # warps to skirt
    polyTransformToRim.SetTransform(scaledDiskToProbeTspTransform)
    polyTransformToRim.SetInputConnection(polyScaleTransform.GetOutputPort())

    # get normals
    polyDataNormals = vtk.vtkPolyDataNormals()  # computes cell normals
    polyDataNormals.SetInputConnection(polyTransformToRim.GetOutputPort())
    polyDataNormals.ConsistencyOn()

    # extrude the marker to underside of valve
    letterHeight = 2 * self.skirtThicknessSpinBox.value
    extrusion = vtk.vtkLinearExtrusionFilter()
    extrusion.SetScaleFactor(letterHeight)
    extrusion.SetInputConnection(polyDataNormals.GetOutputPort())
    extrusion.SetExtrusionTypeToVectorExtrusion()
    extrusion.SetVector(-planeNormal)
    extrusion.CappingOn()

    # create orientation marker model
    name = markerText + "OrientationMarker"

    if slicer.mrmlScene.GetFirstNodeByName(name):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(name))

    modelsLogic = slicer.modules.models.logic()
    markerModel = modelsLogic.AddModel(extrusion.GetOutputPort())
    markerModel.SetName(name)
    markerModel.GetDisplayNode().SetVisibility(True)
    markerModel.GetDisplayNode().SetColor([255, 0, 0])
    markerModel.GetDisplayNode().SetOpacity(1.0)

    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    markerModel.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

    self.valveModel.moveNodeToHeartValveFolder(markerModel)

    # add orientation marker to segmentation, set segment visibility to false
    self.addModelToMoldSegmentation(markerModel)
    segmentationNode = self.getMoldSegmentationNode()
    segmentationNode.GetDisplayNode().SetSegmentVisibility(name + "_seg", False)
    return

  def makeSkirtAroundRim(self, valveRim, skirtOuterRadius, skirtThickness):
    import HeartValveLib
    # import math
    numberOfLandmarkPoints = 80
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    ProbeToAnnulusTransform = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    AnnulusToProbeTransform = np.linalg.inv(ProbeToAnnulusTransform)
    # generate a circle with radius 'averageValveRadius' and find closest point on annulusContour for each point
    averageValveRadius = self.getAverageValveRadius()
    valveRadiusSizeCirclePoints_Annulus = np.empty((4,numberOfLandmarkPoints,))
    closestCorrespondingAnnulusPoints_Probe = np.empty((4, numberOfLandmarkPoints,))
    # get points for a circle with radius 'averageValveRadius' (in Annulus plane)
    for pointIndex in range(numberOfLandmarkPoints):
      angle = float(pointIndex) / numberOfLandmarkPoints * 2.0 * math.pi
      pointOnCircle = [averageValveRadius*math.cos(angle), averageValveRadius*math.sin(angle),0,1]
      valveRadiusSizeCirclePoints_Annulus[:,pointIndex] = pointOnCircle
    # convert circle points to Probe plane
    valveRadiusSizeCirclePoints_Probe = np.dot(AnnulusToProbeTransform, valveRadiusSizeCirclePoints_Annulus)
    # find the corresponding closest points on the annulus (in Probe plane)
    for pointIndex in range(numberOfLandmarkPoints):
      pointOnCircle = valveRadiusSizeCirclePoints_Probe[0:3,pointIndex]
      [closestCorrespondingAnnulusPoints_Probe[0:3,pointIndex], _] = self.valveModel.annulusContourCurve.getClosestPoint(pointOnCircle)
      closestCorrespondingAnnulusPoints_Probe[3,pointIndex] = 1

    if self.shrinkRimSpinBox.value > 0:
      closestCorrespondingAnnulusPointsShrunk_Probe = self.shrinkTargetPoints(closestCorrespondingAnnulusPoints_Probe[0:3], numberOfLandmarkPoints, self.shrinkRimSpinBox.value)
    else:
      closestCorrespondingAnnulusPointsShrunk_Probe = closestCorrespondingAnnulusPoints_Probe[0:3,:]

    annulusLandmarkPoints_ScaledDisk = vtk.vtkPoints()  # points on the unit disk
    annulusLandmarkPoints_ScaledDisk.SetNumberOfPoints(2*numberOfLandmarkPoints)
    annulusLandmarkPoints_Probe = vtk.vtkPoints()
    annulusLandmarkPoints_Probe.SetNumberOfPoints(2*numberOfLandmarkPoints)

    # set source/target points for inside of skirt
    for pointIndex in range(numberOfLandmarkPoints):
      angle = float(pointIndex) / numberOfLandmarkPoints * 2.0 * math.pi  # angles evenly spaced around a circle (2*pi)
      annulusLandmarkPoints_ScaledDisk.SetPoint(pointIndex, averageValveRadius*math.cos(angle), averageValveRadius*math.sin(angle), 0)  # disk source point at that angle
      annulusLandmarkPoints_Probe.SetPoint(numberOfLandmarkPoints - 1 - pointIndex, closestCorrespondingAnnulusPointsShrunk_Probe[:, pointIndex])

    # set source/target points for outside of skirt
    for pointIndex in range(numberOfLandmarkPoints):
      angle = float(pointIndex) / numberOfLandmarkPoints * 2.0 * math.pi  # angles evenly spaced around a circle (2*pi)
      annulusLandmarkPoints_ScaledDisk.SetPoint(numberOfLandmarkPoints + pointIndex, skirtOuterRadius*math.cos(angle), skirtOuterRadius*math.sin(angle), 0) # disk source point
      skirtOuterCircumferencePoint_Annulus = [skirtOuterRadius*math.cos(angle), skirtOuterRadius*math.sin(angle), 0, 1]
      skirtOuterCircumferencePoint_Probe = np.dot(AnnulusToProbeTransform,skirtOuterCircumferencePoint_Annulus)
      annulusLandmarkPoints_Probe.SetPoint(numberOfLandmarkPoints + (numberOfLandmarkPoints-1-pointIndex), skirtOuterCircumferencePoint_Probe[0:3]) # outer skirt target point

    scaledDiskToProbeTspTransform = vtk.vtkThinPlateSplineTransform()  # set up transform matrix for nonlinear warping to fit to shape
    scaledDiskToProbeTspTransform.SetSourceLandmarks(annulusLandmarkPoints_ScaledDisk)
    scaledDiskToProbeTspTransform.SetTargetLandmarks(annulusLandmarkPoints_Probe)
    #
    unitDisk = vtk.vtkDiskSource()
    #unitDisk.SetOuterRadius(2.0)
    #unitDisk.SetInnerRadius(1.0)
    unitDisk.SetOuterRadius(skirtOuterRadius)
    unitDisk.SetInnerRadius(averageValveRadius)
    unitDisk.SetCircumferentialResolution(80)
    unitDisk.SetRadialResolution(15)
    #
    polyTransformToRim = vtk.vtkTransformPolyDataFilter()  # transforms points and associated normals and vectors
    polyTransformToRim.SetTransform(scaledDiskToProbeTspTransform)
    polyTransformToRim.SetInputConnection(unitDisk.GetOutputPort())
    #
    polyDataNormals = vtk.vtkPolyDataNormals()  # computes cell normals
    polyDataNormals.SetInputConnection(polyTransformToRim.GetOutputPort())
    # There are a few triangles in the triangulated unit disk with inconsistent
    # orientation. Enabling consistency check fixes them.
    polyDataNormals.ConsistencyOn()
    #
    skirtExtrusion = vtk.vtkLinearExtrusionFilter()
    skirtExtrusion.SetInputConnection(polyDataNormals.GetOutputPort()) # use GetOutput() to get vtkPolyData object (NOT GetOutputport())
    skirtExtrusion.SetScaleFactor(skirtThickness)
    skirtExtrusion.SetExtrusionTypeToVectorExtrusion()
    skirtExtrusion.SetVector(planeNormal)
    skirtExtrusion.CappingOn()

    translateTransform = vtk.vtkTransform()
    planeNormalUnitVector = (1/np.linalg.norm(planeNormal))*planeNormal
    translateTransform.Translate(-planeNormalUnitVector*(skirtThickness/2))

    polyTransformToRepositionSkirt = vtk.vtkTransformPolyDataFilter()
    polyTransformToRepositionSkirt.SetTransform(translateTransform)
    polyTransformToRepositionSkirt.SetInputConnection(skirtExtrusion.GetOutputPort())

    if slicer.mrmlScene.GetFirstNodeByName("valveSkirt"):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName("valveSkirt"))

    modelsLogic = slicer.modules.models.logic()
    skirtModelNode = modelsLogic.AddModel(polyTransformToRepositionSkirt.GetOutputPort())
    skirtModelNode.SetName("valveSkirt")
    self.valveModel.moveNodeToHeartValveFolder(skirtModelNode)
    skirtModelNode.GetDisplayNode().SetVisibility(True)
    skirtModelNode.GetDisplayNode().SetColor(0.1, 0.3, 0.9)
    skirtModelNode.GetDisplayNode().SetOpacity(1.0)  # can play with these settings
    skirtModelNode.GetDisplayNode().SetAmbient(0.1)
    skirtModelNode.GetDisplayNode().SetDiffuse(0.9)
    skirtModelNode.GetDisplayNode().SetSpecular(0.1)
    skirtModelNode.GetDisplayNode().SetPower(10)
    skirtModelNode.GetDisplayNode().BackfaceCullingOff()
    #
    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    skirtModelNode.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)
    #
    self.makeOrientationMarkerUsingSkirtWarp("R", [1.0, 0.0, 0.0, 0.0], scaledDiskToProbeTspTransform)
    self.makeOrientationMarkerUsingSkirtWarp("S", [0.0, 0.0, 1.0, 0.0], scaledDiskToProbeTspTransform)
    #
    return skirtModelNode

  # makes a box shape around valve; this will be the shape of the outside of the mold
  # currently doesn't take valve segmentation min/max into account; add these later
  def makeMoldBoxModel(self, skirtOuterRadius, modelName, zMin, zMax, colour, boxLength): # later change to self
    import HeartValveLib
    moldBox = vtk.vtkCubeSource()
    moldBox.SetBounds(-boxLength/2.0, boxLength/2.0, -boxLength/2.0, boxLength/2.0,zMin,zMax)
    #
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    ProbeToAnnulusTransform = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    AnnulusToProbeTransform = np.linalg.inv(ProbeToAnnulusTransform)
    #
    rotateTransform = vtk.vtkTransform()
    rotateTransform.SetMatrix(np.ndarray.flatten(AnnulusToProbeTransform))
    #
    polyTransformToProbe = vtk.vtkTransformPolyDataFilter()
    polyTransformToProbe.SetTransform(rotateTransform)
    polyTransformToProbe.SetInputConnection(moldBox.GetOutputPort())
    #
    if slicer.mrmlScene.GetFirstNodeByName(modelName):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(modelName))
    #
    modelsLogic = slicer.modules.models.logic()
    moldBoxModel = modelsLogic.AddModel(polyTransformToProbe.GetOutputPort())
    moldBoxModel.SetName(modelName)
    moldBoxModel.GetDisplayNode().SetVisibility(True)
    moldBoxModel.GetDisplayNode().SetColor(colour)
    moldBoxModel.GetDisplayNode().SetOpacity(0.5)
    moldBoxModel = slicer.mrmlScene.GetFirstNodeByName(modelName)
    #
    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    moldBoxModel.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)
    #
    self.valveModel.moveNodeToHeartValveFolder(moldBoxModel)
    #
    return moldBoxModel

  def makeRectangularPrismModel(self, modelName, colour, xMin, xMax, yMin, yMax, zMin, zMax): # later change to self
    import HeartValveLib
    rectPrism = vtk.vtkCubeSource()
    rectPrism.SetBounds(xMin, xMax, yMin, yMax,zMin,zMax)
    #
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    ProbeToAnnulusTransform = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    AnnulusToProbeTransform = np.linalg.inv(ProbeToAnnulusTransform)
    #
    rotateTransform = vtk.vtkTransform()
    rotateTransform.SetMatrix(np.ndarray.flatten(AnnulusToProbeTransform))
    #
    polyTransformToProbe = vtk.vtkTransformPolyDataFilter()
    polyTransformToProbe.SetTransform(rotateTransform)
    polyTransformToProbe.SetInputConnection(rectPrism.GetOutputPort())
    #
    if slicer.mrmlScene.GetFirstNodeByName(modelName):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(modelName))
    #
    modelsLogic = slicer.modules.models.logic()
    rectPrismModel = modelsLogic.AddModel(polyTransformToProbe.GetOutputPort())
    rectPrismModel.SetName(modelName)
    rectPrismModel.GetDisplayNode().SetVisibility(False)
    rectPrismModel.GetDisplayNode().SetColor(colour)
    rectPrismModel.GetDisplayNode().SetOpacity(0.5)
    rectPrismModel = slicer.mrmlScene.GetFirstNodeByName(modelName)
    #
    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    rectPrismModel.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)
    #
    self.valveModel.moveNodeToHeartValveFolder(rectPrismModel)
    #
    return rectPrismModel

  #makes the triangular prisms that will be part of the bottom mold (to prevent silicon from spilling out)
  def makeTriangularBoundariesForMoldBox(self, modelName, point1, point2, point3, extrusionDirectionVector, colour, boxLength): # later change to self
    import HeartValveLib

    trianglePolyData = vtk.vtkPolyData()
    numPoints = 3

    #make line
    newLine = vtk.vtkCellArray()
    newLine.InsertNextCell(numPoints+1)
    newLine.InsertCellPoint(0)
    newLine.InsertCellPoint(1)
    newLine.InsertCellPoint(2)
    newLine.InsertCellPoint(0) # close the polygon
    trianglePolyData.SetLines(newLine)

    #make poly
    newPoly = vtk.vtkCellArray()
    newPoly.InsertNextCell(numPoints)
    newPoly.InsertCellPoint(0)
    newPoly.InsertCellPoint(1)
    newPoly.InsertCellPoint(2)
    trianglePolyData.SetPolys(newPoly)

    #set points
    trianglePoints_Annulus = vtk.vtkPoints()
    trianglePoints_Annulus.InsertNextPoint(point1)
    trianglePoints_Annulus.InsertNextPoint(point2)
    trianglePoints_Annulus.InsertNextPoint(point3)
    trianglePolyData.SetPoints(trianglePoints_Annulus)

    # extrude triangle to make a triangular prism
    triangleExtrusion = vtk.vtkLinearExtrusionFilter()
    triangleExtrusion.SetInputDataObject(trianglePolyData)
    triangleExtrusion.SetScaleFactor(boxLength)
    triangleExtrusion.SetExtrusionTypeToVectorExtrusion()
    triangleExtrusion.SetVector(extrusionDirectionVector)
    triangleExtrusion.CappingOn()

    # Get ProbeToAnnulus and AnnulusToProve transforms
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    ProbeToAnnulusTransform = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    AnnulusToProbeTransform = np.linalg.inv(ProbeToAnnulusTransform)

    #set AnnulusToProbe transform
    rotateTransform = vtk.vtkTransform()
    rotateTransform.SetMatrix(np.ndarray.flatten(AnnulusToProbeTransform)) # passes the transform matrix as a 1D array

    polyTransformToProbe = vtk.vtkTransformPolyDataFilter()
    polyTransformToProbe.SetTransform(rotateTransform)
    polyTransformToProbe.SetInputConnection(triangleExtrusion.GetOutputPort())

    if slicer.mrmlScene.GetFirstNodeByName(modelName):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(modelName))

    modelsLogic = slicer.modules.models.logic()
    triangleModel = modelsLogic.AddModel(polyTransformToProbe.GetOutputPort())
    triangleModel.SetName(modelName)
    triangleModel.GetDisplayNode().SetVisibility(True)
    triangleModel.GetDisplayNode().SetColor(colour)
    triangleModel.GetDisplayNode().SetOpacity(0.8)

    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    triangleModel.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

    self.valveModel.moveNodeToHeartValveFolder(triangleModel)

    return triangleModel

  # leaflet name not always same as leafletID
  def getLeafletNameFromID(self, leafletID):
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.getMoldSegmentationNode()
    leafletName = segmentationNode.GetSegmentation().GetSegment(leafletID).GetName()
    return leafletName

  def getLeafletIDs(self):
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.getMoldSegmentationNode()
    numberOfSegments = segmentationNode.GetSegmentation().GetNumberOfSegments()  #the 0th segment is 'ValveMask', not considered a leaflet
    segmentIDs = vtk.vtkStringArray()
    segmentationNode.GetSegmentation().GetSegmentIDs(segmentIDs)
    leafletIDs = []

    for index in range(0,numberOfSegments):
      nameOfSegment = self.getLeafletNameFromID(segmentIDs.GetValue(index))
      if "leaflet" in nameOfSegment and "Grown model" not in nameOfSegment:
        leafletIDs.append(segmentIDs.GetValue(index))
    return leafletIDs

  def addModelToMoldSegmentation(self, modelNode):
    import vtkSegmentationCorePython as vtkSegmentationCore

    #set up segment settings
    #segmentationNode = self.valveModel.getLeafletSegmentationNode()
    segmentationNode = self.getMoldSegmentationNode()
    logging.debug("Mold segmentation node:")
    logging.debug(segmentationNode)
    modelDisplayNode = modelNode.GetDisplayNode()
    color = modelDisplayNode.GetColor()
    segment = vtkSegmentationCore.vtkSegment()
    segmentName = modelNode.GetName() + "_seg"
    segment.SetName(segmentName)
    segment.SetColor(color)

    # transform the segment to proper location
    modelToSegmentationTransform = vtk.vtkGeneralTransform()
    slicer.vtkMRMLTransformNode().GetTransformBetweenNodes(modelNode.GetParentTransformNode(),
                                                           segmentationNode.GetParentTransformNode(),
                                                           modelToSegmentationTransform)
    transformFilter = vtk.vtkTransformPolyDataFilter()
    transformFilter.SetInputData(modelNode.GetPolyData())
    transformFilter.SetTransform(modelToSegmentationTransform)
    transformFilter.Update()

    # copy model polydata to segment
    polyDataCopy = vtk.vtkPolyData()
    polyDataCopy.DeepCopy(modelNode.GetPolyData())
    segment.AddRepresentation(vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName(),
                              polyDataCopy)
    #segmentationNode.GetSegmentation().SetMasterRepresentationName('Closed surface')
    segmentationNode.GetSegmentation().SetMasterRepresentationName(vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName())

    if slicer.mrmlScene.GetFirstNodeByName(segmentName):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(segmentName))

    segmentationNode.GetSegmentation().AddSegment(segment)

    segmentationDisplayNode = segmentationNode.GetDisplayNode()
    segmentationDisplayNode.SetSegmentVisibility(segmentName, True) #might not be necessary

  def createModelFromSegment(self, segmentID):
    import vtkSegmentationCorePython as vtkSegmentationCore

    segmentationNode = self.getMoldSegmentationNode()
    segment = segmentationNode.GetSegmentation().GetSegment(segmentID)

    # If the model by that name already exists, delete it
    if slicer.mrmlScene.GetNodeByID(segmentID.strip('_seg')):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetNodeByID(segmentID.strip('_seg')))

    # Add a model to the scene... porting qSlicerSegmentationsModuleWidget::onAddModel()...
    scene = slicer.mrmlScene
    modelNode = slicer.vtkMRMLModelNode()
    scene.AddNode(modelNode)

    modelNode.SetName(segmentID.strip('_seg'))
    parentTransformNode = segmentationNode.GetParentTransformNode()

    # Check that a closed surface representation exists
    closedSurfacePresent = segmentationNode.GetSegmentation().CreateRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName())

    # Export binary labelmap representation into labelmap volume node
    polyData = segment.GetRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName())
    polyDataCopy = vtk.vtkPolyData()
    polyDataCopy.DeepCopy(polyData)  # Make copy of poly data so that the model node does not change if segment changes
    modelNode.SetAndObservePolyData(polyDataCopy)

    # Set color of the exported model
    segmentationDisplayNode = segmentationNode.GetDisplayNode()

    # create model display node
    displayNode = slicer.vtkMRMLModelDisplayNode()
    displayNode = modelNode.GetScene().AddNode(displayNode)
    displayNode.VisibilityOn()
    modelNode.SetAndObserveDisplayNodeID(displayNode.GetID())
    modelDisplayNode = displayNode
    segmentColor = segmentationDisplayNode.GetSegmentColor(segment.GetName())
    modelDisplayNode.SetColor(segmentColor)

    # Set segmentation's parent transform to exported node
    modelNode.SetAndObserveTransformNodeID(parentTransformNode.GetID())

  def createEmptySegment(self, segmentName):
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.getMoldSegmentationNode()
    segment = vtkSegmentationCore.vtkSegment()
    segment.SetName(segmentName)

    if slicer.mrmlScene.GetFirstNodeByName(segmentName):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(segmentName))

    segmentationNode.GetSegmentation().AddSegment(segment)

    segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentName, False)

  def setMasterRepresentationToBinaryLabelmap(self):
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.getMoldSegmentationNode()

    # if the master representation is already binary labelmap, do nothing
    if segmentationNode.GetSegmentation().GetMasterRepresentationName() == \
        vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName():
      return

    # Re-creating closed surface if it was present before, so that changes can be seen.
    closedSurfacePresent = segmentationNode.GetSegmentation().CreateRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())

    #create binary labelmap representation
    segmentationNode.GetSegmentation().CreateRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())

    segmentationNode.GetSegmentation().SetMasterRepresentationName(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())

    if closedSurfacePresent:
      segmentationNode.GetSegmentation().CreateRepresentation(
        vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName())

    # Show binary labelmap in 2D
    displayNode = segmentationNode.GetDisplayNode()
    displayNode.SetPreferredDisplayRepresentationName2D(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())

  def getInvertedBinaryLabelmap(self, modifierLabelmap):
    import vtkSegmentationCorePython as vtkSegmentationCore

    fillValue = 1
    eraseValue = 0
    inverter = vtk.vtkImageThreshold()
    inverter.SetInputData(modifierLabelmap)
    inverter.SetInValue(fillValue)
    inverter.SetOutValue(eraseValue)
    inverter.ReplaceInOn()
    inverter.ThresholdByLower(0)
    inverter.SetOutputScalarType(vtk.VTK_UNSIGNED_CHAR)
    inverter.Update()

    invertedModifierLabelmap = vtkSegmentationCore.vtkOrientedImageData()
    invertedModifierLabelmap.ShallowCopy(inverter.GetOutput())
    imageToWorldMatrix = vtk.vtkMatrix4x4()
    modifierLabelmap.GetImageToWorldMatrix(imageToWorldMatrix)
    invertedModifierLabelmap.SetGeometryFromImageToWorldMatrix(imageToWorldMatrix)
    return invertedModifierLabelmap

    #todo: i should be doing all of this in a separate segmentation
    #slicer mrmlscene create new node, class is slicermrmlsegmenationnode, then copy original node?

  def performLogicalAddOperationOnSegments(self, selectedSegmentID, modifierSegmentID):
    #import HeartValveLib
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.getMoldSegmentationNode()
    segmentation = segmentationNode.GetSegmentation()
    modifierSegment = segmentation.GetSegment(modifierSegmentID)
    modifierSegmentLabelmap = modifierSegment.GetRepresentation(vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())
    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(modifierSegmentLabelmap, segmentationNode,
                                                                        selectedSegmentID,
                                                                        slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MAX)
    return

  def performLogicalSubtractOperationOnSegments(self, selectedSegmentID, modifierSegmentID):
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.getMoldSegmentationNode()
    segmentation = segmentationNode.GetSegmentation()
    modifierSegment = segmentation.GetSegment(modifierSegmentID)
    modifierSegmentLabelmap = modifierSegment.GetRepresentation(vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())
    invertedModifierSegmentLabelmap = self.getInvertedBinaryLabelmap(modifierSegmentLabelmap)
    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(invertedModifierSegmentLabelmap,
                                                                        segmentationNode,
                                                                        selectedSegmentID,
                                                                        slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MIN)

  def growLeafletFromTopSurface(self, leafletTopSurfaceName, desiredThickness, grownLeafletModelName):

    logging.info(f"growing leaflet: {leafletTopSurfaceName}")

    leafletTopSurface = slicer.mrmlScene.GetFirstNodeByName(leafletTopSurfaceName) # TODO: this is hardcoded for now, fix later
    leafletColor = leafletTopSurface.GetDisplayNode().GetColor()
    leafletTopSurfacePolyData = leafletTopSurface.GetPolyData()
    leafletTopSurfacePolyData.GetPointData().SetActiveVectors("Normals")

    # Apply warp vector to pull leaflets apart at coaptation (for mold)
    warpVector = vtk.vtkWarpVector()
    warpVector.SetInputData(leafletTopSurfacePolyData)
    gapDistance = self.gapBetweenLeafletsSpinBox.value
    warpVector.SetScaleFactor(-(desiredThickness/2.0 + gapDistance))

    imp = vtk.vtkImplicitModeller()
    imp.SetInputConnection(warpVector.GetOutputPort())
    imp.SetSampleDimensions(100,100,50) # increase resolution

    contour = vtk.vtkContourFilter()
    contour.ComputeNormalsOn()
    contour.SetInputConnection(imp.GetOutputPort())
    contour.SetValue(0, desiredThickness/2.0)  # Is this necessary?

    # Use PolyDataNormals filter to get rid of artifacts
    # = vtk.vtkPolyDataNormals()
    #polyDataNormals.SetInputConnection(contour.GetOutputPort())
    #polyDataNormals.ConsistencyOn()
    #polyDataNormals.AutoOrientNormalsOn()

    # Try this instead if PolyDataNormals doesn't get rid of artifacts
    #triangles = vtk.vtkTriangleFilter()
    #triangles.SetInputConnection(contour.GetOutputPort())

    # Reverse leaflet normals for visualization
    reverse = vtk.vtkReverseSense()
    reverse.SetInputConnection(contour.GetOutputPort())
    reverse.ReverseNormalsOn()

    if slicer.mrmlScene.GetFirstNodeByName(grownLeafletModelName):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(grownLeafletModelName))

    modelsLogic = slicer.modules.models.logic()
    grownLeafletModel = modelsLogic.AddModel(reverse.GetOutputPort())
    grownLeafletModel.SetName(grownLeafletModelName)  # TODO: this is hardcoded for now, fix later
    grownLeafletModel.GetDisplayNode().SetVisibility(True)
    grownLeafletModel.GetDisplayNode().SetColor(leafletColor)
    grownLeafletModel.GetDisplayNode().SetOpacity(1.0)

    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    grownLeafletModel.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

    return grownLeafletModel

  def createAirTunnelModel(self, centerPoint, name, AnnulusToProbeTransform):
    radius = 1.0
    resolution = 20
    moldBottomHeight = self.moldBottomHeightSpinBox.value
    moldTopHeight = self.moldTopHeightSpinBox.value
    margin = 1.0 # add 1 mm for labelmap subtraction operations to work properly

    line = vtk.vtkLineSource()
    line.SetPoint1(centerPoint + [0,0,- moldBottomHeight - margin])
    line.SetPoint2(centerPoint + [0,0,moldTopHeight + margin])
    line.SetResolution(resolution)
    line.Update()

    tubeFilter = vtk.vtkTubeFilter()
    tubeFilter.SetInputData(line.GetOutput())
    tubeFilter.SetRadius(radius)
    tubeFilter.SetNumberOfSides(resolution)
    tubeFilter.CappingOn()
    tubeFilter.Update()

    # Triangulation is necessary to avoid discontinuous lines
    # in model/slice intersection display
    triangles = vtk.vtkTriangleFilter()
    triangles.SetInputConnection(tubeFilter.GetOutputPort())
    triangles.Update()

    #set AnnulusToProbe transform
    rotateTransform = vtk.vtkTransform()
    rotateTransform.SetMatrix(np.ndarray.flatten(AnnulusToProbeTransform)) # passes the transform matrix as a 1D array

    polyTransformToProbe = vtk.vtkTransformPolyDataFilter()
    polyTransformToProbe.SetTransform(rotateTransform)
    polyTransformToProbe.SetInputConnection(triangles.GetOutputPort())

    if slicer.mrmlScene.GetFirstNodeByName(name):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(name))

    modelsLogic = slicer.modules.models.logic()
    cylinderModel = modelsLogic.AddModel(polyTransformToProbe.GetOutputPort())
    cylinderModel.SetName(name)
    cylinderModel.GetDisplayNode().SetVisibility(False)
    cylinderModel.GetDisplayNode().SetColor([255,0,0])
    cylinderModel.GetDisplayNode().SetOpacity(1.0)

    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    cylinderModel.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

    self.valveModel.moveNodeToHeartValveFolder(cylinderModel)

    self.addModelToMoldSegmentation(cylinderModel)

    #set visibility of helper segments to False
    segmentationNode = self.getMoldSegmentationNode()
    segmentationNode.GetDisplayNode().SetSegmentVisibility(cylinderModel.GetName() + "_seg", False)

    return cylinderModel

  def createAirTunnelReservoir(self, centerPoint, name, AnnulusToProbeTransform):
    width = 10 #10 mm
    resolution = 20
    moldTopHeight = self.moldTopHeightSpinBox.value
    marginTop = 1.0  # add 1 mm on top for labelmap subtraction operations to work properly
    marginBottom = 5.0 # reservoir cone will begin 5mm above separation line of cone
    coneHeight = moldTopHeight - marginBottom + marginTop #cone height will be moltTopHeight setting minus 5mm from the bottom

    cone = vtk.vtkConeSource()
    cone.SetHeight(coneHeight)
    cone.SetRadius(width)
    cone.SetResolution(resolution)
    cone.SetDirection(0,0,-1) #extrude in -z direction
    cone.SetCenter(centerPoint + [0,0,moldTopHeight - coneHeight/2 + marginTop])
    cone.CappingOn()

    # set AnnulusToProbe transform
    rotateTransform = vtk.vtkTransform()
    rotateTransform.SetMatrix(np.ndarray.flatten(AnnulusToProbeTransform))  # passes the transform matrix as a 1D array

    polyTransformToProbe = vtk.vtkTransformPolyDataFilter()
    polyTransformToProbe.SetTransform(rotateTransform)
    polyTransformToProbe.SetInputConnection(cone.GetOutputPort())

    if slicer.mrmlScene.GetFirstNodeByName(name):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(name))

    modelsLogic = slicer.modules.models.logic()
    coneModel = modelsLogic.AddModel(polyTransformToProbe.GetOutputPort())
    coneModel.SetName(name)
    coneModel.GetDisplayNode().SetVisibility(False)
    coneModel.GetDisplayNode().SetColor([255, 0, 0])
    coneModel.GetDisplayNode().SetOpacity(1.0)

    probeToRasTransformNode = self.valveModel.getProbeToRasTransformNode()
    coneModel.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

    self.valveModel.moveNodeToHeartValveFolder(coneModel)

    self.addModelToMoldSegmentation(coneModel)

    # set visibility of helper segments to False
    segmentationNode = self.getMoldSegmentationNode()
    segmentationNode.GetDisplayNode().SetSegmentVisibility(coneModel.GetName() + "_seg", False)

    return coneModel

  def onTestAirTunnels(self, pushed):
    self.createAirTunnels()

  # create tunnels models, to subtract from top mold to prevent air bubbles when using mold
  def createAirTunnels(self):

    numberOfTunnels = self.numberAirTunnels//2 # will put half the tunnels above skirt, half above rim

    skirtOuterRadius = self.skirtOuterRadiusSpinBox.value  # radius is 36mm
    tunnelsRadius = skirtOuterRadius - 5.0 # location of tunnels from center of valve

    #get annuls to probe transform
    import HeartValveLib
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    ProbeToAnnulusTransform = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    AnnulusToProbeTransform = np.linalg.inv(ProbeToAnnulusTransform)

    # get points for a circle with radius 'averageValveRadius' (in Annulus plane)

    # get point for the rim
    skirtTunnelPoints = np.empty((4, numberOfTunnels,))

    angleToShift = (1.0/numberOfTunnels * 2.0 * math.pi) / 2 # shift so skirt tunnels alternate with rim tunnels
    for pointIndex in range(numberOfTunnels):

      #get the points for the tunnels in skirt
      angle = (float(pointIndex) / numberOfTunnels * 2.0 * math.pi) + angleToShift
      skirtPoint = [tunnelsRadius*math.cos(angle), tunnelsRadius*math.sin(angle),0,1]
      skirtTunnelPoints[:,pointIndex] = skirtPoint


    # make tunnels in skirt
    for index in range(numberOfTunnels):
      startPoint = skirtTunnelPoints[0:3, index]
      self.createAirTunnelModel(startPoint, "air tunnel " + str(index), AnnulusToProbeTransform)
      self.createAirTunnelReservoir(startPoint, "air reservoir " + str(index), AnnulusToProbeTransform)

    # get points for rim

    # generate a circle with radius 'averageValveRadius' and find closest point on annulusContour for each point
    averageValveRadius = self.getAverageValveRadius()
    valveRadiusSizeCirclePoints_Annulus = np.empty((4,numberOfTunnels,))
    closestCorrespondingAnnulusPoints_Probe = np.empty((4, numberOfTunnels,))
    # get points for a circle with radius 'averageValveRadius' (in Annulus plane)
    for pointIndex in range(numberOfTunnels):
      angle = float(pointIndex) / numberOfTunnels * 2.0 * math.pi
      pointOnCircle = [averageValveRadius*math.cos(angle), averageValveRadius*math.sin(angle),0,1]
      valveRadiusSizeCirclePoints_Annulus[:,pointIndex] = pointOnCircle
    # convert circle points to Probe plane
    valveRadiusSizeCirclePoints_Probe = np.dot(AnnulusToProbeTransform, valveRadiusSizeCirclePoints_Annulus)
    # find the corresponding closest points on the annulus (in Probe plane)
    for pointIndex in range(numberOfTunnels):
      pointOnCircle = valveRadiusSizeCirclePoints_Probe[0:3,pointIndex]
      [closestCorrespondingAnnulusPoints_Probe[0:3,pointIndex], _] = self.valveModel.annulusContourCurve.getClosestPoint(pointOnCircle)
      closestCorrespondingAnnulusPoints_Probe[3,pointIndex] = 1

    # take shrinkSpinBox setting into consideration for tunnels placed above rim
    if self.shrinkRimSpinBox.value > 0:
      closestCorrespondingAnnulusPointsShrunk = self.shrinkTargetPoints(closestCorrespondingAnnulusPoints_Probe[0:3], numberOfTunnels, self.shrinkRimSpinBox.value - self.rimSizeSpinBox.value)
    else:
      closestCorrespondingAnnulusPointsShrunk = self.shrinkTargetPoints(closestCorrespondingAnnulusPoints_Probe[0:3], numberOfTunnels, -self.rimSizeSpinBox.value)

    rowOfOnes = np.ones((1,numberOfTunnels,))
    closestCorrespondingAnnulusPointsShrunk = np.vstack([closestCorrespondingAnnulusPointsShrunk, rowOfOnes])

    rimTunnelPoints = np.dot(ProbeToAnnulusTransform, closestCorrespondingAnnulusPointsShrunk)

    # make tunnels in rim
    for index in range(numberOfTunnels):
      startPoint = rimTunnelPoints[0:3, index]
      startPoint[2] = 0 #set z value to 0
      self.createAirTunnelModel(startPoint, "air tunnel " + str(numberOfTunnels + index), AnnulusToProbeTransform)
      self.createAirTunnelReservoir(startPoint, "air reservoir " + str(numberOfTunnels + index), AnnulusToProbeTransform)

  def onGrowLeafletsFromTopSurface(self, pushed):
    desiredLeafletThickness = self.leafletThicknessSpinBox.value

    logging.debug(self.leafletIDs)

    for leafletModel in self.valveModel.leafletModels:
      segmentId = leafletModel.segmentId
      leafletSurfaceModelNode = self.valveModel.getLeafletNodeReference("LeafletSurfaceModel", segmentId)
      topSurfaceName = leafletSurfaceModelNode.GetName()
      grownLeafletModelName = "Grown model: " + segmentId
      self.growLeafletFromTopSurface(topSurfaceName, desiredLeafletThickness, grownLeafletModelName)

  def onCreateMoldModels(self, pushed):

    valveRim = self.createRimTube()
    valveRimStiffener = self.createRimStiffener(0.0, self.rimStiffenerLengthSpinBox.value) # this rim will extend downwards

    skirtOuterRadius = self.skirtOuterRadiusSpinBox.value
    skirtThickness = self.skirtThicknessSpinBox.value

    valveSkirt = self.makeSkirtAroundRim(valveRim, skirtOuterRadius, skirtThickness)

    moldTopHeight = self.moldTopHeightSpinBox.value
    moldBottomHeight = self.moldBottomHeightSpinBox.value

    moldBorderHeight = self.borderHeightSpinBox.value
    boxLength = 2*(skirtOuterRadius + 4.0)  # so that there will be 4mm extra on each side of the skirt
    spaceBoxToSkirt = (boxLength / 2.0) - skirtOuterRadius # 4mm, aka moldBorderDepth

    moldBoxTop = self.makeMoldBoxModel(skirtOuterRadius, "topMold", 0, moldTopHeight, [0.1, 0.9, 0.3], boxLength)
    moldBoxBottom = self.makeMoldBoxModel(skirtOuterRadius, "bottomMold", -moldBottomHeight, 0, [0.1, 0.5, 0.5], boxLength)

    #create rectangular prisms for cropping to get rid of artifacts left by subtracting segments of same size
    #crop bottom of mold
    moldBoxBottomCrop = self.makeRectangularPrismModel("cropBottomMold", [0.9, 0.5, 0.5], -boxLength/2.0, boxLength/2.0,
                                                       -boxLength/2.0, boxLength/2.0, -moldBottomHeight - 20.0, -moldBottomHeight+1.0)
    # crop sides of mold by a margin of 1.0mm to remove artifacts
    margin = 1.0
    moldBoxFrontCrop = self.makeRectangularPrismModel("cropMoldFront", [0.9, 0.5, 0.5],
                                                      -boxLength/2.0 - margin, boxLength/2.0 + margin, #xmin and xMax
                                                      -boxLength/2.0 - margin, -boxLength/2.0 + margin, #ymin and ymax
                                                      -moldBottomHeight - margin, 0) #zmin and zmax
    moldBoxRightCrop = self.makeRectangularPrismModel("cropMoldRight", [0.9, 0.5, 0.5],
                                                      boxLength/2.0 - margin, boxLength/2.0 + margin,
                                                      -boxLength/2.0 - margin, boxLength/2.0 + margin,
                                                      -moldBottomHeight - margin, 0)
    moldBoxBackCrop = self.makeRectangularPrismModel("cropMoldBack", [0.9, 0.5, 0.5],
                                                     -boxLength/2.0 - margin, boxLength/2.0 + margin,
                                                     boxLength/2.0 - margin, boxLength/2.0 + margin,
                                                     -moldBottomHeight - margin, 0)
    moldBoxLeftCrop = self.makeRectangularPrismModel("cropMoldLeft", [0.9, 0.5, 0.5],
                                                     -boxLength/2.0 - margin, -boxLength/2.0 + margin,
                                                      -boxLength/2.0, boxLength/2.0,
                                                     -moldBottomHeight - margin, 0)

    #need the borders to overlap with the bottom mold by 1mm for labelmap addition to work properly
    triangleOverlap = 1.0

    trianglePrismForMoldBox_1 = self.makeTriangularBoundariesForMoldBox("triangleBorder1",
                                                                        [boxLength/2.0, boxLength/2.0, -triangleOverlap],
                                                                        [boxLength/2.0, boxLength/2.0-spaceBoxToSkirt, -triangleOverlap],
                                                                        [boxLength/2.0, boxLength/2.0, moldBorderHeight],
                                                                        [-1, 0, 0], [0.9,0.1,0.1], boxLength)

    trianglePrismForMoldBox_2 = self.makeTriangularBoundariesForMoldBox("triangleBorder2",
                                                                        [boxLength/2.0, boxLength/2.0, -triangleOverlap],
                                                                        [boxLength/2.0-spaceBoxToSkirt, boxLength/2.0, -triangleOverlap],
                                                                        [boxLength/2.0, boxLength/2.0, moldBorderHeight],
                                                                        [0, -1, 0], [0.9, 0.1, 0.1], boxLength)

    trianglePrismForMoldBox_3 = self.makeTriangularBoundariesForMoldBox("triangleBorder3",
                                                                        [-boxLength/2.0, -boxLength/2.0, -triangleOverlap],
                                                                        [-boxLength/2.0, -boxLength/2.0+spaceBoxToSkirt, -triangleOverlap],
                                                                        [-boxLength/2.0, -boxLength/2.0, moldBorderHeight],
                                                                        [1, 0, 0], [0.9, 0.1, 0.1], boxLength)

    trianglePrismForMoldBox_4 = self.makeTriangularBoundariesForMoldBox("triangleBorder4",
                                                                        [-boxLength/2.0, -boxLength/2.0, -triangleOverlap],
                                                                        [-boxLength/2.0+spaceBoxToSkirt, -boxLength/2.0, -triangleOverlap],
                                                                        [-boxLength/2.0, -boxLength/2.0, moldBorderHeight],
                                                                        [0, 1, 0], [0.9, 0.1, 0.1], boxLength)

    wedgeDepth = spaceBoxToSkirt # how far the wedge goes into the mold, in mm # 5mm
    wedgeHeight = self.wedgeHeightSpinBox.value #14.0mm
    wedgeWidth = 20.0 #mm
    wedgeTopHeight = moldBorderHeight + (wedgeHeight/2.0)
    wedgeCenterHeight = moldBorderHeight
    wedgeBottomHeight = moldBorderHeight - (wedgeHeight/2.0)

    openingWedge = self.makeTriangularBoundariesForMoldBox("openingWedge",
                                                                 [-wedgeWidth/2, -boxLength/2.0, wedgeBottomHeight],
                                                                 [-wedgeWidth/2, -boxLength/2.0+wedgeDepth, wedgeCenterHeight],
                                                                 [-wedgeWidth/2, -boxLength/2.0, wedgeTopHeight],
                                                                 [1, 0, 0], [0.5, 0.1, 0.5], wedgeWidth)


    #create air tunnel models and adds them to the segmentation
    self.createAirTunnels()

    # add the mold models to MoldSegmentation
    self.addModelToMoldSegmentation(valveRim.curveModelNode)
    self.addModelToMoldSegmentation(valveRimStiffener)
    self.addModelToMoldSegmentation(valveSkirt)
    self.addModelToMoldSegmentation(moldBoxTop)
    self.addModelToMoldSegmentation(moldBoxBottom)
    self.addModelToMoldSegmentation(moldBoxBottomCrop)
    self.addModelToMoldSegmentation(moldBoxFrontCrop)
    self.addModelToMoldSegmentation(moldBoxRightCrop)
    self.addModelToMoldSegmentation(moldBoxBackCrop)
    self.addModelToMoldSegmentation(moldBoxLeftCrop)
    self.addModelToMoldSegmentation(trianglePrismForMoldBox_1)
    self.addModelToMoldSegmentation(trianglePrismForMoldBox_2)
    self.addModelToMoldSegmentation(trianglePrismForMoldBox_3)
    self.addModelToMoldSegmentation(trianglePrismForMoldBox_4)
    self.addModelToMoldSegmentation(openingWedge)

    #set visibility of helper segments to False
    segmentationNode = self.getMoldSegmentationNode()
    segmentationNode.GetDisplayNode().SetSegmentVisibility(moldBoxBottomCrop.GetName() + "_seg", False)
    segmentationNode.GetDisplayNode().SetSegmentVisibility(moldBoxFrontCrop.GetName() + "_seg", False)
    segmentationNode.GetDisplayNode().SetSegmentVisibility(moldBoxRightCrop.GetName() + "_seg", False)
    segmentationNode.GetDisplayNode().SetSegmentVisibility(moldBoxBackCrop.GetName() + "_seg", False)
    segmentationNode.GetDisplayNode().SetSegmentVisibility(moldBoxLeftCrop.GetName() + "_seg", False)

    ###########################
    if self.useGrownLeafletsToMakeMoldButton.isChecked():
      # add leaflet segments grown from extracted top surface to valvePhantom
      # for leafletID in self.leafletIDs:
      #   leafletName = self.getLeafletNameFromID(leafletID)
      #   grownLeafletModelName = "Grown model: " + leafletName
      #   grownLeafletModel = slicer.mrmlScene.GetFirstNodeByName(grownLeafletModelName)
      #   self.addModelToMoldSegmentation(grownLeafletModel)

      for leafletModel in self.valveModel.leafletModels:
        segmentId = leafletModel.segmentId
        grownLeafletModelName = "Grown model: " + segmentId
        grownLeafletModel = slicer.mrmlScene.GetFirstNodeByName(grownLeafletModelName)
        self.addModelToMoldSegmentation(grownLeafletModel)

    ############################

    # add three empty models to MoldSegmentation ("valvePhantom", "topMold", "bottomMold")
    self.createEmptySegment("valvePhantom_seg")
    self.createEmptySegment("valvePhantomClosed_seg")
    self.createEmptySegment("valvePhantomClosedGrownDown_seg")
    self.createEmptySegment("valvePhantomClosedGrownUp_seg") #temporary, for splitting top and bottom molds
    #self.createEmptySegment("valvePhantomClosedGrownUp2mm_seg")  # temporary, for splitting top and bottom molds
    self.createEmptySegment("topMoldFinal_seg")
    self.createEmptySegment("bottomMoldFinal_seg")

    segmentationNode = self.getMoldSegmentationNode()
    #segmentationNode.GetDisplayNode().SetAllSegmentsVisibility(False)

  def onCombineSegmentPartsToCreateMoldWithAutomaticMoldSeparation(self, pushed):
    # use add/subtract logical operators to form the valvePhantom, topMold and bottomMold segments.

    #this button should be pressed after manual editing of top/bottom molds, to master representation should already be binarylabelmap...
    self.setMasterRepresentationToBinaryLabelmap()

    #STEP 1: CREATE THE VALVE PHANTOM SEGMENT
    self.performLogicalAddOperationOnSegments("valvePhantom_seg", "valveSkirt_seg")

    if self.useGrownLeafletsToMakeMoldButton.isChecked():
      # add leaflet segments grown from extracted top surface to valvePhantom
      # for leafletID in self.leafletIDs:
      #   leafletName = self.getLeafletNameFromID(leafletID)
      #   grownLeafletSegmentName = "Grown model: " + leafletName + "_seg"
      #   self.performLogicalAddOperationOnSegments("valvePhantom_seg", grownLeafletSegmentName)
      for leafletModel in self.valveModel.leafletModels:
        segmentId = leafletModel.segmentId
        grownLeafletModelName = "Grown model: " + segmentId
        grownLeafletSegmentName = grownLeafletModelName + "_seg"
        self.performLogicalAddOperationOnSegments("valvePhantom_seg", grownLeafletSegmentName)
    else:
      # add segmented leaflets to valvePhantom
      # for leafletID in self.leafletIDs:
      #   self.performLogicalAddOperationOnSegments("valvePhantom_seg", leafletID)

      for leafletModel in self.valveModel.leafletModels:
        segmentId = leafletModel.segmentId
        self.performLogicalAddOperationOnSegments("valvePhantom_seg", segmentId)


    #the valve phantom used for separating top and bottom molds should not include the rim
    self.performLogicalAddOperationOnSegments("valvePhantomClosed_seg", "valvePhantom_seg")

    self.performLogicalAddOperationOnSegments("valvePhantom_seg", "valveRim_seg")
    self.performLogicalAddOperationOnSegments("valvePhantom_seg", "valveRimStiffener_seg")
    self.performLogicalAddOperationOnSegments("valvePhantom_seg", "ROrientationMarker_seg")
    self.performLogicalAddOperationOnSegments("valvePhantom_seg", "SOrientationMarker_seg")

    #STEP 2: CREATE CLOSED VALVE PHANTOM AND USE IT TO SHAPE TOP/BOTTOM MOLD SEPARATION TO CLOSED PHANTOM

    logging.info("Smoothing closedValvePhantom to close gaps...")
    kernelSizeMm = 5.0  # todo: test if this is large enough to close valvePhantoms from all segmentations
    self.valveModel.smoothSegment(self.getMoldSegmentationNode(), "valvePhantomClosed_seg", kernelSizeMm,
                                  smoothInZDirection=False)
    self.performLogicalAddOperationOnSegments("valvePhantomClosedGrownUp_seg", "valvePhantomClosed_seg")
    self.performLogicalAddOperationOnSegments("valvePhantomClosedGrownDown_seg", "valvePhantomClosed_seg")
    #self.performLogicalAddOperationOnSegments("valvePhantomClosedGrownUp2mm_seg", "valvePhantomClosed_seg")
    # make a new segment that is the grown segment, but translated down
    #self.performLogicalAddOperationOnSegments("valvePhantomClosedGrownDown_seg", "valvePhantomClosedGrownUp_seg")
    #for testing, save a closed valve phantom segment that will not be grown
    #self.performLogicalAddOperationOnSegments("valvePhantomClosedBeforeGrowing_seg", "valvePhantomClosedGrownUp_seg")

    logging.info("Growing closedValvePhantom...")
    grownLeafletThickness = self.leafletThicknessSpinBox.value
    topMoldHeight = self.moldTopHeightSpinBox.value
    #desiredThicknessToGrow = topMoldHeight - 5.0 # approximation #todo: use topMoldHeight then crop molds)
    #desiredThicknessToGrow = desiredThicknessToGrow*2 # because it doesn't seem to working ?

    ############################
    desiredThicknessToGrowUp = 14.0
    desiredThicknessToGrowDown = 30.0
    ############################

    self.growClosedValvePhantomToDesiredThickness("valvePhantomClosedGrownUp_seg",desiredThicknessToGrowUp, "up")

    # now grow it downwards again
    logging.info ("Growing closedValvePhantom downwards...")
    # self.translateClosedValvePhantom("valvePhantomClosedGrownDown_seg", -desiredThicknessToGrowDown*2) # did not work

    #first translate it down, to eliminate noise on top of valvePhantom
    self.translateClosedValvePhantomByLeafletThickness("valvePhantomClosedGrownDown_seg", grownLeafletThickness * 4, "down")
    self.growClosedValvePhantomToDesiredThickness("valvePhantomClosedGrownDown_seg", desiredThicknessToGrowDown, "down") # negative means grow down
    #self.performLogicalSubtractOperationOnSegments("topMold_seg", "valvePhantomClosedGrownDown_seg")
    ###

    #logging.info("Grow thin closedValvePhantom upwards to get rid of noise...")
    #self.growClosedValvePhantomToDesiredThickness("valvePhantomClosedGrownUp2mm_seg", 2.0*2, "up")

    # edit the bottomMold and topMold segments
    logging.info("Performing merges on bottomMold_seg and topMold_seg...")
    #self.performLogicalAddOperationOnSegments("bottomMold_seg", "topMold_seg")  # bottom mold becomes the big mold block
    #self.performLogicalAddOperationOnSegments("topMold_seg", "valvePhantomClosedGrownUp_seg")
    #self.performLogicalSubtractOperationOnSegments("topMold_seg", "valvePhantom_seg")
    #self.performLogicalSubtractOperationOnSegments("bottomMold_seg", "topMold_seg")
    #self.performLogicalSubtractOperationOnSegments("bottomMold_seg", "valvePhantom_seg")
    self.performLogicalAddOperationOnSegments("topMoldFinal_seg", "bottomMold_seg")  # top mold becomes the big mold block
    self.performLogicalAddOperationOnSegments("topMoldFinal_seg","topMold_seg")  # top mold becomes the big mold block

    # Edit bottom mold first, to follow the shape of the closedValvePhantom
    self.performLogicalAddOperationOnSegments("bottomMoldFinal_seg", "bottomMold_seg")
    #self.performLogicalAddOperationOnSegments("bottomMoldFinal_seg", "valvePhantomClosedGrownDown_seg")
    #self.performLogicalSubtractOperationOnSegments("bottomMoldFinal_seg", "valvePhantomClosedGrownUp_seg")

    #what order is best
    #i think adding last is best, maybe for the grow upwards I can cut it off a bit at the top?
    self.performLogicalSubtractOperationOnSegments("bottomMoldFinal_seg", "valvePhantomClosedGrownUp_seg")
    self.performLogicalAddOperationOnSegments("bottomMoldFinal_seg", "valvePhantomClosedGrownDown_seg")
    #self.performLogicalSubtractOperationOnSegments("bottomMoldFinal_seg", "valvePhantomClosedGrownUp2mm_seg")
    self.performLogicalSubtractOperationOnSegments("bottomMoldFinal_seg", "valvePhantom_seg")

    # add mold features to bottomMold
    self.performLogicalAddOperationOnSegments("bottomMoldFinal_seg", "triangleBorder1_seg")
    self.performLogicalAddOperationOnSegments("bottomMoldFinal_seg", "triangleBorder2_seg")
    self.performLogicalAddOperationOnSegments("bottomMoldFinal_seg", "triangleBorder3_seg")
    self.performLogicalAddOperationOnSegments("bottomMoldFinal_seg", "triangleBorder4_seg")
    #self.performLogicalSubtractOperationOnSegments("bottomMoldFinal_seg", "valvePhantom_seg")
    self.performLogicalSubtractOperationOnSegments("bottomMoldFinal_seg", "openingWedge_seg")

    self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "cropBottomMold_seg") # to get rid of labelmap artifacts underneath top mold
    #remove artifacts on sides of top mold (created by subtracting near equal segments) :
    self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "cropMoldFront_seg")
    self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "cropMoldRight_seg")
    self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "cropMoldBack_seg")
    self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "cropMoldLeft_seg")


    # create the topMold segment
    #self.performLogicalSubtractOperationOnSegments("topMold_seg", "bottomMoldFinal_seg")
    #self.performLogicalAddOperationOnSegments("topMoldFinal_seg", "topMold_seg")
    self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "bottomMoldFinal_seg")
    #self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "bottomMoldFinal_seg")
    self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "valvePhantom_seg")
    self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "openingWedge_seg")

    #subtract air tunnels
    for index in range(self.numberAirTunnels):
      self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "air tunnel " + str(index) + "_seg")
      self.performLogicalSubtractOperationOnSegments("topMoldFinal_seg", "air reservoir " + str(index) + "_seg")

    self.performLogicalSubtractOperationOnSegments("bottomMoldFinal_seg", "cropBottomMold_seg")  # to get rid of extra mesh on bottom

    #hide all segments except for valvePhantom and final top and bottom mold
    segmentationNode = self.getMoldSegmentationNode()
    segmentationNode.GetDisplayNode().SetAllSegmentsVisibility(False)
    segmentationNode.GetDisplayNode().SetSegmentVisibility("valvePhantom_seg", True)
    segmentationNode.GetDisplayNode().SetSegmentVisibility("topMoldFinal_seg", True)
    segmentationNode.GetDisplayNode().SetSegmentVisibility("bottomMoldFinal_seg", True)

    # convert these 3 segments to models (so they can be saved as .stl files for printing)
    self.createModelFromSegment("valvePhantom_seg")
    self.createModelFromSegment("bottomMoldFinal_seg")
    self.createModelFromSegment("topMoldFinal_seg")

  def onExportFinalSegmentsAsModels(self, pushed):
    # convert these 3 segments to models
    self.createModelFromSegment("valvePhantom_seg")
    self.createModelFromSegment("bottomMoldFinal_seg")
    self.createModelFromSegment("topMoldFinal_seg")

  def translateClosedValvePhantom(self, phantomName, distanceToTranslate):
    # distanceToTranslate should be negative if you want it to be moved down

    # get closed valve phantom labelmap
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.getMoldSegmentationNode()
    segmentation = segmentationNode.GetSegmentation()
    selectedSegmentID = phantomName
    closedValvePhantomSegment = segmentation.GetSegment(selectedSegmentID)
    closedValvePhantomLabelmap = closedValvePhantomSegment.GetRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())

    # get imageToWorldMatrix of valvePhantomClosedGrownUp_seg
    imageToWorldMatrix = vtk.vtkMatrix4x4()
    closedValvePhantomLabelmap.GetImageToWorldMatrix(imageToWorldMatrix)

    # get planeNormal unit vector for valve
    import HeartValveLib
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    planeNormalUnitVector = (1 / np.linalg.norm(planeNormal)) * planeNormal

    # Apply translation to imageToWorldMatrix
    translateImageToWorldTransform = vtk.vtkTransform()
    translateImageToWorldTransform.SetMatrix(imageToWorldMatrix)
    translateImageToWorldTransform.Translate(-planeNormalUnitVector * distanceToTranslate)
    translatedImageToWorldMatrix = translateImageToWorldTransform.GetMatrix()

    # Create modifier labelmap for translated closedValvePhantom
    modifierLabelmap = vtkSegmentationCore.vtkOrientedImageData()
    modifierLabelmap.ShallowCopy(closedValvePhantomLabelmap)
    modifierLabelmap.SetImageToWorldMatrix(translatedImageToWorldMatrix)

    #
    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(modifierLabelmap, segmentationNode,
                                                                        selectedSegmentID)

  def translateClosedValvePhantomByLeafletThickness(self, phantomName, distanceToTranslate, directionToGrow):

    # seems to grow them downwards (normals facing down)

    if directionToGrow == "down":
      distanceToTranslate = -distanceToTranslate

    # get closed valve phantom labelmap
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.getMoldSegmentationNode()
    segmentation = segmentationNode.GetSegmentation()
    selectedSegmentID = phantomName
    closedValvePhantomSegment = segmentation.GetSegment(selectedSegmentID)
    closedValvePhantomLabelmap = closedValvePhantomSegment.GetRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())

    # get imageToWorldMatrix of valvePhantomClosedGrownUp_seg
    imageToWorldMatrix = vtk.vtkMatrix4x4()
    closedValvePhantomLabelmap.GetImageToWorldMatrix(imageToWorldMatrix)

    # get planeNormal unit vector for valve
    import HeartValveLib
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    planeNormalUnitVector = (1 / np.linalg.norm(planeNormal)) * planeNormal

    # Apply translation to imageToWorldMatrix
    translateImageToWorldTransform = vtk.vtkTransform()
    translateImageToWorldTransform.SetMatrix(imageToWorldMatrix)
    translateImageToWorldTransform.Translate(-planeNormalUnitVector * distanceToTranslate)
    translatedImageToWorldMatrix = translateImageToWorldTransform.GetMatrix()

    # Create modifier labelmap for translated closedValvePhantom
    modifierLabelmap = vtkSegmentationCore.vtkOrientedImageData() # is it ok to make a new object instead of the line above?
    modifierLabelmap.ShallowCopy(closedValvePhantomLabelmap)
    modifierLabelmap.SetImageToWorldMatrix(translatedImageToWorldMatrix)

    #replace with translated labelmap
    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(modifierLabelmap, segmentationNode,
                                                                        selectedSegmentID)

  def growClosedValvePhantom(self, phantomName, distanceToTranslate, directionToGrow):
    # seems to grow them downwards (normals facing down)

    if directionToGrow == "down":
      distanceToTranslate = -distanceToTranslate


    # get closed valve phantom labelmap
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentationNode = self.getMoldSegmentationNode()
    segmentation = segmentationNode.GetSegmentation()
    selectedSegmentID = phantomName
    closedValvePhantomSegment = segmentation.GetSegment(selectedSegmentID)
    closedValvePhantomLabelmap = closedValvePhantomSegment.GetRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())

    # get imageToWorldMatrix of valvePhantomClosedGrownUp_seg
    imageToWorldMatrix = vtk.vtkMatrix4x4()
    closedValvePhantomLabelmap.GetImageToWorldMatrix(imageToWorldMatrix)

    # get planeNormal unit vector for valve
    import HeartValveLib
    annulusControlPoints = self.valveModel.annulusContourCurve.getControlPointsAsArray()
    [planePosition, planeNormal] = HeartValveLib.planeFit(annulusControlPoints)
    planeNormalUnitVector = (1 / np.linalg.norm(planeNormal)) * planeNormal

    # Apply translation to imageToWorldMatrix
    translateImageToWorldTransform = vtk.vtkTransform()
    translateImageToWorldTransform.SetMatrix(imageToWorldMatrix)
    translateImageToWorldTransform.Translate(-planeNormalUnitVector * distanceToTranslate)
    translatedImageToWorldMatrix = translateImageToWorldTransform.GetMatrix()

    # Create modifier labelmap for translated closedValvePhantom
    modifierLabelmap = vtkSegmentationCore.vtkOrientedImageData() # is it ok to make a new object instead of the line above?
    modifierLabelmap.ShallowCopy(closedValvePhantomLabelmap)
    modifierLabelmap.SetImageToWorldMatrix(translatedImageToWorldMatrix)

    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(modifierLabelmap, segmentationNode,
                                                                        selectedSegmentID,
                                                                        slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MAX,
                                                                        modifierLabelmap.GetExtent())

  # This seems to grow it only about half of desired thickness, is there a flaw in my logic?
  def growClosedValvePhantomToDesiredThickness(self, phantomName, desiredThicknessToGrow, directionToGrow):

    grownLeafletThickness = self.leafletThicknessSpinBox.value

    #logging.info("desiredThicknessToGrow = ", desiredThicknessToGrow, "\n")

    # grow the closedValvePhantomThickness until you go as close to the desiredThickness as possible
    currentClosedValvePhantomThickness = grownLeafletThickness
    nextClosedValvePhantomThickness = currentClosedValvePhantomThickness * 2

    while nextClosedValvePhantomThickness <= desiredThicknessToGrow:
      #logging.debug("in loop, currentClosedValvePhantomThickness = ", currentClosedValvePhantomThickness,
      #      ", nextClosedValvePhantomThickness = ", nextClosedValvePhantomThickness, "\n")
      self.growClosedValvePhantom(phantomName, currentClosedValvePhantomThickness, directionToGrow)
      currentClosedValvePhantomThickness = nextClosedValvePhantomThickness
      nextClosedValvePhantomThickness = currentClosedValvePhantomThickness*2

    if currentClosedValvePhantomThickness < desiredThicknessToGrow:
      remainingThicknessToGrow = desiredThicknessToGrow - currentClosedValvePhantomThickness
      #logging.debug("outside of loop, currentClosedValvePhantomThickness = ", currentClosedValvePhantomThickness,
      #      "remainingThicknessToGrow = ", remainingThicknessToGrow)
      self.growClosedValvePhantom(phantomName, remainingThicknessToGrow, directionToGrow)

  def onReload(self):
    logging.debug("Reloading LeafletMoldGenerator")

    packageName='HeartValveLib'
    submoduleNames=['LeafletModel', 'SmoothCurve', 'ValveRoi', 'ValveModel', 'HeartValves']
    import imp
    f, filename, description = imp.find_module(packageName)
    package = imp.load_module(packageName, f, filename, description)
    for submoduleName in submoduleNames:
      f, filename, description = imp.find_module(submoduleName, package.__path__)
      try:
          imp.load_module(packageName+'.'+submoduleName, f, filename, description)
      finally:
          f.close()

    ScriptedLoadableModuleWidget.onReload(self)

#
# LeafletMoldGeneratorLogic
#

class LeafletMoldGeneratorLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  @staticmethod
  def cloneMRMLNode(node):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    itemIDToClone = shNode.GetItemByDataNode(node)
    clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(shNode, itemIDToClone)
    return shNode.GetItemDataNode(clonedItemID)

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)


class LeafletMoldGeneratorTest(ScriptedLoadableModuleTest):
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
    self.test_LeafletMoldGenerator1()

  def test_LeafletMoldGenerator1(self):
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