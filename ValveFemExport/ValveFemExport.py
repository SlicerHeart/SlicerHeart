import collections
import os
import logging
import math
import qt
import vtk
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import numpy as np

import HeartValveLib

CHORD_COLORS = [[1.0, 0.3, 0.3], [1.0, 0.6, 0.6], [0.3, 1.0, 0.3], [0.8, 1.0, 0.8], [0.3, 0.3, 1.0], [0.8, 0.8, 1.0]]

#
# ValveFemExport
#

class ValveFemExport(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Valve FEM Export"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Andras Lasso (PerkLab)", "Csaba Pinter (Ebatinca)", "Matthew A Jolley (CHOP)"]
    self.parent.helpText = """
Export heart valve leaflet surfaces and chordae tendineae as a finite element method (FEM) model,
for simulation of valve closure in FEBio.
<p>See the <a href="https://github.com/SlicerHeart/SlicerHeart/blob/master/Docs/ValveFemExport.md">module documentation</a>
for prerequisites, required inputs, and a description of the workflow.</p>
"""
    self.parent.acknowledgementText = """
This file was originally developed by Andras Lasso, PerkLab.
<p>If you use this module, please cite: Matthew A. Jolley (Corresponding Author), Nicolas R. Mangine,
Devin W. Laurence, Patricia M. Sabin, Wensi Wu, Christian Herz, Christopher N. Zelonis, Justin S. Unger,
Csaba Pinter, Andras Lasso, Steve A. Maas, Jeffrey A. Weiss, "Effect of Parametric Variation of Chordae
Tendineae Structure on Simulated Atrioventricular Valve Closure", Annals of Biomedical Engineering (In Press).</p>
"""

#
# ValveFemExportWidget
#

class ValveFemExportWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
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
    self._papillaryMuscleTipsNode = None

  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    # Load widget from .ui file (created by Qt Designer)
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/ValveFemExport.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Set scene in MRML widgets. Make sure that in Qt designer
    # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
    # "setMRMLScene(vtkMRMLScene*)" slot.
    uiWidget.setMRMLScene(slicer.mrmlScene)

    self.nodeSelectors = [
      (self.ui.heartValveSelector, "HeartValve"),
      (self.ui.annulusCurveNodeSelector, "AnnulusCurve"),
      (self.ui.annulusModelNodeSelector, "AnnulusModel"),
      (self.ui.papillaryMuscleTipsNodeSelector, "PapillaryMuscleTips"),

      (self.ui.leafletModelNodeComboBox1, "LeafletModel1"),
      (self.ui.leafletBoundaryMarkupsNodeComboBox1, "LeafletBoundaryMarkups1"),
      (self.ui.marginCurveNodeComboBox1, "MarginCurve1"),
      (self.ui.secondaryCurveNodeComboBox1, "SecondaryCurve1"),

      (self.ui.leafletModelNodeComboBox2, "LeafletModel2"),
      (self.ui.leafletBoundaryMarkupsNodeComboBox2, "LeafletBoundaryMarkups2"),
      (self.ui.marginCurveNodeComboBox2, "MarginCurve2"),
      (self.ui.secondaryCurveNodeComboBox2, "SecondaryCurve2"),

      (self.ui.leafletModelNodeComboBox3, "LeafletModel3"),
      (self.ui.leafletBoundaryMarkupsNodeComboBox3, "LeafletBoundaryMarkups3"),
      (self.ui.marginCurveNodeComboBox3, "MarginCurve3"),
      (self.ui.secondaryCurveNodeComboBox3, "SecondaryCurve3"),

      (self.ui.leafletNURBSSurfaceNodeSelector, "LeafletNURBSSurface")
      ]

    curvePlaceWidgets = [
      self.ui.papillaryMuscleTipsPlaceWidget,
      self.ui.leafletBoundaryMarkupsNodePlaceWidget1, self.ui.marginCurvePlaceWidget1, self.ui.secondaryCurvePlaceWidget1,
      self.ui.leafletBoundaryMarkupsNodePlaceWidget2, self.ui.marginCurvePlaceWidget2, self.ui.secondaryCurvePlaceWidget2,
      self.ui.leafletBoundaryMarkupsNodePlaceWidget3, self.ui.marginCurvePlaceWidget3, self.ui.secondaryCurvePlaceWidget3
      ]

    self.parameterEditWidgets = [
      (self.ui.leafletSurfaceNurbsResolution, "LeafletSurfaceNurbsResolution"),
      (self.ui.leafletSurfaceMeshResolution, "LeafletSurfaceMeshResolution"),
      (self.ui.chordsPerCm2Slider, "ChordsPerCm2"),
      (self.ui.createShellModelCheckBox, "CreateLeafletSurfaceShellModel"),
      (self.ui.createChordsCheckBox, "CreateChords"),
      (self.ui.enableEdgeBranchCalculationCheckBox, "EnableEdgeBranchCalculation"),
      (self.ui.enableBodyBranchCalculationCheckBox, "EnableBodyBranchCalculation"),
      (self.ui.edgeChordsPerCmSlider, "EdgeChordsPerCm"),
      ]

    # Create a new parameterNode
    # This parameterNode stores all user choices in parameter values, node selections, etc.
    # so that when the scene is saved and reloaded, these settings are restored.
    self.logic = ValveFemExportLogic()
    self.ui.parameterNodeSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", self.moduleName)
    self.setParameterNode(self.logic.getParameterNode())

    self.ui.heartValveSelector.setNodeTypeLabel("HeartValve", "vtkMRMLScriptedModuleNode")
    self.ui.heartValveSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", "HeartValve")

    for curvePlaceWidget in curvePlaceWidgets:
      slicer.util.findChild(curvePlaceWidget, "MoreButton").hide()

    # Connections
    self.ui.parameterNodeSelector.currentNodeChanged.connect(self.setParameterNode)
    self.ui.heartValveImportButton.clicked.connect(self.onHeartValveImport)
    self.ui.addLeafletRegionBoundaryButton.clicked.connect(self.onAddLeafletRegionBoundary)
    self.ui.deleteLeafletRegionBoundaryButton.clicked.connect(self.onDeleteLeafletRegionBoundary)

    self.ui.leafletRegionBoundaryTreeView.currentItemChanged.connect(self.onLeafletRegionBoundarySelected)
    self.ui.generateButton.clicked.connect(self.onGenerate)
    self.ui.exportButton.clicked.connect(self.onExport)

    slicer.util.addParameterEditWidgetConnections(self.parameterEditWidgets, self.updateParameterNodeFromGUI)
    self.ui.edgeBranchLengthSpinBox.valueChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.numberOfEdgeFanBranchesSpinBox.valueChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.edgeBranchRadiusSpinBox.valueChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.bodyBranchLengthSpinBox.valueChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.numberOfBodyRadialBranchesSpinBox.valueChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.bodyBranchRadiusSpinBox.valueChanged.connect(self.updateParameterNodeFromGUI)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    for nodeSelector, nodeReferenceRole in self.nodeSelectors:
      nodeSelector.currentNodeChanged.connect(self.updateParameterNodeFromGUI)

    self.ui.leafletNURBSSurfaceNodeSelector.currentNodeChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.papillaryMuscleTipPointComboBox.currentTextChanged.connect(self.updateParameterNodeFromGUI)

    # These connections ensure that we update parameter node when scene is closed
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    #TODO: Temporarily hide muscle tip combobox and label
    self.ui.label_4.visible = False
    self.ui.papillaryMuscleTipPointComboBox.visible = False

    # Initial GUI update
    self.updateGUIFromParameterNode()

  def cleanup(self):
    """
    Called when the application closes and the module widget is destroyed.
    """
    self.removeObservers()

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

  def onSceneEndImport(self, caller, event):
    """
    Called just after a scene is imported.
    """
    if self.parent.isEntered:
      self.initializeParameterNode()

  def initializeParameterNode(self):
    """
    Ensure parameter node exists and observed.
    """
    # Parameter node stores all user choices in parameter values, node selections, etc.
    # so that when the scene is saved and reloaded, these settings are restored.
    self.setParameterNode(self.logic.getParameterNode())

  def setParameterNode(self, inputParameterNode):
    """
    Adds observers to the selected parameter node. Observation is needed because when the
    parameter node is changed then the GUI must be updated immediately.
    """
    if inputParameterNode:
      self.logic.setDefaultParameters(inputParameterNode)

    # Set parameter node in the parameter node selector widget
    wasBlocked = self.ui.parameterNodeSelector.blockSignals(True)
    self.ui.parameterNodeSelector.setCurrentNode(inputParameterNode)
    self.ui.parameterNodeSelector.blockSignals(wasBlocked)

    if inputParameterNode == self._parameterNode:
      # No change
      return

    # Unobserve previously selected parameter node and add an observer to the newly selected.
    # Changes of parameter node are observed so that whenever parameters are changed by a script or any other module
    # those are reflected immediately in the GUI.
    if self._parameterNode is not None:
      self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    if inputParameterNode is not None:
      self.addObserver(inputParameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self._parameterNode = inputParameterNode

    # Initial GUI update
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self, caller=None, event=None):
    """
    This method is called whenever parameter node is changed.
    The module GUI is updated to show the current state of the parameter node.
    """

    # Disable all sections if no parameter node is selected
    self.ui.importCollapsibleButton.enabled = self._parameterNode is not None
    self.ui.commonInputsCollapsibleButton.enabled = self._parameterNode is not None
    self.ui.chordsCollapsibleButton.enabled = self._parameterNode is not None
    self.ui.advancedCollapsibleButton.enabled = self._parameterNode is not None
    self.ui.generateButton.enabled = self._parameterNode is not None
    self.ui.exportButton.enabled = self._parameterNode is not None

    if self._parameterNode is None:
      return

    self.updatingGUIFromParameterNode = True

    # Update each widget from parameter node
    # Need to temporarily block signals to prevent infinite recursion (MRML node update triggers
    # GUI update, which triggers MRML node update, which triggers GUI update, ...)

    for nodeSelector, nodeReferenceRole in self.nodeSelectors:
      # Signals are not blocked so that place widgets are updated
      nodeSelector.setCurrentNode(self._parameterNode.GetNodeReference(nodeReferenceRole))

    # Allow free moving of papillary muscle tips (we don't want it to stick to the leaflets)

    papillaryMuscleTipsNode = self._parameterNode.GetNodeReference("PapillaryMuscleTips")
    wasBlocked = self.ui.papillaryMuscleTipPointComboBox.blockSignals(True)
    self.ui.papillaryMuscleTipPointComboBox.clear()
    if papillaryMuscleTipsNode:
      papillaryMuscleTipsNode.CreateDefaultDisplayNodes()
      papillaryMuscleTipsNode.GetDisplayNode().SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeUnconstrained)
      for i in range(papillaryMuscleTipsNode.GetNumberOfControlPoints()):
        if papillaryMuscleTipsNode.GetNthControlPointPositionStatus(i) != slicer.vtkMRMLMarkupsNode.PositionDefined:
          continue
        self.ui.papillaryMuscleTipPointComboBox.addItem(papillaryMuscleTipsNode.GetNthControlPointLabel(i))
    self.ui.papillaryMuscleTipPointComboBox.blockSignals(wasBlocked)

    if self._papillaryMuscleTipsNode != papillaryMuscleTipsNode:
      # Unobserve previously selected PapillaryMuscleTips node and add an observer to the newly selected.
      if self._papillaryMuscleTipsNode is not None:
        self.removeObserver(self._papillaryMuscleTipsNode, slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.updateGUIFromParameterNode)
      if papillaryMuscleTipsNode is not None:
        self.addObserver(papillaryMuscleTipsNode, slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.updateGUIFromParameterNode)
      self._papillaryMuscleTipsNode = papillaryMuscleTipsNode

    self.ui.chordBundleNameEdit1.text = self._parameterNode.GetParameter("ChordName1")
    self.ui.chordBundleNameEdit2.text = self._parameterNode.GetParameter("ChordName2")
    self.ui.chordBundleNameEdit3.text = self._parameterNode.GetParameter("ChordName3")

    self.ui.marginCurveNodeComboBox1.baseName = self.ui.chordBundleNameEdit1.text + " margin curve"
    self.ui.marginCurveNodeComboBox2.baseName = self.ui.chordBundleNameEdit2.text + " margin curve"
    self.ui.marginCurveNodeComboBox3.baseName = self.ui.chordBundleNameEdit3.text + " margin curve"

    self.ui.secondaryCurveNodeComboBox1.baseName = self.ui.chordBundleNameEdit1.text + " secondary curve"
    self.ui.secondaryCurveNodeComboBox2.baseName = self.ui.chordBundleNameEdit2.text + " secondary curve"
    self.ui.secondaryCurveNodeComboBox3.baseName = self.ui.chordBundleNameEdit3.text + " secondary curve"

    for modelSelector, markupsSelector in [
      (self.ui.leafletModelNodeComboBox1, self.ui.chordBundleNameEdit1),
      (self.ui.leafletModelNodeComboBox2, self.ui.chordBundleNameEdit2),
      (self.ui.leafletModelNodeComboBox3, self.ui.chordBundleNameEdit3)
      ]:
      modelNode = modelSelector.currentNode()
      if not modelNode:
        continue
      displayNode = modelNode.GetDisplayNode()
      if not displayNode:
        continue
      color = displayNode.GetColor()
      r = int(color[0] * 255)
      g = int(color[1] * 255)
      b = int(color[2] * 255)
      markupsSelector.setStyleSheet("QLineEdit {{ background: rgb({0}, {1}, {2}); }}".format(r, g, b))

    leafletRegionsFolderId = self.logic.getSubjectHierarchyLeafletRegionBoundariesSubfolder(self._parameterNode)
    self.ui.leafletRegionBoundaryTreeView.setRootItem(leafletRegionsFolderId)
    self.ui.leafletRegionBoundaryTreeView.visible = bool(leafletRegionsFolderId)
    self.ui.branchesFrame.visible = bool(leafletRegionsFolderId)

    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    leafletRegionBoundaryNode = shNode.GetItemDataNode(self.ui.leafletRegionBoundaryTreeView.currentItem())
    if leafletRegionBoundaryNode:
      wasBlocked = self.ui.leafletNURBSSurfaceNodeSelector.blockSignals(True)
      self.ui.leafletNURBSSurfaceNodeSelector.setCurrentNode(self._parameterNode.GetNodeReference("LeafletNURBSSurface"))
      self.ui.leafletNURBSSurfaceNodeSelector.blockSignals(wasBlocked)
      wasBlocked = self.ui.papillaryMuscleTipPointComboBox.blockSignals(True)
      self.ui.papillaryMuscleTipPointComboBox.currentText = leafletRegionBoundaryNode.GetAttribute("PapillaryMuscleTipPoint")
      self.ui.papillaryMuscleTipPointComboBox.blockSignals(wasBlocked)

    slicer.util.updateParameterEditWidgetsFromNode(self.parameterEditWidgets, self._parameterNode)
    self.ui.edgeBranchLengthSpinBox.value = float(self._parameterNode.GetParameter("EdgeBranchLengthMm"))
    self.ui.numberOfEdgeFanBranchesSpinBox.value = float(self._parameterNode.GetParameter("NumberOfEdgeFanBranches"))
    self.ui.edgeBranchRadiusSpinBox.value = float(self._parameterNode.GetParameter("EdgeBranchRadiusMm"))
    self.ui.bodyBranchLengthSpinBox.value = float(self._parameterNode.GetParameter("BodyBranchLengthMm"))
    self.ui.numberOfBodyRadialBranchesSpinBox.value = float(self._parameterNode.GetParameter("NumberOfBodyRadialBranches"))
    self.ui.bodyBranchRadiusSpinBox.value = float(self._parameterNode.GetParameter("BodyBranchRadiusMm"))

    self.updatingGUIFromParameterNode = False

  def updateParameterNodeFromGUI(self, caller=None, event=None):
    """
    This method is called when the user makes any change in the GUI.
    The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
    """

    if self._parameterNode is None:
      return

    if self.updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    parameterNodeItemId = shNode.GetItemByDataNode(self._parameterNode)

    for nodeSelector, nodeReferenceRole in self.nodeSelectors:
      self._parameterNode.SetNodeReferenceID(nodeReferenceRole, nodeSelector.currentNodeID)
      # Ensure the margin curves are in the the "Chord endpoints" folder
      if nodeSelector.currentNode() is None:
        continue
      if ("MarginCurve" in nodeReferenceRole) or ("SecondaryCurve" in nodeReferenceRole) or ("PapillaryMuscleTips" in nodeReferenceRole):
        leafletModelsFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, "Chord endpoints")
        if not leafletModelsFolderItemId:
          leafletModelsFolderItemId = shNode.CreateFolderItem(parameterNodeItemId, "Chord endpoints")
        curveItemId = shNode.GetItemByDataNode(nodeSelector.currentNode())
        shNode.SetItemParent(curveItemId, leafletModelsFolderItemId)

    self._parameterNode.SetParameter("ChordName1", self.ui.chordBundleNameEdit1.text)
    self._parameterNode.SetParameter("ChordName2", self.ui.chordBundleNameEdit2.text)
    self._parameterNode.SetParameter("ChordName3", self.ui.chordBundleNameEdit3.text)

    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    leafletRegionBoundaryNode = shNode.GetItemDataNode(self.ui.leafletRegionBoundaryTreeView.currentItem())
    if leafletRegionBoundaryNode:
      # leafletRegionBoundaryNode.SetCurveTypeToShortestDistanceOnSurface(self.ui.leafletNURBSSurfaceNodeSelector.currentNode())
      leafletRegionBoundaryNode.SetAttribute("PapillaryMuscleTipPoint", self.ui.papillaryMuscleTipPointComboBox.currentText)

    slicer.util.updateNodeFromParameterEditWidgets(self.parameterEditWidgets, self._parameterNode)
    self._parameterNode.SetParameter("EdgeBranchLengthMm", str(self.ui.edgeBranchLengthSpinBox.value))
    self._parameterNode.SetParameter("NumberOfEdgeFanBranches", str(self.ui.numberOfEdgeFanBranchesSpinBox.value))
    self._parameterNode.SetParameter("EdgeBranchRadiusMm", str(self.ui.edgeBranchRadiusSpinBox.value))
    self._parameterNode.SetParameter("BodyBranchLengthMm", str(self.ui.bodyBranchLengthSpinBox.value))
    self._parameterNode.SetParameter("NumberOfBodyRadialBranches", str(self.ui.numberOfBodyRadialBranchesSpinBox.value))
    self._parameterNode.SetParameter("BodyBranchRadiusMm", str(self.ui.bodyBranchRadiusSpinBox.value))

    self._parameterNode.EndModify(wasModified)

  def onHeartValveImport(self):
    heartValveNode = self._parameterNode.GetNodeReference("HeartValve")
    valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)
    wasModified = self._parameterNode.StartModify()

    self._parameterNode.SetNodeReferenceID("AnnulusCurve", valveModel.getAnnulusContourMarkupNode().GetID())
    self._parameterNode.SetNodeReferenceID("AnnulusModel", valveModel.getAnnulusContourModelNode().GetID())

    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    parameterNodeItemId = shNode.GetItemByDataNode(self._parameterNode)

    # Is not set for now:
    # "PapillaryMuscleTips"
    # "MarginCurve1", "SecondaryCurve1"
    # "MarginCurve2", "SecondaryCurve2"
    # "MarginCurve3", "SecondaryCurve3"

    # Shell model (created from leaflet surface by default)
    # or closed surface model (created from leaflet segmentation by default)
    leafletSurfaceShellModel = self._parameterNode.GetParameter("CreateLeafletSurfaceShellModel") == "true"

    if not leafletSurfaceShellModel:
      # Get closed surface model from segmentation
      leafletModelsFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, "Leaflet segmentation")
      if leafletModelsFolderItemId:
        shNode.RemoveItemChildren(leafletModelsFolderItemId)
      else:
        leafletModelsFolderItemId = shNode.CreateFolderItem(parameterNodeItemId, "Leaflet segmentation")
      slicer.modules.segmentations.logic().ExportAllSegmentsToModels(valveModel.getLeafletSegmentationNode(), leafletModelsFolderItemId)
      # Delete annulus mask model
      annulusMaskModelId = shNode.GetItemChildWithName(leafletModelsFolderItemId, "Annulus mask")
      annulusMaskModeNode = shNode.GetItemDataNode(annulusMaskModelId)
      if annulusMaskModeNode:
        slicer.mrmlScene.RemoveNode(annulusMaskModeNode)
      # Put back folder under export folder
      shNode.SetItemParent(leafletModelsFolderItemId, parameterNodeItemId)

    for leafletIndex, leafletModel in enumerate(valveModel.leafletModels):
      # Get leaflet name
      import re
      result = re.match("[^ ]+ (.+) leaflet", leafletModel.getName())
      if result:
        chordName = result.groups()[0]
        self._parameterNode.SetParameter("ChordName"+str(leafletIndex+1), chordName)

      # Get leaflet boundary
      leafletBoundaryMarkupNode = leafletModel.getSurfaceBoundaryMarkupNode()
      self._parameterNode.SetNodeReferenceID("LeafletBoundaryMarkups"+str(leafletIndex+1), leafletBoundaryMarkupNode.GetID())

      # Get leaflet surface
      if leafletSurfaceShellModel:
        # Get shell model
        leafletModelNode = leafletModel.surfaceModelNode
        if leafletModel.surfaceModelNode.GetPolyData().GetNumberOfPoints() == 0:
          leafletModelNode = None
      else:
        # Get closed surface model
        leafletModelId = shNode.GetItemChildWithName(leafletModelsFolderItemId, leafletModel.getLeafletSegment().GetName())
        leafletModelNode = shNode.GetItemDataNode(leafletModelId)
      self._parameterNode.SetNodeReferenceID("LeafletModel"+str(leafletIndex+1), leafletModelNode.GetID())

    self._parameterNode.Modified()
    self._parameterNode.EndModify(wasModified)

  def logCallback(self, message):
    slicer.util.showStatusMessage(message)
    slicer.app.processEvents()

  def onAddLeafletRegionBoundary(self):
    nodeName = slicer.mrmlScene.GetUniqueNameByString("RegionBoundary")
    leafletRegionBoundaryNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", nodeName)
    leafletRegionBoundaryNode.CreateDefaultDisplayNodes()
    displayNode = leafletRegionBoundaryNode.GetDisplayNode()
    displayNode.SetPointLabelsVisibility(False)
    # displayNode.SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeToVisibleSurface)
    displayNode.SetGlyphTypeFromString("Sphere3D")
    displayNode.SetSelectedColor(1, 0.2, 0.7)
    displayNode.SetLineThickness(0.3)
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    newLeafletRegionBoundaryItem = shNode.GetItemByDataNode(leafletRegionBoundaryNode)
    leafletRegionsFolderItem = self.logic.getSubjectHierarchyLeafletRegionBoundariesSubfolder(self._parameterNode, createIfNeeded=True)
    shNode.SetItemParent(newLeafletRegionBoundaryItem, leafletRegionsFolderItem)
    self.ui.leafletRegionBoundaryTreeView.setCurrentItem(newLeafletRegionBoundaryItem)
    self.ui.leafletRegionBoundaryPlaceWidget.setPlaceModeEnabled(True)
    self.updateGUIFromParameterNode()

  def onDeleteLeafletRegionBoundary(self):
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    leafletRegionBoundaryNode = shNode.GetItemDataNode(self.ui.leafletRegionBoundaryTreeView.currentItem())
    slicer.mrmlScene.RemoveNode(leafletRegionBoundaryNode)

  def onLeafletRegionBoundarySelected(self, shItemId):
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    selectedLeafletRegionBoundaryNode = shNode.GetItemDataNode(shItemId)
    if not selectedLeafletRegionBoundaryNode:
      return

    self.ui.leafletRegionBoundaryPlaceWidget.setCurrentNode(selectedLeafletRegionBoundaryNode)
    self.ui.leafletRegionBoundaryPlaceWidget.currentNodeActive = True

    self.updateGUIFromParameterNode()

  def onGenerate(self):
    slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
    try:
      # Clear previous outputs
      self.logic.removeSubjectHierarchyOutputFolder(self._parameterNode)

      # Generate shell or copy existing closed surface mesh
      leafletsFolderItemId = self.logic.createSubjectHierarchyOutputSubfolder(self._parameterNode, "Leaflets")
      if self._parameterNode.GetParameter("CreateLeafletSurfaceShellModel") == 'true':
        leafletSurfaceModels = self.logic.createLeafletSurfaces(self._parameterNode, leafletsFolderItemId, self.logCallback)
        if not leafletSurfaceModels:
          raise RuntimeError("No leaflet models could be created. Disable shell model creation (in 'Advanced output options' section) to use leaflet model as is, without extracting shell by leaflet boundary.")
      else:
        leafletSurfaceModels = self.logic.copyLeafletSurfaces(self._parameterNode, leafletsFolderItemId)

      # Export annulus model and curve
      annulusFolderItemId = self.logic.createSubjectHierarchyOutputSubfolder(self._parameterNode, "Annulus")
      self.logic.copyAnnulusModels(self._parameterNode, annulusFolderItemId)

      # Generate chords
      if self._parameterNode.GetParameter("CreateChords") == "true":
        chordsFolderItemId = self.logic.createSubjectHierarchyOutputSubfolder(self._parameterNode, "Chords")
        self.logic.createChordBundles(self._parameterNode, chordsFolderItemId, leafletSurfaceModels, self.logCallback)
        self.logic.createChordBundlesFromRegions(self._parameterNode, chordsFolderItemId, self.logCallback)

    except Exception as e:
      import traceback
      traceback.print_exc()
      slicer.util.errorDisplay("Failed to generate model: "+str(e))
    slicer.app.restoreOverrideCursor()
    self.logCallback("")

  def onExport(self):
    """
    Run processing when user clicks "Apply" button.
    """
    self.ui.outputPathLineEdit.addCurrentPathToHistory()
    slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
    try:
      currentPath = self.ui.outputPathLineEdit.currentPath
      if not currentPath:
        raise ValueError("No output directory defined. Please select an output directory.")
      firstLeafletModelNode = self._parameterNode.GetNodeReference("LeafletModel1")
      commonParentTransformNode = firstLeafletModelNode.GetParentTransformNode() if firstLeafletModelNode else None
      subjectHierarchyOutputFolder = self.logic.getSubjectHierarchyOutputFolder(self._parameterNode)
      self.logic.exportModel(self._parameterNode, subjectHierarchyOutputFolder, currentPath, commonParentTransformNode, self.logCallback)
      slicer.util.delayDisplay("Model export completed")
    except Exception as e:
      import traceback
      traceback.print_exc()
      slicer.util.errorDisplay("Failed to export model: "+str(e))
    slicer.app.restoreOverrideCursor()
    self.logCallback("")

