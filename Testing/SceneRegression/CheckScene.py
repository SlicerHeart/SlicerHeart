"""Check one real SlicerHeart scene: load, convert to the sequence format, verify, save, reload, recompute.

Runs inside Slicer, started by run_scene_regression.py (one Slicer process per scene):

  Slicer.exe --no-splash --testing --no-main-window --additional-module-paths <modules>
      --python-script CheckScene.py -- <scene.mrb> <outdir> [--no-recompute]

Writes <outdir>/<scene>-result.json (checks, warnings, errors, inventories, recomputed metric values)
and <outdir>/<short scene name>-converted/ (the converted scene). The checks are generic: they do not
need to know the scene. run_scene_regression.py compares the result with the baseline of the scene.
Slicer always exits with code 0; a crash is detected by the missing result file.
"""
import hashlib
import json
import logging
import os
import shutil
import sys
import time
import traceback

import numpy as np
import slicer
import vtk

args = [a for a in sys.argv[1:] if a != "--"]
SCENE_PATH = args[0]
OUT_DIR = args[1]
RECOMPUTE = "--no-recompute" not in args[2:]
SCENE_NAME = os.path.splitext(os.path.basename(SCENE_PATH))[0]
os.makedirs(OUT_DIR, exist_ok=True)

result = {"scene": SCENE_NAME, "checks": [], "warnings": [], "errors": [], "timing": {}, "info": {}}


class LogCapture(logging.Handler):
  def __init__(self):
    super().__init__(level=logging.WARNING)
    self.records = []

  def emit(self, record):
    self.records.append((record.levelname, record.getMessage()[:400]))


logCapture = LogCapture()
logging.getLogger().addHandler(logCapture)


def pump(count=5):
  for _ in range(count):
    slicer.app.processEvents()


def check(context, name, ok, detail=""):
  result["checks"].append({"context": context, "check": name, "ok": bool(ok), "detail": str(detail)[:600]})
  print(f"[{'ok  ' if ok else 'FAIL'}] {context}: {name}" + (f" -- {detail}" if (detail and not ok) else ""), flush=True)
  return bool(ok)


def waitForModules(names, timeoutSec=180):
  start = time.time()
  while time.time() - start < timeoutSec:
    if all(hasattr(slicer.modules, name.lower()) for name in names):
      return
    pump(1)
    time.sleep(0.1)
  raise RuntimeError(f"Modules not loaded: {names}")


def shortSceneDirName():
  """Directory name for the converted scene: short, because the Windows path length limit breaks
  saving scenes with long node names into deep folders."""
  digest = hashlib.md5(SCENE_NAME.encode("utf-8")).hexdigest()[:4]
  return f"{SCENE_NAME[:20].rstrip(' ._-')}-{digest}-converted"


def nodeAttrs(node):
  return {k: node.GetAttribute(k) for k in node.GetAttributeNames()}


def markupsCount(node):
  return node.GetNumberOfControlPoints() if node and node.IsA("vtkMRMLMarkupsNode") else None


def segmentSummary(segNode):
  """{segmentName: nonEmpty} for a segmentation node (cheap: scalar range of the labelmap)."""
  if not segNode:
    return None
  seg = segNode.GetSegmentation()
  out = {}
  for i in range(seg.GetNumberOfSegments()):
    sid = seg.GetNthSegmentID(i)
    img = slicer.vtkOrientedImageData()
    try:
      segNode.GetBinaryLabelmapRepresentation(sid, img)
      nonEmpty = bool(img.GetPointData().GetScalars()) and img.GetScalarRange()[1] > 0
    except Exception:
      nonEmpty = None
    out[seg.GetSegment(sid).GetName()] = nonEmpty
  return out


