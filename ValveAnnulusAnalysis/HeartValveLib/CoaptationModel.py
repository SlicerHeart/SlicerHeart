#
#   CoaptationModel.py: Stores leaflet coaptation data, quantifies properties, and creates displayable models
#

import vtk, slicer
import numpy as np
import logging
import HeartValveLib
import SmoothCurve
import operator


class CoaptationModel:

  def __init__(self):
    self.markupGlyphScale = 1.0
    self.baseLine = SmoothCurve.SmoothCurve()
    self.baseLine.setTubeRadius(self.markupGlyphScale/6.0)
    self.baseLine.setInterpolationMethod(HeartValveLib.SmoothCurve.InterpolationSpline)
    self.marginLine = SmoothCurve.SmoothCurve()
    self.marginLine.setTubeRadius(self.markupGlyphScale/6.0)
    self.marginLine.setInterpolationMethod(HeartValveLib.SmoothCurve.InterpolationSpline)
    self.surfaceModelNode = None
    self.segmentationNode = None

  def getName(self, valveModel):
    return "Coaptation {}".format(" - ".join(self.getConnectedLeafletsNames(valveModel)))

  def updateSurfaceModelName(self, valveModel):
    """ SubjectHierarchy items don't get updated after changing name or visibility of the underlying mrml node. Using
    a workaround for now until moving to a Slicer version > 4.10.0

    This issue has been fixed with Slicer/Slicer@767b807
    TODO: Replace workaround once using Slicer version > 4.10.0
    """
    try:
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      shNode.SetItemName(shNode.GetItemByDataNode(self.surfaceModelNode),
                         self.getName(valveModel))
    except ValueError as exc:
      logging.warning("Could not get connected leaflet names: %s\nReason could be missing leaflet surface boundary points"
                   % str(exc))

  def setSurfaceModelNode(self, surfaceModelNode):
    self.surfaceModelNode = surfaceModelNode
    self.updateSurface()

  def setBaseLineMarkupNode(self, baseLineMarkupNode):
    self.baseLine.setControlPointsMarkupNode(baseLineMarkupNode)
    self.updateSurface()

  def getBaseLineMarkupNode(self):
    return self.baseLine.controlPointsMarkupNode

  def setBaseLineModelNode(self, baseLineModelNode):
    self.baseLine.setCurveModelNode(baseLineModelNode)

  def getBaseLineModelNode(self):
    return self.baseLine.curveModelNode

  def setMarginLineMarkupNode(self, marginLineMarkupNode):
    self.marginLine.setControlPointsMarkupNode(marginLineMarkupNode)
    self.updateSurface()

  def getMarginLineMarkupNode(self):
    return self.marginLine.controlPointsMarkupNode

  def setMarginLineModelNode(self, marginLineModelNode):
    self.marginLine.setCurveModelNode(marginLineModelNode)

  def getMarginLineModelNode(self):
    return self.marginLine.curveModelNode

  def updateSurface(self):
    self.baseLine.updateCurve()
    self.marginLine.updateCurve()
    self.computeSurfaceBetweenLines()

  def getValvePlanePosition(self):
    arrayAsString = self.baseLine.controlPointsMarkupNode.GetAttribute("ValvePlanePosition")
    if not arrayAsString:
      return None
    # for example: arrayAsString = "0.32 0.45 0.11"
    return [float(x) for x in arrayAsString.split(' ')]

  def setValvePlanePosition(self, valvePlanePosition):
    if valvePlanePosition is None:
      self.baseLine.controlPointsMarkupNode.RemoveAttribute("ValvePlanePosition")
    else:
      arrayAsString = ' '.join([str(x) for x in valvePlanePosition])
      self.baseLine.controlPointsMarkupNode.SetAttribute("ValvePlanePosition", arrayAsString)

  def getValvePlaneNormal(self):
    arrayAsString = self.baseLine.controlPointsMarkupNode.GetAttribute("ValvePlaneNormal")
    if not arrayAsString:
      return None
    # for example: arrayAsString = "0.32 0.45 0.11"
    return np.array([float(x) for x in arrayAsString.split(' ')])

  def setValvePlaneNormal(self, valvePlaneNormal):
    if valvePlaneNormal is None:
      self.baseLine.controlPointsMarkupNode.RemoveAttribute("ValvePlaneNormal")
    else:
      arrayAsString = ' '.join([str(x) for x in valvePlaneNormal])
      self.baseLine.controlPointsMarkupNode.SetAttribute("ValvePlaneNormal", arrayAsString)

  def computeSurfaceBetweenLines(self):
    """
    Update model with a surface between base and margin lines.
    """

    numberOfBasePoints = self.baseLine.curvePoints.GetNumberOfPoints()
    numberOfMarginPoints = self.marginLine.curvePoints.GetNumberOfPoints()
    if numberOfBasePoints==0 or numberOfMarginPoints==0:
      self.surfaceModelNode.SetAndObservePolyData(None)
      return

    boundaryPoints = vtk.vtkPoints()
    boundaryPoints.DeepCopy(self.baseLine.curvePoints)
    boundaryPoints.InsertPoints(numberOfBasePoints, numberOfMarginPoints, 0, self.marginLine.curvePoints)

    # Add a triangle strip between the base and margin lines
    strips = vtk.vtkCellArray()
    strips.InsertNextCell(numberOfBasePoints*2)
    basePointToMarginPointScale = float(numberOfMarginPoints) / float(numberOfBasePoints)
    for basePointIndex in range(numberOfBasePoints):
      strips.InsertCellPoint(basePointIndex)
      strips.InsertCellPoint(int(numberOfBasePoints+basePointIndex*basePointToMarginPointScale))

    clippingSurfacePolyData = vtk.vtkPolyData()
    clippingSurfacePolyData.SetPoints(boundaryPoints)
    clippingSurfacePolyData.SetStrips(strips)

    triangulator = vtk.vtkTriangleFilter()
    triangulator.SetInputData(clippingSurfacePolyData)
    triangulator.Update()

    clippingPolyData = triangulator.GetOutput()

    self.surfaceModelNode.SetAndObservePolyData(clippingPolyData)

  def getBaseLineMarginLineDistances(self):
    """
    Using closest distance of margin line from base line points.
    Distances between two lines are not symmetric (closest distance of margin line from base line points is not the
    same as closest distance of base line from margin line points).
    """

    numberOfBasePoints = self.baseLine.curvePoints.GetNumberOfPoints()
    numberOfMarginPoints = self.marginLine.curvePoints.GetNumberOfPoints()
    if numberOfBasePoints==0 or numberOfMarginPoints==0:
      self.surfaceModelNode.SetAndObservePolyData(None)
      return None

    basePoints = self.baseLine.curvePoly.GetPoints()

    def getDistance(index):
      closestPoint, _ = self.marginLine.getClosestPoint(basePoints.GetPoint(index))
      return np.linalg.norm(np.array(basePoints.GetPoint(index)) - np.array(closestPoint))

    return np.array([getDistance(i) for i in range(basePoints.GetNumberOfPoints())])

  def getConnectedLeafletsNames(self, valveModel):
    connectedLeaflets = self.getConnectedLeaflets(valveModel)
    connectedLeaflets = map(lambda l: l.getName().replace("leaflet", "").strip(), connectedLeaflets)
    return sorted(connectedLeaflets)

  def getConnectedLeaflets(self, valveModel):
    basePoints = self.baseLine.curvePoly.GetPoints()
    numberOfBasePoints = basePoints.GetNumberOfPoints()
    if not numberOfBasePoints:
      return []
    medianCoaptationPoint = basePoints.GetPoint(int(numberOfBasePoints / 2))
    connectedLeaflets = {}
    for leaflet in valveModel.leafletModels:
      leafletBoundaryPoints = leaflet.surfaceBoundary.curvePoly.GetPoints()
      if leafletBoundaryPoints.GetNumberOfPoints() == 0:
        continue
      connectedLeaflets[leaflet] = \
        np.min([np.linalg.norm(np.array(medianCoaptationPoint) - np.array(leafletBoundaryPoints.GetPoint(i)))
                for i in range(leafletBoundaryPoints.GetNumberOfPoints())])
    connectedLeaflets = sorted(connectedLeaflets.items(), key=operator.itemgetter(1))[:2]
    return list(map(lambda c: c[0], connectedLeaflets))