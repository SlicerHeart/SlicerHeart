#-----------------------------------------------------------------------------
set(MODULE_NAME ValveQuantification)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  ValveQuantificationLib/__init__
  ValveQuantificationLib/MeasurementPreset
  ValveQuantificationLib/MeasurementPresetGenericValve
  ValveQuantificationLib/MeasurementPresetMitralValve
  ValveQuantificationLib/MeasurementPresetTricuspidValve
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/MeasurementPreset/MitralValve.html
  Resources/MeasurementPreset/MitralValve.png
  Resources/MeasurementPreset/TricuspidValve.html
  Resources/MeasurementPreset/TricuspidValve.png
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
