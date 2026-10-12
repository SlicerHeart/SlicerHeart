#-----------------------------------------------------------------------------
set(MODULE_NAME SimplifiedViewer)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/Icons/LayoutFourUpView.png
  Resources/Icons/LayoutConventionalView.png
  Resources/Icons/SeekFirst.svg
  Resources/Icons/SeekPrevious.svg
  Resources/Icons/SeekPlay.svg
  Resources/Icons/SeekNext.svg
  Resources/Icons/SeekLast.svg
  Resources/Icons/SeekLoop.svg
  Resources/Icons/Center.svg
  Resources/Icons/Crosshair.svg
  Resources/Icons/Folder.svg
  Resources/Icons/Fullscreen.svg
  Resources/Icons/FullscreenExit.svg
  Resources/Icons/Layouts.svg
  Resources/Icons/Measurements.svg
  Resources/Icons/SceneViews.svg
  Resources/Icons/SeekPause.svg
  Resources/Icons/Settings.svg
  Resources/Icons/SliceIntersections.svg
  Resources/Icons/Visibility.svg
  Resources/UI/${MODULE_NAME}.ui
  Resources/Stylesheet/${MODULE_NAME}.qss
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