def childTables(node):
  """Table nodes referenced by, or under (SH), a measurement node."""
  tables = []
  roles = []
  node.GetNodeReferenceRoles(roles)
  for role in roles:
    for i in range(node.GetNumberOfNodeReferences(role)):
      ref = node.GetNthNodeReference(role, i)
      if ref and ref.IsA("vtkMRMLTableNode"):
        tables.append(ref)
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  item = shNode.GetItemByDataNode(node)
  if item:
    children = vtk.vtkIdList()
    shNode.GetItemChildren(item, children, True)
    for i in range(children.GetNumberOfIds()):
      n = shNode.GetItemDataNode(children.GetId(i))
      if n and n.IsA("vtkMRMLTableNode") and n not in tables:
        tables.append(n)
  return tables


def tableRows(tableNode):
  rows = {}
  if not tableNode or tableNode.GetNumberOfColumns() < 2:
    return rows
  for r in range(tableNode.GetNumberOfRows()):
    rows[tableNode.GetCellText(r, 0)] = tableNode.GetCellText(r, 1)
  return rows


def valveRefs(measurementNode):
  """{role: referencedNode} for all Valve* roles."""
  out = {}
  roles = []
  measurementNode.GetNodeReferenceRoles(roles)
  for role in roles:
    if role.startswith("Valve"):
      out[role] = measurementNode.GetNodeReference(role)
  return out


def scriptedNodes(moduleName):
  return [n for n in slicer.util.getNodesByClass("vtkMRMLScriptedModuleNode") if n.GetAttribute("ModuleName") == moduleName]


# ---------------------------------------------------------------- legacy inventory

def legacyInventory():
  seqLogic = slicer.modules.sequences.logic()
  inv = {"valves": [], "measurements": []}
  for hv in scriptedNodes("HeartValve"):
    if seqLogic.GetFirstBrowserNodeForProxyNode(hv):
      continue
    a = nodeAttrs(hv)
    volume = hv.GetNodeReference("ValveVolume")
    entry = {
      "name": hv.GetName(), "id": hv.GetID(),
      "valveType": a.get("ValveType"), "phase": a.get("CardiacCyclePhase"),
      "frameIndex": a.get("ValveVolumeSequenceIndex"), "probe": a.get("ProbePosition"),
      "volume": volume.GetName() if volume else None,
      "annulusPoints": markupsCount(hv.GetNodeReference("AnnulusContourPoints")),
      "annulusClass": hv.GetNodeReference("AnnulusContourPoints").GetClassName() if hv.GetNodeReference("AnnulusContourPoints") else None,
      "labels": markupsCount(hv.GetNodeReference("AnnulusLabelsPoints")),
      "segments": segmentSummary(hv.GetNodeReference("LeafletSegmentation")),
      "leafletSurfaces": hv.GetNumberOfNodeReferences("LeafletSurfaceModel"),
      "coaptations": hv.GetNumberOfNodeReferences("CoaptationBaseLineMarkup"),
      "papillary": hv.GetNumberOfNodeReferences("PapillaryLineMarkup"),
      "roi": bool(hv.GetNodeReference("ValveRoiModel")),
    }
    inv["valves"].append(entry)
  byId = {v["id"]: v for v in inv["valves"]}
  for m in scriptedNodes("HeartValveMeasurement"):
    if seqLogic.GetFirstBrowserNodeForProxyNode(m):
      continue
    refs = {}
    for role, node in valveRefs(m).items():
      if node is None:
        refs[role] = None
      elif node.GetID() in byId:
        v = byId[node.GetID()]
        refs[role] = (v["valveType"], v["frameIndex"])
      else:
        refs[role] = ("<non-legacy>", node.GetName())
    inv["measurements"].append({
      "name": m.GetName(), "preset": m.GetAttribute("MeasurementPreset"), "refs": refs,
      "tables": [len(tableRows(t)) for t in childTables(m)],
    })
  return inv


# ---------------------------------------------------------------- converted inventory

def valveBrowserNodes():
  return [b for b in slicer.util.getNodesByClass("vtkMRMLSequenceBrowserNode") if b.GetAttribute("ModuleName") == "HeartValve"]


