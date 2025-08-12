import logging
import vtk, qt, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import numpy as np
import math
from PIL import ImageColor


#
# ValveMoldCreator
#

DEFAULT_LEAFLET_NAME_IDENTIFIER = 'leaflet'      # TODO: need to think more about this. Terminology might be an option


DEFAULT_SEG_NAME_TEMPLATE_ORIGINAL = 'Template_mold_orig'
DEFAULT_SEG_NAME_TEMPLATE_RING = 'Template_mold_ring'
DEFAULT_SEG_NAME_MOLD_COAPTATION = 'Coaptation'
DEFAULT_SEG_NAME_TOP_MOLD = 'Top_mold'
DEFAULT_SEG_NAME_MOLD = 'Mold_base'
DEFAULT_SEG_NAME_FINAL_MOLD = 'Final_Mold'
DEFAULT_SEG_NAME_PROJECTED_ANNULUS = 'Annulus_Projection'
DEFAULT_SEG_NAME_VALVE_SEGMENTATION = 'Leaflet Segmentation'
DEFAULT_MODEL_NAME_HPA = "Hinge Point Apparatus"

DEFAULT_COLOR_MOLD_BASE = "#4a9e00"
DEFAULT_COLOR_COAPTATION = "#0fb5f7"
DEFAULT_COLOR_ANNULUS_PROJECTION = "#FB6542"
DEFAULT_COLOR_HPA = "#ffea00"
DEFAULT_COLOR_MOLD_ASSEMBLY = "#909090"
DEFAULT_MOLD_ASSEMBLY_REPRESENTATION = slicer.vtkMRMLModelDisplayNode.WireframeRepresentation
DEFAULT_MOLD_ASSEMBLY_OPACITY = 0.5

HPA_FIXED_LANDMARKS_NODE_NAME = "fixed_hpa_pts"
MOLD_ASSEMBLY_TO_HPA_TRANSFORM_NODE_NAME = "mold_assembly_to_hpa_transform"
HPA_ASSEMBLY_LID_LANDMARKS_NODE_NAME = "moving_lid_pts"

MOLD_ASSEMBLY_LID_NAME = "Mold_Lid"
MOLD_ASSEMBLY_TOP_NAME = "Mold_Top"
MOLD_ASSEMBLY_BASE_NAME = "Mold_Base"
MOLD_ASSEMBLY_LV_FLANGE_NAME = "LV_Flange"
MOLD_ASSEMBLY_PM_PAP_POST_NAME = "PM_Papillary_Post"
MOLD_ASSEMBLY_AL_PAP_POST_NAME = "AL_Papillary_Post"
MOLD_ASSEMBLY_ATRIAL_FLANGE_NAME = "Atrial_Flange"
MOLD_ASSEMBLY_NEGATIVE_NAME = "Negative"

MOLD_ASSEMBLY_LID_REGISTRATION_VERTICES = [4209, 4878, 3835, 4722]

MOLD_ASSEMBLY_PARTS = [
  MOLD_ASSEMBLY_LID_NAME,
  MOLD_ASSEMBLY_TOP_NAME,
  MOLD_ASSEMBLY_BASE_NAME,
  MOLD_ASSEMBLY_LV_FLANGE_NAME,
  MOLD_ASSEMBLY_PM_PAP_POST_NAME,
  MOLD_ASSEMBLY_AL_PAP_POST_NAME,
  MOLD_ASSEMBLY_ATRIAL_FLANGE_NAME,
  MOLD_ASSEMBLY_NEGATIVE_NAME
]

PARAM_MOLD_COAPTATION_WIDTH_MM = 'Mold_Coaptation_Width_Mm'
PARAM_MOLD_COAPTATION_LEAFLET_DISTANCE_MM = 'Mold_Coaptation_Leaflet_Maximum_Distance_Mm'
PARAM_HPA_USE_ANNULUS_PROJECTION = 'Use_Annulus_Projection'
PARAM_BASE_CLIPPING_DEPTH = 'Base_Clipping_Depth_Mm'
PARAM_BASE_ADD_MARGIN_MM = 'Base_Added_Margin_Mm'
PARAM_ANNULUS_MARGIN = 'Annulus_Projection_Margin_Mm'
PARAM_ANNULUS_OFFSET = 'Annulus_Projection_Offset_Mm'
PARAM_ANNULUS_PROJECTION_MODE = 'Annulus_Projection_Mode'
PARAM_HPA_DIST_TOP_ANNULUS_MIN = 'HPA_Top_Distance_To_Annulus_Minimum'
PARAM_HPA_NUM_LANDMARKS = 'HPA_Number_Of_Landmark_Points'
PARAM_LAX_DIAMETER_OUTSIDE = 'HPA_LAX_Outer_Diameter'
PARAM_LAX_DIAMETER_INSIDE = 'HPA_LAX_Inner_Diameter'
PARAM_SAX_DIAMETER_OUTSIDE = 'HPA_SAX_Outer_Diameter'
PARAM_SAX_DIAMETER_INSIDE = 'HPA_SAX_Inner_Diameter'
PARAM_OUTER_DISK_RADIUS_FACTOR = "HPA_Outer_Disk_Radius_Factor"
PARAM_OUTER_SKIRT_TRANSLATION = "HPA_Outer_Skirt_Translation"
PARAM_HPA_HEIGHT = "HPA_Height"
PARAM_HPA_Z_TRANSLATION = "HPA_Z_Translation"
PARAM_HPA_SKIRT_MIN_THICKNESS = "HPA_Minimum_Thickness"


PARAM_DEFAULTS = {
  PARAM_MOLD_COAPTATION_WIDTH_MM: 1.2,
  PARAM_MOLD_COAPTATION_LEAFLET_DISTANCE_MM: 1.0,
  PARAM_BASE_ADD_MARGIN_MM: 0.0,
  PARAM_BASE_CLIPPING_DEPTH: -18.0,
  PARAM_HPA_DIST_TOP_ANNULUS_MIN: 22.5,
  PARAM_LAX_DIAMETER_OUTSIDE: 78.923,
  PARAM_LAX_DIAMETER_INSIDE: 68.847,
  PARAM_SAX_DIAMETER_OUTSIDE: 58.992,
  PARAM_SAX_DIAMETER_INSIDE: 48.613,
  PARAM_HPA_NUM_LANDMARKS: 180,
  PARAM_ANNULUS_MARGIN: 0,
  PARAM_ANNULUS_OFFSET: -1.0,
  PARAM_ANNULUS_PROJECTION_MODE: "Vertical Line",
  PARAM_HPA_HEIGHT: -1, # undefined
  PARAM_HPA_SKIRT_MIN_THICKNESS: 0.4
}


class ValveMoldCreator(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Valve Mold Creator"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveQuantification"]
    self.parent.contributors = ["Christian Herz (CHOP)"]
    self.parent.helpText = """Mold generation for SlicerHeart based valve segmentation"""
    self.parent.acknowledgementText = """
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
"""


#
# ValveMoldCreatorWidget
#


class ValveMoldCreatorWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.__init__(self, parent)

    try:
      global HeartValveLib
      import HeartValveLib
      import HeartValveLib.SmoothCurve
    except ImportError as exc:
      logging.error("{}: {}".format(self.moduleName, exc.message))

    VTKObservationMixin.__init__(self)  # needed for parameter node observation
    self._parameterNode = None
    self._updatingGUIFromParameterNode = False

    self.logic = ValveMoldCreatorLogic()

    self._valveModel = None

  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    uiWidget = slicer.util.loadUI(self.resourcePath('UI/ValveMoldCreator.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    uiWidget.setMRMLScene(slicer.mrmlScene)

    self.ui.heartValveSelector.setNodeTypeLabel("HeartValve", "vtkMRMLScriptedModuleNode")
    self.ui.heartValveSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", "HeartValve")
    self.ui.heartValveSelector.setMRMLScene(slicer.mrmlScene)
    self.ui.heartValveSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onHeartValveSelect)

    # Get/create parameter node
    valveSegmentationSingletonTag = f"{self.moduleName}SegmentEditor"
    segmentEditorNode = slicer.mrmlScene.GetSingletonNode(valveSegmentationSingletonTag, "vtkMRMLSegmentEditorNode")
    if segmentEditorNode is None:
      segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
      segmentEditorNode.SetName(valveSegmentationSingletonTag)
      segmentEditorNode.SetHideFromEditors(True)
      segmentEditorNode.SetSingletonTag(valveSegmentationSingletonTag)
      segmentEditorNode = slicer.mrmlScene.AddNode(segmentEditorNode)

    self.configureDefaultTerminology()

    self.ui.segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
    self.ui.segmentEditorWidget.setMRMLScene(slicer.mrmlScene)

    self.ui.generateMoldButton.clicked.connect(self.onGenerateMoldButton)
    self.ui.generateCoaptationButton.clicked.connect(self.onGenerateCoaptationButton)
    self.ui.generateHpaButton.clicked.connect(self.onGenerateHpaButton)
    self.ui.addMoldAssemblyButton.clicked.connect(self.onAddMoldAssemblyButton)
    self.ui.projectAnnulusButton.clicked.connect(self.onProjectAnnulusButton)
    self.ui.toggleAnnulusModelButton.clicked.connect(self.onToggleAnnulusModelContourVisibility)
    self.ui.toggleHPAModelButton.clicked.connect(self.onToggleHPAModelVisibility)
    self.ui.toggleAssemblyModelsButton.clicked.connect(self.onToggleMoldAssemblyModelVisibility)
    self.ui.toggleAnnulusLandmarksButton.clicked.connect(self.onToggleAnnulusLandmarksVisibility)
    self.ui.subtractAnnulusButton.clicked.connect(self.onSubtractAnnulusButton)
    self.ui.useAnnulusProjectionCheckbox.toggled.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.baseDepthSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.baseMarginSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.coaptationWidthSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.coaptationDistanceThresholdSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.annulusMarginSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.annulusOffsetSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.annulusProjectionModeCombobox.currentTextChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.hpaLaxInnerDiameterSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.hpaLaxOuterDiameterSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.hpaSaxInnerDiameterSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.hpaSaxOuterDiameterSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.hpaMinimumThicknessSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.hpaHeightSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.hpaTopDistanceToMinAnnulusSlider.valueChanged.connect(lambda v: self.updateParameterNodeFromGUI())
    self.ui.makeHPACircleDimensionsButton.clicked.connect(self.onMakeHPADimensionsCircular)
    self.ui.makeHPACircleDimensionsButton.toggled.connect(self.onMakeHPADimensionsCircularChecked)
    self.ui.resetHPADimensionsButton.clicked.connect(self.onResetHPADimensions)
    self.ui.hpaHeightApplyButton.clicked.connect(self.onApplyHPAHeightButton)
    self.ui.exportMoldButton.clicked.connect(self.onExportMoldButton)

    self.addDblClickDefaultValueObserver()

    self.onHeartValveSelect(self.ui.heartValveSelector.currentNode())

    # Make sure parameter node is initialized (needed for module reload)
    self.initializeParameterNode()

    slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndCloseEvent, self.onCloseScene)

  def addDblClickDefaultValueObserver(self):
    ui = self.ui
    resettableWidgets = [
      (ui.hpaTopDistanceLabel, ui.hpaTopDistanceToMinAnnulusSlider, PARAM_DEFAULTS[PARAM_HPA_DIST_TOP_ANNULUS_MIN]),
      (ui.hpaHeightLabel, ui.hpaHeightSlider, PARAM_DEFAULTS[PARAM_HPA_HEIGHT]),
      (ui.baseDepthLabel, ui.baseDepthSlider, PARAM_DEFAULTS[PARAM_BASE_CLIPPING_DEPTH]),
      (ui.baseMarginLabel, ui.baseMarginSlider, PARAM_DEFAULTS[PARAM_BASE_ADD_MARGIN_MM]),
      (ui.coaptationWidthLabel, ui.coaptationWidthSlider, PARAM_DEFAULTS[PARAM_MOLD_COAPTATION_WIDTH_MM]),
      (ui.coaptationDistanceThresholdLabel, ui.coaptationDistanceThresholdSlider,
       PARAM_DEFAULTS[PARAM_MOLD_COAPTATION_LEAFLET_DISTANCE_MM]),
      (ui.annulusOffsetLabel, ui.annulusOffsetSlider, PARAM_DEFAULTS[PARAM_ANNULUS_OFFSET]),
      (ui.annulusMarginLabel, ui.annulusMarginSlider, PARAM_DEFAULTS[PARAM_ANNULUS_MARGIN]),
      (ui.hpaLaxOuterDiameterLabel, ui.hpaLaxOuterDiameterSlider, PARAM_DEFAULTS[PARAM_LAX_DIAMETER_OUTSIDE]),
      (ui.hpaLaxInnerDiameterLabel, ui.hpaLaxInnerDiameterSlider, PARAM_DEFAULTS[PARAM_LAX_DIAMETER_INSIDE]),
      (ui.hpaSaxOuterDiameterLabel, ui.hpaSaxOuterDiameterSlider, PARAM_DEFAULTS[PARAM_SAX_DIAMETER_OUTSIDE]),
      (ui.hpaSaxInnerDiameterLabel, ui.hpaSaxInnerDiameterSlider, PARAM_DEFAULTS[PARAM_SAX_DIAMETER_INSIDE]),
    ]
    self.dblClickEventFilter = DoubleClickObserver()
    for label, sliderWidget, defaultValue in resettableWidgets:
      self.dblClickEventFilter.observeWidget(label, sliderWidget, defaultValue)

  def onCloseScene(self, caller, event):
    self.initializeParameterNode()

  def configureDefaultTerminology(self):
    tlogic = slicer.modules.terminologies.logic()
    terminologyName = tlogic.LoadTerminologyFromFile(HeartValveLib.getTerminologyFile())
    terminologyEntry = slicer.vtkSlicerTerminologyEntry()
    terminologyEntry.SetTerminologyContextName(terminologyName)

    # NB: GetNthCategoryInTerminology was introduced after Slicer 4.11 06.04 and will cause errors in older versions
    if not hasattr(tlogic, "GetNthCategoryInTerminology"):
      return
    tlogic.GetNthCategoryInTerminology(terminologyName, 0, terminologyEntry.GetCategoryObject())
    tlogic.GetNthTypeInTerminologyCategory(terminologyName, terminologyEntry.GetCategoryObject(), 0,
                                           terminologyEntry.GetTypeObject())
    defaultTerminologyEntry = tlogic.SerializeTerminologyEntry(terminologyEntry)
    self.ui.segmentEditorWidget.defaultTerminologyEntrySettingsKey = "SlicerHeart/DefaultTerminologyEntry"
    self.ui.segmentEditorWidget.defaultTerminologyEntry = defaultTerminologyEntry

  def onHeartValveSelect(self, node):
    logging.debug("Selected heart valve node: {0}".format(node.GetName() if node else "None"))
    self.setHeartValveNode(node)

  def setHeartValveNode(self, heartValveNode):
    if self._valveModel and self._valveModel.getHeartValveNode() == heartValveNode:
      return

    self._valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)

    # Update GUI button enabled/disabled state
    self.setGuiEnabled(heartValveNode is not None)
    segmentationNode = self._valveModel.getLeafletSegmentationNode() if self._valveModel else None
    self.ui.segmentEditorWidget.setSegmentationNode(segmentationNode)
    masterVolumeNode = self._valveModel.getValveVolumeNode() if self._valveModel else None
    self.ui.segmentEditorWidget.setSourceVolumeNode(masterVolumeNode)
    self.ui.segmentEditorWidget.mrmlSegmentEditorNode().Modified()

  def setGuiEnabled(self, enable):
    self.ui.moldGroupBox.setEnabled(enable)
    self.ui.coaptationGroupBox.setEnabled(enable)
    self.ui.annulusGroupBox.setEnabled(enable)
    self.ui.hpaGroupBox.setEnabled(enable)
    self.ui.exportMoldButton.setEnabled(enable)

  def onGenerateMoldButton(self):
    with ProgressDialog() as progressDialog:
      from HeartValveLib.helpers import getValvePhaseShortName
      if getValvePhaseShortName(self._valveModel) == "MS":
        logic = self.logic
      else:
        logic = DiastolicValveMoldCreatorLogic()

      logic.setProgressCallback(progressDialog.updateProgress)
      try:
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        logic.generateMold(valveModel=self._valveModel, parameterNode=self._parameterNode)
      except SegmentationSpacingError as exc:
        raise exc
      finally:
        qt.QApplication.restoreOverrideCursor()
        logic.setProgressCallback(None)

  def onGenerateCoaptationButton(self):
    with ProgressDialog() as progressDialog:
      try:
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        self.logic.setProgressCallback(progressDialog.updateProgress)
        self.logic.generateCoaptation(valveModel=self._valveModel, parameterNode=self._parameterNode)
      except SegmentationSpacingError as exc:
        # segNode = self._valveModel.getLeafletSegmentationNode()
        # geometryWidget = slicer.qMRMLSegmentationGeometryWidget()
        # geometryWidget.setSegmentationNode(segNode)
        # geometryWidget.show()
        # geometryWidget.setIsotropicSpacing(True)
        # geometryWidget.setEditEnabled(True)
        # geometryWidget.setReferenceImageGeometryForSegmentationNode(self._valveModel.getValveVolumeNode())
        raise exc
      finally:
        qt.QApplication.restoreOverrideCursor()
        self.logic.setProgressCallback(None)

  def onToggleAnnulusModelContourVisibility(self):
    if not self._valveModel:
      return

    model = self._valveModel.getAnnulusContourModelNode()
    visibility = model.GetDisplayVisibility()
    model.SetDisplayVisibility(not visibility)

  def onToggleHPAModelVisibility(self):
    if not self._valveModel:
      return

    model = self.logic.getValveModelChildItemByName(self._valveModel, DEFAULT_MODEL_NAME_HPA)
    if model:
      visibility = model.GetDisplayVisibility()
      model.SetDisplayVisibility(not visibility)

  def onToggleAnnulusLandmarksVisibility(self):
    if not self._valveModel:
      return

    labelNode = self._valveModel.getAnnulusLabelsMarkupNode()
    visibility = labelNode.GetDisplayVisibility()
    labelNode.SetDisplayVisibility(not visibility)

  def onProjectAnnulusButton(self):
    self.logic.projectAnnulus(self._valveModel, self._parameterNode)

  def onSubtractAnnulusButton(self):
    self.logic.subtractAnnulus(self._valveModel)

  def onGenerateHpaButton(self):
    with ProgressDialog() as progressDialog:
      try:
        self.logic.setProgressCallback(progressDialog.updateProgress)
        self.logic.generateHPA(self._valveModel, parameterNode=self._parameterNode)
      finally:
        self.logic.setProgressCallback(None)

  def onAddMoldAssemblyButton(self):
    self.logic.addMoldAssembly(self._valveModel)

  def onToggleMoldAssemblyModelVisibility(self):
    if not self._valveModel:
      return

    for model in self.logic.getMoldAssemblyModels(self._valveModel):
      if model is None:
        continue

      visibility = model.GetDisplayVisibility()
      model.SetDisplayVisibility(not visibility)

  def onApplyHPAHeightButton(self):
    with ProgressDialog() as progressDialog:
      try:
        self.logic.setProgressCallback(progressDialog.updateProgress)
        self.logic.generateHPA(self._valveModel,
                               parameterNode=self._parameterNode,
                               valveHPAHeight=self.ui.hpaHeightSlider.value)
      finally:
        self.logic.setProgressCallback(None)

  def onExportMoldButton(self):
    with ProgressDialog() as progressDialog:
      try:
        self.logic.setProgressCallback(progressDialog.updateProgress)
        self.logic.exportMoldToModel(self._valveModel)
      finally:
        self.logic.setProgressCallback(None)

  def onMakeHPADimensionsCircular(self):
    self._parameterNode.SetParameter(PARAM_SAX_DIAMETER_INSIDE, str(self.ui.hpaLaxInnerDiameterSlider.value))
    self._parameterNode.SetParameter(PARAM_SAX_DIAMETER_OUTSIDE, str(self.ui.hpaLaxOuterDiameterSlider.value))

  def onMakeHPADimensionsCircularChecked(self, toggled):
    self.ui.hpaSaxInnerDiameterSlider.enabled = not toggled
    self.ui.hpaSaxOuterDiameterSlider.enabled = not toggled
    self.ui.resetHPADimensionsButton.enabled = not toggled

    if toggled:
      self._syncHPAInnerDiameterSliders = lambda v: self.ui.hpaSaxInnerDiameterSlider.setValue(v)
      self._syncHPAOuterDiameterSliders = lambda v: self.ui.hpaSaxOuterDiameterSlider.setValue(v)
      self.ui.hpaLaxInnerDiameterSlider.valueChanged.connect(self._syncHPAInnerDiameterSliders)
      self.ui.hpaLaxOuterDiameterSlider.valueChanged.connect(self._syncHPAOuterDiameterSliders)
    else:
      if self._syncHPAInnerDiameterSliders:
        self.ui.hpaLaxInnerDiameterSlider.valueChanged.disconnect(self._syncHPAInnerDiameterSliders)
      if self._syncHPAOuterDiameterSliders:
        self.ui.hpaLaxOuterDiameterSlider.valueChanged.disconnect(self._syncHPAOuterDiameterSliders)

  def onResetHPADimensions(self):
    for param in [PARAM_LAX_DIAMETER_INSIDE, PARAM_LAX_DIAMETER_OUTSIDE,
                  PARAM_SAX_DIAMETER_INSIDE, PARAM_SAX_DIAMETER_OUTSIDE]:
      self._parameterNode.SetParameter(param, str(PARAM_DEFAULTS[param]))

  def initializeParameterNode(self):
    if self._parameterNode is not None:
      self._parameterNode = \
        self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self.setParameterNode(self.logic.getParameterNode())

  def setParameterNode(self, inputParameterNode):
    self._parameterNode = inputParameterNode

    if self._parameterNode is not None:
      self.logic.setDefaultParameters(inputParameterNode)
      self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self, caller=None, event=None):
    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
    self._updatingGUIFromParameterNode = True

    # Update node selectors and sliders
    self.ui.useAnnulusProjectionCheckbox.checked = \
      slicer.util.toBool(self._parameterNode.GetParameter(PARAM_HPA_USE_ANNULUS_PROJECTION))
    self.ui.coaptationWidthSlider.value = float(self._parameterNode.GetParameter(PARAM_MOLD_COAPTATION_WIDTH_MM))
    self.ui.coaptationDistanceThresholdSlider.value = \
      float(self._parameterNode.GetParameter(PARAM_MOLD_COAPTATION_LEAFLET_DISTANCE_MM))
    self.ui.baseDepthSlider.value = float(self._parameterNode.GetParameter(PARAM_BASE_CLIPPING_DEPTH))
    self.ui.baseMarginSlider.value = float(self._parameterNode.GetParameter(PARAM_BASE_ADD_MARGIN_MM))
    self.ui.annulusMarginSlider.value = float(self._parameterNode.GetParameter(PARAM_ANNULUS_MARGIN))
    self.ui.annulusOffsetSlider.value = float(self._parameterNode.GetParameter(PARAM_ANNULUS_OFFSET))
    self.ui.annulusProjectionModeCombobox.setCurrentText(self._parameterNode.GetParameter(PARAM_ANNULUS_PROJECTION_MODE))
    self.ui.hpaLaxInnerDiameterSlider.value = float(self._parameterNode.GetParameter(PARAM_LAX_DIAMETER_INSIDE))
    self.ui.hpaLaxOuterDiameterSlider.value = float(self._parameterNode.GetParameter(PARAM_LAX_DIAMETER_OUTSIDE))
    self.ui.hpaSaxInnerDiameterSlider.value = float(self._parameterNode.GetParameter(PARAM_SAX_DIAMETER_INSIDE))
    self.ui.hpaSaxOuterDiameterSlider.value = float(self._parameterNode.GetParameter(PARAM_SAX_DIAMETER_OUTSIDE))
    self.ui.hpaHeightSlider.value = float(self._parameterNode.GetParameter(PARAM_HPA_HEIGHT))
    self.ui.hpaTopDistanceToMinAnnulusSlider.value = float(self._parameterNode.GetParameter(PARAM_HPA_DIST_TOP_ANNULUS_MIN))
    self.ui.hpaMinimumThicknessSlider.value = float(self._parameterNode.GetParameter(PARAM_HPA_SKIRT_MIN_THICKNESS))

    # All the GUI updates are done
    self._updatingGUIFromParameterNode = False

  def updateParameterNodeFromGUI(self, caller=None, event=None):
    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

    self._parameterNode.SetParameter(PARAM_HPA_USE_ANNULUS_PROJECTION, str(self.ui.useAnnulusProjectionCheckbox.checked))
    self._parameterNode.SetParameter(PARAM_MOLD_COAPTATION_WIDTH_MM, str(self.ui.coaptationWidthSlider.value))
    self._parameterNode.SetParameter(PARAM_MOLD_COAPTATION_LEAFLET_DISTANCE_MM,
                                     str(self.ui.coaptationDistanceThresholdSlider.value))
    self._parameterNode.SetParameter(PARAM_BASE_CLIPPING_DEPTH, str(self.ui.baseDepthSlider.value))
    self._parameterNode.SetParameter(PARAM_BASE_ADD_MARGIN_MM, str(self.ui.baseMarginSlider.value))
    self._parameterNode.SetParameter(PARAM_ANNULUS_MARGIN, str(self.ui.annulusMarginSlider.value))
    self._parameterNode.SetParameter(PARAM_ANNULUS_OFFSET, str(self.ui.annulusOffsetSlider.value))
    self._parameterNode.SetParameter(PARAM_ANNULUS_PROJECTION_MODE, self.ui.annulusProjectionModeCombobox.currentText)
    self._parameterNode.SetParameter(PARAM_LAX_DIAMETER_INSIDE, str(self.ui.hpaLaxInnerDiameterSlider.value))
    self._parameterNode.SetParameter(PARAM_LAX_DIAMETER_OUTSIDE, str(self.ui.hpaLaxOuterDiameterSlider.value))
    self._parameterNode.SetParameter(PARAM_SAX_DIAMETER_INSIDE, str(self.ui.hpaSaxInnerDiameterSlider.value))
    self._parameterNode.SetParameter(PARAM_SAX_DIAMETER_OUTSIDE, str(self.ui.hpaSaxOuterDiameterSlider.value))
    self._parameterNode.SetParameter(PARAM_HPA_SKIRT_MIN_THICKNESS, str(self.ui.hpaMinimumThicknessSlider.value))
    self._parameterNode.SetParameter(PARAM_HPA_HEIGHT, str(self.ui.hpaHeightSlider.value))
    self._parameterNode.SetParameter(PARAM_HPA_DIST_TOP_ANNULUS_MIN, str(self.ui.hpaTopDistanceToMinAnnulusSlider.value))
    self._parameterNode.EndModify(wasModified)


#
# ValveMoldCreatorLogic
#


