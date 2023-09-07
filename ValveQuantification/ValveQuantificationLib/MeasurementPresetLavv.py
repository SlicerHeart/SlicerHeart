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

    # Annulus circumference
    self.addMeasurement(self.getAnnulusCircumference(valveModel))

    # Annulus point distances
    self.addMeasurement(self.getDistanceBetweenPoints(valveModel, 'ALC', valveModel, 'SIC'))
    self.addMeasurement(self.getDistanceBetweenPoints(valveModel, 'PMC', valveModel, 'SIC'))
    self.addMeasurement(self.getDistanceBetweenPoints(valveModel, 'ALC', valveModel, 'PMC'))

    planePosition, planeNormal = valveModel.getAnnulusContourPlane()

    # Annulus area measurements
    self.addAnnulusAreaMeasurements(valveModel, planePosition, planeNormal)
    self.addAnnulusHeightMeasurements(valveModel, planePosition, planeNormal)

    self.addMeasurement(self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'PMC', valveModel, 'ALC', oriented=True, positiveDirection_valveModel1=planeNormal))
    self.addMeasurement(self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'ALC', valveModel, 'SIC', oriented=True, positiveDirection_valveModel1=planeNormal))
    self.addMeasurement(self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'SIC', valveModel, 'PMC', oriented=True, positiveDirection_valveModel1=planeNormal))
    self.addMeasurement(self.getCurveLengthBetweenPoints(valveModel, valveModel.annulusContourCurve, 'ALC', valveModel, 'PMC', oriented=True, positiveDirection_valveModel1=planeNormal))

    self.addSegmentedLeafletMeasurements(valveModel, planePosition, planeNormal)

    self.addCoaptationMeasurements(valveModel)

    return self.metricsMessages