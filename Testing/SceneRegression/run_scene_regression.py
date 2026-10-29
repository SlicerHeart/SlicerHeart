#!/usr/bin/env python3
"""Regression check of real SlicerHeart scenes against recorded baselines.

Runs CheckScene.py in one Slicer process per .mrb file of a folder (sequentially, one Slicer at a
time), then compares each result with the baseline stored next to the scene
(<scene>.expected.json) and writes a report.

  python run_scene_regression.py --slicer <Slicer.exe> [--scenes-dir DIR] [options]

The scenes folder is --scenes-dir or the SLICERHEART_SCENES_DIR environment variable. The scenes are
not part of the repository (patient data). Without a usable folder the script exits with code 77,
which CTest reports as "skipped" (SKIP_RETURN_CODE).

Baselines: `--record` writes <scene>.expected.json from the results of this run (the currently
failing generic checks become allowed failures, the recomputed metric values become the reference).
Without --record every scene with a baseline fails when
  - a generic check fails that is not an allowed failure of the baseline,
  - an allowed failure passes now (stale baseline: re-record it),
  - a measurement of the baseline is missing, has other metric rows, or a value differs by more than
    the tolerance, or a measurement appears that the baseline does not know.
A scene without a baseline only has to pass the generic checks; a note asks to record it.

Exit code: 0 all scenes passed, 1 at least one scene failed (or Slicer crashed / timed out),
77 skipped (no scenes).
"""
import argparse
import datetime
import json
import math
import os
import subprocess
import sys
import time

SKIP_EXIT_CODE = 77
REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CheckScene.py")
# Modules loaded from the repository when --module-paths is not given (same list as MasterComparison)
REPO_MODULES = ["ValveAnnulusAnalysis", "ValveSegmentation", "ValveQuantification", "Converter4DSequences",
                "ValveBatchExport", "LeafletAnalysis", "ValvePapillaryAnalysis", "CardiacDeviceSimulator"]
RTOL = 1e-3
ATOL = 1e-3


def parseArgs():
  p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  p.add_argument("--slicer", required=True, help="Slicer launcher executable")
  p.add_argument("--scenes-dir", default=os.environ.get("SLICERHEART_SCENES_DIR"),
                 help="folder of .mrb scenes and their .expected.json baselines (default: $SLICERHEART_SCENES_DIR)")
  p.add_argument("--out-dir", help="results, logs and converted scenes (default: <scenes-dir>/_results)")
  p.add_argument("--module-paths", nargs="*", help="--additional-module-paths for Slicer (default: the modules of this repository)")
  p.add_argument("--launcher-settings", help="--launcher-additional-settings file of a build tree")
  p.add_argument("--scene", action="append", default=[], help="only this scene (file name without .mrb); repeatable")
  p.add_argument("--timeout", type=float, default=3600, help="seconds per scene (default 3600)")
  p.add_argument("--record", action="store_true", help="write/overwrite the baselines from this run")
  p.add_argument("--no-recompute", action="store_true", help="skip recomputing the measurements")
  p.add_argument("--compare-only", action="store_true", help="do not run Slicer, compare existing results in --out-dir")
  return p.parse_args()


# ---------------------------------------------------------------- running Slicer

def killProcessTree(proc):
  if sys.platform == "win32":
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
  else:
    proc.kill()


def runScene(args, scenePath, outDir):
  """Run CheckScene.py on one scene. Returns (exit code or None on timeout, seconds)."""
  modulePaths = args.module_paths or [os.path.join(REPO_DIR, m) for m in REPO_MODULES if os.path.isdir(os.path.join(REPO_DIR, m))]
  cmd = [args.slicer, "--no-splash", "--testing", "--no-main-window"]
  if args.launcher_settings:
    cmd += ["--launcher-additional-settings", args.launcher_settings]
  cmd += ["--additional-module-paths"] + modulePaths
  cmd += ["--python-script", CHECK_SCRIPT, "--", scenePath, outDir]
  if args.no_recompute:
    cmd.append("--no-recompute")
  sceneName = os.path.splitext(os.path.basename(scenePath))[0]
  logPath = os.path.join(outDir, f"{sceneName}.log")
  resultPath = os.path.join(outDir, f"{sceneName}-result.json")
  if os.path.exists(resultPath):
    os.remove(resultPath)
  start = time.time()
  with open(logPath, "w") as log:
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    try:
      exitCode = proc.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
      killProcessTree(proc)
      proc.wait()
      exitCode = None
  return exitCode, time.time() - start


