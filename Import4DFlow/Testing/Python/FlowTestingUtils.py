"""Shared utilities for the Import4DFlow and Analyze4DFlow feature tests.

- TestReport: collects test results, check tables and screenshots, and writes them into a markdown report.
- FlowPhantom: analytic pulsatile flow in a straight, oblique cylindrical vessel. It can generate
  Siemens CS 4D flow-like component (phase) and magnitude images, either directly into the scene
  or as DICOM files, and CFD-like flow field models (unstructured grid with a velocity point data array).
- DICOM helpers: load 4D flow series from a DICOM folder as volume sequences.

Test data locations (for example, anonymized clinical data sets) are read from environment variables
or from the .env.local file in the repository root (KEY=VALUE lines).
"""

import datetime
import functools
import json
import logging
import math
import os
import platform
import subprocess
import time
import traceback
import unittest

import numpy as np
import qt
import vtk
import vtk.util.numpy_support

import slicer

# Environment variable that specifies the root folder of the test reports
REPORT_DIR_ENV_VARIABLE = "SLICERHEART_TEST_REPORT_DIR"

# Environment variable (or .env.local entry) that specifies the folder of an anonymized 4D flow MRI DICOM data set
REAL_DATA_ENV_VARIABLE = "MRI_4D_FLOW_TEST_DATA"

# Siemens CS 4D flow component images store phase in the range of [-4096, 4096)
PHASE_MAX_VALUE = 4096

# Direction code configurations (same as Import4DFlowLogic.axisForDirectionCodes):
# for each RAS axis, (directionCode, invertToRasDirection)
DIRECTION_CONFIGURATION_AXIAL = [("through", True), ("inplane_ap", True), ("inplane_fh", False)]
DIRECTION_CONFIGURATION_CORONAL = [("inplane_rl", False), ("through", True), ("inplane_fh", False)]

# Short direction codes used in the SequenceName DICOM field (for example, 'fl3d1_v150in')
SEQUENCE_NAME_DIRECTION_CODES = {"through": "in", "inplane_ap": "ap", "inplane_fh": "fh", "inplane_rl": "rl"}


#
# Environment
#

def repositoryRoot():
    """Root folder of the SlicerHeartPrivate repository (the folder that contains this module folder)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def environmentValue(name, default=None):
    """Get a value from the environment, or from the .env.local file in the repository root."""
    value = os.environ.get(name)
    if value:
        return value
    envFilePath = os.path.join(repositoryRoot(), ".env.local")
    if os.path.exists(envFilePath):
        with open(envFilePath, encoding="utf-8") as envFile:
            for line in envFile:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
    return default


def gitDescription():
    """Short description of the current SlicerHeartPrivate source code version."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repositoryRoot(),
            capture_output=True, text=True, timeout=30).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repositoryRoot(),
            capture_output=True, text=True, timeout=30).stdout.strip()
        return commit + (" (with local changes)" if status else "")
    except Exception:
        return "unknown"


def isVectorFieldDisplayAvailable():
    """Vector field display node (glyph display of vector volumes) is only available in recent Slicer versions."""
    return hasattr(slicer, "vtkMRMLVectorFieldDisplayNode")


#
# Report
#

