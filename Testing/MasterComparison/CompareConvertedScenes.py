"""
Convert the legacy scenes written by GenerateMasterScenes.py (master branch code) with the
heartvalvesequence code and compare the result to the reference values recorded by master.

For each recorded valve, the matching time point of the converted valve browser is displayed and
its annotations (annulus contour, labels, ROI, segmentation, leaflet surfaces, coaptation,
papillary muscles, phase, frame) are compared to the master values. For each recorded measurement
the converted results table is compared to the master table (data preservation), then the metrics
are recomputed with the heartvalvesequence ValveQuantification code and compared to the master
values (computational equivalence).

Usage: Slicer --python-script CompareConvertedScenes.py -- <directory with the generated scenes>
"""
import glob
import json
import os
import shutil
import sys
import time
import traceback

import numpy as np
import slicer
import vtk

DATA_DIR = sys.argv[-1]
POINT_TOLERANCE = 1e-3  # mm
METRIC_RELATIVE_TOLERANCE = 1e-3
METRIC_ABSOLUTE_TOLERANCE = 1e-3


def pump(count=10):
  for _ in range(count):
    slicer.app.processEvents()


def waitForModules(names, timeoutSec=180):
  start = time.time()
  while time.time() - start < timeoutSec:
    if all(hasattr(slicer.modules, name.lower()) for name in names):
      return
    pump(1)
    time.sleep(0.1)
  raise RuntimeError(f"Modules not loaded: {names}")


def markupsPoints(markupsNode):
  if not markupsNode:
    return None
  points = []
  for index in range(markupsNode.GetNumberOfControlPoints()):
    position = [0.0, 0.0, 0.0]
    markupsNode.GetNthControlPointPosition(index, position)
    points.append(position)
  return points


def markupsLabels(markupsNode):
  if not markupsNode:
    return None
  labels = []
  for index in range(markupsNode.GetNumberOfControlPoints()):
    position = [0.0, 0.0, 0.0]
    markupsNode.GetNthControlPointPosition(index, position)
    labels.append([markupsNode.GetNthControlPointLabel(index)] + position)
  return labels


def segmentInfo(segmentationNode, referenceVolumeNode=None):
  if not segmentationNode:
    return {}
  segmentation = segmentationNode.GetSegmentation()
  result = {}
  for index in range(segmentation.GetNumberOfSegments()):
    segmentId = segmentation.GetNthSegmentID(index)
    segment = segmentation.GetSegment(segmentId)
    voxels = None
    try:
      array = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId, referenceVolumeNode)
      voxels = int(np.count_nonzero(array)) if array is not None else 0
    except Exception:
      pass
    result[segmentId] = {"name": segment.GetName(), "voxels": voxels}
  return result


def tableRows(tableNode):
  if not tableNode:
    return None
  return [[tableNode.GetCellText(rowIndex, columnIndex) for columnIndex in range(tableNode.GetNumberOfColumns())]
          for rowIndex in range(tableNode.GetNumberOfRows())]


def heartValveNodeHasReferences(node, role):
  return node is not None and node.GetNumberOfNodeReferences(role) > 0


class Checker:
  def __init__(self):
    self.checks = []
    self.notes = []

  def note(self, context, name, detail, same):
    """Informational difference that is expected (e.g. regenerated derived geometry)."""
    if not same:
      self.notes.append({"context": context, "note": name, "detail": detail})

  def check(self, context, name, ok, detail=""):
    self.checks.append({"context": context, "check": name, "ok": bool(ok), "detail": detail if not ok else ""})
    return ok

  def points(self, context, name, expected, actual):
    if expected is None or len(expected) == 0:
      return self.check(context, name, not actual, f"expected no points, got {len(actual or [])}")
    if actual is None:
      return self.check(context, name, False, f"expected {len(expected)} points, node missing")
    if len(expected) != len(actual):
      return self.check(context, name, False, f"expected {len(expected)} points, got {len(actual)}")
    difference = float(np.max(np.abs(np.array(expected, dtype=float) - np.array(actual, dtype=float))))
    return self.check(context, name, difference <= POINT_TOLERANCE, f"max difference {difference:.4g} mm")

  def labels(self, context, name, expected, actual):
    expected = sorted(expected or [])
    actual = sorted(actual or [])
    if [e[0] for e in expected] != [a[0] for a in actual]:
      return self.check(context, name, False, f"expected labels {[e[0] for e in expected]}, got {[a[0] for a in actual]}")
    if not expected:
      return self.check(context, name, True)
    difference = float(np.max(np.abs(np.array([e[1:] for e in expected], dtype=float)
                                     - np.array([a[1:] for a in actual], dtype=float))))
    return self.check(context, name, difference <= POINT_TOLERANCE, f"max difference {difference:.4g} mm")


