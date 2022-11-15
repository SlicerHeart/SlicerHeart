import HeartValveLib
import math
import numpy as np
import SmoothCurve


class PapillaryModel:

  @property
  def papillaryLine(self):
    return self.getPapillaryLineMarkupNode()

  @papillaryLine.setter
  def papillaryLine(self, node):
    self.setPapillaryLineMarkupNode(node)

  def __init__(self):
    self.markupGlyphScale = 1.0
    self.markupsCurveNode = None

  def getName(self):
    return self.markupsCurveNode.GetName()

  def setPapillaryLineMarkupNode(self, markupsNode):
    self.markupsCurveNode = markupsNode
    markupsDisplayNode = markupsNode.GetDisplayNode()
    markupsDisplayNode.SetCurveLineSizeMode(markupsDisplayNode.UseLineDiameter)
    markupsDisplayNode.SetLineDiameter(self.markupGlyphScale/4.0)

  def getPapillaryLineMarkupNode(self):
    return self.markupsCurveNode

  def getMuscleChordLength(self):
    markupsNode = self.getPapillaryLineMarkupNode()
    if markupsNode and markupsNode.GetNumberOfControlPoints() >= 3:
      muscleTipPointIndex = markupsNode.GetCurvePointIndexFromControlPointIndex(1)
      return markupsNode.GetCurveLengthBetweenStartEndPointsWorld(muscleTipPointIndex,
                                                                  markupsNode.GetCurve().GetNumberOfPoints()-1)
    return None

  def getMuscleLength(self):
    markupsNode = self.getPapillaryLineMarkupNode()
    if markupsNode and markupsNode.GetNumberOfMarkups() >= 2:
      muscleTipPointIndex = markupsNode.GetCurvePointIndexFromControlPointIndex(1)
      return markupsNode.GetCurveLengthBetweenStartEndPointsWorld(0, muscleTipPointIndex)
    return None

  def getTipChordMuscleAngleDeg(self, annulusPlaneNormal):
    """Returns angle of muscle tip-chord insertion point line and the annulus plane"""
    muscleTipPoint = self.getNthMusclePointPosition(1)
    chordInsertionPoint = self.getNthMusclePointPosition(2)
    if muscleTipPoint is None or chordInsertionPoint is None:
      return None
    muscleDirectionVector = chordInsertionPoint - muscleTipPoint
    return self._getMuscleAngleDeg(annulusPlaneNormal, muscleDirectionVector)

  def getBaseChordMuscleAngleDeg(self, annulusPlaneNormal):
    """Returns angle of muscle base-chord insertion point line and the annulus plane"""
    muscleBasePoint = self.getNthMusclePointPosition(0)
    chordInsertionPoint = self.getNthMusclePointPosition(2)
    if muscleBasePoint is None or chordInsertionPoint is None:
      return None
    muscleDirectionVector = chordInsertionPoint - muscleBasePoint
    return self._getMuscleAngleDeg(annulusPlaneNormal, muscleDirectionVector)

  def _getMuscleAngleDeg(self, annulusPlaneNormal, muscleDirectionVector):
    muscleDirectionVector = muscleDirectionVector / np.linalg.norm(muscleDirectionVector)
    return math.acos(np.dot(annulusPlaneNormal, muscleDirectionVector)) * 180.0 / math.pi - 90.0

  def getNthMusclePointPosition(self, idx):
    if not self.hasMusclePointsPlaced():
      return None
    point = np.array([0., 0., 0.])
    musclePoints = self.getPapillaryLineMarkupNode()
    try:
      # Current API (Slicer-4.13 February 2022)
      musclePoints.GetNthControlPointPosition(idx, point)
    except:
      # Legacy API
      musclePoints.GetNthFiducialPosition(idx, point)
    return point

  def hasMusclePointsPlaced(self):
    markupsNode = self.getPapillaryLineMarkupNode()
    return markupsNode and not markupsNode.GetNumberOfMarkups() < 3