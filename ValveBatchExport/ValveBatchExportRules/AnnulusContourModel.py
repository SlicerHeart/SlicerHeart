import os
import qt
import slicer
from .base import ValveBatchExportRule, getNewSegmentationNode, createLabelNodeFromVisibleSegments


class AnnulusContourModelExportRule(ValveBatchExportRule):

  BRIEF_USE = "Annulus contour model"
  DETAILED_DESCRIPTION = "Export annulus contour model"
  USER_INTERFACE = True

  CMD_FLAG = "-ac"
  CMD_FLAG_MODEL = "-acm"
  CMD_FLAG_SEGMENTATION = "-acl"

  EXPORT_ANNULUS_AS_LABEL = False
  EXPORT_ANNULUS_AS_MODEL = True

  class AnnulusExportFailed(Exception):
    pass

  @classmethod
  def setupUI(cls, layout):
    modelCheckbox = qt.QCheckBox("Export as model (.vtk)")
    segmentationCheckbox = qt.QCheckBox("Export as segmentation (.nrrd)")

    def onModelCheckboxModified(checked):
      cls.EXPORT_ANNULUS_AS_LABEL = checked
      if checked:
        cls.OTHER_FLAGS.append(cls.CMD_FLAG_MODEL)
      else:
        if cls.CMD_FLAG_MODEL in cls.OTHER_FLAGS:
          cls.OTHER_FLAGS.remove(cls.CMD_FLAG_MODEL)

    def onSegCheckboxModified(checked):
      cls.ONE_FILE_PER_SEGMENT = checked
      if checked:
        cls.OTHER_FLAGS.append(cls.CMD_FLAG_SEGMENTATION)
      else:
        if cls.CMD_FLAG_SEGMENTATION in cls.OTHER_FLAGS:
          cls.OTHER_FLAGS.remove(cls.CMD_FLAG_SEGMENTATION)

    modelCheckbox.stateChanged.connect(onModelCheckboxModified)
    modelCheckbox.checked = cls.EXPORT_ANNULUS_AS_MODEL

    segmentationCheckbox.stateChanged.connect(onSegCheckboxModified)
    segmentationCheckbox.checked = cls.EXPORT_ANNULUS_AS_LABEL

    layout.addWidget(modelCheckbox)
    layout.addWidget(segmentationCheckbox)

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      frameNumber = self.getAssociatedFrameNumber(valveModel)
      filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
      valveType = valveModel.heartValveNode.GetAttribute('ValveType')
      cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
      valveModelName = \
        self.generateValveModelName(filename, valveType, cardiacCyclePhaseName, frameNumber, suffix="annulus")

      if self.EXPORT_ANNULUS_AS_MODEL:
        modelNode = valveModel.getAnnulusContourModelNode()

        storageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelStorageNode")
        storageNode.SetFileName(os.path.join(self.outputDir, f"{valveModelName}.vtk"))

        if not storageNode.WriteData(modelNode):
          self.addLog(f"  Annulus contour model export skipped (file writing failed) - {valveModelName}")
        slicer.mrmlScene.RemoveNode(storageNode)

      if self.CMD_FLAG_SEGMENTATION:
        segNode = getSegmentationFromAnnulusContourNode(valveModel)
        if not segNode:
          raise self.AnnulusExportFailed()
        labelNode = createLabelNodeFromVisibleSegments(segNode, valveModel, "Annulus")
        slicer.mrmlScene.RemoveNode(segNode)
        slicer.util.saveNode(labelNode, os.path.join(self.outputDir, f"{valveModelName}.nii.gz"))


def getSegmentationFromAnnulusContourNode(valveModel):
  annulusModelNode = valveModel.getAnnulusContourModelNode()
  segmentationNode = getNewSegmentationNodeFromModel(valveModel.getValveVolumeNode(), annulusModelNode)
  slicer.mrmlScene.RemoveNode(annulusModelNode)
  return segmentationNode


def getNewSegmentationNodeFromModel(valveVolume, modelNode):
  segmentationNode = getNewSegmentationNode(valveVolume)
  segmentationsLogic = slicer.modules.segmentations.logic()
  segmentationsLogic.ImportModelToSegmentationNode(modelNode, segmentationNode)
  return segmentationNode