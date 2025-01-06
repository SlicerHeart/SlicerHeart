import slicer
import vtk
from abc import abstractmethod
from ValveQuantificationLib.MeasurementPreset import *


class MeasurementPresetPapillary(MeasurementPreset):

  QUANTIFICATION_RESULTS_IDENTIFIER = "Papillary measurement results"

  def __init__(self):
    super(MeasurementPresetPapillary, self).__init__()
    self._valveModel = None
    self._valveCenterLabel = None
    self._requiredValveType = None

  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetPapillary, self).computeMetrics(inputValveModels, outputTableNode)
    try:
      self._valveModel = inputValveModels[self._requiredValveType]
      self._valveModel.updatePapillaryModels()
      for papillaryModel in self._getPapillaryMuscles():
        self._quantifyMuscleLength(papillaryModel)
        self._quantifyChordalLength(papillaryModel)
        self._quantifyAnnularMuscleAngle(papillaryModel)
    except KeyError:
      self.metricsMessages.append("Selection of {} is required".format(self.inputValveNames[self._requiredValveType]))
    return self.metricsMessages

  def _getPapillaryMuscles(self):
    papillaryModels = []
    for papillaryModel in self._valveModel.papillaryModels:
      if not papillaryModel.hasMusclePointsPlaced():
        self.metricsMessages.append("Warning: PM `{}` doesn't have enough points placed".format(papillaryModel.getName()))
        continue
      papillaryModels.append(papillaryModel)
    return papillaryModels

  def _quantifyMuscleLength(self, papillaryModel):
    muscleLength = papillaryModel.getMuscleLength()
    if muscleLength is None:
      return
    self.addMeasurement({
      KEY_NAME: '{} muscle length'.format(papillaryModel.getName()),
      KEY_VALUE: '%3.1f' % muscleLength,
      KEY_UNIT: 'mm'
    })

  def _quantifyChordalLength(self, papillaryModel):
    chordLength = papillaryModel.getMuscleChordLength()
    if chordLength is None:
      return
    self.addMeasurement({
      KEY_NAME: '{} chordal length'.format(papillaryModel.getName()),
      KEY_VALUE: '%3.1f' % chordLength,
      KEY_UNIT: 'mm'
    })

  def _quantifyAnnularMuscleAngle(self, papillaryModel):
    papillaryMuscleName = papillaryModel.getName()
    [_, annulusPlaneNormal] = self._valveModel.getAnnulusContourPlane()
    muscleAngles = {
      '{} muscle angle (tip-chord to annulus-plane)'.format(papillaryMuscleName):
        papillaryModel.getTipChordMuscleAngleDeg(annulusPlaneNormal),
      '{} muscle angle (base-chord to annulus-plane)'.format(papillaryMuscleName):
        papillaryModel.getBaseChordMuscleAngleDeg(annulusPlaneNormal)
    }
    for name, muscleAngleDeg in muscleAngles.items():
      if muscleAngleDeg is not None:
        self.addMeasurement({
          KEY_NAME: name,
          KEY_VALUE: '%3.1f' % muscleAngleDeg,
          KEY_UNIT: 'deg'
        })

  def _getItemDataNodeByName(self, name):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    shItem = shNode.GetItemChildWithName(shNode.GetItemByDataNode(self.folderNode), name, True)
    return shNode.GetItemDataNode(shItem) if shItem else None


