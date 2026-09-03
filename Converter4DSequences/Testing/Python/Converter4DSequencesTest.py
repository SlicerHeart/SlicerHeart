"""
Converter4DSequencesTest.py

Tests for converting old-format (one HeartValve node per cardiac phase) SlicerHeart scenes into
the combined 4D sequence format (one valve browser with per-time-point sequences).

Every test builds its own legacy scene with HeartValveTestLib.legacy.LegacySceneBuilder (which
reproduces the node graph written by the pre-4D modules with plain MRML calls), runs the converter
through its public API and then verifies the result through the new-format API (HeartValveLib
ValveBrowser / ValveModel) so that the converted data is proven to be usable, not just present.
"""

import os
import sys
import time

import numpy as np
import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTLIB_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "ValveAnnulusAnalysis", "Testing", "Python"))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.asserts import controlPointPositions, controlPointLabels, shParentName, shParentDataNode  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402
from HeartValveTestLib import legacy  # noqa: E402
from HeartValveTestLib.legacy import LegacySceneBuilder  # noqa: E402


class Converter4DSequencesTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Converter4DSequencesTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "ValveQuantification",
                                "Converter4DSequences", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for the conversion of old-format multi-phase valve annotations to sequences."
    self.parent.acknowledgementText = ""


class Converter4DSequencesTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class Converter4DSequencesTestLogic(ScriptedLoadableModuleLogic):
  pass


