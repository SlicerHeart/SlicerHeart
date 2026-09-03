"""
ValveQuantificationSequenceTest.py

Tests for the sequence (per-time-point) behaviour of valve quantification: measurement nodes that
reference valve proxies, results tables and metric models stored per time point, multi-valve
references across save/reload, the "compute all phases" widget action and preset helpers.

All tests run on a small synthetic volume sequence (no downloads).
"""

import os
import sys

import numpy as np
import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTLIB_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "ValveAnnulusAnalysis", "Testing", "Python"))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class ValveQuantificationSequenceTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ValveQuantificationSequenceTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "ValveQuantification",
                                "Converter4DSequences", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for per-time-point valve quantification."
    self.parent.acknowledgementText = ""


class ValveQuantificationSequenceTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class ValveQuantificationSequenceTestLogic(ScriptedLoadableModuleLogic):
  pass


class ValveQuantificationSequenceTestTest(SlicerHeartTestCase):

  # ---------------------------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _quantLogic():
    import ValveQuantification
    return ValveQuantification.ValveQuantificationLogic()

  @staticmethod
  def _createMeasurementNode(presetId, valveRoles, name="Measurement"):
    """Create a measurement node the way the ValveQuantification module does once it is selected
    (visible, with a subject hierarchy item so results can be nested under it)."""
    measurementNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode", name)
    measurementNode.SetHideFromEditors(False)
    measurementNode.SetAttribute("ModuleName", "HeartValveMeasurement")
    measurementNode.SetAttribute("MeasurementPreset", presetId)
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    shNode.RequestOwnerPluginSearch(measurementNode)
    shNode.SetItemAttribute(shNode.GetItemByDataNode(measurementNode), "ModuleName", "HeartValveMeasurement")
    for role, node in valveRoles.items():
      measurementNode.SetNodeReferenceID(role, node.GetID())
    return measurementNode

  @staticmethod
  def _tableRows(tableNode):
    return {tableNode.GetCellText(r, 0): tableNode.GetCellText(r, 1) for r in range(tableNode.GetNumberOfRows())}

  def _widget(self):
    widget = slicer.modules.valvequantification.widgetRepresentation().self()
    self.assertIsNotNone(widget)
    return widget

  # ---------------------------------------------------------------------------------------------
  # Logic
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _quantificationValveModel(valveBrowser):
    """The ValveModel object the quantification code uses for the valve (see
    MeasurementPreset.computeMetricsForMeasurementNode)."""
    import HeartValveLib
    return HeartValveLib.HeartValves.getValveModel(valveBrowser.heartValveNode)

  def test_generic_valve_metrics_per_time_point(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3))
    valveModel = self._quantificationValveModel(valveBrowser)
    browserNode = valveBrowser.valveBrowserNode
    quantLogic = self._quantLogic()
    preset = quantLogic.getMeasurementPresetById("GenericValve")
    self.assertIsNotNone(preset)
    self.assertIsNone(quantLogic.getMeasurementPresetById("NoSuchPreset"))
    measurementNode = self._createMeasurementNode("GenericValve", {"ValveValve": valveBrowser.heartValveNode})
    self.assertIs(quantLogic.getMeasurementPresetByMeasurementNode(measurementNode), preset)

    factory.switchTo(valveBrowser, 1)
    messages = quantLogic.computeMetrics(measurementNode)
    self.assertIsInstance(messages, list)
    tableNode = preset.metricsTable.metricTableNode
    self.assertIsNotNone(tableNode)
    rows1 = self._tableRows(tableNode)
    self.assertIn("Annulus area (3D)", rows1)
    self.assertGreater(float(rows1["Annulus area (3D)"]), 0.0)
    tableSequence = browserNode.GetSequenceNode(tableNode)
    self.assertIsNotNone(tableSequence, "results table is stored per time point")
    self.assertSequenceIndexValues(tableSequence, [factory.indexValue(1)])
    self.assertShParentIs(tableNode, measurementNode, "table nested under the measurement")
    modelsAfterFirst = len(slicer.util.getNodesByClass("vtkMRMLModelNode"))
    self.assertGreater(len(valveModel.metricsResults), 0, "metric model nodes are cached")
    for name, modelNode in valveModel.metricsResults.items():
      self.assertInScene(modelNode, name)
      modelSequence = browserNode.GetSequenceNode(modelNode)
      self.assertIsNotNone(modelSequence, f"metric model {name} sequenced")
      self.assertSequenceHasItem(modelSequence, factory.indexValue(1), name)

    factory.switchTo(valveBrowser, 3)
    quantLogic.computeMetrics(measurementNode)
    self.assertIs(preset.metricsTable.metricTableNode, tableNode, "same table proxy at every time point")
    rows3 = self._tableRows(tableNode)
    self.assertNotEqual(rows1["Annulus area (3D)"], rows3["Annulus area (3D)"], "contours differ per time point")
    self.assertSequenceIndexValues(tableSequence, [factory.indexValue(1), factory.indexValue(3)])
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLModelNode")), modelsAfterFirst,
                     "metric model nodes are reused, not duplicated")
    for name, modelNode in valveModel.metricsResults.items():
      self.assertSequenceHasItem(browserNode.GetSequenceNode(modelNode), factory.indexValue(3), name)

    # Scrubbing back shows the first time point's results again
    factory.switchTo(valveBrowser, 1)
    self.assertEqual(self._tableRows(tableNode)["Annulus area (3D)"], rows1["Annulus area (3D)"])
    # Recomputing does not add nodes
    quantLogic.computeMetrics(measurementNode)
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLModelNode")), modelsAfterFirst)
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLTableNode")), 1)

  def test_computeMetrics_without_valve_reference(self):
    quantLogic = self._quantLogic()
    measurementNode = self._createMeasurementNode("GenericValve", {})
    messages = quantLogic.computeMetrics(measurementNode)
    self.assertTrue(any("required" in m.lower() for m in messages), messages)
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLTableNode")), 0)

  def test_recompute_is_cheap_when_items_exist(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,))
    valveModel = self._quantificationValveModel(valveBrowser)
    quantLogic = self._quantLogic()
    measurementNode = self._createMeasurementNode("GenericValve", {"ValveValve": valveBrowser.heartValveNode})
    quantLogic.computeMetrics(measurementNode)
    numberOfMetricModels = len(valveModel.metricsResults)
    self.assertGreater(numberOfMetricModels, 1)
    with scene.ModifiedEventCounter(valveModel.valveLabelsNode) as labelEvents:
      quantLogic.computeMetrics(measurementNode)
    self.assertEqual(labelEvents.count, 0, "recomputing must not re-sync unrelated proxies for every metric model")

  def test_multi_valve_references_survive_save_and_reload(self):
    import Converter4DSequences
    factory = NewFormatValveFactory()
    mitral = factory.createAnnotatedValve("mitral", frames=(1,))
    aortic = factory.createAnnotatedValve("aortic", frames=(2,))
    measurementNode = self._createMeasurementNode("MitralValve", {"ValveMitralValve": mitral.heartValveNode,
                                                                 "ValveAorticValve": aortic.heartValveNode})
    # With auto conversion enabled the reload must not treat the new-format measurement as legacy
    self.setSetting(Converter4DSequences.Converter4DSequences.AUTO_CONVERT_SETTING_KEY, True)
    scene.saveAndReloadScene(self.tempDirectory(), resetCaches=self.resetHeartValveLibCaches)
    for _ in range(20):
      slicer.app.processEvents()
    measurementNodes = scene.measurementNodes()
    self.assertEqual(len(measurementNodes), 1)
    measurementNode = measurementNodes[0]
    self.assertFalse(slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(measurementNode),
                     "new-format measurement must not be sequenced by auto conversion")
    browsers = {b.valveType: b for b in [HeartValveLibBrowser(n) for n in scene.valveBrowserNodes()]}
    self.assertEqual(sorted(browsers), ["aortic", "mitral"])
    self.assertEqual(measurementNode.GetNodeReference("ValveMitralValve").GetID(), browsers["mitral"].heartValveNode.GetID())
    self.assertEqual(measurementNode.GetNodeReference("ValveAorticValve").GetID(), browsers["aortic"].heartValveNode.GetID())
    self.assertFalse(Converter4DSequences.Converter4DSequencesLogic().sceneHasConvertibleNodes())

  def test_getMeasurementCardiacCyclePhaseShortNames(self):
    factory = NewFormatValveFactory()
    mitral = factory.createAnnotatedValve("mitral", frames=(1,), phases=("mid-systole",))
    aortic = factory.createAnnotatedValve("aortic", frames=(2,), phases=("mid-systole",))
    quantLogic = self._quantLogic()
    measurementNode = self._createMeasurementNode("MitralValve", {"ValveMitralValve": mitral.heartValveNode,
                                                                 "ValveAorticValve": aortic.heartValveNode})
    self.assertEqual(quantLogic.getMeasurementCardiacCyclePhaseShortNames(measurementNode), ["MS"])
    aortic.valveModel.setCardiacCyclePhase("end-diastole")
    self.assertEqual(quantLogic.getMeasurementCardiacCyclePhaseShortNames(measurementNode), ["MS", "ED"])
    onlyMitral = self._createMeasurementNode("MitralValve", {"ValveMitralValve": mitral.heartValveNode})
    self.assertEqual(quantLogic.getMeasurementCardiacCyclePhaseShortNames(onlyMitral), ["MS"])
    from HeartValveLib import helpers
    self.assertIs(helpers.getHeartValveMeasurementNode("MS"), onlyMitral)
    self.assertIsNone(helpers.getHeartValveMeasurementNode("P4"))

  def test_preset_state_does_not_leak_across_scenes(self):
    """Measurement presets are shared (class-level) objects; results of a previous scene must not be
    written into nodes of that (closed) scene."""
    quantLogic = self._quantLogic()
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,))
    measurementNode = self._createMeasurementNode("GenericValve", {"ValveValve": valveBrowser.heartValveNode})
    quantLogic.computeMetrics(measurementNode)
    preset = quantLogic.getMeasurementPresetById("GenericValve")
    oldTable = preset.metricsTable.metricTableNode

    slicer.mrmlScene.Clear(0)
    self.resetHeartValveLibCaches()
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(2,))
    measurementNode = self._createMeasurementNode("GenericValve", {"ValveValve": valveBrowser.heartValveNode})
    quantLogic.computeMetrics(measurementNode)
    tableNode = preset.metricsTable.metricTableNode
    self.assertIsNot(tableNode, oldTable, "a table of the closed scene must not be reused")
    self.assertInScene(tableNode, "results table of the new scene")
    self.assertIsNotNone(valveBrowser.valveBrowserNode.GetSequenceNode(tableNode), "results table sequenced in the new scene")
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLTableNode")), 1)

  def test_cavc_farthest_point_reset(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("cavc")
    factory.addTimePoint(valveBrowser, 1)
    contour = factory.setContour(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    valveModel.setValveLabels([("R", *contour[0])])
    quantLogic = self._quantLogic()
    preset = quantLogic.getMeasurementPresetById("Cavc")
    preset.onResetInputField("LPoint", {"Cavc": valveModel}, {})
    pointL = valveModel.getAnnulusMarkupPositionByLabel("L")
    self.assertIsNotNone(pointL, "L point must be placed")
    pointR = valveModel.getAnnulusMarkupPositionByLabel("R")
    self.assertGreater(np.linalg.norm(pointL - pointR), 4.0, "L is the point farthest from R")
    from HeartValveLib.util import getClosestPointPositionAlongCurve
    onCurve = getClosestPointPositionAlongCurve(valveModel.annulusContourCurveNode, pointL)
    self.assertLess(np.linalg.norm(onCurve - pointL), 0.3, "L lies on the annulus curve")

  def test_papillary_preset(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,))
    valveModel = valveBrowser.valveModel
    factory.addPapillaryMuscles(valveBrowser)
    quantLogic = self._quantLogic()
    measurementNode = self._createMeasurementNode("MitralValvePM", {"ValveMitralValve": valveBrowser.heartValveNode})
    messages = quantLogic.computeMetrics(measurementNode)
    preset = quantLogic.getMeasurementPresetById("MitralValvePM")
    rows = self._tableRows(preset.metricsTable.metricTableNode)
    self.assertTrue(any("muscle length" in name for name in rows), rows)
    self.assertTrue(any("chordal length" in name for name in rows), rows)
    self.assertFalse(any("doesn't have enough points" in m for m in messages), messages)
    # A muscle without points is reported, not computed
    valveModel.papillaryModels[0].getPapillaryLineMarkupNode().RemoveAllControlPoints()
    messages = quantLogic.computeMetrics(measurementNode)
    self.assertTrue(any("doesn't have enough points" in m for m in messages), messages)

  # ---------------------------------------------------------------------------------------------
  # Widget
  # ---------------------------------------------------------------------------------------------

  def test_widget_computeAllPhaseMetrics(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3, 5))
    browserNode = valveBrowser.valveBrowserNode
    widget = self._widget()
    measurementNode = self._createMeasurementNode("GenericValve", {"ValveValve": valveBrowser.heartValveNode})
    try:
      slicer.app.processEvents()
      widget.heartValveMeasurementSelector.setCurrentNode(measurementNode)
      slicer.app.processEvents()
      self.assertIs(widget.getHeartValveMeasurementNode(), measurementNode)
      self.assertIsNotNone(widget.measurementPreset, "preset selected from the measurement node")
      self.assertIn("Valve", widget.inputValveModels, "valve selector populated from the measurement reference")
      self.assertIsNotNone(widget.valveSequenceBrowserWidget.valveBrowser, "driver browser bound from the valve reference")
      self.assertEqual(widget.valveSequenceBrowserWidget.valveBrowserNode.GetID(), browserNode.GetID())
      scene.selectIndexValue(browserNode, factory.indexValue(3))
      widget.computeAllPhaseMetrics()
      self.assertEqual(browserNode.GetSelectedItemNumber(), 1, "original time point restored")
      preset = widget.logic.getMeasurementPresetById("GenericValve")
      tableNode = preset.metricsTable.metricTableNode
      self.assertInScene(tableNode, "results table")
      tableSequence = browserNode.GetSequenceNode(tableNode)
      self.assertIsNotNone(tableSequence, "results table must be sequenced on the driver browser")
      self.assertSequenceIndexValues(tableSequence, [factory.indexValue(f) for f in (1, 3, 5)])

      # A failure while computing one phase must still restore the original time point
      calls = []
      originalComputeMetrics = widget.logic.computeMetrics

      def failingComputeMetrics(node):
        calls.append(1)
        if len(calls) == 2:
          raise RuntimeError("simulated failure")
        return originalComputeMetrics(node)

      widget.logic.computeMetrics = failingComputeMetrics
      try:
        scene.selectIndexValue(browserNode, factory.indexValue(5))
        with self.assertRaises(RuntimeError):
          widget.computeAllPhaseMetrics()
      finally:
        widget.logic.computeMetrics = originalComputeMetrics
      self.assertEqual(browserNode.GetSelectedItemNumber(), 2, "time point restored even when a phase fails")
    finally:
      widget.heartValveMeasurementSelector.setCurrentNode(None)
      slicer.app.processEvents()

  def test_widget_links_second_valve_browser(self):
    factory = NewFormatValveFactory()
    mitral = factory.createAnnotatedValve("mitral", frames=(1, 3))
    aortic = factory.createAnnotatedValve("aortic", frames=(1, 3))
    widget = self._widget()
    measurementNode = self._createMeasurementNode("MitralValve", {"ValveMitralValve": mitral.heartValveNode,
                                                                 "ValveAorticValve": aortic.heartValveNode})
    try:
      widget.heartValveMeasurementSelector.setCurrentNode(measurementNode)
      slicer.app.processEvents()
      sequenceWidget = widget.valveSequenceBrowserWidget
      self.assertEqual(sequenceWidget.valveBrowserNode.GetID(), mitral.valveBrowserNode.GetID(), "first valve drives")
      self.assertEqual([n.GetID() for n in sequenceWidget.linkedValveBrowserNodes], [aortic.valveBrowserNode.GetID()])
      scene.selectIndexValue(mitral.valveBrowserNode, factory.indexValue(1))
      slicer.app.processEvents()
      self.assertEqual(aortic.valveBrowserNode.GetSelectedItemNumber(), 0, "linked browser follows the driver")
      scene.selectIndexValue(mitral.valveBrowserNode, factory.indexValue(3))
      slicer.app.processEvents()
      self.assertEqual(aortic.valveBrowserNode.GetSelectedItemNumber(), 1)
    finally:
      widget.heartValveMeasurementSelector.setCurrentNode(None)
      slicer.app.processEvents()

  def test_phase_compare_between_two_time_points_of_one_valve(self):
    """A single valve with two annotated time points must be comparable phase-to-phase."""
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    valveModel = None
    for frame, phase in ((1, "mid-systole"), (3, "end-diastole")):
      factory.addTimePoint(valveBrowser, frame, phase=phase)
      valveModel = valveBrowser.valveModel
      contour = factory.setContour(valveBrowser, frame)
      valveModel.setValveLabels([("A", *contour[0]), ("P", *contour[6]), ("PM", *contour[3]), ("AL", *contour[9])])
    quantLogic = self._quantLogic()
    preset = quantLogic.getMeasurementPresetById("PhaseCompare")
    # The only heart valve node of the browser is its proxy; both phase slots can only reference it
    measurementNode = self._createMeasurementNode("PhaseCompare", {"ValveValve1": valveBrowser.heartValveNode,
                                                                  "ValveValve4": valveBrowser.heartValveNode})
    factory.switchTo(valveBrowser, 1)
    messages = quantLogic.computeMetrics(measurementNode)
    rows = self._tableRows(preset.metricsTable.metricTableNode)
    displacementRows = {k: v for k, v in rows.items() if "annulus displacement" in k or "point ED-MS distance" in k}
    self.assertTrue(displacementRows, f"phase compare must report MS/ED differences (messages: {messages})")
    self.assertTrue(any(float(v) > 0.5 for v in displacementRows.values() if v not in ("", "nan")),
                    f"MS and ED contours differ, so the phase comparison must not be a self-comparison: {displacementRows}")


def HeartValveLibBrowser(browserNode):
  import HeartValveLib
  return HeartValveLib.HeartValves.getValveBrowser(browserNode)
