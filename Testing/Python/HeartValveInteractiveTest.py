"""
HeartValveInteractiveTest.py

Interactive tests: the module panels of ValveAnnulusAnalysis, ValveSegmentation and
ValveQuantification are shown in the main window and driven the way a user drives them, with mouse
events sent to the real buttons, selections in the real combo boxes, the time point slider of the
sequence widget, mouse clicks in the slice view to place annulus points, and the Segment Editor
of the ValveSegmentation panel. The checks look at what the user would see (enabled buttons, the
contour shown, the table of results) and at the data model behind it.

The tests need the main window (they are skipped when Slicer runs with --no-main-window). They
run on the small synthetic volume sequence of the fixtures.
"""

import os
import sys

import numpy as np
import qt
import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTLIB_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "ValveAnnulusAnalysis", "Testing", "Python"))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, SkipTest, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class HeartValveInteractiveTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "HeartValveInteractiveTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "ValveQuantification", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Interactive tests of the heart valve module panels."
    self.parent.acknowledgementText = ""


class HeartValveInteractiveTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class HeartValveInteractiveTestLogic(ScriptedLoadableModuleLogic):
  pass


# -------------------------------------------------------------------------------------------------
# User actions
# -------------------------------------------------------------------------------------------------

class User:
  """Simulated user input: real Qt mouse events on widgets, VTK interactor events in views."""

  @staticmethod
  def pump(count=3):
    for _ in range(count):
      slicer.app.processEvents()

  @classmethod
  def click(cls, widget):
    """Left mouse click at the centre of a widget (press and release events, like a mouse)."""
    if not widget.isVisible():
      raise AssertionError(f"'{widget.objectName or widget.text}' is not visible to the user")
    if not widget.enabled:
      raise AssertionError(f"'{widget.objectName or widget.text}' is disabled")
    center = qt.QPointF(widget.rect.center())
    for eventType in (qt.QEvent.MouseButtonPress, qt.QEvent.MouseButtonRelease):
      event = qt.QMouseEvent(eventType, center, qt.Qt.LeftButton, qt.Qt.LeftButton, qt.Qt.NoModifier)
      qt.QCoreApplication.sendEvent(widget, event)
    cls.pump()

  @classmethod
  def expand(cls, collapsibleButton):
    if collapsibleButton.collapsed:
      cls.click(collapsibleButton)

  @classmethod
  def choose(cls, comboBox, text):
    """Pick an entry of a combo box by its text."""
    index = comboBox.findText(text)
    if index < 0:
      raise AssertionError(f"'{text}' is not an entry of the combo box: {[comboBox.itemText(i) for i in range(comboBox.count)]}")
    comboBox.setCurrentIndex(index)
    cls.pump()

  @classmethod
  def pick(cls, nodeSelector, node):
    """Pick a node in a qMRMLNodeComboBox."""
    nodeSelector.setCurrentNode(node)
    cls.pump()

  @classmethod
  def createNew(cls, nodeSelector):
    """The 'Create new ...' entry of a qMRMLNodeComboBox."""
    node = nodeSelector.addNode()
    cls.pump()
    return node

  @classmethod
  def slide(cls, sliderWidget, value):
    """Drag the slider of a widget that contains a QSlider (e.g. the sequence seek widget)."""
    slider = sliderWidget if isinstance(sliderWidget, qt.QSlider) else sliderWidget.findChild(qt.QSlider)
    if slider is None:
      raise AssertionError("no slider found")
    slider.setValue(value)
    cls.pump()

  @classmethod
  def clickInView(cls, viewWidget, xy):
    """Left click at window coordinates *xy* of a slice or 3D view (what slicer.util.clickAndDrag does)."""
    interactor = viewWidget.interactorStyle().GetInteractor()
    interactor.SetEventPosition(int(xy[0]), int(xy[1]))
    interactor.LeftButtonPressEvent()
    interactor.LeftButtonReleaseEvent()
    cls.pump()


