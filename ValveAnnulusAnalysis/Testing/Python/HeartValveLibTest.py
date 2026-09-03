"""
HeartValveLibTest.py

Pure-logic tests for HeartValveLib (no MRML scene needed): the Signal class used to wire the
sequence widgets to the modules, the Constants presets, the util helpers and the geometry functions
in ValveModel.
"""

import math
import os
import sys

import numpy as np
import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_TESTLIB_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase  # noqa: E402


class HeartValveLibTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "HeartValveLibTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Pure-logic tests for HeartValveLib (Signal, Constants, util, geometry)."
    self.parent.acknowledgementText = ""


class HeartValveLibTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class HeartValveLibTestLogic(ScriptedLoadableModuleLogic):
  pass


class HeartValveLibTestTest(SlicerHeartTestCase):

  # ---------------------------------------------------------------------------------------------
  # Signal
  # ---------------------------------------------------------------------------------------------

  def test_signal_emits_in_connection_order(self):
    from HeartValveLib.util import Signal
    calls = []
    signal = Signal()
    signal.connect(lambda: calls.append("a"))
    signal.connect(lambda: calls.append("b"))
    signal.connect(lambda: calls.append("c"))
    signal.emit()
    self.assertEqual(calls, ["a", "b", "c"])
    signal.emit()
    self.assertEqual(calls, ["a", "b", "c", "a", "b", "c"])

  def test_signal_duplicate_connect_registers_once(self):
    from HeartValveLib.util import Signal
    calls = []

    class Receiver:
      def slot(self):
        calls.append(1)

    receiver = Receiver()
    signal = Signal()
    signal.connect(receiver.slot)
    signal.connect(receiver.slot)  # bound methods compare equal
    signal.emit()
    self.assertEqual(len(calls), 1, "a slot connected twice must fire once")
    signal.disconnect(receiver.slot)
    signal.emit()
    self.assertEqual(len(calls), 1, "disconnected slot must not fire")

  def test_signal_rejects_non_callable(self):
    from HeartValveLib.util import Signal
    signal = Signal()
    with self.assertRaises(ValueError):
      signal.connect(42)
    with self.assertRaises(ValueError):
      signal.connect(None)

  def test_signal_disconnect_unknown_is_silent(self):
    from HeartValveLib.util import Signal
    signal = Signal()
    signal.disconnect(lambda: None)  # must not raise
    signal.disconnectAll()
    signal.emit()

  def test_signal_slot_exception_does_not_stop_other_slots(self):
    from HeartValveLib.util import Signal
    calls = []

    def failing():
      calls.append("failing")
      raise RuntimeError("slot failure")

    signal = Signal()
    signal.connect(failing)
    signal.connect(lambda: calls.append("after"))
    signal.emit()  # must not raise
    self.assertEqual(calls, ["failing", "after"])

  def test_signal_forwards_positional_arguments(self):
    from HeartValveLib.util import Signal
    received = []
    signal = Signal()
    signal.connect(lambda *args: received.append(args))
    signal.emit(1, "two", None)
    self.assertEqual(received, [(1, "two", None)])

  def test_signal_connect_disconnect_during_emit(self):
    from HeartValveLib.util import Signal
    calls = []
    signal = Signal()

    def late():
      calls.append("late")

    def first():
      calls.append("first")
      signal.disconnect(first)
      signal.connect(late)

    signal.connect(first)
    signal.emit()
    self.assertEqual(calls, ["first"], "slots connected during emit fire on the next emit only")
    signal.emit()
    self.assertEqual(calls, ["first", "late"], "slot disconnected during emit must not fire again")

  def test_signal_disconnect_all(self):
    from HeartValveLib.util import Signal
    calls = []
    signal = Signal()
    signal.connect(lambda: calls.append(1))
    signal.connect(lambda: calls.append(2))
    signal.disconnectAll()
    signal.emit()
    self.assertEqual(calls, [])

  # ---------------------------------------------------------------------------------------------
  # Package structure
  # ---------------------------------------------------------------------------------------------

  def test_submodules_are_imported_once(self):
    """HeartValveLib/__init__.py star-imports its submodules as top-level modules (it appends its own
    directory to sys.path), while the modules use ``HeartValveLib.<name>`` imports. Both spellings
    must resolve to the same module object, otherwise module-level state (the ValveBrowsers /
    ValveModels caches in HeartValves) is duplicated and callers get different ValveModel objects for
    the same node."""
    import HeartValveLib
    import HeartValveLib.HeartValves
    import HeartValveLib.ValveBrowser
    import HeartValveLib.ValveModel
    import HeartValves
    import ValveBrowser
    import ValveModel
    self.assertIs(HeartValveLib.HeartValves, HeartValves, "HeartValves imported twice")
    self.assertIs(HeartValveLib.ValveBrowser, ValveBrowser, "ValveBrowser imported twice")
    self.assertIs(HeartValveLib.ValveModel, ValveModel, "ValveModel imported twice")
    self.assertIs(HeartValveLib.getValveBrowser, HeartValveLib.HeartValves.getValveBrowser)
    self.assertIs(HeartValveLib.HeartValves.ValveBrowsers, HeartValves.ValveBrowsers, "two ValveBrowsers caches")
    self.assertIs(HeartValveLib.HeartValves.ValveModels, HeartValves.ValveModels, "two ValveModels caches")

  def test_package_exposes_ValveRoi_class(self):
    """ValveSegmentation and MeasurementPreset use ``from HeartValveLib import ValveRoi`` and read
    ``ValveRoi.PARAM_*`` from it, so the package attribute must be the class (a submodule import of
    ``HeartValveLib.ValveRoi`` anywhere replaces it with the module and breaks the widget setup)."""
    import inspect
    import HeartValveLib
    self.assertTrue(inspect.isclass(HeartValveLib.ValveRoi), f"HeartValveLib.ValveRoi is {HeartValveLib.ValveRoi!r}")
    self.assertEqual(HeartValveLib.ValveRoi.PARAM_SCALE, "ValveRoiScale")

  # ---------------------------------------------------------------------------------------------
  # Constants
  # ---------------------------------------------------------------------------------------------

  def test_probe_position_presets_are_valid_rigid_transforms(self):
    from HeartValveLib import Constants
    from HeartValveLib.util import createMatrixFromString
    for presetName, preset in Constants.PROBE_POSITION_PRESETS.items():
      for key in ("name", "description", "probeToRasTransformMatrix", "axialSliceToRasTransformMatrix",
                  "axialSliceToOrtho1SliceRotationsDeg", "axialSliceToOrtho2SliceRotationsDeg"):
        self.assertIn(key, preset, f"{presetName}: missing key {key}")
      for matrixKey in ("probeToRasTransformMatrix", "axialSliceToRasTransformMatrix"):
        matrix = createMatrixFromString(preset[matrixKey])
        rotation = np.array([[matrix.GetElement(r, c) for c in range(3)] for r in range(3)])
        # The preset strings are rounded to 6 digits, so allow ~1e-3 orthonormality error
        orthonormalityError = np.linalg.norm(np.eye(3) - np.dot(rotation.T, rotation))
        self.assertLess(orthonormalityError, 1e-3, f"{presetName}/{matrixKey}: rotation block is not orthonormal")
        self.assertAlmostEqual(np.linalg.det(rotation), 1.0, places=3, msg=f"{presetName}/{matrixKey}: determinant")
        self.assertEqual([matrix.GetElement(3, c) for c in range(4)], [0.0, 0.0, 0.0, 1.0],
                         f"{presetName}/{matrixKey}: last row")
      for rotationKey in ("axialSliceToOrtho1SliceRotationsDeg", "axialSliceToOrtho2SliceRotationsDeg"):
        self.assertEqual(len(preset[rotationKey]), 3, f"{presetName}/{rotationKey}")
    self.assertIn(Constants.PROBE_POSITION_UNKNOWN, Constants.PROBE_POSITION_PRESETS)

  def test_cardiac_cycle_phase_presets(self):
    from HeartValveLib import Constants
    shortNames = [p["shortname"] for p in Constants.CARDIAC_CYCLE_PHASE_PRESETS.values()]
    self.assertEqual(len(shortNames), len(set(shortNames)), "phase short names must be unique")
    self.assertIn("unknown", Constants.CARDIAC_CYCLE_PHASE_PRESETS)
    for phaseName, preset in Constants.CARDIAC_CYCLE_PHASE_PRESETS.items():
      self.assertEqual(len(preset["color"]), 3, phaseName)
      self.assertTrue(all(0.0 <= c <= 1.0 for c in preset["color"]), phaseName)
      self.assertTrue(preset["shortname"], phaseName)

  def test_valve_type_presets(self):
    from HeartValveLib import Constants
    shortNames = [p["shortname"] for p in Constants.VALVE_TYPE_PRESETS.values()]
    self.assertEqual(len(shortNames), len(set(shortNames)), "valve type short names must be unique")
    self.assertIn("unknown", Constants.VALVE_TYPE_PRESETS)
    for valveType, preset in Constants.VALVE_TYPE_PRESETS.items():
      self.assertIn(preset["approximateFlowDirection"], ("anterior", "posterior"), valveType)
      self.assertEqual(len(preset["papillaryNames"]), len(preset["papillaryShortNames"]), valveType)
      self.assertGreater(len(preset["papillaryNames"]), 0, valveType)
      labels = preset["phaseComparePointLabels"]
      self.assertTrue(labels is None or (isinstance(labels, list) and len(labels) >= 3), valveType)

  # ---------------------------------------------------------------------------------------------
  # util
  # ---------------------------------------------------------------------------------------------

  def test_createMatrixFromString(self):
    from HeartValveLib.util import createMatrixFromString
    identity = createMatrixFromString("1 0 0 0  0 1 0 0  0 0 1 0  0 0 0 1")
    self.assertMatricesEqual(identity, vtk.vtkMatrix4x4(), msg="identity")
    matrix = createMatrixFromString("1 2 3 4 5 6 7 8 9 10 11 12 0 0 0 1")
    self.assertEqual(matrix.GetElement(0, 3), 4.0)
    self.assertEqual(matrix.GetElement(2, 1), 10.0)
    self.assertEqual(matrix.GetElement(1, 2), 7.0)
    with self.assertRaises(Exception):
      createMatrixFromString("1 2 3")

  def test_getSampledInterpolatedPointsAsArray_closed(self):
    from HeartValveLib.util import getSampledInterpolatedPointsAsArray
    # Square polyline of side 10 (closed by repeating the first point), sampled every 1 mm
    square = np.array([[0, 10, 10, 0, 0], [0, 0, 10, 10, 0], [0, 0, 0, 0, 0]], dtype=float)
    sampled = getSampledInterpolatedPointsAsArray(square, 1.0, closedCurve=True)
    self.assertEqual(sampled.shape[0], 3)
    self.assertGreaterEqual(sampled.shape[1], 39)
    self.assertLessEqual(sampled.shape[1], 41)
    # Consecutive samples (except the adjusted last one) are 1 mm apart
    for i in range(1, sampled.shape[1] - 1):
      self.assertAlmostEqual(np.linalg.norm(sampled[:, i] - sampled[:, i - 1]), 1.0, places=6, msg=f"sample {i}")
    # All samples lie on the square's boundary
    for i in range(sampled.shape[1]):
      x, y = sampled[0, i], sampled[1, i]
      onBoundary = min(abs(x), abs(x - 10), abs(y), abs(y - 10)) < 1e-6
      self.assertTrue(onBoundary, f"sample {i} ({x}, {y}) not on boundary")
    self.assertEqual(getSampledInterpolatedPointsAsArray(np.zeros((3, 0)), 1.0), [])
    with self.assertRaises(AssertionError):
      getSampledInterpolatedPointsAsArray(square, 0.0)
    with self.assertRaises(AssertionError):
      getSampledInterpolatedPointsAsArray(square.T, 1.0)

  def test_getSampledInterpolatedPointsAsArray_open(self):
    from HeartValveLib.util import getSampledInterpolatedPointsAsArray
    line = np.array([[0, 5], [0, 0], [0, 0]], dtype=float)
    sampled = getSampledInterpolatedPointsAsArray(line, 1.0, closedCurve=False)
    self.assertEqual(sampled.shape, (3, 6))
    np.testing.assert_allclose(sampled[0, :], [0, 1, 2, 3, 4, 5])

  def test_getSampledInterpolatedPointsBetweenStartEndPoints_wraps_around(self):
    from HeartValveLib.util import getSampledInterpolatedPointsBetweenStartEndPointsAsArray
    # 8 points on a unit-spaced polyline along x
    points = np.array([np.arange(8, dtype=float), np.zeros(8), np.zeros(8)])
    forward = getSampledInterpolatedPointsBetweenStartEndPointsAsArray(points, 1.0, 2, 5)
    np.testing.assert_allclose(forward[0, :], [2, 3, 4, 5])
    wrapped = getSampledInterpolatedPointsBetweenStartEndPointsAsArray(points, 1.0, 6, 2)
    self.assertEqual(wrapped.shape[0], 3)
    self.assertAlmostEqual(wrapped[0, 0], 6.0)
    self.assertGreaterEqual(wrapped.shape[1], 3)

  def test_polydata_point_array_round_trip(self):
    from HeartValveLib.util import createPolyDataFromPointArray, getPointArrayFromPolyData
    points = np.array([[0.0, 1.0, 2.0], [3.5, -4.0, 5.25], [6.0, 7.0, -8.0]])
    polyData = createPolyDataFromPointArray(points)
    self.assertEqual(polyData.GetNumberOfPoints(), 3)
    self.assertEqual(polyData.GetNumberOfVerts(), 3)
    np.testing.assert_allclose(getPointArrayFromPolyData(polyData), points)
    points[0, 0] = 99.0  # deep copy: polydata must be unaffected
    self.assertAlmostEqual(getPointArrayFromPolyData(polyData)[0, 0], 0.0)

  def test_getPointsOnPlane(self):
    from HeartValveLib.util import getPointsOnPlane
    # A closed square loop in the z=0 plane crossing the x=0 plane twice
    loop = vtk.vtkPolyData()
    pts = vtk.vtkPoints()
    for p in [(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)]:
      pts.InsertNextPoint(*p)
    lines = vtk.vtkCellArray()
    lines.InsertNextCell(5)
    for i in range(4):
      lines.InsertCellPoint(i)
    lines.InsertCellPoint(0)
    loop.SetPoints(pts)
    loop.SetLines(lines)
    intersections = getPointsOnPlane([0, 0, 0], [1, 0, 0], loop)
    self.assertEqual(intersections.shape[0], 3)
    self.assertEqual(intersections.shape[1], 2)
    np.testing.assert_allclose(intersections[0, :], [0, 0], atol=1e-6)
    self.assertEqual(sorted(intersections[1, :].tolist()), [-5.0, 5.0])

  def test_getAllFilesWithExtension_and_isMRBFile(self):
    from HeartValveLib.helpers import getAllFilesWithExtension, isMRBFile
    tempDir = self.tempDirectory()
    sub = os.path.join(tempDir, "sub")
    os.makedirs(sub)
    for name in ("a.mrb", "b.MRB", "c.txt"):
      with open(os.path.join(tempDir, name), "w") as f:
        f.write("x")
    with open(os.path.join(sub, "d.mrb"), "w") as f:
      f.write("x")
    found = sorted(getAllFilesWithExtension(tempDir, ".mrb", file_name_only=True))
    # fnmatch follows the platform's case rules (case-insensitive on Windows)
    expected = ["a.mrb", "d.mrb"]
    if os.path.normcase("A") == os.path.normcase("a"):
      expected = ["a.mrb", "b.MRB", "d.mrb"]
    self.assertEqual(found, expected)
    fullPaths = getAllFilesWithExtension(tempDir, ".mrb")
    self.assertTrue(all(os.path.isabs(p) for p in fullPaths))
    self.assertTrue(isMRBFile(os.path.join(tempDir, "a.mrb")))
    self.assertTrue(isMRBFile(os.path.join(tempDir, "b.MRB")))
    self.assertFalse(isMRBFile(os.path.join(tempDir, "c.txt")))
    self.assertFalse(isMRBFile(os.path.join(tempDir, "missing.mrb")))

  # ---------------------------------------------------------------------------------------------
  # ValveModel geometry (module-level functions)
  # ---------------------------------------------------------------------------------------------

  def test_planeFit(self):
    from HeartValveLib.ValveModel import planeFit
    rng = np.random.RandomState(1)
    xy = rng.uniform(-10, 10, size=(2, 50))
    z = 2.0 * xy[0] + 3.0 * xy[1] + 1.0
    points = np.vstack((xy, z))
    center, normal = planeFit(points)
    expectedNormal = np.array([2.0, 3.0, -1.0])
    expectedNormal /= np.linalg.norm(expectedNormal)
    self.assertAlmostEqual(abs(np.dot(normal, expectedNormal)), 1.0, places=6)
    self.assertAlmostEqual(2.0 * center[0] + 3.0 * center[1] + 1.0, center[2], places=6)
    with self.assertRaises(AssertionError):
      planeFit(np.zeros((3, 2)))

  def test_lineFit(self):
    from HeartValveLib.ValveModel import lineFit
    direction = np.array([1.0, 2.0, 2.0]) / 3.0
    start = np.array([1.0, -1.0, 4.0])
    points = np.array([start + t * direction for t in np.linspace(0, 9, 10)])
    center, fitted = lineFit(points)
    np.testing.assert_allclose(fitted, direction, atol=1e-6)
    np.testing.assert_allclose(center, points.mean(axis=0), atol=1e-6)
    # Direction must point from the first to the last point
    _, reversedFit = lineFit(points[::-1])
    np.testing.assert_allclose(reversedFit, -direction, atol=1e-6)

  def test_getTransformToPlane(self):
    from HeartValveLib.ValveModel import getTransformToPlane
    planePosition = np.array([1.0, 2.0, 3.0])
    planeNormal = np.array([0.0, 1.0, 1.0]) / math.sqrt(2)
    worldToPlane = getTransformToPlane(planePosition, planeNormal)
    self.assertEqual(worldToPlane.shape, (4, 4))
    origin = np.dot(worldToPlane, np.append(planePosition, 1.0))
    np.testing.assert_allclose(origin[:3], [0, 0, 0], atol=1e-9)
    # A point on the plane maps to z == 0; a point along the normal maps to z == distance
    inPlane = planePosition + np.cross(planeNormal, [1, 0, 0]) * 5.0
    np.testing.assert_allclose(np.dot(worldToPlane, np.append(inPlane, 1.0))[2], 0.0, atol=1e-9)
    alongNormal = planePosition + planeNormal * 2.5
    np.testing.assert_allclose(np.dot(worldToPlane, np.append(alongNormal, 1.0))[2], 2.5, atol=1e-9)
    rotation = worldToPlane[:3, :3]
    np.testing.assert_allclose(np.dot(rotation, rotation.T), np.eye(3), atol=1e-9)
    # Normal parallel to the default x direction (0,0,1) must still produce a valid frame
    worldToPlaneZ = getTransformToPlane(np.zeros(3), np.array([0.0, 0.0, 1.0]))
    np.testing.assert_allclose(np.dot(worldToPlaneZ[:3, :3], worldToPlaneZ[:3, :3].T), np.eye(3), atol=1e-9)

  def test_getPointsProjectedToPlane(self):
    from HeartValveLib.ValveModel import getPointsProjectedToPlane
    planePosition = np.array([0.0, 0.0, 5.0])
    planeNormal = np.array([0.0, 0.0, 1.0])
    points = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 5.0, 3.0]])  # columns are points
    projectedWorld, projectedPlane, above = getPointsProjectedToPlane(points, planePosition, planeNormal)
    np.testing.assert_allclose(projectedWorld[2, :], [5.0, 5.0, 5.0], atol=1e-9)
    np.testing.assert_allclose(projectedWorld[0:2, :], points[0:2, :], atol=1e-9)
    self.assertEqual(projectedPlane.shape, (2, 3))
    self.assertEqual(list(above), [True, False, False])

  def test_getPolyArea(self):
    from HeartValveLib.ValveModel import getPolyArea
    # Vertices are column vectors (2 x N), as produced by getPointsProjectedToPlane
    square = np.array([[0, 2, 2, 0], [0, 0, 2, 2]], dtype=float)
    self.assertAlmostEqual(getPolyArea(square), 4.0)
    self.assertAlmostEqual(getPolyArea(square[:, ::-1]), 4.0, msg="orientation must not matter")
    triangle = np.array([[0, 4, 0], [0, 0, 3]], dtype=float)
    self.assertAlmostEqual(getPolyArea(triangle), 6.0)

  def test_getLinesIntersectionPoints(self):
    from HeartValveLib.ValveModel import getLinesIntersectionPoints
    # Skew lines: x axis (z=0) and a line parallel to y at x=2, z=1 -> closest points (2,0,0) and (2,0,1)
    pa, pb = getLinesIntersectionPoints(np.array([0., 0., 0.]), np.array([1., 0., 0.]),
                                        np.array([2., -1., 1.]), np.array([2., 1., 1.]))
    np.testing.assert_allclose(pa, [2, 0, 0], atol=1e-9)
    np.testing.assert_allclose(pb, [2, 0, 1], atol=1e-9)
    # Intersecting lines: both points coincide
    pa, pb = getLinesIntersectionPoints(np.array([0., 0., 0.]), np.array([1., 1., 0.]),
                                        np.array([1., 0., 0.]), np.array([0., 1., 0.]))
    np.testing.assert_allclose(pa, [0.5, 0.5, 0], atol=1e-9)
    np.testing.assert_allclose(pb, [0.5, 0.5, 0], atol=1e-9)
    # Parallel lines: the implementation returns the centroid of the four points
    parallel = getLinesIntersectionPoints(np.array([0., 0., 0.]), np.array([1., 0., 0.]),
                                          np.array([0., 1., 0.]), np.array([1., 1., 0.]))
    np.testing.assert_allclose(parallel, [0.5, 0.5, 0], atol=1e-9)

  def test_getPointProjectionToLine(self):
    from HeartValveLib.ValveModel import getPointProjectionToLine
    start, end = np.array([0., 0., 0.]), np.array([10., 0., 0.])
    np.testing.assert_allclose(getPointProjectionToLine(np.array([3., 4., 0.]), start, end), [3, 0, 0])
    np.testing.assert_allclose(getPointProjectionToLine(np.array([-3., 4., 0.]), start, end), start)
    np.testing.assert_allclose(getPointProjectionToLine(np.array([13., 4., 1.]), start, end), end)

  def test_vtk_matrix_helpers(self):
    from HeartValveLib.ValveModel import createVtkMatrixFromArray, getVtkTransformPlaneToWorld
    array = np.arange(16, dtype=float).reshape(4, 4)
    matrix = createVtkMatrixFromArray(array)
    for r in range(3):
      for c in range(4):
        self.assertEqual(matrix.GetElement(r, c), array[r, c])
    self.assertEqual([matrix.GetElement(3, c) for c in range(4)], [0, 0, 0, 1])

    planePosition = np.array([3.0, -2.0, 1.0])
    planeNormal = np.array([1.0, 1.0, 0.0]) / math.sqrt(2)
    planeToWorld = getVtkTransformPlaneToWorld(planePosition, planeNormal)
    np.testing.assert_allclose(planeToWorld.TransformPoint((0, 0, 0)), planePosition, atol=1e-9)
    np.testing.assert_allclose(planeToWorld.TransformVector((0, 0, 1)), planeNormal, atol=1e-9)

  def test_rotation_matrix_euler_round_trip(self):
    from HeartValveLib.ValveModel import isRotationMatrix, rotationMatrixToEulerAngles
    self.assertTrue(isRotationMatrix(np.eye(3)))
    self.assertFalse(isRotationMatrix(np.eye(3) * 2.0))
    angle = math.radians(30.0)
    rz = np.array([[math.cos(angle), -math.sin(angle), 0], [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
    np.testing.assert_allclose(rotationMatrixToEulerAngles(rz), [0.0, 0.0, angle], atol=1e-9)
    rx = np.array([[1, 0, 0], [0, math.cos(angle), -math.sin(angle)], [0, math.sin(angle), math.cos(angle)]])
    np.testing.assert_allclose(rotationMatrixToEulerAngles(rx), [angle, 0.0, 0.0], atol=1e-9)
    with self.assertRaises(AssertionError):
      rotationMatrixToEulerAngles(np.eye(3) * 2.0)

  def test_getVolumeSequenceIndexAsDisplayedString(self):
    from HeartValveLib.ValveModel import ValveModel
    valveModel = ValveModel()
    self.assertEqual(valveModel.getVolumeSequenceIndexAsDisplayedString(-1), "NA")
    self.assertEqual(valveModel.getVolumeSequenceIndexAsDisplayedString(0), "1")
    self.assertEqual(valveModel.getVolumeSequenceIndexAsDisplayedString(23), "24")
