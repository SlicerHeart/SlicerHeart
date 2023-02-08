import os
import slicer

from .base import ImageValveBatchExportRule


class ValveVolumeExportRule(ImageValveBatchExportRule):

  BRIEF_USE = "Image volume"
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
      volumeNode = valveModel.getValveVolumeNode()
      if volumeNode is None:
        self.addLog(f"  Valve volume export skipped (valve volume is missing) - {sceneFileName}")
        continue

      frameNumber = self.getAssociatedFrameNumber(valveModel)
      valveModelName = self.generateValveModelName(sceneFileName, valveModel, "volume")
      self.setSequenceFrameNumber(valveModel, frameNumber)
      outputFileName = os.path.join(self.outputDir, f"{valveModelName}{self.FILE_FORMAT}")
      nodeToWrite = valveModel.getValveVolumeNode()

      if self.FILE_FORMAT == ".nrrd":
        storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLNRRDStorageNode")
        storageNode.SetFileName(outputFileName)
        if not storageNode.WriteData(nodeToWrite):
          self.addLog(f"  Valve volume export skipped (file writing failed) - {valveModelName}")
        slicer.mrmlScene.RemoveNode(storageNode)
      else: # .nii.gz
        slicer.util.saveNode(nodeToWrite, outputFileName)
