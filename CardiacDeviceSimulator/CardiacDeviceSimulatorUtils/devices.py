import os
import qt, ctk, vtk
from .helpers import UIHelper

import collections
from collections import OrderedDict

class DeviceImplantWidget(qt.QFrame, UIHelper):

  DEVICE_CLASS_MODIFIED_EVENT = 20000
  DEVICE_PARAMETER_VALUE_MODIFIED_EVENT = 20001

  def __init__(self, deviceClass, parent=None):
    super(DeviceImplantWidget, self).__init__(parent)
    self.deviceClass = deviceClass
    self.parameterNode = None
    self.setup()
    self.destroyed.connect(self._onAboutToBeDestroyed)

  def setParameterNode(self, parameterNode):
    self.parameterNode = parameterNode
    self.updateGUIFromMRML()

  def reset(self):
    wasBlocked = self._presetCombo.blockSignals(True)
    self._presetCombo.setCurrentIndex(0)
    self._presetCombo.blockSignals(wasBlocked)

  def setup(self):
    self.setLayout(qt.QFormLayout(self))
    self._addDeviceLabel()
    self._addPresetsCombo()
    self._addSliders()

  def _onAboutToBeDestroyed(self, obj):
    obj.destroyed.disconnect(self._onAboutToBeDestroyed)

  def updateGUIFromMRML(self):
    if not self.parameterNode:
      return
    presetName = self.parameterNode.GetParameter(self.deviceClass.ID + "_preset")
    wasBlocked = self._presetCombo.blockSignals(True)
    if presetName:
      self._presetCombo.setCurrentText(presetName)
    else:
      self._presetCombo.setCurrentIndex(-1)
    self._presetCombo.blockSignals(wasBlocked)

    for paramName, paramAttributes in self.deviceClass.getParameters().items():
      paramValue = self.parameterNode.GetParameter(self.deviceClass.ID+"_"+paramName)
      if not paramValue:
        continue
      paramValue = float(paramValue)
      sliderWidget = getattr(self, "{}SliderWidget".format(paramName))
      paramScale = (0.01 if paramAttributes["unit"] == "%" else 1.0)
      wasBlocked = sliderWidget.blockSignals(True)
      sliderWidget.value = paramValue / paramScale
      sliderWidget.blockSignals(wasBlocked)

  # def updateMRMLFromGUI(self, parameterNode):
  #   if not parameterNode:
  #     return
  #   valuesChanged = False
  #   for paramName, paramAttributes in self.deviceClass.getParameters().items():
  #     sliderWidget = getattr(self, "{}SliderWidget".format(paramName))
  #     paramValue = sliderWidget.value
  #     paramScale = (0.01 if paramAttributes["unit"] == "%" else 1.0)
  #     newParamValue = str(paramValue * paramScale)
  #     oldParamValue = parameterNode.GetParameter(self.deviceClass.ID+"_"+paramName)
  #     if newParamValue != oldParamValue:
  #       parameterNode.SetParameter(self.deviceClass.ID+"_"+paramName, newParamValue)
  #       valuesChanged = True
  #   if valuesChanged:
  #     self._presetCombo.setCurrentIndex(-1)

  # def setParameters(self, params):
  #   for paramName, paramAttributes in self.deviceClass.getParameters().items():
  #     sliderWidget = getattr(self, "{}SliderWidget".format(paramName))
  #     paramScale = (0.01 if paramAttributes["unit"] == "%" else 1.0)
  #     if not hasattr(modelParameters, paramName):
  #       continue
  #     paramValue = modelParameters[paramName]
  #     wasBlocked = sliderWidget.blockSignals(True)
  #     sliderWidget.value = paramValue * paramScale
  #     sliderWidget.blockSignals(wasBlocked)

  def _addSliders(self):
    for paramName, paramAttributes in self.deviceClass.getParameters().items():
      setattr(self, "{}SliderWidget".format(paramName), self.addSlider(paramAttributes, self.layout(), self.onSliderMoved))

  def _addDeviceLabel(self):
    self._widgetLabel = qt.QLabel(self.deviceClass.NAME)
    self._widgetLabel.setStyleSheet('font: italic "Times New Roman"; font-size: 15px')
    self.layout().addRow("Device Name:", self._widgetLabel)

  def _addPresetsCombo(self):
    self._presets = self.deviceClass.getPresets()
    self._presetCombo = qt.QComboBox()
    if self._presets:
      for model, properties in self._presets.items():
        values = "; ".join([properties[parameter] for parameter, attributes in self.deviceClass.getParameters().items()])
        self._presetCombo.addItem("{} | {{ {} }}".format(model, values))
      self._presetCombo.connect("currentIndexChanged(const QString)", self.onPresetSelected)
      self.layout().addRow("Presets:", self._presetCombo)

  def onSliderMoved(self):
    for paramName, paramAttributes in self.deviceClass.getParameters().items():
      sliderWidget = getattr(self, "{}SliderWidget".format(paramName))
      paramValue = sliderWidget.value
      paramScale = (0.01 if paramAttributes["unit"] == "%" else 1.0)
      newParamValue = str(paramValue * paramScale)
      self.parameterNode.SetParameter(self.deviceClass.ID+"_"+paramName, newParamValue)
    self._presetCombo.setCurrentIndex(-1)
    self.parameterNode.InvokeCustomModifiedEvent(DeviceImplantWidget.DEVICE_PARAMETER_VALUE_MODIFIED_EVENT)

  def onPresetSelected(self, text):
    presetName = text.split(' | ')[0] if text else ""
    self.parameterNode.SetParameter(self.deviceClass.ID + "_preset", presetName)
    if not presetName:
      # preset is not selected (custom settings)
      return
    params = self._presets[presetName]
    for parameter, attributes in self.deviceClass.getParameters().items():
      self.parameterNode.SetParameter(self.deviceClass.ID + "_" + parameter, str(params[parameter]))
    self.parameterNode.InvokeCustomModifiedEvent(DeviceImplantWidget.DEVICE_PARAMETER_VALUE_MODIFIED_EVENT)

