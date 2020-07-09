set(MODULE_NAME ConformalTextureMapping)

#-----------------------------------------------------------------------------
set(MODULE_INCLUDE_DIRECTORIES
  )

set(MODULE_SRCS
  )

set(MODULE_TARGET_LIBRARIES
  )

#-----------------------------------------------------------------------------
add_custom_target(${MODULE_NAME} ALL
                  COMMAND "${CMAKE_COMMAND}" -E copy "${CMAKE_CURRENT_SOURCE_DIR}/${MODULE_NAME}.xml" "${SlicerExecutionModel_DEFAULT_CLI_RUNTIME_OUTPUT_DIRECTORY}/$<CONFIG>"
                  DEPENDS lscm
                  VERBATIM
                  )

add_custom_command(TARGET ${MODULE_NAME} POST_BUILD
                   COMMAND "${CMAKE_COMMAND}" -E copy "${CMAKE_CURRENT_SOURCE_DIR}/${MODULE_NAME}.xml" "${SlicerExecutionModel_DEFAULT_CLI_RUNTIME_OUTPUT_DIRECTORY}/$<CONFIG>"
                   COMMENT "Copying ${MODULE_NAME}.xml file to ${SlicerExecutionModel_DEFAULT_CLI_RUNTIME_OUTPUT_DIRECTORY}" 
                   DEPENDS lscm
                   VERBATIM
                   )

install(
  FILES
    "${SlicerExecutionModel_DEFAULT_CLI_RUNTIME_OUTPUT_DIRECTORY}/$<CONFIG>/${MODULE_NAME}${CMAKE_EXECUTABLE_SUFFIX}"
    ${CMAKE_CURRENT_SOURCE_DIR}/${MODULE_NAME}.xml
  DESTINATION ${Slicer_INSTALL_CLIMODULES_BIN_DIR}
  COMPONENT Runtime
  )

#-----------------------------------------------------------------------------
if(BUILD_TESTING)
  # add_subdirectory(Testing)
endif()
