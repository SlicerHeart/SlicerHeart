"""Feature tests of the Import4DFlow module.

Tests use an analytic flow phantom (generated in the scene or written as Siemens CS 4D flow-like DICOM files)
and, if available, an anonymized clinical 4D flow MRI data set (see FlowTestingUtils.REAL_DATA_ENV_VARIABLE).
Results are written into a markdown report with screenshots (see FlowTestingUtils.TestReport).

Run from the Slicer Python console:

    import slicer.testing
    slicer.testing.runUnitTest([r"<path>/Import4DFlow/Testing/Python"], "Import4DFlowFeaturesTest")
"""

import logging
import math
import os
import shutil
import tempfile
import time
import unittest

import numpy as np
import vtk
import vtk.util.numpy_support

import slicer

import FlowTestingUtils
from FlowTestingUtils import FlowPhantom, reportedTest

import Import4DFlow
from Import4DFlow import Import4DFlowLogic, BackgroundSubtractionMethodEnum, UnwrapModeEnum


# Tolerance of velocity comparisons (m/s): phase values are stored as integers (1 raw unit = venc/4096),
# and DICOM stores them with 2x reduced resolution (rescale slope = 2).
def velocityQuantizationMPerSec(vencCmPerSec):
    return 2.5 * vencCmPerSec / FlowTestingUtils.PHASE_MAX_VALUE / 100.0


