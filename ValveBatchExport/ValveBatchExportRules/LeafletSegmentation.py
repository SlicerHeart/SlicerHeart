import os
from pathlib import Path

import slicer
from .base import ValveBatchExportRule


class LeafletSegmentationExportRule(ValveBatchExportRule):

  BRIEF_USE = "Segmentation (.nrrd)"
  DETAILED_DESCRIPTION = "Export segmentation as 4D nrrd file (each 3D volume is one segment)"

  CMD_FLAG = "-seg"

  def processScene(self, sceneFileName):

    for valveModel in self.getHeartValveModelNodes():
      frameNumber = self.getAssociatedFrameNumber(valveModel)
      filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
      valveType = valveModel.heartValveNode.GetAttribute('ValveType')
      cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
      valveModelName = self.generateValveModelName(filename, valveType, cardiacCyclePhaseName, frameNumber)
      segNode = valveModel.getLeafletSegmentationNode()

      if segNode is None:
        self.addLog(f"  Segmentation export skipped (segmentation is missing) - {valveModelName}")
        continue

      segmentation = segNode.GetSegmentation()

      segmentationBounds = [0, -1, 0, -1, 0, -1]
      segmentation.GetBounds(segmentationBounds)
      if segmentationBounds[0] > segmentationBounds[1] or \
        segmentationBounds[2] > segmentationBounds[3] or \
        segmentationBounds[4] > segmentationBounds[5]:
        self.addLog(f"  Segmentation export skipped (empty segmentation) - {valveModelName}")
        continue

      extensions = [
        ".nrrd",
        ".nii.gz"
      ]
      ext = extensions[1]

      self._saveSegmentsIntoSeparateFiles(valveModel, valveModelName, ext)


  def _saveSegmentsIntoSeparateFiles(self, valveModel, prefix, fileExtension):
    segmentationNode = valveModel.getLeafletSegmentationNode()
    segmentationsLogic = slicer.modules.segmentations.logic()

    from HeartValveLib.util import getAllSegmentIDs
    labelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    for segmentID in getAllSegmentIDs(segmentationNode):
      from HeartValveLib.Constants import VALVE_MASK_SEGMENT_ID
      if segmentID == VALVE_MASK_SEGMENT_ID:
        self.addLog(f"    Skipping Segmentation export for segment with id '{VALVE_MASK_SEGMENT_ID}'")
        continue
      showOnlySegmentWithSegmentID(segmentationNode, segmentID)
      segmentationsLogic.ExportVisibleSegmentsToLabelmapNode(segmentationNode, labelNode,
                                                             valveModel.getLeafletVolumeNode())
      segmentName = segmentationNode.GetSegmentation().GetSegment(segmentID).GetName()
      filename = f"{prefix}_{segmentName.replace(' ', '_')}{fileExtension}"
      slicer.util.saveNode(labelNode, str(Path(self.outputDir) / filename))
    slicer.mrmlScene.RemoveNode(labelNode)


def showOnlySegmentWithSegmentID(segmentationNode, segmentID):
  hideAllSegments(segmentationNode)
  segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, True)


def hideAllSegments(segmentationNode):
  from HeartValveLib.util import getAllSegmentIDs
  for segmentID in getAllSegmentIDs(segmentationNode):
    segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentID, False)
