import os
import slicer
from pathlib import Path
from .base import ValveBatchExportRule


class ValveLandmarksExportRule(ValveBatchExportRule):

  BRIEF_USE = "Valve landmarks (.fcsv)"
  DETAILED_DESCRIPTION = "Export valve landmark points into .fcsv file."

  CMD_FLAG = "-fcsv"

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      sequenceBrowserNode = valveModel.valveBrowserNode
      for annotatedFrameNumber in range(sequenceBrowserNode.GetNumberOfItems()):
        sequenceBrowserNode.SetSelectedItemNumber(annotatedFrameNumber)

        frameNumber = self.getAssociatedFrameNumber(valveModel)
        annulusMarkupNode = valveModel.getAnnulusLabelsMarkupNode()
        filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
        valveType = valveModel.getValveType()
        cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
        valveModelName = self.generateValveModelName(filename, valveType, cardiacCyclePhaseName, frameNumber, "landmarks")
        slicer.util.saveNode(annulusMarkupNode, str(Path(self.outputDir) / f"{valveModelName}.fcsv"))