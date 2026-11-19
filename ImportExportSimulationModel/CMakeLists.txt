#-----------------------------------------------------------------------------
set(MODULE_NAME ImportExportSimulationModel)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  ${MODULE_NAME}Lib/__init__
  ${MODULE_NAME}Lib/Units
  ${MODULE_NAME}Lib/MeshArrays
  ${MODULE_NAME}Lib/OperationMonitor
  ${MODULE_NAME}Lib/MeshConversion
  ${MODULE_NAME}Lib/MeshReduction
  ${MODULE_NAME}Lib/MeshReading
  ${MODULE_NAME}Lib/MeshWriting
  ${MODULE_NAME}Lib/ModelImport
  ${MODULE_NAME}Lib/WidgetUtils
  ${MODULE_NAME}Lib/ArrayInfoTable
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/UI/${MODULE_NAME}.ui
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
