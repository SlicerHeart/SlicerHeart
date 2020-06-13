import os
import unittest
import logging
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

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
    self.parent.dependencies = []  # TODO: add here list of module names that this module requires
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
      (self.ui.marginCurveNodeComboBox1, "MarginCurve1"),
      (self.ui.secondaryCurveNodeComboBox1, "SecondaryCurve1"),
      (self.ui.leafletModelNodeComboBox2, "LeafletModel2"),
      (self.ui.marginCurveNodeComboBox2, "MarginCurve2"),
      (self.ui.secondaryCurveNodeComboBox2, "SecondaryCurve2"),
      (self.ui.leafletModelNodeComboBox3, "LeafletModel3"),
      (self.ui.marginCurveNodeComboBox3, "MarginCurve3"),
      (self.ui.secondaryCurveNodeComboBox3, "SecondaryCurve3")
      ]

    curvePlaceWidgets = [
      self.ui.papillaryMuscleTipsPlaceWidget,
      self.ui.marginCurvePlaceWidget1, self.ui.secondaryCurvePlaceWidget1,
      self.ui.marginCurvePlaceWidget2, self.ui.secondaryCurvePlaceWidget2,
      self.ui.marginCurvePlaceWidget3, self.ui.secondaryCurvePlaceWidget3
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
    self.ui.createChordsButton.connect('clicked(bool)', self.onCreateChords)
    self.ui.exportButton.connect('clicked(bool)', self.onExport)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    for nodeSelector, nodeReferenceRole in self.nodeSelectors:
      nodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)

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

    # Unobserve previusly selected parameter node and add an observer to the newly selected.
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

    if self._parameterNode is None:
      return

    # Update each widget from parameter node
    # Need to temporarily block signals to prevent infinite recursion (MRML node update triggers
    # GUI update, which triggers MRML node update, which triggers GUI update, ...)

    for nodeSelector, nodeReferenceRole in self.nodeSelectors:
      wasBlocked = nodeSelector.blockSignals(True)
      nodeSelector.setCurrentNode(self._parameterNode.GetNodeReference(nodeReferenceRole))
      nodeSelector.blockSignals(wasBlocked)

    self.ui.chordBundleNameEdit1.text = self._parameterNode.GetParameter("ChordName1")
    self.ui.chordBundleNameEdit2.text = self._parameterNode.GetParameter("ChordName2")
    self.ui.chordBundleNameEdit3.text = self._parameterNode.GetParameter("ChordName3")

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

  def updateParameterNodeFromGUI(self, caller=None, event=None):
    """
    This method is called when the user makes any change in the GUI.
    The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
    """

    if self._parameterNode is None:
      return

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

  def onHeartValveImport(self):
    heartValveNode = self._parameterNode.GetNodeReference("HeartValve")
    import HeartValveLib
    valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)
    wasModified = self._parameterNode.StartModify()
    
    self._parameterNode.SetNodeReferenceID("AnnulusCurve", valveModel.getAnnulusContourMarkupNode().GetID())
    self._parameterNode.SetNodeReferenceID("AnnulusModel", valveModel.getAnnulusContourModelNode().GetID())

    # Is not set for now:
    # "PapillaryMuscleTips"
    # "MarginCurve1", "SecondaryCurve1"
    # "MarginCurve2", "SecondaryCurve2"
    # "MarginCurve3", "SecondaryCurve3"

    # Leaflet models
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    parameterNodeItemId = shNode.GetItemByDataNode(self._parameterNode)
    leafletModelsFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, "Leaflet models")
    if leafletModelsFolderItemId:
      shNode.RemoveItemChildren(leafletModelsFolderItemId)
    else:
      leafletModelsFolderItemId = shNode.CreateFolderItem(parameterNodeItemId, "Leaflet models")
    slicer.modules.segmentations.logic().ExportAllSegmentsToModels(valveModel.getLeafletSegmentationNode(), leafletModelsFolderItemId)
    # Delete annulus mask model
    annulusMaskModeId = shNode.GetItemChildWithName(leafletModelsFolderItemId, "Annulus mask")
    annulusMaskModeNode = shNode.GetItemDataNode(annulusMaskModeId)
    if annulusMaskModeNode:
      slicer.mrmlScene.RemoveNode(annulusMaskModeNode)
    # Put back folder under export folder
    shNode.SetItemParent(leafletModelsFolderItemId, parameterNodeItemId)

    for leafletIndex, leafletModel in enumerate(valveModel.leafletModels):

      import re
      result = re.match("[^ ]+ (.+) leaflet", leafletModel.getName())
      if result:
        chordName = result.groups()[0]
        self._parameterNode.SetParameter("ChordName"+str(leafletIndex+1), chordName)

      leafletModeId = shNode.GetItemChildWithName(leafletModelsFolderItemId, leafletModel.getLeafletSegment().GetName())
      leafletModeNode = shNode.GetItemDataNode(leafletModeId)
      self._parameterNode.SetNodeReferenceID("LeafletModel"+str(leafletIndex+1), leafletModeNode.GetID())

    self._parameterNode.Modified()
    self._parameterNode.EndModify(wasModified)


  def onCreateChords(self):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    parameterNodeItemId = shNode.GetItemByDataNode(self._parameterNode)
    chordsFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, "Chords")
    if chordsFolderItemId:
      shNode.RemoveItemChildren(chordsFolderItemId)
    else:
      chordsFolderItemId = shNode.CreateFolderItem(parameterNodeItemId, "Chords")
    self.logic.createChordBundles(self._parameterNode, chordsFolderItemId)

  def onExport(self):
    """
    Run processing when user clicks "Apply" button.
    """
    self.ui.outputPathLineEdit.addCurrentPathToHistory()
    slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
    try:
      self.logic.exportModel(self._parameterNode, self.ui.outputPathLineEdit.currentPath)
    except Exception as e:
      import traceback
      traceback.print_exc()
      slicer.util.errorDisplay("Failed to export data: "+str(e))
    slicer.app.restoreOverrideCursor() 

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

  def setDefaultParameters(self, parameterNode):
    """
    Initialize parameter node with default settings.
    """
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
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
    distanceFilter = vtk.vtkImplicitPolyDataDistance()
    distanceFilter.SetInput(surface_World)
    for endPointIndex in range(endPoints.GetNumberOfControlPoints()):
        endPoint_World = [0,0,0]
        endPoints.GetNthControlPointPositionWorld(endPointIndex, endPoint_World)
        # Snap to closest point on surface
        closestPointOnSurface_World = [0,0,0]
        closestPointDistance = distanceFilter.EvaluateFunctionAndGetClosestPoint(endPoint_World, closestPointOnSurface_World)
        endPoint_World = closestPointOnSurface_World
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
        line = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", "{0}-{1}-{2:02d}".format(baseName,closestStartPointName,endPointIndex))
        line.CreateDefaultDisplayNodes()
        line.GetDisplayNode().SetSelectedColor(color)
        line.AddControlPointWorld(vtk.vtkVector3d(closestStartPoint_World), closestStartPointName)
        line.AddControlPointWorld(vtk.vtkVector3d(endPoint_World), "{0}-{1:02d}".format(baseName, endPointIndex))
        # Put under subject hierarchy folder
        shNode.SetItemParent(shNode.GetItemByDataNode(line), folderItem)
  
  def createChordBundles(self, parameterNode, chordsFolderItemId):
    papillaryMuscleTips = parameterNode.GetNodeReference("PapillaryMuscleTips")
    colors = [[1.0,0.3,0.3], [1.0,0.6,0.6], [0.3,1.0,0.3], [0.8,1.0,0.8], [0.3,0.3,1], [0.8,0.8,1.0]]
    for bundleIndex in range(3):
      leafletSurfaceModel = parameterNode.GetNodeReference("LeafletModel"+str(bundleIndex+1))
      leafletMarginCurve = parameterNode.GetNodeReference("MarginCurve"+str(bundleIndex+1))
      leafletSecondaryCurve = parameterNode.GetNodeReference("SecondaryCurve"+str(bundleIndex+1))
      if not leafletSurfaceModel:
        continue
      if leafletMarginCurve:
        self.createChordBundle(leafletSurfaceModel.GetName()+'-primary', colors[bundleIndex*2],
          papillaryMuscleTips, leafletMarginCurve, leafletSurfaceModel, chordsFolderItemId)
      if leafletSecondaryCurve:
        self.createChordBundle(leafletSurfaceModel.GetName()+'-secondary', colors[bundleIndex*2+1],
          papillaryMuscleTips, leafletSecondaryCurve, leafletSurfaceModel, chordsFolderItemId)

  def saveNode(self, node, outputFolder, expectedTransformNode, enableTransformChange):
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
    else:
      if not self.markupsStorageNode:
        self.markupsStorageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsJsonStorageNode")
      storageNode = self.markupsStorageNode
      extension = ".mkp.json"
    filename = node.GetName().replace(" ", "_") + extension
    logging.info("Saving node "+filename)
    storageNode.SetFileName(outputFolder+"/"+filename)
    storageNode.SetCoordinateSystem(slicer.vtkMRMLStorageNode.CoordinateSystemLPS)
    if not storageNode.WriteData(node):
      raise("Failed to save node: " + node.GetName())

  def deleteTemporaryStorageNodes(self):
    if self.modelStorageNode:
      slicer.mrmlScene.RemoveNode(self.modelStorageNode)
    if self.markupsStorageNode:
      slicer.mrmlScene.RemoveNode(self.markupsStorageNode)

  def exportModel(self, parameterNode, outputFolder):
    commonParentTransformNode = parameterNode.GetNodeReference("LeafletModel1").GetParentTransformNode()

    # Save selected HeartValve nodes
    for referenceRole in ["AnnulusCurve", "AnnulusModel", "LeafletModel1", "LeafletModel2", "LeafletModel3"]:
      node = parameterNode.GetNodeReference(referenceRole)
      if not node:
        continue
      self.saveNode(node, outputFolder, commonParentTransformNode, enableTransformChange=False)

    # Save all chords
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    parameterNodeItemId = shNode.GetItemByDataNode(parameterNode)
    chordsFolderItemId = shNode.GetItemChildWithName(parameterNodeItemId, "Chords")
    chordItemIds = vtk.vtkIdList()
    shNode.GetItemChildren(chordsFolderItemId, chordItemIds, True)
    for chordItemIdIndex in range(chordItemIds.GetNumberOfIds()):
      chordItemId = chordItemIds.GetId(chordItemIdIndex)
      chordNode = shNode.GetItemDataNode(chordItemId)
      if not chordNode:
        # folder item
        continue
      self.saveNode(chordNode, outputFolder, commonParentTransformNode, enableTransformChange=True)
      slicer.app.processEvents()
    
    self.deleteTemporaryStorageNodes()
    logging.info("Export is completed to foler: "+outputFolder)

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
