#-----------------------------------------------------------------------------
set(MODULE_NAME ValveQuantificationExtender)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  ValveQuantificationPresets/__init__
  ValveQuantificationPresets/MeasurementPresetLavv
  ValveQuantificationPresets/MeasurementPresetPhaseCompare
  )

set(MODULE_PYTHON_RESOURCES
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )