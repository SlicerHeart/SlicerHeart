#
#   MeasurementPreset: base class for all measurement presets
#

import vtk, slicer
import math
import numpy as np
import vtk.util.numpy_support as VN
import logging
import HeartValveLib
from HeartValveLib.helpers import getBinaryLabelmapRepresentation
from HeartValveLib.util import translatePolyData, smoothPolyData, windowSincPolyData, remeshPolyData, mergePolydata
import vtkSegmentationCorePython as vtkSegmentationCore

FIELD_ID = 'id' # machine-readable ID to easily refer to a field in the source code
FIELD_TYPE = 'type' # allowed values: FIELD_TYPE_...
FIELD_REQUIRED = 'required'
FIELD_ON_ANNULUS_CONTOUR = 'onAnnulusContour'
FIELD_NAME = 'name'
FIELD_VALVE_ID = 'valveId'
FIELD_UNIT = 'unit'
FIELD_DEFAULT_VALUE = 'defaultValue'
FIELD_MIN_VALUE = 'minValue'
FIELD_MAX_VALUE = 'maxValue'
FIELD_STEP_SIZE = 'stepSize'

FIELD_TYPE_POINT = 'point'
FIELD_TYPE_SCALAR = 'scalar'

KEY_NAME = 'name'
KEY_VALUE = 'value'
KEY_UNIT = 'unit'
KEY_MESSAGE = 'message'
KEY_SUCCESS = 'success'


def createPointInputField(fId, name, valveId, required, snapToAnnulusContour=True):
  return {
    FIELD_TYPE: FIELD_TYPE_POINT,
    FIELD_ID: fId,
    FIELD_NAME: name,
    FIELD_VALVE_ID: valveId,
    FIELD_REQUIRED: required,
    FIELD_ON_ANNULUS_CONTOUR: snapToAnnulusContour
  }


def createScalarInputField(fId, name, defaultValue, unit, minValue, maxValue, stepSize):
  return {
    FIELD_TYPE: FIELD_TYPE_SCALAR,
    FIELD_ID: fId,
    FIELD_NAME: name,
    FIELD_DEFAULT_VALUE: defaultValue,
    FIELD_UNIT: unit,
    FIELD_MIN_VALUE: minValue,
    FIELD_MAX_VALUE: maxValue,
    FIELD_STEP_SIZE: stepSize
  }


class MetricsTable(object):

  TABLE_COLUMNS = ['Metric', 'Value', 'Unit']

  @property
  def metricTableNode(self):
    return self._metricsTableNode

  def __init__(self, name):
    self._metricsTableNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTableNode')
    self._metricsTableNode.SetName(name)
    self._metricsTableNode.SetUseColumnNameAsColumnHeader(True)
    for col in self.TABLE_COLUMNS:
      self._metricsTableNode.AddColumn().SetName(col)

  def addMeasurement(self, measurement):
    rowIndex = self._metricsTableNode.AddEmptyRow()
    self._metricsTableNode.SetCellText(rowIndex, 0, measurement[KEY_NAME])
    self._metricsTableNode.SetCellText(rowIndex, 1, measurement[KEY_VALUE])
    self._metricsTableNode.SetCellText(rowIndex, 2, measurement[KEY_UNIT])


