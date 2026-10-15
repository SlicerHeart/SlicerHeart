"""
HeartValveHelpersTest.py

Tests for the scene-level lookup helpers in HeartValveLib.helpers that downstream modules (DeepHeart,
SlicerHeartPrivate, ...) use to find a valve at a given cardiac phase or volume frame, and for
HeartValveLib.HeartValves.createValveBrowserNode. In sequence scenes a valve has one proxy node for
all of its time points, so these helpers move the valve browser to the matching time point.
"""

import os
import sys

import slicer
from slicer.ScriptedLoadableModule import *

_TESTLIB_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class HeartValveHelpersTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "HeartValveHelpersTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for the phase / frame lookup helpers of HeartValveLib."
    self.parent.acknowledgementText = ""


class HeartValveHelpersTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class HeartValveHelpersTestLogic(ScriptedLoadableModuleLogic):
  pass


class HeartValveHelpersTestTest(SlicerHeartTestCase):

  def setUp(self):
    super().setUp()
    from HeartValveLib import helpers
    self.helpers = helpers
    self.factory = NewFormatValveFactory(numFrames=6)

  def _mitral(self):
    """Mitral valve with time points at frames 1 (MS) and 3 (ED); the browser is left at frame 3."""
    return self.factory.createAnnotatedValve("mitral", frames=(1, 3), phases=("mid-systole", "end-diastole"))

  def _tricuspid(self):
    """Tricuspid valve with one time point at frame 2 (MS)."""
    return self.factory.createAnnotatedValve("tricuspid", frames=(2,), phases=("mid-systole",))

  # ---------------------------------------------------------------------------------------------
  # createValveBrowserNode
  # ---------------------------------------------------------------------------------------------

  def test_createValveBrowserNode(self):
    import HeartValveLib
    valveBrowser = HeartValveLib.HeartValves.createValveBrowserNode(
      self.factory.volumeProxyNode, valveType="tricuspid", probePosition="TTE_APICAL", name="MyValve")
    browserNode = valveBrowser.valveBrowserNode
    self.assertEqual(browserNode.GetName(), "TricuspidValve", "the valve type names the browser, like the GUI")
    self.assertEqual(browserNode.GetAttribute("ModuleName"), "HeartValve")
    self.assertIsNotNone(valveBrowser.heartValveSequenceNode, "master sequence is created")
    self.assertIsNotNone(valveBrowser.axialSliceToRasTransformNode)
    self.assertIs(valveBrowser.valveVolumeNode, self.factory.volumeProxyNode)
    self.assertEqual(valveBrowser.valveType, "tricuspid")
    self.assertEqual(valveBrowser.probePosition, "TTE_APICAL")
    self.assertIs(HeartValveLib.HeartValves.getValveBrowser(browserNode), valveBrowser)
    # The new valve is usable right away: a time point can be added and the valve is found by type
    self.factory.addTimePoint(valveBrowser, 2, phase="mid-systole")
    valveModels = self.helpers.getAllHeartValveModelsForValveType("tricuspid")
    self.assertEqual([vm.heartValveNode for vm in valveModels], [valveBrowser.heartValveNode])
    self.assertEqual(valveModels[0].getValveVolumeSequenceIndex(), 2)

  def test_createValveBrowserNode_defaults(self):
    import HeartValveLib
    valveBrowser = HeartValveLib.HeartValves.createValveBrowserNode()
    self.assertEqual(valveBrowser.valveBrowserNode.GetName(), "HeartValveBrowser")
    self.assertIsNone(valveBrowser.valveVolumeNode)
    another = HeartValveLib.HeartValves.createValveBrowserNode()
    self.assertNotEqual(another.valveBrowserNode.GetName(), "HeartValveBrowser", "names are made unique")
    named = HeartValveLib.HeartValves.createValveBrowserNode(name="MyValve")
    self.assertEqual(named.valveBrowserNode.GetName(), "MyValve")

  # ---------------------------------------------------------------------------------------------
  # Time points by volume frame
  # ---------------------------------------------------------------------------------------------

  def test_getValveTimePointMatchingSequenceIndex(self):
    valveBrowser = self._mitral()
    valveNode = valveBrowser.heartValveNode
    self.assertEqual(self.helpers.getValveTimePointMatchingSequenceIndex(valveNode, 1), 0)
    self.assertEqual(self.helpers.getValveTimePointMatchingSequenceIndex(valveNode, 3), 1)
    self.assertEqual(self.helpers.getValveTimePointMatchingSequenceIndex(valveNode, 2), -1, "no time point")
    self.assertEqual(self.helpers.getValveTimePointMatchingSequenceIndex(valveNode, -1), -1)
    self.assertEqual(self.helpers.getValveTimePointMatchingSequenceIndex(valveNode, 6), -1, "beyond sequence")

  def test_getValveTimePointMatchingSequenceIndex_without_browser(self):
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode")
    node.SetAttribute("ModuleName", "HeartValve")
    self.assertEqual(self.helpers.getValveTimePointMatchingSequenceIndex(node, 0), -1)

  def test_selectValveTimePoint_and_context_manager(self):
    valveBrowser = self._mitral()
    valveNode = valveBrowser.heartValveNode
    browserNode = valveBrowser.valveBrowserNode
    self.assertEqual(browserNode.GetSelectedItemNumber(), 1)
    self.helpers.selectValveTimePoint(valveNode, 0)
    self.assertEqual(browserNode.GetSelectedItemNumber(), 0)
    self.assertEqual(valveBrowser.valveModel.getValveVolumeSequenceIndex(), 1)
    self.helpers.selectValveTimePoint(valveNode, -1)
    self.assertEqual(browserNode.GetSelectedItemNumber(), 0, "negative item number is ignored")
    with self.helpers.valveTimePointSelected(valveNode, 1):
      self.assertEqual(browserNode.GetSelectedItemNumber(), 1)
      self.assertEqual(valveBrowser.valveModel.getValveVolumeSequenceIndex(), 3)
    self.assertEqual(browserNode.GetSelectedItemNumber(), 0, "restored after the block")
    with self.assertRaises(RuntimeError):
      with self.helpers.valveTimePointSelected(valveNode, 1):
        raise RuntimeError("inside")
    self.assertEqual(browserNode.GetSelectedItemNumber(), 0, "restored after an exception")

  def test_getFirstValveModelNodeMatchingSequenceIndex_selects_time_point(self):
    valveBrowser = self._mitral()
    valveModel = self.helpers.getFirstValveModelNodeMatchingSequenceIndex(1)
    self.assertIs(valveModel.heartValveNode, valveBrowser.heartValveNode)
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 1)
    self.assertEqual(valveBrowser.valveBrowserNode.GetSelectedItemNumber(), 0)
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, self.factory.contourPoints(1))
    valveModel = self.helpers.getFirstValveModelNodeMatchingSequenceIndex(3)
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 3)
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, self.factory.contourPoints(3))
    with self.assertRaises(ValueError):
      self.helpers.getFirstValveModelNodeMatchingSequenceIndex(2)
    with self.assertRaises(ValueError):
      self.helpers.getFirstValveModelNodeMatchingSequenceIndex(10)

  def test_getFirstValveModelNodeMatchingSequenceIndexAndValveType(self):
    mitral = self._mitral()
    tricuspid = self._tricuspid()
    valveModel = self.helpers.getFirstValveModelNodeMatchingSequenceIndexAndValveType(2, "tricuspid")
    self.assertIs(valveModel.heartValveNode, tricuspid.heartValveNode)
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 2)
    valveModel = self.helpers.getFirstValveModelNodeMatchingSequenceIndexAndValveType(1, "mitral")
    self.assertIs(valveModel.heartValveNode, mitral.heartValveNode)
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 1)
    with self.assertRaises(ValueError):
      self.helpers.getFirstValveModelNodeMatchingSequenceIndexAndValveType(1, "tricuspid")
    with self.assertRaises(ValueError):
      self.helpers.getFirstValveModelNodeMatchingSequenceIndexAndValveType(2, "mitral")

  def test_getValveModelNodesMatchingSequenceIndex_yields_every_valve(self):
    mitral = self._mitral()
    tricuspid = self._tricuspid()
    self.factory.addTimePoint(tricuspid, 3, phase="end-diastole")
    nodes = []
    for valveModel in self.helpers.getValveModelNodesMatchingSequenceIndex(3):
      self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 3)
      nodes.append(valveModel.heartValveNode)
    self.assertEqual(set(nodes), {mitral.heartValveNode, tricuspid.heartValveNode})
    self.assertEqual(list(self.helpers.getValveModelNodesMatchingSequenceIndex(0)), [])

  # ---------------------------------------------------------------------------------------------
  # Time points by phase
  # ---------------------------------------------------------------------------------------------

  def test_getSpecificHeartValveModelNodesMatchingPhaseAndType(self):
    mitral = self._mitral()
    tricuspid = self._tricuspid()
    valveModels = self.helpers.getSpecificHeartValveModelNodesMatchingPhaseAndType(["ED", "MS"], "mitral")
    self.assertEqual([vm.heartValveNode for vm in valveModels], [mitral.heartValveNode] * 2)
    self.assertEqual(valveModels[-1].getValveVolumeSequenceIndex(), 1, "browser left at the last phase (MS)")
    valveModels = self.helpers.getSpecificHeartValveModelNodesMatchingPhaseAndType(["MS", "ED"], "mitral")
    self.assertEqual(valveModels[-1].getValveVolumeSequenceIndex(), 3, "browser left at the last phase (ED)")
    valveModels = self.helpers.getSpecificHeartValveModelNodesMatchingPhaseAndType(["ED"], "mitral")
    self.assertEqual(len(valveModels), 1)
    self.assertEqual(valveModels[0].getValveVolumeSequenceIndex(), 3)
    valveModels = self.helpers.getSpecificHeartValveModelNodesMatchingPhaseAndType(["MS"], "tricuspid")
    self.assertEqual([vm.heartValveNode for vm in valveModels], [tricuspid.heartValveNode])
    self.assertEqual(valveModels[0].getValveVolumeSequenceIndex(), 2)
    self.assertEqual(self.helpers.getSpecificHeartValveModelNodesMatchingPhaseAndType(["ED"], "tricuspid"), [])
    self.assertEqual(self.helpers.getSpecificHeartValveModelNodesMatchingPhaseAndType(["MS"], "aortic"), [])

  def test_getFirstValveModelNodeMatchingPhaseAndType(self):
    mitral = self._mitral()
    self._tricuspid()
    valveModel = self.helpers.getFirstValveModelNodeMatchingPhaseAndType("MS", "mitral")
    self.assertIs(valveModel.heartValveNode, mitral.heartValveNode)
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 1)
    with self.assertRaises(ValueError):
      self.helpers.getFirstValveModelNodeMatchingPhaseAndType("ED", "tricuspid")

  def test_getValveTimePointsMatchingPhase(self):
    valveBrowser = self._mitral()
    self.factory.addTimePoint(valveBrowser, 5, phase="mid-systole")
    valveNode = valveBrowser.heartValveNode
    self.assertEqual(self.helpers.getValveTimePointsMatchingPhase(valveNode, "MS"), [0, 2])
    self.assertEqual(self.helpers.getValveTimePointsMatchingPhase(valveNode, "ED"), [1])
    self.assertEqual(self.helpers.getValveTimePointsMatchingPhase(valveNode, "MD"), [])
