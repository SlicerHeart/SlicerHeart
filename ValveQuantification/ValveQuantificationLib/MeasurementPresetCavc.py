import numpy as np
import HeartValveLib
import vtk
import slicer
from ValveQuantificationLib.MeasurementPreset import *


class MeasurementPresetCavc(MeasurementPreset):

  def addCoaptationCenterPoint(self, valveModel, coaptationModels, pointName):
    """Compute center point of coaptation surface baseline endpoints.
    This is essentially the point where all leaflet surfaces meet at the base of
    coaptation surfaces.
    Coaptation models are specified because in complex valves not all leaflets
    meet at the same point.
    """
    valveModel.removeAnnulusMarkupLabel(pointName)

    coaptationCenterPoints = None

    for coaptationModel in coaptationModels:
      basePoints = coaptationModel.baseLine.curvePoly.GetPoints()
      numberOfBasePoints = basePoints.GetNumberOfPoints()
      if not numberOfBasePoints:
        continue

      # Find which end of the coaptation base line is farther from the annulus contour
      # (that will be the center point)
      firstCoaptationLinePoint = np.array(basePoints.GetPoint(0))
      [closestAnnulusPointToFirstPoint, dummy] = valveModel.annulusContourCurve.getClosestPoint(
        firstCoaptationLinePoint)
      firstPointDistanceFromAnnulusCurve = np.linalg.norm(closestAnnulusPointToFirstPoint - firstCoaptationLinePoint)
      lastCoaptationLinePoint = np.array(basePoints.GetPoint(numberOfBasePoints - 1))
      [closestAnnulusPointToLastPoint, dummy] = valveModel.annulusContourCurve.getClosestPoint(lastCoaptationLinePoint)
      lastPointDistanceFromAnnulusCurve = np.linalg.norm(closestAnnulusPointToLastPoint - lastCoaptationLinePoint)

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
      meanCoaptationCenterPoint = coaptationCenterPoints.mean(axis=1)
      valveModel.setAnnulusMarkupLabel(pointName, meanCoaptationCenterPoint)

  @staticmethod
  def getAnnulusContourSplitSidesStartIndices(valveModel, pointMA, pointMP, pointL):
    [_, closestPointIdMA] = valveModel.annulusContourCurve.getClosestPoint(pointMA)
    [_, closestPointIdMP] = valveModel.annulusContourCurve.getClosestPoint(pointMP)
    [_, closestPointIdL] = valveModel.annulusContourCurve.getClosestPoint(pointL)
    interpolatedPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    # Determine which side is left/right
    numberOfInterpolatedPoints = interpolatedPoints.shape[1]
    closestPointIdMP_WrappedAround = \
      closestPointIdMP if closestPointIdMA < closestPointIdMP else (closestPointIdMP + numberOfInterpolatedPoints)
    closestPointIdL_WrappedAround = \
      closestPointIdL if closestPointIdL < closestPointIdMP else (closestPointIdL + numberOfInterpolatedPoints)
    if closestPointIdMA < closestPointIdL_WrappedAround < closestPointIdMP_WrappedAround:
      startEndPointIndexL = [closestPointIdMA, closestPointIdMP]
      startEndPointIndexR = [closestPointIdMP, closestPointIdMA]
    else:
      startEndPointIndexL = [closestPointIdMP, closestPointIdMA]
      startEndPointIndexR = [closestPointIdMA, closestPointIdMP]
    return {'L': startEndPointIndexL, 'R': startEndPointIndexR}

  @staticmethod
  def getAnnulusCurvePoints(valveModel, startEndPointIndex):
    interpolatedPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    if startEndPointIndex[0] < startEndPointIndex[1]:
      # Segment between MA and MP point without wrapping around
      curvePoints = interpolatedPoints[:, startEndPointIndex[0]:startEndPointIndex[1] + 1]
    else:
      # Segment between MA and MP point with wrapping around point 0
      curvePoints = np.hstack((interpolatedPoints[:, startEndPointIndex[0]:],
                               interpolatedPoints[:, :startEndPointIndex[1]]))
    # copy the first element to the end to close the curve
    curvePoints = np.c_[curvePoints, curvePoints[:, 0]]
    # resample so that the long connection between the start and end point is has
    # sufficient number of points (to make it count during plane fitting)
    annulusPoints = valveModel.annulusContourCurve.getSampledInterpolatedPointsAsArray(
      curvePoints, samplingDistance=0.1, closedCurve=True)
    return annulusPoints

  @staticmethod
  def getPartialContourPlane(annulusPoints, valveModel):
    partialPlanePosition, partialPlaneNormal = HeartValveLib.planeFit(annulusPoints)
    _, planeNormal = valveModel.getAnnulusContourPlane()
    if np.dot(partialPlaneNormal, planeNormal) < 0:
      # Make the partial plane normal points in the same direction as the complete annulus plane normal
      partialPlaneNormal = -partialPlaneNormal
    return partialPlanePosition, partialPlaneNormal

  def __init__(self):
    super(MeasurementPresetCavc, self).__init__()
    self.id = "Cavc"
    self.name = "CAVC"
    self.inputValveIds = ["Cavc", "AorticValve"]
    self.inputValveNames = dict()
    self.inputValveNames["Cavc"] = "CAVC"
    self.inputValveNames["AorticValve"] = "Aortic valve"
    self.inputFields = [
      createPointInputField("RPoint", "R", self.id, True),
      createPointInputField("LPoint", "L", self.id, True),
      createPointInputField("SRCPoint", "SRC", self.id, True),
      createPointInputField("SLCPoint", "SLC", self.id, True),
      createPointInputField("IRCPoint", "IRC", self.id, True),
      createPointInputField("ILCPoint", "ILC", self.id, True),
      createPointInputField("MaPoint", "MA", self.id, False),
      createPointInputField("MpPoint", "MP", self.id, False),
      createScalarInputField("RaRpPosition", "RA-RP line position", 50.0, "%", 10.0, 90.0, 1.0),
      createScalarInputField("LaLpPosition", "LA-LP line position", 50.0, "%", 10.0, 90.0, 1.0)
    ]
    self.definitionsUrl = self.getResourceFileUrl("Cavc.html")

  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetCavc, self).computeMetrics(inputValveModels, outputTableNode)

    if not "Cavc" in inputValveModels.keys():
      return ["Selection of CAVC is required"]

    valveModel = inputValveModels["Cavc"]

    self.addMeasurement(self.getAnnulusCircumference(valveModel))
    self.addAnnulusPointDistanceMeasurements(valveModel)

    # make sure the valve type is set correctly (annulus contour plane direction is computed from that)
    valveModel.setValveType("cavc")
    [planePosition, planeNormal] = valveModel.getAnnulusContourPlane()
    planeNode = self.createSplittingPlane(valveModel)

    self.addAnnulusHeightMeasurements(valveModel, planePosition, planeNormal)
    self.addAnnulusCurveLengthMeasurements(valveModel)
    self.addAnnulusAreaMeasurements(valveModel, planePosition, planeNormal, quadrantPointLabels=['R', 'L', 'MP', 'MA'])
    self.addSegmentedLeafletMeasurements(valveModel, planePosition, planeNormal)
    self.addSideSeparatedLeafletSurfaceMeasurements(valveModel, planeNode, leafletNames=["superior", "inferior"])

    self.addCoaptationMeasurements(valveModel)

    # left side
    leftCoaptationModels = [["left", "superior"], ["left", "inferior"]]
    self.addCoaptationCenterPoint(valveModel, self.getMatchingCoaptations(valveModel, leftCoaptationModels), "LCC")
    self.addLeftCoaptationMeasurements(valveModel, planeNode)

    slicer.mrmlScene.RemoveNode(planeNode)

    # right side
    rightCoaptationModels = [["right", "superior"], ["right", "inferior"]]
    self.addCoaptationCenterPoint(valveModel, self.getMatchingCoaptations(valveModel, rightCoaptationModels), "RCC")

    try:
      aorticValveModel = inputValveModels["AorticValve"]
      # NB: ensure valve type set correctly -> annulus contour plane direction is computed from that
      aorticValveModel.setValveType("aortic")
    except KeyError:
      aorticValveModel = None

    if aorticValveModel and self.areRequiredLandmarksAvailable(valveModel, names=["R", "L", "LA", "LP"]):
      self.addAngleForAC_LC_R(aorticValveModel, valveModel)
    else:
      self.metricsMessages.append(
        "R, L, LA, LP points and aortic valve have to be defined to compute AC-LC-R angle and AC-LC distance")
      valveModel.removeAnnulusMarkupLabel('LC')
      valveModel.removeAnnulusMarkupLabel('AC')

    if aorticValveModel:
      self.addAorticAnnulusLandmarks(aorticValveModel, valveModel)

    if self.areRequiredLandmarksAvailable(valveModel, names=["MA", "MP", "R", "L"]):
      self.computeAnnulusHeightForEachSide(valveModel)
    return self.metricsMessages

  def addSideSeparatedLeafletSurfaceMeasurements(self, valveModel, planeNode, leafletNames):
    # NB: considering that surfaces were already calculated
    for leafletModel in valveModel.leafletModels:
      segmentName = leafletModel.getName()
      if not any(subString in segmentName for subString in leafletNames):
        continue
      leafletSurfaceModelNode = valveModel.getLeafletNodeReference("LeafletSurfaceModel", leafletModel.segmentId)
      rightSideModel, leftSideModel = cutModel(leafletSurfaceModelNode, planeNode, False)

      self.moveNodeToMeasurementFolder(leftSideModel, None)
      self.moveNodeToMeasurementFolder(rightSideModel, None)

      leftSideModel.SetName(f"Leaflet area - left {segmentName} (3D)")
      rightSideModel.SetName(f"Leaflet area - right {segmentName} (3D)")

      # Compute and add measurement
      for modelNode in [leftSideModel, rightSideModel]:
        massProperties = vtk.vtkMassProperties()
        massProperties.SetInputData(modelNode.GetPolyData())
        leafletSurfaceArea3d = massProperties.GetSurfaceArea()
        self.addMeasurement({
          KEY_NAME: modelNode.GetName(),
          KEY_VALUE: "{:.1f}".format(leafletSurfaceArea3d),
          KEY_UNIT: 'mm*mm'
        })

  def addLeftCoaptationMeasurements(self, valveModel, planeNode):
    if not len(valveModel.coaptationModels):
      return

    leftCoaptationModels = [["left", "superior"], ["left", "inferior"]]
    coaptationModels = self.getMatchingCoaptations(valveModel, leftCoaptationModels)

    centerCoaptationModel = self.getMatchingCoaptations(valveModel, [["superior", "inferior"]])[0]
    centerCoaptationModel.updateSurface()

    newBaseLine = getLeftCoaptationPointsIncludingIntersection(centerCoaptationModel.baseLine, planeNode)
    newMarginLine = getLeftCoaptationPointsIncludingIntersection(centerCoaptationModel.marginLine, planeNode)

    leftCenterCoaptationModel = valveModel.addCoaptationModel()

    setControlPointsWorldFromArray(leftCenterCoaptationModel.baseLine, newBaseLine)
    setControlPointsWorldFromArray(leftCenterCoaptationModel.marginLine, newMarginLine)

    leftCenterCoaptationModel.updateSurface()

    coaptationModels.append(leftCenterCoaptationModel)

    totalBaselineLengths = []
    totalMarginLineLengths = []
    distances = []

    appendSurface = vtk.vtkAppendPolyData()
    appendBaseLines = vtk.vtkAppendPolyData()
    appendMarginLines = vtk.vtkAppendPolyData()

    for coaptationModel in coaptationModels:
      coaptationModel.updateSurface()

      totalBaselineLengths.append(coaptationModel.baseLine.getCurveLength())
      totalMarginLineLengths.append(coaptationModel.marginLine.getCurveLength())
      distances.extend(coaptationModel.getBaseLineMarginLineDistances())

      appendSurface.AddInputData(coaptationModel.surfaceModelNode.GetPolyData())
      appendBaseLines.AddInputData(coaptationModel.baseLine.curveModelNode.GetPolyData())
      appendMarginLines.AddInputData(coaptationModel.marginLine.curveModelNode.GetPolyData())
    appendSurface.Update()
    appendBaseLines.Update()
    appendMarginLines.Update()
    distances = np.array(distances)

    namePrefix = "Coaptation left side"

    modelsLogic = slicer.modules.models.logic()

    baseLineModelNode = modelsLogic.AddModel(appendBaseLines.GetOutput())
    baseLineModelNode.SetName("CoaptationBaseLineModel left side (all)")
    baseLineModelNode.GetDisplayNode().SetColor(1, 1, 0)
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, baseLineModelNode)

    marginLineModelNode = modelsLogic.AddModel(appendMarginLines.GetOutput())
    marginLineModelNode.SetName("CoaptationMarginLineModel left side (all)")
    marginLineModelNode.GetDisplayNode().SetColor(1, 0.5, 0)
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, marginLineModelNode)

    self.addSurfaceAreaMeasurements("{} area (3D)".format(namePrefix),
                                    appendSurface.GetOutput(), valveModel)

    self.addMeasurement({KEY_NAME: '{} base line length'.format(namePrefix),
                         KEY_VALUE: "{:.1f}".format(np.sum(totalBaselineLengths)),
                         KEY_UNIT: 'mm'})

    self.addMeasurement({KEY_NAME: '{} margin line length'.format(namePrefix),
                         KEY_VALUE: "{:.1f}".format(np.sum(totalMarginLineLengths)),
                         KEY_UNIT: 'mm'})

    for measure in ['min', 'mean', 'max']:
      self.addMeasurement({KEY_NAME: '{} height ({})'.format(namePrefix, measure),
                           KEY_VALUE: "{:.1f}".format(getattr(np, measure)(distances)),
                           KEY_UNIT: 'mm'})

    for percentile in [10, 25, 50, 75, 90]:
      self.addMeasurement({KEY_NAME: '{} height ({}th percentile)'.format(namePrefix, percentile),
                           KEY_VALUE: "{:.1f}".format(np.percentile(distances, percentile)),
                           KEY_UNIT: 'mm'})

    valveModel.removeCoaptationModel(valveModel.coaptationModels.index(leftCenterCoaptationModel))

  @staticmethod
  def createSplittingPlane(valveModel):
    valvePlanePosition, valvePlaneNormal = valveModel.getAnnulusContourPlane()
    centerLinePoints = valveModel.getAnnulusMarkupPositionsByLabels(["MA", "MP"])
    [projectedPoints, _, _] = \
      HeartValveLib.getPointsProjectedToPlane(np.array(centerLinePoints).transpose(), valvePlanePosition,
                                              valvePlaneNormal)
    projectedPoints = projectedPoints.transpose()
    maPointProjected = projectedPoints[0]
    planePosition = np.array(projectedPoints).mean(axis=0)
    x_axis = maPointProjected - planePosition
    x_axis = x_axis / np.linalg.norm(x_axis)
    y_axis = valvePlaneNormal  # subject to change
    z_axis = np.cross(x_axis, y_axis)

    # NB: making sure that the plane covers enough space to correctly cut
    pointL, pointR = valveModel.getAnnulusMarkupPositionsByLabels(["L", "R"])
    pointMA, pointMP = valveModel.getAnnulusMarkupPositionsByLabels(["MA", "MP"])

    valveLength = np.linalg.norm(pointL - pointR) / 2
    valveWidth = np.linalg.norm(pointMA - pointMP) / 2

    x_axis = x_axis * valveLength
    y_axis = y_axis * valveWidth

    # splitting plane
    planeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode")
    planeNode.SetName("Splitting plane")
    valveModel.applyProbeToRasTransformToNode(planeNode)
    planeNode.SetAxes(vtk.vtkVector3d(x_axis), vtk.vtkVector3d(y_axis), vtk.vtkVector3d(z_axis))
    planeNode.SetOrigin(vtk.vtkVector3d(planePosition))
    planeNode.SetAutoSizeScalingFactor(10)
    return planeNode

  @staticmethod
  def getMatchingCoaptations(valveModel, keywords):
    def allKeysInName(keys, name):
      return all(key in name for key in keys)
    matching = list()
    for coaptation in valveModel.coaptationModels:
      if any(allKeysInName(keys, coaptation.getName(valveModel)) for keys in keywords):
        matching.append(coaptation)
    return matching

  def addAnnulusCurveLengthMeasurements(self, valveModel):
    self.addMeasurement(
      self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'L', valveModel, 'MA'))
    self.addMeasurement(
      self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'MA', valveModel, 'R'))
    self.addMeasurement(
      self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'R', valveModel, 'MP'))
    self.addMeasurement(
      self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'MP', valveModel, 'L'))

  def addAngleForAC_LC_R(self, aorticValveModel, valveModel):
    [aorticPlanePosition, _] = aorticValveModel.getAnnulusContourPlane()
    pointR, pointL, pointLA, pointLP = valveModel.getAnnulusMarkupPositionsByLabels(["R", "L", "LA", "LP"])
    [pointLC, _] = HeartValveLib.getLinesIntersectionPoints(pointR, pointL, pointLA, pointLP)
    pointAC_AorticValve = aorticPlanePosition  # AC point is centroid of aortic valve
    self.addMeasurement(self.getDistanceBetweenPoints(valveModel, 'LC', aorticValveModel, 'AC',
                                                      point1_valveModel1=pointLC,
                                                      point2_valveModel2=pointAC_AorticValve))
    pointAC_Cavc = self.transformPointFromValve2ToValve1(valveModel, aorticValveModel, pointAC_AorticValve)
    vector_R_LC = pointR - pointLC
    vector_AC_LC = pointAC_Cavc - pointLC
    self.addMeasurement(self.getAngleBetweenVectors(valveModel, vector_R_LC, valveModel, vector_AC_LC, 'AC-LC-R angle'))
    valveModel.setAnnulusMarkupLabel('LC', pointLC)
    valveModel.setAnnulusMarkupLabel('AC', pointAC_Cavc)

  def addAorticAnnulusLandmarks(self, aorticValveModel, valveModel):
    # landmarks are based on closest point to CAVC centroid and orthogonal directions
    [aorticPlanePosition, aorticPlaneNormal] = aorticValveModel.getAnnulusContourPlane()
    [planePosition, _] = valveModel.getAnnulusContourPlane()
    cavcCentroid_AorticValve = self.transformPointFromValve2ToValve1(aorticValveModel, valveModel, planePosition)
    paDirection_AorticValve = aorticPlanePosition - cavcCentroid_AorticValve
    paDirection_AorticValve = paDirection_AorticValve / np.linalg.norm(paDirection_AorticValve)
    lrDirection_AorticValve = np.cross(paDirection_AorticValve, aorticPlaneNormal)
    # Determine R-L intersection points
    cutPlaneNormal = paDirection_AorticValve
    cutPlanePosition = aorticPlanePosition
    [pointL_AorticValve, pointR_AorticValve] = \
      self.getCurveIntersectionApPointsWithPlane(aorticValveModel, cutPlanePosition, cutPlaneNormal,
                                                 lrDirection_AorticValve)
    # Determine A-P intersection points
    cutPlaneNormal = pointR_AorticValve - aorticPlanePosition
    cutPlaneNormal = cutPlaneNormal / np.linalg.norm(cutPlaneNormal)
    [pointP_AorticValve, pointA_AorticValve] = \
      self.getCurveIntersectionApPointsWithPlane(aorticValveModel, cutPlanePosition, cutPlaneNormal,
                                                 paDirection_AorticValve)
    # Add landmarks
    aorticValveModel.setAnnulusMarkupLabel('L', pointL_AorticValve)
    aorticValveModel.setAnnulusMarkupLabel('R', pointR_AorticValve)
    aorticValveModel.setAnnulusMarkupLabel('P', pointP_AorticValve)
    aorticValveModel.setAnnulusMarkupLabel('A', pointA_AorticValve)

  def addAnnulusPointDistanceMeasurements(self, cavcValveModel):
    self.addMeasurement(self.getDistanceBetweenPoints(cavcValveModel, 'L', cavcValveModel, 'R'))
    self.addMeasurement(self.getDistanceBetweenPoints(cavcValveModel, 'MA', cavcValveModel, 'MP'))
    self.addMeasurement(self.getDistanceBetweenPoints(cavcValveModel, 'RA', cavcValveModel, 'RP'))
    self.addMeasurement(self.getDistanceBetweenPoints(cavcValveModel, 'LA', cavcValveModel, 'LP'))

  def computeAnnulusHeightForEachSide(self, valveModel):
    pointMA, pointMP, pointL = valveModel.getAnnulusMarkupPositionsByLabels(["MA", "MP", "L"])
    annulusContourSideStartIndices = self.getAnnulusContourSplitSidesStartIndices(valveModel, pointMA, pointMP, pointL)
    for curveSideName, startEndPointIndex in annulusContourSideStartIndices.items():
      annulusPoints = self.getAnnulusCurvePoints(valveModel, startEndPointIndex)
      self.createAnnulusCurveModel(valveModel, annulusPoints, curveSideName)
      halfPlanePosition, halfPlaneNormal = self.getPartialContourPlane(annulusPoints, valveModel)
      self.createAnnulusPlaneModel(valveModel, annulusPoints, halfPlanePosition, halfPlaneNormal,
                                   "Annulus plane " + curveSideName)
      self.addCavcAnnulusHeightMeasurements(valveModel, curveSideName, startEndPointIndex)

  def addCavcAnnulusHeightMeasurements(self, valveModel, curveSideName, startEndPointIndex):
    annulusPoints = self.getAnnulusCurvePoints(valveModel, startEndPointIndex)
    annulusPointsProjected, pointsOnPositiveSideOfPlane = self.getPlaneProjectedPoints(valveModel, startEndPointIndex)
    # Create annulus height measurements
    distancesFromValvePlane = np.linalg.norm(annulusPoints - annulusPointsProjected, axis=0)
    pointsAbovePlane = pointsOnPositiveSideOfPlane
    pointsBelowPlane = ~pointsOnPositiveSideOfPlane
    # ...[pointsAbovePlane] selects the points that are above the annulus plane
    annulusTopPointIndex = distancesFromValvePlane[pointsAbovePlane].argmax()
    annulusBottomPointIndex = distancesFromValvePlane[pointsBelowPlane].argmax()
    annulusHeightAbove = distancesFromValvePlane[pointsAbovePlane][annulusTopPointIndex]
    annulusHeightBelow = distancesFromValvePlane[pointsBelowPlane][annulusBottomPointIndex]
    self.addMeasurement(
      {KEY_NAME: 'Annulus ' + curveSideName + ' height',
       KEY_VALUE: "{:.1f}".format(annulusHeightAbove + annulusHeightBelow),
       KEY_UNIT: 'mm'})
    self.addMeasurement(
      {KEY_NAME: 'Annulus ' + curveSideName + ' height above',
       KEY_VALUE: "{:.1f}".format(annulusHeightAbove),
       KEY_UNIT: 'mm'})
    self.addMeasurement(
      {KEY_NAME: 'Annulus ' + curveSideName + ' height below',
       KEY_VALUE: "{:.1f}".format(annulusHeightBelow),
       KEY_UNIT: 'mm'})

    # Add annulus height lines
    annulusTopLineModel = self.createLineModel('Annulus ' + curveSideName + ' height ' + curveSideName + ' (above)',
                                               annulusPoints[:, pointsAbovePlane][:, annulusTopPointIndex],
                                               annulusPointsProjected[:, pointsAbovePlane][:,
                                               annulusTopPointIndex])
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, annulusTopLineModel)

    annulusBottomLineModel = self.createLineModel('Annulus ' + curveSideName + ' height ' + curveSideName + ' (below)',
                                                  annulusPoints[:, pointsBelowPlane][:,
                                                  annulusBottomPointIndex],
                                                  annulusPointsProjected[:, pointsBelowPlane][:,
                                                  annulusBottomPointIndex])
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, annulusBottomLineModel)

  def getPlaneProjectedPoints(self, valveModel, startEndPointIndex):
    annulusPoints = self.getAnnulusCurvePoints(valveModel, startEndPointIndex)
    halfPlanePosition, halfPlaneNormal = self.getPartialContourPlane(annulusPoints, valveModel)
    [annulusPointsProjected, _, pointsOnPositiveSideOfPlane] = \
      HeartValveLib.getPointsProjectedToPlane(annulusPoints, halfPlanePosition, halfPlaneNormal)
    return annulusPointsProjected, pointsOnPositiveSideOfPlane

  def createAnnulusCurveModel(self, valveModel, annulusPoints, curveSideName):
    curveName = "Annulus contour " + curveSideName
    modelNode = \
      self.createCurveModel(curveName, annulusPoints, valveModel.annulusContourCurve.tubeRadius,
                            valveModel.getBaseColor(), valveModel.annulusContourCurve.tubeResolution)
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, modelNode)

  def onInputFieldChanged(self, fieldId, inputValveModels, inputFieldValues, computeDependentValues = False):
    cavcValveModel = inputValveModels["Cavc"] if "Cavc" in inputValveModels.keys() else None
    if not cavcValveModel:
      return

    if fieldId=='RPoint' and cavcValveModel.getAnnulusMarkupPositionByLabel('L') is None and computeDependentValues:
      self.onResetInputField('LPoint', inputValveModels, inputFieldValues)
    if fieldId=='LPoint' and cavcValveModel.getAnnulusMarkupPositionByLabel('R') is None and computeDependentValues:
      self.onResetInputField('RPoint', inputValveModels, inputFieldValues)

    if fieldId=='MaPoint' and cavcValveModel.getAnnulusMarkupPositionByLabel('MP') is None and computeDependentValues:
      self.onResetInputField('MpPoint', inputValveModels, inputFieldValues)
    if fieldId=='MpPoint' and cavcValveModel.getAnnulusMarkupPositionByLabel('MA') is None and computeDependentValues:
      self.onResetInputField('MaPoint', inputValveModels, inputFieldValues)

    # RA and RP points
    if fieldId == 'RaRpPosition' or (fieldId in ['RPoint', 'LPoint', 'MaPoint', 'MpPoint'] and computeDependentValues):
      self.onResetInputField('RaRpPosition', inputValveModels, inputFieldValues)

    # LA and LP points
    if fieldId == 'LaLpPosition' or (fieldId in ['RPoint', 'LPoint', 'MaPoint', 'MpPoint'] and computeDependentValues):
      self.onResetInputField('LaLpPosition', inputValveModels, inputFieldValues)

  def onResetInputField(self, fieldId, inputValveModels, inputFieldValues):
    cavcValveModel = inputValveModels["Cavc"] if "Cavc" in inputValveModels.keys() else None
    if not cavcValveModel:
      return

    if fieldId=='LPoint': # L point (farthest from R)
      pointR = cavcValveModel.getAnnulusMarkupPositionByLabel('R')
      if pointR is not None:
        [pointLPosition, pointLId] = cavcValveModel.annulusContourCurve.getFarthestPoint(pointR)
        cavcValveModel.setAnnulusMarkupLabel('L', pointLPosition)
    elif fieldId=='RPoint': # R point (farthest from L)
      pointL = cavcValveModel.getAnnulusMarkupPositionByLabel('L')
      if pointL is not None:
        [pointRPosition, pointRId] = cavcValveModel.annulusContourCurve.getFarthestPoint(pointL)
        cavcValveModel.setAnnulusMarkupLabel('R', pointRPosition)
    elif fieldId=='MpPoint': # MP point (on the other side of the L-R line from MA, L-R orthogonal to MA-MP)
      pointL = cavcValveModel.getAnnulusMarkupPositionByLabel('L')
      pointR = cavcValveModel.getAnnulusMarkupPositionByLabel('R')
      pointMa = cavcValveModel.getAnnulusMarkupPositionByLabel('MA')
      if pointMa is not None and pointL is not None and pointR is not None:
        defaultMaMpPlaneNormal = pointL-pointR
        defaultMaMpPlanePosition = pointMa
        paVector = pointMa - HeartValveLib.getPointProjectionToLine(pointMa, pointL, pointR)
        [pointMp, pointMaDummy] = self.getCurveIntersectionApPointsWithPlane(cavcValveModel, defaultMaMpPlanePosition, defaultMaMpPlaneNormal, paVector)
        cavcValveModel.setAnnulusMarkupLabel('MP', pointMp)
    elif fieldId=='MaPoint': # MA point (on the other side of the L-R line from MP, L-R orthogonal to MA-MP)
      pointL = cavcValveModel.getAnnulusMarkupPositionByLabel('L')
      pointR = cavcValveModel.getAnnulusMarkupPositionByLabel('R')
      pointMp = cavcValveModel.getAnnulusMarkupPositionByLabel('MP')
      if pointMp is not None and pointL is not None and pointR is not None:
        defaultMaMpPlaneNormal = pointL-pointR
        defaultMaMpPlanePosition = pointMp
        apVector = pointMp - HeartValveLib.getPointProjectionToLine(pointMp, pointL, pointR)
        [pointMa, pointMpDummy] = self.getCurveIntersectionApPointsWithPlane(cavcValveModel, defaultMaMpPlanePosition, defaultMaMpPlaneNormal, apVector)
        cavcValveModel.setAnnulusMarkupLabel('MA', pointMa)
    elif fieldId=='RaRpPosition': # RA-RP line position (parallel to MA-MP line, on the right side of the valve)
      maMpPlaneNormal = None
      pointL = cavcValveModel.getAnnulusMarkupPositionByLabel('L')
      pointR = cavcValveModel.getAnnulusMarkupPositionByLabel('R')
      pointMa = cavcValveModel.getAnnulusMarkupPositionByLabel('MA')
      pointMp = cavcValveModel.getAnnulusMarkupPositionByLabel('MP')
      if pointL is not None and pointR is not None and pointMa is not None and pointMp is not None:
        [pointXonLr, pointXonMaMp] = HeartValveLib.getLinesIntersectionPoints(pointL, pointR, pointMa, pointMp)
        maMpPlanePosition = pointXonLr
        valveNormalVector = np.cross(pointL-pointR, pointMp-pointMa)
        maMpPlaneNormal = np.cross(pointMp-pointMa, valveNormalVector)
        maMpPlaneNormal = maMpPlaneNormal/np.linalg.norm(maMpPlaneNormal) # normalize
        paVector = pointMa - pointMp
      raRpPosition = inputFieldValues['RaRpPosition'] if 'RaRpPosition' in inputFieldValues.keys() else None
      if raRpPosition and maMpPlaneNormal is not None and maMpPlaneNormal is not None and pointR is not None and pointL is not None:
        planePosition = maMpPlanePosition + (pointR-maMpPlanePosition)*raRpPosition*0.01
        [pointRp, pointRa] = self.getCurveIntersectionApPointsWithPlane(cavcValveModel, planePosition, maMpPlaneNormal, paVector)
        cavcValveModel.setAnnulusMarkupLabel('RP', pointRp)
        cavcValveModel.setAnnulusMarkupLabel('RA', pointRa)
      else:
        cavcValveModel.removeAnnulusMarkupLabel('RP')
        cavcValveModel.removeAnnulusMarkupLabel('RA')
    elif fieldId=='LaLpPosition': # LA-LP line position (parallel to MA-MP line, on the left side of the valve)
      maMpPlaneNormal = None
      pointL = cavcValveModel.getAnnulusMarkupPositionByLabel('L')
      pointR = cavcValveModel.getAnnulusMarkupPositionByLabel('R')
      pointMa = cavcValveModel.getAnnulusMarkupPositionByLabel('MA')
      pointMp = cavcValveModel.getAnnulusMarkupPositionByLabel('MP')
      if pointL is not None and pointR is not None and pointMa is not None and pointMp is not None:
        [pointXonLr, pointXonMaMp] = HeartValveLib.getLinesIntersectionPoints(pointL, pointR, pointMa, pointMp)
        maMpPlanePosition = pointXonLr
        valveNormalVector = np.cross(pointL-pointR, pointMp-pointMa)
        maMpPlaneNormal = np.cross(pointMp-pointMa, valveNormalVector)
        maMpPlaneNormal = maMpPlaneNormal/np.linalg.norm(maMpPlaneNormal) # normalize
        paVector = pointMa - pointMp
      laLpPosition = inputFieldValues['LaLpPosition'] if 'LaLpPosition' in inputFieldValues.keys() else None
      if laLpPosition and maMpPlaneNormal is not None and maMpPlaneNormal is not None and pointR is not None and pointL is not None:
        planePosition = maMpPlanePosition + (pointL-maMpPlanePosition)*laLpPosition*0.01
        [pointLp, pointLa] = self.getCurveIntersectionApPointsWithPlane(cavcValveModel, planePosition, maMpPlaneNormal, paVector)
        cavcValveModel.setAnnulusMarkupLabel('LP', pointLp)
        cavcValveModel.setAnnulusMarkupLabel('LA', pointLa)
      else:
        cavcValveModel.removeAnnulusMarkupLabel('LP')
        cavcValveModel.removeAnnulusMarkupLabel('LA')


