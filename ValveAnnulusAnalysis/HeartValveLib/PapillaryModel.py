import HeartValveLib
import math
import numpy as np
import SmoothCurve


class PapillaryModel:

  def __init__(self):
    self.markupGlyphScale = 1.0
    self.papillaryLine = SmoothCurve.SmoothCurve()
    self.papillaryLine.setTubeRadius(self.markupGlyphScale/2.0)
    self.papillaryLine.setInterpolationMethod(HeartValveLib.SmoothCurve.InterpolationSpline)

  def getName(self):
    return self.getPapillaryLineModelNode().GetName()

  def updateModel(self):
    self.papillaryLine.updateCurve()
    
  def setPapillaryLineMarkupNode(self, papillaryLineMarkupNode):
    self.papillaryLine.setControlPointsMarkupNode(papillaryLineMarkupNode)

  def getPapillaryLineMarkupNode(self):
    return self.papillaryLine.controlPointsMarkupNode

  def setPapillaryLineModelNode(self, papillaryLineModelNode):
    self.papillaryLine.setCurveModelNode(papillaryLineModelNode)

  def getPapillaryLineModelNode(self):
    return self.papillaryLine.curveModelNode

  def getMuscleChordLength(self):
    musclePoints = self.getPapillaryLineMarkupNode()
    if musclePoints and musclePoints.GetNumberOfMarkups() >= 3:
      muscleTipPointIndex = self.papillaryLine.getCurvePointIndexFromControlPointIndex(1)
      return self.papillaryLine.getCurveLengthBetweenStartEndPoints(muscleTipPointIndex,
                                                                    self.papillaryLine.curvePoints.GetNumberOfPoints()-1)
    return None

  def getMuscleLength(self):
    musclePoints = self.getPapillaryLineMarkupNode()
    if musclePoints and musclePoints.GetNumberOfMarkups() >= 2:
      muscleTipPointIndex = self.papillaryLine.getCurvePointIndexFromControlPointIndex(1)
      return self.papillaryLine.getCurveLengthBetweenStartEndPoints(0, muscleTipPointIndex)
    return None

  def getTipChordMuscleAngleDeg(self, annulusPlaneNormal):
    """Returns angle of muscle tip-chord insertion point line and the annulus plane"""
    muscleTipPoint = self.getNthMusclePoint(1)
    chordInsertionPoint = self.getNthMusclePoint(2)
    if muscleTipPoint is None or chordInsertionPoint is None:
      return None
    muscleDirectionVector = chordInsertionPoint - muscleTipPoint
    return self._getMuscleAngleDeg(annulusPlaneNormal, muscleDirectionVector)

  def getBaseChordMuscleAngleDeg(self, annulusPlaneNormal):
    """Returns angle of muscle base-chord insertion point line and the annulus plane"""
    muscleBasePoint = self.getNthMusclePoint(0)
    chordInsertionPoint = self.getNthMusclePoint(2)
    if muscleBasePoint is None or chordInsertionPoint is None:
      return None
    muscleDirectionVector = chordInsertionPoint - muscleBasePoint
    return self._getMuscleAngleDeg(annulusPlaneNormal, muscleDirectionVector)

  def _getMuscleAngleDeg(self, annulusPlaneNormal, muscleDirectionVector):
    muscleDirectionVector = muscleDirectionVector / np.linalg.norm(muscleDirectionVector)
    return math.acos(np.dot(annulusPlaneNormal, muscleDirectionVector)) * 180.0 / math.pi - 90.0

  def getNthMusclePoint(self, idx):
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
    musclePoints = self.getPapillaryLineMarkupNode()
    return musclePoints and not musclePoints.GetNumberOfMarkups() < 3