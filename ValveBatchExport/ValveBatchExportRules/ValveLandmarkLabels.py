import qt
import os
import slicer
from .base import (
  ImageValveBatchExportRule,
  ValveBatchExportPlugin
)
from .utils import getLabelFromLandmarkPositions
from .constants import VALVE_COMMISSURAL_LANDMARKS, VALVE_QUADRANT_LANDMARKS


class ValveLandmarkLabelsExportRule(ImageValveBatchExportRule):

  BRIEF_USE = "Valve landmark labels"
  DETAILED_DESCRIPTION = "Export valve landmarks as segmentation blob"

  CMD_FLAG = "-ll"
  CMD_FLAG_QUADRANTS = "-llq"
  CMD_FLAG_COMMISSURES = "-llc"
  CMD_FLAG_SEPARATE_FILES = "-lls"  # each landmark goes into separate nrrd

  OTHER_FLAGS = []
  EXPORT_QUADRANT_LANDMARKS = True
  EXPORT_COMMISSURAL_LANDMARKS = True
  ONE_FILE_PER_LANDMARK = False

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      valveType = valveModel.getValveType()
      valveModelName = self.generateValveModelName(sceneFileName, valveModel)

      if self.ONE_FILE_PER_LANDMARK:
        lms = []
        if self.EXPORT_QUADRANT_LANDMARKS:
          lms.extend(VALVE_QUADRANT_LANDMARKS[valveType])
        if self.EXPORT_COMMISSURAL_LANDMARKS:
          lms.extend(VALVE_COMMISSURAL_LANDMARKS[valveType])

        for lm in lms:
          pos = valveModel.getAnnulusMarkupPositionByLabel(lm)
          if pos is None:
            continue
          labelNode = getLabelFromLandmarkPositions(lm, [pos], valveModel)
          slicer.util.saveNode(labelNode,
                               os.path.join(self.outputDir, f"{valveModelName}_landmark_{lm}.seg{self.FILE_FORMAT}"))
      else:
        if self.EXPORT_QUADRANT_LANDMARKS:
          positions = valveModel.getAnnulusMarkupPositionsByLabels(VALVE_QUADRANT_LANDMARKS[valveType])
          positions = list(filter(lambda pos: pos is not None, positions))
          if positions:
            labelNode = getLabelFromLandmarkPositions("quadrant_landmarks", positions, valveModel)
            slicer.util.saveNode(labelNode, os.path.join(self.outputDir,
                                                         f"{valveModelName}_quadrant_landmarks.seg{self.FILE_FORMAT}"))
        if self.EXPORT_COMMISSURAL_LANDMARKS:
          positions = valveModel.getAnnulusMarkupPositionsByLabels(VALVE_COMMISSURAL_LANDMARKS[valveType])
          positions = list(filter(lambda pos: pos is not None, positions))
          if positions:
            labelNode = getLabelFromLandmarkPositions("commissural_landmarks", positions, valveModel)
            slicer.util.saveNode(labelNode, os.path.join(self.outputDir,
                                                         f"{valveModelName}_commissural_landmarks.seg{self.FILE_FORMAT}"))


class ValveLandmarkLabelsExportRuleWidget(ValveBatchExportPlugin):

  def __init__(self, checked=False):
    ValveBatchExportPlugin.__init__(self, ValveLandmarkLabelsExportRule, checked)

  def setup(self):
    ValveBatchExportPlugin.setup(self)
    layout = self.getOptionsLayout()

    logic = self.logic

    separateCheckbox = qt.QCheckBox("One file per landmark")
    quadrantCheckbox = qt.QCheckBox("Quadrant Landmarks (e.g. A,P,S,L)")
    commissuralCheckbox = qt.QCheckBox("Commissural Landmarks (e.g. ASC,PSC,APC)")

    def onQuadrantCheckboxModified(checked):
      logic.EXPORT_QUADRANT_LANDMARKS = checked
      if checked:
        logic.OTHER_FLAGS.append(logic.CMD_FLAG_QUADRANTS)
      else:
        if logic.CMD_FLAG_QUADRANTS in logic.OTHER_FLAGS:
          logic.OTHER_FLAGS.remove(logic.CMD_FLAG_QUADRANTS)

    def onCommissuresCheckboxModified(checked):
      logic.EXPORT_COMMISSURAL_LANDMARKS = checked
      if checked:
        logic.OTHER_FLAGS.append(logic.CMD_FLAG_COMMISSURES)
      else:
        if logic.CMD_FLAG_COMMISSURES in logic.OTHER_FLAGS:
          logic.OTHER_FLAGS.remove(logic.CMD_FLAG_COMMISSURES)

    def onSeparateCheckboxModified(checked):
      logic.ONE_FILE_PER_LANDMARK = checked
      if checked:
        logic.OTHER_FLAGS.append(logic.CMD_FLAG_SEPARATE_FILES)
      else:
        if logic.CMD_FLAG_SEPARATE_FILES in logic.OTHER_FLAGS:
          logic.OTHER_FLAGS.remove(logic.CMD_FLAG_SEPARATE_FILES)

    separateCheckbox.stateChanged.connect(onSeparateCheckboxModified)
    quadrantCheckbox.checked = logic.ONE_FILE_PER_LANDMARK

    quadrantCheckbox.stateChanged.connect(onQuadrantCheckboxModified)
    quadrantCheckbox.checked = logic.EXPORT_QUADRANT_LANDMARKS

    commissuralCheckbox.stateChanged.connect(onCommissuresCheckboxModified)
    commissuralCheckbox.checked = logic.EXPORT_COMMISSURAL_LANDMARKS

    layout.addWidget(separateCheckbox)
    layout.addWidget(quadrantCheckbox)
    layout.addWidget(commissuralCheckbox)