"""
ValveSegmentationSequenceTest.py

Tests for the sequence (per-time-point) behaviour of the ValveSegmentation module: the clipped
leaflet volume computation, per-time-point ROI/segmentation handling through the widget slots and
giving a leaflet the same segment ID at all time points.

All tests run on a small synthetic volume sequence (no downloads).
"""

import os
import sys

import numpy as np
import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTLIB_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "ValveAnnulusAnalysis", "Testing", "Python"))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class ValveSegmentationSequenceTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ValveSegmentationSequenceTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for per-time-point valve segmentation."
    self.parent.acknowledgementText = ""


class ValveSegmentationSequenceTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class ValveSegmentationSequenceTestLogic(ScriptedLoadableModuleLogic):
  pass


class ValveSegmentationSequenceTestTest(SlicerHeartTestCase):

  TERMINOLOGY_A = ("Segmentation category and type - 3D Slicer General Anatomy list~SCT^123037004^Anatomical Structure"
                   "~SCT^7986501^Anterior leaflet~^^~Anatomic codes - DICOM master list~^^~^^")
  TERMINOLOGY_P = ("Segmentation category and type - 3D Slicer General Anatomy list~SCT^123037004^Anatomical Structure"
                   "~SCT^7986502^Posterior leaflet~^^~Anatomic codes - DICOM master list~^^~^^")

  # ---------------------------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _voxelCount(orientedImage):
    if orientedImage is None or orientedImage.GetNumberOfPoints() == 0:
      return 0
    from vtk.util import numpy_support
    return int(np.count_nonzero(numpy_support.vtk_to_numpy(orientedImage.GetPointData().GetScalars())))

  def _widget(self):
    widget = slicer.modules.valvesegmentation.widgetRepresentation().self()
    self.assertIsNotNone(widget)
    return widget

  def _bindWidget(self, widget, valveBrowser):
    from HeartValveLib import ValveRoi
    self.assertEqual(sorted(widget.roiGeometryWidgets), sorted(ValveRoi.GEOMETRY_PARAMS),
                     "ROI geometry widgets missing: the module widget's setup() did not complete")
    widget.setHeartValveBrowserNode(valveBrowser.valveBrowserNode)
    slicer.app.processEvents()
    widget.updateGUIFromHeartValveNode()

  def _unbindWidget(self, widget):
    try:
      widget.setHeartValveBrowserNode(None)
    finally:
      slicer.app.processEvents()

  # ---------------------------------------------------------------------------------------------
  # Logic
  # ---------------------------------------------------------------------------------------------

  def test_getLeafletVolumeClippedAxisAligned(self):
    from ValveSegmentation import ValveSegmentationLogic
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(2,), roi=True, segmentation=True)
    valveModel = valveBrowser.valveModel
    image = ValveSegmentationLogic.getLeafletVolumeClippedAxisAligned(valveModel)
    self.assertIsNotNone(image)
    dims = image.GetDimensions()
    self.assertTrue(all(d > 1 for d in dims), dims)
    self.assertAlmostEqual(image.GetSpacing()[0], 0.3, places=5)
    inside = self._voxelCount(image)
    self.assertGreater(inside, 0, "voxels inside the ROI")
    self.assertLess(inside, dims[0] * dims[1] * dims[2], "voxels outside the ROI are cleared")
    # Shrinking the ROI reduces the number of voxels inside
    valveModel.valveRoi.setRoiGeometry({"ValveRoiScale": 60, "ValveRoiTopDistance": 1, "ValveRoiTopScale": 50,
                                        "ValveRoiBottomDistance": 1, "ValveRoiBottomScale": 50})
    smaller = ValveSegmentationLogic.getLeafletVolumeClippedAxisAligned(valveModel)
    self.assertLess(self._voxelCount(smaller), inside)
    # The result is defined in the Probe coordinate system: its geometry follows the axial orientation
    matrix = vtk.vtkMatrix4x4()
    smaller.GetImageToWorldMatrix(matrix)
    self.assertNotEqual([matrix.GetElement(r, c) for r in range(3) for c in range(3)], [1, 0, 0, 0, 1, 0, 0, 0, 1],
                        "TTE apical axial orientation is not axis aligned with the probe")

  def test_getLeafletVolumeClippedAxisAligned_without_volume(self):
    import HeartValveLib
    from ValveSegmentation import ValveSegmentationLogic
    browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "Bare")
    browserNode.SetAttribute("ModuleName", "HeartValve")
    valveBrowser = HeartValveLib.HeartValves.getValveBrowser(browserNode)
    valveBrowser.addTimePoint("0.5")
    self.assertIsNone(ValveSegmentationLogic.getLeafletVolumeClippedAxisAligned(valveBrowser.valveModel))

  def test_getLeafletVolumeClippedAxisAligned_without_segmentation(self):
    from ValveSegmentation import ValveSegmentationLogic
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(2,), roi=True, segmentation=False)
    valveModel = valveBrowser.valveModel
    self.assertIsNone(valveModel.leafletSegmentationNode)
    # The clipped volume only depends on the valve volume, the axial orientation and the ROI
    image = ValveSegmentationLogic.getLeafletVolumeClippedAxisAligned(valveModel)
    self.assertIsNotNone(image, "clipped volume must be computable before a segmentation exists")
    self.assertGreater(self._voxelCount(image), 0)

  # ---------------------------------------------------------------------------------------------
  # Widget slots
  # ---------------------------------------------------------------------------------------------

  def test_widget_without_valve(self):
    widget = self._widget()
    try:
      widget.setHeartValveBrowserNode(None)
      slicer.app.processEvents()
      self.assertIsNone(widget.valveModel)
      widget.updateGUIFromHeartValveNode()
      self.assertFalse(widget.ui.addSegmentationButton.enabled)
      self.assertFalse(widget.ui.addValveRoiButton.enabled)
      self.assertFalse(widget.ui.segmentEditorWidget.enabled)
      widget.onValveBrowserNodeModified()
      slicer.app.processEvents()
      self.assertIsNone(widget.leafletSegmentsSnapshot)
    finally:
      self._unbindWidget(widget)

  def test_widget_roi_per_time_point(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3))
    valveModel = valveBrowser.valveModel
    widget = self._widget()
    try:
      self._bindWidget(widget, valveBrowser)
      self.assertIs(widget.valveModel, valveModel)
      self.assertTrue(widget.ui.addValveRoiButton.enabled)
      self.assertFalse(widget.ui.removeValveRoiButton.enabled)
      widget.onAddValveRoiButtonClicked()
      widget.updateGUIFromHeartValveNode()
      roiSequence = valveModel.valveRoiSequenceNode
      self.assertIsNotNone(roiSequence)
      self.assertSequenceIndexValues(roiSequence, [factory.indexValue(3)], "ROI only at the current time point")
      self.assertGreater(valveModel.valveRoiModelNode.GetPolyData().GetNumberOfPoints(), 0)
      self.assertFalse(widget.ui.addValveRoiButton.enabled)
      self.assertTrue(widget.ui.removeValveRoiButton.enabled)
      widget.onAddValveRoiButtonClicked()  # no-op when already present
      self.assertSequenceIndexValues(roiSequence, [factory.indexValue(3)])

      factory.switchTo(valveBrowser, 1)
      slicer.app.processEvents()
      widget.updateGUIFromHeartValveNode()
      self.assertIsNone(valveModel.valveRoiModelNode)
      self.assertTrue(widget.ui.addValveRoiButton.enabled)
      widget.onAddValveRoiButtonClicked()
      self.assertSequenceIndexValues(roiSequence, [factory.indexValue(1), factory.indexValue(3)])
      self.assertGreater(valveModel.valveRoiModelNode.GetPolyData().GetNumberOfPoints(), 0, "ROI generated for time point 1")
      widget.onRemoveValveRoiButtonClicked()
      self.assertSequenceIndexValues(roiSequence, [factory.indexValue(3)])
      self.assertIsNone(valveModel.valveRoiModelNode)
      widget.onRemoveValveRoiButtonClicked()  # no-op when absent
      factory.switchTo(valveBrowser, 3)
      slicer.app.processEvents()
      self.assertIsNotNone(valveModel.valveRoiModelNode, "time point 3 keeps its ROI")
    finally:
      self._unbindWidget(widget)

  def test_widget_segmentation_per_time_point(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3), roi=True)
    valveModel = valveBrowser.valveModel
    widget = self._widget()
    try:
      self._bindWidget(widget, valveBrowser)
      self.assertTrue(widget.ui.addSegmentationButton.enabled)
      widget.onAddSegmentationButtonClicked()
      segmentation = valveModel.leafletSegmentationNode
      self.assertIsNotNone(segmentation)
      self.assertSequenceIndexValues(valveModel.leafletSegmentationSequenceNode, [factory.indexValue(3)])
      self.assertTrue(widget.ui.removeSegmentationButton.enabled)
      self.assertTrue(widget.ui.segmentEditorWidget.enabled)
      self.assertEqual(widget.ui.segmentEditorWidget.segmentationNode().GetID(), segmentation.GetID())
      self.assertIn("ValveMask", segmentation.GetSegmentation().GetSegmentIDs())
      factory.switchTo(valveBrowser, 1)
      slicer.app.processEvents()
      widget.updateGUIFromHeartValveNode()
      self.assertIsNone(valveModel.leafletSegmentationNode)
      self.assertFalse(widget.ui.segmentEditorWidget.enabled, "no segmentation at this time point")
      self.assertIsNone(widget.ui.segmentEditorWidget.segmentationNode())
      widget.onRemoveSegmentationButtonClicked()  # no-op
      self.assertSequenceIndexValues(valveModel.leafletSegmentationSequenceNode, [factory.indexValue(3)])
      factory.switchTo(valveBrowser, 3)
      slicer.app.processEvents()
      widget.updateGUIFromHeartValveNode()
      widget.onRemoveSegmentationButtonClicked()
      self.assertEqual(valveModel.leafletSegmentationSequenceNode.GetNumberOfDataNodes(), 0)
      self.assertIsNone(valveModel.leafletSegmentationNode)
    finally:
      self._unbindWidget(widget)

  # ---------------------------------------------------------------------------------------------
  # Segment IDs of a leaflet are the same at all time points
  # ---------------------------------------------------------------------------------------------

  FRAMES = (1, 3, 5)

  def _createSegmentedValve(self, factory, frames=FRAMES, terminologies=False):
    """Valve with Anterior and Posterior leaflets segmented (non-empty) at every time point."""
    valveBrowser = factory.createAnnotatedValve("mitral", frames=frames, roi=True, segmentation=True)
    if terminologies:
      for frameIndex in frames:
        factory.switchTo(valveBrowser, frameIndex)
        segmentation = valveBrowser.valveModel.leafletSegmentationNode.GetSegmentation()
        segmentation.GetSegment("Anterior").SetTag("TerminologyEntry", self.TERMINOLOGY_A)
        segmentation.GetSegment("Posterior").SetTag("TerminologyEntry", self.TERMINOLOGY_P)
        self._saveProxy(valveBrowser)
    return valveBrowser

  @staticmethod
  def _saveProxy(valveBrowser):
    segmentationNode = valveBrowser.valveModel.leafletSegmentationNode
    if segmentationNode:
      slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(valveBrowser.valveBrowserNode, segmentationNode)

  def _segments(self, valveBrowser, factory, frameIndex):
    """{segmentId: (name, terminology, hasContent)} of the leaflet segments stored for a time point."""
    from HeartValveLib.ValveModel import ValveModel
    self._saveProxy(valveBrowser)
    item = valveBrowser.valveModel.leafletSegmentationSequenceNode.GetDataNodeAtValue(factory.indexValue(frameIndex))
    self.assertIsNotNone(item, f"frame {frameIndex}: leaflet segmentation")
    segmentation = item.GetSegmentation()
    result = {}
    for segmentId in segmentation.GetSegmentIDs():
      if segmentId == "ValveMask":
        continue
      definition = ValveModel.getSegmentDefinition(segmentation.GetSegment(segmentId))
      result[segmentId] = (definition["name"], definition["terminology"], ValveModel.segmentHasContent(segmentation, segmentId))
    return result

  def _bindSegmentationWidget(self, widget, valveBrowser):
    self._bindWidget(widget, valveBrowser)
    slicer.app.processEvents()

  def test_widget_switching_time_points_changes_no_segment(self):
    factory = NewFormatValveFactory()
    valveBrowser = self._createSegmentedValve(factory, terminologies=True)
    widget = self._widget()
    try:
      self._bindSegmentationWidget(widget, valveBrowser)
      expected = {frameIndex: self._segments(valveBrowser, factory, frameIndex) for frameIndex in self.FRAMES}
      for frameIndex in self.FRAMES + self.FRAMES:
        factory.switchTo(valveBrowser, frameIndex)
        slicer.app.processEvents()
        widget.onValveBrowserNodeModified()
        slicer.app.processEvents()
      self.assertEqual({frameIndex: self._segments(valveBrowser, factory, frameIndex) for frameIndex in self.FRAMES}, expected,
                       "segments and terminologies are kept (switching replaces every segment of the proxy node)")
    finally:
      self._unbindWidget(widget)

  def test_widget_segment_given_the_terminology_of_a_leaflet_becomes_that_leaflet(self):
    factory = NewFormatValveFactory()
    valveBrowser = self._createSegmentedValve(factory, frames=(3, 5), terminologies=True)
    valveModel = valveBrowser.valveModel
    widget = self._widget()
    try:
      self._bindSegmentationWidget(widget, valveBrowser)
      # New time point: the leaflets are there, empty
      factory.addTimePoint(valveBrowser, 1)
      slicer.app.processEvents()
      widget.updateGUIFromHeartValveNode()
      widget.onAddSegmentationButtonClicked()
      slicer.app.processEvents()
      self.assertEqual({segmentId: segment[2] for segmentId, segment in self._segments(valveBrowser, factory, 1).items()},
                       {"Anterior": False, "Posterior": False})
      # The user segments the posterior leaflet with a new segment, then picks its terminology
      segmentationNode = valveModel.leafletSegmentationNode
      scene.addSphereSegment(segmentationNode, "Segment_1", "Posterior leaflet", (-1.2, 0, 0), 1.2, (0, 1, 0))
      slicer.app.processEvents()
      segmentationNode.GetSegmentation().GetSegment("Segment_1").SetTag("TerminologyEntry", self.TERMINOLOGY_P)
      slicer.app.processEvents()
      segments1 = self._segments(valveBrowser, factory, 1)
      self.assertEqual(list(segments1.keys()), ["Anterior", "Posterior"])
      self.assertEqual(segments1["Posterior"], ("Posterior leaflet", self.TERMINOLOGY_P, True), "the new segment is the posterior leaflet")
      for frameIndex in (3, 5):
        segments = self._segments(valveBrowser, factory, frameIndex)
        self.assertEqual(list(segments.keys()), ["Anterior", "Posterior"], f"frame {frameIndex}")
        self.assertTrue(segments["Posterior"][2], f"frame {frameIndex}: posterior leaflet kept")
      # Geometry kept with the renamed segment
      labelmap = slicer.vtkOrientedImageData()
      self.assertTrue(segmentationNode.GetBinaryLabelmapRepresentation("Posterior", labelmap))
      self.assertGreater(self._voxelCount(labelmap), 0)
    finally:
      self._unbindWidget(widget)

  def test_widget_segment_with_a_new_terminology_keeps_its_id(self):
    factory = NewFormatValveFactory()
    valveBrowser = self._createSegmentedValve(factory, terminologies=True)
    valveModel = valveBrowser.valveModel
    widget = self._widget()
    try:
      self._bindSegmentationWidget(widget, valveBrowser)
      factory.switchTo(valveBrowser, 3)
      slicer.app.processEvents()
      segmentationNode = valveModel.leafletSegmentationNode
      scene.addSphereSegment(segmentationNode, "Custom", "Custom structure", (0, 1.2, 0), 1.0, (0, 0, 1))
      slicer.app.processEvents()
      customTerminology = self.TERMINOLOGY_A.replace("7986501^Anterior leaflet", "7986503^Commissure")
      segmentationNode.GetSegmentation().GetSegment("Custom").SetTag("TerminologyEntry", customTerminology)
      # A leaflet that has content at this time point is not replaced, even with the same terminology
      scene.addSphereSegment(segmentationNode, "Segment_9", "Anterior leaflet", (1.2, 0, 0), 1.2, (1, 0, 0))
      slicer.app.processEvents()
      segmentationNode.GetSegmentation().GetSegment("Segment_9").SetTag("TerminologyEntry", self.TERMINOLOGY_A)
      slicer.app.processEvents()
      segments = self._segments(valveBrowser, factory, 3)
      self.assertEqual(list(segments.keys()), ["Anterior", "Posterior", "Custom", "Segment_9"])
      self.assertEqual(segments["Custom"][1], customTerminology)
      self.assertTrue(segments["Anterior"][2], "anterior leaflet kept")
    finally:
      self._unbindWidget(widget)

  def test_widget_survives_scene_clear(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,), roi=True, segmentation=True)
    widget = self._widget()
    try:
      self._bindWidget(widget, valveBrowser)
      slicer.mrmlScene.Clear(0)
      slicer.app.processEvents()
      widget.updateGUIFromHeartValveNode()
      widget.onValveBrowserNodeModified()
    finally:
      self._unbindWidget(widget)
