#
#   ValveRoi.py: Creates a region of interest around an annulus contour
#

import vtk, qt, ctk, slicer
import math
import numpy as np
import logging
import HeartValveLib

class ValveRoi:
  """
  Cylindrical ROI that can be used for clipping an image.
  Full valve mode: self.annulusContourCurve is set.
  Leaflet mode:
  """

  PARAM_SCALE = "ValveRoiScale"
  PARAM_TOP_DISTANCE = "ValveRoiTopDistance"
  PARAM_TOP_SCALE = "ValveRoiTopScale"
  PARAM_BOTTOM_DISTANCE = "ValveRoiBottomDistance"
  PARAM_BOTTOM_SCALE = "ValveRoiBottomScale"

  GEOMETRY_PARAMS = [PARAM_SCALE, PARAM_TOP_DISTANCE, PARAM_TOP_SCALE, PARAM_BOTTOM_DISTANCE, PARAM_BOTTOM_SCALE]

  def __init__(self):
    # Full valve mode
    self.annulusContourCurve = None
    # Leaflet mode
    self.valveModel = None
    self.leafletSegmentId = None

    self.roiModelNode = None

  def setRoiModelNode(self, destination):
    self.roiModelNode = destination

    # initialize with defaults
    if self.roiModelNode:
      if not self.roiModelNode.GetAttribute(self.PARAM_SCALE):
        self.roiModelNode.SetAttribute(self.PARAM_SCALE, "120")
      if not self.roiModelNode.GetAttribute(self.PARAM_TOP_DISTANCE):
        self.roiModelNode.SetAttribute(self.PARAM_TOP_DISTANCE, "10")
      if not self.roiModelNode.GetAttribute(self.PARAM_TOP_SCALE):
        self.roiModelNode.SetAttribute(self.PARAM_TOP_SCALE, "50")
      if not self.roiModelNode.GetAttribute(self.PARAM_BOTTOM_DISTANCE):
        self.roiModelNode.SetAttribute(self.PARAM_BOTTOM_DISTANCE, "30")
      if not self.roiModelNode.GetAttribute(self.PARAM_BOTTOM_SCALE):
        self.roiModelNode.SetAttribute(self.PARAM_BOTTOM_SCALE, "50")

    self.updateRoi()

  def setAnnulusContourCurve(self, source):
    self.annulusContourCurve = source
    self.valveModel = None
    self.leafletSegmentId = None
    self.updateRoi()

  def setLeaflet(self, valveModel, leafletSegmentId):
    self.valveModel = valveModel
    self.leafletSegmentId = leafletSegmentId
    self.annululusContourCurve = None
    self.updateRoi()

  def getLeafletBoundary(self):
    """
    Get leaflet boundary by concatenating coaptation baselines and annulus contour segment.
    :return: numpy array of point coordinates of leaflet boundary points
    """

    # find bordering coaptation baselines
    self.valveModel.updateCoaptationModels()
    leafletModel = self.valveModel.findLeafletModel(self.leafletSegmentId)
    if leafletModel is None:
      logging.debug("Cannot get leaflet boundary for segment " + self.leafletSegmentId + ": empty segment")
      return None
    leafletSurfaceModelNodeSource = leafletModel.surfaceModelNode
    if (leafletSurfaceModelNodeSource is None
        or leafletSurfaceModelNodeSource.GetPolyData() is None
        or leafletSurfaceModelNodeSource.GetPolyData().GetNumberOfPoints() == 0):
      logging.debug("Cannot get leaflet boundary for segment " + self.leafletSegmentId + ": surface is not extracted")
      return None
    leafletSurfacePolyData = leafletSurfaceModelNodeSource.GetPolyData()

    maxDistanceOfBoundaryPoint = self.valveModel.getAnnulusContourRadius() * 2.0

    closestPointFinder = vtk.vtkImplicitPolyDataDistance()
    closestPointFinder.SetInput(leafletSurfacePolyData)
    boundaryCoaptationModels = []
    for coaptationModel in self.valveModel.coaptationModels:
      boundaryPoints = coaptationModel.baseLine.getControlPointsAsArray()
      numberOfPoints = boundaryPoints.shape[1]
      numberOfBoundaryPoints = 0
      for pointIndex in range(numberOfPoints):
        point1Pos = boundaryPoints[:,pointIndex]
        point2Pos = [0, 0, 0]
        closestPointDistance = closestPointFinder.EvaluateFunctionAndGetClosestPoint(point1Pos, point2Pos)
        if abs(closestPointDistance) < maxDistanceOfBoundaryPoint:
          numberOfBoundaryPoints += 1
      if numberOfPoints and float(numberOfBoundaryPoints)/float(numberOfPoints) > 0.75:
        # If at least 75% of points are near the leaflet surface then we consider this coaptation line
        # as a boundary of this leaflet.
        boundaryCoaptationModels.append(coaptationModel)

    leafletBoundaryPoints = None

    if boundaryCoaptationModels:

      # We have now a list of boundary curves.
      # They have to be concatenated into a single curve (leafletBoundaryPoints).

      coaptationModel = boundaryCoaptationModels.pop()
      leafletBoundaryPoints = coaptationModel.baseLine.getInterpolatedPointsAsArray()

      while boundaryCoaptationModels:

        # find closest continuation
        closestCoaptationModelIndex = -1
        closestDistance = 0
        append = False # append or prepend
        reverseOrder = False # need to reverse the order before append or prepend
        for (coaptationModelIndex, coaptationModel) in enumerate(boundaryCoaptationModels):
          boundaryPoints = coaptationModel.baseLine.getControlPointsAsArray()
          closestDistanceAppendForward = np.linalg.norm(leafletBoundaryPoints[:,-1]-boundaryPoints[:,0])
          closestDistanceAppendReverse = np.linalg.norm(leafletBoundaryPoints[:, -1]-boundaryPoints[:, -1])
          closestDistancePrependForward = np.linalg.norm(boundaryPoints[:, -1]-leafletBoundaryPoints[:, 0])
          closestDistancePrependReverse = np.linalg.norm(boundaryPoints[:, 0]-leafletBoundaryPoints[:, 0])
          if closestDistanceAppendForward < closestDistance or closestCoaptationModelIndex < 0:
            closestCoaptationModelIndex = coaptationModelIndex
            closestDistance = closestDistanceAppendForward
            append = True
            reverseOrder = False
          if closestDistanceAppendReverse < closestDistance:
            closestCoaptationModelIndex = coaptationModelIndex
            closestDistance = closestDistanceAppendReverse
            append = True
            reverseOrder = True
          if closestDistancePrependForward < closestDistance:
            closestCoaptationModelIndex = coaptationModelIndex
            closestDistance = closestDistancePrependForward
            append = False
            reverseOrder = False
          if closestDistancePrependReverse < closestDistance:
            closestCoaptationModelIndex = coaptationModelIndex
            closestDistance = closestDistancePrependReverse
            append = False
            reverseOrder = True

        # append best matching curve
        boundaryPoints = boundaryCoaptationModels[closestCoaptationModelIndex].baseLine.getInterpolatedPointsAsArray()
        if reverseOrder:
          boundaryPoints = np.fliplr(boundaryPoints)
        if append:
          leafletBoundaryPoints = np.hstack([leafletBoundaryPoints, boundaryPoints])
        else:
          leafletBoundaryPoints = np.hstack([boundaryPoints, leafletBoundaryPoints])

        del boundaryCoaptationModels[closestCoaptationModelIndex]

    if leafletBoundaryPoints is None:
      logging.debug("Cannot get leaflet boundary for segment " + self.leafletSegmentId
                    + ": no matching coaptation lines found near the leaflet boundary")
      return None

    ## Get annulus contour segment and append it to the leafletBoundaryPoints to create a closed curve

    # Find out if the segment is between (when going in increasing point index direction)
    # or outside the two intersection points.
    annulusContour = self.valveModel.annulusContourCurve
    [annulusContourStartPoint, annulusContourStartPointId] = annulusContour.getClosestPoint(leafletBoundaryPoints[:,0])
    [annulusContourEndPoint, annulusContourEndPointId] = annulusContour.getClosestPoint(leafletBoundaryPoints[:, -1])
    # midPointIndexForward: index between start/end point if we go forward (from low index to high index)
    midPointBetweenId = int((annulusContourStartPointId+annulusContourEndPointId)/2)
    # midPointIndexReverse: index between start/end point if we go backwards (from high index to low index)
    midPointOutsideId = int(max(annulusContourStartPointId, annulusContourEndPointId)
                            + (annulusContour.curvePoints.GetNumberOfPoints()-abs(annulusContourStartPointId-annulusContourEndPointId))/2)
    midPointOutsideId = midPointOutsideId % annulusContour.curvePoints.GetNumberOfPoints()

    midPointBetween = [0.0, 0.0, 0.0]
    annulusContour.curvePoints.GetPoint(midPointBetweenId, midPointBetween)
    midPointOutside = [0.0, 0.0, 0.0]
    annulusContour.curvePoints.GetPoint(midPointOutsideId, midPointOutside)

    closestPoint = [0, 0, 0]
    midPointBetweenDistance = closestPointFinder.EvaluateFunctionAndGetClosestPoint(midPointBetween, closestPoint)
    midPointOutsideDistance = closestPointFinder.EvaluateFunctionAndGetClosestPoint(midPointOutside, closestPoint)

    if midPointBetweenDistance < midPointOutsideDistance:
      # get points between start/end
      annulusContourPoints = annulusContour.getInterpolatedPointsAsArray()
      annulusContourSegmentPoints = annulusContourPoints[:,min(annulusContourStartPointId,annulusContourEndPointId):
                                                           max(annulusContourStartPointId, annulusContourEndPointId)]
    else:
      # get points outside start/end
      annulusContourPoints = annulusContour.getInterpolatedPointsAsArray()
      annulusContourSegmentPoints1 = annulusContourPoints[:, max(annulusContourStartPointId,annulusContourEndPointId):-1]
      annulusContourSegmentPoints2 = annulusContourPoints[:, 0:min(annulusContourStartPointId,annulusContourEndPointId)]
      annulusContourSegmentPoints = np.hstack([annulusContourSegmentPoints1,annulusContourSegmentPoints2])

    # Append the annulus contour segment points (reorient it as needed)
    closestDistanceAppendForward = np.linalg.norm(leafletBoundaryPoints[:, -1] - annulusContourSegmentPoints[:, 0])
    closestDistanceAppendReverse = np.linalg.norm(leafletBoundaryPoints[:, -1] - annulusContourSegmentPoints[:, -1])
    if closestDistanceAppendReverse < closestDistanceAppendForward:
      annulusContourSegmentPoints = np.fliplr(annulusContourSegmentPoints)
    leafletBoundaryPoints = np.hstack([leafletBoundaryPoints, annulusContourSegmentPoints])

    return leafletBoundaryPoints

  def setRoiGeometry(self, params):
    wasModified = self.roiModelNode.StartModify()
    for paramName in self.GEOMETRY_PARAMS:
      self.roiModelNode.SetAttribute(paramName, str(params[paramName])) # 0-100
    self.roiModelNode.EndModify(wasModified)
    self.updateRoi() # this could be invoked automatically when the node is changed

  def getRoiGeometry(self):
    params = {}
    for paramName in self.GEOMETRY_PARAMS:
      params[paramName] = float(self.roiModelNode.GetAttribute(paramName))
    return params

  def updateRoi(self):
    if not self.roiModelNode:
      return

    numberOfContourPoints = 0
    annulusPoints = None
    planePosition = None
    planeNormal = None
    if self.annulusContourCurve:
      contourPoints = self.annulusContourCurve.curvePoints  # vtk.vtkPoints()
      numberOfContourPoints = contourPoints.GetNumberOfPoints()
      if numberOfContourPoints>0:
        annulusPoints = self.annulusContourCurve.getInterpolatedPointsAsArray()  # formerly contourPointsArray_Ras
        [planePosition, planeNormal] = HeartValveLib.planeFit(annulusPoints)
    elif self.valveModel is not None and self.leafletSegmentId is not None:
      annulusPoints = self.getLeafletBoundary()
      if annulusPoints is not None:
        numberOfContourPoints = annulusPoints.shape[1]
        [planePosition, planeNormal] = self.valveModel.getAnnulusContourPlane()

    if numberOfContourPoints <= 0:
      clippingPolyData = vtk.vtkPolyData()
      self.roiModelNode.SetAndObservePolyData(clippingPolyData)
      self.roiModelNode.Modified()
      return

    scale = float(self.roiModelNode.GetAttribute(self.PARAM_SCALE)) * 0.01
    topDistance = float(self.roiModelNode.GetAttribute(self.PARAM_TOP_DISTANCE))
    topScale = float(self.roiModelNode.GetAttribute(self.PARAM_TOP_SCALE)) * 0.01
    bottomDistance = float(self.roiModelNode.GetAttribute(self.PARAM_BOTTOM_DISTANCE))
    bottomScale = float(self.roiModelNode.GetAttribute(self.PARAM_BOTTOM_SCALE)) * 0.01

    transformPlaneToWorld = vtk.vtkTransform()
    transformWorldToPlaneMatrix = HeartValveLib.getTransformToPlane(planePosition, planeNormal)

    numberOfPoints = annulusPoints.shape[1]
    # Concatenate a 4th line containing 1s so that we can transform the positions using
    # a single matrix multiplication.
    annulusPoints_World = np.row_stack((annulusPoints, np.ones(numberOfPoints)))
    # Point positions in the plane coordinate system:
    annulusPoints_Plane = np.dot(transformWorldToPlaneMatrix, annulusPoints_World)
    # remove the last row (all ones)
    annulusPoints_Plane = annulusPoints_Plane[0:3, :]

    # Add points for middle, top, and bottom planes
    clippingSurfacePoints = vtk.vtkPoints()
    clippingSurfacePoints.Allocate(3*numberOfContourPoints) # annulus contour + 2x shifted annulus contour
    # Middle plane
    annulusPoints_Plane[0,:] = (annulusPoints_Plane[0,:]-annulusPoints_Plane[0,:].mean())*scale+annulusPoints_Plane[0,:].mean()
    annulusPoints_Plane[1,:] = (annulusPoints_Plane[1,:]-annulusPoints_Plane[1,:].mean())*scale+annulusPoints_Plane[1,:].mean()
    for contourPoint in annulusPoints_Plane.T:
      clippingSurfacePoints.InsertNextPoint(contourPoint)
    meanPosZ = annulusPoints_Plane[:,2].mean()
    # Top plane
    contourPointsArrayTop_Ras = np.copy(annulusPoints_Plane)
    contourPointsArrayTop_Ras[0,:] = (contourPointsArrayTop_Ras[0,:]-annulusPoints_Plane[0,:].mean())*topScale+annulusPoints_Plane[0,:].mean()
    contourPointsArrayTop_Ras[1,:] = (contourPointsArrayTop_Ras[1,:]-annulusPoints_Plane[1,:].mean())*topScale+annulusPoints_Plane[1,:].mean()
    contourPointsArrayTop_Ras[2,:] = topDistance # make the plane planar
    for contourPoint in contourPointsArrayTop_Ras.T:
      clippingSurfacePoints.InsertNextPoint(contourPoint)
    # Bottom plane
    contourPointsArrayBottom_Ras = np.copy(annulusPoints_Plane)
    contourPointsArrayBottom_Ras[0,:] = (contourPointsArrayBottom_Ras[0,:]-annulusPoints_Plane[0,:].mean())*bottomScale+annulusPoints_Plane[0,:].mean()
    contourPointsArrayBottom_Ras[1,:] = (contourPointsArrayBottom_Ras[1,:]-annulusPoints_Plane[1,:].mean())*bottomScale+annulusPoints_Plane[1,:].mean()
    contourPointsArrayBottom_Ras[2,:] = -bottomDistance # make the plane planar
    for contourPoint in contourPointsArrayBottom_Ras.T:
      clippingSurfacePoints.InsertNextPoint(contourPoint)

    # Add frustum surfaces
    strips = vtk.vtkCellArray()
    # Between middle and top
    strips.InsertNextCell(numberOfContourPoints*2+2)
    firstTopPointIndex = numberOfContourPoints
    for i in range(numberOfContourPoints):
      strips.InsertCellPoint(i)
      strips.InsertCellPoint(i+firstTopPointIndex)
    strips.InsertCellPoint(0)
    strips.InsertCellPoint(firstTopPointIndex)
    # Between middle and bottom
    strips.InsertNextCell(numberOfContourPoints*2+2)
    firstBottomPointIndex = numberOfContourPoints*2
    for i in range(numberOfContourPoints):
      strips.InsertCellPoint(i)
      strips.InsertCellPoint(i+firstBottomPointIndex)
    strips.InsertCellPoint(0)
    strips.InsertCellPoint(firstBottomPointIndex)
    # Top and bottom caps
    polys = vtk.vtkCellArray()
    polys.InsertNextCell(numberOfContourPoints)
    for i in range(numberOfContourPoints,numberOfContourPoints*2):
      polys.InsertCellPoint(i)
    polys.InsertNextCell(numberOfContourPoints)
    for i in range(numberOfContourPoints*2,numberOfContourPoints*3):
      polys.InsertCellPoint(i)

    clippingSurfacePolyData = vtk.vtkPolyData()
    clippingSurfacePolyData.SetPoints(clippingSurfacePoints)
    clippingSurfacePolyData.SetStrips(strips)
    clippingSurfacePolyData.SetPolys(polys)

    triangulator = vtk.vtkTriangleFilter()
    triangulator.SetInputData(clippingSurfacePolyData)

    transformPlaneToWorldMatrix = np.linalg.inv(transformWorldToPlaneMatrix)
    transformPlaneToWorldMatrixVtk = vtk.vtkMatrix4x4()
    for colIndex in range(4):
      for rowIndex in range(3):
        transformPlaneToWorldMatrixVtk.SetElement(rowIndex, colIndex, transformPlaneToWorldMatrix[rowIndex,colIndex])
    transformPlaneToWorld.SetMatrix(transformPlaneToWorldMatrixVtk)
    polyTransformToWorld = vtk.vtkTransformPolyDataFilter()
    polyTransformToWorld.SetTransform(transformPlaneToWorld)
    polyTransformToWorld.SetInputConnection(triangulator.GetOutputPort())

    polyTransformToWorld.Update()
    clippingPolyData = polyTransformToWorld.GetOutput()

    self.roiModelNode.SetAndObservePolyData(clippingPolyData)
    self.roiModelNode.Modified()

  def clipVolumeWithModel(self, inputVolume, outputVolume, clipOutsideSurface=True, fillValue=0, reduceExtent=False):
    """
    Fill voxels of the input volume inside/outside the clipping model with the provided fill value
    """

    # Determine the transform between the box and the image IJK coordinate systems

    rasToModel = vtk.vtkMatrix4x4()
    if self.roiModelNode.GetParentTransformNode() is not None:
      self.roiModelNode.GetParentTransformNode().GetMatrixTransformFromNode(inputVolume.GetParentTransformNode(), rasToModel)
    elif inputVolume.GetParentTransformNode() is not None:
      inputVolume.GetParentTransformNode().GetMatrixTransformToNode(self.roiModelNode.GetParentTransformNode(), rasToModel)

    inputIjkToRas = vtk.vtkMatrix4x4()
    inputVolume.GetIJKToRASMatrix( inputIjkToRas )

    clippingPolyData = self.roiModelNode.GetPolyData()

    inputImageData = inputVolume.GetImageData()
    outputImageData = vtk.vtkImageData()

    outputIjkToRas = vtk.vtkMatrix4x4()

    self.clipImageWithPolyData(inputImageData, outputImageData, clippingPolyData, rasToModel, inputIjkToRas, outputIjkToRas, clipOutsideSurface, fillValue, reduceExtent)

    outputVolume.SetAndObserveImageData(outputImageData)
    outputVolume.SetIJKToRASMatrix(outputIjkToRas)

  def clipOrientedImageWithModel(self, inputOrientedImage, inputParentTransformNode, outputOrientedImage, outputParentTransformNode, clipOutsideSurface=True, fillValue=0, reduceExtent=False):
    """
    Fill voxels of the input volume inside/outside the clipping model with the provided fill value
    """
    import vtkSegmentationCorePython as vtkSegmentationCore
    # Determine the transform between the box and the image IJK coordinate systems

    rasToModel = vtk.vtkMatrix4x4()
    if self.roiModelNode.GetParentTransformNode() is not None:
      self.roiModelNode.GetParentTransformNode().GetMatrixTransformFromNode(inputParentTransformNode,
                                                                            rasToModel)
    elif inputParentTransformNode is not None:
      inputParentTransformNode.GetMatrixTransformToNode(self.roiModelNode.GetParentTransformNode(),
                                                                    rasToModel)

    inputIjkToRas = vtk.vtkMatrix4x4()
    inputOrientedImage.GetImageToWorldMatrix(inputIjkToRas)
    inputImage = vtk.vtkImageData()
    inputImage.ShallowCopy(inputOrientedImage)
    inputImage.SetOrigin(0,0,0)
    inputImage.SetSpacing(1,1,1)

    clippingPolyData = self.roiModelNode.GetPolyData()

    outputIjkToRas = vtk.vtkMatrix4x4()
    outputImage = vtkSegmentationCore.vtkOrientedImageData()
    self.clipImageWithPolyData(inputImage, outputImage, clippingPolyData, rasToModel, inputIjkToRas,
                               outputIjkToRas, clipOutsideSurface, fillValue, reduceExtent)

    outputOrientedImage.DeepCopy(outputImage)
    outputOrientedImage.SetGeometryFromImageToWorldMatrix(outputIjkToRas)

  def clipImageWithPolyData(self, inputImageData, outputImageData, clippingPolyData, rasToModel, inputIjkToRas, outputIjkToRas, clipOutsideSurface=True, fillValue=0, reduceExtent=False):
    """
    Fill voxels of the input volume inside/outside the clipping model with the provided fill value
    If reduceExtent is True then the extent of the volume will be reduced to the smallest possible box that still contains all the non-zero voxels.
    """

    # Determine the transform between the box and the image IJK coordinate systems

    ijkToModel = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Multiply4x4(rasToModel,inputIjkToRas,ijkToModel)
    modelToIjkTransform = vtk.vtkTransform()
    modelToIjkTransform.SetMatrix(ijkToModel)
    modelToIjkTransform.Inverse()

    transformModelToIjk=vtk.vtkTransformPolyDataFilter()
    transformModelToIjk.SetTransform(modelToIjkTransform)
    transformModelToIjk.SetInputData(clippingPolyData)

    # Use the stencil to fill the volume

    # Convert model to stencil
    polyToStencil = vtk.vtkPolyDataToImageStencil()
    polyToStencil.SetInputConnection(transformModelToIjk.GetOutputPort())
    polyToStencil.SetOutputSpacing(inputImageData.GetSpacing())
    polyToStencil.SetOutputOrigin(inputImageData.GetOrigin())
    polyToStencil.SetOutputWholeExtent(inputImageData.GetExtent())

    # Apply the stencil to the volume
    stencilToImage=vtk.vtkImageStencil()
    stencilToImage.SetInputData(inputImageData)
    stencilToImage.SetStencilConnection(polyToStencil.GetOutputPort())
    if clipOutsideSurface:
      stencilToImage.ReverseStencilOff()
    else:
      stencilToImage.ReverseStencilOn()
    stencilToImage.SetBackgroundValue(fillValue)
    stencilToImage.Update()

    # Update the volume with the stencil operation result
    if reduceExtent:

      clippingPolyDataBounds_Ijk = [0,0,0,0,0,0]
      transformModelToIjk.GetOutput().GetBounds(clippingPolyDataBounds_Ijk)
      inputVolumeExtent_Ijk = inputImageData.GetExtent()
      outputVolumeExtent_Ijk = list(inputVolumeExtent_Ijk) # make a copy
      for i in range(3):
        a = int(math.floor(clippingPolyDataBounds_Ijk[i*2]))
        if a > outputVolumeExtent_Ijk[i*2]:
          outputVolumeExtent_Ijk[i*2] = a
        b = int(math.ceil(clippingPolyDataBounds_Ijk[i*2+1]))
        if b < outputVolumeExtent_Ijk[i*2+1]:
          outputVolumeExtent_Ijk[i*2+1] = b

      clipper = vtk.vtkImageClip()
      clipper.SetOutputWholeExtent(outputVolumeExtent_Ijk)
      clipper.ClipDataOn()
      clipper.SetInputConnection(stencilToImage.GetOutputPort())
      clipper.Update()
      outputImageData.DeepCopy(clipper.GetOutput())

      # Offset the extent to start at [0,0,0]
      # (maybe this is not needed, but we do it because some code may assume the image extent starts from zero)
      outputVolumeExtent_Ijk = list(outputImageData.GetExtent())
      outputIjkToInputIjk = vtk.vtkMatrix4x4()
      for i in range(3):
        outputVolumeExtentOffset = outputVolumeExtent_Ijk[i*2]
        outputVolumeExtent_Ijk[i*2] = outputVolumeExtent_Ijk[i*2]-outputVolumeExtentOffset
        outputVolumeExtent_Ijk[i*2+1] = outputVolumeExtent_Ijk[i*2+1]-outputVolumeExtentOffset
        outputIjkToInputIjk.SetElement(i,3, outputVolumeExtentOffset)
      outputImageData.SetExtent(outputVolumeExtent_Ijk)
      vtk.vtkMatrix4x4.Multiply4x4(inputIjkToRas, outputIjkToInputIjk, outputIjkToRas)

    else:

      outputImageData.DeepCopy(stencilToImage.GetOutput())
      outputIjkToRas.DeepCopy(inputIjkToRas)
