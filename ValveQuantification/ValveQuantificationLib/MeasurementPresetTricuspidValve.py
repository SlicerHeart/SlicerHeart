import HeartValveLib

from ValveQuantificationLib.MeasurementPreset import *


class MeasurementPresetTricuspidValve(MeasurementPreset):

  def __init__(self):
    super(MeasurementPresetTricuspidValve, self).__init__()
    self.id = "TricuspidValve"
    self.name = "Tricuspid valve"
    self.inputValveIds = ["TricuspidValve"]
    self.inputValveNames = {"TricuspidValve": "Tricuspid valve"}
    self.inputFields = [
      createPointInputField("APoint", "A", "TricuspidValve", True),
      createPointInputField("PPoint", "P", "TricuspidValve", True),
      createPointInputField("SPoint", "S", "TricuspidValve", True),
      createPointInputField("LPoint", "L", "TricuspidValve", True),
      createPointInputField("AscPoint", "ASC", "TricuspidValve", False),
      createPointInputField("PscPoint", "PSC", "TricuspidValve", False),
      createPointInputField("ApcPoint", "APC", "TricuspidValve", False)
    ]
    self.definitionsUrl = self.getResourceFileUrl("TricuspidValve.html")

  def addCoaptationCenterPoint(self, valveModel, coaptationModels, pointName):
    """Compute center point of coaptation surface baseline endpoints.
    This is essentially the point where all leaflet surfaces meet at the base of
    coaptation surfaces.
    Coaptation models are specified because in complex valves not all leaflets
    meet at the same point.
    """

    import numpy as np

    valveModel.removeAnnulusMarkupLabel(pointName)

    coaptationCenterPoints = None
    if len(coaptationModels) == 1: # tricuspid has only two leaflets
      coaptationModel = coaptationModels[0]
      basePoints = coaptationModel.baseLine.curvePoly.GetPoints()
      numberOfBasePoints = basePoints.GetNumberOfPoints()
      if numberOfBasePoints:
        coaptationCenterPoints = np.array(basePoints.GetPoint(numberOfBasePoints//2 - 1))
    elif len(coaptationModels) == 3: # not always the case (for example if tricuspid has only two leaflets)
      for coaptationModel in coaptationModels:
        basePoints = coaptationModel.baseLine.curvePoly.GetPoints()
        numberOfBasePoints = basePoints.GetNumberOfPoints()
        if not numberOfBasePoints:
          continue

        # Find which end of the coaptation base line is farther from the annulus contour
        # (that will be the center point)
        firstCoaptationLinePoint = np.array(basePoints.GetPoint(0))
        [closestAnnulusPointToFirstPoint, dummy] = valveModel.annulusContourCurve.getClosestPoint(firstCoaptationLinePoint)
        firstPointDistanceFromAnnulusCurve = np.linalg.norm(closestAnnulusPointToFirstPoint-firstCoaptationLinePoint)
        lastCoaptationLinePoint = np.array(basePoints.GetPoint(numberOfBasePoints - 1))
        [closestAnnulusPointToLastPoint, dummy] = valveModel.annulusContourCurve.getClosestPoint(lastCoaptationLinePoint)
        lastPointDistanceFromAnnulusCurve = np.linalg.norm(closestAnnulusPointToLastPoint-lastCoaptationLinePoint)

        if firstPointDistanceFromAnnulusCurve > lastPointDistanceFromAnnulusCurve:
          coaptationCenterPoint = firstCoaptationLinePoint
        else:
          coaptationCenterPoint = lastCoaptationLinePoint

        # Add to point list
        if coaptationCenterPoints is None:
          coaptationCenterPoints = coaptationCenterPoint
        else:
          coaptationCenterPoints = np.column_stack((coaptationCenterPoints, coaptationCenterPoint))

    # Add markup and mean position
    if coaptationCenterPoints is not None:
      meanCoaptationCenterPoint = coaptationCenterPoints.mean(axis=1) if coaptationCenterPoints.ndim > 1 else coaptationCenterPoints
      valveModel.setAnnulusMarkupLabel(pointName, meanCoaptationCenterPoint)

  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetTricuspidValve, self).computeMetrics(inputValveModels, outputTableNode)

    if not "TricuspidValve" in inputValveModels.keys():
      return ["Selection of tricuspid valve is required"]

    valveModel = inputValveModels["TricuspidValve"]

    # Annulus circumference
    self.addMeasurement(self.getAnnulusCircumference(valveModel))

    # Annulus point distances
    self.addMeasurement(self.getDistanceBetweenPoints(valveModel, 'A', valveModel, 'P'))
    self.addMeasurement(self.getDistanceBetweenPoints(valveModel, 'L', valveModel, 'S'))
    self.addMeasurement(self.getDistanceBetweenPoints(valveModel, 'APC', valveModel, 'PSC'))
    self.addMeasurement(self.getDistanceBetweenPoints(valveModel, 'PSC', valveModel, 'ASC'))
    self.addMeasurement(self.getDistanceBetweenPoints(valveModel, 'ASC', valveModel, 'APC'))

    # make sure the valve type is set correctly (annulus contour plane direction is computed from that)
    valveModel.setValveType("tricuspid")

    [planePosition, planeNormal] = valveModel.getAnnulusContourPlane()

    # Annulus height measurements
    self.addAnnulusHeightMeasurements(valveModel, planePosition, planeNormal)

    self.addMeasurement(self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'APC', valveModel, 'PSC', oriented=True, positiveDirection_valveModel1=planeNormal))
    self.addMeasurement(self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'PSC', valveModel, 'ASC', oriented=True, positiveDirection_valveModel1=planeNormal))
    self.addMeasurement(self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'ASC', valveModel, 'APC', oriented=True, positiveDirection_valveModel1=planeNormal))

    # Annulus area measurements
    self.addAnnulusAreaMeasurements(valveModel, planePosition, planeNormal,
                                    quadrantPointLabels=['A', 'P', 'S', 'L'])

    # Coaptation measurements
    self.addCoaptationMeasurements(valveModel)
    # ACC point is computed from all coaptation surfaces
    self.addCoaptationCenterPoint(valveModel, valveModel.coaptationModels, "ACC")

    # Leaflets
    self.addSegmentedLeafletMeasurements(valveModel, planePosition, planeNormal)

    return self.metricsMessages

  def onInputFieldChanged(self, fieldId, inputValveModels, inputFieldValues, computeDependentValues=False):
    valveModel = inputValveModels["TricuspidValve"] if "TricuspidValve" in inputValveModels.keys() else None
    if not valveModel:
      return

    if fieldId == 'APoint' and valveModel.getAnnulusMarkupPositionByLabel('P') is None and computeDependentValues:
      self.onResetInputField('PPoint', inputValveModels, inputFieldValues)
    if fieldId == 'PPoint' and valveModel.getAnnulusMarkupPositionByLabel('A') is None and computeDependentValues:
      self.onResetInputField('APoint', inputValveModels, inputFieldValues)

    if fieldId == 'SPoint' and valveModel.getAnnulusMarkupPositionByLabel('L') is None and computeDependentValues:
      self.onResetInputField('LPoint', inputValveModels, inputFieldValues)
    if fieldId == 'LPoint' and valveModel.getAnnulusMarkupPositionByLabel('S') is None and computeDependentValues:
      self.onResetInputField('SPoint', inputValveModels, inputFieldValues)

  def onResetInputField(self, fieldId, inputValveModels, inputFieldValues):
    valveModel = inputValveModels["TricuspidValve"] if "TricuspidValve" in inputValveModels.keys() else None
    if not valveModel:
      return

    if fieldId == 'APoint':  # A point (farthest from P)
      pointP = valveModel.getAnnulusMarkupPositionByLabel('P')
      if pointP is not None:
        [pointAPosition, pointAId] = valveModel.annulusContourCurve.getFarthestPoint(pointP)
        valveModel.setAnnulusMarkupLabel('A', pointAPosition)
    elif fieldId == 'PPoint':  # P point (farthest from A)
      pointA = valveModel.getAnnulusMarkupPositionByLabel('A')
      if pointA is not None:
        [pointPPosition, pointPId] = valveModel.annulusContourCurve.getFarthestPoint(pointA)
        valveModel.setAnnulusMarkupLabel('P', pointPPosition)
    elif fieldId == 'SPoint':  # PM point (on the other side of the P-A line from AL, P-A orthogonal to AL-PM)
      pointP = valveModel.getAnnulusMarkupPositionByLabel('P')
      pointA = valveModel.getAnnulusMarkupPositionByLabel('A')
      pointL = valveModel.getAnnulusMarkupPositionByLabel('L')
      if pointL is not None and pointP is not None and pointA is not None:
        defaultLSPlaneNormal = pointP - pointA
        defaultLSPlanePosition = pointL
        slVector = pointL - HeartValveLib.getPointProjectionToLine(pointL, pointP, pointA)
        [pointS, _] = self.getCurveIntersectionApPointsWithPlane(valveModel, defaultLSPlanePosition,
                                                                             defaultLSPlaneNormal, slVector)
        valveModel.setAnnulusMarkupLabel('S', pointS)
    elif fieldId == 'LPoint':  # AL point (on the other side of the P-A line from S, P-A orthogonal to S-AL)
      pointP = valveModel.getAnnulusMarkupPositionByLabel('P')
      pointA = valveModel.getAnnulusMarkupPositionByLabel('A')
      pointS = valveModel.getAnnulusMarkupPositionByLabel('S')
      if pointS is not None and pointP is not None and pointA is not None:
        defaultLSPlaneNormal = pointP - pointA
        defaultLSPlanePosition = pointS
        alSVector = pointS - HeartValveLib.getPointProjectionToLine(pointS, pointP, pointA)
        [pointL, _] = self.getCurveIntersectionApPointsWithPlane(valveModel, defaultLSPlanePosition,
                                                                             defaultLSPlaneNormal, alSVector)
        valveModel.setAnnulusMarkupLabel('L', pointL)