#
# ValveFemExportLogic
#

class ValveFemExportLogic(ScriptedLoadableModuleLogic):
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
    self.modelStorageNode = None
    self.markupsStorageNode = None
    self.outputSubjectHierarchyFolderName = "FEM-model"

  def setDefaultParameters(self, parameterNode):
    """
    Initialize parameter node with default settings.
    """
    if not parameterNode.GetParameter("LeafletSurfaceNurbsResolution"):
      parameterNode.SetParameter("LeafletSurfaceNurbsResolution", "20")
    if not parameterNode.GetParameter("LeafletSurfaceMeshResolution"):
      parameterNode.SetParameter("LeafletSurfaceMeshResolution", "20")
    if not parameterNode.GetParameter("CreateLeafletSurfaceShellModel"):
      parameterNode.SetParameter("CreateLeafletSurfaceShellModel", "false")  # currently, we more often import the shell than creating it
    if not parameterNode.GetParameter("CreateChords"):
      parameterNode.SetParameter("CreateChords", "true")
    if not parameterNode.GetParameter("ChordsPerCm2"):
      parameterNode.SetParameter("ChordsPerCm2", "8")
    if not parameterNode.GetParameter("EdgeBranchLengthMm"):
      parameterNode.SetParameter("EdgeBranchLengthMm", "3.5")
    if not parameterNode.GetParameter("NumberOfEdgeFanBranches"):
      parameterNode.SetParameter("NumberOfEdgeFanBranches", "3")
    if not parameterNode.GetParameter("EdgeBranchRadiusMm"):
      parameterNode.SetParameter("EdgeBranchRadiusMm", "1")
    if not parameterNode.GetParameter("EnableEdgeBranchCalculation"):
      parameterNode.SetParameter("EnableEdgeBranchCalculation", "true")
    if not parameterNode.GetParameter("EdgeChordsPerCm"):
      parameterNode.SetParameter("EdgeChordsPerCm", "3")
    if not parameterNode.GetParameter("BodyBranchLengthMm"):
      parameterNode.SetParameter("BodyBranchLengthMm", "3.5")
    if not parameterNode.GetParameter("NumberOfBodyRadialBranches"):
      parameterNode.SetParameter("NumberOfBodyRadialBranches", "4")
    if not parameterNode.GetParameter("BodyBranchRadiusMm"):
      parameterNode.SetParameter("BodyBranchRadiusMm", "1")
    if not parameterNode.GetParameter("EnableBodyBranchCalculation"):
      parameterNode.SetParameter("EnableBodyBranchCalculation", "true")
    if not parameterNode.GetParameter("SnapToSurfacePoints"):
      parameterNode.SetParameter("SnapToSurfacePoints", "true")

    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    if parameterNode.GetHideFromEditors():
      parameterNode.SetHideFromEditors(False)
      shNode.RequestOwnerPluginSearch(parameterNode)
      shNode.SetItemAttribute(shNode.GetItemByDataNode(parameterNode), "ModuleName", "ValveFEMExport")

  def createChordBundle(self, baseName, color, startPoints, endPoints, surfaceModel, chordsFolderItemId):
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    folderItem = shNode.CreateFolderItem(shNode.GetSceneItemID(), baseName)
    shNode.SetItemParent(folderItem, chordsFolderItemId)
    # Transform model polydata to world coordinate system
    if surfaceModel.GetParentTransformNode():
      transformModelToWorld = vtk.vtkGeneralTransform()
      slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(surfaceModel.GetParentTransformNode(), None, transformModelToWorld)
      polyTransformToWorld = vtk.vtkTransformPolyDataFilter()
      polyTransformToWorld.SetTransform(transformModelToWorld)
      polyTransformToWorld.SetInputData(surfaceModel.GetPolyData())
      polyTransformToWorld.Update()
      surface_World = polyTransformToWorld.GetOutput()
    else:
      surface_World = surfaceModel.GetPolyData()
    pointLocator = vtk.vtkKdTreePointLocator()
    pointLocator.SetDataSet(surface_World)
    pointLocator.BuildLocator()

    # Create table node for spring import into FEBio
    chordTableNode, chordIndexArray, chordNameArray, chordStartPositionArray, chordEndPositionArray = \
      self.createChordTable(baseName, chordsFolderItemId)

    for endPointIndex in range(endPoints.GetNumberOfControlPoints()):
      endPoint_World = np.zeros(3)
      endPoints.GetNthControlPointPositionWorld(endPointIndex, endPoint_World)
      # Snap to closest mesh point (FEM solver requires constraint to be assigned to a point, not anywhere on the surface)
      closestMeshPointIndex = pointLocator.FindClosestPoint(endPoint_World)
      endPoint_World = surface_World.GetPoint(closestMeshPointIndex)
      # Find closest start point
      closestStartPointDistance2 = np.inf
      closestStartPoint_World = np.zeros(3)
      closestStartPointName = ""
      for startPointIndex in range(startPoints.GetNumberOfControlPoints()):
        startPoint_World = np.zeros(3)
        startPoints.GetNthControlPointPositionWorld(startPointIndex, startPoint_World)
        currentDistance = vtk.vtkMath.Distance2BetweenPoints(startPoint_World, endPoint_World)
        if currentDistance < closestStartPointDistance2:
          closestStartPointDistance2 = currentDistance
          closestStartPoint_World = startPoint_World
          closestStartPointName = startPoints.GetNthControlPointLabel(startPointIndex)
      # Create line
      chordName = "{0}-{1}-{2:02d}".format(baseName,closestStartPointName,endPointIndex)
      line = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", chordName)
      line.SetLocked(True)
      line.CreateDefaultDisplayNodes()
      line.GetDisplayNode().SetSelectedColor(color)
      line.GetDisplayNode().SetPropertiesLabelVisibility(False)
      line.AddControlPointWorld(vtk.vtkVector3d(closestStartPoint_World), closestStartPointName)
      line.AddControlPointWorld(vtk.vtkVector3d(endPoint_World), "{0}-{1:02d}".format(baseName, endPointIndex))
      # Put under subject hierarchy folder
      shNode.SetItemParent(shNode.GetItemByDataNode(line), folderItem)
      # Add chord to the table
      rowIndex = chordTableNode.AddEmptyRow()
      chordIndexArray.SetValue(rowIndex, rowIndex+1)  # index in the table is 1-based
      chordStartPositionArray.SetTuple3(rowIndex, closestStartPoint_World[0], closestStartPoint_World[1], closestStartPoint_World[2])
      chordEndPositionArray.SetTuple3(rowIndex, endPoint_World[0], endPoint_World[1], endPoint_World[2])
      chordNameArray.SetValue(rowIndex, chordName)

  def removeSubjectHierarchyOutputFolder(self, parameterNode):
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    parameterNodeItemId = shNode.GetItemByDataNode(parameterNode)
    outputFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, self.outputSubjectHierarchyFolderName)
    if outputFolderItemId:
      shNode.RemoveItemChildren(outputFolderItemId)

  def getSubjectHierarchyOutputFolder(self, parameterNode):
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    parameterNodeItemId = shNode.GetItemByDataNode(parameterNode)
    outputFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, self.outputSubjectHierarchyFolderName)
    return outputFolderItemId

  def getSubjectHierarchyLeafletRegionBoundariesSubfolder(self, parameterNode, createIfNeeded=False):
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    # Get/create output folder
    parameterNodeItemId = shNode.GetItemByDataNode(parameterNode)
    leafletRegionsFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, "Leaflet region boundaries")
    if not leafletRegionsFolderItemId and createIfNeeded:
      leafletRegionsFolderItemId = shNode.CreateFolderItem(parameterNodeItemId, "Leaflet region boundaries")
    return leafletRegionsFolderItemId

  def createSubjectHierarchyOutputSubfolder(self, parameterNode, subfolderName):
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    # Get/create output folder
    parameterNodeItemId = shNode.GetItemByDataNode(parameterNode)
    outputFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, self.outputSubjectHierarchyFolderName)
    if not outputFolderItemId:
      outputFolderItemId = shNode.CreateFolderItem(parameterNodeItemId, self.outputSubjectHierarchyFolderName)
    # Get/create output subfolder
    outputSubfolderItemId = shNode.GetItemChildWithName(outputFolderItemId, subfolderName)
    if not outputSubfolderItemId:
      outputSubfolderItemId = shNode.CreateFolderItem(outputFolderItemId, subfolderName)
    return outputSubfolderItemId

  def createChordBundles(self, parameterNode, chordsFolderItemId, leafletSurfaceModels, logCallback=None):
    papillaryMuscleTips = parameterNode.GetNodeReference("PapillaryMuscleTips")
    if not papillaryMuscleTips or papillaryMuscleTips.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid papillary muscle tips node")

    slicer.app.pauseRender()
    try:
      for bundleIndex in range(len(leafletSurfaceModels)):
        leafletSurfaceModel = leafletSurfaceModels[bundleIndex]
        leafletMarginCurve = parameterNode.GetNodeReference("MarginCurve"+str(bundleIndex+1))
        leafletSecondaryCurve = parameterNode.GetNodeReference("SecondaryCurve"+str(bundleIndex+1))
        if not leafletSurfaceModel:
          continue
        if logCallback:
          logCallback(f"Creating chord bundles for {leafletSurfaceModel.GetName()}...")
        if leafletMarginCurve:
          self.createChordBundle(leafletSurfaceModel.GetName()+'-primary', CHORD_COLORS[bundleIndex*2],
            papillaryMuscleTips, leafletMarginCurve, leafletSurfaceModel, chordsFolderItemId)
        if leafletSecondaryCurve:
          self.createChordBundle(leafletSurfaceModel.GetName()+'-secondary', CHORD_COLORS[bundleIndex*2+1],
            papillaryMuscleTips, leafletSecondaryCurve, leafletSurfaceModel, chordsFolderItemId)
    finally:
      slicer.app.resumeRender()

  def createChordBundlesFromRegions(self, parameterNode, chordsFolderItemId, logCallback=None):
    """
    Create edge and body chords for each region, which are defined by lines dividing the leaflet into
    regions, which translate to parametric rectangles in the NURBS surface.
    The body and edge chord creation functions also create the fan and radial chord branches as well,
    respectively.
    """
    papillaryMuscleTips = parameterNode.GetNodeReference("PapillaryMuscleTips")
    if not papillaryMuscleTips or papillaryMuscleTips.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid papillary muscle tips node")
    leafletNURBSSurfaceNode = parameterNode.GetNodeReference("LeafletNURBSSurface")
    if not leafletNURBSSurfaceNode or leafletNURBSSurfaceNode.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid leaflet NURBS grid surface node")

    snapToSurface = parameterNode.GetParameter("SnapToSurfacePoints") == 'true'
    if snapToSurface:
      # Create temporary grid surface markup node with a control point at each surface vertex to allow snapping on the dense surface
      leafletNURBSSurfaceNode = self.createDenseNURBSSurface(parameterNode)
    else:
      # Use the input NURBS surface for chord endpoint snapping
      parameterNode.SetNodeReferenceID("LeafletNURBSSurfaceForChordSnapping", leafletNURBSSurfaceNode.GetID())

    try:
      slicer.app.pauseRender()
      nurbsGridResolution = leafletNURBSSurfaceNode.GetGridResolution()
      leafletRegionBoundariesFolderItem = self.getSubjectHierarchyLeafletRegionBoundariesSubfolder(parameterNode)
      leafletRegionNodes = vtk.vtkCollection()
      shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
      shNode.GetDataNodesInBranch(leafletRegionBoundariesFolderItem, leafletRegionNodes, "vtkMRMLMarkupsLineNode")

      # Collect NURBS grid (u,v) coordinates for top line points
      regionBoundaryInnerPointIndices = {}
      minVGridIndex = -1
      for regionIndex in range(leafletRegionNodes.GetNumberOfItems()):
        leafletRegionBoundaryNode = leafletRegionNodes.GetItemAsObject(regionIndex)
        leafletRegionBoundaryNode.GetDisplayNode().SetPropertiesLabelVisibility(False)  # Hide name and length (they just clutter the view after chord generation)
        linePoint0Pos = np.zeros(3)
        leafletRegionBoundaryNode.GetNthControlPointPosition(0, linePoint0Pos)
        linePoint1Pos = np.zeros(3)
        leafletRegionBoundaryNode.GetNthControlPointPosition(1, linePoint1Pos)

        minDist0Index = (np.inf, -1)  # Tuple: (distanceMm, controlPointIndex)
        minDist1Index = (np.inf, -1)  # Tuple: (distanceMm, controlPointIndex)
        currentControlPointPos = np.zeros(3)
        for i in range(leafletNURBSSurfaceNode.GetNumberOfControlPoints()):
          leafletNURBSSurfaceNode.GetNthControlPointPosition(i, currentControlPointPos)
          dist = np.linalg.norm(currentControlPointPos - linePoint0Pos)
          if minDist0Index[0] > dist:
            minDist0Index = (dist, i)
          dist = np.linalg.norm(currentControlPointPos - linePoint1Pos)
          if minDist1Index[0] > dist:
            minDist1Index = (dist, i)

        # Use the point that is not on the border
        if minDist0Index[1] // nurbsGridResolution[0] == 0 or minDist0Index[1] // nurbsGridResolution[0] + 1 == nurbsGridResolution[1]:
          regionBoundaryInnerPointIndices[leafletRegionBoundaryNode] = minDist1Index[1]
          minVGridIndex = minDist0Index[1] // nurbsGridResolution[0]  # Remember border V index
        else:
          regionBoundaryInnerPointIndices[leafletRegionBoundaryNode] = minDist0Index[1]
          minVGridIndex = minDist1Index[1] // nurbsGridResolution[0]  # Remember border V index

      # Get maximum of v coordinates (use that for the parametric rectangles). Also order u coordinates in ascending order
      maxVGridIndex = -1
      linesOrderedByGridU = {}
      for regionBoundaryLineNode, pointIndex in regionBoundaryInnerPointIndices.items():
        pointGridIndex = (pointIndex % nurbsGridResolution[0], pointIndex // nurbsGridResolution[0])
        if pointGridIndex[1] > maxVGridIndex:
          maxVGridIndex = pointGridIndex[1]
        linesOrderedByGridU[pointGridIndex[0]] = regionBoundaryLineNode

      linesOrderedByGridU = collections.OrderedDict(sorted(linesOrderedByGridU.items()))

      if minVGridIndex > maxVGridIndex:  # Swap min and max V if the border V grid index is not 0
        (minVGridIndex, maxVGridIndex) = (maxVGridIndex, minVGridIndex)

      def nextIndex(idx):
        return idx + 1 if idx < leafletRegionNodes.GetNumberOfItems() - 1 else 0

      # Create and distribute points in each rectangle region
      enableEdgeBranchCalculation = parameterNode.GetParameter("EnableEdgeBranchCalculation") == "true"
      enableBodyBranchCalculation = parameterNode.GetParameter("EnableBodyBranchCalculation") == "true"
      numOfEdgePointsWithMultipleChordBranchesMap = {}
      for regionIndex in range(leafletRegionNodes.GetNumberOfItems()):
        leftUGridIndex = list(linesOrderedByGridU.keys())[regionIndex]
        rightUGridIndex = list(linesOrderedByGridU.keys())[nextIndex(regionIndex)]
        if logCallback:
          logCallback(f"Creating chord bundles for region {regionIndex + 1} / {leafletRegionNodes.GetNumberOfItems()}...")
        regionFolderItem = None
        if enableEdgeBranchCalculation:
          (regionFolderItem, numOfEdgePointsWithMultipleChordBranches) = \
            self.createEdgeChordBundleFromRegion(parameterNode, leftUGridIndex, rightUGridIndex, chordsFolderItemId)
          if numOfEdgePointsWithMultipleChordBranches > 0:
            numOfEdgePointsWithMultipleChordBranchesMap[regionIndex] = numOfEdgePointsWithMultipleChordBranches
        if enableBodyBranchCalculation:
          regionFolderItem = self.createBodyChordBundleFromRegion(parameterNode, leftUGridIndex, rightUGridIndex, minVGridIndex, maxVGridIndex, chordsFolderItemId)
        # Create mesh to export
        if regionFolderItem:
          self.createChordsMesh(regionFolderItem)

      if numOfEdgePointsWithMultipleChordBranchesMap:
        message = 'Multiple chord branch endpoints connect to the same leaflet grid point!\n\n'
        for regionIndex in numOfEdgePointsWithMultipleChordBranchesMap.keys():
          message += f'Region {leafletRegionNodes.GetItemAsObject(regionIndex).GetName()}: {numOfEdgePointsWithMultipleChordBranchesMap[regionIndex]} branch endpoints coincide\n'
        slicer.util.warningDisplay(message)

    finally:
      if snapToSurface:
        # Delete temporary dense grid surface markup node
        slicer.mrmlScene.RemoveNode(leafletNURBSSurfaceNode.GetOutputSurfaceModelNode())
        slicer.mrmlScene.RemoveNode(leafletNURBSSurfaceNode)
      slicer.app.resumeRender()

  def subtractWrappingGridIndices(self, leftIndex, rightIndex, gridResolution):
    """Utility function to manage wrapped around grid surface. Subtract two indices along wrapped U side."""
    if leftIndex >= rightIndex:
      return leftIndex - rightIndex
    else:
      return gridResolution[0] - rightIndex + leftIndex

  def incrementWrappingGridIndex(self, index, increment, gridResolution):
    """Utility function to manage wrapped around grid surface. Increment index along wrapped U side."""
    if index < gridResolution[0] - increment:
      return index + increment
    else:
      return index - gridResolution[0] + increment

  def controlPointIndex(self, u, v, gridResolution):
    """Utility function to manage wrapped around grid surface. Get control point index by grid point coordinate."""
    return v * gridResolution[0] + u

  def getSurfaceResolution(self, parameterNode):
    """
    Utility function get the resolution of the interpolated surface model generated from the NURBS grid.
    :return: [xRes, yRes] where xRes is the number of surface mesh points in the U direction and yRes
      is the number of surface mesh points in the V direction. Note that the vertex indices on the surface
      model increase in the V direction first, then in the U direction (which is the opposite of the NURBS
      grid control points).
    """
    leafletNurbsSurfaceNode = parameterNode.GetNodeReference("LeafletNURBSSurface")
    if not leafletNurbsSurfaceNode or leafletNurbsSurfaceNode.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid leaflet NURBS grid surface node")
    leafletModelNode = leafletNurbsSurfaceNode.GetOutputSurfaceModelNode()
    if not leafletModelNode:
      raise ValueError("Model node is not set for the leaflet NURBS grid surface node")
    linSpaceXArray = slicer.util.arrayFromModelPointData(leafletModelNode, 'LinSpaceX')
    # Number of surface mesh points in the U direction based on the linear space values
    xRes = len(np.unique(linSpaceXArray))
    # Number of surface mesh points in the V direction
    yRes = (leafletNurbsSurfaceNode.GetGridResolution()[1] - 1) * int(leafletNurbsSurfaceNode.GetSamplingResolution()) + 1
    return [xRes, yRes]

  def createEdgeChordBundleFromRegion(self, parameterNode, leftUGridIndex, rightUGridIndex, chordsFolderItemId):
    """
    Create edge chord bundle for the region defined by the parametric rectangle on the NURBS grid.
    If SnapToSurfacePoints is enabled, the edge chord endpoints are snapped to the surface points instead of the NURBS grid points.

    :param parameterNode:
    :param leftUGridIndex: "Left" U grid index (defined on NURBS grid) for the region parametric rectangle
    :param rightUGridIndex: "Right" U grid index (defined on NURBS grid) for the region parametric rectangle
    :param chordsFolderItemId:
    :return int: SH folder item that contains the chords for the region
    """
    leafletNurbsSurfaceNode = parameterNode.GetNodeReference("LeafletNURBSSurfaceForChordSnapping")
    if not leafletNurbsSurfaceNode or leafletNurbsSurfaceNode.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid leaflet NURBS grid surface node")
    papillaryMuscleTipsNode = parameterNode.GetNodeReference("PapillaryMuscleTips")
    if not papillaryMuscleTipsNode:
      raise RuntimeError('Failed to find papillary muscle tips node')

    # Get variables used for calculation
    chordsPerMm = float(parameterNode.GetParameter("EdgeChordsPerCm") if parameterNode.GetParameter("EdgeChordsPerCm") else "3") / 10.0  # Divide by 10 because the slider uses cm
    baseName = f'{leafletNurbsSurfaceNode.GetName()} (region {leftUGridIndex} - {rightUGridIndex})'
    res = leafletNurbsSurfaceNode.GetGridResolution()  # Increase readability by shortening lines in later function calls

    # Get average papillary muscle tip point
    pos = np.zeros(3)
    meanPapillaryMuscleTipPoint = np.zeros(3)
    for i in range(papillaryMuscleTipsNode.GetNumberOfControlPoints()):
      papillaryMuscleTipsNode.GetNthControlPointPosition(i, pos)
      meanPapillaryMuscleTipPoint += pos
    meanPapillaryMuscleTipPoint /= papillaryMuscleTipsNode.GetNumberOfControlPoints()
    # Get V index that is closer to the average papillary muscle tip point
    minimumDistance = float('inf')
    vGridIndex = -1
    for v in [0, res[1] - 1]:
      numberOfEdgePoints = self.subtractWrappingGridIndices(rightUGridIndex, leftUGridIndex, res) + 1
      pointSum = np.zeros(3)
      for u in range(numberOfEdgePoints):
        edgeControlPointIndex = self.controlPointIndex(self.incrementWrappingGridIndex(leftUGridIndex, u, res), v, res)
        leafletNurbsSurfaceNode.GetNthControlPointPosition(edgeControlPointIndex, pos)
        pointSum += pos
      distance = np.linalg.norm(pointSum / numberOfEdgePoints - meanPapillaryMuscleTipPoint)
      if distance < minimumDistance:
        minimumDistance = distance
        vGridIndex = v

    # Calculate edge length in the region using a temporary curve
    edgePoints = vtk.vtkPoints()
    for u in range(self.subtractWrappingGridIndices(rightUGridIndex, leftUGridIndex, res) + 1):
      edgeControlPointIndex = self.controlPointIndex(self.incrementWrappingGridIndex(leftUGridIndex, u, res), vGridIndex, res)
      leafletNurbsSurfaceNode.GetNthControlPointPosition(edgeControlPointIndex, pos)
      edgePoints.InsertNextPoint(pos[0], pos[1], pos[2])
    tempEdgeCurveNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode', f'{baseName} EdgeCurve Temp')
    tempEdgeCurveNode.SetControlPointPositionsWorld(edgePoints)
    tempEdgeCurveNode.GetMeasurement('length').SetEnabled(True)
    edgeLengthMm = tempEdgeCurveNode.GetMeasurement('length').GetValue()

    # Get number of chords placed on the edge for region
    numberOfChords = int(edgeLengthMm * chordsPerMm + 0.5)

    # Distribute points
    regionEdgeStep = (self.subtractWrappingGridIndices(rightUGridIndex, leftUGridIndex, res) + 1) / numberOfChords
    regionEdgeStart = self.incrementWrappingGridIndex(leftUGridIndex, regionEdgeStep / 2, res)
    pointPositions = []
    meanEdgePoint = np.zeros(3)
    for u in range(numberOfChords):
      regionEdgePosU = self.incrementWrappingGridIndex(regionEdgeStart, u * regionEdgeStep, res)
      pos = np.zeros(3)
      leafletNurbsSurfaceNode.GetNthControlPointPosition(self.controlPointIndex(int(regionEdgePosU + 0.5), vGridIndex, res), pos)
      pointPositions.append(pos)
      meanEdgePoint += pos
    meanEdgePoint /= numberOfChords

    # Create folder for the chords for the current region
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    regionFolderItem = shNode.GetItemByName(baseName)  # The body chord creation function may have already created the folder
    if not regionFolderItem:
      regionFolderItem = shNode.CreateFolderItem(shNode.GetSceneItemID(), baseName)
      shNode.SetItemParent(regionFolderItem, chordsFolderItemId)

    # Automatically find closest papillary muscle tip point for region
    minDistanceToMeanPoint = (np.inf, -1)
    for i in range(papillaryMuscleTipsNode.GetNumberOfControlPoints()):
      pos = np.zeros(3)
      papillaryMuscleTipsNode.GetNthControlPointPosition(i, pos)
      if np.linalg.norm(pos - meanEdgePoint) < minDistanceToMeanPoint[0]:
        minDistanceToMeanPoint = (np.linalg.norm(pos - meanEdgePoint), i)

    closestPapillatyMuscleTipPos = np.zeros(3)
    papillaryMuscleTipsNode.GetNthControlPointPosition(minDistanceToMeanPoint[1], closestPapillatyMuscleTipPos)

    # Create all chords and chord branches
    tempEdgeCurveControlPointsWithBranches = {}
    for endPointIndex, endPoint_World in enumerate(pointPositions):
      # Create line
      chordName = f'{baseName}-edge{endPointIndex:02d}'
      line = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", chordName)
      self.setupChordLine(line, CHORD_COLORS[0])
      line.AddControlPointWorld(vtk.vtkVector3d(closestPapillatyMuscleTipPos), papillaryMuscleTipsNode.GetNthControlPointLabel(minDistanceToMeanPoint[1]))
      line.AddControlPointWorld(vtk.vtkVector3d(endPoint_World), chordName)
      # Put under subject hierarchy folder
      shNode.SetItemParent(shNode.GetItemByDataNode(line), regionFolderItem)

      # Create chord branching
      newBranches = self.createFanChordBranching(parameterNode, line, regionFolderItem, tempEdgeCurveNode)
      tempEdgeCurveControlPointsWithBranches = {k: newBranches.get(k, 0) + tempEdgeCurveControlPointsWithBranches.get(k, 0) for k in set(newBranches) | set(tempEdgeCurveControlPointsWithBranches)}

    # Remove temporary node
    slicer.mrmlScene.RemoveNode(tempEdgeCurveNode)

    numOfEdgePointsWithMultipleChordBranches = sum(value > 1 for value in tempEdgeCurveControlPointsWithBranches.values())
    return (regionFolderItem, numOfEdgePointsWithMultipleChordBranches)

  def createFanChordBranching(self, parameterNode, chordLineNode, regionFolderItem, tempEdgeCurveNode):
    """
    Create fan branching at the valve end of a primary (edge) chord represented by given markups line node.

      P : papillary muscle endpoint
      |
     ...
      |
      │ chord line coming from papillary muscle tip
      │
      C : branching point
      │\
      │ \
      │  \
      │   \
      │    \
      │     \
      │  r   \
      A───────B : fan branch endpoint
       : central branch endpoint

    """
    if not chordLineNode or chordLineNode.GetNumberOfControlPoints() != 2:
      raise ValueError("Invalid chord line node")
    leafletNurbsNode = parameterNode.GetNodeReference("LeafletNURBSSurfaceForChordSnapping")
    if not leafletNurbsNode or leafletNurbsNode.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid leaflet NURBS node")
    if not tempEdgeCurveNode or tempEdgeCurveNode.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid temporary edge curve node")
    if not regionFolderItem:
      raise ValueError("Invalid region folder item ID")

    edgeBranchLengthMm = float(parameterNode.GetParameter("EdgeBranchLengthMm"))
    numberOfEdgeFanBranches = round(float(parameterNode.GetParameter("NumberOfEdgeFanBranches")))
    edgeBranchRadiusMm = float(parameterNode.GetParameter("EdgeBranchRadiusMm"))

    # Get branching point on chord line
    pointP = np.zeros(3)
    chordLineNode.GetNthControlPointPositionWorld(0, pointP)
    pointA = np.zeros(3)
    chordLineNode.GetNthControlPointPositionWorld(1, pointA)
    vectorPA = pointA - pointP
    pointC = pointA - vectorPA / np.linalg.norm(vectorPA) * edgeBranchLengthMm
    # Change endpoint of the main chord line to only reach the branching point
    chordLineNode.SetNthControlPointPositionWorld(1, pointC)

    # Create folder for chord branch
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    branchesFolderItem = shNode.CreateFolderItem(shNode.GetSceneItemID(), f'{chordLineNode.GetName()} - branches')
    shNode.SetItemParent(branchesFolderItem, regionFolderItem)

    # Determine section of edge centered at point A that has 2 radius length (curve length)
    tempEdgeSectionCurveNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode', f'{chordLineNode.GetName()} EdgeSectionCurve Temp')
    tempEdgeSectionCurveNode.GetMeasurement('length').SetEnabled(True)

    pointA_Idx = tempEdgeCurveNode.GetClosestControlPointIndexToPositionWorld(pointA)
    tempEdgeSectionCurveNode.AddControlPointWorld(pointA)

    edgeSectionLengthMm = 0
    edgeSectionLeftIdx = pointA_Idx  # Left end of the edge section as control point index in temporary edge curve (argument)
    edgeSectionRightIdx = pointA_Idx  # Right end of the edge section as control point index in temporary edge curve (argument)
    currentPoint = np.zeros(3)
    iteration = 0
    while edgeSectionLengthMm < edgeBranchRadiusMm * 2.0:  # Until section is just longer than radius
      # Add control point to alternating sides from point A
      if iteration % 2:  # Towards "right"
        if edgeSectionRightIdx == tempEdgeCurveNode.GetNumberOfControlPoints() - 1:  # We stop at the edge of the curve (cannot wrap as it is an open curve)
          iteration += 1
          continue
        currentIdx = edgeSectionRightIdx = edgeSectionRightIdx + 1
      else:
        if edgeSectionLeftIdx == 0:  # We stop at the edge of the curve (cannot wrap as it is an open curve)
          iteration += 1
          continue
        currentIdx = edgeSectionLeftIdx = edgeSectionLeftIdx - 1
      tempEdgeCurveNode.GetNthControlPointPosition(currentIdx, currentPoint)
      if iteration % 2:  # Towards "right"
        tempEdgeSectionCurveNode.AddControlPointWorld(currentPoint)
      else:
        tempEdgeSectionCurveNode.InsertControlPointWorld(0, currentPoint)
      iteration += 1
      edgeSectionLengthMm = tempEdgeSectionCurveNode.GetMeasurement('length').GetValue()

    # Resample edge section curve
    tempEdgeSectionCurveNode.ResampleCurveWorld(edgeSectionLengthMm / (numberOfEdgeFanBranches - 1))

    # Add chord branch lines
    newBranches = {}
    for branchIdx in range(numberOfEdgeFanBranches):
      branchName = f'{chordLineNode.GetName()}-{branchIdx + 1}'
      branchLine = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", branchName)
      self.setupChordLine(branchLine, CHORD_COLORS[1])
      branchLine.AddControlPointWorld(pointC)
      # Get closest edge grid point to the ideal branch endpoint position
      tempEdgeSectionCurveNode.GetNthControlPointPosition(branchIdx, currentPoint)
      branchEndpointIdx = tempEdgeCurveNode.GetClosestControlPointIndexToPositionWorld(currentPoint)
      if branchEndpointIdx in newBranches.keys():
        newBranches[branchEndpointIdx] = newBranches[branchEndpointIdx] + 1
      else:
        newBranches[branchEndpointIdx] = 1
      tempEdgeCurveNode.GetNthControlPointPosition(branchEndpointIdx, currentPoint)
      branchLine.AddControlPointWorld(currentPoint)
      # Put under subject hierarchy folder
      shNode.SetItemParent(shNode.GetItemByDataNode(branchLine), branchesFolderItem)

    # Remove temporary node
    slicer.mrmlScene.RemoveNode(tempEdgeSectionCurveNode)

    return newBranches

  def createBodyChordBundleFromRegion(self, parameterNode, leftUGridIndex, rightUGridIndex, minVGridIndex, maxVGridIndex, chordsFolderItemId):
    """
    Create body chords for the region defined by the parametric rectangle on the NURBS grid.
    If SnapToSurfacePoints is enabled, the chords will be placed on the surface points instead of the NURBS grid points.

    :param parameterNode:
    :param leftUGridIndex: "Left" U grid index (defined on NURBS grid) for the region parametric rectangle
    :param rightUGridIndex: "Right" U grid index (defined on NURBS grid) for the region parametric rectangle
    :param minVGridIndex: Minimum V grid index (defined on NURBS grid) for the region parametric rectangle
    :param maxVGridIndex: Maximum V grid index (defined on NURBS grid) for the region parametric rectangle
    :param chordsFolderItemId:
    :return int: SH folder item that contains the chords for the region
    """
    leafletNurbsSurfaceNode = parameterNode.GetNodeReference("LeafletNURBSSurfaceForChordSnapping")
    if not leafletNurbsSurfaceNode or leafletNurbsSurfaceNode.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid leaflet NURBS grid surface node")

    # Get variables used for calculation
    chordsPerMm2 = float(parameterNode.GetParameter("ChordsPerCm2") if parameterNode.GetParameter("ChordsPerCm2") else "8") / 100.0  # Divide by 100 because chordsDensity is in length unit (mm)
    baseName = f'{leafletNurbsSurfaceNode.GetName()} (region {leftUGridIndex} - {rightUGridIndex})'
    res = leafletNurbsSurfaceNode.GetGridResolution()  # Increase readability by shortening lines in later function calls

    # Create temporary grid surface markup containing only the defined region
    regionGridPoints = vtk.vtkPoints()
    regionGridResolution = (self.subtractWrappingGridIndices(rightUGridIndex, leftUGridIndex, res) + 1, maxVGridIndex - minVGridIndex + 1)
    regionGridPoints.SetNumberOfPoints(regionGridResolution[0] * regionGridResolution[1])
    currentPos = np.zeros(3)
    for v in range(regionGridResolution[1]):
      for u in range(regionGridResolution[0]):
        leafletControlPointIndex = self.controlPointIndex(self.incrementWrappingGridIndex(leftUGridIndex, u, res), minVGridIndex + v, res)
        leafletNurbsSurfaceNode.GetNthControlPointPosition(leafletControlPointIndex, currentPos)
        regionGridPoints.SetPoint(v * regionGridResolution[0] + u, currentPos[0], currentPos[1], currentPos[2])

    regionGridSurfaceNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsGridSurfaceNode', f'{baseName} Temp')
    regionGridSurfaceNode.SetGridResolution(regionGridResolution)
    regionGridSurfaceNode.SetControlPointPositionsWorld(regionGridPoints)

    # Calculate region area
    regionModelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', f'{baseName} Temp Model')
    regionGridSurfaceNode.SetOutputSurfaceModelNodeID(regionModelNode.GetID())
    massProperties = vtk.vtkMassProperties()
    massProperties.SetInputData(regionModelNode.GetPolyData())
    massProperties.Update()
    regionAreaMm2 = massProperties.GetSurfaceArea()

    # Get number of chords placed for region
    numberOfChords = int(regionAreaMm2 * chordsPerMm2 + 0.5)

    # Distribute points
    chordGridResolutionV = int((numberOfChords * regionGridResolution[1]) / regionGridResolution[0] + 0.5)
    chordGridResolutionU = math.ceil(numberOfChords / chordGridResolutionV)

    regionGridStep = np.array([regionGridResolution[0] / chordGridResolutionU, regionGridResolution[1] / chordGridResolutionV])
    regionGridStart = regionGridStep / 2

    pointPositions = []
    meanRegionPoint = np.zeros(3)
    for v in range(chordGridResolutionV):
      rowUOffset = -regionGridStep / 4 if v % 2 else regionGridStep / 4  # Alternating offset within grid cell for each row
      rowUOffset[1] = 0  # We only want offset in the U direction
      for u in range(chordGridResolutionU):
        regionGridPos = np.round(regionGridStart + rowUOffset + np.array([u * regionGridStep[0], v * regionGridStep[1]]))
        pos = np.zeros(3)
        regionGridSurfaceNode.GetNthControlPointPosition(self.controlPointIndex(int(regionGridPos[0] + 0.5), int(regionGridPos[1] + 0.5), regionGridResolution), pos)
        pointPositions.append(pos)
        meanRegionPoint += pos
    meanRegionPoint /= chordGridResolutionU * chordGridResolutionV

    # Create folder for the chords for the current region
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    regionFolderItem = shNode.GetItemByName(baseName)  # The edge chord creation function may have already created the folder
    if not regionFolderItem:
      regionFolderItem = shNode.CreateFolderItem(shNode.GetSceneItemID(), baseName)
      shNode.SetItemParent(regionFolderItem, chordsFolderItemId)

    # Automatically find closest papillary muscle tip point for region
    papillaryMuscleTipsNode = parameterNode.GetNodeReference("PapillaryMuscleTips")
    if not papillaryMuscleTipsNode:
      raise RuntimeError('Failed to find papillary muscle tips node')

    minDistanceToMeanPoint = (np.inf, -1)
    for i in range(papillaryMuscleTipsNode.GetNumberOfControlPoints()):
      pos = np.zeros(3)
      papillaryMuscleTipsNode.GetNthControlPointPosition(i, pos)
      if np.linalg.norm(pos - meanRegionPoint) < minDistanceToMeanPoint[0]:
        minDistanceToMeanPoint = (np.linalg.norm(pos - meanRegionPoint), i)

    closestPapillatyMuscleTipPos = np.zeros(3)
    papillaryMuscleTipsNode.GetNthControlPointPosition(minDistanceToMeanPoint[1], closestPapillatyMuscleTipPos)

    # Get leaflet surface normals
    leafletModelNode = leafletNurbsSurfaceNode.GetOutputSurfaceModelNode()
    normalsFilter = vtk.vtkPolyDataNormals()
    normalsFilter.SetInputConnection(leafletModelNode.GetPolyDataConnection())
    normalsFilter.Update()
    normalsArray = slicer.util.arrayFromModelPointData(leafletModelNode, 'Normals')

    # Build locator for leaflet
    chordEndPointLocator = vtk.vtkPointLocator()
    chordEndPointLocator.SetDataSet(leafletModelNode.GetPolyData())

    # Create all chords and chord branches
    for endPointIndex, endPoint_World in enumerate(pointPositions):
      # Create line
      chordName = f'{baseName}-body{endPointIndex:02d}'
      line = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", chordName)
      self.setupChordLine(line, CHORD_COLORS[2])
      line.AddControlPointWorld(vtk.vtkVector3d(closestPapillatyMuscleTipPos), papillaryMuscleTipsNode.GetNthControlPointLabel(minDistanceToMeanPoint[1]))
      line.AddControlPointWorld(vtk.vtkVector3d(endPoint_World), chordName)
      # Put under subject hierarchy folder
      shNode.SetItemParent(shNode.GetItemByDataNode(line), regionFolderItem)

      # Create chord branching
      self.createRadialChordBranching(parameterNode, line, regionGridSurfaceNode, regionFolderItem, normalsArray, chordEndPointLocator)

    # Remove temporary nodes
    slicer.mrmlScene.RemoveNode(regionGridSurfaceNode)
    slicer.mrmlScene.RemoveNode(regionModelNode)

    return regionFolderItem

  def createRadialChordBranching(self, parameterNode, chordLineNode, regionGridSurfaceNode, regionFolderItem, leafletSurfaceNormalsArray, chordEndPointLocator):
    """
    Create radial branching at the valve end of a secondary (body) chord represented by given markups line node.

      P : papillary muscle endpoint
      |
     ...
      |
      │ chord line coming from papillary muscle tip
      │
      C : branching point
      │\
      │ \
      │  \
      │   \
      │    \
      │     \
      │  r   \
      A───────B : radial branch endpoint
       : central branch endpoint

    """
    if not chordLineNode or chordLineNode.GetNumberOfControlPoints() != 2:
      raise ValueError("Invalid chord line node")
    leafletNurbsNode = parameterNode.GetNodeReference("LeafletNURBSSurfaceForChordSnapping")
    if not leafletNurbsNode or leafletNurbsNode.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid leaflet NURBS node")
    if not regionFolderItem:
      raise ValueError("Invalid region folder item ID")

    bodyBranchLengthMm = float(parameterNode.GetParameter("BodyBranchLengthMm"))
    numberOfBodyRadialBranches = round(float(parameterNode.GetParameter("NumberOfBodyRadialBranches")))
    bodyBranchRadiusMm = float(parameterNode.GetParameter("BodyBranchRadiusMm"))

    # Get branching point on chord line
    pointP = np.zeros(3)
    chordLineNode.GetNthControlPointPositionWorld(0, pointP)
    pointA = np.zeros(3)
    chordLineNode.GetNthControlPointPositionWorld(1, pointA)
    vectorPA = pointA - pointP
    pointC = pointA - vectorPA / np.linalg.norm(vectorPA) * bodyBranchLengthMm
    # Change endpoint of the main chord line to only reach the branching point
    chordLineNode.SetNthControlPointPositionWorld(1, pointC)

    # Create folder for chord branch
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    branchesFolderItem = shNode.CreateFolderItem(shNode.GetSceneItemID(), f'{chordLineNode.GetName()} - branches')
    shNode.SetItemParent(branchesFolderItem, regionFolderItem)

    # Add central branch
    branchName = f'{chordLineNode.GetName()}-central'
    branchLine = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", branchName)
    self.setupChordLine(branchLine, CHORD_COLORS[3])
    branchLine.AddControlPointWorld(pointC)
    branchLine.AddControlPointWorld(pointA)
    # Put under subject hierarchy folder
    shNode.SetItemParent(shNode.GetItemByDataNode(branchLine), branchesFolderItem)

    # Get leaflet surface normal at the chord endpoint
    closestVertexIndex = chordEndPointLocator.FindClosestPoint(pointA)
    leafletSurfaceNormal = leafletSurfaceNormalsArray[closestVertexIndex]

    # Get perpendicular radius direction
    vectorRadiusX = np.cross(vectorPA / np.linalg.norm(vectorPA), leafletSurfaceNormal)
    vectorRadiusX = vectorRadiusX * bodyBranchRadiusMm / np.linalg.norm(vectorRadiusX)

    vectorRadiusY = np.cross(vectorRadiusX, leafletSurfaceNormal)
    vectorRadiusY = vectorRadiusY * bodyBranchRadiusMm / np.linalg.norm(vectorRadiusY)

    # Add chord branch lines
    angleIncrementRad = np.pi * 2 / numberOfBodyRadialBranches
    for branchIdx in range(numberOfBodyRadialBranches):
      # Get chord branch ideal endpoint
      angleRad = angleIncrementRad * branchIdx
      branchEndpointPos = pointA + np.sin(angleRad) * vectorRadiusX + np.cos(angleRad) * vectorRadiusY

      branchName = f'{chordLineNode.GetName()}-{branchIdx + 1}'
      branchLine = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", branchName)
      self.setupChordLine(branchLine, CHORD_COLORS[3])
      branchLine.AddControlPointWorld(pointC)
      branchLine.AddControlPointWorld(branchEndpointPos)
      # Put under subject hierarchy folder
      shNode.SetItemParent(shNode.GetItemByDataNode(branchLine), branchesFolderItem)

      # Snap ideal branch endpoint position to leaflet NURBS grid (use the region NURBS to make search faster)
      closestDistance2 = np.inf
      closestRegionGridPoint = np.zeros(3)
      regionGridPoint = np.zeros(3)
      for regionGridPointIdx in range(regionGridSurfaceNode.GetNumberOfControlPoints()):
        regionGridSurfaceNode.GetNthControlPointPositionWorld(regionGridPointIdx, regionGridPoint)
        currentDistance2 = vtk.vtkMath.Distance2BetweenPoints(regionGridPoint, branchEndpointPos)
        if currentDistance2 < closestDistance2 and vtk.vtkMath.Distance2BetweenPoints(regionGridPoint, pointC) > 1e-6:
          closestDistance2 = currentDistance2
          closestRegionGridPoint = regionGridPoint.copy()
      branchLine.SetNthControlPointPositionWorld(1, closestRegionGridPoint)

  def createChordsMesh(self, regionFolderItem):
    """Create mesh for chords and branches for a given region for spring import into FEBio."""
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()

    # Create chords mesh
    chordsMesh = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", f'Chords mesh - {shNode.GetItemName(regionFolderItem)}')
    shNode.SetItemParent(shNode.GetItemByDataNode(chordsMesh), shNode.GetItemParent(regionFolderItem))
    chordEndpoints = vtk.vtkPoints()
    chordLines = vtk.vtkCellArray()

    startPoint = np.zeros(3)
    endPoint = np.zeros(3)
    allChordsForRegion = slicer.util.getSubjectHierarchyItemChildren(regionFolderItem, True)
    for chordItem in allChordsForRegion:
      if shNode.GetItemLevel(chordItem) == slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder():
        continue  # Skip folders
      chordLine = shNode.GetItemDataNode(chordItem)
      if not chordLine.IsA('vtkMRMLMarkupsLineNode'):
        logging.warning(f'Unexpected node type found in chords region {shNode.GetItemName(regionFolderItem)}')
        continue

      chordLine.GetNthControlPointPosition(0, startPoint)
      chordLine.GetNthControlPointPosition(1, endPoint)
      startPointIndex = chordEndpoints.InsertNextPoint(startPoint)
      endPointIndex = chordEndpoints.InsertNextPoint(endPoint)

      lineIdList = vtk.vtkIdList()
      lineIdList.InsertNextId(startPointIndex)
      lineIdList.InsertNextId(endPointIndex)
      chordLines.InsertNextCell(lineIdList)

    chordsPolyData = vtk.vtkPolyData()
    chordsPolyData.SetPoints(chordEndpoints)
    chordsPolyData.SetLines(chordLines)
    chordsMesh.SetAndObservePolyData(chordsPolyData)

  def setupChordLine(self, chordLineNode, color):
    chordLineNode.SetLocked(True)  # it was left unlocked to allow the user to rearrange the points to achieve more uniform sampling, but with branching it is too complicated for manual modifications
    chordLineNode.CreateDefaultDisplayNodes()
    chordLineNode.GetDisplayNode().SetSelectedColor(color)
    chordLineNode.GetDisplayNode().SetPropertiesLabelVisibility(False)
    chordLineNode.GetDisplayNode().SetPointLabelsVisibility(False)
    chordLineNode.GetDisplayNode().SetGlyphTypeFromString("Sphere3D")
    chordLineNode.GetDisplayNode().UseGlyphScaleOff()
    chordLineNode.GetDisplayNode().SetGlyphSize(0.5)

  @staticmethod
  def fitTpsRectangleToClosedCurve(boundaryCurveNode, rectangleResolution=30, margin=1.2):
    """Requires boundaryCurveNode curve to be sampled uniformly"""
    # Prepare transform object

    # points on the warped boundary curve
    surfaceTransformTargetPoints = boundaryCurveNode.GetCurvePointsWorld()
    numberOfCurveLandmarkPoints = surfaceTransformTargetPoints.GetNumberOfPoints()

    # points on the unit disk
    surfaceTransformSourceCurvePoints = vtk.vtkPoints()
    surfaceTransformSourceCurvePoints.SetNumberOfPoints(numberOfCurveLandmarkPoints)
    angleIncrement = 2.0 * math.pi / float(numberOfCurveLandmarkPoints)
    for pointIndex in range(numberOfCurveLandmarkPoints):
      angle = float(pointIndex) * angleIncrement
      surfaceTransformSourceCurvePoints.SetPoint(pointIndex, math.cos(angle), math.sin(angle), 0)

    # Compute TPS transform
    surfaceTransform = vtk.vtkThinPlateSplineTransform()
    surfaceTransform.SetSourceLandmarks(surfaceTransformSourceCurvePoints)
    surfaceTransform.SetTargetLandmarks(surfaceTransformTargetPoints)

    # Warp a rectangular grid to the boundary curve
    surfaceUnitRectangle = vtk.vtkPlaneSource()
    surfaceUnitRectangle.SetXResolution(rectangleResolution)
    surfaceUnitRectangle.SetYResolution(rectangleResolution)
    radius = 1.0 + margin
    surfaceUnitRectangle.SetOrigin(-radius, -radius, 0)
    surfaceUnitRectangle.SetPoint1(-radius, radius, 0)
    surfaceUnitRectangle.SetPoint2(radius, -radius, 0)

    surfaceTransformFilter = vtk.vtkTransformPolyDataFilter()
    surfaceTransformFilter.SetTransform(surfaceTransform)
    surfaceTransformFilter.SetInputConnection(surfaceUnitRectangle.GetOutputPort())

    surfacePolyDataNormals = vtk.vtkPolyDataNormals()
    surfacePolyDataNormals.SetInputConnection(surfaceTransformFilter.GetOutputPort())
    surfacePolyDataNormals.ConsistencyOn()
    surfacePolyDataNormals.SplittingOff()
    surfacePolyDataNormals.Update()

    return surfacePolyDataNormals.GetOutput()

  @staticmethod
  def createTransformToWorldXYPlane(surfaceModelNode, xDirection=None):
    # Create transform node that transforms the surface model to the XY plane (in world coordinate system)
    medialSurfaceNodePoints = slicer.util.arrayFromModelPoints(surfaceModelNode)
    if surfaceModelNode.GetParentTransformNode():
      transformToWorld = slicer.util.arrayFromTransformMatrix(surfaceModelNode.GetParentTransformNode(), toWorld=True)
      # Concatenate a 4th line containing 1s so that we can transform the positions using a single matrix multiplication.
      medialSurfaceNodePointsHom = np.row_stack((medialSurfaceNodePoints.T, np.ones(medialSurfaceNodePoints.shape[0])))
      # Transform
      medialSurfaceNodePointsWorldHom = np.dot(transformToWorld, medialSurfaceNodePointsHom)
      # Save updated point positions
      medialSurfaceNodePoints = medialSurfaceNodePointsWorldHom[0:3, :].T

    [planePosition, planeNormal] = HeartValveLib.planeFit(medialSurfaceNodePoints.T)
    transformToPlane = HeartValveLib.getVtkTransformPlaneToWorld(planePosition, planeNormal, xDirection=xDirection)
    modelToXYPlaneTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode")
    modelToXYPlaneTransformNode.SetAndObserveTransformFromParent(transformToPlane)
    return modelToXYPlaneTransformNode

  @staticmethod
  def transformPolydata(polydata, transform):
    transformFilter = vtk.vtkTransformPolyDataFilter()
    transformFilter.SetTransform(transform)
    transformFilter.SetInputData(polydata)
    transformFilter.Update()
    return transformFilter.GetOutput()

  @staticmethod
  def fitNurbsSurfaceToModel(medialSurfaceNodeInput, boundaryCurveNodeInput,
                           size_u = 8, size_v = 8, degree_u = 2, degree_v = 2, resolution=0.05,
                           trim_curve=None, xDirection=None):

    # Remove all parent transforms to simplify further steps
    medialSurfaceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "_tmp_MedialSurface")
    medialSurfaceNode.CopyContent(medialSurfaceNodeInput)
    medialSurfaceNode.SetAndObserveTransformNodeID(medialSurfaceNodeInput.GetTransformNodeID())
    medialSurfaceNode.HardenTransform()
    boundaryCurveNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsClosedCurveNode", "_tmp_BoundaryCurve")
    boundaryCurveNode.CopyContent(boundaryCurveNodeInput)
    # shortestDistanceSurface node reference is needed if curve is set to use shortest distance on surface mode
    # but that is not included in node content (as of 2021-01-23)
    boundaryCurveNode.SetNodeReferenceID("shortestDistanceSurface", boundaryCurveNodeInput.GetNodeReferenceID("shortestDistanceSurface"))
    boundaryCurveNode.SetAndObserveTransformNodeID(boundaryCurveNodeInput.GetTransformNodeID())
    boundaryCurveNode.HardenTransform()

    # Prepare transform object
    numberOfCurveLandmarkPoints = 30
    curveLengthMm = boundaryCurveNode.GetCurveLengthWorld()
    # subtract a little bit (0.1 = 10th of a sampling distance) to make sure we don't go over the curve length
    # because we could then get one less sample point
    samplingDistance = curveLengthMm / (numberOfCurveLandmarkPoints - 0.1)
    boundaryCurveNode.ResampleCurveWorld(samplingDistance)
    boundaryCurveNode.SetNumberOfPointsPerInterpolatingSegment(3)
    boundaryCurveNode.SetCurveTypeToCardinalSpline()  # make sure the curve is not constrained anymore
    if boundaryCurveNode.GetCurvePointsWorld().GetNumberOfPoints() == 0:
      raise ValueError("Invalid boundary curve")

    import time
    eventTimes = []
    eventTimes.append(('get inputs', time.time()))

    # Transform medial surface to XY plane for easier computation
    leafletToXYPlaneTransformNode = ValveFemExportLogic.createTransformToWorldXYPlane(medialSurfaceNode, xDirection=xDirection)

    medialSurfaceNode.SetAndObserveTransformNodeID(leafletToXYPlaneTransformNode.GetID())
    medialSurfaceNode.HardenTransform()

    warpedRectanglePolyData = ValveFemExportLogic.fitTpsRectangleToClosedCurve(boundaryCurveNode)
    warpedRectangleModelNode = slicer.modules.models.logic().AddModel(warpedRectanglePolyData)
    warpedRectangleModelNode.SetName(f"{medialSurfaceNodeInput.GetName()}-tps-fit")
    warpedRectangleModelNode.SetAndObserveTransformNodeID(leafletToXYPlaneTransformNode.GetID())
    warpedRectangleModelNode.HardenTransform()

    boundaryCurveNode.SetAndObserveTransformNodeID(leafletToXYPlaneTransformNode.GetID())
    boundaryCurveNode.HardenTransform()

    # Create points array that the NURBS will fit to by cutting the leaflet with XZ planes
    bounds = np.zeros(6)
    medialSurfaceNode.GetBounds(bounds)
    # we will make the NURBS rectangular control point grid a bit bigger than the input surface
    # to avoid artifacts on the boundary
    margin = (bounds[1]-bounds[0]) * 0.10

    medialSurfaceLocalizer = vtk.vtkModifiedBSPTree()
    medialSurfaceLocalizer.SetDataSet(medialSurfaceNode.GetPolyData())
    medialSurfaceLocalizer.BuildLocator()

    tri = vtk.vtkTriangleFilter()
    tri.SetInputData(warpedRectangleModelNode.GetPolyData())
    tri.Update()

    warpedSurfaceLocalizer = vtk.vtkModifiedBSPTree()
    warpedSurfaceLocalizer.SetDataSet(tri.GetOutput())
    warpedSurfaceLocalizer.BuildLocator()

    warpedSurfaceClosestPointLocalizer = vtk.vtkCellLocator()
    warpedSurfaceClosestPointLocalizer.SetDataSet(tri.GetOutput())
    warpedSurfaceClosestPointLocalizer.BuildLocator()

    eventTimes.append(('get surface control points', time.time()))
    points = []
    intersectionPoints = vtk.vtkPoints()
    intersectionCellIds = vtk.vtkIdList()
    for vindex in range(size_v):
      for uindex in range(size_u):
        intersectingLineStart = [
          bounds[0]-margin+(bounds[1]-bounds[0]+2*margin)*uindex/(size_u-1),
          bounds[2]-margin+(bounds[3]-bounds[2]+2*margin)*vindex/(size_v-1),
          bounds[5]+margin]
        intersectingLineEnd = [
          intersectingLineStart[0],
          intersectingLineStart[1],
          bounds[4]-margin]
        intersectionPoints.Reset()
        medialSurfaceLocalizer.IntersectWithLine(intersectingLineStart, intersectingLineEnd, 0.0, intersectionPoints, intersectionCellIds)
        if intersectionPoints.GetNumberOfPoints() > 0:
          closestPoint = intersectionPoints.GetPoint(0)
        else:
            # no intersection point, take it from the warped rectangular surface
            intersectionPoints.Reset()
            warpedSurfaceLocalizer.IntersectWithLine(intersectingLineStart, intersectingLineEnd, 0.0, intersectionPoints, intersectionCellIds)
            if intersectionPoints.GetNumberOfPoints() > 0:
              closestPoint = intersectionPoints.GetPoint(0)
            else:
              closestPoint = np.array([0.0, 0.0, 0.0])
              cellObj = vtk.vtkGenericCell()
              cellId = vtk.mutable(0)
              subId = vtk.mutable(0)
              dist2 = vtk.mutable(0.0)
              targetLocation = [intersectingLineStart[0], intersectingLineStart[1], 0]
              warpedSurfaceClosestPointLocalizer.FindClosestPoint(targetLocation, closestPoint, cellObj, cellId, subId, dist2)

        points.append(closestPoint)

    points = np.array(points)

    # Do global surface interpolation
    eventTimes.append(('interpolate surface', time.time()))
    from geomdl import fitting, tessellate
    from geomdl import exchange_vtk
    surf = fitting.interpolate_surface(points, size_u, size_v, degree_u, degree_v)

    # Plot the interpolated surface
    surf.delta = resolution

    eventTimes.append(('export to vtk', time.time()))
    tempDir = slicer.app.temporaryPath
    timestampStr = qt.QDateTime().currentDateTime().toString("yyyy-MM-dd_hh+mm+ss.zzz")
    tempSurfaceFilePath =  f"{tempDir}/_tessellate_{timestampStr}.vtk"
    exchange_vtk.export_polydata(surf, tempSurfaceFilePath, tessellate=True)
    # Write the NURBS grid:
    #exchange_vtk.export_polydata(surf, "surf.vtk", point_type="ctrlpts", tessellate=False)

    tessellatedModelNode = slicer.util.loadNodeFromFile(tempSurfaceFilePath, 'ModelFile', {"coordinateSystem": "RAS"})
    tessellatedModelNode.SetName(medialSurfaceNodeInput.GetName()+'-fit')
    tessellatedModelNode.GetPolyData().SetVerts(None)  # presence of vertices would prevent most processing opeprations

    os.remove(tempSurfaceFilePath)

    if trim_curve:
      # Get trim points
      eventTimes.append(('get trim points', time.time()))
      trimModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLDynamicModelerNode")
      trimModel.SetToolName("Curve cut")
      trimModel.SetNodeReferenceID("CurveCut.InputModel", tessellatedModelNode.GetID())
      trimModel.SetNodeReferenceID("CurveCut.InputCurve", boundaryCurveNode.GetID())
      trimModel.SetNodeReferenceID("CurveCut.OutputInside", tessellatedModelNode.GetID())
      trimModelTool = slicer.vtkSlicerDynamicModelerCurveCutTool()
      trimModelTool.Run(trimModel)
      slicer.mrmlScene.RemoveNode(trimModel)

    mesh = tessellatedModelNode.GetPolyData()

    smoothing = False
    cleaning = True
    normals = True

    # Smooth
    if smoothing:
      eventTimes.append(('smoothing', time.time()))
      smoothFilter = vtk.vtkSmoothPolyDataFilter()
      smoothFilter.SetInputData(0, mesh)
      smoothFilter.SetInputData(1, mesh)  # constrain smoothed points to the surface
      smoothFilter.SetNumberOfIterations(1000)
      smoothFilter.SetRelaxationFactor(0.5)
      smoothFilter.Update()
      mesh = smoothFilter.GetOutput()

    # Merge points
    if cleaning:
      eventTimes.append(('cleaning', time.time()))
      cleaner = vtk.vtkCleanPolyData()
      cleaner.SetInputData(mesh)
      # Tolerance=0.01 removes ill-shaped triangles without removing significant details
      cleaner.SetTolerance(0.005)
      cleaner.Update()
      mesh = cleaner.GetOutput()
      # Cleaner collapses small triangles to lines, now remove the lines
      mesh.SetLines(None)

    # Compute normals
    if normals:
      eventTimes.append(('normals', time.time()))
      computeNormals = vtk.vtkPolyDataNormals()
      computeNormals.SetInputData(mesh)
      computeNormals.SplittingOff()  # duplicate points would confuse the FEM solver
      computeNormals.AutoOrientNormalsOff()  # it only guaranteed to work for closed surfaces
      computeNormals.ConsistencyOn()
      computeNormals.Update()
      mesh = computeNormals.GetOutput()

    tessellatedModelNode.SetAndObservePolyData(mesh)

    # Transform back results to original position
    leafletToXYPlaneTransformNode.Inverse()
    tessellatedModelNode.SetAndObserveTransformNodeID(leafletToXYPlaneTransformNode.GetID())
    tessellatedModelNode.HardenTransform()

    # Put results under the same transform as input medialSurfaceNode (keeping their current position)
    medialSurfaceTransformNode = medialSurfaceNodeInput.GetParentTransformNode()
    if medialSurfaceTransformNode:
      transformWorldToMedialSurface = vtk.vtkGeneralTransform()
      medialSurfaceTransformNode.GetTransformFromWorld(transformWorldToMedialSurface)
      for modelNode in [tessellatedModelNode, warpedRectangleModelNode]:
        modelNode.SetAndObservePolyData(
          ValveFemExportLogic.transformPolydata(modelNode.GetPolyData(), transformWorldToMedialSurface))
        modelNode.SetAndObserveTransformNodeID(medialSurfaceTransformNode.GetID())

    tessellatedModelNode.GetDisplayNode().EdgeVisibilityOn()

    # Remove temporary nodes
    slicer.mrmlScene.RemoveNode(leafletToXYPlaneTransformNode)
    # Set debug=True for debugging (it will leave behind the temporary nodes for inspection)
    debug = False
    if not debug:
      slicer.mrmlScene.RemoveNode(medialSurfaceNode)
      slicer.mrmlScene.RemoveNode(boundaryCurveNode)
      slicer.mrmlScene.RemoveNode(warpedRectangleModelNode)

    # Print processing times
    eventTimes.append(('end', time.time()))
    print("--------")
    lastLabel=None
    lastTimestamp=None
    for label, timestamp in eventTimes:
        if lastLabel is not None:
            print(f"{lastLabel}: {timestamp-lastTimestamp}")
        lastLabel = label
        lastTimestamp = timestamp

    return tessellatedModelNode

  def createLeafletSurfaces(self, parameterNode, leafletsFolderItemId, logCallback=None):
    # Install geomdl - NURBS modeling package
    try:
      import geomdl
    except:
      slicer.util.pip_install('geomdl')

    xDirection = [0,1,0]
    trim_curve = True
    controlPoints = int(float(parameterNode.GetParameter("LeafletSurfaceNurbsResolution")))
    triangulationResolution = 1.0/float(parameterNode.GetParameter("LeafletSurfaceMeshResolution")) # 0.5 * 1.0/controlPoints

    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()

    leafletSurfaceModels = []
    for leafletIndex in range(3):
      leafletModelNode = parameterNode.GetNodeReference("LeafletModel" + str(leafletIndex + 1))
      leafletBoundaryMarkupNode = parameterNode.GetNodeReference("LeafletBoundaryMarkups" + str(leafletIndex + 1))
      if not leafletModelNode or not leafletBoundaryMarkupNode:
        continue

      if logCallback:
        logCallback(f"Creating leaflet surface for {leafletModelNode.GetName()}...")

      # If curve specified by fiducial lists then convert it now to a curve
      if leafletBoundaryMarkupNode.IsA('vtkMRMLMarkupsFiducialNode'):
        tempCurveNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsClosedCurveNode', 'tmp_ValveFemExportCreateLeafletSurface')
        pts = vtk.vtkPoints()
        leafletBoundaryMarkupNode.GetControlPointPositionsWorld(pts)
        tempCurveNode.SetControlPointPositionsWorld(pts)
        leafletBoundaryMarkupNode = tempCurveNode
      else:
        tempCurveNode = None

      nurbsModelNode = ValveFemExportLogic.fitNurbsSurfaceToModel(leafletModelNode, leafletBoundaryMarkupNode,
        size_u=controlPoints, size_v=controlPoints,
        resolution=triangulationResolution, xDirection=xDirection, trim_curve=trim_curve)
      nurbsModelNode.CreateDefaultDisplayNodes()
      nurbsModelNode.GetDisplayNode().SetColor(leafletModelNode.GetDisplayNode().GetColor())

      if tempCurveNode:
        slicer.mrmlScene.RemoveNode(tempCurveNode)
      shNode.SetItemParent(shNode.GetItemByDataNode(nurbsModelNode), leafletsFolderItemId)
      leafletSurfaceModels.append(nurbsModelNode)

    return leafletSurfaceModels

  def copyNode(self, node, folderItemId):
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    dataNodeClone = slicer.mrmlScene.AddNewNodeByClass(node.GetClassName())
    dataNodeClone.CopyContent(node)
    dataNodeClone.SetName(node.GetName())
    dataNodeClone.CreateDefaultDisplayNodes()
    displayNodeClone = dataNodeClone.GetDisplayNode()
    displayNodeClone.CopyContent(node.GetDisplayNode())
    if node.GetParentTransformNode():
      dataNodeClone.SetAndObserveTransformNodeID(node.GetParentTransformNode().GetID())
    shNode.SetItemParent(shNode.GetItemByDataNode(dataNodeClone), folderItemId)
    return dataNodeClone

  def copyAnnulusModels(self, parameterNode, leafletsFolderItemId):
    for referenceRole in ["AnnulusCurve", "AnnulusModel"]:
      node = parameterNode.GetNodeReference(referenceRole)
      if not node:
        continue
      self.copyNode(node, leafletsFolderItemId)

  def copyLeafletSurfaces(self, parameterNode, leafletsFolderItemId):
    """Instead of creating leaflet shell models, just copy the currentle selected leaflet model nodes to the output folder"""
    leafletSurfaceModels = []
    for referenceRole in ["LeafletModel1", "LeafletModel2", "LeafletModel3"]:
      node = parameterNode.GetNodeReference(referenceRole)
      if not node:
        continue
      leafletSurfaceModels.append(self.copyNode(node, leafletsFolderItemId))
    return leafletSurfaceModels

  def saveNode(self, node, outputFolder, expectedTransformNode, enableTransformChange, ignoreMarkups=True):
    filename = node.GetName().replace(" ", "_")

    if node.IsA("vtkMRMLTableNode"):
      # Table is a special case for several reasons, so we write it here
      originalToExpectedTransform = vtk.vtkGeneralTransform()
      slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(None, expectedTransformNode, originalToExpectedTransform)
      table = node.GetTable()
      chordIndexArray = table.GetColumnByName("Index")
      chordStartPositionArray = table.GetColumnByName("StartPosition")
      chordEndPositionArray = table.GetColumnByName("EndPosition")
      chordNameArray = table.GetColumnByName("Name")
      # Write to file
      filename += ".csv"
      logging.info("Saving node "+filename)
      fout = open(outputFolder+"/"+filename, "w")
      for rowIndex in range(table.GetNumberOfRows()):
        startPosition = originalToExpectedTransform.TransformPoint(chordStartPositionArray.GetTuple3(rowIndex))
        endPosition = originalToExpectedTransform.TransformPoint(chordEndPositionArray.GetTuple3(rowIndex))
        fout.write(f"{chordIndexArray.GetValue(rowIndex)}")
        fout.write(f",{-startPosition[0]},{-startPosition[1]},{startPosition[2]}")
        fout.write(f",{-endPosition[0]},{-endPosition[1]},{endPosition[2]}")
        fout.write(f",{chordNameArray.GetValue(rowIndex)}\n")
      fout.close()
      return

    # Ensure that the node is under the expected transform node
    originalTransformNode = node.GetParentTransformNode()
    if originalTransformNode != expectedTransformNode:
      if enableTransformChange:
        # Transform node to be in the expected coordinate system
        originalToExpectedTransform = vtk.vtkGeneralTransform()
        slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(originalTransformNode, expectedTransformNode, originalToExpectedTransform)
        node.ApplyTransform(originalToExpectedTransform)
        node.SetAndObserveTransformNodeID(expectedTransformNode.GetID() if expectedTransformNode else None)
      else:
        # We are not allowed to change the coordinate system of the node, return with failure
        raise("Node {0} cannot be saved due to unexpected transform node".format(node.GetName()))

    # Save using a temporary storage node to ensure that saving path, format, etc. is kept unchanged
    if node.IsA("vtkMRMLModelNode"):
      if not self.modelStorageNode:
        self.modelStorageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelStorageNode")
      storageNode =  self.modelStorageNode
      storageNode.SetUseCompression(False)
      extension = ".vtk"
    elif node.IsA("vtkMRMLMarkupsNode"):
      if ignoreMarkups:
        return
      if not self.markupsStorageNode:
        self.markupsStorageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsJsonStorageNode")
      storageNode = self.markupsStorageNode
      extension = ".mrk.json"
    else:
      raise RuntimeError("Failed to save node: unsupported type of node " + node.GetName())

    filename += extension
    logging.info("Saving node "+filename)
    storageNode.SetFileName(outputFolder+"/"+filename)
    storageNode.SetCoordinateSystem(slicer.vtkMRMLStorageNode.CoordinateSystemLPS)
    if not storageNode.WriteData(node):
      raise RuntimeError("Failed to save node: " + node.GetName())

  def deleteTemporaryStorageNodes(self):
    if self.modelStorageNode:
      slicer.mrmlScene.RemoveNode(self.modelStorageNode)
      self.modelStorageNode = None
    if self.markupsStorageNode:
      slicer.mrmlScene.RemoveNode(self.markupsStorageNode)
      self.markupsStorageNode = None

  def exportModel(self, parameterNode, shFolderItemId, outputFolder, commonParentTransformNode=None, logCallback=None):
    if not shFolderItemId:
      raise ValueError("Subject hierarchy folder does not exist. Make sure the outputs are correctly generated.")

    slicer.app.pauseRender()
    try:
      os.makedirs(outputFolder, exist_ok=True)

      shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
      if shFolderItemId is None:
        shFolderItemId = shNode.GetItemByDataNode(parameterNode)
      if logCallback:
        logCallback(f"Writing {shNode.GetItemName(shFolderItemId)}...")

      # Write all children of this item (recursively)
      childIds = vtk.vtkIdList()
      shNode.GetItemChildren(shFolderItemId, childIds)
      for itemIdIndex in range(childIds.GetNumberOfIds()):
        shItemId = childIds.GetId(itemIdIndex)
        dataNode = shNode.GetItemDataNode(shItemId)
        if dataNode and dataNode.GetClassName() != "vtkMRMLFolderDisplayNode":
          self.saveNode(dataNode, outputFolder, commonParentTransformNode, enableTransformChange=True)
          slicer.app.processEvents()
        # Write all children of this child item
        grandChildIds = vtk.vtkIdList()
        shNode.GetItemChildren(shItemId, grandChildIds)
        if grandChildIds.GetNumberOfIds() > 0:
          self.exportModel(parameterNode, shItemId, outputFolder, commonParentTransformNode, logCallback)

      self.deleteTemporaryStorageNodes()

    finally:
      slicer.app.resumeRender()

  def createDenseNURBSSurface(self, parameterNode):
    """
    Generate dense NURBS surface from the interpolated vertices of the input NURBS surface.
    This is a workaround so that the logic does not need to be reimplemented from scratch, but
    the chords can snap onto the dense surface.
    """
    leafletNurbsSurfaceNode = parameterNode.GetNodeReference("LeafletNURBSSurface")
    if not leafletNurbsSurfaceNode or leafletNurbsSurfaceNode.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid leaflet NURBS grid surface node")
    leafletModelNode = leafletNurbsSurfaceNode.GetOutputSurfaceModelNode()
    if not leafletModelNode:
      raise ValueError("Model node is not set for the leaflet NURBS grid surface node")

    # Get interpolated surface model resolution.
    # The vertex indices on the surface model increase in the V direction first, then in the U direction
    # (which is the opposite of the NURBS grid control points).
    surfaceRes = self.getSurfaceResolution(parameterNode)

    # Generate dense grid points
    denseGridPoints = vtk.vtkPoints()
    for v in range(surfaceRes[1]):
      for u in range(surfaceRes[0]):  # Along wrapped direction
        currentPoint = leafletModelNode.GetPolyData().GetPoint(u * surfaceRes[1] + v)
        denseGridPoints.InsertNextPoint(currentPoint)

    # Create dense grid surface node
    denseGridSurfaceNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsGridSurfaceNode', f'{leafletNurbsSurfaceNode.GetName()} Dense Temp')
    denseGridSurfaceNode.SetGridResolution(surfaceRes)
    denseGridSurfaceNode.SetSamplingResolution(2)  #TODO: Crashes with 1 (empty evaluated surface when finding wrapping lin space)
    denseGridSurfaceNode.SetWrapAround(slicer.vtkMRMLMarkupsGridSurfaceNode.AlongU)
    # denseGridSurfaceNode.SetDisplayVisibility(False)
    denseGridSurfaceNode.SetControlPointPositionsWorld(denseGridPoints)
    parameterNode.SetNodeReferenceID("LeafletNURBSSurfaceForChordSnapping", denseGridSurfaceNode.GetID())
    # Create dense grid model node to be able to get the surface normals
    denseModelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', f'{denseGridSurfaceNode.GetName()} Model')
    denseGridSurfaceNode.SetOutputSurfaceModelNodeID(denseModelNode.GetID())

    return denseGridSurfaceNode

