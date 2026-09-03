"""
ValveBatchExportRulesTest.py

Rule-level tests for the ValveBatchExport export rules on multi-time-point valves. Each rule is
driven through its lifecycle (processStart / processScene / processEnd) on a synthetic scene with
the output written to a temporary directory. The ValveBatchExportRules package is imported directly
(importing the ValveBatchExport module script builds Qt widgets at import time).
"""

import csv
import os
import sys

import numpy as np
import slicer
from slicer.ScriptedLoadableModule import *

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTLIB_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "ValveAnnulusAnalysis", "Testing", "Python"))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class ValveBatchExportRulesTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ValveBatchExportRulesTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "ValveQuantification", "ValveBatchExport",
                                "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for the ValveBatchExport rules on multi-time-point valves."
    self.parent.acknowledgementText = ""


class ValveBatchExportRulesTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class ValveBatchExportRulesTestLogic(ScriptedLoadableModuleLogic):
  pass


class ValveBatchExportRulesTestTest(SlicerHeartTestCase):

  SCENE_FILE = "C:/data/Case01.mrb"

  # ---------------------------------------------------------------------------------------------
  # Fixture
  # ---------------------------------------------------------------------------------------------

  def setUp(self):
    SlicerHeartTestCase.setUp(self)
    import ValveBatchExportRules
    self.rules = ValveBatchExportRules
    base = ValveBatchExportRules.ValveBatchExportRule
    # These are mutable class attributes shared by every rule; keep tests independent
    base.setPhasesToExport([])
    base.setValveTypesToExport([])
    self.logs = []

  def tearDown(self):
    base = self.rules.ValveBatchExportRule
    base.setPhasesToExport([])
    base.setValveTypesToExport([])
    SlicerHeartTestCase.tearDown(self)

  # Segment names follow the SlicerHeart convention the export rules sort by (lower-case location)
  SEGMENTS = [("Anterior", "anterior leaflet", (1.0, 0.0, 0.0), (1.2, 0.0, 0.0)),
              ("Posterior", "posterior leaflet", (0.0, 1.0, 0.0), (-1.2, 0.0, 0.0))]

  def _buildScene(self, segmentation=True, aortic=True):
    factory = NewFormatValveFactory()
    mitral = factory.createAnnotatedValve("mitral", frames=(1, 4), phases=("mid-systole", "end-diastole"), roi=segmentation)
    if segmentation:
      for frame in (1, 4):
        factory.switchTo(mitral, frame)
        factory.addSegmentation(mitral, segments=self.SEGMENTS)
    if aortic:
      factory.createAnnotatedValve("aortic", frames=(2,), phases=("mid-systole",))
    return factory, mitral

  def _run(self, ruleClass, sceneFile=None, outputDir=None):
    rule = ruleClass()
    rule.outputDir = outputDir or self.tempDirectory()
    rule.logCallback = self.logs.append
    rule.processStart()
    rule.processScene(sceneFile or self.SCENE_FILE)
    rule.afterProcessScene(sceneFile or self.SCENE_FILE)
    rule.processEnd()
    return rule

  @staticmethod
  def _readCsv(path):
    with open(path, newline="") as f:
      return list(csv.DictReader(f))

  @staticmethod
  def _files(directory, suffix=""):
    return sorted(n for n in os.listdir(directory) if n.endswith(suffix))

  # ---------------------------------------------------------------------------------------------
  # Selection
  # ---------------------------------------------------------------------------------------------

  def test_valve_type_filter(self):
    self._buildScene(segmentation=False)
    self.rules.ValveBatchExportRule.setValveTypesToExport(["mitral"])
    rule = self._run(self.rules.AnnulusContourCoordinatesExportRule)
    rows = self._readCsv(os.path.join(rule.outputDir, rule.CURVE_POINTS_CSV_OUTPUT_FILENAME))
    self.assertTrue(rows)
    self.assertEqual({r["Valve"] for r in rows}, {"mitral"})
    self.rules.ValveBatchExportRule.setValveTypesToExport(["aortic"])
    rule = self._run(self.rules.AnnulusContourCoordinatesExportRule)
    rows = self._readCsv(os.path.join(rule.outputDir, rule.CURVE_POINTS_CSV_OUTPUT_FILENAME))
    self.assertEqual({r["Valve"] for r in rows}, {"aortic"})
    self.rules.ValveBatchExportRule.setValveTypesToExport(["tricuspid"])
    rule = self._run(self.rules.AnnulusContourCoordinatesExportRule)
    self.assertEqual(self._readCsv(os.path.join(rule.outputDir, rule.CURVE_POINTS_CSV_OUTPUT_FILENAME)), [])

  def test_phase_filter_selects_time_points(self):
    self._buildScene(segmentation=False)
    self.rules.ValveBatchExportRule.setPhasesToExport(["ED"])
    rule = self._run(self.rules.AnnulusContourCoordinatesExportRule)
    rows = self._readCsv(os.path.join(rule.outputDir, rule.CURVE_POINTS_CSV_OUTPUT_FILENAME))
    self.assertTrue(rows, "the ED time point must be exported")
    self.assertEqual({r["Phase"] for r in rows}, {"ED"}, "only the selected phase may be exported")
    self.assertEqual({r["FrameNumber"] for r in rows}, {"4"})

  # ---------------------------------------------------------------------------------------------
  # Rules
  # ---------------------------------------------------------------------------------------------

  def test_annulus_contour_coordinates_per_time_point(self):
    factory, mitral = self._buildScene(segmentation=False)
    # The scene also contains an aortic valve (frame 2); without a valve type filter all valves are exported
    self.rules.ValveBatchExportRule.setValveTypesToExport(["mitral"])
    ruleClass = self.rules.AnnulusContourCoordinatesExportRule
    ruleClass.EXPORT_CURVE_POINT_COORDINATES = True
    ruleClass.EXPORT_CONTROL_POINT_COORDINATES = True
    try:
      rule = self._run(ruleClass)
    finally:
      ruleClass.EXPORT_CONTROL_POINT_COORDINATES = False
    curveRows = self._readCsv(os.path.join(rule.outputDir, rule.CURVE_POINTS_CSV_OUTPUT_FILENAME))
    controlRows = self._readCsv(os.path.join(rule.outputDir, rule.CONTROL_POINTS_CSV_OUTPUT_FILENAME))
    self.assertEqual(set(curveRows[0].keys()), set(ruleClass.COLUMNS))
    self.assertEqual({r["Valve"] for r in controlRows}, {"mitral"}, "Valve column must hold the valve type")
    byFrame = {}
    for r in controlRows:
      byFrame.setdefault(r["FrameNumber"], []).append((float(r["AnnulusContourX"]), float(r["AnnulusContourY"]),
                                                        float(r["AnnulusContourZ"])))
    self.assertEqual(sorted(byFrame), ["1", "4"], "one block per annotated time point")
    self.assertEqual(len(byFrame["1"]), 12)
    self.assertEqual(len(byFrame["4"]), 12)
    np.testing.assert_allclose(byFrame["1"], NewFormatValveFactory.contourPoints(1), atol=0.01)
    np.testing.assert_allclose(byFrame["4"], NewFormatValveFactory.contourPoints(4), atol=0.01)
    phases = {r["FrameNumber"]: r["Phase"] for r in controlRows}
    self.assertEqual(phases, {"1": "MS", "4": "ED"})
    labels = {(r["FrameNumber"], r["AnnulusContourLabel"]) for r in controlRows if r["AnnulusContourLabel"]}
    self.assertEqual(labels, {(f, l) for f in ("1", "4") for l in ("A", "L", "P", "S")}, "landmark labels per time point")
    self.assertTrue(all(r["Filename"] == "Case01" for r in curveRows))
    self.assertGreater(len([r for r in curveRows if r["FrameNumber"] == "1"]), 12,
                       "curve points are denser than control points")

  def test_landmark_coordinates(self):
    self._buildScene(segmentation=False)
    rule = self._run(self.rules.ValveLandmarkCoordinatesExportRule)
    rows = self._readCsv(os.path.join(rule.outputDir, rule.CSV_OUTPUT_FILENAME))
    self.assertEqual(set(rows[0].keys()), set(rule.COLUMNS))
    mitralRows = [r for r in rows if r["Phase"] in ("MS", "ED") and r["Valve"] == "mitral"]
    self.assertEqual(len(mitralRows), 8, "4 landmarks x 2 time points; the Valve column must hold the valve type: "
                                         + str(rows[:2]))
    self.assertEqual({r["FrameNumber"] for r in mitralRows}, {"1", "4"})
    self.assertEqual({r["LandmarkLabel"] for r in mitralRows}, {"A", "L", "P", "S"})
    expected = NewFormatValveFactory.labelPoints(4)[0]
    row = [r for r in mitralRows if r["FrameNumber"] == "4" and r["LandmarkLabel"] == "A"][0]
    self.assertAlmostEqual(float(row["LandmarkR"]), expected[1], places=1)

  def test_volume_frame_export(self):
    factory, mitral = self._buildScene(segmentation=False, aortic=False)
    rule = self._run(self.rules.ValveVolumeFrameExportRule)
    files = self._files(rule.outputDir, ".nii.gz")
    self.assertEqual(len(files), 2, f"one volume per annotated time point: {files}")
    values = set()
    for name in files:
      volumeNode = slicer.util.loadVolume(os.path.join(rule.outputDir, name))
      values.add(scene.volumeVoxelValue(volumeNode))
      self.assertIn("mitral", name)
    self.assertEqual(values, {2, 5}, "each file must contain its own frame (frame 1 -> value 2, frame 4 -> value 5)")

  def test_volume_sequence_export(self):
    factory, mitral = self._buildScene(segmentation=False)
    rule = self._run(self.rules.ValveVolumeExportRule)
    files = self._files(rule.outputDir, ".seq.nrrd")
    self.assertGreaterEqual(len(files), 1, "sequence written")
    self.assertTrue(any("mitral" in n for n in files) and any("aortic" in n for n in files),
                    f"two valves in one scene need distinguishable output names: {files}")

  def test_leaflet_segmentation_export(self):
    factory, mitral = self._buildScene(segmentation=True, aortic=False)
    valveModel = mitral.valveModel
    sequenceNode = valveModel.leafletSegmentationSequenceNode
    rule = self._run(self.rules.LeafletSegmentationExportRule)
    files = self._files(rule.outputDir, ".seg.nrrd")
    self.assertEqual(len(files), 2, f"one segmentation per annotated time point: {files}")
    for name in files:
      self.assertIn("leaflets", name)
    for indexValue in (factory.indexValue(1), factory.indexValue(4)):
      stored = sequenceNode.GetDataNodeAtValue(indexValue).GetSegmentation()
      self.assertIn("ValveMask", stored.GetSegmentIDs(), "export must not delete the valve mask from the scene")
      self.assertEqual(stored.GetNumberOfSegments(), 3)
    exported = slicer.util.loadSegmentation(os.path.join(rule.outputDir, files[0]))
    self.assertNotIn("ValveMask", exported.GetSegmentation().GetSegmentIDs(), "mask removed from the export")
    self.assertEqual(exported.GetSegmentation().GetNumberOfSegments(), 2)

  def test_leaflet_order_helpers(self):
    rules = self.rules
    self.assertEqual(rules.getLeafletOrderDefinition("Mitral"), ["anterior", "posterior"])
    with self.assertRaises(ValueError):
      rules.getLeafletOrderDefinition("pulmonary")
    self.assertTrue(rules.isSorted(["anterior", "posterior"], ["mitral_anterior_leaflet", "mitral_posterior_leaflet"]))
    self.assertFalse(rules.isSorted(["anterior", "posterior"], ["posterior leaflet", "anterior leaflet"]))
    segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    segmentationNode.CreateDefaultDisplayNodes()
    scene.addSphereSegment(segmentationNode, "Seg_2", "posterior leaflet", (-1, 0, 0), 1.0, (0, 1, 0))
    scene.addSphereSegment(segmentationNode, "Seg_1", "anterior leaflet", (1, 0, 0), 1.0, (1, 0, 0))
    message = rules.checkAndSortSegments(segmentationNode, "mitral")
    self.assertTrue(message)
    self.assertEqual(list(segmentationNode.GetSegmentation().GetSegmentIDs()),
                     ["mitral_anterior_leaflet", "mitral_posterior_leaflet"])
    self.assertEqual(rules.checkAndSortSegments(segmentationNode, "mitral"), "", "already sorted")

  def test_quantification_results_per_time_point(self):
    factory, mitral = self._buildScene(segmentation=False, aortic=False)
    measurementNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode", "Measurement")
    measurementNode.SetHideFromEditors(False)
    measurementNode.SetAttribute("ModuleName", "HeartValveMeasurement")
    measurementNode.SetAttribute("MeasurementPreset", "GenericValve")
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    shNode.RequestOwnerPluginSearch(measurementNode)
    measurementNode.SetNodeReferenceID("ValveValve", mitral.heartValveNode.GetID())
    # Presets are shared objects; drop results of previous scenes so this test measures the time
    # point behaviour only (the leak itself is covered by ValveQuantificationSequenceTest)
    quantLogic = slicer.modules.valvequantification.widgetRepresentation().self().logic
    quantLogic.getMeasurementPresetById("GenericValve").metricsTable = None
    self.rules.ValveBatchExportRule.setPhasesToExport(["MS", "ED"])
    rule = self._run(self.rules.QuantificationResultsExportRule)
    longRows = self._readCsv(os.path.join(rule.outputDir, rule.LONG_CSV_OUTPUT_FILENAME))
    self.assertTrue(longRows, "results written")
    phases = {r["Phase"] for r in longRows}
    self.assertEqual(phases, {"MS", "ED"}, "a measurement of a multi-time-point valve must be exported per time point")
    areaRows = [r for r in longRows if r["Measurement"] == "Annulus area (3D)"]
    self.assertEqual(len(areaRows), 2)
    self.assertNotEqual(areaRows[0]["Value"], areaRows[1]["Value"], "the two time points have different contours")
    hybridRows = self._readCsv(os.path.join(rule.outputDir, rule.HYBRID_CSV_OUTPUT_FILENAME))
    self.assertIn("MS", hybridRows[0].keys())
    self.assertIn("ED", hybridRows[0].keys())

  def test_rules_restore_browser_selection(self):
    factory, mitral = self._buildScene(segmentation=True, aortic=False)
    browserNode = mitral.valveBrowserNode
    for ruleClass in (self.rules.AnnulusContourCoordinatesExportRule, self.rules.ValveLandmarkCoordinatesExportRule,
                      self.rules.LeafletSegmentationExportRule):
      scene.selectIndexValue(browserNode, factory.indexValue(1))
      factory.selectFrame(1)
      self._run(ruleClass)
      self.assertEqual(browserNode.GetSelectedItemNumber(), 0, f"{ruleClass.__name__} must restore the valve time point")

  def test_generateValveModelName_and_unique_names(self):
    rule = self.rules.AnnulusContourCoordinatesExportRule()
    self.assertEqual(rule.generateValveModelName("Case01", "mitral", "MS", 4, "volume"), "Case01_mitral_frame_4_MS_volume")
    self.assertEqual(rule.generateValveModelName("Case01", "mitral", "MS"), "Case01_mitral_MS")
    self.assertEqual(rule.generateValveModelName("Case01", "mitral", "MS"), "Case01_mitral_MS_1")
    self.assertEqual(rule.generateValveModelName("Case01", "mitral", "MS"), "Case01_mitral_MS_2")
    factory, mitral = self._buildScene(segmentation=False, aortic=False)
    self.assertEqual(rule.getAssociatedFrameNumber(mitral.valveModel), 4)
    factory.switchTo(mitral, 1)
    self.assertEqual(rule.getAssociatedFrameNumber(mitral.valveModel), 1)

  def test_exportMRBFile_and_mergeTables(self):
    import ValveBatchExport
    factory, mitral = self._buildScene(segmentation=False, aortic=False)
    tempDir = self.tempDirectory()
    mrbPath = scene.saveSceneToMrb(tempDir, "Case01.mrb")
    outputDir = os.path.join(tempDir, "out", "Case01")
    logic = ValveBatchExport.ValveBatchExportLogic(logCallback=self.logs.append)
    logic.addRule(self.rules.ValveLandmarkCoordinatesExportRule)
    logic.addRule(self.rules.AnnulusContourCoordinatesExportRule)
    logic.exportMRBFile(mrbPath, outputDir)
    self.assertTrue(os.path.exists(os.path.join(outputDir, "ValveLandmarkPoints.csv")))
    self.assertTrue(os.path.exists(os.path.join(outputDir, "AnnulusContourCurvePoints.csv")))
    rows = self._readCsv(os.path.join(outputDir, "ValveLandmarkPoints.csv"))
    self.assertEqual({r["Filename"] for r in rows}, {"Case01"})
    self.assertEqual(len(rows), 8)
    # Existing outputs are skipped on a second run
    self.logs.clear()
    logic.exportMRBFile(mrbPath, outputDir)
    self.assertFalse(any("Exporting mrb file" in m for m in self.logs), "existing outputs are not re-exported")
    logic.exportMRBFile(os.path.join(tempDir, "nothing.txt"), outputDir)
    self.assertTrue(any("not a mrb file" in m for m in self.logs))
    # Merging two case directories concatenates the tables
    secondDir = os.path.join(tempDir, "out", "Case02")
    os.makedirs(secondDir)
    import shutil
    shutil.copy(os.path.join(outputDir, "ValveLandmarkPoints.csv"), os.path.join(secondDir, "ValveLandmarkPoints.csv"))
    mergedDir = os.path.join(tempDir, "merged")
    os.makedirs(mergedDir)
    self.rules.ValveLandmarkCoordinatesExportRule().mergeTables([outputDir, secondDir], mergedDir)
    merged = self._readCsv(os.path.join(mergedDir, "ValveLandmarkPoints.csv"))
    self.assertEqual(len(merged), 8, "identical rows are de-duplicated when merging")
