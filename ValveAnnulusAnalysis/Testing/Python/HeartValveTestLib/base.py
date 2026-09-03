"""
Base test case for the SlicerHeart heart valve sequence test suite.

Every ``test_*`` method runs against a freshly cleared scene and is isolated from the others:
an exception in one method is recorded and the next method still runs. The suite as a whole fails
(``AssertionError`` raised from ``runTest``) when any method failed.

There are no "expected failure" markers: a test that exposes a defect simply fails.
"""

import logging
import shutil
import time
import traceback
import unittest

import slicer
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleTest

from .asserts import HeartValveAsserts

SkipTest = unittest.SkipTest


class SlicerHeartTestCase(ScriptedLoadableModuleTest, HeartValveAsserts):
  """Base class for all SlicerHeart sequence tests.

  Subclasses define ``test_*`` methods. ``runTest`` (called by the Reload & Test panel and by the
  headless runner) executes every method in alphabetical order with a fresh scene. When executed
  through ``unittest`` (ctest via ``slicer.testing.runUnitTest``), unittest discovers the same
  ``test_*`` methods itself and calls ``setUp`` before each one, so both paths give isolated tests.
  """

  #: Set by the runner to print less per-test detail.
  verbose = True

  # ---------------------------------------------------------------------------------------------
  # Fixture
  # ---------------------------------------------------------------------------------------------

  def setUp(self):
    """Fresh scene and fresh HeartValveLib caches.

    HeartValveLib keeps module-global dictionaries (``HeartValves.ValveBrowsers`` /
    ``HeartValves.ValveModels``) keyed by MRML node objects that production code never clears.
    They are reset here purely to isolate tests from each other; a dedicated test in
    ValveBrowserTest checks the production behaviour of those caches.
    """
    slicer.mrmlScene.Clear(0)
    self.resetHeartValveLibCaches()
    self._tempDirs = []
    # Settings that tests may change; restored in tearDown.
    self._savedSettings = {}

  def tearDown(self):
    for key, value in getattr(self, "_savedSettings", {}).items():
      settings = slicer.app.settings()
      if value is None:
        settings.remove(key)
      else:
        settings.setValue(key, value)
    for tempDir in getattr(self, "_tempDirs", []):
      shutil.rmtree(tempDir, ignore_errors=True)

  @staticmethod
  def resetHeartValveLibCaches():
    import HeartValveLib.HeartValves as hv
    hv.ValveBrowsers.clear()
    hv.ValveModels.clear()

  def tempDirectory(self):
    """:returns: a fresh temporary directory removed at the end of the test."""
    tempDir = slicer.util.tempDirectory()
    self._tempDirs.append(tempDir)
    return tempDir

  def setSetting(self, key, value):
    """Set an application setting for the duration of the test (restored in tearDown)."""
    settings = slicer.app.settings()
    if key not in self._savedSettings:
      self._savedSettings[key] = settings.value(key) if settings.contains(key) else None
    settings.setValue(key, value)

  # ---------------------------------------------------------------------------------------------
  # Runner
  # ---------------------------------------------------------------------------------------------

  def testMethodNames(self):
    return sorted(name for name in dir(self) if name.startswith("test_") and callable(getattr(self, name)))

  def runTest(self):
    """Run every ``test_*`` method in isolation and raise if any failed."""
    results = []
    # Production code reports problems through logging.warning/error; echo them to stdout so they
    # end up next to the test output when running headless.
    import sys
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("[log] %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    try:
      for name in self.testMethodNames():
        results.append(self._runOne(name))
    finally:
      logging.getLogger().removeHandler(handler)
    self.lastResults = results
    summary = self.formatResults(results)
    print(summary)
    logging.info(summary)
    failed = [r for r in results if r["status"] == "FAIL"]
    if failed:
      raise AssertionError(f"{len(failed)} of {len(results)} tests failed in {type(self).__name__}: "
                           + ", ".join(r["name"] for r in failed))

  def _runOne(self, name):
    result = {"name": name, "status": "PASS", "traceback": None, "seconds": 0.0, "message": ""}
    startTime = time.time()
    # Flushed so that a hard crash of the application still leaves the name of the running test
    # in the captured output.
    print(f"[test] {type(self).__name__}.{name} ...", flush=True)
    if self.verbose:
      self.delayDisplay(f"{type(self).__name__}.{name}", msec=1)
    try:
      self.setUp()
      try:
        getattr(self, name)()
      finally:
        self.tearDown()
    except SkipTest as e:
      result["status"] = "SKIP"
      result["message"] = str(e)
    except Exception as e:  # noqa: BLE001 - every failure must be recorded, never propagate
      result["status"] = "FAIL"
      result["message"] = f"{type(e).__name__}: {e}"
      result["traceback"] = traceback.format_exc()
      # Printed (not only logged) so the traceback is in the captured console output even if the
      # application crashes later in the run.
      print(f"[test] {type(self).__name__}.{name} FAILED\n{result['traceback']}", flush=True)
      logging.error(f"{type(self).__name__}.{name} FAILED\n{result['traceback']}")
    result["seconds"] = time.time() - startTime
    print(f"[test] {type(self).__name__}.{name} {result['status']} ({result['seconds']:.1f}s)", flush=True)
    return result

  @staticmethod
  def formatResults(results):
    lines = ["", "=" * 78]
    for r in results:
      line = f"{r['status']:<5} {r['name']:<60} {r['seconds']:6.1f}s"
      if r["message"]:
        line += f"  {r['message']}"
      lines.append(line)
    counts = {status: sum(1 for r in results if r["status"] == status) for status in ("PASS", "FAIL", "SKIP")}
    lines.append("-" * 78)
    lines.append(f"PASS: {counts['PASS']}  FAIL: {counts['FAIL']}  SKIP: {counts['SKIP']}")
    for r in results:
      if r["traceback"]:
        lines.append("")
        lines.append(f"--- {r['name']} ---")
        lines.append(r["traceback"].rstrip())
    lines.append("=" * 78)
    return "\n".join(lines)
