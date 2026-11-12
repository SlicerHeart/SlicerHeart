"""
HeartValveWorkflowTest.py

End-to-end test of the sequence-based heart valve workflow, with data created entirely by the code
of this repository: a valve is annotated at two time points (contour, landmarks, ROI, leaflet
segmentation, leaflet surfaces, coaptation, papillary muscles), quantified with three presets at
every time point, saved and reloaded, quantified again and finally batch exported. Every stage
consumes what the previous stage wrote, so this is where the writers and readers of the data model
meet. The per-module suites test the stages in isolation on fixture data.

``test_workflow_on_synthetic_volume`` runs on the small synthetic volume sequence of the fixtures.
``test_workflow_on_mitral_sample`` runs the same workflow on the SlicerHeart "Mitral" sample with the
anatomical annulus contours of ValveModelTest (skipped when the sample cannot be downloaded).
"""

import csv
import math
import os
import sys

import numpy as np
import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTLIB_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "ValveAnnulusAnalysis", "Testing", "Python"))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class HeartValveWorkflowTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "HeartValveWorkflowTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "ValveQuantification", "ValveBatchExport",
                                "LeafletAnalysis", "ValvePapillaryAnalysis", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "End-to-end test of the sequence-based heart valve workflow."
    self.parent.acknowledgementText = ""


class HeartValveWorkflowTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class HeartValveWorkflowTestLogic(ScriptedLoadableModuleLogic):
  pass


