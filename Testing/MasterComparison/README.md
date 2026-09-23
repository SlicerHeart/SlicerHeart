# Master branch comparison of the 4D conversion

Checks that legacy scenes created by the **original master branch code** (one HeartValve node per
cardiac phase) are converted by `Converter4DSequences` without losing or changing data, and that the
heartvalvesequence quantification reproduces the master results.

```powershell
.\Testing\MasterComparison\RunMasterComparison.ps1 -Slicer <Slicer.exe> -MasterRepo <checkout of master> -OutDir <output dir>
```

1. `GenerateMasterScenes.py` runs in a Slicer instance with the SlicerHeart modules of the master
   checkout. It uses the SlicerHeart "Mitral" sample (real 4D ultrasound) and the master HeartValveLib /
   ValveQuantification API to build each scenario, then writes `<scenario>.mrb` and
   `<scenario>.json` (the values stored in the scene and the quantification results computed by master).
2. `CompareConvertedScenes.py` runs with the modules of this checkout. It saves each converted scene
   to `<scenario>-converted/` (a directory, not an .mrb, because of the Windows path length limit). It loads each scene, converts it,
   displays each time point and compares the annotations with the master values. It compares the
   converted results tables with the master tables, then recomputes the metrics and compares those as
   well. It writes `<scenario>-comparison.json`, `<scenario>-notes.json` and `comparison-report.md`.

Use `-SkipGenerate` to rerun only the comparison on already generated scenes.

## Scenarios

| Scenario | Content |
|---|---|
| `mitral_three_phases` | Mitral valve at MS / ES / ED (frames 5, 14, 24) with contour, labels, ROI, leaflet volume and segmentation, leaflet surfaces, coaptation and papillary muscles. For each phase a MitralValve and a GenericValve measurement, plus a PhaseCompare measurement across the phases. |
| `two_valves_custom_phases` | Mitral (mid-systole, custom1) and aortic (mid-systole, unknown) valves on one volume. MitralValve measurements reference both valves (JolleyLab/SlicerHeartPrivate#308). |
| `three_valves_three_phases` | Mitral, tricuspid (3 leaflets, 3 papillary muscles) and aortic (3 cusps) valves, each at MS / ES / ED (frames 5, 14, 24) in one scene. Per phase a MitralValve measurement referencing the mitral and aortic valves, a TricuspidValve and an aortic GenericValve measurement, plus a PhaseCompare measurement for the mitral and the tricuspid valve. The tricuspid and aortic contours are the mitral contours moved to other positions (not anatomical). |
| `single_phase_minimal` | Tricuspid valve, one phase, contour and labels only (no ROI or segmentation). |

## What is compared

At each time point of the converted valve browser (strict comparison):

- **Valve state:** phase, frame index, probe position and contour radius.
- **Annulus:** contour control points and landmark labels, with a 0.001 mm tolerance.
- **ROI:** geometry parameters.
- **Segmentation:** leaflet segments by name, with voxel counts, and the leaflet volume.
- **Leaflet boundaries:** boundary points.
- **Coaptation:** base and margin lines.
- **Papillary muscles:** line points.
- **Measurements:**
  - valve references of each measurement;
  - stored results tables;
  - recomputed metrics, with a relative tolerance of 0.1%.

Recomputed metrics that the heartvalvesequence branch computes differently **by design** are listed as
notes with the reason (`KNOWN_ALGORITHM_CHANGES` in `CompareConvertedScenes.py`), not as failures. The
same applies to derived geometry that is regenerated (ROI model, leaflet and coaptation surfaces), and to
metrics that master could not compute because it raised an exception.

## Results (2026-09-23, heartvalvesequence-master-comparison)

511 of 514 checks pass:

| Scenario | Passed | Failed |
|---|---|---|
| mitral_three_phases | 114 | 0 |
| two_valves_custom_phases | 93 | 0 |
| three_valves_three_phases | 281 | 3 |
| single_phase_minimal | 23 | 0 |

The 3 failures are expected until this branch is rebased on master: the **tricuspid septal papillary
muscle** is dropped in the conversion because the branch does not have master commit 8bd075c, which
added it to the tricuspid valve type. With that commit, all 517 checks pass (287 in
three_valves_three_phases).

The first run found these conversion defects, fixed on this branch:

- **Leaflet segment IDs** differed per phase (master creates new IDs for each phase's segmentation).
  - The 4D code identifies leaflet surface nodes by segment ID, so the leaflets of all but one phase
    lost their boundary and surface.
  - The conversion now harmonizes the IDs, matching segments by terminology entry or by name.
- **Results tables and models** attached to a measurement only in the subject hierarchy were stored for
  one phase only. They are now sequenced per time point, like the 4D quantification stores them.
- **Measurements referencing two valves** were grouped under the valve browser of the alphabetically
  first reference role (aortic), not under the preset's primary valve (mitral).
- **References between converted nodes** were lost, e.g. the segmentation's reference geometry volume.
  Storing a node in a sequence strips its references; they are now restored.
- **TricuspidValve quantification** raised an exception for a valve with one coaptation line (master has
  this guard; it was lost in the port).
- **Quantification of converted time points** failed:
  - it used leaflet models of the previously displayed time point;
  - `ValveRoi.getLeafletBoundary` divided by zero for a coaptation line without points at the displayed
    time point (master has this guard; it was lost in the port).

Expected differences found in the recomputed metrics (not conversion defects):

- **"centered" annulus areas and bending angles: up to 2.5% difference.**
  - Master samples its SmoothCurve spline, heartvalvesequence the markups closed-curve spline.
  - The difference moves the clipping planes and the curve halves slightly.
  - The plain annulus metrics (area, circumference, heights, distances) are identical.
- **Leaflet surface based metrics differ:** leaflet area, thickness estimate, tenting and billow
  height/volume, and atrial area.
  - heartvalvesequence extracts the valve surface with `ValveModel.createValveSurface`, master with a
    smoothed "blanket" surface.
  - Billow volume is 0 with the new extraction on this data (master: ~410 mm³). This is worth a look by
    whoever owns the quantification.
  - The leaflet area metric was renamed from "Leaflet area - X (3D)" to "Leaflet area - X".
- **Regenerated leaflet surfaces have a different number of points.** They are regenerated from the
  boundary and the segmentation in both versions whenever a valve model is set up. The boundary curve is
  interpolated differently.
- **Master itself raises exceptions**, and heartvalvesequence computes those metrics:
  - PhaseCompare with identical planes (`getLinesIntersectionPoints`);
  - MitralValve with an aortic valve reference.
