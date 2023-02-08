import os
import slicer

import HeartValveLib
from .base import ValveBatchExportRule


class ValveVolumeExportRule(ValveBatchExportRule):

  BRIEF_USE = "Image volume sequence"
  DETAILED_DESCRIPTION = "Export image volume as 4D nrrd file (each 3D volume is one time point)"

  CMD_FLAG = "-iv"

  def processScene(self, sceneFileName):
    filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
    outputFilePath = os.path.join(self.outputDir, f"{filename}.seq.nrrd")
    for valveModel in self.getHeartValveModelNodes():
      volumeNode = valveModel.getValveVolumeNode()
      if volumeNode is None:
        self.addLog(f"  Valve volume export skipped (valve volume is missing) - {filename}")
        continue
      volumeSequenceBrowserNode = HeartValveLib.HeartValves.getSequenceBrowserNodeForMasterOutputNode(volumeNode)
      volumeSequenceNode = volumeSequenceBrowserNode.GetMasterSequenceNode() if volumeSequenceBrowserNode is not None else None
      if volumeSequenceNode is not None:
        # input is a sequence, need to clip the entire sequence
        storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVolumeSequenceStorageNode")
        storageNode.SetFileName(outputFilePath)
        nodeToWrite = volumeSequenceNode
        if not storageNode.WriteData(nodeToWrite):
          self.addLog(f"  Valve volume export skipped (file writing failed) - {filename}")
        slicer.mrmlScene.RemoveNode(storageNode)
        break
