#-----------------------------------------------------------------------------
set(MODULE_NAME ValveClipDeviceSimulator)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  ValveClipDevices/__init__
  ValveClipDevices/devices.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/UI/${MODULE_NAME}.ui
  Resources/Icons/${MODULE_NAME}.png
  Resources/Icons/GenericValveClip.png
  Resources/Icons/MitraClipG4NT.png
  Resources/Icons/MitraClipG4NTW.png
  Resources/Icons/MitraClipG4XT.png
  Resources/Icons/MitraClipG4XTW.png
  Resources/Models/grasper.vtp
  Resources/Models/tip.vtp
  Resources/Models/G4NT_grippers.stl
  Resources/Models/G4NT_wing.stl
  Resources/Models/G4NTW_wing.stl
  Resources/Models/G4XT_grippers.stl
  Resources/Models/G4XT_wing.stl
  Resources/Models/G4XTW_wing.stl
  Resources/Models/Mitraclip_common_base.stl
  Resources/Models/Texture_FabricBurlapWhite.jpg
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