class TestReport:
    """Collects test results and writes a markdown report (report.md, with images in the images subfolder)
    and a machine-readable summary (results.json).

    The report is rewritten after each test, so partial results are available even if the application crashes.
    """

    STATUS_ICONS = {"PASSED": "✅", "FAILED": "❌", "SKIPPED": "⚠️"}

    def __init__(self, suiteName, title, description):
        self.suiteName = suiteName
        self.title = title
        self.description = description
        baseDir = os.environ.get(REPORT_DIR_ENV_VARIABLE) or os.path.join(slicer.app.temporaryPath, "SlicerHeart4DFlowTestReports")
        self.outputDir = os.path.join(baseDir, suiteName)
        self.imagesDir = os.path.join(self.outputDir, "images")
        os.makedirs(self.imagesDir, exist_ok=True)
        for fileName in os.listdir(self.imagesDir):
            if fileName.endswith(".png"):
                os.remove(os.path.join(self.imagesDir, fileName))
        self.startTime = datetime.datetime.now()
        self.tests = []
        self.currentTest = None
        self.imageCounter = 0
        self.environment = self._collectEnvironment()

    @staticmethod
    def _collectEnvironment():
        environment = {}
        environment["Slicer version"] = f"{slicer.app.applicationVersion} (revision {slicer.app.revision})"
        environment["Slicer executable"] = slicer.app.applicationFilePath()
        environment["Operating system"] = f"{platform.system()} {platform.release()} ({platform.version()})"
        environment["SlicerHeartPrivate version"] = gitDescription()
        environment["Vector field display node available"] = "yes" if isVectorFieldDisplayAvailable() else "no"
        versions = [f"Python {platform.python_version()}", f"VTK {vtk.vtkVersion.GetVTKVersion()}", f"numpy {np.__version__}"]
        for packageName in ["pydicom", "scipy", "nrrd"]:
            try:
                package = __import__(packageName)
                versions.append(f"{packageName} {package.__version__}")
            except ImportError:
                versions.append(f"{packageName} not installed")
        environment["Python packages"] = ", ".join(versions)
        realDataPath = environmentValue(REAL_DATA_ENV_VARIABLE)
        if realDataPath and os.path.isdir(realDataPath):
            environment["Anonymized 4D flow data set"] = f"available ({REAL_DATA_ENV_VARIABLE})"
        else:
            environment["Anonymized 4D flow data set"] = f"not available (set {REAL_DATA_ENV_VARIABLE} in environment or .env.local)"
        return environment

    # Test lifecycle

    def startTest(self, name, title, description):
        self.currentTest = {
            "name": name, "title": title, "description": description,
            "status": None, "durationSec": 0.0, "items": [], "checks": [], "failedChecks": [], "error": None,
        }
        self.tests.append(self.currentTest)
        logging.info(f"===== {self.suiteName}: {title} ({name}) =====")

    def endTest(self, status, error=None, durationSec=0.0):
        self.currentTest["status"] = status
        self.currentTest["error"] = error
        self.currentTest["durationSec"] = durationSec
        logging.info(f"===== {self.currentTest['name']}: {status} ({durationSec:.1f}s) =====")
        self.currentTest = None
        self.write()

    # Content

    def text(self, text):
        """Add a paragraph (markdown) to the current test."""
        self.currentTest["items"].append({"type": "text", "text": text})

    def table(self, headers, rows, caption=None):
        """Add a table to the current test."""
        self.currentTest["items"].append({"type": "table", "headers": list(headers),
            "rows": [[self._formatValue(value) for value in row] for row in rows], "caption": caption})

    @staticmethod
    def _formatValue(value):
        if isinstance(value, (bool, np.bool_)):
            return "yes" if value else "no"
        if isinstance(value, (float, np.floating)):
            if value != 0 and (abs(value) >= 1e5 or abs(value) < 1e-3):
                return f"{value:.3e}"
            return f"{value:.4g}"
        if isinstance(value, (list, tuple, np.ndarray)):
            return "[" + ", ".join(TestReport._formatValue(v) for v in value) + "]"
        return str(value)

    # Checks: they are recorded in a table and all failures are reported at the end of the test

    def checkClose(self, label, measured, expected, rtol=0.0, atol=0.0, unit=""):
        """Check that measured is within tolerance of expected (|measured-expected| <= atol + rtol*|expected|)."""
        measured = float(measured)
        expected = float(expected)
        tolerance = atol + rtol * abs(expected)
        difference = measured - expected
        passed = bool(abs(difference) <= tolerance) and not math.isnan(measured)
        relativeError = (f"{100.0 * difference / expected:+.2f}%" if expected != 0 else "-")
        toleranceText = []
        if rtol:
            toleranceText.append(f"±{100 * rtol:g}%")
        if atol:
            toleranceText.append(f"±{atol:g}{(' ' + unit) if unit else ''}")
        self._addCheck(label, self._formatValue(measured) + (f" {unit}" if unit else ""),
            self._formatValue(expected) + (f" {unit}" if unit else ""),
            f"{relativeError} (tolerance {' + '.join(toleranceText) or '0'})", passed)
        return passed

    def checkRange(self, label, measured, minimum, maximum, unit=""):
        """Check that minimum <= measured <= maximum (plausibility check)."""
        measured = float(measured)
        passed = bool(minimum <= measured <= maximum)
        self._addCheck(label, self._formatValue(measured) + (f" {unit}" if unit else ""),
            f"{self._formatValue(minimum)} ... {self._formatValue(maximum)}{(' ' + unit) if unit else ''}", "", passed)
        return passed

    def checkTrue(self, label, condition, measured="", expected=""):
        """Check that a condition is true."""
        passed = bool(condition)
        self._addCheck(label, self._formatValue(measured) if measured != "" else ("yes" if passed else "no"),
            expected if expected != "" else "yes", "", passed)
        return passed

    def checkEqual(self, label, measured, expected):
        passed = bool(measured == expected)
        self._addCheck(label, self._formatValue(measured), self._formatValue(expected), "", passed)
        return passed

    def _addCheck(self, label, measured, expected, difference, passed):
        check = {"label": label, "measured": measured, "expected": expected, "difference": difference, "passed": passed}
        self.currentTest["checks"].append(check)
        if not passed:
            self.currentTest["failedChecks"].append(check)
            logging.error(f"Check failed: {label}: measured {measured}, expected {expected} {difference}")

    def failedChecksMessage(self):
        failedChecks = self.currentTest["failedChecks"]
        if not failedChecks:
            return None
        return f"{len(failedChecks)} check(s) failed:\n" + "\n".join(
            f"  - {c['label']}: measured {c['measured']}, expected {c['expected']} {c['difference']}" for c in failedChecks)

    # Screenshots

    def screenshot(self, caption, widget=None, kind="layout"):
        """Capture an image and add it to the current test.
        kind: "layout" (all views in the view layout), "window" (application main window), or "widget" (widget must be specified).
        """
        slicer.app.processEvents()
        try:
            slicer.util.forceRenderAllViews()
        except AttributeError:
            pass
        slicer.app.processEvents()
        if widget is not None:
            pixmap = widget.grab()
        elif kind == "window":
            pixmap = slicer.util.mainWindow().grab()
        else:
            pixmap = slicer.app.layoutManager().viewport().grab()
        self.imageCounter += 1
        testName = self.currentTest["name"] if self.currentTest else "suite"
        fileName = f"{self.imageCounter:03d}_{testName}.png"
        if not pixmap.save(os.path.join(self.imagesDir, fileName)):
            logging.warning(f"Failed to save screenshot {fileName}")
            return
        self.currentTest["items"].append({"type": "image", "path": f"images/{fileName}", "caption": caption})

    # Output

    def summary(self):
        counts = {"PASSED": 0, "FAILED": 0, "SKIPPED": 0}
        for test in self.tests:
            if test["status"] in counts:
                counts[test["status"]] += 1
        return counts

    def write(self):
        counts = self.summary()
        lines = []
        lines.append(f"# {self.title}")
        lines.append("")
        lines.append(self.description)
        lines.append("")
        lines.append(f"Report generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                     f" (test run started {self.startTime.strftime('%Y-%m-%d %H:%M:%S')})")
        lines.append("")
        lines.append("## Environment")
        lines.append("")
        lines.append("| Item | Value |")
        lines.append("|---|---|")
        for key, value in self.environment.items():
            lines.append(f"| {key} | {self._escape(value)} |")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.append(f"**{counts['PASSED']} passed, {counts['FAILED']} failed, {counts['SKIPPED']} skipped** (of {len(self.tests)} tests run)")
        lines.append("")
        lines.append("| Test | Status | Duration | Checks |")
        lines.append("|---|---|---|---|")
        for test in self.tests:
            status = test["status"] or "RUNNING"
            icon = self.STATUS_ICONS.get(status, "⏳")
            numberOfChecks = len(test["checks"])
            numberOfFailedChecks = len(test["failedChecks"])
            checks = f"{numberOfChecks - numberOfFailedChecks}/{numberOfChecks} passed" if numberOfChecks else ""
            anchor = test["name"].lower()
            lines.append(f"| [{self._escape(test['title'])}](#{anchor}) | {icon} {status} | {test['durationSec']:.1f} s | {checks} |")
        lines.append("")
        for test in self.tests:
            status = test["status"] or "RUNNING"
            lines.append(f'<a id="{test["name"].lower()}"></a>')
            lines.append("")
            lines.append(f"## {self.STATUS_ICONS.get(status, '⏳')} {test['title']}")
            lines.append("")
            lines.append(f"`{test['name']}` - **{status}** in {test['durationSec']:.1f} s")
            lines.append("")
            if test["description"]:
                lines.append(test["description"])
                lines.append("")
            if test["error"]:
                lines.append("<details><summary>Error details</summary>" if status == "FAILED" else "<details><summary>Reason</summary>")
                lines.append("")
                lines.append("```")
                lines.append(test["error"].rstrip())
                lines.append("```")
                lines.append("")
                lines.append("</details>")
                lines.append("")
            for item in test["items"]:
                if item["type"] == "text":
                    lines.append(item["text"])
                    lines.append("")
                elif item["type"] == "table":
                    if item["caption"]:
                        lines.append(f"*{item['caption']}*")
                        lines.append("")
                    lines.extend(self._markdownTable(item["headers"], item["rows"]))
                    lines.append("")
                elif item["type"] == "image":
                    lines.append(f"![{self._escape(item['caption'])}]({item['path']})")
                    lines.append("")
                    lines.append(f"*{item['caption']}*")
                    lines.append("")
            if test["checks"]:
                lines.append("**Checks**")
                lines.append("")
                rows = [[("✅" if c["passed"] else "❌"), c["label"], c["measured"], c["expected"], c["difference"]] for c in test["checks"]]
                lines.extend(self._markdownTable(["", "Check", "Measured", "Expected", "Difference"], rows))
                lines.append("")

        with open(os.path.join(self.outputDir, "report.md"), "w", encoding="utf-8") as reportFile:
            reportFile.write("\n".join(lines) + "\n")

        results = {
            "suite": self.suiteName,
            "title": self.title,
            "environment": self.environment,
            "startTime": self.startTime.isoformat(),
            "summary": counts,
            "tests": [{"name": t["name"], "title": t["title"], "status": t["status"], "durationSec": t["durationSec"],
                       "numberOfChecks": len(t["checks"]), "failedChecks": t["failedChecks"],
                       "error": (t["error"] or "").strip().splitlines()[-1] if t["error"] else None} for t in self.tests],
        }
        with open(os.path.join(self.outputDir, "results.json"), "w", encoding="utf-8") as resultsFile:
            json.dump(results, resultsFile, indent=2)

    @staticmethod
    def _escape(text):
        return str(text).replace("|", "\\|").replace("\n", " ")

    @staticmethod
    def _markdownTable(headers, rows):
        lines = ["| " + " | ".join(TestReport._escape(h) for h in headers) + " |",
                 "|" + "---|" * len(headers)]
        for row in rows:
            lines.append("| " + " | ".join(TestReport._escape(v) for v in row) + " |")
        return lines


def reportedTest(title, description=""):
    """Decorator for test methods of a FeatureTestCase: records status, duration, and checks in the report.
    Failed checks (report.check...) make the test fail at the end, so all checks of a test are always evaluated.
    """
    def decorator(testMethod):
        @functools.wraps(testMethod)
        def wrapper(self):
            report = self.report
            report.startTest(testMethod.__name__, title, description)
            startTime = time.time()
            try:
                testMethod(self)
                failedChecksMessage = report.failedChecksMessage()
                if failedChecksMessage:
                    raise AssertionError(failedChecksMessage)
            except unittest.SkipTest as e:
                report.endTest("SKIPPED", str(e), time.time() - startTime)
                raise
            except Exception:
                errorText = traceback.format_exc()
                try:
                    report.screenshot("Application window when the test failed", kind="window")
                except Exception:
                    pass
                report.endTest("FAILED", errorText, time.time() - startTime)
                raise
            else:
                report.endTest("PASSED", None, time.time() - startTime)
        return wrapper
    return decorator


class FeatureTestCase(unittest.TestCase):
    """Base class for feature tests that write a markdown report.
    Derived classes must define REPORT_SUITE_NAME, REPORT_TITLE, REPORT_DESCRIPTION.
    """

    REPORT_SUITE_NAME = "FeatureTest"
    REPORT_TITLE = "Feature test"
    REPORT_DESCRIPTION = ""

    report = None

    @classmethod
    def setUpClass(cls):
        cls.report = TestReport(cls.REPORT_SUITE_NAME, cls.REPORT_TITLE, cls.REPORT_DESCRIPTION)
        # Write Python stack trace if the application crashes (to find the test step that caused it)
        import faulthandler
        cls._crashLogFile = open(os.path.join(cls.report.outputDir, "crash-traceback.txt"), "w")
        faulthandler.enable(cls._crashLogFile, all_threads=False)
        mainWindow = slicer.util.mainWindow()
        if mainWindow:
            mainWindow.resize(1600, 1000)

    @classmethod
    def tearDownClass(cls):
        import faulthandler
        faulthandler.disable()
        cls._crashLogFile.close()
        cls.report.write()
        logging.info(f"Test report written to {os.path.join(cls.report.outputDir, 'report.md')}")

    # If a test runs longer than this then the Python stack is written to crash-traceback.txt (to find where it hangs)
    HANG_TIMEOUT_SEC = 600

    def setUp(self):
        import faulthandler
        faulthandler.dump_traceback_later(self.HANG_TIMEOUT_SEC, repeat=False, file=self._crashLogFile)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        slicer.mrmlScene.Clear()
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)


