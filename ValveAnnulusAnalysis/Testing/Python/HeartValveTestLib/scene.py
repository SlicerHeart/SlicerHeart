"""
Scene-level helpers: synthetic volume sequences, node census, save/reload, sample data.
"""

import os

import numpy as np
import vtk
from vtk.util import numpy_support
import slicer


# -------------------------------------------------------------------------------------------------
# Synthetic volume sequence
# -------------------------------------------------------------------------------------------------

def defaultIndexValues(numFrames, frameTimeSec=0.042):
  """Index values in the style of a real ultrasound sequence (seconds, as strings).

  Deliberately *not* "0", "1", ... so that code confusing item numbers with index values fails.
  """
  return ["%.3f" % (k * frameTimeSec) for k in range(numFrames)]


def createVolumeNode(name, dims=(16, 16, 8), voxelValue=1, spacing=(0.5, 0.5, 1.0), origin=None,
                     addToScene=True):
  """Create a small scalar volume filled with *voxelValue* and a non-identity IJK->RAS direction matrix.

  By default the volume is centred on the origin of its parent coordinate system (so annotations
  placed around (0, 0, 0) in Probe coordinates fall inside the volume).
  """
  if origin is None:
    # directions are (-1, -1, 1): x and y decrease with i and j
    origin = ((dims[0] - 1) * spacing[0] / 2.0, (dims[1] - 1) * spacing[1] / 2.0, -(dims[2] - 1) * spacing[2] / 2.0)
  imageData = vtk.vtkImageData()
  imageData.SetDimensions(*dims)
  imageData.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
  array = numpy_support.vtk_to_numpy(imageData.GetPointData().GetScalars())
  array[:] = voxelValue
  volumeNode = slicer.vtkMRMLScalarVolumeNode()
  volumeNode.SetName(name)
  volumeNode.SetAndObserveImageData(imageData)
  volumeNode.SetSpacing(*spacing)
  volumeNode.SetOrigin(*origin)
  # LPS-like axis flip so that IJK->RAS is not the identity (catches coordinate-system mix-ups)
  volumeNode.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, 1)
  if addToScene:
    slicer.mrmlScene.AddNode(volumeNode)
    volumeNode.CreateDefaultDisplayNodes()
  return volumeNode


def createSyntheticVolumeSequence(numFrames=6, dims=(16, 16, 8), indexValues=None, name="SyntheticUS"):
  """Create a volume sequence + browser + proxy the way a loaded 4D ultrasound looks.

  Frame ``k`` is a constant volume with voxel value ``k + 1`` so tests can tell frames apart.

  :returns: ``(browserNode, sequenceNode, proxyVolumeNode)``
  """
  if indexValues is None:
    indexValues = defaultIndexValues(numFrames)
  sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
  sequenceNode.SetIndexName("time")
  sequenceNode.SetIndexUnit("s")
  sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.NumericIndex)
  for k, indexValue in enumerate(indexValues):
    volumeNode = createVolumeNode(f"{name}_frame{k}", dims=dims, voxelValue=k + 1, addToScene=False)
    sequenceNode.SetDataNodeAtValue(volumeNode, indexValue)

  browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", f"{name}Browser")
  slicer.modules.sequences.logic().AddSynchronizedNode(sequenceNode, None, browserNode)
  browserNode.SetSelectedItemNumber(0)
  slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
  proxyVolumeNode = browserNode.GetProxyNode(sequenceNode)
  proxyVolumeNode.SetName(name)
  return browserNode, sequenceNode, proxyVolumeNode


def volumeVoxelValue(volumeNode):
  """:returns: the (constant) voxel value of a synthetic volume, or None if it has no image."""
  imageData = volumeNode.GetImageData() if volumeNode else None
  if not imageData or imageData.GetNumberOfPoints() == 0:
    return None
  array = slicer.util.arrayFromVolume(volumeNode)
  return int(array.flat[0])


def selectVolumeFrame(volumeBrowserNode, frameIndex):
  volumeBrowserNode.SetSelectedItemNumber(frameIndex)
  slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(volumeBrowserNode)


def selectBrowserItem(browserNode, itemIndex):
  browserNode.SetSelectedItemNumber(itemIndex)
  slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)


def selectIndexValue(browserNode, indexValue):
  """Select the item of the browser's master sequence with the given index value."""
  itemIndex = browserNode.GetMasterSequenceNode().GetItemNumberFromIndexValue(indexValue)
  if itemIndex < 0:
    raise ValueError(f"index value {indexValue!r} not in {browserNode.GetName()}")
  selectBrowserItem(browserNode, itemIndex)


# -------------------------------------------------------------------------------------------------
# Geometry helpers for synthetic annotations
# -------------------------------------------------------------------------------------------------

def ellipsePoints(numPoints=12, radiusX=10.0, radiusY=8.0, center=(0.0, 0.0, 0.0), tilt=0.0, phaseOffset=0.0):
  """Closed-curve control points on a (slightly tilted) ellipse; *phaseOffset* scales the radii so
  that different time points get distinguishable contours."""
  scale = 1.0 + phaseOffset
  points = []
  for i in range(numPoints):
    angle = 2.0 * np.pi * i / numPoints
    x = center[0] + radiusX * scale * np.cos(angle)
    y = center[1] + radiusY * scale * np.sin(angle)
    z = center[2] + tilt * np.sin(angle)
    points.append([float(x), float(y), float(z)])
  return points


def landmarkLabels(contourPoints, labels=("A", "L", "P", "S")):
  """Quadrant landmarks sampled from a contour, as ``(label, r, a, s)`` tuples."""
  step = len(contourPoints) // len(labels)
  return [(label, *contourPoints[i * step]) for i, label in enumerate(labels)]


