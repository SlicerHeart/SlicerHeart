#-----------------------------------------------------------------------------
set(MODULE_NAME FluoroSimulator)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  FluoroDevices/__init__.py
  FluoroDevices/devices.py
  FluoroSimulatorLib/__init__.py
  FluoroSimulatorLib/PositionerAngleViewWidget.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/UI/${MODULE_NAME}.ui
  Resources/Icons/${MODULE_NAME}.png
  Resources/Icons/GenericFluoro.png
  Resources/Icons/GenericBiplaneFluoro.png
  Resources/Models/lateral-arm-c.ply
  Resources/Models/lateral-detector.ply
  Resources/Models/lateral-arm-p.ply
  Resources/Models/frontal-arm-c.ply
  Resources/Models/frontal-detector.ply
  Resources/Models/frontal-arm-l.ply
  Resources/Models/frontal-arm-p.ply
  Resources/Models/table-base.ply
  Resources/Models/table-middle.ply
  Resources/Models/table-top.ply
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
