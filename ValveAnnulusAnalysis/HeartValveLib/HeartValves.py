import os
import vtk
import slicer
import HeartValveLib
from HeartValveLib.Constants import VALVE_MASK_SEGMENT_ID, DEFAULT_SLICE_VIEW_SHOWN_IN_3D
from HeartValveLib.helpers import getAllModuleSpecificScriptableNodes
from HeartValveLib.util import getAllSegmentIDs

import logging

# Dictionary that stores a ValveBrowser Python object for each valve browser MRML node in the scene.
# These Python objects are shared between multiple modules.
ValveBrowsers = {}

# Dictionary that stores a ValveModel Python object for each MRML node in the scene.
# These Python objects are shared between multiple modules.
ValveModels = {}

CardiacFourUpViewLayoutId = 1512
CardiacEightUpViewLayoutId = 1513

HeartOrientationMarkerType = "heart"

try:
  SceneEndImportEventObserver
except NameError:
  SceneEndImportEventObserver = None


def setup(usPresetsScenePath):
  global SceneEndImportEventObserver
  registerCustomLayouts()
  registerCustomVrPresets(usPresetsScenePath)
  updateLegacyHeartValveNodes()
  if SceneEndImportEventObserver is None:
    logging.debug("Added scene end import observer for HeartValves")
    SceneEndImportEventObserver = slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.EndImportEvent, updateLegacyHeartValveNodes)
    # Register subject hierarchy plugin
    import HeartValvesSubjectHierarchyPlugin as hvp
    scriptedPlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
    scriptedPlugin.setPythonSource(hvp.HeartValvesSubjectHierarchyPlugin.filePath)


def getTerminologyFile():
  moduleDir = os.path.dirname(slicer.modules.valveannulusanalysis.path)
  terminologyFile = os.path.join(moduleDir, 'Resources', 'SlicerHeartSegmentationCategoryTypeModifier.json')
  return terminologyFile


def getValveBrowser(valveBrowserNode):
  if valveBrowserNode is None:
    return None

  try:
    valveBrowser = ValveBrowsers[valveBrowserNode]
  except KeyError:
    from HeartValveLib.ValveBrowser import ValveBrowser
    valveBrowser = ValveBrowser()
    valveBrowser.valveBrowserNode = valveBrowserNode

    ValveBrowsers[valveBrowserNode] = valveBrowser
  return valveBrowser


def getValveModel(heartValveNode):
  if heartValveNode is None:
    return None

  try:
    valveModel = ValveModels[heartValveNode]
  except KeyError:
    from HeartValveLib.ValveModel import ValveModel
    valveModel = ValveModel()
    valveModel.setHeartValveNode(heartValveNode)

    # For legacy scenes
    setSequenceBrowserNodeDisplayIndex(valveModel)

    ValveModels[heartValveNode] = valveModel
  return valveModel


def setHeartOrientationmarker(viewNodeId):
  import slicer
  viewNode = slicer.mrmlScene.GetNodeByID(viewNodeId)
  if HeartOrientationMarkerType == "axes":
    viewNode.SetOrientationMarkerType(slicer.vtkMRMLAbstractViewNode.OrientationMarkerTypeAxes)
    viewNode.SetOrientationMarkerSize(slicer.vtkMRMLAbstractViewNode.OrientationMarkerSizeMedium)
  elif HeartOrientationMarkerType == "heart":
    orientationMarkerNode = slicer.mrmlScene.GetFirstNodeByName('HeartOrientationMarker')
    if not orientationMarkerNode:
      moduleDir = os.path.dirname(slicer.modules.valveannulusanalysis.path)
      orientationMarkerModelFilePath = os.path.join(moduleDir, 'Resources', 'HeartOrientationMarker.vtp')
      orientationMarkerNode = slicer.util.loadModel(orientationMarkerModelFilePath)
      orientationMarkerNode.HideFromEditorsOn()
      orientationMarkerNode.GetDisplayNode().SetVisibility(False) # hide from the viewers, just use it as an orientation marker
      orientationMarkerNode.SetName('HeartOrientationMarker')
    viewNode.SetOrientationMarkerHumanModelNodeID(orientationMarkerNode.GetID() )
    viewNode.SetOrientationMarkerType(slicer.vtkMRMLAbstractViewNode.OrientationMarkerTypeHuman)
    viewNode.SetOrientationMarkerSize(slicer.vtkMRMLAbstractViewNode.OrientationMarkerSizeMedium)


