import vtk
import os
import math
import slicer
import logging
import numpy as np
from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase

#
# ValveClipBase abstract device class
#
class ValveClipBase(CardiacDeviceBase):

  PARAMETER_NODE = None

  @classmethod
  def updateModel(cls, modelNode, parameterNode):
    cls.PARAMETER_NODE = parameterNode
    cls.computeGuideTip()
    cls.computeCenterline()

  @classmethod
  def setupDeviceModel(cls):
    """
    Setup device model including guide, sleeve, catheter.
    """
    if not cls.PARAMETER_NODE:
      return
    if cls.PARAMETER_NODE.GetParameter('DeviceClassId') in [None, '']:
      logging.error('setupDeviceModel: Device type not defined')
      return

    # Get parameters
    parameterValues = cls.getParameterValuesFromNode(cls.PARAMETER_NODE)

    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()

    guideInteractionCurveNode = cls.getGuideInteractionCurveNode()
    if not guideInteractionCurveNode:
      guideInteractionCurveNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode', 'GuideInteraction')
      guideInteractionCurveNode.CreateDefaultDisplayNodes()
      guideInteractionCurveNode.GetDisplayNode().SetSelectedColor(0.2, 0.8, 1.0)
      guideInteractionCurveNode.GetDisplayNode().SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeUnconstrained)
      guideInteractionCurveNode.GetDisplayNode().SetLineDiameter(parameterValues["guideDiameter"])
      guideInteractionCurveNode.GetDisplayNode().SetGlyphSize(parameterValues["guideDiameter"] * 1.5)
      guideInteractionCurveNode.GetDisplayNode().SetUseGlyphScale(False)
      guideInteractionCurveNode.GetDisplayNode().SetGlyphType(slicer.vtkMRMLMarkupsDisplayNode.Sphere3D)
      guideInteractionCurveNode.GetDisplayNode().SetCurveLineSizeMode(slicer.vtkMRMLMarkupsDisplayNode.UseLineDiameter)
      guideInteractionCurveNode.GetDisplayNode().SetPropertiesLabelVisibility(False)
      cls.PARAMETER_NODE.SetNodeReferenceID('GuideInteractionCurve', guideInteractionCurveNode.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(guideInteractionCurveNode), shNode.GetItemByDataNode(cls.PARAMETER_NODE))

    guideCurveNode = cls.getGuideCurveNode()
    if not guideCurveNode:
      guideCurveNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode', 'Guide')
      guideCurveNode.SetLocked(True)
      guideCurveNode.CreateDefaultDisplayNodes()
      guideCurveNode.GetDisplayNode().SetSelectedColor(0.2, 0.8, 1.0)
      guideCurveNode.GetDisplayNode().SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeUnconstrained)
      guideCurveNode.GetDisplayNode().SetLineDiameter(parameterValues["guideDiameter"])
      guideCurveNode.GetDisplayNode().SetGlyphSize(0)
      guideCurveNode.GetDisplayNode().SetCurveLineSizeMode(slicer.vtkMRMLMarkupsDisplayNode.UseLineDiameter)
      cls.PARAMETER_NODE.SetNodeReferenceID('GuideCurve', guideCurveNode.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(guideCurveNode), shNode.GetItemByDataNode(cls.PARAMETER_NODE))

    sleeveModelNode = cls.PARAMETER_NODE.GetNodeReference('SleeveModel')
    if not sleeveModelNode:
      sleeveModelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', 'Sleeve')
      sleeveModelNode.CreateDefaultDisplayNodes()
      sleeveModelNode.GetDisplayNode().SetColor(0.8, 0.8, 0.2)
      cls.PARAMETER_NODE.SetNodeReferenceID('SleeveModel', sleeveModelNode.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(sleeveModelNode), shNode.GetItemByDataNode(cls.PARAMETER_NODE))

    markers = [
      ['GuideMarkerModel', [0.6, 0.0, 0.6]],
      ['SleeveMarker1Model', [0.0, 0.0, 0.8]],
      ['SleeveMarker2Model', [0.8, 0.4, 0.0]]
      ]
    for markerType, color in markers:
      markerModelNode = cls.PARAMETER_NODE.GetNodeReference(markerType)
      if not markerModelNode:
        markerModelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', markerType)
        markerModelNode.CreateDefaultDisplayNodes()
        markerModelNode.GetDisplayNode().SetColor(color)
        cls.PARAMETER_NODE.SetNodeReferenceID(markerType, markerModelNode.GetID())
        shNode.SetItemParent(shNode.GetItemByDataNode(markerModelNode), shNode.GetItemByDataNode(cls.PARAMETER_NODE))

    # Use the centerline curve to display the delivery catheter
    centerlineNode = cls.getCenterlineNode()
    if not centerlineNode:
      centerlineNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsCurveNode", "Catheter")
      centerlineNode.CreateDefaultDisplayNodes()
      centerlineNode.GetDisplayNode().SetSelectedColor(0.2, 0.8, 0.4)
      centerlineNode.GetDisplayNode().SetLineDiameter(parameterValues["catheterDiameter"])
      centerlineNode.GetDisplayNode().SetCurveLineSizeMode(slicer.vtkMRMLMarkupsDisplayNode.UseLineDiameter)
      cls.setCenterlineNode(centerlineNode)
      shNode.SetItemParent(shNode.GetItemByDataNode(centerlineNode), shNode.GetItemByDataNode(cls.PARAMETER_NODE))
      # we compute the centerline automatically, prevent the user from accidentally moving
      # a control point (instead of moving the clip or the puncture point)
      # Note: Same as content of CardiacDeviceSimulator.setCenterlineEditingEnabled to prevent having to call into module classes
      centerlineNode.SetLocked(True)
      numberOfcontrolPoints = centerlineNode.GetNumberOfControlPoints()
      wasModify = centerlineNode.StartModify()
      for i in range(numberOfcontrolPoints):
        centerlineNode.SetNthControlPointVisibility(i, False)
      centerlineNode.EndModify(wasModify)

    clipPositioningPlaneNode = cls.PARAMETER_NODE.GetNodeReference('ClipPositioningPlane')
    if not clipPositioningPlaneNode:
      clipPositioningPlaneNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsPlaneNode', 'Clip position')
      cls.PARAMETER_NODE.SetNodeReferenceID('ClipPositioningPlane', clipPositioningPlaneNode.GetID())
      shNode.SetItemParent(shNode.GetItemByDataNode(clipPositioningPlaneNode), shNode.GetItemByDataNode(cls.PARAMETER_NODE))

    cls.computeGuideTip()

  @classmethod
  def setCenterlineNode(cls, centerlineCurveNode):
    if not cls.PARAMETER_NODE:
      return
    cls.PARAMETER_NODE.SetNodeReferenceID("CenterlineCurve", centerlineCurveNode.GetID() if centerlineCurveNode else None)
    if centerlineCurveNode:
      centerlineCurveNode.CreateDefaultDisplayNodes()
      centerlineCurveNode.GetDisplayNode().SetSnapMode(slicer.vtkMRMLMarkupsDisplayNode.SnapModeUnconstrained)

  @classmethod
  def getCenterlineNode(cls):
    return cls.PARAMETER_NODE.GetNodeReference("CenterlineCurve") if cls.PARAMETER_NODE else None

  @classmethod
  def getGuideInteractionCurveNode(cls):
    return cls.PARAMETER_NODE.GetNodeReference("GuideInteractionCurve") if cls.PARAMETER_NODE else None

  @classmethod
  def getGuideCurveNode(cls):
    return cls.PARAMETER_NODE.GetNodeReference("GuideCurve") if cls.PARAMETER_NODE else None

  @classmethod
  def getClipPositioningPlaneNode(cls):
    return cls.PARAMETER_NODE.GetNodeReference("ClipPositioningPlane") if cls.PARAMETER_NODE else None

  @classmethod
  def computeCenterline(cls):
    if not cls.PARAMETER_NODE:
      return

    # Get parameters
    parameterValues = cls.getParameterValuesFromNode(cls.PARAMETER_NODE)

    guideCurveNode = cls.getGuideCurveNode()
    if not guideCurveNode or guideCurveNode.GetNumberOfDefinedControlPoints() < 3:
      return

    slicer.app.pauseRender()
    try:
      # Make sure centerline node exists
      centerlineNode = cls.getCenterlineNode()

      #
      # Get transforms
      #
      guideTipToWorldTransformMatrix = vtk.vtkMatrix4x4()
      guideCurveNode.GetCurvePointToWorldTransformAtPointIndex(guideCurveNode.GetCurvePointIndexFromControlPointIndex(
        guideCurveNode.GetNumberOfControlPoints()-1), guideTipToWorldTransformMatrix)

      sleeveElbowToGuideTipTransformMatrix = vtk.vtkMatrix4x4()
      sleeveElbowToGuideTipTransformMatrix.SetElement(2, 3, parameterValues["sleeveTranslation"])
      sleeveElbowToWorldTransformMatrix = vtk.vtkMatrix4x4()
      vtk.vtkMatrix4x4.Multiply4x4(guideTipToWorldTransformMatrix, sleeveElbowToGuideTipTransformMatrix, sleeveElbowToWorldTransformMatrix)

      # Pulley rotation angles
      sleeveTipDeflectionAP = parameterValues["sleeveTipDeflectionAP"] if "sleeveTipDeflectionAP" in parameterValues.keys() else -parameterValues["sleeveTipDeflectionFE"]  # Support both MitraClip and TriClip
      psi_x = math.pi / 180.0 * sleeveTipDeflectionAP
      sleeveTipDeflectionML = parameterValues["sleeveTipDeflectionML"] if "sleeveTipDeflectionML" in parameterValues.keys() else 0.0  # Support both MitraClip and TriClip
      psi_y = math.pi / 180.0 * sleeveTipDeflectionML

      # Device parameters
      l = arcLength = parameterValues["sleeveArcLength"]  # arc length of the steerable device
      d_b = 2.0  # distance between backbone and tendon; outer diameter of the guide is 5.3mm, so max distance is 2.65 #TODO: as device parameter
      r_p = 2.0 # pulley radius, controls how much bending rotation of the knob causes #TODO: as device parameter

      from math import sqrt
      overallKappa = r_p * sqrt(psi_x*psi_x+psi_y*psi_y)/(l*d_b)

      sleeveSteeredToSleeveElbowTransformMatrix = cls.getDeliverySheathIntermediateFrameToReferenceFrameTransformVtkMatrix(
        l, d_b, r_p, psi_x, psi_y)

      sleeveSteeredToWorldTransform = vtk.vtkTransform()
      sleeveSteeredToWorldTransform.Concatenate(sleeveElbowToWorldTransformMatrix)
      sleeveSteeredToWorldTransform.Concatenate(sleeveSteeredToSleeveElbowTransformMatrix)

      sleeveTipToWorldTransform = vtk.vtkTransform()
      sleeveTipToWorldTransform.Concatenate(sleeveSteeredToWorldTransform)
      sleeveTipToWorldTransform.Translate(0, 0, parameterValues["sleeveTipLength"])

      clipToWorldTransform = vtk.vtkTransform()
      clipToWorldTransform.Concatenate(sleeveTipToWorldTransform)
      clipToWorldTransform.RotateZ(parameterValues["catheterRotation"])
      clipToWorldTransform.Translate(0, 0, parameterValues["catheterTranslation"])
      clipToWorldTransform.Scale(1, -1, -1)

      # Get sleeveTip position
      sleeveTipPosition = np.zeros(4)
      sleeveTipToWorldTransform.GetMatrix().MultiplyPoint(np.array([0,0,0,1]), sleeveTipPosition)
      sleeveTipPosition = sleeveTipPosition[0:3]

      centerlineWasModified = centerlineNode.StartModify()

      # Make sure we have all control points created already (we don't want to delete and recreate them
      # on each update to make update a lightweight operation)
      numberOfControlPoints = 25
      numberOfControlPointsToAdd = numberOfControlPoints - centerlineNode.GetNumberOfControlPoints()
      for pointIndex in range(numberOfControlPointsToAdd):
        centerlineNode.AddControlPointWorld(vtk.vtkVector3d(0, 0, 0))

      slicer.modules.markups.logic().SetAllControlPointsVisibility(centerlineNode, False)

      beforeArcLength = parameterValues["sleeveTranslation"]
      afterArcLength = parameterValues["sleeveTipLength"] + parameterValues["catheterTranslation"]

      totalLength = beforeArcLength + arcLength + afterArcLength
      for controlPointIndex in range(numberOfControlPoints):
        controlPointPositionAlongCurve = totalLength * controlPointIndex / (numberOfControlPoints-1)
        controlPointPosition = np.zeros(4)
        if controlPointPositionAlongCurve < beforeArcLength:
          # before arc
          guideTipToWorldTransformMatrix.MultiplyPoint(np.array([0,0,controlPointPositionAlongCurve,1]), controlPointPosition)
        elif controlPointPositionAlongCurve < beforeArcLength + arcLength:
          # position column from H_i_0
          l = controlPointPositionAlongCurve - beforeArcLength
          controlPointPosition_SleeveElbow = cls.getDeliverySheathIntermediateFrameToReferenceFrameTransformIntermediatePosition(
            l, d_b, r_p, psi_x, psi_y, overallKappa)
          sleeveElbowToWorldTransformMatrix.MultiplyPoint(controlPointPosition_SleeveElbow, controlPointPosition)
        else:
          # after arc
          sleeveSteeredToWorldTransform.MultiplyPoint(np.array([0,0,controlPointPositionAlongCurve - beforeArcLength - arcLength,1]), controlPointPosition)
        controlPointPosition = controlPointPosition[0:3]
        centerlineNode.SetNthControlPointPositionWorld(controlPointIndex, controlPointPosition)

      slicer.modules.markups.logic().SetAllControlPointsVisibility(centerlineNode, False) # Hide all control points

      centerlineNode.EndModify(centerlineWasModified)

      # Update sleeve
      sleeveCurvePoints = vtk.vtkPoints()
      endCurvePointIndex = centerlineNode.GetClosestCurvePointIndexToPositionWorld(sleeveTipPosition)
      centerlineNode.GetSampledCurvePointsBetweenStartEndPointsWorld(sleeveCurvePoints, 3.0, 0, endCurvePointIndex)
      line = vtk.vtkLineSource()
      line.SetPoints(sleeveCurvePoints)
      tube = vtk.vtkTubeFilter()
      tube.SetInputConnection(line.GetOutputPort())
      tube.SetRadius(parameterValues["sleeveDiameter"] / 2.0)
      tube.SetNumberOfSides(24)
      tube.CappingOn()
      tube.Update()
      sleeveModelNode = cls.PARAMETER_NODE.GetNodeReference('SleeveModel')
      sleeveModelNode.SetAndObservePolyData(tube.GetOutput())
      sleeveModelNode.SetSelectable(False) # Prevent picking on sleeve model (endless loop until tip reaches camera)

      # Update markers
      markers = [
        ['GuideMarkerModel', guideCurveNode, guideCurveNode.GetCurvePointsWorld().GetNumberOfPoints()-1,
          -parameterValues["guideMarkerDistanceFromTip"], parameterValues["sleeveMarkerWidth"], parameterValues["guideDiameter"]/2.0*1.1],
        ['SleeveMarker1Model', centerlineNode, endCurvePointIndex, -parameterValues["sleeveMarker1DistanceFromTip"],
          parameterValues["sleeveMarkerWidth"], parameterValues["sleeveDiameter"] / 2.0 * 1.1],
        ['SleeveMarker2Model', centerlineNode, endCurvePointIndex, -parameterValues["sleeveMarker2DistanceFromTip"],
          parameterValues["sleeveMarkerWidth"], parameterValues["sleeveDiameter"] / 2.0 * 1.1]
        ]
      for markerType, curve, tipPointIndex, distance, width, radius in markers:
        markerStartPosition = [0,0,0]
        markerEndPosition = [0,0,0]
        curve.GetPositionAlongCurveWorld(markerStartPosition, tipPointIndex, distance-width/2.0)
        curve.GetPositionAlongCurveWorld(markerEndPosition, tipPointIndex, distance+width/2.0)
        curvePoints = vtk.vtkPoints()
        curvePoints.SetNumberOfPoints(2)
        curvePoints.SetPoint(0, markerStartPosition)
        curvePoints.SetPoint(1, markerEndPosition)
        line = vtk.vtkLineSource()
        line.SetPoints(curvePoints)
        tube = vtk.vtkTubeFilter()
        tube.SetInputConnection(line.GetOutputPort())
        tube.SetRadius(radius)
        tube.SetNumberOfSides(24)
        tube.CappingOn()
        tube.Update()
        markerModelNode = cls.PARAMETER_NODE.GetNodeReference(markerType)
        markerModelNode.SetAndObservePolyData(tube.GetOutput())

      # Update device position
      originalModelNode = cls.PARAMETER_NODE.GetNodeReference('OriginalModel')
      if originalModelNode and originalModelNode.GetPolyData() and originalModelNode.GetPolyData().GetNumberOfPoints() > 0:
        deviceToCenterlineTransform = cls.PARAMETER_NODE.GetNodeReference('PositioningTransform')
        deviceToCenterlineTransform.SetAndObserveTransformToParent(clipToWorldTransform)
    finally:
      slicer.app.resumeRender()

  @classmethod
  def computeGuideTip(cls):
    """
    Compute and apply geometry of the guide tip
    """
    # Get parameters
    parameterValues = cls.getParameterValuesFromNode(cls.PARAMETER_NODE)

    guideInteractionCurveNode = cls.getGuideInteractionCurveNode()
    if not guideInteractionCurveNode:
      return

    if guideInteractionCurveNode.GetNumberOfDefinedControlPoints() < 3:
      return
    else:
      # Hide interaction curve line when guide curve is created
      guideInteractionCurveNode.GetDisplayNode().SetLineDiameter(0)

    slicer.app.pauseRender()
    try:
      # Make sure guide curve node exists
      guideCurveNode = cls.getGuideCurveNode()

      # Device parameters
      arcLength = l = parameterValues["guideTipArcLength"] if "guideTipArcLength" in parameterValues else 0  # arc length of the steerable device
      beforeArcLength = 0 # Guide tip not translatable
      afterArcLength = parameterValues["guideTipLength"] if "guideTipLength" in parameterValues else 0
      totalTipLength = beforeArcLength + arcLength + afterArcLength

      # Get transforms
      guideTipToWorldTransformMatrix = vtk.vtkMatrix4x4()
      guideCurveNode.GetCurvePointToWorldTransformAtPointIndex(guideCurveNode.GetCurvePointIndexFromControlPointIndex(
        guideCurveNode.GetNumberOfControlPoints()-1), guideTipToWorldTransformMatrix)

      # Rebuild curve from interaction curve then resample to have points frequently to prevent bug caused by
      # spline interpolation (see https://github.com/JolleyLabCHOP/Internal/issues/23#issuecomment-794207836)
      resampledControlPointsDistance = 5.0 # mm
      numOfGuideTipPoints = 5 # Expected number of guide tip points
      guideCurveNode.RemoveAllControlPoints()
      interactionInterpolatedCurvePoints = guideInteractionCurveNode.GetCurvePointsWorld()
      guideCurveNode.SetControlPointPositionsWorld(interactionInterpolatedCurvePoints)
      guideCurveNode.ResampleCurveWorld(resampledControlPointsDistance)
      guideCurveNode.SetNumberOfPointsPerInterpolatingSegment(1) # Limit number of points
      slicer.modules.markups.logic().SetAllControlPointsVisibility(guideCurveNode, False) # Hide all control points

      guideCurveWasModified = guideCurveNode.StartModify()

      # Calculate and add guide tip control points if requested
      if totalTipLength > 1e-3:
        # Get transforms
        guideTipBaseToWorldTransformMatrix = vtk.vtkMatrix4x4()
        guideInteractionCurveNode.GetCurvePointToWorldTransformAtPointIndex(guideInteractionCurveNode.GetCurvePointIndexFromControlPointIndex(
          guideInteractionCurveNode.GetNumberOfControlPoints()-1), guideTipBaseToWorldTransformMatrix)

        guideTipRotatedBaseToGuideTipBaseTransform = vtk.vtkTransform()
        guideTipRotatedBaseToGuideTipBaseTransform.RotateZ(parameterValues["guideRotation"])

        guideTipElbowToGuideTipRotatedBaseTransformMatrix = vtk.vtkMatrix4x4()
        guideTipElbowToGuideTipRotatedBaseTransformMatrix.SetElement(2, 3, beforeArcLength)

        guideTipElbowToWorldTransform = vtk.vtkTransform()
        guideTipElbowToWorldTransform.Concatenate(guideTipBaseToWorldTransformMatrix)
        guideTipElbowToWorldTransform.Concatenate(guideTipRotatedBaseToGuideTipBaseTransform)
        guideTipElbowToWorldTransform.Concatenate(guideTipElbowToGuideTipRotatedBaseTransformMatrix)

        # Pulley rotation angles
        guideTipDeflection = parameterValues["guideTipDeflection"] if "guideTipDeflection" in parameterValues.keys() else parameterValues["guideTipDeflectionAP"]  # Support both MitraClip and TriClip
        psi_x = math.pi / 180.0 * guideTipDeflection
        guideTipDeflectionLateral = parameterValues["guideTipDeflectionSL"] if "guideTipDeflectionSL" in parameterValues.keys() else 0.0  # Support both MitraClip and TriClip
        psi_y = math.pi / 180.0 * guideTipDeflectionLateral

        # Device parameters
        d_b = 2.5  # distance between backbone and tendon; outer diameter of the guide is 5.3mm, so max distance is 2.65 #TODO: as device parameter
        r_p = 2.5 # pulley radius, controls how much bending rotation of the knob causes #TODO: as device parameter

        from math import sqrt
        overallKappa = r_p * sqrt(psi_x*psi_x+psi_y*psi_y)/(l*d_b)

        guideTipSteeredToGuideTipElbowTransformMatrix = cls.getDeliverySheathIntermediateFrameToReferenceFrameTransformVtkMatrix(
          l, d_b, r_p, psi_x, psi_y)

        guideTipSteeredToWorldTransform = vtk.vtkTransform()
        guideTipSteeredToWorldTransform.Concatenate(guideTipElbowToWorldTransform)
        guideTipSteeredToWorldTransform.Concatenate(guideTipSteeredToGuideTipElbowTransformMatrix)

        # Compute guide tip points
        for guideTipIndex in range(numOfGuideTipPoints):
          controlPointPositionAlongCurve = totalTipLength * guideTipIndex / (numOfGuideTipPoints-1)
          controlPointPosition = np.zeros(4)
          if controlPointPositionAlongCurve < beforeArcLength:
            # before arc
            guideTipToWorldTransformMatrix.MultiplyPoint(np.array([0,0,controlPointPositionAlongCurve,1]), controlPointPosition)
          if controlPointPositionAlongCurve < arcLength:
            # position column from H_i_0
            currentL = controlPointPositionAlongCurve - beforeArcLength
            controlPointPosition_GuideTipElbow = cls.getDeliverySheathIntermediateFrameToReferenceFrameTransformIntermediatePosition(
              currentL, d_b, r_p, psi_x, psi_y, overallKappa)
            guideTipElbowToWorldTransform.GetMatrix().MultiplyPoint(controlPointPosition_GuideTipElbow, controlPointPosition)
          else:
            # after arc
            guideTipSteeredToWorldTransform.MultiplyPoint(np.array([0,0,controlPointPositionAlongCurve - arcLength,1]), controlPointPosition)
          controlPointPosition = controlPointPosition[0:3]

          controlPointIndex = guideCurveNode.AddControlPointWorld(vtk.vtkVector3d(0, 0, 0))
          guideCurveNode.SetNthControlPointPositionWorld(controlPointIndex, controlPointPosition)
          guideCurveNode.SetNthControlPointLocked(controlPointIndex, True)
          guideCurveNode.SetNthControlPointVisibility(controlPointIndex, False)

    except Exception as e:
      import traceback
      traceback.print_exc()

    finally:
      if 'guideCurveWasModified' in locals():
        guideCurveNode.EndModify(guideCurveWasModified)
      slicer.app.resumeRender()

  @classmethod
  def getDeliverySheathIntermediateFrameToReferenceFrameTransformNumpyArray(cls, l, d_b, r_p, psi_x, psi_y, consistentNormals=True):
    """
    Compose the matrix H_i_0 according to the RADS kinematic model described in Vrooijink2017.
    The matrix gives the transformation from the intermediate frame of the guided sheath (i.e.
    right after the bend) to the reference frame of the guided sheath (i.e. before the bend).

    :param l: Backbone length (midline)
    :param d_b: Tendon distance to backbone arc
    :param r_p: Pulley radius
    :param psi_x: Rotation of pulley controlling X
    :param psi_y: Rotation of pulley controlling Y
    :param consistentNormals: compute XY axis of the intermediate frame using parallel transport method (to minimize torsion)
    """
    from math import sin, cos, sqrt, atan2
    phi = atan2(psi_y, psi_x)
    kappa = r_p * sqrt(psi_x*psi_x+psi_y*psi_y)/(l*d_b)

    if kappa > 1e-3:
      H_i_0 = np.array([
        [cos(phi)*cos(kappa*l), -sin(phi), cos(phi)*sin(kappa*l), cos(phi)*(1-cos(kappa*l))/kappa],
        [sin(phi)*cos(kappa*l),  cos(phi), sin(phi)*sin(kappa*l), sin(phi)*(1-cos(kappa*l))/kappa],
        [        -sin(kappa*l),         0,          cos(kappa*l),             sin(kappa*l) /kappa],
        [                    0,         0,                     0,                               1]
        ])
    else:
      H_i_0 = np.array([
        [cos(phi)*cos(kappa*l), -sin(phi), cos(phi)*sin(kappa*l), 0],
        [sin(phi)*cos(kappa*l),  cos(phi), sin(phi)*sin(kappa*l), 0],
        [        -sin(kappa*l),         0,          cos(kappa*l), l],
        [                    0,         0,                     0, 1]
        ])

    # Compute normals using parellel transport algorithm to minimize torsion
    if consistentNormals:
      # Computation algorithm is adopted from vtkvmtkCenterlineAttributesFilter::ComputeParallelTransportNormals
      t0 = [0,0,1]  # initial tangent
      n0 = [1,0,0]  # initial normal
      t1 = H_i_0[0:3, 2]  # transformed tangent

      dot = vtk.vtkMath.Dot(t0,t1)
      if 1-dot < 0.001:
        theta = 0.0
      else:
        theta = math.acos(dot) * 180.0 / math.pi

      v = [0,0,0]  # rotation axis
      vtk.vtkMath.Cross(t0,t1,v)
      transform = vtk.vtkTransform()
      transform.RotateWXYZ(theta,v)

      n1 = [1,0,0]  # transformed normal
      transform.TransformPoint(n0,n1)

      dot = vtk.vtkMath.Dot(t1,n1)
      n1[0] -= dot * t1[0]
      n1[1] -= dot * t1[1]
      n1[2] -= dot * t1[2]
      vtk.vtkMath.Normalize(n1)

      bn1 = [0,1,0]  # transformed binormal
      vtk.vtkMath.Cross(t1,n1, bn1)

      # update axes in the output matrix
      H_i_0[0:3, 0] = n1
      H_i_0[0:3, 1] = bn1

    return H_i_0

  @classmethod
  def getDeliverySheathIntermediateFrameToReferenceFrameTransformVtkMatrix(cls, l, d_b, r_p, psi_x, psi_y):
    """
    Compose the matrix H_i_0 according to the RADS kinematic model described in Vrooijink2017.
    The matrix gives the transformation from the intermediate frame of the guided sheath (i.e.
    right after the bend) to the reference frame of the guided sheath (i.e. before the bend).

    :param l: Backbone length (midline)
    :param d_b: Tendon distance to backbone arc
    :param r_p: Pulley radius
    :param psi_x: Rotation of pulley controlling X
    :param psi_y: Rotation of pulley controlling Y
    """
    return slicer.util.vtkMatrixFromArray(
      cls.getDeliverySheathIntermediateFrameToReferenceFrameTransformNumpyArray(l, d_b, r_p, psi_x, psi_y))

  @classmethod
  def getDeliverySheathIntermediateFrameToReferenceFrameTransformIntermediatePosition(cls, l, d_b, r_p, psi_x, psi_y, overallKappa):
    """
    Compose the position column of the matrix H_i_0 according to the RADS kinematic model described
    in Vrooijink2017 at an intermediate position defined by `l`.
    See :func:`getDeliverySheathIntermediateFrameToReferenceFrameTransformNumpyArray`.

    :param l: Backbone length (midline), in this case the current position along the bend
    :param d_b: Tendon distance to backbone arc
    :param r_p: Pulley radius
    :param psi_x: Rotation of pulley controlling X
    :param psi_y: Rotation of pulley controlling Y
    :param overallKappa: Overall curvature of the whole bend (using the total `l`)
    """
    from math import sin, cos, sqrt, atan2
    phi = atan2(psi_y, psi_x)

    if overallKappa > 1e-3:
      return np.array([
        cos(phi)*(1-cos(overallKappa*l))/overallKappa,
        sin(phi)*(1-cos(overallKappa*l))/overallKappa,
        sin(overallKappa*l)/overallKappa,
        1])
    else:
      return np.array([0, 0, l, 1])

  @staticmethod
  def intersectionPoints(linePos, lineDir, spherePos, sphereRadius):
    """
    Return intersection points between a sphere and a line as line direction vector multiplier.
    """
    # based on http://ambrsoft.com/TrigoCalc/Sphere/SpherLineIntersection_.htm

    from math import sqrt

    a = np.inner(lineDir, lineDir)
    #b = -2 * (lineDir[0]*(spherePos[0]-linePos[0]) + lineDir[1]*(spherePos[1]-linePos[1]) + lineDir[2]*(spherePos[2]-linePos[2]))
    #c = (spherePos[0]-linePos[0])**2 + (spherePos[1]-linePos[1])**2 + (spherePos[2]-linePos[2])**2 - sphereRadius**2
    b = -2 * np.inner(lineDir, spherePos - linePos)
    c = np.inner(spherePos - linePos, spherePos - linePos) - sphereRadius ** 2

    D = b**2 - 4*a*c
    if D<0:
      return []

    return [(-b+sqrt(D))/(2*a), (-b-sqrt(D))/(2*a)]



