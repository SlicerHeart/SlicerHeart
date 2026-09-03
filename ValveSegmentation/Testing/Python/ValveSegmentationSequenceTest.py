"""
ValveSegmentationSequenceTest.py

Tests for the sequence (per-time-point) behaviour of the ValveSegmentation module: the clipped
leaflet volume computation, per-time-point ROI/segmentation handling through the widget slots and
the segment ID synchronisation between time points.

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
      self.assertIsNone(widget.editingSequenceValue)
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

  def test_widget_updateSegmentIDs_matches_terminology(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3), roi=True)
    valveModel = valveBrowser.valveModel
    widget = self._widget()
    try:
      self._bindWidget(widget, valveBrowser)
      # Time point 3 (current): reference segmentation with terminology tags
      segmentation3 = valveModel.initializeLeafletSegmentation()
      seg = segmentation3.GetSegmentation()
      scene.addSphereSegment(segmentation3, "Anterior", "Anterior leaflet", (1.2, 0, 0), 1.2, (1, 0, 0))
      scene.addSphereSegment(segmentation3, "Posterior", "Posterior leaflet", (-1.2, 0, 0), 1.2, (0, 1, 0))
      seg.GetSegment("Anterior").SetTag("TerminologyEntry", self.TERMINOLOGY_A)
      seg.GetSegment("Posterior").SetTag("TerminologyEntry", self.TERMINOLOGY_P)
      slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(valveBrowser.valveBrowserNode, segmentation3)
      ids3 = sorted(seg.GetSegmentIDs())

      # Time point 1: the user creates the same leaflets with generic IDs, in the other order
      factory.switchTo(valveBrowser, 1)
      slicer.app.processEvents()
      widget.onValveBrowserNodeModified()
      self.assertEqual(widget.editingSequenceValue, factory.indexValue(1))
      segmentation1 = valveModel.initializeLeafletSegmentation()
      seg1 = segmentation1.GetSegmentation()
      for segmentId in list(seg1.GetSegmentIDs()):
        if segmentId != "ValveMask":
          seg1.RemoveSegment(segmentId)
      scene.addSphereSegment(segmentation1, "Segment_1", "Posterior leaflet", (-1.2, 0, 0), 1.2, (0, 1, 0))
      scene.addSphereSegment(segmentation1, "Segment_2", "Anterior leaflet", (1.2, 0, 0), 1.2, (1, 0, 0))
      seg1.GetSegment("Segment_1").SetTag("TerminologyEntry", self.TERMINOLOGY_P)
      seg1.GetSegment("Segment_2").SetTag("TerminologyEntry", self.TERMINOLOGY_A)
      slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(valveBrowser.valveBrowserNode, segmentation1)

      # Leaving time point 1 synchronises its segment IDs with the other time points
      factory.switchTo(valveBrowser, 3)
      slicer.app.processEvents()
      widget.onValveBrowserNodeModified()
      self.assertEqual(widget.editingSequenceValue, factory.indexValue(3))
      stored1 = valveModel.leafletSegmentationSequenceNode.GetDataNodeAtValue(factory.indexValue(1)).GetSegmentation()
      self.assertEqual(sorted(stored1.GetSegmentIDs()), ["Anterior", "Posterior", "ValveMask"],
                       "segment IDs of the edited time point follow the terminology of the reference time point")
      self.assertEqual(stored1.GetSegment("Anterior").GetName(), "Anterior leaflet")
      self.assertEqual(stored1.GetSegment("Posterior").GetName(), "Posterior leaflet")
      self.assertEqual(sorted(valveModel.leafletSegmentationNode.GetSegmentation().GetSegmentIDs()), ids3,
                       "reference time point unchanged")
      # Geometry kept with the renamed segments
      factory.switchTo(valveBrowser, 1)
      slicer.app.processEvents()
      labelmap = slicer.vtkOrientedImageData()
      self.assertTrue(valveModel.leafletSegmentationNode.GetBinaryLabelmapRepresentation("Anterior", labelmap))
      self.assertGreater(self._voxelCount(labelmap), 0)
    finally:
      self._unbindWidget(widget)

  def test_widget_updateSegmentIDs_keeps_unmatched_ids(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3), roi=True)
    valveModel = valveBrowser.valveModel
    widget = self._widget()
    try:
      self._bindWidget(widget, valveBrowser)
      segmentation3 = valveModel.initializeLeafletSegmentation()
      scene.addSphereSegment(segmentation3, "Anterior", "Anterior leaflet", (1.2, 0, 0), 1.2, (1, 0, 0))
      segmentation3.GetSegmentation().GetSegment("Anterior").SetTag("TerminologyEntry", self.TERMINOLOGY_A)
      slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(valveBrowser.valveBrowserNode, segmentation3)
      factory.switchTo(valveBrowser, 1)
      slicer.app.processEvents()
      widget.onValveBrowserNodeModified()
      segmentation1 = valveModel.initializeLeafletSegmentation()
      seg1 = segmentation1.GetSegmentation()
      for segmentId in list(seg1.GetSegmentIDs()):
        if segmentId != "ValveMask":
          seg1.RemoveSegment(segmentId)
      scene.addSphereSegment(segmentation1, "Custom", "Custom structure", (0, 1.2, 0), 1.0, (0, 0, 1))
      scene.addSphereSegment(segmentation1, "Segment_9", "Anterior leaflet", (1.2, 0, 0), 1.2, (1, 0, 0))
      seg1.GetSegment("Segment_9").SetTag("TerminologyEntry", self.TERMINOLOGY_A)
      slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(valveBrowser.valveBrowserNode, segmentation1)
      factory.switchTo(valveBrowser, 3)
      slicer.app.processEvents()
      widget.onValveBrowserNodeModified()
      stored1 = valveModel.leafletSegmentationSequenceNode.GetDataNodeAtValue(factory.indexValue(1)).GetSegmentation()
      self.assertEqual(sorted(stored1.GetSegmentIDs()), ["Anterior", "Custom", "ValveMask"])
      self.assertEqual(stored1.GetNumberOfSegments(), 3, "no segment lost")
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