def metricsByName(rows):
  result = {}
  for row in rows or []:
    if not row:
      continue
    name = row[0]
    # Metric names are not unique in all presets; keep all values of a name in order
    result.setdefault(name, []).append(row)
  return result


def valuesMatch(expected, actual):
  if expected == actual:
    return True
  try:
    e, a = float(expected), float(actual)
  except (TypeError, ValueError):
    return False
  if np.isnan(e) and np.isnan(a):
    return True
  return abs(e - a) <= max(METRIC_ABSOLUTE_TOLERANCE, METRIC_RELATIVE_TOLERANCE * abs(e))


# Metrics that the heartvalvesequence branch computes differently from master on purpose. Differences in
# these are reported separately (with the reason) instead of failing the comparison.
KNOWN_ALGORITHM_CHANGES = [
  (("centered", "bending angle"),
   "annulus curve interpolation: master samples its SmoothCurve spline, heartvalvesequence the markups "
   "closed curve spline, which shifts the quadrant clipping planes / curve halves slightly"),
  (("Leaflet area", "Leaflet thickness", "Tenting", "Billow", "atrial"),
   "valve surface extraction: master wraps the leaflets with a smoothed 'blanket' surface, heartvalvesequence "
   "uses ValveModel.createValveSurface; leaflet area metrics lost the '(3D)' suffix"),
]


def knownChangeReason(metricName):
  for patterns, reason in KNOWN_ALGORITHM_CHANGES:
    if any(pattern in metricName for pattern in patterns):
      return reason
  return None


def compareMetricTables(checker, context, expectedRows, actualRows, allowKnownChanges=False, masterFailed=False):
  """Compare results tables metric by metric; returns list of mismatch descriptions.
  :param allowKnownChanges: differences in metrics listed in KNOWN_ALGORITHM_CHANGES are notes, not failures
  :param masterFailed: master raised an exception while computing, so metrics missing from the master table
    are not failures
  """
  if expectedRows is None:
    return checker.check(context, "results table", actualRows is None or actualRows == [], "master had no table")
  if actualRows is None:
    return checker.check(context, "results table", False, "results table missing")
  expected = metricsByName(expectedRows)
  actual = metricsByName(actualRows)
  mismatches = []

  def mismatch(name, description, missingInMaster=False):
    reason = knownChangeReason(name) if allowKnownChanges else None
    if reason:
      checker.note(context, f"{name!r} (known algorithm change)", description, False)
    elif missingInMaster and masterFailed:
      checker.note(context, f"{name!r} (master raised an exception before computing it)", description, False)
    else:
      mismatches.append(f"{name!r}: {description}")

  for name, expectedMetricRows in expected.items():
    actualMetricRows = actual.get(name, [])
    if len(actualMetricRows) != len(expectedMetricRows):
      mismatch(name, f"{len(expectedMetricRows)} row(s) in master, {len(actualMetricRows)} now")
      continue
    for expectedRow, actualRow in zip(expectedMetricRows, actualMetricRows):
      if not valuesMatch(expectedRow[1] if len(expectedRow) > 1 else None, actualRow[1] if len(actualRow) > 1 else None):
        mismatch(name, f"master {expectedRow[1:]} now {actualRow[1:]}")
      elif expectedRow[2:] != actualRow[2:]:
        mismatch(name, f"unit master {expectedRow[2:]} now {actualRow[2:]}")
  for name in actual:
    if name not in expected:
      mismatch(name, f"not computed by master, now {actual[name][0][1:]}", missingInMaster=True)
  checker.check(context, f"results table ({len(expectedRows)} master rows)", not mismatches,
                f"{len(mismatches)} difference(s): " + "; ".join(mismatches[:40]))
  return mismatches