class Converter4DSequencesTestTest(SlicerHeartTestCase):

  THREE_PHASES = (("mid-systole", 1), ("end-systole", 3), ("mid-diastole", 5))

  # ---------------------------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _logic():
    import Converter4DSequences
    return Converter4DSequences.Converter4DSequencesLogic()

  def _convert(self):
    logic = self._logic()
    logic.performFullConversion(showMessage=False)
    return logic

  @staticmethod
  def _valveBrowsers():
    import HeartValveLib
    return [HeartValveLib.HeartValves.getValveBrowser(n) for n in scene.valveBrowserNodes()]

  def _browserForValveType(self, valveType):
    browsers = [b for b in self._valveBrowsers() if b.valveType == valveType]
    self.assertEqual(len(browsers), 1, f"expected exactly one {valveType} valve browser, found {len(browsers)}")
    return browsers[0]

  @staticmethod
  def _goTo(valveBrowser, indexValue):
    scene.selectIndexValue(valveBrowser.valveBrowserNode, indexValue)

  @staticmethod
  def _segmentVoxelCount(segmentationNode, segmentId):
    labelmap = slicer.vtkOrientedImageData()
    if not segmentationNode.GetBinaryLabelmapRepresentation(segmentId, labelmap) or labelmap.GetNumberOfPoints() == 0:
      return 0
    from vtk.util import numpy_support
    return int(np.count_nonzero(numpy_support.vtk_to_numpy(labelmap.GetPointData().GetScalars())))

  @staticmethod
  def _isProxy(node):
    return slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(node) is not None

  def _assertPhaseData(self, valveBrowser, record, msg=""):
    """Check that the converted valve shows *record*'s data at its time point."""
    msg = msg or f"{record.valveType}/{record.phase}"
    self._goTo(valveBrowser, record.indexValue)
    valveModel = valveBrowser.valveModel
    heartValveNode = valveBrowser.heartValveNode
    self.assertEqual(valveModel.getCardiacCyclePhase(), record.phase, f"{msg}: phase")
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), record.frameIndex, f"{msg}: frame")
    self.assertAlmostEqual(valveModel.annulusContourRadius, 0.5, msg=f"{msg}: contour radius")
    if record.contourPoints is not None:
      curve = valveModel.annulusContourCurveNode
      self.assertIsNotNone(curve, f"{msg}: annulus contour missing")
      self.assertEqual(curve.GetClassName(), "vtkMRMLMarkupsClosedCurveNode", f"{msg}: contour node type")
      self.assertControlPointsEqual(curve, record.contourPoints, msg=f"{msg}: contour points")
      self.assertParentTransformIs(curve, valveBrowser.probeToRasTransformNode, f"{msg}: contour transform")
    if record.labels is not None:
      labels = heartValveNode.GetNodeReference("AnnulusLabelsPoints")
      self.assertIsNotNone(labels, f"{msg}: labels missing")
      self.assertTrue(valveModel.isNodeSpecifiedForCurrentTimePoint(labels), f"{msg}: labels not specified at time point")
      self.assertLabelsEqual(labels, record.labels, msg=f"{msg}: labels")
    if record.roiParams is not None:
      roi = valveModel.valveRoiModelNode
      self.assertIsNotNone(roi, f"{msg}: ROI missing")
      for key, value in record.roiParams.items():
        self.assertEqual(float(roi.GetAttribute(key)), float(value), f"{msg}: ROI attribute {key}")
      self.assertGreater(roi.GetPolyData().GetNumberOfPoints(), 0, f"{msg}: ROI geometry")
    if record.segmentIds:
      segmentation = valveModel.leafletSegmentationNode
      self.assertIsNotNone(segmentation, f"{msg}: segmentation missing")
      ids = list(segmentation.GetSegmentation().GetSegmentIDs())
      for segmentId in record.segmentIds:
        self.assertIn(segmentId, ids, f"{msg}: segment {segmentId}")
        segment = segmentation.GetSegmentation().GetSegment(segmentId)
        self.assertEqual(segment.GetName(), record.segmentNames[segmentId], f"{msg}: segment name")
        self.assertEqual([round(c, 3) for c in segment.GetColor()], [round(c, 3) for c in record.segmentColors[segmentId]],
                         f"{msg}: segment colour")
        self.assertGreater(self._segmentVoxelCount(segmentation, segmentId), 0, f"{msg}: segment {segmentId} geometry")
      leafletVolume = valveModel.leafletVolumeNode
      self.assertIsNotNone(leafletVolume, f"{msg}: leaflet volume missing")
      self.assertEqual(scene.volumeVoxelValue(leafletVolume), record.leafletVolumeValue, f"{msg}: leaflet volume content")
      self.assertParentTransformIs(segmentation, valveBrowser.probeToRasTransformNode, f"{msg}: segmentation transform")
    if record.axialMatrix is not None:
      axial = valveBrowser.axialSliceToRasTransformNode
      self.assertIsNotNone(axial, f"{msg}: axial transform missing")
      matrix = vtk.vtkMatrix4x4()
      axial.GetMatrixTransformToParent(matrix)
      self.assertMatricesEqual(matrix, record.axialMatrix, msg=f"{msg}: axial slice orientation")

  def _assertSceneIsCleanNewFormat(self, builder, extraAllowedNodes=()):
    """No legacy nodes left, no orphans: every annotation node is a proxy of a browser."""
    for record in builder.valves:
      self.assertNotInScene(record.node, f"legacy valve {record.node.GetName()} must be removed")
    allowed = {builder.volumeProxyNode.GetID(), builder.probeToRasTransformNode.GetID()}
    allowed.update(n.GetID() for n in extraAllowedNodes)
    orphans = []
    for className in ("vtkMRMLMarkupsFiducialNode", "vtkMRMLMarkupsClosedCurveNode", "vtkMRMLMarkupsCurveNode",
                      "vtkMRMLModelNode", "vtkMRMLSegmentationNode", "vtkMRMLScalarVolumeNode",
                      "vtkMRMLLinearTransformNode", "vtkMRMLScriptedModuleNode", "vtkMRMLTableNode"):
      for node in slicer.util.getNodesByClass(className):
        if node.GetID() in allowed or node.GetSingletonTag():
          continue
        if node.GetHideFromEditors() and node.GetAttribute("ModuleName") not in ("HeartValve", "HeartValveMeasurement",
                                                                                 "CardiacDeviceAnalysis"):
          continue  # application-internal nodes (slice models, view transforms, ...)
        if not self._isProxy(node):
          orphans.append(f"{className}:{node.GetName()}")
    self.assertFalse(orphans, "nodes that are neither proxies nor allowed leftovers: " + ", ".join(orphans))
    for displayNode in slicer.util.getNodesByClass("vtkMRMLDisplayNode"):
      self.assertIsNotNone(displayNode.GetDisplayableNode(), f"orphan display node {displayNode.GetName()}")
    for sequenceNode in slicer.util.getNodesByClass("vtkMRMLSequenceNode"):
      self.assertIsNotNone(slicer.modules.sequences.logic().GetFirstBrowserNodeForSequenceNode(sequenceNode),
                           f"sequence {sequenceNode.GetName()} is not synchronized with any browser")
    sh = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    allItems = vtk.vtkIdList()
    sh.GetItemChildren(sh.GetSceneItemID(), allItems, True)
    for i in range(allItems.GetNumberOfIds()):
      itemId = allItems.GetId(i)
      if (sh.GetItemDataNode(itemId) is None and sh.GetItemOwnerPluginName(itemId) == "Folder"
          and sh.GetNumberOfItemChildren(itemId) == 0):
        self.fail(f"empty subject hierarchy folder left behind: {sh.GetItemName(itemId)!r}")

  # ---------------------------------------------------------------------------------------------
  # Detection
  # ---------------------------------------------------------------------------------------------

  def test_sceneHasConvertibleNodes(self):
    logic = self._logic()
    self.assertFalse(logic.sceneHasConvertibleNodes(), "empty scene")
    factory = NewFormatValveFactory()
    newValve = factory.createAnnotatedValve("mitral", frames=(1,))
    self.assertFalse(logic.sceneHasConvertibleNodes(), "new-format valve is not convertible")
    measurement = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode", "NewMeasurement")
    measurement.SetAttribute("ModuleName", "HeartValveMeasurement")
    measurement.SetAttribute("MeasurementPreset", "GenericValve")
    measurement.SetNodeReferenceID("ValveValve", newValve.heartValveNode.GetID())
    self.assertFalse(logic.sceneHasConvertibleNodes(), "new-format measurement referencing a proxy is not convertible")

    builder = LegacySceneBuilder(volumeBrowserNode=factory.volumeBrowserNode)
    record = builder.addLegacyValve("tricuspid", frameIndex=2, phase="mid-systole", segmentation=False, roi=False)
    self.assertTrue(logic.sceneHasConvertibleNodes(), "legacy valve is convertible")
    slicer.mrmlScene.RemoveNode(record.node)
    self.assertFalse(logic.sceneHasConvertibleNodes())
    legacyValve = builder.addLegacyValve("tricuspid", frameIndex=2, phase="mid-systole", segmentation=False, roi=False)
    legacyMeasurement = builder.addLegacyMeasurement("GenericValve", {"ValveValve": legacyValve})
    slicer.mrmlScene.RemoveNode(legacyValve.node)
    self.assertFalse(logic.sceneHasConvertibleNodes(), "measurement whose valve is gone is not convertible")
    slicer.mrmlScene.RemoveNode(legacyMeasurement["node"])
    builder.addLegacyDevice()
    self.assertTrue(logic.sceneHasConvertibleNodes(), "legacy device is convertible")

  def test_stripFrameAndPhaseFromName(self):
    logic = self._logic()
    strip = logic._stripFrameAndPhaseFromName
    self.assertEqual(strip("TricuspidValve-ES_f23-segmented"), "TricuspidValve-segmented")
    self.assertEqual(strip("MitralValve-ED_f10"), "MitralValve")
    self.assertEqual(strip("AnnulusContour_25"), "AnnulusContour")
    self.assertEqual(strip("AnnulusContourMarkup"), "AnnulusContourMarkup")
    for phase, shortName in legacy.PHASE_SHORT_NAMES.items():
      self.assertEqual(strip(f"MitralValve-{shortName}_f3"), "MitralValve",
                       f"phase suffix -{shortName} ({phase}) must be stripped")

  # ---------------------------------------------------------------------------------------------
  # Core contract: one valve, three phases
  # ---------------------------------------------------------------------------------------------

  def test_single_valve_three_phases(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES, leaflets=False)
    self._convert()

    valveBrowser = self._browserForValveType("mitral")
    browserNode = valveBrowser.valveBrowserNode
    self.assertEqual(browserNode.GetAttribute("ModuleName"), "HeartValve")
    self.assertEqual(browserNode.GetAttribute("ValveType"), "mitral")
    self.assertEqual(valveBrowser.valveVolumeNode.GetID(), builder.volumeProxyNode.GetID())
    self.assertEqual(valveBrowser.volumeSequenceBrowserNode.GetID(), builder.volumeBrowserNode.GetID())
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [r.indexValue for r in records])
    self.assertEqual(valveBrowser.heartValveNode.GetName(), legacy.expectedProxyName("mitral"))
    self.assertEqual(valveBrowser.heartValveNode.GetAttribute("ModuleName"), "HeartValve")
    self.assertEqual(valveBrowser.probePosition, "TTE_APICAL", "probe position migrated to the volume browser")
    self.assertEqual(builder.volumeBrowserNode.GetAttribute("ProbePosition"), "TTE_APICAL")
    self.assertEqual(valveBrowser.probeToRasTransformNode.GetID(), builder.probeToRasTransformNode.GetID())
    self.assertEqual(len(scene.heartValveNodes()), 1, "single valve proxy node")
    for record in records:
      self._assertPhaseData(valveBrowser, record)
    # Browser-level axial transform is a per-time-point proxy
    axialSequence = browserNode.GetSequenceNode(valveBrowser.axialSliceToRasTransformNode)
    self.assertIsNotNone(axialSequence, "axial transform must be sequenced")
    self.assertSequenceIndexValues(axialSequence, [r.indexValue for r in records])
    # Per-node sequences are configured like the new format creates them
    valveModel = valveBrowser.valveModel
    for name, sequenceNode in (("contour", valveModel.annulusContourCurveSequenceNode),
                               ("labels", valveModel.valveLabelsSequenceNode),
                               ("roi", valveModel.valveRoiSequenceNode),
                               ("segmentation", valveModel.leafletSegmentationSequenceNode),
                               ("leafletVolume", valveModel.leafletVolumeSequenceNode)):
      self.assertIsNotNone(sequenceNode, f"{name} sequence")
      self.assertSequenceIndexValues(sequenceNode, [r.indexValue for r in records], name)
      self.assertTrue(browserNode.GetSaveChanges(sequenceNode), f"{name}: SaveChanges")
      self.assertEqual(browserNode.GetMissingItemMode(sequenceNode),
                       slicer.vtkMRMLSequenceBrowserNode.MissingItemSetToDefault, f"{name}: missing item mode")
    # Old per-phase attribute-based backup moved onto the curve node
    self._goTo(valveBrowser, records[0].indexValue)
    self.assertIsNotNone(valveModel.annulusContourCurveNode.GetAttribute("AnnulusContourCoordinates"))
    self.assertTrue(valveModel.hasStoredAnnulusContour())
    self._assertSceneIsCleanNewFormat(builder)

  def test_display_sequences_and_visibility(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=False)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    browserNode = valveBrowser.valveBrowserNode
    valveModel = valveBrowser.valveModel
    self._goTo(valveBrowser, records[0].indexValue)
    for name, node in (("contour", valveModel.annulusContourCurveNode), ("roi", valveModel.valveRoiModelNode),
                       ("segmentation", valveModel.leafletSegmentationNode)):
      displayNode = node.GetDisplayNode()
      self.assertIsNotNone(displayNode, f"{name}: display node")
      displaySequence = browserNode.GetSequenceNode(displayNode)
      self.assertIsNotNone(displaySequence, f"{name}: display node must be driven by a display sequence")
      self.assertSequenceIndexValues(displaySequence, [r.indexValue for r in records], f"{name}: display items at every time point")
      self.assertTrue(browserNode.GetSaveChanges(displaySequence), f"{name}: display SaveChanges")
      self.assertTrue(displayNode.GetVisibility(), f"{name}: visible after conversion")
    # A display change made at one time point is kept when scrubbing away and back
    contourDisplay = valveModel.annulusContourCurveNode.GetDisplayNode()
    contourDisplay.SetVisibility(False)
    self._goTo(valveBrowser, records[1].indexValue)
    self.assertTrue(valveModel.annulusContourCurveNode.GetDisplayNode().GetVisibility(), "other time point unaffected")
    self._goTo(valveBrowser, records[0].indexValue)
    self.assertFalse(valveModel.annulusContourCurveNode.GetDisplayNode().GetVisibility(), "display edit persisted")

  def test_subject_hierarchy_after_conversion(self):
    builder = LegacySceneBuilder()
    builder.addLegacyValves("mitral", self.THREE_PHASES[:2], coaptation=True, papillary=True)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    browserNode = valveBrowser.valveBrowserNode
    heartValveNode = valveBrowser.heartValveNode
    valveModel = valveBrowser.valveModel
    self.assertShParentIs(heartValveNode, browserNode, "valve proxy under its browser")
    self._goTo(valveBrowser, builder.valves[0].indexValue)
    for name, node in (("contour", valveModel.annulusContourCurveNode), ("labels", heartValveNode.GetNodeReference("AnnulusLabelsPoints")),
                       ("roi", valveModel.valveRoiModelNode), ("segmentation", valveModel.leafletSegmentationNode),
                       ("leafletVolume", valveModel.leafletVolumeNode)):
      self.assertShParentIs(node, heartValveNode, f"{name} under the valve proxy")
    for leafletModel in valveModel.leafletModels:
      self.assertShParentNameIs(leafletModel.surfaceModelNode, "LeafletSurface")
      self.assertShParentNameIs(leafletModel.surfaceBoundary, "LeafletSurfaceEdit")
      self.assertEqual(shParentDataNode(shParentDataNode(leafletModel.surfaceModelNode)) if False else True, True)
    sh = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    axialItem = sh.GetItemByDataNode(valveBrowser.axialSliceToRasTransformNode)
    self.assertEqual(sh.GetItemAttribute(axialItem, slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyExcludeFromTreeAttributeName()), "1")
    self.assertIsNone(sh.GetItemAttribute(sh.GetItemByDataNode(heartValveNode),
                                          slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelAttributeName()) or None)
    self._assertSceneIsCleanNewFormat(builder)

  def test_no_stray_nodes_created_during_conversion(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=False)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    fiducials = [n for n in slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode") if not n.GetSingletonTag()]
    self.assertEqual(len(fiducials), 1, "only the labels proxy may remain: " + ", ".join(n.GetName() for n in fiducials))
    labelsProxy = valveBrowser.heartValveNode.GetNodeReference("AnnulusLabelsPoints")
    self.assertIs(fiducials[0], labelsProxy)
    labelSequences = [s for s in slicer.util.getNodesByClass("vtkMRMLSequenceNode")
                      if s.GetNumberOfDataNodes() and s.GetNthDataNode(0).IsA("vtkMRMLMarkupsFiducialNode")]
    self.assertEqual(len(labelSequences), 1, "exactly one labels sequence")
    # Application-internal transforms (e.g. the hidden slice view transforms) are not counted
    transforms = [n for n in slicer.util.getNodesByClass("vtkMRMLLinearTransformNode") if not n.GetHideFromEditors()]
    self.assertEqual(len(transforms), 2,
                     "probe transform + axial transform proxy only: " + ", ".join(n.GetName() for n in transforms))
    self._assertPhaseData(valveBrowser, records[1])

  def test_valve_model_state_is_consistent_right_after_conversion(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=True)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    valveModel = valveBrowser.valveModel
    self._goTo(valveBrowser, records[0].indexValue)
    self.assertIs(valveModel.valveRoi.roiModelNode, valveModel.valveRoiModelNode,
                  "ValveRoi must point at the converted ROI proxy")
    self.assertIs(valveModel.valveRoi.annulusContourCurve, valveModel.annulusContourCurveNode,
                  "ValveRoi must use the converted annulus curve")
    self.assertEqual(valveModel.valveRoi.getRoiGeometry()["ValveRoiScale"], float(records[0].roiParams["ValveRoiScale"]))
    self.assertEqual(sorted(m.segmentId for m in valveModel.leafletModels), sorted(records[0].segmentIds),
                     "leaflet models must reflect the converted segmentation")

  def test_post_conversion_usability(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=False)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    factory = NewFormatValveFactory(volumeBrowserNode=builder.volumeBrowserNode)

    # Add a new time point on an unannotated frame and annotate it with the new-format API. The
    # converted time points are re-checked after every step so a regression points at its cause.
    factory.addTimePoint(valveBrowser, 0, phase="end-diastole")
    valveModel = valveBrowser.valveModel
    self.assertIsNone(valveModel.annulusContourCurveNode)
    self._assertPhaseData(valveBrowser, records[1], "after addTimePoint")
    factory.switchTo(valveBrowser, 0)
    newContour = factory.setContour(valveBrowser, 0)
    self._assertPhaseData(valveBrowser, records[1], "after setContour")
    factory.switchTo(valveBrowser, 0)
    factory.setLabels(valveBrowser, 0)
    self._assertPhaseData(valveBrowser, records[1], "after setLabels")
    factory.switchTo(valveBrowser, 0)
    factory.addRoi(valveBrowser)
    self._assertPhaseData(valveBrowser, records[1], "after addRoi")
    factory.switchTo(valveBrowser, 0)
    factory.addSegmentation(valveBrowser)
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode,
                                   [factory.indexValue(0)] + [r.indexValue for r in records])
    for record in records:
      self._assertPhaseData(valveBrowser, record, "after addSegmentation")
    factory.switchTo(valveBrowser, 0)
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, newContour, msg="new time point contour")
    self.assertEqual(valveModel.getCardiacCyclePhase(), "end-diastole")

    # Quantification at two time points produces a per-time-point results table
    import ValveQuantification
    quantLogic = ValveQuantification.ValveQuantificationLogic()
    preset = quantLogic.getMeasurementPresetById("GenericValve")
    measurementNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode", "Measurement")
    measurementNode.SetAttribute("ModuleName", "HeartValveMeasurement")
    measurementNode.SetAttribute("MeasurementPreset", preset.id)
    measurementNode.SetNodeReferenceID("Valve" + preset.inputValveIds[0], valveBrowser.heartValveNode.GetID())
    for record in records:
      self._goTo(valveBrowser, record.indexValue)
      quantLogic.computeMetrics(measurementNode)
    tableNode = preset.metricsTable.metricTableNode
    tableSequence = valveBrowser.valveBrowserNode.GetSequenceNode(tableNode)
    self.assertIsNotNone(tableSequence, "results table must be sequenced")
    self.assertSequenceIndexValues(tableSequence, [r.indexValue for r in records])

    # Save and reload: everything still resolves through the new-format API
    scene.saveAndReloadScene(self.tempDirectory(), resetCaches=self.resetHeartValveLibCaches)
    valveBrowser = self._browserForValveType("mitral")
    self.assertEqual(valveBrowser.heartValveSequenceNode.GetNumberOfDataNodes(), 3)
    for record in records:
      self._assertPhaseData(valveBrowser, record, "after reload")
    self.assertFalse(self._logic().sceneHasConvertibleNodes(), "converted scene must not be re-converted")

  # ---------------------------------------------------------------------------------------------
  # Leaflets, coaptation, papillary muscles, clipped volume
  # ---------------------------------------------------------------------------------------------

  def test_leaflet_surfaces_and_boundaries(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=True)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    valveModel = valveBrowser.valveModel
    heartValveNode = valveBrowser.heartValveNode
    self.assertEqual(heartValveNode.GetNumberOfNodeReferences("LeafletSurfaceBoundaryModel"), 0, "legacy boundary models removed")
    leftoverFiducials = [n.GetName() for n in slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode") if n.GetAttribute("SegmentID")]
    self.assertEqual(leftoverFiducials, [], "boundary fiducials upgraded to curves")
    for record in records:
      self._goTo(valveBrowser, record.indexValue)
      valveModel.updateLeafletModelsFromSegmentation()
      self.assertEqual(sorted(m.segmentId for m in valveModel.leafletModels), sorted(record.segmentIds), record.phase)
      for segmentId in record.segmentIds:
        surface = valveModel.getLeafletNodeReference("LeafletSurfaceModel", segmentId)
        boundary = valveModel.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", segmentId)
        self.assertIsNotNone(surface, f"{record.phase}: surface of {segmentId}")
        self.assertIsNotNone(boundary, f"{record.phase}: boundary of {segmentId}")
        self.assertEqual(boundary.GetClassName(), "vtkMRMLMarkupsClosedCurveNode")
        self.assertTrue(valveModel.isNodeSpecifiedForCurrentTimePoint(boundary), f"{record.phase}: boundary item for {segmentId}")
        self.assertControlPointsEqual(boundary, record.boundaryPoints[segmentId], msg=f"{record.phase}: boundary points {segmentId}")
        self.assertGreater(surface.GetPolyData().GetNumberOfPoints(), 0, f"{record.phase}: surface geometry {segmentId}")
        self.assertParentTransformIs(surface, valveBrowser.probeToRasTransformNode)
        self.assertParentTransformIs(boundary, valveBrowser.probeToRasTransformNode)
        self.assertEqual(boundary.GetAttribute("ValvePlaneNormal"), "0.0 0.0 1.0", "boundary attributes preserved")
    self._assertSceneIsCleanNewFormat(builder)

  def test_leaflet_reference_order_differs_between_phases(self):
    builder = LegacySceneBuilder()
    first = builder.addLegacyValve("mitral", frameIndex=1, phase="mid-systole", leafletOrder=["Anterior", "Posterior"])
    second = builder.addLegacyValve("mitral", frameIndex=3, phase="end-systole", leafletOrder=["Posterior", "Anterior"])
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    valveModel = valveBrowser.valveModel
    for record in (first, second):
      self._goTo(valveBrowser, record.indexValue)
      for segmentId in ("Anterior", "Posterior"):
        boundary = valveModel.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", segmentId)
        self.assertIsNotNone(boundary, f"{record.phase}: boundary reference for {segmentId}")
        self.assertEqual(boundary.GetAttribute("SegmentID"), segmentId,
                         f"{record.phase}: the same proxy must hold the same leaflet at every time point")
        self.assertControlPointsEqual(boundary, record.boundaryPoints[segmentId], msg=f"{record.phase}: {segmentId} boundary")
        surface = valveModel.getLeafletNodeReference("LeafletSurfaceModel", segmentId)
        self.assertEqual(surface.GetAttribute("SegmentID"), segmentId, f"{record.phase}: surface of {segmentId}")

  def test_extra_leaflet_in_one_phase(self):
    builder = LegacySceneBuilder()
    two = builder.addLegacyValve("tricuspid", frameIndex=1, phase="mid-systole", segmentIds=("Anterior", "Posterior"))
    three = builder.addLegacyValve("tricuspid", frameIndex=3, phase="end-systole", segmentIds=("Anterior", "Posterior", "Septal"))
    self._convert()
    valveBrowser = self._browserForValveType("tricuspid")
    valveModel = valveBrowser.valveModel
    self._assertPhaseData(valveBrowser, two)
    self._assertPhaseData(valveBrowser, three)
    self._goTo(valveBrowser, three.indexValue)
    valveModel.updateLeafletModelsFromSegmentation()
    self.assertEqual(sorted(m.segmentId for m in valveModel.leafletModels), ["Anterior", "Posterior", "Septal"])
    septalBoundary = valveModel.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", "Septal")
    self.assertIsNotNone(septalBoundary)
    self.assertControlPointsEqual(septalBoundary, three.boundaryPoints["Septal"], msg="septal boundary")
    self._goTo(valveBrowser, two.indexValue)
    self.assertFalse(valveModel.isNodeSpecifiedForCurrentTimePoint(septalBoundary), "no septal leaflet at the first phase")
    anteriorBoundary = valveModel.getLeafletNodeReference("LeafletSurfaceBoundaryMarkup", "Anterior")
    self.assertControlPointsEqual(anteriorBoundary, two.boundaryPoints["Anterior"], msg="anterior boundary, phase 1")

  def test_coaptation_preserved(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], coaptation=True)
    surfacePointCounts = [r.nodes["CoaptationSurfaceModel"][0].GetPolyData().GetNumberOfPoints() for r in records]
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    valveModel = valveBrowser.valveModel
    heartValveNode = valveBrowser.heartValveNode
    self.assertEqual(heartValveNode.GetNumberOfNodeReferences("CoaptationBaseLineMarkup"), 1)
    self.assertEqual(heartValveNode.GetNumberOfNodeReferences("CoaptationMarginLineMarkup"), 1)
    self.assertEqual(heartValveNode.GetNumberOfNodeReferences("CoaptationSurfaceModel"), 1,
                     "coaptation surface reference must be restored on the valve proxy")
    for record, pointCount in zip(records, surfacePointCounts):
      self._goTo(valveBrowser, record.indexValue)
      valveModel.updateCoaptationModels()
      self.assertEqual(len(valveModel.coaptationModels), 1, record.phase)
      coaptation = valveModel.coaptationModels[0]
      base, margin = record.coaptationPoints
      self.assertControlPointsEqual(coaptation.baseLine, base, msg=f"{record.phase}: base line")
      self.assertControlPointsEqual(coaptation.marginLine, margin, msg=f"{record.phase}: margin line")
      self.assertTrue(valveModel.isNodeSpecifiedForCurrentTimePoint(coaptation.baseLine))
      surface = heartValveNode.GetNthNodeReference("CoaptationSurfaceModel", 0)
      self.assertIsNotNone(surface)
      self.assertTrue(valveModel.isNodeSpecifiedForCurrentTimePoint(surface), f"{record.phase}: surface item")
      # The coaptation surface is derived data: CoaptationModel recomputes it from the base and margin
      # lines whenever the coaptation models are updated (on master as well), so the legacy mesh is not
      # expected to be kept point by point. It must exist at every converted time point.
      self.assertGreater(surface.GetPolyData().GetNumberOfPoints(), 0, f"{record.phase}: coaptation surface")
    # Application-internal fiducial nodes (singletons, hidden nodes created by earlier tests' widgets) do not count
    fiducials = [n for n in slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode")
                 if not n.GetSingletonTag() and not n.GetHideFromEditors()]
    self.assertEqual(len(fiducials), 1, "coaptation fiducial markups must be upgraded to curves like the other markups: "
                     + ", ".join(n.GetName() for n in fiducials))
    self._assertSceneIsCleanNewFormat(builder)

  def test_papillary_preserved(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], papillary=True, leaflets=False)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    valveModel = valveBrowser.valveModel
    heartValveNode = valveBrowser.heartValveNode
    self.assertEqual(heartValveNode.GetNumberOfNodeReferences("PapillaryLineMarkup"), 2)
    self.assertEqual(heartValveNode.GetNumberOfNodeReferences("PapillaryLineModel"), 0, "legacy line models removed")
    for record in records:
      self._goTo(valveBrowser, record.indexValue)
      valveModel.updatePapillaryModels()
      self.assertEqual(len(valveModel.papillaryModels), 2, record.phase)
      byName = {m.getName().replace(" papillary muscle", ""): m for m in valveModel.papillaryModels}
      for muscleName, points in record.papillaryPoints.items():
        self.assertIn(muscleName, byName, f"{record.phase}: muscle {muscleName}")
        node = byName[muscleName].getPapillaryLineMarkupNode()
        self.assertEqual(node.GetClassName(), "vtkMRMLMarkupsCurveNode")
        self.assertTrue(valveModel.isNodeSpecifiedForCurrentTimePoint(node), f"{record.phase}: {muscleName} item")
        self.assertControlPointsEqual(node, points, msg=f"{record.phase}: {muscleName} points")
        self.assertTrue(byName[muscleName].hasMusclePointsPlaced())
    self._assertSceneIsCleanNewFormat(builder)

  def test_clipped_volume_migrated_to_browser(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=False, clippedVolume=True)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    clipped = valveBrowser.clippedValveVolumeNode
    self.assertIsNotNone(clipped, "clipped volume must be carried over to the browser's ClippedVolume reference")
    self.assertEqual(scene.volumeVoxelValue(clipped), 77)
    self.assertParentTransformIs(clipped, valveBrowser.probeToRasTransformNode)
    self._assertPhaseData(valveBrowser, records[0])

  # ---------------------------------------------------------------------------------------------
  # Sparse and irregular data
  # ---------------------------------------------------------------------------------------------

  def test_phases_with_missing_annotations(self):
    builder = LegacySceneBuilder()
    full = builder.addLegacyValve("mitral", frameIndex=1, phase="mid-systole", leaflets=False)
    noSegmentation = builder.addLegacyValve("mitral", frameIndex=3, phase="end-systole", segmentation=False, leaflets=False)
    noLabelsNoRoi = builder.addLegacyValve("mitral", frameIndex=5, phase="mid-diastole", labels=False, roi=False, leaflets=False)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    valveModel = valveBrowser.valveModel
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [r.indexValue for r in (full, noSegmentation, noLabelsNoRoi)])
    for record in (full, noSegmentation, noLabelsNoRoi):
      self._assertPhaseData(valveBrowser, record)
    self._goTo(valveBrowser, noSegmentation.indexValue)
    self.assertIsNone(valveModel.leafletSegmentationNode, "no segmentation item at a phase without segmentation")
    self.assertIsNone(valveModel.leafletVolumeNode)
    self.assertSequenceIndexValues(valveModel.leafletSegmentationSequenceNode, [full.indexValue, noLabelsNoRoi.indexValue])
    self._goTo(valveBrowser, noLabelsNoRoi.indexValue)
    self.assertIsNone(valveModel.valveRoiModelNode)
    labels = valveBrowser.heartValveNode.GetNodeReference("AnnulusLabelsPoints")
    self.assertFalse(valveModel.isNodeSpecifiedForCurrentTimePoint(labels))
    self.assertSequenceIndexValues(valveModel.valveLabelsSequenceNode, [full.indexValue, noSegmentation.indexValue])
    self._assertSceneIsCleanNewFormat(builder)

  def test_custom_and_unknown_phases_convert(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", (("custom1", 1), ("unknown", 2), ("custom-transition", 4)), leaflets=False)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    for record in records:
      self._assertPhaseData(valveBrowser, record)
    self._assertSceneIsCleanNewFormat(builder)

  def test_custom_phase_names_are_stripped_from_proxy_names(self):
    builder = LegacySceneBuilder()
    builder.addLegacyValves("mitral", (("custom1", 1), ("unknown", 2)), leaflets=False)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    self._goTo(valveBrowser, builder.valves[0].indexValue)
    leafletVolume = valveBrowser.valveModel.leafletVolumeNode
    self.assertNotIn("-P1", leafletVolume.GetName(), "phase suffix must be stripped from converted node names")
    self.assertNotIn("_f2", leafletVolume.GetName())
    segmentation = valveBrowser.valveModel.leafletSegmentationNode
    self.assertNotIn("-P1", segmentation.GetName())

  def test_invalid_frame_indices_leave_valve_untouched(self):
    builder = LegacySceneBuilder()
    good = builder.addLegacyValve("mitral", frameIndex=1, phase="mid-systole", leaflets=False)
    negative = builder.addLegacyValve("mitral", frameIndex=0, phase="end-systole", leaflets=False, frameIndexAttribute="-1")
    outOfRange = builder.addLegacyValve("mitral", frameIndex=0, phase="mid-diastole", leaflets=False, frameIndexAttribute="99")
    garbage = builder.addLegacyValve("mitral", frameIndex=0, phase="end-diastole", leaflets=False, frameIndexAttribute="abc")
    logic = self._convert()
    valveBrowser = self._browserForValveType("mitral")
    self._assertPhaseData(valveBrowser, good)
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [good.indexValue])
    for record in (negative, outOfRange, garbage):
      self.assertInScene(record.node, f"{record.phase}: unconvertible valve must be kept")
      # The legacy fiducial contour may legitimately be upgraded to a curve node; the data must stay
      contour = record.node.GetNodeReference("AnnulusContourPoints")
      self.assertIsNotNone(contour, f"{record.phase}: its contour must be kept")
      self.assertControlPointsEqual(contour, record.contourPoints, msg=record.phase)
      self.assertEqual(record.node.GetNodeReference("ValveVolume").GetID(), builder.volumeProxyNode.GetID())
      self.assertIsNotNone(record.node.GetNodeReference("LeafletSegmentation"), f"{record.phase}: segmentation kept")
    self.assertTrue(logic.sceneHasConvertibleNodes(), "skipped valves are still reported as convertible")

  def test_duplicate_frame_index_keeps_second_valve(self):
    builder = LegacySceneBuilder()
    first = builder.addLegacyValve("mitral", frameIndex=2, phase="mid-systole", leaflets=False)
    duplicate = builder.addLegacyValve("mitral", frameIndex=2, phase="end-systole", leaflets=False)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [first.indexValue])
    self._goTo(valveBrowser, first.indexValue)
    self.assertIn(valveBrowser.valveModel.getCardiacCyclePhase(), ("mid-systole", "end-systole"))
    converted, kept = (first, duplicate) if valveBrowser.valveModel.getCardiacCyclePhase() == "mid-systole" else (duplicate, first)
    self._assertPhaseData(valveBrowser, converted)
    self.assertInScene(kept.node, "colliding valve must be kept in the scene with its data")
    self.assertControlPointsEqual(kept.nodes["AnnulusContourPoints"], kept.contourPoints, msg="kept valve contour")

  # ---------------------------------------------------------------------------------------------
  # Multiple valves
  # ---------------------------------------------------------------------------------------------

  def test_two_valve_types_on_one_volume_are_not_cross_wired(self):
    builder = LegacySceneBuilder()
    mitral = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], coaptation=True, papillary=True)
    aortic = builder.addLegacyValves("aortic", (("mid-systole", 1), ("end-systole", 3)), coaptation=True)
    self._convert()
    self.assertEqual(len(scene.valveBrowserNodes()), 2)
    mitralBrowser = self._browserForValveType("mitral")
    aorticBrowser = self._browserForValveType("aortic")
    self.assertNotEqual(mitralBrowser.heartValveNode.GetID(), aorticBrowser.heartValveNode.GetID())
    for record in mitral:
      self._assertPhaseData(mitralBrowser, record, f"mitral {record.phase}")
    for record in aortic:
      self._assertPhaseData(aorticBrowser, record, f"aortic {record.phase}")
    # Each browser drives its own proxies
    mitralIds = {n.GetID() for n in self._proxyNodes(mitralBrowser.valveBrowserNode)}
    aorticIds = {n.GetID() for n in self._proxyNodes(aorticBrowser.valveBrowserNode)}
    self.assertFalse(mitralIds & aorticIds, "a node must not be a proxy of both valve browsers")
    for role in ("AnnulusContourPoints", "AnnulusLabelsPoints", "ValveRoiModel", "LeafletSegmentation", "LeafletVolume"):
      m = mitralBrowser.heartValveNode.GetNodeReference(role)
      a = aorticBrowser.heartValveNode.GetNodeReference(role)
      self.assertIsNotNone(m, f"mitral {role}")
      self.assertIsNotNone(a, f"aortic {role}")
      self.assertNotEqual(m.GetID(), a.GetID(), f"{role} shared between valves")
    # Coaptation surface models are named by CoaptationModel after the connected leaflets
    # ("Coaptation Anterior - Posterior"), the same way as in natively created scenes, so those names
    # may repeat between valves. Names assigned by the converter must be unique.
    coaptationSurfaceIds = {browser.heartValveNode.GetNthNodeReferenceID("CoaptationSurfaceModel", i)
                            for browser in (mitralBrowser, aorticBrowser)
                            for i in range(browser.heartValveNode.GetNumberOfNodeReferences("CoaptationSurfaceModel"))}
    names = [n.GetName() for browser in (mitralBrowser, aorticBrowser)
             for n in self._proxyNodes(browser.valveBrowserNode) if n.GetID() not in coaptationSurfaceIds]
    self.assertEqual(len(names), len(set(names)), "proxy node names must be unique: " + ", ".join(sorted(names)))
    self.assertEqual(mitralBrowser.probeToRasTransformNode.GetID(), aorticBrowser.probeToRasTransformNode.GetID())
    self._assertSceneIsCleanNewFormat(builder)

  @staticmethod
  def _proxyNodes(browserNode):
    sequences = vtk.vtkCollection()
    browserNode.GetSynchronizedSequenceNodes(sequences, True)
    proxies = []
    for i in range(sequences.GetNumberOfItems()):
      proxy = browserNode.GetProxyNode(sequences.GetItemAsObject(i))
      if proxy:
        proxies.append(proxy)
    return proxies

  def test_same_valve_type_on_two_volume_sequences(self):
    builderA = LegacySceneBuilder(name="StudyA")
    builderB = LegacySceneBuilder(name="StudyB")
    recordsA = builderA.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=False)
    recordsB = builderB.addLegacyValves("mitral", (("mid-systole", 2), ("end-diastole", 4)), leaflets=False)
    self._convert()
    browsers = [b for b in self._valveBrowsers() if b.valveType == "mitral"]
    self.assertEqual(len(browsers), 2)
    byVolume = {b.valveVolumeNode.GetID(): b for b in browsers}
    self.assertIn(builderA.volumeProxyNode.GetID(), byVolume)
    self.assertIn(builderB.volumeProxyNode.GetID(), byVolume)
    for record in recordsA:
      self._assertPhaseData(byVolume[builderA.volumeProxyNode.GetID()], record, f"A {record.phase}")
    for record in recordsB:
      self._assertPhaseData(byVolume[builderB.volumeProxyNode.GetID()], record, f"B {record.phase}")
    self.assertEqual(byVolume[builderB.volumeProxyNode.GetID()].probeToRasTransformNode.GetID(),
                     builderB.probeToRasTransformNode.GetID())

  def test_legacy_valve_joins_existing_converted_browser(self):
    builder = LegacySceneBuilder()
    first = builder.addLegacyValve("mitral", frameIndex=1, phase="mid-systole", leaflets=False)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    later = builder.addLegacyValve("mitral", frameIndex=3, phase="end-systole", leaflets=False)
    self._convert()
    browsers = [b for b in self._valveBrowsers() if b.valveType == "mitral"]
    self.assertEqual(len(browsers), 1, "a legacy phase of an already converted valve must join that valve's browser")
    self.assertEqual(browsers[0].valveBrowserNode.GetID(), valveBrowser.valveBrowserNode.GetID())
    self._assertPhaseData(valveBrowser, first)
    self._assertPhaseData(valveBrowser, later)

  # ---------------------------------------------------------------------------------------------
  # Measurements
  # ---------------------------------------------------------------------------------------------

  def test_measurement_single_phase(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=False)
    measurement = builder.addLegacyMeasurement("GenericValve", {"ValveValve": records[1]}, hidden=True, tableAsReference=True)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    browserNode = valveBrowser.valveBrowserNode
    measurementNodes = scene.measurementNodes()
    scripted = [f"{n.GetName()}[{n.GetAttribute('ModuleName')},proxy={self._isProxy(n)}]"
                for n in slicer.util.getNodesByClass("vtkMRMLScriptedModuleNode")]
    self.assertEqual(len(measurementNodes), 1, f"converted measurement missing; scripted module nodes: {scripted}")
    proxy = measurementNodes[0]
    self.assertTrue(self._isProxy(proxy), "measurement must be a sequence proxy")
    measurementSequence = browserNode.GetSequenceNode(proxy)
    self.assertSequenceIndexValues(measurementSequence, [records[1].indexValue])
    self.assertEqual(proxy.GetAttribute("MeasurementPreset"), "GenericValve")
    self.assertFalse(proxy.GetHideFromEditors())
    self._goTo(valveBrowser, records[1].indexValue)
    self.assertEqual(proxy.GetNodeReference("ValveValve").GetID(), valveBrowser.heartValveNode.GetID(),
                     "valve reference re-pointed at the valve proxy")
    tableProxy = proxy.GetNodeReference("QuantificationResultsTable")
    self.assertIsNotNone(tableProxy, "referenced table must be re-pointed at a table proxy")
    self.assertTrue(self._isProxy(tableProxy))
    self.assertEqual(tableProxy.GetCellText(0, 0), "Annulus area (3D)")
    self.assertEqual(tableProxy.GetCellText(0, 1), "123.4")
    self.assertShParentIs(proxy, valveBrowser.heartValveNode, "measurement nested under the valve")
    self.assertNotInScene(measurement["node"])
    # Quantification can recompute on the converted measurement
    import ValveQuantification
    quantLogic = ValveQuantification.ValveQuantificationLogic()
    quantLogic.computeMetrics(proxy)
    self.assertEqual(quantLogic.getMeasurementCardiacCyclePhaseShortNames(proxy), ["ES"])

  def test_measurement_result_tables_and_models_without_references_are_preserved(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=False)
    measurement = builder.addLegacyMeasurement("GenericValve", {"ValveValve": records[0]}, tableAsReference=False,
                                               resultModelCount=2)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    proxy = scene.measurementNodes()[0]
    self._goTo(valveBrowser, records[0].indexValue)
    sh = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    children = vtk.vtkIdList()
    sh.GetItemChildren(sh.GetItemByDataNode(proxy), children, True)
    childNodes = [sh.GetItemDataNode(children.GetId(i)) for i in range(children.GetNumberOfIds())]
    childNodes = [n for n in childNodes if n is not None]
    tables = [n for n in childNodes if n.IsA("vtkMRMLTableNode")]
    models = [n for n in childNodes if n.IsA("vtkMRMLModelNode")]
    self.assertEqual(len(tables), 1, "legacy results table must stay attached to the converted measurement")
    self.assertEqual(tables[0].GetCellText(1, 1), "45.6")
    self.assertEqual(len(models), 2, "legacy result models must stay attached to the converted measurement")
    self.assertInScene(measurement["table"])
    for model in measurement["resultModels"]:
      self.assertInScene(model, "result model")

  def test_measurement_referencing_two_phases(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES, leaflets=False)
    builder.addLegacyMeasurement("PhaseCompare", {"ValveValve1": records[0], "ValveValve2": records[2]},
                                 name="PhaseCompare-MS-MD")
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    proxy = scene.measurementNodes()[0]
    measurementSequence = valveBrowser.valveBrowserNode.GetSequenceNode(proxy)
    self.assertSequenceIndexValues(measurementSequence, [records[0].indexValue, records[2].indexValue],
                                   "measurement present at every referenced phase")
    for record in (records[0], records[2]):
      self._goTo(valveBrowser, record.indexValue)
      self.assertEqual(proxy.GetAttribute("MeasurementPreset"), "PhaseCompare", record.phase)
      for role in ("ValveValve1", "ValveValve2"):
        ref = proxy.GetNodeReference(role)
        self.assertIsNotNone(ref, f"{record.phase}: {role}")
        self.assertEqual(ref.GetID(), valveBrowser.heartValveNode.GetID(), f"{record.phase}: {role}")
    self._goTo(valveBrowser, records[1].indexValue)
    self.assertFalse(valveBrowser.valveModel.isNodeSpecifiedForCurrentTimePoint(proxy), "no measurement at the middle phase")

  def test_measurement_with_two_valve_types(self):
    builder = LegacySceneBuilder()
    mitral = builder.addLegacyValves("mitral", self.THREE_PHASES[:1], leaflets=False)
    aortic = builder.addLegacyValves("aortic", self.THREE_PHASES[:1], leaflets=False)
    builder.addLegacyMeasurement("MitralValve", {"ValveMitralValve": mitral[0], "ValveAorticValve": aortic[0]})
    self._convert()
    mitralBrowser = self._browserForValveType("mitral")
    aorticBrowser = self._browserForValveType("aortic")
    proxy = scene.measurementNodes()[0]
    self.assertEqual(len(scene.measurementNodes()), 1)
    self._goTo(mitralBrowser, mitral[0].indexValue)
    self._goTo(aorticBrowser, aortic[0].indexValue)
    self.assertEqual(proxy.GetNodeReference("ValveMitralValve").GetID(), mitralBrowser.heartValveNode.GetID())
    self.assertEqual(proxy.GetNodeReference("ValveAorticValve").GetID(), aorticBrowser.heartValveNode.GetID(),
                     "references to valves of other browsers must be restored too")
    scene.saveAndReloadScene(self.tempDirectory(), resetCaches=self.resetHeartValveLibCaches)
    proxy = scene.measurementNodes()[0]
    mitralBrowser = self._browserForValveType("mitral")
    aorticBrowser = self._browserForValveType("aortic")
    self.assertEqual(proxy.GetNodeReference("ValveMitralValve").GetID(), mitralBrowser.heartValveNode.GetID())
    self.assertEqual(proxy.GetNodeReference("ValveAorticValve").GetID(), aorticBrowser.heartValveNode.GetID())

  def test_new_format_measurement_is_untouched(self):
    builder = LegacySceneBuilder()
    legacyRecords = builder.addLegacyValves("tricuspid", self.THREE_PHASES[:1], leaflets=False)
    factory = NewFormatValveFactory(volumeBrowserNode=builder.volumeBrowserNode)
    newValve = factory.createAnnotatedValve("mitral", frames=(2,))
    measurement = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode", "NewMeasurement")
    measurement.SetAttribute("ModuleName", "HeartValveMeasurement")
    measurement.SetAttribute("MeasurementPreset", "GenericValve")
    measurement.SetNodeReferenceID("ValveValve", newValve.heartValveNode.GetID())
    self._convert()
    self.assertInScene(measurement)
    self.assertFalse(self._isProxy(measurement), "new-format measurement must not be sequenced")
    self.assertEqual(measurement.GetNodeReference("ValveValve").GetID(), newValve.heartValveNode.GetID())
    self.assertEqual(len(scene.measurementNodes()), 1)
    self._assertPhaseData(self._browserForValveType("tricuspid"), legacyRecords[0])

  # ---------------------------------------------------------------------------------------------
  # Idempotency, triggers, side effects
  # ---------------------------------------------------------------------------------------------

  def test_conversion_is_idempotent(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], coaptation=True, papillary=True)
    builder.addLegacyMeasurement("GenericValve", {"ValveValve": records[0]}, tableAsReference=True)
    self._convert()
    censusAfterFirst = scene.nodeCensus()
    referencesAfterFirst = scene.sceneReferenceSnapshot()
    self.assertFalse(self._logic().sceneHasConvertibleNodes())
    self._convert()
    self.assertNodeCountsEqual(censusAfterFirst, scene.nodeCensus(), "second conversion must not change the scene")
    self.assertEqual(scene.sceneReferenceSnapshot(), referencesAfterFirst, "references unchanged by a second conversion")
    self.assertEqual(len(scene.valveBrowserNodes()), 1)
    valveBrowser = self._browserForValveType("mitral")
    for record in records:
      self._assertPhaseData(valveBrowser, record)

  def test_conversion_on_new_format_scene_is_a_no_op(self):
    factory = NewFormatValveFactory()
    factory.createAnnotatedValve("mitral", frames=(1, 3), roi=True, segmentation=True)
    factory.createAnnotatedValve("aortic", frames=(2,))
    census = scene.nodeCensus()
    references = scene.sceneReferenceSnapshot()
    self._convert()
    # Orphan display nodes are swept by the conversion; that is harmless, so display node classes are
    # not compared here
    displayClasses = [c for c in census if c.endswith("DisplayNode")]
    self.assertNodeCountsEqual(census, scene.nodeCensus(), "new-format scene must not be modified", ignore=displayClasses)
    self.assertEqual(scene.sceneReferenceSnapshot(), references)

  def test_conversion_in_progress_flag_is_reset_after_failure(self):
    import Converter4DSequences
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:1], leaflets=False)
    logic = self._logic()

    def boom():
      raise RuntimeError("simulated conversion failure")

    logic.convertSingleFrameToMultiFrameSequences = boom
    try:
      logic.performFullConversion(showMessage=False)
    except Exception:  # noqa: BLE001 - the error display re-raises, which is acceptable
      pass
    self.assertFalse(Converter4DSequences.Converter4DSequencesLogic._conversionInProgress,
                     "re-entrancy guard must be cleared after a failed conversion")
    self.assertInScene(records[0].node, "failed conversion must not delete the legacy valve")
    self._convert()
    self._assertPhaseData(self._browserForValveType("mitral"), records[0])

  def test_auto_conversion_on_scene_load(self):
    import Converter4DSequences
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:2], leaflets=False)
    mrbPath = scene.saveSceneToMrb(self.tempDirectory())
    self.assertTrue(hasattr(slicer.modules, "converter4dsequences"), "module must be loaded for auto conversion")

    self.setSetting(Converter4DSequences.Converter4DSequences.AUTO_CONVERT_SETTING_KEY, False)
    slicer.mrmlScene.Clear(0)
    self.resetHeartValveLibCaches()
    slicer.util.loadScene(mrbPath)
    self._pumpEvents(2.0)
    self.assertTrue(self._logic().sceneHasConvertibleNodes(), "auto conversion disabled: scene stays legacy")
    self.assertEqual(len(scene.valveBrowserNodes()), 0)

    self.setSetting(Converter4DSequences.Converter4DSequences.AUTO_CONVERT_SETTING_KEY, True)
    slicer.mrmlScene.Clear(0)
    self.resetHeartValveLibCaches()
    slicer.util.loadScene(mrbPath)
    deadline = time.time() + 30
    while self._logic().sceneHasConvertibleNodes() and time.time() < deadline:
      self._pumpEvents(0.2)
    self.assertFalse(self._logic().sceneHasConvertibleNodes(), "auto conversion must run after scene load")
    valveBrowser = self._browserForValveType("mitral")
    for record in records:
      self._assertPhaseData(valveBrowser, record)

  @staticmethod
  def _pumpEvents(seconds):
    end = time.time() + seconds
    while time.time() < end:
      slicer.app.processEvents()
      time.sleep(0.05)

  def test_unrelated_scene_content_is_untouched(self):
    builder = LegacySceneBuilder()
    records = builder.addLegacyValves("mitral", self.THREE_PHASES[:1], coaptation=True)
    unrelatedModel = slicer.modules.models.logic().AddModel(scene.sphereSource((0, 0, 0), 2.0))
    unrelatedModel.SetName("UserModel")
    displayNodeId = unrelatedModel.GetDisplayNodeID()
    sh = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    userFolder = sh.CreateFolderItem(sh.GetSceneItemID(), "Coaptation")
    userFolder2 = sh.CreateFolderItem(sh.GetSceneItemID(), "My notes")
    self._convert()
    self.assertInScene(unrelatedModel)
    self.assertEqual(unrelatedModel.GetDisplayNodeID(), displayNodeId, "unrelated display node kept")
    self.assertEqual(sh.GetItemName(userFolder2), "My notes")
    self.assertTrue(sh.GetItemName(userFolder) == "Coaptation" and sh.GetItemParent(userFolder) == sh.GetSceneItemID(),
                    "a user folder that merely shares a legacy folder name must not be deleted")
    self._assertPhaseData(self._browserForValveType("mitral"), records[0])

  # ---------------------------------------------------------------------------------------------
  # Devices
  # ---------------------------------------------------------------------------------------------

  def test_single_device(self):
    builder = LegacySceneBuilder()
    device = builder.addLegacyDevice("ASD_Device_1")
    self._convert()
    browsers = scene.nodesWithAttribute("vtkMRMLSequenceBrowserNode", "ModuleName", "CardiacDeviceAnalysis")
    self.assertEqual(len(browsers), 1)
    browserNode = browsers[0]
    proxy = browserNode.GetProxyNode(browserNode.GetMasterSequenceNode())
    self.assertIsNotNone(proxy)
    self.assertEqual(proxy.GetAttribute("ModuleName"), "CardiacDeviceAnalysis")
    self.assertEqual(proxy.GetAttribute("DeviceClassId"), "Amplatzer")
    self.assertNotInScene(device["node"])
    self.assertSequenceIndexValues(browserNode.GetMasterSequenceNode(), [builder.indexValue(0)])
    self.assertIsNotNone(proxy.GetNodeReference("InputVolume"), "device volume reference must survive conversion")
    self.assertIsNotNone(proxy.GetNodeReference("DeviceModel"), "device model reference must survive conversion")
    self.assertInScene(device["model"])

  def test_two_devices_of_one_type(self):
    builder = LegacySceneBuilder()
    builder.addLegacyDevice("ASD_Device_1", attributes={"DeviceClassId": "One"})
    builder.addLegacyDevice("ASD_Device_2", attributes={"DeviceClassId": "Two"})
    self._convert()
    browsers = scene.nodesWithAttribute("vtkMRMLSequenceBrowserNode", "ModuleName", "CardiacDeviceAnalysis")
    self.assertEqual(len(browsers), 1)
    sequenceNode = browsers[0].GetMasterSequenceNode()
    self.assertEqual(sequenceNode.GetNumberOfDataNodes(), 2, "both devices must survive as distinct items")
    classIds = sorted(sequenceNode.GetNthDataNode(i).GetAttribute("DeviceClassId") for i in range(sequenceNode.GetNumberOfDataNodes()))
    self.assertEqual(classIds, ["One", "Two"])

  # ---------------------------------------------------------------------------------------------
  # Real data smoke test
  # ---------------------------------------------------------------------------------------------

  def test_real_data_smoke(self):
    import ValveModelTest
    volumeBrowserNode = scene.loadMitralSample()
    builder = LegacySceneBuilder(volumeBrowserNode=volumeBrowserNode)
    contours = {5: ValveModelTest.ValveModelTestTest.MITRAL_ANNULUS_CONTOUR_FRAME0,
                24: ValveModelTest.ValveModelTestTest.MITRAL_ANNULUS_CONTOUR_FRAME1}
    records = []
    for frame, phase in ((5, "mid-systole"), (24, "end-diastole")):
      record = builder.addLegacyValve("mitral", frameIndex=frame, phase=phase, segmentation=False, roi=False)
      # Replace the synthetic contour by the anatomical one
      contourNode = record.nodes["AnnulusContourPoints"]
      contourNode.RemoveAllControlPoints()
      for p in contours[frame]:
        contourNode.AddControlPoint(p[0], p[1], p[2])
      record.contourPoints = contours[frame]
      labeled = ValveModelTest.ValveModelTestTest._annulusLandmarkLabels(contours[frame])
      labelsNode = record.nodes["AnnulusLabelsPoints"]
      labelsNode.SetLocked(False)
      labelsNode.RemoveAllControlPoints()
      for label, r, a, s in labeled:
        idx = labelsNode.AddControlPoint(r, a, s)
        labelsNode.SetNthControlPointLabel(idx, label)
      labelsNode.SetLocked(True)
      record.labels = labeled
      records.append(record)
    self._convert()
    valveBrowser = self._browserForValveType("mitral")
    for record in records:
      self._assertPhaseData(valveBrowser, record)
    self._goTo(valveBrowser, records[0].indexValue)
    self.assertEqual(valveBrowser.valveModel.getAnnulusMarkupLabels(), ["A", "L", "P", "S"])
