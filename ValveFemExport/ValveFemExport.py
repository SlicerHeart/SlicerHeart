import os
import unittest
import logging
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import numpy as np

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
    self.parent.contributors = ["Andras Lasso (PerkLab)", "Matthew A Jolley (CHOP)"]
    self.parent.helpText = """
Export leaflets and chords for FEM analysis.
Usage:
<ul>
<li>Load scene that contains leaflet segmentation</li>
<li>If a HeartValve is loaded into the scene then click "Import" to automatically populate inputs</li>
<li>Mark Papillary muscle tips on the image</li>
<li>For leaflet 1: create margin curve and draw that curve at the leaflet margin</li>
<li>For leaflet 1: create secondary curve and draw that curve a bit farther from the leaflet margin</li>
<li>For leaflet 2: margin curve that was defined for leaflet 1 can be selected</li>
<li>For leaflet 2: create secondary curve and draw that curve a bit farther from the leaflet margin</li>
<li>Click "Create chords"</li>
<li>Select output folder</li>
<li>Click Export</li>
</ul>
"""
    self.parent.acknowledgementText = """
This file was originally developed by Andras Lasso, PerkLab.
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
      (self.ui.secondaryCurveNodeComboBox3, "SecondaryCurve3")
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
      #curvePlaceWidget.buttonsVisible = False
      #curvePlaceWidget.colorButton().show()
      #curvePlaceWidget.placeButton().show()
      #curvePlaceWidget.deleteButton().show()

    # Connections
    self.ui.parameterNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.setParameterNode)
    self.ui.heartValveImportButton.connect('clicked(bool)', self.onHeartValveImport)
    self.ui.addLeafletRegionBoundaryButton.connect('clicked(bool)', self.onAddLeafletRegionBoundary)
    self.ui.deleteLeafletRegionBoundaryButton.connect('clicked(bool)', self.onDeleteLeafletRegionBoundary)

    self.ui.leafletRegionBoundaryTreeView.connect("currentItemChanged(vtkIdType)", self.onLeafletRegionBoundarySelected)
    self.ui.generateButton.connect('clicked(bool)', self.onGenerate)
    self.ui.exportButton.connect('clicked(bool)', self.onExport)
    slicer.util.addParameterEditWidgetConnections(self.parameterEditWidgets, self.updateParameterNodeFromGUI)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    for nodeSelector, nodeReferenceRole in self.nodeSelectors:
      nodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)

    self.ui.leafletSurfaceModelNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.updateParameterNodeFromGUI)
    self.ui.papillaryMuscleTipPointComboBox.connect('currentTextChanged(QString)', self.updateParameterNodeFromGUI)

    # Initial GUI update
    self.updateGUIFromParameterNode()

  def cleanup(self):
    """
    Called when the application closes and the module widget is destroyed.
    """
    self.removeObservers()

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
      #markupsSelector.setStyleSheet("ctkCollapsibleGroupBox {{ background: rgb({0}, {1}, {2}); }}".format(r, g, b))
      #markupsSelector.setStyleSheet("qMRMLNodeComboBox {{ background: rgb({0}, {1}, {2}); }}".format(r, g, b))

    # # Update buttons states and tooltips
    # if self._parameterNode.GetNodeReference("InputVolume") and self._parameterNode.GetNodeReference("OutputVolume"):
    #   self.ui.applyButton.toolTip = "Compute output volume"
    #   self.ui.applyButton.enabled = True
    # else:
    #   self.ui.applyButton.toolTip = "Select input and output volume nodes"
    #   self.ui.applyButton.enabled = False

    leafletRegionsFolderId = self.logic.getSubjectHierarchyLeafletRegionsSubfolder(self._parameterNode)
    self.ui.leafletRegionBoundaryTreeView.setRootItem(leafletRegionsFolderId)
    self.ui.leafletRegionBoundaryTreeView.visible = bool(leafletRegionsFolderId)

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    leafletRegionBoundaryNode = shNode.GetItemDataNode(self.ui.leafletRegionBoundaryTreeView.currentItem())
    if leafletRegionBoundaryNode:
      wasBlocked = self.ui.leafletSurfaceModelNodeSelector.blockSignals(True)
      self.ui.leafletSurfaceModelNodeSelector.setCurrentNode(leafletRegionBoundaryNode.GetNodeReference("LeafletSurfaceModel"))
      self.ui.leafletSurfaceModelNodeSelector.blockSignals(wasBlocked)
      wasBlocked = self.ui.papillaryMuscleTipPointComboBox.blockSignals(True)
      self.ui.papillaryMuscleTipPointComboBox.currentText = leafletRegionBoundaryNode.GetAttribute("PapillaryMuscleTipPoint")
      self.ui.papillaryMuscleTipPointComboBox.blockSignals(wasBlocked)

    slicer.util.updateParameterEditWidgetsFromNode(self.parameterEditWidgets, self._parameterNode)

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

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
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

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    leafletRegionBoundaryNode = shNode.GetItemDataNode(self.ui.leafletRegionBoundaryTreeView.currentItem())
    if leafletRegionBoundaryNode:
      leafletRegionBoundaryNode.SetNodeReferenceID("LeafletSurfaceModel", self.ui.leafletSurfaceModelNodeSelector.currentNodeID)
      leafletRegionBoundaryNode.SetCurveTypeToShortestDistanceOnSurface(self.ui.leafletSurfaceModelNodeSelector.currentNode())
      leafletRegionBoundaryNode.SetAttribute("PapillaryMuscleTipPoint", self.ui.papillaryMuscleTipPointComboBox.currentText)

    slicer.util.updateNodeFromParameterEditWidgets(self.parameterEditWidgets, self._parameterNode)

    self._parameterNode.EndModify(wasModified)

  def onHeartValveImport(self):
    heartValveNode = self._parameterNode.GetNodeReference("HeartValve")
    import HeartValveLib
    valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)
    wasModified = self._parameterNode.StartModify()

    self._parameterNode.SetNodeReferenceID("AnnulusCurve", valveModel.getAnnulusContourMarkupNode().GetID())
    self._parameterNode.SetNodeReferenceID("AnnulusModel", valveModel.getAnnulusContourModelNode().GetID())

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
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
    nodeName = slicer.mrmlScene.GetUniqueNameByString("region")
    leafletRegionBoundaryNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsClosedCurveNode", nodeName)
    leafletRegionBoundaryNode.CreateDefaultDisplayNodes()
    displayNode = leafletRegionBoundaryNode.GetDisplayNode()
    displayNode.SetPointLabelsVisibility(False)
    displayNode.SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeToVisibleSurface)
    displayNode.SetGlyphTypeFromString("Sphere3D")
    displayNode.SetSelectedColor(1, 0.2, 0.7)
    displayNode.SetLineThickness(0.3)
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    newLeafletRegionBoundaryItem = shNode.GetItemByDataNode(leafletRegionBoundaryNode)
    leafletRegionsFolderItem = self.logic.getSubjectHierarchyLeafletRegionsSubfolder(self._parameterNode, createIfNeeded=True)
    shNode.SetItemParent(newLeafletRegionBoundaryItem, leafletRegionsFolderItem)
    self.ui.leafletRegionBoundaryTreeView.setCurrentItem(newLeafletRegionBoundaryItem)
    self.ui.leafletRegionBoundaryPlaceWidget.setPlaceModeEnabled(True)
    self.updateGUIFromParameterNode()

  def onDeleteLeafletRegionBoundary(self):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    leafletRegionBoundaryNode = shNode.GetItemDataNode(self.ui.leafletRegionBoundaryTreeView.currentItem())
    slicer.mrmlScene.RemoveNode(leafletRegionBoundaryNode)

  def onLeafletRegionBoundarySelected(self, shItemId):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
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
        parameterNode.SetParameter("ChordsPerCm2", "17")

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    if parameterNode.GetHideFromEditors():
      parameterNode.SetHideFromEditors(False)
      shNode.RequestOwnerPluginSearch(parameterNode)
      shNode.SetItemAttribute(shNode.GetItemByDataNode(parameterNode), "ModuleName", "ValveFEMExport")

  def createChordTable(self, baseName, chordsFolderItemId):
    # Create table node for spring import into FEBio
    chordTableNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTableNode')
    chordTableNode.SetName(baseName)
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    shNode.SetItemParent(shNode.GetItemByDataNode(chordTableNode), chordsFolderItemId)
    chordIndexArray = vtk.vtkIntArray()
    chordIndexArray.SetName("Index")
    chordTableNode.AddColumn(chordIndexArray)
    chordStartPositionArray = vtk.vtkDoubleArray()
    chordStartPositionArray.SetName("StartPosition")
    chordStartPositionArray.SetNumberOfComponents(3)
    chordStartPositionArray.SetComponentName(0, "X")
    chordStartPositionArray.SetComponentName(1, "Y")
    chordStartPositionArray.SetComponentName(2, "Z")
    chordTableNode.AddColumn(chordStartPositionArray)
    chordEndPositionArray = vtk.vtkDoubleArray()
    chordEndPositionArray.SetName("EndPosition")
    chordEndPositionArray.SetNumberOfComponents(3)
    chordEndPositionArray.SetComponentName(0, "X")
    chordEndPositionArray.SetComponentName(1, "Y")
    chordEndPositionArray.SetComponentName(2, "Z")
    chordTableNode.AddColumn(chordEndPositionArray)
    chordNameArray = vtk.vtkStringArray()
    chordNameArray.SetName("Name")
    chordTableNode.AddColumn(chordNameArray)
    return chordTableNode, chordIndexArray, chordNameArray, chordStartPositionArray, chordEndPositionArray

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
    chordTableNode, chordIndexArray, chordNameArray, chordStartPositionArray, chordEndPositionArray = self.createChordTable(baseName, chordsFolderItemId)

    for endPointIndex in range(endPoints.GetNumberOfControlPoints()):
        endPoint_World = [0,0,0]
        endPoints.GetNthControlPointPositionWorld(endPointIndex, endPoint_World)
        # Snap to closest mesh point (FEM solver requires constraint to be assigned to a point, not anywhere on the surface)
        closestMeshPointIndex = pointLocator.FindClosestPoint(endPoint_World)
        endPoint_World = surface_World.GetPoint(closestMeshPointIndex)
        # Find closest start point
        closestStartPointDistance2 = 1e10
        closestStartPoint_World = [0.0,0.0,0.0]
        closestStartPointName = ""
        for startPointIndex in range(startPoints.GetNumberOfControlPoints()):
            startPoint_World = [0,0,0]
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
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    parameterNodeItemId = shNode.GetItemByDataNode(parameterNode)
    outputFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, self.outputSubjectHierarchyFolderName)
    if outputFolderItemId:
      shNode.RemoveItemChildren(outputFolderItemId)

  def getSubjectHierarchyOutputFolder(self, parameterNode):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    parameterNodeItemId = shNode.GetItemByDataNode(parameterNode)
    outputFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, self.outputSubjectHierarchyFolderName)
    return outputFolderItemId

  def getSubjectHierarchyLeafletRegionsSubfolder(self, parameterNode, createIfNeeded=False):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    # Get/create output folder
    parameterNodeItemId = shNode.GetItemByDataNode(parameterNode)
    leafletRegionsFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, "Leaflet regions")
    if not leafletRegionsFolderItemId and createIfNeeded:
      leafletRegionsFolderItemId = shNode.CreateFolderItem(parameterNodeItemId, "Leaflet regions")
    return leafletRegionsFolderItemId

  def createSubjectHierarchyOutputSubfolder(self, parameterNode, subfolderName):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
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
    colors = [[1.0,0.3,0.3], [1.0,0.6,0.6], [0.3,1.0,0.3], [0.8,1.0,0.8], [0.3,0.3,1], [0.8,0.8,1.0]]
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
          self.createChordBundle(leafletSurfaceModel.GetName()+'-primary', colors[bundleIndex*2],
            papillaryMuscleTips, leafletMarginCurve, leafletSurfaceModel, chordsFolderItemId)
        if leafletSecondaryCurve:
          self.createChordBundle(leafletSurfaceModel.GetName()+'-secondary', colors[bundleIndex*2+1],
            papillaryMuscleTips, leafletSecondaryCurve, leafletSurfaceModel, chordsFolderItemId)
    finally:
      slicer.app.resumeRender()

  def createChordBundlesFromRegions(self, parameterNode, chordsFolderItemId, logCallback=None):
    papillaryMuscleTips = parameterNode.GetNodeReference("PapillaryMuscleTips")
    if not papillaryMuscleTips or papillaryMuscleTips.GetNumberOfControlPoints() == 0:
      raise ValueError("Invalid papillary muscle tips node")
    slicer.app.pauseRender()
    try:
      # Divide by 100 because chordsDensity is in length unit (mm)
      chordsDensity = float(parameterNode.GetParameter("ChordsPerCm2") if parameterNode.GetParameter("ChordsPerCm2") else "17") / 100.0
      leafletRegionsFolderItem = self.getSubjectHierarchyLeafletRegionsSubfolder(parameterNode)
      leafletRegionNodes = vtk.vtkCollection()
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      shNode.GetDataNodesInBranch(leafletRegionsFolderItem, leafletRegionNodes, "vtkMRMLMarkupsClosedCurveNode")
      for regionIndex in range(leafletRegionNodes.GetNumberOfItems()):
        leafletRegionBoundaryNode = leafletRegionNodes.GetItemAsObject(regionIndex)
        if logCallback:
          logCallback(f"Creating chord bundles for {leafletRegionBoundaryNode.GetName()}...")
        self.createChordBundleFromRegion(parameterNode, leafletRegionBoundaryNode, chordsDensity, chordsFolderItemId)
    finally:
      slicer.app.resumeRender()

  def createChordBundleFromRegion(self, parameterNode, leafletRegionBoundaryNode, chordsDensity, chordsFolderItemId):
    """
    :param parameterNode:
    :param leafletRegionBoundaryNode:
    :param chordsDensity: in chords per mm2, 0.17 is a good number
    :return:
    """

    baseName = leafletRegionBoundaryNode.GetName()

    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    folderItem = shNode.CreateFolderItem(shNode.GetSceneItemID(), baseName)
    shNode.SetItemParent(folderItem, chordsFolderItemId)

    # Get leaflet region
    leafletModelNode = leafletRegionBoundaryNode.GetNodeReference("LeafletSurfaceModel")
    if not leafletModelNode:
      raise ValueError("Invalid leaflet surface model")
    curveCut = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLDynamicModelerNode")
    curveCut.SetToolName("Curve cut")
    curveCut.SetNodeReferenceID("CurveCut.InputCurve", leafletRegionBoundaryNode.GetID())
    curveCut.SetNodeReferenceID("CurveCut.InputModel", leafletModelNode.GetID())
    leafletRegionModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")  # this node will store the hollow model
    curveCut.SetNodeReferenceID("CurveCut.OutputInside", leafletRegionModelNode.GetID())
    slicer.modules.dynamicmodeler.logic().RunDynamicModelerTool(curveCut)

    # Get area of each cell of the leaflet region to weigh the cell sampling with it
    meshQuality = vtk.vtkMeshQuality()
    meshQuality.SetInputData(leafletRegionModelNode.GetPolyData())
    meshQuality.SetTriangleQualityMeasureToArea()
    meshQuality.Update()
    leafletRegionMesh = meshQuality.GetOutput()
    leafletRegionModelNode.SetAndObserveMesh(leafletRegionMesh)
    cellAreas = slicer.util.arrayFromModelCellData(leafletRegionModelNode, 'Quality')
    regionArea = sum(cellAreas)
    numberOfChords = int(regionArea * chordsDensity)
    logging.info(f"Number of chords for region {leafletRegionBoundaryNode.GetName()}: {numberOfChords}")
    if numberOfChords>100:
      if not slicer.util.confirmYesNoDisplay(f"The number of chords for region {leafletRegionBoundaryNode.GetName()} is very high ({numberOfChords}). Are you sure that the model scale is correct?"):
        return

    # Randomly sample cell, with using the area as weighing factor
    import random
    cellIds = random.choices(list(range(len(cellAreas))), weights=cellAreas, k=numberOfChords)

    #leafletRegionMesh = leafletRegionModelNode.GetMesh()
    pointPositions = []
    for cellId in cellIds:
      cell = leafletRegionMesh.GetCell(cellId)
      # randomly choose one of the point of the triangle cell
      pointPositions.append(leafletRegionMesh.GetPoint(cell.GetPointIds().GetId(random.randint(0, cell.GetNumberOfPoints()-1))))

    #chordEndPoints = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "C")
    #slicer.util.updateMarkupsControlPointsFromArray(chordEndPoints, np.array(pointPositions))

    # Get papillary muscle tip position
    papillaryMuscleTipsNode = parameterNode.GetNodeReference("PapillaryMuscleTips")
    papillaryMuscleTipsPointLabel = leafletRegionBoundaryNode.GetAttribute("PapillaryMuscleTipPoint")
    papillaryMuscleTipPosition = np.zeros(3)
    for i in range(papillaryMuscleTipsNode.GetNumberOfControlPoints()):
      if papillaryMuscleTipsNode.GetNthControlPointLabel(i) == papillaryMuscleTipsPointLabel:
        # found the muscle tip point in the list
        papillaryMuscleTipsNode.GetNthControlPointPositionWorld(i, papillaryMuscleTipPosition)

    chordTableNode, chordIndexArray, chordNameArray, chordStartPositionArray, chordEndPositionArray = self.createChordTable(baseName, chordsFolderItemId)

    for endPointIndex, endPoint_World in enumerate(pointPositions):
        # Create line
        chordName = "{0}-{2:02d}".format(baseName,papillaryMuscleTipsPointLabel,endPointIndex)
        line = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", chordName)
        #line.SetLocked(True)  # it is left unlocked to allow the user to rearrange the points to achieve more uniform sampling
        line.CreateDefaultDisplayNodes()
        line.GetDisplayNode().SetSelectedColor(leafletRegionBoundaryNode.GetDisplayNode().GetSelectedColor())
        line.GetDisplayNode().SetPropertiesLabelVisibility(False)
        line.GetDisplayNode().SetPointLabelsVisibility(False)
        line.GetDisplayNode().SetGlyphTypeFromString("Sphere3D")
        line.GetDisplayNode().UseGlyphScaleOff()
        line.GetDisplayNode().SetGlyphSize(0.5)
        line.GetDisplayNode().SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeToVisibleSurface)
        line.AddControlPointWorld(vtk.vtkVector3d(papillaryMuscleTipPosition), papillaryMuscleTipsPointLabel)
        line.AddControlPointWorld(vtk.vtkVector3d(endPoint_World), "{0}-{1:02d}".format(baseName, endPointIndex))
        # Put under subject hierarchy folder
        shNode.SetItemParent(shNode.GetItemByDataNode(line), folderItem)
        # Add chord to the table
        rowIndex = chordTableNode.AddEmptyRow()
        chordIndexArray.SetValue(rowIndex, rowIndex+1)  # index in the table is 1-based
        chordStartPositionArray.SetTuple3(rowIndex, papillaryMuscleTipPosition[0], papillaryMuscleTipPosition[1], papillaryMuscleTipPosition[2])
        chordEndPositionArray.SetTuple3(rowIndex, endPoint_World[0], endPoint_World[1], endPoint_World[2])
        chordNameArray.SetValue(rowIndex, chordName)

    slicer.mrmlScene.RemoveNode(curveCut)
    slicer.mrmlScene.RemoveNode(leafletRegionModelNode)

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
    import math
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
    import HeartValveLib
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
    samplingDistance = curveLengthMm / (numberOfCurveLandmarkPoints-0.1)
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
    import numpy as np
    bounds=np.zeros(6)
    medialSurfaceNode.GetBounds(bounds)
    # we will make the NURBS rectangular control point grid a bit bigger than the input surface
    # to avoid artifacts on the boundary
    margin = (bounds[1]-bounds[0])*0.10

    import math

    medialSurfaceLocalizer = vtk.vtkModifiedBSPTree()
    medialSurfaceLocalizer.SetDataSet(medialSurfaceNode.GetPolyData())
    medialSurfaceLocalizer.BuildLocator()

    tri=vtk.vtkTriangleFilter()
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
                    #raise ValueError(f"No intersection found with warped surface at {uindex}, {vindex}. Increase rectangle margin or decrease nurbs margin.")
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
        timer=vtk.vtkTimerLog()
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

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

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
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
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

      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
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