def convertedInventory(context):
  import HeartValveLib.HeartValves as HV
  seqLogic = slicer.modules.sequences.logic()
  shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
  inv = {"browsers": [], "legacyValvesLeft": [], "measurementProxies": []}
  for hv in scriptedNodes("HeartValve"):
    if not seqLogic.GetFirstBrowserNodeForProxyNode(hv):
      inv["legacyValvesLeft"].append(hv.GetName())
  for browserNode in valveBrowserNodes():
    try:
      valveBrowser = HV.getValveBrowser(browserNode)
    except Exception:
      result["errors"].append(f"{context}: getValveBrowser({browserNode.GetName()}) raised:\n{traceback.format_exc()[-800:]}")
      continue
    master = browserNode.GetMasterSequenceNode()
    b = {"name": browserNode.GetName(), "valveType": browserNode.GetAttribute("ValveType"),
         "numItems": browserNode.GetNumberOfItems(), "timePoints": []}
    # measurement proxies synchronized by this browser
    seqNodes = vtk.vtkCollection()
    browserNode.GetSynchronizedSequenceNodes(seqNodes, True)
    measurementSeqs = []
    for i in range(seqNodes.GetNumberOfItems()):
      s = seqNodes.GetItemAsObject(i)
      p = browserNode.GetProxyNode(s)
      # The proxy is a blank default node at time points without an item when the sequence uses
      # MissingItemSetToDefault/CreateFromDefault, so identify measurement sequences by their data nodes.
      d0 = s.GetNthDataNode(0) if s.GetNumberOfDataNodes() else None
      if p and ((d0 and d0.GetAttribute("ModuleName") == "HeartValveMeasurement") or p.GetAttribute("ModuleName") == "HeartValveMeasurement"):
        measurementSeqs.append((s, p))
    for itemNumber in range(browserNode.GetNumberOfItems()):
      browserNode.SetSelectedItemNumber(itemNumber)
      pump()
      indexValue = master.GetNthIndexValue(itemNumber)
      tp = {"item": itemNumber, "indexValue": indexValue}
      try:
        valveModel = valveBrowser.valveModel
        tp["phase"] = valveModel.getCardiacCyclePhase()
        tp["frameIndex"] = valveModel.getValveVolumeSequenceIndex()
        tp["probe"] = valveBrowser.probePosition
        tp["annulusPoints"] = markupsCount(valveModel.annulusContourCurveNode)
        tp["annulusClass"] = valveModel.annulusContourCurveNode.GetClassName() if valveModel.annulusContourCurveNode else None
        tp["labels"] = markupsCount(valveModel.valveLabelsNode)
        tp["segments"] = segmentSummary(valveModel.leafletSegmentationNode)
        tp["leafletSurfaces"] = valveBrowser.heartValveNode.GetNumberOfNodeReferences("LeafletSurfaceModel")
        tp["coaptations"] = valveBrowser.heartValveNode.GetNumberOfNodeReferences("CoaptationBaseLineMarkup")
        tp["papillary"] = valveBrowser.heartValveNode.GetNumberOfNodeReferences("PapillaryLineMarkup")
        tp["roi"] = valveModel.valveRoiModelNode is not None
        volumeNode = valveBrowser.valveVolumeNode
        tp["volume"] = volumeNode.GetName() if volumeNode else None
        tp["volumeHasImage"] = bool(volumeNode and volumeNode.GetImageData() and volumeNode.GetImageData().GetNumberOfPoints() > 0)
      except Exception:
        tp["error"] = traceback.format_exc()[-800:]
        result["errors"].append(f"{context}: {browserNode.GetName()} item {itemNumber}: {tp['error']}")
      # measurements present at this index value
      tp["measurements"] = []
      for s, p in measurementSeqs:
        if s.GetItemNumberFromIndexValue(indexValue) < 0:
          continue
        if p.GetAttribute("ModuleName") != "HeartValveMeasurement":
          result["warnings"].append(f"{context}: {browserNode.GetName()} item {itemNumber}: proxy of {s.GetName()} has no ModuleName attribute although the sequence has an item here")
        refs = {}
        for role, node in valveRefs(p).items():
          if node is None:
            refs[role] = None
          else:
            owner = seqLogic.GetFirstBrowserNodeForProxyNode(node)
            refs[role] = (owner.GetAttribute("ValveType") if owner else "<no browser>", node.GetName())
        tp["measurements"].append({
          "proxy": p.GetName(), "sequence": s.GetName(), "preset": p.GetAttribute("MeasurementPreset"),
          "missingItemMode": browserNode.GetMissingItemMode(s),
          "refs": refs, "tables": [len(tableRows(t)) for t in childTables(p)],
          "shItem": bool(shNode.GetItemByDataNode(p)), "hidden": bool(p.GetHideFromEditors()),
        })
      b["timePoints"].append(tp)
    inv["browsers"].append(b)
  return inv