class MeasurementPresetPapillaryAngle(MeasurementPresetPapillary):

  @staticmethod
  def cloneSubjectHierarchyItem(item, name):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    itemIDToClone = shNode.GetItemByDataNode(item)
    clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(shNode, itemIDToClone)
    clonedItem = shNode.GetItemDataNode(clonedItemID)
    clonedItem.SetName(name)
    return clonedItem

  @staticmethod
  def getPointProjectedToAnnularPlane(valveModel, point):
    annulusPlanePosition, annulusPlaneNormal = valveModel.getAnnulusContourPlane()
    point2D = np.zeros([3, 1])
    point2D[:, 0] = np.array(point)
    pointsArrayProjected_World, _, _ = \
      HeartValveLib.getPointsProjectedToPlane(point2D, annulusPlanePosition, annulusPlaneNormal)
    return pointsArrayProjected_World[:, 0]

  @classmethod
  def getPlaneProjectedPoint(cls, plane, point):
    planeNormal, planePosition = cls.getPlaneNormalAndPosition(plane)
    vtkPlane = vtk.vtkPlane()
    vtkPlane.SetOrigin(planePosition)
    vtkPlane.SetNormal(planeNormal)
    projectedPoint = [0.0, 0.0, 0.0]
    vtkPlane.ProjectPoint(point, planePosition, planeNormal, projectedPoint)
    return np.array(projectedPoint)

  @staticmethod
  def getPlaneNormalAndPosition(plane):
    planeNormal, planePosition = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    plane.GetOrigin(planePosition)
    plane.GetNormal(planeNormal)
    return planeNormal, planePosition

  @staticmethod
  def createMarkupsPlane(points, name, visible=False):
    markupsPlane = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", name)
    markupsPlane.AddControlPoint(vtk.vtkVector3d(points[0]))
    markupsPlane.AddControlPoint(vtk.vtkVector3d(points[1]))
    markupsPlane.AddControlPoint(vtk.vtkVector3d(points[2]))
    markupsPlane.SetDisplayVisibility(visible)
    return markupsPlane

  @staticmethod
  def _getUnitVector(lineOrigin, lineTip):
    vector = lineTip - lineOrigin
    return vector / np.linalg.norm(vector)

  def __init__(self):
    super(MeasurementPresetPapillaryAngle, self).__init__()

  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetPapillaryAngle, self).computeMetrics(inputValveModels, outputTableNode)
    if self._valveModel:
      self._quantifyMuscleDistances(self._getListOfPapillaryMuscleDistancePairs())
      # for papillaryMuscleName, papillaryModel in self._getPapillaryMusclesForLocationDetermination().items():
      #   self._quantifyClockwiseMuscleLocationOnAnnularPlane(papillaryModel, papillaryMuscleName)
      #   self._quantifyClockwiseMuscleLocationOnBasePointPlane(papillaryModel, papillaryMuscleName)
    return self.metricsMessages

  def _quantifyMuscleDistances(self, papillaryMuscles):
    if not papillaryMuscles:
      return
    for papillaryModels in papillaryMuscles:
      basePoint1 = papillaryModels[0].getNthMusclePoint(0)
      basePoint2 = papillaryModels[1].getNthMusclePoint(0)
      colName = f'{papillaryModels[0].getName()}-{papillaryModels[1].getName()} distance'
      self.addMeasurement({
        KEY_NAME: colName,
        KEY_VALUE: '%3.1f' % np.linalg.norm(basePoint1 - basePoint2),
        KEY_UNIT: 'mm'
      })
      lineModel = self.createLineModel(colName, basePoint1, basePoint2)
      self.applyProbeToRASAndMoveToMeasurementFolder(self._valveModel, lineModel)

  @abstractmethod
  def _getListOfPapillaryMuscleDistancePairs(self):
    ...

  def _getPapillaryMusclesForLocationDetermination(self):
    return self._getPapillaryMuscles()

  def _quantifyClockwiseMuscleLocationOnAnnularPlane(self, papillaryModel, papillaryMuscleName):
    self._getSeptalAnnularLocationAngle(papillaryModel, papillaryMuscleName)
    self._getValveCenterAnnularLocationAngle(papillaryModel, papillaryMuscleName)

  def _getSeptalAnnularLocationAngle(self, papillaryModel, papillaryMuscleName):
    lineTip, lineOrigin = self._getSeptalLinePointsOnAnnularPlane()
    projectedBasePoint = self.getPointProjectedToAnnularPlane(self._valveModel, papillaryModel.getNthMusclePoint(0))
    muscleAngleDeg = self._getBasePointToLineAngle(projectedBasePoint, lineOrigin, lineTip)
    modelNode = self.createArrowModel("MX->{}".format(papillaryMuscleName), lineOrigin, projectedBasePoint)
    self.applyProbeToRASAndMoveToMeasurementFolder(self._valveModel, modelNode)
    self.addMeasurement({
      KEY_NAME: 'septal plane (ann projection) muscle {} angle'.format(papillaryMuscleName),
      KEY_VALUE: '%3.1f' % muscleAngleDeg,
      KEY_UNIT: 'deg'
    })

  def _getSeptalLinePointsOnAnnularPlane(self):
    pointMA, pointMP = self._valveModel.getAnnulusMarkupPositionsByLabels(["MA", "MP"])
    pointMX = np.mean(np.array([pointMA, pointMP]), axis=0)
    self._valveModel.setAnnulusMarkupLabel('MX', np.mean(np.array([pointMA, pointMP]), axis=0))
    projectedPointMA = self.getPointProjectedToAnnularPlane(self._valveModel, pointMA)
    projectedPointMX = self.getPointProjectedToAnnularPlane(self._valveModel, pointMX)
    modelNode = self.createArrowModel("MX->MA", projectedPointMX, projectedPointMA)
    self.applyProbeToRASAndMoveToMeasurementFolder(self._valveModel, modelNode)
    return projectedPointMA, projectedPointMX

  def _applyProbeToRASAndMoveToMeasurementFolder(self, model):
    self._valveModel.applyProbeToRasTransformToNode(model)
    self.moveNodeToMeasurementFolder(model)

  def _getValveCenterAnnularLocationAngle(self, papillaryModel, papillaryMuscleName):
    lineTip, lineOrigin = self._getValveCenterLinePoints()
    projectedBasePoint = self.getPointProjectedToAnnularPlane(self._valveModel, papillaryModel.getNthMusclePoint(0))
    muscleAngleDeg = self._getBasePointToLineAngle(projectedBasePoint, lineOrigin, lineTip)
    modelNode = self.createArrowModel("{}->{}".format(self._valveCenterLabel, papillaryMuscleName), lineOrigin,
                            projectedBasePoint)
    self.applyProbeToRASAndMoveToMeasurementFolder(self._valveModel, modelNode)
    self.addMeasurement({
      KEY_NAME: 'valve center plane (ann projection) muscle {} angle'.format(papillaryMuscleName),
      KEY_VALUE: '%3.1f' % muscleAngleDeg,
      KEY_UNIT: 'deg'
    })

  def _getValveCenterLinePoints(self):
    projectedPointMA, projectedPointMX = self._getSeptalLinePointsOnAnnularPlane()
    valveCenterPoint = self._valveModel.getAnnulusMarkupPositionByLabel(self._valveCenterLabel)
    projectedValveCenterPoint = self.getPointProjectedToAnnularPlane(self._valveModel, valveCenterPoint)
    valveCenteredPointMA = projectedPointMA + (projectedValveCenterPoint - projectedPointMX)
    modelNode = \
      self.createArrowModel("{}->MA'".format(self._valveCenterLabel), projectedValveCenterPoint, valveCenteredPointMA)
    self.applyProbeToRASAndMoveToMeasurementFolder(self._valveModel, modelNode)
    return valveCenteredPointMA, projectedValveCenterPoint

  def _getBasePointToLineAngle(self, basePoint, lineOrigin, lineTip):
    _, planeNormal = self._valveModel.getAnnulusContourPlane()
    planeNormal = planeNormal / np.linalg.norm(planeNormal)
    v1 = self._getUnitVector(lineOrigin, lineTip)
    v2 = self._getUnitVector(lineOrigin, basePoint)
    dot = np.dot(v1, v2)
    det = np.dot(planeNormal, np.cross(v1, v2))
    angle_deg = np.rad2deg(np.arctan2(det, dot))
    angle_deg = np.abs(angle_deg) if angle_deg < 0 else 360.0 - angle_deg
    return angle_deg

  def _quantifyClockwiseMuscleLocationOnBasePointPlane(self, papillaryModel, papillaryMuscleName):
    pointMA, pointMP, pointMS = self._valveModel.getAnnulusMarkupPositionsByLabels(["MA", "MP", "MS"])
    septalPlane = self._getOrCreatePlane([pointMA, pointMP, pointMS], "Septal Plane")
    basePoint = papillaryModel.getNthMusclePoint(0)
    septalPlaneProjectedBasePoint = self.getPlaneProjectedPoint(septalPlane, basePoint)

    # perpendicular plane to septal plane
    pointMX = np.mean(np.array([pointMA, pointMP]), axis=0)
    translatedProjectedSeptalBasePoint = np.array(septalPlaneProjectedBasePoint) + (np.array(pointMA) - np.array(pointMX))
    basePointPlane = \
      self.createMarkupsPlane([translatedProjectedSeptalBasePoint, septalPlaneProjectedBasePoint, basePoint],
                                             "{} Plane".format(papillaryMuscleName))
    self.applyProbeToRASAndMoveToMeasurementFolder(self._valveModel, basePointPlane)

    basePointPlaneProjectedMXPoint = self.getPlaneProjectedPoint(basePointPlane, pointMX)
    basePointPlaneProjectedMAPoint = self.getPlaneProjectedPoint(basePointPlane, pointMA)

    # valve center
    valveCenterPoint = self._valveModel.getAnnulusMarkupPositionByLabel(self._valveCenterLabel)
    valveCenterPlane = self._getOrCreateValveCenterPlane(septalPlane, pointMX, valveCenterPoint)
    projectedValveCenterPoint = self.getPlaneProjectedPoint(septalPlane, valveCenterPoint)
    valveCenterTranslation = valveCenterPoint - projectedValveCenterPoint
    translatedProjectedMXPoint = basePointPlaneProjectedMXPoint + valveCenterTranslation
    translatedProjectedMAPoint = self.getPlaneProjectedPoint(basePointPlane, pointMA)

    for angleName, originName, (lineOrigin, lineTip) in \
      [("septal plane", "MX", (basePointPlaneProjectedMXPoint, basePointPlaneProjectedMAPoint)),
       ("valve center plane", self._valveCenterLabel, (translatedProjectedMXPoint, translatedProjectedMAPoint))]:
      muscleAngleDeg = self._getBasePointToLineAngle(basePoint, lineOrigin, lineTip)
      modelNode = self.createArrowModel("{}->{}".format(originName, papillaryMuscleName), lineOrigin, basePoint)
      self.applyProbeToRASAndMoveToMeasurementFolder(self._valveModel, modelNode)
      self.addMeasurement({
        KEY_NAME: '{} muscle {} angle'.format(angleName, papillaryMuscleName),
        KEY_VALUE: '%3.1f' % muscleAngleDeg,
        KEY_UNIT: 'deg'
      })

  def _getOrCreatePlane(self, points, planeName):
    plane = self._getItemDataNodeByName(planeName)
    if not plane:
      plane = self.createMarkupsPlane([points[0], points[1], points[2]], planeName)
      self.applyProbeToRASAndMoveToMeasurementFolder(self._valveModel, plane)
    return plane

  def _getOrCreateValveCenterPlane(self, septalPlane, pointMX, valveCenterPoint):
    valveCenterPlaneName = "Valve Center Plane"
    valveCenterPlane = self._getItemDataNodeByName(valveCenterPlaneName)
    if not valveCenterPlane:
      valveCenterPlane = self.cloneSubjectHierarchyItem(septalPlane, valveCenterPlaneName)
      self._translatePlane(valveCenterPlane, translation=valveCenterPoint-pointMX,
                           transformName="{} translation".format(valveCenterPlaneName))
    return valveCenterPlane

  def _translatePlane(self, valveCenterPlane, translation, transformName):
    transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode")
    matrix = np.eye(4)
    matrix[0:3, 3] = translation
    transformNode.SetAndObserveMatrixTransformToParent(slicer.util.vtkMatrixFromArray(matrix))
    self._valveModel.applyProbeToRasTransformToNode(transformNode)
    valveCenterPlane.SetAndObserveTransformNodeID(transformNode.GetID())
    self.moveNodeToMeasurementFolder(valveCenterPlane)


