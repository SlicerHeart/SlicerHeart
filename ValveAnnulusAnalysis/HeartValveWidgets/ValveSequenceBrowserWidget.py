import logging
from string import Template
from enum import IntEnum

import vtk
import slicer
from slicer.util import VTKObservationMixin

import HeartValveLib
from HeartValveLib.Constants import CARDIAC_CYCLE_PHASE_PRESETS


MODULE_NAME = "ValveAnnulusAnalysis"


class Permission(IntEnum):
  READONLY=0
  CREATE=1


def resourcePath(filename):
  import os
  import slicer
  scriptedModulesPath = os.path.dirname(slicer.util.modulePath(MODULE_NAME))
  return os.path.join(scriptedModulesPath, 'Resources', filename)


class ValveSequenceBrowserWidget:

  @property
  def valveVolumeNode(self):
    if not self.valveBrowser:
      return None
    return self.valveBrowser.valveVolumeNode

  def __init__(self, parent=None): # parent should be a layout
    self.ui = slicer.util.loadUI(resourcePath("UI/ValveSequenceBrowserWidget.ui"))
    self.ui.setMRMLScene(slicer.mrmlScene)

    # Just used for keeping track of the observers
    self.heartValveNode = None
    self.heartValveNodeObserver = None

    self.valveVolumeBrowserNode = None          # general browser node that is usually used
    self.valveVolumeBrowserNodeObserver = None

    self.valveModel = None
    self.valveBrowser = None
    self.valveBrowserNode = None
    self.valveBrowserNodeObserver = None
    self.lastValveBrowserSelectedItemIndex = -1

    self.setup(parent)

  def setPermission(self, mode: Permission):
    assert mode in set(Permission)
    self.ui.addTimePointButton.visible = mode == Permission.CREATE
    self.ui.removeTimePointButton.visible = mode == Permission.CREATE

  def destroy(self):
    self.ui.setParent(None)

  def setup(self, parent):
    if parent is not None:
      parent.addWidget(self.ui)

    for cardiacCyclePhaseName in CARDIAC_CYCLE_PHASE_PRESETS.keys():
      self.ui.cardiacCyclePhaseSelector.addItem(cardiacCyclePhaseName)

    # connections
    self.ui.addTimePointButton.clicked.connect(self.onAddTimePointButtonClicked)
    self.ui.removeTimePointButton.clicked.connect(self.onRemoveTimePointButtonClicked)
    self.ui.cardiacCyclePhaseSelector.connect("currentIndexChanged(int)", self.onCardiacCyclePhaseChanged)
    self.ui.goToAnalyzedFrameButton.clicked.connect(self.onGoToAnalyzedFrameButtonClicked)

  def _removeAllObservers(self):
    self._removeValveVolumeBrowserObserver()
    self._removeHeartValveNodeObserver()
    self._removeHeartValveBrowserNodeObserver()

  def setHeartValveBrowserNode(self, heartValveBrowserNode):
    self.ui.heartValveBrowserPlayWidget.setMRMLSequenceBrowserNode(heartValveBrowserNode)
    self.ui.heartValveBrowserSeekWidget.setMRMLSequenceBrowserNode(heartValveBrowserNode)

    if not heartValveBrowserNode:
      self._removeAllObservers()
      self.disableGUI()
      return

    valveBrowserNode = self.valveBrowser.valveBrowserNode if self.valveBrowser else None
    if valveBrowserNode == heartValveBrowserNode and \
       valveBrowserNode == self.valveBrowserNode and self.valveBrowserNodeObserver:
      # no change and already observed
      return

    self._setAndObserveHeartValveBrowserNode(heartValveBrowserNode)

    self.valveBrowser = HeartValveLib.HeartValves.getValveBrowser(heartValveBrowserNode)
    if self.valveBrowser:
      valveVolumeNode = self.valveVolumeNode
      if not valveVolumeNode:
        self._setValveVolumeToBackgroundVolume()

      valveVolumeBrowserNode = self.valveBrowser.volumeSequenceBrowserNode if self.valveBrowser else None
      if (valveVolumeBrowserNode == self.valveVolumeBrowserNode) and self.valveVolumeBrowserNodeObserver:
        # no change and already observed
        return
      self._addValveVolumeBrowserNodeObserver(valveVolumeBrowserNode)
      self.updateGUIFromValveVolumeBrowser()

    self.updateGUIFromHeartValveNode()
    self.onGoToAnalyzedFrameButtonClicked()

    heartValveNode = self.valveBrowser.heartValveNode if self.valveBrowser else None
    self.setHeartValveNode(heartValveNode)

  def _setValveVolumeToBackgroundVolume(self):
    # select background volume by default as valve volume (to spare a click for the user)
    appLogic = slicer.app.applicationLogic()
    selNode = appLogic.GetSelectionNode()
    if selNode.GetActiveVolumeID():
      valveVolumeNode = slicer.mrmlScene.GetNodeByID(selNode.GetActiveVolumeID())
      self.valveBrowser.valveVolumeNode = valveVolumeNode

  def setHeartValveNode(self, heartValveNode):
    if self.valveModel and self.valveModel.getHeartValveNode() == heartValveNode:
      return

    self._setAndObserveHeartValveNode(heartValveNode)
    self.valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)

    self.updateGUIFromHeartValveNode()
    self.onGoToAnalyzedFrameButtonClicked()

  def _setAndObserveHeartValveBrowserNode(self, heartValveBrowserNode):
    self._removeHeartValveBrowserNodeObserver()
    self.valveBrowserNode = heartValveBrowserNode
    if self.valveBrowserNode:
      self.valveBrowserNodeObserver = \
        self.valveBrowserNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onValveBrowserNodeModified)

  def _removeHeartValveBrowserNodeObserver(self):
    if self.valveBrowserNode and self.valveBrowserNodeObserver:
      self.valveBrowserNode.RemoveObserver(self.valveBrowserNodeObserver)
      self.valveBrowserNodeObserver = None

  def _setAndObserveHeartValveNode(self, heartValveNode):
    self._removeHeartValveNodeObserver()
    self.heartValveNode = heartValveNode
    if self.heartValveNode:
      self.heartValveNodeObserver = \
        self.heartValveNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.updateGUIFromHeartValveNode)

  def _removeHeartValveNodeObserver(self):
    if self.heartValveNode and self.heartValveNodeObserver:
      self.heartValveNode.RemoveObserver(self.heartValveNodeObserver)
      self.heartValveNodeObserver = None

  def onGoToAnalyzedFrameButtonClicked(self):
    HeartValveLib.goToAnalyzedFrame(self.valveBrowser.valveModel)

  def _addValveVolumeBrowserNodeObserver(self, valveVolumeBrowserNode):
    self._removeValveVolumeBrowserObserver()
    # Set and observe new parameter node
    self.valveVolumeBrowserNode = valveVolumeBrowserNode
    if self.valveVolumeBrowserNode:
      self.valveVolumeBrowserNodeObserver = \
        self.valveVolumeBrowserNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.updateGUIFromValveVolumeBrowser)

  def _removeValveVolumeBrowserObserver(self):
    if self.valveVolumeBrowserNode and self.valveVolumeBrowserNodeObserver:
      self.valveVolumeBrowserNode.RemoveObserver(self.valveVolumeBrowserNodeObserver)
      self.valveVolumeBrowserNodeObserver = None

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
      heartValveNode = self.valveBrowser.heartValveNode if self.valveBrowser else None
      self.setHeartValveNode(heartValveNode)

    self.updateGUIFromValveVolumeBrowser()

  def onRemoveTimePointButtonClicked(self):
    itemIndex, indexValue = self.valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()
    if indexValue is not None:
      # TODO: add confirm dialog
      self.valveBrowser.removeTimePoint(indexValue)

    self.updateGUIFromHeartValveNode()

  def disableGUI(self):
    self.ui.addTimePointButton.text = "Add volume"
    self._setCardiacCycleIndex(0)
    self.ui.setEnabled(False)

  def updateGUIFromValveVolumeBrowser(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    if not self.valveVolumeBrowserNode or self.valveVolumeBrowserNode.GetPlaybackActive():
      self.disableGUI()
      return

    seqIndex, seqIndexValue = self.valveBrowser.getDisplayedValveVolumeSequenceIndexAndValue()
    hasTimepoint = seqIndexValue and self.valveBrowser.heartValveSequenceNode.GetItemNumberFromIndexValue(seqIndexValue) >= 0

    self.ui.setEnabled(self.valveBrowser.valveBrowserNode is not None if self.valveBrowser else False)
    self.ui.removeTimePointButton.enabled = hasTimepoint
    self.ui.cardiacCyclePhaseSelector.enabled = hasTimepoint

    t = Template("$action volume (index = $index)")
    if hasTimepoint:
      self.ui.addTimePointButton.text = t.substitute(action="Go to", index=seqIndex + 1)
      heartValveNode = self.valveBrowser.heartValveSequenceNode.GetDataNodeAtValue(seqIndexValue)
      self._setCardiacCycleIndex(
        self.ui.cardiacCyclePhaseSelector.findText(heartValveNode.GetAttribute("CardiacCyclePhase"))
      )
    else:
      self.ui.addTimePointButton.text = t.substitute(action="Add", index=seqIndex + 1)
      self._setCardiacCycleIndex(0)

  def updateGUIFromHeartValveNode(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    self.ui.setEnabled(self.valveBrowser.valveBrowserNode is not None if self.valveBrowser else False)

    self._setCardiacCycleIndex(
      self.ui.cardiacCyclePhaseSelector.findText(self.valveModel.getCardiacCyclePhase()) if self.valveModel else 0
    )

    valveVolumeSequenceIndexStr = self.valveModel.getVolumeSequenceIndexAsDisplayedString(
      self.valveModel.getValveVolumeSequenceIndex()) if self.valveModel else ""
    self.ui.valveVolumeSequenceIndexValue.setText(valveVolumeSequenceIndexStr)

    valveModelSelected = self.valveModel is not None
    self.ui.cardiacCyclePhaseSelector.setEnabled(valveModelSelected)

  def _setCardiacCycleIndex(self, index):
    wasBlocked = self.ui.cardiacCyclePhaseSelector.blockSignals(True)
    self.ui.cardiacCyclePhaseSelector.setCurrentIndex(index)
    self.ui.cardiacCyclePhaseSelector.blockSignals(wasBlocked)

  def onValveBrowserNodeModified(self, observer=None, eventid=None):
    # Show current valve volume if switched valve time point
    if self.valveBrowser and self.valveVolumeNode:
      itemIndex, indexValue = self.valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()
      if indexValue is not None:
        if self.lastValveBrowserSelectedItemIndex != itemIndex:
          self.lastValveBrowserSelectedItemIndex = itemIndex
          # Switch volume
          volumeItemIndex = self.valveBrowser.volumeSequenceNode.GetItemNumberFromIndexValue(indexValue)
          self.valveBrowser.volumeSequenceBrowserNode.SetSelectedItemNumber(volumeItemIndex)
      else:
        # No valve node yet in the sequence
        self.lastValveBrowserSelectedItemIndex = -1
    else:
      self.lastValveBrowserSelectedItemIndex = -1

    self.updateGUIFromHeartValveNode()