class DeviceImplantPresets(OrderedDict):

  def __init__(self, csvfile, defaultParameters):
    super(DeviceImplantPresets, self).__init__()
    self._presetCSVFile = csvfile
    if self._presetCSVFile and os.path.exists(self._presetCSVFile):
      self._readPresets()
    else:
      # If preset file is not available then create a default preset from  the parameter info
      presets = OrderedDict()
      defaultPreset = {}
      for paramName, paramAttributes in defaultParameters.items():
        paramScale = (0.01 if paramAttributes["unit"] == "%" else 1.0)
        value = paramAttributes["value"] * paramScale
        defaultPreset[paramName] = str(value)
      presets["Default"] = defaultPreset
      self.update(presets)

  def _readPresets(self):
    import csv
    presets = OrderedDict()
    with open(self._presetCSVFile, mode='r') as csv_file:
      for row in csv.DictReader(csv_file):
        presets[row["Model"]] = {key:row[key] for key in row.keys() if key.lower() != "model"}
    self.update(presets)


class CardiacDeviceBase(object):

  NAME=None
  ID=None

  @classmethod
  def getParameters(cls):
    raise NotImplementedError

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': 0.0}

  @classmethod
  def getSegments(cls):
    return []

  @staticmethod
  def _genParameters(name, info, value, unit, minimum, maximum, singleStep, pageStep, decimals=2):
    return {"name": name, "info": info, "value": value, "unit": unit, "minimum": minimum, "maximum": maximum,
            "singleStep": singleStep, "pageStep": pageStep, "decimals": decimals}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True): #segment: one of 'distal', 'middle', 'proximal', 'whole'
    raise NotImplementedError

  @classmethod
  def getPresets(cls):
    csvFile = os.path.join(cls.RESOURCES_PATH, "Presets", cls.ID + ".csv")
    #if os.path.exists(csvFile):
    return DeviceImplantPresets(csvFile, cls.getParameters())

  @classmethod
  def getIcon(cls):
    if cls.ID:
      pngFile = os.path.join(cls.RESOURCES_PATH, "Icons", cls.ID + ".png")
      if os.path.exists(pngFile):
        return qt.QIcon(qt.QPixmap(pngFile))
    return None

  @classmethod
  def getParameterValuesFromNode(cls, parameterNode):
    parameterValues = {}
    parameters = cls.getParameters()
    for paramName, paramAttributes in parameters.items():
      paramValueStr = parameterNode.GetParameter(cls.ID + "_" + paramName)
      if paramValueStr:
        parameterValues[paramName] = float(parameterNode.GetParameter(cls.ID+"_"+paramName))
      else:
        # value not defined in parameter node, use the default
        paramScale = (0.01 if paramAttributes["unit"] == "%" else 1.0)
        value = paramAttributes["value"] * paramScale
        parameterValues[paramName] = value
    return parameterValues