class ConvertedScene:
  def __init__(self):
    import HeartValveLib
    self.HeartValveLib = HeartValveLib
    self.sequencesLogic = slicer.modules.sequences.logic()

  def valveBrowsers(self, valveType):
    return [self.HeartValveLib.HeartValves.getValveBrowser(browserNode)
            for browserNode in slicer.util.getNodesByClass("vtkMRMLSequenceBrowserNode")
            if browserNode.GetAttribute("ModuleName") == "HeartValve" and browserNode.GetAttribute("ValveType") == valveType]

  def goToTimePoint(self, valveBrowser, indexValue):
    browserNode = valveBrowser.valveBrowserNode
    itemNumber = browserNode.GetMasterSequenceNode().GetItemNumberFromIndexValue(indexValue)
    if itemNumber < 0:
      return False
    browserNode.SetSelectedItemNumber(itemNumber)
    pump()
    valveModel = valveBrowser.valveModel
    self.HeartValveLib.goToAnalyzedFrame(valveModel)
    pump()
    return True

  def measurementProxies(self, valveBrowser, presetId):
    proxies = []
    sequenceNodes = vtk.vtkCollection()
    valveBrowser.valveBrowserNode.GetSynchronizedSequenceNodes(sequenceNodes, True)
    for sequenceNode in sequenceNodes:
      proxyNode = valveBrowser.valveBrowserNode.GetProxyNode(sequenceNode)
      if (proxyNode and proxyNode.GetAttribute("ModuleName") == "HeartValveMeasurement"
          and proxyNode.GetAttribute("MeasurementPreset") == presetId):
        proxies.append((proxyNode, sequenceNode))
    return proxies

  @staticmethod
  def resultsTable(measurementNode):
    roles = []
    measurementNode.GetNodeReferenceRoles(roles)
    for role in roles:
      node = measurementNode.GetNodeReference(role)
      if node and node.IsA("vtkMRMLTableNode"):
        return node
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    children = vtk.vtkIdList()
    shNode.GetItemChildren(shNode.GetItemByDataNode(measurementNode), children, True)
    for index in range(children.GetNumberOfIds()):
      node = shNode.GetItemDataNode(children.GetId(index))
      if node and node.IsA("vtkMRMLTableNode"):
        return node
    return None


