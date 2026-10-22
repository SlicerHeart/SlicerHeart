"""Feature tests of the Analyze4DFlow module.

Flow fields are created from an analytic flow phantom (pulsatile Poiseuille flow in an oblique vessel) in all supported
storage formats: grid transform sequence and vector volume sequence (created by the Import4DFlow module) and model
sequence (CFD-like unstructured grid with velocity point data). Computed flow metrics are compared to analytic values.
If available, an anonymized clinical 4D flow MRI data set is analyzed as well.
Results are written into a markdown report with screenshots (see FlowTestingUtils.TestReport).

Run from the Slicer Python console:

    import slicer.testing
    slicer.testing.runUnitTest([r"<path>/Analyze4DFlow/Testing/Python"], "Analyze4DFlowFeaturesTest")
"""

import math
import os
import shutil
import sys
import tempfile
import time

import numpy as np
import vtk
import vtk.util.numpy_support

import slicer

# Shared test utilities are in the Import4DFlow module's testing folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Import4DFlow", "Testing", "Python")))
import FlowTestingUtils  # noqa: E402
from FlowTestingUtils import FlowPhantom, reportedTest  # noqa: E402

from Analyze4DFlow import Analyze4DFlowLogic  # noqa: E402
from Import4DFlow import Import4DFlowLogic, BackgroundSubtractionMethodEnum  # noqa: E402

KINDS = ["transform", "volume", "model"]
KIND_NAMES = {"transform": "grid transform", "volume": "vector volume", "model": "model (CFD)"}


def tableToDict(tableNode):
    result = {}
    if not tableNode:
        return result
    table = tableNode.GetTable()
    for columnIndex in range(table.GetNumberOfColumns()):
        column = table.GetColumn(columnIndex)
        result[column.GetName()] = [column.GetValue(row) for row in range(column.GetNumberOfTuples())]
    return result