def registerCustomLayouts():
  """Register custom layout when application has started up.
  Need to do it before the widget is activated because a scene with a custom layout may be loaded
  before opening the module GUI."""

  layoutManager = slicer.app.layoutManager()

  customLayout = (
    "<layout type=\"vertical\">"
    " <item>"
    "  <layout type=\"horizontal\">"
    "   <item>"
    "    <view class=\"vtkMRMLSliceNode\" singletontag=\"Green\">"
    "     <property name=\"orientation\" action=\"default\">Coronal</property>"
    "     <property name=\"viewlabel\" action=\"default\">G</property>"
    "     <property name=\"viewcolor\" action=\"default\">#6EB04B</property>"
    "    </view>"
    "   </item>"
    "   <item>"
    "    <view class=\"vtkMRMLSliceNode\" singletontag=\"Yellow\">"
    "     <property name=\"orientation\" action=\"default\">Sagittal</property>"
    "     <property name=\"viewlabel\" action=\"default\">Y</property>"
    "     <property name=\"viewcolor\" action=\"default\">#EDD54C</property>"
    "    </view>"
    "   </item>"
    "  </layout>"
    " </item>"
    " <item>"
    "  <layout type=\"horizontal\">"
    "   <item>"
    "    <view class=\"vtkMRMLSliceNode\" singletontag=\"Red\">"
    "     <property name=\"orientation\" action=\"default\">Axial</property>"
    "     <property name=\"viewlabel\" action=\"default\">R</property>"
    "     <property name=\"viewcolor\" action=\"default\">#F34A33</property>"
    "    </view>"
    "   </item>"
    "   <item>"
    "    <view class=\"vtkMRMLViewNode\" singletontag=\"1\">"
    "     <property name=\"viewlabel\" action=\"default\">1</property>"
    "    </view>"
    "   </item>"
    "  </layout>"
    " </item>"
    "</layout>"
  )
  layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(CardiacFourUpViewLayoutId, customLayout)

  customLayout = (
    "<layout type=\"horizontal\" split=\"true\">"

    "<item>"
    "<layout type=\"vertical\">"
    " <item>"
    "  <layout type=\"horizontal\">"
    "   <item>"
    "    <view class=\"vtkMRMLSliceNode\" singletontag=\"Green\">"
    "     <property name=\"orientation\" action=\"default\">Coronal</property>"
    "     <property name=\"viewlabel\" action=\"default\">G</property>"
    "     <property name=\"viewcolor\" action=\"default\">#6EB04B</property>"
    "    </view>"
    "   </item>"
    "   <item>"
    "    <view class=\"vtkMRMLSliceNode\" singletontag=\"Yellow\">"
    "     <property name=\"orientation\" action=\"default\">Sagittal</property>"
    "     <property name=\"viewlabel\" action=\"default\">Y</property>"
    "     <property name=\"viewcolor\" action=\"default\">#EDD54C</property>"
    "    </view>"
    "   </item>"
    "  </layout>"
    " </item>"
    " <item>"
    "  <layout type=\"horizontal\">"
    "   <item>"
    "    <view class=\"vtkMRMLSliceNode\" singletontag=\"Red\">"
    "     <property name=\"orientation\" action=\"default\">Axial</property>"
    "     <property name=\"viewlabel\" action=\"default\">R</property>"
    "     <property name=\"viewcolor\" action=\"default\">#F34A33</property>"
    "    </view>"
    "   </item>"
    "   <item>"
    "    <view class=\"vtkMRMLViewNode\" singletontag=\"1\">"
    "     <property name=\"viewlabel\" action=\"default\">1</property>"
    "    </view>"
    "   </item>"
    "  </layout>"
    " </item>"
    "</layout>"
    "</item>"

    "<item>"
    "<layout type=\"vertical\">"
    " <item>"
    "  <layout type=\"horizontal\">"
    "   <item>"
    "    <view class=\"vtkMRMLSliceNode\" singletontag=\"Slice6\">"
    "     <property name=\"orientation\" action=\"default\">Coronal</property>"
    "     <property name=\"viewlabel\" action=\"default\">GS</property>"
    "     <property name=\"viewcolor\" action=\"default\">#6EB04B</property>"
    "    </view>"
    "   </item>"
    "   <item>"
    "    <view class=\"vtkMRMLSliceNode\" singletontag=\"Slice5\">"
    "     <property name=\"orientation\" action=\"default\">Sagittal</property>"
    "     <property name=\"viewlabel\" action=\"default\">YS</property>"
    "     <property name=\"viewcolor\" action=\"default\">#EDD54C</property>"
    "    </view>"
    "   </item>"
    "  </layout>"
    " </item>"
    " <item>"
    "  <layout type=\"horizontal\">"
    "   <item>"
    "    <view class=\"vtkMRMLSliceNode\" singletontag=\"Slice4\">"
    "     <property name=\"orientation\" action=\"default\">Axial</property>"
    "     <property name=\"viewlabel\" action=\"default\">RS</property>"
    "     <property name=\"viewcolor\" action=\"default\">#F34A33</property>"
    "    </view>"
    "   </item>"
    "   <item>"
    "    <view class=\"vtkMRMLViewNode\" singletontag=\"1S\">"
    "     <property name=\"viewlabel\" action=\"default\">1S</property>"
    "    </view>"
    "   </item>"
    "  </layout>"
    " </item>"
    "</layout>"
    "</item>"

    "</layout>"
  )
  layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(CardiacEightUpViewLayoutId, customLayout)


def setupDefaultLayout(layoutId=CardiacFourUpViewLayoutId):
  """Sets up views (layout, annotations, slice intersections) in general,
  not for a specific valve."""
  layoutManager = slicer.app.layoutManager()
  if not layoutManager:
    # application is shutting down
    return

  layoutManager.setLayout(layoutId)

  sliceViewNames = ['Red', 'Yellow', 'Green']
  [oldLink, oldHotLink] = setSliceViewsLink(sliceViewNames, False, False)

  # Set heart orientation marker
  for nodeId in ['vtkMRMLViewNode1', 'vtkMRMLSliceNodeRed', 'vtkMRMLSliceNodeGreen', 'vtkMRMLSliceNodeYellow']:
    HeartValveLib.HeartValves.setHeartOrientationmarker(nodeId)

  for sliceViewName in sliceViewNames:
    sliceLogic = layoutManager.sliceWidget(sliceViewName).sliceLogic()
    sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
    sliceViewNode = sliceLogic.GetSliceNode()

    # Show slice intersections
    sliceLogic.GetSliceDisplayNode().SetIntersectingSlicesVisibility(True)

    sliceViewNode.SetSliceVisible(sliceViewName == DEFAULT_SLICE_VIEW_SHOWN_IN_3D)

  setSliceViewsLink(sliceViewNames, oldLink, oldHotLink)

def showSlices(show):
  if not slicer.app.errorLogModel():
    # shutting down
    return

  # If slice views are linked then changing properties would repeatedly change
  # properties in all the views, so we temporarily disable slice linking
  viewNames = ['Red', 'Yellow', 'Green']
  [oldLink, oldHotLink] = HeartValveLib.setSliceViewsLink(viewNames, False, False)
  for viewName in viewNames:
    slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNode'+viewName).SetSliceVisible(show)
  HeartValveLib.setSliceViewsLink(viewNames, oldLink, oldHotLink)


