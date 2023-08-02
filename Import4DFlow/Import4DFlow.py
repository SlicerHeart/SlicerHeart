# Run this script after loading Siemens cardiac 4D flow study.
#
# Note: Do not have any additional images in the scene when running this script.
#
# For example: "MR HEART W & W O IV CONTRAST" study, with 4 series:
# (3 series contain the 3 speed components and the 4th series is the magnitude image)
# - 112: CS4Dflow_R7.7_retro_post 1.6 x 1.6_P
# - 113: CS4Dflow_R7.7_retro_post 1.6 x 1.6_P
# - 114: CS4Dflow_R7.7_retro_post 1.6 x 1.6_P
# - 115: CS4Dflow_R7.7_retro_post 1.6 x 1.6
#

sortedvolumeNodeForDirection = {}
volumeNodes = [None, None, None, None]  # x, y, z, magnitude
unsortedVolumeNodes = slicer.util.getNodesByClass('vtkMRMLScalarVolumeNode')
axisForDirectionCode = {
                           #      orig z seems better
    'v150_through': 0,     # Z axis 2   0                 1
    'v150_inplane_ap': 1,  # X axis 0   1                 0
    'v150_inplane_fh': 2,  # Y axis 1   2                 2
    'magnitude': 3,
}

directions = [-1, -1, 1]

for volumeNode in unsortedVolumeNodes:
    instUids = volumeNode.GetAttribute("DICOM.instanceUIDs").split()
    filename = slicer.dicomDatabase.fileForInstance(instUids[0])
    import pydicom
    ds = pydicom.read_file(filename)
    try:
        directionCode = ds[0x0051,0x1014].value.decode().strip()
    except KeyError:
        # Not Siemens 4D flow, assume it is the magnitude image
        volumeNodes[axisForDirectionCode['magnitude']] = volumeNode
        continue
    volumeNodes[axisForDirectionCode[directionCode]] = volumeNode


volumeSequenceBrowserNodes = []
volumeSequenceNodes = []
for axis in range(len(volumeNodes)):
    volumeSequenceProxyNode = volumeNodes[axis]
    volumeSequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(volumeSequenceProxyNode)
    if not volumeSequenceBrowserNode:
        raise RuntimeError(f"Volume {volumeSequenceProxyNode.GetName()} is expected to be proxy node of a volume sequence")
    volumeSequenceNode = volumeSequenceBrowserNode.GetSequenceNode(volumeSequenceProxyNode)
    volumeSequenceBrowserNodes.append(volumeSequenceBrowserNode)
    volumeSequenceNodes.append(volumeSequenceNode)

import numpy as np
numberOfFrames = volumeSequenceNodes[0].GetNumberOfDataNodes()

volumeSequenceProxyNode = volumeNodes[0]
dims = slicer.util.arrayFromVolume(volumeSequenceProxyNode).shape

displacementImage = vtk.vtkImageData()
displacementImage.SetDimensions(dims[2], dims[1], dims[0])
displacementImage.AllocateScalars(vtk.VTK_FLOAT, 3)

gridTransform = slicer.vtkOrientedGridTransform()
directionMatrix = vtk.vtkMatrix4x4()
volumeSequenceProxyNode.GetIJKToRASDirectionMatrix(directionMatrix)
gridTransform.SetGridDirectionMatrix(directionMatrix)
displacementImage.SetSpacing(volumeSequenceProxyNode.GetSpacing())
displacementImage.SetOrigin(volumeSequenceProxyNode.GetOrigin())
gridTransform.SetDisplacementGridData(displacementImage)

try:
    if not gridTransformNode:
        raise ValueError()
except:
    gridTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode")
gridTransformNode.SetAndObserveTransformFromParent(gridTransform)

displacementArray = slicer.util.arrayFromGridTransform(gridTransformNode)  # shape: (96, 160, 64, 3) = (i, j, k, c)

magnitudeVolumeSequenceNode = volumeSequenceNodes[axisForDirectionCode['magnitude']]

try:
    transformSequenceNode
