#-----------------------------------------------------------------------------
set(MODULE_NAME AsdVsdDeviceSimulator)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  AsdVsdDevices/__init__
  AsdVsdDevices/devices
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/Icons/CustomDevice.png
  Resources/Icons/DuctOccluder.png
  Resources/Icons/DuctOccluder2.png
  Resources/Icons/MultiFenestratedSeptalOccluder.png
  Resources/Icons/MuscularVsdOccluder.png
  Resources/Icons/SeptalOccluder.png
  Resources/Presets/DuctOccluder.csv
  Resources/Presets/DuctOccluder2.csv
  Resources/Presets/MultiFenestratedSeptalOccluder.csv
  Resources/Presets/MuscularVsdOccluder.csv
  Resources/Presets/SeptalOccluder.csv
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