class HarmonyDevice(CardiacDeviceBase):

  NAME="Harmony TCPV"
  ID="Harmony"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    scale = 2.0  # allow scaling animal device to humans
    PA = "Pulmonary artery side"
    PV = "Right ventricle side"
    return {
      "distalStraightRadiusMm": cls._genParameters("Distal straight radius", PA, 15.5, "mm", 5, 15.5 * scale, 0.1, 1),
      "distalStraightLengthMm":cls._genParameters("Distal straight length", PA, 8.9, "mm", 0, 17.7 * scale, 0.1, 1),
      "distalCurvedRadiusMm": cls._genParameters("Distal curved radius", PA, 15, "mm", 0, 15.5 * scale, 0.1, 1),
      "distalCurvedLengthMm": cls._genParameters("Distal curved length", PA, 8.8, "mm", 0, 17.7 * scale, 0.1, 1),
      "midRadiusMm": cls._genParameters("Middle radius", "", 11, "mm", 3, 11 * scale, 0.1, 1),
      "midLengthMm": cls._genParameters("Middle length", "", 17.7, "mm", 5, 17.7 * scale, 0.1, 1),
      "proximalCurvedRadiusMm": cls._genParameters("Proximal curved radius", PA, 21, "mm", 0, 21.5 * scale, 0.1, 1),
      "proximalCurvedLengthMm": cls._genParameters("Proximal curved length", PA, 8.8, "mm", 0, 17.7 * scale, 0.1, 1),
      "proximalStraightRadiusMm": cls._genParameters("Proximal straight radius", PV, 21.5, "mm", 10, 21.5 * scale, 0.1, 1),
      "proximalStraightLengthMm": cls._genParameters("Proximal straight length", PV, 8.9, "mm", 0, 17.7 * scale, 0.1, 1)
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -1.0}

  @classmethod
  def getSegments(cls):
    return ['distal', 'middle', 'proximal']

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    import math

    curvedSectionNumberOfPoints = 7
    curvedSegmentSlope = 2.0

    points = vtk.vtkPoints()

    if segment is None or segment == 'distal' or segment == "whole":

      if not openSegment:  # add a point at center, to make closed model
        points.InsertNextPoint(0, 0, -params['distalStraightLengthMm'] - params['distalCurvedLengthMm'] - params[
          'midLengthMm'] * 0.5)

      points.InsertNextPoint(params['distalStraightRadiusMm'], 0,
                             -params['distalStraightLengthMm'] - params['distalCurvedLengthMm'] - params[
                               'midLengthMm'] * 0.5)

      curvedSectionStartX = params['midRadiusMm']
      curvedSectionStartZ = -params['distalCurvedLengthMm'] - params['midLengthMm'] * 0.5
      radiusScale = (params['distalCurvedRadiusMm'] - params['midRadiusMm']) / (
            math.tanh(0.5 * curvedSegmentSlope) - math.tanh(-0.5 * curvedSegmentSlope))
      for pointIndex in range(0, curvedSectionNumberOfPoints - 1):
        normalizedPos = float(pointIndex) / float(curvedSectionNumberOfPoints - 1)  # goes from 0 to 1
        x = curvedSectionStartX + radiusScale * (
              math.tanh((0.5 - normalizedPos) * curvedSegmentSlope) - math.tanh(-0.5 * curvedSegmentSlope))
        z = curvedSectionStartZ + normalizedPos * params['distalCurvedLengthMm']
        points.InsertNextPoint(x, 0, z)
      points.InsertNextPoint(params['midRadiusMm'], 0, -params['midLengthMm'] * 0.5)

    if (segment == "distal" or segment == "middle") and openSegment == False:  # add a point at center, to make closed model
      points.InsertNextPoint(0, 0, -params['midLengthMm'] * 0.5)

    if segment == "middle":  # whole models should only contain one copy of these point
      points.InsertNextPoint(params['midRadiusMm'], 0, -params['midLengthMm'] * 0.5)
      points.InsertNextPoint(params['midRadiusMm'], 0, +params['midLengthMm'] * 0.5)

    if (segment == "middle" or segment == "proximal") and openSegment == False:  # add a point at center, to make closed model
      points.InsertNextPoint(0, 0, +params['midLengthMm'] * 0.5)

    if segment is None or segment == "proximal" or segment == "whole":
      points.InsertNextPoint(params['midRadiusMm'], 0,
                             +params['midLengthMm'] * 0.5)  # TODO: check if point duplication is not an issue

      curvedSectionStartX = params['midRadiusMm']
      curvedSectionStartZ = params['midLengthMm'] * 0.5
      radiusScale = (params['proximalCurvedRadiusMm'] - params['midRadiusMm']) / (
            math.tanh(0.5 * curvedSegmentSlope) - math.tanh(-0.5 * curvedSegmentSlope))
      for pointIndex in range(1, curvedSectionNumberOfPoints):
        normalizedPos = float(pointIndex) / float(curvedSectionNumberOfPoints - 1)  # goes from 0 to 1
        x = curvedSectionStartX + radiusScale * (
              math.tanh((normalizedPos - 0.5) * curvedSegmentSlope) - math.tanh(-0.5 * curvedSegmentSlope))
        z = curvedSectionStartZ + normalizedPos * params['proximalCurvedLengthMm']
        points.InsertNextPoint(x, 0, z)

      points.InsertNextPoint(params['proximalStraightRadiusMm'], 0,
                             params['midLengthMm'] * 0.5 + params['proximalCurvedLengthMm'] + params[
                               'proximalStraightLengthMm'])

      if segment is not None and openSegment == False:  # add a point at center, to make closed model
        points.InsertNextPoint(0, 0, params['midLengthMm'] * 0.5 + params['proximalCurvedLengthMm'] + params[
          'proximalStraightLengthMm'])

    return points