#
# GenericValveClip device
#
class GenericValveClip(ValveClipBase):

  NAME = "GenericValveClip"
  ID = "GenericValveClip"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  CLIP_GRASPER_POLYDATA = None
  CLIP_TIP_POLYDATA = None

  @classmethod
  def getParameters(cls):
    return {
      # Clip parameters
      #   NB: comes in 13 different sizes
      "openingAngleDeg": cls._genParameters("Opening angle", "How many degrees the device wings are open", 0, "deg", 0, 180, 1.0, 1),
      # Currently unused parameters
      # "clipLengthMm": cls._genParameters("Clip length", "Total length of closed clip", 15, "mm", 10, 22, 1.0, 1),
      # "coaptationLengthMm": cls._genParameters("Coaptation length", "Length of the opening wing", 9, "mm", 6, 15, 1.0, 1),
      # "clipArmsSpanMm": cls._genParameters("Clip arms span", "Total width of the device opened at 120 degrees", 17, "mm", 12, 30, 1.0, 1),

      # Robot parameters
      "sleeveTranslation": cls._genParameters("Sleeve translation", "Position of the sleeve", 0, "mm", 0, 100, 1, 5),
      "sleeveTipDeflectionAP": cls._genParameters("Sleeve tip bending A/P", "Deflection of the sleeve tip in A/P direction", 0, "deg", -120, 120, 1, 10),
      "sleeveTipDeflectionML": cls._genParameters("Sleeve tip bending M/L", "Deflection of the sleeve tip in M/L direction", 0, "deg", -120, 120, 1, 10),
      "catheterTranslation": cls._genParameters("Delivery catheter translation", "Position of the delivery catheter", 0, "mm", 0, 100, 1, 5),
      "catheterRotation": cls._genParameters("Delivery catheter rotation", "Rotation of the delivery catheter along main axis", 0, "deg", -180, 180, 1, 10),

      # Hidden geometry parameters
      "guideMarkerDistanceFromTip": cls._genParameters("", "", 5.0, "mm", 0, 100, 1, 5, 0, False),
      "guideMarkerWidth": cls._genParameters("", "", 3.0, "mm", 0, 100, 1, 5, 0, False),
      "guideDiameter": cls._genParameters("", "", 8.1, "mm", 0, 100, 1, 5, 0, False),
      "sleeveTipLength": cls._genParameters("", "", 10.0, "mm", 0, 100, 1, 5, 0, False),
      "sleeveArcLength": cls._genParameters("", "", 20.0, "mm", 0, 100, 1, 5, 0, False),
      "sleeveMarker1DistanceFromTip": cls._genParameters("", "", 20.0, "mm", 0, 100, 1, 5, 0, False), #TODO: Applies for generic device too?
      "sleeveMarker2DistanceFromTip": cls._genParameters("", "", 30.0, "mm", 0, 100, 1, 5, 0, False), #TODO: Applies for generic device too?
      "sleeveMarkerWidth": cls._genParameters("", "", 1.5, "mm", 0, 100, 0.5, 5, 0, False), #TODO: Applies for generic device too?
      "sleeveDiameter": cls._genParameters("", "", 5.3, "mm", 0, 100, 0.5, 5, 0, False),
      "catheterDiameter": cls._genParameters("", "", 2.5, "mm", 0, 100, 0.5, 5, 0, False),

      # Hidden threshold parameters
      "guideClinicalCurvatureThreshold": cls._genParameters("", "", 0.025, "mm-1", 0, 10, 0.005, 1, 0, False),
      "guidePhysicalCurvatureThreshold": cls._genParameters("", "", 0.05, "mm-1", 0, 10, 0.005, 1, 0, False),
      "catheterClinicalCurvatureThreshold": cls._genParameters("", "", 0.05, "mm-1", 0, 10, 0.005, 1, 0, False),
      "catheterPhysicalCurvatureThreshold": cls._genParameters("", "", 0.1, "mm-1", 0, 10, 0.005, 1, 0, False),
    }

  @classmethod
  def updateModel(cls, modelNode, parameterNode):
    super(GenericValveClip, cls).updateModel(modelNode, parameterNode)

    # Get parameters
    parameterValues = cls.getParameterValuesFromNode(parameterNode)
    # Get models
    if not cls.CLIP_GRASPER_POLYDATA:
      reader = vtk.vtkXMLPolyDataReader()
      reader.SetFileName(os.path.join(cls.RESOURCES_PATH, "Models", "grasper.vtp"))
      reader.Update()
      cls.CLIP_GRASPER_POLYDATA = reader.GetOutput()
    if not cls.CLIP_TIP_POLYDATA:
      reader = vtk.vtkXMLPolyDataReader()
      reader.SetFileName(os.path.join(cls.RESOURCES_PATH, "Models", "tip.vtp"))
      reader.Update()
      cls.CLIP_TIP_POLYDATA = reader.GetOutput()
    # Create model
    appender = vtk.vtkAppendPolyData()
    openingAngleDeg = parameterValues["openingAngleDeg"]
    # Wing 1
    wingTransformer1 = vtk.vtkTransformPolyDataFilter()
    wingTransformer1.SetInputData(cls.CLIP_GRASPER_POLYDATA)
    wingTransform1 = vtk.vtkTransform()
    wingTransform1.RotateX(openingAngleDeg/2.0)
    wingTransformer1.SetTransform(wingTransform1)
    appender.AddInputConnection(wingTransformer1.GetOutputPort())
    # Wing 2
    wingTransformer2 = vtk.vtkTransformPolyDataFilter()
    wingTransformer2.SetInputData(cls.CLIP_GRASPER_POLYDATA)
    wingTransform2 = vtk.vtkTransform()
    wingTransform2.Scale(1,-1,1) # mirror Y
    wingTransform2.RotateX(openingAngleDeg/2.0)
    wingTransformer2.SetTransform(wingTransform2)
    reverser = vtk.vtkReverseSense()
    reverser.SetInputConnection(wingTransformer2.GetOutputPort())
    appender.AddInputConnection(reverser.GetOutputPort())
    # Tip
    appender.AddInputData(cls.CLIP_TIP_POLYDATA)
    # Update model
    appender.Update()
    modelNode.SetAndObservePolyData(appender.GetOutput())


