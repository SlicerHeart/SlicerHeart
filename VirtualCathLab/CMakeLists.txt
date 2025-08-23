#-----------------------------------------------------------------------------
set(MODULE_NAME VirtualCathLab)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  VirtualCathLabDevices/__init__.py
  VirtualCathLabDevices/devices.py
  VirtualCathLabLib/__init__.py
  VirtualCathLabLib/PositionerAngleViewWidget.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/UI/${MODULE_NAME}.ui
  Resources/Icons/${MODULE_NAME}.png
  Resources/Icons/GenericFluoro.png
  Resources/Icons/GenericBiplaneFluoro.png
  Resources/CArmModel.arc
  Resources/Presets/Fluoro.csv
  Resources/Presets/GenericBiplaneFluoro.csv
  Resources/Presets/GenericFluoro.csv
  Resources/Transforms/frontal_camera_to_frontal_source.h5
  Resources/Transforms/lateral_camera_to_lateral_source.h5
  Resources/VolumeRendering/FluoroRenderingPreset_01.vp
  Resources/VolumeRendering/FluoroRenderingPreset_02.vp
  Resources/VolumeRendering/FluoroRenderingPreset_03.vp
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
