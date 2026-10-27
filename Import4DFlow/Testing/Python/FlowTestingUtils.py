"""Shared utilities for the Import4DFlow and Analyze4DFlow feature tests.

- TestReport: collects test results, check tables and screenshots, and writes them into a markdown report.
- FlowPhantom: analytic pulsatile flow in a straight, oblique cylindrical vessel. It can generate
  Siemens CS 4D flow-like component (phase) and magnitude images, either directly into the scene
  or as DICOM files, and CFD-like flow field models (unstructured grid with a velocity point data array).
- DICOM helpers: load 4D flow series from a DICOM folder as volume sequences.

Test data locations (for example, anonymized clinical data sets) are read from environment variables
or from the .env.local file in the repository root (KEY=VALUE lines). Without a local data set of test cases, the
clinical test data set of slicerheart_4dflow (TEST_DATA_REVISION) is downloaded by its ClinicalTestingData class into
~/.SlicerHeart/slicerheart_4dflow_testingdata (shared by all installations), a case when a test first needs it.
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

# Environment variable (or .env.local entry) that specifies the folder of a local data set of 4D flow test cases in
# Slicer-native file format (<folder>/manifest.json, inputs/<case>/, outputs/<case>/, written by
# Export4DFlowTestCases.py). Same variable as in slicerheart_4dflow tests. If it is not set, the clinical test data set
# of slicerheart_4dflow is used (TEST_DATA_REVISION, downloaded on first use).
TEST_CASES_ENV_VARIABLE = "SLICERHEART_4DFLOW_CLINICAL_DATA"

# Revision of the clinical test data set of slicerheart_4dflow (slicerheart_4dflow.testing_data, version 0.4.0 or later)
TEST_DATA_REVISION = "rev002"

# Siemens CS 4D flow component images store phase in the range of [-4096, 4096)
PHASE_MAX_VALUE = 4096

# Direction code configurations (same as Import4DFlowLogic.axisForDirectionCodes):
# for each RAS axis, (directionCode, invertToRasDirection)
DIRECTION_CONFIGURATION_AXIAL = [("through", True), ("inplane_ap", True), ("inplane_fh", False)]
DIRECTION_CONFIGURATION_CORONAL = [("inplane_rl", False), ("through", True), ("inplane_fh", False)]

# Short direction codes used in the SequenceName DICOM field (for example, 'fl3d1_v150in')
SEQUENCE_NAME_DIRECTION_CODES = {"through": "in", "inplane_ap": "ap", "inplane_fh": "fh", "inplane_rl": "rl"}

# Patient-axis direction codes (GE, Philips) for the R, A, S axes, and the vendor sign conventions
# (same as FlowDicom.PATIENT_AXIS_CONFIGURATIONS): (directionCode, invertToRasDirection) for each RAS axis
PATIENT_DIRECTION_CODES = ["patient_rl", "patient_ap", "patient_fh"]
DIRECTION_CONFIGURATION_PATIENT_GE = [("patient_rl", True), ("patient_ap", True), ("patient_fh", False)]
DIRECTION_CONFIGURATION_PATIENT_PHILIPS = [("patient_rl", True), ("patient_ap", True), ("patient_fh", False)]

# Environment variables (or .env.local entries) that specify folders of anonymized 4D flow DICOM data sets of other vendors
REAL_DATA_VENDOR_ENV_VARIABLES = {"ge": "MRI_4D_FLOW_TEST_DATA_GE", "philips": "MRI_4D_FLOW_TEST_DATA_PHILIPS"}
# Folder of anonymized Siemens 4D flow DICOM patient folders (each loaded with the 4D flow DICOM plugin)
REAL_DATA_SIEMENS_CASES_ENV_VARIABLE = "MRI_4D_FLOW_TEST_DATA_SIEMENS_CASES"

# Magnitude scaling of the DICOM phantom variants: the phantom magnitude (3..200) is multiplied by this factor
# (Siemens magnitude images have a fixed 0..255 range; GE and Philips images are scaled arbitrarily)
DICOM_MAGNITUDE_SCALE = {"avanto": 1, "avantofit": 1, "sequencename": 1, "ge": 8, "philips": 20}


#
# Environment
#

def repositoryRoot():
    """Root folder of the SlicerHeart repository (the folder that contains this module folder)."""
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


def clinicalTestingData():
    """The clinical test data set of slicerheart_4dflow (TEST_DATA_REVISION) as a ClinicalTestingData object (its
    manifest is downloaded on first use; the cases are downloaded by prepareTestCase), or None if it is not
    available (slicerheart_4dflow older than 0.4.0, or no network)."""
    from Import4DFlowLib import FlowLibraryBridge
    FlowLibraryBridge.ensureLibrary()
    try:
        from slicerheart_4dflow import testing_data
    except ImportError:
        logging.warning("Downloading the clinical test data set requires slicerheart_4dflow 0.4.0 or later")
        return None
    try:
        manifest = testing_data.clinical_test_data_manifest(TEST_DATA_REVISION)
    except testing_data.TestingDataUnavailable as exc:
        logging.warning(f"Clinical test data set is not available: {exc}")
        return None
    return testing_data.ClinicalTestingData(manifest)


def testCases():
    """The available 4D flow test cases (Slicer-native format): list of (data set folder, case ID), smallest first.
    The data set folder is set in TEST_CASES_ENV_VARIABLE (environment or .env.local); otherwise the cases of the
    clinical test data set of slicerheart_4dflow (clinicalTestingData), which are downloaded by prepareTestCase."""
    root = environmentValue(TEST_CASES_ENV_VARIABLE)
    if not root or not os.path.isfile(os.path.join(root, "manifest.json")):
        data = clinicalTestingData()
        if data is None:
            return []
        # smallest first, by the size of the raw velocity in the manifest (nothing is downloaded yet)
        def downloadSize(caseId):
            return data.files.get(f"inputs/{caseId}/acquisition/velocity_raw.seq.nrrd", {}).get("size", 0)
        return [(str(data.root), caseId) for caseId in sorted(data.cases(), key=downloadSize)]
    from Import4DFlowLib import FlowLibraryBridge
    import Import4DFlow
    slicerIo = FlowLibraryBridge.ensureLibrary().slicer_io
    logic = Import4DFlow.Import4DFlowLogic

    def caseSize(caseId):
        velocityRawPath = logic.testCasePath(root, caseId, "velocity_raw")
        return os.path.getsize(velocityRawPath) if os.path.isfile(velocityRawPath) else 0

    return [(root, caseId) for caseId in sorted(slicerIo.dataset_cases(root), key=caseSize)]


def prepareTestCase(datasetDirectory, caseId):
    """Make the files of a test case available: a case of the clinical test data set of slicerheart_4dflow is
    downloaded (if it is not in the cache yet, verified by the sha256 of the manifest); a local data set is used as it
    is."""
    data = clinicalTestingData()
    if data is not None and os.path.normcase(os.path.abspath(str(data.root))) == os.path.normcase(os.path.abspath(str(datasetDirectory))):
        data.ensure_case(caseId)


def gitDescription():
    """Short description of the current SlicerHeart source code version."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repositoryRoot(),
            capture_output=True, text=True, timeout=30).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repositoryRoot(),
            capture_output=True, text=True, timeout=30).stdout.strip()
        return commit + (" (with local changes)" if status else "")
    except Exception:
        return "unknown"