class HeartValveWorkflowTestTest(SlicerHeartTestCase):

  PHASES = {"mid-systole": "MS", "end-diastole": "ED"}
  SEGMENTS = NewFormatValveFactory.DEFAULT_SEGMENTS  # (segmentId, name, color, center in units of scale)
  RTOL = 1e-3

  # ---------------------------------------------------------------------------------------------
  # Fixture
  # ---------------------------------------------------------------------------------------------

  def setUp(self):
    SlicerHeartTestCase.setUp(self)
    import ValveBatchExportRules
    self.rules = ValveBatchExportRules
    self.rules.ValveBatchExportRule.setPhasesToExport([])
    self.rules.ValveBatchExportRule.setValveTypesToExport([])
    self.logs = []

  def tearDown(self):
    self.rules.ValveBatchExportRule.setPhasesToExport([])
    self.rules.ValveBatchExportRule.setValveTypesToExport([])
    # Release the leaflet surface pipelines (held by the cached ValveModel objects) before the
    # application exits: VTK objects that outlive the render windows block the exit of the test run
    slicer.mrmlScene.Clear(0)
    self.resetHeartValveLibCaches()
    # The measurement presets are shared objects that keep the valve models of the last computation
    import ValveQuantification
    for preset in ValveQuantification.ValveQuantificationLogic().measurementPresets:
      for attribute, value in list(vars(preset).items()):
        if type(value).__name__ in ("ValveModel", "ValveBrowser"):
          setattr(preset, attribute, None)
    import gc
    gc.collect()
    SlicerHeartTestCase.tearDown(self)

  # ---------------------------------------------------------------------------------------------
  # Annotation helpers (what the ValveAnnulusAnalysis, ValveSegmentation, LeafletAnalysis and
  # ValvePapillaryAnalysis modules do, through the same HeartValveLib calls)
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _frame(valveModel):
    """In-plane axes (u, v), normal n and the plane position of the annulus of the valve model."""
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    n = np.array(planeNormal) / np.linalg.norm(planeNormal)
    point0 = [0.0, 0.0, 0.0]
    valveModel.annulusContourCurveNode.GetNthControlPointPosition(0, point0)
    u = np.array(point0) - np.array(planePosition)
    u -= np.dot(u, n) * n
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return np.array(planePosition), u, v, n

  @staticmethod
  def _landmarks(contour):
    """The four landmarks the MitralValve preset needs, sampled from the contour."""
    return [("A", *contour[0]), ("AL", *contour[3]), ("P", *contour[6]), ("PM", *contour[9])]

  def _ensureTimePointInSequences(self, valveBrowser, nodes):
    """Nodes that are stored per time point need an item at the current time point before their
    proxy can be edited (the modules do this in their 'add time point' slots)."""
    browserNode = valveBrowser.valveBrowserNode
    indexValue = browserNode.GetMasterSequenceNode().GetNthIndexValue(browserNode.GetSelectedItemNumber())
    for node in nodes:
      sequenceNode = browserNode.GetSequenceNode(node) if node else None
      if sequenceNode and sequenceNode.GetItemNumberFromIndexValue(indexValue) < 0:
        valveBrowser.addCurrentTimePointToSequence(sequenceNode)

  def _addLeafletSegmentation(self, valveBrowser, scale):
    """Leaflet segmentation with one sphere per leaflet on both sides of the annulus centre (the
    ValveSegmentation module creates the segmentation, the user paints the leaflets)."""
    valveModel = valveBrowser.valveModel
    segmentationNode = valveModel.initializeLeafletSegmentation()
    self.assertIsNotNone(segmentationNode, "initializeLeafletSegmentation")
    center, u, v, n = self._frame(valveModel)
    for segmentId, name, color, offset in self.SEGMENTS:
      sphereCenter = center + scale * (offset[0] * u + offset[1] * v + offset[2] * n)
      scene.addSphereSegment(segmentationNode, segmentId, name, sphereCenter.tolist(), radius=1.2 * scale, color=color)
    valveModel.updateLeafletModelsFromSegmentation()
    return segmentationNode

  def _extractLeafletSurfaces(self, valveBrowser, scale):
    """What the 'Auto-extract all leaflet surfaces' button of LeafletAnalysis does."""
    valveModel = valveBrowser.valveModel
    valveModel.leafletSegmentationNode.CreateClosedSurfaceRepresentation()
    planePosition, planeNormal = valveModel.getAnnulusContourPlane()
    center, u, v, n = self._frame(valveModel)
    for leafletModel in valveModel.leafletModels:
      boundary = leafletModel.getSurfaceBoundaryMarkupNode()
      self._ensureTimePointInSequences(valveBrowser, [boundary, leafletModel.surfaceModelNode])
      leafletModel.autoDetectSurfaceBoundary(planePosition, planeNormal, 30)
      leafletModel.extractSurfaceByBoundary()
      leafletModel.updateSurface()
      polyData = leafletModel.surfaceModelNode.GetPolyData()
      if polyData is None or polyData.GetNumberOfCells() == 0:
        # The automatic boundary detection is made for leaflet-shaped segments; on the spherical
        # test segments it can produce no surface. Fall back to a boundary ring around the sphere,
        # which is what a user places by hand with the boundary point placement.
        offset = next(o for segmentId, _, _, o in self.SEGMENTS if segmentId == leafletModel.segmentId)
        sphereCenter = center + scale * (offset[0] * u + offset[1] * v + offset[2] * n)
        boundary.SetLocked(False)
        boundary.RemoveAllControlPoints()
        for i in range(12):
          angle = 2.0 * math.pi * i / 12
          p = sphereCenter + 1.2 * scale * (math.cos(angle) * u + math.sin(angle) * v)
          boundary.AddControlPoint(p[0], p[1], p[2])
        leafletModel.updateSurface()
        polyData = leafletModel.surfaceModelNode.GetPolyData()
      self.assertGreater(polyData.GetNumberOfCells(), 0, f"leaflet surface of {leafletModel.segmentId}")

  def _addCoaptation(self, valveBrowser, scale):
    """Coaptation base and margin lines between the two leaflets (LeafletAnalysis)."""
    valveModel = valveBrowser.valveModel
    center, u, v, n = self._frame(valveModel)
    # One coaptation surface per valve: its nodes are shared by the time points, each time point gets
    # its own item (what the LeafletAnalysis 'add coaptation time point' button does)
    coaptationModel = valveModel.addCoaptationModel(0)
    self._ensureTimePointInSequences(valveBrowser, [coaptationModel.baseLine, coaptationModel.marginLine,
                                                    coaptationModel.surfaceModelNode])
    basePoints = [center + scale * (x * v) for x in (-1.0, 0.0, 1.0)]
    marginPoints = [p - scale * n for p in basePoints]
    for markupNode, points in ((coaptationModel.baseLine, basePoints), (coaptationModel.marginLine, marginPoints)):
      markupNode.SetLocked(False)
      wasModify = markupNode.StartModify()
      markupNode.RemoveAllControlPoints()
      for p in points:
        markupNode.AddControlPoint(p[0], p[1], p[2])
      markupNode.EndModify(wasModify)
      markupNode.SetLocked(True)
    coaptationModel.updateSurface()
    self.assertGreater(coaptationModel.surfaceModelNode.GetPolyData().GetNumberOfCells(), 0, "coaptation surface")
    return coaptationModel

  def _addPapillaryMuscles(self, valveBrowser, scale):
    """Three points per papillary muscle line below the annulus (ValvePapillaryAnalysis)."""
    valveModel = valveBrowser.valveModel
    center, u, v, n = self._frame(valveModel)
    valveModel.updatePapillaryModels()
    self.assertGreater(len(valveModel.papillaryModels), 0, "papillary models for the valve type")
    for i, papillaryModel in enumerate(valveModel.papillaryModels):
      x = 3.0 if i % 2 == 0 else -3.0
      points = [center + scale * (x * u - 3.0 * n), center + scale * (0.8 * x * u - 1.5 * n), center + scale * (0.4 * x * u)]
      node = valveModel.setPapillaryLinePoints(papillaryModel, [p.tolist() for p in points])
      self.assertIsNotNone(node, "setPapillaryLinePoints")
      self.assertTrue(papillaryModel.hasMusclePointsPlaced())

  def _annotateValve(self, factory, valveType, frames, contourFor, scale, probePosition="TTE_APICAL", full=True):
    """Annotate a valve at every frame of *frames* ({frameIndex: phase}). *full* adds ROI,
    segmentation, leaflet surfaces, coaptation and papillary muscles (contour and landmarks otherwise)."""
    valveBrowser = factory.createValveBrowser(valveType, probePosition=probePosition)
    for frameIndex, phase in frames.items():
      factory.addTimePoint(valveBrowser, frameIndex, phase=phase)
      valveModel = valveBrowser.valveModel
      contour = contourFor(frameIndex)
      self.assertIsNotNone(valveModel.setAnnulusContourPoints(contour), "setAnnulusContourPoints")
      self.assertIsNotNone(valveModel.setValveLabels(self._landmarks(contour)), "setValveLabels")
      if not full:
        continue
      factory.addRoi(valveBrowser)
      self._addLeafletSegmentation(valveBrowser, scale)
      self._extractLeafletSurfaces(valveBrowser, scale)
      self._addCoaptation(valveBrowser, scale)
      self._addPapillaryMuscles(valveBrowser, scale)
    return valveBrowser

  # ---------------------------------------------------------------------------------------------
  # Quantification helpers
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _createMeasurementNode(presetId, valveRoles, name):
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

  @staticmethod
  def _measurementTables(measurementNode):
    """Results tables of a measurement node (referenced or nested in the subject hierarchy)."""
    tables = []
    roles = []
    measurementNode.GetNodeReferenceRoles(roles)
    for role in roles:
      for i in range(measurementNode.GetNumberOfNodeReferences(role)):
        node = measurementNode.GetNthNodeReference(role, i)
        if node and node.IsA("vtkMRMLTableNode") and node not in tables:
          tables.append(node)
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    item = shNode.GetItemByDataNode(measurementNode)
    if item:
      children = vtk.vtkIdList()
      shNode.GetItemChildren(item, children, True)
      for i in range(children.GetNumberOfIds()):
        node = shNode.GetItemDataNode(children.GetId(i))
        if node and node.IsA("vtkMRMLTableNode") and node not in tables:
          tables.append(node)
    return tables

  def _storedRows(self, measurementNode):
    rows = {}
    for tableNode in self._measurementTables(measurementNode):
      rows.update(self._tableRows(tableNode))
    return rows

  def _compute(self, measurementNode, valveBrowser, factory, frames):
    """Compute the preset of the measurement node at every frame. :returns: {frameIndex: rows}"""
    import ValveQuantification
    quantLogic = ValveQuantification.ValveQuantificationLogic()
    results = {}
    for frameIndex in frames:
      factory.switchTo(valveBrowser, frameIndex)
      messages = quantLogic.computeMetrics(measurementNode)
      rows = self._storedRows(measurementNode)
      self.assertTrue(rows, f"{measurementNode.GetName()} at frame {frameIndex} produced no results; messages: {messages}")
      results[frameIndex] = rows
    return results

  def assertRowsAlmostEqual(self, actual, expected, msg=""):
    self.assertEqual(sorted(actual), sorted(expected), f"{msg}: metric rows differ")
    for name, expectedValue in expected.items():
      try:
        a, e = float(actual[name]), float(expectedValue)
      except ValueError:
        self.assertEqual(actual[name], expectedValue, f"{msg}: {name}")
        continue
      if math.isnan(a) and math.isnan(e):
        continue
      # The tables hold rounded values: allow one unit of the last printed decimal besides the
      # relative tolerance (a 1.5 mm3 leaflet volume printed with one decimal may come back as 1.6)
      decimals = len(expectedValue.split(".")[1]) if "." in expectedValue else 0
      self.assertAlmostEqual(a, e, delta=abs(e) * self.RTOL + 1.01 * 10 ** (-decimals), msg=f"{msg}: {name}")

  # ---------------------------------------------------------------------------------------------
  # Inventory of everything the workflow wrote (compared across save/reload)
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _points(markupsNode, places=3):
    points = []
    for i in range(markupsNode.GetNumberOfControlPoints()):
      p = [0.0, 0.0, 0.0]
      markupsNode.GetNthControlPointPosition(i, p)
      points.append(tuple(round(x, places) for x in p))
    return points

  @staticmethod
  def _cells(modelNode):
    polyData = modelNode.GetPolyData() if modelNode else None
    return polyData.GetNumberOfCells() if polyData else 0

  @staticmethod
  def _voxelCounts(segmentationNode):
    """Voxel count per segment, the valve mask segment included."""
    counts = {}
    for segmentId in segmentationNode.GetSegmentation().GetSegmentIDs():
      labelmap = slicer.vtkOrientedImageData()
      if segmentationNode.GetBinaryLabelmapRepresentation(segmentId, labelmap) and labelmap.GetNumberOfPoints():
        from vtk.util import numpy_support
        counts[segmentId] = int(np.count_nonzero(numpy_support.vtk_to_numpy(labelmap.GetPointData().GetScalars())))
      else:
        counts[segmentId] = 0
    return counts

  def _inventory(self):
    import HeartValveLib
    inventory = {"valves": {}, "measurements": {}}
    for browserNode in scene.valveBrowserNodes():
      valveBrowser = HeartValveLib.HeartValves.getValveBrowser(browserNode)
      master = browserNode.GetMasterSequenceNode()
      timePoints = {}
      for item in range(browserNode.GetNumberOfItems()):
        scene.selectBrowserItem(browserNode, item)
        valveModel = valveBrowser.valveModel
        # The leaflet, coaptation and papillary model lists are populated by the modules when the
        # valve is selected (LeafletAnalysis.onHeartValveSelect, ValvePapillaryAnalysis)
        valveModel.updateLeafletModelsFromSegmentation()
        valveModel.updateCoaptationModels()
        valveModel.updatePapillaryModels()
        labelsNode = valveModel.valveLabelsNode
        labels = sorted((labelsNode.GetNthControlPointLabel(i), self._points(labelsNode)[i])
                        for i in range(labelsNode.GetNumberOfControlPoints())) if labelsNode else []
        segmentationNode = valveModel.leafletSegmentationNode
        timePoints[master.GetNthIndexValue(item)] = {
          "phase": valveModel.getCardiacCyclePhase(),
          "frame": valveModel.getValveVolumeSequenceIndex(),
          "contour": self._points(valveModel.annulusContourCurveNode),
          "labels": labels,
          "roi": valveModel.valveRoiModelNode is not None,
          "segments": self._voxelCounts(segmentationNode) if segmentationNode else {},
          "leafletSurfaces": {m.segmentId: self._cells(m.surfaceModelNode) for m in valveModel.leafletModels},
          "coaptations": [(self._points(c.baseLine), self._points(c.marginLine), self._cells(c.surfaceModelNode))
                          for c in valveModel.coaptationModels],
          "papillary": [self._points(m.getPapillaryLineMarkupNode()) for m in valveModel.papillaryModels],
        }
      inventory["valves"][browserNode.GetAttribute("ValveType")] = timePoints
    seqLogic = slicer.modules.sequences.logic()
    for measurementNode in scene.measurementNodes():
      refs = {}
      roles = []
      measurementNode.GetNodeReferenceRoles(roles)
      for role in roles:
        node = measurementNode.GetNodeReference(role)
        if role.startswith("Valve") and node is not None:  # empty roles are not written to the scene file
          owner = seqLogic.GetFirstBrowserNodeForProxyNode(node)
          refs[role] = owner.GetAttribute("ValveType") if owner else None
      inventory["measurements"][measurementNode.GetName()] = {
        "preset": measurementNode.GetAttribute("MeasurementPreset"), "refs": refs}
    return inventory

  # ---------------------------------------------------------------------------------------------
  # The workflow
  # ---------------------------------------------------------------------------------------------

  def _runWorkflow(self, factory, frames, mitralContourFor, aorticContourFor, scale):
    """frames: {frameIndex: phase} of both valves; the aortic valve gets contour and landmarks only."""
    frameIndices = list(frames)
    firstFrame = frameIndices[0]

    # --- 1. Annotation (ValveAnnulusAnalysis, ValveSegmentation, LeafletAnalysis, ValvePapillaryAnalysis)
    mitral = self._annotateValve(factory, "mitral", frames, mitralContourFor, scale, full=True)
    aortic = self._annotateValve(factory, "aortic", frames, aorticContourFor, scale, full=False)
    self.assertEqual(mitral.heartValveSequenceNode.GetNumberOfDataNodes(), len(frames))
    for frameIndex in frameIndices:
      factory.switchTo(mitral, frameIndex)
      valveModel = mitral.valveModel
      self.assertEqual(valveModel.getValveVolumeSequenceIndex(), frameIndex)
      self.assertEqual(valveModel.getCardiacCyclePhase(), frames[frameIndex])
      self.assertControlPointsEqual(valveModel.annulusContourCurveNode, mitralContourFor(frameIndex), places=3,
                                    msg=f"contour at frame {frameIndex} ")
      self.assertIsNotNone(valveModel.valveRoiModelNode, f"ROI at frame {frameIndex}")
      counts = self._voxelCounts(valveModel.leafletSegmentationNode)
      for segmentId, _, _, _ in self.SEGMENTS:
        self.assertGreater(counts.get(segmentId, 0), 0, f"{segmentId} segmented at frame {frameIndex}")
        # The surface boundary is stored per time point; the surface model is a shared node that is
        # regenerated from the boundary of the displayed time point
        leafletModel = valveModel.findLeafletModel(segmentId)
        self.assertTrue(valveModel.isNodeSpecifiedForCurrentTimePoint(leafletModel.getSurfaceBoundaryMarkupNode()),
                        f"leaflet surface boundary of {segmentId} at frame {frameIndex}")
        self.assertGreater(leafletModel.getSurfaceBoundaryMarkupNode().GetNumberOfControlPoints(), 2,
                           f"leaflet surface boundary points of {segmentId} at frame {frameIndex}")
      self.assertEqual(len(valveModel.coaptationModels), 1, f"coaptation at frame {frameIndex}")
      self.assertTrue(all(m.hasMusclePointsPlaced() for m in valveModel.papillaryModels), f"papillary muscles at frame {frameIndex}")

    # --- 2. Quantification (ValveQuantification) at every time point
    mitralMeasurement = self._createMeasurementNode(
      "MitralValve", {"ValveMitralValve": mitral.heartValveNode, "ValveAorticValve": aortic.heartValveNode}, "Mitral measurement")
    papillaryMeasurement = self._createMeasurementNode(
      "MitralValvePM", {"ValveMitralValve": mitral.heartValveNode}, "Papillary measurement")
    phaseCompare = self._createMeasurementNode(
      "PhaseCompare", {"ValveValve1": mitral.heartValveNode, "ValveValve4": mitral.heartValveNode}, "Phase compare")
    mitralResults = self._compute(mitralMeasurement, mitral, factory, frameIndices)
    papillaryResults = self._compute(papillaryMeasurement, mitral, factory, frameIndices)
    phaseCompareResults = self._compute(phaseCompare, mitral, factory, [firstFrame])
    anteriorName, posteriorName = self.SEGMENTS[0][1], self.SEGMENTS[1][1]
    for frameIndex, rows in mitralResults.items():
      self.assertGreater(float(rows["Annulus area (3D)"]), 0.0, f"annulus area at frame {frameIndex}")
      for name in (f"Leaflet area (atrial) - {anteriorName} (3D)", f"Leaflet area (atrial) - {posteriorName} (3D)",
                   f"Leaflet volume - {anteriorName}", f"Leaflet volume - {posteriorName}", "Billow volume", "Tenting volume"):
        self.assertIn(name, rows, f"frame {frameIndex}: leaflet metrics computed from the surfaces and the segmentation")
      self.assertTrue(any("oaptation" in name for name in rows), f"frame {frameIndex}: coaptation metrics; rows: {sorted(rows)[:40]}")
    self.assertNotEqual(mitralResults[frameIndices[0]]["Annulus area (3D)"], mitralResults[frameIndices[-1]]["Annulus area (3D)"],
                        "the time points have different contours")
    for frameIndex, rows in papillaryResults.items():
      self.assertTrue(any("apillary" in name or "hord" in name for name in rows), f"frame {frameIndex}: papillary metrics; rows: {sorted(rows)[:40]}")
    self.assertTrue(any("displacement" in name or "distance" in name for name in phaseCompareResults[firstFrame]),
                    f"phase comparison metrics; rows: {sorted(phaseCompareResults[firstFrame])[:40]}")
    # The results of every time point are stored in the scene
    factory.switchTo(mitral, firstFrame)
    self.assertRowsAlmostEqual(self._storedRows(mitralMeasurement), mitralResults[firstFrame], "results shown at the first time point")
    factory.switchTo(mitral, frameIndices[-1])
    self.assertRowsAlmostEqual(self._storedRows(mitralMeasurement), mitralResults[frameIndices[-1]], "results shown at the last time point")

    # --- 3. Save, reload, compare everything, recompute
    before = self._inventory()
    tempDir = self.tempDirectory()
    mrbPath = os.path.join(tempDir, "Workflow.mrb")
    self.assertTrue(slicer.util.saveScene(mrbPath), "saveScene")
    slicer.mrmlScene.Clear(0)
    self.resetHeartValveLibCaches()
    self.assertTrue(slicer.util.loadScene(mrbPath), "loadScene")
    after = self._inventory()
    self.assertEqual(sorted(after["valves"]), sorted(before["valves"]), "valve browsers after reload")
    for valveType, timePoints in before["valves"].items():
      self.assertEqual(sorted(after["valves"][valveType]), sorted(timePoints), f"{valveType}: time points after reload")
      for indexValue, expected in timePoints.items():
        self.assertEqual(after["valves"][valveType][indexValue], expected, f"{valveType} @ {indexValue} after reload")
    self.assertEqual(after["measurements"], before["measurements"], "measurements after reload")

    import HeartValveLib
    reloadedMitral = next(HeartValveLib.HeartValves.getValveBrowser(b) for b in scene.valveBrowserNodes()
                          if b.GetAttribute("ValveType") == "mitral")
    reloadedFactory = NewFormatValveFactory(volumeBrowserNode=reloadedMitral.volumeSequenceBrowserNode)
    measurementsByName = {node.GetName(): node for node in scene.measurementNodes()}
    recomputed = self._compute(measurementsByName["Mitral measurement"], reloadedMitral, reloadedFactory, frameIndices)
    for frameIndex in frameIndices:
      self.assertRowsAlmostEqual(recomputed[frameIndex], mitralResults[frameIndex], f"recomputed after reload at frame {frameIndex}")
    recomputedPapillary = self._compute(measurementsByName["Papillary measurement"], reloadedMitral, reloadedFactory, frameIndices)
    for frameIndex in frameIndices:
      self.assertRowsAlmostEqual(recomputedPapillary[frameIndex], papillaryResults[frameIndex], f"papillary recomputed after reload at frame {frameIndex}")

    # --- 4. Batch export of the saved scene (ValveBatchExport), checked against the computed values
    import ValveBatchExport
    rules = self.rules
    rules.ValveBatchExportRule.setPhasesToExport([self.PHASES[phase] for phase in frames.values()])
    rules.ValveBatchExportRule.setValveTypesToExport(["mitral"])
    exportLogic = ValveBatchExport.ValveBatchExportLogic(logCallback=self.logs.append)
    for ruleClass in (rules.ValveLandmarkCoordinatesExportRule, rules.AnnulusContourCoordinatesExportRule,
                      rules.QuantificationResultsExportRule, rules.LeafletSegmentationExportRule,
                      rules.ValveVolumeFrameExportRule):
      exportLogic.addRule(ruleClass)
    outputDir = os.path.join(tempDir, "export", "Workflow")
    exportLogic.exportMRBFile(mrbPath, outputDir)
    self.assertFalse([m for m in self.logs if "rror" in m and "No error" not in m], f"export log: {self.logs}")

    def readCsv(name):
      path = os.path.join(outputDir, name)
      self.assertTrue(os.path.exists(path), f"{name} exported; files: {sorted(os.listdir(outputDir))}")
      with open(path, newline="") as f:
        return list(csv.DictReader(f))

    phaseOf = {str(frameIndex): self.PHASES[phase] for frameIndex, phase in frames.items()}
    landmarkRows = readCsv(rules.ValveLandmarkCoordinatesExportRule.CSV_OUTPUT_FILENAME)
    # The quantification adds derived landmarks (e.g. the annulus centroid) to the valves, so the
    # export holds the four placed landmarks per time point plus those
    mitralLandmarks = [r for r in landmarkRows if r["Valve"] == "mitral"]
    self.assertEqual({r["FrameNumber"]: r["Phase"] for r in mitralLandmarks}, phaseOf)
    for frameIndex in frameIndices:
      placed = {label: (r, a, s) for label, r, a, s in self._landmarks(mitralContourFor(frameIndex))}
      exported = {r["LandmarkLabel"]: (float(r["LandmarkR"]), float(r["LandmarkA"]), float(r["LandmarkS"]))
                  for r in mitralLandmarks if r["FrameNumber"] == str(frameIndex)}
      self.assertTrue(set(placed) <= set(exported), f"placed landmarks exported at frame {frameIndex}: {sorted(exported)}")
      for label, expected in placed.items():
        np.testing.assert_allclose(exported[label], expected, atol=0.01, err_msg=f"landmark {label} at frame {frameIndex}")
    contourRows = readCsv(rules.AnnulusContourCoordinatesExportRule.CURVE_POINTS_CSV_OUTPUT_FILENAME)
    self.assertEqual({r["FrameNumber"] for r in contourRows if r["Valve"] == "mitral"}, set(phaseOf), "contour exported per time point")
    quantRows = readCsv(rules.QuantificationResultsExportRule.LONG_CSV_OUTPUT_FILENAME)
    areaRows = {r["Phase"]: r for r in quantRows if r["Measurement"] == "Annulus area (3D)" and r["Phase"] in phaseOf.values()}
    self.assertEqual(sorted(areaRows), sorted(phaseOf.values()), f"annulus area exported per phase: {quantRows[:3]}")
    for frameIndex, phase in frames.items():
      exported = float(areaRows[self.PHASES[phase]]["Value"])
      computed = float(mitralResults[frameIndex]["Annulus area (3D)"])
      self.assertAlmostEqual(exported, computed, delta=computed * self.RTOL, msg=f"exported annulus area at {phase}")
    imageFiles = sorted(n for n in os.listdir(outputDir) if n.endswith("." + rules.ValveBatchExportRule.IMAGE_FILE_EXTENSION))
    leafletFiles = [n for n in imageFiles if "leaflet" in n.lower()]
    self.assertEqual(len(leafletFiles), len(self.SEGMENTS) * len(frames), f"one label map per leaflet and time point: {imageFiles}")
    self.assertEqual(len(imageFiles) - len(leafletFiles), len(frames), f"one volume frame per time point: {imageFiles}")

  # ---------------------------------------------------------------------------------------------
  # Tests
  # ---------------------------------------------------------------------------------------------

  def test_workflow_on_synthetic_volume(self):
    factory = NewFormatValveFactory(numFrames=6)
    frames = {1: "mid-systole", 4: "end-diastole"}
    mitralContour = NewFormatValveFactory.contourPoints
    aorticContour = lambda frameIndex: scene.ellipsePoints(numPoints=12, radiusX=1.5, radiusY=1.3, center=(0.0, 3.5, 1.0),
                                                           tilt=0.2, phaseOffset=0.1 * frameIndex)
    self._runWorkflow(factory, frames, mitralContour, aorticContour, scale=1.0)

  def test_workflow_on_mitral_sample(self):
    import ValveModelTest
    volumeBrowserNode = scene.loadMitralSample()
    factory = NewFormatValveFactory(volumeBrowserNode=volumeBrowserNode)
    cases = ValveModelTest.ValveModelTestTest
    frames = {5: "mid-systole", 24: "end-diastole"}
    mitralContours = {5: cases.MITRAL_ANNULUS_CONTOUR_FRAME0, 24: cases.MITRAL_ANNULUS_CONTOUR_FRAME1}
    aorticContours = {5: cases.AORTIC_ANNULUS_CONTOUR_FRAME0, 24: cases.AORTIC_ANNULUS_CONTOUR_FRAME1}
    self._runWorkflow(factory, frames, mitralContours.__getitem__, aorticContours.__getitem__, scale=5.0)
