#
#   LeafletModel.py: Stores valve leaflet data, quantifies properties, and creates displayable models
#

import vtk, slicer
import HeartValveLib
import math
import numpy as np
import vtk.util.numpy_support as VN
import vtkSegmentationCorePython as vtkSegmentationCore
import SmoothCurve


class LeafletModel:

  def __init__(self):
    self.markupGlyphScale = 0.5
    self.surfaceBoundary = SmoothCurve.SmoothCurve()
    self.surfaceBoundary.closed = True
    self.surfaceBoundary.setTubeRadius(self.markupGlyphScale/2.0)
    self.surfaceModelNode = None
    self.segmentationNode = None
    self.segmentId = None

  def getName(self):
    return self.segmentationNode.GetSegmentation().GetSegment(self.segmentId).GetName()

  def setSegmentationNode(self, segmentationNode):
    self.segmentationNode = segmentationNode

  def setSegmentId(self, segmentId):
    self.segmentId = segmentId

  def setSurfaceModelNode(self, surfaceModelNode):
    self.surfaceModelNode = surfaceModelNode
    self.updateSurface()

  def setSurfaceBoundaryMarkupNode(self, surfaceBoundaryMarkupNode):
    self.surfaceBoundary.setControlPointsMarkupNode(surfaceBoundaryMarkupNode)
    self.updateSurface()

  def getSurfaceBoundaryMarkupNode(self):
    return self.surfaceBoundary.controlPointsMarkupNode

  def setSurfaceBoundaryModelNode(self, surfaceBoundaryModelNode):
    self.surfaceBoundary.setCurveModelNode(surfaceBoundaryModelNode)

  def getSurfaceBoundaryModelNode(self):
    return self.surfaceBoundary.curveModelNode

  def updateSurface(self):
    self.surfaceBoundary.updateCurve()
    self.extractSurfaceByBoundary()

  def getValvePlanePosition(self):
    arrayAsString = self.surfaceBoundary.controlPointsMarkupNode.GetAttribute("ValvePlanePosition")
    if not arrayAsString:
      return None
    # for example: arrayAsString = "0.32 0.45 0.11"
    return [float(x) for x in arrayAsString.split(' ')]

  def setValvePlanePosition(self, valvePlanePosition):
    if valvePlanePosition is None:
      self.surfaceBoundary.controlPointsMarkupNode.RemoveAttribute("ValvePlanePosition")
    else:
      arrayAsString = ' '.join([str(x) for x in valvePlanePosition])
      self.surfaceBoundary.controlPointsMarkupNode.SetAttribute("ValvePlanePosition", arrayAsString)

  def getValvePlaneNormal(self):
    arrayAsString = self.surfaceBoundary.controlPointsMarkupNode.GetAttribute("ValvePlaneNormal")
    if not arrayAsString:
      return None
    # for example: arrayAsString = "0.32 0.45 0.11"
    return np.array([float(x) for x in arrayAsString.split(' ')])

  def setValvePlaneNormal(self, valvePlaneNormal):
    if valvePlaneNormal is None:
      self.surfaceBoundary.controlPointsMarkupNode.RemoveAttribute("ValvePlaneNormal")
    else:
      arrayAsString = ' '.join([str(x) for x in valvePlaneNormal])
      self.surfaceBoundary.controlPointsMarkupNode.SetAttribute("ValvePlaneNormal", arrayAsString)

  def getSelectLargestRegion(self):
    selectLargestRegion = self.surfaceBoundary.controlPointsMarkupNode.GetAttribute("SelectLargestRegion")
    if selectLargestRegion is None:
      # Use largest region by default
      return True
    return selectLargestRegion.lower()=='true'

  def setSelectLargestRegion(self, selectLargestRegion):
    self.surfaceBoundary.controlPointsMarkupNode.SetAttribute(
      "SelectLargestRegion", 'true' if selectLargestRegion else 'false')
    self.updateSurface()

  def getNumberOfControlPoints(self, markupsNode):
    if not markupsNode:
      return 0
    return markupsNode.GetNumberOfDefinedControlPoints()

  def extractSurfaceByBoundary(self):
    """
    Update model to enclose all points in the input markup list
    """

    inputMarkup = self.surfaceBoundary.controlPointsMarkupNode
    numberOfPoints = self.getNumberOfControlPoints(inputMarkup)
    fullLeafletPolydata = self.getLeafletPolydata()
    if not fullLeafletPolydata or fullLeafletPolydata.GetNumberOfCells() == 0 or not inputMarkup or numberOfPoints<3:
      # empty input mesh
      if self.surfaceModelNode.GetPolyData() and self.surfaceModelNode.GetPolyData().GetNumberOfCells() > 0:
        # existing mesh is not empty
        emptyPolyData = vtk.vtkPolyData()
        self.surfaceModelNode.SetAndObservePolyData(emptyPolyData)
      return None

    selectionPoints = vtk.vtkPoints()
    new_coord = [0.0, 0.0, 0.0]
    for i in range(numberOfPoints):
      try:
        # Current API (Slicer-4.13 February 2022)
        inputMarkup.GetNthControlPointPosition(i,new_coord)
      except:
        # Legacy API
        inputMarkup.GetNthFiducialPosition(i,new_coord)
      selectionPoints.InsertPoint(i, new_coord)

    loop = vtk.vtkSelectPolyData()
    loop.SetLoop(selectionPoints)
    loop.GenerateSelectionScalarsOn()
    loop.SetInputData(fullLeafletPolydata)

    # loop.SetSelectionModeToClosestPointRegion() does not seem to work
    # (always extracts the same side of the mesh, regardless of what
    # point is set in loop.SetClosestPoint(...)
    # Therefore, we extract both sides of the surface and choose the one
    # that is closer to the requested closestPoint.
    closestPoint = None
    valvePlaneNormal = self.getValvePlaneNormal()
    valvePlanePosition = self.getValvePlanePosition()
    if valvePlaneNormal is not None and valvePlanePosition is not None:
      # we go 30mm opposite to the valve plane normal direction from the center of the plane
      # to make sure we pick a point on the inflow side
      closestPoint = valvePlanePosition - valvePlaneNormal * 30.0

    loop.SetSelectionModeToLargestRegion()

    clip = vtk.vtkClipPolyData()
    clip.InsideOutOn()
    clip.SetInputConnection(loop.GetOutputPort())
    clip.GenerateClippedOutputOn()
    # attributes = vtk.vtkDataSetAttributes()
    # attributes.SetInputConnection(clip.GetOutputPort())
    # attributes.CopyScalarsOff()

    clip.Update()
    clippedOutput = clip.GetOutput()

    if closestPoint is not None:
      clippedOutputs = [clip.GetOutput(), clip.GetClippedOutput()]
      closestDistances = []

      for part in clippedOutputs:
        cleaner = vtk.vtkCleanPolyData() # removeUnusedPoints
        cleaner.SetInputData(part)
        cleaner.Update()
        cleanedPart = cleaner.GetOutput()
        loc = vtk.vtkPointLocator()
        loc.SetDataSet(cleanedPart)
        foundClosestPointId = loc.FindClosestPoint(closestPoint)
        if foundClosestPointId >=0 and foundClosestPointId < cleanedPart.GetPoints().GetNumberOfPoints():
          nearestPointOnLeafletSurface = np.array(cleanedPart.GetPoints().GetPoint(foundClosestPointId))
          closestDistances.append(np.linalg.norm(nearestPointOnLeafletSurface-closestPoint))
        else:
          # empty mesh, use some large number to not find it as the closest distance
          closestDistances.append(1e6)

      if self.getSelectLargestRegion():
        # inflow side
        minimumClosestDistanceIndex = closestDistances.index(min(closestDistances))
      else:
        # outflow side
        minimumClosestDistanceIndex = closestDistances.index(max(closestDistances))
      clippedOutput = clippedOutputs[minimumClosestDistanceIndex]

    else:

      if self.getSelectLargestRegion():
        clippedOutput = clip.GetClippedOutput()
      else:
        clippedOutput = clip.GetOutput()

    #print("Result: {0} points, {1} cells".format(clippedOutput.GetNumberOfPoints(), clippedOutput.GetNumberOfCells()))
    self.surfaceModelNode.SetAndObservePolyData(clippedOutput)
    if self.surfaceModelNode.GetDisplayNode():
      self.surfaceModelNode.GetDisplayNode().SetActiveScalarName("")
    #outputModel.Modified()

  @staticmethod
  def extractTopSurface(fullLeafletPolydata, surfaceNormalDirections, angleToleranceDeg):

    if not fullLeafletPolydata or fullLeafletPolydata.GetNumberOfCells() == 0:
      # empty input mesh
      return None

    # Clean up input
    cleaner = vtk.vtkCleanPolyData()
    cleaner.SetInputData(fullLeafletPolydata)
    stripper = vtk.vtkTriangleFilter()
    stripper.SetInputConnection(cleaner.GetOutputPort())

    # Compute point normals
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(stripper.GetOutputPort())
    #normals.SetInputData(fullLeafletPolydata)
    normals.AutoOrientNormalsOn()
    #normals.NonManifoldTraversalOn()
    normals.ComputePointNormalsOn()
    normals.ComputeCellNormalsOff()

    # Compute angle compared to surfaceNormalDirection
    calc = vtk.vtkArrayCalculator()
    calc.SetInputConnection(normals.GetOutputPort())
    calc.SetAttributeTypeToPointData()
    calc.AddVectorArrayName("Normals")

    # Get angle difference function string for each normal: angleDiff = acos(dot(Normal, surfaceNormalDirection))
    singleAngleDiffFuncStrs = [] # list of angle differences for each normal direction 'acos(Normals.(iHat*(0.4)+jHat*(0.3)+kHat*(0.2))))'
    for surfaceNormalDirection in surfaceNormalDirections:
      # make sure the surfaceNormalDirection vector is normalized
      normalizedSurfaceNormalDirection = np.array(surfaceNormalDirection)
      normalizedSurfaceNormalDirection = normalizedSurfaceNormalDirection/np.linalg.norm(surfaceNormalDirection)
      vtkVersion = vtk.vtkVersion()
      if vtkVersion.GetVTKMajorVersion() >= 9 and vtkVersion.GetVTKMinorVersion() > 0:
        singleAngleDiffFuncStrs.append("acos(dot(Normals,(iHat*({0})+jHat*({1})+kHat*({2}))))".format(
          normalizedSurfaceNormalDirection[0], normalizedSurfaceNormalDirection[1], normalizedSurfaceNormalDirection[2]))
      else:
        singleAngleDiffFuncStrs.append("acos(Normals.(iHat*({0})+jHat*({1})+kHat*({2})))".format(
          normalizedSurfaceNormalDirection[0], normalizedSurfaceNormalDirection[1],
          normalizedSurfaceNormalDirection[2]))

    # Get function string that computes the minimum for all angle differences
    angleDiffFuncStr = "" # min(min(min(min(diff1,diff2),diff3),diff4),diff5)
    for i in range(len(singleAngleDiffFuncStrs)-1):
      angleDiffFuncStr += "min("
    for index, singleAngleDiffFuncStr in enumerate(singleAngleDiffFuncStrs):
      if index == 0:
        angleDiffFuncStr += singleAngleDiffFuncStr
      else:
        angleDiffFuncStr += ","+singleAngleDiffFuncStr+")"

    print(angleDiffFuncStr)
    calc.SetResultArrayName('angleDiff')
    calc.SetFunction(angleDiffFuncStr)

    # Cut along specified threshold value (smooth cut through cells)
    threshold = vtk.vtkClipPolyData()
    threshold.SetInputConnection(calc.GetOutputPort())
    angleToleranceRad = float(angleToleranceDeg) * math.pi / 180.0
    threshold.SetValue(angleToleranceRad)
    threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "angleDiff")
    threshold.InsideOutOn()

    extractLargest = vtk.vtkPolyDataConnectivityFilter()
    extractLargest.SetExtractionModeToLargestRegion()
    extractLargest.SetInputConnection(threshold.GetOutputPort())
    extractLargest.Update()

    polyData = vtk.vtkPolyData()
    polyData.ShallowCopy(extractLargest.GetOutput())
    polyData.GetPointData().SetActiveScalars(None)
    return polyData

  def createLeafletSurfaceModel(self, surfaceNormalDirections, angleToleranceDeg, visibility = False):
    """Adds a model to the MRML scene, created from the extracted surface of the leaflet
    :param surfaceNormalDirection: 3-element vector defining the surface normal
    :return MRML model node
    """
    fullLeafletPolydata = self.getLeafletPolydata()
    leafletSurfacePolydata = self.extractTopSurface(fullLeafletPolydata, surfaceNormalDirections, angleToleranceDeg)
    if not leafletSurfacePolydata:
      # empty polydata
      return None

    modelsLogic = slicer.modules.models.logic()
    modelNode = modelsLogic.AddModel(leafletSurfacePolydata)
    modelNode.SetName("Leaflet surface")
    modelNode.GetDisplayNode().SetVisibility(visibility)
    modelNode.GetDisplayNode().SetSliceIntersectionThickness(5)
    modelNode.GetDisplayNode().SetColor(self.getLeafletColor())
    modelNode.GetDisplayNode().SetOpacity(0.6)
    modelNode.GetDisplayNode().SetAmbient(0.1)
    modelNode.GetDisplayNode().SetDiffuse(0.9)
    modelNode.GetDisplayNode().SetSpecular(0.1)
    modelNode.GetDisplayNode().SetPower(10)
    modelNode.GetDisplayNode().BackfaceCullingOff()
    return modelNode

  def getLeafletPolydata(self):
    return self.getLeafletSegment().GetRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName())

  def getLeafletColor(self):
    color = self.getLeafletSegment().GetColor()
    displayNode = self.segmentationNode.GetDisplayNode()
    if displayNode:
      color = displayNode.GetSegmentColor(self.segmentId)
    return color

  def getLeafletSegment(self):
    segmentation = self.segmentationNode.GetSegmentation()
    leafletSegment = segmentation.GetSegment(self.segmentId)
    return leafletSegment

  def autoDetectSurfaceBoundary(self, valvePlanePosition, valvePlaneNormal, numberOfBoundaryMarkups=30):

    self.setValvePlanePosition(valvePlanePosition)
    self.setValvePlaneNormal(valvePlaneNormal)

    leafletSegmentationNode = self.segmentationNode
    segmentation = leafletSegmentationNode.GetSegmentation()
    segment = segmentation.GetSegment(self.segmentId)

    # Compute the leaflet plane normal. It's not exactly the same as the valve normal
    # as we want to look at each leaflet from the top and a bit from the side to see the coaptation plane.

    # Leaflet-aligned coordinate system: X points towards leaflet from the center of the valve, Z to up
    segmentPolydata = segment.GetRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName())
    if not segmentPolydata or segmentPolydata.GetNumberOfPoints() == 0:
      # no segmentation is available
      return
    segmentPolydataPoints = VN.vtk_to_numpy(segmentPolydata.GetPoints().GetData())

    planePosition, planeNormal = HeartValveLib.planeFit(segmentPolydataPoints.T)

    # Transform from plane to world
    transformPlaneToWorldMatrix = np.linalg.inv(HeartValveLib.getTransformToPlane(planePosition, planeNormal))

    boundaryMarkups = self.getSurfaceBoundaryMarkupNode()
    try:
      # Current API (Slicer-4.13 February 2022)
      boundaryMarkups.RemoveAllControlPoints()
    except:
      # Legacy API
      boundaryMarkups.RemoveAllMarkups()

    # Put together the 3 transforms and get the tilted plane normal
    for boundaryMarkupIndex in range(numberOfBoundaryMarkups):
      rotAngleZ = 2 * math.pi * float(boundaryMarkupIndex) / float(numberOfBoundaryMarkups)

      cutPlaneNormal_Plane = np.append(
        np.cross(np.array([math.sin(rotAngleZ), math.cos(rotAngleZ), 0]),
        np.array([0, 0, 1])), 0)

      boundaryPointsMaximumDistanceMm = 100
      boundaryPointFarPosition_Plane = np.array([boundaryPointsMaximumDistanceMm * math.sin(rotAngleZ),
                                                 boundaryPointsMaximumDistanceMm * math.cos(rotAngleZ), -50, 1])

      boundaryPointFarPosition_World = np.dot(transformPlaneToWorldMatrix, boundaryPointFarPosition_Plane)
      cutPlaneNormal_World = np.dot(transformPlaneToWorldMatrix, cutPlaneNormal_Plane)

      cutPlane = vtk.vtkPlane()
      cutPlane.SetOrigin(boundaryPointFarPosition_World[0:3])
      cutPlane.SetNormal(cutPlaneNormal_World[0:3])

      cutter = vtk.vtkCutter()
      cutter.SetInputData(segmentPolydata)
      cutter.SetCutFunction(cutPlane)
      cutter.Update()

      loc = vtk.vtkPointLocator()
      loc.SetDataSet(cutter.GetOutput())
      closestPointId = loc.FindClosestPoint(boundaryPointFarPosition_World[0:3])
      if 0 <= closestPointId < cutter.GetOutput().GetPoints().GetNumberOfPoints():
        nearestPointOnLeafletSurface = cutter.GetOutput().GetPoints().GetPoint(closestPointId)
        try:
          # Current API (Slicer-4.13 February 2022)
          boundaryMarkups.AddControlPoint(nearestPointOnLeafletSurface[0], nearestPointOnLeafletSurface[1], nearestPointOnLeafletSurface[2])
        except:
          # Legacy API
          boundaryMarkups.AddFiducial(nearestPointOnLeafletSurface[0], nearestPointOnLeafletSurface[1], nearestPointOnLeafletSurface[2])


  def createSurfaceBoundaryFromCurve(self, valvePlanePosition, valvePlaneNormal, curve):
    """
    :param curve SmoothCurve that will be used to generate surface boundary curve
    """
    self.setValvePlanePosition(valvePlanePosition)
    self.setValvePlaneNormal(valvePlaneNormal)

    leafletSegmentationNode = self.segmentationNode
    segmentation = leafletSegmentationNode.GetSegmentation()
    segment = segmentation.GetSegment(self.segmentId)

    # Compute the leaflet plane normal. It's not exactly the same as the valve normal
    # as we want to look at each leaflet from the top and a bit from the side to see the coaptation plane.

    # Leaflet-aligned coordinate system: X points towards leaflet from the center of the valve, Z to up
    segmentPolydata = segment.GetRepresentation(
      vtkSegmentationCore.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName())
    if not segmentPolydata or segmentPolydata.GetNumberOfPoints() == 0:
      # no segmentation is available
      return

    boundaryMarkups = self.getSurfaceBoundaryMarkupNode()
    try:
      # Current API (Slicer-4.13 February 2022)
      boundaryMarkups.RemoveAllControlPoints()
    except:
      # Legacy API
      boundaryMarkups.RemoveAllMarkups()

    loc = vtk.vtkPointLocator()
    loc.SetDataSet(segmentPolydata)

    numberOfCurvePoints = curve.curvePoints.GetNumberOfPoints()
    pos = [0.0, 0.0, 0.0]
    for pointIndex in range(numberOfCurvePoints):
      curve.curvePoints.GetPoint(pointIndex, pos)
      pos += (pos - valvePlanePosition) * 0.2

      closestPointId = loc.FindClosestPoint(pos)
      if 0 <= closestPointId < segmentPolydata.GetPoints().GetNumberOfPoints():
        nearestPointOnLeafletSurface = segmentPolydata.GetPoints().GetPoint(closestPointId)
        try:
          # Current API (Slicer-4.13 February 2022)
          boundaryMarkups.AddControlPoint(nearestPointOnLeafletSurface[0], nearestPointOnLeafletSurface[1], nearestPointOnLeafletSurface[2])
        except:
          # Legacy API
          boundaryMarkups.AddFiducial(nearestPointOnLeafletSurface[0], nearestPointOnLeafletSurface[1], nearestPointOnLeafletSurface[2])