def compareScenario(scenarioName, reference, checker):
  import Converter4DSequences
  slicer.mrmlScene.Clear(0)
  with Converter4DSequences.Converter4DSequences.suspendAutoConvert():
    slicer.util.loadScene(os.path.join(DATA_DIR, f"{scenarioName}.mrb"))
    pump()
    legacyValveNames = [v["name"] for v in reference["valves"]]
    Converter4DSequences.Converter4DSequencesLogic().performFullConversion(showMessage=False, interactive=False)
    pump()
  # The converted (4D) scene, before any comparison changes it, as sample data for other tests.
  # Saved as a directory, not an .mrb: sequences of models are staged in nested directories named after
  # long metric names, which exceeds the Windows path length limit under the .mrb staging directory.
  # Slicer does not save a scene into a non-empty directory, so the scene of a previous run is removed.
  convertedDir = os.path.join(DATA_DIR, f"{scenarioName}-converted")
  shutil.rmtree(convertedDir, ignore_errors=True)
  os.makedirs(convertedDir)
  checker.check(scenarioName, "converted scene saved", slicer.util.saveScene(convertedDir))
  scene = ConvertedScene()
  logic = Converter4DSequences.Converter4DSequencesLogic()
  ctx = scenarioName
  checker.check(ctx, "nothing left to convert", not logic.sceneHasConvertibleNodes())
  remaining = [n.GetName() for n in slicer.util.getNodesByClass("vtkMRMLScriptedModuleNode")
               if n.GetAttribute("ModuleName") == "HeartValve" and not scene.sequencesLogic.GetFirstBrowserNodeForProxyNode(n)]
  checker.check(ctx, "no legacy valve nodes left", not remaining, f"left: {remaining}")

  valveTypes = sorted({v["valveType"] for v in reference["valves"]})
  for valveType in valveTypes:
    expectedValves = [v for v in reference["valves"] if v["valveType"] == valveType]
    browsers = scene.valveBrowsers(valveType)
    checker.check(ctx, f"{valveType}: one valve browser", len(browsers) == 1, f"found {len(browsers)}")
    if not browsers:
      continue
    browserNode = browsers[0].valveBrowserNode
    checker.check(ctx, f"{valveType}: one time point per legacy valve",
                  browserNode.GetNumberOfItems() == len(expectedValves),
                  f"{browserNode.GetNumberOfItems()} time points for {len(expectedValves)} legacy valves")

  for expected in reference["valves"]:
    vctx = f"{scenarioName} / {expected['name']}"
    browsers = scene.valveBrowsers(expected["valveType"])
    if not browsers:
      continue
    valveBrowser = browsers[0]
    if not checker.check(vctx, "time point exists", scene.goToTimePoint(valveBrowser, expected["indexValue"]),
                         f"no time point at index value {expected['indexValue']}"):
      continue
    valveModel = valveBrowser.valveModel
    checker.check(vctx, "cardiac cycle phase", valveModel.getCardiacCyclePhase() == expected["phase"],
                  f"got {valveModel.getCardiacCyclePhase()}")
    checker.check(vctx, "volume frame index", valveModel.getValveVolumeSequenceIndex() == expected["frameIndex"],
                  f"got {valveModel.getValveVolumeSequenceIndex()}")
    checker.check(vctx, "probe position", valveBrowser.probePosition == expected["probePosition"],
                  f"got {valveBrowser.probePosition}")
    radius = valveModel.annulusContourRadius
    checker.check(vctx, "annulus contour radius",
                  radius is not None and abs(radius - expected["annulusContourRadius"]) < 1e-6, f"got {radius}")
    checker.points(vctx, "annulus contour points", expected["annulusContourPoints"],
                   markupsPoints(valveModel.annulusContourCurveNode))
    checker.labels(vctx, "annulus labels", expected["annulusLabels"], markupsLabels(valveModel.valveLabelsNode))

    roiNode = valveModel.valveRoiModelNode
    if expected["roi"]:
      checker.check(vctx, "valve ROI geometry",
                    roiNode is not None and valveModel.valveRoi.getRoiGeometry() == expected["roi"],
                    f"got {valveModel.valveRoi.getRoiGeometry() if roiNode else None}")
    if expected["roiModelPoints"]:
      roiPoints = roiNode.GetPolyData().GetNumberOfPoints() if roiNode and roiNode.GetPolyData() else 0
      # The ROI model is derived from the annulus contour and the ROI parameters and regenerated
      checker.check(vctx, "valve ROI model (derived)", roiPoints > 0, f"empty (master {expected['roiModelPoints']} points)")
      checker.note(vctx, "valve ROI model points", f"{roiPoints} (master {expected['roiModelPoints']})",
                   roiPoints == expected["roiModelPoints"])

    # Segments and leaflets are compared by name: the conversion harmonizes the segment IDs of the phases
    # (in master each phase's segmentation has its own IDs), so the IDs may differ from the master IDs.
    # The master reference voxel counts were computed in the geometry of the valve volume.
    maskId = scene.HeartValveLib.VALVE_MASK_SEGMENT_ID
    actualSegments = {v["name"]: v["voxels"] for k, v in
                      segmentInfo(valveModel.leafletSegmentationNode, valveBrowser.valveVolumeNode).items() if k != maskId}
    expectedSegments = {v["name"]: v["voxels"] for k, v in (expected["segments"] or {}).items() if k != maskId}
    checker.check(vctx, "leaflet segments", sorted(actualSegments) == sorted(expectedSegments),
                  f"got {sorted(actualSegments)}, master {sorted(expectedSegments)}")
    voxelDifferences = {name: (voxels, actualSegments.get(name)) for name, voxels in expectedSegments.items()
                        if actualSegments.get(name) != voxels}
    checker.check(vctx, "leaflet segment voxels", not voxelDifferences, f"(master, now): {voxelDifferences}")
    if expected["leafletVolumeVoxels"] is not None:
      leafletVolumeNode = valveModel.leafletVolumeNode
      voxels = int(np.count_nonzero(slicer.util.arrayFromVolume(leafletVolumeNode))) if leafletVolumeNode else None
      checker.check(vctx, "leaflet volume", voxels == expected["leafletVolumeVoxels"],
                    f"{voxels} non-zero voxels (master {expected['leafletVolumeVoxels']})")

    if expected["leaflets"]:
      valveModel.updateLeafletModelsFromSegmentation()
    actualLeaflets = {m.getName(): m for m in valveModel.leafletModels}
    expectedLeaflets = {(expected["segments"] or {}).get(segmentId, {}).get("name", segmentId): leaflet
                        for segmentId, leaflet in expected["leaflets"].items()}
    checker.check(vctx, "leaflet models", sorted(actualLeaflets) == sorted(expectedLeaflets),
                  f"got {sorted(actualLeaflets)}, master {sorted(expectedLeaflets)}")
    for leafletName, expectedLeaflet in expectedLeaflets.items():
      leafletModel = actualLeaflets.get(leafletName)
      checker.points(vctx, f"{leafletName} boundary", expectedLeaflet["boundaryPoints"],
                     markupsPoints(leafletModel.surfaceBoundary) if leafletModel else None)
      if expectedLeaflet["surfacePoints"]:
        surface = leafletModel.surfaceModelNode if leafletModel else None
        surfacePoints = surface.GetPolyData().GetNumberOfPoints() if surface and surface.GetPolyData() else 0
        checker.check(vctx, f"{leafletName} surface (derived)", surfacePoints > 0,
                      f"empty surface (master {expectedLeaflet['surfacePoints']} points)")
        checker.note(vctx, f"{leafletName} surface points", f"{surfacePoints} (master {expectedLeaflet['surfacePoints']})",
                     surfacePoints == expectedLeaflet["surfacePoints"])

    if heartValveNodeHasReferences(valveBrowser.heartValveNode, "CoaptationBaseLineMarkup"):
      valveModel.updateCoaptationModels()
    # Coaptation nodes are shared between time points: count those that are specified at this time point
    specifiedCoaptations = [m for m in valveModel.coaptationModels
                            if m.baseLine and valveModel.isNodeSpecifiedForCurrentTimePoint(m.baseLine)]
    checker.check(vctx, "coaptation models", len(specifiedCoaptations) == len(expected["coaptations"]),
                  f"got {len(specifiedCoaptations)} specified at this time point")
    for index, expectedCoaptation in enumerate(expected["coaptations"]):
      if index >= len(specifiedCoaptations):
        break
      coaptationModel = specifiedCoaptations[index]
      checker.points(vctx, f"coaptation {index} base line", expectedCoaptation["baseLine"], markupsPoints(coaptationModel.baseLine))
      checker.points(vctx, f"coaptation {index} margin line", expectedCoaptation["marginLine"], markupsPoints(coaptationModel.marginLine))
      surface = coaptationModel.surfaceModelNode
      surfacePoints = surface.GetPolyData().GetNumberOfPoints() if surface and surface.GetPolyData() else 0
      # The coaptation surface is derived from the base and margin lines and regenerated
      checker.check(vctx, f"coaptation {index} surface (derived)", surfacePoints > 0,
                    f"empty (master {expectedCoaptation['surfacePoints']} points)")
      checker.note(vctx, f"coaptation {index} surface points", f"{surfacePoints} (master {expectedCoaptation['surfacePoints']})",
                   surfacePoints == expectedCoaptation["surfacePoints"])

    heartValveNode = valveBrowser.heartValveNode
    if heartValveNode.GetNumberOfNodeReferences("PapillaryLineMarkup") > 0:
      valveModel.updatePapillaryModels()
    actualPapillary = {m.getName(): markupsPoints(m.getPapillaryLineMarkupNode()) for m in valveModel.papillaryModels}
    expectedPapillary = expected["papillary"]
    checker.check(vctx, "papillary muscles", sorted(actualPapillary) == sorted(expectedPapillary),
                  f"got {sorted(actualPapillary)}")
    for name, expectedPoints in expectedPapillary.items():
      if name in actualPapillary:
        checker.points(vctx, f"papillary {name}", expectedPoints, actualPapillary[name])

  # Measurements
  import ValveQuantification
  quantificationLogic = ValveQuantification.ValveQuantificationLogic()
  for expected in reference["measurements"]:
    mctx = f"{scenarioName} / measurement {expected['key']}"
    inputs = expected["inputs"]
    # Display the time points of all input valves
    firstBrowser = None
    for inputValveId, (valveType, phase, frameIndex) in inputs.items():
      valveReference = next(v for v in reference["valves"] if v["valveType"] == valveType and v["frameIndex"] == frameIndex)
      browsers = scene.valveBrowsers(valveType)
      if browsers:
        scene.goToTimePoint(browsers[0], valveReference["indexValue"])
        firstBrowser = firstBrowser or browsers[0]
    if firstBrowser is None:
      checker.check(mctx, "input valve browser", False, "not found")
      continue
    proxies = [(proxy, sequence) for proxy, sequence in scene.measurementProxies(firstBrowser, expected["preset"])]
    firstInput = next(iter(inputs.values()))
    firstReference = next(v for v in reference["valves"] if v["valveType"] == firstInput[0] and v["frameIndex"] == firstInput[2])
    atTimePoint = [(proxy, sequence) for proxy, sequence in proxies
                   if sequence.GetItemNumberFromIndexValue(firstReference["indexValue"]) >= 0]
    if not checker.check(mctx, "converted measurement at the time point", len(atTimePoint) == 1,
                         f"{len(atTimePoint)} of {len(proxies)} '{expected['preset']}' measurement(s) in "
                         f"{firstBrowser.valveBrowserNode.GetName()} have an item at {firstReference['indexValue']}"):
      continue
    measurementNode = atTimePoint[0][0]

    for inputValveId, (valveType, phase, frameIndex) in inputs.items():
      referenced = measurementNode.GetNodeReference("Valve" + inputValveId)
      browsers = scene.valveBrowsers(valveType)
      expectedNode = browsers[0].heartValveNode if browsers else None
      checker.check(mctx, f"valve reference {inputValveId}",
                    referenced is not None and expectedNode is not None and referenced.GetID() == expectedNode.GetID(),
                    f"references {referenced.GetName() if referenced else None}, expected {expectedNode.GetName() if expectedNode else None}")

    storedRows = tableRows(scene.resultsTable(measurementNode))
    stored = Checker()
    compareMetricTables(stored, f"{mctx} (stored)", expected["results"], storedRows)
    checker.checks.extend(stored.checks)

    try:
      messages = quantificationLogic.computeMetrics(measurementNode) or []
    except Exception:
      messages = [f"EXCEPTION {traceback.format_exc()}"]
    pump()
    recomputedRows = tableRows(scene.resultsTable(measurementNode))
    masterExceptions = [m for m in expected["messages"] if m.startswith("EXCEPTION")]
    compareMetricTables(checker, f"{mctx} (recomputed)", expected["results"], recomputedRows,
                        allowKnownChanges=True, masterFailed=bool(masterExceptions))
    for masterException in masterExceptions:
      checker.note(mctx, "master raised while computing", masterException.strip().splitlines()[-1][:300], False)
    newExceptions = [str(m) for m in messages if str(m).startswith("EXCEPTION")]
    checker.check(mctx, "recompute without exception", not newExceptions,
                  "; ".join(newExceptions)[-1500:] + (" (master also raised)" if masterExceptions else ""))


