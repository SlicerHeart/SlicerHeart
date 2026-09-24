"""
ValveBrowserTest.py

Tests for HeartValveLib.ValveBrowser (the per-valve sequence browser wrapper) and the module-level
helpers in HeartValveLib.HeartValves that deal with browsers, volumes and caches.

All tests run on a small synthetic volume sequence (no downloads, no GUI).
"""

import os
import sys

import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_TESTLIB_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class ValveBrowserTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ValveBrowserTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for HeartValveLib.ValveBrowser and HeartValves helpers."
    self.parent.acknowledgementText = ""


class ValveBrowserTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class ValveBrowserTestLogic(ScriptedLoadableModuleLogic):
  pass


class ValveBrowserTestTest(SlicerHeartTestCase):

  # ---------------------------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _bareBrowser(name="Bare"):
    """A valve browser node without volume, as created by the node selector."""
    import HeartValveLib
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", name)
    node.SetAttribute("ModuleName", "HeartValve")
    return HeartValveLib.HeartValves.getValveBrowser(node)

  @staticmethod
  def _sequenceAxialTransform(valveBrowser):
    """Turn the browser's axial transform into a per-time-point sequence (converted-scene shape)."""
    browserNode = valveBrowser.valveBrowserNode
    transformNode = valveBrowser.axialSliceToRasTransformNode
    sequenceNode = slicer.mrmlScene.AddNewNodeByClass(
      "vtkMRMLSequenceNode", slicer.mrmlScene.GetUniqueNameByString("AxialSliceToRasTransform_Sequence"))
    _, indexValue = valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()
    sequenceNode.SetDataNodeAtValue(transformNode, indexValue)
    browserNode.AddSynchronizedSequenceNode(sequenceNode)
    browserNode.SetSaveChanges(sequenceNode, True)
    browserNode.SetMissingItemMode(sequenceNode, slicer.vtkMRMLSequenceBrowserNode.MissingItemSetToDefault)
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
    valveBrowser.axialSliceToRasTransformNode = browserNode.GetProxyNode(sequenceNode)
    return sequenceNode

  @staticmethod
  def _matrixOf(transformNode):
    matrix = vtk.vtkMatrix4x4()
    transformNode.GetMatrixTransformToParent(matrix)
    return matrix

  @staticmethod
  def _volumeCenterRas(volumeNode):
    extent = volumeNode.GetImageData().GetExtent()
    centerIjk = [(extent[c * 2 + 1] - extent[c * 2] + 1) / 2.0 for c in range(3)] + [1.0]
    ijkToRas = vtk.vtkMatrix4x4()
    volumeNode.GetIJKToRASMatrix(ijkToRas)
    return ijkToRas.MultiplyPoint(centerIjk)[:3]

  # ---------------------------------------------------------------------------------------------
  # getValveBrowser / defaults
  # ---------------------------------------------------------------------------------------------

  def test_getValveBrowser_none(self):
    import HeartValveLib
    self.assertIsNone(HeartValveLib.HeartValves.getValveBrowser(None))

  def test_getValveBrowser_initializes_browser_defaults(self):
    import HeartValveLib
    from HeartValveLib import Constants
    valveBrowser = self._bareBrowser()
    browserNode = valveBrowser.valveBrowserNode

    sequenceNode = valveBrowser.heartValveSequenceNode
    self.assertIsNotNone(sequenceNode, "master sequence must be created")
    self.assertTrue(sequenceNode.GetName().startswith("HeartValveSequence"))
    self.assertEqual(browserNode.GetMasterSequenceNode().GetID(), sequenceNode.GetID())
    self.assertTrue(browserNode.GetSaveChanges(sequenceNode), "SaveChanges must be enabled on the master sequence")
    self.assertFalse(browserNode.GetPlaybackItemSkippingEnabled())
    self.assertAlmostEqual(browserNode.GetPlaybackRateFps(), 1.0)
    self.assertEqual(sequenceNode.GetNumberOfDataNodes(), 0, "no time point yet")
    self.assertIsNone(valveBrowser.heartValveNode, "no proxy before the first time point")

    axial = valveBrowser.axialSliceToRasTransformNode
    self.assertIsNotNone(axial, "axial slice transform must be created")
    self.assertTrue(axial.GetName().startswith("AxialSliceToRasTransform"))
    self.assertShParentIs(axial, browserNode, "axial transform must live under the browser")
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    self.assertEqual(shNode.GetItemAttribute(
      shNode.GetItemByDataNode(axial),
      slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyExcludeFromTreeAttributeName()), "1")
    # Without a volume the probe position is unknown, so the default axial orientation is the UNKNOWN preset
    expected = HeartValveLib.util.createMatrixFromString(
      Constants.PROBE_POSITION_PRESETS[Constants.PROBE_POSITION_UNKNOWN]["axialSliceToRasTransformMatrix"])
    self.assertMatricesEqual(self._matrixOf(axial), expected, msg="default axial orientation")

    # Same Python object on repeated calls, and the node itself is unchanged
    again = HeartValveLib.HeartValves.getValveBrowser(browserNode)
    self.assertIs(again, valveBrowser)
    self.assertEqual(valveBrowser.heartValveSequenceNode.GetID(), sequenceNode.GetID())
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLSequenceNode")), 1)

  def test_probePosition_without_volume(self):
    from HeartValveLib import Constants
    valveBrowser = self._bareBrowser()
    self.assertEqual(valveBrowser.probePosition, Constants.PROBE_POSITION_UNKNOWN)
    with self.assertRaises(RuntimeError):
      valveBrowser.probePosition = Constants.PROBE_POSITION_TTE_APICAL
    self.assertIsNone(valveBrowser.volumeSequenceBrowserNode)
    self.assertIsNone(valveBrowser.volumeSequenceNode)
    self.assertIsNone(valveBrowser.probeToRasTransformNode)

  def test_valveType_default_and_rename(self):
    valveBrowser = self._bareBrowser(name="SomeBrowser")
    browserNode = valveBrowser.valveBrowserNode
    self.assertIsNone(browserNode.GetAttribute("ValveType"))
    self.assertEqual(valveBrowser.valveType, "unknown")
    self.assertEqual(browserNode.GetAttribute("ValveType"), "unknown", "default is written back to the node")
    valveBrowser.valveType = "mitral"
    self.assertEqual(browserNode.GetAttribute("ValveType"), "mitral")
    self.assertEqual(browserNode.GetName(), "MitralValve", "browser is renamed after the valve type")
    # Renaming is skipped when the name already starts with the valve name
    browserNode.SetName("MitralValve_patient1")
    valveBrowser.valveType = "mitral"
    self.assertEqual(browserNode.GetName(), "MitralValve_patient1")
    # Two mitral browsers get unique names
    other = self._bareBrowser(name="Other")
    other.valveType = "mitral"
    self.assertNotEqual(other.valveBrowserNode.GetName(), browserNode.GetName())
    self.assertTrue(other.valveBrowserNode.GetName().startswith("MitralValve"))

  # ---------------------------------------------------------------------------------------------
  # valveVolumeNode / probe transform
  # ---------------------------------------------------------------------------------------------

  def test_valveVolumeNode_setter_creates_probe_transform(self):
    from HeartValveLib import Constants
    factory = NewFormatValveFactory()
    valveBrowser = self._bareBrowser()
    self.assertIsNone(valveBrowser.valveVolumeNode)
    transformsBefore = len(slicer.util.getNodesByClass("vtkMRMLLinearTransformNode"))

    valveBrowser.valveVolumeNode = factory.volumeProxyNode

    self.assertEqual(valveBrowser.valveVolumeNode.GetID(), factory.volumeProxyNode.GetID())
    self.assertEqual(valveBrowser.valveBrowserNode.GetNodeReference("ValveVolume").GetID(), factory.volumeProxyNode.GetID())
    probe = valveBrowser.probeToRasTransformNode
    self.assertIsNotNone(probe, "ProbeToRasTransform must be created for a volume without parent transform")
    self.assertTrue(probe.GetName().startswith("ProbeToRasTransform"))
    self.assertParentTransformIs(factory.volumeProxyNode, probe)
    self.assertShParentIs(probe, factory.volumeProxyNode, "probe transform lives under the volume")
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLLinearTransformNode")), transformsBefore + 1)
    self.assertEqual(valveBrowser.volumeSequenceBrowserNode.GetID(), factory.volumeBrowserNode.GetID())
    self.assertEqual(valveBrowser.volumeSequenceNode.GetID(), factory.volumeSequenceNode.GetID())
    self.assertEqual(factory.volumeBrowserNode.GetIndexDisplayMode(), factory.volumeBrowserNode.IndexDisplayAsIndex)
    # Default probe position is now persisted on the *volume* browser
    self.assertEqual(valveBrowser.probePosition, Constants.PROBE_POSITION_UNKNOWN)
    self.assertEqual(factory.volumeBrowserNode.GetAttribute("ProbePosition"), Constants.PROBE_POSITION_UNKNOWN)
    # The probe transform centres the volume (UNKNOWN preset: no rotation)
    center = self._volumeCenterRas(factory.volumeProxyNode)
    mapped = self._matrixOf(probe).MultiplyPoint(list(center) + [1.0])
    for c in range(3):
      self.assertAlmostEqual(mapped[c], 0.0, places=5, msg=f"volume centre coordinate {c} must map to origin")

  def test_valveVolumeNode_setter_reuses_existing_parent_transform(self):
    factory = NewFormatValveFactory()
    existing = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "ExistingProbeToRas")
    factory.volumeProxyNode.SetAndObserveTransformNodeID(existing.GetID())
    valveBrowser = self._bareBrowser()  # creates the axial slice transform
    transformsBefore = len(slicer.util.getNodesByClass("vtkMRMLLinearTransformNode"))
    valveBrowser.valveVolumeNode = factory.volumeProxyNode
    self.assertEqual(valveBrowser.probeToRasTransformNode.GetID(), existing.GetID())
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLLinearTransformNode")), transformsBefore,
                     "no second probe transform may be created")

  def test_probePosition_setter_updates_probe_transform(self):
    from HeartValveLib import Constants, util
    factory = NewFormatValveFactory()
    valveBrowser = self._bareBrowser()
    valveBrowser.valveVolumeNode = factory.volumeProxyNode
    valveBrowser.probePosition = Constants.PROBE_POSITION_TTE_APICAL
    self.assertEqual(factory.volumeBrowserNode.GetAttribute("ProbePosition"), Constants.PROBE_POSITION_TTE_APICAL)
    self.assertEqual(valveBrowser.probePosition, Constants.PROBE_POSITION_TTE_APICAL)
    preset = util.createMatrixFromString(
      Constants.PROBE_POSITION_PRESETS[Constants.PROBE_POSITION_TTE_APICAL]["probeToRasTransformMatrix"])
    actual = self._matrixOf(valveBrowser.probeToRasTransformNode)
    for r in range(3):
      for c in range(3):
        self.assertAlmostEqual(actual.GetElement(r, c), preset.GetElement(r, c), places=5, msg=f"rotation ({r},{c})")
    # The volume centre still maps to the origin after the rotation
    center = self._volumeCenterRas(factory.volumeProxyNode)
    mapped = actual.MultiplyPoint(list(center) + [1.0])
    for c in range(3):
      self.assertAlmostEqual(mapped[c], 0.0, places=5)
    # A second valve on the same volume sees the same probe position (it is a property of the volume)
    second = self._bareBrowser("Second")
    second.valveVolumeNode = factory.volumeProxyNode
    self.assertEqual(second.probePosition, Constants.PROBE_POSITION_TTE_APICAL)
    self.assertEqual(second.probeToRasTransformNode.GetID(), valveBrowser.probeToRasTransformNode.GetID())

  def test_clippedValveVolumeNode(self):
    factory = NewFormatValveFactory()
    valveBrowser = self._bareBrowser()
    with self.assertRaises(RuntimeError):
      ValveBrowserTestTest._bareBrowserWithoutNode().clippedValveVolumeNode = None
    clipped = scene.createVolumeNode("Clipped", voxelValue=9)
    # Clipped volume assigned before the valve volume: no probe transform yet
    valveBrowser.clippedValveVolumeNode = clipped
    self.assertEqual(valveBrowser.clippedValveVolumeNode.GetID(), clipped.GetID())
    self.assertIsNone(clipped.GetParentTransformNode())
    self.assertShParentIs(clipped, valveBrowser.valveBrowserNode)
    # Assigning the valve volume must re-parent the clipped volume under the new probe transform
    valveBrowser.valveVolumeNode = factory.volumeProxyNode
    self.assertParentTransformIs(clipped, valveBrowser.probeToRasTransformNode, "clipped volume follows the probe")
    valveBrowser.clippedValveVolumeNode = None
    self.assertIsNone(valveBrowser.clippedValveVolumeNode)

  @staticmethod
  def _bareBrowserWithoutNode():
    from HeartValveLib.ValveBrowser import ValveBrowser
    return ValveBrowser()

  def test_setters_without_browser_node_raise(self):
    valveBrowser = self._bareBrowserWithoutNode()
    self.assertIsNone(valveBrowser.valveVolumeNode)
    self.assertIsNone(valveBrowser.heartValveNode)
    self.assertIsNone(valveBrowser.heartValveSequenceNode)
    self.assertIsNone(valveBrowser.axialSliceToRasTransformNode)
    self.assertEqual(valveBrowser.valveType, "unknown")
    with self.assertRaises(RuntimeError):
      valveBrowser.valveVolumeNode = None
    with self.assertRaises(RuntimeError):
      valveBrowser.axialSliceToRasTransformNode = None
    with self.assertRaises(RuntimeError):
      valveBrowser.valveType = "mitral"

  # ---------------------------------------------------------------------------------------------
  # Time points
  # ---------------------------------------------------------------------------------------------

  def test_addTimePoint_first(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    browserNode = valveBrowser.valveBrowserNode
    indexValue = factory.addTimePoint(valveBrowser, 2)
    self.assertEqual(indexValue, factory.indexValue(2))

    heartValveNode = valveBrowser.heartValveNode
    self.assertIsNotNone(heartValveNode)
    self.assertEqual(heartValveNode.GetClassName(), "vtkMRMLScriptedModuleNode")
    self.assertEqual(heartValveNode.GetAttribute("ModuleName"), "HeartValve")
    self.assertFalse(heartValveNode.GetHideFromEditors())
    self.assertTrue(heartValveNode.GetName().startswith(browserNode.GetName()),
                    f"valve node {heartValveNode.GetName()} should be named after the browser {browserNode.GetName()}")
    self.assertShParentIs(heartValveNode, browserNode)
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [indexValue])
    self.assertEqual(browserNode.GetSelectedItemNumber(), 0)
    self.assertEqual(valveBrowser.getDisplayedHeartValveSequenceIndexAndValue(), (0, indexValue))
    valveModel = valveBrowser.valveModel
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 2)
    self.assertEqual(valveModel.getCardiacCyclePhase(), "unknown")
    self.assertIsNone(valveModel.annulusContourCurveNode, "no contour for a brand new time point")
    self.assertIsNotNone(valveModel.valveLabelsNode, "labels node is created with the valve")
    self.assertIsNotNone(valveModel.valveLabelsSequenceNode, "labels node is a per-time-point sequence")
    self.assertSequenceHasItem(valveModel.valveLabelsSequenceNode, indexValue)
    self.assertEqual(len(scene.heartValveNodes()), 1, "exactly one HeartValve node in the scene")

  def test_addTimePoint_second_starts_clean_and_first_is_preserved(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    valveModel = valveBrowser.valveModel if valveBrowser.heartValveNode else None
    factory.addTimePoint(valveBrowser, 1, phase="mid-systole")
    valveModel = valveBrowser.valveModel
    contour1 = factory.setContour(valveBrowser, 1)
    labels1 = factory.setLabels(valveBrowser, 1)
    factory.addRoi(valveBrowser)
    valveModel.valveRoi.setRoiGeometry({"ValveRoiScale": 150, "ValveRoiTopDistance": 12, "ValveRoiTopScale": 40,
                                        "ValveRoiBottomDistance": 25, "ValveRoiBottomScale": 60})
    roiPoints1 = valveModel.valveRoiModelNode.GetPolyData().GetNumberOfPoints()
    self.assertGreater(roiPoints1, 0)

    factory.addTimePoint(valveBrowser, 3)
    self.assertIs(valveBrowser.valveModel, valveModel, "the proxy node (and its ValveModel) is shared by time points")
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [factory.indexValue(1), factory.indexValue(3)])
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 3)
    self.assertEqual(valveModel.getCardiacCyclePhase(), "unknown", "phase is reset for a new time point")
    self.assertIsNone(valveModel.annulusContourCurveNode, "contour is not specified for the new time point")
    self.assertFalse(valveModel.isNodeSpecifiedForCurrentTimePoint(valveModel.valveLabelsNode),
                     "labels are not specified for the new time point")
    self.assertIsNone(valveModel.valveRoiModelNode, "ROI is not specified for the new time point")
    self.assertFalse(valveModel.hasStoredAnnulusContour())

    # Go back: everything of the first time point is intact
    factory.switchTo(valveBrowser, 1)
    self.assertEqual(valveModel.getCardiacCyclePhase(), "mid-systole")
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, contour1, msg="contour of first time point")
    self.assertLabelsEqual(valveModel.valveLabelsNode, labels1, msg="labels of first time point")
    self.assertIsNotNone(valveModel.valveRoiModelNode)
    self.assertEqual(valveModel.valveRoi.getRoiGeometry()["ValveRoiScale"], 150.0)
    self.assertEqual(valveModel.valveRoiModelNode.GetPolyData().GetNumberOfPoints(), roiPoints1)

  def test_addTimePoint_contour_edit_does_not_leak_between_time_points(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("tricuspid")
    factory.addTimePoint(valveBrowser, 0)
    contour0 = factory.setContour(valveBrowser, 0)
    factory.addTimePoint(valveBrowser, 4)
    contour4 = factory.setContour(valveBrowser, 4)
    self.assertControlPointsNotEqual(valveBrowser.valveModel.annulusContourCurveNode, contour0)
    factory.switchTo(valveBrowser, 0)
    self.assertControlPointsEqual(valveBrowser.valveModel.annulusContourCurveNode, contour0)
    factory.switchTo(valveBrowser, 4)
    self.assertControlPointsEqual(valveBrowser.valveModel.annulusContourCurveNode, contour4)

  def test_addTimePoint_carries_axial_orientation_when_sequenced(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    axialSequence = self._sequenceAxialTransform(valveBrowser)
    rotated = scene.rotationMatrixZ(35.0, translation=(1.0, 2.0, 3.0))
    valveBrowser.axialSliceToRasTransformNode.SetMatrixTransformToParent(rotated)
    slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(valveBrowser.valveBrowserNode,
                                                                   valveBrowser.axialSliceToRasTransformNode)

    factory.addTimePoint(valveBrowser, 3)
    self.assertSequenceHasItem(axialSequence, factory.indexValue(3), "new time point gets its own axial item")
    self.assertMatricesEqual(self._matrixOf(valveBrowser.axialSliceToRasTransformNode), rotated,
                             msg="orientation carried over to the new time point")
    factory.switchTo(valveBrowser, 1)
    self.assertMatricesEqual(self._matrixOf(valveBrowser.axialSliceToRasTransformNode), rotated, msg="first time point")
    # Editing the orientation at one time point must not change the other
    factory.switchTo(valveBrowser, 3)
    other = scene.rotationMatrixZ(-20.0)
    valveBrowser.axialSliceToRasTransformNode.SetMatrixTransformToParent(other)
    slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(valveBrowser.valveBrowserNode,
                                                                   valveBrowser.axialSliceToRasTransformNode)
    factory.switchTo(valveBrowser, 1)
    self.assertMatricesEqual(self._matrixOf(valveBrowser.axialSliceToRasTransformNode), rotated, msg="unchanged")
    factory.switchTo(valveBrowser, 3)
    self.assertMatricesEqual(self._matrixOf(valveBrowser.axialSliceToRasTransformNode), other, msg="edited")

  def test_addTimePoint_shared_axial_transform_untouched(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    rotated = scene.rotationMatrixZ(35.0)
    axial = valveBrowser.axialSliceToRasTransformNode
    axial.SetMatrixTransformToParent(rotated)
    factory.addTimePoint(valveBrowser, 3)
    self.assertEqual(valveBrowser.axialSliceToRasTransformNode.GetID(), axial.GetID())
    self.assertMatricesEqual(self._matrixOf(axial), rotated, msg="shared transform must not be reset")
    self.assertIsNone(valveBrowser.valveBrowserNode.GetSequenceNode(axial), "still not a sequence")

  def test_addTimePointAtCurrentFrame(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.selectFrame(3)
    self.assertEqual(valveBrowser.addTimePointAtCurrentFrame(), factory.indexValue(3))
    factory.selectFrame(1)
    self.assertEqual(valveBrowser.addTimePointAtCurrentFrame(), factory.indexValue(1))
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [factory.indexValue(1), factory.indexValue(3)])
    self.assertEqual(valveBrowser.valveBrowserNode.GetSelectedItemNumber(), 0, "sorted by index value")
    # Existing time point: switch only, nothing added
    factory.selectFrame(3)
    self.assertEqual(valveBrowser.addTimePointAtCurrentFrame(), factory.indexValue(3))
    self.assertEqual(valveBrowser.heartValveSequenceNode.GetNumberOfDataNodes(), 2)
    self.assertEqual(valveBrowser.valveBrowserNode.GetSelectedItemNumber(), 1)
    # Frame 0 has a "zero-like" index value and must work too
    factory.selectFrame(0)
    self.assertEqual(valveBrowser.addTimePointAtCurrentFrame(), factory.indexValue(0))
    self.assertEqual(valveBrowser.heartValveSequenceNode.GetNumberOfDataNodes(), 3)
    self.assertEqual(len(scene.heartValveNodes()), 1, "still a single proxy valve node")

  def test_addTimePointAtCurrentFrame_without_volume(self):
    valveBrowser = self._bareBrowser()
    self.assertIsNone(valveBrowser.addTimePointAtCurrentFrame())
    self.assertEqual(valveBrowser.heartValveSequenceNode.GetNumberOfDataNodes(), 0)

  def test_removeTimePoint_master_sequence_and_selection(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    for frame in (1, 3, 5):
      factory.addTimePoint(valveBrowser, frame)
    browserNode = valveBrowser.valveBrowserNode
    self.assertEqual(browserNode.GetSelectedItemNumber(), 2)
    valveBrowser.removeTimePoint(factory.indexValue(5))
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [factory.indexValue(1), factory.indexValue(3)])
    self.assertEqual(browserNode.GetSelectedItemNumber(), 1, "selection clamped to the last remaining item")
    valveBrowser.removeTimePoint(factory.indexValue(1))
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [factory.indexValue(3)])
    self.assertEqual(browserNode.GetSelectedItemNumber(), 0)
    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
    self.assertEqual(valveBrowser.valveModel.getValveVolumeSequenceIndex(), 3)
    valveBrowser.removeTimePoint(factory.indexValue(3))
    self.assertEqual(valveBrowser.heartValveSequenceNode.GetNumberOfDataNodes(), 0)
    # Adding again after removing everything must work
    factory.addTimePoint(valveBrowser, 2)
    self.assertEqual(valveBrowser.valveModel.getValveVolumeSequenceIndex(), 2)

  def test_removeTimePoint_removes_items_from_all_sequences(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    for frame in (1, 3):
      factory.addTimePoint(valveBrowser, frame)
      factory.setContour(valveBrowser, frame)
      factory.setLabels(valveBrowser, frame)
      factory.addRoi(valveBrowser)
    valveModel = valveBrowser.valveModel
    removed = factory.indexValue(3)
    kept = factory.indexValue(1)
    valveBrowser.removeTimePoint(removed)
    for name, sequenceNode in (("contour", valveModel.annulusContourCurveSequenceNode),
                               ("labels", valveModel.valveLabelsSequenceNode),
                               ("roi", valveModel.valveRoiSequenceNode)):
      self.assertSequenceHasItem(sequenceNode, kept, f"{name}: kept time point")
      self.assertSequenceLacksItem(sequenceNode, removed, f"{name}: removed time point must not leave an orphan item")

  # ---------------------------------------------------------------------------------------------
  # Per-node sequences
  # ---------------------------------------------------------------------------------------------

  def test_makeTimeSequence(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 2)
    browserNode = valveBrowser.valveBrowserNode
    modelNode = slicer.modules.models.logic().AddModel(vtk.vtkPolyData())
    modelNode.SetName("Metric")
    sequencesBefore = len(slicer.util.getNodesByClass("vtkMRMLSequenceNode"))

    sequenceNode = valveBrowser.makeTimeSequence(modelNode)
    self.assertIsNotNone(sequenceNode)
    self.assertEqual(sequenceNode.GetName(), "MetricSequence")
    self.assertEqual(browserNode.GetSequenceNode(modelNode).GetID(), sequenceNode.GetID())
    self.assertEqual(browserNode.GetProxyNode(sequenceNode).GetID(), modelNode.GetID(), "the node becomes the proxy")
    self.assertEqual(browserNode.GetMissingItemMode(sequenceNode), slicer.vtkMRMLSequenceBrowserNode.MissingItemSetToDefault)
    self.assertTrue(browserNode.GetSaveChanges(sequenceNode))
    self.assertSequenceIndexValues(sequenceNode, [factory.indexValue(2)], "item for the current time point only")
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLSequenceNode")), sequencesBefore + 1)

    again = valveBrowser.makeTimeSequence(modelNode)
    self.assertEqual(again.GetID(), sequenceNode.GetID(), "idempotent")
    self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLSequenceNode")), sequencesBefore + 1)

  def test_addCurrentTimePointToSequence_creates_item_and_restores_modes(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.addTimePoint(valveBrowser, 3)
    browserNode = valveBrowser.valveBrowserNode
    modelNode = slicer.modules.models.logic().AddModel(vtk.vtkPolyData())
    modelNode.SetName("Metric")
    sequenceNode = valveBrowser.makeTimeSequence(modelNode)  # item at frame 3 only
    browserNode.SetSaveChanges(sequenceNode, False)

    factory.switchTo(valveBrowser, 1)
    self.assertSequenceLacksItem(sequenceNode, factory.indexValue(1))
    with scene.ModifiedEventCounter(browserNode) as browserEvents:
      valveBrowser.addCurrentTimePointToSequence(sequenceNode)
    self.assertSequenceHasItem(sequenceNode, factory.indexValue(1))
    self.assertEqual(browserNode.GetMissingItemMode(sequenceNode),
                     slicer.vtkMRMLSequenceBrowserNode.MissingItemSetToDefault, "missing item mode restored")
    self.assertFalse(browserNode.GetSaveChanges(sequenceNode), "SaveChanges restored to its previous value")
    self.assertEqual(browserEvents.count, 1, "browser property changes are batched into a single ModifiedEvent")
    self.assertEqual(browserNode.GetProxyNode(sequenceNode).GetID(), modelNode.GetID())

  def test_addCurrentTimePointToSequence_existing_item_is_cheap(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setLabels(valveBrowser, 1)
    valveModel = valveBrowser.valveModel
    browserNode = valveBrowser.valveBrowserNode
    modelNode = slicer.modules.models.logic().AddModel(vtk.vtkPolyData())
    sequenceNode = valveBrowser.makeTimeSequence(modelNode)
    self.assertSequenceHasItem(sequenceNode, factory.indexValue(1))
    # An existing item must not trigger a browser-wide proxy refresh (which would re-sync every
    # proxy and made quantification quadratic in the number of metric models)
    with scene.ModifiedEventCounter(valveModel.valveLabelsNode) as labelEvents, \
         scene.ModifiedEventCounter(browserNode) as browserEvents:
      valveBrowser.addCurrentTimePointToSequence(sequenceNode)
    self.assertEqual(labelEvents.count, 0, "unrelated proxies must not be re-synced")
    self.assertEqual(browserEvents.count, 0, "browser must not be modified")

  def test_valveVolumeNode_static_volume_gets_a_single_frame_sequence(self):
    """A valve can be created on a static (non-sequence) volume, e.g. a CT or a single 3D ultrasound
    frame: the volume is wrapped into a single-frame sequence (the volume node itself becomes the
    proxy) and the valve gets its time point at that frame."""
    import HeartValveLib
    volumeNode = scene.createVolumeNode("StaticCT", voxelValue=5)
    browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "MitralValveBrowser")
    browserNode.SetAttribute("ModuleName", "HeartValve")
    valveBrowser = HeartValveLib.HeartValves.getValveBrowser(browserNode)
    valveBrowser.valveVolumeNode = volumeNode
    volumeBrowserNode = valveBrowser.volumeSequenceBrowserNode
    self.assertIsNotNone(volumeBrowserNode, "static volume must be wrapped into a volume sequence")
    self.assertEqual(volumeBrowserNode.GetProxyNode(volumeBrowserNode.GetMasterSequenceNode()).GetID(), volumeNode.GetID(),
                     "the volume node itself is the proxy of the new sequence")
    self.assertEqual(volumeBrowserNode.GetMasterSequenceNode().GetNumberOfDataNodes(), 1)
    self.assertEqual(scene.volumeVoxelValue(volumeNode), 5, "volume content unchanged")
    self.assertEqual([n.GetName() for n in scene.nodesByClass("vtkMRMLScalarVolumeNode")], ["StaticCT"],
                     "no generated proxy volume must be left behind")
    self.assertIsNotNone(valveBrowser.probeToRasTransformNode)
    valveBrowser.probePosition = "TTE_APICAL"
    self.assertEqual(valveBrowser.probePosition, "TTE_APICAL")
    indexValue = valveBrowser.addTimePointAtCurrentFrame()
    self.assertIsNotNone(indexValue, "a time point can be added on the static volume")
    valveModel = valveBrowser.valveModel
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 0)
    self.assertIsNotNone(valveModel.setAnnulusContourPoints(NewFormatValveFactory.contourPoints(0)))
    self.assertEqual(valveModel.annulusContourCurveNode.GetNumberOfControlPoints(), 12)
    # Setting the same volume again (e.g. re-selecting it in the module) must not wrap it twice
    valveBrowser.valveVolumeNode = volumeNode
    self.assertEqual(len(scene.nodesByClass("vtkMRMLSequenceBrowserNode")), 2, "valve browser + one volume browser")
    self.assertEqual(valveBrowser.volumeSequenceBrowserNode.GetID(), volumeBrowserNode.GetID())
    # Everything survives save and reload
    scene.saveAndReloadScene(self.tempDirectory(), resetCaches=self.resetHeartValveLibCaches)
    valveBrowser = HeartValveLib.HeartValves.getValveBrowser(scene.valveBrowserNodes()[0])
    self.assertEqual(valveBrowser.valveModel.getValveVolumeSequenceIndex(), 0)
    self.assertEqual(valveBrowser.valveModel.annulusContourCurveNode.GetNumberOfControlPoints(), 12)
    self.assertEqual(scene.volumeVoxelValue(valveBrowser.valveVolumeNode), 5)
    self.assertEqual(valveBrowser.valveVolumeNode.GetName(), "StaticCT")

  def test_addCurrentTimePointToDisplaySequences(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    factory.addTimePoint(valveBrowser, 3)
    factory.setContour(valveBrowser, 3)
    valveModel = valveBrowser.valveModel
    browserNode = valveBrowser.valveBrowserNode
    curveNode = valveModel.annulusContourCurveNode
    displayNode = curveNode.GetDisplayNode()
    # Drive the display node from a display sequence with an item at frame 3 only (converted-scene shape)
    displaySequence = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "AnnulusContour_Display_Sequence")
    displayNode.SetVisibility(False)
    displaySequence.SetDataNodeAtValue(displayNode, factory.indexValue(3))
    browserNode.AddProxyNode(displayNode, displaySequence, False)
    browserNode.SetSaveChanges(displaySequence, False)
    browserNode.SetMissingItemMode(displaySequence, slicer.vtkMRMLSequenceBrowserNode.MissingItemSetToDefault)

    factory.switchTo(valveBrowser, 1)
    self.assertSequenceLacksItem(displaySequence, factory.indexValue(1))
    valveBrowser.addCurrentTimePointToDisplaySequences(curveNode)
    self.assertSequenceHasItem(displaySequence, factory.indexValue(1), "display item added for current time point")
    self.assertTrue(browserNode.GetSaveChanges(displaySequence), "display edits are now recorded")
    template = displaySequence.GetDataNodeAtValue(factory.indexValue(1))
    self.assertFalse(template.GetVisibility(), "copied from the closest existing time point")
    # No-op paths: item exists -> no browser refresh; non-displayable proxy -> nothing happens
    with scene.ModifiedEventCounter(browserNode) as browserEvents:
      valveBrowser.addCurrentTimePointToDisplaySequences(curveNode)
      valveBrowser.addCurrentTimePointToDisplaySequences(valveBrowser.heartValveNode)
      valveBrowser.addCurrentTimePointToDisplaySequences(None)
    self.assertEqual(browserEvents.count, 0)

  # ---------------------------------------------------------------------------------------------
  # Index accessors
  # ---------------------------------------------------------------------------------------------

  def test_displayed_index_accessors(self):
    bare = self._bareBrowser()
    self.assertEqual(bare.getDisplayedValveVolumeSequenceIndex(), 0)
    self.assertEqual(bare.getDisplayedValveVolumeSequenceIndexAndValue(), (-1, None))
    self.assertIsNone(bare.getDisplayedValveVolumeSequenceIndexValue())
    itemIndex, indexValue = bare.getDisplayedHeartValveSequenceIndexAndValue()
    self.assertIsNone(indexValue, "no time points -> no index value")

    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.selectFrame(4)
    self.assertEqual(valveBrowser.getDisplayedValveVolumeSequenceIndex(), 4)
    self.assertEqual(valveBrowser.getDisplayedValveVolumeSequenceIndexAndValue(), (4, factory.indexValue(4)))
    self.assertEqual(valveBrowser.getDisplayedValveVolumeSequenceIndexValue(), factory.indexValue(4))
    factory.addTimePoint(valveBrowser, 4)
    self.assertEqual(valveBrowser.getDisplayedHeartValveSequenceIndexAndValue(), (0, factory.indexValue(4)))

  def test_accessors_are_safe_without_master_sequence(self):
    """Widgets observe browser nodes and query the ValveBrowser from event handlers; a browser whose
    master sequence is gone (scene closing, node removed) must not make those accessors raise."""
    valveBrowser = self._bareBrowser()
    slicer.mrmlScene.RemoveNode(valveBrowser.heartValveSequenceNode)
    self.assertIsNone(valveBrowser.heartValveSequenceNode)
    self.assertEqual(valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()[1], None)
    self.assertIsNone(valveBrowser.heartValveNode)
    self.assertIsNone(valveBrowser.valveModel)

  # ---------------------------------------------------------------------------------------------
  # Slice orientation
  # ---------------------------------------------------------------------------------------------

  def test_setSliceOrientations(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral", probePosition="UNKNOWN")
    factory.addTimePoint(valveBrowser, 1)
    axialMatrix = scene.rotationMatrixZ(30.0, translation=(5.0, -3.0, 2.0))
    valveBrowser.axialSliceToRasTransformNode.SetMatrixTransformToParent(axialMatrix)
    # Standalone slice nodes (adding slice nodes to the scene of a running application makes the
    # layout manager create views for them)
    axialNode, ortho1Node, ortho2Node = (slicer.vtkMRMLSliceNode() for _ in range(3))

    valveBrowser.setSliceOrientations(axialNode, ortho1Node, ortho2Node, 0)
    sliceToRas = axialNode.GetSliceToRAS()
    for r in range(3):
      self.assertAlmostEqual(sliceToRas.GetElement(r, 2), axialMatrix.GetElement(r, 2), places=5, msg="normal")
      self.assertAlmostEqual(sliceToRas.GetElement(r, 0), axialMatrix.GetElement(r, 0), places=5, msg="x axis")
      self.assertAlmostEqual(sliceToRas.GetElement(r, 3), axialMatrix.GetElement(r, 3), places=5, msg="origin")
    # Ortho views are rotated relative to the axial view (UNKNOWN preset: -90 deg about y / x)
    self.assertMatricesNotEqual(ortho1Node.GetSliceToRAS(), axialNode.GetSliceToRAS(), "ortho1")
    self.assertMatricesNotEqual(ortho2Node.GetSliceToRAS(), axialNode.GetSliceToRAS(), "ortho2")
    self.assertMatricesNotEqual(ortho1Node.GetSliceToRAS(), ortho2Node.GetSliceToRAS(), "ortho1 vs ortho2")
    for r in range(3):
      self.assertAlmostEqual(ortho1Node.GetSliceToRAS().GetElement(r, 3), axialMatrix.GetElement(r, 3), places=5)

    # The ortho rotation must not change the axial view
    before = vtk.vtkMatrix4x4()
    before.DeepCopy(axialNode.GetSliceToRAS())
    ortho1Before = vtk.vtkMatrix4x4()
    ortho1Before.DeepCopy(ortho1Node.GetSliceToRAS())
    valveBrowser.setSliceOrientations(axialNode, ortho1Node, ortho2Node, 45)
    self.assertMatricesEqual(axialNode.GetSliceToRAS(), before, msg="axial unaffected by ortho rotation")
    self.assertMatricesNotEqual(ortho1Node.GetSliceToRAS(), ortho1Before, "ortho1 rotated")

    # Explicit position and matrix; None slice nodes tolerated
    position = [1.0, 2.0, 3.0]
    valveBrowser.setSlicePositionAndOrientation(axialNode, None, None, position, 0)
    for r in range(3):
      self.assertAlmostEqual(axialNode.GetSliceToRAS().GetElement(r, 3), position[r], places=5)
    valveBrowser.setSlicePositionAndOrientation(None, None, None, position, 0, axialSliceToRas=vtk.vtkMatrix4x4())

  # ---------------------------------------------------------------------------------------------
  # HeartValves helpers
  # ---------------------------------------------------------------------------------------------

  def test_browser_lookups(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    hv = HeartValveLib.HeartValves
    self.assertEqual(hv.getSequenceBrowserNodeForMasterOutputNode(factory.volumeProxyNode).GetID(),
                     factory.volumeBrowserNode.GetID())
    self.assertEqual(hv.getSequenceBrowserNodeForMasterOutputNode(valveBrowser.heartValveNode).GetID(),
                     valveBrowser.valveBrowserNode.GetID())
    unrelated = scene.createVolumeNode("Unrelated")
    self.assertIsNone(hv.getSequenceBrowserNodeForMasterOutputNode(unrelated))
    self.assertEqual([n.GetID() for n in hv.getBrowserNodesForSequenceNode(factory.volumeSequenceNode)],
                     [factory.volumeBrowserNode.GetID()])
    self.assertEqual(hv.getBrowserNodesForSequenceNode(valveBrowser.heartValveSequenceNode)[0].GetID(),
                     valveBrowser.valveBrowserNode.GetID())
    # HeartValveLib re-exports the same function objects
    self.assertIs(HeartValveLib.getSequenceBrowserNodeForMasterOutputNode, hv.getSequenceBrowserNodeForMasterOutputNode)

  def test_goToAnalyzedFrame(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.addTimePoint(valveBrowser, 3)
    factory.selectFrame(0)
    HeartValveLib.goToAnalyzedFrame(valveBrowser.valveModel)
    self.assertEqual(factory.volumeBrowserNode.GetSelectedItemNumber(), 3)
    scene.selectIndexValue(valveBrowser.valveBrowserNode, factory.indexValue(1))
    HeartValveLib.goToAnalyzedFrame(valveBrowser.valveModel)
    self.assertEqual(factory.volumeBrowserNode.GetSelectedItemNumber(), 1)
    HeartValveLib.goToAnalyzedFrame(None)  # must not raise
    HeartValveLib.HeartValves.setSequenceBrowserNodeDisplayIndex(valveBrowser.valveModel)
    self.assertEqual(factory.volumeBrowserNode.GetIndexDisplayMode(), factory.volumeBrowserNode.IndexDisplayAsIndex)

  def test_removeLeafletVolumesFromSliceViews(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(2,), roi=True, segmentation=True)
    valveModel = valveBrowser.valveModel
    leafletVolume = valveModel.leafletVolumeNode
    self.assertIsNotNone(leafletVolume)
    composite = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSliceCompositeNode", "TestComposite")
    composite.SetBackgroundVolumeID(leafletVolume.GetID())
    composite.SetForegroundVolumeID(leafletVolume.GetID())
    untouched = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSliceCompositeNode", "Untouched")
    untouched.SetBackgroundVolumeID(factory.volumeProxyNode.GetID())

    HeartValveLib.HeartValves.removeLeafletVolumesFromSliceViews()
    self.assertEqual(composite.GetBackgroundVolumeID(), factory.volumeProxyNode.GetID(),
                     "leaflet volume replaced by the valve volume in the background")
    self.assertIsNone(composite.GetForegroundVolumeID(), "leaflet volume cleared from the foreground")
    self.assertEqual(untouched.GetBackgroundVolumeID(), factory.volumeProxyNode.GetID())
    # Without any leaflet volume the function must be a no-op
    slicer.mrmlScene.Clear(0)
    self.resetHeartValveLibCaches()
    HeartValveLib.HeartValves.removeLeafletVolumesFromSliceViews()

  def test_removeUnusedVolumeNodes(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(2,), roi=True, segmentation=True)
    valveModel = valveBrowser.valveModel
    leafletVolume = valveModel.leafletVolumeNode
    unused = scene.createVolumeNode("Unused")
    HeartValveLib.HeartValves.removeUnusedVolumeNodes()
    self.assertNotInScene(unused, "unused volume removed")
    self.assertInScene(factory.volumeProxyNode, "valve volume kept")
    self.assertInScene(leafletVolume, "leaflet volume kept")

  # ---------------------------------------------------------------------------------------------
  # Caches
  # ---------------------------------------------------------------------------------------------

  def test_cache_returns_same_objects(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    hv = HeartValveLib.HeartValves
    self.assertIs(hv.getValveBrowser(valveBrowser.valveBrowserNode), valveBrowser)
    self.assertIs(hv.getValveModel(valveBrowser.heartValveNode), valveBrowser.valveModel)
    self.assertIs(valveBrowser.valveModel.valveBrowser, valveBrowser)
    self.assertIsNone(hv.getValveModel(None))

  def test_cache_new_node_never_resolves_to_old_browser(self):
    import HeartValveLib
    hv = HeartValveLib.HeartValves
    old = self._bareBrowser("Old")
    oldNode = old.valveBrowserNode
    slicer.mrmlScene.RemoveNode(oldNode)
    new = self._bareBrowser("New")
    self.assertIsNot(new, old)
    self.assertEqual(new.valveBrowserNode.GetName(), "New")
    self.assertIs(hv.getValveBrowser(new.valveBrowserNode), new)

  def test_cache_does_not_retain_removed_nodes(self):
    import HeartValveLib
    hv = HeartValveLib.HeartValves
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    browserNode = valveBrowser.valveBrowserNode
    heartValveNode = valveBrowser.heartValveNode
    self.assertIn(browserNode, hv.ValveBrowsers)
    self.assertIn(heartValveNode, hv.ValveModels)
    slicer.mrmlScene.Clear(0)
    self.assertNotIn(browserNode, hv.ValveBrowsers, "ValveBrowsers cache must not keep nodes removed from the scene")
    self.assertNotIn(heartValveNode, hv.ValveModels, "ValveModels cache must not keep nodes removed from the scene")