except:
    transformSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "4D flow")

transformSequenceNode.SetIndexType(magnitudeVolumeSequenceNode.GetIndexType())
transformSequenceNode.SetIndexName(magnitudeVolumeSequenceNode.GetIndexName())
transformSequenceNode.SetIndexUnit(magnitudeVolumeSequenceNode.GetIndexUnit())

# Just an empirical value, to create few-mm displacements, that can be visualized nicely
scale = 1 / 4096 * 10

for volumeIndex in range(numberOfFrames):
    # volumeIndex = 7
    magnitudeVoxelArray = slicer.util.arrayFromVolume(magnitudeVolumeSequenceNode.GetNthDataNode(volumeIndex)).copy()
    for axis in range(3):
        volumeSequenceNode = volumeSequenceNodes[axis]
        voxelArray = slicer.util.arrayFromVolume(volumeSequenceNode.GetNthDataNode(volumeIndex)).copy() * scale * directions[axis]
        #voxelArray = np.ones(voxelArrayX.shape) * 10
        voxelArray[abs(magnitudeVoxelArray) < 100] = 0
        displacementArray[:, :, :, axis] = voxelArray
    slicer.util.arrayFromGridTransformModified(gridTransformNode)
    indexValue = magnitudeVolumeSequenceNode.GetNthIndexValue(volumeIndex)
    # The transform stores "transform from parent", but visualization displays "transform to parent".
    # (We could not set transform to parent directly because arrayFromGridTransformModified
    # only works with "transform from parent"). Invert the field now to display "transform to parent".
    # This also greatly speeds up the display.
    gridTransformNode.Inverse()
    transformSequenceNode.SetDataNodeAtValue(gridTransformNode, indexValue)
    # Revert to "transform from parent"
    gridTransformNode.Inverse()

# Create a sequence browser node for the new merged sequence
transformSequenceBrowserNode = volumeSequenceBrowserNodes[axisForDirectionCode['magnitude']]
transformSequenceBrowserNode.AddSynchronizedSequenceNode(transformSequenceNode)
slicer.modules.sequences.toolBar().setActiveBrowserNode(transformSequenceBrowserNode)

slicer.mrmlScene.RemoveNode(gridTransformNode)
del gridTransformNode

slicer.modules.sequences.logic().UpdateAllProxyNodes()
gridTransformNode = transformSequenceBrowserNode.GetProxyNode(transformSequenceNode)

magnitudeVolumeNode = volumeNodes[axisForDirectionCode['magnitude']]

# Place transform in the same subject hierarchy folder as the volume node
shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
volumeParentItemId = shNode.GetItemParent(shNode.GetItemByDataNode(magnitudeVolumeNode))
shNode.SetItemParent(shNode.GetItemByDataNode(gridTransformNode), volumeParentItemId)

try:
    transformDisplayNode
except:
    transformDisplayNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformDisplayNode")
gridTransformNode.AddAndObserveDisplayNodeID(transformDisplayNode.GetID())
transformDisplayNode.SetVisibility(True)
transformDisplayNode.SetVisibility2D(True)
transformDisplayNode.SetVisibility3D(False)  # with small glyph spacing, updating of the glyphs in 3D can be slow
transformDisplayNode.SetGlyphDisplayRangeMinMm(scale * 400)
transformDisplayNode.SetGlyphSpacingMm(2.0)
transformDisplayNode.SetGlyphDiameterMm(0.8)
transformDisplayNode.SetAndObserveRegionNode(magnitudeVolumeNode)

# Delete imported component image series from the scene
for axisIndex in range(3):
    slicer.mrmlScene.RemoveNode(volumeSequenceNodes[axisIndex])
    slicer.mrmlScene.RemoveNode(volumeNodes[axisIndex].GetDisplayNode())
    slicer.mrmlScene.RemoveNode(volumeNodes[axisIndex].GetStorageNode())
    slicer.mrmlScene.RemoveNode(volumeNodes[axisIndex])
    slicer.mrmlScene.RemoveNode(volumeSequenceBrowserNodes[axisIndex])