class HeartValveInteractiveTestTest(SlicerHeartTestCase):

  # ---------------------------------------------------------------------------------------------
  # Fixture
  # ---------------------------------------------------------------------------------------------

  def setUp(self):
    SlicerHeartTestCase.setUp(self)
    if slicer.util.mainWindow() is None:
      raise SkipTest("interactive tests need the main window")
    self.user = User
    slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    self.user.pump()

  def tearDown(self):
    for moduleName in ("valveannulusanalysis", "valvesegmentation", "valvequantification"):
      module = getattr(slicer.modules, moduleName, None)
      widget = module.widgetRepresentation().self() if module else None
      if widget is None:
        continue
      try:
        if hasattr(widget, "setHeartValveBrowserNode"):
          widget.setHeartValveBrowserNode(None)
        if hasattr(widget, "heartValveMeasurementSelector"):
          widget.heartValveMeasurementSelector.setCurrentNode(None)
      except Exception:  # noqa: BLE001
        pass
    interactionNode = slicer.app.applicationLogic().GetInteractionNode()
    interactionNode.SetCurrentInteractionMode(interactionNode.ViewTransform)
    self.user.pump()
    SlicerHeartTestCase.tearDown(self)

  @staticmethod
  def _openModule(name):
    slicer.util.selectModule(name)
    User.pump(5)
    widget = getattr(slicer.modules, name.lower()).widgetRepresentation().self()
    return widget

  @staticmethod
  def _showVolume(volumeNode):
    slicer.util.setSliceViewerLayers(background=volumeNode, fit=True)
    User.pump()

  @staticmethod
  def _points(markupsNode):
    points = []
    for i in range(markupsNode.GetNumberOfControlPoints()):
      p = [0.0, 0.0, 0.0]
      markupsNode.GetNthControlPointPosition(i, p)
      points.append(p)
    return points

  def _fixtureValve(self, factory, frames=(1, 3), labels=False, segmentation=False):
    valveBrowser = factory.createValveBrowser("mitral")
    for frame, phase in zip(frames, ("mid-systole", "end-diastole")):
      factory.addTimePoint(valveBrowser, frame, phase=phase)
      contour = factory.setContour(valveBrowser, frame)
      if labels:
        valveBrowser.valveModel.setValveLabels([("A", *contour[0]), ("AL", *contour[3]), ("P", *contour[6]), ("PM", *contour[9])])
      if segmentation:
        factory.addRoi(valveBrowser)
        factory.addSegmentation(valveBrowser)
    return valveBrowser

  # ---------------------------------------------------------------------------------------------
  # ValveAnnulusAnalysis: create a valve, place the annulus by clicking, navigate time points
  # ---------------------------------------------------------------------------------------------

  def test_annulus_analysis_journey(self):
    factory = NewFormatValveFactory(numFrames=6)
    self._showVolume(factory.volumeProxyNode)
    widget = self._openModule("ValveAnnulusAnalysis")
    ui = widget.ui
    sequenceUi = widget.valveSequenceBrowserWidget.ui

    # Create a valve browser with the selector; the valve type and the volume follow from the GUI
    browserNode = self.user.createNew(ui.heartValveBrowserSelector)
    self.assertIsNotNone(browserNode)
    self.assertEqual(widget.valveBrowserNode.GetID(), browserNode.GetID())
    self.assertEqual(widget.valveVolumeNode.GetID(), factory.volumeProxyNode.GetID(), "displayed volume picked up")
    self.user.choose(ui.valveTypeSelector, "tricuspid")
    self.assertEqual(browserNode.GetAttribute("ValveType"), "tricuspid")
    self.user.choose(ui.valveTypeSelector, "mitral")
    self.assertEqual(browserNode.GetAttribute("ValveType"), "mitral")
    self.assertFalse(sequenceUi.removeTimePointButton.enabled, "nothing to remove yet")
    self.assertFalse(ui.addAnnulusContourCurveButton.enabled, "no time point yet")

    # First time point at frame 2: add it, set the phase, add the contour and place points in the red view
    factory.selectFrame(2)
    self.user.click(sequenceUi.addTimePointButton)
    self.assertIsNotNone(widget.valveModel)
    self.assertEqual(widget.valveModel.getValveVolumeSequenceIndex(), 2)
    self.assertTrue(sequenceUi.removeTimePointButton.enabled)
    self.user.choose(sequenceUi.cardiacCyclePhaseSelector, "mid-systole")
    self.assertEqual(widget.valveModel.getCardiacCyclePhase(), "mid-systole")
    self.user.expand(ui.contouringCollapsibleButton)
    self.assertTrue(ui.addAnnulusContourCurveButton.enabled)
    self.user.click(ui.addAnnulusContourCurveButton)
    curveNode = widget.valveModel.annulusContourCurveNode
    self.assertIsNotNone(curveNode, "contour curve created by the button")
    self.assertFalse(ui.addAnnulusContourCurveButton.enabled)
    self.assertTrue(ui.removeAnnulusContourCurveButton.enabled)
    self.assertEqual(curveNode.GetNumberOfControlPoints(), 0)

    redWidget = slicer.app.layoutManager().sliceWidget("Red")
    redView = redWidget.sliceView()
    ui.placeButton2.setPlaceModeEnabled(True)  # the place button of the contouring section
    self.user.pump()
    interactionNode = slicer.app.applicationLogic().GetInteractionNode()
    self.assertEqual(interactionNode.GetCurrentInteractionMode(), interactionNode.Place, "place mode active")
    ui.autoRotateButton.setChecked(False)  # keep the red slice where it is while placing
    self.user.pump()
    width, height = redView.width, redView.height
    clicks = [(width * 0.5 + width * 0.2 * np.cos(a), height * 0.5 + height * 0.2 * np.sin(a))
              for a in np.linspace(0, 2 * np.pi, 6, endpoint=False)]
    for xy in clicks:
      self.user.clickInView(redView, xy)
    ui.placeButton2.setPlaceModeEnabled(False)
    self.user.pump()
    self.assertEqual(curveNode.GetNumberOfControlPoints(), len(clicks), "one control point per click in the slice view")
    firstContour = self._points(curveNode)
    self.assertGreater(curveNode.GetCurveLengthWorld(), 0.0, "closed curve through the clicked points")
    self.assertEqual(ui.annulusMarkupAdjustmentList.currentNode().GetID(), curveNode.GetID(), "point list shows the contour")

    # Second time point at frame 4 with its own contour
    factory.selectFrame(4)
    self.user.pump()
    self.assertIn("Add volume", sequenceUi.addTimePointButton.text)
    self.user.click(sequenceUi.addTimePointButton)
    self.assertEqual(widget.valveModel.getValveVolumeSequenceIndex(), 4)
    self.assertTrue(ui.addAnnulusContourCurveButton.enabled, "the new time point has no contour")
    self.user.click(ui.addAnnulusContourCurveButton)
    secondCurve = widget.valveModel.annulusContourCurveNode
    self.assertEqual(secondCurve.GetNumberOfControlPoints(), 0, "a fresh contour at the new time point")
    ui.placeButton2.setPlaceModeEnabled(True)
    self.user.pump()
    for xy in clicks[:4]:
      self.user.clickInView(redView, (xy[0] + width * 0.05, xy[1]))
    ui.placeButton2.setPlaceModeEnabled(False)
    self.user.pump()
    self.assertEqual(secondCurve.GetNumberOfControlPoints(), 4)
    secondContour = self._points(secondCurve)

    # Navigate with the time point slider: the contour of the first time point is shown again
    seekWidget = sequenceUi.heartValveBrowserSeekWidget
    self.user.slide(seekWidget, 0)
    self.assertEqual(browserNode.GetSelectedItemNumber(), 0)
    self.assertEqual(factory.volumeBrowserNode.GetSelectedItemNumber(), 2, "the volume follows the time point")
    self.assertEqual(widget.valveModel.getValveVolumeSequenceIndex(), 2)
    self.assertEqual(widget.valveModel.annulusContourCurveNode.GetNumberOfControlPoints(), len(clicks))
    self.assertPointsAlmostEqual(self._points(widget.valveModel.annulusContourCurveNode), firstContour, places=3)
    self.user.slide(seekWidget, 1)
    self.assertEqual(factory.volumeBrowserNode.GetSelectedItemNumber(), 4)
    self.assertPointsAlmostEqual(self._points(widget.valveModel.annulusContourCurveNode), secondContour, places=3)

    # Remove the second time point: the first one, with its contour, remains
    self.user.click(sequenceUi.removeTimePointButton)
    self.assertEqual(browserNode.GetNumberOfItems(), 1)
    self.assertEqual(widget.valveModel.getValveVolumeSequenceIndex(), 2)
    self.assertPointsAlmostEqual(self._points(widget.valveModel.annulusContourCurveNode), firstContour, places=3)
    # and the contour of the remaining time point can be removed with its button
    self.user.click(ui.removeAnnulusContourCurveButton)
    self.assertIsNone(widget.valveModel.annulusContourCurveNode)
    self.assertTrue(ui.addAnnulusContourCurveButton.enabled)

  # ---------------------------------------------------------------------------------------------
  # ValveSegmentation: ROI, segmentation, a segment painted in the Segment Editor, time points
  # ---------------------------------------------------------------------------------------------

  def test_segmentation_journey(self):
    factory = NewFormatValveFactory(numFrames=6)
    valveBrowser = self._fixtureValve(factory, frames=(1, 3))
    browserNode = valveBrowser.valveBrowserNode
    self._showVolume(factory.volumeProxyNode)
    widget = self._openModule("ValveSegmentation")
    ui = widget.ui
    sequenceUi = widget.valveSequenceBrowserWidget.ui
    self.user.pick(ui.heartValveBrowserSelector, browserNode)
    self.assertEqual(widget.valveBrowserNode.GetID(), browserNode.GetID())
    self.assertEqual(widget.valveModel.getValveVolumeSequenceIndex(), 3, "opens at the current time point")
    self.assertTrue(ui.addValveRoiButton.enabled)
    self.assertFalse(ui.addSegmentationButton.enabled, "the segmentation needs the ROI first")

    self.user.click(ui.addValveRoiButton)
    self.assertIsNotNone(widget.valveModel.valveRoiModelNode, "ROI created at frame 3")
    self.assertTrue(ui.addSegmentationButton.enabled)
    self.user.click(ui.addSegmentationButton)
    segmentationNode = widget.valveModel.leafletSegmentationNode
    self.assertIsNotNone(segmentationNode, "segmentation created at frame 3")
    editor = ui.segmentEditorWidget
    self.assertTrue(editor.enabled)
    self.assertEqual(editor.segmentationNode().GetID(), segmentationNode.GetID(), "Segment Editor edits the valve segmentation")
    self.assertEqual(editor.sourceVolumeNode().GetID(), widget.valveModel.leafletVolumeNode.GetID(), "editing the leaflet volume")

    # Add a segment with the editor's button and fill it with the threshold effect
    segmentIdsBefore = list(segmentationNode.GetSegmentation().GetSegmentIDs())
    self.user.click(editor.findChild(qt.QPushButton, "AddSegmentButton"))
    segmentIds = list(segmentationNode.GetSegmentation().GetSegmentIDs())
    self.assertEqual(len(segmentIds), len(segmentIdsBefore) + 1, "a segment added in the editor")
    newSegmentId = [s for s in segmentIds if s not in segmentIdsBefore][0]
    self.assertEqual(editor.currentSegmentID(), newSegmentId, "the new segment is selected for editing")
    editor.setActiveEffectByName("Threshold")
    effect = editor.activeEffect()
    self.assertIsNotNone(effect, "Threshold effect available")
    effect.setParameter("MinimumThreshold", "1")
    effect.setParameter("MaximumThreshold", "255")
    effect.self().onApply()
    editor.setActiveEffectByName("")
    self.user.pump()
    self.assertTrue(widget.valveModel.segmentHasContent(segmentationNode.GetSegmentation(), newSegmentId),
                    "the thresholded segment has voxels")
    name = segmentationNode.GetSegmentation().GetSegment(newSegmentId).GetName()

    # The other time point has no segmentation yet; adding one there gives it the same segments, empty
    seekWidget = sequenceUi.heartValveBrowserSeekWidget
    self.user.slide(seekWidget, 0)
    self.assertEqual(widget.valveModel.getValveVolumeSequenceIndex(), 1)
    self.assertFalse(editor.enabled, "no segmentation at frame 1 yet")
    self.assertIsNone(editor.segmentationNode())
    self.assertFalse(ui.addSegmentationButton.enabled, "ROI first")
    self.user.click(ui.addValveRoiButton)
    self.user.click(ui.addSegmentationButton)
    self.assertTrue(editor.enabled)
    segmentationAtFrame1 = widget.valveModel.leafletSegmentationNode
    self.assertEqual(sorted(segmentationAtFrame1.GetSegmentation().GetSegmentIDs()), sorted(segmentIds),
                     "all time points of a valve share the same leaflet segments")
    self.assertEqual(segmentationAtFrame1.GetSegmentation().GetSegment(newSegmentId).GetName(), name)
    self.assertFalse(widget.valveModel.segmentHasContent(segmentationAtFrame1.GetSegmentation(), newSegmentId),
                     "the segment is empty at the new time point")

    # Back at frame 3 the painted segment is still there; removing the segmentation of frame 1 keeps it
    self.user.slide(seekWidget, 1)
    self.assertEqual(editor.segmentationNode().GetID(), widget.valveModel.leafletSegmentationNode.GetID())
    self.assertTrue(widget.valveModel.segmentHasContent(widget.valveModel.leafletSegmentationNode.GetSegmentation(), newSegmentId),
                    "content of frame 3 kept")
    self.user.slide(seekWidget, 0)
    self.assertTrue(ui.removeSegmentationButton.enabled)
    self.user.click(ui.removeSegmentationButton)
    self.assertFalse(editor.enabled, "segmentation of frame 1 removed")
    self.user.slide(seekWidget, 1)
    self.assertTrue(editor.enabled, "segmentation of frame 3 untouched")
    self.assertTrue(widget.valveModel.segmentHasContent(widget.valveModel.leafletSegmentationNode.GetSegmentation(), newSegmentId))

  # ---------------------------------------------------------------------------------------------
  # ValveQuantification: measurement, preset, valves, compute, compute all, browse the results
  # ---------------------------------------------------------------------------------------------

  def test_quantification_journey(self):
    factory = NewFormatValveFactory(numFrames=6)
    mitral = self._fixtureValve(factory, frames=(1, 3), labels=True)
    aortic = factory.createAnnotatedValve("aortic", frames=(1,), phases=("mid-systole",))
    self._showVolume(factory.volumeProxyNode)
    widget = self._openModule("ValveQuantification")

    measurementNode = self.user.createNew(widget.heartValveMeasurementSelector)
    self.assertIsNotNone(measurementNode)
    self.assertEqual(measurementNode.GetAttribute("ModuleName"), "HeartValveMeasurement")
    self.user.expand(widget.valvesCollapsibleButton)
    self.user.choose(widget.presetSelector, widget.logic.getMeasurementPresetById("MitralValve").name)
    self.assertEqual(measurementNode.GetAttribute("MeasurementPreset"), "MitralValve", "preset stored on the measurement")
    self.assertTrue(widget.inputValveNodeSelectors[0].isVisible(), "valve selectors of the preset shown")
    self.user.pick(widget.inputValveNodeSelectors[0], mitral.heartValveNode)
    self.user.pick(widget.inputValveNodeSelectors[1], aortic.heartValveNode)
    self.assertEqual(measurementNode.GetNodeReference("ValveMitralValve").GetID(), mitral.heartValveNode.GetID())
    self.assertEqual(measurementNode.GetNodeReference("ValveAorticValve").GetID(), aortic.heartValveNode.GetID())
    sequenceWidget = widget.valveSequenceBrowserWidget
    self.assertEqual(sequenceWidget.valveBrowserNode.GetID(), mitral.valveBrowserNode.GetID(), "time points of the first valve")
    self.assertEqual([n.GetID() for n in sequenceWidget.linkedValveBrowserNodes], [aortic.valveBrowserNode.GetID()])

    self.user.expand(widget.outputCollapsibleButton)
    preset = widget.logic.getMeasurementPresetById("MitralValve")
    scene.selectIndexValue(mitral.valveBrowserNode, factory.indexValue(1))
    self.user.pump()
    self.user.click(widget.computeButton)
    tableNode = preset.metricsTable.metricTableNode
    self.assertIsNotNone(tableNode, "results table after Compute")
    rowsAtFrame1 = {tableNode.GetCellText(r, 0): tableNode.GetCellText(r, 1) for r in range(tableNode.GetNumberOfRows())}
    self.assertIn("Annulus area (3D)", rowsAtFrame1)
    self.assertGreater(float(rowsAtFrame1["Annulus area (3D)"]), 0.0)
    self.assertNotIn("error", widget.computeStatusTextEdit.plainText.lower())
    tableSequence = mitral.valveBrowserNode.GetSequenceNode(tableNode)
    self.assertIsNotNone(tableSequence, "results stored per time point")
    self.assertSequenceIndexValues(tableSequence, [factory.indexValue(1)])

    self.user.click(widget.computeAllButton)
    self.assertSequenceIndexValues(tableSequence, [factory.indexValue(1), factory.indexValue(3)], "all phases computed")
    self.assertEqual(mitral.valveBrowserNode.GetSelectedItemNumber(), 0, "time point restored after computing all")

    # Browsing the time points with the slider shows the results of that time point
    seekWidget = sequenceWidget.ui.heartValveBrowserSeekWidget
    self.user.slide(seekWidget, 1)
    rowsAtFrame3 = {tableNode.GetCellText(r, 0): tableNode.GetCellText(r, 1) for r in range(tableNode.GetNumberOfRows())}
    self.assertNotEqual(rowsAtFrame3["Annulus area (3D)"], rowsAtFrame1["Annulus area (3D)"], "frame 3 has its own contour and results")
    self.assertEqual(aortic.valveBrowserNode.GetSelectedItemNumber(), 0, "the linked aortic browser stays on its only time point")
    self.user.slide(seekWidget, 0)
    rows = {tableNode.GetCellText(r, 0): tableNode.GetCellText(r, 1) for r in range(tableNode.GetNumberOfRows())}
    self.assertEqual(rows["Annulus area (3D)"], rowsAtFrame1["Annulus area (3D)"], "results of frame 1 shown again")