class MeasurementPresetPapillaryMitralValve(MeasurementPresetPapillaryAngle):

  def __init__(self):
    super(MeasurementPresetPapillaryMitralValve, self).__init__()
    self.id = "MitralValvePM"
    self.name = "Mitral valve (papillary muscles)"
    self._requiredValveType = "MitralValve"
    self.inputValveIds = ["MitralValve", "TricuspidValve"]
    self.inputValveNames = { "MitralValve": "Mitral valve", "TricuspidValve": "Tricuspid valve" }
    self._valveCenterLabel = "X"

  def _getListOfPapillaryMuscleDistancePairs(self):
    papillaryMuscles = self._getPapillaryMuscles()
    count = len(papillaryMuscles)
    if count != 2:
      logging.warning("Only distance between two papillary muscles can be computed. {} were given.".format(count))
      return
    return [ papillaryMuscles ]

  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetPapillaryAngle, self).computeMetrics(inputValveModels, outputTableNode)

    self._quantifyMuscleDistances(self._getListOfPapillaryMuscleDistancePairs())
    import numpy as np

    # main valve (e.g. mitral, lavv)
    mainValveModel = inputValveModels[self._requiredValveType]
    planePositionMV, planeNormalMV = mainValveModel.getAnnulusContourPlane()
    mainAnnulusPoints = mainValveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    self.createAnnulusPlaneModel(mainValveModel, mainAnnulusPoints, planePositionMV, planeNormalMV,
                                 name=f"{self.inputValveNames[self._requiredValveType]} Annulus plane")

    if mainValveModel.getAnnulusMarkupPositionByLabel(self._valveCenterLabel) is None:
      mainValveModel.setAnnulusMarkupLabel(
        self._valveCenterLabel, np.mean(mainValveModel.annulusContourCurve.getInterpolatedPointsAsArray(), axis=1)
      )

    # tricuspid plane
    try:
      tricuspidValveModel = inputValveModels["TricuspidValve"]
      planePositionTV, planeNormalTV = tricuspidValveModel.getAnnulusContourPlane()
      tricuspidAnnulusPoints = tricuspidValveModel.annulusContourCurve.getInterpolatedPointsAsArray()
      self.createAnnulusPlaneModel(tricuspidValveModel, tricuspidAnnulusPoints, planePositionTV, planeNormalTV, name="TV Annulus plane")
    except KeyError:
      self.metricsMessages.append("No Tricuspid Valve found. Skipping parts of the calculation.")
      return self.metricsMessages

    if tricuspidValveModel.getAnnulusMarkupPositionByLabel(self._valveCenterLabel) is None:
      tricuspidValveModel.setAnnulusMarkupLabel(
        self._valveCenterLabel, np.mean(tricuspidValveModel.annulusContourCurve.getInterpolatedPointsAsArray(), axis=1)
      )


    # common plane
    interpolatedPoints = np.append(mainAnnulusPoints, tricuspidAnnulusPoints, axis=1)
    from HeartValveLib.ValveModel import planeFit
    planePositionCP, planeNormalCP = planeFit(interpolatedPoints)
    self.createAnnulusPlaneModel(tricuspidValveModel, interpolatedPoints, planePositionCP, planeNormalCP, name="Common Annulus plane")

    self.addSeptalBasedRotationalAngle(mainValveModel, tricuspidValveModel, planePositionCP, planeNormalCP)
    self.addMainValveCenterBasedRotationAngle(mainValveModel, tricuspidValveModel, planePositionMV, planeNormalMV)

    return self.metricsMessages

  def addSeptalBasedRotationalAngle(self, mitralValveModel, tricuspidValveModel, planePosition, planeNormal):

    # calc center between mv and tv (after plane projection)
    mv_center, mv_tv_center, tv_center = self.getProjectedValveCenters(mitralValveModel, tricuspidValveModel,
                                                                       planePosition, planeNormal)
    mv_tv_axis_model = self.createLineModel("Heart Axis (Common plane)", mv_center, tv_center)
    self.applyProbeToRASAndMoveToMeasurementFolder(mitralValveModel, mv_tv_axis_model)
    # ref axis at 9 o'clock
    ref_axis = tv_center - mv_tv_center
    ref_axis = ref_axis / np.linalg.norm(ref_axis)
    mitralAnnulusSmoothCurve = mitralValveModel.annulusContourCurve
    resampledMitralAnnulusPoints = mitralAnnulusSmoothCurve.getSampledInterpolatedPointsAsArray(
      mitralAnnulusSmoothCurve.getInterpolatedPointsAsArray(), 0.1).transpose()
    from scipy.spatial import KDTree
    tree = KDTree(resampledMitralAnnulusPoints)
    idx = tree.query(mv_tv_center)
    closest_point_on_annulus = resampledMitralAnnulusPoints[idx[1] - 1]
    closest_point_on_annulus = getPointProjectedToPlane(planePosition, planeNormal, closest_point_on_annulus)
    mitralValveModel.setAnnulusMarkupLabel('Ref Point (zero)', closest_point_on_annulus)
    normalVector = self.createArrowModel("Zero Reference Vector (Septal based)", closest_point_on_annulus,
                                         closest_point_on_annulus + 5 * ref_axis)
    self.applyProbeToRASAndMoveToMeasurementFolder(mitralValveModel, normalVector)
    angleOrientationAxis = self.getAngleOrientationAxis(mitralValveModel, planeNormal)
    # get base points
    for papillaryModel in self._getPapillaryMuscles():
      basePoint = papillaryModel.getNthMusclePoint(0)
      basePoint = getPointProjectedToPlane(planePosition, planeNormal, basePoint)
      name = f'{papillaryModel.getName()} septal point based rotation muscle angle'
      node = createAngleNode(ref=closest_point_on_annulus + 5 * ref_axis,
                             base=closest_point_on_annulus,
                             to=basePoint,
                             normal=angleOrientationAxis,
                             name=name)
      self.applyProbeToRASAndMoveToMeasurementFolder(mitralValveModel, node)
      node.UpdateAllMeasurements()

      self.addMeasurement({
        KEY_NAME: name,
        KEY_VALUE: '%3.1f' % node.GetAngleDegrees(),
        KEY_UNIT: 'deg'
      })

    self.addSeptalPlane(closest_point_on_annulus, mv_center, mv_tv_center, planeNormal)

  def addSeptalPlane(self, closest_point_on_annulus, mv_center, mv_tv_center, planeNormal):
    center_mp_axis = mv_center - mv_tv_center
    center_mp_axis = center_mp_axis / np.linalg.norm(center_mp_axis)
    # ref axis at 12 o'clock
    ref_axis = np.cross(center_mp_axis, planeNormal)
    ref_axis = ref_axis / np.linalg.norm(ref_axis)
    self._getOrCreatePlane([closest_point_on_annulus,
                            closest_point_on_annulus + 10 * ref_axis,
                            closest_point_on_annulus + 10 * planeNormal], "Septal Plane")

  def getProjectedValveCenters(self, mitralValveModel, tricuspidValveModel, planePosition, planeNormal):
    mv_center = mitralValveModel.getAnnulusMarkupPositionByLabel('X')
    mv_center = getPointProjectedToPlane(planePosition, planeNormal, mv_center)
    tv_center = tricuspidValveModel.getAnnulusMarkupPositionByLabel('X')
    tv_center = getPointProjectedToPlane(planePosition, planeNormal, tv_center)
    mv_tv_center = np.array([mv_center, tv_center]).mean(axis=0)
    return mv_center, mv_tv_center, tv_center

  def addMainValveCenterBasedRotationAngle(self, mitralValveModel, tricuspidValveModel, planePosition, planeNormal):

    # calc center between mv and tv (after plane projection)
    mv_center, mv_tv_center, tv_center = self.getProjectedValveCenters(mitralValveModel, tricuspidValveModel,
                                                                       planePosition, planeNormal)
    mv_tv_axis_model = self.createLineModel("Heart Axis (NM plane)", mv_center, tv_center)
    self.applyProbeToRASAndMoveToMeasurementFolder(mitralValveModel, mv_tv_axis_model)
    # ref axis at 9 o'clock
    ref_axis = tv_center - mv_tv_center
    ref_axis = ref_axis / np.linalg.norm(ref_axis)
    angleOrientationAxis = self.getAngleOrientationAxis(mitralValveModel, planeNormal)

    normalVector = self.createArrowModel("Zero Reference Vector (LV based)", mv_center,
                                         mv_center + 5 * ref_axis)
    self.applyProbeToRASAndMoveToMeasurementFolder(mitralValveModel, normalVector)

    # get base points
    for papillaryModel in self._getPapillaryMuscles():
      basePoint = papillaryModel.getNthMusclePoint(0)
      basePoint = getPointProjectedToPlane(planePosition, planeNormal, basePoint)
      name = f'{papillaryModel.getName()} center point based rotation muscle angle'
      node = createAngleNode(ref=mv_center + 5 * ref_axis,
                             base=mv_center,
                             to=basePoint,
                             normal=angleOrientationAxis,
                             name=name)
      self.applyProbeToRASAndMoveToMeasurementFolder(mitralValveModel, node)
      node.UpdateAllMeasurements()

      self.addMeasurement({
        KEY_NAME: name,
        KEY_VALUE: '%3.1f' % node.GetAngleDegrees(),
        KEY_UNIT: 'deg'
      })

  def getAngleOrientationAxis(self, mitralValveModel, planeNormal):
    probeToRasTransformNode = mitralValveModel.getProbeToRasTransformNode()
    probeToRas = probeToRasTransformNode.GetMatrixTransformToParent()
    planeNormalRas = probeToRas.MultiplyPoint(np.append(planeNormal, 1))
    angleOrientationAxis = np.array(planeNormalRas)[:-1]
    angleOrientationAxis *= -1
    return angleOrientationAxis


