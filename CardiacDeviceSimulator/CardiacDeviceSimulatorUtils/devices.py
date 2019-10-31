import qt, ctk, vtk
from .helpers import UIHelper

import collections

class CardiacDeviceWidget(ctk.ctkCollapsibleButton, UIHelper):

  def __init__(self, deviceClass, logic, updateCallback=None, parent=None):
    ctk.ctkCollapsibleButton.__init__(self, parent)
    self.deviceClass = deviceClass
    self.logic = logic
    self._updateCB = updateCallback
    self.setup()
    self.destroyed.connect(self._onAboutToBeDestroyed)

  def setup(self):
    self.setLayout(qt.QFormLayout(self))
    self._addSliders()
    self.text = self.deviceClass.NAME
    self.collapsed = True

    self.logic.modelInfo[self.deviceClass.NAME] = self.deviceClass.getModelInfo()
    self.updateModelParametersFromGUI()

  def _onAboutToBeDestroyed(self, obj):
    obj.destroyed.disconnect(self._onAboutToBeDestroyed)

  def updateModelParametersFromGUI(self):
    params = {
      parameter:getattr(self, "{}SliderWidget".format(parameter)).value*(0.01 if attributes["unit"]=="%" else 1)
        for parameter, attributes in self.deviceClass.getParameters().items()
    }
    self.logic.setModelParameters(self.deviceClass.NAME, params)

    if self._updateCB:
      self._updateCB()

  def updateGUIFromModelParameters(self):
    modelParameters = self.logic.getModelParameters(self.deviceClass.NAME)
    self.setParameters(modelParameters)

  def setParameters(self, modelParameters):
    for paramName, paramAttributes in self.deviceClass.getParameters().items():
      sliderWidget = getattr(self, "{}SliderWidget".format(paramName))
      paramScale = (0.01 if paramAttributes["unit"] == "%" else 1.0)
      if not hasattr(modelParameters, paramName):
        continue
      paramValue = modelParameters[paramName]
      wasBlocked = sliderWidget.blockSignals(True)
      sliderWidget.value = paramValue * paramScale
      sliderWidget.blockSignals(wasBlocked)

  def _addSliders(self):
    for paramName, paramAttributes in self.deviceClass.getParameters().items():
      setattr(self, "{}SliderWidget".format(paramName), self.addSlider(paramAttributes, self.layout(), self.updateModelParametersFromGUI))




class CardiacDeviceBase(object):

  NAME=None

  @classmethod
  def getParameters(cls):
    raise NotImplementedError

  @classmethod
  def getModelInfo(cls):
    return {'getProfilePointsMethod': cls.getProfilePoints,
            'segments': [], 'interpolationSmoothness': 0, 'parameters': {}}

  @staticmethod
  def _genParameters(name, info, value, unit, minimum, maximum, singleStep, pageStep, decimals=2):
    return {"name": name, "info": info, "value": value, "unit": unit, "minimum": minimum, "maximum": maximum,
            "singleStep": singleStep, "pageStep": pageStep, "decimals": decimals}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True): #segment: one of 'distal', 'middle', 'proximal', 'whole'
    raise NotImplementedError


class HarmonyDevice(CardiacDeviceBase):

  NAME="Harmony TCPV"

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
  def getModelInfo(cls):
    return {'getProfilePointsMethod': cls.getProfilePoints,
            'segments': ['distal', 'middle', 'proximal'],
            'interpolationSmoothness': -1.0, 'parameters': {}}

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
