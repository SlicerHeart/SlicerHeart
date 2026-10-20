#!/usr/bin/env python
"""Run the Import4DFlow and Analyze4DFlow feature tests in one or more Slicer versions and write a summary report.

Usage (any Python 3 interpreter, for example PythonSlicer.exe of any Slicer installation):

    python Run4DFlowFeatureTests.py --slicer "C:/.../3D Slicer 5.12.4/Slicer.exe" --slicer "C:/.../Slicer.exe" [--output <dir>] [--suite Import4DFlowFeaturesTest]

To regenerate the summary from existing results (for example, after re-running a single suite in one Slicer version):

    python Run4DFlowFeatureTests.py --summary-only [--output <dir>]

For each Slicer version, the tests are run in testing mode (settings are not saved, popups are suppressed) with the main
window shown (needed for screenshots). Reports are written to <output>/<Slicer version>/<module>/report.md and a
summary of all versions to <output>/README.md.

The default output folder is .test-reports in the repository root (ignored by git, because reports may contain
screenshots of clinical data sets).
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPOSITORY_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", "..", ".."))
SUITES = [
    # (test module name, folder that contains the test module, report folder name)
    ("Import4DFlowFeaturesTest", os.path.join(REPOSITORY_ROOT, "Import4DFlow", "Testing", "Python"), "Import4DFlow"),
    ("Analyze4DFlowFeaturesTest", os.path.join(REPOSITORY_ROOT, "Analyze4DFlow", "Testing", "Python"), "Analyze4DFlow"),
]
MODULE_PATHS = [os.path.join(REPOSITORY_ROOT, "Import4DFlow"), os.path.join(REPOSITORY_ROOT, "Analyze4DFlow")]
STATUS_ICONS = {"PASSED": "✅", "FAILED": "❌", "SKIPPED": "⚠️", None: "❓"}


def slicerVersion(slicerExecutable):
    """Get Slicer version string (for example, "5.12.4" or "5.13.0-2026-10-16")."""
    try:
        output = subprocess.run([slicerExecutable, "--version"], capture_output=True, text=True, timeout=300).stdout
        match = re.search(r"Slicer\s+(\S+)", output)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"Failed to get version of {slicerExecutable}: {e}")
    return os.path.basename(os.path.dirname(slicerExecutable)).replace(" ", "_")


def runSuite(slicerExecutable, suiteName, testsDir, reportDir, logFilePath, timeoutSec):
    # Python code must be a single line (multi-line command-line arguments are not parsed correctly on Windows)
    pythonCode = (f"import slicer, slicer.testing; slicer.testing.runUnitTest([{testsDir.replace(os.sep, '/')!r}], {suiteName!r});"
                  " slicer.util.exit(0)")
    command = [slicerExecutable, "--no-splash", "--testing", "--python-code", pythonCode,
               "--additional-module-paths"] + [path.replace(os.sep, "/") for path in MODULE_PATHS]
    environment = dict(os.environ)
    environment["SLICERHEART_TEST_REPORT_DIR"] = reportDir
    startTime = time.time()
    with open(logFilePath, "w", encoding="utf-8", errors="replace") as logFile:
        # Run in the report folder, as the application may create files (for example, DICOM database) in the working directory
        process = subprocess.Popen(command, stdout=logFile, stderr=subprocess.STDOUT, env=environment, cwd=reportDir)
        try:
            exitCode = process.wait(timeout=timeoutSec)
        except subprocess.TimeoutExpired:
            exitCode = "timeout"
            # The Slicer launcher starts the application in a child process, therefore the whole process tree must be stopped
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
            else:
                process.kill()
            process.wait()
    return exitCode, time.time() - startTime


RUN_INFO_FILE_NAME = "run-info.json"


def loadRunInfo(reportDir):
    """Load information about the test runs of a Slicer version (executable, exit code and duration of each suite)."""
    runInfoFilePath = os.path.join(reportDir, RUN_INFO_FILE_NAME)
    if not os.path.exists(runInfoFilePath):
        return {"executable": "", "suites": {}}
    with open(runInfoFilePath, encoding="utf-8") as runInfoFile:
        return json.load(runInfoFile)


def saveRunInfo(reportDir, runInfo):
    with open(os.path.join(reportDir, RUN_INFO_FILE_NAME), "w", encoding="utf-8") as runInfoFile:
        json.dump(runInfo, runInfoFile, indent=2)


def loadResults(reportDir, reportFolderName):
    resultsFilePath = os.path.join(reportDir, reportFolderName, "results.json")
    if not os.path.exists(resultsFilePath):
        return None
    with open(resultsFilePath, encoding="utf-8") as resultsFile:
        return json.load(resultsFile)


def writeSummary(outputDir, runs):
    """runs: list of dict(version, executable, suites: {suiteName: dict(exitCode, durationSec, results)})"""
    lines = ["# 4D flow modules - feature test summary", ""]
    lines.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Slicer versions")
    lines.append("")
    lines.append("| Slicer version | Executable | Vector field display | Suite results |")
    lines.append("|---|---|---|---|")
    for run in runs:
        suiteTexts = []
        vectorField = ""
        for suiteName, testsDir, reportFolderName in SUITES:
            suite = run["suites"].get(suiteName)
            if not suite:
                continue
            results = suite["results"]
            if results:
                counts = results["summary"]
                vectorField = results["environment"].get("Vector field display node available", "")
                suiteTexts.append(f"[{reportFolderName}]({run['version']}/{reportFolderName}/report.md): "
                    f"{counts['PASSED']} passed, {counts['FAILED']} failed, {counts['SKIPPED']} skipped"
                    f" (exit code {suite['exitCode']}, {suite['durationSec'] / 60:.1f} min)")
            else:
                suiteTexts.append(f"{reportFolderName}: no results (exit code {suite['exitCode']}, see {run['version']}/{suiteName}.log)")
        lines.append(f"| {run['version']} | `{run['executable']}` | {vectorField} | {'<br>'.join(suiteTexts)} |")
    lines.append("")

    for suiteName, testsDir, reportFolderName in SUITES:
        if not any(suiteName in run["suites"] for run in runs):
            continue
        lines.append(f"## {reportFolderName}")
        lines.append("")
        # Collect test names in order of appearance
        testTitles = {}
        for run in runs:
            results = run["suites"].get(suiteName, {}).get("results")
            if results:
                for test in results["tests"]:
                    testTitles.setdefault(test["name"], test["title"])
        lines.append("| Test | " + " | ".join(run["version"] for run in runs) + " |")
        lines.append("|---|" + "---|" * len(runs))
        for testName, title in testTitles.items():
            cells = []
            for run in runs:
                results = run["suites"].get(suiteName, {}).get("results")
                test = next((t for t in results["tests"] if t["name"] == testName), None) if results else None
                if not test:
                    cells.append("not run")
                    continue
                cell = f"{STATUS_ICONS.get(test['status'], '❓')} {test['status']}"
                if test["status"] == "FAILED":
                    cell += f" ({len(test['failedChecks'])}/{test['numberOfChecks']} checks failed)" if test["failedChecks"] else ""
                cells.append(cell)
            lines.append(f"| {title} | " + " | ".join(cells) + " |")
        lines.append("")

        # Failure details
        failureLines = []
        for run in runs:
            results = run["suites"].get(suiteName, {}).get("results")
            if not results:
                continue
            for test in results["tests"]:
                if test["status"] != "FAILED":
                    continue
                details = "; ".join(f"{c['label']} (measured {c['measured']}, expected {c['expected']})" for c in test["failedChecks"]) \
                    or (test["error"] or "")
                failureLines.append(f"| {run['version']} | {test['title']} | {details.replace('|', '/')} |")
        if failureLines:
            lines.append("**Failures**")
            lines.append("")
            lines.append("| Slicer version | Test | Details |")
            lines.append("|---|---|---|")
            lines.extend(failureLines)
            lines.append("")

    summaryFilePath = os.path.join(outputDir, "README.md")
    with open(summaryFilePath, "w", encoding="utf-8") as summaryFile:
        summaryFile.write("\n".join(lines) + "\n")
    return summaryFilePath


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slicer", action="append", help="Slicer executable (can be specified multiple times)")
    parser.add_argument("--output", default=os.path.join(REPOSITORY_ROOT, ".test-reports"), help="Output folder for reports")
    parser.add_argument("--suite", action="append", help="Test suite to run (default: all)")
    parser.add_argument("--timeout", type=float, default=3600, help="Timeout for each test suite in seconds")
    parser.add_argument("--summary-only", action="store_true",
        help="Do not run tests, just regenerate the summary from all results in the output folder")
    args = parser.parse_args()
    if not args.slicer and not args.summary_only:
        parser.error("--slicer is required (unless --summary-only is specified)")

    os.makedirs(args.output, exist_ok=True)
    selectedSuites = [s for s in SUITES if not args.suite or s[0] in args.suite]
    for slicerExecutable in (args.slicer or []) if not args.summary_only else []:
        if not os.path.exists(slicerExecutable):
            print(f"Slicer executable not found: {slicerExecutable}")
            continue
        version = slicerVersion(slicerExecutable)
        reportDir = os.path.join(args.output, version)
        os.makedirs(reportDir, exist_ok=True)
        runInfo = loadRunInfo(reportDir)
        runInfo["executable"] = slicerExecutable
        for suiteName, testsDir, reportFolderName in selectedSuites:
            print(f"Running {suiteName} in Slicer {version}...", flush=True)
            logFilePath = os.path.join(reportDir, f"{suiteName}.log")
            exitCode, durationSec = runSuite(slicerExecutable, suiteName, testsDir, reportDir, logFilePath, args.timeout)
            runInfo["suites"][suiteName] = {"exitCode": exitCode, "durationSec": durationSec}
            saveRunInfo(reportDir, runInfo)
            results = loadResults(reportDir, reportFolderName)
            summary = results["summary"] if results else "no results"
            print(f"  exit code {exitCode}, {durationSec:.0f}s: {summary}", flush=True)

    # Summary of all results in the output folder (including results of previous runs of other Slicer versions or suites)
    runs = []
    versions = sorted(name for name in os.listdir(args.output) if os.path.exists(os.path.join(args.output, name, RUN_INFO_FILE_NAME)))
    for version in versions:
        reportDir = os.path.join(args.output, version)
        runInfo = loadRunInfo(reportDir)
        run = {"version": version, "executable": runInfo["executable"], "suites": {}}
        for suiteName, testsDir, reportFolderName in SUITES:
            if suiteName in runInfo["suites"]:
                run["suites"][suiteName] = dict(runInfo["suites"][suiteName], results=loadResults(reportDir, reportFolderName))
        runs.append(run)

    summaryFilePath = writeSummary(args.output, runs)
    print(f"Summary: {summaryFilePath}")
    allPassed = all(suite["exitCode"] == 0 for run in runs for suite in run["suites"].values())
    return 0 if allPassed else 1


if __name__ == "__main__":
    sys.exit(main())
