import vtk
import os
import math
from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase


class SeptalOccluder(CardiacDeviceBase):

  NAME = "Septal Occluder"
  ID = "SeptalOccluder"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {
      'waistDiameterMm': cls._genParameters("Waist diameter", "Diameter of the narrowing between the two discs", 17,
                                            "mm", 4, 38, 1, 0),
      'rightDiameterMm': cls._genParameters("Right disc diameter", "Diameter of right atrial disc", 27, "mm", 12, 48, 1,
                                            0),
      'leftDiameterMm': cls._genParameters("Left disc diameter", "Diameter of the left atrial disc", 31, "mm", 16, 54,
                                           1, 0),
      'waistLengthMm': cls._genParameters("Waist length", "Length of the narrowing between the two discs", 4, "mm", 3, 4,
                                          0.1, 0),

      'lengthMm': cls._genParameters("Length", "Total length", 12, "mm", 12, 16, 1, 0),
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -0.70}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    lengthMm = params['lengthMm']
    radiusMm = params['leftDiameterMm'] / 2.0
    secondaryRadiusMm = params['rightDiameterMm'] / 2.0
    halfNarrowingLength = params['waistLengthMm'] / 2.0
    narrowingRadiusMm = params['waistDiameterMm'] / 2.0

    points = vtk.vtkPoints()

    halfLength = lengthMm * 0.5

    points.InsertNextPoint(0, 0, -halfLength)
    points.InsertNextPoint(radiusMm - (lengthMm*0.5 * math.cos(45) / math.sin(45)) , 0, -halfLength)
    points.InsertNextPoint(radiusMm, 0, -halfNarrowingLength + (halfLength-halfNarrowingLength)/2)

    points.InsertNextPoint(narrowingRadiusMm, 0, -halfNarrowingLength + (halfLength-halfNarrowingLength)/2)
    points.InsertNextPoint(narrowingRadiusMm, 0, halfNarrowingLength + (halfLength-halfNarrowingLength)/2)

    points.InsertNextPoint(secondaryRadiusMm, 0, halfNarrowingLength + (halfLength-halfNarrowingLength)/2)
    points.InsertNextPoint(secondaryRadiusMm, 0, halfLength)
    points.InsertNextPoint(0, 0, halfLength)

    return points


class MultiFenestratedSeptalOccluder(CardiacDeviceBase):

  NAME = "Multi Fenestrated Septal Occluder"
  ID = "MultiFenestratedSeptalOccluder"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {
      'diameterMm': cls._genParameters("Diameter", "Diameter of the discs", 35, "mm", 18, 35, 1, 0),
      # 'lengthMm': cls._genParameters("Length", "Total length", 10, "mm", 12, 16, 4, 0),
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -0.70}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    radiusMm = params['diameterMm'] / 2.0
    lengthMm = radiusMm * 2/3
    halfNarrowingLength = 1.5
    narrowingRadiusMm = 2.0  # NB: guessed the radius

    points = vtk.vtkPoints()

    halfLength = lengthMm * 0.5

    points.InsertNextPoint(0, 0, -halfLength)
    points.InsertNextPoint(radiusMm - (lengthMm * 0.5 * math.cos(45) / math.sin(45)), 0, -halfLength + lengthMm*1/5)
    points.InsertNextPoint(radiusMm, 0, -halfNarrowingLength + (halfLength-halfNarrowingLength)/2)

    points.InsertNextPoint(narrowingRadiusMm, 0, -halfNarrowingLength + (halfLength-halfNarrowingLength)/2)
    points.InsertNextPoint(narrowingRadiusMm, 0, halfNarrowingLength + (halfLength-halfNarrowingLength)/2)

    points.InsertNextPoint(radiusMm, 0, halfNarrowingLength + (halfLength-halfNarrowingLength)/2)
    points.InsertNextPoint(radiusMm, 0, halfLength-lengthMm*1/10)
    points.InsertNextPoint(0, 0, halfLength)

    return points