def setSliceViewsLink(viewNames, link, hotlink):
  layoutManager = slicer.app.layoutManager()
  if not layoutManager:
    # application is closing
    return
  oldValuesStored = False
  oldLink = False
  oldHotLink = False
  for sliceViewName in viewNames:
    sliceLogic = layoutManager.sliceWidget(sliceViewName).sliceLogic()
    sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
    if not oldValuesStored:
      oldLink = sliceCompositeNode.GetLinkedControl()
      oldHotLink = sliceCompositeNode.GetHotLinkedControl()
      oldValuesStored = True
    sliceCompositeNode.SetLinkedControl(link)
    sliceCompositeNode.SetHotLinkedControl(hotlink)
  return oldLink, oldHotLink


def setupDefaultSliceOrientation(resetFov=False, valveModelOrBrowser=None, orthoRotationDeg=0,
                                 axialSliceName='Red', ortho1SliceName='Yellow', ortho2SliceName='Green',
                                 show3DSliceName=None, valveModel = None, valveBrowser = None):
  """Sets up views for a specific valve.
  show3DSliceName is the name of the slice that should be shown in 3D views
  valveModel: can be valve model or browser"""

  if show3DSliceName is None:
    show3DSliceName = DEFAULT_SLICE_VIEW_SHOWN_IN_3D

  layoutManager = slicer.app.layoutManager()
  if not layoutManager:
    # application is closing
    return

  [oldLink, oldHotLink] = setSliceViewsLink([axialSliceName, ortho1SliceName, ortho2SliceName], False, False)

  valveModelOrBrowser.setSliceOrientations(layoutManager.sliceWidget(axialSliceName).sliceLogic().GetSliceNode(),
                                           layoutManager.sliceWidget(ortho1SliceName).sliceLogic().GetSliceNode(),
                                           layoutManager.sliceWidget(ortho2SliceName).sliceLogic().GetSliceNode(),
                                           orthoRotationDeg)

  for sliceViewName in [axialSliceName, ortho1SliceName, ortho2SliceName]:
    sliceLogic = layoutManager.sliceWidget(sliceViewName).sliceLogic()
    sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
    sliceViewNode = sliceLogic.GetSliceNode()

    # Show slice intersections
    sliceLogic.GetSliceDisplayNode().SetIntersectingSlicesVisibility(True)

    # Show only red slice in 3D view
    sliceViewNode.SetSliceVisible(sliceViewName == show3DSliceName)

    if resetFov:
      sliceLogic.FitSliceToAll()

  # Show volume in center of 3D view
  if resetFov:
    for threeDViewIndex in range(layoutManager.threeDViewCount):
      view = layoutManager.threeDWidget(threeDViewIndex).threeDView()
      if view.mrmlViewNode().IsMappedInLayout():
        view.resetFocalPoint()

  setSliceViewsLink([axialSliceName, ortho1SliceName, ortho2SliceName], oldLink, oldHotLink)


def registerCustomVrPresets(usPresetsScenePath):
  """
  Set volume rendering presets from Resources/VrPresets/US-VrPresets.mrml
  """

  if not os.path.isfile(usPresetsScenePath):
    logging.warning('Volume rendering presets are not found at {0}'.format(usPresetsScenePath))
    return

  # Read scene
  usPresetsScene = slicer.vtkMRMLScene()
  vrPropNode = slicer.vtkMRMLVolumePropertyNode()
  usPresetsScene.RegisterNodeClass(vrPropNode)
  usPresetsScene.SetURL(usPresetsScenePath)
  usPresetsScene.Connect()

  # Add presets to volume rendering logic
  vrLogic = slicer.modules.volumerendering.logic()
  presetsScene = vrLogic.GetPresetsScene()
  vrNodes = usPresetsScene.GetNodesByClass("vtkMRMLVolumePropertyNode")
  vrNodes.UnRegister(None)
  for itemNum in range(vrNodes.GetNumberOfItems()):
    node = vrNodes.GetItemAsObject(itemNum)
    vrLogic.AddPreset(node)


def getSequenceBrowserNodeForMasterOutputNode(masterOutputNode):
  browserNodes = slicer.mrmlScene.GetNodesByClass('vtkMRMLSequenceBrowserNode')
  browserNodes.UnRegister(None)
  for itemIndex in range(browserNodes.GetNumberOfItems()):
    browserNode = browserNodes.GetItemAsObject(itemIndex)
    if browserNode.GetProxyNode(browserNode.GetMasterSequenceNode()) == masterOutputNode:
      return browserNode
  return None


def getBrowserNodesForSequenceNode(masterSequenceNode):
  browserNodes = slicer.mrmlScene.GetNodesByClass('vtkMRMLSequenceBrowserNode')
  browserNodes.UnRegister(None)
  foundBrowserNodes = []
  for itemIndex in range(browserNodes.GetNumberOfItems()):
    browserNode = browserNodes.GetItemAsObject(itemIndex)
    if browserNode.GetMasterSequenceNode() == masterSequenceNode:
      foundBrowserNodes.append(browserNode)
  return foundBrowserNodes


def setSequenceBrowserNodeDisplayIndex(valveModel):
  """This method changes all sequence browser nodes associated with the provided valveModel
  so that sequence browser seek widgets display frame index instead of frame time"""
  volumeNode = valveModel.getValveVolumeNode()
  if not volumeNode:
    return
  volumeSequenceBrowserNode = getSequenceBrowserNodeForMasterOutputNode(volumeNode)
  if not volumeSequenceBrowserNode:
    return
  if not hasattr(volumeSequenceBrowserNode, 'SetIndexDisplayMode'):
    # Old Sequences extension version, SetIndexDisplayMode is not supported yet
    return
  volumeSequenceBrowserNode.SetIndexDisplayMode(volumeSequenceBrowserNode.IndexDisplayAsIndex)


def goToAnalyzedFrame(valveModel):
  if valveModel is None:
    return
  valveVolumeSequenceIndex = valveModel.getValveVolumeSequenceIndex()
  volumeNode = valveModel.getValveVolumeNode()
  if valveVolumeSequenceIndex < 0 or not volumeNode:
    return
  volumeSequenceBrowserNode = getSequenceBrowserNodeForMasterOutputNode(volumeNode)
  if not volumeSequenceBrowserNode:
    return
  volumeSequenceBrowserNode.SetSelectedItemNumber(valveVolumeSequenceIndex)