def cutModel(modelNode, planeNode, cappingOn=True):

  planecutModeler = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLDynamicModelerNode")
  planecutModeler.SetToolName("Plane cut")
  planecutModeler.SetNodeReferenceID("PlaneCut.InputModel", modelNode.GetID())
  planecutModeler.SetNodeReferenceID("PlaneCut.InputPlane", planeNode.GetID())
  if cappingOn is False:
    planecutModeler.SetAttribute("CapSurface", "0")

  outputPositiveModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")
  outputNegativeModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")

  planecutModeler.SetNodeReferenceID("PlaneCut.OutputPositiveModel", outputPositiveModelNode.GetID())
  planecutModeler.SetNodeReferenceID("PlaneCut.OutputNegativeModel", outputNegativeModelNode.GetID())

  planecutModeler.SetContinuousUpdate(True)
  slicer.mrmlScene.RemoveNode(planecutModeler)

  return outputNegativeModelNode, outputPositiveModelNode


def getControlPointsWorldAsArray(smoothCurve):
  nOfControlPoints = smoothCurve.controlPointsMarkupNode.GetNumberOfFiducials() if smoothCurve.controlPointsMarkupNode else 0
  points = np.zeros([3, nOfControlPoints])
  pos = [0.0, 0.0, 0.0]
  for i in range(0, nOfControlPoints):
    smoothCurve.controlPointsMarkupNode.GetNthControlPointPositionWorld(i, pos)
    points[0, i] = pos[0]
    points[1, i] = pos[1]
    points[2, i] = pos[2]
  return points


