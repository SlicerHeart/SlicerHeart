import os
import slicer

import HeartValveLib
from .base import ValveBatchExportRule


class ValveVolumeExportRule(ValveBatchExportRule):

  BRIEF_USE = "Image volume (.nrrd)"
  DETAILED_DESCRIPTION = "Export individual image volume frame for each valve model"

  CMD_FLAG = "-iv"

  class NoSequenceBrowserNodeFound(Exception):
    pass

  @classmethod
  def getSequenceBrowserNode(cls, masterOutputNode):
    browserNodes = slicer.mrmlScene.GetNodesByClass('vtkMRMLSequenceBrowserNode')
    browserNodes.UnRegister(None)
    for idx in range(browserNodes.GetNumberOfItems()):
      browserNode = browserNodes.GetItemAsObject(idx)
      if browserNode.GetProxyNode(browserNode.GetMasterSequenceNode()) is masterOutputNode:
        browserNode.SetIndexDisplayMode(browserNode.IndexDisplayAsIndex)
        return browserNode
    raise cls.NoSequenceBrowserNodeFound()

  @classmethod
  def setSequenceFrameNumber(cls, valveModel, frameNumber):
    valveVolume = valveModel.getValveVolumeNode()
    seqBrowser = cls.getSequenceBrowserNode(valveVolume)
    seqBrowser.SetSelectedItemNumber(1)
    seqBrowser.SetSelectedItemNumber(frameNumber)

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
      valveType = valveModel.heartValveNode.GetAttribute('ValveType')
      cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
      valveModelName = self.generateValveModelName(filename, valveType, cardiacCyclePhaseName, suffix="volume")
      volumeNode = valveModel.getValveVolumeNode()
      if volumeNode is None:
        self.addLog(f"  Valve volume export skipped (valve volume is missing) - {valveModelName}")
        continue

      volumeSequenceBrowserNode = HeartValveLib.HeartValves.getSequenceBrowserNodeForMasterOutputNode(volumeNode)
      volumeSequenceNode = \
        volumeSequenceBrowserNode.GetMasterSequenceNode() if volumeSequenceBrowserNode is not None else None
      storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLNRRDStorageNode")
      if volumeSequenceNode is None:
        # valve volume is not part of a sequence
        storageNode.SetFileName(os.path.join(self.outputDir, f"{valveModelName}.nrrd"))
        nodeToWrite = volumeNode
      else:  # save specific frame of the current valve model
        frameNumber = self.getAssociatedFrameNumber(valveModel)
        self.setSequenceFrameNumber(valveModel, frameNumber)
        valveModelName = \
          self.generateValveModelName(filename, valveType, cardiacCyclePhaseName, frameNumber, suffix="volume")
        storageNode.SetFileName(os.path.join(self.outputDir, f"{valveModelName}.nrrd"))
        nodeToWrite = valveModel.getValveVolumeNode()

      if not storageNode.WriteData(nodeToWrite):
        self.addLog(f"  Valve volume export skipped (file writing failed) - {valveModelName}")
      slicer.mrmlScene.RemoveNode(storageNode)