class DuctOccluder(CardiacDeviceBase):

  NAME = "Duct Occluder"
  ID = "DuctOccluder"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {
      'aortaDiameterMm': cls._genParameters("Aorta diameter", "Device diameter at descending aorta", 8, "mm", 5, 12, 1, 0),
      'pulmonaryArteryDiameterMm': cls._genParameters("PA diameter", "Device diameter at pulmonary artery", 6, "mm", 4, 10, 1, 0),
      'diameterMm': cls._genParameters("Retention skirt diameter", "Diameter of the retention skirt", 12, "mm", 9, 18, 1, 0),
      'lengthMm': cls._genParameters("Device length", "Device length", 7, "mm", 5, 8, 1, 0)
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -0.70}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):

    radiusMm = params['diameterMm'] / 2.0
    aortaRadiusMm = params['aortaDiameterMm'] / 2.0
    paRadiusMm = params['pulmonaryArteryDiameterMm'] / 2.0
    lengthMm = params['lengthMm']

    points = vtk.vtkPoints()

    halfLength = lengthMm * 0.5

    points.InsertNextPoint(0, 0, -halfLength)
    points.InsertNextPoint(radiusMm, 0, -halfLength)
    points.InsertNextPoint(radiusMm, 0, -halfLength + 0.10 * halfLength)
    points.InsertNextPoint(aortaRadiusMm*1.1, 0, -halfLength + 0.20 * halfLength)

    points.InsertNextPoint(aortaRadiusMm, 0, 0)

    points.InsertNextPoint(aortaRadiusMm, 0, halfLength*4/5)
    points.InsertNextPoint(paRadiusMm, 0, halfLength)
    points.InsertNextPoint(paRadiusMm-(aortaRadiusMm-paRadiusMm), 0, halfLength*0.1)
    points.InsertNextPoint(0, 0, halfLength*0.1)
    return points


class MuscularVSDOccluder(CardiacDeviceBase):

  NAME = "Muscular VSD Occluder"
  ID = "MuscularVsdOccluder"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {
      'innerDiameterMm': cls._genParameters("Inner diameter", "Device sz/ waist diameter", 8, "mm", 5, 12, 1, 0),
      'outerDiameterMm': cls._genParameters("Skirt diameter", "Disc diameter", 12, "mm", 9, 18, 1, 0),
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -0.70}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):

    radiusMm = params['outerDiameterMm'] / 2.0
    innerRadiusMm = params['innerDiameterMm'] / 2.0
    lengthMm = 7.0

    points = vtk.vtkPoints()

    halfLength = lengthMm * 0.5

    points.InsertNextPoint(0, 0, -halfLength)
    points.InsertNextPoint(radiusMm, 0, -halfLength)
    points.InsertNextPoint(radiusMm, 0, -halfLength + 0.10 * halfLength)
    points.InsertNextPoint(innerRadiusMm, 0, -halfLength + 0.10 * halfLength)

    points.InsertNextPoint(innerRadiusMm, 0, 0)

    points.InsertNextPoint(innerRadiusMm, 0, halfLength - 0.10 * halfLength)
    points.InsertNextPoint(radiusMm, 0, halfLength - 0.10 * halfLength)
    points.InsertNextPoint(radiusMm, 0, halfLength)
    points.InsertNextPoint(innerRadiusMm, 0, halfLength)

    points.InsertNextPoint(innerRadiusMm*0.8, 0, halfLength*0.1)
    points.InsertNextPoint(0, 0, 0)
    return points


