import ctk

import slicer
from slicer.ScriptedLoadableModule import *

from CardiacDeviceSimulator import CardiacDeviceSimulatorWidget
from AsdVsdDevices.devices import *


#
# AsdVsdDeviceSimulator
#

class AsdVsdDeviceSimulator(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  deviceClasses = [SeptalOccluder, MultiFenestratedSeptalOccluder,
                   DuctOccluder, DuctOccluderII, MuscularVSDOccluder, CustomDevice]

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ASD/VSD Device Simulator"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["CardiacDeviceSimulator"]
    self.parent.contributors = ["Christian Herz (CHOP), Andras Lasso (PerkLab, Queen's University), Matt Jolley (CHOP/UPenn)"]
    self.parent.helpText = """
    Evaluate devices for ASD/VSD treatment.
    """
    self.parent.acknowledgementText = """
    This file was originally developed by Christian Herz (CHOP) and Andras Lasso (PerkLab, Queen's University).
    """

    try:
      from CardiacDeviceSimulator import CardiacDeviceSimulatorWidget
      for deviceClass in AsdVsdDeviceSimulator.deviceClasses:
        CardiacDeviceSimulatorWidget.registerDevice(deviceClass)
    except ImportError:
      pass

#
# AsdVsdDeviceSimulatorWidget
#

class AsdVsdDeviceSimulatorWidget(CardiacDeviceSimulatorWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  DEVICE_POSITIONING_NEEDED = True
  DEVICE_DEFORMATION_NEEDED = False
  DEVICE_QUANTIFICATION_NEEDED = False

  def __init__(self, parent=None, deviceClasses=None):
    CardiacDeviceSimulatorWidget.__init__(self, parent, AsdVsdDeviceSimulator.deviceClasses)
    self.logic.moduleName = "AsdVsdDeviceSimulator"

  def setup(self):
    CardiacDeviceSimulatorWidget.setup(self)
    if not self.setupSuccessful:
      return

    # Customize device positioning section
    self.devicePositioningWidget.vesselGroupBox.hide()
    self.devicePositioningWidget.centerlineGroupBox.hide()
    # Expand translate and rotate sections
    self.devicePositioningWidget.devicePositioningPositionSliderWidget.findChildren(ctk.ctkCollapsibleGroupBox)[0].setChecked(True)
    self.devicePositioningWidget.devicePositioningOrientationSliderWidget.findChildren(ctk.ctkCollapsibleGroupBox)[0].setChecked(True)