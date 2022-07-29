class CardiacDeviceSimulatorExtender:
  """
  This class is the 'hook' for slicer to detect and recognize the plugin
  as a loadable scripted module
  """

  def __init__(self, parent):
    parent.title = "Cardiac device simulator extender"
    parent.categories = ["Cardiac"]
    parent.dependencies = ["CardiacDeviceSimulator"]
    parent.contributors = ["Christian Herz (CHOP), Andras Lasso (PerkLab), Matt Jolley (UPenn)"]
    parent.hidden = True
    parent.helpText = """
    Private models related to cardiac procedures.
    """
    parent.acknowledgementText = """
    This file was originally developed by Andras Lasso (PerkLab) and Christian Herz (CHOP).
    """

    try:
      from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase
      from CardiacDeviceSimulator import CardiacDeviceSimulatorWidget
      from CardiacSimulatorDevices.devices import FlaredStentDevice, TwoSidedFlaredStentDevice, SeptalOccluder
      CardiacDeviceSimulatorWidget.registerDevice(FlaredStentDevice)
      CardiacDeviceSimulatorWidget.registerDevice(TwoSidedFlaredStentDevice)
      CardiacDeviceSimulatorWidget.registerDevice(SeptalOccluder)
    except ImportError:
      pass