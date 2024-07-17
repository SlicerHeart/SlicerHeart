#
#   HeartValveModel.py: Stores valve model data, quantifies properties, and creates displayable models
#

import vtk, slicer
import LeafletModel
import CoaptationModel
import PapillaryModel
import ValveRoi
import logging
import HeartValves
import Constants
from helpers import getBinaryLabelmapRepresentation


class ValveModel:

    ANNULUS_CONTOUR_MARKUP_SCALE = 1.3
    ANNULUS_CONTOUR_RADIUS = 0.5

    def __init__(self):
      self._heartValveNode = None

      # Computes a cylindrical ROI based on the annulus contour.
      # When annulus contour is created then it will be set in the valveRoi
      self.valveRoi = ValveRoi.ValveRoi()

      # List of LeafletModel objects, one for each leaflet segment
      self.leafletModels = []

      # List of CoaptationModel objects, one for each coaptation surface
      self.coaptationModels = []

      # List of PapillaryModel objects, one for each papillary muscle
      self.papillaryModels = []

      self.metricsResults = {}

      self.cardiacCyclePhasePresets = Constants.CARDIAC_CYCLE_PHASE_PRESETS

    @property
    def heartValveNode(self):
      """:returns Parameter node storing all information related to this valve (vtkMRMLScriptedModuleNode)."""
      return self._heartValveNode

    @heartValveNode.setter
    def heartValveNode(self, node):
      if self._heartValveNode == node:
        # no change
        return
      self._heartValveNode = node
      if self._heartValveNode:
        self.setHeartValveNodeDefaults()
        # Update parameters and references

        self.annulusContourCurveNode = self._heartValveNodeReferencedProxyNode("AnnulusContourPoints", forDisplayedHeartValvePhase=False)
        self.annulusContourRadius = self.annulusContourRadius

        self.valveLabelsNode = self.valveLabelsNode
        self.valveRoiModelNode = self.valveRoiModelNode

    @property
    def valveBrowserNode(self):
      """:returns Valve browser node that contains analyzed time points.
      It may be just one time point, 4 time points (MS, ES, MD, ED), or a range of time points corresponding
      to a complete heart cycle."""
      if not self.heartValveNode:
        raise RuntimeError("getValveBrowserNode failed: invalid self.heartValveNode")
      valveBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(self.heartValveNode)
      return valveBrowserNode

    @property
    def valveBrowser(self):
      """:returns Valve browser helper object for the valve browser node."""
      valveBrowserNode = self.valveBrowserNode
      if not valveBrowserNode:
        raise RuntimeError("get valveBrowser failed: invalid valveBrowserNode")
      valveBrowser = HeartValves.getValveBrowser(valveBrowserNode)
      return valveBrowser

    @property
    def annulusContourCurveSequenceNode(self):
      return self._heartValveNodeReferencedSequenceNode("AnnulusContourPoints")

    @property
    def annulusContourCurveNode(self):
      """:returns Markup closed curve storing the annulus contour"""
      return self._heartValveNodeReferencedProxyNode("AnnulusContourPoints", forDisplayedHeartValvePhase=True)

    @annulusContourCurveNode.setter
    def annulusContourCurveNode(self, annulusContourMarkupNode):
      if not self.heartValveNode:
        logging.error("set annulusContourCurveNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("AnnulusContourPoints",
                                             annulusContourMarkupNode.GetID() if annulusContourMarkupNode else None)
      self.applyProbeToRasTransformToNode(annulusContourMarkupNode)
      if annulusContourMarkupNode:
        self.moveNodeToHeartValveFolder(annulusContourMarkupNode)
        self.valveBrowser.makeTimeSequence(annulusContourMarkupNode)
      self.valveRoi.setAnnulusContourCurve(annulusContourMarkupNode)

    @property
    def annulusContourRadius(self):
      """:returns Radius of the annulus contour."""
      radiusStr = self.heartValveNode.GetAttribute("AnnulusContourRadius")
      return float(radiusStr) if radiusStr else None

    @annulusContourRadius.setter
    def annulusContourRadius(self, radius):
      if not self.heartValveNode:
        logging.error("set annulusModelRadius failed: invalid heartValveNode")
        return
      self.heartValveNode.SetAttribute("AnnulusContourRadius",str(radius))

      if self.annulusContourCurveNode:
        ValveModel.setLineDiameter(self.annulusContourCurveNode, radius*2)
        ValveModel.setGlyphSize(self.annulusContourCurveNode, radius*self.ANNULUS_CONTOUR_MARKUP_SCALE*2)
      if self.valveLabelsNode:
        ValveModel.setGlyphSize(self.valveLabelsNode, radius*self.ANNULUS_CONTOUR_MARKUP_SCALE*3)

    @property
    def valveLabelsNode(self):
      """:returns Markup point list storing labeled landmark points. The points may or may not be on the annulus contour."""
      return self.heartValveNode.GetNodeReference("AnnulusLabelsPoints") if self.heartValveNode else None

    @valveLabelsNode.setter
    def valveLabelsNode(self, labelsMarkupPointsNode):
      if not self.heartValveNode:
        logging.error("set valveLabelsNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("AnnulusLabelsPoints",
                                             labelsMarkupPointsNode.GetID() if labelsMarkupPointsNode else None)
      self.applyProbeToRasTransformToNode(labelsMarkupPointsNode)

      if labelsMarkupPointsNode:
        self.valveBrowser.makeTimeSequence(labelsMarkupPointsNode)
        self.moveNodeToHeartValveFolder(labelsMarkupPointsNode)

    @property
    def valveLabelsSequenceNode(self):
      return self._heartValveNodeReferencedSequenceNode("AnnulusLabelsPoints")

    @property
    def valveRoiModelNode(self):
      """:returns Model node that displays the valve ROI."""
      return self._heartValveNodeReferencedProxyNode("ValveRoiModel", forDisplayedHeartValvePhase=True)

    @valveRoiModelNode.setter
    def valveRoiModelNode(self, modelNode):
      if not self.heartValveNode:
        logging.error("setValveRoiModelNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("ValveRoiModel", modelNode.GetID() if modelNode else None)
      self.applyProbeToRasTransformToNode(modelNode)
      self.valveRoi.setRoiModelNode(modelNode)
      if modelNode:
        self.moveNodeToHeartValveFolder(modelNode)
        self.valveBrowser.makeTimeSequence(modelNode)

    @property
    def valveRoiSequenceNode(self):
      return self._heartValveNodeReferencedSequenceNode("ValveRoiModel")

    @property
    def leafletVolumeSequenceNode(self):
      return self._heartValveNodeReferencedSequenceNode("LeafletVolume")

    @property
    def leafletVolumeNode(self):
      """:returns Volume that is used for leaflet segmentation (to generate leafletSegmentationNode).
      It is typically isotropic and higher resolution than the original volume."""
      return self._heartValveNodeReferencedProxyNode("LeafletVolume", forDisplayedHeartValvePhase=True)

    @leafletVolumeNode.setter
    def leafletVolumeNode(self, leafletVolumeNode):
      if not self.heartValveNode:
        logging.error("setLeafletVolumeNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("LeafletVolume",
                                             leafletVolumeNode.GetID() if leafletVolumeNode else None)
      self.applyProbeToRasTransformToNode(leafletVolumeNode)
      if leafletVolumeNode:
        self.moveNodeToHeartValveFolder(leafletVolumeNode)
        self.valveBrowser.makeTimeSequence(leafletVolumeNode)

    @property
    def leafletSegmentationSequenceNode(self):
      return self._heartValveNodeReferencedSequenceNode("LeafletSegmentation")

    def isNodeSpecifiedForCurrentTimePoint(self, proxyNode):
      sequenceNode = self.valveBrowserNode.GetSequenceNode(proxyNode)
      if not sequenceNode:
        return False
      valveItemIndex, indexValue = self.valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()
      if not indexValue:
        return False
      itemNumber = sequenceNode.GetItemNumberFromIndexValue(indexValue)
      if itemNumber < 0:
        return False
      return True

    def _heartValveNodeReferencedSequenceNode(self, referenceRole):
      referencedNode = self._heartValveNodeReferencedProxyNode(referenceRole, forDisplayedHeartValvePhase=False)
      if not referencedNode:
        return None
      referencedSequenceNode = self.valveBrowserNode.GetSequenceNode(referencedNode)
      return referencedSequenceNode

    def _heartValveNodeReferencedProxyNode(self, referenceRole, forDisplayedHeartValvePhase):
      """Get node referenced from the heartValveNode
      :param forDisplayedHeartValvePhase specifies if the referenced proxy node of the currently displayed
         heart valve index should be returned. If False then the current referenced node
         is returned, regardless of the proxy node is specified for the current heart valve phase.
      :returns Referenced node
      """
      referencedProxyNode = self.heartValveNode.GetNodeReference(referenceRole) if self.heartValveNode else None
      if (not forDisplayedHeartValvePhase) or (not referencedProxyNode):
        # No need to check if it is for the displayed heart valve phase
        return referencedProxyNode
      # Check if segmentation is available for the current heart valve phase
      if not self.isNodeSpecifiedForCurrentTimePoint(referencedProxyNode):
        return None
      return referencedProxyNode

    @property
    def leafletSegmentationNode(self):
      """Get leaflet segmentation node
      :returns Segmentation node storing each valve leaflet as a segment
      """
      return self._heartValveNodeReferencedProxyNode("LeafletSegmentation", forDisplayedHeartValvePhase=True)

    @leafletSegmentationNode.setter
    def leafletSegmentationNode(self, segmentationNode):
      if not self.heartValveNode:
        logging.error("setLeafletSegmentationNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("LeafletSegmentation",
                                             segmentationNode.GetID() if segmentationNode else None)
      self.applyProbeToRasTransformToNode(segmentationNode)
      if segmentationNode:
        self.moveNodeToHeartValveFolder(segmentationNode)
        self.valveBrowser.makeTimeSequence(segmentationNode)
      self.updateLeafletModelsFromSegmentation()
      self.updateCoaptationModels()

    def setHeartValveNodeDefaults(self):
      """Initialize HeartValveNode with defaults. Already defined values are not changed."""

      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      if self.heartValveNode.GetHideFromEditors():
        self.heartValveNode.SetHideFromEditors(False)
        shNode.RequestOwnerPluginSearch(self.heartValveNode)
        shNode.SetItemAttribute(shNode.GetItemByDataNode(self.heartValveNode), "ModuleName", "HeartValve")

      if not self.annulusContourRadius:
        self.setAnnulusContourRadius(self.ANNULUS_CONTOUR_RADIUS)

      if self.getValveVolumeSequenceIndex() < 0:
        self.setValveVolumeSequenceIndex(-1)  # by default it is set to -1 (undefined)

      if self.valveLabelsNode is None:
        self.valveLabelsNode = self.createAnnulusLabelsMarkupNode()

      # Initialize to default value (if not set to some other value already)
      self.getCardiacCyclePhase()

    def initializeNewTimePoint(self):
      """This method is called after a new time point is added."""
      # By default all properties are copied from the previous time point.
      # The cardiac cycle phase is unique, so reset it to "unknown".
      self.setCardiacCyclePhase("unknown")
      annulusContourMarkupsNode = self.annulusContourCurveNode
      if annulusContourMarkupsNode:
        annulusContourMarkupsNode.RemoveAllControlPoints()
        self.storeAnnulusContour()

    def moveNodeToHeartValveFolder(self, node, subfolderName=None):
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      valveNodeItemId = shNode.GetItemByDataNode(self.heartValveNode)
      if subfolderName:
        folderItemId = shNode.GetItemChildWithName(valveNodeItemId, subfolderName)
        if not folderItemId:
          folderItemId = shNode.CreateFolderItem(valveNodeItemId, subfolderName)
      else:
        folderItemId = valveNodeItemId
      shNode.SetItemParent(shNode.GetItemByDataNode(node), folderItemId)

    def getDisplayedValveVolumeSequenceIndex(self):
      """Get currently displayed item index of valve volume sequence"""
      volumeNode = self.getValveVolumeNode()
      if not volumeNode:
        return 0
      import HeartValveLib
      volumeSequenceBrowserNode = HeartValveLib.getSequenceBrowserNodeForMasterOutputNode(volumeNode)
      if not volumeSequenceBrowserNode:
        logging.warning("Volume sequence node has no browser node")
        return 0
      return volumeSequenceBrowserNode.GetSelectedItemNumber()

    def applyProbeToRasTransformToNode(self, nodeToApplyTo=None):
      if nodeToApplyTo is not None:
        probeToRasTransformNode = self.valveBrowser.probeToRasTransformNode
        nodeToApplyTo.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

    def onProbeToRasTransformNodeChanged(self):
      # Called when a different node is set as probeToRasTransform
      if not self.heartValveNode:
        return

      # Put valve under probeToRas transform (Probe coordinate system)
      self.applyProbeToRasTransformToNode(self.annulusContourCurveNode)
      self.applyProbeToRasTransformToNode(self.valveLabelsNode)
      self.applyProbeToRasTransformToNode(self.valveRoiModelNode)
      self.applyProbeToRasTransformToNode(self.leafletSegmentationNode)
      self.applyProbeToRasTransformToNode(self.leafletVolumeNode)

      # Update parent transform in leaflet surface models
      self.updateLeafletModelsFromSegmentation()
      self.updateCoaptationModels()

    def createAnnulusCurveNode(self):
      markupsLogic = slicer.modules.markups.logic()
      annulusMarkupNode = markupsLogic.AddNewMarkupsNode('vtkMRMLMarkupsClosedCurveNode')
      annulusMarkupNode.SetNumberOfPointsPerInterpolatingSegment(20)
      annulusMarkupNode.SetName(slicer.mrmlScene.GetUniqueNameByString("AnnulusContourMarkup"))
      # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
      annulusMarkupNode.SetMarkupLabelFormat("")
      displayNode = annulusMarkupNode.GetDisplayNode()
      displayNode.SetSelectedColor(self.getBaseColor())
      displayNode.SetColor(self.getBaseColor())
      displayNode.SetPropertiesLabelVisibility(False)
      ValveModel.setLineDiameter(annulusMarkupNode, self.ANNULUS_CONTOUR_RADIUS*2)
      ValveModel.setGlyphSize(annulusMarkupNode, self.ANNULUS_CONTOUR_RADIUS*self.ANNULUS_CONTOUR_MARKUP_SCALE*2)
      self.moveNodeToHeartValveFolder(annulusMarkupNode)
      return annulusMarkupNode

    def createAnnulusLabelsMarkupNode(self):
      markupsLogic = slicer.modules.markups.logic()
      annulusMarkupNodeId = markupsLogic.AddNewFiducialNode()
      annulusMarkupNode = slicer.mrmlScene.GetNodeByID(annulusMarkupNodeId)
      annulusMarkupNode.SetName(slicer.mrmlScene.GetUniqueNameByString("AnnulusLabelsMarkup"))
      annulusMarkupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
      annulusMarkupNode.SetLocked(True) # prevent accidental changes
      self.moveNodeToHeartValveFolder(annulusMarkupNode)
      ValveModel.setGlyphSize(annulusMarkupNode, self.ANNULUS_CONTOUR_RADIUS*self.ANNULUS_CONTOUR_MARKUP_SCALE*3)
      return annulusMarkupNode

    def getVolumeSequenceIndexAsDisplayedString(self, volumeSequenceIndex):
      if volumeSequenceIndex < 0:
        return "NA"  # not available
      # sequence index is 0-based but it is displayed as 1-based
      return str(volumeSequenceIndex + 1)

    def getValveVolumeSequenceIndex(self):
      """"Get item index of analyzed valve volume in the volume sequence. Returns -1 if index value is undefined."""
      valveBrowser = self.valveBrowser
      valveItemIndex, indexValue = valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()
      if indexValue is None:
        # no time points in the valve sequence
        return -1
      volumeSequenceNode = valveBrowser.volumeSequenceNode
      if not volumeSequenceNode:
        # no volume sequence is selected
        return -1
      volumeIndex = volumeSequenceNode.GetItemNumberFromIndexValue(indexValue)
      return volumeIndex

    def setValveVolumeSequenceIndex(self, index):
      if not self.heartValveNode:
        logging.error("setValveVolumeSequenceIndex failed: invalid heartValveNode")
        return
      self.heartValveNode.SetAttribute("ValveVolumeSequenceIndex", str(index))
      self.updateValveNodeNames()

    def createValveRoiModelNode(self):
      modelsLogic = slicer.modules.models.logic()
      polyData = vtk.vtkPolyData()
      modelNode = modelsLogic.AddModel(polyData)
      modelNode.SetName(slicer.mrmlScene.GetUniqueNameByString("ValveRoiModel"))
      self.moveNodeToHeartValveFolder(modelNode)
      modelNode.GetDisplayNode().SetColor(0, 0, 1)
      modelNode.GetDisplayNode().SetVisibility(False)
      modelNode.GetDisplayNode().SetVisibility2D(True)
      modelNode.GetDisplayNode().SetOpacity(0.1)
      modelNode.GetDisplayNode().BackfaceCullingOff()

      self.valveRoiModelNode = modelNode

      return modelNode  # Annulus contour line

    def createLeafletSegmentationNode(self):
      segmentationNode = slicer.vtkMRMLSegmentationNode()
      segmentationNode.SetName("LeafletSegmentation")
      slicer.mrmlScene.AddNode(segmentationNode)
      segmentationNode.CreateDefaultDisplayNodes()
      self.moveNodeToHeartValveFolder(segmentationNode)
      self.updateValveNodeNames()
      return segmentationNode

    def removePapillaryModel(self, papillaryModelIndex):
      papillaryModel = self.papillaryModels[papillaryModelIndex]
      papillaryLineMarkupNode = self.heartValveNode.GetNthNodeReference("PapillaryLineMarkup", papillaryModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("PapillaryLineMarkup", papillaryModelIndex)
      self.papillaryModels.remove(papillaryModel)
      slicer.mrmlScene.RemoveNode(papillaryLineMarkupNode)

    def updatePapillaryModel(self, papillaryModelIndex=-1):
      if papillaryModelIndex < 0:
        papillaryModelIndex = len(self.papillaryModels)
      if papillaryModelIndex<len(self.papillaryModels):
        papillaryModel = self.papillaryModels[papillaryModelIndex]
      else:
        papillaryModel = PapillaryModel.PapillaryModel()
        self.papillaryModels.append(papillaryModel)

      papillaryLineMarkupNode = self.heartValveNode.GetNthNodeReference("PapillaryLineMarkup", papillaryModelIndex)
      if papillaryLineMarkupNode:
        papillaryMuscleName = papillaryLineMarkupNode.GetName().replace(" papillary muscle", "")
      else:
        papillaryMuscleName = self.valveTypePreset["papillaryNames"][papillaryModelIndex]
      if not papillaryLineMarkupNode:
        markupNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode')
        #markupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
        markupNode.SetLocked(True) # prevent accidental changes
        self.moveNodeToHeartValveFolder(markupNode, 'PapillaryMuscles')
        self.heartValveNode.SetNthNodeReferenceID("PapillaryLineMarkup", papillaryModelIndex, markupNode.GetID())
        papillaryLineMarkupNode = markupNode

      papillaryLineMarkupNode.SetName(f"{papillaryMuscleName} papillary muscle")
      self.applyProbeToRasTransformToNode(papillaryLineMarkupNode)
      annulusContourMarkupsNode = self.annulusContourCurveNode
      ValveModel.setGlyphSize(papillaryLineMarkupNode, papillaryModel.markupGlyphScale)
      papillaryLineMarkupNode.GetDisplayNode().SetSelectedColor(annulusContourMarkupsNode.GetDisplayNode().GetSelectedColor())
      papillaryModel.setPapillaryLineMarkupNode(papillaryLineMarkupNode)

      return papillaryModel

    def findPapillaryModel(self, papillaryLineMarkupsNode):
      for papillaryModel in self.papillaryModels:
        if papillaryModel.getPapillaryLineMarkupNode() == papillaryLineMarkupsNode:
          return papillaryModel
      # Not found
      return None

    def updatePapillaryModels(self):
      papillaryMuscleNames = self.valveTypePreset["papillaryNames"]
      numberOfPapillaryModels = len(papillaryMuscleNames)

      # Remove all orphan papillary models
      while len(self.papillaryModels)>numberOfPapillaryModels:
        self.removePapillaryModel(len(self.papillaryModels)-1)

      # Add any missing papillary models and update existing ones
      for papillaryModelIndex in range(numberOfPapillaryModels):
        self.updatePapillaryModel(papillaryModelIndex)

    def removeLeafletNodeReference(self, referenceRole, segmentId):
      if not self.heartValveNode:
        logging.error("removeLeafletNodeReference failed: invalid heartValveNode")
        return
      numberOfReferences = self.heartValveNode.GetNumberOfNodeReferences(referenceRole)
      for referenceIndex in range(numberOfReferences):
        referencedNode = self.heartValveNode.GetNthNodeReference(referenceRole, referenceIndex)
        if referencedNode is not None and referencedNode.GetAttribute('SegmentID') == segmentId:
          self.heartValveNode.RemoveNthNodeReferenceID(referenceRole, referenceIndex)

    def getLeafletNodeReference(self, referenceRole, segmentId):
      if not self.heartValveNode:
        logging.error("getLeafletNodeReference failed: invalid heartValveNode")
        return None
      numberOfReferences = self.heartValveNode.GetNumberOfNodeReferences(referenceRole)
      for referenceIndex in range(numberOfReferences):
        referencedNode = self.heartValveNode.GetNthNodeReference(referenceRole, referenceIndex)
        if referencedNode is not None and referencedNode.GetAttribute('SegmentID') == segmentId:
          return referencedNode
      # not found
      return None

    def setLeafletNodeReference(self, referenceRole, segmentId, node):
      if not self.heartValveNode:
        logging.error("setLeafletNodeReference failed: invalid heartValveNode")
        return None

      numberOfReferences = self.heartValveNode.GetNumberOfNodeReferences(referenceRole)
      existingReferenceUpdated = False
      for referenceIndex in range(numberOfReferences):
        referencedNode = self.heartValveNode.GetNthNodeReference(referenceRole, referenceIndex)
        if referencedNode is not None and referencedNode.GetAttribute('SegmentID') == segmentId:
          self.heartValveNode.SetNthNodeReferenceID(referenceRole, referenceIndex, node.GetID() if node else None)
          existingReferenceUpdated = True
          break

      if node:
        if not existingReferenceUpdated:
          self.heartValveNode.AddNodeReferenceID(referenceRole, node.GetID())
        node.SetAttribute("SegmentID", segmentId)

    def findLeafletModel(self, segmentId):
      for leafletModel in self.leafletModels:
        if leafletModel.segmentId == segmentId:
          return leafletModel
      return None

    def removeLeafletModel(self, segmentId):
      for leafletModel in self.leafletModels:
        if leafletModel.segmentId == segmentId:
          self.removeLeafletNodeReference("LeafletSurfaceModel", segmentId)
          self.removeLeafletNodeReference("LeafletSurfaceBoundaryMarkup", segmentId)
          self.leafletModels.remove(leafletModel)
          return

    def addLeafletModel(self, segmentId):
      leafletModel = self.findLeafletModel(segmentId)
      if not leafletModel:
        leafletModel = LeafletModel.LeafletModel()
        self.leafletModels.append(leafletModel)

      segmentationNode = self.leafletSegmentationNode
      leafletModel.setSegmentationNode(segmentationNode)
      leafletModel.setSegmentId(segmentId)

      segmentName = segmentationNode.GetSegmentation().GetSegment(segmentId).GetName()
      segmentColor = segmentationNode.GetSegmentation().GetSegment(segmentId).GetColor()

      leafletSurfaceModelNode = self.getLeafletNodeReference("LeafletSurfaceModel", segmentId)
      if not leafletSurfaceModelNode:
        modelsLogic = slicer.modules.models.logic()
        polyData = vtk.vtkPolyData()
        modelNode = modelsLogic.AddModel(polyData)
        modelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(segmentName+"SurfaceModel"))
        self.moveNodeToHeartValveFolder(modelNode, 'LeafletSurface')
        modelNode.GetDisplayNode().SetColor(segmentColor)
        modelNode.GetDisplayNode().BackfaceCullingOff()
        modelNode.GetDisplayNode().SetVisibility2D(True)
        modelNode.GetDisplayNode().SetSliceIntersectionThickness(5)
        modelNode.GetDisplayNode().SetAmbient(0.1)
        modelNode.GetDisplayNode().SetDiffuse(0.9)
        modelNode.GetDisplayNode().SetSpecular(0.1)
        modelNode.GetDisplayNode().SetPower(10)
        self.setLeafletNodeReference("LeafletSurfaceModel", segmentId, modelNode)
        leafletSurfaceModelNode = modelNode
      self.applyProbeToRasTransformToNode(leafletSurfaceModelNode)
      leafletModel.setSurfaceModelNode(leafletSurfaceModelNode)

      leafletSurfaceBoundaryMarkupNode = self.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", segmentId)
      if not leafletSurfaceBoundaryMarkupNode:
        markupNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsClosedCurveNode')
        markupNode.SetNumberOfPointsPerInterpolatingSegment(20)
        markupNode.SetName(slicer.mrmlScene.GetUniqueNameByString(segmentName + "SurfaceBoundaryMarkup"))
        markupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
        markupNode.SetLocked(True) # prevent accidental changes
        self.moveNodeToHeartValveFolder(markupNode, 'LeafletSurfaceEdit')
        ValveModel.setGlyphSize(markupNode, leafletModel.markupGlyphScale)
        markupNode.GetDisplayNode().SetColor(0,0,1)
        self.setLeafletNodeReference("LeafletSurfaceBoundaryMarkup", segmentId, markupNode)
        leafletSurfaceBoundaryMarkupNode = markupNode
      self.applyProbeToRasTransformToNode(leafletSurfaceBoundaryMarkupNode)
      leafletModel.setSurfaceBoundaryMarkupNode(leafletSurfaceBoundaryMarkupNode)

      # Move items to folders - for legacy scenes
      self.moveNodeToHeartValveFolder(leafletSurfaceModelNode, 'LeafletSurface')
      self.moveNodeToHeartValveFolder(leafletSurfaceBoundaryMarkupNode, 'LeafletSurfaceEdit')

    def updateLeafletModelsFromSegmentation(self):
      segmentIds = []
      segmentationNode = self.leafletSegmentationNode
      if segmentationNode:
        from HeartValveLib.util import getAllSegmentIDs
        for segmentId in getAllSegmentIDs(segmentationNode):
          if segmentId == VALVE_MASK_SEGMENT_ID:
            continue
          segmentIds.append(segmentId)

      segmentIdsInLeafletModels = []
      for leafletModel in self.leafletModels:
        segmentIdsInLeafletModels.append(leafletModel.segmentId)

      # Keep only those leaflet models that have an ID that matches one of the current segments
      for segmentIdInLeafletModel in segmentIdsInLeafletModels:
        if segmentIdInLeafletModel not in segmentIds:
          # segment is deleted, remove associated leaflet model
          self.removeLeafletModel(segmentIdInLeafletModel)

      # cleanup legacy leaflet surface nodes
      numSurfaceBoundaryMarkups = self.heartValveNode.GetNumberOfNodeReferences("LeafletSurfaceBoundaryMarkup")
      for boundaryMarkupIndex in reversed(range(numSurfaceBoundaryMarkups)):
        boundaryMarkupNode = self.heartValveNode.GetNthNodeReference("LeafletSurfaceBoundaryMarkup", boundaryMarkupIndex)
        surfaceModelNode = self.heartValveNode.GetNthNodeReference("LeafletSurfaceModel", boundaryMarkupIndex)
        if not boundaryMarkupNode.GetAttribute('SegmentID') in segmentIds:
          slicer.mrmlScene.RemoveNode(boundaryMarkupNode)
          slicer.mrmlScene.RemoveNode(surfaceModelNode)

      # Add any missing leaflet models
      for segmentId in segmentIds:
        self.addLeafletModel(segmentId)

    def getCoaptationsForLeaflet(self, leafletModel):
      coaptations = []
      for coaptation in self.coaptationModels:
        connectedLeaflets = coaptation.getConnectedLeaflets(self)
        if leafletModel in connectedLeaflets:
          coaptations.append(coaptation)
      return coaptations

    def removeCoaptationModel(self, coaptationModelIndex):
      coaptationModel = self.coaptationModels[coaptationModelIndex]
      coaptationSurfaceModelNode = self.heartValveNode.GetNthNodeReference("CoaptationSurfaceModel",coaptationModelIndex)
      baseLineMarkupNode = self.heartValveNode.GetNthNodeReference("CoaptationBaseLineMarkup", coaptationModelIndex)
      marginLineMarkupNode = self.heartValveNode.GetNthNodeReference("CoaptationMarginLineMarkup", coaptationModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("CoaptationBaseLineMarkup", coaptationModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("CoaptationMarginLineMarkup", coaptationModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("CoaptationSurfaceModel", coaptationModelIndex)
      self.coaptationModels.remove(coaptationModel)
      slicer.mrmlScene.RemoveNode(coaptationSurfaceModelNode)
      slicer.mrmlScene.RemoveNode(baseLineMarkupNode)
      slicer.mrmlScene.RemoveNode(marginLineMarkupNode)

    def addCoaptationModel(self, coaptationModelIndex=-1):
      if coaptationModelIndex<0:
        coaptationModelIndex = len(self.coaptationModels)
      if coaptationModelIndex<len(self.coaptationModels):
        coaptationModel = self.coaptationModels[coaptationModelIndex]
      else:
        coaptationModel = CoaptationModel.CoaptationModel()
        self.coaptationModels.append(coaptationModel)

      namePrefix = "Coaptation{0}".format(coaptationModelIndex + 1)

      coaptationSurfaceModelNode = self.heartValveNode.GetNthNodeReference("CoaptationSurfaceModel", coaptationModelIndex)
      if not coaptationSurfaceModelNode:
        modelsLogic = slicer.modules.models.logic()
        polyData = vtk.vtkPolyData()
        modelNode = modelsLogic.AddModel(polyData)
        modelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(namePrefix+"SurfaceModel"))
        self.moveNodeToHeartValveFolder(modelNode, 'Coaptation')
        modelNode.GetDisplayNode().SetColor(0.5,1,0.5)
        modelNode.GetDisplayNode().BackfaceCullingOff()
        modelNode.GetDisplayNode().SetVisibility2D(True)
        modelNode.GetDisplayNode().SetSliceIntersectionThickness(5)
        modelNode.GetDisplayNode().SetAmbient(0.1)
        modelNode.GetDisplayNode().SetDiffuse(0.9)
        modelNode.GetDisplayNode().SetSpecular(0.1)
        modelNode.GetDisplayNode().SetPower(10)
        self.heartValveNode.SetNthNodeReferenceID("CoaptationSurfaceModel", coaptationModelIndex, modelNode.GetID())
        coaptationSurfaceModelNode = modelNode
      self.applyProbeToRasTransformToNode(coaptationSurfaceModelNode)
      coaptationModel.setSurfaceModelNode(coaptationSurfaceModelNode)

      baseLineMarkupNode = self.heartValveNode.GetNthNodeReference("CoaptationBaseLineMarkup", coaptationModelIndex)
      if not baseLineMarkupNode:
        markupNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsCurveNode")
        markupNode.SetName(slicer.mrmlScene.GetUniqueNameByString(namePrefix+"BaseLineMarkup"))
        markupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
        markupNode.SetLocked(True) # prevent accidental changes
        self.moveNodeToHeartValveFolder(markupNode, 'CoaptationEdit')
        ValveModel.setGlyphSize(markupNode, coaptationModel.markupGlyphScale)
        markupNode.GetDisplayNode().SetColor(0,0,1)
        self.heartValveNode.SetNthNodeReferenceID("CoaptationBaseLineMarkup", coaptationModelIndex, markupNode.GetID())
        baseLineMarkupNode = markupNode
      self.applyProbeToRasTransformToNode(baseLineMarkupNode)
      coaptationModel.setBaseLineMarkupNode(baseLineMarkupNode)

      marginLineMarkupNode = self.heartValveNode.GetNthNodeReference("CoaptationMarginLineMarkup", coaptationModelIndex)
      if not marginLineMarkupNode:
        markupNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsCurveNode")
        markupNode.SetName(slicer.mrmlScene.GetUniqueNameByString(namePrefix+"MarginLineMarkup"))
        markupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
        markupNode.SetLocked(True) # prevent accidental changes
        self.moveNodeToHeartValveFolder(markupNode, 'CoaptationEdit')
        ValveModel.setGlyphSize(markupNode, coaptationModel.markupGlyphScale)
        markupNode.GetDisplayNode().SetColor(0,0,1)
        # modelNode.GetDisplayNode().SetColor(1,0.5,0)
        self.heartValveNode.SetNthNodeReferenceID("CoaptationMarginLineMarkup", coaptationModelIndex, markupNode.GetID())
        marginLineMarkupNode = markupNode
      self.applyProbeToRasTransformToNode(marginLineMarkupNode)
      coaptationModel.setMarginLineMarkupNode(marginLineMarkupNode)

      coaptationModel.updateSurfaceModelName(self)
      return coaptationModel

    def findCoaptationModel(self, coaptationSurfaceNode):
      for coaptationModel in self.coaptationModels:
        if coaptationModel.surfaceModelNode == coaptationSurfaceNode:
          return coaptationModel
      # Not found
      return None

    def updateCoaptationModels(self):
      numberOfCoaptationModels = self.heartValveNode.GetNumberOfNodeReferences("CoaptationBaseLineMarkup")

      # Remove all orphan coaptation models
      while len(self.coaptationModels)>numberOfCoaptationModels:
        self.removeCoaptationModel(len(self.coaptationModels)-1)

      # Add any missing coaptation models and update existing ones
      for coaptationModelIndex in range(numberOfCoaptationModels):
        self.addCoaptationModel(coaptationModelIndex)

    def getAnnulusContourPlane(self):
      """
      Get plane position and normal of the contour. Plane normal vector points in the direction of blood flow through the valve.
      """
      import numpy as np

      interpolatedPoints = slicer.util.arrayFromMarkupsControlPoints(self.annulusContourCurveNode).T
      planePosition, planeNormal = planeFit(interpolatedPoints)


      probeToRasMatrix = vtk.vtkMatrix4x4()
      slicer.vtkMRMLTransformNode.GetMatrixTransformBetweenNodes(self.valveBrowser.probeToRasTransformNode, None, probeToRasMatrix)
      planeNormal_Probe = np.append(planeNormal, 0)
      planeNormal_Ras = probeToRasMatrix.MultiplyPoint(planeNormal_Probe)

      if self.valveTypePreset["approximateFlowDirection"] == "posterior":
        # heart posterior direction in RAS: [0,-1,0]
        approximateFlowDirection_Ras = [0,-1,0]
      else:
        # heart anterior direction in RAS: [0,1,0]
        approximateFlowDirection_Ras = [0,1,0]

      # Make sure plane normal direction is approximately the same as flow direction
      if np.dot(approximateFlowDirection_Ras, planeNormal_Ras[0:3]) < 0:
        planeNormal = -planeNormal

      return planePosition, planeNormal

    def resampleAnnulusContourMarkups(self, samplingDistance):
      self.annulusContourCurveNode.ResampleCurveWorld(samplingDistance)

    def smoothAnnulusContour(self, numberOfFourierCoefficients, samplingDistance):
      from HeartValveLib.util import smoothCurveFourier
      wasModify = self.annulusContourCurveNode.StartModify()
      smoothCurveFourier(self.annulusContourCurveNode, numberOfFourierCoefficients, samplingDistance)
      self.annulusContourCurveNode.EndModify(wasModify)

    def hasStoredAnnulusContour(self):
      if not self.annulusContourCurveNode:
        return None
      return self.annulusContourCurveNode.GetAttribute("AnnulusContourCoordinates") is not None

    def storeAnnulusContour(self):
      arr = slicer.util.arrayFromMarkupsControlPoints(self.annulusContourCurveNode)
      self.annulusContourCurveNode.SetAttribute("AnnulusContourCoordinates", str(arr.tobytes()))

    def restoreAnnulusContour(self):
      originalPoints = self.annulusContourCurveNode.GetAttribute("AnnulusContourCoordinates")
      if not originalPoints:
        return
      import numpy as np
      arr = np.frombuffer(eval(originalPoints), dtype=np.float64)
      wasModify = self.annulusContourCurveNode.StartModify()
      slicer.util.updateMarkupsControlPointsFromArray(self.annulusContourCurveNode, arr.reshape(-1, 3))
      self.annulusContourCurveNode.EndModify(wasModify)

    def setNonLabeledMarkupsVisibility(self, visible, unselectAll = True):
      annulusMarkupNode = self.annulusContourCurveNode
      if not annulusMarkupNode:
        return
      try:
        # Slicer-4.13 (February 2022) and later
        numberOfControlPoints = annulusMarkupNode.GetNumberOfControlPoints()
      except:
        # fall back to older API
        numberOfControlPoints = annulusMarkupNode.GetNumberOfFiducials()
      wasModify = annulusMarkupNode.StartModify()
      for i in range(0, numberOfControlPoints):
        if not annulusMarkupNode.GetNthControlPointLabel(i):
          annulusMarkupNode.SetNthControlPointVisibility(i, visible)
        if unselectAll and annulusMarkupNode.GetNthControlPointSelected(i):
          annulusMarkupNode.SetNthControlPointSelected(i, False)
      annulusMarkupNode.EndModify(wasModify)

    def getAllMarkupLabels(self):
      """Get a list of all annulus point labels"""
      labels = []
      annulusMarkupNode = self.valveLabelsNode
      numberOfControlPoints = annulusMarkupNode.GetNumberOfControlPoints()
      for i in range(0, numberOfControlPoints):
        try:
          # Slicer-4.13 (February 2022) and later
          label = annulusMarkupNode.GetNthControlPointLabel(i)
        except:
          # fall back to older API
          label = annulusMarkupNode.GetNthFiducialLabel(i)
        if label:
          labels.append(label)
      return labels

    def getAnnulusLabelsMarkupIndexByLabel(self, label):
      annulusMarkupNode = self.valveLabelsNode
      try:
        # Slicer-4.13 (February 2022) and later
        numberOfControlPoints = annulusMarkupNode.GetNumberOfControlPoints()
      except:
        # fall back to older API
        numberOfControlPoints = annulusMarkupNode.GetNumberOfFiducials()
      labelStripped = label.strip()
      for i in range(0, numberOfControlPoints):
        try:
          # Slicer-4.13 (February 2022) and later
          label = annulusMarkupNode.GetNthControlPointLabel(i)
        except:
          # fall back to older API
          label = annulusMarkupNode.GetNthFiducialLabel(i)
        if label.strip()==labelStripped:
          return i
      # not found
      return -1

    def getAnnulusMarkupPositionByLabel(self, label):
      import numpy as np
      annulusMarkupIndex = self.getAnnulusLabelsMarkupIndexByLabel(label)
      if annulusMarkupIndex < 0:
        return None
      pos = [0,0,0]
      try:
        # Current API (Slicer-4.13 February 2022)
        self.valveLabelsNode.GetNthControlPointPosition(annulusMarkupIndex, pos)
      except:
        # Legacy API
        self.valveLabelsNode.GetNthFiducialPosition(annulusMarkupIndex, pos)
      return np.array(pos)

    def getAnnulusMarkupPositionsByLabels(self, labels):
      return [self.getAnnulusMarkupPositionByLabel(label) for label in labels]

    def removeAnnulusMarkupLabel(self, label):
      annulusMarkupIndex = self.getAnnulusLabelsMarkupIndexByLabel(label)
      if annulusMarkupIndex<0:
        return
      self.valveLabelsNode.RemoveNthControlPoint(annulusMarkupIndex)

    def setAnnulusMarkupLabel(self, label, position):
      annulusMarkupIndex = self.getAnnulusLabelsMarkupIndexByLabel(label)
      if annulusMarkupIndex>=0:
        self.valveLabelsNode.SetNthControlPointPosition(annulusMarkupIndex, position[0], position[1], position[2])
      else:
        self.valveLabelsNode.AddControlPoint(vtk.vtkVector3d(position), label)

    def updateValveNodeNames(self):
      # Placeholder for now, we'll see if sequence browser can fully take care of node renames
      pass

    @property
    def probePositionPreset(self):
      # return probe position preset object for this valve
      return Constants.PROBE_POSITION_PRESETS[self.valveBrowser.probePosition]

    @property
    def valveTypePreset(self):
      # return preset object of this valve type
      return Constants.VALVE_TYPE_PRESETS[self.valveBrowser.valveType]

    def setCardiacCyclePhase(self, cardiacCyclePhase):
      if not self.heartValveNode:
        logging.error("setCardiacCyclePhase failed: invalid heartValveNode")
        return
      self.heartValveNode.SetAttribute("CardiacCyclePhase", cardiacCyclePhase)
      self.updateValveNodeNames()

      if self.annulusContourCurveNode and self.annulusContourCurveNode.GetDisplayNode():
        self.annulusContourCurveNode.GetDisplayNode().SetSelectedColor(self.getBaseColor())
        self.annulusContourCurveNode.GetDisplayNode().SetColor(self.getBaseColor())
      if self.valveLabelsNode and self.valveLabelsNode.GetDisplayNode():
        self.valveLabelsNode.GetDisplayNode().SetSelectedColor(self.getBaseColor())
        self.valveLabelsNode.GetDisplayNode().SetColor(self.getDarkColor())

    def getCardiacCyclePhase(self):
      cardiacCyclePhase = self.heartValveNode.GetAttribute("CardiacCyclePhase")
      if not cardiacCyclePhase:
        self.initializeNewTimePoint()
      return cardiacCyclePhase

    def getBaseColor(self):
      cardiacCyclePhaseColor = self.cardiacCyclePhasePresets[self.getCardiacCyclePhase()]["color"]
      return cardiacCyclePhaseColor

    def getDarkColor(self):
      cardiacCyclePhaseColor = self.cardiacCyclePhasePresets[self.getCardiacCyclePhase()]["color"]
      return [cardiacCyclePhaseColor[0]/2.0, cardiacCyclePhaseColor[1]/2.0, cardiacCyclePhaseColor[1]/2.0]

    def getAnnulusMarkupLabels(self):
      import numpy as np
      labels = self.getAllMarkupLabels()
      annulusMarkupLabels = []
      for label in labels:
        pointPositionAnnulus = self.getAnnulusMarkupPositionByLabel(label)
        from HeartValveLib.util import getClosestPointPositionAlongCurve
        closestPointPositionOnAnnulusCurve =\
          getClosestPointPositionAlongCurve(self.annulusContourCurveNode, pointPositionAnnulus)
        if np.linalg.norm(pointPositionAnnulus - closestPointPositionOnAnnulusCurve) > self.annulusContourRadius * 1.5 + 1.0:
          # it is not a label on the annulus (for example, centroid), ignore it
          continue
        annulusMarkupLabels.append(label)
      return annulusMarkupLabels

    def getAnnulusContourCurveSegments(self, splitPointLabels, splitBetweenPoints=True):
      """Split the annulus contour using labeled points
      :param splitPointLabels list of point labels ['A','L','P','S']. The order does not matter
      :param splitBetweenPoints if true then segments will be split halfway between points,
        otherwise segments will be split at each point
      :return segmentInfoSorted, sorted list of dictionaries; first item is the first label in alphabetical order
        label: label of the corresponding landmark point
        closestPointIdOnAnnulusCurve
        closestPointPositionOnAnnulusCurve
        segmentStartPointId: segment starts halfway between this and previous landmark
        segmentStartPointPosition
        segmentEndPointId: segment ends halfway between this and next landmark
        segmentEndPointPosition
        segmentLengthBefore
        segmentLengthAfter
      """
      from HeartValveLib.util import getPositionAlongCurve, getClosestPointPositionAlongCurve, getClosestCurvePointIndexToPosition
      segmentInfo = []
      for label in splitPointLabels:
        pointPositionAnnulus = self.getAnnulusMarkupPositionByLabel(label)
        segmentInfo.append({
          "pointLabel": label,
          "closestPointIdOnAnnulusCurve":
            getClosestCurvePointIndexToPosition(self.annulusContourCurveNode, pointPositionAnnulus),
          "closestPointPositionOnAnnulusCurve":
            getClosestPointPositionAlongCurve(self.annulusContourCurveNode, pointPositionAnnulus)
        })

      # Sort based on closestPointIdOnAnnulusCurve1
      segmentInfoSorted = sorted(segmentInfo, key=lambda tup: tup["closestPointIdOnAnnulusCurve"])

      # In segmentInfoSorted, labels are in order but the first label is randomly selected
      # (it can be S, A, L, P or L, P, S, A). Now we standardize the order so that the alphabetically first label
      # is the first one.
      indexOfFirstLabelInAlphabet = min(enumerate(segmentInfoSorted), key=lambda tup: tup[1]["pointLabel"])[0]
      # Rotate labels so that the order is preserved but the first one is the one that is first in the alphabet
      segmentInfoSorted = segmentInfoSorted[indexOfFirstLabelInAlphabet:] + segmentInfoSorted[:indexOfFirstLabelInAlphabet]

      # Determine split point positions and indexes
      for labelIndex in range(len(segmentInfoSorted)):
        curveSegmentStartLabel = segmentInfoSorted[labelIndex % len(segmentInfoSorted)]
        curveSegmentEndLabel = segmentInfoSorted[(labelIndex + 1) % len(segmentInfoSorted)]

        curveSegmentLength = self.annulusContourCurveNode.GetCurveLengthBetweenStartEndPointsWorld(
          curveSegmentStartLabel["closestPointIdOnAnnulusCurve"],
          curveSegmentEndLabel["closestPointIdOnAnnulusCurve"])

        if splitBetweenPoints:
          # Split halfway between start and end label
          segmentLabel = curveSegmentStartLabel["pointLabel"]
          curveSegmentDividerPointPosition = \
            getPositionAlongCurve(self.annulusContourCurveNode,
                                  curveSegmentStartLabel["closestPointIdOnAnnulusCurve"],
                                  curveSegmentLength / 2.0)
          curveSegmentDividerPointIndex = getClosestCurvePointIndexToPosition(self.annulusContourCurveNode,
                                                                              curveSegmentDividerPointPosition)
          curveSegmentDividerPointPosition = getClosestPointPositionAlongCurve(self.annulusContourCurveNode,
                                                                               curveSegmentDividerPointPosition)
          lengthAfter = curveSegmentLength / 2.0
          lengthBefore = curveSegmentLength / 2.0
        else:
          # Split at start label
          segmentLabel = curveSegmentStartLabel["pointLabel"] + "-" + curveSegmentEndLabel["pointLabel"]
          curveSegmentDividerPointIndex = \
            getClosestCurvePointIndexToPosition(self.annulusContourCurveNode,
                                                curveSegmentStartLabel["closestPointPositionOnAnnulusCurve"])
          curveSegmentDividerPointPosition = \
            getClosestPointPositionAlongCurve(self.annulusContourCurveNode,
                                              curveSegmentStartLabel["closestPointPositionOnAnnulusCurve"])
          lengthAfter = curveSegmentLength
          lengthBefore = 0

        curveSegmentStartLabel["label"] = segmentLabel
        curveSegmentStartLabel["segmentEndPointId"] = curveSegmentDividerPointIndex
        curveSegmentStartLabel["segmentEndPointPosition"] = curveSegmentDividerPointPosition
        curveSegmentStartLabel["segmentLengthAfter"] = lengthAfter
        curveSegmentEndLabel["segmentStartPointId"] = curveSegmentDividerPointIndex
        curveSegmentEndLabel["segmentStartPointPosition"] = curveSegmentDividerPointPosition
        curveSegmentEndLabel["segmentLengthBefore"] = lengthBefore

      return segmentInfoSorted

    def createValveSurface(self, planePosition, planeNormal, kernelSizeMm=2.0, mergeMode=None):
      # TODO: kernelSizeMm maybe determine this using the size (diameter?) of the annulus
      """
      Create valve surface from the union of all segmented leaflets.
      """
      if not mergeMode:
        mergeMode = slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MAX
      import vtkSegmentationCorePython as vtkSegmentationCore

      # Create a temporary segment that is a union of all existing segments
      segmentationNode = self.leafletSegmentationNode
      allLeafletsSegId = segmentationNode.GetSegmentation().AddEmptySegment()
      for leafletModel in self.leafletModels:
        leafletSegmentLabelmap = getBinaryLabelmapRepresentation(segmentationNode, leafletModel.segmentId)
        slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(
          leafletSegmentLabelmap, segmentationNode, allLeafletsSegId, mergeMode
        )

      # Apply smoothing to make sure leaflets are closed
      self.smoothSegment(self.leafletSegmentationNode, allLeafletsSegId, kernelSizeMm, smoothInZDirection=False)

      allLeafletsNumPoints = segmentationNode.GetClosedSurfaceInternalRepresentation(allLeafletsSegId).GetNumberOfPoints()

      # Temporary node, we don't add it to the scene
      allLeafletsSurfaceModelNode = slicer.vtkMRMLModelNode()
      allLeafletsSurfaceBoundaryMarkupNode = slicer.vtkMRMLMarkupsClosedCurveNode()

      allLeafletsModel = LeafletModel.LeafletModel()
      allLeafletsModel.setSegmentationNode(self.leafletSegmentationNode)
      allLeafletsModel.setSegmentId(allLeafletsSegId)
      allLeafletsModel.setSurfaceModelNode(allLeafletsSurfaceModelNode)
      allLeafletsModel.setSurfaceBoundaryMarkupNode(allLeafletsSurfaceBoundaryMarkupNode)

      #allLeafletsModel.autoDetectSurfaceBoundary(self, planePosition, planeNormal)
      allLeafletsModel.createSurfaceBoundaryFromCurve(planePosition, planeNormal, self.annulusContourCurveNode)
      allLeafletsModel.updateSurface()

      allLeafletsSurfacePolyData = allLeafletsSurfaceModelNode.GetPolyData()

      # Delete temporary segment
      segmentationNode.RemoveSegment(allLeafletsSegId)

      return allLeafletsSurfacePolyData if allLeafletsNumPoints != allLeafletsSurfacePolyData.GetNumberOfPoints() else None

    @staticmethod
    def setGlyphSize(markupsNode, glyphSize):
      markupsDisplayNode = markupsNode.GetDisplayNode()
      markupsDisplayNode.SetGlyphSize(glyphSize)
      markupsDisplayNode.SetUseGlyphScale(False)

    @staticmethod
    def setLineDiameter(markupsNode, diameter):
      markupsDisplayNode = markupsNode.GetDisplayNode()
      markupsDisplayNode.SetCurveLineSizeMode(markupsDisplayNode.UseLineDiameter)
      markupsDisplayNode.SetLineDiameter(diameter)

    @staticmethod
    def smoothSegment(segmentationNode, segmentId, kernelSizeMm=None,
                      kernelSizePixel=None, smoothInZDirection=True, method='closing'):
      """
      Smooth segment by applying morphological closing.
      :param kernelSizeMm Diameter of the kernel in mm
      :param smoothInZDirection Useful for closing leaflets without smoothing their surface
      :param method Smoothing method: closing, median
      """
      # based on SegmentEditorSmoothingEffects/smoothSelectedSegment.py

      import vtkSegmentationCorePython as vtkSegmentationCore

      selectedSegmentLabelmap = getBinaryLabelmapRepresentation(segmentationNode, segmentId)

      #segmentation = segmentationNode.GetSegmentation()
      #selectedSegment = segmentation.GetSegment(selectedSegmentID)
      #selectedSegmentLabelmap = selectedSegment.GetRepresentation(
      #  vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())

      if kernelSizeMm:
        selectedSegmentLabelmapSpacing = [1.0, 1.0, 1.0]
        if selectedSegmentLabelmap:
          selectedSegmentLabelmapSpacing = selectedSegmentLabelmap.GetSpacing()
        # size rounded to nearest odd number. If kernel size is even then image gets shifted.
        kernelSizePixel = [int(round((kernelSizeMm / selectedSegmentLabelmapSpacing[componentIndex] + 1) / 2) * 2 - 1) for
                           componentIndex in range(3)]

      if not smoothInZDirection:
        kernelSizePixel[2] = 1

      # calculate new extent
      originalExtent = selectedSegmentLabelmap.GetExtent()
      if (originalExtent[0] > originalExtent[1] or
        originalExtent[2] > originalExtent[3] or
        originalExtent[4] > originalExtent[5]):
        # segment is empty, nothing to do
        return

      newExtent = [0, 0, 0, 0, 0, 0]
      newExtent[0] = originalExtent[0] - kernelSizePixel[0]
      newExtent[1] = originalExtent[1] + kernelSizePixel[0]
      newExtent[2] = originalExtent[2] - kernelSizePixel[1]
      newExtent[3] = originalExtent[3] + kernelSizePixel[1]
      newExtent[4] = originalExtent[4] - kernelSizePixel[2]
      newExtent[5] = originalExtent[5] + kernelSizePixel[2]

      # pad with zeros
      constantPadFilter = vtk.vtkImageConstantPad()
      constantPadFilter.SetInputData(selectedSegmentLabelmap)
      constantPadFilter.SetOutputWholeExtent(newExtent)

      labelValue = 1
      backgroundValue = 0
      thresh = vtk.vtkImageThreshold()
      thresh.SetInputConnection(constantPadFilter.GetOutputPort())
      thresh.ThresholdByLower(0)
      thresh.SetInValue(backgroundValue)
      thresh.SetOutValue(labelValue)
      thresh.SetOutputScalarType(selectedSegmentLabelmap.GetScalarType())

      smoothingFilter = None
      if method == 'closing':
        smoothingFilter = vtk.vtkImageOpenClose3D()
        smoothingFilter.SetOpenValue(backgroundValue)
        smoothingFilter.SetCloseValue(labelValue)
      elif method == 'median':
        smoothingFilter = vtk.vtkImageMedian3D()

      smoothingFilter.SetKernelSize(kernelSizePixel[0], kernelSizePixel[1], kernelSizePixel[2])
      smoothingFilter.SetInputConnection(thresh.GetOutputPort())
      smoothingFilter.Update()

      imageToWorldMatrix = vtk.vtkMatrix4x4()
      selectedSegmentLabelmap.GetImageToWorldMatrix(imageToWorldMatrix)

      modifierLabelmap = vtkSegmentationCore.vtkOrientedImageData()
      modifierLabelmap.ShallowCopy(smoothingFilter.GetOutput())
      modifierLabelmap.SetImageToWorldMatrix(imageToWorldMatrix)

      slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(modifierLabelmap, segmentationNode, segmentId)

    #######################################################
    # Deprecated methods

    def getDefaultAxialSliceToRasTransformMatrix(self):
      # this property is now stored in the valve sequence
      return self.valveBrowser.defaultAxialSliceToRasTransformMatrix

    def getAxialSliceToRasTransformNode(self):
      # this property is now stored in the valve sequence
      return self.valveBrowser.axialSliceToRasTransformNode

    def getProbeToRasTransformNode(self):
      # this property is now stored in the valve sequence
      return self.valveBrowser.probeToRasTransformNode

    def setValveVolumeNode(self, valveVolumeNode):
      # this property is now stored in the valve sequence
      self.valveBrowser.valveVolumeNode = valveVolumeNode

    def getValveVolumeNode(self):
      # this property is now stored in the valve sequence
      return self.valveBrowser.valveVolumeNode

    def setProbePosition(self, probePosition):
      # this property is now stored in the valve sequence
      self.valveBrowser.probePosition = probePosition

    def getProbePosition(self):
      # this property is now stored in the valve sequence
      return self.valveBrowser.probePosition

    def setSliceOrientations(self, axialNode, ortho1Node, ortho2Node, orthoRotationDeg):
      # this is now implemented in the valve sequence
      self.valveBrowser.setSliceOrientations(axialNode, ortho1Node, ortho2Node, orthoRotationDeg)

    def setSlicePositionAndOrientation(self, axialNode, ortho1Node, ortho2Node, position, orthoRotationDeg, axialSliceToRas=None):
      # this is now implemented in the valve sequence
      self.valveBrowser.setSlicePositionAndOrientation(axialNode, ortho1Node, ortho2Node, position, orthoRotationDeg, axialSliceToRas)

    def setValveType(self, valveType):
      # this property is now stored in the valve sequence
      self.valveBrowser.valveType = valveType

    def getValveType(self):
      # this property is now stored in the valve sequence
      return self.valveBrowser.valveType

    def getClippedVolumeNode(self):
      # this property is now stored in the valve sequence
      return self.valveBrowser.clippedValveVolumeNode

    def setClippedVolumeNode(self, clippedValveVolumeNode):
      # this property is now stored in the valve sequence
      self.valveBrowser.clippedValveVolumeNode = clippedValveVolumeNode

    def getHeartValveNode(self):
      """Kept for backward compatibility"""
      return self.heartValveNode

    def setHeartValveNode(self, node):
      """Kept for backward compatibility"""
      self.heartValveNode = node

    def getValveBrowserNode(self):
      """Kept for backward compatibility"""
      return self.valveBrowserNode

    def getValveBrowser(self):
      """Kept for backward compatibility"""
      return self.valveBrowser

    def getLeafletSegmentationNode(self):
      """Kept for backward compatibility"""
      return self.leafletSegmentationNode

    def setLeafletSegmentationNode(self, segmentationNode):
      """Kept for backward compatibility"""
      self.leafletSegmentationNode = segmentationNode

    def getAnnulusLabelsMarkupNode(self):
      """Kept for backward compatibility"""
      return self.valveLabelsNode

    def setAnnulusLabelsMarkupNode(self, annulusLabelsMarkupNode):
      """Kept for backward compatibility"""
      self.valveLabelsNode = annulusLabelsMarkupNode

    def getAnnulusContourRadius(self):
      """Kept for backward compatibility"""
      return self.annulusContourRadius

    def setAnnulusContourRadius(self, radius):
      """Kept for backward compatibility"""
      self.annulusContourRadius = radius

    def setLeafletVolumeNode(self, leafletVolumeNode):
      """Kept for backward compatibility"""
      self.leafletVolumeNode = leafletVolumeNode

    def getLeafletVolumeNode(self):
      """Kept for backward compatibility"""
      return self.leafletVolumeNode

    # Annulus contour points
    def getAnnulusContourMarkupNode(self):
      """Kept for backward compatibility"""
      return self.annulusContourCurveNode

    def setAnnulusContourMarkupNode(self, annulusContourMarkupNode):
      """Kept for backward compatibility"""
      self.annulusContourMarkupNode = annulusContourMarkupNode

    def getValveRoiModelNode(self):
      """Kept for backward compatibility"""
      return self.valveRoiModelNode

    def setValveRoiModelNode(self, modelNode):
      """Kept for backward compatibility"""
      self.valveRoiModelNode = modelNode

# source: http://stackoverflow.com/questions/12299540/plane-fitting-to-4-or-more-xyz-points
def planeFit(points):
  """
  p, n = planeFit(points)

  Given an array, points, of shape (d,...)
  representing points in d-dimensional space,
  fit an d-dimensional plane to the points.
  Return a point, p, on the plane (the point-cloud centroid),
  and the normal, n.
  """
  import numpy as np
  from numpy.linalg import svd
  points = np.reshape(points, (np.shape(points)[0], -1)) # Collapse trialing dimensions
  assert points.shape[0] <= points.shape[1], "There are only {} points in {} dimensions.".format(points.shape[1],
                                                                                                 points.shape[0])
  ctr = points.mean(axis=1)
  x = points - ctr[:,np.newaxis]
  M = np.dot(x, x.T) # Could also use np.cov(x) here.
  return ctr, svd(M)[0][:,-1]


def lineFit(points):
  """
  Given an array, points, of shape (...,3)
  representing points in 3-dimensional space,
  fit a line to the points.
  Return a point on the plane (the point-cloud centroid),
  and the direction vector.

  :param points:
  :return: point on line, direction vector
  """

  import numpy as np

  #points = np.concatenate((x[:, np.newaxis],
  #                       y[:, np.newaxis],
  #                       z[:, np.newaxis]),
  #                      axis=1)

  # Calculate the mean of the points, i.e. the 'center' of the cloud
  pointsmean = points.mean(axis=0)

  # Do an SVD on the mean-centered data.
  uu, dd, vv = np.linalg.svd(points - pointsmean)

  # Now vv[0] contains the first principal component, i.e. the direction
  # vector of the 'best fit' line in the least squares sense.

  # Normalize direction vector to point towards end point
  approximateForwardDirection = points[-1] - points[0]
  approximateForwardDirection = approximateForwardDirection / np.linalg.norm(approximateForwardDirection)
  if np.dot(vv[0], approximateForwardDirection) >= 0:
    lineDirectionVector = vv[0]
  else:
    lineDirectionVector = -vv[0]

  return pointsmean, lineDirectionVector


def getTransformToPlane(planePosition, planeNormal, xDirection=None):
  """Returns transform matrix from World to Plane coordinate systems.
  Plane is defined in the World coordinate system by planePosition and planeNormal.
  Plane coordinate system: origin is planePosition, z axis is planeNormal, x and y axes are orthogonal to z.
  """
  import numpy as np
  import math

  # Determine the plane coordinate system axes.
  planeZ_World = planeNormal/np.linalg.norm(planeNormal)

  # Generate a plane Y axis by generating an orthogonal vector to
  # plane Z axis vector by cross product plane Z axis vector with
  # an arbitrarily chosen vector (that is not parallel to the plane Z axis).
  if xDirection is None:
    unitX_World = np.array([0,0,1])
  else:
    unitX_World = np.array(xDirection)
    unitX_World = unitX_World/np.linalg.norm(unitX_World)

  angle = math.acos(np.dot(planeZ_World,unitX_World))
  # Normalize between -pi/2 .. +pi/2
  if angle>math.pi/2:
    angle -= math.pi
  elif angle<-math.pi/2:
    angle += math.pi
  if abs(angle)*180.0/math.pi>20.0:
    # unitX is not parallel to planeZ, we can use it
    planeY_World = np.cross(planeZ_World, unitX_World)
  else:
    # unitX is parallel to planeZ, use unitY instead
    unitY_World = np.array([0,1,0])
    planeY_World = np.cross(planeZ_World, unitY_World)

  planeY_World = planeY_World/np.linalg.norm(planeY_World)

  # X axis: orthogonal to tool's Y axis and Z axis
  planeX_World = np.cross(planeY_World, planeZ_World)
  planeX_World = planeX_World/np.linalg.norm(planeX_World)

  transformPlaneToWorld = np.row_stack((np.column_stack((planeX_World, planeY_World, planeZ_World, planePosition)),
                                        (0, 0, 0, 1)))
  transformWorldToPlane = np.linalg.inv(transformPlaneToWorld)

  return transformWorldToPlane


def getPointsProjectedToPlane(pointsArray, planePosition, planeNormal):
  """
  Returns points projected to the plane in world coordinate system and in the plane coordinate system,
  and an array of booleans that tell if the point was above/below the plane.
  pointsArray contains each point as a column vector.
  """
  import numpy as np
  numberOfPoints = pointsArray.shape[1]
  # Concatenate a 4th line containing 1s so that we can transform the positions using
  # a single matrix multiplication.
  pointsArray_World = np.row_stack((pointsArray,np.ones(numberOfPoints)))
  transformWorldToPlane = getTransformToPlane(planePosition, planeNormal)
  # Point positions in the plane coordinate system:
  pointsArray_Plane = np.dot(transformWorldToPlane, pointsArray_World)
  pointsAbovePlane = pointsArray_Plane[2,:] > 0
  # Projected point positions in the plane coordinate system:
  pointsArray_Plane[2,:] = np.zeros(numberOfPoints)
  # Projected point positions in the world coordinate system:
  pointsArrayProjected_World = np.dot(np.linalg.inv(transformWorldToPlane), pointsArray_Plane)

  # remove the last row (all ones)
  pointsArrayProjected_World = pointsArrayProjected_World[0:3,:]
  pointsArrayProjected_Plane = pointsArray_Plane[0:2,:]

  return [pointsArrayProjected_World, pointsArrayProjected_Plane, pointsAbovePlane]


def getPolyArea(vertices):
  """
  The area of a 2D polygon can be calculated using Numpy as a one-liner...
  source: http://stackoverflow.com/questions/12642256/python-find-area-of-polygon-from-xyz-coordinates
  """
  import numpy as np
  polyArea = np.sum( [0.5, -0.5] * vertices.T * np.roll( np.roll(vertices.T, 1, axis=0), 1, axis=1) )
  return abs(polyArea)


def getLinesIntersectionPoints(p1, p2, p3, p4):
  """
  Calculate the points in 3D space Pa and Pb that define the line segment which is the shortest route between two lines
  p1p2 and p3p4. Each point occurs at the apparent intersection of the 3D lines.
  The apparent intersection is defined here as the location where the two lines 'appear' to intersect when viewed along
  the line segment PaPb.
  Equation for each line:
  Pa = p1 + ma(p2-p1)
  Pb = p3 + mb(p4-p3)

  Pa lies on the line connecting p1p2.
  Pb lies on the line connecting p3p4.

  The shortest line segment is perpendicular to both lines. Therefore:
  (Pa-Pb).(p2-p1) = 0
  (Pa-Pb).(p4-p3) = 0

  Where:
  '.' indicates the dot product

  A = p1-p3
  B = p2-p1
  C = p4-p3

  Substituting:
  (A + ma(B) - mb(C)).B = 0       &       (A + ma(B) - mb(C)).C = 0
  -----------------------------------------------------------------
  A.B + ma(B.B) - mb(C.B) = 0
  A.B + ma(B.B) - (ma(C.B)-A.C)/C.C)(C.B) = 0
  ma(B.B)(C.C) - ma(C.B)(C.B) = (A.C)(C.B)-(A.B)(C.C)
  ma = ((A.C)(C.B)-(A.B)(C.C))/((B.B)(C.C) - (C.B)(C.B))
  mb = (A.B + ma(B.B))/(C.B)

  If the cross product magnitude of the two lines is equal to 0.0, the lines are parallel.
  """
  import numpy as np
  A = p1-p3
  B = p2-p1
  C = p4-p3

  # Line p1p2 and p3p4 unit vectors
  uv1 = B/np.linalg.norm(B)
  uv2 = C/np.linalg.norm(C)

  # Check for parallel lines
  cp12 = np.cross(uv1, uv2)
  _cp12_ = np.linalg.norm(cp12)

  if round(_cp12_, 6) == 0.0:
    # Lines are parallel
    return (p1+p2+p3+p4)/4

  ma = ((np.dot(A, C)*np.dot(C, B)) - (np.dot(A, B)*np.dot(C, C)))/((np.dot(B, B)*np.dot(C, C)) - (np.dot(C, B)*np.dot(C, B)))
  mb = (ma*np.dot(C, B) + np.dot(A, C))/ np.dot(C, C)

  # Calculate the point on line 1 that is the closest point to line 2
  Pa = p1 + B*ma

  # Calculate the point on line 2 that is the closest point to line 1
  Pb = p3 + C*mb

  return [Pa, Pb]


def getPointProjectionToLine(point, lineStart, lineEnd):
  """
  Compute position of point projected to line segment.
  """
  import numpy as np
  lineSegmentLength = np.linalg.norm(lineEnd-lineStart)
  # Projected point's normalized distance from start point. Distance is between [0,1] if the point is projected on the line.
  normalizedDistance = np.dot( point-lineStart , (lineEnd-lineStart)/lineSegmentLength )/lineSegmentLength

  # Compute projected point position
  if normalizedDistance<=0:
    projectedPointPosition = lineStart
  elif normalizedDistance>=1:
    projectedPointPosition = lineEnd
  else:
    projectedPointPosition = lineStart + normalizedDistance * (lineEnd-lineStart)

  return projectedPointPosition


def createMatrixFromString(transformMatrixString):
  from HeartValveLib.util import createMatrixFromString
  return createMatrixFromString(transformMatrixString)


def createVtkMatrixFromArray(transformArray):
  """Create vtkMatrix4x4 from numpy array(4,4)"""
  transformMatrixVtk = vtk.vtkMatrix4x4()
  for colIndex in range(4):
    for rowIndex in range(3):
      transformMatrixVtk.SetElement(rowIndex, colIndex, transformArray[rowIndex, colIndex])
  return transformMatrixVtk

def getVtkTransformPlaneToWorld(planePosition, planeNormal, xDirection=None):
  import numpy as np
  transformPlaneToWorldVtk = vtk.vtkTransform()
  transformWorldToPlaneMatrix = getTransformToPlane(planePosition, planeNormal, xDirection)
  transformPlaneToWorldMatrix = np.linalg.inv(transformWorldToPlaneMatrix)
  transformWorldToPlaneMatrixVtk = createVtkMatrixFromArray(transformPlaneToWorldMatrix)
  transformPlaneToWorldVtk.SetMatrix(transformWorldToPlaneMatrixVtk)
  return transformPlaneToWorldVtk


# Source: https://www.learnopencv.com/rotation-matrix-to-euler-angles/
# Checks if a matrix is a valid rotation matrix.
def isRotationMatrix(R):
  import numpy as np
  Rt = np.transpose(R)
  shouldBeIdentity = np.dot(Rt, R)
  I = np.identity(3, dtype = R.dtype)
  n = np.linalg.norm(I - shouldBeIdentity)
  return n < 1e-6


# Source: https://www.learnopencv.com/rotation-matrix-to-euler-angles/
# Calculates rotation matrix to euler angles.
# The result is the same as MATLAB except the order
# of the euler angles ( x and z are swapped ).
def rotationMatrixToEulerAngles(R):
  import numpy as np
  import math
  assert(isRotationMatrix(R))
  sy = math.sqrt(R[0,0] * R[0,0] +  R[1,0] * R[1,0])
  singular = sy < 1e-6
  if  not singular :
    x = math.atan2(R[2,1] , R[2,2])
    y = math.atan2(-R[2,0], sy)
    z = math.atan2(R[1,0], R[0,0])
  else :
    x = math.atan2(-R[1,2], R[1,1])
    y = math.atan2(-R[2,0], sy)
    z = 0
  return np.array([x, y, z])
