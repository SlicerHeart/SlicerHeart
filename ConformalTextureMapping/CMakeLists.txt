set(MODULE_NAME ConformalTextureMapping)

#-----------------------------------------------------------------------------
# On non-Windows platforms, do not use $<CONFIG> subfolder
if (WIN32)
  # Copy module XML file to module directory
  add_custom_target(${MODULE_NAME} ALL
    COMMAND "${CMAKE_COMMAND}" -E copy
      "${CMAKE_CURRENT_SOURCE_DIR}/${MODULE_NAME}.xml"
      "${SlicerExecutionModel_DEFAULT_CLI_RUNTIME_OUTPUT_DIRECTORY}/$<CONFIG>/${MODULE_NAME}.xml"
      VERBATIM
    )
  # Add ConformalTextureMapping executable and xml to the install package
  install(
    FILES
      "${SlicerExecutionModel_DEFAULT_CLI_RUNTIME_OUTPUT_DIRECTORY}/$<CONFIG>/${MODULE_NAME}${CMAKE_EXECUTABLE_SUFFIX}"
      ${CMAKE_CURRENT_SOURCE_DIR}/${MODULE_NAME}.xml
    DESTINATION ${Slicer_INSTALL_CLIMODULES_BIN_DIR}
    COMPONENT Runtime
    )
else()
  # Copy module XML file to module directory
  add_custom_target(${MODULE_NAME} ALL
    COMMAND "${CMAKE_COMMAND}" -E copy
      "${CMAKE_CURRENT_SOURCE_DIR}/${MODULE_NAME}.xml"
      "${SlicerExecutionModel_DEFAULT_CLI_RUNTIME_OUTPUT_DIRECTORY}/${MODULE_NAME}.xml"
      VERBATIM
    )
  # Add ConformalTextureMapping executable and xml to the install package
  install(
    FILES
      ${CMAKE_CURRENT_SOURCE_DIR}/${MODULE_NAME}.xml
    DESTINATION ${Slicer_INSTALL_CLIMODULES_BIN_DIR}
    COMPONENT Runtime
    )

  install(
    PROGRAMS
      "${SlicerExecutionModel_DEFAULT_CLI_RUNTIME_OUTPUT_DIRECTORY}/${MODULE_NAME}${CMAKE_EXECUTABLE_SUFFIX}"
    DESTINATION ${Slicer_INSTALL_CLIMODULES_BIN_DIR}
    COMPONENT Runtime
    )
endif()

#-----------------------------------------------------------------------------
if(BUILD_TESTING)
  # add_subdirectory(Testing)
endif()
