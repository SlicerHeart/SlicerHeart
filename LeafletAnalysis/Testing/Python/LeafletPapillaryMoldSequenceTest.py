"""
LeafletPapillaryMoldSequenceTest.py

Tests for the sequence-related behaviour of the LeafletAnalysis, ValvePapillaryAnalysis and
LeafletMoldGenerator module widgets: per-time-point coaptation and papillary muscle items, observer
teardown and the parts of LeafletMoldGenerator that were ported to markups curves.

The module widgets are obtained from the running application and driven through their slots.
"""

import os
import sys

import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTLIB_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "ValveAnnulusAnalysis", "Testing", "Python"))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class LeafletPapillaryMoldSequenceTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "LeafletPapillaryMoldSequenceTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "LeafletAnalysis", "ValvePapillaryAnalysis",
                                "LeafletMoldGenerator", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for LeafletAnalysis, ValvePapillaryAnalysis and LeafletMoldGenerator on sequences."
    self.parent.acknowledgementText = ""


class LeafletPapillaryMoldSequenceTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class LeafletPapillaryMoldSequenceTestLogic(ScriptedLoadableModuleLogic):
  pass


class LeafletPapillaryMoldSequenceTestTest(SlicerHeartTestCase):

  # ---------------------------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------------------------

  @staticmethod
  def _moduleWidget(name):
    return getattr(slicer.modules, name).widgetRepresentation().self()

  @staticmethod
  def _select(widget, heartValveNode):
    slicer.app.processEvents()
    widget.heartValveSelector.setCurrentNode(heartValveNode)
    slicer.app.processEvents()
    if heartValveNode is not None:
      widget.onHeartValveSelect(heartValveNode)

  @staticmethod
  def _shItem(node):
    return slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene).GetItemByDataNode(node)

  # ---------------------------------------------------------------------------------------------
  # LeafletAnalysis
  # ---------------------------------------------------------------------------------------------

  def test_leaflet_analysis_coaptation_time_points(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3), roi=True, segmentation=True)
    valveModel = valveBrowser.valveModel
    browserNode = valveBrowser.valveBrowserNode
    widget = self._moduleWidget("leafletanalysis")
    try:
      self._select(widget, valveBrowser.heartValveNode)
      self.assertIsNotNone(widget.valveModel)
      self.assertEqual(widget.valveSequenceBrowserWidget.valveBrowserNode.GetID(), browserNode.GetID())
      self.assertEqual(len(widget.valveModel.coaptationModels), 0)

      widget.addCoaptationSurface()
      coaptations = widget.valveModel.coaptationModels
      self.assertEqual(len(coaptations), 1)
      coaptation = coaptations[0]
      nodes = [coaptation.baseLine, coaptation.marginLine, coaptation.surfaceModelNode]
      for node in nodes:
        self.assertIsNotNone(browserNode.GetSequenceNode(node), f"{node.GetName()} is sequenced")
        self.assertTrue(widget.valveModel.isNodeSpecifiedForCurrentTimePoint(node), f"{node.GetName()} at frame 3")
      self.assertShParentNameIs(coaptation.surfaceModelNode, "Coaptation")

      factory.switchTo(valveBrowser, 1)
      slicer.app.processEvents()
      widget.coaptationSurfaceSelectionChanged()
      for node in nodes:
        self.assertFalse(widget.valveModel.isNodeSpecifiedForCurrentTimePoint(node), f"{node.GetName()} not at frame 1")
      self.assertTrue(widget.addCoaptationTimePointButton.enabled)
      self.assertFalse(widget.removeCoaptationTimePointButton.enabled)
      widget.onAddCoaptationTimePoint()
      for node in nodes:
        self.assertTrue(widget.valveModel.isNodeSpecifiedForCurrentTimePoint(node), f"{node.GetName()} added at frame 1")
      self.assertFalse(widget.addCoaptationTimePointButton.enabled)
      self.assertTrue(widget.removeCoaptationTimePointButton.enabled)
      widget.onRemoveCoaptationTimePoint()
      for node in nodes:
        self.assertFalse(widget.valveModel.isNodeSpecifiedForCurrentTimePoint(node), f"{node.GetName()} removed at frame 1")
      factory.switchTo(valveBrowser, 3)
      slicer.app.processEvents()
      for node in nodes:
        self.assertTrue(widget.valveModel.isNodeSpecifiedForCurrentTimePoint(node), f"{node.GetName()} kept at frame 3")
    finally:
      self._select(widget, None)

  def test_leaflet_analysis_remove_coaptation_keeps_roi(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3), roi=True, segmentation=True)
    valveModel = valveBrowser.valveModel
    roiSequence = valveModel.valveRoiSequenceNode
    widget = self._moduleWidget("leafletanalysis")
    try:
      self._select(widget, valveBrowser.heartValveNode)
      widget.addCoaptationSurface()
      self.assertEqual(len(widget.valveModel.coaptationModels), 1)
      self.assertSequenceHasItem(roiSequence, factory.indexValue(3))
      widget.removeCoaptationSurface()
      self.assertEqual(len(widget.valveModel.coaptationModels), 0)
      self.assertSequenceHasItem(roiSequence, factory.indexValue(3), "removing a coaptation surface must not delete the valve ROI")
      self.assertIsNotNone(valveModel.valveRoiModelNode)
    finally:
      self._select(widget, None)

  # ---------------------------------------------------------------------------------------------
  # ValvePapillaryAnalysis
  # ---------------------------------------------------------------------------------------------

  def test_papillary_analysis_time_points(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3))
    browserNode = valveBrowser.valveBrowserNode
    widget = self._moduleWidget("valvepapillaryanalysis")
    try:
      self._select(widget, valveBrowser.heartValveNode)
      self.assertIsNotNone(widget.valveModel)
      self.assertEqual(widget.valveSequenceBrowserWidget.valveBrowserNode.GetID(), browserNode.GetID())
      self.assertEqual(len(widget.valveModel.papillaryModels), 2, "papillary models created for the mitral valve")
      papillaryModel = widget.valveModel.papillaryModels[0]
      markupNode = papillaryModel.getPapillaryLineMarkupNode()
      widget.papillaryMusclesTreeView.setCurrentItem(self._shItem(markupNode))
      slicer.app.processEvents()
      widget.updateTimePointButtons()
      self.assertTrue(widget.valveModel.isNodeSpecifiedForCurrentTimePoint(markupNode), "created at the current time point")
      self.assertTrue(widget.removeTimePointButton.enabled)
      self.assertFalse(widget.addTimePointButton.enabled)
      widget.onRemoveTimePoint()
      self.assertFalse(widget.valveModel.isNodeSpecifiedForCurrentTimePoint(markupNode))
      self.assertTrue(widget.addTimePointButton.enabled)
      self.assertFalse(widget.papillaryMuscleLineMarkupPlaceWidget.enabled, "no placing without a time point")
      widget.onAddTimePoint()
      self.assertTrue(widget.valveModel.isNodeSpecifiedForCurrentTimePoint(markupNode))
      self.assertTrue(widget.papillaryMuscleLineMarkupPlaceWidget.enabled)
      widget.valveModel.setPapillaryLinePoints(papillaryModel, [[3, 0, -3], [2.4, 0, -1.5], [1.2, 0, 0]])
      self.assertTrue(papillaryModel.hasMusclePointsPlaced())
      factory.switchTo(valveBrowser, 1)
      slicer.app.processEvents()
      widget.onValveSequenceBrowserNodeModified()
      self.assertFalse(widget.valveModel.isNodeSpecifiedForCurrentTimePoint(markupNode), "not defined at frame 1")
      self.assertFalse(papillaryModel.hasMusclePointsPlaced())
      self.assertTrue(widget.addTimePointButton.enabled)
      factory.switchTo(valveBrowser, 3)
      slicer.app.processEvents()
      widget.onValveSequenceBrowserNodeModified()
      self.assertTrue(papillaryModel.hasMusclePointsPlaced(), "points of frame 3 restored")
    finally:
      self._select(widget, None)

  def test_papillary_analysis_observers(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,))
    widget = self._moduleWidget("valvepapillaryanalysis")
    try:
      self._select(widget, valveBrowser.heartValveNode)
      models = widget.valveModel.papillaryModels
      nodeA = models[0].getPapillaryLineMarkupNode()
      nodeB = models[1].getPapillaryLineMarkupNode()
      widget.setAndObservePapillaryLineMarkupNode(nodeA)
      self.assertIs(widget.papillaryLineMarkupNode, nodeA)
      self.assertEqual(len(widget.papillaryLineMarkupNodeObservers), 3)
      calls = []
      original = widget.onPapillaryLineMarkupNodeModified
      widget.onPapillaryLineMarkupNodeModified = lambda *args: calls.append(args)
      try:
        widget.setAndObservePapillaryLineMarkupNode(nodeB)
        self.assertIs(widget.papillaryLineMarkupNode, nodeB)
        self.assertEqual(len(widget.papillaryLineMarkupNodeObservers), 3)
        calls.clear()
        nodeA.SetLocked(False)
        nodeA.AddControlPoint(1, 2, 3)
        self.assertEqual(calls, [], "observers of the previous node must be removed")
        nodeB.SetLocked(False)
        nodeB.AddControlPoint(1, 2, 3)
        self.assertGreater(len(calls), 0, "the observed node reports point changes")
        widget.setAndObservePapillaryLineMarkupNode(None)
        self.assertEqual(widget.papillaryLineMarkupNodeObservers, [])
        calls.clear()
        nodeB.AddControlPoint(4, 5, 6)
        self.assertEqual(calls, [], "no observer after unsetting the node")
      finally:
        widget.onPapillaryLineMarkupNodeModified = original
    finally:
      self._select(widget, None)

  # ---------------------------------------------------------------------------------------------
  # LeafletMoldGenerator
  # ---------------------------------------------------------------------------------------------

  def test_mold_generator_rim_markup_and_leaflet_ids(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,), roi=True, segmentation=True)
    valveModel = valveBrowser.valveModel
    widget = self._moduleWidget("leafletmoldgenerator")
    try:
      self._select(widget, valveBrowser.heartValveNode)
      self.assertIsNotNone(widget.valveModel)
      widget.rimSizeSpinBox.value = 3.0
      rimNode = widget.createValveRimMarkupNode()
      self.assertEqual(rimNode.GetClassName(), "vtkMRMLMarkupsClosedCurveNode")
      self.assertAlmostEqual(rimNode.GetDisplayNode().GetLineDiameter(), 6.0, places=5, msg="diameter = 2 x rim radius")
      self.assertShParentIs(rimNode, valveBrowser.heartValveNode)
      widget.setValveRimMarkupNode(rimNode)
      self.assertIs(widget.getValveRimMarkupNode(), rimNode)
      self.assertParentTransformIs(rimNode, valveBrowser.probeToRasTransformNode)
      self.assertAlmostEqual(widget.getAverageValveRadius(), 2.25, delta=0.4, msg="mean radius of the 2.5 x 2.0 ellipse")
      # Leaflet IDs of the mold segmentation exclude the valve mask
      valveBrowser.heartValveNode.SetNodeReferenceID("MoldSegmentation", valveModel.leafletSegmentationNode.GetID())
      self.assertEqual(sorted(widget.getLeafletIDs()), ["Anterior", "Posterior"])
      self.assertEqual(widget.getLeafletNameFromID("Anterior"), "Anterior leaflet")
    finally:
      self._select(widget, None)

  def test_mold_generator_clone_keeps_transform(self):
    import LeafletMoldGenerator
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,), roi=True)
    valveModel = valveBrowser.valveModel
    roiNode = valveModel.valveRoiModelNode
    clone = LeafletMoldGenerator.LeafletMoldGeneratorLogic.cloneMRMLNode(roiNode)
    self.assertIsNotNone(clone)
    self.assertNotEqual(clone.GetID(), roiNode.GetID())
    self.assertParentTransformIs(clone, valveBrowser.probeToRasTransformNode)
    self.assertEqual(clone.GetPolyData().GetNumberOfPoints(), roiNode.GetPolyData().GetNumberOfPoints())
