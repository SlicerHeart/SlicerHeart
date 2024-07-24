import qt
import os
from pathlib import Path

import numpy as np
from .base import ValveBatchExportRule
from HeartValveLib.util import (
  getClosestCurvePointIndexToPosition,
  getClosestControlPointIndexToPositionWorld,
  getClosestPointPositionAlongCurve
)


class AnnulusContourCoordinatesExportRule(ValveBatchExportRule):

  BRIEF_USE = "Annulus contour 3D coordinates (.csv)"
  DETAILED_DESCRIPTION = "Export 3D coordinates of annulus contour points"
  USER_INTERFACE = True

  COLUMNS = \
    ['Filename', 'Phase', 'FrameNumber', 'Valve', 'AnnulusContourX', 'AnnulusContourY', 'AnnulusContourZ', 'AnnulusContourLabel']
  CURVE_POINTS_CSV_OUTPUT_FILENAME = 'AnnulusContourCurvePoints.csv'
  CONTROL_POINTS_CSV_OUTPUT_FILENAME = 'AnnulusContourControlPoints.csv'

  OUTPUT_CSV_FILES = [
    CURVE_POINTS_CSV_OUTPUT_FILENAME,
    CONTROL_POINTS_CSV_OUTPUT_FILENAME
  ]

  CMD_FLAG = "-acc"
  CMD_FLAG_1 = "-accu" # curve point coordinates
  CMD_FLAG_2 = "-accc" # control point coordinates

  OTHER_FLAGS = []
  EXPORT_CURVE_POINT_COORDINATES = True
  EXPORT_CONTROL_POINT_COORDINATES = False

  @classmethod
  def setupUI(cls, layout):
    curvePointsCheckbox = qt.QCheckBox(f"Export Curve Points ({cls.CURVE_POINTS_CSV_OUTPUT_FILENAME})")
    controlPointsCheckbox = qt.QCheckBox(f"Export Control Points ({cls.CONTROL_POINTS_CSV_OUTPUT_FILENAME})")

    def onCurvePointsCheckboxModified(checked):
      cls.EXPORT_CURVE_POINT_COORDINATES = checked
      if checked:
        cls.OTHER_FLAGS.append(cls.CMD_FLAG_1)
      else:
        if cls.CMD_FLAG_1 in cls.OTHER_FLAGS:
          cls.OTHER_FLAGS.remove(cls.CMD_FLAG_1)
          if not cls.OTHER_FLAGS:
            controlPointsCheckbox.checked = True

    def onControlPointsCheckboxModified(checked):
      cls.EXPORT_CONTROL_POINT_COORDINATES = checked
      if checked:
        cls.OTHER_FLAGS.append(cls.CMD_FLAG_2)
      else:
        if cls.CMD_FLAG_2 in cls.OTHER_FLAGS:
          cls.OTHER_FLAGS.remove(cls.CMD_FLAG_2)
          if not cls.OTHER_FLAGS:
            curvePointsCheckbox.checked = True

    curvePointsCheckbox.stateChanged.connect(onCurvePointsCheckboxModified)
    curvePointsCheckbox.checked = cls.EXPORT_CURVE_POINT_COORDINATES

    controlPointsCheckbox.stateChanged.connect(onControlPointsCheckboxModified)
    controlPointsCheckbox.checked = cls.EXPORT_CONTROL_POINT_COORDINATES

    layout.addWidget(curvePointsCheckbox)
    layout.addWidget(controlPointsCheckbox)

  def processStart(self):
    self.curveResultsTableNode = self.createTableNode(*self.COLUMNS) if self.EXPORT_CURVE_POINT_COORDINATES else None
    self.controlResultsTableNode = self.createTableNode(*self.COLUMNS) if self.EXPORT_CONTROL_POINT_COORDINATES else None

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():

      sequenceBrowserNode = valveModel.valveBrowserNode
      for annotatedFrameNumber in range(sequenceBrowserNode.GetNumberOfItems()):
        sequenceBrowserNode.SetSelectedItemNumber(annotatedFrameNumber)

        if self.EXPORT_CURVE_POINT_COORDINATES:
          self.addAnnulusContourCurvePoints(sceneFileName, valveModel)
        if self.EXPORT_CONTROL_POINT_COORDINATES:
          self.addAnnulusContourControlPoints(sceneFileName, valveModel)

  def addAnnulusContourCurvePoints(self, sceneFileName, valveModel):
    # Add a row for each contour point
    curvePoints = valveModel.annulusContourCurveNode.GetCurve().GetPoints()
    numberOfAnnulusContourPoints = curvePoints.GetNumberOfPoints()
    startingRowIndex = self.curveResultsTableNode.GetNumberOfRows()
    filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
    valveType = valveModel.heartValveNode.GetAttribute('ValveType')
    cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
    frameNumber = self.getAssociatedFrameNumber(valveModel)
    for i in range(numberOfAnnulusContourPoints):
      pos = [0.0, 0.0, 0.0]
      curvePoints.GetPoint(i, pos)
      self.addRowData(self.curveResultsTableNode, filename, cardiacCyclePhaseName, str(frameNumber), valveType,
                      *[f'{p:.2f}' for p in pos])
    # Add labels to label column
    for label in valveModel.getAnnulusMarkupLabels():
      pos = valveModel.getAnnulusMarkupPositionByLabel(label)

      closestPointIdOnAnnulusCurve = \
        getClosestCurvePointIndexToPosition(valveModel.annulusContourCurveNode, pos)
      closestPointPositionOnAnnulusCurve = \
        getClosestPointPositionAlongCurve(valveModel.annulusContourCurveNode, pos)

      if np.linalg.norm(
          np.array(pos) - np.array(closestPointPositionOnAnnulusCurve)) > valveModel.getAnnulusContourRadius() * 1.5:
        # it is not a label on the annulus (for example, centroid), ignore it
        continue
      self.curveResultsTableNode.SetCellText(startingRowIndex + closestPointIdOnAnnulusCurve, 7, label.strip())

  def addAnnulusContourControlPoints(self, sceneFileName, valveModel):
    filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
    # Add a row for each control point
    markupsNode = valveModel.annulusContourCurveNode
    numberOfAnnulusContourPoints = markupsNode.GetNumberOfControlPoints()
    startingRowIndex = self.controlResultsTableNode.GetNumberOfRows()
    valveType = valveModel.heartValveNode.GetAttribute('ValveType')
    cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
    frameNumber = self.getAssociatedFrameNumber(valveModel)
    for i in range(numberOfAnnulusContourPoints):
      pos = [0.0, 0.0, 0.0]
      markupsNode.GetNthControlPointPosition(i, pos)
      self.addRowData(self.controlResultsTableNode, filename, cardiacCyclePhaseName, str(frameNumber), valveType,
                      *[f'{p:.2f}' for p in pos])
    # Add labels to label column
    for label in valveModel.getAnnulusMarkupLabels():
      pos = valveModel.getAnnulusMarkupPositionByLabel(label)
      closestControlPointIdOnAnnulusCurve = \
        getClosestControlPointIndexToPositionWorld(valveModel.annulusContourCurveNode, pos)
      closestPointPositionOnAnnulusCurve = [0.0, 0.0, 0.0]
      valveModel.annulusContourCurveNode.GetNthControlPointPosition(closestControlPointIdOnAnnulusCurve,
                                                                closestPointPositionOnAnnulusCurve)
      if np.linalg.norm(np.array(pos) - np.array(closestPointPositionOnAnnulusCurve)) > valveModel.getAnnulusContourRadius() * 1.5:
        # it is not a label on the annulus (for example, centroid), ignore it
        continue
      self.controlResultsTableNode.SetCellText(startingRowIndex + closestControlPointIdOnAnnulusCurve, 7, label.strip())

  def processEnd(self):
    if self.curveResultsTableNode:
      self.writeTableNodeToCsv(self.curveResultsTableNode, self.CURVE_POINTS_CSV_OUTPUT_FILENAME)

    if self.controlResultsTableNode:
      self.writeTableNodeToCsv(self.controlResultsTableNode, self.CONTROL_POINTS_CSV_OUTPUT_FILENAME)

  def mergeTables(self, inputDirectories, outputDirectory):
    if self.EXPORT_CURVE_POINT_COORDINATES:
      curvePointsCSVs = self.findCorrespondingFilesInDirectories(inputDirectories,
                                                                   self.CURVE_POINTS_CSV_OUTPUT_FILENAME)
      self.concatCSVsAndSave(curvePointsCSVs, Path(outputDirectory) / self.CURVE_POINTS_CSV_OUTPUT_FILENAME,
                             removeDuplicateRows=True)

    if self.EXPORT_CONTROL_POINT_COORDINATES:
      controlPointsCSVs = self.findCorrespondingFilesInDirectories(inputDirectories,
                                                                   self.CONTROL_POINTS_CSV_OUTPUT_FILENAME)
      self.concatCSVsAndSave(controlPointsCSVs, Path(outputDirectory) / self.CONTROL_POINTS_CSV_OUTPUT_FILENAME,
                             removeDuplicateRows=True)