#
# View helpers
#

def showVolumeInSliceViews(volumeNode, centerRas=None, foreground=None, foregroundOpacity=0.5):
    """Show a volume in all slice views and optionally center the slice views at a point."""
    slicer.util.setSliceViewerLayers(background=volumeNode, foreground=foreground, foregroundOpacity=foregroundOpacity, fit=True)
    if centerRas is not None:
        for sliceViewName in slicer.app.layoutManager().sliceViewNames():
            sliceNode = slicer.app.layoutManager().sliceWidget(sliceViewName).mrmlSliceNode()
            sliceNode.JumpSliceByCentering(*centerRas)


def reset3DView():
    threeDWidget = slicer.app.layoutManager().threeDWidget(0)
    threeDWidget.threeDView().resetFocalPoint()
    threeDWidget.threeDView().resetCamera()


def selectSequenceItem(proxyNode, itemNumber):
    browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(proxyNode)
    browserNode.SetSelectedItemNumber(itemNumber)
    slicer.app.processEvents()


#
# Analytic flow phantom
#

class FlowPhantom:
    """Analytic pulsatile Poiseuille flow in a straight cylindrical vessel, imaged with an oblique 3D volume.

    Velocity: v(p, t) = vmax(t) * (1 - r^2/R^2) * axis, for points p within radius R of the vessel centerline.
    vmax(t) is a half-sine systolic peak followed by a smaller half-sine backflow (regurgitation) and diastasis.
    Analytic flow rate through a plane perpendicular to the vessel: Q(t) = vmax(t)/2 * pi * R^2.
    """

    def __init__(self,
                 dims=(40, 40, 32),
                 spacingMm=(1.5, 1.5, 2.0),
                 volumeRotationDeg=20.0,
                 volumeRotationAxis=(1.0, 1.0, 0.0),
                 centerRas=(5.0, -10.0, 20.0),
                 vesselAxis=(0.25, 0.3, 1.0),
                 vesselRadiusMm=10.0,
                 peakVelocityMPerSec=1.0,
                 backflowFraction=0.2,
                 numberOfFrames=12,
                 frameIntervalMs=60.0,
                 firstFrameTimeMs=0.0,
                 systoleDurationMs=360.0,
                 backflowDurationMs=180.0,
                 nominalIntervalMs=750.0,
                 tissueRadiusMm=24.0):
        self.dims = tuple(int(d) for d in dims)  # I, J, K
        self.spacingMm = np.array(spacingMm, dtype=float)
        self.centerRas = np.array(centerRas, dtype=float)
        self.vesselAxis = np.array(vesselAxis, dtype=float) / np.linalg.norm(vesselAxis)
        self.vesselRadiusMm = float(vesselRadiusMm)
        self.peakVelocityMPerSec = float(peakVelocityMPerSec)
        self.backflowFraction = float(backflowFraction)
        self.numberOfFrames = int(numberOfFrames)
        self.frameTimesMs = [firstFrameTimeMs + frameIntervalMs * i for i in range(self.numberOfFrames)]
        self.systoleDurationMs = float(systoleDurationMs)
        self.backflowDurationMs = float(backflowDurationMs)
        self.nominalIntervalMs = float(nominalIntervalMs)
        self.tissueRadiusMm = float(tissueRadiusMm)

        # Volume orientation: rotation around an oblique axis
        rotation = vtk.vtkTransform()
        rotation.RotateWXYZ(volumeRotationDeg, *volumeRotationAxis)
        self.directionMatrix = np.array([[rotation.GetMatrix().GetElement(r, c) for c in range(3)] for r in range(3)])
        self.originRas = self.centerRas - self.directionMatrix @ (self.spacingMm * (np.array(self.dims) - 1) / 2.0)

        # Voxel center positions (k, j, i, 3) in RAS
        k, j, i = np.indices((self.dims[2], self.dims[1], self.dims[0]))
        ijk = np.stack([i, j, k], axis=-1).astype(float) * self.spacingMm
        self.voxelPositionsRas = self.originRas + ijk @ self.directionMatrix.T
        self.radialDistanceMm = self.radialDistance(self.voxelPositionsRas)
        self.insideVessel = self.radialDistanceMm < self.vesselRadiusMm

    # Geometry

    def ijkToRasMatrix(self):
        matrix = vtk.vtkMatrix4x4()
        for r in range(3):
            for c in range(3):
                matrix.SetElement(r, c, self.directionMatrix[r, c] * self.spacingMm[c])
            matrix.SetElement(r, 3, self.originRas[r])
        return matrix

    def radialDistance(self, pointsRas):
        relative = pointsRas - self.centerRas
        axial = relative @ self.vesselAxis
        radial = relative - axial[..., np.newaxis] * self.vesselAxis
        return np.linalg.norm(radial, axis=-1)

    def perpendicularAxes(self):
        """Two unit vectors that are perpendicular to the vessel axis and each other."""
        helper = np.array([1.0, 0.0, 0.0]) if abs(self.vesselAxis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis1 = np.cross(self.vesselAxis, helper)
        axis1 /= np.linalg.norm(axis1)
        axis2 = np.cross(self.vesselAxis, axis1)
        return axis1, axis2

    # Flow

    def maxVelocity(self, frameIndex):
        """Centerline velocity (m/s) along the vessel axis at the given frame. Negative during backflow."""
        t = self.frameTimesMs[frameIndex] - self.frameTimesMs[0]
        if t <= self.systoleDurationMs:
            return self.peakVelocityMPerSec * math.sin(math.pi * t / self.systoleDurationMs)
        t -= self.systoleDurationMs
        if t <= self.backflowDurationMs:
            return -self.backflowFraction * self.peakVelocityMPerSec * math.sin(math.pi * t / self.backflowDurationMs)
        return 0.0

    def velocityAt(self, pointsRas, frameIndex):
        """Velocity vectors (m/s, RAS) at the given points (..., 3)."""
        r = self.radialDistance(pointsRas)
        profile = np.clip(1.0 - (r / self.vesselRadiusMm) ** 2, 0.0, None)
        return (self.maxVelocity(frameIndex) * profile)[..., np.newaxis] * self.vesselAxis

    def velocityVolumeArray(self, frameIndex):
        """Velocity vectors on the voxel grid (k, j, i, 3), m/s, RAS."""
        return self.velocityAt(self.voxelPositionsRas, frameIndex).astype(np.float32)

    def magnitudeVolumeArray(self):
        """Magnitude image (k, j, i): bright vessel, medium tissue around the vessel, dark (noise level) background."""
        distanceFromCenter = np.linalg.norm(self.voxelPositionsRas - self.centerRas, axis=-1)
        magnitude = np.full(self.radialDistanceMm.shape, 3, dtype=np.int16)
        magnitude[distanceFromCenter < self.tissueRadiusMm] = 100
        magnitude[self.insideVessel] = 200
        return magnitude

    def stationaryTissueMask(self):
        distanceFromCenter = np.linalg.norm(self.voxelPositionsRas - self.centerRas, axis=-1)
        return np.logical_and(distanceFromCenter < self.tissueRadiusMm, self.radialDistanceMm > self.vesselRadiusMm + 2.0)

    def componentVolumeArray(self, frameIndex, axis, vencCmPerSec, invertToRasDirection, phaseOffset=None, wrap=True):
        """Raw phase values (k, j, i) of a velocity component image, as stored by Siemens CS 4D flow
        (range [-4096, 4096), velocity encoding vencCmPerSec maps to 4096).
        phaseOffset: optional additive background phase error (raw units), same shape as the image.
        """
        velocityCmPerSec = self.velocityVolumeArray(frameIndex)[..., axis] * 100.0
        if invertToRasDirection:
            velocityCmPerSec = -velocityCmPerSec
        raw = velocityCmPerSec / vencCmPerSec * PHASE_MAX_VALUE
        if phaseOffset is not None:
            raw = raw + phaseOffset
        if wrap:
            raw = np.mod(raw + PHASE_MAX_VALUE, 2 * PHASE_MAX_VALUE) - PHASE_MAX_VALUE
        return np.round(raw).astype(np.int16)

    def numberOfWrappedVoxels(self, vencCmPerSec):
        """Number of voxels (over all frames and components) where the velocity exceeds the velocity encoding."""
        count = 0
        for frameIndex in range(self.numberOfFrames):
            velocityCmPerSec = np.abs(self.velocityVolumeArray(frameIndex) * 100.0)
            count += int(np.count_nonzero(velocityCmPerSec >= vencCmPerSec))
        return count

    def linearPhaseOffset(self, coefficients=(3.0, -2.0, 4.0), constant=-50.0):
        """Linear background phase offset (raw units) as a function of voxel index (k, j, i)."""
        k, j, i = np.indices((self.dims[2], self.dims[1], self.dims[0]))
        return coefficients[0] * k + coefficients[1] * j + coefficients[2] * i + constant

    def quadraticPhaseOffset(self):
        k, j, i = np.indices((self.dims[2], self.dims[1], self.dims[0]))
        kc, jc, ic = (np.array([self.dims[2], self.dims[1], self.dims[0]]) - 1) / 2.0
        return 0.4 * (i - ic) ** 2 - 0.3 * (j - jc) ** 2 + 0.2 * (k - kc) * (i - ic) + 2.0 * k - 30.0

    # Analytic reference values

    def expectedFlowRateMlPerSec(self, frameIndex, speedThresholdMPerSec=0.0):
        """Flow rate through a plane perpendicular to the vessel, only counting points with speed above the threshold."""
        vmax = abs(self.maxVelocity(frameIndex))
        radius = self.vesselRadiusMm
        if vmax <= speedThresholdMPerSec:
            return 0.0
        cutoffRadius = radius * math.sqrt(1.0 - speedThresholdMPerSec / vmax) if speedThresholdMPerSec > 0 else radius
        flow = math.pi * vmax * (cutoffRadius ** 2 - cutoffRadius ** 4 / (2 * radius ** 2))
        return math.copysign(flow, self.maxVelocity(frameIndex))

    def expectedAreaMm2(self, frameIndex=None, speedThresholdMPerSec=0.0):
        radius = self.vesselRadiusMm
        if frameIndex is None or speedThresholdMPerSec <= 0:
            return math.pi * radius ** 2
        vmax = abs(self.maxVelocity(frameIndex))
        if vmax <= speedThresholdMPerSec:
            return 0.0
        return math.pi * radius ** 2 * (1.0 - speedThresholdMPerSec / vmax)

    def expectedMeanSpeedMPerSec(self, frameIndex):
        """Area-averaged speed over the vessel lumen (Poiseuille: half of the centerline velocity)."""
        return abs(self.maxVelocity(frameIndex)) / 2.0

    def expectedForwardBackwardVolumeMl(self, flowRates=None):
        """Forward (positive) and backward (negative) volume from the flow rate curve sampled at the frame times,
        using trapezoid rule with splitting at zero crossings (independent implementation)."""
        if flowRates is None:
            flowRates = [self.expectedFlowRateMlPerSec(i) for i in range(self.numberOfFrames)]
        timesSec = [t / 1000.0 for t in self.frameTimesMs]
        forward = 0.0
        backward = 0.0
        for i in range(len(timesSec) - 1):
            x0, x1, y0, y1 = timesSec[i], timesSec[i + 1], flowRates[i], flowRates[i + 1]
            if y0 >= 0 and y1 >= 0:
                forward += (y0 + y1) / 2 * (x1 - x0)
            elif y0 <= 0 and y1 <= 0:
                backward += (y0 + y1) / 2 * (x1 - x0)
            else:
                xz = x0 + (x1 - x0) * y0 / (y0 - y1)
                for ya, xa, xb in [(y0, x0, xz), (y1, xz, x1)]:
                    area = ya / 2 * (xb - xa)
                    if area > 0:
                        forward += area
                    else:
                        backward += area
        return forward, backward

    def peakFrameIndex(self):
        return int(np.argmax([self.maxVelocity(i) for i in range(self.numberOfFrames)]))

    def backflowFrameIndex(self):
        return int(np.argmin([self.maxVelocity(i) for i in range(self.numberOfFrames)]))

    def heartRateBpm(self):
        return 60000.0 / self.nominalIntervalMs

    # Scene generation

    def createVolumeNode(self, voxelArray, name, className="vtkMRMLScalarVolumeNode", addToScene=False):
        if addToScene:
            volumeNode = slicer.mrmlScene.AddNewNodeByClass(className, name)
        else:
            volumeNode = slicer.mrmlScene.CreateNodeByClass(className)
            volumeNode.UnRegister(None)
            volumeNode.SetName(name)
        volumeNode.SetIJKToRASMatrix(self.ijkToRasMatrix())
        slicer.util.updateVolumeFromArray(volumeNode, voxelArray)
        return volumeNode

    def createVolumeSequence(self, name, frameArrays, multiVolumeAttributes=True):
        """Create a volume sequence with its own sequence browser (as the DICOM importer does).
        Returns (proxyVolumeNode, sequenceNode, browserNode)."""
        sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
        for frameIndex, frameArray in enumerate(frameArrays):
            volumeNode = self.createVolumeNode(frameArray, name)
            sequenceNode.SetDataNodeAtValue(volumeNode, str(frameIndex))
        if multiVolumeAttributes:
            # Same attributes as set by MultiVolumeImporter when loading 4D DICOM by trigger time
            sequenceNode.SetAttribute("MultiVolume.FrameIdentifyingDICOMTagName", "TriggerTime")
            sequenceNode.SetAttribute("MultiVolume.FrameIdentifyingDICOMTagUnits", "ms")
            sequenceNode.SetAttribute("MultiVolume.FrameLabels", ",".join(f"{t:g}" for t in self.frameTimesMs))
            sequenceNode.SetAttribute("MultiVolume.NumberOfFrames", str(self.numberOfFrames))
        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", name + " browser")
        browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
        proxyNode = browserNode.GetProxyNode(sequenceNode)
        proxyNode.CreateDefaultDisplayNodes()
        return proxyNode, sequenceNode, browserNode

    def createComponentImagesInScene(self, vencCmPerSec=150.0, directionConfiguration=DIRECTION_CONFIGURATION_AXIAL,
                                     phaseOffset=None, wrap=True, withHeartRate=True):
        """Create magnitude and component volume sequences in the scene, with the same attributes that
        Import4DFlowLogic sets when it finds the images in the DICOM database.
        Returns a volume node set dictionary (same format as Import4DFlowLogic.findVolumeNodeSets values).
        """
        magnitudeArray = self.magnitudeVolumeArray()
        magnitudeVolumeNode, magnitudeSequenceNode, _ = self.createVolumeSequence(
            "Magnitude", [magnitudeArray] * self.numberOfFrames)
        magnitudeSequenceNode.SetAttribute("SlicerHeart.directionCode", "magnitude")
        if withHeartRate:
            magnitudeSequenceNode.SetAttribute("SlicerHeart.heartRateBpm", str(self.heartRateBpm()))
        componentVolumeNodes = []
        invertToRasDirections = []
        for axis, (directionCode, invertToRasDirection) in enumerate(directionConfiguration):
            frames = [self.componentVolumeArray(frameIndex, axis, vencCmPerSec, invertToRasDirection, phaseOffset, wrap)
                      for frameIndex in range(self.numberOfFrames)]
            componentVolumeNode, componentSequenceNode, _ = self.createVolumeSequence(f"Phase {directionCode}", frames)
            componentSequenceNode.SetAttribute("SlicerHeart.directionCode", directionCode)
            componentSequenceNode.SetAttribute("SlicerHeart.vencCmPerSec", str(vencCmPerSec))
            componentSequenceNode.SetAttribute("SlicerHeart.maxValue", str(PHASE_MAX_VALUE))
            componentVolumeNodes.append(componentVolumeNode)
            invertToRasDirections.append(invertToRasDirection)
        return {
            "name": "Phantom",
            "componentVolumeNodes": componentVolumeNodes,
            "componentVolumeNodesInvertToRasDirection": invertToRasDirections,
            "magnitudeVolumeNode": magnitudeVolumeNode,
        }

    def createVesselSegmentation(self, referenceVolumeNode, radiusMm=None, name="Vessel"):
        """Segmentation with a single segment that contains the vessel lumen. Returns (segmentationNode, segmentId)."""
        if radiusMm is None:
            radiusMm = self.vesselRadiusMm
        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "__tmp__vessel labelmap")
        labelmapNode.SetIJKToRASMatrix(self.ijkToRasMatrix())
        slicer.util.updateVolumeFromArray(labelmapNode, (self.radialDistanceMm < radiusMm).astype(np.uint8))
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", name)
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(referenceVolumeNode)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode)
        slicer.mrmlScene.RemoveNode(labelmapNode)
        segmentationNode.CreateDefaultDisplayNodes()
        segmentId = segmentationNode.GetSegmentation().GetNthSegmentID(0)
        segmentationNode.GetSegmentation().GetSegment(segmentId).SetName(name)
        return segmentationNode, segmentId

    def createMeasurementPlane(self, tiltDeg=0.0, sizeMm=36.0, name="Plane"):
        """Markups plane through the vessel center. tiltDeg=0: perpendicular to the vessel."""
        axis1, axis2 = self.perpendicularAxes()
        tilt = math.radians(tiltDeg)
        normal = math.cos(tilt) * self.vesselAxis + math.sin(tilt) * axis1
        planeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", name)
        planeNode.SetPlaneType(planeNode.PlaneTypePointNormal)
        planeNode.AddControlPointWorld(vtk.vtkVector3d(*self.centerRas))
        planeNode.SetNormalWorld(normal)
        planeNode.SetSizeMode(planeNode.SizeModeAbsolute)
        planeNode.SetSize(sizeMm, sizeMm)
        return planeNode

    def createFlowModelMesh(self, frameIndex, velocityArrayName="V", lengthMm=40.0, resolutionMm=1.0):
        """CFD-like flow field: unstructured grid of the vessel lumen (a segment of the cylinder around the center)
        with a velocity point data array."""
        halfSize = max(lengthMm / 2, self.vesselRadiusMm) + 2 * resolutionMm
        imageData = vtk.vtkImageData()
        numberOfPoints = int(2 * halfSize / resolutionMm) + 1
        imageData.SetDimensions(numberOfPoints, numberOfPoints, numberOfPoints)
        imageData.SetSpacing(resolutionMm, resolutionMm, resolutionMm)
        imageData.SetOrigin(*(self.centerRas - halfSize))
        # Point positions in VTK point order (x index changes fastest)
        z, y, x = np.indices((numberOfPoints, numberOfPoints, numberOfPoints)).reshape(3, -1)
        points = np.stack([x, y, z], axis=-1) * resolutionMm + (self.centerRas - halfSize)
        velocity = self.velocityAt(points, frameIndex).astype(np.float32)
        relative = points - self.centerRas
        axial = np.abs(relative @ self.vesselAxis)
        inside = np.logical_and(self.radialDistance(points) <= self.vesselRadiusMm + 0.5 * resolutionMm, axial <= lengthMm / 2)
        velocityArray = vtk.util.numpy_support.numpy_to_vtk(velocity, deep=True)
        velocityArray.SetName(velocityArrayName)
        imageData.GetPointData().AddArray(velocityArray)
        insideArray = vtk.util.numpy_support.numpy_to_vtk(inside.astype(np.float32), deep=True)
        insideArray.SetName("inside")
        imageData.GetPointData().SetScalars(insideArray)
        threshold = vtk.vtkThreshold()
        threshold.SetInputData(imageData)
        threshold.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "inside")
        threshold.SetLowerThreshold(0.5)
        threshold.SetUpperThreshold(1.5)
        threshold.SetThresholdFunction(vtk.vtkThreshold.THRESHOLD_BETWEEN)
        threshold.AllScalarsOff()  # keep cells that have at least one point inside
        # Split the axis-aligned voxel cells into tetrahedra, as in typical CFD meshes
        # (voxel cells become invalid if the mesh is rotated by a parent transform)
        tetrahedralize = vtk.vtkDataSetTriangleFilter()
        tetrahedralize.SetInputConnection(threshold.GetOutputPort())
        tetrahedralize.Update()
        mesh = vtk.vtkUnstructuredGrid()
        mesh.DeepCopy(tetrahedralize.GetOutput())
        mesh.GetPointData().RemoveArray("inside")
        return mesh

    def createFlowModelSequence(self, velocityArrayName="V", name="CFD flow"):
        """Sequence of CFD-like flow field models (one per frame). Returns (proxyModelNode, sequenceNode, browserNode)."""
        sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
        sequenceNode.SetIndexName("time")
        sequenceNode.SetIndexUnit("ms")
        for frameIndex in range(self.numberOfFrames):
            modelNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLModelNode")
            modelNode.UnRegister(None)
            modelNode.SetName(name)
            modelNode.SetAndObserveMesh(self.createFlowModelMesh(frameIndex, velocityArrayName))
            sequenceNode.SetDataNodeAtValue(modelNode, f"{self.frameTimesMs[frameIndex]:g}")
        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", name + " browser")
        browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
        proxyNode = browserNode.GetProxyNode(sequenceNode)
        proxyNode.CreateDefaultDisplayNodes()
        return proxyNode, sequenceNode, browserNode

    # DICOM

    def writeDicomSeries(self, outputDir, vencCmPerSec=150.0, directionConfiguration=DIRECTION_CONFIGURATION_AXIAL,
                         variant="avanto", patientName="Phantom^Flow", studyDate="20240102", wrap=True):
        """Write magnitude and phase component series as Siemens CS 4D flow-like DICOM files (one file per slice and frame).

        variant:
        - "avanto": speed and direction code in private tag (0051,1014) with explicit VR (LO), for example 'v150_through'
        - "avantofit": speed and direction code in private tag (0021,1129) as raw bytes (VR UN), as in Siemens Avanto Fit
        - "sequencename": no private tags, speed and direction is only in SequenceName, for example 'fl3d1_v150in'

        Returns list of series instance UIDs: [magnitude, component 0, component 1, component 2].
        """
        import pydicom
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

        os.makedirs(outputDir, exist_ok=True)
        studyInstanceUID = generate_uid()
        frameOfReferenceUID = generate_uid()
        rasToLps = np.diag([-1.0, -1.0, 1.0])
        directionLps = rasToLps @ self.directionMatrix
        originLps = rasToLps @ self.originRas
        rowDirection = directionLps[:, 0]  # direction of increasing column index (I axis)
        columnDirection = directionLps[:, 1]  # direction of increasing row index (J axis)
        sliceDirection = directionLps[:, 2]

        seriesDefinitions = [("magnitude", None, False)]
        for axis, (directionCode, invertToRasDirection) in enumerate(directionConfiguration):
            seriesDefinitions.append((directionCode, axis, invertToRasDirection))

        seriesUIDs = []
        magnitudeArray = self.magnitudeVolumeArray()
        for seriesIndex, (directionCode, axis, invertToRasDirection) in enumerate(seriesDefinitions):
            seriesInstanceUID = generate_uid()
            seriesUIDs.append(seriesInstanceUID)
            seriesDir = os.path.join(outputDir, f"series{seriesIndex}")
            os.makedirs(seriesDir, exist_ok=True)
            vencText = f"{vencCmPerSec:g}"
            for frameIndex in range(self.numberOfFrames):
                if axis is None:
                    voxels = magnitudeArray.astype(np.int32)
                    storedValues = voxels
                else:
                    voxels = self.componentVolumeArray(frameIndex, axis, vencCmPerSec, invertToRasDirection, wrap=wrap).astype(np.int32)
                    # Stored values are in [0, 4095], rescaled to [-4096, 4094] with slope 2 and intercept -4096
                    storedValues = np.clip(np.round((voxels + PHASE_MAX_VALUE) / 2.0), 0, 4095).astype(np.int32)
                for sliceIndex in range(self.dims[2]):
                    sopInstanceUID = generate_uid()
                    ds = Dataset()
                    ds.PatientName = patientName
                    ds.PatientID = "FlowPhantom"
                    ds.PatientBirthDate = "19700101"
                    ds.PatientSex = "O"
                    ds.StudyInstanceUID = studyInstanceUID
                    ds.StudyDate = studyDate
                    ds.StudyTime = "120000"
                    ds.StudyID = "1"
                    ds.AccessionNumber = "PHANTOM1"
                    ds.SeriesInstanceUID = seriesInstanceUID
                    ds.SeriesNumber = 50 + seriesIndex
                    ds.SeriesDescription = f"4D flow phantom {directionCode}"
                    ds.FrameOfReferenceUID = frameOfReferenceUID
                    ds.SOPInstanceUID = sopInstanceUID
                    ds.SOPClassUID = MRImageStorage
                    ds.Modality = "MR"
                    ds.Manufacturer = "SIEMENS"
                    ds.ManufacturerModelName = "Avanto_fit" if variant == "avantofit" else "Avanto"
                    ds.InstanceNumber = frameIndex * self.dims[2] + sliceIndex + 1
                    ds.AcquisitionNumber = 1
                    ds.TriggerTime = f"{self.frameTimesMs[frameIndex]:.6f}"
                    ds.NominalInterval = f"{self.nominalIntervalMs:g}"
                    ds.RepetitionTime = "40"
                    ds.EchoTime = "2.3"
                    ds.FlipAngle = "15"
                    ds.MagneticFieldStrength = "1.5"
                    if axis is None:
                        ds.SequenceName = "fl3d1r2"
                        ds.ImageType = ["ORIGINAL", "PRIMARY", "M", "RETRO", "NORM", "DIS2D"]
                    else:
                        ds.SequenceName = f"fl3d1_v{vencText}{SEQUENCE_NAME_DIRECTION_CODES[directionCode]}"
                        ds.ImageType = ["DERIVED", "PRIMARY", "P", "RETRO", "DIS2D"]
                        ds.RescaleSlope = "2"
                        ds.RescaleIntercept = "-4096"
                        ds.RescaleType = "US"
                        speedAndDirectionCode = f"v{vencText}_{directionCode}"
                        if variant == "avanto":
                            ds.add_new((0x0051, 0x0010), "LO", "SIEMENS MR HEADER")
                            ds.add_new((0x0051, 0x1014), "LO", speedAndDirectionCode)
                        elif variant == "avantofit":
                            ds.add_new((0x0021, 0x0010), "LO", "SIEMENS MR SDS 01")
                            value = (speedAndDirectionCode + " ").encode()  # Siemens pads to even length with a space
                            ds.add_new((0x0021, 0x1129), "UN", value)
                        elif variant != "sequencename":
                            raise ValueError(f"Unknown DICOM variant: {variant}")
                    position = originLps + sliceDirection * self.spacingMm[2] * sliceIndex
                    ds.ImagePositionPatient = [f"{v:.6f}" for v in position]
                    ds.ImageOrientationPatient = [f"{v:.8f}" for v in list(rowDirection) + list(columnDirection)]
                    ds.PixelSpacing = [f"{self.spacingMm[1]:g}", f"{self.spacingMm[0]:g}"]
                    ds.SliceThickness = f"{self.spacingMm[2]:g}"
                    ds.SpacingBetweenSlices = f"{self.spacingMm[2]:g}"
                    ds.SliceLocation = f"{float(np.dot(position, sliceDirection)):.6f}"
                    ds.Rows = self.dims[1]
                    ds.Columns = self.dims[0]
                    ds.SamplesPerPixel = 1
                    ds.PhotometricInterpretation = "MONOCHROME2"
                    ds.BitsAllocated = 16
                    ds.BitsStored = 12
                    ds.HighBit = 11
                    ds.PixelRepresentation = 0
                    ds.PixelData = storedValues[sliceIndex].astype(np.uint16).tobytes()
                    ds.file_meta = FileMetaDataset()
                    ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
                    ds.file_meta.MediaStorageSOPInstanceUID = sopInstanceUID
                    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                    filePath = os.path.join(seriesDir, f"IM{frameIndex:03d}_{sliceIndex:03d}.dcm")
                    try:
                        ds.save_as(filePath, enforce_file_format=True)  # pydicom >= 3.0
                    except TypeError:
                        ds.is_little_endian = True
                        ds.is_implicit_VR = False
                        ds.save_as(filePath, write_like_original=False)  # pydicom 2.x
        return seriesUIDs


