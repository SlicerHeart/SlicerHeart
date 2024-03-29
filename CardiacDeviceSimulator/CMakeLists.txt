#-----------------------------------------------------------------------------
set(MODULE_NAME CardiacDeviceSimulator)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  CardiacDeviceSimulatorUtils/__init__.py
  CardiacDeviceSimulatorUtils/CardiacDeviceSubjectHierarchyPlugin.py
  CardiacDeviceSimulatorUtils/DeviceCompressionQuantificationWidget.py
  CardiacDeviceSimulatorUtils/DeviceCompressionQuantificationWidget.py
  CardiacDeviceSimulatorUtils/DeviceDataTreeWidget.py
  CardiacDeviceSimulatorUtils/DeviceDeformationWidget.py
  CardiacDeviceSimulatorUtils/DevicePositioningWidget.py
  CardiacDeviceSimulatorUtils/devices.py
  CardiacDeviceSimulatorUtils/DeviceSelectorWidget.py
  CardiacDeviceSimulatorUtils/widgethelper.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/Icons/Cylinder.png
  Resources/Icons/Harmony.png
  Resources/Icons/CylinderValveWithSkirt.png
  Resources/Presets/Harmony.csv
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )

#-----------------------------------------------------------------------------
if(BUILD_TESTING)

  # Register the unittest subclass in the main script as a ctest.
  # Note that the test will also be available at runtime.
  slicer_add_python_unittest(SCRIPT ${MODULE_NAME}.py)

  # Additional build-time testing
  add_subdirectory(Testing)
endif()