def copyNodeContentToNewScriptedModuleNode(oldDataNode, shNode):
  newDataNode = slicer.vtkMRMLScriptedModuleNode()
  newDataNode.HideFromEditorsOff()
  # Copy node attributes
  attributeNames = vtk.vtkStringArray()
  oldDataNode.GetAttributeNames(attributeNames)
  for index in range(attributeNames.GetNumberOfValues()):
    attributeName = attributeNames.GetValue(index)
    newDataNode.SetAttribute(attributeName, oldDataNode.GetAttribute(attributeName))
  slicer.mrmlScene.AddNode(newDataNode)
  newDataNode.SetName(oldDataNode.GetName())
  # Copy node references
  newDataNode.CopyReferences(oldDataNode)
  # Move children
  childItemIDs = vtk.vtkIdList()
  #shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  shNode.GetItemChildren(shNode.GetItemByDataNode(oldDataNode), childItemIDs)
  for index in range(childItemIDs.GetNumberOfIds()):
    childItemID = childItemIDs.GetId(index)
    shNode.ReparentItemByDataNode(childItemID, newDataNode)
  return newDataNode


def useCurrentValveVolumeAsLeafletVolume(valveModel):
  goToAnalyzedFrame(valveModel)
  volumeNode = getOrSetValveVolumeNode(valveModel)
  leafletVolumeNode = valveModel.getLeafletVolumeNode()
  name = f"{valveModel.heartValveNode.GetName()}-segmented"
  if leafletVolumeNode is None:
    leafletVolumeNode = slicer.modules.volumes.logic().CloneVolume(volumeNode, name)
    valveModel.setLeafletVolumeNode(leafletVolumeNode)
  else:
    leafletVolumeNodeOriginalDisplayNodeId = leafletVolumeNode.GetDisplayNodeID()
    leafletVolumeNode.Copy(volumeNode)
    imageDataCopy = vtk.vtkImageData()
    imageDataCopy.DeepCopy(volumeNode.GetImageData())
    leafletVolumeNode.SetAndObserveImageData(imageDataCopy)
    leafletVolumeNode.SetName(name)
    leafletVolumeNode.SetAndObserveDisplayNodeID(leafletVolumeNodeOriginalDisplayNodeId)


def getOrSetValveVolumeNode(valveModel):
  volumeNode = valveModel.getValveVolumeNode()
  if not volumeNode:
    appLogic = slicer.app.applicationLogic()
    selNode = appLogic.GetSelectionNode()
    if selNode.GetActiveVolumeID():
      volumeNode = slicer.mrmlScene.GetNodeByID(selNode.GetActiveVolumeID())
      valveModel.setValveVolumeNode(volumeNode)
  return volumeNode


