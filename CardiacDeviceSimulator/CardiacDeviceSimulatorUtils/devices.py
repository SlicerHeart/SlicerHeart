import os
import qt, vtk

import collections
from collections import OrderedDict


class CardiacDeviceBase(object):

  DEVICE_CLASS_MODIFIED_EVENT = 20000
  DEVICE_PARAMETER_VALUE_MODIFIED_EVENT = 20001
  DEVICE_PROFILE_MODIFIED_EVENT = 20002
  QUANTIFICATION_RESULT_UPDATED_EVENT = 20003

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
  def _genParameters(name, info, value, unit, minimum, maximum, singleStep, pageStep, decimals=2, visible=True):
    return {"name": name, "info": info, "value": value, "unit": unit, "minimum": minimum, "maximum": maximum,
            "singleStep": singleStep, "pageStep": pageStep, "decimals": decimals, "visible": visible}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True): #segment: one of 'distal', 'middle', 'proximal', 'whole'
    raise NotImplementedError

  @classmethod
  def updateModel(cls, modelNode, parameterNode):
    """Most devices provides only a profile (via getProfilePoints) and model is computed from rotational sweep
    of these points. However, a device can generate a model of arbitrary shape by overriding this method."""
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


class CylinderSkirtValveDevice(CardiacDeviceBase):

  NAME = "Cylinder valve with skirt"
  ID = "CylinderValveWithSkirt"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {
      "radiusMm": cls._genParameters("Radius", "Base radius", 15, "mm", 0, 30, 0.1, 1),
      "lengthMm": cls._genParameters("Length", "Total length", 30, "mm", 0, 100, 0.1, 1),
      'skirtLengthFraction': cls._genParameters("Skirt length", "Percentage of skirt length relative to total length",
                                                20, "%", 0, 200, 1, 5),
      'skirtRadiusFraction': cls._genParameters("Skirt radius",  "Percentage of radius of skirt compared to the base "
                                                                 "radius", 20, "%", 0, 200, 1, 5)
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -1.0}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    lengthMm = params['lengthMm']
    radiusMm = params['radiusMm']
    skirtLengthFraction = params['skirtLengthFraction']
    skirtRadiusFraction = params['skirtRadiusFraction']

    points = vtk.vtkPoints()

    # Skirt
    points.InsertNextPoint(radiusMm * (1.0 + skirtRadiusFraction), 0, -lengthMm / 2  + lengthMm * skirtLengthFraction)

    # Cylinder
    points.InsertNextPoint(radiusMm, 0, - lengthMm / 2)
    points.InsertNextPoint(radiusMm, 0, - lengthMm / 4)
    points.InsertNextPoint(radiusMm, 0, 0)
    points.InsertNextPoint(radiusMm, 0, lengthMm / 4)
    points.InsertNextPoint(radiusMm, 0, lengthMm / 2)

    return points