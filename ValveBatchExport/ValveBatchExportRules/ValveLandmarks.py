import slicer
from pathlib import Path
from .base import ValveBatchExportRule


class ValveLandmarksExportRule(ValveBatchExportRule):

  BRIEF_USE = "Valve landmarks (.fcsv)"
  DETAILED_DESCRIPTION = "Export valve landmark points into .fcsv file."

  CMD_FLAG = "-fcsv"

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      annulusMarkupNode = valveModel.getAnnulusLabelsMarkupNode()
      valveModelName = self.generateValveModelName(sceneFileName, valveModel, "landmarks")
      slicer.util.saveNode(annulusMarkupNode, str(Path(self.outputDir) / f"{valveModelName}.fcsv"))