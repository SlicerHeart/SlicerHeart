"""
Assertion helpers mixed into SlicerHeartTestCase.

All helpers only use ``self.assert*`` from unittest so they work in both runner paths.
"""

import slicer


def controlPointPositions(markupsNode):
  """:returns: list of ``(x, y, z)`` tuples for every control point (local coordinates)."""
  result = []
  for i in range(markupsNode.GetNumberOfControlPoints()):
    pos = [0.0, 0.0, 0.0]
    markupsNode.GetNthControlPointPosition(i, pos)
    result.append(tuple(pos))
  return result


def controlPointLabels(markupsNode):
  return [markupsNode.GetNthControlPointLabel(i) for i in range(markupsNode.GetNumberOfControlPoints())]


def matrixToList(matrix):
  return [[matrix.GetElement(r, c) for c in range(4)] for r in range(4)]


def shNode():
  return slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)


def shParentDataNode(node):
  """:returns: the data node of the subject hierarchy parent item of *node* (None for folders/root)."""
  sh = shNode()
  itemId = sh.GetItemByDataNode(node)
  if not itemId:
    return None
  parentId = sh.GetItemParent(itemId)
  if not parentId:
    return None
  return sh.GetItemDataNode(parentId)


def shParentName(node):
  sh = shNode()
  itemId = sh.GetItemByDataNode(node)
  if not itemId:
    return None
  parentId = sh.GetItemParent(itemId)
  return sh.GetItemName(parentId) if parentId else None