def updateLegacyHeartValveNodes(unused1=None, unused2=None):

  # TODO: re-enable after finishing refactoring
  return

  import time
  startTime = time.time()
  logging.debug("updateLegacyHeartValveNodes")
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

  # Ensure all proxy nodes are up-to-date (maybe not the latest proxy was saved with the scene)
  sequenceBrowserNodes = slicer.util.getNodesByClass('vtkMRMLSequenceBrowserNode')
  for sequenceBrowserNode in sequenceBrowserNodes:
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(sequenceBrowserNode)

  # Convert HeartValve nodes
  legacyShNodes = slicer.util.getNodesByClass("vtkMRMLSubjectHierarchyLegacyNode")
  newShItemNodeIds = {} # map from old to new SH item nodes
  for legacyShNode in legacyShNodes:
    if legacyShNode.GetAttribute("ModuleName") != "HeartValve":
      continue
    # It is a HeartValve node, move contents to new scripted parameter node
    newHeartValveNode = copyNodeContentToNewScriptedModuleNode(legacyShNode, shNode)
    shNode.SetItemAttribute(shNode.GetItemByDataNode(newHeartValveNode), "ModuleName", "HeartValve")
    # Segmentation was incorrectly not put under the SH node in old scenes, fix it now
    leafletSegmentationNode = newHeartValveNode.GetNodeReference("LeafletSegmentation")
    if leafletSegmentationNode:
      shNode.ReparentItemByDataNode(shNode.GetItemByDataNode(leafletSegmentationNode), newHeartValveNode)
    # Save old->new node ID mapping
    newShItemNodeIds[legacyShNode.GetID()] = newHeartValveNode.GetID()

  heartValves = list(getAllModuleSpecificScriptableNodes("HeartValve"))
  # Update HeartValve nodes
  updateLegacyAnnulusCurveNode(heartValves)
  removeEmptyLeafletSegments(heartValves)
  updateLegacyPapillaryMuscleNodes(heartValves)
  updateLegacyLeafletSurfaceBoundaryNodes(heartValves)
  updateLegacyCoaptationModelNodes(heartValves)
  ensureLeafletVolumeAssociatedWithSegmentations(heartValves)

  # fix icons
  for scriptedModuleNode in heartValves:
    valveNodeItemId = shNode.GetItemByDataNode(scriptedModuleNode)
    shNode.RemoveItemAttribute(valveNodeItemId,
                               slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelAttributeName())

  # Convert heart valve measurement nodes
  legacyShNodes = slicer.util.getNodesByClass("vtkMRMLSubjectHierarchyLegacyNode")
  for legacyShNode in legacyShNodes:
    if legacyShNode.GetAttribute("ModuleName") != "HeartValveMeasurement":
      continue
    # It is a HeartValve measurement node, move contents to new scripted parameter node
    newHeartValveNode = copyNodeContentToNewScriptedModuleNode(legacyShNode, shNode)
    shNode.SetItemAttribute(shNode.GetItemByDataNode(newHeartValveNode), "ModuleName", "HeartValveMeasurement")
    # Update HeartValve node references to the new SH node items using old->new node ID mapping
    for referenceRoleIndex in range(newHeartValveNode.GetNumberOfNodeReferenceRoles()):
      referenceRole = newHeartValveNode.GetNthNodeReferenceRole(referenceRoleIndex)
      for referenceIndex in range(newHeartValveNode.GetNumberOfNodeReferences(referenceRole)):
        oldNodeReferencedNodeID = newHeartValveNode.GetNthNodeReferenceID(referenceRole, referenceIndex)
        if oldNodeReferencedNodeID in newShItemNodeIds:
          newHeartValveNode.SetNthNodeReferenceID(referenceRole, referenceIndex, newShItemNodeIds[oldNodeReferencedNodeID])

  # Convert cardiac module generator nodes
  legacyShNodes = slicer.util.getNodesByClass("vtkMRMLSubjectHierarchyLegacyNode")
  for legacyShNode in legacyShNodes:
    if legacyShNode.GetAttribute("ModuleName") != "CardiacDeviceAnalysis":
      continue
    newNode = copyNodeContentToNewScriptedModuleNode(legacyShNode, shNode)
    shNode.SetItemAttribute(shNode.GetItemByDataNode(newNode), "ModuleName", "CardiacDeviceAnalysis")

  # Remove all legacy SH nodes
  legacyShNodes = slicer.util.getNodesByClass("vtkMRMLSubjectHierarchyLegacyNode")
  for legacyShNode in legacyShNodes:
    slicer.mrmlScene.RemoveNode(legacyShNode)

  # Remove all scene views because they are not used anymore in the SlicerHeart context
  for svNode in slicer.util.getNodesByClass("vtkMRMLSceneViewNode"):
    slicer.mrmlScene.RemoveNode(svNode)
  for svsNode in slicer.util.getNodesByClass("vtkMRMLSceneViewStorageNode"):
    slicer.mrmlScene.RemoveNode(svsNode)

  legacySegmentationNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
  for legacySegmentationNode in legacySegmentationNodes:
    segDisp = legacySegmentationNode.GetDisplayNode()
    seg = legacySegmentationNode.GetSegmentation()
    for segmentIndex in range(seg.GetNumberOfSegments()):
      segmentId = seg.GetNthSegmentID(segmentIndex)
      segment = seg.GetSegment(segmentId)
      color = segment.GetColor()
      overrideColor = segDisp.GetSegmentOverrideColor(segmentId)
      if overrideColor[0]<0 or overrideColor[1]<0 or overrideColor[2]<0:
        continue
      if color[0]!=0.5 or color[1]!=0.5 and color[2]!=0.5:
        continue

      # this is a legacy node

      # move override color to segment color
      segment.SetColor(overrideColor)
      segDisp.SetSegmentOverrideColor(segmentId, -1, -1, -1)

      # Rescale smoothing factor (scale was changed)
      if seg.GetConversionParameter('Smoothing factor') == '0.1':
        seg.SetConversionParameter('Smoothing factor', '0.4')
        legacySegmentationNode.RemoveClosedSurfaceRepresentation()
        legacySegmentationNode.CreateClosedSurfaceRepresentation()

  # Replace vtkMRMLMarkupsDisplayNode by vtkMRMLMarkupsFiducialDisplayNode for markups fiducial nodes
  # (now they have a dedicated display node)
  markupsFiducialNodes = slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode")
  for markupsFiducialNode in markupsFiducialNodes:
    numberOfDisplayNodes = markupsFiducialNode.GetNumberOfDisplayNodes()
    for displayNodeIndex in range(numberOfDisplayNodes):
      oldDisplayNode = markupsFiducialNode.GetNthDisplayNode(displayNodeIndex)
      if oldDisplayNode.GetClassName() == "vtkMRMLMarkupsFiducialDisplayNode":
        # Already has new-style display node
        continue
      newDisplayNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLMarkupsFiducialDisplayNode")
      newDisplayNode.UnRegister(None)  # release reference
      newDisplayNode.Copy(oldDisplayNode)
      newDisplayNode.SetVisibility2D(True)
      newDisplayNode.SetGlyphScale(3.0)
      newDisplayNode = slicer.mrmlScene.AddNode(newDisplayNode)
      if newDisplayNode == oldDisplayNode:
        # singleton node
        continue
      markupsFiducialNode.SetAndObserveNthDisplayNodeID(displayNodeIndex, newDisplayNode.GetID())
      slicer.mrmlScene.RemoveNode(oldDisplayNode)

  # Fix incorrect write state in storage nodes (due to bug in Slicer versions in early 2020, before March 19)
  # and re-read the node.
  storageNodes = slicer.util.getNodesByClass("vtkMRMLStorageNode")
  for storageNode in storageNodes:
    if storageNode.GetWriteStateAsString() != 'SkippedNoData':
      continue
    if not os.path.isfile(storageNode.GetFileName()):
      continue
    storageNode.SetWriteState(slicer.vtkMRMLModelStorageNode.Idle)
    storageNode.ReadData(storageNode.GetStorableNode())

  # Fix orientation marker that was loaded in incorrect orientation in some Slicer-4.11 versions in summer 2020.
  orientationMarkerNode = slicer.mrmlScene.GetFirstNodeByName('HeartOrientationMarker')
  if orientationMarkerNode:
    bounds=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    orientationMarkerNode.GetBounds(bounds)
    centerX = (bounds[0]+bounds[1])/2
    if centerX > 0:
      # heart center should be slightly to the left, but it is to the right
      # so this is the wrong marker - replace it with the latest one
      moduleDir = os.path.dirname(slicer.modules.valveannulusanalysis.path)
      orientationMarkerModelFilePath = os.path.join(moduleDir, 'Resources', 'HeartOrientationMarker.vtp')
      modelStorageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelStorageNode")
      modelStorageNode.SetFileName(orientationMarkerModelFilePath)
      modelStorageNode.ReadData(orientationMarkerNode)
      slicer.mrmlScene.RemoveNode(modelStorageNode)

  stopTime = time.time()
  logging.debug(f'updateLegacyHeartValveNodes completed in {stopTime - startTime:.2f} seconds')