class MeasurementPresetPapillaryLAVValve(MeasurementPresetPapillaryMitralValve):

  def __init__(self):
    super(MeasurementPresetPapillaryLAVValve, self).__init__()
    self.id = "LAVValvePM"
    self.name = "LAVV (papillary muscles)"
    self._requiredValveType = "Lavv"
    self.inputValveIds = ["Lavv", "TricuspidValve"]
    self.inputValveNames = { "Lavv": "Lav Valve", "TricuspidValve": "Tricuspid valve" }
    self._valveCenterLabel = "X"


class MeasurementPresetPapillaryTricuspidValve(MeasurementPresetPapillary):
  # TODO: rotational angle is missing

  def __init__(self):
    super(MeasurementPresetPapillaryTricuspidValve, self).__init__()
    self.id = "TricuspidValvePM"
    self.name = "Tricuspid valve (papillary muscles)"
    self._requiredValveType = "TricuspidValve"
    self.inputValveIds = [self._requiredValveType]
    self.inputValveNames[self._requiredValveType] = "Tricuspid valve"
    self._valveCenterLabel = "X"


class MeasurementPresetPapillaryCavc(MeasurementPresetPapillaryAngle):

  @staticmethod
  def getAnnularSide(valveModel, papillaryModel):
    pointR, pointL = valveModel.getAnnulusMarkupPositionsByLabels(["R", "L"])
    chordInsertionPoint = papillaryModel.getNthMusclePoint(2)
    distanceRMm = np.linalg.norm(chordInsertionPoint - pointR)
    distanceLMm = np.linalg.norm(chordInsertionPoint - pointL)
    return "L" if distanceLMm < distanceRMm else "R"

  def __init__(self):
    super(MeasurementPresetPapillaryCavc, self).__init__()
    self.id = "CavcPM"
    self.name = "CAVC (papillary muscles)"
    self._requiredValveType = "Cavc"
    self.inputValveIds = [self._requiredValveType]
    self.inputValveNames[self._requiredValveType] = "CAVC"
    self._valveCenterLabel = "LC"

  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetPapillaryCavc, self).computeMetrics(inputValveModels, outputTableNode)

    cavcValveModel = inputValveModels["Cavc"]

    # LC point
    pointR, pointL, pointLA, pointLP = cavcValveModel.getAnnulusMarkupPositionsByLabels(["R", "L", "LA", "LP"])
    [pointLC, _] = HeartValveLib.getLinesIntersectionPoints(pointR, pointL, pointLA, pointLP)
    cavcValveModel.setAnnulusMarkupLabel('LC', pointLC)

    # RC point
    pointR, pointL, pointRA, pointRP = cavcValveModel.getAnnulusMarkupPositionsByLabels(["R", "L", "RA", "RP"])
    [pointRC, _] = HeartValveLib.getLinesIntersectionPoints(pointR, pointL, pointRA, pointRP)
    cavcValveModel.setAnnulusMarkupLabel('RC', pointRC)

    self.addSeptalBasedRotationalAngles(cavcValveModel, pointLC, pointRC)
    self.addLeftCenterBasedRotationalAngles(cavcValveModel, pointLC, pointRC)

    return self.metricsMessages

  def addSeptalBasedRotationalAngles(self, cavcValveModel, pointLC, pointRC):
    # common annulus plane
    planePosition, planeNormal = cavcValveModel.getAnnulusContourPlane()
    mitralAnnulusPoints = cavcValveModel.annulusContourCurve.getInterpolatedPointsAsArray()
    self.createAnnulusPlaneModel(cavcValveModel, mitralAnnulusPoints, planePosition, planeNormal, name="Common Annulus plane")

    left_center = getPointProjectedToPlane(planePosition, planeNormal, pointLC)
    right_center = getPointProjectedToPlane(planePosition, planeNormal, pointRC)

    center_axis_model = self.createLineModel("Heart Axis (Common plane)", left_center, right_center)
    self.applyProbeToRASAndMoveToMeasurementFolder(cavcValveModel, center_axis_model)
    center = np.array([left_center, right_center]).mean(axis=0)
    cavcValveModel.setAnnulusMarkupLabel('Ref Point (zero)', center)

    # ref axis at 9 o'clock
    ref_axis = right_center - center
    ref_axis = ref_axis / np.linalg.norm(ref_axis)
    normalVector = self.createArrowModel("Zero Reference Vector (Septal based)", center, center + 5 * ref_axis)
    self.applyProbeToRASAndMoveToMeasurementFolder(cavcValveModel, normalVector)

    probeToRasTransformNode = cavcValveModel.getProbeToRasTransformNode()
    probeToRas = probeToRasTransformNode.GetMatrixTransformToParent()

    for papillaryModel in self._getPapillaryMuscles():
      papillaryMuscleName = papillaryModel.getName()

      if not "lateral" in papillaryMuscleName:
        continue
      planeNormalRas = probeToRas.MultiplyPoint(np.append(planeNormal, 1))
      angleOrientationAxis = np.array(planeNormalRas)[:-1]
      if "lateral" in papillaryMuscleName:
        angleOrientationAxis = angleOrientationAxis * (-1)

      basePoint = papillaryModel.getNthMusclePoint(0)
      basePoint = getPointProjectedToPlane(planePosition, planeNormal, basePoint)

      name = f'{papillaryMuscleName} septal point based rotation muscle angle'

      node = createAngleNode(ref=center + 5 * ref_axis,
                             base=center,
                             to=basePoint,
                             normal=angleOrientationAxis,
                             name=name)
      self.applyProbeToRASAndMoveToMeasurementFolder(cavcValveModel, node)
      node.UpdateAllMeasurements()
      print(f"{name} : {node.GetAngleDegrees()}")
      self.addMeasurement({
        KEY_NAME: name,
        KEY_VALUE: '%3.1f' % node.GetAngleDegrees(),
        KEY_UNIT: 'deg'
      })
    self.addSeptalPlane(planeNormal)

  def addSeptalPlane(self, planeNormal):
    pointMA, pointMP = self._valveModel.getAnnulusMarkupPositionsByLabels(["MA", "MP"])
    self._valveModel.setAnnulusMarkupLabel('MX', np.mean(np.array([pointMA, pointMP]), axis=0))
    projectedPointMA = self.getPointProjectedToAnnularPlane(self._valveModel, pointMA)
    projectedPointMP = self.getPointProjectedToAnnularPlane(self._valveModel, pointMP)
    pointMX = np.mean(np.array([projectedPointMA, projectedPointMP]), axis=0)
    self._getOrCreatePlane([pointMX, projectedPointMP, pointMX + 10 * planeNormal], "Septal Plane")

  def addLeftCenterBasedRotationalAngles(self, cavcValveModel, pointLC, pointRC):
    # left annulus plane
    annulusPoints, planeNormal, planePosition = self.getSideSpecificAnnulus(side="L")
    self.createAnnulusPlaneModel(cavcValveModel, annulusPoints, planePosition, planeNormal, name="Left Annulus plane")

    left_center = getPointProjectedToPlane(planePosition, planeNormal, pointLC)
    right_center = getPointProjectedToPlane(planePosition, planeNormal, pointRC)

    center_axis_model = self.createLineModel("Heart Axis (LV plane)", left_center, right_center)
    self.applyProbeToRASAndMoveToMeasurementFolder(cavcValveModel, center_axis_model)

    center = np.array([left_center, right_center]).mean(axis=0)
    cavcValveModel.setAnnulusMarkupLabel('Ref Point (zero)', center)

    # ref axis at 9 o'clock
    ref_axis = right_center - center
    ref_axis = ref_axis / np.linalg.norm(ref_axis)

    normalVector = self.createArrowModel("Zero Reference Vector (LV based)", left_center, left_center + 5 * ref_axis)
    self.applyProbeToRASAndMoveToMeasurementFolder(cavcValveModel, normalVector)
    probeToRasTransformNode = cavcValveModel.getProbeToRasTransformNode()
    probeToRas = probeToRasTransformNode.GetMatrixTransformToParent()
    for papillaryModel in self._getPapillaryMuscles():
      papillaryMuscleName = papillaryModel.getName()

      if not "lateral" in papillaryMuscleName:
        continue

      planeNormalRas = probeToRas.MultiplyPoint(np.append(planeNormal, 1))
      angleOrientationAxis = np.array(planeNormalRas)[:-1]
      if "lateral" in papillaryMuscleName:
        angleOrientationAxis = angleOrientationAxis * (-1)

      basePoint = papillaryModel.getNthMusclePoint(0)
      basePoint = getPointProjectedToPlane(planePosition, planeNormal, basePoint)
      side_center_point = left_center if "lateral" in papillaryMuscleName else right_center
      side_indicator = "left" if "lateral" in papillaryMuscleName else "right"

      # NB: calculated in common plane
      name = f'{papillaryMuscleName} {side_indicator} center point based rotation muscle angle'
      node = createAngleNode(ref=side_center_point + 5 * ref_axis,
                             base=side_center_point,
                             to=basePoint,
                             normal=angleOrientationAxis,
                             name=name)
      self.applyProbeToRASAndMoveToMeasurementFolder(cavcValveModel, node)
      node.UpdateAllMeasurements()

      print(f"{name} : {node.GetAngleDegrees()}")
      self.addMeasurement({
        KEY_NAME: name,
        KEY_VALUE: '%3.1f' % node.GetAngleDegrees(),
        KEY_UNIT: 'deg'
      })

  def getSideSpecificAnnulus(self, side):
    from ValveQuantificationLib import MeasurementPresetCavc
    pointMA, pointMP, point3 = self._valveModel.getAnnulusMarkupPositionsByLabels(["MA", "MP", side])
    annulusContourSideStartIndices = \
      MeasurementPresetCavc.getAnnulusContourSplitSidesStartIndices(self._valveModel, pointMA, pointMP, point3)
    annulusPoints = MeasurementPresetCavc.getAnnulusCurvePoints(self._valveModel,
                                                                annulusContourSideStartIndices[side])
    planePosition, planeNormal = MeasurementPresetCavc.getPartialContourPlane(annulusPoints, self._valveModel)
    return annulusPoints, planeNormal, planePosition

  def _getPapillaryMusclesForLocationDetermination(self):
    return self._getMusclesBySide("L")

  def _getMusclesBySide(self, side):
    return list(filter(lambda x: self.getAnnularSide(self._valveModel, x) == side, self._getPapillaryMuscles()))

  def _quantifyAnnularMuscleAngle(self, papillaryModel):
    from ValveQuantificationLib import MeasurementPresetCavc
    papillaryMuscleName = papillaryModel.getName()
    point3Label = "L" if "lateral" in papillaryMuscleName else "R"
    pointMA, pointMP, point3 = self._valveModel.getAnnulusMarkupPositionsByLabels(["MA", "MP", point3Label])
    annulusContourSideStartIndices = \
      MeasurementPresetCavc.getAnnulusContourSplitSidesStartIndices(self._valveModel, pointMA, pointMP, point3)
    valveSide = self.getAnnularSide(self._valveModel, papillaryModel)
    annulusPoints = MeasurementPresetCavc.getAnnulusCurvePoints(self._valveModel,
                                                                annulusContourSideStartIndices[valveSide])
    _, annulusPlaneNormal = MeasurementPresetCavc.getPartialContourPlane(annulusPoints, self._valveModel)

    muscleAngles = {
      '{} muscle angle (tip-chord to annulus-plane)'.format(papillaryMuscleName):
        papillaryModel.getTipChordMuscleAngleDeg(annulusPlaneNormal),
      '{} muscle angle (base-chord to annulus-plane)'.format(papillaryMuscleName):
        papillaryModel.getBaseChordMuscleAngleDeg(annulusPlaneNormal)
    }
    for name, muscleAngleDeg in muscleAngles.items():
      if muscleAngleDeg is not None:
        self.addMeasurement({
          KEY_NAME: name,
          KEY_VALUE: '%3.1f' % muscleAngleDeg,
          KEY_UNIT: 'deg'
        })

  def _getListOfPapillaryMuscleDistancePairs(self):
    papillaryModels = []
    for side in ["R", "L"]:
      papillaryMuscles = self._getMusclesBySide(side)
      count = len(papillaryMuscles)
      if count != 2:
        logging.warning("Only distance between two papillary muscles can be computed. {} were given.".format(count))
        continue
      else:
        papillaryModels.append(papillaryMuscles)
    return papillaryModels


def createMarkupsPlane(points, name, visible=False):
  markupsPlane = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", name)
  markupsPlane.AddControlPoint(vtk.vtkVector3d(points[0]))
  markupsPlane.AddControlPoint(vtk.vtkVector3d(points[1]))
  markupsPlane.AddControlPoint(vtk.vtkVector3d(points[2]))
  markupsPlane.SetDisplayVisibility(visible)
  return markupsPlane


def getPointProjectedToPlane(planePosition, planeNormal, point):
  point2D = np.zeros([3, 1])
  point2D[:, 0] = np.array(point)
  pointsArrayProjected_World, _, _ = HeartValveLib.getPointsProjectedToPlane(point2D, planePosition, planeNormal)
  return pointsArrayProjected_World[:, 0]


def createAngleNode(base, ref, to, normal, name):
  angleNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsAngleNode", name)
  angleNode.AddControlPoint(vtk.vtkVector3d(ref))
  angleNode.AddControlPoint(vtk.vtkVector3d(base))
  angleNode.AddControlPoint(vtk.vtkVector3d(to))
  angleNode.SetOrientationRotationAxis(normal)
  angleNode.SetAngleMeasurementModeToOrientedPositive()
  return angleNode