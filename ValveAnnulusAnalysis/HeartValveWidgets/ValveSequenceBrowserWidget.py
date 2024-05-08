import logging
from string import Template
from pathlib import Path

import qt
import vtk
import slicer

import HeartValveLib
from HeartValveLib.util import Signal
from HeartValveLib.Constants import CARDIAC_CYCLE_PHASE_PRESETS


class ValveSequenceBrowserWidget:
  """ Widget for navigating and optional modification of SlicerHeart-based ValveSeries (vtkMRMLSequenceBrowserNode).

    Attributes
    ----------
    valveBrowserNode : slicer.vtkMRMLSequenceBrowserNode
      (required) ValveSeries to be used for navigation and modification (if readOnly set to False)
    visible: bool
      controls visibility of underlying widget
    readOnly: bool
      flag for setting read-only (no add/remove of timepoints and no cardiac cycle modification) (default is False)

    Methods
    ----------
    destroy()
      deletes widget and all observers and signals

    .. code-block:: python

      from HeartValveWidgets.ValveSequenceBrowserWidget import ValveSequenceBrowserWidget
      w = ValveSequenceBrowserWidget(parent=None)
      w.show()

      #set to read only
      w.readOnly = True

      valveSeries = slicer.util.getNode('MitralValve')
      w.valveBrowserNode = valveSeries

      # destroy widget, remove observers, and disconnect signals
      w.destroy()

  """

  @property
  def valveModel(self):
    return self.valveBrowser.valveModel if self.valveBrowser else None

  @property
  def valveBrowser(self):
    return HeartValveLib.HeartValves.getValveBrowser(self.valveBrowserNode)

  @property
  def valveVolumeNode(self):
    if not self.valveBrowser:
      return None
    return self.valveBrowser.valveVolumeNode

  @property
  def heartValveNode(self):
    return self._heartValveNode

  @heartValveNode.setter
  def heartValveNode(self, heartValveNode: slicer.vtkMRMLScriptedModuleNode):
    if self.valveModel and self.valveModel.getHeartValveNode() == heartValveNode:
      return

    self._removeHeartValveNodeObserver()
    self._heartValveNode = heartValveNode
    if self._heartValveNode:
      self._heartValveNodeObserver = \
        self._heartValveNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onHeartValveNodeModified)

    self.updateGUIFromMRML()
    self.onGoToAnalyzedFrameButtonClicked()

  @property
  def valveBrowserNode(self):
    return self._valveBrowserNode

  @valveBrowserNode.setter
  def valveBrowserNode(self, valveBrowserNode: slicer.vtkMRMLSequenceBrowserNode):
    self.ui.heartValveBrowserPlayWidget.setMRMLSequenceBrowserNode(valveBrowserNode)
    self.ui.heartValveBrowserSeekWidget.setMRMLSequenceBrowserNode(valveBrowserNode)

    self._removeHeartValveBrowserNodeObserver()
    self._valveBrowserNode = valveBrowserNode
    if self._valveBrowserNode:
      self._valveBrowserNodeObserver = \
        self._valveBrowserNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onValveBrowserNodeModified)

    if self.valveBrowser and not self.valveVolumeNode:
      self._setValveVolumeToBackgroundVolume()

    if self._valveBrowserNode and self.valveBrowser and self.valveBrowser.volumeSequenceBrowserNode is None:
      logging.warning("Could not retrieve a valid VolumeSequenceBrowserNode for the given ValveSeries.")
    self.valveVolumeBrowserNode = self.valveBrowser.volumeSequenceBrowserNode if self.valveBrowser else None

    self.heartValveNode = self.valveBrowser.heartValveNode if self.valveBrowser else None

  @property
  def valveVolumeBrowserNode(self):
    return self._valveVolumeBrowserNode

  @valveVolumeBrowserNode.setter
  def valveVolumeBrowserNode(self, valveVolumeBrowserNode: slicer.vtkMRMLSequenceBrowserNode):
    self._removeValveVolumeBrowserObserver()
    self._valveVolumeBrowserNode = valveVolumeBrowserNode
    if self._valveVolumeBrowserNode:
      self._valveVolumeBrowserNodeObserver = \
        self._valveVolumeBrowserNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onValveVolumeBrowserNodeModified)
    self.updateGUIFromMRML()

  @property
  def linkedValveBrowserNodes(self):
    return self._linkedValveBrowserNodes

  @linkedValveBrowserNodes.setter
  def linkedValveBrowserNodes(self, linkedValveBrowserNodes: list):
    self._linkedValveBrowserNodes = linkedValveBrowserNodes

  def addlinkedValveBrowserNode(self, linkedValveBrowserNode: slicer.vtkMRMLSequenceBrowserNode):
    self.linkedValveBrowserNodes.append(linkedValveBrowserNode)

  @property
  def readOnly(self):
    return self._readOnly

  @readOnly.setter
  def readOnly(self, enabled: bool):
    self._readOnly = enabled
    self.ui.addTimePointButton.visible = not enabled
    self.ui.removeTimePointButton.visible = not enabled
    self.ui.cardiacCyclePhaseSelector.visible = not enabled
    self.updateGUIFromMRML()

  @property
  def visible(self):
    return self.ui.visible

  @visible.setter
  def visible(self, visibility):
    self.ui.visible = visibility

  def __init__(self, parent: qt.QLayout = None):
    uiFile = str(Path(__file__).parent.parent / "Resources/UI/ValveSequenceBrowserWidget.ui")
    if not Path(uiFile).exists():
      raise FileNotFoundError(f"UI file ({uiFile}) could not be found for {self.__class__.__name__}.")
    self.ui = slicer.util.loadUI(uiFile)
    self.ui.setMRMLScene(slicer.mrmlScene)

    self.valveBrowserNodeModified = Signal()
    self.heartValveNodeModified = Signal()

    # Just used for keeping track of the observers
    self._heartValveNode = None
    self._heartValveNodeObserver = None

    self._valveVolumeBrowserNode = None
    self._valveVolumeBrowserNodeObserver = None

    self._valveBrowserNode = None
    self._valveBrowserNodeObserver = None

    self._readOnly = False

    self.lastValveBrowserSelectedItemIndex = -1

    self._linkedValveBrowserNodes = []

    self.setup(parent)

  def destroy(self):
    self.valveBrowserNode = None
    self._disconnectSignals()
    self.ui.setParent(None)
    self.ui.deleteLater()

  def setup(self, parent):
    if parent is not None:
      parent.addWidget(self.ui)

    for cardiacCyclePhaseName in CARDIAC_CYCLE_PHASE_PRESETS.keys():
      self.ui.cardiacCyclePhaseSelector.addItem(cardiacCyclePhaseName)

    self._connectSignals()

  def _connectSignals(self):
    self.ui.addTimePointButton.clicked.connect(self.onAddTimePointButtonClicked)
    self.ui.removeTimePointButton.clicked.connect(self.onRemoveTimePointButtonClicked)
    self.ui.cardiacCyclePhaseSelector.connect("currentIndexChanged(int)", self.onCardiacCyclePhaseChanged)
    self.ui.goToAnalyzedFrameButton.clicked.connect(self.onGoToAnalyzedFrameButtonClicked)

  def _disconnectSignals(self):
    self.ui.addTimePointButton.clicked.disconnect(self.onAddTimePointButtonClicked)
    self.ui.removeTimePointButton.clicked.disconnect(self.onRemoveTimePointButtonClicked)
    self.ui.cardiacCyclePhaseSelector.disconnect("currentIndexChanged(int)", self.onCardiacCyclePhaseChanged)
    self.ui.goToAnalyzedFrameButton.clicked.disconnect(self.onGoToAnalyzedFrameButtonClicked)

  def show(self):
    self.ui.show()

  def hide(self):
    self.ui.hide()

  def _removeHeartValveBrowserNodeObserver(self):
    if self._valveBrowserNode and self._valveBrowserNodeObserver:
      self._valveBrowserNode.RemoveObserver(self._valveBrowserNodeObserver)
      self._valveBrowserNodeObserver = None

  def _removeHeartValveNodeObserver(self):
    if self._heartValveNode and self._heartValveNodeObserver:
      self._heartValveNode.RemoveObserver(self._heartValveNodeObserver)
      self._heartValveNodeObserver = None

  def _removeValveVolumeBrowserObserver(self):
    if self._valveVolumeBrowserNode and self._valveVolumeBrowserNodeObserver:
      self._valveVolumeBrowserNode.RemoveObserver(self._valveVolumeBrowserNodeObserver)
      self._valveVolumeBrowserNodeObserver = None

  def _setValveVolumeToBackgroundVolume(self):
    # select background volume by default as valve volume (to spare a click for the user)
    appLogic = slicer.app.applicationLogic()
    selNode = appLogic.GetSelectionNode()
    if selNode.GetActiveVolumeID():
      valveVolumeNode = slicer.mrmlScene.GetNodeByID(selNode.GetActiveVolumeID())
      self.valveBrowser.valveVolumeNode = valveVolumeNode

  def onGoToAnalyzedFrameButtonClicked(self):
    HeartValveLib.goToAnalyzedFrame(self.valveModel)

  def onCardiacCyclePhaseChanged(self):
    if self.valveModel is None:
      return
    self.valveModel.setCardiacCyclePhase(self.ui.cardiacCyclePhaseSelector.currentText)

  def onAddTimePointButtonClicked(self):
    volumeSequenceIndex, volumeSequenceIndexValue = self.valveBrowser.getDisplayedValveVolumeSequenceIndexAndValue()
    heartValveSequenceIndex = self.valveBrowser.heartValveSequenceNode.GetItemNumberFromIndexValue(volumeSequenceIndexValue)

    if heartValveSequenceIndex >= 0: # item for timepoint exists
      self.valveBrowser.valveBrowserNode.SetSelectedItemNumber(heartValveSequenceIndex)
    else:
      logging.info(f"Add time point")
      if not volumeSequenceIndexValue:
        raise RuntimeError("Failed to add time point, could not get volume sequence")
      self.valveBrowser.addTimePoint(volumeSequenceIndexValue)
      self.heartValveNode = self.valveBrowser.heartValveNode if self.valveBrowser else None

    self.updateGUIFromMRML()

  def onRemoveTimePointButtonClicked(self):
    itemIndex, indexValue = self.valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()
    if indexValue is not None:
      # TODO: add confirm dialog
      self.valveBrowser.removeTimePoint(indexValue)

    self.updateGUIFromMRML()

  def updateGUIFromMRML(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    cardiacCyclePhase = self.valveModel.getCardiacCyclePhase() if self.valveModel else ""
    cardiacCycleIndex = 0
    if not self.valveBrowserNode or not self.valveVolumeBrowserNode or self.valveVolumeBrowserNode.GetPlaybackActive():
      self.ui.addTimePointButton.text = "Add volume"
      self.ui.setEnabled(False)
    else:
      self.ui.setEnabled(True)
      seqIndex, seqIndexValue = self.valveBrowser.getDisplayedValveVolumeSequenceIndexAndValue()
      hasTimepoint = seqIndexValue and self.valveBrowser.heartValveSequenceNode.GetItemNumberFromIndexValue(seqIndexValue) >= 0

      self.ui.removeTimePointButton.enabled = hasTimepoint
      if hasTimepoint:
        action = "Go to"
        cardiacCycleIndex = self.ui.cardiacCyclePhaseSelector.findText(cardiacCyclePhase)
        self.ui.cardiacCyclePhaseSelector.setEnabled(not self.readOnly)
      else:
        action = "Add"
        self.ui.cardiacCyclePhaseSelector.setEnabled(False)

      self.ui.addTimePointButton.text = "{action} volume (index: {index})".format(action=action, index=seqIndex + 1)

    wasBlocked = self.ui.cardiacCyclePhaseSelector.blockSignals(True)
    self.ui.cardiacCyclePhaseSelector.setCurrentIndex(cardiacCycleIndex)
    self.ui.cardiacCyclePhaseSelector.blockSignals(wasBlocked)

    valveVolumeSequenceIndexStr = self.valveModel.getVolumeSequenceIndexAsDisplayedString(
      self.valveModel.getValveVolumeSequenceIndex()) if self.valveModel else "NA"

    if self.readOnly and cardiacCyclePhase:
      valveVolumeSequenceIndexStr = "Volume index: {index} ({phase})".format(index=valveVolumeSequenceIndexStr, phase=cardiacCyclePhase)
    else:
      valveVolumeSequenceIndexStr = "Volume index: {index}".format(index=valveVolumeSequenceIndexStr)
    self.ui.valveVolumeSequenceIndexLabel.setText(valveVolumeSequenceIndexStr)

  def onValveVolumeBrowserNodeModified(self, observer=None, eventid=None):
    self.updateGUIFromMRML()

  def onHeartValveNodeModified(self, observer=None, eventid=None):
    self.updateGUIFromMRML()
    self.heartValveNodeModified.emit()

  def onValveBrowserNodeModified(self, observer=None, eventid=None):
    # Show current valve volume if switched valve time point
    lastValveBrowserSelectedItemIndex = -1
    if self.valveBrowser and self.valveVolumeNode:
      itemIndex, indexValue = self.valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()
      if indexValue is not None and self.lastValveBrowserSelectedItemIndex != itemIndex: # Switch volume
          lastValveBrowserSelectedItemIndex = itemIndex
          volumeItemIndex = self.valveBrowser.volumeSequenceNode.GetItemNumberFromIndexValue(indexValue)
          self.valveBrowser.volumeSequenceBrowserNode.SetSelectedItemNumber(volumeItemIndex)

    self.lastValveBrowserSelectedItemIndex = lastValveBrowserSelectedItemIndex
    self.updateLinkedSequenceBrowsers()
    self.updateGUIFromMRML()
    self.valveBrowserNodeModified.emit()

  def updateLinkedSequenceBrowsers(self):
    """
    Updates the selected value of the linked valve browsers to match the selected value of the main valve browser.
    """
    _, indexValue = self.valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()

    for linkedValveBrowserNode in self.linkedValveBrowserNodes:
      if not linkedValveBrowserNode:
        continue

      if linkedValveBrowserNode == self.valveBrowserNode:
        # Skip the main valve browser if it was included in the linked browser nodes
        continue

      linkedValveBrowser = HeartValveLib.HeartValves.getValveBrowser(linkedValveBrowserNode)
      if not linkedValveBrowser:
        continue

      linkedHeartValveSequenceNode = linkedValveBrowser.heartValveSequenceNode
      if not linkedHeartValveSequenceNode:
        continue

      linkedHeartValveSequenceIndex = linkedHeartValveSequenceNode.GetItemNumberFromIndexValue(indexValue)
      if linkedHeartValveSequenceIndex < 0:
        continue

      linkedValveBrowser.valveBrowserNode.SetSelectedItemNumber(linkedHeartValveSequenceIndex)
