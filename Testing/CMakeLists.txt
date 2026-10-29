#-----------------------------------------------------------------------------
# Regression check of real SlicerHeart scenes (see SceneRegression/README.md).
#
# The scenes are patient data and are not part of the repository. The test runs the scenes of the
# folder named by the SLICERHEART_SCENES_DIR environment variable at the time CTest runs, and is
# reported as skipped (not failed) when the variable is not set.
add_test(NAME py_SceneRegression
  COMMAND ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/SceneRegression/run_scene_regression.py
    --slicer ${Slicer_LAUNCHER_EXECUTABLE}
    --launcher-settings ${CMAKE_BINARY_DIR}/AdditionalLauncherSettings.ini
    --module-paths
      ${CMAKE_BINARY_DIR}/${Slicer_QTSCRIPTEDMODULES_LIB_DIR}
      ${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_LIB_DIR}
      ${CMAKE_BINARY_DIR}/${Slicer_QTLOADABLEMODULES_LIB_DIR}
  )
set_tests_properties(py_SceneRegression PROPERTIES
  SKIP_RETURN_CODE 77
  TIMEOUT 14400
  LABELS "SceneRegression"
  )

#-----------------------------------------------------------------------------
add_subdirectory(Python)