class Analyze4DFlowFeaturesTest(FlowTestingUtils.FeatureTestCase):

    REPORT_SUITE_NAME = "Analyze4DFlow"
    REPORT_TITLE = "Analyze 4D Flow - feature test report"
    REPORT_DESCRIPTION = (
        "Automated tests of all features of the *Analyze 4D Flow* module: flow quantification in a measurement plane"
        " (flow rate, area, velocity statistics, forward/backward volume, regurgitation fraction, cardiac output, pressure gradient),"
        " vessel masking (segmentation or speed threshold), streamlines, speed volume (magnitude or projected to the plane normal),"
        " masked flow field output, flow metrics plot, heart rate handling, and the module GUI, for all supported flow field"
        " types: grid transform sequence and vector volume sequence (4D flow MRI imported by *Import 4D Flow*), and model sequence"
        " (CFD result).\n\n"
        "The analytic phantom is a pulsatile Poiseuille flow in an oblique cylindrical vessel (radius 10 mm, peak centerline"
        " velocity 1 m/s, 20% backflow) imaged with an oblique volume (1.5x1.5x2 mm voxels). Expected values are computed"
        " from the analytic solution (for example, flow rate Q = pi R^2 vmax / 2).")

    def setUp(self):
        super().setUp()
        self.logic = Analyze4DFlowLogic()
        self.importLogic = Import4DFlowLogic()
        self.temporaryDirectories = []

    def tearDown(self):
        for directory in self.temporaryDirectories:
            shutil.rmtree(directory, ignore_errors=True)

    def temporaryDirectory(self, prefix):
        directory = tempfile.mkdtemp(prefix=prefix, dir=slicer.app.temporaryPath)
        self.temporaryDirectories.append(directory)
        return directory

    # Helpers

    def createFlowField(self, phantom, kind, vencCmPerSec=150.0, velocityArrayName="V"):
        """Create a flow field of the given kind. Returns (flowFieldNode, referenceVolumeNode)."""
        if kind in ["transform", "volume"]:
            volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
            flowFieldNode = self.importLogic.createFlowFieldFromComponentVolumes(
                volumeNodeSet["componentVolumeNodes"], volumeNodeSet["componentVolumeNodesInvertToRasDirection"],
                volumeNodeSet["magnitudeVolumeNode"], storeInTransform=(kind == "transform"))
            self.importLogic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
            return flowFieldNode, volumeNodeSet["magnitudeVolumeNode"]
        flowFieldNode, _, _ = phantom.createFlowModelSequence(velocityArrayName)
        self.logic.setHeartRateBpm(flowFieldNode, phantom.heartRateBpm(), "test")
        referenceVolumeNode = phantom.createVolumeNode(phantom.magnitudeVolumeArray(), "Reference", addToScene=True)
        return flowFieldNode, referenceVolumeNode

    def analyze(self, flowFieldNode, planeNode, segmentationNode=None, segmentId=None, speedThreshold=0.1,
                streamlines=False, speedVolume=False, projected=False, maskedOutput=None, maximumLengthMm=100,
                bidirectional=True, computeAllMetrics=False, samplingDistanceMm=1.0, summary=True):
        """Run analysis. Returns (outputs, metrics, summaryMetrics), where metrics and summaryMetrics are dicts of column values."""
        outputs = {"metricsModel": slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Flow metrics")}
        if streamlines:
            outputs["streamlines"] = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Streamlines")
        if speedVolume:
            outputs["speedVolume"] = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Speed")
        if maskedOutput:
            outputs["maskedFlowField"] = maskedOutput
        self.logic.sampleFlowFieldWithPlane(planeNode, flowFieldNode,
            samplingDistanceMm=samplingDistanceMm,
            outputStreamlinesModel=outputs.get("streamlines"),
            outputFlowMetricsModel=outputs["metricsModel"],
            maskSegmentationNode=segmentationNode, maskSegmentID=segmentId,
            streamlinesMaximumLengthMm=maximumLengthMm, streamlinesBidirectional=bidirectional,
            streamlinesComputeAllMetrics=computeAllMetrics, streamlinesSpeedThresholdMPerSec=speedThreshold,
            outputSpeedVolume=outputs.get("speedVolume"), speedVolumeProjectedToPlane=projected,
            outputMaskedFlowField=maskedOutput)
        outputs["table"] = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Flow metrics table")
        outputs["summaryTable"] = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Flow metrics summary") if summary else None
        self.logic.computeFlowMetricsTable(outputs["metricsModel"], planeNode, flowFieldNode, speedThreshold,
            outputs["table"], outputs["summaryTable"])
        summaryMetrics = {name: values[0] for name, values in tableToDict(outputs["summaryTable"]).items()}
        return outputs, tableToDict(outputs["table"]), summaryMetrics

    def checkMetricsAgainstPhantom(self, label, phantom, metrics, summaryMetrics, speedThreshold=0.0,
                                   flowRtol=0.08, areaRtol=0.15, segmentationMask=True):
        """Compare per-frame and summary metrics to analytic values. Returns table rows."""
        rows = []
        expectedFlows = [phantom.expectedFlowRateMlPerSec(i, 0.0 if segmentationMask else speedThreshold) for i in range(phantom.numberOfFrames)]
        peakFlow = max(abs(f) for f in expectedFlows)
        for frameIndex in range(phantom.numberOfFrames):
            vmax = abs(phantom.maxVelocity(frameIndex))
            expectedArea = phantom.expectedAreaMm2(frameIndex, 0.0 if segmentationMask else speedThreshold)
            rows.append([frameIndex, metrics["Time"][frameIndex], metrics["FlowRate"][frameIndex], expectedFlows[frameIndex],
                metrics["Area"][frameIndex], expectedArea, metrics["MaxVelocity"][frameIndex], vmax * 100,
                metrics["MeanVelocity"][frameIndex], (phantom.expectedMeanSpeedMPerSec(frameIndex) * 100) if segmentationMask else ""])
            # Flow rate: relative tolerance of the peak flow (so frames with near-zero flow are not over-weighted)
            self.report.checkClose(f"{label} Flow rate, frame {frameIndex}", metrics["FlowRate"][frameIndex], expectedFlows[frameIndex],
                atol=flowRtol * peakFlow, unit="ml/s")
            if vmax > 2 * speedThreshold:
                self.report.checkClose(f"{label} Max. velocity, frame {frameIndex}", metrics["MaxVelocity"][frameIndex], vmax * 100,
                    rtol=0.05, atol=1.0, unit="cm/s")
                self.report.checkClose(f"{label} Area, frame {frameIndex}", metrics["Area"][frameIndex], expectedArea, rtol=areaRtol, unit="mm2")
        self.report.checkEqual(f"{label} Frame times", [round(t, 3) for t in metrics["Time"]], [round(t, 3) for t in phantom.frameTimesMs])
        peakFrame = phantom.peakFrameIndex()
        if segmentationMask:
            self.report.checkClose(f"{label} Mean velocity at peak systole", metrics["MeanVelocity"][peakFrame],
                phantom.expectedMeanSpeedMPerSec(peakFrame) * 100, rtol=0.1, unit="cm/s")

        if summaryMetrics:
            forward, backward = phantom.expectedForwardBackwardVolumeMl(expectedFlows)
            heartRate = phantom.heartRateBpm()
            vmaxPeak = phantom.peakVelocityMPerSec
            expectedSummary = [
                ("ForwardVolume", forward, 0.08, 0.0, "ml"),
                ("BackwardVolume", backward, 0.0, 0.08 * abs(forward), "ml"),
                ("TotalVolume", forward + backward, 0.0, 0.08 * abs(forward), "ml"),
                ("RegurgitationFraction", -backward / forward * 100, 0.0, 2.0, "%"),
                ("VolPerMinute", forward / 1000 * heartRate, 0.08, 0.0, "l/min"),
                ("EffectiveVolPerMinute", (forward + backward) / 1000 * heartRate, 0.0, 0.08 * forward / 1000 * heartRate, "l/min"),
                ("PeakVelocity", vmaxPeak * 100, 0.05, 0.0, "cm/s"),
                ("MaxPressureGradient", 4 * vmaxPeak ** 2, 0.1, 0.0, "mmHg"),
                ("MaxFlow", max(expectedFlows), 0.08, 0.0, "ml/s"),
            ]
            summaryRows = []
            for name, expected, rtol, atol, unit in expectedSummary:
                measured = summaryMetrics.get(name, float("nan"))
                summaryRows.append([name, measured, expected, unit])
                self.report.checkClose(f"{label} {name}", measured, expected, rtol=rtol, atol=atol, unit=unit)
            self.report.table(["Metric", "Measured", "Expected (analytic)", "Unit"], summaryRows, f"{label} Summary metrics")
        self.report.table(["Frame", "Time (ms)", "Flow rate (ml/s)", "Expected flow rate", "Area (mm2)", "Expected area",
            "Max. velocity (cm/s)", "Expected max. velocity", "Mean velocity (cm/s)", "Expected mean velocity"], rows,
            f"{label} Flow metrics per frame")
        return rows

    def showResults(self, flowFieldNode, planeNode, phantom, frameIndex, speedVolumeNode=None, streamlinesNode=None):
        FlowTestingUtils.selectSequenceItem(flowFieldNode, frameIndex)
        backgroundNode = flowFieldNode.GetNodeReference("magnitudeVolume") or speedVolumeNode
        if backgroundNode:
            FlowTestingUtils.showVolumeInSliceViews(backgroundNode, phantom.centerRas, foreground=speedVolumeNode if backgroundNode != speedVolumeNode else None)
        FlowTestingUtils.reset3DView()

    # Clinical data helpers

    def realDataDirectoryOrSkip(self):
        dataDir = FlowTestingUtils.environmentValue(FlowTestingUtils.REAL_DATA_ENV_VARIABLE)
        if not dataDir or not os.path.isdir(dataDir):
            self.skipTest(f"Anonymized 4D flow data set is not available (set {FlowTestingUtils.REAL_DATA_ENV_VARIABLE} in the environment or in .env.local)")
        return dataDir

    def loadRealDataFlowFields(self, dataDir, kinds=("transform", "volume")):
        """Load the clinical data set from DICOM (the DICOM database must be open) and create flow fields
        (with temporal unwrapping). Returns (volumeNodeSet, {kind: flowFieldNode})."""
        from DICOMLib import DICOMUtils
        DICOMUtils.importDicom(dataDir, slicer.dicomDatabase)
        FlowTestingUtils.loadDicomSeriesAsVolumeSequences()
        volumeNodeSets = self.importLogic.findVolumeNodeSets()
        self.assertEqual(len(volumeNodeSets), 1, "Number of detected 4D flow image sets")
        volumeNodeSet = list(volumeNodeSets.values())[0]
        flowFieldNodes = {}
        for kind in kinds:
            flowFieldNode = self.importLogic.createFlowFieldFromComponentVolumes(volumeNodeSet["componentVolumeNodes"],
                volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"], storeInTransform=(kind == "transform"))
            self.importLogic.temporalUnwrap(flowFieldNode, 0, 5.0)
            self.importLogic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
            flowFieldNodes[kind] = flowFieldNode
        return volumeNodeSet, flowFieldNodes

    def findPeakCoherentFlow(self, vectorVolumeFlowFieldNode, magnitudeVolumeNode):
        """Find location of the highest coherent systolic flow. Noise (random velocity directions, often saturated at the
        velocity encoding) is suppressed by averaging velocity vectors in a 5x5x5 neighborhood and only considering
        bright voxels; the coherent speed is then median filtered.
        Returns (peakSpeed, peakFrame, peakIndex (k, j, i), peakRas, flowDirection)."""
        import scipy.ndimage
        sequenceNode = self.importLogic._getSequenceFromProxyNode(vectorVolumeFlowFieldNode)
        magnitudeSequenceNode = self.importLogic._getSequenceFromProxyNode(magnitudeVolumeNode)
        best = (-1.0, None, None, None)
        for frameIndex in range(sequenceNode.GetNumberOfDataNodes()):
            velocity = slicer.util.arrayFromVolume(sequenceNode.GetNthDataNode(frameIndex))
            magnitude = slicer.util.arrayFromVolume(magnitudeSequenceNode.GetNthDataNode(frameIndex))
            meanVelocity = np.stack([scipy.ndimage.uniform_filter(velocity[..., c], size=5) for c in range(3)], axis=-1)
            coherentSpeed = scipy.ndimage.median_filter(np.linalg.norm(meanVelocity, axis=-1), size=3)
            coherentSpeed[magnitude < 0.3 * np.percentile(magnitude, 99)] = 0
            index = np.unravel_index(np.argmax(coherentSpeed), coherentSpeed.shape)
            if coherentSpeed[index] > best[0]:
                best = (float(coherentSpeed[index]), frameIndex, index, meanVelocity[index])
        peakSpeed, peakFrame, peakIndex, flowDirection = best
        k, j, i = peakIndex
        flowDirection = flowDirection / np.linalg.norm(flowDirection)
        ijkToRas = vtk.vtkMatrix4x4()
        magnitudeVolumeNode.GetIJKToRASMatrix(ijkToRas)
        peakRas = np.array(ijkToRas.MultiplyPoint([i, j, k, 1])[:3])
        return peakSpeed, peakFrame, peakIndex, peakRas, flowDirection

    @staticmethod
    def createPlane(centerRas, normal, sizeMm, name):
        planeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", name)
        planeNode.SetPlaneType(planeNode.PlaneTypePointNormal)
        planeNode.AddControlPointWorld(vtk.vtkVector3d(*centerRas))
        planeNode.SetNormalWorld(normal)
        planeNode.SetSizeMode(planeNode.SizeModeAbsolute)
        planeNode.SetSize(sizeMm, sizeMm)
        return planeNode

    @staticmethod
    def createSphereSegmentation(centerRas, radiusMm, referenceVolumeNode, name):
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", name)
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(referenceVolumeNode)
        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(*centerRas)
        sphere.SetRadius(radiusMm)
        sphere.SetPhiResolution(30)
        sphere.SetThetaResolution(30)
        sphere.Update()
        segmentId = segmentationNode.AddSegmentFromClosedSurfaceRepresentation(sphere.GetOutput(), name, [0.9, 0.3, 0.2])
        segmentationNode.CreateDefaultDisplayNodes()
        return segmentationNode, segmentId

    # Tests

    @reportedTest("Module and GUI initialization",
        "The module GUI can be loaded, and when the module is entered, the first flow field in the scene is selected automatically.")
    def test_01_ModuleAndWidget(self):
        self.report.checkTrue("Analyze4DFlow module is loaded", hasattr(slicer.modules, "analyze4dflow"))
        phantom = FlowPhantom(numberOfFrames=3)
        flowFieldNode, _ = self.createFlowField(phantom, "transform")
        slicer.util.selectModule("Data")
        slicer.util.selectModule("Analyze4DFlow")
        widget = slicer.modules.analyze4dflow.widgetRepresentation().self()
        self.report.checkTrue("Module widget is created", widget is not None and widget.logic is not None)
        self.report.checkTrue("Flow field is selected automatically when entering the module", widget._parameterNode.inputFlowField == flowFieldNode)
        nodeTypes = list(widget.ui.inputFlowFieldSelector.nodeTypes)
        self.report.checkEqual("Flow field selector node types", nodeTypes, ["vtkMRMLModelNode", "vtkMRMLTransformNode", "vtkMRMLVectorVolumeNode"])
        self.report.checkClose("Heart rate is shown in GUI", widget.ui.heartRateBpmDoubleSpinBox.value, phantom.heartRateBpm(), atol=0.01, unit="bpm")
        self.report.screenshot("Analyze 4D Flow module GUI", kind="window")

    @reportedTest("Automatic flow field detection",
        "`findFirstFlowFieldNode` returns the first grid transform or vector volume tagged as flow field, or the first model"
        " with an unstructured grid mesh that has a 'V' or 'Velocity' point data array.")
    def test_02_FindFirstFlowFieldNode(self):
        phantom = FlowPhantom(numberOfFrames=2)
        self.report.checkTrue("Empty scene: no flow field", self.logic.findFirstFlowFieldNode() is None)
        surfaceModel = slicer.modules.models.logic().AddModel(vtk.vtkPolyData())
        self.report.checkTrue("Surface model is not a flow field", self.logic.findFirstFlowFieldNode() is None)
        meshWithoutVelocity = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Mesh without velocity")
        mesh = phantom.createFlowModelMesh(0, "Pressure")
        meshWithoutVelocity.SetAndObserveMesh(mesh)
        self.report.checkTrue("Unstructured grid without velocity array is not a flow field", self.logic.findFirstFlowFieldNode() is None)
        for arrayName in ["Velocity", "V"]:
            modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", f"CFD {arrayName}")
            modelNode.SetAndObserveMesh(phantom.createFlowModelMesh(1, arrayName))
            found = self.logic.findFirstFlowFieldNode()
            self.report.checkTrue(f"Model with '{arrayName}' array is found", found is not None and found.IsA("vtkMRMLModelNode"),
                found.GetName() if found else None)
            slicer.mrmlScene.RemoveNode(modelNode)
        modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "CFD")
        modelNode.SetAndObserveMesh(phantom.createFlowModelMesh(1, "V"))
        vectorVolumeNode = phantom.createVolumeNode(phantom.velocityVolumeArray(1), "Velocity volume", "vtkMRMLVectorVolumeNode", addToScene=True)
        self.report.checkTrue("Untagged generic vector volume (for example, an RGB image) is not preferred over model",
            self.logic.findFirstFlowFieldNode() == modelNode)
        # Untagged vector volumes that look like velocity fields (for example, loaded from a file)
        for description, setVelocity, resetVelocity in [
                ("spatial vectors", lambda: vectorVolumeNode.SetVoxelVectorType(slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial),
                    lambda: vectorVolumeNode.SetVoxelVectorType(slicer.vtkMRMLVolumeNode.VoxelVectorTypeUndefined)),
                ("velocity quantity", lambda: vectorVolumeNode.SetVoxelValueQuantity(Import4DFlowLogic.createVelocityQuantity()),
                    lambda: vectorVolumeNode.SetVoxelValueQuantity(None)),
                ("velocity unit (mm/s)", lambda: vectorVolumeNode.SetVoxelValueUnits(Analyze4DFlowLogic.createVelocityUnits("mm/s")),
                    lambda: vectorVolumeNode.SetVoxelValueUnits(None))]:
            setVelocity()
            self.report.checkTrue(f"Untagged vector volume with {description} is preferred over model", self.logic.findFirstFlowFieldNode() == vectorVolumeNode)
            resetVelocity()
        self.report.checkTrue("Untagged generic vector volume is not preferred over model (after removing the velocity markers)",
            self.logic.findFirstFlowFieldNode() == modelNode)
        vectorVolumeNode.SetAttribute("SlicerHeart.Type", "FlowField")
        self.report.checkTrue("Tagged vector volume is preferred over model", self.logic.findFirstFlowFieldNode() == vectorVolumeNode)
        transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", "Flow transform")
        transformNode.SetAttribute("SlicerHeart.Type", "FlowField")
        self.report.checkTrue("Tagged transform is preferred over vector volume", self.logic.findFirstFlowFieldNode() == transformNode)
        for node, expectedKind in [(transformNode, "transform"), (vectorVolumeNode, "volume"), (modelNode, "model")]:
            self.report.checkEqual(f"Flow field kind of {node.GetClassName()}", self.logic._flowFieldKind(node), expectedKind)

    @reportedTest("Flow quantification accuracy (segmentation mask)",
        "Flow metrics in a plane perpendicular to the vessel, using a segmentation of the vessel lumen as mask, are compared"
        " to analytic values for all flow field types. Grid transform and vector volume storage must give identical results.")
    def test_03_FlowMetricsSegmentationMask(self):
        phantom = FlowPhantom()
        results = {}
        for kind in KINDS:
            slicer.mrmlScene.Clear()
            label = f"[{KIND_NAMES[kind]}]"
            flowFieldNode, referenceVolumeNode = self.createFlowField(phantom, kind)
            planeNode = phantom.createMeasurementPlane()
            segmentationNode, segmentId = phantom.createVesselSegmentation(referenceVolumeNode)
            startTime = time.time()
            outputs, metrics, summaryMetrics = self.analyze(flowFieldNode, planeNode, segmentationNode, segmentId)
            durationSec = time.time() - startTime
            self.report.text(f"{label} Analysis time: {durationSec:.1f} s")
            results[kind] = (metrics, summaryMetrics)
            self.checkMetricsAgainstPhantom(label, phantom, metrics, summaryMetrics)
            metricsModel = outputs["metricsModel"]
            FlowTestingUtils.selectSequenceItem(flowFieldNode, phantom.peakFrameIndex())
            for arrayName in ["Speed", "insideVessel", "SpeedMasked"]:
                self.report.checkTrue(f"{label} Flow metrics model has '{arrayName}' point data array",
                    metricsModel.GetPolyData().GetPointData().GetArray(arrayName) is not None)
            if kind == "transform":
                self.logic.createPlotFromTable(outputs["table"])
                self.report.screenshot("Flow metrics plot (grid transform flow field)")
        transformMetrics, transformSummary = results["transform"]
        volumeMetrics, volumeSummary = results["volume"]
        differences = [abs(a - b) for name in transformMetrics for a, b in zip(transformMetrics[name], volumeMetrics.get(name, []))]
        differences += [abs(transformSummary[name] - volumeSummary.get(name, float("nan"))) for name in transformSummary]
        self.report.checkClose("Grid transform vs. vector volume: max. difference of all metrics", max(differences), 0.0, atol=1e-3)

    @reportedTest("Flow quantification accuracy (speed threshold mask)",
        "Without segmentation, the vessel is defined by the points where speed is above the threshold (0.1 m/s)."
        " Expected flow and area are computed analytically for the thresholded Poiseuille profile.")
    def test_04_FlowMetricsSpeedThresholdMask(self):
        phantom = FlowPhantom()
        speedThreshold = 0.1
        for kind in ["volume", "model"]:
            slicer.mrmlScene.Clear()
            label = f"[{KIND_NAMES[kind]}, threshold]"
            flowFieldNode, _ = self.createFlowField(phantom, kind)
            planeNode = phantom.createMeasurementPlane()
            _, metrics, summaryMetrics = self.analyze(flowFieldNode, planeNode, speedThreshold=speedThreshold)
            self.checkMetricsAgainstPhantom(label, phantom, metrics, None, speedThreshold=speedThreshold, segmentationMask=False, areaRtol=0.2)
            zeroFlowFrames = [i for i in range(phantom.numberOfFrames) if abs(phantom.maxVelocity(i)) <= speedThreshold]
            for frameIndex in zeroFlowFrames:
                self.report.checkClose(f"{label} Area where speed is below threshold everywhere, frame {frameIndex}", metrics["Area"][frameIndex], 0.0, atol=1e-6, unit="mm2")

    @reportedTest("Flow rate does not depend on plane orientation",
        "Flow rate through a cross-section of the vessel is the flux of the velocity field (integral of the velocity"
        " component normal to the plane), so it must not change when the plane is tilted relative to the vessel axis"
        " (the tilted plane intersects a larger, elliptical area, but the normal velocity component is smaller).")
    def test_05_TiltedPlane(self):
        phantom = FlowPhantom()
        flowFieldNode, referenceVolumeNode = self.createFlowField(phantom, "volume")
        segmentationNode, segmentId = phantom.createVesselSegmentation(referenceVolumeNode)
        peakFrame = phantom.peakFrameIndex()
        expectedFlow = phantom.expectedFlowRateMlPerSec(peakFrame)
        rows = []
        for tiltDeg in [0.0, 20.0, 35.0]:
            planeNode = phantom.createMeasurementPlane(tiltDeg=tiltDeg, sizeMm=48.0, name=f"Plane tilted {tiltDeg:g} deg")
            _, metrics, _ = self.analyze(flowFieldNode, planeNode, segmentationNode, segmentId, summary=False)
            flow = metrics["FlowRate"][peakFrame]
            area = metrics["Area"][peakFrame]
            rows.append([f"{tiltDeg:g}", flow, expectedFlow, area, phantom.expectedAreaMm2() / math.cos(math.radians(tiltDeg)), flow / expectedFlow])
            self.report.checkClose(f"Flow rate at peak systole, plane tilted by {tiltDeg:g} deg", flow, expectedFlow, rtol=0.08, unit="ml/s")
            self.report.checkClose(f"Area at peak systole, plane tilted by {tiltDeg:g} deg (elliptical cross-section)", area,
                phantom.expectedAreaMm2() / math.cos(math.radians(tiltDeg)), rtol=0.15, unit="mm2")
            if tiltDeg == 35.0:
                FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
                FlowTestingUtils.showVolumeInSliceViews(flowFieldNode.GetNodeReference("magnitudeVolume"), phantom.centerRas)
                FlowTestingUtils.reset3DView()
                self.report.screenshot("Measurement plane tilted by 35 degrees relative to the vessel axis")
        self.report.table(["Plane tilt (deg)", "Flow rate (ml/s)", "Expected flow rate (ml/s)", "Area (mm2)", "Expected area (mm2)", "Flow ratio"], rows)

    @reportedTest("Streamlines",
        "Streamlines are seeded from the measurement plane points inside the vessel. They must follow the vessel axis,"
        " stay inside the vessel, be colored by speed, and respect the maximum length and direction (bidirectional / forward)"
        " options. Optional metrics (vorticity, etc.) are only kept if requested.")
    def test_06_Streamlines(self):
        phantom = FlowPhantom()
        peakFrame = phantom.peakFrameIndex()
        cases = [
            ("transform", True, 100, False),
            ("model", True, 100, False),
            ("volume", False, 100, True),
            ("volume", True, 12, False),
        ]
        rows = []
        for kind, bidirectional, maximumLengthMm, computeAllMetrics in cases:
            slicer.mrmlScene.Clear()
            label = f"[{KIND_NAMES[kind]}, {'bidirectional' if bidirectional else 'forward'}, max. length {maximumLengthMm} mm{', all metrics' if computeAllMetrics else ''}]"
            flowFieldNode, referenceVolumeNode = self.createFlowField(phantom, kind)
            if kind == "transform":
                self.importLogic.setFlowFieldVisualizationToDefault(flowFieldNode)
            planeNode = phantom.createMeasurementPlane()
            segmentationNode, segmentId = phantom.createVesselSegmentation(referenceVolumeNode)
            outputs, _, _ = self.analyze(flowFieldNode, planeNode, segmentationNode, segmentId, streamlines=True, speedThreshold=0.02,
                maximumLengthMm=maximumLengthMm, bidirectional=bidirectional, computeAllMetrics=computeAllMetrics, summary=False)
            streamlinesNode = outputs["streamlines"]
            FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
            polyData = streamlinesNode.GetPolyData()
            numberOfLines = polyData.GetNumberOfLines() if polyData else 0
            self.report.checkTrue(f"{label} Streamlines are generated", numberOfLines > 0, numberOfLines, "> 0")
            if not numberOfLines:
                continue
            points = vtk.util.numpy_support.vtk_to_numpy(polyData.GetPoints().GetData())
            relative = points - phantom.centerRas
            axial = relative @ phantom.vesselAxis
            radial = phantom.radialDistance(points)
            # Direction of line segments
            cosines = []
            lines = polyData.GetLines()
            lines.InitTraversal()
            idList = vtk.vtkIdList()
            while lines.GetNextCell(idList):
                ids = [idList.GetId(i) for i in range(idList.GetNumberOfIds())]
                segments = np.diff(points[ids], axis=0)
                lengths = np.linalg.norm(segments, axis=1)
                valid = lengths > 1e-6
                cosines.extend(np.abs(segments[valid] @ phantom.vesselAxis) / lengths[valid])
            meanCosine = float(np.mean(cosines)) if cosines else 0.0
            speedArray = polyData.GetPointData().GetArray("Speed")
            maxSpeed = float(speedArray.GetRange()[1]) if speedArray else float("nan")
            self.report.checkTrue(f"{label} 'Speed' point data array", speedArray is not None)
            self.report.checkClose(f"{label} Streamlines are parallel to the vessel axis (mean |cos| of segment directions)", meanCosine, 1.0, atol=0.02)
            self.report.checkRange(f"{label} Max. distance of streamline points from vessel axis", float(radial.max()), 0.0, phantom.vesselRadiusMm + 1.0, "mm")
            self.report.checkClose(f"{label} Max. speed along streamlines", maxSpeed, phantom.peakVelocityMPerSec, rtol=0.05, unit="m/s")
            axialExtent = (float(axial.min()), float(axial.max()))
            if bidirectional:
                self.report.checkTrue(f"{label} Streamlines extend upstream and downstream of the plane", axialExtent[0] < -5 and axialExtent[1] > 5,
                    axialExtent, "(< -5, > 5) mm")
            else:
                self.report.checkTrue(f"{label} Forward streamlines only extend downstream of the plane", axialExtent[0] > -1.0 and axialExtent[1] > 5,
                    axialExtent, "(> -1, > 5) mm")
            if maximumLengthMm < 50:
                self.report.checkRange(f"{label} Streamline extent along the axis is limited by maximum length",
                    max(abs(axialExtent[0]), abs(axialExtent[1])), 0, maximumLengthMm + 1.0, "mm")
            for arrayName in ["Vorticity", "Rotation", "AngularVelocity"]:
                present = polyData.GetPointData().GetArray(arrayName) is not None
                self.report.checkEqual(f"{label} '{arrayName}' array present", present, computeAllMetrics)
            displayNode = streamlinesNode.GetDisplayNode()
            self.report.checkTrue(f"{label} Streamlines are colored by speed", displayNode is not None and displayNode.GetScalarVisibility()
                and displayNode.GetActiveScalarName() == "Speed")
            rows.append([label, numberOfLines, meanCosine, float(radial.max()), axialExtent, maxSpeed])
            if kind in ["transform", "model"]:
                planeNode.GetDisplayNode().SetOpacity(0.3)
                if kind == "transform":
                    self.logic._getGlyphDisplayNodes(flowFieldNode)[0].SetVisibility(False)
                FlowTestingUtils.showVolumeInSliceViews(referenceVolumeNode, phantom.centerRas)
                slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
                FlowTestingUtils.reset3DView()
                self.report.screenshot(f"Streamlines at peak systole {label}")
                slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
        self.report.table(["Case", "Lines", "Mean |cos|", "Max. radial distance (mm)", "Axial extent (mm)", "Max. speed (m/s)"], rows)

    @reportedTest("Speed volume",
        "The speed volume contains the speed magnitude, or (Doppler-like) the signed velocity component along the plane normal."
        " Color mapping is set according to the mode.")
    def test_07_SpeedVolume(self):
        phantom = FlowPhantom(numberOfFrames=10)
        peakFrame = phantom.peakFrameIndex()
        backflowFrame = phantom.backflowFrameIndex()
        rows = []
        for kind in ["transform", "model"]:
            slicer.mrmlScene.Clear()
            flowFieldNode, referenceVolumeNode = self.createFlowField(phantom, kind)
            if kind == "transform":
                self.importLogic.setFlowFieldVisualizationToDefault(flowFieldNode)
                # Speed magnitude volume uses the same color map as the flow field glyphs
                expectedSpeedColorNodeID = self.importLogic.getFlowFieldDisplayNode(flowFieldNode).GetColorNodeID()
            else:
                # Model has no speed color map, a default color map is used
                expectedSpeedColorNodeID = "vtkMRMLColorTableNodeFileViridis.txt"
            planeNode = phantom.createMeasurementPlane()
            segmentationNode, segmentId = phantom.createVesselSegmentation(referenceVolumeNode)
            speedVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Speed")
            for projected in [False, True]:
                label = f"[{KIND_NAMES[kind]}, {'projected' if projected else 'magnitude'}]"
                startTime = time.time()
                self.logic.sampleFlowFieldWithPlane(planeNode, flowFieldNode, samplingDistanceMm=1.0,
                    outputFlowMetricsModel=slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Metrics"),
                    maskSegmentationNode=segmentationNode, maskSegmentID=segmentId,
                    outputSpeedVolume=speedVolumeNode, speedVolumeProjectedToPlane=projected, streamlinesSpeedThresholdMPerSec=0.02)
                durationSec = time.time() - startTime
                FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
                peakArray = slicer.util.arrayFromVolume(speedVolumeNode).copy()
                FlowTestingUtils.selectSequenceItem(flowFieldNode, backflowFrame)
                backflowArray = slicer.util.arrayFromVolume(speedVolumeNode).copy()
                colorNode = speedVolumeNode.GetScalarVolumeDisplayNode().GetColorNode()
                colorMappingType = colorNode.GetAttribute("SlicerHeart.ColorMappingType") if colorNode else None
                self.report.checkClose(f"{label} Max. value at peak systole", float(peakArray.max()), phantom.peakVelocityMPerSec, rtol=0.05, unit="m/s")
                if projected:
                    expectedMin = phantom.maxVelocity(backflowFrame)
                    self.report.checkClose(f"{label} Min. value during backflow (negative: flow against plane normal)", float(backflowArray.min()),
                        expectedMin, rtol=0.1, unit="m/s")
                    self.report.checkEqual(f"{label} Color mapping type", colorMappingType, "SpeedComponent")
                else:
                    self.report.checkClose(f"{label} Min. value (speed is non-negative)", float(backflowArray.min()), 0.0, atol=1e-6, unit="m/s")
                    self.report.checkClose(f"{label} Max. value during backflow", float(backflowArray.max()), abs(phantom.maxVelocity(backflowFrame)), rtol=0.1, unit="m/s")
                    self.report.checkEqual(f"{label} Color map", speedVolumeNode.GetScalarVolumeDisplayNode().GetColorNodeID(), expectedSpeedColorNodeID)
                if kind == "transform":
                    ijkToRas = vtk.vtkMatrix4x4()
                    speedVolumeNode.GetIJKToRASMatrix(ijkToRas)
                    phantomIjkToRas = phantom.ijkToRasMatrix()
                    geometryError = max(abs(ijkToRas.GetElement(r, c) - phantomIjkToRas.GetElement(r, c)) for r in range(3) for c in range(4))
                    self.report.checkClose(f"{label} Speed volume geometry matches the 4D flow image", geometryError, 0.0, atol=1e-4)
                else:
                    ijkToRas = vtk.vtkMatrix4x4()
                    speedVolumeNode.GetIJKToRASMatrix(ijkToRas)
                    kAxis = np.array([ijkToRas.GetElement(r, 2) for r in range(3)])
                    self.report.checkClose(f"{label} Speed volume K axis is aligned with the plane normal (|cos|)",
                        abs(float(kAxis @ np.array(planeNode.GetNormalWorld())) / np.linalg.norm(kAxis)), 1.0, atol=1e-3)
                rows.append([label, speedVolumeNode.GetImageData().GetDimensions(), speedVolumeNode.GetSpacing(), f"{durationSec:.1f}"])
                FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame if not projected else backflowFrame)
                backgroundNode = flowFieldNode.GetNodeReference("magnitudeVolume") or referenceVolumeNode
                FlowTestingUtils.showVolumeInSliceViews(backgroundNode, phantom.centerRas, foreground=speedVolumeNode, foregroundOpacity=0.7)
                if kind == "transform":
                    self.report.screenshot(f"Speed volume {label} at {'backflow' if projected else 'peak systole'}")
        self.report.table(["Case", "Speed volume size", "Spacing (mm)", "Analysis time (s)"], rows)

    @reportedTest("Masked flow field output",
        "The flow field is masked by a segmentation (half of the vessel radius) or by the speed threshold, and written into"
        " an output node of the same type. Velocities must be zero outside the mask and unchanged inside."
        " An output node of a different type must be rejected.")
    def test_08_MaskedFlowField(self):
        phantom = FlowPhantom(numberOfFrames=8)
        peakFrame = phantom.peakFrameIndex()
        maskRadiusMm = phantom.vesselRadiusMm / 2
        for kind in KINDS:
            slicer.mrmlScene.Clear()
            label = f"[{KIND_NAMES[kind]}]"
            flowFieldNode, referenceVolumeNode = self.createFlowField(phantom, kind)
            if kind == "transform":
                self.importLogic.setFlowFieldVisualizationToDefault(flowFieldNode)
            planeNode = phantom.createMeasurementPlane()
            segmentationNode, segmentId = phantom.createVesselSegmentation(referenceVolumeNode, radiusMm=maskRadiusMm, name="Core")
            outputNode = slicer.mrmlScene.AddNewNodeByClass(flowFieldNode.GetClassName() if kind != "transform" else "vtkMRMLTransformNode", "Masked flow field")
            self.analyze(flowFieldNode, planeNode, segmentationNode, segmentId, maskedOutput=outputNode, summary=False)
            FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
            if kind == "model":
                mesh = outputNode.GetMesh()
                points = vtk.util.numpy_support.vtk_to_numpy(mesh.GetPoints().GetData())
                velocity = vtk.util.numpy_support.vtk_to_numpy(mesh.GetPointData().GetArray("V"))
                expected = phantom.velocityAt(points, peakFrame)
                radial = phantom.radialDistance(points)
            else:
                if kind == "transform":
                    velocity = slicer.util.arrayFromGridTransform(outputNode)
                else:
                    velocity = slicer.util.arrayFromVolume(outputNode)
                expected = phantom.velocityVolumeArray(peakFrame)
                radial = phantom.radialDistanceMm
            # Exclude points near the mask boundary (voxelization / surface discretization)
            inside = radial < maskRadiusMm - 1.5
            outside = radial > maskRadiusMm + 1.5
            self.report.checkClose(f"{label} Max. speed outside the mask", float(np.linalg.norm(velocity[outside], axis=-1).max()), 0.0, atol=1e-6, unit="m/s")
            self.report.checkClose(f"{label} Max. velocity error inside the mask", float(np.abs(velocity[inside] - expected[inside]).max()), 0.0,
                atol=0.002, unit="m/s")
            browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
            self.report.checkTrue(f"{label} Masked flow field is in the flow field's sequence browser", browserNode.GetSequenceNode(outputNode) is not None)
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            self.report.checkEqual(f"{label} Masked flow field is in the same subject hierarchy folder as the input",
                shNode.GetItemParent(shNode.GetItemByDataNode(outputNode)), shNode.GetItemParent(shNode.GetItemByDataNode(flowFieldNode)))
            if kind == "transform":
                outputDisplayNode = self.logic._flowFieldDisplayNode(outputNode)
                self.report.checkTrue(f"{label} Display node is created for the output (hidden)", outputDisplayNode is not None and not outputDisplayNode.GetVisibility())
                self.report.checkTrue(f"{label} Output display uses the input's color map", outputDisplayNode is not None
                    and outputDisplayNode.GetColorNodeID() == self.logic._flowFieldDisplayNode(flowFieldNode).GetColorNodeID())
                outputDisplayNode.SetVisibility(True)
                self.logic._flowFieldDisplayNode(flowFieldNode).SetVisibility(False)
                FlowTestingUtils.showVolumeInSliceViews(flowFieldNode.GetNodeReference("magnitudeVolume"), phantom.centerRas)
                self.report.screenshot(f"Masked flow field (grid transform, mask radius {maskRadiusMm:g} mm) at peak systole")
            # Wrong output type
            wrongOutputClass = "vtkMRMLModelNode" if kind != "model" else "vtkMRMLVectorVolumeNode"
            wrongOutputNode = slicer.mrmlScene.AddNewNodeByClass(wrongOutputClass, "Wrong type")
            with self.assertRaises(ValueError):
                self.logic.sampleFlowFieldWithPlane(planeNode, flowFieldNode, outputMaskedFlowField=wrongOutputNode)
            self.report.checkTrue(f"{label} Output of a different type ({wrongOutputClass}) is rejected", True)

        # Speed threshold mask
        slicer.mrmlScene.Clear()
        flowFieldNode, _ = self.createFlowField(phantom, "volume")
        planeNode = phantom.createMeasurementPlane()
        outputNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "Masked flow field")
        speedThreshold = 0.5
        self.analyze(flowFieldNode, planeNode, speedThreshold=speedThreshold, maskedOutput=outputNode, summary=False)
        FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
        velocity = slicer.util.arrayFromVolume(outputNode)
        expected = phantom.velocityVolumeArray(peakFrame)
        expectedSpeed = np.linalg.norm(expected, axis=-1)
        speed = np.linalg.norm(velocity, axis=-1)
        self.report.checkClose("[speed threshold 0.5 m/s] Max. speed where the speed is below threshold",
            float(speed[expectedSpeed < speedThreshold - 0.01].max()), 0.0, atol=1e-6, unit="m/s")
        self.report.checkClose("[speed threshold 0.5 m/s] Max. velocity error where the speed is above threshold",
            float(np.abs(velocity - expected)[expectedSpeed > speedThreshold + 0.01].max()), 0.0, atol=0.002, unit="m/s")

    @reportedTest("Integration with sequences",
        "Output nodes become proxy nodes of the flow field's sequence browser (one item per frame), the selected frame and"
        " the flow field visibility are restored after the analysis, and output nodes that were in another sequence"
        " browser are moved to the flow field's browser.")
    def test_09_SequenceIntegration(self):
        phantom = FlowPhantom(numberOfFrames=6)
        flowFieldNode, referenceVolumeNode = self.createFlowField(phantom, "transform")
        self.importLogic.setFlowFieldVisualizationToDefault(flowFieldNode)
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        browserNode.SetSelectedItemNumber(3)
        planeNode = phantom.createMeasurementPlane()
        outputs, metrics, _ = self.analyze(flowFieldNode, planeNode, streamlines=True, speedVolume=True,
            maskedOutput=slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", "Masked"), summary=False)
        self.report.checkEqual("Selected frame is restored after analysis", browserNode.GetSelectedItemNumber(), 3)
        displayNode = self.importLogic.getFlowFieldDisplayNode(flowFieldNode)
        self.report.checkTrue("Flow field glyph visibility is restored after analysis", displayNode.GetVisibility())
        for name in ["metricsModel", "streamlines", "speedVolume", "maskedFlowField"]:
            sequenceNode = browserNode.GetSequenceNode(outputs[name])
            self.report.checkTrue(f"Output '{name}' is a proxy node of the flow field's sequence browser", sequenceNode is not None)
            if sequenceNode:
                self.report.checkEqual(f"Output '{name}' sequence has one item per frame", sequenceNode.GetNumberOfDataNodes(), phantom.numberOfFrames)
        speeds = []
        for frameIndex in range(phantom.numberOfFrames):
            browserNode.SetSelectedItemNumber(frameIndex)
            speeds.append(float(slicer.util.arrayFromVolume(outputs["speedVolume"]).max()))
        expectedSpeeds = [abs(phantom.maxVelocity(i)) for i in range(phantom.numberOfFrames)]
        self.report.checkClose("Speed volume changes with the selected frame (max. error of per-frame maximum speed)",
            max(abs(a - b) for a, b in zip(speeds, expectedSpeeds)), 0.0, atol=0.05, unit="m/s")
        self.report.checkEqual("Temporary nodes are removed", len([n for n in slicer.util.getNodes("__tmp__*")]), 0)

        # Output node that is already a proxy node of another sequence browser
        otherModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Model in other browser")
        otherSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "Other sequence")
        otherBrowserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "Other browser")
        slicer.modules.sequences.logic().AddSynchronizedNode(otherSequenceNode, otherModelNode, otherBrowserNode)
        try:
            self.logic.sampleFlowFieldWithPlane(planeNode, flowFieldNode, outputFlowMetricsModel=otherModelNode)
            error = None
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        self.report.checkTrue("Output node that was in another sequence browser can be used", error is None, error or "no error", "no error")
        if error is None:
            self.report.checkTrue("Output node is moved to the flow field's sequence browser",
                browserNode.GetSequenceNode(otherModelNode) is not None and otherBrowserNode.GetSequenceNode(otherModelNode) is None)

    @reportedTest("Static flow fields and input validation",
        "Flow fields that are not in a sequence are analyzed as a single frame (model and vector volume), while grid transforms"
        " must be in a sequence. Flow fields under parent transforms are handled in world coordinates (model) or rejected"
        " (vector volume).")
    def test_10_StaticFlowFieldsAndValidation(self):
        phantom = FlowPhantom(numberOfFrames=6)
        peakFrame = phantom.peakFrameIndex()
        expectedFlow = phantom.expectedFlowRateMlPerSec(peakFrame)

        # Static model
        modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Static CFD")
        modelNode.SetAndObserveMesh(phantom.createFlowModelMesh(peakFrame, "Velocity"))
        referenceVolumeNode = phantom.createVolumeNode(phantom.magnitudeVolumeArray(), "Reference", addToScene=True)
        segmentationNode, segmentId = phantom.createVesselSegmentation(referenceVolumeNode)
        planeNode = phantom.createMeasurementPlane()
        _, metrics, _ = self.analyze(modelNode, planeNode, segmentationNode, segmentId, summary=False)
        self.report.checkEqual("[static model] Number of rows in metrics table", len(metrics.get("FlowRate", [])), 1)
        self.report.checkClose("[static model] Flow rate", metrics["FlowRate"][0], expectedFlow, rtol=0.08, unit="ml/s")
        with self.assertRaises(RuntimeError):
            self.analyze(modelNode, planeNode, segmentationNode, segmentId, summary=True)
        self.report.checkTrue("[static model] Summary metrics (needs multiple frames) are rejected", True)

        # Model under a parent transform: plane and segmentation transformed the same way must give the same flow
        parentTransform = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "Shift and rotate")
        transform = vtk.vtkTransform()
        transform.Translate(15, -8, 4)
        transform.RotateZ(25)
        transform.RotateX(40)  # large rotation, so that errors in transforming velocity vectors are detectable
        parentTransform.SetMatrixTransformToParent(transform.GetMatrix())
        for node in [modelNode, planeNode, segmentationNode]:
            node.SetAndObserveTransformNodeID(parentTransform.GetID())
        outputs, metrics, _ = self.analyze(modelNode, planeNode, segmentationNode, segmentId, streamlines=True, speedThreshold=0.02, summary=False)
        self.report.checkClose("[static model, parent transform] Flow rate", metrics["FlowRate"][0], expectedFlow, rtol=0.08, unit="ml/s")
        # Streamlines (in world coordinate system) must follow the transformed vessel axis
        vesselAxisWorld = np.array(transform.TransformVector(phantom.vesselAxis))
        streamlinesPolyData = outputs["streamlines"].GetPolyData()
        cosines = []
        if streamlinesPolyData and streamlinesPolyData.GetNumberOfLines():
            points = vtk.util.numpy_support.vtk_to_numpy(streamlinesPolyData.GetPoints().GetData())
            lines = streamlinesPolyData.GetLines()
            lines.InitTraversal()
            idList = vtk.vtkIdList()
            while lines.GetNextCell(idList):
                segments = np.diff(points[[idList.GetId(i) for i in range(idList.GetNumberOfIds())]], axis=0)
                lengths = np.linalg.norm(segments, axis=1)
                cosines.extend(np.abs(segments[lengths > 1e-6] @ vesselAxisWorld) / lengths[lengths > 1e-6])
        self.report.checkClose("[static model, parent transform] Streamlines are parallel to the transformed vessel axis (mean |cos|)",
            float(np.mean(cosines)) if cosines else 0.0, 1.0, atol=0.02)
        for node in [modelNode, planeNode, segmentationNode]:
            node.SetAndObserveTransformNodeID(None)

        # Measurement plane under a parent transform (flow field is not transformed): the plane is specified in the
        # transformed coordinate system so that in world coordinate system it is perpendicular to the vessel
        planeTransform = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "Plane transform")
        planeTransform.SetMatrixTransformToParent(transform.GetMatrix())
        worldToPlaneParent = vtk.vtkTransform()
        worldToPlaneParent.SetMatrix(transform.GetMatrix())
        worldToPlaneParent.Inverse()
        transformedPlaneNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "Plane under transform")
        transformedPlaneNode.SetPlaneType(transformedPlaneNode.PlaneTypePointNormal)
        transformedPlaneNode.AddControlPoint(vtk.vtkVector3d(*worldToPlaneParent.TransformPoint(phantom.centerRas)))
        transformedPlaneNode.SetNormal(worldToPlaneParent.TransformVector(phantom.vesselAxis))
        transformedPlaneNode.SetSizeMode(transformedPlaneNode.SizeModeAbsolute)
        transformedPlaneNode.SetSize(36.0, 36.0)
        transformedPlaneNode.SetAndObserveTransformNodeID(planeTransform.GetID())
        self.report.checkClose("[plane under parent transform] Plane normal in world coordinate system is the vessel axis (|cos|)",
            abs(float(np.dot(transformedPlaneNode.GetNormalWorld(), phantom.vesselAxis))), 1.0, atol=1e-6)
        _, metrics, _ = self.analyze(modelNode, transformedPlaneNode, segmentationNode, segmentId, summary=False)
        self.report.checkClose("[static model, plane under parent transform] Flow rate", metrics["FlowRate"][0], expectedFlow, rtol=0.08, unit="ml/s")

        # Static vector volume
        vectorVolumeNode = phantom.createVolumeNode(phantom.velocityVolumeArray(peakFrame), "Static velocity", "vtkMRMLVectorVolumeNode", addToScene=True)
        _, metrics, _ = self.analyze(vectorVolumeNode, planeNode, segmentationNode, segmentId, summary=False)
        self.report.checkEqual("[static vector volume] Number of rows in metrics table", len(metrics.get("FlowRate", [])), 1)
        self.report.checkClose("[static vector volume] Flow rate", metrics["FlowRate"][0], expectedFlow, rtol=0.08, unit="ml/s")
        vectorVolumeNode.SetAndObserveTransformNodeID(parentTransform.GetID())
        with self.assertRaises(RuntimeError):
            self.analyze(vectorVolumeNode, planeNode, segmentationNode, segmentId, summary=False)
        self.report.checkTrue("[static vector volume] Vector volume under a parent transform is rejected", True)

        # Grid transform that is not in a sequence
        transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", "Static transform")
        Analyze4DFlowLogic._setTransformFromDisplacementImage(transformNode, phantom.createVolumeNode(
            phantom.velocityVolumeArray(peakFrame), "tmp", "vtkMRMLVectorVolumeNode"))
        with self.assertRaises(RuntimeError):
            self.logic.sampleFlowFieldWithPlane(planeNode, transformNode)
        self.report.checkTrue("[static grid transform] Grid transform that is not in a sequence is rejected", True)

        # Invalid inputs
        with self.assertRaises(ValueError):
            self.logic.sampleFlowFieldWithPlane(None, vectorVolumeNode)
        self.report.checkTrue("Missing measurement plane is rejected", True)
        meshWithoutVelocity = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "No velocity")
        meshWithoutVelocity.SetAndObserveMesh(phantom.createFlowModelMesh(peakFrame, "Pressure"))
        with self.assertRaises(ValueError):
            self.logic.sampleFlowFieldWithPlane(planeNode, meshWithoutVelocity)
        self.report.checkTrue("Model without velocity array is rejected", True)

    @reportedTest("Flow metrics tables and plot",
        "Flow metrics table has the expected columns, units, and descriptions; the summary table can be computed without the"
        " per-frame table; the plot shows all metrics over time and repeated plotting does not duplicate plot series.")
    def test_11_TablesAndPlot(self):
        phantom = FlowPhantom(numberOfFrames=8)
        flowFieldNode, referenceVolumeNode = self.createFlowField(phantom, "volume")
        planeNode = phantom.createMeasurementPlane()
        segmentationNode, segmentId = phantom.createVesselSegmentation(referenceVolumeNode)
        outputs, metrics, summaryMetrics = self.analyze(flowFieldNode, planeNode, segmentationNode, segmentId)
        tableNode = outputs["table"]
        expectedColumns = ["Time", "Area", "PositiveArea", "NegativeArea", "FlowRate", "PositiveFlowRate", "NegativeFlowRate",
            "MeanVelocity", "MaxVelocity", "MinVelocity", "Percentile1Velocity", "Percentile5Velocity", "Percentile95Velocity",
            "Percentile99Velocity", "StdDevVelocity"]
        self.report.checkEqual("Flow metrics table columns", list(metrics.keys()), expectedColumns)
        self.report.checkEqual("Flow metrics table rows", tableNode.GetNumberOfRows(), phantom.numberOfFrames)
        units = [tableNode.GetColumnUnitLabel(name) for name in expectedColumns]
        self.report.checkEqual("Flow metrics table units", units, ["ms", "mm2", "mm2", "mm2", "ml/s", "ml/s", "ml/s"] + ["cm/s"] * 8)
        expectedSummaryColumns = ["ForwardVolume", "BackwardVolume", "TotalVolume", "RegurgitationFraction", "VolPerMinute",
            "EffectiveVolPerMinute", "PeakVelocity", "MaxPressureGradient", "MaxFlow", "NetPositiveVolume", "NetNegativeVolume"]
        self.report.checkEqual("Summary table columns", list(summaryMetrics.keys()), expectedSummaryColumns)
        summaryTableNode = outputs["summaryTable"]
        summaryUnits = [summaryTableNode.GetColumnUnitLabel(name) for name in expectedSummaryColumns]
        self.report.checkEqual("Summary table units", summaryUnits, ["ml", "ml", "ml", "%", "l/min", "l/min", "cm/s", "mmHg", "ml/s", "ml", "ml"])
        self.report.checkTrue("Summary table column descriptions", all(summaryTableNode.GetColumnDescription(n) for n in expectedSummaryColumns))
        forward = summaryMetrics["ForwardVolume"]
        self.report.checkClose("NetPositiveVolume equals ForwardVolume (no flow reversal within the cross-section)",
            summaryMetrics["NetPositiveVolume"], forward, rtol=0.02, unit="ml")
        self.report.checkTrue("Velocity percentiles are ordered", all(
            metrics["MinVelocity"][i] <= metrics["Percentile1Velocity"][i] <= metrics["Percentile5Velocity"][i] <= metrics["Percentile95Velocity"][i]
            <= metrics["Percentile99Velocity"][i] <= metrics["MaxVelocity"][i] for i in range(phantom.numberOfFrames)))
        self.report.checkTrue("Positive + negative area = area", all(abs(metrics["PositiveArea"][i] + metrics["NegativeArea"][i] - metrics["Area"][i]) < 1e-6
            for i in range(phantom.numberOfFrames)))
        self.report.checkTrue("Positive + negative flow rate = flow rate", all(abs(metrics["PositiveFlowRate"][i] + metrics["NegativeFlowRate"][i]
            - metrics["FlowRate"][i]) < 1e-6 for i in range(phantom.numberOfFrames)))

        # Summary table only
        summaryOnlyTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Summary only")
        try:
            self.logic.computeFlowMetricsTable(outputs["metricsModel"], planeNode, flowFieldNode, 0.1, None, summaryOnlyTableNode)
            error = None
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        self.report.checkTrue("Summary table can be computed without the per-frame table", error is None, error or "no error", "no error")

        # Plot
        plotSeriesNodes = self.logic.createPlotFromTable(tableNode)
        chartNode = self.logic.getParameterNode().outputFlowMetricsPlotChart
        self.report.checkTrue("Plot chart is stored in the parameter node", chartNode is not None)
        self.report.checkEqual("Number of plot series (one per available metric)", len(plotSeriesNodes), len(expectedColumns) - 1)
        self.report.checkTrue("Plot series use time as X axis", all(s.GetXColumnName() == "Time" for s in plotSeriesNodes))
        self.logic.createPlotFromTable(tableNode)
        self.report.checkEqual("Repeated plotting does not duplicate plot series", chartNode.GetNumberOfPlotSeriesNodes(), len(expectedColumns) - 1)
        # Only show flow rates
        for seriesIndex in range(chartNode.GetNumberOfPlotSeriesNodes()):
            seriesNode = chartNode.GetNthPlotSeriesNode(seriesIndex)
            if "FlowRate" not in seriesNode.GetYColumnName():
                seriesNode.SetPlotType(seriesNode.PlotTypeScatter)
        self.report.screenshot("Flow metrics plot")

    @reportedTest("Heart rate",
        "Heart rate is stored with the flow field (on the magnitude volume sequence for 4D flow MRI, on the flow field sequence"
        " or node otherwise), can be computed from the acquisition length or from the DICOM NominalInterval field.")
    def test_12_HeartRate(self):
        from DICOMLib import DICOMUtils
        phantom = FlowPhantom(numberOfFrames=5)
        flowFieldNode, magnitudeVolumeNode = self.createFlowField(phantom, "volume")
        magnitudeSequenceNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(magnitudeVolumeNode).GetSequenceNode(magnitudeVolumeNode)
        self.report.checkClose("[4D flow MRI] Heart rate read from the magnitude sequence", self.logic.heartRateBpm(flowFieldNode), phantom.heartRateBpm(), atol=1e-6, unit="bpm")
        self.logic.setHeartRateBpm(flowFieldNode, 72.5, "user-specified")
        self.report.checkEqual("[4D flow MRI] Heart rate is stored on the magnitude sequence", magnitudeSequenceNode.GetAttribute("SlicerHeart.heartRateBpm"), "72.5")
        self.report.checkEqual("[4D flow MRI] Heart rate source is stored", magnitudeSequenceNode.GetAttribute("SlicerHeart.heartRateSource"), "user-specified")
        expectedFromLength = 60000.0 / (phantom.frameTimesMs[-1] - phantom.frameTimesMs[0])
        self.report.checkClose("Heart rate from acquisition length", self.logic.computeHeartRateBpmFromAcquisitionLength(flowFieldNode), expectedFromLength, atol=1e-6, unit="bpm")

        modelNode, _, _ = phantom.createFlowModelSequence()
        with self.assertRaises(RuntimeError):
            self.logic.heartRateBpm(modelNode)
        self.report.checkTrue("[model sequence] Missing heart rate is reported", True)
        self.logic.setHeartRateBpm(modelNode, 66.0, "test")
        modelSequenceNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(modelNode).GetSequenceNode(modelNode)
        self.report.checkEqual("[model sequence] Heart rate is stored on the model sequence", modelSequenceNode.GetAttribute("SlicerHeart.heartRateBpm"), "66.0")
        with self.assertRaises(RuntimeError):
            self.logic.computeHeartRateBpmFromDicom(modelNode)
        self.report.checkTrue("[model sequence] Heart rate from DICOM is rejected (no magnitude volume)", True)
        staticModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Static")
        self.logic.setHeartRateBpm(staticModelNode, 80.0, "test")
        self.report.checkEqual("[static model] Heart rate is stored on the model node", staticModelNode.GetAttribute("SlicerHeart.heartRateBpm"), "80.0")
        with self.assertRaises(RuntimeError):
            self.logic.computeHeartRateBpmFromAcquisitionLength(staticModelNode)
        self.report.checkTrue("[static model] Heart rate from acquisition length is rejected", True)
        self.logic.setHeartRateBpm(staticModelNode, 0.0, "test")
        with self.assertRaises(RuntimeError):
            self.logic.heartRateBpm(staticModelNode)
        self.report.checkTrue("Invalid (zero) heart rate is reported", True)

        # From DICOM
        dicomPhantom = FlowPhantom(dims=(16, 16, 8), spacingMm=(2.0, 2.0, 3.0), numberOfFrames=3, tissueRadiusMm=12.0, vesselRadiusMm=6.0, nominalIntervalMs=820.0)
        workDir = self.temporaryDirectory("Analyze4DFlowHeartRate_")
        dicomPhantom.writeDicomSeries(os.path.join(workDir, "dicom"), 150.0)
        slicer.mrmlScene.Clear()
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(workDir, "db")) as db:
            DICOMUtils.importDicom(os.path.join(workDir, "dicom"), db)
            FlowTestingUtils.loadDicomSeriesAsVolumeSequences()
            volumeNodeSet = list(self.importLogic.findVolumeNodeSets().values())[0]
            dicomFlowFieldNode = self.importLogic.createFlowFieldFromComponentVolumes(volumeNodeSet["componentVolumeNodes"],
                volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"], storeInTransform=False)
            self.report.checkClose("Heart rate from DICOM NominalInterval", self.logic.computeHeartRateBpmFromDicom(dicomFlowFieldNode),
                60000.0 / 820.0, atol=1e-6, unit="bpm")

    @reportedTest("Trapezoid integration with zero crossing",
        "`trapezoidAreaSplitZero` computes positive and negative areas under a curve, splitting intervals at zero crossings.")
    def test_13_TrapezoidAreaSplitZero(self):
        cases = [
            ("constant positive", [0, 1, 2], [2, 2, 2], (4.0, 0.0)),
            ("constant negative", [0, 1, 2], [-1, -1, -1], (0.0, -2.0)),
            ("symmetric crossing", [0, 1], [1, -1], (0.25, -0.25)),
            ("triangle", [0, 1, 2, 3], [0, 2, 0, -2], (2.0, -1.0)),
            ("unequal crossing", [0, 2], [3, -1], (2.25, -0.25)),
            ("single point", [0], [5], (0.0, 0.0)),
        ]
        rows = []
        for name, x, y, (expectedPositive, expectedNegative) in cases:
            positive, negative = Analyze4DFlowLogic.trapezoidAreaSplitZero(x, y)
            rows.append([name, x, y, positive, expectedPositive, negative, expectedNegative])
            self.report.checkClose(f"{name}: positive area", positive, expectedPositive, atol=1e-9)
            self.report.checkClose(f"{name}: negative area", negative, expectedNegative, atol=1e-9)
        # Sine: integral of sin over [0, 2 pi] = 2 (positive) and -2 (negative)
        x = np.linspace(0, 2 * np.pi, 2001)
        positive, negative = Analyze4DFlowLogic.trapezoidAreaSplitZero(x, np.sin(x))
        self.report.checkClose("sine: positive area", positive, 2.0, rtol=1e-5)
        self.report.checkClose("sine: negative area", negative, -2.0, rtol=1e-5)
        self.report.table(["Case", "x", "y", "Positive area", "Expected", "Negative area", "Expected"], rows)

    @reportedTest("Module GUI workflow",
        "The complete analysis is performed using the module GUI: select inputs and outputs, set heart rate (from acquisition"
        " length, manually), analyze, show plot. Errors are reported for missing heart rate, missing DICOM information, and"
        " missing Sequence Registration extension.")
    def test_14_GuiWorkflow(self):
        phantom = FlowPhantom()
        flowFieldNode, magnitudeVolumeNode = self.createFlowField(phantom, "transform")
        self.importLogic.setFlowFieldVisualizationToDefault(flowFieldNode)
        planeNode = phantom.createMeasurementPlane()
        segmentationNode, segmentId = phantom.createVesselSegmentation(magnitudeVolumeNode)
        magnitudeSequenceNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(magnitudeVolumeNode).GetSequenceNode(magnitudeVolumeNode)
        magnitudeSequenceNode.RemoveAttribute("SlicerHeart.heartRateBpm")

        slicer.util.selectModule("Analyze4DFlow")
        widget = slicer.modules.analyze4dflow.widgetRepresentation().self()
        parameterNode = widget._parameterNode
        parameterNode.inputFlowField = flowFieldNode
        parameterNode.inputPlane = planeNode
        widget.ui.inputMaskSegmentSelectorWidget.setCurrentNode(segmentationNode)
        widget.ui.inputMaskSegmentSelectorWidget.setCurrentSegmentID(segmentId)
        self.report.checkTrue("Mask segmentation is set from GUI", parameterNode.inputMaskSegmentation == segmentationNode
            and parameterNode.inputMaskSegmentID == segmentId)
        parameterNode.outputFlowMetricsModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Flow metrics")
        parameterNode.outputStreamlinesModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Streamlines")
        parameterNode.outputSpeedVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Speed")
        parameterNode.outputFlowMetricsTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Flow metrics table")
        parameterNode.outputFlowMetricsSummaryTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Flow metrics summary")
        parameterNode.samplingDistance = 1.0
        parameterNode.speedThreshold = 0.05

        # Heart rate is required for the summary
        self.report.checkClose("Heart rate is 0 in the GUI when not available", widget.ui.heartRateBpmDoubleSpinBox.value, 0.0, atol=1e-6, unit="bpm")
        with self.assertRaises(ValueError):
            widget.onAnalyzeButton()
        self.report.checkTrue("Analysis without heart rate is rejected (summary table requested)", True)
        with self.assertRaises(RuntimeError):
            widget.onSetHeartRateFromDicomButton()
        self.report.checkTrue("Heart rate from DICOM is rejected for images that are not loaded from DICOM", True)
        widget.onSetHeartRateFromLengthButton()
        expectedFromLength = 60000.0 / (phantom.frameTimesMs[-1] - phantom.frameTimesMs[0])
        self.report.checkClose("Heart rate from acquisition length is shown in GUI", widget.ui.heartRateBpmDoubleSpinBox.value, expectedFromLength, atol=0.01, unit="bpm")
        widget.ui.heartRateBpmDoubleSpinBox.value = phantom.heartRateBpm()
        widget.onHeartRateEdited()
        self.report.checkClose("Manually entered heart rate is stored", self.logic.heartRateBpm(flowFieldNode), phantom.heartRateBpm(), atol=0.01, unit="bpm")
        self.report.checkEqual("Heart rate source", magnitudeSequenceNode.GetAttribute("SlicerHeart.heartRateSource"), "user-specified")

        startTime = time.time()
        widget.onAnalyzeButton()
        self.report.text(f"Analysis time (GUI): {time.time() - startTime:.1f} s")
        metrics = tableToDict(parameterNode.outputFlowMetricsTable)
        summaryMetrics = {name: values[0] for name, values in tableToDict(parameterNode.outputFlowMetricsSummaryTable).items()}
        self.report.checkEqual("[GUI] Flow metrics table rows", len(metrics.get("FlowRate", [])), phantom.numberOfFrames)
        forward, _ = phantom.expectedForwardBackwardVolumeMl()
        self.report.checkClose("[GUI] Forward volume", summaryMetrics.get("ForwardVolume", float("nan")), forward, rtol=0.08, unit="ml")
        self.report.checkTrue("[GUI] Summary table is shown in the GUI", widget.ui.FlowMetricsSummaryTableView.mrmlTableNode() == parameterNode.outputFlowMetricsSummaryTable)
        self.report.checkTrue("[GUI] Flow metrics table is shown in the GUI", widget.ui.FlowMetricsTableView.mrmlTableNode() == parameterNode.outputFlowMetricsTable)
        FlowTestingUtils.selectSequenceItem(flowFieldNode, phantom.peakFrameIndex())
        FlowTestingUtils.showVolumeInSliceViews(magnitudeVolumeNode, phantom.centerRas, foreground=parameterNode.outputSpeedVolume, foregroundOpacity=0.6)
        FlowTestingUtils.reset3DView()
        self.report.screenshot("Module GUI after analysis (peak systole)", kind="window")

        widget.onShowFlowMetricsPlotButton()
        self.report.checkTrue("[GUI] Plot chart is created", parameterNode.outputFlowMetricsPlotChart is not None)
        self.report.screenshot("Module GUI with flow metrics plot", kind="window")

        # Sequence registration (requires SequenceRegistration extension)
        if hasattr(slicer.modules, "sequenceregistration"):
            widget.onSequenceRegistrationPushButton()
            self.report.checkTrue("[GUI] Sequence registration module is set up", slicer.util.moduleSelector().selectedModule == "SequenceRegistration")
        else:
            with self.assertRaises(RuntimeError) as context:
                widget.onSequenceRegistrationPushButton()
            self.report.checkTrue("[GUI] Missing Sequence Registration extension is reported", "Sequence registration" in str(context.exception),
                str(context.exception))
            self.report.text("Sequence Registration extension is not installed: only the error reporting is tested.")

    @reportedTest("Anonymized clinical 4D flow MRI data set",
        "A real Siemens 4D flow acquisition is imported (grid transform and vector volume storage). A measurement plane is"
        " placed automatically at the location of the highest coherent flow velocity (normal = local mean flow direction), with a"
        " spherical mask. Both storage formats must give identical flow metrics, values must be physiologically plausible.")
    def test_15_RealData(self):
        from DICOMLib import DICOMUtils
        dataDir = self.realDataDirectoryOrSkip()
        timings = []
        workDir = self.temporaryDirectory("Analyze4DFlowRealData_")
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(workDir, "db")) as db:
            startTime = time.time()
            DICOMUtils.importDicom(dataDir, db)
            FlowTestingUtils.loadDicomSeriesAsVolumeSequences()
            volumeNodeSets = self.importLogic.findVolumeNodeSets()
            timings.append(["Load DICOM", time.time() - startTime])
            self.report.checkEqual("Number of detected 4D flow image sets", len(volumeNodeSets), 1)
            if not volumeNodeSets:
                return
            volumeNodeSet = list(volumeNodeSets.values())[0]
            flowFieldNodes = {}
            for kind in ["transform", "volume"]:
                startTime = time.time()
                flowFieldNode = self.importLogic.createFlowFieldFromComponentVolumes(volumeNodeSet["componentVolumeNodes"],
                    volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"], storeInTransform=(kind == "transform"))
                self.importLogic.temporalUnwrap(flowFieldNode, 0, 5.0)
                self.importLogic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
                timings.append([f"Import flow field ({KIND_NAMES[kind]})", time.time() - startTime])
                flowFieldNodes[kind] = flowFieldNode
            heartRateFromDicom = self.logic.computeHeartRateBpmFromDicom(flowFieldNodes["transform"])
        magnitudeVolumeNode = volumeNodeSet["magnitudeVolumeNode"]
        heartRate = self.logic.heartRateBpm(flowFieldNodes["transform"])
        self.report.checkClose("Heart rate from DICOM equals heart rate stored at import", heartRateFromDicom, heartRate, atol=1e-6, unit="bpm")
        self.report.checkRange("Heart rate", heartRate, 30, 220, "bpm")
        self.report.checkClose("Heart rate is the same for both storage formats", self.logic.heartRateBpm(flowFieldNodes["volume"]), heartRate, atol=1e-6, unit="bpm")

        peakSpeed, peakFrame, peakIndex, peakRas, flowDirection = self.findPeakCoherentFlow(flowFieldNodes["volume"], magnitudeVolumeNode)
        self.report.text(f"Measurement plane is placed at frame {peakFrame}, RAS position {np.round(peakRas, 1).tolist()},"
            f" normal {np.round(flowDirection, 3).tolist()} (coherent speed in 5x5x5 neighborhood: {peakSpeed:.2f} m/s).")
        planeNode = self.createPlane(peakRas, flowDirection, 30.0, "Measurement plane")
        segmentationNode, segmentId = self.createSphereSegmentation(peakRas, 10.0, magnitudeVolumeNode, "Vessel mask")

        results = {}
        outputsByKind = {}
        for kind in ["transform", "volume"]:
            startTime = time.time()
            outputs, metrics, summaryMetrics = self.analyze(flowFieldNodes[kind], planeNode, segmentationNode, segmentId,
                streamlines=(kind == "transform"), speedVolume=(kind == "transform"), speedThreshold=0.1)
            timings.append([f"Analyze ({KIND_NAMES[kind]})", time.time() - startTime])
            results[kind] = (metrics, summaryMetrics)
            outputsByKind[kind] = outputs
        transformMetrics, transformSummary = results["transform"]
        volumeMetrics, volumeSummary = results["volume"]
        differences = [abs(a - b) for name in transformMetrics for a, b in zip(transformMetrics[name], volumeMetrics.get(name, []))]
        differences += [abs(transformSummary[name] - volumeSummary.get(name, float("nan"))) for name in transformSummary]
        self.report.checkClose("Grid transform vs. vector volume: max. difference of all metrics", max(differences), 0.0, atol=1e-3)

        self.report.checkRange("Peak velocity", transformSummary["PeakVelocity"], 30, 600, "cm/s")
        self.report.checkRange("Forward volume (per heart beat)", transformSummary["ForwardVolume"], 1, 200, "ml")
        self.report.checkRange("Regurgitation fraction", transformSummary["RegurgitationFraction"], 0, 100, "%")
        self.report.checkRange("Forward flow per minute", transformSummary["VolPerMinute"], 0.1, 20, "l/min")
        self.report.checkTrue("Peak flow occurs in systole (first half of the acquired frames)",
            int(np.argmax(transformMetrics["FlowRate"])) < len(transformMetrics["FlowRate"]) // 2 + 1,
            int(np.argmax(transformMetrics["FlowRate"])), f"< {len(transformMetrics['FlowRate']) // 2 + 1}")
        streamlinesNode = outputsByKind["transform"]["streamlines"]
        FlowTestingUtils.selectSequenceItem(flowFieldNodes["transform"], peakFrame)
        numberOfLines = streamlinesNode.GetPolyData().GetNumberOfLines() if streamlinesNode.GetPolyData() else 0
        self.report.checkTrue("Streamlines are generated at peak systole", numberOfLines > 0, numberOfLines, "> 0")

        self.report.table(["Metric", "Grid transform", "Vector volume"],
            [[name, transformSummary[name], volumeSummary.get(name)] for name in transformSummary], "Summary flow metrics")
        self.report.table(["Time (ms)", "Flow rate (ml/s)", "Area (mm2)", "Mean velocity (cm/s)", "Max. velocity (cm/s)"],
            [[transformMetrics["Time"][i], transformMetrics["FlowRate"][i], transformMetrics["Area"][i], transformMetrics["MeanVelocity"][i],
              transformMetrics["MaxVelocity"][i]] for i in range(len(transformMetrics["Time"]))], "Flow metrics per frame (grid transform)")
        self.report.table(["Step", "Duration (s)"], [[name, f"{duration:.1f}"] for name, duration in timings], "Computation times")

        # Screenshots
        self.importLogic.setFlowFieldVisualizationToDefault(flowFieldNodes["transform"])
        FlowTestingUtils.showVolumeInSliceViews(magnitudeVolumeNode, peakRas, foreground=outputsByKind["transform"]["speedVolume"], foregroundOpacity=0.6)
        segmentationNode.GetDisplayNode().SetOpacity3D(0.2)
        FlowTestingUtils.reset3DView()
        self.report.screenshot(f"Clinical data set at frame {peakFrame}: speed volume over magnitude image, streamlines and measurement plane in 3D")
        self.logic.createPlotFromTable(outputsByKind["transform"]["table"])
        self.report.screenshot("Flow metrics plot of the clinical data set")

    @reportedTest("Clinical data set: analysis options",
        "Analysis options are tested on the clinical data set (vector volume storage), at the location of the highest coherent"
        " flow: mass conservation (peak flow rate through parallel planes 4 mm upstream and downstream), plane orientation"
        " (plane tilted by 20 degrees), speed threshold mask (no segmentation), speed volume (magnitude and projected to the"
        " plane normal), and masked flow field output (grid transform and vector volume storage). Consistency is checked using"
        " the peak (systolic) flow rate, because forward and backward volumes also integrate the low velocities of diastolic"
        " frames, which are dominated by noise at the boundary of the (approximate, spherical) vessel mask.")
    def test_16_RealDataAnalysisOptions(self):
        from DICOMLib import DICOMUtils
        dataDir = self.realDataDirectoryOrSkip()
        workDir = self.temporaryDirectory("Analyze4DFlowRealDataOptions_")
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(workDir, "db")):
            volumeNodeSet, flowFieldNodes = self.loadRealDataFlowFields(dataDir)
        magnitudeVolumeNode = volumeNodeSet["magnitudeVolumeNode"]
        flowFieldNode = flowFieldNodes["volume"]
        peakSpeed, peakFrame, peakIndex, peakRas, flowDirection = self.findPeakCoherentFlow(flowFieldNode, magnitudeVolumeNode)
        maskRadiusMm = 10.0
        self.report.text(f"Measurement location: frame {peakFrame}, RAS position {np.round(peakRas, 1).tolist()},"
            f" flow direction {np.round(flowDirection, 3).tolist()}, coherent speed {peakSpeed:.2f} m/s.")

        # Mass conservation: the same blood volume must flow through parallel planes along the vessel
        rows = []
        peakFlowRates = {}
        for offsetMm in [-4.0, 0.0, 4.0]:
            centerRas = peakRas + offsetMm * flowDirection
            planeNode = self.createPlane(centerRas, flowDirection, 30.0, f"Plane {offsetMm:+g} mm")
            segmentationNode, segmentId = self.createSphereSegmentation(centerRas, maskRadiusMm, magnitudeVolumeNode, f"Mask {offsetMm:+g} mm")
            _, metrics, summaryMetrics = self.analyze(flowFieldNode, planeNode, segmentationNode, segmentId)
            peakFlowRates[offsetMm] = max(metrics["FlowRate"])
            rows.append([f"perpendicular, {offsetMm:+g} mm", summaryMetrics["ForwardVolume"], summaryMetrics["BackwardVolume"],
                max(metrics["FlowRate"]), summaryMetrics["PeakVelocity"]])
        for offsetMm in [-4.0, 4.0]:
            self.report.checkClose(f"Mass conservation: peak flow rate {offsetMm:+g} mm along the vessel vs. at the measurement location",
                peakFlowRates[offsetMm], peakFlowRates[0.0], rtol=0.2, unit="ml/s")

        # Plane orientation: flow through a tilted plane (at the same location) must be similar
        helperAxis = np.array([1.0, 0.0, 0.0]) if abs(flowDirection[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        perpendicular = np.cross(flowDirection, helperAxis)
        perpendicular /= np.linalg.norm(perpendicular)
        tiltDeg = 20.0
        tiltedNormal = math.cos(math.radians(tiltDeg)) * flowDirection + math.sin(math.radians(tiltDeg)) * perpendicular
        planeNode = self.createPlane(peakRas, tiltedNormal, 30.0, "Tilted plane")
        segmentationNode, segmentId = self.createSphereSegmentation(peakRas, maskRadiusMm, magnitudeVolumeNode, "Mask tilted")
        _, metrics, summaryMetrics = self.analyze(flowFieldNode, planeNode, segmentationNode, segmentId)
        rows.append([f"tilted by {tiltDeg:g} deg", summaryMetrics["ForwardVolume"], summaryMetrics["BackwardVolume"],
            max(metrics["FlowRate"]), summaryMetrics["PeakVelocity"]])
        self.report.checkClose(f"Peak flow rate through plane tilted by {tiltDeg:g} deg vs. perpendicular plane",
            max(metrics["FlowRate"]), peakFlowRates[0.0], rtol=0.2, unit="ml/s")

        # Speed threshold mask (no segmentation)
        planeNode = self.createPlane(peakRas, flowDirection, 20.0, "Plane, speed threshold mask")
        _, metrics, summaryMetrics = self.analyze(flowFieldNode, planeNode, speedThreshold=0.1)
        rows.append(["speed threshold mask (0.1 m/s), 20 mm plane", summaryMetrics["ForwardVolume"], summaryMetrics["BackwardVolume"],
            max(metrics["FlowRate"]), summaryMetrics["PeakVelocity"]])
        self.report.checkTrue("[speed threshold mask] Area at peak flow is positive", metrics["Area"][peakFrame] > 0, metrics["Area"][peakFrame], "> 0")
        self.report.checkRange("[speed threshold mask] Forward volume", summaryMetrics["ForwardVolume"], 0.5, 200, "ml")
        self.report.table(["Measurement", "Forward volume (ml)", "Backward volume (ml)", "Max. flow rate (ml/s)", "Peak velocity (cm/s)"], rows)

        # Speed volume (magnitude and projected), masked flow field output
        ijkToRas = vtk.vtkMatrix4x4()
        magnitudeVolumeNode.GetIJKToRASMatrix(ijkToRas)
        ijkToRasArray = slicer.util.arrayFromVTKMatrix(ijkToRas)
        dims = magnitudeVolumeNode.GetImageData().GetDimensions()
        k, j, i = np.indices((dims[2], dims[1], dims[0]))
        voxelRas = np.stack([i, j, k], axis=-1) @ ijkToRasArray[:3, :3].T + ijkToRasArray[:3, 3]
        distanceFromCenter = np.linalg.norm(voxelRas - peakRas, axis=-1)
        inside = distanceFromCenter < maskRadiusMm - 2.0
        outside = distanceFromCenter > maskRadiusMm + 2.0
        planeNode = self.createPlane(peakRas, flowDirection, 30.0, "Plane, speed volume")
        segmentationNode, segmentId = self.createSphereSegmentation(peakRas, maskRadiusMm, magnitudeVolumeNode, "Mask, speed volume")
        originalFrame = slicer.util.arrayFromVolume(self.importLogic._getSequenceFromProxyNode(flowFieldNode).GetNthDataNode(peakFrame)).copy()
        speedValues = {}
        for projected in [False, True]:
            speedVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Speed projected" if projected else "Speed")
            self.logic.sampleFlowFieldWithPlane(planeNode, flowFieldNode, samplingDistanceMm=1.0,
                outputFlowMetricsModel=slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Metrics"),
                maskSegmentationNode=segmentationNode, maskSegmentID=segmentId,
                outputSpeedVolume=speedVolumeNode, speedVolumeProjectedToPlane=projected, streamlinesSpeedThresholdMPerSec=0.1)
            FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
            speedValues[projected] = slicer.util.arrayFromVolume(speedVolumeNode).copy()
        expectedMagnitude = np.linalg.norm(originalFrame, axis=-1)
        expectedProjected = originalFrame @ np.array(planeNode.GetNormalWorld())
        self.report.checkClose("[speed volume] Max. error of speed magnitude inside the mask",
            float(np.abs(speedValues[False] - expectedMagnitude)[inside].max()), 0.0, atol=1e-4, unit="m/s")
        self.report.checkClose("[speed volume] Max. error of projected speed inside the mask",
            float(np.abs(speedValues[True] - expectedProjected)[inside].max()), 0.0, atol=1e-4, unit="m/s")
        self.report.checkClose("[speed volume] Max. speed outside the mask", float(np.abs(speedValues[False])[outside].max()), 0.0, atol=1e-6, unit="m/s")
        self.report.checkTrue("[speed volume] Projected speed at the measurement location is positive (flow along the plane normal)",
            speedValues[True][peakIndex] > 0, float(speedValues[True][peakIndex]), "> 0")
        FlowTestingUtils.showVolumeInSliceViews(magnitudeVolumeNode, peakRas, foreground=speedVolumeNode, foregroundOpacity=0.7)
        self.report.screenshot(f"Clinical data set: speed projected to the plane normal (Doppler-like) at frame {peakFrame}")

        for kind in ["transform", "volume"]:
            outputNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode" if kind == "transform" else "vtkMRMLVectorVolumeNode", f"Masked {kind}")
            self.analyze(flowFieldNodes[kind], planeNode, segmentationNode, segmentId, maskedOutput=outputNode, summary=False)
            FlowTestingUtils.selectSequenceItem(flowFieldNodes[kind], peakFrame)
            maskedFrame = slicer.util.arrayFromGridTransform(outputNode) if kind == "transform" else slicer.util.arrayFromVolume(outputNode)
            self.report.checkClose(f"[masked flow field, {KIND_NAMES[kind]}] Max. velocity error inside the mask",
                float(np.abs(maskedFrame - originalFrame)[inside].max()), 0.0, atol=1e-4, unit="m/s")
            self.report.checkClose(f"[masked flow field, {KIND_NAMES[kind]}] Max. speed outside the mask",
                float(np.linalg.norm(maskedFrame, axis=-1)[outside].max()), 0.0, atol=1e-6, unit="m/s")

    @reportedTest("Clinical data set: module GUI workflow",
        "The analysis of the clinical data set is performed using the module GUI: heart rate from DICOM, analysis with all"
        " outputs, flow metrics plot, and sequence registration (requires the Sequence Registration extension).")
    def test_17_RealDataGuiWorkflow(self):
        from DICOMLib import DICOMUtils
        dataDir = self.realDataDirectoryOrSkip()
        workDir = self.temporaryDirectory("Analyze4DFlowRealDataGui_")
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(workDir, "db")):
            volumeNodeSet, flowFieldNodes = self.loadRealDataFlowFields(dataDir)
            magnitudeVolumeNode = volumeNodeSet["magnitudeVolumeNode"]
            flowFieldNode = flowFieldNodes["transform"]
            self.importLogic.setFlowFieldVisualizationToDefault(flowFieldNode)
            peakSpeed, peakFrame, peakIndex, peakRas, flowDirection = self.findPeakCoherentFlow(flowFieldNodes["volume"], magnitudeVolumeNode)
            planeNode = self.createPlane(peakRas, flowDirection, 30.0, "Measurement plane")
            segmentationNode, segmentId = self.createSphereSegmentation(peakRas, 10.0, magnitudeVolumeNode, "Vessel mask")

            # Remove heart rate stored at import, so that it is set from DICOM using the GUI
            magnitudeSequenceNode = self.importLogic._getSequenceFromProxyNode(magnitudeVolumeNode)
            heartRateAtImport = float(magnitudeSequenceNode.GetAttribute("SlicerHeart.heartRateBpm"))
            magnitudeSequenceNode.RemoveAttribute("SlicerHeart.heartRateBpm")

            slicer.util.selectModule("Analyze4DFlow")
            widget = slicer.modules.analyze4dflow.widgetRepresentation().self()
            parameterNode = widget._parameterNode
            parameterNode.inputFlowField = flowFieldNode
            parameterNode.inputPlane = planeNode
            widget.ui.inputMaskSegmentSelectorWidget.setCurrentNode(segmentationNode)
            widget.ui.inputMaskSegmentSelectorWidget.setCurrentSegmentID(segmentId)
            parameterNode.outputFlowMetricsModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Flow metrics")
            parameterNode.outputStreamlinesModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Streamlines")
            parameterNode.outputSpeedVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Speed")
            parameterNode.outputMaskedFlowField = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", "Masked flow field")
            parameterNode.outputFlowMetricsTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Flow metrics table")
            parameterNode.outputFlowMetricsSummaryTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Flow metrics summary")
            parameterNode.samplingDistance = 1.0
            parameterNode.speedThreshold = 0.1

            widget.onSetHeartRateFromDicomButton()
            self.report.checkClose("[GUI] Heart rate from DICOM", widget.ui.heartRateBpmDoubleSpinBox.value, heartRateAtImport, atol=0.01, unit="bpm")
            self.report.checkEqual("[GUI] Heart rate source", magnitudeSequenceNode.GetAttribute("SlicerHeart.heartRateSource"), "dicom-nominal-interval")

        startTime = time.time()
        widget.onAnalyzeButton()
        self.report.text(f"Analysis time (GUI): {time.time() - startTime:.1f} s")
        metrics = tableToDict(parameterNode.outputFlowMetricsTable)
        summaryMetrics = {name: values[0] for name, values in tableToDict(parameterNode.outputFlowMetricsSummaryTable).items()}
        numberOfFrames = self.importLogic._getNumberOfDataNodesInSequence(magnitudeVolumeNode)
        self.report.checkEqual("[GUI] Flow metrics table rows", len(metrics.get("FlowRate", [])), numberOfFrames)
        self.report.checkRange("[GUI] Forward volume", summaryMetrics.get("ForwardVolume", float("nan")), 1, 200, "ml")
        self.report.checkRange("[GUI] Forward flow per minute", summaryMetrics.get("VolPerMinute", float("nan")), 0.1, 20, "l/min")
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        for name in ["outputFlowMetricsModel", "outputStreamlinesModel", "outputSpeedVolume", "outputMaskedFlowField"]:
            self.report.checkTrue(f"[GUI] Output '{name}' is in the flow field's sequence browser",
                browserNode.GetSequenceNode(getattr(parameterNode, name)) is not None)
        FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
        FlowTestingUtils.showVolumeInSliceViews(magnitudeVolumeNode, peakRas, foreground=parameterNode.outputSpeedVolume, foregroundOpacity=0.6)
        FlowTestingUtils.reset3DView()
        self.report.screenshot("Clinical data set: module GUI after analysis", kind="window")

        widget.onShowFlowMetricsPlotButton()
        self.report.checkTrue("[GUI] Plot chart is created", parameterNode.outputFlowMetricsPlotChart is not None)
        self.report.screenshot("Clinical data set: module GUI with flow metrics plot", kind="window")

        if hasattr(slicer.modules, "sequenceregistration"):
            widget.onSequenceRegistrationPushButton()
            self.report.checkTrue("[GUI] Sequence registration module is set up", slicer.util.moduleSelector().selectedModule == "SequenceRegistration")
        else:
            with self.assertRaises(RuntimeError) as context:
                widget.onSequenceRegistrationPushButton()
            self.report.checkTrue("[GUI] Missing Sequence Registration extension is reported", "Sequence registration" in str(context.exception),
                str(context.exception))
            self.report.text("Sequence Registration extension is not installed: only the error reporting is tested.")

    # slicerheart_4dflow methods

    def createLibraryFlowField(self, phantom, kind="volume"):
        """Flow field (image) with vessel segmentation. Returns (flowFieldNode, magnitudeVolumeNode, segmentationNode, segmentId)."""
        flowFieldNode, magnitudeVolumeNode = self.createFlowField(phantom, kind)
        segmentationNode, segmentId = phantom.createVesselSegmentation(magnitudeVolumeNode)
        return flowFieldNode, magnitudeVolumeNode, segmentationNode, segmentId

    @reportedTest("Flow metrics by disc sampling (slicerheart_4dflow)",
        "The disc sampling method (slicerheart_4dflow plane sampling with mask-normalized interpolation) fills the same flow metrics"
        " tables as the plane probe method. Per-frame and summary metrics must match the analytic phantom and the plane probe method,"
        " for both image flow field storage formats.")
    def test_18_FlowMetricsDiscSampling(self):
        phantom = FlowPhantom()
        rows = []
        for kind in ["transform", "volume"]:
            slicer.mrmlScene.Clear()
            flowFieldNode, magnitudeVolumeNode, segmentationNode, segmentId = self.createLibraryFlowField(phantom, kind)
            planeNode = phantom.createMeasurementPlane()
            table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Disc sampling metrics")
            summaryTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Disc sampling summary")
            startTime = time.time()
            self.logic.computeFlowMetricsTableDiscSampling(planeNode, flowFieldNode, segmentationNode, segmentId, 0.0, table, summaryTable)
            discTime = time.time() - startTime
            metrics = tableToDict(table)
            summaryMetrics = {name: values[0] for name, values in tableToDict(summaryTable).items()}
            self.report.checkEqual(f"[{KIND_NAMES[kind]}] Disc sampling table has the same columns as the plane probe table",
                sorted(metrics.keys()), sorted(["Time", "Area", "PositiveArea", "NegativeArea", "FlowRate", "PositiveFlowRate", "NegativeFlowRate",
                "MeanVelocity", "MaxVelocity", "MinVelocity", "Percentile1Velocity", "Percentile5Velocity", "Percentile95Velocity",
                "Percentile99Velocity", "StdDevVelocity"]))
            self.checkMetricsAgainstPhantom(f"[disc sampling, {KIND_NAMES[kind]}]", phantom, metrics, summaryMetrics, flowRtol=0.03, areaRtol=0.08)
            startTime = time.time()
            _, probeMetrics, probeSummary = self.analyze(flowFieldNode, planeNode, segmentationNode, segmentId, speedThreshold=0.0)
            probeTime = time.time() - startTime
            difference = max(abs(a - b) for a, b in zip(metrics["FlowRate"], probeMetrics["FlowRate"]))
            peakFlow = max(abs(q) for q in probeMetrics["FlowRate"])
            self.report.checkClose(f"[{KIND_NAMES[kind]}] Disc sampling and plane probe flow rates agree (max. difference)", difference, 0.0,
                atol=0.03 * peakFlow, unit="ml/s")
            rows.append([KIND_NAMES[kind], summaryMetrics["ForwardVolume"], probeSummary["ForwardVolume"], discTime, probeTime])
        self.report.table(["Storage", "Forward volume, disc sampling (ml)", "Forward volume, plane probe (ml)", "Disc sampling time (s)", "Plane probe time (s)"], rows)

        # Vector volume flow field stored in mm/s (voxel value units): slicerheart_4dflow methods must use the unit
        sequenceNode = self.importLogic._getSequenceFromProxyNode(flowFieldNode)
        for frameIndex in range(sequenceNode.GetNumberOfDataNodes()):
            frameNode = sequenceNode.GetNthDataNode(frameIndex)
            slicer.util.arrayFromVolume(frameNode)[:] *= 1000.0
            slicer.util.arrayFromVolumeModified(frameNode)
            frameNode.SetVoxelValueUnits(Analyze4DFlowLogic.createVelocityUnits("mm/s"))
        flowFieldNode.SetVoxelValueUnits(Analyze4DFlowLogic.createVelocityUnits("mm/s"))
        mmPerSecTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Disc sampling metrics (mm/s flow field)")
        self.logic.computeFlowMetricsTableDiscSampling(planeNode, flowFieldNode, segmentationNode, segmentId, 0.0, mmPerSecTable)
        difference = max(abs(a - b) for a, b in zip(tableToDict(mmPerSecTable)["FlowRate"], metrics["FlowRate"]))
        self.report.checkClose("[vector volume in mm/s] Disc sampling flow rates equal the flow rates of the m/s flow field (max. difference)",
            difference, 0.0, atol=1e-3 * max(abs(q) for q in metrics["FlowRate"]), unit="ml/s")

    @reportedTest("Pathlines (slicerheart_4dflow)",
        "Time-resolved pathlines are emitted from the measurement plane in the vessel at peak systole and traced for 30 ms."
        " In Poiseuille flow particles move along the vessel axis at constant radius: they must stay in the vessel and travel the"
        " distance given by the time integral of the analytic velocity (linearly interpolated between frames).")
    def test_19_Pathlines(self):
        phantom = FlowPhantom()
        flowFieldNode, magnitudeVolumeNode, segmentationNode, segmentId = self.createLibraryFlowField(phantom, "volume")
        planeNode = phantom.createMeasurementPlane()
        pathlinesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Pathlines")
        peakFrame = phantom.peakFrameIndex()
        durationMs = 30.0  # particles near the centerline travel about 30 mm (they would leave the field of view in a longer time)
        self.logic.createPathlines(pathlinesNode, flowFieldNode, planeNode, segmentationNode, segmentId, seedSpacingMm=3.0,
                                   durationMs=durationMs, emissionFrames=[peakFrame])
        polyData = pathlinesNode.GetPolyData()
        self.report.checkTrue("Pathlines are created", polyData.GetNumberOfLines() > 10, polyData.GetNumberOfLines(), "> 10")
        for arrayName in ["time_ms", "Speed", "EmissionTime"]:
            self.report.checkTrue(f"Pathlines have '{arrayName}' point data", polyData.GetPointData().GetArray(arrayName) is not None)
        points = vtk.util.numpy_support.vtk_to_numpy(polyData.GetPoints().GetData())
        times = vtk.util.numpy_support.vtk_to_numpy(polyData.GetPointData().GetArray("time_ms"))
        radial = phantom.radialDistance(points)
        self.report.checkTrue("Pathline points are in the vessel", np.mean(radial < phantom.vesselRadiusMm + 1.0) > 0.99,
            f"{100 * np.mean(radial < phantom.vesselRadiusMm + 1.0):.1f}%", "> 99%")

        # Expected axial displacement: (1 - r^2/R^2) * integral of vmax(t), frames uniformly spanning the cardiac cycle
        rrMs = self.logic.cycleDurationMs(flowFieldNode)
        frameTimes = np.arange(phantom.numberOfFrames + 1) * rrMs / phantom.numberOfFrames
        vmax = np.array([phantom.maxVelocity(i) for i in range(phantom.numberOfFrames)] + [phantom.maxVelocity(0)])
        errors = []
        lines = polyData.GetLines()
        lines.InitTraversal()
        idList = vtk.vtkIdList()
        while lines.GetNextCell(idList):
            ids = [idList.GetId(i) for i in range(idList.GetNumberOfIds())]
            if len(ids) < 2 or radial[ids[0]] > 0.7 * phantom.vesselRadiusMm:
                continue
            t0, t1 = times[ids[0]], times[ids[-1]]
            if t1 - t0 < 0.6 * durationMs:
                continue  # left the field of view (path points are recorded at the tracer time steps, so the last partial step is missing)
            sampleTimes = np.linspace(t0, t1, 200)
            integral = np.trapezoid(np.interp(sampleTimes % rrMs, frameTimes, vmax), sampleTimes)  # m/s * ms = mm
            expected = (1 - (radial[ids[0]] / phantom.vesselRadiusMm) ** 2) * integral
            measured = (points[ids[-1]] - points[ids[0]]) @ phantom.vesselAxis
            errors.append(abs(measured - expected) / max(abs(expected), 1e-6))
        self.report.checkTrue("Pathlines that are traced for the full duration", len(errors) > 5, len(errors), "> 5")
        self.report.checkClose("Median relative error of the pathline displacement along the vessel", float(np.median(errors)), 0.0, atol=0.1)
        FlowTestingUtils.showVolumeInSliceViews(magnitudeVolumeNode, phantom.centerRas)
        FlowTestingUtils.reset3DView()
        self.report.screenshot("Pathlines emitted from the measurement plane at peak systole")

    @reportedTest("Hemodynamics: vorticity, helicity, kinetic energy, energy loss (slicerheart_4dflow)",
        "Velocity-derived maps are computed in the vessel and stored in volume sequences that are browsed with the flow field."
        " In Poiseuille flow the vorticity magnitude is 2 vmax r / R^2, the relative helicity is zero, the kinetic energy is"
        " (rho/2) integral of v^2 (= rho pi R^2 L vmax^2 / 6) and the viscous energy loss rate is mu integral of (dv/dr)^2 (= 2 pi mu L vmax^2).")
    def test_20_Hemodynamics(self):
        phantom = FlowPhantom()
        flowFieldNode, magnitudeVolumeNode, segmentationNode, segmentId = self.createLibraryFlowField(phantom, "volume")
        outputs = [slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name) for name in ["Vorticity", "Helicity", "Kinetic energy", "Energy loss"]]
        table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Hemodynamics")
        startTime = time.time()
        self.logic.computeHemodynamics(flowFieldNode, segmentationNode, segmentId, *outputs, table)
        self.report.text(f"Computation time: {time.time() - startTime:.1f} s")
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        for outputNode in outputs:
            self.report.checkTrue(f"'{outputNode.GetName()}' is browsed with the flow field", browserNode.GetSequenceNode(outputNode) is not None)
        peakFrame = phantom.peakFrameIndex()
        FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
        vmax = phantom.maxVelocity(peakFrame) * 1000  # mm/s
        R = phantom.vesselRadiusMm
        interior = phantom.radialDistanceMm < 0.7 * R
        # Exclude the image faces where the vessel exits (one-sided derivatives)
        interior[:2], interior[-2:], interior[:, :2], interior[:, -2:], interior[:, :, :2], interior[:, :, -2:] = False, False, False, False, False, False
        vorticity = slicer.util.arrayFromVolume(outputs[0])
        expectedVorticity = 2 * vmax * phantom.radialDistanceMm / R ** 2
        self.report.checkClose("Mean vorticity magnitude at peak systole (r < 0.7 R)", float(vorticity[interior].mean()), float(expectedVorticity[interior].mean()),
            rtol=0.1, unit="1/s")
        helicity = slicer.util.arrayFromVolume(outputs[1])
        self.report.checkClose("Mean relative helicity", float(np.abs(helicity[interior]).mean()), 0.0, atol=0.05)
        metrics = tableToDict(table)
        self.report.checkEqual("Hemodynamics table rows", len(metrics["KineticEnergy"]), phantom.numberOfFrames)
        lumenVolumeMm3 = float(np.count_nonzero(phantom.insideVessel)) * float(np.prod(phantom.spacingMm))
        lengthMm = lumenVolumeMm3 / (math.pi * R ** 2)
        expectedKineticEnergyMJ = 1060 * math.pi * (R * 1e-3) ** 2 * (lengthMm * 1e-3) * (vmax * 1e-3) ** 2 / 6 * 1e3
        self.report.checkClose("Kinetic energy at peak systole", metrics["KineticEnergy"][peakFrame], expectedKineticEnergyMJ, rtol=0.15, unit="mJ")
        expectedEnergyLossMW = 2 * math.pi * 0.0035 * (lengthMm * 1e-3) * (vmax * 1e-3) ** 2 * 1e3
        self.report.checkClose("Viscous energy loss rate at peak systole", metrics["EnergyLossRate"][peakFrame], expectedEnergyLossMW, rtol=0.3, unit="mW")
        FlowTestingUtils.showVolumeInSliceViews(outputs[0], phantom.centerRas)
        self.report.screenshot("Vorticity magnitude at peak systole")

    @reportedTest("Wall shear stress (slicerheart_4dflow)",
        "Wall shear stress is computed on the closed surface of the vessel segment. In Poiseuille flow WSS = 2 mu vmax / R along"
        " the vessel wall (away from the open ends), TAWSS is the time average of its magnitude and OSI is 0.5 (1 - |mean WSS| / TAWSS).")
    def test_21_WallShearStress(self):
        phantom = FlowPhantom()
        flowFieldNode, magnitudeVolumeNode, segmentationNode, segmentId = self.createLibraryFlowField(phantom, "volume")
        wssModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Wall shear stress")
        startTime = time.time()
        result = self.logic.computeWallShearStress(flowFieldNode, segmentationNode, segmentId, wssModel)
        self.report.text(f"Computation time: {time.time() - startTime:.1f} s, {len(result['points'])} wall points")
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        self.report.checkTrue("Wall shear stress model is browsed with the flow field", browserNode.GetSequenceNode(wssModel) is not None)
        for arrayName in ["WSS", "WSSMagnitude", "TAWSS", "OSI"]:
            self.report.checkTrue(f"Model has '{arrayName}' point data", wssModel.GetPolyData().GetPointData().GetArray(arrayName) is not None)
        # Wall points along the vessel, away from the image faces
        points = result["points"]
        ijkToRas = slicer.util.arrayFromVTKMatrix(phantom.ijkToRasMatrix())
        ijk = (np.linalg.inv(ijkToRas) @ np.c_[points, np.ones(len(points))].T)[:3].T
        dims = np.array(phantom.dims)
        valid = np.all((ijk > 4) & (ijk < dims - 5), axis=1)
        peakFrame = phantom.peakFrameIndex()
        expectedPeakWss = 2 * 0.0035 * phantom.maxVelocity(peakFrame) / (phantom.vesselRadiusMm * 1e-3)
        self.report.checkClose("Median WSS magnitude at peak systole", float(np.median(result["wss_magnitude"][peakFrame][valid])), expectedPeakWss,
            rtol=0.3, unit="Pa")
        expectedTawss = 2 * 0.0035 * np.mean([abs(phantom.maxVelocity(i)) for i in range(phantom.numberOfFrames)]) / (phantom.vesselRadiusMm * 1e-3)
        self.report.checkClose("Median TAWSS", float(np.median(result["tawss"][valid])), expectedTawss, rtol=0.3, unit="Pa")
        forward = sum(max(phantom.maxVelocity(i), 0) for i in range(phantom.numberOfFrames))
        backward = sum(max(-phantom.maxVelocity(i), 0) for i in range(phantom.numberOfFrames))
        expectedOsi = 0.5 * (1 - (forward - backward) / (forward + backward))
        self.report.checkClose("Median OSI", float(np.median(result["osi"][valid])), expectedOsi, atol=0.05)
        FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
        FlowTestingUtils.reset3DView()
        self.report.screenshot("Wall shear stress magnitude at peak systole")

    @reportedTest("Relative pressure and pressure drop (slicerheart_4dflow)",
        "Relative pressure is computed by the pressure Poisson equation in the vessel of a steady Poiseuille flow (single frame at"
        " peak velocity, so there is no temporal acceleration): the pressure drop between two planes L apart along the vessel is"
        " 4 mu vmax L / R^2.")
    def test_22_Pressure(self):
        phantom = FlowPhantom(numberOfFrames=1, firstFrameTimeMs=180.0, systoleDurationMs=360.0)
        flowFieldNode, magnitudeVolumeNode, segmentationNode, segmentId = self.createLibraryFlowField(phantom, "volume")
        distanceMm = 20.0
        planeA = phantom.createMeasurementPlane(name="Plane A")
        planeB = phantom.createMeasurementPlane(name="Plane B")
        planeA.SetCenterWorld(*(phantom.centerRas - 0.5 * distanceMm * phantom.vesselAxis))
        planeB.SetCenterWorld(*(phantom.centerRas + 0.5 * distanceMm * phantom.vesselAxis))
        pressureVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Pressure")
        table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Pressure drop")
        pressure, drop = self.logic.computeRelativePressure(flowFieldNode, segmentationNode, segmentId, pressureVolume, planeA, planeB, table)
        expectedDropMmHg = 4 * 0.0035 * phantom.maxVelocity(0) * (distanceMm * 1e-3) / (phantom.vesselRadiusMm * 1e-3) ** 2 / 133.322
        self.report.checkClose("Pressure drop between the planes", float(drop[0]), expectedDropMmHg, rtol=0.3, unit="mmHg")
        self.report.checkEqual("Pressure drop table rows", len(tableToDict(table)["PressureDrop"]), 1)
        self.report.checkTrue("Pressure is finite", bool(np.all(np.isfinite(pressure))))
        FlowTestingUtils.showVolumeInSliceViews(pressureVolume, phantom.centerRas)
        self.report.screenshot("Relative pressure in steady Poiseuille flow")

    @reportedTest("Mass conservation (slicerheart_4dflow)",
        "Flow metrics tables of two planes on the same vessel are compared: the net flow volume per heart beat must be the same.")
    def test_23_MassConservation(self):
        phantom = FlowPhantom()
        flowFieldNode, magnitudeVolumeNode, segmentationNode, segmentId = self.createLibraryFlowField(phantom, "volume")
        tables = []
        for name, offset in [("Inflow", -8.0), ("Outflow", 8.0)]:
            planeNode = phantom.createMeasurementPlane(name=name)
            planeNode.SetCenterWorld(*(phantom.centerRas + offset * phantom.vesselAxis))
            table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"{name} flow")
            self.logic.computeFlowMetricsTableDiscSampling(planeNode, flowFieldNode, segmentationNode, segmentId, 0.0, table)
            tables.append(table)
        resultTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Mass conservation")
        result = self.logic.computeMassConservation([tables[0]], [tables[1]], resultTable, self.logic.cycleDurationMs(flowFieldNode))
        self.report.checkClose("Inflow - outflow difference", result["percent_error"], 0.0, atol=2.0, unit="%")
        self.report.checkTrue("Net flow volume is positive", result["in"] > 0, f"{result['in']:.2f} ml")
        self.report.checkEqual("Mass conservation table columns", sorted(tableToDict(resultTable).keys()),
            sorted(["Check", "Inflow", "Outflow", "Difference", "PercentError", "Ratio"]))

    @reportedTest("slicerheart_4dflow methods in the GUI",
        "Flow metrics method and streamlines method are selected in the GUI, hemodynamic outputs are computed by the"
        " 'Compute hemodynamics' button and mass conservation by the 'Compute mass conservation' button.")
    def test_24_LibraryGuiWorkflow(self):
        from Analyze4DFlow import FlowMetricsMethodEnum, StreamlinesMethodEnum
        phantom = FlowPhantom()
        flowFieldNode, magnitudeVolumeNode, segmentationNode, segmentId = self.createLibraryFlowField(phantom, "volume")
        planeNode = phantom.createMeasurementPlane()
        slicer.util.selectModule("Analyze4DFlow")
        widget = slicer.modules.analyze4dflow.widgetRepresentation().self()
        parameterNode = widget._parameterNode
        parameterNode.inputFlowField = flowFieldNode
        parameterNode.inputPlane = planeNode
        parameterNode.inputMaskSegmentation = segmentationNode
        parameterNode.inputMaskSegmentID = segmentId
        parameterNode.samplingDistance = 3.0
        parameterNode.speedThreshold = 0.0
        parameterNode.flowMetricsMethod = FlowMetricsMethodEnum.DiscSampling
        parameterNode.streamlinesMethod = StreamlinesMethodEnum.Pathlines
        parameterNode.outputFlowMetricsTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Flow metrics")
        parameterNode.outputFlowMetricsSummaryTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Flow metrics summary")
        parameterNode.outputStreamlinesModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Pathlines")
        slicer.app.processEvents()
        self.report.checkEqual("[GUI] Flow metrics method combobox shows the selected method",
            widget.ui.flowMetricsMethodSelector.currentText, FlowMetricsMethodEnum.DiscSampling.label())
        self.report.checkTrue("[GUI] Streamline-only options are disabled for pathlines", not widget.ui.streamlinesMaximumLengthSliderWidget.enabled)
        widget.onAnalyzeButton()
        metrics = tableToDict(parameterNode.outputFlowMetricsTable)
        expectedPeakFlow = phantom.expectedFlowRateMlPerSec(phantom.peakFrameIndex())
        self.report.checkClose("[GUI] Disc sampling peak flow rate", max(metrics["FlowRate"]), expectedPeakFlow, rtol=0.03, unit="ml/s")
        self.report.checkTrue("[GUI] Pathlines are created", parameterNode.outputStreamlinesModel.GetPolyData().GetNumberOfLines() > 0)

        parameterNode.outputVorticityVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Vorticity")
        parameterNode.outputHemodynamicsTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Hemodynamics")
        parameterNode.outputWallShearStressModel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "WSS")
        parameterNode.outputPressureVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Pressure")
        widget.onComputeHemodynamicsButton()
        self.report.checkEqual("[GUI] Hemodynamics table rows", len(tableToDict(parameterNode.outputHemodynamicsTable).get("KineticEnergy", [])), phantom.numberOfFrames)
        self.report.checkTrue("[GUI] Wall shear stress is computed", parameterNode.outputWallShearStressModel.GetPolyData() is not None
            and parameterNode.outputWallShearStressModel.GetPolyData().GetPointData().GetArray("TAWSS") is not None)
        self.report.checkTrue("[GUI] Pressure volume is created", parameterNode.outputPressureVolume.GetImageData() is not None)

        widget.ui.inflowTablesSelector.setCheckState(parameterNode.outputFlowMetricsTable, 2)
        widget.ui.outflowTablesSelector.setCheckState(parameterNode.outputFlowMetricsTable, 2)
        widget.onComputeMassConservationButton()
        massConservation = tableToDict(parameterNode.outputMassConservationTable)
        self.report.checkClose("[GUI] Mass conservation of a plane with itself", massConservation["PercentError"][0], 0.0, atol=1e-6, unit="%")
        self.report.screenshot("Analyze 4D Flow module GUI with slicerheart_4dflow outputs", kind="window")
