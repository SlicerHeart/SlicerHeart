"""
Create legacy (one HeartValve node per cardiac phase) scenes with the ORIGINAL master branch code.

Run in a Slicer instance that loads the SlicerHeart modules of the master branch (see
RunMasterComparison.ps1). For each scenario a .mrb scene and a JSON file with reference values
(annotations and quantification results, as computed by master) are written to the output directory.
CompareConvertedScenes.py then loads the scenes with the heartvalvesequence code, converts them to the
4D (sequence) format and compares the result to the reference values.

Usage: Slicer --python-script GenerateMasterScenes.py -- <outputDirectory>
"""
import json
import os
import sys
import time
import traceback

import numpy as np
import slicer
import vtk

OUTPUT_DIR = sys.argv[-1]

# Anatomical mitral annulus contours of the SlicerHeart "Mitral" sample (copied from ValveModelTest:
# MITRAL_ANNULUS_CONTOUR_FRAME0/1, used at frames 5 and 24 like Converter4DSequencesTest.test_real_data_smoke)
MITRAL_CONTOUR_FRAME5 = [
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
MITRAL_CONTOUR_FRAME24 = [
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
    points.append([round(value, 4) for value in position])
  return points


def markupsLabels(markupsNode):
  if not markupsNode:
    return None
  labels = []
  for index in range(markupsNode.GetNumberOfControlPoints()):
    position = [0.0, 0.0, 0.0]
    markupsNode.GetNthControlPointPosition(index, position)
    labels.append([markupsNode.GetNthControlPointLabel(index)] + [round(value, 4) for value in position])
  return labels


def segmentInfo(segmentationNode):
  if not segmentationNode:
    return None
  segmentation = segmentationNode.GetSegmentation()
  result = {}
  for index in range(segmentation.GetNumberOfSegments()):
    segmentId = segmentation.GetNthSegmentID(index)
    segment = segmentation.GetSegment(segmentId)
    voxels = None
    try:
      array = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId)
      voxels = int(np.count_nonzero(array)) if array is not None else 0
    except Exception:
      pass
    result[segmentId] = {"name": segment.GetName(), "voxels": voxels}
  return result


def tableRows(tableNode):
  if not tableNode:
    return None
  rows = []
  for rowIndex in range(tableNode.GetNumberOfRows()):
    rows.append([tableNode.GetCellText(rowIndex, columnIndex) for columnIndex in range(tableNode.GetNumberOfColumns())])
  return rows


def measurementResultsTable(measurementNode):
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  children = vtk.vtkIdList()
  shNode.GetItemChildren(shNode.GetItemByDataNode(measurementNode), children, True)
  for index in range(children.GetNumberOfIds()):
    node = shNode.GetItemDataNode(children.GetId(index))
    if node and node.IsA("vtkMRMLTableNode") and node.GetName().startswith("Quantification results"):
      return node
  return None


class MasterSceneBuilder:
  """Builds a legacy scene with the master HeartValveLib, the same way the master modules do."""

  def __init__(self):
    import SampleData
    SampleData.SampleDataLogic().downloadSample("Mitral")
    # The sample bundles a leaflet segmentation that is not needed here
    for segmentationNode in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
      slicer.mrmlScene.RemoveNode(segmentationNode)
    sequenceNode = slicer.util.getNodesByClass("vtkMRMLSequenceNode")[0]
    self.volumeBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForSequenceNode(sequenceNode)
    self.volumeSequenceNode = self.volumeBrowserNode.GetMasterSequenceNode()
    self.volumeNode = self.volumeBrowserNode.GetProxyNode(self.volumeSequenceNode)
    self.valves = []
    self.measurements = []

  def selectFrame(self, frameIndex):
    self.volumeBrowserNode.SetSelectedItemNumber(frameIndex)
    pump()

  def addValve(self, valveType, phase, frameIndex, contourPoints, roi=True, segmentation=True, leaflets=True,
               coaptation=True, papillary=True, labels=("A", "P", "AL", "PM"),
               leafletNames=("anterior leaflet", "posterior leaflet")):
    import HeartValveLib
    self.selectFrame(frameIndex)
    heartValveNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode")
    heartValveNode.SetHideFromEditors(False)
    heartValveNode.SetAttribute("ModuleName", "HeartValve")
    heartValveNode.SetName(slicer.mrmlScene.GetUniqueNameByString("HeartValve"))
    valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)
    valveModel.setValveVolumeNode(self.volumeNode)
    valveModel.setValveVolumeSequenceIndex(frameIndex)
    valveModel.setValveType(valveType)
    valveModel.setCardiacCyclePhase(phase)

    contourNode = valveModel.getAnnulusContourMarkupNode()
    contourNode.RemoveAllControlPoints()
    for point in contourPoints:
      contourNode.AddControlPoint(vtk.vtkVector3d(point))
    valveModel.updateAnnulusContourModel()

    step = len(contourPoints) // max(len(labels), 1)
    for labelIndex, label in enumerate(labels):
      valveModel.setAnnulusMarkupLabel(label, contourPoints[labelIndex * step])

    record = {"node": heartValveNode, "valveModel": valveModel, "valveType": valveType, "phase": phase,
              "frameIndex": frameIndex, "problems": []}

    if roi:
      valveModel.valveRoi.setRoiGeometry({"ValveRoiScale": 110.0, "ValveRoiTopDistance": 12.0, "ValveRoiTopScale": 60.0,
                                          "ValveRoiBottomDistance": 25.0, "ValveRoiBottomScale": 45.0})

    if segmentation:
      # Leaflet volume: snapshot of the analyzed frame (as ValveSegmentation creates it)
      leafletVolumeNode = slicer.modules.volumes.logic().CloneVolume(
        self.volumeNode, slicer.mrmlScene.GetUniqueNameByString(f"{heartValveNode.GetName()}-segmented"))
      valveModel.setLeafletVolumeNode(leafletVolumeNode)
      segmentationNode = valveModel.getLeafletSegmentationNode()
      segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(self.volumeNode)
      center = np.mean(np.array(contourPoints), axis=0)
      planePosition, planeNormal = valveModel.getAnnulusContourPlane()
      inPlane = np.cross(planeNormal, [0.0, 0.0, 1.0])
      inPlane = inPlane / np.linalg.norm(inPlane)
      inPlane2 = np.cross(planeNormal, inPlane)
      colors = ((1.0, 0.5, 0.5), (0.5, 0.5, 1.0), (0.5, 1.0, 0.5))
      for leafletIndex, segmentName in enumerate(leafletNames):
        # Two leaflets on opposite sides of the annulus center (as before), more evenly around it
        angle = 2.0 * np.pi * leafletIndex / len(leafletNames)
        color = colors[leafletIndex % len(colors)]
        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(*(center + 5.0 * (np.cos(angle) * inPlane + np.sin(angle) * inPlane2)))
        sphere.SetRadius(5.0)
        sphere.SetPhiResolution(30)
        sphere.SetThetaResolution(30)
        sphere.Update()
        segmentId = segmentationNode.AddSegmentFromClosedSurfaceRepresentation(sphere.GetOutput(), segmentName, color)
        segmentationNode.GetSegmentation().GetSegment(segmentId).SetTag("SegmentName", segmentName)
      segmentationNode.CreateBinaryLabelmapRepresentation()
      segmentationNode.GetSegmentation().SetSourceRepresentationName("Binary labelmap") \
        if hasattr(segmentationNode.GetSegmentation(), "SetSourceRepresentationName") else None
      valveModel.updateLeafletModelsFromSegmentation()
      if leaflets:
        for leafletModel in valveModel.leafletModels:
          try:
            leafletModel.autoDetectSurfaceBoundary(planePosition, planeNormal, numberOfBoundaryMarkups=12)
            leafletModel.updateSurface()
          except Exception:
            record["problems"].append(f"leaflet surface {leafletModel.segmentId}: {traceback.format_exc(limit=2)}")

    if coaptation:
      try:
        valveModel.updateCoaptationModels()
        coaptationModel = valveModel.addCoaptationModel()
        center = np.mean(np.array(contourPoints), axis=0)
        planePosition, planeNormal = valveModel.getAnnulusContourPlane()
        direction = np.cross(planeNormal, [1.0, 0.0, 0.0])
        direction = direction / np.linalg.norm(direction)
        for markupsNode, depth in ((coaptationModel.getBaseLineMarkupNode(), 0.0),
                                   (coaptationModel.getMarginLineMarkupNode(), 4.0)):
          markupsNode.SetLocked(False)
          markupsNode.RemoveAllControlPoints()
          for t in (-6.0, -3.0, 0.0, 3.0, 6.0):
            markupsNode.AddControlPoint(vtk.vtkVector3d(center + t * direction - depth * np.array(planeNormal)))
        coaptationModel.updateSurface()
      except Exception:
        record["problems"].append(f"coaptation: {traceback.format_exc(limit=3)}")

    if papillary:
      try:
        valveModel.updatePapillaryModels()
        planePosition, planeNormal = valveModel.getAnnulusContourPlane()
        for muscleIndex, papillaryModel in enumerate(valveModel.papillaryModels):
          markupsNode = papillaryModel.getPapillaryLineMarkupNode()
          markupsNode.SetLocked(False)
          markupsNode.RemoveAllControlPoints()
          numberOfMuscles = len(valveModel.papillaryModels)
          start = np.array(contourPoints[(muscleIndex * 2 + 1) * len(contourPoints) // (2 * numberOfMuscles)])
          for depth in (5.0, 12.0, 20.0):
            markupsNode.AddControlPoint(vtk.vtkVector3d(start - depth * np.array(planeNormal)))
          papillaryModel.updateModel()
      except Exception:
        record["problems"].append(f"papillary: {traceback.format_exc(limit=3)}")

    valveModel.updateValveNodeNames()
    self.valves.append(record)
    return record

  def addMeasurement(self, presetId, valveRecordsByInputId, key):
    import ValveQuantification
    logic = ValveQuantification.ValveQuantificationLogic()
    measurementNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode")
    measurementNode.SetHideFromEditors(False)
    measurementNode.SetAttribute("ModuleName", "HeartValveMeasurement")
    measurementNode.SetAttribute("MeasurementPreset", presetId)
    measurementNode.SetName(slicer.mrmlScene.GetUniqueNameByString(f"{presetId}Measurement"))
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    shNode.RequestOwnerPluginSearch(measurementNode)
    shNode.SetItemAttribute(shNode.GetItemByDataNode(measurementNode), "ModuleName", "HeartValveMeasurement")
    for inputValveId, valveRecord in valveRecordsByInputId.items():
      measurementNode.SetNodeReferenceID("Valve" + inputValveId, valveRecord["node"].GetID())
    messages = []
    try:
      messages = logic.computeMetrics(measurementNode) or []
    except Exception:
      messages = [f"EXCEPTION: {traceback.format_exc(limit=4)}"]
    record = {"node": measurementNode, "key": key, "preset": presetId, "messages": [str(m) for m in messages],
              "inputs": {inputValveId: (valveRecord["valveType"], valveRecord["phase"], valveRecord["frameIndex"])
                         for inputValveId, valveRecord in valveRecordsByInputId.items()}}
    self.measurements.append(record)
    return record

  def reference(self):
    """Reference values of all valves and measurements, as stored in the scene by the master code."""
    result = {"valves": [], "measurements": []}
    for record in self.valves:
      valveModel = record["valveModel"]
      heartValveNode = record["node"]
      entry = {
        "name": heartValveNode.GetName(),
        "valveType": record["valveType"],
        "phase": record["phase"],
        "frameIndex": record["frameIndex"],
        "indexValue": self.volumeSequenceNode.GetNthIndexValue(record["frameIndex"]),
        "annulusContourPoints": markupsPoints(valveModel.getAnnulusContourMarkupNode()),
        "annulusLabels": markupsLabels(valveModel.getAnnulusLabelsMarkupNode()),
        "annulusContourRadius": valveModel.getAnnulusContourRadius(),
        "probePosition": valveModel.getProbePosition(),
        "roi": valveModel.valveRoi.getRoiGeometry() if valveModel.getValveRoiModelNode() else None,
        "roiModelPoints": (valveModel.getValveRoiModelNode().GetPolyData().GetNumberOfPoints()
                           if valveModel.getValveRoiModelNode() and valveModel.getValveRoiModelNode().GetPolyData() else 0),
        "segments": segmentInfo(valveModel.getLeafletSegmentationNode()),
        "leafletVolumeVoxels": (int(np.count_nonzero(slicer.util.arrayFromVolume(valveModel.getLeafletVolumeNode())))
                                if valveModel.getLeafletVolumeNode() else None),
        "leaflets": {leafletModel.segmentId: {
          "boundaryPoints": markupsPoints(leafletModel.getSurfaceBoundaryMarkupNode()),
          "surfacePoints": (leafletModel.surfaceModelNode.GetPolyData().GetNumberOfPoints()
                            if leafletModel.surfaceModelNode and leafletModel.surfaceModelNode.GetPolyData() else 0),
        } for leafletModel in valveModel.leafletModels},
        "coaptations": [{
          "baseLine": markupsPoints(coaptationModel.getBaseLineMarkupNode()),
          "marginLine": markupsPoints(coaptationModel.getMarginLineMarkupNode()),
          "surfacePoints": (coaptationModel.surfaceModelNode.GetPolyData().GetNumberOfPoints()
                            if coaptationModel.surfaceModelNode and coaptationModel.surfaceModelNode.GetPolyData() else 0),
        } for coaptationModel in valveModel.coaptationModels],
        "papillary": {papillaryModel.getName(): markupsPoints(papillaryModel.getPapillaryLineMarkupNode())
                      for papillaryModel in valveModel.papillaryModels},
        "problems": record["problems"],
      }
      result["valves"].append(entry)
    for record in self.measurements:
      result["measurements"].append({
        "name": record["node"].GetName(),
        "key": record["key"],
        "preset": record["preset"],
        "inputs": record["inputs"],
        "messages": record["messages"],
        "results": tableRows(measurementResultsTable(record["node"])),
      })
    return result


def buildScenario(name):
  builder = MasterSceneBuilder()
  contour5, contour24 = MITRAL_CONTOUR_FRAME5, MITRAL_CONTOUR_FRAME24
  # A third anatomically plausible contour: the frame 5 contour shrunk towards its centroid
  center = np.mean(np.array(contour5), axis=0)
  contour14 = [list(center + 0.9 * (np.array(p) - center)) for p in contour5]

  if name == "mitral_three_phases":
    # The common legacy case: one valve analyzed at several cardiac phases, fully annotated,
    # with per-phase measurements and a phase comparison.
    ms = builder.addValve("mitral", "mid-systole", 5, contour5)
    es = builder.addValve("mitral", "end-systole", 14, contour14)
    ed = builder.addValve("mitral", "end-diastole", 24, contour24)
    for valve in (ms, es, ed):
      builder.addMeasurement("MitralValve", {"MitralValve": valve}, key=f"MitralValve-{valve['phase']}")
      builder.addMeasurement("GenericValve", {"Valve": valve}, key=f"GenericValve-{valve['phase']}")
    builder.addMeasurement("PhaseCompare", {"Valve1": ms, "Valve2": es, "Valve4": ed}, key="PhaseCompare")

  elif name == "two_valves_custom_phases":
    # Two valve types on one volume, custom and unknown phases, and a measurement referencing
    # two valves (mitral + aortic), which is what JolleyLab/SlicerHeartPrivate#308 was about.
    mitralMs = builder.addValve("mitral", "mid-systole", 5, contour5, papillary=False)
    mitralP1 = builder.addValve("mitral", "custom1", 24, contour24, coaptation=False, papillary=False)
    aorticMs = builder.addValve("aortic", "mid-systole", 5, [list(np.array(p) + [0, 0, 12]) for p in contour5],
                                segmentation=False, coaptation=False, papillary=False, labels=("R", "L", "N"))
    aorticUn = builder.addValve("aortic", "unknown", 24, [list(np.array(p) + [0, 0, 12]) for p in contour24],
                                segmentation=False, coaptation=False, papillary=False, labels=("R", "L", "N"))
    builder.addMeasurement("MitralValve", {"MitralValve": mitralMs, "AorticValve": aorticMs}, key="MitralValve-MS")
    builder.addMeasurement("MitralValve", {"MitralValve": mitralP1, "AorticValve": aorticUn}, key="MitralValve-P1")
    builder.addMeasurement("GenericValve", {"Valve": aorticUn}, key="GenericValve-aortic-UN")

  elif name == "three_valves_three_phases":
    # Mitral, tricuspid and aortic valves, each analyzed at the same three cardiac phases in one
    # scene, with leaflet segmentations for all three, per-phase measurements (including a
    # measurement referencing two valves) and phase comparisons.
    # The tricuspid and aortic contours are the mitral contours moved (and the aortic one shrunk)
    # to other positions within the volume; they are not anatomical.
    phases = (("mid-systole", 5, contour5), ("end-systole", 14, contour14), ("end-diastole", 24, contour24))

    def moved(contour, offset, scale=1.0):
      contourCenter = np.mean(np.array(contour), axis=0)
      return [list(contourCenter + scale * (np.array(p) - contourCenter) + offset) for p in contour]

    valves = {}
    for phase, frameIndex, contour in phases:
      valves[("mitral", phase)] = builder.addValve("mitral", phase, frameIndex, contour)
      valves[("tricuspid", phase)] = builder.addValve(
        "tricuspid", phase, frameIndex, moved(contour, [-45.0, 5.0, 0.0]), labels=("A", "P", "S", "L"),
        leafletNames=("anterior leaflet", "posterior leaflet", "septal leaflet"))
      valves[("aortic", phase)] = builder.addValve(
        "aortic", phase, frameIndex, moved(contour, [0.0, 30.0, 20.0], scale=0.7), coaptation=False,
        papillary=False, labels=("R", "L", "N"),
        leafletNames=("right coronary leaflet", "left coronary leaflet", "non-coronary leaflet"))
    for phase, frameIndex, contour in phases:
      builder.addMeasurement("MitralValve", {"MitralValve": valves[("mitral", phase)],
                                             "AorticValve": valves[("aortic", phase)]}, key=f"MitralValve-{phase}")
      builder.addMeasurement("TricuspidValve", {"TricuspidValve": valves[("tricuspid", phase)]},
                             key=f"TricuspidValve-{phase}")
      builder.addMeasurement("GenericValve", {"Valve": valves[("aortic", phase)]}, key=f"GenericValve-aortic-{phase}")
    for valveType in ("mitral", "tricuspid"):
      builder.addMeasurement("PhaseCompare", {"Valve1": valves[(valveType, "mid-systole")],
                                              "Valve2": valves[(valveType, "end-systole")],
                                              "Valve4": valves[(valveType, "end-diastole")]},
                             key=f"PhaseCompare-{valveType}")

  elif name == "single_phase_minimal":
    # Contour and labels only (no ROI/segmentation), a single phase: the minimal legacy valve.
    valve = builder.addValve("tricuspid", "end-diastole", 24, contour24, roi=False, segmentation=False,
                             coaptation=False, papillary=False, labels=("A", "P", "S", "L"))
    builder.addMeasurement("GenericValve", {"Valve": valve}, key="GenericValve-ED")

  else:
    raise ValueError(name)
  return builder


SCENARIOS = ["mitral_three_phases", "two_valves_custom_phases", "three_valves_three_phases", "single_phase_minimal"]

log = {"errors": []}
try:
  waitForModules(["ValveAnnulusAnalysis", "ValveQuantification", "ValveSegmentation"])
  os.makedirs(OUTPUT_DIR, exist_ok=True)
  for scenario in SCENARIOS:
    try:
      slicer.mrmlScene.Clear(0)
      builder = buildScenario(scenario)
      reference = builder.reference()
      reference["scenario"] = scenario
      with open(os.path.join(OUTPUT_DIR, f"{scenario}.json"), "w") as f:
        json.dump(reference, f, indent=1)
      if not slicer.util.saveScene(os.path.join(OUTPUT_DIR, f"{scenario}.mrb")):
        log["errors"].append(f"{scenario}: saving the scene failed")
      print(f"[master] {scenario} done", flush=True)
    except Exception:
      log["errors"].append(f"{scenario}: {traceback.format_exc()}")
except Exception:
  log["errors"].append(traceback.format_exc())

with open(os.path.join(OUTPUT_DIR, "generate-log.json"), "w") as f:
  json.dump(log, f, indent=1)
slicer.app.exit(0)
