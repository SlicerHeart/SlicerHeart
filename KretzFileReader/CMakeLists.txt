#-----------------------------------------------------------------------------
set(MODULE_NAME KretzFileReader)
set(MODULE_TITLE "Kretz File Reader")

string(TOUPPER ${MODULE_NAME} MODULE_NAME_UPPER)

#-----------------------------------------------------------------------------
add_subdirectory(Logic)

#-----------------------------------------------------------------------------
set(MODULE_EXPORT_DIRECTIVE "Q_SLICER_${MODULE_NAME_UPPER}_EXPORT")

# Additional includes - Current_{source,binary} and Slicer_{Libs,Base} already included
set(MODULE_INCLUDE_DIRECTORIES
  ${CMAKE_CURRENT_SOURCE_DIR}/Logic
  ${CMAKE_CURRENT_BINARY_DIR}/Logic
  )

set(MODULE_SRCS
  qSlicer${MODULE_NAME}Plugin.cxx
  qSlicer${MODULE_NAME}Plugin.h
  qSlicer${MODULE_NAME}PluginWidget.cxx
  qSlicer${MODULE_NAME}PluginWidget.h
  qSlicer${MODULE_NAME}Module.cxx
  qSlicer${MODULE_NAME}Module.h
  qSlicer${MODULE_NAME}OptionsWidget.cxx
  qSlicer${MODULE_NAME}OptionsWidget.h
  )

set(MODULE_MOC_SRCS
  qSlicer${MODULE_NAME}Plugin.h
  qSlicer${MODULE_NAME}PluginWidget.h
  qSlicer${MODULE_NAME}OptionsWidget.h
  qSlicer${MODULE_NAME}Module.h
  )

set(MODULE_UI_SRCS
  Resources/UI/qSlicer${MODULE_NAME}PluginWidget.ui
  Resources/UI/qSlicer${MODULE_NAME}OptionsWidget.ui
  )

set(MODULE_TARGET_LIBRARIES
  vtkSlicer${MODULE_NAME}Logic
  )

#-----------------------------------------------------------------------------
slicerMacroBuildLoadableModule(
  NAME ${MODULE_NAME}
  TITLE ${MODULE_TITLE}
  EXPORT_DIRECTIVE ${MODULE_EXPORT_DIRECTIVE}
  INCLUDE_DIRECTORIES ${MODULE_INCLUDE_DIRECTORIES}
  SRCS ${MODULE_SRCS}
  MOC_SRCS ${MODULE_MOC_SRCS}
  UI_SRCS ${MODULE_UI_SRCS}
  TARGET_LIBRARIES ${MODULE_TARGET_LIBRARIES}
  WITH_GENERIC_TESTS
  )

#-----------------------------------------------------------------------------
#if(BUILD_TESTING)
#  add_subdirectory(Testing)
#endif()