#
# MitraClipG4 devices
#
class MitraClipG4Base(ValveClipBase):

  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  CLIP_WING_FILENAME = None # To be defined in base class
  CLIP_WING_POLYDATA = None
  CLIP_GRIPPER_FILENAME = None # To be defined in base class
  CLIP_GRIPPER_POLYDATA = None
  CLIP_BASE_POLYDATA = None

  APPLY_FABRIC_TEXTURE = True
  FABRIC_TEXTURE_IMAGE_DATA = None

  @classmethod
  def getParameters(cls):
    return {
      # Clip parameters
      "wingOpeningAngleDeg": cls._genParameters("Wing opening angle", "How many degrees the device wings are open", 0, "deg", 0, 180, 1.0, 1),
      "independentWingOpeningAngleDeg": cls._genParameters("Independent wing angle", "How many degrees the independent wing is open (when -1, they move together)", -1, "deg", -1, 180, 1.0, 1),
      "gripperOpeningAngleDeg": cls._genParameters("Gripper opening angle", "How many degrees the device grippers are open", 0, "deg", 0, 180, 1.0, 1),
      "independentGripperOpeningAngleDeg": cls._genParameters("Independent gripper angle", "How many degrees the independent gripper is open (when -1, they move together)", -1, "deg", -1, 180, 1.0, 1),

      # Robot parameters
      "guideRotation": cls._genParameters("Guide rotation", "Rotation of entire guide along main axis", 0, "deg", -180, 180, 1, 10),
      "guideTipDeflection": cls._genParameters("Guide tip bending", "Deflection of the end of the guide", 35, "deg", 14, 57, 1, 3),
      "sleeveTranslation": cls._genParameters("Sleeve translation", "Position of the sleeve", 0, "mm", -45, 15, 1, 5),
      "sleeveTipDeflectionAP": cls._genParameters("Sleeve tip bending A/P", "Deflection of the sleeve tip in A/P direction", 0, "deg", -90, 90, 1, 10),
      "sleeveTipDeflectionML": cls._genParameters("Sleeve tip bending M/L", "Deflection of the sleeve tip in M/L direction", 0, "deg", 0, 120, 1, 10),
      "catheterTranslation": cls._genParameters("Delivery catheter translation", "Position of the delivery catheter", 14.5, "mm", 14.5, 52.0, 0.5, 5),
      "catheterRotation": cls._genParameters("Delivery catheter rotation", "Rotation of the delivery catheter along main axis", 0, "deg", -180, 180, 1, 10),

      # Hidden geometry parameters
      "guideTipLength": cls._genParameters("", "", 6.0, "mm", 0, 100, 1, 5, 0, False),
      "guideTipArcLength": cls._genParameters("", "", 12.0, "mm", 0, 100, 1, 5, 0, False),
      "guideMarkerDistanceFromTip": cls._genParameters("", "", 5.0, "mm", 0, 100, 1, 5, 0, False),
      "guideMarkerWidth": cls._genParameters("", "", 3.0, "mm", 0, 100, 1, 5, 0, False),
      "guideDiameter": cls._genParameters("", "", 8.1, "mm", 0, 100, 1, 5, 0, False),
      "sleeveTipLength": cls._genParameters("", "", 0.0, "mm", 0, 100, 1, 5, 0, False),
      "sleeveArcLength": cls._genParameters("", "", 20.0, "mm", 0, 100, 1, 5, 0, False),
      "sleeveMarker1DistanceFromTip": cls._genParameters("", "", 20.0, "mm", 0, 100, 1, 5, 0, False), #TODO: Applies for generic device too?
      "sleeveMarker2DistanceFromTip": cls._genParameters("", "", 30.0, "mm", 0, 100, 1, 5, 0, False), #TODO: Applies for generic device too?
      "sleeveMarkerWidth": cls._genParameters("", "", 1.5, "mm", 0, 100, 0.5, 5, 0, False), #TODO: Applies for generic device too?
      "sleeveDiameter": cls._genParameters("", "", 5.3, "mm", 0, 100, 0.5, 5, 0, False),
      "catheterDiameter": cls._genParameters("", "", 2.5, "mm", 0, 100, 0.5, 5, 0, False),

      # Hidden threshold parameters
      "guideClinicalCurvatureThreshold": cls._genParameters("", "", 0.025, "mm-1", 0, 10, 0.005, 1, 0, False),
      "guidePhysicalCurvatureThreshold": cls._genParameters("", "", 0.05, "mm-1", 0, 10, 0.005, 1, 0, False),
      "catheterClinicalCurvatureThreshold": cls._genParameters("", "", 0.05, "mm-1", 0, 10, 0.005, 1, 0, False),
      "catheterPhysicalCurvatureThreshold": cls._genParameters("", "", 0.1, "mm-1", 0, 10, 0.005, 1, 0, False),
    }

  @classmethod
  def updateModel(cls, modelNode, parameterNode):
    super(MitraClipG4Base, cls).updateModel(modelNode, parameterNode)

    slicer.app.applicationLogic().PauseRender()

    # Get parameters
    parameterValues = cls.getParameterValuesFromNode(parameterNode)
    # Get models
    if not cls.CLIP_WING_POLYDATA:
      reader = vtk.vtkSTLReader()
      reader.SetFileName(os.path.join(cls.RESOURCES_PATH, "Models", cls.CLIP_WING_FILENAME))
      normals = vtk.vtkPolyDataNormals()
      normals.SetInputConnection(reader.GetOutputPort())
      normals.Update()
      cls.CLIP_WING_POLYDATA = normals.GetOutput()
    if cls.CLIP_GRIPPER_FILENAME and not cls.CLIP_GRIPPER_POLYDATA:
      reader = vtk.vtkSTLReader()
      reader.SetFileName(os.path.join(cls.RESOURCES_PATH, "Models", cls.CLIP_GRIPPER_FILENAME))
      normals = vtk.vtkPolyDataNormals()
      normals.SetInputConnection(reader.GetOutputPort())
      normals.Update()
      cls.CLIP_GRIPPER_POLYDATA = normals.GetOutput()
    if not cls.CLIP_BASE_POLYDATA:
      reader = vtk.vtkSTLReader()
      reader.SetFileName(os.path.join(cls.RESOURCES_PATH, "Models", "Mitraclip_common_base.stl"))
      normals = vtk.vtkPolyDataNormals()
      normals.SetInputConnection(reader.GetOutputPort())
      normals.Update()
      cls.CLIP_BASE_POLYDATA = normals.GetOutput()
    # Create model
    appender = vtk.vtkAppendPolyData()
    wingOpeningAngleDeg = parameterValues["wingOpeningAngleDeg"]
    independentWingOpeningAngleDeg = parameterValues["independentWingOpeningAngleDeg"]
    # Wing 1
    wingTransformer1 = vtk.vtkTransformPolyDataFilter()
    wingTransformer1.SetInputData(cls.CLIP_WING_POLYDATA)
    wingTransform1_TranslateToOrigin = vtk.vtkTransform()
    wingTransform1_TranslateToOrigin.Translate(0,-2.5,0)
    wingTransform1_Rotation = vtk.vtkTransform()
    wingTransform1_Rotation.RotateX(wingOpeningAngleDeg/2.0)
    wingTransform1_TranslateFromOrigin = vtk.vtkTransform()
    wingTransform1_TranslateFromOrigin.Translate(0,2.5,0)
    wingTransform1 = vtk.vtkTransform()
    wingTransform1.Concatenate(wingTransform1_TranslateToOrigin)
    wingTransform1.Concatenate(wingTransform1_Rotation)
    wingTransform1.Concatenate(wingTransform1_TranslateFromOrigin)
    wingTransformer1.SetTransform(wingTransform1)
    appender.AddInputConnection(wingTransformer1.GetOutputPort())
    # Wing 2
    wing2OpeningAngleDeg = independentWingOpeningAngleDeg if independentWingOpeningAngleDeg > -1 else wingOpeningAngleDeg
    wingTransformer2 = vtk.vtkTransformPolyDataFilter()
    wingTransformer2.SetInputData(cls.CLIP_WING_POLYDATA)
    wingTransform2_Mirror = vtk.vtkTransform()
    wingTransform2_Mirror.Scale(1,-1,1) # mirror Y
    wingTransform2_TranslateToOrigin = vtk.vtkTransform()
    wingTransform2_TranslateToOrigin.Translate(0,-2.5,0)
    wingTransform2_Rotation = vtk.vtkTransform()
    wingTransform2_Rotation.RotateX(wing2OpeningAngleDeg/2.0)
    wingTransform2_TranslateFromOrigin = vtk.vtkTransform()
    wingTransform2_TranslateFromOrigin.Translate(0,2.5,0)
    wingTransform2 = vtk.vtkTransform()
    wingTransform2.Concatenate(wingTransform2_Mirror)
    wingTransform2.Concatenate(wingTransform2_TranslateToOrigin)
    wingTransform2.Concatenate(wingTransform2_Rotation)
    wingTransform2.Concatenate(wingTransform2_TranslateFromOrigin)
    wingTransformer2.SetTransform(wingTransform2)
    reverser = vtk.vtkReverseSense()
    reverser.SetInputConnection(wingTransformer2.GetOutputPort())
    appender.AddInputConnection(reverser.GetOutputPort())
    if cls.CLIP_GRIPPER_FILENAME:
      gripperOpeningAngleDeg = parameterValues["gripperOpeningAngleDeg"]
      independentGripperOpeningAngleDeg = parameterValues["independentGripperOpeningAngleDeg"]
      # Gripper 1
      gripperTransformer1 = vtk.vtkTransformPolyDataFilter()
      gripperTransformer1.SetInputData(cls.CLIP_GRIPPER_POLYDATA)
      gripperTransform1 = vtk.vtkTransform()
      gripperTransform1.RotateX(gripperOpeningAngleDeg/2.0)
      gripperTransformer1.SetTransform(gripperTransform1)
      appender.AddInputConnection(gripperTransformer1.GetOutputPort())
      # Gripper 2
      gripper2OpeningAngleDeg = independentGripperOpeningAngleDeg if independentGripperOpeningAngleDeg > -1 else gripperOpeningAngleDeg
      gripperTransformer2 = vtk.vtkTransformPolyDataFilter()
      gripperTransformer2.SetInputData(cls.CLIP_GRIPPER_POLYDATA)
      gripperTransform2 = vtk.vtkTransform()
      gripperTransform2.Scale(1,-1,1) # mirror Y
      gripperTransform2.RotateX(gripper2OpeningAngleDeg/2.0)
      gripperTransformer2.SetTransform(gripperTransform2)
      reverser = vtk.vtkReverseSense()
      reverser.SetInputConnection(gripperTransformer2.GetOutputPort())
      appender.AddInputConnection(reverser.GetOutputPort())
    # Base
    appender.AddInputData(cls.CLIP_BASE_POLYDATA)
    # Update model
    appender.Update()
    modelNode.SetAndObservePolyData(appender.GetOutput())

    cls.applyTexture(modelNode)

    slicer.app.applicationLogic().ResumeRender()

  @classmethod
  def applyTexture(cls, modelNode):
    #TODO: Calculate texture mapping on the parts individually for nicer and more consistent texture display

    if not cls.APPLY_FABRIC_TEXTURE:
      if cls.FABRIC_TEXTURE_IMAGE_DATA is not None:
        cls.FABRIC_TEXTURE_IMAGE_DATA = None
        modelNode.GetDisplayNode().SetTextureImageDataConnection(None)
      return

    if cls.FABRIC_TEXTURE_IMAGE_DATA is None:
      # Read texture if needed
      reader = vtk.vtkJPEGReader()
      reader.SetFileName(os.path.join(cls.RESOURCES_PATH, "Models", "Texture_FabricBurlapWhite.jpg"))
      reader.Update()
      cls.FABRIC_TEXTURE_IMAGE_DATA = reader.GetOutput()

    # Calculate and set texture coordinates
    textureMap = vtk.vtkTextureMapToCylinder()
    textureMap.SetInputData(modelNode.GetPolyData())
    textureMap.Update()
    modelNode.SetAndObservePolyData(textureMap.GetOutput())

    trivialProducer = vtk.vtkTrivialProducer()
    trivialProducer.SetOutput(cls.FABRIC_TEXTURE_IMAGE_DATA)
    modelNode.GetDisplayNode().SetTextureImageDataConnection(trivialProducer.GetOutputPort())

class MitraClipG4NT(MitraClipG4Base):

  NAME = "MitraClipG4NT"
  ID = "MitraClipG4NT"

  CLIP_WING_FILENAME = 'G4NT_wing.stl'
  CLIP_GRIPPER_FILENAME = 'G4NT_grippers.stl'

class MitraClipG4NTW(MitraClipG4Base):

  NAME = "MitraClipG4NTW"
  ID = "MitraClipG4NTW"

  CLIP_WING_FILENAME = 'G4NTW_wing.stl'
  CLIP_GRIPPER_FILENAME = 'G4NT_grippers.stl'

class MitraClipG4XT(MitraClipG4Base):

  NAME = "MitraClipG4XT"
  ID = "MitraClipG4XT"

  CLIP_WING_FILENAME = 'G4XT_wing.stl'
  CLIP_GRIPPER_FILENAME = 'G4XT_grippers.stl'

class MitraClipG4XTW(MitraClipG4Base):

  NAME = "MitraClipG4XTW"
  ID = "MitraClipG4XTW"

  CLIP_WING_FILENAME = 'G4XTW_wing.stl'
  CLIP_GRIPPER_FILENAME = 'G4XT_grippers.stl'
