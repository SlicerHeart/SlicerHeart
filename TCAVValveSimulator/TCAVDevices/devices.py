import vtk
import os
import math
from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase


class ApicalTetherPlug(CardiacDeviceBase):

  NAME = "Apical Tether Plug"
  ID = "ApicalTetherPlug"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {}

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -0.80}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    radiusMm = 5
    lengthMm = 2

    points = vtk.vtkPoints()

    halfLength = lengthMm * 0.5

    points.InsertNextPoint(0, 0, -halfLength)
    points.InsertNextPoint(radiusMm - (lengthMm * 0.5 * math.cos(45) / math.sin(45)), 0, -halfLength + lengthMm * 1 / 5)
    points.InsertNextPoint(radiusMm, 0, halfLength)
    points.InsertNextPoint(0, 0, halfLength)
    return points


class ApicalTether(CardiacDeviceBase):

  NAME = "Apical Tether"
  ID = "ApicalTether"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {
      # NB: comes in 13 different sizes
      "outerDiameterMm": cls._genParameters("Diameter", "Outer diameter", 30, "mm", 30, 43, 1.0, 1),
      "lengthMm": cls._genParameters("Length", "Total length", 10, "mm", 10, 30, 1.0, 1)
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -0.60}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    radiusMm = 10  # one size

    outerRadiusMm = params['outerDiameterMm'] / 2
    lengthMm = params['lengthMm']

    points = vtk.vtkPoints()

    # Skirt
    points.InsertNextPoint(outerRadiusMm, 0, -lengthMm / 2 - lengthMm * 0.2 - outerRadiusMm * 0.2)

    # Basket
    points.InsertNextPoint(radiusMm, 0, -lengthMm / 2)
    points.InsertNextPoint(radiusMm, 0, 0)
    points.InsertNextPoint(radiusMm, 0, lengthMm / 2)
    points.InsertNextPoint(radiusMm / 2, 0, lengthMm / 2 + lengthMm * 0.2)

    return points


class AngularWinglets(CardiacDeviceBase):

  NAME = "Angular Winglets"
  ID = "AngularWinglets"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    """ Inflow/outflow: 30 mm/36 mm;30 mm/40 mm; 33 mm/44 mm
    """
    return {
      "atrialWingletsAngleDeg": cls._genParameters("Atrial winglets angle", "Atrial winglets angle", 0, "deg", 0, 90, 1, 1),
      "inflowDiameterMm": cls._genParameters("Inflow diameter", "Inflow diameter", 15, "mm", 15, 33, 3.0, 1),
      "outflowDiameterMm": cls._genParameters("Outflow diameter", "Outflow diameter", 15, "mm", 15, 44, 4.0, 1),
      "lengthMm": cls._genParameters("Length", "Total length", 10, "mm", 5, 20, 1.0, 1) # TODO: need to check what's the actual length is
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -0.60}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    atrialWingletsAngleDeg = params['atrialWingletsAngleDeg']
    inflowRadiusMm = params['inflowDiameterMm'] / 2
    outflowRadiusMm = params['outflowDiameterMm'] / 2
    lengthMm = params['lengthMm']

    points = vtk.vtkPoints()

    wingletsLengthMm = outflowRadiusMm - inflowRadiusMm
    wingletRadiusMm = wingletsLengthMm * math.cos(math.radians(atrialWingletsAngleDeg))
    ventricularGraspersRadius = wingletsLengthMm * math.cos(math.radians(70))

    l = lengthMm / 2

    points.InsertNextPoint(inflowRadiusMm, 0, -l - wingletsLengthMm)
    points.InsertNextPoint(inflowRadiusMm, 0, -l)
    points.InsertNextPoint(inflowRadiusMm + wingletRadiusMm, 0,
                           -l - math.sqrt(wingletsLengthMm ** 2 - wingletRadiusMm ** 2))
    points.InsertNextPoint(inflowRadiusMm, 0, -l)
    points.InsertNextPoint(outflowRadiusMm, 0, l)

    # ventricular graspers

    points.InsertNextPoint(outflowRadiusMm, 0, l - l*0.1)
    points.InsertNextPoint(outflowRadiusMm + ventricularGraspersRadius, 0,
                           l - l*0.1  - math.sqrt(wingletsLengthMm ** 2 - ventricularGraspersRadius ** 2))

    return points


class RadialForce(CardiacDeviceBase):
  NAME = "Radial Force"
  ID = "RadialForce"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..", "Resources")

  @classmethod
  def getParameters(cls):
    """ 27 mm with 3 outer stent sizes(43, 46, and 50 mm)
    """
    return {
      "innerDiameterMm": cls._genParameters("Inner stent diameter", "Inner stent diameter", 15, "mm", 15, 27, 1.0, 1),
      "outerDiameterMm": cls._genParameters("Outer stent diameter", "Outer stent diameter", 15, "mm", 15, 50, 1.0, 1),
      "lengthMm": cls._genParameters("Length", "Total length", 15, "mm", 15, 20, 1.0, 1),
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -0.60}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    lengthMm = params['lengthMm']

    innerRadiusMm = params["innerDiameterMm"] / 2.0
    outerRadiusMm = params["outerDiameterMm"] / 2.0

    points = vtk.vtkPoints()

    points.InsertNextPoint(innerRadiusMm, 0, -lengthMm / 4)
    points.InsertNextPoint(innerRadiusMm, 0, 0)
    points.InsertNextPoint(innerRadiusMm, 0, lengthMm / 4)
    points.InsertNextPoint(innerRadiusMm, 0, lengthMm / 2)

    points.InsertNextPoint(outerRadiusMm, 0, lengthMm / 4)
    points.InsertNextPoint(outerRadiusMm, 0, 0)
    points.InsertNextPoint(outerRadiusMm, 0, -lengthMm / 4)

    points.InsertNextPoint(outerRadiusMm * 1.2, 0, -lengthMm * 0.5)
    points.InsertNextPoint(outerRadiusMm * 1.2, 0, -lengthMm * 0.5)

    return points
