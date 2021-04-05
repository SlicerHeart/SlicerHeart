#
#   Measurement preset applicable for all types of valves
#

from MeasurementPreset import *


class MeasurementPresetGenericValve(MeasurementPreset):

  def __init__(self):
    super(MeasurementPresetGenericValve, self).__init__()
    self.id = "GenericValve"
    self.name = "Generic valve"
    self.inputValveIds = ["Valve"]
    self.inputValveNames = {"Valve": "Valve"}
    self.inputFields = []

  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetGenericValve, self).computeMetrics(inputValveModels, outputTableNode)

    if not inputValveModels:
      return ["Valve selection is required"]

    valveModel = inputValveModels["Valve"]

    [planePosition, planeNormal] = valveModel.getAnnulusContourPlane()

    self.addAnnulusAreaMeasurements(valveModel, planePosition, planeNormal)
    self.addAnnulusHeightMeasurements(valveModel, planePosition, planeNormal)

    return self.metricsMessages