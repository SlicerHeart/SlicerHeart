"""
ValveSequenceWidgetTest.py

Tests for the shared sequence widgets (HeartValveWidgets.ValveSequenceBrowserWidget and
ValveSequenceInfoWidget) and for the sequence-specific parts of the ValveAnnulusAnalysis module
widget. The widgets are instantiated on a hidden Qt widget; slots are called directly (no clicking).
"""

import os
import sys

import qt
import vtk
import slicer
from slicer.ScriptedLoadableModule import *

_TESTLIB_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTLIB_DIR not in sys.path:
  sys.path.insert(0, _TESTLIB_DIR)
from HeartValveTestLib import SlicerHeartTestCase, scene  # noqa: E402
from HeartValveTestLib.newformat import NewFormatValveFactory  # noqa: E402


class ValveSequenceWidgetTest(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ValveSequenceWidgetTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["ValveAnnulusAnalysis", "ValveSegmentation", "Sequences", "Volumes"]
    self.parent.contributors = ["SlicerHeart contributors"]
    self.parent.helpText = "Tests for the valve sequence browser/info widgets and the ValveAnnulusAnalysis widget."
    self.parent.acknowledgementText = ""


class ValveSequenceWidgetTestWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)


class ValveSequenceWidgetTestLogic(ScriptedLoadableModuleLogic):
  pass


