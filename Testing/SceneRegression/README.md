# Regression check of real scenes

Runs every real SlicerHeart scene (`.mrb`) of a folder through the sequence conversion and the valve
quantification, and compares the outcome with a baseline recorded for that scene. The scenes are
patient data and are **not part of the repository**: the harness works on whatever folder it is
pointed at, and a scene is useful the moment it is dropped in, with or without a baseline.

```
python Testing/SceneRegression/run_scene_regression.py --slicer <Slicer.exe> --scenes-dir <folder>
```

The folder can also be given with the `SLICERHEART_SCENES_DIR` environment variable. Without a folder
the script exits with code 77, which CTest reports as *skipped*.

## What is checked for every scene

`CheckScene.py` runs in its own Slicer process per scene (sequentially, one Slicer at a time, with a
timeout) and does not need to know the scene:

1. load the scene (auto-conversion suspended) and take an inventory of the legacy HeartValve nodes and
   measurements;
2. convert it with `Converter4DSequences` and check that nothing was lost: one time point per legacy
   valve frame, phase, closed-curve annulus with the same control points, labels, non-empty leaflet
   segments, ROI, volume frame, every measurement at its time point with its valve references and
   results tables;
3. save the converted scene, reload it and check that the time points are identical;
4. recompute every measurement at every time point (`ValveQuantificationLogic.computeMetrics`) and
   check that it ran and that every metric stored in the scene is recomputed.

The recomputed values are compared with the tables stored in the scene only as information (stored
values are often stale: the annulus was edited after measuring, or an older algorithm wrote them).
What makes the recomputed values a regression check is the baseline.

## Baselines

`<scene>.expected.json` next to the scene records the generic checks that failed (allowed failures,
for example a metric row that the current code omits by design) and the recomputed value of every
metric of every measurement. It is created or overwritten with `--record`:

```
python Testing/SceneRegression/run_scene_regression.py --slicer <Slicer.exe> --scenes-dir <folder> --record
```

Review the report of a `--record` run before trusting it: every failing check of that run becomes an
allowed failure. On later runs a scene fails when

- a generic check fails that is not an allowed failure,
- an allowed failure passes now (stale baseline, re-record the scene),
- a measurement of the baseline is missing or no longer computes, its metric rows changed, or a value
  moved by more than 0.1 % (relative) + 0.001 (absolute), or a measurement appeared that the baseline
  does not know.

Baselines live next to the scenes, not in the repository, so nothing derived from patient scenes is
committed. The code version (`git describe`) and the date are stored in the baseline.

## Options

| Option | Meaning |
|---|---|
| `--scene NAME` | only this scene (file name without `.mrb`), repeatable |
| `--out-dir DIR` | results, logs, report and converted scenes (default `<scenes-dir>/_results`) |
| `--module-paths P ...` | module folders for Slicer; default: the module folders of this repository (scripted modules run from source) |
| `--launcher-settings INI` | `AdditionalLauncherSettings.ini` of a build tree |
| `--timeout SEC` | per scene, default 3600; the Slicer process tree is killed on timeout |
| `--no-recompute` | conversion and round trip only (minutes instead of hours for the large scenes) |
| `--compare-only` | re-run the baseline comparison on the results already in `--out-dir` |

Outputs in `--out-dir`: `<scene>.log` (Slicer output), `<scene>-result.json` (all checks, inventories
and recomputed values), `scene-regression-report.md` (summary table and the regressions per scene),
and `<short name>-converted/` (the converted scene, saved as a directory because of the Windows path
length limit).

## CTest

The test `py_SceneRegression` is registered by `Testing/CMakeLists.txt` and runs with the modules of
the build tree. It is skipped unless `SLICERHEART_SCENES_DIR` is set when CTest runs:

```
set SLICERHEART_SCENES_DIR=C:\path\to\scenes
ctest -C RelWithDebInfo -R SceneRegression --output-on-failure
```

A full run of 23 scenes takes about two hours (the largest scene with 13 time points takes about ten
minutes); the test timeout is four hours. Run it before merging changes to `HeartValveLib`,
`Converter4DSequences` or the quantification presets.

## Adding a scene

Copy the `.mrb` into the folder, run the harness for that scene (`--scene NAME`), read its failures:
they are either defects to fix or explained differences. Then record its baseline. Scenes that
exercise unusual data are the most valuable: propagated segmentations, other valve types, scenes from
other labs or older Slicer versions, nodes moved around in the subject hierarchy.
