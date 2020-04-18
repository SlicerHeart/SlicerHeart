project(vtkSlicer${MODULE_NAME}ModuleLogic)

set(KIT ${PROJECT_NAME})

set(${KIT}_EXPORT_DIRECTIVE "VTK_SLICER_${MODULE_NAME_UPPER}_MODULE_LOGIC_EXPORT")

set(${KIT}_INCLUDE_DIRECTORIES
  ${vtkSlicerSequencesModuleMRML_INCLUDE_DIRS}
  ${vtkSlicerSequencesModuleLogic_INCLUDE_DIRS}
  )

if(${Slicer_VERSION_MAJOR}.${Slicer_VERSION_MINOR} VERSION_LESS 4.11)
  list(APPEND ${KIT}_INCLUDE_DIRECTORIES
    ${vtkSlicerSequenceBrowserModuleMRML_INCLUDE_DIRS}
    ${vtkSlicerSequenceBrowserModuleLogic_INCLUDE_DIRS}
    )
endif()

set(${KIT}_SRCS
  vtkSlicer${MODULE_NAME}Logic.cxx
  vtkSlicer${MODULE_NAME}Logic.h
  )

set(${KIT}_TARGET_LIBRARIES
  ${ITK_LIBRARIES}
  vtkSlicerSequencesModuleMRML
  vtkSlicerSequencesModuleLogic
  )

if(${Slicer_VERSION_MAJOR}.${Slicer_VERSION_MINOR} VERSION_LESS 4.11)
  list(APPEND ${KIT}_TARGET_LIBRARIES
    vtkSlicerSequenceBrowserModuleMRML
    vtkSlicerSequenceBrowserModuleLogic
    )
endif()

#-----------------------------------------------------------------------------
SlicerMacroBuildModuleLogic(
  NAME ${KIT}
  EXPORT_DIRECTIVE ${${KIT}_EXPORT_DIRECTIVE}
  INCLUDE_DIRECTORIES ${${KIT}_INCLUDE_DIRECTORIES}
  SRCS ${${KIT}_SRCS}
  TARGET_LIBRARIES ${${KIT}_TARGET_LIBRARIES}
  )