class ValveSequenceWidgetTestTest(SlicerHeartTestCase):

  # ---------------------------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------------------------

  def setUp(self):
    SlicerHeartTestCase.setUp(self)
    self._widgets = []
    self._host = qt.QWidget()
    self._host.setLayout(qt.QVBoxLayout())

  def tearDown(self):
    for widget in self._widgets:
      try:
        widget.destroy()
      except Exception:  # noqa: BLE001
        pass
    self._widgets = []
    self._host.deleteLater()
    self._host = None
    SlicerHeartTestCase.tearDown(self)

  def _browserWidget(self):
    from HeartValveWidgets.ValveSequenceBrowserWidget import ValveSequenceBrowserWidget
    widget = ValveSequenceBrowserWidget(parent=self._host.layout())
    self._widgets.append(widget)
    return widget

  def _infoWidget(self):
    from HeartValveWidgets.ValveSequenceInfoWidget import ValveSequenceInfoWidget
    widget = ValveSequenceInfoWidget(parent=self._host.layout())
    self._widgets.append(widget)
    return widget

  @staticmethod
  def _counter():
    calls = []
    return calls, (lambda *args: calls.append(args))

  # ---------------------------------------------------------------------------------------------
  # ValveSequenceBrowserWidget
  # ---------------------------------------------------------------------------------------------

  def test_construct_bind_and_destroy(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3))
    browserNode = valveBrowser.valveBrowserNode
    widget = self._browserWidget()
    self.assertIsNone(widget.valveBrowserNode)
    self.assertIsNone(widget.valveModel)
    self.assertIsNone(widget.valveBrowser)
    widget.valveBrowserNode = browserNode
    self.assertEqual(widget.valveBrowserNode.GetID(), browserNode.GetID())
    self.assertIs(widget.valveBrowser, valveBrowser)
    self.assertIs(widget.heartValveNode, valveBrowser.heartValveNode)
    self.assertEqual(widget.valveVolumeBrowserNode.GetID(), factory.volumeBrowserNode.GetID())
    self.assertEqual(widget.valveVolumeNode.GetID(), factory.volumeProxyNode.GetID())
    self.assertTrue(widget.ui.enabled)

    browserCalls, browserSlot = self._counter()
    valveCalls, valveSlot = self._counter()
    widget.valveBrowserNodeModified.connect(browserSlot)
    widget.heartValveNodeModified.connect(valveSlot)
    browserNode.Modified()
    valveBrowser.heartValveNode.Modified()
    self.assertEqual(len(browserCalls), 1, "browser signal emitted once per modification")
    self.assertEqual(len(valveCalls), 1, "valve node signal emitted once per modification")

    widget.valveBrowserNode = None
    self.assertIsNone(widget.heartValveNode)
    self.assertIsNone(widget.valveVolumeBrowserNode)
    browserNode.Modified()
    valveBrowser.heartValveNode.Modified()
    factory.volumeBrowserNode.Modified()
    self.assertEqual(len(browserCalls), 1, "no signal after unbinding")
    self.assertEqual(len(valveCalls), 1, "no signal after unbinding")
    self.assertFalse(widget.ui.enabled)

    widget.valveBrowserNode = browserNode
    widget.destroy()
    self._widgets.remove(widget)
    browserNode.Modified()
    self.assertEqual(len(browserCalls), 1, "no signal after destroy")

  def test_time_point_switch_drives_volume_browser(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3))
    browserNode = valveBrowser.valveBrowserNode
    widget = self._browserWidget()
    widget.valveBrowserNode = browserNode
    self.assertEqual(factory.volumeBrowserNode.GetSelectedItemNumber(), 3, "bound at the analyzed frame")
    browserNode.SetSelectedItemNumber(0)
    self.assertEqual(factory.volumeBrowserNode.GetSelectedItemNumber(), 1)
    browserNode.SetSelectedItemNumber(1)
    self.assertEqual(factory.volumeBrowserNode.GetSelectedItemNumber(), 3)
    # Scrubbing the volume alone changes nothing on the valve
    factory.selectFrame(5)
    self.assertEqual(valveBrowser.heartValveSequenceNode.GetNumberOfDataNodes(), 2)
    self.assertEqual(browserNode.GetSelectedItemNumber(), 1)
    self.assertIn("Add volume (index: 6)", widget.ui.addTimePointButton.text)
    # An unrelated modification of the browser must not force the volume back to the analyzed frame
    browserNode.SetAttribute("Comment", "x")
    self.assertEqual(factory.volumeBrowserNode.GetSelectedItemNumber(), 5)
    factory.selectFrame(3)
    self.assertIn("Go to volume (index: 4)", widget.ui.addTimePointButton.text)
    self.assertIn("Volume index: 4", widget.ui.valveVolumeSequenceIndexLabel.text)

  def test_add_and_remove_time_point_slots(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    widget = self._browserWidget()
    widget.valveBrowserNode = valveBrowser.valveBrowserNode
    self.assertFalse(widget.readOnly)
    self.assertFalse(widget.ui.addTimePointButton.isHidden())
    factory.selectFrame(2)
    widget.onAddTimePointButtonClicked()
    self.assertEqual(valveBrowser.heartValveSequenceNode.GetNumberOfDataNodes(), 1)
    self.assertIs(widget.heartValveNode, valveBrowser.heartValveNode)
    self.assertTrue(widget.ui.removeTimePointButton.enabled)
    self.assertTrue(widget.ui.cardiacCyclePhaseSelector.enabled)
    factory.selectFrame(4)
    widget.updateGUIFromMRML()
    self.assertFalse(widget.ui.removeTimePointButton.enabled)
    self.assertFalse(widget.ui.cardiacCyclePhaseSelector.enabled)
    widget.onAddTimePointButtonClicked()
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [factory.indexValue(2), factory.indexValue(4)])
    widget.onRemoveTimePointButtonClicked()
    self.assertSequenceIndexValues(valveBrowser.heartValveSequenceNode, [factory.indexValue(2)])
    widget.onRemoveTimePointButtonClicked()  # no time point at frame 4 any more: no-op
    self.assertEqual(valveBrowser.heartValveSequenceNode.GetNumberOfDataNodes(), 1)

  def test_add_time_point_without_volume_raises(self):
    import HeartValveLib
    browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "Bare")
    browserNode.SetAttribute("ModuleName", "HeartValve")
    HeartValveLib.HeartValves.getValveBrowser(browserNode)
    slicer.app.applicationLogic().GetSelectionNode().SetActiveVolumeID(None)
    widget = self._browserWidget()
    widget.valveBrowserNode = browserNode
    self.assertFalse(widget.ui.enabled, "widget disabled without a volume sequence")
    with self.assertRaises(RuntimeError):
      widget.onAddTimePointButtonClicked()

  def test_bind_uses_background_volume(self):
    import HeartValveLib
    factory = NewFormatValveFactory()
    browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "Fresh")
    browserNode.SetAttribute("ModuleName", "HeartValve")
    HeartValveLib.HeartValves.getValveBrowser(browserNode)
    slicer.app.applicationLogic().GetSelectionNode().SetActiveVolumeID(factory.volumeProxyNode.GetID())
    widget = self._browserWidget()
    widget.valveBrowserNode = browserNode
    self.assertEqual(widget.valveVolumeNode.GetID(), factory.volumeProxyNode.GetID(),
                     "the active (background) volume becomes the valve volume")
    self.assertTrue(widget.ui.enabled)

  def test_readOnly(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,), phases=("mid-systole",))
    widget = self._browserWidget()
    widget.valveBrowserNode = valveBrowser.valveBrowserNode
    widget.readOnly = True
    self.assertTrue(widget.ui.addTimePointButton.isHidden())
    self.assertTrue(widget.ui.removeTimePointButton.isHidden())
    self.assertTrue(widget.ui.cardiacCyclePhaseSelector.isHidden())
    self.assertIn("(mid-systole)", widget.ui.valveVolumeSequenceIndexLabel.text)
    widget.readOnly = False
    self.assertFalse(widget.ui.addTimePointButton.isHidden())
    self.assertNotIn("(mid-systole)", widget.ui.valveVolumeSequenceIndexLabel.text)

  def test_cardiac_phase_selector(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3), phases=("mid-systole", "end-diastole"))
    valveModel = valveBrowser.valveModel
    widget = self._browserWidget()
    widget.valveBrowserNode = valveBrowser.valveBrowserNode
    combo = widget.ui.cardiacCyclePhaseSelector
    self.assertEqual(combo.currentText, "end-diastole", "combo shows the phase of the current time point")
    combo.setCurrentIndex(combo.findText("end-systole"))
    self.assertEqual(valveModel.getCardiacCyclePhase(), "end-systole")
    factory.switchTo(valveBrowser, 1)
    self.assertEqual(combo.currentText, "mid-systole")
    self.assertEqual(valveModel.getCardiacCyclePhase(), "mid-systole")
    # Refreshing the GUI must not write the phase back
    valveModel.setCardiacCyclePhase("mid-diastole")
    with scene.ModifiedEventCounter(valveBrowser.heartValveNode) as events:
      widget.updateGUIFromMRML()
    self.assertEqual(combo.currentText, "mid-diastole")
    self.assertEqual(events.count, 0)
    self.assertEqual(valveModel.getCardiacCyclePhase(), "mid-diastole")

  def test_linked_browsers_follow_index_value(self):
    factory = NewFormatValveFactory()
    mitral = factory.createAnnotatedValve("mitral", frames=(1, 3, 5))
    aortic = factory.createAnnotatedValve("aortic", frames=(1, 5))
    widget = self._browserWidget()
    widget.valveBrowserNode = mitral.valveBrowserNode
    widget.linkedValveBrowserNodes = [aortic.valveBrowserNode, mitral.valveBrowserNode]  # main browser is skipped
    mitral.valveBrowserNode.SetSelectedItemNumber(0)
    self.assertEqual(aortic.valveBrowserNode.GetSelectedItemNumber(), 0)
    mitral.valveBrowserNode.SetSelectedItemNumber(2)
    self.assertEqual(aortic.valveBrowserNode.GetSelectedItemNumber(), 1)
    mitral.valveBrowserNode.SetSelectedItemNumber(1)  # frame 3: no aortic time point, linked browser stays
    self.assertEqual(aortic.valveBrowserNode.GetSelectedItemNumber(), 1)
    widget.addlinkedValveBrowserNode(None)  # tolerated
    mitral.valveBrowserNode.SetSelectedItemNumber(0)
    self.assertEqual(aortic.valveBrowserNode.GetSelectedItemNumber(), 0)

  def test_widget_survives_scene_clear(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,))
    widget = self._browserWidget()
    widget.valveBrowserNode = valveBrowser.valveBrowserNode
    slicer.mrmlScene.Clear(0)
    slicer.app.processEvents()
    widget.updateGUIFromMRML()
    widget.valveBrowserNode = None
    widget.updateGUIFromMRML()
    self.assertFalse(widget.ui.enabled)

  # ---------------------------------------------------------------------------------------------
  # ValveSequenceInfoWidget
  # ---------------------------------------------------------------------------------------------

  def test_analyzeSequence(self):
    from HeartValveWidgets.ValveSequenceInfoWidget import analyzeSequence
    factory = NewFormatValveFactory()
    valveBrowser = factory.createValveBrowser("mitral")
    factory.addTimePoint(valveBrowser, 1)
    factory.setContour(valveBrowser, 1)
    factory.setLabels(valveBrowser, 1)
    factory.addRoi(valveBrowser)
    factory.addSegmentation(valveBrowser)
    factory.addTimePoint(valveBrowser, 4)
    factory.setContour(valveBrowser, 4)
    factory.switchTo(valveBrowser, 4)
    factory.selectFrame(2)  # volume deliberately elsewhere
    data = analyzeSequence(valveBrowser)
    self.assertEqual(data["Frame"], [1, 4])
    self.assertEqual(data["Annulus"], [True, True])
    self.assertEqual(data["Landmarks"], [True, False])
    self.assertEqual(data["Segmentation"], [True, False])
    self.assertEqual(valveBrowser.valveBrowserNode.GetSelectedItemNumber(), 1, "valve selection restored")
    self.assertEqual(factory.volumeBrowserNode.GetSelectedItemNumber(), 2, "volume selection restored")

  def test_series_info_model(self):
    from HeartValveWidgets.ValveSequenceInfoWidget import ValveSeriesInfo
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3))
    model = ValveSeriesInfo()
    self.assertEqual(model.rowCount(), 0)
    model.valveBrowserNode = valveBrowser.valveBrowserNode
    self.assertEqual(model.rowCount(), 2)
    self.assertEqual(model.columnCount(), 4)
    self.assertEqual(model.getRowIdxForValveSequenceIndex(3), 1)
    self.assertEqual(model.getRowIdxForValveSequenceIndex(2), -1)
    self.assertEqual(model.headerData(0, qt.Qt.Horizontal), "Frame")
    # Qt calls rowCount(parent); the override must accept the argument like columnCount does
    self.assertEqual(model.rowCount(qt.QModelIndex()), 2)

  def test_info_widget_selection(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1, 3))
    widget = self._infoWidget()
    widget.valveBrowserNode = None
    self.assertFalse(widget.ui.updateButton.enabled)
    widget.valveBrowserNode = valveBrowser.valveBrowserNode
    self.assertTrue(widget.ui.updateButton.enabled)
    calls, slot = self._counter()
    widget.selectionChanged.connect(slot)
    self.assertEqual(widget.getSelectedVolumeSequenceIndex(), -1)
    widget.selectOrClearVolumeSequenceIndex(3)
    self.assertEqual(widget.getSelectedVolumeSequenceIndex(), 3)
    self.assertGreaterEqual(len(calls), 1)
    widget.selectOrClearVolumeSequenceIndex(2)
    self.assertEqual(widget.getSelectedVolumeSequenceIndex(), -1, "unknown frame clears the selection")
    factory.addTimePoint(valveBrowser, 2)
    widget.update()
    widget.selectOrClearVolumeSequenceIndex(2)
    self.assertEqual(widget.getSelectedVolumeSequenceIndex(), 2)

  # ---------------------------------------------------------------------------------------------
  # ValveAnnulusAnalysis module widget
  # ---------------------------------------------------------------------------------------------

  def _annulusWidget(self):
    widget = slicer.modules.valveannulusanalysis.widgetRepresentation().self()
    self.assertIsNotNone(widget)
    return widget

  def test_annulus_module_creates_valve_browser_from_selector(self):
    factory = NewFormatValveFactory()
    slicer.app.applicationLogic().GetSelectionNode().SetActiveVolumeID(factory.volumeProxyNode.GetID())
    widget = self._annulusWidget()
    try:
      slicer.app.processEvents()
      browserNode = widget.ui.heartValveBrowserSelector.addNode()
      slicer.app.processEvents()
      self.assertIsNotNone(browserNode)
      self.assertEqual(browserNode.GetAttribute("ModuleName"), "HeartValve", "selector stamps the module attribute")
      self.assertEqual(widget.valveBrowserNode.GetID(), browserNode.GetID())
      self.assertEqual(widget.valveVolumeNode.GetID(), factory.volumeProxyNode.GetID())
      self.assertIsNotNone(widget.valveBrowser.axialSliceToRasTransformNode)
      # Time point and contour through the module's slots
      factory.selectFrame(2)
      widget.valveSequenceBrowserWidget.onAddTimePointButtonClicked()
      slicer.app.processEvents()
      self.assertIsNotNone(widget.valveModel)
      self.assertEqual(widget.valveModel.getValveVolumeSequenceIndex(), 2)
      self.assertTrue(widget.ui.addAnnulusContourCurveButton.enabled)
      self.assertFalse(widget.ui.removeAnnulusContourCurveButton.enabled)
      widget.onAddAnnulusContourCurve()
      self.assertIsNotNone(widget.valveModel.annulusContourCurveNode)
      self.assertFalse(widget.ui.addAnnulusContourCurveButton.enabled)
      self.assertTrue(widget.ui.removeAnnulusContourCurveButton.enabled)
      factory.selectFrame(4)
      widget.valveSequenceBrowserWidget.onAddTimePointButtonClicked()
      slicer.app.processEvents()
      widget.onAnnulusMarkupNodeModified()
      self.assertTrue(widget.ui.addAnnulusContourCurveButton.enabled, "new time point has no contour")
      widget.onRemoveAnnulusContourCurve()  # nothing to remove: must not raise
      widget.valveBrowserNode.SetSelectedItemNumber(0)
      slicer.app.processEvents()
      widget.onAnnulusMarkupNodeModified()
      self.assertTrue(widget.ui.removeAnnulusContourCurveButton.enabled)
      widget.onRemoveAnnulusContourCurve()
      self.assertIsNone(widget.valveModel.annulusContourCurveNode)
      self.assertIsNotNone(widget.valveSequenceBrowserWidget.valveBrowserNodeModified)
      self.assertIn(widget.onValveBrowserNodeModified, widget.valveSequenceBrowserWidget.valveBrowserNodeModified._slots)
      self.assertIn(widget.onHeartValveNodeModified, widget.valveSequenceBrowserWidget.heartValveNodeModified._slots)
    finally:
      widget.setHeartValveBrowserNode(None)
      slicer.app.processEvents()

  def test_annulus_module_survives_scene_clear(self):
    factory = NewFormatValveFactory()
    valveBrowser = factory.createAnnotatedValve("mitral", frames=(1,))
    widget = self._annulusWidget()
    try:
      widget.setHeartValveBrowserNode(valveBrowser.valveBrowserNode)
      slicer.app.processEvents()
      self.assertIsNotNone(widget.valveModel)
      slicer.mrmlScene.Clear(0)
      slicer.app.processEvents()
      widget.updateGUIFromHeartValveNode()
      widget.onAnnulusMarkupNodeModified()
    finally:
      widget.setHeartValveBrowserNode(None)
      slicer.app.processEvents()
