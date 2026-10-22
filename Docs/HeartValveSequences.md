# Heart valve sequences (4D SlicerHeart)

## Summary

SlicerHeart stores each heart valve as a **sequence** of time points, so one valve can be annotated at any number of frames of a 4D image. The valve modules (Valve Annulus Analysis, Valve Segmentation, Leaflet Analysis, Valve Papillary Analysis, Valve Quantification, Valve Batch Export) operate on these sequences. Scenes created with earlier versions of SlicerHeart, which stored a separate HeartValve node for every analyzed frame, are converted with the [Converter 4D Sequences](#converting-existing-scenes) module.

## Requirements

- 3D Slicer **5.12.0 or later** (stable) or a current preview release. Older versions crash when switching time points of a converted segmentation (`vtkSegmentation::ReorderSegments`) or when opening the Segment Editor on a converted scene; both fixes are in Slicer 5.12.0.
- Scenes saved in the sequence format cannot be opened by SlicerHeart versions that predate it. Keep a copy of the original `.mrb` if that matters.

## Data model

A scene contains one **volume sequence browser** per 4D image. A static (3D) image is wrapped into a single-frame volume sequence automatically when a valve is created on it. A single `ProbeToRasTransform` is attached to the volume and is shared by all valves on that image, since the probe is assumed not to move during the acquisition.

Each valve is a **valve browser**: a `vtkMRMLSequenceBrowserNode` (named `<valve type>_Browser` after conversion, `HeartValveBrowser` when created in the GUI). All nodes of the valve are placed under the browser's folder in the subject hierarchy. The browser holds:

- **Valve-level properties**, stored on the browser node and shared by all time points: the valve volume (`ValveVolume` reference), the clipped valve volume, valve type and probe position.
- **The HeartValve sequence** (master sequence, `HeartValveSequence`): one HeartValve scripted module node per time point, carrying per-time-point properties such as the cardiac cycle phase. The browser's proxy node is the HeartValve node of the currently displayed time point; this is the node that modules and scripts work on, exactly as they worked on a single HeartValve node before.
- **Synchronized sequences**, created on demand when a time point first gets the data: annulus contour (closed curve markup), annulus landmark labels, valve ROI model, leaflet segmentation and leaflet volume, leaflet surface boundary markups and surface models, coaptation surface models with base and margin lines, papillary muscle lines, quantification result tables and models, and the `AxialSliceToRasTransform` that stores the view orientation. Display nodes are sequenced as well, so visibility and colours can differ per time point.

Time points are indexed by the **frame index of the volume sequence**. A valve does not need a time point at every frame: the valve sequence is sparse, and at frames without a time point the proxy nodes are reset to empty defaults (`MissingItemSetToDefault`), so nothing of a neighbouring frame is shown there.

Changing a proxy node (e.g. moving an annulus point) is written back into the sequence at the current time point (`SaveChanges` is on for every valve sequence).

### Leaflet segments

All time points of a valve have the same set of leaflet segments. Adding, renaming, recolouring or changing the terminology of a segment in Valve Segmentation applies to every time point; deleting a segment that has content at other time points asks whether to remove it everywhere or only clear it at the current time point.

## Working with time points

1. In **Valve Annulus Analysis** select or create a valve series (the valve browser), set the valve volume, valve type and probe position.
2. Move the volume sequence to the frame to annotate (sequence browser toolbar or the module's time point controls) and press **Add** in the *Time points* section. The new time point inherits the view orientation of the previous one. **Remove** deletes the current time point from every sequence of the valve; **Go to** jumps back to the frame of the current time point.
3. Assign the cardiac cycle phase of the time point (mid-systole, end-systole, mid-diastole, end-diastole, ...). Phases are what Valve Quantification's phase-comparison presets and Valve Batch Export's phase filters use to find the frames of interest.
4. Add the annulus contour, segmentation, leaflets, papillary muscles and quantification as before. Each module shows the same time point controls, bound to the selected valve.

From a script, `HeartValveLib.HeartValves.getValveBrowser(browserNode)` returns a `ValveBrowser` with `addTimePointAtCurrentFrame()`, `removeTimePoint(indexValue)`, `valveModel` (the `ValveModel` of the current time point), `heartValveNode`, `volumeSequenceBrowserNode` and `addCurrentTimePointToSequence(sequenceNode)` for adding data of your own to a time point. `HeartValveLib.helpers.getValveTimePointsMatchingPhase` finds the time points of a given phase. `HeartValveLib.HeartValves.getValveModel(heartValveNode)` keeps working on any HeartValve node, proxy or not.

## Converting existing scenes

The **Converter 4D Sequences** module (category *Cardiac*) migrates scenes made with the previous SlicerHeart data model:

- HeartValve nodes of the same valve type on the same volume sequence are merged into one valve browser, each legacy node becoming the time point at its `ValveVolumeSequenceIndex`. Valves on a static volume are first given a single-frame volume sequence. Annulus contours, landmarks, ROI, segmentations, leaflet surfaces, coaptation and papillary data move into synchronized sequences; pre-markups data (fiducial annulus contours, old curve models) is upgraded on the way.
- HeartValveMeasurement nodes (Valve Quantification results) are re-pointed to the converted valve at the phase they were computed for, and their result tables and models become sequences.
- CardiacDeviceAnalysis nodes are converted in the same way.
- The original nodes are removed after a successful conversion and a summary of the converted node counts is shown.

Buttons allow converting one category at a time; *Convert all nodes to sequences* does the full migration and is what the automatic conversion runs. The **Automatic conversion on scene load** checkbox (setting `Converter4DSequences/AutoConvert`) runs the full conversion after every scene import. It is off by default; when it is off, legacy scenes are left unchanged and the valve modules will not list their valves until the scene is converted. Valve Batch Export converts every scene it exports, so legacy cohorts can be exported without converting them by hand.

Conversion happens in memory. Save the scene afterwards (as a new file if the original should stay readable by older SlicerHeart versions).

## Notes on results

Compared with the previous data model, annulus contours are Slicer closed-curve markups instead of the former custom `SmoothCurve` implementation. "Centered" annulus metrics may therefore differ slightly from values computed with older versions (up to about 2.5 % was observed on test cases), and leaflet surfaces are derived from the segmentation at each time point rather than stored separately. Batch export writes one row per time point and names per-valve volume sequences by valve.