def rotationMatrixZ(angleDeg, translation=(0.0, 0.0, 0.0)):
  transform = vtk.vtkTransform()
  transform.Translate(*translation)
  transform.RotateZ(angleDeg)
  matrix = vtk.vtkMatrix4x4()
  matrix.DeepCopy(transform.GetMatrix())
  return matrix


def sphereSource(center, radius=3.0):
  sphere = vtk.vtkSphereSource()
  sphere.SetCenter(*center)
  sphere.SetRadius(radius)
  sphere.SetThetaResolution(12)
  sphere.SetPhiResolution(12)
  sphere.Update()
  return sphere.GetOutput()


def addSphereSegment(segmentationNode, segmentId, name, center, radius=3.0, color=(1.0, 0.0, 0.0)):
  segmentation = segmentationNode.GetSegmentation()
  segmentationNode.AddSegmentFromClosedSurfaceRepresentation(sphereSource(center, radius), name, color, segmentId)
  segment = segmentation.GetSegment(segmentId)
  return segment


# -------------------------------------------------------------------------------------------------
# Scene inspection
# -------------------------------------------------------------------------------------------------

def allNodes():
  nodes = slicer.mrmlScene.GetNodes()
  return [nodes.GetItemAsObject(i) for i in range(nodes.GetNumberOfItems())]


def nodeCensus():
  """:returns: dict className -> number of nodes in the scene."""
  census = {}
  for node in allNodes():
    census[node.GetClassName()] = census.get(node.GetClassName(), 0) + 1
  return census


def nodeIds():
  return {node.GetID() for node in allNodes()}


def nodesByClass(className):
  return list(slicer.util.getNodesByClass(className))


def nodesWithAttribute(className, attributeName, attributeValue):
  return [n for n in slicer.util.getNodesByClass(className) if n.GetAttribute(attributeName) == attributeValue]


def valveBrowserNodes():
  return nodesWithAttribute("vtkMRMLSequenceBrowserNode", "ModuleName", "HeartValve")


def heartValveNodes():
  return nodesWithAttribute("vtkMRMLScriptedModuleNode", "ModuleName", "HeartValve")


def measurementNodes():
  return nodesWithAttribute("vtkMRMLScriptedModuleNode", "ModuleName", "HeartValveMeasurement")


def referenceSnapshot(node):
  """All node references of *node* as ``{role: [ids]}`` (order preserved)."""
  roles = []
  node.GetNodeReferenceRoles(roles)
  snapshot = {}
  for role in roles:
    snapshot[role] = [node.GetNthNodeReferenceID(role, k) for k in range(node.GetNumberOfNodeReferences(role))]
  return snapshot


def sceneReferenceSnapshot():
  """``{nodeId: {role: [ids]}}`` for every node in the scene."""
  return {node.GetID(): referenceSnapshot(node) for node in allNodes()}


class ModifiedEventCounter:
  """Counts ``ModifiedEvent`` on a node; use as a context manager or call ``remove()``."""

  def __init__(self, node, event=vtk.vtkCommand.ModifiedEvent):
    self.node = node
    self.count = 0
    self.tag = node.AddObserver(event, self._onEvent)

  def _onEvent(self, caller, event):
    self.count += 1

  def remove(self):
    if self.tag is not None:
      self.node.RemoveObserver(self.tag)
      self.tag = None

  def __enter__(self):
    return self

  def __exit__(self, *args):
    self.remove()


# -------------------------------------------------------------------------------------------------
# Persistence
# -------------------------------------------------------------------------------------------------

def saveAndReloadScene(tempDir, resetCaches=None):
  """Save the scene to an MRB in *tempDir*, clear, and load it back.

  :param resetCaches: optional callable invoked after clearing (e.g. SlicerHeartTestCase.resetHeartValveLibCaches)
  :returns: path of the MRB
  """
  mrbPath = os.path.join(tempDir, "scene.mrb")
  if not slicer.util.saveScene(mrbPath):
    raise RuntimeError(f"saveScene failed: {mrbPath}")
  slicer.mrmlScene.Clear(0)
  if resetCaches:
    resetCaches()
  if not slicer.util.loadScene(mrbPath):
    raise RuntimeError(f"loadScene failed: {mrbPath}")
  return mrbPath


def saveSceneToMrb(tempDir, name="scene.mrb"):
  mrbPath = os.path.join(tempDir, name)
  if not slicer.util.saveScene(mrbPath):
    raise RuntimeError(f"saveScene failed: {mrbPath}")
  return mrbPath


# -------------------------------------------------------------------------------------------------
# Sample data (used by the two "real data" smoke tests only)
# -------------------------------------------------------------------------------------------------

def loadMitralSample():
  """Download/load the SlicerHeart 'Mitral' sample; returns the volume sequence browser node.

  Raises ``unittest.SkipTest`` when the download is not possible (offline).
  """
  import unittest
  import SampleData
  try:
    SampleData.SampleDataLogic().downloadSample("Mitral")
  except Exception as e:  # noqa: BLE001
    raise unittest.SkipTest(f"Mitral sample data not available: {e}")
  # The sample bundles a leaflet segmentation that is not needed here
  for segmentationNode in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
    slicer.mrmlScene.RemoveNode(segmentationNode)
  sequenceNodes = slicer.util.getNodesByClass("vtkMRMLSequenceNode")
  if not sequenceNodes:
    raise unittest.SkipTest("Mitral sample did not produce a volume sequence")
  browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForSequenceNode(sequenceNodes[0])
  if not browserNode:
    raise unittest.SkipTest("Mitral sample volume sequence has no browser")
  return browserNode