# ---------------------------------------------------------------- comparisons

def compareLegacyToConverted(legacy, conv):
  ctx = "legacy->converted"
  check(ctx, "no legacy valve nodes left", not conv["legacyValvesLeft"], conv["legacyValvesLeft"])
  # one browser per (valveType) -- legacy valves of same type on the same volume collapse into one browser
  legacyTypes = {}
  for v in legacy["valves"]:
    legacyTypes.setdefault(v["valveType"] or "Valve", []).append(v)
  for valveType, valves in legacyTypes.items():
    browsers = [b for b in conv["browsers"] if b["valveType"] == valveType]
    volumes = sorted({v["volume"] for v in valves})
    check(ctx, f"{valveType}: browser(s) created", len(browsers) >= 1, f"{len(browsers)} browsers for {len(valves)} legacy valves on volumes {volumes}")
    totalItems = sum(b["numItems"] for b in browsers)
    uniqueFrames = len({(v["volume"], v["frameIndex"]) for v in valves})
    check(ctx, f"{valveType}: time points == distinct legacy frames", totalItems == uniqueFrames,
          f"{totalItems} time points, {len(valves)} legacy valves at {uniqueFrames} distinct (volume, frame)")
    if uniqueFrames != len(valves):
      result["warnings"].append(f"{valveType}: {len(valves)} legacy valves but only {uniqueFrames} distinct frames (duplicates collapse)")
    # per legacy valve: find the time point
    tpsByFrame = {}
    for b in browsers:
      for tp in b["timePoints"]:
        tpsByFrame.setdefault(str(tp.get("frameIndex")), []).append(tp)
    for v in valves:
      vctx = f"{v['name']} ({valveType} frame {v['frameIndex']})"
      tps = tpsByFrame.get(str(v["frameIndex"]), [])
      if not check(vctx, "time point exists", len(tps) >= 1, f"frames available: {sorted(tpsByFrame)}"):
        continue
      tp = tps[0]
      if "error" in tp:
        check(vctx, "time point readable", False, tp["error"][-300:])
        continue
      check(vctx, "phase", tp["phase"] == v["phase"], f"{tp['phase']} vs legacy {v['phase']}")
      check(vctx, "annulus is a closed curve", tp["annulusClass"] == "vtkMRMLMarkupsClosedCurveNode", tp["annulusClass"])
      if v["annulusPoints"]:
        check(vctx, "annulus control points kept", tp["annulusPoints"] == v["annulusPoints"], f"{tp['annulusPoints']} vs legacy {v['annulusPoints']}")
      if v["labels"]:
        check(vctx, "annulus labels kept", tp["labels"] == v["labels"], f"{tp['labels']} vs legacy {v['labels']}")
      if v["segments"]:
        legacyNonEmpty = sorted(k for k, ne in v["segments"].items() if ne and k != "Annulus mask")
        convNonEmpty = sorted(k for k, ne in (tp["segments"] or {}).items() if ne and k != "Annulus mask")
        check(vctx, "non-empty leaflet segments kept", legacyNonEmpty == convNonEmpty, f"{convNonEmpty} vs legacy {legacyNonEmpty}")
      # Reference counts on the HeartValve proxy are shared by all time points and the sequence format
      # adds default nodes (one leaflet surface per segment, papillary muscles per valve type) and
      # de-duplicates stale references, so only a note is recorded when they differ.
      for key in ("leafletSurfaces", "coaptations", "papillary"):
        if v[key] and tp.get(key) != v[key]:
          result["warnings"].append(f"{vctx}: {key} references {v[key]} -> {tp.get(key)} after conversion")
      if v["roi"]:
        check(vctx, "ROI kept", tp.get("roi"), "no ROI model at time point")
      check(vctx, "volume frame has image data", tp.get("volumeHasImage"), tp.get("volume"))
  # measurements
  for m in legacy["measurements"]:
    mctx = f"measurement {m['name']} ({m['preset']})"
    refs = [r for r in m["refs"].values() if r and r[0] != "<non-legacy>"]
    if not refs:
      check(mctx, "legacy measurement references a legacy valve", False, m["refs"])
      continue
    found = []
    for valveType, frame in refs:
      for b in [b for b in conv["browsers"] if b["valveType"] == valveType]:
        for tp in b["timePoints"]:
          if str(tp.get("frameIndex")) == str(frame):
            found += [mm for mm in tp["measurements"] if mm["preset"] == m["preset"]]
    if not check(mctx, "converted measurement at its time point", len(found) >= 1, f"{len(found)} '{m['preset']}' proxies at {refs}"):
      continue
    mm = found[0]
    for role, legacyRef in m["refs"].items():
      if legacyRef is None or legacyRef[0] == "<non-legacy>":
        continue
      got = mm["refs"].get(role)
      check(mctx, f"valve reference {role} points at {legacyRef[0]} browser proxy", got is not None and got[0] == legacyRef[0], f"got {got}")
    check(mctx, "results tables kept", sum(mm["tables"]) >= sum(m["tables"]), f"rows {mm['tables']} vs legacy {m['tables']}")
    if sorted(mm["tables"]) != sorted(m["tables"]):
      result["warnings"].append(f"{mctx}: results table rows legacy {m['tables']} -> converted {mm['tables']}")
    check(mctx, "measurement proxy in subject hierarchy", mm["shItem"], "no SH item")