#
# ValveFemExportTest
#

class ValveFemExportTest(ScriptedLoadableModuleTest):
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
    self.test_ValveFemExport1()

  def test_ValveFemExport1(self):
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
    inputVolume = SampleData.downloadFromURL(
      nodeNames='MRHead',
      fileNames='MR-Head.nrrd',
      uris='https://github.com/Slicer/SlicerTestingData/releases/download/MD5/39b01631b7b38232a220007230624c8e',
      checksums='MD5:39b01631b7b38232a220007230624c8e')[0]
    self.delayDisplay('Finished with download and loading')

    inputScalarRange = inputVolume.GetImageData().GetScalarRange()
    self.assertEqual(inputScalarRange[0], 0)
    self.assertEqual(inputScalarRange[1], 279)

    outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
    threshold = 50

    # Test the module logic

    logic = ValveFemExportLogic()

    # Test algorithm with non-inverted threshold
    logic.run(inputVolume, outputVolume, threshold, True)
    outputScalarRange = outputVolume.GetImageData().GetScalarRange()
    self.assertEqual(outputScalarRange[0], inputScalarRange[0])
    self.assertEqual(outputScalarRange[1], threshold)

    # Test algorithm with inverted threshold
    logic.run(inputVolume, outputVolume, threshold, False)
    outputScalarRange = outputVolume.GetImageData().GetScalarRange()
    self.assertEqual(outputScalarRange[0], inputScalarRange[0])
    self.assertEqual(outputScalarRange[1], inputScalarRange[1])

    self.delayDisplay('Test passed')