# ---------------------------------------------------------------- comparing with the baseline

def checkKey(c):
  return f"{c['context']} :: {c['check']}"


def valuesEqual(a, b):
  try:
    x, y = float(a), float(b)
  except (TypeError, ValueError):
    return a == b
  if math.isnan(x) and math.isnan(y):
    return True
  return abs(x - y) <= ATOL + RTOL * abs(y)


def baselineFromResult(result, codeVersion):
  return {
    "version": 1,
    "recordedOn": datetime.date.today().isoformat(),
    "code": codeVersion,
    "summary": result["summary"],
    "timing": result["timing"],
    "allowedFailures": {checkKey(c): c["detail"] for c in result["checks"] if not c["ok"]},
    "recompute": {r["key"]: {"ok": r["ok"], "values": r["values"], "messages": r["messages"]}
                  for r in result["info"].get("recompute", [])},
  }


def compareWithBaseline(result, baseline):
  """List of failure strings; empty when the result matches the baseline."""
  failures = []
  allowed = baseline.get("allowedFailures", {})
  checks = {checkKey(c): c for c in result["checks"]}
  for key, c in checks.items():
    if not c["ok"] and key not in allowed:
      failures.append(f"check failed: {key} -- {c['detail']}")
  for key in allowed:
    if key in checks and checks[key]["ok"]:
      failures.append(f"stale baseline: '{key}' is an allowed failure but passes now (re-record with --record)")
  recomputed = {r["key"]: r for r in result["info"].get("recompute", [])}
  for key, ref in baseline.get("recompute", {}).items():
    got = recomputed.get(key)
    if got is None:
      failures.append(f"measurement missing: {key}")
      continue
    if ref["ok"] and not got["ok"]:
      failures.append(f"measurement no longer computes: {key}")
      continue
    refValues, gotValues = ref["values"], got["values"]
    missingRows = sorted(set(refValues) - set(gotValues))
    newRows = sorted(set(gotValues) - set(refValues))
    if missingRows:
      failures.append(f"{key}: metric rows missing: {missingRows[:10]}")
    if newRows:
      failures.append(f"{key}: new metric rows (re-record if intended): {newRows[:10]}")
    changed = [(name, refValues[name], gotValues[name]) for name in refValues if name in gotValues and not valuesEqual(gotValues[name], refValues[name])]
    if changed:
      failures.append(f"{key}: {len(changed)} values changed (baseline -> now): " + ", ".join(f"{n}: {a} -> {b}" for n, a, b in changed[:8]))
  for key in recomputed:
    if key not in baseline.get("recompute", {}):
      failures.append(f"new measurement not in baseline (re-record if intended): {key}")
  return failures


def codeVersion():
  try:
    return subprocess.check_output(["git", "-C", REPO_DIR, "describe", "--always", "--dirty"], text=True).strip()
  except Exception:
    return "unknown"


# ---------------------------------------------------------------- main