def markupsCurveFromMarkupsFiducialNode(markupsFiducialNode, markupsClass, diameter=0.25, glyphSize=1.0, displayNode=None):
  markupsCurveNode = markupsClass()
  markupsCurveNode.SetNumberOfPointsPerInterpolatingSegment(20)
  for idx in range(markupsFiducialNode.GetNumberOfControlPoints()):
    markupsCurveNode.AddControlPoint(
      markupsFiducialNode.GetNthControlPointPosition(idx),
      markupsFiducialNode.GetNthControlPointLabel(idx)
    )
  slicer.mrmlScene.AddNode(markupsCurveNode)
  markupsCurveNode.SetName(markupsFiducialNode.GetName())
  dNode = markupsCurveNode.GetDisplayNode()
  if not dNode:
    markupsCurveNode.CreateDefaultDisplayNodes()
    dNode = markupsCurveNode.GetDisplayNode()
  from HeartValveLib.ValveModel import ValveModel
  if glyphSize:
    ValveModel.setGlyphSize(markupsCurveNode, glyphSize)
  if diameter:
    ValveModel.setLineDiameter(markupsCurveNode, diameter)
  if displayNode:
    dNode.SetSelectedColor(displayNode.GetColor())
  for attr in markupsFiducialNode.GetAttributeNames():
    markupsCurveNode.SetAttribute(attr, markupsFiducialNode.GetAttribute(attr))
  markupsCurveNode.SetDisplayVisibility(markupsFiducialNode.GetDisplayVisibility())
  markupsCurveNode.GetDisplayNode().SetPropertiesLabelVisibility(False)
  return markupsCurveNode


def updateLegacyAnnulusCurveNode(scriptedModuleNodes):
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  for scriptedModuleNode in scriptedModuleNodes:
    logging.debug(f"updateLegacyAnnulusCurveNode for {scriptedModuleNode.GetName()}")
    unSmoothedAnnulusPoints = scriptedModuleNode.GetAttribute("AnnulusContourCoordinates")
    hasUnSmoothedAnnulusPoints = unSmoothedAnnulusPoints is not None
    if hasUnSmoothedAnnulusPoints:
      annulusContourNode = scriptedModuleNode.GetNodeReference("AnnulusContourPoints")
      annulusContourNode.SetAttribute("AnnulusContourCoordinates", unSmoothedAnnulusPoints)
      scriptedModuleNode.RemoveAttribute("AnnulusContourCoordinates")

    valveNodeItemId = shNode.GetItemByDataNode(scriptedModuleNode)

    annulusContourModel = scriptedModuleNode.GetNodeReference("AnnulusContourModel")
    annulusContourNode = scriptedModuleNode.GetNodeReference("AnnulusContourPoints")
    from HeartValveLib.ValveModel import ValveModel
    if annulusContourModel:
      annulusMarkupNode = \
        markupsCurveFromMarkupsFiducialNode(annulusContourNode, slicer.vtkMRMLMarkupsClosedCurveNode,
                                            diameter=ValveModel.ANNULUS_CONTOUR_RADIUS*2,
                                            glyphSize=ValveModel.ANNULUS_CONTOUR_MARKUP_SCALE,
                                            displayNode=annulusContourModel.GetDisplayNode())
      scriptedModuleNode.SetNodeReferenceID("AnnulusContourPoints", annulusMarkupNode.GetID())
      moveNodeToHeartValveFolder(valveNodeItemId, annulusMarkupNode)
      annulusMarkupNode.SetLocked(True)
      for ptIdx in range(annulusMarkupNode.GetNumberOfControlPoints()):
        annulusMarkupNode.SetNthControlPointVisibility(ptIdx, False)
      slicer.mrmlScene.RemoveNode(annulusContourModel)
      slicer.mrmlScene.RemoveNode(annulusContourNode)


def removeEmptyLeafletSegments(scriptedModuleNodes):
  for scriptedModuleNode in scriptedModuleNodes:
    logging.debug(f"removeEmptyLeafletSegments from {scriptedModuleNode.GetName()}")
    leafletSegmentationNode = scriptedModuleNode.GetNodeReference("LeafletSegmentation")
    from SegmentStatisticsPlugins import LabelmapSegmentStatisticsPlugin
    labelStatisticsPlugin = LabelmapSegmentStatisticsPlugin()
    parameterNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode")
    parameterNode.SetParameter("Segmentation", leafletSegmentationNode.GetID())
    labelStatisticsPlugin.setParameterNode(parameterNode)
    for segmentID in getAllSegmentIDs(leafletSegmentationNode):
      if segmentID == VALVE_MASK_SEGMENT_ID:
        continue
      stats = labelStatisticsPlugin.computeStatistics(segmentID)
      if stats["voxel_count"] == 0:
        segment = leafletSegmentationNode.GetSegmentation().GetSegment(segmentID)
        logging.debug(f"Found empty segment {segment.GetName()} for {scriptedModuleNode.GetName()}. Removing it.")
        leafletSegmentationNode.RemoveSegment(segmentID)
    slicer.mrmlScene.RemoveNode(parameterNode)