def setControlPointsWorldFromArray(coaptationModel, controlPointsArray):
  coaptationModel.controlPointsMarkupNode.RemoveAllMarkups()
  wasModifying = coaptationModel.controlPointsMarkupNode.StartModify()
  for controlPointPos in controlPointsArray:
    fidIndex = coaptationModel.controlPointsMarkupNode.AddControlPointWorld(vtk.vtkVector3d(controlPointPos))
    # Deselect it because usually only one markup point is selected
    coaptationModel.controlPointsMarkupNode.SetNthFiducialSelected(fidIndex, False)
  coaptationModel.controlPointsMarkupNode.EndModify(wasModifying)


def getAbovePlaneIndicator(pointsArray, planePosition, planeNormal):
  numberOfPoints = pointsArray.shape[1]
  pointsArray_World = np.row_stack((pointsArray, np.ones(numberOfPoints)))
  from ValveModel import getTransformToPlane
  transformWorldToPlane = getTransformToPlane(planePosition, planeNormal)
  # Point positions in the plane coordinate system:
  pointsArray_Plane = np.dot(transformWorldToPlane, pointsArray_World)
  pointsAbovePlane = pointsArray_Plane[2, :] > 0

  return pointsAbovePlane


def getPointPosition(callback):
  pos = [0, 0, 0]
  callback(pos)
  return np.array(pos)


