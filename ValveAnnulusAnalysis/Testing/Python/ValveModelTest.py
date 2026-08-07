"""
ValveModelTest.py

Tests for the scripting helpers added to HeartValveLib.ValveModel:
  - addAnnulusContourCurve / removeAnnulusContourCurve
  - setAnnulusContourPoints
  - setValveLabels
  - initializeLeafletSegmentation

It also confirms that the ValveSegmentation and ValveQuantification modules can be set up and run
on the resulting valve nodes through their logic methods (no GUI); only that the setup succeeds is
checked, not the numeric results.

The helpers are exercised on a real downloaded ultrasound volume sequence (the SlicerHeart
'Mitral' sample). Mirroring ValveAnnulusAnalysisTest, the volume sequence is downloaded once and a
single valve (annotation) sequence browser is created per valve scenario: one mitral valve and one
aortic valve. Each scenario walks through the full helper workflow with anatomically meaningful
points placed on that valve's annulus.
"""

import vtk, slicer
from slicer.ScriptedLoadableModule import *


class ValveModelTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ValveModelTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = [
      "ValveAnnulusAnalysis", "ValveSegmentation", "ValveQuantification", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for HeartValveLib.ValveModel scripting helpers."
    self.parent.acknowledgementText = ""


class ValveModelTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class ValveModelTestLogic(ScriptedLoadableModuleLogic):
  pass


# ---------------------------------------------------------------------------

class ValveModelTestTest(ScriptedLoadableModuleTest):
  """Test cases for HeartValveLib.ValveModel scripting helpers."""

  # Realistic annulus contour control points (RAS), taken from the ValveAnnulusAnalysis self-test
  # (ValveAnnulusAnalysisTest). With the "TTE_APICAL" probe position these points lie on the
  # respective valve annulus of the downloaded Mitral_US volume, so the markups placed by the tests
  # are anatomically meaningful rather than arbitrary. Two slightly different contours (captured at
  # two cardiac frames) are used to verify per-time-point behavior.
  MITRAL_ANNULUS_CONTOUR_FRAME0 = [
    [86.98819733, 84.78613281, 99.99595642],
    [87.25099182, 92.59313202, 96.04943085],
    [91.62657166, 100.28668976, 95.93429565],
    [99.54394531, 103.84978485, 97.02439117],
    [108.43112183, 102.99208069, 97.06322479],
    [116.29380035, 98.95796204, 96.59480286],
    [119.38338470, 90.87751770, 95.25667572],
    [117.54264832, 82.43365479, 93.17087555],
    [111.96864319, 75.62635040, 92.28639984],
    [104.68697357, 72.24358368, 95.78388977],
    [98.42464447, 73.57678986, 101.90380859],
    [91.83489990, 78.74420166, 104.18357086],
  ]
  MITRAL_ANNULUS_CONTOUR_FRAME1 = [
    [87.24764147, 84.88706671, 100.12486271],
    [86.76681083, 92.47491454, 93.31991339],
    [90.77637954, 100.06069485, 94.41986783],
    [99.65055568, 103.90832343, 96.47194101],
    [108.37462656, 103.01181134, 95.55523894],
    [115.91622973, 98.89828314, 93.31283524],
    [119.29093789, 90.90980422, 92.78906251],
    [117.09441886, 82.30288144, 91.40098545],
    [112.75891091, 74.96626165, 90.98602426],
    [104.02038744, 71.99752687, 94.98181036],
    [97.61549643, 73.28475034, 100.69455198],
    [92.43985483, 79.01178282, 103.34057479],
  ]
  AORTIC_ANNULUS_CONTOUR_FRAME0 = [
    [87.46756744, 79.60205078, 104.07534027],
    [93.12380981, 77.26019287, 104.36550140],
    [97.81135559, 73.91616058, 102.28562927],
    [99.61608124, 69.64796448, 98.37429047],
    [97.99498749, 65.67282104, 93.99780273],
    [94.39620972, 63.33256149, 89.61905670],
    [89.01432037, 63.26695633, 86.80841064],
    [83.31873322, 65.43260193, 87.06101990],
    [79.13238525, 69.24201202, 89.41408539],
    [77.02110291, 73.69961548, 93.07071686],
    [77.78422546, 77.62684631, 97.65192413],
    [81.85909271, 79.77548218, 101.64229584],
  ]
  AORTIC_ANNULUS_CONTOUR_FRAME1 = [
    [99.06072037, 66.76962402, 95.04010257],
    [94.54263497, 63.70303658, 90.29506546],
    [89.95670242, 62.53853856, 87.27035723],
    [82.84905796, 63.50898720, 85.13467754],
    [78.16684960, 67.50735328, 86.81692004],
    [76.21692245, 72.38806095, 90.47465910],
    [76.09617999, 76.70760317, 94.39563487],
    [78.01371648, 79.19176674, 97.49711452],
    [83.72543241, 80.99407078, 101.58800252],
    [89.38005949, 80.82862375, 103.84494893],
    [93.11443156, 78.08531071, 102.91308515],
    [95.25182062, 75.42542061, 101.37756150],
  ]

  # The same workflow runs for every entry below; only the data (valve type and its two annulus
  # contours) differs. Add a valve type here to cover it - no new test code is required.
  VALVE_TEST_CASES = {
    "mitral": (MITRAL_ANNULUS_CONTOUR_FRAME0, MITRAL_ANNULUS_CONTOUR_FRAME1),
    "aortic": (AORTIC_ANNULUS_CONTOUR_FRAME0, AORTIC_ANNULUS_CONTOUR_FRAME1),
  }

  @classmethod
  def _annulusLandmarkLabels(cls, contourPoints):
    """Standard quadrant landmarks (A=anterior, L=lateral, P=posterior, S=septal) placed on the
    annulus by sampling four roughly evenly spaced points from *contourPoints*.

    :returns: list of ``(label, r, a, s)`` tuples suitable for ValveModel.setValveLabels.
    """
    quadrantLabels = ["A", "L", "P", "S"]
    return [(label, *contourPoints[i * (len(contourPoints) // len(quadrantLabels))])
            for i, label in enumerate(quadrantLabels)]

  # -------------------------------------------------------------------------
  # Test fixture
  # -------------------------------------------------------------------------

  def setUp(self):
    slicer.mrmlScene.Clear(0)
    self.volumeSequenceBrowserNode = self._loadVolumeSequence()

  def _loadVolumeSequence(self):
    """Download a real ultrasound image sequence and return its sequence browser node.

    Uses the SlicerHeart 'Mitral' sample (the same data set the ValveAnnulusAnalysis self-test
    downloads), so the tests operate on a realistic multi-frame volume sequence instead of a
    synthetic image. Both valve scenarios annotate frames of this single volume sequence.
    """
    import SampleData
    self.delayDisplay("Load image sequence")
    SampleData.SampleDataLogic().downloadSample("Mitral")
    # Remove the bundled leaflet segmentation; the tests create their own.
    segmentationNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")
    if segmentationNode:
      slicer.mrmlScene.RemoveNode(segmentationNode)
    volumeSequenceNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSequenceNode")
    sequencesLogic = slicer.util.getModuleLogic("Sequences")
    return sequencesLogic.GetFirstBrowserNodeForSequenceNode(volumeSequenceNode)

  def runTest(self):
    self.setUp()
    for valveType in self.VALVE_TEST_CASES:
      self._runValveModelWorkflow(valveType)
    self.delayDisplay("All ValveModel scripting helper tests passed")

  # -------------------------------------------------------------------------
  # Workflow (one valve sequence browser per valve type, like ValveAnnulusAnalysisTest)
  # -------------------------------------------------------------------------

  def _runValveModelWorkflow(self, valveType):
    """Walk a single valve (annotation) sequence browser through the full ValveModel helper
    workflow, exercising every scripting helper and its per-time-point behavior.

    The same workflow runs for every valve type; only the annulus contour data (looked up from
    ``VALVE_TEST_CASES``) differs. A single valve sequence browser is created on the shared
    downloaded volume sequence and a coherent valve setup (valve type + probe position) is
    configured so the placed points lie on the valve annulus of the Mitral_US volume.
    """
    self.delayDisplay(f"Run ValveModel workflow: {valveType}")
    contourFrame0, contourFrame1 = self.VALVE_TEST_CASES[valveType]

    valveBrowser = self._createValveBrowser(valveType)
    volumeBrowserNode = self.volumeSequenceBrowserNode

    # One time point on volume frame 0.
    self._addValveTimePoint(valveBrowser, volumeBrowserNode, 0)
    valveModel = valveBrowser.valveModel

    # --- addAnnulusContourCurve / removeAnnulusContourCurve ---
    self.delayDisplay(f"{valveType}: addAnnulusContourCurve / removeAnnulusContourCurve")
    self.assertIsNone(valveModel.annulusContourCurveNode,
                      "No curve should exist before addAnnulusContourCurve")
    curveNode = valveModel.addAnnulusContourCurve()
    self.assertIsNotNone(curveNode, "addAnnulusContourCurve should return a node")
    self.assertIsNotNone(valveModel.annulusContourCurveNode,
                         "annulusContourCurveNode should be non-None after addAnnulusContourCurve")
    self.assertEqual(curveNode.GetID(), valveModel.annulusContourCurveNode.GetID())
    # Adding again is a no-op: returns the same node.
    self.assertEqual(valveModel.addAnnulusContourCurve().GetID(), curveNode.GetID(),
                     "Second addAnnulusContourCurve call should return the same node (no-op)")
    # Removing reports True once, then False.
    self.assertTrue(valveModel.removeAnnulusContourCurve(),
                    "removeAnnulusContourCurve should report True when an entry was removed")
    self.assertIsNone(valveModel.annulusContourCurveNode,
                      "annulusContourCurveNode should be None after removal")
    self.assertFalse(valveModel.removeAnnulusContourCurve(),
                     "Removing a non-existent entry should return False")

    # --- setAnnulusContourPoints (time point 0) ---
    self.delayDisplay(f"{valveType}: setAnnulusContourPoints")
    curveNode = valveModel.setAnnulusContourPoints(contourFrame0)
    self._assertControlPointsMatch(curveNode, contourFrame0, "setAnnulusContourPoints: ")
    self.assertTrue(valveModel.hasStoredAnnulusContour(),
                    "storeAnnulusContour should have been called")

    # --- setValveLabels (time point 0) ---
    self.delayDisplay(f"{valveType}: setValveLabels")
    labels0 = self._annulusLandmarkLabels(contourFrame0)
    labelsNode = valveModel.setValveLabels(labels0)
    self._assertLabelsMatch(labelsNode, labels0, "setValveLabels: ")
    self.assertTrue(labelsNode.GetLocked(),
                    "Labels node should be locked after setValveLabels")

    # --- initializeLeafletSegmentation (time point 0) ---
    self.delayDisplay(f"{valveType}: initializeLeafletSegmentation")
    segNode0 = valveModel.initializeLeafletSegmentation()
    self.assertIsNotNone(segNode0,
                         "initializeLeafletSegmentation should return a segmentation node")
    self.assertIsNotNone(valveModel.leafletVolumeNode, "Leaflet volume should be created")
    self.assertIsNotNone(valveModel.leafletSegmentationNode, "Leaflet segmentation should be created")
    self.assertEqual(segNode0.GetID(), valveModel.leafletSegmentationNode.GetID())
    # Calling again is a no-op: returns the same node.
    self.assertEqual(valveModel.initializeLeafletSegmentation().GetID(), segNode0.GetID(),
                     "Second initializeLeafletSegmentation call should return the same node (no-op)")
    # Define two segments at time point 0.
    seg0 = segNode0.GetSegmentation()
    for segmentName in ("Anterior", "Posterior"):
      seg0.GetSegment(seg0.AddEmptySegment(segmentName)).SetName(segmentName)

    # --- Regression test for issue #307 (SlicerHeartPrivate): adding a new time point must not
    #     reset the axial slice orientation. On a freshly created valve browser (as above)
    #     axialSliceToRasTransformNode is just a single transform node shared by all time points, so
    #     the bug cannot occur there. It only shows up on scenes migrated from the old per-phase
    #     format, where Converter4DSequences registers AxialSliceToRasTransform as a real
    #     per-time-point sequence with MissingItemMode=MissingItemSetToDefault. Simulate that setup
    #     here so ValveBrowser.addTimePoint's carry-forward of the orientation is actually exercised. ---
    self.delayDisplay(f"{valveType}: axial slice orientation is preserved for new time points")
    axialSequenceNode = self._makeAxialSliceToRasTransformSequence(valveBrowser)
    self.assertEqual(axialSequenceNode.GetNumberOfDataNodes(), 1,
                     "Time point 0 should already have an axial slice orientation sequence item")
    nonDefaultAxialMatrix = vtk.vtkMatrix4x4()
    nonDefaultAxialMatrix.DeepCopy((
      0, -1, 0, 12,
      1, 0, 0, 34,
      0, 0, 1, 56,
      0, 0, 0, 1))
    # SetSaveChanges is enabled for this sequence, so mutating the proxy node writes this matrix back
    # into the sequence's time point 0 item.
    valveBrowser.axialSliceToRasTransformNode.SetMatrixTransformToParent(nonDefaultAxialMatrix)

    # --- Add a second time point (volume frame 1) AFTER the segmentation is in place, so the
    #     heartValveNode state copied to the new time point already carries the LeafletSegmentation
    #     (and LeafletVolume) references. Populate it with distinct annulus/labels. ---
    self.delayDisplay(f"{valveType}: per-time-point behavior")
    self._addValveTimePoint(valveBrowser, volumeBrowserNode, 1)

    # The new time point should start out with the same axial orientation as the time point it was
    # added from, not the sequence's default (identity) matrix.
    self.assertEqual(axialSequenceNode.GetNumberOfDataNodes(), 2,
                     "The new time point should get its own axial slice orientation sequence item")
    newTimePointAxialMatrix = vtk.vtkMatrix4x4()
    valveBrowser.axialSliceToRasTransformNode.GetMatrixTransformToParent(newTimePointAxialMatrix)
    self._assertMatricesEqual(newTimePointAxialMatrix, nonDefaultAxialMatrix,
                              "Axial slice orientation should carry over to a newly added time point "
                              "instead of resetting to identity: ")

    labels1 = self._annulusLandmarkLabels(contourFrame1)
    valveBrowser.valveModel.setAnnulusContourPoints(contourFrame1)
    valveBrowser.valveModel.setValveLabels(labels1)
    segNode1 = valveBrowser.valveModel.initializeLeafletSegmentation()
    self.assertIsNotNone(segNode1)

    # Per-time-point distinctness: each time point keeps its own annulus contour and landmarks.
    self._switchToTimePoint(valveBrowser, volumeBrowserNode, 0)
    self._assertControlPointsMatch(valveBrowser.valveModel.annulusContourCurveNode, contourFrame0,
                                   "Time point 0 annulus: ")
    self._assertLabelsMatch(valveBrowser.valveModel.valveLabelsNode, labels0, "Time point 0 labels: ")

    self._switchToTimePoint(valveBrowser, volumeBrowserNode, 1)
    self._assertControlPointsMatch(valveBrowser.valveModel.annulusContourCurveNode, contourFrame1,
                                   "Time point 1 annulus: ")
    self._assertLabelsMatch(valveBrowser.valveModel.valveLabelsNode, labels1, "Time point 1 labels: ")

    # Leaflet segmentation is stored as a sequence with a single proxy node whose content is
    # swapped per time point (so segNode0 and segNode1 are the same proxy node). The distinct
    # per-time-point data lives in the sequence: one segmentation data node per time point, and the
    # segment definitions from time point 0 are reproduced (empty) in the new time point.
    segmentationSequenceNode = valveBrowser.valveModel.leafletSegmentationSequenceNode
    self.assertIsNotNone(segmentationSequenceNode, "A leaflet segmentation sequence should exist")
    self.assertEqual(segmentationSequenceNode.GetNumberOfDataNodes(), 2,
                     "Each time point should have its own segmentation node in the sequence")
    seg1 = segNode1.GetSegmentation()
    self.assertIsNotNone(seg1.GetSegment("Anterior"),
                         "Anterior segment should be copied to time point 1")
    self.assertIsNotNone(seg1.GetSegment("Posterior"),
                         "Posterior segment should be copied to time point 1")
    self.assertEqual(seg1.GetSegment("Anterior").GetName(), "Anterior")
    self.assertEqual(seg1.GetSegment("Posterior").GetName(), "Posterior")

    # Finally, confirm the ValveSegmentation and ValveQuantification modules can be driven on this
    # valve via their logic methods (no GUI). Use time point 0, which has an annulus contour and a
    # leaflet segmentation set up above.
    self._switchToTimePoint(valveBrowser, volumeBrowserNode, 0)
    self._exerciseValveSegmentationLogic(valveBrowser.valveModel, valveType)
    self._exerciseValveQuantificationLogic(valveBrowser.valveModel, valveType)

  # -------------------------------------------------------------------------
  # Module logic setup (no GUI)
  # -------------------------------------------------------------------------

  def _exerciseValveSegmentationLogic(self, valveModel, valveType):
    """Set up the ValveSegmentation module on the valve using logic methods only.

    Builds the valve ROI (leaflet clipping region) from the annulus contour and runs the clipped,
    axis-aligned leaflet volume generation - the core ValveSegmentation logic step. We only verify
    the setup succeeds (produces geometry / a clipped volume), not the numeric result.
    """
    self.delayDisplay(f"{valveType}: ValveSegmentation logic setup")
    from ValveSegmentation import ValveSegmentationLogic

    # Build the valve ROI clipping model from the annulus contour.
    roiModelNode = valveModel.createValveRoiModelNode()
    self.assertIsNotNone(roiModelNode, "createValveRoiModelNode should return a model node")
    valveModel.valveRoi.setAnnulusContourCurve(valveModel.annulusContourCurveNode)
    valveModel.valveRoi.updateRoi()
    self.assertIsNotNone(roiModelNode.GetMesh(), "Valve ROI model should have a mesh after updateRoi")
    self.assertGreater(roiModelNode.GetMesh().GetNumberOfPoints(), 0,
                       "Valve ROI clipping geometry should be generated from the annulus contour")

    # Core ValveSegmentation logic: generate the clipped, axis-aligned leaflet volume.
    clippedLeafletVolume = ValveSegmentationLogic.getLeafletVolumeClippedAxisAligned(valveModel)
    self.assertIsNotNone(clippedLeafletVolume,
                         "getLeafletVolumeClippedAxisAligned should produce a clipped leaflet volume")

  def _exerciseValveQuantificationLogic(self, valveModel, valveType):
    """Set up the ValveQuantification module on the valve using logic methods only.

    Creates a heart valve measurement node, assigns the generic-valve measurement preset and the
    valve as input, and runs the metrics computation - all without the GUI. We only verify the
    setup runs and produces a metrics table, not specific metric values.
    """
    self.delayDisplay(f"{valveType}: ValveQuantification logic setup")
    from ValveQuantification import ValveQuantificationLogic

    quantificationLogic = ValveQuantificationLogic()

    measurementNode = slicer.mrmlScene.AddNewNodeByClass(
      "vtkMRMLScriptedModuleNode", f"{valveType.capitalize()}ValveMeasurement")
    measurementNode.SetAttribute("ModuleName", "HeartValveMeasurement")

    # Use the generic-valve preset (applicable to any valve type) and wire the valve as its input.
    preset = quantificationLogic.getMeasurementPresetById("GenericValve")
    self.assertIsNotNone(preset, "GenericValve measurement preset should be registered")
    measurementNode.SetAttribute("MeasurementPreset", preset.id)
    inputValveId = preset.inputValveIds[0]
    measurementNode.SetNodeReferenceID("Valve" + inputValveId, valveModel.heartValveNode.GetID())

    # Core ValveQuantification logic: compute the metrics for the measurement node.
    quantificationLogic.computeMetrics(measurementNode)
    computedPreset = quantificationLogic.getMeasurementPreset(measurementNode)
    self.assertIsNotNone(computedPreset.metricsTable,
                         "computeMetrics should create a metrics table")
    self.assertIsNotNone(computedPreset.metricsTable.metricTableNode,
                         "Metrics table node should exist after computeMetrics")

  # -------------------------------------------------------------------------
  # Scene helpers
  # -------------------------------------------------------------------------

  def _createValveBrowser(self, valveType):
    """Create a valve (annotation) sequence browser on the shared downloaded volume sequence.

    Configures the valve type and probe position so that annulus and landmark points placed by the
    tests land on the valve annulus of the Mitral_US volume, the same way
    ValveAnnulusAnalysisTest positions them on the anatomy.
    """
    import HeartValveLib

    volumeBrowserNode = self.volumeSequenceBrowserNode
    volumeSeqNode = volumeBrowserNode.GetMasterSequenceNode()
    volumeProxyNode = volumeBrowserNode.GetProxyNode(volumeSeqNode)

    valveBrowserNode = slicer.mrmlScene.AddNewNodeByClass(
      "vtkMRMLSequenceBrowserNode", f"{valveType.capitalize()}ValveBrowser")
    # Mark the node as a heart valve browser so the valve modules' node selectors list it (the
    # heartValveBrowserSelector filters on ModuleName == "HeartValve"); the GUI's addNode() stamps
    # this attribute, but creating the node directly does not.
    valveBrowserNode.SetAttribute("ModuleName", "HeartValve")
    valveBrowser = HeartValveLib.HeartValves.getValveBrowser(valveBrowserNode)

    # Wire the volume proxy to the valve browser so that goToAnalyzedFrame works.
    valveBrowser.valveVolumeNode = volumeProxyNode
    valveBrowser.valveType = valveType
    valveBrowser.probePosition = "TTE_APICAL"
    return valveBrowser

  def _addValveTimePoint(self, valveBrowser, volumeBrowserNode, frameIdx):
    """Add a valve time point annotating volume frame *frameIdx*.

    The valve time point's index value is set to the volume frame's index value (the convention
    used throughout HeartValveLib), so it stays linked to the volume frame. The valve browser is
    positioned at the new time point on return.
    """
    volumeSeqNode = volumeBrowserNode.GetMasterSequenceNode()
    volumeBrowserNode.SetSelectedItemNumber(frameIdx)
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(volumeBrowserNode)

    indexValue = volumeSeqNode.GetNthIndexValue(frameIdx)
    valveBrowser.addTimePoint(indexValue)
    valveBrowser.valveModel.setValveVolumeSequenceIndex(frameIdx)

  def _switchToTimePoint(self, valveBrowser, volumeBrowserNode, frameIdx):
    """Switch both the valve and volume browser to *frameIdx*."""
    valveBrowser.valveBrowserNode.SetSelectedItemNumber(frameIdx)
    volumeBrowserNode.SetSelectedItemNumber(frameIdx)
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(valveBrowser.valveBrowserNode)
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(volumeBrowserNode)

  def _makeAxialSliceToRasTransformSequence(self, valveBrowser):
    """Register *valveBrowser*'s axialSliceToRasTransformNode as a real per-time-point sequence.

    Mirrors how Converter4DSequences._createSequenceForNode sets up the AxialSliceToRasTransform
    sequence when migrating a scene from the old per-phase format (synchronized sequence node,
    MissingItemMode=MissingItemSetToDefault, browser reference repointed at the sequence's proxy). A
    freshly created valve browser never does this on its own (axialSliceToRasTransformNode is just a
    single transform node shared by all time points), so tests need to simulate it explicitly to
    exercise the per-time-point orientation code path.
    :returns: the new sequence node.
    """
    valveBrowserNode = valveBrowser.valveBrowserNode
    originalAxialTransformNode = valveBrowser.axialSliceToRasTransformNode

    axialSequenceNode = slicer.mrmlScene.AddNewNodeByClass(
      "vtkMRMLSequenceNode", slicer.mrmlScene.GetUniqueNameByString("AxialSliceToRasTransform_Sequence"))
    # Seed the sequence with an item for the currently displayed time point before registering it as
    # synchronized: an empty sequence has no node class to create a proxy from.
    _, indexValue = valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()
    axialSequenceNode.SetDataNodeAtValue(originalAxialTransformNode, indexValue)

    valveBrowserNode.AddSynchronizedSequenceNode(axialSequenceNode)
    valveBrowserNode.SetSaveChanges(axialSequenceNode, True)
    valveBrowserNode.SetMissingItemMode(axialSequenceNode, slicer.vtkMRMLSequenceBrowserNode.MissingItemSetToDefault)
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(valveBrowserNode)
    valveBrowser.axialSliceToRasTransformNode = valveBrowserNode.GetProxyNode(axialSequenceNode)
    return axialSequenceNode

  # -------------------------------------------------------------------------
  # Markup helpers
  # -------------------------------------------------------------------------

  def _getControlPointPositions(self, markupsNode):
    """Return a list of ``(x, y, z)`` tuples for every control point."""
    result = []
    for i in range(markupsNode.GetNumberOfControlPoints()):
      pos = [0.0, 0.0, 0.0]
      markupsNode.GetNthControlPointPosition(i, pos)
      result.append(tuple(pos))
    return result

  def _getControlPointLabels(self, markupsNode):
    return [markupsNode.GetNthControlPointLabel(i)
            for i in range(markupsNode.GetNumberOfControlPoints())]

  def _assertControlPointsMatch(self, markupsNode, expectedPoints, msgPrefix=""):
    """Assert that *markupsNode* holds exactly *expectedPoints* (list of ``[r, a, s]``)."""
    self.assertIsNotNone(markupsNode, f"{msgPrefix}markups node should exist")
    positions = self._getControlPointPositions(markupsNode)
    self.assertEqual(len(positions), len(expectedPoints), f"{msgPrefix}control point count")
    for i, expected in enumerate(expectedPoints):
      for j in range(3):
        self.assertAlmostEqual(positions[i][j], expected[j], places=5,
                               msg=f"{msgPrefix}point {i}, coord {j}")

  def _assertLabelsMatch(self, labelsNode, expectedLabeledPoints, msgPrefix=""):
    """Assert that *labelsNode* holds the expected labels and positions (list of
    ``(label, r, a, s)``)."""
    self.assertIsNotNone(labelsNode, f"{msgPrefix}labels node should exist")
    expectedLabels = [labeledPoint[0] for labeledPoint in expectedLabeledPoints]
    self.assertEqual(self._getControlPointLabels(labelsNode), expectedLabels, f"{msgPrefix}labels")
    positions = self._getControlPointPositions(labelsNode)
    self.assertEqual(len(positions), len(expectedLabeledPoints), f"{msgPrefix}label count")
    for i, (label, r, a, s) in enumerate(expectedLabeledPoints):
      for j, expected in enumerate((r, a, s)):
        self.assertAlmostEqual(positions[i][j], expected, places=5,
                               msg=f"{msgPrefix}label {label}, coord {j}")

  def _assertMatricesEqual(self, actual, expected, msgPrefix=""):
    """Assert that two vtkMatrix4x4 are element-wise equal."""
    for row in range(4):
      for col in range(4):
        self.assertAlmostEqual(actual.GetElement(row, col), expected.GetElement(row, col), places=5,
                               msg=f"{msgPrefix}element ({row}, {col})")
