#
#   Utility methods for interfacing with Slicer
#


class Signal:

  def __init__(self):
    self._slots = set()

  def connect(self, slot):
    if callable(slot):
      self._slots.add(slot)
    else:
      raise ValueError("The provided argument is not a callable")

  def disconnect(self, slot):
    if slot in self._slots:
      self._slots.remove(slot)

  def disconnectAll(self):
    self._slots = set()

  def emit(self, *args):
    for slot in self._slots:
      slot(*args)


def reload(packageName, submoduleNames):
  import imp
  f, filename, description = imp.find_module(packageName)
  package = imp.load_module(packageName, f, filename, description)
  for submoduleName in submoduleNames:
    f, filename, description = imp.find_module(submoduleName, package.__path__)
    try:
      imp.load_module(packageName + '.' + submoduleName, f, filename, description)
    finally:
      f.close()


def timer(func):
  """ This decorator can be used for profiling a method/function by printing the elapsed time after execution.
  """
  def _new_function(*args, **kwargs):
    import time
    startTime = time.time()
    x = func(*args, **kwargs)
    duration = time.time() - startTime
    print(f"{func.__name__} ran in: {duration:.2f} seconds")
    return x

  return _new_function


def setAllControlPointsVisibility(markupsNode, visible):
  wasModify = markupsNode.StartModify()
  for ptIdx in range(markupsNode.GetNumberOfControlPoints()):
    markupsNode.SetNthControlPointVisibility(ptIdx, visible)
  markupsNode.EndModify(wasModify)


def getPointsOnPlane(planePosition, planeNormal, curvePoly):
  import vtk
  import numpy as np
  plane = vtk.vtkPlane()
  plane.SetOrigin(planePosition)
  plane.SetNormal(planeNormal)
  cutEdges = vtk.vtkCutter()
  cutEdges.SetInputData(curvePoly)
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


def createPolyDataFromPointArray(pointArray):
  """Create vtkPolyData from a numpy array. Performs deep copy."""

  import vtk
  number_of_points = pointArray.shape[0]
  # Points
  points = vtk.vtkPoints()
  points.SetNumberOfPoints(number_of_points)
  import vtk.util.numpy_support
  pointArrayDestination = vtk.util.numpy_support.vtk_to_numpy(points.GetData())
  pointArrayDestination[:] = pointArray[:]
  # Vertices
  vertices = vtk.vtkCellArray()
  for i in range(number_of_points):
    vertices.InsertNextCell(1)
    vertices.InsertCellPoint(i)
  # PolyData
  polyData = vtk.vtkPolyData()
  polyData.SetPoints(points)
  polyData.SetVerts(vertices)
  return polyData


def getPointArrayFromPolyData(polyData):
  """Return point coordinates of a vtkPolyData object as a numpy array. Performs shallow copy."""

  import vtk.util.numpy_support
  pointArray = vtk.util.numpy_support.vtk_to_numpy(polyData.GetPoints().GetData())
  return pointArray


def createPointModelFromPointArray(pointArray, visible = True, color = None):
  """Create and display a MRML model node from a numpy array
  that contains 3D point coordinates, by showing a vertex at each point."""

  import slicer
  modelNode = slicer.modules.models.logic().AddModel(createPolyDataFromPointArray(pointArray))
  if color is not None:
    modelNode.GetDisplayNode().SetColor(color)
  modelNode.GetDisplayNode().SetVisibility(1 if visible else 0)
  return modelNode


def createTubeModelFromPointArray(pointArray, loop=True, visible=True, color=None, radius=None, name=None,
                                  keepGeneratorNodes=False):
  """Create and display a MRML model node from a numpy array
  that contains 3D point coordinates, by showing a tube model that connects all points."""

  import slicer
  pointModelNode = createPointModelFromPointArray(pointArray, color)
  tubeModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")
  tubeModelNode.CreateDefaultDisplayNodes()
  if color is not None:
    tubeModelNode.GetDisplayNode().SetColor(color)
  pointModelNode.GetDisplayNode().SetVisibility(0)
  tubeModelNode.GetDisplayNode().SetVisibility(1 if visible else 0)
  markupsToModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsToModelNode")
  if markupsToModelNode is None:
    raise AttributeError("MarkupsToModel extension was not found. Please install MarkupsToModel extension.")
  markupsToModelNode.SetModelType(markupsToModelNode.Curve)
  markupsToModelNode.SetTubeLoop(loop)
  if radius is not None:
    markupsToModelNode.SetTubeRadius(radius)
  markupsToModelNode.SetAndObserveOutputModelNodeID(tubeModelNode.GetID())
  markupsToModelNode.SetAndObserveInputNodeID(pointModelNode.GetID())
  if name is not None:
    tubeModelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name+" curve"))
    pointModelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name+" points"))
    markupsToModelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name+" generator"))
  if keepGeneratorNodes:
    return tubeModelNode, pointModelNode, markupsToModelNode
  else:
    slicer.mrmlScene.RemoveNode(markupsToModelNode)
    slicer.mrmlScene.RemoveNode(pointModelNode.GetDisplayNode())
    slicer.mrmlScene.RemoveNode(pointModelNode)
    return [tubeModelNode]


def smoothCurveFourier(markupsNode, numberOfFourierCoefficients, controlPointDistance):
  import logging
  import slicer
  interpolatedPoints = slicer.util.arrayFromMarkupsCurvePoints(markupsNode).T

  samplingDistance = 1.0 # Fourier-smoothed curve will be computed using this resolution
  interpolatedPoints = getSampledInterpolatedPointsAsArray(interpolatedPoints, samplingDistance)
  if len(interpolatedPoints) == 0:
    logging.warning("smoothCurveFourier failed: no points are available")
    return

  labels, positions = getControlPointLabels(markupsNode)

  import numpy as np
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

  controlPoints = getSampledInterpolatedPointsAsArray(smoothedInterpolatedPoints, controlPointDistance)

  slicer.util.updateMarkupsControlPointsFromArray(markupsNode, controlPoints.T)
  setControlPointLabels(markupsNode, labels, positions)