class DuctOccluderII(CardiacDeviceBase):

  NAME = "Duct Occluder II"
  ID = "DuctOccluder2"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {
      'waistDiameterMm': cls._genParameters("Waist diameter", "Waist diameter", 5, "mm", 3, 6, 1, 0),
      'lengthMm': cls._genParameters("Device length", "Device length", 4, "mm", 4, 6, 1, 0),
      'discDiameterMm': cls._genParameters("Skirt diameter", "Disc diameter", 11, "mm", 9, 12, 1, 0),
    }

  @classmethod
  def getInternalParameters(cls):
    return {'interpolationSmoothness': -0.70}

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):

    radiusMm = params['discDiameterMm'] / 2.0
    waistRadiusMm = params['waistDiameterMm'] / 2.0
    lengthMm = params['lengthMm']

    points = vtk.vtkPoints()

    halfLength = lengthMm * 0.5
    discWidth = (radiusMm - waistRadiusMm) / math.tan(45)

    points.InsertNextPoint(0, 0, -halfLength)
    points.InsertNextPoint(waistRadiusMm, 0, -halfLength)
    points.InsertNextPoint(radiusMm, 0, -halfLength + discWidth)
    points.InsertNextPoint(waistRadiusMm, 0, -halfLength)

    points.InsertNextPoint(waistRadiusMm, 0, 0)

    points.InsertNextPoint(waistRadiusMm, 0, halfLength)
    points.InsertNextPoint(radiusMm, 0, halfLength - discWidth)
    points.InsertNextPoint(waistRadiusMm, 0, halfLength)
    points.InsertNextPoint(0, 0, halfLength)
    return points

class CustomDevice(CardiacDeviceBase):

  NAME = "Custom Device"
  ID = "CustomDevice"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {
      'lengthMm': cls._genParameters("Length", "Total length", 10, "mm", 0, 30, 0.1, 1),
      'diameterMm': cls._genParameters("Primary diameter", "Diameter of the primary disk", 30, "mm", 0, 60, 0.1, 1),
      'secondaryDiameterMm': cls._genParameters("Secondary diameter", "Diameter of secondary disk", 25, "mm", 0, 60, 0.1, 1),
      'waistLengthMm': cls._genParameters("Waist length", "Length of the narrowing between the two disks", 4, "mm", 0, 60, 0.1, 1),
      'narrowingTransitioningLengthFraction': cls._genParameters("Narrowing smoothness",
                                                                  "Percentage of transitioning region length relative "
                                                                  "to total length", 10, "%", 0, 100, 1, 5),
      'waistDiameterMm': cls._genParameters("Waist diameter", "Diameter of the narrowing between the two disks", 15, "mm", 0, 60, 0.1, 1)
    }

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    lengthMm = params['lengthMm']
    radiusMm = params['diameterMm'] / 2.0
    secondaryRadiusMm = params['secondaryDiameterMm'] / 2.0
    halfNarrowingLength = params['waistLengthMm'] / 2.0
    narrowingTransitioningLengthFraction = params['narrowingTransitioningLengthFraction']
    narrowingRadiusMm = params['waistDiameterMm'] / 2.0

    points = vtk.vtkPoints()

    # radius of the model would be larger than the prescribed due to smoothing,
    # apply this scaling factor to make the radius of the model closer to what is prescribed
    radiusOvershoot = 1.16

    smoothingOffset = lengthMm * 0.5 * narrowingTransitioningLengthFraction
    halfLength = lengthMm * 0.5

    points.InsertNextPoint(0, 0, -halfLength)
    points.InsertNextPoint(radiusMm / radiusOvershoot, 0, -halfLength)
    points.InsertNextPoint(radiusMm / radiusOvershoot, 0, -halfNarrowingLength - smoothingOffset)

    points.InsertNextPoint(narrowingRadiusMm, 0, -halfNarrowingLength + smoothingOffset)
    points.InsertNextPoint(narrowingRadiusMm, 0, halfNarrowingLength - smoothingOffset)

    points.InsertNextPoint(secondaryRadiusMm / radiusOvershoot, 0, halfNarrowingLength + smoothingOffset)
    points.InsertNextPoint(secondaryRadiusMm / radiusOvershoot, 0, halfLength)
    points.InsertNextPoint(0, 0, halfLength)

    return points