def compareRoundTrip(before, after):
  ctx = "save/reload"
  check(ctx, "no legacy valve nodes after reload", not after["legacyValvesLeft"], after["legacyValvesLeft"])
  check(ctx, "same number of valve browsers", len(before["browsers"]) == len(after["browsers"]), f"{len(before['browsers'])} -> {len(after['browsers'])}")
  afterByType = {}
  for b in after["browsers"]:
    afterByType.setdefault(b["valveType"], []).append(b)
  for b in before["browsers"]:
    cands = afterByType.get(b["valveType"], [])
    cand = next((c for c in cands if c["numItems"] == b["numItems"]), cands[0] if cands else None)
    bctx = f"{ctx} / {b['name']}"
    if not check(bctx, "browser present after reload", cand is not None, "missing"):
      continue
    check(bctx, "time point count kept", cand["numItems"] == b["numItems"], f"{b['numItems']} -> {cand['numItems']}")
    identical = True
    for tpB, tpA in zip(b["timePoints"], cand["timePoints"]):
      tctx = f"{bctx} item {tpB['item']}"
      for key in ("phase", "frameIndex", "annulusPoints", "labels", "leafletSurfaces", "coaptations", "papillary", "roi", "volumeHasImage"):
        if tpB.get(key) != tpA.get(key):
          identical = check(tctx, f"{key} kept", False, f"{tpB.get(key)} -> {tpA.get(key)}") and identical
      sb = sorted(k for k, ne in (tpB.get("segments") or {}).items() if ne)
      sa = sorted(k for k, ne in (tpA.get("segments") or {}).items() if ne)
      if sb != sa:
        identical = check(tctx, "non-empty segments kept", False, f"{sb} -> {sa}") and identical
      mb = sorted((m["preset"], tuple(sorted(m["tables"]))) for m in tpB["measurements"])
      ma = sorted((m["preset"], tuple(sorted(m["tables"]))) for m in tpA["measurements"])
      if mb != ma:
        identical = check(tctx, "measurements kept", False, f"{mb} -> {ma}") and identical
      for m in tpA["measurements"]:
        bad = [role for role, r in m["refs"].items() if r is None or r[0] == "<no browser>"]
        if bad:
          identical = check(tctx, f"measurement {m['preset']} valve references resolve after reload", False, f"unresolved {bad}: {m['refs']}") and identical
    check(bctx, "time points identical after reload", identical)


