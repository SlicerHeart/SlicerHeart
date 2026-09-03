"""
ValveModelSequenceTest.py

Tests for the per-time-point behaviour of HeartValveLib.ValveModel (annulus contour, labels, ROI,
leaflet segmentation, papillary muscles, coaptation surfaces), ValveRoi and the helpers module.

All tests run on a small synthetic volume sequence; one smoke test uses the downloaded Mitral sample
and is skipped when it is not available.
"""

import math
import os
import sys

import numpy as np
import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_TESTLIB_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.asserts import controlPointPositions  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class ValveModelSequenceTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ValveModelSequenceTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for the per-time-point behaviour of HeartValveLib.ValveModel."
    self.parent.acknowledgementText = ""


class ValveModelSequenceTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class ValveModelSequenceTestLogic(ScriptedLoadableModuleLogic):
  pass


class ValveModelSequenceTestTest(SlicerHeartTestCase):

  # ---------------------------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _segmentIds(segmentationNode):
    return list(segmentationNode.GetSegmentation().GetSegmentIDs())

  @staticmethod
  def _segmentVoxelCount(segmentationNode, segmentId):
    labelmap = slicer.vtkOrientedImageData()
    if not segmentationNode.GetBinaryLabelmapRepresentation(segmentId, labelmap):
      return 0
    if labelmap.GetNumberOfPoints() == 0:
      return 0
    from vtk.util import numpy_support
    array = numpy_support.vtk_to_numpy(labelmap.GetPointData().GetScalars())
    return int(np.count_nonzero(array))

  @staticmethod
  def _sequenceCount():
    return len(slicer.util.getNodesByClass("vtkMRMLSequenceNode"))

  # ---------------------------------------------------------------------------------------------
  # Time-point aware getters
  # ---------------------------------------------------------------------------------------------

  def test_getters_return_none_at_time_point_without_item(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1, phase="mid-systole")
    factory.setContour(valveBrowser, 1)
    factory.setLabels(valveBrowser, 1)
    factory.addRoi(valveBrowser)
    factory.addSegmentation(valveBrowser)
    valveModel = valveBrowser.valveModel
    for name in ("annulusContourCurveNode", "valveLabelsNode", "valveRoiModelNode", "leafletVolumeNode",
                 "leafletSegmentationNode"):
      self.assertIsNotNone(getattr(valveModel, name), f"{name} at annotated time point")
      self.assertTrue(valveModel.isNodeSpecifiedForCurrentTimePoint(getattr(valveModel, name)), name)

    factory.addTimePoint(valveBrowser, 3)
    self.assertIsNone(valveModel.annulusContourCurveNode)
    self.assertIsNone(valveModel.valveRoiModelNode)
    self.assertIsNone(valveModel.leafletVolumeNode)
    self.assertIsNone(valveModel.leafletSegmentationNode)
    self.assertFalse(valveModel.isNodeSpecifiedForCurrentTimePoint(valveBrowser.heartValveNode.GetNodeReference("AnnulusLabelsPoints")))
    # The sequence nodes are still reachable so that items can be added
    self.assertIsNotNone(valveModel.annulusContourCurveSequenceNode)
    self.assertIsNotNone(valveModel.valveLabelsSequenceNode)
    self.assertIsNotNone(valveModel.valveRoiSequenceNode)
    self.assertIsNotNone(valveModel.leafletVolumeSequenceNode)
    self.assertIsNotNone(valveModel.leafletSegmentationSequenceNode)
    self.assertFalse(valveModel.isNodeSpecifiedForCurrentTimePoint(None))
    self.assertTrue(valveModel.isNodeSpecifiedForCurrentTimePoint(valveBrowser.heartValveNode),
                    "the valve node itself always has an item at the current time point")

  def test_valveLabelsNode_is_time_point_aware_like_the_other_getters(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setLabels(valveBrowser, 1)
    factory.addTimePoint(valveBrowser, 3)
    valveModel = valveBrowser.valveModel
    labelsNode = valveBrowser.heartValveNode.GetNodeReference("AnnulusLabelsPoints")
    self.assertFalse(valveModel.isNodeSpecifiedForCurrentTimePoint(labelsNode))
    self.assertIsNone(valveModel.valveLabelsNode,
                      "valveLabelsNode must be None at a time point without labels, like annulusContourCurveNode")

  # ---------------------------------------------------------------------------------------------
  # Annulus contour
  # ---------------------------------------------------------------------------------------------

  def test_addAnnulusContourCurve_and_remove(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    self.assertFalse(valveModel.removeAnnulusContourCurve(), "nothing to remove yet")

    curveNode = valveModel.addAnnulusContourCurve()
    self.assertIsNotNone(curveNode)
    self.assertEqual(curveNode.GetClassName(), "vtkMRMLMarkupsClosedCurveNode")
    self.assertEqual(curveNode.GetNumberOfControlPoints(), 0)
    self.assertIs(valveModel.addAnnulusContourCurve(), curveNode, "idempotent")
    self.assertShParentIs(curveNode, valveBrowser.heartValveNode)
    self.assertParentTransformIs(curveNode, valveBrowser.probeToRasTransformNode)
    sequenceNode = valveModel.annulusContourCurveSequenceNode
    self.assertSequenceIndexValues(sequenceNode, [factory.indexValue(1)])
    self.assertEqual(valveBrowser.valveBrowserNode.GetMissingItemMode(sequenceNode),
                     slicer.vtkMRMLSequenceBrowserNode.MissingItemSetToDefault)
    self.assertAlmostEqual(curveNode.GetDisplayNode().GetLineDiameter(), valveModel.annulusContourRadius * 2, places=5)

    factory.addTimePoint(valveBrowser, 3)
    self.assertIsNone(valveModel.annulusContourCurveNode)
    self.assertIs(valveModel.addAnnulusContourCurve(), curveNode, "same proxy, new item")
    self.assertSequenceIndexValues(sequenceNode, [factory.indexValue(1), factory.indexValue(3)])
    self.assertTrue(valveModel.removeAnnulusContourCurve())
    self.assertIsNone(valveModel.annulusContourCurveNode)
    self.assertSequenceIndexValues(sequenceNode, [factory.indexValue(1)])
    self.assertFalse(valveModel.removeAnnulusContourCurve())
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLMarkupsClosedCurveNode")), 1, "single proxy curve node")

  def test_store_and_restore_annulus_contour(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    self.assertFalse(bool(valveModel.hasStoredAnnulusContour()))
    points = factory.setContour(valveBrowser, 1)
    self.assertTrue(valveModel.hasStoredAnnulusContour())
    curveNode = valveModel.annulusContourCurveNode
    self.assertIsNotNone(curveNode.GetAttribute("AnnulusContourCoordinates"), "backup lives on the curve node")
    self.assertIsNone(valveBrowser.heartValveNode.GetAttribute("AnnulusContourCoordinates"))
    # Resample/modify and restore
    curveNode.RemoveAllControlPoints()
    curveNode.AddControlPoint(1.0, 1.0, 1.0)
    self.assertEqual(curveNode.GetNumberOfControlPoints(), 1)
    valveModel.restoreAnnulusContour()
    self.assertControlPointsEqual(curveNode, points, msg="restored contour")
    # Resampling keeps the curve on the same ellipse and the backup unchanged
    valveModel.resampleAnnulusContourMarkups(1.0)
    self.assertGreater(curveNode.GetNumberOfControlPoints(), len(points))
    valveModel.restoreAnnulusContour()
    self.assertControlPointsEqual(curveNode, points, msg="restored after resampling")
    # Smoothing must run without error and keep a closed curve with roughly the same length
    lengthBefore = curveNode.GetCurveLengthWorld()
    valveModel.smoothAnnulusContour(5, 1.0)
    self.assertGreater(curveNode.GetNumberOfControlPoints(), 4)
    self.assertLess(abs(curveNode.GetCurveLengthWorld() - lengthBefore) / lengthBefore, 0.2)

  def test_setAnnulusContourPoints_without_time_point_fails_cleanly(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    # Without any time point there is no heart valve node, so there is no valve model to call
    self.assertIsNone(valveBrowser.heartValveNode)
    self.assertIsNone(valveBrowser.valveModel)

  def test_initializeNewTimePoint_does_not_touch_other_time_points(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1, phase="mid-systole")
    points = factory.setContour(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    stored = valveModel.annulusContourCurveNode.GetAttribute("AnnulusContourCoordinates")
    factory.addTimePoint(valveBrowser, 3)
    valveModel.initializeNewTimePoint()  # explicitly, as addTimePoint does
    self.assertIsNone(valveModel.annulusContourCurveNode, "must not create a contour item for the new time point")
    self.assertSequenceIndexValues(valveModel.annulusContourCurveSequenceNode, [factory.indexValue(1)])
    factory.switchTo(valveBrowser, 1)
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, points, msg="first time point contour")
    self.assertEqual(valveModel.annulusContourCurveNode.GetAttribute("AnnulusContourCoordinates"), stored)
    self.assertEqual(valveModel.getCardiacCyclePhase(), "mid-systole")

  def test_getCardiacCyclePhase_has_no_side_effects(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    points = factory.setContour(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    stored = valveModel.annulusContourCurveNode.GetAttribute("AnnulusContourCoordinates")
    valveBrowser.heartValveNode.RemoveAttribute("CardiacCyclePhase")
    self.assertEqual(valveModel.getCardiacCyclePhase(), "unknown")
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, points, msg="contour untouched by getter")
    self.assertEqual(valveModel.annulusContourCurveNode.GetAttribute("AnnulusContourCoordinates"), stored)
    self.assertIsNone(valveBrowser.heartValveNode.GetAttribute("CardiacCyclePhase"), "getter must not write")

  def test_setCardiacCyclePhase_per_time_point_and_colors(self):
    from HeartValveLib import Constants
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    valveModel = None
    # Same order as the GUI: add time point, draw the contour, then choose the phase
    for frame, phase in ((1, "mid-systole"), (3, "end-diastole")):
      factory.addTimePoint(valveBrowser, frame)
      factory.setContour(valveBrowser, frame)
      factory.setLabels(valveBrowser, frame)
      valveModel = valveBrowser.valveModel
      valveModel.setCardiacCyclePhase(phase)
    msColor = Constants.CARDIAC_CYCLE_PHASE_PRESETS["mid-systole"]["color"]
    edColor = Constants.CARDIAC_CYCLE_PHASE_PRESETS["end-diastole"]["color"]
    self.assertEqual(valveModel.getCardiacCyclePhase(), "end-diastole")
    self.assertEqual(list(valveModel.getBaseColor()), edColor)
    self.assertEqual(list(valveModel.annulusContourCurveNode.GetDisplayNode().GetColor()), edColor)
    self.assertEqual(list(valveModel.valveLabelsNode.GetDisplayNode().GetSelectedColor()), edColor)
    from HeartValveLib.helpers import getValvePhaseShortName
    self.assertEqual(getValvePhaseShortName(valveModel), "ED")
    factory.switchTo(valveBrowser, 1)
    self.assertEqual(valveModel.getCardiacCyclePhase(), "mid-systole")
    self.assertEqual(getValvePhaseShortName(valveModel), "MS")
    self.assertEqual(list(valveModel.getBaseColor()), msColor)
    # The contour colour indicates the phase, so it must follow the displayed time point
    self.assertEqual(list(valveModel.annulusContourCurveNode.GetDisplayNode().GetColor()), msColor,
                     "contour colour must reflect the phase of the displayed time point")

  def test_getDarkColor(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1, phase="mid-diastole")  # colour (0, 0, 1)
    valveModel = valveBrowser.valveModel
    self.assertEqual([round(c, 4) for c in valveModel.getDarkColor()], [0.0, 0.0, 0.5],
                     "dark colour must halve every channel of the phase colour")
    valveModel.setCardiacCyclePhase("mid-systole")  # colour (1, 0, 0)
    self.assertEqual([round(c, 4) for c in valveModel.getDarkColor()], [0.5, 0.0, 0.0])

  def test_getValveVolumeSequenceIndex(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.addTimePoint(valveBrowser, 4)
    valveModel = valveBrowser.valveModel
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 4)
    # The legacy attribute is irrelevant: the index is derived from the sequence index values
    valveBrowser.heartValveNode.SetAttribute("ValveVolumeSequenceIndex", "0")
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 4)
    factory.switchTo(valveBrowser, 1)
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 1)
    # A valve without volume has no frame index
    bareNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "Bare")
    bareNode.SetAttribute("ModuleName", "HeartValve")
    bare = HeartValveLib.HeartValves.getValveBrowser(bareNode)
    bare.addTimePoint("0.5")
    self.assertEqual(bare.valveModel.getValveVolumeSequenceIndex(), -1)
    self.assertEqual(bare.valveModel.getDisplayedValveVolumeSequenceIndex(), 0)

  # ---------------------------------------------------------------------------------------------
  # Labels and annulus geometry helpers
  # ---------------------------------------------------------------------------------------------

  def test_labels_helpers(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    contour = factory.setContour(valveBrowser, 1)
    labeled = factory.setLabels(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    labelsNode = valveModel.valveLabelsNode
    self.assertTrue(labelsNode.GetLocked())
    self.assertEqual(valveModel.getAllMarkupLabels(), ["A", "L", "P", "S"])
    self.assertEqual(valveModel.getAnnulusLabelsMarkupIndexByLabel(" P "), 2, "labels are matched stripped")
    self.assertEqual(valveModel.getAnnulusLabelsMarkupIndexByLabel("X"), -1)
    self.assertIsNone(valveModel.getAnnulusMarkupPositionByLabel("X"))
    np.testing.assert_allclose(valveModel.getAnnulusMarkupPositionByLabel("A"), labeled[0][1:], atol=1e-6)
    positions = valveModel.getAnnulusMarkupPositionsByLabels(["S", "A"])
    np.testing.assert_allclose(positions[0], labeled[3][1:], atol=1e-6)
    np.testing.assert_allclose(positions[1], labeled[0][1:], atol=1e-6)
    # A label far from the annulus (e.g. a centroid) is not an annulus label
    valveModel.setAnnulusMarkupLabel("C", [0.0, 0.0, -4.0])
    self.assertEqual(valveModel.getAllMarkupLabels(), ["A", "L", "P", "S", "C"])
    self.assertEqual(valveModel.getAnnulusMarkupLabels(), ["A", "L", "P", "S"])
    valveModel.setAnnulusMarkupLabel("A", [9.0, 9.0, 9.0])
    np.testing.assert_allclose(valveModel.getAnnulusMarkupPositionByLabel("A"), [9.0, 9.0, 9.0])
    self.assertEqual(labelsNode.GetNumberOfControlPoints(), 5, "existing label is moved, not duplicated")
    valveModel.removeAnnulusMarkupLabel("C")
    valveModel.removeAnnulusMarkupLabel("nonexistent")
    self.assertEqual(valveModel.getAllMarkupLabels(), ["A", "L", "P", "S"])
    # Labels are per time point
    factory.addTimePoint(valveBrowser, 3)
    labeled3 = [("A", 1.0, 0.0, 0.0), ("P", -1.0, 0.0, 0.0)]
    valveModel.setValveLabels(labeled3)
    self.assertEqual(valveModel.getAllMarkupLabels(), ["A", "P"])
    factory.switchTo(valveBrowser, 1)
    self.assertEqual(valveModel.getAllMarkupLabels(), ["A", "L", "P", "S"])
    self.assertSequenceIndexValues(valveModel.valveLabelsSequenceNode, [factory.indexValue(1), factory.indexValue(3)])

  def test_getAnnulusContourCurveSegments(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    factory.setLabels(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    curveLength = valveModel.annulusContourCurveNode.GetCurveLengthWorld()
    for splitBetween in (True, False):
      segments = valveModel.getAnnulusContourCurveSegments(["S", "P", "A", "L"], splitBetweenPoints=splitBetween)
      self.assertEqual(len(segments), 4)
      self.assertEqual(segments[0]["pointLabel"], "A", "alphabetically first label comes first")
      self.assertEqual([s["pointLabel"] for s in segments], ["A", "L", "P", "S"], "order along the curve")
      for s in segments:
        for key in ("pointLabel", "label", "closestPointIdOnAnnulusCurve", "closestPointPositionOnAnnulusCurve",
                    "segmentStartPointId", "segmentStartPointPosition", "segmentEndPointId",
                    "segmentEndPointPosition", "segmentLengthBefore", "segmentLengthAfter"):
          self.assertIn(key, s)
      total = sum(s["segmentLengthBefore"] + s["segmentLengthAfter"] for s in segments)
      self.assertAlmostEqual(total, curveLength, delta=0.05 * curveLength)
      if splitBetween:
        self.assertEqual(segments[0]["label"], "A")
      else:
        self.assertEqual(segments[0]["label"], "A-L")

  def test_getAnnulusContourPlane_follows_flow_direction(self):
    factory = NewFormatValveFactory()
    # Contour in the x-z plane so that the plane normal is +/-y (anterior/posterior in RAS with the
    # UNKNOWN probe position, whose ProbeToRas has no rotation)
    contour = [[2.5 * math.cos(a), 0.0, 2.0 * math.sin(a)] for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)]
    for valveType, expectedSign in (("mitral", 1.0), ("aortic", -1.0), ("tricuspid", 1.0), ("pulmonary", -1.0)):
      valveBrowser = factory.createValveBrowser(valveType, probePosition="UNKNOWN")
      factory.addTimePoint(valveBrowser, 1)
      valveBrowser.valveModel.setAnnulusContourPoints(contour)
      position, normal = valveBrowser.valveModel.getAnnulusContourPlane()
      np.testing.assert_allclose(position, [0, 0, 0], atol=1e-6)
      self.assertAlmostEqual(abs(normal[1]), 1.0, places=5, msg=valveType)
      self.assertGreater(normal[1] * expectedSign, 0.0, f"{valveType}: normal must point along the flow direction")

  # ---------------------------------------------------------------------------------------------
  # Leaflet segmentation
  # ---------------------------------------------------------------------------------------------

  def test_initializeLeafletSegmentation_per_time_point(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    factory.addRoi(valveBrowser)
    valveModel = valveBrowser.valveModel
    segmentationNode = factory.addSegmentation(valveBrowser)
    self.assertIs(valveModel.initializeLeafletSegmentation(), segmentationNode, "no-op when already initialized")
    self.assertEqual(sorted(self._segmentIds(segmentationNode)), ["Anterior", "Posterior", HeartValveLib.VALVE_MASK_SEGMENT_ID])
    self.assertGreater(self._segmentVoxelCount(segmentationNode, "Anterior"), 0)
    self.assertGreater(self._segmentVoxelCount(segmentationNode, HeartValveLib.VALVE_MASK_SEGMENT_ID), 0,
                       "valve mask generated from the ROI")
    self.assertEqual(segmentationNode.GetSegmentation().GetSegment(HeartValveLib.VALVE_MASK_SEGMENT_ID).GetName(), "Annulus mask")
    leafletVolume = valveModel.leafletVolumeNode
    self.assertEqual(scene.volumeVoxelValue(leafletVolume), 2, "leaflet volume is a clone of frame 1")
    self.assertEqual(segmentationNode.GetNodeReference(segmentationNode.GetReferenceImageGeometryReferenceRole()).GetID(),
                     leafletVolume.GetID())
    self.assertParentTransformIs(segmentationNode, valveBrowser.probeToRasTransformNode)
    self.assertParentTransformIs(leafletVolume, valveBrowser.probeToRasTransformNode)
    self.assertShParentIs(segmentationNode, valveBrowser.heartValveNode)
    self.assertIn("-segmented", leafletVolume.GetName(), f"leaflet volume name: {leafletVolume.GetName()}")
    anteriorColor = segmentationNode.GetSegmentation().GetSegment("Anterior").GetColor()

    # Second time point: segment definitions copied (empty), mask regenerated, own leaflet volume
    factory.addTimePoint(valveBrowser, 3)
    factory.setContour(valveBrowser, 3)
    factory.addRoi(valveBrowser)
    self.assertIsNone(valveModel.leafletSegmentationNode)
    segmentationNode3 = valveModel.initializeLeafletSegmentation()
    self.assertIs(segmentationNode3, segmentationNode, "same proxy node")
    self.assertEqual(sorted(self._segmentIds(segmentationNode3)), ["Anterior", "Posterior", HeartValveLib.VALVE_MASK_SEGMENT_ID])
    self.assertEqual(segmentationNode3.GetSegmentation().GetSegment("Anterior").GetName(), "Anterior leaflet")
    self.assertEqual(list(segmentationNode3.GetSegmentation().GetSegment("Anterior").GetColor()), list(anteriorColor))
    self.assertEqual(self._segmentVoxelCount(segmentationNode3, "Anterior"), 0, "geometry is not copied")
    self.assertGreater(self._segmentVoxelCount(segmentationNode3, HeartValveLib.VALVE_MASK_SEGMENT_ID), 0)
    self.assertEqual(scene.volumeVoxelValue(valveModel.leafletVolumeNode), 4, "leaflet volume cloned from frame 3")
    self.assertSequenceIndexValues(valveModel.leafletSegmentationSequenceNode, [factory.indexValue(1), factory.indexValue(3)])
    self.assertSequenceIndexValues(valveModel.leafletVolumeSequenceNode, [factory.indexValue(1), factory.indexValue(3)])

    # First time point intact
    factory.switchTo(valveBrowser, 1)
    self.assertGreater(self._segmentVoxelCount(valveModel.leafletSegmentationNode, "Anterior"), 0)
    self.assertEqual(scene.volumeVoxelValue(valveModel.leafletVolumeNode), 2)

  def test_initializeLeafletSegmentation_leaves_no_orphan_display_nodes(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    factory.addRoi(valveBrowser)
    valveBrowser.valveModel.initializeLeafletSegmentation()
    factory.addTimePoint(valveBrowser, 3)
    factory.setContour(valveBrowser, 3)
    factory.addRoi(valveBrowser)
    valveBrowser.valveModel.initializeLeafletSegmentation()
    orphans = [d.GetName() for d in slicer.util.getNodesByClass("vtkMRMLDisplayNode") if d.GetDisplayableNode() is None]
    self.assertEqual(orphans, [], "display nodes of temporary clones must be removed with them")

  def test_updateValveMaskSegment(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 2)
    valveModel = valveBrowser.valveModel
    self.assertFalse(valveModel.updateValveMaskSegment(), "no segmentation yet")
    factory.setContour(valveBrowser, 2)
    factory.addRoi(valveBrowser)
    segmentationNode = factory.addSegmentation(valveBrowser, withGeometry=False)
    self.assertTrue(valveModel.updateValveMaskSegment())
    maskVoxels = self._segmentVoxelCount(segmentationNode, HeartValveLib.VALVE_MASK_SEGMENT_ID)
    self.assertGreater(maskVoxels, 0)
    displayNode = segmentationNode.GetDisplayNode()
    self.assertFalse(displayNode.GetSegmentVisibility(HeartValveLib.VALVE_MASK_SEGMENT_ID))
    # Shrinking the ROI shrinks the mask
    valveModel.valveRoi.setRoiGeometry({"ValveRoiScale": 60, "ValveRoiTopDistance": 2, "ValveRoiTopScale": 50,
                                        "ValveRoiBottomDistance": 2, "ValveRoiBottomScale": 50})
    self.assertTrue(valveModel.updateValveMaskSegment())
    self.assertLess(self._segmentVoxelCount(segmentationNode, HeartValveLib.VALVE_MASK_SEGMENT_ID), maskVoxels)
    self.assertEqual(len([s for s in self._segmentIds(segmentationNode) if s == HeartValveLib.VALVE_MASK_SEGMENT_ID]), 1)

  def test_setLeafletSegmentation_copies_segments_and_regenerates_mask(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    factory.addRoi(valveBrowser)
    valveModel = valveBrowser.valveModel
    source = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Source")
    source.CreateDefaultDisplayNodes()
    scene.addSphereSegment(source, "Anterior", "Anterior leaflet", (1.2, 0, 0), radius=1.2, color=(1, 0, 0))
    scene.addSphereSegment(source, "Posterior", "Posterior leaflet", (-1.2, 0, 0), radius=1.2, color=(0, 1, 0))
    scene.addSphereSegment(source, HeartValveLib.VALVE_MASK_SEGMENT_ID, "Bogus mask", (0, 0, 0), radius=0.5, color=(0, 0, 1))
    sourceMaskVoxels = self._segmentVoxelCount(source, HeartValveLib.VALVE_MASK_SEGMENT_ID)

    segmentationNode = valveModel.setLeafletSegmentation(source)
    self.assertIsNotNone(segmentationNode)
    self.assertEqual(sorted(self._segmentIds(segmentationNode)), ["Anterior", "Posterior", HeartValveLib.VALVE_MASK_SEGMENT_ID])
    self.assertGreater(self._segmentVoxelCount(segmentationNode, "Posterior"), 0)
    self.assertEqual(segmentationNode.GetSegmentation().GetSegment(HeartValveLib.VALVE_MASK_SEGMENT_ID).GetName(), "Annulus mask",
                     "mask is regenerated from the ROI, not copied")
    self.assertNotEqual(self._segmentVoxelCount(segmentationNode, HeartValveLib.VALVE_MASK_SEGMENT_ID), sourceMaskVoxels)
    # Subset copy replaces everything
    segmentationNode = valveModel.setLeafletSegmentation(source, segmentIDs=["Anterior", "Missing"])
    self.assertEqual(sorted(self._segmentIds(segmentationNode)), ["Anterior", HeartValveLib.VALVE_MASK_SEGMENT_ID])
    self.assertIsNone(valveModel.setLeafletSegmentation(None))
    self.assertEqual([m.segmentId for m in valveModel.leafletModels], ["Anterior"],
                     "leaflet models must reflect the replaced segmentation content")

  def test_leaflet_models_follow_segmentation(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    factory.addRoi(valveBrowser)
    segmentationNode = factory.addSegmentation(valveBrowser)
    valveModel = valveBrowser.valveModel
    heartValveNode = valveBrowser.heartValveNode
    self.assertEqual(sorted(m.segmentId for m in valveModel.leafletModels), ["Anterior", "Posterior"])
    for segmentId in ("Anterior", "Posterior"):
      surface = valveModel.getLeafletNodeReference("LeafletSurfaceModel", segmentId)
      boundary = valveModel.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", segmentId)
      self.assertIsNotNone(surface, segmentId)
      self.assertIsNotNone(boundary, segmentId)
      self.assertEqual(surface.GetAttribute("SegmentID"), segmentId)
      self.assertEqual(boundary.GetAttribute("SegmentID"), segmentId)
      self.assertEqual(boundary.GetClassName(), "vtkMRMLMarkupsClosedCurveNode")
      self.assertShParentNameIs(surface, "LeafletSurface")
      self.assertShParentNameIs(boundary, "LeafletSurfaceEdit")
      self.assertParentTransformIs(surface, valveBrowser.probeToRasTransformNode)
      self.assertIsNotNone(valveBrowser.valveBrowserNode.GetSequenceNode(boundary), "boundary is per time point")
      leafletModel = valveModel.findLeafletModel(segmentId)
      self.assertIs(leafletModel.surfaceModelNode, surface)
      self.assertIs(leafletModel.surfaceBoundary, boundary)
      self.assertEqual(leafletModel.getName(), segmentationNode.GetSegmentation().GetSegment(segmentId).GetName())
    self.assertIsNone(valveModel.findLeafletModel("Nope"))
    self.assertIsNone(valveModel.getLeafletNodeReference("LeafletSurfaceModel", "Nope"))
    self.assertEqual(heartValveNode.GetNumberOfNodeReferences("LeafletSurfaceModel"), 2)

    # Removing a segment removes its leaflet model and nodes
    posteriorSurface = valveModel.getLeafletNodeReference("LeafletSurfaceModel", "Posterior")
    posteriorBoundary = valveModel.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", "Posterior")
    segmentationNode.GetSegmentation().RemoveSegment("Posterior")
    valveModel.updateLeafletModelsFromSegmentation()
    self.assertEqual([m.segmentId for m in valveModel.leafletModels], ["Anterior"])
    self.assertNotInScene(posteriorSurface)
    self.assertNotInScene(posteriorBoundary)
    self.assertEqual(heartValveNode.GetNumberOfNodeReferences("LeafletSurfaceModel"), 1)

  def test_leaflet_nodes_survive_time_point_with_fewer_segments(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    factory.addRoi(valveBrowser)
    factory.addSegmentation(valveBrowser)
    valveModel = valveBrowser.valveModel
    posteriorBoundary = valveModel.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", "Posterior")
    posteriorBoundary.SetLocked(False)
    posteriorBoundary.AddControlPoint(0.0, -1.0, 0.0)
    posteriorBoundary.AddControlPoint(-1.0, -1.0, 0.0)
    posteriorBoundary.AddControlPoint(-1.0, 0.0, 0.0)
    boundarySequence = valveBrowser.valveBrowserNode.GetSequenceNode(posteriorBoundary)
    self.assertSequenceHasItem(boundarySequence, factory.indexValue(1))

    # Time point 3 only has the anterior leaflet
    factory.addTimePoint(valveBrowser, 3)
    factory.setContour(valveBrowser, 3)
    factory.addRoi(valveBrowser)
    segmentation3 = factory.addSegmentation(valveBrowser, segments=[NewFormatValveFactory.DEFAULT_SEGMENTS[0]])
    # initializeLeafletSegmentation copies the segment definitions of time point 1; the user deletes
    # the posterior leaflet at this time point
    segmentation3.GetSegmentation().RemoveSegment("Posterior")
    self.assertEqual(sorted(self._segmentIds(valveModel.leafletSegmentationNode)),
                     ["Anterior", "ValveMask"])
    valveModel.updateLeafletModelsFromSegmentation()  # what the modules call when the segmentation changes

    # The posterior leaflet of time point 1 must not be destroyed by visiting time point 3
    factory.switchTo(valveBrowser, 1)
    valveModel.updateLeafletModelsFromSegmentation()
    boundary1 = valveModel.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", "Posterior")
    self.assertIsNotNone(boundary1, "posterior boundary reference lost after visiting a time point without that leaflet")
    self.assertInScene(boundarySequence, "posterior boundary sequence")
    self.assertSequenceHasItem(boundarySequence, factory.indexValue(1))
    self.assertEqual(boundary1.GetNumberOfControlPoints(), 3, "posterior boundary points of time point 1")

  # ---------------------------------------------------------------------------------------------
  # Papillary muscles
  # ---------------------------------------------------------------------------------------------

  def test_papillary_muscles(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    sequencesBefore = self._sequenceCount()
    valveModel.updatePapillaryModels()
    self.assertEqual(len(valveModel.papillaryModels), 2, "mitral valve has two papillary muscles")
    names = sorted(m.getName() for m in valveModel.papillaryModels)
    self.assertEqual(names, ["antero-lateral papillary muscle", "postero-medial papillary muscle"])
    self.assertEqual(self._sequenceCount(), sequencesBefore + 2, "one sequence per muscle")
    for papillaryModel in valveModel.papillaryModels:
      node = papillaryModel.getPapillaryLineMarkupNode()
      self.assertEqual(node.GetClassName(), "vtkMRMLMarkupsCurveNode")
      self.assertShParentNameIs(node, "PapillaryMuscles")
      self.assertParentTransformIs(node, valveBrowser.probeToRasTransformNode)
      self.assertIs(valveModel.findPapillaryModel(node), papillaryModel)
      self.assertFalse(papillaryModel.hasMusclePointsPlaced())
      self.assertIsNone(papillaryModel.getMuscleLength())
      self.assertIsNone(papillaryModel.getNthMusclePointPosition(0))
    valveModel.updatePapillaryModels()
    self.assertEqual(len(valveModel.papillaryModels), 2, "idempotent")
    self.assertEqual(self._sequenceCount(), sequencesBefore + 2)

    papillaryModel = valveModel.papillaryModels[0]
    points = [[3.0, 0.0, -3.0], [3.0, 0.0, 0.0], [3.0, 4.0, 0.0]]
    node = valveModel.setPapillaryLinePoints(papillaryModel, points)
    self.assertControlPointsEqual(node, points)
    self.assertTrue(papillaryModel.hasMusclePointsPlaced())
    self.assertAlmostEqual(papillaryModel.getMuscleLength(), 3.0, delta=0.3)
    self.assertAlmostEqual(papillaryModel.getMuscleChordLength(), 4.0, delta=0.4)
    np.testing.assert_allclose(papillaryModel.getNthMusclePointPosition(1), [3, 0, 0])
    # tip->chord runs along +y: parallel to a plane with normal z, perpendicular to a plane with normal y
    self.assertAlmostEqual(papillaryModel.getTipChordMuscleAngleDeg(np.array([0.0, 0.0, 1.0])), 0.0, places=5)
    self.assertAlmostEqual(abs(papillaryModel.getTipChordMuscleAngleDeg(np.array([0.0, 1.0, 0.0]))), 90.0, places=5)
    self.assertAlmostEqual(papillaryModel.getBaseChordMuscleAngleDeg(np.array([0.0, 0.0, 1.0])), -math.degrees(math.atan2(3, 4)) , places=3)

    # Time point specific
    sequenceNode = valveBrowser.valveBrowserNode.GetSequenceNode(node)
    self.assertSequenceIndexValues(sequenceNode, [factory.indexValue(1)])
    factory.addTimePoint(valveBrowser, 3)
    self.assertFalse(valveModel.isNodeSpecifiedForCurrentTimePoint(node))
    self.assertTrue(valveModel.addPapillaryMuscleTimePoint(papillaryModel))
    self.assertTrue(valveModel.isNodeSpecifiedForCurrentTimePoint(node))
    other = [[-3.0, 0.0, -3.0], [-3.0, 0.0, 0.0], [-3.0, 4.0, 0.0]]
    valveModel.setPapillaryLinePoints(papillaryModel, other)
    factory.switchTo(valveBrowser, 1)
    self.assertControlPointsEqual(papillaryModel.getPapillaryLineMarkupNode(), points, msg="time point 1 preserved")
    factory.switchTo(valveBrowser, 3)
    self.assertControlPointsEqual(papillaryModel.getPapillaryLineMarkupNode(), other, msg="time point 3")
    self.assertTrue(valveModel.removePapillaryMuscleTimePoint(papillaryModel))
    self.assertSequenceIndexValues(sequenceNode, [factory.indexValue(1)])
    self.assertFalse(valveModel.addPapillaryMuscleTimePoint(None))
    self.assertIsNone(valveModel.setPapillaryLinePoints(None, points))
    # Switching valve type shrinks/grows the muscle list
    factory.switchTo(valveBrowser, 1)
    valveBrowser.valveType = "cavc"
    valveModel.updatePapillaryModels()
    self.assertEqual(len(valveModel.papillaryModels), 4)
    valveBrowser.valveType = "mitral"
    valveModel.updatePapillaryModels()
    self.assertEqual(len(valveModel.papillaryModels), 2)

  def test_updatePapillaryModels_at_time_point_without_contour(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    valveModel.updatePapillaryModels()
    self.assertEqual(len(valveModel.papillaryModels), 2)
    factory.addTimePoint(valveBrowser, 3)
    self.assertIsNone(valveModel.annulusContourCurveNode)
    # The papillary module refreshes its models on every time point change; a time point without
    # annulus contour must not break it
    valveModel.updatePapillaryModels()
    self.assertEqual(len(valveModel.papillaryModels), 2)

  # ---------------------------------------------------------------------------------------------
  # Coaptation
  # ---------------------------------------------------------------------------------------------

  def test_coaptation_models(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    factory.addRoi(valveBrowser)
    factory.addSegmentation(valveBrowser)
    valveModel = valveBrowser.valveModel
    heartValveNode = valveBrowser.heartValveNode
    sequencesBefore = self._sequenceCount()
    censusBefore = scene.nodeCensus()

    coaptationModel = factory.addCoaptation(valveBrowser)
    self.assertEqual(len(valveModel.coaptationModels), 1)
    self.assertEqual(self._sequenceCount(), sequencesBefore + 3, "surface, base line and margin line sequences")
    surface = coaptationModel.surfaceModelNode
    self.assertIsNotNone(surface)
    self.assertEqual(heartValveNode.GetNthNodeReference("CoaptationSurfaceModel", 0).GetID(), surface.GetID())
    self.assertEqual(heartValveNode.GetNthNodeReference("CoaptationBaseLineMarkup", 0).GetID(), coaptationModel.baseLine.GetID())
    self.assertEqual(heartValveNode.GetNthNodeReference("CoaptationMarginLineMarkup", 0).GetID(), coaptationModel.marginLine.GetID())
    self.assertShParentNameIs(surface, "Coaptation")
    self.assertShParentNameIs(coaptationModel.baseLine, "CoaptationEdit")
    self.assertGreater(surface.GetPolyData().GetNumberOfCells(), 0, "surface between base and margin lines")
    distances = coaptationModel.getBaseLineMarginLineDistances()
    self.assertIsNotNone(distances)
    np.testing.assert_allclose(distances, 1.0, atol=0.05)
    self.assertIs(valveModel.findCoaptationModel(surface), coaptationModel)
    self.assertIsNone(valveModel.findCoaptationModel(None))
    connected = coaptationModel.getConnectedLeaflets(valveModel)
    self.assertLessEqual(len(connected), 2)
    valveModel.updateCoaptationModels()
    self.assertEqual(len(valveModel.coaptationModels), 1, "idempotent")

    # Per time point
    factory.addTimePoint(valveBrowser, 3)
    for node in (surface, coaptationModel.baseLine, coaptationModel.marginLine):
      self.assertFalse(valveModel.isNodeSpecifiedForCurrentTimePoint(node))
    valveModel.updateCoaptationModels()
    self.assertEqual(len(valveModel.coaptationModels), 1, "references are per valve, items are per time point")
    factory.switchTo(valveBrowser, 1)
    self.assertEqual(coaptationModel.baseLine.GetNumberOfControlPoints(), 3)

    # Removal cleans everything up
    valveModel.removeCoaptationModel(0)
    self.assertEqual(len(valveModel.coaptationModels), 0)
    self.assertNotInScene(surface)
    self.assertEqual(heartValveNode.GetNumberOfNodeReferences("CoaptationBaseLineMarkup"), 0)
    self.assertEqual(self._sequenceCount(), sequencesBefore, "sequences of a removed coaptation must not be left behind")
    self.assertNodeCountsEqual(censusBefore, scene.nodeCensus(), "no orphan nodes after removing a coaptation")

  # ---------------------------------------------------------------------------------------------
  # Transforms and ROI
  # ---------------------------------------------------------------------------------------------

  def test_onProbeToRasTransformNodeChanged_reparents_all_nodes(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,), roi=True, segmentation=True)
    factory.addPapillaryMuscles(valveBrowser)
    factory.addCoaptation(valveBrowser)
    valveModel = valveBrowser.valveModel
    oldProbe = valveBrowser.probeToRasTransformNode
    newProbe = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "NewProbe")
    factory.volumeProxyNode.SetAndObserveTransformNodeID(newProbe.GetID())
    valveBrowser.valveVolumeNode = factory.volumeProxyNode  # notifies the valve model
    self.assertEqual(valveBrowser.probeToRasTransformNode.GetID(), newProbe.GetID())
    nodes = [valveModel.annulusContourCurveNode, valveModel.valveLabelsNode, valveModel.valveRoiModelNode,
             valveModel.leafletSegmentationNode, valveModel.leafletVolumeNode]
    nodes += [m.getPapillaryLineMarkupNode() for m in valveModel.papillaryModels]
    nodes += [m.surfaceModelNode for m in valveModel.leafletModels] + [m.surfaceBoundary for m in valveModel.leafletModels]
    nodes += [valveModel.coaptationModels[0].surfaceModelNode, valveModel.coaptationModels[0].baseLine,
              valveModel.coaptationModels[0].marginLine]
    for node in nodes:
      self.assertIsNotNone(node)
      self.assertParentTransformIs(node, newProbe, node.GetName())
    self.assertNotEqual(oldProbe.GetID(), newProbe.GetID())

  def test_valve_roi(self):
    from HeartValveLib import ValveRoi  # the class, as ValveSegmentation imports it
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral", probePosition="UNKNOWN")
    factory.addTimePoint(valveBrowser, 2)
    valveModel = valveBrowser.valveModel
    roi = valveModel.valveRoi
    with self.assertRaises(RuntimeError):
      ValveRoi().setRoiGeometry({})
    self.assertEqual(ValveRoi().getRoiGeometry(), {})

    roiNode = valveModel.createValveRoiModelNode()
    self.assertIs(valveModel.valveRoiModelNode, roiNode)
    self.assertEqual(roi.getRoiGeometry(), {"ValveRoiScale": 120.0, "ValveRoiTopDistance": 10.0, "ValveRoiTopScale": 50.0,
                                            "ValveRoiBottomDistance": 30.0, "ValveRoiBottomScale": 50.0},
                     "defaults are written to a fresh ROI node")
    self.assertEqual(roiNode.GetPolyData().GetNumberOfPoints(), 0, "no contour -> empty ROI")

    factory.setContour(valveBrowser, 2)
    roi.setAnnulusContourCurve(valveModel.annulusContourCurveNode)
    self.assertGreater(roiNode.GetPolyData().GetNumberOfPoints(), 0)
    bounds = roiNode.GetPolyData().GetBounds()
    self.assertLess(bounds[4], -25.0, "ROI extends below the annulus by the bottom distance")
    self.assertGreater(bounds[5], 5.0, "ROI extends above the annulus by the top distance")
    roi.setRoiGeometry({"ValveRoiScale": 100, "ValveRoiTopDistance": 1, "ValveRoiTopScale": 100,
                        "ValveRoiBottomDistance": 1, "ValveRoiBottomScale": 100})
    bounds = roiNode.GetPolyData().GetBounds()
    self.assertAlmostEqual(bounds[5], 1.0 + 0.3, delta=0.5)
    self.assertAlmostEqual(bounds[4], -1.0 - 0.3, delta=0.5)
    # Geometry parameters are per time point (stored on the ROI node, which is sequenced)
    factory.addTimePoint(valveBrowser, 4)
    factory.setContour(valveBrowser, 4)
    factory.addRoi(valveBrowser)
    self.assertEqual(roi.getRoiGeometry()["ValveRoiScale"], 120.0, "new time point starts from defaults")
    factory.switchTo(valveBrowser, 2)
    self.assertEqual(roi.getRoiGeometry()["ValveRoiTopDistance"], 1.0)

    # Clipping the (synthetic, constant) valve volume with the ROI zeroes voxels outside the ROI
    roi.setRoiGeometry({"ValveRoiScale": 100, "ValveRoiTopDistance": 2, "ValveRoiTopScale": 100,
                        "ValveRoiBottomDistance": 2, "ValveRoiBottomScale": 100})
    output = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Clipped")
    roi.clipVolumeWithModel(factory.volumeProxyNode, output)
    array = slicer.util.arrayFromVolume(output)
    self.assertEqual(int(array.max()), 3, "inside voxels keep the frame value")
    self.assertGreater(int(np.count_nonzero(array == 0)), 0, "outside voxels are cleared")
    self.assertGreater(int(np.count_nonzero(array)), 0)
    self.assertLess(int(np.count_nonzero(array)), array.size)

  # ---------------------------------------------------------------------------------------------
  # helpers module
  # ---------------------------------------------------------------------------------------------

  def test_helpers_lookup_functions(self):
    from HeartValveLib import helpers
    factory = NewFormatValveFactory()
    mitralA = factory.createAnnotatedValve("mitral", frames=(3,), phases=("mid-systole",))
    mitralB = factory.createAnnotatedValve("mitral", frames=(1,), phases=("end-diastole",), roi=True, segmentation=True)
    aortic = factory.createAnnotatedValve("aortic", frames=(2,), phases=("mid-systole",))

    self.assertEqual(len(list(helpers.getAllHeartValveNodes())), 3)
    models = helpers.getAllHeartValveModelsForValveType("mitral")
    self.assertEqual([m.getValveVolumeSequenceIndex() for m in models], [1, 3], "sorted by frame")
    self.assertIs(models[0], mitralB.valveModel)
    self.assertEqual(helpers.getAllHeartValveModelsForValveType("tricuspid"), [])
    self.assertIs(helpers.getFirstValveModelNodeMatchingPhase("ED"), mitralB.valveModel)
    with self.assertRaises(ValueError):
      helpers.getFirstValveModelNodeMatchingPhase("P4")
    self.assertIs(helpers.getFirstValveModelNodeMatchingPhaseAndType("MS", "aortic"), aortic.valveModel)
    self.assertIs(helpers.getFirstValveModelNodeMatchingSequenceIndex(2), aortic.valveModel)
    self.assertIs(helpers.getFirstValveModelNodeMatchingSequenceIndexAndValveType(3, "mitral"), mitralA.valveModel)
    with self.assertRaises(ValueError):
      helpers.getFirstValveModelNodeMatchingSequenceIndexAndValveType(3, "aortic")
    self.assertEqual(len(list(helpers.getSpecificHeartValveModelNodes(["MS"]))), 2)
    self.assertEqual(len(list(helpers.getSpecificHeartValveModelNodes(["MS", "ED"]))), 3)
    self.assertEqual(len(list(helpers.getSpecificHeartValveModelNodes(["P1"]))), 0)
    byPhaseAndType = helpers.getSpecificHeartValveModelNodesMatchingPhaseAndType(["ED", "MS"], "mitral")
    self.assertEqual([helpers.getValvePhaseShortName(m) for m in byPhaseAndType], ["ED", "MS"])
    self.assertEqual(helpers.getValveModelNodesMatchingPhaseAndType("MS", "mitral"), [mitralA.valveModel])
    self.assertIs(helpers.getValveModelForSegmentationNode(mitralB.valveModel.leafletSegmentationNode), mitralB.valveModel)
    self.assertIsNone(helpers.getValveModelForSegmentationNode(None))
    self.assertEqual(list(helpers.getAllHeartValveMeasurementNodes()), [])

  def test_setValveModelDataVisibility(self):
    from HeartValveLib import helpers
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,), roi=True, segmentation=True)
    valveModel = valveBrowser.valveModel
    helpers.setValveModelDataVisibility(valveModel, annulus=False, annulusLabels=False, segmentation=False, roi=False)
    self.assertFalse(valveModel.annulusContourCurveNode.GetDisplayNode().GetVisibility())
    self.assertFalse(valveModel.valveLabelsNode.GetDisplayNode().GetVisibility())
    self.assertFalse(valveModel.leafletSegmentationNode.GetDisplayNode().GetVisibility())
    self.assertFalse(valveModel.valveRoiModelNode.GetDisplayNode().GetVisibility())
    helpers.setValveModelDataVisibility(valveModel, annulus=True, annulusLabels=True, segmentation=True, roi=True)
    self.assertTrue(valveModel.annulusContourCurveNode.GetDisplayNode().GetVisibility())
    self.assertTrue(valveModel.leafletSegmentationNode.GetDisplayNode().GetVisibility())
    helpers.hideAllSlicerHeartData()
    self.assertFalse(valveModel.annulusContourCurveNode.GetDisplayNode().GetVisibility())

  # ---------------------------------------------------------------------------------------------
  # Real data smoke test
  # ---------------------------------------------------------------------------------------------

  def test_real_data_smoke(self):
    import HeartValveLib
    import ValveModelTest
    volumeBrowserNode = scene.loadMitralSample()
    factory = NewFormatValveFactory(volumeBrowserNode=volumeBrowserNode)
    valveBrowser = factory.createValveBrowser("mitral", probePosition="TTE_APICAL")
    valveModel = None
    contours = {5: ValveModelTest.ValveModelTestTest.MITRAL_ANNULUS_CONTOUR_FRAME0,
                24: ValveModelTest.ValveModelTestTest.MITRAL_ANNULUS_CONTOUR_FRAME1}
    for frame, contour in contours.items():
      factory.addTimePoint(valveBrowser, frame, phase="mid-systole" if frame == 5 else "end-diastole")
      valveModel = valveBrowser.valveModel
      valveModel.setAnnulusContourPoints(contour)
      valveModel.setValveLabels(ValveModelTest.ValveModelTestTest._annulusLandmarkLabels(contour))
      factory.addRoi(valveBrowser)
      self.assertGreater(valveModel.valveRoiModelNode.GetPolyData().GetNumberOfPoints(), 0)
      segmentationNode = valveModel.initializeLeafletSegmentation()
      self.assertIsNotNone(segmentationNode)
      self.assertGreater(self._segmentVoxelCount(segmentationNode, HeartValveLib.VALVE_MASK_SEGMENT_ID), 0,
                         f"valve mask at frame {frame}")
      self.assertEqual(valveModel.getValveVolumeSequenceIndex(), frame)
    factory.switchTo(valveBrowser, 5)
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, contours[5], msg="frame 5")
    self.assertEqual(valveModel.getAnnulusMarkupLabels(), ["A", "L", "P", "S"])
    factory.switchTo(valveBrowser, 24)
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, contours[24], msg="frame 24")
