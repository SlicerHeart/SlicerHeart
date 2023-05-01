#
#   HeartValveBrowser.py: Manages a time series of valve models.
#

import vtk, slicer
import logging
import HeartValves

class ValveBrowser:
    """Manages a time series of HeartValve nodes.
    Associated MRML node is a vtkMRMLSequenceBrowserNode.
    """

    def __init__(self):
      # copy heart valve node from the sequence into the proxy node
      self.valveBrowserNode = None
      self.placeholderIndexValue = "-1"

    def setValveBrowserNode(self, node):
      if self.valveBrowserNode == node:
        # no change
        return
      self.valveBrowserNode = node
      if self.valveBrowserNode:
        self.setValveBrowserNodeDefaults()

    def getValveBrowserNode(self):
      return self.valveBrowserNode

    def setValveBrowserNodeDefaults(self):
      """Initialize the browser node with defaults. Already defined values are not changed."""
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      browserShItemId = shNode.GetItemByDataNode(self.valveBrowserNode)
      if shNode.GetItemOwnerPluginName(browserShItemId) != 'HeartValves':
        shNode.SetItemAttribute(browserShItemId, "ModuleName", "HeartValve")
        shNode.RequestOwnerPluginSearch(self.valveBrowserNode)

      if not self.getHeartValveSequenceNode():
        logging.debug("Did not find valve sequence node, create a new one")
        heartValveSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", slicer.mrmlScene.GetUniqueNameByString("HeartValveSequence"))
        self.valveBrowserNode.SetAndObserveMasterSequenceNodeID(heartValveSequenceNode.GetID())
        # When the current heartValve node changes in the scene, save it in the sequence
        self.valveBrowserNode.SetSaveChanges(heartValveSequenceNode, True)
      
      if not self.getHeartValveNode():
        logging.debug("Did not find valve node, create a new one")
        heartValveNode = slicer.vtkMRMLScriptedModuleNode()
        heartValveNode.SetHideFromEditors(False)  # allow it to appear in subject hierarchy and node selectors
        heartValveNode.SetName(slicer.mrmlScene.GetUniqueNameByString("HeartValve"))
        heartValveNode.SetAttribute("ModuleName", "HeartValve")
        slicer.mrmlScene.AddNode(heartValveNode)
        heartValveSequenceNode.SetDataNodeAtValue(heartValveNode, self.placeholderIndexValue)
        slicer.mrmlScene.RemoveNode(heartValveNode)
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(self.valveBrowserNode)
        # Create new heart valve model from the valve model sequence proxy node
        heartValveNode = self.getHeartValveNode()
        HeartValves.getValveModel(heartValveNode)

    def getHeartValveSequenceNode(self):
      if not self.valveBrowserNode:
        return None
      return self.valveBrowserNode.GetMasterSequenceNode()
    
    def getHeartValveNode(self):
      if not self.valveBrowserNode:
        return None
      heartValveNode = self.valveBrowserNode.GetProxyNode(self.valveBrowserNode.GetMasterSequenceNode())
      return heartValveNode

    def addHeartValvePhase(self, indexValue):
      heartValveNode = self.getHeartValveNode()
      heartValveSequenceNode = self.getHeartValveSequenceNode()
      heartValveSequenceNode.SetDataNodeAtValue(heartValveNode, indexValue)
      # Switch to that new node
      index = heartValveSequenceNode.GetItemNumberFromIndexValue(indexValue)
      self.valveBrowserNode.SetSelectedItemNumber(index)
      slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(self.valveBrowserNode)
      logging.info(f"Switched to heart valve phase: {index}")
      # Placeholder sequence item is no longer needed, delete it if still exists
      if indexValue != self.placeholderIndexValue:
        if heartValveSequenceNode.GetDataNodeAtValue(self.placeholderIndexValue):
          self.removeHeartValvePhase(self.placeholderIndexValue)

    def removeHeartValvePhase(self, indexValue):
      heartValveSequenceNode = self.getHeartValveSequenceNode()
      heartValveSequenceNode.RemoveDataNodeAtValue(indexValue)

    def getDisplayedValveVolumeSequenceIndex(self):
      """Get currently displayed item index of valve volume sequence"""
      volumeSequenceBrowserNode = self.getVolumeSequenceBrowserNode()
      if not volumeSequenceBrowserNode:
        return 0
      return volumeSequenceBrowserNode.GetSelectedItemNumber()

    def getDisplayedValveVolumeSequenceIndex(self):
      """Get currently displayed item index of valve volume sequence"""
      volumeSequenceBrowserNode = self.getVolumeSequenceBrowserNode()
      if not volumeSequenceBrowserNode:
        return 0
      return volumeSequenceBrowserNode.GetSelectedItemNumber()

    def getValveModel(self):
      heartValveNode = self.getHeartValveNode()
      valveModel = HeartValves.getValveModel(heartValveNode)
      return valveModel

    def getVolumeSequenceBrowserNode(self):
      valveModel = self.getValveModel()
      volumeNode = valveModel.getValveVolumeNode()
      if not volumeNode:
        return None
      import HeartValveLib
      volumeSequenceBrowserNode = HeartValveLib.getSequenceBrowserNodeForMasterOutputNode(volumeNode)
      return volumeSequenceBrowserNode

    def getDisplayedValveVolumeSequenceIndexValue(self):
      """Get currently displayed item index value of valve volume sequence"""
      valveModel = self.getValveModel()
      volumeNode = valveModel.getValveVolumeNode()
      if not volumeNode:
        return None
      import HeartValveLib
      volumeSequenceBrowserNode = HeartValveLib.getSequenceBrowserNodeForMasterOutputNode(volumeNode)
      itemIndex = volumeSequenceBrowserNode.GetSelectedItemNumber()
      volumeSequenceNode = volumeSequenceBrowserNode.GetMasterSequenceNode()
      if itemIndex < 0 or itemIndex >= volumeSequenceNode.GetNumberOfDataNodes():
        return None
      indexValue = volumeSequenceNode.GetNthIndexValue(itemIndex)
      return indexValue
