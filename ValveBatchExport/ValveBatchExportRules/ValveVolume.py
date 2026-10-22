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

    # A scene may contain several valves, analyzed on the same or on different volume sequences.
    # Each volume sequence is written once, into a file named after the valve(s) that use it.
    valveTypesByVolumeSequence = {}
    for valveModel in self.getHeartValveModelNodes():
      if not self.getExportedTimePoints(valveModel):
        continue
      valveType = valveModel.getValveType()
      volumeNode = valveModel.getValveVolumeNode()
      if volumeNode is None:
        self.addLog(f"  Valve volume export skipped (valve volume is missing) - {filename} {valveType}")
        continue
      volumeSequenceBrowserNode = HeartValveLib.HeartValves.getSequenceBrowserNodeForMasterOutputNode(volumeNode)
      volumeSequenceNode = volumeSequenceBrowserNode.GetMasterSequenceNode() if volumeSequenceBrowserNode is not None else None
      if volumeSequenceNode is None:
        self.addLog(f"  Valve volume export skipped (valve volume is not a sequence) - {filename} {valveType}")
        continue
      valveTypes = valveTypesByVolumeSequence.setdefault(volumeSequenceNode, [])
      if valveType not in valveTypes:
        valveTypes.append(valveType)

    for volumeSequenceNode, valveTypes in valveTypesByVolumeSequence.items():
      outputFileName = self.generateUniqueName("_".join([filename] + valveTypes)) + ".seq.nrrd"
      storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVolumeSequenceStorageNode")
      storageNode.SetFileName(os.path.join(self.outputDir, outputFileName))
      if not storageNode.WriteData(volumeSequenceNode):
        self.addLog(f"  Valve volume export skipped (file writing failed) - {outputFileName}")
      slicer.mrmlScene.RemoveNode(storageNode)