class CylinderDevice(CardiacDeviceBase):

  NAME = "Cylinder valve/stent"
  ID = "Cylinder"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    # Use an OrderedDict to display sliders in the order we define them here
    return collections.OrderedDict([
      ("expansionPercent", cls._genParameters("Expansion", "100% means expanded, 0% means crimped", 100, "%", 0, 100, 1, 10)),
      ("expandedDiameterMm", cls._genParameters("Expanded diameter", "", 22.4, "mm", 0, 60, 0.1, 1)),
      ("expandedLengthMm", cls._genParameters("Expanded length", "", 24, "mm", 0, 100, 0.1, 1)),
      ("crimpedDiameterMm", cls._genParameters("Crimped diameter", "", 7, "mm", 0, 60, 0.1, 1)),
      ("crimpedLengthMm", cls._genParameters("Crimped length", "", 32, "mm", 0, 100, 0.1, 1)),
      ("anchorPositionPercent", cls._genParameters("Anchor position", "Defines what point of the device remains in the same position as it expands/contracts", 0, "%", 0, 100, 1, 10))
      ])

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    lengthMm = params['crimpedLengthMm'] + params['expansionPercent'] * (params['expandedLengthMm']-params['crimpedLengthMm'])
    radiusMm = (params['crimpedDiameterMm'] + params['expansionPercent'] * (params['expandedDiameterMm']-params['crimpedDiameterMm'])) / 2.0
    print("Expansion = {0}, actual diameter = {1}, length = {2}".format(params['expansionPercent'], radiusMm * 2.0, lengthMm))
    origin = -lengthMm * params['anchorPositionPercent']
    points = vtk.vtkPoints()
    points.InsertNextPoint(radiusMm, 0, origin+lengthMm * 0.00)
    points.InsertNextPoint(radiusMm, 0, origin+lengthMm * 0.25)
    points.InsertNextPoint(radiusMm, 0, origin+lengthMm * 0.50)
    points.InsertNextPoint(radiusMm, 0, origin+lengthMm * 0.75)
    points.InsertNextPoint(radiusMm, 0, origin+lengthMm * 1.00)
    return points
