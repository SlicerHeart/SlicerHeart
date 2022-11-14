import os
from pathlib import Path

import numpy as np
from .base import ValveBatchExportRule
from HeartValveLib.util import getClosestCurvePointIndexToPosition, getClosestPointPositionAlongCurve


class AnnulusContourCoordinatesExportRule(ValveBatchExportRule):

  BRIEF_USE = "Annulus contour 3D coordinates (.csv)"
  DETAILED_DESCRIPTION = "Export 3D coordinates of annulus contour points"
  COLUMNS = \
    ['Filename', 'Phase', 'FrameNumber', 'Valve', 'AnnulusContourX', 'AnnulusContourY', 'AnnulusContourZ', 'AnnulusContourLabel']
  CSV_OUTPUT_FILENAME = 'AnnulusContourPoints.csv'

  OUTPUT_CSV_FILES = [
    CSV_OUTPUT_FILENAME
  ]

  CMD_FLAG = "-acc"

  def processStart(self):
    self.resultsTableNode = self.createTableNode(*self.COLUMNS)

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      # Add a row for each contour point
      curvePoints = valveModel.annulusContourCurve.GetCurve().GetPoints()
      numberOfAnnulusContourPoints = curvePoints.GetNumberOfPoints()
      startingRowIndex = self.resultsTableNode.GetNumberOfRows()
      filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
      valveType = valveModel.heartValveNode.GetAttribute('ValveType')
      cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
      frameNumber = self.getAssociatedFrameNumber(valveModel)
      for i in range(numberOfAnnulusContourPoints):
        pos = [0.0, 0.0, 0.0]
        curvePoints.GetPoint(i, pos)
        self.addRowData(self.resultsTableNode, filename, cardiacCyclePhaseName, str(frameNumber), valveType, *[f'{p:.2f}' for p in pos])
      # Add labels to label column
      for label in valveModel.getAnnulusMarkupLabels():
        pos = valveModel.getAnnulusMarkupPositionByLabel(label)
        closestPointIdOnAnnulusCurve = \
          getClosestCurvePointIndexToPosition(valveModel.annulusContourCurve, pos)
        closestPointPositionOnAnnulusCurve = \
          getClosestPointPositionAlongCurve(valveModel.annulusContourCurve, pos)
        if np.linalg.norm(np.array(pos) - np.array(closestPointPositionOnAnnulusCurve)) > valveModel.getAnnulusContourRadius() * 1.5:
          # it is not a label on the annulus (for example, centroid), ignore it
          continue
        self.resultsTableNode.SetCellText(startingRowIndex + closestPointIdOnAnnulusCurve, 7, label.strip())

  def processEnd(self):
    self.writeTableNodeToCsv(self.resultsTableNode, self.CSV_OUTPUT_FILENAME)

  def mergeTables(self, inputDirectories, outputDirectory):
    contourPointsCSVs = self.findCorrespondingFilesInDirectories(inputDirectories, self.CSV_OUTPUT_FILENAME)
    self.concatCSVsAndSave(contourPointsCSVs, Path(outputDirectory) / self.CSV_OUTPUT_FILENAME, removeDuplicateRows=True)