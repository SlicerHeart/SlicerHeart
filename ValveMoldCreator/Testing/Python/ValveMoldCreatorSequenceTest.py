"""
ValveMoldCreatorSequenceTest.py

Tests for the ValveMoldCreator logic on a valve stored in the sequence format: the mold generation
and annulus projection steps run on the current time point of a valve browser, and the projected
annulus curve lives in the valve's coordinate system.

The real-data test uses the SlicerHeart "Mitral" sample (4D ultrasound plus a leaflet segmentation of
frame 6) and is skipped when the sample cannot be downloaded.
"""

import os
import sys

import slicer
from slicer.ScriptedLoadableModule import *

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTLIB_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "ValveAnnulusAnalysis", "Testing", "Python"))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class ValveMoldCreatorSequenceTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ValveMoldCreatorSequenceTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "ValveMoldCreator", "Sequences"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for ValveMoldCreator on sequence-format valves."
    self.parent.acknowledgementText = ""


class ValveMoldCreatorSequenceTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class ValveMoldCreatorSequenceTestLogic(ScriptedLoadableModuleLogic):
  pass


class ValveMoldCreatorSequenceTestTest(SlicerHeartTestCase):

  MITRAL_SEGMENTATION_FRAME = 5  # the sample's leaflet segmentation is of frame 6 (1-based)

  def _parameterNode(self, logic):
    import ValveMoldCreator
    parameterNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode")
    parameterNode.SetAttribute("ModuleName", "ValveMoldCreator")
    logic.setDefaultParameters(parameterNode)
    return parameterNode

  def _mitralSampleValve(self):
    """Valve browser on the Mitral sample with one time point at the segmented frame, annotated with the
    reference annulus contour and landmarks, and the sample's leaflet segmentation."""
    import ValveModelTest
    sampleSegmentationNodes = []
    volumeBrowserNode = scene.loadMitralSample()
    # loadMitralSample drops the bundled segmentation; load it again from the sample cache
    import SampleData
    try:
      segmentationNode = SampleData.SampleDataLogic().downloadFromSource(
        SampleData.SampleDataSource(
          sampleName="MitralLeaflets",
          uris="https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/Mitral_f06_Leaflets.seg.nrrd",
          checksums="SHA256:67d43571d9266e8b056e14f5bd4099e5fffdcaf871786720a9d45b601be12814",
          fileNames="Mitral_f06_Leaflets.seg.nrrd",
          loadFileType="SegmentationFile",
          nodeNames="Mitral_f06_Leaflets"))[0]
    except Exception as e:  # noqa: BLE001
      import unittest
      raise unittest.SkipTest(f"Mitral leaflet segmentation not available: {e}")
    factory = NewFormatValveFactory(volumeBrowserNode=volumeBrowserNode)
    valveBrowser = factory.createValveBrowser("mitral", probePosition="TTE_APICAL")
    contour = ValveModelTest.ValveModelTestTest.MITRAL_ANNULUS_CONTOUR_FRAME0
    factory.addTimePoint(valveBrowser, self.MITRAL_SEGMENTATION_FRAME, phase="mid-systole")
    valveModel = valveBrowser.valveModel
    valveModel.setAnnulusContourPoints(contour)
    valveModel.setValveLabels(ValveModelTest.ValveModelTestTest._annulusLandmarkLabels(contour))
    leafletSegmentationNode = valveModel.initializeLeafletSegmentation()
    self.assertIsNotNone(leafletSegmentationNode)
    # Copy the sample's leaflets into the valve's segmentation (same geometry: both are of frame 6)
    sourceSegmentation = segmentationNode.GetSegmentation()
    for index in range(sourceSegmentation.GetNumberOfSegments()):
      segmentId = sourceSegmentation.GetNthSegmentID(index)
      self.assertTrue(leafletSegmentationNode.GetSegmentation().CopySegmentFromSegmentation(sourceSegmentation, segmentId))
    slicer.mrmlScene.RemoveNode(segmentationNode)
    valveModel.updateLeafletModelsFromSegmentation()
    return valveBrowser

  # ---------------------------------------------------------------------------------------------
  # Synthetic valve
  # ---------------------------------------------------------------------------------------------

  def test_projected_annulus_curve_is_in_valve_coordinates(self):
    """The projected annulus curve node is placed under the valve's probe transform, in its folder."""
    import vtk
    import ValveMoldCreator
    factory = NewFormatValveFactory(numFrames=4)
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,), phases=("mid-systole",))
    valveModel = valveBrowser.valveModel
    logic = ValveMoldCreator.ValveMoldCreatorLogic()
    points = vtk.vtkPoints()
    for p in factory.contourPoints(1):
      points.InsertNextPoint(p)
    curveNode = logic.createProjectedAnnulusCurveNode(points, valveModel, "Projected")
    self.assertEqual(curveNode.GetNumberOfControlPoints(), points.GetNumberOfPoints())
    self.assertParentTransformIs(curveNode, valveModel.getProbeToRasTransformNode())
    self.assertShParentIs(curveNode, valveModel.heartValveNode)
    self.assertControlPointsEqual(curveNode, factory.contourPoints(1))

  def test_mold_logic_uses_current_time_point(self):
    """Mold generation reads the annulus of the time point the valve browser shows."""
    import ValveMoldCreator
    factory = NewFormatValveFactory(numFrames=4)
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3), phases=("mid-systole", "end-diastole"),
                                                segmentation=True)
    valveModel = valveBrowser.valveModel
    logic = ValveMoldCreator.ValveMoldCreatorLogic()
    factory.switchTo(valveBrowser, 1)
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, factory.contourPoints(1))
    lowest1 = logic.getLowestAnnulusPoint(valveModel)
    self.assertTrue(abs(lowest1) < 10.0)
    factory.switchTo(valveBrowser, 3)
    self.assertControlPointsEqual(valveModel.annulusContourCurveNode, factory.contourPoints(3))
    self.assertControlPointsNotEqual(valveModel.annulusContourCurveNode, factory.contourPoints(1))
    lowest3 = logic.getLowestAnnulusPoint(valveModel)
    self.assertTrue(abs(lowest3) < 10.0)
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), 3)
    # the leaflet segmentation of the shown time point is what the mold is built from
    segmentationNode = valveModel.getLeafletSegmentationNode()
    self.assertIsNotNone(segmentationNode)
    self.assertGreater(segmentationNode.GetSegmentation().GetNumberOfSegments(), 0)

  # ---------------------------------------------------------------------------------------------
  # Real data
  # ---------------------------------------------------------------------------------------------

  def test_real_data_mold_generation(self):
    import ValveMoldCreator
    from ValveMoldCreator import (DEFAULT_SEG_NAME_MOLD, DEFAULT_SEG_NAME_PROJECTED_ANNULUS,
                                  DEFAULT_SEG_NAME_FINAL_MOLD, DEFAULT_SEG_NAME_TOP_MOLD)
    valveBrowser = self._mitralSampleValve()
    valveModel = valveBrowser.valveModel
    self.assertEqual(valveModel.getValveVolumeSequenceIndex(), self.MITRAL_SEGMENTATION_FRAME)
    segmentationNode = valveModel.getLeafletSegmentationNode()
    segmentation = segmentationNode.GetSegmentation()
    leafletSegmentIds = [segmentation.GetNthSegmentID(i) for i in range(segmentation.GetNumberOfSegments())
                         if "leaflet" in segmentation.GetNthSegment(i).GetName().lower()]
    self.assertGreaterEqual(len(leafletSegmentIds), 2, "sample has leaflet segments")

    logic = ValveMoldCreator.ValveMoldCreatorLogic()
    parameterNode = self._parameterNode(logic)
    logic.generateMold(valveModel, parameterNode)
    for segmentName in (DEFAULT_SEG_NAME_MOLD, DEFAULT_SEG_NAME_TOP_MOLD):
      self.assertIsNotNone(segmentation.GetSegment(segmentName), segmentName)
    self.assertGreater(segmentationNode.GetClosedSurfaceInternalRepresentation(DEFAULT_SEG_NAME_MOLD).GetNumberOfPoints(), 0)
    # the mold segment of the shown time point is saved in the segmentation sequence
    valveBrowserNode = valveBrowser.valveBrowserNode
    segmentationSequenceNode = valveBrowserNode.GetSequenceNode(segmentationNode)
    self.assertIsNotNone(segmentationSequenceNode)
    storedSegmentation = segmentationSequenceNode.GetNthDataNode(0).GetSegmentation()
    self.assertIsNotNone(storedSegmentation.GetSegment(DEFAULT_SEG_NAME_MOLD), "mold segment saved in the sequence")

    if not hasattr(slicer.modules, "markupstomodel"):
      import unittest
      raise unittest.SkipTest("annulus projection needs the MarkupsToModel extension")
    projectedCurveNode = logic.projectAnnulus(valveModel, parameterNode)
    self.assertGreater(projectedCurveNode.GetNumberOfControlPoints(), 0)
    self.assertParentTransformIs(projectedCurveNode, valveModel.getProbeToRasTransformNode())
    self.assertIsNotNone(segmentation.GetSegment(DEFAULT_SEG_NAME_PROJECTED_ANNULUS))
    self.assertFalse(projectedCurveNode.GetDisplayNode().GetVisibility())
    logic.subtractAnnulus(valveModel)

    logic.exportMoldToModel(valveModel)
    self.assertIsNotNone(segmentation.GetSegment(DEFAULT_SEG_NAME_FINAL_MOLD))
    modelNode = logic.getValveModelChildItemByName(valveModel, f"{DEFAULT_SEG_NAME_FINAL_MOLD}_Model")
    self.assertIsNotNone(modelNode, "final mold model is created in the valve folder")
    self.assertGreater(modelNode.GetPolyData().GetNumberOfPoints(), 0)