def recomputeMeasurements():
  """Recompute each measurement proxy at each of its time points. The recomputed values are recorded
  for the baseline comparison; the comparison with the tables stored in the scene is informational
  only, because stored values are often stale (annulus edited after measuring, older algorithms)."""
  import ValveQuantification
  logic = ValveQuantification.ValveQuantificationLogic()
  recompute = result["info"].setdefault("recompute", [])
  for browserNode in valveBrowserNodes():
    master = browserNode.GetMasterSequenceNode()
    seqNodes = vtk.vtkCollection()
    browserNode.GetSynchronizedSequenceNodes(seqNodes, True)
    for i in range(seqNodes.GetNumberOfItems()):
      s = seqNodes.GetItemAsObject(i)
      p = browserNode.GetProxyNode(s)
      if not (p and p.GetAttribute("ModuleName") == "HeartValveMeasurement"):
        continue
      for item in range(s.GetNumberOfDataNodes()):
        indexValue = s.GetNthIndexValue(item)
        itemNumber = master.GetItemNumberFromIndexValue(indexValue)
        if itemNumber < 0:
          continue
        browserNode.SetSelectedItemNumber(itemNumber)
        pump()
        key = f"{browserNode.GetAttribute('ValveType')} / {p.GetName()} @ {indexValue}"
        mctx = f"recompute {key}"
        stored = {}
        for t in childTables(p):
          stored.update(tableRows(t))
        t0 = time.time()
        try:
          messages = logic.computeMetrics(p) or []
          ok = True
          detail = ""
        except Exception:
          ok = False
          messages = []
          detail = traceback.format_exc()[-600:]
        pump()
        check(mctx, "computeMetrics ran", ok, detail)
        recomputed = {}
        if ok:
          for t in childTables(p):
            recomputed.update(tableRows(t))
        diffs = []
        missing = []
        for name, val in stored.items():
          if name not in recomputed:
            missing.append(name)
            continue
          try:
            a, b = float(val), float(recomputed[name])
          except ValueError:
            if val != recomputed[name]:
              diffs.append((name, val, recomputed[name]))
            continue
          if not np.isclose(a, b, rtol=1e-3, atol=1e-3):
            diffs.append((name, a, b))
        recompute.append({
          "key": key, "measurement": p.GetName(), "preset": p.GetAttribute("MeasurementPreset"),
          "indexValue": indexValue, "seconds": round(time.time() - t0, 1), "ok": ok,
          "values": recomputed, "stored": stored,
          "storedMissing": missing, "storedDiffs": diffs,
          "messages": [str(m)[:200] for m in messages][:20]})
        if ok:
          check(mctx, "all stored metrics recomputed", not missing, f"missing: {missing[:10]}")
          if diffs:
            result["warnings"].append(f"{mctx}: {len(diffs)} recomputed values differ from the stored table: {diffs[:5]}")


# ---------------------------------------------------------------- main

