import logging
from string import Template

import vtk
import slicer
from slicer.util import VTKObservationMixin

import HeartValveLib
from HeartValveLib.Constants import CARDIAC_CYCLE_PHASE_PRESETS


MODULE_NAME = "ValveAnnulusAnalysis"


def resourcePath(filename):
  import os
  import slicer
  scriptedModulesPath = os.path.dirname(slicer.util.modulePath(MODULE_NAME))
  return os.path.join(scriptedModulesPath, 'Resources', filename)


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

      #w.readOnly = True

      valveSeries = slicer.util.getNode('MitralValve')
      w.valveBrowserNode = valveSeries

      #w.destroy()

  """

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
        self._heartValveNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.updateGUIFromMRML)

    self.valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)

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

    self.valveBrowser = HeartValveLib.HeartValves.getValveBrowser(valveBrowserNode)
    if self._valveBrowserNode and self.valveBrowser and self.valveBrowser.volumeSequenceBrowserNode is None:
      logging.warning("Could not retrieve a valid VolumeSequenceBrowserNode for the given ValveSeries.")
    self.valveVolumeBrowserNode = self.valveBrowser.volumeSequenceBrowserNode if self.valveBrowser else None

    if self.valveBrowser and not self.valveVolumeNode:
      self._setValveVolumeToBackgroundVolume()

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
        self._valveVolumeBrowserNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.updateGUIFromMRML)

  @property
  def readOnly(self):
    return self._readOnly

  @readOnly.setter
  def readOnly(self, enabled: bool):
    self._readOnly = enabled
    self.ui.addTimePointButton.visible = not enabled
    self.ui.removeTimePointButton.visible = not enabled
    self.ui.cardiacCyclePhaseSelector.enabled = not enabled
    self.updateGUIFromMRML()

  @property
  def visible(self):
    return self.ui.visible

  @visible.setter
  def visible(self, visibility):
    self.ui.visible = visibility

  def __init__(self, parent=None): # parent should be a layout
    self.ui = slicer.util.loadUI(resourcePath("UI/ValveSequenceBrowserWidget.ui"))
    self.ui.setMRMLScene(slicer.mrmlScene)

    # Just used for keeping track of the observers
    self._heartValveNode = None
    self._heartValveNodeObserver = None

    self._valveVolumeBrowserNode = None
    self._valveVolumeBrowserNodeObserver = None

    self._valveBrowserNode = None
    self._valveBrowserNodeObserver = None

    self.valveModel = None
    self.valveBrowser = None

    self._readOnly = False

    self.lastValveBrowserSelectedItemIndex = -1

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
    HeartValveLib.goToAnalyzedFrame(self.valveBrowser.valveModel if self.valveBrowser else None)

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
    cardiacCycleIndex = 0
    if not self.valveBrowserNode or not self.valveVolumeBrowserNode or self.valveVolumeBrowserNode.GetPlaybackActive():
      self.ui.addTimePointButton.text = "Add volume"
      self.ui.setEnabled(False)
    else:
      self.ui.setEnabled(True)
      seqIndex, seqIndexValue = self.valveBrowser.getDisplayedValveVolumeSequenceIndexAndValue()
      hasTimepoint = seqIndexValue and self.valveBrowser.heartValveSequenceNode.GetItemNumberFromIndexValue(seqIndexValue) >= 0

      self.ui.removeTimePointButton.enabled = hasTimepoint
      t = Template("$action volume (index = $index)")
      if hasTimepoint:
        self.ui.addTimePointButton.text = t.substitute(action="Go to", index=seqIndex + 1)
        cardiacCycleIndex = self.ui.cardiacCyclePhaseSelector.findText(self.valveModel.getCardiacCyclePhase()) if self.valveModel else 0
        self.ui.cardiacCyclePhaseSelector.setEnabled(not self.readOnly)
      else:
        self.ui.addTimePointButton.text = t.substitute(action="Add", index=seqIndex + 1)
        self.ui.cardiacCyclePhaseSelector.setEnabled(False)

    wasBlocked = self.ui.cardiacCyclePhaseSelector.blockSignals(True)
    self.ui.cardiacCyclePhaseSelector.setCurrentIndex(cardiacCycleIndex)
    self.ui.cardiacCyclePhaseSelector.blockSignals(wasBlocked)

    valveVolumeSequenceIndexStr = self.valveModel.getVolumeSequenceIndexAsDisplayedString(
      self.valveModel.getValveVolumeSequenceIndex()) if self.valveModel else ""
    self.ui.valveVolumeSequenceIndexValue.setText(valveVolumeSequenceIndexStr)

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
    self.updateGUIFromMRML()
