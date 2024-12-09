import os
import logging
import math

import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *

import HeartValveLib
from HeartValveLib.SmoothCurve import SmoothCurve, InterpolationSpline
from HeartValveLib.Constants import VALVE_TYPE_PRESETS, CARDIAC_CYCLE_PHASE_PRESETS, PROBE_POSITION_PRESETS


#
# ValveAnnulusAnalysis
#

class ValveAnnulusAnalysis(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Valve Annulus Analysis"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Andras Lasso (PerkLab), Christian Herz (CHOP), Matt Jolley (UPenn)"]
    self.parent.helpText = """Specify a valve and its annulus contour"""
    self.parent.acknowledgementText = """This file was originally developed by Andras Lasso, PerkLab."""
    slicer.app.connect("startupCompleted()", self.initializeHeartValveLib)

  def registerSampleData(self):
    """
    Add data sets to Sample Data module.
    """
    # It is always recommended to provide sample data for users to make it easy to try the module,
    # but if no sample data is available then this method (and associated startupCompeted signal connection) can be removed.

    import SampleData
    iconsPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons')

    # To ensure that the source code repository remains small (can be downloaded and installed quickly)
    # it is recommended to store data sets that are larger than a few MB in a Github release.

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category='SlicerHeart',
        sampleName='Mitral',
        thumbnailFileName=os.path.join(iconsPath, 'Mitral.png'),
        uris=['https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/Mitral_US.seq.nrrd',
          'https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/Mitral_f06_Leaflets.seg.nrrd'],
        checksums=['SHA256:dfec24e4aa3820fc00a5303b80ea25a38784fc2ba3210a99c141a85136380042',
          'SHA256:67d43571d9266e8b056e14f5bd4099e5fffdcaf871786720a9d45b601be12814'],
        fileNames=['Mitral_US.seq.nrrd', 'Mitral_f06_Leaflets.seg.nrrd'],
        loadFileType=['SequenceFile', 'SegmentationFile'],
        nodeNames=['Mitral_US', 'Mitral_f06_Leaflets']
    )

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category='SlicerHeart',
        sampleName='Tricuspid',
        thumbnailFileName=os.path.join(iconsPath, 'Tricuspid.png'),
        uris=['https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/Tricuspid_US.seq.nrrd',
          'https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/Tricuspid_f09_Leaflets.seg.nrrd'],
        checksums=['SHA256:3286a9ddb1971bc7a02d2d0518f975071d14edb1c6c2c631347215e311704ca9',
          'SHA256:4e65fb43b8fc78de9e143d86476d617eb7d5ea34379519754d035ff60ed4a15a'],
        fileNames=['Tricuspid_US.seq.nrrd', 'Tricuspid_f09_Leaflets.seg.nrrd'],
        loadFileType=['SequenceFile', 'SegmentationFile'],
        nodeNames=['Tricuspid_US', 'Tricuspid_f09_Leaflets']
    )

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category='SlicerHeart',
        sampleName='CAVC',
        thumbnailFileName=os.path.join(iconsPath, 'CAVC.png'),
        uris=['https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/CAVC_US.seq.nrrd',
          'https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/CAVC_f08_Leaflets.seg.nrrd'],
        checksums=['SHA256:d035de8092356949b71a95ee23acb45228f4b68548e9b53f79db76e452347fc7',
          'SHA256:6c42fd0f07c7affe83a2cda020edb23cf8ff98e40af8d69fc7d6db7726f99934'],
        fileNames=['CAVC_US.seq.nrrd', 'CAVC_f08_Leaflets.seg.nrrd'],
        loadFileType=['SequenceFile', 'SegmentationFile'],
        nodeNames=['CAVC_US', 'CAVC_f08_Leaflets']
    )

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category='SlicerHeart',
        sampleName='PDA',
        thumbnailFileName=os.path.join(iconsPath, 'PDA.png'),
        uris=['https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/PDA_CT.nrrd',
          'https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/PDA_vasculature.seg.nrrd'],
        checksums=['SHA256:00dfd092e10fcddc009671361b808da9324a3f122e72c27dc50d280f4e7ef242',
          'SHA256:e0ec4321cfafdf12093c1148a49e4f6f799ec72709275c815b0694819baa1385'],
        fileNames=['PDA_CT.nrrd', 'PDA_vasculature.seg.nrrd'],
        loadFileType=['VolumeFile', 'SegmentationFile'],
        nodeNames=['PDA_CT', 'PDA_vasculature']
    )

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category='SlicerHeart',
        sampleName='Truncal Valve',
        # sampleDescription property cannot be defined yet in registerCustomSampleDataSource, therefore keeping it as a comment here:
        # sampleDescription='4D gated CT of adolescent with truncus arteriosus s/p repair',
        thumbnailFileName=os.path.join(iconsPath, 'TruncalValve.png'),
        uris=['https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/TruncalValve_4DCT.seq.nrrd'],
        checksums=['SHA256:7573f1bc7ca92d7d1012eecf98211cfd9939c1d22d87aee1db91c8ab72031cfb'],
        fileNames=['TruncalValve_4DCT.seq.nrrd'],
        loadFileType=['SequenceFile'],
        nodeNames=['TruncalValve_4DCT']
    )

  def initializeHeartValveLib(self):
    """Perform initializations that can only be performed when Slicer has started up"""
    self.registerSampleData()
    moduleDir = os.path.dirname(self.parent.path)
    usPresetsScenePath = os.path.join(moduleDir, 'Resources/VrPresets', 'US-VrPresets.mrml')
    HeartValveLib.setup(usPresetsScenePath)
    HeartValveLib.setupTerminology()

#
# ValveAnnulusAnalysisWidget
#

class ValveAnnulusAnalysisWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModuleWidget.__init__(self, parent)

    self.logic = ValveAnnulusAnalysisLogic()

    self.parameterNode = None
    self.parameterNodeObserver = None

    self.annulusMarkupNode = None
    self.annulusMarkupNodeObserver = None

    self.axialSliceToRasTransformNode = None
    self.axialSliceToRasTransformNodeObserver = None

    self.axialSlice = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeRed')
    self.orthogonalSlice1 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeYellow')
    self.orthogonalSlice2 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeGreen')

    self.autoRotateStartAngle = 0
    self.autoRotateStartNumberOfPoints = 0
    self.autoRotatePointsPerSlice = 1

    # Stores the currently selected HeartValveNode (scripted loadable module node)
    # and also provides methods to operate on it.
    self.valveModel = None

    self.annulusContourPreviewCurve = SmoothCurve()
    self.annulusContourPreviewCurve.setInterpolationMethod(InterpolationSpline)
    self.annulusContourPreviewCurve.setClosed(True)
    self.annulusContourPreviewControlPoints = slicer.vtkMRMLMarkupsFiducialNode() # no need to put this into the scene
    self.annulusContourPreviewCurve.setControlPointsMarkupNode(self.annulusContourPreviewControlPoints)

    modelsLogic = slicer.modules.models.logic()
    polyData = vtk.vtkPolyData()
    self.annulusContourPreviewModel = modelsLogic.AddModel(polyData)
    self.annulusContourPreviewModel.SetName(slicer.mrmlScene.GetUniqueNameByString("AnnulusContourPreviewModel"))
    self.annulusContourPreviewModel.SetSaveWithScene(False)
    self.annulusContourPreviewModel.SetHideFromEditors(True)
    self.annulusContourPreviewModel.SetAttribute(slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyExcludeFromTreeAttributeName(), "1") # prevent the node from showing up in SH
    self.annulusContourPreviewModel.GetDisplayNode().SetColor(0.8,0,1.0) # yellow
    self.annulusContourPreviewCurve.setCurveModelNode(self.annulusContourPreviewModel)
    self.annulusContourPreviewCurve.setTubeRadius(0.5)
    self.annulusContourPreviewActive = True # force an initial update
    self.setAnnulusContourPreviewActive(False)

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Load widget from .ui file (created by Qt Designer)
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/ValveAnnulusAnalysis.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    #
    # Main section
    #

    self.ui.heartValveSelector.setNodeTypeLabel("HeartValve", "vtkMRMLScriptedModuleNode")
    self.ui.heartValveSelector.addAttribute( "vtkMRMLScriptedModuleNode", "ModuleName", "HeartValve" )
    self.ui.heartValveSelector.setMRMLScene(slicer.mrmlScene)
    self.ui.heartValveSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onHeartValveSelect)

    for valveTypePresetName in VALVE_TYPE_PRESETS.keys():
      self.ui.valveTypeSelector.addItem(valveTypePresetName)
    self.ui.valveTypeSelector.connect("currentIndexChanged(int)", self.onValveTypeChanged)

    for cardiacCyclePhaseName in CARDIAC_CYCLE_PHASE_PRESETS.keys():
      self.ui.cardiacCyclePhaseSelector.addItem(cardiacCyclePhaseName)
    self.ui.cardiacCyclePhaseSelector.connect("currentIndexChanged(int)", self.onCardiacCyclePhaseChanged)

    self.ui.useCurrentFrameButton.connect("clicked()", self.onUseCurrentFrameButtonClicked)
    self.ui.goToAnalyzedFrameButton.connect("clicked()", self.onGoToAnalyzedFrameButtonClicked)

    #
    # View section
    #
    self.ui.viewCollapsibleButton.connect('toggled(bool)', lambda toggle: self.onWorkflowStepChanged(self.ui.viewCollapsibleButton, toggle))

    # Size policy cannot be set on Qt5 (https://github.com/commontk/CTK/issues/791)
    #self.ui.valveVolumeSelector.sizeAdjustPolicy = qt.QComboBox.AdjustToMinimumContentsLength
    self.ui.valveVolumeSelector.setMRMLScene(slicer.mrmlScene)
    self.ui.valveVolumeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onHeartValveVolumeSelect)

    for probePositionId, probePositionPreset in PROBE_POSITION_PRESETS.items():
      self.ui.probePositionSelector.addItem(probePositionPreset['name'], probePositionId)
      itemIndex = self.ui.probePositionSelector.findData(probePositionId)
      self.ui.probePositionSelector.setItemData(itemIndex, probePositionPreset['description'], qt.Qt.ToolTipRole)
    self.ui.probePositionSelector.connect("currentIndexChanged(int)", self.onProbePositionChanged)

    self.ui.displayFourUpViewButton.connect('clicked()', self.onResetAnnulusView)

    # Valve normalization - orientation
    self.ui.axialSliceToRasTransformOrientationSliderWidget.setMRMLScene(slicer.mrmlScene)
    # Setting of qMRMLTransformSliders.TypeOfTransform is not robust: it has to be set after setMRMLScene and
    # has to be set twice (with setting the type to something else in between).
    # Therefore the following 3 lines are needed, and needed here:
    #self.ui.axialSliceToRasTransformOrientationSliderWidget.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    #self.ui.axialSliceToRasTransformOrientationSliderWidget.TypeOfTransform = slicer.qMRMLTransformSliders.TRANSLATION
    #self.ui.axialSliceToRasTransformOrientationSliderWidget.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    self.ui.axialSliceToRasTransformOrientationSliderWidget.setMRMLTransformNode(None)

    #
    # Annulus contouring section
    #
    self.ui.contouringCollapsibleButton.connect('toggled(bool)', lambda toggle: self.onWorkflowStepChanged(self.ui.contouringCollapsibleButton, toggle))

    self.ui.placeButton.setIcon(qt.QIcon(":/Icons/MarkupsMouseModePlace.png"))
    self.ui.placeButton.connect('clicked(bool)', self.onActivateAnnulusMarkupPlacement)

    self.ui.deleteLastFiducialButton.setIcon(qt.QIcon(":/Icons/MarkupsDelete.png"))
    self.ui.deleteLastFiducialButton.connect('clicked()', self.onDeleteLastFiducialClicked)

    self.ui.deleteAllFiducialsButton.setIcon(qt.QIcon(":/Icons/MarkupsDeleteAllRows.png"))
    self.ui.deleteAllFiducialsButton.connect('clicked()', self.onDeleteAllFiducialsClicked)

    self.ui.orthogonalSlicerRotationSliderWidget.connect('valueChanged(double)', self.onOrthogonalSlicerRotationAngleChanged)

    if self.developerMode:
      self.ui.orthogonalSlicerRotationStepSizeSpinBox.value = 30

    self.ui.orthogonalSliceRotationAngleDecButton.connect('clicked(bool)', self.onOrthogonalSlicerRotationAngleDec)
    self.ui.orthogonalSliceRotationAngleIncButton.connect('clicked(bool)', self.onOrthogonalSlicerRotationAngleInc)

    self.ui.autoRotateButton.setIcon(qt.QIcon(":/Icons/ViewSpin.png"))
    self.ui.autoRotateButton.connect('clicked(bool)', self.onAutoRotateClicked)

    #
    # Annulus contouring adjustment section
    #
    self.ui.contourAdjustmentCollapsibleButton.connect('toggled(bool)', lambda toggle: self.onWorkflowStepChanged(self.ui.contourAdjustmentCollapsibleButton, toggle))

    self.ui.annulusMarkupAdjustmentList.setMRMLScene(slicer.mrmlScene)

    # Uncheck markup placement button if the placement or the markup list is not active anymore
    self.ui.annulusMarkupAdjustmentList.connect('activeMarkupsFiducialPlaceModeChanged(bool)', self.ui.placeButton.setChecked)
    self.ui.annulusMarkupAdjustmentList.connect('currentMarkupsFiducialSelectionChanged(int)', self.currentAnnulusMarkupPointSelectionChanged)

    self.ui.resampleSamplingDistanceSpinBox.connect("valueChanged(double)", self.onResampleSamplingDistanceChanged)
    self.ui.smoothContourFourierCoefficientsSpinBox.connect("valueChanged(int)", self.onSmoothContourFourierCoefficientsChanged)

    self.ui.smoothContourCheckbox.connect("stateChanged(int)", self.onSmoothingEnabledChanged)

    self.ui.smoothContourPreviewCheckbox.connect("toggled(bool)", self.setAnnulusContourPreviewActive)

    self.ui.restoreContourButton.connect('clicked()', self.onRestoreContourClicked)
    self.ui.resampleContourButton.connect('clicked()', self.onResampleContourClicked)

    #
    # Display section
    #
    #self.ui.displayCollapsibleButton.checked = False
    self.ui.displayCollapsibleButton.connect('toggled(bool)',
      lambda toggle: self.onWorkflowStepChanged(self.ui.displayCollapsibleButton, toggle))

    self.ui.annulusModelRadiusSliderWidget.connect('valueChanged(double)', self.onAnnulusModelRadiusChanged)

    # Adding GUI panels to group. This makes sure only one is open at a time.
    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.ui.viewCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.ui.contouringCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.ui.contourAdjustmentCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.ui.displayCollapsibleButton)

    self.ui.viewCollapsibleButton.setChecked(True)

    # Add vertical spacer
    self.layout.addStretch(1)

    # Define list of widgets for updateGUIFromParameterNode, updateParameterNodeFromGUI, and addGUIObservers
    self.nodeSelectorWidgets = {"HeartValve": self.ui.heartValveSelector}

    # Use singleton parameter node (it is created if does not exist yet)
    parameterNode = self.logic.getParameterNode()
    # Set parameter node (widget will observe it and also updates GUI)
    self.setAndObserveParameterNode(parameterNode)

    self.onHeartValveSelect(self.ui.heartValveSelector.currentNode())
    self.onWorkflowStepChanged(self.ui.viewCollapsibleButton, True)

    self.addGUIObservers()

  def cleanup(self):
    # Exit from any special workflow step
    self.onWorkflowStepChanged(self.ui.viewCollapsibleButton, True)
    self.removeGUIObservers()
    self.removeNodeObservers()
    self.setAndObserveParameterNode(None)
    if self.annulusContourPreviewModel:
      slicer.mrmlScene.RemoveNode(self.annulusContourPreviewModel)

  def removeNodeObservers(self):
    if self.annulusMarkupNode and self.annulusMarkupNodeObserver:
      self.annulusMarkupNode.RemoveObserver(self.annulusMarkupNodeObserver)
      self.annulusMarkupNodeObserver = None
    if self.axialSliceToRasTransformNode and self.axialSliceToRasTransformNodeObserver:
      self.axialSliceToRasTransformNode.RemoveObserver(self.axialSliceToRasTransformNodeObserver)
      self.axialSliceToRasTransformNodeObserver = None

  def updateGuiEnabled(self):
    valveModelSelected = self.valveModel is not None
    volumeSelected = self.valveModel is not None and self.valveModel.getValveVolumeNode() is not None
    self.ui.valveTypeSelector.setEnabled(valveModelSelected)
    self.ui.cardiacCyclePhaseSelector.setEnabled(valveModelSelected)
    self.ui.viewCollapsibleButton.setEnabled(valveModelSelected)
    self.ui.contouringCollapsibleButton.setEnabled(volumeSelected)
    self.ui.contourAdjustmentCollapsibleButton.setEnabled(volumeSelected)
    self.ui.axialSliceToRasTransformOrientationSliderWidget.setEnabled(volumeSelected)
    self.ui.displayFourUpViewButton.setEnabled(volumeSelected)
    self.ui.contourAdjustmentCollapsibleButton.setEnabled(valveModelSelected)
    self.ui.restoreContourButton.setEnabled(valveModelSelected and self.valveModel.hasStoredAnnulusContour())

  def getAnnulusContourModelNode(self):
    if self.valveModel is None:
      return None
    return self.valveModel.getAnnulusContourModelNode()

  def onWorkflowStepChanged(self, widget, toggle):

    if toggle:
      # Deactivate smoothing preview if not in contour adjustment
      if widget!=self.ui.contourAdjustmentCollapsibleButton:
        self.ui.smoothContourPreviewCheckbox.setChecked(False)
      # Activate placement mode when entering contouring, deactivate when exiting
      self.onActivateAnnulusMarkupPlacement(widget==self.ui.contouringCollapsibleButton)
      # Only allow fiducial moving in contouring or adjustment mode
      if self.annulusMarkupNode:
        self.annulusMarkupNode.SetLocked(not (widget==self.ui.contouringCollapsibleButton or widget==self.ui.contourAdjustmentCollapsibleButton))
        if self.valveModel:
          self.valveModel.setNonLabeledMarkupsVisibility(widget==self.ui.contouringCollapsibleButton or widget==self.ui.contourAdjustmentCollapsibleButton)
      # Hide annulus slice intersection in contouring mode (it is confusing to see something in the slice views while still just adding points)
      if self.getAnnulusContourModelNode():
        self.getAnnulusContourModelNode().GetDisplayNode().SetVisibility2D(widget!=self.ui.contouringCollapsibleButton)
        self.getAnnulusContourModelNode().GetDisplayNode().SetSliceIntersectionThickness(4)

    # View step
    if widget==self.ui.viewCollapsibleButton:
      if toggle:
        # set up viewers
        self.onDisplayFourUpView(resetViewOrientations=True)
      else:
        # re-center and re-orient view based on axialSliceToRas transform
        self.updateAxialSliceToRasCenterFromSliceViewIntersections()
        #self.onAxialSliceToRasTransformNodeModified()

    # Contour adjustment step
    if toggle and widget==self.ui.contourAdjustmentCollapsibleButton:
      qt.QTimer.singleShot(0, self.ui.annulusMarkupAdjustmentList.tableWidget().setFocus)
      qt.QTimer.singleShot(0, lambda: self.ui.annulusMarkupAdjustmentList.highlightNthFiducial(0))
      # Hide all slice views from 3D
      HeartValveLib.showSlices(False)

    if toggle and widget==self.ui.displayCollapsibleButton:
      # Contour editing centers on the selected contour point.
      # When we finish with that, go back to the default view
      self.onDisplayFourUpView(resetViewOrientations=True)

  def enter(self):
    logging.debug("Enter %s" % self.moduleName)

  def exit(self):
    logging.debug("Exit %s" % self.moduleName)
    # change workflow step to force state update
    self.ui.viewCollapsibleButton.checked = True
    if self.valveModel and self.getNumberOfDefinedControlPoints(self.valveModel.getAnnulusContourMarkupNode())>0:
      # there are fiducials already - probably the contour is already defined, so start in display mode
      self.ui.displayCollapsibleButton.checked = True

  def setAndObserveParameterNode(self, parameterNode):
    if parameterNode is self.parameterNode and self.parameterNodeObserver:
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

  def updateParameterNodeFromGUI(self):
    parameterNode = self.getParameterNode()
    oldModifiedState = parameterNode.StartModify()
    parameterNode.EndModify(oldModifiedState)

  def addGUIObservers(self):
    pass

  def removeGUIObservers(self):
    pass

  def onHeartValveSelect(self, node):
    logging.debug("Selected heart valve node: {0}".format(node.GetName() if node else "None"))

    # Go to display step before switching to another valve (but only if the current node is valid
    # otherwise we could get errors when valve is set to None because the scene is closing)
    if self.valveModel and self.valveModel.getAxialSliceToRasTransformNode():
      self.ui.displayCollapsibleButton.checked = True

    self.setHeartValveNode(node)

    self.updateGuiEnabled()
    if node:
      # change workflow step to force state update
      self.ui.viewCollapsibleButton.checked = True
      if self.getNumberOfDefinedControlPoints(self.valveModel.getAnnulusContourMarkupNode())>0:
        # there are fiducials already - probably the contour is already defined, so start in display mode
        self.ui.displayCollapsibleButton.checked = True

  def setHeartValveNode(self, heartValveNode):
    if self.valveModel and self.valveModel.getHeartValveNode() == heartValveNode:
      return

    self.valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)

    # Observe nodes
    annulusMarkupNode = self.valveModel.getAnnulusContourMarkupNode() if self.valveModel else None
    self.setAndObserveAnnulusMarkupNode(annulusMarkupNode)

    axialSliceToRasTransformNode = self.valveModel.getAxialSliceToRasTransformNode() if self.valveModel else None
    self.setAndObserveAxialSliceToRasTransformNode(axialSliceToRasTransformNode)

    valveVolumeNode = None
    if self.valveModel:
      valveVolumeNode = self.valveModel.getValveVolumeNode()
      if not valveVolumeNode:
        # select background volume by default as valve volume (to spare a click for the user)
        appLogic = slicer.app.applicationLogic()
        selNode = appLogic.GetSelectionNode()
        if selNode.GetActiveVolumeID():
          valveVolumeNode = slicer.mrmlScene.GetNodeByID(selNode.GetActiveVolumeID())
          self.valveModel.setValveVolumeNode(valveVolumeNode)

    wasBlocked = self.ui.valveVolumeSelector.blockSignals(True)
    self.ui.valveVolumeSelector.setCurrentNode(valveVolumeNode)
    self.ui.valveVolumeSelector.blockSignals(wasBlocked)

    wasBlocked = self.ui.annulusModelRadiusSliderWidget.blockSignals(True)
    self.ui.annulusModelRadiusSliderWidget.value = self.valveModel.getAnnulusContourRadius() if self.valveModel else 5.0
    self.ui.annulusModelRadiusSliderWidget.blockSignals(wasBlocked)

    wasBlocked = self.ui.probePositionSelector.blockSignals(True)
    probePositionIndex = self.ui.probePositionSelector.findData(self.valveModel.getProbePosition())  if self.valveModel else 0
    self.ui.probePositionSelector.setCurrentIndex(probePositionIndex)
    self.ui.probePositionSelector.blockSignals(wasBlocked)

    wasBlocked = self.ui.valveTypeSelector.blockSignals(True)
    valveTypeIndex = self.ui.valveTypeSelector.findText(self.valveModel.getValveType()) if self.valveModel else 0
    self.ui.valveTypeSelector.setCurrentIndex(valveTypeIndex)
    self.ui.valveTypeSelector.blockSignals(wasBlocked)

    wasBlocked = self.ui.cardiacCyclePhaseSelector.blockSignals(True)
    cardiacCyclePhaseIndex = self.ui.cardiacCyclePhaseSelector.findText(self.valveModel.getCardiacCyclePhase()) if self.valveModel else 0
    self.ui.cardiacCyclePhaseSelector.setCurrentIndex(cardiacCyclePhaseIndex)
    self.ui.cardiacCyclePhaseSelector.blockSignals(wasBlocked)

    wasBlocked = self.ui.cardiacCyclePhaseSelector.blockSignals(True)
    cardiacCyclePhaseIndex = self.ui.cardiacCyclePhaseSelector.findText(
      self.valveModel.getCardiacCyclePhase()) if self.valveModel else 0
    self.ui.cardiacCyclePhaseSelector.setCurrentIndex(cardiacCyclePhaseIndex)
    self.ui.cardiacCyclePhaseSelector.blockSignals(wasBlocked)

    valveVolumeSequenceIndexStr = self.valveModel.getVolumeSequenceIndexAsDisplayedString(self.valveModel.getValveVolumeSequenceIndex()) if self.valveModel else ""
    self.ui.valveVolumeSequenceIndexValue.setText(valveVolumeSequenceIndexStr)

    self.onDisplayFourUpView(resetViewOrientations=True, resetFov=True)
    self.updateGuiEnabled()
    self.onGoToAnalyzedFrameButtonClicked()

  def setAndObserveAxialSliceToRasTransformNode(self, axialSliceToRasTransformNode):
    logging.debug("Observe annulus to probe transform node: {0}".format(axialSliceToRasTransformNode.GetName() if axialSliceToRasTransformNode else "None"))
    if axialSliceToRasTransformNode == self.axialSliceToRasTransformNode and self.axialSliceToRasTransformNodeObserver:
      # no change and node is already observed
      logging.debug("Already observed")
      return

    # Remove observer to old node
    if self.axialSliceToRasTransformNode and self.axialSliceToRasTransformNodeObserver:
      self.axialSliceToRasTransformNode.RemoveObserver(self.axialSliceToRasTransformNodeObserver)
      self.axialSliceToRasTransformNodeObserver = None
    # Set and observe new node
    self.axialSliceToRasTransformNode = axialSliceToRasTransformNode
    if self.axialSliceToRasTransformNode:
      self.axialSliceToRasTransformNodeObserver = self.axialSliceToRasTransformNode.AddObserver(
        slicer.vtkMRMLTransformableNode.TransformModifiedEvent, self.onAxialSliceToRasTransformNodeModified)
    self.ui.axialSliceToRasTransformOrientationSliderWidget.setMRMLTransformNode(axialSliceToRasTransformNode)

    # Initial update
    self.onAxialSliceToRasTransformNodeModified()

  def updateAxialSliceToRasCenterFromSliceViewIntersections(self):
    """Make the axial slice center the intersection of all slices"""
    if not self.valveModel:
      return

    intersectionPoint = self.logic.getPlaneIntersectionPoint(self.axialSlice, self.orthogonalSlice1, self.orthogonalSlice2)
    axialSliceToRasTransformNode = self.valveModel.getAxialSliceToRasTransformNode()
    axialSliceToRasTransformMatrix = vtk.vtkMatrix4x4()
    axialSliceToRasTransformNode.GetMatrixTransformToParent(axialSliceToRasTransformMatrix)
    if (math.fabs(axialSliceToRasTransformMatrix.GetElement(0, 3) - intersectionPoint[0]) > 0.1
        or math.fabs(axialSliceToRasTransformMatrix.GetElement(1, 3) - intersectionPoint[1]) > 0.1
        or math.fabs(axialSliceToRasTransformMatrix.GetElement(2, 3) - intersectionPoint[2]) > 0.1):
      # origin changed
      axialSliceToRasTransformMatrix.SetElement(0, 3, intersectionPoint[0])
      axialSliceToRasTransformMatrix.SetElement(1, 3, intersectionPoint[1])
      axialSliceToRasTransformMatrix.SetElement(2, 3, intersectionPoint[2])
      axialSliceToRasTransformNode.SetMatrixTransformToParent(axialSliceToRasTransformMatrix)

  def onAxialSliceToRasTransformNodeModified(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    # Update slice center
    self.updateAxialSliceToRasCenterFromSliceViewIntersections()
    # Align orthogonal slices
    self.setNewRotationValue(0)

  def setAndObserveAnnulusMarkupNode(self, annulusMarkupNode):
    logging.debug("Observe annulus markup node: {0}".format(annulusMarkupNode.GetName() if annulusMarkupNode else "None"))
    if annulusMarkupNode == self.annulusMarkupNode and self.annulusMarkupNodeObserver:
      # no change and node is already observed
      logging.debug("Already observed")
      return
    # Remove observer to old node
    if self.annulusMarkupNode and self.annulusMarkupNodeObserver:
      self.annulusMarkupNode.RemoveObserver(self.annulusMarkupNodeObserver)
      self.annulusMarkupNodeObserver = None
    # Set and observe new node
    self.annulusMarkupNode = annulusMarkupNode
    if self.annulusMarkupNode:
      self.annulusMarkupNodeObserver = \
        self.annulusMarkupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                                           self.onAnnulusMarkupNodeModified)

    self.ui.annulusMarkupAdjustmentList.setCurrentNode(self.annulusMarkupNode)
    # Hide label column, annulus labels are specified in a different markup list
    # It can only be done here, after a node is set because columns may be re-created when a new node is set.
    self.ui.annulusMarkupAdjustmentList.tableWidget().setColumnHidden(0,True)
    # Update model
    self.onAnnulusMarkupNodeModified()

  def onAnnulusMarkupNodeModified(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    if not self.annulusMarkupNode:
      self.ui.deleteLastFiducialButton.setEnabled(False)
      self.ui.deleteAllFiducialsButton.setEnabled(False)
      return

    numberOfPoints = self.getNumberOfDefinedControlPoints(self.annulusMarkupNode)
    if numberOfPoints>0:
      self.ui.deleteLastFiducialButton.setEnabled(True)
      self.ui.deleteAllFiducialsButton.setEnabled(True)

    if self.ui.autoRotateButton.checked:
      if numberOfPoints-self.autoRotateStartNumberOfPoints >= 360/self.ui.orthogonalSlicerRotationStepSizeSpinBox.value:
        logging.debug("Finished contouring")
        self.ui.placeButton.setChecked(False)
        self.onActivateAnnulusMarkupPlacement(False)
        self.ui.autoRotateButton.setChecked(False)
        self.ui.contourAdjustmentCollapsibleButton.checked = True
      else:
        orthogonalSliceRotationValue = self.autoRotateStartAngle + int((numberOfPoints-self.autoRotateStartNumberOfPoints)/self.autoRotatePointsPerSlice) * self.ui.orthogonalSlicerRotationStepSizeSpinBox.value
        # wrap around
        if orthogonalSliceRotationValue > self.ui.orthogonalSlicerRotationSliderWidget.maximum:
          orthogonalSliceRotationValue = orthogonalSliceRotationValue - (self.ui.orthogonalSlicerRotationSliderWidget.maximum - self.ui.orthogonalSlicerRotationSliderWidget.minimum)
        if self.ui.orthogonalSlicerRotationSliderWidget.value != orthogonalSliceRotationValue:
          wasBlocked = self.ui.orthogonalSlicerRotationSliderWidget.blockSignals(True)
          self.ui.orthogonalSlicerRotationSliderWidget.value = orthogonalSliceRotationValue
          self.setNewRotationValue(orthogonalSliceRotationValue)
          self.ui.orthogonalSlicerRotationSliderWidget.blockSignals(wasBlocked)

    if self.ui.contourAdjustmentCollapsibleButton.checked:
      self.trackFiducialInSliceView()

    self.valveModel.updateAnnulusContourModel()
    self.updateAnnulusContourPreviewModel()

    # TODO
    #self.valveModel.updateAnnulusPlaneModel()

  def onHeartValveVolumeSelect(self, valveVolumeNode):
    if self.valveModel is None:
      return
    self.valveModel.setValveVolumeNode(valveVolumeNode)
    self.onDisplayFourUpView(resetViewOrientations = True, resetFov = True)
    self.updateGuiEnabled()

  def onResampleSamplingDistanceChanged(self):
    self.updateAnnulusContourPreviewModel()

  def onSmoothContourFourierCoefficientsChanged(self, value):
    self.updateAnnulusContourPreviewModel()

  def onSmoothingEnabledChanged(self, state):
    self.updateAnnulusContourPreviewModel()
    self.ui.smoothContourFourierCoefficientsSpinBox.enabled = self.ui.smoothContourCheckbox.checked

  def updateAnnulusContourPreviewModel(self):
    if not self.annulusContourPreviewActive:
      return

    annulusContourMarkupPositionsArray = slicer.util.arrayFromMarkupsControlPoints(self.valveModel.getAnnulusContourMarkupNode())
    slicer.util.updateMarkupsControlPointsFromArray(self.annulusContourPreviewControlPoints, annulusContourMarkupPositionsArray)

    self.annulusContourPreviewCurve.updateCurve()
    if self.ui.smoothContourCheckbox.checked:
      self.annulusContourPreviewCurve.smoothCurveFourier(self.ui.smoothContourFourierCoefficientsSpinBox.value,
                                                         self.ui.resampleSamplingDistanceSpinBox.value)
    else:
      self.annulusContourPreviewCurve.resampleCurve(self.ui.resampleSamplingDistanceSpinBox.value)
    self.annulusContourPreviewCurve.updateCurve()

  def setAnnulusContourPreviewActive(self, active):
    if self.annulusContourPreviewActive == active:
      return
    self.annulusContourPreviewActive = active
    self.updateAnnulusContourPreviewModel()
    if self.getAnnulusContourModelNode():
      self.getAnnulusContourModelNode().GetDisplayNode().SetVisibility(not self.annulusContourPreviewActive)
    annulusContourPreviewDisplayNode = self.annulusContourPreviewCurve.curveModelNode.GetDisplayNode()
    if not annulusContourPreviewDisplayNode:
      if not self.annulusContourPreviewCurve.curveModelNode.GetScene():
        slicer.mrmlScene.AddNode(self.annulusContourPreviewCurve.curveModelNode)
      self.annulusContourPreviewCurve.curveModelNode.CreateDefaultDisplayNodes()
      annulusContourPreviewDisplayNode = self.annulusContourPreviewCurve.curveModelNode.GetDisplayNode()
    annulusContourPreviewDisplayNode.SetVisibility(self.annulusContourPreviewActive)
    annulusContourPreviewDisplayNode.SetVisibility2D(True)
    annulusContourPreviewDisplayNode.SetSliceIntersectionThickness(4)
    probeToRasTransformNodeId = None
    if self.valveModel and self.valveModel.getProbeToRasTransformNode():
      probeToRasTransformNodeId = self.valveModel.getProbeToRasTransformNode().GetID()
    self.annulusContourPreviewCurve.curveModelNode.SetAndObserveTransformNodeID(probeToRasTransformNodeId)
    # Show markups as cross hair in preview mode to make sure they don't obstruct the preview line
    if self.valveModel and self.valveModel.getAnnulusContourMarkupNode():
      markupDisplayNode = self.valveModel.getAnnulusContourMarkupNode().GetDisplayNode()
      markupDisplayNode.SetGlyphType(markupDisplayNode.Cross2D if self.annulusContourPreviewActive else markupDisplayNode.Sphere3D)

  def currentAnnulusMarkupPointSelectionChanged(self, markupIndex):
    nOfControlPoints = self.getNumberOfDefinedControlPoints(self.annulusMarkupNode) if self.annulusMarkupNode else 0
    for i in range(nOfControlPoints):
      try:
        # Current API (Slicer-4.13 February 2022)
        self.annulusMarkupNode.SetNthControlPointSelected(i, i==markupIndex)
      except:
        # Legacy API
        self.annulusMarkupNode.SetNthFiducialSelected(i, i==markupIndex)

  def onAnnulusModelRadiusChanged(self, radius):
    if not self.valveModel:
      return

    self.valveModel.setAnnulusContourRadius(radius)
    self.valveModel.updateAnnulusContourModel()

  def onOrthogonalSlicerRotationAngleDec(self):
    orthogonalSliceRotationValue = self.ui.orthogonalSlicerRotationSliderWidget.value
    orthogonalSliceRotationValue = orthogonalSliceRotationValue - self.ui.orthogonalSlicerRotationStepSizeSpinBox.value
    # wrap around
    if orthogonalSliceRotationValue < self.ui.orthogonalSlicerRotationSliderWidget.minimum:
      orthogonalSliceRotationValue = orthogonalSliceRotationValue + (self.ui.orthogonalSlicerRotationSliderWidget.maximum - self.ui.orthogonalSlicerRotationSliderWidget.minimum)
    self.ui.orthogonalSlicerRotationSliderWidget.value = orthogonalSliceRotationValue
    self.ui.autoRotateButton.setChecked(False)

  def onOrthogonalSlicerRotationAngleInc(self):
    orthogonalSliceRotationValue = self.ui.orthogonalSlicerRotationSliderWidget.value
    orthogonalSliceRotationValue = orthogonalSliceRotationValue + self.ui.orthogonalSlicerRotationStepSizeSpinBox.value
    # wrap around
    if orthogonalSliceRotationValue > self.ui.orthogonalSlicerRotationSliderWidget.maximum:
      orthogonalSliceRotationValue = orthogonalSliceRotationValue - (self.ui.orthogonalSlicerRotationSliderWidget.maximum - self.ui.orthogonalSlicerRotationSliderWidget.minimum)
    self.ui.orthogonalSlicerRotationSliderWidget.value = orthogonalSliceRotationValue
    self.ui.autoRotateButton.setChecked(False)

  def onOrthogonalSlicerRotationAngleChanged(self, newRotationValue):
    self.setNewRotationValue(newRotationValue)
    self.ui.autoRotateButton.setChecked(False)

  def setNewRotationValue(self, newRotationValue):
    if not self.valveModel:
      return
    self.valveModel.setSliceOrientations(self.axialSlice, self.orthogonalSlice1, self.orthogonalSlice2, newRotationValue)
    return True

  def onAutoRotateClicked(self, pushed):
    if pushed:
      self.autoRotateStartAngle = self.ui.orthogonalSlicerRotationSliderWidget.value
      self.autoRotateStartNumberOfPoints = self.getNumberOfDefinedControlPoints(self.annulusMarkupNode) if self.annulusMarkupNode else 0

  def onResetAnnulusView(self):
    if self.valveModel is None:
      return
    self.axialSliceToRasTransformNode.SetMatrixTransformToParent(self.valveModel.getDefaultAxialSliceToRasTransformMatrix())
    self.onDisplayFourUpView(resetViewOrientations = True, resetFov = True)

  def onCardiacCyclePhaseChanged(self):
    if self.valveModel is None:
      return
    cardiacCyclePhase = self.ui.cardiacCyclePhaseSelector.currentText
    self.valveModel.setCardiacCyclePhase(cardiacCyclePhase)

  def onValveTypeChanged(self):
    if self.valveModel is None:
      return
    valveType = self.ui.valveTypeSelector.currentText
    self.valveModel.setValveType(valveType)

  def onUseCurrentFrameButtonClicked(self):
    if self.valveModel is None:
      return
    valveVolumeSequenceIndex = self.valveModel.getDisplayedValveVolumeSequenceIndex()
    self.setValveVolumeSequenceIndex(valveVolumeSequenceIndex)

  def setValveVolumeSequenceIndex(self, valveVolumeSequenceIndex):
    if self.valveModel:
      self.valveModel.setValveVolumeSequenceIndex(valveVolumeSequenceIndex)
      valveVolumeSequenceIndexStr = self.valveModel.getVolumeSequenceIndexAsDisplayedString(valveVolumeSequenceIndex)
    else:
      valveVolumeSequenceIndexStr = ""
    self.ui.valveVolumeSequenceIndexValue.setText(valveVolumeSequenceIndexStr)

  def onGoToAnalyzedFrameButtonClicked(self):
    HeartValveLib.goToAnalyzedFrame(self.valveModel)

  def onProbePositionChanged(self):
    probePosition = self.ui.probePositionSelector.itemData(self.ui.probePositionSelector.currentIndex)
    self.valveModel.setProbePosition(probePosition)
    self.axialSliceToRasTransformNode.SetMatrixTransformToParent(self.valveModel.getDefaultAxialSliceToRasTransformMatrix())
    self.onDisplayFourUpView(resetViewOrientations = True, resetFov = True)

  def onDisplayFourUpView(self, resetFov = False, resetViewOrientations = False):
    # Switch to default cardiac 4-up layout
    HeartValveLib.setupDefaultLayout()

    # Show valve volume as background volume
    if self.valveModel and self.valveModel.getValveVolumeNode():
      valveVolumeNode = self.valveModel.getValveVolumeNode()
      if valveVolumeNode.GetImageData():
        # Show volume in slice viewers
        appLogic = slicer.app.applicationLogic()
        selNode = appLogic.GetSelectionNode()
        # Updating the volume resets the FOV, so only do it when the volume is changed
        if selNode.GetActiveVolumeID() != valveVolumeNode.GetID():
          selNode.SetReferenceActiveVolumeID(valveVolumeNode.GetID())
          appLogic.PropagateVolumeSelection()
      else:
        logging.warning('onResetAnnulusView failed: valve volume does not contain a valid image')

    if resetViewOrientations and self.valveModel:
      HeartValveLib.setupDefaultSliceOrientation(resetFov = resetFov, valveModel = self.valveModel)

  def onActivateAnnulusMarkupPlacement(self, pushed):
    self.ui.annulusMarkupAdjustmentList.placeActive(pushed)
    if not pushed:
      return

    # Check/update ValveVolumeSequenceIndex
    currentValveVolumeSequenceIndex = self.valveModel.getValveVolumeSequenceIndex()
    displayedValveVolumeSequenceIndex = self.valveModel.getDisplayedValveVolumeSequenceIndex()
    if currentValveVolumeSequenceIndex < 0:
      # analyzed frame has not been set yet, set it now
      self.setValveVolumeSequenceIndex(displayedValveVolumeSequenceIndex)
    else:
      # analyzed frame has been already set, check if it is consistent
      if displayedValveVolumeSequenceIndex != currentValveVolumeSequenceIndex:
        updateValveVolumeSequenceIndex = slicer.util.confirmOkCancelDisplay("Currently displayed frame {0} is not the same as valve volume index {1}. Click OK to update valve volume index.".format(
          self.valveModel.getVolumeSequenceIndexAsDisplayedString(displayedValveVolumeSequenceIndex),
          self.valveModel.getVolumeSequenceIndexAsDisplayedString(currentValveVolumeSequenceIndex)
        ))
        if updateValveVolumeSequenceIndex:
          # OK to update
          self.setValveVolumeSequenceIndex(displayedValveVolumeSequenceIndex)
        else:
          # Cancel
          self.ui.annulusMarkupAdjustmentList.placeActive(False)
          self.ui.placeButton.setChecked(False)
          #qt.QTimer.singleShot(0, lambda: self.ui.placeButton.setChecked(False))
          return

    slicer.app.applicationLogic().GetInteractionNode().SetPlaceModePersistence(1)
    if self.getNumberOfDefinedControlPoints(self.annulusMarkupNode)==0:
      self.ui.autoRotateButton.setChecked(True)
    if self.ui.autoRotateButton.isChecked():
      # forces the slice to the first rotation position
      self.onAnnulusMarkupNodeModified()

  def onDeleteLastFiducialClicked(self):
    numberOfPoints = self.getNumberOfDefinedControlPoints(self.annulusMarkupNode)
    self.annulusMarkupNode.RemoveNthControlPoint(numberOfPoints-1)
    if numberOfPoints<=1:
        self.ui.deleteLastFiducialButton.setEnabled(False)
        self.ui.deleteAllFiducialsButton.setEnabled(False)

  def onDeleteAllFiducialsClicked(self):
    try:
      # Current API (Slicer-4.13 February 2022)
      self.annulusMarkupNode.RemoveAllControlPoints()
    except:
      # Legacy API
      self.annulusMarkupNode.RemoveAllMarkups()
    self.ui.deleteLastFiducialButton.setEnabled(False)
    self.ui.deleteAllFiducialsButton.setEnabled(False)

  def trackFiducialInSliceView(self):

    # Get the view where the user is dragging the markup and don't change that view
    # (it would move the image while the user is marking a point on it and so the screw would drift)
    excludeSliceView = self.annulusMarkupNode.GetAttribute('Markups.MovingInSliceView')
    movingMarkupIndex = self.annulusMarkupNode.GetAttribute('Markups.MovingMarkupIndex')

    if not excludeSliceView or movingMarkupIndex is None or movingMarkupIndex == '':
      return

    try:
      jumpLocation = [0,0,0,1]
      self.annulusMarkupNode.GetMarkupPointWorld(int(movingMarkupIndex), 0, jumpLocation)
    except:
      # Slicer-4.11
      jumpLocation = [0,0,0]
      self.annulusMarkupNode.GetNthControlPointPositionWorld(int(movingMarkupIndex), jumpLocation)

    sliceNodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLSliceNode")
    sliceNodes.UnRegister(None)  # GetNodesByClass returns a new collection
    sliceNodes.InitTraversal()
    while True:
      sliceNode = sliceNodes.GetNextItemAsObject()
      if not sliceNode:
        # end of traversal
        break
      if sliceNode.GetLayoutName() == excludeSliceView:
        continue
      if sliceNode.GetID() == excludeSliceView:  # Some Slicer-4.11 versions saved node ID instead of layout name
        continue
      sliceNode.JumpSliceByCentering(jumpLocation[0],jumpLocation[1],jumpLocation[2])

  def onReload(self):
    logging.debug("Reloading ValveAnnulusAnalysis")

    packageName='HeartValveLib'
    submoduleNames=['util', 'LeafletModel', 'SmoothCurve', 'ValveRoi', 'PapillaryModel', 'ValveModel', 'HeartValves']
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

  def onResampleContourClicked(self):
    self.ui.smoothContourPreviewCheckbox.setChecked(False)
    if self.valveModel.hasStoredAnnulusContour():
      if slicer.util.confirmYesNoDisplay("Found previously stored annulus contour points. "
                                         "Do you want to overwrite them with the currently listed coordinates?"):
        self.valveModel.storeAnnulusContour()
    else:
      self.valveModel.storeAnnulusContour()
    if self.ui.smoothContourCheckbox.checked:
      self.valveModel.smoothAnnulusContour(self.ui.smoothContourFourierCoefficientsSpinBox.value, self.ui.resampleSamplingDistanceSpinBox.value)
    else:
      self.valveModel.resampleAnnulusContourMarkups(self.ui.resampleSamplingDistanceSpinBox.value)
    self.updateGuiEnabled()

  def onRestoreContourClicked(self):
    if slicer.util.confirmYesNoDisplay("Do you want to restore the previously saved annulus contour coordinates?"):
      self.valveModel.restoreAnnulusContour()
      self.annulusContourPreviewCurve.updateCurve()

  def getNumberOfDefinedControlPoints(self, markupsNode):
    return markupsNode.GetNumberOfDefinedControlPoints()

#
# ValveAnnulusAnalysisLogic
#

class ValveAnnulusAnalysisLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)

  def getPlaneIntersectionPoint(self, axialNode, ortho1Node, ortho2Node):
    """
    Compute the center of rotation (common intersection point of the three planes)
    http://mathworld.wolfram.com/Plane-PlaneIntersection.html
    Copied from ValveViewLogic to remove dependency on SlicerHeart extension.
    """

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


