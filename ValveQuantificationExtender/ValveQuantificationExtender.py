class ValveQuantificationExtender:
  """
  This class is the 'hook' for slicer to detect and recognize the plugin
  as a loadable scripted module
  """

  def __init__(self, parent):
    parent.title = "Valve Quantification Extender"
    parent.categories = ["Cardiac"]
    parent.dependencies = ["ValveQuantification"]
    parent.contributors = ["Christian Herz (CHOP), Andras Lasso (PerkLab), Matt Jolley (UPenn)"]
    parent.hidden = True
    parent.helpText = """
    Private models related to cardiac procedures.
    """
    parent.acknowledgementText = """
    This file was originally developed by Christian Herz (CHOP).
    """

    try:
      from ValveQuantification import ValveQuantificationLogic
      import ValveQuantificationPresets
      ValveQuantificationLogic.registerPreset(ValveQuantificationPresets.MeasurementPresetLavv)
      ValveQuantificationLogic.registerPreset(ValveQuantificationPresets.MeasurementPresetPhaseCompare)
    except ImportError as exc:
      import logging
      logging.error("{}: {}".format(parent.title, exc))