def voxelValueUnitsKeptInSequence():
    """Voxel value units and quantity of a volume are kept when it is stored in a sequence (not in all Slicer versions:
    vtkMRMLScalarVolumeNode::CopyContent did not copy them)."""
    volumeNode = slicer.vtkMRMLScalarVolumeNode()
    units = slicer.vtkCodedEntry()
    units.SetValueSchemeMeaning("m/s", "UCUM", "meter per second")
    volumeNode.SetVoxelValueUnits(units)
    sequenceNode = slicer.vtkMRMLSequenceNode()
    storedNode = sequenceNode.SetDataNodeAtValue(volumeNode, "0")
    storedUnits = storedNode.GetVoxelValueUnits() if storedNode else None
    return bool(storedUnits and storedUnits.GetCodeValue() == "m/s")


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
        self.numberOfTests = None
        # Progress of the run, written while it runs (one line at the start and end of each test, flushed at once),
        # so that a slow or hanging test is visible (Run4DFlowFeatureTests.py relays it)
        self.progressFile = open(os.path.join(self.outputDir, "progress.log"), "w", encoding="utf-8")
        self.environment = self._collectEnvironment()

    def progress(self, text):
        self.progressFile.write(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
        self.progressFile.flush()

    @staticmethod
    def _collectEnvironment():
        environment = {}
        environment["Slicer version"] = f"{slicer.app.applicationVersion} (revision {slicer.app.revision})"
        environment["Slicer executable"] = slicer.app.applicationFilePath()
        environment["Operating system"] = f"{platform.system()} {platform.release()} ({platform.version()})"
        environment["SlicerHeart version"] = gitDescription()
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
        self.progress(f"[{len(self.tests)}/{self.numberOfTests or '?'}] start   {name}: {title}")

    def endTest(self, status, error=None, durationSec=0.0):
        self.currentTest["status"] = status
        self.currentTest["error"] = error
        self.currentTest["durationSec"] = durationSec
        logging.info(f"===== {self.currentTest['name']}: {status} ({durationSec:.1f}s) =====")
        counts = {}
        for test in self.tests:
            if test["status"]:
                counts[test["status"]] = counts.get(test["status"], 0) + 1
        message = ""
        if error:
            lines = str(error).strip().splitlines()
            message = f": {lines[-1][:200]}" if lines else ""
        self.progress(f"[{len(self.tests)}/{self.numberOfTests or '?'}] {status:7s} {self.currentTest['name']}"
                      f" ({durationSec:.1f} s){message} | " + ", ".join(f"{n} {s.lower()}" for s, n in sorted(counts.items())))
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
        cls.report.numberOfTests = len(unittest.TestLoader().getTestCaseNames(cls))
        cls.report.progress(f"{cls.report.numberOfTests} tests: {cls.REPORT_SUITE_NAME} in Slicer {slicer.app.applicationVersion}")
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
        cls.report.progress("finished")
        cls.report.progressFile.close()
        logging.info(f"Test report written to {os.path.join(cls.report.outputDir, 'report.md')}")

    # If a test runs longer than this then the Python stack is written to crash-traceback.txt (to find where it hangs),
    # and again after each further period, so that a hang (same stack) can be told from slow progress
    HANG_TIMEOUT_SEC = 600

    def setUp(self):
        import faulthandler
        faulthandler.dump_traceback_later(self.HANG_TIMEOUT_SEC, repeat=True, file=self._crashLogFile)
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

def createLegacyTransformFlowField(flowFieldNode, name=None):
    """Create a flow field stored in a sequence of grid transforms (the legacy format of flow fields created by earlier
    versions of Import 4D Flow: velocity in m/s, RAS, stored as displacement, "transform to parent"), browsed with the
    given flow field, with the same velocity. It is used for testing that flow fields stored in transforms can still be
    read (Import 4D Flow only writes vector volume flow fields). Returns the proxy transform node."""
    from Import4DFlowLib import FlowLibraryBridge
    velocity, _, _ = FlowLibraryBridge.velocityArrayFromFlowField(flowFieldNode)
    geometryNode = FlowLibraryBridge.flowFieldGeometryNode(flowFieldNode)
    sourceSequenceNode = FlowLibraryBridge.sequenceFromProxyNode(flowFieldNode)
    browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(flowFieldNode)
    name = name or slicer.mrmlScene.GenerateUniqueName(f"{flowFieldNode.GetName()} transform")
    sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
    sequenceNode.SetIndexName(sourceSequenceNode.GetIndexName())
    sequenceNode.SetIndexUnit(sourceSequenceNode.GetIndexUnit())
    sequenceNode.SetIndexType(sourceSequenceNode.GetIndexType())
    for attributeName in ["SlicerHeart.vencCmPerSec", "SlicerHeart.processing", "SlicerHeart.phaseUnwrapping"]:
        if sourceSequenceNode.GetAttribute(attributeName):
            sequenceNode.SetAttribute(attributeName, sourceSequenceNode.GetAttribute(attributeName))
    sequenceNode.SetAttribute("SlicerHeart.velocityUnit", "m/s")
    directionMatrix = vtk.vtkMatrix4x4()
    geometryNode.GetIJKToRASDirectionMatrix(directionMatrix)
    for frameIndex in range(sourceSequenceNode.GetNumberOfDataNodes()):
        frameNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLTransformNode")
        frameNode.UnRegister(None)
        dims = geometryNode.GetImageData().GetDimensions()
        velocityImage = vtk.vtkImageData()
        velocityImage.SetDimensions(dims)
        velocityImage.AllocateScalars(vtk.VTK_FLOAT, 3)
        velocityImage.SetSpacing(geometryNode.GetSpacing())
        velocityImage.SetOrigin(geometryNode.GetOrigin())
        gridTransform = slicer.vtkOrientedGridTransform()
        gridTransform.SetGridDirectionMatrix(directionMatrix)
        gridTransform.SetDisplacementGridData(velocityImage)
        frameNode.SetAndObserveTransformFromParent(gridTransform)
        slicer.util.arrayFromGridTransform(frameNode)[:] = velocity[frameIndex] / 1000.0  # m/s
        slicer.util.arrayFromGridTransformModified(frameNode)
        frameNode.SetAttribute("SlicerHeart.Type", "FlowField")
        # Legacy flow fields store "transform to parent" (displayed faster)
        frameNode.Inverse()
        sequenceNode.SetDataNodeAtValue(frameNode, sourceSequenceNode.GetNthIndexValue(frameIndex))
    browserNode.AddSynchronizedSequenceNodeID(sequenceNode.GetID())
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
    transformNode = browserNode.GetProxyNode(sequenceNode)
    transformNode.SetName(name)
    transformNode.SetAttribute("SlicerHeart.Type", "FlowField")
    for role in ["magnitudeVolume", "inputFlowField"]:
        if flowFieldNode.GetNodeReference(role):
            transformNode.SetNodeReferenceID(role, flowFieldNode.GetNodeReference(role).GetID())
    return transformNode


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
                 tissueRadiusMm=24.0,
                 velocityNoiseCmPerSec=0.0,
                 noiseSeed=0):
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
        # Velocity noise of the phase images, as in real images (0: noise-free, for checking the computations exactly).
        # velocityNoiseCmPerSec is the standard deviation of the velocity noise in the stationary tissue; it is inversely
        # proportional to the magnitude (signal to noise ratio): half of it in the vessel, and random phase in the air.
        # Typical value: 2 cm/s (venc 150 cm/s, SNR 50 in tissue).
        self.velocityNoiseCmPerSec = float(velocityNoiseCmPerSec)
        self.noiseSeed = int(noiseSeed)

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
        If the phantom has velocity noise (velocityNoiseCmPerSec), it is added (the same for the same frame and axis).
        """
        velocityCmPerSec = self.velocityVolumeArray(frameIndex)[..., axis] * 100.0
        if invertToRasDirection:
            velocityCmPerSec = -velocityCmPerSec
        raw = velocityCmPerSec / vencCmPerSec * PHASE_MAX_VALUE
        if phaseOffset is not None:
            raw = raw + phaseOffset
        if self.velocityNoiseCmPerSec > 0:
            raw = raw + self.phaseNoise(frameIndex, axis, vencCmPerSec)
        if wrap:
            raw = np.mod(raw + PHASE_MAX_VALUE, 2 * PHASE_MAX_VALUE) - PHASE_MAX_VALUE
        return np.round(raw).astype(np.int16)

    def phaseNoise(self, frameIndex, axis, vencCmPerSec):
        """Phase noise (raw units, k, j, i) of a component image: Gaussian velocity noise with standard deviation
        velocityNoiseCmPerSec * (tissue magnitude / magnitude), and uniformly distributed random phase in the air
        (where the magnitude is at noise level), as in real phase-contrast images."""
        rng = np.random.default_rng([self.noiseSeed, frameIndex, axis])
        magnitude = self.magnitudeVolumeArray().astype(float)
        sigmaRaw = self.velocityNoiseCmPerSec * (100.0 / np.maximum(magnitude, 1.0)) / vencCmPerSec * PHASE_MAX_VALUE
        noise = rng.normal(0.0, 1.0, magnitude.shape) * sigmaRaw
        air = self.airMask()
        noise[air] = rng.uniform(-PHASE_MAX_VALUE, PHASE_MAX_VALUE, int(np.count_nonzero(air)))
        return noise

    def airMask(self):
        """Voxels outside the body (magnitude at noise level)."""
        return self.magnitudeVolumeArray() < 10

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

    def createVolumeSequence(self, name, frameArrays, multiVolumeAttributes=True, indexByFrameTime=False):
        """Create a volume sequence with its own sequence browser (as the DICOM importer does). The index values are the
        frame indices (MultiVolumeImporter) or the frame times (indexByFrameTime, as the 4D flow DICOM plugin).
        Returns (proxyVolumeNode, sequenceNode, browserNode)."""
        sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
        if indexByFrameTime:
            sequenceNode.SetIndexName("time")
            sequenceNode.SetIndexUnit("ms")
            sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.NumericIndex)
        for frameIndex, frameArray in enumerate(frameArrays):
            volumeNode = self.createVolumeNode(frameArray, name)
            sequenceNode.SetDataNodeAtValue(volumeNode, f"{self.frameTimesMs[frameIndex]:g}" if indexByFrameTime else str(frameIndex))
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

    def createInputFlowFieldInScene(self, vencCmPerSec=150.0, directionConfiguration=DIRECTION_CONFIGURATION_AXIAL,
                                    phaseOffset=None, wrap=True, withHeartRate=True, phaseModifier=None):
        """Create the magnitude volume sequence and the input flow field (velocity as acquired) in the scene, as the 4D flow
        DICOM plugin does: the velocity components are generated as Siemens-like phase images (componentVolumeArray, with
        the optional phase offset, wrapping and noise), optionally modified by phaseModifier(frameIndex, axis, phase), and
        scaled to RAS velocity (mm/s) with the direction configuration. Returns the input flow field (proxy node).
        """
        import Import4DFlow
        logic = Import4DFlow.Import4DFlowLogic()
        magnitudeArray = self.magnitudeVolumeArray()
        magnitudeVolumeNode, magnitudeSequenceNode, _ = self.createVolumeSequence(
            "Magnitude", [magnitudeArray] * self.numberOfFrames, indexByFrameTime=True)
        magnitudeSequenceNode.SetAttribute("SlicerHeart.directionCode", "magnitude")
        if withHeartRate:
            magnitudeSequenceNode.SetAttribute("SlicerHeart.heartRateBpm", str(self.heartRateBpm()))
        signs = np.array([-1.0 if invertToRasDirection else 1.0 for _, invertToRasDirection in directionConfiguration])
        rawVelocity = np.empty((self.numberOfFrames,) + self.radialDistanceMm.shape + (3,), np.float32)
        for frameIndex in range(self.numberOfFrames):
            for axis, (directionCode, invertToRasDirection) in enumerate(directionConfiguration):
                phase = self.componentVolumeArray(frameIndex, axis, vencCmPerSec, invertToRasDirection, phaseOffset, wrap)
                if phaseModifier is not None:
                    phase = phaseModifier(frameIndex, axis, phase)
                rawVelocity[frameIndex, ..., axis] = phase.astype(np.float32) * np.float32(vencCmPerSec * 10.0 / PHASE_MAX_VALUE * signs[axis])
        return logic.createInputFlowFieldFromArrays(rawVelocity, magnitudeVolumeNode, [vencCmPerSec * 10.0] * 3, np.diag(signs),
                                                    directionCodes=[directionCode for directionCode, _ in directionConfiguration],
                                                    componentMaxValues=[float(PHASE_MAX_VALUE)] * 3, name="Phantom input flow field")

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

    def createFlowModelMesh(self, frameIndex, velocityArrayName="V", lengthMm=40.0, resolutionMm=1.0, velocityUnit="mm/s"):
        """CFD-like flow field: unstructured grid of the vessel lumen (a segment of the cylinder around the center)
        with a velocity point data array, in velocityUnit ("mm/s", the unit of velocity arrays without declared unit,
        or "m/s")."""
        halfSize = max(lengthMm / 2, self.vesselRadiusMm) + 2 * resolutionMm
        imageData = vtk.vtkImageData()
        numberOfPoints = int(2 * halfSize / resolutionMm) + 1
        imageData.SetDimensions(numberOfPoints, numberOfPoints, numberOfPoints)
        imageData.SetSpacing(resolutionMm, resolutionMm, resolutionMm)
        imageData.SetOrigin(*(self.centerRas - halfSize))
        # Point positions in VTK point order (x index changes fastest)
        z, y, x = np.indices((numberOfPoints, numberOfPoints, numberOfPoints)).reshape(3, -1)
        points = np.stack([x, y, z], axis=-1) * resolutionMm + (self.centerRas - halfSize)
        velocity = (self.velocityAt(points, frameIndex) * {"m/s": 1.0, "mm/s": 1000.0}[velocityUnit]).astype(np.float32)
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
                         variant="avanto", patientName="Phantom^Flow", studyDate="20240102", wrap=True,
                         heartRateSource="nominalInterval"):
        """Write magnitude and velocity component series as vendor-like 4D flow DICOM files (one file per slice and frame).

        variant (Siemens CS 4D flow: phase component images with rescale slope 2 and intercept -4096, range [-4096, 4096)):
        - "avanto": speed and direction code in private tag (0051,1014) with explicit VR (LO), for example 'v150_through'
        - "avantofit": speed and direction code in private tag (0021,1129) as raw bytes (VR UN), as in Siemens Avanto Fit
        - "sequencename": no private tags, speed and direction is only in SequenceName, for example 'fl3d1_v150in'
        variant (patient-axis velocity encoding, directionConfiguration must use PATIENT_DIRECTION_CODES):
        - "ge": GE 4D flow (mm4dflow): the role of the series in private tag (0043,1030) Vas collapse flag (2: magnitude,
          3/4/5: L/R, A/P, S/I velocity), venc (mm/s) in (0019,10CC), Velocity Encode Scale (venc/pi) in (0019,10E2),
          int16 pixel values in mm/s, no rescale tags, all series with the same description. A 5th series with
          flag 7 (complex difference) is written too (loaded as an auxiliary image sequence of the acquisition).
        - "philips": Philips 4D flow classic DICOM: ImageType 'VELOCITY MAP' / 'M_FFE', (2005,1011) 'P' / 'M', venc (cm/s)
          in (2001,101A) PC Velocity (one nonzero element for velocity images), (0018,9090) Velocity Encoding
          Direction in the (2005,140F) sequence, stored values rescaled to cm/s (RescaleType 'cm/s')
        The magnitude values are multiplied by DICOM_MAGNITUDE_SCALE[variant].
        heartRateSource: "nominalInterval" (NominalInterval tag, as Siemens), "heartRate" (HeartRate tag, as GE and
        Philips), or "none" (neither: the heart rate is estimated from the trigger times).

        Returns list of series instance UIDs: [magnitude, component 0, component 1, component 2] (for "ge", followed by
        the complex difference series).
        """
        import pydicom
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.sequence import Sequence
        from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

        if variant not in DICOM_MAGNITUDE_SCALE:
            raise ValueError(f"Unknown DICOM variant: {variant}")
        patientAxisVariant = variant in ("ge", "philips")
        for directionCode, _ in directionConfiguration:
            if patientAxisVariant != (directionCode in PATIENT_DIRECTION_CODES):
                raise ValueError(f"Direction code {directionCode} cannot be used with DICOM variant {variant}")
        if heartRateSource not in ("nominalInterval", "heartRate", "none"):
            raise ValueError(f"Unknown heart rate source: {heartRateSource}")

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
        if variant == "ge":
            seriesDefinitions.append(("cd", None, False))  # complex difference (not a magnitude or velocity image)

        seriesUIDs = []
        magnitudeArray = self.magnitudeVolumeArray().astype(np.int32) * DICOM_MAGNITUDE_SCALE[variant]
        vencMmPerSec = vencCmPerSec * 10.0
        philipsSlope = 2.0 * vencCmPerSec / 4095.0  # stored [0, 4095] -> [-venc, venc] cm/s
        for seriesIndex, (directionCode, axis, invertToRasDirection) in enumerate(seriesDefinitions):
            seriesInstanceUID = generate_uid()
            seriesUIDs.append(seriesInstanceUID)
            seriesDir = os.path.join(outputDir, f"series{seriesIndex}")
            os.makedirs(seriesDir, exist_ok=True)
            vencText = f"{vencCmPerSec:g}"
            signedPixels = (variant == "ge")
            for frameIndex in range(self.numberOfFrames):
                if axis is None:
                    storedValues = magnitudeArray
                else:
                    # Phase in [-4096, 4096) (Siemens raw units), venc at 4096
                    voxels = self.componentVolumeArray(frameIndex, axis, vencCmPerSec, invertToRasDirection, wrap=wrap).astype(np.int32)
                    if variant == "ge":
                        # Pixel values are velocity in mm/s
                        storedValues = np.round(voxels / PHASE_MAX_VALUE * vencMmPerSec).astype(np.int32)
                    elif variant == "philips":
                        velocityCmPerSec = voxels / PHASE_MAX_VALUE * vencCmPerSec
                        storedValues = np.clip(np.round((velocityCmPerSec + vencCmPerSec) / philipsSlope), 0, 4095).astype(np.int32)
                    else:
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
                    ds.SeriesTime = "120313"
                    ds.FrameOfReferenceUID = frameOfReferenceUID
                    ds.SOPInstanceUID = sopInstanceUID
                    ds.SOPClassUID = MRImageStorage
                    ds.Modality = "MR"
                    ds.InstanceNumber = frameIndex * self.dims[2] + sliceIndex + 1
                    ds.AcquisitionNumber = 1
                    ds.TriggerTime = f"{self.frameTimesMs[frameIndex]:.6f}"
                    if heartRateSource == "nominalInterval":
                        ds.NominalInterval = f"{self.nominalIntervalMs:g}"
                    elif heartRateSource == "heartRate":
                        ds.HeartRate = f"{round(60000.0 / self.nominalIntervalMs)}"
                    ds.CardiacNumberOfImages = str(self.numberOfFrames)
                    ds.RepetitionTime = "40"
                    ds.EchoTime = "2.3"
                    ds.FlipAngle = "15"
                    ds.MagneticFieldStrength = "1.5"
                    if variant == "ge":
                        ds.Manufacturer = "GE MEDICAL SYSTEMS"
                        ds.ManufacturerModelName = "DISCOVERY MR750"
                        ds.SoftwareVersions = ["27", "LX", "MR Software release:"]
                        ds.SeriesDescription = f"AX 4D FLOWQ v{vencText}"
                        ds.ImageType = ["ORIGINAL", "PRIMARY", "OTHER"]
                        ds.add_new((0x0019, 0x0010), "LO", "GEMS_ACQU_01")
                        ds.add_new((0x0019, 0x109C), "LO", "mm4dflow/ORv1506")
                        ds.add_new((0x0019, 0x10CB), "SS", 7)  # phase contrast flow axis: all
                        ds.add_new((0x0019, 0x10CC), "SS", int(round(vencMmPerSec)))
                        ds.add_new((0x0019, 0x10D7), "SS", frameIndex + 1)  # cardiac phase number
                        ds.add_new((0x0019, 0x10E2), "DS", f"{vencMmPerSec / np.pi:.6f}")
                        ds.add_new((0x0043, 0x0010), "LO", "GEMS_PARM_01")
                        if directionCode == "cd":
                            vasCollapseFlag = 7
                        elif axis is None:
                            vasCollapseFlag = 2
                        else:
                            vasCollapseFlag = 3 + axis
                        ds.add_new((0x0043, 0x1030), "SS", vasCollapseFlag)
                    elif variant == "philips":
                        ds.Manufacturer = "Philips"
                        ds.ManufacturerModelName = "Ingenia Ambition X"
                        ds.SoftwareVersions = "12.3.0.1"
                        ds.SeriesDescription = "anatomy" if axis is None else ["RL", "AP", "FH"][axis]
                        ds.add_new((0x2001, 0x0010), "LO", "Philips Imaging DD 001")
                        ds.add_new((0x2001, 0x1008), "IS", str(frameIndex + 1))  # phase number
                        ds.add_new((0x2001, 0x100A), "IS", str(sliceIndex + 1))  # slice number
                        ds.add_new((0x2001, 0x1017), "SL", self.numberOfFrames)  # number of phases
                        ds.add_new((0x2001, 0x1018), "SL", self.dims[2])  # number of slices
                        ds.add_new((0x2005, 0x0010), "LO", "Philips MR Imaging DD 001")
                        velocityEncodingItem = Dataset()
                        velocityEncodingItem.PhaseContrast = "YES"
                        velocityEncodingItem.AcquisitionContrast = "FLOW_ENCODED"
                        if axis is None:
                            ds.ImageType = ["ORIGINAL", "PRIMARY", "M_FFE", "M", "FFE"]
                            ds.add_new((0x2001, 0x1016), "SS", 3)  # number of PC directions
                            ds.add_new((0x2001, 0x101A), "FL", [vencCmPerSec] * 3)
                            ds.add_new((0x2005, 0x1011), "CS", "M")
                            velocityEncodingItem.VelocityEncodingDirection = [1.0 / np.sqrt(3.0)] * 3
                            ds.RescaleSlope = "1.7"
                            ds.RescaleIntercept = "0"
                            ds.RescaleType = "normalized"
                        else:
                            ds.ImageType = ["ORIGINAL", "PRIMARY", "VELOCITY MAP", "P", "PCA"]
                            ds.add_new((0x2001, 0x1016), "SS", 1)
                            pcVelocity = [0.0, 0.0, 0.0]
                            pcVelocity[axis] = vencCmPerSec
                            ds.add_new((0x2001, 0x101A), "FL", pcVelocity)
                            ds.add_new((0x2005, 0x1011), "CS", "P")
                            direction = [0.0, 0.0, 0.0]
                            direction[axis] = 1.0
                            velocityEncodingItem.VelocityEncodingDirection = direction
                            ds.RescaleSlope = f"{philipsSlope:.14g}"
                            ds.RescaleIntercept = f"{-vencCmPerSec:g}"
                            ds.RescaleType = "cm/s"
                        ds.add_new((0x2005, 0x140F), "SQ", Sequence([velocityEncodingItem]))
                    else:
                        ds.Manufacturer = "SIEMENS"
                        ds.ManufacturerModelName = "Avanto_fit" if variant == "avantofit" else "Avanto"
                        ds.SeriesDescription = f"4D flow phantom {directionCode}"
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
                    ds.BitsStored = 16 if signedPixels else 12
                    ds.HighBit = 15 if signedPixels else 11
                    ds.PixelRepresentation = 1 if signedPixels else 0
                    ds.PixelData = storedValues[sliceIndex].astype(np.int16 if signedPixels else np.uint16).tobytes()
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

def loadDicomStudyWithFlowPlugin():
    """Load the 4D flow acquisition of the current DICOM database with the 4D flow DICOM plugin (all series of all studies
    are examined together), as a user would load it in the DICOM module. Returns the input flow field (proxy node).
    Raises RuntimeError if the plugin does not find exactly one acquisition."""
    from DICOMLib import DICOMUtils
    fileLists = []
    for patient in slicer.dicomDatabase.patients():
        for study in slicer.dicomDatabase.studiesForPatient(patient):
            fileLists += [slicer.dicomDatabase.filesForSeries(seriesUID) for seriesUID in slicer.dicomDatabase.seriesForStudy(study)]
    loadablesByPlugin, _ = DICOMUtils.getLoadablesFromFileLists(fileLists, ["Import4DFlowDicomPlugin"])
    loadables = next(iter(loadablesByPlugin.values()), [])
    acquisitions = {id(loadable.flowAcquisition) for loadable in loadables}
    if len(acquisitions) != 1:
        raise RuntimeError(f"Expected one 4D flow acquisition, the 4D flow DICOM plugin found {len(acquisitions)} ({len(loadables)} loadables)")
    DICOMUtils.loadLoadables(loadablesByPlugin)
    inputFlowFieldNodeID = loadables[0].flowAcquisition.get("inputFlowFieldNodeID")
    inputFlowFieldNode = slicer.mrmlScene.GetNodeByID(inputFlowFieldNodeID) if inputFlowFieldNodeID else None
    if inputFlowFieldNode is None:
        raise RuntimeError("The 4D flow DICOM plugin did not load the acquisition")
    return inputFlowFieldNode


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
