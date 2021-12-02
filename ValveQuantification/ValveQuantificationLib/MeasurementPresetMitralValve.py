import numpy as np
import HeartValveLib

from ValveQuantificationLib.MeasurementPreset import *


class MeasurementPresetMitralValve(MeasurementPreset):

  def __init__(self):
    super(MeasurementPresetMitralValve, self).__init__()
    self.id = "MitralValve"
    self.name = "Mitral valve"
    self.inputValveIds = ["MitralValve", "AorticValve"]
    self.inputValveNames = { "MitralValve": "Mitral valve", "AorticValve": "Aortic valve" }
    self.inputFields = [
      createPointInputField("APoint", "A", self.id, True),
      createPointInputField("PPoint", "P", self.id, True),
      createPointInputField("PmPoint", "PM", self.id, True),
      createPointInputField("AlPoint", "AL", self.id, True),
      createPointInputField("PmcPoint", "PMC", self.id, False),
      createPointInputField("AlcPoint", "ALC", self.id, False)
    ]
    self.definitionsUrl = self.getResourceFileUrl("MitralValve.html")

  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetMitralValve, self).computeMetrics(inputValveModels, outputTableNode)

    if not "MitralValve" in inputValveModels.keys():
      return ["Selection of mitral valve is required"]

    mitralValveModel = inputValveModels["MitralValve"]

    # Annulus circumference
    self.addMeasurement(self.getAnnulusCircumference(mitralValveModel))

    # Annulus point distances
    self.addMeasurement(self.getDistanceBetweenPoints(mitralValveModel, 'A', mitralValveModel, 'P'))
    self.addMeasurement(self.getDistanceBetweenPoints(mitralValveModel, 'AL', mitralValveModel, 'PM'))
    self.addMeasurement(self.getDistanceBetweenPoints(mitralValveModel, 'ALC', mitralValveModel, 'PMC'))

    # Annulus sphericity index
    self.addMeasurement(self.getSphericityIndex(mitralValveModel, 'A', 'P', 'AL', 'PM'))

    # TODO: getAnnulusContourPlane() uses all the contour points. It may be more robust to use only the posterior points as Alison did
    # Plane normal will be approximately point to anterior direction

    # make sure the valve type is set correctly (annulus contour plane direction is computed from that)
    mitralValveModel.setValveType("mitral")

    [planePosition, planeNormal] = mitralValveModel.getAnnulusContourPlane()

    # Annulus height measurements
    self.addAnnulusHeightMeasurements(mitralValveModel, planePosition, planeNormal)

    # Annulus area measurements
    self.addAnnulusAreaMeasurements(mitralValveModel, planePosition, planeNormal,
                                    quadrantPointLabels = ['A', 'P', 'AL', 'PM'])

    # Leaflets
    self.addSegmentedLeafletMeasurements(mitralValveModel, planePosition, planeNormal)

    aorticValveModel = None
    if "AorticValve" in inputValveModels.keys():
      aorticValveModel = inputValveModels["AorticValve"]
      # make sure the valve type is set correctly (annulus contour plane direction is computed from that)
      aorticValveModel.setValveType("aortic")
      [aorticPlanePosition, aorticPlaneNormal] = aorticValveModel.getAnnulusContourPlane()

    if aorticValveModel:
      pointMC = planePosition
      pointAC_AorticValve = aorticPlanePosition # AC point is centroid of aortic valve
      pointAC_Mitral = self.transformPointFromValve2ToValve1(mitralValveModel, aorticValveModel, pointAC_AorticValve)
      mitralValveModel.setAnnulusMarkupLabel('MC', pointMC)
      mitralValveModel.setAnnulusMarkupLabel('AC', pointAC_Mitral)
      self.addMeasurement(self.getAngleBetweenPlanes(mitralValveModel, planePosition, planeNormal,
                                                    aorticValveModel, aorticPlanePosition, aorticPlaneNormal,
                                                    'Mitral-Aortic valve plane angle',
                                                    invertDirection=False))
      self.addMeasurement(self.getDistanceBetweenPoints(mitralValveModel, 'MC', aorticValveModel, 'AC',
        point1_valveModel1=pointMC, point2_valveModel2=pointAC_AorticValve))

      # Annulus circumference
      self.addMeasurement(self.getAnnulusCircumference(aorticValveModel, name="Aortic Annulus"))

      # Annulus area measurements
      self.addAnnulusAreaMeasurements(aorticValveModel, aorticPlanePosition, aorticPlaneNormal, name="Aortic Annulus")

    else:
      self.metricsMessages.append("Aortic valve has to be defined to compute Mitral-Aortic valve plane angle and AC-MC distance")
      mitralValveModel.removeAnnulusMarkupLabel('MC')
      mitralValveModel.removeAnnulusMarkupLabel('AC')

    # Label aortic valve automatically (based on closest point to mitral centroid and orthogonal directions)
    if aorticValveModel:
      mitralCentroid_AorticValve = self.transformPointFromValve2ToValve1(aorticValveModel, mitralValveModel, planePosition)
      paDirection_AorticValve = aorticPlanePosition - mitralCentroid_AorticValve
      paDirection_AorticValve = paDirection_AorticValve/np.linalg.norm(paDirection_AorticValve)
      lrDirection_AorticValve = np.cross(paDirection_AorticValve, aorticPlaneNormal)
      # Determine R-L intersection points
      cutPlaneNormal = paDirection_AorticValve / np.linalg.norm(paDirection_AorticValve)
      cutPlanePosition = aorticPlanePosition
      [pointL_AorticValve, pointR_AorticValve] = self.getCurveIntersectionApPointsWithPlane(aorticValveModel, cutPlanePosition, cutPlaneNormal, lrDirection_AorticValve)
      # Determine A-P intersection points
      cutPlaneNormal = pointR_AorticValve - aorticPlanePosition
      cutPlaneNormal = cutPlaneNormal / np.linalg.norm(cutPlaneNormal)
      [pointP_AorticValve, pointA_AorticValve] = self.getCurveIntersectionApPointsWithPlane(aorticValveModel, cutPlanePosition, cutPlaneNormal, paDirection_AorticValve)
      # Add landmarks
      aorticValveModel.setAnnulusMarkupLabel('L', pointL_AorticValve)
      aorticValveModel.setAnnulusMarkupLabel('R', pointR_AorticValve)
      aorticValveModel.setAnnulusMarkupLabel('P', pointP_AorticValve)
      aorticValveModel.setAnnulusMarkupLabel('A', pointA_AorticValve)

    # Coaptation measurements
    self.addCoaptationMeasurements(mitralValveModel)

    return self.metricsMessages

  def onInputFieldChanged(self, fieldId, inputValveModels, inputFieldValues, computeDependentValues = False):
    mitralValveModel = inputValveModels["MitralValve"] if "MitralValve" in inputValveModels.keys() else None
    if not mitralValveModel:
      return

    if fieldId == 'APoint' and mitralValveModel.getAnnulusMarkupPositionByLabel('P') is None and computeDependentValues:
      self.onResetInputField('PPoint', inputValveModels, inputFieldValues)
    if fieldId == 'PPoint' and mitralValveModel.getAnnulusMarkupPositionByLabel('A') is None and computeDependentValues:
      self.onResetInputField('APoint', inputValveModels, inputFieldValues)

    if fieldId=='PmPoint' and mitralValveModel.getAnnulusMarkupPositionByLabel('AL') is None and computeDependentValues:
      self.onResetInputField('AlPoint', inputValveModels, inputFieldValues)
    if fieldId=='AlPoint' and mitralValveModel.getAnnulusMarkupPositionByLabel('PM') is None and computeDependentValues:
      self.onResetInputField('PmPoint', inputValveModels, inputFieldValues)

    if fieldId=='PmcPoint' and mitralValveModel.getAnnulusMarkupPositionByLabel('ALC') is None and computeDependentValues:
      self.onResetInputField('AlcPoint', inputValveModels, inputFieldValues)
    if fieldId=='AlcPoint' and mitralValveModel.getAnnulusMarkupPositionByLabel('PMC') is None and computeDependentValues:
      self.onResetInputField('PmcPoint', inputValveModels, inputFieldValues)

  def onResetInputField(self, fieldId, inputValveModels, inputFieldValues):
    mitralValveModel = inputValveModels["MitralValve"] if "MitralValve" in inputValveModels.keys() else None
    if not mitralValveModel:
      return

    if fieldId == 'APoint':  # A point (farthest from P)
      pointP = mitralValveModel.getAnnulusMarkupPositionByLabel('P')
      if pointP is not None:
        [pointAPosition, pointAId] = mitralValveModel.annulusContourCurve.getFarthestPoint(pointP)
        mitralValveModel.setAnnulusMarkupLabel('A', pointAPosition)
    elif fieldId == 'PPoint':  # P point (farthest from A)
      pointA = mitralValveModel.getAnnulusMarkupPositionByLabel('A')
      if pointA is not None:
        [pointPPosition, pointPId] = mitralValveModel.annulusContourCurve.getFarthestPoint(pointA)
        mitralValveModel.setAnnulusMarkupLabel('P', pointPPosition)
    elif fieldId == 'PmPoint':  # PM point (on the other side of the P-A line from AL, P-A orthogonal to AL-PM)
      pointP = mitralValveModel.getAnnulusMarkupPositionByLabel('P')
      pointA = mitralValveModel.getAnnulusMarkupPositionByLabel('A')
      pointAl = mitralValveModel.getAnnulusMarkupPositionByLabel('AL')
      if pointAl is not None and pointP is not None and pointA is not None:
        defaultAlPmPlaneNormal = pointP - pointA
        defaultAlPmPlanePosition = pointAl
        pmAlVector = pointAl - HeartValveLib.getPointProjectionToLine(pointAl, pointP, pointA)
        [pointPm, pointAlDummy] = self.getCurveIntersectionApPointsWithPlane(mitralValveModel, defaultAlPmPlanePosition, defaultAlPmPlaneNormal, pmAlVector)
        mitralValveModel.setAnnulusMarkupLabel('PM', pointPm)
    elif fieldId == 'AlPoint':  # AL point (on the other side of the P-A line from PM, P-A orthogonal to PM-AL)
      pointP = mitralValveModel.getAnnulusMarkupPositionByLabel('P')
      pointA = mitralValveModel.getAnnulusMarkupPositionByLabel('A')
      pointPm = mitralValveModel.getAnnulusMarkupPositionByLabel('PM')
      if pointPm is not None and pointP is not None and pointA is not None:
        defaultAlPmPlaneNormal = pointP - pointA
        defaultAlPmPlanePosition = pointPm
        alPmVector = pointPm - HeartValveLib.getPointProjectionToLine(pointPm, pointP, pointA)
        [pointAl, pointPmDummy] = self.getCurveIntersectionApPointsWithPlane(mitralValveModel, defaultAlPmPlanePosition, defaultAlPmPlaneNormal, alPmVector)
        mitralValveModel.setAnnulusMarkupLabel('AL', pointAl)
    elif fieldId == 'PmcPoint':  # PMC point (on the other side of the P-A line from ALC, P-A orthogonal to ALC-PMC)
      pointP = mitralValveModel.getAnnulusMarkupPositionByLabel('P')
      pointA = mitralValveModel.getAnnulusMarkupPositionByLabel('A')
      pointAlc = mitralValveModel.getAnnulusMarkupPositionByLabel('ALC')
      if pointAlc is not None and pointP is not None and pointA is not None:
        defaultAlcPmcPlaneNormal = pointP - pointA
        defaultAlcPmcPlanePosition = pointAlc
        pmcAlcVector = pointAlc - HeartValveLib.getPointProjectionToLine(pointAlc, pointP, pointA)
        [pointPmc, pointAlcDummy] = self.getCurveIntersectionApPointsWithPlane(mitralValveModel, defaultAlcPmcPlanePosition, defaultAlcPmcPlaneNormal, pmcAlcVector)
        mitralValveModel.setAnnulusMarkupLabel('PMC', pointPmc)
    elif fieldId == 'AlcPoint':  # ALC point (on the other side of the P-A line from PMC, P-A orthogonal to PMC-ALC)
      pointP = mitralValveModel.getAnnulusMarkupPositionByLabel('P')
      pointA = mitralValveModel.getAnnulusMarkupPositionByLabel('A')
      pointPmc = mitralValveModel.getAnnulusMarkupPositionByLabel('PMC')
      if pointPmc is not None and pointP is not None and pointA is not None:
        defaultAlcPmcPlaneNormal = pointP - pointA
        defaultAlcPmcPlanePosition = pointPmc
        alcPmcVector = pointPmc - HeartValveLib.getPointProjectionToLine(pointPmc, pointP, pointA)
        [pointAlc, pointPmcDummy] = self.getCurveIntersectionApPointsWithPlane(mitralValveModel, defaultAlcPmcPlanePosition, defaultAlcPmcPlaneNormal, alcPmcVector)
        mitralValveModel.setAnnulusMarkupLabel('ALC', pointAlc)
