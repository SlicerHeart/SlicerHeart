set(MODULE_NAME ConformalTextureMapping)

#-----------------------------------------------------------------------------

#
# SlicerExecutionModel
#
# find_package(SlicerExecutionModel REQUIRED)
# include(${SlicerExecutionModel_USE_FILE})

#
# LSCM
#
# find_package(LSCM REQUIRED)

#-----------------------------------------------------------------------------
set(MODULE_INCLUDE_DIRECTORIES
  )

set(MODULE_SRCS
  )

set(MODULE_TARGET_LIBRARIES
  )

#-----------------------------------------------------------------------------
# SEMMacroBuildCLI(
  # NAME ${MODULE_NAME}
  # TARGET_LIBRARIES ${MODULE_TARGET_LIBRARIES}
  # INCLUDE_DIRECTORIES ${MODULE_INCLUDE_DIRECTORIES}
  # ADDITIONAL_SRCS ${MODULE_SRCS}
  # RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_BIN_DIR}"
  # LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_LIB_DIR}"
  # ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_LIB_DIR}"
  # )

#-----------------------------------------------------------------------------
if(EXISTS "${CMAKE_BINARY_DIR}/../bin/Debug")
  set(LSCM_EXECUTABLE_PATH ${CMAKE_BINARY_DIR}/../bin/Debug/lscm.exe)
  set(ConformalTextureMapping_CLI_EXECUTABLE_PATH ${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_BIN_DIR}/Debug/${MODULE_NAME}.exe)
  set(ConformalTextureMapping_CLI_XML_PATH ${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_BIN_DIR}/Debug/${MODULE_NAME}.xml)
elseif(EXISTS "${CMAKE_BINARY_DIR}/../bin/Release")
  set(LSCM_EXECUTABLE_PATH ${CMAKE_BINARY_DIR}/../bin/Release/lscm.exe)
  set(ConformalTextureMapping_CLI_EXECUTABLE_PATH ${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_BIN_DIR}/Release/${MODULE_NAME}.exe)
  set(ConformalTextureMapping_CLI_XML_PATH ${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_BIN_DIR}/Release/${MODULE_NAME}.xml)
else()
  set(LSCM_EXECUTABLE_PATH ${CMAKE_BINARY_DIR}/../bin/lscm)
  set(ConformalTextureMapping_CLI_EXECUTABLE_PATH ${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_BIN_DIR}/${MODULE_NAME})
  set(ConformalTextureMapping_CLI_XML_PATH ${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_BIN_DIR}/${MODULE_NAME}.xml)
endif()

configure_file(
  ${LSCM_EXECUTABLE_PATH}
  ${ConformalTextureMapping_CLI_EXECUTABLE_PATH}
  COPYONLY)
configure_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/${MODULE_NAME}.xml
  ${ConformalTextureMapping_CLI_XML_PATH}
  COPYONLY)

install(
  FILES ${ConformalTextureMapping_CLI_EXECUTABLE_PATH}
  DESTINATION ${Slicer_INSTALL_CLIMODULES_BIN_DIR} COMPONENT Runtime)
install(
  FILES ${ConformalTextureMapping_CLI_XML_PATH}
  DESTINATION ${Slicer_INSTALL_CLIMODULES_BIN_DIR} COMPONENT Runtime)

#-----------------------------------------------------------------------------
if(BUILD_TESTING)
  # add_subdirectory(Testing)
endif()