def updateLegacyPapillaryMuscleNodes(scriptedModuleNodes):
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  for scriptedModuleNode in scriptedModuleNodes:
    logging.debug(f"updateLegacyPapillaryMuscleNodes for {scriptedModuleNode.GetName()}")

    # replace papillary muscle SmoothCurves
    valveNodeItemId = shNode.GetItemByDataNode(scriptedModuleNode)

    logging.debug(f"{scriptedModuleNode.GetNumberOfNodeReferences('PapillaryLineModel')} Line Models vs "
                  f"{scriptedModuleNode.GetNumberOfNodeReferences('PapillaryLineMarkup')} Markup Models")

    for papillaryModelIndex in range(scriptedModuleNode.GetNumberOfNodeReferences("PapillaryLineModel")):
      papillaryLineMarkupNode = scriptedModuleNode.GetNthNodeReference("PapillaryLineMarkup", papillaryModelIndex)
      papillaryLineModelNode = scriptedModuleNode.GetNthNodeReference("PapillaryLineModel", papillaryModelIndex)
      papillaryMuscleName = papillaryLineModelNode.GetName().replace(" papillary muscle", "")
      markupsCurveNode = \
        markupsCurveFromMarkupsFiducialNode(papillaryLineMarkupNode, slicer.vtkMRMLMarkupsCurveNode, diameter=0.5,
                                            displayNode=papillaryLineModelNode.GetDisplayNode())
      scriptedModuleNode.SetNthNodeReferenceID("PapillaryLineMarkup", papillaryModelIndex, markupsCurveNode.GetID())
      markupsCurveNode.SetName(f"{papillaryMuscleName} papillary muscle")

      # add to same shfolder
      moveNodeToHeartValveFolder(valveNodeItemId, markupsCurveNode, 'PapillaryMuscles')

    # remove PapillaryMusclesEdit folder including its children
    papMusclesEditFolderId = shNode.GetItemChildWithName(valveNodeItemId, "PapillaryMusclesEdit")
    if papMusclesEditFolderId:
      shNode.RemoveItemChildren(papMusclesEditFolderId)
      shNode.RemoveItem(papMusclesEditFolderId)

    papMusclesFolderId = shNode.GetItemChildWithName(valveNodeItemId, "PapillaryMuscles")
    if papMusclesFolderId:
      children = vtk.vtkCollection()
      shNode.GetDataNodesInBranch(papMusclesFolderId, children)
      for childIdx in range(children.GetNumberOfItems()):
        child = children.GetItemAsObject(childIdx)
        if type(child) is slicer.vtkMRMLModelNode:
          slicer.mrmlScene.RemoveNode(child)


def updateLegacyLeafletSurfaceBoundaryNodes(scriptedModuleNodes):
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  for scriptedModuleNode in scriptedModuleNodes:
    logging.debug(f"updateLegacyLeafletSurfaceBoundaryNodes for {scriptedModuleNode.GetName()}")
    valveNodeItemId = shNode.GetItemByDataNode(scriptedModuleNode)

    # leaflet surface boundary nodes
    numLegacySurfaceBoundaries = scriptedModuleNode.GetNumberOfNodeReferences("LeafletSurfaceBoundaryModel")
    numSurfaceBoundaryMarkups = scriptedModuleNode.GetNumberOfNodeReferences("LeafletSurfaceBoundaryMarkup")
    numLeafletSurfaceModels = scriptedModuleNode.GetNumberOfNodeReferences("LeafletSurfaceModel")
    if numLegacySurfaceBoundaries:
      assert numLegacySurfaceBoundaries == numSurfaceBoundaryMarkups == numLeafletSurfaceModels

      for boundaryModelIndex in range(numLegacySurfaceBoundaries):
        boundaryMarkupNode = scriptedModuleNode.GetNthNodeReference("LeafletSurfaceBoundaryMarkup", boundaryModelIndex)
        boundaryModelNode = scriptedModuleNode.GetNthNodeReference("LeafletSurfaceBoundaryModel", boundaryModelIndex)
        markupsCurveNode =\
          markupsCurveFromMarkupsFiducialNode(boundaryMarkupNode, slicer.vtkMRMLMarkupsClosedCurveNode,
                                              displayNode=boundaryModelNode.GetDisplayNode())
        scriptedModuleNode.SetNthNodeReferenceID("LeafletSurfaceBoundaryMarkup", boundaryModelIndex,
                                                 markupsCurveNode.GetID())
        moveNodeToHeartValveFolder(valveNodeItemId, markupsCurveNode, 'LeafletSurfaceEdit')

      leafletSurfaceEditFolderId = shNode.GetItemChildWithName(valveNodeItemId, "LeafletSurfaceEdit")
      if leafletSurfaceEditFolderId:
        children = vtk.vtkCollection()
        shNode.GetDataNodesInBranch(leafletSurfaceEditFolderId, children)
        for childIdx in range(children.GetNumberOfItems()):
          child = children.GetItemAsObject(childIdx)
          if type(child) in [slicer.vtkMRMLMarkupsFiducialNode, slicer.vtkMRMLModelNode]:
            slicer.mrmlScene.RemoveNode(child)

      leafletSurfaceFolderId = shNode.GetItemChildWithName(valveNodeItemId, "LeafletSurface")
      segmentationNode = scriptedModuleNode.GetNodeReference("LeafletSegmentation")
      segmentIds = [segmentId for segmentId in getAllSegmentIDs(segmentationNode) if segmentId != VALVE_MASK_SEGMENT_ID]
      if leafletSurfaceFolderId:
        children = vtk.vtkCollection()
        shNode.GetDataNodesInBranch(leafletSurfaceFolderId, children)
        for childIdx in range(children.GetNumberOfItems()):
          child = children.GetItemAsObject(childIdx)
          if not child.GetAttribute('SegmentID') in segmentIds:
            slicer.mrmlScene.RemoveNode(child)


