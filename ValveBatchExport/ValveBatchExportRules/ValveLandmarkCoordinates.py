import os
from .base import ValveBatchExportRule


class ValveLandmarkCoordinatesExportRule(ValveBatchExportRule):

  BRIEF_USE = "Valve landmark points 3D coordinates (.csv)"
  DETAILED_DESCRIPTION = "Export 3D coordinates of valve landmark points."
  COLUMNS = \
    ['Filename', 'Phase', 'Valve', 'FrameNumber', 'LandmarkLabel', 'LandmarkR', 'LandmarkA', 'LandmarkS']
  CSV_OUTPUT_FILENAME = 'ValveLandmarkPoints.csv'

  OUTPUT_CSV_FILES = [
    CSV_OUTPUT_FILENAME
  ]

  CMD_FLAG = "-lc"

  def processStart(self):
    self.resultsTableNode = self.createTableNode(*self.COLUMNS)

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      frameNumber = self.getAssociatedFrameNumber(valveModel)
      annulusMarkupNode = valveModel.getAnnulusLabelsMarkupNode()
      numberOfMarkups = annulusMarkupNode.GetNumberOfFiducials()
      filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
      valveType = valveModel.heartValveNode.GetAttribute('ValveType')
      cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
      for markupIndex in range(numberOfMarkups):
        markupLabel = valveModel.getAnnulusLabelsMarkupNode().GetNthFiducialLabel(markupIndex)
        pos = [0.0, 0.0, 0.0]
        valveModel.getAnnulusLabelsMarkupNode().GetNthFiducialPosition(markupIndex, pos)
        self.addRowData(self.resultsTableNode, filename, cardiacCyclePhaseName, str(frameNumber), valveType, markupLabel,
                        *[f'{p:.2f}' for p in pos])

  def processEnd(self):
    self.writeTableNodeToCsv(self.resultsTableNode, self.CSV_OUTPUT_FILENAME)

  def mergeTables(self, inputDirectories, outputDirectory):
    from pathlib import Path
    contourPointsCSVs = self.findCorrespondingFilesInDirectories(inputDirectories, self.CSV_OUTPUT_FILENAME)
    self.concatCSVsAndSave(contourPointsCSVs, Path(outputDirectory) / self.CSV_OUTPUT_FILENAME, removeDuplicateRows=True)