class Import4DFlowFeaturesTest(FlowTestingUtils.FeatureTestCase):

    REPORT_SUITE_NAME = "Import4DFlow"
    REPORT_TITLE = "Import 4D Flow - feature test report"
    REPORT_DESCRIPTION = (
        "Automated tests of all features of the *Import 4D Flow* module: detection of Siemens CS 4D flow images"
        " loaded from DICOM, conversion to flow field (stored in grid transform or vector volume sequence), noise masking,"
        " background phase correction, phase unwrapping (temporal and manual), visualization, export (NRRD stack, 5D NRRD,"
        " anonymized scene), scene persistence, and the module GUI.\n\n"
        "Most tests use an analytic flow phantom: pulsatile Poiseuille flow in an oblique cylindrical vessel"
        " (radius 10 mm), imaged with an oblique (rotated) volume, so that the computed velocity vectors can be compared"
        " to the exact solution. The real-data test uses an anonymized clinical data set.")

    def setUp(self):
        super().setUp()
        self.logic = Import4DFlowLogic()
        self.temporaryDirectories = []

    def tearDown(self):
        for directory in self.temporaryDirectories:
            shutil.rmtree(directory, ignore_errors=True)

    def temporaryDirectory(self, prefix):
        directory = tempfile.mkdtemp(prefix=prefix, dir=slicer.app.temporaryPath)
        self.temporaryDirectories.append(directory)
        return directory

    # Helpers

    def createFlowField(self, volumeNodeSet, storeInTransform, noiseMagnitudeThresholdPercent=5.0,
                        backgroundSubtractionMethod=BackgroundSubtractionMethodEnum.NoSubtraction,
                        stationaryTissueSpeedThresholdVencPercent=10.0, unwrap=False):
        flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(
            volumeNodeSet["componentVolumeNodes"], volumeNodeSet["componentVolumeNodesInvertToRasDirection"],
            volumeNodeSet["magnitudeVolumeNode"], storeInTransform=storeInTransform)
        if unwrap:
            self.logic.temporalUnwrap(flowFieldNode, 0, noiseMagnitudeThresholdPercent)
        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, noiseMagnitudeThresholdPercent,
            backgroundSubtractionMethod, stationaryTissueSpeedThresholdVencPercent)
        return flowFieldNode

    def velocityFrames(self, flowFieldNode):
        """Velocity vectors (k, j, i, 3) of all frames of a flow field, in m/s, RAS."""
        sequenceNode = self.logic._getSequenceFromProxyNode(flowFieldNode)
        frames = []
        for frameIndex in range(sequenceNode.GetNumberOfDataNodes()):
            frameNode = sequenceNode.GetNthDataNode(frameIndex)
            if frameNode.IsA("vtkMRMLTransformNode"):
                frames.append(slicer.util.arrayFromGridTransform(frameNode).copy())
            else:
                frames.append(slicer.util.arrayFromVolume(frameNode).copy())
        return frames

    @staticmethod
    def storageName(storeInTransform):
        return "grid transform" if storeInTransform else "vector volume"

    def checkVelocityFrames(self, label, frames, expectedFrames, toleranceMPerSec, mask=None):
        maxErrors = []
        for measured, expected in zip(frames, expectedFrames):
            difference = np.abs(measured - expected)
            if mask is not None:
                difference = difference[mask]
            maxErrors.append(float(difference.max()))
        self.report.checkClose(f"{label}: maximum velocity error over all frames", max(maxErrors), 0.0,
            atol=toleranceMPerSec, unit="m/s")
        return maxErrors

    def trySetDefaultVisualization(self, flowFieldNode):
        """Set default flow field visualization. Returns None on success, error message on failure
        (for example, when the vector field display node API of the Slicer version is not compatible)."""
        try:
            self.logic.setFlowFieldVisualizationToDefault(flowFieldNode)
            return None
        except Exception as e:
            return f"{type(e).__name__}: {e}"

    def showFlowFieldAtFrame(self, flowFieldNode, frameIndex, phantom=None):
        self.logic.setFlowFieldVisualizationToDefault(flowFieldNode)
        FlowTestingUtils.selectSequenceItem(flowFieldNode, frameIndex)
        magnitudeVolumeNode = flowFieldNode.GetNodeReference("magnitudeVolume")
        FlowTestingUtils.showVolumeInSliceViews(magnitudeVolumeNode, phantom.centerRas if phantom else None)
        displayNode = self.logic.getFlowFieldDisplayNode(flowFieldNode)
        if displayNode:
            displayNode.SetVisibility3D(True)
        FlowTestingUtils.reset3DView()

    # Tests

    @reportedTest("Module and GUI initialization",
        "The module and its GUI can be loaded; the Doppler color table, export format list, and"
        " storage format selector are initialized.")
    def test_01_ModuleAndWidget(self):
        self.report.checkTrue("Import4DFlow module is loaded", hasattr(slicer.modules, "import4dflow"))
        slicer.util.selectModule("Import4DFlow")
        widget = slicer.modules.import4dflow.widgetRepresentation().self()
        self.report.checkTrue("Module widget is created", widget is not None and widget.logic is not None)

        colorNode = Import4DFlowLogic.dopplerColdToHotColorTableNode()
        self.report.checkTrue("Doppler color table is available", colorNode is not None)
        self.report.checkTrue("Doppler color table has colors", colorNode.GetNumberOfColors() > 0, colorNode.GetNumberOfColors(), "> 0")
        self.report.checkEqual("Doppler color table category", colorNode.GetAttribute("Category"), "Flow")
        self.report.checkTrue("Same Doppler color table node is returned on repeated calls",
            Import4DFlowLogic.dopplerColdToHotColorTableNode() == colorNode)

        comboBox = widget.ui.exportFormatComboBox
        formats = [comboBox.itemData(i) for i in range(comboBox.count)]
        self.report.checkEqual("Export formats in GUI", formats, Import4DFlowLogic.EXPORT_FORMATS)
        self.report.checkTrue("'Store in transform' is checked by default", widget.ui.storeInTransformCheckBox.checked)
        self.report.checkTrue("Convert button is disabled without input", not widget.ui.convertButton.enabled)
        self.report.screenshot("Import 4D Flow module GUI", kind="window")

    @reportedTest("Detection of 4D flow images loaded from DICOM",
        "Siemens CS 4D flow phantom images are written as DICOM files (magnitude and 3 phase series, multiple trigger times),"
        " imported into a temporary DICOM database, loaded as volume sequences, then detected by"
        " `findVolumeNodeSets`. Variants: speed/direction code in private tag (0051,1014) (Siemens Avanto),"
        " in private tag (0021,1129) stored as raw bytes (Siemens Avanto Fit), only in SequenceName (free-running sequences),"
        " and a coronal acquisition (different direction configuration). For each detected set, the flow field is computed"
        " and compared to the analytic phantom velocity (end-to-end test of DICOM geometry, rescaling, and direction mapping).")
    def test_02_DicomDetection(self):
        from DICOMLib import DICOMUtils
        vencCmPerSec = 150.0
        phantom = FlowPhantom(dims=(24, 24, 12), spacingMm=(1.5, 1.5, 2.5), numberOfFrames=6, tissueRadiusMm=16.0)
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        cases = [
            ("avanto", FlowTestingUtils.DIRECTION_CONFIGURATION_AXIAL),
            ("avantofit", FlowTestingUtils.DIRECTION_CONFIGURATION_AXIAL),
            ("sequencename", FlowTestingUtils.DIRECTION_CONFIGURATION_AXIAL),
            ("avanto", FlowTestingUtils.DIRECTION_CONFIGURATION_CORONAL),
        ]
        rows = []
        for variant, configuration in cases:
            caseName = f"{variant}, {'axial' if configuration is FlowTestingUtils.DIRECTION_CONFIGURATION_AXIAL else 'coronal'}"
            slicer.mrmlScene.Clear()
            dicomDir = self.temporaryDirectory("Import4DFlowDicom_")
            phantom.writeDicomSeries(os.path.join(dicomDir, "dicom"), vencCmPerSec, configuration, variant)
            with DICOMUtils.TemporaryDICOMDatabase(os.path.join(dicomDir, "db")) as db:
                DICOMUtils.importDicom(os.path.join(dicomDir, "dicom"), db)
                loadedVolumes = FlowTestingUtils.loadDicomSeriesAsVolumeSequences()
                self.report.checkEqual(f"[{caseName}] Number of loaded volume sequences", len(loadedVolumes), 4)
                volumeNodeSets = self.logic.findVolumeNodeSets()
            found = self.report.checkEqual(f"[{caseName}] Number of detected 4D flow image sets", len(volumeNodeSets), 1)
            if not found:
                rows.append([caseName, "not detected", "", "", "", ""])
                continue
            volumeNodeSet = list(volumeNodeSets.values())[0]
            self.report.checkEqual(f"[{caseName}] Image set name", volumeNodeSet["name"], "Phantom, Flow (20240102)")
            directionCodes = [self.logic._getSequenceAttribute(n, "SlicerHeart.directionCode") for n in volumeNodeSet["componentVolumeNodes"]]
            self.report.checkEqual(f"[{caseName}] Direction codes of components (R, A, S)", directionCodes, [c[0] for c in configuration])
            self.report.checkEqual(f"[{caseName}] Invert to RAS direction flags", volumeNodeSet["componentVolumeNodesInvertToRasDirection"],
                [c[1] for c in configuration])
            vencs = [self.logic._getSequenceAttribute(n, "SlicerHeart.vencCmPerSec") for n in volumeNodeSet["componentVolumeNodes"]]
            self.report.checkTrue(f"[{caseName}] Velocity encoding is read from DICOM",
                all(v is not None and abs(float(v) - vencCmPerSec) < 1e-6 for v in vencs), vencs, f"{vencCmPerSec:g}")
            heartRate = self.logic._getSequenceAttribute(volumeNodeSet["magnitudeVolumeNode"], "SlicerHeart.heartRateBpm")
            self.report.checkClose(f"[{caseName}] Heart rate from NominalInterval", float(heartRate or "nan"), phantom.heartRateBpm(), atol=1e-6, unit="bpm")

            # End-to-end check of velocity vectors
            ijkToRas = vtk.vtkMatrix4x4()
            volumeNodeSet["magnitudeVolumeNode"].GetIJKToRASMatrix(ijkToRas)
            phantomIjkToRas = phantom.ijkToRasMatrix()
            geometryError = max(abs(ijkToRas.GetElement(r, c) - phantomIjkToRas.GetElement(r, c)) for r in range(3) for c in range(4))
            self.report.checkClose(f"[{caseName}] Loaded image geometry (IJK to RAS matrix) error", geometryError, 0.0, atol=1e-3)
            flowFieldNode = self.createFlowField(volumeNodeSet, storeInTransform=True)
            frames = self.velocityFrames(flowFieldNode)
            maxErrors = self.checkVelocityFrames(f"[{caseName}] Velocity", frames, expectedFrames, velocityQuantizationMPerSec(vencCmPerSec))
            rows.append([caseName, "detected", directionCodes, volumeNodeSet["componentVolumeNodesInvertToRasDirection"], heartRate, max(maxErrors)])
            if variant == "avanto" and configuration is FlowTestingUtils.DIRECTION_CONFIGURATION_AXIAL:
                self.showFlowFieldAtFrame(flowFieldNode, phantom.peakFrameIndex(), phantom)
                self.report.screenshot("Flow field computed from DICOM phantom (Siemens Avanto variant) at peak systole")
        self.report.table(["DICOM variant", "Result", "Direction codes", "Invert flags", "Heart rate (bpm)", "Max. velocity error (m/s)"], rows,
            "Detection results")

    @reportedTest("Incomplete image sets are rejected",
        "4D flow image sets are only offered for conversion if all 3 velocity components and the magnitude image are available.")
    def test_03_IncompleteImageSetsRejected(self):
        from DICOMLib import DICOMUtils
        phantom = FlowPhantom(dims=(16, 16, 8), spacingMm=(2.0, 2.0, 3.0), numberOfFrames=3, tissueRadiusMm=12.0, vesselRadiusMm=6.0)
        dicomDir = self.temporaryDirectory("Import4DFlowDicom_")
        seriesUIDs = phantom.writeDicomSeries(os.path.join(dicomDir, "dicom"), 150.0)
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(dicomDir, "db")) as db:
            DICOMUtils.importDicom(os.path.join(dicomDir, "dicom"), db)
            # Without magnitude image
            FlowTestingUtils.loadDicomSeriesAsVolumeSequences(seriesUIDs[1:])
            self.report.checkEqual("Image sets found without magnitude image", len(self.logic.findVolumeNodeSets()), 0)
            slicer.mrmlScene.Clear()
            # Without one of the components
            FlowTestingUtils.loadDicomSeriesAsVolumeSequences(seriesUIDs[:3])
            self.report.checkEqual("Image sets found with a missing velocity component", len(self.logic.findVolumeNodeSets()), 0)
            # Complete set
            FlowTestingUtils.loadDicomSeriesAsVolumeSequences(seriesUIDs[3:])
            self.report.checkEqual("Image sets found with all images", len(self.logic.findVolumeNodeSets()), 1)
        # Non-DICOM volumes are ignored
        slicer.mrmlScene.Clear()
        phantom.createComponentImagesInScene()
        self.report.checkEqual("Image sets found for volumes that are not loaded from DICOM", len(self.logic.findVolumeNodeSets()), 0)

    @reportedTest("Flow field creation",
        "`createFlowFieldFromComponentVolumes` merges all image sequences into one sequence browser, replaces frame indices"
        " by trigger times, and creates the flow field node (grid transform or vector volume) with all references.")
    def test_04_CreateFlowField(self):
        phantom = FlowPhantom()
        for storeInTransform in [True, False]:
            slicer.mrmlScene.Clear()
            storage = self.storageName(storeInTransform)
            volumeNodeSet = phantom.createComponentImagesInScene()
            flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(
                volumeNodeSet["componentVolumeNodes"], volumeNodeSet["componentVolumeNodesInvertToRasDirection"],
                volumeNodeSet["magnitudeVolumeNode"], storeInTransform=storeInTransform)
            expectedClass = "vtkMRMLTransformNode" if storeInTransform else "vtkMRMLVectorVolumeNode"
            self.report.checkTrue(f"[{storage}] Flow field node type is {expectedClass}", flowFieldNode.IsA(expectedClass), flowFieldNode.GetClassName(), expectedClass)
            self.report.checkEqual(f"[{storage}] SlicerHeart.Type attribute", flowFieldNode.GetAttribute("SlicerHeart.Type"), "FlowField")
            self.report.checkTrue(f"[{storage}] Magnitude volume reference", flowFieldNode.GetNodeReference("magnitudeVolume") == volumeNodeSet["magnitudeVolumeNode"])
            for component in range(3):
                self.report.checkTrue(f"[{storage}] Component volume reference {component}",
                    flowFieldNode.GetNthNodeReference("componentVolume", component) == volumeNodeSet["componentVolumeNodes"][component])
            browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
            magnitudeBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(volumeNodeSet["magnitudeVolumeNode"])
            self.report.checkTrue(f"[{storage}] Flow field is in the magnitude volume's sequence browser", browserNode is not None and browserNode == magnitudeBrowserNode)
            for component, componentVolumeNode in enumerate(volumeNodeSet["componentVolumeNodes"]):
                componentBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(componentVolumeNode)
                self.report.checkTrue(f"[{storage}] Component {component} is moved into the common sequence browser", componentBrowserNode == browserNode)
                sequenceNode = self.logic._getSequenceFromProxyNode(componentVolumeNode)
                directionCode, invert = FlowTestingUtils.DIRECTION_CONFIGURATION_AXIAL[component]
                self.report.checkTrue(f"[{storage}] Component {component} sequence name contains direction code",
                    f"C{component + 1} {directionCode}" in sequenceNode.GetName(), sequenceNode.GetName())
                self.report.checkEqual(f"[{storage}] Component {component} invertToRasDirection attribute",
                    sequenceNode.GetAttribute("SlicerHeart.invertToRasDirection"), "true" if invert else "false")
            self.report.checkEqual(f"[{storage}] Number of browser items", browserNode.GetNumberOfItems(), phantom.numberOfFrames)
            magnitudeSequenceNode = self.logic._getSequenceFromProxyNode(volumeNodeSet["magnitudeVolumeNode"])
            indexValues = [float(magnitudeSequenceNode.GetNthIndexValue(i)) for i in range(magnitudeSequenceNode.GetNumberOfDataNodes())]
            self.report.checkEqual(f"[{storage}] Frame index values are trigger times", indexValues, phantom.frameTimesMs)
            self.report.checkEqual(f"[{storage}] Index name and unit", (magnitudeSequenceNode.GetIndexName(), magnitudeSequenceNode.GetIndexUnit()), ("time", "ms"))
            self.report.checkEqual(f"[{storage}] Index type is numeric", magnitudeSequenceNode.GetIndexType(), slicer.vtkMRMLSequenceNode.NumericIndex)
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            self.report.checkEqual(f"[{storage}] Flow field is in the same subject hierarchy folder as the magnitude volume",
                shNode.GetItemParent(shNode.GetItemByDataNode(flowFieldNode)),
                shNode.GetItemParent(shNode.GetItemByDataNode(volumeNodeSet["magnitudeVolumeNode"])))

    @reportedTest("Velocity computation accuracy",
        "Velocity vectors computed by `updateFlowFieldFromComponentVolumes` are compared to the analytic phantom"
        " in every voxel and frame, for both storage formats. The phantom volume is oblique (rotated by 20 degrees)."
        " The grid transform must displace each point by the velocity vector (in the 'to parent' direction, which is used"
        " for visualization and analysis).")
    def test_05_VelocityAccuracy(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom()
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        computedFrames = {}
        rows = []
        for storeInTransform in [True, False]:
            slicer.mrmlScene.Clear()
            storage = self.storageName(storeInTransform)
            volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
            startTime = time.time()
            flowFieldNode = self.createFlowField(volumeNodeSet, storeInTransform)
            durationSec = time.time() - startTime
            frames = self.velocityFrames(flowFieldNode)
            computedFrames[storeInTransform] = frames
            self.report.checkEqual(f"[{storage}] Number of frames", len(frames), phantom.numberOfFrames)
            maxErrors = self.checkVelocityFrames(f"[{storage}]", frames, expectedFrames, velocityQuantizationMPerSec(vencCmPerSec))
            peakFrame = phantom.peakFrameIndex()
            rows.append([storage, f"{durationSec:.2f}", max(maxErrors), float(np.linalg.norm(frames[peakFrame], axis=-1).max())])
            sequenceNode = self.logic._getSequenceFromProxyNode(flowFieldNode)
            self.report.checkEqual(f"[{storage}] Velocity unit attribute", sequenceNode.GetAttribute("SlicerHeart.velocityUnit"), "m/s")
            self.report.checkEqual(f"[{storage}] Velocity encoding attribute", sequenceNode.GetAttribute("SlicerHeart.vencCmPerSec"), ",".join([str(vencCmPerSec)] * 3))
            frameNode = sequenceNode.GetNthDataNode(peakFrame)
            self.report.checkEqual(f"[{storage}] Frame node SlicerHeart.Type attribute", frameNode.GetAttribute("SlicerHeart.Type"), "FlowField")

            FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
            if storeInTransform:
                transformToParent = flowFieldNode.GetTransformToParent()
                displacement = np.array(transformToParent.TransformPoint(phantom.centerRas)) - phantom.centerRas
                expectedVelocity = phantom.velocityAt(phantom.centerRas, peakFrame)
                self.report.checkClose(f"[{storage}] Displacement ('to parent') at vessel center equals velocity (error magnitude)",
                    np.linalg.norm(displacement - expectedVelocity), 0.0, atol=0.03, unit="m/s")  # interpolation of the parabolic profile between voxels
            else:
                self.report.checkEqual(f"[{storage}] Voxel vector type is spatial (RAS vectors)", frameNode.GetVoxelVectorType(),
                    slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial)
                ijkToRas = vtk.vtkMatrix4x4()
                flowFieldNode.GetIJKToRASMatrix(ijkToRas)
                phantomIjkToRas = phantom.ijkToRasMatrix()
                geometryError = max(abs(ijkToRas.GetElement(r, c) - phantomIjkToRas.GetElement(r, c)) for r in range(3) for c in range(4))
                self.report.checkClose(f"[{storage}] Vector volume geometry matches magnitude volume", geometryError, 0.0, atol=1e-6)
            if storeInTransform:
                self.showFlowFieldAtFrame(flowFieldNode, peakFrame, phantom)
                self.report.screenshot("Flow field (grid transform) at peak systole, magnitude image in background")

        difference = max(float(np.abs(a - b).max()) for a, b in zip(computedFrames[True], computedFrames[False]))
        self.report.checkClose("Grid transform and vector volume storage contain the same velocities (max. difference)", difference, 0.0, atol=1e-6, unit="m/s")
        self.report.table(["Storage", "Computation time (s)", "Max. velocity error (m/s)", "Max. speed at peak systole (m/s)"], rows)
        self.report.text(f"Analytic peak velocity: {phantom.peakVelocityMPerSec:g} m/s; velocity quantization: {velocityQuantizationMPerSec(vencCmPerSec):.2e} m/s.")

    @reportedTest("Noise masking by magnitude threshold",
        "Velocity is set to zero where the magnitude is below the noise threshold (percentage of the magnitude range)."
        " A constant phase offset is added to all component images so that masked and unmasked regions can be distinguished.")
    def test_06_NoiseMagnitudeThreshold(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom()
        phaseOffset = np.full(phantom.radialDistanceMm.shape, 500.0)
        offsetMPerSec = 500.0 / FlowTestingUtils.PHASE_MAX_VALUE * vencCmPerSec / 100.0
        magnitude = phantom.magnitudeVolumeArray()
        rows = []
        for thresholdPercent in [5.0, 45.0]:
            slicer.mrmlScene.Clear()
            volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec, phaseOffset=phaseOffset)
            flowFieldNode = self.createFlowField(volumeNodeSet, True, noiseMagnitudeThresholdPercent=thresholdPercent)
            frame = self.velocityFrames(flowFieldNode)[0]  # first frame: no flow, only the phase offset
            speed = np.linalg.norm(frame, axis=-1)
            threshold = thresholdPercent / 100.0 * self.logic.magnitudeVolumeRange
            belowThreshold = magnitude < threshold
            aboveThreshold = np.logical_not(belowThreshold)
            maxSpeedBelow = float(speed[belowThreshold].max()) if belowThreshold.any() else 0.0
            minSpeedAbove = float(speed[aboveThreshold].min()) if aboveThreshold.any() else 0.0
            self.report.checkClose(f"[threshold {thresholdPercent:g}%] Maximum speed where magnitude is below threshold", maxSpeedBelow, 0.0, atol=1e-6, unit="m/s")
            self.report.checkClose(f"[threshold {thresholdPercent:g}%] Minimum speed where magnitude is above threshold (phase offset)",
                minSpeedAbove, offsetMPerSec * np.sqrt(3), rtol=0.01, unit="m/s")
            rows.append([f"{thresholdPercent:g}%", f"{threshold:.1f}", int(np.count_nonzero(belowThreshold)), int(np.count_nonzero(aboveThreshold))])
        self.report.table(["Noise threshold", "Magnitude threshold", "Masked voxels", "Unmasked voxels"], rows,
            "Phantom magnitude values: background 3, tissue 100, vessel 200")

    @reportedTest("Background phase correction",
        "A spatially varying background phase error (linear or quadratic function of the voxel position) is added to the"
        " component images. Linear and quadratic fit background subtraction must remove the error from stationary tissue"
        " and restore the vessel velocity. Checks are performed on a phantom with realistic proportions (small vessel"
        " surrounded by a large amount of stationary tissue). A phantom with a large vessel is evaluated for information only:"
        " slowly moving blood near the vessel wall is below the stationary tissue speed threshold, which biases the fit"
        " if the vessel is large compared to the surrounding stationary tissue.")
    def test_07_BackgroundSubtraction(self):
        vencCmPerSec = 150.0
        phantoms = [
            ("realistic proportions (vessel radius 5 mm)", FlowPhantom(vesselRadiusMm=5.0, tissueRadiusMm=30.0), True),
            ("large vessel (radius 10 mm)", FlowPhantom(), False),
        ]
        rows = []
        for phantomName, phantom, checked in phantoms:
            stationaryTissue = phantom.stationaryTissueMask()
            peakFrame = phantom.peakFrameIndex()
            expectedPeak = phantom.velocityVolumeArray(peakFrame)
            cases = [
                ("linear offset", phantom.linearPhaseOffset(), BackgroundSubtractionMethodEnum.NoSubtraction, False),
                ("linear offset", phantom.linearPhaseOffset(), BackgroundSubtractionMethodEnum.LinearFit, True),
                ("quadratic offset", phantom.quadraticPhaseOffset(), BackgroundSubtractionMethodEnum.LinearFit, False),
                ("quadratic offset", phantom.quadraticPhaseOffset(), BackgroundSubtractionMethodEnum.QuadraticFit, True),
            ]
            for offsetName, phaseOffset, method, mustCorrect in cases:
                slicer.mrmlScene.Clear()
                volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec, phaseOffset=phaseOffset)
                flowFieldNode = self.createFlowField(volumeNodeSet, True, backgroundSubtractionMethod=method)
                frame = self.velocityFrames(flowFieldNode)[peakFrame]
                tissueError = float(np.abs(frame[stationaryTissue]).mean())
                vesselError = float(np.abs(frame - expectedPeak)[phantom.insideVessel].mean())
                offsetError = float(np.abs(phaseOffset[stationaryTissue]).mean() / FlowTestingUtils.PHASE_MAX_VALUE * vencCmPerSec / 100.0)
                rows.append([phantomName, offsetName, method.label(), offsetError, tissueError, vesselError])
                if mustCorrect and checked:
                    label = f"[{phantomName}, {offsetName}, {method.label()}]"
                    self.report.checkClose(f"{label} Mean residual velocity in stationary tissue", tissueError, 0.0, atol=0.2 * offsetError, unit="m/s")
                    self.report.checkClose(f"{label} Mean velocity error in the vessel", vesselError, 0.0, atol=0.2 * offsetError, unit="m/s")
        self.report.table(["Phantom", "Background error", "Subtraction method", "Mean background error before correction (m/s)",
            "Mean residual in stationary tissue (m/s)", "Mean velocity error in vessel (m/s)"], rows,
            "Checks require that at least 80% of the background error is removed (realistic proportions only)")

    @reportedTest("Temporal phase unwrapping",
        "Velocity encoding (70 cm/s) is set below the peak velocity (100 cm/s), so phase wraps around in systolic frames."
        " Temporal unwrapping must detect the wrapped voxels (phase wrap segmentations), the corrected flow field must match"
        " the analytic velocity. Resetting unwrapping must remove the phase wrap segmentations.")
    def test_08_TemporalUnwrap(self):
        vencCmPerSec = 70.0
        phantom = FlowPhantom()
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        expectedWrappedVoxels = phantom.numberOfWrappedVoxels(vencCmPerSec)
        self.report.text(f"Number of voxels (over all frames and components) with velocity above the velocity encoding: {expectedWrappedVoxels}")
        self.report.checkTrue("Phantom contains phase wraps", expectedWrappedVoxels > 0, expectedWrappedVoxels, "> 0")
        volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
        flowFieldNode = self.createFlowField(volumeNodeSet, True, unwrap=False)
        wrappedFrames = self.velocityFrames(flowFieldNode)
        wrappedError = max(float(np.abs(f - e).max()) for f, e in zip(wrappedFrames, expectedFrames))
        self.report.checkTrue("Without unwrapping, velocity error is large", wrappedError > 0.5, f"{wrappedError:.3f} m/s", "> 0.5 m/s")

        startTime = time.time()
        self.logic.temporalUnwrap(flowFieldNode, 0, 5.0)
        unwrapDurationSec = time.time() - startTime
        segmentationNodes = [flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", c) for c in range(3)]
        self.report.checkTrue("Phase wrap segmentation is created for each component", all(segmentationNodes))
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        rows = []
        markedVoxels = 0
        for component, segmentationNode in enumerate(segmentationNodes):
            if not segmentationNode:
                continue
            segmentationSequenceNode = browserNode.GetSequenceNode(segmentationNode)
            self.report.checkTrue(f"Phase wrap segmentation {component} is a proxy node in the flow field's sequence browser",
                segmentationSequenceNode is not None)
            if not segmentationSequenceNode:
                continue
            self.report.checkEqual(f"Phase wrap segmentation {component} has a segmentation for each frame",
                segmentationSequenceNode.GetNumberOfDataNodes(), phantom.numberOfFrames)
            for frameIndex in range(segmentationSequenceNode.GetNumberOfDataNodes()):
                frameSegmentation = segmentationSequenceNode.GetNthDataNode(frameIndex)
                count = 0
                for segmentIndex in range(frameSegmentation.GetSegmentation().GetNumberOfSegments()):
                    segmentId = frameSegmentation.GetSegmentation().GetNthSegmentID(segmentIndex)
                    segmentArray = slicer.util.arrayFromSegmentBinaryLabelmap(frameSegmentation, segmentId, volumeNodeSet["magnitudeVolumeNode"])
                    count += int(np.count_nonzero(segmentArray))
                markedVoxels += count
                if count:
                    rows.append([component, frameIndex, count])
        self.report.table(["Component", "Frame", "Voxels marked as wrapped"], rows, "Phase wrap segmentation content")
        self.report.checkEqual("Number of voxels marked as phase wrapped", markedVoxels, expectedWrappedVoxels)

        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
        self.checkVelocityFrames("After temporal unwrapping", self.velocityFrames(flowFieldNode), expectedFrames,
            velocityQuantizationMPerSec(vencCmPerSec))
        self.report.text(f"Temporal unwrapping computation time: {unwrapDurationSec:.2f} s")

        peakFrame = phantom.peakFrameIndex()
        FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
        componentVolumeNode = flowFieldNode.GetNthNodeReference("componentVolume", 2)
        FlowTestingUtils.showVolumeInSliceViews(componentVolumeNode, phantom.centerRas)
        for c, segmentationNode in enumerate(segmentationNodes):
            if segmentationNode and segmentationNode.GetDisplayNode():
                segmentationNode.GetDisplayNode().SetVisibility(c == 2)
        self.report.screenshot("Component image (inplane_fh) at peak systole with phase wrap segmentation")

        # Reset
        self.logic.resetUnwrap(flowFieldNode)
        remaining = [flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", c) for c in range(3)]
        self.report.checkTrue("Resetting unwrapping removes phase wrap segmentations", not any(remaining), remaining, "[None, None, None]")
        self.report.checkEqual("Resetting unwrapping removes phase wrap segmentations from the scene",
            len(slicer.util.getNodesByClass("vtkMRMLSegmentationNode")), 0)
        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
        resetError = max(float(np.abs(f - e).max()) for f, e in zip(self.velocityFrames(flowFieldNode), expectedFrames))
        self.report.checkTrue("After reset, the flow field is computed without unwrapping", resetError > 0.5, f"{resetError:.3f} m/s", "> 0.5 m/s")

        with self.assertRaises(NotImplementedError):
            self.logic.laplacianUnwrap(flowFieldNode)
        self.report.checkTrue("Laplacian unwrapping reports that it is not implemented", True)
        with self.assertRaises(RuntimeError):
            self.logic.temporalUnwrap(flowFieldNode, 1, 5.0)
        self.report.checkTrue("Temporal unwrapping with non-zero reference frame is rejected", True)

    @reportedTest("Manual phase wrap correction",
        "Users can manually mark wrapped voxels by painting into the phase wrap segmentation (for example, where temporal"
        " unwrapping fails). Voxels marked as positive (negative) 1x wrap must be shifted by +2 venc (-2 venc).")
    def test_09_ManualPhaseWrapCorrection(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom()
        volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
        flowFieldNode = self.createFlowField(volumeNodeSet, True, unwrap=True)  # no wraps in the phantom
        frameIndex = phantom.peakFrameIndex()
        component = 2
        FlowTestingUtils.selectSequenceItem(flowFieldNode, frameIndex)
        segmentationNode = flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", component)
        self.report.checkTrue("Phase wrap segmentation exists", segmentationNode is not None)
        segmentIds = [segmentationNode.GetSegmentation().GetNthSegmentID(i) for i in range(segmentationNode.GetSegmentation().GetNumberOfSegments())]
        self.report.text(f"Phase wrap segment IDs: {', '.join(segmentIds)}")

        # Mark a block in the tissue (stationary) region as positive wrap and another one as negative wrap
        componentVolumeNode = volumeNodeSet["componentVolumeNodes"][component]
        positiveMask = np.zeros(phantom.radialDistanceMm.shape, dtype=np.uint8)
        negativeMask = np.zeros(phantom.radialDistanceMm.shape, dtype=np.uint8)
        tissue = phantom.stationaryTissueMask()
        tissueIndices = np.argwhere(tissue)
        positiveMask[tuple(tissueIndices[: len(tissueIndices) // 4].T)] = 1
        negativeMask[tuple(tissueIndices[-len(tissueIndices) // 4:].T)] = 1
        slicer.util.updateSegmentBinaryLabelmapFromArray(positiveMask, segmentationNode, "Wrap-Pos-1x", componentVolumeNode)
        slicer.util.updateSegmentBinaryLabelmapFromArray(negativeMask, segmentationNode, "Wrap-Neg-1x", componentVolumeNode)
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(browserNode, segmentationNode)
        FlowTestingUtils.showVolumeInSliceViews(componentVolumeNode, phantom.centerRas)
        self.report.screenshot("Manually marked phase wrap regions (positive and negative 1x wrap) on the inplane_fh component image")

        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
        frame = self.velocityFrames(flowFieldNode)[frameIndex]
        expected = phantom.velocityVolumeArray(frameIndex)[..., component]
        shiftMPerSec = 2 * vencCmPerSec / 100.0
        positiveShift = float(np.median((frame[..., component] - expected)[positiveMask > 0]))
        negativeShift = float(np.median((frame[..., component] - expected)[negativeMask > 0]))
        unmarked = np.logical_and(positiveMask == 0, negativeMask == 0)
        unmarkedError = float(np.abs(frame[..., component] - expected)[unmarked].max())
        self.report.checkClose("Velocity shift in voxels marked as positive wrap", positiveShift, shiftMPerSec, atol=0.01, unit="m/s")
        self.report.checkClose("Velocity shift in voxels marked as negative wrap", negativeShift, -shiftMPerSec, atol=0.01, unit="m/s")
        self.report.checkClose("Velocity error in unmarked voxels", unmarkedError, 0.0, atol=velocityQuantizationMPerSec(vencCmPerSec), unit="m/s")
        otherFrameError = float(np.abs(self.velocityFrames(flowFieldNode)[0] - phantom.velocityVolumeArray(0)).max())
        self.report.checkClose("Other frames are not affected", otherFrameError, 0.0, atol=velocityQuantizationMPerSec(vencCmPerSec), unit="m/s")

    @reportedTest("Flow field visualization",
        "Default visualization: glyphs in slice views colored by speed, color range set from the velocity encoding,"
        " color legend. Vector volume flow fields require the vector field display node, which is only available in"
        " recent Slicer versions; on other versions the flow field must still be usable (no error).")
    def test_10_Visualization(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom()
        peakFrame = phantom.peakFrameIndex()
        for storeInTransform in [True, False]:
            slicer.mrmlScene.Clear()
            storage = self.storageName(storeInTransform)
            volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
            flowFieldNode = self.createFlowField(volumeNodeSet, storeInTransform)
            error = self.trySetDefaultVisualization(flowFieldNode)
            self.report.checkTrue(f"[{storage}] Default visualization can be set up", error is None, error or "no error", "no error")
            if error:
                continue
            self.logic.setFlowFieldVisualizationToDefault(flowFieldNode)  # repeated calls must not add more display nodes
            displayNode = self.logic.getFlowFieldDisplayNode(flowFieldNode)
            if not storeInTransform and not FlowTestingUtils.isVectorFieldDisplayAvailable():
                self.report.checkTrue(f"[{storage}] No glyph display node in this Slicer version (vector field display node is not available)",
                    displayNode is None)
                self.report.text("Vector field display node is not available in this Slicer version: flow vectors of"
                    " vector volume flow fields cannot be displayed as glyphs.")
                continue
            self.report.checkTrue(f"[{storage}] Glyph display node is created", displayNode is not None)
            if not displayNode:
                continue
            glyphDisplayNodes = [flowFieldNode.GetNthDisplayNode(i) for i in range(flowFieldNode.GetNumberOfDisplayNodes())
                if flowFieldNode.GetNthDisplayNode(i).IsA("vtkMRMLTransformDisplayNode") or flowFieldNode.GetNthDisplayNode(i).IsA("vtkMRMLVectorFieldDisplayNode")]
            self.report.checkEqual(f"[{storage}] Number of glyph display nodes after repeated calls", len(glyphDisplayNodes), 1)
            self.report.checkTrue(f"[{storage}] Visible in slice views", displayNode.GetVisibility() and displayNode.GetVisibility2D())
            # Transform display node and earlier vector field display node: "region", current vector field display node: "samplingRegion"
            regionNode = displayNode.GetSamplingRegionNode() if hasattr(displayNode, "GetSamplingRegionNode") else displayNode.GetRegionNode()
            self.report.checkTrue(f"[{storage}] Region is the magnitude volume", regionNode == volumeNodeSet["magnitudeVolumeNode"])
            colorNode = displayNode.GetColorNode()
            self.report.checkEqual(f"[{storage}] Color node category", colorNode.GetAttribute("Category") if colorNode else None, "Flow")
            colorRange = colorNode.GetColorTransferFunction().GetRange() if colorNode else (0, 0)
            self.report.checkClose(f"[{storage}] Color map range maximum (velocity encoding)", colorRange[1], vencCmPerSec / 100.0, atol=1e-6, unit="m/s")
            colorLegendNode = slicer.modules.colors.logic().GetColorLegendDisplayNode(displayNode)
            self.report.checkTrue(f"[{storage}] Color legend is shown", colorLegendNode is not None)
            if storeInTransform:
                self.report.checkClose(f"[{storage}] Glyph spacing", displayNode.GetGlyphSpacingMm(), 2.0, atol=1e-6, unit="mm")
            else:
                self.report.checkEqual(f"[{storage}] Scalar range uses color node range", displayNode.GetScalarRangeFlag(),
                    slicer.vtkMRMLDisplayNode.UseColorNodeScalarRange)
            self.showFlowFieldAtFrame(flowFieldNode, peakFrame, phantom)
            self.report.screenshot(f"Default flow field visualization ({storage}) at peak systole")

    @reportedTest("Export to NRRD stack",
        "Each frame of the flow field is written to a separate NRRD file, with velocity unit and transform direction"
        " in the header. The written files are loaded back and compared to the analytic velocity.")
    def test_11_ExportNrrdStack(self):
        try:
            import nrrd  # noqa: F401
        except ImportError:
            self.report.text("pynrrd is not installed, the module installs it on first use.")
        vencCmPerSec = 150.0
        phantom = FlowPhantom(numberOfFrames=4)
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        for storeInTransform in [True, False]:
            slicer.mrmlScene.Clear()
            storage = self.storageName(storeInTransform)
            volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
            flowFieldNode = self.createFlowField(volumeNodeSet, storeInTransform)
            exportDir = self.temporaryDirectory("Import4DFlowNrrdStack_")
            self.logic.exportDisplacementFieldToFiles(flowFieldNode, exportDir, Import4DFlowLogic.EXPORT_FORMAT_NRRD_STACK)
            prefix = "transform" if storeInTransform else "velocity"
            files = sorted(f for f in os.listdir(exportDir) if f.endswith(".nrrd"))
            self.report.checkEqual(f"[{storage}] Exported files", files, [f"{prefix}_{i:02d}.nrrd" for i in range(phantom.numberOfFrames)])
            import nrrd
            fileErrors = []
            loadedErrors = []
            # Slicer versions that can read spatial vectors from NRRD files provide measurement frame information in the NRRD reader
            import vtkTeem
            spatialVectorNrrdReadingSupported = hasattr(vtkTeem.vtkTeemNRRDReader(), "GetMeasurementFrameSpecified")
            rasToLps = np.array([-1.0, -1.0, 1.0])
            for frameIndex, fileName in enumerate(files):
                filePath = os.path.join(exportDir, fileName)
                data, header = nrrd.read(filePath)
                self.report.checkEqual(f"[{storage}] {fileName}: sample units", header.get("sample units"), "m/s")
                if storeInTransform:
                    self.report.checkEqual(f"[{storage}] {fileName}: transform direction", header.get("TransformDirection"), "to parent")
                self.report.checkTrue(f"[{storage}] {fileName}: no intent_code field", "intent_code" not in header)
                # Vectors in NRRD files are stored in LPS coordinate system (file axes: component, I, J, K)
                fileVelocityLps = np.asarray(data).transpose(3, 2, 1, 0)
                fileErrors.append(float(np.abs(fileVelocityLps - expectedFrames[frameIndex] * rasToLps).max()))
                if storeInTransform:
                    loadedNode = slicer.util.loadTransform(filePath)
                    velocity = slicer.util.arrayFromGridTransform(loadedNode)
                else:
                    loadedNode = slicer.util.loadVolume(filePath)
                    velocity = slicer.util.arrayFromVolume(loadedNode)
                    if spatialVectorNrrdReadingSupported:
                        self.report.checkEqual(f"[{storage}] {fileName}: loaded as spatial vector volume", loadedNode.GetVoxelVectorType(),
                            slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial)
                    else:
                        # This Slicer version does not convert spatial vectors from LPS (file) to RAS when it reads
                        # NRRD files. Compare to the LPS vectors (to check that the image is loaded correctly otherwise).
                        velocity = velocity * rasToLps
                loadedErrors.append(float(np.abs(velocity - expectedFrames[frameIndex]).max()))
                slicer.mrmlScene.RemoveNode(loadedNode)
            self.report.checkClose(f"[{storage}] Maximum velocity error in files (LPS vectors)", max(fileErrors), 0.0,
                atol=velocityQuantizationMPerSec(vencCmPerSec), unit="m/s")
            self.report.checkClose(f"[{storage}] Maximum velocity error in files loaded back into Slicer", max(loadedErrors), 0.0,
                atol=velocityQuantizationMPerSec(vencCmPerSec), unit="m/s")
            if not storeInTransform and not spatialVectorNrrdReadingSupported:
                self.report.text("Slicer limitation: this Slicer version does not convert spatial vectors from LPS (file) to RAS"
                    " when it loads a vector volume from a NRRD file (fixed in vtkMRMLNRRDStorageNode in later Slicer versions),"
                    " therefore the loaded vectors were compared to LPS vectors. Use the 5D NRRD export to load the flow field"
                    " back into this Slicer version.")

    @reportedTest("Export to 5D NRRD file",
        "All frames of the flow field are written into a single 5D NRRD file (vector, 3 spatial axes, time), which is"
        " loaded back as a volume sequence and compared to the analytic velocity and image geometry.")
    def test_12_ExportNrrd5D(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom(numberOfFrames=5)
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        rows = []
        for storeInTransform in [True, False]:
            slicer.mrmlScene.Clear()
            storage = self.storageName(storeInTransform)
            volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
            flowFieldNode = self.createFlowField(volumeNodeSet, storeInTransform)
            exportDir = self.temporaryDirectory("Import4DFlowNrrd5D_")
            startTime = time.time()
            self.logic.exportDisplacementFieldToFiles(flowFieldNode, exportDir, Import4DFlowLogic.EXPORT_FORMAT_NRRD_5D)
            durationSec = time.time() - startTime
            exportedFile = os.path.join(exportDir, "flowfield.seq.nrrd")
            self.report.checkTrue(f"[{storage}] File is written", os.path.exists(exportedFile))
            if not os.path.exists(exportedFile):
                continue
            with open(exportedFile, "rb") as f:
                header = f.read(2000).decode("ascii", "replace").split("\n\n")[0]
            self.report.checkTrue(f"[{storage}] NRRD dimension is 5", "dimension: 5" in header)
            self.report.checkTrue(f"[{storage}] NRRD kinds", "kinds: vector domain domain domain list" in header)
            loadedSequenceNode = slicer.util.loadNodeFromFile(exportedFile, "SequenceFile")
            self.report.checkEqual(f"[{storage}] Number of frames loaded back", loadedSequenceNode.GetNumberOfDataNodes(), phantom.numberOfFrames)
            indexValues = [float(loadedSequenceNode.GetNthIndexValue(i)) for i in range(loadedSequenceNode.GetNumberOfDataNodes())]
            self.report.checkEqual(f"[{storage}] Frame times loaded back", indexValues, phantom.frameTimesMs)
            maxErrors = []
            geometryErrors = []
            phantomIjkToRas = phantom.ijkToRasMatrix()
            for frameIndex in range(loadedSequenceNode.GetNumberOfDataNodes()):
                frameNode = loadedSequenceNode.GetNthDataNode(frameIndex)
                maxErrors.append(float(np.abs(slicer.util.arrayFromVolume(frameNode) - expectedFrames[frameIndex]).max()))
                ijkToRas = vtk.vtkMatrix4x4()
                frameNode.GetIJKToRASMatrix(ijkToRas)
                geometryErrors.append(max(abs(ijkToRas.GetElement(r, c) - phantomIjkToRas.GetElement(r, c)) for r in range(3) for c in range(4)))
            self.report.checkClose(f"[{storage}] Maximum velocity error (RAS) in loaded file", max(maxErrors), 0.0,
                atol=velocityQuantizationMPerSec(vencCmPerSec), unit="m/s")
            self.report.checkClose(f"[{storage}] Maximum geometry error in loaded file", max(geometryErrors), 0.0, atol=1e-4)
            self.report.checkEqual(f"[{storage}] No temporary nodes are left in the scene",
                len([n for n in slicer.util.getNodesByClass("vtkMRMLVectorVolumeNode") if "temp" in n.GetName()]), 0)
            rows.append([storage, f"{os.path.getsize(exportedFile) / 1e6:.2f}", f"{durationSec:.2f}"])
            self.report.text(f"5D NRRD header ({storage}):\n\n```\n{header.strip()}\n```")
        self.report.table(["Storage", "File size (MB)", "Export time (s)"], rows)

    @reportedTest("Export to anonymized scene",
        "The scene is saved as MRB with all DICOM attributes and identifiers removed and the patient renamed to 'Anonymous'."
        " The current scene must not be changed.")
    def test_13_ExportAnonymizedScene(self):
        from DICOMLib import DICOMUtils
        if not hasattr(slicer.vtkMRMLSubjectHierarchyNode, "GetItemUIDNames"):
            self.skipTest("Anonymization requires Slicer-5.7 or later")
        phantom = FlowPhantom(dims=(20, 20, 10), spacingMm=(2.0, 2.0, 2.5), numberOfFrames=3, tissueRadiusMm=16.0)
        dicomDir = self.temporaryDirectory("Import4DFlowAnon_")
        phantom.writeDicomSeries(os.path.join(dicomDir, "dicom"), 150.0, patientName="Secret^Patient")
        exportDir = os.path.join(dicomDir, "export")
        os.makedirs(exportDir)
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(dicomDir, "db")) as db:
            DICOMUtils.importDicom(os.path.join(dicomDir, "dicom"), db)
            FlowTestingUtils.loadDicomSeriesAsVolumeSequences()
            volumeNodeSet = list(self.logic.findVolumeNodeSets().values())[0]
            self.createFlowField(volumeNodeSet, True)
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        def countIdentifiers(scene):
            dicomAttributes = 0
            nodes = scene.GetNodes()
            for i in range(nodes.GetNumberOfItems()):
                node = nodes.GetItemAsObject(i)
                dicomAttributes += len([a for a in node.GetAttributeNames() if a.startswith("DICOM") or a == "MultiVolume.FrameFileList"])
            sh = scene.GetSubjectHierarchyNode()
            children = vtk.vtkIdList()
            sh.GetItemChildren(sh.GetSceneItemID(), children, True)
            dicomUids = 0
            patientNames = []
            for i in range(children.GetNumberOfIds()):
                itemId = children.GetId(i)
                dicomUids += len([u for u in sh.GetItemUIDNames(itemId) if u.startswith("DICOM")])
                dicomAttributes += len([a for a in sh.GetItemAttributeNames(itemId) if a.startswith("DICOM")])
                if sh.GetItemLevel(itemId) == "Patient":
                    patientNames.append(sh.GetItemName(itemId))
            return dicomAttributes, dicomUids, patientNames

        originalCounts = countIdentifiers(slicer.mrmlScene)
        self.report.checkTrue("Original scene contains DICOM attributes and UIDs", originalCounts[0] > 0 and originalCounts[1] > 0,
            originalCounts[:2], "> 0")
        rootDirectoryBefore = slicer.mrmlScene.GetRootDirectory()
        self.logic.exportDisplacementFieldToFiles(None, exportDir, Import4DFlowLogic.EXPORT_FORMAT_ANONYMIZED_SCENE)
        exportedFiles = os.listdir(exportDir)
        self.report.checkEqual("Exported files", exportedFiles, ["4DFlow-anon.mrb"])
        self.report.checkEqual("Scene root directory is not changed by export", slicer.mrmlScene.GetRootDirectory(), rootDirectoryBefore)
        self.report.checkEqual("Original scene is not modified (DICOM attributes, UIDs, patient names)", countIdentifiers(slicer.mrmlScene), originalCounts)
        if "4DFlow-anon.mrb" not in exportedFiles:
            return
        with open(os.path.join(exportDir, "4DFlow-anon.mrb"), "rb") as f:
            content = f.read()
        self.report.checkTrue("Patient name does not appear in the exported file", b"Secret" not in content)
        slicer.mrmlScene.Clear()
        slicer.util.loadScene(os.path.join(exportDir, "4DFlow-anon.mrb"))
        dicomAttributes, dicomUids, patientNames = countIdentifiers(slicer.mrmlScene)
        self.report.checkEqual("DICOM attributes in anonymized scene", dicomAttributes, 0)
        self.report.checkEqual("DICOM UIDs in anonymized scene", dicomUids, 0)
        self.report.checkEqual("Patient names in anonymized scene", patientNames, ["Anonymous"])
        flowFieldNodes = [n for n in slicer.util.getNodesByClass("vtkMRMLTransformNode") if n.GetAttribute("SlicerHeart.Type") == "FlowField"]
        self.report.checkEqual("Flow field in anonymized scene", len(flowFieldNodes), 1)
        self.report.checkTrue("Flow field magnitude volume reference in anonymized scene",
            bool(flowFieldNodes) and flowFieldNodes[0].GetNodeReference("magnitudeVolume") is not None)

    @reportedTest("Export format validation", "Unknown export formats are rejected.")
    def test_14_ExportInvalidFormat(self):
        with self.assertRaises(ValueError):
            self.logic.exportDisplacementFieldToFiles(None, self.temporaryDirectory("Import4DFlowExport_"), "INVALID")
        self.report.checkTrue("ValueError is raised for unknown export format", True)

    @reportedTest("Scene save and reload",
        "Flow fields of both storage types (with phase wrap segmentations and visualization) are saved in a scene (MRB),"
        " the scene is reloaded, and the flow field, references, and velocity values must be the same.")
    def test_15_SceneSaveReload(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom(numberOfFrames=4)
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
        transformFlowField = self.createFlowField(volumeNodeSet, True, unwrap=True)
        self.logic.setFlowFieldVisualizationToDefault(transformFlowField)
        volumeFlowField = self.createFlowField(volumeNodeSet, False)
        error = self.trySetDefaultVisualization(volumeFlowField)
        if error:
            self.report.text(f"Visualization of the vector volume flow field could not be set up (see visualization test): {error}")
        transformFlowField.SetName("FlowFieldTransform")
        volumeFlowField.SetName("FlowFieldVolume")
        sceneFile = os.path.join(self.temporaryDirectory("Import4DFlowScene_"), "FlowScene.mrb")
        self.report.checkTrue("Scene is saved", slicer.util.saveScene(sceneFile))
        slicer.mrmlScene.Clear()
        slicer.util.loadScene(sceneFile)
        for className, storage in [("vtkMRMLTransformNode", "grid transform"), ("vtkMRMLVectorVolumeNode", "vector volume")]:
            flowFieldNodes = [n for n in slicer.util.getNodesByClass(className) if n.GetAttribute("SlicerHeart.Type") == "FlowField"
                and slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(n)]
            self.report.checkEqual(f"[{storage}] Flow field proxy nodes after reload", len(flowFieldNodes), 1)
            if not flowFieldNodes:
                continue
            flowFieldNode = flowFieldNodes[0]
            self.report.checkTrue(f"[{storage}] Magnitude volume reference is restored", flowFieldNode.GetNodeReference("magnitudeVolume") is not None)
            self.report.checkTrue(f"[{storage}] Component volume references are restored",
                all(flowFieldNode.GetNthNodeReference("componentVolume", c) is not None for c in range(3)))
            self.checkVelocityFrames(f"[{storage}] Velocity after reload", self.velocityFrames(flowFieldNode), expectedFrames,
                velocityQuantizationMPerSec(vencCmPerSec))
            if storage == "grid transform":
                self.report.checkTrue(f"[{storage}] Phase wrap segmentations are restored",
                    all(flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", c) is not None for c in range(3)))
                displayNode = self.logic.getFlowFieldDisplayNode(flowFieldNode)
                self.report.checkTrue(f"[{storage}] Glyph display node is restored", displayNode is not None)
                if displayNode:
                    colorNode = displayNode.GetColorNode()
                    self.report.checkTrue(f"[{storage}] Speed color map is restored", colorNode is not None and colorNode.GetAttribute("Category") == "Flow")
                # Flow field can be updated after reload
                self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
                self.checkVelocityFrames(f"[{storage}] Velocity recomputed after reload", self.velocityFrames(flowFieldNode), expectedFrames,
                    velocityQuantizationMPerSec(vencCmPerSec))

    @reportedTest("Module GUI workflow",
        "The complete workflow is performed using the module GUI: find images, create flow field (both storage formats,"
        " selected by the 'Store in transform' checkbox, which is saved in application settings), compute phase unwrapping"
        " (each mode), recompute flow field, show flow field / magnitude / component images, and export (each format).")
    def test_16_GuiWorkflow(self):
        from DICOMLib import DICOMUtils
        vencCmPerSec = 70.0  # phase wraps
        phantom = FlowPhantom(dims=(28, 28, 16), spacingMm=(1.5, 1.5, 2.0), numberOfFrames=8, tissueRadiusMm=20.0)
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        dicomDir = self.temporaryDirectory("Import4DFlowGui_")
        phantom.writeDicomSeries(os.path.join(dicomDir, "dicom"), vencCmPerSec)
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(dicomDir, "db")) as db:
            DICOMUtils.importDicom(os.path.join(dicomDir, "dicom"), db)
            FlowTestingUtils.loadDicomSeriesAsVolumeSequences()

            slicer.util.selectModule("Import4DFlow")
            widget = slicer.modules.import4dflow.widgetRepresentation().self()
            widget.onInspectButton()
            self.report.checkEqual("Image sets listed in GUI", widget.ui.inputVolumeNodeSetSelector.count, 1)
            self.report.checkEqual("Image set name in GUI", widget.ui.inputVolumeNodeSetSelector.currentText, "Phantom, Flow (20240102)")
            self.report.checkTrue("Convert button is enabled", widget.ui.convertButton.enabled)
            parameterNode = widget._parameterNode

            # Vector volume storage
            widget.ui.storeInTransformCheckBox.checked = False
            self.report.checkEqual("Storage format setting is saved in application settings",
                slicer.util.settingsValue(widget.storeInTransformSettingsKey, True, converter=slicer.util.toBool), False)
            try:
                widget.onConvertButton()
                error = None
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
            self.report.checkTrue("[GUI] 'Create flow field' with vector volume storage completes without error", error is None, error or "no error", "no error")
            volumeFlowField = parameterNode.outputFlowField
            self.report.checkTrue("[GUI] Flow field is created as vector volume", volumeFlowField is not None and volumeFlowField.IsA("vtkMRMLVectorVolumeNode"))
            if volumeFlowField and volumeFlowField.IsA("vtkMRMLVectorVolumeNode"):
                self.checkVelocityFrames("[GUI, vector volume] Velocity (temporal unwrapping is applied automatically)",
                    self.velocityFrames(volumeFlowField), expectedFrames, velocityQuantizationMPerSec(vencCmPerSec))

            # Grid transform storage
            widget.ui.storeInTransformCheckBox.checked = True
            self.report.checkEqual("Storage format setting is updated", slicer.util.settingsValue(widget.storeInTransformSettingsKey, False,
                converter=slicer.util.toBool), True)
            widget.onConvertButton()
            flowFieldNode = parameterNode.outputFlowField
            self.report.checkTrue("[GUI] Flow field is created as grid transform", flowFieldNode is not None and flowFieldNode.IsA("vtkMRMLTransformNode"))
            self.checkVelocityFrames("[GUI, grid transform] Velocity", self.velocityFrames(flowFieldNode), expectedFrames,
                velocityQuantizationMPerSec(vencCmPerSec))
            buttonTexts = [getattr(widget.ui, f"showComponentVolume{c + 1}Button").text for c in range(3)]
            self.report.checkEqual("Component buttons show direction codes", buttonTexts, ["through", "inplane_ap", "inplane_fh"])
            activeBrowser = slicer.modules.sequences.toolBar().activeBrowserNode()
            self.report.checkTrue("Flow field sequence browser is activated in the toolbar",
                activeBrowser == slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode))
            FlowTestingUtils.selectSequenceItem(flowFieldNode, phantom.peakFrameIndex())
            slicer.app.layoutManager().sliceWidget("Red").mrmlSliceNode().JumpSliceByCentering(*phantom.centerRas)
            self.report.screenshot("Module GUI after creating the flow field (peak systole)", kind="window")

            # Show buttons
            displayNode = self.logic.getFlowFieldDisplayNode(flowFieldNode)
            visibility = displayNode.GetVisibility()
            widget.onShowFlowFieldButton()
            self.report.checkEqual("'Show flow field' button toggles glyph visibility (off)", bool(displayNode.GetVisibility()), not visibility)
            widget.onShowFlowFieldButton()
            self.report.checkEqual("'Show flow field' button toggles glyph visibility (on)", bool(displayNode.GetVisibility()), bool(visibility))
            widget.onShowComponentVolumeButton(2)
            redComposite = slicer.app.layoutManager().sliceWidget("Red").mrmlSliceCompositeNode()
            self.report.checkEqual("Component button shows the component image",
                redComposite.GetBackgroundVolumeID(), flowFieldNode.GetNthNodeReference("componentVolume", 2).GetID())
            self.report.checkTrue("Component button selects the phase wrap segmentation in the segment editor",
                widget.ui.segmentEditorWidget.segmentationNode() == flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", 2))
            self.report.screenshot("Component image with phase wrap segmentation selected for editing", kind="window")
            widget.onShowMagnitudeVolumeButton()
            self.report.checkEqual("Magnitude button shows the magnitude image",
                redComposite.GetBackgroundVolumeID(), flowFieldNode.GetNodeReference("magnitudeVolume").GetID())

            # Unwrapping modes
            parameterNode.unwrapMode = UnwrapModeEnum.NoUnwrap
            widget.onComputePhaseUnwrappingButton()
            widget.onRecomputeFlowFieldButton()
            wrappedError = max(float(np.abs(f - e).max()) for f, e in zip(self.velocityFrames(flowFieldNode), expectedFrames))
            self.report.checkTrue("[GUI] No unwrapping: velocity is wrapped", wrappedError > 0.5, f"{wrappedError:.3f} m/s", "> 0.5 m/s")
            parameterNode.unwrapMode = UnwrapModeEnum.TemporalUnwrap
            widget.onComputePhaseUnwrappingButton()
            widget.onRecomputeFlowFieldButton()
            self.checkVelocityFrames("[GUI] Temporal unwrapping, then recompute", self.velocityFrames(flowFieldNode), expectedFrames,
                velocityQuantizationMPerSec(vencCmPerSec))
            parameterNode.unwrapMode = UnwrapModeEnum.LaplacianUnwrap
            with self.assertRaises(NotImplementedError):
                widget.onComputePhaseUnwrappingButton()
            self.report.checkTrue("[GUI] Laplacian unwrapping reports an error", True)

            # Recompute with background subtraction
            parameterNode.backgroundSubtractionMethod = BackgroundSubtractionMethodEnum.LinearFit
            widget.onRecomputeFlowFieldButton()
            self.checkVelocityFrames("[GUI] Recompute with linear background fit (phantom has no background error)",
                self.velocityFrames(flowFieldNode), expectedFrames, 0.01)
            parameterNode.backgroundSubtractionMethod = BackgroundSubtractionMethodEnum.NoSubtraction

            # Export (anonymized scene file name is based on the scene file name, if the scene was loaded from file)
            sceneUrl = slicer.mrmlScene.GetURL()
            anonymizedSceneFileName = (os.path.splitext(os.path.basename(sceneUrl))[0] if sceneUrl else "4DFlow") + "-anon.mrb"
            for exportFormat, expectedFile in [(Import4DFlowLogic.EXPORT_FORMAT_NRRD_5D, "flowfield.seq.nrrd"),
                                               (Import4DFlowLogic.EXPORT_FORMAT_NRRD_STACK, "transform_00.nrrd"),
                                               (Import4DFlowLogic.EXPORT_FORMAT_ANONYMIZED_SCENE, anonymizedSceneFileName)]:
                exportDir = os.path.join(dicomDir, "export-" + exportFormat)
                os.makedirs(exportDir)
                parameterNode.exportDirectory = exportDir
                parameterNode.exportFormat = exportFormat
                self.report.checkEqual(f"[GUI] Export format combobox shows {exportFormat}", widget.ui.exportFormatComboBox.currentData, exportFormat)
                widget.onExportButton()
                self.report.checkTrue(f"[GUI] Export as {exportFormat} writes {expectedFile}", os.path.exists(os.path.join(exportDir, expectedFile)),
                    os.listdir(exportDir))
            self.report.screenshot("Module GUI after export", kind="window")

    @reportedTest("Anonymized clinical 4D flow MRI data set",
        "A real Siemens 4D flow acquisition is loaded from DICOM and converted to flow field (both storage formats)"
        " with temporal phase unwrapping. The two storage formats must give identical velocities, values must be plausible"
        " (below 3x velocity encoding), and the 5D NRRD export must reproduce the flow field.")
    def test_17_RealData(self):
        from DICOMLib import DICOMUtils
        dataDir = FlowTestingUtils.environmentValue(FlowTestingUtils.REAL_DATA_ENV_VARIABLE)
        if not dataDir or not os.path.isdir(dataDir):
            self.skipTest(f"Anonymized 4D flow data set is not available (set {FlowTestingUtils.REAL_DATA_ENV_VARIABLE} in the environment or in .env.local)")
        timings = []
        workDir = self.temporaryDirectory("Import4DFlowRealData_")
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(workDir, "db")) as db:
            startTime = time.time()
            DICOMUtils.importDicom(dataDir, db)
            timings.append(["Import DICOM files into database", time.time() - startTime])
            startTime = time.time()
            FlowTestingUtils.loadDicomSeriesAsVolumeSequences()
            timings.append(["Load series as volume sequences", time.time() - startTime])
            startTime = time.time()
            volumeNodeSets = self.logic.findVolumeNodeSets()
            timings.append(["Find 4D flow image sets", time.time() - startTime])
        self.report.checkEqual("Number of detected 4D flow image sets", len(volumeNodeSets), 1)
        if not volumeNodeSets:
            return
        volumeNodeSet = list(volumeNodeSets.values())[0]
        directionCodes = [self.logic._getSequenceAttribute(n, "SlicerHeart.directionCode") for n in volumeNodeSet["componentVolumeNodes"]]
        vencs = [float(self.logic._getSequenceAttribute(n, "SlicerHeart.vencCmPerSec")) for n in volumeNodeSet["componentVolumeNodes"]]
        heartRate = float(self.logic._getSequenceAttribute(volumeNodeSet["magnitudeVolumeNode"], "SlicerHeart.heartRateBpm") or "nan")
        magnitudeVolumeNode = volumeNodeSet["magnitudeVolumeNode"]
        numberOfFrames = self.logic._getNumberOfDataNodesInSequence(magnitudeVolumeNode)
        self.report.table(["Property", "Value"], [
            ["Direction codes (R, A, S)", directionCodes],
            ["Invert to RAS direction", volumeNodeSet["componentVolumeNodesInvertToRasDirection"]],
            ["Velocity encoding (cm/s)", vencs],
            ["Heart rate from DICOM (bpm)", heartRate],
            ["Number of frames", numberOfFrames],
            ["Image size (voxels)", magnitudeVolumeNode.GetImageData().GetDimensions()],
            ["Voxel spacing (mm)", magnitudeVolumeNode.GetSpacing()],
        ], "Detected 4D flow image set")
        self.report.checkTrue("All 3 velocity components are found", len(volumeNodeSet["componentVolumeNodes"]) == 3)
        self.report.checkRange("Heart rate", heartRate, 30, 220, "bpm")
        self.report.checkTrue("Number of frames", numberOfFrames > 1, numberOfFrames, "> 1")

        frames = {}
        flowFieldNodes = {}
        for storeInTransform in [True, False]:
            storage = self.storageName(storeInTransform)
            startTime = time.time()
            flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(
                volumeNodeSet["componentVolumeNodes"], volumeNodeSet["componentVolumeNodesInvertToRasDirection"],
                magnitudeVolumeNode, storeInTransform=storeInTransform)
            timings.append([f"Create flow field ({storage})", time.time() - startTime])
            startTime = time.time()
            self.logic.temporalUnwrap(flowFieldNode, 0, 5.0)
            timings.append([f"Temporal unwrapping ({storage})", time.time() - startTime])
            startTime = time.time()
            self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
            timings.append([f"Compute flow field ({storage})", time.time() - startTime])
            frames[storeInTransform] = self.velocityFrames(flowFieldNode)
            flowFieldNodes[storeInTransform] = flowFieldNode
        flowFieldNode = flowFieldNodes[True]
        # Creating the second flow field (from the same images) must not modify the first one
        sequenceNode = self.logic._getSequenceFromProxyNode(flowFieldNode)
        indexStrings = [sequenceNode.GetNthIndexValue(i) for i in range(sequenceNode.GetNumberOfDataNodes())]

        def toFloat(text):
            try:
                return float(text)
            except ValueError:
                return float("nan")

        indexValues = [toFloat(text) for text in indexStrings]
        self.report.checkEqual("Number of frames of the first flow field after creating a second flow field", len(indexStrings), numberOfFrames)
        self.report.checkTrue("Frame index values are increasing trigger times",
            all(not math.isnan(v) for v in indexValues) and all(b > a for a, b in zip(indexValues, indexValues[1:])), indexStrings)
        frames[True] = self.velocityFrames(flowFieldNode)
        difference = max(float(np.abs(a - b).max()) for a, b in zip(frames[True], frames[False]))
        self.report.checkClose("Grid transform and vector volume storage give the same velocities (max. difference)", difference, 0.0, atol=1e-5, unit="m/s")

        # Plausibility of velocity values
        speeds = [np.linalg.norm(frame, axis=-1) for frame in frames[True]]
        p99Speeds = [float(np.percentile(s[s > 0], 99)) if np.any(s > 0) else 0.0 for s in speeds]
        peakFrame = int(np.argmax(p99Speeds))
        maxSpeed = max(float(s.max()) for s in speeds)
        self.report.checkRange("Maximum speed (all frames, after unwrapping)", maxSpeed, 0.2, 3 * max(vencs) / 100.0, "m/s")
        segmentationNodes = [flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", c) for c in range(3)]
        self.report.checkTrue("Phase wrap segmentations are created", all(segmentationNodes))
        rows = [[i, f"{indexValues[i]:.1f}", p99Speeds[i], float(speeds[i].max())] for i in range(len(speeds))]
        self.report.table(["Frame", "Time (ms)", "99th percentile speed (m/s)", "Max. speed (m/s)"], rows, "Speed statistics per frame")

        # 5D NRRD export roundtrip
        exportDir = os.path.join(workDir, "export")
        os.makedirs(exportDir)
        startTime = time.time()
        exportedFile = self.logic.exportFlowFieldToNrrd5D(flowFieldNode, exportDir)
        timings.append(["Export to 5D NRRD", time.time() - startTime])
        loadedSequenceNode = slicer.util.loadNodeFromFile(exportedFile, "SequenceFile")
        roundtripError = max(float(np.abs(slicer.util.arrayFromVolume(loadedSequenceNode.GetNthDataNode(i)) - frames[True][i]).max())
            for i in range(loadedSequenceNode.GetNumberOfDataNodes()))
        self.report.checkClose("5D NRRD export roundtrip (max. velocity difference)", roundtripError, 0.0, atol=1e-5, unit="m/s")
        self.report.table(["Step", "Duration (s)"], [[name, f"{duration:.2f}"] for name, duration in timings], "Computation times")

        # Screenshots
        self.logic.setFlowFieldVisualizationToDefault(flowFieldNode)
        FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
        peakSpeed = speeds[peakFrame]
        peakIjk = np.unravel_index(np.argmax(peakSpeed * (peakSpeed < np.percentile(peakSpeed, 99.9))), peakSpeed.shape)
        ijkToRas = vtk.vtkMatrix4x4()
        magnitudeVolumeNode.GetIJKToRASMatrix(ijkToRas)
        peakRas = ijkToRas.MultiplyPoint([peakIjk[2], peakIjk[1], peakIjk[0], 1])[:3]
        FlowTestingUtils.showVolumeInSliceViews(magnitudeVolumeNode, peakRas)
        self.report.screenshot(f"Flow field (grid transform) at frame {peakFrame} ({indexValues[peakFrame]:.0f} ms), slice views centered at a high-speed voxel")
        slicer.util.selectModule("Import4DFlow")
        self.report.screenshot("Application window with the clinical data set", kind="window")
