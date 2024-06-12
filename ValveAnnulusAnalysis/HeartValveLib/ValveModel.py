#
#   HeartValveModel.py: Stores valve model data, quantifies properties, and creates displayable models
#

import vtk, slicer
import SmoothCurve
import LeafletModel
import CoaptationModel
import PapillaryModel
import ValveRoi
import logging
import HeartValves
from Constants import *
from helpers import getBinaryLabelmapRepresentation


class ValveModel:

    def __init__(self):
      self.heartValveNode = None
      self.annulusContourCurve = SmoothCurve.SmoothCurve()
      self.annulusContourCurve.setInterpolationMethod(SmoothCurve.InterpolationSpline)
      self.annulusContourCurve.setClosed(True)

      self.valveRoi = ValveRoi.ValveRoi()
      self.valveRoi.setAnnulusContourCurve(self.annulusContourCurve)

      # List of LeafletModel objects, one for each leaflet segment
      self.leafletModels = []

      # List of CoaptationModel objects, one for each coaptation surface
      self.coaptationModels = []

      # List of PapillaryModel objects, one for each papillary muscle
      self.papillaryModels = []

      # how many times the markup point is larger than the tube diameter
      self.annulusContourMarkupScale = 1.3
      self.defaultAnnulusContourRadius = 0.5

      self.probePositionPresets = PROBE_POSITION_PRESETS

      self.valveTypePresets = VALVE_TYPE_PRESETS

      self.cardiacCyclePhasePresets = CARDIAC_CYCLE_PHASE_PRESETS

    def setHeartValveNode(self, node):
      if self.heartValveNode == node:
        # no change
        return
      self.annulusContourCurve.setCurveModelNode(None)
      self.annulusContourCurve.setControlPointsMarkupNode(None)
      self.heartValveNode = node
      if self.heartValveNode:
        self.setHeartValveNodeDefaults()
        # Update parameters and references
        self.setAnnulusContourRadius(self.getAnnulusContourRadius())
        self.setAnnulusContourModelNode(self.getAnnulusContourModelNode())
        self.setAnnulusContourMarkupNode(self.getAnnulusContourMarkupNode())
        self.setAnnulusLabelsMarkupNode(self.getAnnulusLabelsMarkupNode())
        self.setValveRoiModelNode(self.getValveRoiModelNode())

    def getHeartValveNode(self):
      return self.heartValveNode

    def setHeartValveNodeDefaults(self):
      """Initialize HeartValveNode with defaults. Already defined values are not changed."""
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      if self.heartValveNode.GetHideFromEditors():
        self.heartValveNode.SetHideFromEditors(False)
        shNode.RequestOwnerPluginSearch(self.heartValveNode)
        shNode.SetItemAttribute(shNode.GetItemByDataNode(self.heartValveNode), "ModuleName", "HeartValve")

      if not self.getAnnulusContourRadius():
        self.setAnnulusContourRadius(self.defaultAnnulusContourRadius)

      if self.getValveVolumeSequenceIndex() < 0:
        self.setValveVolumeSequenceIndex(-1)  # by default it is set to -1 (undefined)

      self.getProbePosition()
      self.getCardiacCyclePhase()

      if not self.getAxialSliceToRasTransformNode():
        logging.debug("Did not find annulus transform node, create a new one")
        self.setAxialSliceToRasTransformNode(self.createAxialSliceToRasTransformNode())

      if not self.getAnnulusContourMarkupNode():
        logging.debug("Did not find contour markup point node, create a new one")
        self.setAnnulusContourMarkupNode(self.createAnnulusContourMarkupNode())

      if not self.getAnnulusLabelsMarkupNode():
        logging.debug("Did not find label markup node, create a new one")
        self.setAnnulusLabelsMarkupNode(self.createAnnulusLabelsMarkupNode())

      if not self.getAnnulusContourModelNode():
        logging.debug("Did not find markup model node, create a new one")
        self.setAnnulusContourModelNode(self.createAnnulusContourModelNode())

      if not self.getValveRoiModelNode():
        logging.debug("Did not find ROI model node, create a new one")
        self.setValveRoiModelNode(self.createValveRoiModelNode())

      if not self.getLeafletSegmentationNode():
        logging.debug("Did not find leaflet segmentation node, create a new one")
        self.setLeafletSegmentationNode(self.createLeafletSegmentationNode())

      self.updateLeafletModelsFromSegmentation()

      self.updateCoaptationModels()

    def moveNodeToHeartValveFolder(self, node, subfolderName = None):
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      valveNodeItemId = shNode.GetItemByDataNode(self.heartValveNode)
      if subfolderName:
        folderItemId = shNode.GetItemChildWithName(valveNodeItemId, subfolderName)
        if not folderItemId:
          folderItemId = shNode.CreateFolderItem(valveNodeItemId, subfolderName)
      else:
        folderItemId = valveNodeItemId
      shNode.SetItemParent(shNode.GetItemByDataNode(node), folderItemId)

    def getDefaultAxialSliceToRasTransformMatrix(self):
      axialSliceToRas = vtk.vtkMatrix4x4()
      probePosition = self.getProbePosition()
      probePositionPreset = self.probePositionPresets[probePosition]
      axialSliceToRas.DeepCopy(createMatrixFromString(probePositionPreset['axialSliceToRasTransformMatrix']))
      return axialSliceToRas

    def createAxialSliceToRasTransformNode(self):
      axialSliceToRasTransformNode = slicer.vtkMRMLLinearTransformNode()
      axialSliceToRasTransformNode.SetName(slicer.mrmlScene.GetUniqueNameByString("AxialSliceToRasTransform"))
      axialSliceToRasTransformNode.SetMatrixTransformToParent(self.getDefaultAxialSliceToRasTransformMatrix())

      slicer.mrmlScene.AddNode(axialSliceToRasTransformNode)
      # prevent the node from showing up in SH, as it is not something that users would need to manipulate
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      shNode.SetItemAttribute(shNode.GetItemByDataNode(axialSliceToRasTransformNode),
                              slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyExcludeFromTreeAttributeName(),
                              "1")
      self.moveNodeToHeartValveFolder(axialSliceToRasTransformNode)
      return axialSliceToRasTransformNode

    def setAxialSliceToRasTransformNode(self, axialSliceToRasTransformNode):
      if not self.heartValveNode:
        logging.error("setAxialSliceToRasTransformNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("AxialSliceToRasTransform",
                                             axialSliceToRasTransformNode.GetID() if axialSliceToRasTransformNode else None)

    def getAxialSliceToRasTransformNode(self):
      return self.heartValveNode.GetNodeReference("AxialSliceToRasTransform") if self.heartValveNode else None

    def getProbeToRasTransformNode(self):
      valveVolumeNode = self.getValveVolumeNode()
      if not valveVolumeNode:
        return None
      return valveVolumeNode.GetParentTransformNode()

    def updateProbeToRasTransform(self):
      """Compute ProbeToRasTransform from volume and probe position
      and store it in ProbeToRasTransformNode"""

      # Check inputs
      probeToRasTransformNode = self.getProbeToRasTransformNode()
      valveVolumeNode = self.getValveVolumeNode()
      if not probeToRasTransformNode or not valveVolumeNode:
        return
      if not valveVolumeNode.GetImageData():
        logging.warning('updateProbeToRasTransform failed: valve volume does not contain a valid image')
        return

      # Compute probeToRasTransform so that it centers the volume and orients it approximately
      # correctly in the RAS coordinate system
      valveVolumeExtent = valveVolumeNode.GetImageData().GetExtent()
      valveVolumeCenterIjk = [(valveVolumeExtent[component*2+1]-valveVolumeExtent[component*2]+1)/2.0 for component in range(3)]
      valveVolumeCenterIjk.append(1)
      ijkToRasMatrix = vtk.vtkMatrix4x4()
      valveVolumeNode.GetIJKToRASMatrix(ijkToRasMatrix)
      valveVolumeCenterRas = ijkToRasMatrix.MultiplyPoint(valveVolumeCenterIjk)
      probeToRasTransform = vtk.vtkTransform()
      probeToRasTransformMatrix = vtk.vtkMatrix4x4()
      self.getDefaultProbeToRasOrientation(probeToRasTransformMatrix)
      probeToRasTransform.SetMatrix(probeToRasTransformMatrix)
      probeToRasTransform.Translate(-valveVolumeCenterRas[0],-valveVolumeCenterRas[1],-valveVolumeCenterRas[2])
      probeToRasTransformNode.SetMatrixTransformToParent(probeToRasTransform.GetMatrix())

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

    def setValveVolumeNode(self, valveVolumeNode):
      if not self.heartValveNode:
        logging.error("setValveVolumeNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("ValveVolume", valveVolumeNode.GetID() if valveVolumeNode else None)

      # Create probeToRasTransformNode if does not exist yet
      probeToRasTransformNodeId = None
      if valveVolumeNode:
        if not valveVolumeNode.GetParentTransformNode():
          probeToRasTransformNode = slicer.vtkMRMLLinearTransformNode()
          probeToRasTransformNode.SetName(slicer.mrmlScene.GetUniqueNameByString("ProbeToRasTransform"))
          slicer.mrmlScene.AddNode(probeToRasTransformNode)
          valveVolumeNode.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID())
        #slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(
        #  valveVolumeNode.GetScene(), slicer.vtkMRMLSubjectHierarchyNode.GetAssociatedSubjectHierarchyNode(valveVolumeNode),
        #  None, valveVolumeNode.GetName(), valveVolumeNode)
        self.updateProbeToRasTransform()
        HeartValves.setSequenceBrowserNodeDisplayIndex(self)

      # Put valve under probeToRas transform (Probe coordinate system)
      self.applyProbeToRasTransformToNode(self.getAnnulusContourMarkupNode())
      self.applyProbeToRasTransformToNode(self.getAnnulusContourModelNode())
      self.applyProbeToRasTransformToNode(self.getAnnulusLabelsMarkupNode())
      self.applyProbeToRasTransformToNode(self.getValveRoiModelNode())
      self.applyProbeToRasTransformToNode(self.getLeafletSegmentationNode())
      self.applyProbeToRasTransformToNode(self.getClippedVolumeNode())
      self.applyProbeToRasTransformToNode(self.getLeafletVolumeNode())

      # Update parent transform in leaflet surface models
      self.updateLeafletModelsFromSegmentation()
      self.updateCoaptationModels()

    def applyProbeToRasTransformToNode(self, nodeToApplyTo=None):
      if nodeToApplyTo is not None:
        probeToRasTransformNode = self.getProbeToRasTransformNode()
        nodeToApplyTo.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

    def getValveVolumeNode(self):
      return self.heartValveNode.GetNodeReference("ValveVolume") if self.heartValveNode else None

    def setLeafletVolumeNode(self, clippedValveVolumeNode):
      if not self.heartValveNode:
        logging.error("setLeafletVolumeNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("LeafletVolume",
                                             clippedValveVolumeNode.GetID() if clippedValveVolumeNode else None)
      self.applyProbeToRasTransformToNode(clippedValveVolumeNode)
      self.moveNodeToHeartValveFolder(clippedValveVolumeNode)

    def getLeafletVolumeNode(self):
      """:returns Volume that is used for leaflet segmentation (to generate LeafletSegmentationNode)"""
      return self.heartValveNode.GetNodeReference("LeafletVolume") if self.heartValveNode else None

    def getClippedVolumeNode(self):
      """:returns Volume that is used clipped to the valve ROI for volume rendering"""
      return self.heartValveNode.GetNodeReference("ClippedVolume") if self.heartValveNode else None

    def setClippedVolumeNode(self, clippedValveVolumeNode):
      if not self.heartValveNode:
        logging.error("setClippedVolumeNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("ClippedVolume",
                                             clippedValveVolumeNode.GetID() if clippedValveVolumeNode else None)
      self.applyProbeToRasTransformToNode(clippedValveVolumeNode)

    # Annulus contour points
    def getAnnulusContourMarkupNode(self):
      return self.heartValveNode.GetNodeReference("AnnulusContourPoints") if self.heartValveNode else None

    def setAnnulusContourMarkupNode(self, annulusContourMarkupNode):
      if not self.heartValveNode:
        logging.error("setAnnulusContourMarkupNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("AnnulusContourPoints",
                                             annulusContourMarkupNode.GetID() if annulusContourMarkupNode else None)
      self.applyProbeToRasTransformToNode(annulusContourMarkupNode)
      self.annulusContourCurve.setControlPointsMarkupNode(self.getAnnulusContourMarkupNode())

    def createAnnulusContourMarkupNode(self):
      markupsLogic = slicer.modules.markups.logic()
      annulusMarkupNodeId = markupsLogic.AddNewFiducialNode()
      annulusMarkupNode = slicer.mrmlScene.GetNodeByID(annulusMarkupNodeId)
      annulusMarkupNode.SetName(slicer.mrmlScene.GetUniqueNameByString("AnnulusContourMarkup"))
      annulusMarkupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
      self.moveNodeToHeartValveFolder(annulusMarkupNode)
      annulusMarkupDisplayNode=annulusMarkupNode.GetDisplayNode()
      ValveModel.setGlyphSize(annulusMarkupDisplayNode, self.defaultAnnulusContourRadius*self.annulusContourMarkupScale*2)
      return annulusMarkupNode

    # Annulus contour labels
    def getAnnulusLabelsMarkupNode(self):
      return self.heartValveNode.GetNodeReference("AnnulusLabelsPoints") if self.heartValveNode else None

    def setAnnulusLabelsMarkupNode(self, annulusLabelsMarkupNode):
      if not self.heartValveNode:
        logging.error("setAnnulusLabelsMarkupNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("AnnulusLabelsPoints",
                                             annulusLabelsMarkupNode.GetID() if annulusLabelsMarkupNode else None)
      self.applyProbeToRasTransformToNode(annulusLabelsMarkupNode)
      self.annulusContourCurve.setControlPointsMarkupNode(self.getAnnulusContourMarkupNode())

    def createAnnulusLabelsMarkupNode(self):
      markupsLogic = slicer.modules.markups.logic()
      annulusMarkupNodeId = markupsLogic.AddNewFiducialNode()
      annulusMarkupNode = slicer.mrmlScene.GetNodeByID(annulusMarkupNodeId)
      annulusMarkupNode.SetName(slicer.mrmlScene.GetUniqueNameByString("AnnulusLabelsMarkup"))
      annulusMarkupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
      annulusMarkupNode.SetLocked(True) # prevent accidental changes
      self.moveNodeToHeartValveFolder(annulusMarkupNode)
      annulusMarkupDisplayNode=annulusMarkupNode.GetDisplayNode()
      ValveModel.setGlyphSize(annulusMarkupDisplayNode, self.defaultAnnulusContourRadius*self.annulusContourMarkupScale*3)
      return annulusMarkupNode

    # Annulus contour line
    def getAnnulusContourModelNode(self):
      return self.heartValveNode.GetNodeReference("AnnulusContourModel") if self.heartValveNode else None

    def setAnnulusContourModelNode(self, modelNode):
      if not self.heartValveNode:
        logging.error("setAnnulusModelNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("AnnulusContourModel", modelNode.GetID() if modelNode else None)
      self.applyProbeToRasTransformToNode(modelNode)
      self.annulusContourCurve.setCurveModelNode(self.getAnnulusContourModelNode())

    def createAnnulusContourModelNode(self):
      modelsLogic = slicer.modules.models.logic()
      polyData = vtk.vtkPolyData()
      modelNode = modelsLogic.AddModel(polyData)
      modelNode.SetName(slicer.mrmlScene.GetUniqueNameByString("AnnulusContourModel"))
      self.moveNodeToHeartValveFolder(modelNode)
      modelNode.GetDisplayNode().SetColor(self.cardiacCyclePhasePresets[self.getCardiacCyclePhase()]["color"])
      return modelNode

    def getVolumeSequenceIndexAsDisplayedString(self, volumeSequenceIndex):
      if volumeSequenceIndex < 0:
        return "NA"  # not available
      # sequence index is 0-based but it is displayed as 1-based
      return str(volumeSequenceIndex + 1)

    def getValveVolumeSequenceIndex(self):
      """"Get item index of analyzed valve volume in the volume sequence. Returns -1 if index value is undefined."""
      indexStr = self.heartValveNode.GetAttribute("ValveVolumeSequenceIndex")
      return int(indexStr) if indexStr is not None else -1

    def setValveVolumeSequenceIndex(self, index):
      if not self.heartValveNode:
        logging.error("setValveVolumeSequenceIndex failed: invalid heartValveNode")
        return
      self.heartValveNode.SetAttribute("ValveVolumeSequenceIndex", str(index))
      self.updateValveNodeNames()

    # Annulus contour line radius
    def getAnnulusContourRadius(self):
      radiusStr = self.heartValveNode.GetAttribute("AnnulusContourRadius")
      return float(radiusStr) if radiusStr else None

    def setAnnulusContourRadius(self, radius):
      if not self.heartValveNode:
        logging.error("setAnnulusModelRadius failed: invalid heartValveNode")
        return
      self.heartValveNode.SetAttribute("AnnulusContourRadius",str(radius))

      self.annulusContourCurve.setTubeRadius(radius)
      self.annulusContourCurve.updateCurve()

      if self.getAnnulusContourMarkupNode():
        annulusMarkupDisplayNode = self.getAnnulusContourMarkupNode().GetDisplayNode()
        ValveModel.setGlyphSize(annulusMarkupDisplayNode, radius*self.annulusContourMarkupScale*2)
      if self.getAnnulusLabelsMarkupNode():
        annulusMarkupDisplayNode = self.getAnnulusLabelsMarkupNode().GetDisplayNode()
        ValveModel.setGlyphSize(annulusMarkupDisplayNode, radius*self.annulusContourMarkupScale*3)

    # Annulus contour line
    def getValveRoiModelNode(self):
      return self.heartValveNode.GetNodeReference("ValveRoiModel") if self.heartValveNode else None

    def setValveRoiModelNode(self, modelNode):
      if not self.heartValveNode:
        logging.error("setValveRoiModelNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("ValveRoiModel", modelNode.GetID() if modelNode else None)
      self.applyProbeToRasTransformToNode(modelNode)
      self.valveRoi.setRoiModelNode(modelNode)

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

      self.valveRoi.setRoiModelNode(modelNode)

      return modelNode  # Annulus contour line

    def getLeafletSegmentationNode(self):
      return self.heartValveNode.GetNodeReference("LeafletSegmentation") if self.heartValveNode else None

    def setLeafletSegmentationNode(self, segmentationNode):
      if not self.heartValveNode:
        logging.error("setLeafletSegmentationNode failed: invalid heartValveNode")
        return
      self.heartValveNode.SetNodeReferenceID("LeafletSegmentation",
                                             segmentationNode.GetID() if segmentationNode else None)
      self.applyProbeToRasTransformToNode(segmentationNode)
      self.updateLeafletModelsFromSegmentation()
      self.updateCoaptationModels()

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
      papillaryLineModelNode = self.heartValveNode.GetNthNodeReference("PapillaryLineModel", papillaryModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("PapillaryLineMarkup", papillaryModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("PapillaryLineModel", papillaryModelIndex)
      self.papillaryModels.remove(papillaryModel)
      slicer.mrmlScene.RemoveNode(papillaryLineMarkupNode)
      slicer.mrmlScene.RemoveNode(papillaryLineModelNode)

    def updatePapillaryModel(self, papillaryModelIndex=-1):
      if papillaryModelIndex < 0:
        papillaryModelIndex = len(self.papillaryModels)
      if papillaryModelIndex<len(self.papillaryModels):
        papillaryModel = self.papillaryModels[papillaryModelIndex]
      else:
        papillaryModel = PapillaryModel.PapillaryModel()
        self.papillaryModels.append(papillaryModel)

      papillaryLineModelNode = self.heartValveNode.GetNthNodeReference("PapillaryLineModel", papillaryModelIndex)
      if papillaryLineModelNode:
        papillaryMuscleName = papillaryLineModelNode.GetName().replace(" papillary muscle", "")
      else:
        papillaryMuscleName = self.valveTypePresets[self.getValveType()]["papillaryNames"][papillaryModelIndex]
      papillaryLineMarkupNode = self.heartValveNode.GetNthNodeReference("PapillaryLineMarkup", papillaryModelIndex)
      if not papillaryLineMarkupNode:
        markupsLogic = slicer.modules.markups.logic()
        markupNodeId = markupsLogic.AddNewFiducialNode()
        markupNode = slicer.mrmlScene.GetNodeByID(markupNodeId)
        #markupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
        markupNode.SetLocked(True) # prevent accidental changes
        self.moveNodeToHeartValveFolder(markupNode, 'PapillaryMusclesEdit')
        markupDisplayNode = markupNode.GetDisplayNode()
        ValveModel.setGlyphSize(markupDisplayNode, papillaryModel.markupGlyphScale)
        markupDisplayNode.SetColor(0.5,0,1)
        self.heartValveNode.SetNthNodeReferenceID("PapillaryLineMarkup", papillaryModelIndex, markupNode.GetID())
        papillaryLineMarkupNode = markupNode
      papillaryLineMarkupNode.SetName("PapillaryMarkup-"+papillaryMuscleName)
      self.applyProbeToRasTransformToNode(papillaryLineMarkupNode)
      papillaryModel.setPapillaryLineMarkupNode(papillaryLineMarkupNode)

      if not papillaryLineModelNode:
        modelsLogic = slicer.modules.models.logic()
        polyData = vtk.vtkPolyData()
        modelNode = modelsLogic.AddModel(polyData)
        self.moveNodeToHeartValveFolder(modelNode, 'PapillaryMuscles')
        modelNode.GetDisplayNode().SetVisibility2D(True)
        modelNode.GetDisplayNode().SetOpacity(1.0)
        self.heartValveNode.SetNthNodeReferenceID("PapillaryLineModel", papillaryModelIndex, modelNode.GetID())
        papillaryLineModelNode = modelNode
      annulusContourModel = self.getAnnulusContourModelNode()
      papillaryLineModelNode.GetDisplayNode().SetColor(annulusContourModel.GetDisplayNode().GetColor())
      papillaryLineModelNode.SetName(papillaryMuscleName+" papillary muscle")
      self.applyProbeToRasTransformToNode(papillaryLineModelNode)
      papillaryModel.setPapillaryLineModelNode(papillaryLineModelNode)

      return papillaryModel

    def findPapillaryModel(self, papillaryLineModelNode):
      for papillaryModel in self.papillaryModels:
        if papillaryModel.getPapillaryLineModelNode() == papillaryLineModelNode:
          return papillaryModel
      # Not found
      return None

    def updatePapillaryModels(self):
      papillaryMuscleNames = self.valveTypePresets[self.getValveType()]["papillaryNames"]
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
          self.removeLeafletNodeReference("LeafletSurfaceBoundaryModel", segmentId)
          self.leafletModels.remove(leafletModel)
          return

    def addLeafletModel(self, segmentId):
      leafletModel = self.findLeafletModel(segmentId)
      if not leafletModel:
        leafletModel = LeafletModel.LeafletModel()
        self.leafletModels.append(leafletModel)

      segmentationNode = self.getLeafletSegmentationNode()
      leafletModel.setSegmentationNode(segmentationNode)
      leafletModel.setSegmentId(segmentId)

      segmentName = segmentationNode.GetSegmentation().GetSegment(segmentId).GetName()
      segmentColor = segmentationNode.GetSegmentation().GetSegment(segmentId).GetColor()

      leafletSurfaceModelNode = self.getLeafletNodeReference("LeafletSurfaceModel", segmentId)
      if not leafletSurfaceModelNode:
        modelsLogic = slicer.modules.models.logic()
        polyData = vtk.vtkPolyData()
        modelNode = modelsLogic.AddModel(polyData)
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
      leafletSurfaceModelNode.SetName(segmentName + " SurfaceModel")
      self.applyProbeToRasTransformToNode(leafletSurfaceModelNode)
      leafletModel.setSurfaceModelNode(leafletSurfaceModelNode)

      leafletSurfaceBoundaryMarkupNode = self.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", segmentId)
      if not leafletSurfaceBoundaryMarkupNode:
        markupsLogic = slicer.modules.markups.logic()
        markupNodeId = markupsLogic.AddNewFiducialNode()
        markupNode = slicer.mrmlScene.GetNodeByID(markupNodeId)
        markupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
        markupNode.SetLocked(True) # prevent accidental changes
        self.moveNodeToHeartValveFolder(markupNode, 'LeafletSurfaceEdit')
        markupDisplayNode = markupNode.GetDisplayNode()
        ValveModel.setGlyphSize(markupDisplayNode, leafletModel.markupGlyphScale)
        markupDisplayNode.SetColor(0,0,1)
        self.setLeafletNodeReference("LeafletSurfaceBoundaryMarkup", segmentId, markupNode)
        leafletSurfaceBoundaryMarkupNode = markupNode
      leafletSurfaceBoundaryMarkupNode.SetName(segmentName + " SurfaceBoundaryMarkup")
      self.applyProbeToRasTransformToNode(leafletSurfaceBoundaryMarkupNode)
      leafletModel.setSurfaceBoundaryMarkupNode(leafletSurfaceBoundaryMarkupNode)

      leafletSurfaceBoundaryModelNode = self.getLeafletNodeReference("LeafletSurfaceBoundaryModel", segmentId)
      if not leafletSurfaceBoundaryModelNode:
        modelsLogic = slicer.modules.models.logic()
        polyData = vtk.vtkPolyData()
        modelNode = modelsLogic.AddModel(polyData)
        self.moveNodeToHeartValveFolder(modelNode, 'LeafletSurfaceEdit')
        modelNode.GetDisplayNode().SetColor(0,0,1)
        modelNode.GetDisplayNode().SetOpacity(0.2)
        self.setLeafletNodeReference("LeafletSurfaceBoundaryModel", segmentId, modelNode)
        leafletSurfaceBoundaryModelNode = modelNode
      leafletSurfaceBoundaryModelNode.SetName(segmentName + " SurfaceBoundaryModel")
      self.applyProbeToRasTransformToNode(leafletSurfaceBoundaryModelNode)
      leafletModel.setSurfaceBoundaryModelNode(leafletSurfaceBoundaryModelNode)

      # Move items to folders - for legacy scenes
      self.moveNodeToHeartValveFolder(leafletSurfaceModelNode, 'LeafletSurface')
      self.moveNodeToHeartValveFolder(leafletSurfaceBoundaryMarkupNode, 'LeafletSurfaceEdit')
      self.moveNodeToHeartValveFolder(leafletSurfaceBoundaryModelNode, 'LeafletSurfaceEdit')

    def updateLeafletModelsFromSegmentation(self):
      segmentIds = []
      segmentationNode = self.getLeafletSegmentationNode()
      if segmentationNode:
        segmentIdsVtk = vtk.vtkStringArray()
        segmentationNode.GetSegmentation().GetSegmentIDs(segmentIdsVtk)
        for i in range(segmentIdsVtk.GetNumberOfValues()):
          segmentId = segmentIdsVtk.GetValue(i)
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

      # Add any missing leaflet models
      for segmentId in segmentIds:
        self.addLeafletModel(segmentId)

      self.findAndRemoveOrphanNodes(validSegmentIDs=segmentIds)

    def findAndRemoveOrphanNodes(self, validSegmentIDs):
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      valveNodeItemId = shNode.GetItemByDataNode(self.heartValveNode)
      toDelete = []
      for subFolderId in ["LeafletSurfaceEdit", "LeafletSurface"]:
        folderItemId = shNode.GetItemChildWithName(valveNodeItemId, subFolderId)
        shNode.GetItemChildren(folderItemId, childItemIDs := vtk.vtkIdList())
        for index in range(childItemIDs.GetNumberOfIds()):
          dataNode = shNode.GetItemDataNode(childItemIDs.GetId(index))
          if not dataNode.GetAttribute('SegmentID') in validSegmentIDs:
            toDelete.append(dataNode)
      for node in toDelete:
        logging.debug(f"Found orphan node. Removing {node.GetName()}")
        slicer.mrmlScene.RemoveNode(node)

    def removeCoaptationModel(self, coaptationModelIndex):
      coaptationModel = self.coaptationModels[coaptationModelIndex]
      coaptationSurfaceModelNode = self.heartValveNode.GetNthNodeReference("CoaptationSurfaceModel",coaptationModelIndex)
      baseLineMarkupNode = self.heartValveNode.GetNthNodeReference("CoaptationBaseLineMarkup", coaptationModelIndex)
      baseLineModelNode = self.heartValveNode.GetNthNodeReference("CoaptationBaseLineModel", coaptationModelIndex)
      marginLineMarkupNode = self.heartValveNode.GetNthNodeReference("CoaptationMarginLineMarkup", coaptationModelIndex)
      marginLineModelNode = self.heartValveNode.GetNthNodeReference("CoaptationMarginLineModel", coaptationModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("CoaptationBaseLineMarkup", coaptationModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("CoaptationBaseLineModel", coaptationModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("CoaptationMarginLineMarkup", coaptationModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("CoaptationMarginLineModel", coaptationModelIndex)
      self.heartValveNode.RemoveNthNodeReferenceID("CoaptationSurfaceModel", coaptationModelIndex)
      self.coaptationModels.remove(coaptationModel)
      slicer.mrmlScene.RemoveNode(coaptationSurfaceModelNode)
      slicer.mrmlScene.RemoveNode(baseLineMarkupNode)
      slicer.mrmlScene.RemoveNode(baseLineModelNode)
      slicer.mrmlScene.RemoveNode(marginLineMarkupNode)
      slicer.mrmlScene.RemoveNode(marginLineModelNode)

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
        markupsLogic = slicer.modules.markups.logic()
        markupNodeId = markupsLogic.AddNewFiducialNode()
        markupNode = slicer.mrmlScene.GetNodeByID(markupNodeId)
        markupNode.SetName(slicer.mrmlScene.GetUniqueNameByString(namePrefix+"BaseLineMarkup"))
        markupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
        markupNode.SetLocked(True) # prevent accidental changes
        self.moveNodeToHeartValveFolder(markupNode, 'CoaptationEdit')
        markupDisplayNode = markupNode.GetDisplayNode()
        ValveModel.setGlyphSize(markupDisplayNode, coaptationModel.markupGlyphScale)
        markupDisplayNode.SetColor(0,0,1)
        self.heartValveNode.SetNthNodeReferenceID("CoaptationBaseLineMarkup", coaptationModelIndex, markupNode.GetID())
        baseLineMarkupNode = markupNode
      self.applyProbeToRasTransformToNode(baseLineMarkupNode)
      coaptationModel.setBaseLineMarkupNode(baseLineMarkupNode)

      baseLineModelNode = self.heartValveNode.GetNthNodeReference("CoaptationBaseLineModel", coaptationModelIndex)
      if not baseLineModelNode:
        modelsLogic = slicer.modules.models.logic()
        polyData = vtk.vtkPolyData()
        modelNode = modelsLogic.AddModel(polyData)
        modelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(namePrefix+"BaseLineModel"))
        self.moveNodeToHeartValveFolder(modelNode, 'CoaptationEdit')
        modelNode.GetDisplayNode().SetColor(1,1,0)
        modelNode.GetDisplayNode().SetOpacity(1.0)
        self.heartValveNode.SetNthNodeReferenceID("CoaptationBaseLineModel", coaptationModelIndex, modelNode.GetID())
        baseLineModelNode = modelNode
      self.applyProbeToRasTransformToNode(baseLineModelNode)
      coaptationModel.setBaseLineModelNode(baseLineModelNode)

      marginLineMarkupNode = self.heartValveNode.GetNthNodeReference("CoaptationMarginLineMarkup", coaptationModelIndex)
      if not marginLineMarkupNode:
        markupsLogic = slicer.modules.markups.logic()
        markupNodeId = markupsLogic.AddNewFiducialNode()
        markupNode = slicer.mrmlScene.GetNodeByID(markupNodeId)
        markupNode.SetName(slicer.mrmlScene.GetUniqueNameByString(namePrefix+"MarginLineMarkup"))
        markupNode.SetMarkupLabelFormat("") # don't add labels (such as A-1, A-2, ...) by default, the user will assign labels
        markupNode.SetLocked(True) # prevent accidental changes
        self.moveNodeToHeartValveFolder(markupNode, 'CoaptationEdit')
        markupDisplayNode = markupNode.GetDisplayNode()
        ValveModel.setGlyphSize(markupDisplayNode, coaptationModel.markupGlyphScale)
        markupDisplayNode.SetColor(0,0,1)
        self.heartValveNode.SetNthNodeReferenceID("CoaptationMarginLineMarkup", coaptationModelIndex, markupNode.GetID())
        marginLineMarkupNode = markupNode
      self.applyProbeToRasTransformToNode(marginLineMarkupNode)
      coaptationModel.setMarginLineMarkupNode(marginLineMarkupNode)

      marginLineModelNode = self.heartValveNode.GetNthNodeReference("CoaptationMarginLineModel", coaptationModelIndex)
      if not marginLineModelNode:
        modelsLogic = slicer.modules.models.logic()
        polyData = vtk.vtkPolyData()
        modelNode = modelsLogic.AddModel(polyData)
        modelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(namePrefix+"MarginLineModel"))
        self.moveNodeToHeartValveFolder(modelNode, 'CoaptationEdit')
        modelNode.GetDisplayNode().SetColor(1,0.5,0)
        modelNode.GetDisplayNode().SetOpacity(1.0)
        self.heartValveNode.SetNthNodeReferenceID("CoaptationMarginLineModel", coaptationModelIndex, modelNode.GetID())
        marginLineModelNode = modelNode
      self.applyProbeToRasTransformToNode(marginLineModelNode)
      coaptationModel.setMarginLineModelNode(marginLineModelNode)

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

    # Operations
    def updateAnnulusContourModel(self):
      self.annulusContourCurve.updateCurve()

    def getAnnulusContourPlane(self):
      """
      Get plane position and normal of the contour. Plane normal vector points in the direction of blood flow through the valve.
      """
      import numpy as np

      interpolatedPoints = self.annulusContourCurve.getInterpolatedPointsAsArray()
      [planePosition, planeNormal] = planeFit(interpolatedPoints)

      valveTypeName = self.heartValveNode.GetAttribute("ValveType")
      if not valveTypeName:
        valveTypeName = "unknown"
      valveType = self.valveTypePresets[valveTypeName]

      probeToRasMatrix = vtk.vtkMatrix4x4()
      slicer.vtkMRMLTransformNode.GetMatrixTransformBetweenNodes(self.getProbeToRasTransformNode(), None, probeToRasMatrix)
      planeNormal_Probe = np.append(planeNormal, 0)
      planeNormal_Ras = probeToRasMatrix.MultiplyPoint(planeNormal_Probe)

      if valveType["approximateFlowDirection"] == "posterior":
        # heart posterior direction in RAS: [0,-1,0]
        approximateFlowDirection_Ras = [0,-1,0]
      else:
        # heart anterior direction in RAS: [0,1,0]
        approximateFlowDirection_Ras = [0,1,0]

      # Make sure plane normal direction is approximately the same as flow direction
      if np.dot(approximateFlowDirection_Ras, planeNormal_Ras[0:3]) < 0:
        planeNormal = -planeNormal

      return planePosition, planeNormal

    # def updateAnnulusPlaneModel(self):
    #   interpolatedPoints = self.annulusContourCurve.getInterpolatedPointsAsArray()
    #   [planePosition, planeNormal] = planeFit(interpolatedPoints)
    #   logging.info("pos={0}, normal={1}".format(planePosition, planeNormal))

    def resampleAnnulusContourMarkups(self, samplingDistance):
      self.annulusContourCurve.resampleCurve(samplingDistance)

    def smoothAnnulusContour(self, numberOfFourierCoefficients, samplingDistance):
      self.annulusContourCurve.smoothCurveFourier(numberOfFourierCoefficients, samplingDistance)

    # def sortAnnulusContourMarkups(self):
    #   points = self.annulusContourCurve.getControlPointsAsArray()
    #   [planeCenterPos, planeNormal] = planeFit(points)
    #   print("Annulus: center={0}, normal={1}".format(planeCenterPos, planeNormal))

    def hasStoredAnnulusContour(self):
      originalPoints = self.heartValveNode.GetAttribute("AnnulusContourCoordinates")
      return originalPoints is not None

    def storeAnnulusContour(self):
      arr = self.annulusContourCurve.getControlPointsAsArray()
      self.heartValveNode.SetAttribute("AnnulusContourCoordinates", str(arr.tobytes()))

    def restoreAnnulusContour(self):
      originalPoints = self.heartValveNode.GetAttribute("AnnulusContourCoordinates")
      if not originalPoints:
        return
      import numpy as np
      arr = np.frombuffer(eval(originalPoints), dtype=np.float64)
      self.annulusContourCurve.setControlPointsFromArray(arr.reshape(3,-1))

    def setNonLabeledMarkupsVisibility(self, visible, unselectAll = True):
      annulusMarkupNode = self.getAnnulusContourMarkupNode()
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
        try:
          # Current API (Slicer-4.13 February 2022)
          if not annulusMarkupNode.GetNthControlPointLabel(i):
            annulusMarkupNode.SetNthControlPointVisibility(i, visible)
          if unselectAll and annulusMarkupNode.GetNthControlPointSelected(i):
            annulusMarkupNode.SetNthControlPointSelected(i, False)
        except:
          # Legacy API
          if not annulusMarkupNode.GetNthFiducialLabel(i):
            annulusMarkupNode.SetNthFiducialVisibility(i, visible)
          if unselectAll and annulusMarkupNode.GetNthFiducialSelected(i):
            annulusMarkupNode.SetNthFiducialSelected(i, False)
      annulusMarkupNode.EndModify(wasModify)

    def getAllMarkupLabels(self):
      """Get a list of all annulus point labels"""
      labels = []
      annulusMarkupNode = self.getAnnulusLabelsMarkupNode()
      try:
        # Slicer-4.13 (February 2022) and later
        numberOfControlPoints = annulusMarkupNode.GetNumberOfControlPoints()
      except:
        # fall back to older API
        numberOfControlPoints = annulusMarkupNode.GetNumberOfFiducials()
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
      annulusMarkupNode = self.getAnnulusLabelsMarkupNode()
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
        self.getAnnulusLabelsMarkupNode().GetNthControlPointPosition(annulusMarkupIndex, pos)
      except:
        # Legacy API
        self.getAnnulusLabelsMarkupNode().GetNthFiducialPosition(annulusMarkupIndex, pos)
      return np.array(pos)

    def getAnnulusMarkupPositionsByLabels(self, labels):
      return [self.getAnnulusMarkupPositionByLabel(label) for label in labels]

    def removeAnnulusMarkupLabel(self, label):
      annulusMarkupIndex = self.getAnnulusLabelsMarkupIndexByLabel(label)
      if annulusMarkupIndex<0:
        return
      self.getAnnulusLabelsMarkupNode().RemoveNthControlPoint(annulusMarkupIndex)

    def setAnnulusMarkupLabel(self, label, position):
      annulusMarkupIndex = self.getAnnulusLabelsMarkupIndexByLabel(label)
      if annulusMarkupIndex>=0:
        try:
          # Current API (Slicer-4.13 February 2022)
          self.getAnnulusLabelsMarkupNode().SetNthControlPointPosition(annulusMarkupIndex, position[0], position[1], position[2])
        except:
          # Legacy API
          self.getAnnulusLabelsMarkupNode().SetNthFiducialPosition(annulusMarkupIndex, position[0], position[1], position[2])
      else:
        self.getAnnulusLabelsMarkupNode().AddControlPoint(vtk.vtkVector3d(position), label)

    def getDefaultProbeToRasOrientation(self, probeToRasTransformMatrix):
      probePosition = self.getProbePosition()
      probePositionPreset = self.probePositionPresets[probePosition]
      probeToRasTransformMatrix.DeepCopy(createMatrixFromString(probePositionPreset['probeToRasTransformMatrix']))

    def setProbePosition(self, probePosition):
      if not self.heartValveNode:
        logging.error("setProbePosition failed: invalid heartValveNode")
        return
      self.heartValveNode.SetAttribute("ProbePosition", probePosition)
      self.updateProbeToRasTransform()

    def getProbePosition(self):
      if not self.heartValveNode:
        logging.error("getProbePosition failed: invalid heartValveNode")
        return None
      probePosition = self.heartValveNode.GetAttribute("ProbePosition")
      if not probePosition:
        probePosition = PROBE_POSITION_UNKNOWN
        self.setProbePosition(probePosition)
      return probePosition

    def setSliceOrientations(self, axialNode, ortho1Node, ortho2Node, orthoRotationDeg):

      axialSliceToRasTransformNode = self.getAxialSliceToRasTransformNode()
      axialSliceToRas = vtk.vtkMatrix4x4()
      axialSliceToRasTransformNode.GetMatrixTransformToParent(axialSliceToRas)

      paraAxialOrientationCode = 0

      # Axial (red) - not rotated by orthoRotationDeg
      axialNode.SetSliceToRASByNTP(
        axialSliceToRas.GetElement(0, 2), axialSliceToRas.GetElement(1, 2), axialSliceToRas.GetElement(2, 2),
        axialSliceToRas.GetElement(0, 0), axialSliceToRas.GetElement(1, 0), axialSliceToRas.GetElement(2, 0),
        axialSliceToRas.GetElement(0, 3), axialSliceToRas.GetElement(1, 3), axialSliceToRas.GetElement(2, 3),
        paraAxialOrientationCode)

      # Rotate around Z axis
      axialSliceToRasRotated = vtk.vtkMatrix4x4()
      rotationTransform = vtk.vtkTransform()
      rotationTransform.RotateZ(orthoRotationDeg)
      vtk.vtkMatrix4x4.Multiply4x4(axialSliceToRas, rotationTransform.GetMatrix(), axialSliceToRasRotated)

      rotationTransform = vtk.vtkTransform()
      probePositionPreset = self.probePositionPresets[self.getProbePosition()]

      # Ortho1 (yellow)
      rotationXYZ = probePositionPreset['axialSliceToOrtho1SliceRotationsDeg']
      rotationTransform.SetMatrix(axialSliceToRasRotated)
      rotationTransform.RotateX(rotationXYZ[0])
      rotationTransform.RotateY(rotationXYZ[1])
      rotationTransform.RotateZ(rotationXYZ[2])
      rotatedSliceToRas = rotationTransform.GetMatrix()
      ortho1Node.SetSliceToRASByNTP(
        rotatedSliceToRas.GetElement(0, 2), rotatedSliceToRas.GetElement(1, 2), rotatedSliceToRas.GetElement(2, 2),
        rotatedSliceToRas.GetElement(0, 0), rotatedSliceToRas.GetElement(1, 0), rotatedSliceToRas.GetElement(2, 0),
        rotatedSliceToRas.GetElement(0, 3), rotatedSliceToRas.GetElement(1, 3), rotatedSliceToRas.GetElement(2, 3),
        paraAxialOrientationCode)

      # Ortho2 (green)
      rotationXYZ = probePositionPreset['axialSliceToOrtho2SliceRotationsDeg']
      rotationTransform.SetMatrix(axialSliceToRasRotated)
      rotationTransform.RotateX(rotationXYZ[0])
      rotationTransform.RotateY(rotationXYZ[1])
      rotationTransform.RotateZ(rotationXYZ[2])
      rotatedSliceToRas = rotationTransform.GetMatrix()
      ortho2Node.SetSliceToRASByNTP(
        rotatedSliceToRas.GetElement(0, 2), rotatedSliceToRas.GetElement(1, 2), rotatedSliceToRas.GetElement(2, 2),
        rotatedSliceToRas.GetElement(0, 0), rotatedSliceToRas.GetElement(1, 0), rotatedSliceToRas.GetElement(2, 0),
        rotatedSliceToRas.GetElement(0, 3), rotatedSliceToRas.GetElement(1, 3), rotatedSliceToRas.GetElement(2, 3),
        paraAxialOrientationCode)

    def setSlicePositionAndOrientation(self, axialNode, ortho1Node, ortho2Node, position, orthoRotationDeg, axialSliceToRas=None):

      if axialSliceToRas is None:
        axialSliceToRasTransformNode = self.getAxialSliceToRasTransformNode()
        axialSliceToRas = vtk.vtkMatrix4x4()
        axialSliceToRasTransformNode.GetMatrixTransformToParent(axialSliceToRas)

      paraAxialOrientationCode = 0

      # Axial (red) - not rotated by orthoRotationDeg
      if axialNode:
        axialNode.SetSliceToRASByNTP(
          axialSliceToRas.GetElement(0, 2), axialSliceToRas.GetElement(1, 2), axialSliceToRas.GetElement(2, 2),
          axialSliceToRas.GetElement(0, 0), axialSliceToRas.GetElement(1, 0), axialSliceToRas.GetElement(2, 0),
          position[0], position[1], position[2],
          paraAxialOrientationCode)

      # Rotate around Z axis
      axialSliceToRasRotated = vtk.vtkMatrix4x4()
      rotationTransform = vtk.vtkTransform()
      # import math
      # orthoRotationDeg = math.atan2(directionVector[1], directionVector[0])/math.pi*180.0
      rotationTransform.RotateZ(orthoRotationDeg)
      vtk.vtkMatrix4x4.Multiply4x4(axialSliceToRas, rotationTransform.GetMatrix(), axialSliceToRasRotated)

      rotationTransform = vtk.vtkTransform()
      probePositionPreset = self.probePositionPresets[self.getProbePosition()]

      # Ortho1 (yellow)
      rotationXYZ = probePositionPreset['axialSliceToOrtho1SliceRotationsDeg']
      rotationTransform.SetMatrix(axialSliceToRasRotated)
      rotationTransform.RotateX(rotationXYZ[0])
      rotationTransform.RotateY(rotationXYZ[1])
      rotationTransform.RotateZ(rotationXYZ[2])
      rotatedSliceToRas = rotationTransform.GetMatrix()
      if ortho1Node:
        ortho1Node.SetSliceToRASByNTP(
          rotatedSliceToRas.GetElement(0, 2), rotatedSliceToRas.GetElement(1, 2), rotatedSliceToRas.GetElement(2, 2),
          rotatedSliceToRas.GetElement(0, 0), rotatedSliceToRas.GetElement(1, 0), rotatedSliceToRas.GetElement(2, 0),
          position[0], position[1], position[2],
          paraAxialOrientationCode)

      # Ortho2 (green)
      rotationXYZ = probePositionPreset['axialSliceToOrtho2SliceRotationsDeg']
      rotationTransform.SetMatrix(axialSliceToRasRotated)
      rotationTransform.RotateX(rotationXYZ[0])
      rotationTransform.RotateY(rotationXYZ[1])
      rotationTransform.RotateZ(rotationXYZ[2])
      rotatedSliceToRas = rotationTransform.GetMatrix()
      if ortho2Node:
        ortho2Node.SetSliceToRASByNTP(
          rotatedSliceToRas.GetElement(0, 2), rotatedSliceToRas.GetElement(1, 2), rotatedSliceToRas.GetElement(2, 2),
          rotatedSliceToRas.GetElement(0, 0), rotatedSliceToRas.GetElement(1, 0), rotatedSliceToRas.GetElement(2, 0),
          position[0], position[1], position[2],
          paraAxialOrientationCode)

    def updateValveNodeNames(self):
      valveType = self.heartValveNode.GetAttribute("ValveType")
      if not valveType:
        valveType = "unknown"
      valveName = valveType[0].upper()+valveType[1:]
      cardiacCyclePhase = self.heartValveNode.GetAttribute("CardiacCyclePhase")
      if not cardiacCyclePhase:
        cardiacCyclePhase = "unknown"
      cardiacCyclePhaseName = self.cardiacCyclePhasePresets[cardiacCyclePhase]["shortname"]
      volumeSequenceIndex = self.getVolumeSequenceIndexAsDisplayedString(self.getValveVolumeSequenceIndex())
      volumeSequenceIndex = f"_f{volumeSequenceIndex}" if not volumeSequenceIndex == "NA" else ""

      # heart valve name
      heartValveNodeName = f"{valveName}Valve-{cardiacCyclePhaseName}{volumeSequenceIndex}"
      currentNodeName = self.heartValveNode.GetName()
      if not currentNodeName.startswith(heartValveNodeName): # need to update
        self.heartValveNode.SetName(slicer.mrmlScene.GetUniqueNameByString(heartValveNodeName))

      # segmentation node name
      segmentationNodeName = f"{valveName}Valve-Segmentation-{cardiacCyclePhaseName}{volumeSequenceIndex}"
      leafletSegmentation = self.getLeafletSegmentationNode()
      if not leafletSegmentation:
        return
      currentNodeName = leafletSegmentation.GetName()
      if not currentNodeName.startswith(segmentationNodeName):  # need to update
        leafletSegmentation.SetName(slicer.mrmlScene.GetUniqueNameByString(segmentationNodeName))

      leafletVolumeNode = self.getLeafletVolumeNode()
      if leafletVolumeNode is not None:
        leafletVolumeNode.SetName(f"{self.heartValveNode.GetName()}-segmented")

    def setValveType(self, valveType):
      if not self.heartValveNode:
        logging.error("setValveType failed: invalid heartValveNode")
        return
      self.heartValveNode.SetAttribute("ValveType", valveType)
      self.updateValveNodeNames()

    def getValveType(self):
      valveType = self.heartValveNode.GetAttribute("ValveType")
      if not valveType:
        valveType = "unknown"
        self.setValveType(valveType)
      return valveType

    def setCardiacCyclePhase(self, cardiacCyclePhase):
      if not self.heartValveNode:
        logging.error("setCardiacCyclePhase failed: invalid heartValveNode")
        return
      self.heartValveNode.SetAttribute("CardiacCyclePhase", cardiacCyclePhase)
      self.updateValveNodeNames()

      if self.getAnnulusContourModelNode() and self.getAnnulusContourModelNode().GetDisplayNode():
        self.getAnnulusContourModelNode().GetDisplayNode().SetColor(self.getBaseColor())
      if self.getAnnulusContourMarkupNode() and self.getAnnulusContourMarkupNode().GetDisplayNode():
        self.getAnnulusContourMarkupNode().GetDisplayNode().SetColor(self.getBaseColor())
      if self.getAnnulusLabelsMarkupNode() and self.getAnnulusLabelsMarkupNode().GetDisplayNode():
        self.getAnnulusLabelsMarkupNode().GetDisplayNode().SetSelectedColor(self.getBaseColor())
        self.getAnnulusLabelsMarkupNode().GetDisplayNode().SetColor(self.getDarkColor())

    def getCardiacCyclePhase(self):
      cardiacCyclePhase = self.heartValveNode.GetAttribute("CardiacCyclePhase")
      if not cardiacCyclePhase:
        cardiacCyclePhase = "unknown"
        self.setCardiacCyclePhase(cardiacCyclePhase)
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
        [closestPointPositionOnAnnulusCurve, closestPointIdOnAnnulusCurve] = self.annulusContourCurve.getClosestPoint(pointPositionAnnulus)
        if np.linalg.norm(pointPositionAnnulus - closestPointPositionOnAnnulusCurve) > self.getAnnulusContourRadius() * 1.5 + 1.0:
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
      import numpy as np
      segmentInfo = []
      for label in splitPointLabels:
        pointPositionAnnulus = self.getAnnulusMarkupPositionByLabel(label)
        [closestPointPositionOnAnnulusCurve, closestPointIdOnAnnulusCurve] = self.annulusContourCurve.getClosestPoint(pointPositionAnnulus)
        segmentInfo.append({"pointLabel": label,
          "closestPointIdOnAnnulusCurve": closestPointIdOnAnnulusCurve,
          "closestPointPositionOnAnnulusCurve": closestPointPositionOnAnnulusCurve})

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

        curveSegmentLength = self.annulusContourCurve.getCurveLengthBetweenStartEndPoints(
          curveSegmentStartLabel["closestPointIdOnAnnulusCurve"],
          curveSegmentEndLabel["closestPointIdOnAnnulusCurve"])

        if splitBetweenPoints:
          # Split halfway between start and end label
          segmentLabel = curveSegmentStartLabel["pointLabel"]
          curveSegmentDividerPointPosition = self.annulusContourCurve.getPointAlongCurve(
            curveSegmentLength / 2.0, curveSegmentStartLabel["closestPointIdOnAnnulusCurve"])
          [curveSegmentDividerPointPosition, curveSegmentDividerPointIndex] = \
            self.annulusContourCurve.getClosestPoint(curveSegmentDividerPointPosition)
          lengthAfter = curveSegmentLength / 2.0
          lengthBefore = curveSegmentLength / 2.0
        else:
          # Split at start label
          segmentLabel = curveSegmentStartLabel["pointLabel"] + "-" + curveSegmentEndLabel["pointLabel"]
          [curveSegmentDividerPointPosition, curveSegmentDividerPointIndex] = self.annulusContourCurve.getClosestPoint(
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

    def createValveSurface(self, planePosition, planeNormal, kernelSizeMm=2.0, segmentIds=None, mergeMode=None,
                           smoothInZDirection=False):
      # TODO: kernelSizeMm maybe determine this using the size (diameter?) of the annulus
      """
      Create valve surface from the union of all segmented leaflets.
      """
      if not mergeMode:
        mergeMode = slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MAX
      import vtkSegmentationCorePython as vtkSegmentationCore

      # Create a temporary segment that is a union of all existing segments
      segmentationNode = self.getLeafletSegmentationNode()
      allLeafletsSegId = segmentationNode.GetSegmentation().AddEmptySegment()

      if not segmentIds:
        logging.info("[createValveSurface]: segmentIds were not provided. Getting valve surface from leaflet models directly")
        segmentIds = [leafletModel.segmentId for leafletModel in self.leafletModels]
      else:
        logging.info(f"[createValveSurface]: segmentIds were provided. Getting valve surface by merging {segmentIds}")

      for segId in segmentIds:
        segmentLabelmap = getBinaryLabelmapRepresentation(segmentationNode, segId)
        slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(
          segmentLabelmap, segmentationNode, allLeafletsSegId, mergeMode
        )

      # Apply smoothing to make sure leaflets are closed
      self.smoothSegment(segmentationNode, allLeafletsSegId, kernelSizeMm, smoothInZDirection=smoothInZDirection)

      # Temporary node, we don't add it to the scene
      allLeafletsSurfaceModelNode = slicer.vtkMRMLModelNode()
      allLeafletsSurfaceBoundaryMarkupNode = slicer.vtkMRMLMarkupsFiducialNode()

      allLeafletsModel = LeafletModel.LeafletModel()
      allLeafletsModel.setSegmentationNode(segmentationNode)
      allLeafletsModel.setSegmentId(allLeafletsSegId)
      allLeafletsModel.setSurfaceModelNode(allLeafletsSurfaceModelNode)
      allLeafletsModel.setSurfaceBoundaryMarkupNode(allLeafletsSurfaceBoundaryMarkupNode)

      #allLeafletsModel.autoDetectSurfaceBoundary(self, planePosition, planeNormal)
      allLeafletsModel.createSurfaceBoundaryFromCurve(planePosition, planeNormal, self.annulusContourCurve)
      allLeafletsModel.updateSurface()

      allLeafletsSurfacePolyData = allLeafletsSurfaceModelNode.GetPolyData()

      # Delete temporary segment
      segmentationNode.RemoveSegment(allLeafletsSegId)

      # check if surface
      edges = vtk.vtkFeatureEdges()
      edges.SetInputData(allLeafletsSurfacePolyData)
      edges.FeatureEdgesOff()
      edges.BoundaryEdgesOn()
      edges.NonManifoldEdgesOn()
      edges.Update()
      success = edges.GetOutput().GetNumberOfCells() > 0

      return allLeafletsSurfacePolyData if success else None

    @staticmethod
    def setGlyphSize(markupsDisplayNode, glyphSize):
      markupsDisplayNode.SetGlyphSize(glyphSize)
      markupsDisplayNode.SetUseGlyphScale(False)

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

    def getCoaptationsForLeaflet(self, leafletModel):
      coaptations = []
      for coaptation in self.coaptationModels:
        connectedLeaflets = coaptation.getConnectedLeaflets(self)
        if leafletModel in connectedLeaflets:
          coaptations.append(coaptation)
      return coaptations


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
  transformMatrix = vtk.vtkMatrix4x4()
  transformMatrixArray = list(map(float, filter(None, transformMatrixString.split(' '))))
  for r in range(4):
    for c in range(4):
      transformMatrix.SetElement(r, c, transformMatrixArray[r * 4 + c])
  return transformMatrix


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