def getSampledInterpolatedPointsAsArray(curvePoints, samplingDistance, closedCurve=True):
  """Returns points as column vectors. Samples points along a polyline at equal distances."""
  import numpy as np
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


def getSampledInterpolatedPointsBetweenStartEndPointsAsArray(interpolatedPoints, samplingDistance, startPointIndex, endPointIndex):
  """Returns points as column vectors. Samples points along a polyline at equal distances.
  Assumes closed curve."""
  import numpy as np
  if startPointIndex < endPointIndex:
    curveSegmentPoints = interpolatedPoints[:,startPointIndex:endPointIndex+1]
  else:
    # wrap around
    curvePoints = interpolatedPoints
    curveSegmentPoints = np.hstack((curvePoints[:, startPointIndex:],
                                     curvePoints[:, :endPointIndex]))

  sampledInterpolatedPoints = \
    getSampledInterpolatedPointsAsArray(curveSegmentPoints, samplingDistance, closedCurve=False)
  return sampledInterpolatedPoints


def getControlPointLabels(markupsNode):
  """Save control point labels to a list of labels and positions"""
  import numpy as np
  try:
    # Slicer-4.13 (February 2022) and later
    numberOfControlPoints = markupsNode.GetNumberOfControlPoints()
  except:
    # fall back to older API
    numberOfControlPoints = markupsNode.GetNumberOfFiducials()
  labels = []
  positions = []
  for i in range(numberOfControlPoints):
    try:
      # Current API (Slicer-4.13 February 2022)
      label = markupsNode.GetNthControlPointLabel(i)
    except:
      # Legacy API
      label = markupsNode.GetNthFiducialLabel(i)
    if label:
      labels.append(label)
      position = np.array([0.0, 0.0, 0.0])
      try:
        # Current API (Slicer-4.13 February 2022)
        markupsNode.GetNthControlPointPosition(i, position)
      except:
        # Legacy API
        markupsNode.GetNthFiducialPosition(i, position)
      positions.append(position)
  return labels, positions


def setControlPointLabels(markupsNode, labels, positions):
  """Restore control point labels from a list of labels and positions"""
  wasModifying = markupsNode.StartModify()
  for label, position in zip(labels, positions):
    markupIndex = markupsNode.GetClosestControlPointIndexToPositionWorld(position)
    if markupIndex>=0:
      try:
        # Current API (Slicer-4.13 February 2022)
        markupsNode.SetNthControlPointLabel(markupIndex, label)
      except:
        # Legacy API
        markupsNode.SetNthFiducialLabel(markupIndex, label)
  markupsNode.EndModify(wasModifying)


def toLocalCoordinates(node, posWorld):
  import numpy as np
  posLocal = np.zeros(3)
  node.TransformPointFromWorld(posWorld, posLocal)
  return posLocal


def toWorldCoordinates(node, posLocal):
  import numpy as np
  posWorld = np.zeros(3)
  node.TransformPointToWorld(posLocal, posWorld)
  return posWorld


def getClosestCurvePointIndexToPosition(markupsCurveNode, position):
  return markupsCurveNode.GetClosestCurvePointIndexToPositionWorld(
    toWorldCoordinates(markupsCurveNode, position)
  )

def getClosestControlPointIndexToPositionWorld(markupsCurveNode, position):
  return markupsCurveNode.GetClosestControlPointIndexToPositionWorld(
    toWorldCoordinates(markupsCurveNode, position)
  )


def getFarthestCurvePointIndexToPosition(markupsCurveNode, position):
  import numpy as np
  curvePointId =\
    markupsCurveNode.GetFarthestCurvePointIndexToPositionWorld(toWorldCoordinates(markupsCurveNode, position))
  farthestPointPosition = np.array(markupsCurveNode.GetCurve().GetPoint(curvePointId))
  return farthestPointPosition


def getClosestPointPositionAlongCurve(markupsCurveNode, position):
  import numpy as np
  closestPointPosition = np.zeros(3)
  markupsCurveNode.GetClosestPointPositionAlongCurveWorld(
    toWorldCoordinates(markupsCurveNode, position),
    closestPointPosition)
  return toLocalCoordinates(markupsCurveNode, closestPointPosition)


def getPositionAlongCurve(markupsCurveNode, startCurvePointId, distanceFromStartPoint):
  import numpy as np
  pointPosition = np.zeros(3)
  markupsCurveNode.GetPositionAlongCurveWorld(pointPosition, startCurvePointId, distanceFromStartPoint)
  return toLocalCoordinates(markupsCurveNode, pointPosition)


def getAllSegmentIDs(segmentationNode):
  import vtk
  segmentIDs = vtk.vtkStringArray()
  segmentation = segmentationNode.GetSegmentation()
  segmentation.GetSegmentIDs(segmentIDs)
  return [segmentIDs.GetValue(idx) for idx in range(segmentIDs.GetNumberOfValues())]


def createMatrixFromString(transformMatrixString):
  import vtk
  transformMatrix = vtk.vtkMatrix4x4()
  transformMatrixArray = list(map(float, filter(None, transformMatrixString.split(' '))))
  for r in range(4):
    for c in range(4):
      transformMatrix.SetElement(r, c, transformMatrixArray[r * 4 + c])
  return transformMatrix