def updateLegacyCoaptationModelNodes(scriptedModuleNodes):
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  for scriptedModuleNode in scriptedModuleNodes:
    logging.debug(f"updateLegacyCoaptationModelNodes for {scriptedModuleNode.GetName()}")

    valveNodeItemId = shNode.GetItemByDataNode(scriptedModuleNode)
    numCoaptationBaseLineModels = scriptedModuleNode.GetNumberOfNodeReferences("CoaptationBaseLineModel")
    numCoaptationMarginLineModels = scriptedModuleNode.GetNumberOfNodeReferences("CoaptationMarginLineModel")
    if numCoaptationBaseLineModels > 0 and numCoaptationMarginLineModels > 0:
      for coaptationModelIndex in range(scriptedModuleNode.GetNumberOfNodeReferences("CoaptationBaseLineModel")):
        marginLineModelNode = scriptedModuleNode.GetNthNodeReference("CoaptationMarginLineModel", coaptationModelIndex)
        marginLineMarkupNode = scriptedModuleNode.GetNthNodeReference("CoaptationMarginLineMarkup", coaptationModelIndex)
        newMarginLineMarkupsCurveNode = \
          markupsCurveFromMarkupsFiducialNode(marginLineMarkupNode, markupsClass=slicer.vtkMRMLMarkupsCurveNode,
                                              displayNode=marginLineModelNode.GetDisplayNode())
        scriptedModuleNode.SetNthNodeReferenceID("CoaptationMarginLineMarkup", coaptationModelIndex,
                                                 newMarginLineMarkupsCurveNode.GetID())
        moveNodeToHeartValveFolder(valveNodeItemId, newMarginLineMarkupsCurveNode, 'CoaptationEdit')

        baseLineModelNode = scriptedModuleNode.GetNthNodeReference("CoaptationBaseLineModel", coaptationModelIndex)
        baseLineMarkupNode = scriptedModuleNode.GetNthNodeReference("CoaptationBaseLineMarkup", coaptationModelIndex)
        newBaseLineMarkupsCurveNode = \
          markupsCurveFromMarkupsFiducialNode(baseLineMarkupNode, markupsClass=slicer.vtkMRMLMarkupsCurveNode,
                                              displayNode=baseLineModelNode.GetDisplayNode())
        scriptedModuleNode.SetNthNodeReferenceID("CoaptationBaseLineMarkup", coaptationModelIndex,
                                                 newBaseLineMarkupsCurveNode.GetID())
        moveNodeToHeartValveFolder(valveNodeItemId, newBaseLineMarkupsCurveNode, 'CoaptationEdit')

    coaptationEditFolderId = shNode.GetItemChildWithName(valveNodeItemId, "CoaptationEdit")
    if coaptationEditFolderId:
      children = vtk.vtkCollection()
      shNode.GetDataNodesInBranch(coaptationEditFolderId, children)
      for childIdx in range(children.GetNumberOfItems()):
        child = children.GetItemAsObject(childIdx)
        if type(child) in [slicer.vtkMRMLMarkupsFiducialNode, slicer.vtkMRMLModelNode]:
          slicer.mrmlScene.RemoveNode(child)


def ensureLeafletVolumeAssociatedWithSegmentations(scriptedModuleNodes):
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  for scriptedModuleNode in scriptedModuleNodes:
    valveNodeItemId = shNode.GetItemByDataNode(scriptedModuleNode)
    valveModel = getValveModel(scriptedModuleNode)
    if not valveModel:
      continue

    getOrSetValveVolumeNode(valveModel)

    annulusLabelsMarkupNode = valveModel.getAnnulusLabelsMarkupNode()
    if annulusLabelsMarkupNode:
      annulusLabelsMarkupNode.SetLocked(True)

    # ensure heart valve is parent in subject hierarchy
    segNode = valveModel.getLeafletSegmentationNode()
    shNode.SetItemParent(shNode.GetItemByDataNode(segNode), valveNodeItemId)

    # ensure master volume node of segmentation is not the sequence proxy and was extracted from the set frame index
    if valveModel.getValveVolumeSequenceIndex() < 0:
      logging.warning(f"No ValveVolumeSequenceIndex set for HeartValve with name {scriptedModuleNode.GetName()}")
      continue

    fixedVolumeNode = valveModel.getLeafletVolumeNode()
    if fixedVolumeNode is not None:
      goToAnalyzedFrame(valveModel)
      volumeNode = getOrSetValveVolumeNode(valveModel)
      import numpy as np
      if not np.array_equal(slicer.util.array(volumeNode.GetID()),
                            slicer.util.array(fixedVolumeNode.GetID())):
        slicer.mrmlScene.RemoveNode(fixedVolumeNode)
        fixedVolumeNode = None

    if fixedVolumeNode is None :
      useCurrentValveVolumeAsLeafletVolume(valveModel)

    valveModel.updateValveNodeNames()
    fixedVolumeNode = valveModel.getLeafletVolumeNode()
    segNode.SetNodeReferenceID(segNode.GetReferenceImageGeometryReferenceRole(), fixedVolumeNode.GetID())
    logging.debug(f'Setting LeafletVolume for {valveModel.heartValveNode.GetName()} '
                  f'to ({valveModel.getValveVolumeSequenceIndex()} + 1)')

def moveNodeToHeartValveFolder(valveNodeItemId, node, subfolderName=None):
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  if subfolderName:
    folderItemId = shNode.GetItemChildWithName(valveNodeItemId, subfolderName)
    if not folderItemId:
      folderItemId = shNode.CreateFolderItem(valveNodeItemId, subfolderName)
  else:
    folderItemId = valveNodeItemId
  shNode.SetItemParent(shNode.GetItemByDataNode(node), folderItemId)


def getPlaneIntersectionPoint(axialNode, ortho1Node, ortho2Node):
  """
  Compute the center of rotation (common intersection point of the three planes)
  http://mathworld.wolfram.com/Plane-PlaneIntersection.html
  Copied from ValveViewLogic to remove dependency on SlicerHeart extension.
  """

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


def removeUnusedVolumeNodes():
  valveVolumes = []
  for scriptedModuleNode in slicer.util.getNodesByClass('vtkMRMLScriptedModuleNode'):
    if scriptedModuleNode.GetAttribute("ModuleName") != "HeartValve":
      continue
    valveModel = getValveModel(scriptedModuleNode)
    segmentedVolume = valveModel.getLeafletVolumeNode()
    if segmentedVolume is not None:
      valveVolumes.append(segmentedVolume)
    valveVolume = valveModel.getValveVolumeNode()
    if valveVolume is not None:
      valveVolumes.append(valveVolume)
  volumeNodes = slicer.util.getNodesByClass('vtkMRMLScalarVolumeNode')
  parentless = set(volumeNodes) - set(valveVolumes)
  for volumeNode in parentless:
    slicer.mrmlScene.RemoveNode(volumeNode)


def setMarkupPlaceModeToUnconstrained(markupsNode):
  """In Slicer-4.11, markups would snap to surface, which would interfere with curve drawing.
  This function restores Slicer.-4.10 behavior of not snapping markups to visible surface.
  """
  if not markupsNode or not markupsNode.GetScene():
    return
  markupsNode.CreateDefaultDisplayNodes()
  markupsNode.GetDisplayNode().SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeUnconstrained)