try:
  waitForModules(["ValveAnnulusAnalysis", "ValveQuantification", "Converter4DSequences"])
  import Converter4DSequences
  C = Converter4DSequences.Converter4DSequences
  logic = Converter4DSequences.Converter4DSequencesLogic()
  with C.suspendAutoConvert():
    t0 = time.time()
    slicer.mrmlScene.Clear(0)
    try:
      ok = slicer.util.loadScene(SCENE_PATH)
      loadError = ""
    except Exception as e:
      ok = False
      loadError = str(e)[-300:]
    pump()
    result["timing"]["load"] = round(time.time() - t0, 1)
    nValves = len(scriptedNodes("HeartValve"))
    check("load", "scene loaded (HeartValve nodes present)", nValves > 0, f"loadScene ok={ok} {loadError}; {nValves} HeartValve nodes")
    if not ok:
      result["warnings"].append(f"loadScene reported failure: {loadError}")
    legacy = legacyInventory()
    result["info"]["legacy"] = legacy
    convertible = logic.sceneHasConvertibleNodes()
    result["info"]["convertible"] = convertible
    print(f"[info] {SCENE_NAME}: {len(legacy['valves'])} legacy valves, {len(legacy['measurements'])} legacy measurements, "
          f"{len(valveBrowserNodes())} valve browsers before conversion, convertible={convertible}", flush=True)
    warningsBefore = len(logCapture.records)
    t0 = time.time()
    try:
      logic.performFullConversion(showMessage=False, interactive=False)
      convertedOk = True
      convertErr = ""
    except Exception:
      convertedOk = False
      convertErr = traceback.format_exc()[-1500:]
    pump()
    result["timing"]["convert"] = round(time.time() - t0, 1)
    check("convert", "conversion ran without exception", convertedOk, convertErr)
    result["info"]["conversionLog"] = logCapture.records[warningsBefore:]
    check("convert", "nothing left to convert", not logic.sceneHasConvertibleNodes())
    conv = convertedInventory("converted")
    result["info"]["converted"] = conv
    print(f"[info] {SCENE_NAME}: after conversion {len(conv['browsers'])} valve browsers: "
          + ", ".join(f"{b['valveType']}x{b['numItems']}" for b in conv["browsers"]), flush=True)
    if legacy["valves"] or legacy["measurements"]:
      compareLegacyToConverted(legacy, conv)
    # ---- save and reload
    outScene = os.path.join(OUT_DIR, shortSceneDirName())
    shutil.rmtree(outScene, ignore_errors=True)
    os.makedirs(outScene)
    t0 = time.time()
    saved = slicer.util.saveScene(outScene)
    result["timing"]["save"] = round(time.time() - t0, 1)
    check("save", "converted scene saved", saved, outScene)
    if saved:
      slicer.mrmlScene.Clear(0)
      t0 = time.time()
      mrml = [f for f in os.listdir(outScene) if f.endswith(".mrml")][0]
      ok = slicer.util.loadScene(os.path.join(outScene, mrml))
      pump()
      result["timing"]["reload"] = round(time.time() - t0, 1)
      result["info"]["reloadReturnValue"] = bool(ok)
      check("reload", "converted scene reloaded", len(valveBrowserNodes()) > 0,
            f"loadScene returned {ok}, {len(valveBrowserNodes())} valve browsers")
      check("reload", "reloaded scene has nothing to convert", not logic.sceneHasConvertibleNodes())
      conv2 = convertedInventory("reloaded")
      result["info"]["reloaded"] = conv2
      compareRoundTrip(conv, conv2)
      if RECOMPUTE:
        t0 = time.time()
        recomputeMeasurements()
        result["timing"]["recompute"] = round(time.time() - t0, 1)
except Exception:
  result["errors"].append(traceback.format_exc())
  check("script", "script completed", False, traceback.format_exc()[-800:])

result["log"] = logCapture.records
passed = sum(c["ok"] for c in result["checks"])
failed = sum(not c["ok"] for c in result["checks"])
result["summary"] = {"passed": passed, "failed": failed, "errors": len(result["errors"]),
                     "warningsLogged": sum(1 for lvl, _ in logCapture.records if lvl == "WARNING"),
                     "errorsLogged": sum(1 for lvl, _ in logCapture.records if lvl in ("ERROR", "CRITICAL"))}
with open(os.path.join(OUT_DIR, f"{SCENE_NAME}-result.json"), "w") as f:
  json.dump(result, f, indent=1, default=str)
print(f"[summary] {SCENE_NAME}: {passed} passed, {failed} failed, timing {result['timing']}", flush=True)
slicer.util.exit(0)