#
# DICOM loading
#

def loadDicomSeriesAsVolumeSequences(seriesUIDs=None):
    """Load 4D DICOM series from the current DICOM database as volume sequences (frames identified by trigger time),
    as a user would load them in the DICOM module. Returns list of proxy volume nodes (in the order of seriesUIDs).
    """
    from DICOMLib import DICOMUtils
    if seriesUIDs is None:
        seriesUIDs = []
        for patient in slicer.dicomDatabase.patients():
            for study in slicer.dicomDatabase.studiesForPatient(patient):
                seriesUIDs.extend(slicer.dicomDatabase.seriesForStudy(study))
    plugin = slicer.modules.dicomPlugins["MultiVolumeImporterPlugin"]()
    proxyVolumeNodes = []
    for seriesUID in seriesUIDs:
        files = slicer.dicomDatabase.filesForSeries(seriesUID)
        loadables = plugin.examine([files])
        sequenceLoadables = [loadable for loadable in loadables if getattr(loadable, "loadAsVolumeSequence", False)]
        if not sequenceLoadables:
            raise RuntimeError(f"Series {seriesUID} cannot be loaded as a volume sequence")
        triggerTimeLoadables = [loadable for loadable in sequenceLoadables if "TriggerTime" in loadable.name]
        selectedLoadable = triggerTimeLoadables[0] if triggerTimeLoadables else sequenceLoadables[0]
        for loadable in loadables:
            loadable.selected = (loadable is selectedLoadable)
        loadedNodeIDs = DICOMUtils.loadLoadables({plugin: loadables})
        sequenceBrowserNodes = [slicer.mrmlScene.GetNodeByID(nodeID) for nodeID in loadedNodeIDs
                                if slicer.mrmlScene.GetNodeByID(nodeID) and slicer.mrmlScene.GetNodeByID(nodeID).IsA("vtkMRMLSequenceBrowserNode")]
        if not sequenceBrowserNodes:
            raise RuntimeError(f"Failed to load series {seriesUID} as a volume sequence")
        browserNode = sequenceBrowserNodes[-1]
        proxyVolumeNodes.append(browserNode.GetProxyNode(browserNode.GetMasterSequenceNode()))
    return proxyVolumeNodes