class ValveMoldCreatorLogic(ScriptedLoadableModuleLogic):
  """ This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  PROGRESS_CALLBACK = None

  @classmethod
  def setProgressCallback(cls, callback):
    assert callback is None or callable(callback)
    cls.PROGRESS_CALLBACK = callback

  @classmethod
  def updateProgress(cls, text, value=None, maxValue=None):
    if cls.PROGRESS_CALLBACK:
      cls.PROGRESS_CALLBACK(text, value, maxValue)

  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)

  def resourcePath(self, filename):
    import os
    scriptedModulesPath = os.path.dirname(slicer.util.modulePath(self.moduleName))
    return os.path.join(scriptedModulesPath, 'Resources', filename)

  def setDefaultParameters(self, parameterNode):
    for paramName, paramDefaultValue in PARAM_DEFAULTS.items():
      self._setDefaultParameter(parameterNode, paramName, str(paramDefaultValue))

  @staticmethod
  def _setDefaultParameter(parameterNode, paramName, defaultParamValue):
    if not parameterNode.GetParameter(paramName):
      parameterNode.SetParameter(paramName, defaultParamValue)

  @classmethod
  def createMergedLeafletsSegment(cls, segNode, masterVolume, segmentName):
    segments = getAllLeafletSegments(segNode, DEFAULT_LEAFLET_NAME_IDENTIFIER)
    segmentation = segNode.GetSegmentation()

    pushPolydataToSegmentation(segNode, vtk.vtkPolyData(), segmentName)

    with SegmentEditorWidget() as segmentEditorWidget:
      segmentEditorWidget.setSegmentationNode(segNode)
      segmentEditorWidget.setSourceVolumeNode(masterVolume)
      segmentEditorWidget.setCurrentSegmentID(segmentName)

      from SegmentEditorEffects.SegmentEditorLogicalEffect import LOGICAL_UNION

      segmentEditorWidget.setActiveEffectByName('Logical operators')
      effect = segmentEditorWidget.activeEffect()
      effect.setParameter("Operation", LOGICAL_UNION)
      for segment in segments:
        effect.setParameter("ModifierSegmentID", segmentation.GetSegmentIdBySegment(segment))
        effect.self().onApply()

    segmentClosing(segNode, masterVolume, segmentName)

  @classmethod
  def extrude(cls, surface, planeNormal, extrudeFactor):

    normAuto = vtk.vtkPolyDataNormals()
    normAuto.ConsistencyOn()
    normAuto.SetInputData(surface)
    normAuto.Update()

    extrusion = vtk.vtkLinearExtrusionFilter()
    extrusion.SetExtrusionTypeToVectorExtrusion()
    extrusion.SetVector(np.array(planeNormal))
    extrusion.SetScaleFactor(extrudeFactor)
    extrusion.SetInputConnection(normAuto.GetOutputPort())
    extrusion.CappingOn()
    extrusion.Update()

    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(extrusion.GetOutputPort())
    clean.Update()

    normAuto = vtk.vtkPolyDataNormals()
    normAuto.ConsistencyOn()
    normAuto.AutoOrientNormalsOn()
    normAuto.SetInputConnection(extrusion.GetOutputPort())
    normAuto.Update()

    return normAuto.GetOutput()

  @classmethod
  def fitTpsDiskToClosedCurve(cls, boundaryCurveNode, radialResolution=30):
    """Requires boundaryCurveNode curve to be sampled uniformly"""

    # points on the warped boundary curve
    targetLandmarkPoints = boundaryCurveNode.GetCurvePoints()
    numberOfCurveLandmarkPoints = targetLandmarkPoints.GetNumberOfPoints()

    # points on the unit disk
    sourceCurvePoints = vtk.vtkPoints()
    sourceCurvePoints.SetNumberOfPoints(numberOfCurveLandmarkPoints)
    import math
    angleIncrement = 2.0 * math.pi / float(numberOfCurveLandmarkPoints)
    for pointIndex in range(numberOfCurveLandmarkPoints):
        angle = float(pointIndex) * angleIncrement
        sourceCurvePoints.SetPoint(pointIndex, math.cos(angle), math.sin(angle), 0)

    return cls.warpDisk(sourceCurvePoints, targetLandmarkPoints, 0.0, 1.0, radialResolution)

  @classmethod
  def generateMold(cls, valveModel, parameterNode):
    """ Generate the complete surface mold from the segmentation. The mold bottom is clipped to the specified depth and
    returned into the valve segmentation node.
    :param valveModel: SlicerHeart valve model containing annulus definition
    :param parameterNode: additional parameters for generating surface mold
    :return: None
    """

    segNode = valveModel.getLeafletSegmentationNode()
    segmentation = segNode.GetSegmentation()
    spacing = segNode.GetBinaryLabelmapInternalRepresentation(segmentation.GetNthSegmentID(0)).GetSpacing()
    logging.info(f"Voxel spacing of the segmentation: {spacing}")

    # if any(val > 0.31 for val in list(spacing)):
    #   raise SegmentationSpacingError(f"Voxel spacing of segmentation > 0.3mm : {spacing}")

    cls.updateProgress("Generating cylinders", 1, 4)
    cls.createMoldCylinderTemplate(valveModel, parameterNode)

    cls.updateProgress("Generating top mold", 2)
    cls.createTopMold(valveModel, parameterNode)

    cls.updateProgress("Subtracting", 3)
    valveVolume = valveModel.getValveVolumeNode()
    segNode = valveModel.getLeafletSegmentationNode()
    subtractSegments(segNode, valveVolume, DEFAULT_SEG_NAME_MOLD, DEFAULT_SEG_NAME_TOP_MOLD)
    subtractSegments(segNode, valveVolume, DEFAULT_SEG_NAME_MOLD, DEFAULT_SEG_NAME_TEMPLATE_RING)
    gaussianSmoothSegment(segNode, valveVolume, DEFAULT_SEG_NAME_MOLD, standardDeviationMm=0.3)

    # configure segments display
    segNode.GetDisplayNode().SetSegmentVisibility(DEFAULT_SEG_NAME_TEMPLATE_ORIGINAL, False)
    segNode.GetDisplayNode().SetSegmentVisibility(DEFAULT_SEG_NAME_TOP_MOLD, False)
    segNode.GetDisplayNode().SetSegmentVisibility(DEFAULT_SEG_NAME_TEMPLATE_RING, False)
    segNode.GetDisplayNode().SetSegmentVisibility(DEFAULT_SEG_NAME_PROJECTED_ANNULUS, True)
    segNode.GetDisplayNode().SetSegmentVisibility(DEFAULT_SEG_NAME_MOLD, True)
    segNode.GetSegmentation().GetSegment(DEFAULT_SEG_NAME_MOLD).SetColor(hex2rgb(DEFAULT_COLOR_MOLD_BASE))
    cls.updateProgress("Finishing up", 4)

  @classmethod
  def generateCoaptation(cls, valveModel, parameterNode):
    cls.updateProgress("Creating coaptation area", 1, 4)

    segNode = valveModel.getLeafletSegmentationNode()
    segmentation = segNode.GetSegmentation()

    coaptationSurface = cls.createCoaptationArea(valveModel, parameterNode)

    cls.updateProgress("Creating temporary segmentation", 2)
    tempSegNode = createSegmentationNode()
    pushPolydataToSegmentation(tempSegNode, coaptationSurface, DEFAULT_SEG_NAME_MOLD_COAPTATION)
    removeAllSegmentsMatchingName(segNode, DEFAULT_SEG_NAME_MOLD_COAPTATION)
    segmentation.CopySegmentFromSegmentation(tempSegNode.GetSegmentation(), DEFAULT_SEG_NAME_MOLD_COAPTATION)
    slicer.mrmlScene.RemoveNode(tempSegNode)

    cls.updateProgress("Finishing up", 3)

    # smoothSegment(tempSegNode, valveVolume, DEFAULT_SEG_NAME_MOLD, kernelSizeMm=spacing * 2)

    segNode = valveModel.getLeafletSegmentationNode()
    segNode.GetDisplayNode().SetSegmentVisibility(DEFAULT_SEG_NAME_MOLD_COAPTATION, True)
    segNode.GetSegmentation().GetSegment(DEFAULT_SEG_NAME_MOLD_COAPTATION).SetColor(hex2rgb(DEFAULT_COLOR_COAPTATION))
    cls.updateProgress("Done", 4)

  @staticmethod
  def createCoaptationArea(valveModel, parameterNode):

    def getCoaptationAndSurroundingArea(main_shape, others, minDist=-1.0):
      assert minDist < 1

      # combine other shapes to get overall distance from them
      otherLeaflets = vtk.vtkAppendPolyData()
      for other in others:
        otherLeaflets.AddInputData(other)
      otherLeaflets.Update()

      # distance to other leaflets
      dist = vtk.vtkDistancePolyDataFilter()
      dist.SetInputData(0, main_shape)
      dist.SetInputData(1, otherLeaflets.GetOutput())
      dist.NegateDistanceOn()
      dist.Update()

      # Compute point normals
      normals = vtk.vtkPolyDataNormals()
      normals.SetInputData(main_shape)
      normals.AutoOrientNormalsOn()
      normals.ComputePointNormalsOn()
      normals.ComputeCellNormalsOff()
      normals.Update()

      main_shape.GetPointData().AddArray(dist.GetOutput().GetPointData().GetArray("Distance"))

      threshold = vtk.vtkThreshold()
      threshold.SetInputData(main_shape)
      threshold.SetLowerThreshold(minDist)
      threshold.SetUpperThreshold(1)
      threshold.SetThresholdFunction(vtk.vtkThreshold.THRESHOLD_BETWEEN)
      threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "Distance")
      threshold.Update()

      geometryFilter = vtk.vtkGeometryFilter()
      geometryFilter.SetInputData(threshold.GetOutput())
      geometryFilter.Update()

      return geometryFilter.GetOutput()

    allLeafletsPoly = []
    for leafletModel in valveModel.leafletModels:
      segmentId = leafletModel.segmentId
      leafletSurfaceModelNode = valveModel.getLeafletNodeReference("LeafletSurfaceModel", segmentId)
      assert leafletSurfaceModelNode, f"No leaflet surface model found for leaflet {segmentId}"
      allLeafletsPoly.append(leafletSurfaceModelNode.GetPolyData())

    # for each leaflet warp with other leaflets
    _, planeNormal = valveModel.getAnnulusContourPlane()
    append = vtk.vtkAppendPolyData()

    distanceThresh = float(parameterNode.GetParameter(PARAM_MOLD_COAPTATION_LEAFLET_DISTANCE_MM))

    for leafletPoly in allLeafletsPoly:
      contactArea = \
        getCoaptationAndSurroundingArea(leafletPoly,
                                        others=list(filter(lambda x: x is not leafletPoly, allLeafletsPoly)),
                                        minDist=-distanceThresh)
      append.AddInputData(contactArea)
    append.Update()

    thickness = float(parameterNode.GetParameter(PARAM_MOLD_COAPTATION_WIDTH_MM))
    thickened = increasePolydataThickness(append.GetOutput(), thickness)

    smooth = vtk.vtkSmoothPolyDataFilter()
    smooth.SetInputData(thickened)
    smooth.FeatureEdgeSmoothingOff()
    smooth.BoundarySmoothingOn()
    smooth.SetRelaxationFactor(0.10)
    smooth.SetNumberOfIterations(100)
    smooth.Update()

    return smooth.GetOutput()

  @classmethod
  def createTopMold(cls, valveModel, parameterNode):
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    depth = float(parameterNode.GetParameter(PARAM_BASE_CLIPPING_DEPTH))
    segNode = valveModel.getLeafletSegmentationNode()
    segmentation = segNode.GetSegmentation()

    annulusPoints = slicer.util.arrayFromMarkupsControlPoints(valveModel.annulusContourCurve.controlPointsMarkupNode).T

    from ValveQuantificationLib.MeasurementPreset import MeasurementPreset

    annulusAreaPolyData = MeasurementPreset.createSoapBubblePolyDataFromCircumferencePoints(annulusPoints, 1.2)
    annulusAreaPolyDataBigger = MeasurementPreset.createSoapBubblePolyDataFromCircumferencePoints(annulusPoints, 5.0)

    leafletSegmentIDs = [segmentation.GetSegmentIdBySegment(segment) for segment in
      getAllLeafletSegments(segNode, DEFAULT_LEAFLET_NAME_IDENTIFIER)]

    leafletSurfaces = [segNode.GetClosedSurfaceInternalRepresentation(segmentID) for segmentID in leafletSegmentIDs]
    valveSurfacePolydata = mergePolydata(*leafletSurfaces)

    maxLeafletDepthMm = 60
    allLeafletSurfacePolyDataWithDistance = \
      MeasurementPreset.getSignedDistance(valveSurfacePolydata, annulusAreaPolyData, -planeNormal, maxLeafletDepthMm)

    distances = \
      vtk.util.numpy_support.vtk_to_numpy(
        allLeafletSurfacePolyDataWithDistance.GetCellData().GetArray("Distance")
      )

    annulusAreaPolyDataBigger = translatePolyData(annulusAreaPolyDataBigger, -planeNormal, max(distances) * 1.2)

    from ValveQuantificationLib.MeasurementPreset import extractValveSurfaceWithSmoothPolyDataFilter
    valveSurface = extractValveSurfaceWithSmoothPolyDataFilter(annulusAreaPolyDataBigger, leafletSurfaces, iterations=3,
                                                               nVertices=5000, subdivide=2, smoothIterations=100,
                                                               relaxationFactor=0.7)

    valveSurface = cls.extrude(valveSurface, planeNormal, abs(depth) + 15)  # +indicatorCutOff)
    pushPolydataToSegmentation(segNode, valveSurface, DEFAULT_SEG_NAME_TOP_MOLD)

  @classmethod
  def createMoldCylinderTemplate(cls, valveModel, parameterNode):
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    depth = float(parameterNode.GetParameter(PARAM_BASE_CLIPPING_DEPTH))

    from ValveQuantificationLib import MeasurementPreset
    annulusPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    [annulusPointsProjected, _, _] = \
      HeartValveLib.getPointsProjectedToPlane(annulusPoints, planePosition, planeNormal)
    annulusPlane2D = MeasurementPreset.createPolyDataFromPolygon(annulusPointsProjected.T)
    annulusPlane2D = translatePolyData(annulusPlane2D, planeNormal, -depth)

    baseClippingPlane = vtk.vtkPlane()
    baseClippingPlane.SetNormal(planeNormal)
    baseClippingPlane.SetOrigin(planePosition + planeNormal * depth)

    # create cylinder that comes from the top and extends to clipping depth
    moldTemplate = cls.buildMold(annulusPlane2D, planeNormal, baseClippingPlane)
    segNode = valveModel.getLeafletSegmentationNode()
    pushPolydataToSegmentation(segNode, moldTemplate, DEFAULT_SEG_NAME_TEMPLATE_ORIGINAL)

    marginSizeMm = float(parameterNode.GetParameter(PARAM_BASE_ADD_MARGIN_MM))

    annulusPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    [annulusPointsProjected, _, _] = \
      HeartValveLib.getPointsProjectedToPlane(annulusPoints, planePosition, planeNormal)
    adjustedPositions = increaseAnnulusDiameter(annulusPointsProjected.T, marginSizeMm, planePosition)
    annulusPlane2D = MeasurementPreset.createPolyDataFromPolygon(adjustedPositions)
    annulusPlane2D = translatePolyData(annulusPlane2D, planeNormal, -depth)

    moldTemplate = cls.buildMold(annulusPlane2D, planeNormal, baseClippingPlane)
    pushPolydataToSegmentation(segNode, moldTemplate, DEFAULT_SEG_NAME_MOLD)

    # create ring around the top part of the mold to subtract any strange artifacts
    inputMarkupsNode = valveModel.annulusContourCurve.controlPointsMarkupNode
    increasedAnnulusNode = cloneMRMLNode(inputMarkupsNode)
    markupsPositions = slicer.util.arrayFromMarkupsControlPoints(increasedAnnulusNode)
    adjustedPositions = increaseAnnulusDiameter(markupsPositions, marginSizeMm+2, planePosition)
    slicer.util.updateMarkupsControlPointsFromArray(increasedAnnulusNode, np.array(adjustedPositions))
    annulusPlane3D = cls.fitTpsDiskToClosedCurve(increasedAnnulusNode)
    slicer.mrmlScene.RemoveNode(increasedAnnulusNode)

    baseClippingPlane.SetNormal(-planeNormal)
    baseClippingPlane.SetOrigin(planePosition + planeNormal * abs(depth))
    moldTemplate = cls.buildMold(annulusPlane3D, planeNormal, baseClippingPlane, -abs(depth)+5)

    pushPolydataToSegmentation(segNode, moldTemplate, DEFAULT_SEG_NAME_TEMPLATE_RING)

    valveVolume = valveModel.getValveVolumeNode()

    subtractSegments(segNode, valveVolume, DEFAULT_SEG_NAME_TEMPLATE_RING, DEFAULT_SEG_NAME_TEMPLATE_ORIGINAL)

  def projectAnnulus(self, valveModel, parameterNode, segmentID=DEFAULT_SEG_NAME_MOLD):
    """ Project the annulus onto the mold model """
    segNode = valveModel.getLeafletSegmentationNode()
    assert segNode.GetSegmentation().GetSegment(segmentID) is not None

    segMold = segNode.GetClosedSurfaceInternalRepresentation(segmentID)

    # Project defined annulus onto inner surface
    normals = vtk.vtkFloatArray()
    normals.SetNumberOfComponents(3)
    projPoints = vtk.vtkPoints()

    planePosition, planeNormal = valveModel.getAnnulusContourPlane()

    margin = float(parameterNode.GetParameter(PARAM_ANNULUS_MARGIN))

    annulusPoints = valveModel.annulusContourCurve.getControlPointsAsArray()
    adjustedPositions = increaseAnnulusDiameter(annulusPoints.T, margin, planePosition).T

    findClosestPoint = parameterNode.GetParameter(PARAM_ANNULUS_PROJECTION_MODE) == "Closest Point"
    verticalLine = parameterNode.GetParameter(PARAM_ANNULUS_PROJECTION_MODE) == "Vertical Line"
    offset = float(parameterNode.GetParameter(PARAM_ANNULUS_OFFSET))

    if findClosestPoint:
      # Use kd-tree to find intersection with model
      loc = vtk.vtkKdTreePointLocator()
      loc.SetDataSet(segMold)
      loc.BuildLocator()
    else:
      loc = vtk.vtkOBBTree()
      loc.SetDataSet(segMold)
      loc.BuildLocator()

    for pos in adjustedPositions.T:
      # Get point above annulus to project towards
      points = vtk.vtkPoints()

      if findClosestPoint:
        idx = loc.FindClosestPoint(pos)
        projPoints.InsertNextPoint(segMold.GetPoint(idx))
      else:
        if verticalLine: # vertical line mode
          r = loc.IntersectWithLine(pos + 4 * planeNormal, pos - 4 * planeNormal, points, None)
          if r != 0:
            projPoints.InsertNextPoint(points.GetPoint(0))
        else: # project inwards to annulus centroid
          center = planePosition + offset * 5 * planeNormal
          stiffenerPos = pos + planeNormal * 12
          r = loc.IntersectWithLine(pos + pos - center, center, points, None)
          if r != 0:
            projPoints.InsertNextPoint(points.GetPoint(0))
            normals.InsertNextTuple3(*((stiffenerPos - center) / np.linalg.norm(stiffenerPos - center)))

    projectedAnnulusContourCurve = self.createProjectedSmoothCurve(projPoints, valveModel,
                                                                   DEFAULT_SEG_NAME_PROJECTED_ANNULUS)

    # subtract projected annulus from molds
    pushPolydataToSegmentation(segNode, projectedAnnulusContourCurve.curveModelNode.GetPolyData(),
                               DEFAULT_SEG_NAME_PROJECTED_ANNULUS)

    segNode.GetSegmentation().GetSegment(DEFAULT_SEG_NAME_PROJECTED_ANNULUS).SetColor(hex2rgb(DEFAULT_COLOR_ANNULUS_PROJECTION))

    # hide fiducials and model node
    slicer.modules.markups.logic().SetAllMarkupsVisibility(projectedAnnulusContourCurve.controlPointsMarkupNode, False)
    projectedAnnulusContourCurve.curveModelNode.GetDisplayNode().SetVisibility3D(False)
    return projectedAnnulusContourCurve

  def subtractAnnulus(self, valveModel):
    segNode = valveModel.getLeafletSegmentationNode()

    if not segNode.GetSegmentation().GetSegment(DEFAULT_SEG_NAME_MOLD):
      logging.warning(f"No segment {DEFAULT_SEG_NAME_MOLD} found.")
      return
    if not segNode.GetSegmentation().GetSegment(DEFAULT_SEG_NAME_PROJECTED_ANNULUS):
      logging.warning(f"No segment {DEFAULT_SEG_NAME_PROJECTED_ANNULUS} found.")
      return

    valveVolume = valveModel.getValveVolumeNode()
    subtractSegments(segNode, valveVolume, DEFAULT_SEG_NAME_MOLD, DEFAULT_SEG_NAME_PROJECTED_ANNULUS)

  @classmethod
  def createProjectedSmoothCurve(cls, projPoints, valveModel, name, closed=True):
    fiducialNode = cls.createMarkupsFiducialNodeFromPoints(projPoints, valveModel, name)
    projectedFiducialsContourModel = cls.createModelAndAddToFolder(vtk.vtkPolyData(), valveModel, name)
    projectedFiducialsContourModel.GetDisplayNode().SetColor(0.8, 0, 1.0)
    projectedFiducialsContourCurve = cls.createSmoothCurve(fiducialNode, projectedFiducialsContourModel, closed)
    return projectedFiducialsContourCurve

  @classmethod
  def createMarkupsFiducialNodeFromPoints(cls, projPoints, valveModel, projectedAnnulusName):
    markupsNodeName = f"{projectedAnnulusName}_Points"
    if slicer.mrmlScene.GetFirstNodeByName(markupsNodeName):
      slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(markupsNodeName))
    fiducialNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", markupsNodeName)
    fiducialNode.CreateDefaultDisplayNodes()
    fiducialNode.GetDisplayNode().SetPointLabelsVisibility(False)
    for idx in range(projPoints.GetNumberOfPoints()):
      fiducialNode.AddControlPointWorld(vtk.vtkVector3d(projPoints.GetPoint(idx)))
    cls.applyProbeToRasTransformAndAddToFolder(fiducialNode, valveModel)
    return fiducialNode

  @staticmethod
  def createSmoothCurve(markupsCurve, curveModel, closed):
    from HeartValveLib import SmoothCurve
    smoothCurve = SmoothCurve.SmoothCurve()
    smoothCurve.setInterpolationMethod(SmoothCurve.InterpolationSpline)
    smoothCurve.setClosed(closed)
    smoothCurve.setControlPointsMarkupNode(markupsCurve)
    smoothCurve.setCurveModelNode(curveModel)
    smoothCurve.setTubeRadius(1.0)
    smoothCurve.updateCurve()
    return smoothCurve

  def generateHPA(self, valveModel, parameterNode, valveHPAHeight=None):
    origAnnulusSmoothCurve = valveModel.annulusContourCurve
    try:
      if slicer.util.toBool(parameterNode.GetParameter(PARAM_HPA_USE_ANNULUS_PROJECTION)) is True:
        projectedAnnulus = self.projectAnnulus(valveModel, parameterNode)
        valveModel.annulusContourCurve = projectedAnnulus

      self.updateProgress("Getting lowest annulus profile point", 1, 4)
      lowestAnnulusPointDistance = self.getLowestAnnulusPoint(valveModel)
      hpaDistanceFromLowestAnnulusPoint = float(parameterNode.GetParameter(PARAM_HPA_DIST_TOP_ANNULUS_MIN))
      # NB: reference is the annulus place which is why we need to subtract the lowest distance
      hpaTopTranslation = hpaDistanceFromLowestAnnulusPoint + lowestAnnulusPointDistance
      parameterNode.SetParameter(PARAM_HPA_Z_TRANSLATION, str(hpaTopTranslation))

      self.updateProgress("Warping disk for basic HPA ring", 2)
      planePosition, planeNormal = valveModel.getAnnulusContourPlane()
      sourceLandmarkPoints = self.getSourceLandmarkPoints(parameterNode)
      circlePointsProbe = self.getCircularShapePointsInProbeCoordinatesWithRotation(valveModel, parameterNode)
      outerDiskRadiusFactor = float(parameterNode.GetParameter(PARAM_OUTER_DISK_RADIUS_FACTOR))
      targetLandmarkPoints = self.getTargetLandmarkPoints(planeNormal, parameterNode, circlePointsProbe)
      warpedDisk = self.warpDisk(sourceLandmarkPoints, targetLandmarkPoints, 1.0, 1.0 * outerDiskRadiusFactor)
      polyDataNormals = self.getPolydataNormals(warpedDisk)

      # landmarks for registering mold assembly
      narray = vtk.util.numpy_support.vtk_to_numpy(targetLandmarkPoints.GetData())
      hpaFixedMarkupsNode = self.getValveModelChildItemByName(valveModel, HPA_FIXED_LANDMARKS_NODE_NAME)
      if hpaFixedMarkupsNode:
        slicer.mrmlScene.RemoveNode(hpaFixedMarkupsNode)
      if slicer.mrmlScene.GetFirstNodeByName(HPA_FIXED_LANDMARKS_NODE_NAME):
        slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(HPA_FIXED_LANDMARKS_NODE_NAME))
      hpaFixedMarkupsNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", HPA_FIXED_LANDMARKS_NODE_NAME)
      hpaFixedMarkupsNode.SetDisplayVisibility(False)
      valveModel.moveNodeToHeartValveFolder(hpaFixedMarkupsNode)

      for pos in narray[::targetLandmarkPoints.GetNumberOfPoints() // 4]:
        hpaFixedMarkupsNode.AddControlPoint(pos)

      # extrude towards annulus plane (default) or by valveHPAHeight given in method call

      self.updateProgress("HPA height extrusion towards annulus", 3)
      if not valveHPAHeight:
        maxAnnulusToValveProfileDistance = self.getMaximumAnnulusToValveProfileDistance(valveModel)
        valveHPAHeight = abs(hpaTopTranslation - maxAnnulusToValveProfileDistance)
      parameterNode.SetParameter(PARAM_HPA_HEIGHT, str(valveHPAHeight))
      parameterNode.SetParameter(PARAM_OUTER_SKIRT_TRANSLATION, str(hpaTopTranslation-valveHPAHeight))
      extrusion = self.extrudePolydata(-planeNormal, polyDataNormals, valveHPAHeight, cappingOn=False)

      normals = vtk.vtkPolyDataNormals()
      normals.SetInputConnection(extrusion.GetOutputPort())
      normals.AutoOrientNormalsOn()
      normals.ConsistencyOn()
      normals.Update()

      # keep outer circle only
      conn = vtk.vtkConnectivityFilter()
      conn.SetInputConnection(normals.GetOutputPort())
      conn.SetExtractionModeToSpecifiedRegions()
      conn.InitializeSpecifiedRegionList()
      conn.AddSpecifiedRegion(1)
      conn.Update()
      hpaBase = conn.GetOutput()

      self.updateProgress("Create inner and outer skirt", 4)
      innerSkirt, outerSkirt = self.createSkirts(valveModel, parameterNode)

      hpaCombined = mergePolydata(hpaBase, polyDataNormals, innerSkirt, outerSkirt)

      # cleaning with point merging
      cleaner = vtk.vtkCleanPolyData()
      cleaner.SetInputData(hpaCombined)
      cleaner.PointMergingOn()
      cleaner.Update()
      hpaCombined = cleaner.GetOutput()

      hpaModelNode = self.createModelAndAddToFolder(hpaCombined, valveModel, DEFAULT_MODEL_NAME_HPA)
      hpaModelNode.GetDisplayNode().SetColor(hex2rgb(DEFAULT_COLOR_HPA))

      if all(self.getMoldAssemblyModels(valveModel)):
        self.addMoldAssembly(valveModel)

    finally:
      valveModel.annulusContourCurve = origAnnulusSmoothCurve

  def getSourceLandmarkPoints(self,
                              parameterNode: slicer.vtkMRMLScriptedModuleNode):
    numberOfLandmarkPoints = int(parameterNode.GetParameter(PARAM_HPA_NUM_LANDMARKS))
    sourceLandmarkPoints = vtk.vtkPoints()
    sourceLandmarkPoints.SetNumberOfPoints(numberOfLandmarkPoints)
    for pointIndex in range(numberOfLandmarkPoints):
      # NB: disk source point at that angle on annulus plane
      angle = float(pointIndex) / numberOfLandmarkPoints * 2.0 * math.pi
      sourceLandmarkPoints.SetPoint(pointIndex, math.cos(angle), math.sin(angle), 0)
    return sourceLandmarkPoints

  def getCircularShapePointsInProbeCoordinatesWithRotation(self, valveModel, parameterNode, outerDiskRadiusFactor=None):

    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    ProbeToAnnulusTransform = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    AnnulusToProbeTransform = np.linalg.inv(ProbeToAnnulusTransform)

    outerDiameterLAX = float(parameterNode.GetParameter(PARAM_LAX_DIAMETER_OUTSIDE))
    outerDiameterSAX = float(parameterNode.GetParameter(PARAM_SAX_DIAMETER_OUTSIDE))

    # NB: mean ratio for thickness from Robarts measurements
    if not outerDiskRadiusFactor:
      innerDiameterLAX = float(parameterNode.GetParameter(PARAM_LAX_DIAMETER_INSIDE))
      innerDiameterSAX = float(parameterNode.GetParameter(PARAM_SAX_DIAMETER_INSIDE))

      ratioLAX = outerDiameterLAX / innerDiameterLAX
      ratioSAX = outerDiameterSAX / innerDiameterSAX

      outerDiskRadiusFactor = np.mean([ratioLAX, ratioSAX])
      parameterNode.SetParameter(PARAM_OUTER_DISK_RADIUS_FACTOR, str(outerDiskRadiusFactor))

    radiusLAX = outerDiameterLAX / 2.0 / outerDiskRadiusFactor
    radiusSAX = outerDiameterSAX / 2.0 / outerDiskRadiusFactor

    # get points for circular shape
    numberOfLandmarkPoints = int(parameterNode.GetParameter(PARAM_HPA_NUM_LANDMARKS))
    circlePointsAnnulus = np.empty((4, numberOfLandmarkPoints,))
    for pointIndex in range(numberOfLandmarkPoints):
      angle = float(pointIndex) / numberOfLandmarkPoints * 2.0 * math.pi
      pointOnCircle = [radiusLAX * math.cos(angle), radiusSAX * math.sin(angle), 0, 1]
      circlePointsAnnulus[:, pointIndex] = pointOnCircle

    circlePointsProbe = np.dot(AnnulusToProbeTransform, circlePointsAnnulus)
    # TODO: make this flexible? The user might want to decide on the rotation so maybe providing a slider with angle...
    rotationMatrix = self.getHPARotation(valveModel, circlePointsProbe)
    circlePointsAnnulus = np.dot(rotationMatrix, circlePointsAnnulus)
    circlePointsProbe = np.dot(AnnulusToProbeTransform, circlePointsAnnulus)

    return circlePointsProbe

  def getHPARotation(self, valveModel, valveRadiusSizeCirclePoints_Probe):
    valveType = valveModel.getValveType()
    if valveType == "tricuspid":
      return self._getTricuspidHPARotation(valveModel, valveRadiusSizeCirclePoints_Probe)
    elif valveType in ["mitral", "lavv"]:
      return self._getMitralHPARotation(valveModel, valveRadiusSizeCirclePoints_Probe)
    else:
      raise NotImplementedError(f"HPA rotation has not been implemented for {valveModel.getValveType()}")

  def _getTricuspidHPARotation(self, valveModel, valveRadiusSizeCirclePoints_Probe):
    # Tricuspid: ASC aligns with short axis of the HPA
    valve_center, planeNormal = valveModel.getAnnulusContourPlane()
    from ValveQuantification import ValveQuantificationLogic

    asc = valveModel.getAnnulusMarkupPositionByLabel("ASC")
    assert asc is not None
    annulus_label = ValveQuantificationLogic.getPointProjectedToAnnularPlane(valveModel, asc)
    sax_idx = valveRadiusSizeCirclePoints_Probe.shape[1] // 4
    sax_annulus_pos = ValveQuantificationLogic.getPointProjectedToAnnularPlane(valveModel,
                                                                               valveRadiusSizeCirclePoints_Probe[0:3,
                                                                               sax_idx])
    C_ASC = annulus_label - valve_center
    C_SAX = sax_annulus_pos - valve_center
    return getRotationalAngle(C_ASC, C_SAX, planeNormal)

  def _getMitralHPARotation(self, valveModel, valveRadiusSizeCirclePoints_Probe):
    # Mitral: Long axis aligns with commissural landmarks
    valve_center, planeNormal = valveModel.getAnnulusContourPlane()

    from ValveQuantification import ValveQuantificationLogic
    pmc, alc = valveModel.getAnnulusMarkupPositionsByLabels(["PMC", "ALC"])
    if pmc is None or alc is None:
      raise ValueError("Commissural landmarks are missing. These are required for the HPA rotation.")
    pmc = ValveQuantificationLogic.getPointProjectedToAnnularPlane(valveModel, pmc)
    alc = ValveQuantificationLogic.getPointProjectedToAnnularPlane(valveModel, alc)

    lax_annulus_pos = \
      ValveQuantificationLogic.getPointProjectedToAnnularPlane(valveModel, valveRadiusSizeCirclePoints_Probe[0:3, 0])

    annulus_label = valve_center + (pmc - alc) / 2
    C_ALC = annulus_label - valve_center
    C_LAX = lax_annulus_pos - valve_center
    return getRotationalAngle(C_ALC, C_LAX, planeNormal)

  def getTargetLandmarkPoints(self, planeNormal, parameterNode, valveRadiusSizeCirclePoints_Probe):
    zTranslation = float(parameterNode.GetParameter(PARAM_HPA_Z_TRANSLATION))
    numberOfLandmarkPoints = int(parameterNode.GetParameter(PARAM_HPA_NUM_LANDMARKS))
    planeNormalUnitVector = (1 / np.linalg.norm(planeNormal)) * planeNormal
    targetLandmarkPoints = vtk.vtkPoints()
    targetLandmarkPoints.SetNumberOfPoints(numberOfLandmarkPoints)
    for pointIndex in range(numberOfLandmarkPoints):
      pos = valveRadiusSizeCirclePoints_Probe[0:3, pointIndex]
      targetLandmarkPoints.SetPoint(pointIndex, pos + planeNormalUnitVector * zTranslation)
    return targetLandmarkPoints

  def getMoldAssemblyModels(self, valveModel):
    return [self.getValveModelChildItemByName(valveModel, name) for name in MOLD_ASSEMBLY_PARTS]

  def addMoldAssembly(self, valveModel):
    hpaFixedMarkupsNode = self.getValveModelChildItemByName(valveModel, HPA_FIXED_LANDMARKS_NODE_NAME)
    if not hpaFixedMarkupsNode:
      logging.info("No HPA fixed landmarks found. HPA created?")
      return

    lidModelNode, lidLandmarksNode = self.loadLidModelAndFixedLandmarks(valveModel)
    assemblyTransformNode = self.createAssemblyToHPATransformNode(hpaFixedMarkupsNode, lidLandmarksNode, valveModel)
    self.transformModelAssemblyParts(assemblyTransformNode, lidModelNode, valveModel)

    # apply to all other assembly parts
    for name in MOLD_ASSEMBLY_PARTS:
      modelNode = self.loadMoldAssemblyPart(name, valveModel)
      self.transformModelAssemblyParts(assemblyTransformNode, modelNode, valveModel)


  def transformModelAssemblyParts(self, assemblyTransformNode, lidModelNode, valveModel):
    lidModelNode.SetAndObserveTransformNodeID(assemblyTransformNode.GetID())
    tfmLogic = slicer.modules.transforms.logic()
    tfmLogic.hardenTransform(lidModelNode)
    self.applyProbeToRasTransformAndAddToFolder(lidModelNode, valveModel)

  def createAssemblyToHPATransformNode(self, hpaFixedMarkupsNode, lidLandmarksNode, valveModel):
    assemblyTransformNode = self.getValveModelChildItemByName(valveModel, MOLD_ASSEMBLY_TO_HPA_TRANSFORM_NODE_NAME)
    if assemblyTransformNode:
      slicer.mrmlScene.RemoveNode(assemblyTransformNode)
    assemblyTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode",
                                                               MOLD_ASSEMBLY_TO_HPA_TRANSFORM_NODE_NAME)
    valveModel.moveNodeToHeartValveFolder(assemblyTransformNode)
    params = {'fixedLandmarks': hpaFixedMarkupsNode,
              'movingLandmarks': lidLandmarksNode,
              'transformType': "Rigid",
              'saveTransform': assemblyTransformNode}
    slicer.cli.run(slicer.modules.fiducialregistration, None, params, wait_for_completion=True)
    return assemblyTransformNode

  def loadLidModelAndFixedLandmarks(self, valveModel):
    lidModelNode = self.loadMoldAssemblyPart(MOLD_ASSEMBLY_LID_NAME, valveModel)
    # unique lid landmarks
    movingMarkupsNode = self.getValveModelChildItemByName(valveModel, HPA_ASSEMBLY_LID_LANDMARKS_NODE_NAME)
    if movingMarkupsNode:
      slicer.mrmlScene.RemoveNode(movingMarkupsNode)
    movingMarkupsNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode",
                                                           HPA_ASSEMBLY_LID_LANDMARKS_NODE_NAME)
    movingMarkupsNode.SetDisplayVisibility(False)
    valveModel.moveNodeToHeartValveFolder(movingMarkupsNode)
    for ptIdx in MOLD_ASSEMBLY_LID_REGISTRATION_VERTICES:
      pos = lidModelNode.GetPolyData().GetPoints().GetPoint(ptIdx)
      movingMarkupsNode.AddControlPoint(pos)
    return lidModelNode, movingMarkupsNode

  def loadMoldAssemblyPart(self, name, valveModel):
    modelNode = self.getValveModelChildItemByName(valveModel, name)
    if modelNode:
      slicer.mrmlScene.RemoveNode(modelNode)
    modelFile = self.resourcePath(f"Models/{name}.stl")
    modelNode = slicer.util.loadModel(modelFile)
    modelNode.SetName(name)
    dNode = modelNode.GetDisplayNode()
    dNode.SetRepresentation(DEFAULT_MOLD_ASSEMBLY_REPRESENTATION)
    dNode.SetOpacity(DEFAULT_MOLD_ASSEMBLY_OPACITY)
    dNode.SetColor(hex2rgb(DEFAULT_COLOR_MOLD_ASSEMBLY))
    valveModel.moveNodeToHeartValveFolder(modelNode)
    return modelNode

  @staticmethod
  def warpDisk(sourceLandmarkPoints, targetLandmarkPoints, innerDiskRadius=1.0, outerDiskRadius=1.2,
               radialResolution=30):

    tsp = vtk.vtkThinPlateSplineTransform()
    tsp.SetSourceLandmarks(sourceLandmarkPoints)
    tsp.SetTargetLandmarks(targetLandmarkPoints)

    unitDisk = vtk.vtkDiskSource()
    unitDisk.SetInnerRadius(innerDiskRadius)
    unitDisk.SetOuterRadius(outerDiskRadius)
    unitDisk.SetCircumferentialResolution(sourceLandmarkPoints.GetNumberOfPoints())
    unitDisk.SetRadialResolution(radialResolution)

    polyTransformToTarget = vtk.vtkTransformPolyDataFilter()  # transforms points and associated normals and vectors
    polyTransformToTarget.SetTransform(tsp)
    polyTransformToTarget.SetInputConnection(unitDisk.GetOutputPort())
    polyTransformToTarget.Update()
    return polyTransformToTarget.GetOutput()

  def getPolydataNormals(self, polydata):
    polyDataNormals = vtk.vtkPolyDataNormals()  # computes cell normals
    polyDataNormals.SetInputData(polydata)
    polyDataNormals.ConsistencyOn()
    polyDataNormals.Update()
    return polyDataNormals.GetOutput()

  @classmethod
  def createModelAndAddToFolder(cls, polydata, valveModel, name):
    model = cls.getValveModelChildItemByName(valveModel, name)
    if model:
      slicer.mrmlScene.RemoveNode(model)
    modelsLogic = slicer.modules.models.logic()
    modelNode = modelsLogic.AddModel(polydata)
    modelNode.SetName(name)
    cls.applyProbeToRasTransformAndAddToFolder(modelNode, valveModel)
    return modelNode

  @classmethod
  def getValveModelChildItemByName(cls, valveModel, name):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    valveNodeItemId = shNode.GetItemByDataNode(valveModel.heartValveNode)
    itemId = shNode.GetItemChildWithName(valveNodeItemId, name)
    node = None
    if itemId:
      node = shNode.GetItemDataNode(itemId)
    return node

  @staticmethod
  def applyProbeToRasTransformAndAddToFolder(node, valveModel):
    valveModel.moveNodeToHeartValveFolder(node)
    probeToRasTransformNode = valveModel.getProbeToRasTransformNode()
    node.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

  @staticmethod
  def extrudePolydata(planeNormal, polyInput, scaleFactor, cappingOn=True):
    extrusion = vtk.vtkLinearExtrusionFilter()
    extrusion.SetInputData(polyInput)
    extrusion.SetScaleFactor(scaleFactor)
    extrusion.SetExtrusionTypeToVectorExtrusion()
    extrusion.SetVector(*planeNormal)
    extrusion.SetCapping(cappingOn)
    extrusion.Update()
    return extrusion

  def getMaximumAnnulusToValveProfileDistance(self, valveModel):
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    annulusPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    from ValveQuantification import MeasurementPreset
    annulusAreaPolyData = MeasurementPreset.createSoapBubblePolyDataFromCircumferencePoints(annulusPoints, 1.2)
    moldSurfacePolyData = valveModel.createValveSurface(planePosition, planeNormal)
    moldSurfacePolyDataWithDistance = \
      MeasurementPreset.getSignedDistance(moldSurfacePolyData, annulusAreaPolyData, planeNormal, 60)
    return self.getMaximumSurfaceDistance(planePosition, moldSurfacePolyDataWithDistance, annulusAreaPolyData)

  @staticmethod
  def getMaximumSurfaceDistance(planePosition, basePolyData, coloringPolyData):
    # Remove points that do not belong to cells
    basePolyDataCleaner = vtk.vtkCleanPolyData()
    basePolyDataCleaner.SetInputData(basePolyData)
    basePolyDataCleaner.Update()
    basePolyDataClean = basePolyDataCleaner.GetOutput()

    import vtk.util.numpy_support as VN
    distanceValues = VN.vtk_to_numpy(basePolyDataClean.GetPointData().GetArray('Distance'))
    maxDistancePointIndex = np.argmax(distanceValues)

    closestPointFinder = vtk.vtkImplicitPolyDataDistance()
    closestPointFinder.SetInput(coloringPolyData)

    point1Pos = basePolyDataClean.GetPoints().GetPoint(maxDistancePointIndex)
    return closestPointFinder.EvaluateFunctionAndGetClosestPoint(point1Pos, planePosition)

  @staticmethod
  def getLowestAnnulusPoint(valveModel):
    annulusControlPoints = valveModel.annulusContourCurve.getControlPointsAsArray()
    _, planeNormal = valveModel.getAnnulusContourPlane()
    from ValveQuantification import ValveQuantificationLogic

    distances = []
    for pos in annulusControlPoints.transpose():
      pProj = ValveQuantificationLogic.getPointProjectedToAnnularPlane(valveModel, pos)
      vec = pos - pProj
      distances.append((vec / planeNormal).mean())
    return np.array(distances).min()

  def createSkirts(self, valveModel, parameterNode):
    sourceLandmarkPoints = self.getSkirtSourceLandmarkPoints(parameterNode)
    outerDiskRadiusFactor = float(parameterNode.GetParameter(PARAM_OUTER_DISK_RADIUS_FACTOR))

    innerCirclePointsProbe = self.getCircularShapePointsInProbeCoordinatesWithRotation(valveModel, parameterNode)
    innerZTranslation = float(parameterNode.GetParameter(PARAM_HPA_Z_TRANSLATION))
    innerCirclePointsProbe, innerSkirtDiskPtsInsideProbe = \
      self.getSkirtDiskOuterAndInnerPoints(parameterNode, valveModel, innerCirclePointsProbe, innerZTranslation)

    outerCirclePointsProbe = self.getCircularShapePointsInProbeCoordinatesWithRotation(valveModel, parameterNode, 1.0)
    outerZTranslation = float(parameterNode.GetParameter(PARAM_OUTER_SKIRT_TRANSLATION))
    outerCirclePointsProbe, outerSkirtDiskPtsInsideProbe = \
      self.getSkirtDiskOuterAndInnerPoints(parameterNode, valveModel, outerCirclePointsProbe, outerZTranslation,
                                           marginSizeMm=float(parameterNode.GetParameter(PARAM_HPA_SKIRT_MIN_THICKNESS)))

    # calculate new inner point from vectors
    numberOfLandmarkPoints = int(parameterNode.GetParameter(PARAM_HPA_NUM_LANDMARKS))
    intersectionPointsProbe = np.empty((4, numberOfLandmarkPoints,))
    for pointIndex in range(numberOfLandmarkPoints):
      p1 = innerSkirtDiskPtsInsideProbe[0:3, pointIndex] # inner point
      innerVec = p1 - innerCirclePointsProbe[0:3, pointIndex]
      p2 = outerSkirtDiskPtsInsideProbe[0:3, pointIndex] # shifted point (outside)
      outerVec = p2 - outerCirclePointsProbe[0:3, pointIndex]

      _, p3 = HeartValveLib.getLinesIntersectionPoints(p1,p1+innerVec,p2,p2+outerVec)
      intersectionPointsProbe[0:3, pointIndex] = p3
      intersectionPointsProbe[3, pointIndex] = 1

    innerTargetLandmarkPoints = \
      self.getSkirtTargetLandmarkPoints(parameterNode, innerCirclePointsProbe, intersectionPointsProbe)
    outerTargetLandmarkPoints = \
      self.getSkirtTargetLandmarkPoints(parameterNode, outerCirclePointsProbe, intersectionPointsProbe)

    innerWarpedDisk = self.warpDisk(sourceLandmarkPoints, innerTargetLandmarkPoints, 1.0, 1.0 * outerDiskRadiusFactor)
    outerWarpedDisk = self.warpDisk(sourceLandmarkPoints, outerTargetLandmarkPoints, 1.0, 1.0 * outerDiskRadiusFactor)
    return innerWarpedDisk, reverseNormals(outerWarpedDisk)

  def findCorrespondingClosestAnnulusPoints(self, valveModel, parameterNode, circlePointsProbe):
    numberOfLandmarkPoints = int(parameterNode.GetParameter(PARAM_HPA_NUM_LANDMARKS))
    # find the corresponding closest points on the annulus (in Probe plane)
    closestCorrespondingAnnulusPointsProbe = np.empty((4, numberOfLandmarkPoints,))

    # plane for cutting through annulus for finding cutting points
    p = vtk.vtkPlaneSource()
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    p.SetOrigin(planePosition)
    p.SetPoint2(planePosition + planeNormal)
    poly = valveModel.annulusContourCurve.curvePoly

    for pointIndex in range(numberOfLandmarkPoints):
      pointOnCircle = circlePointsProbe[0:3, pointIndex]

      p.SetPoint1(pointOnCircle - planeNormal)
      p.Update()

      cutter = getPlaneIntersection(poly, p.GetOrigin(), p.GetNormal())
      cutPoints = np.array([np.array(cutter.GetPoint(ptIdx)) for ptIdx in range(cutter.GetNumberOfPoints())])
      minDist = math.inf
      for ptIdx, pt in enumerate(cutPoints):
        dist = np.linalg.norm(pt - pointOnCircle)
        if dist < minDist:
          closestCorrespondingAnnulusPointsProbe[0:3, pointIndex] = pt
          minDist = dist
      closestCorrespondingAnnulusPointsProbe[3, pointIndex] = 1
    return closestCorrespondingAnnulusPointsProbe

  def getSkirtDiskOuterAndInnerPoints(self, parameterNode, valveModel, circlePointsProbe, zTranslation, marginSizeMm=0.0):
    closestCorrespondingAnnulusPointsProbe = \
      self.findCorrespondingClosestAnnulusPoints(valveModel, parameterNode, circlePointsProbe)
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    planeNormalUnitVector = (1 / np.linalg.norm(planeNormal)) * planeNormal

    numberOfLandmarkPoints = int(parameterNode.GetParameter(PARAM_HPA_NUM_LANDMARKS))
    for pointIndex in range(numberOfLandmarkPoints):
      pos = circlePointsProbe[0:3, pointIndex]
      circlePointsProbe[0:3, pointIndex] = pos + planeNormalUnitVector * zTranslation

    if marginSizeMm:
      hpaPos, hpaPlaneNormal = HeartValveLib.planeFit(circlePointsProbe[0:3])

      # 1. project points to hpa plane
      projPts, _, _ = \
        HeartValveLib.getPointsProjectedToPlane(closestCorrespondingAnnulusPointsProbe[0:3], hpaPos, hpaPlaneNormal)

      # 2. shift radius by marginSizeMm
      dilProjPts = increaseAnnulusDiameter(projPts.T, marginSizeMm, hpaPos)

      for pointIndex, pos in enumerate(dilProjPts):
        vec = pos - hpaPos
        vec = vec / np.linalg.norm(vec)
        pos2 = closestCorrespondingAnnulusPointsProbe[0:3, pointIndex]
        closestCorrespondingAnnulusPointsProbe[0:3, pointIndex] = pos2 + vec * marginSizeMm

    return circlePointsProbe, closestCorrespondingAnnulusPointsProbe

  def getSkirtTargetLandmarkPoints(self, parameterNode, outerDiskPointsProbe, innerDiskPointsProbe):
    numberOfLandmarkPoints = int(parameterNode.GetParameter(PARAM_HPA_NUM_LANDMARKS))

    targetLandmarkPoints = vtk.vtkPoints()
    targetLandmarkPoints.SetNumberOfPoints(2 * numberOfLandmarkPoints)
    for pointIndex in range(numberOfLandmarkPoints):
      targetLandmarkPoints.SetPoint(pointIndex, innerDiskPointsProbe[0:3, pointIndex])
      targetLandmarkPoints.SetPoint(numberOfLandmarkPoints + pointIndex, outerDiskPointsProbe[0:3, pointIndex])
    return targetLandmarkPoints

  # def shiftByMarginAndProjectOnMold(self, valveModel, parameterNode, circlePointsProbe, marginSizeMm):
  #

  def getSkirtSourceLandmarkPoints(self, parameterNode):
    outerDiskRadiusFactor = float(parameterNode.GetParameter(PARAM_OUTER_DISK_RADIUS_FACTOR))
    numberOfLandmarkPoints = int(parameterNode.GetParameter(PARAM_HPA_NUM_LANDMARKS))
    sourceLandmarkPoints = vtk.vtkPoints()
    sourceLandmarkPoints.SetNumberOfPoints(2 * numberOfLandmarkPoints)
    for pointIndex in range(numberOfLandmarkPoints):
      angle = float(pointIndex) / numberOfLandmarkPoints * 2.0 * math.pi
      sourceLandmarkPoints.SetPoint(pointIndex, math.cos(angle), math.sin(angle), 0)
      sourceLandmarkPoints.SetPoint(numberOfLandmarkPoints + pointIndex,
                                    outerDiskRadiusFactor * math.cos(angle),
                                    outerDiskRadiusFactor * math.sin(angle), 0)
    return sourceLandmarkPoints

  @classmethod
  def buildMold(cls, extractedSurface, planeNormal, baseClippingPlane, scaleFactor=40, extrusionPoint=None):
    """
    Constructs the top half of mold by extruding inwards towards annulus center, and bottom half of mold by extruding downwards and clipping.
    :param extractedSurface: Extracted inner surface model
    :param midClippingPlane: definition of middle surface plane
    :param baseClippingPlane: definition of bottom clipping plane
    :return: vtkPolyData models (topHalf, bottomHalf)
    """

    extrude = vtk.vtkLinearExtrusionFilter()
    extrude.CappingOn()
    extrude.SetInputData(extractedSurface)

    if extrusionPoint is not None:
      extrude.SetExtrusionTypeToPointExtrusion()
      extrude.SetScaleFactor(-0.6)
      extrude.SetExtrusionPoint(extrusionPoint)
    else:
      extrude.SetExtrusionTypeToVectorExtrusion()
      extrude.SetVector(planeNormal * -1)
      extrude.SetScaleFactor(scaleFactor)

    extrude.Update()

    normAuto = vtk.vtkPolyDataNormals()
    normAuto.ConsistencyOn()
    normAuto.AutoOrientNormalsOn()
    normAuto.SetInputConnection(extrude.GetOutputPort())
    normAuto.Update()

    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(normAuto.GetOutputPort())
    clean.Update()

    # Perform the bottom clipping at the specified depth
    clipBase = vtk.vtkClipPolyData()
    clipBase.SetClipFunction(baseClippingPlane)
    clipBase.SetInputConnection(clean.GetOutputPort())
    clipBase.Update()

    # Fill bottom clip plane
    cutter = vtk.vtkCutter()
    cutter.SetCutFunction(baseClippingPlane)
    cutter.SetInputConnection(clean.GetOutputPort())
    cutter.Update()

    loop = vtk.vtkContourLoopExtraction()
    loop.SetNormal(baseClippingPlane.GetNormal())
    loop.SetLoopClosureToAll()
    loop.SetInputConnection(cutter.GetOutputPort())
    loop.Update()

    tri = vtk.vtkTriangleFilter()
    tri.SetInputConnection(loop.GetOutputPort())
    tri.Update()

    # Flip bottom surface so normal points out
    reverse = vtk.vtkReverseSense()
    reverse.SetInputConnection(tri.GetOutputPort())
    reverse.Update()

    appendBottom = vtk.vtkAppendPolyData()
    appendBottom.AddInputConnection(clipBase.GetOutputPort())
    appendBottom.AddInputConnection(reverse.GetOutputPort())
    appendBottom.Update()

    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(appendBottom.GetOutputPort())
    clean.Update()

    normAuto = vtk.vtkPolyDataNormals()
    normAuto.ConsistencyOn()
    normAuto.AutoOrientNormalsOn()
    normAuto.SetInputConnection(clean.GetOutputPort())
    normAuto.Update()

    return normAuto.GetOutput()

  def exportMoldToModel(self, valveModel):
    segNode = valveModel.getLeafletSegmentationNode()
    segmentation = segNode.GetSegmentation()

    if not segmentation.GetSegment(DEFAULT_SEG_NAME_MOLD):
      logging.warning(f"Could not find {DEFAULT_SEG_NAME_MOLD} in segmentation.")
      return

    valveVolume = valveModel.getLeafletVolumeNode()
    pushPolydataToSegmentation(segNode, vtk.vtkPolyData(), DEFAULT_SEG_NAME_FINAL_MOLD)
    self.updateProgress("Merging Segments", 1, 3)
    addSegment(segNode, valveVolume, DEFAULT_SEG_NAME_MOLD, DEFAULT_SEG_NAME_FINAL_MOLD)
    if segmentation.GetSegment(DEFAULT_SEG_NAME_MOLD_COAPTATION):
      addSegment(segNode, valveVolume, DEFAULT_SEG_NAME_MOLD_COAPTATION, DEFAULT_SEG_NAME_FINAL_MOLD)
      self.updateProgress("Filling holes", 2)
      spacing = segNode.GetBinaryLabelmapInternalRepresentation(segmentation.GetNthSegmentID(0)).GetSpacing()
      segmentClosing(segNode, valveVolume, DEFAULT_SEG_NAME_MOLD_COAPTATION, np.array(spacing).mean() * 2)

    self.updateProgress("Creating Model", 3)
    polydata = segNode.GetClosedSurfaceInternalRepresentation(DEFAULT_SEG_NAME_FINAL_MOLD)

    if not polydata:
      f"Could not find {DEFAULT_SEG_NAME_FINAL_MOLD} in segmentation."
      return
    modelNode = self.createModelAndAddToFolder(polydata, valveModel, f'{DEFAULT_SEG_NAME_FINAL_MOLD}_Model')
    modelNode.GetDisplayNode().SetColor(hex2rgb(DEFAULT_COLOR_COAPTATION))


class DiastolicValveMoldCreatorLogic(ValveMoldCreatorLogic):

  @classmethod
  def generateMold(cls, valveModel, parameterNode):
    """ Generate the complete surface mold from the segmentation. The mold bottom is clipped to the specified depth and
    returned into the valve segmentation node.
    :param valveModel: SlicerHeart valve model containing annulus definition
    :param parameterNode: additional parameters for generating surface mold
    :return: None
    """

    segNode = valveModel.getLeafletSegmentationNode()
    segmentation = segNode.GetSegmentation()
    spacing = segNode.GetBinaryLabelmapInternalRepresentation(segmentation.GetNthSegmentID(0)).GetSpacing()
    logging.info(f"Voxel spacing of the segmentation: {spacing}")

   # cls.updateProgress("Generating cylinders", 1, 5)
    #cls.createMoldCylinderRing(valveModel, parameterNode)

    cls.updateProgress("Generating top mold", 1, 4)
    topMold = cls.createTopMold(valveModel, parameterNode)

    cls.updateProgress("Generating bottom mold", 2)
    bottomMold = cls.createBottomMold(valveModel, parameterNode)

    cls.updateProgress("Combining top and bottom and cleaning up", 3)
    cls.addTopAndBottom(valveModel, topMold, bottomMold)

    cls.updateProgress("Finishing up", 4)

  @classmethod
  def createTopMold(cls, valveModel, parameterNode):
    """
      Generate the complete surface mold from the segmentation. Clips the bottom of the mold to a specified depth.
      Will output mold to Segmentation node.
      :param segNode: The Segmentation node
      :param heartValveNode: SlicerHeart HeartValve MRML node contatining annulus definition
      :param depth: Clipping depth
      :param volume: Reference volume
      :return: None
    """
    segNode = valveModel.getLeafletSegmentationNode()
    segNode.CreateClosedSurfaceRepresentation()

    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    spacing = getAverageVoxelSpacing(segNode)

    angleToleranceDeg = 88

    # Get the proximal surface of the valve
    valveSegmentation = cls.getOrCreateOnePieceValveSegmentation(segNode, valveModel)
    bottomSurface = cls.extractInnerSurfaceModel(valveSegmentation, valveModel, angleToleranceDeg)
    segNode.GetDisplayNode().SetSegmentVisibility(DEFAULT_SEG_NAME_VALVE_SEGMENTATION, False)

    # increase surface thickness
    imp = vtk.vtkImplicitModeller()
    imp.SetInputData(bottomSurface)
    imp.SetMaximumDistance(0.075)
    imp.SetAdjustDistance(spacing)
    imp.SetProcessModeToPerVoxel()
    imp.AdjustBoundsOn()
    res = [100] * 3
    imp.SetSampleDimensions(*res)
    imp.CappingOff()
    imp.Update()

    # voxel spacing should be isotropic
    contour = vtk.vtkContourFilter()
    contour.ComputeNormalsOn()
    contour.SetInputConnection(imp.GetOutputPort())
    contour.SetValue(0, spacing * 3.5)
    contour.Update()

    from HeartValveLib.LeafletModel import LeafletModel
    extractedSurface = LeafletModel.extractTopSurface(contour.GetOutput(), [-planeNormal], angleToleranceDeg)

    if not extractedSurface:
      raise ValueError("No extracted surface")

    baseClippingPlane = cls.getBaseClippingPlane(valveModel, parameterNode)

    topMold = cls.buildMold(extractedSurface, planeNormal, baseClippingPlane,
                            extrusionPoint=baseClippingPlane.GetOrigin())

    append = vtk.vtkAppendPolyData()
    append.AddInputData(topMold)
    append.AddInputData(contour.GetOutput())
    append.Update()

    normAuto = vtk.vtkPolyDataNormals()
    normAuto.ConsistencyOn()
    normAuto.SetInputConnection(append.GetOutputPort())
    normAuto.Update()

    return normAuto.GetOutput()

  @classmethod
  def createMoldCylinderRing(cls, valveModel, parameterNode):
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    depth = float(parameterNode.GetParameter(PARAM_BASE_CLIPPING_DEPTH))

    from ValveQuantificationLib import MeasurementPreset
    annulusPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    [annulusPointsProjected, _, _] = \
      HeartValveLib.getPointsProjectedToPlane(annulusPoints, planePosition, planeNormal)
    annulusPlane2D = MeasurementPreset.createPolyDataFromPolygon(annulusPointsProjected.T)
    annulusPlane2D = translatePolyData(annulusPlane2D, planeNormal, -depth)

    baseClippingPlane = vtk.vtkPlane()
    baseClippingPlane.SetNormal(planeNormal)
    baseClippingPlane.SetOrigin(planePosition + planeNormal * depth)

    # create cylinder that comes from the top and extends to clipping depth
    moldTemplate = cls.buildMold(annulusPlane2D, planeNormal, baseClippingPlane)
    segNode = valveModel.getLeafletSegmentationNode()
    pushPolydataToSegmentation(segNode, moldTemplate, DEFAULT_SEG_NAME_TEMPLATE_ORIGINAL)

    marginSizeMm = float(parameterNode.GetParameter(PARAM_BASE_ADD_MARGIN_MM))

    # create ring around the top part of the mold to subtract any strange artifacts
    inputMarkupsNode = valveModel.annulusContourCurve.controlPointsMarkupNode
    increasedAnnulusNode = cloneMRMLNode(inputMarkupsNode)
    markupsPositions = slicer.util.arrayFromMarkupsControlPoints(increasedAnnulusNode)
    adjustedPositions = increaseAnnulusDiameter(markupsPositions, marginSizeMm + 2, planePosition)
    slicer.util.updateMarkupsControlPointsFromArray(increasedAnnulusNode, np.array(adjustedPositions))
    annulusPlane3D = cls.fitTpsDiskToClosedCurve(increasedAnnulusNode)
    slicer.mrmlScene.RemoveNode(increasedAnnulusNode)

    baseClippingPlane.SetNormal(-planeNormal)
    baseClippingPlane.SetOrigin(planePosition + planeNormal * abs(depth))
    moldTemplate = cls.buildMold(annulusPlane3D, planeNormal, baseClippingPlane, -abs(depth) + 5)

    pushPolydataToSegmentation(segNode, moldTemplate, DEFAULT_SEG_NAME_TEMPLATE_RING)

    valveVolume = valveModel.getValveVolumeNode()

    worldToPlaneMatrix = cls.getVtkTransformPlaneToWorld(planePosition, planeNormal)
    # print(worldToPlaneMatrix)

    subtractSegments(segNode, valveVolume, DEFAULT_SEG_NAME_TEMPLATE_RING, DEFAULT_SEG_NAME_TEMPLATE_ORIGINAL)

  @classmethod
  def getVtkTransformPlaneToWorld(cls, planePosition, planeNormal):
    import numpy as np
    transformPlaneToWorldVtk = vtk.vtkTransform()
    transformWorldToPlaneMatrix = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    transformPlaneToWorldMatrix = np.linalg.inv(transformWorldToPlaneMatrix)
    print(transformPlaneToWorldMatrix)
    # transformWorldToPlaneMatrixVtk = slicer.util.vtkMatrixFromArray(transformPlaneToWorldMatrix)
    # transformPlaneToWorldVtk.SetMatrix(transformWorldToPlaneMatrixVtk)
    # return transformPlaneToWorldVtk

  @classmethod
  def createBottomMold(cls, valveModel, parameterNode):
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()

    # create bottom of the mold
    marginSizeMm = float(parameterNode.GetParameter(PARAM_BASE_ADD_MARGIN_MM))
    from ValveQuantificationLib.MeasurementPreset import MeasurementPreset

    annulusPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    adjustedPositions = increaseAnnulusDiameter(annulusPoints.T, marginSizeMm, planePosition)
    annulusPlane3D = MeasurementPreset.createSoapBubblePolyDataFromCircumferencePoints(adjustedPositions.T)

    baseClippingPlane = cls.getBaseClippingPlane(valveModel, parameterNode)

    bottomMold = cls.buildMold(annulusPlane3D, planeNormal, baseClippingPlane)

    # topMoldRing = cls.buildMold(annulusPlane3D, -planeNormal, baseClippingPlane)

    return bottomMold #, topMoldRing

  @classmethod
  def addTopAndBottom(cls, valveModel, topMold, bottomMold):
    segNode = valveModel.getLeafletSegmentationNode()
    spacing = getAverageVoxelSpacing(segNode)
    removeAllSegmentsMatchingName(segNode, DEFAULT_SEG_NAME_MOLD)
    valveVolume = valveModel.getValveVolumeNode()

    tempSegNode = createSegmentationNode()

    pushPolydataToSegmentation(tempSegNode, topMold, DEFAULT_SEG_NAME_MOLD)
    gaussianSmoothSegment(tempSegNode, valveVolume, DEFAULT_SEG_NAME_MOLD, standardDeviationMm=spacing * 2)
    pushPolydataToSegmentation(tempSegNode, bottomMold, "bottom")
    addSegment(tempSegNode, valveVolume, "bottom", DEFAULT_SEG_NAME_MOLD)
    leafletSegmentationId = getSegmentIdForSegmentName(segNode, DEFAULT_SEG_NAME_VALVE_SEGMENTATION)

    tempSegNode.GetSegmentation().CopySegmentFromSegmentation(segNode.GetSegmentation(), leafletSegmentationId)
    # Remake closed surface representation after adding mold (makes it generated model from labelmap)
    tempSegNode.RemoveClosedSurfaceRepresentation()
    tempSegNode.CreateClosedSurfaceRepresentation()
    subtractSegments(tempSegNode, valveModel.getValveVolumeNode(), DEFAULT_SEG_NAME_MOLD, leafletSegmentationId)
    # leafletSegmentation = tempSegNode.GetClosedSurfaceInternalRepresentation(leafletSegmentationId)
    # translatedLeafletSegmentation = translatePolyData(leafletSegmentation, planeNormal, 1)
    # pushPolydataToSegmentation(tempSegNode, translatedLeafletSegmentation, DEFAULT_SEG_NAME_VALVE_SEGMENTATION+"_translated")
    # subtractSegments(tempSegNode, valveModel.getValveVolumeNode(), DEFAULT_SEG_NAME_MOLD,
    #                  DEFAULT_SEG_NAME_VALVE_SEGMENTATION+"_translated")
    segmentClosing(tempSegNode, valveModel.getValveVolumeNode(), DEFAULT_SEG_NAME_MOLD, spacing * 6)
    # fillHoles
    # # extrude top surface and subtract
    # topSurface = cls.extrude(topSurface, -planeNormal, depth)
    # pushPolydataToSegmentation(segNode, topSurface, "top_surface")
    # subtractSegments(tempSegNode, valveModel.getValveVolumeNode(), DEFAULT_SEG_NAME_MOLD, "top_surface")
    segNode.GetSegmentation().CopySegmentFromSegmentation(tempSegNode.GetSegmentation(), DEFAULT_SEG_NAME_MOLD)
    slicer.mrmlScene.RemoveNode(tempSegNode)

    # configure segments display
    segNode.GetDisplayNode().SetSegmentVisibility(DEFAULT_SEG_NAME_MOLD, True)
    segNode.GetDisplayNode().SetSegmentVisibility(DEFAULT_SEG_NAME_VALVE_SEGMENTATION, False)
    segNode.GetSegmentation().GetSegment(DEFAULT_SEG_NAME_MOLD).SetColor(hex2rgb(DEFAULT_COLOR_MOLD_BASE))

  @classmethod
  def getOrCreateOnePieceValveSegmentation(cls, segNode, valveModel):
    valveSegId = getSegmentIdForSegmentName(segNode, DEFAULT_SEG_NAME_VALVE_SEGMENTATION)
    if not valveSegId:
      segmentation = segNode.GetSegmentation()
      # merge all leaflets into one
      leaflets = []
      for idx, leafletModel in enumerate(valveModel.leafletModels):
        segmentId = leafletModel.segmentId
        segment = segmentation.GetSegment(segmentId)
        if not segment or not "leaflet" in segment.GetName():
          continue

        leaflets.append(segNode.GetClosedSurfaceInternalRepresentation(segmentId))
      leafletModel = mergePolydata(*leaflets)
      spacing = getAverageVoxelSpacing(segNode)
      pushPolydataToSegmentation(segNode, leafletModel, DEFAULT_SEG_NAME_VALVE_SEGMENTATION)
      segmentClosing(segNode, valveModel.getValveVolumeNode(), DEFAULT_SEG_NAME_VALVE_SEGMENTATION, spacing * 2)
      valveSegmentation = segNode.GetClosedSurfaceInternalRepresentation(DEFAULT_SEG_NAME_VALVE_SEGMENTATION)
    else:
      valveSegmentation = segNode.GetClosedSurfaceInternalRepresentation(valveSegId)
    return valveSegmentation

  @classmethod
  def extractInnerSurfaceModel(cls, leafletModel, valveModel, angleToleranceDeg):
    ## source: https://github.com/pcarnah/SlicerMitralValve/blob/master/MVSegmenter/MVSegmenter.py
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()

    # Decimate leaflet polydata for efficiency
    decimate = vtk.vtkDecimatePro()
    decimate.SetTargetReduction(0.6)
    decimate.PreserveTopologyOn()
    decimate.BoundaryVertexDeletionOff()
    decimate.SetInputData(leafletModel)
    decimate.Update()

    leafletModel = decimate.GetOutput()

    # Get Annulus minimum radius
    annulusPoints = valveModel.getAnnulusContourModelNode().GetPolyData().GetPoints()
    minDis = float('inf')
    for i in range(annulusPoints.GetNumberOfPoints()):
      p = annulusPoints.GetPoint(i)
      dis = np.linalg.norm(np.subtract(planePosition, p))
      minDis = min(minDis, dis)

    # Create tube along annulus plane normal to use for bottom half extraction
    lineSource = vtk.vtkLineSource()
    lineSource.SetPoint1(planePosition + planeNormal * 20)
    lineSource.SetPoint2(planePosition - planeNormal * 20)
    lineSource.Update()

    tubeFilter = vtk.vtkTubeFilter()
    tubeFilter.SetRadius(0.5 * minDis)
    tubeFilter.CappingOff()
    tubeFilter.SetNumberOfSides(50)
    tubeFilter.SetInputConnection(lineSource.GetOutputPort())
    tubeFilter.Update()

    # OBBTree for determining self intersection of rays
    obb = vtk.vtkOBBTree()
    obb.SetDataSet(leafletModel)
    obb.BuildLocator()

    locator = vtk.vtkPointLocator()
    locator.SetDataSet(tubeFilter.GetOutput())
    locator.BuildLocator()

    # Loop over remaining points and build scalar array using different techniques for top and bottom half
    a0 = np.zeros(3)
    p = planePosition + planeNormal * 2
    points = vtk.vtkPoints()
    normals = leafletModel.GetPointData().GetNormals()
    tubeNormals = tubeFilter.GetOutput().GetPointData().GetNormals()
    scalars = vtk.vtkFloatArray()
    scalars.SetNumberOfValues(leafletModel.GetNumberOfPoints())
    for i in range(leafletModel.GetNumberOfPoints()):
      leafletModel.GetPoint(i, a0)
      if np.dot(planeNormal, a0 - p) > 0:
        # Point is above annulus plane, set scalar based on self intersection (scalar value will determine clipping)
        r = obb.IntersectWithLine(a0, planePosition + planeNormal * 5, points, None)

        # If not match try with point below annulus plane
        if points.GetNumberOfPoints() != 1:
          r = obb.IntersectWithLine(a0, planePosition - planeNormal * 5, points, None)

        # If only 1 intersection point, line does not cross through leaflet model as the line always intersects at a0
        if points.GetNumberOfPoints() == 1:
          scalars.SetValue(i, 10)  # Set scalar to large value so point will be kept
        else:
          scalars.SetValue(i, -10)  # Set scalar to small value so point will be discarded
      else:
        # Point is below annulus plane
        # Get the closest point on tube surface, find angle between 2 normals in radians
        closestPoint = locator.FindClosestPoint(a0)
        v = np.array(tubeNormals.GetTuple(closestPoint))
        n = np.array(normals.GetTuple(i))
        angle = math.acos(np.dot(n, v) / np.linalg.norm(n) / np.linalg.norm(v))
        scalars.SetValue(i, angle)  # Set scalar to angle

    # Scalars now angles in radians that we can threshold
    leafletModel.GetPointData().SetScalars(scalars)

    # Clip based on scalar values (keep scalars bigger than value)
    angleToleranceRad = float(angleToleranceDeg) * math.pi / 180.0
    clip2 = vtk.vtkClipPolyData()
    clip2.GenerateClipScalarsOff()
    clip2.SetValue(angleToleranceRad)
    clip2.SetInputData(leafletModel)
    clip2.SetInsideOut(False)

    conn = vtk.vtkConnectivityFilter()
    conn.SetInputConnection(clip2.GetOutputPort())
    conn.SetExtractionModeToLargestRegion()
    conn.Update()

    # Fill small holes resulting from extraction and clean poly data
    fill = vtk.vtkFillHolesFilter()
    fill.SetHoleSize(3)
    fill.SetInputConnection(conn.GetOutputPort())
    fill.Update()

    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(fill.GetOutputPort())
    clean.Update()

    # Fix normals
    normClean = vtk.vtkPolyDataNormals()
    normClean.ConsistencyOn()
    normClean.FlipNormalsOn()
    normClean.SetInputConnection(clean.GetOutputPort())
    normClean.Update()

    innerModel = normClean.GetOutput()
    return innerModel

  @classmethod
  def getBaseClippingPlane(cls, valveModel, parameterNode):
    depth = float(parameterNode.GetParameter(PARAM_BASE_CLIPPING_DEPTH))
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    # Create clipped leaflet mold across middle
    baseClippingPlane = vtk.vtkPlane()
    baseClippingPlane.SetNormal(planeNormal)
    baseClippingPlane.SetOrigin(planePosition + planeNormal * depth)
    return baseClippingPlane


class SegmentEditorWidget(object):
  """ Create segment editor to get access to effects

  Usage:
      ```
        with SegmentEditorWidget() as segmentEditorWidget:
          ... # Do something
      ```
  """

  def __init__(self):
    self.segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
    self.segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
    self.segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
    self.segmentEditorNode.SetOverwriteMode(self.segmentEditorNode.OverwriteNone)
    self.segmentEditorWidget.setMRMLSegmentEditorNode(self.segmentEditorNode)

  def __enter__(self):
    return self.segmentEditorWidget

  def __exit__(self, exc_type, exc_value, tb):
    if exc_type is not None:
      import traceback
      traceback.print_exception(exc_type, exc_value, tb)
    self.segmentEditorWidget = None
    slicer.mrmlScene.RemoveNode(self.segmentEditorNode)
    return True


class ProgressDialog(object):

  def __init__(self):
    self._progressDialog = slicer.util.createProgressDialog(autoClose=False)
    self._progressDialog.setWindowFlags(self._progressDialog.windowFlags() | qt.Qt.WindowStaysOnTopHint)
    self._progressDialog.show()
    slicer.app.processEvents()

  def updateProgress(self, text, value=None, maximum=None):
    if not value:
      value = self._progressDialog.value
    if not maximum:
      maximum = self._progressDialog.maximum
    logging.info(f"{value}/{maximum}: {text}")
    self._progressDialog.labelText = text
    if maximum:
      self._progressDialog.maximum = maximum
    if value:
      self._progressDialog.value = value
    slicer.app.processEvents()

  def _onCanceled(self):
    # self._progressDialog.canceled.disconnect(self._onCanceled)
    raise CanceledException

  def __enter__(self):
    # self._progressDialog.canceled.connect(self._onCanceled)
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    self._progressDialog.close()


#
# ValveMoldCreatorTest
#

class ValveMoldCreatorTest(ScriptedLoadableModuleTest):
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
    self.test_ValveMoldCreator1()

  def test_ValveMoldCreator1(self):
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
    inputVolume = SampleData.downloadSample('ValveMoldCreator1')
    self.delayDisplay('Loaded test data set')

    inputScalarRange = inputVolume.GetImageData().GetScalarRange()
    self.assertEqual(inputScalarRange[0], 0)
    self.assertEqual(inputScalarRange[1], 695)

    outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
    threshold = 100

    # Test the module logic

    logic = ValveMoldCreatorLogic()

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


def increaseAnnulusDiameter(markupsPositions, marginSizeMm, centerPos):
  adjustedPositions = []
  for pos in markupsPositions:
    vec = pos - centerPos
    vec = vec / np.linalg.norm(vec)
    adjustedPositions.append(pos + vec * marginSizeMm)
  return np.array(adjustedPositions)


def cloneMRMLNode(node):
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  itemIDToClone = shNode.GetItemByDataNode(node)
  clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(shNode, itemIDToClone)
  return shNode.GetItemDataNode(clonedItemID)


def addSegment(segNode, masterVolume, sourceSegmentID, destinationSegmentID):

  with SegmentEditorWidget() as segmentEditorWidget:
    segmentEditorWidget.setSegmentationNode(segNode)

    masterVolumeID = masterVolume.GetID()
    segmentEditorWidget.setSourceVolumeNode(slicer.util.getNode(masterVolumeID))
    segmentEditorWidget.setCurrentSegmentID(destinationSegmentID)

    from SegmentEditorEffects.SegmentEditorLogicalEffect import LOGICAL_UNION

    segmentEditorWidget.setActiveEffectByName('Logical operators')
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("Operation", LOGICAL_UNION)
    effect.setParameter("ModifierSegmentID", sourceSegmentID)
    effect.self().onApply()


def subtractSegments(segNode, masterVolume, fromSegmentID, subtrahendSegmentID):

  with SegmentEditorWidget() as segmentEditorWidget:
    segmentEditorWidget.setSegmentationNode(segNode)

    segmentEditorWidget.setSourceVolumeNode(slicer.util.getNode(masterVolume.GetID()))
    segmentEditorWidget.setCurrentSegmentID(fromSegmentID)

    from SegmentEditorEffects.SegmentEditorLogicalEffect import LOGICAL_SUBTRACT

    segmentEditorWidget.setActiveEffectByName('Logical operators')
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("Operation", LOGICAL_SUBTRACT)
    effect.setParameter("ModifierSegmentID", subtrahendSegmentID)
    effect.self().onApply()

    segmentEditorWidget.setActiveEffectByName("Islands")
    effect = segmentEditorWidget.activeEffect()
    effect.self().onApply()


def copySegment(segNode, masterVolume, sourceSegmentID, destinationSegmentID):

  with SegmentEditorWidget() as segmentEditorWidget:
    segmentEditorWidget.setSegmentationNode(segNode)

    masterVolumeID = masterVolume.GetID()
    segmentEditorWidget.setSourceVolumeNode(slicer.util.getNode(masterVolumeID))
    segmentEditorWidget.setCurrentSegmentID(destinationSegmentID)

    from SegmentEditorEffects.SegmentEditorLogicalEffect import LOGICAL_COPY

    segmentEditorWidget.setActiveEffectByName('Logical operators')
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("Operation", LOGICAL_COPY)
    effect.setParameter("ModifierSegmentID", sourceSegmentID)
    effect.self().onApply()


def getAllLeafletSegments(segmentationNode, leafletNameIdentifier="leaflet"):
  segmentation = segmentationNode.GetSegmentation()
  segment = lambda segIdx: segmentation.GetNthSegment(segIdx)
  return [segment(segIdx) for segIdx in range(segmentation.GetNumberOfSegments())
              if leafletNameIdentifier in segment(segIdx).GetName()]


def getAllSegmentIDs(segmentationNode):
  segmentIDs = vtk.vtkStringArray()
  segmentation = segmentationNode.GetSegmentation()
  segmentation.GetSegmentIDs(segmentIDs)
  return [segmentIDs.GetValue(idx) for idx in range(segmentIDs.GetNumberOfValues())]


def getSegmentIdForSegmentName(segmentationNode, name):
  segmentation = segmentationNode.GetSegmentation()
  for segmentId in getAllSegmentIDs(segmentationNode):
    segment = segmentation.GetSegment(segmentId)
    segmentName = segment.GetName()
    print(segmentName)
    if segmentName == name:
      return segmentId
  return None


def removeAllSegmentsMatchingName(segNode, segmentName):
  segmentation = segNode.GetSegmentation()
  while segmentation.GetSegmentIdBySegmentName(segmentName):
    segmentID = segmentation.GetSegmentIdBySegmentName(segmentName)
    if segmentation.GetSegmentIndex(segmentID) != -1:
      segmentation.RemoveSegment(segmentID)


def pushPolydataToSegmentation(segNode, polydata, segmentName):
  import vtkSegmentationCorePython as vtkSegmentationCore
  segmentation = segNode.GetSegmentation()
  removeAllSegmentsMatchingName(segNode, segmentName)
  segment = vtkSegmentationCore.vtkSegment()
  segment.AddRepresentation(
    vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName(), polydata)
  segmentation.AddSegment(segment, segmentName)
  segment.SetName(segmentName)


def segmentClosing(segNode, masterVolume, segmentID, kernelSize=1.0):
  from SegmentEditorEffects.SegmentEditorSmoothingEffect import MORPHOLOGICAL_CLOSING

  with SegmentEditorWidget() as segmentEditorWidget:
    segmentEditorWidget.setSegmentationNode(segNode)
    segmentEditorWidget.setSourceVolumeNode(masterVolume)
    segmentEditorWidget.setCurrentSegmentID(segmentID)

    logging.info("Applying morphological closing on segments")
    segmentEditorWidget.setActiveEffectByName("Smoothing")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("SmoothingMethod", MORPHOLOGICAL_CLOSING)
    effect.setParameter("KernelSizeMm", str(kernelSize))
    effect.self().onApply()


def fillHoles(segNode, masterVolume, segmentID, maximumHoleSizeMm=1.0):
  # Create segment editor to get access to effects
  with SegmentEditorWidget() as segmentEditorWidget:
    segmentEditorWidget.setSegmentationNode(segNode)
    segmentEditorWidget.setSourceVolumeNode(masterVolume)
    segmentEditorWidget.setCurrentSegmentID(segmentID)

    allVertebraeSegmentId = segNode.GetSegmentation().AddEmptySegment()

    # Grow the segment to fill in surface cracks
    segmentEditorWidget.setActiveEffectByName("Margin")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("MarginSizeMm",str(maximumHoleSizeMm))
    effect.self().onApply()
    # Invert the segment
    segmentEditorWidget.setActiveEffectByName("Logical operators")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("Operation", "INVERT")
    effect.self().onApply()
    # Remove islands in inverted segment (these are the holes inside the segment)
    segmentEditorWidget.setActiveEffectByName("Islands")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("Operation", "KEEP_LARGEST_ISLAND")
    effect.self().onApply()
    # Grow the inverted segment by the same margin as before to restore the original size
    segmentEditorWidget.setActiveEffectByName("Margin")
    effect = segmentEditorWidget.activeEffect()
    effect.self().onApply()
    # Invert the inverted segment (it will contain all the segment without the holes)
    segmentEditorWidget.setActiveEffectByName("Logical operators")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("Operation", "INVERT")
    effect.self().onApply()
    # Add it to the allVertebraeSegment
    segmentEditorWidget.setCurrentSegmentID(allVertebraeSegmentId)
    segmentEditorWidget.setActiveEffectByName("Logical operators")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("Operation", "UNION")
    effect.setParameter("ModifierSegmentID", segmentID)
    effect.self().onApply()


def growSegment(segNode, masterVolume, segmentID, marginSizeMm=1.0):
  # Create segment editor to get access to effects
  with SegmentEditorWidget() as segmentEditorWidget:
    logging.info(f"Grow segment {segmentID}")
    segmentEditorWidget.setSegmentationNode(segNode)
    segmentEditorWidget.setSourceVolumeNode(masterVolume)
    segmentEditorWidget.setCurrentSegmentID(segmentID)

    # Smoothing
    segmentEditorWidget.setActiveEffectByName("Margin")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("MarginSizeMm", str(marginSizeMm))
    effect.self().onApply()


def gaussianSmoothSegment(segNode, masterVolume, segmentID, standardDeviationMm=0.8):
  from SegmentEditorEffects.SegmentEditorSmoothingEffect import GAUSSIAN

  # Create segment editor to get access to effects
  with SegmentEditorWidget() as segmentEditorWidget:
    logging.info(f"Smoothing segment {segmentID}")
    segmentEditorWidget.setSegmentationNode(segNode)
    segmentEditorWidget.setSourceVolumeNode(masterVolume)
    segmentEditorWidget.setCurrentSegmentID(segmentID)

    # Smoothing
    segmentEditorWidget.setActiveEffectByName("Smoothing")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("SmoothingMethod", GAUSSIAN)
    effect.setParameter("GaussianStandardDeviationMm", standardDeviationMm)
    effect.self().onApply()


def smoothSegment(segNode, masterVolume, segmentID, kernelSizeMm=1.0, method=None):
  if not method:
    method = "MORPHOLOGICAL_OPENING"

  # Create segment editor to get access to effects
  with SegmentEditorWidget() as segmentEditorWidget:
    logging.info(f"Smoothing segment {segmentID}")
    segmentEditorWidget.setSegmentationNode(segNode)
    segmentEditorWidget.setSourceVolumeNode(masterVolume)
    segmentEditorWidget.setCurrentSegmentID(segmentID)

    # Smoothing
    segmentEditorWidget.setActiveEffectByName("Smoothing")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("SmoothingMethod", method)
    effect.setParameter("KernelSizeMm", kernelSizeMm)
    effect.self().onApply()


def shrinkSegment(segNode, masterVolume, segmentID, marginSizeMm=-1.0):
  with SegmentEditorWidget() as segmentEditorWidget:
    segmentEditorWidget.setSegmentationNode(segNode)

    segmentEditorWidget.setSourceVolumeNode(slicer.util.getNode(masterVolume.GetID()))
    segmentEditorWidget.setCurrentSegmentID(segmentID)

    segmentEditorWidget.setActiveEffectByName("Margin")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("MarginSizeMm", str(marginSizeMm))
    effect.self().onApply()


def getRotationalAngle(vec1, vec2, planeNormal):
  dot = np.dot(vec2, vec1)
  det = np.linalg.det(np.dstack([vec1, vec2, planeNormal]))
  angleRad = math.atan2(det, dot)
  return getRotationMatrix(angleRad)


def getRotationMatrix(angleRad):
  mat = np.eye(4)
  mat[0][0] = math.cos(angleRad)
  mat[1][0] = -math.sin(angleRad)
  mat[0][1] = math.sin(angleRad)
  mat[1][1] = math.cos(angleRad)
  return mat


def translatePolyData(polydata, planeNormal, multiplier):
  transform = vtk.vtkTransform()
  transform.Translate(*(planeNormal * multiplier))
  transform.Update()

  polyScaleTransform = vtk.vtkTransformPolyDataFilter()
  polyScaleTransform.SetTransform(transform)
  polyScaleTransform.SetInputData(polydata)
  polyScaleTransform.Update()

  return polyScaleTransform.GetOutput()


def mergePolydata(*args):
  append = vtk.vtkAppendPolyData()
  for arg in args:
    append.AddInputData(arg)
  append.Update()
  return append.GetOutput()


def increasePolydataThickness(polydata, thickness):
  imp = vtk.vtkImplicitModeller()
  imp.SetInputData(polydata)
  print("maximum distance: ", imp.GetMaximumDistance())
  print("adjust distance: ", imp.GetAdjustDistance())
  imp.SetMaximumDistance(0.1)
  imp.SetAdjustDistance(0.06)

  contour = vtk.vtkContourFilter()
  contour.ComputeNormalsOn()
  contour.SetInputConnection(imp.GetOutputPort())
  contour.SetValue(0, thickness)
  contour.Update()

  return contour.GetOutput()


def createSegmentationNode(name="temp"):
  segmentationNode = slicer.vtkMRMLSegmentationNode()
  segmentationNode.SetName(name)
  slicer.mrmlScene.AddNode(segmentationNode)
  segmentationNode.CreateDefaultDisplayNodes()
  return segmentationNode


def reverseNormals(polydata):
  reverse = vtk.vtkReverseSense()
  reverse.SetInputData(polydata)
  reverse.ReverseNormalsOn()
  reverse.Update()
  return reverse.GetOutput()


def getAverageVoxelSpacing(segNode):
  segmentation = segNode.GetSegmentation()
  spacing = segNode.GetBinaryLabelmapInternalRepresentation(segmentation.GetNthSegmentID(0)).GetSpacing()
  import numpy as np
  spacing = np.array(spacing).mean()
  return spacing


def getPlaneIntersection(polydata, planePos, planeNormal):
  # cut with plane through annulus
  plane = vtk.vtkPlane()
  plane.SetOrigin(planePos)
  plane.SetNormal(planeNormal)

  cutter = vtk.vtkCutter()
  cutter.SetCutFunction(plane)
  cutter.SetInputData(polydata)
  cutter.Update()

  return cutter.GetOutput()


def hex2rgb(hex):
  return np.array(ImageColor.getcolor(hex, "RGB")) / 255.0


class SegmentationSpacingError(Exception):
  pass

class CanceledException(BaseException):
  pass


class DoubleClickObserver(qt.QObject):

  def __init__(self):
    super(DoubleClickObserver, self).__init__()
    self.observedWidgets = dict()
    self.defaultValues = dict()

  def observeWidget(self, labelWidget, destinationWidget, defaultValue):
    labelWidget.installEventFilter(self)
    self.observedWidgets[labelWidget] = (destinationWidget, defaultValue)

  def __del__(self):
    for w in self.observedWidgets.keys():
      w.removeEventFilter(self)

  def eventFilter(self, obj, event):
    if type(event) == qt.QMouseEvent and event.type() == qt.QEvent.MouseButtonDblClick:
      try:
        widget, defaultValue = self.observedWidgets[obj]
        widget.value = defaultValue
        logging.debug(f"Setting default value for {obj}: {defaultValue}")
      except KeyError:
        pass
      return True