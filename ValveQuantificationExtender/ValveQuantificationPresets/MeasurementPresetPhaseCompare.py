import vtk, qt, ctk, slicer
import math
import numpy as np
import HeartValveLib

from ValveQuantificationLib.MeasurementPreset import *


class MeasurementPresetPhaseCompare(MeasurementPreset):

  def __init__(self):
    super(MeasurementPresetPhaseCompare, self).__init__()
    self.id = "PhaseCompare"
    self.name = "Phase compare"
    self.inputValveIds = ["Valve1", "Valve2", "Valve3", "Valve4"]
    self.inputValveNames = { "Valve1": "Valve in mid-systole phase",
                             "Valve2": "Valve in end-systole phase",
                             "Valve3": "Valve in mid-diastole phase",
                             "Valve4": "Valve in end-diastole phase"}
    self.inputValveShortNames = { "Valve1": "MS",
                                  "Valve2": "ES",
                                  "Valve3": "MD",
                                  "Valve4": "ED"}
    self.inputFieldsComment = "To measure distances between reference points:\nspecify reference points with the same names for each valve\nin separate measurements."
    #TODO: create a definition file
    #self.definitionsUrl = self.getResourceFileUrl("")

  def createChordsModel(self, modelName, startPoints, endPoints, radius=0.25, color=None, visibility=False):
    """
    Create a line model (thin slab)
    :param modelName: Name of the created model node
    :param startPoints: chord starting points
    :param endPoints: chord endpoints
    :param radius: radius of the line tube
    :param color: color of the line
    :return: MRML model node
    """
    if not color:
      color = [1.0, 1.0, 0.0]

    numberOfChords = startPoints.shape[1]

    # Points and lines
    points = vtk.vtkPoints()
    points.SetNumberOfPoints(numberOfChords*2)
    lines = vtk.vtkCellArray()
    for chordIndex in range(numberOfChords):
      points.SetPoint(chordIndex * 2, startPoints[:,chordIndex])
      points.SetPoint(chordIndex * 2 + 1, endPoints[:,chordIndex])
      lines.InsertNextCell(2)
      lines.InsertCellPoint(chordIndex * 2)
      lines.InsertCellPoint(chordIndex * 2 + 1)

    # Polydata
    linesPolyData = vtk.vtkPolyData()
    linesPolyData.SetPoints(points)
    linesPolyData.SetLines(lines)

    tubeFilter = vtk.vtkTubeFilter()
    tubeFilter.SetInputData(linesPolyData)
    tubeFilter.SetNumberOfSides(8) # improve rendering quality
    tubeFilter.SetRadius(radius)

    modelsLogic = slicer.modules.models.logic()
    tubeFilter.Update()
    modelNode = modelsLogic.AddModel(tubeFilter.GetOutput())
    modelNode.SetName(modelName)
    modelNode.GetDisplayNode().SetVisibility(visibility)
    modelNode.GetDisplayNode().SetColor(color)
    #modelNode.GetDisplayNode().LightingOff() # don't make the line edges darker

    return modelNode

  def getChords(self, valveModel, curveSegmentLength, startPointIndex, endPointIndex, interpolatedPoints,
                requestedDistanceBetweenChords=-1, numberOfChords=-1):
    if requestedDistanceBetweenChords > 0:
      numberOfChords = round(curveSegmentLength/requestedDistanceBetweenChords)
      if numberOfChords<=0:
        return [None, None]
    # Extract the curve segment that is between the start and end points for annulus1
    samplingDistance = curveSegmentLength/numberOfChords
    sampledInterpolatedPoints = valveModel.annulusContourCurve.getSampledInterpolatedPointsBetweenStartEndPointsAsArray(
      interpolatedPoints, samplingDistance, startPointIndex, endPointIndex)
    sampledInterpolatedPoints = sampledInterpolatedPoints[:,:numberOfChords]
    return [sampledInterpolatedPoints, numberOfChords]

  def getSignedDislocationMagnitudesInDirection(self, dislocations, referenceDirections):
    if len(referenceDirections.shape) == 1:
      # same direction is used for all dislocations
      referenceDirection = referenceDirections / np.linalg.norm(referenceDirections)
      dislocationsInReferenceDirections = np.dot(dislocations.T, referenceDirection)
    else:
      dislocationsInReferenceDirections = np.diag(np.dot((referenceDirections/np.linalg.norm(referenceDirections, axis=0)).T, dislocations))
    return dislocationsInReferenceDirections

  def getDislocationsComponentsSignedMagnitudes(self, interpolatedPoints1, interpolatedPoints2, valvePlanePosition, valvePlaneNormal):
    """ Get dislocated mean values relative to the valve. Radial/tangential direction is computed for each chord separately
    and then averaged. Relative to the valve means a coordinate system where:
    x: tangential
    y: radial (positive is dilation)
    z: plane normal
    :param interpolatedPoints1:
    :param interpolatedPoints2:
    :param valvePlanePosition:
    :param valvePlaneNormal:
    :return: [meanDislocationMagnitudeTangential, meanDislocationMagnitudeRadial, meanDislocationMagnitudePlaneNormal]
    """

    directionsFromCentroid = (interpolatedPoints1+interpolatedPoints2)/2.0 - valvePlanePosition.reshape(-1,1)
    tangentialDirections = np.cross(directionsFromCentroid, valvePlaneNormal, axis=0)
    radialDirections = np.cross(valvePlaneNormal, tangentialDirections, axis=0)

    # Column-wise dot product of a, b = np.diag(np.dot(a.T, b))
    dislocations = (interpolatedPoints2-interpolatedPoints1)
    dislocationsTangential = self.getSignedDislocationMagnitudesInDirection(dislocations, tangentialDirections)
    dislocationsRadial = self.getSignedDislocationMagnitudesInDirection(dislocations, radialDirections)
    dislocationsPlaneNormal = self.getSignedDislocationMagnitudesInDirection(dislocations, valvePlaneNormal)

    return [dislocationsTangential, dislocationsRadial, dislocationsPlaneNormal]

  def getCommonAnnulusMarkupLabelsForPhaseComparison(self, valveModel1, valveModel2):
    """ Return a list of common label lists that can be used for phase comparison.

        If phase comparison labels are predefined for the valve type, use these labels
        else return a list of labels available in both valves

    :param valveModel1: HeartValveLib.ValveModel
    :param valveModel2: HeartValveLib.ValveModel
    :return: list of labels that will be used for phase comparison
    """
    assert valveModel1.getValveType() == valveModel2.getValveType()
    labels1 = valveModel1.getAnnulusMarkupLabels()
    labels2 = valveModel2.getAnnulusMarkupLabels()

    commonLabels = list(set(labels1) & set(labels2))  # labels found in both valveModel1 and valveModel2

    # Common labels specified for phase comparison
    # For example, CAVC curve has many 6 points but we only want to use 4 of them for phase comparison chords.
    phaseComparePointLabels = valveModel1.valveTypePresets[valveModel1.getValveType()]["phaseComparePointLabels"]
    if phaseComparePointLabels:
      return list(set(commonLabels) & set(phaseComparePointLabels))
    else:
      return commonLabels

  def getDifferenceBetweenAnnulusContours(self, valveModel1, valvePlane1, valveModel2, valvePlane2, name,
                                          splitBetweenPoints, annulusMarkupLabels):
    """
    splitBetweenPoints: True if contours should be split halfway between points
    """
    import numpy as np
    valvePlanePosition1 = valvePlane1[0]
    valvePlanePosition2 = valvePlane2[0]
    valvePlaneNormal1 = valvePlane1[1]
    valvePlaneNormal2 = valvePlane2[1]

    curveSegments1 = valveModel1.getAnnulusContourCurveSegments(annulusMarkupLabels, splitBetweenPoints=splitBetweenPoints)
    curveSegments2 = valveModel2.getAnnulusContourCurveSegments(annulusMarkupLabels, splitBetweenPoints=splitBetweenPoints)

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    shSubfolderId = shNode.CreateFolderItem(shNode.GetItemByDataNode(self.folderNode),
      name + ' (' + ('-'.join(annulusMarkupLabels)) + ') details')
    shNode.SetItemExpanded(shSubfolderId, False)

    measurements = []
    #requestedDistanceBetweenChords = 1.0
    numberOfChords = 10

    # Create displacements table
    displacementsTable = slicer.vtkMRMLTableNode()
    displacementsTable.SetName(name + ' values')
    displacementTableLabels = displacementsTable.AddColumn()
    displacementTableLabels.SetName('Region')
    displacementTableAngleDeg = vtk.vtkDoubleArray()
    displacementTableAngleDeg.SetName('Angle [deg]')
    displacementsTable.AddColumn(displacementTableAngleDeg)
    displacementTableAngleTotal = vtk.vtkDoubleArray()
    displacementTableAngleTotal.SetName('Displacement [mm]')
    displacementsTable.AddColumn(displacementTableAngleTotal)
    displacementTableAnglePlaneNormal = vtk.vtkDoubleArray()
    displacementTableAnglePlaneNormal.SetName('Displacement (valve plane normal) [mm]')
    displacementsTable.AddColumn(displacementTableAnglePlaneNormal)
    displacementTableAnglePlaneRadial = vtk.vtkDoubleArray()
    displacementTableAnglePlaneRadial.SetName('Displacement (radial) [mm]')
    displacementsTable.AddColumn(displacementTableAnglePlaneRadial)
    slicer.mrmlScene.AddNode(displacementsTable)
    self.moveNodeToMeasurementFolder(displacementsTable)

    for labelIndex in range(len(curveSegments1)):
      curveSegment1 = curveSegments1[labelIndex]
      curveSegment2 = curveSegments2[labelIndex]
      label = curveSegment1["label"]

      # Get curve segment length for annulus1
      [interpolatedPointsAfter1, numberOfChordsAfter] = self.getChords(valveModel1, curveSegment1["segmentLengthAfter"],
                       curveSegment1["closestPointIdOnAnnulusCurve"],
                       curveSegment1["segmentEndPointId"],
                       valveModel1.annulusContourCurve.getInterpolatedPointsAsArray(),
                       #requestedDistanceBetweenChords=requestedDistanceBetweenChords,
                       numberOfChords=numberOfChords if splitBetweenPoints else numberOfChords*2)
      if interpolatedPointsAfter1 is None:
        continue

      if splitBetweenPoints:
        [interpolatedPointsBefore1, numberOfChordsBefore] = self.getChords(valveModel1, curveSegment1["segmentLengthBefore"],
                         curveSegment1["segmentStartPointId"],
                         curveSegment1["closestPointIdOnAnnulusCurve"],
                         valveModel1.annulusContourCurve.getInterpolatedPointsAsArray(),
                         #requestedDistanceBetweenChords=requestedDistanceBetweenChords
                         numberOfChords=numberOfChords if splitBetweenPoints else numberOfChords*2)
        if interpolatedPointsBefore1 is None:
          continue
        interpolatedPoints1 = np.hstack((interpolatedPointsBefore1,interpolatedPointsAfter1))
        landmarkPointIndex1 = interpolatedPointsBefore1.shape[1]
      else:
        interpolatedPoints1 = interpolatedPointsAfter1
        landmarkPointIndex1 = 0

      [interpolatedPointsAfter2, numberOfChordsAfter] = self.getChords(valveModel2, curveSegment2["segmentLengthAfter"],
                       curveSegment2["closestPointIdOnAnnulusCurve"],
                       curveSegment2["segmentEndPointId"],
                       valveModel2.annulusContourCurve.getInterpolatedPointsAsArray(),
                       numberOfChords=numberOfChordsAfter)
      if interpolatedPointsAfter2 is None:
        continue
      if splitBetweenPoints:
        # Get curve segment length for annulus2
        [interpolatedPointsBefore2, numberOfChordsBefore] = self.getChords(valveModel2,
                                                                           curveSegment2["segmentLengthBefore"],
                                                                           curveSegment2["segmentStartPointId"],
                                                                           curveSegment2[
                                                                             "closestPointIdOnAnnulusCurve"],
                                                                           valveModel2.annulusContourCurve.getInterpolatedPointsAsArray(),
                                                                           numberOfChords=numberOfChordsBefore)
        if interpolatedPointsBefore2 is None:
          continue
        interpolatedPoints2 = np.hstack((interpolatedPointsBefore2, interpolatedPointsAfter2))
      else:
        interpolatedPoints2 = interpolatedPointsAfter2


      probeToRasTransformNode = valveModel1.getProbeToRasTransformNode()

      chordsModelNode = self.createChordsModel("{0} {1} chords".format(name, label),
                             interpolatedPoints1, interpolatedPoints2, radius=0.1, color=[1.0, 1.0, 1.0])
      shNode.SetItemParent(shNode.GetItemByDataNode(chordsModelNode), shSubfolderId)
      chordsModelNode.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)

      valvePlanePosition = (valvePlanePosition1+valvePlanePosition2)/2.0
      valvePlaneNormal = (valvePlaneNormal1 + valvePlaneNormal2) / 2.0
      valvePlaneNormal = valvePlaneNormal / np.linalg.norm(valvePlaneNormal)

      averageInterpolatedPoints = (interpolatedPoints1 + interpolatedPoints2)/2
      [averageInterpolatedPointsProjected, averageInterpolatedPointsProjected_Plane, unused] = \
        HeartValveLib.getPointsProjectedToPlane(averageInterpolatedPoints, valvePlanePosition, valvePlaneNormal)

      # Components:
      # x: tangential
      # y: radial (positive is dilation)
      # z: plane normal
      [dislocationsTangential, dislocationsRadial, dislocationsPlaneNormal] = \
        self.getDislocationsComponentsSignedMagnitudes(interpolatedPoints1, interpolatedPoints2, valvePlanePosition, valvePlaneNormal)
      dislocations = interpolatedPoints2 - interpolatedPoints1

      if splitBetweenPoints:
        # centered, so the landmark position is a good representative of center point
        landmark1 = np.array(curveSegment1["closestPointPositionOnAnnulusCurve"])
      else:
        # between two landmark points, so use the mean start position
        landmark1 = interpolatedPoints1.mean(1)
      directionFromCentroid = (landmark1-valvePlanePosition)/np.linalg.norm(landmark1-valvePlanePosition)
      tangentialDirection = np.cross(directionFromCentroid, valvePlaneNormal)
      radialDirection = np.cross(valvePlaneNormal, tangentialDirection)

      if labelIndex == 0:
        # Determine starting angle (position of first landmark)
        firstLandmarkPointIndex = landmarkPointIndex1
        # This angle will be shown as 0 in the result:
        zeroAngleRad = math.atan2(averageInterpolatedPointsProjected_Plane[1,firstLandmarkPointIndex], averageInterpolatedPointsProjected_Plane[0,firstLandmarkPointIndex])
        # This angle will be the shown smallest value. Final angle range will be [minimumAngleRad,minimumAngleRad+2*pi].
        minimumAngleRad = math.atan2(averageInterpolatedPointsProjected_Plane[1,0], averageInterpolatedPointsProjected_Plane[0,0]) - zeroAngleRad
        # angleIncreaseSign will be used as a multiplier to make sure angle is always increasing
        angleIncreaseSign = 1 if minimumAngleRad < zeroAngleRad else -1
        minimumAngleRad *= angleIncreaseSign

      for pointIndex in range(interpolatedPoints1.shape[1]):
        displacementTableLabels.InsertNextValue(label)
        angleRad = angleIncreaseSign * (math.atan2(averageInterpolatedPointsProjected_Plane[1,pointIndex], averageInterpolatedPointsProjected_Plane[0,pointIndex]) - zeroAngleRad)
        # if angleRad < minimumAngleRad:
        #   angleRad += 2*math.pi
        # elif angleRad > minimumAngleRad + 2 * math.pi:
        #   angleRad -= 2*math.pi
        if angleRad < 0:
          angleRad += 2 * math.pi
        elif angleRad > 2 * math.pi:
          angleRad -= 2 * math.pi
        displacementTableAngleDeg.InsertNextValue(angleRad*180.0/math.pi)
        displacementTableAngleTotal.InsertNextValue(np.linalg.norm(dislocations[:,pointIndex]))
        displacementTableAnglePlaneNormal.InsertNextValue(dislocationsPlaneNormal[pointIndex])
        displacementTableAnglePlaneRadial.InsertNextValue(dislocationsRadial[pointIndex])

      # Mean dislocation - total
      meanDislocation = dislocations.mean(1)
      measurements.append(self.getDistanceBetweenPoints(valveModel1, "", valveModel2, "",
        name="{0} {1} mean".format(name, label),
        point1_valveModel1=landmark1,
        point2_valveModel2=landmark1+meanDislocation,
        oriented=True,
        shParentFolderId = shSubfolderId))

      # Mean dislocation - tangential direction
      # measurements.append(self.getDistanceBetweenPoints(valveModel1, "", valveModel2, "",
      #   name="{0} {1} mean (tangential)".format(name, label),
      #   point1_valveModel1=landmark1,
      #   point2_valveModel2=landmark1+tangentialDirection*dislocationsTangential.mean(),
      #   oriented=True, positiveDirection_valveModel1=tangentialDirection))

      # Mean dislocation - radial direction
      measurements.append(self.getDistanceBetweenPoints(valveModel1, "", valveModel2, "",
        name="{0} {1} mean (radial)".format(name, label),
        point1_valveModel1=landmark1,
        point2_valveModel2=landmark1+radialDirection*dislocationsRadial.mean(),
        oriented=True, positiveDirection_valveModel1=directionFromCentroid,
        shParentFolderId=shSubfolderId))

      # Mean dislocation - parallel to plane normal component
      measurements.append(self.getDistanceBetweenPoints(valveModel1, "", valveModel2, "",
        name="{0} {1} mean (valve plane normal)".format(name, label),
        point1_valveModel1=landmark1,
        point2_valveModel2=landmark1+valvePlaneNormal*dislocationsPlaneNormal.mean(),
        oriented=True, positiveDirection_valveModel1=valvePlaneNormal,
        shParentFolderId=shSubfolderId))

    # Rotate displacement table rows to make it start with angle = 0
    columns = [displacementTableLabels, displacementTableAngleDeg, displacementTableAngleTotal, displacementTableAnglePlaneNormal, displacementTableAnglePlaneRadial]
    rowCount = displacementsTable.GetNumberOfRows()
    for column in columns:
      columnOriginal = column.CreateArray(column.GetDataType())
      columnOriginal.DeepCopy(column)
      for rowIndex in range(rowCount):
        newIndex = (rowIndex-firstLandmarkPointIndex) % rowCount
        column.SetValue(newIndex, columnOriginal.GetValue(rowIndex))

    return measurements

  def addValvePair(self, valvePairsToCompare, availableValveIds, valve1ShortName, valve2ShortName):
    valve1Id = list(self.inputValveShortNames.keys())[list(self.inputValveShortNames.values()).index(valve1ShortName)]
    valve2Id = list(self.inputValveShortNames.keys())[list(self.inputValveShortNames.values()).index(valve2ShortName)]
    if not (valve1Id in availableValveIds and valve2Id in availableValveIds):
      # Cannot add valve pair, one or both are not available
      return
    for valvePairToCompare in valvePairsToCompare:
      if valvePairToCompare[0] == valve1Id and valvePairToCompare[1] == valve2Id:
        # already added, no need to add again
        return
    valvePairsToCompare.append([valve1Id, valve2Id])


  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetPhaseCompare, self).computeMetrics(inputValveModels, outputTableNode)

    # Determine which pairs of valves we can compare
    # Get list of available valve IDs
    availableValveIds = []
    for valveId in self.inputValveIds:
      if valveId in inputValveModels.keys():
        availableValveIds.append(valveId)
    if len(availableValveIds)<2:
      return ["Selection of at least two valves are required"]
    # Generate a list of valve ID pairs (each valve is compared to the next one)
    valvePairsToCompare = []
    self.addValvePair(valvePairsToCompare, availableValveIds, "ED", "MS")
    self.addValvePair(valvePairsToCompare, availableValveIds, "ED", "ES")
    self.addValvePair(valvePairsToCompare, availableValveIds, "MS", "ES")
    self.addValvePair(valvePairsToCompare, availableValveIds, "MD", "ES")

    valvePlanes = {}
    # plane normal direction will be determined from the first contour
    # and all the other plane normals will be directed similarly
    for valveId in availableValveIds:
      valveModel = inputValveModels[valveId]
      [planePosition, planeNormal] = valveModel.getAnnulusContourPlane()
      valvePlanes[valveId] = [planePosition, planeNormal]
      annulusPoints = valveModel.annulusContourCurve.getInterpolatedPointsAsArray()
      self.createAnnulusPlaneModel(valveModel, annulusPoints, planePosition, planeNormal,
                                   name="{0} annulus plane".format(self.inputValveShortNames[valveId]))
      # Add centroid point. This makes sure centroid distances will be computed.
      if valveModel.getAnnulusMarkupPositionByLabel('C') is None:
        valveModel.setAnnulusMarkupLabel('C', planePosition)

    # Add measurement results between each pair of points
    for valvePairToCompare in valvePairsToCompare:
      valveModel1 = inputValveModels[valvePairToCompare[0]]
      valve1ShortName = self.inputValveShortNames[valvePairToCompare[0]]
      valveModel2 = inputValveModels[valvePairToCompare[1]]
      valve2ShortName = self.inputValveShortNames[valvePairToCompare[1]]

      # Add plane angle
      planePosition1 = valvePlanes[valvePairToCompare[0]][0]
      planeNormal1 = valvePlanes[valvePairToCompare[0]][1]
      planePosition2 = valvePlanes[valvePairToCompare[1]][0]
      planeNormal2 = valvePlanes[valvePairToCompare[1]][1]

      self.addMeasurement(self.getAngleBetweenPlanes(valveModel1, planePosition1, planeNormal1,
                                                      valveModel1, planePosition2, planeNormal2,
                                                      '{0}-{1} plane angle'.format(valve1ShortName , valve2ShortName)))

      # Distances between each labeled points
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      referencePointsDistancesSubfolderName = "{0}-{1} reference points distance".format(valve1ShortName, valve2ShortName)
      referencePointsDistancesSubfolderId = shNode.CreateFolderItem(shNode.GetItemByDataNode(self.folderNode), referencePointsDistancesSubfolderName)
      shNode.SetItemExpanded(referencePointsDistancesSubfolderId, False)
      labels = valveModel1.getAllMarkupLabels()
      for label in labels:
        displayedName = "{0} point {1}-{2} distance".format(label, valve1ShortName , valve2ShortName)
        self.addMeasurement(self.getDistanceBetweenPoints(valveModel1, label, valveModel2, label, name = displayedName, shParentFolderId=referencePointsDistancesSubfolderId))

      # Distances between annulus contours
      displayedName = "{0}-{1} annulus displacement".format(valve1ShortName, valve2ShortName)

      phaseComparisonLabels = self.getCommonAnnulusMarkupLabelsForPhaseComparison(valveModel1, valveModel2)

      for splitBetweenPoints in [True, False]: # centered (split halfway between points) / not centered (split at points)
          nameSuffix = " centered" if splitBetweenPoints else " between"
          measurements = self.getDifferenceBetweenAnnulusContours(
            valveModel1, valvePlanes[valvePairToCompare[0]], valveModel2, valvePlanes[valvePairToCompare[1]],
            displayedName+nameSuffix,
            splitBetweenPoints, phaseComparisonLabels)
          for measurement in measurements:
            self.addMeasurement(measurement)

    return self.metricsMessages
