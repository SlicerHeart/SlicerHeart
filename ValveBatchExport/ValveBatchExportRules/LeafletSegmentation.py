import os
from pathlib import Path
import qt

import HeartValveLib.Constants
import slicer
from .utils import *
from .base import (
  ImageValveBatchExportRule,
  ValveBatchExportPlugin
)


class LeafletSegmentationExportRuleWidget(ValveBatchExportPlugin):

  def __init__(self, checked=False):
    ValveBatchExportPlugin.__init__(self, LeafletSegmentationExportRule, checked)

  def setup(self):
    ValveBatchExportPlugin.setup(self)
    layout = self.getOptionsLayout()

    logic = self.logic

    def onModified(checked):
      logic.ONE_FILE_PER_SEGMENT = checked
      if checked:
        logic.OTHER_FLAGS.append(logic.CMD_FLAG_1)
      else:
        if logic.CMD_FLAG_1 in logic.OTHER_FLAGS:
          logic.OTHER_FLAGS.remove(logic.CMD_FLAG_1)

    checkbox = qt.QCheckBox("One file per segment")
    checkbox.stateChanged.connect(onModified)
    checkbox.checked = logic.ONE_FILE_PER_SEGMENT

    layout.addWidget(checkbox)


class LeafletSegmentationExportRule(ImageValveBatchExportRule):

  BRIEF_USE = "Leaflet segmentation (.nrrd)"
  DETAILED_DESCRIPTION = "Export leaflet segmentation as 4D nrrd file (each 3D volume is one segment)"

  CMD_FLAG = "-seg"
  CMD_FLAG_1 = "-ssep"  # individual segmentation file per segment

  OTHER_FLAGS = []
  ONE_FILE_PER_SEGMENT = False

  def processScene(self, sceneFileName):

    for valveModel in self.getHeartValveModelNodes():
      valveModelName = self.generateValveModelName(sceneFileName, valveModel)
      leafletSegmentationNode = valveModel.getLeafletSegmentationNode()

      if leafletSegmentationNode is None:
        self.addLog(f"  Leaflet segmentation export skipped (segmentation is missing) - {valveModelName}")
        continue

      if isEmpty(leafletSegmentationNode):
        self.addLog(f"  Leaflet segmentation export skipped (empty segmentation) - {valveModelName}")
        continue

      if deleteValveMask(leafletSegmentationNode) is True:
        self.addLog(
          f"Found segment with id {HeartValveLib.Constants.VALVE_MASK_SEGMENT_ID}. Deleted segment for export")

      if self.ONE_FILE_PER_SEGMENT:
        self._saveSegmentsIntoSeparateFiles(leafletSegmentationNode, valveModelName)
      else:
        if leafletSegmentationNode.GetSegmentation().GetNumberOfSegments() > 1:
          self.addLog("Sorting individual leaflets")
          m = checkAndSortSegments(leafletSegmentationNode, valveModel.getValveType())  # sort segments
          if m:
            self.addLog(m)
          outputFileName = f"{valveModelName}_leaflets.seg{self.FILE_FORMAT}"
        else:
          self.addLog("Only single segmentation found")
          outputFileName = f"{valveModelName}_whole_valve.seg{self.FILE_FORMAT}"

        outputFileName = os.path.join(self.outputDir, outputFileName)

        if self.FILE_FORMAT == self.FILE_FORMAT_OPTIONS[0]: # .nrrd
          storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationStorageNode")
          storageNode.SetFileName(outputFileName)

          if not storageNode.WriteData(leafletSegmentationNode):
            self.addLog(f"  Leaflet segmentation export skipped (file writing failed) - {valveModelName}")
          slicer.mrmlScene.RemoveNode(storageNode)
        else:
            showAllSegments(leafletSegmentationNode)
            labelNode = createLabelNodeFromVisibleSegments(leafletSegmentationNode, valveModel,
                                                           "LeafletSegmentation")
            slicer.util.saveNode(labelNode, outputFileName)

  def _saveSegmentsIntoSeparateFiles(self, segmentationNode, prefix):
    segmentationsLogic = slicer.modules.segmentations.logic()

    for segmentID in getAllSegmentIDs(segmentationNode):
      labelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
      showOnlySegmentWithSegmentID(segmentationNode, segmentID)
      segmentationsLogic.ExportVisibleSegmentsToLabelmapNode(segmentationNode, labelNode)
      segmentName = segmentationNode.GetSegmentation().GetSegment(segmentID).GetName()
      filename = f"{prefix}_{segmentName.replace(' ', '_')}.seg{self.FILE_FORMAT}"
      slicer.util.saveNode(labelNode, str(Path(self.outputDir) / filename))


