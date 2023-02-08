import os

import qt
import slicer

from .utils import (
  getSegmentationFromAnnulusContourNode,
  createLabelNodeFromVisibleSegments,
  getLabelFromLandmarkPositions
)
from .base import (
  ImageValveBatchExportRule,
  ValveBatchExportPlugin
)


class AnnulusContourExportRuleWidget(ValveBatchExportPlugin):

  def __init__(self, checked=False):
    ValveBatchExportPlugin.__init__(self, AnnulusContourExportRule, checked)

  def setup(self):
    ValveBatchExportPlugin.setup(self)
    layout = self.getOptionsLayout()
    logic = self.logic

    self.modelCheckbox = qt.QCheckBox("Export as model (.vtk)")
    self.modelCheckbox.stateChanged.connect(self.onModelCheckboxModified)
    self.modelCheckbox.checked = logic.EXPORT_ANNULUS_AS_MODEL

    self.segmentationCheckbox = qt.QCheckBox("Export as segmentation")
    self.segmentationCheckbox.stateChanged.connect(self.onSegCheckboxModified)
    self.segmentationCheckbox.checked = logic.EXPORT_ANNULUS_AS_LABEL

    self.contourLabelsCheckbox = qt.QCheckBox("Export control points as segmentation")
    self.contourLabelsCheckbox.stateChanged.connect(self.onLabelsCheckboxModified)
    self.contourLabelsCheckbox.checked = logic.EXPORT_ANNULUS_POINTS_AS_LABELS

    layout.addWidget(self.modelCheckbox)
    layout.addWidget(self.segmentationCheckbox)
    layout.addWidget(self.contourLabelsCheckbox)

  def onModelCheckboxModified(self, checked):
    logic = self.logic
    logic.EXPORT_ANNULUS_AS_MODEL = checked
    if checked:
      logic.OTHER_FLAGS.append(logic.CMD_FLAG_MODEL)
    else:
      if logic.CMD_FLAG_MODEL in logic.OTHER_FLAGS:
        logic.OTHER_FLAGS.remove(logic.CMD_FLAG_MODEL)

  def onSegCheckboxModified(self, checked):
    logic = self.logic
    logic.EXPORT_ANNULUS_AS_LABEL = checked
    if checked:
      logic.OTHER_FLAGS.append(logic.CMD_FLAG_SEGMENTATION)
    else:
      if logic.CMD_FLAG_SEGMENTATION in logic.OTHER_FLAGS:
        logic.OTHER_FLAGS.remove(logic.CMD_FLAG_SEGMENTATION)

  def onLabelsCheckboxModified(self, checked):
    logic = self.logic
    logic.EXPORT_ANNULUS_POINTS_AS_LABELS = checked
    if checked:
      logic.OTHER_FLAGS.append(logic.CMD_FLAG_POINT_LABELS)
    else:
      if logic.CMD_FLAG_POINT_LABELS in logic.OTHER_FLAGS:
        logic.OTHER_FLAGS.remove(logic.CMD_FLAG_POINT_LABELS)


class AnnulusContourExportRule(ImageValveBatchExportRule):

  BRIEF_USE = "Annulus contour"
  DETAILED_DESCRIPTION = "Export annulus contour"

  CMD_FLAG = "-ac"
  CMD_FLAG_MODEL = "-acm"
  CMD_FLAG_SEGMENTATION = "-acl"
  CMD_FLAG_POINT_LABELS = "-acp"

  EXPORT_ANNULUS_AS_LABEL = False
  EXPORT_ANNULUS_AS_MODEL = True
  EXPORT_ANNULUS_POINTS_AS_LABELS = False
  NUM_EXPORT_ANNULUS_POINTS_AS_LABELS = 20

  class AnnulusExportFailed(Exception):
    pass

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      valveModelName = self.generateValveModelName(sceneFileName, valveModel, suffix="annulus")

      if not valveModel.getAnnulusContourModelNode().GetPolyData().GetNumberOfPoints() > 0:
        self.addLog(f"  No annulus contour defined for valve model - {valveModelName}")
        continue

      self.exportAnnulusContourModel(valveModel, valveModelName)
      self.exportAnnulusContourAsLabel(valveModel, valveModelName)
      self.exportAnnulusContourPointsAsLabels(valveModel, valveModelName)

  def exportAnnulusContourModel(self, valveModel, valveModelName):
    if not self.EXPORT_ANNULUS_AS_MODEL:
      return
    modelNode = valveModel.getAnnulusContourModelNode()
    storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelStorageNode")
    storageNode.SetFileName(os.path.join(self.outputDir, f"{valveModelName}.vtk"))
    if not storageNode.WriteData(modelNode):
      self.addLog(f"  Annulus contour model export skipped (file writing failed) - {valveModelName}")
    slicer.mrmlScene.RemoveNode(storageNode)

  def exportAnnulusContourAsLabel(self, valveModel, valveModelName):
    if not self.CMD_FLAG_SEGMENTATION:
      return
    segNode = getSegmentationFromAnnulusContourNode(valveModel)
    if not segNode:
      raise self.AnnulusExportFailed()
    labelNode = createLabelNodeFromVisibleSegments(segNode, valveModel, "Annulus")
    slicer.mrmlScene.RemoveNode(segNode)
    slicer.util.saveNode(labelNode, os.path.join(self.outputDir, f"{valveModelName}.seg{self.FILE_FORMAT}"))

  def exportAnnulusContourPointsAsLabels(self, valveModel, valveModelName):
    if not self.CMD_FLAG_POINT_LABELS:
      return
    closedCurve = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsClosedCurveNode")
    positions = slicer.util.arrayFromMarkupsControlPoints(valveModel.annulusContourCurve.controlPointsMarkupNode)
    slicer.util.updateMarkupsControlPointsFromArray(closedCurve, positions)
    # resample curve points to fixed number
    sampleDist = closedCurve.GetCurveLengthWorld() / (self.NUM_EXPORT_ANNULUS_POINTS_AS_LABELS - 1)
    closedCurve.ResampleCurveWorld(sampleDist)
    positions = slicer.util.arrayFromMarkupsControlPoints(closedCurve)
    if positions is not None:
      labelNode = getLabelFromLandmarkPositions("annulus_points", positions, valveModel)
      slicer.util.saveNode(labelNode, os.path.join(self.outputDir, f"{valveModelName}_blobs.seg{self.FILE_FORMAT}"))