class MeasurementPreset(object):

  QUANTIFICATION_RESULTS_IDENTIFIER = "Quantification results"

  def __init__(self):
    self.id = None # machine-readable name (no spaces or special characters)
    self.name = None # human-readable name
    self.inputValveIds = [] # machine-readable name of input valves
    self.inputValveNames = {} # map from inputValveId to human-readable name

    # Points or values defined by the user to define input positions for computations:
    # The user may click in a viewer to specify point position directly (FIELD_TYPE_POINT)
    # or adjust point/line positions with a slider (FIELD_TYPE_SCALAR).
    self.inputFields = []
    self.inputFieldsComment = ""
    self.definitionsUrl = ""

  @classmethod
  def areRequiredLandmarksAvailable(cls, valveModel, names):
    points = valveModel.getAnnulusMarkupPositionsByLabels(names)
    valid = all(pt is not None for pt in points)
    return valid

  @classmethod
  def getResourceFileUrl(cls, filename):
    import inspect
    import os
    valveQuantificationLibDir = os.path.dirname(inspect.getfile(cls))
    filepath = os.path.normpath(
      os.path.join(valveQuantificationLibDir, '..', 'Resources', 'MeasurementPreset', filename))
    from urllib import request
    url = request.pathname2url(filepath)
    return "file://{}".format(url)

  def onInputFieldChanged(self, fieldId, inputValveModels, inputFieldValues, computeDependentValues=False):
    pass

  def onResetInputField(self, fieldId, inputValveModels, inputFieldValues):
    pass

  def computeMetricsForMeasurementNode(self, measurementNode):
    inputValveModels = dict()
    for inputValveId in self.inputValveIds:
      role = 'Valve' + inputValveId
      heartValveNode = measurementNode.GetNodeReference(role)
      if heartValveNode:
        valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)
        inputValveModels[inputValveId] = valveModel
    return self.computeMetrics(inputValveModels, measurementNode)

  def computeMetrics(self, inputValveModels, folderNode):
    self.folderNode = folderNode
    self.clearFolder()
    self.metricsMessages = []
    self.metricsTable = MetricsTable(self.QUANTIFICATION_RESULTS_IDENTIFIER)
    self.moveNodeToMeasurementFolder(self.metricsTable.metricTableNode)
    return self.metricsMessages

  def addMeasurement(self, measurement):
    """ puts results into metricsTable and self.metricsMessages """
    if KEY_MESSAGE in measurement.keys() and measurement[KEY_MESSAGE] is not None:
        self.addMessage(measurement[KEY_MESSAGE])
    if KEY_SUCCESS in measurement.keys() and not measurement[KEY_SUCCESS]:
      return
    self.metricsTable.addMeasurement(measurement)

  def addMessage(self, measurementMessage):
    self.metricsMessages.append(measurementMessage)

  def applyProbeToRASAndMoveToMeasurementFolder(self, valveModel, modelNode, shParentFolderId=None):
    if modelNode is not None:
      valveModel.applyProbeToRasTransformToNode(modelNode)
      self.moveNodeToMeasurementFolder(modelNode, shParentFolderId)

  def moveNodeToMeasurementFolder(self, node, shParentFolderId=None):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    if shParentFolderId is None:
      shNode.SetItemParent(shNode.GetItemByDataNode(node), shNode.GetItemByDataNode(self.folderNode))
    else:
      shNode.SetItemParent(shNode.GetItemByDataNode(node), shParentFolderId)

  def clearFolder(self):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    shNode.RemoveItemChildren(shNode.GetItemByDataNode(self.folderNode))

  def getAnnulusCircumference(self, valveModel, name='Annulus'):
    return {
      KEY_NAME: '{} circumference (3D)'.format(name),
      KEY_VALUE: "{:.1f}".format(valveModel.annulusContourCurve.getCurveLength()),
      KEY_UNIT: 'mm' }

  @staticmethod
  def transformPointFromValve2ToValve1(valveModel1, valveModel2, point_ValveModel2):
    """Transform point defined in valveModel2 coordinate system to valvemodel1 coordinate system
    :param point_ValveModel2: numpy array with 3 elements
    :return point in ValveModel1 coordinate system, numpy array with 3 elements
    """
    probe1ToRasTransformNode = valveModel1.getProbeToRasTransformNode()
    probe2ToRasTransformNode = valveModel2.getProbeToRasTransformNode()
    # TODO: add method to vtkMRMLTransformNode::GetMatrixTransformBetweenNodes(from, to, matrix)
    annulus2ToAnnulus1TransformMatrix = vtk.vtkMatrix4x4()
    if probe2ToRasTransformNode:
      probe2ToRasTransformNode.GetMatrixTransformToNode(probe1ToRasTransformNode, annulus2ToAnnulus1TransformMatrix)
    elif probe1ToRasTransformNode:
      probe1ToRasTransformNode.GetMatrixTransformFromWorld(annulus2ToAnnulus1TransformMatrix)
    # convert numpy array to homogeneous representation
    pointH_ValveModel2 = np.append(point_ValveModel2,1)
    pointH_ValveModel1 = annulus2ToAnnulus1TransformMatrix.MultiplyPoint(pointH_ValveModel2)
    return np.array(pointH_ValveModel1)[:-1] # convert to numpy array and remove last element

  def transformVectorFromValve2ToValve1(self, valveModel1, valveModel2, vector_ValveModel2):
    """Transform vector defined in valveModel2 coordinate system to valvemodel1 coordinate system
    :param valveModel1: valve coordinate system to transform to; if None then the world coordinate system is used
    :param valveModel2: valve coordinate system to transform from; if None then the world coordinate system is used
    :param vector_ValveModel2: vector in ValveModel2 coordinate system, numpy array with 3 elements
    :return vector in ValveModel1 coordinate system, numpy array with 3 elements
    """
    if valveModel1:
      probe1ToRasTransformNode = valveModel1.getProbeToRasTransformNode()
    else:
      probe1ToRasTransformNode = None
    if valveModel2:
      probe2ToRasTransformNode = valveModel2.getProbeToRasTransformNode()
    else:
      probe2ToRasTransformNode = None
    # TODO: add method to vtkMRMLTransformNode::GetMatrixTransformBetweenNodes(from, to, matrix)
    annulus2ToAnnulus1TransformMatrix = vtk.vtkMatrix4x4()
    if probe2ToRasTransformNode:
      probe2ToRasTransformNode.GetMatrixTransformToNode(probe1ToRasTransformNode, annulus2ToAnnulus1TransformMatrix)
    elif probe1ToRasTransformNode:
      probe1ToRasTransformNode.GetMatrixTransformToWorld(annulus2ToAnnulus1TransformMatrix)
      annulus2ToAnnulus1TransformMatrix.Invert() # result is annulus1FromWorld = world to annulus1
    # convert numpy array to homogeneous representation
    vectorH_ValveModel2 = np.append(vector_ValveModel2,0)
    vectorH_ValveModel1 = annulus2ToAnnulus1TransformMatrix.MultiplyPoint(vectorH_ValveModel2)
    return np.array(vectorH_ValveModel1)[:-1] # convert to numpy array and remove last element

  def getDistanceBetweenPoints(self, valveModel1, pointLabel1, valveModel2, pointLabel2, name=None,
                               point1_valveModel1=None, point2_valveModel2=None, oriented=False,
                               positiveDirection_valveModel1=None, shParentFolderId=None):
    """Create a measurement of distance between two points
    :param pointLabel1: numpy array of 3 coordinate values, if point1_valveModel1 is not specified then the position of the annulus contour point with this label will be used
    :param pointLabel2: numpy array of 3 coordinate values, if point2_valveModel2 is not specified then the position of the annulus contour point with this label will be used
    :param point1_valveModel1: position of point1 in valveModel1 coordinate system (optional)
    :param point2_valveModel2: position of point1 in valveModel2 coordinate system (optional)
    :param oriented: if False then a line segments with two sphere endpoints drawn, if True then an arrow is drawn (optional)
    :param positiveDirection_valveModel1: If not None then this direction is used for determining the sign of the displacement
    """
    if point1_valveModel1 is None:
      point1_valveModel1 = valveModel1.getAnnulusMarkupPositionByLabel(pointLabel1)
    if point2_valveModel2 is None:
      point2_valveModel2 = valveModel2.getAnnulusMarkupPositionByLabel(pointLabel2)
    if name is None:
      name = pointLabel1+'-'+pointLabel2+' distance'
    result = {
      KEY_NAME: name,
      KEY_SUCCESS: False
    }
    if point1_valveModel1 is None or point2_valveModel2 is None:
      result[KEY_MESSAGE] = 'Points ' + pointLabel1 + ' and ' + pointLabel2 + ' have to be defined to compute ' + result[KEY_NAME] + '.'
      return result

    # Transform point2 to valvemodel1 coordinate system
    point2_valveModel1 = self.transformPointFromValve2ToValve1(valveModel1, valveModel2, point2_valveModel2)

    distanceMm = np.linalg.norm(point1_valveModel1-point2_valveModel1)
    if positiveDirection_valveModel1 is not None:
      if np.dot(positiveDirection_valveModel1, point2_valveModel1-point1_valveModel1) < 0:
        distanceMm = -distanceMm
    result[KEY_VALUE] = "{:.1f}".format(distanceMm)
    result[KEY_UNIT] = 'mm'
    result[KEY_SUCCESS] = True
    createModelMethod = self.createArrowModel if oriented else self.createLineModel
    lineModel = createModelMethod(result[KEY_NAME], point1_valveModel1, point2_valveModel1)
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel1, lineModel, shParentFolderId)

    return result

  def getCurveLengthBetweenPoints(self, valveModel1, curve, pointLabel1, valveModel2, pointLabel2, name=None,
                                  point1_valveModel1=None, point2_valveModel2=None, oriented=False,
                                  positiveDirection_valveModel1=None, shParentFolderId=None, radius=None,
                                  color=None, visibility=False):
    """Create a measurement of curve length between two points
    :param valveModel1: valve model to allow to get point by label and get valve coordinate system
    :param curve: curve the distance should be computed along (SmoothCurve). It must be under the same transform as valveModel1.
    :param pointLabel1: numpy array of 3 coordinate values, if point1_valveModel1 is not specified then the position of the annulus contour point with this label will be used
    :param valveModel2: valve model to allow to get point by label and get valve coordinate system
    :param pointLabel2: numpy array of 3 coordinate values, if point2_valveModel2 is not specified then the position of the annulus contour point with this label will be used
    :param name: measurement name (optional)
    :param point1_valveModel1: position of point1 in valveModel1 coordinate system (optional)
    :param point2_valveModel2: position of point1 in valveModel2 coordinate system (optional)
    :param oriented: if True then the curve is travelled from point1 to point2 along positive rotation direction (using positiveDirection as axis direction and right-hand-rule),
      if False then the shortest distance along the curve is returned.
    :param positivedirection_valveModel1: direction of the axis of rotation (required if oriented=True)
    :param shParentFolderId: subject hierarchy folder where the measurement will be placed under
    :param radius: radius of the created curve segment model
    :param color: color of the created curve segment model
    :param visibility: visibility of the created curve segment model
    """
    if color is None:
      color = [1, 1, 0]
    if point1_valveModel1 is None:
      point1_valveModel1 = valveModel1.getAnnulusMarkupPositionByLabel(pointLabel1)
    if point2_valveModel2 is None:
      point2_valveModel2 = valveModel2.getAnnulusMarkupPositionByLabel(pointLabel2)
    if name is None:
      name = pointLabel1+'-'+pointLabel2+' distance along annulus curve'
    result = {
      KEY_NAME: name,
      KEY_SUCCESS: False
    }
    if point1_valveModel1 is None or point2_valveModel2 is None:
      result[KEY_MESSAGE] = 'Points ' + pointLabel1 + ' and ' + pointLabel2 + ' have to be defined to compute ' + result[KEY_NAME] + '.'
      return result

    # Transform point2 to valvemodel1 coordinate system
    point2_valveModel1 = self.transformPointFromValve2ToValve1(valveModel1, valveModel2, point2_valveModel2)

    [closestPointOnCurve1, closestPointId1] = curve.getClosestPoint(point1_valveModel1)
    [closestPointOnCurve2, closestPointId2] = curve.getClosestPoint(point2_valveModel1)

    if oriented:
      curvePoints = curve.getInterpolatedPointsAsArray()
      [_, annulusPointsProjected_Plane, _] = HeartValveLib.getPointsProjectedToPlane(curvePoints, [0.0, 0.0, 0.0], positiveDirection_valveModel1)
      points = vtk.vtkPoints()
      nInterpolatedPoints = annulusPointsProjected_Plane.shape[1]
      points.Allocate(nInterpolatedPoints)
      for i in range(nInterpolatedPoints):
        points.InsertNextPoint(annulusPointsProjected_Plane[0, i], annulusPointsProjected_Plane[1, i], 0)

      # Positive rotation direction according to right-hand-rule is counter-clockwise
      if slicer.vtkSlicerMarkupsLogic.IsPolygonClockwise(points):
        startPointIndex = closestPointId2
        endPointIndex = closestPointId1
      else:
        startPointIndex = closestPointId1
        endPointIndex = closestPointId2

      lengthMm = curve.getCurveLengthBetweenStartEndPoints(startPointIndex, endPointIndex)

    else:
      # Non-oriented, use the shorter section of the curve
      length1to2 = curve.getCurveLengthBetweenStartEndPoints(closestPointId1, closestPointId2)
      length2to1 = curve.getCurveLengthBetweenStartEndPoints(closestPointId2, closestPointId1)
      if length1to2<length2to1:
        startPointIndex = closestPointId1
        endPointIndex = closestPointId2
        lengthMm = length1to2
      else:
        startPointIndex = closestPointId2
        endPointIndex = closestPointId1
        lengthMm = length2to1

    result[KEY_VALUE] = "{:.1f}".format(lengthMm)
    result[KEY_UNIT] = 'mm'
    result[KEY_SUCCESS] = True

    curvePoints = curve.getInterpolatedPointsAsArray()
    if startPointIndex<=endPointIndex:
      curveSegmentPoints = curvePoints[:,startPointIndex:endPointIndex+1]
    else:
      curveSegmentPoints = np.hstack((curvePoints[:, startPointIndex:],
                                       curvePoints[:, :endPointIndex]))

    if radius is None:
      radius = curve.tubeRadius * 1.1

    curveModel = self.createCurveModel(name, curveSegmentPoints, radius, color, curve.tubeResolution, visibility)
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel1, curveModel, shParentFolderId)

    return result

  def getAngleBetweenVectors(self, valveModel1, vector1_ValveModel1, valveModel2, vector2_ValveModel2, name):
    """Create a measurement of angle between two vectors
    :return Angle between 0-180deg
    """
    # Transform vector 2 to the first valve's coordinate system
    vector2_ValveModel1 = self.transformVectorFromValve2ToValve1(valveModel1, valveModel2, vector2_ValveModel2)
    # Compute angle (0 <= angle <= 180)
    angleDeg = vtk.vtkMath.DegreesFromRadians(vtk.vtkMath.AngleBetweenVectors(vector1_ValveModel1, vector2_ValveModel1))
    result = {
      KEY_NAME: name,
      KEY_VALUE: "{:.1f}".format(angleDeg),
      KEY_UNIT: 'deg'
    }
    return result

  def getAngleBetweenPlanes(self, valveModel1, planePosition1_ValveModel1, planeNormal1_ValveModel1, valveModel2,
                            planePosition2_ValveModel2, planeNormal2_ValveModel2, name,
                            signFromPlaneNormalDirection=False, invertDirection=False, parallelIsZeroDeg=False):
    """Create a measurement of angle between two vectors
    :param signFromPlaneNormalDirection If set to True then sign of angle difference is computed from orientation
      difference between planeNormal1_ValveModel1 and planeNormal2_ValveModel2 (negative if the angle between
      vectors would be >90deg). If set to False then sign of planeNormal1_ValveModel1 and planeNormal2_ValveModel2
      are ignored and sign is decided based on which side of plane1 the plane normal lines intersect (positive side
      is determined from valveModel1 plane direction).
    :param invertDirection: if set to True then the sign of angle is inverted compared to what is described
      in signFromPlaneNormalDirection documentation.
    :return Angle absolute value is between -90..90deg if parallelIsZeroDeg is True; 90..270deg otherwise.
    """
    # Transform plane2 to the first valve's coordinate system
    planePosition2_ValveModel1 = self.transformPointFromValve2ToValve1(valveModel1, valveModel2, planePosition2_ValveModel2)
    planeNormal2_ValveModel1 = self.transformVectorFromValve2ToValve1(valveModel1, valveModel2, planeNormal2_ValveModel2)

    # Compute angle (0 <= angle <= 180)
    angleDeg = vtk.vtkMath.DegreesFromRadians(vtk.vtkMath.AngleBetweenVectors(planeNormal1_ValveModel1, planeNormal2_ValveModel1))

    if signFromPlaneNormalDirection:
      # Simply use angle between plane normals
      if angleDeg>90.0:
        angleDeg=-(180.0-angleDeg)

    else:
      # Ignore the plane vector orientation (e.g., when comparing two valve planes, relative plane normal direction may be random)

      # bring angle to 0..90deg range, we will determine the sign later
      if angleDeg>90.0:
        angleDeg=180.0-angleDeg

      # Make sure planeNormal1_ValveModel1 points approximately in the same direction as valve plane 1 direction
      [valvePlanePosition, valvePlaneNormal] = valveModel1.getAnnulusContourPlane()
      if np.dot(planeNormal1_ValveModel1, valvePlaneNormal) < 0:
        planeNormal1_ValveModel1 = -planeNormal1_ValveModel1

      # Make the angle signed so that the sign is positive if plane normal intersection point is on the positive side of plane 1.
      [intersectionPoint1, intersectionPoint1] = HeartValveLib.getLinesIntersectionPoints(
        planePosition1_ValveModel1, planePosition1_ValveModel1+planeNormal1_ValveModel1,
        planePosition2_ValveModel1, planePosition2_ValveModel1+planeNormal2_ValveModel1)

      # Planes intersect on the negative side
      if np.dot(planeNormal1_ValveModel1, (intersectionPoint1-planePosition1_ValveModel1)) < 0:
        angleDeg = -angleDeg

    if invertDirection:
      angleDeg = -angleDeg

    if not parallelIsZeroDeg:
      angleDeg += 180.0

    result = {
      KEY_NAME: name,
      KEY_VALUE: "{:.1f}".format(angleDeg),
      KEY_UNIT: 'deg'
    }
    return result

  def getSphericityIndex(self, valveModel, lengthPointLabel1, lengthPointLabel2, widthPointLabel1, widthPointLabel2):
    lengthPoint1 = valveModel.getAnnulusMarkupPositionByLabel(lengthPointLabel1)
    lengthPoint2 = valveModel.getAnnulusMarkupPositionByLabel(lengthPointLabel2)
    widthPoint1 = valveModel.getAnnulusMarkupPositionByLabel(widthPointLabel1)
    widthPoint2 = valveModel.getAnnulusMarkupPositionByLabel(widthPointLabel2)
    result = {
      KEY_NAME: 'Sphericity index (' + lengthPointLabel1 + '-' + lengthPointLabel2 + ' / ' + widthPointLabel1 + '-' + widthPointLabel2 + ')',
      KEY_SUCCESS: False
    }
    if lengthPoint1 is None or lengthPoint2 is None or widthPoint1 is None or widthPoint2 is None:
      result[KEY_MESSAGE] = 'Points ' + lengthPointLabel1 + ', ' + lengthPointLabel2 + ', ' + widthPointLabel1 + ', and ' + widthPointLabel2 + ' have to be defined to compute ' + result[KEY_NAME] + '.'
      return result
    lengthMm = np.linalg.norm(lengthPoint1-lengthPoint2)
    widthMm = np.linalg.norm(widthPoint1-widthPoint2)
    sphericityIndex = lengthMm/widthMm
    result[KEY_VALUE] = "{:.2f}".format(sphericityIndex)
    result[KEY_UNIT] = 'mm/mm'
    result[KEY_SUCCESS] = True
    return result

  def createAnnulusPlaneModel(self, valveModel, annulusPoints, planePosition, planeNormal, name="Annulus plane"):
    [_, annulusPointsProjected_Plane, _] = \
      HeartValveLib.getPointsProjectedToPlane(annulusPoints, planePosition, planeNormal)
    thickness = 0.2 # mm
    planeBoundsMin = annulusPointsProjected_Plane.min(axis=1)[0:2]
    planeBoundsMax = annulusPointsProjected_Plane.max(axis=1)[0:2]
    margin = [ (planeBoundsMax[0]-planeBoundsMin[0])*0.05,  (planeBoundsMax[1]-planeBoundsMin[1])*0.05] # make the plane a bit larger than the annulus (by a 5% margin)
    planeBounds = np.array([planeBoundsMin[0]-margin[0], planeBoundsMax[0]+margin[0], planeBoundsMin[1]-margin[1], planeBoundsMax[1]+margin[1], -thickness/2.0, thickness/2.0])
    annulusPlane = self.createPlaneModel(name, planePosition, planeNormal, planeBounds, color = [0.0,0.0,0.2])
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, annulusPlane)

  def createAnnulusContourModelColoredByDistance(self, valveModel, planePosition, planeNormal):

    nInterpolatedPoints = valveModel.annulusContourCurve.curvePoints.GetNumberOfPoints()
    if nInterpolatedPoints < 2:
      return

    curvePoints = vtk.vtkPoints()
    curvePoints.DeepCopy(valveModel.annulusContourCurve.curvePoints)

    lines = vtk.vtkCellArray()
    lines.InsertNextCell(nInterpolatedPoints+1)
    for i in range(nInterpolatedPoints):
      lines.InsertCellPoint(i)
    lines.InsertCellPoint(0)  # close the curve

    curvePoly = vtk.vtkPolyData()
    curvePoly.SetPoints(curvePoints)
    curvePoly.SetLines(lines)

    plane = vtk.vtkPlane()
    plane.SetOrigin(planePosition)
    plane.SetNormal(planeNormal)

    distanceFromPlaneFilter = vtk.vtkSampleImplicitFunctionFilter()
    distanceFromPlaneFilter.SetImplicitFunction(plane)
    distanceFromPlaneFilter.SetInputData(curvePoly)
    distanceFromPlaneFilter.Update()

    tubeFilter = vtk.vtkTubeFilter()
    tubeFilter.SetInputData(curvePoly)
    # Make tube radius 5% larger than the original contour so that when both
    # are shown in 3D then the colored tube is visible.
    tubeFilter.SetRadius(valveModel.annulusContourCurve.tubeRadius * 1.05)
    tubeFilter.SetNumberOfSides(valveModel.annulusContourCurve.tubeResolution)
    tubeFilter.SetCapping(False)
    tubeFilter.Update()

    coloredTube = tubeFilter.GetOutput()
    numberOfTubePoints = coloredTube.GetNumberOfPoints()

    distFromPlane = distanceFromPlaneFilter.GetOutput()
    curvePointsDistances = distFromPlane.GetPointData().GetArray("Implicit scalars")

    distanceFromPlaneArray = vtk.vtkDoubleArray()
    distanceFromPlaneArray.SetName("Distance")
    distanceFromPlaneArray.Allocate(numberOfTubePoints)
    for pointIndex in range(nInterpolatedPoints):
      for rotationIndex in range(valveModel.annulusContourCurve.tubeResolution):
        # Make distance positive when height is high
        distanceFromPlaneArray.InsertNextValue(-curvePointsDistances.GetValue(pointIndex))

    coloredTube.GetPointData().AddArray(distanceFromPlaneArray)

    # Triangulation is necessary to avoid discontinuous lines
    # in model/slice intersection display
    triangles = vtk.vtkTriangleFilter()
    triangles.SetInputConnection(tubeFilter.GetOutputPort())
    triangles.Update()

    modelsLogic = slicer.modules.models.logic()
    modelNode = modelsLogic.AddModel(triangles.GetOutput())
    modelNode.SetName('Annulus contour colored by height')
    displayNode = modelNode.GetDisplayNode()
    displayNode.SetVisibility(False)
    displayNode.SetActiveScalarName('Distance')
    displayNode.ScalarVisibilityOn()

    # Have a significant ambient lighting (non-direction-dependent) component
    # to make brightness fairly uniform (not make surface too dark if we are
    # looking at it from a shallow angle).
    modelNode.GetDisplayNode().SetAmbient(0.5)
    modelNode.GetDisplayNode().SetDiffuse(0.5)

    distanceRange = curvePointsDistances.GetRange()

    symmetricRange = False

    # Depending on what color node we choose, we may want to make
    # distance range symmetric around 0.
    if symmetricRange and distanceRange[0] < 0 < distanceRange[1]:
      magnitude = max(abs(distanceRange[0]), abs(distanceRange[1]))
      distanceRange = [-magnitude, magnitude]

    baseColorNodeId = 'vtkMRMLColorTableNodeFilePlasma.txt'
    colorNode = slicer.modules.colors.logic().CopyNode(
      slicer.mrmlScene.GetNodeByID(baseColorNodeId), 'Annulus height')
    colorNode.GetLookupTable().SetRange(distanceRange)
    slicer.mrmlScene.AddNode(colorNode)
    colorNode.UnRegister(slicer.mrmlScene)
    self.moveNodeToMeasurementFolder(colorNode)
    displayNode.SetAndObserveColorNodeID(colorNode.GetID())

    # Use the color exactly as defined in the colormap
    displayNode.AutoScalarRangeOff()
    displayNode.SetScalarRangeFlag(displayNode.UseColorNodeScalarRange)
    displayNode.SetScalarRange(distanceRange)  # just in case if switching to manual scalar range

    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, modelNode)

  def addAnnulusHeightMeasurements(self, valveModel, planePosition, planeNormal):
    """
    """
    annulusPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    [annulusPointsProjected, _, pointsOnPositiveSideOfPlane] = \
      HeartValveLib.getPointsProjectedToPlane(annulusPoints, planePosition, planeNormal)
    distancesFromValvePlane = np.linalg.norm(annulusPoints-annulusPointsProjected, axis=0)

    pointsAbovePlane = pointsOnPositiveSideOfPlane
    pointsBelowPlane = ~pointsOnPositiveSideOfPlane

    # ...[pointsAbovePlane] selects the points that are above the annulus plane
    annulusTopPointIndex = distancesFromValvePlane[pointsAbovePlane].argmax()
    annulusBottomPointIndex = distancesFromValvePlane[pointsBelowPlane].argmax()
    annulusHeightAbove = distancesFromValvePlane[pointsAbovePlane][annulusTopPointIndex]
    annulusHeightBelow = distancesFromValvePlane[pointsBelowPlane][annulusBottomPointIndex]
    self.addMeasurement({KEY_NAME: 'Annulus height', KEY_VALUE: "{:.1f}".format(annulusHeightAbove + annulusHeightBelow), KEY_UNIT: 'mm'})
    self.addMeasurement({KEY_NAME: 'Annulus height above', KEY_VALUE: "{:.1f}".format(annulusHeightAbove), KEY_UNIT: 'mm'})
    self.addMeasurement({KEY_NAME: 'Annulus height below', KEY_VALUE: "{:.1f}".format(annulusHeightBelow), KEY_UNIT: 'mm'})
    # Add annulus height lines
    annulusTopLineModel = self.createLineModel('Annulus height (above)', annulusPoints[:,pointsAbovePlane][:,annulusTopPointIndex],
      annulusPointsProjected[:,pointsAbovePlane][:,annulusTopPointIndex])
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, annulusTopLineModel)
    annulusBottomLineModel = self.createLineModel('Annulus height (below)', annulusPoints[:,pointsBelowPlane][:,annulusBottomPointIndex],
      annulusPointsProjected[:,pointsBelowPlane][:,annulusBottomPointIndex])
    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, annulusBottomLineModel)
    # Add annulus plane model
    self.createAnnulusPlaneModel(valveModel, annulusPoints, planePosition, planeNormal)
    # Add annulus contour colored by annulus height
    self.createAnnulusContourModelColoredByDistance(valveModel, planePosition, planeNormal)

  def addCoaptationMeasurements(self, valveModel):
    for coaptationModel in valveModel.coaptationModels:
      surfaceModelNode = coaptationModel.surfaceModelNode

      namePrefix = coaptationModel.getName(valveModel)

      if not surfaceModelNode.GetPolyData():
        valveModel.updateCoaptationModels()

      if not surfaceModelNode.GetPolyData():
        self.metricsMessages.append("No coaptation model found. Skipping.")
        continue

      self.addSurfaceAreaMeasurements("{} area (3D)".format(namePrefix),
                                      surfaceModelNode.GetPolyData(), valveModel)

      self.addMeasurement({KEY_NAME: '{} base line length'.format(namePrefix),
                           KEY_VALUE: "{:.1f}".format(coaptationModel.baseLine.getCurveLength()),
                           KEY_UNIT: 'mm'})

      self.addMeasurement({KEY_NAME: '{} margin line length'.format(namePrefix),
                           KEY_VALUE: "{:.1f}".format(coaptationModel.marginLine.getCurveLength()),
                           KEY_UNIT: 'mm'})

      distances = coaptationModel.getBaseLineMarginLineDistances()

      for measure in ['min', 'mean', 'max']:
        self.addMeasurement({KEY_NAME: '{} height ({})'.format(namePrefix, measure),
                             KEY_VALUE: "{:.1f}".format(getattr(np, measure)(distances)),
                             KEY_UNIT: 'mm'})

      for percentile in [10, 25, 50, 75, 90]:
        self.addMeasurement({KEY_NAME: '{} height ({}th percentile)'.format(namePrefix, percentile),
                             KEY_VALUE: "{:.1f}".format(np.percentile(distances, percentile)),
                             KEY_UNIT: 'mm'})

  def getClipPlanesNormalsOrigin(self, valveModel, planePosition, planeNormal, quadrantPointLabels,
                                 clipBetweenQuadrantPoints=True):
    """

    :param valveModel:
    :param planePosition:
    :param planeNormal:
    :param quadrantPointLabels: (-X, +X, -Y, +Y)
    :param clipBetweenQuadrantPoints: if True then quadrants are cut at halfway between quadrant points
    :param halvesNames: if clipBetweenQuadrantPoints=False then this defines names of halves
    :param quadrantNames: if clipBetweenQuadrantPoints=False then this defines names of quadrants
    :return:
    """

    # Example: quadrantPointLabels=['A', 'P', 'S', 'L']
    quadrantPoints = np.zeros([3, 4])
    halvesNames = []
    quadrantNames = []
    if clipBetweenQuadrantPoints:
      # Example: A, L, P, S
      segmentInfo = valveModel.getAnnulusContourCurveSegments(quadrantPointLabels)
      quadrantPoints[:, 0] = segmentInfo[0]["segmentStartPointPosition"]
      quadrantPoints[:, 1] = segmentInfo[2]["segmentStartPointPosition"]
      quadrantPoints[:, 2] = segmentInfo[1]["segmentStartPointPosition"]
      quadrantPoints[:, 3] = segmentInfo[3]["segmentStartPointPosition"]
      quadrantNames.append(segmentInfo[0]["label"])
      quadrantNames.append(segmentInfo[1]["label"])
      quadrantNames.append(segmentInfo[3]["label"])
      quadrantNames.append(segmentInfo[2]["label"])
      halvesNames.append(segmentInfo[0]["label"] + segmentInfo[3]["label"])
      halvesNames.append(segmentInfo[1]["label"] + segmentInfo[2]["label"])
      halvesNames.append(segmentInfo[0]["label"] + segmentInfo[1]["label"])
      halvesNames.append(segmentInfo[2]["label"] + segmentInfo[3]["label"])
    else:
      for i in range(4):
        quadrantPoints[:,i] = valveModel.getAnnulusMarkupPositionByLabel(quadrantPointLabels[i])
      # Example:
      # halvesNames = ['P', 'A', 'L', 'S']
      # quadrantNames = ['PL', 'AL', 'PS', 'AS']
      halvesNames.append(quadrantPointLabels[0])
      halvesNames.append(quadrantPointLabels[1])
      halvesNames.append(quadrantPointLabels[2])
      halvesNames.append(quadrantPointLabels[3])
      quadrantNames.append(quadrantPointLabels[0] + quadrantPointLabels[2])
      quadrantNames.append(quadrantPointLabels[1] + quadrantPointLabels[2])
      quadrantNames.append(quadrantPointLabels[0] + quadrantPointLabels[3])
      quadrantNames.append(quadrantPointLabels[1] + quadrantPointLabels[3])

    # Transform annulus quadrant divider lines to plane coordinate system
    [quadrantPointsProjected_World, quadrantPointsPointsProjected_Plane, quadrantPointsOnPositiveSideOfPlane] = \
      HeartValveLib.getPointsProjectedToPlane(quadrantPoints, planePosition, planeNormal)
    # Determine quadrant divider lines crossing in the plane
    [quadrantsCrossing_Plane, quadrantsCrossing_Plane2] = HeartValveLib.getLinesIntersectionPoints(
      np.concatenate([quadrantPointsPointsProjected_Plane[:,0],[0]]),
      np.concatenate([quadrantPointsPointsProjected_Plane[:,1],[0]]),
      np.concatenate([quadrantPointsPointsProjected_Plane[:,2],[0]]),
      np.concatenate([quadrantPointsPointsProjected_Plane[:,3],[0]]) )
    # Transform back the crossing to world coordinate system
    transformWorldToPlaneMatrix = HeartValveLib.getTransformToPlane(planePosition, planeNormal)
    transformPlaneToWorldMatrix = np.linalg.inv(transformWorldToPlaneMatrix)
    quadrantsCrossingHomogeneous_Plane = np.concatenate([quadrantsCrossing_Plane,[1]])
    quadrantsCrossingHomogeneous_World = np.dot(transformPlaneToWorldMatrix, quadrantsCrossingHomogeneous_Plane)
    quadrantsCrossing_World = quadrantsCrossingHomogeneous_World[0:3]

    # Clipping planes that divide the plane to halves and quadrants
    planeNormalX = np.cross(quadrantPointsProjected_World[:, 2] - quadrantPointsProjected_World[:, 3], planeNormal)
    if np.dot(planeNormalX, quadrantPointsProjected_World[:, 0]-quadrantPointsProjected_World[:, 1]) > 0:
      planeNormalMinusX = planeNormalX
      planeNormalPlusX = -planeNormalX
    else:
      planeNormalMinusX = -planeNormalX
      planeNormalPlusX = planeNormalX

    planeNormalY = np.cross(quadrantPointsProjected_World[:, 1] - quadrantPointsProjected_World[:, 0], planeNormal)
    if np.dot(planeNormalY, quadrantPointsProjected_World[:, 2]-quadrantPointsProjected_World[:, 3]) > 0:
      planeNormalMinusY = planeNormalY
      planeNormalPlusY = -planeNormalY
    else:
      planeNormalMinusY = -planeNormalY
      planeNormalPlusY = planeNormalY

    return [planeNormalMinusX, planeNormalPlusX, planeNormalMinusY, planeNormalPlusY, quadrantsCrossing_World, halvesNames, quadrantNames]

  def getClipPlanes(self, valveModel, planePosition, planeNormal, quadrantPointLabels, clipBetweenQuadrantPoints=True):
    """Return clipping planes as vtkPlane objects"""

    [planeNormalMinusX, planeNormalPlusX, planeNormalMinusY, planeNormalPlusY, quadrantsCrossing_World, halvesNames, quadrantNames] = \
      self.getClipPlanesNormalsOrigin(valveModel, planePosition, planeNormal, quadrantPointLabels, clipBetweenQuadrantPoints)
    planesNormalsOrigin = [planeNormalMinusX, planeNormalPlusX, planeNormalMinusY, planeNormalPlusY]
    planesOrigin = quadrantsCrossing_World

    planes = []
    for i in range(4):
      plane = vtk.vtkPlane()
      plane.SetNormal(planesNormalsOrigin[i])
      plane.SetOrigin(planesOrigin)
      planes.append(plane)

    return [planes, halvesNames, quadrantNames]

  def addAnnulusAreaMeasurements(self, valveModel, planePosition, planeNormal, mode=None, quadrantPointLabels=None,
                                 invertBendingAngleDirection1=False, invertBendingAngleDirection2=False, name="Annulus"):
    """
    Add annulus area (optionally halves and quadrants)
    :param valveModel:
    :param planePosition:
    :param planeNormal:
    :param mode: 2D or 3D
    :param quadrantPointLabels: 4 annulus points defining halves and quadrants (-X, +X, -Y, +Y)
    :param invertBendingAngleDirection1: invert bending angle signed for first two halves
    :param invertBendingAngleDirection2: invert bending angle signed for second two halves
    :return:
    """
    if not quadrantPointLabels:
      quadrantPointLabels = []

    if not mode:
      self.addAnnulusAreaMeasurements(valveModel, planePosition, planeNormal, "2D", quadrantPointLabels,
                                      invertBendingAngleDirection1, invertBendingAngleDirection2, name)
      self.addAnnulusAreaMeasurements(valveModel, planePosition, planeNormal, "3D", quadrantPointLabels,
                                      invertBendingAngleDirection1, invertBendingAngleDirection2, name)
      return

    annulusPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    if mode == "2D":
      # Transform annulus points to plane coordinate system
      [annulusPointsProjected, _, _] = \
        HeartValveLib.getPointsProjectedToPlane(annulusPoints, planePosition, planeNormal)
      annulusAreaPolyData = self.createPolyDataFromPolygon(annulusPointsProjected.T)
    elif mode == "3D":
      annulusAreaPolyData = self.createSoapBubblePolyDataFromCircumferencePoints(annulusPoints)
    else:
      logging.error("Invalid mode: {0}".format(mode))
      return

    # Full area
    self.addSurfaceAreaMeasurements('{} area ({})'.format(name, mode), annulusAreaPolyData, valveModel)

    # Count how many quadrant separator points are defined (must be 4 for a complete definition)
    numberOfFoundLabels = 0
    for label in quadrantPointLabels:
      if valveModel.getAnnulusLabelsMarkupIndexByLabel(label) >= 0:
        numberOfFoundLabels += 1

    # Only compute halves and quadrants if all 4 quadrant separator points are specified
    if numberOfFoundLabels == 4:

      # Cut quadrants at halfway between landmarks
      for clipBetweenQuadrantPoints in [False, True]:

        nameSuffix = " centered" if clipBetweenQuadrantPoints else ""

        # Add annulus bending angle
        if mode == '3D':
          [_, planeNormalPlusX, _, planeNormalPlusY, planePosition, halvesNames, _] = \
            self.getClipPlanesNormalsOrigin(valveModel, planePosition, planeNormal, quadrantPointLabels,
                                            clipBetweenQuadrantPoints=clipBetweenQuadrantPoints)
          self.addCurveBendingAngleMeasurement('{0} bending angle{1} ({2}-{3})'.format(name, nameSuffix, halvesNames[0], halvesNames[1]), annulusPoints, planePosition, planeNormalPlusX, valveModel, invertDirection=invertBendingAngleDirection1)
          self.addCurveBendingAngleMeasurement('{0} bending angle{1} ({2}-{3})'.format(name, nameSuffix, halvesNames[2], halvesNames[3]), annulusPoints, planePosition, planeNormalPlusY, valveModel, invertDirection=invertBendingAngleDirection2)

        [[planeMinusX, planePlusX, planeMinusY, planePlusY], halvesNames, quadrantNames] = self.getClipPlanes(valveModel, planePosition, planeNormal, quadrantPointLabels, clipBetweenQuadrantPoints=clipBetweenQuadrantPoints)

        # These measurements are the same for both clipBetweenQuadrantPoints True/False, so do them only for one of them:
        if not clipBetweenQuadrantPoints:
          # Add quadrant crossing point.
          quadrantsCrossingPosition = planePlusX.GetOrigin()
          valveModel.setAnnulusMarkupLabel('X', quadrantsCrossingPosition)

          # Add distance measurements between quadrant points and crossing point
          for quadrantIndex in range(4):
            pointLabel1 = quadrantPointLabels[quadrantIndex]
            pointLabel2 = 'X'
            measurementName = pointLabel1 + '-' + pointLabel2 + ' distance (' + mode +')'
            quadrantPoint = valveModel.getAnnulusMarkupPositionByLabel(pointLabel1)
            if mode == '2D':
              quadrantPoint_2D = np.zeros([3, 1])
              quadrantPoint_2D[:, 0] = quadrantPoint
              # For 2D measurements, use the quadrant point position projected to the valve plane
              [quadrantPointProjected_World, quadrantPointPointsProjected_Plane, quadrantPointsOnPositiveSideOfPlane] \
                = HeartValveLib.getPointsProjectedToPlane(quadrantPoint_2D, planePosition, planeNormal)
              quadrantPoint = quadrantPointProjected_World[:, 0]
            self.addMeasurement(self.getDistanceBetweenPoints(valveModel, pointLabel1, valveModel, pointLabel2,
              name=measurementName, point1_valveModel1=quadrantPoint))

        landmarks = ["MA", "MP"]
        if self.areRequiredLandmarksAvailable(valveModel, landmarks):
          pointMA, pointMP = valveModel.getAnnulusMarkupPositionsByLabels(landmarks)
          valveModel.setAnnulusMarkupLabel('MX', np.mean(np.array([pointMA, pointMP]), axis=0))

        # Halves
        self.addSurfaceAreaMeasurements('{0} area{1} ({2}, {3})'.format(name, nameSuffix, mode, halvesNames[0]), annulusAreaPolyData, valveModel, clipPlanes=[planeMinusX])
        self.addSurfaceAreaMeasurements('{0} area{1} ({2}, {3})'.format(name, nameSuffix, mode, halvesNames[1]), annulusAreaPolyData, valveModel, clipPlanes=[planePlusX])
        self.addSurfaceAreaMeasurements('{0} area{1} ({2}, {3})'.format(name, nameSuffix, mode, halvesNames[2]), annulusAreaPolyData, valveModel, clipPlanes=[planeMinusY])
        self.addSurfaceAreaMeasurements('{0} area{1} ({2}, {3})'.format(name, nameSuffix, mode, halvesNames[3]), annulusAreaPolyData, valveModel, clipPlanes=[planePlusY])

        # Quadrants
        self.addSurfaceAreaMeasurements('{0} area{1} ({2}, {3})'.format(name, nameSuffix, mode, quadrantNames[0]), annulusAreaPolyData, valveModel, clipPlanes=[planeMinusX, planeMinusY])
        self.addSurfaceAreaMeasurements('{0} area{1} ({2}, {3})'.format(name, nameSuffix, mode, quadrantNames[1]), annulusAreaPolyData, valveModel, clipPlanes=[planePlusX,  planeMinusY])
        self.addSurfaceAreaMeasurements('{0} area{1} ({2}, {3})'.format(name, nameSuffix, mode, quadrantNames[2]), annulusAreaPolyData, valveModel, clipPlanes=[planeMinusX, planePlusY])
        self.addSurfaceAreaMeasurements('{0} area{1} ({2}, {3})'.format(name, nameSuffix, mode, quadrantNames[3]), annulusAreaPolyData, valveModel, clipPlanes=[planePlusX,  planePlusY])

  @staticmethod
  def createSoapBubblePolyDataFromCircumferencePoints(annulusPoints, radiusScalingFactor=1.0):
    """
    Create a "soap bubble" surface that fits on the provided annulus point list
    :param annulusPoints: points to fit the surface to
    :param radiusScalingFactor: size of the surface. Value of 1.0 (default) means the surface edge fits on the points.
     Larger values increase the generated soap bubble outer radius, which may be useful to avoid coincident points
     when using this surface for cutting another surface.
    :return:
    """
    import math
    numberOfAnnulusPoints = annulusPoints.shape[1]
    numberOfLandmarkPoints =  80

    # Transform a unit disk to the annulus circumference using thin-plate spline interpolation
    # it does not guarantee minimum surface but at least it is a good initial estimate.
    # TODO: add a refinement step when the surface points are adjusted so that the surface
    # area is minimized

    sourceLandmarkPoints = vtk.vtkPoints() # points on the unit disk
    sourceLandmarkPoints.SetNumberOfPoints(numberOfLandmarkPoints) # points on the annulus
    targetLandmarkPoints = vtk.vtkPoints()
    targetLandmarkPoints.SetNumberOfPoints(numberOfLandmarkPoints)
    for pointIndex in range(numberOfLandmarkPoints):
      angle = float(pointIndex)/numberOfLandmarkPoints*2.0*math.pi
      annulusPointIndex = int(round(float(pointIndex)/numberOfLandmarkPoints*numberOfAnnulusPoints))
      sourceLandmarkPoints.SetPoint(pointIndex, math.cos(angle), math.sin(angle), 0)
      targetLandmarkPoints.SetPoint(pointIndex, annulusPoints[:,annulusPointIndex])

    tsp = vtk.vtkThinPlateSplineTransform()
    tsp.SetSourceLandmarks(sourceLandmarkPoints)
    tsp.SetTargetLandmarks(targetLandmarkPoints)

    unitDisk = vtk.vtkDiskSource()
    unitDisk.SetOuterRadius(radiusScalingFactor)
    unitDisk.SetInnerRadius(0.0)
    unitDisk.SetCircumferentialResolution(80)
    unitDisk.SetRadialResolution(15)

    triangulator = vtk.vtkDelaunay2D()
    triangulator.SetTolerance(0.01) # get rid of the small triangles near the center of the unit disk
    triangulator.SetInputConnection(unitDisk.GetOutputPort())

    polyTransformToAnnulus = vtk.vtkTransformPolyDataFilter()
    polyTransformToAnnulus.SetTransform(tsp)
    polyTransformToAnnulus.SetInputConnection(triangulator.GetOutputPort())

    polyDataNormals = vtk.vtkPolyDataNormals()
    polyDataNormals.SetInputConnection(polyTransformToAnnulus.GetOutputPort())
    # There are a few triangles in the triangulated unit disk with inconsistent
    # orientation. Enabling consistency check fixes them.
    polyDataNormals.ConsistencyOn()
    polyDataNormals.Update()
    annulusAreaPolyData = polyDataNormals.GetOutput()

    return annulusAreaPolyData

  def addSurfaceAreaMeasurements(self, name, polyData, valveModel, clipPlanes=None, visibility=False):
    modelsLogic = slicer.modules.models.logic()
    annulusArea3dModel = modelsLogic.AddModel(polyData)
    annulusArea3dModel.SetName(name)
    annulusArea3dModel.GetDisplayNode().SetVisibility(visibility)
    annulusArea3dModel.GetDisplayNode().SetColor(valveModel.getBaseColor())
    annulusArea3dModel.GetDisplayNode().SetOpacity(0.6)
    annulusArea3dModel.GetDisplayNode().SetAmbient(0.1)
    annulusArea3dModel.GetDisplayNode().SetDiffuse(0.9)
    annulusArea3dModel.GetDisplayNode().SetSpecular(0.1)
    annulusArea3dModel.GetDisplayNode().SetPower(10)
    annulusArea3dModel.GetDisplayNode().BackfaceCullingOff()

    self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, annulusArea3dModel)

    # Clip polygon if clipping planes are provided
    if clipPlanes is not None:
      clippedPolyData = annulusArea3dModel.GetPolyData()
      for clipPlane in clipPlanes:
        clip = vtk.vtkClipPolyData()
        clip.SetClipFunction(clipPlane)
        clip.GenerateClipScalarsOn()
        clip.SetInputData(clippedPolyData)
        triangulator = vtk.vtkTriangleFilter()
        triangulator.SetInputConnection(clip.GetOutputPort())
        triangulator.Update()
        clippedPolyData = triangulator.GetOutput()
      annulusArea3dModel.SetAndObservePolyData(clippedPolyData)

    # Compute area
    massProperties = vtk.vtkMassProperties()
    triangulator = vtk.vtkTriangleFilter()
    triangulator.PassLinesOff() # mass properties filter throws a lot of warnings if there are lines in the polydata
    triangulator.SetInputConnection(annulusArea3dModel.GetPolyDataConnection())
    massProperties.SetInputConnection(triangulator.GetOutputPort())
    annulusArea2d = massProperties.GetSurfaceArea()
    self.addMeasurement({KEY_NAME: name, KEY_VALUE: "{:.1f}".format(annulusArea2d), KEY_UNIT: 'mm*mm'})

    return annulusArea3dModel.GetPolyData()

  def addSurfaceAngleMeasurement(self, name, polyDataA, polyDataB, valveModel, visibility = False):
    """This method computes angle between two surfaces by fitting plane to them.
    Currently it is not used, but not deleted because it may be useful in the future."""

    inputPolyData = [polyDataA, polyDataB]
    planeModels = []
    planePositions = []
    planeNormals = []
    for i in range(2):
      planePoints = VN.vtk_to_numpy(inputPolyData[i].GetPoints().GetData()).T
      planePosition, planeNormal = HeartValveLib.planeFit(planePoints)
      planePositions.append(np.copy(planePosition))
      planeNormals.append(np.copy(planeNormal))

      [_, planePointsProjected_Plane, _] = \
        HeartValveLib.getPointsProjectedToPlane(planePoints, planePosition, planeNormal)
      thickness = 0.2  # mm
      planeBoundsMin = planePointsProjected_Plane.min(axis=1)[0:2]
      planeBoundsMax = planePointsProjected_Plane.max(axis=1)[0:2]
      margin = [(planeBoundsMax[0] - planeBoundsMin[0]) * 0.25, (
      planeBoundsMax[1] - planeBoundsMin[1]) * 0.25]  # make the plane a smaller than the surface (by a 25% margin)
      planeBounds = np.array(
        [planeBoundsMin[0] + margin[0], planeBoundsMax[0] - margin[0],
         planeBoundsMin[1] + margin[1], planeBoundsMax[1] - margin[1],
         -thickness / 2.0, thickness / 2.0])

      if i == 0:
        planeModels.append(self.createPlaneModel(name, planePosition, planeNormal, planeBounds, color=[0.0, 0.0, 0.2]))
        self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, planeModels[i])
      elif i != 0 and len(planeModels):
        planeModels.append(self.createPlaneModel(name, planePosition, planeNormal, planeBounds,
                                                 nodeToBeAddedTo=planeModels[0]))

    # Compute angle
    self.addMeasurement(self.getAngleBetweenPlanes(valveModel, planePositions[0], planeNormals[0],
                                                   valveModel, planePositions[1], planeNormals[1], name))

  def addCurveBendingAngleMeasurement(self, name, curvePoints, separatingPlanePosition, separatingPlaneNormal,
                                      valveModel, visibility=False, invertDirection=False):
    """Separate the point set using separating plane. Fit a plane to each, and report the orientation difference."""

    [_, _, pointsOnPositiveSideOfPlane] = \
      HeartValveLib.getPointsProjectedToPlane(curvePoints, separatingPlanePosition, separatingPlaneNormal)

    inputPoints = [curvePoints[:,pointsOnPositiveSideOfPlane], curvePoints[:,~pointsOnPositiveSideOfPlane]]
    planeModels = []
    planePositions = []
    planeNormals = []
    for i in range(2):
      planePoints = inputPoints[i]
      planePosition, planeNormal = HeartValveLib.planeFit(planePoints)
      planePositions.append(np.copy(planePosition))
      planeNormals.append(np.copy(planeNormal))

      [_, planePointsProjected_Plane, _] = \
        HeartValveLib.getPointsProjectedToPlane(planePoints, planePosition, planeNormal)
      thickness = 0.2  # mm
      planeBoundsMin = planePointsProjected_Plane.min(axis=1)[0:2]
      planeBoundsMax = planePointsProjected_Plane.max(axis=1)[0:2]
      # make the plane a bit larger than the surface
      marginPercent = -0.10
      margin = [(planeBoundsMax[0] - planeBoundsMin[0]) * marginPercent, (
      planeBoundsMax[1] - planeBoundsMin[1]) * marginPercent]
      planeBounds = np.array(
        [planeBoundsMin[0] + margin[0], planeBoundsMax[0] - margin[0],
         planeBoundsMin[1] + margin[1], planeBoundsMax[1] - margin[1],
         -thickness / 2.0, thickness / 2.0])

      if i == 0:
        planeModels.append(self.createPlaneModel(name, planePosition, planeNormal, planeBounds, color=[0.0, 0.0, 0.2]))
        self.applyProbeToRASAndMoveToMeasurementFolder(valveModel, planeModels[i])
      elif i != 0 and len(planeModels):
        planeModels.append(self.createPlaneModel(name, planePosition, planeNormal, planeBounds,
                                                 nodeToBeAddedTo=planeModels[0]))

    # Compute angle
    self.addMeasurement(self.getAngleBetweenPlanes(valveModel, planePositions[0], planeNormals[0],
                                                   valveModel, planePositions[1], planeNormals[1], name,
                                                   invertDirection=invertDirection))

  def getCurveIntersectionApPointsWithPlane(self, valveModel, planePosition, planeNormal, sortDirectionVector):
    """Get two point intersections with the specified plane, ordered according to the direction vector
    :param valveModel:
    :param planePosition:
    :param planeNormal:
    :param sortDirectionVector: if vector points P->A direction then first points is P, second point is on A side
    :return: [posteriorPoint, anteriorPoint]
    """
    import math
    curveIntersectionPoints = valveModel.annulusContourCurve.getPointsOnPlane(planePosition, planeNormal)

    # TODO: handle cases when number of intersection points != 2
    # TODO: it would be more robust to sort based on sortDirectionVector position and pick first and last points
    if curveIntersectionPoints.shape[1] != 2:
      logging.warning("There are {} intersection points while exactly 2 points are expected.".format(curveIntersectionPoints.shape[1]))

    p1 = curveIntersectionPoints[:,0]
    p2 = curveIntersectionPoints[:,1]

    p1p2SameDirectionAsSortDirection = (vtk.vtkMath.AngleBetweenVectors(sortDirectionVector, p2-p1) < math.pi/2)
    return [p1, p2] if p1p2SameDirectionAsSortDirection else [p2, p1]

  def addLeafletSurfaceArea3D(self, valveModel, leafletSegmentId, measurementName):

    # Get leaflet surface
    leafletModel = valveModel.findLeafletModel(leafletSegmentId)
    if leafletModel is None:
      # empty segment
      return None, None
    leafletSurfaceModelNodeSource = leafletModel.surfaceModelNode
    if (leafletSurfaceModelNodeSource is None
        or leafletSurfaceModelNodeSource.GetPolyData() is None
        or leafletSurfaceModelNodeSource.GetPolyData().GetNumberOfPoints() == 0):
      logging.warning(f"No surface has been extracted for {leafletSegmentId}")
      return None, None
    leafletSurfacePolyData = vtk.vtkPolyData()
    leafletSurfacePolyData.DeepCopy(leafletSurfaceModelNodeSource.GetPolyData())
    leafletTransformNodeId = leafletSurfaceModelNodeSource.GetTransformNodeID()

    # Get leaflet color
    leafletSegmentationNode = valveModel.getLeafletSegmentationNode()
    segmentation = leafletSegmentationNode.GetSegmentation()
    color = segmentation.GetSegment(leafletSegmentId).GetColor()

    # Create a copy of the leaflet surface
    modelsLogic = slicer.modules.models.logic()
    leafletSurfaceModelNode = modelsLogic.AddModel(leafletSurfacePolyData)
    leafletSurfaceModelNode.SetName(measurementName)
    leafletSurfaceModelNode.GetDisplayNode().SetColor(color)
    leafletSurfaceModelNode.GetDisplayNode().SetVisibility(False)
    leafletSurfaceModelNode.GetDisplayNode().SetSliceIntersectionThickness(5)
    leafletSurfaceModelNode.GetDisplayNode().SetOpacity(0.6)
    leafletSurfaceModelNode.GetDisplayNode().SetAmbient(0.1)
    leafletSurfaceModelNode.GetDisplayNode().SetDiffuse(0.9)
    leafletSurfaceModelNode.GetDisplayNode().SetSpecular(0.1)
    leafletSurfaceModelNode.GetDisplayNode().SetPower(10)
    leafletSurfaceModelNode.GetDisplayNode().BackfaceCullingOff()
    # Place model into subject and transform hierarchy
    self.moveNodeToMeasurementFolder(leafletSurfaceModelNode)
    leafletSurfaceModelNode.SetAndObserveTransformNodeID(leafletTransformNodeId)

    # Compute and add measurement
    massProperties = vtk.vtkMassProperties()
    massProperties.SetInputData(leafletSurfaceModelNode.GetPolyData())
    leafletSurfaceArea3d = massProperties.GetSurfaceArea()
    self.addMeasurement({KEY_NAME: measurementName, KEY_VALUE: "{:.1f}".format(leafletSurfaceArea3d), KEY_UNIT: 'mm*mm'})
    return leafletSurfacePolyData, leafletSurfaceArea3d

  @staticmethod
  def createCurveModel(modelName, curvePoints, radius=0.25, color=None, tubeResolution=8, visibility=False):
    """
    Create a line model (line segment with spheres at the endpoints)
    :param modelName: Name of the created model node
    :param curvePoints: curve points
    :param radius: radius of the line tube
    :param color: color of the line
    :return: MRML model node
    """

    if color is None:
      color = [1.0, 1.0, 0]
    points = vtk.vtkPoints()
    lines = vtk.vtkCellArray()
    curvePoly = vtk.vtkPolyData()
    curvePoly.SetPoints(points)
    curvePoly.SetLines(lines)

    nInterpolatedPoints = curvePoints.shape[1]
    points.Allocate(nInterpolatedPoints)
    lines.InsertNextCell(nInterpolatedPoints)
    for i in range(nInterpolatedPoints):
      points.InsertNextPoint(curvePoints[:, i])
      lines.InsertCellPoint(i)

    tubeFilter = vtk.vtkTubeFilter()
    tubeFilter.SetInputData(curvePoly)
    tubeFilter.SetRadius(radius)
    tubeFilter.SetNumberOfSides(tubeResolution)
    tubeFilter.SetCapping(True)

    # Triangulation is necessary to avoid discontinuous lines
    # in model/slice intersection display
    triangles = vtk.vtkTriangleFilter()
    triangles.SetInputConnection(tubeFilter.GetOutputPort())
    triangles.Update()

    modelsLogic = slicer.modules.models.logic()
    modelNode = modelsLogic.AddModel(triangles.GetOutput())
    modelNode.SetName(modelName)
    modelNode.GetDisplayNode().SetVisibility(visibility)
    modelNode.GetDisplayNode().SetColor(color)

    return modelNode

  @staticmethod
  def createPlaneModel(modelName, planePosition, planeNormal, bounds, color=None, opacity=1.0, displayAsGrid=True,
                       visibility=False, nodeToBeAddedTo=None):
    """
    Create a plane model (thin slab)
    :param modelName: Name of the created model node
    :param planePosition:
    :param planeNormal:
    :param bounds: minX, maxX, minY, maxY, minZ, maxZ - in the plane's coordinate system
    :return: MRML model node
    """

    if color is None:
      color = [1.0, 0.0, 0.0]
    transformPlaneToWorld = HeartValveLib.getVtkTransformPlaneToWorld(planePosition, planeNormal)

    polyTransformToWorld = vtk.vtkTransformPolyDataFilter()
    polyTransformToWorld.SetTransform(transformPlaneToWorld)

    planeSource = vtk.vtkPlaneSource()
    planeSource.SetOrigin(bounds[0], bounds[2], (bounds[4] + bounds[5]) / 2)
    planeSource.SetPoint1(bounds[1], bounds[2], (bounds[4] + bounds[5]) / 2)
    planeSource.SetPoint2(bounds[0], bounds[3], (bounds[4] + bounds[5]) / 2)
    planeSource.SetXResolution(8)
    planeSource.SetYResolution(8)
    polyTransformToWorld.SetInputConnection(planeSource.GetOutputPort())

    if nodeToBeAddedTo:
      append = vtk.vtkAppendPolyData()
      append.AddInputConnection(nodeToBeAddedTo.GetPolyDataConnection())
      append.AddInputConnection(polyTransformToWorld.GetOutputPort())
      nodeToBeAddedTo.SetPolyDataConnection(append.GetOutputPort())
      modelNode = nodeToBeAddedTo
    else:
      modelsLogic = slicer.modules.models.logic()
      modelNode = modelsLogic.AddModel(polyTransformToWorld.GetOutputPort())
      modelNode.SetName(modelName)
      displayNode = modelNode.GetDisplayNode()
      displayNode.SetVisibility(visibility)
      displayNode.SetOpacity(opacity)
      displayNode.SetColor(color)
      if displayAsGrid:
        displayNode.SetRepresentation(slicer.vtkMRMLModelDisplayNode.WireframeRepresentation)
        displayNode.BackfaceCullingOff()
        displayNode.LightingOff()  # don't make the grid darker if it is rotated

    return modelNode

  @staticmethod
  def createPolyDataFromPolygon(pointPositions):
    """
    Create a polygon model (2D) with a tube around its circumference
    :param pointPositions: points defining the polygon, each row defines a point
    :param circumferenceLineRadius: radius of the tube drawn around the circumference, if 0 then no tube is drawn
    :param color: 0-1, 3 components
    :param opacity: 0-1
    :return: MRML model node
    """

    numberOfPoints = pointPositions.shape[0]

    # Polydata
    polygonPolyData = vtk.vtkPolyData()

    # Points
    points = vtk.vtkPoints()
    points.SetNumberOfPoints(numberOfPoints)
    for pointIndex in range(numberOfPoints):
      points.SetPoint(pointIndex, pointPositions[pointIndex])
    polygonPolyData.SetPoints(points)

    # Polygon cell
    polygon = vtk.vtkPolygon()
    polygonPointIds = polygon.GetPointIds()
    polygonPointIds.SetNumberOfIds(numberOfPoints + 1)  # +1 for the closing segment
    for pointIndex in range(numberOfPoints):
      polygonPointIds.SetId(pointIndex, pointIndex)
    polygonPointIds.SetId(numberOfPoints, 0)  # closing segment
    # Cells
    polygons = vtk.vtkCellArray()
    polygons.InsertNextCell(polygon)
    polygonPolyData.SetPolys(polygons)

    # Polygon may be non-convex, so we have to triangulate to allow correct rendering
    # and surface computation
    triangulator = vtk.vtkTriangleFilter()
    triangulator.SetInputData(polygonPolyData)
    triangulator.Update()

    return triangulator.GetOutput()

  @staticmethod
  def createLineModel(modelName, pos1, pos2, radius=0.25, color=None, visibility=False):
    """
    Create a line model (line segment with spheres at the endpoints)
    :param modelName: Name of the created model node
    :param pos1: position of point1
    :param pos2: position of point2
    :param radius: radius of the line tube
    :param color: color of the line
    :return: MRML model node
    """

    if color is None:
      color = [1.0, 1.0, 0]
    point1Source = vtk.vtkSphereSource()
    point1Source.SetCenter(pos1)
    point1Source.SetRadius(radius * 2)

    point2Source = vtk.vtkSphereSource()
    point2Source.SetCenter(pos2)
    point2Source.SetRadius(radius * 2)

    lineSource = vtk.vtkLineSource()
    lineSource.SetResolution(10)  # to make rendering of long lines look nicer
    lineSource.SetPoint1(pos1)
    lineSource.SetPoint2(pos2)

    tubeFilter = vtk.vtkTubeFilter()
    tubeFilter.SetInputConnection(lineSource.GetOutputPort())
    tubeFilter.SetNumberOfSides(8)  # improve rendering quality
    tubeFilter.SetRadius(radius)

    polyDataAppend = vtk.vtkAppendPolyData()
    point1Source.Update()
    polyDataAppend.AddInputData(point1Source.GetOutput())
    point2Source.Update()
    polyDataAppend.AddInputData(point2Source.GetOutput())
    tubeFilter.Update()
    polyDataAppend.AddInputData(tubeFilter.GetOutput())

    modelsLogic = slicer.modules.models.logic()
    polyDataAppend.Update()
    modelNode = modelsLogic.AddModel(polyDataAppend.GetOutput())
    modelNode.SetName(modelName)
    modelNode.GetDisplayNode().SetVisibility(visibility)
    modelNode.GetDisplayNode().SetColor(color)
    # modelNode.GetDisplayNode().LightingOff() # don't make the line edges darker
    return modelNode

  @staticmethod
  def createArrowModel(modelName, pos1, pos2, radius=0.25, color=None, visibility=False):
    """
    Create an arrow model from pos1 to pos2
    :param modelName: Name of the created model node
    :param pos1: position of point1
    :param pos2: position of point2
    :param radius: radius of the line tube
    :param color: color of the line
    :return: MRML model node
    """

    if color is None:
      color = [1.0, 1.0, 0]
    arrowSource = vtk.vtkArrowSource()
    arrowSource.SetShaftRadius(0.5)
    arrowSource.SetTipRadius(1.0)
    arrowSource.SetShaftResolution(16)
    arrowSource.SetTipResolution(16)

    transformPlaneToWorld = HeartValveLib.getVtkTransformPlaneToWorld(pos1, pos2 - pos1)
    transformPlaneToWorld.PreMultiply()
    transformPlaneToWorld.Scale(radius, radius, np.linalg.norm(pos2 - pos1))
    transformPlaneToWorld.RotateY(-90)
    polyTransformToWorld = vtk.vtkTransformPolyDataFilter()
    polyTransformToWorld.SetTransform(transformPlaneToWorld)
    polyTransformToWorld.SetInputConnection(arrowSource.GetOutputPort())

    modelsLogic = slicer.modules.models.logic()
    polyTransformToWorld.Update()
    modelNode = modelsLogic.AddModel(polyTransformToWorld.GetOutput())
    modelNode.SetName(modelName)
    modelNode.GetDisplayNode().SetVisibility(visibility)
    modelNode.GetDisplayNode().SetColor(color)
    # modelNode.GetDisplayNode().LightingOff() # don't make the line edges darker
    return modelNode

  def addSegmentVolumeMeasurement(self, measurementName, color, segmentationNode, segmentID):
    import vtkSegmentationCorePython as vtkSegmentationCore

    segmentLabelmap = getBinaryLabelmapRepresentation(segmentationNode, segmentID)

    # We need to know exactly the value of the segment voxels, apply threshold to make force the selected label value
    labelValue = 1
    backgroundValue = 0
    thresh = vtk.vtkImageThreshold()
    thresh.SetInputData(segmentLabelmap)
    thresh.ThresholdByLower(0)
    thresh.SetInValue(backgroundValue)
    thresh.SetOutValue(labelValue)
    thresh.SetOutputScalarType(vtk.VTK_UNSIGNED_CHAR)
    thresh.Update()

    #  Use binary labelmap as a stencil
    stencil = vtk.vtkImageToImageStencil()
    stencil.SetInputData(thresh.GetOutput())
    stencil.ThresholdByUpper(labelValue)
    stencil.Update()

    stat = vtk.vtkImageAccumulate()
    stat.SetInputData(thresh.GetOutput())
    stat.SetStencilData(stencil.GetOutput())
    stat.Update()

    # Add data to statistics list
    spacing = segmentLabelmap.GetSpacing()
    cubicMMPerVoxel = spacing[0] * spacing[1] * spacing[2]
    ccPerCubicMM = 0.001
    voxelCount = stat.GetVoxelCount()
    volumeMm3 = stat.GetVoxelCount() * cubicMMPerVoxel
    volumeCc = stat.GetVoxelCount() * cubicMMPerVoxel * ccPerCubicMM
    self.addMeasurement({KEY_NAME: measurementName, KEY_VALUE: "{:.1f}".format(volumeMm3), KEY_UNIT: 'mm*mm*mm'})

    # Create a model that shows the volume
    segmentationNode.CreateClosedSurfaceRepresentation()
    modelsLogic = slicer.modules.models.logic()
    modelMesh = vtk.vtkPolyData()
    segmentationNode.GetClosedSurfaceRepresentation(segmentID, modelMesh)
    volumeModelNode = modelsLogic.AddModel(modelMesh)
    volumeModelNode.SetName(measurementName)
    volumeModelNode.GetDisplayNode().SetColor(color)
    volumeModelNode.GetDisplayNode().SetVisibility(False)
    volumeModelNode.GetDisplayNode().SetSliceIntersectionThickness(5)
    volumeModelNode.GetDisplayNode().SetOpacity(1.0)
    volumeModelNode.GetDisplayNode().SetAmbient(0.1)
    volumeModelNode.GetDisplayNode().SetDiffuse(0.9)
    volumeModelNode.GetDisplayNode().SetSpecular(0.1)
    volumeModelNode.GetDisplayNode().SetPower(10)
    volumeModelNode.GetDisplayNode().BackfaceCullingOff()
    # Place model into subject and transform hierarchy
    self.moveNodeToMeasurementFolder(volumeModelNode)
    volumeModelNode.SetAndObserveTransformNodeID(segmentationNode.GetTransformNodeID())
    return volumeMm3

  def addVolumeMeasurementBetweenSurfaces(self, measurementName, color, valveModel, allLeafletSurfacePolyData, annulusAreaPolyData, extrusionDirection, extrusionLength, leafletRois):
    """
    Create a new segmentation node that will be used for performing Boolean operations and
    conversion to surface mesh.
    Discretization is needed for conversion to labelmap for Boolean operations
    Use the same reference geometry as the leaflet segmentation node, but with finer resolution - using oversampling.
    Oversampling by more than a factor of 3 only slightly changes the results (less than about 3%),
    but it would increase computation time a lot, therefore we choose 3.
    :param measurementName:
    :param color:
    :param valveModel:
    :param allLeafletSurfacePolyData:
    :param annulusAreaPolyData:
    :param extrusionDirection:
    :param extrusionLength:
    :param leafletRois: if specified then measurements will be reported for each ROI separately
    :return:
    """

    oversamplingFactor = 3
    segmentationNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', f"VolumeBetweenSurfaces-{measurementName}")
    segmentationNode.CreateDefaultDisplayNodes()
    segmentation = segmentationNode.GetSegmentation()
    # Set parent transform
    leafletSegmentationNode = valveModel.getLeafletSegmentationNode()
    segmentationNode.SetAndObserveTransformNodeID(leafletSegmentationNode.GetTransformNodeID())
    # Set reference image geometry
    referenceGeometryString = leafletSegmentationNode.GetSegmentation().GetConversionParameter(vtkSegmentationCore.vtkSegmentationConverter.GetReferenceImageGeometryParameterName())
    referenceGeometryImage = vtkSegmentationCore.vtkOrientedImageData()
    vtkSegmentationCore.vtkSegmentationConverter.DeserializeImageGeometry(referenceGeometryString, referenceGeometryImage)
    segmentation.SetConversionParameter(vtkSegmentationCore.vtkSegmentationConverter.GetReferenceImageGeometryParameterName(), referenceGeometryString)
    segmentation.SetConversionParameter(vtkSegmentationCore.vtkClosedSurfaceToBinaryLabelmapConversionRule.GetOversamplingFactorParameterName(), str(oversamplingFactor))
    # Crop models to labelmap (to save memory and make sure that at the far end both segments are cropped to the same size)
    cropToRefParamName = vtkSegmentationCore.vtkClosedSurfaceToBinaryLabelmapConversionRule.GetCropToReferenceImageGeometryParameterName()
    segmentation.SetConversionParameter(cropToRefParamName, "1")

    # Leaflet closed surface
    leafletSurfaceExtruder = vtk.vtkLinearExtrusionFilter()
    leafletSurfaceExtruder.SetInputDataObject(allLeafletSurfacePolyData)
    leafletSurfaceExtruder.SetScaleFactor(extrusionLength)
    leafletSurfaceExtruder.SetExtrusionTypeToVectorExtrusion()
    leafletSurfaceExtruder.SetVector(extrusionDirection)
    leafletSurfaceExtruder.Update()
    leafletClosedSurfaceSegmentId = segmentationNode.AddSegmentFromClosedSurfaceRepresentation(
      leafletSurfaceExtruder.GetOutput(), measurementName)

    # Soap bubble closed surface
    soapBubbleSurfaceExtruder = vtk.vtkLinearExtrusionFilter()
    soapBubbleSurfaceExtruder.SetInputDataObject(annulusAreaPolyData)
    soapBubbleSurfaceExtruder.SetScaleFactor(extrusionLength * 1.2)
    soapBubbleSurfaceExtruder.SetExtrusionTypeToVectorExtrusion()
    soapBubbleSurfaceExtruder.SetVector(extrusionDirection)
    soapBubbleSurfaceExtruder.Update()
    soapBubbleClosedSurfaceSegmentId = segmentationNode.AddSegmentFromClosedSurfaceRepresentation(
      soapBubbleSurfaceExtruder.GetOutput(), measurementName+" Soap bubble")

    leafletRoiSegmentIds = []
    for leafletRoi in leafletRois:
      # Leaflet ROI closed surface to get sub-volumes for each surface region
      leafletSegmentation = leafletRoi.valveModel.getLeafletSegmentationNode().GetSegmentation()
      segmentName = leafletSegmentation.GetSegment(leafletRoi.leafletSegmentId).GetName()
      leafletRoiSegmentId = segmentationNode.AddSegmentFromClosedSurfaceRepresentation(
        leafletRoi.roiModelNode.GetPolyData(), measurementName + " - " + segmentName)
      leafletRoiSegmentIds.append(leafletRoiSegmentId)

    segmentationNode.SetSourceRepresentationToBinaryLabelmap()
    segmentationNode.RemoveClosedSurfaceRepresentation()

    # Subtract extruded soap bubble from extruded leaflet surface
    modifierSegmentLabelmap = getBinaryLabelmapRepresentation(segmentationNode, soapBubbleClosedSurfaceSegmentId)

    fillValue = 1
    eraseValue = 0
    inverter = vtk.vtkImageThreshold()
    inverter.SetInputData(modifierSegmentLabelmap)
    inverter.SetInValue(fillValue)
    inverter.SetOutValue(eraseValue)
    inverter.ReplaceInOn()
    inverter.ThresholdByLower(0)
    inverter.SetOutputScalarType(vtk.VTK_UNSIGNED_CHAR)
    inverter.Update()

    invertedModifierSegmentLabelmap = vtkSegmentationCore.vtkOrientedImageData()
    invertedModifierSegmentLabelmap.ShallowCopy(inverter.GetOutput())
    imageToWorldMatrix = vtk.vtkMatrix4x4()
    modifierSegmentLabelmap.GetImageToWorldMatrix(imageToWorldMatrix)
    invertedModifierSegmentLabelmap.SetGeometryFromImageToWorldMatrix(imageToWorldMatrix)

    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(invertedModifierSegmentLabelmap,
      segmentationNode, leafletClosedSurfaceSegmentId, slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MIN)

    # Remove soap bubble segment to not spend time with surface updates
    segmentationNode.RemoveSegment(soapBubbleClosedSurfaceSegmentId)

    # Smooth the segment to reduce jaggedness of the generated surface. It reduces volume by about 1-2%.
    valveModel.smoothSegment(segmentationNode, leafletClosedSurfaceSegmentId, kernelSizePixel=[3,3,3], method='median')
    self.addSegmentVolumeMeasurement(measurementName, color, segmentationNode, leafletClosedSurfaceSegmentId)

    for leafletRoiSegmentId in leafletRoiSegmentIds:
      leafletSegmentLabelmap = getBinaryLabelmapRepresentation(segmentationNode, leafletClosedSurfaceSegmentId)
      leafletRoiLabelmap = getBinaryLabelmapRepresentation(segmentationNode, leafletRoiSegmentId)

      roiExtent = leafletRoiLabelmap.GetExtent()
      leafletExtent = leafletSegmentLabelmap.GetExtent()
      commonExtent = [0, -1, 0, -1, 0, -1]
      for axis in range(3):
        commonExtent[axis * 2] = min(roiExtent[axis * 2], leafletExtent[axis * 2])
        commonExtent[axis * 2 + 1] = max(roiExtent[axis * 2 + 1], leafletExtent[axis * 2 + 1])

      padder = vtk.vtkImageConstantPad()
      padder.SetInputData(leafletSegmentLabelmap)
      padder.SetConstant(0)
      padder.SetOutputWholeExtent(commonExtent)
      padder.Update()
      leafletSegmentLabelmap.DeepCopy(padder.GetOutput())

      slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(leafletSegmentLabelmap,
        segmentationNode, leafletRoiSegmentId, slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MIN)

      leafletName = segmentation.GetSegment(leafletRoiSegmentId).GetName()
      self.addSegmentVolumeMeasurement(leafletName, color, segmentationNode, leafletRoiSegmentId)

    # Delete temporary segmentation
    slicer.mrmlScene.RemoveNode(segmentationNode)

  @staticmethod
  def getSignedDistance(basePolyData, coloringPolyData, extrusionDirection, extrusionLength):
    """
    Computes 'Distance' scalar on basePolyData that contains distance from coloringPolyData.
    Distance is positive if points towards extrusionDirection.
    """
    # Soap bubble closed surface
    coloringSurfaceExtruder = vtk.vtkLinearExtrusionFilter()
    coloringSurfaceExtruder.SetInputDataObject(coloringPolyData)
    coloringSurfaceExtruder.SetScaleFactor(-extrusionLength)
    coloringSurfaceExtruder.SetExtrusionTypeToVectorExtrusion()
    coloringSurfaceExtruder.SetVector(extrusionDirection)
    #coloringSurfaceExtruder.Update()

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(coloringSurfaceExtruder.GetOutputPort())
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()

    distanceFilter = vtk.vtkDistancePolyDataFilter()
    distanceFilter.SetInputData(0, basePolyData)
    distanceFilter.SetInputConnection(1, normals.GetOutputPort())
    distanceFilter.Update()

    return distanceFilter.GetOutput()

  def addModelColoredBySignedDistance(self, measurementName, valveModel, allLeafletSurfacePolyDataWithDistance):

    modelsLogic = slicer.modules.models.logic()
    modelNode = modelsLogic.AddModel(allLeafletSurfacePolyDataWithDistance)
    modelNode.SetName(measurementName)
    modelNode.GetDisplayNode().SetColor(valveModel.getBaseColor())
    modelNode.GetDisplayNode().SetVisibility(False)
    modelNode.GetDisplayNode().SetSliceIntersectionThickness(5)
    modelNode.GetDisplayNode().SetOpacity(1.0)
    modelNode.GetDisplayNode().SetAmbient(0.1)
    modelNode.GetDisplayNode().SetDiffuse(0.9)
    modelNode.GetDisplayNode().SetSpecular(0.1)
    modelNode.GetDisplayNode().SetPower(10)
    modelNode.GetDisplayNode().BackfaceCullingOff()

    modelNode.GetDisplayNode().SetActiveScalarName('Distance')

    useCustomColorNode = True
    modelDisplayNode = modelNode.GetDisplayNode()
    if useCustomColorNode:

      # Get custom color node
      signedDistanceColorSingletonTag = "ValveQuantificationSignedDistanceColor"
      signedDistanceColorNode = \
        slicer.mrmlScene.GetSingletonNode(signedDistanceColorSingletonTag, "vtkMRMLProceduralColorNode")
      if signedDistanceColorNode is None:
        n = slicer.mrmlScene.CreateNodeByClass("vtkMRMLProceduralColorNode")
        n.UnRegister(None)
        n.SetName(slicer.mrmlScene.GenerateUniqueName("Signed distance (mm)"))
        n.SetAttribute("Category", "ValveQuantification")
        # The color node is a procedural color node, which is saved using a storage node.
        # Hidden nodes are not saved if they use a storage node, therefore
        # the color node must be visible.
        n.SetHideFromEditors(False)
        n.SetSingletonTag(signedDistanceColorSingletonTag)
        # Create colormap
        colorMap = n.GetColorTransferFunction()
        colorMap.RemoveAllPoints()
        colorMap.AddRGBPoint(-10.0, 1.0, 0.0, 0.0)
        colorMap.AddRGBPoint(-0.5, 1.0, 0.0, 0.0)
        colorMap.AddRGBPoint(0.0, 0.8, 0.8, 0.8)
        colorMap.AddRGBPoint(0.5, 0.0, 0.0, 1.0)
        colorMap.AddRGBPoint(10.0, 0.0, 0.0, 1.0)
        n.SetNumberOfTableValues(1024)
        signedDistanceColorNode = slicer.mrmlScene.AddNode(n)

      modelDisplayNode.SetAndObserveColorNodeID(signedDistanceColorNode.GetID())
      modelDisplayNode.AutoScalarRangeOff()
      modelDisplayNode.SetScalarRangeFlag(modelDisplayNode.UseColorNodeScalarRange)
      #modelDisplayNode.SetScalarRange(0, 10.0)

    else:
      # Use some default existing color node
      modelDisplayNode.SetAndObserveColorNodeID('vtkMRMLFreeSurferProceduralColorNodeBlueRed')
      # modelDisplayNode.AutoScalarRangeOn()
      modelDisplayNode.SetScalarRangeFlag(slicer.vtkMRMLDisplayNode.UseColorNodeScalarRange)

    modelNode.GetDisplayNode().ScalarVisibilityOn()

    # Place model into subject and transform hierarchy
    self.moveNodeToMeasurementFolder(modelNode)
    leafletSegmentationNode = valveModel.getLeafletSegmentationNode()
    modelNode.SetAndObserveTransformNodeID(leafletSegmentationNode.GetTransformNodeID())

  def addMaximumSurfaceDistanceMeasurement(self, valveModel, maxDistanceName, minDistanceName, basePolyData, coloringPolyData):

    # Remove points that do not belong to cells
    basePolyDataCleaner = vtk.vtkCleanPolyData()
    basePolyDataCleaner.SetInputData(basePolyData)
    basePolyDataCleaner.Update()
    basePolyDataClean = basePolyDataCleaner.GetOutput()

    # signed distance values
    distanceValues = VN.vtk_to_numpy(basePolyDataClean.GetPointData().GetArray('Distance'))
    measurementNames = [minDistanceName, maxDistanceName]
    basePointIndex = [np.argmin(distanceValues), np.argmax(distanceValues)]

    closestPointFinder = vtk.vtkImplicitPolyDataDistance()
    closestPointFinder.SetInput(coloringPolyData)

    for measurementIndex in range(2):
      point1Pos = basePolyDataClean.GetPoints().GetPoint(basePointIndex[measurementIndex])
      point2Pos= [0,0,0]
      closestPointDistance = closestPointFinder.EvaluateFunctionAndGetClosestPoint(point1Pos, point2Pos)
      self.addMeasurement(self.getDistanceBetweenPoints(valveModel, "", valveModel, "",
        measurementNames[measurementIndex], point1Pos, point2Pos))

  def addSegmentedLeafletMeasurements(self, valveModel, planePosition, planeNormal):
    """
    Add leaflet measurements for all leaflets
    :param valveModel:
    :param planePosition: center of the valve, used for tilting the leaflet extraction surface normal
    :param planeNormal:
    :return:
    """

    leafletSegmentationNode = valveModel.getLeafletSegmentationNode()
    if not leafletSegmentationNode:
      return

    # Create soap bubble surface

    annulusPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    annulusAreaPolyData = self.createSoapBubblePolyDataFromCircumferencePoints(annulusPoints, 1.2)

    # Create fused leaflet surface
    leafletSegmentationNode = valveModel.getLeafletSegmentationNode()
    segmentation = leafletSegmentationNode.GetSegmentation()
    allLeafletThickness = []
    leafletSurfaces = []
    for leafletModel in valveModel.leafletModels:
      segmentId = leafletModel.segmentId
      segment = segmentation.GetSegment(segmentId)

      leafletVolume = self.addSegmentVolumeMeasurement("Leaflet volume - {0}".format(segment.GetName()),
                                                       segment.GetColor(), leafletSegmentationNode,
                                                       segmentId)
      try:
        leafletSurfacePolyData, leafletSurfaceArea = self.addLeafletSurfaceArea3D(valveModel, segmentId,
                                                            "Leaflet area - {0} (3D)".format(segment.GetName()))
        if leafletSurfaceArea is not None:
          # NB: estimating leaflet thickness by dividing volume by surface area
          allLeafletThickness.append(leafletVolume/leafletSurfaceArea)
          self.addMeasurement({KEY_NAME: "Leaflet thickness estimate - {0}".format(segment.GetName()),
                               KEY_VALUE: "{:.1f}".format(allLeafletThickness[-1]), KEY_UNIT: 'mm'})

        # NB: necessary for calculating partial atrial surface
        if leafletSurfacePolyData is not None:
          leafletSurfaces.append( leafletSurfacePolyData )
      except TypeError as exc:
        logging.warning("Leaflet ({}) thickness computation failed: {}".format(segment.GetName(), str(exc)))
        import traceback
        traceback.print_exc()

    if allLeafletThickness:
      self.addMeasurement({KEY_NAME: "Leaflet thickness estimate - all",
                           KEY_VALUE: "{:.1f}".format(np.array(allLeafletThickness).mean()),
                           KEY_UNIT: 'mm'})

    valveSurfacePolydata = mergePolydata(*leafletSurfaces)
    try:
      # Smooth PolyData
      # NB: using a bigger annulus area, so it can better fit/wrap to the valve surface
      annulusAreaPolyDataBigger = self.createSoapBubblePolyDataFromCircumferencePoints(annulusPoints, 5.0)

      # Max height of leaflets. Leaflets should not be higher/lower than this value compared to the annulus.
      maxLeafletDepthMm = 60

      # NB: get largest distance in atrial direction and translate 3d annulus plane there to drop the blanket
      allLeafletSurfacePolyDataWithDistance = \
        self.getSignedDistance(valveSurfacePolydata, annulusAreaPolyData, -planeNormal, maxLeafletDepthMm)

      distances = \
        vtk.util.numpy_support.vtk_to_numpy(
          allLeafletSurfacePolyDataWithDistance.GetCellData().GetArray("Distance")
        )

      annulusAreaPolyDataBigger = translatePolyData(annulusAreaPolyDataBigger, -planeNormal, max(distances) * 1.2)

      allLeafletSurfacePolyData = \
        extractValveSurfaceWithSmoothPolyDataFilter(annulusAreaPolyDataBigger, leafletSurfaces, iterations=3,
                                                    nVertices=5000, subdivide=2, smoothIterations=100,
                                                    relaxationFactor=0.7)

      if allLeafletSurfacePolyData:
        self.addBillowTentingAndAtrialSurface(allLeafletSurfacePolyData, annulusAreaPolyData, leafletSurfaces,
                                              valveModel,
                                              planeNormal)  # , strategy="(SmoothPolydata)")

      # NB: Morphological_Closing

      # kernelSizeMm = 2.0
      # allLeafletSurfacePolyData = extractValveSurfaceUsingMorphologicalClosing(valveModel, planePosition,
      #                                                                          planeNormal, kernelSizeMm,
      #                                                                          maxKernelSizeMm=3.0)
      #
      # if allLeafletSurfacePolyData:
      #   self.addBillowTentingAndAtrialSurface(allLeafletSurfacePolyData, annulusAreaPolyData, leafletSurfaces,
      #                                         valveModel,
      #                                         planeNormal) #, strategy="(Morphological_Closing)")

      # NB: Wrap Solidify
      # allLeafletSurfacePolyData = extractValveSurfaceWithWrapSolidify(planeNormal, planePosition, valveModel,
      #                                                                 annulusAreaPolyData, kernelSizeMm)
      #
      # if allLeafletSurfacePolyData:
      #   self.addBillowTentingAndAtrialSurface(allLeafletSurfacePolyData, annulusAreaPolyData, leafletSurfaces,
      #                                         valveModel,
      #                                         planeNormal, strategy="(Wrap Solidify)")

    except AttributeError:
      self.addMessage("Valve Surface not extracted")

  def addBillowTentingAndAtrialSurface(self, allLeafletSurfacePolyData, annulusAreaPolyData, leafletSurfaces,
                                       valveModel, planeNormal, strategy=''):
    if not allLeafletSurfacePolyData:
      logging.warning(f'Could not extract valve surface from {valveModel.heartValveNode.GetName()} using {strategy}')
      return

    # Max height of leaflets. Leaflets should not be higher/lower than this value compared to the annulus.
    maxLeafletDepthMm = 60
    allLeafletSurfacePolyDataWithDistance = \
      self.getSignedDistance(allLeafletSurfacePolyData, annulusAreaPolyData, planeNormal, maxLeafletDepthMm)
    # Add colored model of fused leaflet surface
    self.addModelColoredBySignedDistance(f'Leaflet area (atrial) - all (3D){strategy}', valveModel,
                                         allLeafletSurfacePolyDataWithDistance)
    self.addMaximumSurfaceDistanceMeasurement(valveModel, f"Tenting height{strategy}", f"Billow height{strategy}",
                                              allLeafletSurfacePolyDataWithDistance, annulusAreaPolyData)
    # Add leaflet surface area to measurement list
    # TODO: often the circumference is a bit warped/curved, which increases the surface a bit.
    # It would be nice to straighten the circumference.
    # Examples: L82_NM-F9-final.mrb, L76_NM-F41-final.mrb
    massProperties = vtk.vtkMassProperties()
    massProperties.SetInputData(allLeafletSurfacePolyData)
    leafletSurfaceArea3d = massProperties.GetSurfaceArea()
    self.addMeasurement({KEY_NAME: f'Leaflet area (atrial) - all (3D){strategy}',
                         KEY_VALUE: "{:.1f}".format(leafletSurfaceArea3d),
                         KEY_UNIT: 'mm*mm'})
    if leafletSurfaces:
      self.addLeafletAtrialSurfaceMeasurements(valveModel, allLeafletSurfacePolyData, leafletSurfaces, strategy)
    # Get leaflet projections on the valve plane normal so that we can split the volume measurements per leaflet
    leafletRois = []
    for leafletModel in valveModel.leafletModels:
      segmentId = leafletModel.segmentId

      from HeartValveLib import ValveRoi
      leafletRoi = ValveRoi()
      modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")
      modelNode.CreateDefaultDisplayNodes()
      modelNode.GetDisplayNode().SetBackfaceCulling(0)
      modelNode.SetAndObserveTransformNodeID(valveModel.getLeafletSegmentationNode().GetTransformNodeID())
      leafletRoi.setRoiModelNode(modelNode)
      # Straight cylindrical cutting surface
      roiParams = {
        ValveRoi.PARAM_SCALE: 100.0,
        ValveRoi.PARAM_TOP_SCALE: 100.0,
        ValveRoi.PARAM_BOTTOM_SCALE: 100.0,
        ValveRoi.PARAM_TOP_DISTANCE: 30.0,
        ValveRoi.PARAM_BOTTOM_DISTANCE: 30.0
      }
      leafletRoi.setRoiGeometry(roiParams)
      leafletRoi.setLeaflet(valveModel, segmentId)
      if leafletRoi.roiModelNode.GetPolyData().GetNumberOfPoints() > 0:
        leafletRois.append(leafletRoi)
      else:
        # Coaptation lines are not found
        slicer.mrmlScene.RemoveNode(leafletRoi.roiModelNode)
    self.addVolumeMeasurementBetweenSurfaces(f"Billow volume{strategy}", [1.0, 0.2, 0.2], valveModel, allLeafletSurfacePolyData,
                                             annulusAreaPolyData, planeNormal, maxLeafletDepthMm, leafletRois)
    self.addVolumeMeasurementBetweenSurfaces(f"Tenting volume{strategy}", [0.2, 0.2, 1.0], valveModel, allLeafletSurfacePolyData,
                                             annulusAreaPolyData, planeNormal, -maxLeafletDepthMm, leafletRois)
    for leafletRoi in leafletRois:
      slicer.mrmlScene.RemoveNode(leafletRoi.roiModelNode)

  def addLeafletAtrialSurfaceMeasurements(self, valveModel, allLeafletSurfacePolyData, leafletSurfaces, strategy=''):
    # calculate all cell center distances from atrial valve surface to individual leaflets
    vtkCenters = vtk.vtkCellCenters()
    vtkCenters.SetInputData(allLeafletSurfacePolyData)
    vtkCenters.VertexCellsOn()
    vtkCenters.Update()

    atrialSurfaceCellCenters = vtkCenters.GetOutput()
    dist = vtk.vtkDistancePolyDataFilter()
    dist.SetInputData(0, atrialSurfaceCellCenters)

    distances = []
    for leafletSurface in leafletSurfaces:
      dist.SetInputData(1, leafletSurface)
      dist.Update()
      distances.append(VN.vtk_to_numpy(dist.GetOutput().GetPointData().GetScalars()))

    # prepare for label assignment
    distances = np.abs(np.column_stack(distances))
    assigned_labels = np.argmin(distances, axis=1)

    # add new array to atrial surface with assigned leaflets
    arrayName = "Closest_Leaflet"
    label = vtk.vtkIntArray()
    label.SetName(arrayName)
    label.SetNumberOfComponents(1)
    for lblIdx in assigned_labels:
      label.InsertNextTuple1(lblIdx)
    allLeafletSurfacePolyData.GetCellData().AddArray(label)

    leafletSegmentationNode = valveModel.getLeafletSegmentationNode()
    segmentation = leafletSegmentationNode.GetSegmentation()

    for idx, leafletModel in enumerate(valveModel.leafletModels):
      segmentId = leafletModel.segmentId
      segment = segmentation.GetSegment(segmentId)
      metricName = f'Leaflet area (atrial) - {segment.GetName()} (3D){strategy}'

      allLeafletSurfacePolyData.GetPointData().SetActiveScalars(arrayName)

      threshold = vtk.vtkThreshold()
      threshold.SetInputData(allLeafletSurfacePolyData)
      threshold.SetLowerThreshold(idx)
      threshold.SetUpperThreshold(idx)
      threshold.SetThresholdFunction(vtk.vtkThreshold.THRESHOLD_BETWEEN)
      threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS, arrayName)
      threshold.Update()

      geometryFilter = vtk.vtkGeometryFilter()
      geometryFilter.SetInputData(threshold.GetOutput())
      geometryFilter.Update()
      leafletSurface = geometryFilter.GetOutput()

      modelsLogic = slicer.modules.models.logic()
      modelNode = modelsLogic.AddModel(leafletSurface)
      modelNode.GetDisplayNode().SetVisibility(False)
      modelNode.GetDisplayNode().SetSliceIntersectionThickness(5)
      modelNode.GetDisplayNode().SetColor(leafletModel.getLeafletColor())
      modelNode.GetDisplayNode().SetOpacity(0.6)
      modelNode.GetDisplayNode().SetAmbient(0.1)
      modelNode.GetDisplayNode().SetDiffuse(0.9)
      modelNode.GetDisplayNode().SetSpecular(0.1)
      modelNode.GetDisplayNode().SetPower(10)
      modelNode.GetDisplayNode().BackfaceCullingOff()
      modelNode.SetName(metricName)

      valveModel.applyProbeToRasTransformToNode(modelNode)
      self.moveNodeToMeasurementFolder(modelNode)

      massProperties = vtk.vtkMassProperties()
      massProperties.SetInputData(leafletSurface)
      leafletSurfaceArea3d = massProperties.GetSurfaceArea()
      self.addMeasurement({KEY_NAME: metricName,
                           KEY_VALUE: "{:.1f}".format(leafletSurfaceArea3d),
                           KEY_UNIT: 'mm*mm'})


