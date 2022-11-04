#
#   SmoothCurve.py: Creates smooth curves from markups
#

import vtk, qt, ctk, slicer
import math
import numpy as np
import logging
import HeartValveLib

InterpolationLinear = 0
InterpolationSpline = 1

class SmoothCurve:

  def __init__(self):
    self.controlPointsMarkupNode = None
    self.curveModelNode = None

    self.tubeRadius = 5.0
    self.tubeResolution = 20

    self.numberOfIntermediatePoints = 20

    self.curvePoly = vtk.vtkPolyData()
    self.curvePoints = vtk.vtkPoints()
    self.curvePoly.SetPoints(self.curvePoints)

    self.curvePointsLocator = vtk.vtkPointLocator()
    self.curvePointsLocator.SetDataSet(self.curvePoly)

    self.interpolationMethod = InterpolationLinear
    self.pointInterpolationFunction = self.getInterpolatedPointsLinear

    self.closed = False

  def setCurveModelNode(self, destination):
    self.curveModelNode = destination
    self.updateCurve()

  def setControlPointsMarkupNode(self, source):
    self.controlPointsMarkupNode = source
    HeartValveLib.setMarkupPlaceModeToUnconstrained(self.controlPointsMarkupNode)
    self.updateCurve()

  def setNumberOfIntermediatePoints(self,npts):
    if npts > 0:
      self.numberOfIntermediatePoints = npts
    self.updateCurve()

  def setTubeRadius(self, radius):
    self.tubeRadius = radius
    self.updateCurve()

  def setInterpolationMethod(self, method):
    if method == self.interpolationMethod:
      return

    if method == InterpolationLinear:
      self.pointInterpolationFunction = self.getInterpolatedPointsLinear
    elif method == InterpolationSpline:
      self.pointInterpolationFunction = self.getInterpolatedPointsSpline
    else:
      logging.error("Invalid interpolation method requested: {0}".format(method))
      return

    self.interpolationMethod = method
    self.updateCurve()

  def setClosed(self, closed):
    self.closed = closed
    self.updateCurve()

  def getInterpolatedPointsLinear(self, sourceNode, points):
    try:
      # Slicer-4.13 (February 2022) and later
      numberOfControlPoints = sourceNode.GetNumberOfControlPoints()
    except:
      # fall back to older API
      numberOfControlPoints = sourceNode.GetNumberOfFiducials()
    nInterpolatedPoints = self.numberOfIntermediatePoints*(numberOfControlPoints if self.closed else numberOfControlPoints-1)
    points.Allocate(nInterpolatedPoints)

    pos = np.array([0.0, 0.0, 0.0])
    try:
      # Current API (Slicer-4.13 February 2022)
      sourceNode.GetNthControlPointPosition(0,pos)
    except:
      # Legacy API
      sourceNode.GetNthFiducialPosition(0,pos)
    nextPos = np.array([0.0, 0.0, 0.0])
    for controlPointIndex in range(1,numberOfControlPoints):
      try:
        # Current API (Slicer-4.13 February 2022)
        sourceNode.GetNthControlPointPosition(controlPointIndex,nextPos)
      except:
        # Legacy API
        sourceNode.GetNthFiducialPosition(controlPointIndex,nextPos)
      posStep = (nextPos-pos)/float(self.numberOfIntermediatePoints)
      for intermediatePointIndex in range(self.numberOfIntermediatePoints):
        interpolatedPos = pos+intermediatePointIndex*posStep
        points.InsertNextPoint(interpolatedPos[0], interpolatedPos[1], interpolatedPos[2])
      np.copyto(pos, nextPos)

    # Close contour with an additional segment
    if self.closed:
      try:
        # Current API (Slicer-4.13 February 2022)
        sourceNode.GetNthControlPointPosition(0,nextPos)
      except:
        # Legacy API
        sourceNode.GetNthFiducialPosition(0,nextPos)
      posStep = (nextPos-pos)/float(self.numberOfIntermediatePoints)
      for intermediatePointIndex in range(self.numberOfIntermediatePoints):
        interpolatedPos = pos+intermediatePointIndex*posStep
        points.InsertNextPoint(interpolatedPos[0], interpolatedPos[1], interpolatedPos[2])

    # Add a point at the last position
    points.InsertNextPoint(nextPos)

  def getInterpolatedPointsSpline(self, sourceNode, points):

    # One spline for each direction.
    aSplineX = vtk.vtkCardinalSpline()
    aSplineY = vtk.vtkCardinalSpline()
    aSplineZ = vtk.vtkCardinalSpline()

    aSplineX.SetClosed(self.closed)
    aSplineY.SetClosed(self.closed)
    aSplineZ.SetClosed(self.closed)

    pos = [0.0, 0.0, 0.0]
    try:
      # Slicer-4.13 (February 2022) and later
      numberOfControlPoints = sourceNode.GetNumberOfControlPoints()
    except:
      # fall back to older API
      numberOfControlPoints = sourceNode.GetNumberOfFiducials()
    for i in range(0, numberOfControlPoints):
      try:
        # Current API (Slicer-4.13 February 2022)
        sourceNode.GetNthControlPointPosition(i, pos)
      except:
        # Legacy API
        sourceNode.GetNthFiducialPosition(i, pos)
      aSplineX.AddPoint(i, pos[0])
      aSplineY.AddPoint(i, pos[1])
      aSplineZ.AddPoint(i, pos[2])

    nInterpolatedPoints = self.numberOfIntermediatePoints*(numberOfControlPoints if self.closed else numberOfControlPoints-1)
    curveParameterRange = [0.0, 0.0]
    aSplineX.GetParametricRange(curveParameterRange)
    if self.closed:
      curveParameterRange[1] += 1.0 # for closed splines the parameter space is +1 (see vtkCardinalSpline documentation)

    curveParameter = curveParameterRange[0]
    curveParameterStep = (curveParameterRange[1]-curveParameterRange[0])/(nInterpolatedPoints-1)

    for nInterpolatedPointIndex in range(nInterpolatedPoints):
      points.InsertNextPoint(aSplineX.Evaluate(curveParameter), aSplineY.Evaluate(curveParameter), aSplineZ.Evaluate(curveParameter))
      curveParameter += curveParameterStep

  def updateCurve(self):

    if self.controlPointsMarkupNode and self.curveModelNode:

      self.curvePoints.Reset() # clear without deallocating memory
      lines = vtk.vtkCellArray()
      self.curvePoly.SetLines(lines)

      try:
        # Slicer-4.13 (February 2022) and later
        numberOfControlPoints = self.controlPointsMarkupNode.GetNumberOfControlPoints()
      except:
        # fall back to older API
        numberOfControlPoints = self.controlPointsMarkupNode.GetNumberOfFiducials()
      if numberOfControlPoints >= 2:
        self.pointInterpolationFunction(self.controlPointsMarkupNode, self.curvePoints)
        nInterpolatedPoints = self.curvePoints.GetNumberOfPoints()
        lines.InsertNextCell(nInterpolatedPoints)
        for i in range(nInterpolatedPoints):
          lines.InsertCellPoint(i)

      tubeFilter = vtk.vtkTubeFilter()
      tubeFilter.SetInputData(self.curvePoly)
      tubeFilter.SetRadius(self.tubeRadius)
      tubeFilter.SetNumberOfSides(self.tubeResolution)
      tubeFilter.SetCapping(not self.closed)

      # Triangulation is necessary to avoid discontinuous lines
      # in model/slice intersection display
      triangles = vtk.vtkTriangleFilter()
      triangles.SetInputConnection(tubeFilter.GetOutputPort())
      triangles.Update()

      self.curveModelNode.SetAndObservePolyData(triangles.GetOutput())
      self.curveModelNode.Modified()

  def getControlPointsAsArray(self):
    numberOfControlPoints = 0
    if self.controlPointsMarkupNode:
      try:
        # Slicer-4.13 (February 2022) and later
        numberOfControlPoints = self.controlPointsMarkupNode.GetNumberOfControlPoints()
      except:
        # fall back to older API
        numberOfControlPoints = self.controlPointsMarkupNode.GetNumberOfFiducials()
    points = np.zeros([3,numberOfControlPoints])
    pos = [0.0, 0.0, 0.0]
    for i in range(0, numberOfControlPoints):
      try:
        # Current API (Slicer-4.13 February 2022)
        self.controlPointsMarkupNode.GetNthControlPointPosition(i, pos)
      except:
        # Legacy API
        self.controlPointsMarkupNode.GetNthFiducialPosition(i, pos)
      points[0,i] = pos[0]
      points[1,i] = pos[1]
      points[2,i] = pos[2]
    return points

  def setControlPointsFromArray(self, controlPointsArray):
    try:
      # Current API (Slicer-4.13 February 2022)
      self.controlPointsMarkupNode.RemoveAllControlPoints()
    except:
      # Legacy API
      self.controlPointsMarkupNode.RemoveAllMarkups()
    wasModifying = self.controlPointsMarkupNode.StartModify()
    for controlPointPos in controlPointsArray.T:
      try:
        # Current API (Slicer-4.13 February 2022)
        fidIndex = self.controlPointsMarkupNode.AddControlPoint(controlPointPos)
        # Deselect it because usually only one markup point is selected
        self.controlPointsMarkupNode.SetNthControlPointSelected(fidIndex, False)
      except:
        # Legacy API
        fidIndex = self.controlPointsMarkupNode.AddFiducial(controlPointPos[0], controlPointPos[1], controlPointPos[2])
        # Deselect it because usually only one markup point is selected
        self.controlPointsMarkupNode.SetNthFiducialSelected(fidIndex, False)
    self.controlPointsMarkupNode.EndModify(wasModifying)

  def getInterpolatedPointsAsArray(self):
    n = self.curvePoints.GetNumberOfPoints()
    points = np.zeros([3,n])
    pos = [0.0, 0.0, 0.0]
    for i in range(n):
      self.curvePoints.GetPoint(i, pos)
      points[:,i] = pos
    return points

  def getCurveLength(self, numberOfCurvePoints = -1, startPointIndex = 0):
    """Get length of the curve or a section of the curve
    :param n: if specified then distances up to the first n points are computed
    :return: sum of distances between the curve points
    """
    pointIds = vtk.vtkIdList()
    self.curvePoly.GetLines().GetCell(0, pointIds)

    points = self.curvePoly.GetPoints()

    # Check if there is overlap between the first and last segments
    # if there is, then ignore the last segment (only needed for smooth spline
    # interpolation)
    totalNumberOfCurvePoints = pointIds.GetNumberOfIds()
    if totalNumberOfCurvePoints > 2:
      firstPoint = np.array(points.GetPoint(pointIds.GetId(0)))
      lastPoint = np.array(points.GetPoint(pointIds.GetId(totalNumberOfCurvePoints-2)))
      # Check distance between the first point and the second last point
      if np.linalg.norm(lastPoint-firstPoint) < 0.00001:
        totalNumberOfCurvePoints -= 1

    if numberOfCurvePoints<0 or startPointIndex+numberOfCurvePoints>totalNumberOfCurvePoints:
      numberOfCurvePoints = totalNumberOfCurvePoints-startPointIndex

    length = 0.0
    previousPoint = np.array(points.GetPoint(pointIds.GetId(startPointIndex)))
    for i in range(startPointIndex+1,startPointIndex+numberOfCurvePoints):
      nextPoint = np.array(points.GetPoint(pointIds.GetId(i)))
      length += np.linalg.norm(previousPoint - nextPoint)
      previousPoint = nextPoint

    return length

  def getCurveLengthBetweenStartEndPoints(self, startPointIndex, endPointIndex):
    """Distance along the curve between start and end point (in direction of increasing index).
    Assumes closed curve."""
    if startPointIndex < endPointIndex:
      curveSegmentLength = self.getCurveLength(endPointIndex - startPointIndex, startPointIndex)
    else:
      # wrap around
      curveSegmentLength = self.getCurveLength(endPointIndex, 0)  + self.getCurveLength(-1, startPointIndex)
    return curveSegmentLength

  def resampleCurve(self, controlPointDistance):

    interpolatedPoints = self.getSampledInterpolatedPointsAsArray(self.getInterpolatedPointsAsArray(), controlPointDistance)
    if interpolatedPoints.size == 0:
      logging.warning("resampleCurve failed: no points are available")
      return

    labels, positions = self.getControlPointLabels()
    self.setControlPointsFromArray(interpolatedPoints)
    self.setControlPointLabels(labels, positions)

  def getSampledInterpolatedPointsAsArray(self, curvePoints, samplingDistance, closedCurve=True):
    """Returns points as column vectors. Samples points along a polyline at equal distances."""
    if curvePoints.size == 0:
      return []
    assert samplingDistance > 0, "Sampling Distance <= 0.0 is not valid"
    assert (curvePoints.shape[0]==3), "curvePoints number of rows is expected to be 3"
    distanceFromLastSampledPoint=0
    previousCurvePoint = curvePoints[:,0]
    sampledPoints = previousCurvePoint
    for currentCurvePoint in curvePoints.T:
      segmentLength = np.linalg.norm(currentCurvePoint-previousCurvePoint)
      if segmentLength == 0.0:
        continue
      remainingSegmentLength = distanceFromLastSampledPoint + segmentLength
      if remainingSegmentLength >= samplingDistance:
        segmentDirectionVector = (currentCurvePoint-previousCurvePoint)/segmentLength
        # distance of new sampled point from previous curve point
        distanceFromLastInterpolatedPoint = samplingDistance - distanceFromLastSampledPoint
        while remainingSegmentLength >= samplingDistance:
          newSampledPoint = previousCurvePoint + segmentDirectionVector * distanceFromLastInterpolatedPoint
          sampledPoints = np.vstack((sampledPoints,newSampledPoint))
          distanceFromLastSampledPoint = 0
          distanceFromLastInterpolatedPoint += samplingDistance
          remainingSegmentLength -= samplingDistance
        distanceFromLastSampledPoint = remainingSegmentLength
      else:
        distanceFromLastSampledPoint += segmentLength
      previousCurvePoint = currentCurvePoint.copy()

    # The last segment may be much shorter than all the others, which may introduce artifact in spline fitting.
    # To fix that, move the last point to have two equal segments at the end.
    if closedCurve and (sampledPoints.shape[0]>3):
      firstPoint = sampledPoints[0,:]
      secondLastPoint = sampledPoints[-2,:]
      lastPoint = sampledPoints[-1,:]
      lastTwoSegmentLength = np.linalg.norm(secondLastPoint-lastPoint)+np.linalg.norm(lastPoint-firstPoint)
      lastPoint = secondLastPoint + (lastPoint-secondLastPoint) * lastTwoSegmentLength/2 / np.linalg.norm(secondLastPoint-lastPoint)
      sampledPoints[-1,:] = lastPoint

    return sampledPoints.T

  def getSampledInterpolatedPointsBetweenStartEndPointsAsArray(self, interpolatedPoints, samplingDistance, startPointIndex, endPointIndex):
    """Returns points as column vectors. Samples points along a polyline at equal distances.
    Assumes closed curve."""
    if startPointIndex < endPointIndex:
      curveSegmentPoints = self.getInterpolatedPointsAsArray()[:,startPointIndex:endPointIndex+1]
    else:
      # wrap around
      curvePoints = self.getInterpolatedPointsAsArray()
      curveSegmentPoints = np.hstack((curvePoints[:, startPointIndex:],
                                       curvePoints[:, :endPointIndex]))

    sampledInterpolatedPoints = self.getSampledInterpolatedPointsAsArray(curveSegmentPoints, samplingDistance, closedCurve=False)
    return sampledInterpolatedPoints

  def smoothCurveFourier(self, numberOfFourierCoefficients, controlPointDistance):

    samplingDistance = 1.0 # Fourier-smoothed curve will be computed using this resolution
    interpolatedPoints = self.getSampledInterpolatedPointsAsArray(self.getInterpolatedPointsAsArray(), samplingDistance)
    if interpolatedPoints.size == 0:
      logging.warning("smoothCurveFourier failed: no points are available")
      return

    labels, positions = self.getControlPointLabels()

    smoothedInterpolatedPoints = np.zeros(interpolatedPoints.shape)

    numberOfInterpolatedPoints = interpolatedPoints.shape[1]

    paddingSize = int(numberOfInterpolatedPoints/2)
    # number of points are odd, therefore we need to remove a padding point to make it even (as ifft always returns an even number of points)
    reducedRightPadding = (numberOfInterpolatedPoints & 1) != 0

    for component in range(3):
      y = np.pad(interpolatedPoints[component,:],paddingSize, mode="wrap")
      if reducedRightPadding:
        y = y[:-1] # remove one padding element from the right
      w = np.fft.rfft(y)
      w[numberOfFourierCoefficients:] = 0 # truncate to first (numberOfFourierCoefficients) coefficients
      smoothedPoints = np.fft.irfft(w)
      if reducedRightPadding:
        smoothedInterpolatedPoints[component,:] = smoothedPoints[paddingSize:-(paddingSize-1)]
      else:
        smoothedInterpolatedPoints[component,:] = smoothedPoints[paddingSize:-paddingSize]

    controlPoints = self.getSampledInterpolatedPointsAsArray(smoothedInterpolatedPoints, controlPointDistance)

    self.setControlPointsFromArray(controlPoints)

    self.setControlPointLabels(labels, positions)

  def getControlPointLabels(self):
    """Save control point labels to a list of labels and positions"""
    try:
      # Slicer-4.13 (February 2022) and later
      numberOfControlPoints = self.controlPointsMarkupNode.GetNumberOfControlPoints()
    except:
      # fall back to older API
      numberOfControlPoints = self.controlPointsMarkupNode.GetNumberOfFiducials()
    labels = []
    positions = []
    for i in range(numberOfControlPoints):
      try:
        # Current API (Slicer-4.13 February 2022)
        label = self.controlPointsMarkupNode.GetNthControlPointLabel(i)
      except:
        # Legacy API
        label = self.controlPointsMarkupNode.GetNthFiducialLabel(i)
      if label:
        labels.append(label)
        position = np.array([0.0, 0.0, 0.0])
        try:
          # Current API (Slicer-4.13 February 2022)
          self.controlPointsMarkupNode.GetNthControlPointPosition(i, position)
        except:
          # Legacy API
          self.controlPointsMarkupNode.GetNthFiducialPosition(i, position)
        positions.append(position)
    return labels, positions

  def getClosestMarkupIndex(self, position):
    try:
      # Slicer-4.13 (February 2022) and later
      numberOfControlPoints = self.controlPointsMarkupNode.GetNumberOfControlPoints()
    except:
      # fall back to older API
      numberOfControlPoints = self.controlPointsMarkupNode.GetNumberOfFiducials()
    if numberOfControlPoints<=0:
      return -1
    markupPosition = np.array([0.0, 0.0, 0.0])
    try:
      # Current API (Slicer-4.13 February 2022)
      self.controlPointsMarkupNode.GetNthControlPointPosition(0, markupPosition)
    except:
      # Legacy API
      self.controlPointsMarkupNode.GetNthFiducialPosition(0, markupPosition)
    nearestDistance = np.linalg.norm(markupPosition-position)
    nearestIndex = 0
    for i in range(1, numberOfControlPoints):
      try:
        # Current API (Slicer-4.13 February 2022)
        self.controlPointsMarkupNode.GetNthControlPointPosition(i, markupPosition)
      except:
        # Legacy API
        self.controlPointsMarkupNode.GetNthFiducialPosition(i, markupPosition)
      currentDistance = np.linalg.norm(markupPosition-position)
      if currentDistance<nearestDistance:
        nearestDistance = currentDistance
        nearestIndex = i
    return nearestIndex

  def setControlPointLabels(self, labels, positions):
    """Restore control point labels from a list of labels and positions"""
    wasModifying = self.controlPointsMarkupNode.StartModify()
    for label, position in zip(labels, positions):
      markupIndex = self.getClosestMarkupIndex(position)
      if markupIndex>=0:
        try:
          # Current API (Slicer-4.13 February 2022)
          self.controlPointsMarkupNode.SetNthControlPointLabel(markupIndex, label)
        except:
          # Legacy API
          self.controlPointsMarkupNode.SetNthFiducialLabel(markupIndex, label)
    self.controlPointsMarkupNode.EndModify(wasModifying)

  def getClosestPoint(self, point):
    self.curvePointsLocator.BuildLocator()
    closestPointId = self.curvePointsLocator.FindClosestPoint(point)
    closestPoint = [0.0, 0.0, 0.0]
    self.curvePoints.GetPoint(closestPointId, closestPoint)
    return [closestPoint, closestPointId]

  def getCurvePointIndexFromControlPointIndex(self, controlPointIndex):
    return controlPointIndex * self.numberOfIntermediatePoints + 1

  def getDirectionVector(self, pointId):
    """Get direction vector at specified point index.
    :param pointId point index returned by getClosestPoint
    :return None if there was an error, direction vector of the curve at that position
    """

    if self.curvePoints.GetNumberOfPoints()<2:
      return None

    # Point is at the end of the line
    if pointId <= 0:
      pointPos = np.array(self.curvePoints.GetPoint(0))
      pointPosAfter = np.array(self.curvePoints.GetPoint(1))
      directionVector = (pointPosAfter - pointPos) / np.linalg.norm(pointPosAfter - pointPos)
      return directionVector
    if pointId >= self.curvePoints.GetNumberOfPoints()-1:
      pointPos = np.array(self.curvePoints.GetPoint(self.curvePoints.GetNumberOfPoints()-2))
      pointPosAfter = np.array(self.curvePoints.GetPoint(self.curvePoints.GetNumberOfPoints()-1))
      directionVector = (pointPosAfter - pointPos) / np.linalg.norm(pointPosAfter - pointPos)
      return directionVector

    # point is along the line, compute direction as the average of
    # direction before and after the line
    pointPosBefore = np.array(self.curvePoints.GetPoint(pointId-1))
    pointPos = np.array(self.curvePoints.GetPoint(pointId))
    pointPosAfter = np.array(self.curvePoints.GetPoint(pointId+1))
    directionVectorBefore = (pointPos - pointPosBefore) / np.linalg.norm(pointPos - pointPosBefore)
    directionVectorAfter = (pointPosAfter - pointPos) / np.linalg.norm(pointPosAfter - pointPos)
    directionVector = (directionVectorBefore + directionVectorAfter) / np.linalg.norm(directionVectorBefore + directionVectorAfter)

    return directionVector

  def getFarthestPoint(self, refPoint):
    """Get position of the farthest point on the curve from the specified reference point.
    Distance is Euclidean distance, not distance along the curve.
    :param refPoint: reference point position
    :return: position and ID of the farthest curve point from refPoint
    """
    points = self.curvePoly.GetPoints()
    farthestPoint = np.array(points.GetPoint(0))
    farthestPointDistance = np.linalg.norm(refPoint - farthestPoint)
    farthestPointId = 0

    n = points.GetNumberOfPoints()
    for i in range(1,n):
      nextPoint = np.array(points.GetPoint(i))
      nextPointDistance = np.linalg.norm(nextPoint - refPoint)
      if nextPointDistance>farthestPointDistance:
        farthestPoint = nextPoint
        farthestPointDistance = nextPointDistance
        farthestPointId = i

    return [farthestPoint, farthestPointId]

  def getPointAlongCurve(self, distanceFromRefPoint, refPointId = 0):
    """Get position of a curve point along the curve relative to the specified reference point index
    :param distanceFromRefPoint: distance from the first point
    :return: position of the point found at the given distance
    """
    points = self.curvePoints
    if refPointId<0 or refPointId>=points.GetNumberOfPoints():
      raise ValueError('refPointId '+str(refPointId)+' is out of range')

    idIncrement = 1 if distanceFromRefPoint>=0 else -1
    remainingDistanceFromRefPoint = abs(distanceFromRefPoint)
    point = np.array(points.GetPoint(refPointId))
    pointId = refPointId
    n = points.GetNumberOfPoints()
    while remainingDistanceFromRefPoint>0:
      pointId += idIncrement
      # wrap around for closed curve, terminate search for open curve if reach the end
      if pointId<0:
        if self.closed:
          pointId = n
          continue
        else:
          return 0
      elif pointId>=n:
        if self.closed:
          pointId = -1
          continue
        else:
          return n-1
      # determine how much closer we are now
      nextPoint = np.array(points.GetPoint(pointId))
      remainingDistanceFromRefPoint -= np.linalg.norm(nextPoint - point)
      point = nextPoint

    return point

  def getPointsOnPlane(self, planePosition, planeNormal):
    plane = vtk.vtkPlane()
    plane.SetOrigin(planePosition)
    plane.SetNormal(planeNormal)
    cutEdges = vtk.vtkCutter()
    cutEdges.SetInputData(self.curvePoly)
    cutEdges.SetCutFunction(plane)
    cutEdges.GenerateCutScalarsOff()
    cutEdges.SetValue(0, 0)
    cutEdges.Update()
    intersection = cutEdges.GetOutput()
    intersectionPoints = intersection.GetPoints()
    n = intersectionPoints.GetNumberOfPoints()
    points = np.zeros([3,n])
    pos = [0.0, 0.0, 0.0]
    for i in range(n):
      intersectionPoints.GetPoint(i, pos)
      points[:,i] = pos
    return points