def main():
  args = parseArgs()
  if not args.scenes_dir or not os.path.isdir(args.scenes_dir):
    print(f"Scene regression skipped: no scenes folder ({args.scenes_dir!r}); set --scenes-dir or SLICERHEART_SCENES_DIR")
    return SKIP_EXIT_CODE
  scenes = sorted(f for f in os.listdir(args.scenes_dir) if f.lower().endswith(".mrb"))
  if args.scene:
    wanted = set(args.scene)
    scenes = [f for f in scenes if os.path.splitext(f)[0] in wanted]
    missing = wanted - {os.path.splitext(f)[0] for f in scenes}
    if missing:
      print(f"Scenes not found in {args.scenes_dir}: {sorted(missing)}")
      return 1
  if not scenes:
    print(f"Scene regression skipped: no .mrb files in {args.scenes_dir}")
    return SKIP_EXIT_CODE
  outDir = args.out_dir or os.path.join(args.scenes_dir, "_results")
  os.makedirs(outDir, exist_ok=True)
  version = codeVersion()
  print(f"Scene regression: {len(scenes)} scenes in {args.scenes_dir}, code {version}, results in {outDir}", flush=True)

  rows = []
  anyFailed = False
  for sceneFile in scenes:
    sceneName = os.path.splitext(sceneFile)[0]
    scenePath = os.path.join(args.scenes_dir, sceneFile)
    baselinePath = os.path.join(args.scenes_dir, f"{sceneName}.expected.json")
    resultPath = os.path.join(outDir, f"{sceneName}-result.json")
    row = {"scene": sceneName, "status": "", "passed": 0, "failed": 0, "seconds": 0.0, "failures": [], "notes": []}
    if not args.compare_only:
      print(f"=== {time.strftime('%H:%M:%S')} {sceneName}", flush=True)
      exitCode, seconds = runScene(args, scenePath, outDir)
      row["seconds"] = round(seconds)
      if exitCode is None:
        row["failures"].append(f"timeout after {args.timeout:.0f} s (Slicer killed)")
      elif exitCode != 0:
        row["notes"].append(f"Slicer exit code {exitCode}")
    if not os.path.exists(resultPath):
      row["failures"].append("no result file: Slicer crashed or was killed, see the log")
      row["status"] = "CRASH" if not row["failures"][0].startswith("timeout") else "TIMEOUT"
      anyFailed = True
      rows.append(row)
      print(f"[{row['status']}] {sceneName}: {row['failures'][0]}", flush=True)
      continue
    with open(resultPath) as f:
      result = json.load(f)
    row["passed"], row["failed"] = result["summary"]["passed"], result["summary"]["failed"]
    if args.compare_only:
      row["seconds"] = round(sum(result["timing"].values()))
    if args.record:
      with open(baselinePath, "w") as f:
        json.dump(baselineFromResult(result, version), f, indent=1)
      row["status"] = "RECORDED"
      if row["failed"]:
        row["notes"].append(f"{row['failed']} failing checks recorded as allowed failures")
    elif os.path.exists(baselinePath):
      with open(baselinePath) as f:
        baseline = json.load(f)
      row["failures"] += compareWithBaseline(result, baseline)
      row["status"] = "PASS" if not row["failures"] else "FAIL"
      row["notes"].append(f"baseline {baseline.get('recordedOn')} ({baseline.get('code')})")
    else:
      row["failures"] += [f"check failed: {checkKey(c)} -- {c['detail']}" for c in result["checks"] if not c["ok"]]
      row["status"] = "PASS" if not row["failures"] else "FAIL"
      row["notes"].append("no baseline: only the generic checks apply, run with --record to create one")
    anyFailed = anyFailed or row["status"] == "FAIL"
    rows.append(row)
    print(f"[{row['status']}] {sceneName}: {row['passed']} passed, {row['failed']} failed, {row['seconds']} s"
          + (f"; {len(row['failures'])} regression(s)" if row["failures"] and row["status"] == "FAIL" else ""), flush=True)
    for failure in row["failures"]:
      print(f"    {failure}", flush=True)

  reportPath = os.path.join(outDir, "scene-regression-report.md")
  with open(reportPath, "w") as f:
    f.write(f"# Scene regression report\n\n{datetime.datetime.now():%Y-%m-%d %H:%M}, code {version}, scenes in `{args.scenes_dir}`\n\n")
    f.write("| Scene | Status | Checks passed | Checks failed | Seconds | Notes |\n|---|---|---|---|---|---|\n")
    for row in rows:
      f.write(f"| {row['scene']} | {row['status']} | {row['passed']} | {row['failed']} | {row['seconds']} | {'; '.join(row['notes'])} |\n")
    for row in rows:
      if row["failures"]:
        f.write(f"\n## {row['scene']}: {row['status']}\n\n")
        for failure in row["failures"]:
          f.write(f"- {failure}\n")
  statuses = [row["status"] for row in rows]
  print(f"\n{statuses.count('PASS')} passed, {statuses.count('FAIL')} failed, {statuses.count('RECORDED')} recorded, "
        f"{statuses.count('CRASH') + statuses.count('TIMEOUT')} crashed/timed out. Report: {reportPath}")
  return 1 if anyFailed else 0


if __name__ == "__main__":
  sys.exit(main())