def extractValveSurfaceUsingMorphologicalClosing(valveModel, planePosition, planeNormal, kernelSizeMm, maxKernelSizeMm):
  allLeafletSurfacePolyData = valveModel.createValveSurface(planePosition, planeNormal, kernelSizeMm)
  if not allLeafletSurfacePolyData:  # enable z smoothing
    logging.warning(f'Could not extract valve surface from {valveModel.heartValveNode.GetName()} with kernel size {kernelSizeMm}')
    while allLeafletSurfacePolyData is None and kernelSizeMm < maxKernelSizeMm:
      kernelSizeMm += 0.5
      logging.warning(f'Retrying with kernel size {kernelSizeMm}.')
      allLeafletSurfacePolyData = valveModel.createValveSurface(
        planePosition, planeNormal, kernelSizeMm,
        mergeMode=slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MASK,
        smoothInZDirection=True
      )
  return allLeafletSurfacePolyData


def extractValveSurfaceWithSmoothPolyDataFilter(annulusAreaPolyData, leafletSurfaces, iterations=4, nVertices=10000,
                                                subdivide=2, smoothIterations=50, relaxationFactor=1.0):
  if not leafletSurfaces:
    return None

  valveSurfacePolydata = mergePolydata(*leafletSurfaces)

  remeshed = annulusAreaPolyData
  for i in range(iterations):
    remeshed = smoothPolyData(remeshPolyData(remeshed, nVertices, subdivide), valveSurfacePolydata, smoothIterations, relaxationFactor)
    remeshed = windowSincPolyData(remeshed)
  remeshed = smoothPolyData(remeshPolyData(remeshed, nVertices, subdivide), valveSurfacePolydata, smoothIterations, relaxationFactor)
  remeshed = windowSincPolyData(remeshed, passband=0.1)
  return remeshed


