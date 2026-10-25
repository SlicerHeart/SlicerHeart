"""Feature tests of the Import4DFlow module.

Tests use an analytic flow phantom (generated in the scene or written as Siemens CS 4D flow-like DICOM files)
and, if available, an anonymized clinical 4D flow MRI data set (see FlowTestingUtils.REAL_DATA_ENV_VARIABLE).
Results are written into a markdown report with screenshots (see FlowTestingUtils.TestReport).

Run from the Slicer Python console:

    import slicer.testing
    slicer.testing.runUnitTest([r"<path>/Import4DFlow/Testing/Python"], "Import4DFlowFeaturesTest")
"""

import json
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
from Import4DFlow import Import4DFlowLogic, BackgroundSubtractionMethodEnum, UnwrapModeEnum, NoiseMaskMethodEnum, DivergenceFilterMethodEnum
from Import4DFlowLib import FlowLibraryBridge


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
        """Create and compute a flow field (vector volume sequence, mm/s). If storeInTransform is set then a flow field
        stored in grid transforms (legacy format, m/s; it can be read but not written by Import 4D Flow) is created from it
        and returned."""
        flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(
            volumeNodeSet["componentVolumeNodes"], volumeNodeSet["componentVolumeNodesInvertToRasDirection"],
            volumeNodeSet["magnitudeVolumeNode"])
        if unwrap:
            self.logic.temporalUnwrap(flowFieldNode, 0, noiseMagnitudeThresholdPercent)
        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, noiseMagnitudeThresholdPercent,
            backgroundSubtractionMethod, stationaryTissueSpeedThresholdVencPercent)
        if storeInTransform:
            return FlowTestingUtils.createLegacyTransformFlowField(flowFieldNode)
        return flowFieldNode

    def velocityFrames(self, flowFieldNode):
        """Velocity vectors (k, j, i, 3) of all frames of a flow field, in m/s (as the phantom), RAS. The values are read in
        the declared unit of the flow field (mm/s for vector volumes, m/s for transforms)."""
        velocity, _, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        return [frame / 1000.0 for frame in velocity]

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

    # Clinical data helpers

    def realDataDirectoryOrSkip(self):
        dataDir = FlowTestingUtils.environmentValue(FlowTestingUtils.REAL_DATA_ENV_VARIABLE)
        if not dataDir or not os.path.isdir(dataDir):
            self.skipTest(f"Anonymized 4D flow data set is not available (set {FlowTestingUtils.REAL_DATA_ENV_VARIABLE} in the environment or in .env.local)")
        return dataDir

    def loadRealDataVolumeNodeSet(self, dataDir):
        """Load the clinical data set from DICOM (the DICOM database must be open) and return the detected image set."""
        from DICOMLib import DICOMUtils
        DICOMUtils.importDicom(dataDir, slicer.dicomDatabase)
        FlowTestingUtils.loadDicomSeriesAsVolumeSequences()
        volumeNodeSets = self.logic.findVolumeNodeSets()
        self.assertEqual(len(volumeNodeSets), 1, "Number of detected 4D flow image sets")
        return list(volumeNodeSets.values())[0]

    def isSpatialVectorNrrdReadingSupported(self):
        """Returns True if this Slicer version loads spatial vector volumes from NRRD files as spatial vectors
        (vector components converted from LPS in the file to RAS). Older Slicer versions load single-frame vector
        volume NRRD files without converting the vector components. Determined by saving a small spatial vector
        volume and loading it back."""
        vector = [1.0, 2.0, 3.0]
        volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "__tmp__spatial vector")
        slicer.util.updateVolumeFromArray(volumeNode, np.tile(np.array(vector, dtype=np.float32), (2, 2, 2, 1)))
        volumeNode.SetVoxelVectorType(slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial)
        filePath = os.path.join(self.temporaryDirectory("Import4DFlowSpatialVector_"), "spatial.nrrd")
        loadedNode = None
        try:
            slicer.util.exportNode(volumeNode, filePath)
            loadedNode = slicer.util.loadVolume(filePath)
            return bool(np.allclose(slicer.util.arrayFromVolume(loadedNode), vector))
        finally:
            for node in [volumeNode, loadedNode]:
                if node is None:
                    continue
                for dependentNode in [node.GetStorageNode(), node.GetDisplayNode()]:
                    if dependentNode:
                        slicer.mrmlScene.RemoveNode(dependentNode)
                slicer.mrmlScene.RemoveNode(node)

    def removeFlowField(self, flowFieldNode):
        """Remove a flow field and its sequence from the scene (to reduce memory usage)."""
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        sequenceNode = browserNode.GetSequenceNode(flowFieldNode)
        browserNode.RemoveSynchronizedSequenceNode(sequenceNode.GetID())
        slicer.mrmlScene.RemoveNode(sequenceNode)
        slicer.mrmlScene.RemoveNode(flowFieldNode)

    @staticmethod
    def countDicomIdentifiers(scene):
        """Returns (number of DICOM attributes, number of DICOM UIDs, list of patient names) in a scene."""
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

    def findFlowFieldProxyNodes(self):
        """Returns {storage name: flow field proxy node} for all flow fields in the scene."""
        flowFieldNodes = {}
        for className, storage in [("vtkMRMLTransformNode", "grid transform"), ("vtkMRMLVectorVolumeNode", "vector volume")]:
            for node in slicer.util.getNodesByClass(className):
                if node.GetAttribute("SlicerHeart.Type") == "FlowField" and slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(node):
                    flowFieldNodes[storage] = node
        return flowFieldNodes

    # Tests

    @reportedTest("Module and GUI initialization",
        "The module and its GUI can be loaded; the Doppler color table, export format list, and"
        " storage format selector are initialized.")
    def test_01_ModuleAndWidget(self):
        self.report.checkTrue("Import4DFlow module is loaded", hasattr(slicer.modules, "import4dflow"))
        slicer.util.selectModule("Import4DFlow")
        widget = slicer.modules.import4dflow.widgetRepresentation().self()
        self.report.checkTrue("Module widget is created", widget is not None and widget.logic is not None)
        defaultParameterNode = widget.logic.getParameterNode()
        self.report.checkEqual("Background subtraction is a quadratic fit by default",
            defaultParameterNode.backgroundSubtractionMethod, BackgroundSubtractionMethodEnum.QuadraticFit)

        colorNode = Import4DFlowLogic.dopplerColdToHotColorTableNode()
        self.report.checkTrue("Doppler color table is available", colorNode is not None)
        self.report.checkTrue("Doppler color table has colors", colorNode.GetNumberOfColors() > 0, colorNode.GetNumberOfColors(), "> 0")
        self.report.checkEqual("Doppler color table category", colorNode.GetAttribute("Category"), "Flow")
        self.report.checkTrue("Same Doppler color table node is returned on repeated calls",
            Import4DFlowLogic.dopplerColdToHotColorTableNode() == colorNode)

        comboBox = widget.ui.exportFormatComboBox
        formats = [comboBox.itemData(i) for i in range(comboBox.count)]
        self.report.checkEqual("Export formats in GUI", formats, Import4DFlowLogic.EXPORT_FORMATS)
        self.report.checkTrue("'Remove input flow image after conversion' is checked by default", widget.ui.removeInputImageCheckBox.checked)
        self.report.checkTrue("There is no option to store the flow field in transforms (legacy format, read only)",
            not hasattr(widget.ui, "storeInTransformCheckBox"))
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
            flowFieldNode = self.createFlowField(volumeNodeSet, storeInTransform=False)
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
        " by trigger times, and creates the flow field node (vector volume, mm/s) with all references.")
    def test_04_CreateFlowField(self):
        phantom = FlowPhantom()
        for storeInTransform in [False]:  # flow fields are not written in transforms (legacy format)
            slicer.mrmlScene.Clear()
            storage = self.storageName(storeInTransform)
            volumeNodeSet = phantom.createComponentImagesInScene()
            flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(
                volumeNodeSet["componentVolumeNodes"], volumeNodeSet["componentVolumeNodesInvertToRasDirection"],
                volumeNodeSet["magnitudeVolumeNode"])
            expectedClass = "vtkMRMLVectorVolumeNode"
            self.report.checkTrue(f"[{storage}] Flow field node type is {expectedClass}", flowFieldNode.IsA(expectedClass), flowFieldNode.GetClassName(), expectedClass)
            self.report.checkEqual(f"[{storage}] SlicerHeart.Type attribute", flowFieldNode.GetAttribute("SlicerHeart.Type"), "FlowField")
            self.report.checkTrue(f"[{storage}] Magnitude volume reference", flowFieldNode.GetNodeReference("magnitudeVolume") == volumeNodeSet["magnitudeVolumeNode"])
            inputFlowFieldNode = flowFieldNode.GetNodeReference("inputFlowField")
            self.report.checkTrue(f"[{storage}] Output flow field references the input flow field (velocity as acquired)",
                inputFlowFieldNode is not None and FlowLibraryBridge.isRawFlowField(inputFlowFieldNode))
            if inputFlowFieldNode is not None:
                self.report.checkEqual(f"[{storage}] Input flow field stores the direction codes", FlowLibraryBridge.directionCodes(inputFlowFieldNode),
                    [code for code, _ in FlowTestingUtils.DIRECTION_CONFIGURATION_AXIAL])
                self.report.checkEqual(f"[{storage}] Input flow field stores the velocity encoding (mm/s)",
                    FlowLibraryBridge.vencEncodedMmPerSec(inputFlowFieldNode).tolist(), [1500.0] * 3)  # default venc of the phantom: 150 cm/s
                self.report.checkTrue(f"[{storage}] Input flow field is a vector volume", inputFlowFieldNode.IsA("vtkMRMLVectorVolumeNode"))
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
        " in every voxel and frame. The phantom volume is oblique (rotated by 20 degrees). The flow field is stored in vector"
        " volumes (mm/s); a flow field stored in grid transforms (legacy format, m/s) is created from it to check that it is"
        " read the same way: the grid transform must displace each point by the velocity vector (in the 'to parent'"
        " direction, which is used for visualization and analysis).")
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
            self.report.checkEqual(f"[{storage}] Velocity unit attribute", sequenceNode.GetAttribute("SlicerHeart.velocityUnit"),
                "m/s" if storeInTransform else "mm/s")
            self.report.checkEqual(f"[{storage}] Velocity encoding attribute", sequenceNode.GetAttribute("SlicerHeart.vencCmPerSec"), ",".join([str(vencCmPerSec)] * 3))
            frameNode = sequenceNode.GetNthDataNode(peakFrame)
            self.report.checkEqual(f"[{storage}] Frame node SlicerHeart.Type attribute", frameNode.GetAttribute("SlicerHeart.Type"), "FlowField")
            if not storeInTransform:
                if FlowTestingUtils.voxelValueUnitsKeptInSequence():
                    units = frameNode.GetVoxelValueUnits()
                    quantity = frameNode.GetVoxelValueQuantity()
                    self.report.checkEqual(f"[{storage}] Frame voxel value units", units.GetCodeValue() if units else None, "mm/s")
                    self.report.checkEqual(f"[{storage}] Frame voxel value quantity", quantity.GetCodeMeaning() if quantity else None, "velocity")
                else:
                    self.report.text(f"[{storage}] Frame voxel value units are not checked: this Slicer version does not keep"
                                     " voxel value units of volumes stored in sequences.")

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
            flowFieldNode = self.createFlowField(volumeNodeSet, False, noiseMagnitudeThresholdPercent=thresholdPercent)
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
                flowFieldNode = self.createFlowField(volumeNodeSet, False, backgroundSubtractionMethod=method)
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
        flowFieldNode = self.createFlowField(volumeNodeSet, False, unwrap=False)
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
        componentVolumeNode = self.logic.getRawComponentVolume(flowFieldNode, 2)
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

        self.logic.laplacianUnwrap(flowFieldNode)
        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
        self.checkVelocityFrames("Laplacian unwrapping (slicerheart_4dflow) after reset", self.velocityFrames(flowFieldNode), expectedFrames,
            velocityQuantizationMPerSec(vencCmPerSec))
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
        flowFieldNode = self.createFlowField(volumeNodeSet, False, unwrap=True)  # no wraps in the phantom
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
            # Color map is in the unit of the stored velocity values: m/s for transforms, mm/s for vector volumes
            self.report.checkClose(f"[{storage}] Color map range maximum (velocity encoding)", colorRange[1],
                vencCmPerSec / 100.0 if storeInTransform else vencCmPerSec * 10.0, atol=1e-6, unit="m/s" if storeInTransform else "mm/s")
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
            spatialVectorNrrdReadingSupported = self.isSpatialVectorNrrdReadingSupported()
            rasToLps = np.array([-1.0, -1.0, 1.0])
            # Files store the velocity in the unit of the flow field: m/s for transforms (legacy format), mm/s for vector volumes
            fileUnit, fileUnitToMPerSec = ("m/s", 1.0) if storeInTransform else ("mm/s", 0.001)
            for frameIndex, fileName in enumerate(files):
                filePath = os.path.join(exportDir, fileName)
                data, header = nrrd.read(filePath)
                self.report.checkEqual(f"[{storage}] {fileName}: sample units", header.get("sample units"), fileUnit)
                if storeInTransform:
                    self.report.checkEqual(f"[{storage}] {fileName}: transform direction", header.get("TransformDirection"), "to parent")
                self.report.checkTrue(f"[{storage}] {fileName}: no intent_code field", "intent_code" not in header)
                # Vectors in NRRD files are stored in LPS coordinate system (file axes: component, I, J, K)
                fileVelocityLps = np.asarray(data).transpose(3, 2, 1, 0)
                fileErrors.append(float(np.abs(fileVelocityLps * fileUnitToMPerSec - expectedFrames[frameIndex] * rasToLps).max()))
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
                loadedErrors.append(float(np.abs(velocity * fileUnitToMPerSec - expectedFrames[frameIndex]).max()))
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
            fileUnit, fileUnitToMPerSec = ("m/s", 1.0) if storeInTransform else ("mm/s", 0.001)
            unitsField = header.split("units:")[1].split("\n")[0].strip() if "units:" in header else None
            componentAxisUnit = unitsField.split('"')[1] if unitsField and unitsField.count('"') >= 2 else ""
            if componentAxisUnit:
                self.report.checkEqual(f"[{storage}] Velocity unit in the units field of the component axis", componentAxisUnit, fileUnit)
            else:
                # Slicer versions before 5.13 do not write the voxel value units of volume sequences into the file
                self.report.text(f"[{storage}] Slicer limitation: the velocity unit is not written in the units field of the component"
                    f" axis (units: {unitsField}). The file is in {fileUnit}; vector volumes without unit are read as mm/s.")
            loadedSequenceNode = slicer.util.loadNodeFromFile(exportedFile, "SequenceFile")
            self.report.checkEqual(f"[{storage}] Number of frames loaded back", loadedSequenceNode.GetNumberOfDataNodes(), phantom.numberOfFrames)
            indexValues = [float(loadedSequenceNode.GetNthIndexValue(i)) for i in range(loadedSequenceNode.GetNumberOfDataNodes())]
            self.report.checkEqual(f"[{storage}] Frame times loaded back", indexValues, phantom.frameTimesMs)
            maxErrors = []
            geometryErrors = []
            phantomIjkToRas = phantom.ijkToRasMatrix()
            for frameIndex in range(loadedSequenceNode.GetNumberOfDataNodes()):
                frameNode = loadedSequenceNode.GetNthDataNode(frameIndex)
                maxErrors.append(float(np.abs(slicer.util.arrayFromVolume(frameNode) * fileUnitToMPerSec - expectedFrames[frameIndex]).max()))
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
            self.createFlowField(volumeNodeSet, False)
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        countIdentifiers = self.countDicomIdentifiers

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
        flowFieldNodes = [n for n in slicer.util.getNodesByClass("vtkMRMLVectorVolumeNode") if n.GetAttribute("SlicerHeart.Type") == "FlowField"]
        self.report.checkEqual("Flow field in anonymized scene", len(flowFieldNodes), 1)
        self.report.checkTrue("Flow field magnitude volume reference in anonymized scene",
            bool(flowFieldNodes) and flowFieldNodes[0].GetNodeReference("magnitudeVolume") is not None)

    @reportedTest("Export format validation", "Unknown export formats are rejected.")
    def test_14_ExportInvalidFormat(self):
        with self.assertRaises(ValueError):
            self.logic.exportDisplacementFieldToFiles(None, self.temporaryDirectory("Import4DFlowExport_"), "INVALID")
        self.report.checkTrue("ValueError is raised for unknown export format", True)

    @reportedTest("Scene save and reload",
        "Flow fields (vector volume with phase wrap segmentations and visualization, and a flow field stored in grid"
        " transforms, the legacy format) are saved in a scene (MRB), the scene is reloaded, and the flow field, references,"
        " and velocity values must be the same. The vector volume flow field can be recomputed after reload; the legacy"
        " flow field is read only.")
    def test_15_SceneSaveReload(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom(numberOfFrames=4)
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
        volumeFlowField = self.createFlowField(volumeNodeSet, False, unwrap=True)
        transformFlowField = FlowTestingUtils.createLegacyTransformFlowField(volumeFlowField)
        self.logic.setFlowFieldVisualizationToDefault(transformFlowField)
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
            self.report.checkTrue(f"[{storage}] Input flow field reference is restored",
                flowFieldNode.GetNodeReference("inputFlowField") is not None and FlowLibraryBridge.isRawFlowField(flowFieldNode.GetNodeReference("inputFlowField")))
            self.checkVelocityFrames(f"[{storage}] Velocity after reload", self.velocityFrames(flowFieldNode), expectedFrames,
                velocityQuantizationMPerSec(vencCmPerSec))
            if storage == "grid transform":
                displayNode = self.logic.getFlowFieldDisplayNode(flowFieldNode)
                self.report.checkTrue(f"[{storage}] Glyph display node is restored", displayNode is not None)
                if displayNode:
                    colorNode = displayNode.GetColorNode()
                    self.report.checkTrue(f"[{storage}] Speed color map is restored", colorNode is not None and colorNode.GetAttribute("Category") == "Flow")
                # Flow fields stored in transforms (legacy format) are read only
                try:
                    self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
                    error = None
                except ValueError as e:
                    error = str(e)
                self.report.checkTrue(f"[{storage}] Legacy flow field is not overwritten by recomputation (read only)", error is not None,
                    error or "no error", "ValueError")
            else:
                self.report.checkTrue(f"[{storage}] Phase wrap segmentations are restored",
                    all(flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", c) is not None for c in range(3)))
                # Flow field can be updated after reload
                self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
                self.checkVelocityFrames(f"[{storage}] Velocity recomputed after reload", self.velocityFrames(flowFieldNode), expectedFrames,
                    velocityQuantizationMPerSec(vencCmPerSec))

    @reportedTest("Module GUI workflow",
        "The complete workflow is performed using the module GUI: find images, create flow field (twice: keeping and"
        " removing the component images, the default), compute phase unwrapping"
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
            # This test checks the flow field computed with temporal unwrapping (Laplacian 4D is the default)
            # and without background subtraction (the phantom has no background error; a quadratic fit is the default)
            parameterNode.unwrapMode = UnwrapModeEnum.TemporalUnwrap
            parameterNode.backgroundSubtractionMethod = BackgroundSubtractionMethodEnum.NoSubtraction

            # Component images are kept, as they are converted again below
            parameterNode.removeInputImageAfterConversion = False
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

            # Component images are removed after conversion (default)
            parameterNode.removeInputImageAfterConversion = True
            volumeNodeSet = widget._volumeNodesSets[parameterNode.inputVolumeNodeSet]
            componentVolumeIds = [node.GetID() for node in volumeNodeSet["componentVolumeNodes"]]
            widget.onConvertButton()
            flowFieldNode = parameterNode.outputFlowField
            self.report.checkTrue("[GUI] Component images are removed after conversion",
                all(slicer.mrmlScene.GetNodeByID(nodeId) is None for nodeId in componentVolumeIds))
            self.report.checkTrue("[GUI] Magnitude images are kept after conversion", slicer.mrmlScene.IsNodePresent(volumeNodeSet["magnitudeVolumeNode"]) > 0)
            self.report.checkTrue("[GUI] Input flow field is selected", parameterNode.inputFlowField is not None
                and flowFieldNode is not None and flowFieldNode.GetNodeReference("inputFlowField") is parameterNode.inputFlowField)
            self.report.checkTrue("[GUI] A new flow field is created as vector volume", flowFieldNode is not None
                and flowFieldNode.IsA("vtkMRMLVectorVolumeNode") and flowFieldNode is not volumeFlowField)
            self.checkVelocityFrames("[GUI, second conversion] Velocity", self.velocityFrames(flowFieldNode), expectedFrames,
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
            if displayNode:
                visibility = displayNode.GetVisibility()
                widget.onShowFlowFieldButton()
                self.report.checkEqual("'Show flow field' button toggles glyph visibility (off)", bool(displayNode.GetVisibility()), not visibility)
                widget.onShowFlowFieldButton()
                self.report.checkEqual("'Show flow field' button toggles glyph visibility (on)", bool(displayNode.GetVisibility()), bool(visibility))
            else:
                # Vector volume flow fields are shown as glyphs only if the vector field display node is available
                self.report.checkTrue("No glyph display node in this Slicer version (vector field display node is not available)",
                    not FlowTestingUtils.isVectorFieldDisplayAvailable())
                widget.onShowFlowFieldButton()  # must not fail
            widget.onShowComponentVolumeButton(2)
            redComposite = slicer.app.layoutManager().sliceWidget("Red").mrmlSliceCompositeNode()
            self.report.checkEqual("Component button shows the velocity component of the input flow field",
                redComposite.GetBackgroundVolumeID(), self.logic.getRawComponentVolume(flowFieldNode, 2).GetID())
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
            widget.onComputePhaseUnwrappingButton()
            widget.onRecomputeFlowFieldButton()
            self.checkVelocityFrames("[GUI] Laplacian unwrapping (slicerheart_4dflow), then recompute", self.velocityFrames(flowFieldNode), expectedFrames,
                velocityQuantizationMPerSec(vencCmPerSec))
            parameterNode.unwrapMode = UnwrapModeEnum.TemporalUnwrap

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
                                               (Import4DFlowLogic.EXPORT_FORMAT_NRRD_STACK, "velocity_00.nrrd"),
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
        " with temporal phase unwrapping. The two storage formats must give identical velocities, values must be physiologically"
        " plausible in voxels with strong signal (below 7 m/s), and the 5D NRRD export must reproduce the flow field.")
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
                magnitudeVolumeNode)
            timings.append([f"Create flow field ({storage})", time.time() - startTime])
            startTime = time.time()
            self.logic.temporalUnwrap(flowFieldNode, 0, 5.0)
            timings.append([f"Temporal unwrapping ({storage})", time.time() - startTime])
            startTime = time.time()
            self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
            timings.append([f"Compute flow field ({storage})", time.time() - startTime])
            if storeInTransform:
                # Flow field in the legacy format (read only), created from the computed flow field
                flowFieldNode = FlowTestingUtils.createLegacyTransformFlowField(flowFieldNode)
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
        # Velocity is only measurable where the MR signal is strong (blood, tissue). In low-signal voxels the phase is
        # random noise, which temporal unwrapping may interpret as phase wraps, therefore plausibility of the velocity
        # values is checked in high-signal voxels.
        magnitudeSequenceNode = self.logic._getSequenceFromProxyNode(magnitudeVolumeNode)
        highSignalMaxSpeeds = []
        for frameIndex, speed in enumerate(speeds):
            magnitude = slicer.util.arrayFromVolume(magnitudeSequenceNode.GetNthDataNode(frameIndex))
            highSignal = magnitude >= 0.3 * np.percentile(magnitude, 99)
            highSignalMaxSpeeds.append(float(speed[highSignal].max()) if np.any(highSignal) else 0.0)
        # Highest physiological blood velocities (jets of severe stenoses) are about 5-6 m/s
        self.report.checkRange("Maximum speed in high-signal voxels (all frames, after unwrapping)", max(highSignalMaxSpeeds),
            0.2, 7.0, "m/s")
        self.report.text(f"Maximum speed in all voxels (including low-signal noise): {maxSpeed:.2f} m/s.")
        # Phase wrap segmentations belong to the vector volume flow field (the legacy transform flow field is only read)
        segmentationNodes = [flowFieldNodes[False].GetNthNodeReference("phaseWrapSegmentation", c) for c in range(3)]
        self.report.checkTrue("Phase wrap segmentations are created", all(segmentationNodes))
        rows = [[i, f"{indexValues[i]:.1f}", p99Speeds[i], highSignalMaxSpeeds[i], float(speeds[i].max())] for i in range(len(speeds))]
        self.report.table(["Frame", "Time (ms)", "99th percentile speed (m/s)", "Max. speed in high-signal voxels (m/s)",
            "Max. speed in all voxels (m/s)"], rows, "Speed statistics per frame")

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

    @reportedTest("Clinical data set: processing options",
        "Processing options are tested on the clinical data set: noise masking with different magnitude thresholds, background"
        " phase correction (linear and quadratic fit), and manual phase wrap correction (voxels painted into the phase wrap"
        " segmentation).")
    def test_18_RealDataProcessingOptions(self):
        from DICOMLib import DICOMUtils
        dataDir = self.realDataDirectoryOrSkip()
        workDir = self.temporaryDirectory("Import4DFlowRealDataOptions_")
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(workDir, "db")):
            volumeNodeSet = self.loadRealDataVolumeNodeSet(dataDir)
        magnitudeVolumeNode = volumeNodeSet["magnitudeVolumeNode"]
        magnitudeSequenceNode = self.logic._getSequenceFromProxyNode(magnitudeVolumeNode)
        numberOfFrames = magnitudeSequenceNode.GetNumberOfDataNodes()
        magnitudeFrames = [slicer.util.arrayFromVolume(magnitudeSequenceNode.GetNthDataNode(i)) for i in range(numberOfFrames)]
        vencs = [float(self.logic._getSequenceAttribute(n, "SlicerHeart.vencCmPerSec")) for n in volumeNodeSet["componentVolumeNodes"]]

        # Noise masking
        rows = []
        framesByThreshold = {}
        nonzeroVoxels = {}
        for thresholdPercent in [2.0, 5.0, 15.0]:
            flowFieldNode = self.createFlowField(volumeNodeSet, False, noiseMagnitudeThresholdPercent=thresholdPercent)
            frames = self.velocityFrames(flowFieldNode)
            self.removeFlowField(flowFieldNode)
            framesByThreshold[thresholdPercent] = frames
            magnitudeThreshold = thresholdPercent / 100 * self.logic.magnitudeVolumeRange
            maxSpeedBelow = max(float(np.abs(f[m < magnitudeThreshold]).max()) if np.any(m < magnitudeThreshold) else 0.0
                for f, m in zip(frames, magnitudeFrames))
            self.report.checkClose(f"[noise threshold {thresholdPercent:g}%] Max. speed where magnitude is below threshold", maxSpeedBelow, 0.0, atol=1e-6, unit="m/s")
            nonzeroVoxels[thresholdPercent] = sum(int(np.count_nonzero(np.any(f != 0, axis=-1))) for f in frames)
            rows.append([f"{thresholdPercent:g}%", f"{magnitudeThreshold:.1f}", nonzeroVoxels[thresholdPercent]])
        self.report.table(["Noise threshold", "Magnitude threshold", "Voxels with non-zero velocity (all frames)"], rows)
        self.report.checkTrue("Higher noise threshold masks more voxels", nonzeroVoxels[2.0] >= nonzeroVoxels[5.0] >= nonzeroVoxels[15.0],
            [nonzeroVoxels[t] for t in [2.0, 5.0, 15.0]], "decreasing")
        highThreshold = 15.0 / 100 * self.logic.magnitudeVolumeRange
        difference = max(float(np.abs(a - b)[m >= highThreshold].max()) for a, b, m in zip(framesByThreshold[2.0], framesByThreshold[15.0], magnitudeFrames))
        self.report.checkClose("Velocity above all noise thresholds does not depend on the threshold (max. difference)", difference, 0.0, atol=1e-6, unit="m/s")
        baseFrames = framesByThreshold[5.0]
        del framesByThreshold

        # Background phase correction. Stationary tissue: strong signal and low speed in all frames.
        highSignal = np.all([m >= 0.3 * np.percentile(m, 99) for m in magnitudeFrames], axis=0)
        maxSpeed = np.max([np.linalg.norm(f, axis=-1) for f in baseFrames], axis=0)
        meanSpeed = np.mean([np.linalg.norm(f, axis=-1) for f in baseFrames], axis=0)
        stationary = np.logical_and(highSignal, maxSpeed < 0.1)
        moving = np.logical_and(highSignal, meanSpeed > 0.3)
        self.report.text(f"Stationary tissue (strong signal, speed below 0.1 m/s in all frames): {int(np.count_nonzero(stationary))} voxels;"
            f" moving blood (strong signal, mean speed above 0.3 m/s): {int(np.count_nonzero(moving))} voxels.")

        def stationaryBias(frames):
            """Magnitude of the mean velocity vector of stationary tissue (averaged over all frames)."""
            return float(np.linalg.norm(np.mean([f[stationary].mean(axis=0) for f in frames], axis=0)))

        biasBefore = stationaryBias(baseFrames)
        rows = [["no subtraction", biasBefore, 0.0]]
        for method in [BackgroundSubtractionMethodEnum.LinearFit, BackgroundSubtractionMethodEnum.QuadraticFit]:
            flowFieldNode = self.createFlowField(volumeNodeSet, False, backgroundSubtractionMethod=method)
            frames = self.velocityFrames(flowFieldNode)
            self.removeFlowField(flowFieldNode)
            biasAfter = stationaryBias(frames)
            vesselChange = float(np.median([np.linalg.norm(f - b, axis=-1)[moving] for f, b in zip(frames, baseFrames)]))
            rows.append([method.label(), biasAfter, vesselChange])
            self.report.checkTrue(f"[{method.label()}] Background velocity bias in stationary tissue is not increased",
                biasAfter <= max(biasBefore, 0.005), f"{biasAfter:.4f} m/s", f"<= {max(biasBefore, 0.005):.4f} m/s")
            self.report.checkRange(f"[{method.label()}] Median velocity change in moving blood (background correction is a small offset)",
                vesselChange, 0.0, 0.05, "m/s")
        self.report.table(["Background subtraction", "Mean velocity bias in stationary tissue (m/s)", "Median velocity change in moving blood (m/s)"], rows)

        # Manual phase wrap correction
        flowFieldNode = self.createFlowField(volumeNodeSet, False, unwrap=True)
        before = self.velocityFrames(flowFieldNode)
        frameIndex = numberOfFrames // 4
        component = 0
        FlowTestingUtils.selectSequenceItem(flowFieldNode, frameIndex)
        segmentationNode = flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", component)
        segmentation = segmentationNode.GetSegmentation()
        alreadyWrapped = np.zeros(magnitudeFrames[frameIndex].shape, dtype=bool)
        for segmentIndex in range(segmentation.GetNumberOfSegments()):
            segmentId = segmentation.GetNthSegmentID(segmentIndex)
            alreadyWrapped |= slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId, magnitudeVolumeNode) > 0
        candidates = np.logical_and(magnitudeFrames[frameIndex] >= 0.3 * np.percentile(magnitudeFrames[frameIndex], 99), np.logical_not(alreadyWrapped))
        marked = np.zeros(candidates.shape, dtype=np.uint8)
        marked[tuple(np.argwhere(candidates)[:500].T)] = 1
        if not segmentation.GetSegment("Wrap-Pos-1x"):
            segmentation.AddEmptySegment("Wrap-Pos-1x")
        existingPositiveWraps = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, "Wrap-Pos-1x", magnitudeVolumeNode) > 0
        slicer.util.updateSegmentBinaryLabelmapFromArray(np.logical_or(existingPositiveWraps, marked > 0).astype(np.uint8),
            segmentationNode, "Wrap-Pos-1x", magnitudeVolumeNode)
        browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
        slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(browserNode, segmentationNode)
        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
        after = self.velocityFrames(flowFieldNode)
        invert = volumeNodeSet["componentVolumeNodesInvertToRasDirection"][component]
        expectedShift = 2 * vencs[component] / 100.0 * (-1.0 if invert else 1.0)
        shift = (after[frameIndex][..., component] - before[frameIndex][..., component])[marked > 0]
        self.report.text(f"{int(np.count_nonzero(marked))} voxels of component {component} in frame {frameIndex} are marked as positive 1x wrap.")
        self.report.checkClose("Velocity shift in voxels marked as positive wrap (mean)", float(shift.mean()), expectedShift, atol=1e-4, unit="m/s")
        self.report.checkClose("Velocity shift in voxels marked as positive wrap (max. deviation)", float(np.abs(shift - expectedShift).max()), 0.0, atol=1e-4, unit="m/s")
        unmarkedDifference = 0.0
        for index, (a, b) in enumerate(zip(after, before)):
            difference = np.abs(a - b)
            if index == frameIndex:
                difference[marked > 0, component] = 0
            unmarkedDifference = max(unmarkedDifference, float(difference.max()))
        self.report.checkClose("Velocity change in all other voxels, components, and frames", unmarkedDifference, 0.0, atol=1e-6, unit="m/s")

    @reportedTest("Clinical data set: export and scene persistence",
        "Flow fields of the clinical data set (both storage formats, with temporal unwrapping) are exported to NRRD stack and"
        " anonymized scene, and saved in a scene file. Exported files and reloaded scenes must contain the same velocities;"
        " the anonymized scene must not contain DICOM identifiers.")
    def test_19_RealDataExportAndScene(self):
        from DICOMLib import DICOMUtils
        import nrrd
        dataDir = self.realDataDirectoryOrSkip()
        workDir = self.temporaryDirectory("Import4DFlowRealDataExport_")
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(workDir, "db")):
            volumeNodeSet = self.loadRealDataVolumeNodeSet(dataDir)
        flowFieldNodes = {"grid transform": self.createFlowField(volumeNodeSet, True, unwrap=True),
                          "vector volume": self.createFlowField(volumeNodeSet, False, unwrap=True)}
        frames = {storage: self.velocityFrames(node) for storage, node in flowFieldNodes.items()}
        numberOfFrames = len(frames["grid transform"])
        timings = []

        # Anonymized scene (exported first, while the scene still contains the DICOM identifiers)
        originalCounts = self.countDicomIdentifiers(slicer.mrmlScene)
        self.report.checkTrue("Scene contains DICOM attributes and UIDs before anonymization", originalCounts[0] > 0 and originalCounts[1] > 0,
            originalCounts[:2], "> 0")
        anonymizedDir = os.path.join(workDir, "anonymized")
        os.makedirs(anonymizedDir)
        startTime = time.time()
        self.logic.exportDisplacementFieldToFiles(None, anonymizedDir, Import4DFlowLogic.EXPORT_FORMAT_ANONYMIZED_SCENE)
        timings.append(["Export anonymized scene", time.time() - startTime])
        anonymizedFiles = [f for f in os.listdir(anonymizedDir) if f.endswith(".mrb")]
        self.report.checkEqual("Anonymized scene files", len(anonymizedFiles), 1)

        # NRRD stack
        spatialVectorNrrdReadingSupported = self.isSpatialVectorNrrdReadingSupported()
        rasToLps = np.array([-1.0, -1.0, 1.0])
        for storage, flowFieldNode in flowFieldNodes.items():
            exportDir = os.path.join(workDir, "nrrd-" + storage.replace(" ", "-"))
            os.makedirs(exportDir)
            startTime = time.time()
            self.logic.exportDisplacementFieldToFiles(flowFieldNode, exportDir, Import4DFlowLogic.EXPORT_FORMAT_NRRD_STACK)
            timings.append([f"Export NRRD stack ({storage})", time.time() - startTime])
            files = sorted(f for f in os.listdir(exportDir) if f.endswith(".nrrd"))
            self.report.checkEqual(f"[NRRD stack, {storage}] Number of exported files", len(files), numberOfFrames)
            fileErrors = []
            loadedErrors = []
            for frameIndex, fileName in enumerate(files):
                filePath = os.path.join(exportDir, fileName)
                data, header = nrrd.read(filePath)
                # Files store the velocity in the unit of the flow field: m/s for transforms (legacy format), mm/s for vector volumes
                fileUnitToMPerSec = 1.0 if storage == "grid transform" else 0.001
                fileErrors.append(float(np.abs(np.asarray(data).transpose(3, 2, 1, 0) * fileUnitToMPerSec - frames[storage][frameIndex] * rasToLps).max()))
                if storage == "grid transform":
                    loadedNode = slicer.util.loadTransform(filePath)
                    velocity = slicer.util.arrayFromGridTransform(loadedNode)
                else:
                    loadedNode = slicer.util.loadVolume(filePath)
                    velocity = slicer.util.arrayFromVolume(loadedNode)
                    if not spatialVectorNrrdReadingSupported:
                        velocity = velocity * rasToLps  # this Slicer version does not convert LPS vectors to RAS when reading NRRD
                loadedErrors.append(float(np.abs(velocity * fileUnitToMPerSec - frames[storage][frameIndex]).max()))
                slicer.mrmlScene.RemoveNode(loadedNode)
            self.report.checkClose(f"[NRRD stack, {storage}] Max. velocity difference in files (LPS vectors)", max(fileErrors), 0.0, atol=1e-5, unit="m/s")
            self.report.checkClose(f"[NRRD stack, {storage}] Max. velocity difference in files loaded back into Slicer", max(loadedErrors), 0.0, atol=1e-5, unit="m/s")

        # Scene save and reload
        sceneFile = os.path.join(workDir, "scene", "FlowScene.mrb")
        os.makedirs(os.path.dirname(sceneFile))
        startTime = time.time()
        self.report.checkTrue("Scene is saved", slicer.util.saveScene(sceneFile))
        timings.append(["Save scene", time.time() - startTime])
        slicer.mrmlScene.Clear()
        startTime = time.time()
        slicer.util.loadScene(sceneFile)
        timings.append(["Load scene", time.time() - startTime])
        reloadedFlowFieldNodes = self.findFlowFieldProxyNodes()
        for storage in flowFieldNodes:
            self.report.checkTrue(f"[scene reload, {storage}] Flow field is found", storage in reloadedFlowFieldNodes)
            if storage not in reloadedFlowFieldNodes:
                continue
            reloadedFrames = self.velocityFrames(reloadedFlowFieldNodes[storage])
            self.report.checkEqual(f"[scene reload, {storage}] Number of frames", len(reloadedFrames), numberOfFrames)
            self.report.checkClose(f"[scene reload, {storage}] Max. velocity difference",
                max(float(np.abs(a - b).max()) for a, b in zip(reloadedFrames, frames[storage])), 0.0, atol=1e-6, unit="m/s")
            if storage == "vector volume":  # flow fields in the legacy format (transforms) are not processed
                self.report.checkTrue(f"[scene reload, {storage}] Phase wrap segmentations are restored",
                    all(reloadedFlowFieldNodes[storage].GetNthNodeReference("phaseWrapSegmentation", c) is not None for c in range(3)))

        # Anonymized scene content
        slicer.mrmlScene.Clear()
        if anonymizedFiles:
            slicer.util.loadScene(os.path.join(anonymizedDir, anonymizedFiles[0]))
            dicomAttributes, dicomUids, patientNames = self.countDicomIdentifiers(slicer.mrmlScene)
            self.report.checkEqual("[anonymized scene] DICOM attributes", dicomAttributes, 0)
            self.report.checkEqual("[anonymized scene] DICOM UIDs", dicomUids, 0)
            self.report.checkTrue("[anonymized scene] Patient names", all(name == "Anonymous" for name in patientNames), patientNames, "Anonymous")
            anonymizedFlowFieldNodes = self.findFlowFieldProxyNodes()
            for storage in flowFieldNodes:
                self.report.checkTrue(f"[anonymized scene, {storage}] Flow field is found", storage in anonymizedFlowFieldNodes)
                if storage in anonymizedFlowFieldNodes:
                    self.report.checkClose(f"[anonymized scene, {storage}] Max. velocity difference",
                        max(float(np.abs(a - b).max()) for a, b in zip(self.velocityFrames(anonymizedFlowFieldNodes[storage]), frames[storage])),
                        0.0, atol=1e-6, unit="m/s")
        self.report.table(["Step", "Duration (s)"], [[name, f"{duration:.1f}"] for name, duration in timings], "Computation times")

    @reportedTest("Clinical data set: module GUI workflow",
        "The clinical data set is processed using the module GUI: find images, create flow field (twice; a flow field in the"
        " legacy transform format is created from it, which must contain the same velocities),"
        " phase unwrapping modes, recompute, show flow field / magnitude / component images, and export to 5D NRRD file.")
    def test_20_RealDataGuiWorkflow(self):
        from DICOMLib import DICOMUtils
        dataDir = self.realDataDirectoryOrSkip()
        workDir = self.temporaryDirectory("Import4DFlowRealDataGui_")
        with DICOMUtils.TemporaryDICOMDatabase(os.path.join(workDir, "db")):
            DICOMUtils.importDicom(dataDir, slicer.dicomDatabase)
            FlowTestingUtils.loadDicomSeriesAsVolumeSequences()
            slicer.util.selectModule("Import4DFlow")
            widget = slicer.modules.import4dflow.widgetRepresentation().self()
            widget.onInspectButton()
            self.report.checkEqual("[GUI] Image sets listed in GUI", widget.ui.inputVolumeNodeSetSelector.count, 1)
            self.report.checkTrue("[GUI] Convert button is enabled", widget.ui.convertButton.enabled)
            parameterNode = widget._parameterNode
            # This test compares unwrapping methods with temporal unwrapping (Laplacian 4D is the default),
            # without background subtraction (a quadratic fit is the default)
            parameterNode.unwrapMode = UnwrapModeEnum.TemporalUnwrap
            parameterNode.backgroundSubtractionMethod = BackgroundSubtractionMethodEnum.NoSubtraction

            convertedFlowFieldNodes = []
            for conversion in range(2):
                # The same images are converted twice: they are removed after the last conversion
                parameterNode.removeInputImageAfterConversion = conversion == 1
                try:
                    widget.onConvertButton()
                    error = None
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
                self.report.checkTrue(f"[GUI, conversion {conversion + 1}] 'Create flow field' completes without error", error is None,
                    error or "no error", "no error")
                flowFieldNode = parameterNode.outputFlowField
                self.report.checkTrue(f"[GUI, conversion {conversion + 1}] Flow field is created as vector volume",
                    flowFieldNode is not None and flowFieldNode.IsA("vtkMRMLVectorVolumeNode"))
                convertedFlowFieldNodes.append(flowFieldNode)
        flowFieldNodes = {"vector volume": convertedFlowFieldNodes[1],
                          "grid transform": FlowTestingUtils.createLegacyTransformFlowField(convertedFlowFieldNodes[1])}
        frames = {storage: self.velocityFrames(node) for storage, node in flowFieldNodes.items()}
        self.report.checkClose("[GUI] Repeated conversion gives the same velocities (max. difference)",
            max(float(np.abs(a - b).max()) for a, b in zip(self.velocityFrames(convertedFlowFieldNodes[0]), frames["vector volume"])),
            0.0, atol=1e-5, unit="m/s")
        self.report.checkClose("[GUI] Legacy transform flow field is read with the same velocities (max. difference)",
            max(float(np.abs(a - b).max()) for a, b in zip(frames["grid transform"], frames["vector volume"])), 0.0, atol=1e-5, unit="m/s")
        flowFieldNode = flowFieldNodes["vector volume"]
        temporalFrames = frames["vector volume"]

        # Show buttons
        displayNode = self.logic.getFlowFieldDisplayNode(flowFieldNode)
        if displayNode:  # vector volume flow fields are displayed as glyphs if the vector field display node is available
            visibility = bool(displayNode.GetVisibility())
            widget.onShowFlowFieldButton()
            self.report.checkEqual("[GUI] 'Show flow field' button toggles glyph visibility", bool(displayNode.GetVisibility()), not visibility)
            widget.onShowFlowFieldButton()
        redComposite = slicer.app.layoutManager().sliceWidget("Red").mrmlSliceCompositeNode()
        for component in range(3):
            widget.onShowComponentVolumeButton(component)
            self.report.checkEqual(f"[GUI] Component button {component + 1} shows the velocity component of the input flow field",
                redComposite.GetBackgroundVolumeID(), self.logic.getRawComponentVolume(flowFieldNode, component).GetID())
        self.report.screenshot("Clinical data set: component image with phase wrap segmentation in the module GUI", kind="window")
        widget.onShowMagnitudeVolumeButton()
        self.report.checkEqual("[GUI] Magnitude button shows the magnitude image", redComposite.GetBackgroundVolumeID(),
            flowFieldNode.GetNodeReference("magnitudeVolume").GetID())

        # Unwrapping modes
        parameterNode.unwrapMode = UnwrapModeEnum.NoUnwrap
        widget.onComputePhaseUnwrappingButton()
        widget.onRecomputeFlowFieldButton()
        noUnwrapFrames = self.velocityFrames(flowFieldNode)
        changedVoxels = sum(int(np.count_nonzero(np.any(a != b, axis=-1))) for a, b in zip(noUnwrapFrames, temporalFrames))
        self.report.text(f"Number of voxels (over all frames) changed by temporal unwrapping: {changedVoxels}")
        self.report.checkTrue("[GUI] Removing phase unwrapping changes the flow field (the data set contains phase wraps)", changedVoxels > 0, changedVoxels, "> 0")
        parameterNode.unwrapMode = UnwrapModeEnum.TemporalUnwrap
        widget.onComputePhaseUnwrappingButton()
        widget.onRecomputeFlowFieldButton()
        self.report.checkClose("[GUI] Temporal unwrapping again gives the same flow field (max. difference)",
            max(float(np.abs(a - b).max()) for a, b in zip(self.velocityFrames(flowFieldNode), temporalFrames)), 0.0, atol=1e-6, unit="m/s")
        parameterNode.unwrapMode = UnwrapModeEnum.LaplacianThenTemporalUnwrap
        widget.onComputePhaseUnwrappingButton()
        widget.onRecomputeFlowFieldButton()
        laplacianFrames = self.velocityFrames(flowFieldNode)
        sameVoxels = np.mean([np.mean(np.all(np.abs(a - b) < 1e-6, axis=-1)) for a, b in zip(laplacianFrames, temporalFrames)])
        self.report.checkTrue("[GUI] Laplacian + temporal unwrapping (slicerheart_4dflow) agrees with temporal unwrapping",
            sameVoxels > 0.99, f"{100 * sameVoxels:.2f}% of voxels", "> 99%")
        parameterNode.unwrapMode = UnwrapModeEnum.TemporalUnwrap
        widget.onComputePhaseUnwrappingButton()
        widget.onRecomputeFlowFieldButton()

        # Export
        exportDir = os.path.join(workDir, "export")
        os.makedirs(exportDir)
        parameterNode.exportDirectory = exportDir
        parameterNode.exportFormat = Import4DFlowLogic.EXPORT_FORMAT_NRRD_5D
        widget.onExportButton()
        exportedFile = os.path.join(exportDir, "flowfield.seq.nrrd")
        self.report.checkTrue("[GUI] 5D NRRD file is exported", os.path.exists(exportedFile), os.listdir(exportDir))
        if os.path.exists(exportedFile):
            loadedSequenceNode = slicer.util.loadNodeFromFile(exportedFile, "SequenceFile")
            self.report.checkClose("[GUI] Exported 5D NRRD file contains the flow field (max. difference)",
                max(float(np.abs(slicer.util.arrayFromVolume(loadedSequenceNode.GetNthDataNode(i)) / 1000.0 - temporalFrames[i]).max())
                    for i in range(loadedSequenceNode.GetNumberOfDataNodes())), 0.0, atol=1e-5, unit="m/s")  # file: mm/s
        self.report.screenshot("Clinical data set: module GUI after export", kind="window")

    # slicerheart_4dflow methods

    def addRandomPhaseInAir(self, volumeNodeSet, phantom, seed=0):
        """Replace the phase in the air (background) by random values in each frame, as in real images,
        where the phase of noise voxels is random."""
        rng = np.random.default_rng(seed)
        air = phantom.magnitudeVolumeArray() < 10
        for componentVolumeNode in volumeNodeSet["componentVolumeNodes"]:
            sequenceNode = self.logic._getSequenceFromProxyNode(componentVolumeNode)
            for frameIndex in range(sequenceNode.GetNumberOfDataNodes()):
                frameNode = sequenceNode.GetNthDataNode(frameIndex)
                array = slicer.util.arrayFromVolume(frameNode)
                array[air] = rng.integers(-FlowTestingUtils.PHASE_MAX_VALUE, FlowTestingUtils.PHASE_MAX_VALUE, np.count_nonzero(air))
                slicer.util.arrayFromVolumeModified(frameNode)
        return air

    @reportedTest("Background phase correction by slicerheart_4dflow methods",
        "A linear or quadratic background phase error is added to the component images of a phantom with realistic proportions"
        " and velocity noise (2 cm/s in stationary tissue, random phase in the air). The slicerheart_4dflow robust polynomial fits"
        " (least squares, MSAC, weighted least squares, wrap-around rejection + MSAC) must remove at least 80% of the error from"
        " stationary tissue and the vessel, as the SlicerHeart fits do. The background error is smooth and the same in all frames,"
        " while the noise is not: the residual error is averaged over the frames and smoothed in each region (Gaussian, 2 voxels)"
        " before it is measured.")
    def test_21_LibraryBackgroundCorrection(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom(vesselRadiusMm=5.0, tissueRadiusMm=30.0, velocityNoiseCmPerSec=2.0)
        stationaryTissue = phantom.stationaryTissueMask()
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        rows = []
        for offsetName, phaseOffset, order in [("linear offset", phantom.linearPhaseOffset(), 1), ("quadratic offset", phantom.quadraticPhaseOffset(), 2)]:
            offsetError = float(np.abs(phaseOffset[stationaryTissue]).mean() / FlowTestingUtils.PHASE_MAX_VALUE * vencCmPerSec / 100.0)
            methods = [BackgroundSubtractionMethodEnum.QuadraticFit, BackgroundSubtractionMethodEnum.OlsFit, BackgroundSubtractionMethodEnum.MsacFit,
                       BackgroundSubtractionMethodEnum.WrlsFit, BackgroundSubtractionMethodEnum.WarMsacFit]
            for method in methods:
                for perFrame in ([False, True] if method == BackgroundSubtractionMethodEnum.WarMsacFit else [False]):
                    slicer.mrmlScene.Clear()
                    volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec, phaseOffset=phaseOffset)
                    flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(volumeNodeSet["componentVolumeNodes"],
                        volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"])
                    startTime = time.time()
                    self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, method, 10.0,
                        backgroundPolynomialOrder=max(order, 2), backgroundPerFrame=perFrame)
                    duration = time.time() - startTime
                    residual = np.mean([frame - expected for frame, expected in zip(self.velocityFrames(flowFieldNode), expectedFrames)], axis=0)
                    tissueError = float(np.abs(self.smoothInMask(residual, stationaryTissue)[stationaryTissue]).mean())
                    vesselError = float(np.abs(self.smoothInMask(residual, phantom.insideVessel)[phantom.insideVessel]).mean())
                    label = f"[{offsetName}, {method.label()}{', per frame' if perFrame else ''}]"
                    rows.append([offsetName, method.label() + (", per frame" if perFrame else ""), offsetError, tissueError, vesselError, duration])
                    self.report.checkClose(f"{label} Mean residual velocity in stationary tissue", tissueError, 0.0, atol=0.2 * offsetError, unit="m/s")
                    self.report.checkClose(f"{label} Mean velocity error in the vessel", vesselError, 0.0, atol=0.2 * offsetError, unit="m/s")
        self.report.table(["Background error", "Method", "Mean background error (m/s)", "Mean residual in stationary tissue (m/s)",
            "Mean velocity error in vessel (m/s)", "Time (s)"], rows, "Residual errors averaged over the frames")

    @staticmethod
    def smoothInMask(vectors, mask, sigmaVoxels=2.0):
        """Gaussian smoothing of vectors (k, j, i, 3) using only the voxels in the mask (normalized convolution), to measure
        smooth (systematic) errors in the presence of noise."""
        from scipy.ndimage import gaussian_filter
        weight = gaussian_filter(mask.astype(float), sigmaVoxels)
        smoothed = np.zeros(vectors.shape)
        for component in range(vectors.shape[-1]):
            smoothed[..., component] = gaussian_filter(np.where(mask, vectors[..., component], 0.0), sigmaVoxels) / np.maximum(weight, 1e-6)
        return smoothed

    @reportedTest("Laplacian phase unwrapping (slicerheart_4dflow)",
        "Velocity encoding (70 cm/s) is below the peak velocity (100 cm/s). Laplacian 3D, Laplacian 4D and Laplacian 3D + temporal"
        " unwrapping must find the same wraps as the analytic solution, store them in the phase wrap segmentations (so they can be"
        " edited manually, as temporal unwrapping results), and the corrected flow field must match the analytic velocity.")
    def test_22_LaplacianUnwrap(self):
        vencCmPerSec = 70.0
        phantom = FlowPhantom()
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
        flowFieldNode = self.createFlowField(volumeNodeSet, False, unwrap=True)
        temporalWraps = self.logic.getWrapCounts(flowFieldNode)
        rows = []
        for mode in [UnwrapModeEnum.LaplacianUnwrap, UnwrapModeEnum.Laplacian4DUnwrap, UnwrapModeEnum.LaplacianThenTemporalUnwrap]:
            startTime = time.time()
            self.logic.laplacianUnwrap(flowFieldNode, mode, 5.0)
            duration = time.time() - startTime
            self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
            wraps = self.logic.getWrapCounts(flowFieldNode)
            self.report.checkTrue(f"[{mode.label()}] Phase wrap segmentations are created",
                all(flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", c) for c in range(3)))
            differentVoxels = int(np.count_nonzero(wraps != temporalWraps))
            self.report.checkEqual(f"[{mode.label()}] Voxels with different wraps than temporal unwrapping", differentVoxels, 0)
            self.checkVelocityFrames(f"[{mode.label()}]", self.velocityFrames(flowFieldNode), expectedFrames, velocityQuantizationMPerSec(vencCmPerSec))
            processing = json.loads(self.logic._getSequenceFromProxyNode(flowFieldNode).GetAttribute("SlicerHeart.processing"))
            self.report.checkEqual(f"[{mode.label()}] Unwrapping method is recorded in the flow field", processing["phaseUnwrapping"], mode.name)
            rows.append([mode.label(), int(np.count_nonzero(wraps)), differentVoxels, duration])
        self.report.table(["Method", "Wrapped voxels", "Different from temporal unwrapping", "Time (s)"], rows)

        # Results can be edited: remove the 1x positive wraps of component 3 in the peak frame
        peakFrame = phantom.peakFrameIndex()
        FlowTestingUtils.selectSequenceItem(flowFieldNode, peakFrame)
        segmentationNode = flowFieldNode.GetNthNodeReference("phaseWrapSegmentation", 2)
        segmentId = "Wrap-Pos-1x" if segmentationNode.GetSegmentation().GetSegment("Wrap-Pos-1x") else "Wrap-Neg-1x"
        slicer.util.updateSegmentBinaryLabelmapFromArray(np.zeros(phantom.radialDistanceMm.shape, np.uint8), segmentationNode, segmentId,
            flowFieldNode.GetNodeReference("magnitudeVolume"))
        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
        editedError = float(np.abs(self.velocityFrames(flowFieldNode)[peakFrame] - expectedFrames[peakFrame]).max())
        self.report.checkTrue("Editing the phase wrap segmentation changes the flow field", editedError > 0.5, f"{editedError:.2f} m/s", "> 0.5 m/s")

    @reportedTest("Noise mask by magnitude and velocity noise (slicerheart_4dflow)",
        "The phase of noise voxels (air) is random, as in real images. The slicerheart_4dflow noise mask (low magnitude by Otsu"
        " threshold, or random phase) must set velocity to zero in the air and keep the velocity in the vessel and tissue.")
    def test_23_LibraryNoiseMask(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom()
        volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
        air = self.addRandomPhaseInAir(volumeNodeSet, phantom)
        flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(volumeNodeSet["componentVolumeNodes"],
            volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"])
        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 0.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0,
            noiseMaskMethod=NoiseMaskMethodEnum.BockNoiseMask)
        frames = self.velocityFrames(flowFieldNode)
        maxAirSpeed = max(float(np.linalg.norm(frame[air], axis=-1).max()) for frame in frames)
        self.report.checkClose("Maximum speed in the air (random phase)", maxAirSpeed, 0.0, atol=1e-6, unit="m/s")
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        self.checkVelocityFrames("Velocity in the vessel and tissue", frames, expectedFrames, velocityQuantizationMPerSec(vencCmPerSec), mask=~air)
        processing = json.loads(self.logic._getSequenceFromProxyNode(flowFieldNode).GetAttribute("SlicerHeart.processing"))
        self.report.checkEqual("Noise mask method is recorded in the flow field", processing["noiseMask"], "BockNoiseMask")

    @reportedTest("Divergence-free filtering (slicerheart_4dflow)",
        "Noise is added to the phantom velocity. Divergence-free filtering in the vessel segmentation must reduce the divergence and"
        " the velocity error in the vessel. Filtering without lumen segmentation must be rejected.")
    def test_24_DivergenceFreeFiltering(self):
        vencCmPerSec = 150.0
        phantom = FlowPhantom(numberOfFrames=4)
        rng = np.random.default_rng(1)
        noise = [rng.normal(0, 60, phantom.radialDistanceMm.shape) for _ in range(3)]  # raw units, about 2 cm/s
        library = FlowLibraryBridge.ensureLibrary()
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        interior = phantom.radialDistanceMm < phantom.vesselRadiusMm - 2.0
        interior[:3], interior[-3:], interior[:, :3], interior[:, -3:], interior[:, :, :3], interior[:, :, -3:] = False, False, False, False, False, False
        rows = []
        for method in [DivergenceFilterMethodEnum.NoFilter, DivergenceFilterMethodEnum.FdmProjection, DivergenceFilterMethodEnum.RelaxedProjection,
                       DivergenceFilterMethodEnum.LerayProjection, DivergenceFilterMethodEnum.DivergenceFreeWavelet]:
            slicer.mrmlScene.Clear()
            volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
            for component, componentVolumeNode in enumerate(volumeNodeSet["componentVolumeNodes"]):
                sequenceNode = self.logic._getSequenceFromProxyNode(componentVolumeNode)
                for frameIndex in range(sequenceNode.GetNumberOfDataNodes()):
                    array = slicer.util.arrayFromVolume(sequenceNode.GetNthDataNode(frameIndex))
                    array[:] = np.clip(array + noise[component], -FlowTestingUtils.PHASE_MAX_VALUE, FlowTestingUtils.PHASE_MAX_VALUE - 1)
                    slicer.util.arrayFromVolumeModified(sequenceNode.GetNthDataNode(frameIndex))
            flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(volumeNodeSet["componentVolumeNodes"],
                volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"])
            segmentationNode, segmentId = phantom.createVesselSegmentation(volumeNodeSet["magnitudeVolumeNode"])
            lumenMask = self.logic.getLumenMask(flowFieldNode, segmentationNode, segmentId)
            if method == DivergenceFilterMethodEnum.FdmProjection:
                with self.assertRaises(ValueError):
                    self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0,
                        divergenceFilterMethod=method)
                self.report.checkTrue("Divergence-free filtering without lumen segmentation is rejected", True)
            startTime = time.time()
            self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0,
                divergenceFilterMethod=method, lumenMask=lumenMask)
            duration = time.time() - startTime
            velocity, voxelToWorld, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
            divergence = np.mean([library.divergence_stats(velocity[t], lumenMask, voxelToWorld)["div_rms"] for t in range(velocity.shape[0])])
            error = float(np.mean([np.abs(velocity[t][interior] / 1000.0 - expectedFrames[t][interior]).mean() for t in range(velocity.shape[0])]))
            rows.append([method.label(), divergence, error, duration])
        self.report.table(["Method", "Divergence RMS in the vessel (1/s)", "Mean velocity error in the vessel interior (m/s)", "Time (s)"], rows)
        for row in rows[1:]:
            self.report.checkTrue(f"[{row[0]}] Divergence is reduced", row[1] < rows[0][1], f"{row[1]:.3g}", f"< {rows[0][1]:.3g}")
        self.report.checkTrue("[finite difference projection] Velocity error is not increased", rows[1][2] <= rows[0][2] * 1.05,
            f"{rows[1][2]:.4f}", f"<= {rows[0][2] * 1.05:.4f}")

    @reportedTest("Encoding check, PC-MRA, lumen estimation and quality report (slicerheart_4dflow)",
        "The encoding check must accept the correct velocity component mapping and reject a mapping with an inverted component."
        " The lumen segmentation estimated from the PC-MRA must cover the vessel. The quality report must flag the venc as"
        " inadequate when the velocity is aliased.")
    def test_25_QualityChecks(self):
        phantom = FlowPhantom(velocityNoiseCmPerSec=2.0)
        volumeNodeSet = phantom.createComponentImagesInScene(150.0)
        flowFieldNode = self.createFlowField(volumeNodeSet, False)
        segmentationNode, segmentId = phantom.createVesselSegmentation(volumeNodeSet["magnitudeVolumeNode"])
        lumenMask = self.logic.getLumenMask(flowFieldNode, segmentationNode, segmentId)
        result = self.logic.checkEncodingDirections(flowFieldNode, lumenMask)
        self.report.text("Correct mapping: " + self.logic.encodingCheckSummary(result))
        self.report.checkTrue("Correct component mapping is consistent", result["consistent"])

        # Invert one component (wrong sign flag)
        wrongConfiguration = list(FlowTestingUtils.DIRECTION_CONFIGURATION_AXIAL)
        wrongConfiguration[2] = (wrongConfiguration[2][0], not wrongConfiguration[2][1])
        wrongVolumeNodeSet = phantom.createComponentImagesInScene(150.0)
        wrongFlowFieldNode = self.logic.createFlowFieldFromComponentVolumes(wrongVolumeNodeSet["componentVolumeNodes"],
            [not invert if axis == 2 else invert for axis, invert in enumerate(wrongVolumeNodeSet["componentVolumeNodesInvertToRasDirection"])],
            wrongVolumeNodeSet["magnitudeVolumeNode"])
        self.logic.updateFlowFieldFromComponentVolumes(wrongFlowFieldNode, 5.0, BackgroundSubtractionMethodEnum.NoSubtraction, 10.0)
        wrongResult = self.logic.checkEncodingDirections(wrongFlowFieldNode, lumenMask)
        self.report.text("Mapping with inverted S component: " + self.logic.encodingCheckSummary(wrongResult))
        self.report.checkTrue("Mapping with an inverted component is inconsistent", not wrongResult["consistent"])

        pcmraNode = self.logic.createPcmraVolume(flowFieldNode)
        pcmra = slicer.util.arrayFromVolume(pcmraNode)
        self.report.checkTrue("PC-MRA is brighter in the vessel than in the tissue",
            pcmra[phantom.insideVessel].mean() > 10 * pcmra[phantom.stationaryTissueMask()].mean())
        lumenSegmentationNode, lumenSegmentId = self.logic.createLumenSegmentation(flowFieldNode)
        estimatedLumen = self.logic.getLumenMask(flowFieldNode, lumenSegmentationNode, lumenSegmentId)
        dice = 2 * np.count_nonzero(estimatedLumen & phantom.insideVessel) / (np.count_nonzero(estimatedLumen) + np.count_nonzero(phantom.insideVessel))
        self.report.checkTrue("Estimated lumen overlaps the vessel (Dice)", dice > 0.7, f"{dice:.2f}", "> 0.7")
        # The lumen segment is on a grid twice as fine as the image, and keeps that resolution for editing
        from Import4DFlowLib import FlowLibraryBridge
        segmentMask, segmentVoxelToWorld = FlowLibraryBridge.segmentLabelmap(lumenSegmentationNode, lumenSegmentId)
        imageSpacing = np.linalg.norm(FlowLibraryBridge.voxelToWorld(FlowLibraryBridge.flowFieldGeometryNode(flowFieldNode))[:3, :3], axis=0)
        segmentSpacing = np.linalg.norm(segmentVoxelToWorld[:3, :3], axis=0)
        self.report.checkTrue("Lumen segment is on a grid twice as fine as the image", np.allclose(segmentSpacing, imageSpacing / 2),
            np.round(segmentSpacing, 3).tolist(), f"{np.round(imageSpacing / 2, 3).tolist()}")
        lumenFraction = FlowLibraryBridge.maskFractionFromSegment(lumenSegmentationNode, lumenSegmentId,
                                                                   FlowLibraryBridge.flowFieldGeometryNode(flowFieldNode))
        partialVoxels = np.count_nonzero((lumenFraction > 0) & (lumenFraction < 1))
        self.report.checkTrue("Lumen fraction on the image grid has partial voxels at the wall", partialVoxels > 0, partialVoxels, "> 0")
        self.report.checkTrue("Lumen fraction is the fraction of fine voxels", np.allclose(lumenFraction * 8, np.round(lumenFraction * 8), atol=1e-4))

        report = self.logic.computeQualityReport(flowFieldNode, lumenMask)
        self.report.checkTrue("[venc 150 cm/s] Quality report: venc is adequate", report["venc"]["venc_adequate"])
        tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Quality report")
        self.logic.qualityReportToTable(report, tableNode)
        self.report.checkTrue("Quality report table is created", tableNode.GetNumberOfRows() > 10, tableNode.GetNumberOfRows(), "> 10")
        markdown = self.logic.qualityReportToMarkdown(report)
        self.report.checkTrue("Quality report markdown is created", len(markdown) > 100)

        slicer.mrmlScene.Clear()
        aliasedVolumeNodeSet = phantom.createComponentImagesInScene(70.0)
        aliasedFlowFieldNode = self.createFlowField(aliasedVolumeNodeSet, False, unwrap=True)
        aliasedReport = self.logic.computeQualityReport(aliasedFlowFieldNode, phantom.insideVessel)
        self.report.checkTrue("[venc 70 cm/s] Quality report: venc is not adequate", not aliasedReport["venc"]["venc_adequate"])

    @reportedTest("Test case export and loading (Slicer-native files for slicerheart_4dflow)",
        "The flow field (aliased phantom with background error, unwrapped and background corrected) is exported as a test case."
        " The files are read by slicerheart_4dflow.slicer_io (without Slicer) and must contain the analytic velocity in LPS"
        " components, the raw (aliased) velocity, the wraps, the geometry, measurement planes, plane flows, and the descriptions"
        " of the acquisition, processing and annotations, and no identifying information. Loading the test case into Slicer (without DICOM) must reproduce the flow field and the phase"
        " wrap segmentations.")
    def test_26_TestCaseExportAndLoad(self):
        vencCmPerSec = 70.0
        phantom = FlowPhantom()
        volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
        flowFieldNode = self.createFlowField(volumeNodeSet, False, unwrap=True)
        segmentationNode, segmentId = phantom.createVesselSegmentation(volumeNodeSet["magnitudeVolumeNode"])
        planeNode = phantom.createMeasurementPlane(name="vessel")
        datasetDirectory, caseId = self.temporaryDirectory("TestCase"), "Phantom0001"
        startTime = time.time()
        self.logic.exportTestCaseWithFlows(flowFieldNode, datasetDirectory, caseId, lumenSegmentationNode=segmentationNode,
            lumenSegmentId=segmentId, planeNodes=[planeNode], metadata={"vendor": "siemens"})
        self.report.text(f"Export time: {time.time() - startTime:.1f} s")
        library = FlowLibraryBridge.ensureLibrary()
        self.report.checkEqual("Data set has the exported case", library.dataset_cases(datasetDirectory), [caseId])
        case = library.load_case(datasetDirectory, caseId)  # LPS, as a user of slicerheart_4dflow would read it
        lpsFromRas = np.diag([-1.0, -1.0, 1.0])
        expected = np.stack([phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]) * 1000.0 @ lpsFromRas
        self.report.checkClose("Velocity in the files equals the analytic velocity (LPS components, mm/s)",
            float(np.abs(case["velocity_t"] - expected).max()), 0.0, atol=velocityQuantizationMPerSec(vencCmPerSec) * 1000.0, unit="mm/s")
        ijkToRas = slicer.util.arrayFromVTKMatrix(phantom.ijkToRasMatrix())
        self.report.checkClose("Voxel to world (LPS) matrix", float(np.abs(case["voxel_to_world"] - np.diag([-1, -1, 1, 1]) @ ijkToRas).max()), 0.0, atol=1e-4)
        self.report.checkClose("Frame times", float(np.abs(case["time_ms"] - np.array(phantom.frameTimesMs)).max()), 0.0, atol=1e-3, unit="ms")
        self.report.checkTrue("Raw velocity is aliased (within venc in each encoded component)",
            bool(np.all(np.abs(case["velocity_raw_encoded_t"]) <= case["venc_encoded_mm_s"] + 1e-3)))
        self.report.checkEqual("Wrap counts are integers per encoded component", str(case["wrap_count_t"].dtype), "int16")
        # Wraps are per encoded component: world velocity = encoding_to_world (raw + 2 venc wraps)
        unwrapped = (case["velocity_raw_encoded_t"] + 2 * case["venc_encoded_mm_s"] * case["wrap_count_t"]) @ case["encoding_to_world"].T
        inside = phantom.insideVessel
        self.report.checkClose("Raw velocity + 2 venc x wraps equals the corrected velocity in the vessel",
            float(np.abs(unwrapped[:, inside] - case["velocity_t"][:, inside]).max()), 0.0, atol=1e-2, unit="mm/s")
        self.report.checkEqual("Lumen segmentation", int(np.count_nonzero(case["lumen"] != inside)), 0)
        self.report.checkEqual("Planes", list(case["planes"].keys()), ["vessel"])
        np.testing.assert_allclose(case["planes"]["vessel"]["normal"], lpsFromRas @ phantom.vesselAxis, atol=1e-6)
        rrMs = case["rr_ms"]
        expectedNetVolume = np.mean([phantom.expectedFlowRateMlPerSec(i) for i in range(phantom.numberOfFrames)]) * rrMs / 1000.0
        self.report.checkClose("Net flow volume (plane probe, outputs/flows.json)", case["flows"]["planes"]["vessel"]["net_volume_mL"], expectedNetVolume,
            rtol=0.05, unit="ml")
        libraryFlow = library.plane_flow(case["velocity_t"], case["voxel_to_world"], lumen_mask=case["lumen"], **case["planes"]["vessel"])["flow"] / 1000.0
        self.report.checkClose("slicerheart_4dflow net flow volume from the files", float(np.mean(libraryFlow) * rrMs / 1000.0), expectedNetVolume,
            rtol=0.05, unit="ml")
        self.report.checkTrue("Wrap counts record aliasing", bool(np.any(case["wrap_count_t"] != 0)))
        manifest = Import4DFlowLogic.readTestCaseJson(datasetDirectory, caseId, "manifest")
        self.report.checkEqual("Manifest of the data set", [manifest["format_version"], manifest["license"], manifest["doi"]], [4, "internal", None])
        self.report.checkTrue("Inputs and outputs of the case are in inputs/<case> and outputs/<case>",
            os.path.isfile(os.path.join(datasetDirectory, "inputs", caseId, "acquisition", "velocity_raw.seq.nrrd"))
            and os.path.isfile(os.path.join(datasetDirectory, "outputs", caseId, "velocity.seq.nrrd")))
        self.report.checkEqual("Acquisition description records the vendor", case["acquisition"]["vendor"], "siemens")
        self.report.checkEqual("Processing description records the processing", case["processing"]["processing"]["phaseUnwrapping"], "TemporalUnwrap")
        self.report.checkEqual("Annotations description: specified lumen and planes",
            [case["annotations"]["lumen"]["method"], case["annotations"]["planes"]["method"], case["annotations"]["planes"]["files"]],
            ["manual", "manual", ["vessel.mrk.json"]])
        import nrrd
        for root, _, files in os.walk(datasetDirectory):
            for filename in files:
                if filename.endswith(".nrrd"):
                    header = nrrd.read_header(os.path.join(root, filename))
                    names = [value for key, value in header.items() if key.endswith("_Name")]
                    self.report.checkTrue(f"{filename}: no node names in the header", all(name in ("lumen",) for name in names), names)
        for key in ("manifest", "acquisition", "processing", "annotations"):
            with open(Import4DFlowLogic.testCasePath(datasetDirectory, caseId, key), encoding="utf-8") as file:
                descriptionText = file.read()
            for word in ["Phantom browser", "DICOM", "PatientName", "StudyDate"]:
                self.report.checkTrue(f"{key} description does not contain '{word}'", word not in descriptionText)

        # Load into Slicer without DICOM
        originalVelocity, _, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        originalWraps = self.logic.getWrapCounts(flowFieldNode)
        slicer.mrmlScene.Clear()
        startTime = time.time()
        loaded = self.logic.loadTestCase(datasetDirectory, caseId)
        self.report.text(f"Loading time: {time.time() - startTime:.1f} s")
        loadedVelocity, _, _ = FlowLibraryBridge.velocityArrayFromFlowField(loaded["flowFieldNode"])
        self.report.checkClose("Loaded test case: flow field equals the exported flow field", float(np.abs(loadedVelocity - originalVelocity).max()), 0.0,
            atol=1e-3, unit="mm/s")
        self.report.checkEqual("Loaded test case: phase wrap segmentations are restored",
            int(np.count_nonzero(self.logic.getWrapCounts(loaded["flowFieldNode"]) != originalWraps)), 0)
        self.report.checkTrue("Loaded test case: lumen and planes are loaded", loaded["lumenSegmentationNode"] is not None and len(loaded["planeNodes"]) == 1)
        self.report.checkEqual("Loaded test case: lumen segmentation file can be saved back to the case",
            os.path.normpath(loaded["lumenSegmentationNode"].GetStorageNode().GetFileName()),
            os.path.normpath(os.path.join(datasetDirectory, "inputs", caseId, "annotations", Import4DFlowLogic.TEST_CASE_LUMEN_FILE)))

        # Regenerating the outputs: loaded from the inputs only, processed with the default processing of test cases
        slicer.mrmlScene.Clear()
        regenerated = self.logic.loadTestCase(datasetDirectory, caseId, useOutputs=False)
        frames = self.velocityFrames(regenerated["flowFieldNode"])
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        regeneratedError = max(float(np.abs(f - e)[inside].mean()) for f, e in zip(frames, expectedFrames))
        self.report.checkClose("Loaded from the inputs only (default processing, wraps not read from the outputs):"
            " mean velocity error in the vessel", regeneratedError, 0.0, atol=0.03, unit="m/s")
        processing = json.loads(self.logic._getSequenceFromProxyNode(regenerated["flowFieldNode"]).GetAttribute("SlicerHeart.processing"))
        self.report.checkEqual("Loaded from the inputs only: default unwrapping method", processing["phaseUnwrapping"],
            Import4DFlowLogic.TEST_CASE_DEFAULT_UNWRAP_MODE)

    @reportedTest("slicerheart_4dflow methods in the GUI",
        "Library methods are selected in the module GUI (noise mask, background fit, Laplacian unwrapping, divergence-free filter),"
        " the flow field is created from the phantom images, quality checks are run by the GUI buttons, and the flow field is"
        " exported as a test case and loaded back.")
    def test_27_LibraryGuiWorkflow(self):
        vencCmPerSec = 70.0
        phantom = FlowPhantom(vesselRadiusMm=6.0, tissueRadiusMm=30.0, numberOfFrames=6, velocityNoiseCmPerSec=2.0)
        volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec, phaseOffset=phantom.quadraticPhaseOffset())
        slicer.util.selectModule("Import4DFlow")
        widget = slicer.modules.import4dflow.widgetRepresentation().self()
        widget._volumeNodesSets = {"phantom": volumeNodeSet}
        widget.ui.inputVolumeNodeSetSelector.clear()
        widget.ui.inputVolumeNodeSetSelector.addItem("Phantom", "phantom")
        parameterNode = widget._parameterNode
        parameterNode.inputVolumeNodeSet = "phantom"
        parameterNode.unwrapMode = UnwrapModeEnum.LaplacianThenTemporalUnwrap
        parameterNode.backgroundSubtractionMethod = BackgroundSubtractionMethodEnum.WarMsacFit
        parameterNode.backgroundPolynomialOrder = 2
        parameterNode.noiseMaskMethod = NoiseMaskMethodEnum.MagnitudeThreshold
        slicer.app.processEvents()
        self.report.checkTrue("[GUI] Polynomial order is enabled for slicerheart_4dflow background fit", widget.ui.backgroundPolynomialOrderSpinBox.enabled)
        parameterNode.backgroundSubtractionMethod = BackgroundSubtractionMethodEnum.QuadraticFit
        slicer.app.processEvents()
        self.report.checkTrue("[GUI] Polynomial order is disabled for SlicerHeart background fit", not widget.ui.backgroundPolynomialOrderSpinBox.enabled)
        parameterNode.backgroundSubtractionMethod = BackgroundSubtractionMethodEnum.WarMsacFit
        self.report.checkEqual("[GUI] Unwrapping method combobox shows the selected method",
            widget.ui.unwrappingMethodSelector.currentText, UnwrapModeEnum.LaplacianThenTemporalUnwrap.label())
        widget.onConvertButton()
        flowFieldNode = parameterNode.outputFlowField
        self.report.checkTrue("[GUI] Flow field is created", flowFieldNode is not None)
        expectedFrames = [phantom.velocityVolumeArray(i) for i in range(phantom.numberOfFrames)]
        frames = self.velocityFrames(flowFieldNode)
        vesselError = max(float(np.abs(f - e)[phantom.insideVessel].mean()) for f, e in zip(frames, expectedFrames))
        self.report.checkClose("[GUI] Mean velocity error in the vessel (Laplacian + temporal unwrapping, robust background fit)", vesselError, 0.0, atol=0.03, unit="m/s")

        parameterNode.lumenSegmentation = None
        parameterNode.lumenSegmentID = ""
        widget.onComputeLumenButton()
        self.report.checkTrue("[GUI] Lumen segmentation is created and selected", parameterNode.lumenSegmentation is not None and parameterNode.lumenSegmentID)
        segmentationNode, segmentId = phantom.createVesselSegmentation(volumeNodeSet["magnitudeVolumeNode"])
        parameterNode.lumenSegmentation = segmentationNode
        parameterNode.lumenSegmentID = segmentId
        parameterNode.divergenceFilterMethod = DivergenceFilterMethodEnum.FdmProjection
        widget.onRecomputeFlowFieldButton()
        processing = json.loads(self.logic._getSequenceFromProxyNode(flowFieldNode).GetAttribute("SlicerHeart.processing"))
        self.report.checkEqual("[GUI] Divergence filter is applied", processing["divergenceFilter"], "FdmProjection")
        widget.onCheckEncodingButton()
        self.report.checkTrue("[GUI] Encoding check result is shown", "consistent" in widget.ui.qualityReportTextBrowser.toPlainText())
        widget.onComputeQualityReportButton()
        self.report.checkTrue("[GUI] Quality report is shown", len(widget.ui.qualityReportTextBrowser.toPlainText()) > 100)
        parameterNode.pcmraVolume = None
        widget.onComputePcmraButton()
        self.report.checkTrue("[GUI] PC-MRA volume is created and selected", parameterNode.pcmraVolume is not None)
        self.report.screenshot("Import 4D Flow module GUI with slicerheart_4dflow methods", kind="window")

        datasetDirectory, caseId = self.temporaryDirectory("GuiTestCase"), "Phantom0002"
        parameterNode.exportDirectory = datasetDirectory
        parameterNode.exportFormat = Import4DFlowLogic.EXPORT_FORMAT_TEST_CASE
        self.report.checkEqual("[GUI] Case ID suggested for a new data set", Import4DFlowLogic.nextTestCaseId(datasetDirectory), "Case0001")
        askTestCaseId = widget.askTestCaseId
        widget.askTestCaseId = lambda directory: caseId  # instead of the dialog
        try:
            widget.onExportButton()
        finally:
            widget.askTestCaseId = askTestCaseId
        self.report.checkTrue("[GUI] Test case is exported into the data set",
            os.path.isfile(os.path.join(datasetDirectory, "manifest.json")) and os.path.isdir(os.path.join(datasetDirectory, "inputs", caseId)))
        processingDescription = Import4DFlowLogic.readTestCaseJson(datasetDirectory, caseId, "processing")
        annotations = Import4DFlowLogic.readTestCaseJson(datasetDirectory, caseId, "annotations")
        self.report.checkEqual("[GUI] Test case records the processing", processingDescription["processing"]["backgroundSubtraction"], "WarMsacFit")
        self.report.checkEqual("[GUI] Measurement planes are placed automatically", annotations["planes"]["method"], "automatic")
        self.report.checkEqual("[GUI] Automatic planes are described by the algorithm", annotations["planes"]["algorithm"]["name"],
            "Analyze4DFlowLogic.findMeasurementPlanes")
        slicer.mrmlScene.Clear()
        self.report.checkEqual("[GUI] Case folder selected in the load dialog is resolved to the data set and case",
            Import4DFlowLogic.testCaseFromDirectory(os.path.join(datasetDirectory, "inputs", caseId)), (datasetDirectory, caseId))
        loaded = widget.loadTestCase(datasetDirectory, caseId)
        self.report.checkTrue("[GUI] Test case is loaded", loaded is not None and parameterNode.outputFlowField == loaded["flowFieldNode"])
        frames = self.velocityFrames(parameterNode.outputFlowField)
        loadedError = max(float(np.abs(f - e)[phantom.insideVessel].mean()) for f, e in zip(frames, expectedFrames))
        self.report.checkClose("[GUI] Loaded test case is processed as recorded (mean velocity error in the vessel)", loadedError, 0.0, atol=0.03, unit="m/s")

    @reportedTest("Clinical test cases (Slicer-native files, no DICOM import)",
        "The smallest clinical test case (the clinical test data set of slicerheart_4dflow, downloaded on first use, or a local data"
        " set in FlowTestingUtils.TEST_CASES_ENV_VARIABLE) is loaded without DICOM import."
        " The flow field computed with the recorded processing must match the velocity in the case files. slicerheart_4dflow"
        " Laplacian unwrapping and robust background correction are applied, and the flow through the planes must"
        " agree with the plane flows of the case (outputs/flows.json).")
    def test_28_ClinicalTestCase(self):
        testCases = FlowTestingUtils.testCases()
        if not testCases:
            self.skipTest("No 4D flow test case is available (the clinical test data set requires slicerheart_4dflow 0.3.1 or later"
                          f" and network access, or set {FlowTestingUtils.TEST_CASES_ENV_VARIABLE} in the environment or in .env.local"
                          " to the folder of a data set of test cases)")
        datasetDirectory, caseId = testCases[0]
        FlowTestingUtils.prepareTestCase(datasetDirectory, caseId)
        self.report.text(f"Test case: {caseId}")
        library = FlowLibraryBridge.ensureLibrary()
        case = library.load_case(datasetDirectory, caseId, world="RAS")
        startTime = time.time()
        loaded = self.logic.loadTestCase(datasetDirectory, caseId)
        self.report.text(f"Loading time: {time.time() - startTime:.1f} s")
        flowFieldNode = loaded["flowFieldNode"]
        velocity, voxelToWorld, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        self.report.checkClose("Flow field computed by the recorded processing equals the case velocity", float(np.abs(velocity - case["velocity_t"]).max()), 0.0,
            atol=1.0, unit="mm/s")
        lumen = case["lumen"]
        lumenSegmentation = loaded["lumenSegmentationNode"]
        lumenSegmentId = lumenSegmentation.GetSegmentation().GetNthSegmentID(0)
        self.logic.laplacianUnwrap(flowFieldNode, UnwrapModeEnum.LaplacianThenTemporalUnwrap, 5.0)
        self.logic.updateFlowFieldFromComponentVolumes(flowFieldNode, 5.0, BackgroundSubtractionMethodEnum.WarMsacFit, 10.0,
            lumenMask=self.logic.getLumenMask(flowFieldNode, lumenSegmentation, lumenSegmentId))
        corrected, _, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
        result = self.logic.checkEncodingDirections(flowFieldNode, lumen)
        self.report.checkTrue("Encoding directions are consistent", result["consistent"], self.logic.encodingCheckSummary(result))
        rows = []
        rrMs = case["rr_ms"]
        for name, reference in case["flows"]["planes"].items():
            flow = library.plane_flow(corrected, voxelToWorld, lumen_mask=lumen, **case["planes"][name])["flow"] / 1000.0
            net = float(np.mean(flow) * rrMs / 1000.0)
            rows.append([name, reference["net_volume_mL"], net])
            self.report.checkClose(f"[{name}] Net flow volume with slicerheart_4dflow corrections", net, reference["net_volume_mL"],
                atol=max(1.0, 0.15 * abs(reference["net_volume_mL"])), unit="ml")
        self.report.table(["Plane", "Case net volume (ml)", "slicerheart_4dflow corrections, net volume (ml)"], rows)
        self.logic.setFlowFieldVisualizationToDefault(flowFieldNode)
        FlowTestingUtils.showVolumeInSliceViews(loaded["magnitudeVolumeNode"])
        self.report.screenshot("Clinical test case loaded without DICOM import")

    @reportedTest("Default unwrapping method, unwrapping plausibility check, fallback to temporal unwrapping",
        "Laplacian 4D unwrapping is the default for new flow fields. Temporal unwrapping counts a wrap where the velocity"
        " changes by more than venc between frames, so random phase in voxels with signal accumulates false wraps: the"
        " plausibility check must warn (implausible speed or wraps remaining in the last frame), and must not warn for"
        " correctly unwrapped data. If slicerheart_4dflow is not available, the GUI must use temporal unwrapping.")
    def test_29_UnwrappingDefaultAndPlausibilityCheck(self):
        parameterNode = self.logic.getParameterNode()
        self.report.checkEqual("Default unwrapping method of a new parameter node", parameterNode.unwrapMode.name,
            UnwrapModeEnum.Laplacian4DUnwrap.name)

        # Correctly unwrapped aliased phantom: no warning
        vencCmPerSec = 70.0
        phantom = FlowPhantom()
        volumeNodeSet = phantom.createComponentImagesInScene(vencCmPerSec)
        flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(volumeNodeSet["componentVolumeNodes"],
            volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"])
        warnings = self.logic.temporalUnwrap(flowFieldNode, 0, 5.0)
        self.report.checkEqual("[aliased phantom] Temporal unwrapping warnings", warnings, [])
        warnings = self.logic.laplacianUnwrap(flowFieldNode, UnwrapModeEnum.LaplacianThenTemporalUnwrap, 5.0)
        self.report.checkEqual("[aliased phantom] Laplacian + temporal unwrapping warnings", warnings, [])

        # Random phase in a part of the tissue (signal above the noise threshold): temporal unwrapping accumulates false wraps
        slicer.mrmlScene.Clear()
        volumeNodeSet = phantom.createComponentImagesInScene(150.0)
        rng = np.random.default_rng(3)
        noisyTissue = phantom.stationaryTissueMask() & (rng.random(phantom.radialDistanceMm.shape) < 0.3)
        for componentVolumeNode in volumeNodeSet["componentVolumeNodes"]:
            sequenceNode = self.logic._getSequenceFromProxyNode(componentVolumeNode)
            for frameIndex in range(sequenceNode.GetNumberOfDataNodes()):
                array = slicer.util.arrayFromVolume(sequenceNode.GetNthDataNode(frameIndex))
                array[noisyTissue] = rng.integers(-FlowTestingUtils.PHASE_MAX_VALUE, FlowTestingUtils.PHASE_MAX_VALUE, np.count_nonzero(noisyTissue))
                slicer.util.arrayFromVolumeModified(sequenceNode.GetNthDataNode(frameIndex))
        flowFieldNode = self.logic.createFlowFieldFromComponentVolumes(volumeNodeSet["componentVolumeNodes"],
            volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"])
        warnings = self.logic.temporalUnwrap(flowFieldNode, 0, 5.0)
        self.report.text("Warnings of temporal unwrapping with random phase in 30% of the tissue voxels: " + " / ".join(warnings))
        self.report.checkTrue("[random phase in tissue] Temporal unwrapping gives a plausibility warning", len(warnings) > 0, len(warnings), "> 0")
        stored = json.loads(self.logic._getSequenceFromProxyNode(flowFieldNode).GetAttribute("SlicerHeart.phaseUnwrappingWarnings"))
        self.report.checkEqual("Warnings are stored in the flow field", stored, warnings)
        self.report.checkTrue("Warning recommends Laplacian unwrapping", all("Laplacian" in w for w in warnings))

        # Fallback to temporal unwrapping in the GUI if slicerheart_4dflow is not available
        slicer.util.selectModule("Import4DFlow")
        widget = slicer.modules.import4dflow.widgetRepresentation().self()
        widget._parameterNode.unwrapMode = UnwrapModeEnum.Laplacian4DUnwrap
        originalEnsureLibrary = FlowLibraryBridge.ensureLibrary

        def unavailableLibrary(*args, **kwargs):
            raise RuntimeError("slicerheart_4dflow Python package is required but it was not installed")

        FlowLibraryBridge.ensureLibrary = unavailableLibrary
        try:
            widget.computePhaseUnwrapping(flowFieldNode)
        finally:
            FlowLibraryBridge.ensureLibrary = originalEnsureLibrary
        self.report.checkEqual("[slicerheart_4dflow not available] Temporal unwrapping is used",
            self.logic._getSequenceFromProxyNode(flowFieldNode).GetAttribute("SlicerHeart.phaseUnwrapping"), UnwrapModeEnum.TemporalUnwrap.name)
