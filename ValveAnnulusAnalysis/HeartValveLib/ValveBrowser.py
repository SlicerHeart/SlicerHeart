#
#   HeartValveBrowser.py: Manages a time series of valve models.
#

import vtk, slicer
import logging
import HeartValves
from HeartValveLib.util import createMatrixFromString

from Constants import PROBE_POSITION_PRESETS, PROBE_POSITION_UNKNOWN


class ValveBrowser:
    """Manages a time series of HeartValve nodes.
    Associated MRML node is a vtkMRMLSequenceBrowserNode.
    """

    def __init__(self):
      # copy heart valve node from the sequence into the proxy node
      self._valveBrowserNode = None

    @property
    def valveBrowserNode(self):
      return self._valveBrowserNode

    @valveBrowserNode.setter
    def valveBrowserNode(self, node):
      if self._valveBrowserNode == node:
        # no change
        return
      self._valveBrowserNode = node
      if self._valveBrowserNode:
        self.setValveBrowserNodeDefaults()

    def setValveBrowserNodeDefaults(self):
      """Initialize the browser node with defaults. Already defined values are not changed."""

      # The following line could be uncommented to show simple index, but that could be confused with the frame
      # indices of the valve volume sequence.
      # self.valveBrowserNode.SetIndexDisplayMode(slicer.vtkMRMLSequenceBrowserNode.IndexDisplayAsIndex)

      heartValveSequenceNode = self.heartValveSequenceNode
      if not self.heartValveSequenceNode:
        logging.debug("Did not find valve sequence node, create a new one")
        heartValveSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", slicer.mrmlScene.GetUniqueNameByString("HeartValveSequence"))
        self.valveBrowserNode.SetAndObserveMasterSequenceNodeID(heartValveSequenceNode.GetID())
        # When the current heartValve node changes in the scene, save it in the sequence
        self.valveBrowserNode.SetSaveChanges(heartValveSequenceNode, True)

      # Show each frame, even if it slows down replay
      self.valveBrowserNode.SetPlaybackItemSkippingEnabled(False)
      self.valveBrowserNode.SetPlaybackRateFps(1.0)

      if not self.axialSliceToRasTransformNode:
        logging.debug("Did not find annulus transform node, create a new one")
        self.axialSliceToRasTransformNode = self.createAxialSliceToRasTransformNode()

      # Initialize to default value (if not set to some other value already)
      self.probePosition

    def moveNodeToValveBrowserFolder(self, node):
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      valveBrowserNodeItemId = shNode.GetItemByDataNode(self.valveBrowserNode)
      shNode.SetItemParent(shNode.GetItemByDataNode(node), valveBrowserNodeItemId)

    @property
    def heartValveSequenceNode(self):
      if not self.valveBrowserNode:
        return None
      return self.valveBrowserNode.GetMasterSequenceNode()

    @property
    def heartValveNode(self):
      if not self.valveBrowserNode:
        return None
      heartValveNode = self.valveBrowserNode.GetProxyNode(self.valveBrowserNode.GetMasterSequenceNode())
      return heartValveNode

    def addTimePoint(self, indexValue, valveName="HeartValve"):
      heartValveSequenceNode = self.heartValveSequenceNode

      # Capture the axial slice orientation as it is displayed right now (for the time point we are
      # switching away from) so that it can be carried over to the new time point below. Without this,
      # the new time point has no item in AxialSliceToRasTransform_Sequence, and the sequence browser's
      # missing-item handling for this transform resets it to an identity matrix (rather than holding
      # the last value, as most other per-time-point proxies do) -- causing the slice views to snap to
      # an unrelated (often visibly flipped) orientation when a new time point is added.
      previousAxialSliceToRasTransformNode = self.axialSliceToRasTransformNode
      previousAxialSliceToRasMatrix = None
      if previousAxialSliceToRasTransformNode and heartValveSequenceNode.GetNumberOfDataNodes() > 0:
        previousAxialSliceToRasMatrix = vtk.vtkMatrix4x4()
        previousAxialSliceToRasTransformNode.GetMatrixTransformToParent(previousAxialSliceToRasMatrix)

      if heartValveSequenceNode.GetNumberOfDataNodes() == 0:
        valveName = slicer.mrmlScene.GetUniqueNameByString(valveName)
        logging.debug("Did not find valve node, create a new one")
        heartValveNode = slicer.vtkMRMLScriptedModuleNode()
        heartValveNode.SetHideFromEditors(False)  # allow it to appear in subject hierarchy and node selectors
        heartValveNode.SetName(valveName)
        heartValveNode.SetAttribute("ModuleName", "HeartValve")
        slicer.mrmlScene.AddNode(heartValveNode)
        heartValveSequenceNode.SetDataNodeAtValue(heartValveNode, indexValue)
        slicer.mrmlScene.RemoveNode(heartValveNode)
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(self.valveBrowserNode)
        # Create new heart valve model from the valve model sequence proxy node
        heartValveNode = self.heartValveNode
        heartValveNode.SetName(valveName)
        HeartValves.getValveModel(heartValveNode)
        self.moveNodeToValveBrowserFolder(heartValveNode)
      else:
        heartValveSequenceNode.SetDataNodeAtValue(self.heartValveNode, indexValue)

      # Switch to that new node
      index = heartValveSequenceNode.GetItemNumberFromIndexValue(indexValue)
      self.valveBrowserNode.SetSelectedItemNumber(index)
      slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(self.valveBrowserNode)

      # Give the new time point its own item in AxialSliceToRasTransform_Sequence, carrying forward the
      # orientation from the time point we switched from (see comment above). If there was no previous
      # time point (this is the valve's first) leave it as the freshly-created default.
      if previousAxialSliceToRasMatrix is not None:
        axialSliceToRasTransformSequenceNode = self.valveBrowserNode.GetSequenceNode(self.axialSliceToRasTransformNode)
        if axialSliceToRasTransformSequenceNode:
          self.addCurrentTimePointToSequence(axialSliceToRasTransformSequenceNode)
          self.axialSliceToRasTransformNode.SetMatrixTransformToParent(previousAxialSliceToRasMatrix)

      self.valveModel.initializeNewTimePoint()

      logging.info(f"Switched to heart valve phase: {index}")

    def addTimePointAtCurrentFrame(self, valveName=None):
      """Add a time point for the currently displayed valve volume frame (or switch to it if it
      already exists).

      The time point is linked to the volume frame by using the volume sequence's current index
      value as the time point's index value, which is the convention used throughout HeartValveLib
      (see ValveModel.getValveVolumeSequenceIndex). This lets scripts create a time point that is
      correctly associated with a volume frame without having to replicate the index-value bookkeeping
      (a time point created with a mismatched index value would not be linked to any volume frame).

      :param valveName: name to use if a new valve node is created. Defaults to the browser node name.
      :returns: index value of the new or existing time point, or None on failure.
      """
      _, volumeSequenceIndexValue = self.getDisplayedValveVolumeSequenceIndexAndValue()
      if not volumeSequenceIndexValue:
        logging.error("addTimePointAtCurrentFrame failed: could not get current valve volume frame")
        return None
      heartValveSequenceIndex = self.heartValveSequenceNode.GetItemNumberFromIndexValue(volumeSequenceIndexValue)
      if heartValveSequenceIndex >= 0:
        # Time point for this frame already exists: switch to it
        self.valveBrowserNode.SetSelectedItemNumber(heartValveSequenceIndex)
      else:
        if valveName is None:
          valveName = self.valveBrowserNode.GetName()
        self.addTimePoint(volumeSequenceIndexValue, valveName)
      return volumeSequenceIndexValue

    def removeTimePoint(self, indexValue):
      self.heartValveSequenceNode.RemoveDataNodeAtValue(indexValue)

      itemIndex = self.valveBrowserNode.GetSelectedItemNumber()
      numberOfDataNodes = self.heartValveSequenceNode.GetNumberOfDataNodes()
      if itemIndex >= numberOfDataNodes:
        self.valveBrowserNode.SetSelectedItemNumber(numberOfDataNodes - 1)

    def getDisplayedHeartValveSequenceIndexAndValue(self):
      """Get currently displayed item index and value of the heart valve sequence"""
      itemIndex = self.valveBrowserNode.GetSelectedItemNumber()
      sequenceNode = self.heartValveSequenceNode
      if itemIndex < 0 or itemIndex >= sequenceNode.GetNumberOfDataNodes():
        indexValue = None
      else:
        indexValue = sequenceNode.GetNthIndexValue(itemIndex)
      return itemIndex, indexValue

    def getDisplayedValveVolumeSequenceIndex(self):
      """Get currently displayed item index of valve volume sequence"""
      volumeSequenceBrowserNode = self.volumeSequenceBrowserNode
      if not volumeSequenceBrowserNode:
        return 0
      return volumeSequenceBrowserNode.GetSelectedItemNumber()

    def getDisplayedValveVolumeSequenceIndexValue(self):
      """Get currently displayed item index value of valve volume sequence"""
      itemIndex, indexValue = self.getDisplayedValveVolumeSequenceIndexAndValue()
      return indexValue

    @property
    def valveModel(self):
      valveModel = HeartValves.getValveModel(self.heartValveNode)
      return valveModel

    @property
    def volumeSequenceBrowserNode(self):
      volumeNode = self.valveVolumeNode
      if not volumeNode:
        return None
      import HeartValveLib
      volumeSequenceBrowserNode = HeartValveLib.getSequenceBrowserNodeForMasterOutputNode(volumeNode)
      return volumeSequenceBrowserNode

    @property
    def volumeSequenceNode(self):
      volumeSequenceBrowserNode = self.volumeSequenceBrowserNode
      if not volumeSequenceBrowserNode:
        return None
      volumeSequenceNode = volumeSequenceBrowserNode.GetMasterSequenceNode()
      return volumeSequenceNode

    def getDisplayedValveVolumeSequenceIndexAndValue(self):
      """Get currently displayed item index value of valve volume sequence"""
      volumeSequenceBrowserNode = self.volumeSequenceBrowserNode
      if volumeSequenceBrowserNode:
        itemIndex = volumeSequenceBrowserNode.GetSelectedItemNumber()
      else:
        itemIndex = -1
      volumeSequenceNode = self.volumeSequenceNode
      if itemIndex < 0 or itemIndex >= volumeSequenceNode.GetNumberOfDataNodes():
        indexValue = None
      else:
        indexValue = volumeSequenceNode.GetNthIndexValue(itemIndex)
      return itemIndex, indexValue

    def createAxialSliceToRasTransformNode(self):
      axialSliceToRasTransformNode = slicer.vtkMRMLLinearTransformNode()
      axialSliceToRasTransformNode.SetName(slicer.mrmlScene.GetUniqueNameByString("AxialSliceToRasTransform"))
      axialSliceToRasTransformNode.SetMatrixTransformToParent(self.defaultAxialSliceToRasTransformMatrix)

      slicer.mrmlScene.AddNode(axialSliceToRasTransformNode)
      # prevent the node from showing up in SH, as it is not something that users would need to manipulate
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      shNode.SetItemAttribute(shNode.GetItemByDataNode(axialSliceToRasTransformNode),
                              slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyExcludeFromTreeAttributeName(),
                              "1")
      self.moveNodeToValveBrowserFolder(axialSliceToRasTransformNode)
      return axialSliceToRasTransformNode

    @property
    def valveVolumeNode(self):
      if not self.valveBrowserNode:
        return None
      return self.valveBrowserNode.GetNodeReference("ValveVolume")

    @valveVolumeNode.setter
    def valveVolumeNode(self, valveVolumeNode):
      if not self.valveBrowserNode:
        raise RuntimeError("valveVolumeNode failed: invalid valve browser node")

      self.valveBrowserNode.SetNodeReferenceID("ValveVolume", valveVolumeNode.GetID() if valveVolumeNode else None)

      # Create probeToRasTransformNode if does not exist yet
      probeToRasTransformNodeId = None
      if valveVolumeNode:
        if not valveVolumeNode.GetParentTransformNode():
          probeToRasTransformNode = slicer.vtkMRMLLinearTransformNode()
          probeToRasTransformNode.SetName(slicer.mrmlScene.GetUniqueNameByString("ProbeToRasTransform"))
          slicer.mrmlScene.AddNode(probeToRasTransformNode)
          valveVolumeNode.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID())
          # Move transform under the valve volume (there is one probe positioning transform
          # for the entire volume sequence, as the probe is assumed not to move)
          shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
          valveVolumeNodeItemId = shNode.GetItemByDataNode(valveVolumeNode)
          shNode.SetItemParent(shNode.GetItemByDataNode(probeToRasTransformNode), valveVolumeNodeItemId)

        #slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(
        #  valveVolumeNode.GetScene(), slicer.vtkMRMLSubjectHierarchyNode.GetAssociatedSubjectHierarchyNode(valveVolumeNode),
        #  None, valveVolumeNode.GetName(), valveVolumeNode)
        self.updateProbeToRasTransform()

        # Make sequence browser seek widget display frame index instead of frame time
        self.volumeSequenceBrowserNode.SetIndexDisplayMode(True)

      # Apply probeToRAS transform to all nodes that move with the valve volume

      # Apply to clipped valve volume
      clippedValveVolumeNode = self.clippedValveVolumeNode
      if clippedValveVolumeNode:
        clippedValveVolumeNode.SetAndObserveTransformNodeID(probeToRasTransformNodeId)

      # Apply to nodes managed by the valveModel
      # Let the vale model know that the ProbeToRAS transform node selection changed
      # (in the future the valve model could observe browser node changes to avoid such manual notifications)
      valveModel = self.valveModel
      if valveModel:
        valveModel.onProbeToRasTransformNodeChanged()

    @property
    def clippedValveVolumeNode(self):
      """:returns Volume that is used clipped to the valve ROI. Useful for volume rendering."""
      if not self.valveBrowserNode:
        return None
      return self.valveBrowserNode.GetNodeReference("ClippedVolume")

    @clippedValveVolumeNode.setter
    def clippedValveVolumeNode(self, clippedValveVolumeNode):
      if not self.valveBrowserNode:
        raise RuntimeError("set clippedValveVolumeNode failed: invalid valve browser node")

      self.valveBrowserNode.SetNodeReferenceID("ClippedVolume",
                                               clippedValveVolumeNode.GetID() if clippedValveVolumeNode else None)

      if clippedValveVolumeNode:
        probeToRasTransformNode = self.probeToRasTransformNode
        clippedValveVolumeNode.SetAndObserveTransformNodeID(probeToRasTransformNode.GetID() if probeToRasTransformNode else None)
        self.moveNodeToValveBrowserFolder(clippedValveVolumeNode)

    @property
    def axialSliceToRasTransformNode(self):
      if not self.valveBrowserNode:
        return None
      return self.valveBrowserNode.GetNodeReference("AxialSliceToRasTransform")

    @axialSliceToRasTransformNode.setter
    def axialSliceToRasTransformNode(self, axialSliceToRasTransformNode):
      if not self.valveBrowserNode:
        raise RuntimeError("setAxialSliceToRasTransformNode failed: invalid valve browser node")
      nodeId = axialSliceToRasTransformNode.GetID() if axialSliceToRasTransformNode else None
      self.valveBrowserNode.SetNodeReferenceID("AxialSliceToRasTransform", nodeId)

    @property
    def probeToRasTransformNode(self):
      valveVolumeNode = self.valveVolumeNode
      if not valveVolumeNode:
        return None
      return valveVolumeNode.GetParentTransformNode()

    def updateProbeToRasTransform(self):
      """Compute ProbeToRasTransform from volume and probe position
      and store it in ProbeToRasTransformNode"""

      # Check inputs
      probeToRasTransformNode = self.probeToRasTransformNode
      valveVolumeNode = self.valveVolumeNode
      if not probeToRasTransformNode or not valveVolumeNode:
        return
      if not valveVolumeNode.GetImageData():
        logging.warning('updateProbeToRasTransform failed: valve volume does not contain a valid image')
        return

      # Compute probeToRasTransform so that it centers the volume and orients it approximately
      # correctly in the RAS coordinate system
      valveVolumeExtent = valveVolumeNode.GetImageData().GetExtent()
      valveVolumeCenterIjk = [(valveVolumeExtent[component*2+1]-valveVolumeExtent[component*2]+1)/2.0 for component in range(3)]
      valveVolumeCenterIjk.append(1)
      ijkToRasMatrix = vtk.vtkMatrix4x4()
      valveVolumeNode.GetIJKToRASMatrix(ijkToRasMatrix)
      valveVolumeCenterRas = ijkToRasMatrix.MultiplyPoint(valveVolumeCenterIjk)
      probeToRasTransform = vtk.vtkTransform()
      probeToRasTransformMatrix = vtk.vtkMatrix4x4()

      # get default ProbeToRasOrientation
      probePositionPreset = PROBE_POSITION_PRESETS[self.probePosition]
      probeToRasTransformMatrix.DeepCopy(createMatrixFromString(probePositionPreset['probeToRasTransformMatrix']))

      probeToRasTransform.SetMatrix(probeToRasTransformMatrix)
      probeToRasTransform.Translate(-valveVolumeCenterRas[0],-valveVolumeCenterRas[1],-valveVolumeCenterRas[2])
      probeToRasTransformNode.SetMatrixTransformToParent(probeToRasTransform.GetMatrix())

    @property
    def defaultAxialSliceToRasTransformMatrix(self):
      axialSliceToRas = vtk.vtkMatrix4x4()
      probePositionPreset = PROBE_POSITION_PRESETS[self.probePosition]
      axialSliceToRas.DeepCopy(createMatrixFromString(probePositionPreset['axialSliceToRasTransformMatrix']))
      return axialSliceToRas

    @property
    def probePosition(self):
      if not self.volumeSequenceBrowserNode:
        return PROBE_POSITION_UNKNOWN
      probePosition = self.volumeSequenceBrowserNode.GetAttribute("ProbePosition")
      if not probePosition:
        probePosition = PROBE_POSITION_UNKNOWN
        self.probePosition = probePosition
      return probePosition

    @probePosition.setter
    def probePosition(self, probePosition):
      if not self.volumeSequenceBrowserNode:
        raise RuntimeError("Setting probePosition failed: invalid volume sequence browser node")
      self.volumeSequenceBrowserNode.SetAttribute("ProbePosition", probePosition)
      self.updateProbeToRasTransform()

    @property
    def valveType(self):
      if not self.valveBrowserNode:
        return "unknown"
      valveType = self.valveBrowserNode.GetAttribute("ValveType")
      if not valveType:
        valveType = "unknown"
        self.valveType = valveType
      return valveType

    @valveType.setter
    def valveType(self, valveType):
      if not self.valveBrowserNode:
        raise RuntimeError("Setting valveType failed: invalid valve browser node")
      self.valveBrowserNode.SetAttribute("ValveType", valveType)
      self.updateValveNodeNames()

    def updateValveNodeNames(self):
      valveType = self.valveType
      valveName = valveType[0].upper()+valveType[1:]

      # update valve browser node name
      valveBrowserNodeName = f"{valveName}Valve"
      currentNodeName = self.valveBrowserNode.GetName()
      if not currentNodeName.startswith(valveBrowserNodeName): # need to update
        self.valveBrowserNode.SetName(slicer.mrmlScene.GetUniqueNameByString(valveBrowserNodeName))

      # Need to revise this, as this may no longer be necessary
      valveModel = self.valveModel
      if valveModel:
        valveModel.updateValveNodeNames()

    def makeTimeSequence(self, proxyNode):
      """
      Make a time sequence from a single node and add it to this browser node
      :param proxyNode: node that a sequence should be created for
      :return: sequence node
      """
      sequenceNode = self.valveBrowserNode.GetSequenceNode(proxyNode)
      if sequenceNode:
        # It is already a sequence node
        return sequenceNode

      sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode",
                                                        slicer.mrmlScene.GetUniqueNameByString(proxyNode.GetName()+"Sequence"))
      self.valveBrowserNode.AddProxyNode(proxyNode, sequenceNode, False)
      self.valveBrowserNode.SetSaveChanges(sequenceNode, True)
      # Add it to current timepoint
      slicer.modules.sequences.logic().UpdateSequencesFromProxyNodes(self.valveBrowserNode, proxyNode)
      # Prevent automatic creation of missing items (it would clutter the scene and would be difficult to tell what information is actually specified)
      self.valveBrowserNode.SetMissingItemMode(sequenceNode, slicer.vtkMRMLSequenceBrowserNode.MissingItemSetToDefault)
      return sequenceNode

    def addCurrentTimePointToSequence(self, sequenceNode):
      """Make a time sequence from a single node and add it to this browser node"""

      # Temporarily change missing item mode to create missing items
      oldMissingItemMode = self.valveBrowserNode.GetMissingItemMode(sequenceNode)
      oldSaveChanges = self.valveBrowserNode.GetSaveChanges(sequenceNode)

      self.valveBrowserNode.SetMissingItemMode(sequenceNode, slicer.vtkMRMLSequenceBrowserNode.MissingItemCreateFromDefault)
      self.valveBrowserNode.SetSaveChanges(sequenceNode, True)
      slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(self.valveBrowserNode)

      # Restore original missing item mode
      self.valveBrowserNode.SetSaveChanges(sequenceNode, oldSaveChanges)
      self.valveBrowserNode.SetMissingItemMode(sequenceNode, oldMissingItemMode)

      # If the proxy node's display nodes are driven by display sequences (e.g. in scenes converted
      # from the old format) then those sequences need an item for this time point as well,
      # otherwise the display nodes are reset to defaults on every browser update and the user
      # cannot control visibility or any other display property.
      proxyNode = self.valveBrowserNode.GetProxyNode(sequenceNode)
      self.addCurrentTimePointToDisplaySequences(proxyNode)

    def addCurrentTimePointToDisplaySequences(self, proxyNode):
      """Make sure that display node sequences of a displayable proxy node contain an item
      for the current time point.
      If a display node is driven by a display sequence that has no item for the current time point
      then the display node is reset to defaults on each sequence browser update and any user
      modification (such as toggling visibility) is reverted, therefore an item must be added.
      Display properties are copied from the closest existing time point.
      :param proxyNode: displayable proxy node whose display node sequences should be updated
      """
      if not proxyNode or not proxyNode.IsA("vtkMRMLDisplayableNode"):
        return
      _, indexValue = self.getDisplayedHeartValveSequenceIndexAndValue()
      if indexValue is None:
        return
      for displayNodeIndex in range(proxyNode.GetNumberOfDisplayNodes()):
        displayNode = proxyNode.GetNthDisplayNode(displayNodeIndex)
        if not displayNode:
          continue
        displaySequenceNode = self.valveBrowserNode.GetSequenceNode(displayNode)
        if not displaySequenceNode:
          # Display node is not driven by a sequence, nothing to do
          continue
        if displaySequenceNode.GetItemNumberFromIndexValue(indexValue) < 0:
          # Use the closest existing time point as template so that the new time point starts out
          # with the same appearance (the proxy display node may have already been reset to
          # defaults, so it cannot be used as template)
          templateDisplayNode = displaySequenceNode.GetDataNodeAtValue(indexValue, False)
          displaySequenceNode.SetDataNodeAtValue(templateDisplayNode if templateDisplayNode else displayNode, indexValue)
        self.valveBrowserNode.SetSaveChanges(displaySequenceNode, True)
      slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(self.valveBrowserNode)

    def setSliceOrientations(self, axialNode, ortho1Node, ortho2Node, orthoRotationDeg):

      axialSliceToRasTransformNode = self.axialSliceToRasTransformNode
      axialSliceToRas = vtk.vtkMatrix4x4()
      axialSliceToRasTransformNode.GetMatrixTransformToParent(axialSliceToRas)

      paraAxialOrientationCode = 0

      # Axial (red) - not rotated by orthoRotationDeg
      axialNode.SetSliceToRASByNTP(
        axialSliceToRas.GetElement(0, 2), axialSliceToRas.GetElement(1, 2), axialSliceToRas.GetElement(2, 2),
        axialSliceToRas.GetElement(0, 0), axialSliceToRas.GetElement(1, 0), axialSliceToRas.GetElement(2, 0),
        axialSliceToRas.GetElement(0, 3), axialSliceToRas.GetElement(1, 3), axialSliceToRas.GetElement(2, 3),
        paraAxialOrientationCode)

      # Rotate around Z axis
      axialSliceToRasRotated = vtk.vtkMatrix4x4()
      rotationTransform = vtk.vtkTransform()
      rotationTransform.RotateZ(orthoRotationDeg)
      vtk.vtkMatrix4x4.Multiply4x4(axialSliceToRas, rotationTransform.GetMatrix(), axialSliceToRasRotated)

      rotationTransform = vtk.vtkTransform()
      probePositionPreset = PROBE_POSITION_PRESETS[self.probePosition]

      # Ortho1 (yellow)
      rotationXYZ = probePositionPreset['axialSliceToOrtho1SliceRotationsDeg']
      rotationTransform.SetMatrix(axialSliceToRasRotated)
      rotationTransform.RotateX(rotationXYZ[0])
      rotationTransform.RotateY(rotationXYZ[1])
      rotationTransform.RotateZ(rotationXYZ[2])
      rotatedSliceToRas = rotationTransform.GetMatrix()
      ortho1Node.SetSliceToRASByNTP(
        rotatedSliceToRas.GetElement(0, 2), rotatedSliceToRas.GetElement(1, 2), rotatedSliceToRas.GetElement(2, 2),
        rotatedSliceToRas.GetElement(0, 0), rotatedSliceToRas.GetElement(1, 0), rotatedSliceToRas.GetElement(2, 0),
        rotatedSliceToRas.GetElement(0, 3), rotatedSliceToRas.GetElement(1, 3), rotatedSliceToRas.GetElement(2, 3),
        paraAxialOrientationCode)

      # Ortho2 (green)
      rotationXYZ = probePositionPreset['axialSliceToOrtho2SliceRotationsDeg']
      rotationTransform.SetMatrix(axialSliceToRasRotated)
      rotationTransform.RotateX(rotationXYZ[0])
      rotationTransform.RotateY(rotationXYZ[1])
      rotationTransform.RotateZ(rotationXYZ[2])
      rotatedSliceToRas = rotationTransform.GetMatrix()
      ortho2Node.SetSliceToRASByNTP(
        rotatedSliceToRas.GetElement(0, 2), rotatedSliceToRas.GetElement(1, 2), rotatedSliceToRas.GetElement(2, 2),
        rotatedSliceToRas.GetElement(0, 0), rotatedSliceToRas.GetElement(1, 0), rotatedSliceToRas.GetElement(2, 0),
        rotatedSliceToRas.GetElement(0, 3), rotatedSliceToRas.GetElement(1, 3), rotatedSliceToRas.GetElement(2, 3),
        paraAxialOrientationCode)

    def setSlicePositionAndOrientation(self, axialNode, ortho1Node, ortho2Node, position, orthoRotationDeg, axialSliceToRas=None):

      if axialSliceToRas is None:
        axialSliceToRasTransformNode = self.axialSliceToRasTransformNode
        axialSliceToRas = vtk.vtkMatrix4x4()
        axialSliceToRasTransformNode.GetMatrixTransformToParent(axialSliceToRas)

      paraAxialOrientationCode = 0

      # Axial (red) - not rotated by orthoRotationDeg
      if axialNode:
        axialNode.SetSliceToRASByNTP(
          axialSliceToRas.GetElement(0, 2), axialSliceToRas.GetElement(1, 2), axialSliceToRas.GetElement(2, 2),
          axialSliceToRas.GetElement(0, 0), axialSliceToRas.GetElement(1, 0), axialSliceToRas.GetElement(2, 0),
          position[0], position[1], position[2],
          paraAxialOrientationCode)

      # Rotate around Z axis
      axialSliceToRasRotated = vtk.vtkMatrix4x4()
      rotationTransform = vtk.vtkTransform()
      # import math
      # orthoRotationDeg = math.atan2(directionVector[1], directionVector[0])/math.pi*180.0
      rotationTransform.RotateZ(orthoRotationDeg)
      vtk.vtkMatrix4x4.Multiply4x4(axialSliceToRas, rotationTransform.GetMatrix(), axialSliceToRasRotated)

      rotationTransform = vtk.vtkTransform()
      probePositionPreset = PROBE_POSITION_PRESETS[self.probePosition]

      # Ortho1 (yellow)
      rotationXYZ = probePositionPreset['axialSliceToOrtho1SliceRotationsDeg']
      rotationTransform.SetMatrix(axialSliceToRasRotated)
      rotationTransform.RotateX(rotationXYZ[0])
      rotationTransform.RotateY(rotationXYZ[1])
      rotationTransform.RotateZ(rotationXYZ[2])
      rotatedSliceToRas = rotationTransform.GetMatrix()
      if ortho1Node:
        ortho1Node.SetSliceToRASByNTP(
          rotatedSliceToRas.GetElement(0, 2), rotatedSliceToRas.GetElement(1, 2), rotatedSliceToRas.GetElement(2, 2),
          rotatedSliceToRas.GetElement(0, 0), rotatedSliceToRas.GetElement(1, 0), rotatedSliceToRas.GetElement(2, 0),
          position[0], position[1], position[2],
          paraAxialOrientationCode)

      # Ortho2 (green)
      rotationXYZ = probePositionPreset['axialSliceToOrtho2SliceRotationsDeg']
      rotationTransform.SetMatrix(axialSliceToRasRotated)
      rotationTransform.RotateX(rotationXYZ[0])
      rotationTransform.RotateY(rotationXYZ[1])
      rotationTransform.RotateZ(rotationXYZ[2])
      rotatedSliceToRas = rotationTransform.GetMatrix()
      if ortho2Node:
        ortho2Node.SetSliceToRASByNTP(
          rotatedSliceToRas.GetElement(0, 2), rotatedSliceToRas.GetElement(1, 2), rotatedSliceToRas.GetElement(2, 2),
          rotatedSliceToRas.GetElement(0, 0), rotatedSliceToRas.GetElement(1, 0), rotatedSliceToRas.GetElement(2, 0),
          position[0], position[1], position[2],
          paraAxialOrientationCode)