def getIntersectionPos(planeOrigin, planeNormal, p1, p2):
  """ based on: https://stackoverflow.com/a/39424162/2160261 """
  lineDirection = p2 - p1
  ndotu = planeNormal.dot(lineDirection)

  epsilon = 1e-6

  if abs(ndotu) < epsilon:
    #         print ("no intersection or line is within plane")
    return None

  w = p1 - planeOrigin
  si = -planeNormal.dot(w) / ndotu
  intersection = w + si * lineDirection + planeOrigin
  return intersection


def getLeftCoaptationPointsIncludingIntersection(smoothCurve, planeNode):
  # order is from above plane towards below plane
  # left to right
  controlPoints = getControlPointsWorldAsArray(smoothCurve).transpose()
  planeNormal = getPointPosition(planeNode.GetNormalWorld)
  planeOrigin = getPointPosition(planeNode.GetOriginWorld)

  abovePlane = getAbovePlaneIndicator(np.array([controlPoints[0], controlPoints[-1]]).transpose(), planeOrigin,
                                      planeNormal)

  direction = 1 if abovePlane[0] else -1

  newArray = []
  for pos0, pos1 in zip(controlPoints[::direction], controlPoints[1::direction]):
    abovePlane = getAbovePlaneIndicator(np.array([pos0, pos1]).transpose(), planeOrigin, planeNormal)
    newArray.append(pos0)
    if abovePlane[0] == True and abovePlane[1] == False:
      intersectionPos = getIntersectionPos(planeOrigin, planeNormal, pos0, pos1)
      newArray.append(intersectionPos)
      # print("found intersection")
      # print(newArray[-1])
      break
  return np.array(newArray)