log = {"errors": [], "scenarios": {}}
try:
  waitForModules(["ValveAnnulusAnalysis", "ValveQuantification", "Converter4DSequences"])
  for referencePath in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
    if referencePath.endswith(("-comparison.json", "-notes.json", "generate-log.json", "compare-log.json")):
      continue
    reference = json.load(open(referencePath))
    scenarioName = reference.get("scenario")
    if not scenarioName:
      continue
    checker = Checker()
    try:
      compareScenario(scenarioName, reference, checker)
    except Exception:
      checker.check(scenarioName, "comparison ran", False, traceback.format_exc())
    with open(os.path.join(DATA_DIR, f"{scenarioName}-comparison.json"), "w") as f:
      json.dump(checker.checks, f, indent=1)
    with open(os.path.join(DATA_DIR, f"{scenarioName}-notes.json"), "w") as f:
      json.dump(checker.notes, f, indent=1)
    log["scenarios"][scenarioName] = {"passed": sum(c["ok"] for c in checker.checks),
                                      "failed": sum(not c["ok"] for c in checker.checks)}
    print(f"[compare] {scenarioName}: {log['scenarios'][scenarioName]}", flush=True)

  # Markdown report
  lines = ["# Master vs. 4D conversion comparison", ""]
  for scenarioName, counts in log["scenarios"].items():
    lines.append(f"## {scenarioName}: {counts['passed']} checks passed, {counts['failed']} failed")
    lines.append("")
    checks = json.load(open(os.path.join(DATA_DIR, f"{scenarioName}-comparison.json")))
    for c in checks:
      if not c["ok"]:
        lines.append(f"- FAIL **{c['context']}** - {c['check']}: {c['detail']}")
    notes = json.load(open(os.path.join(DATA_DIR, f"{scenarioName}-notes.json")))
    if notes:
      lines.append("")
      lines.append("Expected differences (regenerated derived data, known algorithm changes, master failures):")
      for n in notes:
        lines.append(f"- {n['context']} - {n['note']}: {n['detail']}")
    lines.append("")
  lines.append("## Known algorithm changes")
  lines.append("")
  for patterns, reason in KNOWN_ALGORITHM_CHANGES:
    lines.append(f"- Metrics containing {', '.join(repr(p) for p in patterns)}: {reason}")
  lines.append("")
  with open(os.path.join(DATA_DIR, "comparison-report.md"), "w") as f:
    f.write("\n".join(lines))
except Exception:
  log["errors"].append(traceback.format_exc())

with open(os.path.join(DATA_DIR, "compare-log.json"), "w") as f:
  json.dump(log, f, indent=1)
slicer.app.exit(0)
