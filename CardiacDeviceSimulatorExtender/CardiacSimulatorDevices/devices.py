import vtk
import os
from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase


class FlaredStentDevice(CardiacDeviceBase):

  NAME = "Flared stent"
  ID = "FlaredStent"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    return {
      'lengthMm': cls._genParameters("Length", "Total length", 30, "mm", 0, 100, 0.1, 1),
      'radiusMm': cls._genParameters("Radius", "Base radius", 15, "mm", 0, 30, 0.1, 1),
      'narrowingLengthFraction': cls._genParameters("Narrowing length",
                                                    "Percentage of narrowing length relative to total length",
                                                    50, "%", 0, 100, 1, 5),
      'narrowingTransitioningLengthFraction': cls._genParameters("Narrowing smoothness",
                                                                 "Percentage of transitioning region length relative "
                                                                 "to total length", 30, "%", 0, 100, 1, 5),
      'narrowingRadiusFraction': cls._genParameters("Narrowing radius",
                                                    "Percentage of radius of narrowing compared to the base radius", 70,
                                                    "%", 0, 100, 1, 5)
    }

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    lengthMm = params['lengthMm']
    radiusMm = params['radiusMm']
    narrowingLengthFraction = params['narrowingLengthFraction']
    narrowingTransitioningLengthFraction = params['narrowingTransitioningLengthFraction']
    narrowingRadiusFraction = params['narrowingRadiusFraction']

    points = vtk.vtkPoints()

    smoothingOffset = lengthMm * 0.5 * narrowingTransitioningLengthFraction
    narrowingLength = lengthMm * narrowingLengthFraction
    halfLength = lengthMm * 0.5

    points.InsertNextPoint(radiusMm, 0, -halfLength)
    points.InsertNextPoint(radiusMm, 0, -halfLength + narrowingLength - smoothingOffset)

    points.InsertNextPoint(radiusMm * narrowingRadiusFraction, 0, -halfLength + narrowingLength + smoothingOffset)
    points.InsertNextPoint(radiusMm * narrowingRadiusFraction, 0, halfLength)
    return points


class TwoSidedFlaredStentDevice(FlaredStentDevice):

  NAME = "Two-sided flared stent"
  ID = "TwoSidedFlaredStent"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  @classmethod
  def getParameters(cls):
    params = super(TwoSidedFlaredStentDevice, cls).getParameters()
    params.update({"narrowingTransitioningLengthFraction": cls._genParameters("Narrowing smoothness",
                                                                              "Percentage of transitioning region "
                                                                              "length relative to total length", 20,
                                                                              "%", 0, 30, 1, 5)})
    return params

  @staticmethod
  def getProfilePoints(params, segment=None, openSegment=True):
    lengthMm = params['lengthMm']
    radiusMm = params['radiusMm']
    narrowingLengthFraction = params['narrowingLengthFraction']
    narrowingTransitioningLengthFraction = params['narrowingTransitioningLengthFraction']
    narrowingRadiusFraction = params['narrowingRadiusFraction']

    points = vtk.vtkPoints()

    smoothingOffset = lengthMm * 0.5 * narrowingTransitioningLengthFraction
    halfNarrowingLength = lengthMm * 0.5 * narrowingLengthFraction
    halfLength = lengthMm * 0.5

    points.InsertNextPoint(radiusMm, 0, -halfLength)
    points.InsertNextPoint(radiusMm, 0, -halfNarrowingLength - smoothingOffset)

    points.InsertNextPoint(radiusMm * narrowingRadiusFraction, 0, -halfNarrowingLength + smoothingOffset)
    points.InsertNextPoint(radiusMm * narrowingRadiusFraction, 0, halfNarrowingLength - smoothingOffset)

    points.InsertNextPoint(radiusMm, 0, halfNarrowingLength + smoothingOffset)
    points.InsertNextPoint(radiusMm, 0, halfLength)

    return points


class SeptalOccluder(CardiacDeviceBase):

  NAME = "Generic Septal occluder"
  ID = "GenericSeptalOccluder"
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