def extractValveSurfaceWithWrapSolidify(planeNormal, planePosition, valveModel, annulusAreaPolyData, kernelSizeMm):
  logging.warning(f'Running Wrap Solidify')

  class SegmentEditorWidget(object):
    """ Create segment editor to get access to effects

    Usage:
        ```
          with SegmentEditorWidget() as segmentEditorWidget:
            ... # Do something
        ```
    """

    def __init__(self):
      self.segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
      self.segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
      self.segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
      self.segmentEditorNode.SetOverwriteMode(self.segmentEditorNode.OverwriteNone)
      self.segmentEditorWidget.setMRMLSegmentEditorNode(self.segmentEditorNode)

    def __enter__(self):
      return self.segmentEditorWidget

    def __exit__(self, exc_type, exc_value, tb):
      if exc_type is not None:
        import traceback
        traceback.print_exception(exc_type, exc_value, tb)
      self.segmentEditorWidget = None
      slicer.mrmlScene.RemoveNode(self.segmentEditorNode)
      return True

  with SegmentEditorWidget() as segmentEditorWidget:
    segmentEditorWidget.setActiveEffectByName('Wrap Solidify')
    if segmentEditorWidget.activeEffect() is None:
      raise ImportError("Wrap Solidify extension needs to be installed.")

  segmentationNode = valveModel.getLeafletSegmentationNode()

  def getAllSegmentIDs(segNode):
    segmentIDs = vtk.vtkStringArray()
    segNode.GetSegmentation().GetSegmentIDs(segmentIDs)
    return [segmentIDs.GetValue(idx) for idx in range(segmentIDs.GetNumberOfValues())]

  def smooth(segID, method):
    segmentEditorWidget.setCurrentSegmentID(segID)
    segmentEditorWidget.setActiveEffectByName("Smoothing")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("SmoothingMethod", method)
    effect.setParameter("KernelSizeMm", 1.0)
    effect.self().onApply()

  def subtract(segId, subtrahendSegId):
    segmentEditorWidget.setCurrentSegmentID(segId)
    segmentEditorWidget.setActiveEffectByName('Logical operators')
    subtractEffect = segmentEditorWidget.activeEffect()
    subtractEffect.setParameter("Operation", "SUBTRACT")
    subtractEffect.setParameter("ModifierSegmentID", subtrahendSegId)
    subtractEffect.self().onApply()

  def removeIslands(segId, minimumSize=200):
    segmentEditorWidget.setCurrentSegmentID(segId)
    segmentEditorWidget.setActiveEffectByName("Islands")
    islandsEffect = segmentEditorWidget.activeEffect()
    islandsEffect.setParameter("MinimumSize", minimumSize)
    islandsEffect.self().onApply()

  def clone(segId):
    newSegId = segmentationNode.GetSegmentation().AddEmptySegment()
    labelmap = getBinaryLabelmapRepresentation(segmentationNode, segId)
    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(
      labelmap, segmentationNode, newSegId,
      slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MASK
    )
    return newSegId

  mergedLeafletsSegId = segmentationNode.GetSegmentation().AddEmptySegment()
  for leafletModel in valveModel.leafletModels:
    leafletSegmentLabelmap = getBinaryLabelmapRepresentation(segmentationNode, leafletModel.segmentId)
    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(
      leafletSegmentLabelmap, segmentationNode, mergedLeafletsSegId,
      slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MASK
    )

  # TODO: problematic for valves with a lot of billow
  extruder = vtk.vtkLinearExtrusionFilter()
  extruder.SetInputData(annulusAreaPolyData)
  extruder.SetExtrusionTypeToVectorExtrusion()
  extruder.SetVector(planeNormal)
  extruder.SetScaleFactor(-2)
  extruder.Update()

  extrudedAnnulusPlaneSegmentId = \
    segmentationNode.AddSegmentFromClosedSurfaceRepresentation(extruder.GetOutput(), "extruded annulus plane")
  mergedLeafletsCappedSegId = segmentationNode.GetSegmentation().AddEmptySegment()
  for segId in [mergedLeafletsSegId, extrudedAnnulusPlaneSegmentId]:
    leafletSegmentLabelmap = getBinaryLabelmapRepresentation(segmentationNode, segId)
    slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(
      leafletSegmentLabelmap, segmentationNode, mergedLeafletsCappedSegId,
      slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MASK
    )

  toDelete = [extrudedAnnulusPlaneSegmentId, mergedLeafletsCappedSegId]  # mergedLeafletsSegId,
  # See all attributes: print(slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentEditorNode"))
  with SegmentEditorWidget() as segmentEditorWidget:
    segmentEditorWidget.setSegmentationNode(segmentationNode)
    segmentEditorWidget.setMasterVolumeNode(valveModel.getLeafletVolumeNode())

    smooth(mergedLeafletsCappedSegId, "MORPHOLOGICAL_CLOSING")

    # wrap solidify
    segmentEditorWidget.setActiveEffectByName('Wrap Solidify')
    wrapSolidifyEffect = segmentEditorWidget.activeEffect()
    wrapSolidifyEffect.setParameter("region", "outerSurface")
    wrapSolidifyEffect.setParameter("smoothingFactor", 0.0)
    wrapSolidifyEffect.setParameter("remeshOversampling", 3.0)
    wrapSolidifyEffect.setParameter("shrinkwrapIterations", 5)
    wrapSolidifyEffect.setParameter("outputType", "newSegment")
    wrapSolidifyEffect.self().onApply()
    solidifiedSegId = getAllSegmentIDs(segmentationNode)[-1]
    toDelete.append(solidifiedSegId)

    subtract(solidifiedSegId, mergedLeafletsCappedSegId)
    # smooth(solidifiedSegId, "MEDIAN")
    removeIslands(solidifiedSegId)

    shellSegId = clone(solidifiedSegId)
    toDelete.append(shellSegId)

    # hollow
    segmentEditorWidget.setCurrentSegmentID(shellSegId)
    segmentEditorWidget.setActiveEffectByName("Hollow")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("ShellMode", "INSIDE_SURFACE")
    effect.setParameter("ShellThicknessMm", 1.0)
    effect.self().onApply()

    # hole itself
    holeSegId = clone(shellSegId)
    toDelete.append(holeSegId)

    subtract(holeSegId, solidifiedSegId)
    subtract(holeSegId, mergedLeafletsCappedSegId)
    removeIslands(holeSegId)

    allLeafletSurfacePolyData = valveModel.createValveSurface(
      planePosition, planeNormal, kernelSizeMm,
      mergeMode=slicer.vtkSlicerSegmentationsModuleLogic.MODE_MERGE_MASK,
      segmentIds=[mergedLeafletsSegId, holeSegId],
      smoothInZDirection=True
    )
  for segID in toDelete:
    segmentationNode.RemoveSegment(segID)
  return allLeafletSurfacePolyData