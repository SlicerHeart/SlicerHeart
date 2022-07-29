#-----------------------------------------------------------------------------
set(MODULE_NAME CardiacDeviceSimulatorExtender)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  CardiacSimulatorDevices/__init__
  CardiacSimulatorDevices/devices
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  WITH_GENERIC_TESTS
  )