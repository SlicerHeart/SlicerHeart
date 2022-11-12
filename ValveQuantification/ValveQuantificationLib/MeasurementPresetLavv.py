from ValveQuantificationLib.MeasurementPreset import *


class MeasurementPresetLavv(MeasurementPreset):

  def __init__(self):
    super(MeasurementPresetLavv, self).__init__()
    self.id = "Lavv"
    self.name = "LAVV"
    self.inputValveIds = ["Lavv"]
    self.inputValveNames = {"Lavv": "LAVV"}
    self.inputFields = [
      createPointInputField("AlcPoint", "ALC", self.id, False),
      createPointInputField("PmcPoint", "PMC", self.id, False),
      createPointInputField("SicPoint", "SIC", self.id, False)
    ]
    self.definitionsUrl = self.getResourceFileUrl("Lavv.html")

  def computeMetrics(self, inputValveModels, outputTableNode):
    super(MeasurementPresetLavv, self).computeMetrics(inputValveModels, outputTableNode)

    if not "Lavv" in inputValveModels.keys():
      return ["Selection of LAVV is required"]

    valveModel = inputValveModels["Lavv"]

    # TODO: add measurements

    return self.metricsMessages