class HeartValveAsserts:
  """Mixin with domain-specific assertions (requires unittest.TestCase's assert methods)."""

  def assertPointsAlmostEqual(self, actualPoints, expectedPoints, places=4, msg=""):
    self.assertEqual(len(actualPoints), len(expectedPoints), f"{msg}: point count")
    for i, (actual, expected) in enumerate(zip(actualPoints, expectedPoints)):
      for j in range(3):
        self.assertAlmostEqual(actual[j], expected[j], places=places, msg=f"{msg}: point {i} coord {j}")

  def assertControlPointsEqual(self, markupsNode, expectedPoints, places=4, msg=""):
    self.assertIsNotNone(markupsNode, f"{msg}: markups node missing")
    self.assertPointsAlmostEqual(controlPointPositions(markupsNode), expectedPoints, places, msg)

  def assertControlPointsNotEqual(self, markupsNode, otherPoints, msg=""):
    self.assertIsNotNone(markupsNode, f"{msg}: markups node missing")
    actual = controlPointPositions(markupsNode)
    if len(actual) != len(otherPoints):
      return
    for actualPoint, otherPoint in zip(actual, otherPoints):
      for j in range(3):
        if abs(actualPoint[j] - otherPoint[j]) > 1e-4:
          return
    self.fail(f"{msg}: control points unexpectedly equal to {otherPoints}")

  def assertLabelsEqual(self, markupsNode, expectedLabeledPoints, places=4, msg=""):
    """*expectedLabeledPoints*: list of ``(label, r, a, s)``."""
    self.assertIsNotNone(markupsNode, f"{msg}: labels node missing")
    self.assertEqual(controlPointLabels(markupsNode), [lp[0] for lp in expectedLabeledPoints], f"{msg}: labels")
    self.assertPointsAlmostEqual(controlPointPositions(markupsNode), [lp[1:] for lp in expectedLabeledPoints],
                                 places, msg)

  def assertMatricesEqual(self, actual, expected, places=5, msg=""):
    for row in range(4):
      for col in range(4):
        self.assertAlmostEqual(actual.GetElement(row, col), expected.GetElement(row, col), places=places,
                               msg=f"{msg}: element ({row}, {col})")

  def assertMatricesNotEqual(self, actual, expected, msg=""):
    for row in range(4):
      for col in range(4):
        if abs(actual.GetElement(row, col) - expected.GetElement(row, col)) > 1e-5:
          return
    self.fail(f"{msg}: matrices unexpectedly equal")

  def assertSequenceHasItem(self, sequenceNode, indexValue, msg=""):
    self.assertIsNotNone(sequenceNode, f"{msg}: sequence node missing")
    self.assertGreaterEqual(sequenceNode.GetItemNumberFromIndexValue(indexValue), 0,
                            f"{msg}: sequence {sequenceNode.GetName()} has no item at index value {indexValue!r}"
                            f" (has {self.sequenceIndexValues(sequenceNode)})")

  def assertSequenceLacksItem(self, sequenceNode, indexValue, msg=""):
    self.assertIsNotNone(sequenceNode, f"{msg}: sequence node missing")
    self.assertLess(sequenceNode.GetItemNumberFromIndexValue(indexValue), 0,
                    f"{msg}: sequence {sequenceNode.GetName()} unexpectedly has an item at {indexValue!r}")

  @staticmethod
  def sequenceIndexValues(sequenceNode):
    return [sequenceNode.GetNthIndexValue(i) for i in range(sequenceNode.GetNumberOfDataNodes())]

  def assertSequenceIndexValues(self, sequenceNode, expectedIndexValues, msg=""):
    self.assertIsNotNone(sequenceNode, f"{msg}: sequence node missing")
    self.assertEqual(self.sequenceIndexValues(sequenceNode), list(expectedIndexValues), f"{msg}: index values")

  def assertNodeReference(self, node, role, expectedNode, msg=""):
    actual = node.GetNodeReference(role)
    expectedId = expectedNode.GetID() if expectedNode else None
    actualId = actual.GetID() if actual else None
    self.assertEqual(actualId, expectedId, f"{msg}: reference {role!r} of {node.GetName()}")

  def assertNthNodeReferences(self, node, role, expectedNodes, msg=""):
    actualIds = [node.GetNthNodeReferenceID(role, i) for i in range(node.GetNumberOfNodeReferences(role))]
    expectedIds = [n.GetID() for n in expectedNodes]
    self.assertEqual(actualIds, expectedIds, f"{msg}: references {role!r} of {node.GetName()}")

  def assertShParentIs(self, node, expectedParentNode, msg=""):
    actual = shParentDataNode(node)
    self.assertIsNotNone(actual, f"{msg}: {node.GetName()} has no data-node parent in subject hierarchy "
                                 f"(parent item: {shParentName(node)!r})")
    self.assertEqual(actual.GetID(), expectedParentNode.GetID(),
                     f"{msg}: {node.GetName()} parent is {actual.GetName()} not {expectedParentNode.GetName()}")

  def assertShParentNameIs(self, node, expectedName, msg=""):
    self.assertEqual(shParentName(node), expectedName, f"{msg}: subject hierarchy parent of {node.GetName()}")

  def assertSegmentIds(self, segmentationNode, expectedIds, msg=""):
    self.assertIsNotNone(segmentationNode, f"{msg}: segmentation missing")
    self.assertEqual(sorted(segmentationNode.GetSegmentation().GetSegmentIDs()), sorted(expectedIds),
                     f"{msg}: segment IDs")

  def assertInScene(self, node, msg=""):
    self.assertIsNotNone(node, f"{msg}: node is None")
    self.assertTrue(slicer.mrmlScene.IsNodePresent(node), f"{msg}: {node.GetName()} is not in the scene")

  def assertNotInScene(self, node, msg=""):
    if node is None:
      return
    self.assertFalse(slicer.mrmlScene.IsNodePresent(node), f"{msg}: {node.GetName()} is still in the scene")

  def assertNodeCountsEqual(self, before, after, msg="", ignore=()):
    """Compare two node censuses (dicts className -> count)."""
    diffs = []
    for className in sorted(set(before) | set(after)):
      if className in ignore:
        continue
      b, a = before.get(className, 0), after.get(className, 0)
      if a != b:
        diffs.append(f"{className}: {b} -> {a}")
    self.assertFalse(diffs, f"{msg}: node counts changed: " + "; ".join(diffs))

  def assertParentTransformIs(self, node, expectedTransformNode, msg=""):
    actual = node.GetParentTransformNode()
    actualId = actual.GetID() if actual else None
    expectedId = expectedTransformNode.GetID() if expectedTransformNode else None
    self.assertEqual(actualId, expectedId, f"{msg}: parent transform of {node.GetName()}")