class ValveAnnulusAnalysisTest(ScriptedLoadableModuleTest):
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
    self.test_Mitral()

  def test_Mitral(self):
    import numpy as np

    self.delayDisplay("Start test_Mitral.")

    slicer.util.selectModule('ValveAnnulusAnalysis')
    slicer.mrmlScene.Clear(0)
    slicer.app.processEvents()

    # Common between all valves
    valveVolumeSequenceBrowser = self.loadValveSampleData(sampleDataName = "Mitral")
    cardiacCyclePhase = "mid-systole"
    analyzedFrame = 5
    probePosition = "TTE apical"

    # -------------------------------------------
    self.delayDisplay("Define mitral valve")

    valveType = "mitral"

    # Get this setting the valve orientation sliders and then calling:
    #   arrayFromTransformMatrix(getNode('AxialSliceToRasTransform'))
    # then replace translation values by valve center position
    axialSliceToRasTransformMatrixArray = np.array([[-0.9868942 , -0.0809964 , -0.13957089,  -9.8],
        [-0.15818841,  0.65649567,  0.73755669,  -9.9],
        [ 0.03188845,  0.74996838, -0.66070422,  13.7],
        [ 0.        ,  0.        ,  0.        ,  1.        ]])

    # Get this by copying `AnnulusContourMarkup` points to new closed curve node `CC`,
    # resample to 12 control points, and call:  arrayFromMarkupsControlPoints(getNode("CC"))
    annulusMarkupControlPointsArray = np.array([[ 86.98819733,  84.78613281,  99.99595642],
        [ 87.25099182,  92.59313202,  96.04943085],
        [ 91.62657166, 100.28668976,  95.93429565],
        [ 99.54394531, 103.84978485,  97.02439117],
        [108.43112183, 102.99208069,  97.06322479],
        [116.29380035,  98.95796204,  96.59480286],
        [119.3833847 ,  90.8775177 ,  95.25667572],
        [117.54264832,  82.43365479,  93.17087555],
        [111.96864319,  75.6263504 ,  92.28639984],
        [104.68697357,  72.24358368,  95.78388977],
        [ 98.42464447,  73.57678986, 101.90380859],
        [ 91.8348999 ,  78.74420166, 104.18357086]])

    self.runSingleCase(valveVolumeSequenceBrowser, cardiacCyclePhase, analyzedFrame, probePosition,
                       valveType, axialSliceToRasTransformMatrixArray, annulusMarkupControlPointsArray)

    # -------------------------------------------
    self.delayDisplay("Define aortic valve (needed for additional valve quantification metrics")

    valveType = "aortic"

    # Get this setting the valve orientation sliders and then calling:
    #   arrayFromTransformMatrix(getNode('AxialSliceToRasTransform_1'))
    axialSliceToRasTransformMatrixArray = np.array([[-0.69571977, -0.3869726 , -0.60516677, 15.09743333],
       [-0.5315348 ,  0.84402519,  0.07135991, -1.35907367],
       [ 0.48316164,  0.3713134 , -0.79289388, 26.04229844],
       [ 0.        ,  0.        ,  0.        ,  1.        ]])

    # Get this by copying `AnnulusContourMarkup` points to new closed curve node `CC`,
    # resample to 12 control points, and call:  arrayFromMarkupsControlPoints(getNode("CC"))
    annulusMarkupControlPointsArray = np.array([[ 87.46756744,  79.60205078, 104.07534027],
       [ 93.12380981,  77.26019287, 104.3655014 ],
       [ 97.81135559,  73.91616058, 102.28562927],
       [ 99.61608124,  69.64796448,  98.37429047],
       [ 97.99498749,  65.67282104,  93.99780273],
       [ 94.39620972,  63.33256149,  89.6190567 ],
       [ 89.01432037,  63.26695633,  86.80841064],
       [ 83.31873322,  65.43260193,  87.0610199 ],
       [ 79.13238525,  69.24201202,  89.41408539],
       [ 77.02110291,  73.69961548,  93.07071686],
       [ 77.78422546,  77.62684631,  97.65192413],
       [ 81.85909271,  79.77548218, 101.64229584]])

    self.runSingleCase(valveVolumeSequenceBrowser, cardiacCyclePhase, analyzedFrame, probePosition,
                       valveType, axialSliceToRasTransformMatrixArray, annulusMarkupControlPointsArray)

    self.delayDisplay("Completed test_Mitral.")

  def loadValveSampleData(self, sampleDataName):
    """Returns sequence browser node"""

    self.delayDisplay("Load image sequence")

    import SampleData
    SampleData.SampleDataLogic().downloadSample(sampleDataName)

    # Remove the leaflet segmentation (we don't use it)
    segmentationNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")
    slicer.mrmlScene.RemoveNode(segmentationNode)

    valveVolumeSequence = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSequenceNode")
    sequencesLogic = slicer.util.getModuleLogic('Sequences')
    valveVolumeSequenceBrowser = sequencesLogic.GetFirstBrowserNodeForSequenceNode(valveVolumeSequence)
    #valveVolume = valveVolumeSequenceBrowser.GetProxyNode(valveVolumeSequence)

    return valveVolumeSequenceBrowser

  def runSingleCase(self, valveVolumeSequenceBrowser, cardiacCyclePhase, analyzedFrame, probePosition,
                    valveType, axialSliceToRasTransformMatrixArray, annulusMarkupControlPointsArray):

    import time
    import numpy as np
    import ValveModel
    import HeartValveLib
        
    ################################

    valveAnnulusAnalysisGui = slicer.modules.ValveAnnulusAnalysisWidget

    axialSlice = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeRed')
    orthogonalSlice1 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeYellow')
    orthogonalSlice2 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeGreen')

    # -------------------------------------------
    self.delayDisplay("Setup heart valve node")

    heartValveNode = valveAnnulusAnalysisGui.ui.heartValveSelector.addNode()

    valveAnnulusAnalysisGui.ui.heartValveSelector.setCurrentNode(heartValveNode)
    valveAnnulusAnalysisGui.ui.valveTypeSelector.currentText = valveType
    valveAnnulusAnalysisGui.ui.cardiacCyclePhaseSelector.currentText = cardiacCyclePhase

    # -------------------------------------------
    self.delayDisplay("Select analysis frame")

    # Simulate some frame browsing
    for frameIndex in range(10):
        valveVolumeSequenceBrowser.SetSelectedItemNumber(frameIndex)
        slicer.app.processEvents()
        time.sleep(0.3)

    # Jump to the analysis frame prescribed for this test
    valveVolumeSequenceBrowser.SetSelectedItemNumber(analyzedFrame)
    valveAnnulusAnalysisGui.ui.useCurrentFrameButton.click()

    # -------------------------------------------
    self.delayDisplay("Set image orientation")


    valveAnnulusAnalysisGui.ui.probePositionSelector.currentText = probePosition

    # Set valve center
    sliceIntersectionPosition = axialSliceToRasTransformMatrixArray[0:3,3]
    slicer.modules.markups.logic().JumpSlicesToLocation(*sliceIntersectionPosition, False)

    # Simulate some manual orientation changes
    lrSlider = slicer.util.findChild(valveAnnulusAnalysisGui.ui.axialSliceToRasTransformOrientationSliderWidget, "LRSlider")
    paSlider = slicer.util.findChild(valveAnnulusAnalysisGui.ui.axialSliceToRasTransformOrientationSliderWidget, "PASlider")
    isSlider = slicer.util.findChild(valveAnnulusAnalysisGui.ui.axialSliceToRasTransformOrientationSliderWidget, "ISSlider")
    for angle in range(10):
        lrSlider.value += 1
        paSlider.value -= 0.2
        #isSlider.value += 0.3
        slicer.app.processEvents()
        time.sleep(0.1)

    # Jump to the slice positions and orientations prescribed for this test
    # set axialSliceToRasTransform 
    axialSliceToRasTransformNode = heartValveNode.GetNodeReference("AxialSliceToRasTransform")
    slicer.util.updateTransformMatrixFromArray(axialSliceToRasTransformNode, axialSliceToRasTransformMatrixArray)
    # update slice view positions and orientations accordingly
    valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)
    valveModel.setSlicePositionAndOrientation(axialSlice, orthogonalSlice1, orthogonalSlice2, sliceIntersectionPosition, 0)

    # -------------------------------------------
    self.delayDisplay("Specify contour points")

    valveAnnulusAnalysisGui.ui.contouringCollapsibleButton.collapsed = False

    # Place control points
    annulusMarkupNode = heartValveNode.GetNodeReference("AnnulusContourPoints")
    for pointPosition in annulusMarkupControlPointsArray:
        annulusMarkupNode.AddControlPoint(pointPosition)
        slicer.app.processEvents()
        time.sleep(0.5)

    # -------------------------------------------
    self.delayDisplay("Adjust contour")

    self.delayDisplay("Enable smoothing preview")
    valveAnnulusAnalysisGui.ui.contourAdjustmentCollapsibleButton.collapsed = False
    valveAnnulusAnalysisGui.ui.smoothContourPreviewCheckbox.checked = True

    self.delayDisplay("Enable smoothing preview")
    valveAnnulusAnalysisGui.ui.resampleContourButton.click()

    valveAnnulusAnalysisGui.ui.displayCollapsibleButton.collapsed = False
