import logging

import slicer
import qt
import ctk
import vtk
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleWidget,
    ScriptedLoadableModuleLogic,
)

from HeartValveLib.HeartValves import (
    getValveModel,
    updateLegacyAnnulusCurveNode,
    updateLegacyPapillaryMuscleNodes,
    updateLegacyLeafletSurfaceBoundaryNodes,
    updateLegacyCoaptationModelNodes,
    getSequenceBrowserNodeForMasterOutputNode,
)
from HeartValveLib.helpers import getAllModuleSpecificScriptableNodes
from HeartValveLib.Constants import VALVE_MASK_SEGMENT_ID
from HeartValveLib.util import getAllSegmentIDs


class Converter4DSequences(ScriptedLoadableModule):
    """Minimal module exposing HeartValve migration utilities."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "Converter4DSequences"
        self.parent.categories = ["Cardiac"]
        self.parent.dependencies = []
        self.parent.contributors = ["SlicerHeart Team"]
        self.parent.helpText = (
            "Convert segmented HeartValve nodes in the current scene to the latest HeartValveLib format."
        )
        self.parent.acknowledgementText = ("Part of the SlicerHeart project.")


class Converter4DSequencesWidget(ScriptedLoadableModuleWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logic = None

    def setup(self):
        super().setup()

        # Build minimal UI programmatically
        migrationPanel = ctk.ctkCollapsibleButton()
        migrationPanel.text = "HeartValve migration"
        migrationLayout = qt.QFormLayout(migrationPanel)

        label = qt.QLabel("Convert segmented HeartValve nodes to the new format:")
        self.convertHeartValvesButton = qt.QPushButton("Convert segmented HeartValves")
        self.convertHeartValvesButton.toolTip = (
            "Scan the scene and convert all segmented HeartValve nodes using HeartValveLib helpers."
        )
        migrationLayout.addRow(label, self.convertHeartValvesButton)

        label2 = qt.QLabel("Convert single-frame HeartValve nodes to multi-frame sequences:")
        self.convertSequencesButton = qt.QPushButton("Convert to multi-frame sequences")
        self.convertSequencesButton.toolTip = (
            "Convert old format HeartValve nodes (single frame reference) to new format (multi-frame sequences)."
        )
        migrationLayout.addRow(label2, self.convertSequencesButton)

        label3 = qt.QLabel("Convert HeartValveMeasurement nodes (A-P distance, etc.) to sequences:")
        self.convertMeasurementsButton = qt.QPushButton("Convert measurements to sequences")
        self.convertMeasurementsButton.toolTip = (
            "Convert HeartValveMeasurement nodes containing analysis results to sequence format."
        )
        migrationLayout.addRow(label3, self.convertMeasurementsButton)

        label4 = qt.QLabel("Convert CardiacDeviceAnalysis nodes to sequences:")
        self.convertDevicesButton = qt.QPushButton("Convert devices to sequences")
        self.convertDevicesButton.toolTip = (
            "Convert CardiacDeviceAnalysis nodes to sequence format."
        )
        migrationLayout.addRow(label4, self.convertDevicesButton)

        label5 = qt.QLabel("Convert all SlicerHeart nodes:")
        self.convertAllButton = qt.QPushButton("Convert all nodes to sequences")
        self.convertAllButton.toolTip = (
            "Convert all SlicerHeart-related nodes (HeartValve, Measurements, Devices) to sequence format."
        )
        migrationLayout.addRow(label5, self.convertAllButton)

        self.layout.addWidget(migrationPanel)
        self.layout.addStretch(1)

        # Logic
        self.logic = Converter4DSequencesLogic()

        # Wire buttons
        self.convertHeartValvesButton.connect("clicked(bool)", self.onConvertHeartValvesButton)
        self.convertSequencesButton.connect("clicked(bool)", self.onConvertSequencesButton)
        self.convertMeasurementsButton.connect("clicked(bool)", self.onConvertMeasurementsButton)
        self.convertDevicesButton.connect("clicked(bool)", self.onConvertDevicesButton)
        self.convertAllButton.connect("clicked(bool)", self.onConvertAllButton)

    def onConvertHeartValvesButton(self):
        with slicer.util.tryWithErrorDisplay("Conversion failed.", waitCursor=True):
            try:
                slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
                results = self.logic.convertSegmentedHeartValvesToNewFormat()
                count = results['convertedCount']
                slicer.util.infoDisplay(f"Converted {count} segmented HeartValve node(s) to the new format.")
            finally:
                slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)

    def onConvertSequencesButton(self):
        with slicer.util.tryWithErrorDisplay("Conversion failed.", waitCursor=True):
            try:
                slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
                count = self.logic.convertSingleFrameToMultiFrameSequences()
                slicer.util.infoDisplay(f"Converted {count} HeartValve node(s) to multi-frame sequence format.")
            finally:
                slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)

    def onConvertMeasurementsButton(self):
        with slicer.util.tryWithErrorDisplay("Conversion failed.", waitCursor=True):
            try:
                slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
                count = self.logic.convertHeartValveMeasurementNodesToSequences()
                slicer.util.infoDisplay(f"Converted {count} HeartValveMeasurement node(s) to sequence format.")
            finally:
                slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)

    def onConvertDevicesButton(self):
        with slicer.util.tryWithErrorDisplay("Conversion failed.", waitCursor=True):
            try:
                slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
                count = self.logic.convertCardiacDeviceNodesToSequences()
                slicer.util.infoDisplay(f"Converted {count} CardiacDeviceAnalysis node(s) to sequence format.")
            finally:
                slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)

    def onConvertAllButton(self):
        with slicer.util.tryWithErrorDisplay("Conversion failed.", waitCursor=True):
            try:
                slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
                # First, run the legacy conversion for segmented valves
                segmentedResults = self.logic.convertSegmentedHeartValvesToNewFormat()
                segmentedCount = segmentedResults['convertedCount']

                # Then, convert all types to sequences
                results = self.logic.convertSingleFrameToMultiFrameSequences()
                valveCount = results['convertedCount']
                nodesToDelete = results['nodesToRemove']

                measurementCount = self.logic.convertHeartValveMeasurementNodesToSequences()
                deviceCount = self.logic.convertCardiacDeviceNodesToSequences()

                # Now that all conversions are done, remove the original nodes
                for node in nodesToDelete:
                    if node:
                        logging.info(f"Removing converted heart valve node: {node.GetName()}")
                        slicer.mrmlScene.RemoveNode(node)

                totalCount = valveCount + measurementCount + deviceCount
                slicer.util.infoDisplay(
                    f"Conversion complete:\n"
                    f"  - {segmentedCount} segmented HeartValve node(s) updated.\n"
                    f"  - {valveCount} HeartValve node(s) converted to sequence format.\n"
                    f"  - {measurementCount} HeartValveMeasurement node(s) converted to sequence format.\n"
                    f"  - {deviceCount} CardiacDeviceAnalysis node(s) converted to sequence format.\n"
                    f"Total: {totalCount} node(s) converted to sequences."
                )
            finally:
                slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)


class Converter4DSequencesLogic(ScriptedLoadableModuleLogic):
    def _createSequenceForNode(self, browserNode, sequenceName, indexName="time", indexUnit="frame", indexType=slicer.vtkMRMLSequenceNode.NumericIndex):
        """
        Helper to create a sequence node and add it to a browser.

        Args:
            browserNode: The browser node to add the sequence to
            sequenceName: Name for the new sequence node
            indexName: Index name (default: "time")
            indexUnit: Index unit (default: "frame")
            indexType: Index type (default: NumericIndex)

        Returns:
            The created sequence node
        """
        sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode")
        sequenceNode.SetName(slicer.mrmlScene.GetUniqueNameByString(sequenceName))
        sequenceNode.SetIndexName(indexName)
        sequenceNode.SetIndexUnit(indexUnit)
        sequenceNode.SetIndexType(indexType)

        browserNode.AddSynchronizedSequenceNode(sequenceNode)
        browserNode.SetSaveChanges(sequenceNode, True)
        browserNode.SetMissingItemMode(sequenceNode, slicer.vtkMRMLSequenceBrowserNode.MissingItemSetToDefault)

        return sequenceNode

    def _captureTransformsFromReferencedNodes(self, hvNode, referenceRoles):
        """
        Capture transform IDs from nodes referenced by a HeartValve node.

        Args:
            hvNode: The HeartValve node
            referenceRoles: List of reference roles to capture (e.g., 'AnnulusContourPoints', 'PapillaryLineMarkup')

        Returns:
            Dictionary mapping role to list of transform IDs
        """
        transforms = {}

        for role in referenceRoles:
            numRefs = hvNode.GetNumberOfNodeReferences(role)
            if numRefs == 0:
                continue

            transforms[role] = []
            for idx in range(numRefs):
                refNode = hvNode.GetNthNodeReference(role, idx)
                if refNode:
                    transformID = refNode.GetTransformNodeID()
                    transforms[role].append(transformID)

        return transforms

    def _restoreTransformsToReferencedNodes(self, hvNode, transforms):
        """
        Restore transform IDs to nodes referenced by a HeartValve node.

        Args:
            hvNode: The HeartValve node
            transforms: Dictionary mapping role to list of transform IDs (from _captureTransformsFromReferencedNodes)
        """
        for role, transformList in transforms.items():
            for idx, transformID in enumerate(transformList):
                if transformID:
                    refNode = hvNode.GetNthNodeReference(role, idx)
                    if refNode:
                        refNode.SetAndObserveTransformNodeID(transformID)

    def convertSegmentedHeartValvesToNewFormat(self):
        """
        Convert all segmented HeartValve nodes in the current scene to the latest
        HeartValveLib format using the provided conversion helpers.

        Returns the number of segmented HeartValve nodes considered for conversion.
        """
        # Ensure proxy nodes are up-to-date
        for sequenceBrowserNode in slicer.util.getNodesByClass('vtkMRMLSequenceBrowserNode'):
            slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(sequenceBrowserNode)

        # Collect HeartValve nodes that are segmented (any non-mask segments present)
        allHeartValves = list(getAllModuleSpecificScriptableNodes("HeartValve"))
        segmentedHeartValves = []
        for hvNode in allHeartValves:
            try:
                # In legacy nodes, the segmentation is just a referenced node, no valve model exists yet
                segNode = hvNode.GetNodeReference("LeafletSegmentation")
                if not segNode:
                    # Also check for the legacy role name, which was sometimes used
                    segNode = hvNode.GetNodeReference("vtkMRMLSegmentationNode")

                if not segNode:
                    continue

                segmentIds = getAllSegmentIDs(segNode)
                nonMaskSegments = [sid for sid in segmentIds if sid != VALVE_MASK_SEGMENT_ID]
                if len(nonMaskSegments) > 0:
                    segmentedHeartValves.append(hvNode)
            except Exception as err:
                logging.warning(
                    f"Skipping HeartValve '{hvNode.GetName()}' due to error while checking segmentation: {err}"
                )

        if not segmentedHeartValves:
            logging.info("No segmented HeartValve nodes found to convert.")
            return 0

        logging.info(f"Converting {len(segmentedHeartValves)} segmented HeartValve node(s) to new format...")

        # Capture transform IDs from nodes BEFORE legacy update functions recreate them
        # These functions create new markup curve nodes without preserving transforms
        transformCaptureMap = {}

        referenceRoles = [
            'AnnulusContourPoints',
            'LeafletSurfaceBoundaryMarkup',
            'CoaptationBaseLineMarkup',
            'CoaptationMarginLineMarkup',
            'CoaptationMarginLineModel',
            'CoaptationBaseLineModel',
            'PapillaryLineMarkup'
        ]

        for hvNode in segmentedHeartValves:
            valveID = hvNode.GetID()
            transformCaptureMap[valveID] = self._captureTransformsFromReferencedNodes(hvNode, referenceRoles)

        # Run conversion helpers and restore transforms
        try:
            updateLegacyAnnulusCurveNode(segmentedHeartValves)
        except Exception as err:
            logging.warning(f"updateLegacyAnnulusCurveNode failed: {err}")

        try:
            updateLegacyPapillaryMuscleNodes(segmentedHeartValves)
        except Exception as err:
            logging.warning(f"updateLegacyPapillaryMuscleNodes failed: {err}")

        try:
            updateLegacyLeafletSurfaceBoundaryNodes(segmentedHeartValves)
        except Exception as err:
            logging.warning(f"updateLegacyLeafletSurfaceBoundaryNodes failed: {err}")

        # Restore transforms to all updated nodes
        for hvNode in segmentedHeartValves:
            valveID = hvNode.GetID()
            if valveID in transformCaptureMap:
                self._restoreTransformsToReferencedNodes(hvNode, transformCaptureMap[valveID])

        # Subject hierarchy cleanup (icons/level attr)
        try:
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            for hvNode in segmentedHeartValves:
                itemId = shNode.GetItemByDataNode(hvNode)
                shNode.RemoveItemAttribute(
                    itemId,
                    slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelAttributeName(),
                )
        except Exception as err:
            logging.warning(f"Subject hierarchy cleanup failed: {err}")

        logging.info("HeartValve conversion complete.")
        return {
            'convertedCount': len(segmentedHeartValves),
            'segmentedHeartValves': segmentedHeartValves,
            'transformCaptureMap': transformCaptureMap
        }

    def convertSingleFrameToMultiFrameSequences(self):
        """
        Convert old format scenes where analysis was done on a single frame to new format
        where multiple frames are stored in sequences.

        Old format: Each heart valve node has a ValveVolumeSequenceIndex attribute but is NOT in a sequence
        New format: Heart valve nodes are stored in a sequence synchronized with the volume sequence
        """
        logging.info("Converting single-frame heart valve nodes to multi-frame sequences")

        # Get all heart valve nodes using the same method as convertSegmentedHeartValvesToNewFormat
        allHeartValves = list(getAllModuleSpecificScriptableNodes("HeartValve"))

        if not allHeartValves:
            logging.info("No heart valve nodes found to convert")
            return 0

        # Filter to only old-format heart valves (have ValveVolumeSequenceIndex but not in a sequence)
        oldFormatHeartValves = []
        for hvNode in allHeartValves:
            try:
                # Check if this is old format: has ValveVolumeSequenceIndex attribute
                sequenceIndexStr = hvNode.GetAttribute("ValveVolumeSequenceIndex")
                if not sequenceIndexStr:
                    # No sequence index set, skip
                    continue

                # Check if already in a sequence browser (new format)
                # Old format nodes are NOT part of a sequence browser
                valveBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(hvNode)
                if valveBrowserNode:
                    # Already in a sequence browser, check if it has multiple frames
                    heartValveSequenceNode = valveBrowserNode.GetMasterSequenceNode()
                    if heartValveSequenceNode and heartValveSequenceNode.GetNumberOfDataNodes() > 1:
                        # Already converted to multi-frame format, skip
                        logging.debug(f"Skipping '{hvNode.GetName()}' - already in multi-frame sequence")
                        continue

                # This is an old-format node (has ValveVolumeSequenceIndex but not in a browser)
                oldFormatHeartValves.append(hvNode)
            except Exception as err:
                logging.warning(f"Skipping HeartValve '{hvNode.GetName()}' due to error: {err}")

        if not oldFormatHeartValves:
            logging.info("No old-format heart valve nodes found to convert")
            return 0

        logging.info(f"Converting {len(oldFormatHeartValves)} old-format heart valve node(s) to new format")

        # Group heart valve nodes by their volume sequence browser and by valve type
        # Each unique valve gets its own sequence
        valvesByVolumeSequence = {}
        for heartValveNode in oldFormatHeartValves:
            try:
                # Get volume node from the HeartValve node reference
                volumeNodeId = heartValveNode.GetNodeReferenceID("ValveVolume")
                if not volumeNodeId:
                    logging.warning(f"Valve {heartValveNode.GetName()} has no ValveVolume reference, skipping")
                    continue

                volumeNode = slicer.mrmlScene.GetNodeByID(volumeNodeId)
                if not volumeNode:
                    logging.warning(f"Valve {heartValveNode.GetName()} references invalid volume node, skipping")
                    continue

                volumeSequenceBrowserNode = getSequenceBrowserNodeForMasterOutputNode(volumeNode)
                if not volumeSequenceBrowserNode:
                    logging.warning(f"Valve {heartValveNode.GetName()} volume is not part of a sequence, skipping")
                    continue

                # Create a unique key combining browser and valve type
                browserNodeId = volumeSequenceBrowserNode.GetID()
                valveType = heartValveNode.GetAttribute("ValveType") or "Valve"
                groupingKey = (browserNodeId, valveType)

                if groupingKey not in valvesByVolumeSequence:
                    valvesByVolumeSequence[groupingKey] = {
                        'volumeSequenceBrowserNode': volumeSequenceBrowserNode,
                        'valveType': valveType,
                        'heartValveNodes': []
                    }
                valvesByVolumeSequence[groupingKey]['heartValveNodes'].append(heartValveNode)
            except Exception as err:
                logging.warning(f"Error processing valve '{heartValveNode.GetName()}': {err}")

        # Process each valve group
        convertedCount = 0
        for groupingKey, browserData in valvesByVolumeSequence.items():
            volumeSequenceBrowserNode = browserData['volumeSequenceBrowserNode']
            heartValveNodes = browserData['heartValveNodes']
            valveType = browserData['valveType']

            logging.info(f"Converting {len(heartValveNodes)} valve node(s) for valve type: {valveType}")

            # Migrate ProbePosition to new format
            if not volumeSequenceBrowserNode.GetAttribute("ProbePosition"):
                # Try to find ProbePosition from any of the heart valve nodes
                for hvNode in heartValveNodes:
                    probePosition = hvNode.GetAttribute("ProbePosition")
                    if probePosition:
                        volumeSequenceBrowserNode.SetAttribute("ProbePosition", probePosition)
                        break

            # Create a valve browser node for this specific valve
            # Each distinct valve gets its own browser and sequence
            valveBrowserNode = None
            for hvNode in heartValveNodes:
                existingBrowser = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(hvNode)
                if existingBrowser:
                    valveBrowserNode = existingBrowser
                    break

            if not valveBrowserNode:
                # Create a new valve browser node with a descriptive name based on valve type
                valveBrowserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode")
                browserName = f"{valveType}_Browser"
                valveBrowserNode.SetName(slicer.mrmlScene.GetUniqueNameByString(browserName))
                # Set the ModuleName attribute so it appears in heartValveBrowserSelector
                valveBrowserNode.SetAttribute("ModuleName", "HeartValve")
                logging.info(f"Created new valve browser node: {valveBrowserNode.GetName()}")

            # Set the ValveType attribute so ValveAnnulusAnalysis can read it
            if not valveBrowserNode.GetAttribute("ValveType"):
                valveBrowserNode.SetAttribute("ValveType", valveType)
                logging.info(f"Set ValveType attribute on browser node: {valveBrowserNode.GetName()}")

            # Get or create the heart valve sequence node for this specific valve
            heartValveSequenceNode = valveBrowserNode.GetMasterSequenceNode()
            if not heartValveSequenceNode:
                # Copy index type and name from the volume sequence to match
                volumeSequenceNode = volumeSequenceBrowserNode.GetMasterSequenceNode()

                heartValveSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode")
                sequenceName = f"{valveType}_Sequence"
                heartValveSequenceNode.SetName(slicer.mrmlScene.GetUniqueNameByString(sequenceName))
                heartValveSequenceNode.SetIndexName(volumeSequenceNode.GetIndexName())
                heartValveSequenceNode.SetIndexUnit(volumeSequenceNode.GetIndexUnit())
                heartValveSequenceNode.SetIndexType(volumeSequenceNode.GetIndexType())
                valveBrowserNode.SetAndObserveMasterSequenceNodeID(heartValveSequenceNode.GetID())
                logging.info(f"Created new heart valve sequence node: {heartValveSequenceNode.GetName()}")

            # For each valve node, add it to the sequence at its specified frame index
            for heartValveNode in heartValveNodes:
                try:
                    # Get the stored frame index from the attribute
                    sequenceIndexStr = heartValveNode.GetAttribute("ValveVolumeSequenceIndex")
                    frameIndex = int(sequenceIndexStr)

                    if frameIndex < 0:
                        logging.warning(f"Valve {heartValveNode.GetName()} has invalid frame index ({frameIndex}), skipping")
                        continue

                    # Get the index value for this frame from the volume sequence
                    masterSequenceNode = volumeSequenceBrowserNode.GetMasterSequenceNode()
                    if frameIndex >= masterSequenceNode.GetNumberOfDataNodes():
                        logging.warning(f"Frame index {frameIndex} out of range for valve {heartValveNode.GetName()}")
                        continue

                    indexValue = masterSequenceNode.GetNthIndexValue(frameIndex)

                    # Add this heart valve node to the sequence at the appropriate index
                    heartValveSequenceNode.SetDataNodeAtValue(heartValveNode, indexValue)
                    logging.info(f"Added {heartValveNode.GetName()} to sequence at frame {frameIndex} (index value: {indexValue})")
                    convertedCount += 1
                except Exception as err:
                    logging.warning(f"Error converting valve '{heartValveNode.GetName()}': {err}")

            # Set up the valve browser to save changes to the sequence
            if heartValveSequenceNode.GetNumberOfDataNodes() > 0:
                valveBrowserNode.SetSaveChanges(heartValveSequenceNode, True)
                # Select the first item to initialize the proxy node
                valveBrowserNode.SetSelectedItemNumber(0)
                # Update proxy nodes to create the current HeartValve proxy node
                slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(valveBrowserNode)
                # Get the proxy node (the current HeartValve node visible in the scene)
                proxyNode = valveBrowserNode.GetProxyNode(heartValveSequenceNode)
                if proxyNode:
                    logging.info(f"Valve browser configured with {heartValveSequenceNode.GetNumberOfDataNodes()} time points, proxy node: {proxyNode.GetName()}")
                else:
                    logging.info(f"Valve browser configured with {heartValveSequenceNode.GetNumberOfDataNodes()} time points")

                # Initialize the valve model for the first timepoint
                try:
                    valveModel = getValveModel(proxyNode if proxyNode else heartValveNodes[0])
                    if valveModel:
                        logging.debug(f"Initialized valve model for first timepoint")

                        # Convert referenced nodes (annulus curves, segmentations, etc.) to sequences
                        self._convertReferencedNodesToSequences(valveBrowserNode, heartValveSequenceNode, heartValveNodes, volumeSequenceBrowserNode)
                except Exception as err:
                    logging.warning(f"Could not initialize valve model: {err}")

        # Remove original heart valve nodes that have been converted
        nodesToRemove = [node for browserData in valvesByVolumeSequence.values() for node in browserData['heartValveNodes']]

        logging.info(f"Conversion complete. Converted {convertedCount} heart valve node(s)")
        return {'convertedCount': convertedCount, 'nodesToRemove': nodesToRemove}

    def _convertReferencedNodesToSequences(self, valveBrowserNode, heartValveSequenceNode, heartValveNodes, volumeSequenceBrowserNode):
        """
        Convert nodes referenced by HeartValve nodes (annulus curves, segmentations, etc.) to sequences.

        In the old format, each HeartValve node directly referenced its annulus curve, segmentation, etc.
        In the new format, these referenced nodes should be in sequences synchronized with the valve browser.

        Args:
            valveBrowserNode: The sequence browser node for the valve sequence
            heartValveSequenceNode: The sequence node containing the heart valve nodes
            heartValveNodes: List of heart valve nodes to process
            volumeSequenceBrowserNode: The sequence browser node for the volume
        """

        logging.info("Converting referenced nodes to sequences")

        # Get the volume sequence for index values
        volumeSequenceNode = volumeSequenceBrowserNode.GetMasterSequenceNode()

        # Collect all referenced nodes from all heart valve nodes, organized by reference role
        referencedNodesByRole = {}
        nodesToRemove = set()
        displayNodesToRemove = set()  # Track display nodes separately
        processedNodesTracker = {}  # Track which nodes we've already captured: nodeID -> entry data

        for heartValveNode in heartValveNodes:
            try:
                # Get the frame index for this valve
                sequenceIndexStr = heartValveNode.GetAttribute("ValveVolumeSequenceIndex")
                frameIndex = int(sequenceIndexStr)
                indexValue = volumeSequenceNode.GetNthIndexValue(frameIndex)

                logging.info(f"Processing valve '{heartValveNode.GetName()}' at frame {frameIndex} (indexValue: {indexValue})")

                # Get all node reference roles dynamically
                roles = []
                heartValveNode.GetNodeReferenceRoles(roles)

                # Iterate through each reference role
                for role in roles:
                    numRefs = heartValveNode.GetNumberOfNodeReferences(role)

                    for refIndex in range(numRefs):
                        referencedNode = heartValveNode.GetNthNodeReference(role, refIndex)
                        if not referencedNode:
                            continue

                        # Skip if already in a sequence
                        if slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(referencedNode):
                            logging.info(f"  Skipping '{referencedNode.GetName()}' (role: {role}) - already in a sequence")
                            continue

                        # Create a more specific key for grouping by role and a base name
                        # Strip frame-specific suffixes to group all frames of the same node type together
                        originalName = referencedNode.GetName()
                        baseName = originalName

                        # Strip frame number suffix (e.g., "_f23", "_25")
                        parts = baseName.split('_')
                        if len(parts) > 1:
                            lastPart = parts[-1]
                            if lastPart.isdigit() or (lastPart.startswith('f') and lastPart[1:].isdigit()):
                                baseName = '_'.join(parts[:-1])

                        # Also strip phase indicators for segmentations (e.g., "-ES", "-ED", "-MD")
                        if referencedNode.IsA('vtkMRMLSegmentationNode'):
                            phaseSuffixes = ['-ES', '-ED', '-MD', '-MS', '-CT', '-CD', '-CS']
                            for suffix in phaseSuffixes:
                                if baseName.endswith(suffix):
                                    baseName = baseName[:-len(suffix)]
                                    break

                        groupingKey = (role, baseName)

                        # Store this node for sequence creation
                        if groupingKey not in referencedNodesByRole:
                            referencedNodesByRole[groupingKey] = []

                        # Capture transform ID and display node per unique node
                        nodeID = referencedNode.GetID()
                        if nodeID not in processedNodesTracker:
                            # Capture transform ID if node is transformable
                            originalTransformID = None
                            if referencedNode.IsA("vtkMRMLTransformableNode"):
                                originalTransformID = referencedNode.GetTransformNodeID()

                            # Capture display node if node is displayable
                            displayNode = None
                            if referencedNode.IsA("vtkMRMLDisplayableNode"):
                                displayNode = referencedNode.GetDisplayNode()
                                if displayNode:
                                    displayNodesToRemove.add(displayNode)  # Track for later removal

                            processedNodesTracker[nodeID] = {
                                'originalTransformID': originalTransformID,
                                'displayNode': displayNode
                            }
                            nodesToRemove.add(referencedNode)
                        else:
                            logging.info(f"  Node '{referencedNode.GetName()}' already captured, reusing transform and display info")

                        # Get the cached transform and display info
                        cachedInfo = processedNodesTracker[nodeID]

                        referencedNodesByRole[groupingKey].append({
                            'node': referencedNode,
                            'indexValue': indexValue,
                            'frameIndex': frameIndex,
                            'originalTransformID': cachedInfo['originalTransformID'],  # Store the transform ID
                            'displayNode': cachedInfo['displayNode']  # Store the display node
                        })
            except Exception as err:
                logging.warning(f"Error processing references for valve '{heartValveNode.GetName()}': {err}")

        # Track sequence nodes to their original node entries for later transform verification
        sequenceToEntriesMap = {}
        # Track data sequence nodes to their display sequence nodes for correct linking
        dataSequenceToDisplaySequenceMap = {}

        for (role, baseName), nodeEntries in referencedNodesByRole.items():
            if len(nodeEntries) == 0:
                continue

            # Get a representative node to create a meaningful name
            firstNode = nodeEntries[0]['node']
            # Use the baseName for the sequence to keep it consistent
            sequenceBaseName = baseName if baseName else firstNode.GetName()

            # Log details about what we're about to add
            uniqueNodeIds = set([entry['node'].GetID() for entry in nodeEntries])
            if len(uniqueNodeIds) == 1:
                logging.warning(f"  WARNING: Same node being added at multiple time points for {baseName}!")

            try:
                # Create a single sequence node for this role
                sequenceNode = self._createSequenceForNode(
                    valveBrowserNode,
                    f"{sequenceBaseName}_Sequence",
                    volumeSequenceNode.GetIndexName(),
                    volumeSequenceNode.GetIndexUnit(),
                    volumeSequenceNode.GetIndexType()
                )

                # Add all nodes for this role to the sequence at their respective time points
                # Track which nodes we've added to avoid true duplicates (same node at same time)
                addedNodes = {}  # key: indexValue, value: node ID

                for entry in nodeEntries:
                    nodeToAdd = entry['node']
                    indexValue = entry['indexValue']

                    # Check if we already added a different node at this time point
                    if indexValue in addedNodes:
                        if addedNodes[indexValue] == nodeToAdd.GetID():
                            logging.debug(f"Skipping duplicate: same node already added at index {indexValue}")
                            continue
                        else:
                            logging.warning(f"Multiple different nodes trying to occupy index {indexValue} in sequence '{sequenceNode.GetName()}'")
                            continue

                    # For segmentation nodes, we need to create a deep copy to preserve segment data
                    # This is crucial because the same segmentation node may be referenced by multiple
                    # valve nodes at different time points in the old format
                    if nodeToAdd.IsA('vtkMRMLSegmentationNode'):
                        # Create a temporary node to hold the copy
                        nodeCopy = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode')
                        nodeCopy.Copy(nodeToAdd)
                        nodeCopy.SetName(nodeToAdd.GetName())

                        # Apply parent transform if the node is transformable
                        if nodeCopy.IsA("vtkMRMLTransformableNode") and entry['originalTransformID']:
                            nodeCopy.SetAndObserveTransformNodeID(entry['originalTransformID'])

                        # Add to sequence - SetDataNodeAtValue stores a copy of the node's data internally
                        sequenceNode.SetDataNodeAtValue(nodeCopy, indexValue)

                        # Remove the temporary copy and its display node from the scene
                        # The data is now stored in the sequence
                        tempDisplayNode = nodeCopy.GetDisplayNode()
                        if tempDisplayNode:
                            slicer.mrmlScene.RemoveNode(tempDisplayNode)
                        slicer.mrmlScene.RemoveNode(nodeCopy)
                    else:
                        # For other node types, SetDataNodeAtValue will create a copy automatically
                        sequenceNode.SetDataNodeAtValue(nodeToAdd, indexValue)

                    addedNodes[indexValue] = nodeToAdd.GetID()                # Store the mapping for later transform verification
                sequenceToEntriesMap[sequenceNode] = nodeEntries

                logging.info(f"Created sequence for role '{role}' (group: '{baseName}'): {sequenceNode.GetName()} with {sequenceNode.GetNumberOfDataNodes()} time points")

                # Create a display node sequence if any of the nodes have display nodes
                displayNodeEntries = [(entry['indexValue'], entry['displayNode']) for entry in nodeEntries if entry.get('displayNode')]
                if displayNodeEntries:
                    try:
                        displaySequenceNode = self._createSequenceForNode(
                            valveBrowserNode,
                            f"{sequenceBaseName}_Display_Sequence",
                            volumeSequenceNode.GetIndexName(),
                            volumeSequenceNode.GetIndexUnit(),
                            volumeSequenceNode.GetIndexType()
                        )

                        addedDisplayNodes = {}
                        for indexValue, displayNode in displayNodeEntries:
                            if indexValue in addedDisplayNodes:
                                continue

                            if displayNode:
                                # Create a copy of the display node
                                displayNodeCopy = slicer.mrmlScene.AddNewNodeByClass(displayNode.GetClassName())
                                displayNodeCopy.Copy(displayNode)
                                displaySequenceNode.SetDataNodeAtValue(displayNodeCopy, indexValue)
                                slicer.mrmlScene.RemoveNode(displayNodeCopy)
                                addedDisplayNodes[indexValue] = displayNode.GetID()

                        logging.info(f"  Created display node sequence: {displaySequenceNode.GetName()} with {displaySequenceNode.GetNumberOfDataNodes()} time points")

                        # Store the mapping between data sequence and display sequence
                        dataSequenceToDisplaySequenceMap[sequenceNode] = displaySequenceNode
                    except Exception as err:
                        logging.warning(f"  Error creating display node sequence: {err}")

            except Exception as err:
                logging.warning(f"Error creating sequence for role '{role}': {err}")

        # Update proxy nodes to reflect the new sequences
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(valveBrowserNode)

        # Ensure proxy nodes have the correct parent transforms and descriptive names
        # Map from grouping key to the actual sequence node that was created
        createdSequences = {}  # (role, baseName) -> sequenceNode

        # Get all synchronized sequences
        synchronizedSequenceNodes = vtk.vtkCollection()
        valveBrowserNode.GetSynchronizedSequenceNodes(synchronizedSequenceNodes, False)

        for i in range(synchronizedSequenceNodes.GetNumberOfItems()):
            seqNode = synchronizedSequenceNodes.GetItemAsObject(i)
            if not seqNode:
                continue

            # Try to match this sequence to one of our groups
            seqName = seqNode.GetName()
            for (role, baseName) in referencedNodesByRole.keys():
                expectedBaseName = baseName if baseName else ""
                if expectedBaseName and expectedBaseName in seqName:
                    createdSequences[(role, baseName)] = seqNode
                    break

        # Now configure each proxy node
        for (role, baseName), nodeEntries in referencedNodesByRole.items():
            if len(nodeEntries) == 0:
                continue

            # Find the sequence we created for this group
            seqNode = createdSequences.get((role, baseName))
            if not seqNode:
                logging.warning(f"Could not find sequence for group ({role}, {baseName})")
                continue

            # Get and configure the proxy node
            proxyNode = valveBrowserNode.GetProxyNode(seqNode)
            if proxyNode:
                # Give the proxy node a descriptive name (remove _Sequence suffix)
                descriptiveName = baseName if baseName else nodeEntries[0]['node'].GetName()
                proxyNode.SetName(descriptiveName)
                logging.info(f"Renamed proxy node to: {descriptiveName}")

                # Find a transform ID from any of the original nodes in this group
                # Use the transform ID that was captured when we first found the nodes
                # (before they were added to sequences, which might clear their transforms)
                originalTransformID = None
                for entry in nodeEntries:
                    # First try the stored transform ID
                    if 'originalTransformID' in entry and entry['originalTransformID']:
                        originalTransformID = entry['originalTransformID']
                        logging.debug(f"Using stored transform {originalTransformID} from node '{entry['node'].GetName()}'")
                        break
                    # Fallback to checking the node directly
                    transformID = entry['node'].GetTransformNodeID()
                    logging.debug(f"Checking node '{entry['node'].GetName()}' (ID: {entry['node'].GetID()}): transformID = {transformID}")
                    if transformID:
                        originalTransformID = transformID
                        logging.debug(f"Found transform {transformID} on node '{entry['node'].GetName()}'")
                        break

                # Set the transform on the proxy node to match the original (only for transformable nodes)
                if proxyNode.IsA("vtkMRMLTransformableNode"):
                    if originalTransformID:
                        if proxyNode.GetTransformNodeID() != originalTransformID:
                            proxyNode.SetAndObserveTransformNodeID(originalTransformID)
                            logging.info(f"Set parent transform on proxy node '{proxyNode.GetName()}': {originalTransformID}")
                    else:
                        logging.info(f"No transform to set for proxy node '{proxyNode.GetName()}' (checked {len(nodeEntries)} original nodes)")

        # Final pass: ensure all proxy nodes have their transforms and display nodes set correctly
        # This is necessary because browser updates might have cleared transforms or display links
        logging.info("Final pass: verifying and reapplying transforms and display nodes to all proxy nodes")

        # Get all synchronized sequences for display node linking
        synchronizedSequenceNodes = vtk.vtkCollection()
        valveBrowserNode.GetSynchronizedSequenceNodes(synchronizedSequenceNodes, True)

        for seqNode, nodeEntries in sequenceToEntriesMap.items():
            proxyNode = valveBrowserNode.GetProxyNode(seqNode)
            if not proxyNode:
                continue

            # Reapply transforms if the proxy node is transformable
            if proxyNode.IsA("vtkMRMLTransformableNode"):
                # Find the original transform ID from the stored entries
                originalTransformID = None
                for entry in nodeEntries:
                    if 'originalTransformID' in entry and entry['originalTransformID']:
                        originalTransformID = entry['originalTransformID']
                        break

                if originalTransformID:
                    currentTransformID = proxyNode.GetTransformNodeID()
                    if currentTransformID != originalTransformID:
                        proxyNode.SetAndObserveTransformNodeID(originalTransformID)
                        logging.info(f"  Re-applied transform {originalTransformID} to proxy '{proxyNode.GetName()}' (was: {currentTransformID})")

            # Link display node sequences to data proxy nodes if the proxy node is displayable
            if proxyNode.IsA("vtkMRMLDisplayableNode"):
                # Use the direct mapping to find the corresponding display sequence
                # This avoids issues with name collisions when multiple valves have similar node names
                displaySequenceNode = dataSequenceToDisplaySequenceMap.get(seqNode)
                if displaySequenceNode:
                    displayProxyNode = valveBrowserNode.GetProxyNode(displaySequenceNode)
                    if displayProxyNode:
                        currentDisplayID = proxyNode.GetDisplayNodeID() if hasattr(proxyNode, 'GetDisplayNodeID') else None
                        if currentDisplayID != displayProxyNode.GetID():
                            proxyNode.SetAndObserveDisplayNodeID(displayProxyNode.GetID())
                            logging.info(f"  Linked display sequence '{displaySequenceNode.GetName()}' to proxy '{proxyNode.GetName()}'")
                    else:
                        logging.warning(f"  Could not get display proxy node for sequence '{displaySequenceNode.GetName()}'")
                else:
                    logging.debug(f"  No display sequence found for data sequence '{seqNode.GetName()}'")

        # Update the heart valve proxy node's references to point to the new proxy nodes
        logging.info("Updating heart valve proxy node references")
        heartValveProxyNode = valveBrowserNode.GetProxyNode(heartValveSequenceNode)
        if heartValveProxyNode:
            # Roles that use simple single references
            singleReferenceRoles = ["AnnulusContourPoints", "AnnulusLabelsPoints", "LeafletSegmentation",
                                   "ValveRoiModel", "LeafletVolume", "vtkMRMLSegmentationNode"]

            # Roles that use Nth references (indexed)
            nthReferenceRoles = ["PapillaryLineMarkup", "LeafletSurfaceBoundaryMarkup",
                                "CoaptationBaseLineMarkup", "CoaptationMarginLineMarkup",
                                "CoaptationBaseLineModel", "CoaptationMarginLineModel",
                                "LeafletSurfaceModel"]

            # Track which Nth reference indices we've set for each role
            nthReferenceIndices = {}  # role -> list of (index, proxyNode)

            # Map from role/baseName to the sequence node
            for (role, baseName), nodeEntries in referencedNodesByRole.items():
                if len(nodeEntries) == 0:
                    continue

                # Find the sequence we created for this group
                sequenceBaseName = baseName if baseName else nodeEntries[0]['node'].GetName()
                sequenceName = f"{sequenceBaseName}_Sequence"

                # Find the sequence node by name
                for i in range(synchronizedSequenceNodes.GetNumberOfItems()):
                    seqNode = synchronizedSequenceNodes.GetItemAsObject(i)
                    if seqNode and sequenceName in seqNode.GetName():
                        proxyNode = valveBrowserNode.GetProxyNode(seqNode)
                        if proxyNode:
                            # Check if this is a simple reference or Nth reference
                            if role in singleReferenceRoles:
                                # Simple single reference
                                heartValveProxyNode.SetNodeReferenceID(role, proxyNode.GetID())
                                logging.info(f"  Updated heart valve proxy reference '{role}' to proxy node '{proxyNode.GetName()}'")
                            elif role in nthReferenceRoles:
                                # Nth reference - need to track indices
                                if role not in nthReferenceIndices:
                                    nthReferenceIndices[role] = []
                                nthReferenceIndices[role].append(proxyNode)
                        break

            # Now set all the Nth references
            for role, proxyNodes in nthReferenceIndices.items():
                # First, clear existing references for this role
                numExisting = heartValveProxyNode.GetNumberOfNodeReferences(role)
                for i in range(numExisting):
                    heartValveProxyNode.RemoveNthNodeReferenceID(role, 0)

                # Add the new proxy node references
                for idx, proxyNode in enumerate(proxyNodes):
                    heartValveProxyNode.SetNthNodeReferenceID(role, idx, proxyNode.GetID())
                    logging.info(f"  Updated heart valve proxy Nth reference '{role}[{idx}]' to proxy node '{proxyNode.GetName()}'")

        # Collect all proxy nodes to avoid accidentally removing their display nodes
        proxyNodeIDs = set()
        proxyDisplayNodeIDs = set()
        for i in range(synchronizedSequenceNodes.GetNumberOfItems()):
            seqNode = synchronizedSequenceNodes.GetItemAsObject(i)
            if seqNode:
                proxyNode = valveBrowserNode.GetProxyNode(seqNode)
                if proxyNode:
                    proxyNodeIDs.add(proxyNode.GetID())
                    if proxyNode.IsA("vtkMRMLDisplayableNode"):
                        proxyDisplayNode = proxyNode.GetDisplayNode()
                        if proxyDisplayNode:
                            proxyDisplayNodeIDs.add(proxyDisplayNode.GetID())
                            logging.debug(f"Keeping proxy display node: {proxyDisplayNode.GetName()} for proxy {proxyNode.GetName()}")

        # Remove original referenced nodes that have been converted
        # First remove the data nodes themselves
        for node in nodesToRemove:
            if node and node.GetID() not in proxyNodeIDs:
                logging.info(f"Removing converted referenced node: {node.GetName()}")
                slicer.mrmlScene.RemoveNode(node)
            elif node:
                logging.debug(f"Skipping removal of {node.GetName()} - it's a proxy node")

        # Then remove all display nodes that were captured during discovery
        # (Remove display nodes after data nodes to avoid subject hierarchy warnings)
        logging.info(f"Removing {len(displayNodesToRemove)} display node(s)")
        for displayNode in displayNodesToRemove:
            if displayNode:
                # Don't remove proxy display nodes
                if displayNode.GetID() in proxyDisplayNodeIDs:
                    logging.debug(f"Skipping removal of proxy display node: {displayNode.GetName()}")
                    continue

                # Check if the display node still exists in the scene (might have been auto-removed with its data node)
                if slicer.mrmlScene.IsNodePresent(displayNode):
                    logging.info(f"Removing display node: {displayNode.GetName()} (ID: {displayNode.GetID()})")
                    slicer.mrmlScene.RemoveNode(displayNode)
                else:
                    logging.debug(f"Display node already removed: {displayNode.GetName()} (ID: {displayNode.GetID()})")

        # Enable display visibility for all display nodes in display sequences
        # This must be done AFTER all proxy node configuration and cleanup is complete
        # The display nodes stored in display sequences control visibility during playback
        logging.info("Enabling display visibility for all display nodes in sequences")
        synchronizedSequenceNodes = vtk.vtkCollection()
        valveBrowserNode.GetSynchronizedSequenceNodes(synchronizedSequenceNodes, True)

        displaySequenceCount = 0
        displayNodeCount = 0
        proxyCount = 0

        for i in range(synchronizedSequenceNodes.GetNumberOfItems()):
            seqNode = synchronizedSequenceNodes.GetItemAsObject(i)
            if not seqNode or seqNode.GetNumberOfDataNodes() == 0:
                continue

            seqName = seqNode.GetName()
            firstNode = seqNode.GetNthDataNode(0)

            # Enable visibility on display nodes in sequences
            if firstNode and firstNode.IsA("vtkMRMLDisplayNode"):
                logging.info(f"  Processing display sequence '{seqName}' with {seqNode.GetNumberOfDataNodes()} display nodes")
                for j in range(seqNode.GetNumberOfDataNodes()):
                    displayNode = seqNode.GetNthDataNode(j)
                    if displayNode:
                        wasVisible = displayNode.GetVisibility()
                        displayNode.SetVisibility(True)
                        nowVisible = displayNode.GetVisibility()
                        displayNodeCount += 1
                displaySequenceCount += 1

            # Enable visibility on proxy nodes
            elif "_Display_Sequence" not in seqName:
                proxyNode = valveBrowserNode.GetProxyNode(seqNode)
                if proxyNode and proxyNode.IsA("vtkMRMLDisplayableNode"):
                    proxyDisplayNode = proxyNode.GetDisplayNode()
                    if proxyDisplayNode:
                        wasVisible = proxyDisplayNode.GetVisibility()
                        proxyDisplayNode.SetVisibility(True)
                        nowVisible = proxyDisplayNode.GetVisibility()
                        logging.info(f"  Proxy '{proxyNode.GetName()}' display visibility: {wasVisible} -> {nowVisible}")
                        proxyCount += 1

        # Organize all converted nodes in subject hierarchy under the heart valve proxy node
        logging.info("Organizing converted nodes in subject hierarchy")
        heartValveProxyNode = valveBrowserNode.GetProxyNode(heartValveSequenceNode)
        if heartValveProxyNode:
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            if shNode:
                # Get or create the heart valve item in subject hierarchy
                valveItemID = shNode.GetItemByDataNode(heartValveProxyNode)
                if not valveItemID:
                    valveItemID = shNode.CreateItem(shNode.GetSceneItemID(), heartValveProxyNode)

                # Move all sequence nodes and their proxy nodes under the valve
                hierarchyCount = 0
                for i in range(synchronizedSequenceNodes.GetNumberOfItems()):
                    seqNode = synchronizedSequenceNodes.GetItemAsObject(i)
                    if not seqNode:
                        continue

                    # Skip the master sequence (it's the valve itself)
                    if seqNode.GetID() == heartValveSequenceNode.GetID():
                        continue

                    # Move sequence node under valve
                    seqItemID = shNode.GetItemByDataNode(seqNode)
                    if seqItemID:
                        shNode.SetItemParent(seqItemID, valveItemID)
                        hierarchyCount += 1

                    # Move proxy node under valve (if it's not a display node)
                    proxyNode = valveBrowserNode.GetProxyNode(seqNode)
                    if proxyNode and not proxyNode.IsA("vtkMRMLDisplayNode"):
                        proxyItemID = shNode.GetItemByDataNode(proxyNode)
                        if proxyItemID:
                            shNode.SetItemParent(proxyItemID, valveItemID)
                            hierarchyCount += 1

                logging.info(f"Organized {hierarchyCount} item(s) under heart valve '{heartValveProxyNode.GetName()}' in subject hierarchy")

        logging.info("Finished converting referenced nodes to sequences")

    def _getValveNodeIdForMeasurement(self, measurementNode):
        """
        Helper to find the valve node ID referenced by a measurement node.

        Args:
            measurementNode: The measurement node to search

        Returns:
            str: The valve node ID, or None if not found
        """
        # Try standard role names first
        for role in ["Valve", "HeartValve", "ValveNode"]:
            valveNodeId = measurementNode.GetNodeReferenceID(role)
            if valveNodeId:
                return valveNodeId

        # Check all roles for a HeartValve node
        numRoles = measurementNode.GetNumberOfNodeReferenceRoles()
        for roleIndex in range(numRoles):
            role = measurementNode.GetNthNodeReferenceRole(roleIndex)
            refNode = measurementNode.GetNthNodeReference(role, 0)
            if refNode and refNode.GetAttribute("ModuleName") == "HeartValve":
                return refNode.GetID()

        return None

    def _findValveBrowserForValveNode(self, valveNode):
        """
        Find the sequence browser containing a valve node.

        Args:
            valveNode: The valve node to find the browser for

        Returns:
            The browser node, or None if not found
        """
        # Try direct lookup first
        browser = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(valveNode)
        if browser:
            return browser

        # Search through all browsers
        valveId = valveNode.GetID()
        valveType = valveNode.GetAttribute("ValveType")

        for browser in slicer.util.getNodesByClass('vtkMRMLSequenceBrowserNode'):
            # Check if browser name matches valve type
            if valveType and valveType in browser.GetName():
                masterSeq = browser.GetMasterSequenceNode()
                if masterSeq:
                    for i in range(masterSeq.GetNumberOfDataNodes()):
                        if masterSeq.GetNthDataNode(i) and masterSeq.GetNthDataNode(i).GetID() == valveId:
                            return browser

        return None

    def convertHeartValveMeasurementNodesToSequences(self):
        """
        Convert HeartValveMeasurement nodes to sequences.

        HeartValveMeasurement nodes store analysis results like A-P distance, annulus area, etc.
        In the old format, these were single nodes. In the new format, they should be in sequences.
        """
        logging.info("Converting HeartValveMeasurement nodes to sequences")

        # Get all HeartValveMeasurement nodes
        allMeasurementNodes = list(getAllModuleSpecificScriptableNodes("HeartValveMeasurement"))

        logging.info(f"Found {len(allMeasurementNodes)} total HeartValveMeasurement node(s)")

        if not allMeasurementNodes:
            logging.info("No HeartValveMeasurement nodes found to convert")
            return 0

        # Filter to only old-format nodes (not already in a sequence)
        oldFormatMeasurementNodes = []
        measurementNodeValveInfo = {}

        for measurementNode in allMeasurementNodes:
            try:
                # Check if already in a sequence browser
                browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(measurementNode)
                if browserNode:
                    logging.info(f"Skipping '{measurementNode.GetName()}' - already in sequence")
                    continue

                # Find referenced valve
                valveNodeId = self._getValveNodeIdForMeasurement(measurementNode)
                if not valveNodeId:
                    # List all references for debugging
                    allRoles = []
                    numRoles = measurementNode.GetNumberOfNodeReferenceRoles()
                    for roleIndex in range(numRoles):
                        role = measurementNode.GetNthNodeReferenceRole(roleIndex)
                        numRefs = measurementNode.GetNumberOfNodeReferences(role)
                        if numRefs > 0:
                            allRoles.append(f"{role}({numRefs})")
                    logging.warning(f"Measurement '{measurementNode.GetName()}' has no Valve reference, skipping. Available references: {', '.join(allRoles) if allRoles else 'none'}")
                    continue

                logging.info(f"Measurement '{measurementNode.GetName()}' needs conversion (references valve ID: {valveNodeId})")
                oldFormatMeasurementNodes.append(measurementNode)
                measurementNodeValveInfo[measurementNode.GetID()] = valveNodeId
            except Exception as err:
                logging.warning(f"Error checking measurement node '{measurementNode.GetName()}': {err}")

        if not oldFormatMeasurementNodes:
            logging.info("No old-format HeartValveMeasurement nodes found to convert")
            return 0

        logging.info(f"Converting {len(oldFormatMeasurementNodes)} HeartValveMeasurement node(s)")

        # Group measurement nodes by the valve they reference
        measurementsByValve = {}
        for measurementNode in oldFormatMeasurementNodes:
            try:
                measurementId = measurementNode.GetID()
                if measurementId not in measurementNodeValveInfo:
                    logging.warning(f"Measurement '{measurementNode.GetName()}' missing valve info, skipping")
                    continue

                valveNodeId = measurementNodeValveInfo[measurementId]
                if valveNodeId not in measurementsByValve:
                    measurementsByValve[valveNodeId] = []
                measurementsByValve[valveNodeId].append(measurementNode)
            except Exception as err:
                logging.warning(f"Error grouping measurement '{measurementNode.GetName()}': {err}")

        # Process each group of measurements based on their common valve
        convertedCount = 0
        nodesToRemove = []

        for valveNodeId, measurementNodes in measurementsByValve.items():
            try:
                valveNode = slicer.mrmlScene.GetNodeByID(valveNodeId)
                if not valveNode:
                    logging.warning(f"Invalid valve ID '{valveNodeId}' for a group of measurements, skipping")
                    continue

                # Find the valve's sequence browser
                valveBrowserNode = self._findValveBrowserForValveNode(valveNode)
                if not valveBrowserNode:
                    logging.warning(f"Could not find sequence browser for valve '{valveNode.GetName()}', skipping {len(measurementNodes)} measurement(s).")
                    continue

                logging.info(f"Converting {len(measurementNodes)} measurement(s) for valve browser: {valveBrowserNode.GetName()}")

                # Group measurements by name to create one sequence per type
                measurementsByName = {}
                for mnode in measurementNodes:
                    mname = mnode.GetName()
                    if mname not in measurementsByName:
                        measurementsByName[mname] = []
                    measurementsByName[mname].append(mnode)

                for measurementName, nodes in measurementsByName.items():
                    if not nodes:
                        continue

                    # Create a sequence for this measurement type
                    masterSequenceNode = valveBrowserNode.GetMasterSequenceNode()
                    measurementSequenceNode = self._createSequenceForNode(
                        valveBrowserNode,
                        f"{measurementName}_Sequence",
                        masterSequenceNode.GetIndexName(),
                        masterSequenceNode.GetIndexUnit(),
                        masterSequenceNode.GetIndexType()
                    )

                    # Add each node to the sequence at the correct timepoint
                    for measurementNode in nodes:
                        try:
                            valveIdForMeasurement = measurementNodeValveInfo[measurementNode.GetID()]

                            # Find the timepoint where this valve exists
                            foundTimepoint = False
                            for timeIdx in range(masterSequenceNode.GetNumberOfDataNodes()):
                                valveNodeAtTime = masterSequenceNode.GetNthDataNode(timeIdx)
                                if valveNodeAtTime and valveNodeAtTime.GetID() == valveIdForMeasurement:
                                    indexValue = masterSequenceNode.GetNthIndexValue(timeIdx)
                                    measurementSequenceNode.SetDataNodeAtValue(measurementNode, indexValue)
                                    logging.debug(f"Added '{measurementName}' to sequence at timepoint {timeIdx}")
                                    foundTimepoint = True
                                    break

                            if not foundTimepoint:
                                logging.warning(f"Could not find matching valve for '{measurementName}' in sequence")
                                continue

                            convertedCount += 1
                            nodesToRemove.append(measurementNode)
                            self._convertMeasurementTableNodes(measurementNode, valveBrowserNode, masterSequenceNode)
                        except Exception as err:
                            logging.warning(f"Error converting measurement '{measurementNode.GetName()}': {err}")

                    if measurementSequenceNode.GetNumberOfDataNodes() > 0:
                        logging.info(f"Created sequence '{measurementSequenceNode.GetName()}' with {measurementSequenceNode.GetNumberOfDataNodes()} node(s)")

            except Exception as err:
                logging.warning(f"Error processing measurement group for valve ID '{valveNodeId}': {err}")

        # Update proxy nodes for all affected browsers
        for valveId in measurementsByValve.keys():
            valveNode = slicer.mrmlScene.GetNodeByID(valveId)
            if valveNode:
                browser = self._findValveBrowserForValveNode(valveNode)
                if browser:
                    slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browser)

        # Remove original measurement nodes
        for node in nodesToRemove:
            if node:
                logging.info(f"Removing converted measurement node: {node.GetName()}")
                slicer.mrmlScene.RemoveNode(node)

        logging.info(f"Converted {convertedCount} HeartValveMeasurement node(s)")
        return convertedCount

    def _convertMeasurementTableNodes(self, measurementNode, valveBrowserNode, masterSequenceNode):
        """
        Convert table nodes referenced by a HeartValveMeasurement node to sequences.

        These tables contain the actual measurement values (A-P distance, annulus area, etc.)
        Tables are added sparsely - only at the timepoint where the measurement itself exists.

        Args:
            measurementNode: The measurement node containing table references
            valveBrowserNode: The sequence browser node to add table sequences to
            masterSequenceNode: The master sequence node for timepoint information
        """
        try:
            # Find the timepoint of the measurement node itself to ensure the table is added sparsely
            valveNodeId = self._getValveNodeIdForMeasurement(measurementNode)
            if not valveNodeId:
                logging.warning(f"Could not find valve reference for measurement '{measurementNode.GetName()}', skipping table conversion.")
                return

            measurementTimepoint = -1
            measurementIndexValue = ""
            for timeIdx in range(masterSequenceNode.GetNumberOfDataNodes()):
                valveNodeAtTime = masterSequenceNode.GetNthDataNode(timeIdx)
                if valveNodeAtTime and valveNodeAtTime.GetID() == valveNodeId:
                    measurementTimepoint = timeIdx
                    measurementIndexValue = masterSequenceNode.GetNthIndexValue(timeIdx)
                    break

            if measurementTimepoint == -1:
                logging.warning(f"Could not find timepoint for measurement '{measurementNode.GetName()}', skipping table conversion.")
                return

            # Get all table node references from the measurement node
            nodesToRemove = set()
            numRoles = measurementNode.GetNumberOfNodeReferenceRoles()
            for roleIndex in range(numRoles):
                role = measurementNode.GetNthNodeReferenceRole(roleIndex)
                numRefs = measurementNode.GetNumberOfNodeReferences(role)

                for refIndex in range(numRefs):
                    tableNode = measurementNode.GetNthNodeReference(role, refIndex)
                    if not tableNode or not tableNode.IsA('vtkMRMLTableNode'):
                        continue

                    # Skip if already in a sequence
                    if slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(tableNode):
                        continue

                    # Create a sequence for this table
                    tableSequenceNode = self._createSequenceForNode(
                        valveBrowserNode,
                        f"{tableNode.GetName()}_Sequence",
                        masterSequenceNode.GetIndexName(),
                        masterSequenceNode.GetIndexUnit(),
                        masterSequenceNode.GetIndexType()
                    )

                    # Add the table ONLY at the specific timepoint for this measurement (sparse)
                    tableSequenceNode.SetDataNodeAtValue(tableNode, measurementIndexValue)
                    nodesToRemove.add(tableNode)

                    logging.debug(f"Converted measurement table '{tableNode.GetName()}' to sparse sequence at timepoint {measurementTimepoint}")

            # Remove original table nodes
            for node in nodesToRemove:
                if node:
                    logging.info(f"Removing converted measurement table node: {node.GetName()}")
                    slicer.mrmlScene.RemoveNode(node)
        except Exception as err:
            logging.warning(f"Error converting measurement table nodes: {err}")

    def convertCardiacDeviceNodesToSequences(self):
        """
        Convert CardiacDeviceAnalysis nodes to sequences.

        CardiacDeviceAnalysis nodes are used for cardiac device simulations and planning.
        Similar to HeartValve nodes, they should be converted to sequences in the new format.
        """
        logging.info("Converting CardiacDeviceAnalysis nodes to sequences")

        # Get all CardiacDeviceAnalysis nodes
        allDeviceNodes = list(getAllModuleSpecificScriptableNodes("CardiacDeviceAnalysis"))

        if not allDeviceNodes:
            logging.info("No CardiacDeviceAnalysis nodes found to convert")
            return 0

        # Filter to only old-format nodes (not already in a sequence)
        oldFormatDeviceNodes = []
        for deviceNode in allDeviceNodes:
            try:
                # Check if already in a sequence browser
                browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(deviceNode)
                if browserNode:
                    logging.debug(f"Skipping '{deviceNode.GetName()}' - already in sequence")
                    continue

                oldFormatDeviceNodes.append(deviceNode)
            except Exception as err:
                logging.warning(f"Error checking device node '{deviceNode.GetName()}': {err}")

        if not oldFormatDeviceNodes:
            logging.info("No old-format CardiacDeviceAnalysis nodes found to convert")
            return 0

        logging.info(f"Converting {len(oldFormatDeviceNodes)} CardiacDeviceAnalysis node(s)")

        # For device nodes, we'll create a dedicated browser if they reference a volume sequence
        # Otherwise, we'll create a standalone sequence
        devicesByVolumeBrowser = {}
        standaloneDevices = []

        for deviceNode in oldFormatDeviceNodes:
            try:
                # Try to find a volume reference
                volumeNode = None
                numRoles = deviceNode.GetNumberOfNodeReferenceRoles()
                for roleIndex in range(numRoles):
                    role = deviceNode.GetNthNodeReferenceRole(roleIndex)
                    if 'volume' in role.lower():
                        volumeNode = deviceNode.GetNthNodeReference(role, 0)
                        if volumeNode:
                            break

                if volumeNode:
                    # Try to find the volume's sequence browser
                    volumeBrowserNode = getSequenceBrowserNodeForMasterOutputNode(volumeNode)
                    if volumeBrowserNode:
                        browserNodeId = volumeBrowserNode.GetID()
                        if browserNodeId not in devicesByVolumeBrowser:
                            devicesByVolumeBrowser[browserNodeId] = {
                                'volumeBrowserNode': volumeBrowserNode,
                                'deviceNodes': []
                            }
                        devicesByVolumeBrowser[browserNodeId]['deviceNodes'].append(deviceNode)
                        continue

                # If we get here, this is a standalone device
                standaloneDevices.append(deviceNode)
            except Exception as err:
                logging.warning(f"Error processing device '{deviceNode.GetName()}': {err}")
                standaloneDevices.append(deviceNode)

        convertedCount = 0
        nodesToRemove = []

        # Process devices grouped by volume browser
        for browserNodeId, browserData in devicesByVolumeBrowser.items():
            volumeBrowserNode = browserData['volumeBrowserNode']
            deviceNodes = browserData['deviceNodes']

            logging.info(f"Converting {len(deviceNodes)} device(s) for volume browser: {volumeBrowserNode.GetName()}")

            # Determine a meaningful name based on the first device
            deviceTypeName = "CardiacDevice"
            if deviceNodes:
                # Try to use the first device's name as a hint
                firstDeviceName = deviceNodes[0].GetName()
                # Extract a meaningful prefix (e.g., "ASD" from "ASD_Device_1")
                if firstDeviceName:
                    # Take the first part before underscore or use the whole name
                    parts = firstDeviceName.split('_')
                    if parts:
                        deviceTypeName = parts[0] if parts[0] else "CardiacDevice"

            # Create a device browser node
            deviceBrowserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode")
            browserName = f"{deviceTypeName}Browser"
            deviceBrowserNode.SetName(slicer.mrmlScene.GetUniqueNameByString(browserName))
            deviceBrowserNode.SetAttribute("ModuleName", "CardiacDeviceAnalysis")

            # Create a sequence for the devices
            volumeSequenceNode = volumeBrowserNode.GetMasterSequenceNode()
            deviceSequenceNode = self._createSequenceForNode(
                deviceBrowserNode,
                f"{deviceTypeName}Sequence",
                volumeSequenceNode.GetIndexName(),
                volumeSequenceNode.GetIndexUnit(),
                volumeSequenceNode.GetIndexType()
            )

            # Add devices to sequence at first timepoint
            for deviceNode in deviceNodes:
                try:
                    indexValue = volumeSequenceNode.GetNthIndexValue(0)
                    deviceSequenceNode.SetDataNodeAtValue(deviceNode, indexValue)
                    logging.info(f"Added {deviceNode.GetName()} to device sequence")
                    convertedCount += 1
                    nodesToRemove.append(deviceNode)
                except Exception as err:
                    logging.warning(f"Error adding device '{deviceNode.GetName()}' to sequence: {err}")

            # Set up the browser
            if deviceSequenceNode.GetNumberOfDataNodes() > 0:
                deviceBrowserNode.SetAndObserveMasterSequenceNodeID(deviceSequenceNode.GetID())
                deviceBrowserNode.SetSaveChanges(deviceSequenceNode, True)
                deviceBrowserNode.SetSelectedItemNumber(0)
                slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(deviceBrowserNode)
                logging.info(f"Created device browser with {deviceSequenceNode.GetNumberOfDataNodes()} device(s)")

        # Process standalone devices
        if standaloneDevices:
            logging.info(f"Converting {len(standaloneDevices)} standalone device(s)")

            # Determine a meaningful name based on the first device
            deviceTypeName = "CardiacDevice"
            if standaloneDevices:
                firstDeviceName = standaloneDevices[0].GetName()
                if firstDeviceName:
                    parts = firstDeviceName.split('_')
                    if parts:
                        deviceTypeName = parts[0] if parts[0] else "CardiacDevice"

            deviceBrowserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode")
            browserName = f"{deviceTypeName}Browser"
            deviceBrowserNode.SetName(slicer.mrmlScene.GetUniqueNameByString(browserName))
            deviceBrowserNode.SetAttribute("ModuleName", "CardiacDeviceAnalysis")

            deviceSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode")
            sequenceName = f"{deviceTypeName}Sequence"
            deviceSequenceNode.SetName(slicer.mrmlScene.GetUniqueNameByString(sequenceName))
            deviceSequenceNode.SetIndexName("time")
            deviceSequenceNode.SetIndexUnit("frame")

            for idx, deviceNode in enumerate(standaloneDevices):
                try:
                    deviceSequenceNode.SetDataNodeAtValue(deviceNode, str(idx))
                    logging.info(f"Added {deviceNode.GetName()} to standalone device sequence")
                    convertedCount += 1
                    nodesToRemove.append(deviceNode)
                except Exception as err:
                    logging.warning(f"Error adding device '{deviceNode.GetName()}' to sequence: {err}")

            if deviceSequenceNode.GetNumberOfDataNodes() > 0:
                deviceBrowserNode.SetAndObserveMasterSequenceNodeID(deviceSequenceNode.GetID())
                deviceBrowserNode.SetSaveChanges(deviceSequenceNode, True)
                deviceBrowserNode.SetSelectedItemNumber(0)
                slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(deviceBrowserNode)

        # Remove original device nodes
        for node in nodesToRemove:
            if node:
                logging.info(f"Removing converted device node: {node.GetName()}")
                slicer.mrmlScene.RemoveNode(node)

        logging.info(f"Converted {convertedCount} CardiacDeviceAnalysis node(s)")
        return convertedCount
