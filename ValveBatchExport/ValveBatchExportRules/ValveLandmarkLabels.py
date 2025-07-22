import qt
import os
import slicer
import vtk
from .base import ValveBatchExportRule, getNewSegmentationNode, createLabelNodeFromVisibleSegments


VALVE_COMMISSURAL_LANDMARKS = {
  "mitral": ['PMC', 'ALC'],
  "tricuspid": ['ASC', 'PSC', 'APC'],
  "cavc": ['SRC', 'SLC', 'IRC', 'ILC'],
  "lavv": ['ALC', 'PMC', 'SIC']
}

VALVE_QUADRANT_LANDMARKS = {
  "mitral": ['A', 'P', 'PM', 'AL'],
  "tricuspid": ['A', 'P', 'S', 'L'],
  "cavc": ['R', 'L', 'MA', 'MP'],
  "lavv": []
}


class ValveLandmarkLabelsExportRule(ValveBatchExportRule):

  BRIEF_USE = "Valve landmark labels (.nrrd)"
  DETAILED_DESCRIPTION = "Export valve landmarks as segmentation blob"
  USER_INTERFACE = True

  CMD_FLAG = "-ll"
  CMD_FLAG_QUADRANTS = "-llq"
  CMD_FLAG_COMMISSURES = "-llc"
  CMD_FLAG_SEPARATE_FILES = "-lls"  # each landmark goes into separate nrrd

  OTHER_FLAGS = []
  EXPORT_QUADRANT_LANDMARKS = True
  EXPORT_COMMISSURAL_LANDMARKS = True
  ONE_FILE_PER_LANDMARK = False

  @classmethod
  def setupUI(cls, layout):
    separateCheckbox = qt.QCheckBox("One file per landmark")
    quadrantCheckbox = qt.QCheckBox("Quadrant Landmarks (e.g. A,P,S,L)")
    commissuralCheckbox = qt.QCheckBox("Commissural Landmarks (e.g. ASC,PSC,APC)")

    def onQuadrantCheckboxModified(checked):
      cls.EXPORT_QUADRANT_LANDMARKS = checked
      if checked:
        cls.OTHER_FLAGS.append(cls.CMD_FLAG_QUADRANTS)
      else:
        if cls.CMD_FLAG_QUADRANTS in cls.OTHER_FLAGS:
          cls.OTHER_FLAGS.remove(cls.CMD_FLAG_QUADRANTS)

    def onCommissuresCheckboxModified(checked):
      cls.EXPORT_COMMISSURAL_LANDMARKS = checked
      if checked:
        cls.OTHER_FLAGS.append(cls.CMD_FLAG_COMMISSURES)
      else:
        if cls.CMD_FLAG_COMMISSURES in cls.OTHER_FLAGS:
          cls.OTHER_FLAGS.remove(cls.CMD_FLAG_COMMISSURES)

    def onSeparateCheckboxModified(checked):
      cls.ONE_FILE_PER_LANDMARK = checked
      if checked:
        cls.OTHER_FLAGS.append(cls.CMD_FLAG_SEPARATE_FILES)
      else:
        if cls.CMD_FLAG_SEPARATE_FILES in cls.OTHER_FLAGS:
          cls.OTHER_FLAGS.remove(cls.CMD_FLAG_SEPARATE_FILES)

    separateCheckbox.stateChanged.connect(onSeparateCheckboxModified)
    quadrantCheckbox.checked = cls.ONE_FILE_PER_LANDMARK

    quadrantCheckbox.stateChanged.connect(onQuadrantCheckboxModified)
    quadrantCheckbox.checked = cls.EXPORT_QUADRANT_LANDMARKS

    commissuralCheckbox.stateChanged.connect(onCommissuresCheckboxModified)
    commissuralCheckbox.checked = cls.EXPORT_COMMISSURAL_LANDMARKS

    layout.addWidget(separateCheckbox)
    layout.addWidget(quadrantCheckbox)
    layout.addWidget(commissuralCheckbox)

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      frameNumber = self.getAssociatedFrameNumber(valveModel)
      filename, file_extension = os.path.splitext(os.path.basename(sceneFileName))
      valveType = valveModel.heartValveNode.GetAttribute('ValveType')
      cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
      valveModelName = self.generateValveModelName(filename, valveType, cardiacCyclePhaseName, frameNumber)
      fileExtension = "nii.gz"

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
                               os.path.join(self.outputDir, f"{valveModelName}_landmark_{lm}.{fileExtension}"))
      else:
        if self.EXPORT_QUADRANT_LANDMARKS:
          positions = valveModel.getAnnulusMarkupPositionsByLabels(VALVE_QUADRANT_LANDMARKS[valveType])
          positions = list(filter(lambda pos: pos is not None, positions))
          if positions:
            labelNode = getLabelFromLandmarkPositions("quadrant_landmarks", positions, valveModel)
            slicer.util.saveNode(labelNode, os.path.join(self.outputDir,
                                                         f"{valveModelName}_quadrant_landmarks.{fileExtension}"))
        if self.EXPORT_COMMISSURAL_LANDMARKS:
          positions = valveModel.getAnnulusMarkupPositionsByLabels(VALVE_COMMISSURAL_LANDMARKS[valveType])
          positions = list(filter(lambda pos: pos is not None, positions))
          if positions:
            labelNode = getLabelFromLandmarkPositions("commissural_landmarks", positions, valveModel)
            slicer.util.saveNode(labelNode, os.path.join(self.outputDir,
                                                         f"{valveModelName}_commissural_landmarks.{fileExtension}"))


def getLabelFromLandmarkPositions(name, positions, valveModel):
  import random
  segNode = getNewSegmentationNode(valveModel.getValveVolumeNode())
  probeToRasTransform = valveModel.getProbeToRasTransformNode()
  segNode.SetAndObserveTransformNodeID(probeToRasTransform.GetID())
  color = [random.uniform(0.0,1.0), random.uniform(0.0,1.0), random.uniform(0.0,1.0)]

  sphereSegment = slicer.vtkSegment()
  sphereSegment.SetName(name)
  sphereSegment.SetColor(*color)

  append = vtk.vtkAppendPolyData()
  for pos in positions:
    sphere = vtk.vtkSphereSource()
    sphere.SetCenter(*pos)
    sphere.SetRadius(1)
    append.AddInputConnection(sphere.GetOutputPort())
  append.Update()

  sphereSegment.AddRepresentation(
    slicer.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName(), append.GetOutput())
  segNode.GetSegmentation().AddSegment(sphereSegment)


  labelNode = createLabelNodeFromVisibleSegments(segNode, valveModel, name)
  slicer.mrmlScene.RemoveNode(segNode)
  return labelNode